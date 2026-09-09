# ============================================================
# NIFTY 200 SWING SNIPER V2.1.2
# ============================================================
#
# FINAL CORRECTED VERSION
#
# FIXES:
# 1. GitHub Actions GCP_CREDENTIALS secret supported
# 2. No credentials.json local-file dependency
# 3. Correct Turnover Rank
# 4. Exact 22 Final List columns
# 5. Strict BUY filters
# 6. True Retest + Hold
# 7. Fresh Breakout
# 8. Breakout Watch
# 9. Risk <= 5%
# 10. Previous 20-Day Range <= 18%
# 11. Extension <= 3%
# 12. TradingView chart links
#
# NO:
# BB
# MACD
# SuperTrend
# Intraday logic
# Random candlestick patterns
#
# ============================================================

import os
import json
import time
import math
import gspread

import numpy as np
import pandas as pd

from oauth2client.service_account import ServiceAccountCredentials


# ============================================================
# CONFIG
# ============================================================

SPREADSHEET_ID = "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E"

NIFTY_SHEET = "NIFTY200"
FINAL_SHEET = "Final List"

TOP_STOCKS = 200
HISTORY_TRADING_DAYS = 120

BREAKOUT_LOOKBACK = 20

EMA_FAST = 20
EMA_SLOW = 50

RSI_LENGTH = 14

RSI_REJECT = 50
RSI_BUY_MIN = 55
RSI_BUY_MAX = 68
RSI_WATCH_MAX = 70
RSI_HARD_REJECT = 80

VOLUME_LENGTH = 20
MIN_VOLUME_RATIO = 1.50

MAX_BREAKOUT_EXTENSION_PCT = 3.0

WATCH_DISTANCE_PCT = 2.0

RETEST_LOOKBACK_DAYS = 5
RETEST_MAX_ABOVE_PCT = 1.0
RETEST_MAX_BELOW_PCT = 3.0

MAX_RISK_PCT = 5.0

TARGET1_R = 1.5
TARGET2_R = 3.0

MIN_BUY_SCORE = 70
MIN_WATCH_SCORE = 60

MAX_FINAL_STOCKS = 12


# ============================================================
# GOOGLE API SCOPES
# ============================================================

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]


# ============================================================
# SAFE FLOAT
# ============================================================

def safe_float(value, default=np.nan):

    try:

        if value is None:
            return default

        if isinstance(value, str):

            value = (
                value
                .replace(",", "")
                .replace("%", "")
                .strip()
            )

        return float(value)

    except Exception:

        return default


# ============================================================
# CLEAN SYMBOL
# ============================================================

def clean_symbol(symbol):

    if symbol is None:
        return ""

    return (
        str(symbol)
        .strip()
        .upper()
        .replace(".NS", "")
    )


# ============================================================
# TRADINGVIEW URL
# ============================================================

def tradingview_url(symbol):

    symbol = clean_symbol(symbol)

    symbol = (
        symbol
        .replace("&", "%26")
        .replace(" ", "%20")
    )

    return (
        '=HYPERLINK('
        f'"https://www.tradingview.com/chart/?symbol=NSE%3A{symbol}",'
        '"Chart")'
    )


# ============================================================
# GOOGLE SHEETS AUTH
# ============================================================

def connect_google_sheet():

    print("\nConnecting to Google Sheets...")

    # --------------------------------------------------------
    # METHOD 1:
    # GitHub Actions secret
    # GCP_CREDENTIALS
    # --------------------------------------------------------

    credentials_json = os.environ.get(
        "GCP_CREDENTIALS"
    )

    if credentials_json:

        print(
            "Using GCP_CREDENTIALS environment secret."
        )

        try:

            credentials_data = json.loads(
                credentials_json
            )

        except json.JSONDecodeError as e:

            raise ValueError(
                "GCP_CREDENTIALS secret is not valid JSON."
            ) from e

        creds = (
            ServiceAccountCredentials
            .from_json_keyfile_dict(
                credentials_data,
                SCOPES
            )
        )

    else:

        # ----------------------------------------------------
        # METHOD 2:
        # Local credentials.json
        # ----------------------------------------------------

        credentials_file = "credentials.json"

        if not os.path.exists(
            credentials_file
        ):

            raise FileNotFoundError(
                "\nGoogle credentials not found.\n\n"
                "For GitHub Actions, add repository secret:\n"
                "GCP_CREDENTIALS\n\n"
                "The secret must contain the complete "
                "Google service-account JSON."
            )

        print(
            "Using local credentials.json."
        )

        creds = (
            ServiceAccountCredentials
            .from_json_keyfile_name(
                credentials_file,
                SCOPES
            )
        )

    client = gspread.authorize(
        creds
    )

    spreadsheet = client.open_by_key(
        SPREADSHEET_ID
    )

    print(
        "Google Sheets connection successful."
    )

    return spreadsheet


