/* Actual E5A scanner/controller/adapter and global routing with dependency doubles. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {createController,open}=require('../public/js/dispatch_review.js');
const actions=['No Remaining Prepared Stock','Close Trip - Stock Stays','Continue Same Plan Overnight','Returned to Warehouse','Transferred to Another Lorry'];
let checks=0;async function test(name,work){await work();checks++;console.log('ok '+name);}
function fixture(options={}){
 let owner='EMP',failure=null,n=0,closed=0,success=0;
 const context={plan:{name:'DPL-1',state:'Loaded'},review:options.review===false?null:{name:'KDR-1',state:options.state||'Reviewing'},
  balances:[{item_code:'ITEM',stock_uom:'Nos',loaded_qty:5,delivered_qty:2,remaining_qty:3}],actions,balance_hash:'HASH',boundary:'All lorry stock is counted; this review settles one Plan.'};
 const calls=[];
 const env={mode:options.mode||'finish',owner:()=>owner,openedOwner:'EMP',token:()=> 'TOKEN',nonce:()=>`E-${++n}`,render(){},close(){closed++;},camera(){},
  success:async()=>{success++;},rpc:async(method,args)=>{calls.push({method,args:structuredClone(args)});if(failure)throw failure;return structuredClone(context);}};
 return {c:createController(env),env,calls,context,owner:v=>owner=v,failure:v=>failure=v,closed:()=>closed,success:()=>success};
}
async function ready(f,choice=2){for(const scan of ['DPL-1',`CFG:SELECT:${choice}`,'KREC-1','CFG:CMD:DISPATCH_REVIEW_REASON','Closing reason'])await f.c.scan(scan);}
function adapter(options={}){
 const f=fixture(options);let dialog,focused=0,hidden=0;const cameras=[];
 class Dialog{
  constructor(config){dialog=this;this.config=config;this.fields_dict={};this.values={};for(const field of config.fields){this.fields_dict[field.fieldname]={df:field,$input:{focus(){focused++;},on:(event,handler)=>{this.fields_dict[field.fieldname][event]=handler;}},$wrapper:{html:value=>{this.summary=value;},find:()=>({on(){}})}};}}
  get_value(k){return this.values[k];}set_value(k,v){this.values[k]=v;}set_df_property(k,p,v){this.fields_dict[k].df[p]=v;}
  show(){}hide(){hidden++;this.onhide?.();}disable_primary_action(){this.enabled=false;}enable_primary_action(){this.enabled=true;}
 }
 class Camera{
  constructor(config){this.config=config;this.hidden=[];this.visible=true;cameras.push(this);this.dialog={$wrapper:{one:(event,fn)=>this.hidden.push(fn)}};}
  hide_dialog(){if(!this.visible)return;this.visible=false;this.hidden.splice(0).forEach(fn=>fn());}
 }
 const launch=()=>open({frappe:{utils:{escape_html:v=>String(v??'').replaceAll('<','&lt;')},ui:{Dialog,...(!options.noCamera?{Scanner:Camera}:{})},
  call:async({method,args})=>({message:await f.env.rpc(method.split('.').at(-1),args)})},mode:f.env.mode,planScan:options.planScan,
  owner:f.env.owner,token:f.env.token,nonce:f.env.nonce,success:f.env.success,recover:plan=>f.env.recover(plan),onClose(){},errorMessage:(err,fallback)=>err.message||fallback});
 return {...f,launch,dialog:()=>dialog,focused:()=>focused,hidden:()=>hidden,cameras};
}
(async()=>{
 await test('begin mode scans Plan and creates a review without any quantity input',async()=>{
  const f=fixture({mode:'begin',review:false});await f.c.scan('DPL-1');await f.c.scan('CFG:CMD:CONFIRM');
  assert.equal(f.calls.at(-1).method,'begin_dispatch_review');assert.equal(f.calls.at(-1).args.dispatch_plan,'DPL-1');assert(!('qty' in f.calls.at(-1).args));
 });
 await test('stock-stays and continuing overnight are distinct closing choices',async()=>{
  for(const choice of [2,3]){const f=fixture();await ready(f,choice);await f.c.confirm();assert.equal(f.calls.at(-1).args.action,actions[choice-1]);assert.equal(f.calls.at(-1).args.balance_hash,'HASH');}
 });
 await test('return and transfer require an explicitly scanned movement entry',async()=>{
  const f=fixture();await ready(f,5);assert.equal(f.c.ready(),false);await f.c.scan('CFG:CMD:DISPATCH_REVIEW_MOVEMENT');await f.c.scan('MAT-STE-123');assert(f.c.ready());
  await f.c.confirm();assert.equal(f.calls.at(-1).args.movement_stock_entry,'MAT-STE-123');
 });
 await test('hold and resume require a reason and use separate controlled endpoints',async()=>{
  for(const [command,state,method] of [['HOLD_DISPATCH_REVIEW','Reviewing','hold_dispatch_review'],['RESUME_DISPATCH_REVIEW','Overnight','resume_dispatch_review']]){
   const f=fixture({state});await f.c.scan('DPL-1');await f.c.scan('CFG:CMD:'+command);assert(!f.c.ready());await f.c.scan('CFG:CMD:DISPATCH_REVIEW_REASON');await f.c.scan('Checked stock');await f.c.confirm();assert.equal(f.calls.at(-1).method,method);
  }
 });
 await test('overnight and completed reviews cannot accidentally be finished again',async()=>{
  for(const state of ['Overnight','Completed']){const f=fixture({state});await ready(f);assert(!f.c.ready());await assert.rejects(()=>f.c.confirm(),/Complete the review/);}
 });
 await test('failed context scan clears old readiness',async()=>{
  const f=fixture();await ready(f);assert(f.c.ready());f.failure(new Error('wrong Plan'));await assert.rejects(()=>f.c.scan('WRONG'));assert.equal(f.c.state.context,null);assert(!f.c.ready());
 });
 await test('invalid numbered choice clears a previous selected decision',async()=>{
  const f=fixture();await ready(f);await assert.rejects(()=>f.c.scan('CFG:SELECT:10'),/displayed closing/);assert.equal(f.c.state.action,'');assert(!f.c.ready());
 });
 await test('lost result retains original closing evidence and token',async()=>{
  const f=fixture();await ready(f);f.failure(new Error('network'));await assert.rejects(()=>f.c.confirm());const original=f.calls.at(-1).args;
  await assert.rejects(()=>f.c.scan('CFG:CMD:DISPATCH_REVIEW_REFRESH'),/Retry the original/);f.failure(null);await f.c.confirm();assert.deepEqual(f.calls.at(-1).args,original);
 });
 await test('first confirmed rejection permits re-review while a failed unknown retry stays locked',async()=>{
  const f=fixture();await ready(f);f.failure({exc_type:'ValidationError'});await assert.rejects(()=>f.c.confirm());assert.equal(f.c.state.pending,null);
  f.failure(null);await f.c.scan('CFG:CMD:DISPATCH_REVIEW_REFRESH');await f.c.scan('CFG:SELECT:2');await f.c.scan('KREC-2');await f.c.scan('CFG:CMD:DISPATCH_REVIEW_REASON');await f.c.scan('New count');
  f.failure(new Error('network'));await assert.rejects(()=>f.c.confirm());f.failure({exc_type:'PermissionError'});await assert.rejects(()=>f.c.confirm());assert(f.c.state.pending);
 });
 await test('changed-payload replay rejection retains the original action',async()=>{
  const f=fixture();await ready(f);f.failure({exc_type:'DispatchReviewReplayError'});await assert.rejects(()=>f.c.confirm());assert(f.c.state.pending);
 });
 await test('duplicate confirms and owner switches cannot create additional actions',async()=>{
  const f=fixture();await ready(f);await Promise.all([f.c.confirm(),f.c.confirm()]);assert.equal(f.calls.filter(c=>c.method==='finish_dispatch_review').length,1);
  const g=fixture();await ready(g);g.owner('OTHER');assert(!g.c.ready());await assert.rejects(()=>g.c.confirm());
 });
 await test('cancel during RPC ignores the late response and keeps the next screen intact',async()=>{
  const f=fixture();await ready(f);let done;f.env.rpc=(method,args)=>new Promise(resolve=>{done=resolve;});const pending=f.c.confirm();await f.c.scan('CFG:CMD:CANCEL');done(f.context);await pending;assert.equal(f.closed(),1);assert.equal(f.success(),0);
 });
 await test('actual dialog supports Tab/Enter scan sequence with focus restoration',async()=>{
  const f=adapter(),view=await f.launch(),d=f.dialog();
  for(const [value,key] of [['DPL-1','Tab'],['CFG:SELECT:3','Enter'],['KREC-1','Tab'],['CFG:CMD:DISPATCH_REVIEW_REASON','Enter'],['Next day','Tab'],['CFG:CMD:CONFIRM','Enter']]){
   d.values.scan=value;let prevented=0;d.fields_dict.scan.keydown({key,preventDefault(){prevented++;},stopPropagation(){}});await view.scan('CFG:CMD:HELP');assert.equal(prevented,1);
  }
  assert.equal(f.calls.at(-1).args.action,'Continue Same Plan Overnight');assert.equal(f.hidden(),1);assert(f.focused()>2);
 });
 await test('blank Tab, Shift Tab and composing input do not consume navigation',async()=>{
  const f=adapter();await f.launch();const d=f.dialog();let prevented=0;
  for(const event of [{key:'Tab'},{key:'Tab',shiftKey:true},{key:'Enter',isComposing:true}])d.fields_dict.scan.keydown({...event,preventDefault(){prevented++;},stopPropagation(){}});
  assert.equal(prevented,0);assert.equal(f.calls.length,0);
 });
 await test('touch evidence inputs and primary action send the same reviewed details',async()=>{
  const f=adapter({planScan:'DPL-1'}),view=await f.launch(),d=f.dialog();await view.scan('CFG:SELECT:2');d.values.count='KREC-TOUCH';d.fields_dict.count.df.onchange();d.values.reason='Checked';d.fields_dict.reason.df.onchange();await d.config.primary_action();
  assert.equal(f.calls.at(-1).args.reconciliation_name,'KREC-TOUCH');assert.equal(f.calls.at(-1).args.reason,'Checked');
 });
 await test('camera cancellation and parent close reject late/duplicate scans',async()=>{
  const f=adapter(),view=await f.launch();await view.scan('CFG:CMD:DISPATCH_REVIEW_CAMERA');f.cameras[0].hide_dialog();f.cameras[0].config.on_scan({decodedText:'DPL-1'});await view.scan('CFG:CMD:HELP');assert.equal(f.calls.length,0);
  await view.scan('CFG:CMD:DISPATCH_REVIEW_CAMERA');f.cameras[1].config.on_scan({decodedText:'DPL-1'});f.cameras[1].config.on_scan({decodedText:'DPL-1'});await view.scan('CFG:CMD:HELP');assert.equal(f.calls.length,1);
  await view.scan('CFG:CMD:CANCEL');f.cameras[1].config.on_scan({decodedText:'DPL-OTHER'});assert.equal(f.calls.length,1);
 });
 await test('unavailable camera keeps a focused scanner alternative',async()=>{
  const f=adapter({noCamera:true}),view=await f.launch();await view.scan('CFG:CMD:DISPATCH_REVIEW_CAMERA');assert.match(f.dialog().summary,/Camera scanning is unavailable/);assert(f.focused()>0);
 });
 await test('global dispatch and catalogue expose the new review actions',async()=>{
  const root=path.resolve(__dirname,'..'),panel=fs.readFileSync(path.join(root,'cfg_kanban/page/kanban_logistics/kanban_logistics.js'),'utf8'),production=fs.readFileSync(path.join(root,'cfg_kanban/page/kanban_operator/kanban_operator.js'),'utf8'),catalogue=fs.readFileSync(path.join(root,'api/operator.py'),'utf8');
  for(const command of ['REVIEW_DISPATCH','FINISH_DISPATCH_REVIEW','HOLD_DISPATCH_REVIEW','RESUME_DISPATCH_REVIEW','DISPATCH_REVIEW_COUNT','DISPATCH_REVIEW_MOVEMENT','DISPATCH_REVIEW_REASON','DISPATCH_REVIEW_CAMERA','DISPATCH_REVIEW_REFRESH'])assert(catalogue.includes('CFG:CMD:'+command));
  for(const command of ['REVIEW_DISPATCH','FINISH_DISPATCH_REVIEW','HOLD_DISPATCH_REVIEW','RESUME_DISPATCH_REVIEW'])assert(production.includes(command));
  const a=panel.indexOf('\tasync function process_scan(value)'),b=panel.indexOf('\n\tasync function lookup_tag(',a);let observed;
  const run=new Function('$scanner','state','open_dispatch_review','command',`let active_route_count_action=null,active_dispatch_review=null,opening_dispatch_review=false,active_delivery_action=null,opening_delivery_action=false,active_route_delivery=null,opening_route_delivery=false,active_prepared_delivery=null,opening_prepared_delivery=false,active_isolation=null,opening_isolation=false,active_repack=null,opening_repack=false;\n`+panel.slice(a,b)+'\nreturn process_scan(command);');
  await run({find:()=>({val(){}})},{lookup:{dispatch_plan:{name:'DPL-1'}}},(...args)=>{observed=args;},'CFG:CMD:FINISH_DISPATCH_REVIEW');assert.deepEqual(observed,['finish','DPL-1']);
 });
 await test('linked recovery preselects its exact submitted movement and disposition',async()=>{
  const f=fixture();f.context.recovery={state:'Received',dispatch_stock_entry:'MOVE-RECOVERY',recovery_action:actions[3]};await f.c.load('DPL-1');
  assert.equal(f.c.state.movement,'MOVE-RECOVERY');assert.equal(f.c.state.action,actions[3]);assert(!f.c.ready());
  const g=adapter({planScan:'DPL-1'});g.context.recovery={state:'Received',dispatch_stock_entry:'MOVE-RECOVERY',recovery_action:actions[3]};await g.launch();assert.equal(g.dialog().values.movement,'MOVE-RECOVERY');
 });
 await test('recovery navigation waits for the Review dialog to close and keeps the Plan',async()=>{
  const f=adapter({planScan:'DPL-1'});let observed;f.env.recover=plan=>{assert.equal(f.hidden(),1);observed=plan;};const view=await f.launch();await view.scan('CFG:CMD:RECOVER_DISPATCH');assert.equal(observed,'DPL-1');assert(view.controller.state.closed);
 });
 await test('terminal Reviews cannot open another recovery checklist',async()=>{
  const f=fixture({state:'Completed'});await f.c.load('DPL-1');await assert.rejects(()=>f.c.scan('CFG:CMD:RECOVER_DISPATCH'),/Begin a Dispatch Review/);assert(!f.c.state.closed);
 });
 console.log(`${checks} E5 review UI checks passed`);
})().catch(error=>{console.error(error);process.exitCode=1;});
