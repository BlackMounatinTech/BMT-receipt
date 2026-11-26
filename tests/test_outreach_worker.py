import sys
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outreach_worker'))
import runner

class OutreachWorkerTests(unittest.TestCase):
    def test_long_run_sends_heartbeat_without_restarting_child_or_rewriting_input(self):
        process=Mock();process.args=['codex','exec']
        process.communicate.side_effect=[subprocess.TimeoutExpired(process.args,60),subprocess.TimeoutExpired(process.args,60),None]
        with patch.object(runner,'request') as request:
            runner.maintain_run(process,'private prompt',timeout=1100)
        self.assertEqual(request.call_count,2)
        self.assertEqual(process.communicate.call_args_list[0].args,('private prompt'.encode(),))
        self.assertEqual(process.communicate.call_args_list[1].args,(None,))
        self.assertEqual(process.communicate.call_count,3)
    def test_deadline_does_not_extend_when_polling(self):
        process=Mock();process.args=['codex','exec'];process.communicate.side_effect=subprocess.TimeoutExpired(process.args,60)
        with patch.object(runner.time,'monotonic',side_effect=[0,0,61]),patch.object(runner,'request') as request:
            with self.assertRaises(subprocess.TimeoutExpired):runner.maintain_run(process,'prompt',timeout=60)
        request.assert_not_called()
    def test_transient_heartbeat_failure_does_not_restart_or_abort_live_child(self):
        process=Mock();process.args=['codex','exec'];process.communicate.side_effect=[subprocess.TimeoutExpired(process.args,60),None]
        with patch.object(runner,'request',side_effect=ConnectionError('temporary CRM outage')),patch('sys.stderr'):
            runner.maintain_run(process,'prompt')
        self.assertEqual(process.communicate.call_count,2)
