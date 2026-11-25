"""Local-only ComfyUI API and optional isolated local process. Standard library."""
import json,os,subprocess,uuid,threading
from pathlib import Path
from urllib.parse import urlencode,urlsplit
from urllib.request import build_opener,ProxyHandler,Request,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
from model import Problem
from connections import local_endpoint
class NoRedirect(HTTPRedirectHandler):
 def redirect_request(self,*args):raise Problem('ComfyUIの転送応答は受け付けません。ローカルの接続先を確認してください。')
class Client:
 def __init__(self,endpoint):self.endpoint=local_endpoint(endpoint);self.opener=build_opener(ProxyHandler({}),NoRedirect())
 def request(self,path,body=None,raw=None,mime=None,timeout=20):
  content=raw if raw is not None else json.dumps(body).encode() if body is not None else None
  req=Request(self.endpoint+path,data=content,headers={'Content-Type':mime or 'application/json'})
  try:
   with self.opener.open(req,timeout=timeout) as r:result=r.read()
  except HTTPError as e:
   detail=e.read().decode('utf-8',errors='replace')
   raise Problem('ComfyUIが処理を受け付けませんでした。ノード・モデル・設定を確認してください。',[detail])
  except (URLError,TimeoutError,OSError) as e:raise Problem('ComfyUIに接続できません。専用ComfyUIを起動し、接続先を確認してください。',[str(e)])
  if mime=='download':return result
  if not result and path in ('/free','/queue','/interrupt'):return {}
  try:return json.loads(result)
  except (ValueError,UnicodeDecodeError):raise Problem('ComfyUIの応答を読めません。接続先と起動ログを確認してください。')
 def inspect(self):return self.request('/object_info')
 def upload(self,path,mid,mime):
  boundary='tsumugoe'+uuid.uuid4().hex;filename='tsumugoe-'+mid+path.suffix.lower();data=b''
  for k,v in [('overwrite','true'),('subfolder','tsumugoe')]:data+=('--'+boundary+'\r\nContent-Disposition: form-data; name="'+k+'"\r\n\r\n'+v+'\r\n').encode()
  data+=('--'+boundary+'\r\nContent-Disposition: form-data; name="image"; filename="'+filename+'"\r\nContent-Type: '+mime+'\r\n\r\n').encode()+path.read_bytes()+('\r\n--'+boundary+'--\r\n').encode();r=self.request('/upload/image',raw=data,mime='multipart/form-data; boundary='+boundary)
  name=r.get('name');sub=r.get('subfolder','')
  if not isinstance(name,str) or Path(name).name!=name or not isinstance(sub,str) or Path(sub).is_absolute() or ':' in sub or '..' in Path(sub).parts:raise Problem('ComfyUIの参照画像保存先を確認してください。')
  return (sub.rstrip('/')+'/' if sub else '')+name
 def download(self,item):
  name=item.get('filename');sub=item.get('subfolder','');kind=item.get('type','output')
  if not isinstance(name,str) or Path(name).name!=name or '/' in name or '\\' in name or not isinstance(sub,str) or Path(sub).is_absolute() or ':' in sub or '..' in sub.replace('\\','/').split('/') or kind not in ('output','temp','input'):raise Problem('ComfyUIの出力ファイル情報を確認してください。')
  return self.request('/view?'+urlencode({'filename':name,'subfolder':sub,'type':kind}),mime='download')
