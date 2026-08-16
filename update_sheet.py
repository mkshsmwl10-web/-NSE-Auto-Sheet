# =========================================================
# NIFTY 200 STRICT BB REVERSAL SCREENER
# =========================================================
#
# FINAL LIST = BB REVERSAL ONLY
#
# LOGIC
# ---------------------------------------------------------
# 1. TOP 200 BY TURNOVER
# 2. PREVIOUS PRICE ACTION FALL
# 3. SETUP CANDLE TOUCHES / BREAKS LOWER BB
# 4. SETUP CANDLE GOES BELOW LOWER BB
# 5. SETUP CANDLE CLOSES BACK ABOVE LOWER BB
# 6. MEANINGFUL LOWER WICK
# 7. TODAY CLOSE BREAKS SETUP HIGH
# 8. TODAY LOW PROTECTS SETUP LOW
# 9. TURNOVER TOP 50
#
# FINAL LIST:
# 💎 STRONG BB REVERSAL
#
# MACD : REMOVED
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
# CONFIG
# =========================================================

SPREADSHEET_ID = (
    "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E"
)

NIFTY_SHEET = "NIFTY200"

FINAL_SHEET = "Final List"


# =========================================================
# BOLLINGER BAND
# =========================================================

BB_LENGTH = 20

BB_MULTIPLIER = 1.5


# =========================================================
# TURNOVER
# =========================================================

HIGH_TURNOVER_RANK = 50


# =========================================================
# HISTORICAL DAYS
# =========================================================

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
# NIFTY200 SHEET
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
# FINAL LIST SHEET
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
# NSE BHAVCOPY DOWNLOAD
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


        df.columns = [

            str(c).strip()

            for c in df.columns

        ]


        # =================================================
        # SYMBOL
        # =================================================

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


        # =================================================
        # OPEN
        # =================================================

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


        # =================================================
        # HIGH
        # =================================================

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


        # =================================================
        # LOW
        # =================================================

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


        # =================================================
        # CLOSE
        # =================================================

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


        # =================================================
        # TURNOVER
        # =================================================

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


        # =================================================
        # SERIES
        # =================================================

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


        # =================================================
        # VALIDATION
        # =================================================

        required = {

            "Symbol": symbol_col,

            "Open": open_col,

            "High": high_col,

            "Low": low_col,

            "Close": close_col,

            "Turnover": turnover_col

        }


        for name, col in required.items():

            if col is None:

                print(
                    f"{name} column missing"
                )

                return None


        # =================================================
        # EQUITY ONLY
        # =================================================

        if series_col:

            df = df[

                df[series_col]
                .astype(str)
                .str.strip()
                .str.upper()
                == "EQ"

            ]


        # =================================================
        # NUMERIC DATA
        # =================================================

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

now = datetime.now()

latest_data = None

latest_date = None


