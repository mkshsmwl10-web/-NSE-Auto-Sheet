import os
import json
import time
import warnings
warnings.filterwarnings("ignore")

import gspread
import pandas as pd
import numpy as np
import yfinance as yf
from oauth2client.service_account import ServiceAccountCredentials

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

MIN_VOLUME_RATIO = 1.50
RSI_BUY_MIN = 55
RSI_BUY_MAX = 68
RSI_WATCH_MAX = 70
RSI_HARD_REJECT = 80

MAX_BREAKOUT_EXTENSION_PCT = 3.0
WATCH_DISTANCE_PCT = 2.0
RETEST_MAX_ABOVE_PCT = 1.0
RETEST_MAX_BELOW_PCT = 3.0

MAX_RISK_PCT = 5.0
TARGET1_R = 1.5
TARGET2_R = 3.0

RETEST_LOOKBACK_DAYS = 5
MAX_FINAL_STOCKS = 12
MIN_BUY_SCORE = 70
MIN_WATCH_SCORE = 60

EXCLUDE_WORDS = [
    "ETF", "BEES", "GOLD", "LIQUID", "SILVER", "INDEX"
]

OUTPUT_COLUMNS = [
    "NSE Code", "Turnover Rank", "Turnover", "Close", "EMA20", "EMA50",
    "RSI14", "Volume Ratio", "20-Day High", "Breakout Level", "Entry",
    "Stop Loss", "Target 1", "Target 2", "Risk %", "Today Change %",
    "Setup", "Strength Score", "20-Day Range %", "ATR14", "Breakout Date",
    "Chart"
]

def get_google_client():
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]

    secret = os.getenv("GCP_CREDENTIALS")

    if secret:
        print("Using GCP_CREDENTIALS environment secret.")
        info = json.loads(secret)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(info, scopes)
    elif os.path.exists("credentials.json"):
        print("Using local credentials.json.")
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            "credentials.json", scopes
        )
    else:
        raise FileNotFoundError(
            "GCP_CREDENTIALS secret not found and credentials.json is missing."
        )

    return gspread.authorize(creds)

def normalize_columns(df):
    df.columns = [
        str(c).strip().lower().replace(" ", "_").replace("-", "_")
        for c in df.columns
    ]

    aliases = {
        "symbol": ["symbol", "nse_code", "nsecode", "code"],
        "turnover": ["turnover", "turnover_value", "traded_value"],
        "turnover_rank": ["turnover_rank", "rank"],
    }

    rename = {}
    for target, candidates in aliases.items():
        for c in candidates:
            if c in df.columns:
                rename[c] = target
                break

    return df.rename(columns=rename)

def get_universe(ws):
    print(f"Reading sheet: {NIFTY_SHEET}")
    values = ws.get_all_records()
    df = pd.DataFrame(values)

    if df.empty:
        raise ValueError("NIFTY200 sheet is empty.")

    df = normalize_columns(df)

    if "symbol" not in df.columns:
        raise ValueError(
            "NIFTY200 must contain 'NSE Code' or 'Symbol' column."
        )

    if "turnover" not in df.columns:
        print("WARNING: Turnover column not found. Ranking will use sheet order.")
        df["turnover"] = 0.0

    df["symbol"] = (
        df["symbol"].astype(str).str.upper().str.strip()
    )
    df["symbol"] = df["symbol"].str.replace(".NS", "", regex=False)

    df["turnover"] = pd.to_numeric(
        df["turnover"], errors="coerce"
    ).fillna(0)

    df = df[
        df["symbol"].notna() &
        (df["symbol"] != "") &
        (df["symbol"] != "NAN")
    ].copy()

    df = df[
        ~df["symbol"].apply(
            lambda x: any(word in x for word in EXCLUDE_WORDS)
        )
    ].copy()

    df = df.drop_duplicates("symbol").reset_index(drop=True)

    # Robust unique turnover ranking
    df = df.sort_values(
        ["turnover", "symbol"],
        ascending=[False, True],
        kind="mergesort"
    ).reset_index(drop=True)

    df["turnover_rank"] = np.arange(1, len(df) + 1)

    df = df.head(200).copy()

    print(f"Universe stocks: {len(df)}")
    return df

def rsi(series, length=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / length, adjust=False, min_periods=length
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / length, adjust=False, min_periods=length
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out

def atr(df, length=14):
    prev_close = df["Close"].shift(1)

    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - prev_close).abs()
    tr3 = (df["Low"] - prev_close).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    return tr.ewm(
        alpha=1 / length, adjust=False, min_periods=length
    ).mean()

