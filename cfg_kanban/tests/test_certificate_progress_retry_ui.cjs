/* Offline execution of the actual dialog functions with browser/Frappe doubles.
 * Run: node cfg_kanban/tests/test_certificate_progress_retry_ui.cjs
 * This does not establish real browser, scanner, database or ERP acceptance.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function runTests(root = path.resolve(__dirname, '../..'), panelOverride) {
    const panel = panelOverride || fs.readFileSync(path.join(root,
        'cfg_kanban/cfg_kanban/page/kanban_operator/kanban_operator.js'), 'utf8');
    const dialogCode = panel.slice(panel.indexOf('\t// Durable intent,'),
        panel.indexOf('\n\tfunction close_consolidated_certificate_process()'));
    const scannerCode = panel.slice(panel.indexOf('\tasync function handle_certificate_dialog_scan('),
        panel.indexOf('\n\tasync function submit_certificate_process()'));
    assert(dialogCode && scannerCode);
    function shared() {
        const map = new Map();
        return { held: false, sequence: 0, storage: {
            getItem: key => map.get(key) || null,
            setItem: (key, value) => map.set(key, value),
        } };
    }
    const values = { good_qty: 60, reject_qty: 0, output_tag: 'TAG-1',
        output_batch: 'BATCH-1', printed_expiry: '2027-01-01',
        first_output_serial: 'S-1', last_output_serial: 'S-60' };
    function harness(store = shared()) {
        const h = { store, dialogs: [], calls: [], messages: [], focus: 0 };
        const state = { session_token: 'CURRENT-SESSION', context: {
            card: { qr_code: 'CARD-1' }, certificate_process: { run: {
                name: 'RUN-1', kanban_cycle: 'CYCLE-1', status: 'In Progress',
                progress_mode: 'Consolidated Partial Progress', selected_qty: 100, good_qty: 0,
            } },
        } };
        h.state = state;
        const frappe = {
            utils: { get_random: () => `TOKEN-${++store.sequence}` },
            ui: { Dialog: class {
                constructor(options) {
                    this.options = options; this.values = {}; this.props = {};
                    for (const f of options.fields) this.values[f.fieldname] = f.default;
                    h.dialogs.push(this);
                }
                async set_values(next) { Object.assign(this.values, next); }
                async set_value(key, value) { this.values[key] = value; }
                get_value(key) { return this.values[key]; }
                set_df_property(key, prop, value) { this.props[`${key}.${prop}`] = value; }
                get_field() { return { $wrapper: { text() {} } }; }
                hide() { this.hidden = true; state.active_certificate_dialog = null; h.focus++; }
                get_primary_btn() { return { trigger: () => {
                    h.lastSubmit = this.options.primary_action(this.values);
                } }; }
            } },
            call: async request => {
                h.calls.push(JSON.parse(JSON.stringify(request.args)));
                return h.respond(request);
            },
            msgprint: message => h.messages.push(message),
            show_alert: message => h.messages.push(message),
        };
        h.respond = async request => ({ message: {
            outcome: 'recorded', event_token: request.args.event_token,
        } });
        const navigator = { locks: { request: async (key, options, callback) => {
            if (store.held) return callback(null);
            store.held = true;
            try { return await callback({ name: key }); } finally { store.held = false; }
        } } };
        h.navigator = navigator;
        const factory = new Function('localStorage', 'navigator', 'frappe', 'state', '__',
            'activate_certificate_dialog', 'scanner_command_message', 'load_card',
            'rearm_certificate_scanner', 'open_camera_scanner', dialogCode + scannerCode +
            '\nreturn {open: open_certificate_process_progress, scan: handle_certificate_dialog_scan};');
        const api = factory(store.storage, navigator, frappe, state, x => x,
            (dialog, mode) => { state.active_certificate_dialog = { dialog, mode, target: 'output_tag' }; },
            message => h.messages.push(message), async () => { if (h.reloadError) throw Error('reload'); },
            () => h.focus++, () => {});
        h.open = async () => { await api.open(); return h.dialogs.at(-1); };
        h.submit = (dialog, inputs = values) => dialog.options.primary_action({ ...inputs });
        h.scan = api.scan;
        h.saved = () => JSON.parse(store.storage.getItem('cfg_certificate_progress_v1:CYCLE-1'));
        return h;
    }
    const cases = [];
    const test = (name, fn) => cases.push([name, fn]);
    test('lost response retains exact payload and token, ignoring edits on retry', async () => {
        const h = harness(), d = await h.open();
        h.respond = async () => { throw Error('response lost after commit'); };
        await h.submit(d);
        assert.equal(h.saved().status, 'pending');
        assert.equal(d.props['good_qty.read_only'], 1);
        assert(!JSON.stringify(h.saved()).includes('CURRENT-SESSION'));
        h.state.session_token = 'REAUTHORIZED-SESSION';
        await h.submit(d, { ...values, good_qty: 5, output_tag: 'DIFFERENT' });
        assert.deepEqual(h.calls[1], { ...h.calls[0], operator_session_token: 'REAUTHORIZED-SESSION' });
    });
    test('cancel/reopen and page refresh restore pending evidence', async () => {
        const h = harness(); h.respond = async () => { throw Error('lost'); };
        const d = await h.open(); await h.submit(d); await h.scan(d, 'CFG:CMD:CANCEL');
        assert.equal(h.saved().status, 'pending');
        const refreshed = harness(h.store), restored = await refreshed.open();
        assert.equal(restored.values.good_qty, 60);
        assert.equal(restored.values.output_tag, 'TAG-1');
        await refreshed.submit(restored, { ...values, good_qty: 2 });
        assert.deepEqual(refreshed.calls[0], h.calls[0]);
        assert.equal(refreshed.saved().status, 'recorded');
    });
    test('confirmed rejection unlocks correction and gives the next attempt a new token', async () => {
        const h = harness(), d = await h.open();
        h.respond = async req => ({ message: { outcome: 'rejected', event_token: req.args.event_token } });
        await h.submit(d);
        assert.equal(h.saved().status, 'rejected'); assert.equal(d.props['good_qty.read_only'], 0);
        await h.submit(d, { ...values, good_qty: 20 });
        assert.equal(h.calls[1].good_qty, 20);
        assert.notEqual(h.calls[1].event_token, h.calls[0].event_token);
    });
    test('unexpected error or uncorrelated response never unlocks corrections', async () => {
        for (const response of [{}, { exc: 'error', message: {} },
            { message: { outcome: 'rejected', event_token: 'WRONG' } }]) {
            const h = harness(), d = await h.open(); h.respond = async () => response;
            await h.submit(d); assert.equal(h.saved().status, 'pending');
            assert.equal(d.props['good_qty.read_only'], 1);
        }
    });
    test('rapid repeated confirmation sends only one request', async () => {
        const h = harness(), d = await h.open(); let release;
        h.respond = req => new Promise(resolve => { release = () => resolve({ message: {
            outcome: 'recorded', event_token: req.args.event_token,
        } }); });
        const first = h.submit(d); await new Promise(resolve => setImmediate(resolve));
        await h.submit(d); assert.equal(h.calls.length, 1);
        release(); await first; await h.submit(d); assert.equal(h.calls.length, 1);
    });
    test('scanner Confirm retries pending and quantity/tag scans cannot change it', async () => {
        const h = harness(), d = await h.open(); h.respond = async () => { throw Error('lost'); };
        await h.submit(d); await h.scan(d, 'CFG:QTY:GOOD:1'); await h.scan(d, 'OTHER-TAG');
        assert.equal(d.values.good_qty, 60); assert.equal(d.values.output_tag, 'TAG-1');
        await h.scan(d, 'CFG:CMD:CONFIRM'); await h.lastSubmit;
        assert.deepEqual(h.calls[0], h.calls[1]); assert(h.focus > 0);
    });
    test('storage write failure prevents sending', async () => {
        const h = harness(), d = await h.open();
        h.store.storage.setItem = () => { throw Error('quota'); };
        await h.submit(d); assert.equal(h.calls.length, 0);
    });
    test('corrupt saved record blocks opening instead of replacing identity', async () => {
        const h = harness(); h.store.storage.setItem('cfg_certificate_progress_v1:CYCLE-1', '{bad');
        await h.open(); assert.equal(h.dialogs.length, 0); assert.equal(h.calls.length, 0);
    });
    test('two tabs cannot send simultaneously', async () => {
        const store = shared(), a = harness(store), b = harness(store);
        const da = await a.open(), db = await b.open(); let release;
        a.respond = req => new Promise(resolve => { release = () => resolve({ message: {
            outcome: 'recorded', event_token: req.args.event_token,
        } }); });
        const first = a.submit(da); await new Promise(resolve => setImmediate(resolve));
        await b.submit(db); assert.equal(b.calls.length, 0); release(); await first;
        await b.submit(db); assert.equal(b.calls.length, 0);
    });
    test('stale recovery tab observes acknowledgement without creating another micro-lot', async () => {
        const a = harness(); a.respond = async () => { throw Error('lost'); };
        const da = await a.open(); await a.submit(da);
        const b = harness(a.store), db = await b.open();
        a.respond = async req => ({ message: { outcome: 'recorded', event_token: req.args.event_token } });
        await a.submit(da); await b.submit(db);
        assert.equal(b.calls.length, 0); assert(db.hidden);
    });
    test('next explicitly opened micro-lot gets a new token', async () => {
        const h = harness(); await h.submit(await h.open()); await h.submit(await h.open());
        assert.notEqual(h.calls[0].event_token, h.calls[1].event_token);
    });
    test('successful acknowledgement survives a subsequent panel reload failure', async () => {
        const h = harness(), d = await h.open(); h.reloadError = true;
        await h.submit(d); await h.submit(d);
        assert.equal(h.saved().status, 'recorded'); assert.equal(h.calls.length, 1);
        assert(h.messages.at(-1).includes('Progress was acknowledged'));
    });
    test('closed run permits only a saved pending retry', async () => {
        const h = harness(); h.respond = async () => { throw Error('lost'); };
        await h.submit(await h.open()); const next = harness(h.store);
        next.state.context.certificate_process.run.status = 'Completed';
        const d = await next.open(); assert(d); await next.submit(d);
        const fresh = harness(); fresh.state.context.certificate_process.run.status = 'Completed';
        await fresh.open(); assert.equal(fresh.dialogs.length, 0);
    });
    test('unsupported browser fails closed', async () => {
        const h = harness(); h.navigator.locks = null;
        await h.open(); assert.equal(h.dialogs.length, 0); assert.equal(h.calls.length, 0);
    });
    const passed = [];
    for (const [name, fn] of cases) { await fn(); passed.push(name); }
    return passed;
}
module.exports = runTests;
if (require.main === module) runTests().then(passed => {
    for (const name of passed) console.log(`PASS ${name}`);
    console.log(`${passed.length} offline JavaScript behavioral checks passed`);
}).catch(error => { console.error(error); process.exitCode = 1; });
