"""Track audio structure, effective settings, WAV processing. Standard library only."""
import copy,hashlib,json,math,wave,array,os
from pathlib import Path
from model import Problem,ident,now
from dialogue import derive,effective

def audio(t):
 value=t.get('audio')
 if isinstance(value,dict) and isinstance(value.get('chunks'),list) and isinstance(value.get('gaps'),list):return value
 return dict(chunks=[],gaps=[],gain=1.0,voice_id=None,chunk_gap_ms=20,target_seconds=18.0,chars_per_second=6.0)
def unit(t,uid):return next((u for u in t['units'] if u['id']==uid),None)
def number(value,name,low=0,high=None):
 if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<low or high is not None and value>high:raise Problem(name+'の数値を確認してください。')
 return value
def context(t,c,w,data,store):
 a=audio(t);u=unit(t,c['unit']);b=next((b for b in t['blocks'] if u and b['id']==u['block']),{});e=effective(t,u,w) if u else {};lines=u.get('lines',[]) if u else [];indexes=c['lines'];valid=bool(indexes) and all(isinstance(i,int) and 0<=i<len(lines) for i in indexes)
 source=[lines[i] for i in indexes] if valid else [];derived=derive(source,w);level=c.get('level') or e.get('level');entry=t.get('levels',{}).get(level,{})
 speaker=u.get('speaker') if u else None;role=next((r for r in w['characters'] if r['id']==speaker),None) if speaker else (w['characters'][0] if len(w['characters'])==1 else None)
 vid=None;origin='未割り当て'
 for value,label in ((c.get('voice_id'),'チャンク指定'),(u.get('voice') if u else None,'パック指定'),(b.get('voice_id') if 'voice_id' in b else b.get('voice'),'Block指定'),(entry.get('voice_id'),'レベル対応'),(a.get('voice_id'),'Track指定'),((role or {}).get('default_voice_id'),'配役の既定')):
  if value:vid=value;origin=label;break
 voice=next((v for v in data['voices'] if v['id']==vid),None);ref=next((r for r in (voice or {}).get('references',[]) if r['id']==voice.get('confirmed_reference_id')),None) if voice else None;mid=ref.get('media_id') if ref else None
 problems=[]
 if not valid:problems.append('台詞の行構成が変わっています。分割プレビューから再構成してください。')
 if not derived['text'].strip():problems.append('読み上げる台詞がありません。台詞画面で入力してください。')
 if not voice:problems.append('ボイスを割り当ててください。指定IDが未登録の場合はボイス管理で確認してください。')
 elif voice.get('references') and not ref:problems.append('Ref音声が未確定です。ボイスライブラリで候補を確定してください。')
 if ref and not store.has_media(data,mid):problems.append('確定Ref音声ファイルがありません。ボイス管理で再登録してください。')
 gain=a.get('gain',1.0);gain_source='Track既定'
 for item,label in ((b,'Block上書き'),(c,'チャンク上書き')):
  if item.get('gain') is not None:gain=item['gain'];gain_source=label
 caption=entry.get('caption','');settings=copy.deepcopy(store.config.get('tts',{}));settings.pop('worker',None);settings.pop('python',None);settings.pop('project_dir',None);settings.pop('timeout_seconds',None)
 fp=hashlib.sha256(json.dumps([derived['text'],caption,vid,mid,settings,(voice or {}).get('tts_options',{})],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 return dict(unit=c['unit'],block=u['block'] if u else '',text=derived['text'],source_lines=source,missing=derived['missing'],caption=caption,level=level,voice_id=vid,voice_name=(voice or {}).get('name','未割り当て'),voice_source=origin,ref_id=mid,ref_name=(data['media'].get(mid) or {}).get('filename','なし'),no_ref=not ref,gain=gain,gain_source=gain_source,estimated_seconds=len(derived['text'])/a.get('chars_per_second',6),fingerprint=fp,problems=problems)
def chunk_state(c,ctx,data,store):
 if c.get('error'):return '生成失敗'
 if c.get('media_id') and store.has_media(data,c['media_id']):return '音声あり' if c.get('fingerprint')==ctx['fingerprint'] else '変更あり'
 return '未生成'
def view(t,w,data,store):
 result=[]
 for i,c in enumerate(audio(t)['chunks']):
  ctx=context(t,c,w,data,store);result.append(dict(**copy.deepcopy(c),sequence=i+1,context=ctx,state=chunk_state(c,ctx,data,store)))
 return dict(chunks=result,gaps=copy.deepcopy(audio(t)['gaps']))
def sync(data,store):
 for w in data['works']:
  for t in w.get('tracks',[]):
   if 'audio' not in t:continue
   a=audio(t)
   for u in t['units']:
    chunks=[c for c in a['chunks'] if c['unit']==u['id']];u['audio_ids']=[c['media_id'] for c in chunks if c.get('media_id')]
    if chunks:u['audio_changed']=any(c.get('media_id') and c.get('fingerprint')!=context(t,c,w,data,store)['fingerprint'] for c in chunks)
def summary(t,w,data,store):
 v=view(t,w,data,store);ready=changed=0
 for u in t['units']:
  rows=[c for c in v['chunks'] if c['unit']==u['id']];covered={i for c in rows for i in c['lines']};required={i for i,line in enumerate(u['lines']) if line.strip()};ready+=bool(rows and required<=covered and all(c['state']=='音声あり' for c in rows));changed+=any(c['state']=='変更あり' for c in rows)
 n=len(t['units']);lines=sum(any(l.strip() for l in u['lines']) for u in t['units']);checks=sum(bool(u.get('needs_check') or u.get('check_reasons')) for u in t['units']);return dict(total=n,lines=lines,ready=ready,changed=changed,needs_check=checks,complete=bool(n) and n==lines==ready and not checks)
def config_problems(store):
 t=store.config['tts'];p=[]
 for k in ('python','worker','checkpoint'):
  if not Path(t.get(k,'')).is_file():p.append('TTSの'+k+'が見つかりません。接続設定を修正してください。')
 if not Path(t.get('project_dir','')).is_dir():p.append('IRODORI-TTSのフォルダがありません。接続設定を修正してください。')
 return p

def wav_info(path):
 with wave.open(str(path),'rb') as f:
  if f.getsampwidth()!=2 or f.getcomptype()!='NONE':raise Problem('PCM 16bit WAVが必要です。TTSの保存形式を確認してください。')
  if f.getnframes()<=0 or f.getframerate()<=0:raise Problem('生成WAVに音声がありません。TTSの設定を確認して再生成してください。')
  return dict(seconds=f.getnframes()/f.getframerate(),rate=f.getframerate(),channels=f.getnchannels(),frames=f.getnframes())
def peaks(path,bins=64):
 with wave.open(str(path),'rb') as f:
  n=f.getnframes();step=max(1,math.ceil(n/bins));result=[]
  while True:
   raw=f.readframes(step)
   if not raw:break
   samples=array.array('h');samples.frombytes(raw);result.append(round(max((abs(x) for x in samples),default=0)/32768,4))
 return result
class Audio:
 def __init__(self,s):
  from tracks import Tracks
  self.s=s;self.m=Tracks(s)
 def locate(self,data,wid,tid):
  w=self.m.work(data,wid);return w,self.m.find(w,tid)
 def plan(self,wid,tid,target=18,cps=6):
  number(target,'目標秒数',.1);number(cps,'1秒あたりの文字数',.1);w,t=self.locate(self.s.data,wid,tid);out=[];old=audio(t)['chunks']
  for u in t['units']:
   group=[];chars=0
   def push():
    if group:
     match=next((c for c in old if c['unit']==u['id'] and c['lines']==group),None);out.append(copy.deepcopy(match) if match else dict(id=ident(),unit=u['id'],lines=group[:],media_id=None,voice_id=None,gain=None));group.clear()
   for i,line in enumerate(u['lines']):
    if not line.strip():push();chars=0;continue
    length=len(derive([line],w)['text'])
    if group and (chars+length)/cps>target:push();chars=0
    group.append(i);chars+=length
   push()
  return out
 def structure_preview(self,wid,tid,target=18,cps=6):
  with self.s.lock:
   rows=self.plan(wid,tid,target,cps);w,t=self.locate(self.s.data,wid,tid);removed_gaps=sum(g['after'] is not None and not any(c['id']==g['after'] for c in rows) for g in audio(t)['gaps']);return dict(removed_gaps=removed_gaps,revision=self.s.data['revision'],chunks=rows,count=len(rows),target_seconds=target,chars_per_second=cps)
 def edit(self,wid,tid,operation,body,revision=None):
  with self.s.lock:
   self.s.check_revision(revision);data=copy.deepcopy(self.s.data);w,t=self.locate(data,wid,tid);a=audio(t)
   if a is not t.get('audio'):
    if 'audio' in t:t.setdefault('extensions',{})['legacy_audio_input']=t['audio']
    t['audio']=a
   rows=a['chunks'];c=next((x for x in rows if x['id']==body.get('chunk_id')),None)
   if operation=='rebuild':a['chunks']=self.plan(wid,tid,body.get('target_seconds',18),body.get('chars_per_second',6));a['target_seconds']=body.get('target_seconds',18);a['chars_per_second']=body.get('chars_per_second',6);a['gaps']=[g for g in a['gaps'] if g['after'] is None or any(c['id']==g['after'] for c in a['chunks'])]
   elif operation=='track':
    for k in ('gain','voice_id','chunk_gap_ms'):
     if k in body:
      if k=='gain':number(body[k],'Track音量',0,4)
      elif k=='chunk_gap_ms':number(body[k],'チャンク間の共通の間（ms）',0)
      elif body[k] is not None and not isinstance(body[k],str):raise Problem('ボイスIDは文字列にしてください。')
      a[k]=body[k]
   elif operation=='block':
    b=next((b for b in t['blocks'] if b['id']==body.get('block_id')),None)
    if not b:raise Problem('Blockがありません。')
    for k in ('gain','voice_id'):
     if k in body:
      if k=='gain' and body[k] is not None:number(body[k],'Block音量',0,4)
      if k=='voice_id' and body[k] is not None and not isinstance(body[k],str):raise Problem('ボイスIDは文字列にしてください。')
      b[k]=body[k]
   elif operation in ('gap-save','gap-delete'):
    gap=next((g for g in a['gaps'] if g['id']==body.get('gap_id')),None)
    if operation=='gap-delete':
     if not gap:raise Problem('空白がありません。')
     a['gaps'].remove(gap)
    else:
     number(body.get('seconds'),'空白の秒数',0)
     if not gap:
      after=body.get('after')
      if after is not None and not any(c['id']==after for c in rows):raise Problem('空白を入れる位置を選んでください。')
      gap=dict(id=ident(),after=after);a['gaps'].append(gap)
     gap['seconds']=body['seconds']
   else:
    if not c:raise Problem('チャンクがありません。構成を更新してください。')
    i=rows.index(c)
    if operation=='chunk':
     for k in ('gain','voice_id','level'):
      if k in body:
       if k=='gain' and body[k] is not None:number(body[k],'チャンク音量',0,4)
       if k!='gain' and body[k] is not None and not isinstance(body[k],str):raise Problem(k+'は文字列にしてください。')
       c[k]=body[k]
    elif operation=='split':
     cut=body.get('at')
     if isinstance(cut,bool) or not isinstance(cut,int) or not 0<cut<len(c['lines']):raise Problem('分割する行の境界を選んでください。')
     other=copy.deepcopy(c);other.update(id=ident(),lines=c['lines'][cut:],media_id=None,fingerprint=None);c['lines']=c['lines'][:cut];rows.insert(i+1,other)
    elif operation=='join':
     if i+1>=len(rows) or rows[i+1]['unit']!=c['unit']:raise Problem('同じ単位の次のチャンクが必要です。')
     other=rows.pop(i+1);c['lines']+=other['lines'];a['gaps']=[g for g in a['gaps'] if g['after']!=other['id']]
    elif operation=='move':
     delta=body.get('direction')
     if delta not in (-1,1):raise Problem('移動方向を選んでください。')
     j=i+delta
     if not 0<=j<len(rows):raise Problem('これ以上移動できません。')
     rows[i],rows[j]=rows[j],rows[i]
    elif operation=='delete':rows.remove(c);a['gaps']=[g for g in a['gaps'] if g['after']!=c['id']]
    else:raise Problem('音声操作がありません。')
   self.s.commit(data,dict(action='audio_'+operation,work_id=wid,track_id=tid));return dict(revision=data['revision'])
 def orphan_list(self):
  result=[]
  for mid,m in self.s.data['media'].items():
   if m.get('kind') in ('track_audio','track_export') and not self.s.media_users(self.s.data,mid):
    p=self.s.media_path(m)
    if p.is_file():result.append(dict(id=mid,work_id=m.get('work_id'),track_id=m.get('track_id'),filename=m['filename'],bytes=p.stat().st_size,created_at=m.get('created_at',''),reason='現在のチャンク・登録Ref音声から参照されていません'))
  return result
 def orphan_delete(self,ids,revision=None):
  with self.s.lock:
   self.s.check_revision(revision);allowed={r['id'] for r in self.orphan_list()}
   if not isinstance(ids,list) or not set(ids)<=allowed:raise Problem('削除対象を一覧から選び直してください。')
   names=[self.s.data['media'][i]['filename'] for i in ids];self.s.commit(copy.deepcopy(self.s.data),dict(action='audio_orphan_delete',files=names),delete_media=ids);return dict(deleted=names,revision=self.s.data['revision'])