# ============================================================
# READ NIFTY200
# ============================================================

def read_nifty200_sheet(spreadsheet):

    print(
        f"\nReading sheet: {NIFTY_SHEET}"
    )

    worksheet = spreadsheet.worksheet(
        NIFTY_SHEET
    )

    records = worksheet.get_all_records()

    if not records:

        raise ValueError(
            f"{NIFTY_SHEET} sheet is empty."
        )

    df = pd.DataFrame(
        records
    )

    print(
        f"Rows loaded: {len(df)}"
    )

    print(
        "Columns found:"
    )

    print(
        list(df.columns)
    )

    return df


# ============================================================
# NORMALIZE COLUMNS
# ============================================================

def normalize_columns(df):

    df = df.copy()

    df.columns = [
        str(c).strip()
        for c in df.columns
    ]

    rename_map = {}

    for col in df.columns:

        c = (
            str(col)
            .lower()
            .replace(" ", "")
            .replace("_", "")
            .replace("-", "")
        )

        if c in [
            "symbol",
            "nsecode",
            "nse",
            "ticker",
            "code"
        ]:

            rename_map[col] = "Symbol"

        elif c in [
            "date",
            "tradingdate",
            "tradedate"
        ]:

            rename_map[col] = "Date"

        elif c == "open":

            rename_map[col] = "Open"

        elif c == "high":

            rename_map[col] = "High"

        elif c == "low":

            rename_map[col] = "Low"

        elif c in [
            "close",
            "ltp",
            "closingprice"
        ]:

            rename_map[col] = "Close"

        elif c in [
            "turnover",
            "value",
            "tradedvalue",
            "totalturnover",
            "turnovervalue"
        ]:

            rename_map[col] = "Turnover"

        elif c in [
            "volume",
            "qty",
            "quantity",
            "tradedqty",
            "shares",
            "volumeqty"
        ]:

            rename_map[col] = "Volume"

    df = df.rename(
        columns=rename_map
    )

    required = [
        "Symbol",
        "Date",
        "Open",
        "High",
        "Low",
        "Close"
    ]

    missing = [
        c
        for c in required
        if c not in df.columns
    ]

    if missing:

        raise ValueError(
            "\nMissing required columns: "
            f"{missing}\n\n"
            "NIFTY200 sheet must contain:\n"
            "Symbol, Date, Open, High, Low, Close\n"
            "and preferably Turnover, Volume."
        )

    return df


# ============================================================
# PREPARE HISTORY
# ============================================================

def prepare_history(df):

    df = normalize_columns(
        df
    )

    df = df.copy()

    df["Symbol"] = (
        df["Symbol"]
        .astype(str)
        .map(clean_symbol)
    )

    df["Date"] = pd.to_datetime(
        df["Date"],
        errors="coerce"
    )

    numeric_columns = [
        "Open",
        "High",
        "Low",
        "Close",
        "Turnover",
        "Volume"
    ]

    for col in numeric_columns:

        if col not in df.columns:

            df[col] = np.nan

        else:

            df[col] = (
                df[col]
                .map(safe_float)
            )

    df = df.dropna(
        subset=[
            "Symbol",
            "Date",
            "Open",
            "High",
            "Low",
            "Close"
        ]
    )

    df = df[
        (df["High"] >= df["Low"]) &
        (df["Close"] > 0)
    ]

    df = df.sort_values(
        [
            "Symbol",
            "Date"
        ]
    )

    df = df.drop_duplicates(
        subset=[
            "Symbol",
            "Date"
        ],
        keep="last"
    )

    return df


# ============================================================
# VALID SYMBOL
# ============================================================

def is_valid_symbol(symbol):

    symbol = clean_symbol(
        symbol
    )

    if not symbol:
        return False

    blocked_words = [
        "ETF",
        "BEES",
        "LIQUID",
        "GILT",
        "INDEX",
        "NIFTY",
        "SENSEX"
    ]

    for word in blocked_words:

        if word in symbol:

            return False

    return True


# ============================================================
# TOP 200 TURNOVER
# ============================================================

