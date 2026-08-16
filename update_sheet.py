# =========================================================
# NIFTY 200 BB REVERSAL SCREENER V8.2
# =========================================================
#
# V8.2 PHILOSOPHY
# ---------------------------------------------------------
# PRIMARY SETUP:
#     💎 LOWER BB REVERSAL
#
# IMPORTANT:
#     MACD / RSI / WEEKLY MACD ARE NOT COMPULSORY.
#
# FINAL LIST:
#     ALL GENUINE BB REVERSAL CANDIDATES
#     RANKED BY STRENGTH SCORE
#
# PRIORITY:
#     1. LOWER BB REVERSAL
#     2. DAILY MACD BEND
#     3. PRICE CONFIRMATION
#     4. RSI RECOVERY
#     5. WEEKLY MACD BEND
#     6. TURNOVER
#
# =========================================================


import os
import json
import io
import zipfile
import time
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
# RSI
# =========================================================

RSI_LENGTH = 14


# =========================================================
# MACD
# =========================================================

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9


# =========================================================
# TURNOVER
# =========================================================

HIGH_TURNOVER_RANK = 50


# =========================================================
# HISTORY
# =========================================================

HISTORY_TRADING_DAYS = 60


# =========================================================
# MINIMUM BB SCORE
# =========================================================
#
# BB reversal itself must be genuine.
#
# Score 35+ = BB reversal candidate
#
# =========================================================

MIN_BB_SCORE = 35


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
            rows=1000,
            cols=50
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
            rows=1000,
            cols=30
        )
    )


# =========================================================
# NSE BHAVCOPY
# =========================================================

def fetch_bhavcopy(date_obj):

    date_str = date_obj.strftime(
        "%Y%m%d"
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
            "Chrome/151.0 Safari/537.36",

        "Accept": "*/*",

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

            csv_file = z.namelist()[0]

            with z.open(
                csv_file
            ) as f:

                df = pd.read_csv(f)


        df.columns = [
            str(c).strip()
            for c in df.columns
        ]


        # =================================================
        # COLUMN FINDER
        # =================================================

        def find_col(names):

            for c in names:

                if c in df.columns:
                    return c

            return None


        symbol_col = find_col([
            "TckrSymb",
            "SYMBOL"
        ])

        open_col = find_col([
            "OpnPric",
            "OPEN",
            "Open"
        ])

        high_col = find_col([
            "HghPric",
            "HIGH",
            "High"
        ])

        low_col = find_col([
            "LwPric",
            "LOW",
            "Low"
        ])

        close_col = find_col([
            "ClsPric",
            "CLOSE",
            "Close"
        ])

        turnover_col = find_col([
            "TtlTrfVal",
            "TtlTrdVal",
            "TURNOVER",
            "TURNOVER_LACS"
        ])

        series_col = find_col([
            "SctySrs",
            "SERIES"
        ])


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
        # NUMERIC
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
        now -
        timedelta(days=i)
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
        latest_date -
        timedelta(days=i)
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
# PREVIOUS LOOKUP
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

history_data = {}

history_dates_found = 0

check_date = (
    latest_date -
    timedelta(days=1)
)

days_checked = 0


while (

    history_dates_found
    < HISTORY_TRADING_DAYS

    and

    days_checked < 90

):

    if check_date.weekday() < 5:

        result = fetch_bhavcopy(
            check_date
        )

        if result is not None:

            hist_df = result["df"]

            h_symbol = result["symbol_col"]
            h_open = result["open_col"]
            h_high = result["high_col"]
            h_low = result["low_col"]
            h_close = result["close_col"]


            for _, row in hist_df.iterrows():

                symbol = str(
                    row[h_symbol]
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
                            row[h_open]
                        ),

                    "high":
                        float(
                            row[h_high]
                        ),

                    "low":
                        float(
                            row[h_low]
                        ),

                    "close":
                        float(
                            row[h_close]
                        )

                })


            history_dates_found += 1


    check_date -= timedelta(days=1)

    days_checked += 1


print(
    "Historical Trading Days Loaded : "
    f"{history_dates_found}"
)


# =========================================================
# RSI
# =========================================================

def rsi_from_closes(
    closes,
    length=14
):

    if len(closes) < length + 1:
        return None

    s = pd.Series(
        closes,
        dtype=float
    )

    delta = s.diff()

    gain = delta.clip(
        lower=0
    )

    loss = -delta.clip(
        upper=0
    )

    avg_gain = (
        gain
        .rolling(length)
        .mean()
        .iloc[-1]
    )

    avg_loss = (
        loss
        .rolling(length)
        .mean()
        .iloc[-1]
    )

    if (
        pd.isna(avg_gain)
        or
        pd.isna(avg_loss)
    ):

        return None

    if avg_loss == 0:
        return 100.0

    rs = (
        avg_gain /
        avg_loss
    )

    return float(
        100 -
        (
            100 /
            (1 + rs)
        )
    )


