import unittest
from datetime import date

import pandas as pd
from half_month_positions import build_portfolio, HOLDING_HEADER, REALIZED_HEADER

TODAY=date(2026,10,17)

def lot(symbol="TCS",kind="STOCK",entry=100,qty=10,state="OPEN",exit_price="",exit_date="",trigger="2026-10-01"):
    return [trigger+":"+symbol,trigger,"2026-10-31",kind,"Theme",symbol,symbol,
            trigger,entry,qty,"PAPER",state,exit_date,exit_price,""]

def quotes(symbol="TCS",price=115,day="2026-10-16"):
    return {symbol:pd.DataFrame({"Close":[price]},index=pd.to_datetime([day]))}

class PortfolioTests(unittest.TestCase):
    def test_stock_boundary_and_full_exit(self):
        h,_,_=build_portfolio([lot()],quotes(),TODAY)
        self.assertEqual(h[0][16:20],[115,150,10,15])
        self.assertIn("TARGET HIT",h[0][15])
        self.assertEqual(len(h[0]),len(HOLDING_HEADER))

    def test_etf_and_below_target(self):
        h,_,_=build_portfolio([lot("ETF",kind="ETF")],quotes("ETF",108),TODAY)
        self.assertEqual(h[0][16],108)
        self.assertEqual(h[0][18],10)
        h,_,_=build_portfolio([lot()],quotes(price=114.99),TODAY)
        self.assertNotIn("TARGET HIT",h[0][15])
        self.assertEqual(h[0][18],0)

    def test_weighted_average_and_target_round_up(self):
        rows=[lot(entry=100,qty=2),lot(entry=101,qty=1,trigger="2026-10-16")]
        h,_,m=build_portfolio(rows,quotes(price=116),TODAY)
        self.assertEqual(len(h),1)
        self.assertEqual(h[0][8:10],[3,301])
        self.assertEqual(h[0][16],115.39)
        self.assertEqual(m["open_lots"],2)

    def test_closed_only_and_reentry_preserve_realized(self):
        closed=lot(state="SELL",exit_price=120,exit_date="2026-10-16")
        h,b,m=build_portfolio([closed],quotes(),TODAY)
        self.assertFalse(h)
        self.assertEqual(b[0][7],200)
        self.assertEqual(len(b[0]),len(REALIZED_HEADER))
        self.assertEqual(m["realized"],200)
        h,b,m=build_portfolio([closed,lot(entry=110,qty=2,trigger="2026-10-16")],quotes(),TODAY)
        self.assertEqual(h[0][20:],[200,210])
        self.assertEqual(h[0][9],220)

    def test_pending_sell_not_invented(self):
        for price,day in [("","2026-10-16"),(120,""),(120,"2026-10-18"),(float("nan"),"2026-10-16")]:
            h,b,m=build_portfolio([lot(state="SELL",exit_price=price,exit_date=day)],quotes(),TODAY)
            self.assertFalse(h)
            self.assertEqual(m["pending_sells"],1)
            self.assertEqual(m["realized"],0)
            self.assertIn("PENDING",b[0][11])

    def test_invalid_ledger_rows_stay_excluded(self):
        h,b,m=build_portfolio([lot(state="INVALID DATA"),lot(qty=2.5),lot(entry=float("inf"))],quotes(),TODAY)
        self.assertFalse(h)
        self.assertFalse(b)

    def test_stale_missing_and_future_quote_no_exit(self):
        for data in [quotes(day="2026-10-01"),{},quotes(day="2026-10-18"),quotes(price=float("nan"))]:
            h,_,_=build_portfolio([lot()],data,TODAY)
            self.assertNotIn("TARGET HIT",h[0][15])
            self.assertEqual(h[0][18],0)

    def test_loss_and_repeat_run_do_not_mutate_history(self):
        rows=[lot(state="SELL",exit_price=90,exit_date="2026-10-16")]
        import copy
        original=copy.deepcopy(rows)
        one=build_portfolio(rows,quotes(),TODAY)
        self.assertEqual(one[2]["realized"],-100)
        self.assertEqual(one,build_portfolio(rows,quotes(),TODAY))
        self.assertEqual(rows,original)

if __name__=="__main__":
    unittest.main()
