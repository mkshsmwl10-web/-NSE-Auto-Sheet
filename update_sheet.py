# ============================================================
# NIFTY 200 POSITIVE DIVERGENCE SCANNER V1.2
# ============================================================
#
# V1.2 - MORE SIGNALS + DEBUG COUNT
#
# SETUPS:
#   1. RSI POSITIVE DIVERGENCE
#   2. CLASSIC POSITIVE DIVERGENCE
#
# DATA:
#   - NIFTY200 Google Sheet
#   - Yahoo Finance daily OHLCV
#
# V1.2 CHANGES:
#   - More relaxed signal-age filter
#   - More relaxed volume filter
#   - More relaxed maximum-risk filter
#   - Checks multiple valid swing-low pairs
#   - Adds Scanner Debug sheet
#   - Shows rejection count at every stage
#   - Google authentication uses GCP_CREDENTIALS
#   - Supports AA column formatting correctly
#   - Uses named gspread update arguments
#
# IMPORTANT:
#   Only COMPLETED DAILY Yahoo candles are used.
#
# ============================================================

import os
import json
import time
import gspread
import numpy as np
import pandas as pd
import yfinance as yf

from oauth2client.service_account import ServiceAccountCredentials


# ============================================================
# SETTINGS
# ============================================================

SPREADSHEET_ID = "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E"

NIFTY_SHEET = "NIFTY200"
FINAL_SHEET = "Final List"
DEBUG_SHEET = "Scanner Debug"

HISTORY_PERIOD = "1y"
MIN_HISTORY_ROWS = 100

RSI_LENGTH = 14
ATR_LENGTH = 14
VOLUME_LENGTH = 20

# Swing low detection
SWING_LEFT = 3
SWING_RIGHT = 3

# Divergence filters
MIN_PRICE_LOWER_LOW_PCT = 0.30
MIN_RSI_HIGHER_LOW = 1.50

# Maximum distance between two swing lows
MAX_SWING_GAP = 90

# V1.2 - More signals
MAX_SIGNAL_AGE = 30

# V1.2 - More signals
MIN_VOLUME_RATIO = 0.60

# V1.2 - More signals
MAX_RISK_PCT = 10.0

# Targets
TARGET1_R = 1.5
TARGET2_R = 3.0

# Maximum stocks in Final List
MAX_FINAL_STOCKS = 30
MIN_FINAL_SCORE = 60
WATCHLIST_MIN_SCORE = 50

# Optional delay between Yahoo requests
REQUEST_DELAY_SECONDS = 0.10


# ============================================================
# OUTPUT COLUMNS
# ============================================================

OUTPUT_COLUMNS = [
    "NSE Code",
    "Turnover Rank",
    "Turnover",
    "Close",
    "Today Change %",
    "Setup",
    "Divergence Strength",
    "Strength Score",
    "Price Low 1",
    "Price Low 2",
    "RSI Low 1",
    "RSI Low 2",
    "RSI14",
    "RSI Improvement",
    "Volume Ratio",
    "EMA20",
    "EMA50",
    "ATR14",
    "Support",
    "Entry",
    "Stop Loss",
    "Target 1",
    "Target 2",
    "Risk %",
    "Signal Date",
    "Days Since Signal",
    "Chart",
]


# ============================================================
# GOOGLE AUTH
# ============================================================

def connect_google_sheet():

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    credentials_json = os.environ.get("GCP_CREDENTIALS")

    if not credentials_json:
        raise RuntimeError(
            "GCP_CREDENTIALS GitHub Secret nahi mila."
        )

    try:
        credentials_dict = json.loads(credentials_json)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            "GCP_CREDENTIALS valid JSON nahi hai."
        ) from e

    required_keys = [
        "type",
        "client_email",
        "private_key"
    ]

    missing = [
        key for key in required_keys
        if key not in credentials_dict
    ]

    if missing:
        raise RuntimeError(
            "GCP_CREDENTIALS mein required fields missing hain: "
            + ", ".join(missing)
        )

    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        credentials_dict,
        scope
    )

    client = gspread.authorize(creds)

    sh = client.open_by_key(
        SPREADSHEET_ID
    )

    return sh


# ============================================================
# RSI
# ============================================================

def calculate_rsi(series, period=14):

    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False
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
# ATR
# ============================================================