# =========================================================
# BB
# =========================================================

def calculate_bb(
    candles,
    length=20,
    multiplier=1.5
):

    if len(candles) < length:

        return (
            None,
            None,
            None
        )

    closes = pd.Series(
        [
            float(x["close"])
            for x in candles[-length:]
        ],
        dtype=float
    )

    middle = float(
        closes.mean()
    )

    std = float(
        closes.std(
            ddof=0
        )
    )

    upper = (
        middle +
        multiplier * std
    )

    lower = (
        middle -
        multiplier * std
    )

    return (
        upper,
        middle,
        lower
    )


def get_bb_for_index(
    candles,
    index
):

    if index < BB_LENGTH - 1:

        return (
            None,
            None,
            None
        )

    return calculate_bb(
        candles[
            index -
            BB_LENGTH +
            1:
            index + 1
        ],
        BB_LENGTH,
        BB_MULTIPLIER
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
        high_price -
        low_price
    )

    if candle_range <= 0:

        return {

            "body_ratio": 0.0,

            "close_position": 0.0,

            "lower_wick_ratio": 0.0,

            "upper_wick_ratio": 0.0

        }


    body = abs(
        close_price -
        open_price
    )

    lower_wick = (
        min(
            open_price,
            close_price
        )
        -
        low_price
    )

    upper_wick = (
        high_price -
        max(
            open_price,
            close_price
        )
    )


    return {

        "body_ratio":
            body /
            candle_range,

        "close_position":
            (
                close_price -
                low_price
            )
            /
            candle_range,

        "lower_wick_ratio":
            lower_wick /
            candle_range,

        "upper_wick_ratio":
            upper_wick /
            candle_range

    }


# =========================================================
# BULLISH ENGULFING
# =========================================================

def bullish_engulfing(
    prev_candle,
    curr_candle
):

    if (
        prev_candle is None
        or
        curr_candle is None
    ):

        return False


    if (
        prev_candle["close"]
        >=
        prev_candle["open"]
    ):

        return False


    if (
        curr_candle["close"]
        <=
        curr_candle["open"]
    ):

        return False


    return (

        curr_candle["open"]
        <=
        prev_candle["close"]

        and

        curr_candle["close"]
        >=
        prev_candle["open"]

    )


# =========================================================
# MACD
# =========================================================

def macd_values(
    closes,
    fast=12,
    slow=26,
    signal=9
):

    if len(closes) < (
        slow +
        signal +
        5
    ):

        return (
            None,
            None,
            None
        )


    s = pd.Series(
        closes,
        dtype=float
    )

    fast_ema = (
        s.ewm(
            span=fast,
            adjust=False
        ).mean()
    )

    slow_ema = (
        s.ewm(
            span=slow,
            adjust=False
        ).mean()
    )

    macd_line = (
        fast_ema -
        slow_ema
    )

    signal_line = (
        macd_line
        .ewm(
            span=signal,
            adjust=False
        )
        .mean()
    )

    hist = (
        macd_line -
        signal_line
    )

    return (
        macd_line,
        signal_line,
        hist
    )


# =========================================================
# DAILY MACD REVERSAL
# =========================================================

def detect_daily_macd_reversal(
    closes
):

    macd_line, signal_line, hist = (
        macd_values(
            closes,
            MACD_FAST,
            MACD_SLOW,
            MACD_SIGNAL
        )
    )


    if (
        macd_line is None
        or
        len(macd_line) < 4
    ):

        return {

            "bend": False,

            "strong": False,

            "cross": False,

            "positive_turn": False,

            "line": None,

            "signal": None,

            "hist": None,

            "hist_slope": 0.0

        }


    m3, m2, m1, m0 = [

        float(x)

        for x in
        macd_line.iloc[-4:]

    ]


    s1 = float(
        signal_line.iloc[-2]
    )

    s0 = float(
        signal_line.iloc[-1]
    )


    h1 = float(
        hist.iloc[-2]
    )

    h0 = float(
        hist.iloc[-1]
    )


    prior_fall = (
        m3 > m2
    )

    rising_sequence = (
        m2 < m1 < m0
    )

    below_zero = (
        m0 < 0
    )


    bend = (
        prior_fall
        and
        rising_sequence
        and
        below_zero
    )


    strong = (
        m2 < m1 < m0
        and
        m0 < 0
        and
        (
            m0 - m1
        )
        >
        (
            m1 - m2
        ) * 0.50
    )


    cross = (
        macd_line.iloc[-2]
        <=
        signal_line.iloc[-2]

        and

        m0 > s0

        and

        m0 < 0
    )


    positive_turn = (
        bend
        or
        strong
    )


    return {

        "bend": bend,

        "strong": strong,

        "cross": cross,

        "positive_turn":
            positive_turn,

        "line": m0,

        "signal": s0,

        "hist": h0,

        "hist_slope":
            h0 - h1

    }


