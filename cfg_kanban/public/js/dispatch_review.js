/* Dispatch Plan review: scanner, touch and camera share the same evidence and closing choice. */
(function(root){
 'use strict';
 const methods={begin:'begin_dispatch_review',finish:'finish_dispatch_review',hold:'hold_dispatch_review',resume:'resume_dispatch_review'};
 const modeCommands={REVIEW_DISPATCH:'begin',FINISH_DISPATCH_REVIEW:'finish',HOLD_DISPATCH_REVIEW:'hold',RESUME_DISPATCH_REVIEW:'resume'};
 function createController(env){
  const s={mode:env.mode||'begin',context:null,action:'',count:'',movement:'',reason:'',arm:'',loading:false,busy:false,pending:null,closed:false,message:'Scan the Dispatch Plan or Dispatch Review.'};
  const fail=msg=>{throw new Error(msg);},changed=()=>env.render(s);
  function edit(){if(env.owner()!==env.openedOwner)fail('Identify the original operator before continuing.');if(s.pending)fail('Retry the original review submission before changing its details.');}
  function mode(value){edit();s.mode=value;s.reason='';s.arm='';changed();}
  async function load(value){
   edit();s.context=null;s.action='';s.count='';s.movement='';s.reason='';s.loading=true;changed();
   try{
    const result=await env.rpc('get_dispatch_review_context',{scan_value:value,operator_session_token:env.token()});
    if(s.closed)return;if(env.owner()!==env.openedOwner)fail('Operator changed; reopen the review.');
    s.context=result;
    if(s.mode==='begin'&&['Reviewing','Held'].includes(result.review?.state))s.mode='finish';
    s.message=result.review?.state==='Overnight'?'This Plan retains its overnight commitments. Use Resume Review and a reason to continue.':
     result.review?.state==='Completed'?'This trip is reconciled. Its closing snapshot is retained below.':
     s.mode==='begin'?'Review loaded, delivered and remaining prepared quantities; Confirm freezes new fulfilment.':'Select the closing choice, scan its closed lorry stock count and enter a reason.';
   }finally{s.loading=false;changed();}
  }
  function set(name,value){edit();if(!['action','count','movement','reason'].includes(name))fail('Unknown review input.');s[name]=String(value||'').trim();changed();}
  function select(n){edit();const action=s.context?.actions?.[n-1];if(!action){s.action='';changed();fail('Select a displayed closing choice.');}s.action=action;changed();}
  function ready(){
   if(s.loading||s.busy||s.closed||!s.context||env.owner()!==env.openedOwner)return false;
   if(s.pending)return true;
   const review=s.context.review;
   if(s.mode==='begin')return !review&&s.context.plan.state==='Loaded';
   if(!review)return false;
   if(s.mode==='hold')return review.state==='Reviewing'&&!!s.reason;
   if(s.mode==='resume')return ['Reviewing','Overnight'].includes(review.state)&&!!s.reason;
   return ['Reviewing','Held'].includes(review.state)&&!!s.action&&!!s.count&&!!s.reason&&
    (!['Returned to Warehouse','Transferred to Another Lorry'].includes(s.action)||!!s.movement);
  }
  async function confirm(){
   if(s.busy||s.closed)return;if(!ready())fail('Complete the review choice, required evidence and reason first.');
   if(env.owner()!==env.openedOwner)fail('Identify the original operator before confirming.');
   s.busy=true;changed();const retry=!!s.pending;
   try{
    if(!s.pending){
     const args=s.mode==='begin'?{dispatch_plan:s.context.plan.name}:{dispatch_review:s.context.review.name,reason:s.reason};
     if(s.mode==='finish')Object.assign(args,{action:s.action,reconciliation_name:s.count,movement_stock_entry:s.movement||null,balance_hash:s.context.balance_hash});
     s.pending={method:methods[s.mode],args:{...args,event_token:env.nonce()}};
    }
    const result=await env.rpc(s.pending.method,{...s.pending.args,operator_session_token:env.token()});
    if(s.closed)return;s.closed=true;env.close();if(env.owner()===env.openedOwner)await env.success(result);
   }catch(error){const type=error?.exc_type||error?.responseJSON?.exc_type;if(!retry&&type&&type!=='DispatchReviewReplayError')s.pending=null;throw error;}
   finally{s.busy=false;changed();}
  }
  async function scan(raw){
   const value=String(raw||'').trim(),upper=value.toUpperCase();if(!value||s.closed)return;
   if(upper==='CFG:CMD:CANCEL'){s.closed=true;env.close();return;}
   if(upper==='CFG:CMD:CONFIRM')return confirm();
   if(upper==='CFG:CMD:DISPATCH_REVIEW_CAMERA')return env.camera();
   if(upper==='CFG:CMD:HELP'){s.message='Scan DPL/KDR, select CFG:SELECT:1–5, scan the closed KREC count. DISPATCH_REVIEW_MOVEMENT arms a Stock Entry; DISPATCH_REVIEW_REASON arms the reason. Confirm submits; Cancel closes. Refresh reads server state before a new correction.';changed();return;}
   edit();
   const command=upper.replace(/^CFG:CMD:/,'');if(upper.startsWith('CFG:CMD:')&&modeCommands[command])return mode(modeCommands[command]);
   if(upper==='CFG:CMD:DISPATCH_REVIEW_REFRESH')return load(s.context?.plan.name||'');
   if(upper==='CFG:CMD:DISPATCH_REVIEW_REASON'){s.arm='reason';return;}
   if(upper==='CFG:CMD:DISPATCH_REVIEW_MOVEMENT'){s.arm='movement';return;}
   if(upper==='CFG:CMD:DISPATCH_REVIEW_COUNT'){s.arm='count';return;}
   const choice=upper.match(/^CFG:SELECT:([1-9]|10)$/);if(choice)return select(Number(choice[1]));
   if(upper.startsWith('CFG:'))fail('Use a displayed Dispatch Review command.');
   if(s.arm){const field=s.arm;s.arm='';return set(field,value);}
   if(upper.startsWith('KREC-'))return set('count',value);
   return load(value);
  }
  return {state:s,mode,load,set,select,ready,confirm,scan};
 }
 async function open(options){
  const f=options.frappe,e=f.utils.escape_html;let dialog,controller,tail=Promise.resolve(),camera=null;
  const focus=()=>{if(!controller.state.closed)dialog.fields_dict.scan.$input.focus();};
  function queue(work){tail=tail.then(work).catch(error=>{controller.state.message=options.errorMessage(error,error.message||'Dispatch Review failed.');render(controller.state);}).finally(focus);return tail;}
  function stopCamera(){const old=camera;camera=null;old?.hide_dialog?.();}
  function startCamera(){
   if(camera||controller.state.closed)return;if(!f.ui.Scanner)throw new Error('Camera scanning is unavailable; use the Scanner field.');
   let accepted=false;camera=new f.ui.Scanner({dialog:true,multiple:false,on_scan:data=>{
    if(accepted||controller.state.closed)return;accepted=true;const value=String(data.decodedText||'').trim();stopCamera();if(value)queue(()=>controller.scan(value));
   }});const instance=camera;camera.dialog?.$wrapper?.one('hidden.bs.modal',()=>{accepted=true;if(camera===instance)camera=null;focus();});
  }
  function render(s){
   const context=s.context,review=context?.review;
   const rows=(context?.balances||[]).map(row=>`<tr><td>${e(row.item_code)} · ${e(row.batch_no||'No Batch')}</td><td>${e(row.visible_code||row.handling_unit||'ERP stock')}</td><td>${row.loaded_qty}</td><td>${row.delivered_qty}</td><td>${row.remaining_qty} ${e(row.stock_uom)}</td></tr>`).join('');
   const choices=(context?.actions||[]).map((action,index)=>`<button type="button" class="btn btn-default btn-block text-left review-choice" data-number="${index+1}">${index+1}. ${e(action)}${s.action===action?' ✓':''}</button>`).join('');
   const additional=(context?.unassigned_deliveries||[]).map(row=>`${e(row.item_code)} · ${row.delivered_qty} ${e(row.stock_uom)}`).join('<br>');
   const lorry=(context?.lorry_balances||[]).map(row=>`${e(row.item_code)} / ${e(row.batch_no||'No Batch')}: ${row.erp_qty} ${e(row.stock_uom)} · This Plan outstanding budget: ${row.prepared_remaining_budget}`).join('<br>');
   const privatePending=s.pending&&options.owner()!==options.openedOwner;
   dialog.fields_dict.summary.$wrapper.html(privatePending?'<p>Identify the original operator to reconcile this action.</p>':
    `<div class="alert ${controller.ready()?'alert-success':'alert-warning'}">${e(s.message)}</div><p>${e(context?.plan.name||'')} · ${e(review?.name||'')} · ${e(review?.state||'')}</p>${context?`<p>${e(context.boundary)}</p><table class="table table-bordered"><tr><th>Item / Batch</th><th>Tag</th><th>Loaded</th><th>Delivered</th><th>Prepared remaining</th></tr>${rows}</table>`:''}<p><strong>Current ERP lorry stock</strong><br>${lorry||'No ERP stock remaining'}</p><p><strong>Additional unassigned stock delivered</strong><br>${additional||'None recorded'}</p><p>${e(s.action)} · ${e(s.count)} · ${e(s.movement)} · ${e(s.reason)}</p>${s.mode==='finish'?choices:''}${s.pending?`<div class="alert alert-warning">Retry original action: ${e(JSON.stringify(s.pending.args))}</div>`:''}${review?.closing_snapshot_json?`<details><summary>Recorded closing stock snapshot</summary><pre>${e(review.closing_snapshot_json)}</pre></details>`:''}`);
   dialog.fields_dict.summary.$wrapper.find('.review-choice').on('click',function(){queue(()=>controller.select(Number(this.dataset.number)));});
   for(const name of ['count','movement','reason'])dialog.set_df_property?.(name,'hidden',s.mode==='begin'||(name!=='reason'&&s.mode!=='finish')?1:0);
   if(controller.ready())dialog.enable_primary_action();else dialog.disable_primary_action();
  }
  const openedOwner=options.owner();options={...options,openedOwner};
  dialog=new f.ui.Dialog({title:'Dispatch Plan Review',size:'extra-large',fields:[
   {fieldname:'scan',label:'Scanner',fieldtype:'Data'},
   {fieldname:'camera',label:'Scan with Camera',fieldtype:'Button',click:()=>queue(()=>startCamera())},
   {fieldname:'summary',fieldtype:'HTML'},
   {fieldname:'finish',label:'Finish Review',fieldtype:'Button',click:()=>queue(()=>controller.mode('finish'))},
   {fieldname:'hold',label:'Hold for Investigation',fieldtype:'Button',click:()=>queue(()=>controller.mode('hold'))},
   {fieldname:'resume',label:'Resume Plan',fieldtype:'Button',click:()=>queue(()=>controller.mode('resume'))},
   {fieldname:'refresh',label:'Refresh Recorded Review',fieldtype:'Button',click:()=>queue(()=>controller.scan('CFG:CMD:DISPATCH_REVIEW_REFRESH'))},
   {fieldname:'count',label:'Closed Lorry Stock Count',fieldtype:'Link',options:'CFG Kanban Route Reconciliation',onchange:()=>queue(()=>controller.set('count',dialog.get_value('count')))},
   {fieldname:'movement',label:'Submitted Recovery Stock Entry',fieldtype:'Link',options:'Stock Entry',onchange:()=>queue(()=>controller.set('movement',dialog.get_value('movement')))},
   {fieldname:'reason',label:'Decision / Resume Reason',fieldtype:'Small Text',onchange:()=>queue(()=>controller.set('reason',dialog.get_value('reason')))},
  ],primary_action_label:'Confirm Reviewed Decision',primary_action:()=>queue(()=>controller.confirm())});
  controller=createController({mode:options.mode,owner:options.owner,openedOwner,token:options.token,nonce:options.nonce,
   rpc:async(method,args)=>(await f.call({method:'cfg_kanban.services.dispatch_reconciliation.'+method,args})).message,
   render,camera:startCamera,close:()=>dialog.hide(),success:options.success});
  dialog.onhide=()=>{controller.state.closed=true;stopCamera();options.onClose();};
  dialog.fields_dict.scan.$input.on('keydown',event=>{
   if(!['Tab','Enter'].includes(event.key)||event.shiftKey||event.ctrlKey||event.altKey||event.metaKey||event.isComposing)return;
   const value=String(dialog.get_value('scan')||'').trim();if(event.key==='Tab'&&!value)return;
   event.preventDefault();event.stopPropagation();dialog.set_value('scan','');if(value)queue(()=>controller.scan(value));
  });
  dialog.show();render(controller.state);focus();if(options.planScan)await queue(()=>controller.load(options.planScan));
  return controller.state.closed?null:{scan:value=>queue(()=>controller.scan(value)),focus,controller};
 }
 const api={createController,open};if(typeof module!=='undefined'&&module.exports)module.exports=api;
 root.cfg_dispatch_review=api;
})(typeof window==='undefined'?globalThis:window);
