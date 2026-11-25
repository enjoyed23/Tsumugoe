"""v0.2 Track intake. Explicit target selection, atomic mirrors, scoped media deletion."""
import copy,hashlib,json,re
from model import Problem,array,object_value,string,merge,ident,now
WORK_FIELDS={'work','works','actors','voices','characters','readings','setup','premise','personas','personality','speech_base','language_reference','words','voice_range','voice_defaults','default_voice','appearance','character_loras','reference_images','settings'}
TRACK_KEYS={'track','lines','cgs','units','blocks','levels'}
def is_track_payload(value):return isinstance(value,dict) and bool(TRACK_KEYS.intersection(value))
def block_of(unit):return unit.rsplit('-',1)[0] if '-' in unit else unit

def validate_lines(lines,path):
 for i,line in enumerate(array(lines,path)):
  string(line,f'{path}[{i}]');opened=False;length=0
  for ch in line:
   if ch=='[':
    if opened:raise Problem('読み指定の [] を入れ子にできません。',[f'{path}[{i}]'])
    opened=True;length=0
   elif ch==']':
    if not opened or not length:raise Problem('読み指定の [] の対応または空の囲みを直してください。',[f'{path}[{i}]'])
    opened=False
   elif opened:length+=1
  if opened:raise Problem('読み指定の閉じ括弧 ] を補ってください。',[f'{path}[{i}]'])
def summary(track,data,store):
 if 'audio' in track:
  from audio import summary as audio_summary
  w=next((w for w in data['works'] if any(t['id']==track['id'] for t in w.get('tracks',[]))),None)
  if w:
   result=audio_summary(track,w,data,store);result['cg_needs_check']=len(__import__('cg_records').timing_checks(track));return result
 units=track.get('units',[]);ready=changed=checks=0
 for u in units:
  ids=u.get('audio_ids',[]);valid=bool(ids) and all(store.has_media(data,mid) for mid in ids)
  changed+=bool(u.get('audio_changed'));ready+=bool(valid and not u.get('audio_changed'));checks+=bool(u.get('needs_check') or u.get('check_reasons'))
 count=len(units);lines=sum(any(s.strip() for s in u.get('lines',[])) for u in units)
 return dict(cg_needs_check=len(__import__('cg_records').timing_checks(track)),total=count,lines=lines,ready=ready,changed=changed,needs_check=checks,complete=bool(count) and count==lines==ready and checks==0)

