"""Tsumugoe v0.2 HTTP application; Python standard library only."""
import argparse,hashlib,json,copy,threading,mimetypes,os,re,sys,traceback
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs,unquote
from model import Store,Problem,VERSION
import connections
BASE=Path(__file__).resolve().parent

class Server(ThreadingHTTPServer):
 daemon_threads=True
 allow_reuse_address=os.name != "nt"

def make_server(store,port=None):
 from audio_jobs import Jobs
 audio_jobs=Jobs(store)
 from cg_jobs import Jobs as CGJobs
 from comfy_client import Service
 cg_jobs=CGJobs(store);comfy_service=Service(store);generation_lock=threading.RLock()
 # Pin static assets to this running version so edits cannot mix new UI with old APIs.
 asset_names=('index.html','app.js','audio.js','cg.js','novel.js','autosave.js','structured.js','style.css')
 assets={name:(store.base/'web'/name).read_bytes() for name in asset_names if (store.base/'web'/name).is_file()}
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,format,*args):pass
  def reply(self,status,value,mime='application/json; charset=utf-8'):
   content=json.dumps(value,ensure_ascii=False,allow_nan=False).encode() if not isinstance(value,bytes) else value
   self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(content)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY');self.end_headers()
   try:self.wfile.write(content)
   except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
  def check_origin(self):
   host=self.headers.get('Host','');u=urlsplit('http://'+host)
   if u.hostname not in ('127.0.0.1','localhost','::1'):raise Problem('このアプリはローカル接続専用です。',status=403)
   origin=self.headers.get('Origin')
   if origin:
    o=urlsplit(origin)
    if o.hostname!=u.hostname or o.port!=u.port or o.scheme!='http':raise Problem('別のサイトからの操作は受け付けません。アプリ画面を開き直してください。',status=403)
  def guarded(self,method):
   try:self.check_origin();method()
   except Problem as e:self.reply(e.status,dict(error=str(e),details=e.details))
   except (ValueError,KeyError,TypeError,json.JSONDecodeError) as e:self.reply(400,dict(error='入力の形式を確認してください。',details=[str(e)]))
   except OSError as e:self.reply(500,dict(error='ファイルを保存できません。空き容量とファイルの使用状態を確認してください。',details=[str(e)]))
   except Exception as e:
    folder=store.work/'logs';folder.mkdir(exist_ok=True)
    with (folder/'server-errors.log').open('a',encoding='utf-8') as f:f.write(traceback.format_exc())
    self.reply(500,dict(error='処理を完了できませんでした。入力は保持してください。work/logs/server-errors.log を確認してください。',details=[type(e).__name__]))
  def do_GET(self):self.guarded(self.get)
  def do_HEAD(self):self.guarded(self.get)
  def get(self):
   route=urlsplit(self.path).path
   if route=='/api/state':return self.reply(200,store.snapshot())
   if route=='/api/cg-job':return self.reply(200,cg_jobs.status())
   if route=='/api/audio-job':return self.reply(200,audio_jobs.status())
   if route=='/api/audio-orphans':
    from audio import Audio
    with store.lock:return self.reply(200,Audio(store).orphan_list())
   if route=='/api/config':return self.reply(200,store.config)
   if route=='/api/version':return self.reply(200,dict(version=VERSION,increment='CG生成・管理',acceptance='ユーザー受け入れ検証待ち'))
   if route.startswith('/media/'):
    key=route[7:]
    with store.lock:media=store.data['media'].get(key)
    if not media:return self.reply(404,dict(error='ファイルが見つかりません。一覧を更新してください。'))
    path=store.media_path(media)
    if not path.is_file():return self.reply(404,dict(error='保存したファイルが見つかりません。再登録してください。'))
    size=path.stat().st_size;start=0;end=size-1;requested=self.headers.get('Range')
    if requested:
     match=re.fullmatch(r'bytes=(\d+)-(\d*)',requested)
     if not match:return self.reply(416,dict(error='再生位置を指定し直してください。'))
     start=int(match[1]);end=min(int(match[2]) if match[2] else end,end)
     if start>end:return self.reply(416,dict(error='再生位置を指定し直してください。'))
    self.send_response(206 if requested else 200);self.send_header('Content-Type',media['mime']);self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
    if requested:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
    self.end_headers()
    if self.command=='HEAD':return
    try:
     with path.open('rb') as f:
      f.seek(start);left=end-start+1
      while left:
       block=f.read(min(left,1024*1024))
       if not block:break
       self.wfile.write(block);left-=len(block)
    except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
    return
   files={'/':'index.html','/app.js':'app.js','/audio.js':'audio.js','/cg.js':'cg.js','/novel.js':'novel.js','/autosave.js':'autosave.js','/structured.js':'structured.js','/style.css':'style.css'}
   if route in files:
    path=store.base/'web'/files[route];return self.reply(200,assets[files[route]],mimetypes.guess_type(path.name)[0]+'; charset=utf-8')
   return self.reply(404,dict(error='ページが見つかりません。左のナビゲーションから開き直してください。'))
  def do_POST(self):self.guarded(self.post)
  def post(self):
   route=urlsplit(self.path);size=int(self.headers.get('Content-Length','0'))
   if size<0:raise Problem('送信データのサイズを確認してください。')
   content=self.rfile.read(size)
   if len(content)!=size:raise Problem('送信が途中で切れました。再送信してください。')
   if route.path=='/api/cg-upload':
    from cg import CG
    q=parse_qs(route.query);revision=int(q['revision'][0]) if 'revision' in q else None
    return self.reply(200,CG(store).upload(q['work_id'][0],q['track_id'][0],q.get('cg_id',q.get('unit_id'))[0],unquote(self.headers.get('X-Filename','image')),content,revision))
   if route.path=='/api/upload':
    q=parse_qs(route.query);revision=int(q['revision'][0]) if 'revision' in q else None
    return self.reply(200,store.upload(q['kind'][0],q['id'][0],unquote(self.headers.get('X-Filename','upload')),content,revision,q.get('replacing',['false'])[0]=='true'))
   if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise Problem('JSON形式で送信してください。')
   try:body=json.loads(content,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('数値には有限値を指定してください。')))
   except (ValueError,UnicodeDecodeError):raise Problem('JSONの構文を確認してください。入力は変更していません。')
   if not isinstance(body,dict):raise Problem('JSONオブジェクトで送信してください。')
   revision=body.get('revision');result=None
   if route.path=='/api/save':result=store.save(body.get('kind'),body.get('record'),revision,body.get('work_id'),body.get('confirmed_names') is True)
   elif route.path=='/api/character-preview':result=store.save('character',body.get('record'),revision,body.get('work_id'),preview=True)
   elif route.path=='/api/import':
    value=body.get('value')
    if 'text' in body:
     try:value=json.loads(body['text'],parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
     except (ValueError,TypeError):raise Problem('貼り付けたJSONの構文を確認してください。入力は残っています。')
    result=store.import_payload(value,revision,body.get('work_id'),body.get('track_id'),body.get('track_mode','new'),body.get('confirmation'))
   elif route.path.startswith('/api/cg-') or route.path in ('/api/comfy-start','/api/comfy-status'):
    from cg import CG,config
    manager=CG(store);wid=body.get('work_id');tid=body.get('track_id');uid=body.get('cg_id',body.get('unit_id'))
    if route.path=='/api/cg-save':result=manager.save(wid,tid,uid,body.get('record'),revision)
    elif route.path=='/api/cg-attach':result=manager.attach(wid,tid,uid,body.get('media_id'),revision)
    elif route.path=='/api/cg-preview':result=cg_jobs.preview(wid,tid,uid)
    elif route.path=='/api/cg-start':
     with generation_lock:
      if audio_jobs.status().get('running'):raise Problem('音声生成中です。完了してからCGを生成してください。')
      result=cg_jobs.start(wid,tid,uid,body.get('token'))
    elif route.path=='/api/cg-stop':result=cg_jobs.stop()
    elif route.path=='/api/cg-gallery':
     with store.lock:result=manager.gallery(wid,tid)
    elif route.path=='/api/cg-inspect':result=cg_jobs.inspect()
    elif route.path=='/api/comfy-start':result=comfy_service.start()
    elif route.path=='/api/comfy-status':result=comfy_service.status()
    elif route.path in ('/api/cg-clear','/api/cg-delete-files'):
     if body.get('confirmed') is not True:raise Problem('削除するCGの内訳を確認してください。')
     result=manager.clear(wid,tid,uid,revision) if route.path=='/api/cg-clear' else manager.delete_files(wid,tid,body.get('ids'),revision)
    elif route.path=='/api/cg-config':result=config(store);result['seed']=str(result['seed'])
    elif route.path=='/api/cg-config-save':
     cfg=copy.deepcopy(store.config);cfg['comfyui']=body.get('config');result=connections.save_config(store,cfg)
    else:raise Problem('CG操作がありません。',status=404)
   elif route.path.startswith('/api/audio-'):
    from audio import Audio
    from audio_jobs import export_wav
    manager=Audio(store);wid=body.get('work_id');tid=body.get('track_id')
    if route.path=='/api/audio-plan':result=manager.structure_preview(wid,tid,body.get('target_seconds',18),body.get('chars_per_second',6))
    elif route.path=='/api/audio-edit':result=manager.edit(wid,tid,body.get('operation'),body,revision)
    elif route.path=='/api/audio-preview':result=audio_jobs.preview(wid,tid,body.get('mode','missing'),body.get('ids'))
    elif route.path=='/api/audio-start':
     with generation_lock:
      if cg_jobs.status().get('running'):raise Problem('CG生成中です。完了してから音声を生成してください。')
      from comfy_client import release_for_audio
      release_for_audio(store)
      result=audio_jobs.start(wid,tid,body.get('mode','missing'),body.get('ids'),body.get('token'))
    elif route.path=='/api/audio-stop':result=audio_jobs.stop()
    elif route.path=='/api/audio-export':result=export_wav(store,wid,tid)
    elif route.path=='/api/audio-orphan-delete':
     if body.get('confirmed') is not True:raise Problem('削除する音声ファイルの一覧を確認してください。')
     result=manager.orphan_delete(body.get('ids'),revision)
    else:raise Problem('音声操作がありません。',status=404)
   elif route.path.startswith('/api/dialogue-'):
    from dialogue import Dialogue
    manager=Dialogue(store);wid=body.get('work_id');tid=body.get('track_id');uid=body.get('unit_id')
    if route.path=='/api/dialogue-save':result=manager.unit_save(wid,tid,uid,body.get('record'),revision)
    elif route.path=='/api/dialogue-block':result=manager.block_save(wid,tid,body.get('block_id'),body.get('level'),revision)
    elif route.path=='/api/dialogue-levels':result=manager.levels_save(wid,tid,body.get('levels'),revision)
    elif route.path=='/api/dialogue-clear':result=manager.clear_check(wid,tid,uid,revision)
    elif route.path=='/api/dialogue-add':result=manager.add(wid,tid,body.get('block_id'),body.get('reference'),revision)
    elif route.path=='/api/dialogue-move':result=manager.move(wid,tid,uid,body.get('direction'),revision)
    else:raise Problem('この台詞操作はありません。',status=404)
   elif route.path.startswith('/api/track-') or route.path.startswith('/api/block-') or route.path=='/api/unit-block-move':
    from tracks import Tracks
    manager=Tracks(store);wid=body.get('work_id');tid=body.get('track_id')
    if route.path in ('/api/track-delete-preview','/api/track-delete'):
     with generation_lock:
      if any(j.get('running') and j.get('work_id')==wid and j.get('track_id')==tid for j in (audio_jobs.status(),cg_jobs.status())):raise Problem('このTrackは生成中です。生成の完了または中断後に削除してください。')
      result=manager.track_preview(wid,tid) if route.path=='/api/track-delete-preview' else manager.track_delete(wid,tid,body.get('signature'),body.get('acknowledged') is True)
    elif route.path=='/api/track-save':result=manager.save_meta(wid,tid,body.get('record'),revision)
    elif route.path=='/api/block-add':result=manager.block_add(wid,tid,body.get('reference'),body.get('position','after'),revision)
    elif route.path=='/api/block-preview':
     with store.lock:result=manager.block_preview(wid,tid,body.get('block_id'))
    elif route.path=='/api/block-delete':result=manager.block_delete(wid,tid,body.get('block_id'),body.get('signature'),body.get('acknowledged') is True)
    elif route.path=='/api/unit-block-move':result=manager.move_unit(wid,tid,body.get('unit_id'),body.get('block_id'),revision)
    else:raise Problem('このTrack操作はまだありません。')
   elif route.path=='/api/delete-preview':
    with store.lock:result=store.deletion_preview(body.get('kind'),body.get('id'),reference_id=body.get('reference_id'))
   elif route.path=='/api/delete':result=store.delete(body.get('kind'),body.get('id'),body.get('signature'),body.get('acknowledged') is True,body.get('reference_id'))
   elif route.path=='/api/image-remove':result=store.remove_image(body.get('id'),body.get('confirmed') is True,revision)
   elif route.path=='/api/reading-save':result=store.reading_save(body.get('work_id'),body.get('record'),revision)
   elif route.path=='/api/reading-delete':result=store.reading_delete(body.get('work_id'),body.get('id'),revision)
   elif route.path=='/api/config-save':result=connections.save_config(store,body.get('config'))
   elif route.path=='/api/connection-check':
    if body.get('service')=='tts':result=connections.check_tts(store)
    elif body.get('service')=='comfyui':result=connections.check_comfy(store)
    else:raise Problem('確認する接続先を選んでください。')
   elif route.path=='/api/extensions-save':result=store.update_extensions(body.get('value'),revision)
   else:raise Problem('操作が見つかりません。画面を再読み込みしてください。',status=404)
   self.reply(200,result)
 server=Server(('127.0.0.1',store.config['port'] if port is None else port),Handler);server.audio_jobs=audio_jobs;server.cg_jobs=cg_jobs;return server

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--port',type=int);parser.add_argument('--base',type=Path,default=BASE);args=parser.parse_args()
 store=Store(args.base);server=make_server(store,args.port)
 print(f'つむごえ v{VERSION}: http://127.0.0.1:{server.server_port}',flush=True)
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:
  server.cg_jobs.stop()
  if server.cg_jobs.thread:server.cg_jobs.thread.join(timeout=8)
  server.audio_jobs.stop()
  if server.audio_jobs.thread:server.audio_jobs.thread.join(timeout=8)
  server.server_close()
if __name__=='__main__':main()
