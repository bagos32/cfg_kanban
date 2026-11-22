/* CFG map default. Saved pins and selected routes retain their actual-location focus. */
(function(root){
 'use strict';
 const center=Object.freeze([3.139,101.6869]),zoom=13;
 function apply(f){if(f?.utils?.map_defaults){f.utils.map_defaults.center=[...center];f.utils.map_defaults.zoom=zoom;}return {center:[...center],zoom};}
 function boot(){apply(root.frappe);}
 const api={center,zoom,apply};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.cfg_kanban_map_defaults=api;
 boot();
 if(root.document){
  if(typeof root.$==='function')root.$(root.document).on('app_ready.cfg_map_defaults',boot);
  if(root.document.readyState==='loading')root.document.addEventListener('DOMContentLoaded',boot,{once:true});
  root.frappe?.router?.on?.('change',boot);
 }
})(typeof window==='undefined'?globalThis:window);
