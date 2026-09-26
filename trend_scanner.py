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
TRANSACTION_SHEET = os.environ.get("TRANSACTION_SHEET", "Trade Transactions")
TARGET_PER_STOCK = float(os.environ.get("TARGET_PER_STOCK", "10000"))
PORTFOLIO_CAPITAL = float(os.environ.get("PORTFOLIO_CAPITAL", "200000"))
TRADE_HOUR_IST = 10
TRADE_MINUTE_IST = 0
TRADE_WINDOW_MINUTES = 20
EXECUTE_TRADES = os.environ.get("EXECUTE_TRADES", "false").strip().lower() == "true"
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


def make_monthly(daily, completed_only=True):
    """
    Build monthly OHLC.

    completed_only=True  -> used for MONTHLY TREND calculation (current month excluded)
    completed_only=False -> used for MONTHLY CHART display (current month included)
    """
    if daily is None or daily.empty:
        return pd.DataFrame()
    work = daily.copy()
    monthly = work.groupby(work.index.to_period("M")).agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    )
    monthly.index = monthly.index.to_timestamp(how="end").normalize()

    if completed_only:
        current_month = pd.Timestamp(datetime.now(IST).replace(tzinfo=None)).to_period("M")
        monthly = monthly[monthly.index.to_period("M") < current_month]

    return monthly


def calculate_dynamic_trend(df):
    """
    Dynamic trend + Big Candle / Inside Candle lock.

    BIG candle is NOT ATR/body-size based.
    A candle becomes the active container/trend candle. Any later candle whose
    full High-Low range stays inside that active candle's High-Low range is a
    SMALL/INSIDE candle. Inside candles never shift the reference Open.

    POSITIVE:
      * Active/reference candle is GREEN.
      * Inside candles (green or red) do nothing.
      * A non-inside GREEN candle continues POSITIVE and becomes the new active
        candle; reference shifts to its Open.
      * A RED candle flips NEGATIVE only if it closes below the active reference
        Open. That RED candle becomes the new active candle/reference.
      * Otherwise the red candle does not shift the reference.

    NEGATIVE: exact reverse.
      * Inside candles do nothing.
      * A non-inside RED candle continues NEGATIVE and becomes the new active
        candle; reference shifts to its Open.
      * A GREEN candle flips POSITIVE only if it closes above the active
        reference Open. That GREEN candle becomes the new active candle/reference.
      * Otherwise the green candle does not shift the reference.
    """
    if df is None or df.empty:
        return "NO DATA", None, None

    work = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    if work.empty:
        return "NO DATA", None, None

    # First completed non-doji candle establishes the first trend/container.
    start_i = 0
    while start_i < len(work):
        o = float(work.iloc[start_i]["Open"])
        c = float(work.iloc[start_i]["Close"])
        if c != o:
            break
        start_i += 1

    if start_i >= len(work):
        return "NO DATA", None, None

    row = work.iloc[start_i]
    active_open = float(row["Open"])
    active_high = float(row["High"])
    active_low = float(row["Low"])
    active_close = float(row["Close"])

    trend = "POSITIVE" if active_close > active_open else "NEGATIVE"
    reference_open = active_open
    last_change = work.index[start_i]

    for i in range(start_i + 1, len(work)):
        row = work.iloc[i]
        o = float(row["Open"])
        h = float(row["High"])
        l = float(row["Low"])
        c = float(row["Close"])

        green = c > o
        red = c < o

        # Full candle is inside the active Big/Container candle:
        # it is SMALL regardless of colour and cannot move the reference.
        inside_active = (h <= active_high and l >= active_low)
        if inside_active:
            continue

        if trend == "POSITIVE":
            # Confirmed opposite-colour reversal.
            if red and c < reference_open:
                trend = "NEGATIVE"
                reference_open = o
                active_open, active_high, active_low = o, h, l
                last_change = work.index[i]

            # Same-trend colour outside active range: new active trend candle.
            elif green:
                reference_open = o
                active_open, active_high, active_low = o, h, l

            # Red without reversal: keep old active candle/reference locked.

        elif trend == "NEGATIVE":
            # Confirmed opposite-colour reversal.
            if green and c > reference_open:
                trend = "POSITIVE"
                reference_open = o
                active_open, active_high, active_low = o, h, l
                last_change = work.index[i]

            # Same-trend colour outside active range: new active trend candle.
            elif red:
                reference_open = o
                active_open, active_high, active_low = o, h, l

            # Green without reversal: keep old active candle/reference locked.

    return trend, round(reference_open, 2), last_change


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
#drawCanvas{position:absolute;inset:0;width:100%;height:100%;z-index:5;pointer-events:none} #drawHit{position:absolute;inset:0;z-index:6;pointer-events:none;cursor:crosshair}
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
  <button id="toolH" onclick="drawH()">H-Line</button> <button id="toolV" onclick="drawV()">V-Line</button>
  <button id="toolT" onclick="drawTrend()">Trend Line</button> <button id="toolR" onclick="drawRay()">Ray</button>
  <button id="toolClear" onclick="clearDrawings()">Clear Drawings</button>
