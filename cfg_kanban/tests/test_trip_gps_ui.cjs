/* Actual GPS source + durable Driver Action controllers, with device/RPC doubles. */
const test=require('node:test'),assert=require('node:assert/strict');
const api=require('../public/js/trip_gps.js'),actions=require('../public/js/driver_route_actions.js');
global.cfg_delivery_maps=require('../public/js/delivery_maps.js');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
const flush=async()=>{for(let n=0;n<40;n++)await Promise.resolve();};
function store(){const data=new Map();return{data,getItem:key=>data.get(key)||null,setItem:(key,value)=>data.set(key,value),removeItem:key=>data.delete(key)};}
function harness(options={}){
 const storage=options.storage||store(),deviceStorage=store(),calls=[],positions=[],renders=[],timers=new Map();let actor='EMP',token='TOKEN',trip='TRIP',active=true,seq=0,fixes=0,timerId=0;
 let gps={state:'Waiting for GPS',lease_id:'LEASE',lease_until_ms:Date.now()+43200000,vehicle_warehouse:'LORRY',publisher_employee:'EMP',last_sequence:0,publish_interval_seconds:15,stale_after_seconds:90,position:null,age_seconds:null};
 const response=async(method,args)=>{
  if(options.respond){const result=await options.respond(method,args);if(result!==undefined)return result;}
  if(method.endsWith('driver_action_context'))return {revision:4,scope_hash:'SCOPE'};
  if(method.endsWith('perform_driver_action'))return {status:'Recorded',action:'Start GPS',result:{lease_id:'LEASE',lease_until_ms:Date.now()+43200000,vehicle_warehouse:'LORRY',publisher_employee:actor,publish_interval_seconds:15}};
  if(method.endsWith('source_status'))return {...gps};
  if(method.endsWith('driver_context'))return {gps:{...gps},can_share:true};
  if(method.endsWith('publish_position')){gps={...gps,state:'Live',last_sequence:args.sequence_no,position:args.position_data,age_seconds:0};return {status:'Recorded',gps};}
  if(method.endsWith('pause_source')){gps={...gps,state:'Paused'};return gps;}
  if(method.endsWith('stop_source')){gps={...gps,state:'Stopped'};return gps;}
  if(method.endsWith('reconcile_driver_action'))return {status:'Unrecorded'};
  throw new Error('Unexpected '+method);
 };
 const c=api.controller({storage,deviceStorage,actionController:actions.controller,locks:options.locks===null?null:{request:async(_key,fn)=>fn()},
  owner:()=>actor,token:()=>token,nonce:()=> 'nonce_'+String(++seq).padStart(24,'0'),trip:()=>trip,active:()=>active,available:()=>options.available!==false,error:e=>e.message||'RPC failed',
  rpc:async(method,args)=>{calls.push({method,args});return response(method,args);},render:s=>renders.push(JSON.stringify(s)),position:(name,gps)=>positions.push({name,gps}),
  positionOnce:()=>{fixes++;return options.position?options.position():Promise.resolve({coords:{latitude:3.139,longitude:101.6869,accuracy:10},timestamp:Date.now()});},
  setTimer:(fn,ms)=>{const id=++timerId;timers.set(id,{fn,ms});return id;},clearTimer:id=>timers.delete(id),
 });
 return {c,storage,deviceStorage,calls,positions,renders,timers,fixes:()=>fixes,actor:value=>actor=value,token:value=>token=value,trip:value=>trip=value,active:value=>active=value,
  gps:value=>gps={...gps,...value},binding:()=>JSON.parse(storage.getItem(api.bindingKey)||'null'),async show(){await c.show();},async start(){await c.show();await c.start();await flush();},async tick(){const first=timers.entries().next().value;if(!first)return;timers.delete(first[0]);first[1].fn();await flush();}};
}
test('explicit Share persists scoped source before sampling; no position or token enters local device storage',async()=>{
 const h=harness();await h.show();assert.equal(h.fixes(),0);await h.c.start();await flush();
 assert.equal(h.fixes(),1);const binding=h.binding();assert.equal(binding.lease_id,'LEASE');assert.equal(binding.sequence,1);
 assert([...h.deviceStorage.data.keys()].every(key=>key==='cfg_trip_gps_device_v1'));assert(!JSON.stringify([...h.storage.data]).includes('latitude'));
 const start=h.calls.find(row=>row.method.endsWith('perform_driver_action'));assert.equal(start.args.action,'Start GPS');assert.equal(start.args.payload.publish_token,binding.publish_token);
 assert(!JSON.stringify(h.c.state).includes(binding.publish_token));assert.equal(h.timers.size,1);assert.equal([...h.timers.values()][0].ms,15000);
});
const departure=(enabled=true)=>({status:'Recorded',action:'Start Route',trip_name:'TRIP',request_actor:'EMP',result:{gps_auto_start:enabled}});
test('configured auto-start runs once on the confirming device and manual Stop defeats replay',async()=>{
 const h=harness();await h.show();await h.c.autoStart(departure());await flush();assert.equal(h.fixes(),1);
 const starts=()=>h.calls.filter(row=>row.method.endsWith('perform_driver_action')).length;
 assert.equal(starts(),1);await h.c.autoStart(departure());assert.equal(starts(),1);
 await h.c.stop();await h.c.autoStart(departure());await flush();assert.equal(starts(),1);assert.equal(h.binding(),null);
});
test('opening or refreshing an opted-in Trip does not start GPS without its recorded departure',async()=>{
 const h=harness({respond:async method=>method.endsWith('driver_context')?{gps:{state:'Not Shared'},can_share:true,auto_start:true,publish_interval_seconds:60}:undefined});
 await h.show();await h.c.context({active:true,token:'TOKEN',operator:{employee:'EMP'},selected:'TRIP',detail:{trip:{name:'TRIP',driver_route_state:'In Progress'},refreshed_on:'now'}});
 assert.equal(h.fixes(),0);assert(!h.calls.some(row=>row.method.endsWith('perform_driver_action')));
});
test('auto-start rejects off policy, voided departure, different actor/trip and hidden page',async()=>{
 const h=harness();await h.show();
 for(const result of [departure(false),{...departure(),status:'Voided'},{...departure(),trip_name:'OTHER'},{...departure(),request_actor:'OTHER'}])await h.c.autoStart(result);
 h.c.hide();await h.c.autoStart(departure());assert.equal(h.fixes(),0);assert(!h.binding());
});
test('auto-start retains an uncertain GPS request for exact retry instead of making another source',async()=>{
 let fail=true;const h=harness({respond:async method=>{if(method.endsWith('perform_driver_action')&&fail)throw Error('Lost');}});
 await h.show();await assert.rejects(()=>h.c.autoStart(departure()),/Lost/);const binding=h.binding();assert.equal(binding.state,'Starting');
 await h.c.autoStart(departure());assert.equal(h.calls.filter(row=>row.method.endsWith('perform_driver_action')).length,1);
 fail=false;await h.c.start();await flush();assert.equal(h.binding().publish_token,binding.publish_token);assert.equal(h.fixes(),1);
});
test('publisher adopts 60/300-second office intervals from source replies without storing coordinates',async()=>{
 const h=harness();h.gps({publish_interval_seconds:60,stale_after_seconds:180});await h.start();
 assert.equal([...h.timers.values()][0].ms,60000);assert.equal(h.c.state.binding.publish_interval_seconds,60);
 h.gps({publish_interval_seconds:300,stale_after_seconds:900});await h.tick();assert.equal([...h.timers.values()][0].ms,300000);
 assert(!JSON.stringify([...h.storage.data]).includes('latitude'));assert.equal(h.fixes(),2);
});
test('explicit source refresh reschedules a changed interval without sampling an extra fix',async()=>{
 const h=harness();await h.start();h.gps({publish_interval_seconds:120});await h.c.recover();
 assert.equal(h.fixes(),1);assert.equal([...h.timers.values()][0].ms,120000);assert.equal(h.timers.size,1);
});
test('HTTPS/geolocation/Web Locks/identity prerequisites block mutations and sampling',async()=>{
 for(const options of [{available:false},{locks:null}]){const h=harness(options);await h.show();await assert.rejects(h.c.start());assert.equal(h.fixes(),0);assert(!h.calls.some(row=>row.method.endsWith('perform_driver_action')));}
 const h=harness();h.token(null);await h.show();await assert.rejects(h.c.start(),/Identify/);assert.equal(h.calls.length,0);
});
test('blocked session storage fails before GPS start mutation or sampling',async()=>{
 const storage=store();storage.setItem=()=>{throw new Error('Blocked storage');};const h=harness({storage});await h.show();await assert.rejects(h.c.start(),/Blocked/);assert.equal(h.fixes(),0);assert(!h.calls.some(row=>row.method.endsWith('perform_driver_action')));assert.equal(h.c.state.binding,null);
});
test('lost Start response retains exact payload/token and blocks another Trip until original retry resolves',async()=>{
 let lost=true;const h=harness({respond:async(method)=>{if(method.endsWith('perform_driver_action')&&lost){lost=false;throw new Error('Network lost');}}});await h.show();await assert.rejects(h.c.start(),/lost/);assert.equal(h.fixes(),0);assert(h.c.state.pending);
 const original=h.calls.find(row=>row.method.endsWith('perform_driver_action')).args;h.trip('OTHER');await h.c.start();await flush();
 const retries=h.calls.filter(row=>row.method.endsWith('perform_driver_action'));assert.deepEqual(retries[1].args,original);assert.equal(h.c.state.binding.trip,'TRIP');assert.equal(h.fixes(),1);
});
test('first confirmed rejection allows correction while rejected uncertain retry remains pending',async()=>{
 let reject=true;const h=harness({respond:async(method)=>{if(method.endsWith('perform_driver_action')&&reject)throw {exc_type:'ValidationError',message:'Already shared'};}});await h.show();await assert.rejects(h.c.start());assert.equal(h.binding(),null);reject=false;await h.c.start();await flush();assert.equal(h.fixes(),1);
 let attempts=0;const q=harness({respond:async(method)=>{if(method.endsWith('perform_driver_action')){if(!attempts++)throw new Error('Unknown result');throw {exc_type:'ValidationError',message:'Trip ended'};}}});await q.show();await assert.rejects(q.c.start());const id=q.calls.find(row=>row.method.endsWith('perform_driver_action')).args.event_token;await assert.rejects(q.c.start());assert.equal(q.calls.filter(row=>row.method.endsWith('perform_driver_action')).at(-1).args.event_token,id);assert.equal(q.fixes(),0);
});
test('Stop during an unknown Start resolves that original source and never samples it',async()=>{
 let lost=true;const h=harness({respond:async(method)=>{if(method.endsWith('perform_driver_action')&&lost){lost=false;throw new Error('Lost');}}});await h.show();await assert.rejects(h.c.start());await h.c.stop();assert.equal(h.binding().intent,false);assert.equal(h.fixes(),0);
 await h.c.start();await flush();assert.equal(h.fixes(),0);assert.equal(h.binding(),null);assert(h.calls.some(row=>row.method.endsWith('stop_source')));
});
test('Supervisor readback/void resolves an unknown Start without creating another identity',async()=>{
 const h=harness({respond:async(method,args)=>{if(method.endsWith('perform_driver_action'))throw new Error('Lost');if(method.endsWith('reconcile_driver_action'))return args.void_reason?{status:'Voided'}:{status:'Unrecorded'};}});await h.show();await assert.rejects(h.c.start());const id=JSON.parse(h.storage.getItem('gps_start:cfg_driver_action:TRIP')).id;await h.c.recover();assert.equal(JSON.parse(h.storage.getItem('gps_start:cfg_driver_action:TRIP')).id,id);await h.c.recover('Trip device unavailable');assert.equal(h.binding(),null);assert.equal(h.fixes(),0);
});
test('reload authenticates its original scoped source and resumes without another Start',async()=>{
 const first=harness();await first.start();first.c.hide();await flush();const second=harness({storage:first.storage});second.c.restore();await second.show();await flush();
 assert.equal(second.fixes(),1);assert(!second.calls.some(row=>row.method.endsWith('perform_driver_action')));assert.equal(second.binding().sequence,2);
});
test('hidden page fences late geolocation and resumes a new sampling generation',async()=>{
 const old=deferred();let count=0;const h=harness({position:()=>++count===1?old.promise:Promise.resolve({coords:{latitude:4,longitude:102,accuracy:10},timestamp:Date.now()})});await h.start();assert.equal(h.fixes(),1);h.c.hide();await flush();await h.show();await flush();assert.equal(h.fixes(),2);
 old.resolve({coords:{latitude:9,longitude:99,accuracy:10},timestamp:Date.now()});await flush();const publish=h.calls.filter(row=>row.method.endsWith('publish_position'));assert.equal(publish.length,1);assert.equal(publish[0].args.position_data.latitude,4);
});
test('hide fences in-flight publish sequence; late responses cannot restart sampling',async()=>{
 const wait=deferred();const h=harness({respond:async method=>method.endsWith('publish_position')?wait.promise:undefined});await h.start();h.c.hide();await flush();
 const pause=h.calls.find(row=>row.method.endsWith('pause_source'));assert.equal(pause.args.sequence_no,1);
 wait.resolve({status:'Recorded',gps:{state:'Live'}});await flush();assert.equal(h.timers.size,0);assert.notEqual(h.c.state.gps?.state,'Live');
});
test('scoped GPS sampling continues after normal delivery-login timeout and stops on explicit operator change',async()=>{
 const h=harness();await h.start();h.token(null);await h.c.context({active:true,token:null,operator:null,selected:null});await h.tick();assert.equal(h.fixes(),2);
 await h.c.operatorChanged();await flush();assert.equal(h.binding(),null);assert.equal(h.timers.size,0);assert.equal(h.positions.at(-1).gps.state,'Stopped');
});
test('changed operator/trip completion stops the source before further samples',async()=>{
 for(const state of [{operator:{employee:'OTHER'}},{detail:{trip:{name:'TRIP',driver_route_state:'Completed'}}}]){const h=harness();await h.start();await h.c.context(state);assert.equal(h.binding(),null);assert.equal(h.timers.size,0);}
});
test('permission denial stops scoped source; transient GPS timeout schedules a fresh fix',async()=>{
 const denied=harness({position:()=>Promise.reject({code:1})});await denied.start();await flush();assert.equal(denied.binding(),null);assert(denied.c.state.message.includes('permission denied'));
 let first=true;const h=harness({position:()=>{if(first){first=false;return Promise.reject({code:3,message:'Timeout'});}return Promise.resolve({coords:{latitude:1,longitude:2,accuracy:50},timestamp:Date.now()});}});await h.start();assert(h.binding());await h.tick();assert.equal(h.c.state.gps.state,'Live');
});
test('a revoked or replaced source clears its token and cannot start another device automatically',async()=>{
 const h=harness({respond:async method=>{if(method.endsWith('publish_position'))throw {exc_type:'GPSLeaseEnded',message:'Replaced'};}});await h.start();assert.equal(h.binding(),null);assert.equal(h.timers.size,0);assert.equal(h.calls.filter(row=>row.method.endsWith('perform_driver_action')).length,1);
});
test('Stop transport failure retains exact source for safe idempotent retry',async()=>{
 let fail=true;const h=harness({respond:async method=>{if(method.endsWith('stop_source')&&fail){fail=false;throw new Error('Offline');}}});await h.start();const original=h.binding();await h.c.stop();assert.equal(h.binding().state,'Stopping');assert.equal(h.timers.size,0);await h.c.stop();assert.equal(h.binding(),null);
 const stops=h.calls.filter(row=>row.method.endsWith('stop_source'));assert.deepEqual(stops[0].args,stops[1].args);assert.equal(stops[0].args.lease_id,original.lease_id);
});

