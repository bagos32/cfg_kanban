/* Real pin/map/navigation code with DOM/Leaflet doubles; no native-device acceptance claim. */
const test=require('node:test'),assert=require('node:assert/strict');
const api=require('../public/js/delivery_maps.js');
const point=(latitude=3.139,longitude=101.6869)=>({latitude,longitude});
const stop=(key='K1',extra={})=>({stop_key:key,sequence:1,site_name:'Shop',customer_name:'Customer',purpose:'Delivery',state:'Loaded',delivery_pin:point(),address:'Street, Town',items:[{item_code:'BAG',planned_qty:5,stock_uom:'Nos',orders:[{sales_order:'SO1',customer_po:'PO1'}]}],...extra});
const state=(extra={})=>({active:true,stale:false,busy:false,detail:{trip:{name:'TRIP',planning_state:'Planned',driver_route_state:'In Progress'},next_stop_key:'K1',current_stop_key:null,stops:[stop()],...extra}});
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
const flush=async()=>{for(let n=0;n<15;n++)await Promise.resolve();};
test('pin utility preserves latitude/longitude ordering and zero coordinates',()=>{
 const value=api.pointJSON('3.139','101.6869');assert.deepEqual(JSON.parse(value).features[0].geometry.coordinates,[101.6869,3.139]);assert.deepEqual(api.readPoint(value),point());assert.deepEqual(api.readPoint(api.pointJSON(0,0)),point(0,0));
});
test('blank, nondecimal, boolean, nonfinite and out-of-range input cannot become a false pin',()=>{
 for(const pair of [['',1],['  ',1],['0x10',1],[true,1],[Infinity,1],[91,1],[1,181],[NaN,1]])assert.throws(()=>api.pointJSON(...pair),/Latitude/);
 for(const pin of [null,{latitude:'3',longitude:101},point(NaN,1),point(1,Infinity),point(91,1)])assert.equal(api.pin(pin),null);
});
test('deleted pins stay empty and shapes/multiple markers are rejected',()=>{
 assert.equal(api.readPoint(null),null);assert.equal(api.readPoint('{"type":"FeatureCollection","features":[]}'),null);
 const data=JSON.parse(api.pointJSON(3,101));data.features.push(data.features[0]);assert.throws(()=>api.readPoint(data),/one Delivery Pin/);
 for(const props of [{point_type:'circle'},[],true]){const data=JSON.parse(api.pointJSON(3,101));data.features[0].properties=props;assert.throws(()=>api.readPoint(data),/marker/);}
});
test('Google Maps and Waze receive the exact pin without operator/trip/order credentials',()=>{
 const urls=api.urls(stop('K1',{operator_session_token:'secret',dispatch_plan:'DPL-SECRET'})),g=new URL(urls.google),w=new URL(urls.waze);
 assert.equal(g.origin,'https://www.google.com');assert.equal(g.pathname,'/maps/dir/');assert.equal(g.searchParams.get('api'),'1');assert.equal(g.searchParams.get('destination'),'3.139,101.6869');assert.equal(g.searchParams.get('travelmode'),'driving');assert.equal(g.searchParams.get('dir_action'),'navigate');assert(!g.searchParams.has('origin'));
 assert.equal(w.origin,'https://waze.com');assert.equal(w.searchParams.get('ll'),'3.139,101.6869');assert.equal(w.searchParams.get('navigate'),'yes');assert.equal(w.searchParams.get('utm_source'),'cfg_kanban');assert(!JSON.stringify(urls).includes('secret'));assert(!JSON.stringify(urls).includes('DPL'));
});
test('missing/invalid pins use encoded address search without inventing a destination',()=>{
 const row=stop('K1',{delivery_pin:null,address:'Jalan A & B #3, 吉隆坡'}),urls=api.urls(row),g=new URL(urls.google),w=new URL(urls.waze);
 assert.equal(urls.kind,'address');assert.equal(g.searchParams.get('destination'),row.address);assert.equal(w.searchParams.get('q'),row.address);assert(!w.searchParams.has('ll'));assert(!w.searchParams.has('navigate'));
 assert.equal(api.urls({...row,address:' '}),null);assert.equal(api.urls({...row,address:'x'.repeat(2200)}),null);
 assert(!api.urls({...row,address:'javascript:alert(1)'}).google.startsWith('javascript:'));
});
test('directions use the server next/current stop regardless of the selected stop or displayed list order',()=>{
 const s=state({stops:[stop('K1'),stop('K2',{sequence:2,site_name:'Other',delivery_pin:point(4,102)})],next_stop_key:'K2'});s.stop='K1';
 let html=api.navigationHTML(s);assert(html.includes('Directions to next stop: Other'));assert(html.includes('4%2C102'));assert(!html.includes('3.139%2C101'));
 s.detail.current_stop_key='K2';assert(api.navigationHTML(s).includes('Directions to current stop'));
 s.detail.next_stop_key=null;assert.equal(api.navigationHTML(s),'');
});
test('stale, refreshing and hidden views offer no usable navigation links',()=>{
 for(const flag of ['stale','busy']){const s=state();s[flag]=true;const html=api.navigationHTML(s);assert(!html.includes('href='));assert(html.includes('disabled'));}
 const s=state();s.active=false;assert(!api.navigationHTML(s).includes('href='));
 for(const phase of ['Completed','Closed Incomplete']){const s=state();s.detail.trip.driver_route_state=phase;assert.equal(api.navigationHTML(s),'');}
 const closed=state();closed.detail.trip.planning_state='Closed';assert.equal(api.navigationHTML(closed),'');
});
test('no pin/address and invalid pin have explicit messages without changing the delivery controls',()=>{
 const s=state({stops:[stop('K1',{delivery_pin:null,delivery_pin_status:'Invalid'})]});let html=api.navigationHTML(s);assert(html.includes('needs correction'));assert(html.includes('Waze — Search Address'));
 s.detail.stops[0].address='';html=api.navigationHTML(s);assert(html.includes('Set a Delivery Pin'));assert(!html.includes('href='));assert.equal(s.detail.stops[0].state,'Loaded');
});
test('coincident/repeated customer visits share a pin with exact independent stop choices',()=>{
 const data=state({stops:[stop('K1'),stop('K2',{sequence:2,state:'Visit planned',purpose:'Visit Only'})],next_stop_key:'K2'}).detail;
 const spec=api.mapSpec(data);assert.equal(spec.located,2);assert.equal(spec.groups.length,1);assert.equal(spec.groups[0].kind,'next');assert.deepEqual(spec.groups[0].stops.map(r=>r.stop_key),['K1','K2']);
 const html=api.popupHTML(spec.groups[0].stops);assert(html.includes('data-map-stop="K1"'));assert(html.includes('data-map-stop="K2"'));assert(html.includes('SO1 / PO1'));assert(html.includes('5 Nos'));
});
test('map state colors reflect current/completed/attention and all popup data is escaped',()=>{
 const rows=[stop('K1',{delivery_pin:point(1,1),driver_completed_on:'2026-11-22'}),stop('K2',{sequence:2,delivery_pin:point(2,2),state:'Review required'}),stop('K3',{sequence:3,delivery_pin:point(3,3)})];
 const spec=api.mapSpec({stops:rows,current_stop_key:'K3'});assert.deepEqual(spec.groups.map(g=>g.kind),['completed','danger','current']);
 const html=api.popupHTML([stop('K1',{site_name:'<img src=x onerror=alert(1)>',address:'<script>'})]);assert(html.includes('&lt;img'));assert(!html.includes('<img'));assert(!html.includes('<script>'));
});
class Element{
 constructor(){this.children=[];this.parentNode=null;this.nodes=new Map();this.listeners={};this.textContent='';this.hidden=false;}
 set innerHTML(value){this.html=value;for(const name of ['cfg-driver-map-info','cfg-driver-map-canvas','cfg-driver-map-message','cfg-driver-map-retry','cfg-map-follow','cfg-map-fit-selected'])this.nodes.set('.'+name,new Element());}
 querySelector(name){return this.nodes.get(name);}
 appendChild(node){if(node.parentNode)node.parentNode.removeChild(node);this.children.push(node);node.parentNode=this;return node;}
 removeChild(node){this.children=this.children.filter(n=>n!==node);node.parentNode=null;}
 addEventListener(name,fn){this.listeners[name]=fn;}
}
function library(){
 const maps=[],tiles=[],groups=[],markers=[];
 const L={map:canvas=>{const map={canvas,fit:0,invalidations:0,removed:false,remove(){this.removed=true;},removeLayer(){},setView(center,zoom){this.center=center;this.zoom=zoom;return this;},panTo(point){this.pan=point;},fitBounds(){this.fit++;},invalidateSize(){this.invalidations++;}};maps.push(map);return map;},
  tileLayer:(url,options)=>{const layer={url,options,events:{},on(name,fn){this.events[name]=fn;return this;},addTo(){return this;}};tiles.push(layer);return layer;},
  divIcon:options=>options,featureGroup:()=>{const group={markers:[],addTo(){return this;},getBounds:()=>[]};groups.push(group);return group;},
  marker:(coords,options)=>{const marker={coords,options,bindPopup(html){this.html=html;return this;},addTo(group){group.markers.push(this);return this;}};markers.push(marker);return marker;}};
 return{L,maps,tiles,groups,markers};
}
function mapHarness(load){
 const lib=library(),slot=new Element(),picks=[],identity={value:'EMP:TRIP'};let loads=0;
 const f={utils:{map_defaults:{tiles:'https://tiles.example/{z}/{x}/{y}.png',options:{attribution:'Native provider'}}}};
 const map=api.createRouteMap({frappe:f,document:{createElement:()=>new Element()},identity:()=>identity.value,pick:key=>picks.push(key),load:()=>{loads++;return load?load(lib):Promise.resolve(lib.L);}});
 return{...lib,map,slot,picks,identity,loads:()=>loads,node:()=>slot.children[0],async update(s=state()){map.update(s,slot);await flush();}};
}
test('map uses configured native tiles and does not request a GPS position',async()=>{
 const h=mapHarness();await h.update();assert.equal(h.maps.length,1);assert.equal(h.tiles[0].url,'https://tiles.example/{z}/{x}/{y}.png');assert.equal(h.markers[0].coords[0],3.139);assert.equal(h.markers[0].coords[1],101.6869);assert.equal(h.maps[0].fit,1);
 assert(h.node().querySelector('.cfg-driver-map-info').textContent.includes('1 / 1'));h.map.clear();assert(h.maps[0].removed);assert.equal(h.slot.children.length,0);
});
test('empty map opens at KL without inventing a customer or vehicle pin',async()=>{
 const h=mapHarness();await h.update(state({stops:[stop('K1',{delivery_pin:null})]}));assert.equal(h.loads(),1);assert.deepEqual(h.maps[0].center,[3.139,101.6869]);assert.equal(h.maps[0].zoom,13);assert.equal(h.markers.length,0);assert(h.node().querySelector('.cfg-driver-map-message').textContent.includes('No saved locations'));
});
test('Fit Selected Customer centres only the chosen pin and disables lorry follow',async()=>{
 const h=mapHarness(),data=state({stops:[stop('K1',{delivery_pin:point(3,101)}),stop('K2',{delivery_pin:point(5,103)})]});data.stop='K2';
 await h.update(data);const fit=h.maps[0].fit;h.map.fitSelected();assert.deepEqual(h.maps[0].center,[5,103]);assert.equal(h.maps[0].zoom,16);assert.equal(h.maps[0].fit,fit);
 assert(h.node().html.includes('Fit Selected Customer'));assert(h.node().html.includes('Customer status colours'));
 data.detail.vehicle_locations=[{trip:{name:'TRIP'},gps:api.observeGPS({state:'Live',position:{latitude:9,longitude:109,accuracy:5},age_seconds:0})}];
 await h.update(data);assert.deepEqual(h.maps[0].center,[5,103]);assert.equal(h.maps[0].fit,fit);
});
test('selected-customer fit refuses missing pins, stale views and changed identity',async()=>{
 const h=mapHarness(),data=state({stops:[stop('K1',{delivery_pin:null})]});data.stop='K1';await h.update(data);
 assert(h.node().querySelector('.cfg-map-fit-selected').disabled);h.map.fitSelected();assert.match(h.node().querySelector('.cfg-driver-map-message').textContent,/saved delivery pin/);
 const other=state();other.stale=true;await h.update(other);h.maps[0].center=[9,99];h.map.fitSelected();assert.deepEqual(h.maps[0].center,[9,99]);
 h.identity.value='OTHER';h.map.fitSelected();assert.deepEqual(h.maps[0].center,[9,99]);
});
test('customer and Trip colours preserve state distinctions and visible legend text',()=>{
 for(const [state,kind] of [['Loaded','next'],['Awaiting loading','pending'],['In Progress','attention'],['Completed','completed'],['Completed with refusal','attention'],['Review required','danger'],['Cancelled','cancelled']])assert.equal(api.stopKind({state}),kind);
 for(const [state,kind] of [['Not Started','next'],['In Progress','attention'],['Completed','completed'],['Closed Incomplete','danger']])assert.equal(api.tripKind({planning_state:'Planned',driver_route_state:state}),kind);
 assert(api.statusLegend().includes('Review Required'));assert(api.statusLegend(true).includes('Closed Incomplete'));assert.equal(api.person('EMP-1','Ali'),'Ali (EMP-1)');
});
test('refresh keeps map and viewport; changed status updates markers and changed pin recenters',async()=>{
 const h=mapHarness();await h.update();const map=h.maps[0];h.map.detach();assert.equal(h.slot.children.length,0);await h.update();assert.equal(h.maps.length,1);assert.equal(map.fit,1);
 const changed=state();changed.detail.stops[0].state='Review required';changed.detail.next_stop_key=null;await h.update(changed);assert.equal(map.fit,1);assert.equal(h.groups.at(-1).markers[0].options.icon.className,'cfg-driver-map-pin danger');
 changed.detail.stops[0].delivery_pin=point(4,102);await h.update(changed);assert.equal(map.fit,2);
});
test('map popup opens only the exact selected visit details and cannot complete a delivery',async()=>{
 const h=mapHarness();await h.update(state({stops:[stop('K1'),stop('K2',{sequence:2})]}));const click=key=>h.node().listeners.click({target:{closest:selector=>selector==='[data-map-stop]'?{getAttribute:()=>key}:null}});
 click('K2');click('OTHER');assert.deepEqual(h.picks,['K2']);
 const stale=state();stale.stale=true;await h.update(stale);click('K1');assert.deepEqual(h.picks,['K2']);
});
test('stale warning clears after a successful refresh and removal of all pins leaves an empty KL map',async()=>{
 const h=mapHarness();await h.update();const s=state();s.stale=true;await h.update(s);assert.match(h.node().querySelector('.cfg-driver-map-message').textContent,/not refreshed/);
 s.stale=false;await h.update(s);assert.equal(h.node().querySelector('.cfg-driver-map-message').textContent,'');
 s.detail.stops[0].delivery_pin=null;await h.update(s);assert(!h.maps[0].removed);assert.deepEqual(h.maps[0].center,[3.139,101.6869]);assert.equal(h.groups.at(-1).markers.length,0);
});
test('late library load after logout or trip replacement cannot render old customer pins',async()=>{
 const wait=deferred(),h=mapHarness(()=>wait.promise);h.map.update(state(),h.slot);h.identity.value=null;h.map.clear();wait.resolve(h.L);await flush();assert.equal(h.maps.length,0);assert.equal(h.slot.children.length,0);
 const first=deferred(),g=mapHarness(()=>first.promise);g.map.update(state(),g.slot);g.identity.value='OTHER:TRIP';first.resolve(g.L);await flush();assert.equal(g.maps.length,0);
});
test('asset failure keeps directions usable and explicit Retry recovers the map',async()=>{
 let fail=true;const h=mapHarness(lib=>fail?Promise.reject(new Error('Offline')):Promise.resolve(lib.L));await h.update();assert(h.node().querySelector('.cfg-driver-map-retry').hidden===false);assert(api.navigationHTML(state()).includes('href='));
 await h.update();assert.equal(h.loads(),1);fail=false;h.node().listeners.click({target:{closest:selector=>selector==='.cfg-driver-map-retry'?{}:null}});await flush();assert.equal(h.loads(),2);assert.equal(h.maps.length,1);assert(h.node().querySelector('.cfg-driver-map-retry').hidden);
});
test('tile failure is isolated and callbacks from a removed trip map cannot mark the new map',async()=>{
 const h=mapHarness();await h.update();h.tiles[0].events.tileerror();assert.match(h.node().querySelector('.cfg-driver-map-message').textContent,/tiles unavailable/);
 await h.update();assert.match(h.node().querySelector('.cfg-driver-map-message').textContent,/tiles unavailable/);h.tiles[0].events.tileload();assert.equal(h.node().querySelector('.cfg-driver-map-message').textContent,'');
 const old=h.tiles[0];h.identity.value='EMP:OTHER';await h.update(state({trip:{name:'OTHER'}}));old.events.tileerror();assert.equal(h.node().querySelector('.cfg-driver-map-message').textContent,'');
});
function tools(write=true){
 const fields=new Map(),events=new Map(),calls=[];
 class Node{html(v){this.htmlValue=v;return this;}find(name){if(!fields.has(name))fields.set(name,new Node());return fields.get(name);}val(v){if(arguments.length){this.value=v;return this;}return this.value;}text(v){this.caption=v;return this;}off(){return this;}on(type,name,fn){events.set(name,fn);return this;}}
 const host=new Node(),frm={doctype:'CFG Kanban Customer Scan Point',doc:{delivery_location:api.pointJSON(0,0),require_gps:1},fields_dict:{delivery_pin_tools:{$wrapper:host}},is_new:()=>false,set_value:async(field,value)=>{calls.push({field,value});frm.doc[field]=value;}};
 api.pinTools(frm,{perm:{has_perm:()=>write}});return{host,fields,events,calls,frm};
}
test('normal Site form sets/replaces/clears one pin, leaving Save and proof GPS under native control',async()=>{
 const h=tools();assert(h.host.htmlValue.includes('value="0"'));h.fields.set('.cfg-site-latitude',{val:()=> '4.2'});h.fields.set('.cfg-site-longitude',{val:()=> '102.3'});await h.events.get('.cfg-site-set-pin')();assert.deepEqual(api.readPoint(h.frm.doc.delivery_location),point(4.2,102.3));assert.equal(h.frm.doc.require_gps,1);assert.match(h.fields.get('.cfg-site-pin-status').caption,/Save/);
 await h.events.get('.cfg-site-clear-pin')();assert.equal(h.frm.doc.delivery_location,null);assert.equal(h.calls.length,2);
});
test('invalid coordinate entry and read-only Site form cannot mutate its pin',async()=>{
 const h=tools();h.fields.set('.cfg-site-latitude',{val:()=> ''});h.fields.set('.cfg-site-longitude',{val:()=> '1'});await h.events.get('.cfg-site-set-pin')();assert.equal(h.calls.length,0);assert.match(h.fields.get('.cfg-site-pin-status').caption,/Latitude/);
 const read=tools(false);await read.events.get('.cfg-site-clear-pin')();assert.equal(read.calls.length,0);assert(read.host.htmlValue.includes('disabled'));
});
test('native Leaflet assets load locally with no Google API key or remote executable script',async()=>{
 const lib=library(),calls=[],slot=new Element();global.L=null;
 const map=api.createRouteMap({frappe:{utils:{map_defaults:{tiles:'native',options:{}}},require:async path=>{calls.push(path);if(path.endsWith('.js'))global.L=lib.L;}},document:{createElement:()=>new Element()},identity:()=> 'EMP',pick(){}});
 map.update(state(),slot);await flush();assert.deepEqual(calls,['/assets/frappe/js/lib/leaflet/leaflet.css','/assets/frappe/js/lib/leaflet/leaflet.js']);assert.equal(lib.maps.length,1);map.clear();delete global.L;
});

