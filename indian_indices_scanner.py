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
from nse_sector_archive import load_index_archive, index_from_archive
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
]
HEAD=["Category","Index Name","Yahoo Symbol","Tracked Stock Candidates (comma-separated)","Enabled (YES/NO)"]
COLS=["Rank","Category","Index","Ticker","Price Date","CMP","1M Return %","3M Return %",
      "NIFTY50 1M %","1M Excess %","1M Outperform?","3M Excess %",
      "3M Outperform?","Data Status","Index Chart"]
LHEAD=["Sector Rank","Index","Sector 1M Excess %","Leader Rank","NSE Stock",
       "Stock 1M %","Index 1M %","Stock vs Index 1M %",
       "Stock vs NIFTY50 1M %","Stock 3M %","Index 3M %",
       "Stock vs Index 3M %","Price Date","Stock CMP","Stock Chart","Universe"]
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
    """Keep only sector indices; preserve edited candidate lists within sector rows."""
    tab=ws(book,UNIVERSE,6)
    values=tab.get_all_values()
    meaningful=[row for row in values if any(str(x).strip() for x in row)]
    if not meaningful:
        meaningful=[HEAD]+[[a,b,c,d,"YES"] for a,b,c,d in SEED if a=="Sector"]
    else:
        # Sector list only. Drop broad market, BSE, thematic and strategy rows.
        sector_rows=[]
        for row in meaningful[1:]:
            row=(row+[""]*5)[:5]
            if row[0].strip().upper()=="SECTOR" and row[1].strip() and row[2].strip():
                sector_rows.append(row)
        meaningful=[HEAD]+sector_rows
    # Rewrite editable tab after category cleanup; do not overwrite sector edits.
    tab.clear()
    tab.resize(rows=max(150,len(meaningful)+2),cols=6)
    tab.update(meaningful,range_name="A1:E"+str(len(meaningful)),value_input_option="RAW")
    tab.freeze(rows=1)
    tab.format("A1:E1",{"backgroundColor":{"red":0.10,"green":0.22,"blue":0.32},
          "textFormat":{"bold":True,"foregroundColor":{"red":1,"green":1,"blue":1}}})
    result=[]
    for row in meaningful[1:]:
        row=(row+[""]*5)[:5]
        cat,name,ticker,candidates,enabled=[x.strip() for x in row]
        if enabled.upper() in ("NO","FALSE","0"):continue
        pool=list(dict.fromkeys(x.strip().upper().removesuffix(".NS")
                                 for x in candidates.split(",") if x.strip()))
        result.append((cat,name,ticker,pool))
    if not result:raise ValueError("No enabled Sector indices in Index Universe")
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


def aligned_metrics(df, target_date, start_1m, start_3m, max_lag_days=5):
    """Same benchmark anchor dates for every sector and stock.

    A snapshot must be recent enough on all three dates. We do not use
    a series' independent latest date or an arbitrary distant old price.
    """
    if df is None or df.empty:return None
    prices=df.copy()
    prices.index=pd.to_datetime(prices.index).tz_localize(None).normalize()
    prices=prices[~prices.index.duplicated(keep="last")].sort_index()
    result={}
    for label,dt in (("end",target_date),("1m",start_1m),("3m",start_3m)):
        eligible=prices.loc[prices.index<=dt].dropna(subset=["Close"])
        if eligible.empty:return None
        when=eligible.index[-1]
        if (dt-when).days>max_lag_days:return None
        val=float(eligible["Close"].iloc[-1])
        if not math.isfinite(val) or val<=0:return None
        result[label]=val
        result[label+"_date"]=str(when.date())
    # If the source has too few months of history, it cannot be a 3M leader.
    result["cmp"]=number(result["end"])
    result["date"]=str(target_date.date())
    result["1m"]=number(100*(result["end"]/result["1m"]-1))
    result["3m"]=number(100*(result["end"]/result["3m"]-1))
    return result


