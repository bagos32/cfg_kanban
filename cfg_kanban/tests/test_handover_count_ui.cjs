/* Actual Logistics count adapters plus the shared scanner controller. No native site. */
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const scanner=require('../public/js/delivery_action_scanner.js');
const source=fs.readFileSync(path.join(__dirname,'../cfg_kanban/page/kanban_logistics/kanban_logistics.js'),'utf8');
function section(a,b){return source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));}
function harness(){
 const calls=[],dialogs=[],store=new Map([['SESSION','TOKEN']]),state={token:'TOKEN',operator:{employee:'SUP'},can_reconcile:true,vehicle_warehouses:[{name:'LORRY-A',company:'A'},{name:'LORRY-B',company:'B'}],reconciliation:{name:'COUNT',lines:[]}};
 let result={name:'COUNT',state:'Counting',lines:[]},failure=null,version=0,options;
 class Dialog{constructor(spec){Object.assign(this,spec);this.values=Object.fromEntries(spec.fields.filter(f=>f.fieldname).map(f=>[f.fieldname,f.default??(f.fieldtype==='Table'?f.data||[]:'')]));dialogs.push(this);}get_values(){return this.fields.some(f=>f.reqd&&!this.values[f.fieldname])?null:this.values;}hide(){options.onClose();}}
 const context={state,session_key:'SESSION',last_reconciliation_key:'LAST',localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)},unique_token:()=>`EVENT-${++version}`,
  __:s=>s,render_reconciliation(){},refresh_list:async()=>{},focus_scanner(){},scanner_error(msg){throw new Error(msg);},active_route_count_action:null,
  frappe:{ui:{Dialog},route_options:{},get_route:()=>['kanban-logistics'],require:async()=>{},msgprint:msg=>{throw new Error(msg);},async call(request){calls.push(structuredClone(request));if(failure)throw failure;return {message:structuredClone(result)};}},window:{cfg_delivery_action_scanner:{fields:scanner.fields,bind(opts){options=opts;const dialog=dialogs.at(-1);const controller=scanner.createController({...opts,openedOwner:opts.owner(),render:()=>{},set:(key,v)=>dialog.values[key]=v,read:key=>dialog.values[key],values:()=>dialog.get_values(),close:()=>dialog.hide(),camera:()=>{}});return {controller,scan:v=>controller.scan(v),focus(){}};}}}};
 vm.createContext(context);vm.runInContext(section('async function count_input_dialog','\n\tasync function open_reconciliation')+'\n'+section('async function loose_count_dialog','\n\tasync function evaluate_reconciliation')+'\n'+section('async function close_reconciliation_dialog','\n\tfunction cancel_reconciliation'),context);
 return {ctx:context,state,calls,dialogs,store,setResult:v=>result=v,setFailure:v=>failure=v,get active(){return context.active_route_count_action;}};
}
test('start count uses numbered scanner warehouse input and a stable opening event',async()=>{
 const h=harness();await h.ctx.reconciliation_dialog();await h.active.scan('CFG:SELECT:1');await h.active.scan('LORRY-B');await h.active.scan('CFG:CMD:CONFIRM');
 assert.equal(h.calls[0].args.company,'B');assert.equal(h.calls[0].args.vehicle_warehouse,'LORRY-B');assert.equal(h.calls[0].args.event_token,'EVENT-1');assert.equal(h.state.reconciliation.name,'COUNT');
});
test('known Trip lorry can be prefilled but an arbitrary default cannot be selected',async()=>{
 const h=harness();h.ctx.frappe.route_options.cfg_count_default_warehouse='LORRY-A';await h.ctx.reconciliation_dialog();assert.equal(h.dialogs[0].values.warehouse,'LORRY-A');
 const b=harness();b.ctx.frappe.route_options.cfg_count_default_warehouse='FOREIGN';await b.ctx.reconciliation_dialog();assert.equal(b.dialogs[0].values.warehouse,'');await assert.rejects(b.active.scan('CFG:CMD:CONFIRM'),/required fields/);assert.equal(b.calls.length,0);
});
test('loose count table is scanner-operable through Item and quantity to server save',async()=>{
 const h=harness();await h.ctx.loose_count_dialog();await h.active.scan('CFG:SELECT:1');await h.active.scan('CFG:CMD:DELIVERY_ADD_ROW');await h.active.scan('ITEM');await h.active.scan('CFG:SELECT:3');await h.active.scan('3');await h.active.scan('CFG:CMD:CONFIRM');
 assert.equal(h.calls[0].method,'cfg_kanban.services.route_reconciliation.save_loose_counts');assert.deepEqual(JSON.parse(h.calls[0].args.counts),[{item_code:'ITEM',qty:'3'}]);
});
test('count closing notes and correction references use exact existing API fields',async()=>{
 const h=harness();h.state.reconciliation.variance_exception='EXCEPTION';h.setResult({name:'COUNT',state:'Closed'});await h.ctx.close_reconciliation_dialog();await h.active.scan('CFG:SELECT:1');await h.active.scan('Corrected and recounted');await h.active.scan('CFG:SELECT:2');await h.active.scan('Stock Entry');await h.active.scan('CFG:SELECT:3');await h.active.scan('STE-CORRECT');await h.active.scan('CFG:CMD:CONFIRM');
 assert.equal(h.calls[0].args.resolution_notes,'Corrected and recounted');assert.equal(h.calls[0].args.correction_reference,'STE-CORRECT');assert.equal(h.state.reconciliation.state,'Closed');
});
test('lost count-start response retries its original warehouse and token',async()=>{
 const h=harness();await h.ctx.reconciliation_dialog();await h.active.scan('CFG:SELECT:1');await h.active.scan('LORRY-A');h.setFailure(new Error('Lost response'));await assert.rejects(h.active.scan('CFG:CMD:CONFIRM'));const active=h.active;assert.ok(active.controller.state.pending);h.setFailure(null);await active.scan('CFG:CMD:CONFIRM');assert.deepEqual(h.calls[0].args,h.calls[1].args);
});
test('operator switch while awaiting response cannot publish the previous count',async()=>{
 const h=harness();await h.ctx.reconciliation_dialog();await h.active.scan('CFG:SELECT:1');await h.active.scan('LORRY-A');let resolve;h.ctx.frappe.call=()=>new Promise(r=>resolve=r);const pending=h.active.scan('CFG:CMD:CONFIRM');h.store.set('SESSION','OTHER');resolve({message:{name:'PRIVATE-COUNT'}});await pending;assert.equal(h.state.reconciliation.name,'COUNT');
});
test('D3 scanner command catalogue and global routes reach the same existing actions',()=>{
 const operator=fs.readFileSync(path.join(__dirname,'../api/operator.py'),'utf8'),production=fs.readFileSync(path.join(__dirname,'../cfg_kanban/page/kanban_operator/kanban_operator.js'),'utf8');
 for(const command of ['START_ROUTE_COUNT','ROUTE_COUNT_SCAN','ROUTE_COUNT_LOOSE','ROUTE_COUNT_EVALUATE','ROUTE_COUNT_CLOSE']){assert.ok(source.includes('CFG:CMD:'+command));assert.ok(operator.includes('CFG:CMD:'+command));assert.ok(production.includes('"'+command+'"'));}
 assert.match(source,/active_route_count_action\.scan\(raw\)/);assert.match(source,/active_route_count_action\.focus\(\)/);
});

