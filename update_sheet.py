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
import html
from pathlib import Path

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
# Pattern chart publishing
# -------------------------
CHART_OUTPUT_DIR = Path(os.environ.get("CHART_OUTPUT_DIR", "docs/charts"))
CHART_BASE_URL = "https://mkshsmwl10-web.github.io/-NSE-Auto-Sheet/docs/charts"


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

    # --------------------------------------------------------
    # HARD RESET FINAL LIST BEFORE WRITING
    # --------------------------------------------------------
    # This removes old merged cells, stale headers, old values and
    # formatting so the 11-column schema can never appear shifted.
    try:
        meta = sh.fetch_sheet_metadata()
        target = None
        for sheet_meta in meta.get("sheets", []):
            props = sheet_meta.get("properties", {})
            if props.get("sheetId") == ws.id:
                target = props
                break

        if target:
            grid = target.get("gridProperties", {})
            row_count = max(int(grid.get("rowCount", 1000)), 100)
            col_count = max(int(grid.get("columnCount", 26)), 11)

            sh.batch_update({
                "requests": [
                    {
                        "unmergeCells": {
                            "range": {
                                "sheetId": ws.id,
                                "startRowIndex": 0,
                                "endRowIndex": row_count,
                                "startColumnIndex": 0,
                                "endColumnIndex": col_count,
                            }
                        }
                    }
                ]
            })
    except Exception as exc:
        print("Unmerge warning:", exc)

    # Clear all existing cell values.
    ws.clear()

    # Reset formatting across the used sheet area.
    try:
        sh.batch_update({
            "requests": [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": ws.id,
                            "startRowIndex": 0,
                            "startColumnIndex": 0,
                        },
                        "cell": {
                            "userEnteredFormat": {}
                        },
                        "fields": "userEnteredFormat",
                    }
                }
            ]
        })
    except Exception as exc:
        print("Format reset warning:", exc)

    # Force exactly 11 columns in Final List.
    try:
        ws.resize(
            rows=max(len(output) + 10, 100),
            cols=len(FINAL_COLUMNS),
        )
    except Exception as exc:
        print("Resize warning:", exc)

    # First write ONLY the exact header row.
    ws.update(
        "A1:K1",
        [FINAL_COLUMNS],
        value_input_option="RAW",
    )

    # Then write data starting from row 2.
    if len(output) > 1:
        ws.update(
            f"A2:K{len(output)}",
            output[1:],
            value_input_option="USER_ENTERED",
        )

    last_row = max(len(output), 2)

    # Verify that Google Sheet actually contains the exact 11 headers.
    try:
        actual_headers = ws.get("A1:K1")
        actual_headers = actual_headers[0] if actual_headers else []

        if actual_headers != FINAL_COLUMNS:
            print("Header mismatch detected. Repairing header row...")
            ws.update(
                "A1:K1",
                [FINAL_COLUMNS],
                value_input_option="RAW",
            )
    except Exception as exc:
        print("Header verification warning:", exc)

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

def find_divergence_details(df):
    """Return divergence setup names plus the exact two swing-low points."""
    found = []
    details = {}

    if df is None or len(df) < MIN_HISTORY_ROWS:
        return found, details

    close = df["close"].astype(float)
    rsi_values = calculate_rsi(close, period=14)
    lows = local_lows(close, left=3, right=3)

    if len(lows) < 2:
        return found, details

    i1, i2 = lows[-2], lows[-1]
    price1 = float(close.iloc[i1])
    price2 = float(close.iloc[i2])
    rsi1 = rsi_values.iloc[i1]
    rsi2 = rsi_values.iloc[i2]

    if pd.isna(rsi1) or pd.isna(rsi2):
        return found, details

    rsi1 = float(rsi1)
    rsi2 = float(rsi2)

    lower_price = price2 <= price1 * 0.995
    higher_rsi = rsi2 > rsi1
    strong_rsi = rsi2 >= rsi1 + 2

    details = {
        "i1": int(i1),
        "i2": int(i2),
        "price1": price1,
        "price2": price2,
        "rsi1": rsi1,
        "rsi2": rsi2,
    }

    if lower_price and strong_rsi:
        found.append("RSI Positive Divergence")

    if lower_price and higher_rsi:
        found.append("Classic Positive Divergence")

    if not found:
        details = {}

    return found, details


def find_divergence_setups(df):
    found, _ = find_divergence_details(df)
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

