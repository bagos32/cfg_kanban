/* Supervisor visibility uses the existing Trip/delivery projection and one real GPS source. */
(function(root){
 'use strict';
 const SESSION='cfg_kanban_operator_session',prefix='cfg_kanban.services.trip_gps.';
 const tr=v=>typeof __==='function'?__(v):v;
 const escape=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
 const maps=()=>root.cfg_delivery_maps||(typeof require==='function'?require('./delivery_maps.js'):null);
 function controller(env){
  const s={active:false,token:null,operator:null,company:'',include_closed:false,start:0,has_more:false,trips:[],selected:null,detail:null,gps:null,stop:null,busy:false,stale:false,error:''};
  let epoch=0;
  const read=()=>env.storage.getItem(SESSION),emit=()=>env.render(s);
  function clear(){s.trips=[];s.detail=null;s.gps=null;s.operator=null;s.stop=null;s.error='';s.stale=false;}
  function sync(){const token=read();if(token!==s.token){epoch++;clear();s.token=token;s.selected=null;s.busy=false;s.start=0;return true;}}
  const valid=(version,token)=>s.active&&version===epoch&&token===s.token&&token===read();
  async function refresh(selected=s.selected,interactive=false){
   const changed=sync();if(changed)selected=null;
   if(!s.active)return;
   s.selected=selected||null;if(!s.token){clear();emit();return;}
   const version=++epoch,token=s.token;
   if(s.detail?.trip.name!==s.selected){s.detail=null;s.gps=null;s.stop=null;}
   s.busy=true;s.error='';emit();
   try{
    const result=await env.rpc(prefix+'supervisor_fleet',{operator_session_token:token,company:s.company||null,include_closed:Number(s.include_closed),start:s.start,interactive:Number(interactive)});
    if(!valid(version,token))return;
    s.trips=(result.trips||[]).map(row=>({...row,gps:maps().observeGPS(row.gps)}));s.operator=result.operator;s.has_more=Boolean(result.has_more);
    if(s.selected){
     const data=await env.rpc(prefix+'supervisor_trip',{trip_name:s.selected,operator_session_token:token,interactive:0});
     if(!valid(version,token))return;
     if(s.company&&data.detail.trip.company!==s.company)throw new Error('Selected Trip belongs to a different Company filter.');
     s.detail=data.detail;s.gps=maps().observeGPS(data.gps);
     if(s.stop&&!s.detail.stops.some(row=>row.stop_key===s.stop))s.stop=null;
    }
    s.stale=false;
   }catch(error){
    if(!valid(version,token))return;
    s.error=env.error(error);s.stale=true;
    if(error?.exc_type||error?.responseJSON?.exc_type||error?._server_messages||error?.responseJSON?._server_messages){clear();s.error=env.error(error);s.stale=true;}
   }finally{if(read()!==s.token){sync();emit();}else if(valid(version,token)){s.busy=false;emit();}}
  }
  return {state:s,refresh,
   async identify(value,pin){
    if(s.busy||!s.active)return;let token=String(value||'').trim();try{token=new URLSearchParams(new URL(token).hash.replace(/^#/, '')).get('operator')||token;}catch(_){}
    if(!token)return;const version=++epoch,baseline=read();clear();s.busy=true;emit();
    try{const result=await env.rpc('cfg_kanban.api.operator.login_operator',{token,pin:pin||'',station:env.storage.getItem('cfg_kanban_station')||''});
     if(!s.active||version!==epoch||baseline!==read())return;env.storage.setItem(SESSION,result.session_token);s.token=result.session_token;s.busy=false;return refresh(null,true);
    }catch(error){if(s.active&&version===epoch)s.error=env.error(error);}finally{if(version===epoch){s.busy=false;emit();}}
   },
   select(name){s.stop=null;return refresh(name,true);},
   viewStop(key){if(sync()){emit();return;}if(s.detail?.stops.some(row=>row.stop_key===key)){s.stop=key;emit();}},
   settings(company,closed){s.trips=[];s.company=company||'';s.include_closed=Boolean(closed);s.start=0;return refresh(null,true);},
   page(delta){if(s.busy)return;s.start=Math.max(0,s.start+delta*20);return refresh(s.selected,true);},
   show(name){s.active=true;sync();return refresh(name||s.selected,false);},
   hide(){s.active=false;epoch++;clear();s.busy=false;emit();},
   changeOperator(){epoch++;clear();s.token=null;s.selected=null;s.busy=false;env.storage.removeItem(SESSION);emit();},
   paint:emit,
  };
 }
 function mapState(state){
  const detail=state.detail?{...state.detail,vehicle_locations:[{trip:state.detail.trip,gps:state.gps}]}:{trip:{name:'__fleet__'},stops:[],vehicle_locations:state.trips};
  return {...state,detail};
 }
 function fleetHTML(state){
  return '<h3>'+tr('Lorries on Trips')+'</h3>'+maps().statusLegend(true)+state.trips.map(row=>`<button type="button" class="btn btn-default cfg-monitor-trip cfg-status-${maps().tripKind(row.trip)}${row.trip.name===state.selected?' selected':''}" data-trip="${escape(row.trip.name)}"><strong>${escape(row.gps.vehicle_reference||row.gps.vehicle_warehouse||row.trip.vehicle_warehouse||'Lorry')}</strong><span>${escape(row.trip.trip_title)} · ${escape(row.trip.name)}</span><span>${escape(row.trip.company)} · ${escape(row.trip.trip_date)}${row.trip.expected_return_date?' → '+escape(row.trip.expected_return_date):''}</span><span>${escape(row.trip.driver_route_state)}</span><span>${tr('Assigned Driver')}: ${escape(row.trip.driver_display||row.trip.driver||'—')}</span><span>${escape(maps().gpsText(row.gps))}</span></button>`).join('')+(!state.trips.length?`<p>${tr('No accessible Trips match this page/filter. Active multi-day Trips remain listed.')}</p>`:'');
 }
 function detailHTML(state){
  const data=state.detail;if(!data)return `<h3>${tr('Fleet overview')}</h3><p>${tr('Choose a Trip to see its customer sequence and delivery status. Only devices explicitly sharing a real location have a lorry marker.')}</p>`;
  const next=data.stops.find(row=>row.stop_key===data.next_stop_key),chosen=data.stops.find(row=>row.stop_key===(state.stop||data.next_stop_key));
  return `<h3>${escape(data.trip.trip_title)} · ${escape(data.trip.name)}</h3><a class="btn btn-default" href="/app/kanban-driver-route/${encodeURIComponent(data.trip.name)}">Open Trip / Customer Stop Controls</a><p>${escape(data.trip.company)} · ${escape(data.trip.driver_route_state)} · ${escape(data.sequence_source)} · ${escape(data.refreshed_on)}</p><p><strong>${tr(data.current_stop_key?'Current stop':'Next stop')}:</strong> ${escape(next?.site_name||next?.customer_name||'—')} · ${escape(next?.state||'')}</p><p><strong>${tr('Assigned Driver')}:</strong> ${escape(data.trip.driver_display||data.trip.driver||'—')} · ${(data.trip.assistant_drivers||[]).map(row=>escape(maps().person(row.employee,row.employee_name))).join(', ')}</p><p><strong>GPS:</strong> ${escape(maps().gpsText(state.gps))} · ${tr('Publisher')}: ${escape(maps().person(state.gps?.publisher_employee,state.gps?.publisher_name))} · ${tr('Last received')}: ${escape(state.gps?.received_on||'—')}</p>${!maps().gpsDisplay(state.gps).live?`<p class="alert alert-warning">${tr('A displayed lorry position is last known. Fresh GPS updates are unavailable; check the source device.')}</p>`:''}
   ${state.operator?.can_override&&state.gps?.lease_id?`<button class="btn btn-warning cfg-monitor-release">${tr('Release GPS Source / Recover Request')}</button>`:''}
   ${maps().statusLegend()}<ol class="cfg-monitor-stops">${data.stops.map(row=>`<li><button type="button" class="btn btn-default cfg-monitor-stop cfg-status-${maps().stopKind(row,data)}" data-monitor-stop="${escape(row.stop_key)}"><strong>${escape(row.sequence)}. ${escape(row.site_name||row.customer_name)}</strong> · ${escape(row.state)} · ${escape(row.purpose)}</button></li>`).join('')}</ol>
   ${root.cfg_driver_route?.cancelledView?.(data)||''}
   ${(data.warnings||[]).map(text=>`<p class="alert alert-warning">${escape(text)}</p>`).join('')}
   ${chosen?`<section class="frappe-card p-3"><h4>${escape(chosen.site_name||chosen.customer_name)}</h4><p>${escape(chosen.address)}</p><div class="table-responsive"><table class="table table-bordered"><thead><tr><th>Product / SO / Customer PO</th><th>Planned</th><th>Loaded</th><th>Delivered</th><th>Remaining</th></tr></thead><tbody>${chosen.items.map(row=>`<tr><td>${escape(row.item_code)}${row.orders.map(order=>`<br>${escape(order.sales_order)} / ${escape(order.customer_po||'—')}`).join('')}</td><td>${escape(row.planned_qty)} ${escape(row.stock_uom)}</td><td>${escape(row.loaded_qty)}</td><td>${escape(row.delivered_qty)}</td><td>${escape(row.remaining_qty)}</td></tr>`).join('')}</tbody></table></div>${chosen.sources.map(row=>`<p>${escape(row.tag_code||row.allocation_kind)} · ${escape(row.item_code)} · ${escape(row.remaining_qty)} ${escape(row.stock_uom)} · ${escape(row.source_state)}</p>`).join('')}</section>`:''}`;
 }
 function releaseController(env){
  let context=null,lease=null;
  const action=env.actions({...env,storage:{getItem:key=>env.storage.getItem('gps_release:'+key),setItem:(key,value)=>env.storage.setItem('gps_release:'+key,value)}});
  return {state:action.state,
   async open(trip,leaseId){lease=leaseId;action.restore(trip);if(!action.state.pending)context=await env.rpc('cfg_kanban.services.driver_route_actions.driver_action_context',{trip_name:trip,operation:'Release GPS',operator_session_token:env.token()});},
   async confirm(reason){if(action.state.pending)return action.retry();if(!String(reason||'').trim())throw new Error('Enter the GPS source release reason.');if(!context)throw new Error('Refresh the release context first.');return action.mutate(context,'Release GPS',{lease_id:lease,reason:String(reason).trim()});},
   check:reason=>action.reconcile(reason),close:()=>action.close(),
  };
 }
 function mount(wrapper){
  const f=root.frappe,page=f.ui.make_app_page({parent:wrapper,title:tr('Supervisor Live Map'),single_column:true}),host=$('<div class="cfg-trip-monitor"></div>').appendTo(page.main);
  host.html(`<section class="frappe-card p-3"><strong class="cfg-monitor-identity"></strong><div class="cfg-monitor-controls"><input class="form-control cfg-monitor-credential" autocomplete="off" placeholder="Supervisor credential"><input class="form-control cfg-monitor-pin" type="password" placeholder="PIN if required"><button class="btn btn-primary cfg-monitor-login">Sign in</button><button class="btn btn-default cfg-monitor-camera">Scan with Camera</button><button class="btn btn-default cfg-monitor-change">Change Operator</button><button class="btn btn-default cfg-monitor-refresh">Refresh</button><button class="btn btn-default cfg-monitor-fleet">Fleet Overview</button></div><p>Supervisor + View All Responsibilities and Customer Delivery are required. Native Company permissions apply. Release also requires Override.</p><div class="cfg-monitor-company"></div><label><input type="checkbox" class="cfg-monitor-closed"> Include completed Trips / last known locations</label><p class="cfg-monitor-notice" role="status"></p></section><div class="cfg-monitor-layout"><aside><div class="cfg-monitor-list"></div><button class="btn btn-default cfg-monitor-prev">Previous</button> <button class="btn btn-default cfg-monitor-next">Next</button></aside><main><div class="cfg-monitor-map-slot"></div><div class="cfg-monitor-detail"></div><div class="cfg-monitor-release-host"></div></main></div>`);
  const rpc=async(method,args)=>(await f.call({method,args})).message,error=e=>root.cfg_driver_route.message(e),storage=root.localStorage;
  let routeMap=null,timer=null,release=null,releaseTrip=null,releaseToken=null,camera=null,cameraEpoch=0;
  const active=()=>app.state.active&&f.get_route()?.[0]==='kanban-trip-monitor';
  const notice=text=>host.find('.cfg-monitor-notice').text(text||'');
  function stopCamera(){cameraEpoch++;camera?.stop_scan?.();camera?.dialog?.hide?.();camera=null;}
  function closeRelease(){release?.close();release=null;releaseTrip=null;releaseToken=null;host.find('.cfg-monitor-release-host').empty();}
  const app=controller({rpc,storage,error,render:s=>{
   if(release&&(!s.active||s.token!==releaseToken||!s.operator||s.stale||s.selected!==releaseTrip))closeRelease();
   host.find('.cfg-monitor-identity').text(s.operator?`${s.operator.employee} · ${s.operator.kanban_role}`:'Identify a Supervisor to view the fleet.');
   host.find('.cfg-monitor-list').html(fleetHTML(s));host.find('.cfg-monitor-detail').html(detailHTML(s));
   host.find('.cfg-monitor-prev').prop('disabled',s.busy||Boolean(release)||s.start===0);host.find('.cfg-monitor-next').prop('disabled',s.busy||Boolean(release)||!s.has_more);
   notice(s.error||(s.busy?'Refreshing…':''));routeMap?.update(mapState(s),s.token&&s.operator?host.find('.cfg-monitor-map-slot')[0]:null);
  }});
  routeMap=maps().createRouteMap({frappe:f,identity:()=>active()&&storage.getItem(SESSION)===app.state.token&&app.state.operator?`${app.state.token}:${app.state.operator.employee}`:null,pick:key=>{if(!release)app.viewStop(key);},pickTrip:name=>{if(!release)app.select(name);}});
  let company;company=f.ui.form.make_control({parent:host.find('.cfg-monitor-company'),df:{fieldname:'company',fieldtype:'Link',options:'Company',label:tr('Company filter'),change:()=>{if(!company)return;closeRelease();app.settings(company.get_value(),host.find('.cfg-monitor-closed').prop('checked'));}},render_input:true});
  async function login(value){stopCamera();closeRelease();await app.identify(value??host.find('.cfg-monitor-credential').val(),host.find('.cfg-monitor-pin').val());host.find('.cfg-monitor-credential,.cfg-monitor-pin').val('');}
  host.on('click.cfg_monitor','.cfg-monitor-login',()=>login()).on('keydown.cfg_monitor','.cfg-monitor-credential',event=>{if(['Enter','Tab'].includes(event.key)&&!event.shiftKey&&!event.ctrlKey&&!event.altKey&&!event.metaKey&&!event.isComposing&&host.find('.cfg-monitor-credential').val()){event.preventDefault();event.stopPropagation();login();}})
   .on('click.cfg_monitor','.cfg-monitor-change',()=>{stopCamera();closeRelease();app.changeOperator();host.find('.cfg-monitor-credential').trigger('focus');})
   .on('click.cfg_monitor','.cfg-monitor-refresh',()=>{if(release)notice('Close the GPS release review before refreshing the map.');else app.refresh(app.state.selected,true);})
   .on('click.cfg_monitor','.cfg-monitor-trip',event=>{closeRelease();app.select($(event.currentTarget).attr('data-trip'));})
   .on('click.cfg_monitor','[data-monitor-stop]',event=>app.viewStop($(event.currentTarget).attr('data-monitor-stop')))
   .on('click.cfg_monitor','.cfg-monitor-fleet',()=>{closeRelease();app.select(null);})
   .on('click.cfg_monitor','.cfg-monitor-prev',()=>app.page(-1)).on('click.cfg_monitor','.cfg-monitor-next',()=>app.page(1))
   .on('change.cfg_monitor','.cfg-monitor-closed',()=>{closeRelease();app.settings(company.get_value(),host.find('.cfg-monitor-closed').prop('checked'));})
   .on('click.cfg_monitor','.cfg-monitor-camera',()=>{stopCamera();if(!f.ui.Scanner){notice('Camera unavailable; use the scanner field.');return;}const version=cameraEpoch,baseline=storage.getItem(SESSION);let accepted=false;
    try{camera=new f.ui.Scanner({dialog:true,multiple:false,on_scan:data=>{if(accepted||!active()||version!==cameraEpoch||baseline!==storage.getItem(SESSION))return;accepted=true;login(data.decodedText);}});camera.dialog?.$wrapper?.one?.('hidden.bs.modal.cfg_monitor',()=>{stopCamera();host.find('.cfg-monitor-credential').trigger('focus');});}catch(e){notice(error(e));}});
  host.on('click.cfg_monitor','.cfg-monitor-release',async()=>{
   if(storage.getItem(SESSION)!==app.state.token){app.refresh(null,false);return;}
   if(release||!active()||!app.state.operator?.can_override||app.state.busy||app.state.stale)return;
   releaseTrip=app.state.selected;releaseToken=app.state.token;const owner=app.state.operator.employee,lease=app.state.gps?.lease_id,box=host.find('.cfg-monitor-release-host');
   box.html('<section class="frappe-card p-3"><h4>Release GPS source</h4><p>Stop an unavailable device before another assigned driver starts sharing. This does not change delivery or stock.</p><input class="form-control cfg-monitor-release-reason" placeholder="Supervisor release / void reason"><input class="form-control cfg-monitor-release-void-reason" placeholder="Reason to void an unrecorded release"><p class="cfg-monitor-release-message" role="status"></p><div class="cfg-monitor-controls"><button class="btn btn-warning cfg-monitor-release-confirm">Release / Retry Original</button><button class="btn btn-default cfg-monitor-release-check">Check Saved Outcome</button><button class="btn btn-warning cfg-monitor-release-void">Void If Unrecorded</button><button class="btn btn-default cfg-monitor-release-close">Close</button></div></section>');
   try{release=releaseController({actions:root.cfg_driver_route_actions.controller,storage:root.sessionStorage,locks:root.navigator.locks,nonce:()=>root.crypto.randomUUID(),rpc,owner:()=>app.state.operator?.employee===owner?owner:null,token:()=>storage.getItem(SESSION)===releaseToken?releaseToken:null,
    render:s=>{box.find('.cfg-monitor-release-confirm,.cfg-monitor-release-check,.cfg-monitor-release-void').prop('disabled',s.busy);box.find('.cfg-monitor-release-reason').prop('disabled',s.busy||Boolean(s.pending));box.find('.cfg-monitor-release-message').text(s.pending?'Original release retained. Retry/check it before changing details.':s.message);},
    success:async result=>{if(active()&&app.state.token===releaseToken){closeRelease();await app.refresh(app.state.selected,true);notice(result.status==='Voided'?'Unrecorded GPS release voided.':'GPS source released.');}}});await release.open(releaseTrip,lease);}catch(e){notice(error(e));}
  });
  async function releaseWork(kind){if(!release)return;const current=release,reason=host.find(kind==='void'?'.cfg-monitor-release-void-reason':'.cfg-monitor-release-reason').val();try{if(kind==='confirm')await current.confirm(reason);else{if(kind==='void'&&!String(reason||'').trim())throw new Error('Enter a Supervisor reason to void.');await current.check(kind==='void'?reason:null);}}catch(e){host.find('.cfg-monitor-release-message').text(error(e));}}
  host.on('click.cfg_monitor','.cfg-monitor-release-confirm',()=>releaseWork('confirm')).on('click.cfg_monitor','.cfg-monitor-release-check',()=>releaseWork('check')).on('click.cfg_monitor','.cfg-monitor-release-void',()=>releaseWork('void')).on('click.cfg_monitor','.cfg-monitor-release-close',closeRelease);
  function tick(){if(!active()||root.document.hidden)return;if(release)app.paint();else if(!app.state.busy)app.refresh(app.state.selected,false);}
  root.addEventListener('storage',event=>{if(event.key===SESSION&&active()){stopCamera();closeRelease();app.refresh(null,false);}});
  root.document.addEventListener('visibilitychange',()=>{if(!root.document.hidden)tick();});
  const lifecycle={async show(name){if(!timer)timer=root.setInterval(tick,15000);await app.show(name);},hide(){closeRelease();stopCamera();routeMap.clear();app.hide();if(timer)root.clearInterval(timer);timer=null;},app};
  f.router?.on?.('change',()=>{if(f.get_route()?.[0]!=='kanban-trip-monitor')lifecycle.hide();});
  return lifecycle;
 }
 const api={controller,mapState,fleetHTML,detailHTML,releaseController,mount};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.cfg_trip_monitor=api;
})(typeof window==='undefined'?globalThis:window);
