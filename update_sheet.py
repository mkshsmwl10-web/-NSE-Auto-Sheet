import gspread
from oauth2client.service_account import ServiceAccountCredentials

import pandas as pd
import requests
import zipfile
import io
import json
import os

from datetime import datetime, timedelta


# =========================================================
# GOOGLE LOGIN
# =========================================================

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


# =========================================================
# GOOGLE SHEET
# =========================================================

SPREADSHEET_ID = "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E"

sheet_nifty = client.open_by_key(
    SPREADSHEET_ID
).worksheet("NIFTY200")


# =========================================================
# BHAVCOPY DOWNLOAD
# =========================================================

def fetch_bhavcopy(date_obj):

    date_str = date_obj.strftime("%Y%m%d")

    url = (
        "https://nsearchives.nseindia.com/content/cm/"
        f"BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv.zip"
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/151.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Referer": "https://www.nseindia.com/"
    }

    try:

        print(f"Downloading Bhavcopy : {date_str}")

        response = requests.get(
            url,
            headers=headers,
            timeout=30
        )

        if response.status_code != 200:
            print(
                f"Bhavcopy not found : "
                f"{date_obj.strftime('%d-%b-%Y')}"
            )
            return None

        with zipfile.ZipFile(
            io.BytesIO(response.content)
        ) as z:

            csv_file = z.namelist()[0]

            with z.open(csv_file) as f:

                df = pd.read_csv(f)

        # -------------------------------------------------
        # CLEAN COLUMN NAMES
        # -------------------------------------------------

        df.columns = [
            str(c).strip()
            for c in df.columns
        ]

        # -------------------------------------------------
        # SYMBOL COLUMN
        # -------------------------------------------------

        symbol_col = next(
            (
                c for c in
                [
                    "TckrSymb",
                    "SYMBOL"
                ]
                if c in df.columns
            ),
            None
        )

        # -------------------------------------------------
        # OPEN COLUMN
        # -------------------------------------------------

        open_col = next(
            (
                c for c in
                [
                    "OpnPric",
                    "OPEN",
                    "Open"
                ]
                if c in df.columns
            ),
            None
        )

        # -------------------------------------------------
        # HIGH COLUMN
        # -------------------------------------------------

        high_col = next(
            (
                c for c in
                [
                    "HghPric",
                    "HIGH",
                    "High"
                ]
                if c in df.columns
            ),
            None
        )

        # -------------------------------------------------
        # LOW COLUMN
        # -------------------------------------------------

        low_col = next(
            (
                c for c in
                [
                    "LwPric",
                    "LOW",
                    "Low"
                ]
                if c in df.columns
            ),
            None
        )

        # -------------------------------------------------
        # CLOSE COLUMN
        # -------------------------------------------------

        close_col = next(
            (
                c for c in
                [
                    "ClsPric",
                    "CLOSE",
                    "Close"
                ]
                if c in df.columns
            ),
            None
        )

        # -------------------------------------------------
        # TURNOVER COLUMN
        # -------------------------------------------------

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

        # -------------------------------------------------
        # SERIES COLUMN
        # -------------------------------------------------

        series_col = next(
            (
                c for c in
                [
                    "SctySrs",
                    "SERIES"
                ]
                if c in df.columns
            ),
            None
        )

        # -------------------------------------------------
        # VALIDATION
        # -------------------------------------------------

        if symbol_col is None:
            print("Symbol column not found")
            return None

        if open_col is None:
            print("Open column not found")
            return None

        if high_col is None:
            print("High column not found")
            return None

        if low_col is None:
            print("Low column not found")
            return None

        if close_col is None:
            print("Close column not found")
            return None

        if turnover_col is None:
            print("Turnover column not found")
            return None

        # -------------------------------------------------
        # ONLY EQUITY
        # -------------------------------------------------

        if series_col:

            df = df[
                df[series_col]
                .astype(str)
                .str.strip()
                .str.upper()
                == "EQ"
            ]

        # -------------------------------------------------
        # NUMERIC DATA
        # -------------------------------------------------

        for col in [
            open_col,
            high_col,
            low_col,
            close_col,
            turnover_col
        ]:

            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

        df = df.dropna(
            subset=[
                open_col,
                high_col,
                low_col,
                close_col,
                turnover_col
            ]
        )

        return {
            "df": df,
            "symbol_col": symbol_col,
            "open_col": open_col,
            "high_col": high_col,
            "low_col": low_col,
            "close_col": close_col,
            "turnover_col": turnover_col
        }

    except Exception as e:

        print(
            f"Bhavcopy Error : {e}"
        )

        return None


