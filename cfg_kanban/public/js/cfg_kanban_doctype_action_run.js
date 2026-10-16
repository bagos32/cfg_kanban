frappe.ui.form.on("CFG Kanban DocType Action Run", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (!["Posting", "Submitted", "Skipped by Condition", "Needs Reconciliation", "Cancelled"].includes(frm.doc.state)
			&& !frm.doc.target_name) {
			frm.add_custom_button(__("Cancel Run with Reason"), () =>
				run_supervisor_action(frm, "cancel", __("Cancel DocType Action Run"),
					__("Cancellation Reason"), __("Cancel Run")), __("Recovery"));
		}
		if (!["Cancelled", "Skipped by Condition", "Needs Reconciliation"].includes(frm.doc.state)) {
			frm.add_custom_button(__("Mark Needs Reconciliation"), () =>
				run_supervisor_action(frm, "require_reconciliation",
					__("Require Supervised Reconciliation"), __("Reconciliation Reason"),
					__("Mark for Reconciliation")), __("Recovery"));
		}
	},
});

function run_supervisor_action(frm, method, title, reason_label, primary_label) {
	const operator_session_token = localStorage.getItem("cfg_kanban_operator_session");
	if (!operator_session_token) {
		frappe.msgprint(__("Identify an authorized Supervisor in the Service Task Panel before using Action Run recovery."));
		return;
	}
	frappe.prompt([
		{ fieldname: "reason", label: reason_label, fieldtype: "Small Text", reqd: 1 },
	], async (values) => {
		await frappe.call({
			method: `cfg_kanban.api.doctype_action_run.${method}`,
			args: {
				run_name: frm.doc.name,
				reason: values.reason,
				operator_session_token,
				retry_token: frappe.utils.get_random(24),
			},
			freeze: true,
			freeze_message: __("Applying controlled Action Run recovery..."),
		});
		await frm.reload_doc();
	}, title, primary_label);
}
