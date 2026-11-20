/* Actual direct-return controller, dialog and global scanner entry points with UI/RPC doubles. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const api=require('../public/js/direct_customer_return.js'),inputs=require('../public/js/delivery_action_scanner.js');
const root=path.resolve(__dirname,'..');let count=0;
async function test(name,work){await work();count++;console.log('ok '+name);}
function storage(){const data=new Map();return {getItem:key=>data.get(key)||null,setItem:(key,value)=>data.set(key,value),data};}
function locks(){let tail=Promise.resolve();return {request(key,work){const next=tail.then(work);tail=next.catch(()=>{});return next;}};}
function fixture(shared={store:storage(),locks:locks(),n:0}){
 let owner='EMP',closed=0,success=0,values={company:'B',customer:'CUST',inspection_location:'QC BAY',customer_return_reason:'Damaged',lines:[{item_code:'BAG',claimed_qty:3}]};
 let rpc=async(method,args)=>method==='preview_direct_customer_return'?{...args,lines:args.lines.map(row=>({...row,stock_uom:'Nos'}))}:{status:'Recorded',return_case:{name:'KRTN1'}};
 const calls=[];
 const env={owner:()=>owner,storage:shared.store,locks:shared.locks,nonce:()=>`E${++shared.n}`,render(){},values:()=>values,
  close(){closed++;},success:async()=>{success++;},rpc:async(method,args)=>{calls.push({method,args:structuredClone(args)});return rpc(method,args);}};
 const c=api.createController(env);c.restore();
 return {c,env,calls,shared,values,actor:value=>owner=value,rpc:value=>rpc=value,closed:()=>closed,success:()=>success,
  saved:()=>JSON.parse(shared.store.getItem('cfg_direct_customer_return_v1:EMP')||'null')};
}
const logistics=fs.readFileSync(path.join(root,'cfg_kanban/page/kanban_logistics/kanban_logistics.js'),'utf8');
function source(name){const start=logistics.search(new RegExp('\\t(?:async )?function '+name+'\\('));assert(start>=0,name);
 const next=logistics.slice(start+1).search(/\n\t(?:async )?function /);return next<0?logistics.slice(start):logistics.slice(start,start+1+next);}
function dialogFixture(){
 const base=fixture();let dialog,focus=0,camera,nonce=0;const calls=[];
 class Dialog{
  constructor(config){dialog=this;this.config=config;this.fields_dict={};this.values={};
   for(const df of config.fields){if(!df.fieldname)continue;this.values[df.fieldname]=df.default;this.fields_dict[df.fieldname]={df,$input:{focus(){focus++;},on:(event,fn)=>{this.fields_dict[df.fieldname][event]=fn;}},$wrapper:{html:value=>{this.fields_dict[df.fieldname].html=value;}}};}}
  get_value(name){return this.values[name];}set_value(name,value){this.values[name]=value;return Promise.resolve();}
  get_values(){return {...this.values};}set_df_property(name,property,value){this.fields_dict[name].df[property]=value;}
  show(){this.visible=true;}hide(){this.visible=false;this.onhide?.();}enable_primary_action(){}disable_primary_action(){}
  get_primary_btn(){return {text:value=>{this.label=value;}};}
 }
 class Scanner{constructor(options){camera=this;this.options=options;this.events=[];this.dialog={$wrapper:{one:(name,fn)=>this.events.push(fn)}};}hide_dialog(){this.events.splice(0).forEach(fn=>fn());}}
 const frappe={utils:{escape_html:value=>String(value??'').replaceAll('<','&lt;')},ui:{Dialog,Scanner},require:async()=>{},
  call:async({method,args})=>{calls.push({method,args:structuredClone(args)});
   if(method.endsWith('get_direct_return_setup'))return {message:{conditions:['Unknown','Damaged'],enabled:true,can_start:true}};
   if(method.endsWith('preview_direct_customer_return'))return {message:{...args,lines:args.lines.map(row=>({...row,stock_uom:row.item_code==='RAW'?'Kg':'Nos'}))}};
   return {message:{status:'Recorded',return_case:{name:'KRTN1'}}};}};
 return {base,calls,frappe,dialog:()=>dialog,camera:()=>camera,focus:()=>focus,
  options:{frappe,owner:base.env.owner,token:()=> 'TOKEN',storage:base.env.storage,locks:base.env.locks,nonce:()=>`D${++nonce}`,errorMessage:(err,fallback)=>err.message||fallback,onClose(){focus++;},success:base.env.success}};
}
(async()=>{
 await test('review precedes issuing and carries canonical stock UOM and selected Customer',async()=>{
  const f=fixture();await f.c.confirm();assert.equal(f.calls.length,1);assert.equal(f.calls[0].method,'preview_direct_customer_return');assert(f.c.state.review);
  await f.c.confirm();const args=f.calls[1].args;assert.equal(args.company,'B');assert.equal(args.customer,'CUST');assert.equal(args.lines[0].stock_uom,'Nos');assert.equal(args.event_token,'E1');assert.equal(f.success(),1);
 });
 await test('review is frozen until explicit edit and a fresh review',async()=>{
  const f=fixture();await f.c.confirm();assert.throws(()=>f.c.editable(),/reviewed intake/);f.values.lines[0].claimed_qty=99;
  f.c.edit();await f.c.confirm();assert.equal(f.c.state.review.args.lines[0].claimed_qty,99);assert.equal(f.calls.length,2);
 });
 await test('unknown submission retains exact original payload after dialog reopen',async()=>{
  const f=fixture();await f.c.confirm();f.rpc(async()=>{throw new Error('Lost response');});await assert.rejects(()=>f.c.confirm());const pending=f.saved();
  const reopened=fixture(f.shared);reopened.values.customer='OTHER';await reopened.c.confirm();assert.deepEqual(reopened.calls[0].args,pending.args);assert.equal(reopened.success(),1);
 });
 await test('first confirmed validation rejection permits correction and uses a new token',async()=>{
  const f=fixture();await f.c.confirm();f.rpc(async()=>{throw {exc_type:'ValidationError'};});await assert.rejects(()=>f.c.confirm());assert.equal(f.saved().status,'Rejected');assert.equal(f.c.state.pending,null);
  f.rpc(async(method,args)=>method.startsWith('preview')?args:{status:'Recorded',return_case:{name:'KRTN2'}});f.values.customer='OTHER';await f.c.confirm();await f.c.confirm();assert.equal(f.calls.at(-1).args.event_token,'E2');assert.equal(f.calls.at(-1).args.customer,'OTHER');
 });
 await test('unknown retry rejection and replay conflicts preserve original details',async()=>{
  const f=fixture();await f.c.confirm();f.rpc(async()=>{throw new Error('Network');});await assert.rejects(()=>f.c.confirm());
  for(const type of ['PermissionError','DirectReturnReplayError','DirectReturnVoidedError']){f.rpc(async()=>{throw {exc_type:type};});await assert.rejects(()=>f.c.confirm());assert.equal(f.saved().status,'Pending');assert(f.c.state.pending);}
  assert.throws(()=>f.c.edit(),/pending intake/);
 });
 await test('unexpected server failure remains pending for reconciliation',async()=>{
  const f=fixture();await f.c.confirm();f.rpc(async()=>{throw {exc_type:'TypeError'};});await assert.rejects(()=>f.c.confirm());assert.equal(f.saved().status,'Pending');
 });
 await test('busy confirmation issues one request and duplicate success scans do nothing',async()=>{
  const f=fixture();await f.c.confirm();await Promise.all([f.c.confirm(),f.c.confirm()]);await f.c.confirm();assert.equal(f.calls.filter(row=>row.method.startsWith('create')).length,1);
 });
 await test('cross-tab pending intake replaces a stale review without immediate resubmission',async()=>{
  const a=fixture(),b=fixture(a.shared);await a.c.confirm();await b.c.confirm();a.rpc(async()=>{throw new Error('Lost');});await assert.rejects(()=>a.c.confirm());
  await assert.rejects(()=>b.c.confirm(),/Another intake/);assert.deepEqual(b.c.state.pending,a.c.state.pending);assert.equal(b.calls.length,1);
  await b.c.confirm();assert.equal(b.calls.at(-1).args.event_token,'E1');
 });
 await test('completed action in another tab prevents an unreviewed new issue',async()=>{
  const a=fixture(),b=fixture(a.shared);await a.c.confirm();await b.c.confirm();await a.c.confirm();await assert.rejects(()=>b.c.confirm(),/another tab/);assert.equal(b.calls.length,1);
 });
 await test('owner changes block edit, review, retry and receipt reads',async()=>{
  const f=fixture();f.actor('OTHER');assert.throws(()=>f.c.editable(),/original intake/);await assert.rejects(()=>f.c.confirm(),/original intake/);await assert.rejects(()=>f.c.reconcile(),/original intake/);assert.equal(f.calls.length,0);
 });
 await test('missing Web Locks prevents mutation while review remains read-only',async()=>{
  const f=fixture();f.env.locks=null;await f.c.confirm();await assert.rejects(()=>f.c.confirm(),/Web Locks/);assert.equal(f.calls.length,1);assert.equal(f.saved(),null);
 });
 await test('late success after Cancel updates receipt but leaves newer screen alone',async()=>{
  const f=fixture();await f.c.confirm();let done;f.rpc(()=>new Promise(resolve=>{done=resolve;}));const request=f.c.confirm();await new Promise(resolve=>setImmediate(resolve));f.c.close();done({status:'Recorded',return_case:{name:'KRTN1'}});await request;
  assert.equal(f.saved().status,'Recorded');assert.equal(f.closed(),1);assert.equal(f.success(),0);
 });
 await test('post-success screen error cannot convert a recorded note into a rejected intake',async()=>{
  const f=fixture();await f.c.confirm();f.env.success=async()=>{throw {exc_type:'PermissionError'};};await assert.rejects(()=>f.c.confirm());assert.equal(f.saved().status,'Recorded');assert.equal(f.c.state.pending,null);
 });
 await test('not-recorded receipt retains request until explicit void acknowledgement',async()=>{
  const f=fixture();await f.c.confirm();f.rpc(async()=>{throw new Error('Lost');});await assert.rejects(()=>f.c.confirm());
  f.rpc(async()=>({status:'Not Recorded'}));await f.c.reconcile();assert(f.c.state.pending);await assert.rejects(()=>f.c.reconcile(true),/reason/);
  f.c.voidReason('Wrong quantity');f.rpc(async()=>({status:'Voided'}));await f.c.reconcile(true);assert.equal(f.saved().status,'Voided');assert.equal(f.c.state.pending,null);f.c.editable();
 });
 await test('void returns an already-recorded note when creation won the race',async()=>{
  const f=fixture();await f.c.confirm();f.rpc(async()=>{throw new Error('Lost');});await assert.rejects(()=>f.c.confirm());f.c.voidReason('Check response');f.rpc(async()=>({status:'Recorded',return_case:{name:'KRTN1'}}));
  await f.c.reconcile(true);assert.equal(f.saved().status,'Recorded');assert.equal(f.success(),1);
 });
 await test('stale receipt does not overwrite a newer pending action in storage',async()=>{
  const f=fixture();await f.c.confirm();f.rpc(async()=>{throw new Error('Lost');});await assert.rejects(()=>f.c.confirm());
  const newer={owner:'EMP',revision:'NEW',status:'Pending',args:{...f.saved().args,event_token:'NEW'}};f.shared.store.setItem('cfg_direct_customer_return_v1:EMP',JSON.stringify(newer));
  f.rpc(async()=>({status:'Recorded',return_case:{name:'OLD'}}));await f.c.reconcile();assert.deepEqual(f.saved(),newer);
 });
 await test('storage failures and corrupt pending data block new intake',async()=>{
  const f=fixture();f.shared.store.setItem('cfg_direct_customer_return_v1:EMP','invalid');assert.throws(()=>f.c.restore(),/unreadable/);
  f.shared.store.setItem('cfg_direct_customer_return_v1:EMP',JSON.stringify({owner:'EMP',status:'Pending',revision:'x'}));assert.throws(()=>f.c.restore(),/incomplete/);
  f.shared.store.data.clear();await f.c.confirm();f.env.storage.setItem=()=>{throw new Error('Storage blocked');};await assert.rejects(()=>f.c.confirm(),/Storage blocked/);assert.equal(f.calls.length,1);
 });
 globalThis.cfg_delivery_action_scanner=inputs;
 await test('actual dialog completes multiple returned Items entirely through scanner controls',async()=>{
  const f=dialogFixture(),h=await api.open(f.options);
  for(const code of ['CFG:SELECT:1','B','CFG:SELECT:2','CUST','CFG:SELECT:4','QC BAY','CFG:CMD:RETURN_REASON','Damaged',
   'CFG:CMD:RETURN_ITEMS','CFG:CMD:RETURN_ADD_ITEM','BAG','CFG:QTY:MATERIAL:3','CFG:CMD:RETURN_ADD_ITEM','RAW','CFG:QTY:MATERIAL:2.25',
   'CFG:CMD:RETURN_PREVIOUS_ITEM','CFG:CMD:RETURN_NEXT_ITEM','CFG:CMD:RETURN_INPUTS','CFG:CMD:CONFIRM'])await h.scan(code);
  assert.equal(f.dialog().label,'Issue Temporary Return Note');assert(f.dialog().fields_dict.summary.html.includes('2.25 Kg'));await h.scan('CFG:CMD:CONFIRM');
  const sent=f.calls.at(-1).args;assert.equal(sent.customer,'CUST');assert.equal(sent.company,'B');assert.deepEqual(sent.lines.map(row=>[row.item_code,row.claimed_qty,row.stock_uom]),[['BAG','3','Nos'],['RAW','2.25','Kg']]);assert.equal(f.base.success(),1);assert(f.focus()>0);
 });
 await test('actual dialog supports touch values and explicit edit before issuance',async()=>{
  const f=dialogFixture(),h=await api.open(f.options);Object.assign(f.dialog().values,{company:'B',customer:'CUST',inspection_location:'QC BAY',customer_return_reason:'Damage',lines:[{item_code:'BAG',claimed_qty:2}]});
  await f.dialog().config.primary_action();await f.dialog().fields_dict.edit.df.click();f.dialog().values.lines[0].claimed_qty=4;await f.dialog().config.primary_action();await f.dialog().config.primary_action();assert.equal(f.calls.at(-1).args.lines[0].claimed_qty,4);
 });
 await test('Tab/Enter suffixes work and blank/modifier keys preserve navigation',async()=>{
  const f=dialogFixture(),h=await api.open(f.options),d=f.dialog();let prevented=0;
  for(const event of [{key:'Tab'},{key:'Tab',shiftKey:true},{key:'Enter',isComposing:true}])await d.fields_dict.scan.keydown({...event,preventDefault(){prevented++;},stopPropagation(){}});assert.equal(prevented,0);
  for(const [value,key] of [['B','Tab'],['CFG:CMD:CANCEL','Enter']]){d.values.scan=value;await d.fields_dict.scan.keydown({key,preventDefault(){prevented++;},stopPropagation(){}});}
  assert.equal(prevented,2);assert.equal(d.values.company,'B');assert.equal(d.visible,false);assert.equal(f.calls.length,1);
 });
 await test('tablet camera scans once and ignores callbacks after cancellation',async()=>{
  const f=dialogFixture(),h=await api.open(f.options);await f.dialog().fields_dict.camera.df.click();const camera=f.camera();camera.options.on_scan({decodedText:'B'});await h.scan('CFG:CMD:HELP');assert.equal(f.dialog().values.company,'B');
  await h.scan('CFG:CMD:CANCEL');camera.options.on_scan({decodedText:'OTHER'});assert.equal(f.dialog().values.company,'B');assert.equal(f.calls.length,1);
 });
 await test('scanner Cancel closes immediately while creation is awaiting a response',async()=>{
  const f=dialogFixture(),h=await api.open(f.options),d=f.dialog();Object.assign(d.values,{company:'B',customer:'CUST',inspection_location:'QC BAY',customer_return_reason:'Damage',lines:[{item_code:'BAG',claimed_qty:2}]});
  await h.scan('CFG:CMD:CONFIRM');const original=f.frappe.call;let done;
  f.frappe.call=options=>options.method.endsWith('create_direct_customer_return')?new Promise(resolve=>{done=resolve;}):original(options);
  const pending=h.scan('CFG:CMD:CONFIRM');await new Promise(resolve=>setImmediate(resolve));assert.equal(typeof done,'function');
  await h.scan('CFG:CMD:CANCEL');assert.equal(d.visible,false);assert(h.controller.state.pending);
  done({message:{status:'Recorded',return_case:{name:'LATE'}}});await pending;assert.equal(f.base.success(),0);
  assert.equal(JSON.parse(f.options.storage.getItem('cfg_direct_customer_return_v1:EMP')).status,'Recorded');
 });
 await test('changed operator sees no original customer or pending item details',async()=>{
  const f=dialogFixture(),h=await api.open(f.options),d=f.dialog();Object.assign(d.values,{company:'B',customer:'PRIVATE CUSTOMER',inspection_location:'QC BAY',customer_return_reason:'Damage',lines:[{item_code:'PRIVATE ITEM',claimed_qty:2}]});
  await h.scan('CFG:CMD:CONFIRM');assert(d.fields_dict.summary.html.includes('PRIVATE CUSTOMER'));f.base.actor('OTHER');await h.scan('CFG:CMD:HELP');
  assert(!d.fields_dict.summary.html.includes('PRIVATE CUSTOMER'));assert(!d.fields_dict.summary.html.includes('PRIVATE ITEM'));assert.equal(d.fields_dict.customer.df.hidden,1);
  await h.scan('CFG:CMD:CONFIRM');assert.equal(f.calls.length,2);await h.scan('CFG:CMD:CANCEL');assert.equal(d.visible,false);
 });
 await test('no stale dialog opens after operator changes during setup',async()=>{
  const f=dialogFixture(),old=f.frappe.call;f.frappe.call=async value=>{const result=await old(value);f.base.actor('OTHER');return result;};await assert.rejects(()=>api.open(f.options),/Operator changed/);assert.equal(f.dialog(),undefined);
 });
 await test('global Logistics command reaches direct intake and active dialog owns subsequent scans',async()=>{
  const actions=[];const run=new Function('$scanner','command','open_direct_customer_return',`let active_dispatch_review=null,opening_dispatch_review=false,active_delivery_action=null,opening_delivery_action=false,active_route_delivery=null,opening_route_delivery=false,active_prepared_delivery=null,opening_prepared_delivery=false,active_isolation=null,opening_isolation=false,active_repack=null,opening_repack=false;\n${source('process_scan')}\nreturn process_scan(command);`);
  await run({find:()=>({val(){}})},'CFG:CMD:DIRECT_CUSTOMER_RETURN',()=>actions.push('direct'));assert.deepEqual(actions,['direct']);
 });
 await test('actual page opener passes owner token storage and focuses its single active action',async()=>{
  const f=dialogFixture(),state={operator:{employee:'EMP'},token:'TOKEN',scan_mode:'lookup'};let pageFocus=0,opened=0;
  const fn=new Function('frappe','window','state','localStorage','navigator','unique_token','server_error_message','focus_scanner','open_return_case','refresh_list','scanner_error','__',
   `let active_dispatch_review=null,opening_dispatch_review=false,active_delivery_action=null,opening_delivery_action=false,active_route_delivery=null,opening_route_delivery=false,active_prepared_delivery=null,opening_prepared_delivery=false,active_repack=null,opening_repack=false,active_isolation=null,opening_isolation=false;\n${source('open_direct_customer_return')}\nreturn {open_direct_customer_return,active:()=>active_delivery_action};`);
  const page=fn(f.frappe,{cfg_direct_customer_return:{open:async options=>{opened++;assert.equal(options.owner(),'EMP');assert.equal(options.token(),'TOKEN');return {scan(){},focus(){pageFocus++;}};}}},state,f.options.storage,{locks:f.options.locks},()=> 'N',(err,message)=>message,()=>{},async()=>{},async()=>{},err=>{throw new Error(err);},s=>s);
  await page.open_direct_customer_return();await page.open_direct_customer_return();assert.equal(opened,1);assert.equal(pageFocus,1);
 });
 await test('all action labels are printable with Production routing and help',async()=>{
  const catalogue=fs.readFileSync(path.join(root,'api/operator.py'),'utf8'),production=fs.readFileSync(path.join(root,'cfg_kanban/page/kanban_operator/kanban_operator.js'),'utf8');
  for(const command of ['DIRECT_CUSTOMER_RETURN','RETURN_ITEMS','RETURN_ADD_ITEM','RETURN_NEXT_ITEM','RETURN_PREVIOUS_ITEM','RETURN_INPUTS','RETURN_REASON','RETURN_EDIT','RETURN_CAMERA','RETURN_RECONCILE','RETURN_VOID_REASON','RETURN_VOID_PENDING'])assert(catalogue.includes('CFG:CMD:'+command));
  assert(production.includes('DIRECT_CUSTOMER_RETURN:'));assert(production.includes('cfg_direct_customer_return:1'));assert(logistics.includes('frappe.route_options?.cfg_direct_customer_return'));assert(logistics.includes('Direct Customer Return: CFG:CMD:DIRECT_CUSTOMER_RETURN'));
 });
 console.log(`${count} direct customer-return UI checks passed`);
})().catch(error=>{console.error(error);process.exitCode=1;});
