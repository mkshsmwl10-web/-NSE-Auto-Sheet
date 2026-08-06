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
# TEMP TEST SIGNAL
# ======================================

output = []

for _ in df.itertuples():

    output.append([
        "TEST",
        "YES",
        "BUY",
        100
    ])

sheet.update(
    range_name="K2:N201",
    values=output
)

print("Signal Columns Updated")
print("SIGNAL ENGINE COMPLETED SUCCESSFULLY")
