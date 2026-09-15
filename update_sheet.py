# =========================================================
# NIFTY 200 POSITIVE DIVERGENCE SCANNER V1.0
# =========================================================
# FINAL LIST:
#   1. RSI POSITIVE DIVERGENCE
#   2. CLASSIC POSITIVE DIVERGENCE
#
# DATA:
#   - NIFTY200 sheet = universe + turnover
#   - Yahoo Finance = 1 year daily OHLCV
#
# IMPORTANT:
#   - Completed daily candles only
#   - No intraday signal
#   - Old breakout/retest logic removed
#   - Final List rewritten completely every run
# =========================================================

import os
import json
import warnings
from datetime import datetime

import gspread
import numpy as np
import pandas as pd
import yfinance as yf
from oauth2client.service_account import ServiceAccountCredentials

warnings.filterwarnings("ignore")


# =========================================================
# SETTINGS
# =========================================================

SPREADSHEET_ID = "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E"

NIFTY_SHEET = "NIFTY200"
FINAL_SHEET = "Final List"

HISTORY_PERIOD = "1y"
MIN_HISTORY_ROWS = 100

RSI_LENGTH = 14
ATR_LENGTH = 14
VOLUME_LENGTH = 20

# Swing detection
SWING_LEFT = 3
SWING_RIGHT = 3

# Divergence quality
MIN_PRICE_LOWER_LOW_PCT = 0.50
MIN_RSI_HIGHER_LOW = 2.0

# Maximum distance between two swing lows
MAX_SWING_GAP = 60

# Signal should not be too old
MAX_SIGNAL_AGE = 15

# Volume
MIN_VOLUME_RATIO = 0.80

# Risk
MAX_RISK_PCT = 7.0

TARGET1_R = 1.5
TARGET2_R = 3.0

MAX_FINAL_STOCKS = 30


# =========================================================
# FINAL LIST COLUMNS
# =========================================================

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


# =========================================================
# EXCLUDED SYMBOLS
# =========================================================

EXCLUDE_WORDS = [
    "ETF",
    "BEES",
    "GOLD",
    "LIQUID",
    "SILVER",
    "INDEX",
]


# =========================================================
# GOOGLE CREDENTIALS
# =========================================================

def get_credentials():

    secret = os.getenv("GCP_CREDENTIALS")

    if secret:

        try:

            info = json.loads(secret)

            return ServiceAccountCredentials.from_json_keyfile_dict(
                info,
                [
                    "https://spreadsheets.google.com/feeds",
                    "https://www.googleapis.com/auth/drive",
                ],
            )

        except Exception as e:

            raise RuntimeError(
                f"GCP_CREDENTIALS is invalid JSON: {e}"
            )

    local_file = "credentials.json"

    if os.path.exists(local_file):

        return ServiceAccountCredentials.from_json_keyfile_name(
            local_file,
            [
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive",
            ],
        )

    raise FileNotFoundError(
        "GCP_CREDENTIALS secret not found and credentials.json is missing."
    )


# =========================================================
# HELPERS
# =========================================================

def clean_symbol(value):

    s = str(value).strip().upper()

    for suffix in [".NS", ".NSE"]:

        if s.endswith(suffix):

            s = s[:-len(suffix)]

    return s


def is_allowed_symbol(symbol):

    s = symbol.upper()

    return not any(
        word in s
        for word in EXCLUDE_WORDS
    )


def to_float(value, default=np.nan):

    try:

        if value is None or value == "":

            return default

        return float(
            str(value)
            .replace(",", "")
            .strip()
        )

    except Exception:

        return default


# =========================================================
# RSI
# =========================================================

def rsi(series, length=14):

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

    rs = (
        avg_gain /
        avg_loss.replace(0, np.nan)
    )

    result = 100 - (
        100 / (1 + rs)
    )

    return result.fillna(50)


# =========================================================
# ATR
# =========================================================

