#!/usr/bin/env python3
"""
NIFTY 200 Positive Divergence + Cup / Cup-with-Handle Scanner V1.3

Keeps:
- RSI Positive Divergence
- Classic Positive Divergence
- Cup
- Cup with Handle

Cup patterns are checked on Daily, Weekly and Monthly OHLC data.
The scanner reports whether the pattern is BEFORE breakout, BREAKOUT,
or AFTER breakout.

Final List keeps Score >= 60 and removes the unwanted columns:
Stock/NSE Code, RSI Improvement %, EMA20, EMA50, Support, Entry,
Target 1, Target 2, Risk %.

NOTE:
Cup/cup-with-handle detection is rule-based, not a discretionary chart
pattern engine. Thresholds can be tuned in the CONFIG section.
"""

import os
import sys
import json
import math
import re
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials


# =========================
# CONFIG
# =========================

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID",
    "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E",
)

FINAL_LIST_SHEET = os.environ.get("FINAL_LIST_SHEET", "Final List")

MIN_HISTORY_ROWS = 100
MIN_SCORE = 60

# Cup detection
CUP_MIN_BARS = {
    "Daily": 40,
    "Weekly": 20,
    "Monthly": 12,
}
CUP_MAX_BARS = {
    "Daily": 180,
    "Weekly": 80,
    "Monthly": 48,
}

# Minimum depth from rim to cup bottom.
CUP_MIN_DEPTH = 0.12
CUP_MAX_DEPTH = 0.45

# The right side should recover close to the left rim.
RIM_TOLERANCE = 0.08

# Handle is a short consolidation/pullback near the right rim.
HANDLE_MAX_RETRACE = 0.18
HANDLE_MAX_BARS_RATIO = 0.35

# Breakout confirmation:
# close must exceed rim by this fraction.
BREAKOUT_BUFFER = 0.005

# Breakout can be considered recent for AFTER BREAKOUT.
RECENT_BREAKOUT_BARS = 12


REMOVE_COLUMNS = {
    "stock/nse code",
    "nse code",
    "stock code",
    "stock/nse",
    "rsi improvement %",
    "rsi improvement",
    "ema20",
    "ema 20",
    "ema50",
    "ema 50",
    "support",
    "entry",
    "target 1",
    "target1",
    "target 2",
    "target2",
    "risk %",
    "risk",
}


# =========================
# GOOGLE SHEETS
# =========================

def normalize_header(x):
    return re.sub(r"\s+", " ", str(x or "").strip().lower())


def get_credentials():
    raw = os.environ.get("GCP_CREDENTIALS", "").strip()

    if not raw:
        raise RuntimeError("GCP_CREDENTIALS is missing.")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    if raw.startswith("{"):
        return Credentials.from_service_account_info(
            json.loads(raw),
            scopes=scopes,
        )

    if os.path.exists(raw):
        return Credentials.from_service_account_file(
            raw,
            scopes=scopes,
        )

    raise RuntimeError(
        "GCP_CREDENTIALS is not valid JSON or a valid credentials file."
    )


def write_final_list(rows):
    creds = get_credentials()
    client = gspread.authorize(creds)

    sh = client.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(FINAL_LIST_SHEET)

    if not rows:
        ws.clear()
        return

    headers = list(rows[0].keys())

    # Remove unwanted columns from final output.
    keep_headers = [
        h for h in headers
        if normalize_header(h) not in REMOVE_COLUMNS
    ]

    # Score column must remain.
    if not any(normalize_header(h) == "score" for h in keep_headers):
        raise RuntimeError("Score column disappeared from output.")

    output = [keep_headers]

    for row in rows:
        output.append([row.get(h, "") for h in keep_headers])

    ws.clear()
    ws.update(
        "A1",
        output,
        value_input_option="USER_ENTERED",
    )

    try:
        ws.freeze(rows=1)
    except Exception:
        pass

    print("Final List updated.")
    print("Rows:", len(rows))
    print("Columns:", len(keep_headers))


# =========================
# DATA
# =========================

