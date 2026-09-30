"""NIFTY spot: last 11 completed sessions, daily HH/HL/LH/LL."""
import json
import math
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
BOOK_ID = "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E"
TAB = "NIFTY 11 Days"


def analyse(rows):
    output = []
    for i, row in enumerate(rows):
        high_label, low_label = "", ""
        trend, sl = "BASE DAY", ""

        if i:
            prev = rows[i - 1]
            high_label = (
                "HH" if row["high"] > prev["high"]
                else "LH" if row["high"] < prev["high"]
                else "EH"
            )
            low_label = (
                "HL" if row["low"] > prev["low"]
                else "LL" if row["low"] < prev["low"]
                else "EL"
            )

            trend = "SIDEWAYS"
            if high_label == "HH" and low_label == "HL":
                trend, sl = "UP", prev["low"]
            elif high_label == "LH" and low_label == "LL":
                trend, sl = "DOWN", prev["high"]

        output.append([
            row["date"].strftime("%Y-%m-%d"),
            row["date"].strftime("%A"),
            row["open"], row["high"], row["low"], row["close"],
            high_label, low_label, trend, sl,
        ])
    return output


def fetch_rows():
    import pandas as pd
    import yfinance as yf

    data = yf.download(
        "^NSEI", period="3mo", interval="1d",
        auto_adjust=False, progress=False, threads=False,
    )
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    now = datetime.now(IST)
    rows = []

    for stamp, values in data.sort_index().iterrows():
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert(IST)
        day = stamp.date()

        if day > now.date():
            continue
        if day == now.date() and now.time() < time(16, 0):
            continue

        prices = [
            float(values[k]) for k in ("Open", "High", "Low", "Close")
        ]
        if not all(math.isfinite(x) and x > 0 for x in prices):
            continue

        o, h, l, c = prices
        if l > min(o, c) or h < max(o, c) or l > h:
            raise RuntimeError("Invalid OHLC; old sheet retained.")

        rows.append({
            "date": day, "open": o, "high": h, "low": l, "close": c
        })

    rows = list({r["date"]: r for r in rows}.values())[-11:]
    if len(rows) != 11:
        raise RuntimeError("Need 11 completed sessions; old sheet retained.")
    return rows


def format_sheet(book, ws, result):
    colors = {
        "UP": {"red": 0.80, "green": 0.94, "blue": 0.82},
        "DOWN": {"red": 1.0, "green": 0.82, "blue": 0.82},
        "SIDEWAYS": {"red": 1.0, "green": 0.94, "blue": 0.70},
        "BASE DAY": {"red": 0.89, "green": 0.92, "blue": 0.96},
    }
    requests = []

    def paint(r1, r2, c1, c2, color, bold=False):
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": r1, "endRowIndex": r2,
                    "startColumnIndex": c1, "endColumnIndex": c2,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": color,
                        "textFormat": {"bold": bold, "fontSize": 11},
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": (
                    "userEnteredFormat.backgroundColor,"
                    "userEnteredFormat.textFormat.bold,"
                    "userEnteredFormat.textFormat.fontSize,"
                    "userEnteredFormat.verticalAlignment"
                ),
            }
        })

    for index, row in enumerate(result, start=1):
        paint(index, index + 1, 0, 10, colors[row[8]])
        paint(index, index + 1, 6, 10, colors[row[8]], True)

    paint(13, 16, 0, 10,
          {"red": 0.85, "green": 0.90, "blue": 1.0}, True)
    paint(14, 15, 1, 2, colors[result[-1][8]], True)

    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": ws.id,
                "gridProperties": {"frozenRowCount": 1},
            },
            "fields": "gridProperties.frozenRowCount",
        }
    })

    widths = [
        (0, 1, 125), (1, 2, 160), (2, 6, 115),
        (6, 8, 135), (8, 9, 180), (9, 10, 125),
    ]
    for start, end, width in widths:
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": ws.id, "dimension": "COLUMNS",
                    "startIndex": start, "endIndex": end,
                },
                "properties": {"pixelSize": width},
                "fields": "pixelSize",
            }
        })

    requests.append({
        "updateDimensionProperties": {
            "range": {
                "sheetId": ws.id, "dimension": "ROWS",
                "startIndex": 0, "endIndex": 22,
            },
            "properties": {"pixelSize": 30},
            "fields": "pixelSize",
        }
    })
    book.batch_update({"requests": requests})


def main():
    import gspread
    from google.oauth2.service_account import Credentials

    rows = fetch_rows()
    result = analyse(rows)

    credentials = Credentials.from_service_account_info(
        json.loads(os.environ["GCP_CREDENTIALS"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    book = gspread.authorize(credentials).open_by_key(
        os.getenv("SPREADSHEET_ID", BOOK_ID)
    )

    try:
        ws = book.worksheet(TAB)
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(title=TAB, rows=30, cols=10)

    values = [[
        "Date", "Day", "Open", "High", "Low", "Close",
        "High vs Prev", "Low vs Prev", "Trend", "Spot SL",
    ]] + result

    values += [
        [""] * 10,
        ["Updated (IST)", datetime.now(IST).isoformat(timespec="seconds")],
        ["Next session bias", result[-1][8]],
        ["Spot SL", result[-1][9]],
        ["Rule", "HH + HL = UP; LH + LL = DOWN; mixed/equal = SIDEWAYS."],
        ["Basis", "Previous-session comparison. First row = BASE DAY."],
        ["SL rule", "UP: previous day low. DOWN: previous day high."],
        ["Source", "Yahoo Finance ^NSEI; only completed daily sessions."],
        ["Note", "Next-session spot SL touch invalidates bias; bias is not a guarantee."],
    ]
    values += [[""] * 10 for _ in range(22 - len(values))]
    values = [row + [""] * (10 - len(row)) for row in values]

    ws.update(
        range_name="A1:J22", values=values,
        value_input_option="RAW",
    )
    ws.freeze(rows=1)
    ws.format("A1:J1", {
        "backgroundColor": {"red": 0.10, "green": 0.20, "blue": 0.35},
        "textFormat": {
            "bold": True,
            "foregroundColor": {"red": 1, "green": 1, "blue": 1},
        },
    })
    for area in ("C2:F12", "J2:J12", "B16"):
        ws.format(area, {
            "numberFormat": {"type": "NUMBER", "pattern": "0.00"}
        })

    format_sheet(book, ws, result)
    print("DAILY COMPARISON VERSION")
    print("Updated:", rows[-1]["date"], result[-1][8:])


if __name__ == "__main__":
    main()
