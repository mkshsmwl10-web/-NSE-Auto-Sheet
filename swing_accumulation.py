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


def sheets_retry_policy():
    from urllib3.util.retry import Retry
    return Retry(total=5, connect=5, read=5, status=5, backoff_factor=4,
                 status_forcelist=(429, 500, 502, 503, 504),
                 allowed_methods=frozenset({'GET', 'HEAD', 'PUT'}),
                 raise_on_status=False, respect_retry_after_header=True)


def open_swing_book():
    import os
    import gspread
    from google.oauth2.service_account import Credentials
    from google.auth.transport.requests import AuthorizedSession
    from requests.adapters import HTTPAdapter
    from update_sheet import SHEET_ID
    raw = os.environ.get('GCP_CREDENTIALS', '').strip()
    if not raw:
        raise RuntimeError('GCP_CREDENTIALS missing')
    scopes = ['https://www.googleapis.com/auth/spreadsheets',
              'https://www.googleapis.com/auth/drive']
    creds = (Credentials.from_service_account_info(json.loads(raw), scopes=scopes)
             if raw.startswith('{') else Credentials.from_service_account_file(raw, scopes=scopes))
    session = AuthorizedSession(creds)
    # Retry HTTP responses before gspread attempts to parse Google's HTML error.
    # POST is excluded so worksheet creation cannot be accidentally repeated.
    session.mount('https://', HTTPAdapter(max_retries=sheets_retry_policy()))
    client = gspread.Client(auth=creds, session=session)
    client.set_timeout((15, 60))
    return client.open_by_key(SHEET_ID)


