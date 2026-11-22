/* Actual driver route controller, rendering and page bindings with offline RPC/DOM doubles. */
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const ui = require('../public/js/driver_route.js');
const SESSION = 'cfg_kanban_operator_session';
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => { resolve=a; reject=b; }); return {promise, resolve, reject}; };
const trip = 'KTRIP-2026-00001';
const item = { item_code: 'BAG', item_name: 'Plastic Bag', is_stock_item: 1, stock_uom: 'Nos', planned_qty: 5, loaded_qty: 4, delivered_qty: 1, remaining_qty: 3, orders: [{sales_order: 'SO1', customer_po: 'PO1'}] };
const stop = { stop_key: 'STOP1', sequence: 1, office_sequence: 1, customer_name: 'ABC', site_name: 'Shop', address: 'Street', purpose: 'Delivery', state: 'Awaiting proof', items: [item], sources: [{ tag_code: 'RM1', item_code: 'BAG', stock_uom: 'Nos', remaining_qty: 3, batch_no: 'LOT', source_state: 'Loaded' }], plans: [{name: 'PLAN', session_accessible: true, delivery_session: 'DEL1', session_state: 'Delivered'}] };
const detail = { trip: {name: trip, trip_title: 'North', company: 'A'}, next_stop_key: 'STOP1', current_stop_key: 'STOP1', stops: [stop], total_stops: 1, completed_stops: 0, sequence_source: 'Office plan', warnings: [], refreshed_on: '2026-11-21' };
function harness() {
  const data = new Map([[SESSION, 'TOKEN']]), calls = [], views = [], notices = [];
  const storage = {getItem: key => data.get(key) || null, setItem: (key,value) => data.set(key,value), removeItem: key => data.delete(key)};
  let respond = async method => method.endsWith('get_driver_trips') ? {operator: {employee: 'EMP'}, trips: [{name: trip, planning_state: 'Planned'}]} : method.endsWith('get_driver_trip') ? structuredClone(detail) : {session_token: 'NEW'};
  const app = ui.controller({storage, call: async (method,args) => {calls.push({method,args}); return respond(method,args);}, render: state => views.push(structuredClone(state)), notify: text => notices.push(text)});
  return {app,data,storage,calls,views,notices,respond: fn => {respond=fn;}};
}
test('uses existing operator session and exact trip; refresh calls only read services', async () => {
  const h=harness();await h.app.show(trip);
  assert.equal(h.app.state.detail.trip.name,trip);assert.equal(h.app.state.operator.employee,'EMP');
  assert.equal(h.calls.length,2);assert(h.calls.every(row => row.args.operator_session_token==='TOKEN'));
  assert(h.calls.every(row => /get_driver_trips|get_driver_trip/.test(row.method)));
});
test('list pagination and closed-history choice retain explicit current trip', async () => {
  const h=harness();await h.app.show(trip);await h.app.page(1);
  assert.equal(h.calls.at(-2).args.start,20);await h.app.showClosed(true);
  assert.equal(h.calls.at(-2).args.include_closed,1);assert.equal(h.calls.at(-2).args.start,0);
});
test('out-of-order responses never replace a newer trip', async () => {
  const h=harness(), old=deferred();
  h.respond(async (method,args) => method.endsWith('get_driver_trips') ? {operator:{employee:'EMP'},trips:[]} : args.trip_name===trip ? old.promise : {...structuredClone(detail),trip:{name:'KTRIP-OTHER'}});
  const first=h.app.select(trip);await Promise.resolve();await Promise.resolve();
  await h.app.select('KTRIP-OTHER');old.resolve(detail);await first;
  assert.equal(h.app.state.detail.trip.name,'KTRIP-OTHER');
});
test('operator switch clears all customer details and pending read results', async () => {
  const h=harness();await h.app.show(trip);const wait=deferred();h.respond(() => wait.promise);
  const request=h.app.refresh();h.app.changeOperator();wait.resolve({operator:{employee:'OLD'},trips:[]});await request;
  assert.equal(h.app.state.detail,null);assert.equal(h.app.state.operator,null);assert.equal(h.app.state.trips.length,0);
  assert.equal(h.data.has(SESSION),false);
});
test('storage change during a read clears the stale view and releases busy guard', async () => {
  const h=harness();await h.app.show(trip);const wait=deferred();h.respond(() => wait.promise);
  const request=h.app.refresh();h.data.set(SESSION,'OTHER');wait.resolve({operator:{employee:'OLD'},trips:[]});await request;
  assert.equal(h.app.state.detail,null);assert.equal(h.app.state.token,'OTHER');assert.equal(h.app.state.busy,false);
});
test('expired session clears source data; permission rejection never becomes logout', async () => {
  const h=harness();await h.app.show(trip);
  h.respond(() => {throw {exc_type:'PermissionError',message:'No longer assigned'};});await h.app.refresh(trip,false);
  assert.equal(h.app.state.detail,null);assert.equal(h.data.get(SESSION),'TOKEN');
  h.respond(() => {throw new Error('Operator session expired');});await h.app.refresh();
  assert.equal(h.app.state.token,null);assert.equal(h.app.state.busy,false);assert.equal(h.data.has(SESSION),false);
});
test('background network failure marks a previous view stale without inventing freshness', async () => {
  const h=harness();await h.app.show(trip);h.respond(() => {throw new Error('Network offline');});
  await h.app.refresh(trip,false);assert.equal(h.app.state.stale,true);assert.equal(h.app.state.detail.refreshed_on,'2026-11-21');
});
test('viewing another stop never starts or completes delivery', async () => {
  const h=harness();await h.app.show(trip);const before=h.calls.length;
  h.app.viewStop('STOP1');assert.equal(h.app.state.stop,'STOP1');assert.equal(h.calls.length,before);
  h.app.viewStop('UNKNOWN');assert.equal(h.app.state.stop,'STOP1');
});
test('trip QR before login is not sent as an operator credential', async () => {
  const h=harness();h.data.clear();await h.app.scan(trip);
  assert.equal(h.calls.length,0);assert.equal(h.app.state.selected,trip);assert(h.notices[0].includes('Sign in'));
});
test('PIN login uses existing authentication and pending selected trip', async () => {
  const h=harness();h.data.clear();await h.app.scan(trip);await h.app.scan('operator-secret','1234','Cab');
  assert.equal(h.calls[0].method,'cfg_kanban.api.operator.login_operator');assert.equal(h.calls[0].args.pin,'1234');
  assert.equal(h.calls.at(-1).args.trip_name,trip);assert.equal(h.data.get(SESSION),'NEW');
});
test('blocked browser storage explains login failure and does not expose a route', async () => {
  const h=harness();h.data.clear();h.storage.setItem=() => {throw new Error('blocked');};await h.app.identify('credential');
  assert.match(h.app.state.error,/storage/);assert.equal(h.app.state.detail,null);
});
test('Trip and operator QR classification permits no arbitrary URL navigation', () => {
  assert.equal(ui.scan('https://erp.example/app/kanban-driver-route/'+trip).value,trip);
  assert.equal(ui.scan('https://erp.example/app/cfg-kanban-delivery-trip/'+trip).kind,'trip');
  assert.equal(ui.scan('https://erp.example/app/kanban-operator#operator=secret').kind,'operator');
  assert.equal(ui.scan('https://other.example/random').kind,'unknown');
});
test('rendering escapes source text and keeps quantities, stock UOM, PO and tag visible', () => {
  const data=structuredClone(detail);data.stops[0].customer_name='<script>';data.stops[0].instructions='<img src=x>';
  const html=ui.detailView({detail:data});
  for(const value of ['BAG','Nos','SO1','PO1','RM1','LOT','Remaining to deliver','Awaiting proof'])assert(html.includes(value),value);
  assert(html.includes('&lt;script&gt;'));assert(!html.includes('<img src=x>'));
  assert(ui.tripList({trips:[{name:trip,planning_state:'Planned'}],start:0}).includes('Planned'));
});
test('session handoff is shown only for accessible active sessions; visit-only never fakes completion', () => {
  const data=structuredClone(detail);data.stops[0].plans[0].session_accessible=false;
  assert(!ui.detailView({detail:data}).includes('data-delivery='));data.stops[0].purpose='Visit Only';
  assert(ui.detailView({detail:data}).includes('record the visit'));
  assert(!ui.detailView({detail:data}).includes('data-complete-stop='));
});
test('hiding page ignores late RPC responses and does not leave a polling busy state', async () => {
  const h=harness(), wait=deferred();h.respond(() => wait.promise);const pending=h.app.show(trip);
  h.app.hide();wait.resolve({operator:{employee:'EMP'},trips:[]});await pending;
  assert.equal(h.app.state.detail,null);assert.equal(h.app.state.busy,false);
});
function domHarness() {
  const h=harness(), events=new Map(), nodes=new Map(), cameras=[], focuses=[], routes=[];let current=['kanban-driver-route'];
  class Node {
    constructor() {this.value='';this.attributes={};}
    html(value){this.markup=value;return this;}text(value){this.caption=value;return this;}val(value){if(arguments.length){this.value=value;return this;}return this.value;}
    appendTo(){return this;}toggle(){return this;}prop(){return this;}trigger(name){focuses.push(name);return this;}
    find(selector){if(!nodes.has(selector))nodes.set(selector,new Node());return nodes.get(selector);}
    on(type,selector,callback){if(typeof selector==='function')events.set(type,selector);else events.set(type+' '+selector,callback);return this;}
    attr(key){return this.attributes[key];}
  }
  global.$=value=>value instanceof Node?value:new Node();global.localStorage=h.storage;
  global.__=value=>value;global.document={hidden:false};
  global.window={addEventListener(type,callback){events.set(type,callback);}};
  global.setInterval=callback=>{events.set('tick',callback);return 1;};global.clearInterval=()=>events.delete('tick');
  global.frappe={ui:{make_app_page:()=>({main:new Node()}),Scanner:class{constructor(options){this.options=options;this.dialog={$wrapper:new Node(),hide(){}};cameras.push(this);}stop_scan(){this.stopped=true;}}},
    call:async({method,args})=>({message:method.endsWith('get_driver_trips')?{operator:{employee:'EMP'},trips:[]}:structuredClone(detail)}),
    router:{on:(event,callback)=>events.set('router:'+event,callback)},get_route:()=>current,set_route:(...args)=>{routes.push(args);current=args;}};
  const view=ui.mount({});
  return {...h,view,events,nodes,cameras,focuses,routes,current:value=>{current=value;},Node};
}
const flush=async()=>{for(let n=0;n<30;n++)await Promise.resolve();};
test('keyboard Enter and Tab submit the same trip; blank/modified keys retain ordinary navigation', async () => {
  const h=domHarness();await h.view.show();const input=h.nodes.get('.cfg-driver-scan');
  let prevented=0;const key=h.events.get('keydown.cfg_driver .cfg-driver-scan');
  for(const code of ['Enter','Tab']){input.val(trip);key({key:code,preventDefault(){prevented++;},stopPropagation(){}});await flush();}
  input.val('');key({key:'Tab'});input.val(trip);key({key:'Tab',shiftKey:true});
  assert.equal(prevented,2);assert.equal(h.view.app.state.detail.trip.name,trip);assert(h.focuses.includes('focus'));h.view.hide();
});
test('camera accepts one scan and discards delayed result after hide or operator switch', async () => {
  const h=domHarness();await h.view.show();const camera=h.events.get('click.cfg_driver .cfg-driver-camera');
  camera();h.cameras[0].options.on_scan({decodedText:trip});h.cameras[0].options.on_scan({decodedText:'KTRIP-OTHER'});await flush();
  assert.equal(h.view.app.state.selected,trip);assert(h.cameras[0].stopped);
  camera();h.view.hide();h.cameras[1].options.on_scan({decodedText:'KTRIP-LATE'});await flush();
  assert.equal(h.view.app.state.selected,trip);
});
test('camera absence gives a useful message and returns scanner focus', async () => {
  const h=domHarness();await h.view.show();frappe.ui.Scanner=null;
  h.events.get('click.cfg_driver .cfg-driver-camera')();assert.match(h.nodes.get('.cfg-driver-notice').caption,/unavailable/);assert(h.focuses.includes('focus'));h.view.hide();
});
test('logistics handoff calls its established session reader without a delivery mutation', async () => {
  const source=fs.readFileSync(path.join(__dirname,'../cfg_kanban/page/kanban_logistics/kanban_logistics.js'),'utf8');
  const start=source.indexOf('if (frappe.route_options?.cfg_driver_delivery_session)');
  const end=source.indexOf('if (frappe.route_options?.cfg_lorry_route)',start);let opened=null;
  await new Function('frappe','sync_session_from_storage','load','open_delivery_session','return (async()=>{'+source.slice(start,end)+'})()')(
    {route_options:{cfg_driver_delivery_session:'DEL1'}},()=>false,async()=>{},async name=>{opened=name;});assert.equal(opened,'DEL1');
});
test('opening existing delivery selects exact session and only navigates to its established workflow', async () => {
  const h=domHarness();await h.view.show(trip);const target=new h.Node();target.attributes['data-delivery']='DEL1';
  h.events.get('click.cfg_driver .cfg-driver-open-delivery')({currentTarget:target});
  assert.deepEqual(frappe.route_options,{cfg_driver_delivery_session:'DEL1'});assert.deepEqual(h.routes.at(-1),['kanban-logistics']);h.view.hide();
});
test('existing Logistics adapter consumes handoff without starting or posting a delivery', async () => {
  const source=fs.readFileSync(path.join(__dirname,'../cfg_kanban/page/kanban_logistics/kanban_logistics.js'),'utf8');
  const start=source.indexOf('\t\tif (frappe.route_options?.cfg_driver_delivery_session)');
  const end=source.indexOf('\t\tif (frappe.route_options?.cfg_lorry_route)',start);assert(start>0&&end>start);
  let opened;await new Function('frappe','sync_session_from_storage','load','open_delivery_session','return (async()=>{'+source.slice(start,end)+'})()')(
    {route_options:{cfg_driver_delivery_session:'DEL1'}},()=>false,async()=>{},async name=>{opened=name;});assert.equal(opened,'DEL1');
});

