frappe.ui.form.on("CFG Process Certificate Run", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.disable_save();
		if (frm.doc.repack_stock_entry) {
			frm.add_custom_button(__("Open ERPNext Repack"), () =>
				frappe.set_route("Form", "Stock Entry", frm.doc.repack_stock_entry), __("View"));
		}
		if (frm.doc.kanban_cycle) {
			frm.add_custom_button(__("Open Kanban Cycle"), () =>
				frappe.set_route("Form", "CFG Kanban Cycle", frm.doc.kanban_cycle), __("View"));
		}
		const manager = ["Manufacturing Manager", "System Manager"]
			.some((role) => frappe.user_roles.includes(role));
		if (manager && frm.doc.status === "Awaiting ERP Submission" && frm.doc.repack_stock_entry) {
			frappe.db.get_value("Stock Entry", frm.doc.repack_stock_entry, "docstatus")
				.then(({ message }) => {
					if (Number(message?.docstatus) !== 1) return;
					frm.add_custom_button(__("Reconcile Submitted Repack"), async () => {
						await frappe.call({
							method: "cfg_kanban.services.certificate_process.reconcile_submitted_certificate_process",
							args: { run_name: frm.doc.name },
							freeze: true,
							freeze_message: __("Reconciling submitted Repack with tags and certificates..."),
						});
						await frm.reload_doc();
					}, __("Recovery"));
				});
		}
		if (!["Awaiting ERP Submission", "Completed", "Exception"].includes(frm.doc.status) ||
			!manager) {
			return;
		}
		frappe.db.get_value("CFG Process Certificate Recovery",
			{ certificate_process_run: frm.doc.name }, "name").then(({ message }) => {
			if (message?.name) {
				frm.add_custom_button(__("Open Controlled Recovery"), () =>
					frappe.set_route("Form", "CFG Process Certificate Recovery", message.name),
					__("Recovery"));
				return;
			}
			if (!["Awaiting ERP Submission", "Completed"].includes(frm.doc.status)) return;
			frm.add_custom_button(__("Request Controlled Recovery"), () => {
				const dialog = new frappe.ui.Dialog({
					title: __("Controlled Certificate Process Recovery"),
					fields: [
						{ fieldname: "warning", fieldtype: "HTML", options:
							`<div class="alert alert-danger"><strong>${__("This freezes the Certificate Process and Card.")}</strong><br>${__("A submitted Repack must be cancelled in ERPNext and its exact physical tags reconciled before release.")}</div>` },
						{ fieldname: "reason", label: __("Detailed Recovery Reason"),
							fieldtype: "Small Text", reqd: 1 },
						{ fieldname: "confirmed", label: __("I am requesting controlled reversal"),
							fieldtype: "Check", default: 0 },
					],
					primary_action_label: __("Freeze and Assess"),
					primary_action: async (values) => {
						if (!values.confirmed) {
							frappe.msgprint(__("Confirm the controlled recovery request."));
							return;
						}
						const response = await frappe.call({
							method: "cfg_kanban.services.certificate_process_recovery.request_certificate_process_recovery",
							args: { run_name: frm.doc.name, reason: values.reason },
							freeze: true, freeze_message: __("Freezing and assessing Certificate Process..."),
						});
						dialog.hide();
						frappe.set_route("Form", "CFG Process Certificate Recovery", response.message.name);
					},
				});
				dialog.show();
			}, __("Recovery"));
		});
	},
});
