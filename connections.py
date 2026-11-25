"""Local-only connectivity checks. No synthesis or model downloads in the pilot."""
import copy,json,os,subprocess,uuid
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import build_opener,ProxyHandler,Request,HTTPRedirectHandler
from model import Problem

def local_endpoint(value):
 if not isinstance(value,str):raise Problem('接続先はURL文字列にしてください。')
 try:
  u=urlsplit(value);port=u.port
 except ValueError:raise Problem('接続先URLのポート番号を確認してください。')
 if u.scheme!='http' or u.hostname not in ('localhost','127.0.0.1','::1') or u.username or u.password or u.query or u.fragment:raise Problem('接続先には http://127.0.0.1:8188 のようなローカルURLを指定してください。外部サーバーには接続しません。')
 return value.rstrip('/')

def save_config(store,value):
 if not isinstance(value,dict):raise Problem('設定はJSONオブジェクトにしてください。')
 config=copy.deepcopy(value)
 if not isinstance(config.get('port'),int) or isinstance(config['port'],bool) or not 1024<=config['port']<=65535:raise Problem('ポート番号は1024〜65535の整数にしてください。')
 if not isinstance(config.get('tts'),dict) or not isinstance(config.get('comfyui'),dict):raise Problem('TTS・ComfyUIの設定を確認してください。')
 local_endpoint(config['comfyui'].get('endpoint'))
 from cg import validate_config
 config['comfyui']=validate_config(config['comfyui'])
 for key in ('project_dir','python','worker','checkpoint'):
  if not isinstance(config['tts'].get(key),str):raise Problem('tts.'+key+' はファイルパスの文字列にしてください。')
 if not isinstance(config.get('ffmpeg_path',''),str):raise Problem('ffmpeg_path はファイルパスの文字列にしてください。')
 with store.lock:
  store._atomic(store.work/'history'/('config-'+uuid.uuid4().hex+'.json'),store.config)
  store._atomic(store.config_path,config);store.config=config
 return dict(saved=True,restart_required=True)

class LocalRedirect(HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  local_endpoint(newurl)
  return super().redirect_request(req,fp,code,msg,headers,newurl)

def check_comfy(store):
 endpoint=local_endpoint(store.config['comfyui']['endpoint'])
 try:
  opener=build_opener(ProxyHandler({}),LocalRedirect())
  with opener.open(Request(endpoint+'/system_stats'),timeout=10) as r:
   result=json.load(r)
   if not isinstance(result,dict) or 'system' not in result:raise ValueError('system_stats response')
  return dict(ok=True,message='ComfyUIの応答を確認しました。画像生成は行っていません。',endpoint=endpoint)
 except Exception as e:return dict(ok=False,message='ComfyUIに接続できません。ComfyUIを起動し、設定の接続先とポートを確認してください。',details=[str(e)])

def check_tts(store):
 config=copy.deepcopy(store.config['tts']);missing=[]
 for key in ('python','worker','checkpoint'):
  if not Path(config.get(key,'')).is_file():missing.append(key+' のファイルが見つかりません。')
 if not Path(config.get('project_dir','')).is_dir():missing.append('project_dir のフォルダが見つかりません。')
 if missing:return dict(ok=False,message='IRODORI-TTSの設定が不足しています。接続設定でパスを修正してください。',details=missing)
 runtime=store.work/'runtime/tts-check';runtime.mkdir(parents=True,exist_ok=True)
 env=os.environ.copy();env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=config['project_dir']+os.pathsep+env.get('PYTHONPATH',''))
 for name in ('TEMP','TMP','MPLCONFIGDIR','TORCHINDUCTOR_CACHE_DIR','TRITON_CACHE_DIR'):
  p=runtime/name;p.mkdir(exist_ok=True);env[name]=str(p)
 request=dict(id=uuid.uuid4().hex,action='shutdown')
 try:
  result=subprocess.run([config['python'],'-B',config['worker']],input=json.dumps(request)+'\n',text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,cwd=runtime,env=env,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
  replies=[json.loads(s[len('@@IRODORI@@'):]) for s in result.stdout.splitlines() if s.startswith('@@IRODORI@@')]
  if result.returncode or not any(r.get('id')==request['id'] and r.get('shutdown') for r in replies):raise ValueError('ワーカーから確認応答がありません。'+result.stdout[-800:])
  return dict(ok=True,message='IRODORI-TTSワーカーの起動と応答を確認しました。モデル読込・音声生成は実行していません。')
 except Exception as e:return dict(ok=False,message='IRODORI-TTSワーカーを起動できません。Python環境・worker・project_dirの設定を確認してください。',details=[str(e)])
