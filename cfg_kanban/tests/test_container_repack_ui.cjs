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
function dialogFixture(options={}) {
 const vm=require('node:vm'),f=fixture(options.shared);let focused=0,hidden=0,created;
 class Dialog {
  constructor(config){created=this;this.config=config;this.values={};this.visible=false;this.events={};this.fields_dict={};
   for(const definition of config.fields){
    const control={df:{...definition},handlers:{},$wrapper:{html(value){this.value=value;return this;},find(){return {on(){}};}}};
    control.make_input=()=>{if(control.$input || control.df.hidden || control.df.fieldtype==='HTML')return;
     const input={on:(event,callback)=>{control.handlers[event]=callback;return input;},trigger:(event)=>{if(event==='focus')focused++;return input;}};
     control.$input=input;
    };
    control.click=()=>{assert(control.$input && !control.df.hidden,'touch requires a visible button');return control.df.click?control.df.click():control.handlers.click?.();};
    control.make_input();this.fields_dict[definition.fieldname]=control;
   }
   this.initiallyHidden=Object.keys(this.fields_dict).filter(name=>!this.fields_dict[name].$input);
   this.$wrapper={is:()=>this.visible,on:(event,callback)=>{this.events[event]=callback;}};
  }
  set_df_property(name,key,value){const field=this.fields_dict[name];field.df[key]=value;if(key==='hidden')field.make_input();}
  get_primary_btn(){return {prop(){return this;}};}
  get_value(name){return this.values[name];}set_value(name,value){this.values[name]=value;}
  show(){this.visible=true;}hide(){this.visible=false;this.events['hidden.bs.modal']?.();}
 }
 const module={exports:{}};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../public/js/container_repack.js'),'utf8'),{module,localStorage:f.env.storage,navigator:{locks:f.env.locks}});
 const open=()=>module.exports.open({frappe:{utils:{escape_html:value=>String(value??'').replaceAll('<','&lt;')},ui:{Dialog},call:({method,args})=>f.env.rpc(method.split('.').at(-1),args).then(message=>({message}))},sourceScan:options.sourceScan,owner:f.env.owner,nonce:f.env.nonce,token:()=> 'SESSION',success:async()=>{},onClose:()=>{hidden++;},errorMessage:(error,fallback)=>error.message||fallback});
 return {...f,open,dialog:()=>created,focused:()=>focused,hidden:()=>hidden};
}
function scannerKey(dialog,value,key='Tab',extra={}) {
 dialog.values.scan=value;let prevented=0,stopped=0;
 const event={key,preventDefault(){prevented++;},stopPropagation(){stopped++;},...extra};
 const result=dialog.fields_dict.scan.handlers.keydown(event);
 return {result,prevented:()=>prevented,stopped:()=>stopped};
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
  const f=dialogFixture(),handle=await f.open(),created=f.dialog();
  created.values.source_scan='TAG1';await created.fields_dict.read_source.click();
  created.values.qty=3;await created.fields_dict.set_quantity.click();
  created.values.destination_scan='BIN2';await created.fields_dict.read_destination.click();
  created.values.reason='Touch repack';await created.fields_dict.set_reason.click();
  assert(created.fields_dict.summary.$wrapper.value.includes('Combined total: 8'));
  await created.config.primary_action();assert.equal(f.hidden(),1);assert(f.focused()>=4);assert.equal(handle.controller.state.completed,true);
  assert.equal(f.calls.at(-1).args.operator_session_token,'SESSION');
 });
 await test('production-bin entry opens with no input for initially hidden new-tag controls',async()=>{
  const f=dialogFixture({sourceScan:'PRODUCTION-BIN'});f.source.visible_code='PRODUCTION-BIN';
  const handle=await f.open(),dialog=f.dialog();
  assert(dialog.initiallyHidden.includes('read_tag'));assert(dialog.initiallyHidden.includes('new_tag'));
  assert.equal(dialog.fields_dict.read_tag.$input,undefined);assert.equal(dialog.fields_dict.new_tag.$input,undefined);
  assert.equal(f.calls[0].method,'repack_source_context');assert.equal(f.calls[0].args.source_scan,'PRODUCTION-BIN');
  assert.equal(handle.controller.state.source.name,'S');assert(dialog.visible);assert(f.focused()>0);
  assert(!f.calls.some(call=>call.method==='move_container_stock'));
 });
 await test('new-tag touch callback works after hidden button is created and shown again',async()=>{
  const f=dialogFixture({sourceScan:'BIN1'}),handle=await f.open(),d=f.dialog();
  d.values.qty=3;await d.fields_dict.set_quantity.click();
  d.values.destination_scan='EMPTY';await d.fields_dict.read_destination.click();
  assert(d.fields_dict.read_tag.$input);assert(!d.fields_dict.read_tag.df.hidden);
  d.values.new_tag='NEW001';await d.fields_dict.read_tag.click();assert.equal(handle.controller.state.newTag,'NEW001');
  d.values.destination_scan='BIN2';await d.fields_dict.read_destination.click();assert(d.fields_dict.read_tag.df.hidden);
  d.values.destination_scan='EMPTY';await d.fields_dict.read_destination.click();
  d.values.new_tag='NEW002';await d.fields_dict.read_tag.click();
  assert.equal(f.calls.filter(call=>call.method==='repack_new_tag_context').length,2);
  d.values.new_tag='';await d.fields_dict.read_tag.click();assert.equal(handle.controller.state.newTag,'');
  d.values.new_tag='NEW002';await d.fields_dict.read_tag.click();
  d.values.reason='Partial bin repack';await d.fields_dict.set_reason.click();await d.config.primary_action();
  assert.equal(f.calls.at(-1).args.new_tag,'NEW002');assert.equal(f.calls.at(-1).args.qty,3);
  assert.equal(f.calls.filter(call=>call.method==='move_container_stock').length,1);
 });
 await test('same dialog remains fully scanner operable with initially hidden buttons',async()=>{
  const f=dialogFixture({sourceScan:'BIN1'}),handle=await f.open();
  await handle.scan('CFG:QTY:MATERIAL:3');await handle.scan('EMPTY');await handle.scan('CFG:CMD:REPACK_NEW_TAG');
  await handle.scan('NEW001');await handle.scan('Physical move');await handle.scan('CFG:CMD:CONFIRM');
  assert.equal(f.calls.at(-1).args.new_tag,'NEW001');assert.equal(f.calls.at(-1).args.operator_session_token,'SESSION');
  assert.equal(handle.controller.state.completed,true);assert.equal(f.hidden(),1);
 });
 await test('source rejection keeps dialog open with inline error and restores focus for correction or cancel',async()=>{
  const f=dialogFixture({sourceScan:'BIN1'}),original=f.env.rpc;
  f.env.rpc=async(method,args)=>{if(method==='repack_source_context')throw new Error('Release the source reservation');return original(method,args);};
  const handle=await f.open(),d=f.dialog();assert(d.visible);assert(f.focused()>0);
  assert(d.fields_dict.summary.$wrapper.value.includes('Release the source reservation'));assert.equal(handle.controller.state.source,null);
  f.env.rpc=original;d.values.source_scan='TAG1';await d.fields_dict.read_source.click();assert.equal(handle.controller.state.source.name,'S');
  await d.config.secondary_action();assert(!d.visible);assert.equal(f.hidden(),1);
  assert(!f.calls.some(call=>call.method==='move_container_stock'));
 });
 await test('reopening hidden-button dialog restores unknown move before a new source is read',async()=>{
  const original=fixture();await ready(original);original.failure(new Error('network'));await assert.rejects(()=>original.c.confirm());
  const pending=original.calls.at(-1).args;
  const f=dialogFixture({shared:{map:original.map},sourceScan:'OTHER-BIN'}),handle=await f.open(),d=f.dialog();
  assert(handle.controller.state.pending);assert.equal(f.calls.length,0);assert(d.fields_dict.read_tag.df.hidden);
  assert(d.fields_dict.source_scan.df.read_only);await d.config.primary_action();
  assert.deepEqual({...f.calls.at(-1).args,operator_session_token:undefined},{...pending,operator_session_token:undefined});
  assert(!f.map.has(pendingKey));assert.equal(f.hidden(),1);
 });
 await test('Tab-suffix scanner completes every popup step and keeps focus',async()=>{
  const f=dialogFixture(),handle=await f.open(),d=f.dialog();
  for(const value of ['TAG1','CFG:QTY:MATERIAL:3','EMPTY','CFG:CMD:REPACK_NEW_TAG','NEW001','Physical Tab move']) {
   const key=scannerKey(d,value);await key.result;assert.equal(key.prevented(),1);assert.equal(key.stopped(),1);assert.equal(d.values.scan,'');
  }
  assert(f.focused()>=7);const key=scannerKey(d,'CFG:CMD:CONFIRM');await key.result;
  assert.equal(handle.controller.state.completed,true);assert.equal(f.hidden(),1);
  const posts=f.calls.filter(call=>call.method==='move_container_stock');assert.equal(posts.length,1);
  assert.equal(posts[0].args.new_tag,'NEW001');assert.equal(posts[0].args.qty,3);assert.equal(posts[0].args.reason,'Physical Tab move');
 });
 await test('Enter suffix remains supported without interpreting a trailing blank suffix twice',async()=>{
  const f=dialogFixture(),handle=await f.open(),d=f.dialog();
  for(const value of ['TAG1','CFG:QTY:MATERIAL:3','BIN2','Enter move'])await scannerKey(d,value,'Enter').result;
  const confirm=scannerKey(d,'CFG:CMD:CONFIRM','Tab');
  const extra=scannerKey(d,'','Enter');assert.equal(extra.prevented(),1);await confirm.result;await extra.result;
  assert(handle.controller.state.completed);assert.equal(f.calls.filter(call=>call.method==='move_container_stock').length,1);
 });
 await test('blank and Shift-Tab keep ordinary navigation and composing keys do not submit',async()=>{
  const f=dialogFixture();await f.open();const d=f.dialog();
  for(const [value,key,extra] of [['','Tab',{}],['TAG1','Tab',{shiftKey:true}],['TAG1','Enter',{isComposing:true}],['TAG1','Tab',{ctrlKey:true}],['TAG1','Tab',{altKey:true}],['TAG1','Tab',{metaKey:true}],['TAG1','x',{}]]) {
   const event=scannerKey(d,value,key,extra);await event.result;assert.equal(event.prevented(),0);assert.equal(d.values.scan,value);
  }
  assert.equal(f.calls.length,0);
 });
 await test('rapid Tab scans queue behind source lookup without losing the next payload',async()=>{
  const f=dialogFixture(),original=f.env.rpc;let release;
  f.env.rpc=(method,args)=>method==='repack_source_context'?new Promise(resolve=>{release=()=>resolve({options:[f.source]});}):original(method,args);
  const handle=await f.open(),d=f.dialog();const first=scannerKey(d,'TAG1');
  const qty=scannerKey(d,'CFG:QTY:MATERIAL:3');const dest=scannerKey(d,'BIN2');const reason=scannerKey(d,'Queued move');
  await new Promise(resolve=>setImmediate(resolve));assert(release);release();
  await Promise.all([first.result,qty.result,dest.result,reason.result]);assert.equal(handle.controller.state.qty,3);assert.equal(handle.controller.state.destinationScan,'BIN2');
  assert.equal(handle.controller.state.reason,'Queued move');await scannerKey(d,'CFG:CMD:CONFIRM').result;
  assert.equal(f.calls.filter(call=>call.method==='move_container_stock').length,1);
 });
 await test('Tab source rejection restores scanner focus and permits correction or Tab Cancel',async()=>{
  const f=dialogFixture(),original=f.env.rpc;f.env.rpc=async(method,args)=>{if(method==='repack_source_context')throw new Error('Wrong source warehouse');return original(method,args);};
  await f.open();const d=f.dialog(),before=f.focused();await scannerKey(d,'BAD').result;
  assert(d.visible);assert(f.focused()>before);assert(d.fields_dict.summary.$wrapper.value.includes('Wrong source warehouse'));
  f.env.rpc=original;await scannerKey(d,'TAG1').result;await scannerKey(d,'CFG:CMD:CANCEL').result;
  assert.equal(f.hidden(),1);assert(!f.calls.some(call=>call.method==='move_container_stock'));
 });
 await test('Tab unknown-result retry keeps the original request and token',async()=>{
  const f=dialogFixture();await f.open();const d=f.dialog();
  for(const value of ['TAG1','CFG:QTY:MATERIAL:3','BIN2','Retry move'])await scannerKey(d,value).result;
  f.failure(new Error('network'));await scannerKey(d,'CFG:CMD:CONFIRM').result;
  const original=f.calls.at(-1).args;assert(f.map.has(pendingKey));
  await scannerKey(d,'CFG:QTY:MATERIAL:2').result;f.failure(null);await scannerKey(d,'CFG:CMD:CONFIRM').result;
  assert.deepEqual(f.calls.at(-1).args,original);assert.equal(f.hidden(),1);assert(!f.map.has(pendingKey));
 });
 await test('main Logistics scanner routes Tab to global Move Repack command and keeps blank Tab navigation',async()=>{
  const source=fs.readFileSync(path.join(__dirname,'../cfg_kanban/page/kanban_logistics/kanban_logistics.js'),'utf8');
  const start=source.indexOf('\t$scanner.find(".logistics-scan-input").on("keydown"');
  const end=source.indexOf('\n\t$scanner.find(".camera-scan")',start);assert(start>=0&&end>start);
  let handler,value='',calls=[];const input={on:(name,fn)=>{handler=fn;},val:()=>value};
  new Function('$scanner','process_scan',source.slice(start,end))({find:()=>input},()=>{calls.push(value);value='';});
  const fire=(text,key,extra={})=>{value=text;let prevented=0;handler({key,preventDefault(){prevented++;},stopPropagation(){},...extra});return prevented;};
  assert.equal(fire('CFG:CMD:MOVE_CONTAINER_STOCK','Tab'),1);assert.deepEqual(calls,['CFG:CMD:MOVE_CONTAINER_STOCK']);
  assert.equal(fire('','Tab'),0);assert.equal(fire('','Tab',{shiftKey:true}),0);
  assert.equal(fire('BIN1','Enter'),1);assert.equal(fire('BIN2','Tab',{isComposing:true}),0);
  assert.equal(fire('BIN3','Tab',{shiftKey:true}),0);assert.equal(calls.length,2);
 });
 console.log(`${checks} container repack UI checks passed`);
})().catch(error=>{console.error(error);process.exitCode=1;});
