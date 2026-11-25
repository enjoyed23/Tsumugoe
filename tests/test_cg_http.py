import json,shutil,threading,unittest
from urllib.request import Request,urlopen
import test_cg as fixtures
from app import BASE,make_server
from test_pilot import PNG
from model import Store
class CGHttpTests(unittest.TestCase):
 def setUp(self):
  fixtures.CGTests.setUp(self);shutil.copytree(BASE/'web',self.base/'web');self.server=make_server(self.s,0);self.server.cg_jobs.client_factory=fixtures.FakeClient;self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.url='http://127.0.0.1:'+str(self.server.server_port)
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();fixtures.CGTests.tearDown(self)
 def call(self,path,body):
  with urlopen(Request(self.url+'/api/'+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})) as r:return json.load(r)
 def test_preview_generate_image_delivery(self):
  b={'work_id':'w','track_id':self.tid,'unit_id':'B1-1'};p=self.call('cg-preview',b);self.assertFalse(p['problems']);self.call('cg-start',{**b,'token':p['token']});self.server.cg_jobs.thread.join(3)
  with urlopen(self.url+'/api/cg-job') as r:j=json.load(r)
  self.assertFalse(j['running']);self.assertTrue(j['adopted'])
  with urlopen(self.url+'/media/'+j['media_id']) as r:self.assertEqual(r.headers['Content-Type'],'image/png');self.assertEqual(r.read(),PNG)
 def test_upload_copy_attach_and_config_persistence(self):
  from urllib.parse import urlencode
  q=urlencode({'work_id':'w','track_id':self.tid,'unit_id':'B1-1','revision':self.s.data['revision']})
  with urlopen(Request(self.url+'/api/cg-upload?'+q,data=PNG,headers={'Content-Type':'application/octet-stream','X-Filename':'neutral.png'})) as r:mid=json.load(r)['media_id']
  self.assertTrue(self.s.media_path(self.s.data['media'][mid]).is_file());cfg=self.call('cg-config',{});cfg['width']=1024;cfg['height']=576;self.call('cg-config-save',{'config':cfg});self.assertEqual(Store(self.base).config['comfyui']['width'],1024)
 def test_running_version_pins_assets(self):
  original=(self.base/'web/cg.js').read_bytes();(self.base/'web/cg.js').write_bytes(original+b'\n// changed on disk')
  with urlopen(self.url+'/cg.js') as r:self.assertEqual(r.read(),original)

 def test_empty_control_responses_are_accepted(self):
  from http.server import BaseHTTPRequestHandler,HTTPServer
  from comfy_client import Client
  class Empty(BaseHTTPRequestHandler):
   def log_message(self,*a):pass
   def do_POST(self):self.rfile.read(int(self.headers.get('Content-Length',0)));self.send_response(200);self.end_headers()
  server=HTTPServer(('127.0.0.1',0),Empty);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   client=Client('http://127.0.0.1:'+str(server.server_port))
   for path in ('/free','/interrupt','/queue'):self.assertEqual(client.request(path,{}),{})
  finally:server.shutdown();server.server_close();thread.join()

 def test_novel_asset_is_served_as_javascript(self):
  with urlopen(self.url+'/novel.js') as r:self.assertIn('javascript',r.headers['Content-Type']);self.assertIn(b'function novelRoute',r.read())

 def test_import_unit_aliases_in_one_block_keeps_distinct_timing(self):
  body={'work_id':'w','track_id':self.tid,'track_mode':'update','value':{'lines':[{'unit':'B1-1','lines':['neutral one']},{'unit':'B1-2','lines':['neutral two']}],'cgs':[{'unit':'B1-1','prompt':'neutral one'},{'unit':'B1-2','prompt':'neutral two'}]}}
  result=self.call('import',body);self.assertFalse(result.get('confirmation_required'));t=self.s.data['works'][0]['tracks'][0];self.assertEqual([c['start_unit'] for c in t['cgs']],['B1-1','B1-2']);self.assertEqual([u['id'] for u in t['units']],['B1-1','B1-2']);self.assertFalse(any(d['needs_check'] for d in self.s.snapshot()['_view']['cg']['w'][self.tid].values()));self.assertEqual(Store(self.base).data,self.s.data)

 def test_track_delete_confirmation_api_and_generation_guard(self):
  from urllib.error import HTTPError
  b={'work_id':'w','track_id':self.tid};self.server.cg_jobs.job={'running':True,'work_id':'w','track_id':self.tid}
  with self.assertRaises(HTTPError) as e:self.call('track-delete-preview',b)
  self.assertEqual(e.exception.code,400);e.exception.close();self.server.cg_jobs.job=None;p=self.call('track-delete-preview',b)
  with self.assertRaises(HTTPError) as e:self.call('track-delete',{**b,'signature':p['signature']})
  self.assertEqual(e.exception.code,409);e.exception.close();result=self.call('track-delete',{**b,'signature':p['signature'],'acknowledged':True});self.assertEqual(result['track_id'],self.tid);self.assertFalse(self.s.data['works'][0]['tracks'])