</div>
<div class="info" id="info"></div><div class="ohlc" id="ohlc">Move mouse over a candle to see OHLC</div>
<div id="chartWrap"><div id="chart"></div><canvas id="drawCanvas"></canvas><div id="drawHit"></div></div>
<script>
const DATA = __DATA_JSON__;
let chart = null;
let candleSeries=null, currentTF="Daily", drawings=[], mode=null, firstPoint=null;
const drawCanvas=document.getElementById("drawCanvas");
const drawHit=document.getElementById("drawHit");
const pen=drawCanvas.getContext("2d");
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
  currentTF=tf; firstPoint=null; mode=null; drawHit.style.pointerEvents="none"; redraw();
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
  setTimeout(resizeDrawingCanvas,0);
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

function resizeDrawingCanvas(){
  const r=drawCanvas.getBoundingClientRect();
  const dpr=window.devicePixelRatio||1;
  drawCanvas.width=Math.max(1,Math.round(r.width*dpr));
  drawCanvas.height=Math.max(1,Math.round(r.height*dpr));
  pen.setTransform(dpr,0,0,dpr,0,0);
  redraw();
}
function setMode(m){
  mode=(mode===m?null:m);
  firstPoint=null;
  drawHit.style.pointerEvents=mode?"auto":"none";
  document.querySelectorAll(".toolbar button").forEach(b=>b.classList.remove("tool-active"));
  const ids={h:"toolH",v:"toolV",t:"toolT",r:"toolR"};
  if(mode && ids[mode]) document.getElementById(ids[mode]).classList.add("tool-active");
}
function drawH(){setMode("h")}
function drawV(){setMode("v")}
function drawTrend(){setMode("t")}
function drawRay(){setMode("r")}
function clearDrawings(){
  drawings=[];
  firstPoint=null;
  mode=null;
  drawHit.style.pointerEvents="none";
  document.querySelectorAll(".toolbar button").forEach(b=>b.classList.remove("tool-active"));
  redraw();
}
function hitPoint(e){
  const r=drawHit.getBoundingClientRect();
  return {x:e.clientX-r.left,y:e.clientY-r.top};
}
function line(x1,y1,x2,y2){
  pen.beginPath(); pen.moveTo(x1,y1); pen.lineTo(x2,y2);
  pen.strokeStyle="#f59e0b"; pen.lineWidth=2; pen.stroke();
}
function redraw(){
  const r=drawCanvas.getBoundingClientRect();
  pen.clearRect(0,0,r.width,r.height);
  drawings.filter(d=>d.tf===currentTF).forEach(d=>{
    if(d.k==="h") line(0,d.a.y,r.width,d.a.y);
    else if(d.k==="v") line(d.a.x,0,d.a.x,r.height);
    else if(d.k==="t") line(d.a.x,d.a.y,d.b.x,d.b.y);
    else if(d.k==="r"){
      const dx=d.b.x-d.a.x,dy=d.b.y-d.a.y;
      if(Math.abs(dx)<0.001) line(d.a.x,d.a.y,d.a.x,dy>=0?r.height:0);
      else{
        const tx=dx>=0?r.width:0, q=(tx-d.a.x)/dx;
        line(d.a.x,d.a.y,tx,d.a.y+q*dy);
      }
    }
  });
}
drawHit.addEventListener("click",e=>{
  if(!mode)return;
  const p=hitPoint(e);
  if(mode==="h"||mode==="v"){
    drawings.push({tf:currentTF,k:mode,a:p});
    redraw(); setMode(null); return;
  }
  if(firstPoint===null){
    firstPoint=p;
  }else{
    drawings.push({tf:currentTF,k:mode,a:firstPoint,b:p});
    firstPoint=null; redraw(); setMode(null);
  }
});

