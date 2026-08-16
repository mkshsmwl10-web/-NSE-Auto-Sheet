# =========================================================
# NIFTY 200 REVERSAL + GAP-UP SCREENER
# VERSION 2
#
# LOGIC:
# 1. TOP 200 BY TURNOVER
# 2. PREVIOUS RED CANDLE
# 3. LOWER BOLLINGER BAND 20, 1.5
# 4. SELLING EXHAUSTION
# 5. LOWER BB REJECTION
# 6. TODAY BREAKS REVERSAL CANDLE HIGH
# 7. REVERSAL LOW PROTECTED
# 8. HIGH TURNOVER
# 9. RED -> GAP -> HOLD
#
# MACD : REMOVED
# MACD200 : REMOVED
# MACD_HISTORY : REMOVED
# NIFTY200_FIXED : REMOVED
# =========================================================


import os
import json
import io
import zipfile
import requests
import gspread
import pandas as pd

from datetime import datetime, timedelta
from oauth2client.service_account import (
    ServiceAccountCredentials
)


# =========================================================
# CONFIGURATION
# =========================================================

SPREADSHEET_ID = (
    "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E"
)

NIFTY_SHEET = "NIFTY200"
FINAL_SHEET = "Final List"


# =========================================================
# BOLLINGER SETTINGS
# =========================================================

BB_LENGTH = 20
BB_MULTIPLIER = 1.5


# =========================================================
# GAP SETTINGS
# =========================================================

MIN_GAP_UP = 0.50


# =========================================================
# HIGH TURNOVER
# =========================================================

HIGH_TURNOVER_RANK = 50


# =========================================================
# HISTORICAL DAYS
# =========================================================

# 20 BB periods + extra candles
HISTORY_TRADING_DAYS = 25


# =========================================================
# GOOGLE LOGIN
# =========================================================

creds_json = os.environ.get(
    "GCP_CREDENTIALS"
)

if not creds_json:

    raise Exception(
        "GCP_CREDENTIALS Secret Missing"
    )


creds_dict = json.loads(
    creds_json
)


scope = [

    "https://spreadsheets.google.com/feeds",

    "https://www.googleapis.com/auth/drive"

]


creds = (
    ServiceAccountCredentials
    .from_json_keyfile_dict(
        creds_dict,
        scope
    )
)


client = gspread.authorize(
    creds
)


# =========================================================
# GOOGLE SHEET
# =========================================================

spreadsheet = (
    client
    .open_by_key(
        SPREADSHEET_ID
    )
)


# =========================================================
# GET / CREATE NIFTY200
# =========================================================

try:

    sheet_nifty = (
        spreadsheet
        .worksheet(
            NIFTY_SHEET
        )
    )

except gspread.WorksheetNotFound:

    sheet_nifty = (
        spreadsheet
        .add_worksheet(
            title=NIFTY_SHEET,
            rows=500,
            cols=30
        )
    )


# =========================================================
# GET / CREATE FINAL LIST
# =========================================================

try:

    sheet_final = (
        spreadsheet
        .worksheet(
            FINAL_SHEET
        )
    )

except gspread.WorksheetNotFound:

    sheet_final = (
        spreadsheet
        .add_worksheet(
            title=FINAL_SHEET,
            rows=500,
            cols=30
        )
    )


# =========================================================
# NSE BHAVCOPY
# =========================================================