# =========================================================
# WEEKLY MACD
# =========================================================

def detect_weekly_macd_reversal(
    candles
):

    if not candles:

        return {

            "bend": False,

            "downtrend": False,

            "line": None,

            "signal": None

        }


    df = pd.DataFrame(
        candles
    )


    if (
        df.empty
        or
        "date" not in df.columns
    ):

        return {

            "bend": False,

            "downtrend": False,

            "line": None,

            "signal": None

        }


    df["date"] = pd.to_datetime(
        df["date"]
    )

    df = df.sort_values(
        "date"
    )


    df["week"] = (
        df["date"]
        .dt
        .to_period("W-FRI")
    )


    weekly = (
        df
        .groupby(
            "week",
            sort=True
        )["close"]
        .last()
    )


    minimum = (
        MACD_SLOW +
        MACD_SIGNAL +
        5
    )


    if len(weekly) < minimum:

        return {

            "bend": False,

            "downtrend": False,

            "line": None,

            "signal": None

        }


    fast_ema = (
        weekly
        .ewm(
            span=MACD_FAST,
            adjust=False
        )
        .mean()
    )


    slow_ema = (
        weekly
        .ewm(
            span=MACD_SLOW,
            adjust=False
        )
        .mean()
    )


    macd_line = (
        fast_ema -
        slow_ema
    )


    signal_line = (
        macd_line
        .ewm(
            span=MACD_SIGNAL,
            adjust=False
        )
        .mean()
    )


    m4, m3, m2, m1, m0 = [

        float(x)

        for x in
        macd_line.iloc[-5:]

    ]


    s0 = float(
        signal_line.iloc[-1]
    )


    downtrend = (

        m4 > m3 > m2 > m1

        and

        m1 < 0

        and

        m0 < 0

    )


    bend = (

        downtrend

        and

        m0 > m1

    )


    return {

        "bend": bend,

        "downtrend": downtrend,

        "line": m0,

        "signal": s0

    }


# =========================================================
# PROCESS TOP 200
# =========================================================

output_rows = []


