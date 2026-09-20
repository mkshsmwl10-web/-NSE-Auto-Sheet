import os
import json
import time
from pathlib import Path

import pandas as pd
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials


# ============================================================
# CONFIG
# ============================================================

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID",
    "1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E",
)

INPUT_SHEET = "NIFTY200"
OUTPUT_SHEET = "Trend Scanner"

CHART_OUTPUT_DIR = Path("docs/trend-charts")
CHART_BASE_URL = (
    "https://mkshsmwl10-web.github.io/"
    "-NSE-Auto-Sheet/docs/trend-charts"
)

# Enough history for Monthly trend calculation
DOWNLOAD_PERIOD = "5y"

CHART_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# GOOGLE LOGIN
# ============================================================

def connect_google_sheet():

    raw = os.environ.get("GCP_CREDENTIALS")

    if not raw:
        raise RuntimeError("GCP_CREDENTIALS secret not found.")

    info = json.loads(raw)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    credentials = Credentials.from_service_account_info(
        info,
        scopes=scopes,
    )

    client = gspread.authorize(credentials)

    return client.open_by_key(SPREADSHEET_ID)


# ============================================================
# SYMBOL CLEANING
# ============================================================

def clean_symbol(value):

    if value is None:
        return ""

    symbol = str(value).strip().upper()

    if symbol.endswith(".NS"):
        symbol = symbol[:-3]

    return symbol


# ============================================================
# FLATTEN YFINANCE DATA
# ============================================================

def clean_dataframe(df):

    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    required = [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
    ]

    for col in required:
        if col not in df.columns:
            if col == "Volume":
                df[col] = 0
            else:
                return pd.DataFrame()

    df = df.dropna(
        subset=["Open", "High", "Low", "Close"]
    )

    return df


# ============================================================
# DOWNLOAD DATA
# ============================================================

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

    except Exception as e:

        print(
            f"Download error {yahoo_symbol}: {e}"
        )

        return pd.DataFrame()


# ============================================================
# COMPLETED DAILY DATA
# ============================================================

def get_completed_daily(df):

    if df.empty:
        return df

    result = df.copy()

    # GitHub workflow normally runs after Indian market close.
    # yfinance daily bars are therefore treated as completed bars.
    return result


# ============================================================
# WEEKLY DATA
# ============================================================

def make_weekly(df):

    if df.empty:
        return df

    weekly = df.resample("W-FRI").agg(
        {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }
    )

    weekly = weekly.dropna(
        subset=["Open", "High", "Low", "Close"]
    )

    # Remove current incomplete week
    now = pd.Timestamp.now(tz="Asia/Kolkata")
    current_week_end = (
        now.normalize()
        + pd.offsets.Week(weekday=4)
    )

    current_week_end = current_week_end.tz_localize(None)

    weekly = weekly[
        weekly.index < current_week_end
    ]

    return weekly


# ============================================================
# MONTHLY DATA
# ============================================================

def make_monthly(df):

    if df.empty:
        return df

    try:
        monthly = df.resample("ME").agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )

    except Exception:

        monthly = df.resample("M").agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )

    monthly = monthly.dropna(
        subset=["Open", "High", "Low", "Close"]
    )

    # Remove current incomplete month
    now = pd.Timestamp.now(tz="Asia/Kolkata")
    current_period = now.tz_localize(None).to_period("M")

    monthly = monthly[
        monthly.index.to_period("M") < current_period
    ]

    return monthly


# ============================================================
# DYNAMIC OPEN TREND
# ============================================================

def calculate_dynamic_trend(df):

    """
    USER'S DYNAMIC OPEN -> CLOSE TREND

    Start:
        Green candle = POSITIVE
        Red candle   = NEGATIVE

    POSITIVE:
        Close < previous reference Open
        => NEGATIVE

    NEGATIVE:
        Close > previous reference Open
        => POSITIVE

    OPEN SHIFT:
        Every processed completed candle gives
        the reference Open for the NEXT candle.

    Therefore:

        trend does not change -> Open shifts

        trend changes ->
        trend-changing candle's Open also becomes
        the new reference for the next reversal.
    """

    if df is None or df.empty:
        return "NO DATA", None, None

    work = df.copy()

    work = work.dropna(
        subset=["Open", "Close"]
    )

    if len(work) < 2:
        return "NO DATA", None, None

    first_open = float(work.iloc[0]["Open"])
    first_close = float(work.iloc[0]["Close"])

    if first_close >= first_open:
        trend = "POSITIVE"
    else:
        trend = "NEGATIVE"

    reference_open = first_open
    last_change_date = work.index[0]

    for i in range(1, len(work)):

        candle_open = float(
            work.iloc[i]["Open"]
        )

        candle_close = float(
            work.iloc[i]["Close"]
        )

        changed = False

        if trend == "POSITIVE":

            if candle_close < reference_open:
                trend = "NEGATIVE"
                changed = True

        else:

            if candle_close > reference_open:
                trend = "POSITIVE"
                changed = True

        if changed:
            last_change_date = work.index[i]

        # Dynamic Open shift
        reference_open = candle_open

    return (
        trend,
        round(reference_open, 2),
        last_change_date,
    )


