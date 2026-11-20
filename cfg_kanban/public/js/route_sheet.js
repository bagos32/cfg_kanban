/* Approved lorry itineraries: native delivery engines own stock and customer documents. */
(function(root){
 'use strict';
 function controller(env){
  const owner=env.owner(),key='cfg_route_sheet_v1:'+owner;
  const s={closed:false,busy:false,pending:null,baseline:null,message:'Scan the lorry Warehouse card or a Dispatch Plan.',context:null,choicePage:0,stage:'stops',selected:null,action:'Save Draft',arrival:'',reason:''};
  const fail=text=>{throw new Error(text);},changed=()=>env.render(s),copy=value=>JSON.parse(JSON.stringify(value));
  function actor(){if(env.owner()!==owner)fail('Identify the original route operator before continuing.');}
  function read(){const text=env.storage.getItem(key);if(!text)return null;let value;try{value=JSON.parse(text);}catch(_){fail('Pending route data is unreadable; reconcile this terminal.');}
   if(value.owner!==owner||!value.event||!['Pending','Recorded','Rejected','Voided'].includes(value.status)||(value.status==='Pending'&&(!value.method||!value.args||value.args.event_token!==value.event)))fail('Pending route data is incomplete; reconcile this terminal.');return value;}
  function write(value){env.storage.setItem(key,JSON.stringify(value));}
  function restore(){const saved=read();s.baseline=saved?.event||null;s.pending=saved?.status==='Pending'?saved:null;changed();}
  function edit(){actor();if(s.closed||s.busy||s.pending)fail('Reconcile or retry the original route request before changing its details.');}
  async function exclusive(work){if(!env.locks?.request)fail('Route actions require HTTPS and a browser supporting Web Locks.');return env.locks.request(key,work);}
  async function mutate(method,args){
   actor();if(s.closed||s.busy)return;s.busy=true;changed();try{return await exclusive(async()=>{
    actor();if(s.closed)return;const saved=read(),retry=!!s.pending;
    if(saved?.status==='Pending'&&saved.event!==s.pending?.event){s.pending=saved;changed();fail('Another route request is pending; review its original details before retrying.');}
    if(s.pending&&(saved?.status!=='Pending'||saved.event!==s.pending.event))fail('This request changed in another tab. Read its recorded outcome.');
    if(!s.pending&&(saved?.event||null)!==s.baseline)fail('Another route action completed. Close and reopen before continuing.');
    const pending=s.pending||{owner,event:env.nonce(),method,args:copy(args),status:'Pending'};pending.args.event_token=pending.event;
    write(pending);s.pending=pending;changed();let result;
    try{result=await env.rpc(pending.method,pending.args);}catch(error){const type=error?.exc_type||error?.responseJSON?.exc_type;
     if(!retry&&['ValidationError','PermissionError','DoesNotExistError','LinkValidationError','MandatoryError'].includes(type)){
      write({owner,event:pending.event,status:'Rejected'});s.pending=null;s.baseline=pending.event;
     }throw error;}
    write({owner,event:pending.event,status:'Recorded'});s.pending=null;s.baseline=pending.event;
    if(!s.closed&&env.owner()===owner)await env.success(result,pending.method);return result;
   });}finally{s.busy=false;changed();}
  }
  async function reconcile(voiding=false){
   actor();if(s.busy||s.closed)return;if(!s.pending)fail('No pending route action is stored on this terminal.');
   if(voiding&&!s.reason.trim())fail('Enter a reason before voiding an unrecorded action.');s.busy=true;changed();
   try{await exclusive(async()=>{actor();const pending=s.pending,visit=pending.method==='start_route_sheet_stop';
    const result=await env.rpc(visit?'reconcile_route_sheet_visit':'reconcile_route_sheet_action',{
     ...(visit?{route_sheet:pending.args.route_sheet,row_key:pending.args.row_key}:{scope_key:pending.args.scope_key}),
     event_token:pending.event,...(voiding?{void_reason:s.reason.trim()}:{})});
    if(result.status==='Recorded'||result.status==='Voided'){
     const saved=read();if(saved?.event===pending.event)write({owner,event:pending.event,status:result.status});
     s.pending=null;s.baseline=pending.event;if(!s.closed&&env.owner()===owner){if(result.status==='Recorded')await env.success(visit?result.result:result,pending.method);else s.message='Unrecorded route request voided. Refresh and review corrected details.';}
    }else s.message='No result is recorded yet. Retry the original request, or void it with a reason before correcting it.';
   });}finally{s.busy=false;changed();}
  }
  function close(){s.closed=true;env.close();}
  return {state:s,restore,edit,mutate,reconcile,close,changed};
 }
 async function open(options){
  const f=options.frappe,e=f.utils.escape_html,owner=options.owner();let d,c,camera=null,tail=Promise.resolve(),launch=[],rows=[],contextArgs={},dragged=null;
  const focus=()=>{if(!c?.state.closed)d.fields_dict.scan.$input.focus();};
  const rpc=async(method,args)=>(await f.call({method:'cfg_kanban.services.route_sheets.'+method,args:{...args,operator_session_token:options.token()}})).message;
  function queue(work){tail=tail.then(work).catch(error=>{c.state.message=options.errorMessage(error,error.message||'Route action failed.');render(c.state);}).finally(focus);return tail;}
  function stopCamera(){const current=camera;camera=null;current?.hide_dialog?.();}
  function cameraScan(){if(camera||c.state.closed)return;if(options.owner()!==owner)throw new Error('Identify the original operator before scanning.');if(!f.ui.Scanner)throw new Error('Camera scanning is unavailable.');
   let accepted=false;camera=new f.ui.Scanner({dialog:true,multiple:false,on_scan:data=>{if(accepted||c.state.closed)return;accepted=true;stopCamera();dispatch(data.decodedText);}});
   const current=camera;camera.dialog?.$wrapper?.one('hidden.bs.modal',()=>{accepted=true;if(camera===current)camera=null;focus();});}
  async function load(args){
   c.edit();const context=await rpc('get_route_context',args);c.edit();contextArgs={...args};delete contextArgs.template;
   c.state.context=context;rows=(context.stops||context.sheet?.stops||[]).map(row=>({...((context.sites||[]).find(site=>site.name===row.customer_scan_point)||{}),...row,row_key:row.row_key||options.nonce()}));
   c.state.selected=null;c.state.stage='stops';c.state.choicePage=0;c.state.arrival='';c.state.message='Review the customer names, delivery addresses and assigned Plans. Supervisor edits apply before route approval.';render(c.state);
  }
  function canEdit(){return options.mode==='editor'&&!!c.state.context?.can_edit&&(!c.state.context.sheet||c.state.context.sheet.state==='Draft');}
  function choices(){const ctx=c.state.context;if(c.state.stage==='launch')return launch;if(c.state.stage==='templates')return ctx?.templates||[];if(c.state.stage==='sites')return ctx?.sites||[];if(c.state.stage==='plans')return ctx?.plans||[];return rows;}
  function label(row){if(c.state.stage==='launch')return row.label;if(c.state.stage==='templates')return row.name+' · Revision '+row.revision;if(c.state.stage==='plans')return row.name+' · '+(row.customer||row.plan_type);return (row.site_name||row.customer_scan_point||row.name||'')+' · '+(row.dispatch_plan||row.customer||'Select Plan');}
  function render(s){
   if(!d)return;const owned=options.owner()===owner,ctx=owned?s.context:null,sheet=ctx?.sheet;
   const pending=owned?s.pending:null;
   d.fields_dict.summary.$wrapper.html(`<p>${e(owned?s.message:'Identify the original route operator before continuing.')}</p>${pending?`<div class="alert alert-warning">Original ${e(pending.method)} retained. Confirm retries it; Refresh reads its outcome. Cancel keeps this pending action.<pre>${e(JSON.stringify(pending.args,null,2))}</pre></div>`:''}${sheet?`<h4>${e(sheet.name)} · ${e(sheet.state)}</h4><p>${e(sheet.scope)} · ${e(sheet.vehicle_reference||'')} · ${e(sheet.sequence_policy)}<br>${e(sheet.verification_policy)}</p>`:''}`);
   const list=owned&&!pending?choices():[];
   d.fields_dict.sequence.$wrapper.html(list.slice(s.choicePage*10,s.choicePage*10+10).map((row,index)=>{
    const absolute=s.choicePage*10+index,selected=s.stage==='stops'&&s.selected===absolute;
    return `<div class="frappe-card p-3 mb-2 route-stop-choice" data-index="${absolute}" ${canEdit()&&s.stage==='stops'?'draggable="true"':''}><button class="btn ${selected?'btn-primary':'btn-default'} route-choice" data-index="${absolute}">${index+1}. ${e(label(row))}</button>
     ${s.stage==='stops'?`<p>${e(row.customer||'')} · ${e(row.state||'Planned')}<br>${e(row.address_display||row.customer_address||'')}<br>${e(row.instructions||'')}</p>${canEdit()?`<button class="btn btn-default route-up" data-index="${absolute}">↑</button> <button class="btn btn-default route-down" data-index="${absolute}">↓</button>`:''}`:''}</div>`;
   }).join('')||'<p>Scan the lorry card or Plan to open its route. Route preparation and approval are completed by a Supervisor.</p>');
   d.fields_dict.controls.$wrapper.html(`<div class="btn-group flex-wrap"><button class="btn btn-default route-reload">Refresh</button><button class="btn btn-default route-prev">Previous choices</button><button class="btn btn-default route-next">Next choices</button>${ctx&&!sheet?.state?.match(/Approved|In Progress|Ready to Close|Completed|Cancelled/)&&options.mode==='editor'?'<button class="btn btn-default route-templates">Select Template</button><button class="btn btn-default route-add">Add Customer</button><button class="btn btn-default route-plan">Assign Plan</button><button class="btn btn-default route-remove">Remove Selected Stop</button><button class="btn btn-default route-save">Save Draft</button><button class="btn btn-primary route-approve">Approve Sequence</button>':''}${sheet&&options.mode==='editor'?'<button class="btn btn-warning route-cancel">Cancel Unstarted Route</button><button class="btn btn-success route-close">Close Settled Trip</button>':''}${pending?'<button class="btn btn-warning route-void">Void If Unrecorded</button>':''}</div>`);
   if(s.busy||!owned)d.disable_primary_action();else d.enable_primary_action();
   d.get_primary_btn?.().text(pending?'Retry Original Request':options.mode==='driver'?'Start Selected Customer Stop':s.action);
   const bind=(selector,fn)=>d.$wrapper.find(selector).off('click').on('click',fn);
   bind('.route-choice',function(){dispatch('CFG:SELECT:'+((Number(this.dataset.index)%10)+1));});
   bind('.route-up',function(){queue(()=>{c.state.selected=Number(this.dataset.index);move(-1);});});bind('.route-down',function(){queue(()=>{c.state.selected=Number(this.dataset.index);move(1);});});
   for(const [selector,cmd] of Object.entries({'.route-reload':'ROUTE_SHEET_REFRESH','.route-prev':'PREVIOUS_MATERIALS','.route-next':'NEXT_MATERIALS','.route-templates':'ROUTE_TEMPLATE','.route-add':'ROUTE_ADD_STOP','.route-plan':'ROUTE_ASSIGN_PLAN','.route-remove':'ROUTE_REMOVE_STOP','.route-save':'ROUTE_SAVE_DRAFT','.route-approve':'ROUTE_APPROVE_SEQUENCE','.route-cancel':'ROUTE_CANCEL_SHEET','.route-close':'ROUTE_CLOSE_SHEET','.route-void':'ROUTE_VOID_PENDING'}))bind(selector,()=>dispatch('CFG:CMD:'+cmd));
   d.$wrapper.find('.route-stop-choice[draggable]').off('dragstart dragover drop').on('dragstart',function(event){dragged=Number(this.dataset.index);event.originalEvent?.dataTransfer?.setData('text/plain',String(dragged));}).on('dragover',event=>event.preventDefault()).on('drop',function(event){event.preventDefault();const target=Number(this.dataset.index);queue(()=>{c.edit();if(!canEdit())throw new Error('Supervisor may reorder only a Draft route.');if(dragged===null)return;const [row]=rows.splice(dragged,1);rows.splice(target,0,row);c.state.selected=target;c.state.choicePage=Math.floor(target/10);dragged=null;render(c.state);});});
  }
  function move(step){c.edit();if(!canEdit())throw new Error('Supervisor may reorder only a Draft route.');const from=c.state.selected;if(from===null||!rows[from])throw new Error('Select a stop first.');const to=Math.max(0,Math.min(rows.length-1,from+step));const [row]=rows.splice(from,1);rows.splice(to,0,row);c.state.selected=to;c.state.choicePage=Math.floor(to/10);render(c.state);}
  async function select(index){
   c.edit();const value=choices()[index];if(!value)throw new Error('Select a displayed numbered choice.');
   if(c.state.stage==='launch')return load(value.args);
   if(c.state.stage==='templates')return load({...contextArgs,template:value.name});
   if(c.state.stage==='sites'){
    if(!canEdit())throw new Error('A Supervisor must edit route stops.');rows.push({...value,customer_scan_point:value.name,dispatch_plan:null,row_key:options.nonce(),state:'Planned'});c.state.selected=rows.length-1;c.state.stage='plans';c.state.choicePage=0;render(c.state);return;
   }
   if(c.state.stage==='plans'){if(c.state.selected===null)throw new Error('Select a customer stop first.');rows[c.state.selected].dispatch_plan=value.name;c.state.stage='stops';c.state.choicePage=0;render(c.state);return;}
   c.state.selected=index;c.state.arrival='';render(c.state);
  }
  async function confirm(){
   if(c.state.pending)return c.mutate(c.state.pending.method,c.state.pending.args);
   const ctx=c.state.context;if(!ctx)throw new Error('Scan the lorry card or Plan first.');
   if(options.mode==='driver'){
    const row=rows[c.state.selected];if(!ctx.sheet||!row)throw new Error('Select the exact customer stop on an approved route.');
    return c.mutate('start_route_sheet_stop',{route_sheet:ctx.sheet.name,row_key:row.row_key,customer_scan:c.state.arrival||null});
   }
   return c.mutate('save_route_sheet',{scope_key:ctx.scope_key,stops:rows.map(row=>({row_key:row.row_key,dispatch_plan:row.dispatch_plan,customer_scan_point:row.customer_scan_point,instructions:row.instructions||''})),
    expected_revision:ctx.sheet?.revision||0,action:c.state.action,template:ctx.template?.name||ctx.sheet?.route_template||null,template_hash:ctx.template_hash||null,reason:c.state.reason||''});
  }
  async function scan(value){
   const raw=String(value||'').trim(),upper=raw.toUpperCase();if(!raw||c.state.closed)return;
   if(upper==='CFG:CMD:CONFIRM')return confirm();if(upper==='CFG:CMD:ROUTE_SHEET_CAMERA')return cameraScan();
   if(upper==='CFG:CMD:ROUTE_SHEET_REFRESH'){if(c.state.pending)return c.reconcile();return load(contextArgs);}
   if(upper==='CFG:CMD:ROUTE_VOID_PENDING')return c.reconcile(true);
   if(upper==='CFG:CMD:ROUTE_SHEET_REASON'){c.state.armReason=true;return;}
   if(c.state.armReason&&!upper.startsWith('CFG:')){c.state.armReason=false;c.state.reason=raw;d.set_value('reason',raw);render(c.state);return;}
   if(upper==='CFG:CMD:HELP'){c.state.message='Numbered choices select customers, templates and Plans. Supervisor: Template, Add Stop, Assign Plan, Move Up/Down or drag, Save Draft or Approve, then Confirm. Driver: choose assigned stop, scan Site QR if required, then Confirm. Refresh reconciles pending requests. A reason is required for void/cancel/close; Cancel closes without deleting pending requests.';render(c.state);return;}
   c.edit();
   if(['CFG:CMD:NEXT_MATERIALS','CFG:CMD:PREVIOUS_MATERIALS'].includes(upper)){c.state.choicePage=Math.max(0,Math.min(Math.max(Math.ceil(choices().length/10)-1,0),c.state.choicePage+(upper.includes('NEXT_')?1:-1)));render(c.state);return;}
   const selected=upper.match(/^CFG:SELECT:(10|[1-9])$/);if(selected)return select(c.state.choicePage*10+Number(selected[1])-1);
   const stages={'CFG:CMD:ROUTE_TEMPLATE':'templates','CFG:CMD:ROUTE_ADD_STOP':'sites','CFG:CMD:ROUTE_ASSIGN_PLAN':'plans','CFG:CMD:ROUTE_STOPS':'stops'};
   if(stages[upper]){c.state.stage=stages[upper];c.state.choicePage=0;render(c.state);return;}
   if(upper==='CFG:CMD:ROUTE_MOVE_UP')return move(-1);if(upper==='CFG:CMD:ROUTE_MOVE_DOWN')return move(1);
   if(upper==='CFG:CMD:ROUTE_REMOVE_STOP'){if(!canEdit()||c.state.selected===null)throw new Error('Supervisor must select a Draft stop.');rows.splice(c.state.selected,1);c.state.selected=null;render(c.state);return;}
   const actions={'CFG:CMD:ROUTE_SAVE_DRAFT':'Save Draft','CFG:CMD:ROUTE_APPROVE_SEQUENCE':'Approve','CFG:CMD:ROUTE_CANCEL_SHEET':'Cancel','CFG:CMD:ROUTE_CLOSE_SHEET':'Close'};
   if(actions[upper]){c.state.action=actions[upper];c.state.message='Review the complete sequence, then Confirm '+c.state.action+'.';render(c.state);return;}
   if(upper.startsWith('CFG:'))throw new Error('Use a displayed route command.');
   if(c.state.context&&options.mode==='driver'){c.state.arrival=raw;c.state.message='Customer Site scan retained for the selected stop. Confirm verifies it.';render(c.state);return;}
   const result=await rpc('get_route_launch_context',{scan_value:raw});c.edit();launch=result.choices||[];
   if(launch.length===1)return load(launch[0].args);c.state.stage='launch';c.state.choicePage=0;c.state.message=launch.length?'Select the exact Plan/combined trip.':'No active assigned load is visible for this lorry.';render(c.state);
  }
  function dispatch(value){if(String(value||'').trim().toUpperCase()==='CFG:CMD:CANCEL')return c.close();return queue(()=>scan(value));}
  d=new f.ui.Dialog({title:options.mode==='editor'?'Plan and Approve Customer Sequence':'Lorry Route Sheet',size:'extra-large',fields:[
   {fieldname:'scan',label:'Scanner / Customer Site QR',fieldtype:'Data'},{fieldname:'camera',label:'Scan with Camera',fieldtype:'Button',click:()=>queue(cameraScan)},
   {fieldname:'summary',fieldtype:'HTML'},{fieldname:'controls',fieldtype:'HTML'},{fieldname:'sequence',fieldtype:'HTML'},
   {fieldname:'reason',label:'Decision / Void Reason',fieldtype:'Small Text',onchange:()=>{if(c)c.state.reason=String(d.get_value('reason')||'');}},
  ],primary_action_label:'Confirm',primary_action:()=>queue(confirm)});
  c=controller({owner:options.owner,storage:options.storage,locks:options.locks,nonce:options.nonce,rpc,render,close:()=>d.hide(),
   success:async(result,method)=>{if(method==='start_route_sheet_stop'){c.state.closed=true;d.hide();await options.success(result);}
    else {c.state.context={...c.state.context,...result};rows=(result.sheet?.stops||rows).map(row=>({...row}));if(['Approved','Cancelled','Completed'].includes(result.sheet?.state)){c.state.closed=true;d.hide();await options.routeSaved?.(result);}else {c.state.message='Draft recorded. Reorder and approve the sequence when ready.';render(c.state);}}}});
  d.onhide=()=>{c.state.closed=true;stopCamera();options.onClose();};
  d.fields_dict.scan.$input.on('keydown',event=>{if(!['Enter','Tab'].includes(event.key)||event.shiftKey||event.ctrlKey||event.altKey||event.metaKey||event.isComposing)return;const value=String(d.get_value('scan')||'').trim();if(event.key==='Tab'&&!value)return;event.preventDefault();event.stopPropagation();d.set_value('scan','');if(value)return dispatch(value);});
  c.restore();d.show();if(!c.state.pending&&options.warehouse)await queue(async()=>{const result=await rpc('get_route_launch_context',{warehouse:options.warehouse});launch=result.choices||[];if(launch.length===1)return load(launch[0].args);c.state.stage='launch';render(c.state);});else if(!c.state.pending&&(options.plan||options.sheet))await queue(()=>load(options.sheet?{route_sheet:options.sheet}:{dispatch_plan:options.plan}));render(c.state);focus();
  return {scan:dispatch,focus,controller:c,getRows:()=>rows};
 }
 const api={controller,open};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.cfg_route_sheet=api;
})(typeof window==='undefined'?globalThis:window);
