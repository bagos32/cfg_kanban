frappe.ui.form.on("CFG Kanban Dispatch Profile", {
	setup(frm) {
		frm.set_query("dispatch_point", () => ({
			filters: { card_type: "Location Card", location_purpose: "Dispatch Operations", active: 1, blocked: 0 },
		}));
		frm.set_query("source_warehouse", () => ({ filters: { company: frm.doc.company || "", is_group: 0 } }));
		for (const fieldname of ["destination_warehouse", "staging_warehouse", "transit_warehouse"]) {
			frm.set_query(fieldname, () => ({ filters: { company: frm.doc.company || "", is_group: 0 } }));
		}
		frm.set_query("customer_site", () => ({ filters: { selling_company: frm.doc.company || "", active: 1 } }));
		frm.set_query("logistics_route", () => ({ filters: { source_company: frm.doc.company || "", active: 1 } }));
		frm.set_query("dispatch_responsibility", () => ({ filters: { active: 1 } }));
	},
	dispatch_point(frm) {
		if (!frm.doc.dispatch_point) return;
		frappe.db.get_value("CFG Kanban Card", frm.doc.dispatch_point, ["company", "current_warehouse"])
			.then(({ message }) => frm.set_value({
				company: message.company,
				source_warehouse: message.current_warehouse,
			}));
	},
});
