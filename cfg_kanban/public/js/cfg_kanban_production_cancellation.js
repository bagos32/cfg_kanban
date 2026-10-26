frappe.ui.form.on("CFG Kanban Production Cancellation", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.disable_save();
		if (frm.doc.kanban_cycle) {
			frm.add_custom_button(__("Open Kanban Cycle"), () =>
				frappe.set_route("Form", "CFG Kanban Cycle", frm.doc.kanban_cycle), __("View"));
		}
		if (frm.doc.work_order) {
			frm.add_custom_button(__("Open Work Order"), () =>
				frappe.set_route("Form", "Work Order", frm.doc.work_order), __("View"));
		}
		if (frm.doc.status === "Completed") {
			frm.dashboard.set_headline_alert(
				__("Cancellation completed. ERP evidence is preserved and the reusable Card has been released."),
				"green"
			);
			return;
		}
		frm.dashboard.set_headline_alert(
			__("Production is frozen. Resolve the listed ERP and physical dependencies before finalization."),
			"orange"
		);
		if (!["Manufacturing Manager", "System Manager"].some((role) => frappe.user_roles.includes(role))) {
			return;
		}
		frm.add_custom_button(__("Refresh Assessment"), async () => {
			await frappe.call({
				method: "cfg_kanban.services.production_cancellation.refresh_production_cancellation",
				args: { cancellation_name: frm.doc.name }, freeze: true,
				freeze_message: __("Rechecking ERP and physical dependencies..."),
			});
			await frm.reload_doc();
		}).addClass("btn-primary");
		if (frm.doc.status === "Ready to Finalize" && !frm.doc.blocking_count) {
			frm.add_custom_button(__("Finalize and Release Card"), () => {
				const dialog = new frappe.ui.Dialog({
					title: __("Finalize Controlled Production Cancellation"),
					fields: [
						{ fieldname: "warning", fieldtype: "HTML", options:
							`<div class="alert alert-danger">${__("This closes the Kanban Cycle as Cancelled and returns its physical Card to Available. ERPNext records are not deleted.")}</div>` },
						{ fieldname: "reconciliation_notes", label: __("Final Reconciliation Evidence"),
							fieldtype: "Text", reqd: 1,
							description: __("Record document references, physical count result, and who verified the reconciliation.") },
						{ fieldname: "confirmed", label: __("I verified every listed dependency is resolved"),
							fieldtype: "Check", default: 0 },
					],
					primary_action_label: __("Finalize Cancellation"),
					primary_action: async (values) => {
						if (!values.confirmed) {
							frappe.msgprint(__("Confirm that every dependency was verified."));
							return;
						}
						await frappe.call({
							method: "cfg_kanban.services.production_cancellation.finalize_production_cancellation",
							args: { cancellation_name: frm.doc.name,
								reconciliation_notes: values.reconciliation_notes },
							freeze: true, freeze_message: __("Finalizing controlled cancellation..."),
						});
						dialog.hide();
						await frm.reload_doc();
					},
				});
				dialog.show();
			}).addClass("btn-danger");
		}
	},
});
