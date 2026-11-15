import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import dispatch_collection_outputs as output


class OutputDispatchTests(unittest.TestCase):
    def test_both_outputs_use_main_and_recover_preserves_deduplication(self):
        with patch.dict(os.environ,{'GITHUB_REPOSITORY':output.REPOSITORY,'GITHUB_TOKEN':'test-token','GITHUB_RUN_ID':'123'}),patch.object(output,'report_from_checkout',return_value={}),patch.object(output,'require_complete_collection',return_value={'collection_run':'123-1'}) as guard,patch.object(output,'GitHub') as factory:
            output.main()
            guard.assert_called_once_with({},expected_run='123')
            calls=factory.return_value.api.call_args_list
            self.assertEqual(len(calls),2)
            self.assertEqual(calls[0].args[2],{'ref':'main','inputs':{'action':'recover'}})
            self.assertTrue(calls[1].args[1].endswith('pages.yml/dispatches'))

    def test_incomplete_collection_never_dispatches_outputs(self):
        with patch.dict(os.environ,{'GITHUB_REPOSITORY':output.REPOSITORY,'GITHUB_TOKEN':'test-token','GITHUB_RUN_ID':'123'}),patch.object(output,'report_from_checkout',return_value={}),patch.object(output,'require_complete_collection',side_effect=RuntimeError('incomplete')),patch.object(output,'GitHub') as factory:
            with self.assertRaises(RuntimeError):output.main()
            factory.assert_not_called()
