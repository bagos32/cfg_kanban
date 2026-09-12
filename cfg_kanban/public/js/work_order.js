frappe.ui.form.on("Work Order", {
	refresh(frm) {
		if (!frm.doc.cfg_kanban_cycle || frm.doc.docstatus !== 1) return;
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