def atr(df, length=14):

    prev_close = df["Close"].shift(1)

    tr1 = df["High"] - df["Low"]

    tr2 = (
        df["High"] -
        prev_close
    ).abs()

    tr3 = (
        df["Low"] -
        prev_close
    ).abs()

    true_range = pd.concat(
        [tr1, tr2, tr3],
        axis=1
    ).max(axis=1)

    return true_range.ewm(
        alpha=1 / length,
        adjust=False,
        min_periods=length
    ).mean()


# =========================================================
# PREPARE HISTORY
# =========================================================

def prepare_history(hist):

    hist = hist.copy()

    if isinstance(
        hist.columns,
        pd.MultiIndex
    ):

        hist.columns = (
            hist.columns
            .get_level_values(0)
        )

    required = [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume"
    ]

    missing = [
        c for c in required
        if c not in hist.columns
    ]

    if missing:

        raise ValueError(
            f"Missing history columns: {missing}"
        )

    hist = hist[
        required
    ].copy()

    for col in required:

        hist[col] = pd.to_numeric(
            hist[col],
            errors="coerce"
        )

    hist = hist.dropna(
        subset=[
            "High",
            "Low",
            "Close"
        ]
    ).copy()

    if len(hist) < MIN_HISTORY_ROWS:

        return None

    # Indicators
    hist["EMA20"] = (
        hist["Close"]
        .ewm(
            span=20,
            adjust=False,
            min_periods=20
        )
        .mean()
    )

    hist["EMA50"] = (
        hist["Close"]
        .ewm(
            span=50,
            adjust=False,
            min_periods=50
        )
        .mean()
    )

    hist["RSI14"] = rsi(
        hist["Close"],
        RSI_LENGTH
    )

    hist["ATR14"] = atr(
        hist,
        ATR_LENGTH
    )

    hist["AvgVolume20"] = (
        hist["Volume"]
        .rolling(
            VOLUME_LENGTH,
            min_periods=VOLUME_LENGTH
        )
        .mean()
    )

    hist["VolumeRatio"] = (
        hist["Volume"] /
        hist["AvgVolume20"]
        .replace(0, np.nan)
    )

    hist["DailyChangePct"] = (
        hist["Close"].pct_change() * 100
    )

    return hist.dropna(
        subset=[
            "EMA20",
            "EMA50",
            "RSI14",
            "ATR14"
        ]
    )


# =========================================================
# SWING LOW DETECTION
# =========================================================

def find_swing_lows(series, left=3, right=3):

    values = series.values

    swing_indices = []

    for i in range(
        left,
        len(values) - right
    ):

        left_values = values[
            i-left:i
        ]

        right_values = values[
            i+1:i+right+1
        ]

        current = values[i]

        if (
            current <= left_values.min()
            and
            current <= right_values.min()
        ):

            swing_indices.append(i)

    return swing_indices


# =========================================================
# FIND DIVERGENCE
# =========================================================

def find_divergence(hist):

    lows = find_swing_lows(
        hist["Low"],
        SWING_LEFT,
        SWING_RIGHT
    )

    if len(lows) < 2:

        return None

    latest_index = len(hist) - 1

    # Only use swings that are confirmed
    confirmed_lows = [
        i for i in lows
        if i + SWING_RIGHT <= latest_index
    ]

    if len(confirmed_lows) < 2:

        return None

    # Search newest valid pair first
    for j in range(
        len(confirmed_lows) - 1,
        0,
        -1
    ):

        i2 = confirmed_lows[j]
        i1 = confirmed_lows[j - 1]

        gap = i2 - i1

        if gap > MAX_SWING_GAP:

            continue

        price1 = float(
            hist["Low"].iloc[i1]
        )

        price2 = float(
            hist["Low"].iloc[i2]
        )

        rsi1 = float(
            hist["RSI14"].iloc[i1]
        )

        rsi2 = float(
            hist["RSI14"].iloc[i2]
        )

        if not all(
            np.isfinite(x)
            for x in [
                price1,
                price2,
                rsi1,
                rsi2
            ]
        ):

            continue

        price_lower_low_pct = (
            (price1 - price2)
            / price1
        ) * 100

        rsi_improvement = rsi2 - rsi1

        # Price must make lower low
        if price_lower_low_pct < MIN_PRICE_LOWER_LOW_PCT:

            continue

        # RSI must make higher low
        if rsi_improvement < MIN_RSI_HIGHER_LOW:

            continue

        # Signal age
        signal_age = (
            latest_index - i2
        )

        if signal_age > MAX_SIGNAL_AGE:

            continue

        signal_date = hist.index[i2]

        return {
            "i1": i1,
            "i2": i2,
            "price1": price1,
            "price2": price2,
            "rsi1": rsi1,
            "rsi2": rsi2,
            "rsi_improvement": rsi_improvement,
            "price_lower_low_pct": price_lower_low_pct,
            "signal_date": signal_date,
            "signal_age": signal_age,
        }

    return None