class Service:
 def __init__(self,store):self.s=store;self.process=None;self.process_endpoint=None;self.lock=threading.Lock()
 def status(self):
  from cg import config
  endpoint=config(self.s)['endpoint'];log='work/comfy-runtime/startup.log'
  try:
   result=Client(endpoint).request('/system_stats',timeout=2)
   if not isinstance(result,dict) or 'system' not in result:raise Problem('ComfyUIの応答形式が違います。接続先を確認してください。')
   return dict(running=True,starting=False,state='ready',endpoint=endpoint,message='接続済み：'+endpoint)
  except Problem:pass
  owned=self.process if self.process_endpoint==endpoint else None
  if owned and owned.poll() is None:return dict(running=False,starting=True,state='starting',endpoint=endpoint,message='ComfyUIを起動中です。接続を待っています。')
  if owned:return dict(running=False,starting=False,state='failed',endpoint=endpoint,message='ComfyUIの起動に失敗しました（終了コード '+str(owned.returncode)+'）。'+log+' を確認してください。')
  return dict(running=False,starting=False,state='stopped',endpoint=endpoint,message='ComfyUIは未起動です。起動ボタンを押してください。')
 def start(self):
  with self.lock:
   state=self.status()
   if state['running'] or state['starting']:return state
   self._start()
   return self.status()
 def _start(self):
  from cg import config
  cfg=config(self.s);c=Client(cfg['endpoint'])
  try:
   c.request('/system_stats');return {'running':True,'message':'専用ComfyUIは起動済みです。'}
  except Problem:pass
  if self.process and self.process.poll() is None and self.process_endpoint==cfg['endpoint']:return {'running':True,'message':'専用ComfyUIを起動中です。少し待って接続を確認してください。'}
  launch=cfg['launcher'];python=Path(launch['python']);main=Path(launch['main'])
  if not python.is_file() or not main.is_file():raise Problem('ComfyUIのPythonまたはmain.pyがありません。CG設定でパスを修正してください。')
  u=urlsplit(cfg['endpoint'])
  if not u.port or u.path not in ('','/'):raise Problem('専用起動にはポートを含むローカルURLを指定してください。')
  root=self.s.work/'comfy-runtime';root.mkdir(exist_ok=True)
  for name in ('input','output','temp','user','cache','models','custom_nodes'): (root/name).mkdir(exist_ok=True)
  import shutil
  node=root/'custom_nodes/tsumugoe_face';node.mkdir(exist_ok=True);shutil.copyfile(Path(__file__).parent/'comfy_nodes/tsumugoe_face.py',node/'__init__.py')
  paths={'shared':{'base_path':launch['models'],'checkpoints':'StableDiffusion','loras':'Lora','vae':'VAE'},'reference':{'ipadapter':launch['ipadapter'],'clip_vision':launch['clip_vision']},'nodes':{'custom_nodes':str(main.parent/'custom_nodes')}}
  (root/'model_paths.yaml').write_text(json.dumps(paths,indent=2),encoding='utf-8');env=os.environ.copy();env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',CUDA_CACHE_PATH=str(root/'cache'),TMP=str(root/'temp'),TEMP=str(root/'temp'))
  args=[str(python),'-B',str(main),'--listen','127.0.0.1','--port',str(u.port),'--base-directory',str(root),'--user-directory',str(root/'user'),'--extra-model-paths-config',str(root/'model_paths.yaml'),'--disable-auto-launch','--offline','--disable-all-custom-nodes','--whitelist-custom-nodes','ComfyUI_IPAdapter_plus','tsumugoe_face','--use-pytorch-cross-attention','--reserve-vram','0.9']
  log=(root/'startup.log').open('ab')
  try:self.process_endpoint=cfg['endpoint'];self.process=subprocess.Popen(args,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
  finally:log.close()
  (root/'process.json').write_text(json.dumps({'pid':self.process.pid,'endpoint':cfg['endpoint']}),encoding='utf-8');return {'running':True,'message':'専用ComfyUIを起動しました。接続確認を行ってください。','pid':self.process.pid}


def release_for_audio(store):
 """Release only our dedicated service's idle model cache before TTS uses the GPU."""
 record=store.work/'comfy-runtime/process.json'
 if not record.is_file():return {'released':False}
 try:owned=json.loads(record.read_text(encoding='utf-8'))
 except (ValueError,OSError):return {'released':False}
 from cg import config
 endpoint=config(store)['endpoint']
 if owned.get('endpoint')!=endpoint:return {'released':False}
 client=Client(endpoint)
 try:q=client.request('/queue')
 except Problem:return {'released':False}
 if q.get('queue_running') or q.get('queue_pending'):raise Problem('専用ComfyUIでCGを処理中です。完了してから音声を生成してください。')
 client.request('/free',{'unload_models':True,'free_memory':True});return {'released':True}
