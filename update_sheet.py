# =========================================================
# NIFTY 200 SWING SNIPER V1
# =========================================================
#
# PURPOSE:
#   2–10 DAY SWING TRADING
#
# FINAL LIST PRIORITY:
#
#   1. RETEST + HOLD        = Highest
#   2. FRESH BREAKOUT       = High
#   3. BREAKOUT WATCH       = Medium
#
# CORE LOGIC:
#
#   NIFTY 200
#   EMA 20 > EMA 50
#   Close > EMA 20
#   10-Day High Breakout
#   Volume Expansion
#   RSI 55–70
#   Consolidation / Base
#   Breakout Retest
#
# NO:
#   NR4
#   NR7
#   Inside Bar
#   Bollinger Band
#   MACD
#
# OUTPUT:
#   Entry
#   Stop Loss
#   Target 1
#   Target 2
#   Risk %
#   Setup
#   Strength Score
#   TradingView Chart
# =========================================================


import os
import json
import io
import zipfile
import requests
import gspread
import pandas as pd
import numpy as np
import time

from datetime import datetime, timedelta
from urllib.parse import quote
from oauth2client.service_account import ServiceAccountCredentials


# =========================================================
# CONFIG
# =========================================================

SPREADSHEET_ID = "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E"

NIFTY_SHEET = "NIFTY200"
FINAL_SHEET = "Final List"

TOP_STOCKS = 200

# Need enough history for EMA50 + RSI + ATR + breakout
HISTORY_TRADING_DAYS = 70

BREAKOUT_LOOKBACK = 10

VOLUME_LOOKBACK = 20

VOLUME_MULTIPLIER = 1.5

RSI_MIN = 55
RSI_MAX = 70

# Retest can happen within last few sessions
RETEST_LOOKBACK = 5

# How close today's low can come to breakout level
RETEST_TOLERANCE = 0.015


# =========================================================
# GOOGLE LOGIN
# =========================================================

creds_json = os.environ.get("GCP_CREDENTIALS")

if not creds_json:
    raise Exception("GCP_CREDENTIALS Secret Missing")

creds_dict = json.loads(creds_json)

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_dict(
    creds_dict,
    scope
)

client = gspread.authorize(creds)


# =========================================================
# GOOGLE SHEETS SAFE RETRY
# =========================================================

def _is_retryable_google_error(exc):

    text = str(exc)

    return any(
        code in text
        for code in ("429", "500", "502", "503", "504")
    )


def safe_google_call(func, *args, retries=6, **kwargs):

    last_error = None

    for attempt in range(retries):

        try:
            return func(*args, **kwargs)

        except gspread.exceptions.APIError as exc:

            last_error = exc

            if (
                not _is_retryable_google_error(exc)
                or attempt == retries - 1
            ):
                raise

            wait = min(30, 2 ** attempt)

            print(
                f"Google Sheets API retry "
                f"{attempt + 1}/{retries} after {wait}s : {exc}"
            )

            time.sleep(wait)

    raise last_error


def safe_batch_clear(sheet, ranges):

    return safe_google_call(
        sheet.batch_clear,
        ranges
    )


def safe_update(sheet, *args, **kwargs):

    return safe_google_call(
        sheet.update,
        *args,
        **kwargs
    )


def safe_format(sheet, *args, **kwargs):

    return safe_google_call(
        sheet.format,
        *args,
        **kwargs
    )


# =========================================================
# GOOGLE SHEETS
# =========================================================

spreadsheet = safe_google_call(
    client.open_by_key,
    SPREADSHEET_ID
)


try:

    sheet_nifty = spreadsheet.worksheet(
        NIFTY_SHEET
    )

except gspread.WorksheetNotFound:

    sheet_nifty = spreadsheet.add_worksheet(
        title=NIFTY_SHEET,
        rows=500,
        cols=30
    )


try:

    sheet_final = spreadsheet.worksheet(
        FINAL_SHEET
    )

except gspread.WorksheetNotFound:

    sheet_final = spreadsheet.add_worksheet(
        title=FINAL_SHEET,
        rows=500,
        cols=30
    )


# =========================================================
# NSE BHAVCOPY
# =========================================================

