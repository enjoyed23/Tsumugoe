import copy,unittest
import test_tracks as fixtures
from model import Store,Problem
class TrackDeleteTests(unittest.TestCase):
 setUp=fixtures.TrackTests.setUp
 tearDown=fixtures.TrackTests.tearDown
 create=fixtures.TrackTests.create
 payload=fixtures.TrackTests.payload
 track=fixtures.TrackTests.track
 media=fixtures.TrackTests.media
 def test_preview_is_read_only_and_counts_actual_files(self):
  tid=self.create();a=self.media(tid,'B1-1','audio');i=self.media(tid,'B1-1','image');self.s.data['media']['image-B1-1']['kind']='cg';self.s._atomic(self.s.path,self.s.data);before=self.s.path.read_bytes();p=self.m.track_preview('w',tid);self.assertEqual(p['units'],2);self.assertEqual(p['cgs'],2);self.assertEqual(p['audio_files'],1);self.assertEqual(p['image_files'],1);self.assertTrue(a.exists() and i.exists());self.assertEqual(before,self.s.path.read_bytes())
 def test_delete_only_target_and_owned_media_and_restore_state(self):
  tid=self.create();other=self.create();before=copy.deepcopy(self.track(other));a=self.media(tid,'B1-1','audio');i=self.media(tid,'B1-1','image');orphan=self.s.work/'media/orphan.bin';orphan.write_bytes(b'neutral orphan');self.s.data['media']['orphan']={'path':'media/orphan.bin','filename':'orphan.bin','kind':'track_audio','work_id':'w','track_id':tid};p=self.m.track_preview('w',tid);self.m.track_delete('w',tid,p['signature'],True);self.assertEqual(self.s.data['works'][0]['tracks'],[before]);self.assertFalse(a.exists() or i.exists() or orphan.exists());self.assertEqual(Store(self.base).data,self.s.data);self.assertTrue(list((self.s.work/'history').glob('metadata-*.json')))
 def test_shared_refs_other_tracks_and_path_alias_are_preserved(self):
  tid=self.create();other=self.create();a=self.media(tid,'B1-1','audio');i=self.media(tid,'B1-1','image');mid='audio-B1-1';self.s.data['media']['alias']=copy.deepcopy(self.s.data['media'][mid]);self.s.save('voices',{'id':'ref','name':'Neutral reference','references':[{'id':'r','media_id':'alias'}]});self.track(other)['cgs'][0]['image_id']='image-B1-1';p=self.m.track_preview('w',tid);self.assertEqual(p['shared_files'],2);self.m.track_delete('w',tid,p['signature'],True);self.assertTrue(a.exists() and i.exists());self.assertIn('alias',self.s.data['media']);self.assertEqual(len(self.s.data['voices']),1)
 def test_acknowledgement_and_stale_confirmation_change_nothing(self):
  tid=self.create();p=self.m.track_preview('w',tid);before=self.s.path.read_bytes()
  with self.assertRaises(Problem):self.m.track_delete('w',tid,p['signature'],False)
  self.assertEqual(before,self.s.path.read_bytes());self.m.save_meta('w',tid,{'synopsis':'neutral changed'});before=self.s.path.read_bytes()
  with self.assertRaises(Problem):self.m.track_delete('w',tid,p['signature'],True)
  self.assertEqual(before,self.s.path.read_bytes())
 def test_wrong_work_never_deletes_track(self):
  tid=self.create();self.s.save('works',{'id':'other-work','title':'Other'});before=self.s.path.read_bytes()
  with self.assertRaises(Problem):self.m.track_delete('other-work',tid,'bad',True)
  self.assertEqual(before,self.s.path.read_bytes())
