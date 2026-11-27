/* Shared field-panel navigation and visible, server-backed readiness states. */
(function(root,factory){const api=factory(root);if(typeof module==='object'&&module.exports)module.exports=api;else root.cfg_field_ui=api;})(typeof window==='undefined'?globalThis:window,function(root){
 'use strict';
 const esc=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
 const memory=new Map(),toolbars=new Map(),NAV={LOGISTICS_PANEL:'kanban-logistics',DRIVER_ROUTE:'kanban-driver-route'};
 let toolbarEvents=false;
 function manifestStatus(row,manifest){
  const receipt=['Dispatched','Awaiting Receipt','Receipt Document Pending'].includes(manifest.state)||manifest.receipt_retry_available;
  const physical=row.line_kind!=='ERP Stock without Physical Tag';
  if(receipt&&physical)return row.receipt_scanned?{color:'green',label:'Receipt scan confirmed'}:{color:'orange',label:'Awaiting receipt scan'};
  if(manifest.dispatch_plan_loading||manifest.dispatch_recovery)return row.loading_confirmed?{color:'green',label:physical?'Tag loading confirmed':'Physical quantity confirmed'}:{color:'orange',label:physical?'Awaiting tag loading scan':'Awaiting physical quantity confirmation'};
  if(row.receipt_scanned||row.state==='Received')return {color:'green',label:'Received'};
  if(physical&&(row.scanned_on||row.scan_event_key))return {color:'green',label:'Tag registered on this Manifest'};
  return !physical&&row.scan_event_key?{color:'green',label:'ERP stock quantity registered'}:{color:'orange',label:physical?'Awaiting tag scan':'ERP stock quantity'};
 }
 function planStatus(plan){
  const review=plan.review_state||plan.dispatch_review_state;
  if(plan.state==='Reconciled')return {color:'green',label:'Settled — ready for closure'};
  if(plan.state==='Cancelled')return {color:'gray',label:'Cancelled — history retained'};
  if(plan.state==='Exception'||review==='Exception')return {color:'red',label:'Recovery required'};
  if(review)return {color:'orange',label:review==='Completed'?'Plan settlement still pending':'Settlement '+review};
  return {color:'orange',label:plan.fulfilment_status==='Completed'?'Delivered — settlement pending':'Settlement pending'};
 }
 function badge(status){return `<span class="cfg-field-badge cfg-field-${esc(status.color)}">${esc(status.label)}</span>`;}
 function storageKey(employee){return 'cfg_field_trip:'+String(root.frappe?.session?.user||'')+':'+String(employee||'');}
 function remember(context){
  if(!context?.trip||!context.employee)return;
  const key=storageKey(context.employee),trip=String(context.trip);memory.set(key,trip);
  try{root.sessionStorage?.setItem(key,trip);}catch(_){}
 }
 function lastTrip(context){
  if(context?.trip)return String(context.trip);
  if(!context?.employee)return null;
  const key=storageKey(context.employee);try{return root.sessionStorage?.getItem(key)||memory.get(key)||null;}catch(_){return memory.get(key)||null;}
 }
 function navigate(panel,context){
  remember(context);
  const trip=panel==='driver'?lastTrip(context):null;
  root.frappe.set_route(panel==='driver'?'kanban-driver-route':'kanban-logistics',...(trip?[trip]:[]));
 }
 function command(raw,context){const text=String(raw||'').trim().toUpperCase();if(!text.startsWith('CFG:CMD:'))return false;const name=text.slice(8);if(!NAV[name])return false;navigate(name==='DRIVER_ROUTE'?'driver':'logistics',context);return true;}
 function switchHTML(panel){return `<nav class="cfg-panel-switch" data-panel="${esc(panel)}" aria-label="Field panels"><span class="cfg-panel-slider" aria-hidden="true"></span><button type="button" data-cfg-panel="driver" aria-pressed="${panel==='driver'}">Driver Route</button><button type="button" data-cfg-panel="logistics" aria-pressed="${panel==='logistics'}">Logistics</button></nav>`;}
 function mountSwitch(page,panel,context){
  const title=page.get_title_area?.()||page.$title_area||page.wrapper?.find?.('.title-area');
  const heading=title?.closest('.page-title');
  const parent=heading?.length?heading:page.main||page;
  if(heading?.length){heading.addClass('cfg-field-heading');heading.closest('.page-head-content').addClass('cfg-field-heading-row');}
  const host=root.$(switchHTML(panel)).appendTo(parent);
  host.on('click.cfg_panel','[data-cfg-panel]',event=>navigate(root.$(event.currentTarget).attr('data-cfg-panel'),context()));
  const sync=()=>remember(context());sync();return {sync,host};
 }
 function menuShift(rect,width,margin=12){return rect.left<margin?margin-rect.left:rect.right>width-margin?width-margin-rect.right:0;}
 function toolbar(page){
  const host=page?.wrapper?.addClass?page.wrapper:root.$(page?.main).closest('.page-container');
  function clamp(menu){if(!menu)return;
   menu.style.setProperty('--cfg-menu-shift','0px');
   const width=root.document.documentElement.clientWidth||root.innerWidth;
   menu.style.setProperty('--cfg-menu-shift',menuShift(menu.getBoundingClientRect(),width)+'px');
  }
  const kind=()=>root.frappe?.get_route?.()[0]==='kanban-operator'?'production':'trip';
  toolbars.set(host[0],kind());
  host.addClass('cfg-field-actions').off('shown.bs.dropdown.cfg_field').on('shown.bs.dropdown.cfg_field',event=>clamp(event.target.querySelector?.('.dropdown-menu')));
  if(!toolbarEvents){toolbarEvents=true;
   root.addEventListener?.('resize',()=>{for(const node of toolbars.keys())if(node?.isConnected&&node.classList.contains('cfg-field-actions'))for(const menu of node.querySelectorAll('.dropdown-menu.show,.open > .dropdown-menu'))clamp(menu);});
   root.frappe?.router?.on?.('change',()=>{
    const route=root.frappe.get_route(),active=route[0]==='kanban-operator'?'production':route[0]==='Form'&&route[1]==='CFG Kanban Delivery Trip'?'trip':null;
    // Frappe reuses the Form wrapper. Do not restyle the next ordinary ERPNext form.
    for(const [node,type] of toolbars)node?.classList.toggle('cfg-field-actions',active===type);
   });
  }
 }
 return {manifestStatus,planStatus,badge,remember,lastTrip,navigate,command,switchHTML,mountSwitch,menuShift,toolbar};
});
