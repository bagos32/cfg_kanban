/* Normal Desk forms share one route inbox; stock execution remains in Dispatch Plans. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.cfg_office_delivery_trip = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  const service = 'cfg_kanban.services.delivery_trips.';
  const e = value => frappe.utils.escape_html(String(value ?? ''));
  const terminal = frm => ['Closed', 'Cancelled'].includes(frm.doc.state);
  const editable = frm => !terminal(frm) && (frm.is_new() || Boolean(frm.perm?.[0]?.write));
  const call = async (method, args) => (await frappe.call({ method: service + method, args, freeze: true })).message;
  function alert(frm, message, color = 'orange') {
    frm.dashboard.set_headline_alert(message, color);
  }
  function stopOptions(frm, row) {
    return (frm.doc.stops || []).filter(stop => (stop.stop_purpose || 'Delivery') === 'Delivery' &&
      !stop.cancellation_request && stop.customer === row.customer && stop.customer_scan_point &&
      (!row.customer_address || stop.customer_address === row.customer_address));
  }
  function inboxStops(frm) {
    return JSON.stringify((frm.doc.stops || []).map(row => Object.fromEntries(
      ['stop_key', 'stop_purpose', 'customer_scan_point', 'customer', 'customer_address', 'cancellation_request']
        .map(field => [field, row[field] || null]))));
  }
  function assign(frm, source, qty, stopKey) {
    if (!editable(frm) || !source.assignable) throw new Error(__('This order is not assignable'));
    const stop = stopOptions(frm, source).find(row => row.stop_key === stopKey);
    if (!stop) throw new Error(__('Choose the exact customer delivery stop'));
    if (!Number.isFinite(qty) || qty <= 0 || qty > Number(source.available_qty) + 0.000001) {
      throw new Error(__('Assigned quantity must fit the displayed available stock quantity'));
    }
    let row = (frm.doc.orders || []).find(row => row.sales_order === source.sales_order && row.sales_order_item === source.sales_order_item);
    if (!row) row = frm.add_child('orders');
    Object.assign(row, { stop_key: stopKey, stop_sequence: (frm.doc.stops || []).indexOf(stop) + 1,
      sales_order: source.sales_order, sales_order_item: source.sales_order_item,
      customer: source.customer, customer_po: source.customer_po, item_code: source.item_code,
      item_name: source.item_name, stock_uom: source.stock_uom, planned_qty: qty, delivery_date: source.delivery_date });
    frm.dirty(); frm.refresh_field('orders');
    alert(frm, __('Assignment updated. Save the Delivery Trip to validate the current order balance.'), 'blue');
    return row;
  }
  async function inbox(frm, fieldname, trip = false, start = 0) {
    const route = trip ? frm.doc.route_template : frm.doc.name;
    const wrapper = frm.fields_dict[fieldname].$wrapper;
    if ((trip && terminal(frm)) || (!trip && !frm.doc.active)) {
      frm.__cfg_inbox_epoch = (frm.__cfg_inbox_epoch || 0) + 1;
      wrapper.html(`<div class="text-muted p-3">${__('This record is historical or inactive. Its saved planning details remain available.')}</div>`); return;
    }
    if (!route || (!trip && frm.is_new())) {
      wrapper.html(`<div class="text-muted p-3">${__('Select and save a Standard Route / Template to view its Sales Orders.')}</div>`); return;
    }
    const token = (frm.__cfg_inbox_epoch || 0) + 1; frm.__cfg_inbox_epoch = token;
    const company = frm.doc.company;
    const stops = trip ? inboxStops(frm) : null;
    const tripName = trip && !frm.is_new() ? frm.doc.name : null;
    const data = await call('get_route_order_inbox', { route_template: route, company,
      trip_name: tripName, ...(trip ? { trip_stops: stops } : {}), start, page_length: 30 });
    if (frm.__cfg_inbox_epoch !== token || frm.doc.company !== company || (trip ? frm.doc.route_template : frm.doc.name) !== route ||
        (trip && (terminal(frm) || (frm.is_new() ? null : frm.doc.name) !== tripName || inboxStops(frm) !== stops))) return;
    frm.__cfg_inbox = data;
    const rows = data.rows || [];
    wrapper.html(`<div class="mb-3"><strong>${__(trip ? 'SO Inbox for Trip Stops' : 'SO Route Inbox')}</strong><p class="text-muted">${trip ? __('Delivery stops include matching Sales Orders with this preset route or no preset route. Add the Customer Site to the Trip, then refresh orders. Orders for another preset route remain excluded.') + ' ' : ''}${__('Saved drafts are shown for information. Only submitted open orders can be assigned. Quantities are in stock UOM; assignment does not reserve ERP stock.')}</p>
      <button class="btn btn-default btn-sm" data-action="refresh">${__('Refresh Orders')}</button>
      ${!trip && frappe.model.can_create('CFG Kanban Delivery Trip') ? `<button class="btn btn-primary btn-sm" data-action="new">${__('New Delivery Trip')}</button>` : ''}</div>
      <div class="table-responsive"><table class="table table-bordered"><thead><tr>
      <th>${__('Sales Order / Customer PO')}</th><th>${__('Customer / Item')}</th><th>${__('Delivery Date / UOM')}</th>
      <th>${__('Ordered / Delivered')}</th><th>${__('Planned Elsewhere / Here')}</th><th>${__('Unassigned')}</th>
      ${trip ? `<th>${__('Assign to Stop')}</th><th>${__('Stock Qty')}</th><th></th>` : ''}</tr></thead><tbody>
      ${rows.map((row, index) => {
        const choices = trip ? stopOptions(frm, row) : [];
        const existing = (frm.doc.orders || []).find(item => item.sales_order === row.sales_order && item.sales_order_item === row.sales_order_item);
        const selected = existing?.stop_key || (choices.length === 1 ? choices[0].stop_key : '');
        return `<tr data-index="${index}"><td><a href="/app/sales-order/${encodeURIComponent(row.sales_order)}">${e(row.sales_order)}</a><br>${e(row.customer_po || '—')}<br><small>${e(row.status)}</small><br><small>${e(row.standard_route || __('No preset route'))}</small></td>
        <td>${e(row.customer_name)}<br><strong>${e(row.item_code)}</strong> ${e(row.item_name)}</td><td>${e(row.delivery_date)}<br>${e(row.stock_uom)}</td>
        <td>${e(row.ordered_qty)} / ${e(row.delivered_qty)}</td><td>${e(row.assigned_elsewhere)} / ${e(row.assigned_here)}</td><td>${e(row.unassigned_qty)}</td>
        ${trip ? `<td><select class="form-control cfg-stop"><option value="">${__('Choose stop')}</option>${choices.map(stop => `<option value="${e(stop.stop_key)}"${stop.stop_key === selected ? ' selected' : ''}>${e((frm.doc.stops || []).indexOf(stop) + 1)} · ${e(stop.site_name || stop.customer)} · ${e(stop.customer_address || '')}</option>`).join('')}</select></td>
        <td><input class="form-control cfg-qty" type="number" min="0" step="0.000001" value="${e(existing?.planned_qty ?? row.unassigned_qty)}"></td>
        <td><button class="btn btn-primary btn-sm" data-action="assign"${!editable(frm) || !row.assignable || !choices.length ? ' disabled' : ''}>${__('Assign / Update')}</button></td>` : ''}</tr>`;
      }).join('') || `<tr><td colspan="9" class="text-muted">${__('No open Sales Order lines on this page.')}</td></tr>`}</tbody></table></div>
      <button class="btn btn-default btn-sm" data-action="previous"${start <= 0 ? ' disabled' : ''}>${__('Previous')}</button>
      <button class="btn btn-default btn-sm" data-action="next"${!data.has_more ? ' disabled' : ''}>${__('Next')}</button>`);
    wrapper.off('.cfg_trip').on('click.cfg_trip', 'button[data-action]', async event => {
      const button = $(event.currentTarget); const action = button.attr('data-action');
      try {
        if (action === 'refresh') return inbox(frm, fieldname, trip, start);
        if (action === 'previous') return inbox(frm, fieldname, trip, Math.max(0, start - data.page_length));
        if (action === 'next') return inbox(frm, fieldname, trip, start + data.page_length);
        if (action === 'new') return frappe.new_doc('CFG Kanban Delivery Trip', { company, route_template: route });
        if (action === 'assign') {
          const tr = button.closest('tr'); const source = rows[Number(tr.attr('data-index'))];
          assign(frm, source, Number(tr.find('.cfg-qty').val()), tr.find('.cfg-stop').val());
        }
      } catch (error) { alert(frm, e(error.message || __('Could not update this assignment'))); }
    });
  }
  async function loadTemplate(frm) {
    if (!editable(frm)) throw new Error(__('This planning record is closed'));
    if ((frm.doc.orders || []).length || (frm.doc.dispatch_plans || []).length) {
      alert(frm, __('Save the trip without order assignments and linked Plans before replacing its stops.')); return;
    }
    if (!frm.doc.route_template) { alert(frm, __('Select a Standard Route / Template first.')); return; }
    const route = frm.doc.route_template; const company = frm.doc.company;
    const data = await call('get_route_template', { route_template: route, company });
    if (frm.doc.route_template !== route || frm.doc.company !== company ||
        (frm.doc.orders || []).length || (frm.doc.dispatch_plans || []).length || !editable(frm)) return;
    for (const field of ['company', 'template_revision', 'template_snapshot_json', 'region', 'direction', 'sequence_policy', 'auto_generate_dispatch', 'dispatch_profile', 'open_route_profile', 'gps_auto_start', 'gps_publish_interval_seconds']) await frm.set_value(field, data[field]);
    frm.clear_table('stops');
    for (const values of data.stops) Object.assign(frm.add_child('stops'), values);
    frm.refresh_field('stops'); frm.dirty(); await inbox(frm, 'order_inbox', true);
  }
  function renumber(frm) {
    const positions = {};
    (frm.doc.stops || []).forEach((stop, index) => { stop.delivery_sequence = index + 1; positions[stop.stop_key] = index + 1; });
    frm.refresh_field('stops');
    for (const field of ['orders', 'dispatch_plans']) {
      (frm.doc[field] || []).forEach(row => { if (positions[row.stop_key]) row.stop_sequence = positions[row.stop_key]; });
      frm.refresh_field(field);
    }
  }
  async function site(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.customer_scan_point) { await frappe.model.set_value(cdt, cdn, 'site_name', ''); return; }
    const name = row.customer_scan_point;
    const { message } = await frappe.db.get_value('CFG Kanban Customer Scan Point', name,
      ['customer', 'customer_address', 'site_name']);
    if (locals[cdt]?.[cdn]?.customer_scan_point !== name) return;
    if (message) for (const field of ['customer', 'customer_address', 'site_name']) await frappe.model.set_value(cdt, cdn, field, message[field]);
  }
  async function loading(frm) {
    if (frm.is_new() || frm.is_dirty()) { alert(frm, __('Save the trip before refreshing its current source details.')); return; }
    const name = frm.doc.name;
    const data = await call('get_loading_sequence', { trip_name: name });
    if (frm.doc.name !== name || frm.is_dirty()) return;
    frm.fields_dict.loading_live.$wrapper.html(`<p class="text-muted">${__('Current source details as of')} ${e(data.refreshed_on)}. ${__('Saved loading instructions update when the trip is saved.')}</p>
      <div class="table-responsive"><table class="table table-bordered"><thead><tr><th>${__('Load')}</th><th>${__('Delivery Stop')}</th><th>${__('Customer / Item')}</th><th>${__('Stock Qty')}</th><th>${__('Tag / Batch')}</th><th>${__('Stock Kind / Stage')}</th></tr></thead><tbody>
      ${(data.rows || []).map(row => `<tr><td>${e(row.loading_sequence)}</td><td>${e(row.delivery_sequence)}</td><td>${e(row.customer)} · ${e(row.item_code)}</td><td>${e(row.qty)} ${e(row.stock_uom)}</td><td>${e(row.tag_code || '—')} / ${e(row.batch_no || '—')}</td><td>${e(row.allocation_kind)} · ${e(row.source_state)}</td></tr>`).join('')}</tbody></table></div>`);
  }
  return { inbox, assign, stopOptions, loadTemplate, renumber, site, loading, editable, alert };
});
