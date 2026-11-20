/* Actual Service Panel rendering and dialog functions with offline DOM/RPC adapters. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const pagePath = path.join(root, 'cfg_kanban/page/kanban_tasks/kanban_tasks.js');
const source = fs.readFileSync(pagePath, 'utf8');
function extract(name) {
  const start = source.search(new RegExp(`\\t(?:async )?function ${name}\\(`));
  assert(start >= 0, name);
  const rest = source.slice(start + 1);
  const next = rest.search(/\n\t(?:async )?function /);
  return source.slice(start, next < 0 ? source.lastIndexOf('\tinstall_live_updates();') : start + 1 + next);
}
const names = ['load', 'render_task_view', 'render', 'render_task_section', 'button', 'priority_class', 'indicator',
  'task_start_message', 'task_started_for_action', 'restore_task_scanner', 'task_dialog',
  'can_open_action', 'should_open_action_after_event', 'scanner_error', 'focus_scanner', 'update_scanner_mode'];
function task(overrides = {}) {
  return { name: 'KTASK-1', task_name: 'Clean Station', status: 'Due', assigned_employee: 'OP',
    can_operate: true, can_assist: false, started_on: null, checklist: '', execution_values: [],
    checklist_evidence: [], priority: 'Normal', ...overrides };
}
function fixture(initial = task()) {
  const s = { task: initial, calls: [], alerts: [], dialogs: [], timers: [], focus: 0, media: 0, actions: [],
    state: { token: 'TOKEN', operator: { employee: 'OP', kanban_role: 'Operator', permissions: { task_verify: false } },
      tasks: [initial], interaction_epoch: 0, task_filter: null } };
  class Element {
    constructor(html = '') { this.content = html; this.children = []; this.events = {}; this.length = 1; }
    appendTo(parent) { parent.children.push(this); return this; }
    append(html) { this.children.push(new Element(html)); return this; }
    find(selector) { this.found ||= {}; return this.found[selector] ||= new Element(); }
    html(value) { this.content = value; return this; }
    empty() { this.content = ''; this.children = []; return this; }
    on(event, fn) { (this.events[event] ||= []).push(fn); return this; }
    one(event, fn) { return this.on(event, fn); }
    emit(event) { const fns = this.events[event] || []; delete this.events[event]; fns.forEach(fn => fn()); }
    trigger(event) { if (event === 'focus') s.focus++; else this.emit(event); return this; }
    select() { return this; }
    removeClass() { return this; } addClass() { return this; }
    text(value) { this.content = value; return this; }
    last() { return this; }
  }
  function $(value) {
    if (value === '.modal:visible') {
      const visible = s.message?.visible ? s.message : [...s.dialogs].reverse().find(d => d.visible)?.$wrapper;
      return visible || Object.assign(new Element(), { length: 0 });
    }
    return new Element(value);
  }
  class Dialog {
    constructor(options) { this.options = options; this.$wrapper = new Element(); this.fields_dict = {}; s.dialogs.push(this); }
    show() { this.visible = true; }
    hide() { this.visible = false; this.$wrapper.emit('hidden.bs.modal'); }
    set_secondary_action_label() {} set_secondary_action() {}
  }
  s.active = new Element(); s.ready = new Element(); s.scanner = new Element();
  const frappe = { ui: { Dialog }, utils: { escape_html: value => String(value ?? '') },
    show_alert: alert => s.alerts.push(alert), msgprint() {},
    call: async ({ method, args }) => {
      s.calls.push({ method, args });
      const name = method.split('.').at(-1);
      if (name === 'get_task_form') return { message: { task: structuredClone(s.task), fields: [], media: [] } };
      if (name === 'operator_session_status') return { message: s.state.operator };
      if (name === 'get_service_tasks_live_revision') return { message: { revision: '2' } };
      if (name === 'get_open_tasks') return { message: [structuredClone(s.task)] };
      if (s.error) {
        if (s.serverMessage) { s.message = new Element(); s.message.visible = true; }
        throw s.error;
      }
      if (name === 'start') Object.assign(s.task, { started_on: '2026-11-20 09:00:00', status: 'In Progress' });
      if (name === 'complete') s.task.status = 'Completed';
      return { message: structuredClone(s.task) };
    } };
  const context = vm.createContext({ $, frappe, __: value => value, state: s.state, session_key: 'SESSION',
    $active_root: s.active, $root: s.ready, $scanner: s.scanner,
    localStorage: { getItem: () => 'TOKEN' }, setTimeout: fn => s.timers.push(fn),
    window: { matchMedia: () => ({ matches: true }) },
    sync_session_from_storage() {}, render_identity() {}, show_login_required() {}, clear_session() {},
    task_identity: () => '', safe_rich_text: value => value, media_evidence_html: () => '',
    dynamic_fields: () => [], verification_evidence: () => [], configure_dynamic_visibility() {},
    bind_media_evidence() { s.media++; }, visible_dynamic_definitions: () => [],
    disposition_dialog() {}, progress_history_dialog() {}, scroll_to_active_work() { s.scrolled = true; },
    open_action_form: async (...args) => s.actions.push(args) });
  vm.runInContext(names.map(extract).join('\n'), context);
  s.api = context; s.flush = () => { while (s.timers.length) s.timers.shift()(); };
  s.render = () => context.render(s.state.tasks);
  const all = element => [element, ...element.children.flatMap(all)];
  s.buttons = (element = s.ready) => all(element).flatMap(e => all(e.found?.['.actions'] || new Element()))
    .filter(e => String(e.content).startsWith('<button')).map(e => ({ label: e.content.match(/>(.*?)<\/button>/)[1], click: e.events.click[0] }));
  s.open = async action => { await context.task_dialog(structuredClone(s.state.tasks[0]), action); return s.dialogs.at(-1); };
  return s;
}
const tests = [];
function test(name, run) { tests.push([name, run]); }
for (const status of ['Planned', 'Due', 'Assigned', 'Overdue']) test(`${status} without Start shows only Start execution action`, () => {
  const s = fixture(task({ status })); s.render(); const labels = s.buttons().map(b => b.label);
  assert(labels.includes('Start')); assert(!labels.includes('Complete')); assert(!labels.includes('Report Progress'));
});
for (const status of ['In Progress', 'Overdue', 'Correction Required']) test(`${status} with timestamp exposes completion and hides Start`, () => {
  const s = fixture(task({ status, started_on: '2026-11-20' })); s.render(); const labels = s.buttons(s.active).map(b => b.label);
  assert(labels.includes(status === 'Correction Required' ? 'Correct and Resubmit' : 'Complete'));
  assert(labels.includes('Report Progress')); assert(!labels.includes('Start'));
});
for (const status of ['In Progress', 'Correction Required']) test(`${status} without timestamp cannot progress or complete`, () => {
  const s = fixture(task({ status })); s.render(); assert(!s.buttons().some(b => ['Complete', 'Report Progress', 'Correct and Resubmit'].includes(b.label)));
});
test('Supervisor Cancel/Bypass remains visible before Start', () => {
  const s = fixture(); s.state.operator.permissions.task_verify = true; s.render();
  assert(s.buttons().some(b => b.label === 'Cancel / Bypass'));
});
test('Supervisor assistance exposes post-start completion without granting Start', () => {
  const s = fixture(task({ status: 'Overdue', started_on: '2026-11-20', assigned_employee: 'OTHER', can_assist: true, can_operate: false }));
  s.state.operator.kanban_role = 'Supervisor'; s.render(); const labels = s.buttons().map(b => b.label);
  assert(labels.includes('Complete')); assert(labels.includes('Report Progress')); assert(!labels.includes('Start'));
});
test('unstarted Supervisor full-control task cannot complete', () => {
  const s = fixture(); s.state.operator.kanban_role = 'Supervisor'; s.render();
  assert(!s.buttons().some(b => b.label === 'Complete'));
});
test('missing On Task Start Action Run still hides Complete', () => {
  const s = fixture(task({ status: 'In Progress', started_on: '2026-11-20', doctype_action_trigger: 'On Task Start' }));
  s.render(); assert(!s.buttons(s.active).some(b => b.label === 'Complete'));
});
test('existing informational Action Run remains openable', () => {
  const s = fixture(task({ doctype_action_run: 'RUN', can_resume_action: true })); s.render();
  assert(s.buttons().some(b => b.label === 'Open Document Form'));
  assert(!s.buttons().some(b => b.label === 'Complete'));
});
for (const action of ['Complete', 'Progress']) test(`premature ${action} restores scanner without opening evidence or calling API`, async () => {
  const s = fixture(); await s.open(action); s.flush();
  assert.equal(s.dialogs.length, 0); assert.equal(s.media, 0); assert.equal(s.calls.length, 0);
  assert(s.focus > 0); assert.equal(s.actions.length, 0);
  assert.equal(s.alerts[0].message, action === 'Complete' ? 'Start the Service Task before completing it' : 'Start the Service Task before reporting progress');
});
test('fresh server snapshot prevents stale completion dialog and evidence', async () => {
  const s = fixture(); s.state.tasks = [task({ status: 'In Progress', started_on: '2026-11-20' })];
  await s.open('Complete'); s.flush(); assert.equal(s.calls.length, 1); assert.equal(s.dialogs.length, 0); assert.equal(s.media, 0); assert(s.focus > 0);
});
for (const serverMessage of [false, true]) test(`server premature rejection restores focus after safe close (message ${serverMessage})`, async () => {
  const s = fixture(task({ status: 'In Progress', started_on: '2026-11-20' }));
  const dialog = await s.open('Complete'); s.error = { responseJSON: { _server_messages: JSON.stringify([JSON.stringify({ message: 'Start the Service Task before completing it' })]) } };
  s.serverMessage = serverMessage; await dialog.options.primary_action({}); s.flush(); assert.equal(dialog.visible, false);
  if (serverMessage) { assert.equal(s.focus, 0); s.message.visible = false; s.message.emit('hidden.bs.modal'); s.flush(); }
  assert(s.focus > 0); assert.equal(s.actions.length, 0);
  assert.equal(s.alerts.at(-1).message, 'Start the Service Task before completing it');
});
test('other validation failures keep completion dialog editable', async () => {
  const s = fixture(task({ status: 'In Progress', started_on: '2026-11-20' })); const dialog = await s.open('Complete');
  s.error = new Error('Complete all checklist items'); await assert.rejects(() => dialog.options.primary_action({}), /checklist/);
  assert.equal(dialog.visible, true); assert.equal(s.focus, 0);
});
test('successful Start refreshes into Active Work and exposes Complete', async () => {
  const s = fixture(); s.render(); await s.buttons().find(b => b.label === 'Start').click();
  await s.dialogs.at(-1).options.primary_action({}); s.flush();
  const labels = s.buttons(s.active).map(b => b.label); assert(labels.includes('Complete')); assert(labels.includes('Report Progress')); assert(!labels.includes('Start'));
  assert(s.scrolled); assert(s.calls.some(call => call.method.endsWith('get_open_tasks')));
});
test('correction dialog retains existing completion notes', async () => {
  const s = fixture(task({ status: 'Correction Required', started_on: '2026-11-20', completion_notes: 'Previous result' }));
  const d = await s.open('Complete'); assert.equal(d.options.fields.find(f => f.fieldname === 'notes').default, 'Previous result');
});
test('completion still opens its required document form at the configured event', async () => {
  const s = fixture(task({ status: 'In Progress', started_on: '2026-11-20', doctype_action_trigger: 'On Task Complete', doctype_action_run: 'RUN' }));
  const d = await s.open('Complete'); await d.options.primary_action({}); assert.equal(s.actions[0][0], 'RUN');
});
// Keep cross-context async callbacks alive; an unfinished test must fail, never silently exit.
const deadline = setTimeout(() => { console.error('Service Task UI checks timed out'); process.exitCode = 1; }, 5000);
(async () => { for (const [name, run] of tests) { await run(); console.log('ok ' + name); } console.log(`${tests.length} Service Task UI checks passed`); })()
  .catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(deadline));
