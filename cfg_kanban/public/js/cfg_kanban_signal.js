frappe.ui.form.on("CFG Kanban Signal", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (["Waiting Approval", "Validated", "Failed"].includes(frm.doc.status)) {
			const purchase = frm.doc.signal_type === "Purchase Replenishment";
			const label = purchase ? __("Approve and Create Material Request") : __("Approve and Create Work Order");
			frm.add_custom_button(label, () => {
			frappe.confirm(purchase
				? __("Approve this purchase signal and create its ERPNext Material Request?")
				: __("Approve this signal and send its Work Order command to ERPNext?"), async () => {
				await frappe.call({ method: "cfg_kanban.api.operator.approve_signal",
					args: { signal_name: frm.doc.name }, freeze: true,
					freeze_message: purchase ? __("Creating Material Request...") : __("Creating Work Order...") });
				frappe.show_alert({ message: purchase ? __("Material Request created") : __("Work Order created"), indicator: "green" });
				frm.reload_doc();
			});
			}).addClass("btn-primary");
		}
		if (frm.doc.status !== "Cancelled" &&
			(frappe.user.has_role("Manufacturing Manager") || frappe.user.has_role("Purchase Manager") || frappe.user.has_role("System Manager"))) {
			frm.add_custom_button(__("Cancel and Roll Back"), () => {
				const dialog = new frappe.ui.Dialog({
					title: __("Cancel Kanban Signal"),
					fields: [{ fieldname: "reason", label: __("Cancellation Reason"),
						fieldtype: "Small Text", reqd: 1 }],
					primary_action_label: __("Cancel Signal and Roll Back"),
					primary_action: async (values) => {
						await frappe.call({ method: "cfg_kanban.api.operator.cancel_signal",
							args: { signal_name: frm.doc.name, reason: values.reason },
							freeze: true, freeze_message: __("Checking and rolling back...") });
						dialog.hide();
						frappe.show_alert({ message: __("Signal cancelled and safe records rolled back"), indicator: "green" });
						await frm.reload_doc();
					},
				});
				dialog.show();
			}, __("Actions"));
		}
	},
});
