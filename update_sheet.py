import os
import json
import io
import zipfile
import requests
import gspread
import pandas as pd

from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials


# =========================================================
# CONFIGURATION
# =========================================================

SPREADSHEET_ID = "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E"

NIFTY_SHEET = "NIFTY200"
FINAL_SHEET = "Final List"

# ---------------------------------------------------------
# BOLLINGER BAND SETTINGS
# ---------------------------------------------------------

BB_LENGTH = 20
BB_MULTIPLIER = 1.5

# ---------------------------------------------------------
# STRONG GAP SETTINGS
# ---------------------------------------------------------

MIN_GAP_UP = 0.50

# ---------------------------------------------------------
# TURNOVER SETTINGS
# ---------------------------------------------------------

# Top 50 turnover stocks are considered HIGH TURNOVER
HIGH_TURNOVER_RANK = 50


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

spreadsheet = client.open_by_key(
    SPREADSHEET_ID
)


# =========================================================
# GET / CREATE SHEETS
# =========================================================

try:

    sheet_nifty = spreadsheet.worksheet(
        NIFTY_SHEET
    )

except gspread.WorksheetNotFound:

    sheet_nifty = spreadsheet.add_worksheet(
        title=NIFTY_SHEET,
        rows=500,
        cols=20
    )


try:

    sheet_final = spreadsheet.worksheet(
        FINAL_SHEET
    )

except gspread.WorksheetNotFound:

    sheet_final = spreadsheet.add_worksheet(
        title=FINAL_SHEET,
        rows=500,
        cols=20
    )


# =========================================================
# NSE BHAVCOPY
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

        print(
            f"Downloading Bhavcopy : {date_str}"
        )

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

        # -------------------------------------------------
        # CLEAN COLUMN NAMES
        # -------------------------------------------------

        df.columns = [
            str(c).strip()
            for c in df.columns
        ]

        # -------------------------------------------------
        # SYMBOL
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
        # OPEN
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
        # HIGH
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
        # LOW
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
        # CLOSE
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
        # TURNOVER
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
        # SERIES
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

        required = [
            symbol_col,
            open_col,
            high_col,
            low_col,
            close_col,
            turnover_col
        ]

        if any(
            x is None
            for x in required
        ):

            print(
                "Required Bhavcopy column missing"
            )

            return None

        # -------------------------------------------------
        # EQUITY ONLY
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
        # NUMERIC
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

latest_data = None
latest_date = None

for i in range(7):

    check_date = (
        today
        - timedelta(days=i)
    )

    if check_date.weekday() >= 5:
        continue

    result = fetch_bhavcopy(
        check_date
    )

    if result is not None:

        latest_data = result
        latest_date = check_date

        break


if latest_data is None:

    raise Exception(
        "Latest NSE Bhavcopy not found"
    )


bhavcopy = latest_data["df"]

symbol_col = latest_data["symbol_col"]
open_col = latest_data["open_col"]
high_col = latest_data["high_col"]
low_col = latest_data["low_col"]
close_col = latest_data["close_col"]
turnover_col = latest_data["turnover_col"]


print(
    "Latest Trading Day : "
    f"{latest_date.strftime('%d-%b-%Y')}"
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
# TURNOVER RANK
# =========================================================

turnover_rank = {}

for rank, (_, row) in enumerate(
    top200.iterrows(),
    start=1
):

    symbol = str(
        row[symbol_col]
    ).strip()

    turnover_rank[symbol] = rank


# =========================================================
# FIND PREVIOUS TRADING DAY
# =========================================================

previous_data = None
previous_date = None

for i in range(1, 7):

    check_date = (
        latest_date
        - timedelta(days=i)
    )

    if check_date.weekday() >= 5:
        continue

    result = fetch_bhavcopy(
        check_date
    )

    if result is not None:

        previous_data = result
        previous_date = check_date

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
    f"{previous_date.strftime('%d-%b-%Y')}"
)


