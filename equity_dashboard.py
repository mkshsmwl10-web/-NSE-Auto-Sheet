#!/usr/bin/env python3
"""Editable weekly P/L ledger, weekly and monthly equity candles, HTML chart.

Records in Equity Weekly Input are user-entered net weekly P/L, not
HalfMonth Signals' hypothetical mark-to-market figures.
DEMO rows are ignored as soon as any LIVE entry exists.
"""
import json
import os
from datetime import datetime
from pathlib import Path

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

SHEET_ID = os.getenv("SPREADSHEET_ID", "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E")
CHART_FILE = Path("docs/charts/equity-performance.html")
CHART_URL = "https://mkshsmwl10-web.github.io/-NSE-Auto-Sheet/docs/charts/equity-performance.html"
INPUT = "Equity Weekly Input"
SETTINGS = "Equity Settings"
WEEKLY = "Equity Weekly"
MONTHLY = "Equity Monthly"


def book():
    raw = os.environ["GCP_CREDENTIALS"].strip()
    scope = ["https://www.googleapis.com/auth/spreadsheets",
             "https://www.googleapis.com/auth/drive"]
    cred = (Credentials.from_service_account_info(json.loads(raw), scopes=scope)
            if raw.startswith("{") else
            Credentials.from_service_account_file(raw, scopes=scope))
    return gspread.authorize(cred).open_by_key(SHEET_ID)


def sheet(b, name, cols=12):
    try:
        return b.worksheet(name)
    except gspread.WorksheetNotFound:
        return b.add_worksheet(title=name, rows=150, cols=cols)


def bootstrap(b):
    config = sheet(b, SETTINGS, 4)
    if not config.get_all_values():
        config.update([["EQUITY SETTINGS", "Value", "Instructions"],
                       ["Opening Equity ₹", 400000,
                        "Example opening amount. Edit B2 to your actual starting equity."],
                       ["Chart link", CHART_URL, "Open after GitHub Pages publishes"],
                       ["Input instructions", "Use LIVE for real weekly data",
                        "DEMO entries are examples, never actual booked returns."]],
                      range_name="A1:C4", value_input_option="RAW")
    config.freeze(rows=1)
    config.format("A1:C1", {
        "backgroundColor": {"red": 0.15, "green": 0.28, "blue": 0.37},
        "textFormat": {"bold": True,
                       "foregroundColor": {"red": 1, "green": 1, "blue": 1}}})
    inp = sheet(b, INPUT, 6)
    if not inp.get_all_values():
        inp.update([
            ["Week Ending Date", "Net P/L ₹", "Mode", "Notes"],
            ["2026-10-04", 12000, "DEMO", "Sample week 1; replace with LIVE figures"],
            ["2026-10-11", -5000, "DEMO", "Sample week 2; replace with LIVE figures"]],
            range_name="A1:D3", value_input_option="RAW")
    inp.freeze(rows=1)
    inp.format("A1:D1", {
        "backgroundColor": {"red": 0.07, "green": 0.40, "blue": 0.40},
        "textFormat": {"bold": True,
                       "foregroundColor": {"red": 1, "green": 1, "blue": 1}}})
    raw_amount = str(config.acell("B2").value or "").replace(",", "").replace("₹", "").strip()
    try:
        opening = float(raw_amount)
    except ValueError as exc:
        raise ValueError("Equity Settings!B2 must be a number") from exc
    if opening < 0:
        raise ValueError("Opening equity cannot be negative")
    entries = []
    for i, row in enumerate(inp.get_all_values()[1:], start=2):
        row += [""] * max(0, 4 - len(row))
        d, amount, mode, note = [str(x).strip() for x in row[:4]]
        if not d and not amount:
            continue
        if not d or not amount:
            raise ValueError("Incomplete Equity Weekly Input row " + str(i))
        try:
            day = pd.to_datetime(d, dayfirst=False, errors="raise").date()
            gain = float(amount.replace(",", "").replace("₹", ""))
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid date or P/L in Equity Weekly Input row " + str(i)) from exc
        mode = mode.upper()
        if mode not in ("LIVE", "DEMO"):
            raise ValueError("Mode must be LIVE or DEMO at Equity Weekly Input row " + str(i))
        entries.append((day, gain, mode, note))
    return opening, entries


