/* Offline execution of the actual WO override dialog with browser/Frappe doubles.
 * Run: node cfg_kanban/tests/test_material_quantity_override_ui.cjs
 * Does not verify real browser focus, scanner hardware or ERP acceptance.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function runTests(root = path.resolve(__dirname, '../..'), panelOverride) {
    const panel = panelOverride || fs.readFileSync(path.join(root,
        'cfg_kanban/cfg_kanban/page/kanban_operator/kanban_operator.js'), 'utf8');
    const code = panel.slice(panel.indexOf('\tfunction open_work_order_yield_override('),
        panel.indexOf('\tasync function open_material_run_dialog('));
    assert(code);
    function harness() {
        const h = { calls: [], dialogs: [], messages: [], focuses: 0, token: 0 };
        const state = { operator: { permissions: { override: true } }, session_token: 'SESSION',
            context: { card: { qr_code: 'CARD-1' } } };
        h.state = state;
        h.candidates = [
            { name: 'EXEC-1', job_card: 'JOB-1', operation: 'Print', material_run_context: {
                work_order: 'WO-1', yield_override: { name: 'APPROVAL-1' } } },
            { name: 'EXEC-2', job_card: 'JOB-2', operation: 'Pack', material_run_context: {
                work_order: 'WO-1', yield_override: { name: 'APPROVAL-1' } } },
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
            code+'\nreturn open_work_order_yield_override;');
        h.open = api(state, frappe, value => value, () => h.candidates,
            message => h.messages.push(message), async () => {},
            (dialog, focus, names, field) => { h.binding={dialog,focus,names,field}; },
            {setTimeout: fn => fn()});
        h.dialog=()=>h.dialogs.at(-1);
        h.submit=()=>h.dialog().options.primary_action({...h.dialog().values});
        state.context.executions=h.candidates;
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
        assert(h.calls[0].method.endsWith('revoke_work_order_yield'));
        assert.equal(h.dialog().visible,false);
    });
    test('pending approval prevents duplicate confirmations', async()=>{
        const h=harness(); h.open(); let finish;
        h.respond=()=>new Promise(resolve=>{finish=resolve;});
        const first=h.submit(); await h.submit(); assert.equal(h.calls.length,1);
        finish({message:{status:'Active'}}); await first;
    });

    function progressHarness(count=12) {
        const h={focus:0,messages:[],refresh:0};
        h.rows=Array.from({length:count},(_,i)=>({item_code:'ITEM-'+i,stock_uom:'Nos',qty:0}));
        h.active={material_page:0,material_index:count===1?0:null,dialog:{
            get_value:()=>h.rows,
            get_field:name=>name==='actual_materials'?{grid:{refresh:()=>h.refresh++}}:{$wrapper:{html:value=>{h.guide=value;}}}
        }};
        const source=panel.slice(panel.indexOf('\tfunction refresh_progress_material_guide('),panel.indexOf('\tfunction apply_scanned_quantity('));
        h.scan=new Function('frappe','__','focus_progress_scanner',source+'\nreturn handle_progress_material_quantity;')(
            {utils:{escape_html:value=>value},msgprint:message=>h.messages.push(message)},value=>value,()=>h.focus++);
        return h;
    }
    test('material scanner requires explicit selection and preserves component stock UOM',()=>{
        const h=progressHarness();h.scan(h.active,'CFG:QTY:MATERIAL:5');
        assert.equal(h.rows[0].qty,0);assert.equal(h.messages.length,1);
        h.scan(h.active,'CFG:SELECT:2');h.scan(h.active,'CFG:QTY:MATERIAL:5');
        assert.equal(h.rows[1].qty,5);assert.equal(h.rows[0].qty,0);assert.equal(h.rows[1].stock_uom,'Nos');
    });
    test('material scanner pages beyond ten without selecting the wrong material',()=>{
        const h=progressHarness();h.scan(h.active,'CFG:CMD:NEXT_MATERIALS');
        assert.equal(h.active.material_page,1);assert(h.guide.includes('ITEM-10'));
        h.scan(h.active,'CFG:SELECT:1');h.scan(h.active,'CFG:QTY:MATERIAL:5');
        assert.equal(h.rows[10].qty,5);assert.equal(h.rows[0].qty,0);
        h.scan(h.active,'CFG:CMD:PREVIOUS_MATERIALS');assert.equal(h.active.material_index,null);
        h.scan(h.active,'CFG:QTY:MATERIAL:2');assert.equal(h.rows[10].qty,5);
    });
    function correctionHarness() {
        const h={calls:[],focus:0,fields:{}};
        const state={operator:{permissions:{override:true}},session_token:'SESSION',context:{card:{name:'CARD',qr_code:'QR'},executions:[
            {name:'EXEC-1',job_card:'JC-1',operation:'Print'},
            {name:'EXEC-2',job_card:'JC-2',operation:'Pack'}]}};
        h.respond=async request=>({message:request.method.endsWith('material_correction_context')?{choices:Array.from({length:12},(_,i)=>({value:'TRACE:'+i,label:'BAG '+i,qty:3}))}:{actual_qty:5}});
        const frappe={utils:{get_random:()=>'STABLE-TOKEN',escape_html:value=>value},
            call:async request=>{h.calls.push(request);return h.respond(request);},
            throw:message=>{throw Error(message);},msgprint:()=>{},show_alert:()=>{},ui:{Dialog:class{
                constructor(options){this.options=options;this.values={};this.visible=true;
                    for(const field of options.fields)if(field.fieldname)this.values[field.fieldname]=field.default;
                    this.$wrapper={is:()=>this.visible};h.dialog=this;}
                set_value(key,value){this.values[key]=value;return Promise.resolve();}
                get_value(key){return this.values[key];}
                set_df_property(){}
                get_field(name){return {$input:{on(){}},$wrapper:{html:value=>{h.fields[name]=value;}},set_focus:()=>h.focus++};}
                get_primary_btn(){return {trigger:()=>this.options.primary_action({...this.values})};}
                show(){}
                hide(){this.visible=false;if(this.onhide)this.onhide();}
            }}};
        const source=panel.slice(panel.indexOf('\tasync function open_material_use_correction('),panel.indexOf('\tasync function open_material_run_dialog('));
        h.open=new Function('state','frappe','__','scanner_command_message','load_card','bind_confirmation_scanner','window',source+'\nreturn open_material_use_correction;')(
            state,frappe,value=>value,()=>{},async()=>{},(dialog,focus,values,field)=>{
                dialog.cfg_scanner_selection_values=values;dialog.cfg_scanner_selection_field=field;
                dialog.onhide=()=>{h.focus++;};
            },{setTimeout:fn=>fn()});
        const scanner=panel.slice(panel.indexOf('\tasync function handle_confirmation_scanner_value('),panel.indexOf('\tfunction scanner_selection_dialog('));
        h.scan=new Function('frappe','__','window',scanner+'\nreturn handle_confirmation_scanner_value;')(frappe,value=>value,{setTimeout:fn=>fn()});
        return h;
    }
    test('correction completes operation selection, paged allocation, quantity, reason and confirm with scanner',async()=>{
        const h=correctionHarness();await h.open();
        await h.scan(h.dialog,'CFG:SELECT:2');assert.equal(h.calls[0].args.execution_name,'EXEC-2');
        await h.scan(h.dialog,'CFG:CMD:NEXT_MATERIALS');
        await h.scan(h.dialog,'CFG:SELECT:1');
        await h.scan(h.dialog,'CFG:QTY:MATERIAL:5');await h.scan(h.dialog,'Counted five bags');
        await h.scan(h.dialog,'CFG:CMD:CONFIRM');
        const request=h.calls.at(-1);
        assert.equal(request.args.target,'TRACE:10');assert.equal(request.args.execution_name,'EXEC-2');
        assert.equal(request.args.actual_qty,5);assert.equal(request.args.reason,'Counted five bags');
        assert.equal(h.dialog.visible,false);assert(h.focus>0);
    });
    test('correction failure retains exact retry identity and scanner focus',async()=>{
        const h=correctionHarness();await h.open();await h.scan(h.dialog,'CFG:SELECT:1');
        await h.scan(h.dialog,'CFG:SELECT:1');await h.scan(h.dialog,'CFG:QTY:MATERIAL:5');await h.scan(h.dialog,'Reason');
        h.respond=async()=>{throw Error('network');};
        await assert.rejects(h.scan(h.dialog,'CFG:CMD:CONFIRM'));await assert.rejects(h.scan(h.dialog,'CFG:CMD:CONFIRM'));
        assert.equal(h.calls.at(-1).args.event_token,h.calls.at(-2).args.event_token);
        assert.equal(h.dialog.visible,true);assert(h.focus>0);
    });
    test('correction cancel restores focus without changing quantities',async()=>{
        const h=correctionHarness();await h.open();await h.scan(h.dialog,'CFG:CMD:CANCEL');
        assert.equal(h.calls.length,0);assert.equal(h.dialog.visible,false);assert(h.focus>0);
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