def calculate_atr(df, period=14):

    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    true_range = pd.concat(
        [tr1, tr2, tr3],
        axis=1
    ).max(axis=1)

    atr = true_range.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False
    ).mean()

    return atr


# ============================================================
# SWING LOW DETECTION
# ============================================================

def find_swing_lows(
    series,
    left=3,
    right=3
):

    swing_lows = []

    values = series.values

    for i in range(
        left,
        len(series) - right
    ):

        current = values[i]

        left_values = values[
            i-left:i
        ]

        right_values = values[
            i+1:i+right+1
        ]

        if (
            current < np.min(left_values)
            and
            current <= np.min(right_values)
        ):

            swing_lows.append(i)

    return swing_lows


# ============================================================
# FIND ALL VALID POSITIVE DIVERGENCES
# ============================================================

def find_all_positive_divergences(df):

    if len(df) < MIN_HISTORY_ROWS:
        return []

    swing_lows = find_swing_lows(
        df["Low"],
        SWING_LEFT,
        SWING_RIGHT
    )

    if len(swing_lows) < 2:
        return []

    candidates = []

    # Check every valid pair.
    # Latest pairs are naturally preferred later.
    for x in range(
        1,
        len(swing_lows)
    ):

        i2 = swing_lows[x]

        for y in range(
            x - 1,
            -1,
            -1
        ):

            i1 = swing_lows[y]

            gap = i2 - i1

            if gap <= 0:
                continue

            if gap > MAX_SWING_GAP:
                break

            price1 = float(
                df["Low"].iloc[i1]
            )

            price2 = float(
                df["Low"].iloc[i2]
            )

            rsi1 = float(
                df["RSI"].iloc[i1]
            )

            rsi2 = float(
                df["RSI"].iloc[i2]
            )

            if np.isnan(rsi1) or np.isnan(rsi2):
                continue

            price_lower_low_pct = (
                (price1 - price2)
                / price1
            ) * 100

            rsi_improvement = (
                rsi2 - rsi1
            )

            if (
                price_lower_low_pct
                < MIN_PRICE_LOWER_LOW_PCT
            ):
                continue

            if (
                rsi_improvement
                < MIN_RSI_HIGHER_LOW
            ):
                continue

            candidates.append({
                "i1": i1,
                "i2": i2,
                "price1": price1,
                "price2": price2,
                "rsi1": rsi1,
                "rsi2": rsi2,
                "price_lower_low_pct":
                    price_lower_low_pct,
                "rsi_improvement":
                    rsi_improvement,
                "date1":
                    df.index[i1],
                "date2":
                    df.index[i2],
            })

    return candidates


# ============================================================
# PICK BEST VALID DIVERGENCE
# ============================================================

def select_best_divergence(
    df,
    candidates
):

    if not candidates:
        return None

    latest_date = pd.Timestamp(
        df.index[-1]
    )

    valid = []

    for candidate in candidates:

        signal_date = pd.Timestamp(
            candidate["date2"]
        )

        age = (
            latest_date - signal_date
        ).days

        if age < 0:
            continue

        if age > MAX_SIGNAL_AGE:
            continue

        # Quality score for choosing the best pair
        rsi_score = min(
            candidate["rsi_improvement"],
            15
        ) * 2

        price_score = min(
            candidate["price_lower_low_pct"],
            10
        ) * 2

        freshness_score = max(
            0,
            30 - age
        )

        pair_score = (
            rsi_score
            + price_score
            + freshness_score
        )

        valid.append(
            (
                pair_score,
                candidate,
                age
            )
        )

    if not valid:
        return None

    valid.sort(
        key=lambda x: (
            -x[0],
            x[2]
        )
    )

    best = valid[0][1]

    return best


# ============================================================
# DIVERGENCE STRENGTH
# ============================================================

def get_divergence_strength(
    price_lower_low_pct,
    rsi_improvement
):

    if (
        price_lower_low_pct >= 3
        and
        rsi_improvement >= 8
    ):
        return "VERY STRONG"

    if (
        price_lower_low_pct >= 2
        and
        rsi_improvement >= 5
    ):
        return "STRONG"

    if (
        price_lower_low_pct >= 1
        and
        rsi_improvement >= 3
    ):
        return "GOOD"

    return "MEDIUM"


