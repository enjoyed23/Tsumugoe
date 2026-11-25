import copy,json,shutil,tempfile,time,unittest
from pathlib import Path
from model import Store,Problem
from app import BASE
from test_pilot import PNG
from cg import CG,config,describe,build,dimension,validate_config,validate_remote
from cg_defaults import defaults,GRAPH
from cg_jobs import Jobs
class FakeClient:
 graphs=[];uploads=[];calls=[];fail=False;pending=False
 def __init__(self,endpoint):self.endpoint=endpoint
 def inspect(self):
  info={n['class_type']:{'input':{'required':{}}} for n in GRAPH.values()};info['TsumugoeFacePass']={'input':{'required':{}}};info['LoraLoader']={'input':{'required':{'lora_name':[['neutral.safetensors']]}}};info['CheckpointLoaderSimple']['input']['required']['ckpt_name']=[['waiIllustriousSDXL_v170.safetensors']];return info
 def upload(self,path,mid,mime):self.uploads.append((str(path),mid,mime));return 'tsumugoe/neutral.png'
 def request(self,path,body=None,**kw):
  self.calls.append((path,body))
  if path=='/prompt':self.graphs.append(copy.deepcopy(body['prompt']));return {'prompt_id':'neutral-job'}
  if path.startswith('/history/'):
   if self.pending:return {}
   if self.fail:return {'neutral-job':{'status':{'status_str':'error'}}}
   return {'neutral-job':{'status':{'status_str':'success'},'outputs':{'save':{'images':[{'filename':'neutral.png','subfolder':'','type':'output'}]}}}}
  return {}
 def download(self,item):return PNG
class CGTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=BASE/'work/test-runs');self.base=Path(self.tmp.name);shutil.copy2(BASE/'config.default.json',self.base/'config.default.json');self.s=Store(self.base);self.s.config['comfyui']=defaults();self.s.config['comfyui']['ipadapter_settings']['enabled']=True;self.s.config['comfyui']['trigger_loras']={'neutral_trigger':[{'name':'neutral.safetensors','strength_model':.9,'strength_clip':.9}]};self.s.save('actors',{'id':'a','name':'Neutral actor','trigger_word':'neutral_trigger'});self.s.save('works',{'id':'w','title':'Neutral work'});self.s.save('character',{'id':'role','actor_id':'a','names':{'full':'案内','family':'','given':'','aliases':[]}},work_id='w');r=self.s.import_payload({'lines':[{'unit':'B1-1','lines':['Neutral dialogue']}],'cgs':[{'unit':'B1-1','prompt':'neutral_trigger, blue teapot, unknown_tag, 日本語','extra':{'keep':True}}]},work_id='w');self.tid=r['track_id'];self.cg=CG(self.s);self.jobs=Jobs(self.s);self.jobs.client_factory=FakeClient;FakeClient.graphs=[];FakeClient.uploads=[];FakeClient.calls=[];FakeClient.fail=False;FakeClient.pending=False
 def tearDown(self):self.tmp.cleanup()
 def cgdata(self):return self.s.data['works'][0]['tracks'][0]['cgs'][0]
 def desc(self):return describe(self.s,self.s.data,'w',self.tid,'B1-1')
 def generate(self):
  p=self.jobs.preview('w',self.tid,'B1-1');self.assertFalse(p['problems'],p['problems']);self.jobs.start('w',self.tid,'B1-1',p['token']);self.jobs.thread.join(4);self.assertFalse(self.jobs.status()['running']);return self.jobs.status()
 def test_actor_lora_does_not_require_global_trigger_mapping(self):
  self.s.config['comfyui']['trigger_loras']={}
  self.s.save('actors',dict(id='a',lora=dict(name='neutral.safetensors',strength_model=.75,strength_clip=.8)))
  d=self.desc();self.assertFalse(d['problems']);self.assertEqual(d['loras'],[dict(name='neutral.safetensors',strength_model=.75,strength_clip=.8)])
  graph=build(config(self.s),self.cgdata(),d,42)
  self.assertEqual(graph['tsumugoe_lora_0']['inputs']['lora_name'],'neutral.safetensors')
  self.assertEqual(graph['sampler']['inputs']['model'],['tsumugoe_lora_0',0])
  self.assertEqual(graph['positive']['inputs']['clip'],['tsumugoe_lora_0',1])
 def test_actor_lora_selection_changes_fingerprint_and_can_be_disabled(self):
  before=self.desc()['fingerprint'];self.s.save('actors',dict(id='a',lora=dict(name='neutral.safetensors',strength_model=.8,strength_clip=.8)))
  self.assertNotEqual(before,self.desc()['fingerprint'])
  self.s.save('actors',dict(id='a',lora=None));self.assertEqual(self.desc()['loras'],[]);self.assertFalse(self.desc()['problems'])
 def test_prompt_exact_and_lora_connected_both_branches(self):
  graph=build(config(self.s),self.cgdata(),self.desc(),42);self.assertEqual(graph['positive']['inputs']['text'],self.cgdata()['prompt']);self.assertEqual(graph['sampler']['inputs']['model'],['tsumugoe_lora_0',0]);self.assertEqual(graph['positive']['inputs']['clip'],['tsumugoe_lora_0',1]);self.assertEqual(graph['negative']['inputs']['clip'],['tsumugoe_lora_0',1]);self.assertEqual(graph['tsumugoe_lora_0']['inputs']['strength_clip'],.9);self.assertNotIn('ipadapter',graph)
 def test_ref_uploaded_and_ipadapter_receives_lora_model(self):
  r=self.s.upload('actors','a','neutral.png',PNG);j=self.generate();self.assertNotIn('error',j);g=FakeClient.graphs[0];self.assertEqual(g['reference_image']['inputs']['image'],'tsumugoe/neutral.png');self.assertEqual(g['ipadapter']['inputs']['model'],['tsumugoe_lora_0',0]);self.assertEqual(g['sampler']['inputs']['model'],['ipadapter',0]);self.assertEqual(FakeClient.uploads[0][1],r['media_id'])
 def test_reference_absence_does_not_fail(self):
  j=self.generate();self.assertNotIn('error',j);self.assertTrue(self.cgdata()['image_id']);self.assertFalse(FakeClient.uploads)
 def test_regen_failure_keeps_existing_image(self):
  self.generate();mid=self.cgdata()['image_id'];path=self.s.media_path(self.s.data['media'][mid]);FakeClient.fail=True;j=self.generate();self.assertIn('error',j);self.assertEqual(self.cgdata()['image_id'],mid);self.assertTrue(path.exists())
 def test_regen_retains_gallery_and_attach_swap(self):
  self.generate();first=self.cgdata()['image_id'];self.generate();second=self.cgdata()['image_id'];self.assertNotEqual(first,second);self.cg.attach('w',self.tid,'B1-1',first);self.assertEqual(self.cgdata()['image_id'],first);self.assertEqual(len(self.cg.gallery('w',self.tid)),2)
 def test_image_generation_does_not_modify_audio_or_lines(self):
  before=copy.deepcopy(self.s.data['works'][0]['tracks'][0]['units'][0]['lines']);self.generate();u=self.s.data['works'][0]['tracks'][0]['units'][0];self.assertEqual(u['lines'],before);self.assertFalse(u['audio_ids'])
 def test_resolution_numeric_validation_and_workflow_latent(self):
  c=config(self.s);dimension(1280,720,c);dimension(1600,904,c)
  for size in [(767,432),(248,432),(1608,904)]:
   with self.assertRaises(Problem):dimension(*size,c)
  c['width']=1024;c['height']=576;g=build(c,self.cgdata(),self.desc(),0);self.assertEqual(g['latent']['inputs']['width'],1024);self.assertEqual(g['latent']['inputs']['height'],576)
 def test_missing_lora_exact_filename_prevents_generation(self):
  self.s.config['comfyui']['trigger_loras']['neutral_trigger'][0]['name']='neutral';p=self.jobs.preview('w',self.tid,'B1-1');self.assertTrue(any('一覧にありません' in x for x in p['problems']))
 def test_pack_lora_alias_strength_override(self):
  self.cg.save('w',self.tid,'B1-1',{'loras':[{'name':'neutral_trigger','weight':.7}]});d=self.desc();self.assertEqual(len(d['loras']),1);self.assertEqual(d['loras'][0]['strength_model'],.7);self.assertEqual(d['loras'][0]['strength_clip'],.7)
 def test_changed_generation_conditions_do_not_attach_old_job(self):
  FakeClient.pending=True;p=self.jobs.preview('w',self.tid,'B1-1');self.jobs.start('w',self.tid,'B1-1',p['token']);deadline=time.monotonic()+2
  while not self.jobs.status().get('prompt_id') and time.monotonic()<deadline:time.sleep(.01)
  self.cg.save('w',self.tid,'B1-1',{'prompt':'Changed neutral prompt'});FakeClient.pending=False;self.jobs.thread.join(3);self.assertFalse(self.jobs.status().get('adopted'));self.assertIsNone(self.cgdata().get('image_id'));self.assertEqual(len(self.cg.gallery('w',self.tid)),1)
 def test_cancel_only_targets_own_prompt(self):
  FakeClient.pending=True;p=self.jobs.preview('w',self.tid,'B1-1');self.jobs.start('w',self.tid,'B1-1',p['token']);deadline=time.monotonic()+2
  while not self.jobs.status().get('prompt_id') and time.monotonic()<deadline:time.sleep(.01)
  self.jobs.stop();self.jobs.thread.join(3);self.assertTrue(self.jobs.status()['cancelled']);self.assertIn(('/interrupt',{'prompt_id':'neutral-job'}),FakeClient.calls);self.assertFalse(self.cgdata().get('image_id'))
 def test_cg_import_clear_confirmation_keeps_dialogue(self):
  self.generate();before=copy.deepcopy(self.s.data['works'][0]['tracks'][0]['units'][0]['lines']);payload={'cgs':[{'unit':'B1-1','prompt':'replacement'}]};p=self.s.import_payload(payload,work_id='w',track_id=self.tid,track_mode='update');self.assertTrue(p['confirmation_required']);self.s.import_payload(payload,work_id='w',track_id=self.tid,track_mode='update',confirmation=p['confirmation']);self.assertIsNone(self.cgdata()['image_id']);self.assertEqual(self.s.data['works'][0]['tracks'][0]['units'][0]['lines'],before)
 def test_no_missing_prompt_or_malformed_loras_accepted(self):
  for row in [{'unit':'x'},{'unit':'x','prompt':'valid','loras':'bad'}]:
   before=self.s.path.read_bytes()
   with self.assertRaises(Problem):self.s.import_payload({'cgs':[row]},work_id='w',track_id=self.tid,track_mode='update')
   self.assertEqual(before,self.s.path.read_bytes())
 def test_unused_delete_protects_attachments_and_actor_refs(self):
  self.generate();first=self.cgdata()['image_id'];self.generate();second=self.cgdata()['image_id']
  with self.assertRaises(Problem):self.cg.delete_files('w',self.tid,[second])
  self.s.save('actors',{'id':'a','image_id':first})
  with self.assertRaises(Problem):self.cg.delete_files('w',self.tid,[first])
 def test_cg_clear_preserves_unit_and_other_fields(self):
  self.generate();self.cg.clear('w',self.tid,'B1-1');u=self.s.data['works'][0]['tracks'][0]['units'][0];self.assertEqual(u['id'],'B1-1');self.assertFalse(self.s.data['works'][0]['tracks'][0]['cgs'])
 def test_state_survives_reload(self):
  self.generate();self.assertEqual(Store(self.base).data,self.s.data)
 def test_local_only_and_workflow_bindings(self):
  for endpoint in ['https://example.com','http://example.com:8189','http://localhost:8189/?remote=1']:
   c=config(self.s);c['endpoint']=endpoint
   with self.assertRaises(Problem):validate_config(c)
  c=config(self.s);c['bindings']['positive']=['missing','text']
  with self.assertRaises(Problem):build(c,self.cgdata(),self.desc(),0)

 def test_stale_custom_clip_chain_is_rejected(self):
  c=config(self.s);c['workflow']['positive']['inputs']['clip']=['custom_lora',1]
  with self.assertRaises(Problem):build(c,self.cgdata(),self.desc(),0)
 def test_reference_binding_can_target_custom_node_id(self):
  c=config(self.s);c['workflow']['custom_ref']=c['workflow'].pop('reference_image');c['workflow']['ipadapter']['inputs']['image']=['custom_ref',0];c['bindings']['reference_image']=['custom_ref','image'];self.s.upload('actors','a','neutral.png',PNG);g=build(c,self.cgdata(),self.desc(),0,'tsumugoe/custom.png');self.assertEqual(g['custom_ref']['inputs']['image'],'tsumugoe/custom.png')
 def test_notes_do_not_change_generation_fingerprint(self):
  before=self.desc()['fingerprint'];self.cg.save('w',self.tid,'B1-1',{'note':'Neutral note'});self.assertEqual(self.desc()['fingerprint'],before)
 def test_bad_seed_and_remote_output_path_rejected(self):
  c=config(self.s);c['seed']='--1'
  with self.assertRaises(Problem):validate_config(c)
  from comfy_client import Client
  with self.assertRaises(Problem):Client('http://localhost:8189').download({'filename':'x.png','subfolder':'../../private'})

 def test_bad_legacy_lora_shape_is_reported_without_breaking_state(self):
  self.cgdata()['loras']=[42];snapshot=self.s.snapshot();self.assertTrue(snapshot['_view']['cg']['w'][self.tid]['B1-1']['problems']);self.assertEqual(snapshot['works'][0]['tracks'][0]['cgs'][0]['loras'],[42])
 def test_multiple_unused_deletion_removes_files_and_keeps_attachment(self):
  self.generate();first=self.cgdata()['image_id'];self.generate();second=self.cgdata()['image_id'];self.generate();last=self.cgdata()['image_id'];paths=[self.s.media_path(self.s.data['media'][m]) for m in (first,second)];r=self.cg.delete_files('w',self.tid,[first,second]);self.assertEqual(len(r['deleted']),2);self.assertTrue(all(not p.exists() for p in paths));self.assertEqual(self.cgdata()['image_id'],last)
 def test_binding_types_are_form_errors(self):
  for key,value in [('adapter',[]),('output',[]),('model_source',{}),('reference_image','bad')]:
   cfg=config(self.s);cfg['bindings'][key]=value
   with self.assertRaises(Problem):validate_config(cfg)

 def test_cache_release_only_for_owned_idle_service(self):
  from comfy_client import release_for_audio
  from unittest.mock import patch
  folder=self.s.work/'comfy-runtime';folder.mkdir();(folder/'process.json').write_text(json.dumps({'endpoint':config(self.s)['endpoint']}),encoding='utf-8')
  with patch('comfy_client.Client',FakeClient):self.assertTrue(release_for_audio(self.s)['released'])
  self.assertIn(('/free',{'unload_models':True,'free_memory':True}),FakeClient.calls)
  FakeClient.calls=[];(folder/'process.json').write_text(json.dumps({'endpoint':'http://127.0.0.1:9999'}),encoding='utf-8')
  with patch('comfy_client.Client',FakeClient):self.assertFalse(release_for_audio(self.s)['released'])
  self.assertFalse(FakeClient.calls)