def get_top_200_symbols(history):

    latest_date = history[
        "Date"
    ].max()

    latest = history[
        history["Date"] == latest_date
    ].copy()

    latest = latest[
        latest["Symbol"]
        .map(is_valid_symbol)
    ].copy()

    if latest.empty:

        raise ValueError(
            "No valid stocks found on latest trading date."
        )

    latest["Turnover"] = pd.to_numeric(
        latest["Turnover"],
        errors="coerce"
    )

    # --------------------------------------------------------
    # IMPORTANT
    # Turnover must exist
    # --------------------------------------------------------

    if latest["Turnover"].notna().sum() == 0:

        raise ValueError(
            "\nTurnover data is missing from NIFTY200 sheet.\n\n"
            "The V2.1.2 screener needs historical Turnover "
            "to rank the NIFTY 200 stocks."
        )

    latest = latest.dropna(
        subset=["Turnover"]
    )

    latest = (
        latest
        .sort_values(
            "Turnover",
            ascending=False
        )
        .drop_duplicates(
            subset=["Symbol"],
            keep="first"
        )
        .reset_index(drop=True)
    )

    latest = latest.head(
        TOP_STOCKS
    ).copy()

    # --------------------------------------------------------
    # CORRECT UNIQUE RANK
    # --------------------------------------------------------

    latest["Turnover Rank"] = (
        np.arange(
            1,
            len(latest) + 1
        )
    )

    if not latest[
        "Turnover Rank"
    ].is_unique:

        raise ValueError(
            "Turnover Rank is not unique."
        )

    print("\n")
    print("=" * 70)
    print("TOP 200 TURNOVER CHECK")
    print("=" * 70)

    print(
        f"Latest trading date : "
        f"{latest_date.date()}"
    )

    print(
        f"Stocks selected     : "
        f"{len(latest)}"
    )

    print(
        f"Rank minimum        : "
        f"{latest['Turnover Rank'].min()}"
    )

    print(
        f"Rank maximum        : "
        f"{latest['Turnover Rank'].max()}"
    )

    print(
        f"Unique ranks        : "
        f"{latest['Turnover Rank'].nunique()}"
    )

    print("\nTop 10:")

    print(
        latest[
            [
                "Turnover Rank",
                "Symbol",
                "Turnover"
            ]
        ]
        .head(10)
        .to_string(index=False)
    )

    return latest


# ============================================================
# RSI
# ============================================================

def calculate_rsi(
    close,
    length=14
):

    delta = close.diff()

    gain = delta.clip(
        lower=0
    )

    loss = -delta.clip(
        upper=0
    )

    avg_gain = (
        gain
        .ewm(
            alpha=1 / length,
            adjust=False,
            min_periods=length
        )
        .mean()
    )

    avg_loss = (
        loss
        .ewm(
            alpha=1 / length,
            adjust=False,
            min_periods=length
        )
        .mean()
    )

    rs = (
        avg_gain /
        avg_loss.replace(
            0,
            np.nan
        )
    )

    rsi = (
        100 -
        (
            100 /
            (1 + rs)
        )
    )

    rsi = rsi.where(
        avg_loss != 0,
        100
    )

    return rsi


# ============================================================
# ATR
# ============================================================

def calculate_atr(
    df,
    length=14
):

    previous_close = (
        df["Close"]
        .shift(1)
    )

    tr1 = (
        df["High"] -
        df["Low"]
    )

    tr2 = (
        df["High"] -
        previous_close
    ).abs()

    tr3 = (
        df["Low"] -
        previous_close
    ).abs()

    tr = pd.concat(
        [
            tr1,
            tr2,
            tr3
        ],
        axis=1
    ).max(axis=1)

    atr = (
        tr
        .ewm(
            alpha=1 / length,
            adjust=False,
            min_periods=length
        )
        .mean()
    )

    return atr


# ============================================================
# ADD INDICATORS
# ============================================================

def add_indicators(df):

    df = df.copy()

    df["EMA20"] = (
        df["Close"]
        .ewm(
            span=EMA_FAST,
            adjust=False
        )
        .mean()
    )

    df["EMA50"] = (
        df["Close"]
        .ewm(
            span=EMA_SLOW,
            adjust=False
        )
        .mean()
    )

    df["RSI14"] = calculate_rsi(
        df["Close"],
        RSI_LENGTH
    )

    df["ATR14"] = calculate_atr(
        df,
        14
    )

    # --------------------------------------------------------
    # PREVIOUS 20 COMPLETED DAYS
    # --------------------------------------------------------

    df["Prev20High"] = (
        df["High"]
        .rolling(
            BREAKOUT_LOOKBACK
        )
        .max()
        .shift(1)
    )

    df["Prev20Low"] = (
        df["Low"]
        .rolling(
            BREAKOUT_LOOKBACK
        )
        .min()
        .shift(1)
    )

    # --------------------------------------------------------
    # RANGE
    # --------------------------------------------------------

    df["Range20Pct"] = (
        (
            df["Prev20High"] -
            df["Prev20Low"]
        )
        /
        df["Prev20Low"]
        *
        100
    )

    # --------------------------------------------------------
    # VOLUME
    # Previous 20 days only
    # --------------------------------------------------------

    df["AvgVolume20"] = (
        df["Volume"]
        .rolling(
            VOLUME_LENGTH
        )
        .mean()
        .shift(1)
    )

    df["VolumeRatio"] = (
        df["Volume"] /
        df["AvgVolume20"]
    )

    # --------------------------------------------------------
    # EMA SLOPE
    # --------------------------------------------------------

    df["EMA20SlopePct"] = (
        (
            df["EMA20"] -
            df["EMA20"].shift(5)
        )
        /
        df["EMA20"].shift(5)
        *
        100
    )

    # --------------------------------------------------------
    # TODAY CHANGE
    # --------------------------------------------------------

    df["TodayChangePct"] = (
        df["Close"]
        .pct_change()
        *
        100
    )

    return df


