/* Actual persistent controller and inline driver controls; RPC/DOM doubles, no live ERP claims. */
const test=require('node:test'),assert=require('node:assert/strict');
const api=require('../public/js/driver_route_actions.js');
const fieldScanner=require('../public/js/delivery_action_scanner.js');
const erp=require('../public/js/dispatch_recovery.js');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
const memory=()=>{const m=new Map();return{getItem:key=>m.get(key)||null,setItem:(key,v)=>m.set(key,v),removeItem:key=>m.delete(key),m};};
const locks=()=>{let tail=Promise.resolve();return{request(_key,work){const result=tail.then(work);tail=result.catch(()=>{});return result;}};};
const context={revision:0,scope_hash:'SCOPE',stop_key:'STOP',dispatch_plan:'PLAN'};
function harness(overrides={}){
 let owner='EMP',token='TOKEN',counter=0;const calls=[],renders=[],saved=[];const storage=memory();
 const env={storage,locks:locks(),owner:()=>owner,token:()=>token,nonce:()=>`ID${++counter}`,render:s=>renders.push({...s}),
  rpc:async(method,args)=>{calls.push({method,args});return{status:'Recorded',action:args.action};},success:async r=>saved.push(r),...overrides};
 const c=api.controller(env);c.restore('TRIP');
 return{c,env,calls,renders,saved,storage:env.storage,owner:v=>owner=v,token:v=>token=v};
}
test('request is persisted before RPC without credentials and successful identity is acknowledged',async()=>{
 const h=harness();h.env.rpc=async(method,args)=>{const pending=JSON.parse(h.storage.getItem('cfg_driver_action:TRIP'));assert.equal(pending.status,'Pending');assert.equal(pending.request.event_token,args.event_token);assert(!JSON.stringify(pending).includes('TOKEN'));return{status:'Recorded',action:args.action};};
 await h.c.mutate(context,'Begin Delivery',{customer_scan:'QR1'});assert.equal(h.c.state.pending,null);assert.equal(JSON.parse(h.storage.getItem('cfg_driver_action:TRIP')).status,'Recorded');
});
test('lost response survives close/reopen and retries the exact original request with a renewed token',async()=>{
 const h=harness({rpc:async()=>{throw new Error('network');}});await assert.rejects(h.c.mutate(context,'Begin Delivery',{customer_scan:'ORIGINAL'}));h.c.close();
 const next=harness({storage:h.storage});next.token('RENEWED');next.c.restore('TRIP');await next.c.retry();
 assert.equal(next.calls[0].args.payload.customer_scan,'ORIGINAL');assert.equal(next.calls[0].args.event_token,'ID1');assert.equal(next.calls[0].args.operator_session_token,'RENEWED');
});
test('first confirmed server rejection allows correction; unknown followed by rejection stays locked',async()=>{
 const rejection=Object.assign(new Error('required'),{exc_type:'ValidationError'});
 const h=harness({rpc:async()=>{throw rejection;}});await assert.rejects(h.c.mutate(context,'Submit Proof',{proof_name:'P'}));assert.equal(h.c.state.pending,null);
 h.env.rpc=async()=>{throw new Error('unknown');};await assert.rejects(h.c.mutate(context,'Submit Proof',{proof_name:'P',recipient_name:'A'}));
 h.env.rpc=async()=>{throw rejection;};await assert.rejects(h.c.retry());assert(h.c.state.pending);
 await assert.rejects(h.c.mutate(context,'Submit Proof',{recipient_name:'B'}),/original request/);
});
test('fingerprint conflicts stay pending and readback Not Recorded never unlocks replacement details',async()=>{
 const h=harness({rpc:async()=>{throw Object.assign(new Error('conflict'),{exc_type:'DriverActionConflict'});}});
 await assert.rejects(h.c.mutate(context,'Begin Delivery',{customer_scan:'QR1'}));h.env.rpc=async()=>({status:'Not Recorded'});await h.c.reconcile();
 assert(h.c.state.pending);assert.match(h.c.state.message,/Keep the original request/);
});
test('recorded readback and supervisor void acknowledge only the original request',async()=>{
 for(const status of ['Recorded','Voided']){
  const h=harness({rpc:async()=>{throw new Error('unknown');}});await assert.rejects(h.c.mutate(context,'Begin Delivery',{customer_scan:'QR'}));
  let args;h.env.rpc=async(_m,a)=>{args=a;return{status};};await h.c.reconcile(status==='Voided'?'Supervisor reconciled':null);
  assert.equal(args.request_actor,'EMP');assert.equal(args.event_token,'ID1');assert.equal(h.c.state.pending,null);
 }
});
test('Web Locks and storage failures prevent a request before it can be sent',async()=>{
 const h=harness({locks:null});await assert.rejects(h.c.mutate(context,'Start Route'),/Web Locks/);assert.equal(h.calls.length,0);
 const s=harness();s.storage.setItem=()=>{throw new Error('storage blocked');};await assert.rejects(s.c.mutate(context,'Start Route'),/storage/);assert.equal(s.calls.length,0);
});
test('corrupt pending identity fails closed and is never silently discarded',()=>{
 const storage=memory();storage.setItem('cfg_driver_action:TRIP','bad-json');assert.throws(()=>harness({storage}),/unreadable/);
 assert.equal(storage.getItem('cfg_driver_action:TRIP'),'bad-json');
});
test('duplicate confirmation while busy sends only one request',async()=>{
 const d=deferred(),h=harness({rpc:()=>d.promise});const first=h.c.mutate(context,'Start Route');await Promise.resolve();await Promise.resolve();
 await h.c.mutate(context,'Start Route');d.resolve({status:'Recorded'});await first;assert.equal(h.saved.length,1);
});
test('shared tab lock and storage baseline prevent concurrent identities and stale retry',async()=>{
 const storage=memory(), lock=locks(),d=deferred();let sent=0;
 const a=harness({storage,locks:lock,rpc:()=>{sent++;return d.promise;}}),b=harness({storage,locks:lock});
 const first=a.c.mutate(context,'Start Route');const second=b.c.mutate(context,'Start Route');
 d.resolve({status:'Recorded'});await first;await assert.rejects(second,/Another tab/);assert.equal(sent,1);assert.equal(b.calls.length,0);
 b.c.restore('TRIP');await b.c.mutate({...context,revision:1},'Begin Delivery');
 await assert.rejects(a.c.mutate(context,'Begin Delivery'),/Another tab/);
});
test('an unresolved request is masked from another operator and late result does not alter their screen',async()=>{
 const d=deferred(),h=harness({rpc:()=>d.promise});const request=h.c.mutate(context,'Start Route');await Promise.resolve();await Promise.resolve();h.owner('OTHER');h.c.close();d.resolve({status:'Recorded'});await request;assert.equal(h.saved.length,0);
 const next=harness({storage:h.storage});next.owner('OTHER');await next.c.mutate(context,'Start Route');
 const p=harness({rpc:async()=>{throw new Error('unknown');}});await assert.rejects(p.c.mutate(context,'Start Route'));p.owner('OTHER');await assert.rejects(p.c.retry(),/original operator/);
});
test('a render/refresh failure after success does not turn a recorded action into an unknown mutation',async()=>{
 const h=harness({success:async()=>{throw new Error('read failed');}});await h.c.mutate(context,'Start Route');assert.equal(h.c.state.pending,null);assert.match(h.c.state.message,/Action recorded/);
});

