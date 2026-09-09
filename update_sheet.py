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
# NIFTY 200 SWING SNIPER V2.1
# ============================================================
#
# PURPOSE:
#   High-quality DAILY swing breakout / retest screener
#
# FINAL LIST PRIORITY:
#   1. RETEST + HOLD
#   2. FRESH BREAKOUT
#   3. BREAKOUT WATCH
#
# V2.1 HARD FILTERS:
#   - EMA20 > EMA50
#   - Close > EMA20
#   - RSI BUY: 55 to 68
#   - RSI 68 to 70 = WATCH / NO CHASE
#   - Volume >= 1.5x average for actionable BUY setups
#   - 20-day breakout
#   - Genuine retest only
#   - Risk <= 5%
#   - 20-day range <= 18%
#   - Breakout extension <= 3%
#   - A-grade BUY score >= 70
#
# IMPORTANT:
#   20-Day High = previous 20 COMPLETED sessions
#   Today's candle is NOT included in 20-Day High.
#
# Google Sheets:
#   Spreadsheet ID = configured below
#   Sheets:
#       NIFTY200
#       Final List
#
# ============================================================


import os
import io
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
# CONFIGURATION
# ============================================================

SPREADSHEET_ID = "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E"

NIFTY_SHEET = "NIFTY200"
FINAL_SHEET = "Final List"

TOP_STOCKS = 200

# Historical data
HISTORY_TRADING_DAYS = 100

# Indicators
BREAKOUT_LOOKBACK = 20
EMA_FAST = 20
EMA_SLOW = 50
RSI_LENGTH = 14
ATR_LENGTH = 14
VOLUME_LENGTH = 20

# Volume filter
MIN_VOLUME_RATIO = 1.50

# RSI
RSI_REJECT = 50
RSI_BUY_MIN = 55
RSI_BUY_MAX = 68
RSI_WATCH_MAX = 70
RSI_HARD_REJECT = 80

# Breakout extension
MAX_BREAKOUT_EXTENSION_PCT = 3.0

# Watch distance below breakout
WATCH_DISTANCE_PCT = 2.0

# Retest tolerance
RETEST_MAX_ABOVE_PCT = 1.0
RETEST_MAX_BELOW_PCT = 3.0

# Risk
MAX_RISK_PCT = 5.0

# Targets
TARGET1_R = 1.5
TARGET2_R = 3.0

# Retest can happen within last 5 sessions
RETEST_LOOKBACK_DAYS = 5

# Final list
MAX_FINAL_STOCKS = 12

# Minimum score for actionable BUY
MIN_BUY_SCORE = 70

# Minimum score for WATCH
MIN_WATCH_SCORE = 60


# ============================================================
# NSE REQUEST SETTINGS
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


# ============================================================
# GOOGLE AUTH
# ============================================================

def get_google_client():

    possible_files = [
        "credentials.json",
        "service_account.json",
        "google_credentials.json",
    ]

    credential_file = None

    for f in possible_files:
        if os.path.exists(f):
            credential_file = f
            break

    if credential_file is None:
        raise FileNotFoundError(
            "Google credentials JSON file not found. "
            "Put credentials.json in the same folder as this script."
        )

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]

    creds = ServiceAccountCredentials.from_json_keyfile_name(
        credential_file,
        scope
    )

    return gspread.authorize(creds)


# ============================================================
# NSE BHAVCOPY URL
# ============================================================

def get_bhavcopy_url(date_obj):

    date_str = date_obj.strftime("%Y%m%d")

    return (
        "https://nsearchives.nseindia.com/content/cm/"
        f"BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv.zip"
    )


# ============================================================
# DOWNLOAD BHAVCOPY
# ============================================================

def fetch_bhavcopy(date_obj):

    url = get_bhavcopy_url(date_obj)

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20
        )

        if response.status_code != 200:
            return None

        if len(response.content) < 1000:
            return None

        z = zipfile.ZipFile(io.BytesIO(response.content))

        csv_files = [
            x for x in z.namelist()
            if x.lower().endswith(".csv")
        ]

        if not csv_files:
            return None

        with z.open(csv_files[0]) as f:
            df = pd.read_csv(f)

        return df

    except Exception as e:

        print(
            f"Bhavcopy failed "
            f"{date_obj.strftime('%Y-%m-%d')}: {e}"
        )

        return None


# ============================================================
# COLUMN FINDER
# ============================================================

