#!/usr/bin/env python3
"""Half-month breakout scanner, independent of update_sheet.py.

An editable Google worksheet controls the user-selected ETF/stock universe.
1st-15th: collect reference High/Low (inclusive).
16th-month end: stock buys above reference High; ETF buys below reference Low.
Daily candle High/Low detects a touch; CMP records the latest available Close.
"""
import calendar
import math
import io
import requests
import json
import os
import re
import time
from datetime import date, timedelta

import gspread
import pandas as pd
import yfinance as yf
from google.oauth2.service_account import Credentials
from half_month_positions import persist_paper_signals

SHEET_ID = os.getenv("SPREADSHEET_ID", "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E")
WATCHLIST_TAB = os.getenv("HALF_MONTH_WATCHLIST", "HalfMonth Watchlist")
SIGNALS_TAB = os.getenv("HALF_MONTH_SIGNALS", "HalfMonth Signals")
WATCH_COLS = ["Type", "Sector / Theme", "Name", "NSE Code"]
RESULT_COLS = [
    "Type", "Sector / Theme", "Name", "NSE Code", "Strategy",
    "Previous Half High", "Previous Half Low", "BUY Level", "CMP", "Today High", "Today Low",
    "BUY Status", "Price Date", "Valid From", "Valid Till",
    "Budget", "Planned Qty", "Trigger Date", "Paper Entry",
    "Invested", "Current Value", "P/L Rs", "P/L %"
]
BUDGET = 5000

# Editable starter set. These are representatives, not a quantitative
# assertion that any one company is the permanent sector leader.
DEFAULT_WATCHLIST = [
    ("ETF", "Nifty 50", "Nifty BeES", "NIFTYBEES"),
    ("ETF", "Banking", "Bank BeES", "BANKBEES"),
    ("ETF", "Midcap 150", "Midcap 150 BeES", "MID150BEES"),
    ("ETF", "Sensex", "ICICI Prudential BSE Sensex ETF", "SENSEXIETF"),
    ("ETF", "Silver", "Silver BeES", "SILVERBEES"),
    ("ETF", "Gold", "Gold BeES", "GOLDBEES"),
    ("ETF", "Smallcap 250", "HDFC Smallcap 250 ETF", "HDFCSML250"),
    ("ETF", "Hang Seng", "Hang Seng BeES", "HNGSNGBEES"),
    ("ETF", "Nasdaq 100", "Motilal Oswal Nasdaq 100 ETF", "MON100"),
    ("STOCK", "Private Banking", "HDFC Bank", "HDFCBANK"),
    ("STOCK", "PSU Banking", "State Bank of India", "SBIN"),
    ("STOCK", "IT Services", "TCS", "TCS"),
    ("STOCK", "Energy / Oil", "Reliance Industries", "RELIANCE"),
    ("STOCK", "Telecom", "Bharti Airtel", "BHARTIARTL"),
    ("STOCK", "Capital Goods / Infra", "Larsen & Toubro", "LT"),
    ("STOCK", "Auto", "Maruti Suzuki", "MARUTI"),
    ("STOCK", "Pharma", "Sun Pharma", "SUNPHARMA"),
    ("STOCK", "FMCG", "Hindustan Unilever", "HINDUNILVR"),
    ("STOCK", "Metals", "Tata Steel", "TATASTEEL"),
    ("STOCK", "Cement", "UltraTech Cement", "ULTRACEMCO"),
    ("STOCK", "Power Utilities", "Power Grid", "POWERGRID"),
    ("STOCK", "Retail", "Trent", "TRENT"),
    ("STOCK", "NBFC", "Bajaj Finance", "BAJFINANCE"),
    ("STOCK", "Jewellery / Lifestyle", "Titan", "TITAN"),
    ("STOCK", "Defence", "Bharat Electronics", "BEL"),
    ("STOCK", "Real Estate", "DLF", "DLF"),
    ("STOCK", "Specialty Chemicals", "Pidilite", "PIDILITIND"),
    ("STOCK", "Hospitals", "Apollo Hospitals", "APOLLOHOSP"),
    ("STOCK", "Hotels", "Indian Hotels", "INDHOTEL"),
]