def prepare_history(raw):
    if raw is None or raw.empty:
        return None

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    required = ["Open", "High", "Low", "Close", "Volume"]
    for c in required:
        if c not in raw.columns:
            return None

    df = raw[required].copy()

    for c in required:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["High", "Low", "Close"]).copy()
    df = df[~df.index.duplicated(keep="last")].sort_index()

    if len(df) < MIN_HISTORY_ROWS:
        return None

    df["EMA20"] = df["Close"].ewm(
        span=EMA_FAST, adjust=False
    ).mean()

    df["EMA50"] = df["Close"].ewm(
        span=EMA_SLOW, adjust=False
    ).mean()

    df["RSI14"] = rsi(df["Close"], RSI_LENGTH)
    df["ATR14"] = atr(df, ATR_LENGTH)

    df["Prev20High"] = df["High"].rolling(
        BREAKOUT_LOOKBACK
    ).max().shift(1)

    df["Prev20Low"] = df["Low"].rolling(
        BREAKOUT_LOOKBACK
    ).min().shift(1)

    df["VolumeAvg20"] = df["Volume"].rolling(
        VOLUME_LENGTH
    ).mean()

    df["VolumeRatio"] = (
        df["Volume"] / df["VolumeAvg20"].replace(0, np.nan)
    )

    df["Range20Pct"] = (
        (df["High"].rolling(BREAKOUT_LOOKBACK).max()
         - df["Low"].rolling(BREAKOUT_LOOKBACK).min())
        / df["Close"] * 100
    )

    df["EMA20SlopePct"] = (
        (df["EMA20"] - df["EMA20"].shift(5))
        / df["EMA20"].shift(5) * 100
    )

    df["DailyChangePct"] = df["Close"].pct_change() * 100

    return df

def get_previous_breakout(df):
    latest = df.iloc[-1]

    start = max(0, len(df) - RETEST_LOOKBACK_DAYS - 1)
    end = len(df) - 1

    for i in range(end - 1, start - 1, -1):
        row = df.iloc[i]

        if pd.isna(row["Prev20High"]):
            continue

        if row["Close"] > row["Prev20High"]:
            return float(row["Prev20High"]), df.index[i]

    return None, None

def score_setup(row, setup):
    score = 0

    if row["EMA20"] > row["EMA50"]:
        score += 20

    if row["Close"] > row["EMA20"]:
        score += 15

    if row["RSI14"] >= 60:
        score += 15
    elif row["RSI14"] >= 55:
        score += 10

    if row["VolumeRatio"] >= 2.0:
        score += 15
    elif row["VolumeRatio"] >= 1.5:
        score += 10

    if row["EMA20SlopePct"] > 0:
        score += 10

    if row["Range20Pct"] <= 12:
        score += 10
    elif row["Range20Pct"] <= 18:
        score += 5

    if setup == "FRESH BREAKOUT":
        score += 10
    elif setup == "RETEST + HOLD":
        score += 10
    elif setup == "BREAKOUT WATCH":
        score += 5

    return min(score, 100)

def make_trade_levels(df, setup, breakout_level):
    row = df.iloc[-1]

    close = float(row["Close"])
    atr_value = float(row["ATR14"])

    recent_low = float(df["Low"].tail(5).min())

    if setup == "BREAKOUT WATCH":
        entry = breakout_level
    else:
        entry = close

    atr_stop = entry - (1.5 * atr_value)
    structure_stop = recent_low * 0.995

    stop = max(atr_stop, structure_stop)

    if stop >= entry:
        stop = entry - atr_value

    risk_pct = (entry - stop) / entry * 100

    # If risk is too high, reject the trade.
    if risk_pct <= 0 or risk_pct > MAX_RISK_PCT:
        return None

    risk_per_share = entry - stop

    target1 = entry + TARGET1_R * risk_per_share
    target2 = entry + TARGET2_R * risk_per_share

    return {
        "Entry": entry,
        "Stop Loss": stop,
        "Target 1": target1,
        "Target 2": target2,
        "Risk %": risk_pct,
    }

