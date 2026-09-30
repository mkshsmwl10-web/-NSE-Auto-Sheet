import os,json
from datetime import datetime,time as dt_time
from zoneinfo import ZoneInfo
import gspread,yfinance as yf
from google.oauth2.service_account import Credentials
SPREADSHEET_ID=os.environ.get("SPREADSHEET_ID","1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E")
IST=ZoneInfo("Asia/Kolkata")
def book():
 raw=os.environ["GCP_CREDENTIALS"]; info=json.loads(raw)
 c=Credentials.from_service_account_info(info,scopes=["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"])
 return gspread.authorize(c).open_by_key(SPREADSHEET_ID)
def n(v):
 try:return float(str(v).replace(",","").strip()) if v not in ("",None) else 0
 except:return 0
def main():
 now=datetime.now(IST); t=now.time().replace(tzinfo=None)
 if now.weekday()>=5 or not(dt_time(9,15)<=t<=dt_time(15,30)):
  print("Outside market hours"); return
 b=book(); ws=b.worksheet("Trend Scanner"); tx=b.worksheet("Trade Transactions")
 tv=tx.get_all_values(); pos={}
 if len(tv)>1:
  h={x.strip():i for i,x in enumerate(tv[0])}
  for r in tv[1:]:
   def c(k): return r[h[k]].strip() if k in h and h[k]<len(r) else ""
   code=c("NSE Code").upper(); a=c("Action").upper()
   if a=="BUY": pos[code]=(n(c("Price")),int(n(c("Units"))))
   elif a=="EXIT": pos.pop(code,None)
 if not pos:return
 syms=[x+".NS" for x in pos]; prices={}
 for s0 in range(0,len(syms),40):
  ch=syms[s0:s0+40]
  try:
   d=yf.download(ch,period="1d",interval="1m",auto_adjust=False,progress=False,threads=True,group_by="ticker",prepost=False)
   for s in ch:
    try:
     p=d if len(ch)==1 else d[s]; q=p["Close"].dropna()
     if not q.empty: prices[s[:-3]]=round(float(q.iloc[-1]),2)
    except:pass
  except Exception as e: print(e)
 vals=ws.get_all_values(); hd={x.strip():i for i,x in enumerate(vals[0])}; ups=[]; live=0
 for rn,r in enumerate(vals[1:],2):
  code=r[hd["NSE Code"]].strip().upper()
  if code not in pos:continue
  if code not in prices:
   live+=n(r[hd["PROFIT/LOSS"]]) if hd["PROFIT/LOSS"]<len(r) else 0; continue
  bp,u=pos[code]; cmp=prices[code]; val=round(cmp*u,2); pnl=round((cmp-bp)*u,2); pct=round((cmp-bp)/bp*100,2) if bp else 0; live+=pnl
  for col,v in [("C",cmp),("K",val),("L",pnl),("M",pct)]: ups.append({"range":f"{col}{rn}","values":[[v]]})
 if ups: ws.batch_update(ups,value_input_option="USER_ENTERED")
 booked=n(ws.acell("T8").value); ws.update(range_name="T7:T9",values=[[round(live,2)],[round(booked,2)],[round(live+booked,2)]],value_input_option="USER_ENTERED")
 print("P/L refreshed; NO BUY/EXIT.")
if __name__=="__main__":main()
