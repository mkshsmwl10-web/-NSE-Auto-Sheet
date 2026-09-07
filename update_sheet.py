# =========================================================
# NIFTY 200 DAILY INSIDE BAR + NR4 + NR7 SCREENER
# =========================================================
#
# FINAL LIST = ONLY:
#   1. INSIDE BAR
#   2. NR4
#   3. NR7
#
# No BB / RSI / MACD / EMA / reversal / chart-pattern logic.
#
# INSIDE BAR:
#   Today's High <= Previous High
#   Today's Low  >= Previous Low
#
# NR4:
#   Today's range is the smallest range of latest 4 trading days.
#
# NR7:
#   Today's range is the smallest range of latest 7 trading days.
#
# NEW:
#   Setup High       = Previous Candle High
#   Setup Low        = Previous Candle Low
#   Breakout Above   = Today's High > Setup High
#   Breakdown Below  = Today's Low < Setup Low
#
# CHART:
#   Final List includes clickable TradingView Daily Chart.
# =========================================================

import os
import json
import io
import zipfile
import requests
import gspread
import pandas as pd
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
HISTORY_TRADING_DAYS = 10


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

        # -------------------------------------------------
        # SYMBOL
        # -------------------------------------------------

        symbol_col = next(
            (
                c
                for c in [
                    "TckrSymb",
                    "SYMBOL"
                ]
                if c in df.columns
            ),
            None
        )

        # -------------------------------------------------
        # OPEN
        # -------------------------------------------------

        open_col = next(
            (
                c
                for c in [
                    "OpnPric",
                    "OPEN",
                    "Open"
                ]
                if c in df.columns
            ),
            None
        )

        # -------------------------------------------------
        # HIGH
        # -------------------------------------------------

        high_col = next(
            (
                c
                for c in [
                    "HghPric",
                    "HIGH",
                    "High"
                ]
                if c in df.columns
            ),
            None
        )

        # -------------------------------------------------
        # LOW
        # -------------------------------------------------

        low_col = next(
            (
                c
                for c in [
                    "LwPric",
                    "LOW",
                    "Low"
                ]
                if c in df.columns
            ),
            None
        )

        # -------------------------------------------------
        # CLOSE
        # -------------------------------------------------

        close_col = next(
            (
                c
                for c in [
                    "ClsPric",
                    "CLOSE",
                    "Close"
                ]
                if c in df.columns
            ),
            None
        )

        # -------------------------------------------------
        # TURNOVER
        # -------------------------------------------------

        turnover_col = next(
            (
                c
                for c in [
                    "TtlTrfVal",
                    "TOTTRDVAL",
                    "Turnover",
                    "TURNOVER"
                ]
                if c in df.columns
            ),
            None
        )

        # -------------------------------------------------
        # SERIES
        # -------------------------------------------------

        series_col = next(
            (
                c
                for c in [
                    "SctySrs",
                    "SERIES",
                    "Series"
                ]
                if c in df.columns
            ),
            None
        )

        required = {

            "Symbol": symbol_col,

            "Open": open_col,

            "High": high_col,

            "Low": low_col,

            "Close": close_col,

            "Turnover": turnover_col

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

        # -------------------------------------------------
        # ONLY EQUITY
        # -------------------------------------------------

        if series_col:

            df = df[
                df[series_col]
                .astype(str)
                .str.strip()
                .str.upper()
                == "EQ"
            ]

        # -------------------------------------------------
        # NUMERIC CONVERSION
        # -------------------------------------------------

        for col in [
            open_col,
            high_col,
            low_col,
            close_col,
            turnover_col
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
                turnover_col
            ]
        )

        return {

            "df": df,

            "symbol_col": symbol_col,

            "open_col": open_col,

            "high_col": high_col,

            "low_col": low_col,

            "close_col": close_col,

            "turnover_col": turnover_col

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

open_col = latest_data["open_col"]

high_col = latest_data["high_col"]

low_col = latest_data["low_col"]

close_col = latest_data["close_col"]

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
# FETCH RECENT TRADING DAYS
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

    # Safety stop
    if (
        latest_date - check_date
    ).days > 30:

        break


history_dates = sorted(
    history_by_date.keys()
)


if len(history_dates) < 7:

    raise Exception(
        f"Only {len(history_dates)} trading days "
        "available. At least 7 are required for NR7."
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
            )

        }

        symbol_history.setdefault(
            symbol,
            []
        ).append(item)


