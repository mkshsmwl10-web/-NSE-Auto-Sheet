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

HISTORY_TRADING_DAYS = 60


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
# V8.1 CLEAN REVERSAL ENGINE
# =========================================================
#
# CORE ORDER:
# 1) WEEKLY MACD: DOWN-TREND -> FRESH BEND UP, STILL BELOW ZERO
# 2) DAILY MACD: MACD LINE BENDS UP BELOW ZERO
# 3) LOWER BB REVERSAL: PRIMARY PRICE TRIGGER
# 4) RSI RECOVERY FROM WEAK/OVERSOLD ZONE
# 5) PRICE CONFIRMATION: GREEN / HIGH BREAK / LOW HOLD / GAP
# 6) TURNOVER: SUPPORTING FACTOR ONLY
#
# IMPORTANT:
# - Histogram alone NEVER qualifies a MACD reversal.
# - Weekly MACD already above zero / established uptrend = REJECT.
# - Daily MACD must be below zero when it turns.
# - Lower BB rejection gets the highest score.
# - Final List = maximum 3 fully qualified candidates.
# =========================================================

BB_LENGTH = 20
BB_MULTIPLIER = 1.5
RSI_LENGTH = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9


def rsi_from_closes(closes, length=14):
    if len(closes) < length + 1:
        return None

    s = pd.Series(closes, dtype=float)
    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(length).mean().iloc[-1]
    avg_loss = loss.rolling(length).mean().iloc[-1]

    if pd.isna(avg_gain) or pd.isna(avg_loss):
        return None

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def calculate_bb(candles, length=20, multiplier=1.5):
    if len(candles) < length:
        return None, None, None

    closes = pd.Series(
        [float(x["close"]) for x in candles[-length:]],
        dtype=float
    )

    middle = float(closes.mean())
    std = float(closes.std(ddof=0))
    upper = middle + multiplier * std
    lower = middle - multiplier * std

    return upper, middle, lower


def get_bb_for_index(candles, index):
    if index < BB_LENGTH - 1:
        return None, None, None

    return calculate_bb(
        candles[index - BB_LENGTH + 1:index + 1],
        BB_LENGTH,
        BB_MULTIPLIER
    )


def candle_structure(open_price, high_price, low_price, close_price):
    candle_range = high_price - low_price

    if candle_range <= 0:
        return {
            "body_ratio": 0.0,
            "close_position": 0.0,
            "lower_wick_ratio": 0.0,
            "upper_wick_ratio": 0.0
        }

    body = abs(close_price - open_price)
    lower_wick = min(open_price, close_price) - low_price
    upper_wick = high_price - max(open_price, close_price)

    return {
        "body_ratio": body / candle_range,
        "close_position": (close_price - low_price) / candle_range,
        "lower_wick_ratio": lower_wick / candle_range,
        "upper_wick_ratio": upper_wick / candle_range
    }


def bullish_engulfing(prev_candle, curr_candle):
    if prev_candle is None or curr_candle is None:
        return False

    if prev_candle["close"] >= prev_candle["open"]:
        return False

    if curr_candle["close"] <= curr_candle["open"]:
        return False

    return (
        curr_candle["open"] <= prev_candle["close"]
        and curr_candle["close"] >= prev_candle["open"]
    )


