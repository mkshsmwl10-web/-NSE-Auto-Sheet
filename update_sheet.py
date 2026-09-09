import os
import io
import json
import zipfile
import time
import requests
import gspread
import pandas as pd
import numpy as np

from datetime import datetime, timedelta
from urllib.parse import quote
from oauth2client.service_account import ServiceAccountCredentials
# ============================================================
# NIFTY 200 SWING SNIPER V2.1.1
# ============================================================
#
# FULLY CORRECTED FINAL VERSION
#
# FINAL LIST:
#   1. RETEST + HOLD
#   2. FRESH BREAKOUT
#   3. BREAKOUT WATCH
#
# CORE FILTERS:
#   EMA20 > EMA50
#   Close > EMA20
#   RSI
#   Volume Ratio
#   20-Day Breakout
#   True Retest
#   Risk <= 5%
#   Previous 20-Day Range <= 18%
#   Extension <= 3%
#
# NO:
#   BB
#   MACD
#   SuperTrend
#   Intraday logic
#   Random candlestick patterns
#
# ============================================================

import io
import math
import time
import requests
import numpy as np
import pandas as pd
import gspread

from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials


# ============================================================
# CONFIG
# ============================================================

SPREADSHEET_ID = "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E"

NIFTY_SHEET = "NIFTY200"
FINAL_SHEET = "Final List"

TOP_STOCKS = 200
HISTORY_TRADING_DAYS = 120

# Breakout
BREAKOUT_LOOKBACK = 20

# EMA
EMA_FAST = 20
EMA_SLOW = 50

# RSI
RSI_LENGTH = 14

RSI_REJECT = 50
RSI_BUY_MIN = 55
RSI_BUY_MAX = 68
RSI_WATCH_MAX = 70
RSI_HARD_REJECT = 80

# Volume
VOLUME_LENGTH = 20
MIN_VOLUME_RATIO = 1.50

# Breakout extension
MAX_BREAKOUT_EXTENSION_PCT = 3.0

# Breakout Watch
WATCH_DISTANCE_PCT = 2.0

# Retest
RETEST_LOOKBACK_DAYS = 5
RETEST_MAX_ABOVE_PCT = 1.0
RETEST_MAX_BELOW_PCT = 3.0

# Risk
MAX_RISK_PCT = 5.0

# Targets
TARGET1_R = 1.5
TARGET2_R = 3.0

# Quality
MIN_BUY_SCORE = 70
MIN_WATCH_SCORE = 60

# Final list size
MAX_FINAL_STOCKS = 12


# ============================================================
# GOOGLE AUTH
# ============================================================

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]


# ============================================================
# HELPER
# ============================================================

def safe_float(x, default=np.nan):
    try:
        if x is None:
            return default

        if isinstance(x, str):
            x = (
                x.replace(",", "")
                 .replace("%", "")
                 .strip()
            )

        return float(x)

    except Exception:
        return default


def clean_symbol(symbol):
    if symbol is None:
        return ""

    return (
        str(symbol)
        .strip()
        .upper()
        .replace(".NS", "")
    )


def tradingview_url(symbol):

    symbol = clean_symbol(symbol)

    # TradingView URL-safe symbol
    symbol = symbol.replace("&", "%26")

    return (
        f'=HYPERLINK('
        f'"https://www.tradingview.com/chart/?symbol=NSE%3A{symbol}",'
        f'"Chart")'
    )


# ============================================================
# GOOGLE SHEETS CONNECTION
# ============================================================

def connect_google_sheet():

    print("\nConnecting to Google Sheets...")

    creds = ServiceAccountCredentials.from_json_keyfile_name(
        "credentials.json",
        SCOPES
    )

    client = gspread.authorize(creds)

    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    return spreadsheet


# ============================================================
# READ NIFTY200 SHEET
# ============================================================

def read_nifty200_sheet(spreadsheet):

    print(f"\nReading sheet: {NIFTY_SHEET}")

    worksheet = spreadsheet.worksheet(NIFTY_SHEET)

    records = worksheet.get_all_records()

    if not records:
        raise ValueError(
            f"{NIFTY_SHEET} sheet is empty."
        )

    df = pd.DataFrame(records)

    print(
        f"Rows loaded from {NIFTY_SHEET}: "
        f"{len(df)}"
    )

    return df