def analyze_stock(symbol, df, turnover_rank, turnover):
    if df is None or len(df) < MIN_HISTORY_ROWS:
        return None

    row = df.iloc[-1]

    needed = [
        "Close", "EMA20", "EMA50", "RSI14", "ATR14",
        "Prev20High", "VolumeRatio", "Range20Pct",
        "EMA20SlopePct"
    ]

    if any(pd.isna(row[x]) for x in needed):
        return None

    close = float(row["Close"])
    ema20 = float(row["EMA20"])
    ema50 = float(row["EMA50"])
    rsi_value = float(row["RSI14"])
    volume_ratio = float(row["VolumeRatio"])
    prev20_high = float(row["Prev20High"])
    range20 = float(row["Range20Pct"])

    if rsi_value >= RSI_HARD_REJECT:
        return None

    if ema20 <= ema50:
        return None

    if close <= ema20:
        return None

    if range20 > 18:
        return None

    breakout_level = None
    breakout_date = None
    setup = None

    extension_pct = (
        (close - prev20_high) / prev20_high * 100
        if prev20_high > 0 else 999
    )

    # ---------------------------------------------------------
    # 1. FRESH BREAKOUT
    # ---------------------------------------------------------
    if (
        close > prev20_high
        and volume_ratio >= MIN_VOLUME_RATIO
        and RSI_BUY_MIN <= rsi_value < RSI_BUY_MAX
        and extension_pct <= MAX_BREAKOUT_EXTENSION_PCT
    ):
        setup = "FRESH BREAKOUT"
        breakout_level = prev20_high
        breakout_date = df.index[-1]

    # ---------------------------------------------------------
    # 2. TRUE RETEST + HOLD
    # ---------------------------------------------------------
    if setup is None:
        old_breakout, old_date = get_previous_breakout(df)

        if old_breakout is not None:
            low_distance_pct = (
                (float(row["Low"]) - old_breakout)
                / old_breakout * 100
            )

            close_distance_pct = (
                (close - old_breakout)
                / old_breakout * 100
            )

            retest_valid = (
                -RETEST_MAX_BELOW_PCT <= low_distance_pct <= RETEST_MAX_ABOVE_PCT
                and close > old_breakout
                and 0 <= close_distance_pct <= MAX_BREAKOUT_EXTENSION_PCT
                and RSI_BUY_MIN <= rsi_value < RSI_BUY_MAX
            )

            if retest_valid:
                setup = "RETEST + HOLD"
                breakout_level = old_breakout
                breakout_date = old_date

    # ---------------------------------------------------------
    # 3. BREAKOUT WATCH
    # ---------------------------------------------------------
    if setup is None:
        distance_below = (
            (prev20_high - close) / prev20_high * 100
        )

        if (
            0 <= distance_below <= WATCH_DISTANCE_PCT
            and RSI_BUY_MIN <= rsi_value <= RSI_WATCH_MAX
        ):
            setup = "BREAKOUT WATCH"
            breakout_level = prev20_high
            breakout_date = ""

    if setup is None:
        return None

    # For fresh/retest BUY setups, require strong volume.
    if setup in ["FRESH BREAKOUT", "RETEST + HOLD"]:
        if volume_ratio < MIN_VOLUME_RATIO:
            return None

    levels = make_trade_levels(df, setup, breakout_level)

    if levels is None:
        return None

    score = score_setup(row, setup)

    if setup in ["FRESH BREAKOUT", "RETEST + HOLD"]:
        if score < MIN_BUY_SCORE:
            return None
    else:
        if score < MIN_WATCH_SCORE:
            return None

    chart = (
        "https://www.tradingview.com/chart/?symbol=NSE%3A"
        + str(symbol).replace("&", "%26")
    )

    return {
        "NSE Code": symbol,
        "Turnover Rank": int(turnover_rank),
        "Turnover": float(turnover),
        "Close": close,
        "EMA20": ema20,
        "EMA50": ema50,
        "RSI14": rsi_value,
        "Volume Ratio": volume_ratio,
        "20-Day High": prev20_high,
        "Breakout Level": breakout_level,
        "Entry": levels["Entry"],
        "Stop Loss": levels["Stop Loss"],
        "Target 1": levels["Target 1"],
        "Target 2": levels["Target 2"],
        "Risk %": levels["Risk %"],
        "Today Change %": float(row["DailyChangePct"]),
        "Setup": setup,
        "Strength Score": score,
        "20-Day Range %": range20,
        "ATR14": float(row["ATR14"]),
        "Breakout Date": (
            pd.Timestamp(breakout_date).strftime("%Y-%m-%d")
            if breakout_date != "" and breakout_date is not None
            else ""
        ),
        "Chart": chart,
    }

