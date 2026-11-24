const test=require('node:test'),assert=require('node:assert/strict'),{webcrypto:crypto}=require('node:crypto');
const pairing=require('../public/js/label_bridge_pairing.js'),bridge=require('../public/js/mobile_print_bridge.js');
const ui=require('../public/js/driver_mobile_print.js');
const source={doctype:'Delivery Note',name:'DN-ALLOWED'};
function memory(){const rows=new Map();return {rows,async get(key){return structuredClone(rows.get(key)||null);},async put(row){rows.set(row.account,structuredClone(row));},async update(account,attempt,work){const old=await this.get(account);if(!old||old.attempt!==attempt)return false;const next=work(old);if(next)rows.set(account,structuredClone(next));else rows.delete(account);return true;}};}
function fixture(options={}){
 const store=options.store||memory(),calls=[],registrations=new Map();let active=true,reply=null;
 const rpc=async(method,args)=>{assert.equal(method,pairing.METHOD);calls.push(structuredClone(args));if(reply)return reply(args);
  if(args.action==='create'){const kid=Buffer.from(crypto.getRandomValues(new Uint8Array(16))).toString('hex');registrations.set(kid,'pending');return {kid,ticket:'a'.repeat(64),code:'000012',expiresIn:120,status:'pending'};}
  if(args.action==='revoke')registrations.set(args.kid,'revoked');return {kid:args.kid,status:registrations.get(args.kid)||'revoked'};
 };
 const config={crypto,store,origin:'https://erp.example',user:'stock@example.com',rpc,valid:()=>active,channel:false,...options};
 const client=pairing.client(config);
 return {client,store,calls,registrations,config,approve(){for(const kid of registrations.keys())registrations.set(kid,'approved');},reply(fn){reply=fn;},inactive(){active=false;},dispose(){client.dispose();}};
}
test('v2 generates a non-exportable P-256 key and stores no bearer ticket or legacy browser key',async()=>{
 const f=fixture(),request=await f.client.begin(source),row=[...f.store.rows.values()][0];
 assert.equal(row.privateKey.extractable,false);assert.equal(row.privateKey.type,'private');assert.equal(row.privateKey.algorithm.namedCurve,'P-256');
 await assert.rejects(()=>crypto.subtle.exportKey('pkcs8',row.privateKey));
 const raw=Buffer.from(row.publicKey,'base64');assert.equal(raw.length,65);assert.equal(raw[0],4);
 assert.equal(request.code,'000012');const url=new URL(request.uri);assert.equal(url.host,'pair');assert.equal(url.searchParams.size,2);assert.equal(url.searchParams.get('v'),'2');assert.equal(url.searchParams.get('ticket'),'a'.repeat(64));assert(request.uri.length<=256);
 assert(!JSON.stringify([...f.store.rows.values()]).includes('a'.repeat(64)));assert(!f.calls.some(row=>'privateKey' in row||'key' in row));
 assert.deepEqual(Object.keys(f.client.state()).sort(),['code','expires','kid','status']);f.dispose();
});
test('native six-field v2 link verifies exact P-256 SHA-256 raw R/S signature and retains one-copy payload',async()=>{
 const f=fixture();await f.client.begin(source);const signer=bridge.signer(crypto);assert.throws(()=>f.client.activate(signer));f.approve();await f.client.check(source);f.client.activate(signer);
 const payload=bridge.encode(new Uint8Array(20),8,20),first=await signer.prepare(payload),second=await signer.prepare(payload),url=new URL(first.uri);
 assert.equal(signer.version(),2);assert.equal(url.searchParams.size,6);assert.equal(url.searchParams.get('v'),'2');assert.equal(JSON.parse(atob(url.searchParams.get('job'))).copies,1);
 const signature=Buffer.from(url.searchParams.get('sig'),'base64');assert.equal(signature.length,64);
 const row=[...f.store.rows.values()][0],publicKey=await crypto.subtle.importKey('raw',Buffer.from(row.publicKey,'base64'),{name:'ECDSA',namedCurve:'P-256'},false,['verify']);
 const message=['v2',url.searchParams.get('kid'),url.searchParams.get('ts'),url.searchParams.get('nonce'),payload].join('\n');
 assert(await crypto.subtle.verify({name:'ECDSA',hash:'SHA-256'},publicKey,signature,new TextEncoder().encode(message)));
 assert.notEqual(url.searchParams.get('nonce'),new URL(second.uri).searchParams.get('nonce'));assert.equal(signer.current(first),first.uri);assert(!first.uri.includes('stock@example.com'));f.dispose();assert.throws(()=>signer.current(first));
});
test('approved key restores after reload for this origin/user without copying or exporting a key',async()=>{
 const f=fixture();await f.client.begin(source);f.approve();await f.client.check(source);f.dispose();
 const restored=pairing.client(f.config),state=await restored.restore(source),signer=bridge.signer(crypto);assert.equal(state.status,'approved');restored.activate(signer);assert(signer.paired());
 const stored=[...f.store.rows.values()][0];assert.equal(stored.privateKey.extractable,false);assert(!('ticket' in stored));restored.dispose();
});
test('cached approval never activates after session or native print permission revalidation fails',async()=>{
 const f=fixture();await f.client.begin(source);f.approve();await f.client.check(source);const signer=bridge.signer(crypto);f.client.activate(signer);const prepared=await signer.prepare('PAYLOAD');
 f.reply(()=>Promise.reject(new Error('Native session or print permission denied')));await assert.rejects(()=>f.client.check(source),/denied/);assert.equal(signer.paired(),false);assert.throws(()=>signer.current(prepared));assert.throws(()=>f.client.activate(bridge.signer(crypto)));
 f.dispose();const reloaded=pairing.client(f.config);await assert.rejects(()=>reloaded.restore(source),/denied/);assert.throws(()=>reloaded.activate(bridge.signer(crypto)));reloaded.dispose();
});
test('different ERP user or origin cannot restore another account pairing',async()=>{
 const f=fixture();await f.client.begin(source);f.approve();await f.client.check(source);
 for(const change of [{user:'other@example.com'},{origin:'https://another.example'}]){const other=pairing.client({...f.config,...change});assert.equal(await other.restore(source),null);other.dispose();}f.dispose();
});
test('HTTPS signed-in-user and browser-storage capabilities are required for approval, not silently downgraded',async()=>{
 for(const options of [{origin:'http://erp.example'},{user:'Guest'},{crypto:{}}]){const f=fixture(options);assert.equal(f.client.supported(),false);await assert.rejects(()=>f.client.begin(source));assert.equal(f.calls.length,0);f.dispose();}
});
test('blocked tab messaging leaves legacy printing available instead of crashing printer setup',async()=>{
 const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),root={crypto,indexedDB:{},location:{origin:'https://erp.example'},btoa,atob,BroadcastChannel:class{constructor(){throw new Error('Blocked');}}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../public/js/label_bridge_pairing.js'),'utf8'),{window:root,URL,Uint8Array,TextEncoder});
 const client=root.cfg_label_bridge_pairing.client({user:'stock@example.com',rpc:()=>assert.fail('No RPC')});
 assert.equal(client.supported(),false);await assert.rejects(()=>client.begin(source),/legacy Browser key/);client.dispose();
});
test('unpair deletes private key, revokes own registration and invalidates already prepared handoff',async()=>{
 const f=fixture();await f.client.begin(source);f.approve();await f.client.check(source);const signer=bridge.signer(crypto);f.client.activate(signer);const prepared=await signer.prepare('PAYLOAD');
 await f.client.unpair(source);assert.equal(f.store.rows.size,0);assert.equal(f.calls.at(-1).action,'revoke');assert.equal(signer.paired(),false);assert.throws(()=>signer.current(prepared));f.dispose();
});
test('expired/revoked status clears only the matching stored key; approval cannot be invented',async()=>{
 for(const status of ['expired','revoked']){const f=fixture();await f.client.begin(source);f.reply(args=>({kid:args.kid,status}));assert.equal((await f.client.check(source)).status,status);assert.equal(f.store.rows.size,0);assert.throws(()=>f.client.activate(bridge.signer(crypto)));f.dispose();}
 const f=fixture();await f.client.begin(source);f.reply(()=>({kid:'f'.repeat(32),status:'approved'}));await assert.rejects(()=>f.client.check(source),/Invalid/);assert.throws(()=>f.client.activate(bridge.signer(crypto)));f.dispose();
});
test('late create response after operator/page change cannot activate or expose a handoff',async()=>{
 const f=fixture();let finish;f.reply(()=>new Promise(resolve=>finish=resolve));const pending=f.client.begin(source);
 while(!finish)await new Promise(resolve=>setImmediate(resolve));f.inactive();finish({kid:'b'.repeat(32),ticket:'a'.repeat(64),code:'000001',expiresIn:120});
 await assert.rejects(()=>pending,/changed/);assert.throws(()=>f.client.activate(bridge.signer(crypto)));f.dispose();
});
test('failed IndexedDB persistence stops before server registration and does not fall back to a shared key',async()=>{
 const f=fixture({store:{async put(){throw new Error('Quota');}}});await assert.rejects(()=>f.client.begin(source),/Quota/);assert.equal(f.calls.length,0);f.dispose();
});
test('corrupt or exportable saved keys fail restore before contacting server',async()=>{
 const f=fixture();await f.client.begin(source);f.approve();await f.client.check(source);const row=[...f.store.rows.values()][0];
 row.privateKey=(await crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},true,['sign','verify'])).privateKey;await f.store.put(row);f.dispose();
 const client=pairing.client(f.config),count=f.calls.length;await assert.rejects(()=>client.restore(source),/invalid/);assert.equal(f.calls.length,count);client.dispose();
});
test('a stale approval response cannot replace a newer pairing started by another tab',async()=>{
 const f=fixture();await f.client.begin(source);let finish;f.reply(()=>new Promise(resolve=>finish=resolve));const pending=f.client.check(source);
 while(!finish)await new Promise(resolve=>setImmediate(resolve));const other=fixture({store:f.store});const newer=await other.client.begin(source);
 const oldKid=f.client.state().kid;finish({kid:oldKid,status:'approved'});await assert.rejects(()=>pending,/Another tab/);assert.equal([...f.store.rows.values()][0].kid,newer.kid);f.dispose();other.dispose();
});
test('account broadcast invalidates another tab signer without broadcasting keys or tickets',async()=>{
 const channels=[];function channel(){const own={onmessage:null,close(){},postMessage(data){assert.deepEqual(Object.keys(data),['account']);for(const peer of channels)if(peer!==own)peer.onmessage?.({data});}};channels.push(own);return own;}
 const store=memory(),f=fixture({store,channel:channel()});await f.client.begin(source);f.approve();await f.client.check(source);const signer=bridge.signer(crypto);f.client.activate(signer);assert(signer.paired());
 const other=fixture({store,channel:channel()});await other.client.begin(source);assert.equal(signer.paired(),false);f.dispose();other.dispose();
});
test('unpair still removes local private key when server revoke fails',async()=>{
 const f=fixture();await f.client.begin(source);f.reply(()=>Promise.reject(new Error('Session expired')));await assert.rejects(()=>f.client.unpair(source),/Session/);assert.equal(f.store.rows.size,0);f.dispose();
});
test('v2 budget splits dense receipts so worst-case encoded raw signatures stay within bridge limit',()=>{
 const width=576,height=1400,bytes=new Uint8Array(width/8*height);let state=7;for(let i=0;i<bytes.length;i++){state=(state*1664525+1013904223)>>>0;bytes[i]=state>>>24;}
 const frames=bridge.chunks(bytes,width,height);assert(frames.length>1);
 for(const frame of frames){const uri=bridge.link({v:'2',kid:'f'.repeat(32),job:frame.payload,ts:'9999999999',nonce:'f'.repeat(32),sig:'/'.repeat(86)+'=='});assert(uri.length<=48000);}
 assert.deepEqual(Buffer.concat(frames.map(frame=>Buffer.from(frame.bytes))),Buffer.from(bytes));
});
test('new and already-matching print jobs use the v2-safe render without extra work',async()=>{
 const calls=[],frames=[{hash:'NEW-1'},{hash:'NEW-2'}],renderer={async render(...args){calls.push(args);return frames;}};
 assert.deepEqual(await ui.reviewedFrames(renderer,'HTML',{},2,['NEW-1','NEW-2','NEW-1','NEW-2']),[...frames,...frames]);assert.equal(calls.length,1);
});
test('existing v1 print manifest selects only the exact legacy layout, preserving complete copies',async()=>{
 const calls=[],old=[{hash:'OLD-1'},{hash:'OLD-2'}],renderer={async render(_html,_settings,options){calls.push(options);return options?.legacyBudget?old:[{hash:'NEW'}];}};
 const result=await ui.reviewedFrames(renderer,'HTML',{},2,['OLD-1','OLD-2','OLD-1','OLD-2']);
 assert.deepEqual(result,[...old,...old]);assert.equal(calls.length,2);assert.deepEqual(calls[1],{legacyBudget:true});
});
test('unreproducible saved print layout is rejected without inventing a replacement manifest',async()=>{
 await assert.rejects(()=>ui.reviewedFrames({async render(){return [{hash:'DIFFERENT'}];}},'HTML',{},1,['ORIGINAL']),/cannot be reproduced/);
});
test('new pairing scanner commands are dispatched and included in the printable command catalogue',()=>{
 const fs=require('node:fs'),path=require('node:path'),catalogue=fs.readFileSync(path.join(__dirname,'../api/operator.py'),'utf8');
 for(const command of ['PRINT_PAIR','PRINT_OPEN','PRINT_FORGET','PRINT_PAIR_BROWSER','PRINT_PAIR_LEGACY']){assert(ui.commands.includes(command));assert(catalogue.includes('CFG:CMD:'+command));}
});