def find_column(df, candidates):

    normalized = {
        str(c).strip().upper(): c
        for c in df.columns
    }

    for candidate in candidates:

        key = candidate.strip().upper()

        if key in normalized:
            return normalized[key]

    return None


# ============================================================
# NORMALIZE BHAVCOPY
# ============================================================

def normalize_bhavcopy(df):

    symbol_col = find_column(
        df,
        [
            "TckrSymb",
            "SYMBOL",
            "Symbol"
        ]
    )

    open_col = find_column(
        df,
        [
            "OpnPric",
            "OPEN",
            "Open"
        ]
    )

    high_col = find_column(
        df,
        [
            "HghPric",
            "HIGH",
            "High"
        ]
    )

    low_col = find_column(
        df,
        [
            "LwPric",
            "LOW",
            "Low"
        ]
    )

    close_col = find_column(
        df,
        [
            "ClsPric",
            "CLOSE",
            "Close"
        ]
    )

    turnover_col = find_column(
        df,
        [
            "TtlTrfVal",
            "TOTTRDVAL",
            "Turnover",
            "TURNOVER"
        ]
    )

    volume_col = find_column(
        df,
        [
            "TtlTradgVol",
            "TOTTRDQTY",
            "TotalTradedQuantity",
            "TOTTRDQTY"
        ]
    )

    series_col = find_column(
        df,
        [
            "SctySrs",
            "SERIES",
            "Series"
        ]
    )

    required = [
        symbol_col,
        open_col,
        high_col,
        low_col,
        close_col,
        turnover_col,
        volume_col
    ]

    if any(x is None for x in required):

        print("Could not identify required columns.")

        print("Available columns:")
        print(list(df.columns))

        return None

    out = pd.DataFrame()

    out["Symbol"] = (
        df[symbol_col]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    out["Open"] = pd.to_numeric(
        df[open_col],
        errors="coerce"
    )

    out["High"] = pd.to_numeric(
        df[high_col],
        errors="coerce"
    )

    out["Low"] = pd.to_numeric(
        df[low_col],
        errors="coerce"
    )

    out["Close"] = pd.to_numeric(
        df[close_col],
        errors="coerce"
    )

    out["Turnover"] = pd.to_numeric(
        df[turnover_col],
        errors="coerce"
    )

    # IMPORTANT:
    # Do NOT use turnover as volume.
    out["Volume"] = pd.to_numeric(
        df[volume_col],
        errors="coerce"
    )

    if series_col is not None:

        out["Series"] = (
            df[series_col]
            .astype(str)
            .str.upper()
            .str.strip()
        )

        out = out[
            out["Series"].isin(["EQ", "BE"])
        ]

    # Remove ETFs / index products
    exclude_pattern = (
        r"BEES|ETF|GOLD|LIQUID|SILVER|INDEX"
    )

    out = out[
        ~out["Symbol"].str.contains(
            exclude_pattern,
            regex=True,
            na=False
        )
    ]

    out = out.dropna(
        subset=[
            "Symbol",
            "Open",
            "High",
            "Low",
            "Close",
            "Turnover",
            "Volume"
        ]
    )

    out = out[
        (out["Close"] > 0) &
        (out["High"] > 0) &
        (out["Low"] > 0) &
        (out["Volume"] > 0)
    ]

    return out


# ============================================================
# GET HISTORICAL MARKET DATA
# ============================================================

def get_market_history():

    frames = []

    current_date = datetime.now().date()

    days_checked = 0

    while len(frames) < HISTORY_TRADING_DAYS:

        date_obj = current_date - timedelta(
            days=days_checked
        )

        days_checked += 1

        if days_checked > 180:

            break

        print(
            "Downloading:",
            date_obj.strftime("%Y-%m-%d")
        )

        raw = fetch_bhavcopy(date_obj)

        if raw is None:

            time.sleep(0.15)

            continue

        df = normalize_bhavcopy(raw)

        if df is None or df.empty:

            continue

        df["Date"] = pd.Timestamp(date_obj)

        frames.append(df)

        print(
            "  OK | rows:",
            len(df)
        )

        time.sleep(0.20)

    if not frames:

        raise RuntimeError(
            "No NSE historical data downloaded."
        )

    history = pd.concat(
        frames,
        ignore_index=True
    )

    history = history.sort_values(
        ["Symbol", "Date"]
    )

    return history


# ============================================================
# CALCULATE RSI
# ============================================================

def calculate_rsi(series, length=14):

    delta = series.diff()

    gain = delta.clip(lower=0)

    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / length,
        adjust=False,
        min_periods=length
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / length,
        adjust=False,
        min_periods=length
    ).mean()

    rs = avg_gain / avg_loss.replace(
        0,
        np.nan
    )

    rsi = 100 - (
        100 / (1 + rs)
    )

    return rsi


