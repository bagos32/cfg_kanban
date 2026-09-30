frappe.ui.form.on("CFG Kanban Logistics Route", {
	setup(frm) {
		frm.set_query("source_warehouse", () => ({ filters: {
			company: frm.doc.source_company || "", is_group: 0,
		} }));
		frm.set_query("transit_warehouse", () => ({ filters: {
			company: frm.doc.source_company || "", is_group: 0,
		} }));
		frm.set_query("destination_warehouse", () => ({ filters: {
			company: frm.doc.destination_company || "", is_group: 0,
		} }));
		frm.set_query("internal_customer", () => ({ filters: {
			is_internal_customer: 1,
		} }));
		frm.set_query("internal_supplier", () => ({ filters: {
			is_internal_supplier: 1,
		} }));
		frm.set_query("selling_price_list", () => ({ filters: { selling: 1 } }));
		frm.set_query("buying_price_list", () => ({ filters: { buying: 1 } }));
	},
});