function setupCrosshairOHLC(){
  if(!chart||!candleSeries)return;
  chart.subscribeCrosshairMove(param=>{
    if(!param || !param.time){
      ohlcBox.innerHTML="<span>Hover candle → OHLC</span>";
      return;
    }
    const d=param.seriesData && param.seriesData.get(candleSeries);
    if(!d || d.open===undefined){
      ohlcBox.innerHTML="<span>Hover candle → OHLC</span>";
      return;
    }
    let date="";
    if(typeof param.time==="string") date=param.time;
    else if(param.time.year) date=param.time.year+"-"+String(param.time.month).padStart(2,"0")+"-"+String(param.time.day).padStart(2,"0");
    else date=String(param.time);
    ohlcBox.innerHTML="<span>"+date+"</span>"+
      "<span>O: "+Number(d.open).toFixed(2)+"</span>"+
      "<span>H: "+Number(d.high).toFixed(2)+"</span>"+
      "<span>L: "+Number(d.low).toFixed(2)+"</span>"+
      "<span>C: "+Number(d.close).toFixed(2)+"</span>";
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
  resizeDrawingCanvas();
});
</script>
</body>
</html>
"""


def generate_chart(code, stock_name, cmp_price, daily, weekly, monthly_chart, daily_info, weekly_info, monthly_info):
    safe_code = code.replace("^", "").replace("/", "-").replace(":", "-")
    filename = f"{safe_code}-trend.html"
    filepath = CHART_OUTPUT_DIR / filename
    chart_url = f"{CHART_BASE_URL}/{filename}?v=17.7"

    payload = {
        "name": stock_name,
        "code": code,
        "cmp": cmp_price,
        "Daily": {"trend": daily_info[0], "reference": daily_info[1], "bars": chart_bars(daily, 180)},
        "Weekly": {"trend": weekly_info[0], "reference": weekly_info[1], "bars": chart_bars(weekly, 120)},
        "Monthly": {"trend": monthly_info[0], "reference": monthly_info[1], "bars": chart_bars(monthly_chart, 60)},
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
    monthly = make_monthly(daily, completed_only=True)
    monthly_chart = make_monthly(daily, completed_only=False)

    # CMP can use latest Yahoo daily value; trend itself uses completed candles only.
    cmp_price = round(float(df.iloc[-1]["Close"]), 2)

    daily_info = calculate_dynamic_trend(daily)
    weekly_info = calculate_dynamic_trend(weekly)
    monthly_info = calculate_dynamic_trend(monthly)

    # Generate dedicated trend chart for every instrument, including NIFTY 50 SPOT.
    chart_url = generate_chart(
        stock["code"], stock["name"], cmp_price,
        daily, weekly, monthly_chart,
        daily_info, weekly_info, monthly_info,
    )

    return {
        "name": stock["name"],
        "code": stock["code"],
        "cmp": cmp_price,
        "daily": daily_info[0],
        "weekly": weekly_info[0],
        "monthly": monthly_info[0],
        "_daily_df": daily,
        "chart": chart_url,
    }




def get_last_month_close(daily_df):
    """Last available completed Daily Close from the previous calendar month."""
    try:
        if daily_df is None or daily_df.empty:
            return None
        d = daily_df.dropna(subset=["Close"]).copy()
        if d.empty:
            return None
        prev_month = d.index[-1].to_period("M") - 1
        prev = d[d.index.to_period("M") == prev_month]
        if prev.empty:
            return None
        return round(float(prev.iloc[-1]["Close"]), 2)
    except Exception:
        return None




def is_sma20_slope_up(daily_df):
    """True only when completed-daily SMA20 is higher than its previous value."""
    try:
        d = daily_df.dropna(subset=["Close"]).copy()
        if len(d) < 21:
            return False
        sma20 = d["Close"].rolling(20).mean()
        return bool(sma20.iloc[-1] > sma20.iloc[-2])
    except Exception:
        return False


def calculate_rs_vs_nifty_1m(stock_daily, nifty_daily):
    """21-session relative return: Stock 1M % minus NIFTY 1M %."""
    try:
        if stock_daily is None or nifty_daily is None:
            return None, ""
        a = stock_daily.dropna(subset=["Close"]).copy()
        b = nifty_daily.dropna(subset=["Close"]).copy()
        common = a.index.intersection(b.index).sort_values()
        if len(common) < 22:
            return None, ""
        start, end = common[-22], common[-1]
        sr = (float(a.loc[end,"Close"]) / float(a.loc[start,"Close"]) - 1) * 100
        nr = (float(b.loc[end,"Close"]) / float(b.loc[start,"Close"]) - 1) * 100
        rs = round(sr - nr, 2)
        return rs, ("OUTPERFORM" if rs > 0 else "UNDERPERFORM")
    except Exception:
        return None, ""


def classify_signal(code, daily, weekly, monthly):
    """Classify stock alignment. NIFTY spot is intentionally excluded."""
    if code == "^NSEI":
        return ""

    combo = (daily, weekly, monthly)

    if combo == ("POSITIVE", "POSITIVE", "POSITIVE"):
        return "ALL POSITIVE"
    if combo == ("NEGATIVE", "NEGATIVE", "NEGATIVE"):
        return "ALL NEGATIVE"
    if combo == ("NEGATIVE", "POSITIVE", "POSITIVE"):
        return "PULLBACK WATCH"
    if combo == ("POSITIVE", "NEGATIVE", "POSITIVE"):
        return "REVERSAL WATCH"

    return ""


def sort_results_for_positional(results):
    """
    Keep NIFTY first, then prioritize positional-long candidates:

      1) ALL POSITIVE + OUTPERFORM
      2) PULLBACK WATCH + OUTPERFORM
      3) REVERSAL WATCH + OUTPERFORM
      4) Other OUTPERFORM stocks
      5) UNDERPERFORM / remaining stocks

    Within the same bucket, higher RS vs NIFTY comes first.
    Trend calculation and RS calculation are NOT changed here.
    """
    def key(r):
        code = r.get("code", "")
        if code == "^NSEI":
            return (-1, 0.0, "")

        signal = classify_signal(
            code,
            r.get("daily", ""),
            r.get("weekly", ""),
            r.get("monthly", ""),
        )
        strength = r.get("rs_strength", "")
        rs = r.get("rs_vs_nifty")
        rs_num = float(rs) if rs is not None else -999999.0

        if strength == "OUTPERFORM" and signal == "ALL POSITIVE":
            bucket = 0
        elif strength == "OUTPERFORM" and signal == "PULLBACK WATCH":
            bucket = 1
        elif strength == "OUTPERFORM" and signal == "REVERSAL WATCH":
            bucket = 2
        elif strength == "OUTPERFORM":
            bucket = 3
        else:
            bucket = 4

        return (bucket, -rs_num, r.get("name", ""))

    return sorted(results, key=key)



def _num(v, default=0.0):
    try:
        if v in ("", None):
            return default
        return float(str(v).replace(",", "").strip())
    except Exception:
        return default


def get_transaction_sheet(book):
    headers = [
        "Date", "Time", "Stock Name", "NSE Code", "Action", "Rank",
        "Price", "Units", "Trade Value", "Realized P/L", "% P/L"
    ]
    try:
        ws = book.worksheet(TRANSACTION_SHEET)
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(title=TRANSACTION_SHEET, rows=2000, cols=len(headers))
        ws.append_row(headers, value_input_option="USER_ENTERED")
        ws.freeze(rows=1)
        ws.format("A1:K1", {
            "backgroundColor":{"red":0.10,"green":0.18,"blue":0.32},
            "textFormat":{"foregroundColor":{"red":1,"green":1,"blue":1},"bold":True},
            "horizontalAlignment":"CENTER",
        })
    values = ws.get_all_values()
    if not values:
        ws.append_row(headers, value_input_option="USER_ENTERED")
    elif [x.strip() for x in values[0]] != headers:
        # Keep existing history safe; only normalize header when sheet is empty apart from header.
        if len(values) == 1:
            ws.update(range_name="A1:K1", values=[headers], value_input_option="USER_ENTERED")
    return ws


def load_trade_state(tx_ws):
    """Rebuild open positions and cumulative booked P/L from permanent transaction history."""
    values = tx_ws.get_all_values()
    open_positions = {}
    booked_by_code = {}
    if len(values) <= 1:
        return open_positions, booked_by_code

    header = [str(x).strip() for x in values[0]]
    idx = {name: i for i, name in enumerate(header)}

    for row in values[1:]:
        def cell(name):
            i = idx.get(name)
            return row[i].strip() if i is not None and i < len(row) else ""

        code = cell("NSE Code")
        action = cell("Action").upper()
        if not code:
            continue

        if action == "BUY":
            open_positions[code] = {
                "name": cell("Stock Name"),
                "buy_price": _num(cell("Price")),
                "units": int(_num(cell("Units"))),
                "buy_date": cell("Date"),
                "buy_time": cell("Time"),
            }
        elif action == "EXIT":
            open_positions.pop(code, None)
            booked_by_code[code] = round(
                booked_by_code.get(code, 0.0) + _num(cell("Realized P/L")), 2
            )

    return open_positions, booked_by_code


def append_trade(tx_ws, stock, action, rank, price, units, realized_pl="", realized_pct=""):
    now = datetime.now(IST)
    trade_value = round(float(price) * int(units), 2)
    tx_ws.append_row([
        now.strftime("%Y-%m-%d"),
        now.strftime("%H:%M:%S"),
        stock.get("name", ""),
        stock.get("code", ""),
        action,
        rank if rank != "" else "",
        round(float(price), 2),
        int(units),
        trade_value,
        realized_pl,
        realized_pct,
    ], value_input_option="USER_ENTERED")



def is_trade_execution_time():
    """
    Trade permission is controlled by the GitHub workflow, not clock time.

    Scheduled workflow: EXECUTE_TRADES=true -> BUY/EXIT allowed.
    Manual/default run: false/absent -> scanner refresh only.
    """
    return EXECUTE_TRADES


def update_portfolio(book, results):
    """
    Rules:
      - Maximum 2 NEW buys per trading day/run.
      - New entry only from current Rank 1-10, best rank first.
      - Already-owned stocks are skipped; scanner keeps moving down the ranks
        until it finds up to 2 new eligible stocks.
      - Previously bought Rank 11-20 positions remain HOLD.
      - Existing Rank 1-10 stays active.
      - Existing Rank 11-20 = HOLD.
      - Existing Rank 21+ OR blank rank = EXIT, profit or loss.
      - Approx Rs 10,000 per new stock: floor(10000 / buy price) units.
      - Every BUY/EXIT is permanently appended to Trade Transactions.
    """
    tx_ws = get_transaction_sheet(book)
    open_positions, booked_by_code = load_trade_state(tx_ws)
    by_code = {r.get("code"): r for r in results if r.get("code") != "^NSEI"}

    execute_trades = is_trade_execution_time()
    if execute_trades:
        print("TRADE MODE: ON — scheduled run; BUY/EXIT transactions allowed.")
    else:
        print("VIEW MODE: scanner refresh only — EXECUTE_TRADES is not enabled.")

    # 1) EXIT first so vacancies become available immediately.
    for code, pos in list(open_positions.items()):
        if not execute_trades:
            continue
        r = by_code.get(code)
        rank = r.get("rank", "") if r else ""
        rank_num = int(rank) if rank not in ("", None) else None

        if r is None or rank_num is None or rank_num >= 21:
            exit_price = float(r.get("cmp")) if r and r.get("cmp") is not None else pos["buy_price"]
            units = int(pos["units"])
            realized = round((exit_price - float(pos["buy_price"])) * units, 2)
            realized_pct = round(
                ((exit_price - float(pos["buy_price"])) / float(pos["buy_price"])) * 100.0, 2
            ) if pos["buy_price"] else 0.0

            stock_for_log = r or {"name": pos.get("name", code), "code": code}
            append_trade(
                tx_ws, stock_for_log, "EXIT",
                rank if rank not in (None, "") else "",
                exit_price, units, realized, realized_pct
            )
            booked_by_code[code] = round(booked_by_code.get(code, 0.0) + realized, 2)
            open_positions.pop(code, None)

    # 2) Fill vacant slots only with Rank 1-10 stocks, best rank first.
    candidates = sorted(
        [
            r for r in results
            if r.get("code") != "^NSEI"
            and r.get("rank", "") != ""
            and 1 <= int(r["rank"]) <= 10
            and r.get("code") not in open_positions
        ],
        key=lambda r: int(r["rank"])
    )

    # Maximum 2 NEW stocks per trading day/run.
    # Already-owned stocks were excluded above, so this naturally picks the
    # next best available ranks (e.g. if Rank 1 & 2 are owned, buy Rank 3 & 4).
    buy_candidates = candidates[:2] if execute_trades else []
    for r in buy_candidates:
        buy_price = float(r["cmp"])
        units = int(TARGET_PER_STOCK // buy_price) if buy_price > 0 else 0
        if units < 1:
            continue
        append_trade(tx_ws, r, "BUY", r["rank"], buy_price, units)
        open_positions[r["code"]] = {
            "name": r["name"],
            "buy_price": round(buy_price, 2),
            "units": units,
            "buy_date": datetime.now(IST).strftime("%Y-%m-%d"),
            "buy_time": datetime.now(IST).strftime("%H:%M:%S"),
        }

    # 3) Attach portfolio fields to scanner rows.
    for r in results:
        code = r.get("code")
        r["buy_price"] = ""
        r["buy_unit"] = ""
        r["total_value"] = ""
        r["profit_loss"] = ""
        r["profit_loss_pct"] = ""
        r["book_profit_loss"] = "" if code == "^NSEI" else round(booked_by_code.get(code, 0.0), 2)

        if code in open_positions:
            pos = open_positions[code]
            bp = float(pos["buy_price"])
            units = int(pos["units"])
            cmp_price = float(r["cmp"])
            r["buy_price"] = round(bp, 2)
            r["buy_unit"] = units
            r["total_value"] = round(cmp_price * units, 2)
            r["profit_loss"] = round((cmp_price - bp) * units, 2)
            r["profit_loss_pct"] = round(((cmp_price - bp) / bp) * 100.0, 2) if bp else 0.0

    live_pl = round(sum(_num(r.get("profit_loss")) for r in results), 2)
    booked_pl = round(sum(booked_by_code.values()), 2)
    invested_capital = round(sum(
        float(pos["buy_price"]) * int(pos["units"])
        for pos in open_positions.values()
    ), 2)
    available_capital = round(PORTFOLIO_CAPITAL - invested_capital, 2)
    total_pl = round(live_pl + booked_pl, 2)

    summary = {
        "capital": round(PORTFOLIO_CAPITAL, 2),
        "per_position": round(TARGET_PER_STOCK, 2),
        "active_positions": len(open_positions),
        "invested_capital": invested_capital,
        "available_capital": available_capital,
        "live_pl": live_pl,
        "booked_pl": booked_pl,
        "total_pl": total_pl,
    }

    print(f"Open portfolio positions: {len(open_positions)}")
    print(f"Invested capital: {invested_capital} | Available: {available_capital}")
    print(f"Live P/L: {live_pl} | Booked P/L: {booked_pl} | Total P/L: {total_pl}")
    return open_positions, booked_by_code, summary


def write_sheet(book, results, summary):
    try:
        ws = book.worksheet(OUTPUT_SHEET)
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(title=OUTPUT_SHEET, rows=500, cols=20)

    ws.clear()

    headers = [
        "Stock Name", "NSE Code", "CMP", "Last Month Close", "1 Month % Change",
        "Rank", "SMA20 SLOPE", "Signal", "BUY PRICE", "BUY UNIT", "TOTAL VALUE",
        "PROFIT/LOSS", "% PROFIT/LOSS", "BOOK PROFIT/LOSS",
        "Daily Trend", "Weekly Trend", "Monthly Trend", "Chart"
    ]
    values = [headers]

    for r in results:
        code = r.get("code")
        rank = r.get("rank", "")
        # Ranking display rule remains unchanged.
        signal = (
            "" if code == "^NSEI" else
            "BUY" if rank != "" and int(rank) <= 10 else
            "HOLD" if rank != "" and int(rank) <= 20 else
            "EXIT"
        )

        values.append([
            r["name"], code, r["cmp"],
            "" if r.get("last_month_close") is None else r["last_month_close"],
            "" if r.get("one_month_change_pct") is None else r["one_month_change_pct"],
            rank,
            "" if code == "^NSEI" else ("UP" if r.get("sma20_slope_up") is True else "DOWN"),
            signal,
            r.get("buy_price", ""), r.get("buy_unit", ""), r.get("total_value", ""),
            r.get("profit_loss", ""), r.get("profit_loss_pct", ""),
            r.get("book_profit_loss", ""),
            r["daily"], r["weekly"], r["monthly"], "OPEN CHART",
        ])

    ws.update(
        range_name=f"A1:R{len(values)}",
        values=values,
        value_input_option="USER_ENTERED",
    )
    ws.freeze(rows=1, cols=1)

    # Portfolio Summary box in S:T
    summary_values = [
        ["PORTFOLIO SUMMARY", "VALUE"],
        ["CAPITAL", summary["capital"]],
        ["PER NEW POSITION", summary["per_position"]],
        ["ACTIVE POSITIONS", summary["active_positions"]],
        ["INVESTED CAPITAL", summary["invested_capital"]],
        ["AVAILABLE CAPITAL", summary["available_capital"]],
        ["LIVE PROFIT/LOSS", summary["live_pl"]],
        ["BOOK PROFIT/LOSS", summary["booked_pl"]],
        ["TOTAL PROFIT/LOSS", summary["total_pl"]],
    ]
    ws.update(range_name="S1:T9", values=summary_values, value_input_option="USER_ENTERED")

    ws.format("S1:T1", {
        "backgroundColor":{"red":0.10,"green":0.18,"blue":0.32},
        "textFormat":{"foregroundColor":{"red":1,"green":1,"blue":1},"bold":True},
        "horizontalAlignment":"CENTER",
    })
    ws.format("S2:S9", {"textFormat":{"bold":True}})
    ws.format("T2:T9", {"horizontalAlignment":"RIGHT"})

    ws.format("A1:R1", {
        "backgroundColor":{"red":0.10,"green":0.18,"blue":0.32},
        "textFormat":{"foregroundColor":{"red":1,"green":1,"blue":1},"bold":True,"fontSize":11},
        "horizontalAlignment":"CENTER","verticalAlignment":"MIDDLE",
    })

    if len(values) > 1:
        ws.format(f"A2:R{len(values)}", {"verticalAlignment":"MIDDLE"})
        ws.format(f"B2:R{len(values)}", {"horizontalAlignment":"CENTER"})
        ws.format("A2:N2", {
            "backgroundColor":{"red":0.88,"green":0.93,"blue":1.0},
            "textFormat":{"bold":True},
        })

    sheet_id = ws.id
    requests = []

    # Remove old conditional formatting every run to avoid duplicate rules.
    try:
        meta = book.fetch_sheet_metadata()
        target = next(x for x in meta["sheets"] if x["properties"]["sheetId"] == sheet_id)
        for index in reversed(range(len(target.get("conditionalFormats", [])))):
            requests.append({"deleteConditionalFormatRule":{"sheetId":sheet_id,"index":index}})
    except Exception as exc:
        print(f"Conditional-format cleanup skipped: {exc}")

    def add_text_rule(col0, text, bg, fg):
        requests.append({
            "addConditionalFormatRule":{
                "rule":{
                    "ranges":[{
                        "sheetId":sheet_id,"startRowIndex":1,
                        "startColumnIndex":col0,"endColumnIndex":col0+1
                    }],
                    "booleanRule":{
                        "condition":{"type":"TEXT_EQ","values":[{"userEnteredValue":text}]},
                        "format":{"backgroundColor":bg,
                                  "textFormat":{"foregroundColor":fg,"bold":True}},
                    },
                },
                "index":0,
            }
        })

    # SMA20 Slope G: UP green, DOWN red.
    add_text_rule(6, "UP",
                  {"red":0.78,"green":0.93,"blue":0.80},
                  {"red":0.05,"green":0.45,"blue":0.12})
    add_text_rule(6, "DOWN",
                  {"red":0.96,"green":0.78,"blue":0.78},
                  {"red":0.70,"green":0.05,"blue":0.05})

    # Signal H: BUY green, HOLD yellow, EXIT red.
    add_text_rule(7, "BUY",
                  {"red":0.80,"green":0.94,"blue":0.81},
                  {"red":0.05,"green":0.45,"blue":0.12})
    add_text_rule(7, "HOLD",
                  {"red":1.00,"green":0.94,"blue":0.70},
                  {"red":0.55,"green":0.35,"blue":0.00})
    add_text_rule(7, "EXIT",
                  {"red":0.96,"green":0.80,"blue":0.80},
                  {"red":0.70,"green":0.05,"blue":0.05})

    # Daily/Weekly/Monthly O:Q: POSITIVE green, NEGATIVE red.
    for col0 in [14, 15, 16]:
        add_text_rule(col0, "POSITIVE",
                      {"red":0.78,"green":0.93,"blue":0.80},
                      {"red":0.05,"green":0.45,"blue":0.12})
        add_text_rule(col0, "NEGATIVE",
                      {"red":0.96,"green":0.78,"blue":0.78},
                      {"red":0.70,"green":0.05,"blue":0.05})

    # Profit/Loss L, % P/L M, Book P/L N: positive green, negative red.
    for col0 in [11, 12, 13]:
        requests.append({
            "addConditionalFormatRule":{
                "rule":{
                    "ranges":[{"sheetId":sheet_id,"startRowIndex":1,
                               "startColumnIndex":col0,"endColumnIndex":col0+1}],
                    "booleanRule":{
                        "condition":{"type":"NUMBER_GREATER","values":[{"userEnteredValue":"0"}]},
                        "format":{"backgroundColor":{"red":0.82,"green":0.95,"blue":0.84},
                                  "textFormat":{"foregroundColor":{"red":0.05,"green":0.40,"blue":0.16},"bold":True}},
                    },
                },"index":0
            }
        })
        requests.append({
            "addConditionalFormatRule":{
                "rule":{
                    "ranges":[{"sheetId":sheet_id,"startRowIndex":1,
                               "startColumnIndex":col0,"endColumnIndex":col0+1}],
                    "booleanRule":{
                        "condition":{"type":"NUMBER_LESS","values":[{"userEnteredValue":"0"}]},
                        "format":{"backgroundColor":{"red":1.0,"green":0.85,"blue":0.85},
                                  "textFormat":{"foregroundColor":{"red":0.65,"green":0.05,"blue":0.05},"bold":True}},
                    },
                },"index":0
            }
        })

    # Summary P/L cells T7:T9: positive green, negative red.
    for row0 in [6, 7, 8]:
        for cond_type, bg, fg in [
            ("NUMBER_GREATER",
             {"red":0.82,"green":0.95,"blue":0.84},
             {"red":0.05,"green":0.40,"blue":0.16}),
            ("NUMBER_LESS",
             {"red":1.0,"green":0.85,"blue":0.85},
             {"red":0.65,"green":0.05,"blue":0.05}),
        ]:
            requests.append({
                "addConditionalFormatRule":{
                    "rule":{
                        "ranges":[{"sheetId":sheet_id,"startRowIndex":row0,
                                   "endRowIndex":row0+1,"startColumnIndex":19,"endColumnIndex":20}],
                        "booleanRule":{
                            "condition":{"type":cond_type,"values":[{"userEnteredValue":"0"}]},
                            "format":{"backgroundColor":bg,
                                      "textFormat":{"foregroundColor":fg,"bold":True}},
                        },
                    },"index":0
                }
            })

    widths = {
        0:190,1:110,2:100,3:125,4:125,5:70,6:105,7:90,
        8:100,9:85,10:110,11:110,12:110,13:125,
        14:115,15:115,16:125,17:125,18:165,19:120
    }
    for col, pixels in widths.items():
        requests.append({
            "updateDimensionProperties":{
                "range":{"sheetId":sheet_id,"dimension":"COLUMNS",
                         "startIndex":col,"endIndex":col+1},
                "properties":{"pixelSize":pixels},"fields":"pixelSize",
            }
        })

    if requests:
        book.batch_update({"requests":requests})

    # Clickable chart links in R.
    try:
        link_requests = []
        for row_index, row in enumerate(results, start=2):
            chart_url = str(row.get("chart", "") or "").strip()
            if not chart_url.startswith(("http://", "https://")):
                continue
            link_requests.append({
                "updateCells":{
                    "range":{"sheetId":ws.id,"startRowIndex":row_index-1,
                             "endRowIndex":row_index,"startColumnIndex":17,"endColumnIndex":18},
                    "rows":[{"values":[{
                        "userEnteredValue":{"stringValue":"OPEN CHART"},
                        "textFormatRuns":[{"startIndex":0,"format":{
                            "link":{"uri":chart_url},"underline":True
                        }}],
                    }]}],
                    "fields":"userEnteredValue,textFormatRuns",
                }
            })
        for i in range(0, len(link_requests), 100):
            book.batch_update({"requests":link_requests[i:i+100]})
        print("Clickable rich-text chart links applied:", len(link_requests))
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

    nifty_daily = next((r.get("_daily_df") for r in results if r["code"] == "^NSEI"), None)
    for r in results:
        if r["code"] == "^NSEI":
            r["rs_vs_nifty"], r["rs_strength"] = None, ""
        else:
            r["rs_vs_nifty"], r["rs_strength"] = calculate_rs_vs_nifty_1m(
                r.get("_daily_df"), nifty_daily
            )

    for r in results:
        r["last_month_close"] = get_last_month_close(r.get("_daily_df"))
        last_close = r.get("last_month_close")
        cmp_price = r.get("cmp")
        if last_close not in (None, 0) and cmp_price is not None:
            r["one_month_change_pct"] = round(
                ((float(cmp_price) - float(last_close)) / float(last_close)) * 100.0, 2
            )
        else:
            r["one_month_change_pct"] = None

        r["sma20_slope_up"] = is_sma20_slope_up(r.get("_daily_df"))

    # V17.7 RANK RULE:
    # 1) Monthly trend must be POSITIVE
    # 2) Weekly trend must be POSITIVE
    # 3) Daily trend is NOT used
    # 4) Completed-daily SMA20 slope must be UP
    # 5) Eligible stocks are ranked ONLY by 1 Month % Change, highest first
    ranked_stocks = [
        r for r in results
        if r.get("code") != "^NSEI"
        and r.get("one_month_change_pct") is not None
        and r.get("monthly") == "POSITIVE"
        and r.get("weekly") == "POSITIVE"
        and r.get("sma20_slope_up") is True
    ]
    ranked_stocks.sort(key=lambda r: -float(r["one_month_change_pct"]))

    for r in results:
        r["rank"] = ""
    for i, r in enumerate(ranked_stocks, 1):
        r["rank"] = i

    # Persistent portfolio + permanent transaction history.
    # EXITs are processed first, then vacant slots are filled from Rank 1-10.
    open_positions, booked_by_code, summary = update_portfolio(book, results)

    # Visible order: NIFTY first, then eligible stocks by Rank 1,2,3...
    # Remaining stocks follow afterwards.
    results = sorted(
        results,
        key=lambda r: (
            0 if r.get("code") == "^NSEI" else
            1 if r.get("rank", "") != "" else 2,
            int(r.get("rank")) if r.get("rank", "") != "" else 999999,
            r.get("name", "")
        )
    )
    write_sheet(book, results, summary)

    print("=" * 72)
    print(f"Completed: {len(results)} instruments")
    print(f"Charts written to: {CHART_OUTPUT_DIR}")
    print("=" * 72)


if __name__ == "__main__":
    main()
