"""Tsumugoe v0.1: independent assets, work-owned roles and readings.
All persistence and imported extensions are lossless JSON; only work/ is writable.
"""
from __future__ import annotations
import copy, datetime, hashlib, io, json, os, threading, uuid, wave
from pathlib import Path

VERSION = '0.5.0'
KINDS = ('actors', 'voices', 'works')
CHAR_FIELDS = ('occupation','personality','background','speech_base','language_reference','voice_range','appearance_cg')
SCHEMA = {
 'actors': {'name':'string','image_id':'string|null','trigger_word':'string','appearance_notes':'string','voice_ids':'array<string>','standard_voice_id':'string|null'},
 'voices': {'name':'string','notes':'string','references':'array<object>','confirmed_reference_id':'string|null'},
 'works': {'title':'string','settings':'object','characters':'array<character>','readings':'array<reading>','relationships':'array<object>'},
 'character': {'actor_id':'string|null','names':'object','default_voice_id':'string|null',**{k:'string' for k in CHAR_FIELDS}},
 'reading': {'text':'string','reading':'string'},
}
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def ident(): return uuid.uuid4().hex
def merge(old, new):
 if isinstance(old,dict) and isinstance(new,dict):
  out=copy.deepcopy(old)
  for key,value in new.items():out[key]=merge(out[key],value) if key in out else copy.deepcopy(value)
  return out
 return copy.deepcopy(new)
class Problem(Exception):
 def __init__(self,message,details=None,status=400):super().__init__(message);self.details=details or [];self.status=status

def object_value(value,path):
 if not isinstance(value,dict):raise Problem(path+' はJSONオブジェクトにしてください。')
 return copy.deepcopy(value)
def string(value,path,empty=True):
 if not isinstance(value,str) or (not empty and not value.strip()):raise Problem(path+' は'+('空でない' if not empty else '')+'文字列にしてください。')
 return value
def array(value,path):
 if not isinstance(value,list):raise Problem(path+' は配列にしてください。')
 return value
def validate_fields(record, kind):
 for key,form in SCHEMA[kind].items():
  if key not in record:continue
  value=record[key]
  if form=='string':string(value,key)
  elif form=='string|null':
   if value is not None:string(value,key,False)
  elif form=='object':object_value(value,key)
  elif form.startswith('array'):
   array(value,key)
   if form=='array<object>' and any(not isinstance(x,dict) for x in value):raise Problem(key+' の各項目はJSONオブジェクトにしてください。')
   if form=='array<string>' and any(not isinstance(x,str) or not x for x in value):raise Problem(key+' の各項目は空でないID文字列にしてください。')

def fresh(kind, key=None):
 common=dict(id=key or ident(),created_at=now(),updated_at=now())
 if kind=='actors':return dict(common,name='',image_id=None,trigger_word='',appearance_notes='',voice_ids=[],standard_voice_id=None)
 if kind=='voices':return dict(common,name='',notes='',references=[],confirmed_reference_id=None)
 if kind=='works':return dict(common,title='',settings={},characters=[],readings=[],relationships=[],tracks=[],track_summaries=[])
 if kind=='character':return dict(common,actor_id=None,names=dict(full='',family='',given='',aliases=[]),default_voice_id=None,**{k:'' for k in CHAR_FIELDS})
 raise Problem('保存先の種類を確認してください。')

