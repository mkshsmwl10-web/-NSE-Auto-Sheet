import os
import json
import gspread
import pandas as pd

from oauth2client.service_account import ServiceAccountCredentials

# ======================================
# GOOGLE LOGIN
# ======================================

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

# ======================================
# GOOGLE SHEET
# ======================================

SPREADSHEET_ID = "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E"

sheet = client.open_by_key(
    SPREADSHEET_ID
).worksheet("MACD200")

# ======================================
# LOAD DATA
# ======================================

data = sheet.get_all_records()

print(f"Loaded {len(data)} Stocks")

if len(data) == 0:
    raise Exception("MACD200 Sheet is Empty")

print("GOOGLE SHEET CONNECTED SUCCESSFULLY")

# ======================================
# CREATE DATAFRAME
# ======================================

df = pd.DataFrame(data)

required_columns = [
    "Symbol",
    "M0","M-1","M-2",
    "W0","W-1","W-2",
    "D0","D-1","D-2"
]

for col in required_columns:
    if col not in df.columns:
        raise Exception(f"Column Missing : {col}")

print("All Required Columns Found")

# ======================================
# CHECK SIGNAL COLUMNS
# ======================================

new_columns = [
    "Weekly_Turn",
    "Daily_Cross",
    "Signal",
    "Score"
]

for col in new_columns:
    if col not in df.columns:
        raise Exception(f"Column Missing : {col}")

print("Signal Columns Found")
# ======================================
# MACD VALUE PARSER
# ======================================

def get_value(text):

    text = str(text).strip()

    if text == "" or text == "NA":
        return None

    text = (
        text.replace("↑", "")
            .replace("↓", "")
            .replace("+", "")
    )

    try:
        return float(text)
    except:
        return None

print("MACD Parser Loaded")
# ======================================
# WEEKLY FRESH TURN DETECTOR
# ======================================

def weekly_turn(w2, w1, w0):

    if None in [w2, w1, w0]:
        return "NA"

    # Fresh Turn Up
    # Histogram pehle gir raha tha, ab mud gaya
    if w2 > w1 and w0 > w1:
        return "TURN UP"

    # Fresh Turn Down
    # Histogram pehle badh raha tha, ab neeche mud gaya
    if w2 < w1 and w0 < w1:
        return "TURN DOWN"

    # Already Rising
    if w2 < w1 < w0:
        return "RISING"

    # Already Falling
    if w2 > w1 > w0:
        return "FALLING"

    return "FLAT"
# ======================================
# DAILY CONFIRMATION
# ======================================

def daily_confirm(d0):

    if d0 is None:
        return "NO"

    if d0 > 0:
        return "YES"

    return "NO"

print("Daily Confirmation Loaded")
# ======================================
# DAILY MACD CROSS DETECTOR
# ======================================

# ======================================
# DAILY POSITIVE
# ======================================

def daily_positive(d0):

    if d0 is None:
        return "NO"

    if d0 > 0:
        return "YES"

    return "NO"


# ======================================
# DAILY FRESH CROSS
# ======================================

def daily_cross(d1, d0):

    if d1 is None or d0 is None:
        return "NO"

    if d1 <= 0 and d0 > 0:
        return "YES"

    return "NO"

print("Daily Signal Engine Loaded")

print("Daily Cross Detector Loaded")

# ======================================
# REAL SIGNAL ENGINE
# ======================================

output = []

for _, row in df.iterrows():

    print(
        row["Symbol"],
        "W:",
        row["W-2"],
        row["W-1"],
        row["W0"],
        "D:",
        row["D-1"],
        row["D0"]
    )

    w2 = get_value(row["W-2"])
    w1 = get_value(row["W-1"])
    w0 = get_value(row["W0"])

    d1 = get_value(row["D-1"])
    d0 = get_value(row["D0"])

    weekly = weekly_turn(w2, w1, w0)

    daily_positive_signal = daily_positive(d0)
    daily_cross_signal = daily_cross(d1, d0)

    score = 0
    signal = "WAIT"

    # Weekly Turn Score

   if weekly == "TURN UP":
    score += 70

elif weekly == "RISING":
    score += 40

    # Daily Positive Score
   if daily_positive_signal == "YES":
    score += 30

    # Bonus for Fresh Daily Cross
    if daily_cross_signal == "YES":
        score += 10

    # Maximum Score = 100
    if score > 100:
        score = 100

    # Final Signal
    if score >= 100:
        signal = "BUY"

    elif score >= 60:
        signal = "WATCH"

    else:
        signal = "WAIT"

    output.append([
        weekly,
        daily_positive_signal,
        signal,
        score
    ])

sheet.update(
    range_name="K2:N201",
    values=output
)

print("UPGRADED SIGNAL ENGINE COMPLETED")
