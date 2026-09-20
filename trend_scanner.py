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
CHART_OUTPUT_DIR = Path(os.environ.get("TREND_CHART_OUTPUT_DIR", "docs/trend-charts"))
CHART_BASE_URL = os.environ.get(
    "TREND_CHART_BASE_URL",
    "https://mkshsmwl10-web.github.io/-NSE-Auto-Sheet/docs/trend-charts",
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
    """
    First candle: Close >= Open => POSITIVE, else NEGATIVE.
    POSITIVE flips if Close < previous reference Open.
    NEGATIVE flips if Close > previous reference Open.
    After EVERY completed candle, that candle's Open becomes next reference Open.
    Equality does not flip.
    """
    if df is None or df.empty:
        return "NO DATA", None, None

    work = df.dropna(subset=["Open", "Close"])
    if work.empty:
        return "NO DATA", None, None

    first_open = float(work.iloc[0]["Open"])
    first_close = float(work.iloc[0]["Close"])
    trend = "POSITIVE" if first_close >= first_open else "NEGATIVE"
    reference_open = first_open
    last_change = work.index[0]

    for i in range(1, len(work)):
        candle_open = float(work.iloc[i]["Open"])
        candle_close = float(work.iloc[i]["Close"])

        if trend == "POSITIVE" and candle_close < reference_open:
            trend = "NEGATIVE"
            last_change = work.index[i]
        elif trend == "NEGATIVE" and candle_close > reference_open:
            trend = "POSITIVE"
            last_change = work.index[i]

        reference_open = candle_open

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
<script src="https://unpkg.com/lightweight-charts@5.0.8/dist/lightweight-charts.standalone.production.js"></script>
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
#chart { width:100%; height:650px; }
@media(max-width:700px) {
  .status-grid { grid-template-columns:1fr; }
  #chart { height:520px; }
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
  <button onclick="fitChart()">Fit</button>
</div>
<div class="info" id="info"></div>
<div id="chart"></div>
<script>
const DATA = __DATA_JSON__;
let chart = null;
let candleSeries = null;

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
  document.querySelectorAll(".toolbar button").forEach(b => b.classList.remove("active"));
  const btn = document.getElementById(tf);
  if (btn) btn.classList.add("active");

  const holder = document.getElementById("chart");
  holder.innerHTML = "";
  const item = DATA[tf];

  document.getElementById("info").innerHTML =
    "<b>" + tf + " Trend:</b> " + item.trend +
    " &nbsp;&nbsp; <b>Current Reference Open:</b> " +
    (item.reference === null ? "-" : item.reference);

  chart = LightweightCharts.createChart(holder, {
    width:holder.clientWidth,
    height:holder.clientHeight,
    layout:{ background:{ color:"#0f172a" }, textColor:"#cbd5e1" },
    grid:{ vertLines:{ color:"#1e293b" }, horzLines:{ color:"#1e293b" } },
    rightPriceScale:{ borderColor:"#475569" },
    timeScale:{ borderColor:"#475569", timeVisible:true }
  });

  candleSeries = chart.addSeries(LightweightCharts.CandlestickSeries, {
    upColor:"#22c55e",
    downColor:"#ef4444",
    borderVisible:false,
    wickUpColor:"#22c55e",
    wickDownColor:"#ef4444"
  });

  candleSeries.setData(item.bars);

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

function fitChart() {
  if (chart) chart.timeScale().fitContent();
}

setupStatuses();
renderTF("Daily");

window.addEventListener("resize", () => {
  if (!chart) return;
  const holder = document.getElementById("chart");
  chart.applyOptions({ width:holder.clientWidth });
});
</script>
</body>
</html>
"""


def generate_chart(code, stock_name, cmp_price, daily, weekly, monthly, daily_info, weekly_info, monthly_info):
    safe_code = code.replace("^", "").replace("/", "-").replace(":", "-")
    filename = f"{safe_code}-trend.html"
    filepath = CHART_OUTPUT_DIR / filename
    chart_url = f"{CHART_BASE_URL}/{filename}?v=3"

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
            f'=HYPERLINK("{r["chart"]}","OPEN CHART")',
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
