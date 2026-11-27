const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const ui=require('../public/js/delivery_product_checks.js');
const actions=require('../public/js/driver_route_actions.js');
const rows=[{name:'T',tagged:true,item_code:'A',visible_code:'1234',qty:3,stock_uom:'Nos',confirmed:false},
 {name:'L',tagged:false,item_code:'B',batch_no:'LOT',qty:2,stock_uom:'Nos',confirmed:false}];
function setup(data=rows){const sent=[];const c=ui.controller({check:{rows:data},submit:async v=>sent.push(v)});return {c,sent};}
test('one exact physical tag scan submits only its identity, including numeric preprinted codes',async()=>{
 const {c,sent}=setup();c.choose('L');await c.scan('1234');assert.deepEqual(sent,[{scan_value:'1234'}]);assert.equal(c.state.selected,null);
});
test('untagged numbered selection requires explicitly checked exact stock UOM quantity',async()=>{
 const {c,sent}=setup();await c.scan('CFG:SELECT:1');assert.equal(c.state.selected,'L');
 await assert.rejects(c.submit(),/exactly 2 Nos/);await c.scan('CFG:QTY:MATERIAL:1');await assert.rejects(c.submit(),/exactly/);
 await c.scan('CFG:QTY:MATERIAL:2');await c.scan('CFG:CMD:CONFIRM');
 assert.deepEqual(sent,[{delivery_allocation:'L',item_code:'B',qty:2}]);
});
test('manual touch selection and input use the same immutable Item and allocation as scanner',async()=>{
 const {c,sent}=setup();c.choose('L');c.quantity('2');await c.submit();assert.equal(sent[0].delivery_allocation,'L');
 for(const qty of ['NaN','Infinity','-1','0','']){c.quantity(qty);await assert.rejects(c.submit());}
 assert.throws(()=>c.choose('T'),/untagged/);
});
test('numbered paging never silently picks a different Batch and excludes confirmed rows',async()=>{
 const items=Array.from({length:12},(_,n)=>({...rows[1],name:'L'+n,batch_no:'B'+n,confirmed:n===0}));
 const {c}=setup(items);await c.scan('CFG:CMD:NEXT_MATERIALS');await c.scan('CFG:SELECT:1');assert.equal(c.state.selected,'L11');
 await assert.rejects(c.scan('CFG:SELECT:2'),/displayed/);await c.scan('CFG:CMD:PREVIOUS_MATERIALS');await c.scan('CFG:SELECT:1');assert.equal(c.state.selected,'L1');
});
test('wrong commands cannot masquerade as physical scans or bypass readiness',async()=>{
 const {c,sent}=setup();await assert.rejects(c.scan('CFG:CMD:COMPLETE_STOP'),/assigned tag/);
 await assert.rejects(c.scan('CFG:QTY:MATERIAL:2'),/Select the untagged/);assert.equal(sent.length,0);
});
test('checklist green is only the saved server confirmation and all labels are escaped',()=>{
 const html=ui.checklist({rows:[{...rows[0],item_code:'<unsafe>',confirmed:true},{...rows[1]}]});
 assert.match(html,/data-confirmed="true"/);assert.match(html,/data-confirmed="false"/);assert.match(html,/Check required/);assert.match(html,/&lt;unsafe&gt;/);assert.doesNotMatch(html,/<unsafe>/);
});
test('verification reuses durable driver request identity after unknown response',async()=>{
 const store=new Map(),sent=[];let fail=true;const env={storage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)},
 locks:{request:async(k,fn)=>fn()},owner:()=> 'DRIVER',token:()=> 'TOKEN',nonce:()=> 'FIXED',render:()=>{},
 rpc:async(method,args)=>{sent.push(structuredClone(args));if(fail){fail=false;throw new Error('Lost response');}return {status:'Recorded'};},success:async()=>{}};
 const c=actions.controller(env);c.restore('TRIP');await assert.rejects(c.mutate({revision:1,scope_hash:'HASH',stop_key:'STOP',dispatch_plan:'PLAN'},'Verify Delivery Goods',{scan_value:'1234'}));
 const reopened=actions.controller(env);reopened.restore('TRIP');await reopened.retry();assert.deepEqual(sent[0],sent[1]);assert.equal(reopened.state.pending,null);
});
test('client/server/scan catalogue/Logistics expose the same product-check action',()=>{
 const base=path.resolve(__dirname,'..');const read=f=>fs.readFileSync(path.join(base,f),'utf8');
 for(const f of ['public/js/driver_route_actions.js','services/driver_route_actions.py','services/trip_sales.py'])assert.match(read(f),/Verify Delivery Goods/);
 for(const f of ['api/operator.py','public/js/driver_route.js','cfg_kanban/page/kanban_logistics/kanban_logistics.js','cfg_kanban/page/kanban_operator/kanban_operator.js'])assert.match(read(f),/VERIFY_DELIVERY_GOODS/);
 assert.match(read('services/customer_delivery.py'),/assert_verified\(delivery\)/);
 assert.match(read('hooks.py'),/delivery_product_scans.validate_delivery_note/);
});
