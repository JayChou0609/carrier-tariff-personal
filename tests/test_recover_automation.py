import base64
import copy
import datetime as dt
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import recover_automation as r
from refresh_tariffs import TARGETS

MOMENT=dt.datetime(2026,11,13,12,22,tzinfo=r.TZ)
SLOT='2026-11-13T12:00:00+08:00'
def complete():
    return {'latest':{'id':'43368007616-2','targetSlot':SLOT,'sources':[
        {'id':c+':'+s,'status':'updated','started':'2026-11-13T12:01:00+08:00',
         'snapshotTimestamp':'2026-11-13T12:10:00+08:00'}
        for c,scopes in TARGETS.items() for s in scopes]}}
def receipt():
    return {'version':1,'status':'complete','cards':True,'target_slot':SLOT,
            'collection_run':'43368007616-1','buckets':['new','today_off','tomorrow_off']}
class Fake:
    def __init__(self,health=None,runs=None):self.h=health or {};self.r=runs or [];self.sent=[]
    def health(self):return self.h
    def runs(self,workflow):return self.r
    def dispatch(self,workflow,inputs):self.sent.append((workflow,inputs))
class RecoveryTests(unittest.TestCase):
    def test_complete_same_batch_attempt_does_nothing(self):
        api=Fake(receipt());self.assertEqual(r.recover(complete(),api,MOMENT)['status'],'complete');self.assertEqual(api.sent,[])
    def test_partial_or_previous_slot_recollects_in_catch_up_mode(self):
        for case in ['missing','partial','older']:
            s=complete()
            if case=='missing':s['latest']['sources'].pop()
            elif case=='partial':s['latest']['sources'][0]['status']='retained'
            else:
                for source in s['latest']['sources']:source['started']='2026-11-13T00:01:00+08:00'
            api=Fake(receipt());r.recover(s,api,MOMENT)
            self.assertEqual(api.sent,[(r.COLLECTOR,{'catch_up':True})])
    def test_completed_collection_without_notification_recovers_send_only(self):
        for h in [{},dict(receipt(),cards=False),dict(receipt(),target_slot='2026-11-13T00:00:00+08:00'),dict(receipt(),collection_run='111-1')]:
            api=Fake(h);r.recover(complete(),api,MOMENT)
            self.assertEqual(api.sent,[(r.NOTIFIER,{'action':'recover'})])
    def test_active_or_waiting_run_prevents_duplicate_dispatch(self):
        for status in ['queued','in_progress','waiting','pending','requested']:
            api=Fake(runs=[{'status':status}]);self.assertFalse(r.recover({},api,MOMENT)['dispatched']);self.assertEqual(api.sent,[])
    def test_recent_run_waits_but_failed_run_is_retried_after_cooldown(self):
        api=Fake(runs=[{'status':'completed','conclusion':'failure','created_at':'2026-11-13T04:20:00Z'}])
        self.assertEqual(r.recover({},api,MOMENT)['status'],'retry_cooldown')
        api.r[0]['created_at']='2026-11-13T04:10:00Z';self.assertTrue(r.recover({},api,MOMENT)['dispatched'])
    def test_beijing_midnight_and_18_require_fresh_collection(self):
        for h in [0,18]:
            moment=MOMENT.replace(hour=h)
            api=Fake(receipt());r.recover({},api,moment.astimezone(dt.timezone.utc))
            self.assertEqual(api.sent[0][0],r.COLLECTOR)
    def test_bad_receipt_bucket_or_unconfirmed_status_never_counts(self):
        for health in [dict(receipt(),buckets=['new']),dict(receipt(),status='started')]:
            self.assertFalse(r.delivery_complete(health,complete()['latest'],SLOT))
if __name__=='__main__':unittest.main()
