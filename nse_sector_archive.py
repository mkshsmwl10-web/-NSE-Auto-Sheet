"""NSE daily all-index close archive; price-index OHLC only.

Reads exchange-published ind_close_all_DDMMYYYY.csv files. Never creates
synthetic levels or proxies. Stores successfully downloaded snapshots in a
versioned repository CSV and remembers checked dates for efficient refresh.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
import io
import json
import math
import re
import requests
import pandas as pd

CACHE=Path("data/sector_index_ohlc.csv")
CHECKS=Path("data/sector_index_checked.json")
COLUMNS=["Date","Index Name","Open","High","Low","Close","Volume"]
ARCHIVE="https://nsearchives.nseindia.com/content/indices/ind_close_all_{}.csv"
ALT="https://archives.nseindia.com/content/indices/ind_close_all_{}.csv"
HEADERS={
  "User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36",
  "Accept":"text/csv,text/plain,application/csv,*/*",
  "Referer":"https://www.nseindia.com/all-reports",
}
ALIASES={
    "NIFTYFINANCIALSERVICES":["NIFTYFINANCIALSERVICES","NIFTYFINSERVICE"],
    "NIFTYPRIVATEBANK":["NIFTYPRIVATEBANK","NIFTYPVTBANK"],
    "NIFTYCONSUMERDURABLES":["NIFTYCONSUMERDURABLES","NIFTYCONSRDURBL"],
    "NIFTYINFRA":["NIFTYINFRA","NIFTYINFRASTRUCTURE"],
    "NIFTYPSE":["NIFTYPSE"],
    "NIFTYHEALTHCARE":["NIFTYHEALTHCARE","NIFTYHEALTHCAREINDEX"],
    "NIFTYOILGAS":["NIFTYOILGAS"],
}
def norm(s):
    return re.sub(r"[^A-Z0-9]","",str(s).upper())

def numeric(s):
    v=str(s).replace(",","").strip()
    try:
        val=float(v)
        return val if math.isfinite(val) else float("nan")
    except (ValueError,TypeError):return float("nan")

def parse(content,day):
    if len(content)<200 or len(content)>2500000:return []
    try:frame=pd.read_csv(io.BytesIO(content),on_bad_lines="skip")
    except (ValueError,pd.errors.ParserError,UnicodeError):return []
    frame.columns=[str(c).strip().lstrip("\ufeff") for c in frame.columns]
    required={"Index Name"}
    if not required.issubset(frame.columns):return []
    names={
      "Open":("Open Index Value","Open"),
      "High":("High Index Value","High"),
      "Low":("Low Index Value","Low"),
      "Close":("Closing Index Value","Closing","Close"),
      "Volume":("Volume","Volume (Shares)"),
    }
    cols={}
    for desired,candidates in names.items():
        cols[desired]=next((c for c in candidates if c in frame.columns),None)
    if cols["Close"] is None:return []
    if "Index Date" in frame.columns:
        dates=pd.to_datetime(frame["Index Date"],dayfirst=True,errors="coerce")
        # Reject unrelated/accidentally cached daily responses
        if dates.notna().any() and not (dates.dt.date==day).any():return []
    entries=[]
    for _,r in frame.iterrows():
        name=str(r.get("Index Name","")).strip()
        if not name or name.lower()=="nan":continue
        c=numeric(r.get(cols["Close"])) if cols["Close"] else float("nan")
        if not math.isfinite(c) or c<=0:continue
        o=numeric(r.get(cols["Open"])) if cols["Open"] else float("nan")
        h=numeric(r.get(cols["High"])) if cols["High"] else float("nan")
        l=numeric(r.get(cols["Low"])) if cols["Low"] else float("nan")
        v=numeric(r.get(cols["Volume"])) if cols["Volume"] else float("nan")
        # Missing OHLC does not become fake intraday candles: use only
        # complete OHLC rows for charts.
        if any(not math.isfinite(p) or p<=0 for p in (o,h,l)):continue
        if h+0.01<max(o,c,l) or l-0.01>min(o,c,h):continue
        entries.append([str(day),name,o,h,l,c,v if math.isfinite(v) else 0])
    return entries

def fetch_day(day):
    stamp=day.strftime("%d%m%Y")
    for root in (ARCHIVE,ALT):
        try:
            response=requests.get(root.format(stamp),headers=HEADERS,timeout=13)
            if response.status_code==404:continue
            if response.status_code!=200:continue
            rows=parse(response.content,day)
            if rows:return day,rows,"OK"
        except requests.RequestException:continue
    return day,[],"UNAVAILABLE"

def load_index_archive(days=120):
    today=date.today()
    since=today-timedelta(days=days)
    if CACHE.exists():
        try:
            cache=pd.read_csv(CACHE,dtype={"Index Name":str,"Date":str})
            if not set(COLUMNS).issubset(cache.columns):raise ValueError("invalid cache")
            cache=cache[COLUMNS]
            cache=cache.loc[cache["Date"]>=str(since)].copy()
        except (ValueError,OSError,pd.errors.ParserError):
            cache=pd.DataFrame(columns=COLUMNS)
    else:cache=pd.DataFrame(columns=COLUMNS)
    try:checked=json.loads(CHECKS.read_text(encoding="utf-8"))
    except (ValueError,OSError):checked={}
    # Recheck unavailable dates later (temporary blocks are common);
    # successful snapshots and confirmed absent holidays can be skipped.
    present=set(cache["Date"].dropna().astype(str).tolist())
    candidates=[since+timedelta(days=i) for i in range((today-since).days+1)]
    weekdays=[d for d in candidates if d.weekday()<5]
    # Always retry absent historical trading days on later runs. A network
    # failure must never become a permanent "holiday" marker.
    missing=[d for d in weekdays if str(d) not in present]
    # Bound each run; all requested days fit the normal 125-day lookback.
    if len(missing)>95:missing=missing[-95:]
    print("NSE daily archive cache:",len(present),"days; requests:",len(missing))
    incoming=[]
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures=[executor.submit(fetch_day,d) for d in missing]
        for f in as_completed(futures):
            d,rows,status=f.result()
            if rows:
                incoming.extend(rows)
                checked[str(d)]="OK"
            elif d<today-timedelta(days=7):checked[str(d)]="UNAVAILABLE"
    if incoming:
        cache=pd.concat([cache,pd.DataFrame(incoming,columns=COLUMNS)],ignore_index=True)
        cache=cache.drop_duplicates(["Date","Index Name"],keep="last")
        cache=cache.sort_values(["Date","Index Name"])
        CACHE.parent.mkdir(parents=True,exist_ok=True)
        cache.to_csv(CACHE,index=False)
    CHECKS.parent.mkdir(parents=True,exist_ok=True)
    CHECKS.write_text(json.dumps({k:v for k,v in checked.items() if k>=str(since)},sort_keys=True),encoding="utf-8")
    print("NSE daily archive new rows:",len(incoming),"total:",len(cache))
    return cache

def index_from_archive(name,archive):
    if archive is None or archive.empty:return None
    candidates=ALIASES.get(norm(name),[norm(name)])
    names=archive["Index Name"].astype(str).map(norm)
    rows=archive.loc[names.isin(candidates)].copy()
    if len(rows)<35:return None
    rows.index=pd.to_datetime(rows["Date"],errors="coerce")
    rows=rows.loc[~rows.index.isna()].sort_index()
    rows=rows.loc[~rows.index.duplicated(keep="last")]
    cols=["Open","High","Low","Close","Volume"]
    out=rows[cols].apply(pd.to_numeric,errors="coerce").dropna(subset=["Open","High","Low","Close"])
    if len(out)<35:return None
    return out
