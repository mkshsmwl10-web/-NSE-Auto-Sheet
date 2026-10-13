#!/usr/bin/env python3
"""Half-month breakout scanner, independent of update_sheet.py.

An editable Google worksheet controls the user-selected ETF/stock universe.
1st-15th: collect reference High/Low (inclusive).
16th-month end: stock buys above reference High; ETF buys below reference Low.
Daily candle High/Low detects a touch; CMP records the latest available Close.
"""
import calendar
import json
import os
import re
import time
from datetime import date, timedelta

import gspread
import pandas as pd
import yfinance as yf
from google.oauth2.service_account import Credentials

SHEET_ID = os.getenv("SPREADSHEET_ID", "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E")
WATCHLIST_TAB = os.getenv("HALF_MONTH_WATCHLIST", "HalfMonth Watchlist")
SIGNALS_TAB = os.getenv("HALF_MONTH_SIGNALS", "HalfMonth Signals")
WATCH_COLS = ["Type", "Sector / Theme", "Name", "NSE Code"]
RESULT_COLS = [
    "Type", "Sector / Theme", "Name", "NSE Code", "Strategy",
    "1-15 High", "1-15 Low", "BUY Level", "CMP", "Today High", "Today Low",
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


def build_row(item, df, error, today):
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
    empty_position = [BUDGET, "", "", "", "", "", "", ""]
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
    qty = int(BUDGET // level) if level > 0 else 0
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
    if quote_date < today - timedelta(days=3):
        status += " | STALE PRICE"

    # Hypothetical full-share allocation at reference level; not an executed fill.
    # Do not compute paper P/L before entry.
    entry = level if first_hit and qty else ""
    invested = round(qty * level, 2) if first_hit and qty else ""
    current = round(qty * cmp_value, 2) if first_hit and qty else ""
    pnl = round(current - invested, 2) if first_hit and qty else ""
    pnl_pct = round(100 * pnl / invested, 2) if invested != "" and invested else ""
    return base + [hi, lo, level, cmp_value, day_high, day_low,
                   status, str(quote_date), *labels,
                   BUDGET, qty, str(first_hit) if first_hit else "",
                   entry, invested, current, pnl, pnl_pct]


def update_results(book, rows):
    ws = worksheet(book, SIGNALS_TAB, len(RESULT_COLS))
    ws.clear()
    ws.resize(rows=max(100, len(rows) + 2), cols=len(RESULT_COLS))
    ws.update([RESULT_COLS] + rows,
              range_name="A1:W" + str(len(rows) + 1),
              value_input_option="RAW")
    ws.freeze(rows=1, cols=4)
    ws.format("A1:W1", {
        "backgroundColor": {"red": 0.11, "green": 0.20, "blue": 0.34},
        "textFormat": {"bold": True,
                       "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        "horizontalAlignment": "CENTER", "wrapStrategy": "WRAP"
    })
    if not rows:
        return
    end = len(rows) + 1
    for col in ("F", "G", "H", "I", "J", "K", "P", "S", "T", "U", "V", "W"):
        ws.format(f"{col}2:{col}{end}", {"numberFormat": {
            "type": "NUMBER", "pattern": "#,##0.00;[Red]-#,##0.00"}})
    ws.format(f"Q2:Q{end}", {"numberFormat": {"type": "NUMBER", "pattern": "0"}})
    styles = []
    for row_no, row in enumerate(rows, start=2):
        status = row[11]
        bg = ({"red": 0.93, "green": 0.96, "blue": 1.0} if row[0] == "STOCK"
              else {"red": 0.95, "green": 0.92, "blue": 1.0})
        if "BUY TRIGGERED" in status:
            bg = {"red": 0.80, "green": 0.96, "blue": 0.83}
        elif "DATA ERROR" in status or "NO REFERENCE DATA" in status:
            bg = {"red": 1, "green": 0.86, "blue": 0.83}
        elif "STALE PRICE" in status:
            bg = {"red": 1, "green": 0.94, "blue": 0.78}
        styles.append({"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": row_no - 1,
                      "endRowIndex": row_no, "startColumnIndex": 0,
                      "endColumnIndex": len(RESULT_COLS)},
            "cell": {"userEnteredFormat": {"backgroundColor": bg}},
            "fields": "userEnteredFormat.backgroundColor"}})
        if row[21] != "":
            pl = float(row[21])
            fg = ({"red": 0.04, "green": 0.43, "blue": 0.19} if pl >= 0
                  else {"red": 0.75, "green": 0.11, "blue": 0.11})
            styles.append({"repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": row_no - 1,
                          "endRowIndex": row_no, "startColumnIndex": 21,
                          "endColumnIndex": 23},
                "cell": {"userEnteredFormat": {
                    "textFormat": {"bold": True, "foregroundColor": fg}}},
                "fields": "userEnteredFormat.textFormat"}})
    for i in range(0, len(styles), 100):
        book.batch_update({"requests": styles[i:i + 100]})


def main():
    # GitHub runner uses UTC; range dates must follow India calendar time.
    today = (pd.Timestamp.now(tz="Asia/Kolkata")).date()
    book = open_book()
    watchlist = get_watchlist(book)
    if not watchlist:
        raise ValueError("HalfMonth Watchlist has no valid symbols")
    rows = []
    for item in watchlist:
        df, error = fetch_daily(item[3])
        row = build_row(item, df, error, today)
        rows.append(row)
        print(item[0], item[3], row[11])
    rows.sort(key=lambda row: (0 if row[0] == "STOCK" else 1,
                               0 if "BUY TRIGGERED" in row[11] else 1,
                               row[1], row[3]))
    update_results(book, rows)
    print("HalfMonth Signals updated:", len(rows), "symbols on", today)


if __name__ == "__main__":
    main()