# ============================================================
# READ NIFTY200
# ============================================================

def read_nifty200(book):

    ws = book.worksheet(INPUT_SHEET)

    values = ws.get_all_values()

    if not values:
        raise RuntimeError(
            "NIFTY200 sheet is empty."
        )

    headers = [
        str(x).strip()
        for x in values[0]
    ]

    rows = values[1:]

    symbol_headers = [
        "NSE Code",
        "NSE CODE",
        "Symbol",
        "SYMBOL",
        "NSECode",
        "Code",
    ]

    symbol_index = None

    for name in symbol_headers:
        if name in headers:
            symbol_index = headers.index(name)
            break

    if symbol_index is None:
        symbol_index = 0

    name_headers = [
        "Stock Name",
        "STOCK NAME",
        "Name",
        "NAME",
        "Company",
        "Company Name",
    ]

    name_index = None

    for name in name_headers:
        if name in headers:
            name_index = headers.index(name)
            break

    stocks = []

    seen = set()

    for row in rows:

        if len(row) <= symbol_index:
            continue

        symbol = clean_symbol(
            row[symbol_index]
        )

        if not symbol:
            continue

        if symbol in seen:
            continue

        seen.add(symbol)

        if (
            name_index is not None
            and len(row) > name_index
            and str(row[name_index]).strip()
        ):
            stock_name = str(
                row[name_index]
            ).strip()

        else:
            stock_name = symbol

        stocks.append(
            {
                "name": stock_name,
                "code": symbol,
                "yahoo": f"{symbol}.NS",
            }
        )

    return stocks


# ============================================================
# CHART DATA
# ============================================================

def chart_bars(df, max_bars):

    if df is None or df.empty:
        return []

    work = df.tail(max_bars)

    bars = []

    for idx, row in work.iterrows():

        bars.append(
            {
                "time": idx.strftime("%Y-%m-%d"),
                "open": round(
                    float(row["Open"]), 2
                ),
                "high": round(
                    float(row["High"]), 2
                ),
                "low": round(
                    float(row["Low"]), 2
                ),
                "close": round(
                    float(row["Close"]), 2
                ),
            }
        )

    return bars


# ============================================================
# GENERATE INTERACTIVE CHART
# ============================================================

def generate_chart(
    code,
    stock_name,
    cmp_price,
    daily,
    weekly,
    monthly,
    daily_info,
    weekly_info,
    monthly_info,
):

    safe_code = (
        code.replace("^", "")
        .replace("/", "-")
        .replace(":", "-")
    )

    filename = (
        f"{safe_code}-trend.html"
    )

    filepath = (
        CHART_OUTPUT_DIR / filename
    )

    chart_url = (
        f"{CHART_BASE_URL}/{filename}?v=1"
    )

    payload = {
        "name": stock_name,
        "code": code,
        "cmp": cmp_price,

        "Daily": {
            "trend": daily_info[0],
            "reference": daily_info[1],
            "bars": chart_bars(
                daily, 180
            ),
        },

        "Weekly": {
            "trend": weekly_info[0],
            "reference": weekly_info[1],
            "bars": chart_bars(
                weekly, 120
            ),
        },

        "Monthly": {
            "trend": monthly_info[0],
            "reference": monthly_info[1],
            "bars": chart_bars(
                monthly, 60
            ),
        },
    }

    data_json = json.dumps(
        payload,
        ensure_ascii=False,
    )

    page = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>{stock_name} Trend Chart</title>

<script src="https://unpkg.com/lightweight-charts@5.0.8/dist/lightweight-charts.standalone.production.js"></script>

<style>

* {{
    box-sizing: border-box;
}}

body {{
    margin: 0;
    background: #0f172a;
    color: #e5e7eb;
    font-family:
        Arial,
        Helvetica,
        sans-serif;
}}

