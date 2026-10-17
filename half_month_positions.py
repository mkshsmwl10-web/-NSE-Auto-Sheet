"""Persistent PAPER-signal ledger for the half-month scanner.

History is the source of truth and is never cleared by scheduled runs.
Users can manually set History column L to SELL to close a PAPER holding,
and optionally record exit date/price in columns M/N.
"""
import calendar
from datetime import date, timedelta

import pandas as pd
import gspread

HISTORY_TAB="HalfMonth History"
HOLDINGS_TAB="HalfMonth Holdings"
HISTORY_HEADER=[
    "Signal ID","Half Start","Half End","Type","Sector / Theme","Name",
    "NSE Code","Trigger Date","Paper Entry","Qty","Record Source",
    "Status (OPEN/SELL)","Sell Date","Sell Price","Notes"
]
HOLDING_HEADER=[
    "Position ID","NSE Code","Type","Name","Sector / Theme","First Half",
    "Latest Trigger","Avg Buy Price","Total Qty","Invested ₹","CMP",
    "Price Date","Current Value ₹","P/L ₹","P/L %","Status / Action",
    "Target Price +10%","Target Profit ₹","Book Qty 50%"
]

def half_window(d):
    if d.day<=15:
        return date(d.year,d.month,1),date(d.year,d.month,15)
    return date(d.year,d.month,16),date(d.year,d.month,
                                        calendar.monthrange(d.year,d.month)[1])


def reference_window(start):
    return half_window(start-timedelta(days=1))