def benchmark_dates(df, all_index_series):
    """Select the latest shared index trading date, then benchmark anchors.

    Only include indices with recent usable data. Any genuinely stale index
    will be DATA UNAVAILABLE, rather than making the comparison very old.
    """
    benchmark=df.dropna(subset=["Close"]).sort_index()
    if benchmark.empty:raise RuntimeError("NIFTY50 benchmark missing")
    latest=benchmark.index[-1].normalize()
    recent=[]
    for series in all_index_series:
        if series is None or series.empty:continue
        candidate=series.dropna(subset=["Close"])
        if candidate.empty:continue
        dt=candidate.index[-1].normalize()
        if (latest-dt).days<=5:recent.append(dt)
    end=min(recent) if recent else latest
    if (latest-end).days>5:raise RuntimeError("Indices are too stale for common comparison")
    anchor=benchmark.loc[benchmark.index<=end]
    if anchor.empty:raise RuntimeError("No benchmark close at common date")
    end=anchor.index[-1].normalize()
    starts=[]
    for offset in (pd.DateOffset(months=1),pd.DateOffset(months=3)):
        before=benchmark.loc[benchmark.index<=end-offset]
        if before.empty:raise RuntimeError("Insufficient NIFTY50 history")
        starts.append(before.index[-1].normalize())
    print("COMMON COMPARISON DATES",str(end.date()),str(starts[0].date()),str(starts[1].date()))
    return end,starts[0],starts[1]


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
    # Google Sheets retains existing column formats across clear()/update().
    # Without explicitly resetting I (and its neighboring return columns),
    # a previously applied DATE format displays numeric excess returns as
    # 1900-01-xx dates. These columns are percentage POINTS, not ratios.
    if name==LEADERS:
        tab.format("F2:L"+str(max(150,len(rows)+2)),
                   {"numberFormat":{"type":"NUMBER","pattern":"0.00"}})
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
    # NSE's official all-index daily file contains most sector price indices.
    # Existing downloaded OHLC is cached between runs in the repository.
    missing=[(name,symbol) for _,name,symbol,_ in universe
             if series.get(symbol) is None]
    if missing:
        archive=load_index_archive(days=125)
        covered=0
        for name,symbol in missing:
            recovered=index_from_archive(name,archive)
            if recovered is not None:
                series[symbol]=recovered
                covered+=1
                print("NSE daily snapshot supplied:",name,len(recovered),"sessions")
        print("Recovered sector index histories:",covered,"of",len(missing))
    # Do not use synthetic prices, ETFs, or incomplete snippets as index data.
    # Missing indices are explicitly DATA UNAVAILABLE.
    reference=series.get("^NSEI")
    if reference is None:
        raise RuntimeError("NIFTY50 benchmark data missing")
    end_date, one_month, three_month=benchmark_dates(reference,
        [series.get(symbol) for _,_,symbol,_ in universe])
    bench=aligned_metrics(reference,end_date,one_month,three_month)
    if bench is None:
        raise RuntimeError("NIFTY50 common-date return unavailable")

    strength=[];leaders=[];chartdata={};qualified_sectors=[]
    for category,name,symbol,pool in universe:
        df=series.get(symbol)
        m=aligned_metrics(df,end_date,one_month,three_month)
        if m is None:
            status="DATA UNAVAILABLE";one=three=cmpv=ex1=ex3="";dt=""
            print("Common-date OHLC missing/stale:",name)
        else:
            status="OK"
            one,three,cmpv,dt=m["1m"],m["3m"],m["cmp"],m["date"]
            ex1=number(one-bench["1m"]);ex3=number(three-bench["3m"])
            if ex1>0:qualified_sectors.append(name)
        out1="YES" if status=="OK" and ex1>0 else "NO" if status=="OK" else ""
        out3="YES" if status=="OK" and ex3>0 else "NO" if status=="OK" else ""
        strength.append([0,category,name,symbol,dt,cmpv,one,three,bench["1m"],
                         ex1,out1,ex3,out3,status,
                         '=HYPERLINK("'+chart_link(name,symbol)+'","OPEN INDEX CHART")'])
        # Index and qualifying stock leaders remain available in chart menu.
        chartdata[name]={"name":name,"index":symbol,"assets":[]}
        if df is not None:chartdata[name]["assets"].append(serialize(symbol,df))
    strength.sort(key=lambda row:(0 if row[13]=="OK" else 1,
                    -row[9] if isinstance(row[9],(int,float)) else 0,row[2]))
    rank_lookup={}
    for i,row in enumerate(strength,start=1):
        row[0]=i if row[13]=="OK" else ""
        if row[13]=="OK":rank_lookup[row[2]]=i

    # Leaders only in 1M outperforming sectors, using exactly the same
    # benchmark start/end dates as Index Strength.
    for category,name,symbol,pool in universe:
        row=next(r for r in strength if r[2]==name)
        if row[10]!="YES":continue
        index_1m,index_3m=row[6],row[7]
        candidates=[]
        for stock in pool:
            ticker=stock+".NS"
            sm=aligned_metrics(series.get(ticker),end_date,one_month,three_month)
            if sm is None:continue
            excess_index=number(sm["1m"]-index_1m)
            excess_nifty=number(sm["1m"]-bench["1m"])
            # A leader must outperform BOTH its index and NIFTY50 in 1M.
            if excess_index<=0 or excess_nifty<=0:continue
            candidates.append((stock,sm,excess_index,excess_nifty))
        candidates.sort(key=lambda x:(-x[2],-x[1]["1m"],x[0]))
        for rank,(stock,sm,excess_index,excess_nifty) in enumerate(candidates[:3],start=1):
            leaders.append([rank_lookup[name],name,row[9],rank,stock,
                            sm["1m"],index_1m,excess_index,excess_nifty,
                            sm["3m"],index_3m,number(sm["3m"]-index_3m),
                            sm["date"],sm["cmp"],
                            '=HYPERLINK("'+chart_link(name,stock+".NS")+'","OPEN STOCK CHART")',
                            "TRACKED CANDIDATES ONLY"])
            sdf=series.get(stock+".NS")
            if sdf is not None:chartdata[name]["assets"].append(serialize(stock+".NS",sdf))
        print("Outperforming sector",name,": qualifying tracked leaders",len(candidates),
              "shown",min(3,len(candidates)))
    leaders.sort(key=lambda row:(row[0],row[3]))
    output(book,RESULTS,COLS,strength,signal_col=10)
    output(book,LEADERS,LHEAD,leaders)
    CHART.parent.mkdir(parents=True,exist_ok=True)
    template=Path("scripts/indian_index_chart_template.html").read_text(encoding="utf-8")
    CHART.write_text(template.replace("/*DATA_PAYLOAD*/",json.dumps({"indices":chartdata,"benchmark":bench},separators=(",",":"))),encoding="utf-8")
    print("Done:",len(strength),"indices,",sum(r[13]=="OK" for r in strength),"with index data;",
          len(leaders),"qualifying outperforming stock leader rows, chart:",CHART)

def serialize(symbol,df):
    df=df.tail(270)
    return {"symbol":symbol,"d":[[str(idx.date()),*map(number,vals)]
                  for idx,vals in zip(df.index,df[["Open","High","Low","Close","Volume"]].itertuples(index=False,name=None))]}

if __name__=="__main__":main()