def open_book():
    raw = os.environ["GCP_CREDENTIALS"].strip()
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = (Credentials.from_service_account_info(json.loads(raw), scopes=scopes)
             if raw.startswith("{") else
             Credentials.from_service_account_file(raw, scopes=scopes))
    return gspread.authorize(creds).open_by_key(SHEET_ID)


def worksheet(book, name, cols):
    try:
        return book.worksheet(name)
    except gspread.WorksheetNotFound:
        return book.add_worksheet(title=name, rows=100, cols=cols)


def get_watchlist(book):
    ws = worksheet(book, WATCHLIST_TAB, len(WATCH_COLS))
    raw = ws.get_all_values()
    # A newly created tab may return [], [[]], blank rows, or headers only.
    # Seed the starter universe only when there are no meaningful user rows.
    normalized = [[str(x).strip() for x in row] for row in raw]
    meaningful = [row for row in normalized if any(row)]
    header = [x.lower() for x in WATCH_COLS]
    has_header = bool(meaningful and
                      [x.lower() for x in meaningful[0][:4]] == header)

    if not meaningful or (has_header and len(meaningful) == 1):
        seeded = [WATCH_COLS] + [list(row) for row in DEFAULT_WATCHLIST]
        ws.resize(rows=max(ws.row_count, len(seeded) + 1), cols=4)
        ws.update(seeded, range_name="A1:D" + str(len(seeded)),
                  value_input_option="RAW")
        ws.freeze(rows=1)
        meaningful = seeded
        has_header = True
        print("Initialized editable watchlist with", len(DEFAULT_WATCHLIST), "symbols")

    # Migrate the one approved ETF ticker on existing editable watchlists.
    for i, row in enumerate(raw[1:], start=2):
        if len(row) >= 4 and str(row[3]).strip().upper() == "SENSEXBEES":
            ws.update_acell(f"C{i}", "ICICI Prudential BSE Sensex ETF")
            ws.update_acell(f"D{i}", "SENSEXIETF")
            print("Migrated Sensex ETF to SENSEXIETF")
    meaningful = [[str(x).strip() for x in row] for row in ws.get_all_values()
                  if any(str(x).strip() for x in row)]
    items, seen = [], set()
    for row in meaningful[1:] if has_header else meaningful:
        if len(row) < 4:
            continue
        kind, sector, name, symbol = [str(x).strip() for x in row[:4]]
        kind, symbol = kind.upper(), symbol.upper().removesuffix(".NS")
        if kind not in ("ETF", "STOCK") or not re.fullmatch(r"[A-Z0-9&._-]+", symbol):
            continue
        if symbol in seen:
            continue
        items.append((kind, sector, name or symbol, symbol))
        seen.add(symbol)
    if not items:
        raise ValueError(
            "HalfMonth Watchlist has rows but no valid symbols. "
            "Set columns A-D to Type, Sector / Theme, Name, NSE Code; "
            "Type must be ETF or STOCK and NSE Code must be an NSE ticker. "
            "Existing user data was left unchanged."
        )
    return items



def get_sip_budgets(book, watchlist):
    """Read per-symbol planned budgets; REAL allocations come from compounding B.

    This controls new paper plans only. It never creates executed investments.
    Blank/duplicate/invalid REAL configurations must not silently use Rs 5,000.
    """
    raw=book.worksheet(WATCHLIST_TAB).get_all_values()
    linked={str(r[3]).strip().upper():r for r in raw[1:] if len(r)>3}
    budgets={}
    for item in watchlist:
        symbol=item[3]; row=linked.get(symbol,[])
        real=len(row)>5 and str(row[5]).strip().upper()=="REAL"
        if not real:
            budgets[symbol]=BUDGET
            continue
        try:
            value=float(str(row[4]).replace(",", "").replace("₹", "").strip())
        except (ValueError,TypeError,IndexError):
            raise ValueError(f"Invalid/duplicate SIP for {symbol}: check ETF Compounding G/B and Watchlist E")
        if not math.isfinite(value) or value<0:
            raise ValueError(f"SIP must be a finite nonnegative amount: {symbol}")
        budgets[symbol]=value
    return budgets