# =========================================================
# SORT HISTORY
# =========================================================

for symbol in symbol_history:

    symbol_history[symbol].sort(
        key=lambda x: x["date"]
    )


# =========================================================
# DETECT INSIDE BAR / NR4 / NR7
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


    if len(hist) < 7:
        continue


    today = hist[-1]

    previous = hist[-2]


    # -----------------------------------------------------
    # TODAY RANGE
    # -----------------------------------------------------

    today_range = (
        today["high"]
        - today["low"]
    )


    # Avoid invalid candles
    if today_range <= 0:
        continue


    # -----------------------------------------------------
    # PREVIOUS RANGE
    # -----------------------------------------------------

    previous_range = (
        previous["high"]
        - previous["low"]
    )


    # -----------------------------------------------------
    # LAST 4 RANGES
    # -----------------------------------------------------

    ranges_4 = [

        bar["high"] - bar["low"]

        for bar in hist[-4:]

    ]


    # -----------------------------------------------------
    # LAST 7 RANGES
    # -----------------------------------------------------

    ranges_7 = [

        bar["high"] - bar["low"]

        for bar in hist[-7:]

    ]


    # =====================================================
    # INSIDE BAR
    # =====================================================

    inside_bar = (

        today["high"]
        <= previous["high"]

        and

        today["low"]
        >= previous["low"]

    )


    # =====================================================
    # NR4
    # =====================================================

    nr4 = (

        today_range
        == min(ranges_4)

    )


    # =====================================================
    # NR7
    # =====================================================

    nr7 = (

        today_range
        == min(ranges_7)

    )


    # -----------------------------------------------------
    # ONLY STOCKS WITH A SETUP
    # -----------------------------------------------------

    if not (
        inside_bar
        or nr4
        or nr7
    ):

        continue


    # =====================================================
    # SETUP TEXT
    # =====================================================

    setups = []


    if inside_bar:
        setups.append(
            "INSIDE BAR"
        )


    if nr4:
        setups.append(
            "NR4"
        )


    if nr7:
        setups.append(
            "NR7"
        )


    setup_text = " + ".join(
        setups
    )


    # =====================================================
    # SETUP HIGH / LOW
    # =====================================================
    #
    # Setup candle = Previous candle
    #
    # This gives us a clean breakout/breakdown
    # reference for today's compressed candle.
    # =====================================================

    setup_high = previous["high"]

    setup_low = previous["low"]


    # =====================================================
    # BREAKOUT / BREAKDOWN
    # =====================================================

    breakout_above = (

        today["high"]
        > setup_high

    )


    breakdown_below = (

        today["low"]
        < setup_low

    )


    # =====================================================
    # TODAY CHANGE %
    # =====================================================

    previous_close = previous["close"]


    if previous_close != 0:

        today_change_pct = (

            (
                today["close"]
                - previous_close
            )

            / previous_close

            * 100

        )

    else:

        today_change_pct = 0.0


    # =====================================================
    # TRADINGVIEW CHART
    # =====================================================
    #
    # quote(..., safe="") makes symbols such as:
    #
    # M&M
    #
    # safe for URL.
    #
    # Example:
    # NSE:M&M
    #
    # becomes:
    # NSE%3AM%26M
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
        today["open"],

        # E
        today["high"],

        # F
        today["low"],

        # G
        today["close"],

        # H
        today_range,

        # I
        previous["high"],

        # J
        previous["low"],

        # K
        previous_range,

        # L
        round(
            today_change_pct,
            2
        ),

        # M
        "YES"
        if inside_bar
        else "NO",

        # N
        "YES"
        if nr4
        else "NO",

        # O
        "YES"
        if nr7
        else "NO",

        # P
        setup_text,

        # Q
        setup_high,

        # R
        setup_low,

        # S
        "YES"
        if breakout_above
        else "NO",

        # T
        "YES"
        if breakdown_below
        else "NO",

        # U
        chart_formula

    ])


