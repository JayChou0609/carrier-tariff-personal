import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import wecom_cloud as cloud


class MemoryState(cloud.GitHubState):
    def __init__(self):
        super().__init__('test-github-token',forbidden=('test-webhook-key',))
        self.requests=[]
        self.fail=False

    def api(self, method, path, body=None, missing=False):
        self.requests.append((method,path,copy.deepcopy(body)))
        if self.fail:
            raise cloud.StateError('GitHub checkpoint API failed: HTTP 409')
        return {'content':{'sha':'new-blob'}}


class CloudTests(unittest.TestCase):
    def test_watchdog_without_new_archive_never_uses_old_data(self):
        from unittest.mock import patch
        with patch.object(cloud.core,'read_json',return_value={'latest':{'id':'111-1'}}):
            self.assertFalse(cloud.upstream_archived(expected_run='222'))
            self.assertTrue(cloud.upstream_archived(expected_run='111'))
        with patch.object(cloud.core,'read_json',return_value={'latest':{'id':'111-1','baseline':True}}):
            self.assertFalse(cloud.upstream_archived(expected_run='111'))
    def complete_report(self):
        stamp='2026-11-11T18:49:26+08:00'
        ids=[c+':'+r for c,regions in cloud.core.SCOPES.items() for r in regions]
        latest={'id':'43001466760-1','timestamp':stamp,'baseline':False,
                'sources':[{'id':sid,'status':'updated','snapshotTimestamp':stamp} for sid in ids]}
        report={'day':'2026-11-11','sources':[{'id':sid,'status':'repository_snapshot','snapshot':stamp} for sid in ids]}
        return latest,report

    def test_formal_push_requires_all_sixteen_updated_sources(self):
        latest,report=self.complete_report()
        with patch.object(cloud.core,'read_json',return_value={'latest':latest}):
            self.assertEqual(cloud.require_complete_collection(report,expected_run='43001466760')['collection_run'],'43001466760-1')
        for status in ['retained','failed','not_connected']:
            latest,report=self.complete_report();latest['sources'][0]['status']=status
            with patch.object(cloud.core,'read_json',return_value={'latest':latest}):
                with self.assertRaisesRegex(cloud.StateError,'采集不完整'):
                    cloud.require_complete_collection(report)

    def test_formal_push_rejects_missing_duplicate_old_day_and_wrong_run(self):
        for kind in ['missing','duplicate','old_day','wrong_run','baseline']:
            latest,report=self.complete_report()
            if kind=='missing':latest['sources'].pop()
            elif kind=='duplicate':latest['sources'][-1]=latest['sources'][0]
            elif kind=='old_day':latest['timestamp']='2026-11-10T18:49:26+08:00'
            elif kind=='wrong_run':latest['id']='123-1'
            else:latest['baseline']=True
            with patch.object(cloud.core,'read_json',return_value={'latest':latest}):
                with self.assertRaises(cloud.StateError):
                    cloud.require_complete_collection(report,expected_run='43001466760')

    def test_formal_push_rejects_file_not_from_current_archive(self):
        latest,report=self.complete_report();report['sources'][0]['snapshot']='2026-11-11T05:43:10+08:00'
        with patch.object(cloud.core,'read_json',return_value={'latest':latest}):
            with self.assertRaisesRegex(cloud.StateError,'归档不一致'):
                cloud.require_complete_collection(report)

    def test_checkpoint_never_contains_webhook_or_github_token(self):
        state=MemoryState()
        for secret in ['test-webhook-key','test-github-token']:
            with self.assertRaises(cloud.StateError):state.put({'leaked':secret})
        self.assertEqual(state.requests,[])

    def test_lease_is_durable_before_sending_and_blocks_ambiguous_retry(self):
        state=MemoryState();state.begin('run-1')
        saved=json.loads(base64.b64decode(state.requests[0][2]['content']))
        self.assertEqual(saved['in_progress']['run'],'run-1')
        with self.assertRaises(cloud.StateError):state.begin('run-2')
        self.assertEqual(len(state.requests),1)

    def test_finish_roundtrips_ledger_and_removes_completed_outbox(self):
        state=MemoryState();state.begin('run-1')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);state.restore(root)
            key='scope|'+cloud.core.now().date().isoformat()+'|new'
            cloud.core.write_json(root/'delivery.json',{key:{'slots':[12],'versions':['v1']}})
            cloud.core.write_json(root/'outbox'/('a'*64+'.json'),{'summary_sent':True,'file_required':False,'file_sent':False})
            cloud.core.write_json(root/'outbox'/('b'*64+'.json'),{'summary_sent':True,'file_required':True,'file_sent':False})
            state.finish(root,root/'backup.json')
            self.assertNotIn('in_progress',state.data)
            self.assertEqual(state.data['delivery'][key]['versions'],['v1'])
            self.assertEqual(list(state.data['outbox']),['b'*64+'.json'])

    def test_failed_checkpoint_write_preserves_lease_and_recovery_backup(self):
        state=MemoryState();state.begin('run-1')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);state.restore(root);state.fail=True
            with self.assertRaises(cloud.StateError):state.finish(root,root/'backup.json')
            self.assertIn('in_progress',state.data)
            self.assertNotIn('in_progress',json.loads((root/'backup.json').read_text()))

    def test_restore_rejects_path_traversal(self):
        state=MemoryState();state.data['outbox']={'../config.json':{}}
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(cloud.StateError):state.restore(td)

    def test_unfinished_card_is_preserved_in_checkpoint(self):
        state=MemoryState();state.begin('run-card')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);state.restore(root)
            name='c'*64+'.json'
            cloud.core.write_json(root/'outbox'/name,{'summary_sent':True,'file_sent':True,
                'cards':{'v1':{'image':True,'text':False}}})
            state.finish(root,root/'backup.json')
            self.assertIn(name,state.data['outbox'])



