import os
import json
import time
from datetime import datetime, time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E")
INPUT_SHEET = os.environ.get("INPUT_SHEET", "NIFTY200")
OUTPUT_SHEET = os.environ.get("TREND_SHEET", "Trend Scanner")
CHART_OUTPUT_DIR = Path(os.environ.get("TREND_CHART_OUTPUT_DIR", "docs/charts"))
CHART_BASE_URL = os.environ.get(
    "TREND_CHART_BASE_URL",
    "https://mkshsmwl10-web.github.io/-NSE-Auto-Sheet/docs/charts",
)
DOWNLOAD_PERIOD = "5y"
IST = ZoneInfo("Asia/Kolkata")
MARKET_SETTLE_TIME = dt_time(15, 35)
CHART_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def connect_google_sheet():
    raw = os.environ.get("GCP_CREDENTIALS")
    if not raw:
        raise RuntimeError("GCP_CREDENTIALS secret not found.")
    info = json.loads(raw)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)


def clean_symbol(value):
    symbol = str(value or "").strip().upper()
    return symbol[:-3] if symbol.endswith(".NS") else symbol


def clean_dataframe(df):
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    for col in ["Open", "High", "Low", "Close"]:
        if col not in df.columns:
            return pd.DataFrame()
    if "Volume" not in df.columns:
        df["Volume"] = 0

    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert(IST).tz_localize(None)
    df.index = idx
    return (
        df.sort_index()
        .loc[~df.index.duplicated(keep="last")]
        .dropna(subset=["Open", "High", "Low", "Close"])
    )


def download_data(yahoo_symbol):
    try:
        df = yf.download(
            yahoo_symbol,
            period=DOWNLOAD_PERIOD,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        return clean_dataframe(df)
    except Exception as exc:
        print(f"Download error {yahoo_symbol}: {exc}")
        return pd.DataFrame()


def get_completed_daily(df):
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    now = datetime.now(IST)
    if out.index[-1].date() == now.date() and now.time() < MARKET_SETTLE_TIME:
        out = out.iloc[:-1]
    return out


def make_weekly(daily):
    if daily is None or daily.empty:
        return pd.DataFrame()
    weekly = daily.resample("W-FRI").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    ).dropna(subset=["Open", "High", "Low", "Close"])
    # Mon-Thu produces a future Friday label: remove that incomplete week.
    return weekly[weekly.index <= daily.index[-1].normalize()]


def make_monthly(daily):
    if daily is None or daily.empty:
        return pd.DataFrame()
    work = daily.copy()
    monthly = work.groupby(work.index.to_period("M")).agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    )
    monthly.index = monthly.index.to_timestamp(how="end").normalize()
    current_month = pd.Timestamp(datetime.now(IST).replace(tzinfo=None)).to_period("M")
    return monthly[monthly.index.to_period("M") < current_month]


def calculate_dynamic_trend(df):
    """Same-trend colour shifts reference; opposite colour flips only on reference break."""
    if df is None or df.empty: return "NO DATA", None, None
    w=df.dropna(subset=["Open","Close"]).copy()
    if w.empty: return "NO DATA", None, None
    s=0
    while s<len(w) and float(w.iloc[s]["Close"])==float(w.iloc[s]["Open"]): s+=1
    if s>=len(w): return "NO DATA", None, None
    o=float(w.iloc[s]["Open"]); c=float(w.iloc[s]["Close"])
    trend="POSITIVE" if c>o else "NEGATIVE"; ref=o; changed=w.index[s]
    for i in range(s+1,len(w)):
        o=float(w.iloc[i]["Open"]); c=float(w.iloc[i]["Close"])
        green=c>o; red=c<o
        if trend=="POSITIVE":
            if green: ref=o
            elif red and c<ref: trend="NEGATIVE"; ref=o; changed=w.index[i]
        else:
            if red: ref=o
            elif green and c>ref: trend="POSITIVE"; ref=o; changed=w.index[i]
    return trend, round(ref,2), changed