# ============================================================
# CALCULATE ATR
# ============================================================

def calculate_atr(df, length=14):

    previous_close = df["Close"].shift(1)

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

    true_range = pd.concat(
        [
            tr1,
            tr2,
            tr3
        ],
        axis=1
    ).max(axis=1)

    atr = true_range.ewm(
        alpha=1 / length,
        adjust=False,
        min_periods=length
    ).mean()

    return atr


# ============================================================
# INDICATORS
# ============================================================

def add_indicators(group):

    group = group.sort_values(
        "Date"
    ).copy()

    close = group["Close"]

    group["EMA20"] = close.ewm(
        span=EMA_FAST,
        adjust=False
    ).mean()

    group["EMA50"] = close.ewm(
        span=EMA_SLOW,
        adjust=False
    ).mean()

    group["RSI14"] = calculate_rsi(
        close,
        RSI_LENGTH
    )

    group["ATR14"] = calculate_atr(
        group,
        ATR_LENGTH
    )

    group["VolumeAvg20"] = (
        group["Volume"]
        .rolling(VOLUME_LENGTH)
        .mean()
        .shift(1)
    )

    group["VolumeRatio"] = (
        group["Volume"] /
        group["VolumeAvg20"]
    )

    # IMPORTANT:
    # Previous 20 COMPLETED sessions.
    # Today's high is NOT included.
    group["Prev20High"] = (
        group["High"]
        .rolling(BREAKOUT_LOOKBACK)
        .max()
        .shift(1)
    )

    group["Prev20Low"] = (
        group["Low"]
        .rolling(BREAKOUT_LOOKBACK)
        .min()
        .shift(1)
    )

    group["Range20High"] = (
        group["High"]
        .rolling(BREAKOUT_LOOKBACK)
        .max()
    )

    group["Range20Low"] = (
        group["Low"]
        .rolling(BREAKOUT_LOOKBACK)
        .min()
    )

    group["Range20Pct"] = (
        (
            group["Range20High"] -
            group["Range20Low"]
        )
        /
        group["Range20Low"]
        * 100
    )

    group["EMA20SlopePct"] = (
        (
            group["EMA20"] -
            group["EMA20"].shift(5)
        )
        /
        group["EMA20"].shift(5)
        * 100
    )

    group["DailyChangePct"] = (
        group["Close"].pct_change() * 100
    )

    return group


# ============================================================
# TRADINGVIEW URL
# ============================================================

def tradingview_formula(symbol):

    chart_symbol = quote(
        f"NSE:{symbol}",
        safe=""
    )

    url = (
        "https://www.tradingview.com/chart/"
        f"?symbol={chart_symbol}&interval=D"
    )

    return (
        '=HYPERLINK("'
        + url
        + '","Daily Chart")'
    )


# ============================================================
# TRUE RETEST DETECTION
# ============================================================

