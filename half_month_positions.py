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
    "Signal ID","NSE Code","Type","Name","Sector / Theme","Half Start",
    "Trigger Date","Paper Entry","Qty","Invested ₹","CMP",
    "Price Date","Current Value ₹","P/L ₹","P/L %","Status / Action"
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
    if qty<2:return None
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


def persist_paper_signals(book,watchlist,market_data,today):
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
    old_start,old_end=half_window(start-timedelta(days=1))
    pending=[]
    for item in watchlist:
        df=market_data.get(item[3])
        for pstart,pend,source in [
            (old_start,old_end,"RECONSTRUCTED OHLC (PAPER)"),
            (start,end,"CURRENT OHLC (PAPER)")]:
            key=str(pstart)+":"+item[3]
            if key in existing:continue
            signal=historic_signal(item,df,pstart,pend,today,source)
            if signal is not None:
                pending.append(signal)
                existing.add(key)
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
        open_rows.append([
            row[0],row[6],row[3],row[5],row[4],row[1],row[7],
            entry,qty,invested,cmp_value,price_date,current,pnl,pct,status
        ])
    open_rows.sort(key=lambda r:(r[5],r[1]))
    holdings=_tab(book,HOLDINGS_TAB,len(HOLDING_HEADER))
    holdings.clear()
    holdings.resize(rows=max(100,len(open_rows)+3),cols=len(HOLDING_HEADER))
    holdings.update([HOLDING_HEADER]+open_rows,
                    range_name="A1:P"+str(len(open_rows)+1),
                    value_input_option="RAW")
    for tab,width in [(history,"A1:O1"),(holdings,"A1:P1")]:
        tab.freeze(rows=1)
        tab.format(width,{"backgroundColor":{"red":0.10,"green":0.25,"blue":0.36},
                "textFormat":{"bold":True,"foregroundColor":{
                    "red":1,"green":1,"blue":1}},"wrapStrategy":"WRAP"})
    if open_rows:
        holdings.format("H2:O"+str(len(open_rows)+1),{
            "numberFormat":{"type":"NUMBER","pattern":"#,##0.00"}})
        holdings.format("A2:P"+str(len(open_rows)+1),{
            "verticalAlignment":"MIDDLE"})
    print("HalfMonth History:",len(raw)-1,"recorded paper signals;",
          len(pending),"new; Holdings:",len(open_rows),"open paper lots")
    return len(pending),len(open_rows)
