import copy
import datetime as dt
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from schedule_guard import decide,TZ
from refresh_tariffs import TARGETS


def status(start='2026-11-12T12:00:01+08:00'):
    return {'latest':{'id':'123-1','baseline':False,'sources':[
        {'id':c+':'+r,'status':'updated','started':start,'snapshotTimestamp':start}
        for c,regions in TARGETS.items() for r in regions]}}


class GuardTests(unittest.TestCase):
    def at(self,hour,minute=0):return dt.datetime(2026,11,12,hour,minute,tzinfo=TZ)
    def test_all_three_main_slots_and_utc_conversion(self):
        for h in [0,12,18]:
            r=decide({},self.at(h).astimezone(dt.timezone.utc))
            self.assertTrue(r['collect']);self.assertEqual(r['target_slot'],self.at(h).isoformat())
    def test_completed_current_slot_skips_but_manual_always_collects(self):
        self.assertFalse(decide(status(),self.at(14,47))['collect'])
        self.assertTrue(decide(status(),self.at(14,47),force=True)['collect'])
    def test_each_new_slot_requires_fresh_collection(self):
        self.assertTrue(decide(status('2026-11-12T06:33:00+08:00'),self.at(12,7))['collect'])
        self.assertTrue(decide(status(),self.at(18,7))['collect'])
        r=decide(status('2026-11-11T19:45:00+08:00'),self.at(0,7))
        self.assertTrue(r['collect']);self.assertTrue(r['target_slot'].startswith('2026-11-12T00'))
    def test_partial_or_baseline_or_missing_source_never_satisfies_slot(self):
        for kind in ['retained','failed','not_connected','missing','duplicate','baseline']:
            s=status()
            if kind=='baseline':s['latest']['baseline']=True
            elif kind=='missing':s['latest']['sources'].pop()
            elif kind=='duplicate':s['latest']['sources'][-1]=copy.deepcopy(s['latest']['sources'][0])
            else:s['latest']['sources'][0]['status']=kind
            self.assertTrue(decide(s,self.at(14,47))['collect'],kind)
    def test_cross_slot_finishing_does_not_hide_older_start_or_old_snapshot(self):
        s=status('2026-11-12T11:50:00+08:00');s['latest']['timestamp']='2026-11-12T12:30:00+08:00'
        self.assertTrue(decide(s,self.at(12,47))['collect'])
        s=status();s['latest']['sources'][0]['snapshotTimestamp']='2026-11-12T06:00:00+08:00'
        self.assertTrue(decide(s,self.at(12,47))['collect'])

if __name__=='__main__':unittest.main()
