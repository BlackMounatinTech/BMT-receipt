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
    def test_reply_prompt_excludes_discovery_and_uses_short_budget(self):
        template=(runner.ROOT/'workflow.txt').read_text()
        prompt=runner.prepare_prompt(template,dict(mode='replies',work_minutes=8))
        self.assertIn('RUN MODE: replies',prompt);self.assertIn('End within 8 minutes',prompt)
        self.assertNotIn('COMPANY-FIRST DISCOVERY:',prompt);self.assertIn('REPLY HANDLING',prompt)
        self.assertIn('HARD TAB LIMIT',prompt);self.assertIn('DELIVERY REVIEW',prompt)
        self.assertNotIn('{{WORK_MINUTES}}',prompt)
    def test_research_prompt_uses_long_budget_and_inbox_checkpoints(self):
        prompt=runner.prepare_prompt((runner.ROOT/'workflow.txt').read_text(),dict(mode='research',work_minutes=40))
        self.assertIn('End within 40 minutes',prompt);self.assertIn('COMPANY-FIRST DISCOVERY:',prompt)
        self.assertIn('about every 15 minutes',prompt)
    def test_tick_passes_server_budget_to_child_watchdog(self):
        import tempfile,json
        with tempfile.TemporaryDirectory() as temp:
            local=Path(temp);(local/'config.json').write_text(json.dumps({'codex_path':'/fake/codex'}))
            claim=dict(run='test-research',mode='research',work_minutes=40,timeout_seconds=2700)
            child=Mock();child.returncode=0
            with patch.object(runner,'LOCAL',local),patch.object(runner,'request',side_effect=[{},claim,{}]),patch.object(runner.subprocess,'Popen',return_value=child),patch.object(runner,'maintain_run') as maintain:
                runner.tick()
            self.assertEqual(maintain.call_args.kwargs['timeout'],2700)
            self.assertIn('End within 40 minutes',maintain.call_args.args[1])
