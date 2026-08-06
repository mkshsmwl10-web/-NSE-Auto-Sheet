import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
import zipfile
import io
from datetime import datetime, timedelta
import os
import json

# =========================
# 1. Google Credentials
# =========================

creds_json = os.environ.get('GCP_CREDENTIALS')

if not creds_json:
    print("CRITICAL ERROR: GCP_CREDENTIALS Secret Missing!")
    exit(1)

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

# =========================
# 2. Google Sheet Setup
# =========================

spreadsheet_id = "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E"

fixed_sheet = client.open_by_key(
    spreadsheet_id
).fixed_sheet("NIFTY200")
fixed_sheet = client.open_by_key(
    spreadsheet_id
).fixed_sheet("NIFTY200_FIXED")
macd_sheet = client.open_by_key(
    spreadsheet_id
).fixed_sheet("MACD_HISTORY")
macd200_sheet = client.open_by_key(
    spreadsheet_id
).fixed_sheet("MACD200")
# =========================
# 3. NSE Bhavcopy Fetcher
# =========================

def fetch_bhavcopy_for_date(date_obj):
    # =========================
# Today's Bhavcopy Dictionary
# =========================

today_data = {}

for row in data_to_insert:
    symbol = str(row[0]).strip()
    close = row[2]

    today_data[symbol] = close

    date_str = date_obj.strftime("%Y%m%d")

    url = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv.zip"

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:

        print(f"Checking Bhavcopy for {date_str}")

        response = requests.get(
            url,
            headers=headers,
            timeout=20
        )

        if response.status_code != 200:
            print("File not found")
            return None

        with zipfile.ZipFile(
            io.BytesIO(response.content)
        ) as z:

            csv_filename = z.namelist()[0]

            with z.open(csv_filename) as f:

                df = pd.read_csv(f)

        # Remove extra spaces
        df.columns = [c.strip() for c in df.columns]

        # Dynamic column names
        sym_col = next(
            (c for c in ['TckrSymb', 'SYMBOL'] if c in df.columns),
            None
        )

        close_col = next(
            (c for c in ['ClsPric', 'CLOSE'] if c in df.columns),
            None
        )

        series_col = next(
            (c for c in ['SctySrs', 'SERIES'] if c in df.columns),
            None
        )

        turnover_col = next(
            (
                c for c in [
                    'TtlTrfVal',
                    'TtlTrdVal',
                    'TURNOVER_LACS',
                    'TURNOVER'
                ]
                if c in df.columns
            ),
            None
        )

        if not all([sym_col, close_col, turnover_col]):
            print("Required columns missing")
            return None

        # EQ Series only
        if series_col:
            df = df[
                df[series_col]
                .astype(str)
                .str.strip() == 'EQ'
            ]

        # Remove ETF / BEES
        filter_keywords = 'BEES|ETF|GOLD|LIQUID|SILVER|INDEX'

        df = df[
            ~df[sym_col]
            .astype(str)
            .str.contains(
                filter_keywords,
                case=False,
                na=False
            )
        ]

        # Numeric conversion
        df[turnover_col] = pd.to_numeric(
            df[turnover_col],
            errors='coerce'
        )

        df = df.dropna(subset=[turnover_col])

        # Sort by Turnover
        df_top = df.sort_values(
            by=turnover_col,
            ascending=False
        ).head(200)

        # Final output
        final_df = df_top[
            [sym_col, turnover_col, close_col]
        ]

        return final_df.values.tolist()

    except Exception as e:

        print(f"NSE Fetch Error: {str(e)}")

        return None

# =========================
# 4. Main Execution Logic
# =========================

date = datetime.now()

data_to_insert = None

fetched_date_str = ""

for i in range(7):

    test_date = date - timedelta(days=i)

    # Skip Saturday/Sunday
    if test_date.weekday() >= 5:
        continue

    data_to_insert = fetch_bhavcopy_for_date(
        test_date
    )

    if data_to_insert:

        fetched_date_str = test_date.strftime(
            '%d-%b-%Y'
        )

        break
# =========================
# 5. Update Google Sheet
# =========================

if data_to_insert:

    try:

        worksheet.batch_clear(['A2:C1000'])

        worksheet.update(
            'A2',
            data_to_insert
        )

        macd200_sheet.batch_clear(['A2:J1000'])

        macd200_rows = []

        for row in data_to_insert:

            macd200_rows.append([
                row[0],
                "NA","NA","NA",
                "NA","NA","NA",
                "NA","NA","NA"
            ])

        macd200_sheet.update(
            'A2',
            macd200_rows
        )

        today_db = datetime.now().strftime("%Y-%m-%d")

        history_rows = []

        for row in fixed_sheet.get_all_values()

            history_rows.append([
                today_db,
                row[0],
                row[2]
            ])

        if history_rows:

            macd_sheet.append_rows(
                history_rows,
                value_input_option='RAW'
            )

        ist_now = (
            datetime.utcnow() +
            timedelta(hours=5, minutes=30)
        ).strftime('%d-%b %H:%M')

        status_msg = (
            f"Data Date: {fetched_date_str} | "
            f"Updated: {ist_now} IST"
        )

       fixed_sheet.update(
            'K2',
            [[status_msg]]
        )

        print(
            f"SUCCESS: NIFTY200 Updated for {fetched_date_str}"
        )

    except Exception as e:

        print(
            f"Google Sheet Update Error: {str(e)}"
        )

