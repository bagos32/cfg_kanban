frappe.ui.form.on("CFG Kanban Process Execution", {
	async refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Open Operator Console"), () => frappe.set_route("kanban-operator"));
		if (frm.doc.job_card && frm.doc.status === "Ready") {
			frm.add_custom_button(__("Start Job Card"), async () => {
				await frappe.call({ method: "cfg_kanban.api.operator.run_job_card_action", args: {
					execution_name: frm.doc.name, action: "start", event_token: frappe.utils.get_random(16),
				}, freeze: true });
				frm.reload_doc();
			}, __("Kanban Actions"));
		}
		if (frm.doc.job_card) {
			const { message } = await frappe.db.get_value("Job Card", frm.doc.job_card,
				["docstatus", "status", "for_quantity", "total_completed_qty"]);
			if (message && message.docstatus === 0 &&
				(message.total_completed_qty || 0) >= (message.for_quantity || 0)) {
				frm.add_custom_button(__("Complete Job Card"), async () => {
					await frappe.call({ method: "cfg_kanban.api.operator.run_job_card_action", args: {
						execution_name: frm.doc.name, action: "complete",
						event_token: frappe.utils.get_random(16),
					}, freeze: true, freeze_message: __("Completing ERPNext Job Card...") });
					await frm.reload_doc();
				}, __("Kanban Actions"));
			}
		}
	},
});