def historic_signal(item,df,start,end,today,source):
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
    qty=int(5000//level)
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


def persist_paper_signals(book,watchlist,market_data,today,verified_symbols=None):
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
        signal=historic_signal(item,df,start,end,today,"CURRENT OHLC (PAPER)")
        if signal is not None:
            pending.append(signal)
            existing.add(key)
    pending.sort(key=lambda row:(row[7],row[6]))
    if pending:
        history.append_rows(pending,value_input_option="RAW",
                            insert_data_option="INSERT_ROWS")
    # Re-read after append so manually edited SELL states are honored.
    raw=history.get_all_values()
    open_rows=[]
    for line in raw[1:]:
        row=(line+[""]*len(HISTORY_HEADER))[:len(HISTORY_HEADER)]
        if not row[0] or not row[6]:continue
        if row[11].strip().upper()=="SELL":continue
        if row[11].strip().upper() not in ("","OPEN"):
            print("Holdings status needs OPEN/SELL:",row[0],row[11])
            continue
        try:
            qty=int(float(str(row[9]).replace(",","")))
            entry=float(str(row[8]).replace(",",""))
            if qty<=0 or entry<=0:continue
        except (TypeError,ValueError):continue
        df=market_data.get(row[6])
        cmp_value="";price_date="";current="";pnl="";pct=""
        status="OPEN | PRICE UNAVAILABLE"
        invested=round(qty*entry,2)
        if df is not None and not df.empty:
            latest=df.iloc[-1]
            cmp_value=round(float(latest["Close"]),2)
            price_date=str(df.index[-1].date())
            current=round(qty*cmp_value,2)
            pnl=round(current-invested,2)
            pct=round(100*pnl/invested,2)
            status="OPEN"
            if (today-df.index[-1].date()).days>3:
                status="OPEN | STALE PRICE"
        if status=="OPEN":
            if pct>=10:
                status="OPEN | REVIEW PARTIAL BOOKING"
            elif pct>=5:
                status="OPEN | REVIEW PROFIT"
            elif pct<=-7:
                status="OPEN | REVIEW RISK"
            else:
                status="OPEN | HOLD / MONITOR"
        open_rows.append([
            row[0],row[6],row[3],row[5],row[4],row[1],row[7],
            entry,qty,invested,cmp_value,price_date,current,pnl,pct,status
        ])
    # Consolidate all OPEN paper lots of the SAME NSE symbol into one row.
    # History stays untouched and remains the per-purchase audit trail.
    lot_count=len(open_rows)
    by_symbol={}
    for lot in open_rows:
        sym=lot[1]
        if sym not in by_symbol:
            by_symbol[sym]=[]
        by_symbol[sym].append(lot)
    cumulative=[]
    for sym,lots in by_symbol.items():
        first=lots[0]
        qty=sum(int(x[8]) for x in lots)
        invested=round(sum(float(x[9]) for x in lots),2)
        avg=round(invested/qty,4) if qty else 0
        # All lots of one NSE symbol refer to the same latest market quote.
        latest_quote=max((x for x in lots if isinstance(x[10],(int,float))),
                         key=lambda x:str(x[11]),default=None)
        cmp=latest_quote[10] if latest_quote else ""
        price_date=latest_quote[11] if latest_quote else ""
        value=round(qty*cmp,2) if latest_quote else ""
        pnl=round(value-invested,2) if latest_quote else ""
        pct=round(100*pnl/invested,2) if latest_quote and invested else ""
        status="OPEN | PRICE UNAVAILABLE"
        if latest_quote:
            status="OPEN | HOLD / MONITOR"
            if "STALE" in str(latest_quote[15]):
                status="OPEN | STALE PRICE"
            elif pct>=10:
                status="OPEN | REVIEW PARTIAL BOOKING"
            elif pct>=5:
                status="OPEN | REVIEW PROFIT"
            elif pct<=-7:
                status="OPEN | REVIEW RISK"
        cumulative.append([
            "TOTAL:"+sym,sym,first[2],first[3],first[4],
            min(str(x[5]) for x in lots),
            max(str(x[6]) for x in lots),
            avg,qty,invested,cmp,price_date,value,pnl,pct,status
        ])
    # Indicative targets on cumulative average cost, not automatic exit orders.
    # Target Profit is the whole position's hypothetical gain at target price.
    # Partial booking rounds DOWN to whole units; a 1-unit lot cannot be halved.
    for position in cumulative:
        q=int(position[8])
        target=round(float(position[7])*1.10+0.00000001,2)
        potential=round(target*q-float(position[9]),2)
        book_qty=q//2
        position.extend([target,potential,book_qty])
    open_rows=cumulative
    open_rows.sort(key=lambda r:(r[5],r[1]))
    holdings=_tab(book,HOLDINGS_TAB,len(HOLDING_HEADER))
    holdings.clear()
    holdings.resize(rows=max(100,len(open_rows)+10),cols=len(HOLDING_HEADER))
    invested_total=round(sum(float(x[9]) for x in open_rows),2)
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
        ["PROFIT PLAN","Target = average buy x 1.10; target profit = whole holding gain; book qty = floor(50% of units). Review only, no auto sell."],
        ["DATA NOTE","Individual paper lots="+str(lot_count)+"; unpriced positions="+str(len(open_rows)-len(priced))+
         "; excludes fees and taxes. Consult risk and asset allocation before selling."],
        [""],
        HOLDING_HEADER,
    ]
    holdings.update(summary+open_rows,
                    range_name="A1:S"+str(len(summary)+len(open_rows)),
                    value_input_option="RAW")
    for tab,width in [(history,"A1:O1"),(holdings,"A7:S7")]:
        tab.freeze(rows=1)
        tab.format(width,{"backgroundColor":{"red":0.10,"green":0.25,"blue":0.36},
                "textFormat":{"bold":True,"foregroundColor":{
                    "red":1,"green":1,"blue":1}},"wrapStrategy":"WRAP"})
    holdings.freeze(rows=7,cols=0)
    if open_rows:
        holdings.format("H8:S"+str(len(open_rows)+7),{
            "numberFormat":{"type":"NUMBER","pattern":"#,##0.00"}})
        holdings.format("A8:S"+str(len(open_rows)+7),{
            "verticalAlignment":"MIDDLE"})
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
                     "startColumnIndex":0,"endColumnIndex":19},
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
            "cell":{"userEnteredFormat":{"backgroundColor":pale_gold,
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
    for tab,col_widths in [(holdings,{0:215,1:120,3:215,4:150,5:115,6:115,11:115,15:220,16:150,17:150,18:135}),
                            (history,{0:215,4:150,5:215,6:120,10:205,11:165,14:340})]:
        for col,width in col_widths.items():
            requests.append({"updateDimensionProperties":{
                "range":{"sheetId":tab.id,"dimension":"COLUMNS",
                         "startIndex":col,"endIndex":col+1},
                "properties":{"pixelSize":width},"fields":"pixelSize"}})
    for i in range(0,len(requests),90):
        book.batch_update({"requests":requests[i:i+90]})
    print("HalfMonth History:",len(raw)-1,"recorded paper signals;",
          len(pending),"new; Holdings:",len(open_rows),"unique open symbols from",lot_count,"paper lots")
    return {"new":len(pending),"holdings":len(open_rows)}
