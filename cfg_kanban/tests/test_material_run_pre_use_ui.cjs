/* Executes actual scanner/dialog functions with doubles; not real kiosk acceptance. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
async function runTests(root=path.resolve(__dirname,'../..')) {
    const panel=fs.readFileSync(path.join(root,'cfg_kanban/cfg_kanban/page/kanban_operator/kanban_operator.js'),'utf8');
    const candidates=panel.slice(panel.indexOf('\tfunction material_run_candidates('),panel.indexOf('\tfunction open_material_rotation_override('));
    const dialogs=panel.slice(panel.indexOf('\tasync function open_material_run_dialog('),panel.indexOf('\tfunction cancel_open_material_run('));
    const scanner=panel.slice(panel.indexOf('\tasync function handle_confirmation_scanner_value('),panel.indexOf('\tfunction scanner_selection_dialog('));
    function harness(count=1) {
        const h={calls:[],dialogs:[],messages:[],focus:0,sequence:0,guides:{}};
        const executions=Array.from({length:count},(_,index)=>({name:'EXEC-'+index,status:'Ready',operation:'Packing',job_card:'JC-'+index,
            material_run_control:'Required Before Progress',material_run_context:{execution_status:'Ready',material_rules:[{rule_row:'BAG',item_code:'BAG',stock_uom:'Nos',qty_per_output:1}],boundary_required:false}}));
        h.state={operator:{permissions:{report_progress:true}},session_token:'SESSION',context:{card:{name:'CARD',qr_code:'QR'},cycle:{name:'CYCLE'},executions}};
        h.respond=async request=>({message:request.method.endsWith('preview_material_draw')?{rule_row:'BAG',item_code:'BAG',stock_uom:'Nos',source_visible_code:'TAG',qty:request.args.quantity}:{name:'RUN'}});
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
                get_field(name){return {$input:{on(){}},$wrapper:{html:value=>{h.guides[name]=value;}},set_focus:()=>h.focus++};}
                get_primary_btn(){return {trigger:()=>this.options.primary_action({...this.values})};}
                show(){}
                hide(){this.visible=false;if(this.onhide)this.onhide();}
            }}};
        const api=new Function('state','frappe','__','scanner_command_message','load_card','bind_confirmation_scanner','window',
            candidates+dialogs+'\nreturn {open:open_material_run_dialog,candidates:material_run_candidates};')(
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
    test('Ready operations can prepare; blocked and terminal operations are excluded',async()=>{
        const h=harness(7);const statuses=['Ready','In Progress','Paused','Blocked','Not Ready','Completed','Cancelled'];
        h.state.context.executions.forEach((row,index)=>{row.status=statuses[index];});
        assert.deepEqual(h.candidates().map(row=>row.status),statuses.slice(0,3));
    });
    test('Ready operation completes source preparation with scanner and never starts Job Card',async()=>{
        const h=harness();await h.open();await h.source();await h.scan('CFG:CMD:CONFIRM');
        assert(h.calls[0].method.endsWith('preview_material_draw'));
        assert(h.calls[1].method.endsWith('start_scanner_run'));
        assert.deepEqual(JSON.parse(h.calls[1].args.material_draws),[{scan_value:'TAG',qty:5,display_source_code:'TAG',source_visible_code:'TAG',rule_row:'BAG',item_code:'BAG',stock_uom:'Nos'}]);
        assert.equal(h.state.context.executions[0].status,'Ready');assert.equal(h.dialog().visible,false);
        assert(h.messages.some(message=>String(message.message).includes('Start Operation before physical work')));
        assert(!h.calls.some(request=>request.method.includes('run_job_card_action')));
    });
    test('multiple operations require explicit numbered selection before evidence',async()=>{
        const h=harness(2);await h.open();assert.equal(h.dialog().values.execution_name,'');
        await h.scan('CFG:CMD:CONFIRM');assert.equal(h.calls.length,0);
        await h.scan('CFG:SELECT:2');await h.source();await h.scan('CFG:SELECT:1');
        assert.equal(h.dialog().values.execution_name,'EXEC-1');
        await h.scan('CFG:CMD:CONFIRM');assert.equal(h.calls.at(-1).args.execution_name,'EXEC-1');
    });
    test('certificate rejection keeps source, retry identity and scanner focus',async()=>{
        const h=harness();await h.open();await h.source();h.respond=async()=>{throw Error('Certificate gate failed');};
        await assert.rejects(h.scan('CFG:CMD:CONFIRM'));await assert.rejects(h.scan('CFG:CMD:CONFIRM'));
        assert.equal(h.calls.at(-1).args.event_token,h.calls.at(-2).args.event_token);
        assert.equal(h.dialog().cfg_material_draws[0].scan_value,'TAG');assert.equal(h.dialog().visible,true);assert(h.focus>0);
        await h.scan('CFG:CMD:CANCEL');assert.equal(h.dialog().visible,false);
    });
    test('Cancel before confirmation records no Material Run',async()=>{
        const h=harness();await h.open();await h.source();await h.scan('CFG:CMD:CANCEL');
        assert.equal(h.calls.length,1);assert(h.calls[0].method.endsWith('preview_material_draw'));
        assert.equal(h.dialog().visible,false);assert(h.focus>0);
    });
    test('preview rejection restores focus without adding a source',async()=>{
        const h=harness();await h.open();h.respond=async()=>{throw Error('wrong Warehouse');};
        await h.scan('CFG:QTY:MATERIAL:5');await assert.rejects(h.scan('WRONG-TAG'));
        assert.equal(h.dialog().cfg_material_draws.length,0);assert.equal(h.dialog().cfg_pending_material_qty,5);assert(h.focus>0);
    });
    test('operator lacking report permission cannot prepare sources',async()=>{
        const h=harness();h.state.operator.permissions.report_progress=false;await h.open();
        assert.equal(h.dialogs.length,0);assert.equal(h.calls.length,0);
    });
    const passed=[];for(const [name,fn] of cases){await fn();passed.push(name);}return passed;
}
module.exports=runTests;
if(require.main===module)runTests().then(results=>console.log(`${results.length} pre-use scanner checks passed`)).catch(error=>{console.error(error);process.exitCode=1;});
