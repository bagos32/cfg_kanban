// Standalone offline smoke test: Node 22+ and Chrome/Firefox. No real ERPNext or printer.
import {spawn,spawnSync} from 'node:child_process';
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import assetBuild from './frappe_asset_build.cjs';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const chrome=process.env.CFG_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const mode=process.env.CFG_BROWSER||'chrome';
const incognito=process.env.CFG_FIELD_INCOGNITO==='1';
const firefox=process.env.CFG_FIREFOX||'/Applications/Firefox.app/Contents/MacOS/firefox';
const esbuild=process.env.CFG_ESBUILD||path.resolve(repo,'../frappe/node_modules/.bin/esbuild');
let finishFirefox;const firefoxResult=new Promise(resolve=>finishFirefox=resolve);
const files=['cfg_kanban/tests/fixtures/driver_field_browser.html','cfg_kanban/public/js/field_ui.js','cfg_kanban/public/js/delivery_product_checks.js','cfg_kanban/public/js/delivery_action_scanner.js','cfg_kanban/public/js/driver_route_actions.js','cfg_kanban/public/css/kanban_operator.css','cfg_kanban/cfg_kanban/page/kanban_driver_route/kanban_driver_route.js'];
const styles=new Map(),scripts=new Map();let currentStyle,previousStyle,currentHelper,previousHelper;
const legacyStyle='/assets/cfg_kanban/css/kanban_operator.css';
async function buildStyles(folder){
 const input=path.join(folder,'public'),out=path.join(folder,'dist/css'),meta=path.join(folder,'styles-meta.json');
 await fs.mkdir(path.join(input,'css'),{recursive:true});
 await fs.writeFile(path.join(input,'cfg_kanban.bundle.scss'),await fs.readFile(path.join(repo,'cfg_kanban/public/cfg_kanban.bundle.scss')));
 const source=await fs.readFile(path.join(repo,'cfg_kanban/public/css/kanban_operator.css'),'utf8');
 const split=source.indexOf('.cfg-panel-switch {');if(split<0)throw new Error('Missing field switch CSS regression boundary.');
 const oldCSS=source.slice(0,split);styles.set(legacyStyle,Buffer.from(oldCSS));
 async function compile(css){
  await fs.writeFile(path.join(input,'css/kanban_operator.css'),css);
  const build=await assetBuild.buildStyle({entryPoint:path.join(input,'cfg_kanban.bundle.scss'),outdir:out});
  const asset=build.assets.find(row=>row.key==='cfg_kanban.bundle.css');
  if(!asset)throw new Error('Native CSS manifest key changed.');
  const output=await fs.readFile(asset.file);if(output.toString().includes('@import'))throw new Error('Bundle still contains an unresolved CSS import.');
  const url='/assets/cfg_kanban/dist/css/'+path.basename(asset.file);styles.set(url,output);return url;
 }
 previousStyle=await compile(oldCSS);currentStyle=await compile(source);
 if(previousStyle===currentStyle)throw new Error('Changed imported CSS reused the previous bundle URL.');
 await fs.mkdir(path.join(input,'js'),{recursive:true});
 await fs.writeFile(path.join(input,'cfg_kanban_field_ui.bundle.js'),await fs.readFile(path.join(repo,'cfg_kanban/public/cfg_kanban_field_ui.bundle.js')));
 const helper=await fs.readFile(path.join(repo,'cfg_kanban/public/js/field_ui.js'),'utf8');
 const begin=helper.indexOf(' function mountSwitch('),end=helper.indexOf(' function menuShift(');
 if(begin<0||end<=begin)throw new Error('Missing navigation API regression boundary.');
 const legacy=helper.slice(0,begin)+` function mountSwitch(parent,panel,context){const host=root.$(switchHTML(panel)).prependTo(parent);host.on('click.cfg_panel','[data-cfg-panel]',event=>navigate(root.$(event.currentTarget).attr('data-cfg-panel'),context()));const sync=()=>remember(context());sync();return {sync,host};}\n`+helper.slice(end);
 async function compileHelper(value){
  await fs.writeFile(path.join(input,'js/field_ui.js'),value);
  const result=spawnSync(esbuild,[path.join(input,'cfg_kanban_field_ui.bundle.js'),'--bundle','--minify','--target=es2017','--sourcemap','--entry-names=[name].[hash]','--outdir='+path.join(folder,'dist/js'),'--metafile='+meta],{encoding:'utf8'});
  if(result.error||result.status!==0)throw new Error(result.error?.message||result.stderr);
  const build=JSON.parse(await fs.readFile(meta,'utf8')),output=Object.keys(build.outputs).find(file=>build.outputs[file].entryPoint&&file.endsWith('.js'));
  if(!output||!Object.keys(build.inputs).some(file=>file.endsWith('js/field_ui.js')))throw new Error('Navigation dependency missing from its JS bundle.');
  const url='/assets/cfg_kanban/dist/js/'+path.basename(output);scripts.set(url,await fs.readFile(output));return url;
 }
 previousHelper=await compileHelper(legacy);currentHelper=await compileHelper(helper);
 if(previousHelper===currentHelper)throw new Error('Changed navigation API reused its previous script URL.');
}
const server=http.createServer(async(req,res)=>{
 const rel=new URL(req.url,'http://localhost').pathname.slice(1);
 if(styles.has('/'+rel)){res.setHeader('Content-Type','text/css');res.setHeader('Cache-Control','public, max-age=31536000, immutable');res.end(styles.get('/'+rel));return;}
 if(scripts.has('/'+rel)){res.setHeader('Content-Type','text/javascript');res.setHeader('Cache-Control','public, max-age=31536000, immutable');res.end(scripts.get('/'+rel));return;}
 if(rel==='cfg-storage-probe'){res.setHeader('Content-Type','text/html');res.end('<title>Offline storage probe</title>');return;}
 if(mode==='firefox'&&rel==='cfg-fixture-result'&&req.method==='POST'){
  let body='';for await(const chunk of req){body+=chunk;if(body.length>200000){res.writeHead(413);res.end();finishFirefox({error:'Fixture result too large'});return;}}
  res.end('ok');try{finishFirefox(JSON.parse(body));}catch(_){finishFirefox({error:'Invalid Firefox fixture result'});}return;
 }
 if(!files.includes(rel)){res.writeHead(404);res.end();return;}
 try{let source=await fs.readFile(path.join(repo,rel));
  if(rel.endsWith('.html'))source=source.toString().replace('__CFG_LEGACY_STYLESHEET__',legacyStyle).replace('__CFG_STYLESHEET__',currentStyle).replace('__CFG_PREVIOUS_STYLESHEET__',previousStyle).replace('__CFG_CURRENT_HELPER__',currentHelper).replace('__CFG_PREVIOUS_HELPER__',previousHelper);
  if(mode==='firefox'&&rel.endsWith('.html'))source=source.toString()+`<script>runFieldUITests().then(result=>fetch('/cfg-fixture-result',{method:'POST',body:JSON.stringify(result)})).catch(error=>fetch('/cfg-fixture-result',{method:'POST',body:JSON.stringify({error:String(error.message||error),stack:error.stack})}));</script>`;
  res.setHeader('Content-Type',rel.endsWith('.html')?'text/html; charset=utf-8':rel.endsWith('.css')?'text/css':'text/javascript');res.end(source);}
 catch(_){res.writeHead(500);res.end();}
});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let browser,socket,browserSocket,profile;let shutdown=false;
const deadline=setTimeout(()=>{console.error('Offline browser check timed out');process.exitCode=1;finishFirefox({error:'Offline Firefox check timed out'});cleanup();},60000);
async function cleanup(){if(shutdown)return;shutdown=true;clearTimeout(deadline);socket?.close();browserSocket?.close();browser?.kill('SIGTERM');server.close();}
async function connect(url){
 const socket=new WebSocket(url);await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
 let counter=0;const pending=new Map();socket.onmessage=e=>{const v=JSON.parse(e.data);if(v.id&&pending.has(v.id)){const {resolve,reject}=pending.get(v.id);pending.delete(v.id);v.error?reject(v.error):resolve(v.result);}};
 const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++counter;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});
 return {socket,call};
}
try{
 if(!['chrome','firefox'].includes(mode))throw new Error('CFG_BROWSER must be chrome or firefox.');
 if(incognito&&mode!=='chrome')throw new Error('CFG_FIELD_INCOGNITO uses an isolated Chrome off-the-record context.');
 if(mode==='chrome'&&typeof WebSocket==='undefined')throw new Error('Node 22+ with WebSocket is required for this standalone browser test.');
 await fs.access(mode==='firefox'?firefox:chrome);profile=await fs.mkdtemp(path.join(os.tmpdir(),'cfg-field-browser-'));
 await buildStyles(profile);
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
 const port=server.address().port;
 if(mode==='firefox'){
  if(process.env.CFG_FIELD_SCREENSHOT)throw new Error('Screenshots are supported by the Chrome runner only.');
  await fs.writeFile(path.join(profile,'user.js'),'user_pref("app.update.auto",false);\nuser_pref("browser.shell.checkDefaultBrowser",false);\nuser_pref("datareporting.policy.dataSubmissionEnabled",false);\n');
  browser=spawn(firefox,['--headless','--no-remote','--profile',profile,`http://127.0.0.1:${port}/cfg_kanban/tests/fixtures/driver_field_browser.html`]);
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
 let tabs=await(await fetch(httpEndpoint+'/json/list')).json(),target=tabs[0];
 if(incognito){
  const normal=await connect(target.webSocketDebuggerUrl);await normal.call('Page.enable');await normal.call('Page.navigate',{url:`http://127.0.0.1:${port}/cfg-storage-probe`});
  for(let i=0;i<100;i++){const v=await normal.call('Runtime.evaluate',{expression:'location.pathname'});if(v.result?.value==='/cfg-storage-probe')break;await sleep(50);}
  await normal.call('Runtime.evaluate',{expression:"localStorage.setItem('cfg-private-probe','normal-profile')"});normal.socket.close();
  const control=await connect(endpoint);browserSocket=control.socket;
  const {browserContextId}=await control.call('Target.createBrowserContext',{disposeOnDetach:true});
  const {targetId}=await control.call('Target.createTarget',{url:'about:blank',browserContextId});
  const {targetInfo}=await control.call('Target.getTargetInfo',{targetId});if(targetInfo.browserContextId!==browserContextId)throw new Error('Incognito target context mismatch.');
  tabs=await(await fetch(httpEndpoint+'/json/list')).json();target=tabs.find(tab=>tab.id===targetId);if(!target)throw new Error('Incognito target is unavailable.');
 }
 const client=await connect(target.webSocketDebuggerUrl);socket=client.socket;const call=client.call;
 await call('Page.enable');await call('Emulation.setDeviceMetricsOverride',{width:Number(process.env.CFG_FIELD_WIDTH||900),height:1100,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url:`http://127.0.0.1:${port}/cfg_kanban/tests/fixtures/driver_field_browser.html`});
 for(let i=0;i<100;i++){const v=await call('Runtime.evaluate',{expression:'typeof window.runFieldUITests'});if(v.result?.value==='function')break;await sleep(100);}
 if(incognito){const storage=await call('Runtime.evaluate',{expression:"localStorage.getItem('cfg-private-probe')"});if(storage.result?.value!==null)throw new Error('Incognito shared normal-profile localStorage.');}
 const result=await call('Runtime.evaluate',{expression:'window.runFieldUITests()',awaitPromise:true,returnByValue:true,timeout:45000});
 if(result.exceptionDetails)throw new Error(result.exceptionDetails.exception?.description||result.exceptionDetails.text);
 console.log(JSON.stringify({incognito,...result.result.value},null,2));
 if(process.env.CFG_FIELD_SCREENSHOT){await call('Runtime.evaluate',{expression:"document.querySelector('#switch').scrollIntoView({block:'start'})"});await sleep(50);const shot=await call('Page.captureScreenshot',{format:'png'});await fs.writeFile(process.env.CFG_FIELD_SCREENSHOT,Buffer.from(shot.data,'base64'));}
 }
}catch(error){console.error(error);process.exitCode=1;}finally{await cleanup();}