def build(opening, entries):
    mode = "LIVE" if any(r[2] == "LIVE" for r in entries) else "DEMO"
    selected = [r for r in entries if r[2] == mode]
    # One row per calendar week, Monday through Sunday. Entries within a
    # week are summed; monthly attribution uses each week's ending date.
    weekly_groups = {}
    for day, gain, _, _ in selected:
        week_start = day - pd.Timedelta(days=day.weekday())
        week_end = week_start + pd.Timedelta(days=6)
        weekly_groups[week_end] = weekly_groups.get(week_end, 0) + gain
    running = float(opening)
    weekly = []
    for week_end, gain in sorted(weekly_groups.items()):
        begin, finish = running, running + gain
        weekly.append({"Period": str(week_end), "Open": round(begin, 2),
                       "High": round(max(begin, finish), 2),
                       "Low": round(min(begin, finish), 2),
                       "Close": round(finish, 2), "P/L": round(gain, 2),
                       "Return %": round(100 * gain / begin, 2) if begin else 0,
                       "Candle": "GREEN" if gain > 0 else "RED" if gain < 0 else "FLAT"})
        running = finish
    months = {}
    for w in weekly:
        key = w["Period"][:7]
        months[key] = months.get(key, 0) + w["P/L"]
    running = float(opening)
    monthly = []
    for period, gain in sorted(months.items()):
        begin, finish = running, running + gain
        monthly.append({"Period": period, "Open": round(begin, 2),
                        "High": round(max(begin, finish), 2),
                        "Low": round(min(begin, finish), 2),
                        "Close": round(finish, 2), "P/L": round(gain, 2),
                        "Return %": round(100 * gain / begin, 2) if begin else 0,
                        "Candle": "GREEN" if gain > 0 else "RED" if gain < 0 else "FLAT"})
        running = finish
    return mode, weekly, monthly


HEADERS = ["Period", "Open", "High", "Low", "Close", "P/L", "Return %", "Candle"]


def write_summary(b, name, mode, opening, data):
    ws = sheet(b, name, len(HEADERS))
    ws.clear()
    ws.resize(rows=max(80, len(data) + 6), cols=8)
    pnl = round(sum(r["P/L"] for r in data), 2)
    result = [
        [name.upper(), "DEMO — NOT REAL RETURNS" if mode == "DEMO"
         else "LIVE — USER-ENTERED RETURNS"],
        ["Opening Equity", opening, "Net P/L", pnl,
         "Closing Equity", round(opening + pnl, 2)],
        ["Chart", CHART_URL],
        HEADERS]
    result.extend([[r[k] for k in HEADERS] for r in data])
    ws.update(result, range_name="A1:H" + str(len(result)),
              value_input_option="RAW")
    ws.freeze(rows=4, cols=1)
    ws.format("A1:H1", {"backgroundColor": {
        "red": 0.13, "green": 0.25, "blue": 0.35},
        "textFormat": {"bold": True, "fontSize": 12,
                       "foregroundColor": {"red": 1, "green": 1, "blue": 1}}})
    ws.format("A4:H4", {"backgroundColor": {
        "red": 0.08, "green": 0.43, "blue": 0.43},
        "textFormat": {"bold": True,
                       "foregroundColor": {"red": 1, "green": 1, "blue": 1}}})
    if data:
        ws.format("B5:G" + str(len(data)+4), {"numberFormat": {
            "type": "NUMBER", "pattern": "#,##0.00;[Red]-#,##0.00"}})
    styles = []
    for n, r in enumerate(data, start=5):
        bg = ({"red": 0.87, "green": 0.96, "blue": 0.89} if r["P/L"] > 0
              else {"red": 1, "green": 0.89, "blue": 0.89} if r["P/L"] < 0
              else {"red": 0.95, "green": 0.96, "blue": 0.97})
        styles.append({"repeatCell": {"range": {
            "sheetId": ws.id, "startRowIndex": n-1, "endRowIndex": n,
            "startColumnIndex": 0, "endColumnIndex": 8},
            "cell": {"userEnteredFormat": {"backgroundColor": bg}},
            "fields": "userEnteredFormat.backgroundColor"}})
    for i in range(0, len(styles), 100):
        b.batch_update({"requests": styles[i:i+100]})


