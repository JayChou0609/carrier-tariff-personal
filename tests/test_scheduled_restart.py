import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import restart_requested_collection as restart


class RequestedRestartTests(unittest.TestCase):
    def test_cancel_before_dispatch_and_preserve_catch_up_guard(self):
        with patch.dict(os.environ,{'GITHUB_REPOSITORY':restart.REPOSITORY,'GH_TOKEN':'test-token'}), patch.object(restart.Path,'read_text',return_value=json.dumps({'run_id':'123'})), patch.object(restart,'GitHub') as factory, patch.object(restart.time,'sleep'):
            api=factory.return_value.api
            api.side_effect=[{'path':'.github/workflows/scheduled-refresh.yml','head_branch':'main','status':'in_progress'}, {}, {'status':'completed'}, {}]
            restart.main()
            self.assertTrue(api.call_args_list[1].args[1].endswith('/cancel'))
            self.assertEqual(api.call_args_list[-1].args[2]['inputs'],{'catch_up':True})

    def test_other_workflow_is_never_cancelled(self):
        with patch.dict(os.environ,{'GITHUB_REPOSITORY':restart.REPOSITORY,'GH_TOKEN':'test-token'}), patch.object(restart.Path,'read_text',return_value=json.dumps({'run_id':'123'})), patch.object(restart,'GitHub') as factory:
            factory.return_value.api.return_value={'path':'.github/workflows/wecom-notify.yml','head_branch':'main','status':'in_progress'}
            with self.assertRaises(RuntimeError):restart.main()
            self.assertEqual(factory.return_value.api.call_count,1)