def fetch_bhavcopy(date_obj):

    date_str = date_obj.strftime("%Y%m%d")

    url = (
        "https://nsearchives.nseindia.com/"
        "content/cm/"
        f"BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv.zip"
    )

    headers = {

        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/151.0 Safari/537.36"
        ),

        "Accept": "*/*",

        "Referer": "https://www.nseindia.com/"
    }

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=30
        )

        if response.status_code != 200:
            return None

        with zipfile.ZipFile(
            io.BytesIO(response.content)
        ) as z:

            csv_file = z.namelist()[0]

            with z.open(csv_file) as f:

                df = pd.read_csv(f)


        df.columns = [
            str(c).strip()
            for c in df.columns
        ]


        # =================================================
        # COLUMN FINDER
        # =================================================

        def find_column(names):

            for name in names:

                if name in df.columns:
                    return name

            return None


        symbol_col = find_column([
            "TckrSymb",
            "SYMBOL"
        ])


        open_col = find_column([
            "OpnPric",
            "OPEN",
            "Open"
        ])


        high_col = find_column([
            "HghPric",
            "HIGH",
            "High"
        ])


        low_col = find_column([
            "LwPric",
            "LOW",
            "Low"
        ])


        close_col = find_column([
            "ClsPric",
            "CLOSE",
            "Close"
        ])


        turnover_col = find_column([
            "TtlTrfVal",
            "TOTTRDVAL",
            "Turnover",
            "TURNOVER"
        ])


        # Volume / Quantity
        volume_col = find_column([
            "TtlTradgVol",
            "TOTTRDQTY",
            "TotalTradedQuantity",
            "TOTTRDVAL"
        ])


        series_col = find_column([
            "SctySrs",
            "SERIES",
            "Series"
        ])


        required = {

            "Symbol": symbol_col,

            "Open": open_col,

            "High": high_col,

            "Low": low_col,

            "Close": close_col,

            "Turnover": turnover_col,

            "Volume": volume_col

        }


        if any(
            value is None
            for value in required.values()
        ):

            print(
                "Bhavcopy required column missing:",
                required
            )

            return None


        # =================================================
        # ONLY EQUITY
        # =================================================

        if series_col:

            df = df[
                df[series_col]
                .astype(str)
                .str.strip()
                .str.upper()
                == "EQ"
            ]


        # =================================================
        # NUMERIC
        # =================================================

        for col in [

            open_col,
            high_col,
            low_col,
            close_col,
            turnover_col,
            volume_col

        ]:

            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )


        df = df.dropna(
            subset=[

                open_col,
                high_col,
                low_col,
                close_col,
                turnover_col,
                volume_col

            ]
        )


        return {

            "df": df,

            "symbol_col": symbol_col,

            "open_col": open_col,

            "high_col": high_col,

            "low_col": low_col,

            "close_col": close_col,

            "turnover_col": turnover_col,

            "volume_col": volume_col

        }


    except Exception as e:

        print(
            f"Bhavcopy Error {date_str}: {e}"
        )

        return None


# =========================================================
# FIND LATEST TRADING DAY
# =========================================================

now = datetime.now()

latest_data = None
latest_date = None


for i in range(10):

    check_date = now - timedelta(days=i)

    if check_date.weekday() >= 5:
        continue


    result = fetch_bhavcopy(
        check_date
    )


    if result is not None:

        latest_data = result

        latest_date = check_date

        break


if latest_data is None:

    raise Exception(
        "Latest NSE Bhavcopy not found"
    )


latest_df = latest_data["df"]

symbol_col = latest_data["symbol_col"]

turnover_col = latest_data["turnover_col"]


print(
    "Latest Trading Day:",
    latest_date.strftime("%d-%b-%Y")
)


# =========================================================
# TOP 200 BY TURNOVER
# =========================================================

exclude_words = (
    "BEES|ETF|GOLD|LIQUID|SILVER|INDEX"
)


top200 = (

    latest_df[

        ~latest_df[symbol_col]
        .astype(str)
        .str.contains(
            exclude_words,
            case=False,
            na=False
        )

    ]

    .sort_values(
        turnover_col,
        ascending=False
    )

    .head(TOP_STOCKS)

    .copy()

)


top200_symbols = set(

    top200[symbol_col]
    .astype(str)
    .str.strip()

)


