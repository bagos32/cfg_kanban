/* Scanner/touch/camera packing. Unknown writes retain the exact original request. */
(function(root){
 'use strict';
 const prefix='cfg_kanban.services.loose_tags.';
 function createController(env){
  const key='cfg-loose-tag:'+env.user+':'+env.openedOwner;
  const empty=()=>({plan:'',stop:'',lines:[],pending:null,pack:null});
  const s=Object.assign({context:null,source:null,selected:null,qty:'',reason:'',arm:'',page:0,busy:false,closed:false,message:'Scan the customer Dispatch Plan or shared Open Route Plan.'},empty());
  function restore(){const raw=env.storage.getItem(key);if(raw)Object.assign(s,JSON.parse(raw));}
  restore();
  const changed=()=>env.render(s),fail=msg=>{throw new Error(msg);};
  function own(){if(s.closed||env.owner()!==env.openedOwner||!env.token())fail('Identify the original operator before continuing.');}
  function save(resolved=null){
   const stored=JSON.parse(env.storage.getItem(key)||'null');
   if(stored?.pending&&JSON.stringify(stored.pending)!==JSON.stringify(s.pending)&&JSON.stringify(stored.pending)!==JSON.stringify(resolved))fail('Another tab has an unresolved packing request. Reopen it before changing this draft.');
   env.storage.setItem(key,JSON.stringify({plan:s.plan,stop:s.stop,lines:s.lines,pending:s.pending,pack:s.pack}));
  }
  function edit(){own();const stored=JSON.parse(env.storage.getItem(key)||'null');if(s.pending||stored?.pending)fail('Read back or retry the original request before changing it.');}
  async function lockedRead(work){
   own();if(s.busy)return;if(!env.locks?.request)fail('Supported browser Web Locks are required to resolve packing requests.');
   s.busy=true;changed();try{return await env.locks.request(key,async()=>{own();restore();return work();});}finally{s.busy=false;changed();}
  }
  const choices=()=>s.context?.stops||s.context?.lines||[];
  async function load(plan=s.plan,stop=s.stop){edit();const context=await env.rpc('packing_context',{dispatch_plan:plan,stop_key:stop||null,operator_session_token:env.token()});own();s.plan=plan;s.stop=context.stop_key||'';s.context=context;s.source=null;s.selected=null;s.page=0;s.pack=null;save();changed();}
  async function source(value){edit();if(!s.plan||!s.stop)fail('Select the exact customer stop first.');s.source=null;s.selected=null;s.qty='';changed();const context=await env.rpc('packing_context',{dispatch_plan:s.plan,stop_key:s.stop,source_scan:value,operator_session_token:env.token()});own();s.context=context;s.source=context.source;s.selected=context.lines.length===1?context.lines[0].name:null;s.qty='';s.page=0;changed();}
  async function select(number){edit();const row=choices()[s.page*10+number-1];if(!row)fail('Choose a displayed number.');if(s.context.stops)return load(s.plan,row.stop_key);s.selected=row.name;changed();}
  function quantity(value){edit();if(!Number.isFinite(Number(value))||Number(value)<=0)fail('Enter a positive stock UOM quantity.');s.qty=String(value);changed();}
  function add(){edit();if(!s.source||!s.selected||!s.qty)fail('Scan the source, select its Plan row and enter quantity first.');const target=s.context.lines.find(r=>r.name===s.selected),qty=Number(s.qty),prior=s.lines.filter(r=>r.dispatch_plan_line===s.selected).reduce((n,r)=>n+Number(r.qty),0);if(qty>Number(s.source.available_qty)||qty+prior>Number(target.remaining_qty))fail('Packed quantity exceeds source availability or the remaining Plan request.');if(s.lines.some(r=>r.source_scan===s.source.scan))fail('This source is already in the pack. Remove its line before correcting the quantity.');s.lines.push({dispatch_plan_line:s.selected,source_scan:s.source.scan,qty,item_code:s.source.item_code,batch_no:s.source.batch_no,stock_uom:s.source.stock_uom});s.source=null;s.qty='';s.selected=null;save();s.message='Line added. Scan the next source or Confirm to create one Loose Tag.';changed();}
  function remove(){edit();if(!s.lines.length)fail('There are no draft packed lines.');s.lines.pop();save();changed();}
  async function write(method,args){
   own();if(s.busy)return;if(!env.locks?.request)fail('Supported browser Web Locks are required for safe packing retries.');
   s.busy=true;changed();try{return await env.locks.request(key,async()=>{
    own();restore();if(s.pack&&method==='create_loose_tag'&&!s.pending)fail('This draft was recorded in another tab. Read its Loose Tag before starting another pack.');if(s.pending&&(s.pending.method!==method||JSON.stringify(s.pending.args)!==JSON.stringify(args)))fail('Another tab has a pending packing action. Reopen it to read back its original request.');
    if(!s.pending){s.pending={method,args};save();}
    const original=s.pending;const result=await env.rpc(original.method,{...original.args,operator_session_token:env.token()});own();s.pending=null;s.pack=result;s.lines=[];save(original);s.message=result.state==='Cancelled'?'Pack cancelled; its QR cannot be reused.':'Loose Tag recorded. Print its QR, then use normal loading.';changed();return result;
   });}finally{s.busy=false;changed();}
  }
  async function confirm(){own();if(s.pending)return write(s.pending.method,s.pending.args);if(s.arm==='cancel'){if(!s.pack||!s.reason)fail('Read the Loose Tag and enter the cancellation reason first.');return write('cancel_loose_tag',{scan_value:s.pack.qr_payload||s.pack.name,reason:s.reason,event_token:env.nonce()});}if(!s.plan||!s.stop||!s.lines.length)fail('Add the packed source lines before confirming.');return write('create_loose_tag',{dispatch_plan:s.plan,stop_key:s.stop,lines:s.lines.map(({dispatch_plan_line,source_scan,qty})=>({dispatch_plan_line,source_scan,qty})),event_token:env.nonce()});}
  async function readback(){return lockedRead(async()=>{
   if(!s.pending){if(s.pack){s.pack=await env.rpc('get_loose_tag',{scan_value:s.pack.name,operator_session_token:env.token()});own();save();changed();return;}fail('No pending request or Loose Tag to read back.');}
   const original=s.pending;
   if(original.method==='cancel_loose_tag'){
    const pack=await env.rpc('get_loose_tag',{scan_value:original.args.scan_value,operator_session_token:env.token()});own();
    if(pack.state==='Cancelled'){s.pending=null;s.pack=pack;save(original);}else s.message='Cancellation is not recorded; retry the original cancellation.';
   }else{
    const result=await env.rpc('read_packing_request',{...original.args,operator_session_token:env.token()});own();
    if(result.recorded){s.pending=null;s.pack=result.pack;s.lines=[];save(original);}else s.message='Packing is not recorded. Retry, or enter a reason and Void Pending to prevent a late request.';
   }
   changed();
  });}
  async function abandon(){return lockedRead(async()=>{
   if(!s.pending||s.pending.method!=='create_loose_tag'||!s.reason)fail('A pending packing request and abandonment reason are required.');
   const original=s.pending;
   const result=await env.rpc('void_packing_request',{...original.args,reason:s.reason,operator_session_token:env.token()});own();
   s.pending=null;s.pack=result;s.lines=[];save(original);changed();
  });}
  async function scan(raw){
   const value=String(raw||'').trim(),upper=value.toUpperCase();if(!value)return;own();
   if(upper==='CFG:CMD:CANCEL'){s.closed=true;env.close();return;}
   if(upper==='CFG:CMD:CONFIRM'||upper==='CFG:CMD:LOOSE_TAG_CREATE')return confirm();
   if(upper==='CFG:CMD:LOOSE_TAG_READBACK')return readback();
   if(upper==='CFG:CMD:LOOSE_TAG_VOID')return abandon();
   if(upper==='CFG:CMD:LOOSE_TAG_REASON'){s.arm='reason';changed();return;}
   if(s.arm==='reason'&&!upper.startsWith('CFG:')){s.reason=value;s.arm=s.pack?'cancel':'';changed();return;}
   if(upper==='CFG:CMD:LOOSE_TAG_PRINT'){if(!s.pack||['Cancelled','Building'].includes(s.pack.state))fail('Create a usable Loose Tag before printing.');return env.print(s.pack);}
   if(upper==='CFG:CMD:LOOSE_TAG_CAMERA')return env.camera();
   if(upper==='CFG:CMD:HELP'){s.message='Scan DPL; shared pools require a numbered customer stop. Scan each source Stock Tag, select a Plan row if ambiguous, scan CFG:QTY:MATERIAL:n, LOOSE_TAG_ADD. Confirm creates one pack. CANCEL_LOOSE_TAG, pack QR, LOOSE_TAG_REASON, reason, Confirm undoes an unused unclaimed pack. LOOSE_TAG_PRINT opens native Print Format selection. Read Back / Void Pending safely resolve unknown creates. Cancel exits without losing the original request.';changed();return;}
   edit();
   if(upper==='CFG:CMD:CANCEL_LOOSE_TAG'){s.arm='cancel';s.message='Scan the unused Loose Tag, then enter its cancellation reason.';changed();return;}
   if(upper==='CFG:CMD:PACK_LOOSE_TAG'||upper==='CFG:CMD:LOOSE_TAG_PLAN'){s.arm='plan';s.pack=null;save();changed();return;}
   if(upper==='CFG:CMD:LOOSE_TAG_SOURCE'){s.arm='source';return;}
   if(upper==='CFG:CMD:LOOSE_TAG_ADD')return add();
   if(upper==='CFG:CMD:LOOSE_TAG_REMOVE')return remove();
   if(['CFG:CMD:NEXT_MATERIALS','CFG:CMD:PREVIOUS_MATERIALS'].includes(upper)){s.page=Math.max(0,Math.min(Math.ceil(choices().length/10)-1,s.page+(upper.includes('NEXT_')?1:-1)));changed();return;}
   const n=upper.match(/^CFG:SELECT:(10|[1-9])$/);if(n)return select(Number(n[1]));
   const q=upper.match(/^CFG:QTY:MATERIAL:(.+)$/);if(q)return quantity(q[1]);
   if(value.startsWith('CFG:LOOSE:')||value.startsWith('KLT-')){s.pack=await env.rpc('get_loose_tag',{scan_value:value,operator_session_token:env.token()});own();save();changed();return;}
   if(s.arm==='plan'||value.startsWith('DPL-')){if(s.lines.length)fail('Remove the draft packed lines before changing their Plan.');s.arm='';return load(value,'');}
   if(s.arm==='source')s.arm='';return source(value);
  }
  return {state:s,scan,load,source,select,quantity,add,remove,confirm,readback,abandon,choices,save};
 }
 async function open(options){
  const f=options.frappe,e=f.utils.escape_html,openedOwner=options.owner();let dialog,c,camera=null,tail=Promise.resolve();
  const focus=()=>{if(!c.state.closed&&options.owner()===openedOwner)dialog.fields_dict.scan.$input.trigger('focus');};
  const queue=work=>{tail=tail.then(work).catch(error=>{c.state.message=options.errorMessage(error,error.message||'Loose Tag action failed.');render(c.state);}).finally(focus);return tail;};
  function stopCamera(){camera?.hide_dialog?.();camera?.dialog?.hide?.();camera=null;}
  function startCamera(){if(camera||c.state.closed)return;if(!f.ui.Scanner)throw new Error('Use the scanner field; camera is unavailable.');let accepted=false;camera=new f.ui.Scanner({dialog:true,multiple:false,on_scan:data=>{if(accepted)return;accepted=true;stopCamera();queue(()=>c.scan(data.decodedText));}});camera.dialog?.$wrapper?.one('hidden.bs.modal',()=>{accepted=true;camera=null;focus();});}
  function render(s){
   const hidden=options.owner()!==openedOwner;
   const lines=(s.pack?.lines||s.lines).map((r,i)=>`<tr><td>${i+1}. ${e(r.item_code||r.source_scan)}</td><td>${e(r.batch_no||'—')}</td><td>${e(r.qty)} ${e(r.stock_uom||'')}</td><td>${e(r.source_visible_code||r.source_scan||'')}</td><td>${e(r.remaining_qty??'')}</td></tr>`).join('');
   const choices=c.choices().slice(s.page*10,s.page*10+10).map((r,i)=>`<button type="button" class="btn btn-default loose-choice" data-n="${i+1}">${i+1}. ${e(r.site_name||r.item_code)} · ${e(r.stock_uom||r.customer||'')} ${e(r.remaining_qty??'')}${s.selected===r.name?' ✓':''}</button>`).join(' ');
   dialog.fields_dict.summary.$wrapper.html(hidden?'<p>Identify the original operator.</p>':`<div class="alert ${s.pending?'alert-warning':'alert-info'}">${e(s.message)}</div><p>${e(s.plan)} · ${e(s.context?.site_name||s.pack?.customer||'')} · ${e(s.pack?.name||'')} ${e(s.pack?.state||'')}</p><div>${choices}</div><table class="table"><tr><th>Item</th><th>Batch</th><th>Packed</th><th>Original source</th><th>Remaining</th></tr>${lines}</table><p>${e(s.source?.visible_code||'')} · ${e(s.qty)} ${e(s.source?.stock_uom||'')} · ${e(s.reason)}</p>${s.pending?'<p>Unknown result retained. Read Back or retry the exact original request.</p>':''}`);
   dialog.fields_dict.summary.$wrapper.find('.loose-choice').on('click',function(){queue(()=>c.select(Number(this.dataset.n)));});
   if(String(dialog.get_value('qty')||'')!==s.qty)dialog.set_value('qty',s.qty||null);
   if(s.busy||hidden)dialog.disable_primary_action();else dialog.enable_primary_action();
  }
  const command=name=>()=>queue(()=>c.scan('CFG:CMD:'+name));
  dialog=new f.ui.Dialog({title:'Multi-SKU Loose Tag',size:'extra-large',fields:[
   {fieldname:'scan',label:'Scanner / Plan / Stock Tag / Command',fieldtype:'Data'},
   {fieldname:'camera',label:'Scan with Camera',fieldtype:'Button',click:()=>queue(startCamera)},
   {fieldname:'summary',fieldtype:'HTML'},
   {fieldname:'qty',label:'Packed Qty (stock UOM)',fieldtype:'Float',precision:6,onchange:()=>{const qty=dialog.get_value('qty');if(qty&&String(qty)!==c.state.qty)queue(()=>c.quantity(qty));}},
   {fieldname:'add',label:'Add Packed Line',fieldtype:'Button',click:command('LOOSE_TAG_ADD')},
   {fieldname:'remove',label:'Remove Last Draft Line',fieldtype:'Button',click:command('LOOSE_TAG_REMOVE')},
   {fieldname:'next',label:'Next Choices',fieldtype:'Button',click:command('NEXT_MATERIALS')},
   {fieldname:'previous',label:'Previous Choices',fieldtype:'Button',click:command('PREVIOUS_MATERIALS')},
   {fieldname:'reason',label:'Correction / Cancellation Reason',fieldtype:'Small Text',onchange:()=>{c.state.reason=String(dialog.get_value('reason')||'').trim();}},
   {fieldname:'cancel_pack',label:'Cancel Unused Pack',fieldtype:'Button',click:command('CANCEL_LOOSE_TAG')},
   {fieldname:'read',label:'Read Back',fieldtype:'Button',click:command('LOOSE_TAG_READBACK')},
   {fieldname:'void',label:'Void Pending Create',fieldtype:'Button',click:command('LOOSE_TAG_VOID')},
   {fieldname:'print',label:'Print Loose Tag',fieldtype:'Button',click:command('LOOSE_TAG_PRINT')},
  ],primary_action_label:'Confirm',primary_action:()=>queue(()=>c.confirm())});
  c=createController({storage:options.storage||localStorage,locks:options.locks||navigator.locks,user:f.session.user,
   owner:options.owner,openedOwner,token:options.token,nonce:options.nonce,render,camera:startCamera,close:()=>dialog.hide(),
   print:pack=>{dialog.hide();f.set_route('Form','CFG Kanban Loose Tag',pack.name);},
   rpc:async(method,args)=>(await f.call({method:prefix+method,args})).message});
  dialog.onhide=()=>{c.state.closed=true;stopCamera();options.onClose();};
  dialog.fields_dict.scan.$input.on('keydown',event=>{if(!['Enter','Tab'].includes(event.key)||event.shiftKey||event.ctrlKey||event.altKey||event.metaKey||event.isComposing)return;const value=String(dialog.get_value('scan')||'').trim();if(!value)return;event.preventDefault();event.stopPropagation();dialog.set_value('scan','');queue(()=>c.scan(value));});
  dialog.show();render(c.state);focus();if(options.scan)await queue(()=>c.scan(options.scan));else if(options.plan&&!c.state.pending)await queue(()=>c.load(options.plan,''));
  return {scan:value=>queue(()=>c.scan(value)),focus,close:()=>dialog.hide(),controller:c};
 }
 const api={createController,open};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.cfg_loose_tags=api;
})(typeof window==='undefined'?globalThis:window);