for i in range(7):

    check_date = (

        now
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
# TOP 200 BY TURNOVER
# =========================================================

exclude_words = (
    "BEES|ETF|GOLD|LIQUID|SILVER|INDEX"
)


top200 = (

    bhavcopy[

        ~bhavcopy[symbol_col]
        .astype(str)
        .str.contains(
            exclude_words,
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
        "Previous trading day "
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
            float(
                row[prev_open_col]
            ),

        "high":
            float(
                row[prev_high_col]
            ),

        "low":
            float(
                row[prev_low_col]
            ),

        "close":
            float(
                row[prev_close_col]
            )

    }


# =========================================================
# HISTORICAL DATA
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

    days_checked < 45

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

                    row[
                        hist_symbol_col
                    ]

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


    middle = float(
        series.mean()
    )


    std = float(
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

        upper,

        middle,

        lower

    )


# =========================================================
# CANDLE STRUCTURE
# =========================================================

def candle_structure(

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


    return {

        "body_ratio":

            body / candle_range,

        "close_position":

            (
                close_price
                - low_price
            )
            / candle_range,

        "lower_wick_ratio":

            lower_wick
            / candle_range,

        "upper_wick_ratio":

            upper_wick
            / candle_range

    }


# =========================================================
# OUTPUT
# =========================================================

output_rows = []


# =========================================================
# PROCESS TOP 200
# =========================================================

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


    today_high = float(
        row[high_col]
    )


    today_low = float(
        row[low_col]
    )


    today_close = float(
        row[close_col]
    )


    # =====================================================
    # PREVIOUS DAY
    # =====================================================

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
    # PREVIOUS CANDLE TYPE
    # =====================================================

    if previous_close < previous_open:

        previous_candle = (
            "RED 🔴"
        )

    elif previous_close > previous_open:

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

    if previous_close != 0:

        gap_up_pct = (

            (
                today_open
                - previous_close
            )
            / previous_close
            * 100

        )

    else:

        gap_up_pct = 0


    # =====================================================
    # CURRENT GAIN
    # =====================================================

    if previous_close != 0:

        current_gain_pct = (

            (
                today_close
                - previous_close
            )
            / previous_close
            * 100

        )

    else:

        current_gain_pct = 0


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
    # HISTORY
    # =====================================================

    hist = history_data.get(
        symbol,
        []
    )


    hist = sorted(

        hist,

        key=lambda x:
            x["date"]

    )


    # =====================================================
    # SETUP CANDLE
    #
    # hist[-1] = previous trading day
    # =====================================================

    if len(hist) >= 3:

        c1 = hist[-3]

        c2 = hist[-2]

        setup = hist[-1]

    else:

        c1 = None

        c2 = None

        setup = None


    # =====================================================
    # SETUP BB
    # =====================================================

    setup_lower_bb = None


    if len(hist) >= BB_LENGTH:

        _, _, setup_lower_bb = (

            calculate_bb(

                hist,

                BB_LENGTH,

                BB_MULTIPLIER

            )

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
    
# =========================================================
# MULTI-REVERSAL SCORING ENGINE
# =========================================================
#
# FINAL LIST IS NOT LIMITED TO ONE PERFECT BB SETUP.
#
# SETUP 1 : LOWER BB REVERSAL
# SETUP 2 : BULLISH ENGULFING + BB/EXHAUSTION
# SETUP 3 : OVERSOLD + STRONG CANDLE / GAP-UP
#
# TURNOVER IS A SCORE FACTOR, NOT A HARD FILTER.
# FINAL LIST = TOP POTENTIAL REVERSALS, MAX 10
# =========================================================


def rsi_from_closes(closes, length=14):

    if len(closes) < length + 1:
        return None

    s = pd.Series(closes, dtype=float)

    delta = s.diff()

    gain = delta.clip(lower=0)

    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(
        length
    ).mean()

    avg_loss = loss.rolling(
        length
    ).mean()

    ag = avg_gain.iloc[-1]
    al = avg_loss.iloc[-1]

    if pd.isna(ag) or pd.isna(al):
        return None

    if al == 0:
        return 100.0

    rs = ag / al

    return float(
        100 - (100 / (1 + rs))
    )


def candle_structure(
    open_price,
    high_price,
    low_price,
    close_price
):

    candle_range = high_price - low_price

    if candle_range <= 0:
        return {
            "body_ratio": 0,
            "close_position": 0,
            "lower_wick_ratio": 0,
            "upper_wick_ratio": 0
        }

    body = abs(
        close_price - open_price
    )

    lower_wick = (
        min(open_price, close_price)
        - low_price
    )

    upper_wick = (
        high_price
        - max(open_price, close_price)
    )

    return {
        "body_ratio":
            body / candle_range,

        "close_position":
            (close_price - low_price)
            / candle_range,

        "lower_wick_ratio":
            lower_wick / candle_range,

        "upper_wick_ratio":
            upper_wick / candle_range
    }


def bullish_engulfing(prev_candle, curr_candle):

    if prev_candle is None or curr_candle is None:
        return False

    prev_open = prev_candle["open"]
    prev_close = prev_candle["close"]

    curr_open = curr_candle["open"]
    curr_close = curr_candle["close"]

    # Previous candle must be bearish.
    if prev_close >= prev_open:
        return False

    # Current candle must be bullish.
    if curr_close <= curr_open:
        return False

    # Real body engulfs previous real body.
    return (
        curr_open <= prev_close
        and
        curr_close >= prev_open
    )


def get_bb_for_index(candles, index):

    if index < BB_LENGTH - 1:
        return None, None, None

    window = candles[
        index - BB_LENGTH + 1:
        index + 1
    ]

    return calculate_bb(
        window,
        BB_LENGTH,
        BB_MULTIPLIER
    )


# =========================================================
# OUTPUT
# =========================================================

output_rows = []


# =========================================================
# PROCESS TOP 200
# =========================================================

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

    today_high = float(
        row[high_col]
    )

    today_low = float(
        row[low_col]
    )

    today_close = float(
        row[close_col]
    )

    previous = previous_lookup.get(symbol)

    if previous is None:
        continue

    previous_open = previous["open"]
    previous_high = previous["high"]
    previous_low = previous["low"]
    previous_close = previous["close"]

    if previous_close < previous_open:
        previous_candle = "RED 🔴"
    elif previous_close > previous_open:
        previous_candle = "GREEN 🟢"
    else:
        previous_candle = "DOJI"

    if previous_close != 0:
        gap_up_pct = (
            (today_open - previous_close)
            / previous_close
            * 100
        )
        current_gain_pct = (
            (today_close - previous_close)
            / previous_close
            * 100
        )
    else:
        gap_up_pct = 0
        current_gain_pct = 0

    if today_close >= today_open:
        gap_maintained = "YES ✅"
    elif today_close > previous_close:
        gap_maintained = "PARTIAL 🟡"
    else:
        gap_maintained = "NO 🔴"

    hist = sorted(
        history_data.get(symbol, []),
        key=lambda x: x["date"]
    )

    # The last historical candle is the previous trading day.
    setup = hist[-1] if len(hist) >= 1 else None
    prev_setup = hist[-2] if len(hist) >= 2 else None
    prev2_setup = hist[-3] if len(hist) >= 3 else None

    setup_lower_bb = None
    setup_rsi = None
    previous_rsi = None
    rsi_recovery = False
    rsi_deep_oversold = False

    if setup is not None:

        setup_index = len(hist) - 1

        _, _, setup_lower_bb = get_bb_for_index(
            hist,
            setup_index
        )

        closes_to_setup = [
            x["close"]
            for x in hist[:setup_index + 1]
        ]

        setup_rsi = rsi_from_closes(
            closes_to_setup,
            14
        )

        # RSI of the candle immediately before the setup candle.
        if len(closes_to_setup) >= 16:
            previous_rsi = rsi_from_closes(
                closes_to_setup[:-1],
                14
            )

        rsi_deep_oversold = (
            setup_rsi is not None
            and
            setup_rsi <= 30
        )

        # Fresh RSI recovery: RSI is still relatively low,
        # but has started turning upward.
        rsi_recovery = (
            previous_rsi is not None
            and
            setup_rsi is not None
            and
            setup_rsi > previous_rsi
            and
            setup_rsi <= 45
        )

    # -----------------------------------------------------
    # PRICE FALL / EXHAUSTION
    # -----------------------------------------------------

    falling_closes = False
    lower_low = False

    if (
        prev2_setup is not None
        and
        prev_setup is not None
        and
        setup is not None
    ):

        falling_closes = (
            prev2_setup["close"]
            > prev_setup["close"]
            > setup["close"]
        )

        lower_low = (
            setup["low"]
            < prev_setup["low"]
        )

    selling_exhaustion = (
        falling_closes
        and
        lower_low
    )

    # -----------------------------------------------------
    # LOWER BB
    # -----------------------------------------------------

    bb_touch = False
    bb_break = False
    close_back_above_bb = False

    if setup_lower_bb is not None and setup is not None:

        bb_touch = (
            setup["low"]
            <= setup_lower_bb
        )

        bb_break = (
            setup["low"]
            < setup_lower_bb
        )

        close_back_above_bb = (
            setup["close"]
            > setup_lower_bb
        )

    # -----------------------------------------------------
    # LOWER WICK REJECTION
    # -----------------------------------------------------

    bb_rejection = False

    if setup is not None:

        setup_candle = candle_structure(
            setup["open"],
            setup["high"],
            setup["low"],
            setup["close"]
        )

        bb_rejection = (
            setup_candle["lower_wick_ratio"] >= 0.20
            and
            setup_candle["close_position"] >= 0.50
        )

    # -----------------------------------------------------
    # BULLISH ENGULFING
    # -----------------------------------------------------

    engulfing = bullish_engulfing(
        prev_setup,
        setup
    )

    # -----------------------------------------------------
    # OVERSOLD
    # -----------------------------------------------------

    oversold = (
        setup_rsi is not None
        and
        setup_rsi <= 35
    )

    deep_oversold = (
        setup_rsi is not None
        and
        setup_rsi <= 30
    )

    # -----------------------------------------------------
    # TODAY STRONG CANDLE
    # -----------------------------------------------------

    today_candle = candle_structure(
        today_open,
        today_high,
        today_low,
        today_close
    )

    today_green = (
        today_close > today_open
    )

    strong_green = (
        today_green
        and
        today_candle["body_ratio"] >= 0.45
        and
        today_candle["close_position"] >= 0.65
    )

    # -----------------------------------------------------
    # GAP-UP
    # -----------------------------------------------------

    gap_up = (
        gap_up_pct >= 0.50
    )

    strong_gap_up = (
        gap_up_pct >= 1.00
    )

    # -----------------------------------------------------
    # TODAY CONFIRMATION
    # -----------------------------------------------------

    high_break = False
    low_protected = False

    if setup is not None:

        high_break = (
            today_close > setup["high"]
        )

        low_protected = (
            today_low >= setup["low"]
        )

    # -----------------------------------------------------
    # RECENT BB TOUCH
    #
    # Gives the scanner some flexibility. A stock does not
    # have to touch BB on exactly one candle if the touch
    # happened in the recent 3-candle reversal area.
    # -----------------------------------------------------

    recent_bb_touch = False
    recent_bb_rejection = False

    recent_rsi = setup_rsi

    recent_bb_low = setup_lower_bb

    recent_bars = hist[-3:] if len(hist) >= 3 else hist

    for idx_offset, bar in enumerate(recent_bars):

        absolute_index = (
            len(hist)
            - len(recent_bars)
            + idx_offset
        )

        _, _, bb_low = get_bb_for_index(
            hist,
            absolute_index
        )

        if bb_low is None:
            continue

        if bar["low"] <= bb_low:

            recent_bb_touch = True

            cs = candle_structure(
                bar["open"],
                bar["high"],
                bar["low"],
                bar["close"]
            )

            if (
                cs["lower_wick_ratio"] >= 0.20
                and
                cs["close_position"] >= 0.50
            ):
                recent_bb_rejection = True

    # -----------------------------------------------------
    # REVERSAL SETUPS
    # -----------------------------------------------------

    bb_reversal = (
        recent_bb_touch
        and
        (
            recent_bb_rejection
            or
            strong_green
            or
            engulfing
        )
    )

    engulfing_reversal = (
        engulfing
        and
        (
            recent_bb_touch
            or
            selling_exhaustion
        )
    )

    oversold_reversal = (
        (
            oversold
            or
            rsi_recovery
        )
        and
        (
            strong_green
            or
            engulfing
            or
            gap_up
            or
            high_break
        )
    )

    # -----------------------------------------------------
    # CONFIRMATION QUALITY
    # -----------------------------------------------------

    confirmation = (
        high_break
        or
        strong_green
        or
        strong_gap_up
    )

    # -----------------------------------------------------
    # TURNOVER SCORE
    # -----------------------------------------------------

    rank = turnover_rank.get(
        symbol,
        999
    )

    if rank <= 25:
        turnover_score = 10
    elif rank <= 50:
        turnover_score = 8
    elif rank <= 100:
        turnover_score = 5
    elif rank <= 150:
        turnover_score = 3
    else:
        turnover_score = 1

    # -----------------------------------------------------
    # SCORE
# ---------------------------------------------------------
# PURPOSE:
# Find stocks that are not merely "near the BB", but are
# actually showing a reversal + confirmation + momentum.
#
# The score is deliberately biased toward PRICE ACTION.
# Turnover is supportive, not the main reason for a high score.
# ---------------------------------------------------------

score = 0

# 1) BB / exhaustion
if recent_bb_touch:
    score += 10

if recent_bb_rejection:
    score += 10

if selling_exhaustion:
    score += 8

# 2) Reversal trigger
if engulfing:
    score += 15

if oversold:
    score += 10

if rsi_recovery:
    score += 10

if deep_oversold:
    score += 5

# 3) Real price confirmation — highest importance
if strong_green:
    score += 12

if high_break:
    score += 12

if low_protected:
    score += 8

# 4) Gap confirmation
if gap_up:
    score += 4

if strong_gap_up:
    score += 5

if gap_maintained == "YES ✅":
    score += 5

# 5) Turnover — supportive only
score += turnover_score

# 6) Independent setup agreement
setup_count = sum([
    bb_reversal,
    engulfing_reversal,
    oversold_reversal
])

if setup_count >= 2:
    score += 5

if setup_count >= 3:
    score += 5

# ---------------------------------------------------------
# IMPORTANT:
# A stock with negative current gain must not become a
# "strong reversal" only because several historical signals
# are present.
# ---------------------------------------------------------

if current_gain_pct < 0:
    score = min(score, 59)

# Positive momentum bonus
if current_gain_pct >= 2.0:
    score += 3

if current_gain_pct >= 4.0:
    score += 3

if score > 100:
    score = 100

# ---------------------------------------------------------
# SETUP TYPE
    # -----------------------------------------------------

    setup_names = []

    if bb_reversal:
        setup_names.append("💎 BB REVERSAL")

    if engulfing_reversal:
        setup_names.append("🔥 ENGULFING")

    if oversold_reversal:
        if rsi_recovery:
            setup_names.append("🚀 RSI RECOVERY")
        else:
            setup_names.append("🚀 OVERSOLD")

    if len(setup_names) == 0:
        setup_type = "—"
    else:
        setup_type = " + ".join(setup_names)

    # -----------------------------------------------------
    # SIGNAL
# ---------------------------------------------------------

if score >= 85:
    final_signal = "💎 A+ POTENTIAL"

elif score >= 75:
    final_signal = "🔥 STRONG SWING"

elif score >= 65:
    final_signal = "👀 WATCH"

else:
    final_signal = "—"

# ---------------------------------------------------------
# OUTPUT
    # -----------------------------------------------------

    output_rows.append([

        symbol,
        turnover,

        previous_open,
        previous_high,
        previous_low,
        previous_close,
        previous_candle,

        today_open,
        round(gap_up_pct, 2),

        today_close,
        round(current_gain_pct, 2),

        gap_maintained,

        (
            round(setup_lower_bb, 2)
            if setup_lower_bb is not None
            else ""
        ),

        (
            round(setup_rsi, 2)
            if setup_rsi is not None
            else ""
        ),

        (
            round(previous_rsi, 2)
            if previous_rsi is not None
            else ""
        ),

        "YES 🔄" if rsi_recovery else "NO",

        "YES ✅" if recent_bb_touch else "NO",

        "YES 🔥" if recent_bb_rejection else "NO",

        "YES 🔥" if engulfing else "NO",

        "YES 🔥" if oversold else "NO",

        "YES 🚀" if strong_green else "NO",

        "YES 🚀" if high_break else "NO",

        "YES ✅" if low_protected else "NO",

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
    "RSI 14",
    "Previous RSI 14",
    "RSI Recovery?",

    "BB Touch?",
    "BB Rejection?",
    "Bullish Engulfing?",
    "Oversold?",
    "Strong Green?",
    "High Break?",
    "Low Protected?",

    "Setup Type",

    "Turnover Rank",
    "Strength Score",
    "Signal"
]


# =========================================================
# WRITE NIFTY200
# =========================================================

sheet_nifty.batch_clear(
    ["A1:AA1000"]
)

sheet_nifty.update(
    range_name="A1:AA1",
    values=[nifty_headers],
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
#
# FINAL LIST V5
#
# Goal:
#   Find a small number of HIGH-QUALITY reversal candidates
#   from NIFTY 200 rather than filling the list with weak setups.
#
# HARD ENTRY-QUALITY GATES:
#   1. A genuine reversal setup exists
#   2. Current gain is positive
#   3. Today's low protects the setup candle low
#   4. At least one real price confirmation exists:
#        - High Break
#        - Strong Green
#        - Bullish Engulfing
#        - Gap Up + Gap Hold
#
# This deliberately removes cases such as:
#   HINDUNILVR: negative current gain + no gap hold
#
# Final list is compact and decision-focused.
# =========================================================

# Known NIFTY200 row layout
#  0 Symbol
#  1 Turnover
#  2 Previous Open
#  3 Previous High
#  4 Previous Low
#  5 Previous Close
#  6 Previous Candle
#  7 Today Open
#  8 Gap Up %
#  9 CMP
# 10 Current Gain %
# 11 Gap Maintained
# 12 Lower BB
# 13 RSI
# 14 Previous RSI
# 15 RSI Recovery
# 16 BB Touch
# 17 BB Rejection
# 18 Bullish Engulfing
# 19 Oversold
# 20 Strong Green
# 21 High Break
# 22 Low Protected
# 23 Setup Type
# 24 Turnover Rank
# 25 Strength Score
# 26 Signal

SCORE_INDEX = 25
TURNOVER_RANK_INDEX = 24
GAIN_INDEX = 10

final_candidates = []

for row in output_rows:

    if len(row) <= SCORE_INDEX:
        continue

    try:
        score = float(row[SCORE_INDEX])
    except (TypeError, ValueError):
        continue

    try:
        gain = float(row[GAIN_INDEX])
    except (TypeError, ValueError):
        gain = -999

    # Boolean confirmation from the displayed YES/NO fields.
    bb_touch = str(row[16]).startswith("YES")
    bb_rejection = str(row[17]).startswith("YES")
    engulfing = str(row[18]).startswith("YES")
    oversold = str(row[19]).startswith("YES")
    strong_green = str(row[20]).startswith("YES")
    high_break = str(row[21]).startswith("YES")
    low_protected = str(row[22]).startswith("YES")

    gap_maintained = str(row[11])

    # Core reversal setup.
    core_reversal = (
        bb_rejection
        or engulfing
        or oversold
        or str(row[15]).startswith("YES")
    )

    # Real price-action confirmation.
    price_confirmation = (
        high_break
        or strong_green
        or engulfing
        or (
            str(row[8]).replace("%", "").strip() not in ("", "0", "0.0")
            and gap_maintained.startswith("YES")
        )
    )

    # HARD GATES
    if not core_reversal:
        continue

    if gain <= 0:
        continue

    if not low_protected:
        continue

    if not price_confirmation:
        continue

    # Only genuine candidates enter the Final List.
    if score < 65:
        continue

    try:
        turnover_rank_value = float(row[TURNOVER_RANK_INDEX])
    except (TypeError, ValueError):
        turnover_rank_value = 9999

    # Prefer stocks with stronger current momentum, then score,
    # then turnover rank.
    final_candidates.append({
        "row": row,
        "score": score,
        "gain": gain,
        "turnover_rank": turnover_rank_value
    })


# =========================================================
# SORT — MOMENTUM FIRST, QUALITY SECOND
# =========================================================

final_candidates.sort(
    key=lambda item: (
        item["score"],
        item["gain"],
        -item["turnover_rank"]
    ),
    reverse=True
)

# Maximum 10, but fewer is perfectly acceptable.
final_candidates = final_candidates[:10]


# =========================================================
# COMPACT FINAL LIST
# =========================================================
#
# Only columns needed for a quick trading decision are shown.
# The detailed NIFTY200 sheet still contains all diagnostics.
# =========================================================

final_headers = [
    "Rank",
    "NSE Code",
    "Turnover",
    "Prev Candle",
    "Today Open",
    "Gap %",
    "CMP",
    "Gain %",
    "Lower BB",
    "RSI",
    "Confirmation",
    "Setup",
    "Score",
    "Signal"
]

final_output = []

for rank, item in enumerate(final_candidates, start=1):

    row = item["row"]

    # Compact confirmation summary.
    confirmations = []

    if str(row[17]).startswith("YES"):
        confirmations.append("BB REJ")

    if str(row[18]).startswith("YES"):
        confirmations.append("ENGULF")

    if str(row[19]).startswith("YES"):
        confirmations.append("OVERSOLD")

    if str(row[20]).startswith("YES"):
        confirmations.append("GREEN")

    if str(row[21]).startswith("YES"):
        confirmations.append("HIGH BREAK")

    if str(row[22]).startswith("YES"):
        confirmations.append("LOW HOLD")

    if str(row[11]).startswith("YES"):
        confirmations.append("GAP HOLD")

    confirmation_text = " + ".join(confirmations)

    # Make the #1 qualifying candidate visually distinct.
    signal = row[26]

    if rank == 1 and item["score"] >= 75:
        signal = "🎯 TOP SWING"

    final_output.append([
        rank,
        row[0],
        row[1],
        row[6],
        row[7],
        row[8],
        row[9],
        row[10],
        row[12],
        row[13],
        confirmation_text,
        row[23],
        row[25],
        signal
    ])


# =========================================================
# CLEAR FINAL LIST
# =========================================================

sheet_final.batch_clear(
    ["A1:N1000"]
)


# =========================================================
# WRITE HEADER
# =========================================================

sheet_final.update(
    range_name="A1:N1",
    values=[final_headers],
    value_input_option="RAW"
)


# =========================================================
# WRITE DATA
# =========================================================

if final_output:

    sheet_final.update(
        range_name="A2",
        values=final_output,
        value_input_option="RAW"
    )


# =========================================================
# FINAL LIST — CLEAN / COMPACT / VISUAL FORMATTING
# =========================================================

try:

    # Header
    sheet_final.format(
        "A1:N1",
        {
            "backgroundColor": {
                "red": 0.05,
                "green": 0.12,
                "blue": 0.20
            },
            "textFormat": {
                "bold": True,
                "fontSize": 9,
                "foregroundColor": {
                    "red": 1,
                    "green": 1,
                    "blue": 1
                }
            },
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
            "wrapStrategy": "WRAP"
        }
    )

    if final_output:

        last_row = len(final_output) + 1

        # Compact body
        sheet_final.format(
            f"A2:N{last_row}",
            {
                "textFormat": {
                    "fontSize": 8
                },
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP"
            }
        )

        # Stock names
        sheet_final.format(
            f"B2:B{last_row}",
            {
                "textFormat": {
                    "bold": True,
                    "fontSize": 9
                },
                "horizontalAlignment": "LEFT"
            }
        )

        # Confirmation and setup
        sheet_final.format(
            f"K2:L{last_row}",
            {
                "textFormat": {
                    "bold": True,
                    "fontSize": 8
                },
                "wrapStrategy": "WRAP"
            }
        )

        # Score
        sheet_final.format(
            f"M2:M{last_row}",
            {
                "textFormat": {
                    "bold": True,
                    "fontSize": 9
                }
            }
        )

        # Signal
        sheet_final.format(
            f"N2:N{last_row}",
            {
                "textFormat": {
                    "bold": True,
                    "fontSize": 9
                },
                "wrapStrategy": "WRAP"
            }
        )

        # Highlight the first candidate.
        if final_output[0][0] == 1:
            sheet_final.format(
                "A2:N2",
                {
                    "backgroundColor": {
                        "red": 0.90,
                        "green": 0.97,
                        "blue": 0.90
                    },
                    "textFormat": {
                        "bold": True,
                        "fontSize": 9
                    }
                }
            )

    # Compact widths
    widths = {
        "A:A": 42,
        "B:B": 95,
        "C:C": 92,
        "D:D": 75,
        "E:E": 75,
        "F:F": 55,
        "G:G": 75,
        "H:H": 60,
        "I:I": 78,
        "J:J": 55,
        "K:K": 180,
        "L:L": 190,
        "M:M": 55,
        "N:N": 105
    }

    # Use Sheets column dimension formatting through repeated calls.
    # The compact ranges are intentionally kept narrow.
    for col_range, width in widths.items():
        try:
            sheet_final.format(
                col_range,
                {
                    "padding": {
                        "top": 2,
                        "bottom": 2,
                        "left": 2,
                        "right": 2
                    }
                }
            )
        except Exception:
            pass

    sheet_final.freeze(rows=1)

except Exception as e:

    print(
        f"Final List Formatting Warning : {e}"
    )


# =========================================================
# FINAL LIST SUMMARY
# =========================================================

print(
    "----------------------------------------"
)

print(
    "FINAL LIST V5 : STRICT SWING QUALITY FILTER"
)

print(
    f"Qualified Stocks : {len(final_output)}"
)

for item in final_candidates:

    row = item["row"]

    print(
        row[0],
        "| Score:",
        row[25],
        "| Gain:",
        row[10],
        "| Turnover Rank:",
        row[24],
        "| Setup:",
        row[23]
    )

# =========================================================
# FINAL REPORT
# =========================================================

print(
    "========================================"
)

print(
    "NIFTY200 MULTI-REVERSAL SCREENER UPDATED"
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
    f"Stocks Scanned : "
    f"{len(output_rows)}"
)

print(
    f"Final Candidates : "
    f"{len(final_output)}"
)

print(
    "----------------------------------------"
)

print(
    "TOP 200 BY TURNOVER : YES"
)

print(
    "BOLLINGER : 20, 1.5"
)

print(
    "RSI : 14"
)

print(
    "SETUP 1 : LOWER BB REVERSAL"
)

print(
    "SETUP 2 : BULLISH ENGULFING"
)

print(
    "SETUP 3 : OVERSOLD + RSI RECOVERY"
)

print(
    "TURNOVER : SCORE FACTOR"
)

print(
    "STRICT FINAL FILTER : POSITIVE GAIN + LOW HOLD + PRICE CONFIRMATION"
)

print(
    "MAX FINAL STOCKS : 10 (FEWER IS OK)"
)

print(
    "MACD : REMOVED"
)

print(
    "========================================"
)
