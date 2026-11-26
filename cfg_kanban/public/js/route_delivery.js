/* Open Route customer visits, supervision and stock allocation; one scanner/touch controller. */
(function(root){
 'use strict';
 const pendingKey='cfg_kanban_route_action_pending_v1',lockKey='cfg_kanban_route_action_v1';
 const methods={visit:'start_route_stop',plan:'add_route_stop',approve:'approve_route_stop_order',skip:'skip_route_stop',stock:'allocate_route_stock'};
 function createController(env){
  const s={mode:env.mode||'visit',plans:[],plan:null,stops:[],stop:null,choices:[],choice:null,choosing:'',page:0,
   deliverySession:env.deliverySession,customerScan:'',customerSite:'',scanValue:'',item:'',batch:'',qty:0,reason:'',arm:'',loading:false,busy:false,
   closed:false,completed:false,pending:null,cancelPending:false,pendingReason:'',message:'Scan the Open Route Plan or Customer Site.'};
  const changed=()=>env.render(s),fail=msg=>{throw new Error(msg);};
  const editable=()=>{if(s.pending)fail('Retry the original pending route action before changing it.');if(env.owner()!==env.openedOwner)fail('Identify the original operator before continuing.');};
  function readPending(){
   const value=env.storage.getItem(pendingKey);if(!value)return null;
   let row;try{row=JSON.parse(value);}catch(_){fail('Pending route data is unreadable. Reconcile this terminal before another action.');}
   if(!row?.args?.event_token||!row.owner||methods[row.mode]!==row.method||
      (row.mode==='stock'&&(!row.args.delivery_session||!row.args.source_key||!Number.isFinite(Number(row.args.qty))))||
      (['visit','plan'].includes(row.mode)&&(!row.args.dispatch_plan||!row.args.customer_scan))||
      (['approve','skip'].includes(row.mode)&&(!row.args.route_stop||!row.args.reason)))fail('Pending route data is incomplete; reconcile this terminal.');
   return row;
  }
  function restore(){
   const row=readPending();if(!row)return false;
   s.pending=row;s.mode=row.mode;s.deliverySession=row.args.delivery_session||s.deliverySession;s.message='An earlier route action has no acknowledged result. Confirm retries that original action; Cancel closes without discarding it.';changed();return true;
  }
  function stopChoices(){
   s.stop=null;s.page=0;
   if(!s.plan){s.stops=[];s.choosing='';return;}
   if(s.mode==='plan'){s.stops=[];s.choosing='';return;}
   const planning=['approve','skip'].includes(s.mode);
   s.stops=(s.plan.stops||[]).filter(row=>planning?row.state==='Planned':
    row.customer_scan_point===s.customerSite&&(row.state==='Planned'||row.name===s.plan.active_route_stop));
   const active=s.stops.find(row=>row.name===s.plan.active_route_stop);
   if(active&&!planning){s.stop=active;s.choosing='';}
   else if(s.stops.length===1){s.stop=s.stops[0];s.choosing='';}
   else s.choosing=s.stops.length>1?'stop':'';
   if(planning&&s.stop)s.arm='reason';
  }
  async function context(value){
   editable();s.customerScan='';s.customerSite='';s.stop=null;s.stops=[];s.loading=true;s.message='Checking eligible route work...';changed();
   try{
    const result=await env.rpc('route_context',{scan_value:value,dispatch_plan:s.plan?.name||null,operator_session_token:env.token()});
    if(s.closed)return;
    if(env.owner()!==env.openedOwner)fail('Operator changed. Close and identify the intended operator.');
    if(result.customer_scan&&s.plan){
     const plan=result.plans.find(row=>row.name===s.plan.name);if(!plan)fail('This Customer Site is outside the selected route.');
     s.plan=plan;s.customerScan=result.customer_scan;s.customerSite=result.customer_site||'';
    }else{
     s.plans=result.plans||[];s.plan=s.plans.length===1?s.plans[0]:null;s.page=0;
     s.customerScan=result.customer_scan||'';s.customerSite=result.customer_site||'';s.choosing=s.plans.length>1?'plan':'';
    }
    if(s.plan)stopChoices();
    s.message=s.choosing==='plan'?'Select the exact numbered Open Route Plan.':s.choosing==='stop'?'Select the exact numbered visit.':
     ['approve','skip'].includes(s.mode)?'Select the planned Stop and enter a Supervisor reason.':
     !s.customerScan?'Scan the physical Customer Site.':'Review the Customer Site and Stop, then Confirm.';
   }finally{s.loading=false;changed();}
  }
  function select(n){
   editable();const values=s.choosing==='plan'?s.plans:s.choosing==='stop'?s.stops:s.choices;
   const row=values[s.page*10+n-1];if(!row){s.choice=null;s.stop=null;if(s.mode!=='stock'){s.customerScan='';s.customerSite='';}changed();fail('Select one of the displayed numbered choices.');}
   if(s.choosing==='plan'){s.plan=row;stopChoices();}
   else if(s.choosing==='stop'){s.stop=row;s.choosing='';if(['approve','skip'].includes(s.mode))s.arm='reason';}
   else{s.choice=row;s.qty=row.contents?0:row.full_quantity_only?Number(row.physical_qty||row.available_qty):0;s.choosing='';}
   changed();
  }
  async function stock(values){
   editable();s.choice=null;s.choices=[];s.qty=0;s.page=0;s.loading=true;s.message='Checking source stock...';changed();
   s.scanValue=values.scan_value||'';s.item=values.item_code||'';s.batch=values.batch_no||'';
   try{
    const result=await env.rpc('route_stock_context',{delivery_session:s.deliverySession,operator_session_token:env.token(),
     scan_value:s.scanValue||null,item_code:s.item||null,batch_no:s.batch||null});
    if(s.closed)return;
    if(env.owner()!==env.openedOwner)fail('Operator changed. Close and identify the intended operator.');
    s.choices=result.choices||[];s.item=result.item_code||s.item;s.batch=result.batch_no||s.batch;
    if(result.requires_batch){s.arm='batch';s.message='Scan or select the exact Batch for this Item.';}
    else if(s.choices.length===1){s.choosing='stock';select(1);s.message='Set the quantity and confirm the stock source.';}
    else{s.choosing=s.choices.length>1?'stock':'';s.message=s.choices.length?'Choose the exact Stock Tag, prepared route stock or unassigned lorry stock.':'No eligible stock is available for this source.';}
    if(result.untagged_requires_batch)s.message+=' Tagged sources retain their Batch; select an exact Batch to find untagged stock.';
    if(result.tagged_only)s.message+=' Serialized Items require a complete tagged unit.';
    if(result.unavailable_tags?.length)s.message+=' Other loaded tags: '+result.unavailable_tags.map(row=>row.visible_code+' — '+row.reason).join('; ');
   }finally{s.loading=false;changed();}
  }
  function quantity(value){editable();if(s.mode!=='stock')fail('Quantity applies to Route Stock allocation.');const n=Number(value);if(!Number.isFinite(n)||n<=0){s.qty=0;changed();fail('Stock quantity must be positive.');}s.qty=n;changed();}
  function reason(value){if(s.pending&&s.cancelPending){s.pendingReason=String(value||'').trim();s.arm='';changed();return;}editable();s.reason=String(value||'').trim();s.arm='';changed();}
  function ready(){
   if(s.pending)return !s.pending.invalid&&s.pending.owner===env.owner()&&(!s.cancelPending||!!s.pendingReason);if(s.loading||s.choosing)return false;
   if(s.mode==='stock')return !!s.choice&&(s.choice.contents||s.qty>0&&s.qty<=Number(s.choice.available_qty));
   if(!s.plan||s.plan.dispatch_review_state)return false;
   if(['approve','skip'].includes(s.mode))return !!s.stop&&!!s.reason&&(s.mode!=='approve'||!!s.plan.can_approve_order);
   if(!s.customerScan)return false;
   if(s.mode==='plan')return !!s.plan.can_plan_stops;
   if(s.plan.active_route_stop&&(s.stop?.name!==s.plan.active_route_stop||s.plan.can_resume_stop===false))return false;
   const next=(s.plan.stops||[]).filter(row=>row.state==='Planned'&&Number(row.planned_sequence)>0).sort((a,b)=>Number(a.planned_sequence)-Number(b.planned_sequence))[0];
   if(s.plan.stop_sequence_policy==='Planned Order'&&next&&s.stop?.name!==next.name&&!s.stop?.override_approved_by)return false;
   return (s.plan.state==='Loaded'||s.plan.existing_lorry_stock_only&&s.plan.state==='Ready for Fulfilment')&&(s.plan.stop_sequence_policy!=='Planned Order'||!!s.stop);
  }
  function request(){
   if(!ready())fail('Complete the route, Customer Site, numbered choice, quantity or reason shown above.');
   const args={event_token:env.nonce(),operator_session_token:env.token()};
   if(s.mode==='stock')Object.assign(args,{delivery_session:s.deliverySession,source_key:s.choice.source_key,qty:s.choice.contents?0:s.qty,
       scan_value:s.scanValue||null,item_code:s.item||null,batch_no:s.batch||null});
   else if(['approve','skip'].includes(s.mode))Object.assign(args,{route_stop:s.stop.name,reason:s.reason});
   else Object.assign(args,{dispatch_plan:s.plan.name,customer_scan:s.customerScan,...(s.mode==='visit'?{route_stop:s.stop?.name||null}:{})});
   return {mode:s.mode,method:methods[s.mode],owner:env.owner(),args};
  }
  async function confirm(){
   if(s.closed||s.completed||s.busy)return;
   if(!env.locks?.request)fail('This route action requires an HTTPS browser with Web Locks.');
   s.busy=true;changed();
   try{return await env.locks.request(lockKey,async()=>{
    if(s.closed||s.completed)return;
    const stored=readPending();
    if(stored&&(!s.pending||stored.args.event_token!==s.pending.args.event_token))fail('Another route action is awaiting reconciliation. Close and reopen to retry it.');
    if(!stored&&s.pending)fail('The pending route action was reconciled in another tab. Close and reopen.');
    const row=stored||request();
    if(row.owner!==env.owner()||row.owner!==env.openedOwner)fail('The original operator must reconcile this route action.');
    env.storage.setItem(pendingKey,JSON.stringify(row));s.pending=row;changed();
    let result;
    if(s.cancelPending){
     if(!s.pendingReason)fail('Enter the reason for cancelling the unrecorded action.');
     const outcome=await env.rpc('void_unrecorded_route_action',{action:row.mode,event_token:row.args.event_token,
      delivery_session:row.args.delivery_session,dispatch_plan:row.args.dispatch_plan,route_stop:row.args.route_stop,
      reason:s.pendingReason,operator_session_token:env.token()});
     return acceptOutcome(outcome,row);
    }
    try{result=await env.rpc(row.method,{...row.args,operator_session_token:env.token()});}
    catch(error){
     const type=error?.exc_type||error?.responseJSON?.exc_type;
     if(type==='RouteActionVoidedError'||(type&&!stored&&!['RouteReplayConflictError','DuplicateEntryError'].includes(type))){env.storage.removeItem(pendingKey);s.pending=null;}
     throw error;
    }
    env.storage.removeItem(pendingKey);s.pending=null;s.completed=true;
    if(env.owner()!==row.owner){s.plan=null;s.plans=[];s.choices=[];s.choice=null;s.customerScan='';s.customerSite='';s.reason='';s.message='The action was recorded for the original operator. Close and identify that operator to resume.';changed();return;}
    s.closed=true;env.close();await env.success(result,row.mode,row.args);return result;
   });}finally{s.busy=false;changed();}
  }
  async function acceptOutcome(outcome,row){
   if(!outcome.recorded&&!outcome.voided){s.message='No recorded result was found. Retry the original Confirm, or cancel the unrecorded action with a reason.';changed();return;}
   env.storage.removeItem(pendingKey);s.pending=null;s.completed=true;s.closed=true;env.close();
   if(env.owner()===row.owner)await env.success(outcome.result||{dispatch_plan:outcome.dispatch_plan},outcome.recorded?row.mode:'void',row.args);
  }
  async function reconcile(){
   if(s.closed||s.busy)return;if(!env.locks?.request)fail('This route action requires Web Locks.');s.busy=true;changed();
   try{return await env.locks.request(lockKey,async()=>{
    const row=readPending();if(!row||!s.pending||row.args.event_token!==s.pending.args.event_token)fail('Reopen the original pending route action.');
    if(row.owner!==env.owner()||row.owner!==env.openedOwner)fail('The original operator must reconcile this route action.');
    const result=await env.rpc('reconcile_route_action',{action:row.mode,event_token:row.args.event_token,
     delivery_session:row.args.delivery_session,dispatch_plan:row.args.dispatch_plan,route_stop:row.args.route_stop,
     operator_session_token:env.token()});return acceptOutcome(result,row);
   });}finally{s.busy=false;changed();}
  }
  async function scan(raw){
   const value=String(raw||'').trim(),upper=value.toUpperCase();if(!value||s.closed)return;
   if(upper==='CFG:CMD:CANCEL'){s.closed=true;env.close();return;}
   if(upper==='CFG:CMD:CONFIRM')return confirm();
   if(upper==='CFG:CMD:ROUTE_CAMERA')return env.camera();
   if(upper==='CFG:CMD:ROUTE_RECONCILE')return reconcile();
   if(upper==='CFG:CMD:ROUTE_VOID_PENDING'){if(!s.pending||s.pending.invalid)fail('Open a valid original pending action first.');s.cancelPending=true;s.arm='reason';s.message='Cancel only if unrecorded: enter a reason, then Confirm. A recorded action will be reopened instead.';changed();return;}
   if(s.pending&&s.cancelPending&&(!upper.startsWith('CFG:')||upper==='CFG:CMD:ROUTE_REASON')){if(upper==='CFG:CMD:ROUTE_REASON'){s.arm='reason';return;}return reason(value);}
   if(upper==='CFG:CMD:HELP'){s.message='Scan the Plan and Customer Site, select numbered choices and Confirm. Stock: scan a tag/container or select Product to list eligible loaded Stock Tags and untagged stock. Choose an exact tag/source; tags keep their own Batch, while untagged stock needs an exact Batch when required, Material Qty, Confirm. Manager actions need a planned Stop and reason. Cancel preserves uncertain requests.';changed();return;}
   editable();
   if(upper==='CFG:CMD:NEXT_MATERIALS'||upper==='CFG:CMD:PREVIOUS_MATERIALS'){
    const list=s.choosing==='plan'?s.plans:s.choosing==='stop'?s.stops:s.choices;
    s.page=Math.max(0,Math.min(Math.max(Math.ceil(list.length/10)-1,0),s.page+(upper.includes('NEXT_')?1:-1)));changed();return;
   }
   const choice=upper.match(/^CFG:SELECT:(10|[1-9])$/);if(choice)return select(Number(choice[1]));
   const qty=upper.match(/^CFG:QTY:MATERIAL:([+-]?\d+(?:\.\d+)?)$/);
   if(qty){const n=Number(qty[1]);return quantity(/^[+-]/.test(qty[1])?s.qty+n:n);}
   if(upper==='CFG:CMD:ROUTE_REASON'){if(!['approve','skip'].includes(s.mode))fail('Reason applies to a Supervisor Stop action.');s.arm='reason';s.message='Scan the Supervisor reason next.';changed();return;}
   if(upper==='CFG:CMD:ROUTE_ITEM'){if(s.mode!=='stock')fail('Open Route Stock allocation first.');s.arm='item';s.choice=null;s.message='Scan/select the ERP Item next.';changed();return;}
   if(upper==='CFG:CMD:ROUTE_BATCH'){if(s.mode!=='stock')fail('Open Route Stock allocation first.');if(!s.item)fail('Select an ERP Item before its Batch.');s.arm='batch';s.choice=null;changed();return;}
   if(upper==='CFG:CMD:ROUTE_SOURCE'){
    s.plans=[];s.plan=null;s.stops=[];s.stop=null;s.choices=[];s.choice=null;s.choosing='';s.customerScan='';s.customerSite='';s.item='';s.batch='';s.qty=0;s.arm='';
    s.message=s.mode==='stock'?'Scan the next stock source.':'Scan another Plan and Customer Site.';changed();return;
   }
   if(upper.startsWith('CFG:'))fail('Use an Open Route command or scan a physical identity.');
   if(s.arm==='reason')return reason(value);
   if(s.mode==='stock'){
    const arm=s.arm;s.arm='';
    if(arm==='batch')return stock({item_code:s.item,batch_no:value});
    if(arm==='item')return stock({item_code:value});
    return stock({scan_value:value});
   }
   if(['approve','skip'].includes(s.mode)&&s.stop)return reason(value);
   return context(value);
  }
  return {state:s,restore,context,stock,select,quantity,reason,ready,confirm,reconcile,scan};
 }
 async function open(options){
  const f=options.frappe,e=f.utils.escape_html;let controller,dialog,camera=null,tail=Promise.resolve();
  const focus=()=>{if(!controller.state.closed)dialog.fields_dict.scan.$input.focus();};
  function queue(work){tail=tail.then(work).catch(error=>{controller.state.message=options.errorMessage(error,error.message||'Route action failed.');render(controller.state);}).finally(focus);return tail;}
  function stopCamera(){const active=camera;camera=null;active?.hide_dialog?.();}
  function startCamera(){
   if(camera||controller.state.closed)return;if(!f.ui.Scanner)throw new Error('Camera scanning is unavailable; use the Scanner field.');
   let accepted=false;camera=new f.ui.Scanner({dialog:true,multiple:false,on_scan:data=>{
    if(accepted||controller.state.closed)return;accepted=true;const value=String(data.decodedText||'').trim();stopCamera();if(value)queue(()=>controller.scan(value));else focus();
   }});const instance=camera;camera.dialog?.$wrapper?.one('hidden.bs.modal',()=>{accepted=true;if(camera===instance)camera=null;focus();});
  }
  function label(row){
   if(row.contents)return `${row.container_visible_code} · Full container · `+row.contents.map(r=>`${r.item_code}: ${r.physical_qty} ${r.stock_uom}`).join(' / ');
   if(row.source_kind)return `${row.source_kind} · ${row.visible_code||row.item_code} · ${row.batch_no||'No Batch'} · Available ${row.available_qty} ${row.stock_uom}`;
   if(row.customer_scan_point)return `Planned ${row.planned_sequence||'-'} · ${row.site_name||row.customer_scan_point} · ${row.state}${row.override_approved_by?' · Sequence approved':''}`;
   return `${row.name} · ${row.business_label||''} · ${row.vehicle_reference||row.vehicle_warehouse||''} · ${row.stop_sequence_policy||''}`;
  }
  function render(s){
   if(dialog.set_df_property){for(const name of ['item_code','batch_no','qty'])dialog.set_df_property(name,'hidden',s.mode==='stock'?0:1);dialog.set_df_property('reason','hidden',s.cancelPending||['approve','skip'].includes(s.mode)?0:1);dialog.set_df_property('reconcile','hidden',s.pending?0:1);dialog.set_df_property('void_pending','hidden',s.pending?0:1);}
   const rows=s.choosing==='plan'?s.plans:s.choosing==='stop'?s.stops:s.mode==='stock'?s.choices:[];
   const choices=rows.slice(s.page*10,s.page*10+10).map((row,i)=>`<button type="button" class="btn btn-default btn-block text-left route-choice" data-number="${i+1}">${i+1}. ${e(label(row))}</button>`).join('');
   const pending=s.pending&&s.pending.owner!==options.owner()?`<div class="alert alert-warning">${e('Identify original operator '+(s.pending.owner||'')+' to reconcile this action.')}</div>`:s.pending?`<div class="alert alert-warning">${e(s.pending.mode)} · ${e(s.pending.args.dispatch_plan||s.pending.args.delivery_session||s.pending.args.route_stop||'')} · ${e(s.pending.args.scan_value||s.pending.args.customer_scan||s.pending.args.item_code||'')} · ${e(String(s.pending.args.qty??''))} · ${e(s.pending.args.reason||'')}</div>`:'';
   const summary=[s.plan?.name,s.customerScan,s.stop?.site_name,s.choice?label(s.choice):'',s.mode==='stock'?`Quantity: ${s.qty}`:'',s.cancelPending?s.pendingReason:s.reason].filter(Boolean).map(value=>e(String(value))).join('<br>');
   dialog.fields_dict.review.$wrapper.html(`${pending}<div class="alert ${controller.ready()?'alert-success':'alert-warning'}">${e(s.message)}</div>${summary?`<p>${summary}</p>`:''}${choices}`);
   dialog.fields_dict.review.$wrapper.find('.route-choice').on('click',function(){queue(()=>controller.select(Number(this.dataset.number)));});
   if(controller.ready()&&!s.busy&&!s.loading&&!s.completed)dialog.enable_primary_action();else dialog.disable_primary_action();
  }
  dialog=new f.ui.Dialog({title:'Open Route Delivery',size:'large',fields:[
   {fieldname:'scan',label:'Scanner',fieldtype:'Data'},
   {fieldname:'camera',label:'Scan with Camera',fieldtype:'Button',click:()=>queue(()=>startCamera())},
   {fieldname:'review',fieldtype:'HTML'},
   {fieldname:'reconcile',label:'Re-read Pending Action',fieldtype:'Button',hidden:1,click:()=>queue(()=>controller.reconcile())},
   {fieldname:'void_pending',label:'Cancel If Unrecorded',fieldtype:'Button',hidden:1,click:()=>queue(()=>controller.scan('CFG:CMD:ROUTE_VOID_PENDING'))},
   {fieldname:'item_code',label:'Product — Stock Tags or Untagged Stock',fieldtype:'Link',options:'Item',hidden:options.mode==='stock'?0:1,
    onchange:()=>{const value=dialog?.get_value('item_code');if(controller&&value)queue(()=>controller.stock({item_code:value}));}},
   {fieldname:'batch_no',label:'Exact Batch',fieldtype:'Link',options:'Batch',hidden:options.mode==='stock'?0:1,
    onchange:()=>{const value=dialog?.get_value('batch_no');if(controller&&controller.state.item&&value)queue(()=>controller.stock({item_code:controller.state.item,batch_no:value}));}},
   {fieldname:'qty',label:'Stock Quantity',fieldtype:'Float',hidden:options.mode==='stock'?0:1,
    onchange:()=>{const value=dialog?.get_value('qty');if(controller&&value!==undefined&&value!==null)queue(()=>controller.quantity(value));}},
   {fieldname:'reason',label:'Supervisor Reason',fieldtype:'Small Text',hidden:['approve','skip'].includes(options.mode)?0:1,
    onchange:()=>{if(controller)queue(()=>controller.reason(dialog.get_value('reason')));}},
  ],primary_action_label:'Confirm Route Action',primary_action:()=>queue(()=>controller.confirm())});
  controller=createController({mode:options.mode,deliverySession:options.deliverySession,owner:options.owner,openedOwner:options.owner(),
   token:options.token,nonce:options.nonce,storage:localStorage,locks:navigator.locks,render,camera:startCamera,
   rpc:async(method,args)=>(await f.call({method:'cfg_kanban.services.route_delivery.'+method,args})).message,
   success:options.success,close:()=>dialog.hide()});
  dialog.onhide=()=>{controller.state.closed=true;stopCamera();options.onClose();};
  dialog.fields_dict.scan.$input.on('keydown',event=>{
   if(!['Tab','Enter'].includes(event.key)||event.shiftKey||event.ctrlKey||event.altKey||event.metaKey||event.isComposing)return;
   const value=String(dialog.get_value('scan')||'').trim();if(event.key==='Tab'&&!value)return;
   event.preventDefault();event.stopPropagation();dialog.set_value('scan','');if(value)queue(()=>controller.scan(value));
  });
  dialog.show();let restored=false;
  try{restored=controller.restore();}catch(error){controller.state.message=error.message;controller.state.pending={invalid:true,args:{},mode:'unreadable'};}
  render(controller.state);focus();
  if(!restored&&!controller.state.pending){
   if(options.planScan)await queue(()=>controller.context(options.planScan));
   if(options.siteScan)await queue(()=>controller.context(options.siteScan));
  }
  return controller.state.closed?null:{scan:value=>queue(()=>controller.scan(value)),focus,controller,close:()=>dialog.hide()};
 }
 const api={createController,open,pendingKey,lockKey};if(typeof module!=='undefined'&&module.exports)module.exports=api;
 root.cfg_route_delivery=api;
})(typeof window==='undefined'?globalThis:window);
