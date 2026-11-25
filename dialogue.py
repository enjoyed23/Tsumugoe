"""Dialogue editing and derived TTS previews. No synthesis or stored speech copy."""
import copy,re
from model import Problem,object_value,string,now
PATTERN=re.compile(r'\[([^\[\]]+)\]')
def dictionary(w):return {r['text']:r.get('reading','') for r in w.get('readings',[])}
def derive(lines,w):
 d=dictionary(w);missing=[];result=[]
 for line in lines:
  def sub(m):
   key=m.group(1)
   if not d.get(key) and key not in missing:missing.append(key)
   return d.get(key) or key
  result.append(PATTERN.sub(sub,line))
 return dict(lines=result,text='\n'.join(result),missing=missing)
def levels_validate(value):
 value=object_value(value,'levels')
 for key,row in value.items():
  string(key,'level key',False);object_value(row,'levels.'+key)
  if 'caption' in row:string(row['caption'],'levels.'+key+'.caption')
  if row.get('voice_id') is not None:string(row['voice_id'],'levels.'+key+'.voice_id',False)
 return value
def marks_validate(row):
 for key in ('level','speaker','voice','voice_id'):
  if row.get(key) is not None:string(row[key],key,False)
def effective(t,u,w):
 b=next((b for b in t.get('blocks',[]) if b['id']==u['block']),{});level=u.get('level') or b.get('level');entry=t.get('levels',{}).get(level,{})
 speaker=u.get('speaker');role=next((c for c in w['characters'] if c['id']==speaker),None) if speaker else (w['characters'][0] if len(w['characters'])==1 else None)
 return dict(level=level,caption=entry.get('caption',''),voice_id=entry.get('voice_id') or (role or {}).get('default_voice_id'),speaker=speaker,level_missing=bool(level and level not in t.get('levels',{})),speaker_missing=bool(speaker and not role))
def update_flags(data,before):
 oldworks={w['id']:w for w in before.get('works',[])}
 for w in data.get('works',[]):
  old=oldworks.get(w['id'],{});a=dictionary(old);b=dictionary(w);changed={k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)}
  for t in w.get('tracks',[]):
   for u in t.get('units',[]):
    used={m.group(1) for line in u.get('lines',[]) for m in PATTERN.finditer(line)}
    if used&changed:u['audio_changed']=True
    voices={v['id'] for v in data['voices']};block=next((b for b in t['blocks'] if b['id']==u['block']),{});level=t.get('levels',{}).get(u.get('level') or block.get('level'),{});refs=[u.get('voice'),block.get('voice'),block.get('voice_id'),level.get('voice_id')]
    if any(v and v not in voices for v in refs):
     u['needs_check']=True
     if 'ボイス未登録' not in u.setdefault('check_reasons',[]):u['check_reasons'].append('ボイス未登録')
    missing=derive(u.get('lines',[]),w)['missing']
    if missing:
     u['needs_check']=True;reasons=u.setdefault('check_reasons',[])
     if '読み未登録' not in reasons:reasons.append('読み未登録')
def preview(t,u,w):
 result=derive(u.get('lines',[]),w);result.update(effective(t,u,w));result['display_lines']=[PATTERN.sub(lambda m:m.group(1),line) for line in u.get('lines',[])];return result