for _, row in top200.iterrows():

    symbol = str(
        row[symbol_col]
    ).strip()


    try:

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

    except (
        TypeError,
        ValueError
    ):

        continue


    previous = (
        previous_lookup
        .get(symbol)
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
    # BASIC PRICE DATA
    # =====================================================

    previous_candle = (

        "RED 🔴"
        if previous_close < previous_open

        else

        "GREEN 🟢"
        if previous_close > previous_open

        else

        "DOJI"

    )


    if previous_close != 0:

        gap_up_pct = (

            (
                today_open -
                previous_close
            )
            /
            previous_close
            *
            100

        )

        current_gain_pct = (

            (
                today_close -
                previous_close
            )
            /
            previous_close
            *
            100

        )

    else:

        gap_up_pct = 0.0
        current_gain_pct = 0.0


    gap_maintained = (

        "YES ✅"
        if today_close >= today_open

        else

        "PARTIAL 🟡"
        if today_close > previous_close

        else

        "NO 🔴"

    )


    # =====================================================
    # HISTORY
    # =====================================================

    hist = sorted(

        history_data
        .get(symbol, []),

        key=lambda x:
            x["date"]

    )


    if len(hist) < 60:
        continue


    all_candles = (
        hist +
        [{
            "date":
                latest_date,

            "open":
                today_open,

            "high":
                today_high,

            "low":
                today_low,

            "close":
                today_close
        }]
    )


    closes = [
        x["close"]
        for x in all_candles
    ]


    # =====================================================
    # MACD
    # =====================================================

    daily = (
        detect_daily_macd_reversal(
            closes
        )
    )


    weekly = (
        detect_weekly_macd_reversal(
            all_candles
        )
    )


    # =====================================================
    # SETUP CANDLE
    # =====================================================

    setup = hist[-1]

    setup_index = (
        len(hist) - 1
    )


    _, _, setup_lower_bb = (
        get_bb_for_index(
            hist,
            setup_index
        )
    )


    # =====================================================
    # RSI
    # =====================================================

    setup_closes = [
        x["close"]
        for x in
        hist[:setup_index + 1]
    ]


    setup_rsi = (
        rsi_from_closes(
            setup_closes,
            RSI_LENGTH
        )
    )


    previous_rsi = (

        rsi_from_closes(
            setup_closes[:-1],
            RSI_LENGTH
        )

        if
        len(setup_closes)
        >=
        RSI_LENGTH + 2

        else
        None

    )


    current_rsi = (
        rsi_from_closes(
            closes,
            RSI_LENGTH
        )
    )


    rsi_recovery = (

        previous_rsi is not None

        and

        setup_rsi is not None

        and

        setup_rsi >
        previous_rsi

        and

        setup_rsi <= 50

    )


    current_rsi_recovery = (

        setup_rsi is not None

        and

        current_rsi is not None

        and

        current_rsi >
        setup_rsi

        and

        current_rsi <= 55

    )


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


    # =====================================================
    # LOWER BB ENGINE
    # =====================================================

    recent_bb_touch = False

    recent_bb_rejection = False

    best_lower_bb = (
        setup_lower_bb
    )

    bb_rejection_index = None


    recent_start = max(
        0,
        len(hist) - 4
    )


    for idx in range(
        recent_start,
        len(hist)
    ):

        _, _, bb_low = (
            get_bb_for_index(
                hist,
                idx
            )
        )


        if bb_low is None:
            continue


        bar = hist[idx]


        if bar["low"] <= bb_low:

            recent_bb_touch = True


            cs = candle_structure(

                bar["open"],
                bar["high"],
                bar["low"],
                bar["close"]

            )


            rejection = (

                cs[
                    "lower_wick_ratio"
                ] >= 0.20

                and

                cs[
                    "close_position"
                ] >= 0.50

                and

                bar["close"]
                >=
                bb_low

            )


            if rejection:

                recent_bb_rejection = True

                bb_rejection_index = idx

                best_lower_bb = bb_low


    # =====================================================
    # SETUP CANDLE BB REJECTION
    # =====================================================

    setup_cs = candle_structure(

        setup["open"],
        setup["high"],
        setup["low"],
        setup["close"]

    )


    setup_bb_touch = (

        setup_lower_bb is not None

        and

        setup["low"]
        <=
        setup_lower_bb

    )


    setup_bb_break = (

        setup_lower_bb is not None

        and

        setup["low"]
        <
        setup_lower_bb

    )


    setup_bb_close_back = (

        setup_lower_bb is not None

        and

        setup["close"]
        >=
        setup_lower_bb

    )


    meaningful_wick = (

        setup_cs[
            "lower_wick_ratio"
        ] >= 0.20

    )


    strong_wick = (

        setup_cs[
            "lower_wick_ratio"
        ] >= 0.30

    )


    setup_bb_rejection = (

        setup_bb_touch

        and

        setup_bb_close_back

        and

        meaningful_wick

    )


    # =====================================================
    # PREVIOUS RED + LOWER BB
    # =====================================================

    prev_idx = (
        len(hist) - 2
    )


    previous_red_lower_bb = False

    gapup_after_red_bb = False


    if prev_idx >= 0:

        _, _, prev_bb_low = (
            get_bb_for_index(
                hist,
                prev_idx
            )
        )


        prev_bar = hist[prev_idx]


        previous_red_lower_bb = (

            prev_bb_low is not None

            and

            prev_bar["close"]
            <
            prev_bar["open"]

            and

            prev_bar["low"]
            <=
            prev_bb_low

        )


        gapup_after_red_bb = (

            previous_red_lower_bb

            and

            today_open >
            prev_bar["close"]

            and

            today_close >
            today_open

        )


    # =====================================================
    # CORE BB PATTERN
    # =====================================================

    bb_core = (

        recent_bb_touch

        and

        recent_bb_rejection

    )


    bb_pattern = (

        bb_core

        or

        setup_bb_rejection

        or

        gapup_after_red_bb

    )


    # =====================================================
    # TODAY PRICE CONFIRMATION
    # =====================================================

    today_cs = candle_structure(

        today_open,
        today_high,
        today_low,
        today_close

    )


    strong_green = (

        today_close >
        today_open

        and

        today_cs[
            "body_ratio"
        ] >= 0.45

        and

        today_cs[
            "close_position"
        ] >= 0.65

    )


    high_break = (

        today_close >
        setup["high"]

    )


    low_protected = (

        today_low >=
        setup["low"]

    )


    gap_up = (
        gap_up_pct >= 0.50
    )


    strong_gap_up = (
        gap_up_pct >= 1.00
    )


    engulfing = (
        bullish_engulfing(
            setup,
            all_candles[-1]
        )
    )


    # =====================================================
    # CONFIRMATIONS
    # =====================================================

    confirmations_count = sum([

        strong_green,

        high_break,

        low_protected,

        gap_maintained == "YES ✅",

        engulfing,

        current_rsi_recovery,

        daily["positive_turn"],

        weekly["bend"]

    ])


    # =====================================================
    # V8.2 SCORE
    # =====================================================
    #
    # MAX = 100
    #
    # BB = 50
    # DAILY MACD = 15
    # PRICE = 15
    # RSI = 10
    # WEEKLY = 7
    # TURNOVER = 3
    #
    # =====================================================

    score = 0


    # -----------------------------------------------------
    # BB = 50
    # -----------------------------------------------------

    if bb_core:
        score += 30

    elif setup_bb_rejection:
        score += 27

    elif gapup_after_red_bb:
        score += 25


    if recent_bb_touch:
        score += 5


    if recent_bb_rejection:
        score += 6


    if meaningful_wick:
        score += 4


    if strong_wick:
        score += 2


    if previous_red_lower_bb:
        score += 3


    # -----------------------------------------------------
    # DAILY MACD = 15
    # -----------------------------------------------------

    if daily["bend"]:
        score += 10

    elif daily["strong"]:
        score += 8


    if daily["cross"]:
        score += 3


    if daily.get(
        "hist_slope",
        0
    ) > 0:

        score += 2


    # -----------------------------------------------------
    # PRICE = 15
    # -----------------------------------------------------

    if strong_green:
        score += 4


    if high_break:
        score += 4


    if low_protected:
        score += 3


    if gap_maintained == "YES ✅":
        score += 2


    if engulfing:
        score += 2


    # -----------------------------------------------------
    # RSI = 10
    # -----------------------------------------------------

    if rsi_recovery:
        score += 4


    if current_rsi_recovery:
        score += 3


    if oversold:
        score += 2


    if deep_oversold:
        score += 1


    # -----------------------------------------------------
    # WEEKLY = 7
    # -----------------------------------------------------

    if weekly["downtrend"]:
        score += 3


    if weekly["bend"]:
        score += 4


    # -----------------------------------------------------
    # TURNOVER = 3
    # -----------------------------------------------------

    turnover_rank_value = (
        turnover_rank.get(
            symbol,
            999
        )
    )


    if turnover_rank_value <= 25:
        score += 3

    elif turnover_rank_value <= 100:
        score += 2

    else:
        score += 1


    score = min(
        100,
        score
    )


    # =====================================================
    # V8.2 QUALIFICATION
    # =====================================================
    #
    # ONLY BB REVERSAL IS REQUIRED.
    #
    # NO MACD HARD FILTER
    # NO RSI HARD FILTER
    # NO WEEKLY HARD FILTER
    #
    # =====================================================

    qualified = (

        bb_pattern

        and

        score >= MIN_BB_SCORE

    )


    # =====================================================
    # PRIMARY SETUP
    # =====================================================

    primary_setup = "—"


    if bb_core:

        primary_setup = (
            "💎 STRONG BB REVERSAL"
        )

    elif setup_bb_rejection:

        primary_setup = (
            "💎 BB REJECTION"
        )

    elif gapup_after_red_bb:

        primary_setup = (
            "💎 RED + LOWER BB → GAP-UP"
        )


    # =====================================================
    # SETUP TEXT
    # =====================================================

    setup_names = []


    if bb_core:
        setup_names.append(
            "💎 BB REVERSAL"
        )

    elif setup_bb_rejection:
        setup_names.append(
            "💎 BB REJECTION"
        )


    if previous_red_lower_bb:
        setup_names.append(
            "RED + LOWER BB"
        )


    if gapup_after_red_bb:
        setup_names.append(
            "GAP-UP"
        )


    if oversold:
        setup_names.append(
            "🚀 OVERSOLD"
        )


    if rsi_recovery:
        setup_names.append(
            "RSI RECOVERY"
        )


    if current_rsi_recovery:
        setup_names.append(
            "CURRENT RSI ↑"
        )


    if daily["positive_turn"]:
        setup_names.append(
            "🔄 DAILY MACD BEND ↑"
        )


    if daily["cross"]:
        setup_names.append(
            "MACD CROSS"
        )


    if weekly["bend"]:
        setup_names.append(
            "📉 WEEKLY MACD BEND ↑"
        )


    if strong_green:
        setup_names.append(
            "GREEN"
        )


    if high_break:
        setup_names.append(
            "HIGH BREAK"
        )


    if low_protected:
        setup_names.append(
            "LOW HOLD"
        )


    if gap_maintained == "YES ✅":
        setup_names.append(
            "GAP HOLD"
        )


    if engulfing:
        setup_names.append(
            "ENGULFING"
        )


    full_setup = (

        " + ".join(
            setup_names
        )

        if setup_names

        else

        "—"

    )


    # =====================================================
    # SIGNAL
    # =====================================================

    if score >= 80:

        signal = (
            "🎯 TOP SWING"
        )

    elif score >= 65:

        signal = (
            "🔥 STRONG SWING"
        )

    elif score >= 50:

        signal = (
            "🟢 SWING WATCH"
        )

    else:

        signal = (
            "👀 BB WATCH"
        )


    # =====================================================
    # DAILY MACD TEXT
    # =====================================================

    if daily["bend"]:

        daily_macd_text = (
            "🔥 BEND ↑"
        )

    elif daily["strong"]:

        daily_macd_text = (
            "🟢 TURN ↑"
        )

    elif daily["cross"]:

        daily_macd_text = (
            "⚡ CROSS ↑"
        )

    else:

        daily_macd_text = (
            "—"
        )


    # =====================================================
    # WEEKLY MACD TEXT
    # =====================================================

    if weekly["bend"]:

        weekly_macd_text = (
            "🔥 BEND ↑"
        )

    elif weekly["downtrend"]:

        weekly_macd_text = (
            "📉 DOWN"
        )

    else:

        weekly_macd_text = (
            "—"
        )


    # =====================================================
    # CONFIRMATION TEXT
    # =====================================================

    confirmation_list = []


    if daily["positive_turn"]:
        confirmation_list.append(
            "DAILY MACD"
        )


    if rsi_recovery:
        confirmation_list.append(
            "RSI"
        )


    if strong_green:
        confirmation_list.append(
            "GREEN"
        )


    if high_break:
        confirmation_list.append(
            "HIGH BREAK"
        )


    if low_protected:
        confirmation_list.append(
            "LOW HOLD"
        )


    if engulfing:
        confirmation_list.append(
            "ENGULFING"
        )


    if weekly["bend"]:
        confirmation_list.append(
            "WEEKLY MACD"
        )


    if gapup_after_red_bb:
        confirmation_list.append(
            "GAP-UP"
        )


    confirmation_text = (

        " + ".join(
            confirmation_list
        )

        if confirmation_list

        else

        "BB ONLY"

    )


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
            best_lower_bb,
            2
        )
        if best_lower_bb is not None
        else "",

        round(
            setup_rsi,
            2
        )
        if setup_rsi is not None
        else "",

        round(
            previous_rsi,
            2
        )
        if previous_rsi is not None
        else "",

        "YES 🔄"
        if rsi_recovery
        else "NO",

        "YES ✅"
        if recent_bb_touch
        else "NO",

        "YES 🔥"
        if recent_bb_rejection
        else "NO",

        "YES 🔥"
        if engulfing
        else "NO",

        "YES 🔥"
        if oversold
        else "NO",

        "YES 🚀"
        if strong_green
        else "NO",

        "YES 🚀"
        if high_break
        else "NO",

        "YES ✅"
        if low_protected
        else "NO",

        primary_setup,

        full_setup,

        turnover_rank_value,

        score,

        signal,

        daily_macd_text,

        "YES 🚀"
        if daily["strong"]
        else "NO",

        "YES 🔥"
        if daily["cross"]
        else "NO",

        round(
            daily["line"],
            6
        )
        if daily["line"] is not None
        else "",

        round(
            daily["signal"],
            6
        )
        if daily["signal"] is not None
        else "",

        round(
            daily["hist"],
            6
        )
        if daily["hist"] is not None
        else "",

        weekly_macd_text,

        "YES 📉"
        if weekly["downtrend"]
        else "NO",

        "YES 🟢"
        if daily["positive_turn"]
        else "NO",

        round(
            current_rsi,
            2
        )
        if current_rsi is not None
        else "",

        "YES 💎"
        if previous_red_lower_bb
        else "NO",

        "YES 🚀"
        if gapup_after_red_bb
        else "NO",

        "YES 🔄"
        if current_rsi_recovery
        else "NO",

        "YES ✅"
        if qualified
        else "NO"

    ])