# ============================================================
# SCORE
# ============================================================

def calculate_score(
    price_lower_low_pct,
    rsi_improvement,
    current_rsi,
    volume_ratio,
    close,
    ema20,
    ema50,
    days_since_signal
):

    score = 0

    # RSI improvement
    if rsi_improvement >= 10:
        score += 25
    elif rsi_improvement >= 7:
        score += 20
    elif rsi_improvement >= 5:
        score += 15
    elif rsi_improvement >= 3:
        score += 10
    else:
        score += 5

    # Price lower low
    if price_lower_low_pct >= 5:
        score += 20
    elif price_lower_low_pct >= 3:
        score += 15
    elif price_lower_low_pct >= 2:
        score += 12
    elif price_lower_low_pct >= 1:
        score += 8
    else:
        score += 5

    # Current RSI
    if 35 <= current_rsi <= 50:
        score += 15
    elif 30 <= current_rsi < 35:
        score += 12
    elif 50 < current_rsi <= 60:
        score += 10
    else:
        score += 5

    # Volume
    if volume_ratio >= 1.5:
        score += 15
    elif volume_ratio >= 1.2:
        score += 12
    elif volume_ratio >= 1:
        score += 9
    elif volume_ratio >= 0.8:
        score += 6
    elif volume_ratio >= 0.6:
        score += 4
    else:
        score += 2

    # Trend
    if close > ema20 and ema20 > ema50:
        score += 15
    elif close > ema20:
        score += 10
    elif close > ema50:
        score += 7
    else:
        score += 3

    # Freshness
    if days_since_signal <= 3:
        score += 10
    elif days_since_signal <= 7:
        score += 8
    elif days_since_signal <= 15:
        score += 6
    elif days_since_signal <= 22:
        score += 4
    else:
        score += 2

    return min(
        score,
        100
    )


# ============================================================
# LOAD NIFTY200
# ============================================================