test('automatic refresh cannot renew the operator session as user activity', async () => {
  const h=harness();await h.app.show(trip);assert(h.calls.every(row=>row.args.interactive===1));
  h.calls.length=0;await h.app.refresh(trip,false);assert(h.calls.every(row=>row.args.interactive===0));
});

test('duplicate scanner login and late response cannot overwrite another tab operator', async () => {
  const h=harness(), wait=deferred();h.data.clear();h.respond(()=>wait.promise);
  const first=h.app.identify('credential');await h.app.identify('credential');assert.equal(h.calls.length,1);
  h.data.set(SESSION,'OTHER');wait.resolve({session_token:'OLD'});await first;
  assert.equal(h.data.get(SESSION),'OTHER');assert.equal(h.app.state.busy,false);assert.equal(h.app.state.detail,null);
});

test('native router departure stops camera and timer without relying on a Page hide callback', async () => {
  const h=domHarness();await h.view.show(trip);h.events.get('click.cfg_driver .cfg-driver-camera')();
  h.current(['kanban-logistics']);h.events.get('router:change')();
  assert.equal(h.view.app.state.active,false);assert.equal(h.events.has('tick'),false);assert.equal(h.cameras[0].stopped,true);
});

test('background loss of list permission removes cached trip headers as well as details', async () => {
  const h=harness();await h.app.show(trip);
  h.respond(()=>{throw {exc_type:'PermissionError',message:'No longer authorized'};});
  await h.app.refresh(trip,false);assert.equal(h.app.state.detail,null);assert.deepEqual(h.app.state.trips,[]);
  assert.equal(h.data.get(SESSION),'TOKEN');
});
test('local stop selection after token replacement clears the old operator view immediately', async () => {
  const h=harness();await h.app.show(trip);h.data.set(SESSION,'OTHER');h.app.viewStop('STOP1');
  assert.equal(h.app.state.detail,null);assert.equal(h.views.at(-1).operator,null);
});


