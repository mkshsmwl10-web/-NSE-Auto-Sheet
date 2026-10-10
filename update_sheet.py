#!/usr/bin/env python3
"""NSE Auto Sheet: SMA 9/18/50/200 scanner, Final List and HTML charts.
Filter: latest price > SMA200 and SMA50 latest > SMA50 previous.
NIFTY200 input worksheet is read-only. Requires GCP_CREDENTIALS.
"""
import os, json, re, html, time
from pathlib import Path
import pandas as pd
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials

SHEET_ID = os.getenv('SPREADSHEET_ID', '1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E')
INPUT_SHEET = os.getenv('INPUT_SHEET', 'NIFTY200')
FINAL_SHEET = os.getenv('FINAL_LIST_SHEET', 'Final List')
CHART_DIR = Path(os.getenv('CHART_OUTPUT_DIR', 'docs/charts'))
CHART_BASE = os.getenv('CHART_BASE_URL', 'https://mkshsmwl10-web.github.io/-NSE-Auto-Sheet/docs/charts').rstrip('/')
COLUMNS = ['Stock Name','NSE Code','CMP','SMA 9','SMA 18','SMA 50','SMA 200','SMA 50 Slope','Chart Link']

def google_book():
    raw = os.environ.get('GCP_CREDENTIALS','').strip()
    if not raw: raise RuntimeError('GCP_CREDENTIALS missing')
    scopes = ['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive']
    if raw.startswith('{'):
        creds = Credentials.from_service_account_info(json.loads(raw), scopes=scopes)
    else:
        creds = Credentials.from_service_account_file(raw, scopes=scopes)
    return gspread.authorize(creds).open_by_key(SHEET_ID)

def get_stocks(book):
    values = book.worksheet(INPUT_SHEET).get_all_values()
    if not values: raise RuntimeError('NIFTY200 input sheet empty')
    headers = [re.sub(r'\s+',' ',v.strip().lower()) for v in values[0]]
    def col(options, fallback):
        return next((headers.index(x) for x in options if x in headers), fallback)
    ci = col(['nse code','nse_code','nsecode','symbol','stock code','code'], 0)
    ni = col(['stock name','stock_name','company name','company','name','stock'], None)
    stocks, seen = [], set()
    for line in values[1:]:
        if len(line)<=ci: continue
        code=line[ci].strip().upper().removesuffix('.NS')
        if not re.fullmatch(r'[A-Z0-9&._-]+',code) or code in seen: continue
        name=line[ni].strip() if ni is not None and ni<len(line) else code
        stocks.append((name or code,code)); seen.add(code)
    return stocks

