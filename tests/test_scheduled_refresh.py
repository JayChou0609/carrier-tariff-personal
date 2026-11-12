import copy
import datetime as dt
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from refresh_tariffs import (TARGETS, FOLDERS, acceptable, changes, fetch_carrier,
                             merge_sample, merge_reports, read, write)
from archive_tariffs import capture, put_object, publish_indexes, seed_legacy, collection_complete


def item(identity='1', fee='39', title='套餐A'):
    return {'id': identity, 'title': title, 'fee': fee, 'firstLevel': '套餐',
            'detail': {'feesStandard': fee, 'commonData': '30', 'offDate': '2035-12-31'}}


class ScheduledTest(unittest.TestCase):
    def test_partial_retained_collection_is_not_a_complete_success(self):
        rows=[{'id':c+':'+s,'status':'updated'} for c,scopes in TARGETS.items() for s in scopes]
        self.assertTrue(collection_complete(rows))
        for status in ['retained','failed','not_connected']:
            changed=copy.deepcopy(rows);changed[0]['status']=status
            self.assertFalse(collection_complete(changed))
        self.assertFalse(collection_complete(rows[:-1]))
        self.assertFalse(collection_complete(rows[:-1]+[rows[0]]))

    def test_scope_list_and_cron(self):
        self.assertEqual(sum(len(x) for x in TARGETS.values()), 17)
        self.assertEqual(TARGETS['unicom'], ['quanguo','jiangsu','shanghai','hebei','henan','sichuan','guangdong'])
        path = ROOT / '.github/workflows'
        text = (path / 'scheduled-refresh.yml').read_text()
        self.assertIn('"0 0,12,18 * * *"', text)
        self.assertIn('timezone: Asia/Shanghai',text)
        self.assertIn('"7,27,47 * * * *"',text)
        self.assertIn('cancel-in-progress: false', text)
        for filename in ['mobile-build.yml','telecom-gb-fetch.yml','unicom-fetch.yml','province-notify.yml']:
            self.assertNotIn('\n  schedule:', (path / filename).read_text())

    def test_telecom_official_province_codes_and_fresh_sessions(self):
        from unittest.mock import patch
        import telecom_pipeline as t
        self.assertEqual({s:t.SCOPES[s]['prov'] for s in ['jiangsu','shanghai','zhejiang']},
                         {'jiangsu':'600103','shanghai':'600102','zhejiang':'600104'})
        issued=[]
        def call(fn, request):
            if fn=='tariffSectionHome':
                session='new-session-'+str(len(issued));issued.append(session)
                self.assertEqual(request['sessionid'],'')
                return {'responseContent':{'provCode':request['provCode'],'sessionid':session,
                                            'lableOneList':[{'id':'A','name':'套餐'}]}}
            self.assertEqual(request['sessionid'],issued[-1])
            return {'responseContent':{'zoneTitleListCount':1,
                    'zoneTitleList':[{'id':'official','name':'已核验套餐','fees':'59'}]}}
        with patch.object(t,'call',side_effect=call),patch.object(t.time,'sleep'):
            for scope in ['jiangsu','shanghai','zhejiang']:
                self.assertEqual(len(t.fetch_scope(scope,t.SCOPES[scope]['prov'])),1)
        self.assertEqual(len(set(issued)),3)

    def test_telecom_rejects_wrong_province_or_truncated_category(self):
        from unittest.mock import patch
        import telecom_pipeline as t
        with patch.object(t,'call',return_value={'responseContent':{'provCode':'wrong'}}):
            with self.assertRaisesRegex(ValueError,'编码与请求不一致'):t.home('600103')
        with patch.object(t,'home',return_value={'sessionid':'fresh','lableOneList':[{'id':'A'}]}), \
             patch.object(t,'query',return_value={'zoneTitleListCount':2,'zoneTitleList':[{'name':'A'}]}):
            with self.assertRaisesRegex(ValueError,'被截断'):t.fetch_scope('jiangsu','600103')

    def test_failure_empty_and_drop_never_overwrite(self):
        for data, error in [([], ''), ([item()], 'timeout')]:
            with self.assertRaises(ValueError): acceptable([item()], data, error)
        with self.assertRaises(ValueError): acceptable([item(str(x)) for x in range(10)], [item()])

    def test_mobile_field_changes_detected(self):
        a = {'name':'移动套餐','fields':{'资费类型':'套餐','归属':'个人资费','资费标准':'39元/月'}}
        b = copy.deepcopy(a);b['fields']['资费标准']='49元/月'
        delta = changes([a], [b])
        self.assertEqual(len(delta['modified_items']), 1)
        self.assertFalse(delta['added_items'])

    def test_missing_unicom_sample_is_retained(self):
        old = [item(), item('2', title='套餐B')]
        counters = {}
        for _ in range(10):
            result = merge_sample(old, [old[0]], counters, dt.date(2026,11,3))
            self.assertEqual(len(result), 2)
        self.assertEqual(counters['2'], 10)

    def test_expired_unicom_requires_six_misses(self):
        old = [item(), item('2', title='旧套餐')]
        old[1]['detail']['offDate'] = '2020-01-01'
        counters = {}
        for _ in range(5): self.assertEqual(len(merge_sample(old,[old[0]],counters,dt.date(2026,11,3))),2)
        self.assertEqual(len(merge_sample(old,[old[0]],counters,dt.date(2026,11,3))),1)

    def test_unicom_missing_detail_preserves_known_fields(self):
        result = merge_sample([item()], [dict(item(fee='49'), detail={})], {}, dt.date(2026,11,3))
        self.assertEqual(result[0]['fee'], '39')

    def test_collector_isolates_missing_provinces_and_does_not_mutate_old(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);old={'timestamp':'old','items':[item()]}
            write(root/'telecom/data/quanguo.json',old)
            def collect(c,s,ctx):
                if s!='quanguo':raise NotImplementedError('not connected')
                return [item(fee='49')], ''
            report=fetch_carrier('telecom',root,collector=collect)
            self.assertEqual(report[0]['status'],'updated')
            self.assertEqual([r['status'] for r in report[1:]],['not_connected']*3)
            self.assertEqual(read(root/'telecom/data/quanguo.json'),old)
            self.assertEqual(read(root/'_refresh/refresh-telecom/files/telecom/data/quanguo.json')['items'][0]['fee'],'49')

    def test_missing_artifacts_preserve_all_snapshots(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);old={'timestamp':'old','items':[item()]}
            write(root/'data/quanguo.json',old)
            rows=merge_reports(root,root/'no-artifacts')
            self.assertEqual(len(rows),17)
            self.assertTrue(all(r['status']=='failed' for r in rows))
            self.assertEqual(read(root/'data/quanguo.json'),old)

    def test_immutable_deduplicated_archive_and_full_fields(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'site';archive=Path(td)/'archive'
            old={'timestamp':'2026-11-03T00:00:00+08:00','items':[item()]}
            old['items'][0]['detail']['serviceContent']='完整详情'*1000
            write(root/'data/quanguo.json',old)
            row={'id':'mobile:quanguo','carrier':'mobile','region':'quanguo','name':'全国移动','path':'data/quanguo.json','status':'updated'}
            first=capture(archive,root,[row],'2026-11-03T00:00:00+08:00','r1',baseline=True)
            old['timestamp']='2026-11-03T12:00:00+08:00';write(root/row['path'],old)
            second=capture(archive,root,[row],'2026-11-03T12:00:00+08:00','r2',baseline=True)
            self.assertEqual(first['sources'][0]['snapshot'],second['sources'][0]['snapshot'])
            stored=json.loads(gzip.decompress((archive/first['sources'][0]['snapshot']).read_bytes()))
            self.assertEqual(stored['items'][0]['detail']['serviceContent'],'完整详情'*1000)
            with self.assertRaises(ValueError):capture(archive,root,[row],'2026-11-03T12:00:00+08:00','r2')

    def test_archive_retains_more_than_sixty_runs_and_all_original_history(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'site';archive=Path(td)/'archive'
            original=[{'ts':str(i),'full_detail':'x'*1000} for i in range(100)]
            write(root/'data/history.json',original)
            seed_legacy(archive,root)
            write(root/'data/history.json',[]);seed_legacy(archive,root)
            self.assertEqual(json.loads(gzip.decompress((archive/'legacy/mobile-history.json.gz').read_bytes())),original)
            for i in range(65):capture(archive,root,[],'2026-11-03T00:00:00+08:00','r'+str(i))
            publish_indexes(archive,root,'JayChou0609/carrier-tariff-personal')
            self.assertEqual(len(read(root/'history/data/2026.json')['runs']),65)

    def test_archive_missing_source_has_no_fabricated_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'site';archive=Path(td)/'archive'
            row={'id':'telecom:jiangsu','name':'江苏电信','path':'telecom/data/jiangsu.json','status':'not_connected'}
            report=capture(archive,root,[row],'2026-11-03T00:00:00+08:00','r1')
            self.assertIsNone(report['sources'][0]['snapshot'])
            self.assertIsNone(report['sources'][0]['count'])

    def test_archive_modifications_include_before_snapshot_and_details(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'site';archive=Path(td)/'archive'
            row={'id':'unicom:jiangsu','name':'江苏联通','path':'unicom/data/jiangsu.json','status':'updated'}
            old={'items':[item()]};write(root/row['path'],{'items':[item(fee='49')]})
            record=capture(archive,root,[row],'2026-11-03T12:00:00+08:00','r1',{'unicom:jiangsu':old})
            entry=record['sources'][0]
            self.assertEqual(entry['modified'],1)
            self.assertIn('previousSnapshot',entry)
            delta=json.loads(gzip.decompress((archive/entry['changes']).read_bytes()))
            self.assertEqual(delta['modified_items'][0]['fee'],'49')
            self.assertTrue(delta['modified_details'])


if __name__=='__main__':unittest.main()
