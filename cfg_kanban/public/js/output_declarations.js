/* Station bundles are pending declarations; ERP submission activates their stock. */
(function(root){
 "use strict";
 const key="cfg_kanban_pending_output_declaration_v1",lock="cfg_kanban_output_declaration_submit_v1";
 function createController(env){
  const s={station:null,choice:null,page:0,qty:0,tag:"",bin:"",notes:"Operator bundled reported final output",arm:"",mode:"pack",cancel:null,pending:null,busy:false,done:false,closed:false,message:""};
  const changed=()=>env.render(s),fail=message=>{throw new Error(message);};
  function physicalOrText(value){if(/^[a-z]+:\/\//i.test(String(value))&&/[#?&]operator=/i.test(String(value)))fail("Cancel this dialog before switching operators.");return value;}
  function editable(){if(s.pending||s.busy||s.done||s.closed)fail("Reconcile the original confirmation before changing the declaration.");}
  function saved(){const raw=env.storage.getItem(key);if(!raw)return null;let row;try{row=JSON.parse(raw);}catch(_){fail("Pending declaration data is unreadable. Reconcile this terminal before another declaration.");}if(!row?.args?.event_token||!row.owner||!row.method)fail("Pending declaration data is incomplete. Reconcile this terminal.");return row;}
  function rows(){return s.mode==="cancel"?(s.choice?.declarations||[]).filter(row=>["Declared","Bound to Draft"].includes(row.status)&&row.workstation===s.station.workstation):(s.station?.choices||[]);}
  async function station(value){editable();physicalOrText(value);s.station=await env.rpc("station_output_context",{station_scan:value});s.choice=null;s.page=0;s.qty=0;s.tag="";s.bin="";s.mode="pack";if(s.station.choices.length===1)choose(1);changed();}
  function choose(number){editable();const row=rows()[s.page*10+number-1];if(!row||number<1||number>10)fail("Select a displayed numbered choice from 1 to 10.");if(s.mode==="cancel")s.cancel=row;else{s.choice=row;s.qty=0;s.tag="";s.bin="";}changed();}
  function quantity(value,add=false){editable();value=Number(value);if(!Number.isFinite(value)||value<=0)fail("Enter a finite positive quantity.");s.qty=add?s.qty+value:value;changed();}
  function notes(value){editable();physicalOrText(value);s.notes=String(value||"").trim();changed();}
  async function identity(value,kind){editable();physicalOrText(value);if(!s.choice)fail("Select the exact Work Order before scanning an output tag/bin.");const result=await env.rpc("classify_output_identity",{station_scan:s.station.station_scan,work_order:s.choice.work_order,scan_value:value});if(kind&&kind!==result.kind)fail("This identity is not the requested output tag/bin type.");if(result.kind==="bin")s.bin=result.code;else s.tag=result.code;changed();}
  function cancelMode(){editable();if(!s.choice)fail("Select the Work Order first.");s.mode="cancel";s.cancel=null;s.page=0;s.notes="";changed();}
  function packMode(){editable();s.mode="pack";s.cancel=null;s.page=0;s.notes="Operator bundled reported final output";changed();}
  function request(){
   if(!s.station||!s.choice)fail("Scan the station and select the exact Work Order.");
   if(s.mode==="cancel"){if(!s.cancel||!s.notes)fail("Select the exact declaration and scan/enter a cancellation reason.");return {method:"cancel_declaration",args:{declaration_name:s.cancel.name,reason:s.notes,event_token:env.nonce()}};}
   if(!Number.isFinite(s.qty)||s.qty<=0||s.qty>Number(s.choice.available_qty)+0.000001||(!s.tag&&!s.bin))fail("Use available reported good quantity and scan a new tag, an empty output bin, or both.");
   return {method:"declare_output",args:{station_scan:s.station.station_scan,work_order:s.choice.work_order,qty:s.qty,tag_code:s.tag||null,container_code:s.bin||null,notes:s.notes,event_token:env.nonce()}};
  }
  async function confirm(){
   if(s.busy||s.done||s.closed)return;if(!env.locks?.request)fail("Use HTTPS and a browser with Web Locks support.");s.busy=true;changed();
   try{return await env.locks.request(lock,async()=>{
    if(s.closed||s.done)return;const stored=saved();
    if(stored&&(!s.pending||stored.args.event_token!==s.pending.args.event_token)){s.pending=stored;changed();fail("Another output action is pending. Reopen and reconcile that original action first.");}
    if(stored&&stored.owner!==env.owner())fail("The original operator must reconcile this terminal's pending output action.");
    if(!stored&&s.pending)fail("This output action was reconciled in another tab. Close and reopen.");
    const pending=stored||{owner:env.owner(),...request()};if(!pending.owner)fail("Identify an operator first.");
    env.storage.setItem(key,JSON.stringify(pending));s.pending=pending;changed();
    let result;try{result=await env.rpc(pending.method,pending.args);}catch(error){if(error?.exc_type||error?.responseJSON?.exc_type){env.storage.removeItem(key);s.pending=null;}throw error;}
    env.storage.removeItem(key);s.pending=null;s.done=true;changed();await env.success(result);return result;
   });}finally{s.busy=false;changed();}
  }
  async function scan(raw){
   const value=String(raw||"").trim(),upper=value.toUpperCase();if(!value)return;
   if(upper==="CFG:CMD:CANCEL"){if(!s.busy){s.closed=true;env.close();}return;}if(upper==="CFG:CMD:CONFIRM")return confirm();editable();
   if(upper==="CFG:CMD:CANCEL_OUTPUT_DECLARATION")return cancelMode();if(upper==="CFG:CMD:PACK_FINISHED_OUTPUT")return packMode();
   const arms={"CFG:CMD:OUTPUT_STATION":"station","CFG:CMD:OUTPUT_TAG":"tag","CFG:CMD:OUTPUT_BIN":"bin","CFG:CMD:OUTPUT_REASON":"reason"};if(arms[upper]){s.arm=arms[upper];changed();return;}
   if(upper==="CFG:CMD:NEXT_MATERIALS"||upper==="CFG:CMD:PREVIOUS_MATERIALS"){s.page=Math.max(0,Math.min(Math.ceil(rows().length/10)-1,s.page+(upper==="CFG:CMD:NEXT_MATERIALS"?1:-1)));changed();return;}
   const selection=/^CFG:SELECT:(10|[1-9])$/.exec(upper);if(selection)return choose(Number(selection[1]));
   const qty=/^CFG:QTY:GOOD:(\+?)(\d+(?:\.\d+)?)$/.exec(upper);if(qty)return quantity(qty[2],!!qty[1]);
   if(upper.startsWith("CFG:"))fail("Use an output declaration command or a physical station/tag/bin label.");
   physicalOrText(value);const arm=s.arm;s.arm="";if(!s.station||arm==="station")return station(value);if(arm==="reason"||s.mode==="cancel")return notes(value);return identity(value,arm||null);
  }
  function restore(){s.pending=saved();changed();return s.pending;}
  return {state:s,rows,station,choose,quantity,notes,identity,cancelMode,packMode,confirm,scan,restore};
 }
 async function open(options){
  const f=options.frappe,e=f.utils.escape_html;let dialog,c,queue=Promise.resolve();
  function focus(){if(dialog?.$wrapper.is(":visible"))dialog.fields_dict.scan.$input.trigger("focus");}
  const enqueue=action=>{queue=queue.then(action).catch(error=>{const message=f.msg_dialog;if(message&&message!==dialog&&message.$wrapper?.is(":visible")){message.$wrapper.one("hidden.bs.modal.cfg_output_focus",focus);message.hide();}c.state.message=options.errorMessage(error,error.message||"Output confirmation was not acknowledged. Retry its original data.");render(c.state);}).finally(focus);return queue;};
  function render(s){
   if(!dialog)return;
   const choices=c.rows().slice(s.page*10,s.page*10+10).map((row,i)=>`<button type="button" class="btn btn-default output-choice" data-number="${i+1}">${i+1}. ${s.mode==="cancel"?`${e(row.name)} · ${e(row.tag_code||row.container_code)} · ${e(row.qty)} · ${e(row.status)}`:`${e(row.work_order)} · ${e(row.item_code)} · ${e(row.available_qty)} ${e(row.stock_uom)} available`}</button>`).join("<br>");
   const pending=s.pending?`<div class="alert alert-warning">Unacknowledged ${e(s.pending.method)}: ${e(s.pending.args.work_order||s.pending.args.declaration_name)} · ${e(s.pending.args.qty||"")} · ${e(s.pending.args.tag_code||s.pending.args.container_code||"")}. Retry original Confirm. Cancel retains this action across reopen/refresh.</div>`:"";
   const summary=s.choice?`<p><strong>${e(s.choice.work_order)} · ${e(s.choice.item_code)}</strong><br>Station good: ${e(s.choice.station_good_qty)} · Already received: ${e(s.choice.already_received_qty)} · Pending declarations: ${e(s.choice.pending_declared_qty)}<br><strong>Available to bundle: ${e(s.choice.available_qty)} ${e(s.choice.stock_uom)}</strong></p>`:"Scan the station and select the Work Order.";
   dialog.fields_dict.summary.$wrapper.html(`${pending}<p>${e(s.station?.workstation||"Station required")}</p>${summary}${choices}<p>${s.mode==="cancel"?`Cancel declaration: ${e(s.cancel?.name||"Select one")}`:`Bundle: ${e(s.qty)} · Tag: ${e(s.tag||"—")} · Bin: ${e(s.bin||"—")}`}</p><p>${e(s.notes)}</p><p class="text-danger">${e(s.message)}</p>`);
   dialog.fields_dict.summary.$wrapper.find(".output-choice").on("click",function(){enqueue(()=>c.choose(Number(this.dataset.number)));});
   for(const name of ["station","read_station","qty","set_qty","identity","read_identity","reason","set_reason","cancel_declaration","pack_mode"])dialog.set_df_property(name,"read_only",!!(s.pending||s.busy));dialog.get_primary_btn().prop("disabled",s.busy);
  }
  dialog=new f.ui.Dialog({title:"Bundle / Tag Finished Output — Pending ERP",size:"large",fields:[
   {fieldname:"summary",fieldtype:"HTML"},{fieldname:"scan",label:"Scanner",fieldtype:"Data",description:"Station → Work Order choice → Good Quantity → tag/bin → Confirm. Optional tag and bin may be scanned in either order. Next/Previous Material Choices page lists."},
   {fieldname:"station",label:"Workstation Queue Card",fieldtype:"Data"},{fieldname:"read_station",label:"Read Station",fieldtype:"Button"},
   {fieldname:"qty",label:"Quantity in This Bundle",fieldtype:"Float"},{fieldname:"set_qty",label:"Set Quantity",fieldtype:"Button"},
   {fieldname:"identity",label:"Preprinted Main Tag / Empty Output Bin",fieldtype:"Data"},{fieldname:"read_identity",label:"Read Tag / Bin",fieldtype:"Button"},
   {fieldname:"reason",label:"Notes / Cancellation Reason",fieldtype:"Small Text"},{fieldname:"set_reason",label:"Set Reason",fieldtype:"Button"},
   {fieldname:"cancel_declaration",label:"Cancel a Declaration",fieldtype:"Button"},{fieldname:"pack_mode",label:"Back to Bundle / Tag",fieldtype:"Button"},
   {fieldname:"help",fieldtype:"HTML",options:"<small>Only reported good final-operation output is available. This does not report production again or create stock. Supervisor receipt preparation adopts the exact bundles; ERP submission activates their stock. Bound-Draft cancellation requires a supervisor. CFG:CMD:CANCEL exits safely.</small>"}
  ],primary_action_label:"Confirm",primary_action:()=>enqueue(()=>c.confirm()),secondary_action_label:"Cancel",secondary_action:()=>enqueue(()=>c.scan("CFG:CMD:CANCEL"))});
  c=createController({storage:localStorage,locks:navigator.locks,owner:options.owner,nonce:options.nonce,render,rpc:(method,args)=>f.call({method:`cfg_kanban.services.output_declarations.${method}`,args:{...args,operator_session_token:options.token()},freeze:true,error:()=>{}}).then(response=>response.message),close:()=>dialog.hide(),success:async result=>{dialog.hide();await options.success(result);}});
  for(const [button,method,field] of [["read_station","station","station"],["set_qty","quantity","qty"],["read_identity","identity","identity"],["set_reason","notes","reason"]])dialog.fields_dict[button].$input.on("click",()=>enqueue(()=>c[method](dialog.get_value(field))));
  dialog.fields_dict.cancel_declaration.$input.on("click",()=>enqueue(()=>c.cancelMode()));dialog.fields_dict.pack_mode.$input.on("click",()=>enqueue(()=>c.packMode()));
  dialog.fields_dict.scan.$input.on("keydown",event=>{if(event.key==="Enter"){event.preventDefault();const value=dialog.get_value("scan");dialog.set_value("scan","");enqueue(()=>c.scan(value));}});
  dialog.$wrapper.on("hidden.bs.modal",()=>{c.state.closed=true;options.onClose();});dialog.show();
  try{c.restore();}catch(error){dialog.hide();throw error;}
  if(options.stationScan&&!c.state.pending)await enqueue(()=>c.station(options.stationScan));focus();return {controller:c,dialog,focus,scan:value=>enqueue(()=>c.scan(value))};
 }
 const api={createController,open,pendingKey:key};if(typeof module!=="undefined"&&module.exports)module.exports=api;else root.cfg_output_declarations=api;
})(typeof window==="undefined"?globalThis:window);
