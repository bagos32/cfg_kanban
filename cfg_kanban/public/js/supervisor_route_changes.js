/* Inline route decisions in the existing Supervisor Centre; no office planning popup. */
(function(root){
 'use strict';
 const SESSION='cfg_kanban_operator_session';
 const authorized=operator=>Boolean(operator&&['Supervisor','Development Proxy'].includes(operator.kanban_role)&&operator.view_all_responsibilities&&operator.permissions?.override&&operator.permissions?.complete);
 function bind(options){
  const {frappe:f,host,storage}=options,e=f.utils.escape_html,tr=value=>typeof __==='function'?__(value):value;
  let rows=[],selected=null,action=null,operator=null,token=null,camera=null,cameraEpoch=0,epoch=0,working=false,hidden=false;
  host.html(`<section class="frappe-card p-4"><h2>${tr('Delivery Route Changes')}</h2><p>${tr('Review route-order and customer-stop cancellation requests here. Cancellation requires a reason and an explicit decision for loaded goods.')}</p><div class="cfg-route-requests"></div>
   <div class="cfg-route-review-login" style="display:none"><p>${tr('Identify a Supervisor with View All Responsibilities, Override and Complete permissions.')}</p><input class="form-control cfg-route-credential" autocomplete="off" placeholder="${tr('Supervisor credential')}"><input class="form-control cfg-route-pin" type="password" autocomplete="off" placeholder="${tr('PIN if required')}"><button class="btn btn-primary cfg-route-sign-in">${tr('Sign in for Review')}</button><button class="btn btn-default cfg-route-camera">${tr('Scan with Camera')}</button><button class="btn btn-default cfg-route-login-close">${tr('Close Review')}</button></div>
   <div class="cfg-route-review-notice" role="status"></div><div class="cfg-route-review-host"></div></section>`);
  const readToken=()=>storage.getItem(SESSION),onPage=()=>!hidden&&options.active(),notice=value=>host.find('.cfg-route-review-notice').text(value||'');
  function focus(){if(!onPage())return;if(action)return action.focus();if(selected)host.find('.cfg-route-credential').trigger('focus');}
  function stopCamera(){cameraEpoch++;camera?.stop_scan?.();camera?.dialog?.hide?.();camera=null;}
  function close(){epoch++;stopCamera();const panel=action;action=null;panel?.close();selected=null;working=false;operator=null;token=null;host.find('.cfg-route-review-host').empty();host.find('.cfg-route-review-login').hide();host.find('.cfg-route-credential,.cfg-route-pin').val('');notice('');options.onIdle();}
  function render(){host.find('.cfg-route-requests').html(rows.map(row=>`<div class="cfg-attention-item"><strong>${e(row.request_type==='Cancel Customer Stop'?'Cancel stop':'Route order')} · ${e(row.target_customer)} · ${e(row.state)}</strong><small>${e(row.delivery_trip)} · ${e(row.company)} · ${e(row.requested_by)} · ${e(row.reason)}</small><button class="btn btn-default cfg-route-review" data-request="${e(row.name)}">${tr(row.state==='Pending'?'Review Request':'View Decision / Recover Action')} · ${e(row.name)}</button></div>`).join('')||`<p class="text-muted">${tr('No route change requests.')}</p>`);}
  async function rpc(method,args){return(await f.call({method,args})).message;}
  async function launch(ticket){
   if(!selected||!authorized(operator)||!onPage()||epoch!==ticket||readToken()!==token)return;
   const request=selected;host.find('.cfg-route-review-login').hide();
   action=root.cfg_driver_route_actions.open({frappe:f,host:host.find('.cfg-route-review-host'),trip:request.delivery_trip,
    operation:'Review Route Change',outcome:request.name,owner:()=>operator?.employee,token:()=>readToken()===token?token:null,
    active:()=>onPage()&&selected===request,detail:()=>({trip:{trip_title:request.delivery_trip},stops:[]}),
    refresh:async()=>{await options.refresh();},storage,locks:options.locks,nonce:options.nonce,error:options.error,supervisor:()=>authorized(operator),
    onClose:()=>{action=null;close();}});
   notice('');focus();
  }
  async function select(row){
   if(working||action||!onPage())return;selected=row;const ticket=++epoch;working=true;options.onBusy();notice(tr('Checking Supervisor identity…'));
   try{
    token=readToken();operator=token?await rpc('cfg_kanban.api.operator.operator_session_status',{operator_session_token:token}):null;
    if(!onPage()||epoch!==ticket)return;
    if(authorized(operator)&&readToken()===token)await launch(ticket);
    else {operator=null;host.find('.cfg-route-review-login').show();notice(tr('Scan a Supervisor credential to review this request.'));}
   }catch(error){if(onPage()&&epoch===ticket){operator=null;host.find('.cfg-route-review-login').show();notice(options.error(error));}}
   finally{if(epoch===ticket){working=false;focus();}}
  }
  async function signIn(value){
   if(working||!selected||!onPage())return;const raw=String(value||host.find('.cfg-route-credential').val()||'').trim();if(!raw)return;
   let credential=raw;try{credential=new URLSearchParams(new URL(raw).hash.replace(/^#/, '')).get('operator')||raw;}catch(_){}
   const ticket=++epoch,baseline=readToken();working=true;
   try{
    const result=await rpc('cfg_kanban.api.operator.login_operator',{token:credential,pin:host.find('.cfg-route-pin').val()||'',station:storage.getItem('cfg_kanban_station')||''});
    if(!onPage()||epoch!==ticket||readToken()!==baseline)return;
    if(!authorized(result.operator))throw new Error('This operator needs Supervisor, View All Responsibilities, Override and Complete permissions.');
    storage.setItem(SESSION,result.session_token);token=result.session_token;operator=result.operator;host.find('.cfg-route-credential,.cfg-route-pin').val('');await launch(ticket);
   }catch(error){if(onPage()&&epoch===ticket)notice(options.error(error));}
   finally{if(epoch===ticket){working=false;focus();}}
  }
  function startCamera(){
   if(camera||!selected||action||!onPage())return;if(!f.ui.Scanner){notice(tr('Camera unavailable; use the credential field.'));return;}
   const ticket=cameraEpoch;let accepted=false;
   camera=new f.ui.Scanner({dialog:true,multiple:false,on_scan:data=>{if(accepted||ticket!==cameraEpoch||!onPage()||!selected)return;accepted=true;stopCamera();signIn(data.decodedText);}});
   camera.dialog?.$wrapper?.one?.('hidden.bs.modal.cfg_route_review',()=>{cameraEpoch++;camera=null;focus();});
  }
  host.on('click.cfg_route_review','.cfg-route-review',event=>{const row=rows.find(r=>r.name===$(event.currentTarget).attr('data-request'));if(row)select(row);})
   .on('click.cfg_route_review','.cfg-route-sign-in',()=>signIn())
   .on('click.cfg_route_review','.cfg-route-camera',startCamera)
   .on('click.cfg_route_review','.cfg-route-login-close',close)
   .on('keydown.cfg_route_review','.cfg-route-credential',event=>{if(!['Enter','Tab'].includes(event.key)||event.shiftKey||event.ctrlKey||event.altKey||event.metaKey||event.isComposing)return;if(!host.find('.cfg-route-credential').val())return;event.preventDefault();event.stopPropagation();signIn();});
  function changed(event){if(event.key===SESSION&&selected)close();}
  root.addEventListener?.('storage',changed);
  return {update(values){rows=values||[];render();},busy:()=>Boolean(selected||working||action),select,
   async openName(name){if(!onPage()||selected)return;try{const row=rows.find(r=>r.name===name)||await rpc('frappe.client.get',{doctype:'CFG Kanban Route Change Request',name});if(onPage())await select(row);}catch(error){notice(options.error(error));}},
   show(){hidden=false;},hide(){hidden=true;close();},close,focus};
 }
 const api={bind,authorized};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.cfg_supervisor_route_changes=api;
})(typeof window==='undefined'?globalThis:window);