# =========================================================
# PREVIOUS DAY LOOKUP
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
# HISTORICAL DATA FOR BOLLINGER BAND
# =========================================================

# We need at least 20 previous closes.
# Current day is included separately.

history_data = {}

history_dates_found = 0

check_date = (
    latest_date
    - timedelta(days=1)
)

days_checked = 0

while (
    history_dates_found < 22
    and days_checked < 45
):

    if check_date.weekday() < 5:

        result = fetch_bhavcopy(
            check_date
        )

        if result is not None:

            df_hist = result["df"]

            hist_symbol_col = result["symbol_col"]
            hist_open_col = result["open_col"]
            hist_high_col = result["high_col"]
            hist_low_col = result["low_col"]
            hist_close_col = result["close_col"]

            for _, row in df_hist.iterrows():

                symbol = str(
                    row[hist_symbol_col]
                ).strip()

                if symbol not in history_data:

                    history_data[symbol] = []

                history_data[symbol].append({

                    "date": check_date,

                    "open": float(
                        row[hist_open_col]
                    ),

                    "high": float(
                        row[hist_high_col]
                    ),

                    "low": float(
                        row[hist_low_col]
                    ),

                    "close": float(
                        row[hist_close_col]
                    )

                })

            history_dates_found += 1

    check_date -= timedelta(days=1)

    days_checked += 1


print(
    f"Historical Trading Days Loaded : "
    f"{history_dates_found}"
)


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def safe_float(value):

    try:

        value = float(value)

        if pd.isna(value):
            return None

        return value

    except:

        return None


# =========================================================
# BOLLINGER BAND
# =========================================================

def calculate_lower_bb(
    closes,
    length=20,
    multiplier=1.5
):

    if len(closes) < length:

        return None

    series = pd.Series(
        closes[-length:]
    )

    sma = series.mean()

    std = series.std(
        ddof=0
    )

    lower_band = (
        sma
        - multiplier * std
    )

    return float(
        lower_band
    )


# =========================================================
# STRONG GREEN CANDLE
# =========================================================

def is_strong_green_candle(
    open_price,
    high_price,
    low_price,
    close_price
):

    if any(
        x is None
        for x in [
            open_price,
            high_price,
            low_price,
            close_price
        ]
    ):

        return False

    candle_range = (
        high_price
        - low_price
    )

    body = abs(
        close_price
        - open_price
    )

    if candle_range <= 0:
        return False

    body_ratio = (
        body
        / candle_range
    )

    close_position = (
        close_price
        - low_price
    ) / candle_range

    return (

        close_price > open_price

        and body_ratio >= 0.60

        and close_position >= 0.75

    )


# =========================================================
# BUILD NIFTY200 OUTPUT
# =========================================================

output_rows = []


