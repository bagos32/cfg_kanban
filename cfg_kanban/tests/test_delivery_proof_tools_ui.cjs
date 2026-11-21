/* Shared native proof-media adapter; all HTTP, GPS and canvas surfaces are offline doubles. */
const test=require('node:test'),assert=require('node:assert/strict');
const tools=require('../public/js/delivery_proof_tools.js');
const wait=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};};
function setup(){
 let token='TOKEN',valid=true,nonce=0;const events=new Map(),nodes=new Map(),calls=[],posts=[],draws=[],pointer=new Map(),opened=[];
 class Node{
  constructor(key=''){this.key=key;if(key==='canvas')this[0]=canvas;}
  find(key){if(!nodes.has(key))nodes.set(key,new Node(key));return nodes.get(key);}html(v){this.markup=v;return this;}text(v){this.caption=v;return this;}
  off(){return this;}on(type,selector,callback){events.set(type+' '+selector,callback);return this;}
  closest(){return this;}data(){return'MEDIA';}
 }
 const ctx={drawImage(...args){draws.push(['image',...args]);},fillRect(){},fillText(text){draws.push(['text',text]);},beginPath(){},moveTo(){},lineTo(){},stroke(){},clearRect(){}};
 const canvas={width:600,height:180,getContext:()=>ctx,getBoundingClientRect:()=>({left:0,top:0,width:600,height:180}),
  addEventListener:(name,fn)=>pointer.set(name,fn),removeEventListener:name=>pointer.delete(name),setPointerCapture(){},toBlob:cb=>cb({size:4})};
 const evidence=new Node(),signature=new Node();
 global.$=value=>value instanceof Node?value:new Node();global.__=v=>v;
 global.FormData=class{constructor(){this.fields=[];}append(...row){this.fields.push(row);}};
 global.File=class{constructor(parts,name,options){this.name=name;this.type=options.type;this.size=4;}};
 Object.defineProperty(globalThis,'navigator',{configurable:true,value:{geolocation:{getCurrentPosition(ok){ok({coords:{latitude:1.5,longitude:2.5,accuracy:6}});}}}});
 global.createImageBitmap=async()=>({width:1000,height:700,close(){}});
 global.document={createElement:()=>canvas};global.open=(...args)=>opened.push(args);
 global.fetch=async(url,options)=>{posts.push({url,options});return{ok:true};};
 const f={utils:{escape_html:v=>String(v).replaceAll('<','&lt;')},call:async({method,args})=>{
  calls.push({method,args});
  if(method.endsWith('get_delivery_proof_camera_stamp'))return{message:{captured_at:'2026-11-21 10:00:00'}};
  if(method.endsWith('create_delivery_proof_upload_url'))return{message:{url:'https://private-s3/upload',method:'POST',fields:{key:'PRIVATE'},media_id:'MEDIA',confirmation_token:'CONFIRM'}};
  if(method.endsWith('create_delivery_proof_view_url'))return{message:{url:'https://private-s3/view'}};
  if(method.endsWith('list_delivery_proof_media'))return{message:[{media_id:'MEDIA',original_filename:'<filename>',evidence_kind:'photo'}]};
  return{message:{}};
 }};
 const binding=tools.bind({frappe:f,proof:{name:'POD',media:[]},field:name=>({$wrapper:name==='evidence'?evidence:signature}),token:()=>token,
  valid:()=>valid,nonce:()=>`UPLOAD${++nonce}`,error:e=>e.message});
 return{binding,f,calls,posts,draws,pointer,nodes,events,opened,token:v=>token=v,valid:v=>valid=v,canvas,Node};
}
test('tablet controls expose camera, file capture and a touch signature canvas',()=>{
 assert.match(tools.evidenceHTML(),/capture="environment"/);assert.match(tools.evidenceHTML(),/multiple/);assert.match(tools.signatureHTML(),/touch-action:none/);
});
test('evidence uses private S3 upload authorization, POST, confirmation then native media readback',async()=>{
 const h=setup();await h.binding.upload([{name:'proof.pdf',type:'application/pdf',size:4}],'attachment');
 assert.equal(h.posts.length,1);assert.equal(h.posts[0].options.method,'POST');
 assert.deepEqual(h.calls.map(c=>c.method.split('.').at(-1)),['create_delivery_proof_upload_url','confirm_delivery_proof_upload','list_delivery_proof_media']);
 assert(h.calls.every(c=>c.args.proof_name==='POD'&&c.args.operator_session_token==='TOKEN'));
 assert.equal(h.calls[0].args.capture_source,'file-upload');assert.equal(h.calls[1].args.confirmation_token,'CONFIRM');
 assert.match(h.nodes.get('.cfg-proof-media').markup,/&lt;filename>/);assert.equal(h.binding.busy(),false);h.binding.close();
});
test('camera photo keeps the actual image and stamps server time, reference and GPS before upload',async()=>{
 const h=setup();await h.binding.upload([{name:'camera.jpg',type:'image/jpeg',size:4}],'photo',true);
 assert.equal(h.calls[0].method.split('.').at(-1),'get_delivery_proof_camera_stamp');
 assert.equal(h.draws[0][0],'image');const text=h.draws.filter(r=>r[0]==='text').map(r=>r[1]).join(' ');
 assert.match(text,/POD.*2026-11-21/);assert.match(text,/GPS 1.500000, 2.500000/);
 const auth=h.calls.find(c=>c.method.endsWith('create_delivery_proof_upload_url')).args;
 assert.equal(auth.evidence_kind,'photo');assert.equal(auth.capture_source,'timestamped-camera');assert.equal(auth.latitude,1.5);h.binding.close();
});
test('S3 failure leaves proof incomplete and never confirms unavailable evidence',async()=>{
 const h=setup();global.fetch=async()=>({ok:false,status:503});await h.binding.upload([{name:'proof',type:'image/jpeg',size:4}],'photo');
 assert.equal(h.calls.filter(c=>c.method.endsWith('confirm_delivery_proof_upload')).length,0);assert.match(h.nodes.get('.cfg-proof-status').caption,/503/);h.binding.close();
});
test('pending evidence is counted as busy and a second upload cannot overtake it',async()=>{
 const h=setup(),d=deferred();global.fetch=()=>d.promise;
 const first=h.binding.upload([{name:'proof',type:'image/jpeg',size:4}],'photo');await wait();assert(h.binding.busy());
 await h.binding.upload([{name:'second',type:'image/jpeg',size:4}],'photo');assert.equal(h.calls.length,1);
 d.resolve({ok:true});await first;assert.equal(h.calls.length,3);assert.equal(h.binding.busy(),false);h.binding.close();
});
test('closing or changing operator before upload authorization returns blocks late binary transfer',async()=>{
 for(const change of ['close','operator']){
  const h=setup(),d=deferred();h.f.call=async request=>{h.calls.push(request);return d.promise;};
  const request=h.binding.upload([{name:'proof',type:'image/jpeg',size:4}],'photo');await wait();
  if(change==='close')h.binding.close();else h.token('OTHER');d.resolve({message:{url:'PRIVATE',method:'POST',fields:{},media_id:'M'}});await request;assert.equal(h.posts.length,0);
 }
});
test('signature remains busy through encoding and upload and uses native signature evidence kind',async()=>{
 const h=setup(),d=deferred();h.canvas.toBlob=cb=>d.promise.then(cb);
 const ev={clientX:2,clientY:4,pointerId:1};h.pointer.get('pointerdown')(ev);h.pointer.get('pointermove')(ev);h.pointer.get('pointerup')();
 h.events.get('click.cfg_proof_tools .cfg-save-signature')();assert(h.binding.busy());d.resolve({size:4});await wait();
 const auth=h.calls.find(c=>c.method.endsWith('create_delivery_proof_upload_url'));assert.equal(auth.args.evidence_kind,'signature');assert.equal(auth.args.capture_source,'signature-pad');assert.equal(h.binding.busy(),false);h.binding.close();
});
test('media view/archive stay on the same proof scope and no presigned URL is retained in metadata',async()=>{
 const h=setup();h.events.get('click.cfg_proof_tools .cfg-view-proof').call(new h.Node());await wait();assert.equal(h.opened.length,1);
 h.events.get('click.cfg_proof_tools .cfg-remove-proof').call(new h.Node());await wait();
 assert(h.calls.every(c=>c.args.proof_name==='POD'));assert(!JSON.stringify(h.calls).includes('private-s3'));h.binding.close();assert.equal(h.pointer.size,0);
});
test('GPS denial gives a recoverable proof error without authorizing a photo upload',async()=>{
 const h=setup();navigator.geolocation.getCurrentPosition=(_ok,fail)=>fail();await h.binding.upload([{name:'camera.jpg',type:'image/jpeg',size:4}],'photo',true);
 assert.equal(h.calls.length,0);assert.match(h.nodes.get('.cfg-proof-status').caption,/Location permission/);h.binding.close();
});