def find_retest(group):

    group = group.sort_values(
        "Date"
    ).reset_index(drop=True)

    current_idx = len(group) - 1

    if current_idx < RETEST_LOOKBACK_DAYS + BREAKOUT_LOOKBACK:
        return None

    current = group.iloc[current_idx]

    # Current trend must still be healthy
    if not (
        current["EMA20"] >
        current["EMA50"]
    ):
        return None

    if not (
        current["Close"] >
        current["EMA20"]
    ):
        return None

    if pd.isna(current["RSI14"]):
        return None

    # Do not classify 68+ RSI as BUY
    if not (
        RSI_BUY_MIN <=
        current["RSI14"] <
        RSI_BUY_MAX
    ):
        return None

    if pd.isna(current["Range20Pct"]):
        return None

    if current["Range20Pct"] > 18:
        return None

    # Search previous 1-5 sessions for a genuine breakout
    start_idx = max(
        BREAKOUT_LOOKBACK,
        current_idx - RETEST_LOOKBACK_DAYS
    )

    for idx in range(
        current_idx - 1,
        start_idx - 1,
        -1
    ):

        row = group.iloc[idx]

        if pd.isna(row["Prev20High"]):
            continue

        breakout_level = row["Prev20High"]

        # Breakout candle conditions
        breakout_close = row["Close"]

        breakout_extension = (
            (
                breakout_close -
                breakout_level
            )
            /
            breakout_level
            * 100
        )

        if breakout_close <= breakout_level:
            continue

        if breakout_extension > MAX_BREAKOUT_EXTENSION_PCT:
            continue

        if row["EMA20"] <= row["EMA50"]:
            continue

        if row["RSI14"] < RSI_BUY_MIN:
            continue

        if row["RSI14"] >= RSI_BUY_MAX:
            continue

        if row["VolumeRatio"] < MIN_VOLUME_RATIO:
            continue

        # Now test whether current candle retested
        # the old breakout level.
        current_low = current["Low"]
        current_close = current["Close"]

        max_retest_price = (
            breakout_level *
            (
                1 +
                RETEST_MAX_ABOVE_PCT / 100
            )
        )

        min_retest_price = (
            breakout_level *
            (
                1 -
                RETEST_MAX_BELOW_PCT / 100
            )
        )

        touched_level = (
            current_low <=
            max_retest_price
        )

        did_not_fail_deeply = (
            current_low >=
            min_retest_price
        )

        held_level = (
            current_close >
            breakout_level
        )

        not_chasing = (
            current_close <=
            breakout_level *
            (
                1 +
                MAX_BREAKOUT_EXTENSION_PCT / 100
            )
        )

        if (
            touched_level and
            did_not_fail_deeply and
            held_level and
            not_chasing
        ):

            return {
                "breakout_level": breakout_level,
                "breakout_date": row["Date"],
                "setup": "RETEST + HOLD"
            }

    return None


# ============================================================
# FRESH BREAKOUT
# ============================================================

def check_fresh_breakout(row):

    if pd.isna(row["Prev20High"]):
        return False

    if pd.isna(row["EMA20"]):
        return False

    if pd.isna(row["EMA50"]):
        return False

    if pd.isna(row["RSI14"]):
        return False

    if pd.isna(row["VolumeRatio"]):
        return False

    if pd.isna(row["Range20Pct"]):
        return False

    breakout_level = row["Prev20High"]

    close = row["Close"]

    extension = (
        (
            close -
            breakout_level
        )
        /
        breakout_level
        * 100
    )

    conditions = [

        # Trend
        row["EMA20"] > row["EMA50"],

        # Price above EMA20
        close > row["EMA20"],

        # Actual breakout
        close > breakout_level,

        # RSI BUY zone
        RSI_BUY_MIN <=
        row["RSI14"] <
        RSI_BUY_MAX,

        # Volume confirmation
        row["VolumeRatio"] >=
        MIN_VOLUME_RATIO,

        # Not excessively extended
        extension <=
        MAX_BREAKOUT_EXTENSION_PCT,

        # Avoid huge range stocks
        row["Range20Pct"] <= 18,
    ]

    return all(conditions)


# ============================================================
# BREAKOUT WATCH
# ============================================================

def check_breakout_watch(row):

    if pd.isna(row["Prev20High"]):
        return False

    if pd.isna(row["EMA20"]):
        return False

    if pd.isna(row["EMA50"]):
        return False

    if pd.isna(row["RSI14"]):
        return False

    if pd.isna(row["Range20Pct"]):
        return False

    breakout_level = row["Prev20High"]

    close = row["Close"]

    distance_pct = (
        (
            breakout_level -
            close
        )
        /
        breakout_level
        * 100
    )

    conditions = [

        # Trend
        row["EMA20"] > row["EMA50"],

        # Price above EMA20
        close > row["EMA20"],

        # Still below breakout
        close < breakout_level,

        # Maximum 2% below breakout
        distance_pct <=
        WATCH_DISTANCE_PCT,

        # Don't show extremely weak RSI
        row["RSI14"] >= RSI_REJECT,

        # RSI up to 70
        row["RSI14"] <= RSI_WATCH_MAX,

        # Range filter
        row["Range20Pct"] <= 18,
    ]

    return all(conditions)


# ============================================================
# SCORE
# ============================================================

