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
	route_type(frm) {
		const internal = frm.doc.route_type === "Internal Warehouse Transfer";
		["internal_customer", "internal_supplier", "selling_price_list", "buying_price_list", "billing_frequency"]
			.forEach((fieldname) => frm.toggle_reqd(fieldname, !internal));
		frm.toggle_reqd("internal_transfer_mode", internal);
		frm.toggle_reqd("transit_warehouse", internal && frm.doc.internal_transfer_mode === "Goods in Transit");
		if (internal && frm.doc.source_company) frm.set_value("destination_company", frm.doc.source_company);
	},
	internal_transfer_mode(frm) {
		frm.toggle_reqd(
			"transit_warehouse",
			frm.doc.route_type === "Internal Warehouse Transfer" && frm.doc.internal_transfer_mode === "Goods in Transit"
		);
	},
	source_company(frm) {
		if (frm.doc.route_type === "Internal Warehouse Transfer" && frm.doc.source_company) {
			frm.set_value("destination_company", frm.doc.source_company);
		}
	},
	refresh(frm) {
		frm.trigger("route_type");
	},
});
