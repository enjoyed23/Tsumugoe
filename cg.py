"""CG ownership, exact prompt pass-through and explicit workflow wiring."""
import copy,hashlib,json,math,struct,re
from pathlib import Path
from model import Problem,merge,object_value,string,ident,now
from cg_defaults import defaults,is_standard
from connections import local_endpoint

def config(s):
 cfg=merge(defaults(),s.config.get('comfyui',{}))
 if isinstance(cfg.get('seed'),str) and re.fullmatch(r'-?\d+',cfg['seed']):cfg['seed']=int(cfg['seed'])
 return cfg
def dimension(width,height,cfg):
 for label,n in [('幅',width),('高さ',height)]:
  if isinstance(n,bool) or not isinstance(n,int) or n<256 or n%8:raise Problem(label+'は256px以上、8の倍数の整数にしてください。')
  if n>cfg['max_edge']:raise Problem('解像度が確認済み上限を超えています。上限以下の値を指定してください。')
 if width*height>cfg['max_pixels']:raise Problem('総画素数が確認済み上限を超えています。解像度を下げてください。')
def validate_config(value):
 cfg=merge(defaults(),object_value(value,'comfyui'))
 if isinstance(cfg.get('seed'),str) and re.fullmatch(r'-?\d+',cfg['seed']):cfg['seed']=int(cfg['seed'])
 local_endpoint(cfg['endpoint'])
 for k in ('max_edge','max_pixels'):
  if isinstance(cfg[k],bool) or not isinstance(cfg[k],int) or cfg[k]<=0:raise Problem(k+'は正の整数にしてください。')
 if cfg['max_edge']>2048 or cfg['max_pixels']>2048*2048:raise Problem('上限は長辺2048px・4194304画素以内にしてください。')
 dimension(cfg['width'],cfg['height'],cfg)
 if isinstance(cfg['seed'],bool) or not isinstance(cfg['seed'],int) or not -1<=cfg['seed']<2**63:raise Problem('シードは-1（ランダム）または0以上の整数にしてください。')
 if not isinstance(cfg['timeout_seconds'],(int,float)) or isinstance(cfg['timeout_seconds'],bool) or not math.isfinite(cfg['timeout_seconds']) or cfg['timeout_seconds']<=0:raise Problem('タイムアウト秒数を確認してください。')
 object_value(cfg['face_inpaint'],'face_inpaint');object_value(cfg['ipadapter_settings'],'ipadapter_settings')
 for label,value,lo,hi in [('CFG',cfg['sampler_cfg'],0,100),('顔denoise',cfg['face_inpaint']['denoise'],0,1),('IP-Adapter weight',cfg['ipadapter_settings']['weight'],-10,10)]:
  if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi:raise Problem(label+'の数値を確認してください。')
 if type(cfg['ipadapter_settings']['enabled']) is not bool:raise Problem('IP-AdapterのON/OFFを確認してください。')
 if type(cfg['face_inpaint']['enabled']) is not bool:raise Problem('顔パスのON/OFFを確認してください。')
 for key in ('weight_type','embeds_scaling'):string(cfg['ipadapter_settings'][key],'ipadapter_settings.'+key,False)
 string(cfg['negative_prompt'],'negative_prompt');graph=object_value(cfg['workflow'],'workflow')
 if not graph:raise Problem('ComfyUIのAPI形式ワークフローを指定してください。')
 for key,node in graph.items():
  object_value(node,'workflow.'+key);string(node.get('class_type'),'class_type',False);object_value(node.get('inputs'),'inputs')
 object_value(cfg['bindings'],'bindings');object_value(cfg['trigger_loras'],'trigger_loras');object_value(cfg['launcher'],'launcher')
 for key in ('positive','negative','width','height','seed','reference_image'):
  v=cfg['bindings'].get(key)
  if not isinstance(v,list) or len(v)!=2 or any(not isinstance(x,str) or not x for x in v):raise Problem('差し込み先は[ノードID,入力名]の配列にしてください。',[key])
 for key in ('output','sampler'):string(cfg['bindings'].get(key),'bindings.'+key,False)
 if cfg['bindings'].get('adapter') is not None:string(cfg['bindings']['adapter'],'bindings.adapter',False)
 for key in ('model_source','clip_source'):
  v=cfg['bindings'].get(key)
  if not isinstance(v,list) or len(v)!=2 or not isinstance(v[0],str) or isinstance(v[1],bool) or not isinstance(v[1],int) or v[1]<0:raise Problem('接続元は[ノードID,出力番号]の配列にしてください。',[key])
 for key in ('python','main','models','ipadapter','clip_vision'):string(cfg['launcher'].get(key),'launcher.'+key,False)
 for key,rows in cfg['trigger_loras'].items():
  string(key,'trigger_loras key',False)
  if not isinstance(rows,list) or not rows:raise Problem('LoRAの対応先は空でない配列にしてください。')
  cg_validate({'prompt':'','loras':rows})
 return cfg

