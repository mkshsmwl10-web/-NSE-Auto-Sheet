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
COLUMNS = ['Rank','Stock Name','NSE Code','CMP','SMA 9','SMA 18','SMA 50','SMA 200','SMA 50 Slope','50 Slope %','SMA 200 Distance %','Vol Ratio','RSI 14','20D Breakout','Score','Pullback Signal','Support SMA','Candle Pattern','Entry Above','Stop Below','Chart Link']

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

def pullback_setup(df):
    """Uptrend SMA touch followed by bullish rejection candle, latest daily bar only."""
    empty={'signal':'NO SETUP','sma':'','candle':'','entry':'','stop':'','date':''}
    if len(df)<202: return empty
    bar,prev=df.iloc[-1],df.iloc[-2]
    op,hi,lo,cl=(float(bar[k]) for k in ('Open','High','Low','Close'))
    prev_op,prev_cl=float(prev['Open']),float(prev['Close'])
    span=hi-lo
    if span<=0: return empty
    body=abs(cl-op)
    high_close=(hi-cl)/span<=.25
    strong=(cl>op and body/span>=.55 and high_close)
    engulf=(prev_cl<prev_op and cl>op and op<=prev_cl and cl>=prev_op and high_close)
    hammer=(cl>op and body>0 and (min(op,cl)-lo)>=1.8*body and high_close)
    candle='BULLISH ENGULFING' if engulf else 'HAMMER' if hammer else 'STRONG GREEN' if strong else ''
    touches=[]
    for n in (9,18,50,200):
        col=f'SMA {n}'
        for age in (0,1,2):
            b=df.iloc[-1-age]
            level=float(b[col])
            if pd.isna(level) or level<=0: continue
            low=float(b['Low'])
            if level*.99<=low<=level*1.01 and float(b['High'])>=level and cl>level:
                touches.append((age,abs(low/level-1),n))
                break
    if not touches: return empty
    touches.sort()
    age,_,n=touches[0]
    volume=float(bar['Vol Ratio']) if pd.notna(bar['Vol Ratio']) else 0.
    rsi=float(bar['RSI 14']) if pd.notna(bar['RSI 14']) else 0.
    stop=min(float(df.iloc[-1-i]['Low']) for i in range(age+1))
    confirmed=bool(candle and cl>prev_cl and volume>=.8 and rsi>=50 and stop<hi)
    return {
        'signal':'BUY OPPORTUNITY' if confirmed else 'PULLBACK WATCH',
        'sma':f'SMA {n}','candle':candle or 'WAIT CANDLE',
        'entry':round(hi,2) if confirmed else '',
        'stop':round(stop,2) if confirmed else '',
        'date':str(df.index[-1].date()) if confirmed else ''
    }


