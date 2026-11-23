/* A separate route view over the existing trip, loading and customer-delivery records. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.cfg_driver_route = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  const SESSION = 'cfg_kanban_operator_session';
  const service = 'cfg_kanban.services.driver_routes.';
  const maps=()=>typeof window!=='undefined'?window.cfg_delivery_maps:null;
  const tr = value => typeof __ === 'function' ? __(value) : value;
  const escape = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
  function scan(value) {
    const text = String(value || '').trim();
    try {
      const url = new URL(text);
      const operator = new URLSearchParams(url.hash.replace(/^#/, '')).get('operator');
      if (operator) return { kind: 'operator', value: operator };
      const match = url.pathname.match(/^\/app\/(?:kanban-driver-route|cfg-kanban-delivery-trip)\/([^/]+)\/?$/);
      if (match) return { kind: 'trip', value: decodeURIComponent(match[1]) };
      return { kind: 'unknown', value: text };
    } catch (_) { return { kind: /^KTRIP-[A-Za-z0-9-]+$/i.test(text) ? 'trip' : 'credential', value: text }; }
  }
  function expired(error) {
    return /operator session|scan your operator QR|operator profile is inactive|terminal login/i.test(message(error));
  }
  function message(error) {
    const value = error?.responseJSON || error;
    if (value?._server_messages) {
      try { return JSON.parse(value._server_messages).map(row => typeof row === 'string' ? JSON.parse(row).message : row.message).filter(Boolean).join(' '); } catch (_) { /* use fallback */ }
    }
    return error?.message || tr('Could not refresh the route. Retry Refresh.');
  }
  function controller({ call, storage, render, notify = () => {} }) {
    const state = { token: null, operator: null, trips: [], detail: null, selected: null, stop: null,
      start: 0, has_more: false, include_closed: false, busy: false, stale: false, error: '', active: true, can_view_all: false };
    let epoch = 0;
    const readToken = () => { try { return storage.getItem(SESSION); } catch (_) { return null; } };
    const emit = () => render(state);
    function clear() { state.operator = null; state.can_view_all = false; state.trips = []; state.detail = null; state.stop = null; state.error = ''; state.stale = false; }
    function sync() {
      const token = readToken();
      if (token === state.token) return;
      epoch++; clear(); state.token = token; state.busy = false; state.start = 0; state.selected = null;
      return true;
    }
    function valid(ticket, token) { return state.active && epoch === ticket && state.token === token && readToken() === token; }
    async function refresh(selected = state.selected, manual = true) {
      const previousToken = state.token, previousSelected = state.selected;
      const changed = sync();
      if (changed && previousToken && selected === previousSelected) selected = null;
      state.selected = selected || null;
      if (!state.token || !state.active) { emit(); return; }
      const token = state.token; const ticket = ++epoch;
      if (selected !== state.detail?.trip?.name) state.detail = null;
      state.busy = true; state.error = ''; emit();
      let listRead = false;
      try {
        const list = await call(service + 'get_driver_trips', { operator_session_token: token,
          include_closed: Number(state.include_closed), start: state.start, page_length: 20, interactive: Number(manual) });
        if (!valid(ticket, token)) return;
        listRead = true;
        state.operator = list.operator; state.can_view_all = Boolean(list.can_view_all); state.trips = list.trips || []; state.has_more = Boolean(list.has_more);
        if (!state.selected && state.operator?.employee) {
          try { state.selected = storage.getItem('cfg_driver_trip:' + state.operator.employee) || null; } catch (_) { /* optional preference */ }
        }
        if (state.selected) {
          const detail = await call(service + 'get_driver_trip', { trip_name: state.selected, operator_session_token: token, interactive: Number(manual) });
          if (!valid(ticket, token)) return;
          state.detail = detail;
          if (state.stop && !(detail.stops || []).some(row => row.stop_key === state.stop)) state.stop = null;
          try { storage.setItem('cfg_driver_trip:' + state.operator.employee, state.selected); } catch (_) { /* view still works */ }
        } else state.detail = null;
        state.stale = false;
      } catch (error) {
        if (!valid(ticket, token)) return;
        state.error = message(error); state.stale = true;
        // Denied ownership/permission must remove already displayed customer information.
        const rejected = Boolean(error?.exc_type || error?.responseJSON?.exc_type || error?._server_messages || error?.responseJSON?._server_messages);
        if (rejected && !listRead) { state.trips = []; state.operator = null; }
        if (expired(error) || rejected || manual) {
          state.detail = null;
          if (expired(error)) { clear(); state.token = null; try { if (readToken() === token) storage.removeItem(SESSION); } catch (_) {} state.error = message(error); }
        }
      } finally { if (readToken() !== state.token) { sync(); emit(); } else if (valid(ticket, token)) { state.busy = false; emit(); } else if (state.active && epoch === ticket && !state.token) { state.busy = false; emit(); } }
    }
    async function identify(value, pin, station) {
      const target = scan(value);
      if (target.kind === 'trip') { state.selected = target.value; notify(tr('Sign in as the assigned driver, then open this trip.')); return; }
      if (target.kind === 'unknown' || !target.value) { notify(tr('Scan the operator credential or enter its code.')); return; }
      if (state.busy && !state.token) return;
      const originalToken = readToken();
      const ticket = ++epoch; clear(); state.busy = true; emit();
      try {
        const result = await call('cfg_kanban.api.operator.login_operator', { token: target.value, pin: pin || '', station: station || '' });
        if (!state.active || epoch !== ticket) return;
        if (readToken() !== originalToken) { sync(); emit(); return; }
        try { storage.setItem(SESSION, result.session_token); } catch (_) { throw new Error(tr('Browser storage is unavailable. Allow storage and sign in again.')); }
        state.token = result.session_token; state.busy = false; return refresh(state.selected);
      } catch (error) { if (state.active && epoch === ticket) { state.error = message(error); state.busy = false; emit(); } }
    }
    return { state, refresh, identify,
      select(name) { state.stop = null; return refresh(name); },
      viewStop(key) { if (sync()) { emit(); return; } if (state.detail?.stops?.some(row => row.stop_key === key)) { state.stop = key; emit(); } },
      changeOperator() { epoch++; clear(); state.token = null; state.selected = null; state.busy = false; try { storage.removeItem(SESSION); } catch (_) {} emit(); },
      async scan(value, pin, station) {
        sync(); const target = scan(value);
        if (!state.token) return identify(value, pin, station);
        if (target.kind === 'trip') return this.select(target.value);
        notify(tr('Enter a Delivery Trip ID, or choose Change Operator to scan another credential.'));
      },
      async page(delta) { if (state.busy) return; state.start = Math.max(0, state.start + delta * 20); return refresh(); },
      async showClosed(value) { state.include_closed = value; state.start = 0; return refresh(); },
      show(name) { if (!state.active) { state.detail = null; state.trips = []; state.operator = null; } state.active = true; return refresh(name || state.selected); },
      hide() { state.active = false; epoch++; state.busy = false; },
      session() { if (sync()) emit(); return state.token; },
    };
  }
  function tripList(state) {
    return `<h3>${tr('My Delivery Trips')}</h3>${state.trips.map(row => `<button class="cfg-driver-trip btn btn-default${row.name === state.selected ? ' selected' : ''}" data-trip="${escape(row.name)}">
      <strong>${escape(row.trip_title || row.name)}</strong><span>${escape(row.name)} · ${escape(row.company)}</span>
      <span>${escape(row.trip_date)}${row.expected_return_date ? ' → ' + escape(row.expected_return_date) : ''} · ${escape(row.planning_state)} · ${escape(row.driver_route_state || tr('Not Started'))}</span>
      <span>${escape(row.vehicle_warehouse || tr('Lorry not yet assigned'))}</span></button>`).join('') || `<p class="text-muted">${tr('No trips on this page. The office must assign your Employee as the trip driver.')}</p>`}
      <div class="cfg-driver-pages"><button class="btn btn-default" data-page="-1"${state.start <= 0 || state.busy ? ' disabled' : ''}>${tr('Previous')}</button>
      <button class="btn btn-default" data-page="1"${!state.has_more || state.busy ? ' disabled' : ''}>${tr('Next')}</button></div>`;
  }
  function detailView(state) {
    const data = state.detail;
    if (!data) return `<div class="frappe-card p-4"><h3>${tr('Select a trip')}</h3><p>${tr('Choose your trip to see its next stop and the products assigned there.')}</p></div>`;
    const selected = (data.stops || []).find(row => row.stop_key === (state.stop || data.next_stop_key)) || data.stops?.[0];
    const next = (data.stops || []).find(row => row.stop_key === data.next_stop_key);
    const badge = data.current_stop_key ? tr('Current stop') : data.sequence_source === 'Approved Route Sheet' ? tr('Next delivery stop') : tr('Next planned stop');
    return `<section class="frappe-card cfg-driver-summary p-4"><div class="cfg-driver-summary-head"><div><h2>${escape(data.trip.trip_title || data.trip.name)}</h2>
      <p>${escape(data.trip.company)} · ${escape(data.trip.driver_route_state || tr('Not Started'))} · ${escape(data.vehicle_reference || data.vehicle_warehouse || tr('Lorry not yet assigned'))}</p></div>
      <span>${escape(data.completed_stops)} / ${escape(data.total_stops)} ${tr('stops complete')}${data.cancelled_stop_count?' · '+escape(data.cancelled_stop_count)+' '+tr('cancelled'):''}</span></div>
      <p><strong>${badge}:</strong> ${next ? escape(next.site_name || next.customer_name) + ' · ' + escape(next.state) : tr('No next stop recorded')}
      <br><small>${escape(data.sequence_source)} · ${tr('Updated')} ${escape(data.refreshed_on)}</small></p>
      ${maps()?.navigationHTML(state)||''}
      ${data.trip.planning_state === 'Planned' && (data.trip.driver_route_state || 'Not Started') === 'Not Started' ? `<button class="btn btn-primary cfg-driver-start-route">${tr('Start Route')}</button>` : ''}
      ${data.trip.driver_route_state && data.trip.driver_route_state !== 'Not Started' ? `<button class="btn btn-default cfg-driver-resume-route">${tr('Continue / Check saved action')}</button>` : ''}
      <p><strong>${tr('Assigned Driver')}:</strong> ${escape(data.trip.driver||'—')} · <strong>${tr('Assistant Drivers')}:</strong> ${(data.trip.assistant_drivers||[]).map(row=>escape(row.employee_name||row.employee)).join(', ')||'—'}</p>
      ${data.can_add_assistant?`<button class="btn btn-default cfg-driver-add-assistant">${tr('Add Assistant Driver')}</button>`:''}
      ${data.route_sequence?.can_change?`<button class="btn btn-default cfg-driver-order">${tr(data.route_sequence.enforced?'Request Stop Order Change':'Change Stop Order')}</button>`:''}
      ${data.route_sequence?.request?`<p class="alert alert-info">${tr(data.route_sequence.request.request_type||'Route change')}: ${escape(data.route_sequence.request.name)} · ${escape(data.route_sequence.request.state)} · ${escape(data.route_sequence.request.approval_mode||'')} ${escape(data.route_sequence.request.decision_reason||'')}${data.route_sequence.request.can_cancel?` <button class="btn btn-default cfg-driver-cancel-order">${tr(data.route_sequence.request.request_type==='Cancel Customer Stop'?'Withdraw Cancellation Request':'Cancel Route Request')}</button>`:''}</p>`:''}
      ${(data.warnings || []).map(warning => `<p class="alert alert-warning">${escape(warning)}</p>`).join('')}
      <div class="cfg-driver-map-slot"></div>
      <div class="cfg-driver-stops">${(data.stops || []).map(stop => `<button class="btn btn-default${selected?.stop_key === stop.stop_key ? ' selected' : ''}" data-stop="${escape(stop.stop_key)}"><strong>${escape(stop.sequence)}. ${escape(stop.site_name || stop.customer_name)}</strong><span>${escape(stop.state)}${stop.purpose === 'Visit Only' ? ' · ' + tr('Visit Only') : ''}</span></button>`).join('')}</div></section>
      ${selected ? stopView(selected, data.trip) + cancellationControl(selected,data,state) + returnView(data,selected,state) : ''}${cancelledView(data)}`;
  }
  function cancellationControl(stop,data,state){
    if(stop.driver_completed_on||['In Progress','Awaiting proof','Delivery Note pending','Awaiting stop completion','Review required','Completed','Completed with refusal','Cancelled'].includes(stop.state)||stop.plans?.some(p=>p.delivery_session)||(!data.can_cancel_stop&&!data.can_request_stop_cancellation))return '';
    return `<section class="frappe-card p-3 mt-3"><button class="btn btn-warning cfg-driver-cancel-stop" data-cancel-stop="${escape(stop.stop_key)}"${state.stale||state.busy?' disabled':''}>${tr(data.can_cancel_stop?'Cancel Customer Stop':'Request Stop Cancellation')}</button><p class="text-muted">${tr('Every cancellation needs Supervisor approval. Existing delivery/proof must be resolved first.')}</p></section>`;
  }
  function cancelledView(data){
    if(!data.cancelled_stops?.length)return '';
    return `<details class="frappe-card p-3 mt-3"><summary>${tr('Cancelled Customer Stops')} (${escape(data.cancelled_stops.length)})</summary>${data.cancelled_stops.map(row=>`<section class="mt-3"><strong>${escape(row.office_sequence)}. ${escape(row.site_name||row.customer_name)}</strong><p>${escape(row.cancelled_on)} · ${escape(row.cancelled_by)} · ${escape(row.cancellation_reason)}</p><p>${escape(row.stock_disposition)} · ${escape(row.cancellation_request)}</p>${(row.loaded_stock||[]).map(stock=>`<p>${escape(stock.visible_code||stock.item_code)} · ${escape(stock.qty)} ${escape(stock.stock_uom)} · ${escape(stock.stock_state)} · ${tr('Last recorded custody')}: ${escape(stock.current_warehouse)}</p>`).join('')}</section>`).join('')}</details>`;
  }
  function stopView(stop, trip) {
    return `<section class="frappe-card p-4 mt-3"><h3>${escape(stop.sequence)}. ${escape(stop.site_name || stop.customer_name)}</h3>
      <button class="btn btn-default cfg-driver-stop-print" data-print-stop="${escape(stop.stop_key)}">${tr('Documents / Print / Invoice')}</button>
      <p>${escape(stop.customer_name)} · ${escape(stop.purpose)} · <strong>${escape(stop.state)}</strong></p>
      <p class="cfg-driver-address">${escape(stop.address || tr('No address recorded'))}</p>
      <p class="text-muted">${stop.delivery_pin ? tr('Delivery Pin')+': '+escape(stop.delivery_pin.latitude)+', '+escape(stop.delivery_pin.longitude) : tr('Delivery pin not set; directions use the saved address.')}</p>
      ${stop.instructions ? `<p class="cfg-driver-instructions">${escape(stop.instructions)}</p>` : ''}
      ${stop.driver_visit_notes ? `<p class="cfg-driver-instructions"><strong>${tr('Visit notes')}:</strong> ${escape(stop.driver_visit_notes)}</p>` : ''}
      ${(stop.route_sheets || []).map(row => `<p class="text-muted">${escape(row.name)} · ${escape(row.planning_state)} · ${escape(row.sequence_policy)} · ${escape(row.verification_policy)}</p>`).join('')}
      ${(stop.warnings || []).map(row => `<p class="alert alert-warning">${escape(row)}</p>`).join('')}
      ${stop.can_open_sale ? `<button class="btn btn-primary cfg-driver-open-sale" data-sale-stop="${escape(stop.stop_key)}">${tr('Sell from Lorry')}</button>` : ''}
      ${stop.open_sale ? `<p>${tr('Open Route sale')}: ${escape(stop.open_sale.state)} · ${escape(stop.open_sale.delivery_note||'')}</p>`+(stop.open_sale.allocations||[]).map(row=>`<div class="cfg-driver-source"><strong>${escape(row.visible_code||row.item_code)}</strong><span>${escape(row.item_code)} · ${escape(row.batch_no||'—')} · ${escape(row.state)}</span><span>${tr('Selected')}: ${escape(row.allocated_qty)} ${escape(row.stock_uom)} · ${tr('Delivered')}: ${escape(row.delivered_qty||0)} ${escape(row.stock_uom)}</span></div>`).join('') : ''}
      ${stop.purpose === 'Visit Only' ? `<p class="alert alert-info">${tr('Use Sell from Lorry when this customer buys, or Complete Stop to record the visit without a sale.')}</p>` : ''}
      <div class="table-responsive"><table class="table table-bordered"><thead><tr><th>${tr('Product / Order / Customer PO')}</th><th>${tr('Planned')}</th><th>${tr('Loaded')}</th><th>${tr('Delivered')}</th><th>${tr('Not prepared')}</th><th>${tr('Remaining to deliver')}</th></tr></thead><tbody>
      ${(stop.items || []).map(row => `<tr><td><strong>${escape(row.item_code)}</strong> ${escape(row.item_name)}<br>${row.orders.map(order => escape(order.sales_order) + ' · ' + escape(order.customer_po || '—')).join('<br>')}</td>
      <td>${escape(row.planned_qty)} ${escape(row.stock_uom)}</td><td>${row.is_stock_item ? escape(row.loaded_qty) : '—'}</td><td>${row.is_stock_item ? escape(row.delivered_qty) : '—'}</td><td>${row.is_stock_item ? escape(row.unprepared_qty) : '—'}</td><td>${row.is_stock_item ? escape(row.remaining_qty) + ' ' + escape(row.stock_uom) : tr('Service item')}</td></tr>`).join('')}</tbody></table></div>
      <h4>${tr('Tags and untagged stock for this stop')}</h4>
      ${(stop.sources || []).map(row => `<div class="cfg-driver-source"><strong>${escape(row.tag_code || (row.allocation_kind === 'Untagged ERP Stock' ? tr('Untagged ERP stock') : tr('Tag not recorded')))}</strong>
      <span>${escape(row.item_code)} · ${tr('Batch')} ${escape(row.batch_no || '—')}</span><span>${tr('Remaining to deliver')}: <strong>${escape(row.remaining_qty)} ${escape(row.stock_uom)}</strong> · ${escape(row.source_state)}</span></div>`).join('') || `<p class="text-muted">${tr('No prepared stock tags or untagged allocations are recorded for this stop.')}</p>`}
      ${trip.driver_route_state === 'In Progress' && !stop.driver_completed_on ? `<button class="btn btn-primary cfg-driver-complete-stop" data-complete-stop="${escape(stop.stop_key)}">${tr('Complete Stop')}</button>` : ''}
      ${(stop.plans || []).filter(row => row.session_accessible && row.delivery_session && !['Closed', 'Cancelled'].includes(row.session_state)).map(row => `<button class="btn btn-primary cfg-driver-open-delivery" data-delivery="${escape(row.delivery_session)}">${tr('Open existing delivery')} · ${escape(row.name)}</button>`).join('')}
      <p class="text-muted mt-3"><small>${tr('Remaining quantities are assigned deliveries, not free lorry stock. Complete Stop guides the existing Delivery Note and required proof workflow.')}</small></p></section>`;
  }
  function returnView(data,stop,state) {
    const cases=(data.return_cases||[]).filter(row=>row.stop_key===stop.stop_key);
    const outcomes=[...new Set((stop.sources||[]).filter(row=>['Held','Transferred Hold'].includes(row.refused_stock_state)).map(row=>row.refusal_outcome))];
    return `<section class="frappe-card p-4 mt-3"><h4>${tr('Refusals and collected returns')}</h4>
      ${(stop.sources||[]).filter(row=>row.refused_qty>0).map(row=>`<p>${escape(row.item_code)} · ${escape(row.refused_qty)} ${escape(row.stock_uom)} ${tr('refused')} · ${escape(row.refused_stock_state)} · ${escape(row.refused_warehouse||'')} · ${escape(row.qc_return_case||'')}</p>`).join('')}
      ${data.trip.planning_state==='Planned'&&['In Progress','Completed'].includes(data.trip.driver_route_state)?`<button class="btn btn-primary cfg-driver-collect-return" data-collect-stop="${escape(stop.stop_key)}">${tr('Collect Old Customer Return')}</button>`:''}
      ${state.can_view_all&&state.operator?.can_override?outcomes.map(name=>`<button class="btn btn-default cfg-driver-release-refused" data-release-stop="${escape(stop.stop_key)}" data-outcome="${escape(name)}">${tr('Release Refused Stock')} · ${escape(name)}</button>`).join(''):''}
      ${cases.map(row=>`<p><strong>${escape(row.name)}</strong> · ${escape(row.state)} · ${row.stock_already_owned?tr('Company-owned refusal; no credit/receipt'):tr('Old customer goods; awaiting QC/accounting workflow')}<br>${tr('Inspection')}: ${escape(row.inspection_location)} · ${tr('QC finished')}: ${escape(row.qc_completed_on||'—')}<br>
        <a class="btn btn-default" target="_blank" rel="noopener" href="/printview?doctype=CFG%20Kanban%20Return%20Case&name=${encodeURIComponent(row.name)}&format=CFG%20Temporary%20Return%20Note&no_letterhead=1">${row.stock_already_owned?tr('Refusal QC Note'):tr('Temporary Return Note')}</a> <a class="btn btn-default" href="/app/cfg-kanban-return-case/${encodeURIComponent(row.name)}">${tr('Open Return Case')}</a></p>`).join('')}
      </section>`;
  }
  function mount(wrapper) {
    const page = frappe.ui.make_app_page({ parent: wrapper, title: tr('Driver Route'), single_column: true });
    const $root = $('<div class="cfg-driver-route"></div>').appendTo(page.main);
    $root.html(`<section class="frappe-card cfg-driver-toolbar p-3"><div class="cfg-driver-identity"></div><div class="cfg-driver-scan-row"><input class="form-control cfg-driver-scan" autocomplete="off" placeholder="${tr('Operator credential or Delivery Trip ID')}">
      <input class="form-control cfg-driver-pin" type="password" autocomplete="off" placeholder="${tr('PIN if required')}">
      <button class="btn btn-primary cfg-driver-confirm">${tr('Open / Sign in')}</button><button class="btn btn-default cfg-driver-camera">${tr('Scan with Camera')}</button>
      <button class="btn btn-default cfg-driver-change">${tr('Change Operator')}</button><button class="btn btn-default cfg-driver-refresh">${tr('Refresh')}</button></div>
      <label class="mt-2"><input type="checkbox" class="cfg-driver-closed"> ${tr('Show closed trips')}</label><div class="cfg-driver-notice" role="status" aria-live="polite"></div></section>
      <div class="cfg-driver-gps-host"></div><div class="cfg-driver-layout"><aside class="cfg-driver-list"></aside><main><div class="cfg-driver-detail"></div><div class="cfg-driver-print-launch mt-3"></div><div class="cfg-driver-action-host"></div></main></div>`);
    const input = $root.find('.cfg-driver-scan'); let camera = null, cameraEpoch = 0, timer = null, action = null, routeMap = null, gps = null;
    const notice = text => $root.find('.cfg-driver-notice').text(text || '');
    const app = controller({ storage: localStorage,
      call: async (method, args) => (await frappe.call({ method, args })).message,
      notify: notice, render(state) {
        if(!state.active||!state.token||!state.operator||!state.detail||state.stale)window.cfg_driver_mobile_print?.forget?.();
        if (action && (!state.active || !state.token || !state.operator || !state.detail || state.stale)) action.close();
        $root.find('.cfg-driver-identity').text(state.operator ? `${state.operator.employee_name || state.operator.employee} · ${state.operator.employee}` : tr('Sign in with your operator credential'));
        $root.find('.cfg-driver-pin').toggle(!state.token); $root.find('.cfg-driver-confirm').prop('disabled', state.busy);
        const source=gps?.controller.state;
        if(state.detail&&source?.binding?.trip===state.detail.trip.name&&source.gps)state.detail.vehicle_locations=[{trip:state.detail.trip,gps:source.gps}];
        gps?.context(state);
        routeMap?.detach();
        $root.find('.cfg-driver-print-launch').html(state.detail&&state.operator&&!state.stale?'<button class="btn btn-default cfg-driver-print-documents">Documents / Print / Invoice</button>':'');
        $root.find('.cfg-driver-list').html(tripList(state)); $root.find('.cfg-driver-detail').html(detailView(state));
        routeMap?.update(state,$root.find('.cfg-driver-map-slot')[0]);
        notice(state.error ? (state.stale ? tr('Not refreshed') + ': ' : '') + state.error : state.busy ? tr('Refreshing…') : '');
      },
    });
    routeMap=maps()?.createRouteMap({frappe,
      identity:()=>{let token;try{token=localStorage.getItem(SESSION);}catch(_){return null;}return app.state.active&&frappe.get_route()?.[0]==='kanban-driver-route'&&token&&token===app.state.token&&app.state.operator?.employee?`${token}:${app.state.operator.employee}:${app.state.selected}`:null;},
      pick:key=>{if(action||!app.session()||!app.state.active||app.state.stale||app.state.busy)return;app.viewStop(key);},
    });
    gps=window.cfg_trip_gps?.bind({frappe,host:$root.find('.cfg-driver-gps-host'),storage:sessionStorage,deviceStorage:localStorage,locks:navigator.locks,
      nonce:()=>crypto.randomUUID(),owner:()=>app.state.operator?.employee,token:()=>app.state.token,trip:()=>app.state.selected,
      active:()=>app.state.active&&frappe.get_route()?.[0]==='kanban-driver-route'&&!document.hidden,error:message,
      supervisor:()=>app.state.can_view_all&&app.state.operator?.can_override,
      position:(trip,location)=>{if(app.state.detail?.trip.name===trip){app.state.detail.vehicle_locations=[{trip:app.state.detail.trip,gps:window.cfg_delivery_maps.observeGPS(location)}];routeMap?.update(app.state,$root.find('.cfg-driver-map-slot')[0]);}},
    });
    app.hide(); // A late asset load must not activate an already hidden Desk page.
    const focus = () => action ? action.focus() : input.trigger('focus');
    async function submit(value) { if(String(value??input.val()).trim().toUpperCase()==='CFG:CMD:MOBILE_PRINT'&&!action){input.val('');return printDocuments();} const command=String(value??input.val()).trim();if(command.toUpperCase()==='CFG:CMD:CANCEL_CUSTOMER_STOP'&&!action){input.val('');const key=app.state.stop||app.state.detail?.next_stop_key;if(!key){notice(tr('Select an unstarted customer stop first.'));focus();return;}return execute(key,'Cancel Customer Stop');} const text=String(value??input.val()).trim();if(/^CFG:CMD:GPS_(SHARE|STOP|REFRESH)$/.test(text)&&!action){input.val('');try{return await gps?.scan(text);}finally{focus();}} if (action) { const scan = value ?? input.val(); input.val(''); return action.scan(scan); } try { let station = ''; try { station = localStorage.getItem('cfg_kanban_station') || ''; } catch (_) {} await app.scan(value ?? input.val(), $root.find('.cfg-driver-pin').val(), station); input.val(''); $root.find('.cfg-driver-pin').val(''); } finally { focus(); } }
    function stopCamera() { cameraEpoch++; try { camera?.stop_scan?.(); camera?.dialog?.hide?.(); } catch (_) {} camera = null; }
    $root.on('keydown.cfg_driver', '.cfg-driver-scan', event => {
      if (!['Enter', 'Tab'].includes(event.key) || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey || event.isComposing || !String(input.val() || '').trim()) return;
      event.preventDefault(); event.stopPropagation(); submit();
    });
    $root.on('click.cfg_driver', '.cfg-driver-confirm', () => submit());
    $root.on('click.cfg_driver', '.cfg-driver-trip', event => { action?.close(); return app.select($(event.currentTarget).attr('data-trip')); });
    $root.on('click.cfg_driver', '[data-stop]', event => { action?.close(); return app.viewStop($(event.currentTarget).attr('data-stop')); });
    $root.on('click.cfg_driver', '[data-page]', event => app.page(Number($(event.currentTarget).attr('data-page'))));
    $root.on('change.cfg_driver', '.cfg-driver-closed', event => app.showClosed(event.currentTarget.checked));
    $root.on('click.cfg_driver', '.cfg-driver-change', async () => { window.cfg_driver_mobile_print?.forget?.(); action?.close(); stopCamera(); await gps?.operatorChanged(); app.changeOperator(); focus(); });
    $root.on('click.cfg_driver', '.cfg-driver-refresh', () => action ? action.refresh() : app.refresh());
    function execute(stop, operation, outcome) {
      if (action || !app.session() || !app.state.detail || app.state.stale || app.state.busy) return;
      stopCamera();
      try {
        action = window.cfg_driver_route_actions.open({frappe, host:$root.find('.cfg-driver-action-host'),
          trip:app.state.selected, stop:stop || null, operation, outcome, owner:()=>app.state.operator?.employee, token:()=>app.session(),
          active:()=>app.state.active && route(), detail:()=>app.state.detail,
          refresh:()=>app.refresh(app.state.selected, true), storage:localStorage, locks:navigator.locks,
          nonce:()=>crypto.randomUUID(), error:message, supervisor:()=>app.state.can_view_all && app.state.operator?.can_override && ['Supervisor','Development Proxy'].includes(app.state.operator?.kanban_role),
          onClose:()=>{action=null;focus();}});
      } catch(error) { $root.find('.cfg-driver-action-host').empty(); notice(message(error)); focus(); }
    }
    function printDocuments(stopKey=null) {
      if(action||!app.session()||!app.state.detail||app.state.stale||app.state.busy)return;
      stopCamera();
      try { action=window.cfg_driver_mobile_print.open({frappe,host:$root.find('.cfg-driver-action-host'),
        trip:app.state.selected,stop:stopKey||app.state.stop||app.state.detail.next_stop_key||null,
        owner:()=>app.state.operator?.employee,token:()=>app.session(),active:()=>app.state.active&&route(),
        refresh:()=>app.refresh(app.state.selected,true),storage:localStorage,locks:navigator.locks,
        nonce:()=>crypto.randomUUID(),error:message,onClose:()=>{action=null;focus();}});
      }catch(error){$root.find('.cfg-driver-action-host').empty();notice(message(error));focus();}
    }
    $root.on('click.cfg_driver','.cfg-driver-print-documents',()=>printDocuments());
    $root.on('click.cfg_driver','.cfg-driver-stop-print',event=>printDocuments($(event.currentTarget).attr('data-print-stop')));
    $root.on('click.cfg_driver','.cfg-driver-cancel-stop',event=>execute($(event.currentTarget).attr('data-cancel-stop'),'Cancel Customer Stop'));
    $root.on('click.cfg_driver','.cfg-driver-order',()=>execute(null,'Change Route Order'));
    $root.on('click.cfg_driver','.cfg-driver-cancel-order',()=>execute(null,'Cancel Route Change'));
    $root.on('click.cfg_driver','.cfg-driver-add-assistant',()=>execute(null,'Add Assistant'));
    $root.on('click.cfg_driver','.cfg-driver-open-sale',event=>execute($(event.currentTarget).attr('data-sale-stop'),'Sell from Lorry'));
    $root.on('click.cfg_driver', '.cfg-driver-collect-return', event => execute($(event.currentTarget).attr('data-collect-stop'),'Collect Old Return'));
    $root.on('click.cfg_driver', '.cfg-driver-release-refused', event => execute($(event.currentTarget).attr('data-release-stop'),'Release Refused Stock',$(event.currentTarget).attr('data-outcome')));
    $root.on('click.cfg_driver', '.cfg-driver-start-route', () => execute());
    $root.on('click.cfg_driver', '.cfg-driver-resume-route', () => execute(app.state.stop || app.state.detail?.next_stop_key));
    $root.on('click.cfg_driver', '.cfg-driver-complete-stop', event => execute($(event.currentTarget).attr('data-complete-stop')));
    $root.on('click.cfg_driver', '.cfg-driver-open-delivery', event => {
      const name = $(event.currentTarget).attr('data-delivery');
      action?.close();
      if (!app.session() || app.state.stale || !app.state.detail?.stops?.some(stop => stop.plans.some(plan => plan.session_accessible && plan.delivery_session === name)||stop.open_sale?.delivery_session===name)) return;
      frappe.route_options = { cfg_driver_delivery_session: name }; frappe.set_route('kanban-logistics');
    });
    $root.on('click.cfg_driver','.cfg-driver-directions',event=>{if(!app.session()||!app.state.operator||!app.state.detail||app.state.stale||app.state.busy||!app.state.active){event.preventDefault();notice(tr('Refresh the route before opening directions.'));}});
    $root.on('click.cfg_driver', '.cfg-driver-camera', () => {
      stopCamera(); if (!frappe.ui.Scanner) { notice(tr('Camera scanning is unavailable. Use the scanner field.')); focus(); return; }
      const ticket = cameraEpoch, token = app.session(); let accepted = false;
      try { camera = new frappe.ui.Scanner({ dialog: true, multiple: false, on_scan(data) {
        if (accepted || ticket !== cameraEpoch || !app.state.active || !route() || app.session() !== token) return;
        accepted = true; stopCamera(); submit(String(data.decodedText || '').trim());
      } }); camera.dialog?.$wrapper?.on('hidden.bs.modal.cfg_driver', () => { cameraEpoch++; focus(); }); }
      catch (_) { notice(tr('Could not start the camera. Use the scanner field.')); focus(); }
    });
    const route = () => frappe.get_route()?.[0] === 'kanban-driver-route';
    function tick() { if (route() && !document.hidden && !app.state.busy && !action) app.refresh(app.state.selected, false); }
    function storageChanged(event) { if (event.key === SESSION && app.state.active) { window.cfg_driver_mobile_print?.forget?.(); action?.close(); stopCamera(); gps?.operatorChanged(); app.refresh(); } }
    window.addEventListener('storage', storageChanged);
    document.addEventListener?.('visibilitychange',()=>{if(document.hidden)gps?.hide();else if(app.state.active){gps?.show();tick();}});
    const lifecycle = {
      async show(name) { if (!timer) timer = setInterval(tick, 15000); await app.show(name); if(!document.hidden)await gps?.show(); focus(); },
      hide() { window.cfg_driver_mobile_print?.forget?.(); gps?.hide(); action?.close(); stopCamera(); routeMap?.clear(); app.hide(); if (timer) clearInterval(timer); timer = null; }, app,
    };
    frappe.router?.on?.('change', () => { if (!route()) lifecycle.hide(); });
    return lifecycle;
  }
  return { controller, scan, expired, message, tripList, detailView, mount, escape,cancelledView,cancellationControl };
});
