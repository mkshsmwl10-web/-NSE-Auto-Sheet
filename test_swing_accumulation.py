import unittest
from datetime import datetime
import pandas as pd
from swing_accumulation import evaluate, completed_bars, IST


class SwingTests(unittest.TestCase):
    def test_google_transient_retry_policy(self):
        from swing_accumulation import sheets_retry_policy
        from urllib3.response import HTTPResponse
        policy = sheets_retry_policy()
        self.assertTrue(policy.is_retry('GET', 502))
        self.assertTrue(policy.is_retry('PUT', 503))
        self.assertFalse(policy.is_retry('GET', 403))
        self.assertFalse(policy.is_retry('POST', 502))
        for _ in range(5):
            policy = policy.increment(method='GET', response=HTTPResponse(status=502))
        from urllib3.exceptions import MaxRetryError
        with self.assertRaises(MaxRetryError):
            policy.increment(method='GET', response=HTTPResponse(status=502))

    def bars(self):
        closes = [60+i*.15 for i in range(210)]
        closes += [94+(i%2)*.5+i*.03 for i in range(20)]
        df = pd.DataFrame({'Close': closes}, index=pd.bdate_range('2025-01-01', periods=230))
        df['Open'] = df.Close-.1
        df['High'] = df.Close+.5
        df['Low'] = df.Close-.5
        df['Volume'] = [200 if x > 0 else 100 for x in df.Close.diff().fillna(1)]
        return df

    def test_breakout_and_reference_excludes_signal(self):
        df = self.bars()
        df.iloc[-1] = pd.Series({'Close': 96.5, 'Open': 95, 'High': 96.6, 'Low': 95, 'Volume': 1000})
        result = evaluate(df)
        self.assertEqual(result['Status'], 'BREAKOUT')
        self.assertLess(result['Resistance'], result['Close'])
        self.assertGreater(result['Target 2R'], result['Indicative Entry'])

    def test_intraday_excluded(self):
        df = self.bars()
        today = df.index[-1]
        now = datetime(today.year, today.month, today.day, 13, 0, tzinfo=IST)
        self.assertEqual(len(completed_bars(df, now)), len(df)-1)

    def test_zero_volume_rejected(self):
        df = self.bars(); df['Volume'] = 0
        self.assertIsNone(evaluate(df))

    def test_short_history_rejected(self):
        self.assertIsNone(evaluate(self.bars().tail(50)))


if __name__ == '__main__':
    unittest.main()
