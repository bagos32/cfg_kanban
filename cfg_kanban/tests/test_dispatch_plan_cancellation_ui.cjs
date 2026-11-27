/* Actual Logistics cancellation/reload/renderer, with offline RPC and DOM adapters. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../cfg_kanban/page/kanban_logistics/kanban_logistics.js'), 'utf8');
const open = source.slice(source.indexOf('\tasync function open_dispatch_plan(name)'), source.indexOf('\n\tfunction render_dispatch_plan(plan)'));
const render = source.slice(source.indexOf('\tfunction render_dispatch_plan(plan)'), source.indexOf('\n\tasync function run_dispatch_plan_action('));
const cancel = source.slice(source.indexOf('\tfunction cancel_dispatch_plan_dialog(plan)'), source.indexOf('\n\tfunction render_vehicle_overview('));

function fixture() {
  let dialog, html = '', focus = 0, renders = 0, scannerUpdates = 0;
  const calls = [], errors = [], handlers = new Map();
  const released = { name: 'TEST-RELEASED', state: 'Released', allocation_kind: 'Untagged ERP Stock',
    visible_code: 'ERP STOCK', item_code: 'WR1,5KG', stock_uom: 'Nos', allocated_qty: 10 };
  const skipped = { name: 'TEST-STOP', state: 'Skipped', site_name: 'Sin Yong' };
  let plan = { name: 'DPL-TEST-CANCEL', state: 'Approved', plan_type: 'Open Route Stock',
    fulfilment_mode: 'Vehicle Delivery', business_label: 'Shared Open Route Stock', company: 'TEST COMPANY',
    source_warehouse: 'TEST SOURCE', office_delivery_trip: 'KTRIP-TEST', dispatch_profile: 'TEST PROFILE',
    tag_policy: 'Untagged', profile_revision: 1, stock_rotation_policy: 'FEFO',
    lines: [{ name: 'TEST-LINE', item_code: 'WR1,5KG', requested_qty: 10, stock_uom: 'Nos', reserved_qty: 0 }],
    allocations: [released], actual_stop_count: 0, completed_stop_count: 0, can_cancel: true,
    route_delivery: { stops: [skipped], stop_sequence_policy: 'Flexible Order' } };
  const state = { token: 'TEST-SESSION', scan_mode: 'lookup', dispatch_plan_line: null };
  class Dialog {
    constructor(config) { this.config = config; dialog = this; this.hidden = false; }
    show() {}
    hide() { this.hidden = true; this.onhide?.(); }
  }
  const frappe = { utils: { escape_html: value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;') },
    ui: { Dialog }, async call(request) {
      calls.push(structuredClone(request));
      if (request.method.endsWith('cancel_dispatch_plan')) {
        plan = { ...plan, state: 'Cancelled', can_cancel: false,
          lines: plan.lines.map(row => ({ ...row, line_state: 'Cancelled' })) };
        delete plan.route_delivery;
      }
      return { message: structuredClone(plan) };
    } };
  const lookup = {
    html(value) { html = value; handlers.clear(); },
    find(selector) {
      return { on(event, callback) {
        const className = selector.slice(1);
        if (html.includes(` ${className}"`) || html.includes(` ${className} `)) handlers.set(selector, callback);
      } };
    },
  };
  const api = new Function('frappe', '__', 'state', '$lookup', 'unique_token', 'focus_scanner',
    'update_scanner_state', 'scanner_error', 'server_error_message', 'format_number', 'didRender',
    `${open}\n${render}\n${cancel}\nfunction render_lookup(){didRender();render_dispatch_plan(state.lookup.dispatch_plan);}
     return {open:open_dispatch_plan,cancel:cancel_dispatch_plan_dialog};`)(
    frappe, value => value, state, lookup, () => 'TEST-EVENT', () => { focus++; },
    () => { scannerUpdates++; }, value => errors.push(value), error => error.message,
    value => String(value), () => { renders++; });
  return { api, state, calls, errors, released, skipped, handlers,
    dialog: () => dialog, html: () => html, focus: () => focus,
    renders: () => renders, scannerUpdates: () => scannerUpdates };
}

test('Cancel Plan replaces the Approved view with Cancelled and retains Released audit', async () => {
  const f = fixture(); await f.api.open('DPL-TEST-CANCEL');
  assert.match(f.html(), /Shared Open Route Stock · Approved/);
  assert.match(f.html(), /Sin Yong.*Skipped/);
  assert(f.handlers.has('.cancel-dispatch-plan'));
  f.handlers.get('.cancel-dispatch-plan')();
  assert.equal(f.dialog().config.fields.find(row => row.fieldname === 'reason').reqd, 1);
  await f.dialog().config.primary_action({ reason: 'Test unused shared pool cancelled' });
  assert.equal(f.calls.at(-1).method, 'cfg_kanban.services.dispatch_planning.cancel_dispatch_plan');
  assert.deepEqual(f.calls.at(-1).args, { dispatch_plan: 'DPL-TEST-CANCEL', reason: 'Test unused shared pool cancelled',
    event_token: 'TEST-EVENT', operator_session_token: 'TEST-SESSION' });
  assert.equal(f.state.lookup.dispatch_plan.state, 'Cancelled');
  assert.match(f.html(), /Shared Open Route Stock · Cancelled/);
  assert.match(f.html(), /Reservation Audit/); assert.match(f.html(), /Released/);
  assert.doesNotMatch(f.html(), /Open Route Customer Stops|Start \/ Resume Route Visit|Plan Customer Stop/);
  assert(!f.handlers.has('.cancel-dispatch-plan')); assert(f.dialog().hidden);
  assert.equal(f.state.scan_mode, 'lookup'); assert.equal(f.state.dispatch_plan_line, null);
  assert(f.scannerUpdates() > 0); assert(f.focus() > 0); assert.deepEqual(f.errors, []);
});

test('Opening the same Plan again renders Cancelled without active route controls', async () => {
  const f = fixture(); await f.api.open('DPL-TEST-CANCEL'); f.api.cancel(f.state.lookup.dispatch_plan);
  await f.dialog().config.primary_action({ reason: 'Test unused shared pool cancelled' });
  f.state.lookup = null;
  await f.api.open('DPL-TEST-CANCEL');
  assert.equal(f.calls.at(-1).method, 'cfg_kanban.services.dispatch_planning.get_dispatch_plan');
  assert.equal(f.state.lookup.dispatch_plan.state, 'Cancelled');
  assert.match(f.html(), /Cancelled/); assert.match(f.html(), /WR1,5KG/); assert.match(f.html(), /Released/);
  assert.doesNotMatch(f.html(), /Open Route Customer Stops|cancel-dispatch-plan|start-open-route/);
  assert.equal(f.skipped.state, 'Skipped'); assert.equal(f.released.state, 'Released');
  assert.deepEqual(f.errors, []); assert.equal(f.renders(), 3);
});
