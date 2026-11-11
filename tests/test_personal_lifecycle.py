import copy
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from build_lifecycle import Registry, entry_key, day, state, build_lifecycle
import test_personal_additions as additions


def tariff(on='2020-04-01', off='2026-11-10', id_='A', title='套餐A'):
    return {'id': id_, 'title': title, 'firstLevel': '套餐', 'detail': {'onDate': on, 'offDate': off}}


class LifecycleTest(unittest.TestCase):
    def test_official_reactivation_after_expiry(self):
        r=Registry();a=tariff();b=tariff('2026-11-11','2027-12-31')
        r.observe([a],'2026-11-10T12:00:00+08:00',False)
        r.observe([b],'2026-11-11T12:00:00+08:00')
        event=r.current[entry_key(b)][0]
        self.assertEqual(event['date'],'2026-11-11')
        self.assertEqual(event['basis'],'官方重新上线日期')
        self.assertEqual(event['previousStopDate'],'2026-11-10')
        r.observe([b],'2026-11-12T12:00:00+08:00')
        self.assertEqual(len(r.current[entry_key(b)]),1)

    def test_unchanged_launch_date_has_distinct_confirmation_basis(self):
        r=Registry();a=tariff();b=tariff(off='2027-12-31')
        r.observe([a],'2026-11-09T12:00:00+08:00',False)
        r.observe([b],'2026-11-11T12:00:00+08:00')
        event=r.current[entry_key(b)][0]
        self.assertEqual(event['date'],'2026-11-11')
        self.assertIn('确认日期',event['basis'])
        self.assertEqual(event['onDate'],'2020-04-01')

    def test_first_seen_missing_reappearance_and_ordinary_edit_are_not_reactivation(self):
        r=Registry();a=tariff(off='2030-01-01')
        r.observe([a],'2026-11-09T12:00:00+08:00',False)
        r.observe([],'2026-11-10T12:00:00+08:00')
        b=copy.deepcopy(a);b['fee']='300'
        r.observe([b,tariff(id_='B',title='全新套餐',off='2030-01-01')],'2026-11-11T12:00:00+08:00')
        self.assertEqual(r.current,{})

    def test_renewal_before_end_day_is_not_reactivation(self):
        r=Registry();a=tariff();b=tariff(off='2030-01-01')
        r.observe([a],'2026-11-09T12:00:00+08:00',False)
        r.observe([b],'2026-11-10T12:00:00+08:00')
        self.assertEqual(r.current,{})

    def test_upcoming_reactivation_waits_for_official_day(self):
        r=Registry();a=tariff(off='2026-11-08');b=tariff('2026-11-11','2030-01-01')
        r.observe([a],'2026-11-09T12:00:00+08:00',False)
        r.observe([b],'2026-11-10T12:00:00+08:00');self.assertEqual(r.current,{})
        r.observe([b],'2026-11-11T00:00:00+08:00')
        self.assertEqual(r.current[entry_key(b)][0]['date'],'2026-11-11')

    def test_multiple_cycles_and_shared_report_number_do_not_merge(self):
        r=Registry();a=tariff();b=tariff(id_='B',title='另一套餐',off='2030-01-01')
        for x in [a,b]:x['detail']['reportNo']='SHARED'
        r.observe([a,b],'2026-11-09T12:00:00+08:00',False)
        active=tariff('2026-11-11','2026-11-11');r.observe([active,b],'2026-11-11T12:00:00+08:00')
        r.observe([active,b],'2026-11-12T00:00:00+08:00')
        again=tariff('2026-11-13','2030-01-01');r.observe([again,b],'2026-11-13T12:00:00+08:00')
        self.assertEqual(len(r.current[entry_key(again)]),2)
        self.assertNotIn(entry_key(b),r.current)

    def test_official_stopped_state_overrides_placeholder_and_unknown(self):
        a=tariff(off='2029-12-31');a['detail']['state']='已停售'
        r=Registry();r.observe([a],'2026-11-10T12:00:00+08:00',False)
        b=tariff('2026-11-11','2029-12-31');r.observe([b],'2026-11-11T12:00:00+08:00')
        self.assertEqual(r.current[entry_key(b)][0]['basis'],'官方重新上线日期')
        self.assertEqual(state({'detail':{}},'2026-11-11'),'unknown')
        self.assertEqual(day('2026-02-30'),'')
        self.assertEqual(day('2026-11-10T16:00:00Z'),'2026-11-11')


class LifecycleArchiveTest(unittest.TestCase):
    setUp = additions.AdditionsTest.setUp
    save = additions.AdditionsTest.save
    def test_retained_run_does_not_confirm_reactivation(self):
        a=tariff();b=tariff('2026-11-11','2030-01-01')
        self.save([a],'2026-11-09','base',baseline=True)
        self.row['status']='retained';self.save([b],'2026-11-11','failed',[a])
        data=build_lifecycle(self.archive,self.root)
        self.assertEqual(data['sources'][self.row['id']]['items'],{})
        self.row['status']='updated';self.save([b],'2026-11-11','confirmed',[a])
        data=build_lifecycle(self.archive,self.root)
        self.assertEqual(data['sources'][self.row['id']]['items'][entry_key(b)][0]['date'],'2026-11-11')

if __name__=='__main__':unittest.main()