turnover_rank = {

    str(row[symbol_col]).strip(): rank

    for rank, (_, row)
    in enumerate(
        top200.iterrows(),
        start=1
    )

}


print(
    f"Top {TOP_STOCKS} Stocks Found: "
    f"{len(top200)}"
)


# =========================================================
# FETCH HISTORY
# =========================================================

history_by_date = {}

check_date = latest_date


while len(history_by_date) < HISTORY_TRADING_DAYS:

    if check_date.weekday() < 5:

        result = fetch_bhavcopy(
            check_date
        )

        if result is not None:

            history_by_date[
                check_date.strftime("%Y-%m-%d")
            ] = result


    check_date -= timedelta(days=1)


    if (
        latest_date - check_date
    ).days > 110:

        break


history_dates = sorted(
    history_by_date.keys()
)


if len(history_dates) < 55:

    raise Exception(
        f"Only {len(history_dates)} trading days "
        "available. At least 55 are required."
    )


print(
    f"Historical Trading Days Loaded: "
    f"{len(history_dates)}"
)


# =========================================================
# BUILD SYMBOL HISTORY
# =========================================================

symbol_history = {}


for date_key in history_dates:

    data = history_by_date[date_key]

    df = data["df"]

    s_col = data["symbol_col"]

    o_col = data["open_col"]

    h_col = data["high_col"]

    l_col = data["low_col"]

    c_col = data["close_col"]

    v_col = data["volume_col"]


    for _, row in df.iterrows():

        symbol = str(
            row[s_col]
        ).strip()


        if symbol not in top200_symbols:
            continue


        item = {

            "date": date_key,

            "open": float(
                row[o_col]
            ),

            "high": float(
                row[h_col]
            ),

            "low": float(
                row[l_col]
            ),

            "close": float(
                row[c_col]
            ),

            "volume": float(
                row[v_col]
            )

        }


        symbol_history.setdefault(
            symbol,
            []
        ).append(item)


# =========================================================
# SORT
# =========================================================

for symbol in symbol_history:

    symbol_history[symbol].sort(
        key=lambda x: x["date"]
    )


# =========================================================
# INDICATOR FUNCTIONS
# =========================================================

def calculate_rsi(close_series, period=14):

    delta = close_series.diff()

    gain = delta.clip(
        lower=0
    )

    loss = -delta.clip(
        upper=0
    )


    avg_gain = gain.rolling(
        period
    ).mean()


    avg_loss = loss.rolling(
        period
    ).mean()


    rs = avg_gain / avg_loss.replace(
        0,
        np.nan
    )


    rsi = 100 - (
        100 / (1 + rs)
    )


    return rsi


def calculate_atr(df, period=14):

    previous_close = df["close"].shift(1)


    tr1 = (
        df["high"]
        - df["low"]
    )


    tr2 = (
        df["high"]
        - previous_close
    ).abs()


    tr3 = (
        df["low"]
        - previous_close
    ).abs()


    true_range = pd.concat(
        [tr1, tr2, tr3],
        axis=1
    ).max(axis=1)


    atr = true_range.rolling(
        period
    ).mean()


    return atr


# =========================================================
# SWING SCAN
# =========================================================

final_rows = []


