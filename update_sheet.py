# ============================================================
# NIFTY 200 POSITIVE DIVERGENCE SCANNER V1.0
# ============================================================
#
# FINAL LIST:
#   1. RSI POSITIVE DIVERGENCE
#   2. CLASSIC POSITIVE DIVERGENCE
#
# OLD BREAKOUT / RETEST LOGIC REMOVED
#
# DATA:
#   - NIFTY200 Google Sheet
#   - Yahoo Finance daily OHLCV
#
# ============================================================

import gspread
import numpy as np
import pandas as pd
import yfinance as yf

from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta


# ============================================================
# SETTINGS
# ============================================================

SPREADSHEET_ID = "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E"

NIFTY_SHEET = "NIFTY200"
FINAL_SHEET = "Final List"

HISTORY_PERIOD = "1y"
MIN_HISTORY_ROWS = 100

RSI_LENGTH = 14
ATR_LENGTH = 14
VOLUME_LENGTH = 20

# Swing low detection
SWING_LEFT = 3
SWING_RIGHT = 3

# Divergence filters
MIN_PRICE_LOWER_LOW_PCT = 0.50
MIN_RSI_HIGHER_LOW = 2.0

# Maximum distance between two swing lows
MAX_SWING_GAP = 60

# Signal freshness
MAX_SIGNAL_AGE = 15

# Volume
MIN_VOLUME_RATIO = 0.80

# Risk
MAX_RISK_PCT = 7.0

# Targets
TARGET1_R = 1.5
TARGET2_R = 3.0

# Maximum stocks in Final List
MAX_FINAL_STOCKS = 30


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
    "RSI Improvement %",
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

    # --------------------------------------------------------
    # IMPORTANT:
    # Apni existing credentials JSON ka naam/path yahan rakho
    # --------------------------------------------------------

    creds = ServiceAccountCredentials.from_json_keyfile_name(
        "credentials.json",
        scope
    )

    client = gspread.authorize(creds)

    sh = client.open_by_key(SPREADSHEET_ID)

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

    rs = avg_gain / avg_loss.replace(0, np.nan)

    rsi = 100 - (100 / (1 + rs))

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

def find_swing_lows(series, left=3, right=3):

    swing_lows = []

    values = series.values

    for i in range(left, len(series) - right):

        current = values[i]

        left_values = values[i-left:i]
        right_values = values[i+1:i+right+1]

        if (
            current < np.min(left_values)
            and
            current <= np.min(right_values)
        ):
            swing_lows.append(i)

    return swing_lows


# ============================================================
# GET DIVERGENCE
# ============================================================