def read_nifty200(book):
    ws = book.worksheet(INPUT_SHEET)
    values = ws.get_all_values()
    if not values:
        raise RuntimeError("NIFTY200 sheet is empty.")

    headers = [str(x).strip() for x in values[0]]
    rows = values[1:]
    symbol_names = ["NSE Code", "NSE CODE", "Symbol", "SYMBOL", "NSECode", "Code"]
    name_names = ["Stock Name", "STOCK NAME", "Name", "NAME", "Company", "Company Name"]

    symbol_index = next((headers.index(x) for x in symbol_names if x in headers), 0)
    name_index = next((headers.index(x) for x in name_names if x in headers), None)

    stocks, seen = [], set()
    for row in rows:
        if len(row) <= symbol_index:
            continue
        symbol = clean_symbol(row[symbol_index])
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        stock_name = (
            str(row[name_index]).strip()
            if name_index is not None and len(row) > name_index and str(row[name_index]).strip()
            else symbol
        )
        stocks.append({"name": stock_name, "code": symbol, "yahoo": f"{symbol}.NS"})
    return stocks


def chart_bars(df, max_bars):
    if df is None or df.empty:
        return []
    return [
        {
            "time": idx.strftime("%Y-%m-%d"),
            "open": round(float(row["Open"]), 2),
            "high": round(float(row["High"]), 2),
            "low": round(float(row["Low"]), 2),
            "close": round(float(row["Close"]), 2),
        }
        for idx, row in df.tail(max_bars).iterrows()
    ]


HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__PAGE_TITLE__</title>
<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
<style>
* { box-sizing:border-box; }
body { margin:0; background:#0f172a; color:#e5e7eb; font-family:Arial,Helvetica,sans-serif; }
.header { padding:18px 22px; background:#111827; border-bottom:1px solid #334155; }
.title { font-size:24px; font-weight:700; }
.subtitle { margin-top:6px; color:#94a3b8; }
.status-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; padding:14px 20px; }
.status { padding:12px; border-radius:8px; text-align:center; font-weight:700; }
.positive { background:#14532d; color:#dcfce7; }
.negative { background:#7f1d1d; color:#fee2e2; }
.nodata { background:#374151; color:#f8fafc; }
.toolbar { padding:8px 20px 14px; }
button { border:1px solid #475569; background:#1e293b; color:white; padding:9px 17px; margin-right:7px; border-radius:6px; cursor:pointer; font-weight:700; }
button.active { background:#2563eb; }
.info { padding:0 20px 10px; color:#cbd5e1; }
.ohlc { padding:0 20px 10px; min-height:24px; color:#e2e8f0; font-weight:700; }
.ohlc span { margin-right:14px; }
.toolbar button.tool-active { background:#7c3aed; border-color:#a78bfa; }
#chartWrap{position:relative;width:100%;height:650px} #chart{position:absolute;inset:0}
#overlay{position:absolute;inset:0;width:100%;height:100%;z-index:5;pointer-events:none;overflow:visible}
@media(max-width:700px) {
  .status-grid { grid-template-columns:1fr; }
  #chartWrap { height:520px; }
}
</style>
</head>
<body>
<div class="header">
  <div class="title" id="title"></div>
  <div class="subtitle" id="subtitle"></div>
</div>
<div class="status-grid">
  <div id="dailyStatus" class="status">Daily</div>
  <div id="weeklyStatus" class="status">Weekly</div>
  <div id="monthlyStatus" class="status">Monthly</div>
</div>
<div class="toolbar">
  <button id="Daily" onclick="renderTF('Daily')">1D</button>
  <button id="Weekly" onclick="renderTF('Weekly')">1W</button>
  <button id="Monthly" onclick="renderTF('Monthly')">1M</button>
  <button onclick="zoomBy(0.75)">+</button><button onclick="zoomBy(1.35)">−</button>
  <button onclick="fitChart()">Fit</button><button onclick="resetChart()">Reset</button>
  <button id="toolH" onclick="drawH()">H-Line</button><button id="toolV" onclick="drawV()">V-Line</button>
  <button id="toolT" onclick="drawTrend()">Trend Line</button><button id="toolR" onclick="drawRay()">Ray</button>
  <button onclick="clearDrawings()">Clear Drawings</button>
</div>
<div class="info" id="info"></div><div class="ohlc" id="ohlc">Move mouse over a candle to see OHLC</div>
<div id="chartWrap"><div id="chart"></div><svg id="overlay" xmlns="http://www.w3.org/2000/svg"></svg></div>
<script>
const DATA = __DATA_JSON__;
let chart = null;
let candleSeries=null, currentTF="Daily", drawings=[], mode=null, firstPoint=null;
const overlay=document.getElementById("overlay");
const ohlcBox=document.getElementById("ohlc");

document.getElementById("title").textContent = DATA.name + " (" + DATA.code + ")";
document.getElementById("subtitle").textContent = "CMP: " + DATA.cmp;

function statusClass(trend) {
  if (trend === "POSITIVE") return "status positive";
  if (trend === "NEGATIVE") return "status negative";
  return "status nodata";
}

function setupStatuses() {
  [["dailyStatus","Daily"],["weeklyStatus","Weekly"],["monthlyStatus","Monthly"]].forEach(pair => {
    const el = document.getElementById(pair[0]);
    const tf = pair[1];
    el.className = statusClass(DATA[tf].trend);
    el.innerHTML = tf + "<br>" + DATA[tf].trend;
  });
}

function renderTF(tf) {
  currentTF=tf; firstPoint=null; mode=null; overlay.style.pointerEvents="none"; redraw();
  document.querySelectorAll(".toolbar button").forEach(b => b.classList.remove("active"));
  const btn = document.getElementById(tf);
  if (btn) btn.classList.add("active");

  const holder = document.getElementById("chart");
  holder.innerHTML = "";
  const item = DATA[tf];

  document.getElementById("info").innerHTML =
    "<b>" + tf + " Trend:</b> " + item.trend +
    " &nbsp;&nbsp; <b>Active Reversal Open:</b> " +
    (item.reference === null ? "-" : item.reference);

  chart = LightweightCharts.createChart(holder, {
    width:holder.clientWidth,
    height:holder.clientHeight,
    layout:{ background:{ color:"#0f172a" }, textColor:"#cbd5e1" },
    grid:{ vertLines:{ color:"#1e293b" }, horzLines:{ color:"#1e293b" } },
    rightPriceScale:{ borderColor:"#475569" },
    timeScale:{ borderColor:"#475569", timeVisible:true }
  });

  candleSeries = chart.addCandlestickSeries({
    upColor:"#22c55e",
    downColor:"#ef4444",
    borderVisible:false,
    wickUpColor:"#22c55e",
    wickDownColor:"#ef4444"
  });

  candleSeries.setData(item.bars);
  setupCrosshairOHLC();

  if (item.reference !== null) {
    candleSeries.createPriceLine({
      price:item.reference,
      color:"#f59e0b",
      lineWidth:2,
      lineStyle:2,
      axisLabelVisible:true,
      title:"Reference Open"
    });
  }

  chart.timeScale().fitContent();
}

function fitChart(){if(chart)chart.timeScale().fitContent();}
function zoomBy(f){
  if(!chart)return;
  const t=chart.timeScale(), r=t.getVisibleLogicalRange();
  if(!r)return;
  const m=(r.from+r.to)/2, h=(r.to-r.from)*f/2;
  t.setVisibleLogicalRange({from:m-h,to:m+h});
}
function fitChart(){ if(chart) chart.timeScale().fitContent(); }
function resetChart(){ fitChart(); clearDrawings(); }

function setMode(m){
  mode=(mode===m?null:m);
  firstPoint=null;
  overlay.style.pointerEvents=mode?"auto":"none";
  document.querySelectorAll(".toolbar button").forEach(b=>b.classList.remove("tool-active"));
  const map={h:"toolH",v:"toolV",t:"toolT",r:"toolR"};
  if(mode && map[mode]) document.getElementById(map[mode]).classList.add("tool-active");
}
function drawH(){setMode("h")}
function drawV(){setMode("v")}
function drawTrend(){setMode("t")}
function drawRay(){setMode("r")}

function clearDrawings(){
  drawings=[];
  firstPoint=null;
  redraw();
}
function point(e){
  const r=overlay.getBoundingClientRect();
  return {x:e.clientX-r.left,y:e.clientY-r.top};
}
function svgLine(x1,y1,x2,y2){
  const n=document.createElementNS("http://www.w3.org/2000/svg","line");
  n.setAttribute("x1",x1); n.setAttribute("y1",y1);
  n.setAttribute("x2",x2); n.setAttribute("y2",y2);
  n.setAttribute("stroke","#f59e0b"); n.setAttribute("stroke-width","2");
  overlay.appendChild(n);
}
function redraw(){
  while(overlay.firstChild) overlay.removeChild(overlay.firstChild);
  const r=overlay.getBoundingClientRect(), w=r.width, h=r.height;
  drawings.filter(d=>d.tf===currentTF).forEach(d=>{
    if(d.k==="h") svgLine(0,d.a.y,w,d.a.y);
    else if(d.k==="v") svgLine(d.a.x,0,d.a.x,h);
    else if(d.k==="t") svgLine(d.a.x,d.a.y,d.b.x,d.b.y);
    else if(d.k==="r"){
      const dx=d.b.x-d.a.x, dy=d.b.y-d.a.y;
      if(Math.abs(dx)<0.001) svgLine(d.a.x,d.a.y,d.a.x,dy>=0?h:0);
      else{
        const tx=dx>=0?w:0, z=(tx-d.a.x)/dx;
        svgLine(d.a.x,d.a.y,tx,d.a.y+z*dy);
      }
    }
  });
}
overlay.addEventListener("click",e=>{
  if(!mode)return;
  const p=point(e);
  if(mode==="h"||mode==="v"){
    drawings.push({tf:currentTF,k:mode,a:p});
    redraw();
    setMode(null);
    return;
  }
  if(!firstPoint) firstPoint=p;
  else{
    drawings.push({tf:currentTF,k:mode,a:firstPoint,b:p});
    firstPoint=null;
    redraw();
    setMode(null);
  }
});

function setupCrosshairOHLC(){
  if(!chart || !candleSeries)return;
  chart.subscribeCrosshairMove(param=>{
    if(!param || !param.time){
      ohlcBox.textContent="Move mouse over a candle to see OHLC";
      return;
    }
    const d=param.seriesData.get(candleSeries);
    if(!d || d.open===undefined)return;
    const date=typeof param.time==="string"?param.time:
      (param.time.year+"-"+String(param.time.month).padStart(2,"0")+"-"+String(param.time.day).padStart(2,"0"));
    ohlcBox.innerHTML=
      "<span>"+date+"</span>"+
      "<span>O "+Number(d.open).toFixed(2)+"</span>"+
      "<span>H "+Number(d.high).toFixed(2)+"</span>"+
      "<span>L "+Number(d.low).toFixed(2)+"</span>"+
      "<span>C "+Number(d.close).toFixed(2)+"</span>";
  });
}

setupStatuses();
try {
  renderTF("Daily");
} catch (err) {
  document.getElementById("chart").innerHTML =
    '<div style="padding:24px;color:#fecaca;font-weight:700;">Chart error: ' +
    String(err) + '</div>';
  console.error(err);
}

window.addEventListener("resize", () => {
  if (!chart) return;
  const holder = document.getElementById("chart");
  chart.applyOptions({ width:holder.clientWidth });
  redraw();
});
</script>
</body>
</html>
"""


def generate_chart(code, stock_name, cmp_price, daily, weekly, monthly, daily_info, weekly_info, monthly_info):
    safe_code = code.replace("^", "").replace("/", "-").replace(":", "-")
    filename = f"{safe_code}-trend.html"
    filepath = CHART_OUTPUT_DIR / filename
    chart_url = f"{CHART_BASE_URL}/{filename}?v=10"

    payload = {
        "name": stock_name,
        "code": code,
        "cmp": cmp_price,
        "Daily": {"trend": daily_info[0], "reference": daily_info[1], "bars": chart_bars(daily, 180)},
        "Weekly": {"trend": weekly_info[0], "reference": weekly_info[1], "bars": chart_bars(weekly, 120)},
        "Monthly": {"trend": monthly_info[0], "reference": monthly_info[1], "bars": chart_bars(monthly, 60)},
    }

    page = HTML_TEMPLATE.replace("__PAGE_TITLE__", f"{stock_name} Trend Chart")
    page = page.replace("__DATA_JSON__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
    filepath.write_text(page, encoding="utf-8")
    return chart_url


def scan_stock(stock):
    df = download_data(stock["yahoo"])
    if df.empty:
        return None

    daily = get_completed_daily(df)
    if daily.empty:
        return None

    weekly = make_weekly(daily)
    monthly = make_monthly(daily)

    # CMP can use latest Yahoo daily value; trend itself uses completed candles only.
    cmp_price = round(float(df.iloc[-1]["Close"]), 2)

    daily_info = calculate_dynamic_trend(daily)
    weekly_info = calculate_dynamic_trend(weekly)
    monthly_info = calculate_dynamic_trend(monthly)

    # Generate dedicated trend chart for every instrument, including NIFTY 50 SPOT.
    chart_url = generate_chart(
        stock["code"], stock["name"], cmp_price,
        daily, weekly, monthly,
        daily_info, weekly_info, monthly_info,
    )

    return {
        "name": stock["name"],
        "code": stock["code"],
        "cmp": cmp_price,
        "daily": daily_info[0],
        "weekly": weekly_info[0],
        "monthly": monthly_info[0],
        "chart": chart_url,
    }


def write_sheet(book, results):
    try:
        ws = book.worksheet(OUTPUT_SHEET)
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(title=OUTPUT_SHEET, rows=500, cols=10)

    ws.clear()

    headers = ["Stock Name", "NSE Code", "CMP", "Daily Trend", "Weekly Trend", "Monthly Trend", "Chart"]
    values = [headers]

    for r in results:
        values.append([
            r["name"], r["code"], r["cmp"], r["daily"], r["weekly"], r["monthly"],
            "OPEN CHART",
        ])

    ws.update(
        range_name=f"A1:G{len(values)}",
        values=values,
        value_input_option="USER_ENTERED",
    )
    ws.freeze(rows=1, cols=1)

    ws.format("A1:G1", {
        "backgroundColor":{"red":0.10,"green":0.18,"blue":0.32},
        "textFormat":{
            "foregroundColor":{"red":1,"green":1,"blue":1},
            "bold":True,
            "fontSize":11,
        },
        "horizontalAlignment":"CENTER",
        "verticalAlignment":"MIDDLE",
    })

    if len(values) > 1:
        ws.format(f"A2:G{len(values)}", {"verticalAlignment":"MIDDLE"})
        ws.format(f"B2:G{len(values)}", {"horizontalAlignment":"CENTER"})
        ws.format("A2:G2", {
            "backgroundColor":{"red":0.88,"green":0.93,"blue":1.0},
            "textFormat":{"bold":True},
        })
        ws.format(f"G2:G{len(values)}", {
            "textFormat":{
                "bold":True,
                "foregroundColor":{"red":0.05,"green":0.30,"blue":0.75},
            },
            "horizontalAlignment":"CENTER",
        })

    sheet_id = ws.id
    requests = []

    # Clear existing conditional-format rules so repeated runs stay clean.
    try:
        meta = book.fetch_sheet_metadata()
        target = next(s for s in meta["sheets"] if s["properties"]["sheetId"] == sheet_id)
        rule_count = len(target.get("conditionalFormats", []))
        for index in reversed(range(rule_count)):
            requests.append({
                "deleteConditionalFormatRule":{
                    "sheetId":sheet_id,
                    "index":index,
                }
            })
    except Exception as exc:
        print(f"Conditional-format cleanup skipped: {exc}")

    for col_index in [3, 4, 5]:
        requests.append({
            "addConditionalFormatRule":{
                "rule":{
                    "ranges":[{
                        "sheetId":sheet_id,
                        "startRowIndex":1,
                        "startColumnIndex":col_index,
                        "endColumnIndex":col_index+1,
                    }],
                    "booleanRule":{
                        "condition":{"type":"TEXT_EQ","values":[{"userEnteredValue":"POSITIVE"}]},
                        "format":{
                            "backgroundColor":{"red":0.82,"green":0.95,"blue":0.84},
                            "textFormat":{
                                "foregroundColor":{"red":0.05,"green":0.40,"blue":0.16},
                                "bold":True,
                            },
                        },
                    },
                },
                "index":0,
            }
        })
        requests.append({
            "addConditionalFormatRule":{
                "rule":{
                    "ranges":[{
                        "sheetId":sheet_id,
                        "startRowIndex":1,
                        "startColumnIndex":col_index,
                        "endColumnIndex":col_index+1,
                    }],
                    "booleanRule":{
                        "condition":{"type":"TEXT_EQ","values":[{"userEnteredValue":"NEGATIVE"}]},
                        "format":{
                            "backgroundColor":{"red":1.0,"green":0.85,"blue":0.85},
                            "textFormat":{
                                "foregroundColor":{"red":0.65,"green":0.05,"blue":0.05},
                                "bold":True,
                            },
                        },
                    },
                },
                "index":0,
            }
        })

    widths = {0:190, 1:110, 2:100, 3:120, 4:120, 5:130, 6:130}
    for col, pixels in widths.items():
        requests.append({
            "updateDimensionProperties":{
                "range":{
                    "sheetId":sheet_id,
                    "dimension":"COLUMNS",
                    "startIndex":col,
                    "endIndex":col+1,
                },
                "properties":{"pixelSize":pixels},
                "fields":"pixelSize",
            }
        })

    if requests:
        book.batch_update({"requests":requests})

    # TRUE CLICKABLE CHART LINKS
    # Same Google Sheets rich-text method used by the working Final List.
    try:
        rich_link_requests = []

        for row_index, row in enumerate(results, start=2):
            chart_url = str(row.get("chart", "") or "").strip()

            if not chart_url.startswith(("http://", "https://")):
                continue

            rich_link_requests.append({
                "updateCells": {
                    "range": {
                        "sheetId": ws.id,
                        "startRowIndex": row_index - 1,
                        "endRowIndex": row_index,
                        "startColumnIndex": 6,
                        "endColumnIndex": 7,
                    },
                    "rows": [{
                        "values": [{
                            "userEnteredValue": {
                                "stringValue": "OPEN CHART"
                            },
                            "textFormatRuns": [{
                                "startIndex": 0,
                                "format": {
                                    "link": {"uri": chart_url},
                                    "underline": True,
                                },
                            }],
                        }]
                    }],
                    "fields": "userEnteredValue,textFormatRuns",
                }
            })

        for batch_start in range(0, len(rich_link_requests), 100):
            book.batch_update({
                "requests": rich_link_requests[
                    batch_start:batch_start + 100
                ]
            })

        print("Clickable rich-text chart links applied:", len(rich_link_requests))

    except Exception as exc:
        print("WARNING: Rich-text chart link formatting failed:", exc)


def main():
    print("=" * 72)
    print("NIFTY SPOT + NIFTY200 DYNAMIC TREND SCANNER")
    print("=" * 72)

    book = connect_google_sheet()
    stocks = read_nifty200(book)

    instruments = [
        {"name":"NIFTY 50 SPOT", "code":"^NSEI", "yahoo":"^NSEI"}
    ] + stocks

    print(f"Total instruments: {len(instruments)}")
    results = []

    for i, stock in enumerate(instruments, start=1):
        print(f"[{i}/{len(instruments)}] {stock['code']}")
        try:
            result = scan_stock(stock)
            if result:
                results.append(result)
                print(f"  D={result['daily']} | W={result['weekly']} | M={result['monthly']}")
            else:
                print("  NO DATA")
        except Exception as exc:
            print(f"  ERROR: {exc}")
        time.sleep(0.10)

    write_sheet(book, results)

    print("=" * 72)
    print(f"Completed: {len(results)} instruments")
    print(f"Charts written to: {CHART_OUTPUT_DIR}")
    print("=" * 72)


if __name__ == "__main__":
    main()
