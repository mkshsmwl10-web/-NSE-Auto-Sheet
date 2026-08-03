import os, json, math
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import yfinance as yf

creds_json = os.environ["GCP_CREDENTIALS"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(
    json.loads(creds_json),
    ["https://spreadsheets.google.com/feeds",
     "https://www.googleapis.com/auth/drive"]
)
client = gspread.authorize(creds)

SPREADSHEET_ID="13Jy8xJB9l6SQ124aEIAF3wFJRvJIUXX6jOH61rFb3zY"
sheet=client.open_by_key(SPREADSHEET_ID).worksheet("sheet2")

symbols=[s for s in sheet.col_values(1)[1:] if s.strip()]
print("ETF SCRIPT STARTED", len(symbols))

header=[["ETF","Weekly Close","20W SMA","Difference %","Signal"]]
rows=[]

for s in symbols:
    ticker=s.replace("NSE:","")+".NS"
    print("Processing",ticker)
    try:
        df=yf.download(ticker,period="30wk",interval="1wk",progress=False,auto_adjust=False)
        if df.empty:
            rows.append([s,"","","","NO DATA"])
            continue
        close_series=df["Close"].dropna()
        if len(close_series)<20:
            rows.append([s,"","","","NO DATA"])
            continue
        close=float(close_series.iloc[-1])
        sma20=float(close_series.tail(20).mean())
        if math.isnan(close) or math.isnan(sma20):
            rows.append([s,"","","","NO DATA"])
            continue
        diff=round((close-sma20)/sma20*100,2)
        signal="BUY" if close<sma20 else "WAIT"
        rows.append([s,round(close,2),round(sma20,2),diff,signal])
    except Exception as e:
        print(e)
        rows.append([s,"","","","ERROR"])

sheet.update(values=header, range_name="R1")
sheet.update(values=rows, range_name="R2")
print("ETF WEEKLY SIP SHEET UPDATED")
