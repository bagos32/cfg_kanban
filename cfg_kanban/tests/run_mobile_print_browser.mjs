// Standalone offline smoke test: Node 22+ and Chrome/Firefox. No real ERPNext or printer.
import {spawn} from 'node:child_process';
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const chrome=process.env.CFG_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const mode=process.env.CFG_BROWSER||'chrome';
const firefox=process.env.CFG_FIREFOX||'/Applications/Firefox.app/Contents/MacOS/firefox';
let finishFirefox;const firefoxResult=new Promise(resolve=>finishFirefox=resolve);
const files=['cfg_kanban/tests/fixtures/mobile_print_browser.html',
 'cfg_kanban/public/js/vendor/html2canvas-1.4.1.min.js','cfg_kanban/public/js/mobile_print_bridge.js',
 'cfg_kanban/public/js/driver_route_actions.js','cfg_kanban/public/js/delivery_action_scanner.js',
 'cfg_kanban/public/js/driver_mobile_print.js','cfg_kanban/public/js/dispatch_recovery.js'];
const server=http.createServer(async(req,res)=>{
 const rel=new URL(req.url,'http://localhost').pathname.slice(1);
 if(mode==='firefox'&&rel==='cfg-fixture-result'&&req.method==='POST'){
  let body='';for await(const chunk of req){body+=chunk;if(body.length>200000){res.writeHead(413);res.end();finishFirefox({error:'Fixture result too large'});return;}}
  res.end('ok');try{finishFirefox(JSON.parse(body));}catch(_){finishFirefox({error:'Invalid Firefox fixture result'});}return;
 }
 if(rel==='cfg-fixture/print.css'){res.setHeader('Content-Type','text/css');res.end('.csp-print-marker{width:37px;height:17px;background:#000}.csp-print-logo{width:20px;height:20px}');return;}
 if(rel==='cfg-fixture/letterhead.bmp'){
  const bmp=Buffer.alloc(70);bmp.write('BM');bmp.writeUInt32LE(70,2);bmp.writeUInt32LE(54,10);bmp.writeUInt32LE(40,14);bmp.writeInt32LE(2,18);bmp.writeInt32LE(2,22);bmp.writeUInt16LE(1,26);bmp.writeUInt16LE(24,28);bmp.writeUInt32LE(16,34);
  for(let n=54;n<70;n++)bmp[n]=n%3?255:0;res.setHeader('Content-Type','image/bmp');res.end(bmp);return;
 }
 if(!files.includes(rel)){res.writeHead(404);res.end();return;}
 try{let source=await fs.readFile(path.join(repo,rel));
  if(mode==='firefox'&&rel.endsWith('.html'))source=source.toString()+`<script>runMobileTests().then(result=>fetch('/cfg-fixture-result',{method:'POST',body:JSON.stringify(result)})).catch(error=>fetch('/cfg-fixture-result',{method:'POST',body:JSON.stringify({error:String(error.message||error),stack:error.stack})}));</script>`;
  res.setHeader('Content-Type',rel.endsWith('.html')?'text/html; charset=utf-8':'text/javascript');res.end(source);}
 catch(_){res.writeHead(500);res.end();}
});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let browser,socket,profile;let shutdown=false;
const deadline=setTimeout(()=>{console.error('Offline browser check timed out');process.exitCode=1;finishFirefox({error:'Offline Firefox check timed out'});cleanup();},60000);
async function cleanup(){if(shutdown)return;shutdown=true;clearTimeout(deadline);socket?.close();browser?.kill('SIGTERM');server.close();}
try{
 if(!['chrome','firefox'].includes(mode))throw new Error('CFG_BROWSER must be chrome or firefox.');
 if(mode==='chrome'&&typeof WebSocket==='undefined')throw new Error('Node 22+ with WebSocket is required for this standalone browser test.');
 await fs.access(mode==='firefox'?firefox:chrome);profile=await fs.mkdtemp(path.join(os.tmpdir(),'cfg-mobile-browser-'));
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
 const port=server.address().port;
 if(mode==='firefox'){
  if(process.env.CFG_PRINT_SCREENSHOT)throw new Error('Screenshots are supported by the Chrome runner only.');
  await fs.writeFile(path.join(profile,'user.js'),'user_pref("app.update.auto",false);\nuser_pref("browser.shell.checkDefaultBrowser",false);\nuser_pref("datareporting.policy.dataSubmissionEnabled",false);\n');
  browser=spawn(firefox,['--headless','--no-remote','--profile',profile,`http://127.0.0.1:${port}/cfg_kanban/tests/fixtures/mobile_print_browser.html`]);
  let stderr='';browser.stderr.on('data',data=>stderr=(stderr+data).slice(-4000));browser.on('error',error=>finishFirefox({error:String(error)}));browser.on('exit',()=>{if(!shutdown)finishFirefox({error:'Firefox exited before fixture completion',stderr});});
  const result=await firefoxResult;if(result.error)throw new Error(result.error+'\n'+(result.stack||result.stderr||''));
  console.log(JSON.stringify({browser:mode,...result},null,2));
 }else{
 browser=spawn(chrome,['--headless=new','--no-first-run','--no-default-browser-check','--disable-gpu',
  '--remote-debugging-port=0','--user-data-dir='+profile,'about:blank']);
 let endpoint='',stderr='';browser.stderr.on('data',data=>{stderr+=data;const m=stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/);if(m)endpoint=m[1];});
 for(let i=0;i<100&&!endpoint;i++)await sleep(100);
 if(!endpoint)throw new Error('Isolated Chrome did not start: '+stderr.slice(-1000));
 const httpEndpoint=endpoint.replace(/^ws:/,'http:').replace(/\/devtools\/browser\/.*/,'');
 const tabs=await(await fetch(httpEndpoint+'/json/list')).json();
 socket=new WebSocket(tabs[0].webSocketDebuggerUrl);
 await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
 let counter=0;const pending=new Map();
 socket.onmessage=e=>{const v=JSON.parse(e.data);if(v.id&&pending.has(v.id)){const {resolve,reject}=pending.get(v.id);pending.delete(v.id);v.error?reject(v.error):resolve(v.result);}};
 const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++counter;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});
 await call('Page.enable');await call('Emulation.setDeviceMetricsOverride',{width:900,height:1100,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url:`http://127.0.0.1:${port}/cfg_kanban/tests/fixtures/mobile_print_browser.html`});
 for(let i=0;i<100;i++){const v=await call('Runtime.evaluate',{expression:'typeof window.runMobileTests'});if(v.result?.value==='function')break;await sleep(100);}
 const result=await call('Runtime.evaluate',{expression:'window.runMobileTests()',awaitPromise:true,returnByValue:true,timeout:45000});
 if(result.exceptionDetails)throw new Error(result.exceptionDetails.exception?.description||result.exceptionDetails.text);
 console.log(JSON.stringify(result.result.value,null,2));
 if(process.env.CFG_PRINT_SCREENSHOT){const shot=await call('Page.captureScreenshot',{format:'png'});await fs.writeFile(process.env.CFG_PRINT_SCREENSHOT,Buffer.from(shot.data,'base64'));}
 }
}catch(error){console.error(error);process.exitCode=1;}finally{await cleanup();}