class AtmosphereTests(CGTests):
 def test_atmosphere_graph_and_summary(self):
  c=config(self.s);c['negative_prompt']='neutral negative, text';c['sampler_cfg']=7.5;c['ipadapter_settings']={'enabled':True,'weight':.65,'weight_type':'style transfer','embeds_scaling':'K+V'}
  d=self.desc();d['reference_id']='neutral';g=build(c,self.cgdata(),d,42,'neutral.png')
  self.assertEqual(g['negative']['inputs']['text'],'neutral negative, text');self.assertEqual(g['sampler']['inputs']['cfg'],7.5)
  self.assertEqual(g['ipadapter']['inputs']['weight'],.65);self.assertEqual(g['ipadapter']['inputs']['weight_type'],'style transfer');self.assertEqual(g['ipadapter']['inputs']['embeds_scaling'],'K+V')
  f=g['tsumugoe_face']['inputs'];self.assertEqual(f['model'],['tsumugoe_lora_0',0]);self.assertEqual(f['positive'],['positive',0]);self.assertEqual(f['denoise'],.4);self.assertEqual(g['save']['inputs']['images'],['tsumugoe_face',0])
  c['face_inpaint']['enabled']=False;self.assertNotIn('tsumugoe_face',build(c,self.cgdata(),d,42,'neutral.png'))
 def test_custom_workflow_keeps_conditions(self):
  c=config(self.s);c['workflow']['sampler']['inputs']['cfg']=6.25;c['workflow']['ipadapter']['inputs']['weight']=.25
  d=self.desc();d['reference_id']='neutral';g=build(c,self.cgdata(),d,42,'neutral.png');self.assertEqual(g['sampler']['inputs']['cfg'],6.25);self.assertEqual(g['ipadapter']['inputs']['weight'],.25);self.assertNotIn('tsumugoe_face',g)
 def test_effective_summary_and_validation(self):
  d=self.desc()['generation_settings'];self.assertEqual(d['cfg'],7);self.assertTrue(d['face_enabled']);self.assertFalse(d['negative_present']);self.assertEqual(d['ipadapter']['weight'],.4)
  for key,val in [('sampler_cfg',float('nan')),('face_inpaint',{'enabled':True,'denoise':2}),('ipadapter_settings',{'weight':float('inf')})]:
   c=config(self.s);c[key]=val
   with self.assertRaises(Problem):validate_config(c)

class IPAdapterDefaultTests(unittest.TestCase):
 def test_default_off_bypasses_reference_nodes(self):
  c=defaults();self.assertFalse(c['ipadapter_settings']['enabled']);g=build(c,{'prompt':'neutral'},{'loras':[],'reference_id':'image'},42,'neutral.png');self.assertNotIn('ipadapter',g);self.assertNotIn('reference_image',g);self.assertEqual(g['sampler']['inputs']['model'],['checkpoint',0])