# ============================================================
# NORMALIZE COLUMN NAMES
# ============================================================

def normalize_columns(df):

    df = df.copy()

    df.columns = [
        str(c).strip()
        for c in df.columns
    ]

    rename_map = {}

    for col in df.columns:

        c = col.lower().replace(" ", "").replace("_", "")

        if c in ["symbol", "nsecode", "nse", "ticker"]:
            rename_map[col] = "Symbol"

        elif c in ["date", "tradingdate"]:
            rename_map[col] = "Date"

        elif c in ["open"]:
            rename_map[col] = "Open"

        elif c in ["high"]:
            rename_map[col] = "High"

        elif c in ["low"]:
            rename_map[col] = "Low"

        elif c in ["close", "ltp"]:
            rename_map[col] = "Close"

        elif c in [
            "turnover",
            "value",
            "tradedvalue",
            "totalturnover"
        ]:
            rename_map[col] = "Turnover"

        elif c in [
            "volume",
            "qty",
            "quantity",
            "tradedqty",
            "shares"
        ]:
            rename_map[col] = "Volume"

    df = df.rename(columns=rename_map)

    required = [
        "Symbol",
        "Date",
        "Open",
        "High",
        "Low",
        "Close"
    ]

    missing = [
        c for c in required
        if c not in df.columns
    ]

    if missing:
        raise ValueError(
            f"Missing required columns: {missing}"
        )

    return df


# ============================================================
# PREPARE HISTORY
# ============================================================

def prepare_history(df):

    df = normalize_columns(df)

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

    numeric_cols = [
        "Open",
        "High",
        "Low",
        "Close",
        "Turnover",
        "Volume"
    ]

    for col in numeric_cols:

        if col in df.columns:

            df[col] = (
                df[col]
                .map(safe_float)
            )

        else:

            df[col] = np.nan

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

    df = df.sort_values(
        ["Symbol", "Date"]
    )

    df = df.drop_duplicates(
        subset=["Symbol", "Date"],
        keep="last"
    )

    return df


# ============================================================
# EXCLUDE UNWANTED SYMBOLS
# ============================================================

def is_valid_symbol(symbol):

    symbol = clean_symbol(symbol)

    if not symbol:
        return False

    # Common index / ETF / non-equity exclusions
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
# TOP 200 BY TURNOVER
# ============================================================

def get_top_200_symbols(history):

    latest_date = history["Date"].max()

    latest = history[
        history["Date"] == latest_date
    ].copy()

    latest = latest[
        latest["Symbol"].map(is_valid_symbol)
    ].copy()

    latest["Turnover"] = pd.to_numeric(
        latest["Turnover"],
        errors="coerce"
    )

    latest = latest.dropna(
        subset=["Turnover"]
    )

    # One row per symbol
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

    # ========================================================
    # IMPORTANT:
    # Robust ranking.
    # This fixes the old 1,1,1 turnover rank bug.
    # ========================================================

    latest["Turnover Rank"] = (
        latest["Turnover"]
        .rank(
            method="first",
            ascending=False
        )
        .astype(int)
    )

    latest = (
        latest
        .sort_values("Turnover Rank")
        .head(TOP_STOCKS)
        .reset_index(drop=True)
    )

    # Re-number AFTER TOP 200 selection
    latest["Turnover Rank"] = (
        np.arange(1, len(latest) + 1)
    )

    # Safety check
    if not latest["Turnover Rank"].is_unique:
        raise ValueError(
            "ERROR: Turnover Rank is not unique."
        )

    print("\n================================================")
    print("TOP 200 TURNOVER CHECK")
    print("================================================")

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

    print("\nTop 10 by turnover:")

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

def calculate_rsi(close, length=14):

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

    rs = avg_gain / avg_loss.replace(
        0,
        np.nan
    )

    rsi = 100 - (
        100 / (1 + rs)
    )

    # If avg loss is zero, RSI is effectively 100
    rsi = rsi.where(
        avg_loss != 0,
        100
    )

    return rsi


# ============================================================
# ATR
# ============================================================