def macd_values(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal + 5:
        return None, None, None

    s = pd.Series(closes, dtype=float)
    fast_ema = s.ewm(span=fast, adjust=False).mean()
    slow_ema = s.ewm(span=slow, adjust=False).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line

    return macd_line, signal_line, hist


def detect_daily_macd_reversal(closes):
    """
    Fresh DAILY MACD LINE reversal below zero.

    Required:
    - prior MACD was falling
    - last 3 MACD values are rising
    - current MACD remains below zero

    Cross and histogram improvement are secondary confirmations.
    """
    macd_line, signal_line, hist = macd_values(
        closes,
        MACD_FAST,
        MACD_SLOW,
        MACD_SIGNAL
    )

    if macd_line is None or len(macd_line) < 4:
        return {
            "bend": False,
            "strong": False,
            "cross": False,
            "positive_turn": False,
            "line": None,
            "signal": None,
            "hist": None
        }

    m3, m2, m1, m0 = [
        float(x) for x in macd_line.iloc[-4:]
    ]

    s1 = float(signal_line.iloc[-2])
    s0 = float(signal_line.iloc[-1])

    h1 = float(hist.iloc[-2])
    h0 = float(hist.iloc[-1])

    prior_fall = m3 > m2
    rising_sequence = m2 < m1 < m0
    below_zero = m0 < 0

    bend = prior_fall and rising_sequence and below_zero

    strong = (
        m2 < m1 < m0
        and m0 < 0
        and (m0 - m1) > (m1 - m2) * 0.50
    )

    cross = (
        float(macd_line.iloc[-2]) <= s1
        and m0 > s0
        and m0 < 0
    )

    positive_turn = bend or strong

    return {
        "bend": bend,
        "strong": strong,
        "cross": cross,
        "positive_turn": positive_turn,
        "line": m0,
        "signal": s0,
        "hist": h0,
        "hist_slope": h0 - h1
    }


def detect_weekly_macd_reversal(candles):
    """
    WEEKLY regime filter.

    Required:
    - previous weekly MACD values were declining
    - current weekly MACD has just turned upward
    - current weekly MACD is still below zero

    This deliberately rejects established positive/uptrend MACD.
    """
    if not candles:
        return {
            "bend": False,
            "downtrend": False,
            "line": None,
            "signal": None
        }

    df = pd.DataFrame(candles)

    if df.empty or "date" not in df.columns:
        return {
            "bend": False,
            "downtrend": False,
            "line": None,
            "signal": None
        }

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")

    # Friday-ended trading weeks.
    df["week"] = df["date"].dt.to_period("W-FRI")
    weekly = df.groupby("week", sort=True)["close"].last()

    minimum = MACD_SLOW + MACD_SIGNAL + 5
    if len(weekly) < minimum:
        return {
            "bend": False,
            "downtrend": False,
            "line": None,
            "signal": None
        }

    fast_ema = weekly.ewm(
        span=MACD_FAST,
        adjust=False
    ).mean()

    slow_ema = weekly.ewm(
        span=MACD_SLOW,
        adjust=False
    ).mean()

    macd_line = fast_ema - slow_ema

    signal_line = macd_line.ewm(
        span=MACD_SIGNAL,
        adjust=False
    ).mean()

    m4, m3, m2, m1, m0 = [
        float(x) for x in macd_line.iloc[-5:]
    ]

    s0 = float(signal_line.iloc[-1])

    # Established weekly downtrend before the turn.
    downtrend = (
        m4 > m3 > m2 > m1
        and m1 < 0
        and m0 < 0
    )

    # Fresh turn only now.
    bend = (
        downtrend
        and m0 > m1
    )

    return {
        "bend": bend,
        "downtrend": downtrend,
        "line": m0,
        "signal": s0
    }


def retry_google_call(func, label, attempts=5):
    """
    Google Sheets occasionally returns 503.
    Retry transient failures instead of killing the workflow.
    """
    import time

    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:
            last_error = exc
            print(
                f"Google Sheets retry {attempt}/{attempts} "
                f"after {label}: {exc}"
            )
            if attempt < attempts:
                time.sleep(min(2 ** attempt, 12))

    raise last_error


# =========================================================
# PROCESS TOP 200
# =========================================================

output_rows = []

for _, row in top200.iterrows():

    symbol = str(row[symbol_col]).strip()

    try:
        turnover = float(row[turnover_col])
        today_open = float(row[open_col])
        today_high = float(row[high_col])
        today_low = float(row[low_col])
        today_close = float(row[close_col])
    except (TypeError, ValueError):
        continue

    previous = previous_lookup.get(symbol)
    if previous is None:
        continue

    previous_open = previous["open"]
    previous_high = previous["high"]
    previous_low = previous["low"]
    previous_close = previous["close"]

    previous_candle = (
        "RED 🔴" if previous_close < previous_open
        else "GREEN 🟢" if previous_close > previous_open
        else "DOJI"
    )

    if previous_close != 0:
        gap_up_pct = (
            (today_open - previous_close)
            / previous_close * 100
        )
        current_gain_pct = (
            (today_close - previous_close)
            / previous_close * 100
        )
    else:
        gap_up_pct = 0.0
        current_gain_pct = 0.0

    gap_maintained = (
        "YES ✅" if today_close >= today_open
        else "PARTIAL 🟡" if today_close > previous_close
        else "NO 🔴"
    )

    hist = sorted(
        history_data.get(symbol, []),
        key=lambda x: x["date"]
    )

    if len(hist) < 60:
        continue

    # Add the latest trading day for daily/weekly current readings.
    all_candles = hist + [{
        "date": latest_date,
        "open": today_open,
        "high": today_high,
        "low": today_low,
        "close": today_close
    }]

    closes = [x["close"] for x in all_candles]

    daily = detect_daily_macd_reversal(closes)
    weekly = detect_weekly_macd_reversal(all_candles)

    # Previous trading day is the main setup candle.
    setup = hist[-1]
    setup_index = len(hist) - 1

    _, _, setup_lower_bb = get_bb_for_index(
        hist,
        setup_index
    )

    setup_closes = [
        x["close"] for x in hist[:setup_index + 1]
    ]

    setup_rsi = rsi_from_closes(
        setup_closes,
        RSI_LENGTH
    )

    previous_rsi = (
        rsi_from_closes(
            setup_closes[:-1],
            RSI_LENGTH
        )
        if len(setup_closes) >= RSI_LENGTH + 2
        else None
    )

    current_rsi = rsi_from_closes(
        closes,
        RSI_LENGTH
    )

    rsi_recovery = (
        previous_rsi is not None
        and setup_rsi is not None
        and setup_rsi > previous_rsi
        and setup_rsi <= 50
    )

    current_rsi_recovery = (
        setup_rsi is not None
        and current_rsi is not None
        and current_rsi > setup_rsi
        and current_rsi <= 55
    )

    oversold = (
        setup_rsi is not None
        and setup_rsi <= 35
    )

    deep_oversold = (
        setup_rsi is not None
        and setup_rsi <= 30
    )

    # -----------------------------------------------------
    # LOWER BB REVERSAL — PRIMARY
    # -----------------------------------------------------

    recent_bb_touch = False
    recent_bb_rejection = False
    best_lower_bb = setup_lower_bb
    bb_rejection_index = None

    recent_start = max(0, len(hist) - 4)

    for idx in range(recent_start, len(hist)):
        _, _, bb_low = get_bb_for_index(hist, idx)

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
                cs["lower_wick_ratio"] >= 0.20
                and cs["close_position"] >= 0.50
                and bar["close"] >= bb_low
            )

            if rejection:
                recent_bb_rejection = True
                bb_rejection_index = idx
                best_lower_bb = bb_low

    setup_bb_rejection = (
        setup_lower_bb is not None
        and setup["low"] <= setup_lower_bb
        and setup["close"] >= setup_lower_bb
        and candle_structure(
            setup["open"],
            setup["high"],
            setup["low"],
            setup["close"]
        )["lower_wick_ratio"] >= 0.20
    )

    # Previous red candle at lower BB + today's gap-up concept.
    prev_idx = len(hist) - 2
    previous_red_lower_bb = False
    gapup_after_red_bb = False

    if prev_idx >= 0:
        _, _, prev_bb_low = get_bb_for_index(
            hist,
            prev_idx
        )

        prev_bar = hist[prev_idx]

        previous_red_lower_bb = (
            prev_bb_low is not None
            and prev_bar["close"] < prev_bar["open"]
            and prev_bar["low"] <= prev_bb_low
        )

        gapup_after_red_bb = (
            previous_red_lower_bb
            and today_open > prev_bar["close"]
            and today_close > today_open
        )

    bb_core = (
        recent_bb_touch
        and recent_bb_rejection
    )

    bb_pattern = (
        bb_core
        or gapup_after_red_bb
        or setup_bb_rejection
    )

    # -----------------------------------------------------
    # PRICE CONFIRMATION
    # -----------------------------------------------------

    today_cs = candle_structure(
        today_open,
        today_high,
        today_low,
        today_close
    )

    strong_green = (
        today_close > today_open
        and today_cs["body_ratio"] >= 0.45
        and today_cs["close_position"] >= 0.65
    )

    high_break = today_close > setup["high"]

    low_protected = today_low >= setup["low"]

    gap_up = gap_up_pct >= 0.50
    strong_gap_up = gap_up_pct >= 1.00

    engulfing = bullish_engulfing(
        setup,
        all_candles[-1]
    )

    # "Green + high break + low hold" are price confirmation.
    confirmations = sum([
        strong_green,
        high_break,
        low_protected,
        gap_maintained == "YES ✅",
        gapup_after_red_bb
    ])

    # -----------------------------------------------------
    # HARD V8.1 CORE
    # -----------------------------------------------------
    #
    # Weekly regime + daily MACD + lower BB + RSI are the
    # reversal engine. Price action confirms it.
    # -----------------------------------------------------

    weekly_core = (
        weekly["downtrend"]
        and weekly["bend"]
    )

    daily_core = (
        daily["positive_turn"]
        and daily["line"] is not None
        and daily["line"] < 0
    )

    rsi_core = (
        rsi_recovery
        or current_rsi_recovery
    )

    price_core = confirmations >= 2

    qualified = (
        weekly_core
        and daily_core
        and bb_pattern
        and rsi_core
        and price_core
    )

    # -----------------------------------------------------
    # SCORE — 100 MAX
    # -----------------------------------------------------

    score = 0

    # LOWER BB: 35 points — highest priority.
    if bb_core:
        score += 25
    elif setup_bb_rejection or gapup_after_red_bb:
        score += 18

    if recent_bb_rejection:
        score += 6

    if previous_red_lower_bb:
        score += 4

    # DAILY MACD: 30 points — second highest.
    if daily["bend"]:
        score += 22
    elif daily["strong"]:
        score += 18

    if daily["cross"]:
        score += 4

    if daily.get("hist_slope", 0) > 0:
        score += 4

    # WEEKLY REGIME: 15 points.
    if weekly["downtrend"]:
        score += 8

    if weekly["bend"]:
        score += 7

    # RSI: 10 points.
    if rsi_recovery:
        score += 5

    if current_rsi_recovery:
        score += 3

    if oversold:
        score += 2

    # PRICE CONFIRMATION: 7 points.
    if strong_green:
        score += 2

    if high_break:
        score += 2

    if low_protected:
        score += 1

    if gap_maintained == "YES ✅":
        score += 1

    if engulfing:
        score += 1

    # TURNOVER: 3 points only.
    turnover_rank_value = turnover_rank.get(
        symbol,
        999
    )

    if turnover_rank_value <= 25:
        score += 3
    elif turnover_rank_value <= 100:
        score += 2
    else:
        score += 1

    score = min(100, score)

    # -----------------------------------------------------
    # SETUP TEXT
    # -----------------------------------------------------

    setup_names = []

    if bb_core or setup_bb_rejection:
        setup_names.append("💎 BB REVERSAL")

    if previous_red_lower_bb:
        setup_names.append("RED+LOWER BB")

    if gapup_after_red_bb:
        setup_names.append("GAP-UP")

    if oversold:
        setup_names.append("🚀 OVERSOLD")

    if rsi_recovery or current_rsi_recovery:
        setup_names.append("🚀 RSI RECOVERY")

    if daily["positive_turn"]:
        setup_names.append("🔄 DAILY MACD BEND UP")

    if weekly["bend"]:
        setup_names.append("📉 WEEKLY MACD BEND")

    if strong_green:
        setup_names.append("GREEN")

    if high_break:
        setup_names.append("HIGH BREAK")

    if low_protected:
        setup_names.append("LOW HOLD")

    if gap_maintained == "YES ✅":
        setup_names.append("GAP HOLD")

    setup_type = (
        " + ".join(setup_names)
        if setup_names
        else "—"
    )

    if score >= 85:
        signal = "🎯 TOP SWING"
    elif score >= 75:
        signal = "🔥 STRONG SWING"
    else:
        signal = "👀 WATCH"

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
        round(best_lower_bb, 2) if best_lower_bb is not None else "",
        round(setup_rsi, 2) if setup_rsi is not None else "",
        round(previous_rsi, 2) if previous_rsi is not None else "",
        "YES 🔄" if rsi_recovery else "NO",
        "YES ✅" if recent_bb_touch else "NO",
        "YES 🔥" if recent_bb_rejection else "NO",
        "YES 🔥" if engulfing else "NO",
        "YES 🔥" if oversold else "NO",
        "YES 🚀" if strong_green else "NO",
        "YES 🚀" if high_break else "NO",
        "YES ✅" if low_protected else "NO",
        setup_type,
        turnover_rank_value,
        score,
        signal,
        "YES 🔄" if daily["bend"] else "NO",
        "YES 🚀" if daily["strong"] else "NO",
        "YES 🔥" if daily["cross"] else "NO",
        round(daily["line"], 6) if daily["line"] is not None else "",
        round(daily["signal"], 6) if daily["signal"] is not None else "",
        round(daily["hist"], 6) if daily["hist"] is not None else "",
        "YES 🔄" if weekly["bend"] else "NO",
        "YES 📉" if weekly["downtrend"] else "NO",
        "YES 🟢" if daily["positive_turn"] else "NO",
        round(current_rsi, 2) if current_rsi is not None else "",
        "YES 💎" if previous_red_lower_bb else "NO",
        "YES 🚀" if gapup_after_red_bb else "NO",
        "YES 🔄" if current_rsi_recovery else "NO",
        "YES ✅" if qualified else "NO"
    ])