def calculate_score(row, setup):

    score = 0

    # --------------------------------------------------------
    # TREND
    # --------------------------------------------------------

    if row["EMA20"] > row["EMA50"]:
        score += 20

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    if row["Close"] > row["EMA20"]:
        score += 10

    # --------------------------------------------------------
    # EMA20 SLOPE
    # --------------------------------------------------------

    slope = row["EMA20SlopePct"]

    if pd.notna(slope):

        if slope >= 1.0:
            score += 10

        elif slope > 0:
            score += 5

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    rsi = row["RSI14"]

    if pd.notna(rsi):

        if 55 <= rsi < 65:
            score += 15

        elif 65 <= rsi < 68:
            score += 12

        elif 68 <= rsi <= 70:
            score += 5

        elif 50 <= rsi < 55:
            score += 5

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    volume_ratio = row["VolumeRatio"]

    if pd.notna(volume_ratio):

        if volume_ratio >= 2.0:
            score += 20

        elif volume_ratio >= 1.5:
            score += 15

        elif volume_ratio >= 1.2:
            score += 10

    # --------------------------------------------------------
    # SETUP QUALITY
    # --------------------------------------------------------

    if setup == "RETEST + HOLD":
        score += 20

    elif setup == "FRESH BREAKOUT":
        score += 15

    elif setup == "BREAKOUT WATCH":
        score += 5

    # --------------------------------------------------------
    # RANGE
    # --------------------------------------------------------

    if pd.notna(row["Range20Pct"]):

        if row["Range20Pct"] <= 12:
            score += 5

        elif row["Range20Pct"] <= 18:
            score += 2

    return int(score)


# ============================================================
# TRADE LEVELS
# ============================================================

def calculate_trade_levels(
    row,
    setup,
    breakout_level
):

    entry = float(row["Close"])

    atr = float(row["ATR14"])

    if pd.isna(atr) or atr <= 0:
        return None

    # Recent 5-day structure
    recent_low = (
        row["_Recent5Low"]
    )

    structure_stop = (
        recent_low -
        0.25 * atr
    )

    # Breakout-based stop
    breakout_stop = (
        breakout_level -
        0.50 * atr
    )

    # Choose the tighter but valid structure stop
    possible_stops = [
        structure_stop,
        breakout_stop
    ]

    valid_stops = [
        x for x in possible_stops
        if x < entry
    ]

    if not valid_stops:
        return None

    # Higher stop = lower risk
    stop_loss = max(valid_stops)

    risk_amount = (
        entry -
        stop_loss
    )

    if risk_amount <= 0:
        return None

    risk_pct = (
        risk_amount /
        entry *
        100
    )

    # Hard risk filter
    if risk_pct > MAX_RISK_PCT:
        return None

    target1 = (
        entry +
        risk_amount *
        TARGET1_R
    )

    target2 = (
        entry +
        risk_amount *
        TARGET2_R
    )

    return {
        "Entry": entry,
        "Stop Loss": stop_loss,
        "Target 1": target1,
        "Target 2": target2,
        "Risk %": risk_pct
    }


# ============================================================
# ANALYZE STOCK
# ============================================================