# =========================================================
# NIFTY200 HEADERS
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

    "Primary Setup",
    "Full Setup",

    "Turnover Rank",
    "Strength Score",
    "Signal",

    "Daily MACD",
    "Daily MACD Strong",
    "Daily MACD Cross",
    "Daily MACD Line",
    "Daily MACD Signal",
    "Daily MACD Hist",

    "Weekly MACD",
    "Weekly MACD Downtrend",

    "Daily MACD Positive Turn",

    "Current RSI",

    "Prev Red + Lower BB",
    "Gap-Up After BB",
    "Current RSI Recovery",

    "V8.2 Qualified"

]


# =========================================================
# GOOGLE RETRY
# =========================================================

def retry_google_call(
    func,
    label,
    attempts=5
):

    last_error = None

    for attempt in range(
        1,
        attempts + 1
    ):

        try:

            return func()

        except Exception as exc:

            last_error = exc

            print(
                f"Google Sheets retry "
                f"{attempt}/{attempts} "
                f"after {label}: "
                f"{exc}"
            )

            if attempt < attempts:

                time.sleep(
                    min(
                        2 ** attempt,
                        12
                    )
                )


    raise last_error


# =========================================================
# UPDATE NIFTY200
# =========================================================

retry_google_call(

    lambda:
        sheet_nifty.batch_clear(
            ["A1:AZ1000"]
        ),

    "NIFTY200 clear"

)


