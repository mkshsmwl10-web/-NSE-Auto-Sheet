import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
import zipfile
import io
from datetime import datetime, timedelta
import os
import json

# Credentials Setup
creds_json = os.environ.get('GCP_CREDENTIALS')
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

# Google Sheet ID
spreadsheet_id = "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E"

worksheet = client.open_by_key(
    spreadsheet_id
).worksheet("Top 250 Stocks")

# NSE Data Fetcher
def fetch_bhavcopy_for_date(date_obj):

    date_str = date_obj.strftime("%Y%m%d")

    url = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv.zip"

    headers = {
        'User-Agent': 'Mozilla/5.0'
    }

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=20
        )

        if response.status_code == 200:

            with zipfile.ZipFile(
                io.BytesIO(response.content)
            ) as z:

                csv_filename = z.namelist()[0]

                with z.open(csv_filename) as f:

                    df = pd.read_csv(f)

                    sym_col = 'TckrSymb'
                    close_col = 'ClsPric'
                    vol_col = 'TtlTradgVol'
                    series_col = 'SctySrs'

                    # EQ only
                    df = df[
                        df[series_col]
                        .astype(str)
                        .str.strip() == 'EQ'
                    ]

                    # Remove ETFs
                    filter_keywords = 'BEES|ETF|GOLD|LIQUID|SILVER'

                    df = df[
                        ~df[sym_col]
                        .astype(str)
                        .str.contains(
                            filter_keywords,
                            case=False,
                            na=False
                        )
                    ]

                    df_top = df.sort_values(
                        by=vol_col,
                        ascending=False
                    ).head(250)

                    return df_top[
                        [sym_col, vol_col, close_col]
                    ].values.tolist()

        return None

    except Exception as e:
        print(e)
        return None

# Main Logic
date = datetime.now()

data_to_insert = None

for i in range(5):

    test_date = date - timedelta(days=i)

    if test_date.weekday() >= 5:
        continue

    data_to_insert = fetch_bhavcopy_for_date(
        test_date
    )

    if data_to_insert:
        break

# Update Sheet
if data_to_insert:

    worksheet.batch_clear(['A2:C251'])

    worksheet.update(
        'A2',
        data_to_insert
    )

    print("SUCCESS: Sheet Updated!")