def detect_positive_divergence(df):

    if len(df) < 100:
        return None

    swing_lows = find_swing_lows(
        df["Low"],
        SWING_LEFT,
        SWING_RIGHT
    )

    if len(swing_lows) < 2:
        return None

    # Search latest valid pair first
    for x in range(len(swing_lows) - 1, 0, -1):

        i2 = swing_lows[x]

        for y in range(x - 1, -1, -1):

            i1 = swing_lows[y]

            gap = i2 - i1

            if gap <= 0:
                continue

            if gap > MAX_SWING_GAP:
                break

            price1 = float(df["Low"].iloc[i1])
            price2 = float(df["Low"].iloc[i2])

            rsi1 = float(df["RSI"].iloc[i1])
            rsi2 = float(df["RSI"].iloc[i2])

            if np.isnan(rsi1) or np.isnan(rsi2):
                continue

            # Price must make lower low
            price_lower_low_pct = (
                (price1 - price2) / price1
            ) * 100

            # RSI must make higher low
            rsi_improvement = rsi2 - rsi1

            if price_lower_low_pct < MIN_PRICE_LOWER_LOW_PCT:
                continue

            if rsi_improvement < MIN_RSI_HIGHER_LOW:
                continue

            return {
                "i1": i1,
                "i2": i2,
                "price1": price1,
                "price2": price2,
                "rsi1": rsi1,
                "rsi2": rsi2,
                "price_lower_low_pct": price_lower_low_pct,
                "rsi_improvement": rsi_improvement,
                "date1": df.index[i1],
                "date2": df.index[i2],
            }

    return None


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

    # --------------------------------------------------------
    # RSI improvement
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Price lower low
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Current RSI
    # --------------------------------------------------------

    if 35 <= current_rsi <= 50:
        score += 15

    elif 30 <= current_rsi < 35:
        score += 12

    elif 50 < current_rsi <= 60:
        score += 10

    else:
        score += 5

    # --------------------------------------------------------
    # Volume
    # --------------------------------------------------------

    if volume_ratio >= 1.5:
        score += 15

    elif volume_ratio >= 1.2:
        score += 12

    elif volume_ratio >= 1:
        score += 9

    elif volume_ratio >= 0.8:
        score += 6

    else:
        score += 2

    # --------------------------------------------------------
    # Trend
    # --------------------------------------------------------

    if close > ema20 and ema20 > ema50:
        score += 15

    elif close > ema20:
        score += 10

    elif close > ema50:
        score += 7

    else:
        score += 3

    # --------------------------------------------------------
    # Freshness
    # --------------------------------------------------------

    if days_since_signal <= 3:
        score += 10

    elif days_since_signal <= 7:
        score += 8

    elif days_since_signal <= 10:
        score += 6

    else:
        score += 3

    return min(score, 100)


# ============================================================
# LOAD NIFTY200
# ============================================================

