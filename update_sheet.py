import os
import json
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

# ============================================================

OUTPUT_COLUMNS = [
"NSE Code",
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
"Chart"
]

# ============================================================

# GOOGLE SHEET CONNECTION

# ============================================================

def connect_google_sheet():


credentials_json = os.environ.get("GCP_CREDENTIALS")

if not credentials_json:
    raise RuntimeError(
        "GCP_CREDENTIALS environment variable not found."
    )

try:
    credentials_dict = json.loads(credentials_json)
except Exception as e:
    raise RuntimeError(
        f"GCP_CREDENTIALS is not valid JSON: {e}"
    )

required_keys = [
    "type",
    "project_id",
    "private_key",
    "client_email"
]

missing_keys = [
    key for key in required_keys
    if key not in credentials_dict
]

if missing_keys:
    raise RuntimeError(
        f"GCP_CREDENTIALS missing keys: {missing_keys}"
    )

scopes = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

credentials = ServiceAccountCredentials.from_json_keyfile_dict(
    credentials_dict,
    scopes
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


previous_close = df["Close"].shift(1)

tr1 = df["High"] - df["Low"]

tr2 = (df["High"] - previous_close).abs()

tr3 = (df["Low"] - previous_close).abs()

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

# SWING LOWS

# ============================================================

def find_swing_lows(series, left=3, right=3):


swing_lows = []

values = series.values

for i in range(left, len(series) - right):

    current_value = values[i]

    left_values = values[i - left:i]

    right_values = values[i + 1:i + right + 1]

    if (
        current_value <= np.min(left_values)
        and current_value <= np.min(right_values)
    ):
        swing_lows.append(i)

return swing_lows


# ============================================================

# POSITIVE DIVERGENCE

# ============================================================

def detect_positive_divergence(
df,
min_price_lower_low_pct=0.50,
min_rsi_higher_low=2.0,
max_gap=60
):


if len(df) < MIN_HISTORY_ROWS:
    return None

price_lows = find_swing_lows(
    df["Low"],
    SWING_LEFT,
    SWING_RIGHT
)

if len(price_lows) < 2:
    return None

candidates = []

for i in range(len(price_lows) - 1):

    idx1 = price_lows[i]

    for j in range(i + 1, len(price_lows)):

        idx2 = price_lows[j]

        gap = idx2 - idx1

        if gap > max_gap:
            continue

        price_low1 = float(df["Low"].iloc[idx1])
        price_low2 = float(df["Low"].iloc[idx2])

        rsi_low1 = float(df["RSI"].iloc[idx1])
        rsi_low2 = float(df["RSI"].iloc[idx2])

        if not np.isfinite(rsi_low1):
            continue

        if not np.isfinite(rsi_low2):
            continue

        price_lower_low_pct = (
            (price_low1 - price_low2)
            / price_low1
            * 100
        )

        rsi_improvement = rsi_low2 - rsi_low1

        if price_lower_low_pct < min_price_lower_low_pct:
            continue

        if rsi_improvement < min_rsi_higher_low:
            continue

        candidates.append(
            {
                "idx1": idx1,
                "idx2": idx2,
                "price_low1": price_low1,
                "price_low2": price_low2,
                "rsi_low1": rsi_low1,
                "rsi_low2": rsi_low2,
                "price_lower_low_pct": price_lower_low_pct,
                "rsi_improvement": rsi_improvement,
                "signal_date": df.index[idx2]
            }
        )

if not candidates:
    return None

candidates.sort(
    key=lambda x: x["idx2"],
    reverse=True
)

return candidates[0]


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

records = ws.get_all_records()

if not records:
    raise RuntimeError(
        "NIFTY200 sheet is empty."
    )

symbols = []

for row in records:

    symbol = (
        row.get("NSE Code")
        or row.get("Symbol")
        or row.get("NSE CODE")
        or row.get("SYMBOL")
    )

    if not symbol:
        continue

    symbol = str(symbol).strip().upper()

    if not symbol:
        continue

    if symbol not in symbols:
        symbols.append(symbol)

print(
    f"NIFTY200 stocks loaded: {len(symbols)}"
)

print(
    "Turnover Rank: IGNORED"
)

print(
    "Turnover: IGNORED"
)

print(
    "NIFTY200 Volume column: IGNORED"
)

return symbols


# ============================================================

# DOWNLOAD STOCK DATA

# ============================================================

def download_stock_data(symbol):


try:

    ticker = f"{symbol}.NS"

    df = yf.download(
        ticker,
        period=HISTORY_PERIOD,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False
    )

    if df is None or df.empty:
        print(
            f"{symbol}: No Yahoo Finance data."
        )
        return None

    # Handle MultiIndex
    if isinstance(df.columns, pd.MultiIndex):

        try:
            df.columns = df.columns.get_level_values(0)
        except Exception:
            df.columns = [
                col[0] if isinstance(col, tuple)
                else col
                for col in df.columns
            ]

    required_columns = [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume"
    ]

    for col in required_columns:

        if col not in df.columns:

            print(
                f"{symbol}: Missing column {col}"
            )

            return None

        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    df = df.dropna(
        subset=required_columns
    )

    if len(df) < MIN_HISTORY_ROWS:

        print(
            f"{symbol}: Insufficient history "
            f"({len(df)} rows)"
        )

        return None

    return df

except Exception as e:

    print(
        f"{symbol}: Download error - {e}"
    )

    return None


# ============================================================

# ANALYZE STOCK

# ============================================================

def analyze_stock(symbol):


df = download_stock_data(symbol)

if df is None:
    return None

try:

    # Indicators
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
        .ewm(span=20, adjust=False)
        .mean()
    )

    df["EMA50"] = (
        df["Close"]
        .ewm(span=50, adjust=False)
        .mean()
    )

    df["VolumeAvg20"] = (
        df["Volume"]
        .rolling(VOLUME_LENGTH)
        .mean()
    )

    df["VolumeRatio"] = (
        df["Volume"]
        / df["VolumeAvg20"]
    )

    # Latest values
    latest = df.iloc[-1]

    close = float(latest["Close"])

    current_rsi = float(latest["RSI"])

    atr14 = float(latest["ATR"])

    ema20 = float(latest["EMA20"])

    ema50 = float(latest["EMA50"])

    volume_ratio = float(
        latest["VolumeRatio"]
    )

    if not all(
        np.isfinite(x)
        for x in [
            close,
            current_rsi,
            atr14,
            ema20,
            ema50,
            volume_ratio
        ]
    ):

        print(
            f"{symbol}: Invalid indicator values."
        )

        return None

    # Today change %
    if len(df) >= 2:

        previous_close = float(
            df["Close"].iloc[-2]
        )

        today_change_pct = (
            (close - previous_close)
            / previous_close
            * 100
        )

    else:

        today_change_pct = 0.0

    # Divergence
    divergence = detect_positive_divergence(
        df,
        MIN_PRICE_LOWER_LOW_PCT,
        MIN_RSI_HIGHER_LOW,
        MAX_SWING_GAP
    )

    if divergence is None:

        print(
            f"{symbol}: No valid positive divergence."
        )

        return None

    signal_date = pd.Timestamp(
        divergence["signal_date"]
    )

    latest_date = pd.Timestamp(
        df.index[-1]
    )

    days_since_signal = (
        latest_date.date()
        - signal_date.date()
    ).days

    if days_since_signal > MAX_SIGNAL_AGE:

        print(
            f"{symbol}: Signal too old "
            f"({days_since_signal} days)."
        )

        return None

    # Volume filter
    if volume_ratio < MIN_VOLUME_RATIO:

        print(
            f"{symbol}: Volume ratio too low "
            f"({volume_ratio:.2f})."
        )

        return None

    price_low1 = divergence[
        "price_low1"
    ]

    price_low2 = divergence[
        "price_low2"
    ]

    rsi_low1 = divergence[
        "rsi_low1"
    ]

    rsi_low2 = divergence[
        "rsi_low2"
    ]

    price_lower_low_pct = divergence[
        "price_lower_low_pct"
    ]

    rsi_improvement = divergence[
        "rsi_improvement"
    ]

    divergence_strength = (
        get_divergence_strength(
            price_lower_low_pct,
            rsi_improvement
        )
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

    # Support
    support = price_low2

    # Entry
    entry = close

    # Stop loss
    stop1 = (
        entry
        - (1.07 * atr14)
    )

    stop2 = (
        support
        - (0.18 * atr14)
    )

    stop_loss = min(
        stop1,
        stop2
    )

    # Risk
    risk_amount = (
        entry - stop_loss
    )

    if risk_amount <= 0:

        print(
            f"{symbol}: Invalid risk."
        )

        return None

    risk_pct = (
        risk_amount
        / entry
        * 100
    )

    if risk_pct > MAX_RISK_PCT:

        print(
            f"{symbol}: Risk too high "
            f"({risk_pct:.2f}%)."
        )

        return None

    # Targets
    target1 = (
        entry
        + risk_amount * TARGET1_R
    )

    target2 = (
        entry
        + risk_amount * TARGET2_R
    )

    chart_url = (
        "https://in.tradingview.com/chart/"
        f"?symbol=NSE%3A{symbol}"
    )

    result = [

        symbol,

        round(close, 2),

        round(today_change_pct, 2),

        "RSI POSITIVE DIVERGENCE",

        divergence_strength,

        int(score),

        round(price_low1, 2),

        round(price_low2, 2),

        round(rsi_low1, 2),

        round(rsi_low2, 2),

        round(current_rsi, 2),

        round(rsi_improvement, 2),

        round(volume_ratio, 2),

        round(ema20, 2),

        round(ema50, 2),

        round(atr14, 2),

        round(support, 2),

        round(entry, 2),

        round(stop_loss, 2),

        round(target1, 2),

        round(target2, 2),

        round(risk_pct, 2),

        signal_date.strftime(
            "%Y-%m-%d"
        ),

        int(days_since_signal),

        "Chart"
    ]

    print(
        f"{symbol}: VALID | "
        f"Score={score} | "
        f"RSI Improvement={rsi_improvement:.2f} | "
        f"Volume Ratio={volume_ratio:.2f} | "
        f"Signal Age={days_since_signal}"
    )

    return result

except Exception as e:

    print(
        f"{symbol}: Analysis error - {e}"
    )

    return None


# ============================================================

# WRITE FINAL SHEET

# ============================================================

def write_final_sheet(
spreadsheet,
results
):


ws = spreadsheet.worksheet(
    FINAL_SHEET
)

# Clear complete sheet
ws.clear()

# Header
ws.update(
    "A1:Y1",
    [OUTPUT_COLUMNS]
)

# Sort results
if results:

    results.sort(
        key=lambda x: (
            -int(x[5]),
            int(x[23]),
            x[0]
        )
    )

    results = results[
        :MAX_FINAL_STOCKS
    ]

    # Write data A:Y
    end_row = len(results) + 1

    ws.update(
        f"A2:Y{end_row}",
        results
    )

    # TradingView hyperlink formulas
    hyperlink_formulas = []

    for row in results:

        symbol = row[0]

        url = (
            "https://in.tradingview.com/chart/"
            f"?symbol=NSE%3A{symbol}"
        )

        hyperlink_formulas.append(
            [
                f'=HYPERLINK("{url}","Chart")'
            ]
        )

    ws.update(
        f"Y2:Y{end_row}",
        hyperlink_formulas,
        value_input_option="USER_ENTERED"
    )

# Header formatting
try:

    ws.format(
        "A1:Y1",
        {
            "backgroundColor": {
                "red": 0.20,
                "green": 0.20,
                "blue": 0.20
            },
            "textFormat": {
                "bold": True,
                "foregroundColor": {
                    "red": 1,
                    "green": 1,
                    "blue": 1
                }
            },
            "horizontalAlignment": "CENTER"
        }
    )

except Exception as e:

    print(
        f"Header formatting warning: {e}"
    )

# Freeze first row
try:

    ws.freeze(
        rows=1
    )

except Exception as e:

    print(
        f"Freeze warning: {e}"
    )

# Filter
try:

    ws.set_basic_filter(
        "A1:Y"
    )

except Exception as e:

    print(
        f"Filter warning: {e}"
    )

# Column widths
try:

    widths = {

        "A": 110,
        "B": 90,
        "C": 100,
        "D": 180,
        "E": 130,
        "F": 90,
        "G": 100,
        "H": 100,
        "I": 90,
        "J": 90,
        "K": 80,
        "L": 110,
        "M": 100,
        "N": 90,
        "O": 90,
        "P": 90,
        "Q": 90,
        "R": 90,
        "S": 90,
        "T": 90,
        "U": 90,
        "V": 80,
        "W": 110,
        "X": 110,
        "Y": 100
    }

    for col, width in widths.items():

        ws.format(
            f"{col}:{col}",
            {
                "columnWidth": width
            }
        )

except Exception as e:

    print(
        f"Width formatting warning: {e}"
    )

print(
    f"Final List updated successfully: "
    f"{len(results)} stocks."
)


# ============================================================

# MAIN

# ============================================================

def main():


print("=" * 70)

print(
    "NIFTY 200 POSITIVE DIVERGENCE SCANNER"
)

print("=" * 70)

spreadsheet = connect_google_sheet()

symbols = load_nifty200(
    spreadsheet
)

results = []

total = len(symbols)

for number, symbol in enumerate(
    symbols,
    start=1
):

    print(
        f"\n[{number}/{total}] "
        f"Analyzing {symbol}..."
    )

    result = analyze_stock(
        symbol
    )

    if result is not None:

        results.append(
            result
        )

print("\n" + "=" * 70)

print(
    f"VALID STOCKS FOUND: {len(results)}"
)

print("=" * 70)

write_final_sheet(
    spreadsheet,
    results
)

print(
    "Scanner completed successfully."
)


if **name** == "**main**":
main()