# =========================================================
# SORT
# =========================================================
#
# Priority:
#   1. NR7
#   2. NR4
#   3. Inside Bar
#   4. Turnover rank
#
# More compressed setups get higher priority.
# =========================================================

def setup_priority(row):

    setup_text = str(
        row[15]
    )


    if "NR7" in setup_text:
        return 3


    if "NR4" in setup_text:
        return 2


    if "INSIDE BAR" in setup_text:
        return 1


    return 0


final_rows.sort(

    key=lambda row: (

        setup_priority(row),

        -int(row[1])

    ),

    reverse=True

)


# =========================================================
# FINAL LIST HEADERS
# =========================================================

final_headers = [

    "NSE Code",

    "Turnover Rank",

    "Turnover",

    "Today Open",

    "Today High",

    "Today Low",

    "Today Close",

    "Today Range",

    "Previous High",

    "Previous Low",

    "Previous Range",

    "Today Change %",

    "Inside Bar?",

    "NR4?",

    "NR7?",

    "Setup",

    "Setup High",

    "Setup Low",

    "Breakout Above?",

    "Breakdown Below?",

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

    "A1:U1",

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
# WRITE SIMPLE NIFTY200 DATA
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

    # -----------------------------------------------------
    # HEADER
    # -----------------------------------------------------

    safe_format(

        sheet_final,

        "A1:U1",

        {

            "textFormat": {

                "bold": True,

                "fontSize": 10

            },

            "horizontalAlignment": "CENTER",

            "verticalAlignment": "MIDDLE",

            "wrapStrategy": "WRAP"

        }

    )


    # -----------------------------------------------------
    # DATA
    # -----------------------------------------------------

    if final_rows:

        last_row = (
            len(final_rows)
            + 1
        )


        safe_format(

            sheet_final,

            f"A2:U{last_row}",

            {

                "fontSize": 9,

                "horizontalAlignment":
                    "CENTER",

                "verticalAlignment":
                    "MIDDLE"

            }

        )


    # -----------------------------------------------------
    # FREEZE HEADER
    # -----------------------------------------------------

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

inside_count = sum(

    1

    for row in final_rows

    if row[12] == "YES"

)


nr4_count = sum(

    1

    for row in final_rows

    if row[13] == "YES"

)


nr7_count = sum(

    1

    for row in final_rows

    if row[14] == "YES"

)


breakout_count = sum(

    1

    for row in final_rows

    if row[18] == "YES"

)


breakdown_count = sum(

    1

    for row in final_rows

    if row[19] == "YES"

)


print(
    "========================================"
)

print(
    "DAILY INSIDE BAR + NR4 + NR7 SCREENER"
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

    f"Inside Bar: "
    f"{inside_count}"

)

print(

    f"NR4: "
    f"{nr4_count}"

)

print(

    f"NR7: "
    f"{nr7_count}"

)

print(

    f"Breakout Above: "
    f"{breakout_count}"

)

print(

    f"Breakdown Below: "
    f"{breakdown_count}"

)

print(

    f"Final List: "
    f"{len(final_rows)}"

)

print(
    "========================================"
)

print(
    "BB / RSI / MACD / EMA / PATTERN LOGIC: REMOVED"
)

print(
    "SETUPS: INSIDE BAR / NR4 / NR7"
)

print(
    "SETUP HIGH/LOW: PREVIOUS CANDLE"
)

print(
    "BREAKOUT: TODAY HIGH > SETUP HIGH"
)

print(
    "BREAKDOWN: TODAY LOW < SETUP LOW"
)

print(
    "CHART: CLICKABLE TRADINGVIEW DAILY CHART"
)

print(
    "========================================"
)
