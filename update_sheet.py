#!/usr/bin/env python3
"""
NIFTY 200 Positive Divergence + Cup Pattern Scanner V2.0

FINAL LIST EXACT COLUMNS:
A  Stock Name
B  NSE Code
C  Setup
D  Daily Pattern
E  Daily Status
F  Weekly Pattern
G  Weekly Status
H  Monthly Pattern
I  Monthly Status
J  CMP
K  Chart Link

SETUPS ARE COMPLETELY SEPARATE:
1. RSI Positive Divergence
2. Classic Positive Divergence
3. Cup Pattern

Cup Pattern is scanned independently on:
- Daily
- Weekly
- Monthly

Cup status:
- BEFORE BREAKOUT
- BREAKOUT
- AFTER BREAKOUT

If a stock has divergence AND a cup pattern, separate rows are written.
No old columns such as Score, RSI Improvement %, EMA20, EMA50, Support,
Entry, Target, Risk, Cup Pattern Present, etc. are written to Final List.
"""

import os
import sys
import json
import re

import numpy as np
import pandas as pd
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials


# ============================================================
# CONFIG
# ============================================================

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID",
    "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E",
)

FINAL_LIST_SHEET = os.environ.get("FINAL_LIST_SHEET", "Final List")
INPUT_SHEET = os.environ.get("INPUT_SHEET", "NIFTY200")

MIN_HISTORY_ROWS = 100

# -------------------------
# Cup configuration
# -------------------------

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

CUP_MIN_DEPTH = 0.12
CUP_MAX_DEPTH = 0.45

RIM_TOLERANCE = 0.08

HANDLE_MAX_RETRACE = 0.18
HANDLE_MAX_BARS_RATIO = 0.35

BREAKOUT_BUFFER = 0.005
RECENT_BREAKOUT_BARS = 12


# ============================================================
# FINAL LIST SCHEMA - NEVER CHANGE ORDER ACCIDENTALLY
# ============================================================

FINAL_COLUMNS = [
    "Stock Name",
    "NSE Code",
    "Setup",
    "Daily Pattern",
    "Daily Status",
    "Weekly Pattern",
    "Weekly Status",
    "Monthly Pattern",
    "Monthly Status",
    "CMP",
    "Chart Link",
]


# ============================================================
# GOOGLE SHEETS
# ============================================================

def normalize_header(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or "").strip().lower(),
    )


def get_credentials():
    raw = os.environ.get("GCP_CREDENTIALS", "").strip()

    if not raw:
        raise RuntimeError("GCP_CREDENTIALS is missing.")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    # GitHub secret contains complete JSON.
    if raw.startswith("{"):
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "GCP_CREDENTIALS contains invalid JSON."
            ) from exc

        return Credentials.from_service_account_info(
            info,
            scopes=scopes,
        )

    # Local file path.
    if os.path.exists(raw):
        return Credentials.from_service_account_file(
            raw,
            scopes=scopes,
        )

    raise RuntimeError(
        "GCP_CREDENTIALS is not valid JSON or a valid credentials file."
    )


def get_google_sheet():
    creds = get_credentials()
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)


