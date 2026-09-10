# =========================================================
# NIFTY 200 SWING SNIPER V2.1.4
# =========================================================
# FINAL LIST:
#   - High-quality BUY: FRESH BREAKOUT / RETEST + HOLD
#   - High-quality WATCH: near breakout, waiting for confirmation
#
# Data:
#   - NIFTY200 sheet = current universe + turnover
#   - Yahoo Finance = 1 year daily OHLCV history
#
# Important:
#   - Uses completed daily candles only.
#   - No intraday entry.
#   - Google Sheet header is rewritten from A:V every run.
# =========================================================

import os
import json
import time
import warnings
from datetime import datetime

import gspread
import numpy as np
import pandas as pd
import yfinance as yf
from oauth2client.service_account import ServiceAccountCredentials

warnings.filterwarnings("ignore")

SPREADSHEET_ID = "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E"
NIFTY_SHEET = "NIFTY200"
FINAL_SHEET = "Final List"

HISTORY_PERIOD = "1y"
MIN_HISTORY_ROWS = 70

BREAKOUT_LOOKBACK = 20
EMA_FAST = 20
EMA_SLOW = 50
RSI_LENGTH = 14
ATR_LENGTH = 14
VOLUME_LENGTH = 20

# V2.1.4 = stricter sniper filters
MIN_VOLUME_RATIO_BUY = 1.50
MIN_VOLUME_RATIO_WATCH = 1.00

RSI_BUY_MIN = 55
RSI_BUY_MAX = 68          # BUY requires RSI < 68
RSI_WATCH_MAX = 68        # WATCH also avoids RSI 68+
RSI_HARD_REJECT = 80

MAX_BREAKOUT_EXTENSION_PCT = 3.0
WATCH_DISTANCE_PCT = 2.0

RETEST_MAX_ABOVE_PCT = 1.0
RETEST_MAX_BELOW_PCT = 3.0
RETEST_LOOKBACK_DAYS = 5

MAX_RISK_PCT = 5.0
TARGET1_R = 1.5
TARGET2_R = 3.0

MAX_FINAL_STOCKS = 12
MIN_BUY_SCORE = 75
MIN_WATCH_SCORE = 70

# Exact 22-column output. Never change order accidentally.
OUTPUT_COLUMNS = [
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
    "Chart",
]

EXCLUDE_WORDS = ["ETF", "BEES", "GOLD", "LIQUID", "SILVER", "INDEX"]


def get_credentials():
    """Use GitHub Actions secret first; support local credentials.json too."""
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
            raise RuntimeError(f"GCP_CREDENTIALS is invalid JSON: {e}")

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


def clean_symbol(value):
    s = str(value).strip().upper()
    for suffix in [".NS", ".NSE"]:
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


def is_allowed_symbol(symbol):
    s = symbol.upper()
    return not any(word in s for word in EXCLUDE_WORDS)


def to_float(value, default=np.nan):
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace(",", "").strip())
    except Exception:
        return default


def rsi(series, length=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)


def atr(df, length=14):
    prev_close = df["Close"].shift(1)

    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - prev_close).abs()
    tr3 = (df["Low"] - prev_close).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.ewm(
        alpha=1 / length, adjust=False, min_periods=length
    ).mean()