def detect_cup(df, timeframe, return_details=False):
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
        return (None, "", {}) if return_details else (None, "")

    min_bars = CUP_MIN_BARS[timeframe]
    max_bars = CUP_MAX_BARS[timeframe]

    if len(df) < min_bars:
        return (None, "", {}) if return_details else (None, "")

    # Keep the recent relevant window.
    data = df.tail(
        min(
            len(df),
            max_bars + 30,
        )
    ).copy()

    if len(data) < min_bars:
        return (None, "", {}) if return_details else (None, "")

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
        return (None, "", {}) if return_details else (None, "")

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
        return (None, "", {}) if return_details else (None, "")

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

    details = {
        "data": data.copy(),
        "li": int(li),
        "bi": int(bi),
        "ri": int(ri),
        "left_rim": float(best["left_rim"]),
        "right_rim": float(best["right_rim"]),
        "bottom": float(best["bottom"]),
        "rim": float(rim),
        "breakout_level": float(breakout_level),
        "breakout_index": (
            int(breakout_index)
            if breakout_index is not None
            else None
        ),
        "pattern": pattern,
        "status": status,
        "timeframe": timeframe,
    }

    if return_details:
        return pattern, status, details

    return pattern, status


# ============================================================
# CHART LINK
# ============================================================

def _date_col(df):
    if "date" in df.columns:
        return "date"
    return "datetime"


def _safe_slug(value):
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value).strip())
    return value.strip("-") or "chart"


def pattern_chart_url(filename):
    return f"{CHART_BASE_URL}/{filename}"


def _svg_price_chart(df, marks=None, title="", max_bars=220):
    """Create a dependency-free SVG close-price chart with scanner markers."""
    marks = marks or {}
    data = df.copy().tail(max_bars).reset_index(drop=False)
    if data.empty:
        return "<p>No chart data.</p>"

    # If original indices were supplied, convert them to the displayed tail.
    original_start = max(0, len(df) - len(data))
    close = data["close"].astype(float).to_numpy()
    high = data["high"].astype(float).to_numpy()
    low = data["low"].astype(float).to_numpy()

    width, height = 1120, 520
    ml, mr, mt, mb = 72, 28, 50, 58
    pw, ph = width - ml - mr, height - mt - mb

    y_min = float(np.nanmin(low))
    y_max = float(np.nanmax(high))
    pad = max((y_max - y_min) * 0.08, max(abs(y_max), 1) * 0.005)
    y_min -= pad
    y_max += pad

    def xpix(i):
        return ml + (i / max(len(data) - 1, 1)) * pw

    def ypix(v):
        return mt + (y_max - float(v)) / max(y_max - y_min, 1e-9) * ph

    pts = " ".join(f"{xpix(i):.1f},{ypix(v):.1f}" for i, v in enumerate(close))
    out = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{ml}" y="28" font-size="20" font-weight="700" fill="#172033">{html.escape(title)}</text>',
    ]

    # Horizontal grid + labels.
    for k in range(6):
        v = y_min + (y_max - y_min) * k / 5
        y = ypix(v)
        out.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{width-mr}" y2="{y:.1f}" stroke="#e8edf3" stroke-width="1"/>')
        out.append(f'<text x="{ml-8}" y="{y+4:.1f}" text-anchor="end" font-size="12" fill="#667085">{v:.2f}</text>')

    out.append(f'<polyline points="{pts}" fill="none" stroke="#1f5fbf" stroke-width="2.2"/>')

    # Breakout level.
    if marks.get("breakout_level") is not None:
        by = ypix(marks["breakout_level"])
        out.append(f'<line x1="{ml}" y1="{by:.1f}" x2="{width-mr}" y2="{by:.1f}" stroke="#d97706" stroke-width="2" stroke-dasharray="8 6"/>')
        out.append(f'<text x="{width-mr-4}" y="{by-7:.1f}" text-anchor="end" font-size="12" font-weight="700" fill="#b45309">Breakout {marks["breakout_level"]:.2f}</text>')

    # Scanner points.
    point_specs = [
        ("li", "Left Rim", "#7c3aed"),
        ("bi", "Cup Bottom", "#dc2626"),
        ("ri", "Right Rim", "#7c3aed"),
        ("breakout_index", "Breakout", "#059669"),
        ("i1", "Low 1", "#dc2626"),
        ("i2", "Low 2", "#dc2626"),
    ]
    mapped = {}
    for key, label, color in point_specs:
        idx = marks.get(key)
        if idx is None:
            continue
        di = int(idx) - original_start
        if di < 0 or di >= len(data):
            continue
        mapped[key] = di
        val = float(close[di])
        if key == "bi":
            val = float(low[di])
        out.append(f'<circle cx="{xpix(di):.1f}" cy="{ypix(val):.1f}" r="6" fill="{color}" stroke="#fff" stroke-width="2"/>')
        out.append(f'<text x="{xpix(di):.1f}" y="{ypix(val)-12:.1f}" text-anchor="middle" font-size="12" font-weight="700" fill="{color}">{label}</text>')

    # Price divergence line.
    if "i1" in mapped and "i2" in mapped:
        a, b = mapped["i1"], mapped["i2"]
        out.append(f'<line x1="{xpix(a):.1f}" y1="{ypix(close[a]):.1f}" x2="{xpix(b):.1f}" y2="{ypix(close[b]):.1f}" stroke="#dc2626" stroke-width="3"/>')

    # Cup guide lines.
    if all(k in mapped for k in ("li", "bi", "ri")):
        a, b, c = mapped["li"], mapped["bi"], mapped["ri"]
        guide = f"{xpix(a):.1f},{ypix(close[a]):.1f} {xpix(b):.1f},{ypix(low[b]):.1f} {xpix(c):.1f},{ypix(close[c]):.1f}"
        out.append(f'<polyline points="{guide}" fill="none" stroke="#7c3aed" stroke-width="3" stroke-dasharray="7 5"/>')

    # X-axis dates.
    dc = _date_col(data)
    dates = pd.to_datetime(data[dc], errors="coerce")
    for i in np.linspace(0, len(data)-1, min(6, len(data)), dtype=int):
        label = dates.iloc[i].strftime("%Y-%m-%d") if not pd.isna(dates.iloc[i]) else ""
        out.append(f'<text x="{xpix(i):.1f}" y="{height-20}" text-anchor="middle" font-size="11" fill="#667085">{label}</text>')

    out.append("</svg>")
    return "".join(out)


