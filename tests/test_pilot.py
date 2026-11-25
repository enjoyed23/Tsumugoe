import base64,copy,hashlib,io,json,shutil,tempfile,threading,unittest,wave
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from app import BASE,make_server
from model import Store,Problem
import connections
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=')
def wav_bytes():
 buffer=io.BytesIO()
 with wave.open(buffer,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(b'\x00\x00'*800)
 return buffer.getvalue()
class PilotTests(unittest.TestCase):
 def setUp(self):
  root=BASE/'work/test-runs';root.mkdir(parents=True,exist_ok=True);self.tmp=tempfile.TemporaryDirectory(dir=root);self.base=Path(self.tmp.name);shutil.copy2(BASE/'config.default.json',self.base/'config.default.json');shutil.copytree(BASE/'web',self.base/'web');self.s=Store(self.base)
 def tearDown(self):self.tmp.cleanup()
 def add_actor(self,key='actor',name='Neutral actor'):
  self.s.save('actors',dict(id=key,name=name,trigger_word='neutral_trigger'));return key
 def add_work(self,key='work',title='Neutral work'):
  self.s.save('works',dict(id=key,title=title));return key
 def add_voice(self,key='voice'):
  self.s.save('voices',dict(id=key,name='Neutral voice'));return key
 def role(self,wid,key='role',name='案内',reading='あんない',**extra):
  self.s.save('character',dict(id=key,actor_id='actor',names=dict(full=name,family='',given='',aliases=[]),readings=[dict(text=name,reading=reading)],occupation='案内係',personality='丁寧',background='一般的な背景',**extra),work_id=wid)
 def test_empty_work_and_empty_title_are_valid_containers(self):
  first=self.s.save('works',{})
  second=self.s.save('works',dict(title=''))
  fresh=Store(self.base)
  self.assertNotEqual(first['id'],second['id'])
  for w in fresh.data['works']:
   self.assertEqual(w['title'],'無題の作品');self.assertEqual(w['tracks'],[]);self.assertEqual(w['characters'],[])
 def test_reading_autosave_returns_stable_identity(self):
  self.add_work();first=self.s.reading_save('work',dict(text='検証名',reading=''))
  self.s.reading_save('work',dict(id=first['id'],text='検証名',reading='けんしょうめい'))
  rows=Store(self.base).data['works'][0]['readings']
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]['id'],first['id']);self.assertEqual(rows[0]['reading'],'けんしょうめい')
 def test_actor_reused_by_two_works_and_role_edits_are_independent(self):
  self.add_actor();self.add_work();self.add_work('other');self.role('work');self.role('other');before=copy.deepcopy(self.s.data['works']);self.s.save('actors',dict(id='actor',name='Updated asset',trigger_word='changed'))
  self.assertEqual(self.s.data['works'],before);self.s.save('character',dict(id='role',occupation='受付'),work_id='work');self.assertEqual(self.s.find(self.s.data,'works','other')['characters'][0]['occupation'],'案内係');self.assertEqual(self.s.data['actors'][0]['name'],'Updated asset')
 def test_same_display_names_and_work_titles_never_select_records(self):
  self.s.import_payload(dict(actors=[dict(name='Same'),dict(name='Same')],works=[dict(title='Same'),dict(title='Same')]))
  self.assertEqual(len(self.s.data['actors']),2);self.assertEqual(len({a['id'] for a in self.s.data['actors']}),2);self.assertEqual(len(self.s.data['works']),2)
 def test_unknown_information_including_underscore_and_nested_fields_survives(self):
  self.s.import_payload(dict(actors=[dict(id='a',name='Neutral',_custom={'x':[1,2]},future={'nested':{'a':'original'}})],future_root={'arbitrary':['retained']}))
  self.s.save('actors',dict(id='a',future={'nested':{'b':'new'}}));fresh=Store(self.base);self.assertEqual(fresh.data['actors'][0]['_custom'],{'x':[1,2]});self.assertEqual(fresh.data['actors'][0]['future']['nested'],{'a':'original','b':'new'});self.assertEqual(fresh.data['extensions']['future_root'],{'arbitrary':['retained']})
 def test_import_validates_entire_batch_before_writing(self):
  before=self.s.path.read_bytes()
  with self.assertRaises(Problem):self.s.import_payload(dict(actors=[dict(name='Valid'),dict(name=12)]))
  self.assertEqual(before,self.s.path.read_bytes());self.assertEqual(self.s.data['actors'],[])
 def test_duplicate_ids_inside_a_packet_fail_atomically(self):
  with self.assertRaises(Problem):self.s.import_payload(dict(actors=[dict(id='same',name='A'),dict(id='same',name='B')]))
  self.assertEqual(self.s.data['revision'],0)
 def test_name_dictionary_seeding_blank_readings_aliases_and_kanji(self):
  self.add_actor();self.add_work();self.s.save('character',dict(actor_id='actor',names=dict(full='案内',family='案内',given='係',aliases=['ガイド']),readings=[dict(text='案内',reading='案内'),dict(text='案内',reading='')]),work_id='work')
  rows=self.s.data['works'][0]['readings'];self.assertEqual({r['text'] for r in rows},{'案内','係','ガイド'});self.assertEqual(next(r for r in rows if r['text']=='係')['reading'],'');self.assertEqual(next(r for r in rows if r['text']=='案内')['reading'],'案内')
 def test_reading_conflict_aborts_role_and_entire_import(self):
  self.add_actor();self.add_work();self.role('work');before=self.s.path.read_bytes()
  with self.assertRaises(Problem):self.role('work','second',reading='べつよみ')
  self.assertEqual(self.s.path.read_bytes(),before)
  with self.assertRaises(Problem):self.s.import_payload(dict(actors=[dict(name='Must not persist')],characters=[dict(names=dict(full='案内'),readings=[dict(text='案内',reading='べつ')])],work_id='work'))
  self.assertEqual(self.s.path.read_bytes(),before)
 def test_reading_conflicts_are_local_to_each_work(self):
  self.add_actor();self.add_work();self.add_work('other');self.role('work');self.role('other',reading='ガイド');self.assertEqual(self.s.data['works'][1]['readings'][0]['reading'],'ガイド')
 def test_manual_dictionary_edit_is_single_truth_and_prevents_duplicate_readings(self):
  self.add_actor();self.add_work();self.role('work');row=self.s.data['works'][0]['readings'][0];self.s.reading_save('work',dict(id=row['id'],text=row['text'],reading='ガイド'))
  self.assertEqual(self.s.data['works'][0]['readings'][0]['reading'],'ガイド')
  with self.assertRaises(Problem):self.s.reading_save('work',dict(text='案内',reading='べつ'))
 def test_name_change_requires_preview_then_preserves_shared_and_manual_entries(self):
  self.add_actor();self.add_work();self.role('work');self.role('work','second');row=self.s.data['works'][0]['readings'][0];self.s.reading_save('work',dict(id=row['id'],text='案内',reading='あんない'));before=self.s.path.read_bytes();patch=dict(id='role',names=dict(full='受付'),readings=[dict(text='受付',reading='うけつけ')]);preview=self.s.save('character',patch,work_id='work',preview=True)
  self.assertTrue(preview['names_changed']);self.assertEqual(self.s.path.read_bytes(),before)
  with self.assertRaises(Problem):self.s.save('character',patch,work_id='work')
  self.s.save('character',patch,work_id='work',confirmed_names=True);self.assertEqual({r['text'] for r in self.s.data['works'][0]['readings']},{'案内','受付'})
 def test_sole_automatic_name_follows_rename_after_confirmation(self):
  self.add_actor();self.add_work();self.role('work');self.s.save('character',dict(id='role',names=dict(full='受付')),work_id='work',confirmed_names=True);self.assertEqual([r['text'] for r in self.s.data['works'][0]['readings']],['受付'])
 def test_reading_delete_of_name_keeps_a_missing_reading_row(self):
  self.add_actor();self.add_work();self.role('work');row=self.s.data['works'][0]['readings'][0];self.s.reading_delete('work',row['id']);self.assertEqual(self.s.data['works'][0]['readings'][0]['reading'],'')
 def test_image_is_copied_replacement_is_confirmed_and_old_file_removed(self):
  self.add_actor();result=self.s.upload('actors','actor','neutral.png',PNG);old=self.s.media_path(self.s.data['media'][result['media_id']]);self.assertEqual(old.read_bytes(),PNG)
  with self.assertRaises(Problem):self.s.upload('actors','actor','replacement.png',PNG)
  new=self.s.upload('actors','actor','replacement.png',PNG,replacing=True);self.assertFalse(old.exists());self.assertTrue(self.s.media_path(self.s.data['media'][new['media_id']]).exists())
 def test_bad_audio_does_not_write_media_or_metadata(self):
  self.add_voice();before=self.s.path.read_bytes()
  with self.assertRaises(Problem):self.s.upload('voices','voice','bad.wav',b'not a wav')
  self.assertEqual(self.s.path.read_bytes(),before);self.assertFalse((self.s.work/'media').exists())
 def test_voice_candidate_registration_confirmation_and_restart(self):
  self.add_voice();self.s.upload('voices','voice','neutral.wav',wav_bytes());voice=self.s.data['voices'][0];ref=voice['references'][0];self.assertAlmostEqual(ref['seconds'],.1);self.s.save('voices',dict(id='voice',confirmed_reference_id=ref['id']));fresh=Store(self.base);self.assertEqual(fresh.data['voices'][0]['confirmed_reference_id'],ref['id']);self.assertEqual(fresh.voice_status(fresh.data['voices'][0],fresh.data),[])
 def test_assigning_voice_affects_one_role_not_other_works_or_actor(self):
  self.add_actor();self.add_voice();self.add_voice('other_voice');self.add_work();self.add_work('other');self.role('work',default_voice_id='voice');self.role('other',default_voice_id='voice');actors=copy.deepcopy(self.s.data['actors']);self.s.save('character',dict(id='role',default_voice_id='other_voice'),work_id='work');self.assertEqual(self.s.data['works'][1]['characters'][0]['default_voice_id'],'voice');self.assertEqual(self.s.data['actors'],actors)
 def test_delete_two_stage_usage_and_missing_reference_preserve_role_information(self):
  self.add_actor();self.add_voice();self.add_work();self.role('work',default_voice_id='voice');before=copy.deepcopy(self.s.data['works']);preview=self.s.deletion_preview('actors','actor');self.assertEqual(preview['usage']['works'][0]['track_count'],0)
  with self.assertRaises(Problem):self.s.delete('actors','actor',preview['signature'])
  self.s.delete('actors','actor',preview['signature'],True);self.assertEqual(self.s.data['works'],before);self.assertTrue(self.s.character_status(before[0]['characters'][0],self.s.data))
 def test_stale_delete_preview_cannot_delete_changed_data(self):
  self.add_actor();preview=self.s.deletion_preview('actors','actor');self.s.save('actors',dict(id='actor',name='Updated'))
  with self.assertRaises(Problem):self.s.delete('actors','actor',preview['signature'],True)
  self.assertEqual(self.s.data['actors'][0]['name'],'Updated')
 def test_work_deletion_keeps_independent_voice_actor_and_media(self):
  self.add_actor();self.add_voice();self.add_work();self.role('work');result=self.s.upload('actors','actor','neutral.png',PNG);path=self.s.media_path(self.s.data['media'][result['media_id']]);preview=self.s.deletion_preview('works','work');self.s.delete('works','work',preview['signature'],True);self.assertEqual(self.s.data['works'],[]);self.assertEqual(len(self.s.data['actors']),1);self.assertEqual(len(self.s.data['voices']),1);self.assertTrue(path.exists())
 def test_voice_deletion_removes_owned_audio_but_not_character(self):
  self.add_actor();self.add_voice();self.add_work();self.role('work',default_voice_id='voice');result=self.s.upload('voices','voice','neutral.wav',wav_bytes());path=self.s.media_path(self.s.data['media'][result['media_id']]);preview=self.s.deletion_preview('voices','voice');self.s.delete('voices','voice',preview['signature'],True);self.assertFalse(path.exists());self.assertEqual(self.s.data['works'][0]['characters'][0]['default_voice_id'],'voice')
 def test_shared_media_is_not_deleted_while_other_asset_uses_it(self):
  self.add_actor();self.add_actor('other');result=self.s.upload('actors','actor','neutral.png',PNG);mid=result['media_id'];self.s.save('actors',dict(id='other',image_id=mid));preview=self.s.deletion_preview('actors','actor');self.s.delete('actors','actor',preview['signature'],True);self.assertTrue(self.s.media_path(self.s.data['media'][mid]).exists())
 def test_stale_save_is_rejected_without_changes(self):
  self.add_actor();before=self.s.path.read_bytes()
  with self.assertRaises(Problem):self.s.save('actors',dict(id='actor',name='Stale'),revision=0)
  self.assertEqual(self.s.path.read_bytes(),before)
 def test_large_input_is_not_artificially_limited(self):
  self.s.import_payload(dict(actors=[dict(name='Neutral',appearance_notes='材料'*100000,future_list=list(range(10000)))]));self.assertEqual(len(self.s.data['actors'][0]['appearance_notes']),200000)
 def test_metadata_backup_kept_before_save(self):
  before=self.s.path.read_bytes();self.add_actor();backup=self.s.work/'history/metadata-00000000.json';self.assertEqual(backup.read_bytes(),before)
 def test_local_endpoints_only_and_redirects_are_checked(self):
  for url in ('https://example.com','http://192.168.1.2:8188','http://localhost.example.com','file:///etc/passwd','http://user:pass@localhost:8188'):
   with self.assertRaises(Problem):connections.local_endpoint(url)
  self.assertEqual(connections.local_endpoint('http://127.0.0.1:8188/'),'http://127.0.0.1:8188')
  with self.assertRaises(Problem):connections.LocalRedirect().redirect_request(None,None,302,'',{},'https://example.com')
 def test_tts_check_uses_shutdown_and_offline_environment_not_synthesis(self):
  for key in ('python','worker','checkpoint'):
   path=self.base/(key+'.fixture');path.write_bytes(b'neutral');self.s.config['tts'][key]=str(path)
  self.s.config['tts']['project_dir']=str(self.base)
  def run(args,**kwargs):
   request=json.loads(kwargs['input']);self.assertEqual(request['action'],'shutdown');self.assertNotIn('text',request);self.assertEqual(kwargs['env']['HF_HUB_OFFLINE'],'1');self.assertTrue(Path(kwargs['cwd']).is_relative_to(self.s.work));return type('Result',(),dict(returncode=0,stdout='@@IRODORI@@'+json.dumps(dict(id=request['id'],shutdown=True))))()
  with patch('connections.subprocess.run',side_effect=run):self.assertTrue(connections.check_tts(self.s)['ok'])
 def test_pilot_has_no_track_production_ui(self):
  html=(BASE/'web/index.html').read_text(encoding='utf-8');self.assertIn('資産ライブラリ',html);self.assertNotIn('音声生成スタジオ',html);self.assertNotIn('ノベル表示',html)

 def test_failed_delete_restores_metadata_and_image(self):
  self.add_actor();mid=self.s.upload('actors','actor','neutral.png',PNG)['media_id'];path=self.s.media_path(self.s.data['media'][mid]);before=self.s.path.read_bytes();preview=self.s.deletion_preview('actors','actor');original=self.s._atomic
  def fail_write(target,value):
   if target==self.s.path:raise OSError('neutral write failure')
   return original(target,value)
  with patch.object(self.s,'_atomic',side_effect=fail_write):
   with self.assertRaises(OSError):self.s.delete('actors','actor',preview['signature'],True)
  self.assertEqual(self.s.path.read_bytes(),before);self.assertEqual(path.read_bytes(),PNG);self.assertEqual(len(self.s.data['actors']),1)
 def test_comfy_local_success_response_without_generation(self):
  from http.server import BaseHTTPRequestHandler,HTTPServer
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(handler):
    if handler.path!='/system_stats':raise AssertionError('Unexpected generate request')
    data=json.dumps({'system':{'os':'test'}}).encode();handler.send_response(200);handler.send_header('Content-Length',str(len(data)));handler.end_headers();handler.wfile.write(data)
  server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:self.s.config['comfyui']['endpoint']=f'http://127.0.0.1:{server.server_port}';self.assertTrue(connections.check_comfy(self.s)['ok'])
  finally:server.shutdown();server.server_close();thread.join()

 def test_unknown_fields_on_character_reading_rows_are_retained(self):
  self.add_actor();self.add_work();self.s.import_payload({'characters':[{'actor_id':'actor','names':{'full':'案内'},'readings':[{'text':'案内','reading':'あんない','future':{'note':'retained'}}]}],'work_id':'work'})
  row=self.s.data['works'][0]['readings'][0];self.assertEqual(row['future'],{'note':'retained'})

