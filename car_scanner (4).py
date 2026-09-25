#!/usr/bin/env python3
"""Independent NIFTY200 cumulative-average (CAR) scanner.

Equivalent to the saved Sheets rule: find the highest daily high in the last
364 calendar days; average closes starting on that day; require the ten most
recent cumulative averages to rise strictly (nine comparisons).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import gspread
import pandas as pd
import yfinance as yf

from update_sheet import get_google_sheet, get_nifty200_stocks


ALL_TAB = "CAR RESULTS"
BUY_TAB = "CAR BUY"
HEADERS = ["Stock Name", "NSE Code", "CAR Rating", "High Date"]


def rate_car(frame: pd.DataFrame) -> tuple[str, str]:
    if frame is None or frame.empty:
        return "DATA UNAVAILABLE", ""
    frame = frame.dropna(subset=["High", "Close"]).sort_index()
    if frame.empty:
        return "DATA UNAVAILABLE", ""

    # idxmax returns the earliest day if the maximum high occurred more than once.
    high_date = frame["High"].idxmax()
    closes = frame.loc[high_date:, "Close"]
    high_day = high_date.strftime("%Y-%m-%d")
    if len(closes) < 10:
        return "Short History", high_day

    averages = closes.cumsum() / pd.Series(range(1, len(closes) + 1), index=closes.index)
    last_ten = averages.iloc[-10:]
    passed = all(last_ten.iloc[i] > last_ten.iloc[i - 1] for i in range(1, 10))
    return ("Buy/Average Out" if passed else "Avoid/Hold"), high_day


def fetch_stock(symbol: str, start: str, end: str) -> pd.DataFrame:
    data = yf.download(
        symbol + ".NS", start=start, end=end, interval="1d",
        auto_adjust=False, progress=False, threads=False,
    )
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    return data


def replace_tab(book, name: str, rows: list[list[str]]) -> None:
    try:
        tab = book.worksheet(name)
    except gspread.WorksheetNotFound:
        tab = book.add_worksheet(title=name, rows=max(201, len(rows) + 10), cols=8)
    tab.clear()
    tab.resize(rows=max(2, len(rows)), cols=8)
    tab.update(range_name=f"A1:D{len(rows)}", values=rows, value_input_option="RAW")
    tab.freeze(rows=1)
    tab.format("A1:D1", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.88, "green": 0.94, "blue": 1}})


def main() -> None:
    book = get_google_sheet()
    stocks = get_nifty200_stocks()
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    start = (today - timedelta(days=364)).isoformat()
    end = (today + timedelta(days=1)).isoformat()  # yfinance end is exclusive
    all_rows = [HEADERS]
    buy_rows = [HEADERS]
    for stock in stocks:
        name, code = stock["Stock Name"], stock["NSE Code"]
        try:
            rating, high_day = rate_car(fetch_stock(code, start, end))
        except Exception as exc:
            print(f"{code}: fetch failed: {exc}")
            rating, high_day = "DATA UNAVAILABLE", ""
        row = [name, code, rating, high_day]
        all_rows.append(row)
        if rating == "Buy/Average Out":
            buy_rows.append(row)
        print(f"{code}: {rating}")

    replace_tab(book, ALL_TAB, all_rows)
    replace_tab(book, BUY_TAB, buy_rows)
    buy_tab = book.worksheet(BUY_TAB)
    buy_tab.update(range_name="F1:G2", values=[["Stocks scanned", "CAR passed"], [len(stocks), len(buy_rows) - 1]])
    print(f"CAR passed: {len(buy_rows) - 1} / {len(stocks)}")
    print(f"Data unavailable: {sum(r[2] == 'DATA UNAVAILABLE' for r in all_rows[1:])}")


if __name__ == "__main__":
    main()
