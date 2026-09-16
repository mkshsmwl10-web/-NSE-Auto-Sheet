import os
import json
import gspread
import numpy as np
import pandas as pd
import yfinance as yf

from oauth2client.service_account import ServiceAccountCredentials


# ============================================================
# NIFTY 200 POSITIVE DIVERGENCE SCANNER V1.1
# ============================================================

SPREADSHEET_ID = "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E"

NIFTY_SHEET = "NIFTY200"
FINAL_SHEET = "Final List"

HISTORY_PERIOD = "1y"
MIN_HISTORY_ROWS = 100

RSI_LENGTH = 14
ATR_LENGTH = 14
VOLUME_LENGTH = 20

SWING_LEFT = 3
SWING_RIGHT = 3

MIN_PRICE_LOWER_LOW_PCT = 0.50
MIN_RSI_HIGHER_LOW = 2.0
MAX_SWING_GAP = 60

MAX_SIGNAL_AGE = 15
MIN_VOLUME_RATIO = 0.80
MAX_RISK_PCT = 7.0

TARGET1_R = 1.5
TARGET2_R = 3.0

MAX_FINAL_STOCKS = 30


# ============================================================
# FINAL LIST COLUMNS
# A:Y = 25 COLUMNS
# ============================================================

OUTPUT_COLUMNS = [
    "NSE Code",              # A
    "Close",                 # B
    "Today Change %",        # C
    "Setup",                 # D
    "Divergence Strength",   # E
    "Strength Score",        # F
    "Price Low 1",           # G
    "Price Low 2",           # H
    "RSI Low 1",             # I
    "RSI Low 2",             # J
    "RSI14",                 # K
    "RSI Improvement",       # L
    "Volume Ratio",           # M
    "EMA20",                 # N
    "EMA50",                 # O
    "ATR14",                 # P
    "Support",                # Q
    "Entry",                  # R
    "Stop Loss",              # S
    "Target 1",               # T
    "Target 2",               # U
    "Risk %",                 # V
    "Signal Date",            # W
    "Days Since Signal",      # X
    "Chart"                   # Y
]


# ============================================================
# GOOGLE SHEETS CONNECTION
# ============================================================

def connect_google_sheet():

    credentials_json = os.environ.get("GCP_CREDENTIALS")

    if not credentials_json:
        raise RuntimeError("GCP_CREDENTIALS environment variable not found.")

    try:
        credentials_info = json.loads(credentials_json)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"GCP_CREDENTIALS contains invalid JSON: {e}"
        )

    required_keys = [
        "type",
        "project_id",
        "private_key",
        "client_email"
    ]

    missing_keys = [
        key for key in required_keys
        if key not in credentials_info
    ]

    if missing_keys:
        raise RuntimeError(
            f"GCP_CREDENTIALS missing keys: {missing_keys}"
        )

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    credentials = ServiceAccountCredentials.from_json_keyfile_dict(
        credentials_info,
        scope
    )

    client = gspread.authorize(credentials)

    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    print("Google Sheet connected successfully.")

    return spreadsheet


# ============================================================
# RSI
# ============================================================

def calculate_rsi(close, length=14):

    delta = close.diff()

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

    rs = avg_gain / avg_loss.replace(0, np.nan)

    rsi = 100 - (100 / (1 + rs))

    return rsi


# ============================================================
# ATR
# ============================================================

def calculate_atr(df, length=14):

    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    previous_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - previous_close).abs()
    tr3 = (low - previous_close).abs()

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


# ============================================================
# SWING LOW DETECTION
# ============================================================

def find_swing_lows(series, left=3, right=3):

    swing_lows = []

    values = series.values

    for i in range(left, len(series) - right):

        current = values[i]

        left_values = values[i - left:i]
        right_values = values[i + 1:i + right + 1]

        if (
            current <= np.min(left_values)
            and current <= np.min(right_values)
        ):
            swing_lows.append(i)

    return swing_lows


# ============================================================
# POSITIVE DIVERGENCE
# ============================================================

