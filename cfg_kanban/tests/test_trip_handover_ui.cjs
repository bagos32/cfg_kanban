/* Real controller functions with explicit RPC/storage doubles; no site/device acceptance. */
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const api=require('../public/js/trip_handover.js');
const prefix='cfg_kanban.services.';
function harness(){
 const values=new Map([['cfg_kanban_operator_session','TOKEN']]),calls=[],events=[];
 const storage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
 const row={dispatch_allocation:'TAG',handling_unit:'HU',visible_code:'TAG1',item_code:'ITEM',remaining_qty:5,stock_uom:'Nos'};
 const loose={dispatch_allocation:'LOOSE',handling_unit:null,item_code:'LOOSE-ITEM',remaining_qty:6,stock_uom:'Kg'};
 let ctx={operator:{employee:'SUP',employee_name:'Supervisor',kanban_role:'Supervisor'},can_manage:true,can_start:true,can_complete:true,
  trip:{name:'KTRIP-1'},plans:[{name:'DPL-1',state:'Loaded',balances:[row,loose]}],returns:[{name:'KRTN-1'}],trips:[],start:0,return_start:0};
 let detail={plan:{name:'DPL-1'},review:{name:'KDR-1',state:'Reviewing'},balance_hash:'HASH',balances:[row,loose],
  recovery_routes:[{name:'RETURN',destination_warehouse:'Warehouse'},{name:'QC',destination_warehouse:'Quarantine'}]};
 let fail=null,wait=null,count=0;
 const env={storage,locks:{request:async(_name,_options,work)=>work({name:'LOCK'})},user:'erp@example.com',nonce:()=>`EVENT-${++count}`,render:()=>{},camera:()=>events.push('camera'),
  openMovement:v=>events.push(['movement',v]),openReview:v=>events.push(['review',v]),openQC:v=>events.push(['QC',v]),openCount:()=>events.push('count'),
  async rpc(method,args){calls.push({method,args:structuredClone(args)});if(wait)return wait(method,args);if(fail&&method.endsWith('create_mixed_dispatch_recovery'))throw fail;
   if(method.endsWith('get_trip_handover'))return structuredClone(ctx);
   if(method.endsWith('get_plan_handover_context'))return structuredClone(detail);
   if(method.endsWith('login_operator'))return {session_token:'NEW-TOKEN'};
   return {};
  }};
 const c=api.controller(env);return {c,calls,events,storage,values,row,loose,env,get context(){return ctx;},get detail(){return detail;},setFail:v=>fail=v,setWait:v=>wait=v};
}
async function opened(){const h=harness();await h.c.showPage('KTRIP-1');await h.c.selectPlan('DPL-1');return h;}
async function assign(c,number,destination,qty){await c.scan('CFG:CMD:HANDOVER_ITEMS');await c.scan('CFG:SELECT:'+number);await c.scan('CFG:CMD:HANDOVER_DESTINATION');await c.scan('CFG:SELECT:'+destination);if(qty!==undefined)await c.scan('CFG:QTY:MATERIAL:'+qty);await c.scan('CFG:CMD:HANDOVER_ADD');}
test('QR parser accepts Trip/Plan/Review and operator fragment, never treats arbitrary URL as credential',()=>{
 assert.deepEqual(api.identity('DRS-DEMO'),{source:'DRS-DEMO'});
 assert.deepEqual(api.identity('https://erp/app/cfg-kanban-route-sheet/DRS-DEMO'),{source:'DRS-DEMO'});
 assert.deepEqual(api.identity('https://erp/app/cfg-kanban-delivery-trip/KTRIP-1'),{source:'KTRIP-1'});
 assert.deepEqual(api.identity('https://erp/app/kanban-trip-handover/DPL-1'),{source:'DPL-1'});
 assert.deepEqual(api.identity('https://erp/app/kanban-operator#operator=SECRET'),{credential:'SECRET'});
});
test('scanner can assign whole tag to keep and split loose quantities to two destinations',async()=>{
 const {c}=await opened();await assign(c,1,1);await assign(c,2,2,3);await assign(c,2,3,3);
 assert.deepEqual(c.state.choices,[{dispatch_allocation:'TAG',action:'Keep on Lorry',logistics_route:null,qty:5},
  {dispatch_allocation:'LOOSE',action:'Return / Transfer',logistics_route:'RETURN',qty:3},
  {dispatch_allocation:'LOOSE',action:'Return / Transfer',logistics_route:'QC',qty:3}]);
});
test('explicit approval freezes one exact payload and original nonce before RPC',async()=>{
 const h=await opened();await assign(h.c,1,1);await assign(h.c,2,2);await h.c.scan('CFG:CMD:HANDOVER_REASON');await h.c.scan('Trip completed');await h.c.scan('CFG:CMD:HANDOVER_APPROVE');await h.c.scan('CFG:CMD:CONFIRM');
 const call=h.calls.find(row=>row.method.endsWith('create_mixed_dispatch_recovery'));
 assert.equal(call.args.balance_hash,'HASH');assert.equal(call.args.reason,'Trip completed');assert.equal(JSON.parse(call.args.dispositions).length,2);assert.equal(call.args.event_token,'EVENT-1');assert.equal(h.c.state.pending,null);
});
test('unknown submission retains payload across Back, refresh and panel reopening',async()=>{
 const h=await opened();h.setFail(new Error('Network lost'));await assign(h.c,1,1);await assign(h.c,2,2);h.c.set('reason','Trip completed');h.c.intent('approve');await h.c.confirm();const pending=structuredClone(h.c.state.pending);
 assert.ok(pending);assert.throws(()=>h.c.set('reason','Changed'),/original/);await h.c.scan('CFG:CMD:CANCEL');assert.ok(h.c.state.pending);
 h.c.hide();await h.c.showPage('KTRIP-1');assert.deepEqual(h.c.state.pending,pending);await h.c.confirm();
 const calls=h.calls.filter(r=>r.method.endsWith('create_mixed_dispatch_recovery'));assert.deepEqual(calls[0].args,calls[1].args);
});
test('confirmed first validation rejection permits correction; replay conflict retains request',async()=>{
 const h=await opened();await assign(h.c,1,1);h.c.set('reason','Done');h.c.intent('approve');h.setFail({exc_type:'ValidationError',message:'Missing quantity'});await h.c.confirm();assert.equal(h.c.state.pending,null);h.c.set('reason','Corrected');
 h.setFail({exc_type:'DispatchRecoveryReplayError',message:'Identity conflict'});h.c.intent('approve');await h.c.confirm();assert.ok(h.c.state.pending);
});
test('a physical tag cannot be partially assigned or over-allocated in the client',async()=>{
 const {c}=await opened();await c.select(1);c.show('destinations');await c.select(2);c.set('qty','2');assert.throws(()=>c.add(),/stay whole/);c.set('qty','6');assert.throws(()=>c.add(),/exceed/);
});
test('existing tag identity can select source out of sequence',async()=>{
 const {c}=await opened();await c.scan('TAG1');assert.equal(c.state.item.dispatch_allocation,'TAG');assert.equal(c.state.qty,'5');
});
test('choices can be removed by numbered scanner selection before submission',async()=>{
 const {c}=await opened();await assign(c,1,1);await c.scan('CFG:CMD:HANDOVER_CHOICES');await c.scan('CFG:SELECT:1');assert.equal(c.state.choices.length,0);
});
test('Begin Review and cancellation each require explicit intent and reason where applicable',async()=>{
 const h=await opened();h.c.intent('begin');await h.c.confirm();assert.ok(h.calls.some(c=>c.method.endsWith('begin_dispatch_review')));
 h.c.intent('cancel');await assert.rejects(h.c.confirm(),/reason/);h.c.set('reason','Correct destinations');await h.c.confirm();assert.ok(h.calls.some(c=>c.method.endsWith('cancel_mixed_dispatch_recovery')));
});
test('driver can read summary and QC links but cannot approve stock decisions',async()=>{
 const h=harness();h.context.can_manage=false;await h.c.showPage('KTRIP-1');assert.equal(h.c.state.context.plans.length,1);h.c.show('returns');await h.c.select(1);assert.deepEqual(h.events,[['QC','KRTN-1']]);assert.throws(()=>h.c.intent('approve'),/Supervisor/);
});
test('recovery selection opens the exact second destination instead of the first one',async()=>{
 const h=await opened();h.c.state.detail.mixed_recovery={active:true,groups:[{manifest:'KMF-1'},{manifest:'KMF-2'}]};h.c.show('movements');await h.c.select(2);assert.deepEqual(h.events,[['movement','KMF-2']]);
});
test('count, finish, camera and Help share the scanner path',async()=>{
 const h=await opened();for(const command of ['HANDOVER_COUNT','HANDOVER_FINISH','HANDOVER_CAMERA','HELP'])await h.c.scan('CFG:CMD:'+command);assert.deepEqual(h.events,['count',['review','DPL-1'],'camera']);assert.match(h.c.state.message,/fresh D3 count/);
});
test('operator switch removes old private display and cannot submit previous choices',async()=>{
 const h=await opened();await assign(h.c,1,1);h.storage.setItem('cfg_kanban_operator_session','OTHER');await assert.rejects(h.c.scan('CFG:CMD:CONFIRM'),/Operator changed/);assert.equal(h.c.state.context,null);assert.equal(h.c.state.detail,null);assert.equal(h.c.state.choices.length,0);
});
test('late response after page hide never restores old trip data',async()=>{
 const h=harness();let resolve;h.setWait(()=>new Promise(r=>resolve=r));const opening=h.c.showPage('KTRIP-1');h.c.hide();resolve(structuredClone(h.context));await opening;assert.equal(h.c.state.context,null);assert.equal(h.c.state.operator,null);
});
test('Web Locks unavailable or already held blocks submission before persistence or RPC',async()=>{
 const h=await opened();h.c.intent('begin');h.env.locks=null;await assert.rejects(h.c.confirm(),/Web Locks/);
 h.env.locks={request:async(_name,_options,work)=>work(null)};await assert.rejects(h.c.confirm(),/Another tab/);
 assert.equal(h.c.state.pending,null);assert.equal(h.calls.filter(c=>c.method.endsWith('begin_dispatch_review')).length,0);
});
test('another tab pending request cannot be overwritten or redirected to another API',async()=>{
 const h=await opened();await assign(h.c,1,1);h.c.set('reason','Done');h.c.intent('approve');h.setFail(new Error('Lost'));
 await h.c.confirm();const key=[...h.values.keys()].find(k=>k.startsWith('cfg_trip_handover_pending:'));
 const other=JSON.parse(h.values.get(key));other.args.reason='Other tab';h.values.set(key,JSON.stringify(other));
 await assert.rejects(h.c.confirm(),/Another tab changed/);assert.equal(h.calls.filter(r=>r.method.endsWith('create_mixed_dispatch_recovery')).length,1);
 other.method='cfg_kanban.services.unrelated_action';h.values.set(key,JSON.stringify(other));h.c.hide();await h.c.showPage('KTRIP-1');assert.match(h.c.state.message,/investigation/);
});
test('normal page has camera, Tab/Enter, focus restoration and entry points/catalogue',()=>{
 const root=path.resolve(__dirname,'..'),read=p=>fs.readFileSync(path.join(root,p),'utf8'),page=read('public/js/trip_handover.js');
 for(const value of ['Scan with Camera',"['Enter','Tab']",'finally(focus)','storage','on_page_hide'])assert.ok((page+read('cfg_kanban/page/kanban_trip_handover/kanban_trip_handover.js')).includes(value),value);
 for(const file of ['public/js/driver_route.js','cfg_kanban/page/kanban_operator/kanban_operator.js','cfg_kanban/page/kanban_logistics/kanban_logistics.js','api/operator.py'])assert.match(read(file),/TRIP_HANDOVER/);
 for(const command of ['HANDOVER_ITEMS','HANDOVER_DESTINATION','HANDOVER_ADD','HANDOVER_APPROVE','HANDOVER_CANCEL_DECISIONS','HANDOVER_REASON','HANDOVER_MOVEMENTS','HANDOVER_FINISH','HANDOVER_RETURNS','HANDOVER_CAMERA'])assert.ok(read('api/operator.py').includes('CFG:CMD:'+command));
 assert.match(read('cfg_kanban/doctype/cfg_kanban_delivery_trip/cfg_kanban_delivery_trip.js'),/Trip Handover/);
});


