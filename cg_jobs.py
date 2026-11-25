"""CG jobs use their own ComfyUI prompt IDs and never interrupt other jobs."""
import copy,json,secrets,threading,time,struct
from pathlib import Path
from model import Problem,ident,now
from cg import CG,config,resolve,describe,build,validate_remote,image_type
from comfy_client import Client
class Jobs:
 def __init__(self,s):self.s=s;self.lock=threading.Lock();self.job=None;self.cancel=threading.Event();self.thread=None;self.client_factory=Client
 def inspect(self):
  info=self.client_factory(config(self.s)['endpoint']).inspect();models={}
  for name,field in [('CheckpointLoaderSimple','ckpt_name'),('LoraLoader','lora_name'),('CLIPVisionLoader','clip_name'),('IPAdapterModelLoader','ipadapter_file')]:models[name]=(info.get(name,{}).get('input',{}).get('required',{}).get(field) or [[]])[0]
  return dict(ok=True,models=models,reference_available='IPAdapterAdvanced' in info and bool(models['CLIPVisionLoader']) and bool(models['IPAdapterModelLoader']))
 def preview(self,wid,tid,uid):
  with self.s.lock:
   d=describe(self.s,self.s.data,wid,tid,uid);cfg=config(self.s);w,t,u=resolve(self.s.data,wid,tid,uid)
   if not d['problems']:
    try:
     graph=build(cfg,u,d,0);d['effective_loras']=[dict(name=n['inputs']['lora_name'],strength_model=n['inputs']['strength_model'],strength_clip=n['inputs']['strength_clip']) for n in graph.values() if n['class_type']=='LoraLoader'];info=self.client_factory(cfg['endpoint']).inspect();d['problems']+=validate_remote(graph,info)
    except Problem as e:d['problems'].append(str(e));d['problems']+=e.details
   d['token']=d['fingerprint'];return d
 def start(self,wid,tid,uid,token):
  with self.lock:
   if self.job and self.job['running']:raise Problem('CGを生成中です。完了を待つか、中断してください。')
   d=self.preview(wid,tid,uid)
   if d['token']!=token:raise Problem('生成条件が変わりました。要約を確認し直してください。',status=409)
   if d['problems']:raise Problem('CGを生成できません。表示された条件を修正してください。',d['problems'])
   self.cancel=threading.Event();self.job=dict(id=ident(),work_id=wid,track_id=tid,cg_id=uid,running=True,phase='生成準備',prompt_id=None,started_at=now());self.thread=threading.Thread(target=self.run,args=(copy.deepcopy(self.job),d),daemon=True);self.thread.start();return self.status()
 def status(self):return copy.deepcopy(self.job or {'running':False})
 def stop(self):
  self.cancel.set();pid=(self.job or {}).get('prompt_id')
  if pid:
   client=self.client_factory((self.job or {}).get('endpoint',config(self.s)['endpoint']))
   try:client.request('/interrupt',{'prompt_id':pid});client.request('/queue',{'delete':[pid]})
   except Problem:pass
  return {'stopping':True}
 def cleanup(self,prefix):
  # Only a unique filename prefix in this app's dedicated output directory is eligible.
  folder=(self.s.work/'comfy-runtime/output').resolve()
  if folder.is_relative_to(self.s.work.resolve()) and prefix.startswith('tsumugoe_'):
   for p in folder.glob(prefix+'_*.png'):
    if p.is_file() and p.resolve().parent==folder:p.unlink(missing_ok=True)
 def run(self,job,d):
  prefix='tsumugoe_'+job['id'];media_path=None;started=time.monotonic();cfg=config(self.s);client=self.client_factory(cfg['endpoint']);receipt={};jobpath=self.s.work/'cg/jobs'/(job['id']+'.json');self.job['endpoint']=cfg['endpoint']
  try:
   with self.s.lock:
    w,t,u=resolve(self.s.data,job['work_id'],job['track_id'],job['cg_id']);source=copy.deepcopy(u)
    if describe(self.s,self.s.data,job['work_id'],job['track_id'],job['cg_id'])['fingerprint']!=d['fingerprint']:raise Problem('開始前に設定が変わりました。要約を確認し直してください。')
    ref=d['reference_id'];ref_path=self.s.media_path(self.s.data['media'][ref]) if ref else None;mime=self.s.data['media'][ref]['mime'] if ref else None
   if self.cancel.is_set():raise InterruptedError('CG生成を中断しました。')
   ref_name=client.upload(ref_path,ref,mime) if ref else None;seed=cfg['seed'] if cfg['seed']>=0 else secrets.randbits(63);graph=build(cfg,source,d,seed,ref_name,prefix);receipt=dict(id=job['id'],work_id=job['work_id'],track_id=job['track_id'],cg_id=job['cg_id'],reference_id=ref,reference_input=ref_name,seed=str(seed),workflow=graph,description=d,time=now());self.s._atomic(jobpath,receipt)
   result=client.request('/prompt',{'prompt':graph,'client_id':'tsumugoe-'+job['id']});pid=result.get('prompt_id')
   if not isinstance(pid,str) or not pid:raise Problem('ComfyUIのジョブIDを取得できません。ノード設定を確認してください。')
   self.job.update(prompt_id=pid,phase='ComfyUIで生成中',seed=str(seed));receipt['prompt_id']=pid;self.s._atomic(jobpath,receipt);deadline=time.monotonic()+cfg['timeout_seconds'];history=None
   while time.monotonic()<deadline:
    if self.cancel.is_set():raise InterruptedError('CG生成を中断しました。今回の画像は採用しません。')
    response=client.request('/history/'+pid);history=response.get(pid)
    if history:
     state=history.get('status',{})
     if state.get('status_str')=='error':raise Problem('ComfyUIの生成処理が失敗しました。モデル・VRAM・起動ログを確認してください。',[json.dumps(state.get('messages',[]),ensure_ascii=False)])
     if history.get('outputs'):break
    self.cancel.wait(.4)
   else:raise Problem('CG生成が時間切れです。ComfyUIの状態とタイムアウト設定を確認してください。')
   images=(history or {}).get('outputs',{}).get(cfg['bindings']['output'],{}).get('images',[])
   if not images:raise Problem('指定した出力ノードに画像がありません。CG設定の出力ノードを確認してください。')
   face_status=(history or {}).get('outputs',{}).get('tsumugoe_face',{}).get('tsumugoe_face',[]);receipt['face_inpaint']=face_status;self.job['face_inpaint']=face_status
   self.job['phase']='画像を保存中';raw=client.download(images[0]);mime,ext=image_type(raw)
   if self.cancel.is_set():raise InterruptedError('CG生成を中断しました。')
   with self.s.lock:
    data=copy.deepcopy(self.s.data);w,t,u=resolve(data,job['work_id'],job['track_id'],job['cg_id']);current=describe(self.s,data,job['work_id'],job['track_id'],job['cg_id']);mid=ident();media_path=self.s.work/'media'/(mid+'.'+ext);media_path.parent.mkdir(exist_ok=True);media_path.write_bytes(raw);size=list(struct.unpack('>II',raw[16:24])) if ext=='png' else None
    metadata=dict(path='media/'+media_path.name,filename=prefix+'.'+ext,mime=mime,kind='cg',work_id=w['id'],track_id=t['id'],cg_id=u['id'],created_at=now(),source='comfyui',seed=str(seed),size=size,reference_id=ref,face_inpaint=face_status,loras=d.get('effective_loras',d['loras']),receipt='cg/jobs/'+job['id']+'.json');data['media'][mid]=metadata
    adopted=current['fingerprint']==d['fingerprint'] and not self.cancel.is_set()
    if adopted:u.update(image_id=mid,changed=False,error=None,generation_fingerprint=d['fingerprint'])
    self.s.commit(data,dict(action='cg_generate',work_id=w['id'],track_id=t['id'],cg_id=u['id'],media_id=mid,adopted=adopted,prompt_id=pid,reference_id=ref));self.job.update(media_id=mid,adopted=adopted,phase='完了' if adopted else '生成中に条件が変わったため未採用。画像一覧から確認できます。');media_path=None
   receipt.update(result=images[0],media_id=mid,adopted=adopted,elapsed_seconds=time.monotonic()-started);self.s._atomic(jobpath,receipt)
  except Exception as e:
   if media_path:media_path.unlink(missing_ok=True)
   self.job.update(error=str(e),details=getattr(e,'details',[]),phase='中断' if self.cancel.is_set() else '生成失敗')
   try:
    with self.s.lock:
     data=copy.deepcopy(self.s.data);w,t,u=resolve(data,job['work_id'],job['track_id'],job['cg_id'])
     if u:u['error']=str(e);self.s.commit(data,dict(action='cg_error',work_id=w['id'],track_id=t['id'],cg_id=u['id'],reason=str(e)))
   except Problem:pass
   if receipt:receipt.update(error=str(e));self.s._atomic(jobpath,receipt)
  finally:
   try:self.cleanup(prefix)
   except OSError:pass
   self.job.update(running=False,cancelled=self.cancel.is_set(),elapsed_seconds=time.monotonic()-started)
