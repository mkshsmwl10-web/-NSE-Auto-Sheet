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
# ======================================
# MODULE 3 - PART 2
# APPEND TODAY DATA TO MACD_HISTORY
# ======================================

today_db = datetime.now().strftime("%Y-%m-%d")

# Read existing history
history_data = sheet_history.get_all_values()

# Prevent duplicate append
already_exists = False

if len(history_data) > 1:

    for row in history_data[1:]:

        if len(row) >= 2 and row[0] == today_db:

            already_exists = True
            break

if already_exists:

    print(f"{today_db} already exists in MACD_HISTORY")

else:

    fixed_data = sheet_fixed.get_all_values()

    history_rows = []

    for row in fixed_data[1:]:

        if len(row) == 0:
            continue

        symbol = row[0].strip()

        if symbol in today_close:

            history_rows.append([
                today_db,
                symbol,
                today_close[symbol]
            ])

    if history_rows:

        sheet_history.append_rows(
            history_rows,
            value_input_option="RAW"
        )

        print(f"Added {len(history_rows)} rows to MACD_HISTORY")
        # =====================================================
# MODULE 4 - PART 1
# READ MACD_HISTORY
# =====================================================

history_data = sheet_history.get_all_values()

if len(history_data) <= 1:
    raise Exception("MACD_HISTORY Empty")

history_df = pd.DataFrame(
    history_data[1:],
    columns=history_data[0]
)

history_df["Date"] = pd.to_datetime(
    history_df["Date"]
)

history_df["Close"] = pd.to_numeric(
    history_df["Close"],
    errors="coerce"
)

history_df = history_df.dropna(
    subset=["Close"]
)

history_df = history_df.sort_values(
    ["Symbol", "Date"]
)

print(
    f"MACD_HISTORY Loaded : {len(history_df)} Rows"
)
# =====================================================
# MODULE 4 - PART 2
# MACD FUNCTIONS
# =====================================================

def calculate_macd(df):

    df = df.copy()

    df["EMA12"] = df["Close"].ewm(
        span=12,
        adjust=False
    ).mean()

    df["EMA26"] = df["Close"].ewm(
        span=26,
        adjust=False
    ).mean()

    df["MACD"] = df["EMA12"] - df["EMA26"]

    df["SIGNAL"] = df["MACD"].ewm(
        span=9,
        adjust=False
    ).mean()

    df["HIST"] = df["MACD"] - df["SIGNAL"]

    return df


def hist_arrow(current_hist, previous_hist):

    if pd.isna(current_hist):
        return "NA"

    arrow = "↑" if current_hist >= previous_hist else "↓"

    return f"{current_hist:+.2f}{arrow}"


print("MODULE 4 PART 2 LOADED")
# =====================================================
# MODULE 4 - PART 3A
# DAILY MACD
# =====================================================

symbols = sheet_macd200.col_values(1)[1:]

macd200_output = []

for symbol in symbols:

    df = history_df[
        history_df["Symbol"] == symbol
    ].copy()

    if len(df) < 35:

        macd200_output.append([
            "NA","NA","NA",
            "NA","NA","NA",
            "NA","NA","NA"
        ])

        continue

    daily = calculate_macd(df)

    hist = daily["HIST"].tolist()

    D0 = hist_arrow(
        hist[-1],
        hist[-2]
    )

    D1 = hist_arrow(
        hist[-2],
        hist[-3]
    )

    D2 = hist_arrow(
        hist[-3],
        hist[-4]
    )

    # Weekly / Monthly next Part
    W0 = W1 = W2 = "NA"
    M0 = M1 = M2 = "NA"

    macd200_output.append([

        M0,
        M1,
        M2,

        W0,
        W1,
        W2,

        D0,
        D1,
        D2

    ])

print("MODULE 4 PART 3A LOADED")

print("MODULE 1 SUCCESS")

print("Google Connected")