for _, row in top200.iterrows():

    symbol = str(
        row[symbol_col]
    ).strip()

    turnover = safe_float(
        row[turnover_col]
    )

    today_open = safe_float(
        row[open_col]
    )

    today_high = safe_float(
        row[high_col]
    )

    today_low = safe_float(
        row[low_col]
    )

    today_close = safe_float(
        row[close_col]
    )

    previous = previous_lookup.get(
        symbol
    )

    if previous is None:

        continue


    previous_open = previous["open"]
    previous_high = previous["high"]
    previous_low = previous["low"]
    previous_close = previous["close"]


    # =====================================================
    # PREVIOUS CANDLE
    # =====================================================

    if previous_close < previous_open:

        previous_candle = "RED 🔴"

    elif previous_close > previous_open:

        previous_candle = "GREEN 🟢"

    else:

        previous_candle = "DOJI"


    # =====================================================
    # GAP UP %
    # =====================================================

    gap_up_pct = (

        (
            today_open
            - previous_close
        )
        / previous_close
        * 100

        if previous_close != 0
        else 0

    )


    # =====================================================
    # CURRENT GAIN %
    # =====================================================

    current_gain_pct = (

        (
            today_close
            - previous_close
        )
        / previous_close
        * 100

        if previous_close != 0
        else 0

    )


    # =====================================================
    # GAP MAINTAINED
    # =====================================================

    if today_close >= today_open:

        gap_maintained = "YES ✅"

    elif today_close > previous_close:

        gap_maintained = "PARTIAL 🟡"

    else:

        gap_maintained = "NO 🔴"


    # =====================================================
    # HISTORICAL DATA
    # =====================================================

    hist = history_data.get(
        symbol,
        []
    )

    # Newest first currently.
    hist = sorted(
        hist,
        key=lambda x: x["date"]
    )


    # -----------------------------------------------------
    # CLOSES FOR BB
    # -----------------------------------------------------

    historical_closes = [

        x["close"]

        for x in hist

        if x["close"] is not None

    ]


    # Current close is added
    # for today's BB calculation.

    bb_closes = (
        historical_closes
        + [today_close]
    )


    # =====================================================
    # LOWER BB
    # =====================================================

    lower_bb = calculate_lower_bb(
        bb_closes,
        BB_LENGTH,
        BB_MULTIPLIER
    )


    # =====================================================
    # BB TOUCH
    # =====================================================

    bb_touch = False

    if lower_bb is not None:

        bb_touch = (
            today_low <= lower_bb
        )


    # =====================================================
    # PREVIOUS 3 CANDLE FALL
    # =====================================================

    falling_before_reversal = False

    if len(hist) >= 3:

        c1 = hist[-3]["close"]
        c2 = hist[-2]["close"]
        c3 = hist[-1]["close"]

        falling_before_reversal = (

            c1 > c2 > c3

        )


    # =====================================================
    # STRONG GREEN CANDLE
    # =====================================================

    strong_green = is_strong_green_candle(

        today_open,
        today_high,
        today_low,
        today_close

    )


    # =====================================================
    # BB REVERSAL
    # =====================================================

    bb_reversal = (

        bb_touch

        and
        falling_before_reversal

        and
        strong_green

    )


    # =====================================================
    # BB GAP REVERSAL
    # =====================================================

    bb_gap_reversal = (

        bb_touch

        and
        falling_before_reversal

        and
        gap_up_pct >= MIN_GAP_UP

        and
        today_close >= today_open

    )


    # =====================================================
    # TURNOVER STRENGTH
    # =====================================================

    rank = turnover_rank.get(
        symbol,
        999
    )

    high_turnover = (
        rank <= HIGH_TURNOVER_RANK
    )


    # =====================================================
    # GAP SETUP
    # =====================================================

    strong_gap = (

        previous_candle == "RED 🔴"

        and
        gap_up_pct >= MIN_GAP_UP

        and
        today_close >= today_open

    )


    # =====================================================
    # CORE GAP SIGNAL
    # =====================================================

    if strong_gap:

        gap_signal = (
            "🔥 STRONG GAP UP"
        )

    elif (

        previous_candle == "RED 🔴"

        and
        gap_up_pct > 0

        and
        today_close > previous_close

    ):

        gap_signal = (
            "🟢 GAP HOLD"
        )

    else:

        gap_signal = "—"


    # =====================================================
    # BB SIGNAL
    # =====================================================

    if bb_gap_reversal:

        bb_signal = (
            "🔥 BB GAP REVERSAL"
        )

    elif bb_reversal:

        bb_signal = (
            "🟢 BB REVERSAL"
        )

    else:

        bb_signal = "—"


    # =====================================================
    # SETUP TYPE
    # =====================================================

    if (
        bb_gap_reversal
        and high_turnover
    ):

        setup_type = (
            "💎 BB GAP REVERSAL + HIGH TURNOVER"
        )

    elif (
        bb_reversal
        and high_turnover
    ):

        setup_type = (
            "💎 BB REVERSAL + HIGH TURNOVER"
        )

    elif (
        strong_gap
        and high_turnover
    ):

        setup_type = (
            "🔥 GAP UP + HIGH TURNOVER"
        )

    elif bb_gap_reversal:

        setup_type = (
            "🔥 BB GAP REVERSAL"
        )

    elif bb_reversal:

        setup_type = (
            "🟢 BB REVERSAL"
        )

    elif strong_gap:

        setup_type = (
            "🔥 STRONG GAP UP"
        )

    else:

        setup_type = "—"


    # =====================================================
    # FINAL STRENGTH SCORE
    # =====================================================

    score = 0


    # High turnover
    if high_turnover:

        score += 25


    # Previous red candle
    if previous_candle == "RED 🔴":

        score += 15


    # Strong gap
    if gap_up_pct >= MIN_GAP_UP:

        score += 20


    # Gain maintained
    if today_close >= today_open:

        score += 15


    # Lower BB touch
    if bb_touch:

        score += 10


    # Strong green candle
    if strong_green:

        score += 10


    # BB reversal
    if bb_reversal:

        score += 5


    if score > 100:

        score = 100


    # =====================================================
    # FINAL SIGNAL
    # =====================================================

    if (
        bb_gap_reversal
        and high_turnover
    ):

        final_signal = (
            "💎 STRONG BB GAP REVERSAL"
        )

    elif (
        bb_reversal
        and high_turnover
    ):

        final_signal = (
            "💎 STRONG BB REVERSAL"
        )

    elif (
        strong_gap
        and high_turnover
    ):

        final_signal = (
            "🔥 STRONG GAP UP"
        )

    elif strong_gap:

        final_signal = (
            "🟢 GAP HOLD"
        )

    elif bb_reversal:

        final_signal = (
            "🟢 BB REVERSAL"
        )

    else:

        final_signal = "—"


    # =====================================================
    # OUTPUT
    # =====================================================

    output_rows.append([

        symbol,
        turnover,

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

        today_close,

        round(
            current_gain_pct,
            2
        ),

        gap_maintained,

        round(
            lower_bb,
            2
        )
        if lower_bb is not None
        else "",

        "YES ✅"
        if bb_touch
        else "NO",

        "YES 🔥"
        if bb_reversal
        else "NO",

        setup_type,

        rank,

        score,

        final_signal

    ])


