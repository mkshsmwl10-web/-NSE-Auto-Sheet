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
# NIFTY 200 SWING SNIPER V2
# ============================================================
#
# PURPOSE:
#   DAILY SWING TRADING SCREENER
#
# FINAL LIST PRIORITY:
#   1. RETEST + HOLD
#   2. FRESH 20-DAY BREAKOUT
#   3. BREAKOUT WATCH
#
# CORE FILTERS:
#   - NIFTY 200 universe
#   - Top 200 by turnover
#   - EMA20 > EMA50
#   - Close > EMA20
#   - RSI14
#   - Volume >= 1.5x Volume20 average
#   - 20-day breakout
#   - Proper breakout retest
#   - Current price cannot be far away from breakout level
#   - RSI > 70 = NO CHASE
#   - RSI > 80 = HARD REJECT
#   - Maximum risk = 6%
#
# TARGET:
#   T1 = 1.5R
#   T2 = 3R
#
# GOOGLE SHEETS:
#   Sheet 1 = NIFTY200
#   Sheet 2 = Final List
#
# TRADINGVIEW:
#   Daily clickable chart
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

# Need enough history for EMA50 + RSI + ATR + 20D breakout
HISTORY_TRADING_DAYS = 90

# Swing parameters
BREAKOUT_LOOKBACK = 20

EMA_FAST = 20
EMA_SLOW = 50

RSI_LENGTH = 14
ATR_LENGTH = 14
VOLUME_LENGTH = 20

MIN_VOLUME_RATIO = 1.50

# RSI rules
RSI_REJECT = 50
RSI_BUY_MIN = 55
RSI_BUY_MAX = 70
RSI_HARD_REJECT = 80

# Maximum distance above breakout level
MAX_BREAKOUT_EXTENSION_PCT = 3.0

# Watch zone
WATCH_DISTANCE_PCT = 2.0

# Retest zone
RETEST_MAX_ABOVE_PCT = 1.0
RETEST_MAX_BELOW_PCT = 3.0

# Maximum swing risk
MAX_RISK_PCT = 6.0

# Targets
TARGET1_R = 1.5
TARGET2_R = 3.0

# Maximum stocks in Final List
MAX_FINAL_STOCKS = 15

# Number of sessions to search backward for previous breakout
RETEST_LOOKBACK_DAYS = 5


# ============================================================
# GOOGLE AUTH
# ============================================================

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets"
]


# ============================================================
# SAFE GOOGLE API FUNCTIONS
# ============================================================

def safe_google_call(func, *args, retries=5, **kwargs):
    """
    Retry Google API calls if temporary errors occur.
    """

    for attempt in range(retries):

        try:
            return func(*args, **kwargs)

        except Exception as e:

            print(
                f"Google API error "
                f"(attempt {attempt + 1}/{retries}): {e}"
            )

            if attempt < retries - 1:
                time.sleep(2 + attempt * 2)

            else:
                raise


def safe_batch_clear(worksheet, ranges):

    try:
        return safe_google_call(
            worksheet.batch_clear,
            ranges
        )

    except Exception as e:

        print(f"Batch clear failed: {e}")

        return None


def safe_update(worksheet, cell_range, values):

    for attempt in range(5):

        try:

            return worksheet.update(
                cell_range,
                values,
                value_input_option="USER_ENTERED"
            )

        except Exception as e:

            print(
                f"Update error "
                f"(attempt {attempt + 1}/5): {e}"
            )

            if attempt < 4:
                time.sleep(2 + attempt)

            else:
                raise


def safe_format(worksheet, cell_range, fmt):

    try:

        return worksheet.format(
            cell_range,
            fmt
        )

    except Exception as e:

        print(f"Formatting skipped: {e}")


# ============================================================
# NSE SESSION
# ============================================================

def create_nse_session():

    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/140.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/"
    })

    try:
        session.get(
            "https://www.nseindia.com/",
            timeout=15
        )
    except Exception:
        pass

    return session


# ============================================================
# FIND COLUMN
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
# FETCH NSE BHAVCOPY
# ============================================================

