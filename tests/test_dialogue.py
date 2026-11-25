import copy,shutil,tempfile,unittest
from pathlib import Path
from model import Store,Problem
from app import BASE
from dialogue import Dialogue,derive,preview
class DialogueTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=BASE/'work/test-runs');self.base=Path(self.tmp.name);shutil.copy2(BASE/'config.default.json',self.base/'config.default.json');self.s=Store(self.base);self.s.save('works',dict(id='w',title='Neutral'));r=self.s.import_payload(dict(lines=[dict(unit='B1-1',lines=['[案内]係です。','']),dict(unit='B1-2',lines=['案内します。'])]),work_id='w');self.tid=r['track_id'];self.d=Dialogue(self.s)
 def tearDown(self):self.tmp.cleanup()
 def work(self):return self.s.data['works'][0]
 def track(self):return self.work()['tracks'][0]
 def test_readings_keep_original_and_remove_brackets(self):
  self.s.reading_save('w',dict(text='案内',reading='あんない'));u=self.track()['units'][0];p=preview(self.track(),u,self.work());self.assertEqual(p['lines'],['あんない係です。','']);self.assertEqual(p['display_lines'],['案内係です。','']);self.assertEqual(u['lines'],['[案内]係です。','']);self.assertEqual(derive(['案内 [未知]'],self.work())['text'],'案内 未知')
 def test_missing_flag_and_manual_clear(self):
  u=self.track()['units'][0];self.assertTrue(u['needs_check']);self.assertIn('読み未登録',u['check_reasons'])
  with self.assertRaises(Problem):self.d.clear_check('w',self.tid,u['id'])
  self.s.reading_save('w',dict(text='案内',reading='案内'));self.assertTrue(u['needs_check']);self.d.clear_check('w',self.tid,u['id']);self.assertFalse(self.track()['units'][0]['needs_check'])
 def test_dictionary_only_marks_bracketed_occurrences_and_keeps_files(self):
  t=self.track();p=self.s.work/'sample.wav';p.write_bytes(b'neutral');self.s.data['media']['m']={'path':'sample.wav'};t['units'][0]['audio_ids']=['m'];self.s.reading_save('w',dict(text='案内',reading='あんない'));self.assertTrue(self.track()['units'][0]['audio_changed']);self.assertFalse(self.track()['units'][1]['audio_changed']);self.assertTrue(p.exists());self.assertEqual(self.track()['units'][0]['audio_ids'],['m'])
 def test_edit_lines_keeps_audio_and_cg_marks_changed(self):
  u=self.track()['units'][1];u['audio_ids']=['old'];u['cg']={'prompt':'neutral'};self.d.unit_save('w',self.tid,u['id'],dict(lines=['Updated','',''],speaker='role',level='calm'));u=self.track()['units'][1];self.assertEqual(u['lines'],['Updated','','']);self.assertEqual(u['audio_ids'],['old']);self.assertEqual(u['cg'],{'prompt':'neutral'});self.assertTrue(u['audio_changed'])
 def test_bad_brackets_and_types_are_atomic(self):
  for line in ('[]','[a','a]','[[a]]'):
   before=self.s.path.read_bytes()
   with self.assertRaises(Problem):self.d.unit_save('w',self.tid,'B1-1',dict(lines=[line]))
   self.assertEqual(before,self.s.path.read_bytes())
  with self.assertRaises(Problem):self.d.unit_save('w',self.tid,'B1-1',dict(level=3))
 def test_levels_import_edit_and_affected_scope(self):
  r=self.s.import_payload(dict(levels={'calm':{'caption':'Neutral caption','future':True}},lines=[dict(unit='B1-2',lines=['Normal'],level='calm')]),work_id='w',track_id=self.tid,track_mode='update');self.assertFalse(r.get('confirmation_required',False));self.track()['units'][0]['audio_changed']=False;self.track()['units'][1]['audio_changed']=False;self.d.levels_save('w',self.tid,dict(calm={'caption':'Updated caption','voice_id':None,'future':True}));self.assertFalse(self.track()['units'][0]['audio_changed']);self.assertTrue(self.track()['units'][1]['audio_changed']);self.assertEqual(preview(self.track(),self.track()['units'][1],self.work())['caption'],'Updated caption');self.assertTrue(self.track()['levels']['calm']['future'])
 def test_caption_not_reading_replaced(self):
  self.s.reading_save('w',dict(text='案内',reading='あんない'));self.d.levels_save('w',self.tid,{'x':{'caption':'[案内]'}});self.d.unit_save('w',self.tid,'B1-1',{'level':'x'});self.assertEqual(preview(self.track(),self.track()['units'][0],self.work())['caption'],'[案内]')
 def test_add_reorder_persist_and_ids_stay_unique(self):
  r=self.d.add('w',self.tid,'B1','B1-1');self.assertEqual(r['unit_id'],'B1-3');self.assertEqual([u['id'] for u in self.track()['units']],['B1-1','B1-3','B1-2']);self.d.move('w',self.tid,'B1-3',-1);self.assertEqual(self.track()['units'][0]['id'],'B1-3');self.assertEqual(Store(self.base).data,self.s.data)
 def test_stale_edit_rejected_and_unknown_info_kept(self):
  rev=self.s.data['revision'];self.d.unit_save('w',self.tid,'B1-1',dict(future={'a':'kept'}));before=self.s.path.read_bytes()
  with self.assertRaises(Problem):self.d.unit_save('w',self.tid,'B1-1',dict(lines=['Old']),rev)
  self.assertEqual(before,self.s.path.read_bytes());self.assertEqual(self.track()['units'][0]['future'],{'a':'kept'})
 def test_import_unknown_level_and_speaker_are_retained(self):
  self.s.import_payload(dict(lines=[dict(unit='B1-2',lines=['Neutral'],speaker='future-role',level='future-level')]),work_id='w',track_id=self.tid,track_mode='update');p=preview(self.track(),self.track()['units'][1],self.work());self.assertTrue(p['speaker_missing']);self.assertTrue(p['level_missing'])

 def test_block_level_inherits_and_unit_overrides(self):
  self.d.levels_save('w',self.tid,{'a':{'caption':'A'},'b':{'caption':'B'}});self.d.unit_save('w',self.tid,'B1-2',{'level':'b'});self.d.block_save('w',self.tid,'B1','a');self.assertEqual(preview(self.track(),self.track()['units'][0],self.work())['caption'],'A');self.assertEqual(preview(self.track(),self.track()['units'][1],self.work())['caption'],'B')
 def test_dictionary_changes_do_not_mark_other_tracks_without_brackets(self):
  r=self.s.import_payload({'lines':[{'unit':'B1-1','lines':['案内です。']}]},work_id='w');self.s.reading_save('w',{'text':'案内','reading':'あんない'});self.assertTrue(self.track()['units'][0]['audio_changed']);self.assertFalse(self.work()['tracks'][1]['units'][0]['audio_changed'])
 def test_empty_lines_distinct_from_one_pause(self):
  self.d.unit_save('w',self.tid,'B1-2',{'lines':[]});self.assertEqual(self.track()['units'][1]['lines'],[]);self.d.unit_save('w',self.tid,'B1-2',{'lines':['']});self.assertEqual(self.track()['units'][1]['lines'],[''])
