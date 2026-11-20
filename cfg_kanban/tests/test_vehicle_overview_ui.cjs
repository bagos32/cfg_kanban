/* Execute lorry stock/route visibility and the Logistics branch of the real floor page. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const floor=require('../public/js/logistics_floor.js');
const app=path.resolve(__dirname,'..'),logistics=fs.readFileSync(path.join(app,'cfg_kanban/page/kanban_logistics/kanban_logistics.js'),'utf8'),floorPage=fs.readFileSync(path.join(app,'cfg_kanban/page/kanban_floor/kanban_floor.js'),'utf8');
const e=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
let count=0;async function test(name,work){await work();console.log('ok '+name);count++;}
function source(text,name){const start=text.search(new RegExp('\\t(?:async )?function '+name+'\\('));assert(start>=0,name);const next=text.slice(start+1).search(/\n\t(?:async )?function /);return next<0?text.slice(start):text.slice(start,start+1+next);}
const plan={name:'DPL',business_label:'Loaded route',state:'Loaded',source_warehouse:'SOURCE',customer:'CUSTOMER',fulfilment_status:'In Progress',quantities_by_uom:{Nos:{loaded:5},Kg:{loaded:3}},stops:[{name:'STOP',planned_sequence:1,site_name:'Shop',customer:'CUSTOMER',state:'Planned'}]};
(async()=>{
 await test('completed loading view shows current ERP quantity, tag coverage and loaded history separately',()=>{
  const run=new Function('frappe','format_number','__',source(logistics,'render_vehicle_overview')+'\nreturn render_vehicle_overview;')({utils:{escape_html:e}},value=>String(value),s=>s);
  const html=run({can_view_stock:true,stock:[{item_code:'BAG',erp_qty:2,tag_qty:2,untagged_qty:0,stock_uom:'Nos',tags:[{physical_scan_code:'BIN1',current_qty:2,stock_uom:'Nos',quality_state:'Released'}]}],assigned_plans:[plan]});
  assert(html.includes('Current Lorry Stock'));assert(html.includes('Assigned Loads and Customer Stops'));assert(html.includes('CUSTOMER'));assert(html.includes('2 Nos'));assert(html.includes('5 Nos'));assert(html.includes('3 Kg'));assert(html.includes('BIN1'));
 });
 await test('unauthorized lorry view contains no inventory table and explains required access',()=>{
  const run=new Function('frappe','format_number','__',source(logistics,'render_vehicle_overview')+'\nreturn render_vehicle_overview;')({utils:{escape_html:e}},value=>String(value),s=>s);
  const html=run({can_view_stock:false,stock:[],assigned_plans:[]});assert(!html.includes('<table'));assert(html.includes('Warehouse read permission'));
 });
 await test('logistics floor shows ready loads upcoming preparation and assigned vehicle without workstations',()=>{
  const html=floor.render({company:'B',profile:{profile_name:'Driver Floor',refresh_interval_seconds:30,queue_depth:5},vehicles:[{name:'LORRY',vehicle_reference:'TRUCK1',plans:[plan]}],preparing:[{...plan,name:'READY',state:'Ready for Vehicle'},{...plan,name:'PICK',state:'Picking'}]},e);
  for(const value of ['Ready to Load (1)','Upcoming Preparation (1)','TRUCK1','DPL','READY','PICK','Shop'])assert(html.includes(value),value);
  assert(!html.includes('draggable="true"'));assert(!html.includes('Workstation'));
 });
 await test('customer names and scanned labels are escaped in stock and floor views',()=>{
  const html=floor.render({company:'B',profile:{profile_name:'<img src=x>',queue_depth:1},preparing:[{...plan,customer:'<script>',state:'Ready for Vehicle'}]},e);
  assert(!html.includes('<script>'));assert(html.includes('&lt;script&gt;'));assert(!html.includes('<img src=x>'));
 });
 await test('floor queue depth is respected with explicit overflow count',()=>{
  const html=floor.render({company:'B',profile:{profile_name:'Floor',queue_depth:1},preparing:[{...plan,name:'FIRST',state:'Ready for Vehicle'},{...plan,name:'SECOND',state:'Ready for Vehicle'}]},e);
  assert(html.includes('FIRST'));assert(!html.includes('SECOND'));assert(html.includes('1 more'));
 });
 await test('actual floor loader routes logistics response to read-only renderer and schedules refresh',async()=>{
  const data={mode:'logistics',profile:{refresh_interval_seconds:20}},calls=[];let html;
  const run=new Function('state','frappe','window','$root','render','schedule','__',source(floorPage,'load_dashboard')+'\nreturn load_dashboard();');
  await run({profile:'LOGISTICS'},{call:async args=>{calls.push(args);return {message:data};},require:async asset=>calls.push(asset),utils:{escape_html:e}},
   {cfg_logistics_floor:{render:value=>{assert.equal(value,data);return 'LOGISTICS';}}},{html:value=>{html=value;}},()=>{throw new Error('Production render used');},seconds=>calls.push(seconds),s=>s);
  assert.equal(html,'LOGISTICS');assert.equal(calls.at(-1),20);assert(calls.some(row=>String(row).includes('logistics_floor.js')));
 });
 await test('warehouse renderer embeds persistent overview and opens its loaded Plan',()=>{
  const code=source(logistics,'render_warehouse_operations');assert(code.includes('render_vehicle_overview(context.vehicle_overview)'));assert(code.includes('.vehicle-open-plan'));assert(code.includes('open_dispatch_plan'));
 });
 await test('live refresh rereads the selected lorry and ignores stale responses',async()=>{
  const code=source(logistics,'refresh_live_work_context');
  const run=new Function('state','frappe','render_lookup','guard',code+'\nreturn refresh_live_work_context(guard);');
  const state={token:'TOKEN',lookup:{warehouse_operations:{location_card:'CARD',version:1}}};let rendered=0;
  await run(state,{call:async options=>{assert.equal(options.args.scan_value,'CARD');return {message:{warehouse_operations:{location_card:'CARD',version:2}}};}},()=>{rendered++;},()=>true);
  assert.equal(state.lookup.warehouse_operations.version,2);assert.equal(rendered,1);
  await run(state,{call:async()=>({message:{warehouse_operations:{location_card:'CARD',version:3}}})},()=>{rendered++;},()=>false);
  assert.equal(state.lookup.warehouse_operations.version,2);assert.equal(rendered,1);
  assert.equal(state.lookup.warehouse_operations.version,2);assert.equal(rendered,1);
  const stale=new Function('state','frappe','render_lookup',code+'\nreturn refresh_live_work_context(()=>false);');
  await stale(state,{call:async()=>({message:{warehouse_operations:{version:3}}})},()=>{throw new Error('Stale view rendered');});
  assert.equal(state.lookup.warehouse_operations.version,2);
 });
 await test('assigned route appears once with customer address after loading is closed',()=>{
  const run=new Function('frappe','format_number','__','view',source(logistics,'render_vehicle_overview')+'\nreturn render_vehicle_overview(view);');
  const html=run({utils:{escape_html:e}},value=>String(value),value=>value,{can_view_stock:true,stock:[],assigned_plans:[],route_sheets:[{name:'RS1',state:'Approved',scope:'Combined Lorry Trip',sequence_policy:'Planned Order',verification_policy:'Require Customer Site QR',stops:[{site_name:'Shop A',customer:'CUST',address_display:'Street A',state:'Planned',dispatch_plan:'DPL'}]}]});
  assert.equal(html.split('<strong>RS1').length-1,1);assert(html.includes('Street A'));assert(html.includes('Open Customer Route'));
 });
 console.log(`${count} lorry/floor UI checks passed`);
})().catch(error=>{console.error(error);process.exitCode=1;});
