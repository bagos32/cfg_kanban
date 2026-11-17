/* Stock isolation changes selection priority, never physical stock or validity. */
(function (root) {
 "use strict";
 function createController(env, initialAction = null) {
  const s={context:null,target:null,action:initialAction,reason:"",page:0,armSource:false,busy:false,pending:null,done:false,closed:false,message:""};
  const render=()=>env.render(s), fail=(message)=>{throw new Error(message);};
  function editable(){if(s.pending||s.busy||s.done||s.closed)fail("Retry the original confirmation, or cancel and reread the current isolation state.");}
  async function source(value){editable();const context=await env.rpc("get_rotation_isolation_context",{scan_value:value});s.context=context;s.target=context.targets.length===1?context.targets[0]:null;s.page=0;s.message="";render();}
  function choose(number){editable();const target=s.context?.targets[s.page*10+number-1];if(!target||number<1||number>10)fail("Select a displayed target from 1 to 10.");s.target=target;render();}
  function action(value){editable();if(value!==0&&value!==1)fail("Choose Isolate or Release.");s.action=value;render();}
  function reason(value){editable();s.reason=String(value||"").trim();render();}
  async function confirm(){
   if(s.busy||s.done||s.closed)return;
   if(!s.pending){
    if(!s.context||!s.target||s.action===null||!s.reason)fail("Select the exact tag/bin, Isolate or Release, and enter a reason.");
    s.pending={scan_value:s.context.source_scan,target_name:s.target.name,excluded:s.action,reason:s.reason,context_signature:s.context.signature,event_token:env.nonce()};
   }
   s.busy=true;render();
   try {
    const result=await env.rpc("set_rotation_isolation",s.pending);
    s.pending=null;s.done=true;render();await env.success(result);return result;
   } catch(error){if(error?.exc_type||error?.responseJSON?.exc_type)s.pending=null;throw error;}
   finally{s.busy=false;render();}
  }
  async function scan(raw){
   const value=String(raw||"").trim(),upper=value.toUpperCase();if(!value)return;
   if(upper==="CFG:CMD:CANCEL"){if(!s.busy){s.closed=true;env.close();}return;}
   if(upper==="CFG:CMD:CONFIRM")return confirm();
   editable();
   if(upper==="CFG:CMD:ISOLATE_STOCK")return action(1);
   if(upper==="CFG:CMD:RELEASE_STOCK")return action(0);
   if(upper==="CFG:CMD:ISOLATION_SOURCE"){s.armSource=true;render();return;}
   if(upper==="CFG:CMD:NEXT_MATERIALS"||upper==="CFG:CMD:PREVIOUS_MATERIALS"){
    const delta=upper==="CFG:CMD:NEXT_MATERIALS"?1:-1;s.page=Math.max(0,Math.min(Math.ceil((s.context?.targets.length||0)/10)-1,s.page+delta));render();return;
   }
   const selected=/^CFG:SELECT:(10|[1-9])$/.exec(upper);if(selected)return choose(Number(selected[1]));
   if(upper.startsWith("CFG:"))fail("Use an isolation command, target choice or physical tag/bin label.");
   if(!s.context||s.armSource){s.armSource=false;return source(value);}
   if(!s.target)fail("Select the numbered tag/bin before scanning the reason.");
   return reason(value);
  }
  return {state:s,source,choose,action,reason,confirm,scan};
 }
 async function open(options){
  const f=options.frappe,e=f.utils.escape_html;let dialog,controller,queue=Promise.resolve();
  function focus(){if(dialog?.$wrapper.is(":visible"))dialog.fields_dict.scan.$input.trigger("focus");}
  const enqueue=(action)=>{queue=queue.then(action).catch((error)=>{
   const message=f.msg_dialog;if(message&&message!==dialog&&message.$wrapper?.is(":visible")){message.$wrapper.one("hidden.bs.modal.cfg_isolation_focus",focus);message.hide();}
   controller.state.message=options.errorMessage(error,error.message||"Confirmation was not acknowledged. Retry its original data or cancel and reread the current state.");render(controller.state);
  }).finally(focus);return queue;};
  function render(s){
   if(!dialog)return;
   const describe=(row)=>`${e(row.scope)} · ${e(row.visible_code)} · ${e(row.item_code||"Physical bin")} · ${e(row.batch_no||"No Batch")} · ${e(row.qty)} ${e(row.stock_uom||"")}${row.expiry_date?` · Expiry ${e(row.expiry_date)}`:""}${row.loaded_on?` · Loaded ${e(row.loaded_on)}`:""}${row.source_code?` · Source ${e(row.source_code)}`:""}`;
   const rules=(row)=>`${row.excluded?"Local rule: ISOLATED":"Local rule: automatic selection enabled"}${row.effective_isolation?` · Effective tag/bin rules: ${e(row.effective_isolation.rules.map(rule=>rule.scope+" "+rule.visible_code+": "+rule.reason).join("; "))}`:""}${row.batch_isolation?` · Batch ISOLATED: ${e(row.batch_isolation.batch)} (${e(row.batch_isolation.reason)})`:""}`;
   const targets=(s.context?.targets||[]).slice(s.page*10,s.page*10+10).map((row,i)=>`<button type="button" class="btn btn-default isolation-choice" data-number="${i+1}">${i+1}. ${describe(row)}</button><br><small>${rules(row)}</small>`).join("<br>");
   dialog.fields_dict.summary.$wrapper.html(`<p><strong>${s.action===1?"ISOLATE":s.action===0?"RELEASE":"Choose Isolate or Release"}</strong></p>${targets}<p><strong>Selected:</strong> ${s.target?describe(s.target):"Scan source, then select the numbered target"}</p><p>Reason: ${e(s.reason||"Required")}</p><p>${s.target?rules(s.target):""}</p>${s.pending?"<div class='alert alert-warning'>Unacknowledged confirmation: retry the original request, or Cancel and reread current state before another action.</div>":""}<p class="text-danger">${e(s.message)}</p>`);
   dialog.fields_dict.summary.$wrapper.find(".isolation-choice").on("click",function(){enqueue(()=>controller.choose(Number(this.dataset.number)));});
   for(const name of ["source","read_source","isolate","release","reason","set_reason"])dialog.set_df_property(name,"read_only",!!(s.pending||s.busy));
   dialog.get_primary_btn().prop("disabled",s.busy);
  }
  dialog=new f.ui.Dialog({title:"FEFO / FIFO Isolation",size:"large",fields:[
   {fieldname:"summary",fieldtype:"HTML"},
   {fieldname:"scan",label:"Scanner",fieldtype:"Data",description:"Scan tag/bin → numbered target → Isolate Stock or Release Stock → reason → Confirm. Next/Previous Material Choices page targets; Isolation Source arms a new source."},
   {fieldname:"source",label:"Stock Tag / Bin",fieldtype:"Data"},
   {fieldname:"read_source",label:"Read Source",fieldtype:"Button"},
   {fieldname:"isolate",label:"Isolate",fieldtype:"Button"},{fieldname:"release",label:"Release",fieldtype:"Button"},
   {fieldname:"reason",label:"Isolation / Release Reason",fieldtype:"Small Text"},{fieldname:"set_reason",label:"Set Reason",fieldtype:"Button"},
   {fieldname:"help",fieldtype:"HTML",options:"<small>A bin rule stays on that physical bin and affects future loads until released. A tag/fill rule follows that stock through splits/replacements. Batch, tag and bin rules apply independently. Release only clears the selected rule. Explicit scans still require valid expiry, certificates, quality and stock. Cancel: CFG:CMD:CANCEL.</small>"}
  ],primary_action_label:"Confirm",primary_action:()=>enqueue(()=>controller.confirm()),secondary_action_label:"Cancel",secondary_action:()=>enqueue(()=>controller.scan("CFG:CMD:CANCEL"))});
  controller=createController({render,nonce:options.nonce,rpc:(method,args)=>f.call({method:`cfg_kanban.services.rotation_isolation.${method}`,args:{...args,operator_session_token:options.token()},freeze:true,error:()=>{}}).then(response=>response.message),close:()=>dialog.hide(),success:async(result)=>{dialog.hide();await options.success(result);}},options.action??null);
  dialog.fields_dict.read_source.$input.on("click",()=>enqueue(()=>controller.source(dialog.get_value("source"))));
  dialog.fields_dict.isolate.$input.on("click",()=>enqueue(()=>controller.action(1)));dialog.fields_dict.release.$input.on("click",()=>enqueue(()=>controller.action(0)));
  dialog.fields_dict.set_reason.$input.on("click",()=>enqueue(()=>controller.reason(dialog.get_value("reason"))));
  dialog.fields_dict.scan.$input.on("keydown",event=>{if(event.key==="Enter"){event.preventDefault();const value=dialog.get_value("scan");dialog.set_value("scan","");enqueue(()=>controller.scan(value));}});
  dialog.$wrapper.on("hidden.bs.modal",()=>{controller.state.closed=true;options.onClose();});
  dialog.show();render(controller.state);if(options.sourceScan)await enqueue(()=>controller.source(options.sourceScan));focus();
  return {controller,dialog,focus,scan:(value)=>enqueue(()=>controller.scan(value))};
 }
 const api={createController,open};if(typeof module!=="undefined"&&module.exports)module.exports=api;else root.cfg_stock_isolation=api;
})(typeof window==="undefined"?globalThis:window);