class Tracks:
 def __init__(self,store):self.s=store
 def work(self,data,wid):return self.s.find(data,'works',wid)
 def find(self,w,tid):
  result=next((t for t in w.get('tracks',[]) if t['id']==tid),None)
  if not result:raise Problem('取り込み先のTrackが見つかりません。作品画面で選び直してください。',status=404)
  return result
 def summarize(self,w,data):
  w['track_summaries']=[dict(track_id=t['id'],number=t['number'],title=t['title'],synopsis=t.get('synopsis',''),complete=summary(t,data,self.s)['complete']) for t in w.get('tracks',[])]
 def new_unit(self,key,block,order):return dict(id=key,block=block,order=order,lines=[],audio_ids=[],audio_changed=False,needs_check=False,check_reasons=[])
 def normalize(self,value):
  value=object_value(value,'Trackパック');header=object_value(value.get('track',{}),'track')
  for key in ('id','title','synopsis','relation_stage'):
   if key in header:string(header[key],'track.'+key,empty=key not in ('id','title'))
  if 'overrides' in header:object_value(header['overrides'],'track.overrides')
  from dialogue import levels_validate,marks_validate
  if 'levels' in value:levels_validate(value['levels'])
  if 'levels' in header:levels_validate(header['levels'])
  result=dict(header=header,lines=None,cgs=None,units=[],blocks=None)
  if 'blocks' in value:
   result['blocks']=[];seen=set()
   for i,row in enumerate(array(value['blocks'],'blocks')):
    row=object_value(row,f'blocks[{i}]');marks_validate(row);key=string(row.get('id'),f'blocks[{i}].id',False)
    if key in seen:raise Problem('Block IDが入力内で重複しています。',[key])
    seen.add(key)
    if 'title' in row:string(row['title'],'blocks.title')
    result['blocks'].append(row)
  for kind,keyname in (('lines','unit'),('units','id')):
   if kind not in value:continue
   rows=[];seen=set()
   for i,row in enumerate(array(value[kind],kind)):
    row=object_value(row,f'{kind}[{i}]');key=string(row.get(keyname),f'{kind}[{i}].{keyname}',False)
    if key in seen:raise Problem(kind+' の単位IDが重複しています。',[key])
    seen.add(key);marks_validate(row)
    if 'block' in row:string(row['block'],kind+'.block',False)
    if 'order' in row and (not isinstance(row['order'],int) or isinstance(row['order'],bool)):raise Problem(kind+'.order は整数にしてください。',[key])
    if kind=='lines' or kind=='units' and 'lines' in row:validate_lines(row.get('lines'),f'{kind}[{i}] {key}.lines')
    if kind=='cgs':
     from cg import cg_validate
     string(row.get('prompt'),f'cgs[{i}].prompt');cg_validate(row)
    rows.append(row)
   result[kind]=rows
  if 'cgs' in value:
   from cg import cg_validate
   result['cgs']=[];seen=set()
   for i,row in enumerate(array(value['cgs'],'cgs')):
    row=object_value(row,f'cgs[{i}]')
    if 'id' in row:key=string(row['id'],f'cgs[{i}].id',False)
    else:key=string(row.get('unit'),f'cgs[{i}].id / legacy unit',False)
    if key in seen:raise Problem('CG IDが入力内で重複しています。',[key])
    seen.add(key);legacy=row.pop('unit',None);row['id']=key
    # start_unit is explicit; unit is a compatibility spelling of that exact timing.
    # Only block-only records retain the old Block-start behavior.
    if 'start_unit' not in row and legacy is not None:row['start_unit']=string(legacy,f'cgs[{i}].unit',False)
    if 'block' not in row:row['block']=None
    if row['block'] is not None:string(row['block'],f'cgs[{i}].block',False)
    string(row.get('prompt'),f'cgs[{i}].prompt');cg_validate(row);result['cgs'].append(row)
  return result
 def import_payload(self,value,wid,tid=None,mode='new',revision=None,confirmation=None):
  with self.s.lock:
   self.s.check_revision(revision)
   if mode not in ('new','update'):raise Problem('新規Track追加か、既存Track更新かを選んでください。')
   if not wid:raise Problem('取り込み先の作品を選んでください。既存Trackへ自動で振り分けません。')
   normalized=self.normalize(value);data=copy.deepcopy(self.s.data);w=self.work(data,wid);w.setdefault('tracks',[]);self.summarize(w,data)
   if mode=='update':
    if not tid:raise Problem('更新するTrackを明示的に選んでください。')
    t=self.find(w,tid);incoming=normalized['header'].get('id')
    if incoming and incoming not in (t['id'],t.get('source_id')):raise Problem('パックのTrack IDと選択した更新先が違います。新規追加か正しい更新先を選んでください。')
   else:
    number=max([0]+[r['number'] for r in w['tracks']])+1
    t=dict(id=ident(),number=number,title=normalized['header'].get('title','Track '+str(number)),synopsis='',relation_stage='',units=[],blocks=[],cgs=[],extensions={},inherited_work_id=wid,prior_summaries=copy.deepcopy(w['track_summaries']),created_at=now(),updated_at=now());w['tracks'].append(t)
    if normalized['header'].get('id'):t['source_id']=normalized['header']['id']
   from dialogue import effective,levels_validate
   previous_effective={u['id']:effective(t,u,w) for u in t['units']}
   before=copy.deepcopy(t);header=normalized['header']
   for key,item in header.items():
    if key not in ('id','units','blocks','lines','cgs','work_id','number','created_at','prior_summaries','inherited_work_id','imports','audio','cgs'):t[key]=copy.deepcopy(item)
   if 'levels' in value:t['levels']=merge(t.get('levels',{}),value['levels'])
   t.setdefault('levels',{})
   lines=normalized['lines'];cgs=normalized['cgs'];whole=lines is not None and cgs is not None
   lids={r['unit'] for r in lines} if lines is not None else set();cids={r['id'] for r in cgs} if cgs is not None else set();wanted=lids|{r['id'] for r in normalized['units']}
   units={u['id']:u for u in t['units']};added=[];updated=[];deleted=[];cleared_audio=set();cleared_cg=set();removed_ids=[];changes=[]
   def clear_audio(u):
    if isinstance(t.get('audio'),dict) and isinstance(t['audio'].get('chunks'),list):
     if t['audio'].get('export_id'):cleared_audio.add(t['audio'].pop('export_id'))
     removed=[c for c in t['audio']['chunks'] if c['unit']==u['id']];cleared_audio.update(c['media_id'] for c in removed if c.get('media_id'));t['audio']['chunks']=[c for c in t['audio']['chunks'] if c['unit']!=u['id']];t['audio']['gaps']=[g for g in t['audio']['gaps'] if not any(c['id']==g['after'] for c in removed)]
    cleared_audio.update(u.get('audio_ids',[]));u['audio_ids']=[];u['audio_changed']=False
   if whole:
    for key in list(units):
     if key not in wanted:clear_audio(units[key]);removed_ids.append(key);units.pop(key);deleted.append(key)
   def ensure(key,row):
    if key not in units:units[key]=self.new_unit(key,row.get('block',block_of(key)),len(units)+1);added.append(key)
    elif key not in updated and key not in added:updated.append(key)
    return units[key]
   for row in normalized['units']:
    key=row['id']
    if whole and key not in wanted:raise Problem('単位IDを確認してください。',[key])
    u=ensure(key,row)
    for field,item in row.items():
     if field not in ('audio_ids','cg','id','lines'):
      u[field]=merge(u.get(field),item)
    u.setdefault('extensions',{}).update({field:copy.deepcopy(row[field]) for field in ('audio_ids','cg','lines') if field in row})
   if lines is not None:
    for u in list(units.values()):
     if (not lines or whole and u['id'] not in lids):
      if u.get('lines'):changes.append('台詞消去 '+u['id'])
      u['lines']=[];clear_audio(u)
    for index,row in enumerate(lines):
     u=ensure(row['unit'],row);
     if whole and 'order' not in row:u['order']=index+1
     clear_audio(u)
     for key,item in row.items():
      if key not in ('unit','id','audio_ids','cg'):u[key]=copy.deepcopy(item)
     u['lines']=copy.deepcopy(row['lines'])
   if cgs is not None:
    old_cgs={r['id']:r for r in t.get('cgs',[])}
    # Existing synchronization: nonempty kind-only upsert; whole/empty is mirror.
    remove=set(old_cgs)-cids if whole or not cgs else set()
    for key in remove:
     row=old_cgs.pop(key)
     if row.get('image_id'):cleared_cg.add(row['image_id'])
     changes.append('CG消去 '+key)
    for row in cgs:
     old=old_cgs.get(row['id'],{})
     if old.get('image_id'):cleared_cg.add(old['image_id'])
     old_cgs[row['id']]={**copy.deepcopy(row),'image_id':None}
    t['cgs']=list(old_cgs.values())
    from cg_records import validate_timings
   blocks=copy.deepcopy(t['blocks']);bids={b['id'] for b in blocks}
   if normalized['blocks'] is not None:
    for row in normalized['blocks']:
     old=next((b for b in blocks if b['id']==row['id']),None)
     if old:old.update(merge(old,row))
     else:blocks.append(copy.deepcopy(row));bids.add(row['id'])
    order=[r['id'] for r in normalized['blocks']];blocks.sort(key=lambda b:order.index(b['id']) if b['id'] in order else len(order))
   for u in units.values():
    if u['block'] not in bids:blocks.append(dict(id=u['block'],title=''));bids.add(u['block'])
   order={b['id']:i for i,b in enumerate(blocks)};t['blocks']=blocks;t['units']=sorted(units.values(),key=lambda u:(order[u['block']],u['order']))
   from cg_records import validate_timings
   validate_timings(t)
   for u in t['units']:
    if u['id'] in previous_effective and previous_effective[u['id']]!=effective(t,u,w):u['audio_changed']=True
   protected=[key for key in value if key in WORK_FIELDS];extras={key:item for key,item in value.items() if key not in TRACK_KEYS and key not in WORK_FIELDS};t['extensions']=merge(t.get('extensions',{}),extras);t['source_payload']=merge(t.get('source_payload',{}),value);t['updated_at']=now()
   audio_files={mid for mid in cleared_audio if self.s.has_media(data,mid) and not self.s.media_users(data,mid)};cg_files={mid for mid in cleared_cg if self.s.has_media(data,mid) and not self.s.media_users(data,mid)}
   empty_kind=(lines is not None and not lines) or (cgs is not None and not cgs)
   details=dict(units=len(removed_ids),lines=sum(x.startswith('台詞消去 ') for x in changes),cgs=sum(x.startswith('CG消去 ') for x in changes),audio_files=len(audio_files),image_files=len(cg_files),audio_links=len(cleared_audio),image_links=len(cleared_cg))
   signature=hashlib.sha256(json.dumps([self.s.data['revision'],wid,tid if mode=='update' else 'new',mode,value],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
   needs_confirmation=empty_kind or any(details.values())
   if needs_confirmation and confirmation!=signature:return dict(confirmation_required=True,confirmation=signature,delete_counts=details,removed_units=removed_ids,changes=changes,empty_keys=[k for k in ('lines','cgs') if k in value and value[k]==[]],work_id=wid,track_id=tid,mode=mode)
   known_voices={v['id'] for v in data['voices']};voice_warnings=[]
   for label,records in [('Block',normalized['blocks'] or []),('単位',(normalized['lines'] or [])+normalized['units'])]:
    for r in records:
     for k in ('voice','voice_id'):
      if r.get(k) and r[k] not in known_voices:voice_warnings.append('ボイス未登録：'+str(r[k])+'（'+label+' '+r.get('unit',r.get('id',''))+'）')
   for label,r in value.get('levels',normalized['header'].get('levels',{})).items():
    if r.get('voice_id') and r['voice_id'] not in known_voices:voice_warnings.append('ボイス未登録：'+r['voice_id']+'（レベル '+label+'）')
   self.summarize(w,data);report=dict(added=len(added)+sum(r['id'] not in {c['id'] for c in before.get('cgs',[])} for r in cgs or []),updated=len(set(updated))+sum(r['id'] in {c['id'] for c in before.get('cgs',[])} for r in cgs or []),deleted=len(deleted),items=[dict(kind='unit',id=x,operation='追加') for x in added]+[dict(kind='unit',id=x,operation='更新') for x in dict.fromkeys(updated) if x not in added]+[dict(kind='unit',id=x,operation='削除') for x in deleted],warnings=['作品レベルの項目は反映しません：'+key for key in protected]+list(dict.fromkeys(voice_warnings)),retained_fields=list(extras),delete_counts=details)
   report['items'] += [dict(kind='CG',id=r['id'],operation='更新' if any(c['id']==r['id'] for c in before.get('cgs',[])) else '追加') for r in cgs or []]
   archive='imports/'+ident()+'.json';self.s._atomic(self.s.work/archive,value);t.setdefault('imports',[]).append(dict(path=archive,time=now()))
   self.s.commit(data,dict(action='track_import',work_id=wid,track_id=t['id'],report=report),delete_media=cleared_audio|cleared_cg)
   return dict(report=report,work_id=wid,track_id=t['id'],revision=data['revision'])
 def save_meta(self,wid,tid,record,revision=None):
  with self.s.lock:
   self.s.check_revision(revision);record=object_value(record,'track');data=copy.deepcopy(self.s.data);w=self.work(data,wid);t=self.find(w,tid)
   for key,item in record.items():
    if key in ('id','units','blocks','audio_ids','number','source_payload','inherited_work_id','prior_summaries','audio','cgs'):continue
    if key in ('title','synopsis','relation_stage'):string(item,'track.'+key,empty=key!='title')
    t[key]=merge(t.get(key),item)
   t['updated_at']=now();self.summarize(w,data);self.s.commit(data,dict(action='track_save',work_id=wid,track_id=tid));return dict(revision=data['revision'])
 def block_add(self,wid,tid,reference=None,position='after',revision=None):
  with self.s.lock:
   self.s.check_revision(revision);data=copy.deepcopy(self.s.data);w=self.work(data,wid);t=self.find(w,tid);ids={b['id'] for b in t['blocks']}
   if position not in ('before','after'):raise Problem('追加位置を前または後で指定してください。')
   if reference is not None and reference not in ids:raise Problem('挿入先のBlockがありません。')
   n=1
   while 'B'+str(n) in ids:n+=1
   key='B'+str(n);index=next(i for i,b in enumerate(t['blocks']) if b['id']==reference)+(position=='after') if reference else len(t['blocks']);t['blocks'].insert(index,dict(id=key,title=''));self.s.commit(data,dict(action='block_add',work_id=wid,track_id=tid,block_id=key));return dict(block_id=key,revision=data['revision'])
 def block_preview(self,wid,tid,bid):
  w=self.work(self.s.data,wid);t=self.find(w,tid)
  if not any(b['id']==bid for b in t['blocks']):raise Problem('Blockが見つかりません。')
  units=[u for u in t['units'] if u['block']==bid];signature=hashlib.sha256(json.dumps([self.s.data['revision'],wid,tid,bid]).encode()).hexdigest()
  from audio import audio
  ids={u['id'] for u in units};media={mid for u in units for mid in u.get('audio_ids',[])};media.update(c.get('media_id') for c in audio(t)['chunks'] if c['unit'] in ids)
  if units and audio(t).get('export_id'):media.add(audio(t)['export_id'])
  simulated=copy.deepcopy(self.s.data);sw=self.work(simulated,wid);st=self.find(sw,tid);st['units']=[u for u in st['units'] if u['block']!=bid]
  if isinstance(st.get('audio'),dict) and 'chunks' in st['audio']:
   st['audio']['chunks']=[c for c in st['audio']['chunks'] if c['unit'] not in ids]
   if units:st['audio'].pop('export_id',None)
  files=sum(self.s.has_media(simulated,mid) and not self.s.media_users(simulated,mid) for mid in media)
  return dict(work_id=wid,track_id=tid,block_id=bid,unit_count=len(units),audio_files=files,cg_count=0,cg_timing_count=sum(c.get('start_unit') in ids if 'start_unit' in c else c.get('block')==bid for c in t.get('cgs',[])),signature=signature)
 def block_delete(self,wid,tid,bid,signature,acknowledged=False):
  with self.s.lock:
   preview=self.block_preview(wid,tid,bid)
   if acknowledged is not True or signature!=preview['signature']:raise Problem('Blockの内訳を確認し直してください。',status=409)
   data=copy.deepcopy(self.s.data);w=self.work(data,wid);t=self.find(w,tid);removed=[u for u in t['units'] if u['block']==bid];media=set()
   for u in removed:
    media.update(u.get('audio_ids',[]))
    # CG images are not owned by this Block.
   if isinstance(t.get('audio'),dict) and isinstance(t['audio'].get('chunks'),list):
    if removed and t['audio'].get('export_id'):media.add(t['audio'].pop('export_id'))
    ids={u['id'] for u in removed};discard=[c for c in t['audio']['chunks'] if c['unit'] in ids];media.update(c.get('media_id') for c in discard);t['audio']['chunks']=[c for c in t['audio']['chunks'] if c['unit'] not in ids];t['audio']['gaps']=[g for g in t['audio']['gaps'] if not any(c['id']==g['after'] for c in discard)]
   removed_ids={u['id'] for u in removed}
   for cg in t.get('cgs',[]):
    if 'start_unit' in cg:
     if cg['start_unit'] in removed_ids:cg['start_unit']=None
    elif cg.get('block')==bid:cg['block']=None
   t['units']=[u for u in t['units'] if u['block']!=bid];t['blocks']=[b for b in t['blocks'] if b['id']!=bid];self.summarize(w,data);self.s.commit(data,dict(action='block_delete',**preview),delete_media=media);return dict(deleted=bid,unit_count=len(removed),revision=data['revision'])
 def track_preview(self,wid,tid):
  from audio import audio
  with self.s.lock:
   w=self.work(self.s.data,wid);t=self.find(w,tid);a=audio(t)
   candidates={mid for mid,m in self.s.data['media'].items() if m.get('work_id')==wid and m.get('track_id')==tid and m.get('kind') in ('track_audio','track_export','cg')}
   candidates.update(mid for u in t['units'] for mid in u.get('audio_ids',[]));candidates.update(c.get('media_id') for c in a['chunks']);candidates.add(a.get('export_id'));candidates.update(c.get('image_id') for c in t.get('cgs',[]));candidates.discard(None)
   data=copy.deepcopy(self.s.data);dw=self.work(data,wid);dw['tracks']=[x for x in dw['tracks'] if x['id']!=tid]
   protected_paths={self.s.media_path(m) for mid,m in data['media'].items() if self.s.media_users(data,mid)}
   files=[];shared=[]
   for mid in sorted(candidates):
    m=data['media'].get(mid)
    if not m:continue
    if self.s.media_users(data,mid) or self.s.media_path(m) in protected_paths:shared.append(mid)
    else:files.append(mid)
   existing=[mid for mid in files if self.s.has_media(data,mid)]
   return dict(work_id=wid,track_id=tid,title=t['title'],number=t['number'],blocks=len(t['blocks']),units=len(t['units']),chunks=len(a['chunks']),cgs=len(t.get('cgs',[])),audio_files=sum(data['media'][mid].get('kind')!='cg' for mid in existing),image_files=sum(data['media'][mid].get('kind')=='cg' for mid in existing),shared_files=len(shared),delete_media=files,signature=hashlib.sha256(json.dumps([self.s.data['revision'],wid,tid,'track_delete']).encode()).hexdigest())
 def track_delete(self,wid,tid,signature,acknowledged=False):
  with self.s.lock:
   p=self.track_preview(wid,tid)
   if acknowledged is not True or signature!=p['signature']:raise Problem('Trackの削除対象と内訳を確認し直してください。',status=409)
   data=copy.deepcopy(self.s.data);w=self.work(data,wid);w['tracks']=[t for t in w['tracks'] if t['id']!=tid];self.s.commit(data,dict(action='track_delete',work_id=wid,track_id=tid,title=p['title'],counts={k:p[k] for k in ('blocks','units','chunks','cgs','audio_files','image_files','shared_files')}),delete_media=p['delete_media']);return dict(deleted=p['title'],track_id=tid,counts={k:p[k] for k in ('blocks','units','chunks','cgs','audio_files','image_files','shared_files')},revision=data['revision'])
 def move_unit(self,wid,tid,uid,bid,revision=None):
  with self.s.lock:
   self.s.check_revision(revision);data=copy.deepcopy(self.s.data);w=self.work(data,wid);t=self.find(w,tid)
   if not any(b['id']==bid for b in t['blocks']):raise Problem('移動先のBlockを選んでください。')
   u=next((u for u in t['units'] if u['id']==uid),None)
   if not u:raise Problem('移動する単位がありません。')
   u['block']=bid;u['order']=max([0]+[x['order'] for x in t['units'] if x['block']==bid])+1;order={b['id']:i for i,b in enumerate(t['blocks'])};t['units'].sort(key=lambda x:(order[x['block']],x['order']));self.s.commit(data,dict(action='unit_block_move',work_id=wid,track_id=tid,unit_id=uid,block_id=bid));return dict(revision=data['revision'])