test('freshness ages while offline without double-counting when already-projected GPS is rendered again',()=>{
 const raw=api.observeGPS({state:'Live',position:{latitude:4,longitude:102,accuracy:20},age_seconds:5,stale_after_seconds:90},1000);
 const once=api.gpsDisplay(raw,11000),twice=api.gpsDisplay(once,11000);assert.equal(once.age_seconds,15);assert.equal(twice.age_seconds,15);assert.equal(twice.state,'Live');
 assert.equal(api.gpsDisplay(raw,92000).state,'Stale');assert.equal(api.gpsDisplay({state:'Live',position:null,age_seconds:0}).live,false);
});
test('first real lorry fix focuses its actual location; later GPS movement preserves viewport unless Follow is enabled',async()=>{
 const h=mapHarness();await h.update(state({stops:[]}));assert.deepEqual(h.maps[0].center,[3.139,101.6869]);assert.equal(h.maps[0].fit,0);
 const data=state({stops:[],vehicle_locations:[{trip:{name:'TRIP'},gps:api.observeGPS({state:'Live',position:{latitude:4.2,longitude:102.3,accuracy:10},age_seconds:0,vehicle_reference:'TRUCK'})}]});
 await h.update(data);assert.equal(h.maps[0].fit,1);assert.deepEqual(h.markers.at(-1).coords,[4.2,102.3]);assert(h.markers.at(-1).options.icon.className.includes('vehicle'));assert.match(h.markers.at(-1).html,/±10 m/);
 data.detail.vehicle_locations[0].gps.position.latitude=4.3;await h.update(data);assert.equal(h.maps[0].fit,1);assert.equal(h.maps[0].pan,undefined);
 h.node().listeners.click({target:{closest:selector=>selector==='.cfg-map-follow'?{}:null}});await flush();assert.deepEqual(h.maps[0].pan,[4.3,102.3]);
 data.detail.vehicle_locations[0].gps.state='Paused';await h.update(data);assert(h.markers.at(-1).options.icon.className.includes('last-known'));assert.match(h.markers.at(-1).html,/not a live fix/);
});
test('a Supervisor lorry popup opens only its exact Trip, and cannot open a vanished or stale Trip',async()=>{
 const h=mapHarness(),picks=[];h.map.clear();const map=api.createRouteMap({frappe:{utils:{map_defaults:{tiles:'native',options:{}}}},document:{createElement:()=>new Element()},identity:()=> 'SUP',pickTrip:name=>picks.push(name),load:()=>Promise.resolve(h.L)});
 const s=state({stops:[],vehicle_locations:[{trip:{name:'TRIP'},gps:{state:'Stopped',position:{latitude:5,longitude:103},age_seconds:500}}]});map.update(s,h.slot);await flush();
 const node=h.slot.children[0],click=key=>node.listeners.click({target:{closest:selector=>selector==='[data-map-trip]'?{getAttribute:()=>key}:null}});click('TRIP');click('OTHER');assert.deepEqual(picks,['TRIP']);s.stale=true;map.update(s,h.slot);await flush();click('TRIP');assert.deepEqual(picks,['TRIP']);map.clear();
});
test('the first lorry fix joins existing customer bounds once, while normal movement keeps the viewport',async()=>{
 const h=mapHarness();await h.update();assert.equal(h.maps[0].fit,1);
 const data=state({vehicle_locations:[{trip:{name:'TRIP'},gps:{state:'Live',position:{latitude:4,longitude:102,accuracy:10},age_seconds:0}}]});await h.update(data);assert.equal(h.maps[0].fit,2);
 data.detail.vehicle_locations[0].gps.position.latitude=4.5;await h.update(data);assert.equal(h.maps[0].fit,2);
});
