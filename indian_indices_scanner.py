#!/usr/bin/env python3
"""Separate Indian index relative-strength scanner and interactive chart publisher.

This never modifies half_month_scanner.py / update_sheet.py.
Tracked leaders are chosen from user-editable candidate stocks, not a claim of
ranking all official constituents. Price returns are not total returns.
"""
import json, os, math, time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path
from datetime import date
from urllib.parse import quote
import gspread
import pandas as pd
import yfinance as yf
from google.oauth2.service_account import Credentials

SHEET_ID=os.getenv("SPREADSHEET_ID","1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E")
UNIVERSE="Index Universe"
RESULTS="Index Strength"
LEADERS="Index Leaders"
CHART=Path("docs/charts/indian-index-strength.html")
URL="https://mkshsmwl10-web.github.io/-NSE-Auto-Sheet/docs/charts/indian-index-strength.html"
# Core India/NSE index catalog; Yahoo coverage may vary by ticker.
# Users can update symbols/candidate baskets in the Index Universe tab.
SEED=[
("Broad","NIFTY 50","^NSEI","RELIANCE,HDFCBANK,ICICIBANK,BHARTIARTL,SBIN,LT,TCS,INFY"),
("BSE","BSE SENSEX","^BSESN","RELIANCE,HDFCBANK,ICICIBANK,BHARTIARTL,LT,TCS,INFY,AXISBANK"),
("BSE","BSE 100","^BSE100","RELIANCE,HDFCBANK,ICICIBANK,SBIN,LT,TCS,INFY"),
("BSE","BSE 200","^BSE200","RELIANCE,HDFCBANK,ICICIBANK,SBIN,LT,TCS,INFY"),
("BSE","BSE 500","^BSE500","RELIANCE,HDFCBANK,ICICIBANK,SBIN,LT,TCS,INFY"),
("Broad","NIFTY NEXT 50","^NSMIDCP","BEL,HAL,DMART,TRENT,INDIGO,SIEMENS,ABB"),
("Broad","NIFTY 100","^CNX100","RELIANCE,HDFCBANK,ICICIBANK,BHARTIARTL,SBIN,LT,TCS"),
("Broad","NIFTY 200","^NSE200","RELIANCE,HDFCBANK,ICICIBANK,BHARTIARTL,SBIN,LT,TCS"),
("Broad","NIFTY 500","^CRSLDX","RELIANCE,HDFCBANK,ICICIBANK,BHARTIARTL,SBIN,TCS"),
("Broad","NIFTY MIDCAP 50","^NSEMDCP50","BSE,CDSL,COFORGE,PERSISTENT,FEDERALBNK"),
("Broad","NIFTY MIDCAP 100","^NSEMDCP100","BSE,CDSL,COFORGE,PERSISTENT,FEDERALBNK"),
("Broad","NIFTY MIDCAP 150","^NSEMDCP150","BSE,CDSL,COFORGE,PERSISTENT,FEDERALBNK"),
("Broad","NIFTY SMALLCAP 50","^NSESMCP50","CAMS,IEX,IRCON,RVNL,HUDCO"),
("Broad","NIFTY SMALLCAP 100","^NSESMCP100","CAMS,IEX,IRCON,RVNL,HUDCO"),
("Broad","NIFTY SMALLCAP 250","^NSESMCP250","CAMS,IEX,IRCON,RVNL,HUDCO"),
("Broad","NIFTY MIDCAP SELECT","^NSEMDCPSELECT","PERSISTENT,COFORGE,MAXHEALTH,POLYCAB"),
("Sector","NIFTY BANK","^NSEBANK","HDFCBANK,ICICIBANK,SBIN,AXISBANK,KOTAKBANK,INDUSINDBK"),
("Sector","NIFTY PRIVATE BANK","^NIFTYPVTBANK","HDFCBANK,ICICIBANK,AXISBANK,KOTAKBANK,INDUSINDBK"),
("Sector","NIFTY PSU BANK","^CNXPSUBANK","SBIN,BANKBARODA,PNB,CANBK,UNIONBANK"),
("Sector","NIFTY FINANCIAL SERVICES","^CNXFINANCE","HDFCBANK,ICICIBANK,BAJFINANCE,SBIN,SHRIRAMFIN"),
("Sector","NIFTY IT","^CNXIT","TCS,INFY,HCLTECH,WIPRO,TECHM,PERSISTENT"),
("Sector","NIFTY AUTO","^CNXAUTO","MARUTI,M&M,TATAMOTORS,BAJAJ-AUTO,EICHERMOT,TVSMOTOR"),
("Sector","NIFTY FMCG","^CNXFMCG","HINDUNILVR,ITC,NESTLEIND,BRITANNIA,DABUR,VBL"),
("Sector","NIFTY PHARMA","^CNXPHARMA","SUNPHARMA,DRREDDY,CIPLA,LUPIN,AUROPHARMA,DIVISLAB"),
("Sector","NIFTY METAL","^CNXMETAL","TATASTEEL,JSWSTEEL,HINDALCO,SAIL,NATIONALUM"),
("Sector","NIFTY REALTY","^CNXREALTY","DLF,GODREJPROP,OBEROIRLTY,PRESTIGE,PHOENIXLTD"),
("Sector","NIFTY ENERGY","^CNXENERGY","RELIANCE,ONGC,NTPC,POWERGRID,COALINDIA"),
("Sector","NIFTY OIL & GAS","^NIFTYOILGAS","RELIANCE,ONGC,IOC,BPCL,GAIL"),
("Sector","NIFTY INFRA","^CNXINFRA","LT,ADANIPORTS,NTPC,POWERGRID,ULTRACEMCO"),
("Sector","NIFTY MEDIA","^CNXMEDIA","ZEEL,SUNTV,PVRINOX,NETWORK18"),
("Sector","NIFTY CONSUMER DURABLES","^NIFTYCONSDUR","TITAN,VOLTAS,BLUESTAR,DIXON,HAVELLS"),
("Sector","NIFTY HEALTHCARE","^NIFTYHEALTHCARE","MAXHEALTH,APOLLOHOSP,FORTIS,SUNPHARMA,CIPLA"),
("Sector","NIFTY PSE","^CNXPSE","NTPC,ONGC,POWERGRID,COALINDIA,BEL"),
("Sector","NIFTY COMMODITIES","^CNXCOMMODITIES","TATASTEEL,JSWSTEEL,ULTRACEMCO,HINDALCO,ONGC"),
("Thematic","NIFTY INDIA CONSUMPTION","^CNXCONSUMPTION","BHARTIARTL,ITC,TITAN,INDHOTEL,DMART"),
("Thematic","NIFTY DEFENCE","^NIFTYDEFENCE","BEL,HAL,BDL,MAZDOCK,COCHINSHIP"),
("Thematic","NIFTY INDIA DIGITAL","^NIFTYINDIADIGITAL","BHARTIARTL,INFY,TCS,PERSISTENT,NAUKRI"),
("Thematic","NIFTY EV & NEW AGE AUTO","^NIFTYEV","M&M,TVSMOTOR,EICHERMOT,BAJAJ-AUTO,TATAMOTORS"),
("Strategy","NIFTY 100 LOW VOLATILITY 30","^NIFTY100LV30","HINDUNILVR,ITC,POWERGRID,NTPC,BRITANNIA"),
("Strategy","NIFTY 500 MOMENTUM 50","^NIFTY500MOM50","BEL,HAL,BSE,CDSL,PERSISTENT"),
]
HEAD=["Category","Index Name","Yahoo Symbol","Tracked Stock Candidates (comma-separated)","Enabled (YES/NO)"]
COLS=["Rank","Category","Index","Ticker","Price Date","CMP","1M Return %","3M Return %",
      "NIFTY50 1M %","1M Excess %","1M Outperform?","3M Excess %",
      "3M Outperform?","Data Status","Index Chart"]
