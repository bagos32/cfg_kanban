frappe.ui.form.on('CFG Kanban Loose Tag', {
    refresh(frm) {
        frm.disable_save();
        if(!frm.is_new()) {
            frm.add_custom_button(__('View / Cancel Pack'),()=>{frappe.route_options={cfg_loose_tag:'CFG:LOOSE:'+frm.doc.name};frappe.set_route('kanban-logistics');});
            if(!['Cancelled','Building'].includes(frm.doc.state))frm.add_custom_button(__('Print Loose Tag'),()=>frm.print_doc());
        }
    }
});
