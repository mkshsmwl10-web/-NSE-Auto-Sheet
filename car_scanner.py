#!/usr/bin/env python3
"""Independent NIFTY200 cumulative-average (CAR) scanner."""

from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

import gspread
import pandas as pd
import yfinance as yf

from update_sheet import get_google_sheet, get_nifty200_stocks


ALL_TAB = "CAR RESULTS"
BUY_TAB = "CAR BUY"
HEADERS = ["Stock Name", "NSE Code", "CAR Rating", "High Date", "CMP", "Chart Link"]


def rate_car(frame: pd.DataFrame) -> tuple[str, str]:
    if frame is None or frame.empty:
        return "DATA UNAVAILABLE", ""

    frame = frame.dropna(subset=["High", "Close"]).sort_index()
    if frame.empty:
        return "DATA UNAVAILABLE", ""

    high_date = frame["High"].idxmax()
    closes = frame.loc[high_date:, "Close"]
    high_day = high_date.strftime("%Y-%m-%d")

    if len(closes) < 10:
        return "Short History", high_day

    averages = closes.cumsum() / pd.Series(
        range(1, len(closes) + 1), index=closes.index
    )
    last_ten = averages.iloc[-10:]
    passed = all(
        last_ten.iloc[i] > last_ten.iloc[i - 1] for i in range(1, 10)
    )
    return ("Buy/Average Out" if passed else "Avoid/Hold"), high_day


def fetch_stock(symbol: str, start: str, end: str) -> pd.DataFrame:
    data = yf.download(
        symbol + ".NS",
        start=start,
        end=end,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    return data


def replace_tab(book, name: str, rows: list[list]) -> None:
    try:
        tab = book.worksheet(name)
    except gspread.WorksheetNotFound:
        tab = book.add_worksheet(
            title=name, rows=max(201, len(rows) + 10), cols=9
        )

    tab.clear()
    tab.resize(rows=max(2, len(rows)), cols=9)
    tab.update(
        range_name=f"A1:F{len(rows)}",
        values=rows,
        value_input_option="USER_ENTERED",
    )
    tab.freeze(rows=1)

    tab.format("A1:F1", {
        "textFormat": {
            "bold": True,
            "foregroundColor": {"red": 1, "green": 1, "blue": 1},
        },
        "backgroundColor": {"red": 0.12, "green": 0.30, "blue": 0.55},
    })

    if len(rows) > 1:
        tab.format(f"A2:F{len(rows)}", {
            "backgroundColor": {"red": 0.97, "green": 0.98, "blue": 1},
            "verticalAlignment": "MIDDLE",
        })
        tab.format(
            f"E2:E{len(rows)}",
            {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}},
        )
        tab.format(f"F2:F{len(rows)}", {
            "textFormat": {
                "foregroundColor": {
                    "red": 0.08, "green": 0.37, "blue": 0.80
                },
                "bold": True,
            },
        })

        green = {"red": 0.84, "green": 0.96, "blue": 0.86}
        if name == BUY_TAB:
            tab.format(
                f"A2:F{len(rows)}", {"backgroundColor": green}
            )
        else:
            requests = [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": tab.id,
                            "startRowIndex": i,
                            "endRowIndex": i + 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": 6,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": green
                            }
                        },
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                }
                for i, row in enumerate(rows[1:], start=1)
                if row[2] == "Buy/Average Out"
            ]
            if requests:
                book.batch_update({"requests": requests})

    widths = [170, 115, 160, 115, 105, 130]
    book.batch_update({
        "requests": [
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": tab.id,
                        "dimension": "COLUMNS",
                        "startIndex": i,
                        "endIndex": i + 1,
                    },
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize",
                }
            }
            for i, width in enumerate(widths)
        ]
    })


def main() -> None:
    book = get_google_sheet()
    stocks = get_nifty200_stocks()

    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    start = (today - timedelta(days=364)).isoformat()
    end = (today + timedelta(days=1)).isoformat()

    all_rows = [HEADERS]
    buy_rows = [HEADERS]

    for stock in stocks:
        name, code = stock["Stock Name"], stock["NSE Code"]

        try:
            frame = fetch_stock(code, start, end)
            rating, high_day = rate_car(frame)
            cmp_price = (
                round(float(frame["Close"].dropna().iloc[-1]), 2)
                if not frame.empty else ""
            )
        except Exception as exc:
            print(f"{code}: fetch failed: {exc}")
            rating, high_day = "DATA UNAVAILABLE", ""
            cmp_price = ""

        chart_url = (
            "https://www.tradingview.com/chart/?symbol="
            + quote("NSE:" + code, safe="")
        )
        chart_link = f'=HYPERLINK("{chart_url}","OPEN CHART")'

        row = [name, code, rating, high_day, cmp_price, chart_link]
        all_rows.append(row)

        if rating == "Buy/Average Out":
            buy_rows.append(row)

        print(f"{code}: {rating}")

    replace_tab(book, ALL_TAB, all_rows)
    replace_tab(book, BUY_TAB, buy_rows)

    buy_tab = book.worksheet(BUY_TAB)
    buy_tab.update(
        range_name="H1:I2",
        values=[
            ["Stocks scanned", "CAR passed"],
            [len(stocks), len(buy_rows) - 1],
        ],
    )
    buy_tab.format("H1:I1", {
        "textFormat": {"bold": True},
        "backgroundColor": {"red": 0.91, "green": 0.95, "blue": 1},
    })

    print(f"CAR passed: {len(buy_rows) - 1} / {len(stocks)}")
    print(
        "Data unavailable: "
        f"{sum(r[2] == 'DATA UNAVAILABLE' for r in all_rows[1:])}"
    )


if __name__ == "__main__":
    main()