def calculate_atr(df, length=14):

    prev_close = df["Close"].shift(1)

    tr1 = (
        df["High"] -
        df["Low"]
    )

    tr2 = (
        df["High"] -
        prev_close
    ).abs()

    tr3 = (
        df["Low"] -
        prev_close
    ).abs()

    tr = pd.concat(
        [tr1, tr2, tr3],
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
        ATR_LENGTH
    )

    # --------------------------------------------------------
    # Previous 20 COMPLETED sessions
    #
    # IMPORTANT:
    # shift(1) means today's candle is NOT included.
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
    # Previous 20-day range
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
    # Volume ratio
    #
    # Previous 20-day average volume,
    # excluding today's volume.
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
    # EMA20 slope
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
    # Daily change
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

    today_idx = len(df) - 1

    start_idx = max(
        1,
        today_idx -
        RETEST_LOOKBACK_DAYS
    )

    # Search last 1-5 completed sessions
    for idx in range(
        start_idx,
        today_idx
    ):

        row = df.iloc[idx]

        close = row["Close"]
        prev_high = row["Prev20High"]
        volume_ratio = row["VolumeRatio"]
        rsi = row["RSI14"]

        if pd.isna(prev_high):
            continue

        if pd.isna(volume_ratio):
            continue

        if pd.isna(rsi):
            continue

        ema20 = row["EMA20"]
        ema50 = row["EMA50"]

        if pd.isna(ema20) or pd.isna(ema50):
            continue

        # Trend
        if ema20 <= ema50:
            continue

        # Breakout
        if close <= prev_high:
            continue

        # Volume confirmation
        if volume_ratio < MIN_VOLUME_RATIO:
            continue

        # RSI confirmation
        if not (
            RSI_BUY_MIN <= rsi < RSI_BUY_MAX
        ):
            continue

        # Extension at breakout should not be excessive
        extension = (
            (close - prev_high)
            /
            prev_high
            *
            100
        )

        if extension > MAX_BREAKOUT_EXTENSION_PCT:
            continue

        # Range filter
        range20 = row["Range20Pct"]

        if pd.isna(range20):
            continue

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

    level = breakout_info["level"]

    today_low = today["Low"]
    today_close = today["Close"]

    # Current low can move slightly above breakout level
    # or up to 3% below it.
    upper_level = (
        level *
        (1 + RETEST_MAX_ABOVE_PCT / 100)
    )

    lower_level = (
        level *
        (1 - RETEST_MAX_BELOW_PCT / 100)
    )

    touched_level = (
        today_low <= upper_level
        and
        today_low >= lower_level
    )

    if not touched_level:
        return False

    # Close must hold above breakout level
    if today_close <= level:
        return False

    # Current extension
    extension = (
        (today_close - level)
        /
        level
        *
        100
    )

    if extension > MAX_BREAKOUT_EXTENSION_PCT:
        return False

    # Current RSI must still be healthy
    rsi = today["RSI14"]

    if pd.isna(rsi):
        return False

    if not (
        RSI_BUY_MIN <= rsi < RSI_BUY_MAX
    ):
        return False

    # Trend must still hold
    if today["EMA20"] <= today["EMA50"]:
        return False

    if today["Close"] <= today["EMA20"]:
        return False

    # Range filter
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

    close = today["Close"]
    breakout_level = today["Prev20High"]

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
        today["VolumeRatio"] < MIN_VOLUME_RATIO
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
        (close - breakout_level)
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

    close = today["Close"]
    breakout_level = today["Prev20High"]

    if pd.isna(breakout_level):
        return False

    # Must still be below breakout
    if close >= breakout_level:
        return False

    # Distance from breakout
    distance_pct = (
        (breakout_level - close)
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
        RSI_BUY_MIN <= rsi <= RSI_WATCH_MAX
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
# CALCULATE TRADE LEVELS
# ============================================================

def calculate_trade_levels(
    df,
    setup
):

    today = df.iloc[-1]

    close = float(today["Close"])

    breakout_level = float(
        today["Prev20High"]
    )

    atr = float(today["ATR14"])

    recent_low = float(
        df["Low"]
        .tail(5)
        .min()
    )

    if not np.isfinite(atr) or atr <= 0:
        atr = close * 0.02

    # --------------------------------------------------------
    # ENTRY
    # --------------------------------------------------------

    if setup == "BREAKOUT WATCH":

        # Planned entry at breakout level
        entry = breakout_level

    else:

        entry = close

    # --------------------------------------------------------
    # STOP LOSS
    #
    # Use structural low / ATR.
    # Keep risk <= 5%.
    # --------------------------------------------------------

    structural_stop = (
        recent_low -
        0.25 * atr
    )

    atr_stop = (
        entry -
        1.0 * atr
    )

    stop = max(
        structural_stop,
        atr_stop
    )

    # Stop cannot be above entry
    if stop >= entry:

        stop = (
            entry -
            0.75 * atr
        )

    # Risk
    risk_pct = (
        (entry - stop)
        /
        entry
        *
        100
    )

    # If risk is too high, cap at 5%
    if risk_pct > MAX_RISK_PCT:

        stop = (
            entry *
            (1 - MAX_RISK_PCT / 100)
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

    # --------------------------------------------------------
    # EMA trend
    # --------------------------------------------------------

    if ema20 > ema50:
        score += 20

    # Close above EMA20
    if close > ema20:
        score += 15

    # EMA20 rising
    if (
        not pd.isna(ema_slope)
        and
        ema_slope > 0
    ):
        score += 10

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if not pd.isna(rsi):

        if 55 <= rsi < 68:
            score += 15

        elif 68 <= rsi <= 70:
            score += 8

    # --------------------------------------------------------
    # Volume
    # --------------------------------------------------------

    if not pd.isna(volume_ratio):

        if volume_ratio >= 2.0:
            score += 15

        elif volume_ratio >= 1.5:
            score += 10

        elif volume_ratio >= 1.2:
            score += 5

    # --------------------------------------------------------
    # Range quality
    # --------------------------------------------------------

    if not pd.isna(range20):

        if range20 <= 12:
            score += 10

        elif range20 <= 18:
            score += 7

    # --------------------------------------------------------
    # Setup bonus
    # --------------------------------------------------------

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
# ANALYZE ONE STOCK
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

    df = add_indicators(df)

    # Remove rows without required indicators
    df = df.dropna(
        subset=[
            "EMA20",
            "EMA50",
            "RSI14",
            "ATR14",
            "Prev20High",
            "Prev20Low",
            "Range20Pct"
        ]
    ).copy()

    if len(df) < 30:
        return None

    today = df.iloc[-1]

    close = float(today["Close"])

    # --------------------------------------------------------
    # Hard reject
    # --------------------------------------------------------

    if close <= 0:
        return None

    if (
        pd.isna(today["RSI14"])
        or
        today["RSI14"] < RSI_REJECT
        or
        today["RSI14"] >= RSI_HARD_REJECT
    ):
        return None

    if today["EMA20"] <= today["EMA50"]:
        return None

    if close <= today["EMA20"]:
        return None

    if today["Range20Pct"] > 18:
        return None

    # --------------------------------------------------------
    # SETUP DETECTION
    # Priority:
    #
    # 1. RETEST + HOLD
    # 2. FRESH BREAKOUT
    # 3. BREAKOUT WATCH
    # --------------------------------------------------------

    setup = None
    breakout_date = ""

    previous_breakout = find_previous_breakout(
        df
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

    elif check_fresh_breakout(df):

        setup = "FRESH BREAKOUT"

        breakout_date = (
            today["Date"]
            .strftime("%Y-%m-%d")
        )

    # --------------------------------------------------------
    # WATCH
    # --------------------------------------------------------

    elif check_breakout_watch(df):

        setup = "BREAKOUT WATCH"

        breakout_date = ""

    else:

        return None

    # --------------------------------------------------------
    # Score
    # --------------------------------------------------------

    score = calculate_score(
        df,
        setup
    )

    # Minimum score
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
    # Trade levels
    # --------------------------------------------------------

    levels = calculate_trade_levels(
        df,
        setup
    )

    risk_pct = levels["Risk %"]

    if risk_pct > MAX_RISK_PCT:
        return None

    # --------------------------------------------------------
    # Extension
    # --------------------------------------------------------

    breakout_level = float(
        today["Prev20High"]
    )

    extension_pct = (
        (close - breakout_level)
        /
        breakout_level
        *
        100
    )

    # Fresh / retest cannot be overextended
    if setup in [
        "RETEST + HOLD",
        "FRESH BREAKOUT"
    ]:

        if extension_pct > MAX_BREAKOUT_EXTENSION_PCT:
            return None

    # --------------------------------------------------------
    # Output
    # --------------------------------------------------------

    result = {

        "NSE Code": symbol,

        "Turnover Rank": int(
            turnover_rank
        ),

        "Turnover": float(
            turnover
        ),

        "Close": round(
            close,
            2
        ),

        "EMA20": round(
            today["EMA20"],
            2
        ),

        "EMA50": round(
            today["EMA50"],
            2
        ),

        "RSI14": round(
            today["RSI14"],
            2
        ),

        "Volume Ratio": round(
            today["VolumeRatio"],
            2
        ),

        "20-Day High": round(
            today["Prev20High"],
            2
        ),

        "Breakout Level": round(
            breakout_level,
            2
        ),

        "Entry": round(
            levels["Entry"],
            2
        ),

        "Stop Loss": round(
            levels["Stop Loss"],
            2
        ),

        "Target 1": round(
            levels["Target 1"],
            2
        ),

        "Target 2": round(
            levels["Target 2"],
            2
        ),

        "Risk %": round(
            risk_pct,
            2
        ),

        "Today Change %": round(
            today["TodayChangePct"],
            2
        ),

        "Setup": setup,

        "Strength Score": score,

        "20-Day Range %": round(
            today["Range20Pct"],
            2
        ),

        "ATR14": round(
            today["ATR14"],
            2
        ),

        "Breakout Date": breakout_date,

        "Chart": tradingview_url(
            symbol
        )
    }

    return result


# ============================================================
# SORT FINAL LIST
# ============================================================

def sort_final_results(results):

    if not results:
        return []

    df = pd.DataFrame(results)

    # --------------------------------------------------------
    # Setup priority
    # --------------------------------------------------------

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

    # Highest quality first
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
        .drop(columns=["_SetupPriority"])
        .head(MAX_FINAL_STOCKS)
        .reset_index(drop=True)
    )

    return df.to_dict(
        orient="records"
    )


# ============================================================
# WRITE FINAL LIST
# ============================================================

def write_final_sheet(
    spreadsheet,
    results
):

    print(
        f"\nUpdating sheet: {FINAL_SHEET}"
    )

    try:

        worksheet = spreadsheet.worksheet(
            FINAL_SHEET
        )

    except Exception:

        worksheet = spreadsheet.add_worksheet(
            title=FINAL_SHEET,
            rows=100,
            cols=30
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
    # CLEAR OLD DATA
    # ========================================================

    worksheet.clear()

    # ========================================================
    # PREPARE VALUES
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

        values.append(row)

    # ========================================================
    # WRITE EXACT RANGE
    # ========================================================

    end_row = len(values)
    end_col = len(headers)

    # Convert column number to letter
    def col_letter(n):

        result = ""

        while n:

            n, remainder = divmod(
                n - 1,
                26
            )

            result = (
                chr(65 + remainder)
                +
                result
            )

        return result

    end_col_letter = col_letter(
        end_col
    )

    cell_range = (
        f"A1:{end_col_letter}{end_row}"
    )

    worksheet.update(
        cell_range,
        values,
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
# PRINT FINAL TABLE
# ============================================================

def print_final_results(results):

    print("\n")
    print("=" * 140)
    print("V2.1.1 FINAL SWING SNIPER LIST")
    print("=" * 140)

    if not results:

        print(
            "\nNo stocks qualified."
        )

        print(
            "This is okay — the screener is "
            "intentionally strict."
        )

        return

    df = pd.DataFrame(results)

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
    print("=" * 140)

    print(
        f"FINAL STOCK COUNT: "
        f"{len(df)}"
    )

    print("=" * 140)


# ============================================================
# VALIDATE FINAL RESULTS
# ============================================================

def validate_results(results):

    if not results:
        return

    df = pd.DataFrame(results)

    print("\n")
    print("FINAL VALIDATION")
    print("-" * 80)

    # Turnover rank
    duplicate_ranks = (
        df["Turnover Rank"]
        .duplicated()
        .sum()
    )

    print(
        f"Duplicate turnover ranks : "
        f"{duplicate_ranks}"
    )

    # Range
    bad_range = (
        df["20-Day Range %"] > 18
    ).sum()

    print(
        f"Range > 18%              : "
        f"{bad_range}"
    )

    # Risk
    bad_risk = (
        df["Risk %"] > MAX_RISK_PCT
    ).sum()

    print(
        f"Risk > 5%                : "
        f"{bad_risk}"
    )

    # Buy RSI
    buy_mask = df["Setup"].isin(
        [
            "RETEST + HOLD",
            "FRESH BREAKOUT"
        ]
    )

    bad_buy_rsi = (
        (
            df.loc[
                buy_mask,
                "RSI14"
            ] < RSI_BUY_MIN
        )
        |
        (
            df.loc[
                buy_mask,
                "RSI14"
            ] >= RSI_BUY_MAX
        )
    ).sum()

    print(
        f"Invalid BUY RSI          : "
        f"{bad_buy_rsi}"
    )

    # Setup count
    print("\nSetup count:")

    print(
        df["Setup"]
        .value_counts()
        .to_string()
    )

    print("-" * 80)


# ============================================================
# MAIN SCREENER
# ============================================================

def run_screener():

    print("\n")
    print("=" * 80)
    print("NIFTY 200 SWING SNIPER V2.1.1")
    print("=" * 80)

    start_time = time.time()

    # --------------------------------------------------------
    # Google
    # --------------------------------------------------------

    spreadsheet = connect_google_sheet()

    # --------------------------------------------------------
    # Read data
    # --------------------------------------------------------

    raw_df = read_nifty200_sheet(
        spreadsheet
    )

    # --------------------------------------------------------
    # Prepare
    # --------------------------------------------------------

    history = prepare_history(
        raw_df
    )

    print(
        f"\nPrepared history rows: "
        f"{len(history)}"
    )

    # --------------------------------------------------------
    # Top 200
    # --------------------------------------------------------

    top_symbols = get_top_200_symbols(
        history
    )

    # --------------------------------------------------------
    # Rank map
    #
    # IMPORTANT:
    # We create a direct dictionary.
    # This prevents the old rank=1 mapping issue.
    # --------------------------------------------------------

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
    # Analyze
    # --------------------------------------------------------

    results = []

    symbols = list(
        top_symbols["Symbol"]
    )

    print(
        f"\nAnalyzing {len(symbols)} stocks..."
    )

    for count, symbol in enumerate(
        symbols,
        start=1
    ):

        try:

            stock_df = history[
                history["Symbol"] == symbol
            ].copy()

            stock_df = stock_df.sort_values(
                "Date"
            )

            # Keep enough history
            if len(stock_df) > HISTORY_TRADING_DAYS:
                stock_df = stock_df.tail(
                    HISTORY_TRADING_DAYS
                )

            result = analyze_stock(

                symbol=symbol,

                stock_df=stock_df,

                turnover_rank=rank_map[symbol],

                turnover=turnover_map[symbol]
            )

            if result is not None:

                results.append(result)

                print(
                    f"[QUALIFY] "
                    f"{symbol:<15} "
                    f"Rank={result['Turnover Rank']:<3} "
                    f"RSI={result['RSI14']:<6} "
                    f"Score={result['Strength Score']:<3} "
                    f"{result['Setup']}"
                )

        except Exception as e:

            print(
                f"[ERROR] "
                f"{symbol}: {e}"
            )

    # --------------------------------------------------------
    # Sort + Limit
    # --------------------------------------------------------

    results = sort_final_results(
        results
    )

    # --------------------------------------------------------
    # Validate
    # --------------------------------------------------------

    validate_results(
        results
    )

    # --------------------------------------------------------
    # Print
    # --------------------------------------------------------

    print_final_results(
        results
    )

    # --------------------------------------------------------
    # Write Google Sheet
    # --------------------------------------------------------

    write_final_sheet(
        spreadsheet,
        results
    )

    # --------------------------------------------------------
    # Finish
    # --------------------------------------------------------

    elapsed = (
        time.time() -
        start_time
    )

    print("\n")
    print("=" * 80)

    print(
        f"V2.1.1 COMPLETED"
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