def download_ohlcv(symbol, period="5y", interval="1d"):
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(
            period=period,
            interval=interval,
            auto_adjust=False,
        )

        if df is None or df.empty:
            return None

        df = df.reset_index()

        # Standardize names.
        df.columns = [
            str(c).strip().lower().replace(" ", "_")
            for c in df.columns
        ]

        required = {"close", "high", "low", "volume"}
        if not required.issubset(set(df.columns)):
            return None

        df = df.dropna(subset=["close", "high", "low"])
        return df

    except Exception as e:
        print("Download error:", symbol, e)
        return None


def resample_ohlcv(df, timeframe):
    x = df.copy()

    if "date" in x.columns:
        date_col = "date"
    elif "datetime" in x.columns:
        date_col = "datetime"
    else:
        return None

    x[date_col] = pd.to_datetime(x[date_col], errors="coerce")
    x = x.dropna(subset=[date_col])
    x = x.set_index(date_col)

    rule = {
        "Daily": "1D",
        "Weekly": "W-FRI",
        "Monthly": "ME",
    }[timeframe]

    out = x.resample(rule).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()

    return out.reset_index()


# =========================
# RSI DIVERGENCE
# =========================

def rsi(series, period=14):
    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False,
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False,
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def local_lows(series, left=3, right=3):
    values = series.to_numpy(dtype=float)
    lows = []

    for i in range(left, len(values) - right):
        window = values[i-left:i+right+1]
        if values[i] == np.min(window):
            lows.append(i)

    return lows


def positive_divergence(df):
    if df is None or len(df) < MIN_HISTORY_ROWS:
        return False, "", 0

    close = df["close"].astype(float)
    rs = rsi(close, 14)

    lows = local_lows(close, 3, 3)

    if len(lows) < 2:
        return False, "", 0

    i1, i2 = lows[-2], lows[-1]

    price1 = close.iloc[i1]
    price2 = close.iloc[i2]
    rsi1 = rs.iloc[i1]
    rsi2 = rs.iloc[i2]

    if pd.isna(rsi1) or pd.isna(rsi2):
        return False, "", 0

    lower_price = price2 < price1 * 0.995
    higher_rsi = rsi2 >= rsi1 + 2

    if lower_price and higher_rsi:
        return True, "RSI Positive Divergence", 65

    # Classic positive divergence can use a lower low with improving
    # momentum even if the RSI improvement is smaller.
    if lower_price and rsi2 > rsi1:
        return True, "Classic Positive Divergence", 60

    return False, "", 0


# =========================
# CUP / CUP WITH HANDLE
# =========================

def smooth(values, window):
    if len(values) < window:
        return values
    return pd.Series(values).rolling(
        window=window,
        center=True,
        min_periods=1,
    ).mean().to_numpy()


