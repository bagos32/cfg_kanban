/* A return worklist over the existing QC, credit and physical-disposition workflows. */
(function(root){
 'use strict';
 const SESSION='cfg_kanban_operator_session',prefix='cfg_kanban.services.return_qc_monitor.';
 const tr=v=>typeof __==='function'?__(v):v;
 const escape=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
 const defaults=()=>({view:'Needs Follow-up',sort:'Oldest intake first'});
 function message(error){
  const value=error?.responseJSON||error;
  try{if(value?._server_messages)return JSON.parse(value._server_messages).map(row=>typeof row==='string'?JSON.parse(row).message:row.message).filter(Boolean).join(' ');}catch(_){}
  return error?.message||tr('Could not refresh the return worklist. Retry Refresh.');
 }
 function scan(value){
  const text=String(value||'').trim();
  try{
   const url=new URL(text),operator=new URLSearchParams(url.hash.replace(/^#/, '')).get('operator');
   if(operator)return {kind:'operator',value:operator};
   const match=url.pathname.match(/^\/app\/(?:cfg-kanban-return-case|kanban-return-qc)\/([^/]+)\/?$/);
   return match?{kind:'case',value:decodeURIComponent(match[1])}:{kind:'unknown',value:text};
  }catch(_){return {kind:text.includes('://')?'unknown':/^KRTN-/i.test(text)?'case':'raw',value:text};}
 }
 function controller(env){
  const s={active:false,token:null,operator:null,filters:defaults(),rows:[],counts:{},total:0,start:0,
   has_more:false,companies:[],states:[],selected:null,detail:null,busy:false,stale:false,error:'',refreshed_on:null,reset_revision:0};
  let epoch=0,storageError=false;
  const emit=()=>env.render(s);
  function read(){try{const token=env.storage.getItem(SESSION);storageError=false;return token;}catch(_){storageError=true;return null;}}
  function clear(reset=false){s.operator=null;s.rows=[];s.counts={};s.total=0;s.detail=null;s.companies=[];s.states=[];s.refreshed_on=null;s.has_more=false;s.stale=false;s.error='';if(reset){s.reset_revision++;s.filters=defaults();s.start=0;s.selected=null;}}
  function sync(){const token=read();if(token!==s.token){epoch++;clear(true);s.token=token;s.busy=false;return true;}}
  const valid=(version,token)=>s.active&&epoch===version&&s.token===token&&read()===token;
  async function refresh(selected=s.selected,interactive=false){
   const old=s.token,changed=sync();if(changed&&old)selected=null;
   if(!s.active)return;
   s.selected=selected||null;
   if(!s.token){clear();s.error=storageError?tr('Browser storage is unavailable. Enable storage and sign in again.'):'';emit();return;}
   const version=++epoch,token=s.token;
   if(s.detail?.name!==s.selected)s.detail=null;
   s.busy=true;s.error='';emit();
   try{
    const result=await env.rpc(prefix+'get_qc_worklist',{operator_session_token:token,filters:{...s.filters},start:s.start,page_length:10,interactive:Number(interactive)});
    if(!valid(version,token))return;
    s.operator=result.operator;s.rows=result.rows||[];s.counts=result.counts||{};s.total=result.total||0;s.has_more=Boolean(result.has_more);
    s.companies=result.companies||[];s.states=result.states||[];s.filters={...defaults(),...result.filters};s.refreshed_on=result.refreshed_on;
    if(s.selected){
     const detail=await env.rpc(prefix+'get_qc_case',{scan_value:s.selected,operator_session_token:token,company:s.filters.company||null,interactive:0});
     if(!valid(version,token))return;
     if(detail.actor!==s.operator.employee)throw new Error('QC operator changed. Refresh the worklist.');
     if(s.filters.company&&detail.selling_company!==s.filters.company)throw new Error('Selected return belongs to a different Company filter.');
     s.detail=detail;s.selected=detail.name;
    }
    s.stale=false;
   }catch(error){
    if(!valid(version,token))return;
    const rejected=Boolean(error?.exc_type||error?.responseJSON?.exc_type||error?._server_messages||error?.responseJSON?._server_messages);
    if(rejected){clear(true);if(/operator session|scan your operator QR|profile is inactive|terminal login/i.test(message(error))){try{if(read()===token)env.storage.removeItem(SESSION);}catch(_){}s.token=null;}}
    s.error=message(error);s.stale=true;
   }finally{if(read()!==s.token){sync();emit();}else if(valid(version,token)){s.busy=false;emit();}else if(s.active&&epoch===version&&!s.token){s.busy=false;emit();}}
  }
  async function identify(value,pin=''){
   const target=scan(value);sync();
   if(target.kind==='case'){s.selected=target.value;env.notify?.(tr('Sign in with your QC operator credential, then open this return.'));emit();return;}
   if(target.kind==='unknown'||!target.value){env.notify?.(tr('Scan the QC operator credential.'));return;}
   if(s.busy&&!s.token)return;
   const before=read(),version=++epoch;clear();s.busy=true;emit();
   try{
    let station='';try{station=env.storage.getItem('cfg_kanban_station')||'';}catch(_){}
    const result=await env.rpc('cfg_kanban.api.operator.login_operator',{token:target.value,pin,station});
    if(!s.active||version!==epoch)return;
    if(read()!==before){sync();emit();return;}
    try{env.storage.setItem(SESSION,result.session_token);}catch(_){throw new Error('Browser storage is unavailable. Enable storage and sign in again.');}
    s.token=result.session_token;s.busy=false;return refresh(s.selected,true);
   }catch(error){if(s.active&&epoch===version){s.error=message(error);s.busy=false;emit();}}
  }
  function ready(){if(sync()){emit();return false;}return Boolean(s.active&&s.token&&s.operator&&!s.busy&&!s.stale&&s.detail);}
  return {state:s,refresh,identify,
   async show(name){s.active=true;return refresh(name||s.selected,false);},
   hide(){s.active=false;epoch++;s.busy=false;clear(true);emit();},
   settings(values){if(sync()){emit();return;}s.filters={...defaults(),...values};s.start=0;s.detail=null;s.selected=null;return refresh(null,true);},
   page(delta){if(sync()){emit();return;}if(!s.active||s.busy||!s.token||delta>0&&!s.has_more)return;s.start=Math.max(0,s.start+delta*10);s.detail=null;s.selected=null;return refresh(null,true);},
   select(name){if(sync()){emit();return;}if(!s.rows.some(row=>row.name===name))return;return refresh(name,true);},
   async openScan(value){if(sync()){emit();return;}return refresh(value,true);},
   session(){if(sync())emit();return s.token;},
   changeOperator(){epoch++;clear(true);s.token=null;s.busy=false;try{env.storage.removeItem(SESSION);}catch(_){}emit();},
   inspect(){if(!ready()||!s.detail.can_inspect)return;env.inspect({name:s.detail.name,operator:s.operator.employee});},
   record(){if(!ready())return;env.record('CFG Kanban Return Case',s.detail.name);},
   linked(index){if(!ready())return;const link=s.detail.links?.[index];if(link&&LINKS.has(link.doctype))env.record(link.doctype,link.name);},
   async scan(value,pin){const target=scan(value);if(!this.session())return identify(value,pin);if(target.kind==='operator'){env.notify?.(tr('Choose Change Operator before signing in as another person.'));return;}if(target.kind==='unknown'){env.notify?.(tr('Scan a Temporary Return Note or case number.'));return;}return this.openScan(target.value);},
  };
 }
 const LINKS=new Set(['Sales Invoice','Credit Note','Delivery Note','Stock Entry','CFG Kanban Delivery Trip','CFG Kanban Delivery Outcome']);
 function age(seconds){if(seconds===null||seconds===undefined)return '—';const n=Number(seconds);if(!Number.isFinite(n)||n<0)return '—';return n>=86400?`${Math.floor(n/86400)} d ${Math.floor(n%86400/3600)} h`:n>=3600?`${Math.floor(n/3600)} h ${Math.floor(n%3600/60)} min`:`${Math.floor(n/60)} min`;}
 function nextHTML(rows){return (rows||[]).map(row=>`<div class="cfg-qc-follow"><strong>${escape(row.owner)}</strong> · ${escape(row.label)}</div>`).join('')||`<span class="text-muted">${tr('No pending action in the recorded case state')}</span>`;}
 function summaryHTML(s){
  return `<div class="cfg-qc-totals"><strong>${escape(s.total)} ${tr('matching cases')}</strong>${Object.entries(s.counts).map(([state,total])=>`<span>${escape(state)}: <b>${escape(total)}</b></span>`).join('')}</div><small>${tr('Counts follow the active filters and your native permissions. Accounting and stock are separate tracks; quantities are shown in their own UOM.')}</small>`;
 }
 function listHTML(s){
  if(!s.operator)return `<p>${tr('Identify a Customer Return QC operator to view accessible returns.')}</p>`;
  return `<div class="table-responsive"><table class="table table-bordered cfg-qc-table"><thead><tr><th>${tr('Return / Customer')}</th><th>${tr('Inspection / Age since intake')}</th><th>${tr('Accounting / Stock')}</th><th>${tr('Pending follow-up')}</th></tr></thead><tbody>${s.rows.map((row,index)=>`<tr${s.selected===row.name?' class="active"':''}><td><button class="btn btn-default cfg-qc-select" data-case="${escape(row.name)}"${s.busy||s.stale?' disabled':''}><strong>${index+1}. ${escape(row.name)}</strong></button><div>${escape(row.customer)} · ${escape(row.site_name||'')}</div><small>${escape(row.selling_company)} · ${escape(row.kind)}</small><div>${escape(row.driver_trip||'')}</div></td><td><strong>${escape(row.inspection)}</strong><div>${escape(row.state)}</div><div>${escape(age(row.age_seconds))}</div><small>${escape(row.inspection_location||'—')} · ${row.return_flow!=='Customer Return for QC'?tr('QC not applicable'):row.received_on?tr('QC receipt acknowledged'):tr('QC receipt unconfirmed')}</small></td><td><div>${tr('Accounts')}: ${escape(row.accounting_status||'—')}</div><small>${tr('Credit')}: ${escape(row.credit_document_status||'—')} · ${tr('Accounting return')}: ${escape(row.accounting_sales_invoice_status||'—')}</small><div>${tr('Physical stock')}: ${escape(row.disposition_status||'—')}</div><small>${tr('Receipt')}: ${escape(row.stock_disposition_entry_status||'—')}</small></td><td>${nextHTML(row.follow_up)}</td></tr>`).join('')||`<tr><td colspan="4">${tr('No matching cases. Change the filters or select All Returns for history.')}</td></tr>`}</tbody></table></div>`;
 }
 function detailHTML(s){
  const d=s.detail;if(!d)return `<p class="text-muted">${tr('Select a case or scan its Temporary Return Note for items, inspection results and follow-up links.')}</p>`;
  const disabled=s.busy||s.stale||!s.operator?' disabled':'';
  return `<section class="frappe-card cfg-qc-detail p-3"><h3>${escape(d.name)} · ${escape(d.customer)}</h3><p><strong>${escape(d.selling_company)} · ${escape(d.kind)} · ${escape(d.state)}</strong></p><div class="cfg-qc-actions"><button class="btn btn-default cfg-qc-record"${disabled}>${tr('Open Return Case')}</button>${d.can_inspect?`<button class="btn btn-primary cfg-qc-inspect"${disabled}>${tr('Open QC Inspection')}</button>`:''}</div><p>${tr('Inspection custody location')}: ${escape(d.inspection_location||'—')} · ${d.return_flow!=='Customer Return for QC'?tr('QC not applicable'):d.received_on?tr('QC receipt acknowledged'):tr('QC receipt unconfirmed')}</p><p>${tr('Collection lorry (recorded)')}: ${escape(d.collection_vehicle_warehouse||'—')} · ${escape(d.driver_trip||'')}</p><p>${escape(d.customer_return_reason||'')}</p><p>${tr('Reported source reference')}: ${escape(d.reported_source_reference||'—')}</p>${d.stock_already_owned?`<div class="alert alert-warning">${tr('Company-owned refused goods. Use their controlled release, recovery or disposal. No customer credit or duplicate stock receipt.')}</div>`:d.return_flow==='Customer Return for QC'?`<div class="alert alert-info">${tr('Old customer goods remain controlled custody until the existing QC and physical disposition steps complete. Accounting credit is separate.')}</div>`:''}
   <h4>${tr('Pending follow-up')}</h4>${nextHTML(d.follow_up)}${(d.warnings||[]).map(v=>`<p class="alert alert-warning">${escape(v)}</p>`).join('')}
   <div class="table-responsive"><table class="table table-bordered"><thead><tr><th>${tr('Item / Tag / Batch / Expiry')}</th><th>${tr('UOM')}</th><th>${tr('Claimed')}</th><th>${tr('Received')}</th><th>${tr('Accepted')}</th><th>${tr('Rejected')}</th><th>${tr('QC result / Reason')}</th></tr></thead><tbody>${(d.lines||[]).map(row=>`<tr><td>${escape(row.item_code)}<br>${escape(row.original_visible_code||'—')} · ${escape(row.batch_no||'—')}<br>${escape(row.expiry_date||'—')}</td><td>${escape(row.stock_uom)}</td><td>${escape(row.claimed_qty??'—')}</td><td>${escape(row.received_qty??'—')}</td><td>${escape(row.accepted_qty??'—')}</td><td>${escape(row.rejected_qty??'—')}</td><td>${escape(row.qc_disposition||'Pending')}<br>${escape(row.qc_reason||'')}<br>${escape(row.condition||'')}</td></tr>`).join('')}</tbody></table></div>
   <div>${Object.entries(d.totals_by_uom||{}).map(([unit,v])=>`<p><strong>${escape(unit)}</strong> · ${tr('Claimed / Received / Accepted / Rejected')}: ${escape(v.claimed_qty??'—')} / ${escape(v.received_qty??'—')} / ${escape(v.accepted_qty??'—')} / ${escape(v.rejected_qty??'—')}</p>`).join('')}</div>
   ${(d.owned_custody||[]).map(row=>`<p>${escape(row.visible_code||row.item_code)} · ${escape(row.qty)} ${escape(row.stock_uom)} · ${escape(row.stock_state)} · ${escape(row.warehouse)}</p>`).join('')}
   <p>${tr('QC notes')}: ${escape(d.qc_notes||'—')}</p><p>${tr('QC operator')}: ${escape(d.qc_operator||'—')} · ${tr('Started')}: ${escape(d.qc_started_on||'—')} · ${tr('Completed')}: ${escape(d.qc_completed_on||'—')}</p>
   <div class="cfg-qc-actions">${(d.links||[]).filter(row=>LINKS.has(row.doctype)).map(row=>`<button class="btn btn-default cfg-qc-link" data-link="${d.links.indexOf(row)}"${disabled}>${escape(row.label)} · ${escape(row.name)} · ${tr(row.docstatus===0?'Draft':row.docstatus===1?'Submitted':row.docstatus===2?'Cancelled':'Record')}</button>`).join('')}</div><small>${tr('Actions open the existing authorized workflows. Opening this page never receives stock, completes QC or creates credit.')}</small></section>`;
 }
 async function handoff(env){
  const request=env.request;
  if(!request||typeof request.name!=='string'||typeof request.operator!=='string')throw new Error('Select a return from Customer Return QC.');
  await env.sync();const token=env.token();
  if(!token||env.operator()?.employee!==request.operator)throw new Error('Identify the same QC operator before opening this return.');
  const current=()=>env.active()&&env.token()===token&&env.operator()?.employee===request.operator;
  const data=await env.read(request.name,token);
  if(!current())return false;
  if(data.actor!==request.operator)throw new Error('QC operator changed. Return to the worklist and identify the current operator.');
  if(data.name!==request.name)throw new Error('Return Case identity changed. Refresh Customer Return QC.');
  await env.open(data.name);return current();
 }
 function mount(wrapper){
  const f=root.frappe,page=f.ui.make_app_page({parent:wrapper,title:tr('Customer Return QC'),single_column:true}),host=$('<div class="cfg-return-qc"></div>').appendTo(page.main);
  host.html(`<section class="frappe-card p-3"><div class="cfg-qc-identity"></div><div class="cfg-qc-login cfg-qc-actions"><input class="form-control cfg-qc-credential" autocomplete="off" placeholder="${tr('QC operator credential')}"><input class="form-control cfg-qc-pin" type="password" placeholder="${tr('PIN if required')}"><button class="btn btn-primary cfg-qc-login-button">${tr('Sign in')}</button></div><div class="cfg-qc-actions"><input class="form-control cfg-qc-scan" autocomplete="off" placeholder="${tr('Scan Temporary Return Note / case number or command')}"><button class="btn btn-default cfg-qc-camera">${tr('Scan with Camera')}</button><button class="btn btn-default cfg-qc-change">${tr('Change Operator')}</button><button class="btn btn-default cfg-qc-refresh">${tr('Refresh')}</button><button class="btn btn-default cfg-qc-clear-case">${tr('Clear Selected Case')}</button></div><p>${tr('Customer Return QC responsibility is required. All cases and counts respect the terminal user’s native Company/record permissions.')}</p><p class="cfg-qc-notice" role="status"></p><small class="cfg-qc-freshness"></small><div class="cfg-qc-filters"></div><div class="cfg-qc-actions"><button class="btn btn-primary cfg-qc-apply">${tr('Apply Filters')}</button><button class="btn btn-default cfg-qc-clear">${tr('Clear Filters')}</button><button class="btn btn-default cfg-qc-help">${tr('Scanner Help')}</button></div></section><section class="frappe-card p-3 mt-3 cfg-qc-summary"></section><section class="frappe-card p-3 mt-3 cfg-qc-list"></section><div class="cfg-qc-actions mt-3"><button class="btn btn-default cfg-qc-prev">${tr('Previous')}</button><span class="cfg-qc-range"></span><button class="btn btn-default cfg-qc-next">${tr('Next')}</button></div><div class="cfg-qc-detail-host mt-3"></div>`);
  const active=()=>app.state.active&&f.get_route()?.[0]==='kanban-return-qc',storage=root.localStorage;
  let timer=null,camera=null,cameraEpoch=0,identity=null,noticeText='',controls={};
  const notice=text=>{noticeText=text||'';host.find('.cfg-qc-notice').text(noticeText);};
  const rpc=async(method,args)=>(await f.call({method,args})).message;
  const focus=()=>{if(active())host.find(app.state.token?'.cfg-qc-scan':'.cfg-qc-credential').trigger('focus');};
  function stopCamera(){cameraEpoch++;camera?.stop_scan?.();camera?.dialog?.hide?.();camera=null;}
  const app=controller({storage,rpc,notify:notice,record:(dt,name)=>f.set_route('Form',dt,name),inspect:request=>{f.route_options={cfg_qc_return_case:request};f.set_route('kanban-logistics');},render:s=>{
   const identityKey=`${s.token}:${s.reset_revision}`;if(identity!==identityKey){identity=identityKey;stopCamera();for(const [key,c] of Object.entries(controls))c.set_value(s.filters[key]||'');}
   host.find('.cfg-qc-identity').text(s.operator?`${s.operator.employee_name||s.operator.employee} · ${s.operator.kanban_role}`:tr('QC operator required'));
   host.find('.cfg-qc-login').toggle(!s.token);host.find('.cfg-qc-summary').html(summaryHTML(s));host.find('.cfg-qc-list').html(listHTML(s));host.find('.cfg-qc-detail-host').html(detailHTML(s));
   host.find('.cfg-qc-prev').prop('disabled',s.busy||s.start===0||!s.operator);host.find('.cfg-qc-next').prop('disabled',s.busy||!s.has_more||!s.operator);
   host.find('.cfg-qc-apply,.cfg-qc-clear').prop('disabled',s.busy||!s.operator);
   host.find('.cfg-qc-freshness').text(s.refreshed_on?`${s.stale?tr('Stale cached information')+' · ':''}${tr('Last refreshed')}: ${s.refreshed_on}`:'');
   host.find('.cfg-qc-range').text(s.operator?s.rows.length?`${s.start+1}–${s.start+s.rows.length} / ${s.total}`:`0 / ${s.total}`:'');
   host.find('.cfg-qc-notice').text(s.error||(s.busy?tr('Refreshing…'):s.stale?tr('Cached information is stale. Refresh before opening an action.'):noticeText));
   const options=['',...s.states].join('\n');if(controls.state&&controls.state.df.options!==options){const value=controls.state.get_value();controls.state.df.options=options;controls.state.refresh();controls.state.set_value(value||'');}
  }});
  const fields=[['view','Select','Worklist',['Needs Follow-up','All Returns','Closed / Cancelled']],['company','Link','Company','Company'],['customer','Link','Customer','Customer'],['location','Link','Inspection Location','Location'],['trip','Link','Original Driver Trip','CFG Kanban Delivery Trip'],['custody_trip','Link','Current Custody Trip','CFG Kanban Delivery Trip'],['state','Select','Case State',['']],['flow','Select','Workflow',['','Customer Return for QC','Delivery Note Correction']],['from_date','Date','Intake From'],['to_date','Date','Intake To'],['search','Data','Case / Customer / Source Search'],['sort','Select','Order',['Oldest intake first','Recently updated']]];
  for(const [name,type,label,options] of fields){const c=f.ui.form.make_control({parent:host.find('.cfg-qc-filters'),df:{fieldname:name,fieldtype:type,label:tr(label),options:Array.isArray(options)?options.join('\n'):options},render_input:true});controls[name]=c;}
  controls.view.set_value('Needs Follow-up');controls.sort.set_value('Oldest intake first');
  async function run(work){try{return await work();}catch(error){notice(message(error));}finally{focus();}}
  function apply(){const values=Object.fromEntries(Object.entries(controls).map(([key,c])=>[key,c.get_value()||'']));return app.settings(values);}
  async function submit(value){
   const text=String(value??(host.find('.cfg-qc-scan').val()||'')).trim();host.find('.cfg-qc-scan').val('');if(!text)return;
   const command=text.toUpperCase();
   if(command==='CFG:CMD:VIEW_RETURN_QC_MONITOR')return app.refresh(null,true);
   if(command==='CFG:CMD:REFRESH')return app.refresh(app.state.selected,true);
   if(command==='CFG:CMD:CANCEL')return app.refresh(null,true);
   if(command==='CFG:CMD:NEXT_MATERIALS')return app.page(1);
   if(command==='CFG:CMD:PREVIOUS_MATERIALS')return app.page(-1);
   if(command==='CFG:CMD:QC_INSPECT_RETURN')return app.inspect();
   if(command==='CFG:CMD:RETURN_CASE_RECORD')return app.record();
   if(command==='CFG:CMD:HELP'){notice(tr('Scan a case number/QR or numbered CFG:SELECT:1–10. NEXT_MATERIALS / PREVIOUS_MATERIALS page the worklist. QC_INSPECT_RETURN opens the existing inspection workflow; RETURN_CASE_RECORD opens its normal form. REFRESH updates; CANCEL clears selection. All action commands use CFG:CMD:.'));return;}
   const choice=command.match(/^CFG:SELECT:(10|[1-9])$/);if(choice){const row=app.state.rows[Number(choice[1])-1];if(row)return app.select(row.name);notice(tr('Select a visible numbered return case.'));return;}
   return app.scan(text,host.find('.cfg-qc-pin').val());
  }
  async function login(value){stopCamera();try{return await app.identify(value??host.find('.cfg-qc-credential').val(),host.find('.cfg-qc-pin').val());}finally{host.find('.cfg-qc-credential,.cfg-qc-pin').val('');}}
  host.on('click.cfg_return_qc','.cfg-qc-login-button',()=>run(()=>login()))
   .on('keydown.cfg_return_qc','.cfg-qc-credential',event=>{if(['Enter','Tab'].includes(event.key)&&!event.shiftKey&&!event.ctrlKey&&!event.altKey&&!event.metaKey&&!event.isComposing&&host.find('.cfg-qc-credential').val()){event.preventDefault();event.stopPropagation();run(()=>login());}})
   .on('keydown.cfg_return_qc','.cfg-qc-scan',event=>{if(['Enter','Tab'].includes(event.key)&&!event.shiftKey&&!event.ctrlKey&&!event.altKey&&!event.metaKey&&!event.isComposing&&host.find('.cfg-qc-scan').val()){event.preventDefault();event.stopPropagation();run(()=>submit());}})
   .on('click.cfg_return_qc','.cfg-qc-select',event=>run(()=>app.select($(event.currentTarget).attr('data-case'))))
   .on('click.cfg_return_qc','.cfg-qc-inspect',()=>run(()=>app.inspect())).on('click.cfg_return_qc','.cfg-qc-record',()=>run(()=>app.record()))
   .on('click.cfg_return_qc','.cfg-qc-link',event=>run(()=>app.linked(Number($(event.currentTarget).attr('data-link')))))
   .on('click.cfg_return_qc','.cfg-qc-refresh',()=>run(()=>app.refresh(app.state.selected,true)))
   .on('click.cfg_return_qc','.cfg-qc-clear-case',()=>run(()=>app.refresh(null,true)))
   .on('click.cfg_return_qc','.cfg-qc-prev',()=>run(()=>app.page(-1))).on('click.cfg_return_qc','.cfg-qc-next',()=>run(()=>app.page(1)))
   .on('click.cfg_return_qc','.cfg-qc-change',()=>{stopCamera();notice('');app.changeOperator();focus();})
   .on('click.cfg_return_qc','.cfg-qc-apply',()=>run(apply)).on('click.cfg_return_qc','.cfg-qc-clear',()=>run(()=>{for(const c of Object.values(controls))c.set_value('');controls.view.set_value('Needs Follow-up');controls.sort.set_value('Oldest intake first');return app.settings(defaults());}))
   .on('click.cfg_return_qc','.cfg-qc-help',()=>run(()=>submit('CFG:CMD:HELP')))
   .on('click.cfg_return_qc','.cfg-qc-camera',()=>{stopCamera();if(!f.ui.Scanner){notice(tr('Camera is unavailable; use the scanner field.'));focus();return;}const token=app.session(),version=cameraEpoch;let accepted=false;
    try{camera=new f.ui.Scanner({dialog:true,multiple:false,on_scan:data=>{if(accepted||version!==cameraEpoch||!active()||app.session()!==token)return;accepted=true;stopCamera();run(()=>submit(data.decodedText));}});camera.dialog?.$wrapper?.one?.('hidden.bs.modal.cfg_return_qc',()=>{stopCamera();focus();});}catch(error){notice(message(error));focus();}});
  function tick(){if(active()&&!root.document.hidden&&!app.state.busy)app.refresh(app.state.selected,false);}
  root.addEventListener('storage',event=>{if(event.key===SESSION&&active()){stopCamera();notice('');app.refresh(null,false);}});
  root.document.addEventListener('visibilitychange',()=>{if(root.document.hidden)stopCamera();else tick();});
  const life={async show(name){notice('');if(!timer)timer=root.setInterval(tick,15000);await app.show(name);for(const [key,c] of Object.entries(controls))c.set_value(app.state.filters[key]||'');focus();},hide(){stopCamera();app.hide();notice('');if(timer)root.clearInterval(timer);timer=null;},app};
  f.router?.on?.('change',()=>{if(f.get_route()?.[0]!=='kanban-return-qc')life.hide();});return life;
 }
 const api={controller,scan,message,age,summaryHTML,listHTML,detailHTML,handoff,mount};
 if(typeof module!=='undefined'&&module.exports)module.exports=api;root.cfg_return_qc=api;
})(typeof window==='undefined'?globalThis:window);