.header {{
    padding: 18px 22px;
    background: #111827;
    border-bottom:
        1px solid #334155;
}}

.title {{
    font-size: 24px;
    font-weight: 700;
}}

.subtitle {{
    margin-top: 6px;
    color: #94a3b8;
}}

.status-grid {{
    display: grid;
    grid-template-columns:
        repeat(3, 1fr);
    gap: 10px;
    padding: 14px 20px;
}}

.status {{
    padding: 12px;
    border-radius: 8px;
    text-align: center;
    font-weight: 700;
}}

.positive {{
    background: #14532d;
    color: #dcfce7;
}}

.negative {{
    background: #7f1d1d;
    color: #fee2e2;
}}

.nodata {{
    background: #374151;
}}

.toolbar {{
    padding: 8px 20px 14px;
}}

button {{
    border: 1px solid #475569;
    background: #1e293b;
    color: white;
    padding: 9px 17px;
    margin-right: 7px;
    border-radius: 6px;
    cursor: pointer;
    font-weight: 700;
}}

button.active {{
    background: #2563eb;
}}

.info {{
    padding: 0 20px 10px;
    color: #cbd5e1;
}}

#chart {{
    width: 100%;
    height: 650px;
}}

@media(max-width:700px) {{

    .status-grid {{
        grid-template-columns: 1fr;
    }}

    #chart {{
        height: 520px;
    }}
}}

</style>
</head>

<body>

<div class="header">

<div class="title">
{stock_name} ({code})
</div>

<div class="subtitle">
CMP: {cmp_price}
</div>

</div>

<div class="status-grid">

<div id="dailyStatus"
class="status">
Daily
</div>

<div id="weeklyStatus"
class="status">
Weekly
</div>

<div id="monthlyStatus"
class="status">
Monthly
</div>

</div>

<div class="toolbar">

<button id="Daily"
onclick="renderTF('Daily')">
1D
</button>

<button id="Weekly"
onclick="renderTF('Weekly')">
1W
</button>

<button id="Monthly"
onclick="renderTF('Monthly')">
1M
</button>

<button onclick="fitChart()">
Fit
</button>

</div>

<div class="info"
id="info"></div>

<div id="chart"></div>

<script>

const DATA = {data_json};

let chart = null;
let candleSeries = null;

function statusClass(trend) {{

    if (trend === "POSITIVE")
        return "status positive";

    if (trend === "NEGATIVE")
        return "status negative";

    return "status nodata";
}}

function setupStatuses() {{

    const d =
        document.getElementById(
            "dailyStatus"
        );

    const w =
        document.getElementById(
            "weeklyStatus"
        );

    const m =
        document.getElementById(
            "monthlyStatus"
        );

    d.className =
        statusClass(
            DATA.Daily.trend
        );

    w.className =
        statusClass(
            DATA.Weekly.trend
        );

    m.className =
        statusClass(
            DATA.Monthly.trend
        );

    d.innerHTML =
        "Daily<br>" +
        DATA.Daily.trend;

    w.innerHTML =
        "Weekly<br>" +
        DATA.Weekly.trend;

    m.innerHTML =
        "Monthly<br>" +
        DATA.Monthly.trend;
}}

function renderTF(tf) {{

    document
        .querySelectorAll("button")
        .forEach(
            b => b.classList.remove(
                "active"
            )
        );

    const btn =
        document.getElementById(tf);

    if (btn)
        btn.classList.add(
            "active"
        );

    const holder =
        document.getElementById(
            "chart"
        );

    holder.innerHTML = "";

    const item = DATA[tf];

    document.getElementById(
        "info"
    ).innerHTML =
        "<b>" + tf + " Trend:</b> "
        + item.trend
        + " &nbsp;&nbsp; "
        + "<b>Current Reference Open:</b> "
        + (
            item.reference === null
            ? "-"
            : item.reference
        );

    chart =
        LightweightCharts.createChart(
            holder,
            {{
                width:
                    holder.clientWidth,

                height:
                    holder.clientHeight,

                layout: {{
                    background: {{
                        color: "#0f172a"
                    }},
                    textColor:
                        "#cbd5e1"
                }},

                grid: {{
                    vertLines: {{
                        color: "#1e293b"
                    }},
                    horzLines: {{
                        color: "#1e293b"
                    }}
                }},

                crosshair: {{
                    mode: 1
                }},

                rightPriceScale: {{
                    borderColor:
                        "#475569"
                }},

                timeScale: {{
                    borderColor:
                        "#475569",
                    timeVisible: true
                }}
            }}
        );

    candleSeries =
        chart.addSeries(
            LightweightCharts
                .CandlestickSeries,
            {{
                upColor:
                    "#22c55e",

                downColor:
                    "#ef4444",

                borderVisible:
                    false,

                wickUpColor:
                    "#22c55e",

                wickDownColor:
                    "#ef4444"
            }}
        );

    candleSeries.setData(
        item.bars
    );

    if (
        item.reference !== null
    ) {{

        candleSeries.createPriceLine(
            {{
                price:
                    item.reference,

                color:
                    "#f59e0b",

                lineWidth: 2,

                lineStyle: 2,

                axisLabelVisible:
                    true,

                title:
                    "Reference Open"
            }}
        );
    }}

    chart
        .timeScale()
        .fitContent();
}}