# ============================================================
# FIND PREVIOUS BREAKOUT
# ============================================================

def find_previous_breakout(df):

    if len(df) < (
        BREAKOUT_LOOKBACK +
        RETEST_LOOKBACK_DAYS +
        10
    ):

        return None

    today_idx = (
        len(df) - 1
    )

    start_idx = max(
        1,
        today_idx -
        RETEST_LOOKBACK_DAYS
    )

    for idx in range(
        start_idx,
        today_idx
    ):

        row = df.iloc[idx]

        close = row["Close"]

        prev_high = (
            row["Prev20High"]
        )

        volume_ratio = (
            row["VolumeRatio"]
        )

        rsi = row["RSI14"]

        ema20 = row["EMA20"]
        ema50 = row["EMA50"]

        range20 = row["Range20Pct"]

        if pd.isna(prev_high):
            continue

        if pd.isna(volume_ratio):
            continue

        if pd.isna(rsi):
            continue

        if pd.isna(ema20):
            continue

        if pd.isna(ema50):
            continue

        if pd.isna(range20):
            continue

        # Trend
        if ema20 <= ema50:
            continue

        # Breakout
        if close <= prev_high:
            continue

        # Volume
        if volume_ratio < MIN_VOLUME_RATIO:
            continue

        # RSI
        if not (
            RSI_BUY_MIN <=
            rsi <
            RSI_BUY_MAX
        ):

            continue

        # Extension
        extension = (
            (
                close -
                prev_high
            )
            /
            prev_high
            *
            100
        )

        if extension > MAX_BREAKOUT_EXTENSION_PCT:
            continue

        # Range
        if range20 > 18:
            continue

        return {
            "index": idx,
            "date": row["Date"],
            "level": float(prev_high)
        }

    return None


# ============================================================
# TRUE RETEST
# ============================================================

def check_true_retest(
    df,
    breakout_info
):

    if breakout_info is None:
        return False

    today = df.iloc[-1]

    level = float(
        breakout_info["level"]
    )

    today_low = float(
        today["Low"]
    )

    today_close = float(
        today["Close"]
    )

    upper_level = (
        level *
        (
            1 +
            RETEST_MAX_ABOVE_PCT /
            100
        )
    )

    lower_level = (
        level *
        (
            1 -
            RETEST_MAX_BELOW_PCT /
            100
        )
    )

    # --------------------------------------------------------
    # LOW MUST ACTUALLY COME BACK TO BREAKOUT ZONE
    # --------------------------------------------------------

    if not (
        today_low <= upper_level
        and
        today_low >= lower_level
    ):

        return False

    # --------------------------------------------------------
    # CLOSE MUST HOLD ABOVE BREAKOUT
    # --------------------------------------------------------

    if today_close <= level:
        return False

    # --------------------------------------------------------
    # EXTENSION
    # --------------------------------------------------------

    extension = (
        (
            today_close -
            level
        )
        /
        level
        *
        100
    )

    if extension > MAX_BREAKOUT_EXTENSION_PCT:
        return False

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    rsi = today["RSI14"]

    if pd.isna(rsi):
        return False

    if not (
        RSI_BUY_MIN <=
        rsi <
        RSI_BUY_MAX
    ):

        return False

    # --------------------------------------------------------
    # TREND
    # --------------------------------------------------------

    if today["EMA20"] <= today["EMA50"]:
        return False

    if today["Close"] <= today["EMA20"]:
        return False

    # --------------------------------------------------------
    # RANGE
    # --------------------------------------------------------

    if (
        pd.isna(today["Range20Pct"])
        or
        today["Range20Pct"] > 18
    ):

        return False

    return True


# ============================================================
# FRESH BREAKOUT
# ============================================================

