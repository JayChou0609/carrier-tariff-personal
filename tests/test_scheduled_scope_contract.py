import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from monitoring_scopes import TARGETS, REGIONS
from refresh_tariffs import fetch_carrier, merge_reports, FOLDERS, write, read
import wecom_tariffs as notify


class ScopeContractTests(unittest.TestCase):
    def test_collection_and_push_and_cloudflare_share_36_sources(self):
        self.assertEqual(TARGETS,notify.SCOPES)
        self.assertEqual(len(REGIONS),9)
        self.assertTrue(all(len(regions)==9 for regions in TARGETS.values()))
        worker=(ROOT/'cloudflare/tariff-watchdog/worker.mjs').read_text()
        sources=json.loads(re.search(r'const SOURCES = (\[.*?\]);',worker).group(1))
        self.assertEqual(set(sources),{c+':'+r for c,rs in TARGETS.items() for r in rs})

    def test_unicom_artifacts_merge_without_overwriting_other_shards(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'root';incoming=Path(td)/'incoming'
            def collector(carrier,scope,context):
                return [{'id':scope,'title':scope,'detail':{'onDate':'2026-11-15'}}],''
            for group,scopes in [('a',['quanguo','jiangsu','shanghai']),('b',['zhejiang','hebei','henan']),('c',['sichuan','guangdong','gansu'])]:
                fetch_carrier('unicom',root,incoming/('refresh-unicom-'+group),collector,scopes)
            rows=merge_reports(root,incoming)
            self.assertEqual(sum(r['status']=='updated' for r in rows),9)
            self.assertEqual(set(read(root/'unicom/data/_scheduled_sampling.json')),set(TARGETS['unicom']))
            for region in TARGETS['unicom']:
                self.assertEqual(read(root/'unicom/data'/(region+'.json'))['items'][0]['id'],region)

    def test_duplicate_or_unknown_shards_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);incoming=root/'incoming'
            row={'carrier':'unicom','region':'jiangsu','status':'failed'}
            for group in ['a','b']:write(incoming/('refresh-unicom-'+group)/'status.json',{'sources':[row]})
            with self.assertRaisesRegex(ValueError,'重复'):merge_reports(root,incoming)
        with self.assertRaises(ValueError):fetch_carrier('unicom',scopes=['unknown'])
        with self.assertRaises(ValueError):fetch_carrier('unicom',scopes=['jiangsu','jiangsu'])