# =========================================================
# FIND LATEST TRADING DAY
# =========================================================

today = datetime.now()

today_data = None
today_date_obj = None
today_date_text = ""

for i in range(7):

    check_date = today - timedelta(days=i)

    if check_date.weekday() >= 5:
        continue

    result = fetch_bhavcopy(check_date)

    if result is not None:

        today_data = result
        today_date_obj = check_date
        today_date_text = check_date.strftime(
            "%d-%b-%Y"
        )

        break


if today_data is None:

    raise Exception(
        "Latest NSE Bhavcopy not found"
    )


# =========================================================
# TODAY DATA
# =========================================================

bhavcopy = today_data["df"]

symbol_col = today_data["symbol_col"]
open_col = today_data["open_col"]
high_col = today_data["high_col"]
low_col = today_data["low_col"]
close_col = today_data["close_col"]
turnover_col = today_data["turnover_col"]


print(
    f"Latest Trading Day : {today_date_text}"
)


# =========================================================
# FILTER TOP 200 BY TURNOVER
# =========================================================

filter_words = (
    "BEES|ETF|GOLD|LIQUID|SILVER|INDEX"
)


top200 = (
    bhavcopy[
        ~bhavcopy[symbol_col]
        .astype(str)
        .str.contains(
            filter_words,
            case=False,
            na=False
        )
    ]
    .sort_values(
        turnover_col,
        ascending=False
    )
    .head(200)
    .copy()
)


print(
    f"Top 200 Stocks Found : {len(top200)}"
)


# =========================================================
# FIND PREVIOUS TRADING DAY
# =========================================================

previous_data = None
previous_date_obj = None

for i in range(1, 8):

    check_date = (
        today_date_obj
        - timedelta(days=i)
    )

    if check_date.weekday() >= 5:
        continue

    result = fetch_bhavcopy(check_date)

    if result is not None:

        previous_data = result
        previous_date_obj = check_date

        break


if previous_data is None:

    raise Exception(
        "Previous Trading Day Bhavcopy not found"
    )


previous_df = previous_data["df"]

prev_symbol_col = previous_data["symbol_col"]
prev_open_col = previous_data["open_col"]
prev_high_col = previous_data["high_col"]
prev_low_col = previous_data["low_col"]
prev_close_col = previous_data["close_col"]


print(
    "Previous Trading Day : "
    f"{previous_date_obj.strftime('%d-%b-%Y')}"
)


# =========================================================
# PREVIOUS DAY DICTIONARY
# =========================================================

previous_lookup = {}

for _, row in previous_df.iterrows():

    symbol = str(
        row[prev_symbol_col]
    ).strip()

    previous_lookup[symbol] = {

        "open": float(
            row[prev_open_col]
        ),

        "high": float(
            row[prev_high_col]
        ),

        "low": float(
            row[prev_low_col]
        ),

        "close": float(
            row[prev_close_col]
        )
    }


# =========================================================
# CREATE FINAL NIFTY200 OUTPUT
# =========================================================

output_rows = []