for _, latest_row in top200.iterrows():

    symbol = str(
        latest_row[symbol_col]
    ).strip()


    hist = symbol_history.get(
        symbol,
        []
    )


    if len(hist) < 55:
        continue


    df = pd.DataFrame(
        hist
    )


    # =====================================================
    # INDICATORS
    # =====================================================

    df["EMA20"] = (
        df["close"]
        .ewm(
            span=20,
            adjust=False
        )
        .mean()
    )


    df["EMA50"] = (
        df["close"]
        .ewm(
            span=50,
            adjust=False
        )
        .mean()
    )


    df["RSI14"] = calculate_rsi(
        df["close"],
        14
    )


    df["ATR14"] = calculate_atr(
        df,
        14
    )


    df["Volume20"] = (
        df["volume"]
        .rolling(20)
        .mean()
    )


    # =====================================================
    # TODAY
    # =====================================================

    today = df.iloc[-1]

    previous = df.iloc[-2]


    close = float(
        today["close"]
    )


    high = float(
        today["high"]
    )


    low = float(
        today["low"]
    )


    ema20 = float(
        today["EMA20"]
    )


    ema50 = float(
        today["EMA50"]
    )


    rsi = float(
        today["RSI14"]
    )


    atr = float(
        today["ATR14"]
    )


    volume = float(
        today["volume"]
    )


    avg_volume = float(
        today["Volume20"]
    )


    if any(
        pd.isna(x)
        for x in [
            ema20,
            ema50,
            rsi,
            atr,
            avg_volume
        ]
    ):

        continue


    # =====================================================
    # TREND
    # =====================================================

    trend_ok = (

        ema20 > ema50

        and

        close > ema20

    )


    if not trend_ok:
        continue


    # =====================================================
    # 10-DAY BREAKOUT LEVEL
    #
    # IMPORTANT:
    # Today's candle is NOT included.
    #
    # This prevents self-comparison.
    # =====================================================

    previous_10_high = (
        df["high"]
        .iloc[-11:-1]
        .max()
    )


    previous_10_low = (
        df["low"]
        .iloc[-11:-1]
        .min()
    )


    # =====================================================
    # BREAKOUT
    #
    # CLOSE must break the 10-day high.
    # Intraday wick alone is NOT enough.
    # =====================================================

    fresh_breakout = (

        close
        > previous_10_high

    )


    # =====================================================
    # VOLUME CONFIRMATION
    # =====================================================

    volume_ratio = (

        volume
        / avg_volume

    )


    volume_ok = (

        volume_ratio
        >= VOLUME_MULTIPLIER

    )


    # =====================================================
    # RSI
    # =====================================================

    rsi_ok = (

        RSI_MIN
        <= rsi
        <= RSI_MAX

    )


    # =====================================================
    # CONSOLIDATION
    #
    # Previous 10-day range relative to price
    # =====================================================

    recent_10 = df.iloc[-11:-1]


    range_high = (
        recent_10["high"].max()
    )


    range_low = (
        recent_10["low"].min()
    )


    consolidation_range_pct = (

        (
            range_high
            - range_low
        )
        /
        close
        *
        100

    )


    # =====================================================
    # RETEST DETECTION
    #
    # Search last 5 sessions for a genuine
    # closing breakout.
    #
    # Then today's candle comes back near the
    # breakout level but closes above it.
    # =====================================================

    retest = False

    breakout_level = np.nan

    breakout_date = ""


    if len(df) >= 17:

        start_index = max(
            10,
            len(df)
            - RETEST_LOOKBACK
            - 1
        )


        for idx in range(
            start_index,
            len(df) - 1
        ):

            candidate = df.iloc[idx]


            prior_10_high = (
                df["high"]
                .iloc[
                    idx - 10:
                    idx
                ]
                .max()
            )


            candidate_close = float(
                candidate["close"]
            )


            # Previous session must have
            # closed above its 10-day high
            candidate_breakout = (

                candidate_close
                > prior_10_high

            )


            if not candidate_breakout:
                continue


            level = float(
                prior_10_high
            )


            # Today's low comes back near
            # the breakout level
            retest_zone_low = (
                level
                * (1 - RETEST_TOLERANCE)
            )


            retest_zone_high = (
                level
                * (1 + RETEST_TOLERANCE)
            )


            today_retested = (

                low
                <= retest_zone_high

                and

                low
                >= retest_zone_low

                and

                close
                > level

            )


            if today_retested:

                retest = True

                breakout_level = level

                breakout_date = str(
                    candidate["date"]
                )

                break


    # =====================================================
    # WATCH SETUP
    #
    # Stock is close to breakout but has not yet
    # produced a confirmed closing breakout.
    # =====================================================

    near_breakout = (

        close
        >= previous_10_high * 0.985

        and

        close
        <= previous_10_high * 1.015

    )


    # =====================================================
    # FINAL SETUP
    # =====================================================

    setup = None


    if retest:

        setup = "RETEST + HOLD"


    elif fresh_breakout and volume_ok and rsi_ok:

        setup = "FRESH BREAKOUT"


    elif near_breakout and rsi_ok:

        setup = "BREAKOUT WATCH"


    else:

        continue


    # =====================================================
    # BREAKOUT LEVEL
    # =====================================================

    if retest:

        entry_level = float(
            breakout_level
        )

    else:

        entry_level = float(
            previous_10_high
        )


    # =====================================================
    # ENTRY
    # =====================================================

    if setup == "RETEST + HOLD":

        entry = close

    elif setup == "FRESH BREAKOUT":

        entry = close

    else:

        # Planned entry only
        entry = entry_level


    # =====================================================
    # STOP LOSS
    #
    # Use recent 5-day low minus ATR buffer.
    # =====================================================

    recent_5_low = float(
        df["low"]
        .iloc[-5:]
        .min()
    )


    stop_loss = (
        recent_5_low
        - (atr * 0.25)
    )


    # Make sure SL is below entry

    if stop_loss >= entry:

        stop_loss = (
            entry
            - atr
        )


    risk = (
        entry
        - stop_loss
    )


    if risk <= 0:
        continue


    risk_pct = (
        risk
        /
        entry
        *
        100
    )


    # =====================================================
    # TARGETS
    # =====================================================

    target_1 = (
        entry
        + (risk * 1.5)
    )


    target_2 = (
        entry
        + (risk * 3.0)
    )


    # =====================================================
    # STRENGTH SCORE
    # =====================================================

    score = 0


    # Trend
    score += 20


    # Price above EMA20
    if close > ema20:
        score += 10


    # EMA20 vs EMA50 distance
    ema_distance_pct = (

        (
            ema20
            - ema50
        )
        /
        ema50
        *
        100

    )


    if ema_distance_pct > 2:
        score += 10


    # RSI
    if 55 <= rsi <= 65:
        score += 15

    elif 65 < rsi <= 70:
        score += 10


    # Volume
    if volume_ratio >= 2:
        score += 20

    elif volume_ratio >= 1.5:
        score += 15


    # Breakout
    if fresh_breakout:
        score += 15


    # Retest bonus
    if retest:
        score += 15


    # Consolidation bonus
    if consolidation_range_pct <= 12:
        score += 5


    # Cap
    score = min(
        score,
        100
    )


    # =====================================================
    # TODAY CHANGE
    # =====================================================

    previous_close = float(
        previous["close"]
    )


    if previous_close != 0:

        today_change_pct = (

            (
                close
                - previous_close
            )
            /
            previous_close
            *
            100

        )

    else:

        today_change_pct = 0


    # =====================================================
    # TRADINGVIEW
    # =====================================================

    chart_symbol = quote(
        f"NSE:{symbol}",
        safe=""
    )


    chart_formula = (

        '=HYPERLINK('

        f'"https://www.tradingview.com/chart/'
        f'?symbol={chart_symbol}&interval=D",'

        '"Daily Chart")'

    )


    # =====================================================
    # FINAL ROW
    # =====================================================

    final_rows.append([

        # A
        symbol,

        # B
        turnover_rank.get(
            symbol,
            999
        ),

        # C
        latest_row[turnover_col],

        # D
        round(close, 2),

        # E
        round(ema20, 2),

        # F
        round(ema50, 2),

        # G
        round(rsi, 2),

        # H
        round(volume_ratio, 2),

        # I
        round(previous_10_high, 2),

        # J
        round(entry_level, 2),

        # K
        round(entry, 2),

        # L
        round(stop_loss, 2),

        # M
        round(target_1, 2),

        # N
        round(target_2, 2),

        # O
        round(risk_pct, 2),

        # P
        round(today_change_pct, 2),

        # Q
        setup,

        # R
        score,

        # S
        round(consolidation_range_pct, 2),

        # T
        round(volume_ratio, 2),

        # U
        round(atr, 2),

        # V
        breakout_date,

        # W
        chart_formula

    ])


