/* Label Bridge v1 compatibility. No key persistence, printer ACK, or automatic resend. */
(function(root,factory){const api=factory(root);if(typeof module==='object'&&module.exports)module.exports=api;else root.cfg_mobile_print_bridge=api;})(typeof window==='undefined'?globalThis:window,function(root){
 'use strict';
 const MAX_URI=48000;
 function bytes64(bytes){let out='';for(let i=0;i<bytes.length;i+=8192)out+=String.fromCharCode(...bytes.subarray(i,i+8192));return root.btoa(out);}
 function rle(bytes){const out=[];const run=at=>{let n=1;while(n<128&&at+n<bytes.length&&bytes[at+n]===bytes[at])n++;return n;};
  for(let at=0;at<bytes.length;){const n=run(at);if(n>=3){out.push(128|(n-1),bytes[at]);at+=n;}else{const start=at++;while(at<bytes.length&&at-start<128&&run(at)<3)at++;out.push(at-start-1,...bytes.subarray(start,at));}}return new Uint8Array(out);}
 function dimensions(width,height){if(!Number.isInteger(width)||width<8||width>2048||width%8||!Number.isInteger(height)||height<1||height>4096)throw new Error('Label Bridge requires 8–2048 dots, width divisible by 8, and 1–4096 rows.');}
 function raster(rgba,width,height){dimensions(width,height);if(rgba.length!==width*height*4)throw new Error('Invalid canvas pixels.');const out=new Uint8Array(width/8*height);
  for(let p=0;p<width*height;p++){const at=p*4,a=rgba[at+3]/255,gray=.2126*rgba[at]+.7152*rgba[at+1]+.0722*rgba[at+2];if(gray*a+255*(1-a)<128)out[p>>3]|=128>>(p&7);}return out;}
 function encode(bytes,width,height){dimensions(width,height);if(bytes.length!==width/8*height)throw new Error('Invalid raster length.');const packed=rle(bytes),use=packed.length<bytes.length;
  return root.btoa(JSON.stringify({v:1,width,height,copies:1,raster:bytes64(use?packed:bytes),...(use?{packing:'rle'}:{})}));}
 function link(fields){const uri='labelbridge://print?'+new URLSearchParams(fields);if(uri.length>MAX_URI)throw new Error('This segment is larger than Label Bridge permits.');return uri;}
 function fits(payload){try{return link({job:payload,ts:'9999999999',nonce:'f'.repeat(32),sig:'/+'.repeat(22)+'=='}).length<=MAX_URI-80;}catch(_){return false;}}
 function chunks(bytes,width,height,breaks=[]){if(width%8||bytes.length!==width/8*height)throw new Error('Invalid receipt raster.');const stride=width/8,out=[];let start=0;
  while(start<height){let low=1,high=Math.min(4096,height-start),best=0;while(low<=high){const n=Math.floor((low+high)/2);if(fits(encode(bytes.subarray(start*stride,(start+n)*stride),width,n))){best=n;low=n+1;}else high=n-1;}
   if(!best)throw new Error('One raster row exceeds the bridge limit.');
   if(start+best<height){const safe=breaks.filter(y=>y>start+best*.7&&y<=start+best);if(safe.length)best=Math.max(...safe)-start;}
   const raw=bytes.slice(start*stride,(start+best)*stride);out.push({width,height:best,payload:encode(raw,width,best),bytes:raw,start});start+=best;
  }return out;
 }
 async function digest(bytes,crypto=root.crypto){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(v=>v.toString(16).padStart(2,'0')).join('');}
 function signer(crypto=root.crypto,now=()=>Date.now()){
  let key=null,generation=0;
  return {forget(){generation++;key=null;},paired:()=>!!key,
   async pair(text){const current=++generation;key=null;if(!/^[0-9a-f]{32}$/.test(text))throw new Error('Enter the companion app’s 32-character lowercase hexadecimal signing key.');
    if(!crypto?.subtle)throw new Error('Direct printing requires HTTPS and Web Crypto.');
    // Protocol uses the UTF-8 text of the hex key, not decoded hex bytes.
    const imported=await crypto.subtle.importKey('raw',new TextEncoder().encode(text),{name:'HMAC',hash:'SHA-256'},false,['sign']);
    if(current!==generation)throw new Error('Printer pairing was cleared.');key=imported;},
   async prepare(payload){if(!key)throw new Error('Pair the signing key for this tab first.');const current=generation,ts=String(Math.floor(now()/1000)),nonce=Array.from(crypto.getRandomValues(new Uint8Array(16))).map(v=>v.toString(16).padStart(2,'0')).join('');
    const signature=await crypto.subtle.sign('HMAC',key,new TextEncoder().encode('v1\n'+ts+'\n'+nonce+'\n'+payload));
    if(current!==generation)throw new Error('Printer pairing changed.');return {uri:link({job:payload,ts,nonce,sig:bytes64(new Uint8Array(signature))}),created:now(),generation:current};},
   current(prepared){if(!key||!prepared||prepared.generation!==generation||now()-prepared.created<0||now()-prepared.created>80000)throw new Error('Prepare a fresh Label Bridge handoff.');return prepared.uri;},
  };
 }
 function preferences(storage,site,company){const key='cfg_mobile_printer:'+site+':'+company;
  function validate(value){const dpi=Number(value.dpi),width=Number(value.printable_width),paper=Number(value.paper_width_mm);
   if(!Number.isInteger(width)||width<128||width>2048||width%8||!Number.isInteger(dpi)||dpi<100||dpi>600||!Number.isFinite(paper)||paper<20||paper>120||width/dpi*25.4>paper+.5)throw new Error('Check paper width, printable dot width and DPI.');
   const formats=Object.fromEntries(Object.entries(value.formats||{}).filter(([k,v])=>typeof k==='string'&&typeof v==='string'));
   return {v:1,alias:String(value.alias||'').slice(0,100),paper_width_mm:paper,printable_width:width,dpi,formats};}
  return {load(defaults){const raw=storage.getItem(key);if(!raw)return validate({...defaults,formats:{}});try{return validate(JSON.parse(raw));}catch(_){throw new Error('Saved printer settings are invalid. Reset this device’s printer setup.');}},
   save(value){const safe=validate(value);storage.setItem(key,JSON.stringify(safe));return safe;},reset(){storage.removeItem(key);},validate};
 }
 function resource(value,origin){if(/^data:image\/(png|jpeg|gif|webp|svg\+xml)[;,]/i.test(value))return value;
  const url=new URL(value,origin);if(url.origin!==new URL(origin).origin||!['http:','https:'].includes(url.protocol))throw new Error('Direct print cannot read an external image/font. Use normal ERPNext print or a same-origin Print Format asset.');return url.href;}
 function framePolicy(origin){const site=new URL(origin);if(!['http:','https:'].includes(site.protocol)||site.origin==='null')throw new Error('Print preview requires an HTTP(S) site origin.');
  // srcdoc/about:blank clones do not resolve CSP 'self' consistently across engines.
  // The explicit origin is the same origin already enforced by resource(), not an external allowlist.
  return `default-src 'none'; img-src 'self' ${site.origin} data:; style-src 'self' ${site.origin} 'unsafe-inline'; font-src 'self' ${site.origin} data:; script-src 'none'; frame-src 'none'; connect-src 'none'; form-action 'none'`;}
 async function render(html,settings,env={}){
  const expires=Date.now()+(env.timeoutMs||60000);
  async function wait(promise){let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Direct-print preview timed out. Use Normal ERPNext Print or review the saved job before retrying.')),Math.max(1,expires-Date.now()));})]);}finally{clearTimeout(timer);}}
  const document=env.document||root.document,canvasRenderer=env.html2canvas||root.html2canvas,origin=env.origin||root.location.origin;
  if(!canvasRenderer)throw new Error('The receipt renderer is not loaded. Refresh this page.');
  const parsed=new DOMParser().parseFromString(html,'text/html');
  if(parsed.querySelector('.print-format script'))throw new Error('Direct print requires a static ERPNext Print Format; use normal print for script-rendered content.');
  parsed.querySelectorAll('script,iframe,object,embed,base,meta,form,input,button').forEach(node=>node.remove());
  if(parsed.querySelector('canvas,video'))throw new Error('Use a static ERPNext Print Format for direct printing.');
  for(const img of parsed.querySelectorAll('img')){let src=resource(img.getAttribute('src')||'',origin);
   if(!src.startsWith('data:')&&new URL(src).pathname==='/api/method/cfg_kanban.services.delivery_note_printing.signature_image'){
    const response=await wait((env.fetch||root.fetch)(src,{credentials:'same-origin',cache:'no-store',redirect:'follow',referrerPolicy:'no-referrer'}));
    const type=(response.headers.get('content-type')||'').split(';')[0].trim().toLowerCase(),length=Number(response.headers.get('content-length')||0);
    if(!response.ok||!['image/png','image/jpeg','image/webp'].includes(type)||length>512*1024)throw new Error('The authorized delivery signature image could not be read.');
    const bytes=new Uint8Array(await wait(response.arrayBuffer()));if(!bytes.length||bytes.length>512*1024)throw new Error('Delivery signature image exceeds its print size limit.');
    src='data:'+type+';base64,'+bytes64(bytes);
   }
   img.setAttribute('src',src);img.removeAttribute('srcset');img.removeAttribute('loading');}
  for(const node of parsed.querySelectorAll('*'))for(const attr of Array.from(node.attributes))if(attr.name.toLowerCase().startsWith('on'))node.removeAttribute(attr.name);
  for(const node of parsed.querySelectorAll('link')){if(node.rel!=='stylesheet'){node.remove();continue;}node.href=resource(node.getAttribute('href'),origin);}
  // CSS background and font assets must obey the same no-proxy, same-origin contract.
  for(const style of parsed.querySelectorAll('style,[style]')){const css=style.tagName==='STYLE'?style.textContent:style.getAttribute('style');for(const match of css.matchAll(/url\(\s*['"]?([^)'"\s]+)['"]?\s*\)/g))resource(match[1],origin);}
  const iframe=document.createElement('iframe');iframe.setAttribute('sandbox','allow-same-origin');iframe.setAttribute('aria-hidden','true');
  const scale=settings.dpi/96,cssWidth=settings.printable_width/scale;
  iframe.style.cssText=`position:fixed;left:-20000px;top:0;width:${cssWidth}px;height:900px;border:0;visibility:hidden;`;
  const security=`<meta http-equiv="Content-Security-Policy" content="${framePolicy(origin)}">`;
  const sizing=`<style>html,body{margin:0!important;width:${cssWidth}px!important;min-width:0!important;background:white!important}.print-format{max-width:100%!important;min-height:0!important;box-sizing:border-box}.print-format-gutter{padding:0!important;margin:0!important;background:white!important}.print-toolbar,.action-banner{display:none!important}@media screen{.print-format{margin:0!important;box-shadow:none!important}}</style>`;
  document.body.appendChild(iframe);
  try{
   await wait(new Promise((resolve,reject)=>{const timeout=setTimeout(()=>reject(new Error('Print Format resources did not load.')),15000);iframe.onload=()=>{clearTimeout(timeout);resolve();};iframe.srcdoc='<!doctype html><html><head>'+security+parsed.head.innerHTML+sizing+'</head><body>'+parsed.body.innerHTML+'</body></html>';}));
   const doc=iframe.contentDocument;
   // Match the safe layout adjustments made by native Frappe v15 printview.
   const page=doc.querySelector('.page-break');if(page){page.style.display='flex';page.style.flexDirection='column';}
   const footer=doc.getElementById('footer-html');if(footer){footer.classList.add('hidden-pdf');footer.classList.remove('visible-pdf');footer.style.order='1';footer.style.marginTop='20px';}
   await wait(Promise.race([doc.fonts?.ready||Promise.resolve(),new Promise((_,reject)=>setTimeout(()=>reject(new Error('Print fonts did not load.')),10000))]));
   for(const image of doc.images){if(!image.complete)await wait(new Promise((resolve,reject)=>{const timeout=setTimeout(()=>reject(new Error('A Print Format image did not load.')),10000);image.onload=()=>{clearTimeout(timeout);resolve();};image.onerror=()=>{clearTimeout(timeout);reject(new Error('A Print Format image could not be read.'));};}));if(!image.naturalWidth)throw new Error('A Print Format image is unavailable. Use normal print or correct its asset.');}
   let element=doc.querySelector('.print-format');const roots=Array.from(doc.querySelectorAll('.print-format')).filter(node=>!node.parentElement?.closest('.print-format'));
   if(roots.length>1){element=doc.createElement('div');element.style.width=cssWidth+'px';for(const page of roots)element.appendChild(page);doc.body.appendChild(element);}
   if(!element)throw new Error('ERPNext did not return a printable document.');
   if(element.scrollWidth>cssWidth+2)throw new Error('This Print Format is wider than the configured paper. Choose an 80mm format or adjust printer setup.');
   const height=Math.ceil(element.getBoundingClientRect().height*scale);
   if(!height||height>1000000||settings.printable_width/8*height>32*1024*1024)throw new Error('This document exceeds the direct-print size limit. Use normal ERPNext print.');
   const boundaries=Array.from(element.querySelectorAll('tr,p,div,hr,img,h1,h2,h3')).map(el=>Math.floor((el.getBoundingClientRect().bottom-element.getBoundingClientRect().top)*scale)).filter(y=>y>0);
   let start=0;const frames=[];
   while(start<height){let end=Math.min(start+4096,height);if(end<height){const safe=boundaries.filter(y=>y>start+3000&&y<=end);if(safe.length)end=Math.max(...safe);}
    const capture=doc.createElement('canvas');capture.width=settings.printable_width;capture.height=end-start;
    const canvas=await wait(canvasRenderer(element,{canvas:capture,backgroundColor:'#ffffff',scale,width:cssWidth,height:(end-start)/scale,x:0,y:start/scale,windowWidth:cssWidth,windowHeight:900,scrollX:0,scrollY:0,useCORS:false,allowTaint:false,logging:false,imageTimeout:10000,removeContainer:true}));
    if(canvas.width!==settings.printable_width||canvas.height!==end-start)throw new Error('Renderer dimensions do not match the printer setup.');
    const pixels=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
    frames.push(...chunks(raster(pixels,canvas.width,canvas.height),canvas.width,canvas.height,boundaries.filter(y=>y>start&&y<=end).map(y=>y-start)));
    start=end;if(frames.length>1000)throw new Error('Too many print segments. Use normal ERPNext print.');
   }
   for(const frame of frames)frame.hash=await wait(digest(new TextEncoder().encode(frame.width+'\n'+frame.height+'\n'+frame.payload)));
   return frames;
  }finally{iframe.remove();}
 }
 return {MAX_URI,bytes64,rle,raster,encode,link,fits,chunks,digest,signer,preferences,resource,framePolicy,render};
});
