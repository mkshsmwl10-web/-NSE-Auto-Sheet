#!/usr/bin/env python3
"""NSE Auto Sheet: SMA 9/18/50/200 scanner, Final List and HTML charts.
Filter: latest price > SMA200 (no mandatory SMA50 slope rule).
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
COLUMNS = ['Rank','Stock Name','NSE Code','CMP','SMA 50','SMA 200','SMA 50 Slope','SMA 200 Distance %','RS 1M vs NIFTY %','RS 55D vs NIFTY %','Cumulative RS','Score','ST Trend','Supertrend 10,3','BUY Level','Stop Below','Supertrend Signal','Chart Link']

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

def supertrend_setup(df, atr_period=10, multiplier=3.0):
    """Daily Supertrend 10,3. BUY whenever the current trend is UP.
    Stop is 95% of latest SMA200 for all BUY rows; no SELL signals generated.
    """
    high,low,close=df['High'],df['Low'],df['Close']
    prev_close=close.shift(1)
    true_range=pd.concat([(high-low).abs(),
                          (high-prev_close).abs(),
                          (low-prev_close).abs()],axis=1).max(axis=1)
    # Wilder ATR with SMA-seeded initial observation.
    atr=pd.Series(float('nan'),index=df.index,dtype='float64')
    if len(df)<max(202,atr_period+2):
        return {'signal':'','trend':'','line':None,'entry':'','stop':'','date':''}
    start=atr_period-1
    atr.iloc[start]=float(true_range.iloc[:atr_period].mean())
    for i in range(start+1,len(df)):
        atr.iloc[i]=(atr.iloc[i-1]*(atr_period-1)+float(true_range.iloc[i]))/atr_period
    upper=(high+low)/2+multiplier*atr
    lower=(high+low)/2-multiplier*atr
    final_upper=upper.copy()
    final_lower=lower.copy()
    bullish=[False]*len(df)
    for i in range(start+1,len(df)):
        prev=i-1
        final_upper.iloc[i]=(upper.iloc[i] if upper.iloc[i]<final_upper.iloc[prev]
                             or close.iloc[prev]>final_upper.iloc[prev]
                             else final_upper.iloc[prev])
        final_lower.iloc[i]=(lower.iloc[i] if lower.iloc[i]>final_lower.iloc[prev]
                             or close.iloc[prev]<final_lower.iloc[prev]
                             else final_lower.iloc[prev])
        # Compare against the PREVIOUS finalized band on trend changes;
        # current bands can move with the signal candle and delay flips.
        if bullish[prev]:
            bullish[i]=bool(close.iloc[i]>=final_lower.iloc[prev])
        else:
            bullish[i]=bool(close.iloc[i]>final_upper.iloc[prev])
    trend='UP' if bullish[-1] else 'DOWN'
    value=float(final_lower.iloc[-1] if bullish[-1] else final_upper.iloc[-1])
    # Every stock currently in an UP Supertrend receives BUY status.
    # All scan results are already restricted to Close > SMA200.
    buy=bool(bullish[-1] and float(close.iloc[-1])>float(df['SMA 200'].iloc[-1]))
    # Highest candle HIGH throughout the active green Supertrend run,
    # starting with the latest red-to-green flip candle (inclusive).
    # A green run may last one day or many days.
    buy_level = ''
    buy_high_date = ''
    green_start_date = ''
    if buy:
        green_start=len(df)-1
        while green_start>start+1 and bullish[green_start-1]:
            green_start-=1
        active_high=high.iloc[green_start:]
        highest_index=int(active_high.to_numpy().argmax())+green_start
        buy_level=round(float(high.iloc[highest_index]),2)
        buy_high_date=str(df.index[highest_index].date())
        green_start_date=str(df.index[green_start].date())
    # Historical chart lines use exactly the same bands and trend states
    # as the latest signal. None breaks the line when trend changes.
    history_up=[round(float(final_lower.iloc[i]),3) if bullish[i] and i>start
                else None for i in range(len(df))]
    history_down=[round(float(final_upper.iloc[i]),3) if not bullish[i] and i>start
                  else None for i in range(len(df))]
    return {'signal':'BUY' if buy else '',
            'trend':trend,'line':round(value,2),
            'entry':buy_level,
            'stop':round(float(df['SMA 200'].iloc[-1])*0.95,2) if buy else '',
            'date':buy_high_date,
            'green_start_date':green_start_date,
            'history_up':history_up,'history_down':history_down}



def relative_strength(stock_close, benchmark_close, sessions):
    """Stock minus NIFTY return in percentage points over N shared sessions."""
    if benchmark_close is None:
        return None
    stock = stock_close.copy()
    bench = benchmark_close.copy()
    stock.index = pd.to_datetime(stock.index).tz_localize(None).normalize()
    bench.index = pd.to_datetime(bench.index).tz_localize(None).normalize()
    common = pd.concat([stock.rename('stock'), bench.rename('nifty')],
                       axis=1, join='inner').dropna().sort_index()
    if len(common) < sessions+1 or common.index[-1] != stock.index[-1]:
        return None
    first,last=common.iloc[-sessions-1],common.iloc[-1]
    if min(first['stock'],first['nifty'])<=0:
        return None
    return round(float((last['stock']/first['stock'] -
                        last['nifty']/first['nifty'])*100),2)


def quality_score(df, rs21, rs55):
    """100-point relative-strength and trend-quality ranking, not a trade signal."""
    last,prev=df.iloc[-1],df.iloc[-2]
    price=float(last['Close'])
    sma50=float(last['SMA 50'])
    sma200=float(last['SMA 200'])
    slope=(sma50/float(prev['SMA 50'])-1)*100
    dist=(price/sma200-1)*100
    # RS 21 (25), RS 55 (25): >= +10 and +18 pp respectively earns full points.
    rs21_pts=min(max((rs21 or 0)/10,0),1)*25
    rs55_pts=min(max((rs55 or 0)/18,0),1)*25
    # Trend (20): slope 8, price > 50 5, complete SMA alignment 7.
    trend_pts=(min(max(slope/.35,0),1)*8 +
               (5 if price>sma50 else 0) +
               (7 if last['SMA 9']>last['SMA 18']>last['SMA 50'] else 0))
    # Momentum (10): reward RSI 50–70; a very hot RSI > 75 receives less.
    rsi=float(last['RSI 14']) if pd.notna(last['RSI 14']) else 0
    rsi_pts=(10 if 55<=rsi<=70 else
             7 if 50<=rsi<55 or 70<rsi<=75 else
             3 if 45<=rsi<50 or 75<rsi<=80 else 0)
    vol=float(last['Vol Ratio']) if pd.notna(last['Vol Ratio']) else 0
    vol_pts=min(max(vol/1.5,0),1)*10
    # Extension / entry discipline (10): avoid favoring overextended shares.
    extension_pts=(10 if dist<=15 else 7 if dist<=25 else
                   3 if dist<=40 else 0)
    return round(rs21_pts+rs55_pts+trend_pts+rsi_pts+vol_pts+extension_pts,2)



def chart_html(name, code, df, rs_1m=None, rs_55=None, score=None, st=None):
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
        ('SMA 50', '#2563eb', 2.2),
        ('SMA 200', '#dc2626', 2.5)
    ]:
        traces.append({
            'type': 'scatter', 'mode': 'lines',
            'name': col + ' (' + format(float(df[col].iloc[-1]), ',.2f') + ')',
            'x': dates, 'y': numbers(col),
            'line': {'color': color, 'width': width}, 'xaxis': 'x', 'yaxis': 'y'
        })
    # Historical Supertrend overlays: green in UP trend, red in DOWN trend.
    # No SELL markers/signals are generated.
    setup = st if st is not None else supertrend_setup(df)
    for key, label, color in (
        ('history_up','Supertrend 10,3 UP','#16a34a'),
        ('history_down','Supertrend 10,3 DOWN','#dc2626')
    ):
        traces.append({
            'type':'scatter','mode':'lines','name':label,
            'x':dates,'y':setup[key][-len(shown):],
            'line':{'color':color,'width':2.8},
            'connectgaps':False,'xaxis':'x','yaxis':'y'
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
    details.update({'stSignal':setup['signal'],'stTrend':setup['trend'],
                    'stLine':setup['line'],'entry':setup['entry'],'stop':setup['stop'],
                    'greenStartDate':setup['green_start_date'],'buyHighDate':setup['date']})
    if setup['signal']=='BUY':
        # Mark the candle that set the current green-streak high.
        if setup['date'] in dates:
            traces.append({
                'type':'scatter','mode':'markers+text','name':'BUY Level High',
                'x':[setup['date']],'y':[setup['entry']],
                'text':['BUY ₹'+format(setup['entry'],',.2f')],
                'textposition':'top center',
                'marker':{'color':'#0f766e','size':13,'symbol':'diamond'},
                'xaxis':'x','yaxis':'y'
            })
        # Persistent horizontal BUY breakout level across the visible chart.
        traces.append({
            'type':'scatter','mode':'lines','name':'BUY Level ₹'+format(setup['entry'],',.2f'),
            'x':[dates[0],dates[-1]],'y':[setup['entry'],setup['entry']],
            'line':{'color':'#0f766e','width':2.5,'dash':'dash'},
            'xaxis':'x','yaxis':'y'
        })
    details['rs1m'] = rs_1m
    details['rs55'] = rs_55
    details['score'] = score
    details['cumulativeRs'] = round(rs_1m + rs_55, 2) if rs_1m is not None and rs_55 is not None else None
    payload = json.dumps({'traces': traces, 'details': details}, separators=(',', ':'))
    title = html.escape(f'{name} ({code}) — Daily SMA & Supertrend Chart')
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
<p>Daily candles • SMA 50 blue • SMA 200 red • Supertrend (10,3) green UP / red DOWN • Volume</p>
<div id="metrics"></div>
<div class="controls">
<button onclick="range(63,this)">3 months</button>
<button onclick="range(126,this)" class="sel">6 months</button>
<button onclick="range(252,this)">1 year</button>
<button onclick="range(320,this)">All</button>
<button onclick="levels(this)" class="sel">Support / Resistance</button>
</div><div id="plot"></div>
<p class="note">Supertrend BUY means the current daily (10,3) trend is UP, not necessarily a new reversal today. DOWN-trend stocks are listed after UP-trend stocks in the sheet; no SELL signals are shown. BUY Level is the highest candle high since the latest red-to-green Supertrend flip (including flip day), not just today's high. SL at 95% of SMA200 is indicative, not a broker order. 60-session support/resistance are informational.</p>
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
m('RS 21D vs NIFTY 50',d.rs1m===null?'N/A':((d.rs1m>0?'+':'')+d.rs1m.toFixed(2)+' pp'),d.rs1m===null?'':(d.rs1m>0?'green':'red'))+
m('RS 55D vs NIFTY 50',d.rs55===null?'N/A':((d.rs55>0?'+':'')+d.rs55.toFixed(2)+' pp'),d.rs55===null?'':(d.rs55>0?'green':'red'))+
m('Cumulative RS',d.cumulativeRs===null?'N/A':((d.cumulativeRs>0?'+':'')+d.cumulativeRs.toFixed(2)+' pp'),d.cumulativeRs===null?'':(d.cumulativeRs>0?'green':'red'))+
m('Quality Score',d.score===null?'N/A':d.score.toFixed(2)+'/100')+
m('Supertrend Signal',d.stSignal||'—',d.stSignal==='BUY'?'green':'')+
m('Supertrend Trend',d.stTrend,d.stTrend==='UP'?'green':'red')+
m('Supertrend (10,3)',d.stLine===null?'N/A':'₹'+d.stLine.toLocaleString('en-IN'))+
m('BUY Level (green-run high)',d.entry?'Above ₹'+d.entry:'—')+
m('Green trend began',d.greenStartDate||'—')+
m('Highest high date',d.buyHighDate||'—')+
m('SL (SMA200 - 5%)',d.stop?'₹'+d.stop:'—');
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


def scan(name,code,nifty_close):
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
    if not (latest['Close']>latest['SMA 200']): return None
    rs_1m = relative_strength(close, nifty_close, 21)
    rs_55 = relative_strength(close, nifty_close, 55)
    score = quality_score(df, rs_1m, rs_55)
    setup = supertrend_setup(df)
    CHART_DIR.mkdir(parents=True,exist_ok=True)
    filename=re.sub(r'[^A-Za-z0-9_-]','-',code)+'-sma-chart.html'
    (CHART_DIR/filename).write_text(chart_html(name,code,df,rs_1m,rs_55,score,setup),encoding='utf-8')
    url=f'{CHART_BASE}/{filename}?v=12'
    slope_pct = (float(latest['SMA 50'])/float(prev['SMA 50'])-1)*100
    distance_pct = (float(latest['Close'])/float(latest['SMA 200'])-1)*100
    vol_ratio = float(latest['Vol Ratio']) if pd.notna(latest['Vol Ratio']) else 0.0
    rsi = float(latest['RSI 14']) if pd.notna(latest['RSI 14']) else 50.0
    alignment = bool(latest['SMA 9'] > latest['SMA 18'] > latest['SMA 50'])
    breakout = bool(latest['Close'] > df['High'].iloc[-21:-1].max())
    return {'Stock Name':name,'NSE Code':code,'CMP':round(float(latest['Close']),2),
            'SMA 9':round(float(latest['SMA 9']),2),'SMA 18':round(float(latest['SMA 18']),2),
            'SMA 50':round(float(latest['SMA 50']),2),'SMA 200':round(float(latest['SMA 200']),2),
            'SMA 50 Slope':'UP' if slope_pct>0 else 'DOWN',
            '50 Slope %':round(slope_pct,4),
            'SMA 200 Distance %':round(distance_pct,2),
            'Vol Ratio':round(vol_ratio,2),
            'RSI 14':round(rsi,2),
            '20D Breakout':'YES' if breakout else 'NO',
            'Score':score,
            'Supertrend Signal':setup['signal'],
            'Supertrend 10,3':setup['line'] if setup['line'] is not None else '',
            'ST Trend':setup['trend'],'BUY Level':setup['entry'],
            'Stop Below':setup['stop'],
            'RS 1M vs NIFTY %':rs_1m if rs_1m is not None else '',
            'RS 55D vs NIFTY %':rs_55 if rs_55 is not None else '',
            'Cumulative RS':round(rs_1m + rs_55, 2) if rs_1m is not None and rs_55 is not None else '',
            'Chart Link':url}

def write_output(book, rows):
    """Write compact 18-column Final List; preserve signals and rank."""
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
    values=[COLUMNS]+[[row.get(c,'') for c in COLUMNS] for row in rows]
    end_col='R'
    ws.update(values, range_name=f'A1:{end_col}{len(values)}', value_input_option='RAW')
    ws.freeze(rows=1, cols=3)
    ws.format(f'A1:{end_col}1',{
        'backgroundColor':{'red':0.80,'green':0.90,'blue':0.99},
        'textFormat':{'bold':True,'fontSize':10},
        'horizontalAlignment':'CENTER','wrapStrategy':'WRAP'
    })
    if rows:
        last_row=len(rows)+1
        for col in ('D','E','F','H','L','N','O','P'):
            ws.format(f'{col}2:{col}{last_row}',{
                'numberFormat':{'type':'NUMBER','pattern':'0.00'}})
        ws.format(f'I2:K{last_row}',{
            'numberFormat':{'type':'NUMBER','pattern':'+0.00;-0.00;0.00'}})
        # Reset old visual highlighting and mark today's Supertrend BUY rows.
        colors=[{'repeatCell':{
            'range':{'sheetId':ws.id,'startRowIndex':1,'endRowIndex':last_row,
                     'startColumnIndex':0,'endColumnIndex':len(COLUMNS)},
            'cell':{'userEnteredFormat':{
                'backgroundColor':{'red':1,'green':1,'blue':1}}},
            'fields':'userEnteredFormat.backgroundColor'}}]
        chart_requests=[]
        for i,row in enumerate(rows,start=2):
            chart_requests.append({'updateCells':{
                'range':{'sheetId':ws.id,'startRowIndex':i-1,'endRowIndex':i,
                         'startColumnIndex':17,'endColumnIndex':18},
                'rows':[{'values':[{
                    'userEnteredValue':{'stringValue':'OPEN CHART'},
                    'textFormatRuns':[{'startIndex':0,'format':{
                        'link':{'uri':row['Chart Link']},'underline':True}}]}]}],
                'fields':'userEnteredValue,textFormatRuns'}})
            if row.get('Supertrend Signal')=='BUY':
                colors.append({'repeatCell':{
                    'range':{'sheetId':ws.id,'startRowIndex':i-1,'endRowIndex':i,
                             'startColumnIndex':0,'endColumnIndex':len(COLUMNS)},
                    'cell':{'userEnteredFormat':{
                        'backgroundColor':{'red':0.86,'green':0.97,'blue':0.88}}},
                    'fields':'userEnteredFormat.backgroundColor'}})
        for start in range(0,len(chart_requests),100):
            book.batch_update({'requests':chart_requests[start:start+100]})
        for start in range(0,len(colors),100):
            book.batch_update({'requests':colors[start:start+100]})
        ws.format(f'Q2:Q{last_row}',{'textFormat':{'bold':True}})
    print(f'Final List updated: {len(rows)} qualifying stocks, {len(COLUMNS)} columns')



def main():
    book=google_book()
    stocks=get_stocks(book)
    print(f'Scanning {len(stocks)} stocks for CMP>SMA200; all SMA50 slopes allowed')
    # Fetch NIFTY once for all stocks; never request it separately per ticker.
    nifty_close = None
    try:
        nifty_history = yf.Ticker('^NSEI').history(
            period='6mo', interval='1d', auto_adjust=False, actions=False)
        if nifty_history is not None and not nifty_history.empty:
            nifty_close = pd.to_numeric(nifty_history['Close'], errors='coerce').dropna()
            print('NIFTY50 benchmark observations:',len(nifty_close))
    except Exception as exc:
        print('NIFTY50 benchmark unavailable:',exc)
    rows=[]
    for i,(name,code) in enumerate(stocks,1):
        try:
            result=scan(name,code,nifty_close)
            if result: rows.append(result); print(f'  PASS {code}')
        except Exception as exc: print(f'  ERROR {code}: {exc}')
        if i%50==0: print(f'Processed {i}/{len(stocks)}')
    # Ranking priorities:
    # 1) All Supertrend UP/BUY stocks first, DOWN stocks afterward.
    # 2) Within each trend group, favor close within 10% of SMA200.
    # 3) Within each distance group, prefer rising SMA50.
    # 4) Within those groups, rank by cumulative 21D + 55D RS.
    rows.sort(key=lambda r: (
        r['ST Trend'] != 'UP',
        r['SMA 200 Distance %'] > 10.0,
        r['SMA 50 Slope'] != 'UP',
        r['Cumulative RS'] == '',
        -r['Cumulative RS'] if r['Cumulative RS'] != '' else 0,
        -r['Score'], r['NSE Code']
    ))
    for rank, row in enumerate(rows, 1):
        row['Rank'] = rank
    write_output(book,rows)
    print('Charts generated in',CHART_DIR,'— ensure workflow publishes docs/charts to GitHub Pages.')

if __name__=='__main__': main()
