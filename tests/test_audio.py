import copy,shutil,tempfile,time,wave,array,unittest,threading
from pathlib import Path
from unittest.mock import patch
from app import BASE
from model import Store,Problem
from audio import Audio,audio,view,summary,context,wav_info
from audio_jobs import Jobs,export_wav
from dialogue import Dialogue

def make_wav(path,rate=8000,frames=800,value=2000):
 with wave.open(str(path),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes(array.array('h',[value]*frames).tobytes())
class FakeWorker:
 fail=False;cancel_after=None;calls=[]
 def __init__(self,s,cancel):self.s=s;self.cancel=cancel;self.count=0
 def synthesize(self,ctx,path):
  self.count+=1;type(self).calls.append(copy.deepcopy(ctx))
  if self.fail:raise Problem('Neutral simulated failure')
  make_wav(path)
  if self.cancel_after==self.count:self.cancel.set()
 def close(self):pass
class AudioTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=BASE/'work/test-runs');self.base=Path(self.tmp.name);shutil.copy2(BASE/'config.default.json',self.base/'config.default.json');self.s=Store(self.base);self.s.save('works',dict(id='w',title='Neutral'));self.s.save('voices',dict(id='v',name='Neutral no-ref'));r=self.s.import_payload(dict(lines=[dict(unit='B1-1',lines=['Neutral one','Neutral two']),dict(unit='B2-1',lines=['Neutral three'])]),work_id='w');self.tid=r['track_id'];self.a=Audio(self.s);self.a.edit('w',self.tid,'rebuild',{'target_seconds':.1,'chars_per_second':6});self.a.edit('w',self.tid,'track',{'voice_id':'v'});self.jobs=Jobs(self.s);self.jobs.worker_factory=FakeWorker;FakeWorker.fail=False;FakeWorker.cancel_after=None;FakeWorker.calls=[]
 def tearDown(self):self.tmp.cleanup()
 def track(self):return self.s.data['works'][0]['tracks'][0]
 def rows(self):return view(self.track(),self.s.data['works'][0],self.s.data,self.s)['chunks']
 def generate(self,mode='all',ids=None):
  with patch('audio_jobs.config_problems',return_value=[]):
   p=self.jobs.preview('w',self.tid,mode,ids);self.jobs.start('w',self.tid,mode,ids,p['token'])
  deadline=time.monotonic()+5
  while self.jobs.status()['running'] and time.monotonic()<deadline:time.sleep(.01)
  self.assertFalse(self.jobs.status()['running']);self.assertNotIn('error',self.jobs.status());return self.jobs.status()
 def test_split_uses_reading_length_and_line_boundaries(self):
  t=self.track();self.assertEqual([c['lines'] for c in audio(t)['chunks']],[[0],[1],[0]]);self.s.reading_save('w',{'text':'X','reading':'a'*50});Dialogue(self.s).unit_save('w',self.tid,'B1-1',{'lines':['[X]','short']});p=self.a.plan('w',self.tid,5,6);self.assertEqual([c['lines'] for c in p if c['unit']=='B1-1'],[[0],[1]])
 def test_preview_does_not_change_persisted_data(self):
  before=copy.deepcopy(self.s.data);raw=self.s.path.read_bytes();self.a.structure_preview('w',self.tid);self.assertEqual(self.s.data,before);self.assertEqual(self.s.path.read_bytes(),raw)
 def test_precedence_chunk_block_level_track(self):
  t=self.track();self.s.save('voices',{'id':'other','name':'Other'});self.s.import_payload({'levels':{'x':{'voice_id':'other','caption':'Neutral'}}},work_id='w',track_id=self.tid,track_mode='update');Dialogue(self.s).unit_save('w',self.tid,'B1-1',{'level':'x'});self.assertEqual(self.rows()[0]['context']['voice_source'],'レベル対応');self.a.edit('w',self.tid,'block',{'block_id':'B1','voice_id':'v'});self.assertEqual(self.rows()[0]['context']['voice_source'],'Block指定');self.a.edit('w',self.tid,'chunk',{'chunk_id':self.rows()[0]['id'],'voice_id':'other'});self.assertEqual(self.rows()[0]['context']['voice_source'],'チャンク指定')
 def test_success_keeps_only_one_audio_and_regen_preserves_id_number(self):
  self.generate();rows=self.rows();old=rows[0]['media_id'];oldpath=self.s.media_path(self.s.data['media'][old]);cid=rows[0]['id'];self.generate('selected',[cid]);self.assertFalse(oldpath.exists());self.assertEqual(self.rows()[0]['id'],cid);self.assertEqual(self.rows()[0]['sequence'],1);self.assertEqual(len(self.s.data['media']),3)
 def test_failure_keeps_previous_audio_and_error_on_chunk(self):
  self.generate();old=self.rows()[0]['media_id'];p=self.s.media_path(self.s.data['media'][old]);FakeWorker.fail=True;self.generate('selected',[self.rows()[0]['id']]);self.assertTrue(p.exists());self.assertEqual(self.rows()[0]['media_id'],old);self.assertEqual(self.rows()[0]['state'],'生成失敗')
 def test_cancel_discards_new_outputs_and_keeps_old(self):
  self.generate();old=[c['media_id'] for c in self.rows()];FakeWorker.cancel_after=1;r=self.generate();self.assertTrue(r['cancelled']);self.assertEqual([c['media_id'] for c in self.rows()],old);self.assertEqual(len(self.s.data['media']),3);self.assertFalse(list((self.s.work/'runtime/jobs').rglob('*.wav')))
 def test_text_change_invalidates_only_own_chunk_and_gain_does_not(self):
  self.generate();Dialogue(self.s).unit_save('w',self.tid,'B1-1',{'lines':['Changed','Neutral two']});self.assertEqual([c['state'] for c in self.rows()],['変更あり','音声あり','音声あり']);self.a.edit('w',self.tid,'track',{'gain':.5});self.a.edit('w',self.tid,'gap-save',{'after':self.rows()[0]['id'],'seconds':.25});self.assertEqual([c['state'] for c in self.rows()],['変更あり','音声あり','音声あり'])
 def test_voice_change_invalidates_affected_not_all(self):
  self.generate();self.s.save('voices',{'id':'other','name':'Other'});self.a.edit('w',self.tid,'block',{'block_id':'B1','voice_id':'other'});self.assertEqual([c['state'] for c in self.rows()],['変更あり','変更あり','音声あり'])
 def test_wav_has_exact_requested_silence_and_gain(self):
  self.generate();self.a.edit('w',self.tid,'track',{'gain':.5});self.a.edit('w',self.tid,'gap-save',{'after':self.rows()[0]['id'],'seconds':.25});r=export_wav(self.s,'w',self.tid);p=self.s.media_path(self.s.data['media'][r['media_id']]);self.assertAlmostEqual(wav_info(p)['seconds'],.59,places=5)
  with wave.open(str(p),'rb') as f:
   samples=array.array('h');samples.frombytes(f.readframes(f.getnframes()));self.assertEqual(samples[0],1000);self.assertTrue(all(x==0 for x in samples[800:2960]));self.assertEqual(samples[2960],1000)
 def test_export_before_ready_rejected(self):
  with self.assertRaises(Problem):export_wav(self.s,'w',self.tid)
 def test_join_split_move_and_numbers(self):
  cid=self.rows()[0]['id'];self.a.edit('w',self.tid,'join',{'chunk_id':cid});self.assertEqual(len(self.rows()),2);self.a.edit('w',self.tid,'split',{'chunk_id':cid,'at':1});self.a.edit('w',self.tid,'move',{'chunk_id':cid,'direction':1});self.assertEqual([c['sequence'] for c in self.rows()],[1,2,3]);self.assertEqual(self.rows()[1]['id'],cid)
 def test_import_clears_matching_audio_after_confirmation_only(self):
  self.generate();r=self.s.import_payload({'lines':[{'unit':'B1-1','lines':['Replacement']}]},work_id='w',track_id=self.tid,track_mode='update');self.assertTrue(r['confirmation_required']);self.assertEqual(r['delete_counts']['audio_files'],2);self.assertEqual(len(self.rows()),3);self.s.import_payload({'lines':[{'unit':'B1-1','lines':['Replacement']}]},work_id='w',track_id=self.tid,track_mode='update',confirmation=r['confirmation']);self.assertEqual(len(self.rows()),1);self.assertEqual(self.rows()[0]['unit'],'B2-1');self.assertEqual(len(self.s.data['media']),1)
 def test_orphans_only_generated_unreferenced_not_ref(self):
  self.generate();cid=self.rows()[0]['id'];mid=self.rows()[0]['media_id'];self.a.edit('w',self.tid,'delete',{'chunk_id':cid});orphans=self.a.orphan_list();self.assertEqual([o['id'] for o in orphans],[mid]);self.s.save('voices',{'id':'ref','name':'Neutral ref','references':[{'id':'r','media_id':mid}]});self.assertFalse(self.a.orphan_list())
 def test_stale_preview_cannot_start(self):
  with patch('audio_jobs.config_problems',return_value=[]):
   p=self.jobs.preview('w',self.tid);self.a.edit('w',self.tid,'track',{'gain':.9})
   with self.assertRaises(Problem):self.jobs.start('w',self.tid,'missing',[],p['token'])
 def test_missing_voice_reported_and_flagged(self):
  self.generate();r=self.s.import_payload({'lines':[{'unit':'B2-1','lines':['Neutral'],'voice':'missing'}]},work_id='w',track_id=self.tid,track_mode='update');self.assertTrue(r['confirmation_required']);r=self.s.import_payload({'lines':[{'unit':'B2-1','lines':['Neutral'],'voice':'missing'}]},work_id='w',track_id=self.tid,track_mode='update',confirmation=r['confirmation']);self.assertTrue(r['report']['warnings']);self.assertTrue(self.track()['units'][1]['needs_check'])
 def test_full_readback_persistence(self):
  self.generate();self.assertEqual(Store(self.base).data,self.s.data)

 def test_zero_frame_wav_rejected(self):
  p=self.s.work/'empty.wav';make_wav(p,frames=0)
  with self.assertRaises(Problem):wav_info(p)
 def test_unknown_legacy_audio_retained_on_first_edit(self):
  self.track()['audio']={'future':'preserved'};self.a.edit('w',self.tid,'track',{'gain':.8});self.assertEqual(self.track()['extensions']['legacy_audio_input'],{'future':'preserved'})
 def test_timeout_change_does_not_invalidate_audio(self):
  self.generate();self.s.config['tts']['timeout_seconds']=900;self.assertTrue(all(c['state']=='音声あり' for c in self.rows()))
 def test_block_delete_clears_audio_export_but_keeps_other_block(self):
  self.generate();r=export_wav(self.s,'w',self.tid);p=self.s.media_path(self.s.data['media'][r['media_id']]);from tracks import Tracks
  m=Tracks(self.s);preview=m.block_preview('w',self.tid,'B1');m.block_delete('w',self.tid,'B1',preview['signature'],True);self.assertFalse(p.exists());self.assertEqual(len(self.rows()),1)
 def test_work_delete_removes_own_export_and_chunks(self):
  self.generate();r=export_wav(self.s,'w',self.tid);paths=[self.s.media_path(m) for m in self.s.data['media'].values()];p=self.s.deletion_preview('works','w');self.s.delete('works','w',p['signature'],True);self.assertTrue(all(not p.exists() for p in paths));self.assertTrue(self.s.data['voices'])

 def test_common_gap_saved_without_regeneration_and_zero_disables(self):
  self.generate();old=[c['media_id'] for c in self.rows()];self.a.edit('w',self.tid,'track',{'chunk_gap_ms':125});self.assertEqual(Store(self.base).data['works'][0]['tracks'][0]['audio']['chunk_gap_ms'],125);self.assertEqual([c['media_id'] for c in self.rows()],old);self.assertTrue(all(c['state']=='音声あり' for c in self.rows()))
  result=export_wav(self.s,'w',self.tid);path=self.s.media_path(self.s.data['media'][result['media_id']]);self.assertAlmostEqual(wav_info(path)['seconds'],.55)
  with wave.open(str(path),'rb') as f:
   samples=array.array('h');samples.frombytes(f.readframes(f.getnframes()));self.assertEqual(samples[0],2000);self.assertTrue(all(x==0 for x in samples[800:1800]));self.assertEqual(samples[1800],2000);self.assertTrue(all(x==0 for x in samples[2600:3600]));self.assertEqual(samples[-1],2000)
  self.a.edit('w',self.tid,'track',{'chunk_gap_ms':0});result=export_wav(self.s,'w',self.tid);self.assertAlmostEqual(result['seconds'],.3)
 def test_common_gap_rejects_invalid_values_atomically(self):
  for value in [-1,True,'20',None,float('nan'),float('inf')]:
   before=self.s.path.read_bytes()
   with self.assertRaises(Problem):self.a.edit('w',self.tid,'track',{'chunk_gap_ms':value})
   self.assertEqual(before,self.s.path.read_bytes())

 def test_block_end_silence_persists_and_exports_without_regeneration(self):
  self.generate();old=[c['media_id'] for c in self.rows()]
  self.a.edit('w',self.tid,'track',{'chunk_gap_ms':0})
  self.a.edit('w',self.tid,'block',{'block_id':'B1','end_gap_ms':250})
  self.a.edit('w',self.tid,'block',{'block_id':'B2','end_gap_ms':100})
  fresh=Store(self.base).data['works'][0]['tracks'][0]
  self.assertEqual([b.get('end_gap_ms') for b in fresh['blocks']],[250,100])
  self.assertEqual([c['media_id'] for c in self.rows()],old)
  self.assertTrue(all(c['state']=='音声あり' for c in self.rows()))
  result=export_wav(self.s,'w',self.tid)
  self.assertAlmostEqual(result['seconds'],.65)
  with wave.open(str(self.s.media_path(self.s.data['media'][result['media_id']])),'rb') as f:
   samples=array.array('h');samples.frombytes(f.readframes(f.getnframes()))
  self.assertTrue(all(x==2000 for x in samples[:1600]))
  self.assertTrue(all(x==0 for x in samples[1600:3600]))
  self.assertTrue(all(x==2000 for x in samples[3600:4400]))
  self.assertTrue(all(x==0 for x in samples[4400:]))
  self.a.edit('w',self.tid,'block',{'block_id':'B1','end_gap_ms':0})
  self.assertAlmostEqual(export_wav(self.s,'w',self.tid)['seconds'],.4)
 def test_block_end_silence_adds_to_common_and_manual_gaps(self):
  self.generate();self.a.edit('w',self.tid,'track',{'chunk_gap_ms':20})
  self.a.edit('w',self.tid,'block',{'block_id':'B1','end_gap_ms':250})
  self.a.edit('w',self.tid,'gap-save',{'after':self.rows()[1]['id'],'seconds':.1})
  self.assertAlmostEqual(export_wav(self.s,'w',self.tid)['seconds'],.69)
 def test_block_end_gap_rejects_invalid_values_without_writing(self):
  for value in [-1,True,None,'20',float('nan'),float('inf')]:
   before=self.s.path.read_bytes()
   with self.assertRaises(Problem):self.a.edit('w',self.tid,'block',{'block_id':'B1','end_gap_ms':value})
   self.assertEqual(before,self.s.path.read_bytes())
