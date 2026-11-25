"""Track-owned CG records and pure legacy migration; no unit affiliation."""
import copy
from model import Problem

def block_part(key):return key.rsplit('-',1)[0] if '-' in key else key

def migrate(data):
 changed=False
 for w in data['works']:
  for t in w.get('tracks',[]):
   if 'cgs' not in t:t['cgs']=[];changed=True
   used={r['id'] for r in t['cgs']}
   for u in t.get('units',[]):
    if 'cg' not in u:continue
    old=u.pop('cg');changed=True
    if not old:continue
    key=u['id'];base=key;n=2
    while key in used:key=base+'~'+str(n);n+=1
    row=copy.deepcopy(old);row.pop('unit',None);row['id']=key;row['block']=block_part(u['id']);
    if 'character_id' not in row and u.get('speaker'):row['character_id']=u['speaker']
    used.add(key);t['cgs'].append(row)
   assigned=set()
   for r in t['cgs']:
    bid=r.get('block') if 'start_unit' not in r else None
    if bid and bid in assigned:r['block']=None;r['timing_note']='旧データで表示先Blockが重複していたため未設定に移行';changed=True
    elif bid:assigned.add(bid)
   for m in data.get('media',{}).values():
    if m.get('kind')=='cg' and m.get('track_id')==t['id'] and 'unit_id' in m:
     m.setdefault('cg_id',m.pop('unit_id'));changed=True
 return changed

def timing_unit(t,r):
 if 'start_unit' in r:return r['start_unit']
 return next((u['id'] for u in t['units'] if u['block']==r.get('block')),None)

def timing_checks(t):
 ids={u['id'] for u in t['units']};out={}
 for r in t.get('cgs',[]):
  target=timing_unit(t,r)
  if not target:out[r['id']]='表示タイミングが未設定です。CG編集でユニットを選んでください。'
  elif target not in ids:out[r['id']]='表示先ユニットがありません。CG編集で選び直してください。'
 return out

def at_block(t,bid):
 matches=[r for r in t.get('cgs',[]) if r.get('block')==bid and 'start_unit' not in r]
 return matches[-1] if matches else None

def validate_timings(t):
 seen={}
 for r in t.get('cgs',[]):
  target=timing_unit(t,r)
  key=('unit',target) if target else ('block',r.get('block')) if 'start_unit' not in r and r.get('block') else None
  if key is None:continue
  if key in seen:raise Problem('同じ表示開始ユニットに指定できるCGは1件です。表示先を変更してください。',[target or r.get('block'),seen[key],r['id']])
  seen[key]=r['id']