def analyze_stock(group):

    group = add_indicators(group)

    if len(group) < 60:
        return None

    group = group.reset_index(
        drop=True
    )

    # Recent 5-day low
    group["_Recent5Low"] = (
        group["Low"]
        .rolling(5)
        .min()
    )

    row = group.iloc[-1]

    required_values = [
        row["Close"],
        row["EMA20"],
        row["EMA50"],
        row["RSI14"],
        row["ATR14"],
        row["VolumeRatio"],
        row["Prev20High"],
        row["Range20Pct"],
        row["_Recent5Low"]
    ]

    if any(
        pd.isna(x)
        for x in required_values
    ):
        return None

    setup = None

    breakout_level = None

    breakout_date = None

    # ========================================================
    # PRIORITY 1: TRUE RETEST + HOLD
    # ========================================================

    retest = find_retest(group)

    if retest is not None:

        setup = retest["setup"]

        breakout_level = (
            retest["breakout_level"]
        )

        breakout_date = (
            retest["breakout_date"]
        )

    # ========================================================
    # PRIORITY 2: FRESH BREAKOUT
    # ========================================================

    elif check_fresh_breakout(row):

        setup = "FRESH BREAKOUT"

        breakout_level = (
            row["Prev20High"]
        )

        breakout_date = (
            row["Date"]
        )

    # ========================================================
    # PRIORITY 3: WATCH
    # ========================================================

    elif check_breakout_watch(row):

        setup = "BREAKOUT WATCH"

        breakout_level = (
            row["Prev20High"]
        )

        breakout_date = None

    else:

        return None

    # ========================================================
    # EXTENSION
    # ========================================================

    extension_pct = (
        (
            row["Close"] -
            breakout_level
        )
        /
        breakout_level
        * 100
    )

    # Fresh/retest cannot be too extended
    if setup != "BREAKOUT WATCH":

        if extension_pct > MAX_BREAKOUT_EXTENSION_PCT:

            return None

    # ========================================================
    # SCORE
    # ========================================================

    score = calculate_score(
        row,
        setup
    )

    # ========================================================
    # SCORE FILTER
    # ========================================================

    if setup != "BREAKOUT WATCH":

        if score < MIN_BUY_SCORE:
            return None

    else:

        if score < MIN_WATCH_SCORE:
            return None

    # ========================================================
    # TRADE LEVELS
    # ========================================================

    trade = calculate_trade_levels(
        row,
        setup,
        breakout_level
    )

    if trade is None:

        return None

    # ========================================================
    # FINAL RESULT
    # ========================================================

    result = {

        "Symbol": row["Symbol"],

        "Date": row["Date"],

        "Close": float(row["Close"]),

        "EMA20": float(row["EMA20"]),

        "EMA50": float(row["EMA50"]),

        "RSI14": float(row["RSI14"]),

        "VolumeRatio": float(
            row["VolumeRatio"]
        ),

        "20-Day High": float(
            row["Prev20High"]
        ),

        "Breakout Level": float(
            breakout_level
        ),

        "Range20Pct": float(
            row["Range20Pct"]
        ),

        "ATR14": float(
            row["ATR14"]
        ),

        "TodayChangePct": float(
            row["DailyChangePct"]
        ),

        "Setup": setup,

        "Strength Score": int(
            score
        ),

        "Breakout Date": (
            breakout_date
            if breakout_date is not None
            else ""
        ),

        "Turnover": float(
            row["_Turnover"]
        ),

    }

    result.update(trade)

    return result


# ============================================================
# GET TOP 200 BY LATEST TURNOVER
# ============================================================

def get_top_200_symbols(history):

    latest_date = history["Date"].max()

    latest = history[
        history["Date"] ==
        latest_date
    ].copy()

    latest = latest.sort_values(
        "Turnover",
        ascending=False
    )

    latest = latest.drop_duplicates(
        subset=["Symbol"]
    )

    latest = latest.head(
        TOP_STOCKS
    )

    latest["Turnover Rank"] = (
        np.arange(1, len(latest) + 1)
    )

    return latest[
        [
            "Symbol",
            "Turnover",
            "Turnover Rank"
        ]
    ]


# ============================================================
# PREPARE HISTORICAL DATA
# ============================================================

def prepare_history(history, top_symbols):

    symbols = set(
        top_symbols["Symbol"]
    )

    history = history[
        history["Symbol"].isin(symbols)
    ].copy()

    turnover_map = dict(
        zip(
            top_symbols["Symbol"],
            top_symbols["Turnover"]
        )
    )

    rank_map = dict(
        zip(
            top_symbols["Symbol"],
            top_symbols["Turnover Rank"]
        )
    )

    history["_Turnover"] = (
        history["Symbol"]
        .map(turnover_map)
    )

    history["_TurnoverRank"] = (
        history["Symbol"]
        .map(rank_map)
    )

    return history


# ============================================================
# RUN SCREENER
# ============================================================

