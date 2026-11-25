import copy,json,shutil,tempfile,unittest
from pathlib import Path
from model import Store,Problem
from tracks import Tracks
from app import BASE
class TrackTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=BASE/'work/test-runs');self.base=Path(self.tmp.name);shutil.copy2(BASE/'config.default.json',self.base/'config.default.json');self.s=Store(self.base);self.s.save('works',dict(id='w',title='Neutral',settings={'future':'retained'}));self.m=Tracks(self.s)
 def tearDown(self):self.tmp.cleanup()
 def payload(self):return dict(track={'title':'Neutral Track','synopsis':'Neutral summary'},lines=[{'unit':'B1-1','lines':['First']},{'unit':'B1-2','lines':['Second']}],cgs=[{'id':'B1-1','block':'B1','prompt':'neutral tags'},{'id':'B1-2','block':None,'prompt':'neutral tags 2'}])
 def create(self,p=None):return self.s.import_payload(p or self.payload(),work_id='w')['track_id']
 def track(self,tid):return self.s.data['works'][0]['tracks'][next(i for i,t in enumerate(self.s.data['works'][0]['tracks']) if t['id']==tid)]
 def update(self,tid,p,confirm=True):
  r=self.s.import_payload(p,work_id='w',track_id=tid,track_mode='update')
  if r.get('confirmation_required') and confirm:r=self.s.import_payload(p,work_id='w',track_id=tid,track_mode='update',confirmation=r['confirmation'])
  return r
 def media(self,tid,uid,kind):
  mid=kind+'-'+uid;path=self.s.work/('media/'+mid+'.bin');path.parent.mkdir(exist_ok=True);path.write_bytes(b'neutral');self.s.data['media'][mid]=dict(path='media/'+mid+'.bin',filename=mid+'.bin');u=next(u for u in self.track(tid)['units'] if u['id']==uid)
  if kind=='audio':u['audio_ids']=[mid]
  else:next(c for c in self.track(tid)['cgs'] if c['id']==uid)['image_id']=mid
  self.s._atomic(self.s.path,self.s.data);return path
 def test_new_track_same_ids_never_touches_previous(self):
  t1=self.create();before=copy.deepcopy(self.track(t1));t2=self.create();self.assertNotEqual(t1,t2);self.assertEqual(before,self.track(t1));self.assertEqual(self.track(t2)['number'],2);self.assertEqual(self.track(t2)['prior_summaries'][0]['synopsis'],'Neutral summary')
 def test_single_lines_upserts_and_preserves_cgs_and_omitted_units(self):
  t=self.create();before=copy.deepcopy(self.track(t)['units'][1]);self.update(t,dict(lines=[dict(unit='B1-1',lines=['Updated']),dict(unit='B2-1',lines=['New'])]));u=self.track(t)['units'];self.assertEqual(u[0]['lines'],['Updated']);self.assertEqual(self.track(t)['cgs'][0]['prompt'],'neutral tags');self.assertEqual(u[1],before);self.assertEqual(u[2]['id'],'B2-1')
 def test_single_cgs_preserves_lines_and_omitted_cgs(self):
  t=self.create();self.update(t,dict(cgs=[dict(unit='B1-1',prompt='updated')]));u=self.track(t)['units'];self.assertEqual(u[0]['lines'],['First']);self.assertEqual(self.track(t)['cgs'][1]['prompt'],'neutral tags 2');self.assertEqual(len(u),2)
 def test_empty_lines_confirms_and_only_clears_lines_audio(self):
  t=self.create();audio=self.media(t,'B1-1','audio');image=self.media(t,'B1-1','image');r=self.update(t,{'lines':[]},False);self.assertTrue(r['confirmation_required']);self.assertEqual(r['delete_counts']['audio_files'],1);self.assertTrue(audio.exists());self.update(t,{'lines':[]});self.assertFalse(audio.exists());self.assertTrue(image.exists());self.assertEqual(len(self.track(t)['units']),2);self.assertTrue(all(not u['lines'] for u in self.track(t)['units']));self.assertTrue(len(self.track(t)['cgs'])==2)
 def test_empty_cgs_confirms_and_preserves_lines(self):
  t=self.create();self.assertTrue(self.update(t,{'cgs':[]},False)['confirmation_required']);self.update(t,{'cgs':[]});self.assertEqual(self.track(t)['units'][0]['lines'],['First']);self.assertTrue(not self.track(t)['cgs'])
 def test_empty_zero_always_confirms(self):
  r=self.s.import_payload({'lines':[]},work_id='w');self.assertTrue(r['confirmation_required']);self.assertEqual(r['delete_counts']['units'],0);self.assertEqual(self.s.data['works'][0]['tracks'],[])
 def test_whole_removes_only_ids_outside_union_and_never_shifts(self):
  t=self.create();audio=self.media(t,'B1-2','audio');r=self.update(t,dict(lines=[dict(unit='B1-2',lines=['Exact'])],cgs=[]),False);self.assertEqual(r['removed_units'],['B1-1']);self.assertEqual(r['delete_counts']['audio_files'],1);self.update(t,dict(lines=[dict(unit='B1-2',lines=['Exact'])],cgs=[]));self.assertEqual([u['id'] for u in self.track(t)['units']],['B1-2']);self.assertEqual(self.track(t)['units'][0]['lines'],['Exact']);self.assertFalse(audio.exists())
 def test_same_ids_audio_clear_requires_confirmation(self):
  t=self.create();p=self.media(t,'B1-1','audio');r=self.update(t,dict(lines=[dict(unit='B1-1',lines=['First'])]),False);self.assertTrue(r['confirmation_required']);self.assertEqual(r['delete_counts']['audio_files'],1);self.assertTrue(p.exists())
 def test_cg_overwrite_clears_image_and_preserves_shared_refs(self):
  t=self.create();p=self.media(t,'B1-1','image');mid=self.track(t)['cgs'][0]['image_id'];self.s.save('actors',dict(name='Neutral',image_id=mid));r=self.update(t,dict(cgs=[dict(unit='B1-1',prompt='different')]),False);self.assertEqual(r['delete_counts']['image_files'],0);self.assertEqual(r['delete_counts']['image_links'],1);self.update(t,dict(cgs=[dict(unit='B1-1',prompt='different')]));self.assertTrue(p.exists());self.assertIsNone(self.track(t)['cgs'][0]['image_id'])
 def test_invalid_batch_atomic_and_no_arbitrary_length_limit(self):
  t=self.create();before=self.s.path.read_bytes()
  with self.assertRaises(Problem):self.update(t,dict(lines=[dict(unit='B1-1',lines=['Valid']),dict(unit='B1-3',lines=['[broken'])]))
  self.assertEqual(before,self.s.path.read_bytes());text='neutral '*20000;self.update(t,dict(lines=[dict(unit='B1-1',lines=[text])],unknown={'large':text}));self.assertEqual(self.track(t)['units'][0]['lines'],[text]);self.assertEqual(self.track(t)['extensions']['unknown']['large'],text)
 def test_protected_work_fields_reported_original_retained(self):
  t=self.create();r=self.update(t,dict(lines=[dict(unit='B1-1',lines=['New'])],settings={'future':'overwrite'},setup={'x':'proposal'}));self.assertEqual(self.s.data['works'][0]['settings'],{'future':'retained'});self.assertEqual(len(r['report']['warnings']),2);self.assertEqual(self.track(t)['source_payload']['setup'],{'x':'proposal'})
 def test_block_add_move_delete_and_persistence(self):
  t=self.create();r=self.m.block_add('w',t,'B1','before');bid=r['block_id'];self.assertEqual(self.track(t)['blocks'][0]['id'],bid);self.assertEqual(len(self.track(t)['units']),2);self.m.move_unit('w',t,'B1-2',bid);p=self.m.block_preview('w',t,bid);self.assertEqual(p['unit_count'],1);self.m.block_delete('w',t,bid,p['signature'],True);self.assertEqual([u['id'] for u in self.track(t)['units']],['B1-1']);fresh=Store(self.base);self.assertEqual(fresh.data,self.s.data)
 def test_stale_confirmation_has_no_side_effects(self):
  t=self.create();r=self.update(t,{'lines':[]},False);self.m.save_meta('w',t,dict(synopsis='Changed'));before=self.s.path.read_bytes();v=self.s.import_payload({'lines':[]},work_id='w',track_id=t,track_mode='update',confirmation=r['confirmation']);self.assertTrue(v['confirmation_required']);self.assertEqual(before,self.s.path.read_bytes())
 def test_explicit_update_target_required(self):
  t=self.create()
  with self.assertRaises(Problem):self.s.import_payload({'lines':[]},work_id='w',track_mode='update')
  with self.assertRaises(Problem):self.update(t,dict(track={'id':'unrelated'},lines=[]))
 def test_work_asset_update_cannot_replace_tracks(self):
  t=self.create();self.s.save('works',dict(id='w',tracks=[]));self.assertEqual(self.track(t)['title'],'Neutral Track');self.assertEqual(self.s.data['works'][0]['extensions']['imported_tracks'],[])
 def test_no_manual_unit_delete(self):self.assertFalse(hasattr(self.m,'delete_unit'))

 def test_absent_lines_never_updates_from_supplemental_units(self):
  t=self.create();self.update(t,dict(units=[dict(id='B1-1',lines=['Supplemental source'])]));self.assertEqual(self.track(t)['units'][0]['lines'],['First']);self.assertEqual(self.track(t)['units'][0]['extensions']['lines'],['Supplemental source'])
 def test_unknown_id_cannot_rekey_line_target(self):
  t=self.create();self.update(t,dict(lines=[dict(unit='B1-1',id='OTHER',lines=['Exact'])]));self.assertEqual(self.track(t)['units'][0]['id'],'B1-1');self.assertEqual(self.track(t)['units'][1]['lines'],['Second'])
