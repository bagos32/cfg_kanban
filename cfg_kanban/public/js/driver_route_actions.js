/* Durable driver action identity; native delivery/proof services remain the posting owners. */
(function(root){
 'use strict';
 const prefix='cfg_kanban.services.driver_route_actions.';
 const actions=['Start Route','Begin Delivery','Confirm Allocations','Create Delivery Note','Open Proof','Submit Proof','Complete Stop'];
 function controller(env){
  const s={trip:null,pending:null,busy:false,closed:false,baseline:null,message:''};
  const fail=text=>{throw new Error(text);};
  const changed=()=>{if(!s.closed)env.render(s);};
  const key=()=> 'cfg_driver_action:'+s.trip;
  const mark=value=>value ? JSON.stringify(value) : null;
  function read(){const raw=env.storage.getItem(key());if(!raw)return null;let value;
   try{value=JSON.parse(raw);}catch(_){fail('Pending driver request is unreadable; ask a Supervisor to reconcile it.');}
   if(value.v!==1||value.trip!==s.trip||!value.id||!value.actor||!value.request||!actions.includes(value.request.action)||value.request.trip_name!==s.trip||value.request.event_token!==value.id||!['Pending','Recorded','Rejected','Voided'].includes(value.status))fail('Pending driver request is invalid; reconcile this terminal.');
   return value;
  }
  function settled(value,status){return {v:1,trip:value.trip,actor:value.actor,id:value.id,attempts:value.attempts,status,
   request:{trip_name:value.trip,action:value.request.action,event_token:value.id}};}
  function write(value){env.storage.setItem(key(),JSON.stringify(value));s.baseline=mark(value);}
  function restore(trip){s.trip=trip;const value=read();s.pending=value?.status==='Pending'?value:null;s.baseline=mark(value);changed();return value;}
  function actor(){if(!env.owner()||!env.token())fail('Identify an operator before executing the route.');}
  async function exclusive(work){if(!env.locks?.request)fail('Driver actions require HTTPS, browser storage and Web Locks.');return env.locks.request(key(),work);}
  function loaded(){const value=read();if(mark(value)!==s.baseline)fail('Another tab changed this driver action. Refresh and review its current outcome first.');return value;}
  async function send(value,retry){
   actor();if(value.actor!==env.owner())fail('Identify the original operator before retrying this driver action.');
   value.attempts=(value.attempts||0)+1;write(value);s.pending=value;s.baseline=mark(value);changed();
   try{
    const result=await env.rpc(prefix+'perform_driver_action',{...value.request,operator_session_token:env.token()});
    if(result.status!=='Recorded')fail('Driver result was not confirmed; reconcile the original request.');
    const saved=settled(value,'Recorded');write(saved);s.pending=null;s.baseline=mark(saved);
    if(!s.closed&&value.actor===env.owner()){try{await env.success(result);}catch(error){s.message='Action recorded. Refresh the page to continue.';}}
    return result;
   }catch(error){
    const type=error?.exc_type||error?.responseJSON?.exc_type;
    if(!retry&&type&&type!=='DriverActionConflict'){
     const saved=settled(value,'Rejected');write(saved);s.pending=null;s.baseline=mark(saved);
    }
    throw error;
   }finally{changed();}
  }
  async function run(work){if(s.busy||s.closed)return;s.busy=true;changed();try{return await exclusive(work);}finally{s.busy=false;changed();}}
  return {state:s,restore,
   async mutate(context,action,payload={}){return run(async()=>{actor();loaded();if(s.pending)fail('Retry or reconcile the original request before entering new details.');
    const id=env.nonce();const value={v:1,trip:s.trip,actor:env.owner(),status:'Pending',id,attempts:0,
     request:{trip_name:s.trip,action,event_token:id,expected_revision:context.revision,scope_hash:context.scope_hash,
       stop_key:context.stop_key||null,dispatch_plan:context.dispatch_plan||null,payload:JSON.parse(JSON.stringify(payload))}};
    if(!actions.includes(action))fail('Unsupported driver action.');write(value);s.pending=value;s.baseline=mark(value);return send(value,false);});},
   async retry(){return run(async()=>{const saved=loaded();if(!saved||saved.status!=='Pending')fail('No original driver request is pending.');return send(saved,true);});},
   async reconcile(reason){return run(async()=>{actor();const saved=loaded();if(!saved||saved.status!=='Pending')fail('No driver request needs reconciliation.');
    const result=await env.rpc(prefix+'reconcile_driver_action',{...saved.request,request_actor:saved.actor,void_reason:reason||null,operator_session_token:env.token()});
    if(['Recorded','Voided'].includes(result.status)){const recorded=settled(saved,result.status);write(recorded);s.pending=null;s.baseline=mark(recorded);if(!s.closed)await env.success(result);}
    else s.message='No result is recorded yet. Keep the original request; retry it or ask a Supervisor to void it with a reason.';
    changed();return result;});},
   close(){s.closed=true;},
  };
 }

 function open(options){
  const f=options.frappe,e=f.utils.escape_html,host=options.host,tr=value=>typeof __==='function'?__(value):value;
  const owner=options.owner(),token=options.token();
  let context=null,inputs={},inputScanner=null,camera=null,cameraVersion=0,closed=false,loading=false,tools=null,epoch=0,arrival='',automatic=false;
  let tail=Promise.resolve();
  const valid=()=>!closed&&options.owner()===owner&&options.token()===token&&options.active();
  const focus=()=>{if(valid())host.find('.driver-action-scan').trigger('focus');};
  const rpc=async(method,args)=>(await f.call({method,args})).message;
  function queue(work){tail=tail.then(work).catch(async error=>{if(valid()){host.find('.driver-action-message').text(options.error(error));automatic=false;}}).finally(focus);return tail;}
  function stopCamera(){cameraVersion++;camera?.stop_scan?.();camera?.hide_dialog?.();camera?.dialog?.hide?.();camera=null;}
  async function load(){
   if(!valid()||loading||c.state.pending)return;loading=true;const version=++epoch;
   try{const next=await rpc(prefix+'driver_action_context',{trip_name:options.trip,stop_key:options.stop||null,operator_session_token:options.token()});if(!valid()||version!==epoch)return;context=next;render();}
   finally{loading=false;update();focus();}
  }
  async function recorded(result){
   if(!valid())return;await options.refresh();if(!valid())return;
   if(result.action==='Start Route'){close();return;}
   await load();if(!valid())return;
   if(context?.next_step==='Done'){close();return;}
   const auto=context&&(['Confirm Allocations','Open Proof'].includes(context.next_step)||
    (context.next_step==='Create Delivery Note'&&!(context.requirements?.fields||[]).length)||
    (context.next_step==='Begin Delivery'&&(!context.require_scan||arrival)));
   if(automatic&&auto&&result.status!=='Voided')setTimeout(()=>{if(valid())queue(()=>submit(true));},0);
  }
  const c=controller({storage:options.storage,locks:options.locks,owner:options.owner,token:options.token,nonce:options.nonce,rpc,render:update,success:recorded});
  function update(){
   if(!valid())return;const pending=c.state.pending,own=!pending||pending.actor===owner;
   host.find('.driver-action-confirm').text(tr(pending?'Retry original request':context?.next_step==='Start Route'?'Start Route':context?.next_step==='Submit Proof'?'Submit delivery proof':context?.next_step==='Create Delivery Note'?'Confirm document details':'Complete Stop'))
    .prop('disabled',c.state.busy||loading||!own||(!pending&&(!context||['Blocked','Await ERP','Done'].includes(context.next_step))));
   host.find('.driver-action-fields :input').prop('disabled',c.state.busy||Boolean(pending));
   host.find('.driver-action-readback').toggle(true).prop('disabled',c.state.busy);
   host.find('.driver-action-void,.driver-action-void-reason').toggle(Boolean(pending)&&options.supervisor());
   if(pending){stopCamera();host.find('.driver-action-message').text(own?`Original ${pending.request.action} retained. Retry uses the same details. ${c.state.message}`:'Another operator has an unresolved request. Reidentify that operator or use authorized Supervisor reconciliation.');}
   else if(c.state.message)host.find('.driver-action-message').text(c.state.message);
  }
  function field(df){const parent=$('<div class="mt-3"></div>').appendTo(host.find('.driver-action-fields'));
   const control=f.ui.form.make_control({parent,df,render_input:true});if(df.default!==undefined)control.set_value(df.default);inputs[df.fieldname]=control;return control;}
  function values(){return Object.fromEntries(Object.entries(inputs).filter(([_key,control])=>control.get_value).map(([key,control])=>[key,control.get_value()]));}
  function render(){
   if(!valid())return;tools?.close?.();tools=null;inputs={};inputScanner=null;
   const detail=options.detail(),stop=(detail?.stops||[]).find(row=>row.stop_key===(c.state.pending?c.state.pending.request.stop_key:context?.stop_key||options.stop));
   const pending=c.state.pending,owned=!pending||pending.actor===owner;
   host.html(`<section class="frappe-card p-4 mt-3 driver-action-panel"><h3>${tr('Driver route action')}</h3><div class="driver-action-summary"></div>
    <div class="driver-action-message alert alert-info" role="status"></div><div class="driver-action-fields"></div><div class="driver-action-input-help text-muted"></div>
    <div class="driver-action-scanner mt-3"><input class="form-control driver-action-scan" autocomplete="off" placeholder="${tr('Scanner: Customer Site, field value or Confirm')}"><button class="btn btn-default driver-action-camera">${tr('Scan with Camera')}</button></div>
    <div class="driver-action-controls mt-3"><button class="btn btn-primary driver-action-confirm"></button><button class="btn btn-default driver-action-readback">${tr('Check saved outcome / Refresh')}</button>
    <input class="form-control driver-action-void-reason" placeholder="${tr('Supervisor reason to void an unrecorded request')}"><button class="btn btn-warning driver-action-void">${tr('Void if unrecorded')}</button><button class="btn btn-default driver-action-cancel">${tr('Close')}</button></div></section>`);
   if(owned)host.find('.driver-action-summary').html(stop?`<h4>${e(stop.site_name||stop.customer_name)}</h4><p>${e(stop.address||'')}</p>`+
    stop.items.map(row=>`<div><strong>${e(row.item_code)}</strong> · ${e(row.planned_qty)} ${e(row.stock_uom)} ${e(row.orders.map(order=>order.sales_order).join(', '))}</div>`).join(''):
    `<h4>${e(detail?.trip?.trip_title||options.trip)}</h4><p>${tr('Start this loaded route. This records departure; it creates no customer Delivery Note.')}</p>`);
   if(pending){update();return;}
   const step=context?.next_step;
   host.find('.driver-action-message').text(context?.message||(!context?tr('Loading current action…'):step==='Begin Delivery'?tr('Confirm the full prepared quantities for this customer. The Delivery Note follows the configured Draft or auto-submit policy; required proof remains mandatory.'):step));
   if(step==='Begin Delivery'&&context.require_scan)field({fieldname:'customer_scan',label:tr('Required Customer Site QR'),fieldtype:'Data',reqd:1,default:arrival});
   if(step==='Create Delivery Note')for(const df of window.cfg_dispatch_recovery.erpFields(context.requirements?.fields||[]))field(df);
   if(step==='Submit Proof'){
    const proof=context.proof;
    host.find('.driver-action-message').text([proof.proof_policy,proof.require_signature?tr('Signature required'):null,proof.require_photo?tr('Photo required'):null,proof.require_gps?tr('GPS required'):null].filter(Boolean).join(' · '));
    field({fieldname:'disposition',label:tr('Proof disposition'),fieldtype:'Select',options:proof.allowed_dispositions.join('\n'),default:proof.allowed_dispositions[0],reqd:1});
    field({fieldname:'recipient_name',label:tr('Recipient name'),fieldtype:'Data'});field({fieldname:'unattended_reason',label:tr('Unattended reason'),fieldtype:'Small Text'});field({fieldname:'notes',label:tr('Notes'),fieldtype:'Small Text'});
    field({fieldname:'evidence',fieldtype:'HTML',options:window.cfg_delivery_proof_tools.evidenceHTML()});field({fieldname:'signature',fieldtype:'HTML',options:window.cfg_delivery_proof_tools.signatureHTML()});
    tools=window.cfg_delivery_proof_tools.bind({frappe:f,proof,field:name=>inputs[name],token:()=>options.token(),valid:()=>valid()&&!c.state.busy&&!c.state.pending,nonce:options.nonce,error:options.error});
   }
   if(step==='Complete Stop'&&context.purpose==='Visit Only')field({fieldname:'notes',label:tr('Visit information / notes'),fieldtype:'Small Text'});
   if(step==='Await ERP'&&context.delivery_note)host.find('.driver-action-fields').html(`<p>${tr('Awaiting authorized ERP submission')}: ${e(context.delivery_note)}. ${tr('Refresh after submission; this stop stays open.')}</p>`);
   const defs=Object.entries(inputs).filter(([_name,control])=>!['HTML','Section Break','Column Break'].includes(control.df.fieldtype)).map(([name,control])=>({...control.df,name}));
   inputScanner=window.cfg_delivery_action_scanner.createController({fields:defs,owner:options.owner,openedOwner:owner,render:s=>{
     const choices=inputScanner?.choices()||defs;
     host.find('.driver-action-input-help').text((s.table?`${s.table.label} · Row ${s.table.index+1}. `:'')+
      choices.slice(s.page*10,s.page*10+10).map((row,index)=>`${index+1}. ${row.label||row.name}${(s.table?s.table.column:s.field)===row.name?' ✓':''}`).join(' · '));
    },nonce:options.nonce,values,
    set:(name,value)=>inputs[name].set_value(value),read:name=>inputs[name].get_value(),submit:async()=>submit(),close:()=>{},success:async()=>{},camera:startCamera});
   host.find('.driver-action-input-help').text(defs.map((row,index)=>`${index+1}. ${row.label||row.name}`).join(' · '));
   update();focus();
  }
  async function submit(auto=false){
   if(!valid())throw new Error('Operator changed; reopen this driver action.');if(c.state.pending)return c.retry();
   if(!context||['Blocked','Await ERP','Done'].includes(context.next_step))return;
   if(tools?.busy?.())throw new Error('Wait until proof evidence has finished uploading.');
   let payload={},v=values(),step=context.next_step;
   if(!auto)automatic=step!=='Start Route';
   if(step==='Begin Delivery'){arrival=String(v.customer_scan||arrival||'').trim();if(context.require_scan&&!arrival)throw new Error('Scan the required Customer Site before confirmation.');payload.customer_scan=arrival||null;}
   if(step==='Create Delivery Note')payload.required_erp_inputs=window.cfg_dispatch_recovery.erpValues(context.requirements?.fields||[],v);
   if(step==='Submit Proof'){
    const location=context.proof.require_gps&&v.disposition!=='No Proof Recorded'?await window.cfg_delivery_proof_tools.geotag():null;
    if(!valid())throw new Error('Operator changed; reopen the proof.');
    payload={proof_name:context.proof.name,disposition:v.disposition,recipient_name:v.recipient_name||'',unattended_reason:v.unattended_reason||'',notes:v.notes||'',latitude:location?.latitude??null,longitude:location?.longitude??null,location_accuracy:location?.accuracy??null};
   }
   if(step==='Complete Stop'&&context.purpose==='Visit Only')payload.notes=v.notes||'';
   await c.mutate(context,step,payload);
  }
  async function scan(value){
   const text=String(value||'').trim(),upper=text.toUpperCase();if(!text||!valid())return;
   if(upper==='CFG:CMD:CANCEL')return close();if(upper==='CFG:CMD:CONFIRM')return submit();
   if(['CFG:CMD:REFRESH','CFG:CMD:ROUTE_SHEET_REFRESH'].includes(upper))return c.state.pending?c.reconcile():load();
   if(upper==='CFG:CMD:HELP'){host.find('.driver-action-message').text('Confirm submits reviewed details. Scan Customer Site when required. CFG:SELECT:1–10 arms a field; scan its value. DELIVERY_RECIPIENT and ERP table-row commands are supported. Cancel closes while retaining unknown results. Refresh reads back the saved outcome.');return;}
   if(c.state.pending)throw new Error('Retry or reconcile the original request before editing.');
   if(context?.next_step==='Begin Delivery'&&context.require_scan&&!upper.startsWith('CFG:')){await inputs.customer_scan.set_value(text);return;}
   return inputScanner?.scan(text);
  }
  function startCamera(){if(camera||closed)return;if(!f.ui.Scanner)throw new Error('Camera unavailable; use the Scanner field.');const version=cameraVersion;let accepted=false;
   camera=new f.ui.Scanner({dialog:true,multiple:false,on_scan:data=>{if(accepted||version!==cameraVersion||!valid())return;accepted=true;stopCamera();queue(()=>scan(data.decodedText));}});camera.dialog?.$wrapper?.one?.('hidden.bs.modal.cfg_driver_action',()=>{cameraVersion++;camera=null;focus();});}
  function close(){if(closed)return;closed=true;epoch++;c.close();tools?.close?.();stopCamera();host.empty();options.onClose();}
  host.off('.cfg_driver_action').on('click.cfg_driver_action','.driver-action-confirm',()=>queue(submit))
   .on('click.cfg_driver_action','.driver-action-readback',()=>queue(()=>c.state.pending?c.reconcile():load()))
   .on('click.cfg_driver_action','.driver-action-camera',()=>queue(startCamera)).on('click.cfg_driver_action','.driver-action-cancel',close)
   .on('click.cfg_driver_action','.driver-action-void',()=>queue(async()=>{const reason=String(host.find('.driver-action-void-reason').val()||'').trim();if(!reason)throw new Error('Enter the Supervisor reason first.');await c.reconcile(reason);} ))
   .on('keydown.cfg_driver_action','.driver-action-scan',event=>{if(!['Enter','Tab'].includes(event.key)||event.shiftKey||event.ctrlKey||event.altKey||event.metaKey||event.isComposing)return;const input=host.find('.driver-action-scan'),value=String(input.val()||'').trim();if(!value)return;event.preventDefault();event.stopPropagation();input.val('');queue(()=>scan(value));});
  c.restore(options.trip);render();if(!c.state.pending)queue(load);
  return {scan:value=>queue(()=>scan(value)),close,focus,controller:c,refresh:()=>queue(()=>c.state.pending?c.reconcile():load())};
 }
 const api={controller,open};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.cfg_driver_route_actions=api;
})(typeof window==='undefined'?globalThis:window);
