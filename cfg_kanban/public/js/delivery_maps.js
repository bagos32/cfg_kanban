/* Optional Site pins and read-only driver maps. Directions use official universal URLs. */
(function(root){
 'use strict';
 const defaults=f=>(root.cfg_kanban_map_defaults||(typeof require==='function'?require('./map_defaults.js'):null))?.apply(f)||{center:[3.139,101.6869],zoom:13};
 const tr=value=>typeof __==='function'?__(value):value;
 const escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
 function pin(value){
  if(!value||typeof value.latitude!=='number'||typeof value.longitude!=='number'||!Number.isFinite(value.latitude)||!Number.isFinite(value.longitude)||Math.abs(value.latitude)>90||Math.abs(value.longitude)>180)return null;
  return {latitude:value.latitude,longitude:value.longitude};
 }
 function readPoint(value){
  if(value==null||value==='')return null;
  const data=typeof value==='string'?JSON.parse(value):value;
  if(data==null)return null;
  const features=data.type==='FeatureCollection'?data.features:[data];
  if(!Array.isArray(features)||features.length>1)throw new Error('Keep one Delivery Pin marker.');
  if(!features.length)return null;
  const feature=features[0],props=feature?.properties??{},coords=feature?.geometry?.coordinates;
  if(typeof props!=='object'||Array.isArray(props)||feature?.type!=='Feature'||feature?.geometry?.type!=='Point'||!Array.isArray(coords)||coords.length!==2||['circle','circlemarker'].includes(props.point_type))throw new Error('Use one Delivery Pin marker, not a shape.');
  const result=pin({latitude:coords[1],longitude:coords[0]});if(!result)throw new Error('Delivery Pin coordinates are invalid.');return result;
 }
 function pointJSON(latitude,longitude){
  const decimal=value=>typeof value==='number'?value:typeof value==='string'&&/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(value.trim())?Number(value):NaN;
  const result=pin({latitude:decimal(latitude),longitude:decimal(longitude)});
  if(!result)throw new Error('Enter Latitude (-90 to 90) and Longitude (-180 to 180).');
  return JSON.stringify({type:'FeatureCollection',features:[{type:'Feature',properties:{},geometry:{type:'Point',coordinates:[result.longitude,result.latitude]}}]});
 }
 function urls(stop){
  const saved=pin(stop?.delivery_pin),address=String(stop?.address||'').trim();
  const destination=saved?`${saved.latitude},${saved.longitude}`:address;
  if(!destination)return null;
  // https://developers.google.com/maps/documentation/urls/guide
  const google=new URL('https://www.google.com/maps/dir/');google.search=new URLSearchParams({api:'1',destination,travelmode:'driving',dir_action:'navigate'});
  // https://developers.google.com/waze/deeplinks -- omit origin; the map app handles device location.
  const waze=new URL('https://waze.com/ul');waze.search=new URLSearchParams(saved?{ll:destination,navigate:'yes',utm_source:'cfg_kanban'}:{q:address,utm_source:'cfg_kanban'});
  if(google.href.length>2048||waze.href.length>2048)return null;
  return {google:google.href,waze:waze.href,kind:saved?'pin':'address'};
 }
 function navigationHTML(state){
  const data=state.detail,next=data?.stops?.find(row=>row.stop_key===data.next_stop_key);
  if(!next||['Closed','Cancelled'].includes(data.trip.planning_state)||['Completed','Closed Incomplete'].includes(data.trip.driver_route_state))return '';
  const links=urls(next),disabled=Boolean(state.stale||state.busy||state.active===false);
  const title=data.current_stop_key?tr('Directions to current stop'):tr('Directions to next stop');
  const message=links?.kind==='pin'?tr('Saved customer delivery pin'):next.delivery_pin_status==='Invalid'?tr('Delivery pin needs correction. Check the address search result before navigation.'):tr('No saved delivery pin. Check the address search result before navigation.');
  const button=(label,url)=>disabled?`<button class="btn btn-default" disabled>${tr(label)}</button>`:`<a class="btn btn-primary cfg-driver-directions" href="${escape(url)}" target="_blank" rel="noopener noreferrer">${tr(label)}</a>`;
  return `<div class="cfg-driver-navigation"><strong>${title}: ${escape(next.site_name||next.customer_name)}</strong><p>${escape(links?message:tr('Set a Delivery Pin or delivery address on the Customer Site before opening directions.'))}</p>${links?button(links.kind==='pin'?'Google Maps':'Google Maps — Address',links.google)+button(links.kind==='pin'?'Waze':'Waze — Search Address',links.waze):''}${disabled?`<small>${tr('Refresh the route before opening directions.')}</small>`:''}</div>`;
 }
 function observeGPS(gps,now=Date.now()){return gps?{...gps,observed_ms:now}:null;}
 function gpsDisplay(gps,now=Date.now()){
  if(!gps)return {state:'Not Shared',live:false,position:null,age_seconds:null};
  const point=pin(gps.position),elapsed=Number.isFinite(gps.observed_ms)?Math.max(0,now-gps.observed_ms)/1000:0;
  const age=Number.isFinite(gps.age_seconds)?gps.age_seconds+elapsed:null;
  let state=gps.state||'Not Shared';
  if(['Live','Low Accuracy'].includes(state)&&(!point||age===null||age>(gps.stale_after_seconds||90)))state='Stale';
  return {...gps,observed_ms:now,state,live:['Live','Low Accuracy'].includes(state),position:point?{...point,accuracy:gps.position.accuracy,captured_ms:gps.position.captured_ms}:null,age_seconds:age};
 }
 function gpsText(gps){
  const row=gpsDisplay(gps),age=row.age_seconds===null?'No fix':Math.floor(row.age_seconds)+'s ago';
  return `${row.state} · ${age}${Number.isFinite(gps?.position?.accuracy)?' · ±'+Math.round(gps.position.accuracy)+' m':''}`;
 }
 function vehicleHTML(row){
  const gps=row.gps,trip=row.trip||{};
  return `<div><strong>${escape(gps.vehicle_reference||gps.vehicle_warehouse||trip.vehicle_warehouse||'Lorry')}</strong><div>${escape(trip.trip_title||trip.name||'')}</div><div>${escape(gpsText(gps))}</div>${gps.live?'':`<strong>${tr('Last known position; not a live fix')}</strong>`}<div>${tr('Publisher')}: ${escape(gps.publisher_employee||'—')}</div>${trip.name?`<button type="button" class="btn btn-default" data-map-trip="${escape(trip.name)}">${tr('View Trip')}</button>`:''}</div>`;
 }
 function mapSpec(detail){
  const groups=new Map();let located=0;
  for(const stop of detail?.stops||[]){
   const point=pin(stop.delivery_pin);if(!point)continue;located++;
   const key=`${point.latitude},${point.longitude}`;
   if(!groups.has(key))groups.set(key,{point,stops:[],kind:'pending'});
   groups.get(key).stops.push(stop);
  }
  for(const group of groups.values()){
   if(group.stops.some(row=>row.stop_key===detail.current_stop_key))group.kind='current';
   else if(group.stops.some(row=>row.stop_key===detail.next_stop_key))group.kind='next';
   else if(group.stops.every(row=>row.driver_completed_on||['Completed','Completed with refusal','Visit completed'].includes(row.state)))group.kind='completed';
   else if(group.stops.some(row=>['Review required','Awaiting proof','Delivery Note pending','Awaiting stop completion'].includes(row.state)))group.kind='attention';
  }
  return {groups:[...groups.values()],located,total:detail?.stops?.length||0,vehicles:(detail?.vehicle_locations||[]).map(row=>({...row,gps:gpsDisplay(row.gps)})).filter(row=>row.gps.position)};
 }
 function popupHTML(stops){
  return stops.map(stop=>`<div class="cfg-driver-map-stop"><strong>${escape(stop.sequence)}. ${escape(stop.site_name||stop.customer_name)}</strong><div>${escape(stop.state)} · ${escape(stop.purpose)}</div><div>${escape(stop.address)}</div>${(stop.items||[]).map(row=>`<div>${escape(row.item_code)} · ${escape(row.planned_qty)} ${escape(row.stock_uom)}${(row.orders||[]).map(order=>` · ${escape(order.sales_order)} / ${escape(order.customer_po||'—')}`).join('')}</div>`).join('')}<button type="button" class="btn btn-default btn-sm" data-map-stop="${escape(stop.stop_key)}">${tr('View Stop')}</button></div>`).join('');
 }
 let libraryPromise=null;
 async function leaflet(f){
  if(libraryPromise)return libraryPromise;
  libraryPromise=(async()=>{
   await f.require('/assets/frappe/js/lib/leaflet/leaflet.css');
   if(!root.L)await f.require('/assets/frappe/js/lib/leaflet/leaflet.js');
   if(!root.L?.map)throw new Error('Map library unavailable');
   return root.L;
  })().catch(error=>{libraryPromise=null;throw error;});
  return libraryPromise;
 }
 function createRouteMap(options){
  const f=options.frappe,doc=options.document||root.document;
  let node=null,map=null,markers=null,latest=null,ticket=0,owner=null,trip=null,signature=null,failed=false,tileError=false,locations=null,follow=false,hadPositions=false,hadVehicles=false;
  const valid=()=>latest&&owner&&owner===options.identity();
  function detach(){if(node?.parentNode)node.parentNode.removeChild(node);}
  function clear(){ticket++;try{map?.remove();}catch(_){}map=null;markers=null;detach();node=null;latest=null;owner=null;trip=null;signature=null;locations=null;failed=false;tileError=false;follow=false;hadPositions=false;hadVehicles=false;}
  function fit(){if(map&&markers&&(markers._cfgCount||0))map.fitBounds(markers.getBounds(),{padding:[28,28],maxZoom:16});else if(map){const d=defaults(f);map.setView(d.center,d.zoom);}}
  function makeNode(){
   node=doc.createElement('section');node.className='cfg-driver-map';
   node.innerHTML=`<h4>${tr('Trip locations')}</h4><p class="cfg-driver-map-info"></p><div class="cfg-driver-map-legend"><span class="next">${tr('Next / Current')}</span><span class="completed">${tr('Completed')}</span><span class="pending">${tr('Pending')}</span><span class="attention">${tr('Check')}</span><span class="vehicle">${tr('Lorry GPS')}</span><span class="last-known">${tr('Last known')}</span></div><div class="cfg-driver-map-canvas" role="region" aria-label="${tr('Customer stops and lorry locations')}"></div><div class="cfg-driver-map-controls"><button type="button" class="btn btn-default cfg-map-kl">Kuala Lumpur</button> <button type="button" class="btn btn-default cfg-map-fit">${tr('Fit Locations')}</button> <button type="button" class="btn btn-default cfg-map-follow" aria-pressed="false">${tr('Follow Lorry: Off')}</button></div><p class="cfg-driver-map-message" role="status"></p><button type="button" class="btn btn-default cfg-driver-map-retry" hidden>${tr('Retry Map')}</button>`;
   node.addEventListener('click',event=>{
    if(!valid())return;
    if(event.target.closest?.('.cfg-map-kl')){follow=false;const d=defaults(f);map?.setView(d.center,d.zoom);followLabel();return;}
    if(event.target.closest?.('.cfg-map-fit')){follow=false;fit();followLabel();return;}
    if(event.target.closest?.('.cfg-map-follow')){follow=!follow;followLabel();signature=null;update(latest,node.parentNode);return;}
    if(latest.stale||latest.busy)return;
    const selected=event.target.closest?.('[data-map-stop]'),vehicle=event.target.closest?.('[data-map-trip]');
    if(selected){const key=selected.getAttribute('data-map-stop');if(latest.detail.stops.some(row=>row.stop_key===key))options.pick?.(key);return;}
    if(vehicle){const key=vehicle.getAttribute('data-map-trip');if((latest.detail.vehicle_locations||[]).some(row=>row.trip?.name===key))options.pickTrip?.(key);return;}
    if(event.target.closest?.('.cfg-driver-map-retry')){failed=false;signature=null;update(latest,node.parentNode);}
   });
  }
  function followLabel(){const button=node?.querySelector('.cfg-map-follow');if(button){button.textContent=tr(follow?'Follow Lorry: On':'Follow Lorry: Off');button.setAttribute?.('aria-pressed',String(follow));}}
  function message(text,retry=false){if(!node)return;node.querySelector('.cfg-driver-map-message').textContent=text;const button=node.querySelector('.cfg-driver-map-retry');button.hidden=!retry;button.disabled=Boolean(latest?.stale||latest?.busy);}
  function status(){
   const spec=mapSpec(latest?.detail);
   message(latest?.stale?tr('View not refreshed. Location may be stale; refresh before acting.'):failed?tr('Map unavailable. Delivery controls remain available; retry the map.'):tileError?tr('Map tiles unavailable. Delivery controls remain available.'):!spec.located&&!spec.vehicles.length?tr('No saved locations. Map opens at Kuala Lumpur; office can add customer pins. No lorry position is assumed.'):'',failed);
  }
  function update(state,slot){
   const identity=options.identity();
   if(!slot||!state.detail||!state.active||!identity){clear();return;}
   if(owner!==identity||trip!==state.detail.trip.name){clear();owner=identity;trip=state.detail.trip.name;}
   latest=state;if(!node)makeNode();slot.appendChild(node);
   const spec=mapSpec(state.detail);
   node.querySelector('.cfg-driver-map-info').textContent=`${spec.located} / ${spec.total} ${tr('stops have a delivery pin. Numbered pins follow the current stop sequence.')} ${spec.vehicles.length} ${tr('lorry positions. Grey positions are last known, not live.')}`;
   node.querySelector('.cfg-map-follow').hidden=spec.vehicles.length!==1;
   const content=JSON.stringify(spec);
   if(signature===content||failed){map?.invalidateSize();status();return;}
   signature=content;const version=++ticket;
   (options.load||(()=>leaflet(f)))().then(L=>{
    if(!valid()||version!==ticket)return;
    const canvas=node.querySelector('.cfg-driver-map-canvas');
    const first=!map;
    if(!map){
     const d=defaults(f);map=L.map(canvas);map.setView(d.center,d.zoom);
     const provider=f.utils.map_defaults,tileMap=map;
     L.tileLayer(provider.tiles,provider.options).on('tileerror',()=>{if(valid()&&map===tileMap){tileError=true;status();}}).on('tileload',()=>{if(valid()&&map===tileMap){tileError=false;status();}}).addTo(map);
    }
    if(markers)map.removeLayer(markers);
    markers=L.featureGroup();markers._cfgCount=spec.groups.length+spec.vehicles.length;
    for(const group of spec.groups){
     const numbers=group.stops.map(row=>row.sequence),label=numbers.length>2?`${numbers[0]} +${numbers.length-1}`:numbers.join(' / ');
     const icon=L.divIcon({className:`cfg-driver-map-pin ${group.kind}`,html:`<span>${escape(label)}</span>`,iconSize:[44,36],iconAnchor:[22,36]});
     L.marker([group.point.latitude,group.point.longitude],{icon,keyboard:true,title:group.stops.map(row=>`${row.sequence}. ${row.site_name||row.customer_name}`).join(' / ')}).bindPopup(popupHTML(group.stops),{maxWidth:360}).addTo(markers);
    }
    for(const row of spec.vehicles){
     const gps=row.gps,icon=L.divIcon({className:`cfg-driver-map-pin ${gps.live?'vehicle':'last-known'}`,html:`<span>${escape(gps.vehicle_reference||'Lorry')}</span>`,iconSize:[72,36],iconAnchor:[36,18]});
     L.marker([gps.position.latitude,gps.position.longitude],{icon,keyboard:true,title:gpsText(gps)}).bindPopup(vehicleHTML(row),{maxWidth:360}).addTo(markers);
    }
    markers.addTo(map);
    // GPS motion/status refresh must not override a manually chosen map viewport.
    const nextLocations=JSON.stringify(spec.groups.map(group=>group.point));
    if(first||locations!==nextLocations||(!hadVehicles&&spec.vehicles.length)||(hadPositions&&!spec.groups.length&&!spec.vehicles.length))fit();
    hadVehicles=Boolean(spec.vehicles.length);
    hadPositions=Boolean(spec.groups.length||spec.vehicles.length);
    locations=nextLocations;
    if(follow&&spec.vehicles.length===1&&spec.vehicles[0].gps.live){const p=spec.vehicles[0].gps.position;map.panTo([p.latitude,p.longitude]);}
    map.invalidateSize();followLabel();status();
   }).catch(()=>{if(valid()&&version===ticket){failed=true;status();}});
  }
  return {update,detach,clear};
 }
 function pinTools(frm,f){
  const field=frm.fields_dict.delivery_pin_tools;if(!field)return;
  let value=null;try{value=readPoint(frm.doc.delivery_location);}catch(_){}
  const write=f.perm.has_perm(frm.doctype,0,frm.is_new()?'create':'write',frm.doc),host=field.$wrapper;
  host.html(`<div class="row"><label class="col-sm-5">${tr('Latitude')}<input class="form-control cfg-site-latitude" inputmode="decimal" autocomplete="off" value="${escape(value?.latitude??'')}"${write?'':' disabled'}></label><label class="col-sm-5">${tr('Longitude')}<input class="form-control cfg-site-longitude" inputmode="decimal" autocomplete="off" value="${escape(value?.longitude??'')}"${write?'':' disabled'}></label></div><div class="mb-3"><button type="button" class="btn btn-default cfg-site-set-pin"${write?'':' disabled'}>${tr('Set Pin')}</button> <button type="button" class="btn btn-default cfg-site-clear-pin"${write?'':' disabled'}>${tr('Clear Pin')}</button>${value?` <a class="btn btn-default" href="${escape('https://www.google.com/maps/search/?'+new URLSearchParams({api:'1',query:`${value.latitude},${value.longitude}`}))}" target="_blank" rel="noopener noreferrer">${tr('View Pin in Google Maps')}</a>`:''}</div><p class="text-muted">${tr('Paste coordinates from your map, or use the marker tool below. Set Pin replaces the previous marker. Save the Customer Site to publish the pin.')}</p><p class="cfg-site-pin-status" role="status"></p>`);
  host.off('.cfg_delivery_pin').on('click.cfg_delivery_pin','.cfg-site-set-pin',async()=>{
   if(!write)return;try{await frm.set_value('delivery_location',pointJSON(host.find('.cfg-site-latitude').val(),host.find('.cfg-site-longitude').val()));host.find('.cfg-site-pin-status').text(tr('Pin updated. Save the Customer Site.'));}catch(error){host.find('.cfg-site-pin-status').text(error.message);}
  }).on('click.cfg_delivery_pin','.cfg-site-clear-pin',async()=>{if(!write)return;await frm.set_value('delivery_location',null);host.find('.cfg-site-pin-status').text(tr('Pin cleared. Save the Customer Site.'));});
 }
 const api={pin,readPoint,pointJSON,urls,navigationHTML,mapSpec,popupHTML,createRouteMap,pinTools,observeGPS,gpsDisplay,gpsText,vehicleHTML};
 if(typeof module!=='undefined'&&module.exports)module.exports=api;root.cfg_delivery_maps=api;
})(typeof window==='undefined'?globalThis:window);
