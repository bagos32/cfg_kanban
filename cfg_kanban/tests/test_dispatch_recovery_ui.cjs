/* Actual E5B1 scanner controller/dialog and global dispatch, with offline RPC/UI doubles. */
const assert=require('node:assert/strict'),fs=require('node:fs');
const {createController,open,erpFields,erpValues}=require('../public/js/dispatch_recovery.js');
let checks=0;async function test(name,work){await work();checks++;console.log('ok '+name);}
function fixture(options={}){
 let owner='EMP',failure=null,once=false,n=0,closed=0,finished=0,inputCalls=0;
 const routes=Array.from({length:options.routes||2},(_,i)=>({name:'ROUTE-'+(i+1),destination_warehouse:'WH-'+(i+1),action:'Returned to Warehouse',auto_submit:1}));
 const context={plan:{name:'DPL-1',state:'Loaded',vehicle_warehouse:'LORRY1'},review:{name:'KDR-1',state:'Reviewing'},balance_hash:'HASH',recovery_routes:routes,recovery_manifest:null};
 const calls=[],lines=[{name:'TAG-LINE',handling_unit:'TAG',visible_code:'TAG1',item_code:'ITEM',batch_no:'LOT',stock_uom:'Nos',dispatch_qty:options.tagQty??3,loading_confirmed:0},
  {name:'LOOSE-LINE',handling_unit:null,item_code:'BAG',batch_no:'BAGLOT',stock_uom:'Nos',dispatch_qty:options.looseQty??5,loading_confirmed:0}];
 function mutate(method,args){
  if(method==='create_dispatch_recovery')context.recovery_manifest={name:'KMF-1',state:'Draft',logistics_route:args.logistics_route,recovery_reason:args.reason,source_warehouse:'LORRY1',destination_warehouse:routes.find(r=>r.name===args.logistics_route).destination_warehouse,lines:structuredClone(lines),auto_submit_internal_dispatch:1};
  const m=context.recovery_manifest;
  if(method==='scan_dispatch_recovery'){assert.equal(args.scan_value,'TAG1');m.lines[0].loading_confirmed=1;}
  if(method==='confirm_dispatch_recovery_loose'){const row=m.lines.find(r=>r.name===args.line_name&&!r.handling_unit);assert(row,'loose source identity required');assert.equal(args.qty,row.dispatch_qty);row.loading_confirmed=1;}
  if(method==='prepare_dispatch_recovery')m.state='Prepared';
  if(method==='post_dispatch_recovery'){m.state='Received';m.dispatch_stock_entry='MAT-STE-1';m.dispatch_document_status='Submitted';}
  if(method==='cancel_dispatch_recovery')m.state='Cancelled';
 }
 const env={owner:()=>owner,openedOwner:'EMP',token:()=> 'TOKEN',nonce:()=>`E-${++n}`,render(){},close(){closed++;},camera(){},finish:async()=>{finished++;},
  inputs:async()=>{inputCalls++;return {};},rpc:async(method,args)=>{calls.push({method,args:structuredClone(args)});if(failure){const err=failure;if(once){failure=null;once=false;}throw err;}mutate(method,args);return structuredClone(context);}};
 return {c:createController(env),env,context,lines,calls,owner:v=>owner=v,failure:(v,one=false)=>{failure=v;once=one;},closed:()=>closed,finished:()=>finished,inputCalls:()=>inputCalls};
}
async function create(f){for(const raw of ['DPL-1','CFG:SELECT:1','CFG:CMD:RECOVERY_REASON','Trip return','CFG:CMD:CONFIRM'])await f.c.scan(raw);}
async function confirmSources(f){for(const raw of ['TAG1','CFG:SELECT:1','CFG:QTY:MATERIAL:5','CFG:CMD:CONFIRM'])await f.c.scan(raw);}
function adapter(options={}){
 const f=fixture(options),dialogs=[],cameras=[];let focused=0,transition=0;
 class Dialog{
  constructor(config){this.config=config;dialogs.push(this);this.values={};this.fields_dict={};for(const field of config.fields){this.values[field.fieldname]=field.default;this.fields_dict[field.fieldname]={df:field,$input:{focus(){focused++;},on:(event,handler)=>{this.fields_dict[field.fieldname][event]=handler;}},$wrapper:{html:value=>{this.summary=value;},find:()=>({on(){}})}};}}
  get_value(k){return this.values[k];}set_value(k,v){this.values[k]=v;}get_values(){return {...this.values};}set_df_property(k,p,v){this.fields_dict[k].df[p]=v;}
  set_primary_action(label,fn){this.config.primary_action=fn;}get_primary_btn(){return {text:value=>{this.label=value;}};}
  show(){}hide(){if(this.hidden)return;this.hidden=true;this.onhide?.();}enable_primary_action(){this.enabled=true;}disable_primary_action(){this.enabled=false;}
 }
 class Camera{
  constructor(config){this.config=config;this.handlers=[];this.visible=true;cameras.push(this);this.dialog={$wrapper:{one:(event,fn)=>this.handlers.push(fn)}};}
  hide_dialog(){if(!this.visible)return;this.visible=false;this.handlers.splice(0).forEach(fn=>fn());}
 }
 const api={utils:{escape_html:v=>String(v??'').replaceAll('<','&lt;')},ui:{Dialog,...(!options.noCamera?{Scanner:Camera}:{})},require:async()=>{require('../public/js/delivery_action_scanner.js');},set_route(){},
  call:async({method,args})=>({message:method.endsWith('get_dispatch_requirements')?{fields:options.requirements||[]}:await f.env.rpc(method.split('.').at(-1),args)})};
 const launch=()=>open({frappe:api,planScan:options.planScan,owner:f.env.owner,token:f.env.token,nonce:f.env.nonce,onClose(){},errorMessage:(error,fallback)=>error.message||fallback,finish:async()=>{transition++;}});
 return {...f,launch,dialogs,cameras,focused:()=>focused,transition:()=>transition};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 await test('explicit route choice and Supervisor reason are required before checklist creation',async()=>{
  const f=fixture();await f.c.scan('DPL-1');assert(!f.c.ready());await f.c.scan('CFG:SELECT:1');assert(!f.c.ready());await f.c.scan('CFG:CMD:RECOVERY_REASON');await f.c.scan('Return');assert(f.c.ready());await f.c.confirm();
  assert.equal(f.calls.at(-1).method,'create_dispatch_recovery');assert.equal(f.calls.at(-1).args.balance_hash,'HASH');assert.equal(f.calls.at(-1).args.logistics_route,'ROUTE-1');
 });
 await test('single eligible route still requires an explicit choice',async()=>{const f=fixture({routes:1});await f.c.load('DPL-1');await f.c.set('reason','Return');assert(!f.c.ready());});
 await test('paged numbered routes cannot silently select a destination',async()=>{
  const f=fixture({routes:22});await f.c.load('DPL-1');await f.c.scan('CFG:CMD:NEXT_MATERIALS');await f.c.scan('CFG:SELECT:10');assert.equal(f.c.state.route,'ROUTE-20');
  await f.c.scan('CFG:CMD:NEXT_MATERIALS');await assert.rejects(()=>f.c.scan('CFG:SELECT:10'),/displayed/);assert.equal(f.c.state.route,'');
 });
 await test('physical source and exact loose quantity can be confirmed in either order',async()=>{
  for(const order of [0,1]){const f=fixture();await create(f);assert(!f.c.ready());
   if(!order)await f.c.scan('TAG1');await f.c.scan('CFG:SELECT:1');await f.c.scan('CFG:QTY:MATERIAL:4');assert(!f.c.ready());await f.c.scan('CFG:QTY:MATERIAL:5');await f.c.confirm();
   if(order)await f.c.scan('TAG1');assert.equal(f.c.step(),'prepare');assert(f.c.ready());
  }
 });
 await test('prepare and post are separate reviewed steps using the existing Manifest',async()=>{
  const f=fixture();await create(f);await confirmSources(f);await f.c.scan('CFG:CMD:RECOVERY_PREPARE');await f.c.confirm();assert.equal(f.calls.at(-1).method,'prepare_dispatch_recovery');
  await f.c.scan('CFG:CMD:RECOVERY_POST');await f.c.confirm();assert.equal(f.calls.at(-1).method,'post_dispatch_recovery');assert.equal(f.calls.at(-1).args.manifest_name,'KMF-1');assert.equal(f.inputCalls(),1);
  assert.equal(f.c.state.context.recovery_manifest.state,'Received');assert(!f.c.ready());await f.c.scan('CFG:CMD:FINISH_DISPATCH_REVIEW');assert.equal(f.finished(),1);
 });
 await test('post cannot substitute for unconfirmed preparation',async()=>{const f=fixture();await create(f);await f.c.scan('CFG:CMD:RECOVERY_POST');assert(!f.c.ready());await assert.rejects(()=>f.c.confirm(),/displayed recovery step/);});
 await test('unknown result preserves the original token, destination and reason',async()=>{
  const f=fixture();await f.c.load('DPL-1');await f.c.select(1);await f.c.set('reason','Return');f.failure(new Error('network'));await assert.rejects(()=>f.c.confirm());const original=f.calls.at(-1).args;
  assert.throws(()=>f.c.select(2),/Retry the original/);await assert.rejects(()=>f.c.load('DPL-2'),/Retry the original/);f.failure(null);await f.c.confirm();assert.deepEqual(f.calls.at(-1).args,original);
 });
 await test('confirmed first rejection allows correction; unknown retry rejection stays locked',async()=>{
  const f=fixture();await f.c.load('DPL-1');await f.c.select(1);await f.c.set('reason','Return');f.failure({exc_type:'ValidationError'});await assert.rejects(()=>f.c.confirm());assert.equal(f.c.state.pending,null);await f.c.select(2);
  f.failure(new Error('network'));await assert.rejects(()=>f.c.confirm());f.failure({exc_type:'PermissionError'});await assert.rejects(()=>f.c.confirm());assert(f.c.state.pending);
 });
 await test('typed conflicting-payload rejection retains original recovery identity',async()=>{
  const f=fixture();await f.c.load('DPL-1');await f.c.select(1);await f.c.set('reason','Return');f.failure({exc_type:'DispatchRecoveryReplayError'});await assert.rejects(()=>f.c.confirm());assert(f.c.state.pending);
 });
 await test('lost post response retains mandatory ERP inputs without reopening their dialog',async()=>{
  const f=fixture();await create(f);await confirmSources(f);await f.c.confirm();f.env.inputs=async()=>({parent:{project:'P'},tables:{}});
  f.failure(new Error('network'));await assert.rejects(()=>f.c.confirm());const old=f.calls.at(-1).args;f.env.inputs=async()=>{throw new Error('Must not reread');};f.failure(null);await f.c.confirm();assert.deepEqual(f.calls.at(-1).args,old);
 });
 await test('cancel closes safely while unused-recovery cancellation requires a new reason',async()=>{
  const f=fixture();await create(f);await f.c.scan('CFG:CMD:RECOVERY_CANCEL');assert(!f.c.ready());await f.c.scan('Wrong destination');await f.c.confirm();assert.equal(f.calls.at(-1).method,'cancel_dispatch_recovery');assert.equal(f.c.state.context.recovery_manifest.state,'Cancelled');
  const before=f.calls.length;await f.c.scan('CFG:CMD:CANCEL');assert.equal(f.calls.length,before);assert.equal(f.closed(),1);
 });
 await test('refresh/reopen reads an existing Manifest and never creates another automatically',async()=>{
  const f=fixture();await create(f);await f.c.load('KMF-1');assert.equal(f.c.state.context.recovery_manifest.name,'KMF-1');assert.equal(f.calls.filter(row=>row.method==='create_dispatch_recovery').length,1);
  f.context.recovery_manifest.state='Dispatch Document Pending';await f.c.scan('CFG:CMD:RECOVERY_REFRESH');assert(!f.c.ready());assert.match(f.c.state.message,/ERP document/);
 });
 await test('failed load clears the previous checklist and readiness',async()=>{const f=fixture();await create(f);f.failure(new Error('wrong'));await assert.rejects(()=>f.c.load('BAD'));assert.equal(f.c.state.context,null);assert(!f.c.ready());});
 await test('duplicate confirmation and operator changes cannot submit additional actions',async()=>{
  const f=fixture();await f.c.load('DPL-1');await f.c.select(1);await f.c.set('reason','Return');await Promise.all([f.c.confirm(),f.c.confirm()]);assert.equal(f.calls.filter(row=>row.method==='create_dispatch_recovery').length,1);
  f.owner('OTHER');assert(!f.c.ready());await assert.rejects(()=>f.c.scan('TAG1'),/original Supervisor/);
 });
 await test('closing during a request ignores its late response',async()=>{
  const f=fixture();await f.c.load('DPL-1');await f.c.select(1);await f.c.set('reason','Return');let done;f.env.rpc=()=>new Promise(resolve=>{done=resolve;});const pending=f.c.confirm();await f.c.scan('CFG:CMD:CANCEL');done(f.context);await pending;assert.equal(f.closed(),1);assert.equal(f.c.state.context.recovery_manifest,null);
 });
 await test('ERP scalar, item-row and table requirements retain their scope',async()=>{
  const requirements=[{scope:'parent',fieldname:'project',fieldtype:'Link',label:'Project',options:'Project'},
   {scope:'child',table_field:'items',row_index:1,fieldname:'cost_center',fieldtype:'Link'},
   {scope:'table',fieldname:'sales_team',options:'Sales Team',fields:[{fieldname:'sales_person',fieldtype:'Link',options:'Sales Person',reqd:1}]}];
  const fields=erpFields(requirements);assert.equal(fields[2].fieldtype,'Table');assert.equal(fields[2].fields[0].reqd,1);
  const values=erpValues(requirements,{recovery_erp_0:'P',recovery_erp_1:'CC',recovery_erp_2:[{sales_person:'SP'}]});
  assert.equal(values.parent.project,'P');assert.equal(values.tables.items[1].cost_center,'CC');assert.equal(values.tables.sales_team[0].sales_person,'SP');
 });
 await test('actual dialog handles scanner-only Tab/Enter checklist through posting',async()=>{
  const f=adapter(),view=await f.launch(),d=f.dialogs[0];
  for(const [raw,key] of [['DPL-1','Tab'],['CFG:SELECT:1','Enter'],['CFG:CMD:RECOVERY_REASON','Tab'],['Return','Enter'],['CFG:CMD:CONFIRM','Tab'],['TAG1','Enter'],['CFG:SELECT:1','Tab'],['CFG:QTY:MATERIAL:5','Enter'],['CFG:CMD:CONFIRM','Tab'],['CFG:CMD:CONFIRM','Enter'],['CFG:CMD:CONFIRM','Tab']]){
   d.values.scan=raw;let prevented=0;d.fields_dict.scan.keydown({key,preventDefault(){prevented++;},stopPropagation(){}});await view.scan('CFG:CMD:HELP');assert.equal(prevented,1);
  }
  assert.equal(view.controller.state.context.recovery_manifest.state,'Received');assert(f.focused()>10);assert.match(d.summary,/MAT-STE-1/);
 });
 await test('touch quantity/reason and primary confirmation share the same controller',async()=>{
  const f=adapter({planScan:'DPL-1'}),view=await f.launch(),d=f.dialogs[0];await view.scan('CFG:SELECT:1');d.values.reason='Touch reason';d.fields_dict.reason.df.onchange();await d.config.primary_action();assert.equal(f.calls.at(-1).args.reason,'Touch reason');
  await view.scan('TAG1');await view.scan('CFG:SELECT:1');d.values.qty='5';d.fields_dict.qty.df.onchange();await d.config.primary_action();assert.equal(f.calls.at(-1).args.qty,5);
 });
 await test('blank Tab, Shift Tab and composing input retain native navigation',async()=>{
  const f=adapter();await f.launch();let prevented=0;for(const event of [{key:'Tab'},{key:'Tab',shiftKey:true},{key:'Enter',isComposing:true}])f.dialogs[0].fields_dict.scan.keydown({...event,preventDefault(){prevented++;},stopPropagation(){}});assert.equal(prevented,0);assert.equal(f.calls.length,0);
 });
 await test('camera scan deduplication and camera/parent cancellation restore focus',async()=>{
  const f=adapter(),view=await f.launch();await view.scan('CFG:CMD:RECOVERY_CAMERA');f.cameras[0].hide_dialog();f.cameras[0].config.on_scan({decodedText:'DPL-1'});await view.scan('CFG:CMD:HELP');assert.equal(f.calls.length,0);
  await view.scan('CFG:CMD:RECOVERY_CAMERA');f.cameras[1].config.on_scan({decodedText:'DPL-1'});f.cameras[1].config.on_scan({decodedText:'DPL-1'});await view.scan('CFG:CMD:HELP');assert.equal(f.calls.length,1);
  await view.scan('CFG:CMD:CANCEL');f.cameras[1].config.on_scan({decodedText:'DPL-2'});assert.equal(f.calls.length,1);assert(f.focused()>0);
 });
 await test('required ERP table rows and numbered columns remain scanner-operable',async()=>{
  const f=adapter({requirements:[{scope:'table',fieldname:'sales_team',label:'Sales Team',fields:[{fieldname:'sales_person',label:'Person',fieldtype:'Link',reqd:1},{fieldname:'allocated_percentage',label:'Percent',fieldtype:'Float',reqd:1}]}]}),view=await f.launch();
  for(const raw of ['DPL-1','CFG:SELECT:1','CFG:CMD:RECOVERY_REASON','Return','CFG:CMD:CONFIRM','TAG1','CFG:SELECT:1','CFG:QTY:MATERIAL:5','CFG:CMD:CONFIRM','CFG:CMD:CONFIRM'])await view.scan(raw);
  const pending=view.scan('CFG:CMD:CONFIRM');await tick();
  for(const raw of ['CFG:SELECT:1','CFG:CMD:DELIVERY_ADD_ROW','CFG:SELECT:1','PERSON','CFG:SELECT:2','100','CFG:CMD:CONFIRM'])await view.scan(raw);
  await pending;const values=JSON.parse(f.calls.at(-1).args.required_erp_inputs);assert.equal(values.tables.sales_team[0].sales_person,'PERSON');assert.equal(values.tables.sales_team[0].allocated_percentage,'100');
 });
 await test('camera unavailable leaves a focused scanner path',async()=>{const f=adapter({noCamera:true}),view=await f.launch();await view.scan('CFG:CMD:RECOVERY_CAMERA');assert.match(f.dialogs[0].summary,/Camera scanning is unavailable/);assert(f.focused()>0);});
 await test('required ERP scalar input remains scanner-operable inside the nested dialog',async()=>{
  const f=adapter({requirements:[{scope:'parent',fieldname:'project',label:'Project',fieldtype:'Link',options:'Project'}]}),view=await f.launch();
  for(const raw of ['DPL-1','CFG:SELECT:1','CFG:CMD:RECOVERY_REASON','Return','CFG:CMD:CONFIRM','TAG1','CFG:SELECT:1','CFG:QTY:MATERIAL:5','CFG:CMD:CONFIRM','CFG:CMD:CONFIRM'])await view.scan(raw);
  const pending=view.scan('CFG:CMD:CONFIRM');await tick();assert.equal(f.dialogs.length,2);await view.scan('CFG:SELECT:1');await view.scan('PROJ');await view.scan('CFG:CMD:CONFIRM');await pending;
  assert.equal(JSON.parse(f.calls.at(-1).args.required_erp_inputs).parent.project,'PROJ');assert.equal(view.controller.state.context.recovery_manifest.state,'Received');
 });
 await test('cancelling nested ERP inputs creates no stock movement and restores parent focus',async()=>{
  const f=adapter({requirements:[{scope:'parent',fieldname:'project',fieldtype:'Data'}]}),view=await f.launch();
  for(const raw of ['DPL-1','CFG:SELECT:1','CFG:CMD:RECOVERY_REASON','Return','CFG:CMD:CONFIRM','TAG1','CFG:SELECT:1','CFG:QTY:MATERIAL:5','CFG:CMD:CONFIRM','CFG:CMD:CONFIRM'])await view.scan(raw);
  const pending=view.scan('CFG:CMD:CONFIRM');await tick();await view.scan('CFG:CMD:CANCEL');await pending;assert.equal(f.calls.filter(r=>r.method==='post_dispatch_recovery').length,0);assert(f.focused()>0);assert(view.controller.ready());
 });
 await test('Finish Review transition occurs only after the recovery dialog closes',async()=>{
  const f=adapter(),view=await f.launch();for(const raw of ['DPL-1','CFG:SELECT:1','CFG:CMD:RECOVERY_REASON','Return','CFG:CMD:CONFIRM','TAG1','CFG:SELECT:1','CFG:QTY:MATERIAL:5','CFG:CMD:CONFIRM','CFG:CMD:CONFIRM','CFG:CMD:CONFIRM','CFG:CMD:FINISH_DISPATCH_REVIEW'])await view.scan(raw);
  assert(f.dialogs[0].hidden);assert.equal(f.transition(),1);
 });
 await test('global Logistics routing, Production command and printable catalogue expose recovery',async()=>{
  const panel=fs.readFileSync(require.resolve('../cfg_kanban/page/kanban_logistics/kanban_logistics.js'),'utf8'),operator=fs.readFileSync(require.resolve('../cfg_kanban/page/kanban_operator/kanban_operator.js'),'utf8'),catalogue=fs.readFileSync(require.resolve('../api/operator.py'),'utf8');
  for(const name of ['RECOVER_DISPATCH','RECOVERY_REASON','RECOVERY_SOURCE','RECOVERY_PREPARE','RECOVERY_POST','RECOVERY_CANCEL','RECOVERY_REFRESH','RECOVERY_CAMERA'])assert(catalogue.includes('CFG:CMD:'+name));assert(operator.includes('RECOVER_DISPATCH:"recovery"'));
  const a=panel.indexOf('\tasync function process_scan(value)'),b=panel.indexOf('\n\tasync function lookup_tag(',a);let observed;
  const run=new Function('$scanner','state','open_dispatch_review','command',`let active_loose_tag=null,opening_loose_tag=false,active_route_count_action=null,active_dispatch_review=null,opening_dispatch_review=false,active_delivery_action=null,opening_delivery_action=false,active_route_delivery=null,opening_route_delivery=false,active_prepared_delivery=null,opening_prepared_delivery=false,active_isolation=null,opening_isolation=false,active_repack=null,opening_repack=false;\n`+panel.slice(a,b)+'\nreturn process_scan(command);');
  await run({find:()=>({val(){}})},{lookup:{dispatch_plan:{name:'DPL-1'}}},(...args)=>{observed=args;},'CFG:CMD:RECOVER_DISPATCH');assert.deepEqual(observed,['recovery','DPL-1']);
 });
 await test('existing Draft with a confirmed tag exposes untagged count entry without a fake stock scan',async()=>{
  const f=adapter({tagQty:2,looseQty:1}),view=await f.launch(),d=f.dialogs[0];await create({c:view.controller});await view.scan('TAG1');
  assert.equal(d.fields_dict.qty.df.hidden,0);assert.equal(d.fields_dict.qty.df.read_only,1);assert.match(d.summary,/Enter Count:/);
  assert.match(d.fields_dict.qty.df.description,/does not require a QR/);
  await view.scan('CFG:SELECT:1');assert.equal(d.fields_dict.qty.df.read_only,0);assert.equal(String(d.values.qty??''),'');
  assert.equal(d.label,'Confirm Counted Loose Quantity');assert.match(d.fields_dict.qty.df.description,/expected 1 Nos/);
  d.values.qty='1';d.fields_dict.qty.df.onchange();await d.config.primary_action();
  const confirmed=f.calls.find(row=>row.method==='confirm_dispatch_recovery_loose');assert.equal(confirmed.args.qty,1);assert.equal(confirmed.args.line_name,'LOOSE-LINE');
  assert.equal(f.calls.filter(row=>row.method==='scan_dispatch_recovery').length,1);
  assert.equal(d.label,'Prepare and Reserve');assert.equal(d.enabled,true);
  d.fields_dict.prepare.df.click();await d.config.primary_action();assert.equal(f.context.recovery_manifest.state,'Prepared');
  assert.equal(d.fields_dict.qty.df.hidden,1);
  d.fields_dict.post.df.click();await d.config.primary_action();assert.equal(f.context.recovery_manifest.state,'Received');
 });
 await test('scanner quantity is mirrored into the visible count field for the selected row',async()=>{
  const f=adapter({looseQty:1}),view=await f.launch(),d=f.dialogs[0];await create({c:view.controller});
  await view.scan('CFG:SELECT:1');await view.scan('CFG:QTY:MATERIAL:1');
  assert.equal(d.values.qty,'1');assert.equal(d.fields_dict.qty.df.read_only,0);assert.equal(view.controller.state.line,'LOOSE-LINE');
  await view.scan('CFG:CMD:CONFIRM');assert.equal(f.context.recovery_manifest.lines[1].loading_confirmed,1);
 });
 await test('loose entry never preselects a row or fills the expected amount as a physical count',async()=>{
  const f=adapter(),view=await f.launch(),d=f.dialogs[0];await create({c:view.controller});
  assert.equal(view.controller.state.line,'');assert.equal(view.controller.state.qty,'');assert.equal(d.fields_dict.qty.df.read_only,1);
  await view.scan('CFG:SELECT:1');assert.equal(String(d.values.qty??''),'');assert.equal(d.enabled,false);
  d.values.qty='4';d.fields_dict.qty.df.onchange();await d.config.primary_action();
  assert.equal(f.calls.filter(row=>row.method==='confirm_dispatch_recovery_loose').length,0);assert.equal(d.enabled,false);
 });
 await test('unknown loose confirmation freezes the visible quantity and retries the original identity',async()=>{
  const f=adapter({looseQty:1}),view=await f.launch(),d=f.dialogs[0];await create({c:view.controller});await view.scan('CFG:SELECT:1');await view.scan('CFG:QTY:MATERIAL:1');
  f.failure(new Error('Lost response'));await d.config.primary_action();const original=f.calls.at(-1).args;
  assert.equal(d.fields_dict.qty.df.read_only,1);assert(view.controller.state.pending);
  d.values.qty='2';d.fields_dict.qty.df.onchange();await tick();assert.equal(d.values.qty,'1');
  f.failure(null);await d.config.primary_action();assert.deepEqual(f.calls.at(-1).args,original);
 });
 await test('recovery quantity descriptions escape source metadata',async()=>{
  const f=adapter(),view=await f.launch(),d=f.dialogs[0];await create({c:view.controller});
  f.context.recovery_manifest.lines[1].item_code='<img src=x>';await view.scan('KMF-1');await view.scan('CFG:SELECT:1');
  assert(!d.fields_dict.qty.df.description.includes('<img'));assert(d.fields_dict.qty.df.description.includes('&lt;img'));
 });
 await test('raw manual input enables quantity confirmation without waiting for blur or native onchange',async()=>{
  const f=adapter({looseQty:1}),view=await f.launch(),d=f.dialogs[0];await create({c:view.controller});await view.scan('TAG1');await view.scan('CFG:SELECT:1');
  const before=f.focused();await d.fields_dict.qty['input.cfg_dispatch_recovery']({currentTarget:{value:'1'}});
  assert.equal(view.controller.state.qty,'1');assert.equal(d.values.qty,'1');assert.equal(d.enabled,true);assert.equal(f.focused(),before);
  await d.config.primary_action();assert.equal(f.calls.at(-1).method,'confirm_dispatch_recovery_loose');assert.equal(f.calls.at(-1).args.qty,1);
 });
 await test('manual multi-digit decimals keep focus and only become ready at the exact quantity',async()=>{
  const f=adapter({looseQty:12.5});f.lines[1].stock_uom='Kg';const view=await f.launch(),d=f.dialogs[0];await create({c:view.controller});await view.scan('TAG1');await view.scan('CFG:SELECT:1');
  const before=f.focused();for(const raw of ['1','12','12.','12.5']){
   await d.fields_dict.qty['input.cfg_dispatch_recovery']({currentTarget:{value:raw}});
   assert.equal(view.controller.state.qty,raw);assert.equal(d.values.qty,raw);assert.equal(d.enabled,raw==='12.5');
  }
  assert.equal(f.focused(),before);await d.config.primary_action();assert.equal(f.calls.at(-1).args.qty,12.5);
 });
 await test('delayed native change after typing cannot steal focus or replace the count',async()=>{
  const f=adapter({looseQty:1}),view=await f.launch(),d=f.dialogs[0];await create({c:view.controller});await view.scan('CFG:SELECT:1');
  await d.fields_dict.qty['input.cfg_dispatch_recovery']({currentTarget:{value:'1'}});const before=f.focused();
  await d.fields_dict.qty.df.onchange();assert.equal(d.values.qty,'1');assert.equal(f.focused(),before);assert.equal(view.controller.state.qty,'1');
 });
 await test('unchanged quantity properties do not refresh the field while typing',async()=>{
  const f=adapter({looseQty:1}),view=await f.launch(),d=f.dialogs[0];await create({c:view.controller});await view.scan('CFG:SELECT:1');
  let refreshes=0;const original=d.set_df_property.bind(d);d.set_df_property=(name,key,value)=>{if(name==='qty')refreshes++;original(name,key,value);};
  await d.fields_dict.qty['input.cfg_dispatch_recovery']({currentTarget:{value:'1'}});assert.equal(refreshes,0);
 });
 console.log(`${checks} E5 recovery UI checks passed`);
})().catch(error=>{console.error(error);process.exitCode=1;});