retry_google_call(

    lambda:
        sheet_nifty.update(
            "A1:AP1",
            [nifty_headers],
            value_input_option="RAW"
        ),

    "NIFTY200 headers"

)


if output_rows:

    retry_google_call(

        lambda:
            sheet_nifty.update(
                "A2",
                output_rows,
                value_input_option="RAW"
            ),

        "NIFTY200 data"

    )


# =========================================================
# FINAL LIST
# =========================================================
#
# V8.2:
#
# BB reversal is enough.
#
# MACD / RSI / WEEKLY MACD
# only increase score.
#
# NO MAXIMUM 3.
#
# =========================================================

qualified_rows = []


for row in output_rows:

    if len(row) < 42:
        continue


    qualified = (
        str(row[41])
        .startswith("YES")
    )


    if not qualified:
        continue


    try:

        score = float(
            row[26]
        )

        gain = float(
            row[10]
        )

        turnover_rank_value = float(
            row[25]
        )

    except (
        TypeError,
        ValueError
    ):

        continue


    # Confirmation count

    confirmation_count = 0


    for idx in [

        15, 17, 18, 19,
        20, 21, 22, 37,
        38, 39

    ]:

        if str(
            row[idx]
        ).startswith("YES"):

            confirmation_count += 1


    qualified_rows.append({

        "row": row,

        "score": score,

        "gain": gain,

        "turnover_rank":
            turnover_rank_value,

        "confirmations":
            confirmation_count

    })


