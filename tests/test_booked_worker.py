import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outreach_worker'))
import booked
ROOT=Path(__file__).resolve().parents[1]/'outreach_worker'
class BookedWorkerTests(unittest.TestCase):
 def test_no_job_does_not_start_ai_or_touch_outreach(self):
  request=Mock(return_value={'job':None})
  with tempfile.TemporaryDirectory() as tmp,patch.object(booked.subprocess,'Popen') as popen:
   self.assertFalse(booked.run_booked(ROOT,Path(tmp),request));popen.assert_not_called()
  self.assertEqual(request.call_args.kwargs['path'],'/api/booked-research/worker')
 def test_job_uses_read_only_prompt_and_marks_unfinished_work_failed(self):
  with tempfile.TemporaryDirectory() as tmp:
   local=Path(tmp);(local/'config.json').write_text(json.dumps({'codex_path':'/fake/codex'}))
   request=Mock(side_effect=[{'job':{'id':'test-job','company':'Concrete Co','lead_id':1}},{}]);process=Mock();process.communicate.return_value=None
   with patch.object(booked.subprocess,'Popen',return_value=process):self.assertTrue(booked.run_booked(ROOT,local,request))
   prompt=process.communicate.call_args.args[0].decode();self.assertIn('READ-ONLY',prompt);self.assertIn('Never send any messages',prompt);self.assertIn('Do not spawn agents',prompt);self.assertIn('20 are confirmed',prompt)
   self.assertEqual(request.call_args.args[1]['op'],'fail');self.assertNotIn('enable',str(request.call_args_list))

if __name__=='__main__':unittest.main()
