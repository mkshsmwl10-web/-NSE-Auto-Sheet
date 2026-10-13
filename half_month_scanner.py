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
    "BUY Status", "Price Date", "Valid From", "Valid Till"
]

# Editable starter set. These are representatives, not a quantitative
# assertion that any one company is the permanent sector leader.
DEFAULT_WATCHLIST = [
    ("ETF", "Nifty 50", "Nifty BeES", "NIFTYBEES"),
    ("ETF", "Banking", "Bank BeES", "BANKBEES"),
    ("ETF", "Midcap 150", "Midcap 150 BeES", "MID150BEES"),
    ("ETF", "Sensex", "Sensex BeES", "SENSEXBEES"),
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
    if not raw:
        # Create user-owned watchlist only once. Later updates never overwrite.
        ws.update([WATCH_COLS] + [list(row) for row in DEFAULT_WATCHLIST],
                  range_name="A1:D" + str(len(DEFAULT_WATCHLIST) + 1))
        ws.freeze(rows=1)
        raw = [WATCH_COLS] + [list(row) for row in DEFAULT_WATCHLIST]
        print("Created editable watchlist with", len(DEFAULT_WATCHLIST), "items")
    items, seen = [], set()
    for row in raw[1:]:
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
    return items


def fetch_daily(symbol):
    last_error = "empty OHLC"
    for attempt in range(3):
        try:
            df = yf.Ticker(symbol + ".NS").history(period="3mo", interval="1d",
                                                    auto_adjust=True)
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
    last_day = calendar.monthrange(today.year, today.month)[1]
    from_day, end_day = date(today.year, today.month, 16), date(today.year, today.month, last_day)
    base = [kind, sector, name, symbol,
            "BUY ABOVE HIGH" if kind == "STOCK" else "BUY BELOW LOW"]
    if error or df is None:
        return base + ["", "", "", "", "", "", "DATA ERROR: " + (error or "no data"),
                       "", str(from_day), str(end_day)]
    # Reference candle window is always the current month's days 1-15.
    ref = df[(df.index.year == today.year) &
             (df.index.month == today.month) &
             (df.index.day <= 15)]
    latest = df.iloc[-1]
    quote_date = df.index[-1].date()
    cmp_value = round(float(latest["Close"]), 2)
    day_high = round(float(latest["High"]), 2)
    day_low = round(float(latest["Low"]), 2)
    if ref.empty:
        return base + ["", "", "", cmp_value, day_high, day_low,
                       "NO 1-15 DATA", str(quote_date), str(from_day), str(end_day)]
    hi, lo = round(float(ref["High"].max()), 2), round(float(ref["Low"].min()), 2)
    level = hi if kind == "STOCK" else lo
    if today.day <= 15:
        status = "BUILDING RANGE (1-15)"
    elif quote_date < from_day:
        status = "AWAITING 16+ SESSION"
    elif quote_date > end_day or quote_date > today:
        status = "CHECK PRICE DATE"
    elif kind == "STOCK":
        status = "BUY TRIGGERED" if float(latest["High"]) > hi else "WAIT ABOVE HIGH"
    else:
        status = "BUY TRIGGERED" if float(latest["Low"]) < lo else "WAIT BELOW LOW"
    return base + [hi, lo, level, cmp_value, day_high, day_low,
                   status, str(quote_date), str(from_day), str(end_day)]


def update_results(book, rows):
    ws = worksheet(book, SIGNALS_TAB, len(RESULT_COLS))
    ws.clear()
    ws.resize(rows=max(100, len(rows) + 2), cols=len(RESULT_COLS))
    ws.update([RESULT_COLS] + rows,
              range_name="A1:O" + str(len(rows) + 1),
              value_input_option="RAW")
    ws.freeze(rows=1, cols=4)
    ws.format("A1:O1", {
        "backgroundColor": {"red": 0.8, "green": 0.9, "blue": 0.99},
        "textFormat": {"bold": True}, "wrapStrategy": "WRAP"
    })
    if rows:
        end = len(rows) + 1
        ws.format("F2:K" + str(end), {"numberFormat": {
            "type": "NUMBER", "pattern": "0.00"}})
        styles = []
        for row_no, row in enumerate(rows, start=2):
            if row[11] == "BUY TRIGGERED":
                color = {"red": 0.85, "green": 0.96, "blue": 0.86}
            elif row[11].startswith("DATA ERROR"):
                color = {"red": 1, "green": 0.90, "blue": 0.86}
            else:
                continue
            styles.append({"repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": row_no - 1,
                          "endRowIndex": row_no, "startColumnIndex": 0,
                          "endColumnIndex": len(RESULT_COLS)},
                "cell": {"userEnteredFormat": {"backgroundColor": color}},
                "fields": "userEnteredFormat.backgroundColor"}})
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
                               0 if row[11] == "BUY TRIGGERED" else 1,
                               row[1], row[3]))
    update_results(book, rows)
    print("HalfMonth Signals updated:", len(rows), "symbols on", today)


if __name__ == "__main__":
    main()
