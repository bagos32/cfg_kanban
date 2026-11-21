frappe.ui.form.on('CFG Kanban Route Template', {
  setup(frm) {
    frm.set_query('customer_scan_point', 'stops', () => ({filters: {selling_company: frm.doc.company, active: 1}}));
    frm.set_query('customer', 'stops', () => ({filters: {disabled: 0}}));
    frm.set_query('customer_address', 'stops', (_doc, cdt, cdn) => ({filters: [
      ['Dynamic Link', 'link_doctype', '=', 'Customer'], ['Dynamic Link', 'link_name', '=', locals[cdt][cdn].customer || '']]}));
    return frappe.require('/assets/cfg_kanban/js/office_delivery_trip.js');
  },
  async refresh(frm) {
    await frappe.require('/assets/cfg_kanban/js/office_delivery_trip.js');
    if (!frm.is_new()) {
      frm.add_custom_button(__('Open Delivery Trips'), () => frappe.set_route('List', 'CFG Kanban Delivery Trip', {route_template: frm.doc.name}));
      await window.cfg_office_delivery_trip.inbox(frm, 'order_inbox');
    }
  },
});
frappe.ui.form.on('CFG Kanban Route Template Stop', {
  customer_scan_point(frm, cdt, cdn) { return window.cfg_office_delivery_trip.site(frm, cdt, cdn); },
});