# =========================================================
# NIFTY200 OUTPUT
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
    "Signal",
    "Daily MACD Bend",
    "Daily MACD Strong",
    "Daily MACD Cross",
    "Daily MACD Line",
    "Daily MACD Signal",
    "Daily MACD Hist",
    "Weekly MACD Bend",
    "Weekly MACD Downtrend",
    "Daily MACD Positive Turn",
    "Current RSI",
    "Prev Red + Lower BB",
    "Gap-Up After BB",
    "Current RSI Recovery",
    "V8.1 Qualified"
]

retry_google_call(
    lambda: sheet_nifty.batch_clear(["A1:AZ1000"]),
    "NIFTY200 clear"
)

retry_google_call(
    lambda: sheet_nifty.update(
        "A1:AO1",
        [nifty_headers],
        value_input_option="RAW"
    ),
    "NIFTY200 header update"
)

if output_rows:
    retry_google_call(
        lambda: sheet_nifty.update(
            "A2",
            output_rows,
            value_input_option="RAW"
        ),
        "NIFTY200 data update"
    )


# =========================================================
# FINAL LIST
# =========================================================
#
# Only fully qualified V8.1 stocks enter this list.
# Maximum 3.
# =========================================================

qualified_rows = []

for row in output_rows:
    if len(row) < 42:
        continue

    qualified = str(row[41]).startswith("YES")
    if not qualified:
        continue

    try:
        score = float(row[25])
        gain = float(row[10])
        turnover_rank_value = float(row[24])
    except (TypeError, ValueError):
        continue

    confirmations = sum([
        str(row[20]).startswith("YES"),
        str(row[21]).startswith("YES"),
        str(row[22]).startswith("YES"),
        str(row[11]).startswith("YES"),
        str(row[38]).startswith("YES")
    ])

    qualified_rows.append({
        "row": row,
        "score": score,
        "gain": gain,
        "turnover_rank": turnover_rank_value,
        "confirmations": confirmations
    })


