/* Actual route controller/adapter with storage, Web Lock, RPC, camera and Dialog doubles. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {createController,pendingKey}=require('../public/js/route_delivery.js');let checks=0;
function fixture(options={}){
 const map=options.map||new Map(),lock=options.lock||{tail:Promise.resolve()},calls=[];
 let owner='EMP',nonce=0,failure=null,closed=0,success=0;
 const plan={name:'DPL-ROUTE',state:'Loaded',business_label:'North route',vehicle_reference:'LORRY',
  stop_sequence_policy:'Flexible Order',can_plan_stops:true,can_approve_order:true,stops:[]};
 const tag={source_key:'SOURCE',source_kind:'Prepared Route Stock',item_code:'ITEM',stock_uom:'Nos',available_qty:5,physical_qty:5,visible_code:'TAG'};
 const env={mode:options.mode||'visit',deliverySession:'DELIVERY',owner:()=>owner,openedOwner:'EMP',token:()=> 'SESSION',nonce:()=>`EVENT-${++nonce}`,
  storage:{getItem:key=>map.get(key)||null,setItem:(key,value)=>map.set(key,value),removeItem:key=>map.delete(key)},
  locks:{request(key,work){const promise=lock.tail.then(work);lock.tail=promise.catch(()=>{});return promise;}},
  render(){},close(){closed++;},camera(){},success:async()=>{success++;},rpc:async(method,args)=>{
   calls.push({method,args:structuredClone(args)});
   if(method==='route_context')return {plans:[plan],customer_scan:args.scan_value==='SITE'?'SITE':null,customer_site:args.scan_value==='SITE'?'SITE-ID':null};
   if(method==='route_stock_context'){
    if(args.scan_value==='BIN')return {mode:'container',choices:[{source_key:'container',source_kind:'Full Container',contents:[tag]}]};
    if(args.scan_value==='ITEM'||args.item_code)return {mode:'item',item_code:'ITEM',batch_no:args.batch_no,
     choices:[{...tag,visible_code:null,source_kind:'Prepared Route Stock'},{...tag,source_key:'unassigned',source_kind:'Unassigned Lorry Stock',available_qty:4}]};
    return {mode:'stock_tag',choices:[tag]};
   }
   if(failure)throw failure;return {name:'RESULT',dispatch_plan:plan.name};
  }};
 return {c:createController(env),env,map,lock,calls,plan,tag,owner:value=>{owner=value;},failure:value=>{failure=value;},closed:()=>closed,success:()=>success};
}
async function visit(f){await f.c.scan('DPL-ROUTE');await f.c.scan('SITE');}
async function stock(f){await f.c.scan('TAG');await f.c.scan('CFG:QTY:MATERIAL:2');}
async function test(name,fn){await fn();checks++;console.log('ok '+name);}
function adapter(options={}){
 const f=fixture(options);let dialog,focused=0;const cameras=[];
 class Dialog{
  constructor(config){this.config=config;dialog=this;this.values={};this.fields_dict={};this.properties={};
   for(const field of config.fields)this.fields_dict[field.fieldname]={df:field,$input:{focus(){focused++;},on:(name,callback)=>{this.fields_dict[field.fieldname][name]=callback;}},$wrapper:{html:value=>{this.html=value;},find:()=>({on(){}})}};
  }
  get_value(name){return this.values[name];}set_value(name,value){this.values[name]=value;}show(){}hide(){this.onhide();}
  enable_primary_action(){this.enabled=true;}disable_primary_action(){this.enabled=false;}
  set_df_property(name,key,value){this.properties[name+':'+key]=value;}
 }
 class Camera{
  constructor(config){if(options.cameraError)throw new Error('Camera startup failed');this.config=config;this.visible=true;this.hidden=[];cameras.push(this);this.dialog={$wrapper:{one:(name,fn)=>this.hidden.push(fn)}};}
  hide_dialog(){if(!this.visible)return;this.visible=false;for(const fn of this.hidden.splice(0))fn();}
  decode(value){this.config.on_scan({decodedText:value});this.hide_dialog();}
 }
 const module={exports:{}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../public/js/route_delivery.js'),'utf8'),{module,localStorage:f.env.storage,navigator:{locks:f.env.locks}});
 const launch=()=>module.exports.open({mode:options.mode,planScan:options.planScan,siteScan:options.siteScan,deliverySession:'DELIVERY',
  frappe:{utils:{escape_html:value=>String(value??'').replaceAll('<','&lt;')},ui:{Dialog,...(!options.noCamera?{Scanner:Camera}:{})},
   call:async({method,args})=>({message:await f.env.rpc(method.split('.').at(-1),args)})},
  owner:f.env.owner,token:f.env.token,nonce:f.env.nonce,success:f.env.success,onClose(){},errorMessage:(error,fallback)=>error.message||fallback});
 return {...f,launch,dialog:()=>dialog,cameras,focused:()=>focused};
}
(async()=>{
 await test('flexible visit scans Plan/Site and starts one customer Session',async()=>{const f=fixture();await visit(f);assert(f.c.ready());await f.c.scan('CFG:CMD:CONFIRM');assert.equal(f.calls.at(-1).method,'start_route_stop');assert.equal(f.calls.at(-1).args.customer_scan,'SITE');assert.equal(f.success(),1);});
 await test('validated existing-lorry pool can start its native optional visit without a loading Manifest',async()=>{
  const f=fixture();f.plan.state='Ready for Fulfilment';f.plan.existing_lorry_stock_only=1;await visit(f);assert(f.c.ready());await f.c.confirm();assert.equal(f.calls.at(-1).method,'start_route_stop');
  const invalid=fixture();invalid.plan.state='Ready for Fulfilment';await visit(invalid);assert(!invalid.c.ready());
 });
 await test('several Plans require numbered choice and page beyond ten',async()=>{
  const f=fixture();f.env.rpc=async()=>({plans:Array.from({length:12},(_,i)=>({...f.plan,name:`DPL-${i}`})),customer_scan:'SITE',customer_site:'SITE-ID'});
  await f.c.scan('SITE');assert(!f.c.ready());await f.c.scan('CFG:CMD:NEXT_MATERIALS');await f.c.scan('CFG:SELECT:2');assert.equal(f.c.state.plan.name,'DPL-11');assert(f.c.ready());
 });
 await test('repeated planned visits to one Site require exact numbered Stop',async()=>{
  const f=fixture();f.plan.stops=[1,2].map(n=>({name:`STOP${n}`,state:'Planned',customer_scan_point:'SITE-ID',planned_sequence:n}));
  await visit(f);assert(!f.c.ready());await f.c.scan('CFG:SELECT:2');await f.c.confirm();assert.equal(f.calls.at(-1).args.route_stop,'STOP2');
 });
 await test('strict mode has no ready state for an unplanned Site',async()=>{const f=fixture();f.plan.stop_sequence_policy='Planned Order';await visit(f);assert(!f.c.ready());await assert.rejects(()=>f.c.confirm(),/Complete the route/);assert.equal(f.calls.filter(c=>c.method==='start_route_stop').length,0);});
 await test('adding a planned visit does not require choosing an older duplicate visit',async()=>{
  const f=fixture({mode:'plan'});f.plan.stops=[1,2].map(n=>({name:`STOP${n}`,state:'Planned',customer_scan_point:'SITE-ID'}));
  await visit(f);assert(f.c.ready());await f.c.confirm();assert.equal(f.calls.at(-1).method,'add_route_stop');
 });
 await test('Supervisor approval captures selected Stop and scanner reason',async()=>{
  const f=fixture({mode:'approve'});f.plan.stops=[{name:'STOP',state:'Planned',planned_sequence:2,customer_scan_point:'SITE-ID'}];
  await f.c.scan('DPL-ROUTE');assert(!f.c.ready());await f.c.scan('Customer requested early visit');await f.c.confirm();
  assert.equal(f.calls.at(-1).method,'approve_route_stop_order');assert.equal(f.calls.at(-1).args.reason,'Customer requested early visit');
 });
 await test('Profile with overrides disabled cannot show ready approval',async()=>{const f=fixture({mode:'approve'});f.plan.can_approve_order=false;f.plan.stops=[{name:'STOP',state:'Planned'}];await f.c.scan('DPL-ROUTE');f.c.reason('Urgent');assert(!f.c.ready());});
 await test('prepared tagged source uses scanned identity and declared quantity',async()=>{
  const f=fixture({mode:'stock'});await stock(f);await f.c.confirm();const args=f.calls.at(-1).args;
  assert.equal(args.scan_value,'TAG');assert.equal(args.qty,2);assert.equal(args.source_key,'SOURCE');assert.equal(args.delivery_session,'DELIVERY');
 });
 await test('prepared and unassigned loose stock require explicit source choice',async()=>{
  const f=fixture({mode:'stock'});await f.c.scan('ITEM');await f.c.scan('CFG:QTY:MATERIAL:2');assert(!f.c.ready());
  await f.c.scan('CFG:SELECT:2');await f.c.scan('CFG:QTY:MATERIAL:2');await f.c.confirm();assert.equal(f.calls.at(-1).args.source_key,'unassigned');assert.equal(f.calls.at(-1).args.item_code,'ITEM');
 });
 await test('required Batch is scanned before quantity and origin choice',async()=>{
  const f=fixture({mode:'stock'});const rpc=f.env.rpc;f.env.rpc=async(method,args)=>method==='route_stock_context'&&!args.batch_no?{requires_batch:true,item_code:'ITEM',choices:[]}:rpc(method,args);
  await f.c.scan('ITEM');assert.equal(f.c.state.arm,'batch');await f.c.scan('BATCH-A');await f.c.scan('CFG:SELECT:1');await f.c.scan('CFG:QTY:MATERIAL:2');await f.c.confirm();assert.equal(f.calls.at(-1).args.batch_no,'BATCH-A');
 });
 await test('ordinary full container confirms its whole contents without numeric re-entry',async()=>{const f=fixture({mode:'stock'});await f.c.scan('BIN');assert(f.c.ready());await f.c.confirm();assert.equal(f.calls.at(-1).args.qty,0);assert.equal(f.calls.at(-1).args.source_key,'container');});
 await test('invalid quantity clears green readiness instead of retaining an old amount',async()=>{const f=fixture({mode:'stock'});await stock(f);assert(f.c.ready());assert.throws(()=>f.c.quantity(-1),/positive/);assert(!f.c.ready());assert.equal(f.c.state.qty,0);});
 await test('failed Site lookup clears the previous ready Site',async()=>{
  const f=fixture();await visit(f);f.env.rpc=async()=>{throw new Error('Wrong Site');};await assert.rejects(()=>f.c.scan('WRONG'),/Wrong Site/);assert(!f.c.ready());assert.equal(f.c.state.customerScan,'');
 });
 await test('lost response persists original stock request through close and refresh',async()=>{
  const f=fixture({mode:'stock'});await stock(f);f.failure(new Error('network'));await assert.rejects(()=>f.c.confirm(),/network/);const original=f.calls.at(-1).args;
  await assert.rejects(()=>f.c.scan('CFG:QTY:MATERIAL:3'),/original pending/);await f.c.scan('CFG:CMD:CANCEL');assert(f.map.has(pendingKey));
  const next=fixture({map:f.map,lock:f.lock});assert(next.c.restore());await next.c.confirm();assert.deepEqual(next.calls.at(-1).args,original);assert(!f.map.has(pendingKey));
 });
 await test('confirmed rejection permits correction with a new action token',async()=>{
  const f=fixture({mode:'stock'});await stock(f);f.failure({exc_type:'ValidationError'});await assert.rejects(()=>f.c.confirm());assert(!f.map.has(pendingKey));f.c.quantity(1);f.failure(null);await f.c.confirm();assert.equal(f.calls.at(-1).args.event_token,'EVENT-2');
 });
 await test('two tabs cannot overwrite a pending stock action',async()=>{
  const map=new Map(),lock={tail:Promise.resolve()};const a=fixture({mode:'stock',map,lock}),b=fixture({mode:'stock',map,lock});await stock(a);await stock(b);a.failure(new Error('network'));
  const results=await Promise.allSettled([a.c.confirm(),b.c.confirm()]);assert(results.every(r=>r.status==='rejected'));assert.equal(a.calls.filter(c=>c.method==='allocate_route_stock').length+b.calls.filter(c=>c.method==='allocate_route_stock').length,1);
 });
 await test('a restored tab must reopen after another tab reconciles the request',async()=>{
  const f=fixture({mode:'stock'});await stock(f);f.failure(new Error('network'));await assert.rejects(()=>f.c.confirm());
  const a=fixture({map:f.map,lock:f.lock}),b=fixture({map:f.map,lock:f.lock});a.c.restore();b.c.restore();await a.c.confirm();await assert.rejects(()=>b.c.confirm(),/another tab/);
 });
 await test('wrong operator cannot reconcile persisted stock intent',async()=>{const f=fixture({mode:'stock'});await stock(f);f.failure(new Error('network'));await assert.rejects(()=>f.c.confirm());const next=fixture({map:f.map});next.c.restore();next.owner('OTHER');await assert.rejects(()=>next.c.confirm(),/original operator/);});
 await test('missing Web Locks and failed storage both block mutation RPC',async()=>{
  const a=fixture();await visit(a);a.env.locks=null;await assert.rejects(()=>a.c.confirm(),/Web Locks/);
  const b=fixture();await visit(b);b.env.storage.setItem=()=>{throw new Error('Quota');};await assert.rejects(()=>b.c.confirm(),/Quota/);assert.equal(b.calls.filter(c=>c.method==='start_route_stop').length,0);
 });
 await test('corrupt or mismatched persisted methods fail closed',()=>{const f=fixture();f.map.set(pendingKey,'bad');assert.throws(()=>f.c.restore(),/unreadable/);f.map.set(pendingKey,JSON.stringify({mode:'stock',method:'delete_stock',owner:'EMP',args:{event_token:'E'}}));assert.throws(()=>f.c.restore(),/incomplete/);});
 await test('repeated confirmation during and after success posts once',async()=>{const f=fixture();await visit(f);await Promise.all([f.c.confirm(),f.c.confirm()]);await f.c.confirm();assert.equal(f.calls.filter(c=>c.method==='start_route_stop').length,1);});
 await test('operator switch during a mutation does not display the old result',async()=>{const f=fixture();await visit(f);const rpc=f.env.rpc;f.env.rpc=async(m,a)=>{const value=await rpc(m,a);f.owner('OTHER');return value;};await f.c.confirm();assert.equal(f.success(),0);assert.equal(f.c.state.plan,null);});
 await test('Tab scanner completes source, quantity and confirmation with focus restoration',async()=>{
  const f=adapter({mode:'stock'});const view=await f.launch(),dialog=f.dialog();
  for(const value of ['TAG','CFG:QTY:MATERIAL:2','CFG:CMD:CONFIRM']){dialog.values.scan=value;let prevented=0;dialog.fields_dict.scan.keydown({key:'Tab',preventDefault(){prevented++;},stopPropagation(){}});assert.equal(prevented,1);}
  await view.scan('CFG:CMD:HELP');assert.equal(f.success(),1);assert(f.focused()>0);
 });
 await test('blank Tab, Shift Tab and composing input retain normal navigation',async()=>{
  const f=adapter();await f.launch();const d=f.dialog();let count=0;d.values.scan='';d.fields_dict.scan.keydown({key:'Tab',preventDefault(){count++;}});d.values.scan='TAG';d.fields_dict.scan.keydown({key:'Tab',shiftKey:true,preventDefault(){count++;}});d.fields_dict.scan.keydown({key:'Enter',isComposing:true,preventDefault(){count++;}});assert.equal(count,0);
 });
 await test('camera cancel and parent close reject late callbacks',async()=>{
  const f=adapter({mode:'stock'});const view=await f.launch();await view.scan('CFG:CMD:ROUTE_CAMERA');const first=f.cameras[0];first.hide_dialog();first.config.on_scan({decodedText:'TAG'});assert.equal(f.calls.length,0);
  await view.scan('CFG:CMD:ROUTE_CAMERA');const second=f.cameras[1];await view.scan('CFG:CMD:CANCEL');assert(!second.visible);second.config.on_scan({decodedText:'TAG'});assert.equal(f.calls.length,0);
 });
 await test('camera reads a source once and remains scanner confirmable',async()=>{
  const f=adapter({mode:'stock'});const view=await f.launch();await view.scan('CFG:CMD:ROUTE_CAMERA');f.cameras[0].decode('TAG');f.cameras[0].config.on_scan({decodedText:'TAG'});await view.scan('CFG:QTY:MATERIAL:2');await view.scan('CFG:CMD:CONFIRM');assert.equal(f.calls.filter(c=>c.method==='allocate_route_stock').length,1);assert.equal(f.calls.filter(c=>c.method==='route_stock_context').length,1);
 });
 await test('camera unavailable/startup failure retains a focused scanner alternative',async()=>{for(const options of [{noCamera:true},{cameraError:true}]){const f=adapter(options);const view=await f.launch();await view.scan('CFG:CMD:ROUTE_CAMERA');assert.match(f.dialog().html,/Camera/);assert(f.focused()>0);}});
 await test('opening the generic action restores stock-mode fields for the original pending request',async()=>{
  const f=fixture({mode:'stock'});await stock(f);f.failure(new Error('network'));await assert.rejects(()=>f.c.confirm());const next=adapter({map:f.map});const view=await next.launch();assert.equal(view.controller.state.mode,'stock');assert.equal(next.dialog().properties['qty:hidden'],0);await view.scan('CFG:CMD:CONFIRM');assert.equal(next.success(),1);
 });
 await test('touch Item/Batch/quantity and scanner use the same controller payload',async()=>{
  const f=adapter({mode:'stock'});const view=await f.launch(),d=f.dialog();d.values.item_code='ITEM';d.fields_dict.item_code.df.onchange();await view.scan('CFG:SELECT:2');d.values.qty=2;d.fields_dict.qty.df.onchange();await d.config.primary_action();assert.equal(f.calls.at(-1).args.source_key,'unassigned');assert.equal(f.calls.at(-1).args.qty,2);
 });
 await test('all route commands are printable and global routing opens the correct mode',async()=>{
  const root=path.resolve(__dirname,'../..'),catalogue=fs.readFileSync(path.join(root,'cfg_kanban/api/operator.py'),'utf8'),panel=fs.readFileSync(path.join(root,'cfg_kanban/cfg_kanban/page/kanban_logistics/kanban_logistics.js'),'utf8');
  for(const command of ['START_ROUTE_DELIVERY','ALLOCATE_ROUTE_STOCK','PLAN_ROUTE_STOP','APPROVE_ROUTE_ORDER','SKIP_ROUTE_STOP','ROUTE_CAMERA','ROUTE_SOURCE','ROUTE_ITEM','ROUTE_BATCH','ROUTE_REASON'])assert(catalogue.includes('CFG:CMD:'+command));
  const start=panel.indexOf('\tasync function process_scan(value)'),end=panel.indexOf('\n\tasync function lookup_tag(',start);let args;
  const run=new Function('$scanner','active_dispatch_review','opening_dispatch_review','active_delivery_action','opening_delivery_action','active_route_delivery','opening_route_delivery','active_prepared_delivery','opening_prepared_delivery','active_isolation','opening_isolation','active_repack','opening_repack','scanner_error','repack_scanner_help','open_route_action','state','let active_route_count_action=null,active_loose_tag=null,opening_loose_tag=false;\n'+panel.slice(start,end)+'\nreturn process_scan("CFG:CMD:PLAN_ROUTE_STOP");');
  await run({find:()=>({val(){}})},null,false,null,false,null,false,null,false,null,false,null,false,()=>{},()=>{},(...value)=>{args=value;},{lookup:{dispatch_plan:{name:'DPL-ROUTE'}}});
  assert.deepEqual(args,['plan','DPL-ROUTE',null]);
 });
 await test('a failed retry keeps the earlier uncertain intent locked',async()=>{
  const f=fixture({mode:'stock'});await stock(f);f.failure(new Error('network'));await assert.rejects(()=>f.c.confirm());
  f.failure({exc_type:'PermissionError'});await assert.rejects(()=>f.c.confirm());assert(f.map.has(pendingKey));
  await assert.rejects(()=>f.c.scan('CFG:QTY:MATERIAL:3'),/original pending/);
 });
 await test('a recorded conflict preserves intent until read-back acknowledges the real result',async()=>{
  const f=fixture({mode:'stock'});await stock(f);f.failure({exc_type:'RouteReplayConflictError'});await assert.rejects(()=>f.c.confirm());assert(f.map.has(pendingKey));
  const rpc=f.env.rpc;f.env.rpc=async(method,args)=>method==='reconcile_route_action'?{recorded:1,voided:0,result:{name:'REAL-SESSION'}}:rpc(method,args);
  await f.c.scan('CFG:CMD:ROUTE_RECONCILE');assert(!f.map.has(pendingKey));assert.equal(f.success(),1);
 });
 await test('no-record read-back keeps the request pending until reasoned cancellation is acknowledged',async()=>{
  const f=fixture({mode:'stock'});await stock(f);f.failure(new Error('network'));await assert.rejects(()=>f.c.confirm());
  const rpc=f.env.rpc;f.env.rpc=async(method,args)=>method==='reconcile_route_action'?{recorded:0,voided:0}:method==='void_unrecorded_route_action'?{recorded:0,voided:1,dispatch_plan:'DPL-ROUTE'}:rpc(method,args);
  await f.c.reconcile();assert(f.map.has(pendingKey));await f.c.scan('CFG:CMD:ROUTE_VOID_PENDING');assert(!f.c.ready());
  await f.c.scan('No physical allocation made');await f.c.scan('CFG:CMD:CONFIRM');assert(!f.map.has(pendingKey));assert.equal(f.success(),1);
 });
 await test('strict out-of-order choice stays red until the Stop has Supervisor approval',async()=>{
  const f=fixture();f.plan.stop_sequence_policy='Planned Order';f.plan.stops=[{name:'FIRST',state:'Planned',planned_sequence:1,customer_scan_point:'OTHER'},{name:'SECOND',state:'Planned',planned_sequence:2,customer_scan_point:'SITE-ID'}];
  await visit(f);assert(!f.c.ready());f.plan.stops[1].override_approved_by='SUPERVISOR';assert(f.c.ready());
 });
 await test('another operators pending payload is masked in the dialog',async()=>{
  const f=fixture({mode:'stock'});await stock(f);f.failure(new Error('network'));await assert.rejects(()=>f.c.confirm());
  const next=adapter({map:f.map});next.owner('OTHER');await next.launch();assert(!next.dialog().html.includes(' · TAG · '));assert.match(next.dialog().html,/original operator EMP/);
 });
 console.log(`${checks} E4B route UI checks passed`);
})().catch(error=>{console.error(error);process.exitCode=1;});