def write_final_list(rows):
    """Write exact Final List columns and apply a clean light design."""

    sh = get_google_sheet()

    try:
        ws = sh.worksheet(FINAL_LIST_SHEET)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(
            title=FINAL_LIST_SHEET,
            rows=1000,
            cols=len(FINAL_COLUMNS),
        )

    output = [FINAL_COLUMNS]

    for row in rows:
        output.append([
            row.get("Stock Name", ""),
            row.get("NSE Code", ""),
            row.get("Setup", ""),
            row.get("Daily Pattern", ""),
            row.get("Daily Status", ""),
            row.get("Weekly Pattern", ""),
            row.get("Weekly Status", ""),
            row.get("Monthly Pattern", ""),
            row.get("Monthly Status", ""),
            row.get("CMP", ""),
            row.get("Chart Link", ""),
        ])

    # Clear old data and old dark/black formatting.
    ws.clear()
    try:
        ws.clear(format_only=True)
    except Exception:
        pass

    try:
        ws.resize(rows=max(len(output) + 10, 100), cols=11)
    except Exception:
        pass

    ws.update("A1", output, value_input_option="USER_ENTERED")

    last_row = max(len(output), 2)

    try:
        ws.freeze(rows=1, cols=2)
    except Exception:
        try:
            ws.freeze(rows=1)
        except Exception:
            pass

    # Light blue header - no black strip.
    try:
        ws.format("A1:K1", {
            "backgroundColor": {"red": 0.82, "green": 0.91, "blue": 0.98},
            "textFormat": {
                "bold": True,
                "fontSize": 10,
                "foregroundColor": {"red": 0.08, "green": 0.16, "blue": 0.28},
            },
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
            "wrapStrategy": "WRAP",
            "borders": {
                "bottom": {
                    "style": "SOLID_MEDIUM",
                    "color": {"red": 0.35, "green": 0.55, "blue": 0.75},
                }
            },
        })

        ws.format(f"A2:K{last_row}", {
            "verticalAlignment": "MIDDLE",
            "wrapStrategy": "WRAP",
            "textFormat": {
                "fontSize": 10,
                "foregroundColor": {"red": 0.10, "green": 0.14, "blue": 0.20},
            },
        })

        ws.format(f"A2:B{last_row}", {"textFormat": {"bold": True}})
        ws.format(f"C2:I{last_row}", {"horizontalAlignment": "CENTER"})
        ws.format(f"J2:J{last_row}", {
            "horizontalAlignment": "RIGHT",
            "numberFormat": {"type": "NUMBER", "pattern": "0.00"},
        })

        # Setup column: very light blue.
        ws.format(f"C2:C{last_row}", {
            "backgroundColor": {"red": 0.91, "green": 0.97, "blue": 1.00},
            "textFormat": {"bold": True},
            "horizontalAlignment": "CENTER",
        })

        # Status columns: soft cream/yellow.
        for col in ("E", "G", "I"):
            ws.format(f"{col}2:{col}{last_row}", {
                "backgroundColor": {"red": 1.00, "green": 0.97, "blue": 0.86},
                "textFormat": {"bold": True},
                "horizontalAlignment": "CENTER",
            })

        # Chart links.
        ws.format(f"K2:K{last_row}", {
            "textFormat": {
                "foregroundColor": {"red": 0.05, "green": 0.35, "blue": 0.80},
                "underline": True,
            },
            "horizontalAlignment": "CENTER",
        })

    except Exception as exc:
        print("Formatting warning:", exc)

    # Alternating rows + sensible column widths.
    try:
        requests = []

        for row_no in range(2, last_row + 1):
            if row_no % 2 == 0:
                requests.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": ws.id,
                            "startRowIndex": row_no - 1,
                            "endRowIndex": row_no,
                            "startColumnIndex": 0,
                            "endColumnIndex": 11,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {
                                    "red": 0.965,
                                    "green": 0.98,
                                    "blue": 0.995,
                                }
                            }
                        },
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                })

        widths = [145, 115, 190, 145, 135, 145, 135, 145, 135, 90, 135]
        for idx, width in enumerate(widths):
            requests.append({
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": ws.id,
                        "dimension": "COLUMNS",
                        "startIndex": idx,
                        "endIndex": idx + 1,
                    },
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize",
                }
            })

        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": ws.id,
                    "dimension": "ROWS",
                    "startIndex": 0,
                    "endIndex": 1,
                },
                "properties": {"pixelSize": 42},
                "fields": "pixelSize",
            }
        })

        if requests:
            sh.batch_update({"requests": requests})

    except Exception as exc:
        print("Advanced formatting warning:", exc)

    print("")
    print("==========================================")
    print("FINAL LIST UPDATED + CLEAN DESIGN")
    print("==========================================")
    print("Rows:", len(rows))
    print("Columns:", len(FINAL_COLUMNS))
    print("Black header strip: REMOVED")
    print("Header: LIGHT BLUE")
    print("Frozen: Header + first 2 columns")
    print("==========================================")


