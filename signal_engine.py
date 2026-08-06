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
# WEEKLY TURN DETECTOR
# ======================================

def weekly_turn(w2, w1, w0):

    if None in [w2, w1, w0]:
        return "NA"

    # Histogram rising
    if w2 < w1 < w0:
        return "TURN UP"

    # Histogram falling
    if w2 > w1 > w0:
        return "TURN DOWN"

    return "FLAT"

print("Weekly Turn Detector Loaded")
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

def daily_cross(d1, d0):

    if d1 is None or d0 is None:
        return "NO"

    if d1 <= 0 and d0 > 0:
        return "YES"

    return "NO"


print("Daily Cross Detector Loaded")


# ======================================
# REAL SIGNAL ENGINE
# ======================================

output = []

for _, row in df.iterrows():

    w2 = get_value(row["W-2"])
    w1 = get_value(row["W-1"])
    w0 = get_value(row["W0"])

    d1 = get_value(row["D-1"])
    d0 = get_value(row["D0"])


    weekly = weekly_turn(w2, w1, w0)

    daily = daily_cross(d1, d0)


    score = 0
    signal = "WAIT"


    # Weekly confirmation
    if weekly == "TURN UP":
        score += 2


    # Daily confirmation
    if daily == "YES":
        score += 2


    # Final Decision

    if score >= 4:
        signal = "STRONG BUY"

    elif score >= 2:
        signal = "WATCH"

    else:
        signal = "WAIT"


    output.append([
        weekly,
        daily,
        signal,
        score
    ])


sheet.update(
    range_name="K2:N201",
    values=output
)


print("UPGRADED SIGNAL ENGINE COMPLETED")
