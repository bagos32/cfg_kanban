// Standalone offline smoke test: Node 22+ and Chrome. No real ERPNext or printer.
import {spawn} from 'node:child_process';
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const chrome=process.env.CFG_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const files=['cfg_kanban/tests/fixtures/mobile_print_browser.html',
 'cfg_kanban/public/js/vendor/html2canvas-1.4.1.min.js','cfg_kanban/public/js/mobile_print_bridge.js',
 'cfg_kanban/public/js/driver_route_actions.js','cfg_kanban/public/js/delivery_action_scanner.js',
 'cfg_kanban/public/js/driver_mobile_print.js','cfg_kanban/public/js/dispatch_recovery.js'];
const server=http.createServer(async(req,res)=>{
 const rel=new URL(req.url,'http://localhost').pathname.slice(1);
 if(!files.includes(rel)){res.writeHead(404);res.end();return;}
 try{res.setHeader('Content-Type',rel.endsWith('.html')?'text/html; charset=utf-8':'text/javascript');res.end(await fs.readFile(path.join(repo,rel)));}
 catch(_){res.writeHead(500);res.end();}
});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let browser,socket,profile;let shutdown=false;
const deadline=setTimeout(()=>{console.error('Offline browser check timed out');process.exitCode=1;cleanup();},60000);
async function cleanup(){if(shutdown)return;shutdown=true;clearTimeout(deadline);socket?.close();browser?.kill('SIGTERM');server.close();}
try{
 if(typeof WebSocket==='undefined')throw new Error('Node 22+ with WebSocket is required for this standalone browser test.');
 await fs.access(chrome);profile=await fs.mkdtemp(path.join(os.tmpdir(),'cfg-mobile-browser-'));
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
 const port=server.address().port;
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
}catch(error){console.error(error);process.exitCode=1;}finally{await cleanup();}