def chart_html(name, code, df):
    """Daily candlestick, SMA overlay and volume with responsive time-range buttons."""
    shown = df.tail(320)
    dates = [d.strftime('%Y-%m-%d') for d in shown.index]
    def numbers(col):
        return [None if pd.isna(v) else round(float(v), 3) for v in shown[col]]
    traces = [{
        'type': 'candlestick', 'name': 'Candles', 'x': dates,
        'open': numbers('Open'), 'high': numbers('High'),
        'low': numbers('Low'), 'close': numbers('Close'),
        'increasing': {'line': {'color': '#16a34a'}},
        'decreasing': {'line': {'color': '#dc2626'}},
        'xaxis': 'x', 'yaxis': 'y'
    }]
    for col, color, width in [
        ('SMA 9', '#f59e0b', 1.8),
        ('SMA 18', '#8b5cf6', 1.8),
        ('SMA 50', '#16a34a', 2.5),
        ('SMA 200', '#dc2626', 2.5)
    ]:
        traces.append({
            'type': 'scatter', 'mode': 'lines',
            'name': col + ' (' + format(float(df[col].iloc[-1]), ',.2f') + ')',
            'x': dates, 'y': numbers(col),
            'line': {'color': color, 'width': width}, 'xaxis': 'x', 'yaxis': 'y'
        })
    colors = ['#86efac' if c >= o else '#fca5a5'
              for o, c in zip(shown['Open'], shown['Close'])]
    traces.append({
        'type': 'bar', 'name': 'Volume', 'x': dates,
        'y': numbers('Volume'), 'marker': {'color': colors},
        'xaxis': 'x2', 'yaxis': 'y2'
    })
    last = df.iloc[-1]
    previous = df.iloc[-2]
    pct = (float(last['SMA 50']) / float(previous['SMA 50']) - 1) * 100
    window = df.iloc[-61:-1]
    details = {
        'cmp': round(float(last['Close']), 2),
        'sma50': round(float(last['SMA 50']), 2),
        'sma200': round(float(last['SMA 200']), 2),
        'slope': round(pct, 4),
        'priceAbove': bool(last['Close'] > last['SMA 200']),
        'support': round(float(window['Low'].min()), 2),
        'resistance': round(float(window['High'].max()), 2),
        'rsi': round(float(last['RSI 14']), 2) if pd.notna(last['RSI 14']) else None,
        'volratio': round(float(last['Vol Ratio']), 2) if pd.notna(last['Vol Ratio']) else None,
        'breakout': bool(last['Close'] > df['High'].iloc[-21:-1].max()),
        'alignment': bool(last['SMA 9'] > last['SMA 18'] > last['SMA 50'])
    }
    setup = pullback_setup(df)
    details.update({'pullback':setup['signal'],'supportSma':setup['sma'],
                    'candle':setup['candle'],'entry':setup['entry'],'stop':setup['stop']})
    if setup['signal']=='BUY OPPORTUNITY':
        traces.append({
            'type':'scatter','mode':'markers+text','name':'Pullback Opportunity',
            'x':[setup['date']],'y':[setup['stop']],
            'text':['BUY SETUP'],'textposition':'bottom center',
            'marker':{'color':'#16a34a','size':16,'symbol':'triangle-up'},
            'xaxis':'x','yaxis':'y'
        })
    payload = json.dumps({'traces': traces, 'details': details}, separators=(',', ':'))
    title = html.escape(f'{name} ({code}) — Advanced Daily SMA Chart')
    page = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{font:14px system-ui,sans-serif;background:#f1f5f9;color:#172033;margin:0}
main{max-width:1550px;margin:auto;padding:18px}
h1{font-size:24px}p{color:#64748b}
#metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}
.metric{background:white;border-radius:12px;padding:12px;border:1px solid #e2e8f0}
.metric small{display:block;color:#64748b;margin-bottom:5px}.metric strong{font-size:19px}
.green{color:#15803d}.red{color:#b91c1c}
.controls{display:flex;flex-wrap:wrap;gap:9px;margin:10px 0}
button{background:white;border:1px solid #cbd5e1;border-radius:9px;padding:9px 13px;cursor:pointer}
button.sel{border-color:#2563eb;background:#dbeafe}
#plot{height:75vh;min-height:550px;background:white;border-radius:12px}
.note{font-size:12px;line-height:1.5}
</style></head><body><main><h1>__TITLE__</h1>
<p>Daily candles • SMA 9 orange • SMA 18 purple • SMA 50 green • SMA 200 red • Volume</p>
<div id="metrics"></div>
<div class="controls">
<button onclick="range(63,this)">3 months</button>
<button onclick="range(126,this)" class="sel">6 months</button>
<button onclick="range(252,this)">1 year</button>
<button onclick="range(320,this)">All</button>
<button onclick="levels(this)" class="sel">Support / Resistance</button>
</div><div id="plot"></div>
<p class="note">Support and resistance are indicative previous-60-session low/high. Not live buy/exit levels or broker orders. SMA slope is based on the latest two daily SMA50 values.</p>
</main><script>
const data=__DATA__;
const t=data.traces,d=data.details;
const m=(name,value,style='')=>'<div class="metric"><small>'+name+'</small><strong class="'+style+'">'+value+'</strong></div>';
document.getElementById('metrics').innerHTML=
m('Latest close','₹'+d.cmp.toLocaleString('en-IN'))+
m('SMA 50','₹'+d.sma50.toLocaleString('en-IN'))+
m('SMA 200','₹'+d.sma200.toLocaleString('en-IN'))+
m('50 SMA slope',d.slope.toFixed(4)+'%',d.slope>0?'green':'red')+
m('Above SMA 200',d.priceAbove?'YES':'NO',d.priceAbove?'green':'red')+
m('60-day low','₹'+d.support.toLocaleString('en-IN'))+
m('60-day high','₹'+d.resistance.toLocaleString('en-IN'))+
m('Volume Ratio',d.volratio===null?'N/A':d.volratio.toFixed(2)+'x')+
m('RSI 14',d.rsi===null?'N/A':d.rsi.toFixed(1))+
m('20D Breakout',d.breakout?'YES':'NO',d.breakout?'green':'')+
m('SMA Alignment',d.alignment?'9 > 18 > 50':'Mixed',d.alignment?'green':'')+
m('Pullback Signal',d.pullback,d.pullback==='BUY OPPORTUNITY'?'green':'')+
m('Support SMA',d.supportSma||'—')+
m('Candle',d.candle||'—')+
m('Entry trigger',d.entry?'Above ₹'+d.entry:'—')+
m('Setup stop',d.stop?'Below ₹'+d.stop:'—');
const dates=t[0].x,last=dates[dates.length-1];
let showLevels=true;
const shapes=[
{type:'line',xref:'x',x0:dates[0],x1:last,yref:'y',y0:d.support,y1:d.support,line:{color:'#0891b2',dash:'dot',width:1.5}},
{type:'line',xref:'x',x0:dates[0],x1:last,yref:'y',y0:d.resistance,y1:d.resistance,line:{color:'#ea580c',dash:'dot',width:1.5}}
];
const layout={
margin:{l:70,r:30,t:55,b:45},paper_bgcolor:'#fff',plot_bgcolor:'#fff',
hovermode:'x unified',legend:{orientation:'h',y:1.09,x:0},
xaxis:{type:'date',domain:[0,1],anchor:'y',rangeslider:{visible:false},rangebreaks:[{bounds:['sat','mon']}],range:[dates[Math.max(0,dates.length-126)],last]},
yaxis:{domain:[.28,1],title:'Price (INR)',gridcolor:'#e2e8f0'},
xaxis2:{type:'date',domain:[0,1],anchor:'y2',matches:'x',rangebreaks:[{bounds:['sat','mon']}]},
yaxis2:{domain:[0,.21],title:'Volume',rangemode:'tozero',gridcolor:'#f1f5f9'},
shapes:shapes,dragmode:'zoom'
};
function range(n,btn){
const from=dates[Math.max(0,dates.length-n)];
Plotly.relayout('plot',{'xaxis.range':[from,last]});
document.querySelectorAll('.controls button:nth-child(-n+4)').forEach(b=>b.classList.remove('sel'));
btn.classList.add('sel');
}
function levels(btn){
showLevels=!showLevels;Plotly.relayout('plot',{shapes:showLevels?shapes:[]});
btn.classList.toggle('sel',showLevels);
}
if(window.Plotly) Plotly.newPlot('plot',t,layout,{responsive:true,displaylogo:false,scrollZoom:true});
else document.getElementById('plot').textContent='Plotly CDN unavailable. Check your connection.';
</script></body></html>"""
    return page.replace('__TITLE__', title).replace('__DATA__', payload)


def scan(name,code):
    raw=yf.Ticker(code+'.NS').history(period='3y',interval='1d',auto_adjust=False,actions=False)
    if raw is None or raw.empty or len(raw)<202: return None
    close=pd.to_numeric(raw['Close'],errors='coerce').dropna()
    if len(close)<202: return None
    df=pd.DataFrame(index=close.index)
    df['Close']=close
    for field in ('Open', 'High', 'Low', 'Volume'):
        df[field] = pd.to_numeric(raw[field], errors='coerce').reindex(df.index)
    if df[['Open', 'High', 'Low']].isna().any().any():
        return None
    df['Volume'] = df['Volume'].fillna(0)
    for n in (9,18,50,200):
        df[f'SMA {n}'] = close.rolling(n, min_periods=n).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rs = gain / loss.replace(0, float('nan'))
    df['RSI 14'] = (100 - 100/(1+rs)).fillna(100).where(loss != 0, 100)
    avg_vol = df['Volume'].shift(1).rolling(20, min_periods=20).mean()
    df['Vol Ratio'] = df['Volume'] / avg_vol.replace(0, float('nan'))

    latest=df.iloc[-1]; prev=df.iloc[-2]
    if pd.isna(latest['SMA 200']) or pd.isna(prev['SMA 50']): return None
    if not (latest['Close']>latest['SMA 200'] and latest['SMA 50']>prev['SMA 50']): return None
    CHART_DIR.mkdir(parents=True,exist_ok=True)
    filename=re.sub(r'[^A-Za-z0-9_-]','-',code)+'-sma-chart.html'
    (CHART_DIR/filename).write_text(chart_html(name,code,df),encoding='utf-8')
    url=f'{CHART_BASE}/{filename}?v=5'
    slope_pct = (float(latest['SMA 50'])/float(prev['SMA 50'])-1)*100
    distance_pct = (float(latest['Close'])/float(latest['SMA 200'])-1)*100
    vol_ratio = float(latest['Vol Ratio']) if pd.notna(latest['Vol Ratio']) else 0.0
    rsi = float(latest['RSI 14']) if pd.notna(latest['RSI 14']) else 50.0
    setup = pullback_setup(df)
    alignment = bool(latest['SMA 9'] > latest['SMA 18'] > latest['SMA 50'])
    breakout = bool(latest['Close'] > df['High'].iloc[-21:-1].max())
    # Transparent 100-point score: slope 40, alignment 25, volume 20, RSI 15.
    # Slope: 0.5% daily = full 40; volume: 2x prior 20 days = full 20.
    slope_points = min(max(slope_pct / 0.5, 0), 1) * 40
    align_points = 25 if alignment else 0
    volume_points = min(max(vol_ratio/2, 0), 1) * 20
    rsi_points = min(max((rsi-40)/30, 0), 1) * 15
    score = round(slope_points + align_points + volume_points + rsi_points, 2)
    return {'Stock Name':name,'NSE Code':code,'CMP':round(float(latest['Close']),2),
            'SMA 9':round(float(latest['SMA 9']),2),'SMA 18':round(float(latest['SMA 18']),2),
            'SMA 50':round(float(latest['SMA 50']),2),'SMA 200':round(float(latest['SMA 200']),2),
            'SMA 50 Slope':'UP',
            '50 Slope %':round(slope_pct,4),
            'SMA 200 Distance %':round(distance_pct,2),
            'Vol Ratio':round(vol_ratio,2),
            'RSI 14':round(rsi,2),
            '20D Breakout':'YES' if breakout else 'NO',
            'Score':score,
            'Pullback Signal':setup['signal'],'Support SMA':setup['sma'],
            'Candle Pattern':setup['candle'],'Entry Above':setup['entry'],
            'Stop Below':setup['stop'],'Chart Link':url}

def write_output(book, rows):
    """Keep ALL qualifying stocks, sorted by score and ranked 1..N."""
    try:
        ws = book.worksheet(FINAL_SHEET)
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(title=FINAL_SHEET, rows=1000, cols=len(COLUMNS))
    try:
        book.batch_update({'requests':[{'unmergeCells':{'range':{'sheetId':ws.id}}}]})
    except Exception as exc:
        print('Unmerge warning:', exc)
    ws.clear()
    ws.resize(rows=max(100,len(rows)+2), cols=len(COLUMNS))
    values = [COLUMNS] + [[r.get(c,'') for c in COLUMNS] for r in rows]
    end_col = 'U'
    ws.update(values, range_name=f'A1:{end_col}{len(values)}', value_input_option='RAW')
    ws.freeze(rows=1, cols=3)
    ws.format(f'A1:{end_col}1', {
        'backgroundColor':{'red':0.80,'green':0.90,'blue':0.99},
        'textFormat':{'bold':True,'fontSize':10},
        'horizontalAlignment':'CENTER','wrapStrategy':'WRAP'
    })
    if rows:
        last_row = len(values)
        ws.format(f'D2:K{last_row}',{
            'numberFormat':{'type':'NUMBER','pattern':'0.00'}
        })
        ws.format(f'M2:M{last_row}',{
            'numberFormat':{'type':'NUMBER','pattern':'0.00'}
        })
        ws.format(f'O2:O{last_row}',{
            'backgroundColor':{'red':0.88,'green':0.96,'blue':0.88},
            'textFormat':{'bold':True},
            'numberFormat':{'type':'NUMBER','pattern':'0.00'}
        })
        ws.format(f'A2:A{last_row}',{
            'backgroundColor':{'red':0.9,'green':0.94,'blue':1.0},
            'textFormat':{'bold':True}
        })
        requests = []
        for i,row in enumerate(rows,start=2):
            requests.append({'updateCells':{
                'range':{'sheetId':ws.id,'startRowIndex':i-1,'endRowIndex':i,
                         'startColumnIndex':20,'endColumnIndex':21},
                'rows':[{'values':[{
                    'userEnteredValue':{'stringValue':'OPEN CHART'},
                    'textFormatRuns':[{'startIndex':0,'format':{
                        'link':{'uri':row['Chart Link']},'underline':True
                    }}]
                }]}],
                'fields':'userEnteredValue,textFormatRuns'
            }})
        for i in range(0,len(requests),100):
            book.batch_update({'requests':requests[i:i+100]})
    if rows:
        ws.format(f'Q2:Q{len(rows)+1}', {
            'backgroundColor':{'red':0.91,'green':0.97,'blue':0.91},
            'textFormat':{'bold':True}
        })
        ws.format(f'T2:U{len(rows)+1}', {
            'numberFormat':{'type':'NUMBER','pattern':'0.00'}
        })
    print(f'Final List updated: {len(rows)} qualifying stocks, all ranked, {len(COLUMNS)} columns')


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
    rows.sort(key=lambda r: (-r['Score'], -r['50 Slope %'], r['NSE Code']))
    for rank, row in enumerate(rows, 1):
        row['Rank'] = rank
    write_output(book,rows)
    print('Charts generated in',CHART_DIR,'— ensure workflow publishes docs/charts to GitHub Pages.')

if __name__=='__main__': main()