def detect_positive_divergence(
    df,
    price_column="Low",
    rsi_column="RSI14"
):

    if len(df) < MIN_HISTORY_ROWS:
        return None

    price = df[price_column]
    rsi = df[rsi_column]

    swing_indices = find_swing_lows(
        price,
        SWING_LEFT,
        SWING_RIGHT
    )

    if len(swing_indices) < 2:
        return None

    # Latest valid pair first
    for i in range(len(swing_indices) - 1, 0, -1):

        idx2 = swing_indices[i]
        idx1 = swing_indices[i - 1]

        gap = idx2 - idx1

        if gap > MAX_SWING_GAP:
            continue

        price_low1 = float(price.iloc[idx1])
        price_low2 = float(price.iloc[idx2])

        rsi_low1 = float(rsi.iloc[idx1])
        rsi_low2 = float(rsi.iloc[idx2])

        if any(
            pd.isna(x)
            for x in [
                price_low1,
                price_low2,
                rsi_low1,
                rsi_low2
            ]
        ):
            continue

        price_lower_low_pct = (
            (price_low1 - price_low2)
            / price_low1
        ) * 100

        rsi_improvement = rsi_low2 - rsi_low1

        # Positive divergence:
        # Price = Lower Low
        # RSI = Higher Low

        if price_lower_low_pct < MIN_PRICE_LOWER_LOW_PCT:
            continue

        if rsi_improvement < MIN_RSI_HIGHER_LOW:
            continue

        return {
            "idx1": idx1,
            "idx2": idx2,
            "date1": df.index[idx1],
            "date2": df.index[idx2],
            "price_low1": price_low1,
            "price_low2": price_low2,
            "rsi_low1": rsi_low1,
            "rsi_low2": rsi_low2,
            "price_lower_low_pct": price_lower_low_pct,
            "rsi_improvement": rsi_improvement
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
        and rsi_improvement >= 8
    ):
        return "VERY STRONG"

    if (
        price_lower_low_pct >= 2
        and rsi_improvement >= 5
    ):
        return "STRONG"

    if (
        price_lower_low_pct >= 1
        and rsi_improvement >= 3
    ):
        return "GOOD"

    return "MEDIUM"


# ============================================================
# SCORE
# ============================================================

def calculate_score(
    rsi_improvement,
    price_lower_low_pct,
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
    elif volume_ratio >= 1.0:
        score += 9
    elif volume_ratio >= 0.8:
        score += 6
    else:
        score += 2

    # Trend
    if close > ema20 > ema50:
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
    elif days_since_signal <= 10:
        score += 6
    else:
        score += 3

    return min(score, 100)


# ============================================================
# LOAD NIFTY 200
# ============================================================

def load_nifty200(spreadsheet):

    ws = spreadsheet.worksheet(NIFTY_SHEET)

    values = ws.get_all_values()

    if not values:
        raise RuntimeError(
            "NIFTY200 sheet is empty."
        )

    headers = [
        str(x).strip()
        for x in values[0]
    ]

    # Find NSE Code column
    possible_names = [
        "NSE Code",
        "NSE CODE",
        "NSECode",
        "Symbol",
        "SYMBOL"
    ]

    code_index = None

    for name in possible_names:

        if name in headers:
            code_index = headers.index(name)
            break

    if code_index is None:

        raise RuntimeError(
            "NSE Code / Symbol column not found in NIFTY200 sheet."
        )

    rows = []

    for row in values[1:]:

        if code_index >= len(row):
            continue

        symbol = str(
            row[code_index]
        ).strip().upper()

        if not symbol:
            continue

        rows.append({
            "NSE Code": symbol
        })

    df = pd.DataFrame(rows)

    df = df.drop_duplicates(
        subset=["NSE Code"]
    )

    print(
        f"NIFTY200 stocks loaded: {len(df)}"
    )

    return df


# ============================================================
# DOWNLOAD STOCK DATA
# ============================================================

def download_stock_data(symbol):

    yahoo_symbol = f"{symbol}.NS"

    try:

        df = yf.download(
            yahoo_symbol,
            period=HISTORY_PERIOD,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False
        )

    except Exception as e:

        print(
            f"{symbol}: Yahoo download error: {e}"
        )

        return None

    if df is None or df.empty:
        return None

    # Handle MultiIndex
    if isinstance(df.columns, pd.MultiIndex):

        try:
            df.columns = df.columns.get_level_values(0)
        except Exception:
            pass

    required_columns = [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume"
    ]

    for column in required_columns:

        if column not in df.columns:
            return None

        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )

    df = df.dropna(
        subset=required_columns
    )

    if len(df) < MIN_HISTORY_ROWS:
        return None

    return df


# ============================================================
# ANALYZE STOCK
# ============================================================