# ============================================================
# INPUT STOCK LIST
# ============================================================

def get_nifty200_stocks():
    """
    Reads NIFTY200 sheet and returns:
        [
            {
                "Stock Name": "...",
                "NSE Code": "..."
            }
        ]

    Tries several common header names so the scanner works with
    existing NIFTY200 sheet layouts.
    """

    sh = get_google_sheet()

    try:
        ws = sh.worksheet(INPUT_SHEET)
    except gspread.WorksheetNotFound:
        raise RuntimeError(
            f'{INPUT_SHEET} worksheet not found.'
        )

    values = ws.get_all_values()

    if not values:
        raise RuntimeError(
            f'{INPUT_SHEET} sheet is empty.'
        )

    headers = values[0]
    normalized = [
        normalize_header(x)
        for x in headers
    ]

    # -------------------------
    # NSE code candidates
    # -------------------------

    code_candidates = [
        "nse code",
        "nse_code",
        "nsecode",
        "symbol",
        "stock code",
        "stock_code",
        "stock/nse code",
        "code",
    ]

    # -------------------------
    # Stock name candidates
    # -------------------------

    name_candidates = [
        "stock name",
        "stock_name",
        "company name",
        "company_name",
        "company",
        "name",
        "stock",
    ]

    code_idx = None
    name_idx = None

    for candidate in code_candidates:
        if candidate in normalized:
            code_idx = normalized.index(candidate)
            break

    for candidate in name_candidates:
        if candidate in normalized:
            candidate_idx = normalized.index(candidate)

            # Avoid accidentally using the code column as name.
            if candidate_idx != code_idx:
                name_idx = candidate_idx
                break

    # If no code header exists, use first column.
    if code_idx is None:
        code_idx = 0

    stocks = []
    seen_codes = set()

    for row in values[1:]:
        if code_idx >= len(row):
            continue

        code = str(row[code_idx]).strip().upper()

        if not code:
            continue

        # Remove accidental .NS from NSE code.
        if code.endswith(".NS"):
            code = code[:-3]

        if not re.match(r"^[A-Z0-9&._-]+$", code):
            continue

        if code in seen_codes:
            continue

        # Name priority:
        # 1. Name column
        # 2. Code itself
        if name_idx is not None and name_idx < len(row):
            name = str(row[name_idx]).strip()
        else:
            name = code

        if not name:
            name = code

        stocks.append({
            "Stock Name": name,
            "NSE Code": code,
        })

        seen_codes.add(code)

    if not stocks:
        raise RuntimeError(
            "No valid NSE stocks found in NIFTY200 sheet."
        )

    return stocks


# ============================================================
# DATA
# ============================================================

def download_ohlcv(symbol, period="5y", interval="1d"):
    try:
        ticker = yf.Ticker(symbol)

        df = ticker.history(
            period=period,
            interval=interval,
            auto_adjust=False,
            actions=False,
        )

        if df is None or df.empty:
            return None

        df = df.reset_index()

        # Standardize column names.
        new_columns = []

        for column in df.columns:
            name = str(column).strip().lower()

            name = name.replace(" ", "_")
            name = name.replace("-", "_")

            new_columns.append(name)

        df.columns = new_columns

        # yfinance can sometimes return datetime instead of date.
        if "date" not in df.columns and "datetime" not in df.columns:
            if isinstance(df.index, pd.DatetimeIndex):
                df = df.reset_index()
            else:
                return None

        required = {
            "close",
            "high",
            "low",
            "volume",
        }

        if not required.issubset(set(df.columns)):
            return None

        df["close"] = pd.to_numeric(
            df["close"],
            errors="coerce",
        )

        df["high"] = pd.to_numeric(
            df["high"],
            errors="coerce",
        )

        df["low"] = pd.to_numeric(
            df["low"],
            errors="coerce",
        )

        df["volume"] = pd.to_numeric(
            df["volume"],
            errors="coerce",
        )

        df = df.dropna(
            subset=[
                "close",
                "high",
                "low",
            ]
        )

        df = df.sort_values(
            "date" if "date" in df.columns else "datetime"
        )

        df = df.reset_index(drop=True)

        return df

    except Exception as exc:
        print(
            f"  Download error for {symbol}: {exc}"
        )
        return None