def style_swing_sheet(book, ws):
    """Apply persistent column colors and status rules without duplicating rules."""
    requests = json.loads(r'''[{"repeatCell":{"range":{"sheetId":__SHEET_ID__,"startRowIndex":2,"startColumnIndex":0,"endColumnIndex":18},"cell":{"userEnteredFormat":{"backgroundColor":{"red":1,"green":1,"blue":1},"textFormat":{"fontFamily":"Arial","fontSize":10,"foregroundColor":{"red":0.09019607843137255,"green":0.12549019607843137,"blue":0.2}},"verticalAlignment":"MIDDLE","wrapStrategy":"CLIP"}},"fields":"userEnteredFormat"}},{"repeatCell":{"range":{"sheetId":__SHEET_ID__,"startRowIndex":0,"endRowIndex":2,"startColumnIndex":0,"endColumnIndex":18},"cell":{"userEnteredFormat":{"backgroundColor":{"red":0.08627450980392157,"green":0.19607843137254902,"blue":0.30980392156862746},"textFormat":{"bold":true,"foregroundColor":{"red":1,"green":1,"blue":1},"fontSize":10},"wrapStrategy":"WRAP","verticalAlignment":"MIDDLE"}},"fields":"userEnteredFormat"}},{"repeatCell":{"range":{"sheetId":__SHEET_ID__,"startRowIndex":2,"startColumnIndex":7,"endColumnIndex":8},"cell":{"userEnteredFormat":{"backgroundColor":{"red":1,"green":0.9411764705882353,"blue":0.8509803921568627},"textFormat":{"bold":true,"foregroundColor":{"red":0.6039215686274509,"green":0.27058823529411763,"blue":0}},"numberFormat":{"type":"NUMBER","pattern":"#,##0.00"},"horizontalAlignment":"RIGHT"}},"fields":"userEnteredFormat"}},{"repeatCell":{"range":{"sheetId":__SHEET_ID__,"startRowIndex":1,"endRowIndex":2,"startColumnIndex":7,"endColumnIndex":8},"cell":{"userEnteredFormat":{"backgroundColor":{"red":0.6039215686274509,"green":0.27058823529411763,"blue":0},"textFormat":{"bold":true,"foregroundColor":{"red":1,"green":1,"blue":1}},"wrapStrategy":"WRAP"}},"fields":"userEnteredFormat"}},{"repeatCell":{"range":{"sheetId":__SHEET_ID__,"startRowIndex":2,"startColumnIndex":8,"endColumnIndex":9},"cell":{"userEnteredFormat":{"backgroundColor":{"red":0.8666666666666667,"green":0.9529411764705882,"blue":0.8941176470588236},"textFormat":{"bold":true,"foregroundColor":{"red":0.09019607843137255,"green":0.3843137254901961,"blue":0.2235294117647059}},"numberFormat":{"type":"NUMBER","pattern":"#,##0.00"},"horizontalAlignment":"RIGHT"}},"fields":"userEnteredFormat"}},{"repeatCell":{"range":{"sheetId":__SHEET_ID__,"startRowIndex":1,"endRowIndex":2,"startColumnIndex":8,"endColumnIndex":9},"cell":{"userEnteredFormat":{"backgroundColor":{"red":0.09019607843137255,"green":0.3843137254901961,"blue":0.2235294117647059},"textFormat":{"bold":true,"foregroundColor":{"red":1,"green":1,"blue":1}},"wrapStrategy":"WRAP"}},"fields":"userEnteredFormat"}},{"repeatCell":{"range":{"sheetId":__SHEET_ID__,"startRowIndex":2,"startColumnIndex":12,"endColumnIndex":13},"cell":{"userEnteredFormat":{"backgroundColor":{"red":0.8901960784313725,"green":0.9294117647058824,"blue":1},"textFormat":{"bold":true,"foregroundColor":{"red":0.09803921568627451,"green":0.28627450980392155,"blue":0.6274509803921569}},"numberFormat":{"type":"NUMBER","pattern":"#,##0.00"},"horizontalAlignment":"RIGHT"}},"fields":"userEnteredFormat"}},{"repeatCell":{"range":{"sheetId":__SHEET_ID__,"startRowIndex":1,"endRowIndex":2,"startColumnIndex":12,"endColumnIndex":13},"cell":{"userEnteredFormat":{"backgroundColor":{"red":0.09803921568627451,"green":0.28627450980392155,"blue":0.6274509803921569},"textFormat":{"bold":true,"foregroundColor":{"red":1,"green":1,"blue":1}},"wrapStrategy":"WRAP"}},"fields":"userEnteredFormat"}},{"repeatCell":{"range":{"sheetId":__SHEET_ID__,"startRowIndex":2,"startColumnIndex":13,"endColumnIndex":14},"cell":{"userEnteredFormat":{"backgroundColor":{"red":1,"green":0.8941176470588236,"blue":0.8941176470588236},"textFormat":{"bold":true,"foregroundColor":{"red":0.6470588235294118,"green":0.11764705882352941,"blue":0.17254901960784313}},"numberFormat":{"type":"NUMBER","pattern":"#,##0.00"},"horizontalAlignment":"RIGHT"}},"fields":"userEnteredFormat"}},{"repeatCell":{"range":{"sheetId":__SHEET_ID__,"startRowIndex":1,"endRowIndex":2,"startColumnIndex":13,"endColumnIndex":14},"cell":{"userEnteredFormat":{"backgroundColor":{"red":0.6470588235294118,"green":0.11764705882352941,"blue":0.17254901960784313},"textFormat":{"bold":true,"foregroundColor":{"red":1,"green":1,"blue":1}},"wrapStrategy":"WRAP"}},"fields":"userEnteredFormat"}},{"repeatCell":{"range":{"sheetId":__SHEET_ID__,"startRowIndex":2,"startColumnIndex":15,"endColumnIndex":16},"cell":{"userEnteredFormat":{"backgroundColor":{"red":0.8862745098039215,"green":0.9607843137254902,"blue":0.9372549019607843},"textFormat":{"bold":true,"foregroundColor":{"red":0.07058823529411765,"green":0.4117647058823529,"blue":0.30980392156862746}},"numberFormat":{"type":"NUMBER","pattern":"#,##0.00"},"horizontalAlignment":"RIGHT"}},"fields":"userEnteredFormat"}},{"repeatCell":{"range":{"sheetId":__SHEET_ID__,"startRowIndex":1,"endRowIndex":2,"startColumnIndex":15,"endColumnIndex":16},"cell":{"userEnteredFormat":{"backgroundColor":{"red":0.07058823529411765,"green":0.4117647058823529,"blue":0.30980392156862746},"textFormat":{"bold":true,"foregroundColor":{"red":1,"green":1,"blue":1}},"wrapStrategy":"WRAP"}},"fields":"userEnteredFormat"}},{"repeatCell":{"range":{"sheetId":__SHEET_ID__,"startRowIndex":2,"startColumnIndex":6,"endColumnIndex":7},"cell":{"userEnteredFormat":{"numberFormat":{"type":"NUMBER","pattern":"0.00"}}},"fields":"userEnteredFormat.numberFormat"}},{"repeatCell":{"range":{"sheetId":__SHEET_ID__,"startRowIndex":2,"startColumnIndex":9,"endColumnIndex":12},"cell":{"userEnteredFormat":{"numberFormat":{"type":"NUMBER","pattern":"0.00"}}},"fields":"userEnteredFormat.numberFormat"}},{"repeatCell":{"range":{"sheetId":__SHEET_ID__,"startRowIndex":2,"startColumnIndex":14,"endColumnIndex":15},"cell":{"userEnteredFormat":{"numberFormat":{"type":"NUMBER","pattern":"0.00"}}},"fields":"userEnteredFormat.numberFormat"}},{"addConditionalFormatRule":{"index":0,"rule":{"ranges":[{"sheetId":__SHEET_ID__,"startRowIndex":2,"startColumnIndex":4,"endColumnIndex":5}],"booleanRule":{"condition":{"type":"TEXT_EQ","values":[{"userEnteredValue":"BREAKOUT"}]},"format":{"backgroundColor":{"red":0.7764705882352941,"green":0.9372549019607843,"blue":0.807843137254902},"textFormat":{"bold":true,"foregroundColor":{"red":0.09019607843137255,"green":0.3843137254901961,"blue":0.2235294117647059}}}}}}},{"addConditionalFormatRule":{"index":0,"rule":{"ranges":[{"sheetId":__SHEET_ID__,"startRowIndex":2,"startColumnIndex":4,"endColumnIndex":5}],"booleanRule":{"condition":{"type":"TEXT_EQ","values":[{"userEnteredValue":"WATCH"}]},"format":{"backgroundColor":{"red":1,"green":0.9490196078431372,"blue":0.7019607843137254},"textFormat":{"bold":true,"foregroundColor":{"red":0.5058823529411764,"green":0.35294117647058826,"blue":0}}}}}}},{"addConditionalFormatRule":{"index":0,"rule":{"ranges":[{"sheetId":__SHEET_ID__,"startRowIndex":2,"startColumnIndex":4,"endColumnIndex":5}],"booleanRule":{"condition":{"type":"TEXT_EQ","values":[{"userEnteredValue":"RISK TOO WIDE"}]},"format":{"backgroundColor":{"red":1,"green":0.8509803921568627,"blue":0.8509803921568627},"textFormat":{"bold":true,"foregroundColor":{"red":0.6470588235294118,"green":0.11764705882352941,"blue":0.17254901960784313}}}}}}},{"addConditionalFormatRule":{"index":0,"rule":{"ranges":[{"sheetId":__SHEET_ID__,"startRowIndex":2,"startColumnIndex":4,"endColumnIndex":5}],"booleanRule":{"condition":{"type":"TEXT_EQ","values":[{"userEnteredValue":"NO SETUP"}]},"format":{"backgroundColor":{"red":0.9294117647058824,"green":0.9411764705882353,"blue":0.9568627450980393},"textFormat":{"bold":true,"foregroundColor":{"red":0.34901960784313724,"green":0.396078431372549,"blue":0.4745098039215686}}}}}}},{"addConditionalFormatRule":{"index":0,"rule":{"ranges":[{"sheetId":__SHEET_ID__,"startRowIndex":2,"startColumnIndex":4,"endColumnIndex":5}],"booleanRule":{"condition":{"type":"TEXT_EQ","values":[{"userEnteredValue":"STALE DATA"}]},"format":{"backgroundColor":{"red":0.9098039215686274,"green":0.8666666666666667,"blue":0.9607843137254902},"textFormat":{"bold":true,"foregroundColor":{"red":0.41568627450980394,"green":0.21176470588235294,"blue":0.5490196078431373}}}}}}},{"updateSheetProperties":{"properties":{"sheetId":__SHEET_ID__,"gridProperties":{"hideGridlines":true,"frozenRowCount":2,"frozenColumnCount":3}},"fields":"gridProperties.hideGridlines,gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}},{"updateDimensionProperties":{"range":{"sheetId":__SHEET_ID__,"dimension":"COLUMNS","startIndex":0,"endIndex":1},"properties":{"pixelSize":55},"fields":"pixelSize"}},{"updateDimensionProperties":{"range":{"sheetId":__SHEET_ID__,"dimension":"COLUMNS","startIndex":1,"endIndex":2},"properties":{"pixelSize":185},"fields":"pixelSize"}},{"updateDimensionProperties":{"range":{"sheetId":__SHEET_ID__,"dimension":"COLUMNS","startIndex":2,"endIndex":4},"properties":{"pixelSize":120},"fields":"pixelSize"}},{"updateDimensionProperties":{"range":{"sheetId":__SHEET_ID__,"dimension":"COLUMNS","startIndex":4,"endIndex":5},"properties":{"pixelSize":155},"fields":"pixelSize"}},{"updateDimensionProperties":{"range":{"sheetId":__SHEET_ID__,"dimension":"COLUMNS","startIndex":5,"endIndex":16},"properties":{"pixelSize":120},"fields":"pixelSize"}},{"updateDimensionProperties":{"range":{"sheetId":__SHEET_ID__,"dimension":"COLUMNS","startIndex":16,"endIndex":17},"properties":{"pixelSize":260},"fields":"pixelSize"}},{"updateDimensionProperties":{"range":{"sheetId":__SHEET_ID__,"dimension":"COLUMNS","startIndex":17,"endIndex":18},"properties":{"pixelSize":190},"fields":"pixelSize"}},{"updateDimensionProperties":{"range":{"sheetId":__SHEET_ID__,"dimension":"ROWS","startIndex":0,"endIndex":2},"properties":{"pixelSize":48},"fields":"pixelSize"}},{"setBasicFilter":{"filter":{"range":{"sheetId":__SHEET_ID__,"startRowIndex":1,"startColumnIndex":0,"endColumnIndex":18}}}}]'''.replace('__SHEET_ID__', str(ws.id)))
    metadata = book.fetch_sheet_metadata()
    sheet = next(s for s in metadata['sheets'] if s['properties']['sheetId'] == ws.id)
    existing = sheet.get('conditionalFormats', [])
    def has_rule(rule):
        return any(old.get('booleanRule') == rule.get('booleanRule') and
                   old.get('ranges') == rule.get('ranges') for old in existing)
    requests = [r for r in requests if 'addConditionalFormatRule' not in r or
                not has_rule(r['addConditionalFormatRule']['rule'])]
    # Google may normalize RGB values; match status + target range too.
    statuses = {v['userEnteredValue'] for r in existing
                if all(x.get('startColumnIndex') == 4 and x.get('endColumnIndex') == 5
                       and x.get('startRowIndex') == 2 for x in r.get('ranges', []))
                and r.get('booleanRule', {}).get('condition', {}).get('type') == 'TEXT_EQ'
                for v in r['booleanRule']['condition'].get('values', [])}
    requests = [r for r in requests if 'addConditionalFormatRule' not in r or
                r['addConditionalFormatRule']['rule']['booleanRule']['condition']['values'][0]['userEnteredValue'] not in statuses]
    book.batch_update({'requests': requests})


def main():
    import gspread
    import yfinance as yf
    from update_sheet import get_stocks
    book = open_swing_book()
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
    style_swing_sheet(book, ws)
    print(f'Swing Accumulation updated: {len(rows)} stocks; errors: {len(errors)}')


if __name__ == '__main__':
    main()