function fitChart() {{

    if (chart)
        chart
            .timeScale()
            .fitContent();
}}

setupStatuses();

renderTF("Daily");

window.addEventListener(
    "resize",
    () => {{

        if (!chart)
            return;

        const holder =
            document.getElementById(
                "chart"
            );

        chart.applyOptions(
            {{
                width:
                    holder.clientWidth
            }}
        );
    }
);

</script>

</body>
</html>
"""

    filepath.write_text(
        page,
        encoding="utf-8",
    )

    return chart_url


# ============================================================
# SCAN ONE STOCK
# ============================================================

def scan_stock(stock):

    name = stock["name"]
    code = stock["code"]
    yahoo = stock["yahoo"]

    df = download_data(yahoo)

    if df.empty:
        return None

    daily = get_completed_daily(df)
    weekly = make_weekly(df)
    monthly = make_monthly(df)

    if daily.empty:
        return None

    cmp_price = round(
        float(daily.iloc[-1]["Close"]),
        2,
    )

    daily_info = calculate_dynamic_trend(
        daily
    )

    weekly_info = calculate_dynamic_trend(
        weekly
    )

    monthly_info = calculate_dynamic_trend(
        monthly
    )

    chart_url = generate_chart(
        code=code,
        stock_name=name,
        cmp_price=cmp_price,
        daily=daily,
        weekly=weekly,
        monthly=monthly,
        daily_info=daily_info,
        weekly_info=weekly_info,
        monthly_info=monthly_info,
    )

    return {
        "name": name,
        "code": code,
        "cmp": cmp_price,
        "daily": daily_info[0],
        "weekly": weekly_info[0],
        "monthly": monthly_info[0],
        "chart": chart_url,
    }


# ============================================================
# WRITE GOOGLE SHEET
# ============================================================

def write_sheet(book, results):

    try:
        ws = book.worksheet(
            OUTPUT_SHEET
        )

    except gspread.WorksheetNotFound:

        ws = book.add_worksheet(
            title=OUTPUT_SHEET,
            rows=500,
            cols=10,
        )

    ws.clear()

    headers = [
        "Stock Name",
        "NSE Code",
        "CMP",
        "Daily Trend",
        "Weekly Trend",
        "Monthly Trend",
        "Chart",
    ]

    values = [headers]

    for r in results:

        values.append(
            [
                r["name"],
                r["code"],
                r["cmp"],
                r["daily"],
                r["weekly"],
                r["monthly"],
                "OPEN CHART",
            ]
        )

    ws.update(
        range_name=(
            f"A1:G{len(values)}"
        ),
        values=values,
    )

    # Freeze first row AND first column
    ws.freeze(
        rows=1,
        cols=1,
    )

    # Header style
    ws.format(
        "A1:G1",
        {
            "backgroundColor": {
                "red": 0.10,
                "green": 0.18,
                "blue": 0.32,
            },
            "textFormat": {
                "foregroundColor": {
                    "red": 1,
                    "green": 1,
                    "blue": 1,
                },
                "bold": True,
                "fontSize": 11,
            },
            "horizontalAlignment":
                "CENTER",
            "verticalAlignment":
                "MIDDLE",
        },
    )

    # General formatting
    if len(values) > 1:

        ws.format(
            f"A2:G{len(values)}",
            {
                "verticalAlignment":
                    "MIDDLE",
            },
        )

        ws.format(
            f"B2:G{len(values)}",
            {
                "horizontalAlignment":
                    "CENTER",
            },
        )

    # NIFTY SPOT row highlight
    if len(values) >= 2:

        ws.format(
            "A2:G2",
            {
                "backgroundColor": {
                    "red": 0.88,
                    "green": 0.93,
                    "blue": 1.0,
                },
                "textFormat": {
                    "bold": True,
                },
            },
        )

    # POSITIVE / NEGATIVE colors
    requests = []

    sheet_id = ws.id

    for col_index in [3, 4, 5]:

        # POSITIVE
        requests.append(
            {
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [
                            {
                                "sheetId":
                                    sheet_id,
                                "startRowIndex":
                                    1,
                                "startColumnIndex":
                                    col_index,
                                "endColumnIndex":
                                    col_index + 1,
                            }
                        ],
                        "booleanRule": {
                            "condition": {
                                "type":
                                    "TEXT_EQ",
                                "values": [
                                    {
                                        "userEnteredValue":
                                            "POSITIVE"
                                    }
                                ],
                            },
                            "format": {
                                "backgroundColor": {
                                    "red": 0.82,
                                    "green": 0.95,
                                    "blue": 0.84,
                                },
                                "textFormat": {
                                    "foregroundColor": {
                                        "red": 0.05,
                                        "green": 0.40,
                                        "blue": 0.16,
                                    },
                                    "bold": True,
                                },
                            },
                        },
                    },
                    "index": 0,
                }
            }
        )

        # NEGATIVE
        requests.append(
            {
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [
                            {
                                "sheetId":
                                    sheet_id,
                                "startRowIndex":
                                    1,
                                "startColumnIndex":
                                    col_index,
                                "endColumnIndex":
                                    col_index + 1,
                            }
                        ],
                        "booleanRule": {
                            "condition": {
                                "type":
                                    "TEXT_EQ",
                                "values": [
                                    {
                                        "userEnteredValue":
                                            "NEGATIVE"
                                    }
                                ],
                            },
                            "format": {
                                "backgroundColor": {
                                    "red": 1.0,
                                    "green": 0.85,
                                    "blue": 0.85,
                                },
                                "textFormat": {
                                    "foregroundColor": {
                                        "red": 0.65,
                                        "green": 0.05,
                                        "blue": 0.05,
                                    },
                                    "bold": True,
                                },
                            },
                        },
                    },
                    "index": 0,
                }
            }
        )

    # Column widths
    widths = {
        0: 190,
        1: 110,
        2: 100,
        3: 120,
        4: 120,
        5: 130,
        6: 130,
    }

    for col, pixels in widths.items():

        requests.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId":
                            sheet_id,
                        "dimension":
                            "COLUMNS",
                        "startIndex":
                            col,
                        "endIndex":
                            col + 1,
                    },
                    "properties": {
                        "pixelSize":
                            pixels
                    },
                    "fields":
                        "pixelSize",
                }
            }
        )

    book.batch_update(
        {
            "requests": requests
        }
    )

    # Clickable OPEN CHART formulas
    for row_number, r in enumerate(
        results,
        start=2,
    ):

        formula = (
            '=HYPERLINK("'
            + r["chart"]
            + '","OPEN CHART")'
        )

        ws.update_acell(
            f"G{row_number}",
            formula,
        )

    # Chart column styling
    if len(values) > 1:

        ws.format(
            f"G2:G{len(values)}",
            {
                "textFormat": {
                    "bold": True,
                    "foregroundColor": {
                        "red": 0.05,
                        "green": 0.30,
                        "blue": 0.75,
                    },
                },
                "horizontalAlignment":
                    "CENTER",
            },
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print(
        "NIFTY200 + NIFTY SPOT "
        "DYNAMIC TREND SCANNER"
    )
    print("=" * 70)

    book = connect_google_sheet()

    stocks = read_nifty200(book)

    # NIFTY SPOT always first
    all_items = [
        {
            "name": "NIFTY 50 SPOT",
            "code": "^NSEI",
            "yahoo": "^NSEI",
        }
    ]

    all_items.extend(stocks)

    print(
        f"Total instruments: "
        f"{len(all_items)}"
    )

    results = []

    for i, stock in enumerate(
        all_items,
        start=1,
    ):

        print(
            f"[{i}/{len(all_items)}] "
            f"{stock['code']}"
        )

        try:

            result = scan_stock(
                stock
            )

            if result:

                results.append(
                    result
                )

                print(
                    "  "
                    f"D={result['daily']} | "
                    f"W={result['weekly']} | "
                    f"M={result['monthly']}"
                )

            else:

                print(
                    "  NO DATA"
                )

        except Exception as e:

            print(
                f"  ERROR: {e}"
            )

        time.sleep(0.10)

    write_sheet(
        book,
        results,
    )

    print("=" * 70)
    print(
        f"Completed: "
        f"{len(results)} instruments"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