def resolve(data,wid,tid,uid):
 from tracks import Tracks
 w=next((w for w in data['works'] if w['id']==wid),None)
 if not w:raise Problem('作品が見つかりません。',status=404)
 t=next((t for t in w.get('tracks',[]) if t['id']==tid),None)
 if not t:raise Problem('Trackが見つかりません。',status=404)
 u=next((c for c in t.get('cgs',[]) if c['id']==uid),None)
 if not u:raise Problem('CGが見つかりません。',status=404)
 return w,t,u

def cg_validate(row):
 object_value(row,'cg');string(row.get('prompt',''),'cg.prompt')
 if 'start_unit' in row and row['start_unit'] is not None:string(row['start_unit'],'cg.start_unit',False)
 if 'block' in row and row['block'] is not None:string(row['block'],'cg.block',False)
 if 'note' in row:string(row['note'],'cg.note')
 if row.get('character_id') is not None:string(row['character_id'],'character_id',False)
 if 'loras' in row:
  if not isinstance(row['loras'],list):raise Problem('lorasは配列にしてください。')
  for lora in row['loras']:
   object_value(lora,'loras');string(lora.get('name'),'loras.name',False)
   for key in ('weight','strength_model','strength_clip'):
    if key in lora and (isinstance(lora[key],bool) or not isinstance(lora[key],(int,float)) or not math.isfinite(lora[key])):raise Problem('LoRAの強度は有限の数値にしてください。')

