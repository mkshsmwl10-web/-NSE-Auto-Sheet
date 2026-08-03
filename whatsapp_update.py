import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd

# ----------------------------
# GOOGLE LOGIN
# ----------------------------

creds_json = os.environ["GCP_CREDENTIALS"]

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

# ----------------------------
# OPEN GOOGLE SHEET
# ----------------------------

SPREADSHEET_ID = "13Jy8xJB9l6SQ124aEIAF3wFJRvJIUXX6jOH61rFb3zY"

sheet = client.open_by_key(SPREADSHEET_ID).worksheet("Dashboard")

data = sheet.get_all_records()

df = pd.DataFrame(data)

print(df)
