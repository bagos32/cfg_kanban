/* Actual API/SQL payload -> real Logistics renderer; offline doubles, no browser acceptance. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const root = path.resolve(__dirname, '../..');
const python = `import json
from cfg_kanban.tests.test_hopper_inventory import TestHopperInventory
fixture=TestHopperInventory()
fixture.setUp()
try:
 print(json.dumps(fixture.lookup_payload()))
finally:
 fixture.tearDown()
 fixture.doCleanups()
`;
const payload = JSON.parse(execFileSync('python3',['-B','-c',python],{cwd:root,encoding:'utf8',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}}));
const source=fs.readFileSync(path.join(root,'cfg_kanban/cfg_kanban/page/kanban_logistics/kanban_logistics.js'),'utf8');
const render=source.slice(source.indexOf('\tfunction render_lookup()'),source.indexOf('\tfunction render_withdrawal_card('));
function html(lookup) {
    let result='';const panel={html:value=>{result=value;},find:()=>({on(){}})};
    new Function('state','$lookup','frappe','__','format_number','manage_container_dialog',render+'\nrender_lookup();')(
        {lookup},panel,{utils:{escape_html:value=>String(value??'').replace(/[<>&"]/g,char=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[char]))}},value=>value,String,()=>{});
    return result;
}
const rendered=html(payload);
assert(rendered.includes('PRODUCT · Rinse WIP'));
assert(rendered.includes('Cendol WIP'));
assert(rendered.includes('OLD-WO (Closed)'));
assert(rendered.includes('3 Nos'));
assert(rendered.includes('2 / 1 Nos'));
assert(!rendered.includes('Empty Container'));
assert(rendered.includes('Intermediate WIP, separate from ERP-posted stock.'));
const ordinary=structuredClone(payload);delete ordinary.operation_wip;
assert(html(ordinary).includes('Empty Container'));
const escaped=structuredClone(payload);escaped.operation_wip.item_code='<script>';assert(!html(escaped).includes('<script>'));
console.log('3 Hopper lookup renderer checks passed');