# =========================================================
# CLASSIC DIVERGENCE QUALITY
# =========================================================

def classify_divergence(div):

    rsi_imp = div["rsi_improvement"]

    price_drop = div[
        "price_lower_low_pct"
    ]

    if (
        rsi_imp >= 8
        and price_drop >= 2
    ):

        return "STRONG"

    if (
        rsi_imp >= 5
        and price_drop >= 1
    ):

        return "GOOD"

    return "MEDIUM"


# =========================================================
# SCORE
# =========================================================

def calculate_score(
    latest,
    div
):

    score = 0

    # -----------------------------------------
    # RSI divergence strength
    # -----------------------------------------

    rsi_imp = div[
        "rsi_improvement"
    ]

    if rsi_imp >= 10:

        score += 30

    elif rsi_imp >= 7:

        score += 25

    elif rsi_imp >= 5:

        score += 20

    else:

        score += 15

    # -----------------------------------------
    # Price lower low
    # -----------------------------------------

    price_drop = div[
        "price_lower_low_pct"
    ]

    if price_drop >= 5:

        score += 20

    elif price_drop >= 3:

        score += 15

    elif price_drop >= 1:

        score += 10

    else:

        score += 5

    # -----------------------------------------
    # Current RSI
    # -----------------------------------------

    current_rsi = float(
        latest["RSI14"]
    )

    if 30 <= current_rsi <= 45:

        score += 15

    elif 45 < current_rsi <= 55:

        score += 12

    elif current_rsi < 30:

        score += 10

    else:

        score += 5

    # -----------------------------------------
    # Volume
    # -----------------------------------------

    volume_ratio = float(
        latest["VolumeRatio"]
    )

    if volume_ratio >= 1.5:

        score += 15

    elif volume_ratio >= 1.0:

        score += 10

    elif volume_ratio >= 0.8:

        score += 5

    # -----------------------------------------
    # Trend improvement
    # -----------------------------------------

    if latest["Close"] > latest["EMA20"]:

        score += 5

    if latest["EMA20"] > latest["EMA50"]:

        score += 5

    # -----------------------------------------
    # Freshness
    # -----------------------------------------

    age = div["signal_age"]

    if age <= 3:

        score += 5

    elif age <= 7:

        score += 3

    return int(
        min(score, 100)
    )


# =========================================================
# TRADE LEVELS
# =========================================================

def calculate_levels(
    hist,
    div
):

    latest = hist.iloc[-1]

    close = float(
        latest["Close"]
    )

    atr14 = float(
        latest["ATR14"]
    )

    # Recent structural support
    support = float(
        min(
            div["price2"],
            hist["Low"].tail(10).min()
        )
    )

    # Entry = close confirmation
    entry = close

    # ATR + structure stop
    atr_stop = (
        entry -
        1.5 * atr14
    )

    structure_stop = (
        support * 0.995
    )

    stop = max(
        atr_stop,
        structure_stop
    )

    risk_points = (
        entry - stop
    )

    if risk_points <= 0:

        return None

    risk_pct = (
        risk_points /
        entry
    ) * 100

    if risk_pct > MAX_RISK_PCT:

        return None

    target1 = (
        entry +
        TARGET1_R * risk_points
    )

    target2 = (
        entry +
        TARGET2_R * risk_points
    )

    return {
        "support": support,
        "entry": entry,
        "stop": stop,
        "target1": target1,
        "target2": target2,
        "risk_pct": risk_pct,
    }


