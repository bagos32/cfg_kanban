frappe.ui.form.on('CFG Kanban Trip GPS',{
 refresh(frm){frm.disable_save();if(!frm.is_new())frm.add_custom_button(__('Supervisor Live Map'),()=>{
  frappe.route_options={cfg_trip_monitor_trip:frm.doc.delivery_trip};frappe.set_route('kanban-trip-monitor');
 });}
});
