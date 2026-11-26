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
function panel({step='Begin Delivery',requireScan=false,requirements=[],proof=null,fail=null,existingStorage=null,quantities=[],looseTags=[],selectedStock=[],stockPending=false,setup={conditions:['Unknown','Damaged']},previewFailure=null,sessionState=null,recoveryMessage=null,exception=null}={}){
 const nodes=new Map(),events=new Map(),controls={},calls=[],cameras=[],storage=existingStorage||memory();let owner='EMP',token='TOKEN',active=true,closed=0,refreshes=0,revision=0,current=step,lastAction='',stockOptions=null,stockClosed=0,stockFocus=0;const stockScans=[];
 class Node{
  constructor(){this.value='';this.disabled=false;this.caption='';this.visible=true;}
  html(v){this.markup=v;return this;}prepend(v){this.markup=v+(this.markup||'');return this;}append(v){this.markup=(this.markup||'')+v;return this;}attr(k,v){this.attrs=this.attrs||{};if(arguments.length===2){this.attrs[k]=v;return this;}return this.attrs[k];}text(v){this.caption=v;return this;}empty(){this.markup='';return this;}appendTo(){return this;}
  find(key){if(!nodes.has(key))nodes.set(key,new Node());return nodes.get(key);}prop(k,v){this[k]=v;return this;}toggle(v){this.visible=v;return this;}
  val(v){if(arguments.length){this.value=v;return this;}return this.value;}trigger(){this.focused=true;return this;}
  off(){return this;}on(type,selector,callback){events.set(type+' '+selector,callback);return this;}one(){return this;}
 }
 global.$=value=>value instanceof Node?value:new Node();global.__=v=>v;
 const host=new Node(),f={utils:{escape_html:v=>String(v??'').replaceAll('<','&lt;')},ui:{form:{make_control:({df})=>{
  const control={df,$wrapper:new Node(),value:df.default,get_value(){return this.value;},set_value(v){this.value=v;}};controls[df.fieldname]=control;return control;}
 },Scanner:class{constructor(opts){this.opts=opts;this.dialog={$wrapper:new Node(),hide(){}};cameras.push(this);}stop_scan(){this.stopped=true;}}},
 require:async()=>{window.cfg_route_delivery=stockApi;},call:async({method,args})=>{
  calls.push({method,args});
  if(method.endsWith('driver_action_context'))return{message:{...context,revision,next_step:current,dispatch_plan:['Request Stop Cancellation','Cancel Customer Stop','Add Assistant','Edit Route Order','Decide Route Change','Cancel Route Change'].includes(current)?null:context.dispatch_plan,stop_key:['Add Assistant','Edit Route Order','Decide Route Change','Cancel Route Change'].includes(current)?null:context.stop_key,delivery_session:'DELIVERY',session_state:sessionState,message:recoveryMessage,exception,selected_stock:selectedStock,quantities,loose_tags:looseTags,setup,require_scan:requireScan,requirements:{fields:requirements},proof,delivery_note:'DN',purpose:current==='Complete Stop'?'Visit Only':'Delivery'}};
  if(method.endsWith('scan_loose_tag')){if(args.stop_key!=='STOP'||args.scan_value!=='CFG:LOOSE:KLT-1')throw new Error('Wrong customer stop');looseTags[0].state='Scanned';return{message:{...looseTags[0],lines:looseTags[0].lines}};}
  if(method.endsWith('preview_driver_quantities')||method.endsWith('preview_open_quantities')){if(previewFailure)throw previewFailure;return {message:args.quantities.map(row=>({...row,item_code:'ITEM',stock_uom:'Nos',refused_qty:5-Number(row.accepted_qty)}))};}
  if(method.endsWith('preview_driver_collection')){if(previewFailure)throw previewFailure;return {message:{...args.payload,company:'A',customer:'CUST',inspection_location:'QC BAY',lines:args.payload.lines.map(row=>({...row,stock_uom:'Nos'}))}};}
  if(method.endsWith('reconcile_driver_action'))return{message:{status:'Recorded',action:lastAction}};
  if(fail)throw fail;
  lastAction=args.action;revision++;
  current=({ 'Start Route':'Begin Delivery','Begin Delivery':'Confirm Allocations','Begin Open Sale':'Select Route Stock','Confirm Allocations':'Create Delivery Note','Create Delivery Note':proof?'Open Proof':'Done','Open Proof':'Submit Proof','Submit Proof':'Done','Complete Stop':'Done'})[args.action];
  return{message:{status:'Recorded',action:args.action}};
 }};
 const stockApi={pendingKey:'cfg_kanban_route_action_pending_v1',open:async opts=>{stockOptions=opts;return{close(){stockClosed++;opts.onClose();},focus(){stockFocus++;},scan(value){stockScans.push(value);}};}};
 if(stockPending)storage.setItem(stockApi.pendingKey,'pending');
 let evidenceBusy=false;
 global.window={cfg_delivery_action_scanner:fieldScanner,cfg_dispatch_recovery:erp,cfg_delivery_proof_tools:{evidenceHTML:()=>'<input type="file">',signatureHTML:()=>'<canvas></canvas>',
  bind:()=>({busy:()=>evidenceBusy,close(){}}),geotag:async()=>({latitude:1,longitude:2,accuracy:3})}};
 const view=api.open({frappe:f,host,trip:'TRIP',stop:'STOP',owner:()=>owner,token:()=>token,active:()=>active,
  detail:()=>({trip:{trip_title:'Trip'},stops:[{stop_key:'STOP',site_name:'Shop',address:'Street',items:[{item_code:'ITEM',planned_qty:5,stock_uom:'Nos',orders:[{sales_order:'SO'}]}]}]}),
  refresh:async()=>{refreshes++;},storage,locks:locks(),nonce:()=>`REQUEST${calls.length}`,error:e=>e.message,supervisor:()=>false,onClose:()=>{closed++;}});
 return{view,nodes,events,controls,calls,cameras,storage,closed:()=>closed,refreshes:()=>refreshes,owner:v=>owner=v,token:v=>token=v,active:v=>active=v,evidenceBusy:v=>evidenceBusy=v,current:v=>current=v,stock:()=>stockOptions,stockClosed:()=>stockClosed,stockFocus:()=>stockFocus,stockScans,Node};
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

const preparedQty=()=>[{dispatch_allocation:'ALLOC',source_label:'ITEM / RM1 / LOT',item_code:'ITEM',stock_uom:'Nos',prepared_qty:5,accepted_qty:5,refusal_reason:'',condition:'Good / Unwanted'}];
test('refusal review is required before mutation and submits the same reviewed stock sources',async()=>{
 const h=panel({quantities:preparedQty()});await tick();
 h.controls.quantities.df.data[0].accepted_qty=3;h.controls.quantities.df.data[0].refusal_reason='Reduced order';
 await h.view.scan('CFG:CMD:CONFIRM');assert.equal(h.calls.filter(c=>c.method.endsWith('perform_driver_action')).length,0);
 assert.match(h.nodes.get('.driver-action-message').caption,/accepted 3, refused 2/);assert(h.nodes.get('.driver-action-fields :input').disabled);
 h.controls.quantities.df.data[0].accepted_qty=1;
 await h.view.scan('CFG:CMD:CONFIRM');await tick();
 const write=h.calls.find(c=>c.args.action==='Begin Delivery');assert.equal(write.args.payload.quantities[0].accepted_qty,3);assert.equal(write.args.payload.quantities[0].dispatch_allocation,'ALLOC');
});
test('scanner edits quantities without corrupting Customer Site QR and Return to Edit reopens corrections',async()=>{
 const h=panel({quantities:preparedQty(),requireScan:true});await tick();await h.view.scan('SITE');
 await h.view.scan('CFG:SELECT:2');await h.view.scan('CFG:CMD:DELIVERY_NEXT_ROW');await h.view.scan('CFG:QTY:MATERIAL:3');await h.view.scan('CFG:SELECT:3');await h.view.scan('Reduced order');
 assert.equal(h.controls.customer_scan.get_value(),'SITE');assert.equal(h.controls.quantities.get_value()[0].accepted_qty,'3');
 await h.view.scan('CFG:CMD:CONFIRM');assert(h.nodes.get('.driver-action-fields :input').disabled);
 await h.view.scan('CFG:CMD:RETURN_EDIT');assert(!h.nodes.get('.driver-action-fields :input').disabled);assert(h.nodes.get('.driver-action-scan').focused);
});
test('old return is reviewed before one controlled note with scanner and camera inputs',async()=>{
 const h=panel({step:'Collect Old Return'});await tick();
 await h.view.scan('CFG:CMD:RETURN_REASON');await h.view.scan('Old damaged goods');
 await h.view.scan('CFG:CMD:RETURN_ITEMS');await h.view.scan('CFG:CMD:RETURN_ADD_ITEM');await h.view.scan('ITEM');await h.view.scan('CFG:QTY:MATERIAL:3');
 await h.view.scan('CFG:CMD:CONFIRM');assert.equal(h.calls.filter(c=>c.method.endsWith('perform_driver_action')).length,0);assert.match(h.nodes.get('.driver-action-message').caption,/3 Nos/);
 await h.view.scan('CFG:CMD:CONFIRM');await tick();const req=h.calls.find(c=>c.args.action==='Collect Old Return');assert.equal(req.args.payload.lines[0].claimed_qty,'3');assert.equal(h.closed(),1);
});
test('invalid quantity preview is editable with scanner focus and creates no action request',async()=>{
 const h=panel({quantities:preparedQty(),previewFailure:new Error('Refusal reason required')});await tick();h.controls.quantities.df.data[0].accepted_qty=2;
 await h.view.scan('CFG:CMD:CONFIRM');assert.match(h.nodes.get('.driver-action-message').caption,/reason required/);assert(!h.nodes.get('.driver-action-fields :input').disabled);assert(h.nodes.get('.driver-action-scan').focused);
 assert.equal(h.calls.filter(c=>c.method.endsWith('perform_driver_action')).length,0);
});
test('old return unknown result retains original reviewed quantities across close and reopen',async()=>{
 const h=panel({step:'Collect Old Return',fail:new Error('lost response')});await tick();h.controls.lines.df.data=[{item_code:'ITEM',claimed_qty:3}];
 await h.view.scan('CFG:CMD:CONFIRM');await h.view.scan('CFG:CMD:CONFIRM');assert(h.view.controller.state.pending);await h.view.scan('CFG:CMD:CANCEL');
 const next=panel({existingStorage:h.storage});await tick();await next.view.scan('CFG:CMD:RETURN_EDIT');assert(next.view.controller.state.pending);await next.view.scan('CFG:CMD:CONFIRM');await tick();
 assert.equal(next.calls.find(c=>c.args.action==='Collect Old Return').args.payload.lines[0].claimed_qty,3);
});
test('existing note control is shown once and Supervisor release selects exact held line IDs',async()=>{
 const old=panel({step:'Collect Old Return'});await tick();assert(old.controls.existing_return_case);
 const h=panel({step:'Release Refused Stock',setup:{outcome:'OUT',rows:[{line_name:'LINE',item_code:'ITEM',refused_qty:2,stock_uom:'Nos',selected:1}]}});await tick();h.controls.reason.set_value('Approved');
 await h.view.scan('CFG:CMD:CONFIRM');await tick();const r=h.calls.find(c=>c.args.action==='Release Refused Stock');assert.deepEqual(r.args.payload,{outcome:'OUT',line_names:['LINE'],reason:'Approved'});
});

test('recording a refusal clears the quantity review so required proof inputs remain editable',async()=>{
 const proof={name:'POD',proof_policy:'Required',require_signature:0,require_photo:0,require_gps:0,allowed_dispositions:['Attended']};
 const h=panel({quantities:preparedQty(),proof});await tick();h.controls.quantities.df.data[0].accepted_qty=3;h.controls.quantities.df.data[0].refusal_reason='Downsize';
 await h.view.scan('CFG:CMD:CONFIRM');await h.view.scan('CFG:CMD:CONFIRM');await tick();
 assert.equal(h.nodes.get('.driver-action-fields :input').disabled,false);
 await h.view.scan('CFG:CMD:DELIVERY_RECIPIENT');await h.view.scan('Recipient');await h.view.scan('CFG:CMD:CONFIRM');await tick();
 assert.equal(h.calls.find(c=>c.args.action==='Submit Proof').args.payload.recipient_name,'Recipient');assert.equal(h.closed(),1);
});

test('optional sale opens only a native Session after required QR and pauses for product selection',async()=>{
 const h=panel({step:'Begin Open Sale',requireScan:true});await tick();await h.view.scan('CFG:CMD:CONFIRM');await tick();
 assert.equal(h.calls.filter(c=>c.method.endsWith('perform_driver_action')).length,0);
 await h.view.scan('SITE-QR');await h.view.scan('CFG:CMD:CONFIRM');await tick();
 assert.deepEqual(h.calls.filter(c=>c.method.endsWith('perform_driver_action')).map(c=>c.args.action),['Begin Open Sale']);
 assert.equal(h.calls.find(c=>c.args.action==='Begin Open Sale').args.payload.customer_scan,'SITE-QR');
 assert.match(h.nodes.get('.driver-action-fields').markup,/Add Product/);assert.equal(h.nodes.get('.driver-action-confirm').disabled,true);
});
test('reopened selected stock lazily loads native API and confirms one DN using existing proof controls',async()=>{
 const h=panel({step:'Select Route Stock',selectedStock:[{item_code:'BAG',visible_code:'<TAG>',allocated_qty:2,stock_uom:'Nos',state:'Reserved'}]});await tick();
 assert.match(h.nodes.get('.driver-action-fields').markup,/&lt;TAG>/);await h.view.scan('CFG:CMD:CONFIRM');await tick();
 assert.deepEqual(h.calls.filter(c=>c.method.endsWith('perform_driver_action')).map(c=>c.args.action),['Confirm Allocations','Create Delivery Note']);assert.equal(h.closed(),1);
});
test('shared stock child receives exact Session, forwards scans and closes with its parent',async()=>{
 const h=panel({step:'Select Route Stock'});await tick();await h.view.scan('CFG:CMD:ROUTE_ALLOCATE_STOCK');await tick();
 assert.equal(h.stock().deliverySession,'DELIVERY');assert.equal(h.stock().mode,'stock');await h.view.scan('TAG-QR');assert.deepEqual(h.stockScans,['TAG-QR']);
 h.view.focus();assert(h.stockFocus()>0);h.view.close();assert.equal(h.stockClosed(),1);assert.equal(h.closed(),1);
});
test('an unresolved native stock mutation blocks finishing the sale and remains recoverable',async()=>{
 const h=panel({step:'Select Route Stock',stockPending:true,selectedStock:[{item_code:'BAG',allocated_qty:2,state:'Reserved'}]});await tick();await h.view.scan('CFG:CMD:CONFIRM');await tick();
 assert.match(h.nodes.get('.driver-action-message').caption,/pending stock selection/);assert.equal(h.calls.filter(c=>c.method.endsWith('perform_driver_action')).length,0);
 assert(h.storage.getItem('cfg_kanban_route_action_pending_v1'));await h.view.scan('CFG:CMD:ROUTE_ALLOCATE_STOCK');assert.equal(h.stock().deliverySession,'DELIVERY');
});

test('lead adds an assistant by Employee ID with one reviewed action and no delivery mutation',async()=>{
 const h=panel({step:'Add Assistant',setup:{team:['EXISTING']}});await tick();
 assert.equal(h.controls.employee.df.options,'Employee');assert.match(h.nodes.get('.driver-action-message').caption,/EXISTING/);
 await h.view.scan('CFG:CMD:CONFIRM');await tick();assert.equal(h.calls.filter(c=>c.method.endsWith('perform_driver_action')).length,0);
 await h.view.scan('EMP-ASSISTANT');await h.view.scan('CFG:CMD:CONFIRM');await tick();
 const writes=h.calls.filter(c=>c.method.endsWith('perform_driver_action'));assert.equal(writes.length,1);
 assert.equal(writes[0].args.action,'Add Assistant');assert.deepEqual(writes[0].args.payload,{employee:'EMP-ASSISTANT'});
 assert.equal(writes[0].args.dispatch_plan,null);assert.equal(writes[0].args.stop_key,null);assert.equal(h.closed(),1);
});
test('uncertain assistant assignment retains original employee across Close and retry',async()=>{
 const h=panel({step:'Add Assistant',setup:{team:[]},fail:new Error('lost response')});await tick();await h.view.scan('HELP1');await h.view.scan('CFG:CMD:CONFIRM');await tick();
 assert(h.view.controller.state.pending);await h.view.scan('CFG:CMD:CANCEL');
 const next=panel({existingStorage:h.storage});await tick();await next.view.scan('HELP2');await next.view.scan('CFG:CMD:CONFIRM');await tick();
 const write=next.calls.find(c=>c.method.endsWith('perform_driver_action'));assert.equal(write.args.action,'Add Assistant');assert.equal(write.args.payload.employee,'HELP1');assert.equal(next.closed(),1);
});
test('assistant selection supports camera, safe Cancel and focus restoration',async()=>{
 const h=panel({step:'Add Assistant',setup:{team:[]}});await tick();h.events.get('click.cfg_driver_action .driver-action-camera')();await tick();
 h.cameras[0].opts.on_scan({decodedText:'HELP1'});await tick();assert.equal(h.controls.employee.get_value(),'HELP1');
 await h.view.scan('CFG:CMD:CANCEL');assert.equal(h.closed(),1);assert.equal(h.calls.filter(c=>c.method.endsWith('perform_driver_action')).length,0);
});

const orderStops=()=>['A','B','C'].map(stop_key=>({stop_key,label:'Shop '+stop_key,customer:'Customer '+stop_key}));
test('scanner reorders unfinished stops and records the exact displayed flexible order',async()=>{
 const h=panel({step:'Edit Route Order',setup:{enforced:false,stops:orderStops()}});await tick();
 await h.view.scan('CFG:SELECT:3');await h.view.scan('CFG:CMD:ROUTE_MOVE_UP');await h.view.scan('CFG:CMD:ROUTE_MOVE_UP');
 await h.view.scan('CFG:CMD:CONFIRM');await tick();const write=h.calls.find(c=>c.args.action==='Change Route Order');
 assert.deepEqual(write.args.payload.order,['C','A','B']);assert.equal(write.args.stop_key,null);assert.equal(write.args.dispatch_plan,null);assert.equal(h.closed(),1);
});
test('enforced order submits a reasoned proposal and never selects the approval scope for the Supervisor',async()=>{
 const h=panel({step:'Edit Route Order',setup:{enforced:true,stops:orderStops()}});await tick();await h.view.scan('CFG:SELECT:2');await h.view.scan('CFG:CMD:ROUTE_MOVE_UP');
 await h.view.scan('CFG:CMD:CONFIRM');assert(!h.calls.some(c=>c.method.endsWith('perform_driver_action')));assert.match(h.nodes.get('.driver-action-message').caption,/reason/);
 await h.view.scan('CFG:CMD:ROUTE_REASON');await h.view.scan('Customer closes early');await h.view.scan('CFG:CMD:CONFIRM');await tick();
 const write=h.calls.find(c=>c.args.action==='Request Route Change');assert.deepEqual(write.args.payload,{order:['B','A','C'],reason:'Customer closes early'});assert.equal(h.closed(),1);
});
test('touch arrows and drag/drop share the same customer order model',async()=>{
 const h=panel({step:'Edit Route Order',setup:{enforced:false,stops:orderStops()}});await tick();const row=new h.Node();row.attr('data-order-key','C');
 h.events.get('click.cfg_driver_action .driver-order-up')({currentTarget:row});await tick();
 h.events.get('dragstart.cfg_driver_action .driver-order-row')({currentTarget:row,originalEvent:{dataTransfer:{setData(){}}},preventDefault(){}});
 const target=new h.Node();target.attr('data-order-key','A');h.events.get('drop.cfg_driver_action .driver-order-row')({currentTarget:target,preventDefault(){}});await tick();
 await h.view.scan('CFG:CMD:CONFIRM');await tick();assert.deepEqual(h.calls.find(c=>c.args.action==='Change Route Order').args.payload.order,['C','A','B']);
});
test('both decision scopes are selectable during Supervisor review and rejection is explicit',async()=>{
 for(const mode of ['Next Customer Only','Entire Proposed Order']){
  const h=panel({step:'Decide Route Change',setup:{request_name:'KRC',state:'Pending',requested_by:'EMP',reason:'Traffic',current:orderStops(),proposed:orderStops().reverse(),approvable:true,modes:['Next Customer Only','Entire Proposed Order']}});await tick();
  assert.match(h.controls.approval_mode.df.options,/Next Customer Only\nEntire Proposed Order/);h.controls.approval_mode.set_value(mode);h.controls.reason.set_value('Checked');
  await h.view.scan('CFG:CMD:CONFIRM');await tick();assert.deepEqual(h.calls.find(c=>c.args.action==='Decide Route Change').args.payload,{request_name:'KRC',decision:'Approve',approval_mode:mode,reason:'Checked'});assert.equal(h.closed(),1);
 }
});
test('stale request only offers Reject and completed decision cannot be submitted again',async()=>{
 const setup={request_name:'KRC',state:'Pending',requested_by:'EMP',reason:'Traffic',current:orderStops(),proposed:orderStops().reverse(),approvable:false,modes:['Next Customer Only','Entire Proposed Order']};
 const h=panel({step:'Decide Route Change',setup});await tick();assert.equal(h.controls.decision.df.options,'Reject');h.controls.reason.set_value('Trip progressed');await h.view.scan('CFG:CMD:CONFIRM');await tick();assert.equal(h.calls.find(c=>c.args.action==='Decide Route Change').args.payload.decision,'Reject');
 const done=panel({step:'Decide Route Change',setup:{...setup,state:'Approved',decision_reason:'Checked'}});await tick();await done.view.scan('CFG:CMD:CONFIRM');assert(!done.calls.some(c=>c.method.endsWith('perform_driver_action')));
});
test('unknown route request survives Close and retry without replacing its order or reason',async()=>{
 const h=panel({step:'Edit Route Order',setup:{enforced:true,stops:orderStops()},fail:new Error('Lost response')});await tick();await h.view.scan('CFG:SELECT:2');await h.view.scan('CFG:CMD:ROUTE_MOVE_UP');await h.view.scan('CFG:CMD:ROUTE_REASON');await h.view.scan('Traffic');await h.view.scan('CFG:CMD:CONFIRM');assert(h.view.controller.state.pending);await h.view.scan('CFG:CMD:CANCEL');
 const next=panel({existingStorage:h.storage});await tick();await next.view.scan('CFG:CMD:ROUTE_MOVE_DOWN');assert(next.view.controller.state.pending);await next.view.scan('CFG:CMD:CONFIRM');await tick();const write=next.calls.find(c=>c.args.action==='Request Route Change');assert.deepEqual(write.args.payload,{order:['B','A','C'],reason:'Traffic'});assert.equal(next.closed(),1);
});
test('request cancellation and scanner safe Close retain distinct meanings',async()=>{
 const h=panel({step:'Cancel Route Change',setup:{request_name:'KRC'}});await tick();await h.view.scan('Office changed');await h.view.scan('CFG:CMD:CONFIRM');await tick();assert.deepEqual(h.calls.find(c=>c.args.action==='Cancel Route Change').args.payload,{request_name:'KRC',reason:'Office changed'});
 const other=panel({step:'Edit Route Order',setup:{enforced:false,stops:orderStops()}});await tick();await other.view.scan('CFG:CMD:CANCEL');assert.equal(other.closed(),1);assert(!other.calls.some(c=>c.method.endsWith('perform_driver_action')));
});
test('pure order model preserves source identities and refuses unknown drag targets',()=>{
 const source=orderStops(),model=api.stopOrder(source);model.move('C','A');assert.deepEqual(model.keys(),['C','A','B']);assert.deepEqual(source,orderStops());assert.throws(()=>model.move('UNKNOWN','A'),/current customer/);model.shift('C',-1);assert.deepEqual(model.keys(),['C','A','B']);
});

test('more than ten customers page their scanner numbers and keep a moved customer on its new page',async()=>{
 const stops=Array.from({length:21},(_,n)=>({stop_key:'K'+n,label:'Shop '+n,customer:'C'+n}));
 const h=panel({step:'Edit Route Order',setup:{enforced:false,stops}});await tick();assert.match(h.nodes.get('.driver-action-input-help').caption,/Numbered choices select customers/);
 await h.view.scan('CFG:CMD:NEXT_MATERIALS');await h.view.scan('CFG:SELECT:1');await h.view.scan('CFG:CMD:ROUTE_MOVE_UP');
 assert.match(h.nodes.get('.driver-order-help').caption,/10\. Shop 10/);await h.view.scan('CFG:CMD:ROUTE_REASON');await h.view.scan('Traffic');assert.match(h.nodes.get('.driver-action-input-help').caption,/ROUTE_REASON/);
 await h.view.scan('CFG:CMD:CONFIRM');await tick();const order=h.calls.find(c=>c.args.action==='Change Route Order').args.payload.order;assert.equal(order[9],'K10');assert.equal(order[10],'K9');assert.equal(order.length,21);
});

const cancellationSetup=()=>({request_type:'Cancel Customer Stop',target:{sequence:2,site_name:'<Shop>',customer:'BUYER',address:'Street',orders:[{sales_order:'SO1',customer_po:'PO1',item_code:'ITEM',planned_qty:4,stock_uom:'Nos'}],plans:[{name:'PLAN',state:'Loaded',vehicle_warehouse:'LORRY',sources:[{visible_code:'<TAG>',item_code:'ITEM',qty:4,stock_uom:'Nos',batch_no:'LOT'}]}]},goods_hash:'ORIGINAL-GOODS',has_loaded_goods:true,dispositions:['Keep Reserved for Return','Release for Same-trip Sale'],supervisor:true});
test('Supervisor cancellation shows exact goods and scanner reason/disposition use one reviewed request',async()=>{
 const h=panel({step:'Cancel Customer Stop',setup:cancellationSetup()});await tick();assert(h.nodes.get('.driver-action-fields').markup.includes('&lt;Shop&gt;'));assert(h.nodes.get('.driver-action-fields').markup.includes('&lt;TAG&gt;'));
 await h.view.scan('CFG:CMD:STOP_CANCEL_REASON');await h.view.scan('Customer closed');await h.view.scan('CFG:CMD:STOP_STOCK_DISPOSITION');await h.view.scan('Release for Same-trip Sale');await h.view.scan('CFG:CMD:CONFIRM');await tick();
 const sent=h.calls.filter(row=>row.method.endsWith('perform_driver_action'));assert.equal(sent.length,1);assert.equal(sent[0].args.action,'Cancel Customer Stop');assert.equal(sent[0].args.dispatch_plan,null);assert.equal(sent[0].args.stop_key,'STOP');assert.deepEqual(sent[0].args.payload,{reason:'Customer closed',goods_hash:'ORIGINAL-GOODS',stock_disposition:'Release for Same-trip Sale'});assert.equal(h.closed(),1);
});
test('driver cancellation records a request only and requires a reason',async()=>{
 const h=panel({step:'Request Stop Cancellation',setup:{...cancellationSetup(),supervisor:false}});await tick();await h.view.scan('CFG:CMD:CONFIRM');assert(!h.calls.some(row=>row.method.endsWith('perform_driver_action')));
 await h.view.scan('CFG:CMD:STOP_CANCEL_REASON');await h.view.scan('Customer asked to cancel');await h.view.scan('CFG:CMD:CONFIRM');await tick();const sent=h.calls.find(row=>row.method.endsWith('perform_driver_action'));assert.equal(sent.args.action,'Request Stop Cancellation');assert.deepEqual(sent.args.payload,{reason:'Customer asked to cancel'});
});
test('Supervisor cancellation approval offers stock disposition instead of sequence approval scope',async()=>{
 const setup={...cancellationSetup(),request_name:'KRC',state:'Pending',requested_by:'DRIVER',reason:'Closed',approvable:true},h=panel({step:'Decide Route Change',setup});await tick();assert(h.controls.stock_disposition);assert(!h.controls.approval_mode);
 h.controls.reason.set_value('Confirmed with customer');h.controls.stock_disposition.set_value('Keep Reserved for Return');await h.view.scan('CFG:CMD:CONFIRM');await tick();const sent=h.calls.find(row=>row.args.action==='Decide Route Change');assert.equal(sent.args.payload.goods_hash,'ORIGINAL-GOODS');assert.equal(sent.args.payload.stock_disposition,'Keep Reserved for Return');assert.equal(sent.args.payload.request_name,'KRC');assert.equal(h.closed(),1);
});
test('lost cancellation response freezes its exact source/stock decision and reload retries original identity',async()=>{
 const h=panel({step:'Cancel Customer Stop',setup:cancellationSetup(),fail:new Error('Lost')});await tick();h.controls.reason.set_value('Customer closed');await h.view.scan('CFG:CMD:CONFIRM');const original=h.calls.find(row=>row.args.action==='Cancel Customer Stop').args;h.view.close();
 const next=panel({step:'Cancel Customer Stop',setup:{...cancellationSetup(),goods_hash:'CHANGED'},existingStorage:h.storage});await tick();await next.view.scan('CFG:CMD:CONFIRM');await tick();const replay=next.calls.find(row=>row.args.action==='Cancel Customer Stop').args;assert.equal(replay.event_token,original.event_token);assert.deepEqual(replay.payload,original.payload);assert.equal(next.closed(),1);
});

const loosePack=()=>({name:'KLT-1',qr_payload:'CFG:LOOSE:KLT-1',state:'Ready',lines:[{dispatch_allocation:'ALLOCATION',item_code:'A',stock_uom:'Nos',qty:5,source_visible_code:'SOURCE-A'},{dispatch_allocation:'B-ALLOC',item_code:'B',stock_uom:'Nos',qty:2,source_visible_code:'SOURCE-B'}]});
test('Loose Tag scan reveals both lines on existing delivery screen and gates full acceptance',async()=>{
 const h=panel({quantities:preparedQty(),looseTags:[loosePack()]});await tick();
 await h.view.scan('CFG:CMD:CONFIRM');await tick();assert.equal(h.calls.filter(c=>c.method.endsWith('perform_driver_action')).length,0);
 await h.view.scan('CFG:LOOSE:KLT-1');await tick();assert(h.nodes.get('.driver-action-message').caption.includes('SOURCE-A'));assert(h.nodes.get('.driver-action-message').caption.includes('SOURCE-B'));
 await h.view.scan('CFG:CMD:CONFIRM');await tick();assert.equal(h.calls.filter(c=>c.args.action==='Begin Delivery').length,1);
});
test('Open Route Loose Tag uses existing accepted/refused table and review before sale confirmation',async()=>{
 const h=panel({step:'Begin Open Sale',quantities:preparedQty(),looseTags:[loosePack()]});await tick();await h.view.scan('CFG:LOOSE:KLT-1');
 h.controls.quantities.df.data[0].accepted_qty=3;h.controls.quantities.df.data[0].refusal_reason='Downsize';
 await h.view.scan('CFG:CMD:CONFIRM');assert(h.calls.some(c=>c.method.endsWith('preview_open_quantities')));assert(!h.calls.some(c=>c.args.action==='Begin Open Sale'));
 await h.view.scan('CFG:CMD:CONFIRM');await tick();const call=h.calls.find(c=>c.args.action==='Begin Open Sale');assert.equal(call.args.payload.quantities[0].accepted_qty,3);
});
test('wrong Loose Tag stays on the stop screen, posts nothing and restores scanner focus',async()=>{
 const h=panel({quantities:preparedQty(),looseTags:[loosePack()]});await tick();await h.view.scan('CFG:LOOSE:OTHER');await tick();
 assert(!h.calls.some(c=>c.method.endsWith('perform_driver_action')));assert(h.nodes.get('.driver-action-message').caption.includes('Wrong customer'));assert(h.nodes.get('.driver-action-scan').focused);
});

test('Customer Identified selection shows Add Product, the current Session and restores scanner focus',async()=>{
 const h=panel({step:'Select Route Stock',sessionState:'Customer Identified'});await tick();
 assert.match(h.nodes.get('.driver-action-fields').markup,/Add Product \/ Scan Stock/);
 assert.match(h.nodes.get('.driver-action-summary').markup,/DELIVERY/);assert.match(h.nodes.get('.driver-action-summary').markup,/Customer Identified/);
 h.events.get('click.cfg_driver_action .driver-action-add-stock')();await tick();
 assert.equal(h.stock().deliverySession,'DELIVERY');assert.equal(h.stock().mode,'stock');assert.equal(h.calls.filter(c=>c.method.endsWith('perform_driver_action')).length,0);
 h.stock().onClose();assert(h.nodes.get('.driver-action-scan').focused);
});
test('printed Allocate Open Route Stock command opens goods selection in the same Session',async()=>{
 const h=panel({step:'Select Route Stock',sessionState:'Customer Identified'});await tick();
 await h.view.scan('CFG:CMD:ALLOCATE_ROUTE_STOCK');await tick();assert.equal(h.stock().deliverySession,'DELIVERY');
 await h.view.scan('SOURCE-QR');assert.deepEqual(h.stockScans,['SOURCE-QR']);
 h.view.close();assert.equal(h.stockClosed(),1);
});
test('genuine blocked state displays Session, note and exception links without posting or hiding the problem',async()=>{
 const h=panel({step:'Blocked',sessionState:'Exception',recoveryMessage:'Open Route Session DELIVERY is Exception. Open Kanban Logistics.',exception:'EX-1'});await tick();
 assert.match(h.nodes.get('.driver-action-message').caption,/Kanban Logistics/);
 assert.match(h.nodes.get('.driver-action-summary').markup,/cfg-kanban-delivery-session\/DELIVERY/);
 assert.match(h.nodes.get('.driver-action-summary').markup,/delivery-note\/DN/);assert.match(h.nodes.get('.driver-action-summary').markup,/cfg-kanban-exception\/EX-1/);
 assert.equal(h.nodes.get('.driver-action-confirm').disabled,true);await h.view.scan('CFG:CMD:CONFIRM');await tick();
 assert.equal(h.calls.filter(c=>c.method.endsWith('perform_driver_action')).length,0);assert(h.nodes.get('.driver-action-scan').focused);
});