def prepare_history(hist):
    hist = hist.copy()

    if isinstance(hist.columns, pd.MultiIndex):
        hist.columns = hist.columns.get_level_values(0)

    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in required if c not in hist.columns]
    if missing:
        raise ValueError(f"Missing history columns: {missing}")

    hist = hist[required].copy()

    for col in required:
        hist[col] = pd.to_numeric(hist[col], errors="coerce")

    hist = hist.dropna(subset=["High", "Low", "Close"]).copy()

    if len(hist) < MIN_HISTORY_ROWS:
        return None

    hist["EMA20"] = hist["Close"].ewm(
        span=EMA_FAST, adjust=False, min_periods=EMA_FAST
    ).mean()

    hist["EMA50"] = hist["Close"].ewm(
        span=EMA_SLOW, adjust=False, min_periods=EMA_SLOW
    ).mean()

    hist["RSI14"] = rsi(hist["Close"], RSI_LENGTH)
    hist["ATR14"] = atr(hist, ATR_LENGTH)

    # Previous completed 20-session high.
    hist["Prev20High"] = (
        hist["High"].rolling(BREAKOUT_LOOKBACK, min_periods=BREAKOUT_LOOKBACK).max()
        .shift(1)
    )

    hist["Prev20Low"] = (
        hist["Low"].rolling(BREAKOUT_LOOKBACK, min_periods=BREAKOUT_LOOKBACK).min()
        .shift(1)
    )

    hist["AvgVolume20"] = (
        hist["Volume"].rolling(VOLUME_LENGTH, min_periods=VOLUME_LENGTH).mean()
    )

    hist["VolumeRatio"] = (
        hist["Volume"] / hist["AvgVolume20"].replace(0, np.nan)
    )

    hist["Range20Pct"] = (
        (
            hist["High"].rolling(BREAKOUT_LOOKBACK).max()
            - hist["Low"].rolling(BREAKOUT_LOOKBACK).min()
        )
        / hist["Close"]
        * 100
    )

    hist["EMA20SlopePct"] = (
        hist["EMA20"].pct_change(5) * 100
    )

    hist["DailyChangePct"] = hist["Close"].pct_change() * 100

    return hist.dropna(
        subset=["EMA20", "EMA50", "RSI14", "ATR14", "Prev20High"]
    )


def get_previous_breakout(hist):
    """Find the most recent genuine breakout in the previous 1-5 completed sessions."""
    if len(hist) < RETEST_LOOKBACK_DAYS + 2:
        return None

    end = len(hist) - 1
    start = max(0, end - RETEST_LOOKBACK_DAYS)

    candidates = []

    for i in range(start, end):
        row = hist.iloc[i]

        if pd.isna(row["Prev20High"]):
            continue

        if row["Close"] > row["Prev20High"]:
            candidates.append(
                {
                    "date": hist.index[i],
                    "level": float(row["Prev20High"]),
                    "close": float(row["Close"]),
                }
            )

    return candidates[-1] if candidates else None


def calculate_levels(entry, hist):
    latest = hist.iloc[-1]

    atr_value = float(latest["ATR14"])
    recent_low = float(hist["Low"].tail(5).min())

    atr_stop = entry - (1.5 * atr_value)
    structure_stop = recent_low * 0.995

    # Higher stop = tighter risk, but still protected by recent structure.
    stop = max(atr_stop, structure_stop)

    risk_pct = ((entry - stop) / entry) * 100

    if risk_pct <= 0:
        return None

    # Never allow a setup whose calculated risk exceeds 5%.
    if risk_pct > MAX_RISK_PCT:
        return None

    risk_points = entry - stop

    target1 = entry + TARGET1_R * risk_points
    target2 = entry + TARGET2_R * risk_points

    return {
        "Entry": entry,
        "Stop Loss": stop,
        "Target 1": target1,
        "Target 2": target2,
        "Risk %": risk_pct,
    }


def calculate_score(latest, setup):
    score = 0

    # Trend
    if latest["EMA20"] > latest["EMA50"]:
        score += 20

    # Price above EMA20
    if latest["Close"] > latest["EMA20"]:
        score += 15

    # RSI
    if RSI_BUY_MIN <= latest["RSI14"] < RSI_BUY_MAX:
        score += 15
    elif RSI_BUY_MIN <= latest["RSI14"] < RSI_WATCH_MAX:
        score += 10

    # Volume
    if latest["VolumeRatio"] >= MIN_VOLUME_RATIO_BUY:
        score += 15
    elif latest["VolumeRatio"] >= MIN_VOLUME_RATIO_WATCH:
        score += 10

    # EMA slope
    if latest["EMA20SlopePct"] > 0:
        score += 10

    # Controlled 20-day range
    if latest["Range20Pct"] <= 12:
        score += 10
    elif latest["Range20Pct"] <= 18:
        score += 5

    # Setup quality
    if setup in ("FRESH BREAKOUT", "RETEST + HOLD"):
        score += 10
    elif setup == "BREAKOUT WATCH":
        score += 5

    return int(min(score, 100))