def check_fresh_breakout(df):

    today = df.iloc[-1]

    close = float(
        today["Close"]
    )

    breakout_level = (
        today["Prev20High"]
    )

    if pd.isna(breakout_level):
        return False

    # Trend
    if today["EMA20"] <= today["EMA50"]:
        return False

    if close <= today["EMA20"]:
        return False

    # Breakout
    if close <= breakout_level:
        return False

    # Volume
    if (
        pd.isna(today["VolumeRatio"])
        or
        today["VolumeRatio"] <
        MIN_VOLUME_RATIO
    ):

        return False

    # RSI
    if pd.isna(today["RSI14"]):
        return False

    if not (
        RSI_BUY_MIN <=
        today["RSI14"] <
        RSI_BUY_MAX
    ):

        return False

    # Extension
    extension = (
        (
            close -
            breakout_level
        )
        /
        breakout_level
        *
        100
    )

    if extension > MAX_BREAKOUT_EXTENSION_PCT:
        return False

    # Range
    if (
        pd.isna(today["Range20Pct"])
        or
        today["Range20Pct"] > 18
    ):

        return False

    return True


# ============================================================
# BREAKOUT WATCH
# ============================================================

def check_breakout_watch(df):

    today = df.iloc[-1]

    close = float(
        today["Close"]
    )

    breakout_level = (
        today["Prev20High"]
    )

    if pd.isna(breakout_level):
        return False

    # Must remain below breakout
    if close >= breakout_level:
        return False

    distance_pct = (
        (
            breakout_level -
            close
        )
        /
        breakout_level
        *
        100
    )

    if distance_pct > WATCH_DISTANCE_PCT:
        return False

    # Trend
    if today["EMA20"] <= today["EMA50"]:
        return False

    if close <= today["EMA20"]:
        return False

    # RSI
    rsi = today["RSI14"]

    if pd.isna(rsi):
        return False

    if not (
        RSI_BUY_MIN <=
        rsi <=
        RSI_WATCH_MAX
    ):

        return False

    # Range
    if (
        pd.isna(today["Range20Pct"])
        or
        today["Range20Pct"] > 18
    ):

        return False

    return True


# ============================================================
# TRADE LEVELS
# ============================================================

def calculate_trade_levels(
    df,
    setup
):

    today = df.iloc[-1]

    close = float(
        today["Close"]
    )

    breakout_level = float(
        today["Prev20High"]
    )

    atr = float(
        today["ATR14"]
    )

    recent_low = float(
        df["Low"]
        .tail(5)
        .min()
    )

    if (
        not np.isfinite(atr)
        or
        atr <= 0
    ):

        atr = close * 0.02

    # Entry
    if setup == "BREAKOUT WATCH":

        entry = breakout_level

    else:

        entry = close

    # Structural stop
    structural_stop = (
        recent_low -
        0.25 * atr
    )

    # ATR stop
    atr_stop = (
        entry -
        1.0 * atr
    )

    stop = max(
        structural_stop,
        atr_stop
    )

    if stop >= entry:

        stop = (
            entry -
            0.75 * atr
        )

    risk_pct = (
        (
            entry -
            stop
        )
        /
        entry
        *
        100
    )

    # Hard cap
    if risk_pct > MAX_RISK_PCT:

        stop = (
            entry *
            (
                1 -
                MAX_RISK_PCT /
                100
            )
        )

        risk_pct = MAX_RISK_PCT

    risk_amount = (
        entry -
        stop
    )

    target1 = (
        entry +
        TARGET1_R *
        risk_amount
    )

    target2 = (
        entry +
        TARGET2_R *
        risk_amount
    )

    return {
        "Entry": entry,
        "Stop Loss": stop,
        "Target 1": target1,
        "Target 2": target2,
        "Risk %": risk_pct
    }


# ============================================================
# QUALITY SCORE
# ============================================================

def calculate_score(
    df,
    setup
):

    today = df.iloc[-1]

    score = 0

    close = today["Close"]
    ema20 = today["EMA20"]
    ema50 = today["EMA50"]
    rsi = today["RSI14"]
    volume_ratio = today["VolumeRatio"]
    range20 = today["Range20Pct"]
    ema_slope = today["EMA20SlopePct"]

    # EMA trend
    if ema20 > ema50:
        score += 20

    # Close > EMA20
    if close > ema20:
        score += 15

    # Rising EMA
    if (
        not pd.isna(ema_slope)
        and
        ema_slope > 0
    ):

        score += 10

    # RSI
    if not pd.isna(rsi):

        if 55 <= rsi < 68:

            score += 15

        elif 68 <= rsi <= 70:

            score += 8

    # Volume
    if not pd.isna(volume_ratio):

        if volume_ratio >= 2.0:

            score += 15

        elif volume_ratio >= 1.5:

            score += 10

        elif volume_ratio >= 1.2:

            score += 5

    # Range
    if not pd.isna(range20):

        if range20 <= 12:

            score += 10

        elif range20 <= 18:

            score += 7

    # Setup
    if setup == "RETEST + HOLD":

        score += 10

    elif setup == "FRESH BREAKOUT":

        score += 8

    elif setup == "BREAKOUT WATCH":

        score += 5

    return int(
        min(score, 100)
    )


