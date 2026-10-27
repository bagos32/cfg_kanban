frappe.ui.form.on("CFG Kanban WIP Bin Pool", {
	pool_mode(frm) {
		frm.trigger("setup_bin_query");
	},
	company(frm) {
		frm.trigger("setup_bin_query");
	},
	wip_warehouse(frm) {
		frm.trigger("setup_bin_query");
	},
	setup_bin_query(frm) {
		frm.set_query("reusable_bin", "bins", () => ({ filters: {
			tag_kind: "Reusable Container",
			reusable_container_role: frm.doc.pool_mode === "Loose Multi-Item"
				? "Loose Multi-Item WIP Bin" : "Standard Quantity WIP Bin",
			inventory_company: frm.doc.company || "",
			current_warehouse: frm.doc.wip_warehouse || "",
			identity_state: ["in", ["Active", "Empty"]],
			quality_state: "Released",
		} }));
	},
	setup(frm) {
		frm.set_query("wip_warehouse", () => ({ filters: {
			company: frm.doc.company || "", is_group: 0, disabled: 0,
		} }));
		frm.trigger("setup_bin_query");
	},
	refresh(frm) {
		frm.set_intro(frm.doc.pool_mode === "Loose Multi-Item"
			? __("This pool authorizes controlled loose, multi-Item WIP accumulation for one Operation, Company, and ERPNext WIP Warehouse. Every physical bin has its own Item allow-list. Pool setup alone never moves stock.")
			: __("This pool authorizes fixed-capacity visual WIP bins for one Operation, Company, and ERPNext WIP Warehouse. Map every physical bin to its workstation; parallel workstations may share the pool. Pool setup alone never moves stock."), "blue");
	},
});