def analyze_stock(symbol, hist, turnover_rank, turnover):
    latest = hist.iloc[-1]

    close = float(latest["Close"])
    ema20 = float(latest["EMA20"])
    ema50 = float(latest["EMA50"])
    rsi14 = float(latest["RSI14"])
    volume_ratio = float(latest["VolumeRatio"])
    prev20_high = float(latest["Prev20High"])
    atr14 = float(latest["ATR14"])
    range20 = float(latest["Range20Pct"])
    daily_change = float(latest["DailyChangePct"])
    slope = float(latest["EMA20SlopePct"])

    if not np.isfinite(close):
        return None

    # -----------------------------
    # HARD QUALITY FILTERS
    # -----------------------------
    if rsi14 >= RSI_HARD_REJECT:
        return None

    if ema20 <= ema50:
        return None

    if close <= ema20:
        return None

    if range20 > 18:
        return None

    if slope <= 0:
        return None

    if rsi14 < RSI_BUY_MIN:
        return None

    if rsi14 >= RSI_WATCH_MAX:
        return None

    previous_breakout = get_previous_breakout(hist)

    setup = None
    breakout_level = prev20_high
    breakout_date = ""

    # -----------------------------
    # 1. FRESH BREAKOUT
    # -----------------------------
    if (
        close > prev20_high
        and volume_ratio >= MIN_VOLUME_RATIO_BUY
        and RSI_BUY_MIN <= rsi14 < RSI_BUY_MAX
    ):
        extension_pct = ((close - prev20_high) / prev20_high) * 100

        if extension_pct <= MAX_BREAKOUT_EXTENSION_PCT:
            setup = "FRESH BREAKOUT"
            breakout_level = prev20_high
            breakout_date = latest.name.strftime("%Y-%m-%d")

    # -----------------------------
    # 2. TRUE RETEST + HOLD
    # -----------------------------
    if setup is None and previous_breakout is not None:
        breakout_level = previous_breakout["level"]
        breakout_date = pd.Timestamp(previous_breakout["date"]).strftime("%Y-%m-%d")

        distance_from_breakout = (
            (close - breakout_level) / breakout_level
        ) * 100

        low_distance = (
            (float(latest["Low"]) - breakout_level) / breakout_level
        ) * 100

        if (
            volume_ratio >= MIN_VOLUME_RATIO_BUY
            and RSI_BUY_MIN <= rsi14 < RSI_BUY_MAX
            and low_distance >= -RETEST_MAX_BELOW_PCT
            and low_distance <= RETEST_MAX_ABOVE_PCT
            and close >= breakout_level
            and distance_from_breakout <= MAX_BREAKOUT_EXTENSION_PCT
            and distance_from_breakout >= -RETEST_MAX_BELOW_PCT
        ):
            setup = "RETEST + HOLD"

    # -----------------------------
    # 3. HIGH-QUALITY BREAKOUT WATCH
    # -----------------------------
    if setup is None:
        distance_below = (
            (prev20_high - close) / prev20_high
        ) * 100

        if (
            0 <= distance_below <= WATCH_DISTANCE_PCT
            and volume_ratio >= MIN_VOLUME_RATIO_WATCH
            and RSI_BUY_MIN <= rsi14 < RSI_WATCH_MAX
        ):
            setup = "BREAKOUT WATCH"
            breakout_level = prev20_high
            breakout_date = ""

    if setup is None:
        return None

    score = calculate_score(latest, setup)

    if setup == "BREAKOUT WATCH":
        if score < MIN_WATCH_SCORE:
            return None
    else:
        if score < MIN_BUY_SCORE:
            return None

    # Entry:
    # BUY = current close.
    # WATCH = breakout trigger level.
    entry = close if setup != "BREAKOUT WATCH" else breakout_level

    levels = calculate_levels(entry, hist)
    if levels is None:
        return None

    chart = (
        "https://www.tradingview.com/chart/?symbol=NSE%3A"
        + symbol
    )

    return {
        "NSE Code": symbol,
        "Turnover Rank": int(turnover_rank),
        "Turnover": round(float(turnover), 2),
        "Close": round(close, 2),
        "EMA20": round(ema20, 2),
        "EMA50": round(ema50, 2),
        "RSI14": round(rsi14, 2),
        "Volume Ratio": round(volume_ratio, 2),
        "20-Day High": round(float(hist["High"].tail(20).max()), 2),
        "Breakout Level": round(breakout_level, 2),
        "Entry": round(levels["Entry"], 2),
        "Stop Loss": round(levels["Stop Loss"], 2),
        "Target 1": round(levels["Target 1"], 2),
        "Target 2": round(levels["Target 2"], 2),
        "Risk %": round(levels["Risk %"], 2),
        "Today Change %": round(daily_change, 2),
        "Setup": setup,
        "Strength Score": score,
        "20-Day Range %": round(range20, 2),
        "ATR14": round(atr14, 2),
        "Breakout Date": breakout_date,
        "Chart": chart,
    }


