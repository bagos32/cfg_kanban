/* Prepared customer-load selection; scanner, camera and touch share one controller. */
(function(root){
 'use strict';
 function createController(env){
  const s={plans:[],plan:null,customerScan:'',page:0,busy:false,pending:null,closed:false,completed:false,message:'Scan the loaded Dispatch Plan or Customer Site.'};
  const changed=()=>env.render(s),fail=msg=>{throw new Error(msg);};
  function select(n){
   if(s.pending)fail('Retry the original prepared delivery before changing it.');
   const plan=s.plans[s.page*10+n-1];if(!plan)fail('Select one of the displayed numbered Plans.');
   s.plan=plan;s.message=s.customerScan?'Ready: confirm this prepared customer load.':'Scan the Customer Site printed at the delivery location.';changed();
  }
  async function context(value){
   if(env.owner()!==env.openedOwner)fail('Identify the original operator before selecting prepared work.');
   if(s.pending)fail('Retry the original prepared delivery before changing it.');
   const result=await env.rpc('prepared_delivery_context',{scan_value:value,operator_session_token:env.token()});
   if(s.closed)return;
   if(env.owner()!==env.openedOwner){s.plans=[];s.plan=null;s.customerScan='';changed();fail('Operator changed; close this dialog and identify the intended operator.');}
   if(result.customer_scan && s.plan){
    const match=result.plans.find(p=>p.name===s.plan.name);
    if(!match)fail('This Customer Site has no matching prepared Plan for the selected load.');
    s.plans=result.plans;s.plan=match;s.customerScan=result.customer_scan;
   }else{
    s.plans=result.plans||[];s.plan=null;s.page=0;s.customerScan=result.customer_scan||'';
    if(s.plans.length===1)select(1);
   }
   s.message=!s.plans.length?'No eligible loaded Customer Order Plans at this site.':
    !s.plan?'Select the exact numbered Plan.':!s.customerScan?'Scan the Customer Site printed at the delivery location.':'Ready: confirm this prepared customer load.';
   changed();
  }
  async function confirm(){
   if(s.busy||s.closed||s.completed)return;
   if(!s.plan||!s.customerScan)fail('Select the exact prepared Plan and scan its Customer Site first.');
   if(env.owner()!==env.openedOwner)fail('Identify the original operator before confirming this prepared delivery.');
   s.busy=true;changed();
   try{
    s.pending=s.pending||{dispatch_plan:s.plan.name,customer_scan:s.customerScan,event_token:env.nonce(),operator_session_token:env.token()};
    const result=await env.rpc('start_prepared_delivery',s.pending);
    s.completed=true;
    if(env.owner()!==env.openedOwner||env.token()!==s.pending.operator_session_token){
     s.plans=[];s.plan=null;s.customerScan='';s.pending=null;
     s.message='Prepared delivery was recorded for the original operator. Close this dialog and identify that operator to resume.';changed();return;
    }
    s.closed=true;env.close();await env.success(result);
   }catch(error){
    if(error?.exc_type||error?.responseJSON?.exc_type)s.pending=null;
    throw error;
   }finally{s.busy=false;changed();}
  }
  async function scan(raw){
   const value=String(raw||'').trim(),upper=value.toUpperCase();if(!value||s.closed)return;
   if(upper==='CFG:CMD:CANCEL'){s.closed=true;env.close();return;}
   if(upper==='CFG:CMD:CONFIRM')return confirm();
   if(upper==='CFG:CMD:PREPARED_DELIVERY_CAMERA')return env.camera();
   if(upper==='CFG:CMD:HELP'){s.message='Scan a Plan or Customer Site, choose CFG:SELECT:1–10 when needed, then Confirm. Next/Previous Material Choices page Plans. Cancel closes safely. No quantity re-entry is required.';changed();return;}
   if(s.pending)fail('Retry the original prepared delivery before changing it.');
   if(upper==='CFG:CMD:PREPARED_DELIVERY_SOURCE'){s.plan=null;s.customerScan='';s.plans=[];s.page=0;s.message='Scan another loaded Plan or Customer Site.';changed();return;}
   if(upper==='CFG:CMD:NEXT_MATERIALS'||upper==='CFG:CMD:PREVIOUS_MATERIALS'){
    s.page=Math.max(0,Math.min(Math.ceil(s.plans.length/10)-1,s.page+(upper.includes('NEXT_')?1:-1)));changed();return;
   }
   const choice=upper.match(/^CFG:SELECT:(10|[1-9])$/);if(choice)return select(Number(choice[1]));
   if(upper.startsWith('CFG:'))fail('Use a prepared-delivery command or scan a physical Customer Site/Dispatch Plan.');
   return context(value);
  }
  return {state:s,context,select,confirm,scan};
 }
 async function open(options){
  const f=options.frappe,e=f.utils.escape_html;let dialog,controller,tail=Promise.resolve(),camera=null;
  const focus=()=>{if(!controller.state.closed)dialog.fields_dict.scan.$input.focus();};
  function enqueue(work){tail=tail.then(work).catch(err=>{controller.state.message=options.errorMessage(err,err.message||'Prepared delivery failed.');render(controller.state);}).finally(focus);return tail;}
  function stopCamera(){const current=camera;camera=null;if(current)current.hide_dialog?.();}
  function startCamera(){
   if(camera||controller.state.closed)return;
   if(!f.ui.Scanner)throw new Error('Camera scanning is unavailable on this device. Use the Scanner field.');
   let accepted=false;
   camera=new f.ui.Scanner({dialog:true,multiple:false,on_scan:data=>{
    if(accepted||controller.state.closed)return;accepted=true;
    const value=String(data.decodedText||'').trim();stopCamera();if(value)enqueue(()=>controller.scan(value));else focus();
   }});
   const instance=camera;
   camera.dialog?.$wrapper?.one('hidden.bs.modal',()=>{accepted=true;if(camera===instance)camera=null;focus();});
  }
  function summary(plan){
   if(plan.quantity_summary)return plan.quantity_summary;
   const quantities={};for(const row of plan.lines||[])quantities[row.stock_uom]=(quantities[row.stock_uom]||0)+Number(row.loaded_qty||0);
   return Object.entries(quantities).map(([uom,qty])=>`${qty} ${uom}`).join(' / ');
  }
  function render(s){
   const rows=s.plans.slice(s.page*10,s.page*10+10).map((plan,i)=>
    `<button type="button" class="btn btn-default btn-block text-left prepared-plan-choice" data-number="${i+1}">${i+1}. ${e(plan.name)} · ${e(plan.business_label||'')} · ${e(plan.vehicle_reference||plan.vehicle_warehouse||'')} · ${e(summary(plan))}${s.plan?.name===plan.name?' ✓':''}</button>`).join('');
   dialog.fields_dict.review.$wrapper.html(`<p>${e(s.message)}</p>${rows}<p>${e(s.customerScan||'Customer Site scan required')}</p>`);
   dialog.fields_dict.review.$wrapper.find('.prepared-plan-choice').on('click',function(){const n=Number(this.dataset.number);enqueue(()=>controller.select(n));});
   if(s.busy||!s.plan||!s.customerScan)dialog.disable_primary_action();else dialog.enable_primary_action();
  }
  dialog=new f.ui.Dialog({title:'Prepared Customer Delivery',size:'large',fields:[
   {fieldname:'scan',label:'Scanner',fieldtype:'Data'},
   {fieldname:'camera',label:'Scan with Camera',fieldtype:'Button',click:()=>enqueue(()=>startCamera())},
   {fieldname:'review',fieldtype:'HTML'},
  ],primary_action_label:'Start / Resume Prepared Delivery',primary_action:()=>enqueue(()=>controller.confirm())});
  controller=createController({token:options.token,owner:options.owner,openedOwner:options.owner(),nonce:options.nonce,
   rpc:async(method,args)=>(await f.call({method:'cfg_kanban.services.dispatch_fulfilment.'+method,args})).message,
   render,close:()=>dialog.hide(),success:options.success,camera:startCamera});
  dialog.onhide=()=>{controller.state.closed=true;stopCamera();options.onClose();};
  dialog.fields_dict.scan.$input.on('keydown',event=>{
   if(!['Enter','Tab'].includes(event.key)||event.shiftKey||event.ctrlKey||event.altKey||event.metaKey||event.isComposing)return;
   const raw=String(dialog.get_value('scan')||'').trim();if(event.key==='Tab'&&!raw)return;
   event.preventDefault();event.stopPropagation();dialog.set_value('scan','');if(raw)enqueue(()=>controller.scan(raw));
  });
  dialog.show();render(controller.state);focus();
  if(options.planScan)await enqueue(()=>controller.context(options.planScan));
  if(options.siteScan)await enqueue(()=>controller.context(options.siteScan));
  return controller.state.closed ? null : {scan:value=>enqueue(()=>controller.scan(value)),focus,controller};
 }
 const api={createController,open};if(typeof module!=='undefined'&&module.exports)module.exports=api;
 root.cfg_dispatch_fulfilment=api;
})(typeof window==='undefined'?globalThis:window);
