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
const names = ['task_list_args', 'process_scanner_value', 'load_service_card', 'clear_task_filter',
  'operator_token_from_url', 'service_task_token', 'check_live_updates', 'live_refresh_safe', 'login_operator',
  'scan_service_code', 'sync_session_from_storage', 'clear_session', 'operator_session_expired', 'load', 'render_task_view', 'render', 'render_task_section', 'button', 'priority_class', 'indicator',
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
    val(value) { if (arguments.length) { this.value = value; return this; } return this.value || ''; }
    is() { return true; } closest() { return this; } get() { return null; }
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
    if (value === '#freeze:visible, .freeze-message:visible') return Object.assign(new Element(), { length: 0 });
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
  class Scanner { constructor(options) { s.camera = options; } }
  const frappe = { dom: { freeze_count: 0 }, ui: { Dialog, Scanner }, utils: { escape_html: value => String(value ?? '') },
    show_alert: alert => s.alerts.push(alert), msgprint() {},
    call: async ({ method, args }) => {
      s.calls.push({ method, args });
      const name = method.split('.').at(-1);
      if (name === 'resolve_service_card_scan') {
        if (s.locationError) throw s.locationError;
        return { message: s.resolution || { matched: false } };
      }
      if (name === 'resolve_card_scan') return { message: s.actionResolution || { matched: false } };
      if (name === 'resolve_service_scan') return { message: { task: structuredClone(s.task) } };
      if (name === 'login_operator') return { message: { session_token: 'SWITCHED', operator: s.state.operator } };
      if (name === 'get_task_form') return { message: { task: structuredClone(s.task), fields: [], media: [] } };
      if (name === 'operator_session_status') return { message: s.state.operator };
      if (name === 'get_service_tasks_live_revision') return { message: { revision: '2' } };
      if (name === 'get_open_tasks') {
        if (s.taskRequest) return s.taskRequest(args);
        if (s.listError) throw s.listError;
        return { message: structuredClone(args.scanned_task ? (s.scannedTasks || [s.task]) : args.service_card ? (s.locationTasks || [s.task]) : [s.task]) };
      }
      if (s.error) {
        if (s.serverMessage) { s.message = new Element(); s.message.visible = true; }
        throw s.error;
      }
      if (name === 'start') Object.assign(s.task, { started_on: '2026-11-20 09:00:00', status: 'In Progress' });
      if (name === 'complete') s.task.status = 'Completed';
      return { message: structuredClone(s.task) };
    } };
  s.storedToken = 'TOKEN';
  const context = vm.createContext({ $, frappe, URL, URLSearchParams, page: { main: {} }, wrapper: {}, document: { hidden: false }, __: value => value, state: s.state, session_key: 'SESSION',
    $active_root: s.active, $root: s.ready, $scanner: s.scanner,
    localStorage: { getItem: () => s.storedToken, setItem: (_key, value) => { s.storedToken = value; }, removeItem: () => { s.storedToken = null; } }, setTimeout: fn => s.timers.push(fn),
    window: { matchMedia: () => ({ matches: true }) },
    sync_session_from_storage() {}, render_identity() {}, show_login_required() {}, clear_session() {},
    find_service_task(value) { s.foundTask = value; }, open_action_card_selector(value) { s.selectedAction = value; },
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
  s.scan = async value => { s.scanner.find('.service-scan-input').val(value); await context.process_scanner_value(); s.flush(); };
  s.text = element => all(element).map(e => String(e.content)).join(' ');
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
function location(s) {
  s.resolution = { matched: true, card: { name: 'LOC-CARD', card_number: 'CLEAN-01', location: 'RINSE BAY', company: 'CFG' } };
}
const credentialCalls = s => s.calls.filter(call => call.method.endsWith('login_operator'));
test('General Service Point scan opens the location list without credential or Action resolver fallback', async () => {
  const s = fixture(); location(s); await s.scan('location-uuid');
  assert.equal(s.state.service_card.name, 'LOC-CARD');
  assert.equal(s.calls.find(call => call.method.endsWith('get_open_tasks')).args.service_card, 'LOC-CARD');
  assert.equal(credentialCalls(s).length, 0); assert(!s.calls.some(call => call.method.endsWith('resolve_card_scan')));
  assert(s.text(s.ready).includes('RINSE BAY')); assert(s.focus > 0); assert.equal(s.dialogs.length, 0); assert.equal(s.media, 0);
});
test('empty location gives an empty-work message without operator-credential fallback', async () => {
  const s = fixture(); location(s); s.locationTasks = []; await s.scan('location-uuid');
  assert(s.text(s.ready).includes('No open Service Tasks are available'));
  assert.equal(credentialCalls(s).length, 0); assert.equal(s.actions.length, 0);
});
test('Location Card before login asks for operator and rescan without attempting login', async () => {
  const s = fixture(); s.state.token = null; s.storedToken = null;
  s.resolution = { matched: true, requires_operator: true, message: 'Identify the operator first, then scan the General Service Point Location Card again' };
  await s.scan('location-uuid'); assert.equal(credentialCalls(s).length, 0);
  assert.equal(s.calls.length, 1); assert(s.alerts.at(-1).message.includes('Identify the operator first'));
  assert(!s.state.service_card); assert(s.focus > 0);
});
test('location configuration failure cannot fall through to credential login', async () => {
  const s = fixture(); s.locationError = new Error('Location Card is blocked'); await s.scan('location-uuid');
  assert.equal(credentialCalls(s).length, 0); assert.equal(s.state.token, 'TOKEN'); assert(s.focus > 0);
});
test('manual refresh retains location scope', async () => {
  const s = fixture(); location(s); await s.scan('location-uuid'); await s.api.load();
  const reads = s.calls.filter(call => call.method.endsWith('get_open_tasks'));
  assert.equal(reads.length, 2); assert(reads.every(call => call.args.service_card === 'LOC-CARD'));
});
test('live refresh retains location scope and does not move scanner focus', async () => {
  const s = fixture(); location(s); await s.scan('location-uuid'); const focus = s.focus;
  s.state.live_revision = 'old'; await s.api.check_live_updates(); s.flush();
  const reads = s.calls.filter(call => call.method.endsWith('get_open_tasks'));
  assert.equal(reads.length, 2); assert.equal(reads.at(-1).args.service_card, 'LOC-CARD'); assert.equal(s.focus, focus);
});
test('Show All clears location scope and reloads the full eligible queue', async () => {
  const s = fixture(); location(s); await s.scan('location-uuid'); await s.api.clear_task_filter(); s.flush();
  assert.equal(s.state.service_card, null);
  assert.equal(s.calls.filter(call => call.method.endsWith('get_open_tasks')).at(-1).args.service_card, null);
  assert(!s.text(s.ready).includes('cfg-service-location-context'));
});
test('scoped refresh rejection preserves operator identification for retry or Show All', async () => {
  const s = fixture(); location(s); await s.scan('location-uuid'); s.listError = new Error('Location Card is inactive');
  await s.api.load(); s.flush(); assert.equal(s.state.token, 'TOKEN'); assert.equal(s.storedToken, 'TOKEN');
  assert(s.alerts.at(-1).message.includes('Retry or select Show All'));
});
test('late task-list reply cannot overwrite a newly selected location', async () => {
  const s = fixture(); s.state.service_card = { name: 'LOC-A' }; let reply;
  s.taskRequest = () => new Promise(resolve => { reply = resolve; });
  const pending = s.api.load(); await new Promise(resolve => setImmediate(resolve));
  s.state.service_card = { name: 'LOC-B' }; s.state.tasks = [{ name: 'B-TASK' }];
  reply({ message: [{ name: 'STALE-A-TASK' }] }); await pending;
  assert.equal(s.state.tasks[0].name, 'B-TASK');
});
test('existing exact Task scan still opens its task rather than a credential', async () => {
  const s = fixture(); await s.scan('KTASK-1'); assert.equal(s.foundTask, 'KTASK-1'); assert.equal(credentialCalls(s).length, 0);
});
test('explicit Task scan can leave a location filter', async () => {
  const s = fixture(); s.state.service_card = { name: 'LOC-CARD' }; await s.scan('KTASK-1');
  assert.equal(s.state.service_card, null); assert.equal(s.foundTask, 'KTASK-1');
});
test('Schedule Service Point QR keeps its occurrence-resolution path', async () => {
  const s = fixture(); s.state.service_card = { name: 'LOC-CARD' };
  await s.scan('CFG:SERVICE:SCHEDULE:SCH'); assert.equal(s.foundTask, 'KTASK-1');
  assert(s.calls.some(call => call.method.endsWith('resolve_service_scan'))); assert.equal(s.state.service_card, null);
});
test('reusable DocType Action Card routing remains available', async () => {
  const s = fixture(); s.actionResolution = { matched: true, card: { name: 'ACTION' } }; await s.scan('action-uuid');
  assert.equal(s.selectedAction.card.name, 'ACTION'); assert.equal(credentialCalls(s).length, 0);
});
test('unmatched raw operator credential keeps the existing switch path', async () => {
  const s = fixture(); await s.scan('employee-secret'); assert.equal(credentialCalls(s).length, 1);
  assert.equal(credentialCalls(s)[0].args.token, 'employee-secret');
});
test('explicit operator URL skips location lookup and clears the previous location', async () => {
  const s = fixture(); s.state.service_card = { name: 'LOC-CARD' };
  await s.scan('https://example.test/app/kanban-tasks#operator=employee-secret');
  assert(!s.calls.some(call => call.method.endsWith('resolve_service_card_scan')));
  assert.equal(credentialCalls(s)[0].args.token, 'employee-secret'); assert.equal(s.state.service_card, null);
});
test('camera scan uses the same General Service Point routing', async () => {
  const s = fixture(); location(s); s.api.scan_service_code(); s.camera.on_scan({ decodedText: 'location-uuid' });
  await new Promise(resolve => setImmediate(resolve)); s.flush();
  assert.equal(s.state.service_card.name, 'LOC-CARD'); assert.equal(credentialCalls(s).length, 0);
});

test('scanned other-role tasks render separately with no Start, Progress, Complete or evidence action', async () => {
  const s = fixture(); location(s);
  s.locationTasks = [task({ assigned_employee: null, responsible_role: 'Maintenance', scan_view_only: true,
    can_operate: false, can_assist: false, monitor_only: true, progress_count: 3, doctype_action_run: 'PRIVATE-RUN' })];
  await s.scan('location-uuid');
  assert(s.text(s.ready).includes('Scanned Tasks — View Only'));
  assert(s.text(s.ready).includes('Maintenance'));
  assert.equal(s.buttons().length, 0); assert.equal(s.buttons(s.active).length, 0);
  assert.equal(s.actions.length, 0); assert.equal(s.media, 0);
});
test('Show All drops scanned other-role references and returns to the role queue', async () => {
  const s = fixture(); location(s);
  s.locationTasks = [task({ name: 'OTHER', scan_view_only: true, can_operate: false })];
  await s.scan('location-uuid'); await s.api.clear_task_filter(); s.flush();
  assert(!s.text(s.ready).includes('Scanned Tasks — View Only'));
  assert.equal(s.calls.filter(call => call.method.endsWith('get_open_tasks')).at(-1).args.scanned_task, null);
});
test('exact Task outside the queue is requested by ID and shown as a reference', async () => {
  const s = fixture(); s.state.tasks = [];
  s.scannedTasks = [task({ name: 'KTASK-OTHER', assigned_employee: null, responsible_role: 'Maintenance', scan_view_only: true, can_operate: false })];
  await s.scan('KTASK-OTHER');
  assert.equal(s.calls.find(call => call.method.endsWith('get_open_tasks')).args.scanned_task, 'KTASK-OTHER');
  assert.equal(s.state.scanned_task, 'KTASK-OTHER'); assert.equal(s.foundTask, 'KTASK-OTHER');
  assert(s.text(s.ready).includes('Scanned Tasks — View Only'));
  assert.equal(credentialCalls(s).length, 0);
});
test('exact scanned Task scope survives live refresh', async () => {
  const s = fixture(); await s.scan('KTASK-1'); s.state.live_revision = 'old';
  await s.api.check_live_updates();
  assert.equal(s.calls.filter(call => call.method.endsWith('get_open_tasks')).at(-1).args.scanned_task, 'KTASK-1');
});
for (const card_type of ['Task Card', 'Asset Card']) test(`${card_type} scan opens its reference context`, async () => {
  const s = fixture(); s.resolution = { matched: true, card: { name: 'IDENTITY', card_number: 'CARD-1', card_type, label: 'CONTEXT' } };
  await s.scan('identity-qr'); assert.equal(s.state.service_card.name, 'IDENTITY');
  assert(s.text(s.ready).includes(card_type)); assert(s.text(s.ready).includes('CONTEXT'));
  assert.equal(credentialCalls(s).length, 0);
});

// Keep cross-context async callbacks alive; an unfinished test must fail, never silently exit.
const deadline = setTimeout(() => { console.error('Service Task UI checks timed out'); process.exitCode = 1; }, 5000);
(async () => { for (const [name, run] of tests) { await run(); console.log('ok ' + name); } console.log(`${tests.length} Service Task UI checks passed`); })()
  .catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(deadline));
