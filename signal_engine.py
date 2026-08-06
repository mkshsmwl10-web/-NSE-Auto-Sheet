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