def load_nifty200(sh):

    ws = sh.worksheet(
        NIFTY_SHEET
    )

    data = ws.get_all_records()

    df = pd.DataFrame(data)

    if df.empty:
        raise ValueError(
            "NIFTY200 sheet is empty."
        )

    possible_code_columns = [
        "NSE Code",
        "Symbol",
        "SYMBOL",
        "Code",
        "Ticker"
    ]

    code_column = None

    for col in possible_code_columns:

        if col in df.columns:
            code_column = col
            break

    if code_column is None:
        raise ValueError(
            "NSE Code/Symbol column not found "
            "in NIFTY200 sheet."
        )

    df["NSE Code"] = (
        df[code_column]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    if "Turnover" in df.columns:

        df["Turnover"] = pd.to_numeric(
            df["Turnover"],
            errors="coerce"
        ).fillna(0)

    else:

        df["Turnover"] = 0

    df = df[
        df["NSE Code"].notna()
        &
        (df["NSE Code"] != "")
        &
        (df["NSE Code"] != "NAN")
    ]

    df["Turnover Rank"] = (
        df["Turnover"]
        .rank(
            ascending=False,
            method="min"
        )
        .astype(int)
    )

    return df[
        [
            "NSE Code",
            "Turnover Rank",
            "Turnover"
        ]
    ].drop_duplicates(
        subset=["NSE Code"]
    )


# ============================================================
# DOWNLOAD STOCK DATA
# ============================================================

def download_stock_data(symbol):

    ticker = symbol + ".NS"

    try:

        df = yf.download(
            ticker,
            period=HISTORY_PERIOD,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False
        )

    except Exception:

        return None

    if df is None or df.empty:
        return None

    if isinstance(
        df.columns,
        pd.MultiIndex
    ):

        try:

            df.columns = (
                df.columns
                .get_level_values(0)
            )

        except Exception:

            return None

    required = [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume"
    ]

    for col in required:

        if col not in df.columns:
            return None

    df = df[
        required
    ].copy()

    for col in required:

        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    df = df.dropna()

    if len(df) < MIN_HISTORY_ROWS:
        return None

    return df


# ============================================================
# ANALYZE STOCK
# ============================================================

def analyze_stock(
    symbol,
    turnover_rank,
    turnover,
    debug
):

    debug["Data Attempted"] += 1

    df = download_stock_data(
        symbol
    )

    if df is None:

        debug["Data Failed"] += 1

        return None

    debug["Data Passed"] += 1

    df["RSI"] = calculate_rsi(
        df["Close"],
        RSI_LENGTH
    )

    df["ATR"] = calculate_atr(
        df,
        ATR_LENGTH
    )

    df["EMA20"] = (
        df["Close"]
        .ewm(
            span=20,
            adjust=False
        )
        .mean()
    )

    df["EMA50"] = (
        df["Close"]
        .ewm(
            span=50,
            adjust=False
        )
        .mean()
    )

    df["AvgVolume"] = (
        df["Volume"]
        .rolling(
            VOLUME_LENGTH
        )
        .mean()
    )

    df["VolumeRatio"] = (
        df["Volume"]
        /
        df["AvgVolume"]
    )

    candidates = find_all_positive_divergences(
        df
    )

    debug["Divergence Pairs Found"] += len(
        candidates
    )

    if not candidates:

        debug["No Divergence"] += 1

        return None

    divergence = select_best_divergence(
        df,
        candidates
    )

    if divergence is None:

        debug["Signal Too Old"] += 1

        return None

    debug["Fresh Divergence"] += 1

    last = df.iloc[-1]

    close = float(
        last["Close"]
    )

    current_rsi = float(
        last["RSI"]
    )

    atr = float(
        last["ATR"]
    )

    ema20 = float(
        last["EMA20"]
    )

    ema50 = float(
        last["EMA50"]
    )

    volume_ratio = float(
        last["VolumeRatio"]
    )

    if np.isnan(current_rsi):

        debug["Invalid RSI"] += 1

        return None

    if np.isnan(atr) or atr <= 0:

        debug["Invalid ATR"] += 1

        return None

    if np.isnan(volume_ratio):

        volume_ratio = 0

    # Volume is now a soft-enough V1.2 filter
    if volume_ratio < MIN_VOLUME_RATIO:

        debug["Volume Failed"] += 1

        return None

    debug["Volume Passed"] += 1

    signal_date = pd.Timestamp(
        divergence["date2"]
    )

    latest_date = pd.Timestamp(
        df.index[-1]
    )

    days_since_signal = (
        latest_date - signal_date
    ).days

    if days_since_signal < 0:

        debug["Invalid Signal Date"] += 1

        return None

    if days_since_signal > MAX_SIGNAL_AGE:

        debug["Signal Too Old"] += 1

        return None

    price_lower_low_pct = float(
        divergence[
            "price_lower_low_pct"
        ]
    )

    rsi_improvement = float(
        divergence[
            "rsi_improvement"
        ]
    )

    if (
        price_lower_low_pct >= 2
        and
        rsi_improvement >= 5
    ):

        setup = (
            "CLASSIC POSITIVE DIVERGENCE"
        )

    else:

        setup = (
            "RSI POSITIVE DIVERGENCE"
        )

    strength = get_divergence_strength(
        price_lower_low_pct,
        rsi_improvement
    )

    score = calculate_score(
        price_lower_low_pct,
        rsi_improvement,
        current_rsi,
        volume_ratio,
        close,
        ema20,
        ema50,
        days_since_signal
    )

    recent_lows = (
        df["Low"]
        .tail(10)
        .min()
    )

    divergence_support = min(
        divergence["price1"],
        divergence["price2"]
    )

    support = min(
        float(recent_lows),
        float(divergence_support)
    )

    entry = close

    atr_stop = (
        entry
        -
        (1.5 * atr)
    )

    support_stop = (
        support * 0.995
    )

    stop_loss = max(
        atr_stop,
        support_stop
    )

    if stop_loss >= entry:

        stop_loss = entry - atr

    risk = (
        entry - stop_loss
    )

    if risk <= 0:

        debug["Invalid Risk"] += 1

        return None

    risk_pct = (
        risk / entry
    ) * 100

    if risk_pct > MAX_RISK_PCT:

        debug["Risk Failed"] += 1

        return None

    debug["Risk Passed"] += 1

    target1 = (
        entry
        +
        risk * TARGET1_R
    )

    target2 = (
        entry
        +
        risk * TARGET2_R
    )

    if len(df) >= 2:

        previous_close = float(
            df["Close"].iloc[-2]
        )

        if previous_close != 0:

            today_change = (
                (close - previous_close)
                /
                previous_close
            ) * 100

        else:

            today_change = 0

    else:

        today_change = 0

    chart_url = (
        "https://www.tradingview.com/chart/"
        "?symbol=NSE%3A"
        + symbol
    )

    debug["Final Candidates"] += 1

    return {

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

        "Today Change %": round(
            today_change,
            2
        ),

        "Setup": setup,

        "Divergence Strength": strength,

        "Strength Score": round(
            score,
            2
        ),

        "Price Low 1": round(
            divergence["price1"],
            2
        ),

        "Price Low 2": round(
            divergence["price2"],
            2
        ),

        "RSI Low 1": round(
            divergence["rsi1"],
            2
        ),

        "RSI Low 2": round(
            divergence["rsi2"],
            2
        ),

        "RSI14": round(
            current_rsi,
            2
        ),

        "RSI Improvement": round(
            rsi_improvement,
            2
        ),

        "Volume Ratio": round(
            volume_ratio,
            2
        ),

        "EMA20": round(
            ema20,
            2
        ),

        "EMA50": round(
            ema50,
            2
        ),

        "ATR14": round(
            atr,
            2
        ),

        "Support": round(
            support,
            2
        ),

        "Entry": round(
            entry,
            2
        ),

        "Stop Loss": round(
            stop_loss,
            2
        ),

        "Target 1": round(
            target1,
            2
        ),

        "Target 2": round(
            target2,
            2
        ),

        "Risk %": round(
            risk_pct,
            2
        ),

        "Signal Date": signal_date.strftime(
            "%Y-%m-%d"
        ),

        "Days Since Signal": int(
            days_since_signal
        ),

        "Chart": chart_url,
    }


# ============================================================
# EXCEL COLUMN LETTER TO ZERO-BASED INDEX
# ============================================================

def column_letter_to_index(letter):

    col_index = 0

    for ch in letter.upper():

        col_index = (
            col_index * 26
            +
            ord(ch)
            -
            ord("A")
            +
            1
        )

    return col_index - 1


# ============================================================
# WRITE FINAL SHEET
# ============================================================

def write_final_sheet(
    ws,
    results
):

    try:
        ws.clear_basic_filter()
    except Exception:
        pass

    ws.clear()

    values = [
        OUTPUT_COLUMNS
    ]

    for item in results:

        values.append([
            item.get(
                col,
                ""
            )
            for col in OUTPUT_COLUMNS
        ])

    last_row = len(values)
    last_col = "AA"

    ws.update(
        range_name=f"A1:{last_col}{last_row}",
        values=values,
        value_input_option="USER_ENTERED"
    )

    # Header
    ws.format(
        f"A1:{last_col}1",
        {
            "backgroundColor": {
                "red": 0.12,
                "green": 0.18,
                "blue": 0.28
            },
            "textFormat": {
                "foregroundColor": {
                    "red": 1,
                    "green": 1,
                    "blue": 1
                },
                "bold": True,
                "fontSize": 10
            },
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE"
        }
    )

    # General
    if last_row >= 2:

        ws.format(
            f"A2:{last_col}{last_row}",
            {
                "textFormat": {
                    "fontSize": 10
                },
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE"
            }
        )

    # Integer
    for col in [
        "B",
        "Z"
    ]:

        if last_row >= 2:

            ws.format(
                f"{col}2:{col}{last_row}",
                {
                    "numberFormat": {
                        "type": "NUMBER",
                        "pattern": "0"
                    }
                }
            )

    # Turnover
    if last_row >= 2:

        ws.format(
            f"C2:C{last_row}",
            {
                "numberFormat": {
                    "type": "NUMBER",
                    "pattern": "#,##0"
                }
            }
        )

    # Decimal columns
    decimal_columns = [
        "D",
        "E",
        "H",
        "I",
        "J",
        "K",
        "L",
        "M",
        "N",
        "O",
        "P",
        "Q",
        "R",
        "S",
        "T",
        "U",
        "V",
        "W",
        "X"
    ]

    for col in decimal_columns:

        if last_row >= 2:

            ws.format(
                f"{col}2:{col}{last_row}",
                {
                    "numberFormat": {
                        "type": "NUMBER",
                        "pattern": "0.00"
                    }
                }
            )

    # Trading levels
    if last_row >= 2:

        ws.format(
            f"T2:X{last_row}",
            {
                "numberFormat": {
                    "type": "NUMBER",
                    "pattern": "0.00"
                }
            }
        )

    # Signal Date as text
    if last_row >= 2:

        ws.format(
            f"Y2:Y{last_row}",
            {
                "numberFormat": {
                    "type": "TEXT",
                    "pattern": "@"
                }
            }
        )

    # Chart hyperlinks
    if results:

        chart_formulas = []

        for item in results:

            url = item["Chart"]

            formula = (
                '=HYPERLINK("'
                +
                url
                +
                '","📈 Chart")'
            )

            chart_formulas.append([
                formula
            ])

        ws.update(
            range_name=f"AA2:AA{last_row}",
            values=chart_formulas,
            value_input_option="USER_ENTERED"
        )

    # Row colors
    for row_num, item in enumerate(
        results,
        start=2
    ):

        if (
            item["Setup"]
            ==
            "CLASSIC POSITIVE DIVERGENCE"
        ):

            row_color = {
                "red": 0.84,
                "green": 0.92,
                "blue": 1.00
            }

        else:

            row_color = {
                "red": 0.84,
                "green": 1.00,
                "blue": 0.86
            }

        ws.format(
            f"A{row_num}:AA{row_num}",
            {
                "backgroundColor": row_color
            }
        )

    # Score highlight
    for row_num, item in enumerate(
        results,
        start=2
    ):

        score = float(
            item["Strength Score"]
        )

        if score >= 75:

            ws.format(
                f"H{row_num}",
                {
                    "backgroundColor": {
                        "red": 0.55,
                        "green": 0.90,
                        "blue": 0.55
                    },
                    "textFormat": {
                        "bold": True
                    }
                }
            )

        elif score >= 65:

            ws.format(
                f"H{row_num}",
                {
                    "backgroundColor": {
                        "red": 0.75,
                        "green": 0.95,
                        "blue": 0.65
                    },
                    "textFormat": {
                        "bold": True
                    }
                }
            )

    # Freeze
    try:
        ws.freeze(
            rows=1
        )
    except Exception:
        pass

    # Filter
    try:

        ws.set_basic_filter(
            f"A1:{last_col}{max(last_row, 2)}"
        )

    except Exception:
        pass

    # Widths
    widths = {
        "A": 110,
        "B": 80,
        "C": 120,
        "D": 85,
        "E": 95,
        "F": 190,
        "G": 110,
        "H": 95,
        "I": 90,
        "J": 90,
        "K": 80,
        "L": 80,
        "M": 70,
        "N": 105,
        "O": 90,
        "P": 90,
        "Q": 90,
        "R": 80,
        "S": 90,
        "T": 85,
        "U": 90,
        "V": 90,
        "W": 90,
        "X": 80,
        "Y": 100,
        "Z": 100,
        "AA": 90
    }

    requests = []

    for letter, width in widths.items():

        col_index = column_letter_to_index(
            letter
        )

        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": ws.id,
                    "dimension": "COLUMNS",
                    "startIndex": col_index,
                    "endIndex": col_index + 1
                },
                "properties": {
                    "pixelSize": width
                },
                "fields": "pixelSize"
            }
        })

    try:

        ws.spreadsheet.batch_update({
            "requests": requests
        })

    except Exception as e:

        print(
            f"Column width warning: {e}"
        )

    print(
        f"Final List updated: {len(results)} stocks"
    )