# =========================================================
# ANALYZE STOCK
# =========================================================

def analyze_stock(
    symbol,
    hist,
    turnover_rank,
    turnover
):

    latest = hist.iloc[-1]

    close = float(
        latest["Close"]
    )

    if not np.isfinite(close):

        return None

    # -----------------------------------------
    # Divergence
    # -----------------------------------------

    div = find_divergence(hist)

    if div is None:

        return None

    # -----------------------------------------
    # Volume filter
    # -----------------------------------------

    volume_ratio = float(
        latest["VolumeRatio"]
    )

    if (
        not np.isfinite(volume_ratio)
        or
        volume_ratio < MIN_VOLUME_RATIO
    ):

        return None

    # -----------------------------------------
    # Divergence classification
    # -----------------------------------------

    strength = classify_divergence(
        div
    )

    score = calculate_score(
        latest,
        div
    )

    # -----------------------------------------
    # Setup classification
    # -----------------------------------------

    # RSI positive divergence:
    # RSI itself is the confirming oscillator.

    setup = "RSI POSITIVE DIVERGENCE"

    # Classic positive divergence:
    # stronger structural lower-low +
    # meaningful RSI higher-low.

    if (
        div["price_lower_low_pct"] >= 2
        and
        div["rsi_improvement"] >= 5
    ):

        setup = "CLASSIC POSITIVE DIVERGENCE"

    # -----------------------------------------
    # Levels
    # -----------------------------------------

    levels = calculate_levels(
        hist,
        div
    )

    if levels is None:

        return None

    # -----------------------------------------
    # Chart
    # -----------------------------------------

    chart = (
        "https://www.tradingview.com/chart/"
        "?symbol=NSE%3A"
        + symbol
    )

    signal_date = pd.Timestamp(
        div["signal_date"]
    )

    days_since = int(
        div["signal_age"]
    )

    return {

        "NSE Code":
            symbol,

        "Turnover Rank":
            int(turnover_rank),

        "Turnover":
            round(
                float(turnover),
                2
            ),

        "Close":
            round(close, 2),

        "Today Change %":
            round(
                float(
                    latest[
                        "DailyChangePct"
                    ]
                ),
                2
            ),

        "Setup":
            setup,

        "Divergence Strength":
            strength,

        "Strength Score":
            score,

        "Price Low 1":
            round(
                div["price1"],
                2
            ),

        "Price Low 2":
            round(
                div["price2"],
                2
            ),

        "RSI Low 1":
            round(
                div["rsi1"],
                2
            ),

        "RSI Low 2":
            round(
                div["rsi2"],
                2
            ),

        "RSI14":
            round(
                float(
                    latest["RSI14"]
                ),
                2
            ),

        "RSI Improvement %":
            round(
                div[
                    "rsi_improvement"
                ],
                2
            ),

        "Volume Ratio":
            round(
                volume_ratio,
                2
            ),

        "EMA20":
            round(
                float(
                    latest["EMA20"]
                ),
                2
            ),

        "EMA50":
            round(
                float(
                    latest["EMA50"]
                ),
                2
            ),

        "ATR14":
            round(
                float(
                    latest["ATR14"]
                ),
                2
            ),

        "Support":
            round(
                levels["support"],
                2
            ),

        "Entry":
            round(
                levels["entry"],
                2
            ),

        "Stop Loss":
            round(
                levels["stop"],
                2
            ),

        "Target 1":
            round(
                levels["target1"],
                2
            ),

        "Target 2":
            round(
                levels["target2"],
                2
            ),

        "Risk %":
            round(
                levels["risk_pct"],
                2
            ),

        "Signal Date":
            signal_date.strftime(
                "%Y-%m-%d"
            ),

        "Days Since Signal":
            days_since,

        "Chart":
            chart,
    }