LHEAD=["Index","Leader Rank","NSE Stock","Stock 1M %","Stock 3M %","Index 3M %","3M Excess %","Stock CMP","Price Date","Stock Chart","Universe"]
def connect():
    raw=os.environ["GCP_CREDENTIALS"].strip()
    scope=["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
    cred=(Credentials.from_service_account_info(json.loads(raw),scopes=scope) if raw.startswith("{")
          else Credentials.from_service_account_file(raw,scopes=scope))
    return gspread.authorize(cred).open_by_key(SHEET_ID)
def ws(book,name,cols=16):
    try:return book.worksheet(name)
    except gspread.WorksheetNotFound:return book.add_worksheet(title=name,rows=150,cols=cols)
def number(x):
    try:
        f=float(x)
        return round(f,2) if math.isfinite(f) else ""
    except (ValueError,TypeError):return ""
def source(book):
    tab=ws(book,UNIVERSE,6)
    values=tab.get_all_values()
    if not any(any(str(c).strip() for c in row) for row in values):
        contents=[HEAD]+[[a,b,c,d,"YES"] for a,b,c,d in SEED]
        tab.resize(rows=max(150,len(contents)+2),cols=6)
        tab.update(contents,range_name="A1:E"+str(len(contents)),value_input_option="RAW")
        values=contents
    tab.freeze(rows=1)
    tab.format("A1:E1",{"backgroundColor":{"red":0.10,"green":0.22,"blue":0.32},
          "textFormat":{"bold":True,"foregroundColor":{"red":1,"green":1,"blue":1}}})
    result=[]
    for row in values[1:]:
        row=(row+[""]*5)[:5]
        cat,name,ticker,candidates,enabled=[x.strip() for x in row]
        if not name or not ticker or enabled.upper() in ("NO","FALSE","0"):continue
        pool=list(dict.fromkeys(x.strip().upper().removesuffix(".NS") for x in candidates.split(",") if x.strip()))
        result.append((cat,name,ticker,pool))
    return result
def download(ticker):
    for attempt in range(2):
        try:
            df=yf.Ticker(ticker).history(period="1y",interval="1d",auto_adjust=False)
            if df is None or df.empty:return None
            df=df[["Open","High","Low","Close","Volume"]].dropna(subset=["Close"]).copy()
            df.index=pd.to_datetime(df.index).tz_localize(None).normalize()
            df=df[~df.index.duplicated(keep="last")].sort_index()
            return df if len(df)>=25 else None
        except Exception as ex:
            print("Fetch error",ticker,str(ex)[:90])
            time.sleep(attempt+1)
    return None
def _nse_history_post(name, start, finish):
    """Request official price-return OHLC; parse NSE's doubly encoded JSON."""
    body={"cinfo":("{'name':'"+name.upper()+"','startDate':'"+
                   start.strftime("%d %b %Y")+"','endDate':'"+
                   finish.strftime("%d %b %Y")+"','indexName':'"+
                   name.upper()+"'}")}
    headers={"Content-Type":"application/json; charset=utf-8",
             "Accept":"application/json, text/javascript, */*",
             "Referer":"https://www.niftyindices.com/reports/historical-data",
             "User-Agent":"Mozilla/5.0"}
    url="https://www.niftyindices.com/Backpage.aspx/getHistoricaldatatabletoString"
    resp=requests.post(url,json=body,headers=headers,timeout=12)
    resp.raise_for_status()
    payload=resp.json()
    if not isinstance(payload,dict):return None
    raw=payload.get("d")
    if raw in (None,"false",""):return None
    if isinstance(raw,str):
        raw=json.loads(raw)
    if not isinstance(raw,list) or len(raw)<35:return None
    frame=pd.DataFrame(raw)
    if "HistoricalDate" not in frame:return None
    frame.index=pd.to_datetime(frame["HistoricalDate"],format="%d %b %Y",errors="coerce")
    for key in ("OPEN","HIGH","LOW","CLOSE"):
        if key not in frame:return None
        frame[key]=pd.to_numeric(frame[key].astype(str).str.replace(",","",regex=False).replace("-",pd.NA),errors="coerce")
    frame=frame[["OPEN","HIGH","LOW","CLOSE"]].rename(columns=str.title)
    frame=frame.dropna(subset=["Close"])
    if frame.empty:return None
    # Historical back-computed index levels sometimes lack intraday OHLC.
    for col in ("Open","High","Low"):
        frame[col]=frame[col].fillna(frame["Close"])
    frame["Volume"]=0
    frame=frame.loc[~frame.index.isna()].sort_index()
    frame=frame[~frame.index.duplicated(keep="last")]
    return frame if len(frame)>=35 else None


def official_nse_index(name, long_names=None):
    """Try NSE's true historical price index OHLC; never substitute an ETF."""
    if not name.upper().startswith("NIFTY"):return None
    finish=date.today()
    start=finish-timedelta(days=350)
    mapping=(long_names or {}).get(name.upper(),name)
    # Different indices have different historical/display aliases.
    possibilities=list(dict.fromkeys([mapping,name]))
    for candidate in possibilities:
        try:
            df=_nse_history_post(candidate,start,finish)
            if df is not None:
                print("Official NSE index OHLC:",name,"mapped as",candidate,len(df),"sessions")
                return df
        except (requests.RequestException,ValueError,TypeError,KeyError) as exc:
            print("NSE index historical issue:",name,str(exc)[:95])
            # A blocked remote endpoint is unlikely to work with another alias.
            if isinstance(exc,requests.RequestException):break
    print("No official history for:",name)
    return None


def official_name_map():
    """NSE-supplied mapping; keep original display names if it is offline."""
    url="https://iislliveblob.niftyindices.com/assets/json/IndexMapping.json"
    try:
        payload=requests.get(url,timeout=10).json()
        if not isinstance(payload,list):return {}
        mapped={}
        for entry in payload:
            if not isinstance(entry,dict):continue
            trading=str(entry.get("Trading_Index_Name") or "").strip()
            long_name=str(entry.get("Index_long_name") or "").strip()
            if trading and long_name:
                mapped[trading.upper()]=long_name
                mapped[long_name.upper()]=long_name
        print("Official index names loaded:",len(mapped))
        return mapped
    except (requests.RequestException,ValueError) as exc:
        print("NSE name mapping unavailable:",str(exc)[:100])
        return {}


def metrics(df):
    if df is None or df.empty:return None
    now=float(df["Close"].iloc[-1])
    latest=df.index[-1]
    out={"cmp":number(now),"date":str(latest.date())}
    for key,delta in (("1m",pd.DateOffset(months=1)),("3m",pd.DateOffset(months=3))):
        earlier=df[df.index<=latest-delta]
        out[key]=number(100*(now/float(earlier["Close"].iloc[-1])-1)) if not earlier.empty else ""
    return out
def chart_link(index,asset):
    return URL+"?index="+quote(index,safe="")+"&asset="+quote(asset,safe="")
def output(book,name,header,rows,signal_col=None):
    tab=ws(book,name,len(header)+1);tab.clear()
    tab.resize(rows=max(150,len(rows)+2),cols=len(header))
    tab.update([header]+rows,range_name="A1:"+chr(64+len(header))+str(len(rows)+1),value_input_option="USER_ENTERED")
    tab.freeze(rows=1,cols=min(3,len(header)))
    tab.format("A1:"+chr(64+len(header))+"1",{
        "backgroundColor":{"red":0.09,"green":0.31,"blue":0.35},
        "textFormat":{"bold":True,"foregroundColor":{"red":1,"green":1,"blue":1}},
        "wrapStrategy":"WRAP"})
    fmt=[]
    for i,row in enumerate(rows,start=2):
        val=row[signal_col] if signal_col is not None else ""
        if val=="YES":bg={"red":0.84,"green":0.96,"blue":0.88}
        elif val=="NO":bg={"red":0.99,"green":0.91,"blue":0.90}
        else:bg={"red":0.94,"green":0.97,"blue":0.98} if i%2 else {"red":1,"green":1,"blue":1}
        fmt.append({"repeatCell":{"range":{"sheetId":tab.id,"startRowIndex":i-1,"endRowIndex":i,
                   "startColumnIndex":0,"endColumnIndex":len(header)},
                   "cell":{"userEnteredFormat":{"backgroundColor":bg}},
                   "fields":"userEnteredFormat.backgroundColor"}})
    for j in range(0,len(fmt),100):book.batch_update({"requests":fmt[j:j+100]})
def main():
    book=connect();universe=source(book)
    all_symbols={"^NSEI"}
    for cat,name,index,pool in universe:
        all_symbols.add(index)
        all_symbols.update(x+".NS" for x in pool)
    print("Downloading",len(all_symbols),"market series")
    series={}
    for sym in sorted(all_symbols):
        series[sym]=download(sym)
    # Multiple index endpoints can be slow, so fetch missing indices in
    # parallel. Avoid inaccurate proxy ETFs or synthetic prices.
    mapping=official_name_map()
    missing={(name,symbol) for _,name,symbol,_ in universe
             if series.get(symbol) is None and name.upper().startswith("NIFTY")}
    if series.get("^NSEI") is None:
        missing.add(("NIFTY 50","^NSEI"))
    if missing:
        print("Checking official NSE price histories:",len(missing))
        with ThreadPoolExecutor(max_workers=5) as pool:
            jobs={pool.submit(official_nse_index,name,mapping):(name,symbol)
                  for name,symbol in missing}
            for future in as_completed(jobs):
                name,symbol=jobs[future]
                try:df=future.result()
                except Exception as exc:
                    print("Index fallback task error:",name,str(exc)[:130])
                    df=None
                if df is not None:series[symbol]=df
    bench=metrics(series.get("^NSEI"))
    if bench is None or bench["1m"]=="" or bench["3m"]=="":
        raise RuntimeError("NIFTY 50 benchmark data missing: cannot label outperform; try another run")
    strength=[];leaders=[];chartdata={};valid=[]
    for category,name,symbol,pool in universe:
        df=series.get(symbol);m=metrics(df)
        if m is None or m["1m"]=="" or m["3m"]=="":
            status="DATA UNAVAILABLE";one=three=cmpv=ex1=ex3="";dt=""
        else:
            status="OK";one,three,cmpv,dt=m["1m"],m["3m"],m["cmp"],m["date"]
            ex1=number(one-bench["1m"]);ex3=number(three-bench["3m"])
            valid.append((name,ex1))
        out1="YES" if status=="OK" and ex1>0 else "NO" if status=="OK" else ""
        out3="YES" if status=="OK" and ex3>0 else "NO" if status=="OK" else ""
        strength.append([0,category,name,symbol,dt,cmpv,one,three,bench["1m"],
                        ex1,out1,ex3,out3,status,
                        '=HYPERLINK("'+chart_link(name,symbol)+'","OPEN INDEX CHART")'])
        chartdata[name]={"name":name,"index":symbol,"assets":[]}
        if df is not None:chartdata[name]["assets"].append(serialize(symbol,df))
        picks=[]
        for stock in pool:
            sm=metrics(series.get(stock+".NS"))
            if sm and sm["3m"]!="" and sm["1m"]!="":
                picks.append((stock,sm))
        picks.sort(key=lambda x:x[1]["3m"],reverse=True)
        for rank,(stock,sm) in enumerate(picks[:3],start=1):
            leaders.append([name,rank,stock,sm["1m"],sm["3m"],three,
                           number(sm["3m"]-three) if three!="" else "",
                           sm["cmp"],sm["date"],
                           '=HYPERLINK("'+chart_link(name,stock+".NS")+'","OPEN STOCK CHART")',
                           "TRACKED CANDIDATES"])
            sdf=series.get(stock+".NS")
            if sdf is not None:chartdata[name]["assets"].append(serialize(stock+".NS",sdf))
        if len(picks)<3:print("Only",len(picks),"tracked leaders for",name)
    strength.sort(key=lambda r:(0 if r[13]=="OK" else 1,-r[9] if isinstance(r[9],(int,float)) else 0,r[2]))
    for i,row in enumerate(strength,start=1):row[0]=i if row[13]=="OK" else ""
    output(book,RESULTS,COLS,strength,signal_col=10)
    output(book,LEADERS,LHEAD,leaders)
    CHART.parent.mkdir(parents=True,exist_ok=True)
    template=Path("scripts/indian_index_chart_template.html").read_text(encoding="utf-8")
    CHART.write_text(template.replace("/*DATA_PAYLOAD*/",json.dumps({"indices":chartdata,"benchmark":bench},separators=(",",":"))),encoding="utf-8")
    print("Done:",len(strength),"indices,",sum(r[13]=="OK" for r in strength),"with index data;",
          len(leaders),"tracked stock leader rows, chart:",CHART)

def serialize(symbol,df):
    df=df.tail(270)
    return {"symbol":symbol,"d":[[str(idx.date()),*map(number,vals)]
                  for idx,vals in zip(df.index,df[["Open","High","Low","Close","Volume"]].itertuples(index=False,name=None))]}

if __name__=="__main__":main()
