import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import yfinance as yf

# ==========================
# Google Authentication
# ==========================

creds_json = os.environ.get("GCP_CREDENTIALS")

if not creds_json:
    raise Exception("GCP_CREDENTIALS Secret Missing")

creds_dict = json.loads(creds_json)

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_dict(
    creds_dict,
    scope
)

client = gspread.authorize(creds)

# ==========================
# Open ETF Sheet
# ==========================

SPREADSHEET_ID = "13Jy8xJB9l6SQ124aEIAF3wFJRvJIUXX6jOH61rFb3zY"

sheet = client.open_by_key(SPREADSHEET_ID).worksheet("sheet2")

# Read ETF Codes from Column A
symbols = sheet.col_values(1)[1:]

print(f"Total ETFs Found : {len(symbols)}")
print(symbols)

for s in symbols:
    print(s)
results = []

for s in symbols:

    if not s:
        continue

    ticker = s.replace("NSE:", "") + ".NS"

    print(f"Processing {ticker}")

    try:

        df = yf.download(
            ticker,
            period="30wk",
            interval="1wk",
            progress=False,
            auto_adjust=False
        )

        if df.empty or len(df) < 20:
            print(f"Not enough data : {ticker}")
            continue

        close = float(df["Close"].iloc[-1])

        sma20 = float(df["Close"].tail(20).mean())

        diff = ((close - sma20) / sma20) * 100

        signal = "BUY" if close < sma20 else "WAIT"

        print(
            ticker,
            close,
            sma20,
            round(diff, 2),
            signal
        )

        results.append([
            close,
            sma20,
            round(diff, 2),
            signal
        ])

    except Exception as e:

        print(ticker, str(e))
