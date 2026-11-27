/* One customer-drop checklist, shared by Driver Route and Logistics. No stock posting. */
(function(root){
 'use strict';
 const esc=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
 function controller(env){
  const rows=env.check.rows||[],s={selected:null,qty:'',tag:'',page:0};
  const loose=()=>rows.filter(r=>!r.tagged&&!r.confirmed);
  const changed=()=>env.render?.(s);
  function choose(name){const row=loose().find(r=>r.name===name);if(!row)throw new Error('Select a pending untagged Item at this stop.');s.selected=name;s.qty='';s.tag='';changed();}
  function payload(){
   if(s.tag.trim())return {scan_value:s.tag.trim()};
   const row=loose().find(r=>r.name===s.selected);
   if(!row)throw new Error('Scan an assigned Stock Tag / box, or select an untagged Item and enter its checked quantity.');
   const qty=Number(s.qty);
   if(!String(s.qty).trim()||!Number.isFinite(qty)||qty<=0||Math.abs(qty-Number(row.qty))>0.000001)throw new Error(`Confirm exactly ${row.qty} ${row.stock_uom} of ${row.item_code}.`);
   return {delivery_allocation:row.name,item_code:row.item_code,qty};
  }
  async function submit(){if(env.valid&&!env.valid())throw new Error('Finish or reconcile the current request first.');return env.submit(payload());}
  async function scan(raw){
   const text=String(raw||'').trim(),upper=text.toUpperCase();if(!text)return;
   if(env.valid&&!env.valid())throw new Error('Finish or reconcile the current request first.');
   const select=upper.match(/^CFG:SELECT:(10|[1-9])$/),qty=text.match(/^CFG:QTY:MATERIAL:(.+)$/i);
   if(select){const row=loose()[s.page*10+Number(select[1])-1];if(!row)throw new Error('Choose a displayed untagged Item number.');return choose(row.name);}
   if(qty){if(!s.selected)throw new Error('Select the untagged Item first.');s.qty=qty[1];s.tag='';changed();return;}
   if(['CFG:CMD:NEXT_MATERIALS','CFG:CMD:PREVIOUS_MATERIALS'].includes(upper)){s.page=Math.max(0,Math.min(Math.max(0,Math.ceil(loose().length/10)-1),s.page+(upper.includes('NEXT_')?1:-1)));changed();return;}
   if(upper==='CFG:CMD:CONFIRM')return submit();
   if(upper==='CFG:CMD:VERIFY_DELIVERY_GOODS'){changed();return;}
   if(upper.startsWith('CFG:')&&!text.startsWith('CFG:LOOSE:'))throw new Error('Scan an assigned tag, SELECT an untagged Item, then QTY and CONFIRM.');
   s.tag=text;s.selected=null;s.qty='';changed();return submit();
  }
  return {state:s,choose,scan,submit,payload,loose,refresh:changed,tag(value){s.tag=String(value||'');if(s.tag){s.selected=null;s.qty='';}},quantity(value){s.qty=String(value??'');s.tag='';}};
 }
 function checklist(check){return `<div class="cfg-drop-checklist">${(check.rows||[]).map(r=>`<div class="p-2 mb-2 border ${r.confirmed?'alert-success':'alert-warning'}" data-drop-allocation="${esc(r.name)}" data-confirmed="${Boolean(r.confirmed)}"><strong>${esc(r.item_code)}</strong> · ${esc(r.qty)} ${esc(r.stock_uom)} · ${esc(r.batch_no||'No Batch')}<br>${esc(r.tagged?r.visible_code:'Untagged ERP stock')}${r.container_visible_code?' · '+esc(r.container_visible_code):''} · <b>${r.confirmed?'Checked':'Check required'}</b></div>`).join('')}</div>`;}
 function mount(options){
  const host=options.parent,f=options.frappe;let closed=false,camera=null;
  const valid=()=>!closed&&(!options.valid||options.valid());
  const focus=()=>{if(valid())host.find('.cfg-drop-scan').trigger('focus');};
  const report=async work=>{try{await work();}catch(error){host.find('.cfg-drop-message').text(options.error?options.error(error):error.message||String(error));}finally{focus();}};
  async function startCamera(){
   if(!valid()||camera)return;if(!f.ui.Scanner)throw new Error('Camera unavailable; use the Scanner field.');let accepted=false;
   camera=new f.ui.Scanner({dialog:true,multiple:false,on_scan:data=>{if(accepted||!valid())return;accepted=true;camera?.stop_scan?.();camera?.hide_dialog?.();camera?.dialog?.hide?.();camera=null;report(()=>c.scan(data.decodedText));}});
   camera.dialog?.$wrapper?.one?.('hidden.bs.modal.cfg_drop',()=>{camera=null;focus();});
  }
  host.html(`<p>Scan the accepted goods for this customer. For untagged goods, select the Item / Batch and confirm its exact quantity in stock UOM.</p>${checklist(options.check)}<div class="cfg-drop-message" role="status"></div><div class="cfg-drop-inputs"><label>Stock Tag / box / loaded bin QR</label><input class="form-control cfg-drop-scan" autocomplete="off"><button type="button" class="btn btn-default cfg-drop-camera">Scan with Camera</button><div class="cfg-drop-choices mt-3"></div><button type="button" class="btn btn-default cfg-drop-prev">Previous choices</button><button type="button" class="btn btn-default cfg-drop-next">Next choices</button><div class="cfg-drop-quantity mt-2"><label class="cfg-drop-qty-label"></label><input class="form-control cfg-drop-qty" type="number" inputmode="decimal" min="0" step="any" placeholder="Enter physically checked quantity"></div><button type="button" class="btn btn-primary cfg-drop-confirm mt-2">Confirm product check</button></div>`);
  const c=controller({check:options.check,valid,submit:options.submit,render:s=>{
   const choices=c.loose().slice(s.page*10,s.page*10+10),selected=c.loose().find(r=>r.name===s.selected);
   host.find('.cfg-drop-choices').html(choices.map((r,i)=>`<button type="button" class="btn btn-default cfg-drop-choice mb-2" data-allocation="${esc(r.name)}" aria-pressed="${r.name===s.selected}">${i+1}. ${esc(r.item_code)} / ${esc(r.batch_no||'No Batch')} · ${esc(r.qty)} ${esc(r.stock_uom)}</button>`).join(''));
   host.find('.cfg-drop-quantity').toggle(Boolean(selected));host.find('.cfg-drop-qty-label').text(selected?`${selected.item_code} / ${selected.batch_no||'No Batch'} · ${selected.qty} ${selected.stock_uom}`:'');
   host.find('.cfg-drop-qty').val(s.qty);host.find('.cfg-drop-scan').val(s.tag);
  }});
  host.find('.cfg-drop-inputs').toggle(!options.check.ready);
  host.on('click.cfg_drop','.cfg-drop-choice',event=>report(async()=>c.choose(root.$(event.currentTarget).attr('data-allocation'))))
   .on('input.cfg_drop','.cfg-drop-qty',event=>c.quantity(event.currentTarget.value))
   .on('input.cfg_drop','.cfg-drop-scan',event=>c.tag(event.currentTarget.value))
   .on('click.cfg_drop','.cfg-drop-confirm',()=>report(c.submit))
   .on('click.cfg_drop','.cfg-drop-next',()=>report(()=>c.scan('CFG:CMD:NEXT_MATERIALS')))
   .on('click.cfg_drop','.cfg-drop-prev',()=>report(()=>c.scan('CFG:CMD:PREVIOUS_MATERIALS')))
   .on('keydown.cfg_drop','.cfg-drop-scan',event=>{if(!['Enter','Tab'].includes(event.key)||event.shiftKey||event.ctrlKey||event.altKey||event.metaKey||event.isComposing)return;const value=event.currentTarget.value.trim();if(!value)return;event.preventDefault();event.stopPropagation();report(()=>c.scan(value));})
   .on('click.cfg_drop','.cfg-drop-camera',()=>report(startCamera));
  // Initialize after c exists: native controls may fire changes synchronously.
  c.refresh();
  return {scan:raw=>['CFG:CMD:DELIVERY_CAMERA','CFG:CMD:RETURN_CAMERA'].includes(String(raw||'').trim().toUpperCase())?startCamera():c.scan(raw),submit:c.submit,focus,controller:c,close(){closed=true;camera?.stop_scan?.();camera?.hide_dialog?.();camera?.dialog?.hide?.();camera=null;host.off('.cfg_drop');}};
 }
 function open(options){
  const f=options.frappe,owner=options.owner(),token=options.token();let closed=false,busy=false,pending=null,view=null,tail=Promise.resolve();
  const dialog=new f.ui.Dialog({title:'Verify Customer Delivery Goods',size:'large',fields:[{fieldname:'checks',fieldtype:'HTML'}]});
  const host=dialog.fields_dict.checks.$wrapper;
  const valid=()=>!closed&&options.owner()===owner&&options.token()===token&&(!options.active||options.active());
  const rpc=async(method,args)=>(await f.call({method,args})).message;
  const focus=()=>{if(valid())view?.focus();};
  const showError=error=>host.find('.cfg-drop-message').text(options.error(error));
  const queue=work=>{tail=tail.then(work).catch(showError).finally(focus);return tail;};
  async function load(){
   if(!valid()||busy)return;
   const delivery=await rpc('cfg_kanban.services.customer_delivery.get_delivery_session',{delivery_session:options.delivery.name,operator_session_token:token});
   if(!valid())return;view?.close();
   if(!delivery.product_verification?.required){host.text('This Session does not require a customer product check.');return;}
   view=mount({frappe:f,parent:host,check:delivery.product_verification,valid:()=>valid()&&!busy&&!pending,error:options.error,
    submit:async values=>{pending={values:JSON.parse(JSON.stringify(values)),id:options.nonce()};return send();}});
   dialog.set_primary_action(pending?'Retry original product check':'Refresh saved checks',()=>queue(()=>pending?send():load()));
   if(pending){host.find('.cfg-drop-inputs :input').prop('disabled',true);host.find('.cfg-drop-message').text('Original product check retained. Retry it before editing; no stock was moved.');}
   options.updated?.(delivery);focus();
  }
  async function send(){
   if(!valid()||busy)return;busy=true;dialog.disable_primary_action();host.find('.cfg-drop-inputs :input').prop('disabled',true);
   try{
    await rpc('cfg_kanban.services.delivery_product_scans.verify_delivery_goods',{delivery_session:options.delivery.name,event_token:pending.id,operator_session_token:token,payload:JSON.stringify(pending.values)});
    pending=null;
   }catch(error){if(error?.exc_type||error?.responseJSON?.exc_type)pending=null;throw error;}
   finally{busy=false;if(valid()){dialog.enable_primary_action();await load();}}
  }
  dialog.onhide=()=>{closed=true;view?.close();options.onClose();};dialog.show();queue(load);
  return {focus,close:()=>dialog.hide(),scan:value=>queue(async()=>{
   const text=String(value||'').trim().toUpperCase();
   if(text==='CFG:CMD:CANCEL'){dialog.hide();return;}
   if(pending)return send();
   if(text==='CFG:CMD:REFRESH')return load();
   if(text==='CFG:CMD:HELP'){host.find('.cfg-drop-message').text('Scan each allocated tag or box. Untagged: SELECT 1–10, CFG:QTY:MATERIAL:<count>, CONFIRM. NEXT/PREVIOUS_MATERIALS pages Items. Camera is available. Cancel returns to Logistics; saved checks remain.');return;}
   return view?.scan(value);
  })};
 }
 const api={controller,checklist,mount,open};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.cfg_delivery_product_checks=api;
})(typeof window==='undefined'?globalThis:window);