def fetch_daily(symbol):
    last_error = "empty OHLC"
    for attempt in range(3):
        try:
            df = yf.Ticker(symbol + ".NS").history(period="3mo", interval="1d",
                                                    auto_adjust=False)
            if df is None or df.empty:
                raise ValueError("no daily NSE OHLC")
            df = df[["High", "Low", "Close"]].dropna().copy()
            df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
            df = df[~df.index.duplicated(keep="last")].sort_index()
            if df.empty:
                raise ValueError("no valid OHLC")
            return df, ""
        except Exception as exc:
            last_error = str(exc)
            time.sleep(attempt + 1)
    return None, last_error[:100]


def load_nse_recent(today):
    """Fetch official NSE security-wise daily bhavcopies once for all symbols.

    These are actual NSE daily OHLC records (not live quotes). Only valid
    exchange-published days are accepted; no missing day is fabricated.
    """
    reports={}
    source_dates=[]
    headers={
        "User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
        "Accept":"text/csv,application/csv,text/plain,*/*",
        "Referer":"https://www.nseindia.com/all-reports",
    }
    session=requests.Session()
    session.headers.update(headers)
    # Do not treat a partial in-session candle as final close.
    now_ist=pd.Timestamp.now(tz="Asia/Kolkata")
    latest_day=today if now_ist.hour>=19 else today-timedelta(days=1)
    archive="https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{}.csv"
    for age in range(25):
        day=latest_day-timedelta(days=age)
        if day.weekday()>=5:continue
        url=archive.format(day.strftime("%d%m%Y"))
        try:
            response=session.get(url,timeout=13)
            if response.status_code==404:continue
            response.raise_for_status()
            if len(response.content)<100 or len(response.content)>8000000:
                continue
            table=pd.read_csv(io.BytesIO(response.content),low_memory=False)
            table.columns=[str(c).strip().upper().lstrip("\ufeff") for c in table.columns]
            needed={"SYMBOL","SERIES","HIGH_PRICE","LOW_PRICE","CLOSE_PRICE"}
            if not needed.issubset(table.columns):
                print("NSE fallback unexpected columns:",day,list(table.columns)[:12])
                continue
            table["SYMBOL"]=table["SYMBOL"].astype(str).str.strip().str.upper()
            table["SERIES"]=table["SERIES"].astype(str).str.strip().str.upper()
            table=table[table["SERIES"].isin(("EQ","BE","BZ","SM","ST"))].copy()
            if table.empty:continue
            # Explicit date check if source includes it.
            if "DATE1" in table.columns:
                record_dates=pd.to_datetime(table["DATE1"].astype(str).str.strip(),
                                            errors="coerce",dayfirst=True)
                table=table.loc[record_dates.dt.date==day]
                if table.empty:
                    print("NSE fallback archive date mismatch:",day)
                    continue
            source_dates.append(day)
            for row in table.itertuples(index=False):
                rec=dict(zip(table.columns,row))
                symbol=rec["SYMBOL"]
                try:
                    hi=float(str(rec["HIGH_PRICE"]).replace(",","").strip())
                    lo=float(str(rec["LOW_PRICE"]).replace(",","").strip())
                    close=float(str(rec["CLOSE_PRICE"]).replace(",","").strip())
                except (TypeError,ValueError):
                    continue
                if not (0<lo<=hi and 0<close and lo-0.01<=close<=hi+0.01):
                    continue
                # NSE EQ series is the preferred regular-market record.
                priority=0 if rec["SERIES"]=="EQ" else 1
                old=reports.get((symbol,day))
                if old is None or priority<old[0]:
                    reports[(symbol,day)]=(priority,hi,lo,close)
            print("NSE full bhavcopy confirmed:",day,"symbols:",len(table))
        except (requests.RequestException,ValueError,pd.errors.ParserError,
                UnicodeError) as exc:
            print("NSE bhavcopy unavailable:",day,str(exc)[:120])
    session.close()
    print("NSE fallback available trading days:",len(source_dates),
          "most recent:",max(source_dates) if source_dates else "NONE")
    return reports,(max(source_dates) if source_dates else None)


