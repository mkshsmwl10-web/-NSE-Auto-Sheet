"""Persistent PAPER-signal ledger for the half-month scanner.

History is the source of truth and is never cleared by scheduled runs.
Users can manually set History column L to SELL to close a PAPER holding,
and record exit date/price in columns M/N to calculate booked paper profit.
"""
import calendar
import math
from decimal import Decimal, ROUND_CEILING
from datetime import date, timedelta

import pandas as pd
import gspread

HISTORY_TAB="HalfMonth History"
HOLDINGS_TAB="HalfMonth Holdings"
REALIZED_TAB="HalfMonth Realized"
REALIZED_HEADER=["NSE Code","Type","Name","SELL Records","Sold Qty",
                 "Sold Cost ₹","Sale Proceeds ₹","Realized P/L ₹",
                 "Last Sell Date","Pending SELL Records","Open Qty","Status"]
HISTORY_HEADER=[
    "Signal ID","Half Start","Half End","Type","Sector / Theme","Name",
    "NSE Code","Trigger Date","Paper Entry","Qty","Record Source",
    "Status (OPEN/SELL)","Sell Date","Sell Price","Notes"
]
HOLDING_HEADER=[
    "Position ID","NSE Code","Type","Name","Sector / Theme","First Half",
    "Latest Trigger","Avg Buy Price","Total Qty","Invested ₹","CMP",
    "Price Date","Current Value ₹","P/L ₹","P/L %","Status / Action",
    "Target Price","Target Profit ₹","Exit Qty (Target Hit)",
    "Target %","Realized P/L ₹","Total P/L ₹"
]

def _positive(value):
    try:
        number=float(str(value).replace(",", "").replace("₹", "").strip())
        return number if math.isfinite(number) and number>0 else None
    except (TypeError, ValueError):
        return None


def build_portfolio(records, market_data, today):
    """Derive cumulative OPEN lots and booked SELL P/L without editing the ledger.

    SELL closes a complete history lot. Missing/invalid exit details stay pending;
    neither CMP nor the profit target is ever substituted for an execution price.
    Amounts are gross PAPER accounting, not broker/tax FIFO accounting.
    """
    groups={}
    for line in records:
        row=(list(line)+[""]*len(HISTORY_HEADER))[:len(HISTORY_HEADER)]
        symbol=str(row[6]).strip().upper()
        state=str(row[11]).strip().upper()
        if not row[0] or not symbol or state not in ("", "OPEN", "SELL"):
            continue  # INVALID DATA and other archived states stay excluded.
        group=groups.setdefault(symbol,{"first":row,"open":[],"sells":0,
                    "pending":0,"sold_qty":0,"cost":0.,"proceeds":0.,"dates":[]})
        qty=_positive(row[9]); entry=_positive(row[8])
        if state=="SELL":
            group["sells"]+=1
            exit_price=_positive(row[13])
            try:
                exit_day=date.fromisoformat(str(row[12]).strip())
                entry_day=date.fromisoformat(str(row[7]).strip())
                dates_valid=entry_day<=exit_day<=today
            except (ValueError,TypeError):
                dates_valid=False
            if not qty or not qty.is_integer() or not entry or not exit_price or not dates_valid:
                group["pending"]+=1
                continue
            group["sold_qty"]+=int(qty)
            group["cost"]+=entry*qty
            group["proceeds"]+=exit_price*qty
            group["dates"].append(exit_day.isoformat())
        elif qty and qty.is_integer() and entry:
            group["open"].append((row,int(qty),entry))

    holdings=[]; booked=[]; realized_total=0.; pending_total=0; lot_count=0
    for symbol,group in groups.items():
        first=group["first"]; lots=group["open"]
        realized=round(group["proceeds"]-group["cost"],2)
        realized_total+=realized; pending_total+=group["pending"]
        qty=sum(lot[1] for lot in lots)
        if group["sells"]:
            booked.append([symbol,first[3],first[5],group["sells"],group["sold_qty"],
                           round(group["cost"],2),round(group["proceeds"],2),realized,
                           max(group["dates"],default=""),group["pending"],qty,
                           "PENDING EXIT DETAILS" if group["pending"] else "BOOKED | GROSS PAPER P/L"])
        if not lots:
            continue
        lot_count+=len(lots)
        first=lots[0][0]
        invested=round(sum(lot[1]*lot[2] for lot in lots),2)
        average=invested/qty
        target_pct=15 if str(first[3]).strip().upper()=="STOCK" else 8
        target=float((Decimal(str(invested))/Decimal(qty)*
                      (Decimal(1)+Decimal(target_pct)/100)).quantize(Decimal("0.01"),rounding=ROUND_CEILING))
        cmp=""; quote_day=""; value=""; pnl=""; pct=""
        status="OPEN | PRICE UNAVAILABLE"
        frame=market_data.get(symbol)
        if frame is not None and not frame.empty:
            # Ignore future, missing, zero and non-finite prices.
            for stamp,bar in frame.sort_index(ascending=False).iterrows():
                day=pd.Timestamp(stamp).date()
                price=_positive(bar.get("Close"))
                if day<=today and price:
                    cmp=round(price,2); quote_day=day.isoformat()
                    value=round(qty*cmp,2); pnl=round(value-invested,2)
                    pct=round(100*pnl/invested,2)
                    status="OPEN | HOLD / MONITOR"
                    if (today-day).days>3:
                        status="OPEN | STALE PRICE"
                    elif cmp>=target:
                        status="TARGET HIT | EXIT ALERT (FULL QTY)"
                    elif pct<=-7:
                        status="OPEN | REVIEW RISK"
                    break
        total=round(realized+pnl,2) if isinstance(pnl,(float,int)) else ""
        holdings.append(["TOTAL:"+symbol,symbol,first[3],first[5],first[4],
                         min(str(lot[0][1]) for lot in lots),max(str(lot[0][7]) for lot in lots),
                         round(average,4),qty,invested,cmp,quote_day,value,pnl,pct,status,
                         target,round(target*qty-invested,2),qty if "TARGET HIT" in status else 0,
                         target_pct,realized,total])
    holdings.sort(key=lambda row:(row[5],row[1])); booked.sort(key=lambda row:row[0])
    return holdings,booked,{"open_lots":lot_count,"invested":round(sum(row[9] for row in holdings),2),
                            "realized":round(realized_total,2),"pending_sells":pending_total}