class RecoveryCheckpointTests(unittest.TestCase):
    def test_checkpoint_keeps_lease_until_final_finish(self):
        state=MemoryState();state.begin('123-1')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);state.restore(root)
            name='d'*64+'.json'
            cloud.core.write_json(root/'outbox'/name,{'summary_sent':True,'file_required':False,'cards':{'v':{'image':True,'text':True}}})
            state.checkpoint(root,root/'backup.json')
            self.assertIn(name,state.data['outbox'])
            self.assertIn('in_progress',state.data)
            state.finish(root,root/'backup.json')
            self.assertNotIn('in_progress',state.data)
    def test_recovery_requires_original_run_to_be_completed(self):
        state=MemoryState();state.data['in_progress']={'run':'123-1'}
        with patch.object(state,'api',return_value={'status':'in_progress','head_branch':'main','path':'.github/workflows/wecom-notify.yml'}):
            with self.assertRaises(cloud.StateError):state.recover()
        state.data['blocked']={'scope':'x'}
        def api(method,path,body=None,missing=False):
            if method=='GET':return {'status':'completed','head_branch':'main','path':'.github/workflows/wecom-notify.yml'}
            return {'content':{'sha':'new'}}
        with patch.object(state,'api',side_effect=api):state.recover()
        self.assertNotIn('in_progress',state.data);self.assertNotIn('blocked',state.data)
    def test_success_receipt_contains_three_buckets_but_no_credentials(self):
        state=MemoryState();report={'collection_run':'123-1','target_slot':'2026-11-13T12:00:00+08:00','day':'2026-11-13'}
        with patch.object(state,'api',side_effect=lambda method,path,body=None,missing=False: None if method=='GET' else state.requests.append((method,path,body))):
            state.mark_success(report)
        body=state.requests[-1][2];health=json.loads(base64.b64decode(body['content']))
        self.assertEqual(sorted(health['buckets']),['new','today_off','tomorrow_off'])
        self.assertTrue(health['cards']);self.assertEqual(health['collection_run'],'123-1')
        self.assertNotIn('test-github-token',json.dumps(health))

    def test_large_state_uses_blob_api_when_contents_omits_payload(self):
        state=MemoryState()
        payload={'version':1,'delivery':{},'outbox':{}}
        def api(method,path,body=None,missing=False):
            if path.startswith('git/ref/'):return {'object':{'sha':'branch'}}
            if path.startswith('contents/'):return {'sha':'stateblob','encoding':'none','content':''}
            if path=='git/blobs/stateblob':return {'encoding':'base64','content':base64.b64encode(json.dumps(payload).encode()).decode()}
            raise AssertionError(path)
        with patch.object(state,'api',side_effect=api):self.assertEqual(state.load(),payload)
        self.assertEqual(state.sha,'stateblob')


if __name__=='__main__':unittest.main()