def merge_nse_recent(df,symbol,reports):
    """Append genuinely newer NSE daily OHLC; don't overwrite Yahoo bars."""
    matched=sorted([(d,ohlc) for (sym,d),ohlc in reports.items() if sym==symbol])
    if not matched:return df,0
    rows=[[pd.Timestamp(d),ohlc[1],ohlc[2],ohlc[3]] for d,ohlc in matched]
    archive=pd.DataFrame(rows,columns=["Date","High","Low","Close"]).set_index("Date")
    if df is None or df.empty:
        return archive, len(archive)
    # NSE archive is the authoritative exchange OHLC. Fill MISSING
    # intermediate dates and replace mismatched Yahoo bars, not just dates
    # newer than Yahoo's final row. Otherwise a missing reference-period
    # low (e.g. 2026-10-15) silently corrupts half-month trigger levels.
    merged=df.copy()
    merged.update(archive)
    missing=archive.loc[~archive.index.isin(merged.index)]
    merged=pd.concat([merged,missing]).sort_index()
    merged=merged[~merged.index.duplicated(keep="last")]
    return merged,len(missing)



def validate_reference(symbol,reports,today):
    """Block buys unless official NSE archive covers the reference half."""
    if today.day<=15:
        end=date(today.year,today.month,1)-timedelta(days=1)
        start=date(end.year,end.month,16)
    else:
        start=date(today.year,today.month,1)
        end=date(today.year,today.month,15)
    weekdays={start+timedelta(days=i) for i in range((end-start).days+1)
              if (start+timedelta(days=i)).weekday()<5}
    archive_days={d for (_sym,d) in reports if start<=d<=end}
    symbol_days={d for (sym,d) in reports if sym==symbol and start<=d<=end}
    missing=archive_days-symbol_days
    archive_gap=weekdays-archive_days
    if missing or len(symbol_days)<7 or len(archive_gap)>2:
        return False, ("DATA UNVERIFIED | NO NEW BUY | NSE ref days "
                       +str(len(symbol_days))+" | missing symbol "
                       +str(len(missing))+" | archive gaps "+str(len(archive_gap)))
    return True, "NSE VERIFIED "+str(len(symbol_days))+" days"


