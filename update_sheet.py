#!/usr/bin/env python3
"""
NIFTY 200 POSITIVE DIVERGENCE + CUP PATTERN SCANNER V1.4

SETUPS ARE COMPLETELY SEPARATE

SETUP A:
    RSI Positive Divergence
    Classic Positive Divergence

SETUP B:
    Cup Pattern
    Cup with Handle

Cup Pattern is independently checked on:
    Daily
    Weekly
    Monthly

Cup Status:
    BEFORE BREAKOUT
    BREAKOUT
    AFTER BREAKOUT

FINAL LIST:
    Stock Name
    NSE Code
    Setup
    Daily Pattern
    Daily Status
    Weekly Pattern
    Weekly Status
    Monthly Pattern
    Monthly Status
    CMP
    Chart Link

IMPORTANT:
    RSI + Cup is NEVER created as a combined setup.
    If a stock has both, it gets separate rows.
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

INPUT_SHEET = "NIFTY200"
FINAL_LIST_SHEET = os.environ.get(
    "FINAL_LIST_SHEET",
    "Final List",
)

MIN_HISTORY_ROWS = 100

# ------------------------------------------------------------
# DIVERGENCE
# ------------------------------------------------------------

RSI_PERIOD = 14

SWING_LEFT = 3
SWING_RIGHT = 3

MIN_PRICE_LOWER_LOW_PCT = 0.50
MIN_RSI_IMPROVEMENT = 2.0

MAX_DIVERGENCE_GAP = 60
MAX_SIGNAL_AGE = 15


# ------------------------------------------------------------
# CUP
# ------------------------------------------------------------

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
# FINAL OUTPUT COLUMNS
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
# HEADER NORMALIZER
# ============================================================

def normalize_header(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or "").strip().lower()
    )


# ============================================================
# GOOGLE CREDENTIALS
# ============================================================

def get_credentials():

    raw = os.environ.get(
        "GCP_CREDENTIALS",
        ""
    ).strip()

    if not raw:
        raise RuntimeError(
            "GCP_CREDENTIALS is missing."
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    # GitHub Secret contains JSON
    if raw.startswith("{"):

        return Credentials.from_service_account_info(
            json.loads(raw),
            scopes=scopes,
        )

    # Or a credentials file path
    if os.path.exists(raw):

        return Credentials.from_service_account_file(
            raw,
            scopes=scopes,
        )

    raise RuntimeError(
        "GCP_CREDENTIALS is not valid JSON "
        "or a valid credentials file."
    )


# ============================================================
# YAHOO SYMBOL
# ============================================================

def yahoo_symbol(nse_code):

    code = str(
        nse_code
    ).strip().upper()

    if not code:
        return None

    if code.endswith(".NS"):
        return code

    return code + ".NS"


# ============================================================
# TRADINGVIEW CHART LINK
# ============================================================

def tradingview_link(nse_code):

    code = str(
        nse_code
    ).strip().upper()

    code = code.replace(
        ".NS",
        ""
    )

    return (
        "https://in.tradingview.com/chart/"
        "?symbol=NSE%3A"
        + code
    )


# ============================================================
# DOWNLOAD DATA
# ============================================================

def download_ohlcv(
    symbol,
    period="5y",
    interval="1d"
):

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

        # Normalize column names
        df.columns = [
            str(c)
            .strip()
            .lower()
            .replace(" ", "_")
            for c in df.columns
        ]

        required = {
            "close",
            "high",
            "low",
            "volume",
        }

        if not required.issubset(
            set(df.columns)
        ):
            return None

        df = df.dropna(
            subset=[
                "close",
                "high",
                "low",
            ]
        )

        if len(df) < MIN_HISTORY_ROWS:
            return None

        return df

    except Exception as e:

        print(
            "Download error:",
            symbol,
            e
        )

        return None


# ============================================================
# RESAMPLE
# ============================================================

def resample_ohlcv(
    df,
    timeframe
):

    x = df.copy()

    if "date" in x.columns:
        date_col = "date"

    elif "datetime" in x.columns:
        date_col = "datetime"

    else:
        return None

    x[date_col] = pd.to_datetime(
        x[date_col],
        errors="coerce"
    )

    x = x.dropna(
        subset=[date_col]
    )

    x = x.set_index(
        date_col
    )

    rules = {
        "Daily": "1D",
        "Weekly": "W-FRI",
        "Monthly": "ME",
    }

    rule = rules[timeframe]

    out = x.resample(
        rule
    ).agg({

        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",

    }).dropna()

    return out.reset_index()


# ============================================================
# RSI
# ============================================================

def rsi(
    series,
    period=14
):

    delta = series.diff()

    gain = delta.clip(
        lower=0
    )

    loss = -delta.clip(
        upper=0
    )

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

    rs = (
        avg_gain /
        avg_loss.replace(
            0,
            np.nan
        )
    )

    return (
        100 -
        (
            100 /
            (1 + rs)
        )
    )


# ============================================================
# PIVOT LOWS
# ============================================================

def local_lows(
    series,
    left=3,
    right=3
):

    values = series.to_numpy(
        dtype=float
    )

    lows = []

    for i in range(
        left,
        len(values) - right
    ):

        window = values[
            i-left:i+right+1
        ]

        if (
            np.isfinite(values[i])
            and
            values[i] == np.min(window)
        ):
            lows.append(i)

    return lows


# ============================================================
# POSITIVE DIVERGENCE
# ============================================================

def find_divergence_setups(df):

    """
    Returns a LIST.

    Possible results:
        RSI Positive Divergence
        Classic Positive Divergence

    Both can be returned independently.

    This function NEVER returns Cup Pattern.
    """

    results = []

    if (
        df is None
        or len(df) < MIN_HISTORY_ROWS
    ):
        return results

    close = df[
        "close"
    ].astype(float)

    rsi_values = rsi(
        close,
        RSI_PERIOD
    )

    lows = local_lows(
        close,
        SWING_LEFT,
        SWING_RIGHT
    )

    if len(lows) < 2:
        return results

    # Test recent pivot pairs
    recent_lows = lows[-8:]

    best_rsi = None
    best_classic = None

    for x in range(
        len(recent_lows) - 1
    ):

        i1 = recent_lows[x]

        for y in range(
            x + 1,
            len(recent_lows)
        ):

            i2 = recent_lows[y]

            gap = i2 - i1

            if (
                gap <= 0
                or gap > MAX_DIVERGENCE_GAP
            ):
                continue

            price1 = float(
                close.iloc[i1]
            )

            price2 = float(
                close.iloc[i2]
            )

            rsi1 = float(
                rsi_values.iloc[i1]
            )

            rsi2 = float(
                rsi_values.iloc[i2]
            )

            if not all(
                np.isfinite(x)
                for x in [
                    price1,
                    price2,
                    rsi1,
                    rsi2,
                ]
            ):
                continue

            price_lower_pct = (
                (price1 - price2)
                / price1
                * 100
            )

            rsi_improvement = (
                rsi2 - rsi1
            )

            signal_age = (
                len(df) - 1 - i2
            )

            if (
                signal_age >
                MAX_SIGNAL_AGE
            ):
                continue

            # ------------------------------------------------
            # RSI POSITIVE DIVERGENCE
            # ------------------------------------------------

            if (
                price_lower_pct
                >= MIN_PRICE_LOWER_LOW_PCT
                and
                rsi_improvement
                >= MIN_RSI_IMPROVEMENT
            ):

                candidate = {
                    "Setup":
                        "RSI Positive Divergence",

                    "Signal Age":
                        signal_age,

                    "RSI Improvement":
                        rsi_improvement,

                    "Price Lower Low":
                        price_lower_pct,
                }

                if (
                    best_rsi is None
                    or
                    signal_age <
                    best_rsi["Signal Age"]
                ):
                    best_rsi = candidate

            # ------------------------------------------------
            # CLASSIC POSITIVE DIVERGENCE
            # ------------------------------------------------

            if (
                price_lower_pct
                >= MIN_PRICE_LOWER_LOW_PCT
                and
                rsi2 > rsi1
            ):

                candidate = {
                    "Setup":
                        "Classic Positive Divergence",

                    "Signal Age":
                        signal_age,

                    "RSI Improvement":
                        rsi_improvement,

                    "Price Lower Low":
                        price_lower_pct,
                }

                if (
                    best_classic is None
                    or
                    signal_age <
                    best_classic["Signal Age"]
                ):
                    best_classic = candidate

    if best_rsi is not None:

        results.append(
            best_rsi
        )

    if best_classic is not None:

        results.append(
            best_classic
        )

    return results


# ============================================================
# SMOOTHING
# ============================================================

def smooth(
    values,
    window
):

    if len(values) < window:
        return values

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
# CUP DETECTOR
# ============================================================

def detect_cup(
    df,
    timeframe
):

    """
    Returns:

        pattern
        status

    Pattern:
        Cup
        Cup with Handle

    Status:
        BEFORE BREAKOUT
        BREAKOUT
        AFTER BREAKOUT

    No divergence logic is used here.
    """

    if df is None:
        return None, ""

    min_bars = CUP_MIN_BARS[
        timeframe
    ]

    max_bars = CUP_MAX_BARS[
        timeframe
    ]

    if len(df) < min_bars:
        return None, ""

    data = df.tail(
        min(
            len(df),
            max_bars + 30
        )
    ).copy()

    close = data[
        "close"
    ].astype(float).to_numpy()

    high = data[
        "high"
    ].astype(float).to_numpy()

    low = data[
        "low"
    ].astype(float).to_numpy()

    n = len(close)

    if n < min_bars:
        return None, ""

    sm = smooth(
        close,
        max(
            3,
            n // 30
        )
    )

    left_zone_end = int(
        n * 0.45
    )

    right_zone_start = int(
        n * 0.55
    )

    if (
        left_zone_end < 5
        or
        right_zone_start >= n - 5
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

    # --------------------------------------------------------
    # FIND CUP
    # --------------------------------------------------------

    for li in left_candidates:

        left_rim = sm[li]

        if left_rim <= 0:
            continue

        bottom_slice = low[
            li + 3:
            right_zone_start
        ]

        if len(bottom_slice) < 5:
            continue

        rel_bottom = int(
            np.argmin(
                bottom_slice
            )
        )

        bi = (
            li
            + 3
            + rel_bottom
        )

        bottom = low[bi]

        depth = (
            (left_rim - bottom)
            / left_rim
        )

        if (
            depth < CUP_MIN_DEPTH
            or
            depth > CUP_MAX_DEPTH
        ):
            continue

        for ri in right_candidates:

            if ri <= bi:
                continue

            right_rim = sm[ri]

            rim_similarity = (
                abs(
                    right_rim -
                    left_rim
                )
                / left_rim
            )

            if (
                rim_similarity >
                RIM_TOLERANCE
            ):
                continue

            left_span = (
                bi - li
            )

            right_span = (
                ri - bi
            )

            if (
                left_span < 5
                or
                right_span < 5
            ):
                continue

            balance = (
                min(
                    left_span,
                    right_span
                )
                /
                max(
                    left_span,
                    right_span
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
                "bottom": bottom,
                "depth": depth,
                "balance": balance,
            }

            if (
                best is None
                or
                candidate["ri"] >
                best["ri"]
            ):
                best = candidate

    if best is None:
        return None, ""

    li = best["li"]
    bi = best["bi"]
    ri = best["ri"]

    rim = max(
        best["left_rim"],
        best["right_rim"]
    )

    breakout_level = (
        rim *
        (1 + BREAKOUT_BUFFER)
    )

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    breakout_index = None

    for j in range(
        ri + 1,
        len(close)
    ):

        if (
            close[j] >
            breakout_level
        ):

            breakout_index = j
            break

    # --------------------------------------------------------
    # HANDLE
    # --------------------------------------------------------

    pattern = "Cup"

    if ri < len(close) - 1:

        handle_start = ri + 1

        handle = close[
            handle_start:
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
                    (
                        handle_high -
                        handle_low
                    )
                    /
                    handle_high
                )

                handle_bars = len(
                    handle
                )

                max_handle_bars = max(
                    3,
                    int(
                        (ri - li)
                        *
                        HANDLE_MAX_BARS_RATIO
                    )
                )

                cup_mid = (
                    best["bottom"]
                    +
                    (
                        rim -
                        best["bottom"]
                    )
                    * 0.50
                )

                if (
                    handle_bars
                    <= max_handle_bars
                    and
                    handle_retrace
                    <= HANDLE_MAX_RETRACE
                    and
                    handle_low
                    >= cup_mid
                ):
                    pattern = (
                        "Cup with Handle"
                    )

    # --------------------------------------------------------
    # STATUS
    # --------------------------------------------------------

    if breakout_index is None:

        status = (
            "BEFORE BREAKOUT"
        )

    else:

        bars_since = (
            len(close)
            - 1
            - breakout_index
        )

        if bars_since <= 2:

            status = "BREAKOUT"

        elif (
            bars_since
            <= RECENT_BREAKOUT_BARS
        ):

            status = (
                "AFTER BREAKOUT"
            )

        else:

            # Old breakout is ignored.
            return None, ""

    return pattern, status


# ============================================================
# GET STOCK NAME + NSE CODE
# ============================================================

def get_nifty200_stocks():

    creds = get_credentials()

    client = gspread.authorize(
        creds
    )

    sh = client.open_by_key(
        SPREADSHEET_ID
    )

    try:

        ws = sh.worksheet(
            INPUT_SHEET
        )

    except gspread.WorksheetNotFound:

        raise RuntimeError(
            "NIFTY200 worksheet not found."
        )

    values = ws.get_all_values()

    if not values:
        raise RuntimeError(
            "NIFTY200 sheet is empty."
        )

    headers = values[0]

    normalized = [
        normalize_header(x)
        for x in headers
    ]

    # --------------------------------------------------------
    # NSE CODE COLUMN
    # --------------------------------------------------------

    code_candidates = [
        "nse code",
        "nse_code",
        "symbol",
        "stock",
        "stock code",
        "stock/nse code",
        "code",
        "nse symbol",
    ]

    code_idx = None

    for candidate in code_candidates:

        if candidate in normalized:

            code_idx = (
                normalized.index(
                    candidate
                )
            )

            break

    if code_idx is None:

        code_idx = 0

    # --------------------------------------------------------
    # STOCK NAME COLUMN
    # --------------------------------------------------------

    name_candidates = [
        "stock name",
        "stock",
        "name",
        "company name",
        "company",
        "security name",
    ]

    name_idx = None

    for candidate in name_candidates:

        if candidate in normalized:

            name_idx = (
                normalized.index(
                    candidate
                )
            )

            break

    stocks = []

    seen = set()

    for row in values[1:]:

        if (
            code_idx >=
            len(row)
        ):
            continue

        code = str(
            row[code_idx]
        ).strip().upper()

        if not code:
            continue

        if code in seen:
            continue

        seen.add(code)

        if (
            name_idx is not None
            and
            name_idx < len(row)
        ):

            name = str(
                row[name_idx]
            ).strip()

        else:

            name = code

        if not name:
            name = code

        stocks.append({
            "Stock Name": name,
            "NSE Code": code,
        })

    return stocks


# ============================================================
# SCAN ONE STOCK
# ============================================================

def scan_stock(
    stock_name,
    nse_code
):

    symbol = yahoo_symbol(
        nse_code
    )

    daily = download_ohlcv(
        symbol,
        period="5y",
        interval="1d"
    )

    if (
        daily is None
        or
        len(daily) <
        MIN_HISTORY_ROWS
    ):
        return []

    current_price = float(
        daily[
            "close"
        ].iloc[-1]
    )

    chart = tradingview_link(
        nse_code
    )

    results = []

    # ========================================================
    # SETUP A — DIVERGENCE
    # ========================================================

    divergence_setups = (
        find_divergence_setups(
            daily
        )
    )

    for div in divergence_setups:

        results.append({

            "Stock Name":
                stock_name,

            "NSE Code":
                nse_code,

            "Setup":
                div["Setup"],

            "Daily Pattern":
                "",

            "Daily Status":
                "",

            "Weekly Pattern":
                "",

            "Weekly Status":
                "",

            "Monthly Pattern":
                "",

            "Monthly Status":
                "",

            "CMP":
                round(
                    current_price,
                    2
                ),

            "Chart Link":
                chart,
        })

    # ========================================================
    # SETUP B — CUP PATTERN
    # ========================================================

    cup_result = {

        "Daily Pattern": "",
        "Daily Status": "",

        "Weekly Pattern": "",
        "Weekly Status": "",

        "Monthly Pattern": "",
        "Monthly Status": "",
    }

    cup_found = False

    for timeframe in [
        "Daily",
        "Weekly",
        "Monthly",
    ]:

        tf_df = resample_ohlcv(
            daily,
            timeframe
        )

        pattern, status = (
            detect_cup(
                tf_df,
                timeframe
            )
        )

        if pattern:

            cup_found = True

            cup_result[
                f"{timeframe} Pattern"
            ] = pattern

            cup_result[
                f"{timeframe} Status"
            ] = status

    # IMPORTANT:
    # Cup gets its OWN row.
    # It is NEVER combined with divergence.

    if cup_found:

        results.append({

            "Stock Name":
                stock_name,

            "NSE Code":
                nse_code,

            "Setup":
                "Cup Pattern",

            "Daily Pattern":
                cup_result[
                    "Daily Pattern"
                ],

            "Daily Status":
                cup_result[
                    "Daily Status"
                ],

            "Weekly Pattern":
                cup_result[
                    "Weekly Pattern"
                ],

            "Weekly Status":
                cup_result[
                    "Weekly Status"
                ],

            "Monthly Pattern":
                cup_result[
                    "Monthly Pattern"
                ],

            "Monthly Status":
                cup_result[
                    "Monthly Status"
                ],

            "CMP":
                round(
                    current_price,
                    2
                ),

            "Chart Link":
                chart,
        })

    return results


# ============================================================
# WRITE FINAL LIST
# ============================================================

def write_final_list(
    rows
):

    creds = get_credentials()

    client = gspread.authorize(
        creds
    )

    sh = client.open_by_key(
        SPREADSHEET_ID
    )

    try:

        ws = sh.worksheet(
            FINAL_LIST_SHEET
        )

    except gspread.WorksheetNotFound:

        ws = sh.add_worksheet(
            title=FINAL_LIST_SHEET,
            rows=1000,
            cols=len(FINAL_COLUMNS)
        )

    ws.clear()

    # Always use fixed columns.
    output = [
        FINAL_COLUMNS
    ]

    for row in rows:

        output.append([
            row.get(
                column,
                ""
            )
            for column in FINAL_COLUMNS
        ])

    ws.update(
        "A1",
        output,
        value_input_option="USER_ENTERED",
    )

    try:
        ws.freeze(
            rows=1
        )
    except Exception:
        pass

    # Header formatting
    try:

        ws.format(
            "A1:K1",
            {
                "textFormat": {
                    "bold": True
                },
                "horizontalAlignment":
                    "CENTER",
            }
        )

    except Exception:
        pass

    print(
        "Final List updated."
    )

    print(
        "Rows:",
        len(rows)
    )

    print(
        "Columns:",
        len(FINAL_COLUMNS)
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=============================================="
    )

    print(
        "NIFTY 200 DIVERGENCE + CUP SCANNER V1.4"
    )

    print(
        "=============================================="
    )

    print(
        "Divergence and Cup are COMPLETELY SEPARATE."
    )

    print(
        "Cup timeframes: Daily / Weekly / Monthly"
    )

    print(
        ""
    )

    stocks = (
        get_nifty200_stocks()
    )

    print(
        "Stocks found:",
        len(stocks)
    )

    results = []

    for number, stock in enumerate(
        stocks,
        start=1
    ):

        stock_name = stock[
            "Stock Name"
        ]

        nse_code = stock[
            "NSE Code"
        ]

        print(
            f"[{number}/{len(stocks)}] "
            f"{nse_code} - {stock_name}"
        )

        try:

            stock_results = (
                scan_stock(
                    stock_name,
                    nse_code
                )
            )

            if stock_results:

                for result in (
                    stock_results
                ):

                    results.append(
                        result
                    )

                    print(
                        "   FOUND:",
                        result["Setup"]
                    )

            else:

                print(
                    "   No setup"
                )

        except Exception as e:

            print(
                "   ERROR:",
                e
            )

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    setup_order = {

        "RSI Positive Divergence":
            1,

        "Classic Positive Divergence":
            2,

        "Cup Pattern":
            3,
    }

    results.sort(
        key=lambda x: (
            setup_order.get(
                x.get(
                    "Setup",
                    ""
                ),
                99
            ),
            x.get(
                "Stock Name",
                ""
            ),
            x.get(
                "NSE Code",
                ""
            ),
        )
    )

    # --------------------------------------------------------
    # WRITE
    # --------------------------------------------------------

    write_final_list(
        results
    )

    print(
        ""
    )

    print(
        "=============================================="
    )

    print(
        "SCAN COMPLETE"
    )

    print(
        "Qualified rows:",
        len(results)
    )

    print(
        "=============================================="
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as exc:

        print(
            "FATAL ERROR:",
            exc
        )

        sys.exit(1)
