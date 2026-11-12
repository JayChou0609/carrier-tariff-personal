import copy
import datetime as dt
import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import wecom_tariffs as app

KEY = '00000000-0000-0000-0000-000000000000'
CONFIG = {'wecom_webhook':'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key='+KEY}
DAY = dt.date(2026,11,11)


def raw(title='资费A', on='2026年11月11日', off='2026年11月12日'):
    return {'name':title,'fields':{'方案编号':'R1','归属':'个人资费','资费类型':'套餐',
                                 '资费标准':'39元/月','上线日期':on,'下线日期':off}}


def report():
    row=app.normalize(raw(),'mobile:jiangsu','2026-11-11T12:00:00+08:00')
    return {'day':'2026-11-11','generated':'2026-11-11T12:00:00+08:00',
            'sources':[{'id':'mobile:jiangsu','status':'downloaded'}],
            'buckets':{'new':[row],'today_off':[],'tomorrow_off':[row]}}


class DummyClient:
    def __init__(self, fail=False):self.sent=[];self.uploads=[];self.fail=fail
    def send(self, kind, body):self.sent.append((kind,body));return 'ok'
    def upload_csv(self,name,body):
        if self.fail:raise app.WeComError('upload unavailable')
        self.uploads.append((name,body));return 'media-1'


