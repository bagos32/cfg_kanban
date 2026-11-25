/* Guided whole-remainder recovery; the existing Manifest/ERP engine owns movement. */
(function(root){
 'use strict';
 const methods={create:'create_dispatch_recovery',source:'scan_dispatch_recovery',loose:'confirm_dispatch_recovery_loose',prepare:'prepare_dispatch_recovery',post:'post_dispatch_recovery',cancel:'cancel_dispatch_recovery'};
 function createController(env){
  const s={context:null,route:'',reason:'',line:'',qty:'',page:0,action:'',arm:'',busy:false,loading:false,pending:null,closed:false,message:'Scan the Dispatch Plan, Review or recovery Manifest. Begin a Dispatch Review first.'};
  const fail=message=>{throw new Error(message);},changed=()=>env.render(s),manifest=()=>s.context?.recovery_manifest;
  function edit(){if(env.owner()!==env.openedOwner)fail('Identify the original Supervisor before continuing.');if(s.pending)fail('Retry the original recovery submission before changing its details.');}
  function apply(context){
   s.context=context;s.line='';s.qty='';s.page=0;s.action='';s.arm='';
   const m=manifest();s.route=m&&m.state!=='Cancelled'?m.logistics_route:'';s.reason=m&&m.state!=='Cancelled'?m.recovery_reason:'';
   s.message=!m||m.state==='Cancelled'?'Choose an approved destination route and enter a Supervisor reason. Confirm creates the recovery checklist.':
    m.state==='Draft'?'Scan each Stock Tag or its container. Select each loose row and confirm its exact physical quantity; then Prepare.':
    m.state==='Received'?'Movement posted. Close a fresh balanced D3 lorry count, then Finish Dispatch Review using this Stock Entry. Do this before using the recovered stock.':
    m.state==='Dispatch Document Pending'?'Read back the ERP document. Submit a saved Draft through authorized ERP review, then Refresh.':
    'All sources confirmed and reserved. Review the destination, then confirm the movement.';
  }
  async function load(value){
   edit();s.context=null;s.route='';s.reason='';s.line='';s.qty='';s.page=0;s.loading=true;changed();
   try{const result=await env.rpc('get_dispatch_recovery_context',{scan_value:value,operator_session_token:env.token()});
    if(s.closed)return;if(env.owner()!==env.openedOwner)fail('Supervisor changed; reopen recovery.');apply(result);
   }finally{s.loading=false;changed();}
  }
  function choices(){const m=manifest();return !m||m.state==='Cancelled'?(s.context?.recovery_routes||[]):(m.lines||[]).filter(row=>!row.handling_unit);}
  function select(number){
   edit();const row=choices()[s.page*10+number-1];if(!row){s.route='';s.line='';changed();fail('Choose a displayed route or loose-stock row.');}
   const m=manifest();if(!m||m.state==='Cancelled'){s.route=row.name;s.action='create';}
   else{if(m.state!=='Draft')fail('Loose stock can only be confirmed on a Draft recovery.');s.line=row.name;s.qty='';s.action='loose';}changed();
  }
  function set(name,value){edit();if(name==='reason'&&manifest()&&manifest().state!=='Cancelled'&&s.action!=='cancel')fail('The saved recovery reason is immutable; cancel an unused recovery to change its instructions.');if(!['reason','qty'].includes(name))fail('Unknown recovery input.');s[name]=String(value??'').trim();changed();}
  function action(value){edit();s.action=value;if(value==='cancel'){s.reason='';s.arm='reason';}changed();}
  function step(){
   if(s.pending)return s.pending.step;
   if(['cancel','prepare','post'].includes(s.action))return s.action;
   const m=manifest();if(!m||m.state==='Cancelled')return 'create';
   if(s.action==='loose'&&s.line)return 'loose';
   if(m.state==='Draft')return 'prepare';
   return 'post';
  }
  function ready(){
   if(s.closed||s.loading||s.busy||!s.context||env.owner()!==env.openedOwner)return false;
   if(s.pending)return true;
   if(!['Reviewing','Held'].includes(s.context.review?.state))return false;
   const m=manifest(),next=step();
   if(next==='create')return !!s.route&&!!s.reason&&(!m||m.state==='Cancelled');
   if(next==='cancel')return !s.context.mixed_recovery?.active&&['Draft','Prepared'].includes(m?.state)&&!m.dispatch_command&&!m.dispatch_stock_entry&&!!s.reason;
   if(next==='loose'){const row=m?.lines?.find(row=>row.name===s.line);return m?.state==='Draft'&&!!row&&Number.isFinite(Number(s.qty))&&Number(s.qty)>0&&Math.abs(Number(s.qty)-Number(row.dispatch_qty))<=0.000001;}
   if(next==='prepare')return m?.state==='Draft'&&m.lines?.length>0&&m.lines.every(row=>row.loading_confirmed);
   return m?.state==='Prepared'||!!m?.dispatch_retry_available;
  }
  async function run(next,args){
   const retry=!!s.pending;
   if(!s.pending)s.pending={step:next,method:methods[next],args:{...args,event_token:env.nonce()}};
   try{const result=await env.rpc(s.pending.method,{...s.pending.args,operator_session_token:env.token()});
    if(s.closed)return;if(env.owner()!==env.openedOwner)fail('Identify the original Supervisor, then retry the recorded recovery action.');
    s.pending=null;apply(result);
   }catch(error){const type=error?.exc_type||error?.responseJSON?.exc_type;if(!retry&&type&&type!=='DispatchRecoveryReplayError')s.pending=null;throw error;}
  }
  async function confirm(){
   if(s.busy||s.closed)return;if(!ready())fail('Complete the displayed recovery step before confirming.');
   s.busy=true;changed();
   try{
    if(s.pending)return await run(s.pending.step,s.pending.args);
    const m=manifest(),next=step();let args;
    if(next==='create')args={dispatch_review:s.context.review.name,logistics_route:s.route,reason:s.reason,balance_hash:s.context.balance_hash};
    else if(next==='loose')args={manifest_name:m.name,line_name:s.line,qty:Number(s.qty)};
    else if(next==='cancel')args={manifest_name:m.name,reason:s.reason};
    else args={manifest_name:m.name};
    if(next==='post'){
     const values=await env.inputs(m);if(values===null||s.closed)return;
     if(env.owner()!==env.openedOwner)fail('Identify the original Supervisor before posting.');
     args.required_erp_inputs=JSON.stringify(values);
    }
    await run(next,args);
   }finally{s.busy=false;changed();}
  }
  async function source(value){
   edit();const m=manifest();if(!m||m.state!=='Draft')fail('Create a Draft recovery before scanning its sources.');
   if(s.busy)return;s.busy=true;changed();try{await run('source',{manifest_name:m.name,scan_value:value});}finally{s.busy=false;changed();}
  }
  async function finish(){edit();if(manifest()?.state!=='Received')fail('Post the recovery movement before finishing its Review.');s.closed=true;await env.finish(s.context.plan.name);}
  async function scan(raw){
   const value=String(raw||'').trim(),upper=value.toUpperCase();if(!value||s.closed)return;
   if(upper==='CFG:CMD:CANCEL'){s.closed=true;env.close();return;}
   if(upper==='CFG:CMD:HELP'){s.message='Scan DPL/KDR/KMF. Select route 1–10, RECOVERY_REASON, reason, Confirm. Scan sources; select loose row, CFG:QTY:MATERIAL:n, Confirm. Prepare then Post with Confirm. RECOVERY_CANCEL cancels an unused recovery after a reason; CANCEL only closes. Refresh reads recorded status. After posting use a fresh D3 count and Finish Dispatch Review.';changed();return;}
   if(['CFG:CMD:RECOVERY_CAMERA','CFG:CMD:DISPATCH_REVIEW_CAMERA'].includes(upper))return env.camera();
   if(upper==='CFG:CMD:CONFIRM')return confirm();
   edit();
   if(upper==='CFG:CMD:FINISH_DISPATCH_REVIEW')return finish();
   if(['CFG:CMD:RECOVERY_REFRESH','CFG:CMD:DISPATCH_REVIEW_REFRESH'].includes(upper))return load(manifest()?.name||s.context?.plan.name||'');
   if(['CFG:CMD:RECOVERY_REASON','CFG:CMD:DISPATCH_REVIEW_REASON'].includes(upper)){s.arm='reason';return;}
   if(upper==='CFG:CMD:RECOVERY_SOURCE'){s.arm='source';s.line='';s.qty='';return;}
   if(upper==='CFG:CMD:RECOVERY_CANCEL')return action('cancel');
   if(upper==='CFG:CMD:RECOVERY_PREPARE'){s.line='';return action('prepare');}
   if(upper==='CFG:CMD:RECOVERY_POST')return action('post');
   if(['CFG:CMD:NEXT_MATERIALS','CFG:CMD:PREVIOUS_MATERIALS'].includes(upper)){
    s.page=Math.max(0,Math.min(Math.max(Math.ceil(choices().length/10)-1,0),s.page+(upper.includes('NEXT_')?1:-1)));changed();return;
   }
   const choice=upper.match(/^CFG:SELECT:([1-9]|10)$/);if(choice)return select(Number(choice[1]));
   const quantity=upper.match(/^CFG:QTY:MATERIAL:(.+)$/);if(quantity)return set('qty',quantity[1]);
   if(upper.startsWith('CFG:'))fail('Use a displayed recovery command.');
   if(s.arm){const name=s.arm;s.arm='';return name==='source'?source(value):set(name,value);}
   if(/^(DPL|KDR|KMF)-/i.test(value))return load(value);
   if(!s.context)return load(value);
   return source(value);
  }
  return {state:s,load,set,select,choices,step,ready,action,source,confirm,finish,scan};
 }
 function erpFields(requirements){return requirements.map((row,index)=>({fieldname:`recovery_erp_${index}`,label:row.label,fieldtype:row.scope==='table'?'Table':row.fieldtype,
  options:row.options,reqd:1,default:row.default,...(row.scope==='table'?{data:row.default||[],in_place_edit:true,fields:(row.fields||[]).map(column=>({...column,in_list_view:1,columns:2}))}:{})}));}
 function erpValues(requirements,values){const result={parent:{},tables:{}};requirements.forEach((row,index)=>{
  const value=values[`recovery_erp_${index}`];if(row.scope==='table')result.tables[row.fieldname]=value||[];
  else if(row.scope==='parent')result.parent[row.fieldname]=value;
  else{result.tables[row.table_field]??=[];result.tables[row.table_field][row.row_index]??={};result.tables[row.table_field][row.row_index][row.fieldname]=value;}
 });return result;}
 async function open(options){
  const f=options.frappe,e=f.utils.escape_html,openedOwner=options.owner();let dialog,controller,camera=null,child=null,childDialog=null,nextAction=null,renderedContext=null,renderedLine=null,renderedAction=null,tail=Promise.resolve();
  const focus=()=>{if(child)return child.focus();if(!controller.state.closed)dialog.fields_dict.scan.$input.focus();};
  function queue(work){tail=tail.then(work).catch(error=>{controller.state.message=options.errorMessage(error,error.message||'Recovery failed.');render(controller.state);}).finally(focus);return tail;}
  function stopCamera(){const old=camera;camera=null;old?.hide_dialog?.();}
  function startCamera(){
   if(camera||controller.state.closed)return;if(!f.ui.Scanner)throw new Error('Camera scanning is unavailable; use the Scanner field.');
   let accepted=false;camera=new f.ui.Scanner({dialog:true,multiple:false,on_scan:data=>{if(accepted||controller.state.closed)return;accepted=true;const value=String(data.decodedText||'').trim();stopCamera();if(value)queue(()=>controller.scan(value));}});
   const instance=camera;camera.dialog?.$wrapper?.one('hidden.bs.modal',()=>{accepted=true;if(camera===instance)camera=null;focus();});
  }
  async function inputs(manifest){
   const response=await f.call({method:'cfg_kanban.api.logistics.get_dispatch_requirements',args:{manifest_name:manifest.name,operator_session_token:options.token()}});
   if(controller.state.closed||options.owner()!==openedOwner)return null;
   const requirements=response.message.fields||[];if(!requirements.length)return {};
   await f.require('/assets/cfg_kanban/js/delivery_action_scanner.js');
   if(controller.state.closed||options.owner()!==openedOwner)return null;
   return new Promise(resolve=>{
    const fields=erpFields(requirements);let collected=null;
    childDialog=new f.ui.Dialog({title:'Recovery Stock Entry Details',fields:[...root.cfg_delivery_action_scanner.fields(),...fields]});
    child=root.cfg_delivery_action_scanner.bind({frappe:f,dialog:childDialog,fields:fields.map(row=>({...row,name:row.fieldname})),
     owner:options.owner,nonce:options.nonce,errorMessage:options.errorMessage,label:'Use Reviewed ERP Details',
     submit:async values=>{collected=erpValues(requirements,values);},success:async()=>{},
     onClose:()=>{child=null;childDialog=null;resolve(collected);focus();}});
   });
  }
  function render(s){
   const m=s.context?.recovery_manifest,active=m&&m.state!=='Cancelled';
   const rows=(m?.lines||[]).map(row=>`<tr class="${row.loading_confirmed?'text-success':'text-danger'}"><td>${e(row.item_code)} / ${e(row.batch_no||'No Batch')}</td><td>${e(row.container_visible_code||row.visible_code||'ERP stock')}</td><td>${row.dispatch_qty} ${e(row.stock_uom)}</td><td>${row.loading_confirmed?'Confirmed':'Scan / confirm quantity'}</td></tr>`).join('');
   const choices=controller.choices().slice(s.page*10,s.page*10+10).map((row,index)=>`<button type="button" class="btn btn-default btn-block text-left recovery-choice" data-number="${index+1}">${index+1}. ${e(active?`${row.item_code} / ${row.batch_no||'No Batch'} · ${row.dispatch_qty} ${row.stock_uom}`:`${row.name} → ${row.destination_warehouse} · ${row.action}`)}${[s.route,s.line].includes(row.name)?' ✓':''}</button>`).join('');
   dialog.fields_dict.summary.$wrapper.html(`<div class="alert ${controller.ready()?'alert-success':'alert-warning'}">${e(s.message)}</div><p>${e(s.context?.plan.name||'')} · ${e(s.context?.review.name||'')} · ${e(m?.name||'')} · ${e(m?.state||'')}</p><p>${e(m?.source_warehouse||s.context?.plan.vehicle_warehouse||'')} → ${e(m?.destination_warehouse||'Select a route')}</p><p>${e(s.route)} · ${e(s.reason)}</p>${s.line?`<p>Counted loose quantity: <strong>${e(s.qty||'Enter quantity')}</strong></p>`:''}${m?`<table class="table table-bordered"><tr><th>Item / Batch</th><th>Physical source</th><th>Quantity</th><th>Ready</th></tr>${rows}</table>`:''}${choices}<p>Page ${s.page+1}; numbered choices 1–10. ${active?'Select a loose row, enter its exact counted quantity, then Confirm.':'Choose the approved route explicitly.'}</p>${s.pending?`<div class="alert alert-warning">Retry original action: ${e(JSON.stringify(s.pending.args))}</div>`:''}${m?.dispatch_stock_entry?`<p>Stock Entry: <a class="recovery-entry" href="#">${e(m.dispatch_stock_entry)}</a> · ${e(m.dispatch_document_status||'Read ERP status')}</p>`:''}`);
   dialog.fields_dict.summary.$wrapper.find('.recovery-choice').on('click',function(){queue(()=>controller.select(Number(this.dataset.number)));});
   dialog.fields_dict.summary.$wrapper.find('.recovery-entry').on('click',event=>{event.preventDefault();f.set_route('Form','Stock Entry',m.dispatch_stock_entry);});
   if(renderedContext!==s.context||renderedLine!==s.line||renderedAction!==s.action){
    renderedContext=s.context;renderedLine=s.line;renderedAction=s.action;
    for(const name of ['reason','qty'])if(String(dialog.get_value(name)||'')!==s[name])dialog.set_value(name,s[name]);
   }
   dialog.set_df_property?.('reason','hidden',active&&s.action!=='cancel'?1:0);
   dialog.set_df_property?.('qty','hidden',s.line?0:1);
   dialog.set_df_property?.('finish','hidden',m?.state==='Received'?0:1);
   if(controller.ready())dialog.enable_primary_action();else dialog.disable_primary_action();
   const labels={create:'Create Recovery Checklist',loose:'Confirm Counted Loose Quantity',prepare:'Prepare and Reserve',post:m?.auto_submit_internal_dispatch?'Post Recovery Movement':'Create Recovery Draft',cancel:'Cancel Unused Recovery',source:'Retry Source Confirmation'};
   dialog.get_primary_btn?.().text(labels[controller.step()]||'Confirm');
  }
  dialog=new f.ui.Dialog({title:'Return / Transfer Dispatch Leftovers',size:'extra-large',fields:[
   {fieldname:'scan',label:'Scanner',fieldtype:'Data'},
   {fieldname:'camera',label:'Scan with Camera',fieldtype:'Button',click:()=>queue(startCamera)},
   {fieldname:'summary',fieldtype:'HTML'},
   {fieldname:'previous',label:'Previous Choices',fieldtype:'Button',click:()=>queue(()=>controller.scan('CFG:CMD:PREVIOUS_MATERIALS'))},
   {fieldname:'next',label:'Next Choices',fieldtype:'Button',click:()=>queue(()=>controller.scan('CFG:CMD:NEXT_MATERIALS'))},
   {fieldname:'reason',label:'Supervisor Reason',fieldtype:'Small Text',onchange:()=>{const value=dialog.get_value('reason');if(String(value??'')!==controller.state.reason)return queue(()=>controller.set('reason',value));}},
   {fieldname:'qty',label:'Physically Counted Loose Quantity',fieldtype:'Data',onchange:()=>{const value=dialog.get_value('qty');if(String(value??'')!==controller.state.qty)return queue(()=>controller.set('qty',value));}},
   {fieldname:'prepare',label:'Prepare Confirmed Sources',fieldtype:'Button',click:()=>queue(()=>controller.action('prepare'))},
   {fieldname:'post',label:'Post / Create ERP Movement',fieldtype:'Button',click:()=>queue(()=>controller.action('post'))},
   {fieldname:'cancel_recovery',label:'Cancel Unused Recovery',fieldtype:'Button',click:()=>queue(()=>controller.action('cancel'))},
   {fieldname:'refresh',label:'Refresh Recorded Recovery',fieldtype:'Button',click:()=>queue(()=>controller.scan('CFG:CMD:RECOVERY_REFRESH'))},
   {fieldname:'finish',label:'Finish Review After Fresh Count',fieldtype:'Button',click:()=>queue(()=>controller.finish())},
  ],primary_action_label:'Confirm Recovery Step',primary_action:()=>queue(()=>controller.confirm())});
  controller=createController({owner:options.owner,openedOwner,token:options.token,nonce:options.nonce,render,camera:startCamera,inputs,
   rpc:async(method,args)=>(await f.call({method:'cfg_kanban.services.dispatch_recovery.'+method,args})).message,
   close:()=>dialog.hide(),finish:plan=>{nextAction=()=>options.finish(plan);dialog.hide();}});
  dialog.onhide=()=>{controller.state.closed=true;stopCamera();childDialog?.hide();options.onClose();nextAction?.();};
  dialog.fields_dict.scan.$input.on('keydown',event=>{
   if(!['Enter','Tab'].includes(event.key)||event.shiftKey||event.ctrlKey||event.altKey||event.metaKey||event.isComposing)return;
   const value=String(dialog.get_value('scan')||'').trim();if(event.key==='Tab'&&!value)return;
   event.preventDefault();event.stopPropagation();dialog.set_value('scan','');if(value)queue(()=>controller.scan(value));
  });
  dialog.show();render(controller.state);focus();if(options.planScan)await queue(()=>controller.load(options.planScan));
  return controller.state.closed?null:{scan:value=>child?child.scan(value):queue(()=>controller.scan(value)),focus,controller,close:()=>dialog.hide()};
 }
 const api={createController,open,erpFields,erpValues};if(typeof module!=='undefined'&&module.exports)module.exports=api;
 root.cfg_dispatch_recovery=api;
})(typeof window==='undefined'?globalThis:window);
