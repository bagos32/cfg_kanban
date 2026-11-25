/* Actual Desk helpers and form handlers, with offline Frappe/RPC doubles. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const ui = require('../public/js/office_delivery_trip.js');
const formPath = path.join(root, 'cfg_kanban/doctype/cfg_kanban_delivery_trip/cfg_kanban_delivery_trip.js');
const templatePath = path.join(root, 'cfg_kanban/doctype/cfg_kanban_route_template/cfg_kanban_route_template.js');
function harness() {
  const handlers = {}, calls = [], headlines = [], queries = {}, buttons = {};
  const wrapper = () => ({ text: '', html(value) { this.text = value; return this; }, off() { return this; }, on(_event, _selector, callback) { this.callback = callback; return this; } });
  const fields = { order_inbox: { $wrapper: wrapper() }, loading_live: { $wrapper: wrapper() }, planning_help: { $wrapper: wrapper() } };
  for (const field of ['stops', 'dispatch_plans']) fields[field] = { grid: { controls: {}, get_field(name) { return this.controls[name] ||= {}; } } };
  const frm = { doc: { name: 'TRIP', company: 'A', route_template: 'NORTH', state: 'Draft', stops: [
    { stop_key: 'STOP_KEY_1', customer: 'C1', customer_scan_point: 'SITE1', customer_address: 'ADDR1', site_name: 'Shop', stop_purpose: 'Delivery' },
    { stop_key: 'STOP_KEY_2', customer: 'C2', customer_scan_point: 'SITE2', stop_purpose: 'Visit Only' },
  ], orders: [], dispatch_plans: [] }, fields_dict: fields, perm: [{ write: 1 }],
    newRecord: false, changed: false, is_new() { return this.newRecord; }, is_dirty() { return this.changed; },
    add_child(field) { const row = {}; this.doc[field].push(row); return row; }, dirty() { this.changed = true; },
    clear_table(field) { this.doc[field] = []; }, refresh_field() {}, dashboard: { set_headline_alert(message) { headlines.push(message); } },
    async set_value(field, value) { this.doc[field] = value; this.changed = true; }, async save() { this.changed = false; },
    set_query(field, childOrQuery, callback) { queries[field] = callback || childOrQuery; },
    add_custom_button(label, callback) { buttons[label] = callback; },
  };
  const source = { sales_order: 'SO1', sales_order_item: 'SO-ROW1', customer: 'C1', customer_name: 'Customer', customer_po: 'PO1',
    customer_address: 'ADDR1', item_code: 'BAG', item_name: 'Bag', stock_uom: 'Nos', available_qty: 5, unassigned_qty: 5,
    assigned_elsewhere: 0, assigned_here: 0, ordered_qty: 5, delivered_qty: 0, status: 'To Deliver', assignable: 1 };
  const response = { rows: [source], page_length: 30, has_more: false };
  global.__ = message => message;
  global.locals = { STOP: { ROW: { customer_scan_point: 'SITE1' } } };
  global.window = { cfg_office_delivery_trip: ui, cfg_trip_continuation:{mount:()=>({hide(){},open:async()=>calls.push({follow_on:frm.doc.name})})} };
  global.frappe = { utils: { escape_html: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'), get_random: () => '0123456789abcdefghij' },
    async call(args) { calls.push(args); return { message: response }; }, async require() {},
    ui: { form: { on(doctype, callbacks) { handlers[doctype] = callbacks; } } },
    model: { can_create: () => true, async set_value(cdt, cdn, field, value) { locals[cdt][cdn][field] = value; } },
    db: { async get_value() { return { message: { customer: 'C1', customer_address: 'ADDR1', site_name: 'Shop' } }; } },
    new_doc(...args) { calls.push({ new_doc: args }); }, set_route(...args) { calls.push({ route: args }); },
  };
  return { frm, source, response, handlers, calls, queries, buttons, headlines };
}
test('inbox assignment updates exact SO row and is saved explicitly', () => {
  const { frm, source } = harness();
  const row = ui.assign(frm, source, 3, 'STOP_KEY_1');
  ui.assign(frm, source, 4, 'STOP_KEY_1');
  assert.equal(frm.doc.orders.length, 1); assert.equal(row.planned_qty, 4);
  assert.equal(row.sales_order_item, 'SO-ROW1'); assert.equal(row.customer_po, 'PO1');
  assert.equal(row.stock_uom, 'Nos'); assert.equal(frm.changed, true);
});
test('assignment rejects wrong stop, overcapacity, draft and closed planning', () => {
  const { frm, source } = harness();
  for (const qty of [0, -1, Infinity, NaN, 6]) assert.throws(() => ui.assign(frm, source, qty, 'STOP_KEY_1'));
  assert.throws(() => ui.assign(frm, source, 2, 'STOP_KEY_2'));
  source.assignable = 0; assert.throws(() => ui.assign(frm, source, 2, 'STOP_KEY_1'));
  source.assignable = 1; frm.doc.state = 'Closed'; assert.throws(() => ui.assign(frm, source, 2, 'STOP_KEY_1'));
  assert.equal(frm.doc.orders.length, 0);
});
test('multiple matching sites remain an explicit stop choice; visit-only is omitted', async () => {
  const { frm, source } = harness();
  frm.doc.stops.push({ ...frm.doc.stops[0], stop_key: 'STOP_KEY_3' });
  assert.equal(ui.stopOptions(frm, source).length, 2);
  await ui.inbox(frm, 'order_inbox', true);
  const html = frm.fields_dict.order_inbox.$wrapper.text;
  assert.ok(html.includes('STOP_KEY_1')); assert.ok(html.includes('STOP_KEY_3'));
  assert.ok(!html.includes('STOP_KEY_2')); assert.ok(!html.includes(' selected'));
});
test('draft inbox row has disabled Assign and all source text is escaped', async () => {
  const { frm, source, calls } = harness(); source.assignable = 0; source.customer_name = '<img src=x onerror=alert(1)>'; source.customer_po = '<script>bad</script>';
  await ui.inbox(frm, 'order_inbox', true);
  const html = frm.fields_dict.order_inbox.$wrapper.text;
  assert.match(html, /data-action="assign" disabled/); assert.ok(!html.includes('<img'));
  assert.ok(html.includes('&lt;script&gt;')); assert.equal(calls[0].args.trip_name, 'TRIP');
  assert.equal(calls[0].args.company, 'A'); assert.equal(calls[0].args.route_template, 'NORTH');
});
test('late inbox response cannot overwrite changed Company or route', async () => {
  const { frm, response } = harness(); let finish;
  frappe.call = () => new Promise(resolve => { finish = resolve; });
  const pending = ui.inbox(frm, 'order_inbox', true); frm.doc.company = 'B'; finish({ message: response }); await pending;
  assert.equal(frm.fields_dict.order_inbox.$wrapper.text, '');
});
test('template loading populates full form, template revision and independent stop identities', async () => {
  const { frm } = harness(); frm.newRecord = true;
  frappe.call = async args => ({ message: args.method.endsWith('get_route_template') ? { company: 'A', region: 'North', direction: 'Coast', sequence_policy: 'Planned Order', auto_generate_dispatch: 1, dispatch_profile: 'KNOWN', open_route_profile: 'OPEN', template_revision: 2, template_snapshot_json: '{"revision":2}', stops: [{ stop_key: 'NEW_KEY_1', customer: 'C1', stop_purpose: 'Visit Only' }] } : { rows: [] } });
  await ui.loadTemplate(frm);
  assert.equal(frm.doc.auto_generate_dispatch, 1); assert.equal(frm.doc.dispatch_profile, 'KNOWN'); assert.equal(frm.doc.open_route_profile, 'OPEN');
  assert.equal(frm.doc.template_revision, 2); assert.equal(frm.doc.stops.length, 1);
  assert.equal(frm.doc.stops[0].stop_key, 'NEW_KEY_1'); assert.equal(frm.doc.direction, 'Coast'); assert.equal(frm.changed, true);
});
test('template replacement never erases existing order/Plan assignments', async () => {
  const { frm, source, calls } = harness(); ui.assign(frm, source, 2, 'STOP_KEY_1');
  await ui.loadTemplate(frm); assert.equal(calls.length, 0); assert.equal(frm.doc.stops.length, 2);
});
test('template response is discarded if orders were added during the request', async () => {
  const { frm, source } = harness(); let finish;
  frappe.call = () => new Promise(resolve => { finish = resolve; });
  const pending = ui.loadTemplate(frm); ui.assign(frm, source, 2, 'STOP_KEY_1');
  finish({ message: { stops: [] } }); await pending;
  assert.equal(frm.doc.stops.length, 2); assert.equal(frm.doc.orders.length, 1);
});
test('reordering changes sequence numbers while preserving exact stop identities', () => {
  const { frm, source } = harness(); const order = ui.assign(frm, source, 2, 'STOP_KEY_1');
  frm.doc.dispatch_plans.push({ stop_key: 'STOP_KEY_1', stop_sequence: 1 });
  frm.doc.stops.reverse(); ui.renumber(frm);
  assert.equal(order.stop_key, 'STOP_KEY_1'); assert.equal(order.stop_sequence, 2);
  assert.equal(frm.doc.dispatch_plans[0].stop_sequence, 2);
});
test('late Customer Site lookup never overwrites a newly selected Site', async () => {
  const { frm } = harness(); let finish;
  frappe.db.get_value = () => new Promise(resolve => { finish = resolve; });
  const pending = ui.site(frm, 'STOP', 'ROW'); locals.STOP.ROW.customer_scan_point = 'SITE2';
  finish({ message: { customer: 'OLD-CUSTOMER' } }); await pending;
  assert.equal(locals.STOP.ROW.customer, undefined);
});
test('loading preview requires saved clean trip and shows mixed physical sources', async () => {
  const { frm, calls, response } = harness(); frm.changed = true; await ui.loading(frm); assert.equal(calls.length, 0);
  frm.changed = false; response.refreshed_on = '2026-11-21'; response.rows = [{ loading_sequence: 1, delivery_sequence: 3, customer: 'C1', item_code: 'BAG', qty: 2, stock_uom: 'Nos', allocation_kind: 'Untagged ERP Stock', source_state: 'Reserved' }];
  await ui.loading(frm); assert.ok(calls[0].method.endsWith('get_loading_sequence'));
  assert.match(frm.fields_dict.loading_live.$wrapper.text, /Untagged ERP Stock/); assert.equal(frm.changed, false);
});
test('normal form keeps Company filters and restores state after failed status save', async () => {
  const { frm, handlers, queries, buttons } = harness(); vm.runInThisContext(fs.readFileSync(formPath, 'utf8'));
  const controller = handlers['CFG Kanban Delivery Trip']; await controller.setup(frm); await controller.refresh(frm);
  assert.equal(queries.employee().filters.status, 'Active');
  assert.equal(queries.route_template().filters.company, 'A'); assert.equal(queries.vehicle_warehouse().filters.cfg_is_vehicle_warehouse, 1);
  await buttons['Close Planning'](); assert.equal(frm.doc.state, 'Draft');
  frm.doc.closure_reason = 'Wrong trip'; frm.save = async () => { throw new Error('Unsettled Plan'); };
  await buttons['Close Planning'](); assert.equal(frm.doc.state, 'Draft');
  frm.save = async () => {}; await buttons['Mark Planned'](); assert.equal(frm.doc.state, 'Planned');
});
test('office driver selection fetches its name and retains the Employee ID',async()=>{
 const {frm,handlers}=harness();vm.runInThisContext(fs.readFileSync(formPath,'utf8'));
 frappe.db.get_value=async()=>({message:{employee_name:'Ali'}});frm.doc.driver='EMP-1';
 await handlers['CFG Kanban Delivery Trip'].driver(frm);assert.equal(frm.doc.driver_display,'Ali (EMP-1)');
  let finish;frappe.db.get_value=()=>new Promise(resolve=>finish=resolve);const waiting=handlers['CFG Kanban Delivery Trip'].driver(frm);await Promise.resolve();
 frm.doc.driver='EMP-2';finish({message:{employee_name:'OLD'}});await waiting;assert.notEqual(frm.doc.driver_display,'OLD (EMP-1)');
});
test('loading a route template copies GPS policy into the normal Trip form',async()=>{
 const {frm,response}=harness();response.company='A';response.stops=[];response.gps_auto_start=1;response.gps_publish_interval_seconds=120;
 await ui.loadTemplate(frm);assert.equal(frm.doc.gps_auto_start,1);assert.equal(frm.doc.gps_publish_interval_seconds,120);
});
test('legacy departure lorry sync uses the saved Trip and reloads without editing its itinerary', async () => {
  const { frm, handlers, calls, buttons }=harness();let reloads=0;const fields=[];
  frm.doc.driver_route_state='In Progress';frm.doc.driver_route_snapshot_json='{"vehicle":"LORRY"}';frm.doc.modified='2026-11-23 12:00:00';
  frm.set_df_property=(...args)=>fields.push(args);frm.reload_doc=async()=>{reloads++;frm.doc.vehicle_warehouse='LORRY';};
  vm.runInThisContext(fs.readFileSync(formPath,'utf8'));await handlers['CFG Kanban Delivery Trip'].refresh(frm);
  assert(fields.some(row=>row[0]==='vehicle_warehouse'&&row[1]==='read_only'&&row[2]));
  await buttons['Sync Lorry Assignment']();const request=calls.find(row=>row.method?.endsWith('sync_trip_lorry'));
  assert.deepEqual(request.args,{trip_name:'TRIP',expected_modified:'2026-11-23 12:00:00'});
  assert.equal(reloads,1);assert.equal(frm.changed,false);assert.equal(frm.doc.vehicle_warehouse,'LORRY');
});
test('lorry sync rejects dirty form and releases busy guard after server rejection', async () => {
  const { frm, handlers, calls, buttons, headlines }=harness();frm.doc.driver_route_state='In Progress';frm.doc.driver_route_snapshot_json='{}';
  vm.runInThisContext(fs.readFileSync(formPath,'utf8'));await handlers['CFG Kanban Delivery Trip'].refresh(frm);
  frm.changed=true;await buttons['Sync Lorry Assignment']();assert(headlines.at(-1).includes('Reload'));
  assert(!calls.some(row=>row.method?.endsWith('sync_trip_lorry')));frm.changed=false;
  const original=frappe.call;frappe.call=async args=>{if(args.method.endsWith('sync_trip_lorry'))throw Error('Trip changed');return original(args);};
  await assert.rejects(buttons['Sync Lorry Assignment'],/Trip changed/);assert.equal(frm.__cfg_lorry_sync_busy,false);
});
test('unstarted or already-bound Trips do not show legacy lorry sync', async () => {
  for(const state of ['Not Started','In Progress']){
    const { frm, handlers, buttons }=harness();frm.doc.driver_route_state=state;frm.doc.driver_route_snapshot_json='{}';
    if(state==='In Progress')frm.doc.vehicle_warehouse='LORRY';
    vm.runInThisContext(fs.readFileSync(formPath,'utf8'));await handlers['CFG Kanban Delivery Trip'].refresh(frm);
    assert.equal(buttons['Sync Lorry Assignment'],undefined);
  }
});
test('template and Sales Order open native Desk pages and retain demand actions', async () => {
  const { frm, handlers, calls, buttons, queries } = harness();
  vm.runInThisContext(fs.readFileSync(templatePath, 'utf8')); await handlers['CFG Kanban Route Template'].refresh(frm);
  buttons['Open Delivery Trips'](); assert.equal(calls.at(-1).route[0], 'List');
  vm.runInThisContext(fs.readFileSync(path.join(root, 'public/js/sales_order.js'), 'utf8'));
  frm.fields_dict.cfg_delivery_route = {}; frm.doc.docstatus = 1; frm.doc.cfg_delivery_route = 'NORTH'; frm.doc.customer = 'C1';
  handlers['Sales Order'].setup(frm); handlers['Sales Order'].refresh(frm);
  assert.ok(buttons['Evaluate Kanban Demand']); buttons['Open Route Inbox']();
  assert.deepEqual(calls.at(-1).route, ['Form', 'CFG Kanban Route Template', 'NORTH']);
  assert.ok(queries.cfg_delivery_route().filters.some(row => row[1] === 'customer' && row[3] === 'C1'));
});

test('inactive routes and terminal trips retain history without an active-inbox RPC', async () => {
  const { frm, calls } = harness(); frm.doc.active = 0;
  await ui.inbox(frm, 'order_inbox'); assert.equal(calls.length, 0);
  frm.doc.state = 'Closed'; await ui.inbox(frm, 'order_inbox', true);
  assert.equal(calls.length, 0); assert.match(frm.fields_dict.order_inbox.$wrapper.text, /historical/);
});

test('generated dispatch is a saved-form action with exact stale-write timestamp and duplicate guard', async () => {
  const {frm,handlers,buttons,calls,queries}=harness(); frm.doc.modified='2026-11-21 12:00'; let reloaded=0,finish;
  frm.reload_doc=async()=>{reloaded++;};
  vm.runInThisContext(fs.readFileSync(formPath,'utf8'));const form=handlers['CFG Kanban Delivery Trip'];await form.setup(frm);await form.refresh(frm);
  assert.equal(queries.dispatch_profile().filters.plan_type,'Customer Order');assert.equal(queries.open_route_profile().filters.plan_type,'Open Route Stock');
  calls.length=0;frm.changed=true;await buttons['Generate / Refresh Dispatch']();assert.equal(calls.length,0);
  frm.changed=false;frappe.call=args=>{calls.push(args);return new Promise(resolve=>{finish=resolve;});};
  const first=buttons['Generate / Refresh Dispatch']();await buttons['Generate / Refresh Dispatch']();assert.equal(calls.length,1);
  assert.deepEqual(calls[0].args,{trip_name:'TRIP',expected_modified:'2026-11-21 12:00'});finish({message:{}});await first;
  assert.equal(reloaded,1);assert.equal(frm.__cfg_dispatch_busy,false);
});

test('office assistant presets become read only after driver departure',async()=>{
 const {frm,handlers}=harness();const properties={};frm.set_df_property=(name,key,value)=>{properties[name+':'+key]=value;};
 vm.runInThisContext(fs.readFileSync(formPath,'utf8'));const form=handlers['CFG Kanban Delivery Trip'];await form.setup(frm);await form.refresh(frm);
 assert.equal(properties['assistant_drivers:read_only'],false);frm.doc.driver_route_state='In Progress';await form.refresh(frm);
 assert.equal(properties['assistant_drivers:read_only'],true);
});

// The detailed mounted editor is exercised by the standalone browser fixture.
test('follow-on setup opens on the saved native Trip form and keeps existing load generation hidden',async()=>{
 const {frm,handlers,buttons,calls}=harness();frm.doc.follow_on_of='ORIGINAL';
 vm.runInThisContext(fs.readFileSync(formPath,'utf8'));await handlers['CFG Kanban Delivery Trip'].refresh(frm);
 assert.equal(buttons['Generate / Refresh Dispatch'],undefined);await buttons['Plan Follow-on Trip']();assert.deepEqual(calls.at(-1),{follow_on:'TRIP'});
});
