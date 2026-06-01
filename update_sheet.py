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

worksheet = client.open_by_key(
    spreadsheet_id
).worksheet("Top 250 Stocks")

macd_sheet = client.open_by_key(
    spreadsheet_id
).worksheet("MACD_HISTORY")
# =========================
# 3. NSE Bhavcopy Fetcher
# =========================

def fetch_bhavcopy_for_date(date_obj):

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
        ).head(250)

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

        # Clear old data
        worksheet.batch_clear(['A2:C251'])

        # Insert new data
        worksheet.update(
            'A2',
            data_to_insert
        )

        # =========================
        # Save History For MACD
        # =========================

        today_db = datetime.now().strftime("%Y-%m-%d")

        history_rows = []

        for row in data_to_insert:

            symbol = row[0]
            close_price = row[2]

            history_rows.append([
                today_db,
                symbol,
                close_price
            ])

        if history_rows:

            macd_sheet.append_rows(
                history_rows,
                value_input_option='RAW'
            )

        # Status message
        ist_now = (
            datetime.utcnow() +
            timedelta(hours=5, minutes=30)
        ).strftime('%d-%b %H:%M')

        status_msg = (
            f"Data Date: {fetched_date_str} | "
            f"Updated: {ist_now} IST"
        )

        worksheet.update(
            'K2',
            [[status_msg]]
        )

        print(
            f"SUCCESS: Top 250 Turnover Stocks Updated for {fetched_date_str}"
        )

    except Exception as e:

        print(
            f"Google Sheet Update Error: {str(e)}"
        )

else:

    print(
        "FAILED: No Bhavcopy Data Found in Last 7 Days"
    )
