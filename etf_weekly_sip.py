import os, json, math
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import yfinance as yf

# -------------------------
# GOOGLE LOGIN
# -------------------------

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

# -------------------------
# READ ETF SYMBOLS
# A3 SE START
# -------------------------

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

print("ETF SCRIPT STARTED - SHEET0:", len(symbols))

# -------------------------
# DOWNLOAD DATA
# -------------------------

rows = []

for s in symbols:

    if "#" in s:
        continue

    ticker = s.replace("NSE:", "") + ".NS"

    print("Processing", ticker)

    try:

        df = yf.download(
            ticker,
            period="30wk",
            interval="1wk",
            progress=False,
            auto_adjust=False
        )

        if df.empty:
            rows.append([
                s, "", "", "", "", "NO DATA"
            ])
            continue

        close_series = df["Close"].dropna()

        if len(close_series) < 20:
            rows.append([
                s, "", "", "", "", "NO DATA"
            ])
            continue

        close = float(close_series.iloc[-1])

        sma20 = float(
            close_series.tail(20).mean()
        )

        if math.isnan(close) or math.isnan(sma20):
            rows.append([
                s, "", "", "", "", "NO DATA"
            ])
            continue

        # Difference %
        diff = round(
            (close - sma20) / sma20 * 100,
            2
        )

        # -------------------------
        # ACTION
        # -------------------------

        if diff < 0:
            action = "SIP"
        else:
            action = "WAIT"

        rows.append([
            s,
            round(close, 2),
            round(sma20, 2),
            diff,
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

# -------------------------
# RANK ONLY NEGATIVE DIFFERENCE
# MOST NEGATIVE = RANK 1
# -------------------------

negative_rows = []

for i, row in enumerate(rows):

    if isinstance(row[3], (int, float)) and row[3] < 0:
        negative_rows.append(
            (i, row[3])
        )

# Most negative first
negative_rows.sort(
    key=lambda x: x[1]
)

# -------------------------
# ASSIGN RANK
# -------------------------

for rank, (index, diff) in enumerate(
    negative_rows,
    start=1
):

    rows[index][4] = rank

# -------------------------
# HEADER
# -------------------------

header = [[
    "ETF",
    "Weekly Close",
    "20W SMA",
    "Difference %",
    "Rank",
    "Action"
]]

# -------------------------
# UPDATE SHEET0
# J3:O3
# -------------------------

sheet.update(
    values=header,
    range_name="J3:O3"
)

# -------------------------
# UPDATE DATA
# J4:O...
# -------------------------

if rows:

    sheet.update(
        values=rows,
        range_name=f"J4:O{3 + len(rows)}"
    )

print("ETF WEEKLY SIP - SHEET0 UPDATED")
print("ETF COUNT:", len(rows))
print("RANK = NEGATIVE DIFFERENCE ONLY")
print("MOST NEGATIVE = RANK 1")
print("ACTION = NEGATIVE DIFFERENCE -> SIP")
print("ACTION = POSITIVE DIFFERENCE -> WAIT")
# -------------------------
# SIP ETF LIST - P3
# RANK WISE
# -------------------------

sip_list = []

for row in rows:

    if (
        isinstance(row[4], int)
        and row[4] > 0
        and row[5] == "SIP"
    ):
        sip_list.append([
            row[4],   # Rank
            row[0],   # ETF
            row[3]    # Difference %
        ])

# Rank 1, 2, 3, 4... order
sip_list.sort(key=lambda x: x[0])

# Header P3:R3
sip_header = [[
    "Rank",
    "ETF",
    "Difference %"
]]

sheet.update(
    values=sip_header,
    range_name="P3:R3"
)

# Clear old SIP list area
sheet.batch_clear([
    "P4:R500"
])

# Write current SIP list
if sip_list:

    sheet.update(
        values=sip_list,
        range_name=f"P4:R{3 + len(sip_list)}"
    )

print("SIP ETF RANK LIST UPDATED - P3")