# =========================================================
# NIFTY200 HEADER
# =========================================================

nifty_headers = [

    "NSE Code",
    "Turnover",
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
    "Lower BB (20,1.5)",
    "BB Touch?",
    "BB Reversal?",
    "Setup Type",
    "Turnover Rank",
    "Strength Score",
    "Signal"

]


# =========================================================
# UPDATE NIFTY200
# =========================================================

sheet_nifty.batch_clear(
    ["A1:S1000"]
)


sheet_nifty.update(
    range_name="A1:S1",
    values=[nifty_headers],
    value_input_option="RAW"
)


sheet_nifty.update(
    range_name="A2",
    values=output_rows,
    value_input_option="RAW"
)


# =========================================================
# FINAL LIST FILTER
# =========================================================

final_candidates = []


for row in output_rows:

    if len(row) < 19:
        continue


    symbol = row[0]
    turnover = row[1]

    previous_open = row[2]
    previous_high = row[3]
    previous_low = row[4]
    previous_close = row[5]

    previous_candle = row[6]

    today_open = row[7]
    gap_up_pct = row[8]

    cmp_price = row[9]
    current_gain_pct = row[10]

    gap_maintained = row[11]

    lower_bb = row[12]
    bb_touch = row[13]
    bb_reversal = row[14]

    setup_type = row[15]
    turnover_rank_value = row[16]
    score = row[17]
    signal = row[18]


    # =====================================================
    # HIGH TURNOVER
    # =====================================================

    high_turnover = (

        isinstance(
            turnover_rank_value,
            int
        )

        and
        turnover_rank_value
        <= HIGH_TURNOVER_RANK

    )


    # =====================================================
    # CORE GAP SETUP
    # =====================================================

    core_gap_setup = (

        previous_candle == "RED 🔴"

        and
        isinstance(
            gap_up_pct,
            (int, float)
        )

        and
        gap_up_pct >= MIN_GAP_UP

        and
        isinstance(
            cmp_price,
            (int, float)
        )

        and
        isinstance(
            today_open,
            (int, float)
        )

        and
        cmp_price >= today_open

        and
        high_turnover

    )


    # =====================================================
    # BB REVERSAL SETUP
    # =====================================================

    bb_setup = (

        bb_reversal == "YES 🔥"

        and
        high_turnover

    )


    # =====================================================
    # BB GAP REVERSAL
    # =====================================================

    bb_gap_setup = (

        "BB GAP REVERSAL"
        in str(setup_type)

        and
        high_turnover

    )


    # =====================================================
    # FINAL FILTER
    # =====================================================

    if (

        core_gap_setup

        or
        bb_setup

        or
        bb_gap_setup

    ):

        final_candidates.append(row)