def resample_ohlcv(df, timeframe):
    if df is None or df.empty:
        return None

    x = df.copy()

    if "date" in x.columns:
        date_col = "date"
    elif "datetime" in x.columns:
        date_col = "datetime"
    else:
        return None

    x[date_col] = pd.to_datetime(
        x[date_col],
        errors="coerce",
    )

    x = x.dropna(
        subset=[date_col]
    )

    x = x.set_index(date_col)

    rules = {
        "Daily": "1D",
        "Weekly": "W-FRI",
        "Monthly": "ME",
    }

    rule = rules[timeframe]

    try:
        out = x.resample(rule).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna(
            subset=[
                "high",
                "low",
                "close",
            ]
        )

    except Exception:
        # Compatibility for pandas versions where ME is unsupported.
        if timeframe == "Monthly":
            out = x.resample("M").agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }).dropna(
                subset=[
                    "high",
                    "low",
                    "close",
                ]
            )
        else:
            raise

    return out.reset_index()


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
        adjust=False,
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False,
    ).mean()

    rs = avg_gain / avg_loss.replace(
        0,
        np.nan,
    )

    result = 100 - (
        100 / (1 + rs)
    )

    return result


def local_lows(series, left=3, right=3):
    values = series.to_numpy(
        dtype=float
    )

    lows = []

    if len(values) < left + right + 1:
        return lows

    for i in range(
        left,
        len(values) - right,
    ):
        window = values[
            i - left:i + right + 1
        ]

        if values[i] == np.min(window):
            lows.append(i)

    return lows


# ============================================================
# POSITIVE DIVERGENCE
# ============================================================

def find_divergence_setups(df):
    """
    Returns separate setups.

    Possible output:
        ["RSI Positive Divergence"]
        ["Classic Positive Divergence"]
        ["RSI Positive Divergence",
         "Classic Positive Divergence"]
        []

    RSI Positive Divergence:
        Price makes lower low by >= 0.5%
        RSI makes higher low by >= 2 points.

    Classic Positive Divergence:
        Price makes lower low by >= 0.5%
        RSI makes a higher low.

    Both are deliberately allowed to produce separate rows.
    """

    found = []

    if df is None:
        return found

    if len(df) < MIN_HISTORY_ROWS:
        return found

    close = df["close"].astype(float)

    rsi_values = calculate_rsi(
        close,
        period=14,
    )

    lows = local_lows(
        close,
        left=3,
        right=3,
    )

    if len(lows) < 2:
        return found

    # Look at the latest two confirmed swing lows.
    i1, i2 = lows[-2], lows[-1]

    price1 = float(close.iloc[i1])
    price2 = float(close.iloc[i2])

    rsi1 = rsi_values.iloc[i1]
    rsi2 = rsi_values.iloc[i2]

    if pd.isna(rsi1) or pd.isna(rsi2):
        return found

    rsi1 = float(rsi1)
    rsi2 = float(rsi2)

    lower_price = (
        price2 <= price1 * 0.995
    )

    higher_rsi = (
        rsi2 > rsi1
    )

    strong_rsi = (
        rsi2 >= rsi1 + 2
    )

    # Strong RSI positive divergence.
    if lower_price and strong_rsi:
        found.append(
            "RSI Positive Divergence"
        )

    # Classic positive divergence.
    if lower_price and higher_rsi:
        found.append(
            "Classic Positive Divergence"
        )

    return found


# ============================================================
# CUP HELPERS
# ============================================================

