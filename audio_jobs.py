"""One local generation job. Staged outputs, cancellation, no takes."""
import copy,json,os,queue,shutil,subprocess,threading,time,wave,array
from pathlib import Path
from model import Problem,ident,now
from audio import Audio,audio,context,chunk_state,config_problems,wav_info,peaks,summary
class Worker:
 def __init__(self,store,cancel):self.s=store;self.cancel=cancel;self.p=None;self.q=queue.Queue()
 def start(self):
  cfg=self.s.config['tts'];runtime=self.s.work/'runtime/tts';runtime.mkdir(parents=True,exist_ok=True);env=os.environ.copy();env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8',PYTHONPATH=cfg['project_dir']+os.pathsep+env.get('PYTHONPATH',''))
  for name in ('TEMP','TMP','MPLCONFIGDIR','TORCHINDUCTOR_CACHE_DIR','TRITON_CACHE_DIR'):
   p=runtime/name;p.mkdir(exist_ok=True);env[name]=str(p)
  self.p=subprocess.Popen([cfg['python'],'-B',cfg['worker']],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',cwd=runtime,env=env,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
  def read():
   for line in self.p.stdout:
    if line.startswith('@@IRODORI@@'):
     try:self.q.put(json.loads(line[11:]))
     except ValueError:pass
   self.q.put({'eof':True})
  threading.Thread(target=read,daemon=True).start()
 def synthesize(self,ctx,path):
  if not self.p:self.start()
  cfg=self.s.config['tts'];vid=ctx['voice_id'];voice=next(v for v in self.s.data['voices'] if v['id']==vid);mid=ctx['ref_id'];rid=ident();request=dict(id=rid,action='synthesize',checkpoint=cfg['checkpoint'],model_device=cfg.get('model_device','cuda'),model_precision=cfg.get('model_precision','bf16'),codec_device=cfg.get('codec_device','cuda'),codec_precision=cfg.get('codec_precision','fp32'),num_steps=cfg.get('num_steps',40),duration_scale=cfg.get('duration_scale',1.0),text=ctx['text'],output=str(path),voice={**voice.get('tts_options',{}),'caption':ctx['caption'],'no_ref':ctx['no_ref'],'ref_wav':str(self.s.media_path(self.s.data['media'][mid])) if mid else ''})
  self.p.stdin.write(json.dumps(request,ensure_ascii=True)+'\n');self.p.stdin.flush();deadline=time.monotonic()+cfg.get('timeout_seconds',1800)
  while True:
   if self.cancel.is_set():self.close();raise InterruptedError('中断しました。')
   if time.monotonic()>deadline:self.close();raise Problem('TTS応答が時間切れです。接続設定とワーカーログを確認してください。')
   try:r=self.q.get(timeout=.1)
   except queue.Empty:continue
   if r.get('eof'):raise Problem('TTSワーカーが終了しました。環境・GPUメモリ・モデル設定を確認してください。')
   if r.get('id')==rid:
    if not r.get('ok'):raise Problem('TTS生成失敗：'+r.get('error','応答を確認してください。'))
    return
 def close(self):
  if self.p:
   if self.p.poll() is None:self.p.terminate()
   try:self.p.wait(timeout=5)
   except subprocess.TimeoutExpired:self.p.kill();self.p.wait(timeout=5)
   for f in (self.p.stdin,self.p.stdout):
    if f:f.close()
   self.p=None
class Jobs:
 def __init__(self,store):self.s=store;self.lock=threading.Lock();self.job=None;self.cancel=threading.Event();self.worker_factory=Worker;self.thread=None
 def preview(self,wid,tid,mode='missing',ids=None):
  with self.s.lock:
   w,t=Audio(self.s).locate(self.s.data,wid,tid);rows=[];global_errors=config_problems(self.s);selected=set(ids or [])
   for i,c in enumerate(audio(t)['chunks']):
    ctx=context(t,c,w,self.s.data,self.s);state=chunk_state(c,ctx,self.s.data,self.s);eligible=mode=='all' or mode=='selected' and c['id'] in selected or mode=='changed' and state=='変更あり' or mode=='retry' and (c.get('error') or c.get('interrupted')) or mode=='missing' and state!='音声あり';errors=global_errors+ctx['problems'];status='対象' if eligible and not errors else '実行不可' if eligible else 'スキップ';rows.append(dict(id=c['id'],sequence=i+1,unit=c['unit'],status=status,reasons=errors if eligible else ['指定した生成範囲の対象外です。'],fingerprint=ctx['fingerprint'],voice=ctx['voice_name'],ref=ctx['ref_name']))
   if mode not in ('all','selected','changed','retry','missing'):raise Problem('生成範囲を選び直してください。')
   token=__import__('hashlib').sha256(json.dumps([self.s.data['revision'],wid,tid,rows],sort_keys=True).encode()).hexdigest();return dict(token=token,rows=rows,target=sum(r['status']=='対象' for r in rows),blocked=sum(r['status']=='実行不可' for r in rows),skipped=sum(r['status']=='スキップ' for r in rows))
 def start(self,wid,tid,mode,ids,token):
  with self.lock:
   if self.job and self.job['running']:raise Problem('生成中です。完了を待つか中断してください。')
   p=self.preview(wid,tid,mode,ids)
   if p['token']!=token:raise Problem('設定が変わりました。生成前の内訳をもう一度確認してください。',status=409)
   if not p['target']:raise Problem('生成できる対象がありません。内訳の理由を修正してください。')
   self.cancel=threading.Event();self.job=dict(id=ident(),work_id=wid,track_id=tid,running=True,total=p['target'],done=0,current=None,results=[],cancelled=False);self.thread=threading.Thread(target=self.run,args=(copy.deepcopy(self.job),[r for r in p['rows'] if r['status']=='対象']),daemon=True);self.thread.start();return self.status()
 def status(self):return copy.deepcopy(self.job or dict(running=False,results=[]))
 def stop(self):
  self.cancel.set();return dict(stopping=True)
 def run(self,job,rows):
  stage=self.s.work/'runtime/jobs'/job['id'];worker=None;pending=[]
  try:
   stage.mkdir(parents=True,exist_ok=True);worker=self.worker_factory(self.s,self.cancel)
   for row in rows:
    if self.cancel.is_set():break
    self.job['current']=row['sequence'];path=stage/(row['id']+'.wav')
    with self.s.lock:
     w,t=Audio(self.s).locate(self.s.data,job['work_id'],job['track_id']);c=next((c for c in audio(t)['chunks'] if c['id']==row['id']),None)
     if not c:continue
     ctx=context(t,c,w,self.s.data,self.s)
    result=dict(id=row['id'],sequence=row['sequence'],fingerprint=ctx['fingerprint'])
    try:
     if ctx['fingerprint']!=row['fingerprint']:raise Problem('生成前に設定が変わりました。内訳を確認し直してください。')
     worker.synthesize(ctx,path);info=wav_info(path);result.update(ok=True,path=path,info=info,peaks=peaks(path),actual_text=ctx['text'],ref_id=ctx['ref_id'],voice_id=ctx['voice_id']);pending.append(result)
    except InterruptedError:break
    except Exception as e:result.update(ok=False,error=str(e));pending.append(result)
    self.job['done']+=1;self.job['results'].append({k:v for k,v in result.items() if k in ('id','sequence','ok','error')})
   with self.s.lock:
    data=copy.deepcopy(self.s.data);w,t=Audio(self.s).locate(data,job['work_id'],job['track_id']);removed=[];published=[]
    for row in rows:
     c=next((c for c in audio(t)['chunks'] if c['id']==row['id']),None)
     if self.cancel.is_set() and c:c['interrupted']=True
    if not self.cancel.is_set():
     for r in pending:
      c=next((c for c in audio(t)['chunks'] if c['id']==r['id']),None)
      if not c:
       for result in self.job['results']:
        if result['id']==r['id']:result.update(ok=False,error='生成中にチャンクが削除されたため採用しませんでした。')
       continue
      if context(t,c,w,data,self.s)['fingerprint']!=r['fingerprint']:
       c['error']='生成中に設定が変わったため採用しませんでした。変更後の内容で再生成してください。'
       for result in self.job['results']:
        if result['id']==r['id']:result.update(ok=False,error=c['error'])
       continue
      if not r['ok']:c['error']=r['error'];continue
      mid=ident();dest=self.s.work/'media'/(mid+'.wav');dest.parent.mkdir(exist_ok=True);shutil.copy2(r['path'],dest);published.append(dest)
      data['media'][mid]=dict(path='media/'+dest.name,filename='chunk-'+str(r['sequence'])+'.wav',mime='audio/wav',kind='track_audio',work_id=job['work_id'],track_id=job['track_id'],seconds=r['info']['seconds'],created_at=now());removed.append(c.get('media_id'));c.update(media_id=mid,fingerprint=r['fingerprint'],actual_text=r['actual_text'],used_ref_id=r['ref_id'],used_voice_id=r['voice_id'],seconds=r['info']['seconds'],peaks=r['peaks'],error=None,interrupted=False)
    try:self.s.commit(data,dict(action='audio_generate',work_id=job['work_id'],track_id=job['track_id'],cancelled=self.cancel.is_set(),results=self.job['results']),delete_media=removed)
    except Exception:
     for p in published:p.unlink(missing_ok=True)
     raise
  except Exception as e:self.job['error']=str(e)
  finally:
   if worker:
    try:worker.close()
    except Exception as e:self.job.setdefault('error',str(e))
   for p in stage.glob('*.wav'):p.unlink(missing_ok=True)
   try:stage.rmdir()
   except OSError:pass
   self.job['cancelled']=self.cancel.is_set();self.job['running']=False;self.job['current']=None

def export_wav(store,wid,tid):
 with store.lock:
  data=copy.deepcopy(store.data);w,t=Audio(store).locate(data,wid,tid)
  if not summary(t,w,data,store)['complete']:raise Problem('全単位の台詞・全チャンクの生成・要確認の解消を終えてから書き出してください。')
  chunks=audio(t)['chunks'];gaps=audio(t)['gaps'];mid=ident();dest=store.work/'media'/(mid+'.wav');dest.parent.mkdir(exist_ok=True);params=None
  try:
   with wave.open(str(dest),'wb') as out:
    for index,c in enumerate(chunks):
     ctx=context(t,c,w,data,store);p=store.media_path(data['media'][c['media_id']]);info=wav_info(p)
     if params is None:params=(info['channels'],info['rate']);out.setnchannels(params[0]);out.setsampwidth(2);out.setframerate(params[1])
     if params!=(info['channels'],info['rate']):raise Problem('WAVのチャンネル数・サンプルレートが異なります。同じTTS設定で再生成してください。')
     if index:
      left=round(audio(t).get('chunk_gap_ms',20)/1000*params[1])
      while left:n=min(left,params[1]);out.writeframesraw(b'\0'*(n*params[0]*2));left-=n
     for g in gaps:
      if (index==0 and g['after'] is None) or index and g['after']==chunks[index-1]['id']:
       left=round(g['seconds']*params[1]);block=b'\0'*(min(left,params[1])*params[0]*2)
       while left:n=min(left,params[1]);out.writeframesraw(block[:n*params[0]*2]);left-=n
     with wave.open(str(p),'rb') as f:
      while True:
       raw=f.readframes(65536)
       if not raw:break
       values=array.array('h');values.frombytes(raw);out.writeframesraw(array.array('h',(max(-32768,min(32767,round(x*ctx['gain']))) for x in values)).tobytes())
    for g in gaps:
     if chunks and g['after']==chunks[-1]['id']:
      left=round(g['seconds']*params[1])
      while left:n=min(left,params[1]);out.writeframesraw(b'\0'*(n*params[0]*2));left-=n
   info=wav_info(dest);data['media'][mid]=dict(path='media/'+dest.name,filename='track-'+str(t['number'])+'.wav',mime='audio/wav',kind='track_export',work_id=wid,track_id=tid,created_at=now(),seconds=info['seconds']);old=audio(t).get('export_id');audio(t)['export_id']=mid;store.commit(data,dict(action='audio_export',work_id=wid,track_id=tid),delete_media=[old] if old else []);return dict(media_id=mid,seconds=info['seconds'])
  except Exception:dest.unlink(missing_ok=True);raise