class PushTests(unittest.TestCase):
    def test_cards_send_image_then_text_and_do_not_repeat(self):
        import base64,hashlib
        self.ready();client=DummyClient();r=report()
        with patch.dict(app.os.environ,{'WECOM_TARIFF_CARDS':'1'}),patch('wecom_cards.render_card',return_value=b'image-data'):
            app.send_report(r,self.config,self.state,client)
            images=[body for kind,body in client.sent if kind=='image']
            self.assertEqual(len(images),2)
            self.assertEqual(base64.b64decode(images[0]['base64']),b'image-data')
            self.assertEqual(images[0]['md5'],hashlib.md5(b'image-data').hexdigest())
            before=len(client.sent)
            self.assertEqual(app.send_report(r,self.config,self.state,client)['sent'],0)
            self.assertEqual(before,len(client.sent))

    def test_each_completed_collection_sends_full_cards_but_retry_does_not(self):
        self.ready();client=DummyClient();r=report()
        with patch.dict(app.os.environ,{'WECOM_TARIFF_CARDS':'1'}),patch('wecom_cards.render_card',return_value=b'image'):
            for collection in ['morning-1','noon-1','evening-1']:
                r['collection_run']=collection
                client.sent=[]
                result=app.send_report(r,self.config,self.state,client)
                self.assertEqual(sum(kind=='image' for kind,_ in client.sent),2)
                self.assertEqual(sum(kind=='text' for kind,_ in client.sent),5)
                self.assertGreaterEqual(result['sent'],7)
                self.assertEqual(app.send_report(r,self.config,self.state,client)['sent'],0)
            self.assertEqual(len(client.uploads),2) # Business CSV remains daily-deduped.

    def test_new_batch_card_text_failure_resumes_after_accepted_image(self):
        class FailingClient(DummyClient):
            fail_once=False
            def send(self,kind,body):
                if self.fail_once and kind=='text' and self.sent and self.sent[-1][0]=='image':
                    self.fail_once=False
                    raise app.WeComError('interrupted card text')
                return super().send(kind,body)
        self.ready();client=FailingClient();r=report();r['collection_run']='morning-1'
        with patch.dict(app.os.environ,{'WECOM_TARIFF_CARDS':'1'}),patch('wecom_cards.render_card',return_value=b'image'):
            app.send_report(r,self.config,self.state,client)
            r['collection_run']='noon-1';client.sent=[];client.fail_once=True
            with self.assertRaises(app.WeComError):app.send_report(r,self.config,self.state,client)
            (self.state/'blocked.json').unlink()
            app.send_report(r,self.config,self.state,client)
            self.assertEqual(sum(kind=='image' for kind,_ in client.sent),2)
            self.assertEqual(app.send_report(r,self.config,self.state,client)['sent'],0)

    def test_card_does_not_call_confirmation_a_second_launch(self):
        from wecom_cards import text_card
        row=app.normalize(raw(),'mobile:jiangsu','2026-11-11')
        fields=json.loads(row['details']);fields['firstConfirmTimeStr']='2026-11-10 16:10:43'
        row['details']=json.dumps(fields,ensure_ascii=False)
        content=text_card(row,'今日下线')
        self.assertIn('重新上线日期：无已确认记录',content)
        self.assertIn('官方确认时间：2026-11-10 16:10:43',content)

    def test_card_text_failure_resumes_without_repeating_accepted_image(self):
        class FailAfterImage(DummyClient):
            fail_once=True
            def send(self,kind,body):
                if self.fail_once and kind=='text' and self.sent and self.sent[-1][0]=='image':
                    self.fail_once=False
                    raise app.WeComError('text connection failed')
                return super().send(kind,body)
        self.ready();client=FailAfterImage();r=report()
        with patch.dict(app.os.environ,{'WECOM_TARIFF_CARDS':'1'}),patch('wecom_cards.render_card',return_value=b'image'):
            with self.assertRaises(app.WeComError):app.send_report(r,self.config,self.state,client)
            (self.state/'blocked.json').unlink()
            app.send_report(r,self.config,self.state,client)
        self.assertEqual(sum(kind=='image' for kind,_ in client.sent),2)

    def test_three_beijing_slots_use_correct_day_and_tomorrow_across_midnight(self):
        for hour in [0,12,18]:
            moment=dt.datetime(2026,11,12,hour,0,tzinfo=app.TZ)
            with tempfile.TemporaryDirectory() as td,patch.object(app,'now',return_value=moment):
                state=Path(td)
                r=app.collect(state_dir=state,loader=lambda u:{'timestamp':'2026-11-12T00:00:00+08:00','items':[raw(on='2026-11-12',off='2026-11-13')]})
                self.assertEqual(r['day'],'2026-11-12')
                self.assertEqual(len(r['buckets']['new']),17)
                self.assertEqual(len(r['buckets']['tomorrow_off']),17)
                self.assertFalse(r['buckets']['today_off'])
                config=app.validate_config(CONFIG)
                app.write_json(state/'ready.json',{'scope':app.config_hash(config)})
                app.send_report(r,config,state,DummyClient())
                ledger=app.read_json(state/'delivery.json')
                self.assertTrue(all(v['slots']==[hour] for v in ledger.values()))

    def test_summary_shows_source_snapshot_dates_even_without_new_rows(self):
        r=report();r['sources'][0]['snapshot']='2026-11-11T06:18:37+08:00'
        self.assertIn('2026-11-11T06:18:37+08:00',app.summary(r,'new',[]))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.state=Path(self.temp.name)/'.private'
        self.config=app.validate_config(CONFIG)

    def ready(self):
        app.write_json(self.state/'ready.json',{'scope':app.config_hash(self.config)})

    def test_new_collection_reports_all_three_categories_even_after_earlier_slot_send(self):
        self.ready();client=DummyClient();r=report()
        app.send_report(r,self.config,self.state,client)
        r['collection_run']='43001466760-2'
        client.sent=[]
        self.assertEqual(app.send_report(r,self.config,self.state,client)['sent'],3)
        self.assertEqual([x[1]['content'].split('】')[0]+'】' for x in client.sent],
                         ['【今日上线】','【明日下线】','【今日下线】'])
        self.assertEqual(app.send_report(r,self.config,self.state,client)['sent'],0)
        r['collection_run']='43001466760-3'
        self.assertEqual(app.send_report(r,self.config,self.state,client)['sent'],3)

    def test_official_dates_exclude_capture_and_confirmation_dates(self):
        x=raw(on='');x['fields']['firstConfirmTimeStr']='2026-11-11 12:00:00';x['timestamp']='2026-11-11'
        self.assertEqual(app.normalize(x,'mobile:jiangsu','2026-11-11')['on_date'],'')
        self.assertEqual(app.date_day('2028-02-29'),'2028-02-29')
        self.assertEqual(app.date_day('2026-02-30'),'')
        self.assertEqual(app.date_day('2026-11-10T16:01:00Z'),'2026-11-11')

    def test_four_nationals_twelve_provinces_are_classified_independently(self):
        def loader(url):return {'timestamp':'2026-11-11T12:00:00+08:00','items':[raw()]}
        r=app.collect(DAY,state_dir=self.state,loader=loader)
        self.assertEqual(len(r['sources']),17)
        self.assertEqual(len(r['buckets']['new']),17)
        self.assertEqual(len(r['buckets']['tomorrow_off']),17)
        self.assertFalse(r['buckets']['today_off'])

    def test_total_failure_is_not_a_zero_report(self):
        with self.assertRaisesRegex(RuntimeError,'全部数据源'):
            app.collect(DAY,state_dir=self.state,loader=lambda u:(_ for _ in ()).throw(OSError()))

    def test_cached_data_is_explicitly_marked(self):
        app.write_json(self.state/'cache/mobile-jiangsu.json',{'timestamp':'2026-11-10T00:00:00+08:00','items':[raw()]})
        r=app.collect(DAY,state_dir=self.state,loader=lambda u:(_ for _ in ()).throw(OSError()))
        self.assertEqual(sum(s['status']=='cached' for s in r['sources']),1)
        self.assertEqual(sum(s['status']=='failed' for s in r['sources']),16)
        self.assertEqual(len(r['buckets']['new']),1)

    def test_webhook_rejects_other_destinations_and_query_injection(self):
        for value in ['http://qyapi.weixin.qq.com/cgi-bin/webhook/send?key='+KEY,
                      'https://attacker.test/cgi-bin/webhook/send?key='+KEY,
                      CONFIG['wecom_webhook']+'&other=x',CONFIG['wecom_webhook']+'#bad']:
            with self.assertRaises(ValueError):app.validate_config({'wecom_webhook':value})

    def test_secret_is_private_and_not_in_errors(self):
        app.write_json(self.state/'config.json',self.config)
        self.assertEqual((self.state/'config.json').stat().st_mode & 0o777,0o600)
        self.assertEqual(self.state.stat().st_mode & 0o777,0o700)
        self.assertNotIn(KEY,app.Client(self.config).redact(CONFIG['wecom_webhook']))

    def test_no_send_until_target_group_is_tested(self):
        client=DummyClient();result=app.send_report(report(),self.config,self.state,client)
        self.assertEqual(result['status'],'not_verified');self.assertFalse(client.sent)

    def test_same_slot_deduplicates_but_next_slot_sends_three_summaries(self):
        self.ready();client=DummyClient()
        with patch.object(app,'now',return_value=dt.datetime(2026,11,11,0,5,tzinfo=app.TZ)):
            self.assertEqual(app.send_report(report(),self.config,self.state,client)['sent'],5)
            self.assertEqual(app.send_report(report(),self.config,self.state,client)['sent'],0)
        with patch.object(app,'now',return_value=dt.datetime(2026,11,11,12,5,tzinfo=app.TZ)):
            self.assertEqual(app.send_report(report(),self.config,self.state,client)['sent'],3)
        self.assertEqual(len(client.uploads),2)

    def test_failures_keep_summary_checkpoint_and_stop_unattended_retry(self):
        self.ready();bad=DummyClient(fail=True)
        with self.assertRaises(app.WeComError):app.send_report(report(),self.config,self.state,bad)
        self.assertEqual(len(bad.sent),1)
        with self.assertRaises(app.WeComError):app.send_report(report(),self.config,self.state,DummyClient())
        (self.state/'blocked.json').unlink();good=DummyClient()
        app.send_report(report(),self.config,self.state,good)
        self.assertEqual(good.sent[0][0],'file')

    def test_snapshot_and_confirmation_updates_do_not_repeat_business(self):
        a=raw();b=copy.deepcopy(a);b['fields']['firstConfirmTimeStr']='2026-11-11 18:00:00'
        self.assertEqual(app.normalize(a,'mobile:jiangsu','old')['version'],app.normalize(b,'mobile:jiangsu','new')['version'])

    def test_messages_fit_text_limit_and_csv_preserves_rows(self):
        r=report();row=r['buckets']['new'][0];row['title']='测试'*1000;row['fee']='资费'*1000
        self.assertLessEqual(len(app.summary(r,'new',[row]).encode()),1900)
        row['title']='=formula'
        output=app.csv_bytes([row]).decode('utf-8-sig')
        self.assertIn("'=formula",output)
        self.assertIn('2026-11-12',output)

    def test_payload_uses_robot_endpoint_without_application_credentials(self):
        client=app.Client(self.config)
        with patch.object(client,'request',return_value={'errcode':0}) as send:
            client.send('text',{'content':'测试'})
        endpoint,payload=send.call_args.args
        self.assertTrue(endpoint.startswith('webhook/send?key='))
        self.assertEqual(payload,{'msgtype':'text','text':{'content':'测试'}})
        self.assertNotIn('agentid',payload)

    def test_missing_api_acknowledgement_never_counts_as_success(self):
        client=app.Client(self.config)
        with patch.object(app.urllib.request,'urlopen') as request:
            request.return_value.__enter__.return_value=io.BytesIO(b'{"ok":true}')
            with self.assertRaisesRegex(app.WeComError,'未确认发送成功'):
                client.send('text',{'content':'test'})


if __name__=='__main__':unittest.main()
