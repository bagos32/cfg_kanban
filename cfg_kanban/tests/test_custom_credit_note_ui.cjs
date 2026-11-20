/* Desk accounting controls with a real script and a lightweight Frappe adapter. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../public/js/cfg_kanban_return_case.js'), 'utf8');
function fixture(available = true) {
  const state = { calls: [], routes: [], alerts: [], properties: [], buttons: [] };
  const frappe = {
    user_roles: ['Accounts User'], utils: { escape_html: s => String(s ?? ''), get_random: () => 'EVENT' },
    ui: { form: { on: (_, handlers) => { state.handlers = handlers; } } },
    set_route: (...args) => state.routes.push(args), show_alert: value => state.alerts.push(value), msgprint: () => {},
    call: async request => {
      state.calls.push(request);
      if (request.method.endsWith('get_accounting_context')) return { message: { custom_credit_note_available: available, accepted_items: [], candidate_invoices: [] } };
      if (state.error) throw state.error;
      return { message: state.result || { credit_document: 'NATIVE-1', credit_document_doctype: 'Sales Invoice' } };
    }
  };
  frappe.ui.Dialog = class {
    constructor(options) {
      state.dialog = this; this.options = options; this.fields_dict = {}; this.values = {};
      for (const field of options.fields) {
        this.fields_dict[field.fieldname] = { df: { ...field }, $wrapper: { html: () => {} } };
        if (field.default !== undefined) this.values[field.fieldname] = field.default;
      }
      this.values.source_basis = 'Exact Sales Invoice';
    }
    get_value(name) { return this.values[name]; }
    set_value(name, value) { this.values[name] = value; }
    set_df_property(name, key, value) { state.properties.push([name, key, value]); this.fields_dict[name].df[key] = value; }
    disable_primary_action() { this.disabled = true; }
    enable_primary_action() { this.disabled = false; }
    show() { this.shown = true; }
    hide() { this.hidden = true; }
  };
  const ctx = vm.createContext({ frappe, __: text => text, console });
  vm.runInContext(source, ctx);
  state.frm = { docname: 'CASE', doc: { return_flow: 'Customer Return for QC', state: 'QC Completed - Accounting Pending', accepted_total_qty: 2 },
    is_new: () => false, add_custom_button: (name, action) => state.buttons.push({ name, action }), reload_doc: async () => {} };
  state.open = async () => { await ctx.open_accounting_dialog(state.frm); return state.dialog; };
  state.submit = async (values = {}) => {
    const dialog = state.dialog;
    await dialog.options.primary_action({ source_basis: 'Exact Sales Invoice', source_sales_invoice: 'ORIGINAL', decision_notes: 'QC accepted', ...dialog.values, ...values });
  };
  return state;
}
const tests = [];
const test = (name, fn) => tests.push([name, fn]);
test('checkbox defaults to standard Sales Invoice Return', async () => {
  const s = fixture(); const d = await s.open(); assert.equal(d.values.use_custom_credit_note, 0);
  await s.submit(); assert.equal(s.calls.at(-1).args.use_custom_credit_note, 0);
  assert.equal(s.routes.at(-1)[1], 'Sales Invoice');
});
test('checked choice reaches backend and opens custom Credit Note', async () => {
  const s = fixture(); await s.open(); s.result = { credit_document: 'CN-1', credit_document_doctype: 'Credit Note' };
  await s.submit({ use_custom_credit_note: 1 }); assert.equal(s.calls.at(-1).args.use_custom_credit_note, 1);
  assert.equal(s.routes.at(-1)[1], 'Credit Note'); assert.equal(s.routes.at(-1)[2], 'CN-1');
});
test('unavailable optional app or permissions leave checkbox disabled', async () => {
  const s = fixture(false); const d = await s.open(); assert.equal(d.fields_dict.use_custom_credit_note.df.read_only, true);
});
test('No Credit hides and clears custom choice', async () => {
  const s = fixture(); const d = await s.open(); d.values.use_custom_credit_note = 1; d.values.source_basis = 'No Credit';
  d.fields_dict.source_basis.df.onchange(); assert.equal(d.values.use_custom_credit_note, 0);
  assert.equal(d.fields_dict.use_custom_credit_note.df.hidden, true);
});
test('No Credit submission sends neither source nor custom-document request', async () => {
  const s = fixture(); await s.open(); s.result = {};
  await s.submit({ source_basis: 'No Credit', source_sales_invoice: 'ORIGINAL', use_custom_credit_note: 1 });
  assert.equal(s.calls.at(-1).args.use_custom_credit_note, 0); assert.equal(s.calls.at(-1).args.source_sales_invoice, null);
  assert.equal(s.routes.length, 0);
});
test('backend rejection keeps dialog editable without reporting success', async () => {
  const s = fixture(); const d = await s.open(); s.error = new Error('Credit Note Create permission required');
  await assert.rejects(s.submit({ use_custom_credit_note: 1 }), /permission/);
  assert.equal(d.disabled, false); assert.equal(s.routes.length, 0); assert.equal(s.alerts.length, 0);
});
test('legacy backend response still opens Sales Invoice Return', async () => {
  const s = fixture(); await s.open(); s.result = { credit_document: 'OLD-RETURN' };
  await s.submit(); assert.equal(s.routes.at(-1)[1], 'Sales Invoice');
});
test('existing custom document and its native accounting invoice open separately', async () => {
  const s = fixture(); Object.assign(s.frm.doc, { credit_document: 'CN-1', credit_document_doctype: 'Credit Note',
    credit_document_status: 'Submitted', accounting_sales_invoice: 'SINV-RET-1' });
  s.handlers.refresh(s.frm);
  s.buttons.find(b => b.name === 'Open Credit Return').action(); assert.equal(s.routes.at(-1)[1], 'Credit Note');
  s.buttons.find(b => b.name === 'Open Accounting Sales Invoice Return').action(); assert.equal(s.routes.at(-1)[2], 'SINV-RET-1');
  assert.equal(s.buttons.some(b => b.name === 'Prepare Accounting Decision'), false);
});
(async () => {
  for (const [name, fn] of tests) { await fn(); console.log('ok '+name); }
  console.log(tests.length+' custom Credit Note UI checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
