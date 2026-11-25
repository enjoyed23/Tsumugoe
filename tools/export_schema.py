"""Generate the pilot input schema from the application field model."""
import json,sys
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE))
from model import SCHEMA

def convert(form):
 if form=='string|null':return {'type':['string','null']}
 if form=='string':return {'type':'string'}
 if form=='object':return {'type':'object','additionalProperties':True}
 if form=='array<string>':return {'type':'array','items':{'type':'string'}}
 if form=='array<object>':return {'type':'array','items':{'type':'object','additionalProperties':True}}
 return {'type':'array','items':{'$ref':'#/$defs/'+{'array<character>':'character','array<reading>':'reading'}[form]}}

def record(kind):
 properties={k:convert(v) for k,v in SCHEMA[kind].items()}
 properties['id']={'type':['string','null'],'minLength':1,'description':'省略またはnullは新規登録。同じIDのみ更新。表示名では照合しません。'}
 return {'type':'object','properties':properties,'additionalProperties':True}
defs={k:record(k) for k in SCHEMA}
defs['actors']['anyOf']=[{'required':['name']},{'required':['id']}]
defs['voices']['anyOf']=[{'required':['name']},{'required':['id']}]
defs['works']['anyOf']=[{'required':['title']},{'required':['id']}]
defs['reading']['required']=['text']
defs['character']['properties']['readings']={'type':'array','items':{'$ref':'#/$defs/reading'},'description':'作品の読み辞書へ投入。キャラクターに別の辞書は作りません。'}
defs['character']['properties']['names']={'type':'object','properties':{'full':{'type':'string'},'family':{'type':'string'},'given':{'type':'string'},'aliases':{'type':'array','items':{'type':'string'}}},'additionalProperties':True}
defs['voices']['properties']['references']={'type':'array','items':{'type':'object','required':['id'],'properties':{'id':{'type':'string','minLength':1},'media_id':{'type':['string','null']},'name':{'type':'string'},'notes':{'type':'string'},'source_text':{'type':'string'},'created_at':{'type':'string'}},'additionalProperties':True}}
schema={'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'urn:tsumugoe:input:v0.1','title':'つむごえ v0.1 取り込み型','type':'object','properties':{k:{'type':'array','items':{'$ref':'#/$defs/'+k}} for k in ('actors','voices','works')},'additionalProperties':True,'$defs':defs}
schema['properties'].update({'characters':{'type':'array','items':{'$ref':'#/$defs/character'}},'readings':{'type':'array','items':{'$ref':'#/$defs/reading'}},'work_id':{'type':['string','null']}})
(BASE/'schemas/v0.1.schema.json').write_text(json.dumps(schema,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':print('schemas/v0.1.schema.json')