# ============================================================
# ANALYZE STOCK
# ============================================================

def analyze_stock(
    symbol,
    stock_df,
    turnover_rank,
    turnover
):

    df = stock_df.copy()

    if len(df) < 70:
        return None

    df = add_indicators(
        df
    )

    required_indicators = [
        "EMA20",
        "EMA50",
        "RSI14",
        "ATR14",
        "Prev20High",
        "Prev20Low",
        "Range20Pct"
    ]

    df = df.dropna(
        subset=required_indicators
    ).copy()

    if len(df) < 30:
        return None

    today = df.iloc[-1]

    close = float(
        today["Close"]
    )

    if close <= 0:
        return None

    # --------------------------------------------------------
    # HARD REJECT
    # --------------------------------------------------------

    rsi = today["RSI14"]

    if (
        pd.isna(rsi)
        or
        rsi < RSI_REJECT
        or
        rsi >= RSI_HARD_REJECT
    ):

        return None

    if today["EMA20"] <= today["EMA50"]:
        return None

    if close <= today["EMA20"]:
        return None

    if today["Range20Pct"] > 18:
        return None

    # --------------------------------------------------------
    # SETUP
    # --------------------------------------------------------

    setup = None
    breakout_date = ""

    previous_breakout = (
        find_previous_breakout(
            df
        )
    )

    # --------------------------------------------------------
    # RETEST
    # --------------------------------------------------------

    if check_true_retest(
        df,
        previous_breakout
    ):

        setup = "RETEST + HOLD"

        breakout_date = (
            previous_breakout["date"]
            .strftime("%Y-%m-%d")
        )

    # --------------------------------------------------------
    # FRESH BREAKOUT
    # --------------------------------------------------------

    elif check_fresh_breakout(
        df
    ):

        setup = "FRESH BREAKOUT"

        breakout_date = (
            today["Date"]
            .strftime("%Y-%m-%d")
        )

    # --------------------------------------------------------
    # WATCH
    # --------------------------------------------------------

    elif check_breakout_watch(
        df
    ):

        setup = "BREAKOUT WATCH"

        breakout_date = ""

    else:

        return None

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = calculate_score(
        df,
        setup
    )

    if setup in [
        "RETEST + HOLD",
        "FRESH BREAKOUT"
    ]:

        if score < MIN_BUY_SCORE:
            return None

    else:

        if score < MIN_WATCH_SCORE:
            return None

    # --------------------------------------------------------
    # LEVELS
    # --------------------------------------------------------

    levels = calculate_trade_levels(
        df,
        setup
    )

    risk_pct = levels["Risk %"]

    if risk_pct > MAX_RISK_PCT:
        return None

    # --------------------------------------------------------
    # EXTENSION
    # --------------------------------------------------------

    breakout_level = float(
        today["Prev20High"]
    )

    extension_pct = (
        (
            close -
            breakout_level
        )
        /
        breakout_level
        *
        100
    )

    if setup in [
        "RETEST + HOLD",
        "FRESH BREAKOUT"
    ]:

        if extension_pct > MAX_BREAKOUT_EXTENSION_PCT:
            return None

    # --------------------------------------------------------
    # RESULT
    # --------------------------------------------------------

    return {

        "NSE Code":
            symbol,

        "Turnover Rank":
            int(turnover_rank),

        "Turnover":
            float(turnover),

        "Close":
            round(close, 2),

        "EMA20":
            round(today["EMA20"], 2),

        "EMA50":
            round(today["EMA50"], 2),

        "RSI14":
            round(today["RSI14"], 2),

        "Volume Ratio":
            round(today["VolumeRatio"], 2),

        "20-Day High":
            round(today["Prev20High"], 2),

        "Breakout Level":
            round(breakout_level, 2),

        "Entry":
            round(levels["Entry"], 2),

        "Stop Loss":
            round(levels["Stop Loss"], 2),

        "Target 1":
            round(levels["Target 1"], 2),

        "Target 2":
            round(levels["Target 2"], 2),

        "Risk %":
            round(risk_pct, 2),

        "Today Change %":
            round(today["TodayChangePct"], 2),

        "Setup":
            setup,

        "Strength Score":
            score,

        "20-Day Range %":
            round(today["Range20Pct"], 2),

        "ATR14":
            round(today["ATR14"], 2),

        "Breakout Date":
            breakout_date,

        "Chart":
            tradingview_url(symbol)
    }


# ============================================================
# SORT RESULTS
# ============================================================