# =========================================================
# FINAL SORT
# =========================================================

def final_sort_key(
    item
):

    return (

        item["score"],

        item["confirmations"],

        -item[
            "turnover_rank"
        ]

    )


qualified_rows.sort(
    key=final_sort_key,
    reverse=True
)


# =========================================================
# FINAL SIGNAL
# =========================================================

for rank, item in enumerate(

    qualified_rows,

    start=1

):

    score = item["score"]


    if rank == 1:

        item["signal"] = (
            "🎯 TOP SWING"
        )

    elif score >= 75:

        item["signal"] = (
            "🔥 STRONG SWING"
        )

    elif score >= 60:

        item["signal"] = (
            "🟢 SWING WATCH"
        )

    else:

        item["signal"] = (
            "👀 BB WATCH"
        )


# =========================================================
# FINAL HEADERS
# =========================================================

final_headers = [

    "Rank",

    "NSE Code",

    "CMP",

    "Gain %",

    "Lower BB",

    "RSI",

    "Daily MACD",

    "Weekly MACD",

    "Confirmation",

    "Primary Setup",

    "Full Setup",

    "Score",

    "Signal"

]


# =========================================================
# FINAL OUTPUT
# =========================================================

final_output = []


for rank, item in enumerate(

    qualified_rows,

    start=1

):

    row = item["row"]


    # -----------------------------------------------------
    # CONFIRMATIONS
    # -----------------------------------------------------

    confirmations = []


    if str(
        row[17]
    ).startswith("YES"):

        confirmations.append(
            "BB REJ"
        )


    if str(
        row[19]
    ).startswith("YES"):

        confirmations.append(
            "OVERSOLD"
        )


    if str(
        row[20]
    ).startswith("YES"):

        confirmations.append(
            "GREEN"
        )


    if str(
        row[21]
    ).startswith("YES"):

        confirmations.append(
            "HIGH BREAK"
        )


    if str(
        row[22]
    ).startswith("YES"):

        confirmations.append(
            "LOW HOLD"
        )


    if str(
        row[11]
    ).startswith("YES"):

        confirmations.append(
            "GAP HOLD"
        )


    if str(
        row[37]
    ).startswith("YES"):

        confirmations.append(
            "RED+LOWER BB"
        )


    if str(
        row[38]
    ).startswith("YES"):

        confirmations.append(
            "GAP-UP"
        )


    if str(
        row[39]
    ).startswith("YES"):

        confirmations.append(
            "RSI ↑"
        )


    confirmation_text = (

        " + ".join(
            confirmations
        )

        if confirmations

        else

        "BB ONLY"

    )


    # -----------------------------------------------------
    # FINAL MACD TEXT
    # -----------------------------------------------------

    daily_macd_text = row[28]

    weekly_macd_text = row[34]


    # -----------------------------------------------------
    # FINAL ROW
    # -----------------------------------------------------

    final_output.append([

        rank,

        row[0],

        row[9],

        row[10],

        row[12],

        row[39]
        if row[39] != ""
        else row[13],

        daily_macd_text,

        weekly_macd_text,

        confirmation_text,

        row[23],

        row[24],

        item["score"],

        item["signal"]

    ])


