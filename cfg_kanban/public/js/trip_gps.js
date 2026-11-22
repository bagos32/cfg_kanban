/* One visible foreground GPS publisher. Operator actions keep their normal inactivity timeout. */
(function(root){
 'use strict';
 const KEY='cfg_trip_gps_binding_v1',DEVICE='cfg_trip_gps_device_v1',prefix='cfg_kanban.services.trip_gps.';
 const ended=new Set(['Stopped','Trip Ended','Expired','Revoked']);
 function controller(env){
  let binding=null,action=null,visible=false,epoch=0,timer=null,busy=false,lastContext=null,contextTicket=0,inflightEpoch=null;
  const s={binding:null,gps:null,context:null,message:'',pending:false,busy:false};
  function render(){s.action_message=action?.state.message||'';s.binding=binding?{trip:binding.trip,actor:binding.actor,vehicle:binding.vehicle,state:binding.state,lease_until_ms:binding.lease_until_ms}:null;s.pending=Boolean(action?.state.pending);s.busy=busy||Boolean(action?.state.busy);env.render(s);}
  function save(){if(binding)env.storage.setItem(KEY,JSON.stringify(binding));else env.storage.removeItem(KEY);render();}
  function halt(){epoch++;busy=false;if(timer)env.clearTimer(timer);timer=null;}
  function clear(){halt();contextTicket++;lastContext=null;binding=null;s.gps=null;s.context=null;action?.close();action=null;save();}
  const rpc=(name,args)=>env.rpc(prefix+name,args);
  const args=()=>({trip_name:binding.trip,lease_id:binding.lease_id,publish_token:binding.publish_token});
  const valid=version=>version===epoch&&visible&&env.active()&&binding?.intent&&binding?.lease_id&&binding.state!=='Stopping';
  const fail=error=>{s.message=env.error(error);render();};
  function createAction(){
   action=env.actionController({storage:{getItem:key=>env.storage.getItem('gps_start:'+key),setItem:(key,value)=>env.storage.setItem('gps_start:'+key,value)},
    locks:env.locks,owner:env.owner,token:env.token,nonce:env.nonce,rpc:env.rpc,render,success:recorded});
   const saved=action.restore(binding.trip);
   if(saved?.status==='Pending'){if(saved.request.action!=='Start GPS')throw new Error('Reconcile the original GPS request first.');binding.actor=saved.actor;binding.device_id=saved.request.payload.device_id;binding.publish_token=saved.request.payload.publish_token;save();}
  }
  async function recorded(result){
   if(!binding)return;
   if(result.status==='Voided'){clear();s.message='The unrecorded GPS start was voided.';render();return;}
   const data=result.result;if(!data?.lease_id){s.message='GPS start recorded; check its saved source before continuing.';render();return;}
   Object.assign(binding,data,{vehicle:data.vehicle_reference||data.vehicle_warehouse,state:'Sharing'});save();
   if(!binding.intent)return stop();
   await resume();
  }
  async function refreshSource(version=epoch){
   if(!binding?.lease_id)return null;
   const id=binding.lease_id,result=await rpc('source_status',args());
   if(binding?.lease_id!==id||version!==epoch||!visible||!env.active())return null;
   s.gps=root.cfg_delivery_maps?.observeGPS(result)||result;binding.sequence=Math.max(binding.sequence||0,result.last_sequence||0);save();
   env.position(binding.trip,s.gps||result);
   if(ended.has(result.state)){const label=result.state;clear();s.message='GPS sharing '+label.toLowerCase()+'. Identify the assigned driver and Share GPS to start again.';render();return null;}
   return result;
  }
  async function sample(version){
   if(!valid(version)||busy)return;
   busy=true;inflightEpoch=version;render();
   try{
    const pos=await env.positionOnce();if(!valid(version))return;
    const fix={latitude:pos.coords.latitude,longitude:pos.coords.longitude,accuracy:pos.coords.accuracy,captured_ms:pos.timestamp};
    binding.sequence=(binding.sequence||0)+1;save();const id=binding.lease_id;
    const result=await rpc('publish_position',{...args(),position_data:fix,sequence_no:binding.sequence});
    if(!valid(version)||binding.lease_id!==id)return;
    s.gps=root.cfg_delivery_maps?.observeGPS(result.gps)||result.gps;s.message='GPS sharing active. Keep Driver Route visible on the device travelling with the lorry.';env.position(binding.trip,s.gps);render();
   }catch(error){
    if(!valid(version))return;
    const type=error?.exc_type||error?.responseJSON?.exc_type;
    if(type==='GPSLeaseEnded'||type==='PermissionError'){clear();fail(error);return;}
    if(error?.code===1){await stop();s.message='Location permission denied. Enable device/browser location, then Share GPS.';render();return;}
    fail(error);
   }finally{
    if(inflightEpoch===version)busy=false;render();if(valid(version))timer=env.setTimer(()=>sample(version),(binding.publish_interval_seconds||15)*1000);
   }
  }
  async function resume(){
   if(!visible||!env.active()||!binding?.intent||!binding.lease_id||busy)return;
   halt();const version=epoch;
   try{if(await refreshSource(version)){if(valid(version))sample(version);}}
   catch(error){if(version===epoch){const type=error?.exc_type||error?.responseJSON?.exc_type;if(type==='GPSLeaseEnded'||type==='PermissionError')clear();fail(error);if(valid(version))timer=env.setTimer(()=>resume(),15000);}}
  }
  async function start(){
   if(busy||action?.state.busy)return;
   if(!env.available())throw new Error('GPS sharing requires HTTPS and location support on the lorry device.');
   if(!env.owner()||!env.token())throw new Error('Identify the assigned driver before starting GPS sharing.');
   if(binding){
    if(action?.state.pending)return action.retry();
    if(binding.state==='Starting')return recover();
    if(binding.state==='Stopping')return stop();
    throw new Error('This device is already sharing '+binding.trip+'. Stop it before starting or renewing another source.');
   }
   if(!env.locks?.request)throw new Error('GPS sharing requires browser Web Locks.');
   const trip=env.trip();if(!trip)throw new Error('Select the active Delivery Trip first.');
   const actor=env.owner(),token=env.token(),version=epoch;
   const context=await env.rpc('cfg_kanban.services.driver_route_actions.driver_action_context',{trip_name:trip,operation:'Start GPS',operator_session_token:token});
   if(version!==epoch||actor!==env.owner()||token!==env.token()||trip!==env.trip()||!env.active())return;
   let device=env.deviceStorage.getItem(DEVICE);if(!device){device=env.nonce();env.deviceStorage.setItem(DEVICE,device);}
   binding={v:1,trip,actor,device_id:device,publish_token:env.nonce()+env.nonce(),sequence:0,intent:true,state:'Starting'};
   try{save();createAction();await action.mutate(context,'Start GPS',{device_id:device,publish_token:binding.publish_token});}
   catch(error){if(!action){binding=null;render();}else if(binding&&!action.state.pending&&!action.state.busy&&action.state.baseline){clear();}throw error;}
  }
  async function recover(reason){
   if(action?.state.pending)return action.reconcile(reason);
   if(!binding)return;
   if(binding.lease_id)return refreshSource();
   if(!env.token()||env.owner()!==binding.actor)throw new Error('Reidentify the original GPS publisher to recover its recorded start.');
   const result=await rpc('driver_context',{trip_name:binding.trip,operator_session_token:env.token()});
   if(!result.gps.lease_id)throw new Error('No GPS source found. Reconcile the original start before replacing it.');
   binding.lease_id=result.gps.lease_id;
   try{const own=await rpc('source_status',args());Object.assign(binding,{lease_until_ms:own.lease_until_ms,vehicle:own.vehicle_reference||own.vehicle_warehouse,state:'Sharing'});save();if(binding.intent)await resume();else await stop();}
   catch(error){delete binding.lease_id;throw error;}
  }
  async function stop(){
   halt();if(!binding)return;binding.intent=false;try{save();}catch(error){fail(error);}
   if(!binding.lease_id){
    s.message='GPS start outcome is unresolved. Retry/check the original request; a Supervisor can void it if unrecorded. No location is being sampled.';render();return;
   }
   binding.state='Stopping';save();const id=binding.lease_id;
   try{const result=await rpc('stop_source',args());if(binding?.lease_id===id){env.position(binding.trip,root.cfg_delivery_maps?.observeGPS(result)||result);clear();s.message='GPS sharing stopped.';render();}}
   catch(error){const type=error?.exc_type||error?.responseJSON?.exc_type;if(type==='GPSLeaseEnded')clear();fail(error);}
  }
  async function context(state){
   if(binding&&state.operator?.employee&&state.operator.employee!==binding.actor){await stop();return;}
   if(binding&&state.detail?.trip?.name===binding.trip&&['Completed','Closed Incomplete'].includes(state.detail.trip.driver_route_state)){await stop();return;}
   if(state.busy||!state.active||!state.token||!state.operator||!state.selected){contextTicket++;lastContext=null;s.context=null;render();return;}
   const token=state.token,trip=state.selected,actor=state.operator.employee;
   const key=state.token+':'+state.selected+':'+state.detail?.refreshed_on;if(key===lastContext)return;lastContext=key;const version=++contextTicket;
   try{const result=await rpc('driver_context',{trip_name:state.selected,operator_session_token:state.token});if(version!==contextTicket||!env.active()||env.token()!==token||env.trip()!==trip||env.owner()!==actor)return;s.context={...result,gps:root.cfg_delivery_maps?.observeGPS(result.gps)||result.gps};render();}
   catch(error){if(version===contextTicket){s.context=null;if(!binding)fail(error);}}
  }
  function restore(){
   const raw=env.storage.getItem(KEY);if(!raw)return;
   let value;try{value=JSON.parse(raw);}catch(_){throw new Error('Stored GPS source is unreadable; ask a Supervisor to release it.');}
   if(value.v!==1||!value.trip||!value.actor||!value.publish_token||!['Starting','Sharing','Stopping'].includes(value.state))throw new Error('Stored GPS source is invalid; ask a Supervisor to release it.');
   binding=value;createAction();render();
  }
  return {state:s,start,stop,recover,context,restore,
   async show(){visible=true;if(binding?.state==='Stopping')await stop();else if(binding?.lease_id)await resume();render();},
   hide(){visible=false;halt();if(binding?.lease_id&&binding.state!=='Stopping'){const id=binding.lease_id,version=epoch;rpc('pause_source',{...args(),sequence_no:binding.sequence||0}).then(result=>{if(binding?.lease_id===id&&version===epoch&&!visible){s.gps=root.cfg_delivery_maps?.observeGPS(result)||result;env.position(binding.trip,s.gps||result);render();}}).catch(()=>{});}render();},
   async operatorChanged(){await stop();},
  };
 }
 function bind(options){
  const f=options.frappe,host=options.host;let app,tail=Promise.resolve();
  const queue=work=>{tail=tail.then(work).catch(error=>{host.find('.cfg-gps-message').text(options.error(error));});return tail;};
  host.html('<section class="frappe-card p-3 mt-3"><strong>Trip GPS sharing</strong><p class="cfg-gps-status"></p><p class="cfg-gps-message" role="status"></p><div class="driver-action-controls"><button class="btn btn-default cfg-gps-start">Share GPS / Retry Start</button><button class="btn btn-default cfg-gps-stop">Stop GPS / Retry Stop</button><button class="btn btn-default cfg-gps-read">Check Saved GPS Source</button><input class="form-control cfg-gps-void-reason" placeholder="Supervisor reason to void an unrecorded GPS start"><button class="btn btn-warning cfg-gps-void">Void Unrecorded Start</button></div><small>Use one device travelling with the lorry. Keep this page visible; locked/background pages may pause. GPS continues independently of the delivery-action login timeout. Sharing permission lasts 12 hours; stop/start to renew.</small></section>');
  app=controller({...options,actionController:root.cfg_driver_route_actions.controller,
   rpc:async(method,args)=>(await f.call({method,args})).message,
   available:()=>root.isSecureContext!==false&&Boolean(root.navigator?.geolocation),
   positionOnce:()=>new Promise((resolve,reject)=>root.navigator.geolocation.getCurrentPosition(resolve,reject,{enableHighAccuracy:true,timeout:12000,maximumAge:0})),
   setTimer:(fn,ms)=>root.setTimeout(fn,ms),clearTimer:id=>root.clearTimeout(id),
   render:s=>{
    const row=s.binding,gps=s.gps||s.context?.gps;
    host.find('.cfg-gps-status').text(row?`${row.trip} · ${row.vehicle||''} · ${row.actor} · ${row.state}${gps?' · '+(root.cfg_delivery_maps?.gpsText(gps)||gps.state):''}${row.lease_until_ms?' · Until '+new Date(row.lease_until_ms).toLocaleString():''}`:gps?`Selected Trip GPS: ${gps.state}${gps.publisher_employee?' · '+gps.publisher_employee:''}`:'Select an active Trip and Share GPS on its lorry device.');
    host.find('.cfg-gps-message').text([s.message,s.action_message].filter(Boolean).join(' '));
    host.find('.cfg-gps-start').prop('disabled',s.busy||(!s.binding&&!s.context?.can_share));host.find('.cfg-gps-stop').prop('disabled',!row);
    host.find('.cfg-gps-void,.cfg-gps-void-reason').toggle(Boolean(s.pending)&&options.supervisor());
   }});
  host.on('click.cfg_gps','.cfg-gps-start',()=>queue(()=>app.start())).on('click.cfg_gps','.cfg-gps-stop',()=>app.stop().catch(error=>host.find('.cfg-gps-message').text(options.error(error))))
   .on('click.cfg_gps','.cfg-gps-read',()=>queue(()=>app.recover())).on('click.cfg_gps','.cfg-gps-void',()=>queue(()=>{const reason=String(host.find('.cfg-gps-void-reason').val()||'').trim();if(!reason)throw new Error('Enter the Supervisor reason.');return app.recover(reason);}));
  try{app.restore();}catch(error){host.find('.cfg-gps-message').text(options.error(error));}
  return {context:state=>queue(()=>app.context(state)),show:()=>queue(()=>app.show()),hide:()=>app.hide(),operatorChanged:()=>app.operatorChanged(),
   scan:value=>value==='CFG:CMD:GPS_STOP'?app.stop():queue(()=>value==='CFG:CMD:GPS_SHARE'?app.start():app.recover()),controller:app};
 }
 const api={controller,bind,bindingKey:KEY};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.cfg_trip_gps=api;
})(typeof window==='undefined'?globalThis:window);
