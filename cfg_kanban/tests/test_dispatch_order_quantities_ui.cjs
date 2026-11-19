/* Actual Dispatch dialog with RPC/grid doubles; no live Frappe/browser acceptance. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'../..');
const source=fs.readFileSync(path.join(root,'cfg_kanban/cfg_kanban/page/kanban_logistics/kanban_logistics.js'),'utf8');
const body=source.slice(source.indexOf('\tfunction create_dispatch_plan_dialog(profile)'),source.indexOf('\n\tasync function open_dispatch_plan('));
let count=0;
function fixture(){
 let dialog,focus=0,renders=0;const errors=[],calls=[],responses=[];
 class Dialog{
  constructor(config){this.config=config;this.values={};this.fields_dict={};this.enabled=true;dialog=this;
   for(const f of config.fields){this.values[f.fieldname]=f.default||'';this.fields_dict[f.fieldname]={df:f,grid:{refresh(){}}};}
  }
  get_value(name){return this.values[name];}
  enable_primary_action(){this.enabled=true;}
  disable_primary_action(){this.enabled=false;}
  show(){}
  hide(){this.onhide();}
  async change(name,value){this.values[name]=value;return this.fields_dict[name].df.onchange?.();}
  values_for_submit(){return {...this.values,items:this.fields_dict.items.df.data||[]};}
 }
 const state={token:'SESSION'};
 const frappe={ui:{Dialog},utils:{escape_html:String},datetime:{get_today:()=> '2026-11-19'},call:async request=>{
  calls.push(structuredClone(request));
  if(request.method.endsWith('get_dispatch_sales_order_lines')) return responses.shift()();
  return {message:{name:'PLAN'}};
 }};
 new Function('frappe','__','state','unique_token','focus_scanner','render_lookup','scanner_error','server_error_message',body+'\ncreate_dispatch_plan_dialog({name:"PROFILE",plan_type:"Customer Order",company:"B",customer_site:"SITE"});')(
  frappe,x=>x,state,()=> 'TOKEN',()=>{focus++;},()=>{renders++;},msg=>errors.push(msg),(err,fallback)=>err.message||fallback);
 const lines=[{item_code:'ITEM',stock_uom:'Nos',requested_qty:36}];
 return {dialog,state,errors,calls,responses,lines,focus:()=>focus,renders:()=>renders};
}
async function check(name,fn){await fn();count++;console.log('ok '+name);}
(async()=>{
 await check('all visible table columns including Qty fit Frappe grid width',()=>{
  const f=fixture(),columns=f.dialog.fields_dict.items.df.fields.filter(x=>x.in_list_view);
  assert.equal(columns.reduce((n,x)=>n+x.columns,0),10);
  assert(columns.find(x=>x.fieldname==='requested_qty'));assert(columns.find(x=>x.fieldname==='stock_uom'));
 });
 await check('Sales Order selection loads remaining stock quantities and partial edit is submitted',async()=>{
  const f=fixture();f.responses.push(async()=>({message:{lines:f.lines}}));await f.dialog.change('sales_order','SO');
  assert.equal(f.calls[0].args.customer_site,'SITE');assert.equal(f.calls[0].args.dispatch_profile,'PROFILE');
  assert.equal(f.dialog.fields_dict.items.df.data[0].requested_qty,36);
  f.dialog.fields_dict.items.df.data[0].requested_qty=24;
  await f.dialog.config.primary_action(f.dialog.values_for_submit());
  assert.equal(JSON.parse(f.calls.at(-1).args.lines)[0].requested_qty,24);assert.equal(f.renders(),1);assert.equal(f.focus(),2);
 });
 await check('late response cannot replace a newer Sales Order',async()=>{
  const f=fixture();let resolve;f.responses.push(()=>new Promise(r=>{resolve=r;}));const first=f.dialog.change('sales_order','OLD');
  f.responses.push(async()=>({message:{lines:[{item_code:'NEW',requested_qty:7}]}}));await f.dialog.change('sales_order','NEW');
  resolve({message:{lines:f.lines}});await first;
  assert.equal(f.dialog.fields_dict.items.df.data[0].item_code,'NEW');assert(f.dialog.enabled);
 });
 await check('confirmation is blocked while quantities load',async()=>{
  const f=fixture();let resolve;f.responses.push(()=>new Promise(r=>{resolve=r;}));const loading=f.dialog.change('sales_order','SO');
  assert(!f.dialog.enabled);await f.dialog.config.primary_action(f.dialog.values_for_submit());
  assert.equal(f.calls.length,1);assert.match(f.errors[0],/Wait/);resolve({message:{lines:f.lines}});await loading;
 });
 await check('failed lookup clears stale rows and cannot create an order plan',async()=>{
  const f=fixture();f.dialog.fields_dict.items.df.data=f.lines;
  f.responses.push(async()=>{throw new Error('Wrong Company');});await f.dialog.change('sales_order','WRONG');
  assert.deepEqual(f.dialog.fields_dict.items.df.data,[]);assert(!f.dialog.enabled);
  await f.dialog.config.primary_action(f.dialog.values_for_submit());assert.equal(f.calls.length,1);
 });
 await check('changing Customer Site reloads and revalidates the order',async()=>{
  const f=fixture();f.responses.push(async()=>({message:{lines:f.lines}}));await f.dialog.change('sales_order','SO');
  f.responses.push(async()=>{throw new Error('Wrong Customer');});await f.dialog.change('customer_site','OTHER');
  assert.equal(f.calls.at(-1).args.customer_site,'OTHER');assert.deepEqual(f.dialog.fields_dict.items.df.data,[]);
 });
 await check('removing Sales Order permits manual quantities without retaining old rows',async()=>{
  const f=fixture();f.responses.push(async()=>({message:{lines:f.lines}}));await f.dialog.change('sales_order','SO');
  await f.dialog.change('sales_order','');assert.deepEqual(f.dialog.fields_dict.items.df.data,[]);assert(f.dialog.enabled);
  f.dialog.fields_dict.items.df.data=[{item_code:'MANUAL',requested_qty:3}];await f.dialog.config.primary_action(f.dialog.values_for_submit());
  assert.equal(JSON.parse(f.calls.at(-1).args.lines)[0].item_code,'MANUAL');
 });
 await check('invalid manual rows are rejected before create RPC',async()=>{
  const f=fixture();f.dialog.fields_dict.items.df.data=[{item_code:'ITEM',requested_qty:0}];
  await f.dialog.config.primary_action(f.dialog.values_for_submit());assert.equal(f.calls.length,0);assert.match(f.errors[0],/positive/);
 });
 await check('cancel restores scanner focus and ignores late preview',async()=>{
  const f=fixture();let resolve;f.responses.push(()=>new Promise(r=>{resolve=r;}));const loading=f.dialog.change('sales_order','SO');
  f.dialog.hide();resolve({message:{lines:f.lines}});await loading;
  assert.equal(f.focus(),1);assert.deepEqual(f.dialog.fields_dict.items.df.data,[]);
 });
 console.log(`${count} Dispatch quantity UI checks passed`);
})().catch(e=>{console.error(e);process.exitCode=1;});