test('route lifecycle renders departure, stop completion and saved-outcome access separately', () => {
  const data=structuredClone(detail);data.trip.planning_state='Planned';data.trip.driver_route_state='Not Started';
  let html=ui.detailView({detail:data});assert(html.includes('cfg-driver-start-route'));assert(!html.includes('data-complete-stop='));
  data.trip.driver_route_state='In Progress';html=ui.detailView({detail:data});assert(!html.includes('cfg-driver-start-route'));assert(html.includes('data-complete-stop='));
  data.trip.driver_route_state='Completed';html=ui.detailView({detail:data});assert(html.includes('cfg-driver-resume-route'));assert(!html.includes('data-complete-stop='));
});

test('inline action has its own host and pauses polling until page hide safely closes it', async () => {
  const h=domHarness();await h.view.show(trip);let opened,closed=0;
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{locks:{}}});
  window.cfg_driver_route_actions={open(options){opened=options;return{focus(){},close(){closed++;options.onClose();}};}};
  h.events.get('click.cfg_driver .cfg-driver-start-route')();assert.equal(opened.trip,trip);assert.equal(opened.owner(),'EMP');
  const count=h.view.app.state.detail;h.events.get('tick')();await flush();assert.equal(h.view.app.state.detail,count);
  h.view.hide();assert.equal(closed,1);assert.equal(h.view.app.state.active,false);
});