test('Stop during a slow preflight cancels the not-yet-created source',async()=>{
 const wait=deferred(),h=harness({respond:async method=>method.endsWith('driver_action_context')?wait.promise:undefined});await h.show();const start=h.c.start();await h.c.stop();wait.resolve({revision:4,scope_hash:'SCOPE'});await start;assert.equal(h.binding(),null);assert.equal(h.fixes(),0);assert(!h.calls.some(row=>row.method.endsWith('perform_driver_action')));
});
test('pending request recovery adopts its original secret if only the source binding was lost',async()=>{
 let fail=true;const one=harness({respond:async method=>{if(method.endsWith('perform_driver_action')&&fail){fail=false;throw new Error('Lost');}}});await one.show();await assert.rejects(one.c.start());const request=JSON.parse(one.storage.getItem('gps_start:cfg_driver_action:TRIP')).request;one.storage.removeItem(api.bindingKey);
 const two=harness({storage:one.storage});await two.show();await assert.rejects(two.c.start(),/original request/);assert.equal(two.binding().publish_token,request.payload.publish_token);await two.c.start();await flush();assert.equal(two.c.state.binding.trip,'TRIP');assert.equal(two.fixes(),1);assert.equal(two.calls.find(row=>row.method.endsWith('source_status')).args.publish_token,request.payload.publish_token);
});
test('visible Stop is not queued behind a slow Start RPC, so a late confirmation cannot start sampling',async()=>{
 const nodes=new Map(),events=new Map(),storage=store(),wait=deferred(),positions=[],calls=[];
 class Node{html(){return this;}find(key){if(!nodes.has(key))nodes.set(key,new Node());return nodes.get(key);}text(value){this.caption=value;return this;}prop(){return this;}toggle(){return this;}val(){return ''; }on(type,selector,fn){events.set(selector,fn);return this;}}
 global.cfg_driver_route_actions=actions;global.isSecureContext=true;let seq=0;
 Object.defineProperty(global,'navigator',{configurable:true,value:{geolocation:{getCurrentPosition(){throw new Error('Must not sample stopped start');}},locks:{request:async(_key,fn)=>fn()}}});
 const f={call:async({method,args})=>{calls.push({method,args});return{message:method.endsWith('driver_action_context')?{revision:1,scope_hash:'SCOPE'}:method.endsWith('perform_driver_action')?await wait.promise:{state:'Stopped',position:null}};}};
 const ui=api.bind({frappe:f,host:new Node(),storage,deviceStorage:store(),locks:navigator.locks,owner:()=> 'EMP',token:()=> 'TOKEN',trip:()=> 'TRIP',nonce:()=> 'nonce_'+String(++seq).padStart(24,'0'),active:()=>true,error:e=>e.message,position:(trip,gps)=>positions.push(gps),supervisor:()=>false});
 await ui.show();const start=events.get('.cfg-gps-start')();await flush();assert(calls.some(row=>row.method.endsWith('perform_driver_action')));await events.get('.cfg-gps-stop')();assert.equal(ui.controller.state.binding.state,'Starting');
 wait.resolve({status:'Recorded',action:'Start GPS',result:{lease_id:'LEASE'}});await start;await flush();assert.equal(ui.controller.state.binding,null);assert(calls.some(row=>row.method.endsWith('stop_source')));assert.equal(positions.at(-1).state,'Stopped');ui.hide();
});

