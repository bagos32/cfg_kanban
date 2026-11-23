const test=require('node:test'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const bridge=require('../public/js/mobile_print_bridge.js'),ui=require('../public/js/driver_mobile_print.js');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function keyFixture(){const handlers={},attributes={};const input={value:'AUTOFILLED',type:'password',style:{},setAttribute:(k,v)=>attributes[k]=v,addEventListener:(type,fn)=>handlers[type]=fn};const entry=ui.pairingEntry();entry.bind(input,'TEST');return {input,entry,attributes,fire:(type,event={})=>handlers[type]?.(event)};}
test('pairing input is non-login, masked, initially empty and marked against autofill',()=>{
 const f=keyFixture();assert.equal(f.input.type,'text');assert.equal(f.input.style.webkitTextSecurity,'disc');assert.equal(f.input.value,'');
 assert.equal(f.attributes.autocomplete,'off');assert.equal(f.attributes.spellcheck,'false');assert.equal(f.attributes.autocapitalize,'none');assert.equal(f.attributes['data-lpignore'],'true');assert(f.attributes.name.startsWith('cfg_bridge_entry_'));
});
test('unnoticed valid-shaped autofill is rejected and cleared without returning the key',()=>{
 const f=keyFixture();f.input.value='a'.repeat(32);f.fire('input',{isTrusted:true,inputType:'insertReplacementText'});
 assert.throws(()=>f.entry.take(),/autofill/);assert.equal(f.input.value,'');
 f.fire('keydown',{isTrusted:false,key:'a'});f.input.value='a'.repeat(32);f.fire('input');assert.throws(()=>f.entry.take(),/autofill/);
});
test('manual paste typing mobile composition and scanner routes approve only the entered value',()=>{
 for(const kind of ['paste','keydown','beforeinput','scanner']){
  const f=keyFixture(),key='0'.repeat(32);
  f.fire(kind,{isTrusted:true,key:'0',inputType:'insertCompositionText'});f.input.value=' '+key+' ';f.fire('input');if(kind==='scanner')f.entry.scanned();
  assert.equal(f.entry.take(),key);assert.equal(f.input.value,'');assert.throws(()=>f.entry.take(),/autofill/);
 }
});
test('autofill replacement after manual entry and stale keyboard intent cannot authorize pairing',()=>{
 const f=keyFixture();f.fire('paste',{isTrusted:true});f.input.value='0'.repeat(32);f.fire('input');f.input.value='1'.repeat(32);f.fire('input');assert.throws(()=>f.entry.take(),/autofill/);
 for(const type of ['keyup','blur']){f.fire('keydown',{isTrusted:true,key:'a'});f.fire(type);f.input.value='1'.repeat(32);f.fire('input');assert.throws(()=>f.entry.take(),/autofill/);}
 f.fire('keydown',{isTrusted:true,key:'c',ctrlKey:true});f.input.value='1'.repeat(32);f.fire('input');assert.throws(()=>f.entry.take(),/autofill/);
});
test('redraw and explicit clearing discard any pending raw pairing key',()=>{
 const f=keyFixture();f.input.value='0'.repeat(32);f.entry.scanned();f.entry.clear();assert.equal(f.input.value,'');assert.throws(()=>f.entry.take(),/autofill/);
});
test('queued print clicks retain their action when the browser event target changes',async()=>{
 const source=fs.readFileSync(path.join(__dirname,'../public/js/driver_mobile_print.js'),'utf8');
 const binding=source.split('\n').find(line=>line.includes("host.on('click.cfg_mobile','[data-mobile]'"));
 for(const name of ['confirm','resume','abandon','setup','close']){
  let handler,queued,called,prevented=false;
  const node={action:name},event={currentTarget:node,preventDefault:()=>prevented=true};
  vm.runInNewContext(binding,{host:{on:(_event,_selector,fn)=>handler=fn},queue:fn=>queued=fn,
   command:(action,target)=>called={action,target},$:target=>({attr:()=>target?.action})});
  handler(event);event.currentTarget=null;await queued();
  assert.equal(called.action,name);assert.equal(called.target,node);assert(prevented);
 }
});
function unpack(payload){const data=JSON.parse(atob(payload)),raw=Uint8Array.from(Buffer.from(data.raster,'base64'));if(!data.packing)return {...data,bytes:raw};const out=[];for(let at=0;at<raw.length;){const code=raw[at++],n=(code&127)+1;if(code&128){const value=raw[at++];for(let k=0;k<n;k++)out.push(value);}else for(let k=0;k<n;k++)out.push(raw[at++]);}return {...data,bytes:new Uint8Array(out)};}
test('raster uses alpha-on-white, luminance and MSB-first bytes',()=>{
 const rgba=new Uint8ClampedArray(8*4);for(let n=0;n<8;n++)rgba.set([255,255,255,255],n*4);
 rgba.set([0,0,0,255],0);rgba.set([0,0,0,0],4);rgba.set([0,0,0,255],7*4);
 assert.deepEqual([...bridge.raster(rgba,8,1)],[129]);
});
test('RLE handles boundaries and remains exactly compatible with the supplied decoder protocol',()=>{
 for(const n of [1,2,3,127,128,129,1024]){const bytes=Uint8Array.from({length:n},(_,i)=>i<140?7:(i*71)%256),width=8,payload=bridge.encode(bytes,width,n);
  const decoded=unpack(payload);assert.deepEqual(decoded.bytes,bytes);assert.equal(decoded.copies,1);assert.equal(decoded.v,1);}
});
test('dense long receipts are split to both height and URI limits without losing a raster byte',()=>{
 const width=576,height=8500,raw=new Uint8Array(width/8*height);let state=17;for(let n=0;n<raw.length;n++){state=(state*1664525+1013904223)>>>0;raw[n]=state>>>24;}
 const chunks=bridge.chunks(raw,width,height);assert(chunks.length>3);
 for(const piece of chunks){assert(piece.height<=4096);assert(bridge.fits(piece.payload));assert.deepEqual(unpack(piece.payload).bytes,piece.bytes);}
 assert.deepEqual(Buffer.concat(chunks.map(c=>Buffer.from(c.bytes))),Buffer.from(raw));
});
test('safe row boundaries are preferred without dropping the tail',()=>{
 const raw=new Uint8Array(8/8*5000),frames=bridge.chunks(raw,8,5000,[4000]);
 assert.equal(frames[0].height,4000);assert.equal(frames[1].height,1000);
});
test('invalid raster geometry, length and oversize URI fail closed',()=>{
 for(const args of [[7,1],[2056,1],[8,0],[8,4097]])assert.throws(()=>bridge.encode(new Uint8Array(1),...args));
 assert.throws(()=>bridge.encode(new Uint8Array(2),8,1));assert.throws(()=>bridge.link({job:'x'.repeat(48000)}));
});
test('HMAC signs the exact v1 string with UTF-8 key text and never includes the secret in the URI',async()=>{
 const key='0123456789abcdef0123456789abcdef',now=1700000000000;
 const fake={subtle:crypto.webcrypto.subtle,getRandomValues:array=>array.fill(10)};
 const signer=bridge.signer(fake,()=>now);await signer.pair(key);
 const payload=bridge.encode(new Uint8Array(20),8,20),prepared=await signer.prepare(payload),url=new URL(prepared.uri);
 const message='v1\n1700000000\n'+'0a'.repeat(16)+'\n'+payload;
 const signature=crypto.createHmac('sha256',Buffer.from(key,'utf8')).update(message).digest('base64');
 assert.equal(url.searchParams.get('sig'),signature);assert.equal(url.searchParams.get('job'),payload);
 assert(!prepared.uri.includes(key));assert(!url.searchParams.has('key'));assert.equal(signer.current(prepared),prepared.uri);
});
test('expired links, invalid keys and forgotten pairings cannot hand off',async()=>{
 let now=0;const signer=bridge.signer(crypto.webcrypto,()=>now);
 await assert.rejects(()=>signer.pair('BAD'));await assert.rejects(()=>signer.prepare('PAYLOAD'));
 await signer.pair('0'.repeat(32));const first=await signer.prepare('PAYLOAD');now=81000;assert.throws(()=>signer.current(first));
 now=0;signer.forget();assert.throws(()=>signer.current(first));await signer.pair('1'.repeat(32));assert.throws(()=>signer.current(first));
});
test('forgetting while key import or signing is pending invalidates its completion',async()=>{
 let done;const cryptoMock={subtle:{importKey:()=>new Promise(resolve=>done=resolve)}};
 const signer=bridge.signer(cryptoMock);const pending=signer.pair('0'.repeat(32));signer.forget();done({});await assert.rejects(()=>pending);assert.equal(signer.paired(),false);
});
test('saved settings are isolated by site/company and omit all secrets and unknown fields',()=>{
 const data=new Map(),storage={getItem:k=>data.get(k),setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)},defaults={dpi:203,printable_width:576,paper_width_mm:80};
 const prefs=bridge.preferences(storage,'https://site','A');prefs.save({...defaults,alias:'Van 1',formats:{'Sales Invoice':'Custom80'},signing_key:'SECRET',token:'CREDENTIAL'});
 assert(![...data.values()][0].includes('SECRET'));assert(![...data.values()][0].includes('CREDENTIAL'));
 assert.equal(prefs.load(defaults).formats['Sales Invoice'],'Custom80');
 assert.equal(bridge.preferences(storage,'https://site','B').load(defaults).alias,'');prefs.reset();assert.equal(data.size,0);
 assert.throws(()=>prefs.save({...defaults,printable_width:577}));assert.throws(()=>prefs.save({...defaults,paper_width_mm:40}));
});
test('resource access allows native/private assets and QR data but rejects external or script URLs',()=>{
 assert.equal(bridge.resource('/private/files/qr.png','https://erp.example'),'https://erp.example/private/files/qr.png');
 assert.equal(bridge.resource('data:image/png;base64,AA==','https://erp.example'),'data:image/png;base64,AA==');
 for(const value of ['javascript:alert(1)','https://elsewhere.example/image.png','file:///tmp/key'])assert.throws(()=>bridge.resource(value,'https://erp.example'));
});
test('whole copies are collated as page1 page2 page1 page2 and unknown pages remain current',()=>{
 const pages=[{hash:'a'},{hash:'b'}],frames=ui.copies(pages,2);assert.deepEqual(frames.map(f=>f.hash),['a','b','a','b']);
 assert.equal(ui.nextPage({segments:{pages:{1:{status:'Outcome Unknown'}}}},frames),1);
 assert.equal(ui.nextPage({segments:{pages:{1:{status:'Operator Confirmed'}}}},frames),2);
});
test('recipient and office progress respect complete copy boundaries',()=>{
 const frames=ui.copies([{hash:'a'},{hash:'b'}],2),job={copies:2,document_type:'Delivery Note',segments:{pages:{}}};
 assert.deepEqual(ui.copyProgress(job,frames),{page:1,copy:1,part:1,parts:2,count:2,label:'Recipient copy'});
 job.segments.pages[1]={status:'Operator Confirmed'};
 assert.equal(ui.copyProgress(job,frames).part,2);
 job.segments.pages[2]={status:'Outcome Unknown'};
 assert.equal(ui.copyProgress(job,frames).copy,1);
 job.segments.pages[2]={status:'Operator Confirmed'};
 assert.deepEqual(ui.copyProgress(job,frames),{page:3,copy:2,part:1,parts:2,count:2,label:'Office copy'});
 for(const n of [3,4])job.segments.pages[n]={status:'Operator Confirmed'};
 assert.equal(ui.copyProgress(job,frames),null);
 assert.throws(()=>ui.copyProgress({copies:3,segments:{}},frames),/invalid/);
 assert.equal(ui.copyProgress({copies:2,document_type:'CFG Kanban Handling Unit',segments:{}},frames).label,'Copy 1');
});
test('normal printing opens the exact native format and never invokes invoice or credit creation',()=>{
 const href=ui.nativeLink({doctype:'Sales Invoice',name:'INV & 1'},'Custom Format / 80',true),params=new URL(href,'https://erp.example').searchParams;
 assert.equal(params.get('name'),'INV & 1');assert.equal(params.get('format'),'Custom Format / 80');assert.equal(params.get('no_letterhead'),'1');
});
test('unfinished jobs separate resumable ownership from office recovery and escape metadata',()=>{
 const escape=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
 const html=ui.unfinishedJobs([
  {name:'OWN',document_name:'DN',status:'Prepared',operator:'DRIVER',delivery_trip:'TRIP',stop_key:'STOP',can_resume:true},
  {name:'OLD / 1',document_name:'<script>bad</script>',operator:'OTHER',delivery_trip:'OLD',can_resume:false}
 ],escape);
 assert(html.includes('data-job="OWN"'));assert(html.includes('Resume / Review'));
 assert(!html.includes('data-job="OLD / 1"'));assert(html.includes('/app/cfg-kanban-mobile-print-job/OLD%20%2F%201'));
 assert(html.includes('Office Recovery'));assert(html.includes('OTHER'));assert(!html.includes('<script>'));
 assert.equal(ui.unfinishedJobs([],escape),'');
});
function officeFixture(status='Prepared',allowed=true){
 let handlers,button,prompt,intro,calls=[],reloaded=0,dirty=false;
 const f={utils:{escape_html:value=>String(value).replaceAll('<','&lt;')},ui:{form:{on:(_name,value)=>handlers=value}},prompt:(fields,callback)=>{prompt={fields,callback};},
  call:async value=>{calls.push(value);},msgprint:message=>calls.push(message)};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../cfg_kanban/doctype/cfg_kanban_mobile_print_job/cfg_kanban_mobile_print_job.js'),'utf8'),{frappe:f,__:(s)=>s});
 const frm={doc:{name:'JOB',status,modified:'VERSION',segments_json:JSON.stringify({pages:{1:{status:'Operator Confirmed'},2:{status:'Outcome Unknown <check>'}}}),__onload:{can_close_mobile_print_job:allowed}},
  is_new:()=>false,is_dirty:()=>dirty,set_intro:value=>intro=value,add_custom_button:(label,callback)=>button={label,callback},
  reload_doc:async()=>reloaded++};
 handlers.refresh(frm);
 return {button:()=>button,prompt:()=>prompt,intro:()=>intro,calls,dirty:()=>dirty=true,reloads:()=>reloaded,f};
}
test('normal print-job form limits closure controls to authorized unfinished jobs',()=>{
 for(const state of ['Operator Confirmed','Abandoned'])assert.equal(officeFixture(state).button(),undefined);
 assert.equal(officeFixture('Prepared',false).button(),undefined);
 for(const state of ['Prepared','Awaiting Confirmation']){
  const fixture=officeFixture(state);assert.equal(fixture.button().label,'Close Unfinished Job');
  assert(fixture.intro().includes('Segment 1: Operator Confirmed'));
  assert(fixture.intro().includes('Segment 2: Outcome Unknown &lt;check>'));
  fixture.button().callback();assert.equal(fixture.prompt().fields[0].reqd,1);
 }
});
test('office closure submits exact job version and reason, then reloads after success',async()=>{
 const fixture=officeFixture();fixture.button().callback();await fixture.prompt().callback({reason:'Checked the physical receipt'});
 assert.equal(fixture.calls[0].method,'cfg_kanban.services.mobile_printing.close_mobile_print_job');
 assert.deepEqual(JSON.parse(JSON.stringify(fixture.calls[0].args)),{print_job:'JOB',reason:'Checked the physical receipt',expected_modified:'VERSION'});
 assert.equal(fixture.reloads(),1);
 const failed=officeFixture();failed.f.call=async()=>{throw new Error('Print job changed');};failed.button().callback();
 await assert.rejects(()=>failed.prompt().callback({reason:'Reviewed'}),/changed/);assert.equal(failed.reloads(),0);
 const dirty=officeFixture();dirty.dirty();dirty.button().callback();assert.equal(dirty.prompt(),undefined);
});
