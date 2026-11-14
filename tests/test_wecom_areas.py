import copy
import json
from pathlib import Path
import re
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from tariff_areas import display_area, display_fields, AREA_CODES
from wecom_cards import card_fields, text_card
from wecom_tariffs import normalize, csv_bytes


class AreaDisplayTests(unittest.TestCase):
    def test_official_cities_and_provinces(self):
        self.assertEqual(display_area('5160','mobile'),'徐州')
        self.assertEqual(display_area('5160、0250,GS，0210','mobile'),'徐州、南京、甘肃、上海')
        self.assertEqual(display_area('000','mobile'),'全国')
        self.assertEqual(display_area('JS00','gb'),'江苏')
        self.assertEqual(display_area('600103','telecom'),'江苏')

    def test_no_guessing_or_code_leaks(self):
        self.assertEqual(display_area('5160','unicom'),'适用地区待核验')
        for value in ['999999','!AH','UNKNOWN','5169']:
            self.assertEqual(display_area(value,'mobile'),'适用地区待核验')
        self.assertEqual(display_area('江苏省内31个地区','mobile'),'江苏省内31个地区')
        self.assertEqual(display_area('徐州、5160','mobile'),'徐州')

    def test_cards_csv_and_original_identity(self):
        raw={'name':'全球通尊享权益-2档（3个月）','fields':{'方案编号':'26JS201985','适用地区':'5160','上线日期':'2026-10-16','下线日期':'2026-11-14','资费标准':'0元/月'}}
        before=copy.deepcopy(raw)
        row=normalize(raw,'mobile:jiangsu','2026-11-14T00:06:31+08:00')
        original=copy.deepcopy(row)
        self.assertEqual(dict(card_fields(row))['适用地区'],'徐州')
        self.assertIn('适用地区：徐州',text_card(row,'今日下线'))
        self.assertNotIn('5160',text_card(row,'今日下线'))
        self.assertIn('徐州',csv_bytes([row]).decode('utf-8-sig'))
        self.assertEqual(raw,before)
        self.assertEqual(row,original)
        self.assertEqual(json.loads(row['details'])['适用地区'],'5160')

    def test_browser_dictionary_matches_canonical(self):
        script=(ROOT/'custom/area-names.js').read_text()
        mobile=json.loads(re.search(r'const mobileCodes = (\{.*?\});',script).group(1))
        other=json.loads(re.search(r'const carrierCodes = (\{.*?\});',script).group(1))
        self.assertEqual(mobile,AREA_CODES['mobile'])
        self.assertEqual(other,{k:AREA_CODES[k] for k in ['gb','telecom']})