def load_nifty200(sh):

    ws = sh.worksheet(NIFTY_SHEET)

    data = ws.get_all_records()

    df = pd.DataFrame(data)

    if df.empty:
        raise ValueError("NIFTY200 sheet is empty.")

    # --------------------------------------------------------
    # Find NSE Code column
    # --------------------------------------------------------

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
            "NSE Code/Symbol column not found in NIFTY200 sheet."
        )

    df["NSE Code"] = (
        df[code_column]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    # --------------------------------------------------------
    # Turnover
    # --------------------------------------------------------

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
    ]

    # --------------------------------------------------------
    # Turnover Rank
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Handle Yahoo multi-index
    # --------------------------------------------------------

    if isinstance(df.columns, pd.MultiIndex):

        try:
            df.columns = df.columns.get_level_values(0)
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

    df = df[required].copy()

    # --------------------------------------------------------
    # Convert numeric
    # --------------------------------------------------------

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
    turnover
):

    df = download_stock_data(symbol)

    if df is None:
        return None

    # --------------------------------------------------------
    # Indicators
    # --------------------------------------------------------

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
        .rolling(VOLUME_LENGTH)
        .mean()
    )

    df["VolumeRatio"] = (
        df["Volume"] /
        df["AvgVolume"]
    )

    # --------------------------------------------------------
    # Divergence
    # --------------------------------------------------------

    divergence = detect_positive_divergence(df)

    if divergence is None:
        return None

    # --------------------------------------------------------
    # Latest data
    # --------------------------------------------------------

    last = df.iloc[-1]

    close = float(last["Close"])
    current_rsi = float(last["RSI"])
    atr = float(last["ATR"])
    ema20 = float(last["EMA20"])
    ema50 = float(last["EMA50"])
    volume_ratio = float(last["VolumeRatio"])

    if np.isnan(current_rsi):
        return None

    if np.isnan(atr) or atr <= 0:
        return None

    if np.isnan(volume_ratio):
        volume_ratio = 0

    # --------------------------------------------------------
    # Signal age
    # --------------------------------------------------------

    signal_date = pd.Timestamp(
        divergence["date2"]
    )

    latest_date = pd.Timestamp(
        df.index[-1]
    )

    days_since_signal = (
        latest_date - signal_date
    ).days

    if days_since_signal > MAX_SIGNAL_AGE:
        return None

    if days_since_signal < 0:
        return None

    # --------------------------------------------------------
    # Volume filter
    # --------------------------------------------------------

    if volume_ratio < MIN_VOLUME_RATIO:
        return None

    # --------------------------------------------------------
    # Divergence metrics
    # --------------------------------------------------------

    price_lower_low_pct = (
        divergence["price_lower_low_pct"]
    )

    rsi_improvement = (
        divergence["rsi_improvement"]
    )

    # --------------------------------------------------------
    # Setup classification
    # --------------------------------------------------------

    if (
        price_lower_low_pct >= 2
        and
        rsi_improvement >= 5
    ):

        setup = "CLASSIC POSITIVE DIVERGENCE"

    else:

        setup = "RSI POSITIVE DIVERGENCE"

    # --------------------------------------------------------
    # Strength
    # --------------------------------------------------------

    strength = get_divergence_strength(
        price_lower_low_pct,
        rsi_improvement
    )

    # --------------------------------------------------------
    # Score
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Support
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Entry
    # --------------------------------------------------------

    entry = close

    # --------------------------------------------------------
    # Stop loss
    #
    # ATR based + support based
    # --------------------------------------------------------

    atr_stop = entry - (1.5 * atr)

    support_stop = support * 0.995

    stop_loss = max(
        atr_stop,
        support_stop
    )

    # Make sure SL remains below entry
    if stop_loss >= entry:

        stop_loss = entry - atr

    risk = entry - stop_loss

    if risk <= 0:
        return None

    risk_pct = (
        risk / entry
    ) * 100

    # --------------------------------------------------------
    # Maximum risk filter
    # --------------------------------------------------------

    if risk_pct > MAX_RISK_PCT:
        return None

    # --------------------------------------------------------
    # Targets
    # --------------------------------------------------------

    target1 = entry + (
        risk * TARGET1_R
    )

    target2 = entry + (
        risk * TARGET2_R
    )

    # --------------------------------------------------------
    # Today's change
    # --------------------------------------------------------

    if len(df) >= 2:

        previous_close = float(
            df["Close"].iloc[-2]
        )

        today_change = (
            (close - previous_close)
            /
            previous_close
        ) * 100

    else:

        today_change = 0

    # --------------------------------------------------------
    # Chart
    # --------------------------------------------------------

    chart_url = (
        "https://www.tradingview.com/chart/"
        "?symbol=NSE%3A"
        + symbol
    )

    # --------------------------------------------------------
    # Return
    # --------------------------------------------------------

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

        "RSI Improvement %": round(
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

        # STRING deliberately
        "Signal Date": signal_date.strftime(
            "%Y-%m-%d"
        ),

        "Days Since Signal": int(
            days_since_signal
        ),

        "Chart": chart_url,
    }


# ============================================================
# WRITE FINAL SHEET
# ============================================================

