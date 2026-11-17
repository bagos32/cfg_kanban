/* Executes actual scanner/dialog functions with doubles; not real kiosk acceptance. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
async function runTests(root=path.resolve(__dirname,'../..')) {
    const panel=fs.readFileSync(path.join(root,'cfg_kanban/cfg_kanban/page/kanban_operator/kanban_operator.js'),'utf8');
    const candidates='';
    const dialogs=panel.slice(panel.indexOf('    async function open_hopper_recovery('),panel.indexOf('    async function open_material_run_recovery('));
    const scanner=panel.slice(panel.indexOf('\tasync function handle_confirmation_scanner_value('),panel.indexOf('\tfunction scanner_selection_dialog('));
    function harness(count=1) {
        const h={calls:[],dialogs:[],messages:[],focus:0,sequence:0,guides:{},handlers:{}};
        const executions=Array.from({length:count},(_,index)=>({name:'EXEC-'+index,status:'Ready',operation:'Packing',job_card:'JC-'+index,
            material_run_control:'Required Before Progress',material_run_context:{execution_status:'Ready',material_rules:[{rule_row:'BAG',item_code:'BAG',stock_uom:'Nos',qty_per_output:1}],boundary_required:false}}));
        h.state={operator:{permissions:{report_progress:true,override:true}},session_token:'SESSION',context:{card:{name:'CARD',qr_code:'QR'},cycle:{name:'CYCLE'},executions}};
        h.targetCount=1;
        h.respond=async request=>({message:request.method.endsWith('carry_in_targets')?{work_order:request.args.target_work_order,choices:Array.from({length:h.targetCount},(_,index)=>({name:'JC-RINSE-'+index,label:'Rinse Job '+index}))}:request.method.endsWith('recovery_context')?{hopper_fill:'FILL',work_order:'WO',work_order_status:'Closed',item_code:'PRODUCT',remaining_qty:3,reserved_qty:0,stock_uom:'Nos'}:{recovered_qty:3}});
        const frappe={utils:{get_random:()=>`TOKEN-${++h.sequence}`,escape_html:value=>String(value)},
            call:async request=>{h.calls.push(request);return h.respond(request);},
            show_alert:value=>h.messages.push(value),msgprint:value=>h.messages.push(value),
            throw:message=>{throw Error(message);},ui:{Dialog:class{
                constructor(options){this.options=options;this.values={};this.visible=true;this.props={};
                    for(const field of options.fields)if(field.fieldname)this.values[field.fieldname]=field.default;
                    this.$wrapper={is:()=>this.visible};h.dialogs.push(this);}
                set_value(key,value){this.values[key]=value;return Promise.resolve();}
                get_value(key){return this.values[key];}
                set_df_property(name,key,value){this.props[name+':'+key]=value;}
                get_field(name){return {$input:{on:(event,fn)=>{h.handlers[event]=fn;}},$wrapper:{html:value=>{h.guides[name]=value;}},set_focus:()=>h.focus++};}
                get_primary_btn(){return {trigger:()=>this.options.primary_action({...this.values})};}
                show(){}
                hide(){this.visible=false;if(this.onhide)this.onhide();}
            }}};
        const api=new Function('state','frappe','__','scanner_command_message','load_card','bind_confirmation_scanner','window',
            candidates+dialogs+'\nreturn {open:open_hopper_recovery,candidates:()=>[]};')(
                h.state,frappe,value=>value,value=>h.messages.push(value),async()=>{},
                (dialog,focus,values,field)=>{dialog.cfg_scanner_selection_values=values;dialog.cfg_scanner_selection_field=field;dialog.onhide=()=>h.focus++;},
                {setTimeout:fn=>fn()});
        h.open=api.open;h.candidates=api.candidates;h.dialog=()=>h.dialogs.at(-1);
        const scan=new Function('frappe','__','window',scanner+'\nreturn handle_confirmation_scanner_value;')(
            frappe,value=>value,{setTimeout:fn=>fn()});
        h.scan=value=>scan(h.dialog(),value);
        h.source=async()=>{await h.scan('CFG:QTY:MATERIAL:5');await h.scan('TAG');};
        return h;
    }
    const cases=[];const test=(name,fn)=>cases.push([name,fn]);
    test('closed WO full transfer is scanner operable without an active card',async()=>{
        const h=harness();h.state.context=null;await h.open();await h.scan('HOPPER_3');await h.scan('CFG:SELECT:1');await h.scan('HOPPER_4');await h.scan('CFG:QTY:MATERIAL:3');await h.scan('Physical transfer verified');await h.scan('CFG:CMD:CONFIRM');
        const args=h.calls.at(-1).args;assert.equal(args.action,'Transfer remaining');assert.equal(args.hopper_fill,'FILL');assert.equal(args.hopper_scan,'HOPPER_3');assert.equal(args.destination_scan,'HOPPER_4');assert.equal(args.physical_qty,3);assert(!h.dialog().visible);assert(h.focus>0);
    });
    test('confirm empty requires explicit zero count and reason by scanner',async()=>{
        const h=harness();await h.open();await h.scan('HOPPER_3');await h.scan('CFG:SELECT:2');await h.scan('CFG:QTY:MATERIAL:0');await h.scan('Physically checked empty');await h.scan('CFG:CMD:CONFIRM');
        assert.equal(h.calls.at(-1).args.action,'Confirm physically empty');assert.equal(h.calls.at(-1).args.physical_qty,0);assert.equal(h.calls.at(-1).args.destination_scan,null);
    });
    test('discard uses physical remainder and preserves source identity',async()=>{
        const h=harness();await h.open();await h.scan('HOPPER_3');await h.scan('CFG:SELECT:3');await h.scan('CFG:QTY:MATERIAL:3');await h.scan('Discarded spoiled material');await h.scan('CFG:CMD:CONFIRM');
        assert.equal(h.calls.at(-1).args.action,'Discard remaining');assert.equal(h.calls.at(-1).args.hopper_fill,'FILL');
    });
    test('touch selection uses the same recovery endpoint and exact fill',async()=>{
        const h=harness();await h.open();const d=h.dialog();await d.set_value('hopper_scan','HOPPER_3');await d.cfg_raw_scanner_handler('HOPPER_3');await d.set_value('action','Discard remaining');await d.set_value('physical_qty','3');await d.set_value('reason','Physical disposition');await d.options.primary_action({...d.values});
        assert.equal(h.calls.at(-1).args.action,'Discard remaining');assert.equal(h.calls.at(-1).args.physical_qty,3);
    });
    test('missing physical count cannot default to confirm empty',async()=>{
        const h=harness();await h.open();await h.scan('HOPPER_3');await h.scan('CFG:SELECT:2');await h.scan('Physical check');await assert.rejects(h.scan('CFG:CMD:CONFIRM'),/physical quantity/);assert.equal(h.calls.length,1);
    });
    test('uncertain response retries identical payload and blocks edits',async()=>{
        const h=harness();await h.open();await h.scan('HOPPER_3');await h.scan('CFG:SELECT:2');await h.scan('CFG:QTY:MATERIAL:0');await h.scan('Physical check');
        h.respond=async()=>{throw Error('Network interrupted');};await assert.rejects(h.scan('CFG:CMD:CONFIRM'));await assert.rejects(h.scan('CFG:CMD:CONFIRM'));
        assert.deepEqual(h.calls.at(-1).args,h.calls.at(-2).args);assert(h.focus>0);
        await h.scan('CFG:QTY:MATERIAL:1');await assert.rejects(h.scan('CFG:CMD:CONFIRM'),/original recovery data/);
        await h.scan('CFG:CMD:CANCEL');assert(!h.dialog().visible);
    });
    test('cancel before confirming never changes the hopper',async()=>{
        const h=harness();await h.open();await h.scan('HOPPER_3');await h.scan('CFG:CMD:CANCEL');assert.equal(h.calls.length,1);assert(h.focus>0);
    });
    test('non-supervisor cannot open recovery',async()=>{
        const h=harness();h.state.operator.permissions.override=false;await h.open();assert.equal(h.dialogs.length,0);assert.equal(h.calls.length,0);
    });
    test('failed source scan keeps scanner focus for retry',async()=>{
        const h=harness();await h.open();h.respond=async()=>{throw Error('No active fill');};await assert.rejects(h.scan('UNKNOWN'));assert(h.focus>0);await h.scan('CFG:CMD:CANCEL');assert(!h.dialog().visible);
    });
    test('carry-in scans Work Order and explicitly selects Rinse Job Card',async()=>{
        const h=harness();h.state.context=null;await h.open();await h.scan('HOPPER_3');await h.scan('CFG:SELECT:4');await h.scan('NEW-WO');await h.scan('CFG:SELECT:1');await h.scan('CFG:QTY:MATERIAL:3');await h.scan('Confirmed inherited WIP');await h.scan('CFG:CMD:CONFIRM');
        const args=h.calls.at(-1).args;assert.equal(args.action,'Carry into Work Order');assert.equal(args.target_work_order,'NEW-WO');assert.equal(args.target_job_card,'JC-RINSE-0');assert.equal(args.physical_qty,3);assert.equal(args.destination_scan,null);
    });
    test('carry-in supports numbered Job Card choices beyond ten',async()=>{
        const h=harness();h.targetCount=12;await h.open();await h.scan('HOPPER_3');await h.scan('CFG:SELECT:4');await h.scan('NEW-WO');await h.scan('CFG:CMD:NEXT_MATERIALS');await h.scan('CFG:SELECT:2');await h.scan('CFG:QTY:MATERIAL:3');await h.scan('Confirmed inherited WIP');await h.scan('CFG:CMD:CONFIRM');
        assert.equal(h.calls.at(-1).args.target_job_card,'JC-RINSE-11');
    });
    test('carry-in touch target change loads the same numbered choices',async()=>{
        const h=harness();await h.open();await h.scan('HOPPER_3');const d=h.dialog();await d.set_value('action','Carry into Work Order');await h.handlers['change.cfg-hopper-action']();await d.set_value('target_work_order','NEW-WO');await h.handlers['change.cfg-hopper-target']();await d.set_value('target_job_card','JC-RINSE-0');await d.set_value('physical_qty','3');await d.set_value('reason','Inherited WIP');await d.options.primary_action({...d.values});
        assert.equal(h.calls.at(-1).args.target_job_card,'JC-RINSE-0');assert.equal(h.calls.at(-1).args.target_work_order,'NEW-WO');
    });
    test('carry-in cannot submit without resolving an exact receiving Job Card',async()=>{
        const h=harness();await h.open();await h.scan('HOPPER_3');await h.scan('CFG:SELECT:4');await h.scan('CFG:QTY:MATERIAL:3');await assert.rejects(h.scan('CFG:CMD:CONFIRM'),/exact Rinse Job Card/);assert.equal(h.calls.length,1);
    });
    test('stable command has global dispatch, touch toolbar and printable catalogue',async()=>{
        assert(panel.includes('RECOVER_HOPPER: open_hopper_recovery'));
        assert(panel.includes('page.add_inner_button(__("Recover Hopper"), open_hopper_recovery)'));
        assert(panel.includes('Closed-Work-Order Hopper recovery: CFG:CMD:RECOVER_HOPPER'));
        assert(fs.readFileSync(path.join(root,'cfg_kanban/api/operator.py'),'utf8').includes('("Recover Hopper", "CFG:CMD:RECOVER_HOPPER", "")'));
        assert(fs.readFileSync(path.join(root,'docs/USER_MANUAL.md'),'utf8').includes('`CFG:CMD:RECOVER_HOPPER`'));
    });
    const passed=[];for(const [name,fn] of cases){await fn();passed.push(name);}return passed;
}
module.exports=runTests;
if(require.main===module)runTests().then(results=>console.log(`${results.length} Hopper recovery scanner checks passed`)).catch(error=>{console.error(error);process.exitCode=1;});
