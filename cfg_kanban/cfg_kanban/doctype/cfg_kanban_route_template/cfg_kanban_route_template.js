frappe.ui.form.on("CFG Kanban Route Template", {
 setup(frm) {
  frm.fields_dict.stops.grid.get_field("customer_scan_point").get_query=()=>({filters:{active:1,selling_company:frm.doc.company || ""}});
 },
});