class Store:
 def __init__(self,base):
  self.base=Path(base).resolve();self.work=self.base/'work';self.work.mkdir(parents=True,exist_ok=True);self.lock=threading.RLock()
  self.path=self.work/'library.json'
  if self.path.exists():
   try:self.data=json.loads(self.path.read_text(encoding='utf-8'))
   except (ValueError,OSError) as e:raise Problem('保存データを読めません。work/history のバックアップを保全してください。',[str(e)])
  else:
   self.data=dict(version=VERSION,revision=0,actors=[],voices=[],works=[],media={},extensions={},events=[]);self._atomic(self.path,self.data)
  self.config_path=self.work/'config.json'
  if not self.config_path.exists():self._atomic(self.config_path,json.loads((self.base/'config.default.json').read_text(encoding='utf-8')))
  self.config=json.loads(self.config_path.read_text(encoding='utf-8'))
  from cg_records import migrate
  migrated=copy.deepcopy(self.data)
  if migrate(migrated):self.commit(migrated,dict(action='migrate_track_cgs'))
 def _atomic(self,path,value):
  path=Path(path);assert path.resolve().is_relative_to(self.work.resolve())
  path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.tmp')
  with temp.open('w',encoding='utf-8',newline='\n') as f:json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
  os.replace(temp,path)
 def check_revision(self,revision):
  if revision is not None and revision!=self.data['revision']:raise Problem('別の操作で保存内容が更新されました。入力は残っています。最新の内容を取得してから保存し直してください。',status=409)
 def find(self,data,kind,key):
  found=next((r for r in data[kind] if r['id']==key),None)
  if found is None:raise Problem('対象が見つかりません。一覧から選び直してください。',status=404)
  return found
 def snapshot(self):
  with self.lock:
   data=copy.deepcopy(self.data)
   data['_view']=dict(actors={a['id']:self.actor_status(a,data) for a in data['actors']},voices={v['id']:self.voice_status(v,data) for v in data['voices']},characters={w['id']+':'+c['id']:self.character_status(c,data,w) for w in data['works'] for c in w['characters']})
   data['_view']['media']={key:self.has_media(data,key) for key in data['media']}
   data['_view']['voice_confirmed']={v['id']:self.voice_ready(v,data) for v in data['voices']}
   from tracks import summary
   data['_view']['tracks']={w['id']:{t['id']:summary(t,data,self) for t in w.get('tracks',[])} for w in data['works']}
   from dialogue import preview,update_flags
   update_flags(data,self.data)
   data['_view']['dialogue']={w['id']:{t['id']:{u['id']:preview(t,u,w) for u in t.get('units',[])} for t in w.get('tracks',[])} for w in data['works']}
   from audio import view,config_problems
   data['_view']['audio_config']=config_problems(self)
   data['_view']['audio']={w['id']:{t['id']:view(t,w,data,self) for t in w.get('tracks',[])} for w in data['works']}
   from cg import describe
   data['_view']['cg']={w['id']:{t['id']:{c['id']:describe(self,data,w['id'],t['id'],c['id']) for c in t.get('cgs',[])} for t in w.get('tracks',[])} for w in data['works']}
   return data
 def has_media(self,data,key):
  if key not in data['media']:return False
  try:return self.media_path(data['media'][key]).is_file()
  except (Problem,OSError):return False
 def actor_status(self,actor,data):
  issues=[]
  if not actor.get('trigger_word'):issues.append('LoRAトリガーワード未登録')
  if not self.has_media(data,actor.get('image_id')):issues.append('画像未登録')
  if not actor.get('voice_ids'):issues.append('関連ボイス未登録')
  ids={v['id'] for v in data['voices']}
  if any(x not in ids for x in actor['voice_ids']):issues.append('参照先のボイスが見つかりません')
  linked=[v for v in data['voices'] if v['id'] in actor['voice_ids']]
  if any(not self.voice_ready(v,data) for v in linked):issues.append('関連ボイスが未確定またはRef音声不足')
  if actor['voice_ids'] and not actor.get('standard_voice_id'):issues.append('標準ボイス未指定')
  return issues
 def voice_ready(self,voice,data):
  ref=next((r for r in voice['references'] if r['id']==voice.get('confirmed_reference_id')),None)
  return bool(ref and self.has_media(data,ref.get('media_id')))
 def voice_status(self,voice,data):
  issues=[];refs=voice['references'];confirmed=next((r for r in refs if r['id']==voice['confirmed_reference_id']),None)
  if not refs:issues.append('Ref音声未登録')
  if not self.voice_ready(voice,data):issues.append('ボイス未確定')
  if any(not self.has_media(data,r.get('media_id')) for r in refs):issues.append('音声ファイル未登録')
  return issues
 def character_status(self,char,data,work=None):
  issues=[]
  if not any(a['id']==char['actor_id'] for a in data['actors']):issues.append('元アクター未選択または削除済み')
  voice=next((v for v in data['voices'] if v['id']==char['default_voice_id']),None)
  if not voice:issues.append('既定ボイス未選択または削除済み')
  elif not self.voice_ready(voice,data):issues.append('既定ボイス未確定またはRef音声不足')
  if not char['names'].get('full'):issues.append('名前未入力')
  work=work or next((w for w in data['works'] if char in w['characters']),None)
  if work:
   texts=list(dict.fromkeys([char['names'].get(k,'') for k in ('full','family','given')]+char['names'].get('aliases',[])))
   missing=[text for text in texts if text and not any(r['text']==text and r['reading'] for r in work['readings'])]
   if missing:issues.append('読み未入力：'+'、'.join(missing))
  return issues
 def commit(self,data,event,delete_media=()):
  from dialogue import update_flags
  update_flags(data,self.data)
  from audio import sync
  sync(data,self)
  from tracks import Tracks
  for w in data['works']:Tracks(self).summarize(w,data)
  data['version']=VERSION
  data['revision']=self.data['revision']+1
  data['events'].append(dict(time=now(),**event))
  # A metadata snapshot is kept before every mutation; generated files are never swept by directory.
  self._atomic(self.work/'history'/f'metadata-{self.data["revision"]:08d}.json',self.data)
  moved=[]
  try:
   for key in set(delete_media):
    media=data['media'].get(key)
    if not media or self.media_users(data,key):continue
    path=self.media_path(media)
    if path.exists():
     temp=path.with_name(path.name+'.deleting-'+ident());os.replace(path,temp);moved.append((path,temp))
    data['media'].pop(key,None)
   self._atomic(self.path,data);self.data=data
  except Exception:
   for path,temp in reversed(moved):os.replace(temp,path)
   raise
  for _,temp in moved:
   try:temp.unlink()
   except OSError:pass # Metadata is committed; a Windows file lock may delay physical cleanup.
 def media_path(self,media):
  path=(self.work/media['path']).resolve()
  if not path.is_relative_to((self.work/'media').resolve()):raise Problem('管理フォルダ外のファイルは使用できません。')
  return path
 def media_users(self,data,key):
  from audio import audio
  users=[a['id'] for a in data['actors'] if a.get('image_id')==key]+[v['id'] for v in data['voices'] if any(r.get('media_id')==key for r in v['references'])]
  for w in data['works']:
   for t in w.get('tracks',[]):
    if audio(t).get('export_id')==key or any(c.get('media_id')==key for c in audio(t)['chunks']):users.append(t['id'])
    if any(c.get('image_id')==key for c in t.get('cgs',[])):users.append(t['id'])
    for u in t.get('units',[]):
     if key in u.get('audio_ids',[]):users.append(t['id'])
  return users
 def _record(self,data,kind,value):
  value=object_value(value,kind);value=copy.deepcopy(value)
  key=value.get('id')
  if key is not None:string(key,kind+'.id',False)
  old=next((r for r in data[kind] if r['id']==key),None) if key else None
  if kind=='works':
   for field in ('tracks','track_summaries'):
    if field in value:
     value.setdefault('extensions',{})['imported_'+field]=value.pop(field)
  result=merge(old or fresh(kind,key),value);result['updated_at']=now();validate_fields(result,kind)
  if kind=='works' and not result['title'].strip():result['title']='無題の作品'
  string(result.get('name') if kind!='works' else result.get('title'),kind+('.name' if kind!='works' else '.title'),False)
  if kind=='actors':
   if result['standard_voice_id'] and result['standard_voice_id'] not in result['voice_ids']:raise Problem('アクターの標準ボイスは、関連ボイスの中から選んでください。')
  if kind=='voices':
   seen=set()
   for ref in result['references']:
    object_value(ref,'references');string(ref.get('id'),'references.id',False)
    if ref['id'] in seen:raise Problem('Ref音声のIDが重複しています。')
    seen.add(ref['id'])
    for field in ('name','notes','source_text','created_at'):
     if field in ref:string(ref[field],'references.'+field)
    if ref.get('media_id') is not None:string(ref['media_id'],'references.media_id',False)
   if result['confirmed_reference_id'] and result['confirmed_reference_id'] not in seen:raise Problem('確定するRef音声を候補の中から選んでください。')
  if old:data[kind][data[kind].index(old)]=result
  else:data[kind].append(result)
  return result,old
 def _reading(self,work,value,source=None,manual=False,edit_id=None):
  row=object_value(value,'readings');validate_fields(row,'reading');text=string(row.get('text'),'readings.text',False);reading=string(row.get('reading',''),'readings.reading')
  existing=next((r for r in work['readings'] if r['text']==text),None)
  if existing:
   if existing['reading'] and reading and existing['reading']!=reading and existing['id']!=edit_id:raise Problem('読み指定が競合しています。既存の読みを確認し、作品の辞書で編集してください。',[text+'：既存「'+existing['reading']+'」／入力「'+reading+'」'])
   if reading or edit_id:existing['reading']=reading
   row={**existing,**{k:v for k,v in row.items() if k not in ('id','text','reading','sources','manual')}}
   row['sources']=copy.deepcopy(existing.get('sources',[]));row['manual']=existing.get('manual',False) or manual
   work['readings'][work['readings'].index(existing)]=row
  else:
   row=merge(row,dict(id=ident(),text=text,reading=reading,sources=[],manual=manual));work['readings'].append(row)
  if source and source not in row['sources']:row['sources'].append(source)
  return row
 def _character(self,data,work,value):
  value=object_value(value,'character');seeds=value.pop('readings',[]);array(seeds,'character.readings')
  key=value.get('id')
  if key is not None:string(key,'character.id',False)
  old=next((c for c in work['characters'] if c['id']==key),None) if key else None
  result=merge(old or fresh('character',key),value);result['updated_at']=now();validate_fields(result,'character')
  names=result['names']
  for part in ('full','family','given'):string(names.get(part,''),'names.'+part)
  if any(not isinstance(x,str) for x in array(names.get('aliases',[]),'names.aliases')):raise Problem('別名・呼び名は文字列の配列にしてください。')
  seedmap={};seed_records={}
  for seed in seeds:
   seed=object_value(seed,'character.readings');validate_fields(seed,'reading');text=string(seed.get('text'),'readings.text',False);reading=string(seed.get('reading',''),'readings.reading')
   if text in seedmap and seedmap[text] and reading and seedmap[text]!=reading:raise Problem('入力内で同じ表記に異なる読みがあります。',[text])
   seed_records[text]=merge(seed_records.get(text,{}),seed)
   if reading or text not in seedmap:seedmap[text]=reading
  if old:
   for row in work['readings']:row['sources']=[s for s in row.get('sources',[]) if s.get('character_id')!=old['id']]
  # Keep old values available while reattaching unchanged name forms.
  texts=list(dict.fromkeys([names.get(k,'') for k in ('full','family','given')]+names.get('aliases',[])))
  for text in texts:
   if text:self._reading(work,merge(seed_records.get(text,{}),dict(text=text,reading=seedmap.get(text,''))),dict(character_id=result['id'],kind='name'))
  for text,reading in seedmap.items():
   if text not in texts:self._reading(work,merge(seed_records.get(text,{}),dict(text=text,reading=reading)),dict(character_id=result['id'],kind='import'))
  work['readings']=[r for r in work['readings'] if r.get('manual') or r.get('sources')]
  if old:work['characters'][work['characters'].index(old)]=result
  else:work['characters'].append(result)
  return result,old
 def save(self,kind,value,revision=None,work_id=None,confirmed_names=False,preview=False):
  with self.lock:
   self.check_revision(revision);data=copy.deepcopy(self.data)
   if kind=='character':
    work=self.find(data,'works',work_id);before=copy.deepcopy(work['readings']);result,old=self._character(data,work,value)
    changes=dict(added=[r['text'] for r in work['readings'] if not any(x['text']==r['text'] for x in before)],removed=[r['text'] for r in before if not any(x['text']==r['text'] for x in work['readings'])])
    names_changed=bool(old and old['names']!=result['names'])
    if preview:return dict(record=result,reading_changes=changes,names_changed=names_changed,revision=self.data['revision'])
    if names_changed and not confirmed_names:raise Problem('名前の変更に伴う読み辞書の更新内容を確認してください。',status=409)
   else:
    if kind not in KINDS:raise Problem('保存先を確認してください。')
    if kind=='works' and any(k in value for k in ('characters','readings')):return self.import_payload({'works':[value]},revision)
    result,old=self._record(data,kind,value)
   self.commit(data,dict(action='save',kind=kind,id=result['id'],work_id=work_id))
   return dict(id=result['id'],revision=data['revision'])
 def reading_save(self,work_id,value,revision=None):
  with self.lock:
   self.check_revision(revision);data=copy.deepcopy(self.data);work=self.find(data,'works',work_id)
   key=value.get('id');old=next((r for r in work['readings'] if r['id']==key),None)
   if key and old is None:raise Problem('読み指定が見つかりません。辞書を更新してください。')
   if old and old['text']!=value.get('text'):work['readings'].remove(old)
   row=self._reading(work,value,manual=True,edit_id=key);self.commit(data,dict(action='reading_save',work_id=work_id));return dict(id=row['id'],revision=data['revision'])
 def reading_delete(self,work_id,key,revision=None):
  with self.lock:
   self.check_revision(revision);data=copy.deepcopy(self.data);work=self.find(data,'works',work_id);row=next((r for r in work['readings'] if r['id']==key),None)
   if not row:raise Problem('読み指定が見つかりません。')
   # A name-owned entry stays as an explicit missing-reading row, rather than losing its ownership.
   if row.get('sources'):row['reading']='';row['manual']=False
   else:work['readings'].remove(row)
   self.commit(data,dict(action='reading_delete',work_id=work_id,text=row['text']));return dict(revision=data['revision'])
 def import_payload(self,value,revision=None,work_id=None,track_id=None,track_mode='new',confirmation=None):
  from tracks import Tracks,is_track_payload
  if is_track_payload(value):return Tracks(self).import_payload(value,work_id,track_id,track_mode,revision,confirmation)
  with self.lock:
   self.check_revision(revision);value=object_value(value,'入力全体');data=copy.deepcopy(self.data);report=dict(added=0,updated=0,deleted=0,items=[],warnings=[])
   collections={key:array(value[key],key) for key in KINDS if key in value}
   for kind,rows in collections.items():
    seen=set()
    for row in rows:
     row=object_value(row,kind);key=row.get('id')
     if key and key in seen:raise Problem(kind+' 内でIDが重複しています。',[str(key)])
     if key:seen.add(key)
     chars=row.pop('characters',None) if kind=='works' else None;readings=row.pop('readings',None) if kind=='works' else None
     result,old=self._record(data,kind,row);report['updated' if old else 'added']+=1;report['items'].append(dict(kind=kind,id=result['id'],operation='更新' if old else '追加'))
     if kind=='works':
      if readings is not None:
       for r in array(readings,'works.readings'):self._reading(result,r,manual=True)
      if chars is not None:
       char_ids=set()
       for c in array(chars,'works.characters'):
        if not isinstance(c,dict):raise Problem('配役はオブジェクトの配列にしてください。')
        if c.get('id') and c['id'] in char_ids:raise Problem('作品内で配役IDが重複しています。')
        if c.get('id'):char_ids.add(c['id'])
        r,previous=self._character(data,result,c);report['updated' if previous else 'added']+=1;report['items'].append(dict(kind='character',id=r['id'],work_id=result['id'],operation='更新' if previous else '追加'))
   if 'characters' in value:
    target=value.get('work_id',work_id)
    if not target:raise Problem('配役の取り込み先作品を選んでください。')
    work=self.find(data,'works',target);seen=set()
    for c in array(value['characters'],'characters'):
     if isinstance(c,dict) and c.get('id') in seen:raise Problem('配役IDが重複しています。')
     if isinstance(c,dict) and c.get('id'):seen.add(c['id'])
     r,old=self._character(data,work,c);report['updated' if old else 'added']+=1;report['items'].append(dict(kind='character',id=r['id'],work_id=work['id'],operation='更新' if old else '追加'))
   if 'readings' in value:
    target=value.get('work_id',work_id)
    if not target:raise Problem('辞書の取り込み先作品を選んでください。')
    work=self.find(data,'works',target)
    for r in array(value['readings'],'readings'):self._reading(work,r,manual=True)
   for key,content in value.items():
    if key not in (*KINDS,'characters','readings','work_id'):data['extensions'][key]=merge(data['extensions'].get(key),content)
   # Check the complete batch before one atomic commit. Names never select an existing record.
   changed_actors={i['id'] for i in report['items'] if i['kind']=='actors'}
   changed_voices={i['id'] for i in report['items'] if i['kind']=='voices'}
   changed_works={i['id'] for i in report['items'] if i['kind']=='works'}
   changed_characters={(i.get('work_id'),i['id']) for i in report['items'] if i['kind']=='character'}
   for a in data['actors']:
    if a['id'] in changed_actors:
     for issue in self.actor_status(a,data):report['warnings'].append(a['name']+'：'+issue)
   for v in data['voices']:
    if v['id'] in changed_voices:
     for issue in self.voice_status(v,data):report['warnings'].append(v['name']+'：'+issue)
   for w in data['works']:
    for c in w['characters']:
     if w['id'] in changed_works or (w['id'],c['id']) in changed_characters:
      for issue in self.character_status(c,data,w):report['warnings'].append((c['names'].get('full') or c['id'])+'：'+issue)
   report['retained_fields']=[key for key in value if key not in (*KINDS,'characters','readings','work_id')]
   self.commit(data,dict(action='import',report=report));return dict(report=report,revision=data['revision'])
 def usage(self,kind,key,data=None):
  data=data or self.data;works=[];actors=[]
  for work in data['works']:
   users=[c for c in work['characters'] if (kind=='actors' and c['actor_id']==key) or (kind=='voices' and c['default_voice_id']==key)]
   if users:works.append(dict(id=work['id'],title=work['title'],track_count=len(work.get('tracks',[])),characters=[c['names'].get('full') or '名前未入力' for c in users]))
  if kind=='voices':actors=[dict(id=a['id'],name=a['name']) for a in data['actors'] if key in a['voice_ids']]
  return dict(works=works,actors=actors)
 def deletion_preview(self,kind,key,work_id=None,reference_id=None):
  if kind not in KINDS:raise Problem('削除対象を確認してください。')
  record=self.find(self.data,kind,key);usage=self.usage(kind,key)
  label=record.get('name',record.get('title',''))
  if kind=='works':usage['works']=[dict(id=key,title=label,track_count=len(record.get('tracks',[])),characters=[c['names'].get('full','') for c in record['characters']])]
  if reference_id:
   ref=next((r for r in record.get('references',[]) if r['id']==reference_id),None)
   if not ref:raise Problem('Ref音声が見つかりません。')
   label=ref.get('name','Ref音声')
  signature=hashlib.sha256(json.dumps([self.data['revision'],kind,key,reference_id],ensure_ascii=False).encode()).hexdigest()
  return dict(kind=kind,id=key,reference_id=reference_id,name=label,usage=usage,signature=signature,revision=self.data['revision'],consequence='配役のキャラクター情報は保持し、参照先が無いことを要確認で表示します。' if kind!='works' else 'この作品の設定・配役・読み辞書を削除します。独立したアクターとボイスは保持します。')
 def delete(self,kind,key,signature,acknowledged=False,reference_id=None):
  with self.lock:
   preview=self.deletion_preview(kind,key,reference_id=reference_id)
   if acknowledged is not True or signature!=preview['signature']:raise Problem('削除対象と影響先を確認し、チェックを付けてから削除してください。',status=409)
   data=copy.deepcopy(self.data);record=self.find(data,kind,key);media=[]
   if reference_id:
    ref=next(r for r in record['references'] if r['id']==reference_id);media.append(ref.get('media_id'));record['references'].remove(ref)
    if record['confirmed_reference_id']==reference_id:record['confirmed_reference_id']=None
   else:
    if kind=='actors':media.append(record.get('image_id'))
    if kind=='voices':media.extend(r.get('media_id') for r in record['references'])
    if kind=='works':
     media.extend(mid for mid,m in data['media'].items() if m.get('kind')=='cg' and m.get('work_id')==key)
     for track in record.get('tracks',[]):
      from audio import audio
      media.extend(c.get('media_id') for c in audio(track)['chunks']);media.append(audio(track).get('export_id'))
      for unit in track.get('units',[]):
       media.extend(unit.get('audio_ids',[]))
       if unit.get('cg'):media.append(unit['cg'].get('image_id'))
    data[kind].remove(record)
   self.commit(data,dict(action='delete',kind=kind,id=key,name=preview['name'],reference_id=reference_id),delete_media=media)
   return dict(deleted=preview['name'],revision=data['revision'])
 def upload(self,kind,key,filename,content,revision=None,replacing=False):
  with self.lock:
   self.check_revision(revision);data=copy.deepcopy(self.data);record=self.find(data,kind,key)
   if kind=='actors':
    if record.get('image_id') and not replacing:raise Problem('画像を差し替えることを確認してください。',status=409)
    if content.startswith(b'\x89PNG\r\n\x1a\n'):ext='png';mime='image/png'
    elif content.startswith(b'\xff\xd8\xff'):ext='jpg';mime='image/jpeg'
    elif content[:4]==b'RIFF' and content[8:12]==b'WEBP':ext='webp';mime='image/webp'
    elif content.startswith((b'GIF87a',b'GIF89a')):ext='gif';mime='image/gif'
    else:raise Problem('画像を読み取れません。PNG・JPEG・WebP・GIFの画像を選んでください。')
    old=record.get('image_id');metadata={}
   elif kind=='voices':
    try:
     with wave.open(io.BytesIO(content),'rb') as audio:
      seconds=audio.getnframes()/audio.getframerate();metadata=dict(seconds=seconds,rate=audio.getframerate(),channels=audio.getnchannels())
      if seconds<=0:raise wave.Error('empty')
    except (wave.Error,EOFError,ZeroDivisionError):raise Problem('参照音声を読めません。PCM形式のWAVを選んでください。')
    ext='wav';mime='audio/wav';old=None
   else:raise Problem('アップロード先を確認してください。')
   mid=ident();path=self.work/'media'/(mid+'.'+ext);path.parent.mkdir(exist_ok=True);path.write_bytes(content)
   data['media'][mid]=dict(id=mid,path=path.relative_to(self.work).as_posix(),filename=Path(filename.replace('\\','/')).name,mime=mime,bytes=len(content),created_at=now(),**metadata)
   if kind=='actors':record['image_id']=mid
   else:record['references'].append(dict(id=ident(),media_id=mid,name=Path(filename).name,created_at=now(),notes='',source_text='',**metadata))
   try:self.commit(data,dict(action='upload',kind=kind,id=key),delete_media=[old] if old else [])
   except Exception:path.unlink(missing_ok=True);raise
   return dict(media_id=mid,revision=data['revision'])
 def remove_image(self,key,confirmed=False,revision=None):
  with self.lock:
   self.check_revision(revision)
   if confirmed is not True:raise Problem('画像の削除を確認してください。')
   data=copy.deepcopy(self.data);actor=self.find(data,'actors',key);old=actor.get('image_id');actor['image_id']=None
   self.commit(data,dict(action='image_delete',id=key),delete_media=[old] if old else []);return dict(revision=data['revision'])
 def update_extensions(self,value,revision=None):
  with self.lock:
   self.check_revision(revision);data=copy.deepcopy(self.data);data['extensions']=object_value(value,'追加情報');self.commit(data,dict(action='extensions_save'));return dict(revision=data['revision'])
