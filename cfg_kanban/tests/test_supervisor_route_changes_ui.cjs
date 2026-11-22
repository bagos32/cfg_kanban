/* Actual Supervisor review lifecycle with DOM/RPC doubles; no live browser claim. */
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const api=require('../public/js/supervisor_route_changes.js');
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};};
const tick=async()=>{for(let i=0;i<5;i++)await new Promise(r=>setTimeout(r,0));};
const supervisor=()=>({employee:'SUP',kanban_role:'Supervisor',view_all_responsibilities:1,permissions:{override:1,complete:1}});
const row={name:'KRC-1',delivery_trip:'TRIP',company:'A',state:'Pending',target_customer:'Shop',requested_by:'DRIVER',reason:'Traffic'};
function harness({token='TOKEN',identity=supervisor(),respond=null}={}){
 const nodes=new Map(),events=new Map(),calls=[],cameras=[],panels=[],data=new Map(),storage={getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v)};if(token)data.set('cfg_kanban_operator_session',token);
 let active=true,busy=0,idle=0,refreshed=0,storageChanged;
 class Node{
  html(v){this.markup=v;return this;}text(v){this.caption=v;return this;}find(key){if(!nodes.has(key))nodes.set(key,new Node());return nodes.get(key);}empty(){this.markup='';return this;}hide(){this.visible=false;return this;}show(){this.visible=true;return this;}
  val(v){if(arguments.length){this.value=v;return this;}return this.value;}on(type,selector,fn){events.set(type+' '+selector,fn);return this;}trigger(){this.focused=true;return this;}one(){return this;}
 }
 global.__=v=>v;global.$=v=>v;global.cfg_driver_route_actions={open:opts=>{const p={opts,closed:0,focus(){},close(){this.closed++;opts.onClose();}};panels.push(p);return p;}};global.addEventListener=(event,fn)=>{if(event==='storage')storageChanged=fn;};
 const f={utils:{escape_html:v=>String(v||'').replaceAll('<','&lt;')},call:async({method,args})=>{calls.push({method,args});return {message:respond?await respond(method,args):method.endsWith('operator_session_status')?identity:method==='frappe.client.get'?row:{session_token:'NEW',operator:identity}};},ui:{Scanner:class{constructor(opts){this.opts=opts;this.dialog={$wrapper:new Node(),hide(){}};cameras.push(this);}stop_scan(){this.stopped=true;}}}};
 const h=api.bind({frappe:f,host:new Node(),storage,locks:{},nonce:()=> 'ID',active:()=>active,error:e=>e.message,refresh:async()=>{refreshed++;},onBusy:()=>busy++,onIdle:()=>idle++});h.update([row]);
 return{h,nodes,events,calls,cameras,panels,data,storage,busy:()=>busy,idle:()=>idle,refreshed:()=>refreshed,active:v=>active=v,changeStorage:()=>storageChanged({key:'cfg_kanban_operator_session'})};
}
test('Supervisor review requires all role and permission flags',()=>{
 assert(api.authorized(supervisor()));for(const change of [{kanban_role:'Operator'},{view_all_responsibilities:0},{permissions:{complete:1}},{permissions:{override:1}}])assert(!api.authorized({...supervisor(),...change}));
});
test('opening review explicitly checks identity once and suspends background refresh',async()=>{
 const h=harness();assert.equal(h.calls.length,0);await h.h.select(row);assert.equal(h.busy(),1);assert(h.h.busy());assert.equal(h.calls.length,1);assert.equal(h.calls[0].method,'cfg_kanban.api.operator.operator_session_status');
 assert.equal(h.panels[0].opts.trip,'TRIP');assert.equal(h.panels[0].opts.outcome,'KRC-1');assert.equal(h.panels[0].opts.operation,'Review Route Change');
 h.h.update([{...row,state:'Approved'}]);assert.equal(h.panels[0].closed,0);await h.panels[0].opts.refresh();assert.equal(h.refreshed(),1);
 h.panels[0].close();assert(!h.h.busy());assert(h.idle()>0);
});
test('normal operator must identify a Supervisor and camera login extracts operator credential',async()=>{
 const h=harness({token:null});await h.h.select(row);assert.equal(h.panels.length,0);assert(h.nodes.get('.cfg-route-review-login').visible);
 h.events.get('click.cfg_route_review .cfg-route-camera')();h.cameras[0].opts.on_scan({decodedText:'https://erp/app/kanban-operator#operator=SUPSECRET'});await tick();
 assert.equal(h.calls[0].args.token,'SUPSECRET');assert.equal(h.data.get('cfg_kanban_operator_session'),'NEW');assert.equal(h.panels.length,1);assert(h.cameras[0].stopped);
});
test('Enter and Tab login use the same credential path and prevent double submission',async()=>{
 const d=deferred(),h=harness({token:null,respond:()=>d.promise});await h.h.select(row);const input=h.nodes.get('.cfg-route-credential');input.val('SUP');let prevented=0;
 for(const key of ['Enter','Tab'])h.events.get('keydown.cfg_route_review .cfg-route-credential')({key,preventDefault(){prevented++;},stopPropagation(){}});
 assert.equal(h.calls.length,1);d.resolve({session_token:'NEW',operator:supervisor()});await tick();assert.equal(h.panels.length,1);assert.equal(prevented,2);
});
test('late identity check after page hide cannot open an action',async()=>{
 const d=deferred(),h=harness({respond:()=>d.promise});const work=h.h.select(row);h.h.hide();d.resolve(supervisor());await work;assert.equal(h.panels.length,0);assert(!h.h.busy());
});
test('operator replacement closes active review and invalidates its credentials',async()=>{
 const h=harness();await h.h.select(row);const panel=h.panels[0];h.data.set('cfg_kanban_operator_session','OTHER');assert.equal(panel.opts.token(),null);h.changeStorage();assert.equal(panel.closed,1);assert(!h.h.busy());
});
test('lookup of older decision uses native permission-aware document reader and can recover unknown action',async()=>{
 const h=harness();await h.h.openName('KRC-OLDER');assert.equal(h.calls[0].method,'frappe.client.get');assert.equal(h.calls[0].args.doctype,'CFG Kanban Route Change Request');assert.equal(h.panels[0].opts.outcome,'KRC-1');
});
test('a camera result after safe Close is ignored',async()=>{
 const h=harness({token:null});await h.h.select(row);h.events.get('click.cfg_route_review .cfg-route-camera')();h.h.close();h.cameras[0].opts.on_scan({decodedText:'LATE'});await tick();assert.equal(h.calls.length,0);assert(h.cameras[0].stopped);
});
test('Supervisor Centre pauses its actual timer during review and restores it on close',async()=>{
 let panelOptions,panelBusy=false,loads=0,route=['kanban-supervisor'],timer=null,cleared=0;
 class Node{appendTo(){return this;}empty(){return this;}append(){return this;}html(){return this;}find(){return this;}on(){return this;}}
 const centre={busy:()=>panelBusy,update(){},show(){},hide(){panelBusy=false;panelOptions.onIdle();},openName(){}};
 const f={pages:{'kanban-supervisor':{}},ui:{make_app_page:()=>({main:{},add_field:()=>({get_value:()=>''}),set_primary_action(){},add_inner_button(){}})},
  require:async()=>{},get_route:()=>route,call:async()=>{loads++;return{message:{counts:{}}};},utils:{escape_html:v=>String(v||'')},router:{on(){}}};
 const context={frappe:f,$:()=>new Node(),__:v=>v,window:{cfg_supervisor_route_changes:{bind:o=>{panelOptions=o;return centre;}}},localStorage:{},navigator:{locks:{}},crypto:{randomUUID:()=> 'ID'},format_number:v=>v,
  setTimeout:fn=>{timer=fn;return 1;},clearTimeout:()=>{timer=null;cleared++;}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../cfg_kanban/page/kanban_supervisor/kanban_supervisor.js'),'utf8'),context);f.pages['kanban-supervisor'].on_page_load({});await tick();assert.equal(loads,1);assert(timer);
 panelBusy=true;panelOptions.onBusy();assert.equal(timer,null);await panelOptions.refresh();assert.equal(loads,2);assert.equal(timer,null);
 panelBusy=false;panelOptions.onIdle();assert(timer);route=['another'];f.pages['kanban-supervisor'].on_page_hide();assert.equal(timer,null);assert(cleared>0);
});