def chart_html(name, code, df):
    # Plotly CDN is loaded when the chart is opened in a browser.
    # A single source of SMA calculations is used by sheet and chart.
    last=df.tail(320).copy()
    x=[d.strftime('%Y-%m-%d') for d in last.index]
    traces=[]
    for col,color,width in [('Close','#334155',2),('SMA 9','#f59e0b',1.8),('SMA 18','#8b5cf6',1.8),('SMA 50','#16a34a',2.4),('SMA 200','#dc2626',2.4)]:
        vals=[None if pd.isna(v) else round(float(v),3) for v in last[col]]
        traces.append({'x':x,'y':vals,'name':col,'type':'scatter','mode':'lines','line':{'color':color,'width':width}})
    title=html.escape(f'{name} ({code}) — Daily SMA Chart')
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'''+title+'''</title><script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script><style>body{font-family:Arial,sans-serif;margin:0;background:#f8fafc;color:#0f172a}.wrap{max-width:1400px;margin:auto;padding:18px}#chart{height:75vh;min-height:460px;background:white;border-radius:12px}.note{color:#475569}</style></head><body><div class="wrap"><h2>'''+title+'''</h2><p class="note">Daily close with SMA 9 (amber), SMA 18 (purple), SMA 50 (green), SMA 200 (red).</p><div id="chart"></div></div><script>const traces='''+json.dumps(traces,separators=(',',':'))+''';Plotly.newPlot('chart',traces,{hovermode:'x unified',legend:{orientation:'h'},xaxis:{rangeslider:{visible:true}},yaxis:{title:'Price (INR)'},margin:{l:65,r:25,t:30,b:55},paper_bgcolor:'#fff',plot_bgcolor:'#fff'},{responsive:true,displaylogo:false});</script></body></html>'''

def scan(name,code):
    raw=yf.Ticker(code+'.NS').history(period='3y',interval='1d',auto_adjust=False,actions=False)
    if raw is None or raw.empty or len(raw)<202: return None
    close=pd.to_numeric(raw['Close'],errors='coerce').dropna()
    if len(close)<202: return None
    df=pd.DataFrame(index=close.index)
    df['Close']=close
    for n in (9,18,50,200): df[f'SMA {n}']=close.rolling(n,min_periods=n).mean()
    latest=df.iloc[-1]; prev=df.iloc[-2]
    if pd.isna(latest['SMA 200']) or pd.isna(prev['SMA 50']): return None
    if not (latest['Close']>latest['SMA 200'] and latest['SMA 50']>prev['SMA 50']): return None
    CHART_DIR.mkdir(parents=True,exist_ok=True)
    filename=re.sub(r'[^A-Za-z0-9_-]','-',code)+'-sma-chart.html'
    (CHART_DIR/filename).write_text(chart_html(name,code,df),encoding='utf-8')
    url=f'{CHART_BASE}/{filename}?v=1'
    return {'Stock Name':name,'NSE Code':code,'CMP':round(float(latest['Close']),2),
            'SMA 9':round(float(latest['SMA 9']),2),'SMA 18':round(float(latest['SMA 18']),2),
            'SMA 50':round(float(latest['SMA 50']),2),'SMA 200':round(float(latest['SMA 200']),2),
            'SMA 50 Slope':'UP','Chart Link':url}

def write_output(book,rows):
    try: ws=book.worksheet(FINAL_SHEET)
    except gspread.WorksheetNotFound: ws=book.add_worksheet(title=FINAL_SHEET,rows=1000,cols=len(COLUMNS))
    # Old merged cells and old columns must not survive schema migration.
    try:
        book.batch_update({'requests':[{'unmergeCells':{'range':{'sheetId':ws.id}}}]})
    except Exception as exc: print('Unmerge warning:',exc)
    ws.clear()
    ws.resize(rows=max(100,len(rows)+2),cols=len(COLUMNS))
    values=[COLUMNS]+[[r.get(c,'') for c in COLUMNS] for r in rows]
    ws.update(values,range_name=f'A1:I{len(values)}',value_input_option='RAW')
    ws.freeze(rows=1,cols=2)
    ws.format('A1:I1',{'backgroundColor':{'red':0.82,'green':0.91,'blue':0.98},'textFormat':{'bold':True,'fontSize':10},'horizontalAlignment':'CENTER','wrapStrategy':'WRAP'})
    if rows:
        ws.format(f'C2:G{len(values)}',{'numberFormat':{'type':'NUMBER','pattern':'0.00'},'horizontalAlignment':'RIGHT'})
        ws.format(f'H2:H{len(values)}',{'backgroundColor':{'red':0.85,'green':0.96,'blue':0.87},'textFormat':{'bold':True}})
        requests=[]
        for i,r in enumerate(rows,2):
            requests.append({'updateCells':{'range':{'sheetId':ws.id,'startRowIndex':i-1,'endRowIndex':i,'startColumnIndex':8,'endColumnIndex':9},'rows':[{'values':[{'userEnteredValue':{'stringValue':'OPEN CHART'},'textFormatRuns':[{'startIndex':0,'format':{'link':{'uri':r['Chart Link']},'underline':True}}]}]}],'fields':'userEnteredValue,textFormatRuns'}})
        for i in range(0,len(requests),100): book.batch_update({'requests':requests[i:i+100]})
    print(f'Final List updated: {len(rows)} qualifying stocks; 9 columns')

def main():
    book=google_book()
    stocks=get_stocks(book)
    print(f'Scanning {len(stocks)} stocks for CMP>SMA200 and SMA50 slope UP')
    rows=[]
    for i,(name,code) in enumerate(stocks,1):
        try:
            result=scan(name,code)
            if result: rows.append(result); print(f'  PASS {code}')
        except Exception as exc: print(f'  ERROR {code}: {exc}')
        if i%50==0: print(f'Processed {i}/{len(stocks)}')
    rows.sort(key=lambda r:(-(r['CMP']/r['SMA 200']-1),r['NSE Code']))
    write_output(book,rows)
    print('Charts generated in',CHART_DIR,'— ensure workflow publishes docs/charts to GitHub Pages.')

if __name__=='__main__': main()
