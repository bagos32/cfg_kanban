frappe.ui.form.on("CFG Kanban WIP Bin Pool", {
	setup(frm) {
		frm.set_query("wip_warehouse", () => ({ filters: {
			company: frm.doc.company || "", is_group: 0, disabled: 0,
		} }));
		frm.set_query("reusable_bin", "bins", () => ({ filters: {
			tag_kind: "Reusable Container",
			reusable_container_role: "Standard Quantity WIP Bin",
			inventory_company: frm.doc.company || "",
			current_warehouse: frm.doc.wip_warehouse || "",
			identity_state: ["in", ["Active", "Empty"]],
			quality_state: "Released",
		} }));
	},
	refresh(frm) {
		frm.set_intro(__("This pool authorizes fixed-capacity visual WIP bins for one Operation, Company, and ERPNext WIP Warehouse. Map every physical bin to its workstation; parallel workstations may share the pool. Pool setup alone never moves stock."), "blue");
	},
});