def load_universe(ws):
    records = ws.get_all_records()
    if not records:
        raise ValueError(f"{NIFTY_SHEET} sheet is empty.")

    df = pd.DataFrame(records)

    symbol_col = None
    for col in ["NSE Code", "Symbol", "symbol", "NSECODE"]:
        if col in df.columns:
            symbol_col = col
            break

    if symbol_col is None:
        raise ValueError(
            "NIFTY200 must contain 'NSE Code' or 'Symbol'."
        )

    df["NSE Code"] = df[symbol_col].apply(clean_symbol)

    if "Turnover" not in df.columns:
        raise ValueError("NIFTY200 must contain 'Turnover'.")

    df["Turnover"] = df["Turnover"].apply(to_float)
    df = df[df["NSE Code"].notna()]
    df = df[df["NSE Code"].astype(str).str.len() > 0]
    df = df[df["NSE Code"].apply(is_allowed_symbol)]
    df = df[df["Turnover"].notna()]

    # Stable turnover ranking.
    df = df.sort_values(
        "Turnover",
        ascending=False,
        kind="mergesort"
    ).reset_index(drop=True)

    df["Turnover Rank"] = np.arange(1, len(df) + 1)

    # Keep top 200 after exclusions.
    df = df.head(200).copy()

    return df


def download_history(symbols):
    tickers = [f"{s}.NS" for s in symbols]

    print(f"Downloading Yahoo Finance history for {len(tickers)} symbols...")

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
        print("Bulk Yahoo download failed:", e)
        return {}

    histories = {}

    if data is None or data.empty:
        return histories

    for symbol in symbols:
        ticker = f"{symbol}.NS"

        try:
            if len(symbols) == 1:
                hist = data.copy()
            else:
                if ticker not in data.columns.get_level_values(0):
                    continue
                hist = data[ticker].copy()

            hist = prepare_history(hist)

            if hist is not None:
                histories[symbol] = hist

        except Exception as e:
            print(f"History error {symbol}: {e}")

    return histories


