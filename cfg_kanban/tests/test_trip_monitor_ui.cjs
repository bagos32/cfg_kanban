/* Supervisor reads + release receipts are exercised without a server or GPS simulator. */
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const api=require('../public/js/trip_monitor.js'),maps=require('../public/js/delivery_maps.js'),actions=require('../public/js/driver_route_actions.js');
const SESSION='cfg_kanban_operator_session',flush=async()=>{for(let n=0;n<40;n++)await Promise.resolve();};
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
const trip={name:'KTRIP-1',trip_title:'North Route',company:'A',trip_date:'2026-11-19',expected_return_date:'2026-11-22',vehicle_warehouse:'LORRY',driver_route_state:'In Progress'};
const stop={stop_key:'S1',sequence:1,site_name:'Shop',customer_name:'Buyer',state:'Loaded',purpose:'Delivery',address:'Jalan A',items:[{item_code:'BAG',stock_uom:'Nos',planned_qty:5,loaded_qty:5,delivered_qty:2,remaining_qty:3,orders:[{sales_order:'SO1',customer_po:'PO1'}]}],sources:[{tag_code:'RM1',item_code:'BAG',remaining_qty:3,stock_uom:'Nos',source_state:'Loaded'}]};
const gps=()=>({state:'Live',live:true,position:{latitude:4,longitude:102,accuracy:15},age_seconds:2,lease_id:'LEASE',publisher_employee:'DRIVER',vehicle_reference:'ABC123',vehicle_warehouse:'LORRY'});
const fleet=()=>({trips:[{trip,gps:gps()}],operator:{employee:'SUP',kanban_role:'Supervisor',can_override:true},has_more:false});
const detail=()=>({detail:{trip,stops:[structuredClone(stop)],next_stop_key:'S1',sequence_source:'Approved Route Sheet',refreshed_on:'2026-11-22 10:00',warnings:[]},gps:gps()});
function store(){const data=new Map([[SESSION,'TOKEN']]);return{data,getItem:key=>data.get(key)||null,setItem:(key,value)=>data.set(key,value),removeItem:key=>data.delete(key)};}
function harness(respond){const storage=store(),calls=[],views=[];const c=api.controller({storage,error:e=>e.message||'Read failed',render:s=>views.push(structuredClone(s)),rpc:async(method,args)=>{calls.push({method,args});if(respond){const value=await respond(method,args);if(value!==undefined)return value;}if(method.endsWith('supervisor_fleet'))return fleet();if(method.endsWith('supervisor_trip'))return detail();return {session_token:'NEW'};}});return{c,calls,storage,views};}
test('Supervisor page opens the real active Trip and passive refresh never renews action login',async()=>{
 const h=harness();await h.c.show(trip.name);assert.equal(h.c.state.detail.stops[0].items[0].remaining_qty,3);assert(h.calls.every(row=>row.args.interactive===0));
 await h.c.refresh(trip.name,false);assert(h.calls.every(row=>row.args.interactive===0));assert(h.c.state.gps.observed_ms);
});
test('Company/closed filters clear old Trip and keep multi-day active fleet data',async()=>{
 const h=harness();await h.c.show(trip.name);await h.c.settings('B',true);assert.equal(h.c.state.detail,null);assert.equal(h.c.state.selected,null);
 const args=h.calls.at(-1).args;assert.equal(args.company,'B');assert.equal(args.include_closed,1);assert.equal(args.interactive,1);assert.equal(h.c.state.trips[0].trip.trip_date,'2026-11-19');
});
test('fleet/default map never invents a position, selected Trip uses its exact stops and GPS',async()=>{
 const h=harness();await h.c.show();let state=api.mapState(h.c.state);assert.equal(state.detail.trip.name,'__fleet__');assert.equal(state.detail.stops.length,0);assert.equal(state.detail.vehicle_locations[0].gps.position.latitude,4);
 h.c.state.trips[0].gps={state:'Not Shared',position:null};assert.equal(maps.mapSpec(api.mapState(h.c.state).detail).vehicles.length,0);
 await h.c.select(trip.name);state=api.mapState(h.c.state);assert.equal(state.detail.stops[0].stop_key,'S1');assert.equal(state.detail.vehicle_locations.length,1);
});
test('Supervisor customer and fleet views share colour legends and Name (ID) labels',async()=>{
 const h=harness();await h.c.show(trip.name);h.c.state.detail.trip.driver_display='Ali (EMP-1)';h.c.state.gps.publisher_name='Abu';h.c.state.gps.publisher_employee='EMP-2';
 const html=api.detailHTML(h.c.state);assert(html.includes('Customer status colours'));assert(html.includes('cfg-monitor-stop cfg-status-'));assert(html.includes('Ali (EMP-1)'));assert(html.includes('Abu (EMP-2)'));
 const fleetHTML=api.fleetHTML(h.c.state);assert(fleetHTML.includes('Trip status colours'));assert(fleetHTML.includes('cfg-monitor-trip cfg-status-attention'));
});
test('typed permission rejection clears cached fleet and customer details; network loss marks staleness',async()=>{
 let failure=null;const h=harness(()=>{if(failure)throw failure;});await h.c.show(trip.name);failure=new Error('Offline');await h.c.refresh();assert(h.c.state.detail);assert(h.c.state.stale);
 failure={exc_type:'PermissionError',message:'Company denied'};await h.c.refresh();assert.equal(h.c.state.detail,null);assert.equal(h.c.state.trips.length,0);assert.equal(h.c.state.operator,null);
});
test('late results after page hide or identity replacement cannot draw old customer/GPS information',async()=>{
 const wait=deferred(),h=harness(()=>wait.promise),work=h.c.show(trip.name);h.c.hide();wait.resolve(fleet());await work;assert.equal(h.c.state.detail,null);assert.equal(h.c.state.trips.length,0);
 const d=deferred(),q=harness(()=>d.promise),read=q.c.show(trip.name);q.storage.setItem(SESSION,'OTHER');d.resolve(fleet());await read;assert.equal(q.c.state.detail,null);assert.equal(q.c.state.token,'OTHER');
});
test('Stop selection uses actual server order/status and escapes customer, tag, SO and PO text',async()=>{
 const h=harness();await h.c.show(trip.name);const data=h.c.state.detail;data.stops[0].site_name='<Shop>';data.stops[0].sources[0].tag_code='<RM>';data.stops[0].items[0].orders[0].customer_po='<PO>';
 let html=api.detailHTML(h.c.state);assert(html.includes('&lt;Shop&gt;'));assert(html.includes('&lt;RM&gt;'));assert(html.includes('&lt;PO&gt;'));assert(html.includes('Approved Route Sheet'));assert(html.includes('±15 m'));
 h.c.state.gps.observed_ms=Date.now()-100000;html=api.detailHTML(h.c.state);assert(html.includes('Stale'));assert(html.includes('last known'));assert(!html.includes('Complete Stop'));
});
test('scanned URL credentials go through the existing operator login, then native supervisor authorization',async()=>{
 const h=harness();await h.c.show();await h.c.identify('https://erp/app/kanban-operator#operator=SECRET','1234');const login=h.calls.find(row=>row.method.endsWith('login_operator'));assert.equal(login.args.token,'SECRET');assert.equal(login.args.pin,'1234');assert.equal(h.storage.getItem(SESSION),'NEW');
});
test('release retry retains exact original lease and reason after a lost response/reload',async()=>{
 const storage=store(),calls=[];let first=true,actor='SUP',count=0;
 const env={actions:actions.controller,storage,locks:{request:async(_key,fn)=>fn()},nonce:()=> 'REQUEST'+(++count),owner:()=>actor,token:()=> 'TOKEN',render(){},success:async()=>{},rpc:async(method,args)=>{calls.push({method,args});if(method.endsWith('driver_action_context'))return {revision:8,scope_hash:'SCOPE'};if(method.endsWith('perform_driver_action')){if(first){first=false;throw new Error('Lost');}return {status:'Recorded',action:'Release GPS',result:{lease_id:'OLD',gps_released:true}};}return {status:'Unrecorded'};}};
 const one=api.releaseController(env);await one.open(trip.name,'OLD');await assert.rejects(one.confirm('Device battery empty'));const original=calls.at(-1).args;one.close();
 const two=api.releaseController(env);await two.open(trip.name,'REPLACEMENT');await two.confirm('Different reason');assert.deepEqual(calls.at(-1).args,original);assert.equal(two.state.pending,null);
 assert([...storage.data.keys()].some(key=>key.startsWith('gps_release:')));assert(!storage.data.has('cfg_driver_action:'+trip.name));
});
test('Supervisor release unknown-result readback/void uses existing receipt and requires a new void reason',async()=>{
 const calls=[],storage=store();let seq=0;
 const c=api.releaseController({actions:actions.controller,storage,locks:{request:async(_key,fn)=>fn()},nonce:()=> 'ID'+(++seq),owner:()=> 'SUP',token:()=> 'TOKEN',render(){},success:async()=>{},rpc:async(method,args)=>{calls.push({method,args});if(method.endsWith('driver_action_context'))return {revision:1,scope_hash:'SCOPE'};if(method.endsWith('perform_driver_action'))throw new Error('Unknown');return {status:args.void_reason?'Voided':'Unrecorded'};}});
 await c.open(trip.name,'LEASE');await assert.rejects(c.confirm(''));await assert.rejects(c.confirm('Release unavailable phone'));await c.check();assert(c.state.pending);await c.check('Supervisor confirms this release was never recorded');assert.equal(c.state.pending,null);assert(calls.at(-1).args.void_reason);
});
function domHarness(){
 const nodes=new Map(),events=new Map(),calls=[],cameras=[],updates=[];const storage=store();let route=['kanban-trip-monitor'],control;
 class Node{constructor(){this[0]=this;this.props={};}html(v){this.htmlValue=v;return this;}find(key){if(!nodes.has(key))nodes.set(key,new Node());return nodes.get(key);}text(v){this.caption=v;return this;}prop(key,value){if(arguments.length>1){this.props[key]=value;return this;}return this.props[key];}val(value){if(arguments.length){this.value=value;return this;}return this.value;}empty(){return this.html('');}trigger(){return this;}on(type,selector,fn){events.set(type+' '+selector,fn);return this;}one(){return this;}appendTo(){return this;}attr(key){return this[key];}}
 global.$=value=>value instanceof Node?value:new Node();global.localStorage=storage;global.sessionStorage=store();global.cfg_driver_route={message:e=>e.message||'Failed'};
 global.cfg_driver_route_actions=actions;global.cfg_delivery_maps={...maps,createRouteMap:options=>({update:(state,slot)=>updates.push({state,slot,identity:options.identity()}),clear:()=>updates.push({cleared:true})})};
 global.addEventListener=(name,fn)=>events.set('window:'+name,fn);global.document={hidden:false,addEventListener:(name,fn)=>events.set('document:'+name,fn)};
 Object.defineProperty(global,'navigator',{configurable:true,value:{locks:{request:async(_key,fn)=>fn()}}});global.setInterval=fn=>{events.set('tick',fn);return 1;};global.clearInterval=()=>events.delete('tick');
 global.frappe={get_route:()=>route,utils:{escape_html:v=>v},router:{on:(name,fn)=>events.set('router:'+name,fn)},ui:{make_app_page:()=>({main:new Node()}),form:{make_control:options=>{control={options,get_value:()=> 'A'};return control;}},Scanner:class{constructor(options){this.options=options;this.dialog={$wrapper:new Node(),hide(){}};cameras.push(this);}stop_scan(){this.stopped=true;}}},call:async({method,args})=>{calls.push({method,args});return{message:method.endsWith('supervisor_fleet')?fleet():method.endsWith('supervisor_trip')?detail():method.endsWith('driver_action_context')?{revision:1,scope_hash:'SCOPE'}:{session_token:'NEW'}};}};
 const view=api.mount({});return{view,events,nodes,calls,cameras,storage,updates,route:value=>route=value,control:()=>control};
}
test('native monitor mounts full page, polls passively, stops on navigation and camera has one-result fencing',async()=>{
 const h=domHarness();await h.view.show(trip.name);assert(h.updates.at(-1).identity);assert.equal(h.view.app.state.detail.trip.name,trip.name);
 h.events.get('tick')();await flush();assert.equal(h.calls.at(-1).args.interactive,0);
 h.events.get('click.cfg_monitor .cfg-monitor-camera')();h.cameras[0].options.on_scan({decodedText:'https://erp/app/kanban-operator#operator=SUP'});await flush();assert(h.cameras[0].stopped);assert.equal(h.calls.filter(r=>r.method.endsWith('login_operator')).length,1);
 h.route(['kanban-floor']);h.events.get('router:change')();assert.equal(h.view.app.state.active,false);assert(!h.events.has('tick'));assert.equal(h.updates.at(-1).slot,null);
});
test('monitor release review preserves typed reason by suspending polling and remains separate from delivery actions',async()=>{
 const h=domHarness();await h.view.show(trip.name);await h.events.get('click.cfg_monitor .cfg-monitor-release')();h.nodes.get('.cfg-monitor-release-reason').val('Device unavailable');const before=h.calls.length;
 h.events.get('tick')();await flush();assert.equal(h.calls.length,before);assert.equal(h.nodes.get('.cfg-monitor-release-reason').val(),'Device unavailable');h.events.get('click.cfg_monitor .cfg-monitor-release-close')();h.view.hide();
});
test('native page loads KL/map assets and opens the requested Trip in a normal Page',async()=>{
 let assets,opened;const source=fs.readFileSync(path.join(__dirname,'../cfg_kanban/page/kanban_trip_monitor/kanban_trip_monitor.js'),'utf8'),f={pages:{'kanban-trip-monitor':{}},route_options:{cfg_trip_monitor_trip:trip.name},get_route:()=>['kanban-trip-monitor'],require:async value=>assets=value};
 vm.runInNewContext(source,{frappe:f,window:{cfg_trip_monitor:{mount:()=>({show:async value=>opened=value,hide(){}})}}});f.pages['kanban-trip-monitor'].on_page_load({});await flush();assert.equal(opened,trip.name);assert(assets.includes('/assets/cfg_kanban/js/map_defaults.js'));assert(assets.includes('/assets/cfg_kanban/js/delivery_maps.js'));assert(!f.route_options.cfg_trip_monitor_trip);
});

test('local stop selection after identity replacement clears all previous customer information immediately',async()=>{
 const h=harness();await h.c.show(trip.name);h.storage.setItem(SESSION,'OTHER');h.c.viewStop('S1');assert.equal(h.c.state.detail,null);assert.equal(h.c.state.operator,null);assert.equal(h.c.state.token,'OTHER');
});
