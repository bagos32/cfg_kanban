const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path');
const {toolchain,buildStyle}=require('./frappe_asset_build.cjs');
const repo=path.resolve(__dirname,'../..');
let missing;
try{toolchain();}catch(error){missing='Set CFG_FRAPPE_NODE_MODULES to installed Frappe build dependencies: '+error.message;}
const options={skip:missing||false};
async function fixture(){
 const folder=await fs.mkdtemp(path.join(os.tmpdir(),'cfg-postcss-regression-'));
 const css=await fs.readFile(path.join(repo,'cfg_kanban/public/css/kanban_operator.css'),'utf8');
 await fs.mkdir(path.join(folder,'css'));
 await fs.writeFile(path.join(folder,'css/kanban_operator.css'),css);
 return {folder,css,entry:path.join(folder,'cfg_kanban.bundle.scss')};
}

test('native PostCSS reproduces the reported temporary-path failure for a CSS import',options,async()=>{
 const s=await fixture(),entry=path.join(s.folder,'legacy.bundle.css');
 await fs.writeFile(entry,'@import "./css/kanban_operator.css";\n');
 await assert.rejects(buildStyle({entryPoint:entry,outdir:path.join(s.folder,'bad-output')}),
  error=>error.errors?.some(row=>row.text.includes('ENOENT')&&row.text.includes('kanban_operator.css')));
});

test('the actual Sass entry builds normal and RTL CSS with the existing native manifest key',options,async()=>{
 await assert.rejects(fs.access(path.join(repo,'cfg_kanban/public/cfg_kanban.bundle.css')),{code:'ENOENT'});
 const s=await fixture();
 await fs.copyFile(path.join(repo,'cfg_kanban/public/cfg_kanban.bundle.scss'),s.entry);
 const hook=(await fs.readFile(path.join(repo,'cfg_kanban/hooks.py'),'utf8')).match(/app_include_css\s*=\s*"([^"]+)"/)[1];
 for(const rtl of [false,true]){
  const result=await buildStyle({entryPoint:s.entry,outdir:path.join(s.folder,rtl?'rtl':'normal'),rtl});
  assert.equal(result.assets.length,1);const asset=result.assets[0];
  assert.equal(asset.key,(rtl?'rtl_':'')+hook);
  assert.match(path.basename(asset.file),/^cfg_kanban\.bundle\.[A-Z0-9]+\.css$/);
  const css=await fs.readFile(asset.file,'utf8');
  assert.doesNotMatch(css,/@import\b/);
  for(const selector of ['.cfg-panel-switch','.cfg-panel-slider','.cfg-logistics-scanner','.cfg-field-actions'])assert(css.includes(selector),selector);
 }
});

test('the imported stylesheet still changes the native compiled bundle hash',options,async()=>{
 const s=await fixture();
 await fs.copyFile(path.join(repo,'cfg_kanban/public/cfg_kanban.bundle.scss'),s.entry);
 const first=await buildStyle({entryPoint:s.entry,outdir:path.join(s.folder,'first')});
 await fs.writeFile(path.join(s.folder,'css/kanban_operator.css'),s.css+'\n.cfg-cache-regression { color: #123456; }\n');
 const second=await buildStyle({entryPoint:s.entry,outdir:path.join(s.folder,'second')});
 assert.notEqual(path.basename(first.assets[0].file),path.basename(second.assets[0].file));
 assert.equal(first.assets[0].key,second.assets[0].key);
});
