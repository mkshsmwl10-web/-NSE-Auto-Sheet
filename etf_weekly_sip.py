import os
import json
import math
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import yfinance as yf
import pandas as pd

# =========================================================
# GOOGLE LOGIN
# =========================================================

creds_json = os.environ["GCP_CREDENTIALS"]

creds = ServiceAccountCredentials.from_json_keyfile_dict(
    json.loads(creds_json),
    [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
)

client = gspread.authorize(creds)

SPREADSHEET_ID = "13Jy8xJB9l6SQ124aEIAF3wFJRvJIUXX6jOH61rFb3zY"

sheet = client.open_by_key(
    SPREADSHEET_ID
).worksheet("Sheet0")

print("GOOGLE SHEET CONNECTED")

# =========================================================
# READ ETF + STOCK SYMBOLS
# A3 SE START
# =========================================================

symbols = []

all_values = sheet.col_values(1)

for s in all_values[2:]:

    s = str(s).strip()

    if (
        s == ""
        or s.startswith("#")
        or s in ["NA", "N/A", "#NUM!", "#N/A"]
    ):
        continue

    symbols.append(s)

print("ETF + STOCK SYMBOLS LOADED:", len(symbols))

# =========================================================
# RESULT ROWS
# =========================================================

rows = []

# =========================================================
# PROCESS EACH STOCK / ETF
# =========================================================

for s in symbols:

    clean_symbol = s.replace("NSE:", "").strip()
    ticker = clean_symbol + ".NS"

    print("Processing:", ticker)

    try:

        # -------------------------------------------------
        # DOWNLOAD DAILY DATA
        # Daily data is converted to Friday weekly data.
        # This gives a much closer TradingView-style
        # Weekly Close calculation.
        # -------------------------------------------------

        df = yf.download(
            ticker,
            period="8mo",
            interval="1d",
            progress=False,
            auto_adjust=False
        )

        if df.empty:
            rows.append([
                s,
                "",
                "",
                "",
                "",
                "NO DATA"
            ])
            continue

        # -------------------------------------------------
        # GET CLOSE COLUMN
        # -------------------------------------------------

        close_data = df["Close"]

        if isinstance(close_data, pd.DataFrame):
            close_data = close_data.iloc[:, 0]

        close_data = close_data.dropna()

        if len(close_data) < 20:
            rows.append([
                s,
                "",
                "",
                "",
                "",
                "NO DATA"
            ])
            continue

        # -------------------------------------------------
        # CONVERT DAILY CLOSE TO FRIDAY WEEKLY CLOSE
        # -------------------------------------------------

        weekly_close = close_data.resample("W-FRI").last().dropna()

        if len(weekly_close) < 20:
            rows.append([
                s,
                "",
                "",
                "",
                "",
                "NO DATA"
            ])
            continue

        # -------------------------------------------------
        # CURRENT WEEKLY CLOSE
        # -------------------------------------------------

        weekly_close_value = float(
            weekly_close.iloc[-1]
        )

        # -------------------------------------------------
        # 20 WEEK SMA
        # -------------------------------------------------

        sma20_series = weekly_close.rolling(
            window=20,
            min_periods=20
        ).mean()

        sma20_value = float(
            sma20_series.iloc[-1]
        )

        # -------------------------------------------------
        # SAFETY CHECK
        # -------------------------------------------------

        if (
            math.isnan(weekly_close_value)
            or math.isnan(sma20_value)
            or sma20_value == 0
        ):
            rows.append([
                s,
                "",
                "",
                "",
                "",
                "NO DATA"
            ])
            continue

        # -------------------------------------------------
        # DIFFERENCE %
        # -------------------------------------------------

        difference = (
            (weekly_close_value - sma20_value)
            / sma20_value
        ) * 100

        difference = round(difference, 2)

        # -------------------------------------------------
        # ACTION
        #
        # BELOW 20W SMA = SIP
        # ABOVE 20W SMA = WAIT
        # -------------------------------------------------

        if difference < 0:
            action = "SIP"
        else:
            action = "WAIT"

        rows.append([
            s,
            round(weekly_close_value, 2),
            round(sma20_value, 2),
            difference,
            "",
            action
        ])

    except Exception as e:

        print("ERROR:", s, e)

        rows.append([
            s,
            "",
            "",
            "",
            "",
            "ERROR"
        ])

# =========================================================
# RANK ONLY NEGATIVE DIFFERENCE
#
# MOST NEGATIVE = RANK 1
# =========================================================

negative_rows = []

for index, row in enumerate(rows):

    difference = row[3]

    if (
        isinstance(difference, (int, float))
        and difference < 0
    ):
        negative_rows.append(
            (index, difference)
        )

# ---------------------------------------------------------
# Example:
#
# -25% = Rank 1
# -18% = Rank 2
# -12% = Rank 3
# -5%  = Rank 4
# +2%  = No Rank
# ---------------------------------------------------------

negative_rows.sort(
    key=lambda x: x[1]
)

# =========================================================
# ASSIGN RANK
# =========================================================

for rank, (index, difference) in enumerate(
    negative_rows,
    start=1
):

    rows[index][4] = rank

# =========================================================
# MAIN HEADER
# J3:O3
# =========================================================

header = [[
    "ETF / STOCK",
    "Weekly Close",
    "20W SMA",
    "Difference %",
    "Rank",
    "Action"
]]

sheet.update(
    values=header,
    range_name="J3:O3"
)

# =========================================================
# CLEAR OLD MAIN DATA
# =========================================================

sheet.batch_clear([
    "J4:O1000"
])

# =========================================================
# WRITE MAIN DATA
# =========================================================

if rows:

    sheet.update(
        values=rows,
        range_name=f"J4:O{3 + len(rows)}"
    )

# =========================================================
# SIP LIST
# P3:R3
# =========================================================

sip_list = []

for row in rows:

    rank = row[4]
    action = row[5]

    if (
        isinstance(rank, int)
        and rank > 0
        and action == "SIP"
    ):

        sip_list.append([
            rank,
            row[0],
            row[3]
        ])

# =========================================================
# SORT SIP LIST BY RANK
# =========================================================

sip_list.sort(
    key=lambda x: x[0]
)

# =========================================================
# SIP HEADER
# =========================================================

sip_header = [[
    "Rank",
    "ETF / STOCK",
    "Difference %"
]]

sheet.update(
    values=sip_header,
    range_name="P3:R3"
)

# =========================================================
# CLEAR OLD SIP LIST
# =========================================================

sheet.batch_clear([
    "P4:R1000"
])

# =========================================================
# WRITE SIP LIST
# =========================================================

if sip_list:

    sheet.update(
        values=sip_list,
        range_name=f"P4:R{3 + len(sip_list)}"
    )

# =========================================================
# FINAL STATUS
# =========================================================

print("----------------------------------------")
print("ETF + STOCK WEEKLY SIP UPDATED")
print("TOTAL SYMBOLS:", len(rows))
print("NEGATIVE / SIP SYMBOLS:", len(sip_list))
print("RANK 1 = MOST NEGATIVE DIFFERENCE")
print("NEGATIVE DIFFERENCE = SIP")
print("POSITIVE DIFFERENCE = WAIT")
print("MAIN DATA = J:O")
print("SIP RANK LIST = P:R")
print("----------------------------------------")