def analyze_stock(symbol):

    df = download_stock_data(symbol)

    if df is None:
        return None

    # --------------------------------------------------------
    # Indicators
    # --------------------------------------------------------

    df["RSI14"] = calculate_rsi(
        df["Close"],
        RSI_LENGTH
    )

    df["ATR14"] = calculate_atr(
        df,
        ATR_LENGTH
    )

    df["EMA20"] = df["Close"].ewm(
        span=20,
        adjust=False
    ).mean()

    df["EMA50"] = df["Close"].ewm(
        span=50,
        adjust=False
    ).mean()

    df["VolumeAvg20"] = df["Volume"].rolling(
        VOLUME_LENGTH
    ).mean()

    df["VolumeRatio"] = (
        df["Volume"]
        / df["VolumeAvg20"]
    )

    # --------------------------------------------------------
    # Latest values
    # --------------------------------------------------------

    latest = df.iloc[-1]

    close = float(latest["Close"])
    current_rsi = float(latest["RSI14"])
    atr14 = float(latest["ATR14"])
    ema20 = float(latest["EMA20"])
    ema50 = float(latest["EMA50"])
    volume_ratio = float(latest["VolumeRatio"])

    # --------------------------------------------------------
    # Previous close / daily change
    # --------------------------------------------------------

    if len(df) >= 2:

        previous_close = float(
            df["Close"].iloc[-2]
        )

        today_change_pct = (
            (close - previous_close)
            / previous_close
        ) * 100

    else:

        today_change_pct = 0.0

    # --------------------------------------------------------
    # Divergence
    # --------------------------------------------------------

    divergence = detect_positive_divergence(
        df
    )

    if divergence is None:
        return None

    signal_date = pd.Timestamp(
        divergence["date2"]
    ).date()

    today_date = pd.Timestamp(
        df.index[-1]
    ).date()

    days_since_signal = (
        today_date - signal_date
    ).days

    # --------------------------------------------------------
    # Signal age filter
    # --------------------------------------------------------

    if days_since_signal > MAX_SIGNAL_AGE:
        return None

    # --------------------------------------------------------
    # Volume filter
    # --------------------------------------------------------

    if (
        pd.isna(volume_ratio)
        or volume_ratio < MIN_VOLUME_RATIO
    ):
        return None

    # --------------------------------------------------------
    # Divergence values
    # --------------------------------------------------------

    price_lower_low_pct = float(
        divergence["price_lower_low_pct"]
    )

    rsi_improvement = float(
        divergence["rsi_improvement"]
    )

    price_low1 = float(
        divergence["price_low1"]
    )

    price_low2 = float(
        divergence["price_low2"]
    )

    rsi_low1 = float(
        divergence["rsi_low1"]
    )

    rsi_low2 = float(
        divergence["rsi_low2"]
    )

    # --------------------------------------------------------
    # Strength
    # --------------------------------------------------------

    divergence_strength = get_divergence_strength(
        price_lower_low_pct,
        rsi_improvement
    )

    # --------------------------------------------------------
    # Setup
    # --------------------------------------------------------

    setup = "RSI POSITIVE DIVERGENCE"

    # --------------------------------------------------------
    # Score
    # --------------------------------------------------------

    strength_score = calculate_score(
        rsi_improvement,
        price_lower_low_pct,
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

    support = price_low2

    # --------------------------------------------------------
    # Entry
    # --------------------------------------------------------

    entry = close

    # --------------------------------------------------------
    # Stop Loss
    # --------------------------------------------------------

    atr_stop = entry - (
        1.07 * atr14
    )

    support_stop = support - (
        0.18 * atr14
    )

    stop_loss = min(
        atr_stop,
        support_stop
    )

    if stop_loss <= 0:
        return None

    # --------------------------------------------------------
    # Risk
    # --------------------------------------------------------

    risk_amount = entry - stop_loss

    risk_pct = (
        risk_amount / entry
    ) * 100

    if risk_pct > MAX_RISK_PCT:
        return None

    # --------------------------------------------------------
    # Targets
    # --------------------------------------------------------

    target1 = entry + (
        risk_amount * TARGET1_R
    )

    target2 = entry + (
        risk_amount * TARGET2_R
    )

    # --------------------------------------------------------
    # TradingView chart
    # --------------------------------------------------------

    chart_url = (
        "https://www.tradingview.com/chart/"
        f"?symbol=NSE%3A{symbol}"
    )

    # --------------------------------------------------------
    # Return
    # --------------------------------------------------------

    return {

        "NSE Code": symbol,

        "Close": round(
            close, 2
        ),

        "Today Change %": round(
            today_change_pct, 2
        ),

        "Setup": setup,

        "Divergence Strength":
            divergence_strength,

        "Strength Score": int(
            strength_score
        ),

        "Price Low 1": round(
            price_low1, 2
        ),

        "Price Low 2": round(
            price_low2, 2
        ),

        "RSI Low 1": round(
            rsi_low1, 2
        ),

        "RSI Low 2": round(
            rsi_low2, 2
        ),

        "RSI14": round(
            current_rsi, 2
        ),

        "RSI Improvement": round(
            rsi_improvement, 2
        ),

        "Volume Ratio": round(
            volume_ratio, 2
        ),

        "EMA20": round(
            ema20, 2
        ),

        "EMA50": round(
            ema50, 2
        ),

        "ATR14": round(
            atr14, 2
        ),

        "Support": round(
            support, 2
        ),

        "Entry": round(
            entry, 2
        ),

        "Stop Loss": round(
            stop_loss, 2
        ),

        "Target 1": round(
            target1, 2
        ),

        "Target 2": round(
            target2, 2
        ),

        "Risk %": round(
            risk_pct, 2
        ),

        # IMPORTANT:
        # Actual date string, not Excel serial number
        "Signal Date": signal_date.strftime(
            "%Y-%m-%d"
        ),

        "Days Since Signal": int(
            days_since_signal
        ),

        "Chart": chart_url
    }


# ============================================================
# WRITE FINAL SHEET
# ============================================================

def write_final_sheet(ws, results):

    # --------------------------------------------------------
    # Clear complete old sheet
    # --------------------------------------------------------

    ws.clear()

    # --------------------------------------------------------
    # Header
    # --------------------------------------------------------

    header = OUTPUT_COLUMNS

    values = [
        header
    ]

    # --------------------------------------------------------
    # Data
    # --------------------------------------------------------

    for result in results:

        row = [
            result.get(column, "")
            for column in OUTPUT_COLUMNS
        ]

        values.append(row)

    last_row = max(
        len(values),
        2
    )

    # --------------------------------------------------------
    # Write A:Y ONLY
    # --------------------------------------------------------

    ws.update(
        range_name=f"A1:Y{last_row}",
        values=values
    )

    # --------------------------------------------------------
    # Header formatting
    # --------------------------------------------------------

    ws.format(
        "A1:Y1",
        {
            "textFormat": {
                "bold": True
            },
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
            "wrapStrategy": "WRAP"
        }
    )

    # --------------------------------------------------------
    # General formatting
    # --------------------------------------------------------

    if last_row >= 2:

        ws.format(
            f"A2:Y{last_row}",
            {
                "verticalAlignment": "MIDDLE"
            }
        )

        # Center selected columns
        ws.format(
            f"A2:F{last_row}",
            {
                "horizontalAlignment": "CENTER"
            }
        )

        ws.format(
            f"G2:V{last_row}",
            {
                "horizontalAlignment": "RIGHT"
            }
        )

        ws.format(
            f"W2:X{last_row}",
            {
                "horizontalAlignment": "CENTER"
            }
        )

        ws.format(
            f"Y2:Y{last_row}",
            {
                "horizontalAlignment": "CENTER"
            }
        )

    # --------------------------------------------------------
    # Number formatting
    # --------------------------------------------------------

    decimal_columns = [
        "B",
        "C",
        "F",
        "G",
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
        "V"
    ]

    for column in decimal_columns:

        if last_row >= 2:

            ws.format(
                f"{column}2:{column}{last_row}",
                {
                    "numberFormat": {
                        "type": "NUMBER",
                        "pattern": "0.00"
                    }
                }
            )

    # Strength Score should be integer
    if last_row >= 2:

        ws.format(
            f"F2:F{last_row}",
            {
                "numberFormat": {
                    "type": "NUMBER",
                    "pattern": "0"
                }
            }
        )

        ws.format(
            f"X2:X{last_row}",
            {
                "numberFormat": {
                    "type": "NUMBER",
                    "pattern": "0"
                }
            }
        )

        # Signal Date must remain text YYYY-MM-DD
        ws.format(
            f"W2:W{last_row}",
            {
                "numberFormat": {
                    "type": "TEXT"
                }
            }
        )

    # --------------------------------------------------------
    # Chart hyperlinks
    # --------------------------------------------------------

    if last_row >= 2:

        for row_number, result in enumerate(
            results,
            start=2
        ):

            chart_url = result.get(
                "Chart",
                ""
            )

            if chart_url:

                formula = (
                    f'=HYPERLINK("{chart_url}","📈 Chart")'
                )

                ws.update(
                    range_name=f"Y{row_number}",
                    values=[[formula]],
                    raw=False
                )

    # --------------------------------------------------------
    # Row formatting based on strength
    # --------------------------------------------------------

    if last_row >= 2:

        for row_number, result in enumerate(
            results,
            start=2
        ):

            strength = result.get(
                "Divergence Strength",
                ""
            )

            if strength == "VERY STRONG":

                ws.format(
                    f"A{row_number}:Y{row_number}",
                    {
                        "textFormat": {
                            "bold": True
                        }
                    }
                )

            elif strength == "STRONG":

                ws.format(
                    f"A{row_number}:Y{row_number}",
                    {
                        "textFormat": {
                            "bold": True
                        }
                    }
                )

    # --------------------------------------------------------
    # Freeze header
    # --------------------------------------------------------

    ws.freeze(rows=1)

    # --------------------------------------------------------
    # Filter
    # --------------------------------------------------------

    try:
        ws.clear_basic_filter()
    except Exception:
        pass

    if last_row >= 2:

        try:
            ws.set_basic_filter(
                f"A1:Y{last_row}"
            )
        except Exception as e:

            print(
                f"Filter warning: {e}"
            )

    # --------------------------------------------------------
    # Column widths
    # --------------------------------------------------------

    widths = {
        "A": 100,
        "B": 90,
        "C": 100,
        "D": 190,
        "E": 120,
        "F": 90,
        "G": 95,
        "H": 95,
        "I": 90,
        "J": 90,
        "K": 75,
        "L": 105,
        "M": 100,
        "N": 90,
        "O": 90,
        "P": 85,
        "Q": 90,
        "R": 90,
        "S": 95,
        "T": 90,
        "U": 90,
        "V": 80,
        "W": 105,
        "X": 110,
        "Y": 150
    }

    requests = []

    for column, width in widths.items():

        column_number = ord(column) - ord("A")

        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": ws.id,
                    "dimension": "COLUMNS",
                    "startIndex": column_number,
                    "endIndex": column_number + 1
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

    print(
        "Final List range: A:Y (25 columns)"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("NIFTY 200 POSITIVE DIVERGENCE SCANNER V1.1")
    print("=" * 70)

    spreadsheet = connect_google_sheet()

    # --------------------------------------------------------
    # Load NIFTY200
    # --------------------------------------------------------

    nifty200 = load_nifty200(
        spreadsheet
    )

    # --------------------------------------------------------
    # Final List worksheet
    # --------------------------------------------------------

    final_ws = spreadsheet.worksheet(
        FINAL_SHEET
    )

    results = []

    total = len(nifty200)

    # --------------------------------------------------------
    # Analyze every stock
    # --------------------------------------------------------

    for count, symbol in enumerate(
        nifty200["NSE Code"],
        start=1
    ):

        print(
            f"[{count}/{total}] Analyzing {symbol}"
        )

        try:

            result = analyze_stock(
                symbol
            )

            if result is not None:

                results.append(result)

                print(
                    f"  SIGNAL: {symbol} | "
                    f"Score={result['Strength Score']} | "
                    f"Strength={result['Divergence Strength']}"
                )

            else:

                print(
                    f"  No valid signal: {symbol}"
                )

        except Exception as e:

            print(
                f"  ERROR {symbol}: {e}"
            )

    # --------------------------------------------------------
    # Sort
    # --------------------------------------------------------

    results = sorted(
        results,
        key=lambda x: (
            -x["Strength Score"],
            x["Days Since Signal"],
            x["NSE Code"]
        )
    )

    # --------------------------------------------------------
    # Limit final stocks
    # --------------------------------------------------------

    results = results[
        :MAX_FINAL_STOCKS
    ]

    # --------------------------------------------------------
    # Write
    # --------------------------------------------------------

    write_final_sheet(
        final_ws,
        results
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("SCAN COMPLETE")
    print("=" * 70)

    print(
        f"Total NIFTY200 stocks: {total}"
    )

    print(
        f"Valid divergence signals: {len(results)}"
    )

    print(
        "Final List columns: A:Y = 25"
    )

    print("=" * 70)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
