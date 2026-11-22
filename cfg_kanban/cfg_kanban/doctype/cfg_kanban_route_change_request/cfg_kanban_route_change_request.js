frappe.ui.form.on('CFG Kanban Route Change Request', {
 refresh(frm) {
  frm.disable_save();
  if(!frm.is_new())frm.add_custom_button(__('Review in Supervisor Centre'),()=>{
   frappe.route_options={cfg_route_change_request:frm.doc.name};frappe.set_route('kanban-supervisor');
  });
 }
});
