frappe.ui.form.on("Work Order", {
	refresh(frm) {
		if (!frm.doc.cfg_kanban_cycle) return;
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Reload BOM Details"), async () => {
				const response = await frappe.call({
					method: "cfg_kanban.integrations.erp_gateway.reload_draft_work_order_bom",
					args: { work_order_name: frm.doc.name }, freeze: true,
					freeze_message: __("Loading BOM materials and operations..."),
				});
				frappe.show_alert({ message: __("Loaded {0} operation(s) and {1} material row(s)",
					[response.message.operations, response.message.required_items]), indicator: "green" });
				frm.reload_doc();
			}, __("Kanban"));
			return;
		}
		if (frm.doc.docstatus !== 1) return;
		frm.add_custom_button(__("Sync Kanban Job Cards"), async () => {
			const response = await frappe.call({
				method: "cfg_kanban.integrations.erp_feedback.reconcile_work_order",
				args: { work_order_name: frm.doc.name }, freeze: true,
				freeze_message: __("Synchronizing Kanban status and Job Cards..."),
			});
			frappe.show_alert({
				message: __("Kanban synchronized with {0} Job Card(s)", [response.message.job_cards]),
				indicator: "green",
			});
			frm.reload_doc();
		}, __("Kanban"));
	},
});
