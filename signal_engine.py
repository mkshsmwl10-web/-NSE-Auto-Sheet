import gspread
import pandas as pd
import json
import os

from oauth2client.service_account import ServiceAccountCredentials

# ======================================
# GOOGLE LOGIN
# ======================================

creds_json = os.environ.get("GCP_CREDENTIALS")

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

SPREADSHEET_ID = "1bNXvVoDXgBmB-R_w6nJr4sBVYK6E"

sheet = client.open_by_key(
    SPREADSHEET_ID
).worksheet("MACD200")

data = sheet.get_all_records()

print(f"Loaded {len(data)} Stocks")