def download_all_history(symbols):
    print(f"Downloading {len(symbols)} stocks from Yahoo Finance...")
    results = {}

    tickers = [f"{s}.NS" for s in symbols]

    try:
        data = yf.download(
            tickers=tickers,
            period=HISTORY_PERIOD,
            interval="1d",
            auto_adjust=False,
            group_by="ticker",
            threads=True,
            progress=False
        )
    except Exception as e:
        print("Bulk download failed:", e)
        data = None

    if data is not None and not data.empty:
        for symbol in symbols:
            ticker = f"{symbol}.NS"

            try:
                if len(symbols) == 1:
                    raw = data.copy()
                elif isinstance(data.columns, pd.MultiIndex):
                    if ticker not in data.columns.get_level_values(0):
                        continue
                    raw = data[ticker].copy()
                else:
                    raw = data.copy()

                prepared = prepare_history(raw)

                if prepared is not None:
                    results[symbol] = prepared
            except Exception:
                continue

    print(f"Historical data available: {len(results)} stocks")

    # Fallback for missing symbols
    missing = [s for s in symbols if s not in results]

    if missing:
        print(f"Retrying {len(missing)} missing symbols individually...")

        for i, symbol in enumerate(missing, 1):
            try:
                raw = yf.download(
                    f"{symbol}.NS",
                    period=HISTORY_PERIOD,
                    interval="1d",
                    auto_adjust=False,
                    progress=False
                )

                prepared = prepare_history(raw)

                if prepared is not None:
                    results[symbol] = prepared

            except Exception as e:
                print(f"  {symbol}: failed")

            time.sleep(0.05)

    print(f"Final historical data count: {len(results)}")
    return results

def write_final_sheet(client, rows):
    ws = client.open_by_key(SPREADSHEET_ID).worksheet(FINAL_SHEET)

    ws.clear()

    values = [OUTPUT_COLUMNS]

    for row in rows:
        values.append([
            row.get(col, "") for col in OUTPUT_COLUMNS
        ])

    ws.update(
        range_name=f"A1:V{len(values)}",
        values=values,
        value_input_option="USER_ENTERED"
    )

    # Basic formatting
    try:
        ws.freeze(rows=1)
        ws.format(
            "A1:V1",
            {
                "textFormat": {"bold": True},
                "horizontalAlignment": "CENTER"
            }
        )
        ws.format(
            f"A2:V{len(values)}",
            {"verticalAlignment": "MIDDLE"}
        )
    except Exception:
        pass

    print(f"Final List updated: {len(rows)} stocks")

def main():
    print("=" * 70)
    print("NIFTY 200 SWING SNIPER V2.1.3")
    print("=" * 70)

    print("Connecting to Google Sheets...")
    client = get_google_client()
    print("Google Sheets connection successful.")

    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    nifty_ws = spreadsheet.worksheet(NIFTY_SHEET)

    universe = get_universe(nifty_ws)

    symbols = universe["symbol"].tolist()

    history = download_all_history(symbols)

    candidates = []

    for _, urow in universe.iterrows():
        symbol = urow["symbol"]

        if symbol not in history:
            continue

        result = analyze_stock(
            symbol=symbol,
            df=history[symbol],
            turnover_rank=urow["turnover_rank"],
            turnover=urow["turnover"]
        )

        if result is not None:
            candidates.append(result)

    if candidates:
        candidates.sort(
            key=lambda x: (
                x["Strength Score"],
                x["Setup"] != "FRESH BREAKOUT",
                -x["Risk %"]
            ),
            reverse=True
        )

        # Prefer BUY setups over WATCH if score is close.
        candidates = sorted(
            candidates,
            key=lambda x: (
                1 if x["Setup"] in ["FRESH BREAKOUT", "RETEST + HOLD"] else 0,
                x["Strength Score"],
                -x["Risk %"]
            ),
            reverse=True
        )

        candidates = candidates[:MAX_FINAL_STOCKS]

    print("-" * 70)
    print(f"Candidates found: {len(candidates)}")

    for x in candidates:
        print(
            f"{x['NSE Code']:15s} | "
            f"{x['Setup']:18s} | "
            f"Score {x['Strength Score']:3d} | "
            f"RSI {x['RSI14']:.2f} | "
            f"Risk {x['Risk %']:.2f}%"
        )

    write_final_sheet(client, candidates)

    # Diagnostics
    if candidates:
        ranks = [x["Turnover Rank"] for x in candidates]
        ranges = [x["20-Day Range %"] for x in candidates]
        risks = [x["Risk %"] for x in candidates]

        assert len(ranks) == len(set(ranks)), "Duplicate turnover ranks detected."
        assert all(x <= 18 for x in ranges), "Range filter failed."
        assert all(x <= MAX_RISK_PCT for x in risks), "Risk filter failed."

        for x in candidates:
            if x["Setup"] in ["FRESH BREAKOUT", "RETEST + HOLD"]:
                assert RSI_BUY_MIN <= x["RSI14"] < RSI_BUY_MAX

    print("=" * 70)
    print("V2.1.3 completed successfully.")
    print("=" * 70)

if __name__ == "__main__":
    main()