test('optional visit exposes one shared-pool sale and actual selected/delivered products',()=>{
 const data=structuredClone(detail);data.trip.driver_route_state='In Progress';Object.assign(data.stops[0],{purpose:'Visit Only',can_open_sale:true,items:[],sources:[],open_sale:{state:'Completed',delivery_note:'DN-OPEN',allocations:[{item_code:'BAG',visible_code:'<TAG>',allocated_qty:2,delivered_qty:2,stock_uom:'Nos',state:'Delivered'}]}});
 const html=ui.detailView({detail:data});assert.match(html,/Sell from Lorry/);assert.match(html,/DN-OPEN/);assert.match(html,/&lt;TAG&gt;/);assert.match(html,/Selected: 2/);assert.match(html,/Delivered: 2/);
 data.stops[0].can_open_sale=false;assert(!ui.detailView({detail:data}).includes('data-sale-stop='));
});

test('route displays its team and only exposes Add Assistant when server permits the lead',()=>{
 const data=structuredClone(detail);data.trip.driver='LEAD';data.trip.assistant_drivers=[{employee:'HELP1',employee_name:'<Assistant>'},{employee:'HELP2'}];data.can_add_assistant=true;
 const state={detail:data};let html=ui.detailView(state);assert.match(html,/Assigned Driver/);assert.match(html,/LEAD/);assert.match(html,/&lt;Assistant&gt;/);assert.match(html,/HELP2/);assert.match(html,/cfg-driver-add-assistant/);
 data.can_add_assistant=false;html=ui.detailView(state);assert(!html.includes('cfg-driver-add-assistant'));
});

test('route shows enforced/flexible editing and persistent request decision feedback',()=>{
 const data=structuredClone(detail);data.route_sequence={can_change:true,enforced:true,request:{name:'KRC',state:'Pending',can_cancel:true}};
 let html=ui.detailView({detail:data});assert.match(html,/Request Stop Order Change/);assert.match(html,/Cancel Route Request/);
 data.route_sequence={can_change:true,enforced:false,request:{name:'KRC',state:'Approved',approval_mode:'Entire Proposed Order',decision_reason:'Reviewed'}};
 html=ui.detailView({detail:data});assert.match(html,/Change Stop Order/);assert.match(html,/Entire Proposed Order/);assert.match(html,/Reviewed/);assert(!html.includes('Cancel Route Request'));
 data.route_sequence.can_change=false;html=ui.detailView({detail:data});assert(!html.includes('cfg-driver-order'));
});