def _svg_rsi_chart(df, details, title="RSI (14)", max_bars=220):
    data = df.copy()
    data["rsi14"] = calculate_rsi(data["close"].astype(float), 14)
    original_start = max(0, len(data) - max_bars)
    data = data.tail(max_bars).reset_index(drop=True)

    width, height = 1120, 300
    ml, mr, mt, mb = 72, 28, 45, 45
    pw, ph = width - ml - mr, height - mt - mb

    def xpix(i):
        return ml + (i / max(len(data)-1, 1)) * pw
    def ypix(v):
        return mt + (100-float(v))/100 * ph

    vals = data["rsi14"].to_numpy(dtype=float)
    pts = " ".join(
        f"{xpix(i):.1f},{ypix(v):.1f}"
        for i, v in enumerate(vals) if np.isfinite(v)
    )

    out = [
        f'<svg viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fff"/>',
        f'<text x="{ml}" y="26" font-size="18" font-weight="700" fill="#172033">{html.escape(title)}</text>',
    ]
    for level in (30, 50, 70):
        y = ypix(level)
        out.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{width-mr}" y2="{y:.1f}" stroke="#e5e7eb" stroke-dasharray="6 5"/>')
        out.append(f'<text x="{ml-8}" y="{y+4:.1f}" text-anchor="end" font-size="12" fill="#667085">{level}</text>')
    out.append(f'<polyline points="{pts}" fill="none" stroke="#2563eb" stroke-width="2.2"/>')

    i1 = int(details["i1"]) - original_start
    i2 = int(details["i2"]) - original_start
    if 0 <= i1 < len(data) and 0 <= i2 < len(data):
        r1, r2 = float(details["rsi1"]), float(details["rsi2"])
        out.append(f'<line x1="{xpix(i1):.1f}" y1="{ypix(r1):.1f}" x2="{xpix(i2):.1f}" y2="{ypix(r2):.1f}" stroke="#059669" stroke-width="3"/>')
        for i, r, lab in ((i1, r1, "RSI Low 1"), (i2, r2, "RSI Low 2")):
            out.append(f'<circle cx="{xpix(i):.1f}" cy="{ypix(r):.1f}" r="6" fill="#059669" stroke="#fff" stroke-width="2"/>')
            out.append(f'<text x="{xpix(i):.1f}" y="{ypix(r)-12:.1f}" text-anchor="middle" font-size="12" font-weight="700" fill="#047857">{lab}: {r:.1f}</text>')
    out.append("</svg>")
    return "".join(out)


