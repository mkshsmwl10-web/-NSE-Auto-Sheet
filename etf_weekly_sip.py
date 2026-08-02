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

sheet = client.open_by_key(SPREADSHEET_ID).worksheet("Sheet2")

# Read ETF Codes from Column A
symbols = sheet.col_values(1)[1:]

print(f"Total ETFs Found : {len(symbols)}")

for s in symbols:
    print(s)
    # ==========================
# TEST YFINANCE
# ==========================

for s in symbols:

    if not s:
        continue

    ticker = s.replace("NSE:", "") + ".NS"

    print(f"Checking {ticker}")

    df = yf.download(
        ticker,
        period="30wk",
        interval="1wk",
        progress=False,
        auto_adjust=False
    )

    if df.empty:
        print("No Data")
    else:
        print(df[['Close']].tail())
        break