test('a late source read from an earlier visible generation cannot rewind the displayed fresh position',async()=>{
 const wait=deferred();let sources=0;const h=harness({respond:async method=>{if(method.endsWith('source_status')&&++sources===1)return wait.promise;}});
 await h.show();const start=h.c.start();await flush();h.c.hide();await flush();await h.show();await flush();assert.equal(h.c.state.gps.state,'Live');
 wait.resolve({state:'Paused',position:{latitude:9,longitude:99},last_sequence:0});await start;await flush();assert.equal(h.c.state.gps.state,'Live');assert.equal(h.c.state.gps.position.latitude,3.139);await h.c.stop();
});
test('a late pause response cannot repaint a resumed source as paused',async()=>{
 const wait=deferred();const h=harness({respond:async method=>method.endsWith('pause_source')?wait.promise:undefined});await h.start();h.c.hide();await h.show();await flush();assert.equal(h.c.state.gps.state,'Live');
 wait.resolve({state:'Paused',position:{latitude:1,longitude:2}});await flush();assert.equal(h.c.state.gps.state,'Live');await h.c.stop();
});
test('a late selected-Trip context cannot expose the old publisher after login expiry',async()=>{
 const wait=deferred(),h=harness({respond:async method=>method.endsWith('driver_context')?wait.promise:undefined});await h.show();const context=h.c.context({active:true,token:'TOKEN',operator:{employee:'EMP'},selected:'TRIP',detail:{refreshed_on:'1'}});
 h.token(null);await h.c.context({active:true,token:null,operator:null,selected:null});wait.resolve({can_share:true,gps:{state:'Live',publisher_employee:'EMP'}});await context;assert.equal(h.c.state.context,null);assert.equal(h.fixes(),0);
});
test('a temporary source-status outage retries automatically without renewing delivery login or inventing another Start',async()=>{
 let fail=true;const h=harness({respond:async method=>{if(method.endsWith('source_status')&&fail){fail=false;throw new Error('Offline');}}});await h.start();assert.equal(h.fixes(),0);assert.equal(h.timers.size,1);
 h.token(null);await h.tick();await flush();assert.equal(h.fixes(),1);assert.equal(h.c.state.gps.state,'Live');assert.equal(h.calls.filter(row=>row.method.endsWith('perform_driver_action')).length,1);await h.c.stop();
});
