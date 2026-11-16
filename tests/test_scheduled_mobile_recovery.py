import sys
from pathlib import Path
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from refresh_tariffs import TARGETS, FOLDERS, write, read, merge_reports


class FailedSourceRecoveryTests(unittest.TestCase):
    def fixture(self,root,incoming,carrier,failed):
        base=incoming/('refresh-'+carrier+'-all')
        rows=[]
        for region in TARGETS[carrier]:
            item={'id':'old','title':'原有资费','detail':{'offDate':'2035-01-01'}}
            path=Path(FOLDERS[carrier])/(region+'.json')
            write(root/path,{'items':[item]})
            write(base/'files'/path,{'items':[item]})
            rows.append({'carrier':carrier,'region':region,'status':'retained' if region==failed else 'updated'})
        write(base/'status.json',{'sources':rows})

    def test_failed_mobile_is_recollected_before_being_marked_updated(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'root';incoming=Path(td)/'incoming'
            self.fixture(root,incoming,'mobile','henan')
            calls=[]
            def fetch(carrier,region,context):
                calls.append((carrier,region));return [{'id':'fresh','name':'河南正式资费'}],''
            rows=merge_reports(root,incoming,fetch)
            self.assertEqual(calls,[('mobile','henan')])
            row=next(x for x in rows if x['id']=='mobile:henan')
            self.assertEqual(row['status'],'updated');self.assertEqual(row['recovery'],'archive_retry')
            self.assertEqual(read(root/'data/henan.json')['items'][0]['id'],'fresh')

    def test_failure_stays_retained_and_preserves_existing_data(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'root';incoming=Path(td)/'incoming'
            self.fixture(root,incoming,'mobile','henan')
            rows=merge_reports(root,incoming,lambda *args:([],'官方分类仍失败'))
            row=next(x for x in rows if x['id']=='mobile:henan')
            self.assertEqual(row['status'],'retained')
            self.assertEqual(read(root/'data/henan.json')['items'][0]['id'],'old')

    def test_unicom_recovery_keeps_unobserved_unexpired_records(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'root';incoming=Path(td)/'incoming'
            self.fixture(root,incoming,'unicom','quanguo')
            rows=merge_reports(root,incoming,lambda *args:([{'id':'new','title':'新资费','detail':{'offDate':'2035-01-01'}}],''))
            row=next(x for x in rows if x['id']=='unicom:quanguo')
            self.assertEqual(row['status'],'updated')
            self.assertEqual({x['id'] for x in read(root/'unicom/data/quanguo.json')['items']},{'old','new'})
