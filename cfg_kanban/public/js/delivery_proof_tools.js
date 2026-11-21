/* Shared private evidence controls for the existing delivery-proof workflow. */
(function (root) {
  'use strict';
  const tr = value => typeof __ === 'function' ? __(value) : value;
  const service = 'cfg_kanban.api.media.';
  function evidenceHTML() {
    return `<div class="cfg-proof-tools"><label class="btn btn-default cfg-proof-camera">${tr('Camera photo')}<input type="file" accept="image/*" capture="environment" hidden></label>
      <label class="btn btn-default cfg-proof-file">${tr('Upload evidence')}<input type="file" accept="image/*,application/pdf,video/*" multiple hidden></label>
      <div class="cfg-proof-status" role="status"></div><div class="cfg-proof-media"></div></div>`;
  }
  function signatureHTML() {
    return `<div><canvas class="cfg-signature-pad" width="600" height="180" style="width:100%;max-width:600px;border:1px solid #aaa;touch-action:none"></canvas>
      <div><button type="button" class="btn btn-default cfg-clear-signature">${tr('Clear signature')}</button>
      <button type="button" class="btn btn-default cfg-save-signature">${tr('Save signature')}</button></div></div>`;
  }
  function geotag() {
    if (!root.navigator?.geolocation) return Promise.reject(new Error(tr('This device does not provide geolocation.')));
    return new Promise((resolve, reject) => root.navigator.geolocation.getCurrentPosition(
      position => resolve({ latitude: position.coords.latitude, longitude: position.coords.longitude, accuracy: position.coords.accuracy }),
      () => reject(new Error(tr('Location permission is required for delivery proof.'))),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }));
  }
  async function stampPhoto(file, capturedAt, reference, location, label) {
    const bitmap = root.createImageBitmap ? await root.createImageBitmap(file) : await new Promise((resolve, reject) => {
      const image = new root.Image(), url = root.URL.createObjectURL(file);
      image.onload = () => { root.URL.revokeObjectURL(url); resolve(image); };
      image.onerror = () => { root.URL.revokeObjectURL(url); reject(new Error(tr('Could not read the photograph.'))); };
      image.src = url;
    });
    const canvas = root.document.createElement('canvas'); canvas.width = bitmap.width; canvas.height = bitmap.height;
    const ctx = canvas.getContext('2d'); ctx.drawImage(bitmap, 0, 0); bitmap.close?.();
    const strip = Math.max(78, Math.round(canvas.width * .065));
    ctx.fillStyle = 'rgba(0,0,0,0.75)'; ctx.fillRect(0, canvas.height - strip, canvas.width, strip);
    const size = Math.max(16, Math.round(strip * .23)); ctx.fillStyle = '#fff'; ctx.font = `${size}px sans-serif`;
    ctx.fillText(`${reference} · ${capturedAt}`, size, canvas.height - strip + size * 1.3);
    ctx.font = `${Math.round(size * .8)}px sans-serif`;
    ctx.fillText(`GPS ${location.latitude.toFixed(6)}, ${location.longitude.toFixed(6)} · ±${Math.round(location.accuracy)}m`, size, canvas.height - strip + size * 2.6);
    ctx.fillText(label, size, canvas.height - size * .5);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', .9));
    if (!blob) throw new Error(tr('Could not prepare the timestamped photograph.'));
    return new root.File([blob], `delivery-proof-${Date.now()}.jpg`, { type: 'image/jpeg' });
  }
  function bind(options) {
    const f = options.frappe, evidence = options.field('evidence').$wrapper, signature = options.field('signature').$wrapper;
    const token = options.token(), valid = () => !closed && options.token() === token && options.valid();
    let closed = false, working = false, rows = options.proof.media || [], drawing = false, ink = false;
    const rpc = async (name, args = {}) => (await f.call({method: service + name,
      args: {proof_name: options.proof.name, operator_session_token: token, ...args}})).message;
    const status = text => { if (valid()) evidence.find('.cfg-proof-status').text(text); };
    function render() {
      if (!valid()) return;
      const e = f.utils.escape_html;
      evidence.find('.cfg-proof-media').html(rows.length ? rows.map(row =>
        `<div class="cfg-logistics-line" data-media-id="${e(row.media_id)}"><div><strong>${e(row.evidence_kind || 'attachment')}</strong> ${e(row.original_filename)}</div>
        <div><button type="button" class="btn btn-default cfg-view-proof">${tr('Open')}</button> <button type="button" class="btn btn-danger cfg-remove-proof">${tr('Remove')}</button></div></div>`).join('') : tr('No proof media uploaded yet'));
    }
    async function refresh() { const next = await rpc('list_delivery_proof_media'); if (valid()) { rows = next || []; render(); } }
    async function work(action) {
      if (!valid() || working) return;
      working = true;
      try { await action(); }
      catch (error) { status(options.error(error)); }
      finally { working = false; }
    }
    async function upload(files, kind, camera = false) {
      return work(async () => {
        let location = null, capturedAt = null, selected = Array.from(files || []);
        if (!selected.length) return;
        if (camera) {
          location = await geotag(); if (!valid()) return;
          const stamp = await rpc('get_delivery_proof_camera_stamp'); if (!valid()) return;
          capturedAt = stamp.captured_at;
          selected = [await stampPhoto(selected[0], capturedAt, options.proof.name, location, 'CFG Kanban customer delivery proof')];
        }
        for (const file of selected) {
          if (!valid()) return; status(tr('Uploading') + ' ' + file.name);
          const auth = await rpc('create_delivery_proof_upload_url', {original_filename:file.name, content_type:file.type, size_bytes:file.size,
            idempotency_key:options.nonce(), evidence_kind:kind, capture_source:camera?'timestamped-camera':kind==='signature'?'signature-pad':'file-upload',
            capture_timestamp:capturedAt, latitude:location?.latitude, longitude:location?.longitude, location_accuracy:location?.accuracy});
          if (!valid()) return;
          if (!auth.already_available) {
            const form = new root.FormData(); Object.entries(auth.fields || {}).forEach(([key, value]) => form.append(key, value)); form.append('file', file);
            const result = await root.fetch(auth.url, {method:auth.method, body:form});
            if (!result.ok) throw new Error(tr('Private upload failed with HTTP') + ' ' + result.status);
            if (!valid()) return;
            await rpc('confirm_delivery_proof_upload', {media_id:auth.media_id, confirmation_token:auth.confirmation_token});
          }
        }
        if (valid()) { await refresh(); status(tr('Evidence uploaded')); }
      });
    }
    evidence.off('.cfg_proof_tools').on('change.cfg_proof_tools', '.cfg-proof-camera input', function () { upload(this.files, 'photo', true); this.value=''; })
      .on('change.cfg_proof_tools', '.cfg-proof-file input', function () { upload(this.files, 'attachment'); this.value=''; })
      .on('click.cfg_proof_tools', '.cfg-view-proof', function () { const id=$(this).closest('[data-media-id]').data('media-id'); work(async () => {
        const result=await rpc('create_delivery_proof_view_url', {media_id:id}); if(valid())root.open(result.url, '_blank', 'noopener'); }); })
      .on('click.cfg_proof_tools', '.cfg-remove-proof', function () { const id=$(this).closest('[data-media-id]').data('media-id'); work(async () => {
        await rpc('archive_delivery_proof_media', {media_id:id}); if(valid()){rows=rows.filter(row=>row.media_id!==id);render();} }); });
    const canvas=signature.find('canvas')[0], ctx=canvas.getContext('2d'); ctx.strokeStyle='#111';ctx.lineWidth=3;ctx.lineCap='round';
    const point=event=>{const rect=canvas.getBoundingClientRect();return{x:(event.clientX-rect.left)*canvas.width/rect.width,y:(event.clientY-rect.top)*canvas.height/rect.height};};
    const down=event=>{if(!valid()||working)return;drawing=true;const p=point(event);ctx.beginPath();ctx.moveTo(p.x,p.y);canvas.setPointerCapture(event.pointerId);};
    const move=event=>{if(!drawing||!valid()||working)return;const p=point(event);ctx.lineTo(p.x,p.y);ctx.stroke();ink=true;};
    const up=()=>{drawing=false;};
    canvas.addEventListener('pointerdown',down);canvas.addEventListener('pointermove',move);canvas.addEventListener('pointerup',up);canvas.addEventListener('pointercancel',up);
    signature.off('.cfg_proof_tools').on('click.cfg_proof_tools','.cfg-clear-signature',()=>{if(!valid()||working)return;ctx.clearRect(0,0,canvas.width,canvas.height);ink=false;})
      .on('click.cfg_proof_tools','.cfg-save-signature',()=>{
        if(!valid()||working)return;if(!ink){status(tr('Ask the recipient to sign before saving.'));return;}
        // Count image encoding as work too, so submission cannot overtake the signature upload.
        work(async()=>{const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));if(!blob)throw new Error(tr('Could not prepare the signature.'));
          if(valid()){working=false;await upload([new root.File([blob],`recipient-signature-${Date.now()}.png`,{type:'image/png'})],'signature');}});
      });
    render();
    return {upload,refresh,busy:()=>working,close(){closed=true;drawing=false;evidence.off('.cfg_proof_tools');signature.off('.cfg_proof_tools');
      canvas.removeEventListener('pointerdown',down);canvas.removeEventListener('pointermove',move);canvas.removeEventListener('pointerup',up);canvas.removeEventListener('pointercancel',up);}};
  }
  const api={bind,geotag,stampPhoto,evidenceHTML,signatureHTML};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.cfg_delivery_proof_tools=api;
})(typeof window==='undefined'?globalThis:window);
