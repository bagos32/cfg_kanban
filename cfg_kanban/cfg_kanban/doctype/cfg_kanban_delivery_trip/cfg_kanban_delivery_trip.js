frappe.ui.form.on('CFG Kanban Delivery Trip', {
  async setup(frm) {
    frm.set_query('driver', () => ({ filters: { status: 'Active' } }));
    frm.set_query('route_template', () => ({ filters: { active: 1, company: frm.doc.company || '' } }));
    for (const name of ['source_warehouse', 'vehicle_warehouse']) frm.set_query(name, () => ({ filters: {
      company: frm.doc.company || '', is_group: 0, disabled: 0, ...(name === 'vehicle_warehouse' ? { cfg_is_vehicle_warehouse: 1 } : {}) } }));
    frm.fields_dict.stops.grid.get_field('customer_scan_point').get_query = () => ({ filters: { active: 1, selling_company: frm.doc.company || '' } });
    frm.fields_dict.stops.grid.get_field('customer_address').get_query = (_doc, cdt, cdn) => ({ filters: [
      ['Dynamic Link', 'link_doctype', '=', 'Customer'], ['Dynamic Link', 'link_name', '=', locals[cdt][cdn].customer || ''] ] });
    frm.fields_dict.dispatch_plans.grid.get_field('dispatch_plan').get_query = () => ({ filters: {
      company: frm.doc.company || '', plan_type: 'Customer Order', fulfilment_mode: 'Vehicle Delivery' } });
    await frappe.require('/assets/cfg_kanban/js/office_delivery_trip.js');
  },
  async refresh(frm) {
    await frappe.require('/assets/cfg_kanban/js/office_delivery_trip.js');
    const ui = window.cfg_office_delivery_trip;
    frm.fields_dict.planning_help.$wrapper.html(`<p class="text-muted">${__('Plan the trip here. Assigned order quantities are planning commitments; actual stock picking and loading use the linked Dispatch Plans. Load the last delivery stop first.')}</p>`);
    if (ui.editable(frm)) frm.add_custom_button(__('Load Route Template'), () => ui.loadTemplate(frm));
    frm.add_custom_button(__('Refresh SO Inbox'), () => ui.inbox(frm, 'order_inbox', true));
    if (!frm.is_new()) frm.add_custom_button(__('Refresh Loading Details'), () => ui.loading(frm));
    if (ui.editable(frm) && !frm.is_new()) {
      for (const state of ['Draft', 'Planned', 'Closed', 'Cancelled']) {
        if (state === frm.doc.state) continue;
        frm.add_custom_button(__(state === 'Draft' ? 'Return to Draft' : state === 'Planned' ? 'Mark Planned' : state === 'Closed' ? 'Close Planning' : 'Cancel Planning'), async () => {
          if (['Closed', 'Cancelled'].includes(state) && !(frm.doc.closure_reason || '').trim()) {
            ui.alert(frm, __('Enter Closure / Cancellation Reason in Notes and History first.')); return;
          }
          const previous = frm.doc.state;
          try { await frm.set_value('state', state); await frm.save(); }
          catch (error) { await frm.set_value('state', previous); ui.alert(frm, __('Planning status was not saved. Correct the reported error and save again.')); }
        }, __('Planning Status'));
      }
    }
    ui.renumber(frm);
    if (frm.doc.route_template) await ui.inbox(frm, 'order_inbox', true);
  },
  async route_template(frm) {
    if (window.cfg_office_delivery_trip && frm.doc.route_template && !(frm.doc.stops || []).length) await window.cfg_office_delivery_trip.loadTemplate(frm);
  },
  validate(frm) { window.cfg_office_delivery_trip?.renumber(frm); },
});
frappe.ui.form.on('CFG Kanban Delivery Trip Stop', {
  stops_add(frm, cdt, cdn) { locals[cdt][cdn].stop_key = 'S' + frappe.utils.get_random(20); window.cfg_office_delivery_trip?.renumber(frm); },
  stops_move(frm) { window.cfg_office_delivery_trip?.renumber(frm); },
  stops_remove(frm) { window.cfg_office_delivery_trip?.renumber(frm); },
  customer_scan_point(frm, cdt, cdn) { return window.cfg_office_delivery_trip.site(frm, cdt, cdn); },
});
frappe.ui.form.on('CFG Kanban Delivery Trip Plan', {
  stop_sequence(frm, cdt, cdn) {
    const row = locals[cdt][cdn]; const stop = (frm.doc.stops || [])[Number(row.stop_sequence) - 1];
    frappe.model.set_value(cdt, cdn, 'stop_key', stop?.stop_key || '');
  },
});