def detect_cup(df, timeframe):
    """
    Returns:
      pattern: None / Cup / Cup with Handle
      status: BEFORE BREAKOUT / BREAKOUT / AFTER BREAKOUT
      score: pattern score
    """

    if df is None:
        return None, "", 0

    min_bars = CUP_MIN_BARS[timeframe]
    max_bars = CUP_MAX_BARS[timeframe]

    if len(df) < min_bars:
        return None, "", 0

    # Work on recent history but allow enough room for a large cup.
    data = df.tail(min(len(df), max_bars + 30)).copy()

    close = data["close"].astype(float).to_numpy()
    high = data["high"].astype(float).to_numpy()
    low = data["low"].astype(float).to_numpy()

    if len(close) < min_bars:
        return None, "", 0

    sm = smooth(close, max(3, len(close) // 30))

    # Find candidate left rim in the first half and bottom afterward.
    n = len(sm)

    left_zone_end = int(n * 0.45)
    right_zone_start = int(n * 0.55)

    if left_zone_end < 5 or right_zone_start >= n - 5:
        return None, "", 0

    left_candidates = np.argsort(sm[:left_zone_end])[-10:]
    right_candidates = np.argsort(sm[right_zone_start:])[-10:] + right_zone_start

    best = None

    for li in left_candidates:
        left_rim = sm[li]

        # Bottom must be meaningfully after left rim.
        bottom_slice = low[li + 3:right_zone_start]
        if len(bottom_slice) < 5:
            continue

        rel_bottom = int(np.argmin(bottom_slice))
        bi = li + 3 + rel_bottom
        bottom = low[bi]

        depth = (left_rim - bottom) / left_rim if left_rim else 0

        if depth < CUP_MIN_DEPTH or depth > CUP_MAX_DEPTH:
            continue

        for ri in right_candidates:
            if ri <= bi:
                continue

            right_rim = sm[ri]

            # Right rim should recover close to left rim.
            rim_similarity = abs(right_rim - left_rim) / left_rim

            if rim_similarity > RIM_TOLERANCE:
                continue

            # Cup should have a rounded/gradual recovery rather than
            # an immediate V-shape.
            left_span = bi - li
            right_span = ri - bi

            if left_span < 5 or right_span < 5:
                continue

            balance = min(left_span, right_span) / max(left_span, right_span)

            if balance < 0.25:
                continue

            candidate = {
                "li": li,
                "bi": bi,
                "ri": ri,
                "left_rim": left_rim,
                "right_rim": right_rim,
                "depth": depth,
                "balance": balance,
            }

            if best is None or candidate["depth"] > best["depth"]:
                best = candidate

    if best is None:
        return None, "", 0

    li = best["li"]
    bi = best["bi"]
    ri = best["ri"]
    rim = max(best["left_rim"], best["right_rim"])

    current_close = close[-1]

    # Breakout level is the higher rim.
    breakout_level = rim * (1 + BREAKOUT_BUFFER)

    # Search for breakout after the right rim.
    after_right = close[ri + 1:]

    breakout_index = None

    for j, value in enumerate(after_right, start=ri + 1):
        if value > breakout_level:
            breakout_index = j
            break

    # Handle detection.
    pattern = "Cup"

    handle_start = ri
    handle_end = len(close) - 1
    handle = close[handle_start:handle_end + 1]

    if len(handle) >= 3:
        handle_high = np.max(handle)
        handle_low = np.min(handle)

        handle_retrace = (
            (handle_high - handle_low) / handle_high
            if handle_high
            else 0
        )

        max_handle_bars = max(
            3,
            int((ri - li) * HANDLE_MAX_BARS_RATIO)
        )

        handle_bars = len(handle)

        # Handle should be relatively short and shallow.
        if (
            handle_bars <= max_handle_bars
            and handle_retrace <= HANDLE_MAX_RETRACE
            and handle_low >= best["bi"] if False else True
        ):
            # Additional condition: handle low should remain above
            # the cup midpoint, avoiding a deep retracement.
            cup_mid = bottom + (rim - bottom) * 0.50

            if handle_low >= cup_mid:
                pattern = "Cup with Handle"

    if breakout_index is not None:
        # If breakout is on the latest few bars => BREAKOUT.
        bars_since = len(close) - 1 - breakout_index

        if bars_since <= 2:
            status = "BREAKOUT"
        elif bars_since <= RECENT_BREAKOUT_BARS:
            status = "AFTER BREAKOUT"
        else:
            status = "AFTER BREAKOUT"
    else:
        status = "BEFORE BREAKOUT"

    score = 60

    # Better score for clean depth / balance.
    if best["depth"] >= 0.18:
        score += 5
    if best["balance"] >= 0.50:
        score += 5
    if pattern == "Cup with Handle":
        score += 5
    if status == "BREAKOUT":
        score += 5

    score = min(score, 80)

    return pattern, status, score


# =========================
# SYMBOL HELPERS
# =========================

def yahoo_symbol(nse_code):
    code = str(nse_code).strip().upper()

    if not code:
        return None

    if code.endswith(".NS"):
        return code

    return code + ".NS"


# =========================
# MAIN SCANNER
# =========================

def scan_symbol(nse_code):
    symbol = yahoo_symbol(nse_code)

    daily = download_ohlcv(symbol, period="5y", interval="1d")

    if daily is None or len(daily) < MIN_HISTORY_ROWS:
        return None

    divergence_found, divergence_type, divergence_score = positive_divergence(
        daily
    )

    patterns = []

    for timeframe in ("Daily", "Weekly", "Monthly"):
        tf_df = resample_ohlcv(daily, timeframe)

        pattern, status, pscore = detect_cup(tf_df, timeframe)

        if pattern:
            patterns.append({
                "timeframe": timeframe,
                "pattern": pattern,
                "status": status,
                "score": pscore,
            })

    # Require either divergence OR cup-family pattern.
    if not divergence_found and not patterns:
        return None

    best_pattern_score = max(
        [p["score"] for p in patterns],
        default=0,
    )

    # Combined score.
    if divergence_found:
        score = max(divergence_score, best_pattern_score)
        if patterns:
            score = min(100, score + 5)
    else:
        score = best_pattern_score

    if score < MIN_SCORE:
        return None

    current_price = float(daily["close"].iloc[-1])

    daily_patterns = [
        p for p in patterns if p["timeframe"] == "Daily"
    ]
    weekly_patterns = [
        p for p in patterns if p["timeframe"] == "Weekly"
    ]
    monthly_patterns = [
        p for p in patterns if p["timeframe"] == "Monthly"
    ]

    def pattern_text(items):
        if not items:
            return ""
        return "; ".join(
            f'{x["pattern"]} - {x["status"]}'
            for x in items
        )

    pattern_names = []
    for p in patterns:
        pattern_names.append(
            f'{p["timeframe"]}: {p["pattern"]}'
        )

    setup_parts = []
    if divergence_found:
        setup_parts.append(divergence_type)
    if pattern_names:
        setup_parts.extend(pattern_names)

    return {
        "NSE Code": nse_code,
        "Setup": " + ".join(setup_parts),
        "Divergence Strength": divergence_type if divergence_found else "",
        "Score": score,
        "Current Price": round(current_price, 2),

        "Daily Pattern": pattern_text(daily_patterns),
        "Weekly Pattern": pattern_text(weekly_patterns),
        "Monthly Pattern": pattern_text(monthly_patterns),

        "Cup Pattern Present":
            "YES" if patterns else "NO",

        "Cup Pattern Timeframes":
            ", ".join(p["timeframe"] for p in patterns),

        "Cup Breakout Status":
            "; ".join(
                f'{p["timeframe"]}: {p["status"]}'
                for p in patterns
            ),
    }


def get_nifty200_codes():
    """
    Reads NIFTY200 sheet and tries common NSE-code headers.
    """
    creds = get_credentials()
    client = gspread.authorize(creds)

    sh = client.open_by_key(SPREADSHEET_ID)

    try:
        ws = sh.worksheet("NIFTY200")
    except gspread.WorksheetNotFound:
        raise RuntimeError("NIFTY200 worksheet not found.")

    values = ws.get_all_values()

    if not values:
        raise RuntimeError("NIFTY200 sheet is empty.")

    headers = values[0]
    normalized = [normalize_header(x) for x in headers]

    code_idx = None

    candidates = [
        "nse code",
        "nse_code",
        "symbol",
        "stock",
        "stock/nse code",
        "code",
    ]

    for candidate in candidates:
        if candidate in normalized:
            code_idx = normalized.index(candidate)
            break

    if code_idx is None:
        # If no header is found, use first column as a fallback.
        code_idx = 0

    codes = []

    for row in values[1:]:
        if code_idx >= len(row):
            continue

        code = str(row[code_idx]).strip().upper()

        if code and code not in codes:
            codes.append(code)

    return codes


def main():
    print("==========================================")
    print("NIFTY 200 DIVERGENCE + CUP SCANNER V1.3")
    print("==========================================")

    codes = get_nifty200_codes()

    print("Stocks found:", len(codes))

    results = []

    for number, code in enumerate(codes, start=1):
        print(f"[{number}/{len(codes)}] {code}")

        try:
            result = scan_symbol(code)

            if result:
                results.append(result)
                print(
                    "  FOUND:",
                    result["Setup"],
                    "| Score:", result["Score"],
                )

        except Exception as e:
            print("  ERROR:", e)

    # Highest score first.
    results.sort(
        key=lambda x: float(x.get("Score", 0)),
        reverse=True,
    )

    write_final_list(results)

    print("==========================================")
    print("SCAN COMPLETE")
    print("Qualified stocks:", len(results))
    print("Score filter: >=", MIN_SCORE)
    print("==========================================")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("FATAL ERROR:", exc)
        sys.exit(1)
