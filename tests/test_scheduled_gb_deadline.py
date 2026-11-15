from pathlib import Path
import signal
import sys
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pipelines'))
from gb_pipeline import request_deadline
import gb_pipeline
from unittest.mock import patch
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from refresh_tariffs import TARGETS, merge_reports, write, read


class GBDeadlineTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(signal,'setitimer'),'POSIX collector deadline')
    def test_slow_read_is_bounded_and_signal_handler_restored(self):
        previous=signal.getsignal(signal.SIGALRM)
        with self.assertRaises(TimeoutError):
            with request_deadline(.02):
                time.sleep(.1)
        self.assertIs(signal.getsignal(signal.SIGALRM),previous)
        with request_deadline(.1):
            pass
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0],0)

    def test_failed_leaf_retry_preserves_official_duplicate_order(self):
        calls=[]
        def post(path,body):
            leaf=body['type3'];calls.append(leaf)
            if calls==['A']:
                raise TimeoutError('cold TLS connection')
            return {'data':[{'id':'shared','productName':leaf}]}
        tree=[('GZ',None,[('GZ_TC',[('A',),('B',)])])]
        with patch.object(gb_pipeline,'_post',side_effect=post),patch.object(gb_pipeline.time,'sleep'):
            rows,failed=gb_pipeline.query(tree,'SC00')
        self.assertEqual(calls,['A','B','A'])
        self.assertEqual(failed,0)
        self.assertEqual(rows[0]['productName'],'A')

    def test_archive_retries_failed_source_with_fresh_official_data(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'root';incoming=Path(td)/'incoming';base=incoming/'refresh-gb-c'
            rows=[]
            for region in TARGETS['gb']:
                raw={'items':[{'id':region,'title':'旧资费'}],'timestamp':'2026-11-15T18:00:00+08:00'}
                write(root/'gb/data'/(region+'.json'),raw)
                write(base/'files/gb/data'/(region+'.json'),raw)
                rows.append({'carrier':'gb','region':region,'status':'retained' if region=='sichuan' else 'updated'})
            write(base/'status.json',{'sources':rows})
            calls=[]
            def collector(carrier,scope,context):
                calls.append((carrier,scope))
                return [{'id':'fresh','title':'新采集的官方资费'}],''
            report=merge_reports(root,incoming,collector)
            fixed=next(row for row in report if row['id']=='gb:sichuan')
            self.assertEqual(calls,[('gb','sichuan')])
            self.assertEqual(fixed['status'],'updated')
            self.assertEqual(fixed['recovery'],'archive_retry')
            self.assertEqual(read(root/'gb/data/sichuan.json')['items'][0]['id'],'fresh')