# =========================================================
# SORT
# =========================================================
#
# Priority:
#
#   RETEST + HOLD
#   FRESH BREAKOUT
#   BREAKOUT WATCH
#
# Then score.
# =========================================================

def setup_priority(setup):

    if setup == "RETEST + HOLD":
        return 3

    if setup == "FRESH BREAKOUT":
        return 2

    if setup == "BREAKOUT WATCH":
        return 1

    return 0


final_rows.sort(

    key=lambda row: (

        setup_priority(
            row[16]
        ),

        int(row[17]),

        -int(row[1])

    ),

    reverse=True

)


# =========================================================
# HEADERS
# =========================================================

final_headers = [

    "NSE Code",

    "Turnover Rank",

    "Turnover",

    "Close",

    "EMA 20",

    "EMA 50",

    "RSI 14",

    "Volume x Avg",

    "10-Day High",

    "Breakout Level",

    "Entry",

    "Stop Loss",

    "Target 1",

    "Target 2",

    "Risk %",

    "Today Change %",

    "Setup",

    "Strength Score",

    "10-Day Range %",

    "Volume Ratio",

    "ATR 14",

    "Breakout Date",

    "Chart"

]


# =========================================================
# CLEAR OLD DATA
# =========================================================

safe_batch_clear(
    sheet_final,
    ["A1:AZ1000"]
)


