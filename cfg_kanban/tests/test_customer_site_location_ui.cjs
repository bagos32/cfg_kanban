/* Normal Site form boot and delayed asset ownership checks, using the actual form script. */
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../public/js/cfg_kanban_customer_scan_point.js'),'utf8');
const flush=async()=>{for(let n=0;n<15;n++)await Promise.resolve();};
function harness(){let handlers,resolve,reject;const ready=new Promise((a,b)=>{resolve=a;reject=b;}),installed=[],buttons=[],requests=[];let text='';
 const window={},f={ui:{form:{on:(dt,value)=>handlers=value}},require:asset=>{requests.push(asset);return ready;}};
 const frm={doc:{name:'SITE1'},fields_dict:{delivery_pin_tools:{$wrapper:{text:value=>text=value}}},is_new:()=>true,add_custom_button:value=>buttons.push(value)};
 vm.runInNewContext(source,{frappe:f,window,__:value=>value});return{handlers,frm,window,resolve,reject,installed,buttons,requests,text:()=>text};}
test('new Customer Site gets inline pin tools without opening a popup or automatically saving',async()=>{
 const h=harness();h.handlers.refresh(h.frm);assert.deepEqual(h.requests,['/assets/cfg_kanban/js/delivery_maps.js']);assert.equal(h.buttons.length,0);
 h.window.cfg_delivery_maps={pinTools:frm=>h.installed.push(frm.doc.name)};h.resolve();await flush();assert.deepEqual(h.installed,['SITE1']);
 h.handlers.delivery_location(h.frm);await flush();assert.equal(h.requests.length,1);assert.equal(h.installed.length,2);
});
test('late success/failure from a previous Site cannot replace the new Site pin editor',async()=>{
 for(const fail of [false,true]){const h=harness();h.handlers.refresh(h.frm);h.frm.doc={name:'SITE2'};h.window.cfg_delivery_maps={pinTools:frm=>h.installed.push(frm.doc.name)};
  if(fail)h.reject(new Error('Offline'));else h.resolve();await flush();assert.equal(h.installed.length,0);assert.equal(h.text(),'');}
});
