"""End-of-day price/volume swing screen; never confirms institutional ownership."""
from datetime import datetime, time
from zoneinfo import ZoneInfo
import json
from pathlib import Path
import pandas as pd

IST = ZoneInfo('Asia/Kolkata')
COLUMNS = ['Rank', 'Stock Name', 'NSE Code', 'Data Date', 'Status', 'Score /100',
           'Close', 'Resistance', 'Support', 'Volume Ratio', 'Up/Down Volume',
           'Base Width %', 'Indicative Entry', 'Stop Below', 'Risk %',
           'Target 2R', 'Institutional Evidence', 'Chart']


def completed_bars(raw, now=None):
    now = now or datetime.now(IST)
    df = raw.copy()
    dates = pd.to_datetime(df.index)
    dates = dates.tz_localize(IST) if dates.tz is None else dates.tz_convert(IST)
    # Exclude today's unfinished daily candle, including a post-close buffer.
    cutoff = now.date()
    mask = dates.date <= cutoff if now.time() >= time(16, 0) else dates.date < cutoff
    return df.loc[mask].sort_index()


def evaluate(raw):
    df = raw[['Open', 'High', 'Low', 'Close', 'Volume']].apply(pd.to_numeric, errors='coerce').dropna()
    if len(df) < 210 or not df.index.is_unique:
        return None
    if (df[['Open', 'High', 'Low', 'Close']] <= 0).any().any() or (df.Volume < 0).any():
        return None
    last = df.iloc[-1]
    base = df.iloc[-21:-1]  # today's high/volume never enters its own reference
    resistance, support = float(base.High.max()), float(base.Low.min())
    mean_volume = float(base.Volume.mean())
    if mean_volume <= 0:
        return None
    width = (resistance / support - 1) * 100
    vol_ratio = float(last.Volume / mean_volume)
    moves = df.Close.diff().reindex(base.index)
    up, down = base.loc[moves > 0, 'Volume'], base.loc[moves < 0, 'Volume']
    ud = float(up.mean() / down.mean()) if len(up) and len(down) and down.mean() > 0 else None
    sma50, sma200 = df.Close.rolling(50).mean(), df.Close.rolling(200).mean()
    trend = bool(last.Close > sma50.iloc[-1] > sma200.iloc[-1] and sma50.iloc[-1] > sma50.iloc[-6])
    tight = width <= 15
    buying = ud is not None and ud >= 1.3
    # Later lows above earlier lows are only a proxy for support holding.
    held = bool(base.Low.iloc[-10:].min() >= base.Low.iloc[:10].min())
    strong_close = bool(last.High > last.Low and (last.Close-last.Low)/(last.High-last.Low) >= .7)
    score = 25*trend + 20*tight + 20*buying + 15*held + 10*(vol_ratio >= 1.5) + 10*strong_close
    breakout = bool(last.Close > resistance and vol_ratio >= 1.5 and strong_close)
    near = bool(.97 * resistance <= last.Close <= resistance)
    qualified = trend and tight and buying and held
    status = 'BREAKOUT' if qualified and breakout else 'WATCH' if qualified and near else 'NO SETUP'
    # Breakout is a completed-close signal; entry is a reference, not an order.
    entry = float(last.Close) if status == 'BREAKOUT' else resistance * 1.001
    stop = float(df.Low.iloc[-5:].min()) * .995
    risk = (entry-stop)/entry*100
    if status != 'NO SETUP' and not 0 < risk <= 7:
        status = 'RISK TOO WIDE'
    actionable = status in ('WATCH', 'BREAKOUT')
    return {'Data Date': str(df.index[-1].date()), 'Status': status, 'Score /100': int(score),
            'Close': round(float(last.Close), 2), 'Resistance': round(resistance, 2),
            'Support': round(support, 2), 'Volume Ratio': round(vol_ratio, 2),
            'Up/Down Volume': round(ud, 2) if ud is not None else '', 'Base Width %': round(width, 2),
            'Indicative Entry': round(entry, 2) if actionable else '',
            'Stop Below': round(stop, 2) if actionable else '',
            'Risk %': round(risk, 2) if actionable else '',
            'Target 2R': round(entry+2*(entry-stop), 2) if actionable else '',
            'Institutional Evidence': 'UNVERIFIED: delivery / holdings / deals not loaded'}


def main():
    import gspread
    import yfinance as yf
    from update_sheet import google_book, get_stocks
    book = google_book()
    stocks = get_stocks(book)
    rows, errors = [], []
    now = datetime.now(IST)
    for name, code in stocks:
        try:
            raw = yf.Ticker(code+'.NS').history(period='2y', interval='1d', auto_adjust=True, actions=False)
            df = completed_bars(raw, now)
            result = evaluate(df)
            if result is None:
                raise ValueError('Insufficient or invalid OHLCV')
            age = (now.date()-df.index[-1].date()).days
            if age > 4:
                result['Status'] = 'STALE DATA'
                for key in ('Indicative Entry', 'Stop Below', 'Risk %', 'Target 2R'):
                    result[key] = ''
            result.update({'Stock Name': name, 'NSE Code': code,
                           'Chart': 'https://www.tradingview.com/chart/?symbol=NSE%3A'+code.replace('&', '%26')})
            rows.append(result)
        except Exception as exc:
            errors.append({'NSE Code': code, 'Error': str(exc)})
            print('ERROR', code, exc)
    # A bad feed must not erase the previous successful screen.
    if not stocks or len(rows) < max(1, .8*len(stocks)):
        raise RuntimeError(f'Coverage too low: {len(rows)}/{len(stocks)}; previous sheet retained')
    order = {'BREAKOUT': 0, 'WATCH': 1, 'RISK TOO WIDE': 2, 'NO SETUP': 3, 'STALE DATA': 4}
    rows.sort(key=lambda r: (order[r['Status']], -r['Score /100'], r['NSE Code']))
    for rank, row in enumerate(rows, 1):
        row['Rank'] = rank
    out = Path('swing_output'); out.mkdir(exist_ok=True)
    pd.DataFrame(rows)[COLUMNS].to_csv(out/'signals.csv', index=False)
    (out/'run.json').write_text(json.dumps({'run_at': now.isoformat(), 'scanned': len(stocks),
        'valid': len(rows), 'errors': errors}, indent=2), encoding='utf-8')
    try:
        ws = book.worksheet('Swing Accumulation')
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(title='Swing Accumulation', rows=max(300,len(rows)+5), cols=len(COLUMNS))
    note = f'Run {now:%Y-%m-%d %H:%M} IST | Coverage {len(rows)}/{len(stocks)} | Heuristic, not backtested. Institutional buying UNVERIFIED.'
    values = [[note]+['']*(len(COLUMNS)-1), COLUMNS] + [[r.get(c,'') for c in COLUMNS] for r in rows]
    previous_count = ws.row_count
    ws.resize(rows=max(previous_count,len(values)), cols=max(ws.col_count,len(COLUMNS)))
    # One values write replaces old rows and clears any leftover records.
    values += [['']*len(COLUMNS) for _ in range(max(0,previous_count-len(values)))]
    ws.update(values, range_name=f'A1:R{len(values)}', value_input_option='RAW')
    ws.freeze(rows=2, cols=3)
    ws.format('A1:R2', {'backgroundColor': {'red': .08, 'green': .18, 'blue': .3},
        'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}}, 'wrapStrategy': 'WRAP'})
    print(f'Swing Accumulation updated: {len(rows)} stocks; errors: {len(errors)}')


if __name__ == '__main__':
    main()
