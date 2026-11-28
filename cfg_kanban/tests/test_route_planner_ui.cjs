const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const ui = require('../public/js/route_planner.js');
const flush = () => new Promise(resolve => setImmediate(resolve));
function harness(t) {
  const calls = [], routes = [], reloads = [];
  const run = { name: 'RUN1', status: 'Ready', source_revision: 2, attempt_count: 1, original: [
    { stop_key: 'STOP1', site_name: 'First' }, { stop_key: 'STOP2', site_name: 'Second' }],
    proposed: [{ stop_key: 'STOP2', site_name: 'Second', start_time: '2026-11-22T08:10:00+08:00' },
      { stop_key: 'STOP1', site_name: 'First', start_time: '2026-11-22T08:30:00+08:00' }] };
  const data = { ready: true, errors: [], warnings: ['Mock ten-minute legs'], settings: 'SETTINGS', total_load_grams: 9000, runs: [run] };
  const wrapper = { value: '', handlers: {}, html(value) { this.value = value; return this; }, off() { this.handlers = {}; return this; },
    on(event, _selector, callback) { this.handlers[event] = callback; return this; } };
  const frm = { doc: { name: 'TRIP', company: 'A', modified: '2026-11-22 07:00:00' }, perm: [{ write: 1 }],
    fields_dict: { planner_panel: { $wrapper: wrapper } }, fresh: false, dirty: false,
    is_new() { return this.fresh; }, is_dirty() { return this.dirty; }, async reload_doc() { reloads.push('reload'); } };
  global.__ = value => value;
  global.frappe = { user_roles: ['Stock Manager'], async call(request) {
    calls.push(request);
    if (request.method.endsWith('get_planning_panel')) return { message: data };
    if (request.method.endsWith('decide_mock_proposal')) return { message: { accepted: request.args.decision === 'Accept', run } };
    return { message: run };
  }, set_route(...args) { routes.push(args); }, new_doc(...args) { routes.push(args); } };
  let api;
  return { calls, data, run, wrapper, frm, reloads, routes, mount() { api = ui.mount(frm); t.after(() => api.destroy()); return api; } };
}
test('the planner is inline in a normal form, names mock estimates and escapes all source text', async t => {
  const h = harness(t); h.run.original[0].site_name = '<img src=x onerror=boom()>'; h.mount(); await flush();
  assert.match(h.wrapper.value, /Mock Route Planner/); assert.match(h.wrapper.value, /no savings are claimed/i);
  assert.match(h.wrapper.value, /&lt;img/); assert.doesNotMatch(h.wrapper.value, /<img/);
  assert.match(h.wrapper.value, /2026-11-22 08:10:00 MYT/); assert.match(h.wrapper.value, /data-planner-reason/);
  assert.equal(h.calls.length, 1);
});
test('unsaved, dirty, read-only and other-role forms never request or accept a proposal', async t => {
  for (const kind of ['new', 'dirty', 'readonly', 'role']) {
    const h = harness(t);
    if (kind === 'new') h.frm.fresh = true;
    if (kind === 'dirty') h.frm.dirty = true;
    if (kind === 'readonly') h.frm.perm = [{ read: 1 }];
    if (kind === 'role') frappe.user_roles = ['Stock User'];
    const api = h.mount(); await api.act('request'); await api.act('accept');
    assert.equal(h.calls.length, 0, kind); assert.match(h.wrapper.value, /Save this Trip/);
  }
});
test('request uses the saved Trip revision and duplicate clicks share one pending request', async t => {
  const h = harness(t), api = h.mount(); await flush(); let finish;
  const normal = frappe.call;
  frappe.call = args => args.method.endsWith('request_mock_proposal') ? new Promise(resolve => { h.calls.push(args); finish = resolve; }) : normal(args);
  const pending = api.act('request'); await api.act('request');
  assert.equal(h.calls.filter(row => row.method.endsWith('request_mock_proposal')).length, 1);
  const call = h.calls.at(-1); assert.deepEqual(call.args, { trip_name: 'TRIP', expected_modified: h.frm.doc.modified });
  finish({ message: h.run }); await pending;
});
test('accept needs an explicit reason and exact Run; successful acceptance reloads normal Trip', async t => {
  const h = harness(t), api = h.mount(); await flush();
  await api.act('accept'); assert.equal(h.reloads.length, 0); assert.match(h.wrapper.value, /enter a reason/);
  api.reason('Reviewed the mock comparison'); await api.act('accept');
  const call = h.calls.find(row => row.method.endsWith('decide_mock_proposal'));
  assert.deepEqual(call.args, { run_name: 'RUN1', decision: 'Accept', reason: 'Reviewed the mock comparison' });
  assert.equal(h.reloads.length, 1);
});
test('stale proposals and readiness blockers disable acceptance', () => {
  const html = ui.render({ ready: false, errors: ['Stop 2 missing pin'], runs: [{ name: 'R', status: 'Ready', stale: true, original: [] }] }, 'R', '', false, '');
  assert.match(html, /Stop 2 missing pin/); assert.match(html, /Inputs changed/);
  assert.match(html, /data-planner-action="accept" disabled/); assert.match(html, /data-planner-action="request" disabled/);
});
test('late response after another Trip or dirty edit never replaces the active form', async t => {
  const h = harness(t); let finish;
  frappe.call = () => new Promise(resolve => { finish = resolve; });
  const api = h.mount(); h.frm.doc.name = 'OTHER'; finish({ message: h.data }); await flush();
  assert.equal(h.wrapper.value, ''); api.destroy();
});
test('a late acceptance reply never reloads over unsaved form edits', async t => {
  const h = harness(t), api = h.mount(); await flush(); let finish; const normal = frappe.call;
  frappe.call = args => args.method.endsWith('decide_mock_proposal') ? new Promise(resolve => { finish = resolve; }) : normal(args);
  api.reason('Reviewed'); const pending = api.act('accept'); h.frm.dirty = true;
  finish({ message: { accepted: true, run: h.run } }); await pending;
  assert.equal(h.reloads.length, 0); assert.match(h.wrapper.value, /Save this Trip/);
});
test('lost acceptance reply reads history rather than making another acceptance or solve', async t => {
  const h = harness(t), api = h.mount(); await flush(); const normal = frappe.call;
  frappe.call = async args => {
    if (args.method.endsWith('decide_mock_proposal')) { h.calls.push(args); h.run.status = 'Accepted'; throw new Error('Lost reply'); }
    return normal(args);
  };
  api.reason('Reviewed'); await api.act('accept');
  assert.equal(h.calls.filter(row => row.method.endsWith('decide_mock_proposal')).length, 1);
  assert.equal(h.calls.filter(row => row.method.endsWith('request_mock_proposal')).length, 0);
  assert.match(h.wrapper.value, /Accepted/); assert.match(h.wrapper.value, /Refresh history/);
});
test('retry, reject and interrupted decisions retain the same run and reason', async t => {
  const h = harness(t), api = h.mount(); await flush(); api.reason('Reviewed interruption');
  await api.act('retry'); await api.act('reject'); await api.act('interrupt');
  for (const call of h.calls.filter(row => !row.method.endsWith('get_planning_panel'))) {
    assert.equal(call.args.run_name, 'RUN1'); assert.equal(call.args.reason, 'Reviewed interruption');
  }
});
test('company setup opens the normal settings form and defaults an absent setup to the current Company', async t => {
  const h = harness(t), api = h.mount(); await flush(); await api.act('settings');
  assert.deepEqual(h.routes[0], ['Form', 'CFG Kanban Route Planner Settings', 'SETTINGS']);
  h.data.settings = null; await api.refresh(); await api.act('settings');
  assert.deepEqual(h.routes[1], ['CFG Kanban Route Planner Settings', { company: 'A' }]);
});
test('form loads a hashed planner bundle and destroys the previous component on refresh', () => {
  const source = fs.readFileSync(path.resolve(__dirname, '../cfg_kanban/doctype/cfg_kanban_delivery_trip/cfg_kanban_delivery_trip.js'), 'utf8');
  assert.match(source, /frappe.require\('cfg_route_planner.bundle.js'\)/);
  assert.match(source, /frm.__cfg_route_planner\?\.destroy\(\)/);
  assert.doesNotMatch(source, /route_planner.*Dialog/);
});
