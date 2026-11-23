/* Native-format driver documents, durable requests, and explicit Label Bridge handoff. */
(function(root,factory){const api=factory(root);if(typeof module==='object'&&module.exports)module.exports=api;else root.cfg_driver_mobile_print=api;})(typeof window==='undefined'?globalThis:window,function(root){
 'use strict';
 const service='cfg_kanban.services.mobile_printing.';
 let memoryKey=null;
 function forget(){memoryKey?.signer.forget();memoryKey=null;}
 const commands=['MOBILE_PRINT','PRINT_NATIVE','PRINT_SEND','PRINT_OPEN','PRINT_CONFIRM','PRINT_UNKNOWN','PRINT_SETUP','PRINT_PAIR','PRINT_FORGET','CREATE_DRIVER_INVOICE','CREATE_RETURN_LABEL','MOBILE_PRINT_BACK'];
 function nativeLink(entry,format,noLetterhead){return '/printview?'+new URLSearchParams({doctype:entry.doctype,name:entry.name,format,no_letterhead:noLetterhead?'1':'0'});}
 function unfinishedJobs(jobs,e){return jobs.map(row=>{
  const label=[row.name,row.document_name,row.status,row.operator,row.delivery_trip,row.stop_key||'Trip documents'].filter(Boolean).map(e).join(' · ');
  return row.can_resume===false?`<div class="mt-2">${label}<br><a class="btn btn-default" href="/app/cfg-kanban-mobile-print-job/${encodeURIComponent(row.name)}" target="_blank" rel="noopener">Open Print Job for Office Recovery</a><small>Another operator or Trip owns this job. Office closure requires authority and a reason.</small></div>`:`<button class="btn btn-default" data-mobile="resume" data-job="${e(row.name)}">Resume / Review · ${label}</button>`;
 }).join('');}
 function copies(frames,count){if(!Number.isInteger(count)||count<1||count>5)throw new Error('Select one to five copies.');const out=[];for(let n=0;n<count;n++)out.push(...frames);if(out.length>1000)throw new Error('Too many print segments; use normal ERPNext printing.');return out;}
 function nextPage(job,frames){for(let n=1;n<=frames.length;n++)if(job.segments?.pages?.[String(n)]?.status!=='Operator Confirmed')return n;return null;}
 function open(options){
  const f=options.frappe,host=options.host,e=f.utils.escape_html,bridge=root.cfg_mobile_print_bridge;
  if(!bridge||!root.cfg_driver_route_actions)throw new Error('Printing assets are unavailable; refresh the driver page.');
  const owner=options.owner(),token=options.token();let signer=bridge.signer();
  let closed=false,mode='choose',context=null,controls={},fields=[],scanner=null,camera=null,cameraVersion=0,version=0,
      prefs=null,prefStore=null,job=null,frames=[],prepared=null,handed=false,loading=false,message='',requirements=null,
      jobName=null,jobStop=options.stop||null,releaseLease=null,leaseReady=false,selected=null,selectedLabel=null;
  let tail=Promise.resolve();const inputLocks=new WeakMap();
  const valid=()=>!closed&&options.active()&&options.owner()===owner&&options.token()===token;
  const rpc=async(method,args)=>{const answer=(await f.call({method,args:{...args,operator_session_token:token}})).message;if(!valid())throw new Error('Operator or page changed.');return answer;};
  const focus=()=>{if(valid())host.find('.cfg-mobile-scan').trigger('focus');};
  function stopCamera(){cameraVersion++;try{camera?.stop_scan?.();camera?.dialog?.hide?.();}catch(_){}camera=null;}
  function queue(work){tail=tail.then(async()=>{if(!valid())return;try{await work();}catch(error){if(valid()){message=options.error(error);update();}}finally{focus();}});return tail;}
  function field(df,target='.cfg-mobile-fields'){const node=$('<div class="mt-3"></div>').appendTo(host.find(target));const control=f.ui.form.make_control({parent:node,df,render_input:true});controls[df.fieldname]=control;fields.push({...df,name:df.fieldname,control});if(df.default!==undefined)control.set_value(df.default);return control;}
  function value(key){const control=controls[key];return control?.df.fieldtype==='Table'?(control.grid?.get_data?.()||control.get_value?.()||[]):control?.get_value?.();}
  function values(){return Object.fromEntries(fields.map(row=>[row.name,value(row.name)]));}
  function selectedEntry(){const index=Number(value('document'))-1;return value('document')!==''&&Number.isInteger(index)?context.documents[index]:null;}
  function update(){if(!valid())return;
   host.find('.cfg-mobile-message').text(message||c.state.message||'');
   const pending=c.state.pending,busy=loading||c.state.busy;
   for(const node of host.find('.cfg-mobile-fields')[0]?.querySelectorAll('input,select,textarea,button')||[]){
    if(busy||pending){if(!inputLocks.has(node))inputLocks.set(node,node.disabled);node.disabled=true;}
    else if(inputLocks.has(node)){node.disabled=inputLocks.get(node);inputLocks.delete(node);}
   }
   host.find('[data-mobile]').prop('disabled',busy);
   host.find('[data-mobile="retry"],[data-mobile="readback"]').toggle(!!pending);
   host.find('[data-mobile="confirm"]').prop('disabled',busy||!!pending);
   host.find('.cfg-mobile-pending').text(pending?`Unconfirmed ${pending.request.action}. Original details are retained. Retry or read back the result before editing.`:'');
   if(mode==='choose'){
    const entry=selectedEntry(),format=value('format');
    const href=entry&&format&&!pending&&!busy?nativeLink(entry,format,value('no_letterhead')):null;
    const link=host.find('.cfg-mobile-native');if(href)link.attr('href',href).removeAttr('aria-disabled');else link.removeAttr('href').attr('aria-disabled','true');
   }
  }
  async function lease(){if(leaseReady)return;if(!options.locks?.request)throw new Error('Direct printing requires HTTPS and Web Locks.');
   await new Promise((resolve,reject)=>{options.locks.request('cfg_mobile_print_device', {ifAvailable:true},async lock=>{
    if(!lock){reject(new Error('Another tab has the printer panel open. Close it before sending another print.'));return;}
    if(!valid()){resolve();return;}leaseReady=true;resolve();await new Promise(done=>{releaseLease=done;});
   }).catch(reject);});
  }
  async function load(){loading=true;update();const ticket=++version;
   try{const next=await rpc(service+'get_mobile_print_context',{trip_name:options.trip,stop_key:options.stop||null});if(ticket!==version||!valid())return;context={...next,dispatch_plan:null};
    if(memoryKey&&memoryKey.owner===owner&&memoryKey.token===token&&memoryKey.company===next.company){if(signer!==memoryKey.signer)signer.forget();signer=memoryKey.signer;}else{forget();memoryKey={owner,token,company:next.company,signer};}
    prefStore=bridge.preferences(options.storage,root.location.origin,next.company);prefs=prefStore.load(next.defaults);mode='choose';draw();}
   finally{loading=false;update();}
  }
  async function showJob(name){jobName=name;mode='job';prepared=null;handed=false;loading=true;if(job?.name!==name){job=null;frames=[];}draw();const ticket=++version;
   const original=context.active_jobs.find(row=>row.name===name);jobStop=original?(original.stop_key||null):(options.stop||null);
   try{const next=await rpc(service+'get_mobile_print_job',{trip_name:options.trip,print_job:name});if(ticket!==version||!valid())return;
    if(Object.prototype.hasOwnProperty.call(next,'stop_key'))jobStop=next.stop_key||null;
    const dimensions=prefStore.validate(next.printer_settings||prefs),settings=JSON.stringify(dimensions),old=job;job=next;
    if(!frames.length||old?.name!==next.name||old?.render_hash!==next.render_hash||old?.settings!==settings){const rendered=await bridge.render(next.html,dimensions);if(ticket!==version||!valid())return;frames=copies(rendered,Number(next.copies));}
    job.settings=settings;mode='job';draw();
   }finally{loading=false;update();}
  }
  async function recorded(receipt){if(!valid())return;message='';const result=receipt.result||{};
   if(receipt.action==='Prepare Mobile Print'){await showJob(result.print_job);return;}
   if(receipt.action==='Record Print Segment'){
    if(result.job_status==='Operator Confirmed'){message='All segments were confirmed by the operator. This is not a printer acknowledgement.';job=null;frames=[];jobName=null;await load();return;}
    await showJob(result.print_job);
    if(result.outcome==='Awaiting Confirmation'&&frames.length){const page=nextPage(job,frames);prepared=await signer.prepare(frames[page-1].payload);handed=false;draw();}
    return;
   }
   if(receipt.action==='Close Mobile Print'){job=null;frames=[];jobName=null;await load();return;}
   await options.refresh();if(!valid())return;
   await load();
   message=result.invoice?`Invoice ${result.invoice} · ${result.docstatus===1?'Submitted':'Draft'}${result.existing_draft?' · existing office draft reused':''}`:result.custody_label?`Custody label ${result.custody_label} created. Select it below to print.`:'Action recorded.';
   update();
  }
  const c=root.cfg_driver_route_actions.controller({storage:options.storage,locks:options.locks,owner:options.owner,token:options.token,nonce:options.nonce,
   rpc,render:update,success:recorded});
  function formats(){selected=selectedEntry();if(!selected)return;
   const saved=prefs.formats[selected.doctype];const choices=selected.formats;
   const chosen=choices.includes(saved)?saved:selected.default_format;
   controls.format.df.options=choices;controls.format.refresh();controls.format.set_value(chosen);update();}
  function bindScanner(){if(!root.cfg_delivery_action_scanner)return;
   scanner=root.cfg_delivery_action_scanner.createController({fields,owner:options.owner,openedOwner:owner,
    editable:()=>!loading&&!c.state.busy&&!c.state.pending,
    values,nonce:options.nonce,set:async(name,val)=>{if(c.state.pending||c.state.busy||loading)throw new Error('Resolve the original request before editing.');if(!controls[name])throw new Error('Choose a displayed input.');if(controls[name].df.cannot_add_rows&&Array.isArray(val)&&val.length!==(value(name)||[]).length)throw new Error('Fill the mapped Invoice rows; adding or deleting source Items is not allowed.');await controls[name].set_value(val);},
    read:name=>value(name),render:s=>{if(valid())host.find('.cfg-mobile-input-help').text((s.message||'')+' '+scanner.choices().slice(s.page*10,s.page*10+10).map((row,index)=>`${index+1}. ${row.label||row.name}`).join(' · '));},
    submit:()=>confirm(),success:()=>{},close:()=>{},camera:startCamera});
   host.find('.cfg-mobile-input-help').text(fields.map((row,index)=>`${index+1}. ${row.label}`).join(' · '));
  }
  function invoiceERPFields(){return root.cfg_dispatch_recovery.erpFields(requirements?.fields||[]).map((df,index)=>requirements.fields[index]?.fieldname==='items'?{...df,cannot_add_rows:true,cannot_delete_rows:true}:df);}
  function draw(){if(!valid())return;stopCamera();controls={};fields=[];scanner=null;
   host.html(`<section class="frappe-card p-4 cfg-mobile-panel"><h3>Driver documents &amp; printing</h3><div class="cfg-mobile-message" role="status" aria-live="polite"></div><div class="cfg-mobile-pending alert-warning"></div>
    <div class="cfg-mobile-tools"><button class="btn btn-default" data-mobile="back">Documents</button><button class="btn btn-default" data-mobile="setup">Printer Setup</button><button class="btn btn-default" data-mobile="invoice">Create Invoice</button><button class="btn btn-default" data-mobile="label">Create Return Custody Label</button><button class="btn btn-default" data-mobile="close">Close</button></div>
    <div class="cfg-mobile-body"></div><div class="cfg-mobile-fields"></div><div class="cfg-mobile-preview"></div><div class="cfg-mobile-handoff"></div>
    <div class="cfg-mobile-controls"><button class="btn btn-primary" data-mobile="confirm">Confirm</button><button class="btn btn-default" data-mobile="retry">Retry original request</button><button class="btn btn-default" data-mobile="readback">Read back result</button></div>
    <div class="cfg-mobile-scan-row"><input class="form-control cfg-mobile-scan" autocomplete="off" placeholder="Scanner ready"><button class="btn btn-default" data-mobile="camera">Scan with Camera</button></div><small class="cfg-mobile-input-help"></small></section>`);
   const body=host.find('.cfg-mobile-body'),confirmButton=host.find('[data-mobile="confirm"]');
   if(!context){body.html('<p>Loading office printer setup…</p><a class="btn btn-default" href="/app/cfg-kanban-mobile-print-profile">Open Office Mobile Print Profiles</a>');confirmButton.hide();update();return;}
   if(mode==='choose'){
    body.html(`<p>${e(context.company)} · ${e(prefs.alias||'Label Bridge companion app')} · ${e(prefs.printable_width)} dots / ${e(prefs.dpi)} DPI</p><p>Choose a document and its ERPNext Print Format. Preview every segment before a direct print. Printer pairing and Bluetooth selection are handled in the companion app.</p><a class="btn btn-default cfg-mobile-native" target="_blank" rel="noopener">Normal ERPNext Print</a>`);
    field({fieldname:'document',label:'Document',fieldtype:'Select',options:[{label:'Choose a document',value:''},...context.documents.map((row,index)=>({label:(index+1)+'. '+row.name+' · '+row.label+(row.docstatus===0&&['Sales Invoice','Delivery Note','Credit Note'].includes(row.doctype)?' · Draft':''),value:String(index+1)}))],default:'',change:formats});
    field({fieldname:'format',label:'ERPNext Print Format',fieldtype:'Select',options:['Standard'],default:'Standard',change:update});
    field({fieldname:'copies',label:'Complete copies (1–5)',fieldtype:'Int',default:1});
    field({fieldname:'no_letterhead',label:'No letterhead',fieldtype:'Check',default:0,change:update});
    field({fieldname:'reason',label:'Reprint reason (required for an already printed tag)',fieldtype:'Small Text'});
    confirmButton.text('Prepare Direct Print');
    if(context.active_jobs.length)body.append(`<div class="mt-3"><b>Unfinished print jobs</b><p>Resume your own job on this Trip here, keeping its original stop. For another operator or Trip, ask the office to review and close the original job with a reason. Check the paper first; closing does not confirm printing or cancel the document.</p>${unfinishedJobs(context.active_jobs,e)}</div>`);
   }else if(mode==='setup'){
    body.html(`<p>Saved settings belong to this browser and Company. Select/pair the Bluetooth printer inside Label Bridge. Its signing key stays in this tab’s memory.</p><a class="btn btn-default" href="/app/cfg-kanban-mobile-print-profile/${encodeURIComponent(context.profile)}">Open Office Print / Invoice Policy</a>`);
    field({fieldname:'alias',label:'Device printer name (reference only)',fieldtype:'Data',default:prefs.alias});
    field({fieldname:'paper_width_mm',label:'Paper width (mm)',fieldtype:'Float',default:prefs.paper_width_mm});
    field({fieldname:'printable_width',label:'Printable width (dots, multiple of 8)',fieldtype:'Int',default:prefs.printable_width});
    field({fieldname:'dpi',label:'Printer DPI',fieldtype:'Int',default:prefs.dpi});
    field({fieldname:'signing_key',label:'Companion app signing key (not saved)',fieldtype:'Password'});
    body.append('<button class="btn btn-default" data-mobile="pair">Pair Key for This Tab</button><button class="btn btn-default" data-mobile="forget">Forget Key</button><button class="btn btn-default" data-mobile="reset">Reset Device Settings</button>');
    confirmButton.text('Save Device Settings');
   }else if(mode==='invoice'){
    body.text(`Office policy: ${context.invoice_mode}. Invoice creation is a separate accounting action, with native numbering, taxes and billing checks. It does not issue stock again.`);
    field({fieldname:'delivery_note',label:'Submitted Delivery Note',fieldtype:'Select',options:['',...context.invoice_sources],default:context.invoice_sources.length===1?context.invoice_sources[0]:'',change:()=>queue(invoiceFields)});
    host.find('.cfg-mobile-fields').append('<div class="cfg-mobile-erp-fields"></div>');
    if(requirements)for(const df of invoiceERPFields())field(df,'.cfg-mobile-erp-fields');
    confirmButton.text(context.invoice_mode==='Automatic Submission'?'Create and Submit Invoice':'Create Invoice Draft');
   }else if(mode==='label'){
    body.html('<div class="alert alert-warning">Old customer return custody only. Pending QC — not available stock. This creates neither ERP stock nor customer credit.</div>');
    field({fieldname:'return_line',label:'Collected return Item row',fieldtype:'Select',options:[{label:'Choose a returned Item',value:''},...context.custody_lines.map((row,index)=>({label:(index+1)+'. '+row.return_case+' · '+row.item_code+' · '+row.remaining_qty+' '+row.stock_uom+' · '+(row.batch_no||'No Batch')+' · '+(row.expiry_date||'No expiry'),value:String(index+1)}))],default:'',change:()=>{selectedLabel=value('return_line')!==''?context.custody_lines[Number(value('return_line'))-1]:null;if(selectedLabel)controls.qty.set_value(selectedLabel.remaining_qty);}});
    field({fieldname:'qty',label:'Quantity on this custody label (stock UOM)',fieldtype:'Float'});confirmButton.text('Create Custody Label');
   }else if(mode==='job'){
    body.html(`<p>${e(jobName)} · ${e(job?.document_name||'')} · ${e(job?.print_format||'')}</p><p>Label Bridge does not acknowledge paper output. After opening it, check the receipt and confirm this segment before continuing. An uncertain result is never retried automatically.</p>`);
    field({fieldname:'reason',label:'Reason for retry or closing an unfinished job',fieldtype:'Small Text'});
    field({fieldname:'signing_key',label:'Pair companion key if needed (not saved)',fieldtype:'Password'});
    body.append('<button class="btn btn-default" data-mobile="pair">Pair Key</button><button class="btn btn-default" data-mobile="abandon">Close Unfinished Job</button>');
    if(job&&frames.length){const page=nextPage(job,frames),frame=frames[page-1],prior=job.segments?.pages?.[String(page)];
     body.append(`<p><b>Segment ${page} of ${frames.length} · ${e(prior?.status||'Not handed off')}</b></p>`);
     const canvas=root.document.createElement('canvas');canvas.width=frame.width;canvas.height=frame.height;
     const ctx=canvas.getContext('2d'),image=ctx.createImageData(frame.width,frame.height);
     for(let pixel=0;pixel<frame.width*frame.height;pixel++){const color=frame.bytes[pixel>>3]&(128>>(pixel&7))?0:255,at=pixel*4;image.data[at]=color;image.data[at+1]=color;image.data[at+2]=color;image.data[at+3]=255;}ctx.putImageData(image,0,0);
     canvas.className='cfg-mobile-raster';host.find('.cfg-mobile-preview').append(canvas);
     if(prepared&&!handed)host.find('.cfg-mobile-handoff').html('<a href="#" class="btn btn-primary cfg-mobile-open-bridge">Open Label Bridge for This Segment</a>');
     confirmButton.text(prior?'Prepare Explicit Retry of This Segment':'Prepare This Segment for Handoff');
     if(prior)body.append('<button class="btn btn-success" data-mobile="printed">Confirm This Segment Printed</button><button class="btn btn-default" data-mobile="unknown">Outcome Unknown</button>');
    }else{body.append('<p>Preparing preview, or the source has changed. Close this job with a reason if it cannot be resumed.</p>');confirmButton.hide();}
   }
   bindScanner();update();focus();
  }
  async function invoiceFields(){const name=value('delivery_note');if(requirements?.delivery_note===name)return;requirements=null;host.find('.cfg-mobile-erp-fields').empty();
   fields=fields.filter(row=>row.name==='delivery_note');controls=Object.fromEntries(fields.map(row=>[row.name,row.control]));
   if(!name){bindScanner();return;}const ticket=++version;
   const next=await rpc(service+'get_driver_invoice_requirements',{trip_name:options.trip,stop_key:options.stop,delivery_note:name});if(ticket!==version||mode!=='invoice')return;
   if(next.profile_version!==context.profile_version||next.invoice_mode!==context.invoice_mode)throw new Error('Office Invoice policy changed. Refresh Documents and review the current policy.');
   requirements=next;
   if(next.existing_draft)message=`Existing draft ${next.existing_draft} will be reused and will not be auto-submitted.`;
   for(const df of invoiceERPFields())field(df,'.cfg-mobile-erp-fields');
   bindScanner();update();
  }
  async function confirm(){if(loading||c.state.busy||c.state.pending)throw new Error('Resolve the original request before confirming new details.');
   if(mode==='setup'){const v=values();prefs=prefStore.save({...v,formats:prefs.formats});message='Device settings saved. The signing key was not saved.';mode='choose';draw();return;}
   if(mode==='choose'){const entry=selectedEntry();if(!entry)throw new Error('Choose a document first.');await lease();
    prefs=prefStore.save({...prefs,formats:{...prefs.formats,[entry.doctype]:value('format')}});
    return c.mutate(context,'Prepare Mobile Print',{doctype:entry.doctype,name:entry.name,print_format:value('format'),copies:Number(value('copies')),no_letterhead:Number(value('no_letterhead'))||0,reason:value('reason')||'',printer_settings:{dpi:prefs.dpi,printable_width:prefs.printable_width,paper_width_mm:prefs.paper_width_mm}});}
   if(mode==='invoice'){if(!requirements||value('delivery_note')!==requirements.delivery_note)throw new Error('Select a Delivery Note and wait for its Invoice requirements.');
    return c.mutate(context,'Create Sales Invoice',{delivery_note:value('delivery_note'),required_erp_inputs:root.cfg_dispatch_recovery.erpValues(requirements.fields||[],values()),profile_version:context.profile_version,invoice_mode:context.invoice_mode});}
   if(mode==='label'){const line=value('return_line')!==''?context.custody_lines[Number(value('return_line'))-1]:null;if(!line)throw new Error('Choose a collected return Item row.');
    return c.mutate(context,'Create Custody Label',{return_case:line.return_case,return_line:line.return_line,qty:Number(value('qty'))});}
   if(mode==='job'){if(!job||!frames.length)throw new Error('Load the current print job first.');if(!signer.paired())throw new Error('Pair the companion app key first.');await lease();
    return segment('Awaiting Confirmation');}
  }
  async function segment(outcome){const page=nextPage(job,frames);if(!page)throw new Error('All segments are already confirmed.');
   return c.mutate({...context,stop_key:jobStop},'Record Print Segment',{print_job:job.name,page,frame_hashes:frames.map(row=>row.hash),outcome,reason:value('reason')||''});}
  async function pair(){const text=String(value('signing_key')||'');controls.signing_key?.set_value('');await signer.pair(text);message='Signing key paired in memory for this tab.';update();}
  function startCamera(){stopCamera();if(!f.ui.Scanner)throw new Error('Camera scanner is unavailable. Use the Scanner field.');const ticket=cameraVersion;let accepted=false;
   camera=new f.ui.Scanner({dialog:true,multiple:false,on_scan:data=>{if(accepted||ticket!==cameraVersion||!valid())return;accepted=true;stopCamera();scan(data.decodedText);}});camera.dialog?.$wrapper?.on('hidden.bs.modal.cfg_mobile',focus);}
  async function command(name,node){if(name==='close')return close();if(name==='camera')return startCamera();
   if(name==='retry'||(name==='confirm'&&c.state.pending))return c.retry();if(name==='readback')return c.reconcile();
   if(c.state.pending)throw new Error('Retry or read back the original request first.');
   prepared=null;handed=false;
   if(name==='confirm')return confirm();if(name==='pair')return pair();
   if(name==='forget'){signer.forget();message='Signing key forgotten.';update();return;}
   if(name==='back'){if(c.state.pending){mode='choose';draw();return;}return load();}
   if(name==='setup'){mode='setup';draw();return;}
   if(name==='reset'){prefStore.reset();prefs=prefStore.load(context.defaults);message='Device settings reset to office defaults.';draw();return;}
   if(name==='invoice'){if(!options.stop||!context.invoice_sources.length)throw new Error('Select a stop with a submitted Delivery Note and authorized Invoice policy.');mode='invoice';requirements=null;draw();if(value('delivery_note'))await invoiceFields();return;}
   if(name==='label'){if(!options.stop||!context.custody_lines.length)throw new Error('This stop has no unlabelled collected returns awaiting QC.');mode='label';draw();return;}
   if(name==='resume'){await lease();return showJob($(node).attr('data-job'));}
   if(name==='printed')return segment('Operator Confirmed');if(name==='unknown')return segment('Outcome Unknown');
   if(name==='abandon'){if(!jobName)throw new Error('Select an unfinished job.');return c.mutate({...context,stop_key:jobStop},'Close Mobile Print',{print_job:jobName,reason:value('reason')||''});}
  }
  function scan(raw){if(String(raw||'').trim().toUpperCase()==='CFG:CMD:PRINT_OPEN'){openBridge();return Promise.resolve();}return queue(async()=>{const text=String(raw||'').trim(),upper=text.toUpperCase();if(!text)return;
   const names={MOBILE_PRINT_BACK:'back',PRINT_SETUP:'setup',CREATE_DRIVER_INVOICE:'invoice',CREATE_RETURN_LABEL:'label',PRINT_PAIR:'pair',PRINT_FORGET:'forget',PRINT_CONFIRM:'printed',PRINT_UNKNOWN:'unknown',PRINT_SEND:'confirm',CONFIRM:'confirm',REFRESH:'readback',CANCEL:'close',DELIVERY_CAMERA:'camera'};
   const key=upper.replace(/^CFG:CMD:/,'');if(names[key])return command(names[key]);
   if(key==='HELP'){message='Choose inputs with CFG:SELECT:1–10; scan their values. PRINT_SETUP, CREATE_DRIVER_INVOICE and CREATE_RETURN_LABEL select actions. Confirm prepares a print; use the fresh Open Label Bridge button, then PRINT_CONFIRM after checking paper. No automatic resend. Cancel closes safely. ERP table row commands are supported.';update();return;}
   if(key==='PRINT_NATIVE'){const href=host.find('.cfg-mobile-native').attr('href');if(!href)throw new Error('Choose a document and Print Format.');root.open(href,'_blank','noopener');return;}
   if(loading||c.state.busy||c.state.pending)throw new Error('Resolve the original request before editing or scanning another document.');
   const matches=context.documents.map((row,index)=>({row,index})).filter(({row})=>row.scan_code===text||row.name===text);
   if(mode==='choose'&&matches.length===1){await controls.document.set_value(String(matches[0].index+1));formats();return;}
   if(mode==='choose'&&matches.length>1)throw new Error('More than one document matches this scan. Choose its exact document type.');
   if(upper.startsWith('CFG:CMD:')||/^CFG:SELECT:/.test(upper)||scanner?.state?.field)return scanner?.scan(text);
   throw new Error('Choose an input with a numbered scanner label, then scan its value.');});}
  function close(){if(closed)return;closed=true;version++;stopCamera();if(!options.active()||options.owner()!==owner||options.token()!==token)forget();else if(signer!==memoryKey?.signer)signer.forget();prepared=null;frames=[];job=null;
   releaseLease?.();releaseLease=null;c.close();host.off('.cfg_mobile').empty();options.onClose();}
  host.on('click.cfg_mobile','[data-mobile]',event=>queue(()=>command($(event.currentTarget).attr('data-mobile'),event.currentTarget)));
  host.on('click.cfg_mobile','.cfg-mobile-native',event=>{if(!valid()||loading||c.state.pending||!host.find('.cfg-mobile-native').attr('href'))event.preventDefault();});
  function openBridge(){try{if(!valid()||loading||c.state.busy||c.state.pending||handed||!leaseReady)throw new Error('Prepare the current operator’s print handoff first.');
    const uri=signer.current(prepared);handed=true;prepared=null;message='Label Bridge opened; physical outcome is unknown. Check the paper, then confirm or record Outcome Unknown.';draw();root.location.href=uri;
   }catch(error){message=options.error(error);update();}finally{focus();}}
  host.on('click.cfg_mobile','.cfg-mobile-open-bridge',event=>{event.preventDefault();openBridge();});
  host.on('keydown.cfg_mobile','.cfg-mobile-scan',event=>{if(!['Enter','Tab'].includes(event.key)||event.shiftKey||event.ctrlKey||event.altKey||event.metaKey||event.isComposing)return;const text=host.find('.cfg-mobile-scan').val();if(!String(text||'').trim())return;event.preventDefault();event.stopPropagation();host.find('.cfg-mobile-scan').val('');scan(text);});
  c.restore(options.trip);draw();queue(load);
  return {close,focus,scan,controller:c,refresh:()=>queue(()=>c.state.pending?c.reconcile():load()),valid};
 }
 return {commands,nativeLink,unfinishedJobs,copies,nextPage,open,forget};
});
