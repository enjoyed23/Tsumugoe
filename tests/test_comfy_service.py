import unittest
from unittest.mock import patch,Mock
import test_cg as fixtures
from comfy_client import Service
from model import Problem
class ComfyServiceTests(unittest.TestCase):
 def setUp(self):fixtures.CGTests.setUp(self)
 def tearDown(self):fixtures.CGTests.tearDown(self)
 def test_existing_service_is_reused_without_launch(self):
  svc=Service(self.s)
  with patch('comfy_client.Client.request',return_value={'system':{}}),patch.object(svc,'_start') as launch:
   self.assertEqual(svc.start()['state'],'ready');launch.assert_not_called()
 def test_starting_process_is_not_launched_twice(self):
  svc=Service(self.s);process=Mock();process.poll.return_value=None
  def launch():svc.process=process;svc.process_endpoint=self.s.config['comfyui']['endpoint']
  with patch('comfy_client.Client.request',side_effect=Problem('offline')),patch.object(svc,'_start',side_effect=launch) as start:
   first=svc.start();self.assertTrue(first['starting']);self.assertFalse(first['running']);svc.start();self.assertEqual(start.call_count,1)
 def test_failed_process_reports_log_and_exit_code(self):
  svc=Service(self.s);svc.process=Mock();svc.process.poll.return_value=1;svc.process.returncode=1;svc.process_endpoint=self.s.config['comfyui']['endpoint']
  with patch('comfy_client.Client.request',side_effect=Problem('offline')):
   r=svc.status();self.assertEqual(r['state'],'failed');self.assertIn('startup.log',r['message']);self.assertIn('1',r['message'])
 def test_missing_launcher_paths_fail_before_process_creation(self):
  svc=Service(self.s);self.s.config['comfyui']['launcher']['python']='missing-test-python'
  with patch('comfy_client.Client.request',side_effect=Problem('offline')),patch('comfy_client.subprocess.Popen') as popen:
   with self.assertRaises(Problem):svc.start()
   popen.assert_not_called()
