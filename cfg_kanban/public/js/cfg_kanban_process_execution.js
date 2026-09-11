frappe.ui.form.on("CFG Kanban Process Execution", {
	refresh(frm) {
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
	},
});
