import json,threading,shutil,time,unittest
from urllib.request import Request,urlopen
from unittest.mock import patch
import test_audio as fixtures
FakeWorker=fixtures.FakeWorker
from app import BASE,make_server
class AudioHttpTests(unittest.TestCase):
 def setUp(self):
  fixtures.AudioTests.setUp(self);shutil.copytree(BASE/'web',self.base/'web');self.server=make_server(self.s,0);self.server.audio_jobs.worker_factory=FakeWorker;self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.url='http://127.0.0.1:'+str(self.server.server_port)
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();fixtures.AudioTests.tearDown(self)
 def call(self,path,body=None):
  req=Request(self.url+'/api/'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
  with urlopen(req) as r:return json.load(r)
 def test_audio_plan_generate_status_export_and_range(self):
  body={'work_id':'w','track_id':self.tid};p=self.call('audio-plan',body);self.assertEqual(p['count'],2)
  with patch('audio_jobs.config_problems',return_value=[]):
   p=self.call('audio-preview',{**body,'mode':'all'});self.assertEqual(p['target'],3);self.call('audio-start',{**body,'mode':'all','token':p['token']})
  deadline=time.monotonic()+5
  while self.call('audio-job')['running'] and time.monotonic()<deadline:time.sleep(.01)
  self.assertFalse(self.call('audio-job')['running']);r=self.call('audio-export',body)
  with urlopen(Request(self.url+'/media/'+r['media_id'],headers={'Range':'bytes=0-43'})) as response:self.assertEqual(response.status,206);self.assertEqual(response.read()[:4],b'RIFF')
  with urlopen(self.url+'/audio.js') as response:self.assertIn(b'studioTransport',response.read())