def run_screener(history):

    top_symbols = get_top_200_symbols(
        history
    )

    history = prepare_history(
        history,
        top_symbols
    )

    results = []

    total = len(top_symbols)

    print("")
    print(
        "Analyzing Top",
        total,
        "stocks..."
    )
    print("")

    for count, symbol in enumerate(
        top_symbols["Symbol"],
        start=1
    ):

        print(
            f"[{count}/{total}] {symbol}"
        )

        group = history[
            history["Symbol"] ==
            symbol
        ].copy()

        if group.empty:
            continue

        result = analyze_stock(
            group
        )

        if result is not None:

            result["Turnover Rank"] = int(
                top_symbols.loc[
                    top_symbols["Symbol"] == symbol,
                    "Turnover Rank"
                ].iloc[0]
            )

            results.append(result)

    if not results:

        return pd.DataFrame()

    df = pd.DataFrame(
        results
    )

    # ========================================================
    # SETUP PRIORITY
    # ========================================================

    priority_map = {
        "RETEST + HOLD": 1,
        "FRESH BREAKOUT": 2,
        "BREAKOUT WATCH": 3
    }

    df["_Priority"] = (
        df["Setup"]
        .map(priority_map)
        .fillna(99)
    )

    # ========================================================
    # SORT
    # ========================================================

    df = df.sort_values(
        [
            "_Priority",
            "Strength Score",
            "Turnover Rank"
        ],
        ascending=[
            True,
            False,
            True
        ]
    )

    # ========================================================
    # MAX FINAL STOCKS
    # ========================================================

    df = df.head(
        MAX_FINAL_STOCKS
    ).copy()

    return df


# ============================================================
# FORMAT VALUE
# ============================================================

def fmt(value, decimals=2):

    if value is None:
        return ""

    if pd.isna(value):
        return ""

    try:
        return round(
            float(value),
            decimals
        )

    except Exception:
        return value


# ============================================================
# BUILD NIFTY200 SHEET
# ============================================================

def build_nifty200_sheet(top_symbols):

    rows = []

    for _, row in top_symbols.iterrows():

        rows.append(
            [
                row["Symbol"],
                int(row["Turnover Rank"]),
                fmt(row["Turnover"], 0)
            ]
        )

    return rows


# ============================================================
# BUILD FINAL SHEET
# ============================================================

def build_final_sheet(df):

    # EXACTLY 22 COLUMNS
    #
    # A  NSE Code
    # B  Turnover Rank
    # C  Turnover
    # D  Close
    # E  EMA20
    # F  EMA50
    # G  RSI14
    # H  Volume Ratio
    # I  20-Day High
    # J  Breakout Level
    # K  Entry
    # L  Stop Loss
    # M  Target 1
    # N  Target 2
    # O  Risk %
    # P  Today Change %
    # Q  Setup
    # R  Strength Score
    # S  20-Day Range %
    # T  ATR14
    # U  Breakout Date
    # V  Chart

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

    rows = [
        headers
    ]

    for _, row in df.iterrows():

        symbol = row["Symbol"]

        rows.append(
            [
                symbol,

                int(
                    row["Turnover Rank"]
                ),

                fmt(
                    row["Turnover"],
                    0
                ),

                fmt(
                    row["Close"]
                ),

                fmt(
                    row["EMA20"]
                ),

                fmt(
                    row["EMA50"]
                ),

                fmt(
                    row["RSI14"]
                ),

                fmt(
                    row["VolumeRatio"]
                ),

                fmt(
                    row["20-Day High"]
                ),

                fmt(
                    row["Breakout Level"]
                ),

                fmt(
                    row["Entry"]
                ),

                fmt(
                    row["Stop Loss"]
                ),

                fmt(
                    row["Target 1"]
                ),

                fmt(
                    row["Target 2"]
                ),

                fmt(
                    row["Risk %"]
                ),

                fmt(
                    row["TodayChangePct"]
                ),

                row["Setup"],

                int(
                    row["Strength Score"]
                ),

                fmt(
                    row["Range20Pct"]
                ),

                fmt(
                    row["ATR14"]
                ),

                (
                    row["Breakout Date"].strftime(
                        "%Y-%m-%d"
                    )
                    if hasattr(
                        row["Breakout Date"],
                        "strftime"
                    )
                    else row["Breakout Date"]
                ),

                tradingview_formula(
                    symbol
                )
            ]
        )

    return rows


# ============================================================
# UPDATE GOOGLE SHEET
# ============================================================

def update_sheet(
    spreadsheet,
    sheet_name,
    values
):

    try:

        worksheet = spreadsheet.worksheet(
            sheet_name
        )

    except gspread.WorksheetNotFound:

        worksheet = spreadsheet.add_worksheet(
            title=sheet_name,
            rows=1000,
            cols=30
        )

    worksheet.clear()

    if not values:
        return

    worksheet.update(
        range_name="A1",
        values=values,
        value_input_option="USER_ENTERED"
    )

    # Freeze header
    try:
        worksheet.freeze(rows=1)
    except Exception:
        pass


# ============================================================
# OPTIONAL SHEET FORMATTING
# ============================================================

