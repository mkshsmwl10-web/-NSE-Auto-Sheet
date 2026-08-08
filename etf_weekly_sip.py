```python
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

# -------------------------
# SHEET0
# -------------------------

sheet = client.open_by_key(
    SPREADSHEET_ID
).worksheet("Sheet0")

# -------------------------
# READ ETF SYMBOLS
# A3 COLUMN SE START
# -------------------------

symbols = []

all_values = sheet.col_values(1)

# A3 se data read hoga
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

header = [[
    "ETF",
    "Weekly Close",
    "20W SMA",
    "Difference %",
    "Signal"
]]

rows = []

for s in symbols:

    # Skip bad symbols
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
            rows.append([s, "", "", "", "NO DATA"])
            continue

        close_series = df["Close"].dropna()

        if len(close_series) < 20:
            rows.append([s, "", "", "", "NO DATA"])
            continue

        close = float(close_series.iloc[-1])
        sma20 = float(close_series.tail(20).mean())

        if math.isnan(close) or math.isnan(sma20):
            rows.append([s, "", "", "", "NO DATA"])
            continue

        diff = round((close - sma20) / sma20 * 100, 2)

        signal = "BUY" if close < sma20 else "WAIT"

        rows.append([
            s,
            round(close, 2),
            round(sma20, 2),
            diff,
            signal
        ])

    except Exception as e:

        print("ERROR:", s, e)

        rows.append([
            s,
            "",
            "",
            "",
            "ERROR"
        ])

# -------------------------
# UPDATE SHEET0
# J3 SE RESULT START
# -------------------------

# Header J3:N3
sheet.update(
    values=header,
    range_name="J3:N3"
)

# Data J4:N...
if rows:
    sheet.update(
        values=rows,
        range_name=f"J4:N{3 + len(rows)}"
    )

print("ETF WEEKLY SIP - SHEET0 UPDATED")
print("ETF COUNT:", len(rows))
```