def half_window(d):
    if d.day<=15:
        return date(d.year,d.month,1),date(d.year,d.month,15)
    return date(d.year,d.month,16),date(d.year,d.month,
                                        calendar.monthrange(d.year,d.month)[1])


def reference_window(start):
    return half_window(start-timedelta(days=1))


def historic_signal(item,df,start,end,today,source,budget=5000):
    """Reconstruct a model trigger ONLY from historical OHLC evidence."""
    if df is None or df.empty:return None
    kind,sector,name,symbol=item
    ref_start,ref_end=reference_window(start)
    ref=df[(df.index.date>=ref_start)&(df.index.date<=ref_end)]
    bars=df[(df.index.date>=start)&(df.index.date<=min(end,today))]
    # Do not backfill on inadequate reference history.
    if len(ref)<5 or bars.empty:return None
    high=float(ref["High"].max())
    low=float(ref["Low"].min())
    level=round(high if kind=="STOCK" else low,2)
    if level<=0:return None
    qty=int(budget//level)
    if qty<1:return None
    hits=(bars[bars["High"]>high] if kind=="STOCK"
          else bars[bars["Low"]<low])
    if hits.empty:return None
    signal_date=hits.index[0].date()
    key=str(start)+":"+symbol
    return [key,str(start),str(end),kind,sector,name,symbol,
            str(signal_date),level,qty,source,"OPEN","","",
            "PAPER signal only; not a confirmed executed trade"]


def _tab(book,title,columns):
    try:tab=book.worksheet(title)
    except gspread.WorksheetNotFound:
        tab=book.add_worksheet(title=title,rows=200,cols=columns)
    if tab.col_count<columns:tab.resize(cols=columns)
    return tab


def persist_paper_signals(book,watchlist,market_data,today,verified_symbols=None,budgets=None):
    """Append-only history, derived live holdings, never lose prior halves."""
    history=_tab(book,HISTORY_TAB,len(HISTORY_HEADER))
    raw=history.get_all_values()
    if not raw or not any(str(x).strip() for x in raw[0]):
        history.update([HISTORY_HEADER],range_name="A1:O1",
                       value_input_option="RAW")
        raw=[HISTORY_HEADER]
    elif raw[0][:len(HISTORY_HEADER)]!=HISTORY_HEADER:
        raise ValueError("HalfMonth History columns changed. Existing ledger preserved; fix headers before rerun.")
    existing={str(row[0]).strip() for row in raw[1:] if row and row[0]}
    start,end=half_window(today)
    # No monthly cap. Record every valid PAPER signal from the current half,
    # at most once per symbol and period. Existing history is append-only.
    # Don't retrospectively create trades in prior half periods.
    pending=[]
    for item in watchlist:
        if verified_symbols is not None and item[3] not in verified_symbols:
            print("UNVERIFIED: suppressing new paper buy",item[3])
            continue
        df=market_data.get(item[3])
        key=str(start)+":"+item[3]
        if key in existing:continue
        signal=historic_signal(item,df,start,end,today,"CURRENT OHLC (PAPER)",
                               budget=(budgets or {}).get(item[3],5000))
        if signal is not None:
            pending.append(signal)
            existing.add(key)
    pending.sort(key=lambda row:(row[7],row[6]))
    if pending:
        history.append_rows(pending,value_input_option="RAW",
                            insert_data_option="INSERT_ROWS")
    # Re-read after append so manually edited SELL states are honored.
    raw=history.get_all_values()
    open_rows, realized_rows, metrics = build_portfolio(raw[1:], market_data, today)
    lot_count=metrics["open_lots"]
    holdings=_tab(book,HOLDINGS_TAB,len(HOLDING_HEADER))
    holdings.clear()
    holdings.resize(rows=max(holdings.row_count,100,len(open_rows)+10),cols=len(HOLDING_HEADER))
    invested_total=metrics["invested"]
    priced=[x for x in open_rows if isinstance(x[12],(float,int))]
    priced_invested=round(sum(float(x[9]) for x in priced),2)
    market_value=round(sum(float(x[12]) for x in priced),2)
    unrealized=round(market_value-priced_invested,2)
    return_pct=round(100*unrealized/priced_invested,2) if priced_invested else 0
    winners=sum(1 for x in priced if x[13]>0)
    losers=sum(1 for x in priced if x[13]<0)
    summary=[
        ["HALF-MONTH HOLDINGS | PAPER PORTFOLIO","Illustrative signals, not broker trades"],
        ["INVESTED CAPITAL","","MARKET VALUE","","UNREALIZED P/L","","RETURN %","","SYMBOLS HELD","","PROFIT SYMBOLS","","LOSS SYMBOLS"],
        [invested_total,"",market_value,"",unrealized,"",return_pct,"",len(open_rows),"",winners,"",losers],
        ["PROFIT PLAN","Stock target 15%; ETF target 8% on cumulative average cost. TARGET HIT = full-position EXIT ALERT; no automatic sale."],
        ["DATA NOTE","Paper lots="+str(lot_count)+"; unpriced="+str(len(open_rows)-len(priced))+
         "; SELL needs M=Sell Date and N=Sell Price. L=SELL closes the entire history lot; excludes fees and taxes."],
        [""],
        HOLDING_HEADER,
    ]
    summary[1].extend(["", "REALIZED P/L", "", "TOTAL P/L", "", "SELL PENDING", "", "TARGET HITS"])
    summary[2].extend(["", metrics["realized"], "", round(unrealized+metrics["realized"],2), "", metrics["pending_sells"], "", sum("TARGET HIT" in row[15] for row in open_rows)])
    holdings.update(summary+open_rows,
                    range_name="A1:V"+str(len(summary)+len(open_rows)),
                    value_input_option="RAW")
    for tab,width in [(history,"A1:O1"),(holdings,"A7:V7")]:
        tab.freeze(rows=1)
        tab.format(width,{"backgroundColor":{"red":0.10,"green":0.25,"blue":0.36},
                "textFormat":{"bold":True,"foregroundColor":{
                    "red":1,"green":1,"blue":1}},"wrapStrategy":"WRAP"})
    holdings.freeze(rows=7,cols=1)
    if open_rows:
        holdings.format("H8:V"+str(len(open_rows)+7),{
            "numberFormat":{"type":"NUMBER","pattern":"#,##0.00"}})
        holdings.format("A8:V"+str(len(open_rows)+7),{
            "verticalAlignment":"MIDDLE"})
    # Whole quantities/counts and calendar dates are not money values.
    for column in ("I", "S", "T"):
        if open_rows:
            holdings.format(f"{column}8:{column}{len(open_rows)+7}",{
                "numberFormat":{"type":"NUMBER","pattern":"0"}})
    # Persistent color styling: reapplied after every scanner run.
    navy={"red":0.10,"green":0.25,"blue":0.36}
    white={"red":1,"green":1,"blue":1}
    dark={"red":0.13,"green":0.22,"blue":0.32}
    pale_blue={"red":0.91,"green":0.96,"blue":1}
    pale_mint={"red":0.90,"green":0.98,"blue":0.94}
    pale_red={"red":1,"green":0.91,"blue":0.91}
    pale_gold={"red":1,"green":0.96,"blue":0.83}
    requests=[]
    for idx,row in enumerate(open_rows,start=7):
        positive=isinstance(row[13],(float,int)) and row[13]>=0
        bg=pale_mint if positive else pale_red
        if not isinstance(row[13],(float,int)):bg=pale_gold
        requests.append({"repeatCell":{
            "range":{"sheetId":holdings.id,"startRowIndex":idx,"endRowIndex":idx+1,
                     "startColumnIndex":0,"endColumnIndex":22},
            "cell":{"userEnteredFormat":{"backgroundColor":
                pale_blue if idx%2 else {"red":0.95,"green":0.97,"blue":0.99},
                "textFormat":{"foregroundColor":dark}}},
            "fields":"userEnteredFormat.backgroundColor,userEnteredFormat.textFormat"}})
        requests.append({"repeatCell":{
            "range":{"sheetId":holdings.id,"startRowIndex":idx,"endRowIndex":idx+1,
                     "startColumnIndex":13,"endColumnIndex":15},
            "cell":{"userEnteredFormat":{"backgroundColor":bg,
                "textFormat":{"bold":True,"foregroundColor":
                    {"red":0.05,"green":0.40,"blue":0.24} if positive
                    else {"red":0.71,"green":0.15,"blue":0.20}}}},
            "fields":"userEnteredFormat.backgroundColor,userEnteredFormat.textFormat"}})
        requests.append({"repeatCell":{
            "range":{"sheetId":holdings.id,"startRowIndex":idx,"endRowIndex":idx+1,
                     "startColumnIndex":15,"endColumnIndex":16},
            "cell":{"userEnteredFormat":{"backgroundColor":pale_mint if "TARGET HIT" in row[15] else pale_gold,
                "textFormat":{"bold":True,"foregroundColor":dark}}},
            "fields":"userEnteredFormat.backgroundColor,userEnteredFormat.textFormat"}})
    requests.extend([
        {"repeatCell":{
            "range":{"sheetId":holdings.id,"startRowIndex":0,"endRowIndex":2},
            "cell":{"userEnteredFormat":{"backgroundColor":navy,
                "textFormat":{"bold":True,"foregroundColor":white,"fontSize":12}}},
            "fields":"userEnteredFormat.backgroundColor,userEnteredFormat.textFormat"}},
        {"repeatCell":{
            "range":{"sheetId":holdings.id,"startRowIndex":2,"endRowIndex":3},
            "cell":{"userEnteredFormat":{
                "backgroundColor":pale_mint if unrealized>=0 else pale_red,
                "textFormat":{"bold":True,"foregroundColor":dark,"fontSize":14},
                "numberFormat":{"type":"NUMBER","pattern":"#,##0.00"}}},
            "fields":"userEnteredFormat"}},
        {"repeatCell":{
            "range":{"sheetId":holdings.id,"startRowIndex":3,"endRowIndex":5},
            "cell":{"userEnteredFormat":{"backgroundColor":pale_gold,
                "textFormat":{"bold":True,"foregroundColor":dark}}},
            "fields":"userEnteredFormat.backgroundColor,userEnteredFormat.textFormat"}},
        {"updateDimensionProperties":{
            "range":{"sheetId":holdings.id,"dimension":"ROWS","startIndex":2,"endIndex":3},
            "properties":{"pixelSize":36},"fields":"pixelSize"}},
        {"updateDimensionProperties":{
            "range":{"sheetId":holdings.id,"dimension":"ROWS","startIndex":3,"endIndex":5},
            "properties":{"pixelSize":30},"fields":"pixelSize"}}
    ])
    for idx,row in enumerate(raw[1:],start=1):
        if not row or not row[0]:continue
        closed=len(row)>11 and str(row[11]).strip().upper()=="SELL"
        bg=pale_red if closed else pale_mint if idx%2 else pale_blue
        requests.append({"repeatCell":{
            "range":{"sheetId":history.id,"startRowIndex":idx,"endRowIndex":idx+1,
                     "startColumnIndex":0,"endColumnIndex":15},
            "cell":{"userEnteredFormat":{"backgroundColor":bg,
                "textFormat":{"foregroundColor":dark}}},
            "fields":"userEnteredFormat.backgroundColor,userEnteredFormat.textFormat"}})
        requests.append({"repeatCell":{
            "range":{"sheetId":history.id,"startRowIndex":idx,"endRowIndex":idx+1,
                     "startColumnIndex":11,"endColumnIndex":12},
            "cell":{"userEnteredFormat":{"textFormat":{"bold":True,
                "foregroundColor":{"red":0.66,"green":0.15,"blue":0.17} if closed
                   else {"red":0.07,"green":0.42,"blue":0.26}}}},
            "fields":"userEnteredFormat.textFormat"}})
    for tab,col_widths in [(holdings,{0:215,1:120,3:215,4:150,5:115,6:115,11:115,15:220,16:150,17:150,18:160,19:100,20:155,21:155}),
                            (history,{0:215,4:150,5:215,6:120,10:205,11:165,14:340})]:
        for col,width in col_widths.items():
            requests.append({"updateDimensionProperties":{
                "range":{"sheetId":tab.id,"dimension":"COLUMNS",
                         "startIndex":col,"endIndex":col+1},
                "properties":{"pixelSize":width},"fields":"pixelSize"}})
    # Dedicated per-symbol report retains profits after the last open lot is sold.
    booked=_tab(book,REALIZED_TAB,len(REALIZED_HEADER))
    booked.clear()
    booked.resize(rows=max(booked.row_count,100,len(realized_rows)+8),cols=len(REALIZED_HEADER))
    booked.update([REALIZED_HEADER]+realized_rows,
                  range_name="A1:L"+str(len(realized_rows)+1),value_input_option="RAW")
    booked.freeze(rows=1)
    booked.format("A1:L1",{"backgroundColor":navy,"textFormat":{"bold":True,"foregroundColor":white},"wrapStrategy":"WRAP"})
    if realized_rows:
        booked.format("E2:H"+str(len(realized_rows)+1),{"numberFormat":{"type":"NUMBER","pattern":"#,##0.00"}})
    requests.extend([
        {"updateDimensionProperties":{"range":{"sheetId":booked.id,"dimension":"COLUMNS","startIndex":0,"endIndex":12},"properties":{"pixelSize":145},"fields":"pixelSize"}},
        {"updateDimensionProperties":{"range":{"sheetId":booked.id,"dimension":"COLUMNS","startIndex":2,"endIndex":3},"properties":{"pixelSize":215},"fields":"pixelSize"}},
        {"updateDimensionProperties":{"range":{"sheetId":booked.id,"dimension":"COLUMNS","startIndex":11,"endIndex":12},"properties":{"pixelSize":310},"fields":"pixelSize"}},
    ])
    for i in range(0,len(requests),90):
        book.batch_update({"requests":requests[i:i+90]})
    print("HalfMonth History:",len(raw)-1,"recorded paper signals;",
          len(pending),"new; Holdings:",len(open_rows),"unique open symbols from",lot_count,"paper lots")
    return {"new":len(pending),"holdings":len(open_rows)}