# =========================================================
# LOAD NIFTY 200 UNIVERSE
# =========================================================

def load_universe(ws):

    records = ws.get_all_records()

    if not records:

        raise ValueError(
            f"{NIFTY_SHEET} sheet is empty."
        )

    df = pd.DataFrame(
        records
    )

    symbol_col = None

    for col in [
        "NSE Code",
        "Symbol",
        "symbol",
        "NSECODE"
    ]:

        if col in df.columns:

            symbol_col = col

            break

    if symbol_col is None:

        raise ValueError(
            "NIFTY200 must contain "
            "'NSE Code' or 'Symbol'."
        )

    df["NSE Code"] = (
        df[symbol_col]
        .apply(clean_symbol)
    )

    if "Turnover" not in df.columns:

        raise ValueError(
            "NIFTY200 must contain "
            "'Turnover'."
        )

    df["Turnover"] = (
        df["Turnover"]
        .apply(to_float)
    )

    df = df[
        df["NSE Code"].notna()
    ]

    df = df[
        df["NSE Code"]
        .astype(str)
        .str.len() > 0
    ]

    df = df[
        df["NSE Code"]
        .apply(is_allowed_symbol)
    ]

    df = df[
        df["Turnover"].notna()
    ]

    # Highest turnover first
    df = df.sort_values(
        "Turnover",
        ascending=False,
        kind="mergesort"
    ).reset_index(
        drop=True
    )

    df["Turnover Rank"] = (
        np.arange(
            1,
            len(df) + 1
        )
    )

    df = df.head(
        200
    ).copy()

    return df


# =========================================================
# DOWNLOAD YAHOO HISTORY
# =========================================================

def download_history(symbols):

    tickers = [
        f"{s}.NS"
        for s in symbols
    ]

    print(
        f"Downloading Yahoo Finance "
        f"history for {len(tickers)} symbols..."
    )

    try:

        data = yf.download(
            tickers=tickers,
            period=HISTORY_PERIOD,
            interval="1d",
            auto_adjust=False,
            group_by="ticker",
            threads=True,
            progress=False,
        )

    except Exception as e:

        print(
            "Bulk Yahoo download failed:",
            e
        )

        return {}

    histories = {}

    if (
        data is None
        or
        data.empty
    ):

        return histories

    for symbol in symbols:

        ticker = f"{symbol}.NS"

        try:

            if len(symbols) == 1:

                hist = data.copy()

            else:

                if (
                    ticker
                    not in
                    data.columns
                    .get_level_values(0)
                ):

                    continue

                hist = data[
                    ticker
                ].copy()

            hist = prepare_history(
                hist
            )

            if hist is not None:

                histories[
                    symbol
                ] = hist

        except Exception as e:

            print(
                f"History error "
                f"{symbol}: {e}"
            )

    return histories


# =========================================================
# WRITE FINAL SHEET
# =========================================================

