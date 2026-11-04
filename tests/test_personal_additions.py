import copy
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from archive_tariffs import capture, put_object
from build_additions import build_additions, fingerprint, beijing_date
from refresh_tariffs import write


def item(id_, title='套餐A', price='39', report='R'):
    return {'id': id_, 'title': title, 'fee': price, 'firstLevel': '套餐',
            'secondLevel': '个人', 'detail': {'reportNo': report, 'offDate': '2030-12-31'}}


class AdditionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'site'
        self.archive = Path(self.temp.name) / 'archive'
        self.row = {'id':'unicom:jiangsu','name':'江苏联通','carrier':'unicom','region':'jiangsu',
                    'path':'unicom/data/jiangsu.json','status':'updated'}

    def save(self, items, day, key, previous=None, baseline=False):
        value = {'timestamp': day+'T12:00:00+08:00', 'items': items}
        write(self.root/self.row['path'], value)
        capture(self.archive, self.root, [self.row], value['timestamp'], key,
                {self.row['id']: {'items':previous}} if previous is not None else {}, baseline)

    def entries(self):
        return build_additions(self.archive, self.root)['sources']['unicom:jiangsu']['items']

    def test_baseline_and_modified_items_never_become_new(self):
        original = item('1')
        self.save([original], '2026-11-03', 'baseline', baseline=True)
        edited = item('1', price='49')
        added = item('2','新套餐',report='NEW')
        self.save([edited,added], '2026-11-04', 'update', [original])
        dates = self.entries()
        self.assertNotIn(fingerprint(edited), dates)
        self.assertEqual(dates, {fingerprint(added):'2026-11-04'})
        self.assertEqual(self.entries(), dates)  # rebuilding is deterministic

    def test_id_drift_title_changes_and_reappearance_keep_first_added_day(self):
        baseline = item('base','基础套餐',report='B')
        first = item('new','新增套餐',report='N')
        self.save([baseline], '2026-11-01', 'base', baseline=True)
        self.save([baseline,first], '2026-11-02', 'add', [baseline])
        drift = item('changed','新增套餐',price='49',report='N2')
        self.save([baseline,drift], '2026-11-03', 'drift', [baseline,first])
        renamed = item('changed','重命名套餐',price='59',report='N2')
        self.save([baseline,renamed], '2026-11-04', 'rename', [baseline,drift])
        self.save([baseline], '2026-11-05', 'remove', [baseline,renamed])
        self.save([baseline,first], '2026-11-06', 'return', [baseline])
        dates = self.entries()
        for it in [first,drift,renamed]:
            self.assertEqual(dates[fingerprint(it)], '2026-11-02')

    def test_shared_report_and_same_title_different_businesses_stay_separate(self):
        old = item('old','旧业务',report='SHARED')
        added = item('new','新业务',report='SHARED')
        another = item('third','新业务',report='SHARED')
        another['firstLevel']='加装包'
        self.save([old], '2026-11-03', 'base', baseline=True)
        self.save([old,added,another], '2026-11-04', 'update', [old])
        self.assertEqual(self.entries(), {fingerprint(added):'2026-11-04',fingerprint(another):'2026-11-04'})

    def test_a_new_business_reusing_an_old_report_number_is_still_new(self):
        old = item('old','已下架旧业务',report='REUSED')
        other = item('other','独立业务',report='OTHER')
        new = item('new','全新业务',report='REUSED')
        self.save([old,other], '2026-11-01', 'base', baseline=True)
        self.save([other], '2026-11-02', 'remove', [old,other])
        self.save([other,new], '2026-11-03', 'new', [other])
        self.assertEqual(self.entries()[fingerprint(new)], '2026-11-03')

    def test_empty_failed_and_late_baseline_do_not_fabricate_new_records(self):
        old = item('old')
        self.save([old], '2026-11-03', 'base', baseline=True)
        self.row['status']='failed'
        self.save([old], '2026-11-04', 'failed', [old])
        self.row['status']='updated'
        self.save([old,item('new','补充基线')], '2026-11-05', 'late-base', baseline=True)
        self.assertEqual(self.entries(), {})

    def test_dates_are_beijing_calendar_dates(self):
        self.assertEqual(beijing_date('2026-11-03T16:01:00Z'),'2026-11-04')
        self.assertEqual(beijing_date('2026-11-03T15:59:00Z'),'2026-11-03')

    def test_tampered_archive_fails_before_replacing_good_index(self):
        self.save([item('old')], '2026-11-03', 'base', baseline=True)
        self.entries()
        previous=(self.root/'data/additions.json').read_bytes()
        path=next(self.archive.glob('objects/*/*.gz'))
        import gzip
        path.write_bytes(gzip.compress(b'{"items":[]}'))
        with self.assertRaisesRegex(ValueError,'Corrupt archive'):
            self.entries()
        self.assertEqual((self.root/'data/additions.json').read_bytes(),previous)

    def test_mobile_raw_and_normalized_delta_use_the_same_identity(self):
        raw={'name':'移动套餐','fields':{'归属':'个人资费','资费类型':'套餐','方案编号':'A','资费标准':'39元/月'}}
        normalized={'id':'','title':'移动套餐','firstLevel':'个人资费','secondLevel':'套餐','detail':raw['fields']}
        self.assertEqual(fingerprint(raw),fingerprint(normalized))


if __name__=='__main__':
    unittest.main()