def fetch_bhavcopy(session, date_obj):

    date_str = date_obj.strftime("%Y%m%d")

    url = (
        "https://nsearchives.nseindia.com/content/cm/"
        f"BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv.zip"
    )

    try:

        response = session.get(
            url,
            timeout=30
        )

        if response.status_code != 200:
            return None

        if len(response.content) < 500:
            return None

        with zipfile.ZipFile(
            io.BytesIO(response.content)
        ) as z:

            csv_files = [
                name
                for name in z.namelist()
                if name.lower().endswith(".csv")
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
# NORMALIZE BHAVCOPY
# ============================================================

def normalize_bhavcopy(raw_df):

    if raw_df is None or raw_df.empty:
        return None

    symbol_col = find_column(
        raw_df,
        [
            "TckrSymb",
            "SYMBOL",
            "Symbol"
        ]
    )

    open_col = find_column(
        raw_df,
        [
            "OpnPric",
            "OPEN",
            "Open"
        ]
    )

    high_col = find_column(
        raw_df,
        [
            "HghPric",
            "HIGH",
            "High"
        ]
    )

    low_col = find_column(
        raw_df,
        [
            "LwPric",
            "LOW",
            "Low"
        ]
    )

    close_col = find_column(
        raw_df,
        [
            "ClsPric",
            "CLOSE",
            "Close"
        ]
    )

    turnover_col = find_column(
        raw_df,
        [
            "TtlTrfVal",
            "TOTTRDVAL",
            "Turnover",
            "TURNOVER"
        ]
    )

    volume_col = find_column(
        raw_df,
        [
            "TtlTradgVol",
            "TOTTRDQTY",
            "TotalTradedQuantity",
            "TOTTRDQTY"
        ]
    )

    series_col = find_column(
        raw_df,
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
        turnover_col
    ]

    if any(x is None for x in required):

        print(
            "Required NSE columns not found."
        )

        print(
            "Available columns:",
            list(raw_df.columns)
        )

        return None

    data = pd.DataFrame()

    data["symbol"] = (
        raw_df[symbol_col]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    data["open"] = pd.to_numeric(
        raw_df[open_col],
        errors="coerce"
    )

    data["high"] = pd.to_numeric(
        raw_df[high_col],
        errors="coerce"
    )

    data["low"] = pd.to_numeric(
        raw_df[low_col],
        errors="coerce"
    )

    data["close"] = pd.to_numeric(
        raw_df[close_col],
        errors="coerce"
    )

    data["turnover"] = pd.to_numeric(
        raw_df[turnover_col],
        errors="coerce"
    )

    # --------------------------------------------------------
    # REAL TRADED QUANTITY
    # --------------------------------------------------------

    if volume_col is not None:

        data["volume"] = pd.to_numeric(
            raw_df[volume_col],
            errors="coerce"
        )

    else:

        # Do NOT use turnover as volume.
        # If quantity is unavailable, volume ratio
        # will simply remain unavailable.
        data["volume"] = np.nan

    # --------------------------------------------------------
    # SERIES FILTER
    # --------------------------------------------------------

    if series_col is not None:

        data["series"] = (
            raw_df[series_col]
            .astype(str)
            .str.upper()
            .str.strip()
        )

        data = data[
            data["series"].eq("EQ")
        ]

    # --------------------------------------------------------
    # BASIC CLEANING
    # --------------------------------------------------------

    data = data.dropna(
        subset=[
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "turnover"
        ]
    )

    data = data[
        (data["close"] > 0) &
        (data["high"] > 0) &
        (data["low"] > 0)
    ]

    # --------------------------------------------------------
    # REMOVE ETFs / INDEX PRODUCTS
    # --------------------------------------------------------

    exclude_pattern = (
        r"BEES|ETF|GOLD|LIQUID|SILVER|INDEX"
    )

    data = data[
        ~data["symbol"].str.contains(
            exclude_pattern,
            case=False,
            regex=True,
            na=False
        )
    ]

    data = data.drop_duplicates(
        subset=["symbol"],
        keep="first"
    )

    return data


# ============================================================
# GET TRADING DAYS
# ============================================================

def get_recent_market_data(session, required_days=90):

    print(
        f"\nDownloading approximately "
        f"{required_days} trading days..."
    )

    frames = []

    current_date = datetime.now().date()

    days_checked = 0

    while (
        len(frames) < required_days
        and days_checked < required_days + 45
    ):

        date_obj = (
            current_date -
            timedelta(days=days_checked)
        )

        raw = fetch_bhavcopy(
            session,
            date_obj
        )

        if raw is not None:

            df = normalize_bhavcopy(
                raw
            )

            if df is not None and not df.empty:

                df["date"] = pd.Timestamp(
                    date_obj
                )

                frames.append(df)

                print(
                    f"Downloaded "
                    f"{date_obj}: "
                    f"{len(df)} stocks"
                )

        days_checked += 1

        time.sleep(0.15)

    if not frames:

        raise RuntimeError(
            "No NSE market data downloaded."
        )

    result = pd.concat(
        frames,
        ignore_index=True
    )

    result = result.sort_values(
        ["date", "symbol"]
    )

    return result


# ============================================================
# TECHNICAL INDICATORS
# ============================================================

def calculate_rsi(series, length=14):

    delta = series.diff()

    gain = delta.clip(
        lower=0
    )

    loss = -delta.clip(
        upper=0
    )

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


def calculate_atr(df, length=14):

    previous_close = df["close"].shift(1)

    tr1 = (
        df["high"] -
        df["low"]
    )

    tr2 = (
        df["high"] -
        previous_close
    ).abs()

    tr3 = (
        df["low"] -
        previous_close
    ).abs()

    true_range = pd.concat(
        [tr1, tr2, tr3],
        axis=1
    ).max(axis=1)

    atr = true_range.ewm(
        alpha=1 / length,
        adjust=False,
        min_periods=length
    ).mean()

    return atr


def add_indicators(df):

    df = df.copy()

    df = df.sort_values(
        "date"
    )

    # EMA20
    df["ema20"] = (
        df["close"]
        .ewm(
            span=EMA_FAST,
            adjust=False
        )
        .mean()
    )

    # EMA50
    df["ema50"] = (
        df["close"]
        .ewm(
            span=EMA_SLOW,
            adjust=False
        )
        .mean()
    )

    # RSI
    df["rsi"] = calculate_rsi(
        df["close"],
        RSI_LENGTH
    )

    # ATR
    df["atr"] = calculate_atr(
        df,
        ATR_LENGTH
    )

    # Volume average
    if df["volume"].notna().sum() >= VOLUME_LENGTH:

        df["volume_avg20"] = (
            df["volume"]
            .rolling(
                VOLUME_LENGTH
            )
            .mean()
        )

        df["volume_ratio"] = (
            df["volume"] /
            df["volume_avg20"]
        )

    else:

        df["volume_avg20"] = np.nan
        df["volume_ratio"] = np.nan

    # 20-day previous high
    # IMPORTANT:
    # excludes today's candle
    df["prev20_high"] = (
        df["high"]
        .rolling(
            BREAKOUT_LOOKBACK
        )
        .max()
        .shift(1)
    )

    # 20-day previous low
    df["prev20_low"] = (
        df["low"]
        .rolling(
            BREAKOUT_LOOKBACK
        )
        .min()
        .shift(1)
    )

    # 20-day range
    df["range20_high"] = (
        df["high"]
        .rolling(
            BREAKOUT_LOOKBACK
        )
        .max()
    )

    df["range20_low"] = (
        df["low"]
        .rolling(
            BREAKOUT_LOOKBACK
        )
        .min()
    )

    df["range20_pct"] = (
        (
            df["range20_high"] /
            df["range20_low"]
        ) - 1
    ) * 100

    # EMA slope
    df["ema20_prev5"] = (
        df["ema20"].shift(5)
    )

    df["ema20_slope_pct"] = (
        (
            df["ema20"] /
            df["ema20_prev5"]
        ) - 1
    ) * 100

    # Daily change
    df["today_change_pct"] = (
        (
            df["close"] /
            df["close"].shift(1)
        ) - 1
    ) * 100

    return df


# ============================================================
# BREAKOUT DETECTION
# ============================================================

def find_previous_breakout(df):

    """
    Search last 5 completed sessions for a genuine
    20-day breakout.

    A valid breakout requires:

        close > previous 20-day high
        EMA20 > EMA50
        volume >= 1.5x average
        RSI 55-70
    """

    if len(df) < 30:
        return None

    last_idx = len(df) - 1

    start_idx = max(
        BREAKOUT_LOOKBACK + 1,
        last_idx - RETEST_LOOKBACK_DAYS
    )

    candidates = []

    for idx in range(
        start_idx,
        last_idx
    ):

        row = df.iloc[idx]

        prior20_high = (
            df["high"]
            .iloc[
                idx - BREAKOUT_LOOKBACK:idx
            ]
            .max()
        )

        if pd.isna(prior20_high):
            continue

        close = row["close"]

        if not (
            close > prior20_high
        ):
            continue

        ema20 = row["ema20"]
        ema50 = row["ema50"]

        if pd.isna(ema20) or pd.isna(ema50):
            continue

        if not (
            ema20 > ema50
        ):
            continue

        rsi = row["rsi"]

        if pd.isna(rsi):
            continue

        if not (
            RSI_BUY_MIN <= rsi <= RSI_BUY_MAX
        ):
            continue

        volume_ratio = row[
            "volume_ratio"
        ]

        if pd.isna(volume_ratio):
            continue

        if volume_ratio < MIN_VOLUME_RATIO:
            continue

        candidates.append({
            "idx": idx,
            "date": row["date"],
            "level": prior20_high,
            "close": close
        })

    if not candidates:
        return None

    # Most recent valid breakout
    return candidates[-1]


# ============================================================
# TRUE RETEST DETECTION
# ============================================================

def detect_retest(df):

    """
    True retest conditions:

    1. Previous valid 20-day breakout exists
    2. Breakout occurred within last 5 sessions
    3. Today's LOW comes back near breakout level
    4. Today's CLOSE remains above breakout level
    5. Price is not >3% above breakout level
    6. Current RSI is 50-70
    7. RSI >70 = reject
    8. Deep breakdown >3% below breakout level = reject
    """

    breakout = find_previous_breakout(df)

    if breakout is None:
        return None

    today = df.iloc[-1]

    level = breakout["level"]

    close = today["close"]
    low = today["low"]

    if pd.isna(close) or pd.isna(low):
        return None

    # Current price distance from breakout level
    extension_pct = (
        (close / level) - 1
    ) * 100

    # If price already ran >3%, this is NOT a retest
    if extension_pct > MAX_BREAKOUT_EXTENSION_PCT:
        return None

    # Deep failure below breakout level
    low_distance_pct = (
        (low / level) - 1
    ) * 100

    if low_distance_pct < -RETEST_MAX_BELOW_PCT:
        return None

    # Low must actually touch / come near breakout level
    if low > (
        level *
        (1 + RETEST_MAX_ABOVE_PCT / 100)
    ):
        return None

    # Close must hold above breakout
    if close <= level:
        return None

    # Current RSI
    rsi = today["rsi"]

    if pd.isna(rsi):
        return None

    # Hard reject high RSI
    if rsi > RSI_BUY_MAX:
        return None

    if rsi < RSI_REJECT:
        return None

    # Trend
    if not (
        today["ema20"] >
        today["ema50"]
    ):
        return None

    if close <= today["ema20"]:
        return None

    # Recent low for stop
    recent5_low = (
        df["low"]
        .iloc[-5:]
        .min()
    )

    atr = today["atr"]

    if pd.isna(atr) or atr <= 0:
        return None

    return {
        "setup": "RETEST + HOLD",
        "breakout_level": level,
        "breakout_date": breakout["date"],
        "entry": close,
        "extension_pct": extension_pct,
        "recent5_low": recent5_low,
        "atr": atr
    }


# ============================================================
# FRESH BREAKOUT
# ============================================================

def detect_fresh_breakout(df):

    today = df.iloc[-1]

    close = today["close"]
    prev20_high = today["prev20_high"]

    if pd.isna(prev20_high):
        return None

    # Today's close must break previous 20D high
    if close <= prev20_high:
        return None

    # Trend
    if not (
        today["ema20"] >
        today["ema50"]
    ):
        return None

    if close <= today["ema20"]:
        return None

    # RSI hard filter
    rsi = today["rsi"]

    if pd.isna(rsi):
        return None

    if rsi > RSI_BUY_MAX:
        return None

    if rsi < RSI_BUY_MIN:
        return None

    # Volume
    volume_ratio = today[
        "volume_ratio"
    ]

    if pd.isna(volume_ratio):
        return None

    if volume_ratio < MIN_VOLUME_RATIO:
        return None

    # Don't chase
    extension_pct = (
        (close / prev20_high) - 1
    ) * 100

    if extension_pct > MAX_BREAKOUT_EXTENSION_PCT:
        return None

    atr = today["atr"]

    if pd.isna(atr) or atr <= 0:
        return None

    recent5_low = (
        df["low"]
        .iloc[-5:]
        .min()
    )

    return {
        "setup": "FRESH 20-DAY BREAKOUT",
        "breakout_level": prev20_high,
        "breakout_date": today["date"],
        "entry": close,
        "extension_pct": extension_pct,
        "recent5_low": recent5_low,
        "atr": atr
    }


# ============================================================
# BREAKOUT WATCH
# ============================================================

def detect_breakout_watch(df):

    today = df.iloc[-1]

    close = today["close"]

    prev20_high = today[
        "prev20_high"
    ]

    if pd.isna(prev20_high):
        return None

    # Must not already be broken
    if close >= prev20_high:
        return None

    # Distance below breakout
    distance_pct = (
        (prev20_high / close) - 1
    ) * 100

    # Only close to breakout
    if distance_pct > WATCH_DISTANCE_PCT:
        return None

    # Trend
    if not (
        today["ema20"] >
        today["ema50"]
    ):
        return None

    if close <= today["ema20"]:
        return None

    # RSI
    rsi = today["rsi"]

    if pd.isna(rsi):
        return None

    if rsi < 50:
        return None

    if rsi > 70:
        return None

    # Volume does not have to already be 1.5x
    # because this is a WATCH setup.

    atr = today["atr"]

    if pd.isna(atr) or atr <= 0:
        return None

    recent5_low = (
        df["low"]
        .iloc[-5:]
        .min()
    )

    return {
        "setup": "BREAKOUT WATCH",
        "breakout_level": prev20_high,
        "breakout_date": "",
        "entry": prev20_high,
        "extension_pct": 0,
        "recent5_low": recent5_low,
        "atr": atr
    }


# ============================================================
# STOP LOSS / TARGETS
# ============================================================

def calculate_trade_levels(
    entry,
    breakout_level,
    recent5_low,
    atr,
    setup
):

    if pd.isna(entry):
        return None

    if pd.isna(atr) or atr <= 0:
        return None

    # --------------------------------------------------------
    # Stop logic
    # --------------------------------------------------------
    #
    # For a swing trade:
    #
    # recent low - 0.25 ATR
    #
    # But we also keep breakout structure in mind.
    #
    # Stop must remain below entry.
    #

    structure_stop = (
        recent5_low -
        0.25 * atr
    )

    breakout_stop = (
        breakout_level -
        0.50 * atr
    )

    # Use tighter of the two valid structure stops
    candidates = [
        structure_stop,
        breakout_stop
    ]

    candidates = [
        x for x in candidates
        if pd.notna(x) and x < entry
    ]

    if not candidates:
        return None

    # Choose higher stop = lower risk
    stop_loss = max(candidates)

    # Risk
    risk = (
        entry -
        stop_loss
    )

    if risk <= 0:
        return None

    risk_pct = (
        risk /
        entry
    ) * 100

    # Maximum risk filter
    if risk_pct > MAX_RISK_PCT:
        return None

    target1 = (
        entry +
        TARGET1_R * risk
    )

    target2 = (
        entry +
        TARGET2_R * risk
    )

    return {
        "entry": entry,
        "stop_loss": stop_loss,
        "target1": target1,
        "target2": target2,
        "risk_pct": risk_pct
    }


# ============================================================
# STRENGTH SCORE
# ============================================================

def calculate_strength_score(
    row,
    setup,
    breakout_extension_pct
):

    score = 0

    close = row["close"]
    ema20 = row["ema20"]
    ema50 = row["ema50"]
    rsi = row["rsi"]
    volume_ratio = row["volume_ratio"]
    ema20_slope = row["ema20_slope_pct"]
    range20_pct = row["range20_pct"]

    # --------------------------------------------------------
    # TREND
    # --------------------------------------------------------

    if ema20 > ema50:
        score += 20

    # --------------------------------------------------------
    # PRICE ABOVE EMA20
    # --------------------------------------------------------

    if close > ema20:
        score += 10

    # --------------------------------------------------------
    # EMA20 SLOPE
    # --------------------------------------------------------

    if pd.notna(ema20_slope):

        if ema20_slope > 1.0:
            score += 10

        elif ema20_slope > 0:
            score += 5

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if pd.notna(rsi):

        if 55 <= rsi <= 65:
            score += 15

        elif 65 < rsi <= 70:
            score += 10

        elif 50 <= rsi < 55:
            score += 5

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    if pd.notna(volume_ratio):

        if volume_ratio >= 2.0:
            score += 20

        elif volume_ratio >= 1.5:
            score += 15

        elif volume_ratio >= 1.2:
            score += 10

    # --------------------------------------------------------
    # SETUP
    # --------------------------------------------------------

    if setup == "RETEST + HOLD":
        score += 20

    elif setup == "FRESH 20-DAY BREAKOUT":
        score += 15

    elif setup == "BREAKOUT WATCH":
        score += 5

    # --------------------------------------------------------
    # CONSOLIDATION QUALITY
    # --------------------------------------------------------

    if pd.notna(range20_pct):

        if range20_pct <= 12:
            score += 5

    return min(
        int(score),
        100
    )


# ============================================================
# PROCESS ONE STOCK
# ============================================================

def process_stock(symbol_df):

    if symbol_df is None:
        return None

    if len(symbol_df) < 60:
        return None

    df = symbol_df.copy()

    df = df.sort_values(
        "date"
    ).reset_index(
        drop=True
    )

    df = add_indicators(
        df
    )

    today = df.iloc[-1]

    # --------------------------------------------------------
    # Basic validity
    # --------------------------------------------------------

    required_values = [
        today["close"],
        today["ema20"],
        today["ema50"],
        today["rsi"],
        today["atr"]
    ]

    if any(
        pd.isna(x)
        for x in required_values
    ):
        return None

    # --------------------------------------------------------
    # HARD RSI REJECTION
    # --------------------------------------------------------

    if today["rsi"] > RSI_HARD_REJECT:
        return None

    # RSI below 50 cannot be a buy setup
    if today["rsi"] < RSI_REJECT:
        return None

    # --------------------------------------------------------
    # PRIORITY 1: RETEST
    # --------------------------------------------------------

    setup_data = detect_retest(
        df
    )

    # --------------------------------------------------------
    # PRIORITY 2: FRESH BREAKOUT
    # --------------------------------------------------------

    if setup_data is None:

        setup_data = detect_fresh_breakout(
            df
        )

    # --------------------------------------------------------
    # PRIORITY 3: WATCH
    # --------------------------------------------------------

    if setup_data is None:

        setup_data = detect_breakout_watch(
            df
        )

    if setup_data is None:
        return None

    # --------------------------------------------------------
    # TRADE LEVELS
    # --------------------------------------------------------

    trade = calculate_trade_levels(
        entry=setup_data["entry"],
        breakout_level=setup_data[
            "breakout_level"
        ],
        recent5_low=setup_data[
            "recent5_low"
        ],
        atr=setup_data["atr"],
        setup=setup_data["setup"]
    )

    if trade is None:
        return None

    # --------------------------------------------------------
    # STRENGTH SCORE
    # --------------------------------------------------------

    score = calculate_strength_score(
        today,
        setup_data["setup"],
        setup_data["extension_pct"]
    )

    # --------------------------------------------------------
    # FINAL RESULT
    # --------------------------------------------------------

    result = {

        "NSE Code": symbol_df[
            "symbol"
        ].iloc[-1],

        "Close": today["close"],

        "EMA20": today["ema20"],

        "EMA50": today["ema50"],

        "RSI14": today["rsi"],

        "Volume Ratio": today[
            "volume_ratio"
        ],

        "20-Day High": today[
            "prev20_high"
        ],

        "Breakout Level": setup_data[
            "breakout_level"
        ],

        "Entry": trade[
            "entry"
        ],

        "Stop Loss": trade[
            "stop_loss"
        ],

        "Target 1": trade[
            "target1"
        ],

        "Target 2": trade[
            "target2"
        ],

        "Risk %": trade[
            "risk_pct"
        ],

        "Today Change %": today[
            "today_change_pct"
        ],

        "Setup": setup_data[
            "setup"
        ],

        "Strength Score": score,

        "20-Day Range %": today[
            "range20_pct"
        ],

        "ATR14": today[
            "atr"
        ],

        "Breakout Date": setup_data[
            "breakout_date"
        ],

        "Breakout Extension %": setup_data[
            "extension_pct"
        ]
    }

    return result


# ============================================================
# TRADINGVIEW CHART
# ============================================================

def tradingview_formula(symbol):

    # Important:
    # safe="" ensures special symbols like M&M
    # are properly encoded.

    chart_symbol = quote(
        f"NSE:{symbol}",
        safe=""
    )

    url = (
        "https://www.tradingview.com/chart/"
        f"?symbol={chart_symbol}"
        "&interval=D"
    )

    return (
        '=HYPERLINK('
        f'"{url}",'
        '"Daily Chart")'
    )


# ============================================================
# GOOGLE SHEET AUTHENTICATION
# ============================================================

def connect_google():

    credentials_json = os.environ.get(
        "GCP_CREDENTIALS"
    )

    if not credentials_json:

        raise RuntimeError(
            "GCP_CREDENTIALS environment variable "
            "was not found."
        )

    try:

        credentials_dict = json.loads(
            credentials_json
        )

    except Exception:

        raise RuntimeError(
            "GCP_CREDENTIALS is not valid JSON."
        )

    credentials = (
        ServiceAccountCredentials
        .from_json_keyfile_dict(
            credentials_dict,
            SCOPES
        )
    )

    client = gspread.authorize(
        credentials
    )

    spreadsheet = safe_google_call(
        client.open_by_key,
        SPREADSHEET_ID
    )

    return spreadsheet


# ============================================================
# UPDATE NIFTY200 SHEET
# ============================================================

def update_nifty200_sheet(
    spreadsheet,
    market_df
):

    print(
        "\nUpdating NIFTY200 sheet..."
    )

    try:

        sheet = safe_google_call(
            spreadsheet.worksheet,
            NIFTY_SHEET
        )

    except Exception:

        sheet = safe_google_call(
            spreadsheet.add_worksheet,
            NIFTY_SHEET,
            rows=1000,
            cols=20
        )

    # --------------------------------------------------------
    # Latest day only
    # --------------------------------------------------------

    latest_date = market_df[
        "date"
    ].max()

    latest = market_df[
        market_df["date"].eq(
            latest_date
        )
    ].copy()

    latest = latest.sort_values(
        "turnover",
        ascending=False
    ).head(
        TOP_STOCKS
    )

    latest["Turnover Rank"] = range(
        1,
        len(latest) + 1
    )

    output = [
        [
            "NSE Code",
            "Turnover Rank",
            "Turnover",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume"
        ]
    ]

    for _, row in latest.iterrows():

        output.append([
            row["symbol"],
            int(row["Turnover Rank"]),
            round(
                float(row["turnover"]),
                2
            ),
            round(
                float(row["open"]),
                2
            ),
            round(
                float(row["high"]),
                2
            ),
            round(
                float(row["low"]),
                2
            ),
            round(
                float(row["close"]),
                2
            ),
            (
                round(
                    float(row["volume"]),
                    0
                )
                if pd.notna(
                    row["volume"]
                )
                else ""
            )
        ])

    # Clear existing
    safe_batch_clear(
        sheet,
        [
            "A:Z"
        ]
    )

    safe_update(
        sheet,
        "A1",
        output
    )

    safe_format(
        sheet,
        "A1:H1",
        {
            "textFormat": {
                "bold": True
            }
        }
    )

    print(
        f"NIFTY200 updated: "
        f"{len(output) - 1} stocks"
    )


# ============================================================
# UPDATE FINAL LIST
# ============================================================

def update_final_sheet(
    spreadsheet,
    final_df
):

    print(
        "\nUpdating Final List..."
    )

    try:

        sheet = safe_google_call(
            spreadsheet.worksheet,
            FINAL_SHEET
        )

    except Exception:

        sheet = safe_google_call(
            spreadsheet.add_worksheet,
            FINAL_SHEET,
            rows=1000,
            cols=30
        )

    # --------------------------------------------------------
    # Column order
    # --------------------------------------------------------

    columns = [

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

    output = [
        columns
    ]

    # --------------------------------------------------------
    # Rows
    # --------------------------------------------------------

    for _, row in final_df.iterrows():

        symbol = row[
            "NSE Code"
        ]

        output.append([

            symbol,

            int(
                row["Turnover Rank"]
            ),

            round(
                float(row["Turnover"]),
                2
            ),

            round(
                float(row["Close"]),
                2
            ),

            round(
                float(row["EMA20"]),
                2
            ),

            round(
                float(row["EMA50"]),
                2
            ),

            round(
                float(row["RSI14"]),
                2
            ),

            (
                round(
                    float(row["Volume Ratio"]),
                    2
                )
                if pd.notna(
                    row["Volume Ratio"]
                )
                else ""
            ),

            round(
                float(row["20-Day High"]),
                2
            ),

            round(
                float(row["Breakout Level"]),
                2
            ),

            round(
                float(row["Entry"]),
                2
            ),

            round(
                float(row["Stop Loss"]),
                2
            ),

            round(
                float(row["Target 1"]),
                2
            ),

            round(
                float(row["Target 2"]),
                2
            ),

            round(
                float(row["Risk %"]),
                2
            ),

            round(
                float(row["Today Change %"]),
                2
            ),

            row["Setup"],

            int(
                row["Strength Score"]
            ),

            round(
                float(row["20-Day Range %"]),
                2
            ),

            round(
                float(row["ATR14"]),
                2
            ),

            (
                row["Breakout Date"]
                .strftime("%Y-%m-%d")
                if isinstance(
                    row["Breakout Date"],
                    pd.Timestamp
                )
                else row["Breakout Date"]
            ),

            tradingview_formula(
                symbol
            )
        ])

    # --------------------------------------------------------
    # Clear old Final List
    # --------------------------------------------------------

    safe_batch_clear(
        sheet,
        [
            "A:Z"
        ]
    )

    # --------------------------------------------------------
    # Write
    # --------------------------------------------------------

    safe_update(
        sheet,
        "A1",
        output
    )

    # --------------------------------------------------------
    # Header formatting
    # --------------------------------------------------------

    safe_format(
        sheet,
        "A1:V1",
        {
            "textFormat": {
                "bold": True
            }
        }
    )

    # --------------------------------------------------------
    # Number formatting
    # --------------------------------------------------------

    safe_format(
        sheet,
        f"D2:N{max(2, len(output))}",
        {
            "numberFormat": {
                "type": "NUMBER",
                "pattern": "0.00"
            }
        }
    )

    safe_format(
        sheet,
        f"G2:G{max(2, len(output))}",
        {
            "numberFormat": {
                "type": "NUMBER",
                "pattern": "0.00"
            }
        }
    )

    safe_format(
        sheet,
        f"O2:P{max(2, len(output))}",
        {
            "numberFormat": {
                "type": "NUMBER",
                "pattern": "0.00"
            }
        }
    )

    print(
        f"Final List updated: "
        f"{len(output) - 1} stocks"
    )


# ============================================================
# MAIN SCREENER
# ============================================================

def main():

    print(
        "\n"
        "============================================================\n"
        "       NIFTY 200 SWING SNIPER V2\n"
        "============================================================\n"
    )

    start_time = time.time()

    # --------------------------------------------------------
    # NSE SESSION
    # --------------------------------------------------------

    session = create_nse_session()

    # --------------------------------------------------------
    # DOWNLOAD DATA
    # --------------------------------------------------------

    market_df = get_recent_market_data(
        session,
        HISTORY_TRADING_DAYS
    )

    if market_df.empty:

        raise RuntimeError(
            "Market dataframe is empty."
        )

    print(
        f"\nTotal downloaded rows: "
        f"{len(market_df)}"
    )

    # --------------------------------------------------------
    # SELECT TOP 200 BY LATEST TURNOVER
    # --------------------------------------------------------

    latest_date = market_df[
        "date"
    ].max()

    latest = market_df[
        market_df["date"].eq(
            latest_date
        )
    ].copy()

    latest = latest.sort_values(
        "turnover",
        ascending=False
    )

    latest = latest.head(
        TOP_STOCKS
    )

    universe = set(
        latest["symbol"]
        .tolist()
    )

    print(
        f"\nNIFTY 200 universe: "
        f"{len(universe)} stocks"
    )

    # --------------------------------------------------------
    # PROCESS STOCKS
    # --------------------------------------------------------

    results = []

    grouped = market_df[
        market_df["symbol"].isin(
            universe
        )
    ].groupby(
        "symbol"
    )

    total = len(universe)

    for count, (symbol, stock_df) in enumerate(
        grouped,
        start=1
    ):

        print(
            f"[{count}/{total}] "
            f"{symbol}",
            end="\r"
        )

        try:

            result = process_stock(
                stock_df
            )

            if result is not None:

                result[
                    "Turnover Rank"
                ] = int(
                    latest.loc[
                        latest["symbol"].eq(
                            symbol
                        ),
                        "turnover"
                    ].rank(
                        ascending=False,
                        method="min"
                    ).iloc[0]
                )

                result[
                    "Turnover"
                ] = float(
                    latest.loc[
                        latest["symbol"].eq(
                            symbol
                        ),
                        "turnover"
                    ].iloc[0]
                )

                results.append(
                    result
                )

        except Exception as e:

            print(
                f"\nError processing "
                f"{symbol}: {e}"
            )

    print(
        "\n\nProcessing completed."
    )

    # --------------------------------------------------------
    # NO RESULTS
    # --------------------------------------------------------

    if not results:

        print(
            "\nNo Swing Sniper setups found."
        )

        # Still update empty Final List
        empty_columns = [
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

        empty_df = pd.DataFrame(
            columns=empty_columns
        )

        spreadsheet = connect_google()

        update_final_sheet(
            spreadsheet,
            empty_df
        )

        return

    # --------------------------------------------------------
    # RESULTS DATAFRAME
    # --------------------------------------------------------

    result_df = pd.DataFrame(
        results
    )

    # --------------------------------------------------------
    # PRIORITY ORDER
    # --------------------------------------------------------

    setup_priority = {
        "RETEST + HOLD": 1,
        "FRESH 20-DAY BREAKOUT": 2,
        "BREAKOUT WATCH": 3
    }

    result_df[
        "Setup Priority"
    ] = result_df[
        "Setup"
    ].map(
        setup_priority
    ).fillna(99)

    # --------------------------------------------------------
    # QUALITY FILTER
    # --------------------------------------------------------
    #
    # Score >= 60 for actual actionable setups.
    # WATCH can be slightly lower.
    #

    result_df = result_df[
        (
            (
                result_df["Setup"].eq(
                    "BREAKOUT WATCH"
                )
            )
            |
            (
                result_df["Strength Score"] >= 60
            )
        )
    ].copy()

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    result_df = result_df.sort_values(
        [
            "Setup Priority",
            "Strength Score",
            "Turnover Rank"
        ],
        ascending=[
            True,
            False,
            True
        ]
    )

    # --------------------------------------------------------
    # MAX 15 STOCKS
    # --------------------------------------------------------

    result_df = result_df.head(
        MAX_FINAL_STOCKS
    ).copy()

    # --------------------------------------------------------
    # FINAL COLUMN ORDER
    # --------------------------------------------------------

    final_columns = [

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
        "Breakout Date"
    ]

    result_df = result_df[
        final_columns
    ]

    # --------------------------------------------------------
    # PRINT FINAL RESULTS
    # --------------------------------------------------------

    print(
        "\n"
        "============================================================"
    )

    print(
        "              FINAL SWING SNIPER LIST"
    )

    print(
        "============================================================"
    )

    if result_df.empty:

        print(
            "No stocks passed final quality filter."
        )

    else:

        display_columns = [
            "NSE Code",
            "Setup",
            "Close",
            "Breakout Level",
            "Entry",
            "Stop Loss",
            "Target 1",
            "Target 2",
            "RSI14",
            "Volume Ratio",
            "Risk %",
            "Strength Score"
        ]

        print(
            result_df[
                display_columns
            ].to_string(
                index=False
            )
        )

    # --------------------------------------------------------
    # GOOGLE SHEETS
    # --------------------------------------------------------

    spreadsheet = connect_google()

    # Update NIFTY200
    update_nifty200_sheet(
        spreadsheet,
        market_df
    )

    # Update Final List
    update_final_sheet(
        spreadsheet,
        result_df
    )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    elapsed = (
        time.time() -
        start_time
    )

    print(
        "\n"
        "============================================================"
    )

    print(
        "                 SCREENER COMPLETE"
    )

    print(
        "============================================================"
    )

    print(
        f"Latest Market Date : "
        f"{latest_date.strftime('%Y-%m-%d')}"
    )

    print(
        f"Universe           : "
        f"{len(universe)} stocks"
    )

    print(
        f"Final Candidates   : "
        f"{len(result_df)}"
    )

    print(
        f"Runtime            : "
        f"{elapsed:.1f} seconds"
    )

    print(
        "============================================================"
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