for _, row in top200.iterrows():

    symbol = str(
        row[symbol_col]
    ).strip()

    turnover = float(
        row[turnover_col]
    )

    today_open = float(
        row[open_col]
    )

    today_close = float(
        row[close_col]
    )

    # -----------------------------------------------------
    # PREVIOUS DAY DATA
    # -----------------------------------------------------

    previous = previous_lookup.get(
        symbol
    )

    if previous is None:

        output_rows.append([
            symbol,
            turnover,
            today_close,
            "",
            "",
            "",
            "",
            "NA",
            today_open,
            "",
            today_close,
            "",
            "NA",
            "—"
        ])

        continue


    previous_open = previous["open"]
    previous_high = previous["high"]
    previous_low = previous["low"]
    previous_close = previous["close"]


    # -----------------------------------------------------
    # PREVIOUS CANDLE
    # -----------------------------------------------------

    if previous_close < previous_open:

        previous_candle = "RED 🔴"

    elif previous_close > previous_open:

        previous_candle = "GREEN 🟢"

    else:

        previous_candle = "DOJI"


    # -----------------------------------------------------
    # GAP UP %
    # -----------------------------------------------------

    if previous_close != 0:

        gap_up_pct = (
            (today_open - previous_close)
            / previous_close
        ) * 100

    else:

        gap_up_pct = 0


    # -----------------------------------------------------
    # CMP
    # -----------------------------------------------------

    # EOD Bhavcopy mein latest available price
    # Close Price hi hai

    cmp_price = today_close


    # -----------------------------------------------------
    # CURRENT GAIN %
    # -----------------------------------------------------

    if previous_close != 0:

        current_gain_pct = (
            (cmp_price - previous_close)
            / previous_close
        ) * 100

    else:

        current_gain_pct = 0


    # -----------------------------------------------------
    # GAP MAINTAINED
    # -----------------------------------------------------

    if cmp_price >= today_open:

        gap_maintained = "YES ✅"

    elif cmp_price > previous_close:

        gap_maintained = "PARTIAL 🟡"

    else:

        gap_maintained = "NO 🔴"


    # -----------------------------------------------------
    # SIGNAL
    # -----------------------------------------------------

    if (
        previous_close < previous_open
        and gap_up_pct >= 0.50
        and cmp_price >= today_open
    ):

        signal = "🔥 STRONG GAP UP"


    elif (
        previous_close < previous_open
        and gap_up_pct > 0
        and cmp_price > previous_close
    ):

        signal = "🟢 GAP HOLD"


    elif (
        previous_close < previous_open
        and gap_up_pct > 0
        and cmp_price <= previous_close
    ):

        signal = "🔴 GAP FAILED"


    else:

        signal = "—"


    # -----------------------------------------------------
    # FINAL ROW
    # -----------------------------------------------------

    output_rows.append([

        symbol,
        turnover,
        today_close,

        previous_open,
        previous_high,
        previous_low,
        previous_close,

        previous_candle,

        today_open,

        round(
            gap_up_pct,
            2
        ),

        cmp_price,

        round(
            current_gain_pct,
            2
        ),

        gap_maintained,

        signal

    ])


# =========================================================
# GOOGLE SHEET HEADER
# =========================================================

headers = [

    "NSE Code",
    "Turnover",
    "Close Price",

    "Previous Open",
    "Previous High",
    "Previous Low",
    "Previous Close",

    "Previous Candle",

    "Today Open",
    "Gap Up %",

    "CMP",
    "Current Gain %",

    "Gap Maintained?",
    "Signal"

]


# =========================================================
# CLEAR OLD NIFTY200 DATA
# =========================================================

sheet_nifty.batch_clear(
    ["A1:N1000"]
)


# =========================================================
# WRITE HEADER
# =========================================================

sheet_nifty.update(
    "A1",
    [headers],
    value_input_option="RAW"
)


# =========================================================
# WRITE DATA
# =========================================================

if output_rows:

    sheet_nifty.update(
        "A2",
        output_rows,
        value_input_option="RAW"
    )


# =========================================================
# FORMATTING
# =========================================================

try:

    sheet_nifty.format(
        "A1:N1",
        {
            "textFormat": {
                "bold": True
            },
            "horizontalAlignment": "CENTER"
        }
    )

    sheet_nifty.freeze(
        rows=1
    )

except Exception as e:

    print(
        f"Formatting Warning : {e}"
    )


# =========================================================
# FINAL MESSAGE
# =========================================================

print(
    "========================================"
)

print(
    "NIFTY200 GAP-UP SCREENER UPDATED"
)

print(
    f"Trading Date : {today_date_text}"
)

print(
    "Previous Date : "
    f"{previous_date_obj.strftime('%d-%b-%Y')}"
)

print(
    f"Stocks : {len(output_rows)}"
)

print(
    "MACD MODULE : REMOVED"
)

print(
    "========================================"
)
