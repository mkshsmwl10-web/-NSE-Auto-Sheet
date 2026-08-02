import gspread
from oauth2client.service_account import ServiceAccountCredentials

SPREADSHEET_ID = "13Jy8xJB9l6SQ124aEIAF3wFJRvJIUXX6jOH61rFb3zY"

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name(
    "service_account.json", scope
)

client = gspread.authorize(creds)

sheet = client.open_by_key(SPREADSHEET_ID).worksheet("Sheet2")

print(sheet.acell("A2").value)
