const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const ui=require('../public/js/field_ui.js');
test('Manifest loading stays pending until the server confirms that exact source',()=>{
 const manifest={state:'Draft',dispatch_plan_loading:true};
 const row={line_kind:'Tagged Stock',visible_code:'1234',scanned_on:'reservation-time',loading_confirmed:0};
 assert.equal(ui.manifestStatus(row,manifest).color,'orange');row.loading_confirmed=1;
 assert.equal(ui.manifestStatus(row,manifest).color,'green');
 row.loading_confirmed=0;assert.equal(ui.manifestStatus(row,manifest).color,'orange');
});
test('receipt uses its own scan evidence rather than a previous loading scan',()=>{
 const manifest={state:'Awaiting Receipt',dispatch_plan_loading:true},row={line_kind:'Tagged Stock',loading_confirmed:1};
 assert.equal(ui.manifestStatus(row,manifest).color,'orange');row.receipt_scanned=1;
 assert.equal(ui.manifestStatus(row,manifest).color,'green');
});
test('normal Manifest registration and loose loading confirmation stay distinct',()=>{
 const row={line_kind:'Tagged Stock'};assert.equal(ui.manifestStatus(row,{state:'Draft'}).color,'orange');
 row.scan_event_key='accepted-tag';assert.match(ui.manifestStatus(row,{state:'Draft'}).label,/registered/);
 const loose={line_kind:'ERP Stock without Physical Tag',loading_confirmed:0};
 assert.equal(ui.manifestStatus(loose,{state:'Draft',dispatch_recovery:true}).color,'orange');loose.loading_confirmed=1;
 assert.equal(ui.manifestStatus(loose,{state:'Draft',dispatch_recovery:true}).color,'green');
});
test('delivered or completed review alone is not shown as settled',()=>{
 assert.equal(ui.planStatus({state:'Loaded',fulfilment_status:'Completed'}).color,'orange');
 assert.equal(ui.planStatus({state:'Loaded',review_state:'Completed'}).color,'orange');
 assert.equal(ui.planStatus({state:'Reconciled',review_state:'Completed'}).color,'green');
 assert.equal(ui.planStatus({state:'Cancelled'}).color,'gray');assert.equal(ui.planStatus({state:'Exception'}).color,'red');
});
test('panel switch retains Trip per ERP user and operator without storing a credential',()=>{
 const rows=new Map(),routes=[];global.frappe={session:{user:'terminal'},set_route:(...args)=>routes.push(args)};
 global.sessionStorage={getItem:key=>rows.get(key),setItem:(key,value)=>rows.set(key,value)};
 ui.navigate('logistics',{trip:'KTRIP-1',employee:'EMP-A'});ui.navigate('driver',{employee:'EMP-A'});
 assert.deepEqual(routes.at(-1),['kanban-driver-route','KTRIP-1']);ui.navigate('driver',{employee:'EMP-B'});
 assert.deepEqual(routes.at(-1),['kanban-driver-route']);assert.ok([...rows.values()].every(value=>value==='KTRIP-1'));
 assert.equal(ui.command('LOGISTICS_PANEL',{employee:'EMP-A'}),false);
 assert.equal(ui.command('CFG:CMD:LOGISTICS_PANEL',{employee:'EMP-A'}),true);
});
test('dropdown viewport correction handles both edges without moving a fitting menu',()=>{
 assert.equal(ui.menuShift({left:-80,right:160},320),92);
 assert.equal(ui.menuShift({left:200,right:440},320),-132);
 assert.equal(ui.menuShift({left:24,right:264},320),0);
});
test('both switch positions are explicit text and keyboard-operable buttons',()=>{
 const html=ui.switchHTML('logistics');assert.match(html,/data-panel="logistics"/);
 assert.match(html,/data-cfg-panel="logistics" aria-pressed="true"/);assert.match(html,/Driver Route/);
 assert.match(html,/type="button"/);assert.doesNotMatch(html,/onclick=/);
});
test('navigation commands, genealogy return and grouped operator/trip tools keep native actions',()=>{
 const root=path.resolve(__dirname,'..'),read=name=>fs.readFileSync(path.join(root,name),'utf8');
 for(const command of ['DRIVER_ROUTE','LOGISTICS_PANEL'])assert.ok(read('api/operator.py').includes('CFG:CMD:'+command));
 assert.match(read('cfg_kanban/page/material_genealogy/material_genealogy.js'),/Back to Logistics/);
 assert.match(read('cfg_kanban/page/kanban_operator/kanban_operator.js'),/refresh_console/);
 assert.match(read('cfg_kanban/page/kanban_operator/kanban_operator.js'),/Operator Tools/);
 assert.match(read('cfg_kanban/doctype/cfg_kanban_delivery_trip/cfg_kanban_delivery_trip.js'),/Trip Tools/);
});