def final_sort_key(item):
    # BB and daily MACD are already dominant in score.
    # Keep price confirmation as the first tie-breaker.
    return (
        item["score"],
        item["confirmations"],
        -abs(item["gain"] - 2.5),
        -item["turnover_rank"]
    )


qualified_rows.sort(
    key=final_sort_key,
    reverse=True
)

qualified_rows = qualified_rows[:3]

for rank, item in enumerate(
    qualified_rows,
    start=1
):
    if rank == 1:
        item["signal"] = "🎯 TOP SWING"
    elif item["score"] >= 75:
        item["signal"] = "🔥 STRONG SWING"
    else:
        item["signal"] = "👀 WATCH"


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
    "Setup",
    "Score",
    "Signal"
]

final_output = []

for rank, item in enumerate(
    qualified_rows,
    start=1
):
    row = item["row"]

    confirmations = []

    if str(row[17]).startswith("YES"):
        confirmations.append("BB REJ")

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

    if str(row[37]).startswith("YES"):
        confirmations.append("RED+LOWER BB")

    if str(row[38]).startswith("YES"):
        confirmations.append("GAP-UP")

    daily_macd_text = (
        "BEND ↑"
        if str(row[27]).startswith("YES")
        else "—"
    )

    weekly_macd_text = (
        "BEND ↑"
        if str(row[33]).startswith("YES")
        else "—"
    )

    final_output.append([
        rank,
        row[0],
        row[9],
        row[10],
        row[12],
        row[39] if row[39] != "" else row[13],
        daily_macd_text,
        weekly_macd_text,
        " + ".join(confirmations),
        row[23],
        item["score"],
        item["signal"]
    ])