safe_batch_clear(
    sheet_nifty,
    ["A1:AZ1000"]
)


# =========================================================
# WRITE FINAL LIST
# =========================================================

safe_update(

    sheet_final,

    "A1:W1",

    [final_headers],

    value_input_option="RAW"

)


if final_rows:

    safe_update(

        sheet_final,

        "A2",

        final_rows,

        value_input_option="USER_ENTERED"

    )


# =========================================================
# WRITE NIFTY200
# =========================================================

nifty_headers = [

    "Rank",

    "NSE Code",

    "Turnover"

]


nifty_rows = []


for rank, (_, row) in enumerate(

    top200.iterrows(),

    start=1

):

    nifty_rows.append([

        rank,

        str(
            row[symbol_col]
        ).strip(),

        row[turnover_col]

    ])


safe_update(

    sheet_nifty,

    "A1:C1",

    [nifty_headers],

    value_input_option="RAW"

)


if nifty_rows:

    safe_update(

        sheet_nifty,

        "A2",

        nifty_rows,

        value_input_option="USER_ENTERED"

    )


# =========================================================
# FORMATTING
# =========================================================

try:

    safe_format(

        sheet_final,

        "A1:W1",

        {

            "textFormat": {

                "bold": True,

                "fontSize": 10

            },

            "horizontalAlignment":
                "CENTER",

            "verticalAlignment":
                "MIDDLE",

            "wrapStrategy":
                "WRAP"

        }

    )


    if final_rows:

        last_row = (
            len(final_rows)
            + 1
        )


        safe_format(

            sheet_final,

            f"A2:W{last_row}",

            {

                "fontSize": 9,

                "horizontalAlignment":
                    "CENTER",

                "verticalAlignment":
                    "MIDDLE"

            }

        )


    sheet_final.freeze(
        rows=1
    )


except Exception as e:

    print(
        f"Formatting Warning: {e}"
    )


# =========================================================
# SUMMARY
# =========================================================

retest_count = sum(

    1

    for row in final_rows

    if row[16]
    == "RETEST + HOLD"

)


breakout_count = sum(

    1

    for row in final_rows

    if row[16]
    == "FRESH BREAKOUT"

)


watch_count = sum(

    1

    for row in final_rows

    if row[16]
    == "BREAKOUT WATCH"

)


print(
    "========================================"
)

print(
    "NIFTY 200 SWING SNIPER V1"
)

print(
    "========================================"
)

print(

    "Trading Date:",

    latest_date.strftime(
        "%d-%b-%Y"
    )

)

print(

    f"Stocks Scanned: "
    f"{len(top200)}"

)

print(

    f"Retest + Hold: "
    f"{retest_count}"

)

print(

    f"Fresh Breakout: "
    f"{breakout_count}"

)

print(

    f"Breakout Watch: "
    f"{watch_count}"

)

print(

    f"Final List: "
    f"{len(final_rows)}"

)

print(
    "========================================"
)

print(
    "TREND: EMA20 > EMA50 + CLOSE > EMA20"
)

print(
    "BREAKOUT: DAILY CLOSE > PREVIOUS 10-DAY HIGH"
)

print(
    "VOLUME: >= 1.5X 20-DAY AVERAGE"
)

print(
    "RSI: 55–70"
)

print(
    "RETEST: BREAKOUT LEVEL RECLAIM + HOLD"
)

print(
    "TARGETS: 1.5R / 3R"
)

print(
    "NR4 / NR7 / INSIDE BAR: REMOVED"
)

print(
    "========================================"
)
