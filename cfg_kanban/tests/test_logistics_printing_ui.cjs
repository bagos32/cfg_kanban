/* Offline rendering of frozen certificate printing metadata. */
const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
async function runTests(root=path.resolve(__dirname,'../..')) {
 const panel=fs.readFileSync(path.join(root,'cfg_kanban/cfg_kanban/page/kanban_logistics/kanban_logistics.js'),'utf8');
 const start=panel.indexOf('\tfunction certificate_printing_details_html(');assert(start>=0);
 const tail=panel.slice(start);const next=/\n\t(?:async )?function /.exec(tail);assert(next);
 const escape=value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
 const render=new Function('frappe','__',tail.slice(0,next.index)+'\nreturn certificate_printing_details_html;')({utils:{escape_html:escape}},value=>value);
 const row=evidence=>({stock_identity_snapshot:JSON.stringify({certificate_output_evidence:evidence})});
 const cases=[];const test=(name,fn)=>cases.push([name,fn]);
 test('dispatch shows captured printed date even without a Batch or serial range',()=>{
  const html=render(row([{printed_expiry:'2027-06-01'}]));assert(html.includes('Printed expiry'));assert(html.includes('2027-06-01'));
 });
 test('source serial boundaries are explicitly distinguished from exact membership',()=>{
  const html=render(row([{first_output_serial:'S001',last_output_serial:'S010'}]));
  assert(html.includes('source evidence'));assert(html.includes('S001 – S010'));
 });
 test('partial progress preserves gaps rather than manufacturing one continuous range',()=>{
  const html=render(row([{first_output_serial:'S001',last_output_serial:'S025',progress:[
   {first_output_serial:'S001',last_output_serial:'S005'},{first_output_serial:'S020',last_output_serial:'S025'}]}]));
  assert(html.includes('S001 – S005'));assert(html.includes('S020 – S025'));assert(!html.includes('S001 – S025'));
 });
 test('printed values are escaped before rendering',()=>{
  const html=render(row([{first_output_serial:'<img src=x onerror=alert(1)>',last_output_serial:'END'}]));
  assert(!html.includes('<img'));assert(html.includes('&lt;img'));
 });
 test('old or malformed snapshots do not break the manifest',()=>{
  for(const value of ['', '{bad','null','{}','{"certificate_output_evidence":null}'])assert.equal(render({stock_identity_snapshot:value}),'');
 });
 test('duplicate printing evidence does not repeat the displayed range',()=>{
  const source={printed_expiry:'2027-06-01',first_output_serial:'S001',last_output_serial:'S010'};
  const html=render(row([source,source]));assert.equal(html.split('S001 – S010').length-1,1);
 });
 const passed=[];for(const[name,fn]of cases){await fn();passed.push(name);}return passed;
}
module.exports=runTests;
if(require.main===module)runTests().then(results=>console.log(`${results.length} logistics metadata checks passed`)).catch(error=>{console.error(error);process.exitCode=1;});
