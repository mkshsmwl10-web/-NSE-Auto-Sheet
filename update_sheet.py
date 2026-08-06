import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
import zipfile
import io
import json
import os

from datetime import datetime, timedelta

# ======================================
# GOOGLE LOGIN
# ======================================

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

# ======================================
# GOOGLE SHEET
# ======================================

SPREADSHEET_ID = "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E"

sheet_nifty = client.open_by_key(
    SPREADSHEET_ID
).worksheet("NIFTY200")

sheet_fixed = client.open_by_key(
    SPREADSHEET_ID
).worksheet("NIFTY200_FIXED")

sheet_history = client.open_by_key(
    SPREADSHEET_ID
).worksheet("MACD_HISTORY")

sheet_macd200 = client.open_by_key(
    SPREADSHEET_ID
).worksheet("MACD200")
# ======================================
# BHAVCOPY DOWNLOAD
# ======================================

def fetch_bhavcopy(date_obj):

    date_str = date_obj.strftime("%Y%m%d")

    url = (
        "https://nsearchives.nseindia.com/content/cm/"
        f"BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv.zip"
    )

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:

        print(f"Downloading {date_str}")

        response = requests.get(
            url,
            headers=headers,
            timeout=30
        )

        if response.status_code != 200:
            return None

        with zipfile.ZipFile(
            io.BytesIO(response.content)
        ) as z:

            csv_file = z.namelist()[0]

            with z.open(csv_file) as f:

                df = pd.read_csv(f)

        df.columns = [
            c.strip()
            for c in df.columns
        ]

        symbol_col = next(
            (
                c for c in
                ["TckrSymb", "SYMBOL"]
                if c in df.columns
            ),
            None
        )

        close_col = next(
            (
                c for c in
                ["ClsPric", "CLOSE"]
                if c in df.columns
            ),
            None
        )

        turnover_col = next(
            (
                c for c in
                [
                    "TtlTrfVal",
                    "TtlTrdVal",
                    "TURNOVER",
                    "TURNOVER_LACS"
                ]
                if c in df.columns
            ),
            None
        )

        series_col = next(
            (
                c for c in
                ["SctySrs", "SERIES"]
                if c in df.columns
            ),
            None
        )

        if symbol_col is None:
            return None

        if close_col is None:
            return None

        if turnover_col is None:
            return None

        if series_col:

            df = df[
                df[series_col]
                .astype(str)
                .str.strip()
                == "EQ"
            ]

        df[turnover_col] = pd.to_numeric(
            df[turnover_col],
            errors="coerce"
        )

        df = df.dropna(
            subset=[turnover_col]
        )

        return df

    except Exception as e:

        print(e)

        return None
      # ======================================
# MAIN PROGRAM
# ======================================

today = datetime.now()

bhavcopy = None
data_date = ""

for i in range(7):

    check_date = today - timedelta(days=i)

    if check_date.weekday() >= 5:
        continue

    bhavcopy = fetch_bhavcopy(check_date)

    if bhavcopy is not None:

        data_date = check_date.strftime("%d-%b-%Y")

        break

if bhavcopy is None:

    raise Exception("Bhavcopy not found")

# ======================================
# FILTER TOP 200
# ======================================

filter_words = "BEES|ETF|GOLD|LIQUID|SILVER|INDEX"

symbol_col = "TckrSymb" if "TckrSymb" in bhavcopy.columns else "SYMBOL"
close_col = "ClsPric" if "ClsPric" in bhavcopy.columns else "CLOSE"
turnover_col = (
    "TtlTrfVal"
    if "TtlTrfVal" in bhavcopy.columns
    else "TtlTrdVal"
)

top200 = (
    bhavcopy[
        ~bhavcopy[symbol_col]
        .astype(str)
        .str.contains(filter_words, case=False, na=False)
    ]
    .sort_values(turnover_col, ascending=False)
    .head(200)
)

rows = top200[
    [symbol_col, turnover_col, close_col]
].values.tolist()

sheet_nifty.batch_clear(["A2:C1000"])

sheet_nifty.update(
    "A2",
    rows
)

print("NIFTY200 UPDATED")
# ======================================
# MODULE 2
# INITIALIZE NIFTY200_FIXED
# ======================================

fixed_data = sheet_fixed.get_all_values()

# Only initialize if sheet is empty
if len(fixed_data) <= 1:

    print("Initializing NIFTY200_FIXED...")

    # Clear old data
    sheet_fixed.batch_clear(["A2:C1000"])

    # Copy today's Top 200
    sheet_fixed.update(
        "A2",
        rows
    )

    print("NIFTY200_FIXED CREATED")

else:

    print("NIFTY200_FIXED already exists")
    # ======================================
# MODULE 3 - PART 1
# CREATE TODAY CLOSE DICTIONARY
# ======================================

today_close = {}

for _, row in bhavcopy.iterrows():

    symbol = str(row[symbol_col]).strip()

    close = float(row[close_col])

    today_close[symbol] = close

print(f"Today's Close Dictionary : {len(today_close)} Symbols")

print("MODULE 1 SUCCESS")

print("Google Connected")
