/* Exercise the Frappe v15 stylesheet pipeline, including its real PostCSS plugin.
 * See frappe/esbuild/esbuild.js and sass_options.js at v15.69.2.
 * Tools come from an existing Bench or a temporary CFG_FRAPPE_NODE_MODULES path.
 */
const fs=require('node:fs'),path=require('node:path'),{createRequire}=require('node:module');

function toolchain(nodeModules=process.env.CFG_FRAPPE_NODE_MODULES){
 const folder=nodeModules||path.resolve(__dirname,'../../../frappe/node_modules');
 const load=createRequire(path.resolve(folder,'__cfg_build_probe__.cjs'));
 return {esbuild:load('esbuild'),postcss:load('@frappe/esbuild-plugin-postcss2').default,
  autoprefixer:load('autoprefixer'),rtlcss:load('rtlcss')};
}

async function buildStyle({entryPoint,outdir,rtl=false,nodeModules}){
 const tools=toolchain(nodeModules);
 // Normalize macOS /tmp aliases before the plugin computes its temporary paths.
 entryPoint=fs.realpathSync(entryPoint);
 const sourceDir=path.dirname(entryPoint);
 const sassOptions={includePaths:[sourceDir,path.dirname(sourceDir)],quietDeps:true,
  importer(url){return {file:url.replace(/^~/,'').replace(/\.css$/,'')};}};
 const plugins=rtl?[tools.rtlcss,tools.autoprefixer]:[tools.autoprefixer];
 const result=await tools.esbuild.build({entryPoints:[entryPoint],outdir,
  entryNames:'[dir]/[name].[hash]',target:['es2017'],sourcemap:true,bundle:true,
  metafile:true,minify:true,logLevel:'silent',
  plugins:[tools.postcss({plugins,sassOptions,rootDir:sourceDir})]});
 const assets=Object.entries(result.metafile.outputs).filter(([,info])=>info.entryPoint)
  .map(([file,info])=>({file,key:(rtl?'rtl_':'')+path.basename(info.entryPoint)}));
 return {...result,assets};
}

module.exports={toolchain,buildStyle};
