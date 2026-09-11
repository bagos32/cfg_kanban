frappe.ui.form.on("CFG Kanban Signal", {
	refresh(frm) {
		if (frm.is_new() || !["Waiting Approval", "Validated", "Failed"].includes(frm.doc.status)) return;
		frm.add_custom_button(__("Approve and Create Work Order"), () => {
			frappe.confirm(__("Approve this signal and send its Work Order command to ERPNext?"), async () => {
				await frappe.call({ method: "cfg_kanban.api.operator.approve_signal",
					args: { signal_name: frm.doc.name }, freeze: true,
					freeze_message: __("Creating Work Order...") });
				frappe.show_alert({ message: __("Work Order created"), indicator: "green" });
				frm.reload_doc();
			});
		}).addClass("btn-primary");
	},
});