def write_final_sheet(
    ws,
    rows
):

    # Remove everything old
    ws.clear()

    values = [
        OUTPUT_COLUMNS
    ]

    for row in rows:

        values.append(
            [
                row.get(
                    col,
                    ""
                )
                for col in OUTPUT_COLUMNS
            ]
        )

    end_row = max(
        len(values),
        1
    )

    end_col = len(
        OUTPUT_COLUMNS
    )

    # Convert column number to Excel letter
    def col_letter(n):

        result = ""

        while n:

            n, remainder = divmod(
                n - 1,
                26
            )

            result = chr(
                65 + remainder
            ) + result

        return result

    last_col = col_letter(
        end_col
    )

    ws.update(
        f"A1:{last_col}{end_row}",
        values,
        value_input_option="USER_ENTERED",
    )

    # -----------------------------------------------------
    # HEADER
    # -----------------------------------------------------

    try:

        ws.format(
            f"A1:{last_col}1",
            {
                "backgroundColor": {
                    "red": 0.10,
                    "green": 0.25,
                    "blue": 0.45,
                },
                "textFormat": {
                    "bold": True,
                    "foregroundColor": {
                        "red": 1,
                        "green": 1,
                        "blue": 1,
                    },
                },
                "horizontalAlignment":
                    "CENTER",
                "verticalAlignment":
                    "MIDDLE",
            },
        )

        if len(values) > 1:

            ws.format(
                f"A2:{last_col}{end_row}",
                {
                    "horizontalAlignment":
                        "CENTER",
                    "verticalAlignment":
                        "MIDDLE",
                },
            )

        # -------------------------------------------------
        # FREEZE HEADER
        # -------------------------------------------------

        ws.freeze(
            rows=1
        )

        # -------------------------------------------------
        # CONDITIONAL ROW COLORS
        # -------------------------------------------------

        # Find Setup column
        setup_col = (
            OUTPUT_COLUMNS.index(
                "Setup"
            ) + 1
        )

        def letter(n):

            result = ""

            while n:

                n, r = divmod(
                    n - 1,
                    26
                )

                result = chr(
                    65 + r
                ) + result

            return result

        setup_letter = letter(
            setup_col
        )

        # Green = RSI divergence
        # Blue = Classic divergence

        if len(values) > 1:

            for i, row in enumerate(
                rows,
                start=2
            ):

                setup = row[
                    "Setup"
                ]

                if setup == (
                    "RSI POSITIVE DIVERGENCE"
                ):

                    bg = {
                        "red": 0.80,
                        "green": 1.00,
                        "blue": 0.80,
                    }

                else:

                    bg = {
                        "red": 0.80,
                        "green": 0.90,
                        "blue": 1.00,
                    }

                ws.format(
                    f"A{i}:{last_col}{i}",
                    {
                        "backgroundColor":
                            bg
                    },
                )

        # -------------------------------------------------
        # CHART COLUMN
        # -------------------------------------------------

        chart_col = (
            OUTPUT_COLUMNS.index(
                "Chart"
            ) + 1
        )

        chart_letter = letter(
            chart_col
        )

        if len(values) > 1:

            for row_num in range(
                2,
                end_row + 1
            ):

                formula = (
                    f'=HYPERLINK('
                    f'{chart_letter}{row_num},'
                    f'"📈 Chart")'
                )

                # Keep actual URL hidden
                # and show clickable Chart
                ws.update(
                    f"{chart_letter}{row_num}",
                    [[
                        formula
                    ]],
                    value_input_option=
                    "USER_ENTERED",
                )

        # -------------------------------------------------
        # COLUMN WIDTHS
        # -------------------------------------------------

        widths = {
            "A": 110,
            "B": 100,
            "C": 110,
            "D": 90,
            "E": 95,
            "F": 190,
            "G": 110,
            "H": 100,
            "I": 100,
            "J": 100,
            "K": 90,
            "L": 90,
            "M": 75,
            "N": 105,
            "O": 95,
            "P": 90,
            "Q": 90,
            "R": 90,
            "S": 100,
            "T": 90,
            "U": 90,
            "V": 90,
            "W": 90,
            "X": 80,
            "Y": 110,
            "Z": 110,
            "AA": 100,
        }

        for col, width in widths.items():

            try:

                ws.set_basic_filter(
                    f"A1:{last_col}{end_row}"
                )

                break

            except:

                pass

    except Exception as e:

        print(
            "Formatting warning:",
            e
        )


# =========================================================
# DIAGNOSTICS
# =========================================================

