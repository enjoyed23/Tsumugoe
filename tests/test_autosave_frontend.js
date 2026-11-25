const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/autosave.js','utf8'),app=fs.readFileSync('web/app.js','utf8'),cg=fs.readFileSync('web/cg.js','utf8');
const forms=new Map(),drafts=new Map(),requests=[];let failure=null,hook=null;
const ctx=vm.createContext({console,setTimeout,clearTimeout,Promise,Map,Object,Number,JSON,Error,Array,db:{revision:1},route:'works',drafts,document:{activeElement:null},history:{replaceState(){}},config:{tts:{},comfyui:{}},actor:()=>null,voice:()=>({references:[],confirmed_reference_id:null}),parseObject:(s)=>JSON.parse(s),draftKey:(...x)=>JSON.stringify(x),capture:n=>({...n.values}),feedback:(m,s)=>{m.textContent=s},dirtyStatus(){},report(){},render(){},storedRecord:()=>null,clone:x=>x,refresh:async()=>{ctx.db.revision++},request:async(path,body)=>{requests.push({path,body});if(hook)await hook();if(failure)throw failure;return {id:body.record?.id||'new-id'}},mark(){}});vm.runInContext(source,ctx);
const run=s=>vm.runInContext(s,ctx);function form(kind,id,where,values){const n={_identity:[kind,id,where],dataset:{key:JSON.stringify([kind,id,where])},values:{...values},isConnected:false,message:{},querySelector(){return this.message}};ctx.autoRegister(n);drafts.set(n.dataset.key,{values:n.values});return n}
(async()=>{
 const n=form('reading-new',null,'w',{text:'検証',reading:''});await ctx.autoEnqueue(n);assert.equal(n._identity[0],'reading');assert.equal(n._identity[1],'new-id');assert.equal(drafts.size,0);
 n.values.reading='けんしょう';drafts.set(n.dataset.key,{});await ctx.autoEnqueue(n);assert.equal(requests.at(-1).body.record.id,'new-id');
 failure=Error('表記を確認してください');n.values.reading='更新';drafts.set(n.dataset.key,{});await ctx.autoEnqueue(n);assert.ok(drafts.has(n.dataset.key));assert.match(n.message.textContent,/表記を確認/);failure=null;
 let release;hook=()=>new Promise(r=>{release=r});const pending=ctx.autoEnqueue(n);await Promise.resolve();n.values.reading='さらに更新';release();hook=null;await pending;assert.ok(drafts.has(n.dataset.key));await new Promise(r=>setTimeout(r,25));assert.equal(drafts.size,0);assert.equal(requests.at(-1).body.record.reading,'さらに更新');
 const actor=form('actors',null,null,{name:'検証',voice_ids:'[]',appearance_notes:'',trigger_word:''});await ctx.autoFlush(actor);assert.equal(actor._identity[1],'new-id');assert.equal(drafts.size,0);
 const w=form('works',null,null,{title:'',settings:'{}'});assert.equal(ctx.autoPayload(w,w.values).body.record.title,'');
 assert.ok(!app.includes("if(drafts.size)return"));assert.ok(!app.includes("addEventListener('beforeunload'"));assert.ok(!cg.includes('disabled=drafts.has'));
 const actions=app.slice(app.indexOf('function formActions'),app.indexOf('function value('));assert.ok(!actions.includes("action("));assert.ok(actions.includes('data')||actions.includes('dataset'));
 console.log('Autosave: stable new identity, sequential edits, retained failures, in-flight edits, file-first creation and nonblocking navigation: OK');
})().catch(e=>{console.error(e);process.exitCode=1});