class Dialogue:
 def __init__(self,store):
  from tracks import Tracks
  self.s=store;self.m=Tracks(store)
 def unit_save(self,wid,tid,uid,record,revision=None):
  from tracks import validate_lines
  with self.s.lock:
   self.s.check_revision(revision);record=object_value(record,'unit');data=copy.deepcopy(self.s.data);w=self.m.work(data,wid);t=self.m.find(w,tid);u=next((u for u in t['units'] if u['id']==uid),None)
   if u is None:raise Problem('単位が見つかりません。Trackを開き直してください。')
   if 'lines' in record:validate_lines(record['lines'],uid+'.lines')
   marks_validate(record);prior=copy.deepcopy(u)
   for k,v in record.items():
    if k not in ('id','block','order','audio_ids','audio_changed','cg','needs_check','check_reasons'):u[k]=copy.deepcopy(v)
   if any(prior.get(k)!=u.get(k) for k in ('lines','level','speaker')):u['audio_changed']=True
   u['updated_at']=now();self.m.summarize(w,data);self.s.commit(data,dict(action='unit_save',work_id=wid,track_id=tid,unit_id=uid));return dict(revision=data['revision'])
 def levels_save(self,wid,tid,levels,revision=None):
  with self.s.lock:
   self.s.check_revision(revision);levels_validate(levels);data=copy.deepcopy(self.s.data);w=self.m.work(data,wid);t=self.m.find(w,tid);before={u['id']:effective(t,u,w) for u in t['units']};t['levels']=copy.deepcopy(levels)
   for u in t['units']:
    if before[u['id']]!=effective(t,u,w):u['audio_changed']=True
   self.s.commit(data,dict(action='levels_save',work_id=wid,track_id=tid));return dict(revision=data['revision'])
 def clear_check(self,wid,tid,uid,revision=None):
  with self.s.lock:
   self.s.check_revision(revision);data=copy.deepcopy(self.s.data);w=self.m.work(data,wid);t=self.m.find(w,tid);u=next((u for u in t['units'] if u['id']==uid),None)
   if not u:raise Problem('単位が見つかりません。')
   if derive(u['lines'],w)['missing']:raise Problem('読み未登録の表記を辞書に登録してから確認済みにしてください。')
   u['needs_check']=False;u['check_reasons']=[];self.s.commit(data,dict(action='unit_check_clear',work_id=wid,track_id=tid,unit_id=uid));return dict(revision=data['revision'])
 def add(self,wid,tid,bid,reference=None,revision=None):
  with self.s.lock:
   self.s.check_revision(revision);data=copy.deepcopy(self.s.data);w=self.m.work(data,wid);t=self.m.find(w,tid)
   if not any(b['id']==bid for b in t['blocks']):raise Problem('追加するBlockを選んでください。')
   ids={u['id'] for u in t['units']};n=1
   while bid+'-'+str(n) in ids:n+=1
   uid=bid+'-'+str(n);unit=self.m.new_unit(uid,bid,0);rows=[u for u in t['units'] if u['block']==bid]
   if reference is not None and not any(u['id']==reference for u in rows):raise Problem('挿入先の単位を選び直してください。')
   index=next(i for i,u in enumerate(rows) if u['id']==reference)+1 if reference else 0;rows.insert(index,unit)
   for i,u in enumerate(rows):u['order']=i+1
   t['units']=[u for b in t['blocks'] for u in (rows if b['id']==bid else [x for x in t['units'] if x['block']==b['id']])];self.m.summarize(w,data);self.s.commit(data,dict(action='unit_add',work_id=wid,track_id=tid,unit_id=uid));return dict(unit_id=uid,revision=data['revision'])
 def move(self,wid,tid,uid,direction,revision=None):
  with self.s.lock:
   self.s.check_revision(revision)
   if direction not in (-1,1):raise Problem('移動方向を上または下で指定してください。')
   data=copy.deepcopy(self.s.data);w=self.m.work(data,wid);t=self.m.find(w,tid);u=next((u for u in t['units'] if u['id']==uid),None)
   if not u:raise Problem('単位が見つかりません。')
   rows=[x for x in t['units'] if x['block']==u['block']];i=rows.index(u);j=i+direction
   if not 0<=j<len(rows):raise Problem('このBlock内ではこれ以上移動できません。')
   rows[i],rows[j]=rows[j],rows[i]
   for i,x in enumerate(rows):x['order']=i+1
   t['units']=[x for b in t['blocks'] for x in (rows if b['id']==u['block'] else [x for x in t['units'] if x['block']==b['id']])];self.s.commit(data,dict(action='unit_move',work_id=wid,track_id=tid,unit_id=uid));return dict(revision=data['revision'])

 def block_save(self,wid,tid,bid,level,revision=None):
  with self.s.lock:
   self.s.check_revision(revision);marks_validate({'level':level});data=copy.deepcopy(self.s.data);w=self.m.work(data,wid);t=self.m.find(w,tid);b=next((b for b in t['blocks'] if b['id']==bid),None)
   if b is None:raise Problem('Blockが見つかりません。')
   before={u['id']:effective(t,u,w) for u in t['units']};b['level']=level
   for u in t['units']:
    if before[u['id']]!=effective(t,u,w):u['audio_changed']=True
   self.s.commit(data,dict(action='block_level_save',work_id=wid,track_id=tid,block_id=bid));return dict(revision=data['revision'])