def build_row(item, df, error, today, confirmed_market_day=None, budget=BUDGET):
    kind, sector, name, symbol = item
    if today.day <= 15:
        prev_end = date(today.year, today.month, 1) - timedelta(days=1)
        ref_start = date(prev_end.year, prev_end.month, 16)
        ref_end = prev_end
        valid_from = date(today.year, today.month, 1)
        valid_until = date(today.year, today.month, 15)
    else:
        ref_start = date(today.year, today.month, 1)
        ref_end = date(today.year, today.month, 15)
        valid_from = date(today.year, today.month, 16)
        valid_until = date(today.year, today.month,
                           calendar.monthrange(today.year, today.month)[1])
    base = [kind, sector, name, symbol,
            "BUY ABOVE HIGH" if kind == "STOCK" else "BUY BELOW LOW"]
    labels = [str(valid_from), str(valid_until)]
    empty_position = [budget, "", "", "", "", "", "", ""]
    if error or df is None:
        return base + ["", "", "", "", "", "", "DATA ERROR: " + (error or "no data"),
                       "", *labels, *empty_position]

    df = df[df.index.date <= today]
    if df.empty:
        return base + ["", "", "", "", "", "", "NO CURRENT DATA",
                       "", *labels, *empty_position]
    ref = df[(df.index.date >= ref_start) & (df.index.date <= ref_end)]
    latest = df.iloc[-1]
    quote_date = df.index[-1].date()
    cmp_value = round(float(latest["Close"]), 2)
    day_high = round(float(latest["High"]), 2)
    day_low = round(float(latest["Low"]), 2)
    if ref.empty:
        return base + ["", "", "", cmp_value, day_high, day_low,
                       "NO REFERENCE DATA", str(quote_date), *labels,
                       *empty_position]
    hi = round(float(ref["High"].max()), 2)
    lo = round(float(ref["Low"].min()), 2)
    level = hi if kind == "STOCK" else lo
    qty = int(budget // level) if level > 0 else 0
    valid_bars = df[(df.index.date >= valid_from) &
                    (df.index.date <= min(today, valid_until))]
    hits = (valid_bars[valid_bars["High"] > hi] if kind == "STOCK"
            else valid_bars[valid_bars["Low"] < lo])
    first_hit = hits.index[0].date() if not hits.empty else None
    if quote_date < valid_from:
        status = "AWAITING NEW HALF"
    elif first_hit:
        status = "BUY TRIGGERED"
    else:
        status = "WAIT ABOVE HIGH" if kind == "STOCK" else "WAIT BELOW LOW"
    # Prefer an exchange-confirmed market day. Do not assume holidays traded.
    if confirmed_market_day is not None:
        if quote_date < confirmed_market_day:
            status += " | STALE PRICE"
    elif quote_date < today - timedelta(days=3):
        status += " | STALE PRICE | NSE VERIFY UNAVAILABLE"
    elif quote_date < today-timedelta(days=1) and today.weekday()<5:
        status += " | CHECK PRICE DATE (NSE UNAVAILABLE)"

    # Hypothetical full-share allocation at reference level; not an executed fill.
    # Do not compute paper P/L before entry.
    entry = level if first_hit and qty else ""
    invested = round(qty * level, 2) if first_hit and qty else ""
    current = round(qty * cmp_value, 2) if first_hit and qty else ""
    pnl = round(current - invested, 2) if first_hit and qty else ""
    pnl_pct = round(100 * pnl / invested, 2) if invested != "" and invested else ""
    return base + [hi, lo, level, cmp_value, day_high, day_low,
                   status, str(quote_date), *labels,
                   budget, qty, str(first_hit) if first_hit else "",
                   entry, invested, current, pnl, pnl_pct]


def update_results(book, rows, excluded=0):
    """Refresh a clean, readable 23-column dashboard and its paper positions."""
    ws = worksheet(book, SIGNALS_TAB, len(RESULT_COLS))
    ws.clear()
    ws.resize(rows=max(100, len(rows) + 8), cols=len(RESULT_COLS))
    triggered = [r for r in rows if "BUY TRIGGERED" in r[11] and r[19] != ""]
    invested = round(sum(float(r[19]) for r in triggered), 2)
    current = round(sum(float(r[20]) for r in triggered), 2)
    profit = round(current - invested, 2)
    return_pct = round(profit / invested * 100, 2) if invested else 0
    summary_labels = ["SYMBOLS", "STOCKS", "ETFs", "BUY TRIGGERED",
                      "INVESTED ₹", "CURRENT ₹", "P/L ₹", "RETURN %",
                      "EXCLUDED QTY < 1"]
    summary_values = [len(rows), sum(r[0] == "STOCK" for r in rows),
                      sum(r[0] == "ETF" for r in rows), len(triggered),
                      invested, current, profit, return_pct, excluded]
    # Row 1 dashboard title, rows 3-4 KPIs, row 6 actual data headers.
    # Use two columns per KPI for less visual crowding.
    data = [["HALF-MONTH | STOCK BREAKOUT + ETF DIP",
             "SIP from ETF Compounding B for REAL symbols • Paper P/L only"]]
    data.append(["MONTHLY LIMIT: NONE", "Paper plans: linked SIP budget for REAL symbols; ₹5,000 for other watchlist symbols"])
    label_row, value_row = [""] * 23, [""] * 23
    for i, (label, value) in enumerate(zip(summary_labels, summary_values)):
        label_row[i * 2] = label
        value_row[i * 2] = value
    data.extend([label_row, value_row,
                 ["Stocks: above previous half HIGH   |   ETFs: below previous half LOW"
                  "   |   Price Date and STALE PRICE warnings matter."],
                 RESULT_COLS])
    # Planned budget/quantity stay live when the user edits compounding SIP B.
    # Keep the numerical rows for statistics and styling; only output P/Q formulas.
    display_rows=[list(row) for row in rows]
    for rn,row in enumerate(display_rows,start=7):
        row[15]=(f'=IF(D{rn}="","",IFERROR(VLOOKUP(D{rn},'
                 f"'HalfMonth Watchlist'!$D$2:$E$100,2,FALSE),5000))")
        row[16]=(f'=IF(D{rn}="","",IFERROR(IF(AND(ISNUMBER(P{rn}),'
                 f'ISNUMBER(H{rn}),H{rn}>0),INT(P{rn}/H{rn}),""),""))')
    data.extend(display_rows)
    ws.update(data, range_name="A1:W" + str(len(data)), value_input_option="RAW")
    ws.freeze(rows=6, cols=0)

    navy = {"red": 0.16, "green": 0.25, "blue": 0.35}
    ivory = {"red": 0.97, "green": 0.98, "blue": 0.98}
    muted = {"red": 0.34, "green": 0.42, "blue": 0.47}
    teal = {"red": 0.06, "green": 0.38, "blue": 0.40}
    styles = []
    def format_range(a1, fmt):
        ws.format(a1, fmt)

    format_range("A1:W1", {
        "backgroundColor": navy, "textFormat": {
            "bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1},
            "fontSize": 12}, "verticalAlignment": "MIDDLE"})
    format_range("A3:R3", {
        "backgroundColor": {"red": 0.90, "green": 0.95, "blue": 0.95},
        "textFormat": {"bold": True, "fontSize": 9,
                       "foregroundColor": muted}})
    format_range("A4:R4", {
        "backgroundColor": {"red": 0.95, "green": 0.98, "blue": 0.97},
        "textFormat": {"bold": True, "fontSize": 13,
                       "foregroundColor": navy}})
    format_range("A5:W5", {
        "backgroundColor": ivory,
        "textFormat": {"italic": True, "foregroundColor": muted}})
    format_range("A6:W6", {
        "backgroundColor": teal,
        "textFormat": {"bold": True, "fontSize": 10,
                       "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
        "wrapStrategy": "WRAP"})
    ws.format("K4:Q4", {"numberFormat": {
        "type": "NUMBER", "pattern": "#,##0.00;[Red]-#,##0.00"}})
    format_range("Q4", {"textFormat": {
        "bold": True,
        "foregroundColor": ({"red": 0.10, "green": 0.46, "blue": 0.31}
                            if profit >= 0 else
                            {"red": 0.74, "green": 0.22, "blue": 0.23})}})
    end = len(rows) + 6
    if rows:
        for col in ("F", "G", "H", "I", "J", "K", "P", "S", "T", "U", "V", "W"):
            ws.format(f"{col}7:{col}{end}", {"numberFormat": {
                "type": "NUMBER", "pattern": "#,##0.00;[Red]-#,##0.00"}})
        ws.format(f"Q7:Q{end}", {"numberFormat": {
            "type": "NUMBER", "pattern": "0"}})
        for row_no, row in enumerate(rows, start=7):
            status = str(row[11])
            triggered = "BUY TRIGGERED" in status
            stale = "STALE PRICE" in status
            stock = row[0] == "STOCK"
            even = row_no % 2 == 0
            bg = ({"red": 0.94, "green": 0.97, "blue": 0.99} if stock
                  else {"red": 0.96, "green": 0.96, "blue": 0.99})
            if even:
                bg = ({"red": 0.90, "green": 0.95, "blue": 0.98} if stock
                      else {"red": 0.93, "green": 0.94, "blue": 0.98})
            if "DATA ERROR" in status or "NO REFERENCE DATA" in status:
                bg = {"red": 1.0, "green": 0.90, "blue": 0.88}
            elif triggered:
                # Strong emerald background + bold white text across the row,
                # including triggered rows with a STALE PRICE warning.
                bg = {"red": 0.05, "green": 0.42, "blue": 0.27}
            elif stale:
                bg = {"red": 0.99, "green": 0.96, "blue": 0.88}
            # Always reset foreground color. A formerly triggered green/white
            # row would otherwise keep invisible WHITE text on its new pale
            # background after the half-month period rolls over.
            cell_format = {
                "backgroundColor": bg,
                "verticalAlignment": "MIDDLE",
                "textFormat": {
                    "bold": bool(triggered),
                    "fontSize": 11 if triggered else 10,
                    "foregroundColor": (
                        {"red": 1, "green": 1, "blue": 1}
                        if triggered else
                        {"red": 0.12, "green": 0.20, "blue": 0.27}
                    )
                }
            }
            if triggered:
                cell_format["borders"] = {
                    edge: {"style": "SOLID_MEDIUM",
                           "color": {"red": 0.02, "green": 0.30, "blue": 0.19}}
                    for edge in ("top", "bottom")}
            styles.append({"repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": row_no - 1,
                          "endRowIndex": row_no,
                          "startColumnIndex": 0, "endColumnIndex": 23},
                "cell": {"userEnteredFormat": cell_format},
                "fields": ("userEnteredFormat" if triggered else
                           "userEnteredFormat.backgroundColor,"
                           "userEnteredFormat.verticalAlignment,"
                           "userEnteredFormat.textFormat")}})
            # High-contrast accents on actionable numbers and state, kept
            # after row-level styling so text remains readable.
            if not triggered:
                accents = [
                    (3, 4, {"red":0.10,"green":0.30,"blue":0.62},
                     {"red":0.86,"green":0.93,"blue":1.00}),
                    (7, 8, {"red":0.38,"green":0.25,"blue":0.66},
                     {"red":0.94,"green":0.89,"blue":1.00}),
                    (8, 9, {"red":0.05,"green":0.40,"blue":0.46},
                     {"red":0.85,"green":0.97,"blue":0.98}),
                    (11, 12, {"red":0.47,"green":0.31,"blue":0.06},
                     {"red":1.00,"green":0.94,"blue":0.75}),
                    (12, 13, {"red":0.24,"green":0.33,"blue":0.49},
                     {"red":0.90,"green":0.94,"blue":0.98}),
                ]
                if "DATA ERROR" in status or "NO REFERENCE DATA" in status:
                    accents[3] = (11, 12,
                        {"red":0.64,"green":0.08,"blue":0.08},
                        {"red":1.00,"green":0.79,"blue":0.79})
                if stale:
                    accents[3] = (11, 12,
                        {"red":0.61,"green":0.26,"blue":0.04},
                        {"red":1.00,"green":0.85,"blue":0.58})
                for c0,c1,fg,fill in accents:
                    styles.append({"repeatCell":{
                        "range":{"sheetId":ws.id,"startRowIndex":row_no-1,
                                 "endRowIndex":row_no,
                                 "startColumnIndex":c0,"endColumnIndex":c1},
                        "cell":{"userEnteredFormat":{
                            "backgroundColor":fill,
                            "textFormat":{"bold":True,
                                          "foregroundColor":fg}}},
                        "fields":"userEnteredFormat.backgroundColor,"
                                 "userEnteredFormat.textFormat"}})
            # Profit and loss cells keep their own high-contrast distinction.
            if row[21] != "":
                positive = float(row[21]) >= 0
                fg = ({"red": 0.76, "green": 1.0, "blue": 0.76} if positive
                      else {"red": 1.0, "green": 0.77, "blue": 0.70}) if triggered else (
                      {"red": 0.08, "green": 0.47, "blue": 0.31} if positive
                      else {"red": 0.75, "green": 0.24, "blue": 0.26})
                styles.append({"repeatCell": {
                    "range": {"sheetId": ws.id, "startRowIndex": row_no - 1,
                              "endRowIndex": row_no,
                              "startColumnIndex": 21, "endColumnIndex": 23},
                    "cell": {"userEnteredFormat": {
                        "textFormat": {"bold": True, "fontSize": 11,
                                       "foregroundColor": fg}}},
                    "fields": "userEnteredFormat.textFormat"}})

    # One batch formats status rows and sets compact but readable column widths.
    widths = {0: 78, 1: 155, 2: 220, 3: 116, 4: 142,
              11: 240, 12: 110, 13: 110, 14: 110,
              17: 112, 18: 108, 21: 100, 22: 95}
    for idx, width in widths.items():
        styles.append({"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": idx, "endIndex": idx + 1},
            "properties": {"pixelSize": width}, "fields": "pixelSize"}})
    styles.append({"updateDimensionProperties": {
        "range": {"sheetId": ws.id, "dimension": "ROWS",
                  "startIndex": 5, "endIndex": 6},
        "properties": {"pixelSize": 44}, "fields": "pixelSize"}})
    for i in range(0, len(styles), 100):
        book.batch_update({"requests": styles[i:i + 100]})
    print("Summary:", len(rows), "eligible,", excluded, "excluded;",
          "invested", invested, "current", current, "P/L", profit)



