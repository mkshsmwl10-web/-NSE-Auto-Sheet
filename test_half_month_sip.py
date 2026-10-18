import unittest
from datetime import date
from types import SimpleNamespace
import pandas as pd
from half_month_scanner import get_sip_budgets, build_row
from half_month_positions import historic_signal

ITEM=("ETF","Nifty 50","Nifty BeES","NIFTYBEES")

def fake_book(row):
    return SimpleNamespace(worksheet=lambda name:SimpleNamespace(get_all_values=lambda:[['Type','Sector','Name','NSE Code','SIP','Account'],row]))

class SipTests(unittest.TestCase):
    def test_live_linked_sip_and_nonreal_default(self):
        self.assertEqual(get_sip_budgets(fake_book([*ITEM,'6000','REAL']),[ITEM]),{'NIFTYBEES':6000})
        self.assertEqual(get_sip_budgets(fake_book([*ITEM,'9000','PAPER']),[ITEM]),{'NIFTYBEES':5000})

    def test_invalid_real_config_never_falls_back(self):
        for val in ['', 'DUPLICATE SIP', '-1', 'NaN', 'inf']:
            with self.assertRaises(ValueError):
                get_sip_budgets(fake_book([*ITEM,val,'REAL']),[ITEM])

    def test_zero_sip_pauses_new_plan(self):
        self.assertEqual(get_sip_budgets(fake_book([*ITEM,'0','REAL']),[ITEM]),{'NIFTYBEES':0})

    def test_signal_and_ledger_use_same_budget(self):
        idx=pd.to_datetime(['2026-10-01','2026-10-02','2026-10-05','2026-10-06','2026-10-07','2026-10-16'])
        frame=pd.DataFrame({'High':[105]*6,'Low':[100]*5+[99],'Close':[102]*6},index=idx)
        row=build_row(ITEM,frame,'',date(2026,10,17),date(2026,10,16),budget=6500)
        self.assertEqual(row[15:17],[6500,65])
        record=historic_signal(ITEM,frame,date(2026,10,16),date(2026,10,31),date(2026,10,17),'PAPER',budget=6500)
        self.assertEqual(record[9],65)
        self.assertEqual(record[10:12],['PAPER','OPEN'])

if __name__=='__main__':
    unittest.main()