def smooth(values, window):
    values = np.asarray(
        values,
        dtype=float,
    )

    if len(values) < 3:
        return values

    window = max(
        3,
        int(window),
    )

    return (
        pd.Series(values)
        .rolling(
            window=window,
            center=True,
            min_periods=1,
        )
        .mean()
        .to_numpy()
    )


# ============================================================
# CUP / CUP WITH HANDLE
# ============================================================

def detect_cup(df, timeframe):
    """
    Returns:
        (pattern, status)

    pattern:
        Cup
        Cup with Handle
        None

    status:
        BEFORE BREAKOUT
        BREAKOUT
        AFTER BREAKOUT
    """

    if df is None:
        return None, ""

    min_bars = CUP_MIN_BARS[timeframe]
    max_bars = CUP_MAX_BARS[timeframe]

    if len(df) < min_bars:
        return None, ""

    # Keep the recent relevant window.
    data = df.tail(
        min(
            len(df),
            max_bars + 30,
        )
    ).copy()

    if len(data) < min_bars:
        return None, ""

    close = data["close"].astype(
        float
    ).to_numpy()

    high = data["high"].astype(
        float
    ).to_numpy()

    low = data["low"].astype(
        float
    ).to_numpy()

    n = len(close)

    # Smooth only for rim detection.
    sm = smooth(
        close,
        max(
            3,
            n // 30,
        ),
    )

    left_zone_end = int(
        n * 0.45
    )

    right_zone_start = int(
        n * 0.55
    )

    if (
        left_zone_end < 5
        or right_zone_start >= n - 5
    ):
        return None, ""

    left_candidates = (
        np.argsort(
            sm[:left_zone_end]
        )[-10:]
    )

    right_candidates = (
        np.argsort(
            sm[right_zone_start:]
        )[-10:]
        + right_zone_start
    )

    best = None

    for li in left_candidates:
        left_rim = float(
            sm[li]
        )

        if left_rim <= 0:
            continue

        bottom_slice = low[
            li + 3:right_zone_start
        ]

        if len(bottom_slice) < 5:
            continue

        relative_bottom = int(
            np.argmin(bottom_slice)
        )

        bi = (
            li
            + 3
            + relative_bottom
        )

        bottom_price = float(
            low[bi]
        )

        depth = (
            left_rim - bottom_price
        ) / left_rim

        if (
            depth < CUP_MIN_DEPTH
            or depth > CUP_MAX_DEPTH
        ):
            continue

        for ri in right_candidates:
            if ri <= bi:
                continue

            right_rim = float(
                sm[ri]
            )

            rim_similarity = (
                abs(
                    right_rim
                    - left_rim
                )
                / left_rim
            )

            if (
                rim_similarity
                > RIM_TOLERANCE
            ):
                continue

            left_span = bi - li
            right_span = ri - bi

            if (
                left_span < 5
                or right_span < 5
            ):
                continue

            balance = (
                min(
                    left_span,
                    right_span,
                )
                / max(
                    left_span,
                    right_span,
                )
            )

            if balance < 0.25:
                continue

            candidate = {
                "li": li,
                "bi": bi,
                "ri": ri,
                "left_rim": left_rim,
                "right_rim": right_rim,
                "bottom": bottom_price,
                "depth": depth,
                "balance": balance,
            }

            if (
                best is None
                or candidate["depth"]
                > best["depth"]
            ):
                best = candidate

    if best is None:
        return None, ""

    li = best["li"]
    bi = best["bi"]
    ri = best["ri"]

    rim = max(
        best["left_rim"],
        best["right_rim"],
    )

    current_close = float(
        close[-1]
    )

    breakout_level = (
        rim * (
            1
            + BREAKOUT_BUFFER
        )
    )

    # --------------------------------------------------------
    # Find first confirmed close above breakout level after
    # the right side of the cup.
    # --------------------------------------------------------

    breakout_index = None

    for j in range(
        ri + 1,
        len(close),
    ):
        if (
            close[j]
            > breakout_level
        ):
            breakout_index = j
            break

    # --------------------------------------------------------
    # Handle detection
    # --------------------------------------------------------

    pattern = "Cup"

    handle = close[
        ri:
    ]

    if len(handle) >= 3:
        handle_high = float(
            np.max(handle)
        )

        handle_low = float(
            np.min(handle)
        )

        if handle_high > 0:
            handle_retrace = (
                handle_high
                - handle_low
            ) / handle_high
        else:
            handle_retrace = 1.0

        max_handle_bars = max(
            3,
            int(
                (ri - li)
                * HANDLE_MAX_BARS_RATIO
            ),
        )

        handle_bars = len(handle)

        # Cup midpoint.
        cup_mid = (
            best["bottom"]
            + (
                rim
                - best["bottom"]
            ) * 0.50
        )

        if (
            handle_bars
            <= max_handle_bars
            and handle_retrace
            <= HANDLE_MAX_RETRACE
            and handle_low
            >= cup_mid
        ):
            pattern = "Cup with Handle"

    # --------------------------------------------------------
    # Breakout status
    # --------------------------------------------------------

    if breakout_index is None:
        status = "BEFORE BREAKOUT"

    else:
        bars_since = (
            len(close)
            - 1
            - breakout_index
        )

        if bars_since <= 2:
            status = "BREAKOUT"
        else:
            status = "AFTER BREAKOUT"

    return pattern, status