test('Next Guided Step opens missing reviews, pending movement, one count and next Plan with that count',async()=>{
 const h=await opened();h.context.closure_guide={stage:0,plan:'DPL-1',message:'Open review'};await h.c.refresh();await h.c.scan('CFG:CMD:HANDOVER_NEXT_STEP');assert.equal(h.c.state.intent,'begin');
 h.context.closure_guide={stage:1,plan:'DPL-1',manifest:'KMF-PENDING'};await h.c.refresh();await h.c.scan('CFG:CMD:HANDOVER_NEXT_STEP');assert.deepEqual(h.events.at(-1),['movement','KMF-PENDING']);
 h.context.closure_guide={stage:2,plan:'DPL-1'};await h.c.refresh();await h.c.scan('CFG:CMD:HANDOVER_NEXT_STEP');assert.equal(h.events.at(-1),'count');
 let received;h.env.openReview=(plan,count)=>{received={plan,count};};h.context.closure_guide={stage:3,plan:'DPL-1',shared_count:'ONE-COUNT'};await h.c.refresh();await h.c.scan('CFG:CMD:HANDOVER_NEXT_STEP');assert.deepEqual(received,{plan:'DPL-1',count:'ONE-COUNT'});
 h.env.openRoute=name=>h.events.push(['route',name]);h.context.closure_guide={stage:4,route_sheet:'SHEET'};await h.c.refresh();await h.c.scan('CFG:CMD:HANDOVER_NEXT_STEP');assert.deepEqual(h.events.at(-1),['route','SHEET']);
});

test('guided unfinished proof opens its exact existing Delivery Session',async()=>{
 const h=await opened();let selected;h.env.openDelivery=name=>selected=name;h.context.closure_guide={stage:0,plan:'DPL-1',delivery_session:'NEEDS-PROOF'};
 await h.c.refresh();await h.c.scan('CFG:CMD:HANDOVER_NEXT_STEP');assert.equal(selected,'NEEDS-PROOF');
});
