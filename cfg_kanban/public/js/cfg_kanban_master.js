frappe.ui.form.on("CFG Kanban Master", {
	setup(frm) {
		frm.set_query("bom", () => ({ filters: {
			item: frm.doc.item_code || "", is_active: 1, docstatus: 1,
		} }));
		frm.set_query("operation", "operator_field_definitions", () => ({
			query: "cfg_kanban.api.form_queries.master_operations",
			filters: { kanban_master: frm.doc.name || "" },
		}));
		frm.set_query("linked_operation", "process_task_profiles", () => ({
			query: "cfg_kanban.api.form_queries.master_operations",
			filters: { kanban_master: frm.doc.name || "" },
		}));
	},
	item_code(frm) {
		if (!frm.doc.item_code) return;
		frappe.db.get_value("Item", frm.doc.item_code, ["stock_uom", "default_bom"])
			.then(({ message }) => frm.set_value({
				stock_uom: message.stock_uom,
				bom: frm.doc.bom || message.default_bom,
			}));
	},
	production_policy(frm) {
		const mto = frm.doc.production_policy === "Customer Make-to-Order";
		if (mto && frm.doc.demand_scope !== "Customer") frm.set_value("demand_scope", "Customer");
		frm.set_df_property("threshold_source", "read_only", mto);
		if (mto) frm.set_value("threshold_source", "ERPNext Warehouse Reorder Level");
	},
	refresh(frm) {
		frm.trigger("production_policy");
		if (frm.doc.production_policy === "Customer Make-to-Order") {
			frm.set_intro(__("MTO mode creates one digital cycle and Batch per Sales Order line. It does not reserve reusable cards or use reorder stock."), "blue");
		}
	},
});

frappe.ui.form.on("CFG Kanban Operation Profile", {
	execution_mode(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, "allow_parallel", row.execution_mode === "Parallel Workstations" ? 1 : 0);
	},
});

frappe.ui.form.on("CFG Kanban Field Definition", {
	definition_scope(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.definition_scope === "Operation") frappe.model.set_value(cdt, cdn, "process_task_key", null);
		if (row.definition_scope === "Process Task") frappe.model.set_value(cdt, cdn, "operation", null);
	},
});