# ============================================================
# CHART LINK
# ============================================================

def tradingview_link(nse_code):
    code = str(
        nse_code
    ).strip().upper()

    return (
        "https://in.tradingview.com/chart/"
        "?symbol=NSE%3A"
        + code
    )


# ============================================================
# BUILD OUTPUT ROW
# ============================================================

def make_row(
    stock_name,
    nse_code,
    setup,
    cmp_price,
    daily_pattern="",
    daily_status="",
    weekly_pattern="",
    weekly_status="",
    monthly_pattern="",
    monthly_status="",
):
    return {
        "Stock Name": stock_name,
        "NSE Code": nse_code,
        "Setup": setup,

        "Daily Pattern": daily_pattern,
        "Daily Status": daily_status,

        "Weekly Pattern": weekly_pattern,
        "Weekly Status": weekly_status,

        "Monthly Pattern": monthly_pattern,
        "Monthly Status": monthly_status,

        "CMP": round(
            float(cmp_price),
            2,
        ),

        "Chart Link": tradingview_link(
            nse_code
        ),
    }


# ============================================================
# SCAN ONE STOCK
# ============================================================

def scan_stock(stock):
    stock_name = stock["Stock Name"]
    nse_code = stock["NSE Code"]

    symbol = (
        str(nse_code)
        .strip()
        .upper()
    )

    if symbol.endswith(".NS"):
        symbol = symbol[:-3]

    yahoo_symbol = (
        symbol
        + ".NS"
    )

    daily = download_ohlcv(
        yahoo_symbol,
        period="5y",
        interval="1d",
    )

    if (
        daily is None
        or len(daily) < MIN_HISTORY_ROWS
    ):
        return []

    cmp_price = float(
        daily["close"].iloc[-1]
    )

    results = []

    # ========================================================
    # SETUP A - DIVERGENCE
    # ========================================================

    divergence_setups = (
        find_divergence_setups(
            daily
        )
    )

    for setup in divergence_setups:
        # Divergence is a separate setup row.
        # Cup fields remain blank.
        results.append(
            make_row(
                stock_name=stock_name,
                nse_code=nse_code,
                setup=setup,
                cmp_price=cmp_price,
            )
        )

    # ========================================================
    # SETUP B - CUP PATTERN
    # ========================================================

    cup_results = {}

    for timeframe in (
        "Daily",
        "Weekly",
        "Monthly",
    ):
        tf_df = resample_ohlcv(
            daily,
            timeframe,
        )

        pattern, status = detect_cup(
            tf_df,
            timeframe,
        )

        cup_results[timeframe] = (
            pattern,
            status,
        )

    daily_pattern, daily_status = (
        cup_results["Daily"]
    )

    weekly_pattern, weekly_status = (
        cup_results["Weekly"]
    )

    monthly_pattern, monthly_status = (
        cup_results["Monthly"]
    )

    cup_found = any(
        pattern is not None
        for pattern, status
        in cup_results.values()
    )

    if cup_found:
        # Exactly ONE Cup Pattern row.
        #
        # It can contain:
        # Daily Cup
        # Weekly Cup
        # Monthly Cup
        #
        # without mixing with divergence.
        results.append(
            make_row(
                stock_name=stock_name,
                nse_code=nse_code,
                setup="Cup Pattern",
                cmp_price=cmp_price,

                daily_pattern=(
                    daily_pattern
                    or ""
                ),
                daily_status=(
                    daily_status
                    or ""
                ),

                weekly_pattern=(
                    weekly_pattern
                    or ""
                ),
                weekly_status=(
                    weekly_status
                    or ""
                ),

                monthly_pattern=(
                    monthly_pattern
                    or ""
                ),
                monthly_status=(
                    monthly_status
                    or ""
                ),
            )
        )

    return results


