frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		frm.add_custom_button(__("Evaluate Kanban Demand"), async () => {
			const response = await frappe.call({ method: "cfg_kanban.services.sales_demand.evaluate_order",
				args: { sales_order: frm.doc.name }, freeze: true,
				freeze_message: __("Evaluating Kanban demand...") });
			const created = (response.message || []).filter((row) => row.status === "Waiting Approval").length;
			frappe.show_alert({ message: __("Kanban evaluation complete: {0} proposal(s) waiting approval", [created]),
				indicator: created ? "orange" : "green" });
			frappe.set_route("List", "CFG Kanban Demand", { sales_order: frm.doc.name });
		}, __("Create"));
	},
});
