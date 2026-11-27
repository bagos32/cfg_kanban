/* Execute E4C scanner/touch controls and actual Logistics dialog adapters with UI/RPC doubles. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const api=require('../public/js/delivery_action_scanner.js');
const prepared=require('../public/js/dispatch_fulfilment.js');
const root=path.resolve(__dirname,'..'),panel=fs.readFileSync(path.join(root,'cfg_kanban/page/kanban_logistics/kanban_logistics.js'),'utf8');
let count=0;async function test(name,work){await work();count++;console.log('ok '+name);}
function fixture(){
 let owner='EMP',n=0,closes=0,success=0,failure=null,values={recipient_name:'Receiver',disposition:'Attended'};const sent=[];
 const env={fields:[{name:'recipient_name'},{name:'notes'}],owner:()=>owner,openedOwner:'EMP',nonce:()=>`E-${++n}`,
  render(){},close(){closes++;},camera(){},values:()=>values,set:async(k,v)=>{values[k]=v;},
  submit:async(v,key)=>{sent.push({values:structuredClone(v),key});if(failure)throw failure;},success:async()=>{success++;}};
 return {env,c:api.createController(env),sent,owner:v=>owner=v,failure:v=>failure=v,values:v=>values=v,closed:()=>closes,success:()=>success};
}
function source(name){
 const pattern=new RegExp('\\t(?:async )?function '+name+'\\('),start=panel.search(pattern);assert(start>=0,name);
 const end=panel.slice(start+1).search(/\n\t(?:async )?function /);return end<0?panel.slice(start):panel.slice(start,start+1+end);
}
function adapter(){
 let dialog,focus=0,owner='EMP',nonce=0,hide=0,fail=null,serverProof={name:'PROOF',state:'Draft',site_name:'Shop',proof_policy:'Required',require_gps:0,
  allowed_dispositions:['Attended'],require_recipient_name:1};const calls=[],cameras=[];let evidence=0;
 class Dialog{
  constructor(config){dialog=this;this.config=config;this.fields_dict={};this.values={};
   for(const f of config.fields){if(!f.fieldname)continue;this.values[f.fieldname]=f.default;this.fields_dict[f.fieldname]={df:f,$input:{focus(){focus++;},on:(event,fn)=>{this.fields_dict[f.fieldname][event]=fn;}},$wrapper:{html:v=>{this.review=v;}}};}
  }
  get_value(k){return this.values[k];}get_values(){return {...this.values};}set_value(k,v){this.values[k]=v;}
  set_primary_action(label,fn){this.primary=fn;this.label=label;}show(){this.visible=true;}hide(){hide++;this.visible=false;this.onhide?.();}
  enable_primary_action(){this.enabled=true;}disable_primary_action(){this.enabled=false;}
 }
 class Camera{
  constructor(config){this.config=config;cameras.push(this);this.handlers=[];this.dialog={$wrapper:{one:(event,fn)=>this.handlers.push(fn)}};}
  hide_dialog(){this.handlers.splice(0).forEach(fn=>fn());}
 }
 const state={operator:{employee:'EMP'},token:'TOKEN',scan_mode:'lookup',lookup:{delivery_session:{name:'KDS',fulfilment_mode:'Customer Pickup',auto_submit_delivery_note:1}}};
 const frappe={utils:{escape_html:v=>String(v??'').replaceAll('<','&lt;')},ui:{Dialog,Scanner:Camera},require:async()=>{},
  call:async({method,args})=>{calls.push({method,args:structuredClone(args)});if(fail)throw fail;
   if(method.endsWith('get_or_create_delivery_proof'))return {message:serverProof};
   if(method.endsWith('get_customer_delivery_requirements'))return {message:{fields:[]}};
   return {message:{name:'KDS',state:'Closed'}};
  },show_alert(){},set_route(){}};
 const window={cfg_delivery_action_scanner:api};
 const names=['delivery_action_dialog','confirm_delivery_allocations','prepare_customer_delivery_note','required_erp_dialog_fields','required_erp_values','submit_customer_delivery_note','open_delivery_proof'];
 const run=new Function('frappe','window','state','unique_token','server_error_message','fetch_delivery','render_lookup','refresh_list','focus_scanner','scanner_error','bind_delivery_proof_evidence','delivery_geotag','__',
  `let active_route_count_action=null,active_dispatch_review=null,opening_dispatch_review=false,active_delivery_action=null,opening_delivery_action=false,active_route_delivery=null,active_prepared_delivery=null,active_repack=null,active_isolation=null;\n`+
  names.map(source).join('\n')+'\nreturn {delivery_action_dialog,confirm_delivery_allocations,prepare_customer_delivery_note,open_delivery_proof,handle:()=>active_delivery_action};');
 const methods=run(frappe,window,state,()=>`T-${++nonce}`,(err,fallback)=>err.message||fallback,async()=>({name:'KDS'}),()=>{},async()=>{},()=>{focus++;},err=>{throw new Error(err);},()=>{evidence++;},async()=>({latitude:1,longitude:2,accuracy:3}),text=>text);
 return {methods,state,calls,frappe,dialog:()=>dialog,focused:()=>focus,hidden:()=>hide,cameras,evidence:()=>evidence,
  failure:v=>fail=v,proof:v=>serverProof=v};
}
(async()=>{
 await test('scanner field values and touch values submit the same reviewed acknowledgement',async()=>{
  const f=fixture();await f.c.scan('CFG:CMD:DELIVERY_RECIPIENT');await f.c.scan('Scanned Receiver');await f.c.scan('CFG:CMD:CONFIRM');
  assert.equal(f.sent[0].values.recipient_name,'Scanned Receiver');assert.equal(f.success(),1);
 });
 await test('numbered fields select notes and reject an invalid number',async()=>{
  const f=fixture();await f.c.scan('CFG:SELECT:2');await f.c.scan('Collected at counter');assert.equal(f.env.values().notes,'Collected at counter');
  await assert.rejects(()=>f.c.scan('CFG:SELECT:10'),/displayed field/);
 });
 await test('unknown submission freezes values and original event identity',async()=>{
  const f=fixture();f.failure(new Error('network'));await assert.rejects(()=>f.c.confirm());
  await assert.rejects(()=>f.c.scan('Other Name'),/Retry the original/);f.env.values().recipient_name='Touch Edit';
  f.failure(null);await f.c.confirm();assert.deepEqual(f.sent[0],f.sent[1]);
 });
 await test('first confirmed rejection permits correction but unknown retry rejection remains locked',async()=>{
  const f=fixture();f.failure({exc_type:'ValidationError'});await assert.rejects(()=>f.c.confirm());assert.equal(f.c.state.pending,null);
  await f.c.scan('Corrected');f.failure(new Error('lost'));await assert.rejects(()=>f.c.confirm());
  f.failure({exc_type:'PermissionError'});await assert.rejects(()=>f.c.confirm());assert(f.c.state.pending);
 });
 await test('busy and repeated confirmation do not submit twice',async()=>{
  const f=fixture();await Promise.all([f.c.confirm(),f.c.confirm()]);await f.c.confirm();assert.equal(f.sent.length,1);
 });
 await test('operator switch blocks both input and confirmation',async()=>{
  const f=fixture();f.owner('OTHER');await assert.rejects(()=>f.c.scan('Name'),/original operator/);await assert.rejects(()=>f.c.confirm(),/original operator/);assert.equal(f.sent.length,0);
 });
 await test('late response after cancel does not close a newer dialog or replace its screen',async()=>{
  const f=fixture();let done;f.env.submit=()=>new Promise(resolve=>{done=resolve;});const pending=f.c.confirm();
  await f.c.scan('CFG:CMD:CANCEL');done();await pending;assert.equal(f.closed(),1);assert.equal(f.success(),0);
 });
 await test('missing required dialog values block submission',async()=>{
  const f=fixture();f.values(null);await assert.rejects(()=>f.c.confirm(),/required fields/);assert.equal(f.sent.length,0);
 });
 await test('actual allocation confirmation opens a scanner dialog and sends one stable token',async()=>{
  const f=adapter();await f.methods.confirm_delivery_allocations(f.state.lookup.delivery_session);
  await f.methods.handle().scan('CFG:CMD:CONFIRM');assert.equal(f.calls.at(-1).args.event_token,'T-1');
  assert(f.calls.at(-1).method.endsWith('confirm_delivery_allocations'));assert.equal(f.hidden(),1);assert(f.focused()>0);
 });
 await test('actual Delivery Note action retains configured Draft or submit policy',async()=>{
  const f=adapter();f.state.lookup.delivery_session.auto_submit_delivery_note=0;
  await f.methods.prepare_customer_delivery_note(f.state.lookup.delivery_session);assert.equal(f.dialog().label,'Create Draft');
  await f.methods.handle().scan('CFG:CMD:CONFIRM');const call=f.calls.at(-1);
  assert(call.method.endsWith('create_customer_delivery_document'));assert.equal(call.args.event_token,'T-1');assert.equal(call.args.required_erp_inputs,'{"parent":{},"tables":{}}');
 });
 await test('actual pickup proof keeps signature/photo tools and scanner recipient entry',async()=>{
  const f=adapter();await f.methods.open_delivery_proof(f.state.lookup.delivery_session);assert.equal(f.evidence(),1);
  const h=f.methods.handle();await h.scan('CFG:CMD:DELIVERY_RECIPIENT');await h.scan('Customer Rep');await h.scan('CFG:CMD:CONFIRM');
  const sent=f.calls.at(-1);assert(sent.method.endsWith('submit_delivery_proof'));assert.equal(sent.args.recipient_name,'Customer Rep');assert.equal(sent.args.disposition,'Attended');
  assert(f.dialog().config.fields.some(r=>r.fieldname==='signature'));assert(f.dialog().config.fields.some(r=>r.fieldname==='evidence'));
 });
 await test('Tab and Enter suffixes complete the actual proof dialog and restore focus',async()=>{
  const f=adapter();await f.methods.open_delivery_proof(f.state.lookup.delivery_session);const d=f.dialog(),h=f.methods.handle();
  for(const [value,key] of [['Receiver','Tab'],['CFG:CMD:CONFIRM','Enter']]){
   d.values.delivery_scanner=value;let stopped=0;await d.fields_dict.delivery_scanner.keydown({key,preventDefault(){stopped++;},stopPropagation(){}});assert.equal(stopped,1);
  }
  await h.scan('CFG:CMD:HELP');assert.equal(f.calls.at(-1).args.recipient_name,'Receiver');assert(f.focused()>1);
 });
 await test('blank Tab, Shift Tab and composition preserve ordinary navigation',async()=>{
  const f=adapter();await f.methods.open_delivery_proof(f.state.lookup.delivery_session);const d=f.dialog();let prevented=0;
  for(const event of [{key:'Tab'},{key:'Tab',shiftKey:true},{key:'Enter',isComposing:true}])await d.fields_dict.delivery_scanner.keydown({...event,preventDefault(){prevented++;},stopPropagation(){}});
  assert.equal(prevented,0);assert.equal(f.calls.length,1);
 });
 await test('camera scan accepts one recipient and ignores late callbacks after cancellation',async()=>{
  const f=adapter();await f.methods.open_delivery_proof(f.state.lookup.delivery_session);const h=f.methods.handle();
  await h.scan('CFG:CMD:DELIVERY_CAMERA');const camera=f.cameras[0];camera.config.on_scan({decodedText:'Camera Name'});await h.scan('CFG:CMD:HELP');
  assert.equal(f.dialog().values.recipient_name,'Camera Name');await h.scan('CFG:CMD:CANCEL');camera.config.on_scan({decodedText:'Late'});
  assert.equal(f.dialog().values.recipient_name,'Camera Name');assert.equal(f.calls.length,1);
 });
 await test('warehouse prepared selection displays source and mode and clears stale Site after failed scan',async()=>{
  let fail=false;const f=fixture(),c=prepared.createController({...f.env,token:()=> 'TOKEN',rpc:async(method,args)=>{
   if(fail)throw new Error('wrong Site');return {plans:[{name:'DPL',fulfilment_mode:'Customer Pickup',source_warehouse:'SALES',lines:[{stock_uom:'Nos',requested_qty:5}]}],customer_scan:args.scan_value==='SITE'?'SITE':null};}});
  await c.scan('DPL');await c.scan('SITE');assert.equal(c.state.customerScan,'SITE');fail=true;
  await assert.rejects(()=>c.scan('WRONG'));assert.equal(c.state.customerScan,'');await assert.rejects(()=>c.confirm(),/scan its Customer Site/);
 });
 await test('required ERP scalar inputs remain scanner-enterable without dropping mandatory values',async()=>{
  const f=adapter(),old=f.frappe.call;f.frappe.call=async args=>args.method.endsWith('get_customer_delivery_requirements')?{message:{fields:[{scope:'parent',fieldname:'posting_date',label:'Posting Date',fieldtype:'Date'}]}}:old(args);
  await f.methods.prepare_customer_delivery_note(f.state.lookup.delivery_session);await f.methods.handle().scan('2026-11-20');await f.methods.handle().scan('CFG:CMD:CONFIRM');
  assert.equal(JSON.parse(f.calls.at(-1).args.required_erp_inputs).parent.posting_date,'2026-11-20');
 });
 await test('mandatory ERP table rows can be captured entirely by scanner',async()=>{
  const f=adapter(),old=f.frappe.call;f.frappe.call=async args=>args.method.endsWith('get_customer_delivery_requirements')?{message:{fields:[{scope:'table',fieldname:'sales_team',label:'Sales Team',fieldtype:'Table',fields:[{fieldname:'sales_person',label:'Sales Person',fieldtype:'Link'},{fieldname:'allocated_percentage',label:'Percentage',fieldtype:'Float'}]}]}}:old(args);
  await f.methods.prepare_customer_delivery_note(f.state.lookup.delivery_session);const h=f.methods.handle();
  for(const scan of ['CFG:SELECT:1','CFG:CMD:DELIVERY_ADD_ROW','Person A','CFG:SELECT:2','50','CFG:CMD:DELIVERY_ADD_ROW','Person B','CFG:SELECT:2','50','CFG:CMD:DELIVERY_PREVIOUS_ROW','CFG:CMD:DELIVERY_NEXT_ROW','CFG:CMD:DELIVERY_INPUTS','CFG:CMD:CONFIRM'])await h.scan(scan);
  assert.deepEqual(JSON.parse(f.calls.at(-1).args.required_erp_inputs).tables.sales_team,[{sales_person:'Person A',allocated_percentage:'50'},{sales_person:'Person B',allocated_percentage:'50'}]);
 });
 await test('more than ten ERP inputs page through the standard numbered-choice commands',async()=>{
  const f=fixture();f.env.fields=Array.from({length:12},(_,i)=>({name:'field'+(i+1)}));const c=api.createController(f.env);
  await c.scan('CFG:CMD:NEXT_MATERIALS');await c.scan('CFG:SELECT:2');await c.scan('Input 12');
  assert.equal(f.env.values().field12,'Input 12');await c.scan('CFG:CMD:PREVIOUS_MATERIALS');assert.equal(c.state.page,0);
 });
 await test('warehouse command and pickup action route through actual global dispatcher',async()=>{
  const start=panel.indexOf('\tasync function process_scan(value)'),end=panel.indexOf('\n\tasync function lookup_tag(',start);const actions=[];
  const code=`let active_route_count_action=null,active_loose_tag=null,opening_loose_tag=false,active_dispatch_review=null,opening_dispatch_review=false,active_delivery_action=null,opening_delivery_action=false,active_route_delivery=null,opening_route_delivery=false,active_prepared_delivery=null,opening_prepared_delivery=false,active_isolation=null,opening_isolation=false,active_repack=null,opening_repack=false;\n`+panel.slice(start,end)+'\nreturn process_scan(command);';
  const run=new Function('$scanner','state','open_prepared_delivery','confirm_delivery_allocations','prepare_customer_delivery_note','open_delivery_proof','verify_delivery_goods','command',code);
  const args=[{find:()=>({val(){}})},{lookup:{delivery_session:{name:'KDS',fulfilment_mode:'Customer Pickup'},dispatch_plan:{name:'DPL'}}},(...v)=>actions.push(['start',...v]),()=>{},()=>{},v=>actions.push(['proof',v.name]),v=>actions.push(['check',v.name])];
  await run(...args,'CFG:CMD:START_WAREHOUSE_DELIVERY');await run(...args,'CFG:CMD:ACKNOWLEDGE_PICKUP');await run(...args,'CFG:CMD:VERIFY_DELIVERY_GOODS');assert.deepEqual(actions,[['start','DPL',null],['proof','KDS'],['check','KDS']]);
 });
 await test('new commands have catalogue entries and Production entry routing',async()=>{
  const catalogue=fs.readFileSync(path.join(root,'api/operator.py'),'utf8'),production=fs.readFileSync(path.join(root,'cfg_kanban/page/kanban_operator/kanban_operator.js'),'utf8');
  for(const name of ['VERIFY_DELIVERY_GOODS','START_WAREHOUSE_DELIVERY','ACKNOWLEDGE_PICKUP','CONFIRM_CUSTOMER_ALLOCATION','CREATE_CUSTOMER_DELIVERY_NOTE','CAPTURE_DELIVERY_PROOF']){assert(catalogue.includes('CFG:CMD:'+name));assert(production.includes(name));}
  for(const name of ['DELIVERY_RECIPIENT','DELIVERY_CAMERA'])assert(catalogue.includes('CFG:CMD:'+name));
 });
 console.log(`${count} E4C UI checks passed`);
})().catch(error=>{console.error(error);process.exitCode=1;});