else:

    print(
        "FAILED: No Bhavcopy Data Found in Last 7 Days"
    )
# ==========================================================
# MODULE 3 - PART 1
# READ MACD HISTORY + MACD FUNCTIONS
# ==========================================================

import numpy as np

# ---------------------------------
# Read MACD_HISTORY Sheet
# ---------------------------------

history_data = macd_sheet.get_all_values()

if len(history_data) <= 1:
    print("MACD_HISTORY Empty")
    exit()

history_df = pd.DataFrame(
    history_data[1:],
    columns=history_data[0]
)

history_df["Date"] = pd.to_datetime(history_df["Date"])

history_df["Close"] = pd.to_numeric(
    history_df["Close"],
    errors="coerce"
)

history_df = history_df.dropna(subset=["Close"])

history_df = history_df.sort_values(
    ["Symbol", "Date"]
)

# ---------------------------------
# MACD Function
# ---------------------------------

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

    df["MACD"] = (
        df["EMA12"] -
        df["EMA26"]
    )

    df["SIGNAL"] = df["MACD"].ewm(
        span=9,
        adjust=False
    ).mean()

    df["HIST"] = (
        df["MACD"] -
        df["SIGNAL"]
    )

    return df

# ---------------------------------
# Histogram + Arrow
# ---------------------------------

def hist_arrow(hist_now, hist_prev):

    if pd.isna(hist_now):
        return "NA"

    arrow = "↑"

    if hist_now < hist_prev:
        arrow = "↓"

    return f"{hist_now:+.2f}{arrow}"

print("MODULE 3 PART 1 LOADED")
# ==========================================================
# MODULE 3 - PART 2
# DAILY / WEEKLY / MONTHLY MACD
# ==========================================================

symbols = macd200_sheet.col_values(1)[1:]

macd200_output = []

for symbol in symbols:

    try:

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

        # ==========================
        # DAILY
        # ==========================

        daily = calculate_macd(df)

        d_hist = daily["HIST"].tolist()

        D0 = hist_arrow(
            d_hist[-1],
            d_hist[-2]
        )

        D1 = hist_arrow(
            d_hist[-2],
            d_hist[-3]
        )

        D2 = hist_arrow(
            d_hist[-3],
            d_hist[-4]
        )

        # ==========================
        # WEEKLY
        # ==========================

        weekly = (
            df
            .set_index("Date")
            .resample("W-FRI")
            .last()
            .dropna()
            .reset_index()
        )

        if len(weekly) >= 35:

            weekly = calculate_macd(weekly)

            w_hist = weekly["HIST"].tolist()

            W0 = hist_arrow(
                w_hist[-1],
                w_hist[-2]
            )

            W1 = hist_arrow(
                w_hist[-2],
                w_hist[-3]
            )

            W2 = hist_arrow(
                w_hist[-3],
                w_hist[-4]
            )

        else:

            W0 = W1 = W2 = "NA"

        # ==========================
        # MONTHLY
        # ==========================

        monthly = (
            df
            .set_index("Date")
            .resample("ME")
            .last()
            .dropna()
            .reset_index()
        )

        if len(monthly) >= 35:

            monthly = calculate_macd(monthly)

            m_hist = monthly["HIST"].tolist()

            M0 = hist_arrow(
                m_hist[-1],
                m_hist[-2]
            )

            M1 = hist_arrow(
                m_hist[-2],
                m_hist[-3]
            )

            M2 = hist_arrow(
                m_hist[-3],
                m_hist[-4]
            )

        else:

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

    except Exception as e:

        print(symbol, e)

        macd200_output.append([

            "NA","NA","NA",

            "NA","NA","NA",

            "NA","NA","NA"

        ])

print("MODULE 3 PART 2 LOADED")
# =====================================
# Update MACD200 Sheet
# =====================================

macd200_sheet.update(
    range_name="B2:J201",
    values=macd200_output
)

print("MACD200 UPDATED SUCCESSFULLY")
# =========================
# Read Fixed NIFTY200 List
# =========================

fixed_rows = fixed_sheet.get_all_values()

fixed_symbols = [
    row[0].strip()
    for row in fixed_rows[1:]
    if row and row[0].strip()
]