def write_final_sheet(ws, rows):
    # Always clear old data so no stale header/columns remain.
    ws.clear()

    values = [OUTPUT_COLUMNS]

    for row in rows:
        values.append([row.get(col, "") for col in OUTPUT_COLUMNS])

    end_row = max(len(values), 1)

    # Exact A:V output.
    ws.update(
        f"A1:V{end_row}",
        values,
        value_input_option="USER_ENTERED",
    )

    # Header formatting.
    try:
        ws.format(
            "A1:V1",
            {
                "textFormat": {"bold": True},
                "horizontalAlignment": "CENTER",
            },
        )

        if len(values) > 1:
            ws.format(
                f"A2:V{end_row}",
                {
                    "horizontalAlignment": "CENTER",
                },
            )

        ws.freeze(rows=1)

    except Exception as e:
        print("Formatting warning:", e)


def diagnostics(rows):
    if not rows:
        print("No candidates found.")
        return

    df = pd.DataFrame(rows)

    assert len(df["Turnover Rank"]) == len(
        set(df["Turnover Rank"])
    ), "Duplicate turnover ranks found."

    assert (df["Risk %"] <= MAX_RISK_PCT + 1e-9).all(), \
        "Risk > 5% found."

    buy = df[df["Setup"].isin(["FRESH BREAKOUT", "RETEST + HOLD"])]

    if not buy.empty:
        assert (buy["RSI14"] >= RSI_BUY_MIN).all()
        assert (buy["RSI14"] < RSI_BUY_MAX).all()
        assert (buy["Volume Ratio"] >= MIN_VOLUME_RATIO_BUY).all()

    watch = df[df["Setup"] == "BREAKOUT WATCH"]

    if not watch.empty:
        assert (watch["RSI14"] >= RSI_BUY_MIN).all()
        assert (watch["RSI14"] < RSI_WATCH_MAX).all()
        assert (watch["Volume Ratio"] >= MIN_VOLUME_RATIO_WATCH).all()

    print("\nDiagnostics:")
    print(f"Candidates: {len(df)}")
    print(f"BUY: {len(buy)}")
    print(f"WATCH: {len(watch)}")
    print(f"Max risk: {df['Risk %'].max():.2f}%")
    print(f"Max score: {df['Strength Score'].max()}")


def main():
    print("=" * 65)
    print("NIFTY 200 SWING SNIPER V2.1.4")
    print("=" * 65)

    creds = get_credentials()
    gc = gspread.authorize(creds)

    sh = gc.open_by_key(SPREADSHEET_ID)
    universe_ws = sh.worksheet(NIFTY_SHEET)
    final_ws = sh.worksheet(FINAL_SHEET)

    universe = load_universe(universe_ws)

    print(f"Universe loaded: {len(universe)} stocks")

    symbols = universe["NSE Code"].tolist()
    histories = download_history(symbols)

    print(f"Usable histories: {len(histories)}")

    candidates = []

    for _, u in universe.iterrows():
        symbol = u["NSE Code"]

        if symbol not in histories:
            continue

        try:
            result = analyze_stock(
                symbol=symbol,
                hist=histories[symbol],
                turnover_rank=int(u["Turnover Rank"]),
                turnover=float(u["Turnover"]),
            )

            if result:
                candidates.append(result)

        except Exception as e:
            print(f"Analysis error {symbol}: {e}")

    # BUY first, then WATCH; highest score first.
    setup_priority = {
        "FRESH BREAKOUT": 0,
        "RETEST + HOLD": 1,
        "BREAKOUT WATCH": 2,
    }

    candidates.sort(
        key=lambda x: (
            setup_priority.get(x["Setup"], 9),
            -x["Strength Score"],
            x["Turnover Rank"],
        )
    )

    # Hard cap final list.
    candidates = candidates[:MAX_FINAL_STOCKS]

    diagnostics(candidates)

    write_final_sheet(final_ws, candidates)

    print("\nFinal List updated successfully.")
    print(f"Rows written: {len(candidates)}")
    print("Columns written: A:V (exactly 22 columns)")
    print("=" * 65)


if __name__ == "__main__":
    main()
