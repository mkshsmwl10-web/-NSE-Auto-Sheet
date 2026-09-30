"""Rolling eleven completed NIFTY spot sessions; confirmed 1-left/1-right pivots."""
import json
import math
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
BOOK_ID = '1bNXvVoDXgBmB-R_w6nJr4sBVYK6bksrv35BVYkiNe2E'
TAB = 'NIFTY 11 Days'


def analyse(rows):
    highs, lows, output = [], [], []
    for i, row in enumerate(rows):
        high_label = low_label = ''
        # The middle candle becomes confirmed only after its right candle closes.
        if i >= 2:
            left, mid, right = rows[i-2:i+1]
            if mid['high'] > left['high'] and mid['high'] > right['high']:
                high_label = ('HH' if mid['high'] > highs[-1] else 'LH' if mid['high'] < highs[-1] else 'EH') if highs else 'FIRST HIGH'
                highs.append(mid['high'])
                output[i-1][6] = high_label
            if mid['low'] < left['low'] and mid['low'] < right['low']:
                low_label = ('HL' if mid['low'] > lows[-1] else 'LL' if mid['low'] < lows[-1] else 'EL') if lows else 'FIRST LOW'
                lows.append(mid['low'])
                output[i-1][7] = low_label
        trend, sl = 'INSUFFICIENT SWINGS', ''
        if len(highs) >= 2 and len(lows) >= 2:
            trend = 'SIDEWAYS'
            if highs[-1] > highs[-2] and lows[-1] > lows[-2] and row['close'] > lows[-1]:
                trend, sl = 'UP', lows[-1]
            elif highs[-1] < highs[-2] and lows[-1] < lows[-2] and row['close'] < highs[-1]:
                trend, sl = 'DOWN', highs[-1]
        output.append([row['date'].strftime('%Y-%m-%d'), row['date'].strftime('%A'),
                       row['open'], row['high'], row['low'], row['close'], '', '', trend, sl])
    return output


def fetch_rows():
    import yfinance as yf
    import pandas as pd
    data = yf.download('^NSEI', period='3mo', interval='1d', auto_adjust=False,
                       progress=False, threads=False)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    now = datetime.now(IST)
    rows = []
    for stamp, values in data.sort_index().iterrows():
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert(IST)
        day = stamp.date()
        if day > now.date() or (day == now.date() and now.time() < time(16, 0)):
            continue
        prices = [float(values[k]) for k in ('Open', 'High', 'Low', 'Close')]
        if not all(math.isfinite(x) and x > 0 for x in prices):
            continue
        o, h, l, c = prices
        if l > min(o, c) or h < max(o, c) or l > h:
            raise RuntimeError('Invalid OHLC received; sheet retained.')
        rows.append(dict(date=day, open=o, high=h, low=l, close=c))
    rows = list({r['date']: r for r in rows}.values())[-11:]
    if len(rows) != 11:
        raise RuntimeError('Fewer than eleven sessions received; sheet retained.')
    return rows


def main():
    import gspread
    from google.oauth2.service_account import Credentials
    rows = fetch_rows()  # Validate source before touching the spreadsheet.
    result = analyse(rows)
    creds = Credentials.from_service_account_info(json.loads(os.environ['GCP_CREDENTIALS']),
        scopes=['https://www.googleapis.com/auth/spreadsheets'])
    book = gspread.authorize(creds).open_by_key(os.getenv('SPREADSHEET_ID', BOOK_ID))
    try:
        ws = book.worksheet(TAB)
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(title=TAB, rows=30, cols=10)
    values = [['Date', 'Day', 'Open', 'High', 'Low', 'Close', 'Swing High', 'Swing Low', 'Trend as of Close', 'Spot SL']] + result
    values += [[''] * 10, ['Updated (IST)', datetime.now(IST).isoformat(timespec='seconds')],
               ['Next session bias', result[-1][8]], ['Spot SL', result[-1][9]],
               ['Rule', 'Confirmed pivot: higher/lower than one candle on each side. Labels confirm one session later.'],
               ['Basis', 'Only these 11 completed sessions; insufficient pivots = no signal.'],
               ['SL rule', 'UP: latest confirmed swing low. DOWN: latest confirmed swing high. Intraday spot touch invalidates bias.'],
               ['Source', 'Yahoo Finance ^NSEI daily; next-session bias is not a forecast guarantee.']]
    # Fixed owned range; overwrite old output without clearing other tabs.
    values += [[''] * 10 for _ in range(22-len(values))]
    ws.update(range_name='A1:J22', values=values, value_input_option='RAW')
    ws.freeze(rows=1)
    ws.format('A1:J1', {'backgroundColor': {'red': .1, 'green': .2, 'blue': .35},
        'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}}})
    ws.format('C2:F12', {'numberFormat': {'type': 'NUMBER', 'pattern': '0.00'}})
    ws.format('J2:J12', {'numberFormat': {'type': 'NUMBER', 'pattern': '0.00'}})
    print('Updated', TAB, 'through', rows[-1]['date'], result[-1][8:])


if __name__ == '__main__':
    main()