def format_final_sheet(
    spreadsheet,
    sheet_name
):

    try:

        worksheet = spreadsheet.worksheet(
            sheet_name
        )

        # Header bold
        worksheet.format(
            "A1:V1",
            {
                "textFormat": {
                    "bold": True
                }
            }
        )

        # Wider columns
        widths = {
            "A": 110,
            "B": 100,
            "C": 120,
            "D": 90,
            "E": 90,
            "F": 90,
            "G": 80,
            "H": 100,
            "I": 110,
            "J": 110,
            "K": 90,
            "L": 90,
            "M": 90,
            "N": 90,
            "O": 80,
            "P": 110,
            "Q": 130,
            "R": 100,
            "S": 120,
            "T": 90,
            "U": 110,
            "V": 110
        }

        # Some gspread versions don't support
        # direct width formatting consistently,
        # so ignore failures.
        for col, width in widths.items():

            try:

                worksheet.format(
                    f"{col}:{col}",
                    {
                        "pixelSize": width
                    }
                )

            except Exception:
                pass

    except Exception as e:

        print(
            "Formatting warning:",
            e
        )


# ============================================================
# PRINT FINAL RESULT
# ============================================================

def print_results(df):

    print("")
    print("=" * 110)
    print("NIFTY 200 SWING SNIPER V2.1 - FINAL LIST")
    print("=" * 110)

    if df.empty:

        print(
            "No stock qualified today."
        )

        return

    display_columns = [
        "Symbol",
        "Turnover Rank",
        "Close",
        "EMA20",
        "EMA50",
        "RSI14",
        "VolumeRatio",
        "20-Day High",
        "Breakout Level",
        "Entry",
        "Stop Loss",
        "Target 1",
        "Target 2",
        "Risk %",
        "Setup",
        "Strength Score"
    ]

    print(
        df[
            display_columns
        ].to_string(
            index=False
        )
    )

    print("")
    print(
        "Total final stocks:",
        len(df)
    )

    print("")
    print(
        "IMPORTANT:"
    )

    print(
        "RETEST + HOLD = highest priority"
    )

    print(
        "FRESH BREAKOUT = confirmed breakout"
    )

    print(
        "BREAKOUT WATCH = wait for breakout + volume confirmation"
    )

    print(
        "RSI 68-70 = NO CHASE / WATCH zone"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("")
    print("=" * 70)
    print("NIFTY 200 SWING SNIPER V2.1")
    print("=" * 70)
    print("")

    # --------------------------------------------------------
    # Download history
    # --------------------------------------------------------

    history = get_market_history()

    print("")
    print(
        "Historical rows:",
        len(history)
    )

    print(
        "Latest date:",
        history["Date"].max()
    )

    # --------------------------------------------------------
    # Top 200
    # --------------------------------------------------------

    top_symbols = get_top_200_symbols(
        history
    )

    print(
        "Top 200 stocks:",
        len(top_symbols)
    )

    # --------------------------------------------------------
    # Run screener
    # --------------------------------------------------------

    final_df = run_screener(
        history
    )

    # --------------------------------------------------------
    # Print
    # --------------------------------------------------------

    print_results(
        final_df
    )

    # --------------------------------------------------------
    # Google Sheets
    # --------------------------------------------------------

    try:

        client = get_google_client()

        spreadsheet = client.open_by_key(
            SPREADSHEET_ID
        )

        # NIFTY200 sheet
        nifty_values = (
            [
                [
                    "NSE Code",
                    "Turnover Rank",
                    "Turnover"
                ]
            ]
            +
            build_nifty200_sheet(
                top_symbols
            )
        )

        update_sheet(
            spreadsheet,
            NIFTY_SHEET,
            nifty_values
        )

        # Final List
        if final_df.empty:

            final_values = [
                [
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
            ]

        else:

            final_values = build_final_sheet(
                final_df
            )

        update_sheet(
            spreadsheet,
            FINAL_SHEET,
            final_values
        )

        format_final_sheet(
            spreadsheet,
            FINAL_SHEET
        )

        print("")
        print(
            "Google Sheets updated successfully."
        )

        print(
            f"Sheet: {FINAL_SHEET}"
        )

    except Exception as e:

        print("")
        print(
            "Google Sheets update failed:"
        )

        print(e)

    print("")
    print("=" * 70)
    print("V2.1 COMPLETE")
    print("=" * 70)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
