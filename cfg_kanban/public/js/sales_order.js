frappe.ui.form.on("Sales Order", {
	setup(frm) {
		if (frm.fields_dict.cfg_delivery_route) frm.set_query("cfg_delivery_route", () => ({ filters: [
			["CFG Kanban Route Template", "active", "=", 1],
			["CFG Kanban Route Template", "company", "=", frm.doc.company],
			["CFG Kanban Route Template Stop", "customer", "=", frm.doc.customer],
		] }));
	},
	refresh(frm) {
		if (!frm.is_new() && frm.doc.cfg_delivery_route) {
			frm.add_custom_button(__("Open Route Inbox"), () =>
				frappe.set_route("Form", "CFG Kanban Route Template", frm.doc.cfg_delivery_route));
		}
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
