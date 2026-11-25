import copy,unittest
import test_cg as fixtures
from model import Store,Problem
from tracks import Tracks
from cg import CG,describe
from test_pilot import PNG
class IndependentCGTests(unittest.TestCase):
 def setUp(self):fixtures.CGTests.setUp(self);self.manager=Tracks(self.s)
 def tearDown(self):fixtures.CGTests.tearDown(self)
 def track(self):return self.s.data['works'][0]['tracks'][0]
 def update(self,p):
  r=self.s.import_payload(p,work_id='w',track_id=self.tid,track_mode='update')
  if r.get('confirmation_required'):r=self.s.import_payload(p,work_id='w',track_id=self.tid,track_mode='update',confirmation=r['confirmation'])
  return r
 def test_cg_only_creates_no_units_or_blocks(self):
  r=self.s.import_payload({'cgs':[{'id':'CG-X','block':'B9','prompt':'neutral'}]},work_id='w');t=self.s.data['works'][0]['tracks'][-1];self.assertFalse(t['units']);self.assertFalse(t['blocks']);self.assertEqual(t['cgs'][0]['id'],'CG-X');self.assertNotIn('unit',t['cgs'][0]);self.assertTrue(describe(self.s,self.s.data,'w',r['track_id'],'CG-X')['needs_check'])
 def test_legacy_prefix_and_separate_identity(self):
  self.update({'cgs':[{'unit':'B6-3','prompt':'neutral'}]});c=next(c for c in self.track()['cgs'] if c['id']=='B6-3');self.assertEqual(c['start_unit'],'B6-3');self.assertNotIn('unit',c);self.assertEqual([u['id'] for u in self.track()['units']],['B1-1'])
 def test_block_delete_retains_cg_and_actual_image(self):
  mid=CG(self.s).upload('w',self.tid,'B1-1','neutral.png',PNG)['media_id'];path=self.s.media_path(self.s.data['media'][mid]);p=self.manager.block_preview('w',self.tid,'B1');self.assertEqual(p['cg_timing_count'],1);self.assertEqual(p['cg_count'],0);self.manager.block_delete('w',self.tid,'B1',p['signature'],True);t=self.track();self.assertFalse(t['units']);self.assertIsNone(t['cgs'][0]['block']);self.assertTrue(path.exists());self.assertEqual(t['cgs'][0]['image_id'],mid);self.assertTrue(describe(self.s,self.s.data,'w',self.tid,'B1-1')['needs_check']);self.assertEqual(Store(self.base).data,self.s.data)
 def test_timing_edit_keeps_generation_image_and_fingerprint(self):
  mid=CG(self.s).upload('w',self.tid,'B1-1','neutral.png',PNG)['media_id'];bid=self.manager.block_add('w',self.tid)['block_id'];before=describe(self.s,self.s.data,'w',self.tid,'B1-1')['fingerprint'];CG(self.s).save('w',self.tid,'B1-1',{'block':bid});c=self.track()['cgs'][0];self.assertEqual(c['block'],bid);self.assertEqual(c['image_id'],mid);self.assertEqual(before,describe(self.s,self.s.data,'w',self.tid,'B1-1')['fingerprint']);self.assertFalse(c.get('changed',False))
 def test_duplicate_block_import_and_edit_are_atomic(self):
  before=self.s.path.read_bytes()
  with self.assertRaises(Problem):self.update({'cgs':[{'id':'CG-X','block':'B1','prompt':'neutral'}]})
  self.assertEqual(before,self.s.path.read_bytes());self.update({'cgs':[{'id':'CG-X','block':None,'prompt':'neutral'}]});before=self.s.path.read_bytes()
  with self.assertRaises(Problem):CG(self.s).save('w',self.tid,'CG-X',{'block':'B1'})
  self.assertEqual(before,self.s.path.read_bytes())
 def test_migration_preserves_images_text_and_extra_data_once(self):
  t=self.track();old=copy.deepcopy(t['cgs'][0]);old['image_id']='existing-image';old['extra']={'neutral':True};t['units'][0]['cg']=old;t.pop('cgs');before=copy.deepcopy(t['units'][0]['lines']);self.s._atomic(self.s.path,self.s.data);fresh=Store(self.base);t=fresh.data['works'][0]['tracks'][0];self.assertNotIn('cg',t['units'][0]);self.assertEqual(t['units'][0]['lines'],before);self.assertEqual(t['cgs'][0]['image_id'],'existing-image');self.assertTrue(t['cgs'][0]['extra']['neutral']);self.assertEqual(Store(self.base).data,fresh.data)
 def test_duplicate_legacy_migration_unsets_second_only(self):
  from cg_records import migrate
  d=copy.deepcopy(self.s.data);t=d['works'][0]['tracks'][0];t['cgs']=[];t['units'][0]['cg']={'prompt':'one','image_id':'one'};t['units'].append(dict(id='B1-2',block='B1',lines=[],cg={'prompt':'two','image_id':'two'}));migrate(d);self.assertEqual([c['block'] for c in t['cgs']],['B1',None]);self.assertEqual([c['image_id'] for c in t['cgs']],['one','two'])
 def test_whole_pack_independent_cg_id_never_becomes_unit(self):
  self.update({'lines':[{'unit':'B1-1','lines':['neutral']}],'cgs':[{'id':'CG-X','block':'B1','prompt':'neutral'}]});self.assertEqual([u['id'] for u in self.track()['units']],['B1-1']);self.assertEqual([c['id'] for c in self.track()['cgs']],['CG-X'])

 def test_unit_timing_allows_distinct_units_in_same_block(self):
  self.update({'lines':[{'unit':'B1-2','lines':['neutral second']}],'cgs':[{'id':'B1-1','start_unit':'B1-1','prompt':'neutral first'},{'id':'CG-X','start_unit':'B1-2','prompt':'neutral second'}]});self.assertEqual([c.get('start_unit') for c in self.track()['cgs']],['B1-1','B1-2']);self.assertFalse(describe(self.s,self.s.data,'w',self.tid,'CG-X')['needs_check'])
 def test_unit_timing_save_preserves_image_and_generation_fingerprint(self):
  self.update({'lines':[{'unit':'B1-2','lines':['neutral second']}]});mid=CG(self.s).upload('w',self.tid,'B1-1','neutral.png',PNG)['media_id'];before=describe(self.s,self.s.data,'w',self.tid,'B1-1')['fingerprint'];CG(self.s).save('w',self.tid,'B1-1',{'start_unit':'B1-2'});c=self.track()['cgs'][0];self.assertEqual(c['start_unit'],'B1-2');self.assertNotIn('block',c);self.assertEqual(c['image_id'],mid);self.assertEqual(before,describe(self.s,self.s.data,'w',self.tid,'B1-1')['fingerprint']);self.assertEqual(Store(self.base).data,self.s.data)
 def test_duplicate_unit_and_legacy_block_start_rejected(self):
  before=self.s.path.read_bytes()
  with self.assertRaises(Problem):self.update({'cgs':[{'id':'CG-X','start_unit':'B1-1','prompt':'neutral'}]})
  self.assertEqual(before,self.s.path.read_bytes())
 def test_block_delete_clears_unit_timing_but_keeps_cg(self):
  CG(self.s).save('w',self.tid,'B1-1',{'start_unit':'B1-1'});p=self.manager.block_preview('w',self.tid,'B1');self.assertEqual(p['cg_timing_count'],1);self.manager.block_delete('w',self.tid,'B1',p['signature'],True);self.assertIsNone(self.track()['cgs'][0]['start_unit']);self.assertTrue(describe(self.s,self.s.data,'w',self.tid,'B1-1')['needs_check'])

 def test_unit_alias_keeps_exact_timing_for_same_block(self):
  self.update({'lines':[{'unit':'B1-1','lines':['neutral first']},{'unit':'B1-2','lines':['neutral second']}],'cgs':[{'unit':'B1-1','prompt':'neutral first'},{'id':'CG-X','unit':'B1-2','block':'B1','prompt':'neutral second','future':{'preserved':True}}]});c=self.track()['cgs'];self.assertEqual([r['start_unit'] for r in c],['B1-1','B1-2']);self.assertEqual(c[1]['id'],'CG-X');self.assertTrue(c[1]['future']['preserved']);self.assertNotIn('unit',c[1]);self.assertEqual(len(self.track()['units']),2);self.assertEqual(Store(self.base).data,self.s.data)
 def test_explicit_start_unit_overrides_unit_alias_including_null(self):
  self.update({'lines':[{'unit':'B1-2','lines':['neutral second']}],'cgs':[{'id':'CG-X','unit':'B1-1','start_unit':'B1-2','prompt':'neutral'}]});c=next(c for c in self.track()['cgs'] if c['id']=='CG-X');self.assertEqual(c['start_unit'],'B1-2')
  self.update({'cgs':[{'id':'CG-X','unit':'B1-1','start_unit':None,'prompt':'neutral'}]});c=next(c for c in self.track()['cgs'] if c['id']=='CG-X');self.assertIsNone(c['start_unit'])
 def test_cg_unit_alias_never_creates_dialogue_unit(self):
  r=self.s.import_payload({'cgs':[{'unit':'B9-1','prompt':'neutral one'},{'unit':'B9-2','prompt':'neutral two'}]},work_id='w');t=self.s.data['works'][0]['tracks'][-1];self.assertEqual([c['start_unit'] for c in t['cgs']],['B9-1','B9-2']);self.assertFalse(t['units']);self.assertFalse(t['blocks'])
