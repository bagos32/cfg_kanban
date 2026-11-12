/* Offline execution of the actual WO override dialog with browser/Frappe doubles.
 * Run: node cfg_kanban/tests/test_material_rotation_override_ui.cjs
 * Does not verify real browser focus, scanner hardware or ERP acceptance.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function runTests(root = path.resolve(__dirname, '../..'), panelOverride) {
    const panel = panelOverride || fs.readFileSync(path.join(root,
        'cfg_kanban/cfg_kanban/page/kanban_operator/kanban_operator.js'), 'utf8');
    const code = panel.slice(panel.indexOf('\tfunction open_material_rotation_override('),
        panel.indexOf('\tasync function open_material_run_dialog('));
    assert(code);
    function harness() {
        const h = { calls: [], dialogs: [], messages: [], focuses: 0, token: 0 };
        const state = { operator: { permissions: { override: true } }, session_token: 'SESSION',
            context: { card: { qr_code: 'CARD-1' } } };
        h.state = state;
        h.candidates = [
            { name: 'EXEC-1', job_card: 'JOB-1', operation: 'Print', material_run_context: {
                work_order: 'WO-1', material_rotation_override: { name: 'APPROVAL-1' } } },
            { name: 'EXEC-2', job_card: 'JOB-2', operation: 'Pack', material_run_context: {
                work_order: 'WO-1', material_rotation_override: { name: 'APPROVAL-1' } } },
        ];
        h.respond = async () => ({ message: { status: 'Active' } });
        const frappe = { utils: { get_random: () => 'TOKEN-'+(++h.token), escape_html: value => value },
            call: async request => { h.calls.push(request); return h.respond(request); },
            ui: { Dialog: class {
                constructor(options) {
                    this.options=options; this.values={}; this.visible=true;
                    for (const f of options.fields) if(f.fieldname) this.values[f.fieldname]=f.default;
                    this.$wrapper={ is: () => this.visible }; h.dialogs.push(this);
                }
                async set_value(key,value) { this.values[key]=value; }
                get_field() { return { set_focus: () => h.focuses++ }; }
                show() {}
                hide() { this.visible=false; h.focuses++; }
            } },
        };
        const api = new Function('state','frappe','__','material_run_candidates',
            'scanner_command_message','load_card','bind_confirmation_scanner','window',
            code+'\nreturn open_material_rotation_override;');
        h.open = api(state, frappe, value => value, () => h.candidates,
            message => h.messages.push(message), async () => {},
            (dialog, focus, names, field) => { h.binding={dialog,focus,names,field}; },
            {setTimeout: fn => fn()});
        h.dialog=()=>h.dialogs.at(-1);
        h.submit=()=>h.dialog().options.primary_action({...h.dialog().values});
        return h;
    }
    const cases=[];
    const test=(name,fn)=>cases.push([name,fn]);
    test('multiple lanes of one WO produce one approval context', async()=>{
        const h=harness(); h.open();
        assert.deepEqual(h.binding.names,['EXEC-2']);
        assert.equal(h.dialog().values.execution_name,'EXEC-2');
        assert(h.dialog().options.fields[0].options.includes('WO-1'));
    });
    test('multiple WOs require an explicit numbered choice', async()=>{
        const h=harness(); h.candidates[1].material_run_context.work_order='WO-2'; h.open();
        assert.equal(h.dialog().values.execution_name,''); await h.submit(); assert.equal(h.calls.length,0);
        assert.deepEqual(h.binding.names,['EXEC-1','EXEC-2']);
        await h.dialog().set_value('execution_name',h.binding.names[1]);
        await h.dialog().cfg_raw_scanner_handler('Supervisor reason'); await h.submit();
        assert.equal(h.calls[0].args.execution_name,'EXEC-2');
        assert.equal(h.calls[0].args.reason,'Supervisor reason');
    });
    test('unauthorized operator cannot open an approval dialog', async()=>{
        const h=harness(); h.state.operator.permissions.override=false; h.open();
        assert.equal(h.dialogs.length,0); assert.equal(h.calls.length,0);
    });
    test('failed request retains token and restores focus', async()=>{
        const h=harness(); h.open(); await h.dialog().cfg_raw_scanner_handler('Reason');
        h.respond=async()=>{throw Error('network');};
        await assert.rejects(h.submit()); await assert.rejects(h.submit());
        assert.equal(h.calls[0].args.event_token,h.calls[1].args.event_token);
        assert(h.focuses>=2);
    });
    test('revocation targets the exact approval displayed when opening', async()=>{
        const h=harness(); h.open(true); await h.dialog().cfg_raw_scanner_handler('Revoke reason');
        await h.submit(); assert.equal(h.calls[0].args.approval_name,'APPROVAL-1');
        assert(h.calls[0].method.endsWith('revoke_work_order_material_rotation'));
        assert.equal(h.dialog().visible,false);
    });
    test('pending approval prevents duplicate confirmations', async()=>{
        const h=harness(); h.open(); let finish;
        h.respond=()=>new Promise(resolve=>{finish=resolve;});
        const first=h.submit(); await h.submit(); assert.equal(h.calls.length,1);
        finish({message:{status:'Active'}}); await first;
    });
    const passed=[];
    for(const [name,fn] of cases){await fn(); passed.push(name);}
    return passed;
}
module.exports=runTests;
if(require.main===module) runTests().then(passed=>{
    for(const name of passed)console.log('PASS '+name);
    console.log(`${passed.length} offline override UI checks passed`);
}).catch(error=>{console.error(error);process.exitCode=1;});