def write_final_sheet(
    ws,
    results
):

    # --------------------------------------------------------
    # Clear old values
    # --------------------------------------------------------

    ws.clear()

    # --------------------------------------------------------
    # Prepare data
    # --------------------------------------------------------

    values = [
        OUTPUT_COLUMNS
    ]

    for item in results:

        values.append([
            item.get(col, "")
            for col in OUTPUT_COLUMNS
        ])

    last_row = len(values)
    last_col = "AA"

    # --------------------------------------------------------
    # Write values
    # --------------------------------------------------------

    ws.update(
        f"A1:{last_col}{last_row}",
        values,
        value_input_option="USER_ENTERED"
    )

    # ========================================================
    # HEADER
    # ========================================================

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

    # ========================================================
    # GENERAL FORMATTING
    # ========================================================

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

    # ========================================================
    # NUMBER FORMATS
    # ========================================================

    # Integer columns
    integer_columns = [
        "B",
        "Z"
    ]

    for col in integer_columns:

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

    # --------------------------------------------------------
    # Signal Date = TEXT
    # Prevent 1900/1901 date conversion
    # --------------------------------------------------------

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

    # ========================================================
    # CHART FORMULAS
    # ========================================================
    #
    # IMPORTANT:
    # Old code created circular reference:
    #
    # HYPERLINK(AA2, ...)
    #
    # which caused #REF!
    #
    # Now actual URL is inserted directly.
    # ========================================================

    if len(results) > 0:

        chart_formulas = []

        for item in results:

            url = item["Chart"]

            formula = (
                '=HYPERLINK("'
                + url
                + '","📈 Chart")'
            )

            chart_formulas.append([
                formula
            ])

        ws.update(
            f"AA2:AA{last_row}",
            chart_formulas,
            value_input_option="USER_ENTERED"
        )

    # ========================================================
    # ROW COLORS
    # ========================================================

    for row_num, item in enumerate(
        results,
        start=2
    ):

        setup = item["Setup"]

        if setup == "CLASSIC POSITIVE DIVERGENCE":

            # Light Blue
            row_color = {
                "red": 0.84,
                "green": 0.92,
                "blue": 1.00
            }

        else:

            # Light Green
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

    # ========================================================
    # SCORE HIGHLIGHT
    # ========================================================

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

    # ========================================================
    # FREEZE HEADER
    # ========================================================

    try:
        ws.freeze(rows=1)
    except Exception:
        pass

    # ========================================================
    # FILTER
    # ========================================================

    try:

        ws.set_basic_filter(
            f"A1:{last_col}{max(last_row, 2)}"
        )

    except Exception:
        pass

    # ========================================================
    # COLUMN WIDTHS
    # ========================================================

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

    # --------------------------------------------------------
    # Use Sheets batch update for column widths
    # --------------------------------------------------------

    requests = []

    for letter, width in widths.items():

        col_index = ord(letter) - ord("A")

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
        f"Final List updated: {len(results)} stocks"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("NIFTY 200 POSITIVE DIVERGENCE SCANNER")
    print("=" * 70)

    # --------------------------------------------------------
    # Connect
    # --------------------------------------------------------

    sh = connect_google_sheet()

    print("Google Sheet connected.")

    # --------------------------------------------------------
    # Load NIFTY200
    # --------------------------------------------------------

    universe = load_nifty200(sh)

    print(
        f"NIFTY200 stocks found: {len(universe)}"
    )

    # --------------------------------------------------------
    # Final sheet
    # --------------------------------------------------------

    final_ws = sh.worksheet(
        FINAL_SHEET
    )

    # --------------------------------------------------------
    # Scan
    # --------------------------------------------------------

    results = []

    total = len(universe)

    for counter, row in enumerate(
        universe.itertuples(index=False),
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
                turnover
            )

            if result is not None:

                results.append(result)

                print(
                    f"   -> {result['Setup']} "
                    f"| Score {result['Strength Score']}"
                )

        except Exception as e:

            print(
                f"   ERROR: {symbol} -> {e}"
            )

    # ========================================================
    # SORT
    # ========================================================

    if results:

        # First priority = score
        # Second = fresh signal
        # Third = turnover rank

        results = sorted(
            results,
            key=lambda x: (
                -float(x["Strength Score"]),
                int(x["Days Since Signal"]),
                int(x["Turnover Rank"])
            )
        )

        # ----------------------------------------------------
        # Limit
        # ----------------------------------------------------

        results = results[
            :MAX_FINAL_STOCKS
        ]

    # ========================================================
    # WRITE
    # ========================================================

    write_final_sheet(
        final_ws,
        results
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    classic_count = sum(
        1
        for x in results
        if x["Setup"]
        == "CLASSIC POSITIVE DIVERGENCE"
    )

    rsi_count = sum(
        1
        for x in results
        if x["Setup"]
        == "RSI POSITIVE DIVERGENCE"
    )

    print()
    print("=" * 70)
    print("SCAN COMPLETE")
    print("=" * 70)

    print(
        f"Total Signals : {len(results)}"
    )

    print(
        f"Classic Divergence : {classic_count}"
    )

    print(
        f"RSI Divergence : {rsi_count}"
    )

    print("=" * 70)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
