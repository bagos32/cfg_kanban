frappe.ui.form.on("CFG Kanban Employee Competency", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		if (frm.doc.status === "Active") {
			add_status_action(frm, __("Suspend"), "Suspended");
			add_status_action(frm, __("Revoke"), "Revoked");
		} else if (frm.doc.status === "Suspended") {
			add_status_action(frm, __("Reactivate"), "Active");
			add_status_action(frm, __("Revoke"), "Revoked");
		}
	},
});

function add_status_action(frm, label, status) {
	frm.add_custom_button(label, () => {
		frappe.prompt({
			fieldname: "reason",
			label: __("Reason"),
			fieldtype: "Small Text",
			reqd: 1,
		}, async (values) => {
			await frappe.call({
				method: "cfg_kanban.services.competency.change_competency_status",
				args: {
					competency_name: frm.doc.name,
					status,
					reason: values.reason,
				},
				freeze: true,
				freeze_message: __("Updating competency authorization..."),
			});
			await frm.reload_doc();
		}, __("{0} Competency", [label]), __("Confirm"));
	}, __("Authorization"));
}
