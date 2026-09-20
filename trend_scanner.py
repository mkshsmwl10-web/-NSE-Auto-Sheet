import os
import json
import time

import pandas as pd
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials


# ============================================================
# CONFIG
# ============================================================

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID",
    "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E",
)

INPUT_SHEET = "NIFTY200"
OUTPUT_SHEET = "Trend Scanner"


# ============================================================
# GOOGLE SHEET LOGIN
# ============================================================

def connect_google_sheet():
    credentials_json = os.environ.get("GCP_CREDENTIALS")

    if not credentials_json:
        raise RuntimeError("GCP_CREDENTIALS secret not found.")

    credentials_info = json.loads(credentials_json)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    credentials = Credentials.from_service_account_info(
        credentials_info,
        scopes=scopes,
    )

    client = gspread.authorize(credentials)

    return client.open_by_key(SPREADSHEET_ID)


# ============================================================
# CLEAN SYMBOL
# ============================================================

def clean_symbol(value):
    if value is None:
        return ""

    symbol = str(value).strip().upper()

    if symbol.endswith(".NS"):
        symbol = symbol[:-3]

    return symbol


# ============================================================
# DYNAMIC OPEN -> CLOSE TREND
# ============================================================

def calculate_dynamic_trend(df):
    """
    USER LOGIC

    1. Green candle starts POSITIVE trend.
    2. Red candle starts NEGATIVE trend.

    POSITIVE:
        If current candle CLOSE < previous reference OPEN
        -> trend becomes NEGATIVE.

    NEGATIVE:
        If current candle CLOSE > previous reference OPEN
        -> trend becomes POSITIVE.

    IMPORTANT:
        Every completed candle gives us the next reference OPEN.

        So whether trend changes or does not change,
        after processing the candle:

            reference_open = current candle OPEN

        This creates the dynamic shifting OPEN level.
    """

    if df is None or df.empty:
        return "NO DATA", None

    df = df.copy()

    # Flatten yfinance MultiIndex if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    required = ["Open", "Close"]

    for col in required:
        if col not in df.columns:
            return "NO DATA", None

    df = df.dropna(subset=["Open", "Close"])

    if len(df) < 2:
        return "NO DATA", None

    # --------------------------------------------------------
    # FIRST CANDLE
    # --------------------------------------------------------

    first_open = float(df.iloc[0]["Open"])
    first_close = float(df.iloc[0]["Close"])

    if first_close >= first_open:
        trend = "POSITIVE"
    else:
        trend = "NEGATIVE"

    reference_open = first_open

    # --------------------------------------------------------
    # PROCESS NEXT CANDLES
    # --------------------------------------------------------

    for i in range(1, len(df)):

        candle_open = float(df.iloc[i]["Open"])
        candle_close = float(df.iloc[i]["Close"])

        # ---------------- POSITIVE ----------------
        if trend == "POSITIVE":

            if candle_close < reference_open:
                trend = "NEGATIVE"

        # ---------------- NEGATIVE ----------------
        else:

            if candle_close > reference_open:
                trend = "POSITIVE"

        # ----------------------------------------------------
        # OPEN SHIFT
        # Current candle OPEN becomes next reference OPEN
        # ----------------------------------------------------

        reference_open = candle_open

    return trend, reference_open


# ============================================================
# DOWNLOAD STOCK DATA
# ============================================================

def download_stock(symbol):
    ticker = f"{symbol}.NS"

    try:
        df = yf.download(
            ticker,
            period="1y",
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )

        if df is None or df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.dropna(subset=["Open", "High", "Low", "Close"])

        return df

    except Exception as e:
        print(f"Download error {symbol}: {e}")
        return None


# ============================================================
# READ NIFTY200
# ============================================================

def read_nifty200(sheet):
    ws = sheet.worksheet(INPUT_SHEET)

    values = ws.get_all_values()

    if not values:
        raise RuntimeError("NIFTY200 sheet is empty.")

    headers = [str(x).strip() for x in values[0]]

    print("NIFTY200 headers:", headers)

    rows = values[1:]

    # --------------------------------------------------------
    # Find NSE Code column
    # --------------------------------------------------------

    possible_symbol_headers = [
        "NSE Code",
        "NSE CODE",
        "Symbol",
        "SYMBOL",
        "NSECode",
        "Code",
    ]

    symbol_index = None

    for name in possible_symbol_headers:
        if name in headers:
            symbol_index = headers.index(name)
            break

    # If header not found, use first column
    if symbol_index is None:
        print("NSE Code header not found. Using column A.")
        symbol_index = 0

    # --------------------------------------------------------
    # Find Stock Name column
    # --------------------------------------------------------

    possible_name_headers = [
        "Stock Name",
        "STOCK NAME",
        "Name",
        "NAME",
        "Company",
        "Company Name",
    ]

    name_index = None

    for name in possible_name_headers:
        if name in headers:
            name_index = headers.index(name)
            break

    stocks = []

    for row in rows:

        if len(row) <= symbol_index:
            continue

        symbol = clean_symbol(row[symbol_index])

        if not symbol:
            continue

        if name_index is not None and len(row) > name_index:
            stock_name = str(row[name_index]).strip()
        else:
            stock_name = symbol

        stocks.append(
            {
                "name": stock_name,
                "symbol": symbol,
            }
        )

    # Remove duplicates
    unique = []
    seen = set()

    for stock in stocks:

        if stock["symbol"] in seen:
            continue

        seen.add(stock["symbol"])
        unique.append(stock)

    return unique


# ============================================================
# WRITE TREND SCANNER
# ============================================================

def write_results(sheet, results):
    try:
        ws = sheet.worksheet(OUTPUT_SHEET)

    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(
            title=OUTPUT_SHEET,
            rows=500,
            cols=10,
        )

    ws.clear()

    output = [
        [
            "Stock Name",
            "NSE Code",
            "CMP",
            "Daily Trend",
            "Weekly Trend",
            "Monthly Trend",
        ]
    ]

    output.extend(results)

    ws.update(
        range_name=f"A1:F{len(output)}",
        values=output,
    )

    # Freeze header
    ws.freeze(rows=1)

    # Bold header
    ws.format(
        "A1:F1",
        {
            "textFormat": {
                "bold": True
            },
            "horizontalAlignment": "CENTER",
        },
    )

    print(f"Google Sheet updated: {len(results)} stocks")


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("NIFTY200 DYNAMIC TREND SCANNER")
    print("=" * 60)

    sheet = connect_google_sheet()

    stocks = read_nifty200(sheet)

    print(f"Stocks found: {len(stocks)}")

    results = []

    for number, stock in enumerate(stocks, start=1):

        symbol = stock["symbol"]
        stock_name = stock["name"]

        print(
            f"[{number}/{len(stocks)}] "
            f"Scanning {symbol}..."
        )

        df = download_stock(symbol)

        if df is None or df.empty:
            print("  No data")
            continue

        try:
            cmp_price = round(
                float(df.iloc[-1]["Close"]),
                2,
            )

            daily_trend, reference_open = calculate_dynamic_trend(df)

            print(
                f"  CMP={cmp_price} "
                f"Trend={daily_trend} "
                f"Reference Open={reference_open}"
            )

            results.append(
                [
                    stock_name,
                    symbol,
                    cmp_price,
                    daily_trend,
                    "PENDING",
                    "PENDING",
                ]
            )

        except Exception as e:
            print(f"  Scan error: {e}")

        # Small pause to reduce Yahoo pressure
        time.sleep(0.10)

    write_results(sheet, results)

    print("=" * 60)
    print("TREND SCANNER COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    main()