def sort_final_results(results):

    if not results:
        return []

    df = pd.DataFrame(
        results
    )

    setup_priority = {

        "RETEST + HOLD": 1,

        "FRESH BREAKOUT": 2,

        "BREAKOUT WATCH": 3
    }

    df["_SetupPriority"] = (
        df["Setup"]
        .map(setup_priority)
        .fillna(99)
    )

    df = df.sort_values(
        [
            "_SetupPriority",
            "Strength Score",
            "Turnover Rank"
        ],
        ascending=[
            True,
            False,
            True
        ]
    )

    df = (
        df
        .drop(
            columns=[
                "_SetupPriority"
            ]
        )
        .head(
            MAX_FINAL_STOCKS
        )
        .reset_index(
            drop=True
        )
    )

    return df.to_dict(
        orient="records"
    )


# ============================================================
# WRITE FINAL SHEET
# ============================================================

def write_final_sheet(
    spreadsheet,
    results
):

    print(
        f"\nUpdating sheet: {FINAL_SHEET}"
    )

    try:

        worksheet = (
            spreadsheet
            .worksheet(
                FINAL_SHEET
            )
        )

    except Exception:

        print(
            "Final List sheet not found. "
            "Creating it."
        )

        worksheet = (
            spreadsheet
            .add_worksheet(
                title=FINAL_SHEET,
                rows=100,
                cols=30
            )
        )

    # ========================================================
    # EXACT 22 COLUMNS
    # ========================================================

    headers = [

        "NSE Code",
        "Turnover Rank",
        "Turnover",
        "Close",
        "EMA20",
        "EMA50",
        "RSI14",
        "Volume Ratio",
        "20-Day High",
        "Breakout Level",
        "Entry",
        "Stop Loss",
        "Target 1",
        "Target 2",
        "Risk %",
        "Today Change %",
        "Setup",
        "Strength Score",
        "20-Day Range %",
        "ATR14",
        "Breakout Date",
        "Chart"

    ]

    # ========================================================
    # CLEAR
    # ========================================================

    worksheet.clear()

    # ========================================================
    # VALUES
    # ========================================================

    values = [
        headers
    ]

    for result in results:

        row = []

        for header in headers:

            row.append(
                result.get(
                    header,
                    ""
                )
            )

        values.append(
            row
        )

    # ========================================================
    # RANGE
    # ========================================================

    def col_letter(number):

        result = ""

        while number:

            number, remainder = divmod(
                number - 1,
                26
            )

            result = (
                chr(
                    65 +
                    remainder
                )
                +
                result
            )

        return result

    end_row = len(values)

    end_col = len(headers)

    end_col_letter = (
        col_letter(
            end_col
        )
    )

    cell_range = (
        f"A1:{end_col_letter}{end_row}"
    )

    # ========================================================
    # WRITE
    # Compatible with current gspread
    # ========================================================

    worksheet.update(
        range_name=cell_range,
        values=values,
        value_input_option="USER_ENTERED"
    )

    print(
        f"Written range: {cell_range}"
    )

    print(
        f"Columns written: {end_col}"
    )

    print(
        f"Rows written: {len(results)}"
    )


# ============================================================
# PRINT FINAL RESULTS
# ============================================================

def print_final_results(results):

    print("\n")
    print("=" * 150)
    print(
        "V2.1.2 FINAL SWING SNIPER LIST"
    )
    print("=" * 150)

    if not results:

        print(
            "\nNo stocks qualified."
        )

        print(
            "The screener is intentionally strict."
        )

        return

    df = pd.DataFrame(
        results
    )

    display_cols = [

        "NSE Code",
        "Turnover Rank",
        "Close",
        "EMA20",
        "EMA50",
        "RSI14",
        "Volume Ratio",
        "20-Day High",
        "Entry",
        "Stop Loss",
        "Target 1",
        "Target 2",
        "Risk %",
        "Setup",
        "Strength Score",
        "20-Day Range %",
        "ATR14"

    ]

    print(
        df[
            display_cols
        ].to_string(
            index=False
        )
    )

    print("\n")
    print("=" * 150)

    print(
        f"FINAL STOCK COUNT: {len(df)}"
    )

    print("=" * 150)


# ============================================================
# VALIDATE
# ============================================================

