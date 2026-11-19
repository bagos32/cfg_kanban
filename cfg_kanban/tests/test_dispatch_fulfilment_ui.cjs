/* Actual E4A controller/dialog and Logistics scanner routing, with RPC/UI doubles. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {createController,open}=require('../public/js/dispatch_fulfilment.js');
let checks=0;
function fixture(){
 const plan={name:'DPL-1',business_label:'Customer load',vehicle_reference:'Lorry 1',quantity_summary:'5 Nos / 2 Kg'};
 let owner='EMP',count=0,closed=0,success=0,failure=null;const calls=[];
 const env={owner:()=>owner,openedOwner:'EMP',token:()=> 'SESSION',nonce:()=>`E-${++count}`,render(){},close(){closed++;},camera(){},
  success:async()=>{success++;},rpc:async(method,args)=>{
   calls.push({method,args:structuredClone(args)});
   if(method==='prepared_delivery_context')return {plans:[plan],customer_scan:args.scan_value==='SITE'?'SITE':null};
   if(failure)throw failure;return {name:'DELIVERY',dispatch_plan:args.dispatch_plan};
  }};
 return {c:createController(env),env,plan,calls,owner:v=>{owner=v;},failure:v=>{failure=v;},closed:()=>closed,success:()=>success};
}
async function ready(f){await f.c.scan('DPL-1');await f.c.scan('SITE');}
async function test(name,fn){await fn();checks++;console.log('ok '+name);}
function ui(options={}){
 const f=fixture();let dialog,focused=0,closed=0;const cameras=[];
 class Dialog{
  constructor(config){dialog=this;this.config=config;this.values={};this.fields_dict={};
   for(const field of config.fields){this.fields_dict[field.fieldname]={df:field,$input:{focus(){focused++;},on:(name,fn)=>{this.fields_dict[field.fieldname][name]=fn;}},$wrapper:{html:value=>{this.html=value;},find:()=>({on(){}})}};}
  }
  get_value(name){return this.values[name];}set_value(name,value){this.values[name]=value;}
  show(){}hide(){closed++;this.onhide();}disable_primary_action(){this.enabled=false;}enable_primary_action(){this.enabled=true;}
 }
 class Camera{
  constructor(config){this.config=config;this.hidden=[];this.visible=true;cameras.push(this);this.dialog={$wrapper:{one:(name,fn)=>{this.hidden.push(fn);}}};}
  hide_dialog(){if(!this.visible)return;this.visible=false;for(const fn of this.hidden.splice(0))fn();}
  async decode(value){await this.config.on_scan({decodedText:value});this.hide_dialog();}
 }
 const launch=()=>open({frappe:{utils:{escape_html:value=>String(value??'').replaceAll('<','&lt;')},ui:{Dialog,...(!options.noCamera?{Scanner:Camera}:{})},
  call:async({method,args})=>({message:await f.env.rpc(method.split('.').at(-1),args)})},
  token:f.env.token,owner:f.env.owner,nonce:f.env.nonce,success:f.env.success,onClose(){},errorMessage:(err,fallback)=>err.message||fallback,
  planScan:options.planScan,siteScan:options.siteScan});
 return {...f,launch,dialog:()=>dialog,focused:()=>focused,closed:()=>closed,cameras};
}
(async()=>{
 await test('loaded Plan then Customer Site scan sends no retyped quantity',async()=>{
  const f=fixture();await ready(f);await f.c.scan('CFG:CMD:CONFIRM');
  assert.equal(f.calls.at(-1).args.dispatch_plan,'DPL-1');assert.equal(f.calls.at(-1).args.customer_scan,'SITE');
  assert(!('qty' in f.calls.at(-1).args));assert.equal(f.success(),1);
 });
 await test('Site first with one eligible Plan is ready without ambiguity',async()=>{
  const f=fixture();await f.c.scan('SITE');assert.equal(f.c.state.plan.name,'DPL-1');await f.c.confirm();assert.equal(f.success(),1);
 });
 await test('multiple Plans require explicit numbered selection and page after ten',async()=>{
  const f=fixture();f.env.rpc=async()=>({plans:Array.from({length:12},(_,i)=>({...f.plan,name:`DPL-${i+1}`})),customer_scan:'SITE'});
  await f.c.scan('SITE');assert.equal(f.c.state.plan,null);await assert.rejects(()=>f.c.confirm(),/exact prepared Plan/);
  await f.c.scan('CFG:CMD:NEXT_MATERIALS');await f.c.scan('CFG:SELECT:2');assert.equal(f.c.state.plan.name,'DPL-12');
 });
 await test('wrong site does not silently select another prepared load',async()=>{
  const f=fixture();await f.c.scan('DPL-1');f.env.rpc=async()=>({plans:[{name:'DPL-OTHER'}],customer_scan:'WRONG'});
  await assert.rejects(()=>f.c.scan('WRONG'),/no matching prepared Plan/);assert.equal(f.c.state.customerScan,'');assert.equal(f.c.state.plan.name,'DPL-1');
 });
 await test('lost response preserves the original request and blocks changed selection',async()=>{
  const f=fixture();await ready(f);f.failure(new Error('network'));await assert.rejects(()=>f.c.confirm(),/network/);
  const original=f.calls.at(-1).args;await assert.rejects(()=>f.c.scan('CFG:CMD:PREPARED_DELIVERY_SOURCE'),/Retry the original/);
  f.failure(null);await f.c.confirm();assert.deepEqual(f.calls.at(-1).args,original);assert.equal(f.success(),1);
 });
 await test('confirmed rejection permits correction with a fresh request token',async()=>{
  const f=fixture();await ready(f);f.failure({exc_type:'ValidationError'});await assert.rejects(()=>f.c.confirm());
  assert.equal(f.c.state.pending,null);await f.c.scan('CFG:CMD:PREPARED_DELIVERY_SOURCE');await ready(f);
  f.failure(null);await f.c.confirm();assert.equal(f.calls.at(-1).args.event_token,'E-2');
 });
 await test('repeated confirmation creates only one request while busy and after success',async()=>{
  const f=fixture();await ready(f);await Promise.all([f.c.confirm(),f.c.confirm()]);await f.c.confirm();
  assert.equal(f.calls.filter(c=>c.method==='start_prepared_delivery').length,1);
 });
 await test('operator changes cannot confirm the original selection',async()=>{
  const f=fixture();await ready(f);f.owner('OTHER');await assert.rejects(()=>f.c.confirm(),/original operator/);
 });
 await test('cancel closes safely without creating a Session',async()=>{
  const f=fixture();await ready(f);await f.c.scan('CFG:CMD:CANCEL');await f.c.confirm();assert.equal(f.closed(),1);assert.equal(f.success(),0);
 });
 await test('scanner Tab and Enter share the dialog sequence and restore focus',async()=>{
  const f=ui();const view=await f.launch(),d=f.dialog();
  const key=async(value,key)=>{d.values.scan=value;let prevented=0;await d.fields_dict.scan.keydown({key,preventDefault(){prevented++;},stopPropagation(){}});return prevented;};
  assert.equal(await key('DPL-1','Tab'),1);assert.equal(await key('SITE','Enter'),1);
  await view.scan('CFG:CMD:CONFIRM');assert.equal(f.success(),1);assert.equal(f.closed(),1);assert(f.focused()>0);
 });
 await test('blank Tab and Shift Tab keep normal focus navigation',async()=>{
  const f=ui();await f.launch();const d=f.dialog();d.values.scan='';let prevented=0;
  await d.fields_dict.scan.keydown({key:'Tab',preventDefault(){prevented++;},stopPropagation(){}});
  d.values.scan='DPL-1';await d.fields_dict.scan.keydown({key:'Tab',shiftKey:true,preventDefault(){prevented++;},stopPropagation(){}});
  assert.equal(prevented,0);assert.equal(f.calls.length,0);
 });
 await test('touch selection and confirmation submit the same Plan/site fields',async()=>{
  const f=ui({planScan:'DPL-1',siteScan:'SITE'});await f.launch();assert(f.dialog().enabled);
  await f.dialog().config.primary_action();assert.equal(f.success(),1);assert.equal(f.calls.at(-1).args.customer_scan,'SITE');
 });
 await test('camera decode is accepted once; late result after cancel is ignored',async()=>{
  const f=ui();const view=await f.launch();await view.scan('CFG:CMD:PREPARED_DELIVERY_CAMERA');const camera=f.cameras[0];
  camera.hide_dialog();await camera.config.on_scan({decodedText:'DPL-1'});assert.equal(f.calls.length,0);
  await view.scan('CFG:CMD:PREPARED_DELIVERY_CAMERA');await f.cameras[1].decode('DPL-1');
  await view.scan('CFG:CMD:HELP');assert.equal(f.calls.length,1);
 });
 await test('closing parent stops camera and ignores delayed results',async()=>{
  const f=ui();const view=await f.launch();await view.scan('CFG:CMD:PREPARED_DELIVERY_CAMERA');const camera=f.cameras[0];
  await view.scan('CFG:CMD:CANCEL');assert(!camera.visible);await camera.config.on_scan({decodedText:'SITE'});assert.equal(f.calls.length,0);
 });
 await test('camera unavailable reports a useful error and keeps scanner focus',async()=>{
  const f=ui({noCamera:true});const view=await f.launch();await view.scan('CFG:CMD:PREPARED_DELIVERY_CAMERA');
  assert.match(f.dialog().html,/Camera scanning is unavailable/);assert(f.focused()>0);
 });
 await test('all new commands are in the print catalogue and global Logistics scanner',async()=>{
  const root=path.resolve(__dirname,'../..');const panel=fs.readFileSync(path.join(root,'cfg_kanban/cfg_kanban/page/kanban_logistics/kanban_logistics.js'),'utf8');
  const catalogue=fs.readFileSync(path.join(root,'cfg_kanban/api/operator.py'),'utf8');
  for(const command of ['START_PREPARED_DELIVERY','PREPARED_DELIVERY_SOURCE','PREPARED_DELIVERY_CAMERA'])assert(catalogue.includes('CFG:CMD:'+command));
  assert(panel.includes('if (active_prepared_delivery) return active_prepared_delivery.scan(raw);'));
  const start=panel.indexOf('\tasync function process_scan(value)'),end=panel.indexOf('\n\tasync function lookup_tag(',start);let called;
  const run=new Function('$scanner','active_route_delivery','opening_route_delivery','active_prepared_delivery','opening_prepared_delivery','active_isolation','opening_isolation','active_repack','opening_repack','scanner_error','repack_scanner_help','open_prepared_delivery','state',panel.slice(start,end)+'\nreturn process_scan("CFG:CMD:START_PREPARED_DELIVERY");');
  await run({find:()=>({val(){}})},null,false,null,false,null,false,null,false,()=>{},()=>{},(...args)=>{called=args;},{lookup:{dispatch_plan:{name:'DPL-1'}}});
  assert.equal(called[0],'DPL-1');
 });
 await test('operator switch during creation does not show the old Session to the new operator',async()=>{
  const f=fixture();await ready(f);const rpc=f.env.rpc;f.env.rpc=async(method,args)=>{const result=await rpc(method,args);f.owner('OTHER');return result;};
  await f.c.confirm();assert.equal(f.success(),0);assert.equal(f.c.state.plan,null);assert.match(f.c.state.message,/original operator/);
 });
 await test('closing during initial lookup cannot leave a stale active dialog adapter',async()=>{
  const f=ui({planScan:'DPL-1'});let resolve;f.env.rpc=()=>new Promise(r=>{resolve=r;});
  const loading=f.launch();await Promise.resolve();f.dialog().hide();resolve({plans:[f.plan],customer_scan:null});
  assert.equal(await loading,null);assert.equal(f.success(),0);
 });
 console.log(`${checks} E4A UI checks passed`);
})().catch(error=>{console.error(error);process.exitCode=1;});
