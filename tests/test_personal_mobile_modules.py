import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'pipelines/mobile'))
import fetcher

class MobileModulesTest(unittest.TestCase):
    def test_module_tariffs_keep_dates_and_context(self):
        target={'name':'5G任我用自选套餐流量包300元','reportNo':'24JS200058','onlineDay':'20200401','offineDay':'20261111','firstConfirmTimeStr':'2026-11-10 16:10:43','fees':'300','feesUnit':'元/月'}
        data={'data':{'beans':[{'tariffName':'任我用自选套餐流量包','nonModuleList':[],
            'moduleList':[{'moduleName':'自选流量包','tariffList':[target]}]}]}}
        result=fetcher._parse_items(data)
        self.assertEqual(len(result),1)
        f=result[0]['fields']
        self.assertEqual(f['上线日期'],'2020年4月1日')
        self.assertEqual(f['下线日期'],'2026年11月11日')
        self.assertEqual(f['方案编号'],'24JS200058')
        self.assertEqual(f['firstConfirmTimeStr'],'2026-11-10 16:10:43')
        self.assertEqual(f['套餐模块'],'自选流量包')
        self.assertEqual(f['资费标准'],'300元/月')

    def test_same_name_different_reports_and_categories_are_not_lost(self):
        a={'name':'同名业务','reportNo':'A'}
        data={'data':{'beans':[{'nonModuleList':[a,a,dict(a,reportNo='B'),dict(a,type2=2)],'moduleList':[]}]}}
        self.assertEqual(len(fetcher._parse_items(data)),3)

if __name__=='__main__':unittest.main()