test('loose count shows an editable Physical Qty within the Frappe v15 grid budget',async()=>{
 const h=harness();await h.ctx.loose_count_dialog();
 const table=h.dialogs[0].fields.find(field=>field.fieldname==='counts');
 // Native v15 Grid.setup_visible_columns starts at 1 and stops above 11:
 // only ten layout columns are available for user data fields.
 // https://github.com/frappe/frappe/blob/v15.69.2/frappe/public/js/frappe/form/grid.js
 const fields=table.fields.filter(field=>field.in_list_view&&!field.hidden);
 assert.ok(fields.reduce((n,field)=>n+field.columns,0)<=10,'Physical Qty must fit after Item and Batch');
 assert.deepEqual(Array.from(fields,field=>field.fieldname),['item_code','batch_no','qty']);
 const qty=fields.find(field=>field.fieldname==='qty');
 assert.equal(qty.fieldtype,'Float');assert.ok(!qty.read_only);assert.equal(table.in_place_edit,true);
});
test('typed quantity and exact Batch reach the existing save endpoint',async()=>{
 const h=harness();await h.ctx.loose_count_dialog();
 h.dialogs[0].values.counts=[{item_code:'ITEM',batch_no:'BATCH',qty:2.5}];
 await h.active.controller.confirm();
 assert.equal(h.calls.length,1);assert.equal(h.calls[0].method,'cfg_kanban.services.route_reconciliation.save_loose_counts');
 assert.deepEqual(JSON.parse(h.calls[0].args.counts),[{item_code:'ITEM',batch_no:'BATCH',qty:2.5}]);
 assert.equal(h.calls[0].args.reconciliation_name,'COUNT');assert.equal(h.calls[0].args.operator_session_token,'TOKEN');
});
test('reopening loose counts retains saved quantities and does not copy tagged or expected stock',async()=>{
 const h=harness();h.state.reconciliation.lines=[
  {item_code:'LOOSE',batch_no:'BATCH',loose_count_qty:4.5,tagged_count_qty:2,expected_closing_qty:10},
  {item_code:'TAGGED',loose_count_qty:0,tagged_count_qty:7,expected_closing_qty:7}];
 await h.ctx.loose_count_dialog();
 assert.deepEqual(JSON.parse(JSON.stringify(h.dialogs[0].values.counts)),[{item_code:'LOOSE',batch_no:'BATCH',qty:4.5}]);
});
test('empty loose count explains Add Row and safe Cancel submits no count',async()=>{
 const h=harness();await h.ctx.loose_count_dialog();
 const table=h.dialogs[0].fields.find(field=>field.fieldname==='counts');
 assert.match(table.description,/Add Row/);assert.match(table.description,/Physical Qty/);
 assert.notEqual(table.cannot_add_rows,true);assert.equal(h.dialogs[0].values.counts.length,0);
 await h.active.scan('CFG:CMD:CANCEL');assert.equal(h.calls.length,0);
});
