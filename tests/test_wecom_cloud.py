import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

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


if __name__=='__main__':unittest.main()