def fetch_bhavcopy(date_obj):

    date_str = (
        date_obj.strftime(
            "%Y%m%d"
        )
    )


    url = (
        "https://nsearchives.nseindia.com/"
        "content/cm/"
        f"BhavCopy_NSE_CM_0_0_0_"
        f"{date_str}_F_0000.csv.zip"
    )


    headers = {

        "User-Agent":
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/151.0 Safari/537.36",

        "Accept":
            "*/*",

        "Referer":
            "https://www.nseindia.com/"

    }


    try:

        print(
            f"Downloading Bhavcopy : "
            f"{date_str}"
        )


        response = requests.get(

            url,

            headers=headers,

            timeout=30

        )


        if response.status_code != 200:

            print(
                f"HTTP Status : "
                f"{response.status_code}"
            )

            return None


        with zipfile.ZipFile(

            io.BytesIO(
                response.content
            )

        ) as z:

            csv_file = (
                z.namelist()[0]
            )


            with z.open(
                csv_file
            ) as f:

                df = pd.read_csv(
                    f
                )


        # -------------------------------------------------
        # CLEAN COLUMNS
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

                c

                for c in [

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

                c

                for c in [

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

                c

                for c in [

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

                c

                for c in [

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

                c

                for c in [

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

                c

                for c in [

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

                c

                for c in [

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

            print(
                "Symbol column missing"
            )

            return None


        if open_col is None:

            print(
                "Open column missing"
            )

            return None


        if high_col is None:

            print(
                "High column missing"
            )

            return None


        if low_col is None:

            print(
                "Low column missing"
            )

            return None


        if close_col is None:

            print(
                "Close column missing"
            )

            return None


        if turnover_col is None:

            print(
                "Turnover column missing"
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

        numeric_columns = [

            open_col,
            high_col,
            low_col,
            close_col,
            turnover_col

        ]


        for col in numeric_columns:

            df[col] = pd.to_numeric(

                df[col],

                errors="coerce"

            )


        df = df.dropna(

            subset=numeric_columns

        )


        return {

            "df": df,

            "symbol_col":
                symbol_col,

            "open_col":
                open_col,

            "high_col":
                high_col,

            "low_col":
                low_col,

            "close_col":
                close_col,

            "turnover_col":
                turnover_col

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


bhavcopy = (
    latest_data["df"]
)


symbol_col = (
    latest_data["symbol_col"]
)

open_col = (
    latest_data["open_col"]
)

high_col = (
    latest_data["high_col"]
)

low_col = (
    latest_data["low_col"]
)

close_col = (
    latest_data["close_col"]
)

turnover_col = (
    latest_data["turnover_col"]
)


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
    f"Top 200 Stocks Found : "
    f"{len(top200)}"
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


    turnover_rank[
        symbol
    ] = rank


# =========================================================
# PREVIOUS TRADING DAY
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
        "Previous Trading Day "
        "Bhavcopy not found"
    )


previous_df = (
    previous_data["df"]
)


prev_symbol_col = (
    previous_data["symbol_col"]
)

prev_open_col = (
    previous_data["open_col"]
)

prev_high_col = (
    previous_data["high_col"]
)

prev_low_col = (
    previous_data["low_col"]
)

prev_close_col = (
    previous_data["close_col"]
)


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


    previous_lookup[
        symbol
    ] = {

        "open":
            float(row[prev_open_col]),

        "high":
            float(row[prev_high_col]),

        "low":
            float(row[prev_low_col]),

        "close":
            float(row[prev_close_col])

    }


# =========================================================
# HISTORICAL DATA
# =========================================================
#
# We download historical OHLC data so that the
# Lower Bollinger Band can be calculated correctly.
#
# Current day + previous days are kept separately.
#
# =========================================================

history_data = {}


history_dates_found = 0


check_date = (
    latest_date
    - timedelta(days=1)
)


days_checked = 0


while (

    history_dates_found
    < HISTORY_TRADING_DAYS

    and

    days_checked
    < 45

):

    if check_date.weekday() < 5:

        result = fetch_bhavcopy(

            check_date

        )


        if result is not None:

            hist_df = (
                result["df"]
            )


            hist_symbol_col = (
                result["symbol_col"]
            )

            hist_open_col = (
                result["open_col"]
            )

            hist_high_col = (
                result["high_col"]
            )

            hist_low_col = (
                result["low_col"]
            )

            hist_close_col = (
                result["close_col"]
            )


            for _, row in hist_df.iterrows():

                symbol = str(

                    row[hist_symbol_col]

                ).strip()


                if symbol not in history_data:

                    history_data[
                        symbol
                    ] = []


                history_data[
                    symbol
                ].append({

                    "date":
                        check_date,

                    "open":
                        float(
                            row[
                                hist_open_col
                            ]
                        ),

                    "high":
                        float(
                            row[
                                hist_high_col
                            ]
                        ),

                    "low":
                        float(
                            row[
                                hist_low_col
                            ]
                        ),

                    "close":
                        float(
                            row[
                                hist_close_col
                            ]
                        )

                })


            history_dates_found += 1


    check_date -= timedelta(
        days=1
    )


    days_checked += 1


print(
    "Historical Trading Days Loaded : "
    f"{history_dates_found}"
)


# =========================================================
# HELPER
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

def calculate_bb(
    candles,
    length=20,
    multiplier=1.5
):

    if len(candles) < length:

        return None, None, None


    closes = [

        x["close"]

        for x in candles[-length:]

    ]


    series = pd.Series(
        closes
    )


    middle = (
        series.mean()
    )


    std = (
        series.std(
            ddof=0
        )
    )


    upper = (

        middle
        + multiplier * std

    )


    lower = (

        middle
        - multiplier * std

    )


    return (

        float(upper),

        float(middle),

        float(lower)

    )


# =========================================================
# CANDLE QUALITY
# =========================================================

def candle_strength(

    open_price,
    high_price,
    low_price,
    close_price

):

    candle_range = (

        high_price
        - low_price

    )


    if candle_range <= 0:

        return {

            "body_ratio": 0,

            "close_position": 0,

            "lower_wick_ratio": 0,

            "upper_wick_ratio": 0

        }


    body = abs(

        close_price
        - open_price

    )


    lower_wick = (

        min(
            open_price,
            close_price
        )
        - low_price

    )


    upper_wick = (

        high_price
        - max(
            open_price,
            close_price
        )

    )


    close_position = (

        close_price
        - low_price

    ) / candle_range


    return {

        "body_ratio":
            body / candle_range,

        "close_position":
            close_position,

        "lower_wick_ratio":
            lower_wick / candle_range,

        "upper_wick_ratio":
            upper_wick / candle_range

    }


# =========================================================
# BUILD OUTPUT
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


    previous = (
        previous_lookup.get(
            symbol
        )
    )


    if previous is None:

        continue


    previous_open = (
        previous["open"]
    )

    previous_high = (
        previous["high"]
    )

    previous_low = (
        previous["low"]
    )

    previous_close = (
        previous["close"]
    )


    # =====================================================
    # PREVIOUS CANDLE
    # =====================================================

    if (

        previous_close
        < previous_open

    ):

        previous_candle = (
            "RED 🔴"
        )

    elif (

        previous_close
        > previous_open

    ):

        previous_candle = (
            "GREEN 🟢"
        )

    else:

        previous_candle = (
            "DOJI"
        )


    # =====================================================
    # GAP
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
    # CURRENT GAIN
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

        gap_maintained = (
            "YES ✅"
        )

    elif today_close > previous_close:

        gap_maintained = (
            "PARTIAL 🟡"
        )

    else:

        gap_maintained = (
            "NO 🔴"
        )


    # =====================================================
    # HISTORICAL CANDLES
    # =====================================================

    hist = (
        history_data.get(
            symbol,
            []
        )
    )


    hist = sorted(

        hist,

        key=lambda x:
            x["date"]

    )


    # =====================================================
    # NEED 20+ CANDLES
    # =====================================================

    lower_bb = None
    middle_bb = None
    upper_bb = None


    if len(hist) >= BB_LENGTH:

        (
            upper_bb,
            middle_bb,
            lower_bb

        ) = calculate_bb(

            hist,

            BB_LENGTH,

            BB_MULTIPLIER

        )


    # =====================================================
    # SETUP CANDLE
    #
    # Previous day is the setup candle.
    # It is hist[-1] because history is up to
    # previous trading day.
    # =====================================================

    setup = None

    c1 = None
    c2 = None


    if len(hist) >= 3:

        c1 = hist[-3]

        c2 = hist[-2]

        setup = hist[-1]


    # =====================================================
    # BB OF SETUP CANDLE
    #
    # To avoid mixing today's data,
    # calculate BB from candles available
    # up to setup candle.
    # =====================================================

    setup_lower_bb = None


    if len(hist) >= BB_LENGTH:

        (
            _,
            _,
            setup_lower_bb

        ) = calculate_bb(

            hist,

            BB_LENGTH,

            BB_MULTIPLIER

        )


    # =====================================================
    # SETUP VALUES
    # =====================================================

    if setup is not None:

        setup_open = (
            setup["open"]
        )

        setup_high = (
            setup["high"]
        )

        setup_low = (
            setup["low"]
        )

        setup_close = (
            setup["close"]
        )

    else:

        setup_open = None

        setup_high = None

        setup_low = None

        setup_close = None


    # =====================================================
    # SELLING EXHAUSTION
    # =====================================================

    selling_exhaustion = False


    if (

        c1 is not None

        and

        c2 is not None

        and

        setup is not None

    ):

        falling_closes = (

            c1["close"]
            > c2["close"]
            > setup_close

        )


        lower_low = (

            setup["low"]
            <= c2["low"]

        )


        selling_exhaustion = (

            falling_closes

            and

            lower_low

        )


    # =====================================================
    # BB TOUCH
    # =====================================================

    bb_touch = False


    if (

        setup_lower_bb
        is not None

        and

        setup is not None

    ):

        bb_touch = (

            setup_low
            <= setup_lower_bb

        )


    # =====================================================
    # SETUP CANDLE STRUCTURE
    # =====================================================

    rejection_data = None


    if setup is not None:

        rejection_data = (
            candle_strength(

                setup_open,

                setup_high,

                setup_low,

                setup_close

            )
        )


    # =====================================================
    # BB REJECTION
    # =====================================================

    bb_rejection = False


    if (

        rejection_data is not None

        and

        setup_lower_bb
        is not None

    ):

        close_above_bb = (

            setup_close
            > setup_lower_bb

        )


        meaningful_lower_wick = (

            rejection_data[
                "lower_wick_ratio"
            ]
            >= 0.25

        )


        close_in_upper_half = (

            rejection_data[
                "close_position"
            ]
            >= 0.50

        )


        bb_rejection = (

            close_above_bb

            and

            meaningful_lower_wick

            and

            close_in_upper_half

        )


    # =====================================================
    # REVERSAL SETUP
    # =====================================================

    reversal_setup = (

        selling_exhaustion

        and

        bb_touch

        and

        bb_rejection

    )


    # =====================================================
    # TODAY CANDLE
    # =====================================================

    today_candle_data = (
        candle_strength(

            today_open,

            today_high,

            today_low,

            today_close

        )
    )


    today_green = (

        today_close
        > today_open

    )


    # =====================================================
    # HIGH BREAK
    # =====================================================

    high_break = False


    if setup is not None:

        high_break = (

            today_close
            > setup_high

        )


    # =====================================================
    # LOW PROTECTION
    # =====================================================

    low_protected = False


    if setup is not None:

        low_protected = (

            today_low
            > setup_low

        )


    # =====================================================
    # STRONG CONFIRMATION
    # =====================================================

    strong_confirmation = (

        today_green

        and

        today_candle_data[
            "body_ratio"
        ] >= 0.50

        and

        today_candle_data[
            "close_position"
        ] >= 0.70

    )


    # =====================================================
    # TURNOVER
    # =====================================================

    rank = (
        turnover_rank.get(
            symbol,
            999
        )
    )


    high_turnover = (

        rank
        <= HIGH_TURNOVER_RANK

    )


    # =====================================================
    # GAP CONFIRMATION
    # =====================================================

    gap_confirmation = (

        gap_up_pct
        >= MIN_GAP_UP

    )


    # =====================================================
    # BB BREAKOUT REVERSAL
    # =====================================================

    bb_breakout_reversal = (

        reversal_setup

        and

        high_break

        and

        low_protected

        and

        high_turnover

    )


    # =====================================================
    # BB GAP REVERSAL
    # =====================================================

    bb_gap_reversal = (

        bb_breakout_reversal

        and

        gap_confirmation

    )


    # =====================================================
    # OLD GAP SETUP
    # =====================================================

    red_gap_hold = (

        previous_candle
        == "RED 🔴"

        and

        gap_confirmation

        and

        today_close
        >= today_open

        and

        high_turnover

    )


    # =====================================================
    # SETUP TYPE
    # =====================================================

    if bb_gap_reversal:

        setup_type = (
            "💎 BB GAP REVERSAL"
        )

    elif bb_breakout_reversal:

        setup_type = (
            "🔥 BB BREAKOUT REVERSAL"
        )

    elif red_gap_hold:

        setup_type = (
            "🚀 RED → GAP → HOLD"
        )

    elif reversal_setup:

        setup_type = (
            "🟡 REVERSAL WAIT"
        )

    else:

        setup_type = (
            "—"
        )


    # =====================================================
    # BB STATUS
    # =====================================================

    if bb_gap_reversal:

        bb_signal = (
            "💎 CONFIRMED"
        )

    elif bb_breakout_reversal:

        bb_signal = (
            "🔥 CONFIRMED"
        )

    elif reversal_setup:

        bb_signal = (
            "🟡 WAITING BREAKOUT"
        )

    elif bb_touch:

        bb_signal = (
            "🟡 BB TOUCH"
        )

    else:

        bb_signal = (
            "—"
        )


    # =====================================================
    # STRENGTH SCORE V2
    # =====================================================

    score = 0


    # High turnover
    if high_turnover:

        score += 20


    # Selling exhaustion
    if selling_exhaustion:

        score += 15


    # BB touch
    if bb_touch:

        score += 15


    # BB rejection
    if bb_rejection:

        score += 15


    # Breakout
    if high_break:

        score += 15


    # Low protection
    if low_protected:

        score += 10


    # Gap
    if gap_confirmation:

        score += 10


    if score > 100:

        score = 100


    # =====================================================
    # FINAL SIGNAL
    # =====================================================

    if bb_gap_reversal:

        final_signal = (
            "💎 STRONG BB GAP REVERSAL"
        )

    elif bb_breakout_reversal:

        final_signal = (
            "🔥 STRONG BB BREAKOUT"
        )

    elif red_gap_hold:

        final_signal = (
            "🚀 STRONG GAP HOLD"
        )

    elif reversal_setup:

        final_signal = (
            "🟡 REVERSAL WAIT"
        )

    else:

        final_signal = (
            "—"
        )


    # =====================================================
    # OUTPUT ROW
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
            setup_lower_bb,
            2
        )
        if setup_lower_bb is not None
        else "",

        "YES ✅"
        if bb_touch
        else "NO",

        "YES 🔥"
        if bb_rejection
        else "NO",

        "YES 🚀"
        if high_break
        else "NO",

        "YES ✅"
        if low_protected
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

    "BB Rejection?",

    "High Break?",

    "Low Protected?",

    "Setup Type",

    "Turnover Rank",

    "Strength Score",

    "Signal"

]


# =========================================================
# UPDATE NIFTY200
# =========================================================

sheet_nifty.batch_clear(
    [
        "A1:U1000"
    ]
)


sheet_nifty.update(

    range_name="A1:U1",

    values=[
        nifty_headers
    ],

    value_input_option="RAW"

)


if output_rows:

    sheet_nifty.update(

        range_name="A2",

        values=output_rows,

        value_input_option="RAW"

    )


# =========================================================
# FINAL LIST
# =========================================================

final_candidates = []


for row in output_rows:

    if len(row) < 21:

        continue


    setup_type = str(
        row[17]
    )


    # -----------------------------------------------------
    # ONLY CONFIRMED SETUPS
    # -----------------------------------------------------

    confirmed = (

        "BB GAP REVERSAL"
        in setup_type

        or

        "BB BREAKOUT REVERSAL"
        in setup_type

        or

        "RED → GAP → HOLD"
        in setup_type

    )


    if confirmed:

        final_candidates.append(
            row
        )


# =========================================================
# SORT FINAL LIST
# =========================================================

final_candidates.sort(

    key=lambda x: (

        x[19],   # Strength Score

        -x[18],  # Turnover Rank

        x[8]     # Gap %

    ),

    reverse=True

)


# =========================================================
# FINAL OUTPUT
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

        row[18],

        row[19],

        row[20]

    ])


# =========================================================
# FINAL LIST HEADER
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

    "BB Rejection?",

    "High Break?",

    "Low Protected?",

    "Setup Type",

    "Turnover Rank",

    "Strength Score",

    "Signal"

]


# =========================================================
# CLEAR FINAL LIST
# =========================================================

sheet_final.batch_clear(

    [
        "A1:V1000"
    ]

)


# =========================================================
# WRITE FINAL HEADER
# =========================================================

sheet_final.update(

    range_name="A1:V1",

    values=[
        final_headers
    ],

    value_input_option="RAW"

)


# =========================================================
# WRITE FINAL DATA
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

        "A1:U1",

        {

            "textFormat": {

                "bold": True

            },

            "horizontalAlignment":
                "CENTER"

        }

    )


    sheet_final.format(

        "A1:V1",

        {

            "textFormat": {

                "bold": True

            },

            "horizontalAlignment":
                "CENTER"

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
# FINAL REPORT
# =========================================================

print(
    "========================================"
)

print(
    "NIFTY200 REVERSAL SCREENER UPDATED"
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
    f"Stocks : "
    f"{len(output_rows)}"
)

print(
    f"Final Strong Stocks : "
    f"{len(final_output)}"
)

print(
    "----------------------------------------"
)

print(
    "TOP 200 BY TURNOVER : YES"
)

print(
    "HIGH TURNOVER : TOP 50"
)

print(
    "BOLLINGER : 20, 1.5"
)

print(
    "SELLING EXHAUSTION : YES"
)

print(
    "LOWER BB REJECTION : YES"
)

print(
    "HIGH BREAK CONFIRMATION : YES"
)

print(
    "LOW PROTECTED : YES"
)

print(
    "RED -> GAP -> HOLD : YES"
)

print(
    "MACD : REMOVED"
)

print(
    "========================================"
)
