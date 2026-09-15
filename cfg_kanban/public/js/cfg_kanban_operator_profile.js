frappe.ui.form.on("CFG Kanban Operator Profile", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Issue New QR Credential"), async () => {
			frappe.confirm(__("This will invalidate the operator's previous QR. Continue?"), async () => {
				const response = await frappe.call({
					method: "cfg_kanban.api.operator.issue_operator_credential",
					args: { profile_name: frm.doc.name }, freeze: true,
				});
				const token = frappe.utils.escape_html(response.message.qr_token);
				frappe.msgprint({
					title: __("New Operator QR Credential"),
					message: `<p>${__("Copy this credential now. It is stored only as a hash and cannot be shown again.")}</p><pre>${token}</pre>`,
					indicator: "green",
				});
			});
		}, __("Credentials"));
	},
});