# ============================================================
# MAIN
# ============================================================

def main():
    print("")
    print("==========================================")
    print("NIFTY 200 DIVERGENCE + CUP SCANNER V2.0")
    print("==========================================")
    print("")
    print("Final List schema:")
    print("A  Stock Name")
    print("B  NSE Code")
    print("C  Setup")
    print("D  Daily Pattern")
    print("E  Daily Status")
    print("F  Weekly Pattern")
    print("G  Weekly Status")
    print("H  Monthly Pattern")
    print("I  Monthly Status")
    print("J  CMP")
    print("K  Chart Link")
    print("")

    stocks = get_nifty200_stocks()

    print(
        "Stocks found:",
        len(stocks),
    )

    results = []

    for number, stock in enumerate(
        stocks,
        start=1,
    ):
        code = stock["NSE Code"]
        name = stock["Stock Name"]

        print(
            f"[{number}/{len(stocks)}] "
            f"{code} | {name}"
        )

        try:
            stock_results = scan_stock(
                stock
            )

            if stock_results:
                results.extend(
                    stock_results
                )

                for row in stock_results:
                    print(
                        "  FOUND:",
                        row["Setup"],
                    )

        except Exception as exc:
            print(
                "  ERROR:",
                code,
                "|",
                exc,
            )

    # --------------------------------------------------------
    # Sort:
    # Stock Name -> Setup
    # --------------------------------------------------------

    results.sort(
        key=lambda row: (
            str(
                row.get(
                    "Stock Name",
                    "",
                )
            ).upper(),
            str(
                row.get(
                    "Setup",
                    "",
                )
            ),
        )
    )

    # --------------------------------------------------------
    # Write sheet
    # --------------------------------------------------------

    write_final_list(
        results
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    divergence_rows = sum(
        1
        for row in results
        if row["Setup"]
        in {
            "RSI Positive Divergence",
            "Classic Positive Divergence",
        }
    )

    cup_rows = sum(
        1
        for row in results
        if row["Setup"]
        == "Cup Pattern"
    )

    print("")
    print("==========================================")
    print("SCAN COMPLETE")
    print("==========================================")
    print(
        "Qualified output rows:",
        len(results),
    )
    print(
        "Divergence rows:",
        divergence_rows,
    )
    print(
        "Cup Pattern rows:",
        cup_rows,
    )
    print("")
    print(
        "IMPORTANT: Divergence and Cup are "
        "separate Setup rows."
    )
    print("==========================================")


if __name__ == "__main__":
    try:
        main()

    except Exception as exc:
        print("")
        print("==========================================")
        print("FATAL ERROR")
        print("==========================================")
        print(exc)
        print("==========================================")
        sys.exit(1)
