/* Direct customer-selected custody intake; QC/accounting remain on the existing Return Case. */
(function(root){
 'use strict';
 const prefix='cfg_direct_customer_return_v1:';
 function createController(env){
  const owner=env.owner(),key=prefix+owner;
  const s={owner,closed:false,busy:false,review:null,pending:null,baseline:null,voidReason:'',armVoid:false,message:'Select Company, Customer and inspection custody; enter physical returned Items and a reason. Review before issuing the note.'};
  const copy=value=>JSON.parse(JSON.stringify(value)),fail=message=>{throw new Error(message);},changed=()=>env.render(s);
  function read(){const value=env.storage.getItem(key);if(!value)return null;let row;try{row=JSON.parse(value);}catch(_){fail('Pending return data is unreadable; reconcile this terminal before another intake.');}
   if(row.owner!==owner||!row.revision||!['Pending','Recorded','Rejected','Voided'].includes(row.status)
     ||(row.status==='Pending'&&(row.args?.event_token!==row.revision||!row.args?.company||!row.args?.customer||!row.args?.inspection_location||!Array.isArray(row.args?.lines)||!row.args.lines.length)))
    fail('Pending return data is incomplete; reconcile this terminal.');return row;}
  function write(row){env.storage.setItem(key,JSON.stringify(row));}
  function actor(){if(env.owner()!==owner)fail('Identify the original intake operator before continuing.');}
  function editable(){actor();if(s.closed||s.busy||s.pending||s.review)fail('Finish the reviewed intake or reconcile its original submission before editing.');}
  function exclusive(work){if(!env.locks?.request)fail('Direct return submission requires HTTPS and a browser supporting Web Locks.');return env.locks.request(key,work);}
  function restore(){const saved=read();s.baseline=saved?.revision||null;s.pending=saved?.status==='Pending'?saved:null;changed();return s.pending;}
  function edit(){actor();if(s.pending||s.busy)fail('Reconcile the original pending intake before correcting its details.');s.review=null;s.message='Edit the intake, then Review again.';changed();}
  async function recorded(result,token){
   const saved=read();if(saved?.revision===token)write({owner,revision:token,status:'Recorded',return_case:result.return_case.name});s.baseline=token;s.pending=null;
   if(s.closed||env.owner()!==owner)return;s.closed=true;env.close();await env.success(result.return_case);
  }
  async function confirm(){
   if(s.closed||s.busy)return;actor();
   if(!s.pending&&!s.review){
    const values=env.values();if(!values)fail('Complete the required return inputs first.');
    s.busy=true;changed();try{const context=await env.rpc('preview_direct_customer_return',values);if(s.closed)return;actor();
     s.review={context,args:{company:context.company,customer:context.customer,customer_address:context.customer_address||null,
      inspection_location:context.inspection_location,customer_return_reason:context.customer_return_reason,
      customer_acknowledgement_name:context.customer_acknowledgement_name||'',lines:context.lines}};
     s.message='Review Company, Customer, custody and every physical quantity in its stock UOM. Confirm issues the Temporary Return Note; Return to Edit makes corrections.';
    }finally{s.busy=false;changed();}return;
   }
   s.busy=true;changed();try{await exclusive(async()=>{
    actor();if(s.closed)return;const saved=read(),retry=!!s.pending;
    if(saved?.status==='Pending'&&saved.args.event_token!==s.pending?.args.event_token){s.pending=saved;s.review=null;changed();fail('Another intake is awaiting reconciliation. Review its original pending details before retrying.');}
    if(s.pending&&(!saved||saved.status!=='Pending'||saved.args.event_token!==s.pending.args.event_token))fail('This intake was reconciled in another tab. Refresh its recorded outcome.');
    if(!s.pending&&saved?.revision!==s.baseline&&(saved?.revision||s.baseline))fail('Another intake completed in another tab. Close and reopen before issuing a new note.');
    const pending=s.pending||{owner,status:'Pending',revision:env.nonce(),args:copy(s.review.args)};
    pending.args.event_token=pending.revision;write(pending);s.pending=pending;changed();
    let result;try{result=await env.rpc('create_direct_customer_return',pending.args);}
    catch(error){const type=error?.exc_type||error?.responseJSON?.exc_type;
     if(!retry&&['ValidationError','PermissionError','DoesNotExistError','LinkValidationError','MandatoryError'].includes(type)){
      write({owner,revision:pending.revision,status:'Rejected'});s.pending=null;s.review=null;s.baseline=pending.revision;
     }throw error;}
    await recorded(result,pending.revision);
   });}finally{s.busy=false;changed();}
  }
  async function reconcile(voiding=false){
   actor();if(s.busy||s.closed)return;if(!s.pending){const saved=read();if(saved?.status==='Pending')s.pending=saved;}
   if(!s.pending)fail('There is no pending intake on this terminal to reconcile.');
   if(voiding&&!s.voidReason.trim())fail('Enter or scan a reason before voiding an unrecorded intake.');
   s.busy=true;changed();try{await exclusive(async()=>{
    actor();if(s.closed)return;const token=s.pending.args.event_token;
    const result=await env.rpc(voiding?'void_unrecorded_direct_return':'get_direct_return_receipt',{
     event_token:token,...(voiding?{reason:s.voidReason.trim()}:{})});
    if(result.status==='Recorded')return recorded(result,token);
    if(s.closed)return;actor();if(result.status==='Voided'){
     const saved=read();if(saved?.revision===token)write({owner,revision:token,status:'Voided'});
     s.pending=null;s.review=null;s.baseline=token;s.message='Unrecorded intake voided. Its old token cannot create a note; review the corrected intake again.';
    }else s.message='No note is recorded yet. Retry the original details, or enter a void reason and void the unrecorded action before correcting it.';
   });}finally{s.busy=false;changed();}
  }
  function voidReason(value){actor();s.voidReason=String(value||'');changed();}
  function close(){s.closed=true;env.close();}
  return {state:s,restore,editable,edit,confirm,reconcile,voidReason,close};
 }
 async function open(options){
  const f=options.frappe,e=f.utils.escape_html,owner=options.owner();
  const setup=(await f.call({method:'cfg_kanban.services.direct_customer_returns.get_direct_return_setup',args:{operator_session_token:options.token()}})).message;
  if(options.owner()!==owner)throw new Error('Operator changed; reopen Direct Customer Return.');
  await f.require('/assets/cfg_kanban/js/delivery_action_scanner.js');
  if(options.owner()!==owner)throw new Error('Operator changed; reopen Direct Customer Return.');
  let dialog,controller,input,camera=null,tail=Promise.resolve();
  const focus=()=>{if(!controller?.state.closed)dialog.fields_dict.scan.$input.focus();};
  function queue(work){tail=tail.then(work).catch(error=>{controller.state.message=options.errorMessage(error,error.message||'Direct return failed.');render(controller.state);}).finally(focus);return tail;}
  function dispatch(raw){if(String(raw||'').trim().toUpperCase()==='CFG:CMD:CANCEL')return controller.close();return queue(()=>scan(raw));}
  function dispatch(value){if(String(value||'').trim().toUpperCase()==='CFG:CMD:CANCEL')return controller.close();return queue(()=>scan(value));}
  function stopCamera(){const old=camera;camera=null;old?.hide_dialog?.();}
  function cameraScan(){if(camera||controller.state.closed)return;if(options.owner()!==owner)throw new Error('Identify the original intake operator before scanning.');if(!f.ui.Scanner)throw new Error('Camera scanning is unavailable; use the Scanner field.');
   let accepted=false;camera=new f.ui.Scanner({dialog:true,multiple:false,on_scan:data=>{if(accepted||controller.state.closed)return;accepted=true;const raw=String(data.decodedText||'').trim();stopCamera();if(raw)dispatch(raw);}});
   const current=camera;camera.dialog?.$wrapper?.one('hidden.bs.modal',()=>{accepted=true;if(camera===current)camera=null;focus();});}
  const inputs=[
   {fieldname:'company',label:'Selling Company',fieldtype:'Link',options:'Company',reqd:1,get_query:()=>({filters:{is_group:0}})},
   {fieldname:'customer',label:'Customer',fieldtype:'Link',options:'Customer',reqd:1,get_query:()=>({filters:{disabled:0}})},
   {fieldname:'customer_address',label:'Customer Address (Optional)',fieldtype:'Link',options:'Address',get_query:()=>({filters:[['Dynamic Link','link_doctype','=','Customer'],['Dynamic Link','link_name','=',dialog.get_value('customer')||'']]})},
   {fieldname:'inspection_location',label:'Inspection Custody Location',fieldtype:'Link',options:'Location',reqd:1},
   {fieldname:'customer_return_reason',label:'Customer Return Reason',fieldtype:'Small Text',reqd:1},
   {fieldname:'customer_acknowledgement_name',label:'Customer Representative (Optional)',fieldtype:'Data'},
   {fieldname:'lines',label:'Returned Physical Items — Qty in Item Stock UOM',fieldtype:'Table',reqd:1,in_place_edit:true,cannot_add_rows:false,cannot_delete_rows:false,
    fields:[
     {fieldname:'item_code',label:'Item',fieldtype:'Link',options:'Item',reqd:1,in_list_view:1,columns:2,get_query:()=>({filters:{disabled:0}})},
     {fieldname:'batch_no',label:'Batch (Optional)',fieldtype:'Link',options:'Batch',in_list_view:1,columns:1},
     {fieldname:'expiry_date',label:'Printed Expiry (Optional)',fieldtype:'Date',in_list_view:1,columns:1},
     {fieldname:'claimed_qty',label:'Physical Qty (Stock UOM)',fieldtype:'Float',reqd:1,in_list_view:1,columns:2},
     {fieldname:'condition',label:'Condition',fieldtype:'Select',options:setup.conditions,default:'Unknown',in_list_view:1,columns:2},
     {fieldname:'original_visible_code',label:'Stock Tag / Reference (Optional)',fieldtype:'Data',in_list_view:1,columns:2},
     {fieldname:'details',label:'Details',fieldtype:'Small Text'},
    ]},
  ];
  function values(){const values=dialog.get_values();if(!values)return null;return Object.fromEntries(inputs.map(field=>[field.fieldname,values[field.fieldname]]));}
  function render(s){
   if(!dialog)return;const owned=options.owner()===owner,context=owned?(s.review?.context||s.pending?.args):null;
   const rows=(context?.lines||[]).map(row=>`<tr><td>${e(row.item_code)}</td><td>${e(row.batch_no||'No Batch')}<br>${e(row.expiry_date||'')}</td><td>${e(String(row.claimed_qty))} ${e(row.stock_uom||'')}</td><td>${e(row.condition||'Unknown')}<br>${e(row.original_visible_code||'')}</td></tr>`).join('');
   dialog.fields_dict.summary.$wrapper.html(`<div class="alert alert-warning">Temporary custody for QC. This creates no ERP stock receipt or accounting credit.</div><p>${e(owned?s.message:'Identify the original intake operator before continuing.')}</p>${context?`<p><strong>${e(context.company)} · ${e(context.customer_name||context.customer)}</strong><br>Custody: ${e(context.inspection_location)}<br>${e(context.customer_return_reason)}</p><table class="table table-bordered"><tr><th>Item</th><th>Batch / Expiry</th><th>Physical Qty</th><th>Condition / Ref</th></tr>${rows}</table>`:''}${owned&&s.pending?'<div class="alert alert-warning">Original submission retained. Confirm retries it. Refresh reads its outcome; Cancel closes and preserves this pending action.</div>':''}`);
   const nav=input?.state,choices=input?.choices()||[];
   dialog.fields_dict.navigation.$wrapper.html(`<p>${nav?.table?`${e(nav.table.label||'Returned Items')} · Row ${nav.table.index+1}`:'Select an input number, then scan its value.'}</p>`+choices.slice((nav?.page||0)*10,(nav?.page||0)*10+10).map((field,index)=>`<div>${index+1}. ${e(field.label||field.name)}${(nav?.table?nav.table.column:nav?.field)===field.name?' ✓':''}</div>`).join(''));
   for(const field of inputs)dialog.set_df_property?.(field.fieldname,'hidden',!owned||s.review||s.pending?1:0);
   dialog.set_df_property?.('void_reason','hidden',owned&&s.pending?0:1);
   if(s.busy||!owned)dialog.disable_primary_action();else dialog.enable_primary_action();
   dialog.get_primary_btn?.().text(s.pending?'Retry Original Intake':s.review?'Issue Temporary Return Note':'Review Return Details');
  }
  async function scan(raw){
   const text=String(raw||'').trim(),upper=text.toUpperCase();if(!text||controller.state.closed)return;
   if(upper==='CFG:CMD:CANCEL')return controller.close();
   if(upper==='CFG:CMD:CONFIRM')return controller.confirm();
   if(['CFG:CMD:RETURN_CAMERA','CFG:CMD:DELIVERY_CAMERA'].includes(upper))return cameraScan();
   if(upper==='CFG:CMD:RETURN_RECONCILE')return controller.reconcile();
   if(upper==='CFG:CMD:RETURN_VOID_PENDING')return controller.reconcile(true);
   if(upper==='CFG:CMD:RETURN_VOID_REASON'){controller.state.armVoid=true;return;}
   if(controller.state.armVoid){controller.state.armVoid=false;return controller.voidReason(text);}
   if(upper==='CFG:CMD:RETURN_EDIT')return controller.edit();
   if(upper==='CFG:CMD:HELP'){controller.state.message='Select Company, Customer, optional address, custody and reason. Select Returned Items, RETURN_ADD_ITEM, numbered columns and values; Material Qty enters the active row quantity. Review then Confirm issues the note. RETURN_EDIT returns to inputs. Pending requests use RETURN_RECONCILE or RETURN_VOID_REASON plus RETURN_VOID_PENDING. Camera/Tab/Enter and Cancel are supported.';render(controller.state);return;}
   controller.editable();
   if(upper==='CFG:CMD:RETURN_REASON')return input.field('customer_return_reason');
   if(upper==='CFG:CMD:RETURN_ITEMS')return input.field('lines');
   const aliases={'CFG:CMD:RETURN_ADD_ITEM':'CFG:CMD:DELIVERY_ADD_ROW','CFG:CMD:RETURN_NEXT_ITEM':'CFG:CMD:DELIVERY_NEXT_ROW','CFG:CMD:RETURN_PREVIOUS_ITEM':'CFG:CMD:DELIVERY_PREVIOUS_ROW','CFG:CMD:RETURN_INPUTS':'CFG:CMD:DELIVERY_INPUTS'};
   const qty=upper.match(/^CFG:QTY:MATERIAL:(.+)$/);
   if(qty){if(input.state.table?.name!=='lines')throw new Error('Select a returned Item row before entering Material Qty.');input.state.table.column='claimed_qty';return input.value(qty[1]);}
   return input.scan(aliases[upper]||text);
  }
  dialog=new f.ui.Dialog({title:'Direct Customer Return',size:'extra-large',fields:[
   {fieldname:'scan',label:'Scanner',fieldtype:'Data'},{fieldname:'camera',label:'Scan with Camera',fieldtype:'Button',click:()=>queue(cameraScan)},
   {fieldname:'summary',fieldtype:'HTML'},{fieldname:'navigation',fieldtype:'HTML'},...inputs,
   {fieldname:'add_item',label:'Add Returned Item',fieldtype:'Button',click:()=>queue(async()=>{controller.editable();input.field('lines');await input.tableRow(0,true);})},
   {fieldname:'edit',label:'Return to Edit',fieldtype:'Button',click:()=>queue(()=>controller.edit())},
   {fieldname:'refresh',label:'Refresh Pending Outcome',fieldtype:'Button',click:()=>queue(()=>controller.reconcile())},
   {fieldname:'void_reason',label:'Reason to Void Unrecorded Intake',fieldtype:'Small Text',onchange:()=>{const value=dialog.get_value('void_reason');return queue(()=>controller.voidReason(value));}},
   {fieldname:'void_pending',label:'Void Unrecorded Intake',fieldtype:'Button',click:()=>queue(()=>controller.reconcile(true))},
  ],primary_action_label:'Review Return Details',primary_action:()=>queue(()=>controller.confirm())});
  controller=createController({owner:options.owner,storage:options.storage,locks:options.locks,nonce:options.nonce,values,render,
   rpc:async(method,args)=>(await f.call({method:'cfg_kanban.services.direct_customer_returns.'+method,args:{...args,operator_session_token:options.token()}})).message,
   close:()=>dialog.hide(),success:options.success});
  input=root.cfg_delivery_action_scanner.createController({owner:options.owner,openedOwner:owner,
   fields:inputs.map(field=>({...field,name:field.fieldname})),read:name=>dialog.get_value(name),set:(name,value)=>dialog.set_value(name,value),
   render:()=>render(controller.state),camera:cameraScan,nonce:options.nonce});
  controller.restore();
  if(!setup.enabled||!setup.can_start)controller.state.message='New return intake requires enabled Customer Return Workflows and Start permission. A pending recorded outcome can still be read with Refresh.';
  dialog.onhide=()=>{controller.state.closed=true;stopCamera();options.onClose();};
  dialog.fields_dict.scan.$input.on('keydown',event=>{
   if(!['Enter','Tab'].includes(event.key)||event.shiftKey||event.ctrlKey||event.altKey||event.metaKey||event.isComposing)return;
   const value=String(dialog.get_value('scan')||'').trim();if(event.key==='Tab'&&!value)return;event.preventDefault();event.stopPropagation();dialog.set_value('scan','');if(value)return dispatch(value);
  });
  dialog.show();render(controller.state);focus();return {scan:dispatch,focus,controller,input};
 }
 const api={createController,open};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.cfg_direct_customer_return=api;
})(typeof window==='undefined'?globalThis:window);