def main():
    # GitHub runner uses UTC; range dates must follow India calendar time.
    today = (pd.Timestamp.now(tz="Asia/Kolkata")).date()
    book = open_book()
    watchlist = get_watchlist(book)
    if not watchlist:
        raise ValueError("HalfMonth Watchlist has no valid symbols")
    budgets = get_sip_budgets(book, watchlist)
    rows = []
    excluded = 0
    market_data = {}
    official_prices,confirmed_day=load_nse_recent(today)
    audit_rows=[]
    verified_symbols=set()
    for item in watchlist:
        df, error = fetch_daily(item[3])
        df,added=merge_nse_recent(df,item[3],official_prices)
        if added:
            print("NSE fallback filled:",item[3],added,"new daily bars")
            error=""
        verified, check = validate_reference(item[3], official_prices, today)
        audit_rows.append([item[3],check])
        if not verified:
            error=check
        else:
            verified_symbols.add(item[3])
        # Retain OHLC for P/L of old positions even when new buys are blocked.
        market_data[item[3]] = df
        # If the official source is blocked, the old day stays visible.
        row = build_row(item, df, error, today,confirmed_day, budget=budgets[item[3]])
        qty = row[16]
        # Keep user watchlist untouched, but exclude anything with <2 whole
        # units at the prior half-period's reference entry price.
        if isinstance(qty, (int, float)) and qty < 1:
            excluded += 1
            print("EXCLUDED (quantity under 1):", item[0], item[3], qty)
            continue
        rows.append(row)
        print(item[0], item[3], row[11])
    rows.sort(key=lambda row: (0 if row[0] == "STOCK" else 1,
                               0 if "BUY TRIGGERED" in row[11] else 1,
                               row[1], row[3]))
    # Keep prices updating for old holdings removed from the active watchlist.
    try:
        previous = book.worksheet("HalfMonth History").get_all_values()
    except gspread.WorksheetNotFound:
        previous = []
    for entry in previous[1:]:
        if len(entry)<7 or not entry[6]:continue
        old_symbol = entry[6].strip().upper()
        if old_symbol in market_data:continue
        df, error = fetch_daily(old_symbol)
        df, added = merge_nse_recent(df, old_symbol, official_prices)
        market_data[old_symbol] = df
    audit=worksheet(book,"HalfMonth Data Audit",2)
    audit.clear()
    audit.resize(rows=max(50,len(audit_rows)+2),cols=2)
    audit.update([["NSE Code","Reference OHLC Verification"]]+audit_rows,
                 range_name="A1:B"+str(len(audit_rows)+1),
                 value_input_option="RAW")
    audit.freeze(rows=1)
    ledger = persist_paper_signals(book, watchlist, market_data, today,
                                   verified_symbols=verified_symbols, budgets=budgets)
    for row in rows:
        if "BUY TRIGGERED" in str(row[11]):
            row[11] = str(row[11]).replace("BUY TRIGGERED", "BUY TRIGGERED | PAPER RECORDED")
    update_results(book, rows, excluded)
    print("HalfMonth Signals updated:", len(rows), "symbols on", today)


if __name__ == "__main__":
    main()

