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
        h.materials={TAG:{rule_row:'BAG',item_code:'BAG',stock_uom:'Nos',source_visible_code:'TAG'}};
        h.respond=async request=>{
            if(request.method.endsWith('start_scanner_run'))return {message:{name:'RUN'}};
            if(request.method.endsWith('identify_material_run_scan') && (request.args.capture_boundary || request.args.scan_value.startsWith('NEW-')))return {message:{scan_type:'Boundary',boundary:request.args.scan_value}};
            if(request.method.endsWith('identify_material_run_scan') && request.args.scan_value.startsWith('HOPPER'))return {message:{scan_type:'Hopper',preview:{visible_code:request.args.scan_value,work_order:'WO',item_code:'PRODUCT',loaded_qty:5,available_qty:3,run_qty:3,stock_uom:'Nos'}}};
            const source=h.materials[request.args.scan_value];
            if(!source)throw Error('Unconfigured source');
            if(request.args.quantity>10)throw Error('Requested quantity exceeds available');
            const preview={...source,qty:Number(request.args.quantity || 0)};
            return {message:request.method.endsWith('identify_material_run_scan')?{scan_type:'Material',preview}:preview};
        };
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
                get_field(name){return {df:{read_only:this.props[name+':read_only']},$input:{on(){}},$wrapper:{html:value=>{h.guides[name]=value;}},set_focus:()=>h.focus++};}
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
        assert(h.calls[0].method.endsWith('identify_material_run_scan'));
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
        assert.equal(h.calls.length,1);assert(h.calls[0].method.endsWith('identify_material_run_scan'));
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
    test('opt-in Hopper scan displays quantity and is included in the run request',async()=>{
        const h=harness();h.state.context.executions[0].material_run_context.hopper_mode='Consume Hopper';
        const original=h.respond;h.respond=async request=>request.method.endsWith('identify_material_run_scan') && request.args.scan_value.startsWith('HOPPER')
            ? {message:{scan_type:'Hopper',preview:{visible_code:'HOPPER_3',work_order:'WO',loaded_qty:5,available_qty:3,stock_uom:'Nos'}}}
            : original(request);
        await h.open();await h.scan('CFG:CMD:CONFIRM');assert.equal(h.calls.length,0);
        await h.scan('HOPPER_3');assert.equal(h.dialog().cfg_hopper_preview.loaded_qty,5);
        await h.source();await h.scan('CFG:CMD:CONFIRM');
        assert.equal(h.calls.at(-1).args.hopper_scan,'HOPPER_3');
    });
    test('exhausted Operation Card displays why available Hopper WIP stays red',async()=>{
        const h=harness();h.state.context.executions[0].material_run_context.hopper_mode='Consume Hopper';
        const original=h.respond;h.respond=async request=>{
            const result=await original(request);
            if(result.message.scan_type==='Hopper')Object.assign(result.message.preview,{loaded_qty:2,available_qty:2,run_qty:0,
                allocation_target_qty:3,allocation_processed_qty:3,allocation_remaining_qty:0,
                allocation_block_reason:'This Operation Card allocation is complete. Cancel this dialog, close the Operation Card cycle, then allocate its next cycle against the remaining Job Card demand.'});
            return result;
        };
        await h.open();await h.scan('HOPPER_1');await h.source();
        const html=h.guides.material_draw_summary;
        assert(html.includes('0 Nos · HOPPER_1 · Loaded: 2 · Available: 2'));
        assert(html.includes('Card target: 3 · Processed: 3 · Allocation remaining: 0'));
        assert(html.includes('close the Operation Card cycle'));
        assert(html.includes('alert-danger'));await h.scan('CFG:CMD:CONFIRM');
        assert(!h.calls.some(request=>request.method.endsWith('start_scanner_run')));
        await h.scan('CFG:CMD:CANCEL');assert(!h.dialog().visible);assert(h.focus>0);
    });
    test('second run with remaining allocation shows Hopper green and permits touch confirmation',async()=>{
        const h=harness();h.state.context.executions[0].material_run_context.hopper_mode='Consume Hopper';
        const original=h.respond;h.respond=async request=>{
            const result=await original(request);
            if(result.message.scan_type==='Hopper')Object.assign(result.message.preview,{loaded_qty:2,available_qty:2,run_qty:2,
                allocation_target_qty:5,allocation_processed_qty:3,allocation_remaining_qty:2,allocation_block_reason:null});
            return result;
        };
        await h.open();await h.dialog().set_value('material_source_scan','HOPPER_1');
        await h.dialog().options.fields.find(field=>field.fieldname==='read_material_source').click();
        await h.source();assert(!h.guides.material_draw_summary.includes('alert-danger'));
        assert(h.guides.material_draw_summary.includes('Allocation remaining: 2'));
        await h.dialog().get_primary_btn().trigger();assert(h.calls.at(-1).method.endsWith('start_scanner_run'));
    });
    test('failed Hopper preview preserves focus and cannot confirm a run',async()=>{
        const h=harness();h.state.context.executions[0].material_run_context.hopper_mode='Consume Hopper';
        h.respond=async()=>{throw Error('Hopper is empty');};await h.open();
        await assert.rejects(h.scan('HOPPER_3'));assert.equal(h.dialog().cfg_hopper_scan,null);assert(h.focus>0);
        await h.scan('CFG:CMD:CONFIRM');assert.equal(h.calls.length,1);
        await h.scan('CFG:CMD:CANCEL');assert.equal(h.dialog().visible,false);
    });
    test('normal digital handoff adds no Hopper scan or request binding',async()=>{
        const h=harness();h.state.context.executions[0].material_run_context.hopper_mode='None';
        await h.open();await h.source();await h.scan('CFG:CMD:CONFIRM');
        assert.equal(h.calls.length,2);assert.equal(h.calls.at(-1).args.hopper_scan,null);
    });
    test('real Card Context payload requires and submits the Hopper scan',async()=>{
        const {execFileSync}=require('node:child_process');
        const code="import json;from cfg_kanban.tests.test_material_run_pre_use_context import card_run_context;print(json.dumps(card_run_context('Consume Hopper')))";
        const context=JSON.parse(execFileSync('python3',['-B','-c',code],{cwd:root,encoding:'utf8',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}}));
        const h=harness();h.state.context.executions[0].material_run_context=context;
        const original=h.respond;h.respond=async request=>request.method.endsWith('identify_material_run_scan') && request.args.scan_value.startsWith('HOPPER')
            ? {message:{scan_type:'Hopper',preview:{visible_code:'HOPPER_3',work_order:'WO',loaded_qty:5,available_qty:5,stock_uom:'Nos'}}} : original(request);
        await h.open();await h.scan('CFG:CMD:CONFIRM');assert.equal(h.calls.length,0);
        await h.scan('HOPPER_3');await h.source();await h.scan('CFG:CMD:CONFIRM');
        assert.equal(h.calls.at(-1).args.hopper_scan,'HOPPER_3');
    });
    test('partial nested context falls back to execution Hopper snapshot',async()=>{
        const h=harness();h.state.context.executions[0].material_run_hopper_mode='Fill Hopper';
        await h.open();await h.scan('CFG:CMD:CONFIRM');assert.equal(h.calls.length,0);
        assert(h.guides.material_run_guide.includes('Scan an empty production Hopper'));
    });
    function twoMaterials(h) {
        h.state.context.executions[0].material_run_context.material_rules=[{rule_row:'A',item_code:'RAW-A',stock_uom:'Kg'},{rule_row:'B',item_code:'RAW-B',stock_uom:'Nos'}];
        h.materials={A:{rule_row:'A',item_code:'RAW-A',stock_uom:'Kg',source_visible_code:'SOURCE-A'},B:{rule_row:'B',item_code:'RAW-B',stock_uom:'Nos',source_visible_code:'SOURCE-B'}};
    }
    test('checklist starts red in boundary, hopper and configured material order',async()=>{
        const h=harness();const c=h.state.context.executions[0].material_run_context;c.boundary_mode='Every Material Run';c.boundary_required=true;c.hopper_mode='Consume Hopper';c.output_item_code='PRODUCT';
        await h.open();const html=h.guides.material_draw_summary;
        assert(html.indexOf('New output boundary')<html.indexOf('PRODUCT'));
        assert(html.indexOf('PRODUCT')<html.indexOf('BAG'));
        assert.equal((html.match(/alert-danger/g)||[]).length,3);
    });
    test('loaded hopper appears green in Ready to confirm alongside raw tags',async()=>{
        const h=harness();const c=h.state.context.executions[0].material_run_context;c.boundary_mode='Every Material Run';c.boundary_required=true;c.hopper_mode='Consume Hopper';c.output_item_code='PRODUCT';
        await h.open();await h.scan('HOPPER_3');assert(h.guides.material_draw_summary.includes('3 Nos · HOPPER_3'));
        await h.source();await h.scan('NEW-PACK-BOUNDARY');
        assert.equal((h.guides.material_draw_summary.match(/alert-success/g)||[]).length,3);
        await h.scan('CFG:CMD:CONFIRM');assert.equal(h.calls.at(-1).args.output_serial_boundary,'NEW-PACK-BOUNDARY');assert.equal(h.calls.at(-1).args.hopper_scan,'HOPPER_3');
    });
    test('raw tag before boundary or hopper is routed to its item and cannot satisfy those rows',async()=>{
        const h=harness();const c=h.state.context.executions[0].material_run_context;c.boundary_mode='Every Material Run';c.boundary_required=true;c.hopper_mode='Consume Hopper';
        await h.open();await h.source();assert.equal(h.dialog().cfg_material_draws.length,1);assert.equal(h.dialog().get_value('output_serial_boundary'),'');assert.equal(h.dialog().cfg_hopper_scan,null);
        await h.scan('CFG:CMD:CONFIRM');assert(!h.calls.some(r=>r.method.endsWith('start_scanner_run')));
    });
    test('source-first scan waits red for quantity then revalidates and turns green',async()=>{
        const h=harness();await h.open();await h.scan('TAG');assert.equal(h.dialog().cfg_material_draws.length,0);
        assert(h.guides.material_draw_summary.includes('Quantity needed'));await h.scan('CFG:QTY:MATERIAL:5');
        assert.equal(h.dialog().cfg_material_draws[0].qty,5);assert(h.calls.at(-1).method.endsWith('preview_material_draw'));
        assert(!h.guides.material_draw_summary.includes('alert-danger'));
    });
    test('items scanned out of order retain the configured checklist and payload order',async()=>{
        const h=harness();twoMaterials(h);await h.open();await h.scan('CFG:QTY:MATERIAL:5');await h.scan('B');await h.scan('CFG:QTY:MATERIAL:2');await h.scan('A');
        assert(h.guides.material_draw_summary.indexOf('RAW-A')<h.guides.material_draw_summary.indexOf('RAW-B'));
        await h.scan('CFG:CMD:CONFIRM');assert.deepEqual(JSON.parse(h.calls.at(-1).args.material_draws).map(row=>[row.rule_row,row.qty]),[['A',2],['B',5]]);
    });
    test('selected item quantity is not stolen by a different scanned item',async()=>{
        const h=harness();twoMaterials(h);await h.open();await h.scan('CFG:SELECT:1');await h.scan('CFG:QTY:MATERIAL:2');await h.scan('B');
        assert.equal(h.dialog().cfg_material_sources.A.qty,2);assert.equal(h.dialog().cfg_material_sources.B.qty,0);assert.equal(h.dialog().cfg_material_draws.length,0);
        await h.scan('CFG:QTY:MATERIAL:5');await h.scan('A');
        assert.deepEqual(h.dialog().cfg_material_draws.map(row=>[row.rule_row,row.qty]),[['A',2],['B',5]]);
    });
    test('several source-first scans remain visible and explicit selection supplies missing quantity',async()=>{
        const h=harness();twoMaterials(h);await h.open();await h.scan('A');await h.scan('B');await h.scan('CFG:QTY:MATERIAL:5');await h.scan('CFG:SELECT:1');await h.scan('CFG:QTY:MATERIAL:2');
        assert.deepEqual(h.dialog().cfg_material_draws.map(row=>row.qty),[2,5]);
    });
    test('confirmation is blocked when any configured component is still red',async()=>{
        const h=harness();twoMaterials(h);await h.open();await h.scan('CFG:QTY:MATERIAL:2');await h.scan('A');await h.scan('CFG:CMD:CONFIRM');
        assert(!h.calls.some(r=>r.method.endsWith('start_scanner_run')));assert(h.guides.material_draw_summary.includes('RAW-B'));
    });
    test('failed quantity correction removes stale ready draw until successful revalidation',async()=>{
        const h=harness();await h.open();await h.source();await h.scan('CFG:SELECT:1');await assert.rejects(h.scan('CFG:QTY:MATERIAL:100'));
        assert.equal(h.dialog().cfg_material_draws.length,0);assert(h.guides.material_draw_summary.includes('alert-danger'));await h.scan('CFG:CMD:CONFIRM');assert(!h.calls.some(r=>r.method.endsWith('start_scanner_run')));
        await h.scan('CFG:QTY:MATERIAL:5');assert.equal(h.dialog().cfg_material_draws[0].qty,5);
    });
    test('touch quantity and Read Scan use the same checked payload',async()=>{
        const h=harness();await h.open();const d=h.dialog();await d.set_value('material_quantity',5);await d.options.fields.find(f=>f.fieldname==='apply_material_quantity').click();await d.set_value('material_source_scan','TAG');await d.options.fields.find(f=>f.fieldname==='read_material_source').click();await d.options.primary_action({...d.values});
        assert.equal(JSON.parse(h.calls.at(-1).args.material_draws)[0].qty,5);
    });
    test('uncertain confirmation permits original replay but blocks new material edits',async()=>{
        const h=harness();await h.open();await h.source();h.respond=async()=>{throw Error('Network interrupted');};await assert.rejects(h.scan('CFG:CMD:CONFIRM'));
        await h.scan('CFG:QTY:MATERIAL:6');assert.equal(h.dialog().cfg_material_draws[0].qty,5);await assert.rejects(h.scan('CFG:CMD:CONFIRM'));
        assert.deepEqual(h.calls.at(-1).args,h.calls.at(-2).args);
    });
    test('rapid quantity/tag scans serialize around pending source validation',async()=>{
        const h=harness();twoMaterials(h);let release;const original=h.respond;
        h.respond=async request=>request.args.scan_value==='A'?new Promise(resolve=>{release=()=>resolve({message:{scan_type:'Material',preview:{...h.materials.A,qty:request.args.quantity}}});}):original(request);
        await h.open();const first=h.scan('CFG:QTY:MATERIAL:2');const tag=h.scan('A');const second=h.scan('CFG:QTY:MATERIAL:5');const other=h.scan('B');
        await first;await new Promise(resolve=>setImmediate(resolve));assert(release);release();await Promise.all([tag,second,other]);
        assert.deepEqual(h.dialog().cfg_material_draws.map(row=>[row.rule_row,row.qty]),[['A',2],['B',5]]);
    });
    test('Confirm waits for queued source validation instead of submitting an incomplete run',async()=>{
        const h=harness();let release;h.respond=async request=>request.method.endsWith('identify_material_run_scan')?new Promise(resolve=>{release=()=>resolve({message:{scan_type:'Material',preview:{...h.materials.TAG,qty:5}}});}):{message:{name:'RUN'}};
        await h.open();await h.scan('CFG:QTY:MATERIAL:5');const tag=h.scan('TAG');const confirm=h.scan('CFG:CMD:CONFIRM');await new Promise(resolve=>setImmediate(resolve));assert(!h.calls.some(r=>r.method.endsWith('start_scanner_run')));release();await Promise.all([tag,confirm]);assert(h.calls.at(-1).method.endsWith('start_scanner_run'));
    });
    test('cancelled dialog ignores a late source response',async()=>{
        const h=harness();let release;h.respond=async()=>new Promise(resolve=>{release=()=>resolve({message:{scan_type:'Material',preview:{...h.materials.TAG,qty:5}}});});
        await h.open();await h.scan('CFG:QTY:MATERIAL:5');const tag=h.scan('TAG');await new Promise(resolve=>setImmediate(resolve));await h.scan('CFG:CMD:CANCEL');release();await tag;assert.equal(h.dialog().cfg_material_draws.length,0);assert(!h.dialog().visible);
    });
    test('explicit boundary command is globally routed, printable, and supported inside the dialog',async()=>{
        const h=harness();const c=h.state.context.executions[0].material_run_context;c.boundary_mode='Every Material Run';c.boundary_required=true;
        await h.open();await h.scan('CFG:CMD:MATERIAL_RUN_BOUNDARY');await h.scan('NEW-OUTPUT');assert.equal(h.dialog().get_value('output_serial_boundary'),'NEW-OUTPUT');assert.equal(h.calls.at(-1).args.capture_boundary,1);
        assert(panel.includes('MATERIAL_RUN_BOUNDARY: material_run_boundary_command'));
        assert(fs.readFileSync(path.join(root,'cfg_kanban/api/operator.py'),'utf8').includes('CFG:CMD:MATERIAL_RUN_BOUNDARY'));
        assert(panel.includes('CFG:CMD:MATERIAL_RUN_BOUNDARY explicitly captures'));
        assert(fs.readFileSync(path.join(root,'docs/USER_MANUAL.md'),'utf8').includes('`CFG:CMD:MATERIAL_RUN_BOUNDARY`'));
    });
    test('existing carry-forward does not require a new source just because another row is scanned',async()=>{
        const h=harness();twoMaterials(h);h.state.context.executions[0].material_run_context.material_rules[0].carry_forward_qty=2;
        await h.open();await h.scan('CFG:QTY:MATERIAL:5');await h.scan('B');assert(!h.guides.material_draw_summary.includes('alert-danger'));await h.scan('CFG:CMD:CONFIRM');assert(h.calls.at(-1).method.endsWith('start_scanner_run'));
    });
    test('a pending unassigned quantity binds to an explicitly selected item without leaking to the next source',async()=>{
        const h=harness();twoMaterials(h);await h.open();await h.scan('CFG:QTY:MATERIAL:2');await h.scan('CFG:SELECT:1');await h.scan('CFG:QTY:MATERIAL:5');await h.scan('B');
        assert.equal(h.dialog().cfg_material_sources.A.qty,5);assert.equal(h.dialog().cfg_material_sources.B.qty,0);assert.equal(h.dialog().cfg_pending_material_qty,0);
    });
    test('double confirmation while a source check is pending sends one Start request',async()=>{
        const h=harness();let release;h.respond=async request=>request.method.endsWith('identify_material_run_scan')?new Promise(resolve=>{release=()=>resolve({message:{scan_type:'Material',preview:{...h.materials.TAG,qty:5}}});}):{message:{name:'RUN'}};
        await h.open();await h.scan('CFG:QTY:MATERIAL:5');const tag=h.scan('TAG');const first=h.scan('CFG:CMD:CONFIRM');const second=h.scan('CFG:CMD:CONFIRM');await new Promise(resolve=>setImmediate(resolve));release();await Promise.all([tag,first,second]);
        assert.equal(h.calls.filter(r=>r.method.endsWith('start_scanner_run')).length,1);
    });
    test('a changed operation context discards the old in-flight preview',async()=>{
        const h=harness(2);let release;h.respond=async()=>new Promise(resolve=>{release=()=>resolve({message:{scan_type:'Material',preview:{...h.materials.TAG,qty:0}}});});
        await h.open();await h.scan('CFG:SELECT:1');const tag=h.scan('TAG');await new Promise(resolve=>setImmediate(resolve));await h.dialog().set_value('execution_name','EXEC-1');await h.dialog().cfg_selection_changed('EXEC-1');release();await tag;
        assert.equal(h.dialog().cfg_material_draws.length,0);assert.deepEqual(h.dialog().cfg_material_sources,{});
    });
    test('material choices beyond ten retain explicit scanner selection',async()=>{
        const h=harness();h.state.context.executions[0].material_run_context.material_rules=Array.from({length:12},(_,i)=>({rule_row:'R'+i,item_code:'ITEM-'+i,stock_uom:'Nos'}));
        await h.open();await h.scan('CFG:CMD:NEXT_MATERIALS');await h.scan('CFG:SELECT:2');await h.scan('CFG:QTY:MATERIAL:4');assert.equal(h.dialog().cfg_material_sources.R11.qty,4);assert.equal(h.dialog().cfg_pending_material_qty,0);
    });
    test('a second physical source for one item cannot silently replace its checked source',async()=>{
        const h=harness();h.materials.OTHER={...h.materials.TAG,source_visible_code:'OTHER-TAG'};await h.open();await h.source();await h.scan('CFG:QTY:MATERIAL:2');await assert.rejects(h.scan('OTHER'),/different source/);
        assert.equal(h.dialog().cfg_material_draws[0].scan_value,'TAG');assert.equal(h.dialog().cfg_material_draws[0].qty,5);await h.scan('CFG:CMD:CONFIRM');assert(!h.calls.some(r=>r.method.endsWith('start_scanner_run')));
    });
    test('confirmed Frappe rejection permits corrected quantities and displays its readable message',async()=>{
        const h=harness();await h.open();await h.source();const original=h.respond;
        h.respond=async()=>{throw {exc_type:'ValidationError',_server_messages:JSON.stringify([JSON.stringify({message:'<b>BAG</b> certificate needs correction'})])};};
        await assert.rejects(h.scan('CFG:CMD:CONFIRM'));assert.equal(h.dialog().cfg_material_run_pending_request,null);assert(h.guides.material_draw_summary.includes('BAG certificate needs correction'));
        h.respond=original;await h.scan('CFG:QTY:MATERIAL:4');await h.scan('TAG');await h.scan('CFG:CMD:CONFIRM');assert.equal(JSON.parse(h.calls.at(-1).args.material_draws)[0].qty,4);
    });
    test('an HTTP timeout without explicit Frappe rejection retains the original request',async()=>{
        const h=harness();await h.open();await h.source();h.respond=async()=>{throw {status:408,message:'Proxy timeout'};};await assert.rejects(h.scan('CFG:CMD:CONFIRM'));
        assert(h.dialog().cfg_material_run_pending_request);await h.scan('CFG:QTY:MATERIAL:2');assert.equal(h.dialog().cfg_material_draws[0].qty,5);
    });
    test('a late touch preview does not erase the next unapplied quantity or source code',async()=>{
        const h=harness();let release;h.respond=async()=>new Promise(resolve=>{release=()=>resolve({message:{scan_type:'Material',preview:{...h.materials.TAG,qty:5}}});});
        await h.open();await h.scan('CFG:QTY:MATERIAL:5');await h.dialog().set_value('material_source_scan','TAG');const scan=h.dialog().options.fields.find(f=>f.fieldname==='read_material_source').click();await new Promise(resolve=>setImmediate(resolve));
        await h.dialog().set_value('material_quantity',2);await h.dialog().set_value('material_source_scan','NEXT-TAG');release();await scan;
        assert.equal(h.dialog().get_value('material_quantity'),2);assert.equal(h.dialog().get_value('material_source_scan'),'NEXT-TAG');assert.equal(h.dialog().cfg_material_draws[0].qty,5);
    });
    test('visible code and UUID alias for the same raw source are not mistaken for two sources',async()=>{
        const h=harness();h.materials.TAG.source_handling_unit='HU-TAG';h.materials.ALIAS={...h.materials.TAG};await h.open();await h.source();await h.scan('ALIAS');assert.equal(h.dialog().cfg_material_draws[0].source_handling_unit,'HU-TAG');assert.equal(h.dialog().cfg_material_draws[0].qty,5);
    });
    test('a different Hopper cannot silently replace the selected Hopper input',async()=>{
        const h=harness();h.state.context.executions[0].material_run_context.hopper_mode='Consume Hopper';await h.open();await h.scan('HOPPER_3');await assert.rejects(h.scan('HOPPER_4'),/different Hopper/);assert.equal(h.dialog().cfg_hopper_scan,'HOPPER_3');
    });
    test('the same Hopper with a changed fill requires reload instead of hiding the change',async()=>{
        const h=harness();h.state.context.executions[0].material_run_context.hopper_mode='Consume Hopper';let fill='FIRST';const original=h.respond;
        h.respond=async request=>{const result=await original(request);if(result.message.scan_type==='Hopper')Object.assign(result.message.preview,{handling_unit:'HU-HOPPER',hopper_fill:fill});return result;};
        await h.open();await h.scan('HOPPER_3');fill='SECOND';await assert.rejects(h.scan('HOPPER_3'),/different Hopper or fill/);assert.equal(h.dialog().cfg_hopper_preview.hopper_fill,'FIRST');await h.source();await h.scan('CFG:CMD:CONFIRM');assert(!h.calls.some(r=>r.method.endsWith('start_scanner_run')));assert(h.guides.material_draw_summary.includes('alert-danger'));
    });
    const passed=[];for(const [name,fn] of cases){await fn();passed.push(name);}return passed;
}
module.exports=runTests;
if(require.main===module)runTests().then(results=>console.log(`${results.length} pre-use scanner checks passed`)).catch(error=>{console.error(error);process.exitCode=1;});