# =========================================================
# SORT FINAL LIST
# =========================================================

final_candidates.sort(

    key=lambda x: (
        x[17],
        -x[16],
        x[8]
    ),

    reverse=True

)


# =========================================================
# FINAL LIST OUTPUT
# =========================================================

final_output = []


for rank, row in enumerate(
    final_candidates,
    start=1
):

    final_output.append([

        rank,

        row[0],
        row[1],

        row[2],
        row[3],
        row[4],
        row[5],

        row[6],

        row[7],
        row[8],

        row[9],
        row[10],

        row[11],

        row[12],

        row[13],

        row[14],

        row[15],

        row[16],

        row[17],

        row[18]

    ])


# =========================================================
# FINAL LIST HEADERS
# =========================================================

final_headers = [

    "Rank",
    "NSE Code",
    "Turnover",

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

    "Lower BB (20,1.5)",
    "BB Touch?",
    "BB Reversal?",

    "Setup Type",

    "Turnover Rank",

    "Strength Score",

    "Signal"

]


# =========================================================
# CLEAR FINAL LIST
# =========================================================

sheet_final.batch_clear(
    ["A1:T1000"]
)


# =========================================================
# WRITE FINAL LIST HEADER
# =========================================================

sheet_final.update(
    range_name="A1:T1",
    values=[final_headers],
    value_input_option="RAW"
)


# =========================================================
# WRITE FINAL LIST
# =========================================================

if final_output:

    sheet_final.update(
        range_name="A2",
        values=final_output,
        value_input_option="RAW"
    )


# =========================================================
# FORMATTING
# =========================================================

try:

    sheet_nifty.format(
        "A1:S1",
        {
            "textFormat": {
                "bold": True
            },
            "horizontalAlignment": "CENTER"
        }
    )

    sheet_final.format(
        "A1:T1",
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

    sheet_final.freeze(
        rows=1
    )

except Exception as e:

    print(
        f"Formatting Warning : {e}"
    )


# =========================================================
# FINAL LOG
# =========================================================

print(
    "========================================"
)

print(
    "NIFTY200 GAP + BB SCREENER UPDATED"
)

print(
    f"Trading Date : "
    f"{latest_date.strftime('%d-%b-%Y')}"
)

print(
    f"Previous Date : "
    f"{previous_date.strftime('%d-%b-%Y')}"
)

print(
    f"Stocks : {len(output_rows)}"
)

print(
    f"Final Strong Stocks : "
    f"{len(final_output)}"
)

print(
    "Bollinger Band : 20, 1.5"
)

print(
    "High Turnover : Top 50"
)

print(
    "MACD : REMOVED"
)

print(
    "========================================"

)
