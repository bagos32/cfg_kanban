/* Executes the shared scanner/touch controller with offline RPC/storage/lock doubles. */
const assert = require('node:assert/strict');
const {createController,pendingKey}=require('../public/js/container_repack.js');
const fs=require('node:fs'),path=require('node:path');
let checks=0;
function fixture(shared) {
 const map=shared?.map||new Map(), calls=[];let owner='EMP',nonce=0,closed=0,success=0,fail=null;
 const source={name:'S',visible_code:'TAG1',qty:10,available_qty:10,stock_uom:'Kg',item_code:'PRODUCT',batch_no:'BATCH'};
 const target={...source,name:'D',visible_code:'TAG2',qty:5};
 const env={storage:{getItem:k=>map.get(k)||null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k)},
 locks:shared?.locks||{request:async(k,fn)=>fn()},owner:()=>owner,nonce:()=>`event-${++nonce}`,
 render(){},close(){closed++;},async success(){success++;},async rpc(method,args){
  calls.push({method,args:structuredClone(args)});
  if(method==='repack_source_context')return {options:[source]};
  if(method==='repack_destination_context')return {destination:'B',visible_code:'BIN2',role:'Logistics Container',options:args.destination_scan==='EMPTY'?[]:[target],new_tag_allowed:args.destination_scan==='EMPTY'};
  if(method==='repack_new_tag_context')return {visible_code:args.new_tag};
  if(fail)throw fail;
  return {destination_stock:'D',destination_qty:8};
 }};
 const c=createController(env);
 return {c,env,calls,map,source,target,owner:value=>{owner=value;},failure:value=>{fail=value;},closed:()=>closed,success:()=>success};
}
async function ready(f){await f.c.source('TAG1');f.c.quantity(3);await f.c.destination('BIN2');f.c.reason('Repack');}
async function test(name,fn){await fn();checks++;console.log(`ok ${name}`);}
(async()=>{
 await test('scanner sequence selects existing tag and combines quantity',async()=>{
  const f=fixture();await f.c.scan('TAG1');await f.c.scan('CFG:QTY:MATERIAL:3');await f.c.scan('BIN2');await f.c.scan('Physical repack');await f.c.scan('CFG:CMD:CONFIRM');
  const args=f.calls.at(-1).args;assert.equal(args.destination_stock,'D');assert.equal(args.new_tag,null);assert.equal(args.qty,3);assert.equal(f.success(),1);assert(!f.map.has(pendingKey));
 });
 await test('touch and scanner share payload',async()=>{const f=fixture();await ready(f);await f.c.confirm();assert.equal(f.calls.at(-1).args.reason,'Repack');assert.equal(f.calls.at(-1).args.destination_stock,'D');});
 await test('repeated/queued confirmation after success creates only one move',async()=>{const f=fixture();await ready(f);await Promise.all([f.c.confirm(),f.c.confirm()]);await f.c.confirm();assert.equal(f.calls.filter(x=>x.method==='move_container_stock').length,1);});
 await test('empty destination optional preprinted tag is explicitly armed',async()=>{const f=fixture();await f.c.scan('TAG1');await f.c.scan('CFG:QTY:MATERIAL:3');await f.c.scan('EMPTY');await f.c.scan('CFG:CMD:REPACK_NEW_TAG');await f.c.scan('NEW001');await f.c.scan('Physical repack');await f.c.confirm();assert.equal(f.calls.at(-1).args.new_tag,'NEW001');});
 await test('loaded destination rejects a new preprinted tag',async()=>{const f=fixture();await ready(f);await assert.rejects(()=>f.c.tag('NEW1'),/only for an empty/);});
 await test('numbered choices use explicit selection and page beyond ten',async()=>{const f=fixture();f.env.rpc=async()=>({options:Array.from({length:12},(_,i)=>({...f.source,name:`S${i}`}))});await f.c.source('BIN1');assert.equal(f.c.state.source,null);await assert.rejects(()=>f.c.scan('OTHER'),/numbered/);await f.c.scan('CFG:CMD:NEXT_MATERIALS');await f.c.scan('CFG:SELECT:2');assert.equal(f.c.state.source.name,'S11');});
 await test('multiple destination choices never silently select',async()=>{const f=fixture();await ready(f);const original=f.env.rpc;f.env.rpc=async(method,args)=>method==='repack_destination_context'?{options:[f.target,{...f.target,name:'D2'}],new_tag_allowed:false}:original(method,args);await f.c.destination('BIN2');await assert.rejects(()=>f.c.confirm(),/select the source and destination/);await f.c.scan('CFG:SELECT:2');assert.equal(f.c.state.target.name,'D2');});
 await test('source correction clears incompatible destination and new tag',async()=>{const f=fixture();await ready(f);await f.c.scan('CFG:CMD:REPACK_SOURCE');await f.c.scan('TAG1');assert.equal(f.c.state.destination,null);assert.equal(f.c.state.newTag,'');});
 await test('quantity increments and reason arm stay scanner operable',async()=>{const f=fixture();await ready(f);await f.c.scan('CFG:QTY:MATERIAL:+2');await f.c.scan('CFG:CMD:REPACK_REASON');await f.c.scan('Another reason');assert.equal(f.c.state.qty,5);assert.equal(f.c.state.reason,'Another reason');});
 await test('lost response persists original request across close and refresh',async()=>{
  const f=fixture();await ready(f);f.failure(new Error('network'));await assert.rejects(()=>f.c.confirm(),/network/);const original=f.calls.at(-1).args;
  assert(f.map.has(pendingKey));await assert.rejects(()=>f.c.source('TAG2'),/Retry the original/);await f.c.scan('CFG:CMD:CANCEL');assert.equal(f.closed(),1);assert(f.map.has(pendingKey));
  const next=fixture({map:f.map});next.c.restore();await next.c.confirm();assert.deepEqual(next.calls.at(-1).args,original);assert(!next.map.has(pendingKey));
 });
 await test('confirmed server rejection allows correction and new identity',async()=>{const f=fixture();await ready(f);f.failure({exc_type:'ValidationError'});await assert.rejects(()=>f.c.confirm());assert(!f.map.has(pendingKey));f.c.quantity(2);f.failure(null);await f.c.confirm();assert.equal(f.calls.at(-1).args.qty,2);assert.equal(f.calls.at(-1).args.event_token,'event-2');});
 await test('another operator cannot reconcile original pending move',async()=>{const f=fixture();await ready(f);f.failure(new Error('network'));await assert.rejects(()=>f.c.confirm());f.owner('OTHER');await assert.rejects(()=>f.c.confirm(),/original operator/);assert.equal(f.calls.filter(x=>x.method==='move_container_stock').length,1);});
 await test('another tab cannot overwrite pending move',async()=>{const f=fixture(),other=fixture({map:f.map});await ready(f);await ready(other);f.failure(new Error('network'));await assert.rejects(()=>f.c.confirm());await assert.rejects(()=>other.c.confirm(),/Another move/);assert.equal(other.calls.filter(x=>x.method==='move_container_stock').length,0);});
 await test('tab holding reconciled pending must reopen instead of sending fresh action',async()=>{const f=fixture();await ready(f);f.failure(new Error('network'));await assert.rejects(()=>f.c.confirm());const other=fixture({map:f.map});other.c.restore();await other.c.confirm();await assert.rejects(()=>f.c.confirm(),/reconciled in another tab/);});
 await test('storage failure blocks RPC before posting',async()=>{const f=fixture();await ready(f);f.env.storage.setItem=()=>{throw new Error('storage blocked');};await assert.rejects(()=>f.c.confirm(),/storage blocked/);assert.equal(f.calls.filter(x=>x.method==='move_container_stock').length,0);});
 await test('missing Web Locks blocks submission',async()=>{const f=fixture();await ready(f);f.env.locks=null;await assert.rejects(()=>f.c.confirm(),/Web Locks/);});
 await test('corrupt pending slot fails closed',async()=>{const f=fixture();f.map.set(pendingKey,'bad json');assert.throws(()=>f.c.restore(),/unreadable/);});
 await test('cancelled dialog cannot post queued confirmation',async()=>{const f=fixture();await ready(f);await f.c.scan('CFG:CMD:CANCEL');await f.c.confirm();assert.equal(f.calls.filter(x=>x.method==='move_container_stock').length,0);});
 await test('invalid/excessive quantity and missing reason cannot post',async()=>{const f=fixture();await ready(f);assert.throws(()=>f.c.quantity('nan'));f.c.quantity(11);await assert.rejects(()=>f.c.confirm(),/within available/);f.c.quantity(3);f.c.reason('');await assert.rejects(()=>f.c.confirm(),/reason/);assert.equal(f.calls.filter(x=>x.method==='move_container_stock').length,0);});
 await test('global routing, catalogue, help, focus and production Return guard ship together',async()=>{
  const root=path.resolve(__dirname,'..');const logistics=fs.readFileSync(path.join(root,'cfg_kanban/page/kanban_logistics/kanban_logistics.js'),'utf8'),production=fs.readFileSync(path.join(root,'cfg_kanban/page/kanban_operator/kanban_operator.js'),'utf8'),catalog=fs.readFileSync(path.join(root,'api/operator.py'),'utf8'),ui=fs.readFileSync(path.join(root,'public/js/container_repack.js'),'utf8');
  for(const command of ['MOVE_CONTAINER_STOCK','REPACK_SOURCE','REPACK_DESTINATION','REPACK_NEW_TAG','REPACK_REASON'])assert(catalog.includes(`CFG:CMD:${command}`));
  assert(production.includes('MOVE_CONTAINER_STOCK:'));assert(production.includes('cfg_open_container_repack'));assert(logistics.includes('raw.toUpperCase() === "CFG:CMD:MOVE_CONTAINER_STOCK"'));assert(logistics.includes('active_repack.scan(raw)'));
  assert(logistics.includes('is_quantity_bin && row.virtual_content && row.return_to_source_supported ?'));assert(logistics.includes('repack_scanner_help'));assert(ui.includes('hidden.bs.modal'));assert(ui.includes('.finally(focus)'));
 });
 await test('real dialog adapter binds touch inputs and restores scanner focus after success',async()=>{
  const vm=require('node:vm');const f=fixture();let focused=0,hidden=0,created;
  const button={prop(){return this;}};
  class Dialog {
   constructor(config){created=this;this.config=config;this.values={};this.visible=false;this.events={};this.fields_dict={};
    for(const field of config.fields){const handlers={};const input={on:(event,callback)=>{handlers[event]=callback;return input;},trigger:(event)=>{if(event==='focus')focused++;return input;}};
     this.fields_dict[field.fieldname]={$input:input,handlers,$wrapper:{html(value){this.value=value;return this;},find(){return {on(){}};}}};}
    this.$wrapper={is:()=>this.visible,on:(event,callback)=>{this.events[event]=callback;}};
   }
   set_df_property(){}get_primary_btn(){return button;}get_value(name){return this.values[name];}set_value(name,value){this.values[name]=value;}
   show(){this.visible=true;}hide(){this.visible=false;this.events['hidden.bs.modal']?.();}
  }
  const module={exports:{}};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../public/js/container_repack.js'),'utf8'),{module,localStorage:f.env.storage,navigator:{locks:f.env.locks}});
  const handle=await module.exports.open({frappe:{utils:{escape_html:value=>String(value??'').replaceAll('<','&lt;')},ui:{Dialog},call:({method,args})=>f.env.rpc(method.split('.').at(-1),args).then(message=>({message}))},owner:f.env.owner,nonce:f.env.nonce,token:()=> 'SESSION',success:async()=>{},onClose:()=>{hidden++;},errorMessage:(error,fallback)=>error.message||fallback});
  created.values.source_scan='TAG1';await created.fields_dict.read_source.handlers.click();
  created.values.qty=3;await created.fields_dict.set_quantity.handlers.click();
  created.values.destination_scan='BIN2';await created.fields_dict.read_destination.handlers.click();
  created.values.reason='Touch repack';await created.fields_dict.set_reason.handlers.click();
  assert(created.fields_dict.summary.$wrapper.value.includes('Combined total: 8'));
  await created.config.primary_action();assert.equal(hidden,1);assert(focused>=4);assert.equal(handle.controller.state.completed,true);
  assert.equal(f.calls.at(-1).args.operator_session_token,'SESSION');
 });
 console.log(`${checks} container repack UI checks passed`);
})().catch(error=>{console.error(error);process.exitCode=1;});
