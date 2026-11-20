/* Scanner/touch confirmation of the existing allocation, ERP-details and proof actions. */
(function(root){
 'use strict';
 function createController(env){
  const s={closed:false,busy:false,pending:null,attempted:false,page:0,table:null,field:env.fields[0]?.name||'',message:'Review the action, then Confirm. Scan a field number to enter its value.'};
  const fail=message=>{throw new Error(message);},changed=()=>env.render(s);
  function edit(){if(env.owner()!==env.openedOwner)fail('Identify the original operator before continuing.');if(s.pending)fail('Retry the original submission before changing its details.');}
  function field(name){edit();if(!env.fields.some(row=>row.name===name))fail('This field is not available for scanner input.');s.field=name;s.table=null;changed();}
  function choices(){return s.table?s.table.fields:env.fields;}
  async function tableRow(step=0,add=false){
   edit();const field=env.fields.find(row=>row.name===s.field);
   if(field?.fieldtype!=='Table')fail('Select a table input before choosing a row.');
   const rows=JSON.parse(JSON.stringify(env.read(field.name)||[]));
   let index=add?rows.length:s.table?Math.max(0,Math.min(rows.length-1,s.table.index+step)):0;
   if(!rows.length||add){rows.push(Object.fromEntries((field.fields||[]).filter(c=>c.default!==undefined).map(c=>[c.fieldname,c.default])));index=rows.length-1;await env.set(field.name,rows);}
   const columns=(field.fields||[]).filter(c=>!c.read_only&&!['Section Break','Column Break','HTML'].includes(c.fieldtype)).map(c=>({...c,name:c.fieldname}));
   if(!columns.length)fail('This ERP table has no editable columns.');
   s.table={name:field.name,label:field.label,index,fields:columns,column:columns[0].name};s.page=0;changed();
  }
  async function value(raw){
   edit();if(!s.field)fail('Select a displayed field first.');
   if(s.table){const rows=JSON.parse(JSON.stringify(env.read(s.table.name)||[]));if(!rows[s.table.index])fail('Select the table row again.');rows[s.table.index][s.table.column]=raw;await env.set(s.table.name,rows);}
   else{if(env.fields.find(row=>row.name===s.field)?.fieldtype==='Table')fail('Use DELIVERY_ADD_ROW or DELIVERY_NEXT_ROW to enter the table.');await env.set(s.field,raw);}
   changed();
  }
  async function confirm(){
   if(s.closed||s.busy)return;if(env.owner()!==env.openedOwner)fail('Identify the original operator before confirming.');
   s.busy=true;changed();const retry=!!s.pending;
   try{
    if(!s.pending){const values=env.values();if(values===null||values===undefined)fail('Complete the required fields before confirming.');s.pending={values:JSON.parse(JSON.stringify(values)),event_token:env.nonce()};}s.attempted=true;
    await env.submit(s.pending.values,s.pending.event_token);
    if(s.closed)return;
    s.closed=true;env.close();
    if(env.owner()===env.openedOwner)await env.success();
   }catch(error){if(!retry&&(error?.exc_type||error?.responseJSON?.exc_type))s.pending=null;throw error;}
   finally{s.busy=false;changed();}
  }
  async function scan(raw){
   const text=String(raw||'').trim(),upper=text.toUpperCase();if(!text||s.closed)return;
   if(upper==='CFG:CMD:CANCEL'){s.closed=true;env.close();return;}
   if(upper==='CFG:CMD:CONFIRM')return confirm();
   if(upper==='CFG:CMD:DELIVERY_CAMERA')return env.camera();
   if(upper==='CFG:CMD:DELIVERY_RECIPIENT')return field('recipient_name');
   if(upper==='CFG:CMD:DELIVERY_ADD_ROW')return tableRow(0,true);
   if(upper==='CFG:CMD:DELIVERY_NEXT_ROW')return tableRow(1);
   if(upper==='CFG:CMD:DELIVERY_PREVIOUS_ROW')return tableRow(-1);
   if(upper==='CFG:CMD:DELIVERY_INPUTS'){edit();s.table=null;s.page=0;changed();return;}
   if(['CFG:CMD:NEXT_MATERIALS','CFG:CMD:PREVIOUS_MATERIALS'].includes(upper)){edit();s.page=Math.max(0,Math.min(Math.max(Math.ceil(choices().length/10)-1,0),s.page+(upper.includes('NEXT_')?1:-1)));changed();return;}
   if(upper==='CFG:CMD:HELP'){s.message='CFG:SELECT:1–10 chooses an input; scan its value. DELIVERY_RECIPIENT arms the name. Confirm submits the reviewed details; Cancel closes safely. NEXT/PREVIOUS_MATERIALS page fields. For a selected ERP table use DELIVERY_ADD_ROW or DELIVERY_NEXT_ROW, numbered columns and scanned values; DELIVERY_INPUTS returns to the main inputs. Tablet photo/signature tools remain available.';changed();return;}
   const selected=upper.match(/^CFG:SELECT:(10|[1-9])$/);
   if(selected){const row=choices()[s.page*10+Number(selected[1])-1];if(!row)fail('Choose a displayed field number.');if(s.table){edit();s.table.column=row.name;changed();return;}return field(row.name);}
   if(upper.startsWith('CFG:'))fail('Use a displayed delivery command.');
   return value(text);
  }
  return {state:s,field,value,tableRow,choices,confirm,scan};
 }
 function bind(options){
  const {dialog,frappe:f}=options;let controller,tail=Promise.resolve(),camera=null;
  const focus=()=>{if(!controller.state.closed)dialog.fields_dict.delivery_scanner.$input.focus();};
  function render(s){
   const e=f.utils.escape_html;
   dialog.fields_dict.delivery_scanner_help.$wrapper.html(`<p>${e(s.message)}</p>${s.pending?`<div class="alert alert-warning">Retry original details: ${e(JSON.stringify(s.pending.values))}</div>`:''}`+(s.table?`<p>${e(s.table.label||s.table.name)} · Row ${s.table.index+1}</p>`:'')+controller.choices().slice(s.page*10,s.page*10+10).map((field,index)=>`<div>${index+1}. ${e(field.label||field.name)}${(s.table?s.table.column:s.field)===field.name?' ✓':''}</div>`).join(''));
   if(s.busy)dialog.disable_primary_action();else dialog.enable_primary_action();
  }
  function queue(work){tail=tail.then(work).catch(error=>{controller.state.message=options.errorMessage(error,error.message||'Delivery action failed.');render(controller.state);}).finally(focus);return tail;}
  function stopCamera(){const current=camera;camera=null;current?.hide_dialog?.();}
  function startCamera(){
   if(camera||controller.state.closed)return;if(!f.ui.Scanner)throw new Error('Camera scanner is unavailable; use the Scanner field.');
   let accepted=false;camera=new f.ui.Scanner({dialog:true,multiple:false,on_scan:data=>{
    if(accepted||controller.state.closed)return;accepted=true;const text=String(data.decodedText||'').trim();stopCamera();if(text)queue(()=>controller.scan(text));
   }});const instance=camera;camera.dialog?.$wrapper?.one('hidden.bs.modal',()=>{accepted=true;if(camera===instance)camera=null;focus();});
  }
  controller=createController({...options,openedOwner:options.owner(),render,camera:startCamera,
   set:(name,value)=>dialog.set_value(name,value),read:name=>dialog.get_value(name),values:()=>dialog.get_values(),close:()=>dialog.hide()});
  const oldHide=dialog.onhide;dialog.onhide=()=>{controller.state.closed=true;stopCamera();oldHide?.();options.onClose();};
  dialog.set_primary_action(options.label,()=>queue(()=>controller.confirm()));
  dialog.fields_dict.delivery_scanner.$input.on('keydown',event=>{
   if(!['Enter','Tab'].includes(event.key)||event.shiftKey||event.ctrlKey||event.altKey||event.metaKey||event.isComposing)return;
   const value=String(dialog.get_value('delivery_scanner')||'').trim();if(event.key==='Tab'&&!value)return;
   event.preventDefault();event.stopPropagation();dialog.set_value('delivery_scanner','');if(value)queue(()=>controller.scan(value));
  });
  dialog.fields_dict.delivery_scanner_camera.df.click=()=>queue(()=>startCamera());
  dialog.show();render(controller.state);focus();return {scan:value=>queue(()=>controller.scan(value)),focus,controller};
 }
 function fields(){return [
  {fieldname:'delivery_scanner',label:'Scanner',fieldtype:'Data'},
  {fieldname:'delivery_scanner_camera',label:'Scan with Camera',fieldtype:'Button'},
  {fieldname:'delivery_scanner_help',fieldtype:'HTML'},
 ];}
 const api={createController,bind,fields};if(typeof module!=='undefined'&&module.exports)module.exports=api;
 root.cfg_delivery_action_scanner=api;
})(typeof window==='undefined'?globalThis:window);