class HttpTests(unittest.TestCase):
 add_voice=PilotTests.add_voice
 def setUp(self):
  PilotTests.setUp(self);self.server=make_server(self.s,0);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.url=f'http://127.0.0.1:{self.server.server_port}'
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();PilotTests.tearDown(self)
 def post(self,path,value,headers=None):
  req=Request(self.url+'/api/'+path,data=json.dumps(value).encode(),headers={'Content-Type':'application/json',**(headers or {})})
  with urlopen(req,timeout=5) as r:return json.load(r)
 def test_http_asset_save_state_and_cross_origin_block(self):
  result=self.post('save',dict(kind='actors',record=dict(name='Neutral'),revision=0));self.assertTrue(result['id'])
  with urlopen(self.url+'/api/state') as r:self.assertEqual(len(json.load(r)['actors']),1)
  with self.assertRaises(HTTPError) as caught:self.post('save',dict(kind='actors',record=dict(name='Must not save')),{'Origin':'http://example.com'})
  self.assertEqual(caught.exception.code,403);self.assertEqual(len(self.s.data['actors']),1)
 def test_http_media_range_and_path_isolation(self):
  self.add_voice();result=self.s.upload('voices','voice','neutral.wav',wav_bytes());req=Request(self.url+'/media/'+result['media_id'],headers={'Range':'bytes=0-7'})
  with urlopen(req) as r:self.assertEqual(r.status,206);self.assertEqual(r.read(),wav_bytes()[:8])
  with self.assertRaises(HTTPError) as caught:urlopen(self.url+'/media/../../config.default.json')
  self.assertEqual(caught.exception.code,404)
 def test_http_bad_import_keeps_file_unchanged(self):
  before=self.s.path.read_bytes()
  with self.assertRaises(HTTPError):self.post('import',dict(text='{"actors": [}'))
  self.assertEqual(self.s.path.read_bytes(),before)
if __name__=='__main__':unittest.main()
