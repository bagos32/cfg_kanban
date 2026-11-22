const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const api=require('../public/js/map_defaults.js'),maps=require('../public/js/delivery_maps.js');
test('KL defaults retain native tile provider/options and do not mutate frozen shared coordinates',()=>{
 const f={utils:{map_defaults:{center:[19,72],zoom:8,tiles:'native/{z}',options:{attribution:'Native'},imagePath:'local'}}},options=f.utils.map_defaults.options;
 const result=api.apply(f);assert.deepEqual(result,{center:[3.139,101.6869],zoom:13});assert.equal(f.utils.map_defaults.tiles,'native/{z}');assert.equal(f.utils.map_defaults.options,options);assert.equal(f.utils.map_defaults.imagePath,'local');
 result.center[0]=0;assert.equal(api.center[0],3.139);assert.deepEqual(maps.readPoint(maps.pointJSON(-4,110)),{latitude:-4,longitude:110});
});
test('existing Desk native maps receive KL defaults at boot/app-ready/navigation, saved pins remain native values',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../public/js/map_defaults.js'),'utf8'),events=new Map();
 const window={document:{readyState:'loading',addEventListener:(name,fn)=>events.set(name,fn)},$:()=>({on:(name,fn)=>events.set(name,fn)}),frappe:{utils:{map_defaults:{center:[19,72],zoom:8}},router:{on:(name,fn)=>events.set(name,fn)}}};
 vm.runInNewContext(source,{window});assert.equal(window.frappe.utils.map_defaults.center[0],3.139);
 window.frappe.utils.map_defaults.center=[1,1];events.get('app_ready.cfg_map_defaults')();assert.equal(window.frappe.utils.map_defaults.center[1],101.6869);assert(events.has('DOMContentLoaded'));assert(events.has('change'));
});
