/* Logistics floor: read-only dispatch visibility, using the existing Dashboard Profile. */
(function(root){
 "use strict";
 function render(data,e){
  const qty=(plan,key)=>Object.entries(plan.quantities_by_uom || {}).map(([uom,values])=>`${e(String(values[key] || 0))} ${e(uom)}`).join(" · ");
  function tile(plan){return `<article class="frappe-card p-3 mb-2"><strong>${e(plan.name)} · ${e(plan.business_label)}</strong>
   <div>${e(plan.customer || plan.delivery_route_reference || plan.territory || plan.logistics_route || "Route stock")}</div>
   <div>${e(plan.source_warehouse)} · ${e(plan.required_date || plan.trip_date || "")}</div>
   <div>${e(plan.destination_assignment_policy==='Fixed'?plan.destination_warehouse:'Lorry selected at loading')}</div>
   <span class="indicator-pill ${plan.state==='Ready for Vehicle'?'green':'orange'}">${e(plan.state)}</span>
   <div>${plan.state==='Loaded'?`Loaded: ${qty(plan,'loaded')}`:`Prepared: ${qty(plan,'reserved')} / ${qty(plan,'requested')}`}</div>
   ${(plan.stops || []).map(stop=>`<small class="d-block">${e(String(stop.planned_sequence || '—'))}. ${e(stop.site_name || stop.customer)} · ${e(stop.state)}</small>`).join("")}</article>`;}
  const ready=(data.preparing || []).filter(plan=>plan.state==='Ready for Vehicle');
  const upcoming=(data.preparing || []).filter(plan=>plan.state!=='Ready for Vehicle');
  const depth=Math.max(1,Number(data.profile.queue_depth)||5);
  const list=rows=>rows.slice(0,depth).map(tile).join('')+(rows.length>depth?`<p>${e(String(rows.length-depth))} more; open Logistics for the full queue.</p>`:'');
  return `<div class="cfg-logistics-floor"><div class="cfg-floor-head"><div><h2>${e(data.profile.profile_name)}</h2><p>${e(data.company)} · ${e(data.profile.description || 'Dispatch and lorry queues')}</p></div><div>Live refresh: ${e(String(data.profile.refresh_interval_seconds))}s</div></div>
   <div class="row"><section class="col-md-6"><h3>Ready to Load (${ready.length})</h3>${list(ready) || '<p>No loads are ready for vehicle assignment.</p>'}</section>
   <section class="col-md-6"><h3>Upcoming Preparation (${upcoming.length})</h3>${list(upcoming) || '<p>No upcoming preparation.</p>'}</section></div>
   <div class="row">${(data.vehicles || []).map(vehicle=>`<section class="col-md-6 col-xl-4"><div class="frappe-card p-3 mb-3"><h3>${e(vehicle.vehicle_reference || vehicle.name)}</h3><p>${e(vehicle.name)}</p>${list(vehicle.plans || []) || '<p>No active assigned loads.</p>'}</div></section>`).join('') || '<p>No readable lorry Warehouse is configured for this display.</p>'}</div>
   <p class="text-muted">${e(data.stock_note || '')}</p></div>`;
 }
 const api={render};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.cfg_logistics_floor=api;
})(typeof window==='undefined'?globalThis:window);