def describe(s,data,wid,tid,uid):
 w,t,u=resolve(data,wid,tid,uid);cg=u;cfg=config(s);problems=[];warnings=[];role=None
 if 'character_id' in cg:
  if cg['character_id']:role=next((r for r in w['characters'] if r['id']==cg['character_id']),None)
  if cg['character_id'] and not role:problems.append('対象の配役がありません。CGの対象キャラクターを選び直してください。')
 elif len(w['characters'])==1:role=w['characters'][0]
 elif len(w['characters'])>1:problems.append('対象キャラクターを選択してください。二人分の領域別生成は後続の範囲です。')
 actor=next((a for a in data['actors'] if role and a['id']==role.get('actor_id')),None)
 if role and not actor:problems.append('配役元のアクターが見つかりません。作品の配役を確認してください。')
 trigger=(actor or {}).get('trigger_word','');image_id=(actor or {}).get('image_id');reference=bool(image_id and s.has_media(data,image_id))
 if not cfg['ipadapter_settings']['enabled']:reference=False
 if cfg['ipadapter_settings']['enabled'] and image_id and not reference:problems.append('登録画像のファイルが見つかりません。アクターで画像を再登録してください。')
 if not cg.get('prompt','').strip():problems.append('CGプロンプトを入力して保存してください。')
 if trigger and trigger not in cg.get('prompt',''):warnings.append('トリガーワードがプロンプトに見当たりません。文字列は変更せず送信します。')
 if actor and not image_id:warnings.append('アクター画像は未登録です。参照画像なしで生成します。')
 loras=[];valid_cg=True;valid_configuration=True
 try:cg_validate(cg)
 except Problem as e:problems.append(str(e));valid_cg=False
 try:validate_config(cfg)
 except Problem as e:problems.append(str(e));valid_configuration=False
 def expand(row):
  direct=(actor or {}).get('lora');alias=[direct] if direct and row['name']==trigger else cfg['trigger_loras'].get(row['name']);entries=alias if alias is not None else [row]
  if not isinstance(entries,list) or not entries:raise Problem('トリガーとLoRAの対応は配列で指定してください。')
  for entry in entries:
   cg_validate({'prompt':'','loras':[entry]});strength=row.get('weight');model=row.get('strength_model',strength if strength is not None else entry.get('strength_model',entry.get('weight',.9)));clip=row.get('strength_clip',strength if strength is not None else entry.get('strength_clip',entry.get('weight',.9)));item=dict(name=entry['name'],strength_model=model,strength_clip=clip)
   previous=next((x for x in loras if x['name']==item['name']),None)
   if previous:previous.update(item)
   else:loras.append(item)
 try:
  if actor and 'lora' in actor and valid_configuration:
   if actor['lora']:expand(actor['lora'])
  elif trigger and valid_configuration:
   if trigger not in cfg['trigger_loras']:problems.append('キャラクターのLoRAが未設定です。アクター画面でLoRAファイルを選んでください。')
   else:expand({'name':trigger})
  if valid_cg and valid_configuration and isinstance(cg.get('loras',[]),list):
   for lora in cg.get('loras',[]):expand(lora)
 except Problem as e:problems.append(str(e))
 fingerprint=hashlib.sha256(json.dumps([{k:cg.get(k) for k in ('prompt','character_id','loras')},(actor or {}).get('id'),(actor or {}).get('lora'),trigger,image_id,cfg],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
 return dict(work_id=wid,track_id=tid,cg_id=uid,block=cg.get('block'),start_unit=__import__('cg_records').timing_unit(t,cg),needs_check=uid in __import__('cg_records').timing_checks(t),timing_issue=__import__('cg_records').timing_checks(t).get(uid),character_id=(role or {}).get('id'),character_name=(role or {}).get('names',{}).get('full','背景・キャラクター指定なし'),actor_id=(actor or {}).get('id'),trigger=trigger,reference_id=image_id if reference else None,reference_name=(data['media'].get(image_id) or {}).get('filename','なし') if cfg['ipadapter_settings']['enabled'] else '無効（参照画像は送信しません）',loras=loras,width=cfg['width'],height=cfg['height'],seed=cfg['seed'],generation_settings=generation_settings(cfg,reference),fingerprint=fingerprint,problems=problems,warnings=warnings)

def generation_settings(cfg,reference=False):
 standard=is_standard(cfg);g=cfg['workflow'];b=cfg['bindings'];adapter=g.get(b.get('adapter'),{}).get('inputs',{})
 return dict(standard=standard,negative_present=bool(cfg['negative_prompt']),cfg=cfg['sampler_cfg'] if standard else g.get(b['sampler'],{}).get('inputs',{}).get('cfg'),face_enabled=bool(standard and cfg['face_inpaint']['enabled']),face_denoise=cfg['face_inpaint']['denoise'] if standard else None,ipadapter_active=bool(reference and cfg['ipadapter_settings']['enabled']),ipadapter=copy.deepcopy(cfg['ipadapter_settings']) if standard else {k:adapter.get(k) for k in ('weight','weight_type','embeds_scaling')})

def prune(graph,output):
 keep=set();visiting=set()
 def visit(key):
  if key in visiting:raise Problem('ワークフローの接続に循環があります。')
  if key in keep:return
  if key not in graph:raise Problem('ワークフローの接続先ノードがありません。',[key])
  visiting.add(key)
  for value in graph[key]['inputs'].values():
   if isinstance(value,list) and len(value)==2 and isinstance(value[0],str) and isinstance(value[1],int):visit(value[0])
  visiting.remove(key);keep.add(key)
 visit(output);return {k:v for k,v in graph.items() if k in keep}

def build(cfg,cg,description,seed,reference_name=None,output_prefix='tsumugoe'):
 graph=copy.deepcopy(cfg['workflow']);b=cfg['bindings']
 def put(binding,value):
  where=b.get(binding)
  if not isinstance(where,list) or len(where)!=2 or where[0] not in graph or where[1] not in graph[where[0]]['inputs']:raise Problem('ワークフローの差し込み先を確認してください。',[binding])
  graph[where[0]]['inputs'][where[1]]=value
 put('positive',cg['prompt']);put('negative',cfg['negative_prompt']);put('width',cfg['width']);put('height',cfg['height']);put('seed',seed)
 model=copy.deepcopy(b['model_source']);clip=copy.deepcopy(b['clip_source'])
 # Do not silently bypass a custom model or CLIP chain when bindings are stale.
 sampler_inputs=graph.get(b['sampler'],{}).get('inputs',{});adapter_inputs=graph.get(b.get('adapter'),{}).get('inputs',{})
 original_model=sampler_inputs.get('model')
 if original_model==[b.get('adapter'),0]:original_model=adapter_inputs.get('model')
 if original_model!=model:raise Problem('MODELの接続元とbindings.model_sourceが一致していません。CG設定で既存チェーンの末尾を指定してください。')
 for bind in ('positive','negative'):
  node=graph[b[bind][0]]
  if 'clip' in node['inputs'] and node['inputs']['clip']!=clip:raise Problem('CLIPの接続元とbindings.clip_sourceが一致していません。CG設定を確認してください。')
 for i,lora in enumerate(description['loras']):
  key='tsumugoe_lora_'+str(i)
  if key in graph:raise Problem('予約されたLoRAノードIDがワークフローと重複しています。')
  graph[key]={'class_type':'LoraLoader','inputs':{'model':model,'clip':clip,'lora_name':lora['name'],'strength_model':lora['strength_model'],'strength_clip':lora['strength_clip']}};model=[key,0];clip=[key,1]
 for node in graph.values():
  if node['class_type']=='CLIPTextEncode' and node['inputs'].get('clip')==b['clip_source']:node['inputs']['clip']=copy.deepcopy(clip)
 sampler=b['sampler'];adapter=b.get('adapter');output=b['output']
 if sampler not in graph or output not in graph:raise Problem('サンプラーまたは出力ノードの指定を確認してください。')
 if description['reference_id'] and cfg['ipadapter_settings']['enabled']:
  if adapter not in graph or not graph[adapter]['class_type'].startswith('IPAdapter'):raise Problem('参照画像を使うIP-Adapterノードを設定してください。')
  graph[adapter]['inputs']['model']=model;put('reference_image',reference_name or 'pending.png');graph[sampler]['inputs']['model']=[adapter,0]
 else:graph[sampler]['inputs']['model']=model
 if is_standard(cfg):
  graph[sampler]['inputs']['cfg']=cfg['sampler_cfg']
  if adapter in graph:graph[adapter]['inputs'].update({k:v for k,v in cfg['ipadapter_settings'].items() if k!='enabled'})
  if cfg['face_inpaint']['enabled']:
   face_inputs=dict(image=['decode',0],model=model,positive=graph[sampler]['inputs']['positive'],negative=graph[sampler]['inputs']['negative'],vae=['checkpoint',2],seed=seed,steps=graph[sampler]['inputs']['steps'],cfg=cfg['sampler_cfg'],sampler_name=graph[sampler]['inputs']['sampler_name'],scheduler=graph[sampler]['inputs']['scheduler'],denoise=cfg['face_inpaint']['denoise'])
   graph['tsumugoe_face']={'class_type':'TsumugoeFacePass','inputs':face_inputs};graph[output]['inputs']['images']=['tsumugoe_face',0]
 if 'filename_prefix' in graph[output]['inputs']:graph[output]['inputs']['filename_prefix']=output_prefix
 return prune(graph,output)

def validate_remote(graph,info):
 problems=[]
 for key,node in graph.items():
  name=node['class_type']
  if name not in info:problems.append('ComfyUIにノードがありません：'+name);continue
  required=info[name].get('input',{}).get('required',{})
  for field,definition in required.items():
   if field not in node['inputs']:problems.append(key+' の '+field+' が未設定です。');continue
   value=node['inputs'][field]
   if not (name=='LoadImage' and field=='image') and isinstance(definition,list) and definition and isinstance(definition[0],list) and value not in definition[0] and not isinstance(value,list):problems.append(key+' の '+field+' がComfyUIの一覧にありません：'+str(value))
 return problems

class CG:
 def __init__(self,s):self.s=s
 def save(self,wid,tid,uid,record,revision=None):
  with self.s.lock:
   self.s.check_revision(revision);record=object_value(record,'cg');cg_validate(record);data=copy.deepcopy(self.s.data);w,t,u=resolve(data,wid,tid,uid);old=copy.deepcopy(u);u.update(merge(old,{k:v for k,v in record.items() if k not in ('id','unit','image_id','generated','error','generation_fingerprint')}))
   if 'start_unit' in record:
    if record['start_unit'] is not None and not any(x['id']==record['start_unit'] for x in t['units']):raise Problem('表示先ユニットを一覧から選んでください。')
    u.pop('block',None)
   if 'start_unit' not in record and 'block' in record and record['block'] is not None and not any(b['id']==record['block'] for b in t['blocks']):raise Problem('表示先Blockを一覧から選んでください。')
   if old.get('prompt')!=u.get('prompt') or old.get('character_id')!=u.get('character_id') or old.get('loras')!=u.get('loras'):u['changed']=True
   from cg_records import validate_timings
   validate_timings(t)
   self.s.commit(data,dict(action='cg_save',work_id=wid,track_id=tid,cg_id=uid));return dict(revision=data['revision'])
 def attach(self,wid,tid,uid,mid,revision=None):
  with self.s.lock:
   self.s.check_revision(revision);data=copy.deepcopy(self.s.data);w,t,u=resolve(data,wid,tid,uid);m=data['media'].get(mid)
   if not m or m.get('kind')!='cg' or m.get('work_id')!=wid or not self.s.has_media(data,mid):raise Problem('この作品の管理画像から選んでください。')
   u['image_id']=mid;u['changed']=False;self.s.commit(data,dict(action='cg_attach',work_id=wid,track_id=tid,cg_id=uid,media_id=mid));return dict(revision=data['revision'])
 def gallery(self,wid,tid):
  return [dict(id=mid,**copy.deepcopy(m),used=bool(self.s.media_users(self.s.data,mid))) for mid,m in self.s.data['media'].items() if m.get('kind')=='cg' and m.get('work_id')==wid and m.get('track_id')==tid and self.s.has_media(self.s.data,mid)]
 def upload(self,wid,tid,uid,filename,content,revision=None):
  mime,ext=image_type(content)
  with self.s.lock:
   self.s.check_revision(revision);data=copy.deepcopy(self.s.data);w,t,u=resolve(data,wid,tid,uid);mid=ident();path=self.s.work/'media'/(mid+'.'+ext);path.parent.mkdir(exist_ok=True);path.write_bytes(content)
   data['media'][mid]=dict(path='media/'+path.name,filename=Path(filename).name,mime=mime,kind='cg',work_id=wid,track_id=tid,created_at=now(),source='upload',cg_id=uid,size=list(struct.unpack('>II',content[16:24])) if ext=='png' else None);u['image_id']=mid;u['changed']=False
   try:self.s.commit(data,dict(action='cg_upload',work_id=wid,track_id=tid,cg_id=uid))
   except Exception:path.unlink(missing_ok=True);raise
   return dict(media_id=mid,revision=data['revision'])
 def delete_files(self,wid,tid,ids,revision=None):
  with self.s.lock:
   self.s.check_revision(revision)
   if not isinstance(ids,list) or not ids or any(not isinstance(i,str) for i in ids):raise Problem('削除する画像を一覧から選んでください。')
   allowed={r['id'] for r in self.gallery(wid,tid) if not r['used']}
   if not set(ids)<=allowed:raise Problem('使用中の画像は削除できません。添付先を変更して一覧を確認し直してください。')
   names=[self.s.data['media'][i]['filename'] for i in ids];self.s.commit(copy.deepcopy(self.s.data),dict(action='cg_files_delete',work_id=wid,track_id=tid,files=names),delete_media=ids);return dict(deleted=names,revision=self.s.data['revision'])
 def clear(self,wid,tid,uid,revision=None):
  with self.s.lock:
   self.s.check_revision(revision);data=copy.deepcopy(self.s.data);w,t,u=resolve(data,wid,tid,uid);mid=u.get('image_id');t['cgs'].remove(u);self.s.commit(data,dict(action='cg_clear',work_id=wid,track_id=tid,cg_id=uid),delete_media=[mid] if mid else []);return dict(revision=data['revision'])

def image_type(content):
 if content.startswith(b'\x89PNG\r\n\x1a\n') and len(content)>=33 and content[12:16]==b'IHDR':return 'image/png','png'
 if content.startswith(b'\xff\xd8\xff'):return 'image/jpeg','jpg'
 if content[:4]==b'RIFF' and content[8:12]==b'WEBP':return 'image/webp','webp'
 if content.startswith((b'GIF87a',b'GIF89a')):return 'image/gif','gif'
 raise Problem('画像を読めません。PNG・JPEG・WebP・GIFを指定してください。')