def _write_chart_page(filename, stock_name, nse_code, setup, sections):
    CHART_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cards = "\n".join(
        f'<section class="card">{section}</section>'
        for section in sections
    )
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(nse_code)} - {html.escape(setup)}</title>
<style>
body{{margin:0;background:#f5f7fb;color:#172033;font-family:Arial,Helvetica,sans-serif}}
.wrap{{max-width:1200px;margin:24px auto;padding:0 14px}}
.head{{background:#172033;color:white;padding:20px 24px;border-radius:14px}}
.head h1{{margin:0 0 6px;font-size:26px}}
.head p{{margin:4px 0;color:#dbe7ff}}
.card{{background:white;margin-top:18px;padding:14px;border-radius:14px;box-shadow:0 2px 12px rgba(16,24,40,.08);overflow:auto}}
svg{{display:block;width:100%;min-width:850px;height:auto}}
.note{{font-size:13px;color:#667085;margin-top:16px}}
</style>
</head>
<body><div class="wrap">
<div class="head">
<h1>{html.escape(stock_name)} ({html.escape(nse_code)})</h1>
<p>Scanner setup: {html.escape(setup)}</p>
</div>
{cards}
<p class="note">Markers are generated from the same Python scanner logic that qualified this row.</p>
</div></body></html>"""
    (CHART_OUTPUT_DIR / filename).write_text(page, encoding="utf-8")
    return pattern_chart_url(filename)


def generate_divergence_chart(stock_name, nse_code, setup, daily, details):
    filename = f"{_safe_slug(nse_code)}-{_safe_slug(setup).lower()}.html"
    price_marks = {
        "i1": details["i1"],
        "i2": details["i2"],
    }
    sections = [
        _svg_price_chart(
            daily,
            marks=price_marks,
            title=f"{nse_code} Daily Price - {setup}",
        ),
        _svg_rsi_chart(
            daily,
            details,
            title=f"{nse_code} RSI(14) - Positive Divergence",
        ),
    ]
    return _write_chart_page(
        filename, stock_name, nse_code, setup, sections
    )


def generate_cup_chart(stock_name, nse_code, cup_details):
    filename = f"{_safe_slug(nse_code)}-cup-pattern.html"
    sections = []

    for timeframe in ("Daily", "Weekly", "Monthly"):
        details = cup_details.get(timeframe) or {}
        if not details:
            continue
        title = (
            f"{nse_code} {timeframe} - "
            f"{details['pattern']} | {details['status']}"
        )
        marks = {
            "li": details["li"],
            "bi": details["bi"],
            "ri": details["ri"],
            "breakout_index": details["breakout_index"],
            "breakout_level": details["breakout_level"],
        }
        sections.append(
            _svg_price_chart(
                details["data"],
                marks=marks,
                title=title,
                max_bars=260,
            )
        )

    return _write_chart_page(
        filename, stock_name, nse_code, "Cup Pattern", sections
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
    chart_url="",
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

        "Chart Link": (
            f'=HYPERLINK("{chart_url}","Pattern Chart")'
            if chart_url
            else ""
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

    divergence_setups, divergence_details = (
        find_divergence_details(daily)
    )

    for setup in divergence_setups:
        chart_url = generate_divergence_chart(
            stock_name=stock_name,
            nse_code=nse_code,
            setup=setup,
            daily=daily,
            details=divergence_details,
        )

        results.append(
            make_row(
                stock_name=stock_name,
                nse_code=nse_code,
                setup=setup,
                cmp_price=cmp_price,
                chart_url=chart_url,
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

        pattern, status, details = detect_cup(
            tf_df,
            timeframe,
            return_details=True,
        )

        cup_results[timeframe] = (
            pattern,
            status,
            details,
        )

    daily_pattern, daily_status = (
        cup_results["Daily"][:2]
    )

    weekly_pattern, weekly_status = (
        cup_results["Weekly"][:2]
    )

    monthly_pattern, monthly_status = (
        cup_results["Monthly"][:2]
    )

    cup_found = any(
        pattern is not None
        for pattern, status, details
        in cup_results.values()
    )

    if cup_found:
        cup_details = {
            timeframe: values[2]
            for timeframe, values in cup_results.items()
            if values[0] is not None and values[2]
        }

        chart_url = generate_cup_chart(
            stock_name=stock_name,
            nse_code=nse_code,
            cup_details=cup_details,
        )

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
                chart_url=chart_url,

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


def _extract_hyperlink_url(formula):
    match = re.search(r'=HYPERLINK\("([^"]+)"', str(formula or ""))
    return match.group(1) if match else ""


def _write_combined_stock_chart(nse_code, stock_name, rows):
    """Create one stock page that shows all already-generated setup pages."""
    urls = []
    for row in rows:
        url = _extract_hyperlink_url(row.get("Chart Link", ""))
        if url and url not in urls:
            urls.append(url)

    if not urls:
        return ""

    # If there is only one setup page, use it directly.
    if len(urls) == 1:
        return urls[0]

    filename = f"{_safe_slug(nse_code)}-all-patterns.html"

    frames = []
    for row in rows:
        url = _extract_hyperlink_url(row.get("Chart Link", ""))
        if not url:
            continue

        setup = html.escape(str(row.get("Setup", "")))
        child_filename = url.rsplit("/", 1)[-1]

        frames.append(
            f"""
            <section class="setup">
              <h2>{setup}</h2>
              <iframe
                src="{html.escape(child_filename)}"
                loading="lazy"
                title="{setup}">
              </iframe>
            </section>
            """
        )

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(str(nse_code))} - All Patterns</title>
<style>
body{{margin:0;background:#f5f7fb;font-family:Arial,Helvetica,sans-serif;color:#172033}}
.wrap{{max-width:1250px;margin:22px auto;padding:0 14px}}
.head{{background:#172033;color:#fff;padding:18px 22px;border-radius:14px}}
.head h1{{margin:0}}
.setup{{background:#fff;margin-top:18px;padding:14px;border-radius:14px;box-shadow:0 2px 12px rgba(16,24,40,.08)}}
.setup h2{{margin:0 0 12px}}
iframe{{width:100%;height:900px;border:0;border-radius:10px;background:#fff}}
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <h1>{html.escape(str(stock_name))} ({html.escape(str(nse_code))})</h1>
    <p>All scanner-detected setups for this stock</p>
  </div>
  {''.join(frames)}
</div>
</body>
</html>"""

    CHART_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (CHART_OUTPUT_DIR / filename).write_text(page, encoding="utf-8")
    return pattern_chart_url(filename)


def merge_rows_one_per_stock(results):
    """
    Preserve ALL original scanner detections, but display one Final List row
    per NSE Code. No stock is discarded merely because it has multiple setups.
    """
    grouped = {}
    order = []

    for row in results:
        code = str(row.get("NSE Code", "")).strip().upper()
        if not code:
            continue
        if code not in grouped:
            grouped[code] = []
            order.append(code)
        grouped[code].append(row)

    merged = []

    for code in order:
        rows = grouped[code]
        base = dict(rows[0])

        setups = []
        for row in rows:
            setup = str(row.get("Setup", "")).strip()
            if setup and setup not in setups:
                setups.append(setup)

        base["Setup"] = " + ".join(setups)

        # Preserve Cup fields from whichever original row contains them.
        for col in (
            "Daily Pattern",
            "Daily Status",
            "Weekly Pattern",
            "Weekly Status",
            "Monthly Pattern",
            "Monthly Status",
        ):
            value = ""
            for row in rows:
                candidate = str(row.get(col, "") or "").strip()
                if candidate:
                    value = row.get(col, "")
                    break
            base[col] = value

        stock_name = str(base.get("Stock Name", code))
        combined_url = _write_combined_stock_chart(
            nse_code=code,
            stock_name=stock_name,
            rows=rows,
        )

        base["Chart Link"] = (
            f'=HYPERLINK("{combined_url}","Pattern Chart")'
            if combined_url
            else ""
        )

        merged.append(base)

    return merged

def main():
    CHART_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for old_chart in CHART_OUTPUT_DIR.glob("*.html"):
        try:
            old_chart.unlink()
        except OSError:
            pass

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
    # Final List display:
    # ONE stock = ONE row, while preserving every detection.
    # --------------------------------------------------------

    results = merge_rows_one_per_stock(results)

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