const tick=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setTimeout(resolve,0));};
function panel({step='Begin Delivery',requireScan=false,requirements=[],proof=null,fail=null,existingStorage=null}={}){
 const nodes=new Map(),events=new Map(),controls={},calls=[],cameras=[],storage=existingStorage||memory();let owner='EMP',token='TOKEN',active=true,closed=0,refreshes=0,revision=0,current=step,lastAction='';
 class Node{
  constructor(){this.value='';this.disabled=false;this.caption='';this.visible=true;}
  html(v){this.markup=v;return this;}text(v){this.caption=v;return this;}empty(){this.markup='';return this;}appendTo(){return this;}
  find(key){if(!nodes.has(key))nodes.set(key,new Node());return nodes.get(key);}prop(k,v){this[k]=v;return this;}toggle(v){this.visible=v;return this;}
  val(v){if(arguments.length){this.value=v;return this;}return this.value;}trigger(){this.focused=true;return this;}
  off(){return this;}on(type,selector,callback){events.set(type+' '+selector,callback);return this;}one(){return this;}
 }
 global.$=()=>new Node();global.__=v=>v;
 const host=new Node(),f={utils:{escape_html:v=>String(v??'').replaceAll('<','&lt;')},ui:{form:{make_control:({df})=>{
  const control={df,$wrapper:new Node(),value:df.default,get_value(){return this.value;},set_value(v){this.value=v;}};controls[df.fieldname]=control;return control;}
 },Scanner:class{constructor(opts){this.opts=opts;this.dialog={$wrapper:new Node(),hide(){}};cameras.push(this);}stop_scan(){this.stopped=true;}}},
 call:async({method,args})=>{
  calls.push({method,args});
  if(method.endsWith('driver_action_context'))return{message:{...context,revision,next_step:current,require_scan:requireScan,requirements:{fields:requirements},proof,delivery_note:'DN',purpose:current==='Complete Stop'?'Visit Only':'Delivery'}};
  if(method.endsWith('reconcile_driver_action'))return{message:{status:'Recorded',action:lastAction}};
  if(fail)throw fail;
  lastAction=args.action;revision++;
  current=({ 'Start Route':'Begin Delivery','Begin Delivery':'Confirm Allocations','Confirm Allocations':'Create Delivery Note','Create Delivery Note':proof?'Open Proof':'Done','Open Proof':'Submit Proof','Submit Proof':'Done','Complete Stop':'Done'})[args.action];
  return{message:{status:'Recorded',action:args.action}};
 }};
 let evidenceBusy=false;
 global.window={cfg_delivery_action_scanner:fieldScanner,cfg_dispatch_recovery:erp,cfg_delivery_proof_tools:{evidenceHTML:()=>'<input type="file">',signatureHTML:()=>'<canvas></canvas>',
  bind:()=>({busy:()=>evidenceBusy,close(){}}),geotag:async()=>({latitude:1,longitude:2,accuracy:3})}};
 const view=api.open({frappe:f,host,trip:'TRIP',stop:'STOP',owner:()=>owner,token:()=>token,active:()=>active,
  detail:()=>({trip:{trip_title:'Trip'},stops:[{stop_key:'STOP',site_name:'Shop',address:'Street',items:[{item_code:'ITEM',planned_qty:5,stock_uom:'Nos',orders:[{sales_order:'SO'}]}]}]}),
  refresh:async()=>{refreshes++;},storage,locks:locks(),nonce:()=>`REQUEST${calls.length}`,error:e=>e.message,supervisor:()=>false,onClose:()=>{closed++;}});
 return{view,nodes,events,controls,calls,cameras,storage,closed:()=>closed,refreshes:()=>refreshes,owner:v=>owner=v,token:v=>token=v,active:v=>active=v,evidenceBusy:v=>evidenceBusy=v,current:v=>current=v,Node};
}
test('Start Route requires review and records departure without advancing into a delivery',async()=>{
 const h=panel({step:'Start Route'});await tick();assert.equal(h.calls.filter(c=>c.method.endsWith('perform_driver_action')).length,0);
 await h.view.scan('CFG:CMD:CONFIRM');await tick();assert.deepEqual(h.calls.filter(c=>c.method.endsWith('perform_driver_action')).map(c=>c.args.action),['Start Route']);assert.equal(h.closed(),1);
});
test('one reviewed confirmation advances native allocation and DN steps without extra scans',async()=>{
 const h=panel();await tick();await h.view.scan('CFG:CMD:CONFIRM');await tick();
 assert.deepEqual(h.calls.filter(c=>c.method.endsWith('perform_driver_action')).map(c=>c.args.action),['Begin Delivery','Confirm Allocations','Create Delivery Note']);assert.equal(h.closed(),1);
});
test('mandatory Customer Site QR cannot be replaced by a guessed site; camera and fixed scan both work',async()=>{
 const h=panel({requireScan:true});await tick();await h.view.scan('CFG:CMD:CONFIRM');assert.equal(h.calls.filter(c=>c.method.endsWith('perform_driver_action')).length,0);
 assert.match(h.nodes.get('.driver-action-message').caption,/required Customer Site/);
 h.events.get('click.cfg_driver_action .driver-action-camera')();await tick();h.cameras[0].opts.on_scan({decodedText:'SITE-QR'});await tick();
 assert.equal(h.controls.customer_scan.get_value(),'SITE-QR');await h.view.scan('CFG:CMD:CONFIRM');await tick();assert.equal(h.calls.find(c=>c.args.action==='Begin Delivery').args.payload.customer_scan,'SITE-QR');assert(h.cameras[0].stopped);
});
test('required ERP scalar and table inputs pause automatic posting and remain scanner-operable',async()=>{
 const requirements=[{scope:'parent',fieldname:'custom_reference',label:'Reference',fieldtype:'Data'},{scope:'table',fieldname:'custom_rows',label:'Rows',fields:[{fieldname:'value',label:'Value',fieldtype:'Data'}]}];
 const h=panel({requirements});await tick();await h.view.scan('CFG:CMD:CONFIRM');await tick();
 assert.equal(h.calls.filter(c=>c.args.action==='Create Delivery Note').length,0);
 await h.view.scan('CFG:SELECT:1');await h.view.scan('REF');await h.view.scan('CFG:SELECT:2');await h.view.scan('CFG:CMD:DELIVERY_ADD_ROW');await h.view.scan('ROW');await h.view.scan('CFG:CMD:CONFIRM');await tick();
 assert.deepEqual(h.calls.find(c=>c.args.action==='Create Delivery Note').args.payload.required_erp_inputs,{parent:{custom_reference:'REF'},tables:{custom_rows:[{value:'ROW'}]}});
});
test('an existing Draft waits for authorized ERP submission with no new posting request',async()=>{
 const h=panel({step:'Await ERP'});await tick();await h.view.scan('CFG:CMD:CONFIRM');assert.equal(h.calls.filter(c=>c.method.endsWith('perform_driver_action')).length,0);
 assert.match(h.nodes.get('.driver-action-fields').markup,/Awaiting authorized ERP submission/);assert.equal(h.nodes.get('.driver-action-readback').visible,true);
});
test('proof capture uses native proof record and GPS, and cannot overtake an evidence upload',async()=>{
 const proof={name:'POD',proof_policy:'Required',require_signature:1,require_photo:1,require_gps:1,allowed_dispositions:['Attended']};
 const h=panel({proof});await tick();await h.view.scan('CFG:CMD:CONFIRM');await tick();
 assert.equal(h.calls.filter(c=>c.args.action==='Submit Proof').length,0);h.evidenceBusy(true);await h.view.scan('CFG:CMD:CONFIRM');assert.match(h.nodes.get('.driver-action-message').caption,/finished uploading/);
 h.evidenceBusy(false);await h.view.scan('CFG:CMD:DELIVERY_RECIPIENT');await h.view.scan('Recipient');await h.view.scan('CFG:CMD:CONFIRM');await tick();
 const request=h.calls.find(c=>c.args.action==='Submit Proof');assert.equal(request.args.payload.proof_name,'POD');assert.equal(request.args.payload.recipient_name,'Recipient');assert.equal(request.args.payload.latitude,1);assert.equal(h.closed(),1);
});
test('unknown submission disables correction, closes safely, and reopens with original identity',async()=>{
 const h=panel({requireScan:true,fail:new Error('network lost')});await tick();await h.view.scan('QR1');await h.view.scan('CFG:CMD:CONFIRM');await tick();
 assert(h.view.controller.state.pending);assert.equal(h.nodes.get('.driver-action-fields :input').disabled,true);await h.view.scan('CFG:CMD:CANCEL');assert.equal(h.closed(),1);
 const next=panel({existingStorage:h.storage});await tick();assert(next.view.controller.state.pending);await next.view.scan('QR2');assert.match(next.nodes.get('.driver-action-message').caption,/original request/);
 await next.view.scan('CFG:CMD:CONFIRM');await tick();assert.equal(next.calls.find(c=>c.method.endsWith('perform_driver_action')).args.payload.customer_scan,'QR1');
});
test('Enter/Tab restoration, safe Cancel and stale camera callbacks respect the page owner',async()=>{
 const h=panel({requireScan:true});await tick();const handler=h.events.get('keydown.cfg_driver_action .driver-action-scan');let prevent=0;
 for(const key of ['Enter','Tab']){h.nodes.get('.driver-action-scan').val('QR');handler({key,preventDefault(){prevent++;},stopPropagation(){}});await tick();}
 assert.equal(prevent,2);assert.equal(h.controls.customer_scan.get_value(),'QR');assert(h.nodes.get('.driver-action-scan').focused);
 h.events.get('click.cfg_driver_action .driver-action-camera')();await tick();h.owner('OTHER');h.cameras[0].opts.on_scan({decodedText:'PRIVATE'});await tick();assert.equal(h.controls.customer_scan.get_value(),'QR');h.view.close();assert(h.cameras[0].stopped);
});
test('visit-only completion sends notes and no fabricated delivery allocation',async()=>{
 const h=panel({step:'Complete Stop'});await tick();await h.view.scan('A forecast visit');await h.view.scan('CFG:CMD:CONFIRM');await tick();
 const writes=h.calls.filter(c=>c.method.endsWith('perform_driver_action'));assert.equal(writes.length,1);assert.equal(writes[0].args.action,'Complete Stop');assert.equal(writes[0].args.payload.notes,'A forecast visit');
});


test('acknowledged proof outcome removes recipient, notes and GPS from browser recovery storage',async()=>{
 const h=harness();await h.c.mutate(context,'Submit Proof',{proof_name:'POD',recipient_name:'Private Recipient',notes:'Private note',latitude:1});
 const saved=h.storage.getItem('cfg_driver_action:TRIP');assert(!saved.includes('Private'));assert(!saved.includes('latitude'));assert.equal(JSON.parse(saved).status,'Recorded');
});
