/* Executes actual scanner/touch controller and dialog with offline doubles. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {createController}=require('../public/js/stock_isolation.js');
let checks=0;
function fixture(action=null){
 let failure=null,success=0,closed=0,count=0;
 const target={name:'TAG',visible_code:'TAG1',scope:'Stock Tag / Fill',item_code:'RAW',batch_no:null,qty:3,stock_uom:'Kg',excluded:0,reason:''};
 const context={source_scan:'TAG1',signature:'SNAPSHOT',targets:[target]},calls=[];
 const env={render(){},nonce:()=>`event-${++count}`,close(){closed++;},success:async()=>{success++;},rpc:async(method,args)=>{
  calls.push({method,args:structuredClone(args)});if(method==='get_rotation_isolation_context')return structuredClone(context);if(failure)throw failure;return {source_scan:'TAG1',excluded:args.excluded};
 }};
 return {c:createController(env,action),env,context,target,calls,failure:value=>{failure=value;},success:()=>success,closed:()=>closed};
}
async function ready(f){await f.c.source('TAG1');f.c.action(1);f.c.reason('Set aside');}
async function test(name,fn){await fn();checks++;console.log(`ok ${name}`);}
(async()=>{
 await test('nonbatch stock isolates through scanner commands',async()=>{const f=fixture();await f.c.scan('CFG:CMD:ISOLATE_STOCK');await f.c.scan('TAG1');await f.c.scan('Set aside');await f.c.scan('CFG:CMD:CONFIRM');const args=f.calls.at(-1).args;assert.equal(args.target_name,'TAG');assert.equal(args.excluded,1);assert.equal(args.context_signature,'SNAPSHOT');assert.equal(f.success(),1);});
 await test('release can be selected globally before source',async()=>{const f=fixture(0);await f.c.scan('TAG1');await f.c.scan('Available again');await f.c.confirm();assert.equal(f.calls.at(-1).args.excluded,0);});
 await test('loaded bin requires exact numbered target, not an implicit fill',async()=>{const f=fixture(1);f.context.targets=[{...f.target,name:'BIN',scope:'Bin (current and future loads)'},f.target];await f.c.source('BIN1');assert.equal(f.c.state.target,null);f.c.reason('Whole bin');await assert.rejects(()=>f.c.confirm(),/exact tag\/bin/);await f.c.scan('CFG:SELECT:1');await f.c.confirm();assert.equal(f.calls.at(-1).args.target_name,'BIN');});
 await test('individual fill choice changes that fill rather than permanent bin',async()=>{const f=fixture(1);f.context.targets=[{...f.target,name:'BIN'},f.target];await f.c.source('BIN1');await f.c.scan('CFG:SELECT:2');await f.c.scan('Only this fill');await f.c.confirm();assert.equal(f.calls.at(-1).args.target_name,'TAG');});
 await test('target paging uses standard selection one through ten',async()=>{const f=fixture();f.context.targets=Array.from({length:12},(_,i)=>({...f.target,name:`FILL${i}`}));await f.c.source('BIN1');await f.c.scan('CFG:CMD:NEXT_MATERIALS');await f.c.scan('CFG:SELECT:2');assert.equal(f.c.state.target.name,'FILL11');await f.c.scan('CFG:CMD:PREVIOUS_MATERIALS');await f.c.scan('CFG:SELECT:1');assert.equal(f.c.state.target.name,'FILL0');});
 await test('source can be rearmed without treating physical identity as a reason',async()=>{const f=fixture();await ready(f);await f.c.scan('CFG:CMD:ISOLATION_SOURCE');await f.c.scan('TAG2');assert.equal(f.calls.at(-1).args.scan_value,'TAG2');});
 await test('missing action or reason never posts',async()=>{const f=fixture();await f.c.source('TAG1');await assert.rejects(()=>f.c.confirm(),/Isolate or Release/);f.c.action(1);await assert.rejects(()=>f.c.confirm(),/reason/);assert.equal(f.calls.filter(row=>row.method==='set_rotation_isolation').length,0);});
 await test('lost response freezes payload and retries original token',async()=>{const f=fixture();await ready(f);f.failure(new Error('network'));await assert.rejects(()=>f.c.confirm(),/network/);const original=f.calls.at(-1).args;assert.throws(()=>f.c.action(0),/original/);assert.throws(()=>f.c.reason('Changed'),/original/);f.failure(null);await f.c.confirm();assert.deepEqual(f.calls.at(-1).args,original);});
 await test('confirmed rejection permits corrections with a new token',async()=>{const f=fixture();await ready(f);f.failure({exc_type:'ValidationError'});await assert.rejects(()=>f.c.confirm());f.c.action(0);f.c.reason('Now available');f.failure(null);await f.c.confirm();assert.equal(f.calls.at(-1).args.event_token,'event-2');assert.equal(f.calls.at(-1).args.excluded,0);});
 await test('double confirmation and cancellation cannot post another action',async()=>{const f=fixture();await ready(f);await Promise.all([f.c.confirm(),f.c.confirm()]);await f.c.confirm();assert.equal(f.calls.filter(row=>row.method==='set_rotation_isolation').length,1);const next=fixture();await ready(next);await next.c.scan('CFG:CMD:CANCEL');await next.c.confirm();assert.equal(next.closed(),1);assert.equal(next.calls.filter(row=>row.method==='set_rotation_isolation').length,0);});
 await test('cancel after unknown response is available for rereading current state',async()=>{const f=fixture();await ready(f);f.failure(new Error('network'));await assert.rejects(()=>f.c.confirm());await f.c.scan('CFG:CMD:CANCEL');assert.equal(f.closed(),1);});
 await test('global dispatch, catalogue, help, form action and guard share the feature',async()=>{
  const root=path.resolve(__dirname,'..');const logistics=fs.readFileSync(path.join(root,'cfg_kanban/page/kanban_logistics/kanban_logistics.js'),'utf8'),production=fs.readFileSync(path.join(root,'cfg_kanban/page/kanban_operator/kanban_operator.js'),'utf8'),catalog=fs.readFileSync(path.join(root,'api/operator.py'),'utf8'),form=fs.readFileSync(path.join(root,'public/js/cfg_kanban_handling_unit.js'),'utf8'),manual=fs.readFileSync(path.join(root,'../docs/USER_MANUAL.md'),'utf8');
  for(const command of ['STOCK_ISOLATION','ISOLATE_STOCK','RELEASE_STOCK','ISOLATION_SOURCE'])assert(catalog.includes(`CFG:CMD:${command}`));
  for(const command of ['STOCK_ISOLATION','ISOLATE_STOCK','RELEASE_STOCK']){assert(production.includes(command+':'));assert(logistics.includes(`raw.toUpperCase() === "CFG:CMD:${command}"`));}
  assert(logistics.includes('active_isolation.scan(raw)'));assert(logistics.includes('active_isolation.focus()'));assert(production.includes('Bin rules cover current/future loads'));assert(form.includes('cfg_stock_isolation.open'));assert(manual.includes('future loads until explicitly released'));
 });
 await test('real dialog touch adapter shows independent rules and restores focus',async()=>{
  const f=fixture(),mod={exports:{}};let created,focused=0,hidden=0;
  f.context.targets[0].effective_isolation={rules:[{scope:'Bin',visible_code:'BIN1',reason:'Keep set aside'}]};
  f.context.targets[0].batch_isolation={batch:'BATCH1',reason:'Independent Batch rule'};
  class Dialog{
   constructor(config){created=this;this.config=config;this.fields_dict={};this.values={};this.visible=false;this.events={};
    for(const field of config.fields){const handlers={};const input={on:(event,callback)=>{handlers[event]=callback;return input;},trigger:()=>{focused++;return input;}};this.fields_dict[field.fieldname]={handlers,$input:input,$wrapper:{html(value){this.value=value;return this;},find(){return {on(){}};}}};}
    this.$wrapper={is:()=>this.visible,on:(event,callback)=>{this.events[event]=callback;}};
   }
   set_df_property(){}get_primary_btn(){return {prop(){}};}get_value(name){return this.values[name];}set_value(name,value){this.values[name]=value;}show(){this.visible=true;}hide(){this.visible=false;this.events['hidden.bs.modal']?.();}
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../public/js/stock_isolation.js'),'utf8'),{module:mod});
  const handle=await mod.exports.open({frappe:{utils:{escape_html:value=>String(value??'').replaceAll('<','&lt;')},ui:{Dialog},call:({method,args})=>f.env.rpc(method.split('.').at(-1),args).then(message=>({message}))},token:()=> 'SUPERVISOR',nonce:f.env.nonce,errorMessage:(error,fallback)=>error.message||fallback,onClose:()=>{hidden++;},success:async()=>{}});
  created.values.source='TAG1';await created.fields_dict.read_source.handlers.click();await created.fields_dict.release.handlers.click();created.values.reason='Release tag only';await created.fields_dict.set_reason.handlers.click();
  assert(created.fields_dict.summary.$wrapper.value.includes('Batch ISOLATED: BATCH1'));assert(created.fields_dict.summary.$wrapper.value.includes('Bin BIN1'));
  await created.config.primary_action();assert.equal(handle.controller.state.done,true);assert.equal(f.calls.at(-1).args.excluded,0);assert.equal(f.calls.at(-1).args.operator_session_token,'SUPERVISOR');assert.equal(hidden,1);assert(focused>=3);
 });
 console.log(`${checks} stock isolation UI checks passed`);
})().catch(error=>{console.error(error);process.exitCode=1;});
