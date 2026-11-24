/* Shared origin/user-scoped Label Bridge v2 approval. No browser key or ERP credentials in links. */
(function(root,factory){const api=factory(root);if(typeof module==='object'&&module.exports)module.exports=api;else root.cfg_label_bridge_pairing=api;})(typeof window==='undefined'?globalThis:window,function(root){
 'use strict';
 const METHOD='cfg_kanban.services.label_bridge_pairing.pairing';
 const hex=bytes=>Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
 const b64=bytes=>root.btoa(String.fromCharCode(...bytes));
 function keyStore(indexedDB=root.indexedDB){
  let opened=null;
  function database(){if(!indexedDB)throw new Error('Browser approval needs IndexedDB. Use the legacy Browser key on this device.');
   if(!opened)opened=new Promise((resolve,reject)=>{const request=indexedDB.open('cfg_label_bridge_v2',1);
    request.onupgradeneeded=()=>{if(!request.result.objectStoreNames.contains('browsers'))request.result.createObjectStore('browsers',{keyPath:'account'});};
    request.onerror=()=>{opened=null;reject(new Error('Browser key storage is unavailable. Check this browser’s storage settings.'));};
    request.onblocked=()=>{opened=null;reject(new Error('Close another tab that is updating printer pairing.'));};
    request.onsuccess=()=>{const db=request.result;db.onversionchange=()=>{db.close();opened=null;};resolve(db);};});return opened;
  }
  async function change(account,work){const db=await database();return new Promise((resolve,reject)=>{
   const transaction=db.transaction('browsers','readwrite'),store=transaction.objectStore('browsers'),request=store.get(account);let result;
   transaction.oncomplete=()=>resolve(result);transaction.onerror=transaction.onabort=()=>reject(new Error('Browser pairing could not be saved. Start pairing again.'));
   request.onsuccess=()=>{try{result=work(request.result||null,store);}catch(error){transaction.abort();reject(error);}};
  });}
  return {
   async get(account){const db=await database();return new Promise((resolve,reject)=>{const request=db.transaction('browsers','readonly').objectStore('browsers').get(account);request.onsuccess=()=>resolve(request.result||null);request.onerror=()=>reject(new Error('Browser pairing could not be read.'));});},
   put(record){return change(record.account,(_old,store)=>{store.put(record);return true;});},
   update(account,attempt,work){return change(account,(old,store)=>{if(!old||old.attempt!==attempt)return false;const next=work(old);if(next)store.put(next);else store.delete(account);return true;});},
   close(){const pending=opened;opened=null;pending?.then(db=>db.close(),()=>{});},
  };
 }
 function client(options={}){
  const crypto=options.crypto||root.crypto,origin=new URL(options.origin||root.location.origin).origin,user=options.user,
   store=options.store||keyStore(),rpc=options.rpc,now=options.now||(()=>Date.now()),valid=options.valid||(()=>true),
   account=JSON.stringify([origin,user]);
  let generation=0,record=null,verified=false,disposed=false;
  const listeners=new Set();let channel=null;
  try{channel=options.channel===false?null:(options.channel||(root.BroadcastChannel?new root.BroadcastChannel('cfg_label_bridge_v2'):null));}catch(_){channel=null;}
  const supported=()=>origin.startsWith('https://')&&!!crypto?.subtle&&!!(options.store||root.indexedDB)&&(options.channel===false||!!channel)&&typeof user==='string'&&user!==''&&user!=='Guest';
  const active=()=>!disposed&&valid();
  function announce(){channel?.postMessage({account});}
  function clear(){generation++;record=null;verified=false;for(const listener of listeners)listener();}
  if(channel)channel.onmessage=event=>{if(event.data?.account===account)clear();};
  function guard(version){if(!active()||version!==generation)throw new Error('Browser pairing or signed-in ERP user changed.');}
  function requireSupport(){if(!supported())throw new Error('Browser approval needs HTTPS, Web Crypto, IndexedDB, tab messaging and a signed-in ERPNext user. Use the legacy Browser key if necessary.');}
  function context(value){if(!value?.doctype||!value?.name)throw new Error('Choose an authorized printable document before pairing.');return {document_type:value.doctype,document_name:value.name};}
  async function request(action,args,source){return rpc(METHOD,{action,...args,...context(source)});}
  function publicState(value){return value?{kid:value.kid,status:value.status,code:value.code,expires:value.expires}:null;}
  async function validKey(value){const key=value?.privateKey;if(!key||key.type!=='private'||key.extractable||key.algorithm?.name!=='ECDSA'||key.algorithm?.namedCurve!=='P-256'||!key.usages?.includes?.('sign'))return false;
   try{const bytes=Uint8Array.from(root.atob(value.publicKey),c=>c.charCodeAt(0));if(bytes.length!==65||bytes[0]!==4)return false;
    const publicKey=await crypto.subtle.importKey('raw',bytes,{name:'ECDSA',namedCurve:'P-256'},false,['verify']),challenge=crypto.getRandomValues(new Uint8Array(32)),signature=await crypto.subtle.sign({name:'ECDSA',hash:'SHA-256'},key,challenge);
    return crypto.subtle.verify({name:'ECDSA',hash:'SHA-256'},publicKey,signature,challenge);
   }catch(_){return false;}
  }
  async function check(source){requireSupport();verified=false;const version=generation,current=record||await store.get(account);guard(version);
   if(!current||!/^[0-9a-f]{32}$/.test(current.kid||''))return null;
   const latest=await store.get(account);guard(version);if(latest?.attempt!==current.attempt){clear();throw new Error('Another tab changed browser pairing. Review Printer Setup.');}
   const answer=await request('status',{kid:current.kid},source);guard(version);
   if(answer?.kid!==current.kid||!['pending','approved','expired','revoked'].includes(answer.status))throw new Error('Invalid browser approval response. Start pairing again.');
   if(['expired','revoked'].includes(answer.status)){
    await store.update(account,current.attempt,()=>null);guard(version);record=null;generation++;announce();return {...publicState(current),status:answer.status};}
   const updated={...current,status:answer.status};if(!await store.update(account,current.attempt,()=>updated)){clear();throw new Error('Another tab changed browser pairing.');}
   guard(version);record=updated;verified=answer.status==='approved';return publicState(record);
  }
  return {supported,endpoint:origin+'/api/method/'+METHOD,
   state:()=>publicState(record),
   onChange(listener){listeners.add(listener);return ()=>listeners.delete(listener);},
   async begin(source){requireSupport();clear();const version=generation;
    const keys=await crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},false,['sign','verify']);guard(version);
    const publicKey=b64(new Uint8Array(await crypto.subtle.exportKey('raw',keys.publicKey)));guard(version);
    const pending={account,attempt:hex(crypto.getRandomValues(new Uint8Array(16))),privateKey:keys.privateKey,publicKey,status:'pending'};
    await store.put(pending);guard(version);announce();
    const answer=await request('create',{publicKey},source);guard(version);
    if(!/^[0-9a-f]{64}$/.test(answer?.ticket||'')||!/^[0-9a-f]{32}$/.test(answer?.kid||'')||!/^\d{6}$/.test(answer?.code||'')||!Number.isInteger(answer.expiresIn)||answer.expiresIn<1||answer.expiresIn>300)throw new Error('Invalid pairing response. Start again from ERPNext.');
    const next={...pending,kid:answer.kid,code:answer.code,expires:now()+answer.expiresIn*1000};
    if(!await store.update(account,pending.attempt,()=>next)){clear();throw new Error('Another tab started a different pairing request.');}
    guard(version);record=next;
    // Bearer ticket stays only in this return value, never IndexedDB/localStorage.
    return {...publicState(next),uri:'labelbridge://pair?'+new URLSearchParams({v:'2',ticket:answer.ticket})};
   },
   async restore(source){requireSupport();const version=++generation;record=null;verified=false;const saved=await store.get(account);guard(version);if(!saved)return null;
    if(!await validKey(saved)){guard(version);throw new Error('Saved browser pairing is invalid. Pair this browser again.');}
    guard(version);record=saved;return check(source);},
   check,
   activate(signer){if(!active()||!verified||record?.status!=='approved')throw new Error('Approve this browser in Label Bridge first.');const version=generation,kid=record.kid;
    signer.pairBrowser(kid,record.privateKey,()=>active()&&verified&&version===generation&&record?.kid===kid&&record.status==='approved');},
   async unpair(source){requireSupport();const old=record||await store.get(account);clear();
    if(old)await store.update(account,old.attempt,()=>null);announce();
    if(old?.kid){try{const answer=await request('revoke',{kid:old.kid},source);if(answer?.kid!==old.kid||answer.status!=='revoked')throw new Error('Invalid revocation response.');}
     catch(error){throw new Error('Browser key removed here; server revocation could not be confirmed. Remove approved browsers in Label Bridge too. '+(error?.message||'Server request failed.'));}}
   },
   dispose(){clear();disposed=true;channel?.close();if(!options.store)store.close?.();listeners.clear();},
  };
 }
 return {METHOD,keyStore,client};
});