def create_chart(mode, opening, weekly, monthly):
    CHART_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"weekly": weekly, "monthly": monthly,
                          "mode": mode, "opening": opening}, ensure_ascii=False)
    page = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Weekly / Monthly Equity Candles</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{margin:0;background:#f3f7f8;color:#193843;font:15px system-ui,Arial}
main{max-width:1100px;margin:30px auto;padding:0 18px}
header{background:#193843;color:white;border-radius:16px;padding:23px}
h1{margin:0 0 8px;font-size:25px}p{margin:8px 0}
.notice{margin:15px 0;padding:12px;background:#fff1d4;border-radius:9px}
.controls{display:flex;flex-wrap:wrap;gap:8px;margin:20px 0}
button{background:#e1eeef;color:#194a50;border:0;border-radius:9px;padding:10px 18px;font-weight:bold;cursor:pointer}
button.active{background:#12665e;color:white}
#chart{min-height:460px;background:white;border-radius:16px}
footer{margin-top:18px;color:#52666f;font-size:13px}
</style></head><body><main><header><h1>Equity P/L • Candlestick Dashboard</h1>
<p>Weekly / Monthly • User-entered net P/L • Starts at ₹<span id="opening"></span></p></header>
<div id="mode" class="notice"></div>
<div class="controls">
<button onclick="draw('weekly','candle',this)" class="active">Weekly Candles</button>
<button onclick="draw('monthly','candle',this)">Monthly Candles</button>
<button onclick="draw('weekly','bar',this)">Weekly P/L</button>
<button onclick="draw('monthly','bar',this)">Monthly P/L</button>
</div><div id="chart"></div>
<footer>High/Low are endpoints of the period's opening and closing equity, not real intraweek extremes.
Monthly grouping uses the week-ending date. Brokerage and taxes depend on input net P/L.</footer></main>
<script>
const db = __PAYLOAD__;
document.getElementById('opening').textContent=db.opening.toLocaleString('en-IN');
document.getElementById('mode').textContent=db.mode==='DEMO'?
'DEMO DATA ONLY — These sample gains/losses are not your actual trading returns. Replace with LIVE entries in Equity Weekly Input.':
'LIVE MODE — Derived from your manually entered weekly P/L, not broker-linked.';
function draw(period,kind,button){
if(button){document.querySelectorAll('button').forEach(b=>b.classList.remove('active'));button.classList.add('active')}
const a=db[period]||[], x=a.map(z=>z.Period), gain=a.map(z=>z['P/L']);
let trace;
if(kind==='candle'){trace={type:'candlestick',x,open:a.map(z=>z.Open),high:a.map(z=>z.High),
low:a.map(z=>z.Low),close:a.map(z=>z.Close),
increasing:{line:{color:'#078568'},fillcolor:'#078568'},
decreasing:{line:{color:'#d04b55'},fillcolor:'#d04b55'}}}
else{trace={type:'bar',x,y:gain,marker:{color:gain.map(v=>v>=0?'#078568':'#d04b55')}}}
Plotly.react('chart',[trace],{title:period.toUpperCase()+(kind==='candle'?' Equity Candles':' Net P/L'),
paper_bgcolor:'white',plot_bgcolor:'white',font:{color:'#244450'},dragmode:'pan',
yaxis:{title:kind==='candle'?'Equity ₹':'P/L ₹',tickformat:',.0f'},
xaxis:{title:period==='weekly'?'Week ending':'Month',rangeslider:{visible:false}},
margin:{l:90,r:35,t:65,b:65}}, {responsive:true,displaylogo:false});
}
draw('weekly','candle',null);
</script></body></html>"""
    CHART_FILE.write_text(page.replace("__PAYLOAD__", payload), encoding="utf-8")


def main():
    b = book()
    opening, entries = bootstrap(b)
    mode, weekly, monthly = build(opening, entries)
    write_summary(b, WEEKLY, mode, opening, weekly)
    write_summary(b, MONTHLY, mode, opening, monthly)
    create_chart(mode, opening, weekly, monthly)
    print("Equity dashboard:", mode, len(weekly), "weeks,",
          len(monthly), "months; chart:", CHART_FILE)


if __name__ == "__main__":
    main()
