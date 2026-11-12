/* Offline execution of the actual receipt dialog and scanner handlers. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
async function runTests(root=path.resolve(__dirname,'../..')) {
 const panel=fs.readFileSync(path.join(root,'cfg_kanban/cfg_kanban/page/kanban_operator/kanban_operator.js'),'utf8');
 const dialogCode=panel.slice(panel.indexOf('\tfunction manufacture_receipt_dialog('),panel.indexOf('\tfunction bind_confirmation_scanner('));
 const scannerCode=panel.slice(panel.indexOf('\tasync function handle_confirmation_scanner_value('),panel.indexOf('\tfunction scanner_selection_dialog('));
 function harness() {
  const h={calls:[],focus:0};
  h.flow={cycle:'CYCLE',mode:'Skip WIP Transfer',remaining_output_qty:5,output_warehouse:'Finished',
   manufacture_posting_mode:'Create Draft for Tag / Batch Review',materials:[
    {item_code:'RAW',source_warehouse:'Store',manufacture_pending_qty:2},
    {item_code:'BAG',source_warehouse:'Store',manufacture_pending_qty:5}],
   material_run_receipt_actuals:[{item_code:'RAW',source_warehouse:'Store',stock_uom:'Kg',used_qty:3,settled_qty:3,pending_qty:0}]};
  h.respond=async()=>({message:{stock_entry:'RECEIPT'}});
  const frappe={utils:{escape_html:value=>String(value),get_random:()=>'TOKEN'},
   call:async request=>{h.calls.push(request);return h.respond(request);},show_alert:()=>{},ui:{Dialog:class {
    constructor(options){h.dialog=this;this.options=options;this.values={};this.visible=true;
     for(const field of options.fields)if(field.fieldname)this.values[field.fieldname]=field.fieldtype==='Table'?field.data:field.default;
     this.$wrapper={is:()=>this.visible};}
    get_value(key){return this.values[key];}
    set_value(key,value){this.values[key]=value;return Promise.resolve();}
    get_field(){return {set_focus:()=>h.focus++};}
    get_primary_btn(){return {trigger:()=>this.options.primary_action({...this.values})};}
    show(){}
    hide(){this.visible=false;if(this.onhide)this.onhide();}
   }}};
  h.open=new Function('frappe','__','material_confirmation_fields','restore_scanner_focus','bind_confirmation_scanner','state','load_card','window',dialogCode+'\nreturn manufacture_receipt_dialog;')(
   frappe,value=>value,()=>[],()=>h.focus++,(dialog)=>{h.dialog=dialog;},{session_token:'SESSION',context:{card:{qr_code:'CARD'}}},async()=>{}, {setTimeout:fn=>fn()});
  const scan=new Function('frappe','__','window',scannerCode+'\nreturn handle_confirmation_scanner_value;')(frappe,value=>value,{setTimeout:fn=>fn()});
  h.scan=value=>scan(h.dialog,value);return h;
 }
 const cases=[];const test=(name,fn)=>cases.push([name,fn]);
 test('unused tracked BOM residual is absent from editable confirmation',async()=>{
  const h=harness();h.open(h.flow,true);
  assert.deepEqual(h.dialog.values.materials.map(row=>row.item_code),['BAG']);
  assert(h.dialog.options.fields.some(field=>String(field.options).includes('Unused BOM balances remain in stock')));
  await h.scan('CFG:CMD:CONFIRM');assert.deepEqual(h.calls[0].args.lines,[{item_code:'BAG',source_warehouse:'Store',qty:5}]);
  assert.equal(h.calls[0].args.output_qty,5);assert.equal(h.calls[0].args.defer_submit_for_scanning,1);
 });
 test('all-tracked receipt needs no extra raw-material allocation',async()=>{
  const h=harness();h.flow.materials=h.flow.materials.slice(0,1);h.open(h.flow,true);
  assert.equal(h.dialog.values.materials.length,0);await h.scan('CFG:CMD:CONFIRM');assert.deepEqual(h.calls[0].args.lines,[]);
 });
 test('untracked material remains in the ordinary consumption table',async()=>{
  const h=harness();h.flow.material_run_receipt_actuals=[];h.open(h.flow,true);
  assert.deepEqual(h.dialog.values.materials.map(row=>row.qty),[2,5]);
 });
 test('receipt rejection retains the dialog and restores scanner focus',async()=>{
  const h=harness();h.open(h.flow,true);h.respond=async()=>{throw Error('reconcile consumption');};
  await assert.rejects(h.scan('CFG:CMD:CONFIRM'));assert.equal(h.dialog.visible,true);assert(h.focus>0);
 });
 test('Cancel leaves without preparing stock and restores focus',async()=>{
  const h=harness();h.open(h.flow,true);await h.scan('CFG:CMD:CANCEL');
  assert.equal(h.calls.length,0);assert.equal(h.dialog.visible,false);assert(h.focus>0);
 });
 test('pending confirmation cannot create a second receipt request',async()=>{
  const h=harness();h.open(h.flow,true);let finish;h.respond=()=>new Promise(resolve=>{finish=resolve;});
  const first=h.scan('CFG:CMD:CONFIRM');await h.scan('CFG:CMD:CONFIRM');assert.equal(h.calls.length,1);
  finish({message:{stock_entry:'RECEIPT'}});await first;
 });
 const passed=[];for(const[name,fn]of cases){await fn();passed.push(name);}return passed;
}
module.exports=runTests;
if(require.main===module)runTests().then(results=>console.log(`${results.length} receipt scanner checks passed`)).catch(error=>{console.error(error);process.exitCode=1;});
