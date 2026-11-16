/* Executes actual scanner/dialog functions with doubles; not real kiosk acceptance. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
async function runTests(root=path.resolve(__dirname,'../..')) {
    const panel=fs.readFileSync(path.join(root,'cfg_kanban/cfg_kanban/page/kanban_operator/kanban_operator.js'),'utf8');
    const candidates='';
    const dialogs=panel.slice(panel.indexOf('    async function open_material_run_recovery('),panel.indexOf('\n\tasync function open_material_run_dialog('));
    const scanner=panel.slice(panel.indexOf('\tasync function handle_confirmation_scanner_value('),panel.indexOf('\tfunction scanner_selection_dialog('));
    function harness(count=1) {
        const h={calls:[],dialogs:[],messages:[],focus:0,sequence:0,guides:{}};
        const executions=Array.from({length:count},(_,index)=>({name:'EXEC-'+index,status:'Ready',operation:'Packing',job_card:'JC-'+index,
            material_run_control:'Required Before Progress',material_run_context:{execution_status:'Ready',material_rules:[{rule_row:'BAG',item_code:'BAG',stock_uom:'Nos',qty_per_output:1}],boundary_required:false}}));
        h.state={operator:{permissions:{report_progress:true,override:true}},session_token:'SESSION',context:{card:{name:'CARD',qr_code:'QR'},cycle:{name:'CYCLE'},executions}};
        h.respond=async request=>({message:request.method.endsWith('recovery_runs')?[{name:'RUN'}]:request.method.endsWith('recovery_context')?{material_run:'RUN',work_order:'WO',operation:'Rinse',unused_qty:1,good_qty:5,hopper_reserved_qty:0}:{released_qty:1}});
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
            candidates+dialogs+'\nreturn {open:open_material_run_recovery,candidates:()=>[]};')(
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
    test('supervisor can release an explicitly selected run by scanner',async()=>{
        const h=harness();await h.open();await h.scan('CFG:SELECT:1');await h.scan('CFG:SELECT:1');await h.scan('Unused balance returned');await h.scan('CFG:CMD:CONFIRM');
        assert.equal(h.calls.at(-1).args.action,'Release unused');assert.equal(h.calls.at(-1).args.material_run,'RUN');
    });
    test('reconstruction scans hopper, physical quantity and reason',async()=>{
        const h=harness();await h.open();await h.scan('CFG:SELECT:1');await h.scan('CFG:SELECT:2');await h.scan('HOPPER_3');await h.scan('CFG:QTY:MATERIAL:5');await h.scan('Physical count verified');await h.scan('CFG:CMD:CONFIRM');
        assert.equal(h.calls.at(-1).args.action,'Reconstruct hopper');assert.equal(h.calls.at(-1).args.hopper_scan,'HOPPER_3');assert.equal(h.calls.at(-1).args.physical_qty,5);
    });
    test('rejected recovery retains identity and focus; cancel is safe',async()=>{
        const h=harness();await h.open();await h.scan('CFG:SELECT:1');await h.scan('CFG:SELECT:1');await h.scan('Physical check');
        h.respond=async()=>{throw Error('Recovery rejected');};await assert.rejects(h.scan('CFG:CMD:CONFIRM'));await assert.rejects(h.scan('CFG:CMD:CONFIRM'));
        assert.equal(h.calls.at(-1).args.event_token,h.calls.at(-2).args.event_token);assert(h.focus>0);
        await h.scan('CFG:CMD:CANCEL');assert.equal(h.dialog().visible,false);
    });
    test('non-supervisor cannot open recovery',async()=>{
        const h=harness();h.state.operator.permissions.override=false;await h.open();assert.equal(h.dialogs.length,0);assert.equal(h.calls.length,0);
    });
    const passed=[];for(const [name,fn] of cases){await fn();passed.push(name);}return passed;
}
module.exports=runTests;
if(require.main===module)runTests().then(results=>console.log(`${results.length} recovery scanner checks passed`)).catch(error=>{console.error(error);process.exitCode=1;});