retry_google_call(
    lambda: sheet_final.batch_clear(["A1:AZ1000"]),
    "Final List clear"
)

retry_google_call(
    lambda: sheet_final.update(
        "A1:L1",
        [final_headers],
        value_input_option="RAW"
    ),
    "Final List header update"
)

if final_output:
    retry_google_call(
        lambda: sheet_final.update(
            "A2",
            final_output,
            value_input_option="RAW"
        ),
        "Final List data update"
    )


# =========================================================
# FORMATTING
# =========================================================

try:
    sheet_final.format(
        "A1:L1",
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

        sheet_final.format(
            f"A2:L{last_row}",
            {
                "textFormat": {"fontSize": 8},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP"
            }
        )

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

        sheet_final.format(
            f"I2:J{last_row}",
            {
                "textFormat": {
                    "bold": True,
                    "fontSize": 8
                },
                "wrapStrategy": "WRAP"
            }
        )

        sheet_final.format(
            f"K2:L{last_row}",
            {
                "textFormat": {
                    "bold": True,
                    "fontSize": 9
                },
                "wrapStrategy": "WRAP"
            }
        )

        sheet_final.format(
            "A2:L2",
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

    sheet_final.freeze(rows=1)

except Exception as exc:
    print(
        f"Final List Formatting Warning : {exc}"
    )


# =========================================================
# SUMMARY
# =========================================================

print("----------------------------------------")
print(
    "FINAL LIST V8.1 : "
    "WEEKLY DOWN+BEND -> DAILY MACD BEND -> "
    "LOWER BB REVERSAL"
)
print(
    f"Qualified Stocks : "
    f"{len(final_output)}"
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
        "| Swing Score:",
        item["score"],
        "| Gain:",
        item["gain"],
        "| Turnover Rank:",
        item["turnover_rank"],
        "| Confirmations:",
        item["confirmations"],
        "| Signal:",
        item["signal"]
    )

print("========================================")
print("NIFTY200 V8.1 SWING SCREENER UPDATED")
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
print("----------------------------------------")
print("TOP 200 BY TURNOVER : YES")
print("BOLLINGER : 20, 1.5")
print("RSI : 14")
print("WEEKLY MACD : DOWN-TREND + FRESH BEND UP BELOW ZERO")
print("DAILY MACD : MACD LINE FRESH BEND UP BELOW ZERO")
print("LOWER BB : PRIMARY REVERSAL TRIGGER")
print("RSI : RECOVERY REQUIRED")
print("PRICE : GREEN / HIGH BREAK / LOW HOLD / GAP CONFIRMATION")
print("TURNOVER : SUPPORTING FACTOR ONLY")
print("FINAL LIST : MAXIMUM 3 FULLY QUALIFIED STOCKS")
print("TOP SWING : ONLY RANK #1")
print("GOOGLE SHEETS : TRANSIENT 503 RETRY ENABLED")
print("========================================")