# ============================================================
# WRITE DEBUG SHEET
# ============================================================

def write_debug_sheet(
    sh,
    debug,
    total_universe,
    results
):

    try:

        ws = sh.worksheet(
            DEBUG_SHEET
        )

    except Exception:

        ws = sh.add_worksheet(
            title=DEBUG_SHEET,
            rows=50,
            cols=5
        )

    try:
        ws.clear_basic_filter()
    except Exception:
        pass

    ws.clear()

    final_count = len(results)

    rows = [
        [
            "NIFTY 200 POSITIVE DIVERGENCE SCANNER V1.2",
            "",
            "",
            "",
        ],
        [
            "Metric",
            "Count",
            "Percentage",
            "Meaning"
        ],
        [
            "NIFTY200 Universe",
            total_universe,
            100,
            "Stocks loaded from NIFTY200"
        ],
        [
            "Data Attempted",
            debug["Data Attempted"],
            "",
            "Yahoo Finance requests"
        ],
        [
            "Data Passed",
            debug["Data Passed"],
            "",
            "Valid OHLCV history"
        ],
        [
            "Data Failed",
            debug["Data Failed"],
            "",
            "Yahoo data unavailable/invalid"
        ],
        [
            "Divergence Pairs Found",
            debug["Divergence Pairs Found"],
            "",
            "All valid swing-low divergence pairs"
        ],
        [
            "Fresh Divergence",
            debug["Fresh Divergence"],
            "",
            f"Signal age <= {MAX_SIGNAL_AGE} days"
        ],
        [
            "Signal Too Old",
            debug["Signal Too Old"],
            "",
            f"Signal age > {MAX_SIGNAL_AGE} days"
        ],
        [
            "No Divergence",
            debug["No Divergence"],
            "",
            "No valid positive divergence"
        ],
        [
            "Volume Passed",
            debug["Volume Passed"],
            "",
            f"Volume ratio >= {MIN_VOLUME_RATIO}"
        ],
        [
            "Volume Failed",
            debug["Volume Failed"],
            "",
            f"Volume ratio < {MIN_VOLUME_RATIO}"
        ],
        [
            "Invalid RSI",
            debug["Invalid RSI"],
            "",
            "RSI unavailable"
        ],
        [
            "Invalid ATR",
            debug["Invalid ATR"],
            "",
            "ATR unavailable"
        ],
        [
            "Invalid Risk",
            debug["Invalid Risk"],
            "",
            "Risk calculation invalid"
        ],
        [
            "Risk Passed",
            debug["Risk Passed"],
            "",
            f"Risk <= {MAX_RISK_PCT}%"
        ],
        [
            "Risk Failed",
            debug["Risk Failed"],
            "",
            f"Risk > {MAX_RISK_PCT}%"
        ],
        [
            "Final Candidates",
            debug["Final Candidates"],
            "",
            "Passed all filters before ranking"
        ],
        [
            "Final List",
            final_count,
            "",
            f"Top {MAX_FINAL_STOCKS} by score"
        ],
    ]

    # Fill percentages
    for i in range(
        2,
        len(rows)
    ):

        count = rows[i][1]

        if (
            isinstance(count, (int, float))
            and
            total_universe > 0
        ):

            rows[i][2] = round(
                (
                    count
                    /
                    total_universe
                ) * 100,
                2
            )

    ws.update(
        range_name=f"A1:D{len(rows)}",
        values=rows,
        value_input_option="USER_ENTERED"
    )

    ws.format(
        "A1:D1",
        {
            "backgroundColor": {
                "red": 0.12,
                "green": 0.18,
                "blue": 0.28
            },
            "textFormat": {
                "foregroundColor": {
                    "red": 1,
                    "green": 1,
                    "blue": 1
                },
                "bold": True,
                "fontSize": 12
            }
        }
    )

    ws.format(
        "A2:D2",
        {
            "backgroundColor": {
                "red": 0.80,
                "green": 0.85,
                "blue": 0.92
            },
            "textFormat": {
                "bold": True
            }
        }
    )

    if len(rows) >= 3:

        ws.format(
            f"B3:C{len(rows)}",
            {
                "numberFormat": {
                    "type": "NUMBER",
                    "pattern": "0.00"
                }
            }
        )

    try:
        ws.freeze(rows=2)
    except Exception:
        pass

    try:

        ws.set_basic_filter(
            f"A2:D{len(rows)}"
        )

    except Exception:
        pass

    debug_widths = {
        "A": 220,
        "B": 100,
        "C": 100,
        "D": 320
    }

    requests = []

    for letter, width in debug_widths.items():

        col_index = column_letter_to_index(
            letter
        )

        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": ws.id,
                    "dimension": "COLUMNS",
                    "startIndex": col_index,
                    "endIndex": col_index + 1
                },
                "properties": {
                    "pixelSize": width
                },
                "fields": "pixelSize"
            }
        })

    try:

        ws.spreadsheet.batch_update({
            "requests": requests
        })

    except Exception:
        pass

    print(
        f"Scanner Debug updated: {len(rows) - 2} metrics"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print(
        "NIFTY 200 POSITIVE DIVERGENCE SCANNER V1.2"
    )
    print(
        "MORE SIGNALS + DEBUG COUNT"
    )
    print("=" * 70)

    print(
        f"Signal Age Filter : <= {MAX_SIGNAL_AGE} days"
    )

    print(
        f"Volume Filter     : >= {MIN_VOLUME_RATIO}"
    )

    print(
        f"Risk Filter       : <= {MAX_RISK_PCT}%"
    )

    sh = connect_google_sheet()

    print(
        "Google Sheet connected."
    )

    universe = load_nifty200(
        sh
    )

    total = len(
        universe
    )

    print(
        f"NIFTY200 stocks found: {total}"
    )

    final_ws = sh.worksheet(
        FINAL_SHEET
    )

    debug = {
        "Data Attempted": 0,
        "Data Failed": 0,
        "Data Passed": 0,
        "Divergence Pairs Found": 0,
        "Fresh Divergence": 0,
        "Signal Too Old": 0,
        "No Divergence": 0,
        "Volume Passed": 0,
        "Volume Failed": 0,
        "Invalid RSI": 0,
        "Invalid ATR": 0,
        "Invalid Signal Date": 0,
        "Invalid Risk": 0,
        "Risk Passed": 0,
        "Risk Failed": 0,
        "Final Candidates": 0,
    }

    results = []

    for counter, row in enumerate(
        universe.itertuples(
            index=False
        ),
        start=1
    ):

        symbol = row[0]
        turnover_rank = row[1]
        turnover = row[2]

        print(
            f"[{counter}/{total}] {symbol}"
        )

        try:

            result = analyze_stock(
                symbol,
                turnover_rank,
                turnover,
                debug
            )

            if result is not None:

                results.append(
                    result
                )

                print(
                    "   -> "
                    f"{result['Setup']} "
                    f"| {result['Divergence Strength']} "
                    f"| Score "
                    f"{result['Strength Score']} "
                    f"| Age "
                    f"{result['Days Since Signal']}d"
                )

        except Exception as e:

            debug["Data Failed"] += 1

            print(
                f"   ERROR: {symbol} -> {e}"
            )

        if REQUEST_DELAY_SECONDS > 0:

            time.sleep(
                REQUEST_DELAY_SECONDS
            )

    # ========================================================
    # SORT
    # ========================================================

    if results:

        results = sorted(
            results,
            key=lambda x: (
                -float(
                    x["Strength Score"]
                ),
                int(
                    x["Days Since Signal"]
                ),
                int(
                    x["Turnover Rank"]
                )
            )
        )

        results = results[
            :MAX_FINAL_STOCKS
        ]

    # ========================================================
    # WRITE FINAL LIST
    # ========================================================

    write_final_sheet(
        final_ws,
        results
    )

    # ========================================================
    # WRITE DEBUG
    # ========================================================

    write_debug_sheet(
        sh,
        debug,
        total,
        results
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    classic_count = sum(
        1
        for x in results
        if x["Setup"]
        ==
        "CLASSIC POSITIVE DIVERGENCE"
    )

    rsi_count = sum(
        1
        for x in results
        if x["Setup"]
        ==
        "RSI POSITIVE DIVERGENCE"
    )

    print()
    print("=" * 70)
    print(
        "SCAN COMPLETE - V1.2"
    )
    print("=" * 70)

    print(
        f"Universe              : {total}"
    )

    print(
        f"Data Passed           : "
        f"{debug['Data Passed']}"
    )

    print(
        f"Divergence Pairs      : "
        f"{debug['Divergence Pairs Found']}"
    )

    print(
        f"Fresh Divergence      : "
        f"{debug['Fresh Divergence']}"
    )

    print(
        f"Volume Passed         : "
        f"{debug['Volume Passed']}"
    )

    print(
        f"Risk Passed           : "
        f"{debug['Risk Passed']}"
    )

    print(
        f"Final Candidates      : "
        f"{debug['Final Candidates']}"
    )

    print(
        f"Final List            : "
        f"{len(results)}"
    )

    print(
        f"Classic Divergence    : "
        f"{classic_count}"
    )

    print(
        f"RSI Divergence        : "
        f"{rsi_count}"
    )

    print("=" * 70)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
