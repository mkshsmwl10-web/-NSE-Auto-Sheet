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
import numpy as np
import time

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

HISTORY_TRADING_DAYS = 220


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
# GOOGLE SHEETS SAFE RETRY
# =========================================================
def _is_retryable_google_error(exc):
    text = str(exc)
    return any(code in text for code in ("429", "500", "502", "503", "504"))


def safe_google_call(func, *args, retries=6, **kwargs):
    last_error = None
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except gspread.exceptions.APIError as exc:
            last_error = exc
            if not _is_retryable_google_error(exc) or attempt == retries - 1:
                raise
            wait = min(30, 2 ** attempt)
            print(f"Google Sheets API retry {attempt + 1}/{retries} after {wait}s : {exc}")
            time.sleep(wait)
    raise last_error


def safe_batch_clear(sheet, ranges):
    return safe_google_call(sheet.batch_clear, ranges)


def safe_update(sheet, *args, **kwargs):
    return safe_google_call(sheet.update, *args, **kwargs)


def safe_format(sheet, *args, **kwargs):
    return safe_google_call(sheet.format, *args, **kwargs)


# =========================================================
# GOOGLE SHEET
# =========================================================

spreadsheet = safe_google_call(
    client.open_by_key,
    SPREADSHEET_ID
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

    days_checked < 320

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
# DAILY MACD HISTOGRAM — FRESH BEND BELOW ZERO → UP
# =========================================================
def macd_histogram_from_closes(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return []
    series = pd.Series(closes, dtype=float)
    macd_line = series.ewm(span=fast, adjust=False).mean() - series.ewm(span=slow, adjust=False).mean()
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return (macd_line - signal_line).tolist()


def detect_macd_bend(closes, fast=12, slow=26, signal=9):
    """Daily MACD early reversal + positive turn."""
    min_bars = slow + signal + 5
    if len(closes) < min_bars:
        return False, False, False, False, None, None, None, None

    series = pd.Series(closes, dtype=float)
    macd_line = series.ewm(span=fast, adjust=False).mean() - series.ewm(span=slow, adjust=False).mean()
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line

    m3, m2, m1, m0 = [float(x) for x in macd_line.iloc[-4:]]
    h1, h0 = float(hist.iloc[-2]), float(hist.iloc[-1])
    s0 = float(signal_line.iloc[-1])

    bend_up = m2 < m3 and m1 <= m2 and m0 > m1 and m0 < 0
    strong_recovery = m2 < m3 and m1 > m2 and m0 > m1 and m0 < 0
    macd_cross_up = macd_line.iloc[-2] <= signal_line.iloc[-2] and macd_line.iloc[-1] > signal_line.iloc[-1]

    # Main V8 trigger: histogram turns positive now.
    daily_macd_positive_turn = h1 <= 0 and h0 > 0
    # If already above zero, a fresh rising histogram + bullish MACD cross is also valid.
    daily_macd_bullish = daily_macd_positive_turn or (h0 > 0 and h0 > h1 and macd_line.iloc[-1] > signal_line.iloc[-1])

    return bend_up, strong_recovery, macd_cross_up, daily_macd_positive_turn, m0, s0, h0, float(h0 - h1)


def detect_weekly_macd_reversal(candles, fast=12, slow=26, signal=9):
    """Weekly MACD must be in a downtrend and start bending upward below zero."""
    if not candles:
        return False, False, None, None

    df = pd.DataFrame(candles)
    if df.empty or "date" not in df.columns:
        return False, False, None, None

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    df["week"] = df["date"].dt.to_period("W-FRI")
    weekly = df.groupby("week", sort=True)["close"].last()

    if len(weekly) < slow + signal + 3:
        return False, False, None, None

    macd_line = weekly.ewm(span=fast, adjust=False).mean() - weekly.ewm(span=slow, adjust=False).mean()
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()

    m3, m2, m1, m0 = [float(x) for x in macd_line.iloc[-4:]]
    s0 = float(signal_line.iloc[-1])

    # Macro regime: MACD was falling for at least two weeks, then bends up.
    downtrend = m3 > m2 > m1 and m1 < 0
    bend_up = downtrend and m0 > m1 and m0 < 0
    return bend_up, downtrend, m0, s0


# =========================================================

# =========================================================
# DAILY CHART PATTERN ENGINE V8.1
# =========================================================
def _pct_diff(a, b):
    return 999.0 if b == 0 else abs(a-b)/abs(b)*100.0

def _extrema(vals, order=2):
    highs, lows = [], []
    for i in range(order, len(vals)-order):
        w = vals[i-order:i+order+1]
        if vals[i] == max(w): highs.append(i)
        if vals[i] == min(w): lows.append(i)
    return highs, lows

def detect_daily_patterns(candles):
    if len(candles) < 30:
        return '—', 0
    df = pd.DataFrame(candles).sort_values('date').reset_index(drop=True)
    for c in ['open','high','low','close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=['open','high','low','close']).reset_index(drop=True)
    if len(df) < 30: return '—', 0
    h, l, c = df['high'].tolist(), df['low'].tolist(), df['close'].tolist()
    n=len(df); found=[]

    # Double bottom: two similar lows, meaningful neckline, recent breakout.
    off=max(0,n-70); _, lows=_extrema(l[off:],2); lows=[x+off for x in lows]
    for i in range(len(lows)):
        for j in range(i+1,len(lows)):
            a,b=lows[i],lows[j]
            if b-a<6 or b<n-18 or _pct_diff(l[a],l[b])>4: continue
            neckline=max(h[a:b+1])
            if neckline>max(l[a],l[b])*1.04 and c[-1]>=neckline*0.985:
                found.append(('DOUBLE BOTTOM',9)); break
        if any(x[0]=='DOUBLE BOTTOM' for x in found): break

    # Cup & handle: broad U-shaped recovery with similar rims and shallow handle.
    if n>=80:
        start=max(0,n-140); end=n-12
        if end-start>=50:
            left=max(h[start:end]); li=start+h[start:end].index(left)
            ti=start+l[start:end].index(min(l[start:end]))
            rw=h[max(ti+5,start):end]
            if rw:
                ri=max(ti+5,start)+rw.index(max(rw)); right=h[ri]; trough=l[ti]
                depth=(min(left,right)-trough)/min(left,right)*100 if min(left,right)>0 else 0
                handle=c[-12:-2]
                if li<ti<ri and _pct_diff(left,right)<=10 and 8<=depth<=40 and handle:
                    hd=(right-min(handle))/right*100 if right else 999
                    if 2<=hd<=18 and c[-1]>=max(handle)*0.985:
                        found.append(('CUP & HANDLE',10))

    # Bull flag: strong prior impulse, controlled downward/flat consolidation, breakout.
    if n>=25:
        imp=c[-25:-10]; flag=c[-10:]
        if len(imp)>=8 and len(flag)>=6:
            impulse_gain=(max(imp)-min(imp))/max(min(imp),1e-9)*100
            slope=np.polyfit(range(len(flag)),flag,1)[0]
            fr=(max(flag)-min(flag))/max(max(flag),1e-9)*100
            if impulse_gain>=10 and slope<=0 and fr<=12 and c[-1]>=max(flag[:-1]):
                found.append(('BULL FLAG',8))

    # Triangles: converging upper/lower boundaries.
    if n>=25:
        hh=np.array(h[-25:],float); ll=np.array(l[-25:],float); x=np.arange(25)
        hs=np.polyfit(x,hh,1)[0]; ls=np.polyfit(x,ll,1)[0]
        hspan=(max(hh)-min(hh))/max(np.mean(hh),1e-9)*100
        lspan=(max(ll)-min(ll))/max(np.mean(ll),1e-9)*100
        if hs<0 and ls>0 and hspan>=2 and lspan>=2: found.append(('SYMMETRICAL TRIANGLE',8))
        elif ls>0 and abs(hs)<=abs(ls)*0.25 and hspan>=2: found.append(('ASCENDING TRIANGLE',8))
        elif hs<0 and abs(ls)<=abs(hs)*0.25 and lspan>=2: found.append(('DESCENDING TRIANGLE',5))

    # Wedges.
    if n>=25:
        hh=np.array(h[-25:],float); ll=np.array(l[-25:],float); x=np.arange(25)
        hs=np.polyfit(x,hh,1)[0]; ls=np.polyfit(x,ll,1)[0]
        if hs>0 and ls>0 and ls>hs*1.15: found.append(('RISING WEDGE',5))
        elif hs<0 and ls<0 and abs(hs)>abs(ls)*1.15: found.append(('FALLING WEDGE',7))

    # Rectangle/range.
    if n>=20:
        seg=c[-20:]; rng=(max(seg)-min(seg))/max(np.mean(seg),1e-9)*100
        slope=np.polyfit(range(len(seg)),seg,1)[0]
        if rng<=10 and abs(slope)/max(np.mean(seg),1e-9)*100<0.08: found.append(('RECTANGLE / RANGE',4))

    if not found: return '—',0
    found.sort(key=lambda x:x[1], reverse=True)
    seen=set(); names=[]
    for name,_ in found:
        if name not in seen:
            names.append(name); seen.add(name)
        if len(names)>=3: break
    score=max(dict(found).get(x,0) for x in names)
    return ' + '.join(names), score


def calculate_pattern_strength(row):
    """100-point pattern/reversal strength. BB + Daily MACD have highest weight."""
    def yes(i):
        return i < len(row) and str(row[i]).startswith("YES")

    # Output indexes from NIFTY200 row
    bb_touch = yes(16)
    bb_rejection = yes(17)
    prev_red_lower_bb = yes(37)
    gapup_after_bb = yes(38)

    macd_bend = yes(27)
    macd_strong = yes(28)
    macd_cross = yes(29)
    macd_positive = yes(35)

    try:
        pattern_score = float(row[41]) if str(row[41]).strip() else 0.0
    except (TypeError, ValueError, IndexError):
        pattern_score = 0.0

    # LOWER BB REVERSAL = 40 points
    bb_score = 0
    if bb_touch:
        bb_score += 5
    if bb_rejection:
        bb_score += 20
    if prev_red_lower_bb:
        bb_score += 10
    if gapup_after_bb:
        bb_score += 5

    # DAILY MACD REVERSAL = 40 points
    macd_score = 0
    if macd_bend:
        macd_score += 15
    if macd_strong:
        macd_score += 10
    if macd_positive:
        macd_score += 10
    if macd_cross:
        macd_score += 5

    # DAILY CHART PATTERN = 20 points
    pattern_component = min(20, max(0, pattern_score) * 2)

    total = min(100, bb_score + macd_score + pattern_component)

    if total >= 85:
        label = "💎 PRIME REVERSAL"
    elif total >= 70:
        label = "🔥 STRONG PATTERN"
    elif total >= 55:
        label = "👀 WATCH"
    else:
        label = "—"

    return round(total, 1), label

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

    pattern_candles = hist + [{"date": latest_date, "open": today_open, "high": today_high, "low": today_low, "close": today_close}]
    daily_pattern, pattern_score = detect_daily_patterns(pattern_candles)

    macd_closes = [x["close"] for x in hist] + [today_close]
    (
        macd_bend_up,
        macd_strong_recovery,
        macd_cross_up,
        daily_macd_positive_turn,
        macd_line_now,
        macd_signal_now,
        macd_hist_now,
        macd_hist_slope
    ) = detect_macd_bend(macd_closes)

    weekly_candles = hist + [{
        "date": latest_date,
        "close": today_close
    }]
    (
        weekly_macd_bend,
        weekly_macd_downtrend,
        weekly_macd_now,
        weekly_signal_now
    ) = detect_weekly_macd_reversal(weekly_candles)

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

    current_rsi = rsi_from_closes(macd_closes, 14)
    current_rsi_recovery = (
        setup_rsi is not None and
        current_rsi is not None and
        current_rsi > setup_rsi and
        current_rsi <= 55
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

    # Previous red candle at/through lower BB, followed by a gap-up bullish candle.
    previous_red_lower_bb = False
    gapup_after_red_bb = False
    if prev_setup is not None:
        prev_idx = len(hist) - 2
        _, _, prev_bb_low = get_bb_for_index(hist, prev_idx)
        previous_red_lower_bb = (
            prev_bb_low is not None and
            prev_setup["close"] < prev_setup["open"] and
            prev_setup["low"] <= prev_bb_low
        )
        gapup_after_red_bb = (
            previous_red_lower_bb and
            setup is not None and
            setup["open"] > prev_setup["close"] and
            setup["close"] > setup["open"]
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

    # ---------------------------------------------------------
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

    if macd_bend_up:
        score += 8
    if macd_strong_recovery:
        score += 4
    if macd_cross_up:
        score += 4

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
    # ---------------------------------------------------------

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

    if macd_bend_up:
        setup_names.append("🔄 MACD BEND UP")
    elif macd_cross_up:
        setup_names.append("🔥 MACD CROSS UP")

    if len(setup_names) == 0:
        setup_type = "—"
    else:
        setup_type = " + ".join(setup_names)

    # ---------------------------------------------------------
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
    # ---------------------------------------------------------

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

        final_signal,

        # Internal V7 fields; not shown in Final List.
        "YES 🔄" if macd_bend_up else "NO",
        "YES 🚀" if macd_strong_recovery else "NO",
        "YES 🔥" if macd_cross_up else "NO",
        (round(macd_line_now, 6) if macd_line_now is not None else ""),
        (round(macd_signal_now, 6) if macd_signal_now is not None else ""),
        (round(macd_hist_now, 6) if macd_hist_now is not None else ""),
        "YES 🔄" if weekly_macd_bend else "NO",
        "YES 📉" if weekly_macd_downtrend else "NO",
        "YES 🟢" if daily_macd_positive_turn else "NO",
        (round(current_rsi, 2) if current_rsi is not None else ""),
        "YES 💎" if previous_red_lower_bb else "NO",
        "YES 🚀" if gapup_after_red_bb else "NO",
        "YES 🔄" if current_rsi_recovery else "NO",
        daily_pattern,
        pattern_score
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
    "Signal",
    "Daily MACD Bend",
    "Daily MACD Strong Recovery",
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
    "Daily Chart Pattern",
    "Pattern Score"
]


# =========================================================
# WRITE NIFTY200
# =========================================================

safe_batch_clear(sheet_nifty, ["A1:AP1000"])

sheet_nifty.update(
    range_name="A1:AP1",
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
# V8 FINAL LIST — MACRO DOWN + DAILY TURN + BB REVERSAL
# =========================================================
# Core philosophy:
# 1. WEEKLY MACD = downtrend, but starting to bend up below zero.
# 2. DAILY MACD = turns positive / bullish above signal.
# 3. LOWER BB REVERSAL = primary trigger and highest weight.
# 4. RSI must recover from oversold/weak zone.
# 5. Strong bullish candle, high break, protected low, gap-up pattern
#    and turnover are confirmations — not substitutes for the core.
# 6. Maximum 3 stocks. Only #1 can be TOP SWING.
# =========================================================

SCORE_INDEX = 25
TURNOVER_RANK_INDEX = 24
GAIN_INDEX = 10

final_candidates = []

for row in output_rows:
    if len(row) < 38:
        continue
    try:
        base_score = float(row[SCORE_INDEX])
        gain = float(row[GAIN_INDEX])
        turnover_rank_value = float(row[TURNOVER_RANK_INDEX])
    except (TypeError, ValueError):
        continue

    rsi_recovery = str(row[15]).startswith("YES")
    bb_touch = str(row[16]).startswith("YES")
    bb_rejection = str(row[17]).startswith("YES")
    engulfing = str(row[18]).startswith("YES")
    oversold = str(row[19]).startswith("YES")
    strong_green = str(row[20]).startswith("YES")
    high_break = str(row[21]).startswith("YES")
    low_protected = str(row[22]).startswith("YES")
    gap_hold = str(row[11]).startswith("YES")

    macd_bend_up = str(row[27]).startswith("YES")
    macd_strong_recovery = str(row[28]).startswith("YES")
    macd_cross_up = str(row[29]).startswith("YES")
    daily_macd_positive_turn = str(row[35]).startswith("YES")
    weekly_macd_bend = str(row[33]).startswith("YES")
    weekly_macd_downtrend = str(row[34]).startswith("YES")
    previous_red_lower_bb = str(row[37]).startswith("YES")
    gapup_after_red_bb = str(row[38]).startswith("YES") if len(row) > 38 else False
    current_rsi_recovery = str(row[39]).startswith("YES") if len(row) > 39 else False
    daily_pattern = str(row[40]) if len(row) > 40 and str(row[40]).strip() else "—"
    pattern_score = float(row[41]) if len(row) > 41 and str(row[41]).strip() else 0.0

    try:
        gap_pct = float(row[8])
    except (TypeError, ValueError):
        gap_pct = 0.0

    # ---------------- V8 FINAL ROUTES ----------------
    # FINAL LIST = every stock that passes at least ONE valid
    # reversal route.  No all-conditions AND filter.
    # Daily MACD + Lower BB remain the highest-priority signals.

    if gain <= 0 or gain > 8:
        continue

    bb_core = bb_touch and bb_rejection

    # Daily MACD reversal: early bend below zero is intentionally
    # accepted before a full positive crossover.
    daily_macd_reversal = (
        macd_bend_up
        or macd_strong_recovery
        or daily_macd_positive_turn
        or macd_cross_up
    )

    weekly_macd_reversal = (
        weekly_macd_downtrend and weekly_macd_bend
    )

    bb_route = (
        bb_core
        or previous_red_lower_bb
        or gapup_after_red_bb
        or (recent_bb_touch and (strong_green or engulfing))
    )

    macd_route = daily_macd_reversal

    rsi_route = (
        oversold
        or rsi_recovery
        or current_rsi_recovery
    )

    gap_route = (
        previous_red_lower_bb
        and gapup_after_red_bb
    )

    price_route = (
        strong_green
        and (high_break or low_protected or gap_hold)
    )

    engulf_route = (
        engulfing
        and (recent_bb_touch or oversold or selling_exhaustion)
    )

    # Weekly MACD is a regime/quality filter, not a mandatory gate.
    # This prevents the Final List from becoming empty while still
    # rewarding the desired weekly downtrend -> bend setup.
    any_valid_route = (
        bb_route
        or macd_route
        or rsi_route
        or gap_route
        or price_route
        or engulf_route
    )

    if not any_valid_route:
        continue

    confirmations = sum([
        bb_core,
        daily_macd_reversal,
        weekly_macd_reversal,
        oversold,
        rsi_recovery or current_rsi_recovery,
        strong_green,
        high_break,
        low_protected,
        gapup_after_red_bb,
        engulfing
    ])

    # ---------------- V8 SCORE ----------------
    # 100-point scale. BB + Daily MACD dominate.
    score = 0

    # A. LOWER BB REVERSAL — PRIMARY
    if bb_core:
        score += 28
    elif recent_bb_touch:
        score += 15

    if bb_rejection:
        score += 10
    if previous_red_lower_bb:
        score += 7
    if gapup_after_red_bb:
        score += 7

    # B. DAILY MACD REVERSAL — PRIMARY
    if macd_bend_up:
        score += 15
    if macd_strong_recovery:
        score += 5
    if daily_macd_positive_turn:
        score += 8
    if macd_cross_up:
        score += 4

    # C. WEEKLY MACD — REGIME CONFIRMATION
    if weekly_macd_downtrend:
        score += 5
    if weekly_macd_bend:
        score += 7

    # D. RSI RECOVERY
    if oversold:
        score += 5
    if rsi_recovery:
        score += 6
    if current_rsi_recovery:
        score += 4
    if deep_oversold:
        score += 2

    # E. PRICE CONFIRMATION
    if strong_green:
        score += 5
    if high_break:
        score += 5
    if low_protected:
        score += 4
    if gap_maintained == "YES ✅":
        score += 3
    if engulfing:
        score += 3

    # F. TURNOVER — SUPPORTIVE ONLY
    if turnover_rank_value <= 25:
        score += 4
    elif turnover_rank_value <= 50:
        score += 3
    elif turnover_rank_value <= 100:
        score += 2
    else:
        score += 1

    # Fresh move bonus: leave room for the intended swing.
    if 0.5 <= gain <= 3:
        score += 4
    elif 3 < gain <= 5:
        score += 2

    # Chart pattern is confirmation only; BB + Daily MACD remain primary.
    if pattern_score >= 9: score += 5
    elif pattern_score >= 7: score += 4
    elif pattern_score >= 5: score += 2

    score = min(100, score)

    if score >= 82:
        signal = "🎯 TOP SWING"
    elif score >= 72:
        signal = "🔥 STRONG SWING"
    else:
        signal = "👀 WATCH"

    pattern_strength, pattern_signal = calculate_pattern_strength(row)

    final_candidates.append({
        "row": row,
        "score": score,
        "gain": gain,
        "turnover_rank": turnover_rank_value,
        "confirmations": confirmations,
        "signal": signal,
        "pattern_strength": pattern_strength,
        "pattern_signal": pattern_signal
    })


def freshness_distance(gain):
    return abs(gain - 2.5)


final_candidates.sort(
    key=lambda x: (
        x["score"],
        x["confirmations"],
        -freshness_distance(x["gain"]),
        -x["turnover_rank"]
    ),
    reverse=True
)
# Keep ALL qualified stocks; ranking decides priority.

# Only rank #1 can be TOP SWING.
for rank, item in enumerate(final_candidates, start=1):
    if rank == 1 and item["score"] >= 82 and item["confirmations"] >= 3:
        item["signal"] = "🎯 TOP SWING"
    elif item["score"] >= 72:
        item["signal"] = "🔥 STRONG SWING"
    else:
        item["signal"] = "👀 WATCH"

# =========================================================
# COMPACT CLEAN FINAL LIST V8
# =========================================================
final_headers = [
    "Rank", "NSE Code", "CMP", "Gain %", "Lower BB", "RSI",
    "Daily MACD", "Weekly MACD", "Confirmation", "Setup", "Pattern",
    "Pattern Strength", "Pattern Signal", "Score", "Signal", "Chart"
]

final_output = []
for rank, item in enumerate(final_candidates, start=1):
    row = item["row"]
    confirmations = []
    if str(row[17]).startswith("YES"): confirmations.append("BB REJ")
    if str(row[19]).startswith("YES"): confirmations.append("OVERSOLD")
    if str(row[20]).startswith("YES"): confirmations.append("GREEN")
    if str(row[21]).startswith("YES"): confirmations.append("HIGH BREAK")
    if str(row[22]).startswith("YES"): confirmations.append("LOW HOLD")
    if str(row[11]).startswith("YES"): confirmations.append("GAP HOLD")
    if str(row[37]).startswith("YES"): confirmations.append("RED+LOWER BB")
    if str(row[38]).startswith("YES"): confirmations.append("GAP-UP")

    macd_text = "MACD+" if str(row[35]).startswith("YES") else ("BEND ↑" if str(row[27]).startswith("YES") else "—")
    weekly_text = "BEND ↑" if str(row[33]).startswith("YES") else ("DOWN 📉" if str(row[34]).startswith("YES") else "—")
    pattern_name = str(row[40]).strip() if len(row) > 40 and str(row[40]).strip() else "—"
    final_output.append([
        rank,
        row[0],
        row[9],
        row[10],
        row[12],
        row[36] if len(row) > 36 else row[13],
        macd_text,
        weekly_text,
        " + ".join(confirmations),
        row[23],
        pattern_name,
        item["pattern_strength"],
        item["pattern_signal"],
        item["score"],
        item["signal"],
        f'=HYPERLINK("https://www.tradingview.com/chart/?symbol=NSE%3A{row[0]}","📈 CHART")'
    ])

safe_batch_clear(sheet_final, ["A1:AZ1000"])
safe_update(sheet_final, "A1:P1", [final_headers], value_input_option="RAW")
if final_output:
    safe_update(sheet_final, "A2", final_output, value_input_option="USER_ENTERED")

# =========================================================
# CLEAN V8 FORMATTING
# =========================================================
try:
    safe_format(sheet_final, "A1:P1", {
        "backgroundColor": {"red": 0.05, "green": 0.12, "blue": 0.20},
        "textFormat": {"bold": True, "fontSize": 9, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP"
    })
    if final_output:
        last_row = len(final_output) + 1
        safe_format(sheet_final, f"A2:P{last_row}", {
            "textFormat": {"fontSize": 8},
            "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP"
        })
        safe_format(sheet_final, f"B2:B{last_row}", {"textFormat": {"bold": True, "fontSize": 9}, "horizontalAlignment": "LEFT"})
        safe_format(sheet_final, f"I2:J{last_row}", {"textFormat": {"bold": True, "fontSize": 8}, "wrapStrategy": "WRAP"})
        safe_format(sheet_final, f"K2:O{last_row}", {"textFormat": {"bold": True, "fontSize": 9}, "wrapStrategy": "WRAP"})
        safe_format(sheet_final, f"P2:P{last_row}", {"textFormat": {"bold": True, "fontSize": 9}, "horizontalAlignment": "CENTER"})
        safe_format(sheet_final, "A2:M2", {
            "backgroundColor": {"red": 0.90, "green": 0.97, "blue": 0.90},
            "textFormat": {"bold": True, "fontSize": 9}
        })
    widths = {"A:A": 38, "B:B": 100, "C:C": 75, "D:D": 55, "E:E": 75, "F:F": 50,
              "G:G": 70, "H:H": 70, "I:I": 180, "J:J": 180, "K:K": 150, "L:L": 70,
              "M:M": 125, "N:N": 55, "O:O": 105, "P:P": 90}
    for col_range, width in widths.items():
        try:
            safe_format(sheet_final, col_range, {"padding": {"top": 2, "bottom": 2, "left": 2, "right": 2}})
        except Exception:
            pass
    sheet_final.freeze(rows=1)
except Exception as e:
    print(f"Final List Formatting Warning : {e}")

# =========================================================
# V7 SUMMARY
# =========================================================

print("----------------------------------------")
print("FINAL LIST V8 : ANY VALID REVERSAL ROUTE | BB + DAILY MACD PRIORITY")
print(f"Qualified Stocks : {len(final_output)}")

for rank, item in enumerate(final_candidates, start=1):
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
print("NIFTY200 V8 SWING SCREENER UPDATED")
print(f"Trading Date : {latest_date.strftime('%d-%b-%Y')}")
print(f"Previous Date : {previous_date.strftime('%d-%b-%Y')}")
print(f"Stocks Scanned : {len(output_rows)}")
print(f"Final Candidates : {len(final_output)}")
print("----------------------------------------")
print("TOP 200 BY TURNOVER : YES")
print("BOLLINGER : 20, 1.5")
print("RSI : 14")
print("SETUPS : BB REVERSAL / ENGULFING / OVERSOLD + RSI RECOVERY")
print("V8 : WEEKLY MACD DOWN-TREND + BEND + DAILY MACD POSITIVE TURN + LOWER BB REVERSAL")
print("V8.2 : ALL QUALIFIED STOCKS — NO TOP-3 LIMIT")
print("V8 : RANK #1 IS TOP SWING WHEN SCORE >= 85")
print("MACD : DAILY BEND/POSITIVE TURN + WEEKLY DOWN/BEND | LOWER BB HIGHEST PRIORITY")
print("V8.2 PATTERN STRENGTH : LOWER BB 40 + DAILY MACD 40 + CHART PATTERN 20")
print("PATTERN : DAILY DOUBLE BOTTOM / CUP & HANDLE / BULL FLAG / TRIANGLES / WEDGES / RANGE")
print("========================================")