def diagnostics(rows):

    print("\n")
    print("=" * 60)
    print("DIVERGENCE DIAGNOSTICS")
    print("=" * 60)

    if not rows:

        print(
            "No positive divergence "
            "candidates found."
        )

        return

    df = pd.DataFrame(
        rows
    )

    print(
        f"Candidates: {len(df)}"
    )

    print(
        "RSI Positive Divergence:",
        (
            df["Setup"]
            ==
            "RSI POSITIVE DIVERGENCE"
        ).sum()
    )

    print(
        "Classic Positive Divergence:",
        (
            df["Setup"]
            ==
            "CLASSIC POSITIVE DIVERGENCE"
        ).sum()
    )

    print(
        "Strong:",
        (
            df["Divergence Strength"]
            ==
            "STRONG"
        ).sum()
    )

    print(
        "Good:",
        (
            df["Divergence Strength"]
            ==
            "GOOD"
        ).sum()
    )

    print(
        "Medium:",
        (
            df["Divergence Strength"]
            ==
            "MEDIUM"
        ).sum()
    )

    print(
        "Highest Score:",
        df["Strength Score"].max()
    )

    print(
        "Lowest Risk:",
        f"{df['Risk %'].min():.2f}%"
    )

    print(
        "Highest Risk:",
        f"{df['Risk %'].max():.2f}%"
    )

    print("=" * 60)


# =========================================================
# MAIN
# =========================================================

def main():

    print("=" * 70)

    print(
        "NIFTY 200 "
        "POSITIVE DIVERGENCE SCANNER V1.0"
    )

    print("=" * 70)

    creds = get_credentials()

    gc = gspread.authorize(
        creds
    )

    sh = gc.open_by_key(
        SPREADSHEET_ID
    )

    universe_ws = (
        sh.worksheet(
            NIFTY_SHEET
        )
    )

    final_ws = (
        sh.worksheet(
            FINAL_SHEET
        )
    )

    # -----------------------------------------------------
    # NIFTY200
    # -----------------------------------------------------

    universe = load_universe(
        universe_ws
    )

    print(
        f"Universe loaded: "
        f"{len(universe)} stocks"
    )

    symbols = (
        universe[
            "NSE Code"
        ].tolist()
    )

    # -----------------------------------------------------
    # DOWNLOAD DATA
    # -----------------------------------------------------

    histories = download_history(
        symbols
    )

    print(
        f"Usable histories: "
        f"{len(histories)}"
    )

    # -----------------------------------------------------
    # ANALYZE
    # -----------------------------------------------------

    candidates = []

    for _, u in universe.iterrows():

        symbol = u[
            "NSE Code"
        ]

        if symbol not in histories:

            continue

        try:

            result = analyze_stock(
                symbol=symbol,
                hist=histories[
                    symbol
                ],
                turnover_rank=int(
                    u[
                        "Turnover Rank"
                    ]
                ),
                turnover=float(
                    u[
                        "Turnover"
                    ]
                ),
            )

            if result:

                candidates.append(
                    result
                )

        except Exception as e:

            print(
                f"Analysis error "
                f"{symbol}: {e}"
            )

    # -----------------------------------------------------
    # SORT
    # -----------------------------------------------------

    setup_priority = {
        "CLASSIC POSITIVE DIVERGENCE": 0,
        "RSI POSITIVE DIVERGENCE": 1,
    }

    strength_priority = {
        "STRONG": 0,
        "GOOD": 1,
        "MEDIUM": 2,
    }

    candidates.sort(
        key=lambda x: (
            setup_priority.get(
                x["Setup"],
                9
            ),
            strength_priority.get(
                x[
                    "Divergence Strength"
                ],
                9
            ),
            -x[
                "Strength Score"
            ],
            x[
                "Turnover Rank"
            ],
        )
    )

    # -----------------------------------------------------
    # FINAL LIMIT
    # -----------------------------------------------------

    candidates = candidates[
        :MAX_FINAL_STOCKS
    ]

    diagnostics(
        candidates
    )

    # -----------------------------------------------------
    # WRITE GOOGLE SHEET
    # -----------------------------------------------------

    write_final_sheet(
        final_ws,
        candidates
    )

    print("\n")
    print(
        "Final List updated successfully."
    )

    print(
        f"Rows written: "
        f"{len(candidates)}"
    )

    print(
        f"Columns written: "
        f"{len(OUTPUT_COLUMNS)}"
    )

    print("=" * 70)


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
