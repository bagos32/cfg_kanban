/* Durable driver action identity; native delivery/proof services remain the posting owners. */
(function(root){
 'use strict';
 const prefix='cfg_kanban.services.driver_route_actions.';
 const actions=['Create Sales Invoice','Create Custody Label','Prepare Mobile Print','Record Print Segment','Close Mobile Print','Request Stop Cancellation','Cancel Customer Stop','Release GPS','Start GPS','Start Route','Begin Delivery','Confirm Allocations','Create Delivery Note','Open Proof','Submit Proof','Complete Stop','Collect Old Return','Release Refused Stock','Begin Open Sale','Add Assistant','Change Route Order','Request Route Change','Cancel Route Change','Decide Route Change'];
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

 function stopOrder(stops){
  const rows=stops.map(row=>({...row}));
  function shift(key,delta){const index=rows.findIndex(r=>r.stop_key===key),next=index+delta;if(index<0)throw new Error('Select a current customer stop.');if(next<0||next>=rows.length)return;rows.splice(next,0,rows.splice(index,1)[0]);}
  return {list:()=>rows.map(r=>({...r})),keys:()=>rows.map(r=>r.stop_key),shift,
   move(key,target){const from=rows.findIndex(r=>r.stop_key===key),to=rows.findIndex(r=>r.stop_key===target);if(from<0||to<0)throw new Error('Select a current customer stop.');rows.splice(to,0,rows.splice(from,1)[0]);}};
 }
 function cancellationSummary(setup){
  const data=setup?.target||{},e=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
  return `<div class="alert alert-warning"><strong>${e(data.sequence)}. ${e(data.site_name||data.customer)}</strong><p>${e(data.address)}</p><p>Cancel this visit only. The Sales Order stays outstanding. Loaded goods stay on the lorry; no DN, credit or stock transfer is created.</p>${(data.orders||[]).map(row=>`<div>${e(row.sales_order)} / ${e(row.customer_po||'—')} · ${e(row.item_code)} · ${e(row.planned_qty)} ${e(row.stock_uom)}</div>`).join('')}${(data.plans||[]).map(plan=>`<div class="mt-2"><strong>${e(plan.name)} · ${e(plan.state)}</strong><div>${e(plan.vehicle_warehouse||plan.source_warehouse||'')}</div>${(plan.sources||[]).map(row=>`<div>${e(row.visible_code||'Untagged ERP stock')} · ${e(row.item_code)} · ${e(row.qty)} ${e(row.stock_uom)} · Batch ${e(row.batch_no||'—')} · Expiry ${e(row.expiry_date||'—')}</div>`).join('')}</div>`).join('')}${setup?.message?`<p>${e(setup.message)}</p>`:''}</div>`;
 }
 function open(options){
  const f=options.frappe,e=f.utils.escape_html,host=options.host,tr=value=>typeof __==='function'?__(value):value;
  const owner=options.owner(),token=options.token();
  let context=null,inputs={},inputScanner=null,camera=null,cameraVersion=0,closed=false,loading=false,tools=null,epoch=0,arrival='',automatic=false,returnReview=null,quantityReview=null;
  let stockChild=null,routeOrder=null,routeSelected=null,draggedStop=null,routePage=0;
  let tail=Promise.resolve();
  const valid=()=>!closed&&options.owner()===owner&&options.token()===token&&options.active();
  const focus=()=>{if(stockChild)return stockChild.focus();if(valid())host.find('.driver-action-scan').trigger('focus');};
  const rpc=async(method,args)=>(await f.call({method,args})).message;
  function queue(work){tail=tail.then(work).catch(async error=>{if(valid()){host.find('.driver-action-message').text(options.error(error));automatic=false;}}).finally(focus);return tail;}
  function stopCamera(){cameraVersion++;camera?.stop_scan?.();camera?.hide_dialog?.();camera?.dialog?.hide?.();camera=null;}
  async function load(){
   if(!valid()||loading||c.state.pending)return;
   if(quantityReview||returnReview)throw new Error('Return to Edit before refreshing an unsubmitted review.');
   loading=true;const version=++epoch;
   try{const next=await rpc(prefix+'driver_action_context',{trip_name:options.trip,stop_key:options.stop||null,operation:options.operation||null,outcome_name:options.outcome||null,operator_session_token:options.token()});if(!valid()||version!==epoch)return;context=next;render();}
   finally{loading=false;update();focus();}
  }
  async function recorded(result){
   if(['Begin Delivery','Begin Open Sale'].includes(result.action)){quantityReview=null;}
   if(!valid())return;await options.refresh();if(!valid())return;
   options.recorded?.(result);
   if(['Request Stop Cancellation','Cancel Customer Stop','Start Route','Collect Old Return','Release Refused Stock','Add Assistant','Change Route Order','Request Route Change','Cancel Route Change','Decide Route Change'].includes(result.action)){close();return;}
   await load();if(!valid())return;
   if(context?.next_step==='Done'){close();return;}
   const auto=context&&(['Confirm Allocations','Open Proof'].includes(context.next_step)||
    (context.next_step==='Create Delivery Note'&&!(context.requirements?.fields||[]).length)||
    (context.next_step==='Begin Delivery'&&(!context.require_scan||arrival)));
   if(automatic&&auto&&result.status!=='Voided')setTimeout(()=>{if(valid())queue(()=>submit(true));},0);
  }
  const c=controller({storage:options.storage,locks:options.locks,owner:options.owner,token:options.token,nonce:options.nonce,rpc,render:update,success:recorded});
  function packSummary(packs){return packs.map(p=>`<div class="alert ${p.state==='Scanned'?'alert-success':'alert-warning'}"><strong>${e(p.name)} · ${e(p.state)}</strong>${p.lines.map(r=>`<div>${e(r.item_code)} / ${e(r.batch_no||'—')} · ${e(r.qty)} ${e(r.stock_uom)} · ${e(r.source_visible_code)}</div>`).join('')}</div>`).join('');}
  function update(){
   if(!valid())return;const pending=c.state.pending,own=!pending||pending.actor===owner;
   host.find('.driver-action-confirm').text(tr(pending?'Retry original request':context?.next_step==='Done'?'Recorded':context?.next_step==='Request Stop Cancellation'?'Request Supervisor Cancellation':context?.next_step==='Cancel Customer Stop'?'Cancel This Customer Stop':context?.next_step==='Start Route'?'Start Route':context?.next_step==='Edit Route Order'?(context.setup.enforced?'Request Supervisor Approval':'Save Stop Order'):context?.next_step==='Decide Route Change'?'Record Route Decision':context?.next_step==='Cancel Route Change'?'Cancel Route Request':context?.next_step==='Add Assistant'?'Add Assistant Driver':context?.next_step==='Collect Old Return'?(returnReview?'Issue Temporary Return Note':'Review Collected Return'):context?.next_step==='Release Refused Stock'?'Release Selected Refused Stock':context?.next_step==='Submit Proof'?'Submit delivery proof':context?.next_step==='Begin Open Sale'?'Open Customer Sale':context?.next_step==='Select Route Stock'?'Finish Selection / Create DN':context?.next_step==='Create Delivery Note'?'Confirm document details':context?.next_step==='Begin Delivery'?(quantityReview?'Confirm Accepted / Refused':'Deliver Accepted Quantities'):'Complete Stop'))
    .prop('disabled',c.state.busy||loading||!own||(!pending&&(context?.loose_tags||[]).some(p=>p.state!=='Scanned'))||(!pending&&(!context||['Blocked','Await ERP','Done'].includes(context.next_step)||(context.next_step==='Select Route Stock'&&!(context.selected_stock||[]).some(r=>['Reserved','Delivery Pending'].includes(r.state))))));
   host.find('.driver-action-fields :input').prop('disabled',c.state.busy||Boolean(pending)||Boolean(returnReview)||Boolean(quantityReview));
   host.find('.driver-order-row').attr?.('draggable',!(c.state.busy||pending));
   host.find('.driver-action-readback').toggle(true).prop('disabled',c.state.busy);
   host.find('.driver-action-void,.driver-action-void-reason').toggle(Boolean(pending)&&options.supervisor());
   if(pending){stopCamera();host.find('.driver-action-message').text(own?`Original ${pending.request.action} retained. Retry uses the same details. ${c.state.message}`:'Another operator has an unresolved request. Reidentify that operator or use authorized Supervisor reconciliation.');}
   else if(c.state.message)host.find('.driver-action-message').text(c.state.message);
  }
  function field(df){const parent=$('<div class="mt-3"></div>').appendTo(host.find('.driver-action-fields'));
   const control=f.ui.form.make_control({parent,df,render_input:true});if(df.default!==undefined)control.set_value(df.default);inputs[df.fieldname]=control;return control;}
  function valueOf(control){return control.df.fieldtype==='Table'?(control.grid?.get_data?.()||control.get_value?.()||control.df.data||[]):control.get_value?.();}
  function values(){return Object.fromEntries(Object.entries(inputs).filter(([_key,control])=>control.get_value||control.df.fieldtype==='Table').map(([key,control])=>[key,valueOf(control)]));}

  function orderEditable(){if(!valid()||c.state.busy||c.state.pending||context?.next_step!=='Edit Route Order')throw new Error('Finish the original route request before changing its order.');}
  function drawOrder(){
   if(!routeOrder)return;const rows=routeOrder.list();
   host.find('.driver-order-list').html(rows.map((row,index)=>`<div class="driver-order-row p-2 border mb-2${row.stop_key===routeSelected?' bg-light':''}" draggable="true" data-order-key="${e(row.stop_key)}"><strong>${index+1}. ${e(row.label)}</strong> · ${e(row.customer)} <button type="button" class="btn btn-default btn-sm driver-order-up" data-order-key="${e(row.stop_key)}"${index===0?' disabled':''}>↑ ${tr('Up')}</button> <button type="button" class="btn btn-default btn-sm driver-order-down" data-order-key="${e(row.stop_key)}"${index===rows.length-1?' disabled':''}>↓ ${tr('Down')}</button></div>`).join(''));
   host.find('.driver-order-help').text(`${tr('Drag customers or use Up/Down. Scanner: SELECT chooses a customer, ROUTE_MOVE_UP / ROUTE_MOVE_DOWN moves it, ROUTE_REASON enters the reason.')} ${tr('Customer numbers on this scanner page')}: `+rows.slice(routePage*10,routePage*10+10).map((r,i)=>`${i+1}. ${r.label}`).join(' · '));
  }
  function moveOrder(key,delta){orderEditable();routeOrder.shift(key,delta);routeSelected=key;routePage=Math.floor(routeOrder.keys().indexOf(key)/10);drawOrder();}
  function render(){
   if(!valid())return;tools?.close?.();tools=null;inputs={};inputScanner=null;
   const detail=options.detail(),stop=(detail?.stops||[]).find(row=>row.stop_key===(c.state.pending?c.state.pending.request.stop_key:context?.stop_key||options.stop));
   const pending=c.state.pending,owned=!pending||pending.actor===owner;
   host.html(`<section class="frappe-card p-4 mt-3 driver-action-panel"><h3>${tr(options.operation||'Driver route action')}</h3><div class="driver-action-summary"></div>
    <div class="driver-action-message alert alert-info" role="status"></div><div class="driver-action-fields"></div><div class="driver-action-input-help text-muted"></div>
    <div class="driver-action-scanner mt-3"><input class="form-control driver-action-scan" autocomplete="off" placeholder="${tr('Scanner: Customer Site, field value or Confirm')}"><button class="btn btn-default driver-action-camera">${tr('Scan with Camera')}</button></div>
    <div class="driver-action-controls mt-3"><button class="btn btn-primary driver-action-confirm"></button><button class="btn btn-default driver-action-readback">${tr('Check saved outcome / Refresh')}</button>
    <input class="form-control driver-action-void-reason" placeholder="${tr('Supervisor reason to void an unrecorded request')}"><button class="btn btn-warning driver-action-void">${tr('Void if unrecorded')}</button><button class="btn btn-default driver-action-edit-return">${tr('Return to Edit')}</button><button class="btn btn-default driver-action-cancel">${tr('Close')}</button></div></section>`);
   if(owned)host.find('.driver-action-summary').html(stop?`<h4>${e(stop.site_name||stop.customer_name)}</h4><p>${e(stop.address||'')}</p>`+
    stop.items.map(row=>`<div><strong>${e(row.item_code)}</strong> · ${e(row.planned_qty)} ${e(row.stock_uom)} ${e(row.orders.map(order=>order.sales_order).join(', '))}</div>`).join(''):
    `<h4>${e(detail?.trip?.trip_title||options.trip)}</h4>${context?.next_step==='Start Route'?`<p>${tr('Start this loaded route. This records departure; it creates no customer Delivery Note.')}</p>`:''}`);
   if(owned&&context?.delivery_session){
    const sessionURL='/app/cfg-kanban-delivery-session/'+encodeURIComponent(context.delivery_session);
    const note=context.delivery_note,exception=context.exception;
    host.find('.driver-action-summary').append(`<p class="driver-session-reference">${tr('Delivery Session')}: <a href="${e(sessionURL)}" target="_blank" rel="noopener">${e(context.delivery_session)}</a> · ${e(context.session_state||'')}</p>`+
     (note?`<p>${tr('Delivery Note')}: <a href="/app/delivery-note/${e(encodeURIComponent(note))}" target="_blank" rel="noopener">${e(note)}</a></p>`:'')+
     (exception?`<p>${tr('Exception')}: <a href="/app/cfg-kanban-exception/${e(encodeURIComponent(exception))}" target="_blank" rel="noopener">${e(exception)}</a></p>`:''));
   }
   if(pending){update();return;}
   const step=context?.next_step;
   host.find('.driver-action-edit-return').toggle((step==='Collect Old Return'&&Boolean(returnReview))||(step==='Begin Delivery'&&Boolean(quantityReview))||Boolean(quantityReview));
   host.find('.driver-action-message').text(context?.message||(!context?tr('Loading current action…'):step==='Begin Delivery'?tr('Review accepted quantities; reduce Accepted and enter a reason/condition for refused stock. The Delivery Note follows the configured Draft or auto-submit policy; required proof remains mandatory.'):step));
   if(['Request Stop Cancellation','Cancel Customer Stop'].includes(step)){
    host.find('.driver-action-fields').html(cancellationSummary(context.setup));
    field({fieldname:'reason',label:tr('Customer Stop Cancellation Reason'),fieldtype:'Small Text',reqd:1});
    if(step==='Cancel Customer Stop'&&context.setup.has_loaded_goods)field({fieldname:'stock_disposition',label:tr('Loaded Goods Disposition'),fieldtype:'Select',options:context.setup.dispositions.join('\n'),default:context.setup.dispositions[0],reqd:1});
   }
   if(step==='Edit Route Order'){
    routeOrder=stopOrder(context.setup.stops);routeSelected=null;routePage=0;
    host.find('.driver-action-message').text(context.setup.enforced?tr('Sequence is enforced. Put the requested next customer first, arrange the other pending stops, and enter a reason. The Supervisor chooses one-next-customer or the full proposed order.'):tr('Reorder unfinished customer stops, then save. Completed stops and the loaded stock record stay fixed.'));
    host.find('.driver-action-fields').html('<div class="driver-order-list"></div><p class="driver-order-help text-muted"></p>');drawOrder();
    field({fieldname:'reason',label:tr('Route Change Reason'),fieldtype:'Small Text',reqd:context.setup.enforced?1:0});
   }
   if(step==='Cancel Route Change'){
    host.find('.driver-action-message').text(tr(context.setup.request_type==='Cancel Customer Stop'?'Withdraw the pending cancellation request. The customer stop stays active.':'Cancel the pending route request; the current approved route order continues.'));
    field({fieldname:'reason',label:tr('Cancellation Reason'),fieldtype:'Small Text',reqd:1});
   }
   if(step==='Decide Route Change'){
    const setup=context.setup;
    host.find('.driver-action-message').text(`${setup.request_name} · ${setup.state} · ${setup.requested_by}: ${setup.reason}`);
    if(setup.request_type==='Cancel Customer Stop')host.find('.driver-action-fields').html(cancellationSummary(setup));
    else host.find('.driver-action-fields').html(`<p><strong>${tr('Remaining Order at Request')}:</strong> ${setup.current.map(r=>e(r.label)).join(' → ')}</p><p><strong>${tr('Proposed remaining order')}:</strong> ${setup.proposed.map(r=>e(r.label)).join(' → ')}</p>`);
    if(setup.state==='Pending'){
     if(!setup.approvable)host.find('.driver-action-fields').append(`<p class="alert alert-warning">${tr('Trip progressed or has an active stop. Only rejection is available here; refresh after proof or ask for a fresh request.')}</p>`);
     field({fieldname:'decision',label:tr('Decision'),fieldtype:'Select',options:(setup.approvable?['Approve','Reject']:['Reject']).join('\n'),default:setup.approvable?'Approve':'Reject',reqd:1});
     if(setup.request_type==='Cancel Customer Stop'){if(setup.has_loaded_goods)field({fieldname:'stock_disposition',label:tr('Loaded Goods Disposition'),fieldtype:'Select',options:setup.dispositions.join('\n'),default:setup.dispositions[0],reqd:1});}
     else field({fieldname:'approval_mode',label:tr('Approval Scope'),fieldtype:'Select',options:setup.modes.join('\n'),default:setup.modes[0]});
     field({fieldname:'reason',label:tr('Supervisor Decision Reason'),fieldtype:'Small Text',reqd:1});
    }else{context.next_step='Done';host.find('.driver-action-fields').append(`<p>${e(setup.approval_mode||'')} · ${e(setup.decision_reason||'')}</p>`);}
   }
   if(step==='Add Assistant'){
    host.find('.driver-action-message').text(tr('Select an Employee or scan their Employee ID. Each assistant signs in separately.')+((context.setup.team||[]).length?' '+tr('Current assistants')+': '+context.setup.team.join(', '):''));
    field({fieldname:'employee',label:tr('Assistant Driver Employee / ID'),fieldtype:'Link',options:'Employee',reqd:1,get_query:()=>({filters:{status:'Active'}})});
   }
   if(['Begin Delivery','Begin Open Sale'].includes(step)&&context.require_scan)field({fieldname:'customer_scan',label:tr('Required Customer Site QR'),fieldtype:'Data',reqd:1,default:arrival});
   if(['Begin Delivery','Begin Open Sale'].includes(step)&&context.quantities?.length)field({fieldname:'quantities',label:tr('Accepted / Refused — stock UOM'),fieldtype:'Table',cannot_add_rows:true,cannot_delete_rows:true,in_place_edit:true,data:context.quantities,fields:[
    {fieldname:'dispatch_allocation',fieldtype:'Data',read_only:1,hidden:1},
    {fieldname:'source_label',label:'Item / Tag / Batch',fieldtype:'Data',read_only:1,in_list_view:1,columns:3},
    {fieldname:'stock_uom',label:'UOM',fieldtype:'Data',read_only:1,in_list_view:1,columns:1},
    {fieldname:'prepared_qty',label:'Loaded',fieldtype:'Float',read_only:1,in_list_view:1,columns:1},
    {fieldname:'accepted_qty',label:'Accepted',fieldtype:'Float',in_list_view:1,columns:1},
    {fieldname:'condition',label:'Refused Condition',fieldtype:'Select',options:['Good / Unwanted','Damaged','Expired','Pest or Contamination','Customer Handling Damage','Wrong Item or Quantity','Other','Unknown'],in_list_view:1,columns:2},
    {fieldname:'refusal_reason',label:'Refusal Reason',fieldtype:'Small Text',in_list_view:1,columns:2},
   ]});
   if(context?.loose_tags?.length)host.find('.driver-action-fields').prepend?.('<div class="driver-loose-tags">'+packSummary(context.loose_tags)+'</div>');
   if(step==='Collect Old Return'){
    host.find('.driver-action-message').text(tr('Old customer goods: temporary custody for QC. No stock receipt or credit is posted. Review the stock UOM quantities before issuing the note.'));
    field({fieldname:'existing_return_case',label:'Existing Temporary Return Note QR / Number (optional; collect full case)',fieldtype:'Data'});
    field({fieldname:'inspection_location',label:'Inspection Custody Location',fieldtype:'Link',options:'Location',reqd:1,default:context.setup.inspection_location});
    field({fieldname:'customer_return_reason',label:'Customer Return Reason',fieldtype:'Small Text',reqd:1});
    field({fieldname:'customer_acknowledgement_name',label:'Customer Representative',fieldtype:'Data'});
    field({fieldname:'reported_source_reference',label:'Original DN / Customer Reference (if known)',fieldtype:'Data'});
    field({fieldname:'lines',label:'Old goods physically collected — Item stock UOM',fieldtype:'Table',in_place_edit:true,data:[],fields:[
     {fieldname:'item_code',label:'Item',fieldtype:'Link',options:'Item',in_list_view:1,columns:2,reqd:1},
     {fieldname:'claimed_qty',label:'Qty',fieldtype:'Float',in_list_view:1,columns:1,reqd:1},
     {fieldname:'batch_no',label:'Batch',fieldtype:'Link',options:'Batch',in_list_view:1,columns:2},
     {fieldname:'expiry_date',label:'Expiry',fieldtype:'Date'},
     {fieldname:'condition',label:'Condition',fieldtype:'Select',options:context.setup.conditions,default:'Unknown',in_list_view:1,columns:2},
     {fieldname:'original_visible_code',label:'Old Tag / Reference',fieldtype:'Data',in_list_view:1,columns:3},
     {fieldname:'details',label:'Details',fieldtype:'Small Text'},
    ]});
   }
   if(step==='Select Route Stock'){
    host.find('.driver-action-fields').html(`<p>${tr('Select prepared route stock or eligible unassigned lorry stock. Customer-order stock and QC-held goods remain protected.')}</p><button class="btn btn-primary driver-action-add-stock">${tr('Add Product / Scan Stock')}</button>`+(context.selected_stock||[]).map(r=>`<p>${e(r.visible_code||r.item_code)} · ${e(r.batch_no||'')} · ${e(r.allocated_qty)} ${e(r.stock_uom)} · ${e(r.state)}</p>`).join(''));
   }
   if(step==='Release Refused Stock'){
    field({fieldname:'release_rows',label:'Select held refused stock',fieldtype:'Table',cannot_add_rows:true,cannot_delete_rows:true,in_place_edit:true,data:context.setup.rows,fields:[
     {fieldname:'line_name',fieldtype:'Data',read_only:1,hidden:1},{fieldname:'selected',label:'Release',fieldtype:'Check',in_list_view:1,columns:1},
     {fieldname:'item_code',label:'Item',fieldtype:'Data',read_only:1,in_list_view:1,columns:3},
     {fieldname:'refused_qty',label:'Qty',fieldtype:'Float',read_only:1,in_list_view:1,columns:2},
     {fieldname:'stock_uom',label:'UOM',fieldtype:'Data',read_only:1,in_list_view:1,columns:1},
     {fieldname:'stock_state',label:'Held Status',fieldtype:'Data',read_only:1,in_list_view:1,columns:3},
    ]});field({fieldname:'reason',label:'Supervisor Release Reason',fieldtype:'Small Text',reqd:1});
   }

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
   const orderHelp=tr('Numbered choices select customers in the order list above. ROUTE_REASON selects the reason field.');
   inputScanner=window.cfg_delivery_action_scanner.createController({fields:defs,owner:options.owner,openedOwner:owner,render:s=>{
     if(step==='Edit Route Order'){host.find('.driver-action-input-help').text(orderHelp);return;}
     const choices=inputScanner?.choices()||defs;
     host.find('.driver-action-input-help').text((s.table?`${s.table.label} · Row ${s.table.index+1}. `:'')+
      choices.slice(s.page*10,s.page*10+10).map((row,index)=>`${index+1}. ${row.label||row.name}${(s.table?s.table.column:s.field)===row.name?' ✓':''}`).join(' · '));
    },nonce:options.nonce,values,
    set:(name,value)=>inputs[name].set_value(value),read:name=>valueOf(inputs[name]),submit:async()=>submit(),close:()=>{},success:async()=>{},camera:startCamera});
   host.find('.driver-action-input-help').text(step==='Edit Route Order'?orderHelp:defs.map((row,index)=>`${index+1}. ${row.label||row.name}`).join(' · '));
   update();focus();
  }
  async function submit(auto=false){
   if(!valid())throw new Error('Operator changed; reopen this driver action.');if(c.state.pending)return c.retry();
   if(!context||['Blocked','Await ERP','Done'].includes(context.next_step))return;
   if(tools?.busy?.())throw new Error('Wait until proof evidence has finished uploading.');
   let payload={},v=values(),step=context.next_step;
   if(!auto)automatic=!['Start Route','Add Assistant'].includes(step);
   if(!c.state.pending&&(context.loose_tags||[]).some(p=>p.state!=='Scanned'))throw new Error('Scan every assigned Loose Tag at this customer stop before confirming.');
   if(['Begin Delivery','Begin Open Sale'].includes(step)&&context.quantities?.length)payload.quantities=(v.quantities||inputs.quantities.df.data||[]).map(row=>({dispatch_allocation:row.dispatch_allocation,accepted_qty:row.accepted_qty,refusal_reason:row.refusal_reason||'',condition:row.condition||'Good / Unwanted'}));
   if(['Begin Delivery','Begin Open Sale'].includes(step)){arrival=String(v.customer_scan||arrival||'').trim();if(context.require_scan&&!arrival)throw new Error('Scan the required Customer Site before confirmation.');payload.customer_scan=arrival||null;}
   if(['Begin Delivery','Begin Open Sale'].includes(step)&&context.quantities?.length){
    if(!quantityReview&&payload.quantities.some((r,index)=>Number(r.accepted_qty)!==Number(context.quantities[index].prepared_qty))){
     const preview=await rpc(step==='Begin Open Sale'?'cfg_kanban.services.loose_tags.preview_open_quantities':prefix+'preview_driver_quantities',{trip_name:options.trip,stop_key:context.stop_key,dispatch_plan:context.dispatch_plan,quantities:payload.quantities,operator_session_token:options.token()});
     if(!valid())return;quantityReview=JSON.parse(JSON.stringify(payload));
     host.find('.driver-action-message').text(preview.map(r=>`${r.item_code}${r.visible_code?' / '+r.visible_code:''}${r.batch_no?' / '+r.batch_no:''}: accepted ${r.accepted_qty}, refused ${r.refused_qty} ${r.stock_uom} · ${r.refusal_reason||''}`).join(' | ')+'. Confirm records these quantities. Quality refusals create company-owned QC custody; no credit or stock receipt.');
     host.find('.driver-action-edit-return').toggle(true);update();return;
    }
    if(quantityReview)payload=quantityReview;
   }
   if(['Begin Delivery','Begin Open Sale'].includes(step)&&quantityReview)payload=JSON.parse(JSON.stringify(quantityReview));
   if(step==='Edit Route Order'){
    if(context.setup.enforced&&!String(v.reason||'').trim())throw new Error('Enter a reason for the Supervisor route request.');
    payload={order:routeOrder.keys(),reason:v.reason||''};step=context.setup.enforced?'Request Route Change':'Change Route Order';automatic=false;
   }
   if(step==='Cancel Route Change'){payload={request_name:context.setup.request_name,reason:v.reason||''};automatic=false;}
   if(['Request Stop Cancellation','Cancel Customer Stop'].includes(step)){
    const reason=String(v.reason||'').trim();if(!reason)throw new Error('Enter the customer-stop cancellation reason.');
    payload={reason};automatic=false;
    if(step==='Cancel Customer Stop'){payload.goods_hash=context.setup.goods_hash;payload.stock_disposition=v.stock_disposition||'Keep Reserved for Return';}
   }
   if(step==='Decide Route Change'){payload={request_name:context.setup.request_name,decision:v.decision,approval_mode:v.approval_mode,reason:v.reason||''};if(context.setup.request_type==='Cancel Customer Stop'){payload.goods_hash=context.setup.goods_hash;payload.stock_disposition=v.stock_disposition||'Keep Reserved for Return';}automatic=false;}
   if(step==='Add Assistant'){
    payload.employee=String(v.employee||'').trim();
    if(!payload.employee)throw new Error('Select an Assistant Driver Employee first.');
   }
   if(step==='Create Delivery Note')payload.required_erp_inputs=window.cfg_dispatch_recovery.erpValues(context.requirements?.fields||[],v);
   if(step==='Submit Proof'){
    const location=context.proof.require_gps&&v.disposition!=='No Proof Recorded'?await window.cfg_delivery_proof_tools.geotag():null;
    if(!valid())throw new Error('Operator changed; reopen the proof.');
    payload={proof_name:context.proof.name,disposition:v.disposition,recipient_name:v.recipient_name||'',unattended_reason:v.unattended_reason||'',notes:v.notes||'',latitude:location?.latitude??null,longitude:location?.longitude??null,location_accuracy:location?.accuracy??null};
   }
   if(step==='Complete Stop'&&context.purpose==='Visit Only')payload.notes=v.notes||'';
   if(step==='Collect Old Return'){
    if(!returnReview){
     const data={existing_return_case:v.existing_return_case||null,inspection_location:v.inspection_location,customer_return_reason:v.customer_return_reason,customer_acknowledgement_name:v.customer_acknowledgement_name||'',reported_source_reference:v.reported_source_reference||'',lines:(v.lines||[]).map(row=>Object.fromEntries(['item_code','claimed_qty','batch_no','expiry_date','condition','original_visible_code','details'].map(key=>[key,row[key]])))};
     const preview=await rpc(prefix+'preview_driver_collection',{trip_name:options.trip,stop_key:options.stop,payload:data,operator_session_token:options.token()});
     if(!valid())return;returnReview={...data,lines:preview.lines,existing_return_case:preview.existing_return_case||null};
     host.find('.driver-action-message').text(`${preview.company} · ${preview.customer_name||preview.customer} · ${preview.inspection_location}. `+preview.lines.map(r=>`${r.item_code}: ${r.claimed_qty} ${r.stock_uom}`).join(' · ')+(preview.existing_return_case?'. Confirm collects this existing note; no duplicate claim.':'. Confirm issues one Temporary Return Note.')+' Return to Edit permits corrections.');
     host.find('.driver-action-edit-return').toggle(true);update();return;
    }
    payload=returnReview;
   }
   if(step==='Release Refused Stock')payload={outcome:context.setup.outcome,line_names:(v.release_rows||[]).filter(r=>r.selected).map(r=>r.line_name),reason:v.reason||''};

   if(step==='Select Route Stock'){
    await f.require('/assets/cfg_kanban/js/route_delivery.js');if(!valid())return;
    const pending=options.storage.getItem(window.cfg_route_delivery.pendingKey);
    if(pending)throw new Error('Resolve the pending stock selection through Add Product before confirming delivery.');
    step='Confirm Allocations';
   }
   await c.mutate(context,step,payload);
  }
  async function scan(value){
   if(stockChild)return stockChild.scan(value);
   const text=String(value||'').trim(),upper=text.toUpperCase();if(!text||!valid())return;
   if(upper==='CFG:CMD:CANCEL')return close();if(upper==='CFG:CMD:CONFIRM')return submit();
   if(['CFG:CMD:REFRESH','CFG:CMD:ROUTE_SHEET_REFRESH'].includes(upper))return c.state.pending?c.reconcile():load();
   if(upper==='CFG:CMD:HELP'){host.find('.driver-action-message').text(context?.next_step==='Edit Route Order'?'Numbered choices select customers. ROUTE_MOVE_UP / ROUTE_MOVE_DOWN changes their order. NEXT_MATERIALS / PREVIOUS_MATERIALS pages the customer choices. ROUTE_REASON selects the reason. Confirm saves or requests approval; Cancel closes safely.':'Open Route goods: ALLOCATE_ROUTE_STOCK opens Add Product / Scan Stock in this Session. Scan the source or Item, select the source, enter stock UOM quantity and Confirm; repeat, then Confirm on the stop screen creates its DN. Loose Tag: scan CFG:LOOSE: QR once at its assigned customer stop; review every packed Item/Batch/source and Accepted quantity. Reduce a refused quantity with reason/condition, Confirm, then continue native DN/proof. For customer cancellation, STOP_CANCEL_REASON arms the reason; STOP_STOCK_DISPOSITION selects Keep Reserved for Return or Release for Same-trip Sale using numbered choices. Drivers request; Supervisors approve. Confirm submits reviewed details. Scan Customer Site when required. CFG:SELECT:1–10 arms a field; scan its value. DELIVERY_RECIPIENT and ERP table-row commands are supported. Cancel closes while retaining unknown results. Refresh reads back the saved outcome.');return;}
   if(c.state.pending)throw new Error('Retry or reconcile the original request before editing.');
   if(text.startsWith('CFG:LOOSE:')){
    if(!['Begin Delivery','Begin Open Sale'].includes(context?.next_step))throw new Error('Open the assigned customer stop before scanning its unused Loose Tag.');
    if(quantityReview)throw new Error('Return to Edit before scanning another pack.');
    const packed=await rpc('cfg_kanban.services.loose_tags.scan_loose_tag',{trip_name:options.trip,stop_key:context.stop_key,scan_value:text,operator_session_token:options.token()});
    if(!valid())return;
    for(const pack of context.loose_tags||[])if(pack.name===packed.name)pack.state=packed.state;
    host.find('.driver-loose-tags').html(packSummary(context.loose_tags||[]));
    host.find('.driver-action-message').text(packed.lines.map(r=>`${r.item_code} / ${r.batch_no||'—'}: ${r.qty} ${r.stock_uom} · ${r.source_visible_code}`).join(' | ')+'. All lines are in Accepted / Refused below. Confirm delivers the accepted quantities.');update();return;
   }
   if(context?.next_step==='Edit Route Order'){
    const selected=upper.match(/^CFG:SELECT:(10|[1-9])$/);
    if(selected){orderEditable();const row=routeOrder.list()[routePage*10+Number(selected[1])-1];if(!row)throw new Error('Choose a displayed customer number.');routeSelected=row.stop_key;drawOrder();return;}
    if(['CFG:CMD:NEXT_MATERIALS','CFG:CMD:PREVIOUS_MATERIALS'].includes(upper)){orderEditable();routePage=Math.max(0,Math.min(Math.ceil(routeOrder.list().length/10)-1,routePage+(upper.includes('NEXT_')?1:-1)));drawOrder();return;}
    if(upper==='CFG:CMD:ROUTE_REASON')return inputScanner.field('reason');
    if(['CFG:CMD:ROUTE_MOVE_UP','CFG:CMD:ROUTE_MOVE_DOWN'].includes(upper)){
     if(!routeSelected)throw new Error('Select the customer number to move first.');return moveOrder(routeSelected,upper.endsWith('_UP')?-1:1);
    }
   }
   if(upper==='CFG:CMD:RETURN_EDIT'){returnReview=null;quantityReview=null;host.find('.driver-action-edit-return').toggle(false);update();return;}
   if(returnReview||quantityReview)throw new Error('Use Return to Edit before changing reviewed quantities.');
   if(context?.next_step==='Begin Delivery'&&context.require_scan&&!inputScanner?.state.table&&inputScanner?.state.field==='customer_scan'&&!upper.startsWith('CFG:')){await inputs.customer_scan.set_value(text);return;}
   if(['CFG:CMD:ALLOCATE_ROUTE_STOCK','CFG:CMD:ROUTE_ALLOCATE_STOCK'].includes(upper)&&context?.next_step==='Select Route Stock')return addStock();
   if(upper==='CFG:CMD:RETURN_CAMERA')return startCamera();
   if(upper==='CFG:CMD:STOP_CANCEL_REASON')return inputScanner.field('reason');
   if(upper==='CFG:CMD:STOP_STOCK_DISPOSITION')return inputScanner.field('stock_disposition');
   if(upper==='CFG:CMD:RETURN_REASON')return inputScanner.field('customer_return_reason');
   if(upper==='CFG:CMD:RETURN_ITEMS')return inputScanner.field('lines');
   const aliases={'CFG:CMD:RETURN_ADD_ITEM':'CFG:CMD:DELIVERY_ADD_ROW','CFG:CMD:RETURN_NEXT_ITEM':'CFG:CMD:DELIVERY_NEXT_ROW','CFG:CMD:RETURN_PREVIOUS_ITEM':'CFG:CMD:DELIVERY_PREVIOUS_ROW','CFG:CMD:RETURN_INPUTS':'CFG:CMD:DELIVERY_INPUTS'};
   if(['CFG:CMD:RETURN_ADD_ITEM','CFG:CMD:DELIVERY_ADD_ROW'].includes(upper)&&['quantities','release_rows'].includes(inputScanner?.state.field))throw new Error('Prepared quantity/release rows cannot be added. Choose their existing row.');
   const qty=text.match(/^CFG:QTY:MATERIAL:(.+)$/i);
   if(qty){if(!inputScanner.state.table)throw new Error('Choose the quantity table row first.');inputScanner.state.table.column=inputScanner.state.table.name==='quantities'?'accepted_qty':'claimed_qty';return inputScanner.value(qty[1]);}
   return inputScanner?.scan(aliases[upper]||text);
  }
  function startCamera(){if(camera||closed)return;if(!f.ui.Scanner)throw new Error('Camera unavailable; use the Scanner field.');const version=cameraVersion;let accepted=false;
   camera=new f.ui.Scanner({dialog:true,multiple:false,on_scan:data=>{if(accepted||version!==cameraVersion||!valid())return;accepted=true;stopCamera();queue(()=>scan(data.decodedText));}});camera.dialog?.$wrapper?.one?.('hidden.bs.modal.cfg_driver_action',()=>{cameraVersion++;camera=null;focus();});}
  async function addStock(){
   if(!valid()||stockChild||c.state.pending||context?.next_step!=='Select Route Stock')return;
   await f.require('/assets/cfg_kanban/js/route_delivery.js');if(!valid())return;
   stockChild=await window.cfg_route_delivery.open({frappe:f,mode:'stock',deliverySession:context.delivery_session,
    owner:options.owner,token:options.token,nonce:options.nonce,errorMessage:(_err,fallback)=>fallback,
    success:async()=>{stockChild=null;if(valid())await load();},onClose:()=>{stockChild=null;focus();}});
   if(!valid()){stockChild?.close?.();stockChild=null;}
  }
  function close(){if(closed)return;stockChild?.close?.();stockChild=null;closed=true;epoch++;c.close();tools?.close?.();stopCamera();host.empty();options.onClose();}
  host.off('.cfg_driver_action').on('click.cfg_driver_action','.driver-action-add-stock',()=>queue(addStock)).on('click.cfg_driver_action','.driver-action-edit-return',()=>{if(c.state.pending||c.state.busy)return;returnReview=null;quantityReview=null;host.find('.driver-action-edit-return').toggle(false);update();focus();}).on('click.cfg_driver_action','.driver-action-confirm',()=>queue(submit))
   .on('click.cfg_driver_action','.driver-action-readback',()=>queue(()=>c.state.pending?c.reconcile():load()))
   .on('click.cfg_driver_action','.driver-action-camera',()=>queue(startCamera)).on('click.cfg_driver_action','.driver-action-cancel',close)
   .on('click.cfg_driver_action','.driver-action-void',()=>queue(async()=>{const reason=String(host.find('.driver-action-void-reason').val()||'').trim();if(!reason)throw new Error('Enter the Supervisor reason first.');await c.reconcile(reason);} ))
   .on('keydown.cfg_driver_action','.driver-action-scan',event=>{if(!['Enter','Tab'].includes(event.key)||event.shiftKey||event.ctrlKey||event.altKey||event.metaKey||event.isComposing)return;const input=host.find('.driver-action-scan'),value=String(input.val()||'').trim();if(!value)return;event.preventDefault();event.stopPropagation();input.val('');queue(()=>scan(value));});
  host.on('click.cfg_driver_action','.driver-order-up',event=>queue(()=>moveOrder($(event.currentTarget).attr('data-order-key'),-1)))
   .on('click.cfg_driver_action','.driver-order-down',event=>queue(()=>moveOrder($(event.currentTarget).attr('data-order-key'),1)))
   .on('dragstart.cfg_driver_action','.driver-order-row',event=>{try{orderEditable();draggedStop=$(event.currentTarget).attr('data-order-key');event.originalEvent.dataTransfer.setData('text/plain',draggedStop);}catch(_){event.preventDefault();}})
   .on('dragover.cfg_driver_action','.driver-order-row',event=>{if(draggedStop&&!c.state.pending&&!c.state.busy)event.preventDefault();})
   .on('drop.cfg_driver_action','.driver-order-row',event=>{event.preventDefault();const key=$(event.currentTarget).attr('data-order-key'),source=draggedStop;draggedStop=null;queue(()=>{orderEditable();routeOrder.move(source,key);routeSelected=source;routePage=Math.floor(routeOrder.keys().indexOf(source)/10);drawOrder();});})
   .on('dragend.cfg_driver_action','.driver-order-row',()=>{draggedStop=null;});
  c.restore(options.trip);render();if(!c.state.pending)queue(load);
  return {scan:value=>queue(()=>scan(value)),close,focus,controller:c,refresh:()=>queue(()=>c.state.pending?c.reconcile():load())};
 }
 const api={controller,open,stopOrder,cancellationSummary};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.cfg_driver_route_actions=api;
})(typeof window==='undefined'?globalThis:window);
