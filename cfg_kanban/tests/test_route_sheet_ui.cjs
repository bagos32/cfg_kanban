/* Route controller and actual scanner/touch/drag dialog with UI/RPC doubles. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const api=require('../public/js/route_sheet.js');let ntests=0;async function test(name,fn){await fn();console.log('ok '+name);ntests++;}
function store(){const data=new Map();return {getItem:key=>data.get(key)||null,setItem:(key,value)=>data.set(key,value),data};}
function locks(){let tail=Promise.resolve();return {request(key,fn){const next=tail.then(fn);tail=next.catch(()=>{});return next;}};}
function fixture(shared={storage:store(),locks:locks(),n:0}){
 let owner='EMP',success=0,closed=0,fn=async()=>({sheet:{name:'RS1',state:'Draft',revision:1,stops:[]}});const calls=[];
 const env={owner:()=>owner,storage:shared.storage,locks:shared.locks,nonce:()=>`E${++shared.n}`,render(){},close(){closed++;},success:async()=>{success++;},rpc:async(method,args)=>{calls.push({method,args:structuredClone(args)});return fn(method,args);}};
 const c=api.controller(env);c.restore();return {c,env,shared,calls,actor:value=>owner=value,rpc:value=>fn=value,success:()=>success,closed:()=>closed,saved:()=>JSON.parse(shared.storage.getItem('cfg_route_sheet_v1:EMP')||'null')};
}
const args={scope_key:'V:LORRY',stops:[{row_key:'R1',dispatch_plan:'P1',customer_scan_point:'SITE1'}],expected_revision:0,action:'Save Draft'};
function dialogFixture(mode='editor'){
 const b=fixture();let d,focus=0,camera;const handlers={},calls=[];let ctx={scope_key:'V:LORRY',company:'B',scope:'Combined Lorry Trip',can_edit:true,
  templates:[{name:'TEMPLATE',revision:1}],template:{name:'TEMPLATE',revision:1},template_hash:'HASH',
  plans:[{name:'P1',plan_type:'Customer Order',customer:'A'},{name:'P2',plan_type:'Open Route Stock'}],
  sites:[{name:'SITE1',site_name:'Shop A',customer:'A',address_display:'Street A'},{name:'SITE2',site_name:'Shop B',customer:'B',address_display:'Street B'}],
  stops:[{row_key:'R1',dispatch_plan:'P1',customer_scan_point:'SITE1',site_name:'Shop A'},{row_key:'R2',dispatch_plan:'P2',customer_scan_point:'SITE2',site_name:'Shop B'}]};
 function query(selector){return {off(){return this;},on(event,fn){handlers[selector]??={};handlers[selector][event]=fn;return this;}};}
 class Dialog{
  constructor(config){d=this;this.config=config;this.values={};this.fields_dict={};this.$wrapper={find:query};
   for(const df of config.fields){this.fields_dict[df.fieldname]={df,$input:{focus(){focus++;},on:(event,fn)=>{this.fields_dict[df.fieldname][event]=fn;}},$wrapper:{html:value=>{this.fields_dict[df.fieldname].html=value;}}};}}
  get_value(key){return this.values[key];}set_value(key,value){this.values[key]=value;}show(){this.visible=true;}hide(){this.visible=false;this.onhide?.();}enable_primary_action(){}disable_primary_action(){}get_primary_btn(){return {text:value=>this.label=value};}
 }
 class Scanner{constructor(options){camera=this;this.options=options;this.handlers=[];this.dialog={$wrapper:{one:(name,fn)=>this.handlers.push(fn)}};}hide_dialog(){this.handlers.splice(0).forEach(fn=>fn());}}
 const frappe={utils:{escape_html:value=>String(value??'').replaceAll('<','&lt;')},ui:{Dialog,Scanner},call:async({method,args})=>{
  calls.push({method,args:structuredClone(args)});if(method.endsWith('get_route_context'))return {message:structuredClone(ctx)};
  if(method.endsWith('get_route_launch_context'))return {message:{choices:[{label:'Combined Lorry',args:{warehouse:'LORRY'}}]}};
  if(method.endsWith('save_route_sheet'))return {message:{scope_key:'V:LORRY',sheet:{name:'RS1',state:args.action==='Approve'?'Approved':'Draft',revision:1,stops:args.stops}}};
  return {message:{name:'KDS1',state:'Allocating'}};
 }};
 const options={frappe,mode,warehouse:'LORRY',owner:b.env.owner,token:()=> 'TOKEN',nonce:b.env.nonce,storage:b.env.storage,locks:b.env.locks,errorMessage:(error,message)=>error.message||message,onClose(){focus++;},success:b.env.success};
 return {b,frappe,options,handlers,calls,context:value=>ctx=value,ctx:()=>ctx,dialog:()=>d,camera:()=>camera,focus:()=>focus};
}
(async()=>{
 await test('stable request token and payload survive unknown result and reopening',async()=>{
  const f=fixture();f.rpc(async()=>{throw new Error('Lost');});await assert.rejects(()=>f.c.mutate('save_route_sheet',args));const pending=f.saved();
  const again=fixture(f.shared);await again.c.mutate('start_route_sheet_stop',{row_key:'WRONG'});assert.equal(again.calls[0].method,'save_route_sheet');assert.deepEqual(again.calls[0].args,pending.args);
 });
 await test('confirmed first rejection allows correction, while unknown retry rejection keeps original',async()=>{
  const f=fixture();f.rpc(async()=>{throw {exc_type:'ValidationError'};});await assert.rejects(()=>f.c.mutate('save_route_sheet',args));assert.equal(f.saved().status,'Rejected');
  f.rpc(async()=>{throw new Error('Lost');});await assert.rejects(()=>f.c.mutate('save_route_sheet',args));f.rpc(async()=>{throw {exc_type:'PermissionError'};});await assert.rejects(()=>f.c.mutate('save_route_sheet',args));assert.equal(f.saved().status,'Pending');
 });
 await test('busy double confirmation and changed operator cannot issue another mutation',async()=>{
  const f=fixture();await Promise.all([f.c.mutate('save_route_sheet',args),f.c.mutate('save_route_sheet',args)]);assert.equal(f.calls.length,1);
  f.actor('OTHER');await assert.rejects(()=>f.c.mutate('save_route_sheet',args),/original/);
 });
 await test('cross-tab original pending request must be explicitly reviewed before replay',async()=>{
  const a=fixture(),b=fixture(a.shared);a.rpc(async()=>{throw new Error('Lost');});await assert.rejects(()=>a.c.mutate('save_route_sheet',args));
  await assert.rejects(()=>b.c.mutate('save_route_sheet',args),/Another route request/);assert.equal(b.calls.length,0);await b.c.mutate('save_route_sheet',args);assert.equal(b.calls[0].args.event_token,'E1');
 });
 await test('missing Web Locks or blocked storage prevents submission',async()=>{
  const f=fixture();f.env.locks=null;await assert.rejects(()=>f.c.mutate('save_route_sheet',args),/Web Locks/);assert.equal(f.calls.length,0);
  f.env.locks=locks();f.env.storage.setItem=()=>{throw new Error('Storage blocked');};await assert.rejects(()=>f.c.mutate('save_route_sheet',args),/Storage blocked/);assert.equal(f.calls.length,0);
 });
 await test('late response after scanner cancel records receipt without touching a newer view',async()=>{
  const f=fixture();let done;f.rpc(()=>new Promise(resolve=>done=resolve));const pending=f.c.mutate('save_route_sheet',args);await new Promise(resolve=>setImmediate(resolve));f.c.close();done({sheet:{name:'RS1'}});await pending;assert.equal(f.saved().status,'Recorded');assert.equal(f.success(),0);
 });
 await test('read-back absence stays locked until a reasoned void is acknowledged',async()=>{
  const f=fixture();f.rpc(async()=>{throw new Error('Lost');});await assert.rejects(()=>f.c.mutate('save_route_sheet',args));f.rpc(async()=>({status:'Not Recorded'}));await f.c.reconcile();assert(f.c.state.pending);
  await assert.rejects(()=>f.c.reconcile(true),/reason/);f.c.state.reason='Wrong sequence';f.rpc(async()=>({status:'Voided'}));await f.c.reconcile(true);assert.equal(f.saved().status,'Voided');assert.equal(f.c.state.pending,null);
 });
 await test('visit reconciliation uses the visit receipt instead of a planning receipt',async()=>{
  const f=fixture();f.rpc(async()=>{throw new Error('Lost');});await assert.rejects(()=>f.c.mutate('start_route_sheet_stop',{route_sheet:'RS1',row_key:'R1'}));f.rpc(async()=>({status:'Recorded',result:{name:'KDS1'}}));await f.c.reconcile();assert.equal(f.calls.at(-1).method,'reconcile_route_sheet_visit');assert.equal(f.success(),1);
 });
 await test('scanner arrows reorder before approval and send the displayed full order',async()=>{
  const f=dialogFixture(),h=await api.open(f.options);for(const scan of ['CFG:SELECT:2','CFG:CMD:ROUTE_MOVE_UP','CFG:CMD:ROUTE_APPROVE_SEQUENCE','CFG:CMD:CONFIRM'])await h.scan(scan);
  const sent=f.calls.find(row=>row.method.endsWith('save_route_sheet'));assert.deepEqual(sent.args.stops.map(row=>row.row_key),['R2','R1']);assert.equal(sent.args.action,'Approve');assert.equal(sent.args.template_hash,'HASH');assert(f.focus()>0);
 });
 await test('touch drag/drop submits the same order as scanner controls',async()=>{
  const f=dialogFixture(),h=await api.open(f.options),events=f.handlers['.route-stop-choice[draggable]'];
  events.dragstart.call({dataset:{index:'1'}},{originalEvent:{dataTransfer:{setData(){}}}});events.drop.call({dataset:{index:'0'}},{preventDefault(){}});await h.scan('CFG:CMD:HELP');await h.scan('CFG:CMD:CONFIRM');
  assert.deepEqual(f.calls.find(row=>row.method.endsWith('save_route_sheet')).args.stops.map(row=>row.row_key),['R2','R1']);
 });
 await test('non-Supervisor and approved route cannot reorder',async()=>{
  const f=dialogFixture();f.context({...f.ctx(),can_edit:false});const h=await api.open(f.options);await h.scan('CFG:SELECT:1');await h.scan('CFG:CMD:ROUTE_MOVE_DOWN');assert.deepEqual(h.getRows().map(row=>row.row_key),['R1','R2']);assert(f.dialog().fields_dict.summary.html.includes('Supervisor'));
 });
 await test('driver selects assigned stop and submits exact Site scan when required',async()=>{
  const f=dialogFixture('driver');f.context({scope_key:'V:LORRY',sheet:{name:'RS1',state:'Approved',verification_policy:'Require Customer Site QR',stops:f.ctx().stops}});const h=await api.open(f.options);
  await h.scan('CFG:SELECT:1');await h.scan('CUSTOMER-SITE-QR');await h.scan('CFG:CMD:CONFIRM');const sent=f.calls.at(-1);assert(sent.method.endsWith('start_route_sheet_stop'));assert.equal(sent.args.row_key,'R1');assert.equal(sent.args.customer_scan,'CUSTOMER-SITE-QR');assert.equal(f.b.success(),1);
 });
 await test('driver selection mode sends no invented physical QR value',async()=>{
  const f=dialogFixture('driver');f.context({scope_key:'V:LORRY',sheet:{name:'RS1',state:'Approved',verification_policy:'Allow Assigned Stop Selection',stops:f.ctx().stops}});const h=await api.open(f.options);await h.scan('CFG:SELECT:2');await h.scan('CFG:CMD:CONFIRM');assert.equal(f.calls.at(-1).args.customer_scan,null);assert.equal(f.calls.at(-1).args.row_key,'R2');
 });
 await test('Tab/Enter and camera accept scans once; Cancel restores parent focus',async()=>{
  const f=dialogFixture(),h=await api.open(f.options),d=f.dialog();let prevented=0;d.values.scan='CFG:SELECT:1';await d.fields_dict.scan.keydown({key:'Tab',preventDefault(){prevented++;},stopPropagation(){}});assert.equal(prevented,1);
  await d.fields_dict.camera.df.click();const camera=f.camera();camera.options.on_scan({decodedText:'CFG:SELECT:2'});await h.scan('CFG:CMD:HELP');assert.equal(h.controller.state.selected,1);
  await h.scan('CFG:CMD:CANCEL');camera.options.on_scan({decodedText:'CFG:CMD:CONFIRM'});assert.equal(d.visible,false);assert(f.focus()>0);
 });
 await test('numbered stop choices page beyond ten and keep a moved stop visible',async()=>{
  const f=dialogFixture();const ctx=f.ctx();ctx.stops=Array.from({length:12},(_,i)=>({row_key:'R'+(i+1),dispatch_plan:'P2',customer_scan_point:'SITE'+(i+1),site_name:'Shop '+(i+1)}));f.context(ctx);
  const h=await api.open(f.options);await h.scan('CFG:CMD:NEXT_MATERIALS');await h.scan('CFG:SELECT:1');assert.equal(h.controller.state.selected,10);
  await h.scan('CFG:CMD:ROUTE_MOVE_UP');assert.equal(h.controller.state.selected,9);assert.equal(h.controller.state.choicePage,0);assert.equal(h.getRows()[9].row_key,'R11');
 });
 await test('new global commands route from both panels and have printable command labels',()=>{
  const base=path.resolve(__dirname,'..'),operator=fs.readFileSync(path.join(base,'api/operator.py'),'utf8'),prod=fs.readFileSync(path.join(base,'cfg_kanban/page/kanban_operator/kanban_operator.js'),'utf8'),panel=fs.readFileSync(path.join(base,'cfg_kanban/page/kanban_logistics/kanban_logistics.js'),'utf8');
  for(const name of ['VIEW_LORRY_ROUTE','EDIT_ROUTE_SEQUENCE']){assert(operator.includes('CFG:CMD:'+name));assert(prod.includes(name));assert(panel.includes('CFG:CMD:'+name));}
  for(const name of ['ROUTE_TEMPLATE','ROUTE_MOVE_UP','ROUTE_MOVE_DOWN','ROUTE_APPROVE_SEQUENCE','ROUTE_SAVE_DRAFT','ROUTE_SHEET_CAMERA','ROUTE_REVIEW_PLANS','ROUTE_OPEN_DELIVERIES'])assert(operator.includes('CFG:CMD:'+name));
  assert(panel.includes('if (active_delivery_action) return active_delivery_action.scan(raw)'));
  assert(panel.includes('openReview:plan=>open_dispatch_review("begin",plan),openDelivery:name=>open_delivery_session(name)'));
 });
 function cancellationContext(f,state='Cancellation Pending'){
  return {scope_key:'V:LORRY',sheet:{name:'OLD-SHEET',state,revision:7,can_start:false,can_cancel:state!=='Cancelled',stops:f.ctx().stops,
   cancellation_reason:'End old route',cancellation:{ready:false,plans:[{name:'P1',state:'Loaded',review_state:'Reviewing',settled:false,open_deliveries:[{name:'KDS-OPEN',state:'Delivered'}]},
    {name:'P2',state:'Reconciled',review_state:'Settled',settled:true,open_deliveries:[]}]}}};
 }
 await test('pending cancellation shows blockers, exact sheet ID and finish action without draft edits',async()=>{
  const f=dialogFixture();f.context(cancellationContext(f));const call=f.frappe.call;f.frappe.call=async args=>args.method.endsWith('save_route_sheet')?{message:f.ctx()}:call(args);
  const h=await api.open(f.options),d=f.dialog();assert(d.fields_dict.summary.html.includes('KDS-OPEN'));assert(d.fields_dict.controls.html.includes('Finish Route Cancellation'));assert(!d.fields_dict.controls.html.includes('Approve Sequence'));
  await h.scan('CFG:CMD:ROUTE_SHEET_REASON');await h.scan('Supervisor ends trip');await h.scan('CFG:CMD:ROUTE_CANCEL_SHEET');await h.scan('CFG:CMD:CONFIRM');
  assert(d.visible);assert.equal(h.controller.state.context.sheet.state,'Cancellation Pending');assert.equal(h.controller.state.action,'Cancel');assert(f.focus()>0);
 });
 await test('scanner finish-cancel submits frozen parent and revision, then closes after settlement',async()=>{
  const f=dialogFixture();f.context(cancellationContext(f));let submitted;const call=f.frappe.call;
  f.frappe.call=async request=>{if(request.method.endsWith('save_route_sheet')){submitted=request.args;return {message:{scope_key:'V:LORRY',sheet:{...f.ctx().sheet,state:'Cancelled'}}};}return call(request);};
  const h=await api.open(f.options);await h.scan('CFG:CMD:ROUTE_SHEET_REASON');await h.scan('E5 settled');await h.scan('CFG:CMD:CONFIRM');
  assert.equal(submitted.route_sheet,'OLD-SHEET');assert.equal(submitted.expected_revision,7);assert.equal(submitted.reason,'E5 settled');assert.equal(submitted.action,'Cancel');assert.equal(f.dialog().visible,false);
 });
 await test('touch and numbered scanner review handoff release parent before opening E5 once',async()=>{
  const f=dialogFixture();f.context(cancellationContext(f));let closed=0,review=null;f.options.onClose=()=>closed++;f.options.openReview=async name=>{assert.equal(closed,1);review=name;};
  const h=await api.open(f.options);f.handlers['.route-reviews'].click();await h.scan('CFG:SELECT:2');assert.equal(review,'P2');assert.equal(f.dialog().visible,false);
  f.dialog().onhide();assert.equal(closed,1);
 });
 await test('open-delivery choice hands the original Session to its controlled workflow',async()=>{
  const f=dialogFixture();f.context(cancellationContext(f));let delivery=null;f.options.openDelivery=async name=>delivery=name;const h=await api.open(f.options);
  await h.scan('CFG:CMD:ROUTE_OPEN_DELIVERIES');await h.scan('CFG:SELECT:1');assert.equal(delivery,'KDS-OPEN');assert.equal(f.dialog().visible,false);
 });
 await test('stopped routes cannot start visits and terminal history has no cancellation buttons',async()=>{
  const f=dialogFixture('driver');f.context(cancellationContext(f));const h=await api.open(f.options);await h.scan('CFG:SELECT:1');await h.scan('CFG:CMD:CONFIRM');
  assert(!f.calls.some(row=>row.method.endsWith('start_route_sheet_stop')));assert(f.dialog().fields_dict.summary.html.includes('route is stopped'));
  const old=dialogFixture();old.context(cancellationContext(old,'Cancelled'));await api.open(old.options);assert(!old.dialog().fields_dict.controls.html.includes('route-cancel'));
 });
 await test('lost cancellation reply read-back retains recovery state and refresh targets original sheet',async()=>{
  const f=dialogFixture();const initial=cancellationContext(f,'In Progress');initial.sheet.can_start=true;f.context(initial);let receipt=false,refreshArgs;const call=f.frappe.call;
  f.frappe.call=async request=>{
   if(request.method.endsWith('save_route_sheet'))throw new Error('Lost reply');
   if(request.method.endsWith('reconcile_route_sheet_action')){receipt=true;return {message:{status:'Recorded',sheet:cancellationContext(f).sheet}};}
   if(receipt&&request.method.endsWith('get_route_context'))refreshArgs=request.args;
   return call(request);
  };
  const h=await api.open(f.options);await h.scan('CFG:CMD:ROUTE_CANCEL_SHEET');await h.scan('CFG:CMD:CONFIRM');assert(h.controller.state.pending);
  await h.scan('CFG:CMD:ROUTE_SHEET_REFRESH');assert.equal(h.controller.state.context.sheet.state,'Cancellation Pending');assert.equal(h.controller.state.action,'Cancel');assert(f.dialog().visible);
  await h.scan('CFG:CMD:ROUTE_SHEET_REFRESH');assert.equal(refreshArgs.route_sheet,'OLD-SHEET');assert.equal(h.controller.state.pending,null);
 });
 await test('Ready to Close exposes Close Route to authorized driver view and confirms the existing closure action',async()=>{
  const f=dialogFixture('driver');f.context({scope_key:'V:LORRY',sheet:{name:'RS1',state:'Ready to Close',revision:4,can_start:false,can_close:true,stops:f.ctx().stops}});
  let sent;const original=f.frappe.call;f.frappe.call=async request=>{if(request.method.endsWith('save_route_sheet')){sent=request.args;return {message:{sheet:{...f.ctx().sheet,state:'Completed'}}};}return original(request);};
  const h=await api.open(f.options),d=f.dialog();assert(d.fields_dict.controls.html.includes('Close Route'));assert(d.fields_dict.controls.html.includes('E5 Plan Reviews'));
  await h.scan('CFG:CMD:ROUTE_CLOSE_SHEET');await h.scan('CFG:CMD:CONFIRM');assert.equal(sent,undefined);assert(d.fields_dict.summary.html.includes('closure reason'));
  await h.scan('CFG:CMD:ROUTE_SHEET_REASON');await h.scan('All deliveries verified');await h.scan('CFG:CMD:CONFIRM');
  assert.equal(sent.action,'Close');assert.equal(sent.route_sheet,'RS1');assert.equal(sent.expected_revision,4);assert.equal(sent.reason,'All deliveries verified');assert(!d.visible);assert(f.focus()>0);
 });
 await test('read-only Ready to Close has no Close Route button',async()=>{
  const f=dialogFixture('driver');f.context({scope_key:'V:LORRY',sheet:{name:'RS1',state:'Ready to Close',can_start:false,can_close:false,stops:f.ctx().stops}});
  await api.open(f.options);assert(!f.dialog().fields_dict.controls.html.includes('route-close'));
 });
 await test('guided leftovers hands off the exact Sheet after closing its dialog once',async()=>{
  const f=dialogFixture('driver');f.context({scope_key:'V:LORRY',sheet:{name:'DRS-GROUP',state:'Ready to Close',can_close:true,can_start:false,stops:f.ctx().stops}});
  let opened;f.options.openHandover=name=>{assert(!f.dialog().visible);opened=name;};const h=await api.open(f.options);assert(f.dialog().fields_dict.controls.html.includes('Guided Closure / Leftovers'));
  await h.scan('CFG:CMD:TRIP_HANDOVER');assert.equal(opened,'DRS-GROUP');assert(h.controller.state.closed);
 });
 console.log(`${ntests} route-sheet UI checks passed`);
})().catch(error=>{console.error(error);process.exitCode=1;});