# =========================================================
# CLEAR FINAL LIST
# =========================================================

retry_google_call(

    lambda:
        sheet_final.batch_clear(
            ["A1:AZ1000"]
        ),

    "Final List clear"

)


# =========================================================
# FINAL HEADER
# =========================================================

retry_google_call(

    lambda:
        sheet_final.update(
            "A1:M1",
            [final_headers],
            value_input_option="RAW"
        ),

    "Final List headers"

)


# =========================================================
# FINAL DATA
# =========================================================

if final_output:

    retry_google_call(

        lambda:
            sheet_final.update(
                "A2",
                final_output,
                value_input_option="RAW"
            ),

        "Final List data"

    )


# =========================================================
# FORMATTING
# =========================================================

try:

    # Header

    sheet_final.format(

        "A1:M1",

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

            "horizontalAlignment":
                "CENTER",

            "verticalAlignment":
                "MIDDLE",

            "wrapStrategy":
                "WRAP"

        }

    )


    if final_output:

        last_row = (
            len(final_output) + 1
        )


        sheet_final.format(

            f"A2:M{last_row}",

            {

                "textFormat": {

                    "fontSize": 8

                },

                "horizontalAlignment":
                    "CENTER",

                "verticalAlignment":
                    "MIDDLE",

                "wrapStrategy":
                    "WRAP"

            }

        )


        # NSE Code

        sheet_final.format(

            f"B2:B{last_row}",

            {

                "textFormat": {

                    "bold": True,

                    "fontSize": 9

                },

                "horizontalAlignment":
                    "LEFT"

            }

        )


        # Setup columns

        sheet_final.format(

            f"I2:K{last_row}",

            {

                "textFormat": {

                    "bold": True,

                    "fontSize": 8

                },

                "wrapStrategy":
                    "WRAP"

            }

        )


        # Score + Signal

        sheet_final.format(

            f"L2:M{last_row}",

            {

                "textFormat": {

                    "bold": True,

                    "fontSize": 9

                },

                "wrapStrategy":
                    "WRAP"

            }

        )


        # Rank 1

        sheet_final.format(

            "A2:M2",

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


    sheet_final.freeze(
        rows=1
    )


except Exception as exc:

    print(
        "Final List Formatting Warning : "
        f"{exc}"
    )


# =========================================================
# SUMMARY
# =========================================================

print(
    "========================================"
)

print(
    "NIFTY 200 BB REVERSAL SCREENER V8.2"
)

print(
    "========================================"
)

print(
    "Trading Date : "
    f"{latest_date.strftime('%d-%b-%Y')}"
)

print(
    "Previous Date : "
    f"{previous_date.strftime('%d-%b-%Y')}"
)

print(
    "Stocks Scanned : "
    f"{len(output_rows)}"
)

print(
    "BB Candidates : "
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
    "LOWER BB : PRIMARY TRIGGER"
)

print(
    "MACD : CONFIRMATION ONLY"
)

print(
    "WEEKLY MACD : REGIME ONLY"
)

print(
    "RSI : CONFIRMATION ONLY"
)

print(
    "PRICE ACTION : CONFIRMATION"
)

print(
    "TURNOVER : SUPPORTING FACTOR"
)

print(
    "FINAL LIST : ALL BB REVERSAL CANDIDATES"
)

print(
    "MAXIMUM FINAL CANDIDATES : NO LIMIT"
)

print(
    "========================================"
)


for rank, item in enumerate(

    qualified_rows,

    start=1

):

    row = item["row"]

    print(

        rank,

        "|",

        row[0],

        "| Score:",

        item["score"],

        "| Gain:",

        item["gain"],

        "| Daily:",

        row[28],

        "| Weekly:",

        row[34],

        "| Signal:",

        item["signal"]

    )


print(
    "========================================"
)

print(
    "NIFTY200 V8.2 UPDATED"
)

print(
    "========================================"
)