def validate_results(results):

    print("\n")
    print("=" * 80)
    print("FINAL VALIDATION")
    print("=" * 80)

    if not results:

        print(
            "No results to validate."
        )

        return

    df = pd.DataFrame(
        results
    )

    duplicate_ranks = (
        df["Turnover Rank"]
        .duplicated()
        .sum()
    )

    bad_range = (
        df["20-Day Range %"] > 18
    ).sum()

    bad_risk = (
        df["Risk %"] > 5
    ).sum()

    buy_mask = df[
        "Setup"
    ].isin(
        [
            "RETEST + HOLD",
            "FRESH BREAKOUT"
        ]
    )

    buy_rows = df.loc[
        buy_mask
    ]

    if len(buy_rows) > 0:

        bad_buy_rsi = (
            (
                buy_rows["RSI14"] <
                RSI_BUY_MIN
            )
            |
            (
                buy_rows["RSI14"] >=
                RSI_BUY_MAX
            )
        ).sum()

    else:

        bad_buy_rsi = 0

    print(
        f"Duplicate turnover ranks : "
        f"{duplicate_ranks}"
    )

    print(
        f"Range > 18%              : "
        f"{bad_range}"
    )

    print(
        f"Risk > 5%                : "
        f"{bad_risk}"
    )

    print(
        f"Invalid BUY RSI          : "
        f"{bad_buy_rsi}"
    )

    print("\nSetup count:")

    print(
        df["Setup"]
        .value_counts()
        .to_string()
    )

    # --------------------------------------------------------
    # FINAL PASS / FAIL
    # --------------------------------------------------------

    if (
        duplicate_ranks == 0
        and
        bad_range == 0
        and
        bad_risk == 0
        and
        bad_buy_rsi == 0
    ):

        print(
            "\nVALIDATION: PASS"
        )

    else:

        print(
            "\nVALIDATION: FAIL"
        )

        raise ValueError(
            "Final validation failed."
        )

    print("=" * 80)


# ============================================================
# MAIN
# ============================================================

def run_screener():

    print("\n")
    print("=" * 80)
    print(
        "NIFTY 200 SWING SNIPER V2.1.2"
    )
    print("=" * 80)

    start_time = time.time()

    # --------------------------------------------------------
    # GOOGLE
    # --------------------------------------------------------

    spreadsheet = (
        connect_google_sheet()
    )

    # --------------------------------------------------------
    # READ
    # --------------------------------------------------------

    raw_df = (
        read_nifty200_sheet(
            spreadsheet
        )
    )

    # --------------------------------------------------------
    # PREPARE
    # --------------------------------------------------------

    history = (
        prepare_history(
            raw_df
        )
    )

    print(
        f"\nPrepared history rows: "
        f"{len(history)}"
    )

    # --------------------------------------------------------
    # TOP 200
    # --------------------------------------------------------

    top_symbols = (
        get_top_200_symbols(
            history
        )
    )

    rank_map = dict(
        zip(
            top_symbols["Symbol"],
            top_symbols["Turnover Rank"]
        )
    )

    turnover_map = dict(
        zip(
            top_symbols["Symbol"],
            top_symbols["Turnover"]
        )
    )

    print(
        f"\nRank map created: "
        f"{len(rank_map)} symbols"
    )

    # --------------------------------------------------------
    # ANALYZE
    # --------------------------------------------------------

    results = []

    symbols = list(
        top_symbols["Symbol"]
    )

    print(
        f"\nAnalyzing "
        f"{len(symbols)} stocks..."
    )

    for count, symbol in enumerate(
        symbols,
        start=1
    ):

        try:

            stock_df = history[
                history["Symbol"] ==
                symbol
            ].copy()

            stock_df = stock_df.sort_values(
                "Date"
            )

            if len(stock_df) > HISTORY_TRADING_DAYS:

                stock_df = (
                    stock_df
                    .tail(
                        HISTORY_TRADING_DAYS
                    )
                )

            result = analyze_stock(

                symbol=symbol,

                stock_df=stock_df,

                turnover_rank=
                    rank_map[symbol],

                turnover=
                    turnover_map[symbol]
            )

            if result is not None:

                results.append(
                    result
                )

                print(
                    f"[QUALIFY] "
                    f"{symbol:<15} "
                    f"Rank="
                    f"{result['Turnover Rank']:<3} "
                    f"RSI="
                    f"{result['RSI14']:<6} "
                    f"Score="
                    f"{result['Strength Score']:<3} "
                    f"{result['Setup']}"
                )

            if count % 25 == 0:

                print(
                    f"Processed "
                    f"{count}/"
                    f"{len(symbols)}"
                )

        except Exception as e:

            print(
                f"[ERROR] "
                f"{symbol}: {e}"
            )

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    results = (
        sort_final_results(
            results
        )
    )

    # --------------------------------------------------------
    # VALIDATE
    # --------------------------------------------------------

    validate_results(
        results
    )

    # --------------------------------------------------------
    # PRINT
    # --------------------------------------------------------

    print_final_results(
        results
    )

    # --------------------------------------------------------
    # WRITE
    # --------------------------------------------------------

    write_final_sheet(
        spreadsheet,
        results
    )

    elapsed = (
        time.time() -
        start_time
    )

    print("\n")
    print("=" * 80)

    print(
        "V2.1.2 COMPLETED"
    )

    print(
        f"Final stocks: "
        f"{len(results)}"
    )

    print(
        f"Time taken: "
        f"{elapsed:.1f} seconds"
    )

    print("=" * 80)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    run_screener()
