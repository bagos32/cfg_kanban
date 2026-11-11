frappe.ui.form.on("CFG Process Certificate Recovery", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.disable_save();
		frm.add_custom_button(__("Open Certificate Process Run"), () =>
			frappe.set_route("Form", "CFG Process Certificate Run", frm.doc.certificate_process_run),
			__("View"));
		const discarded_draft = frm.doc.status === "Completed"
			&& Number(frm.doc.repack_docstatus_snapshot || 0) === 0;
		if (frm.doc.repack_stock_entry_name && !discarded_draft) {
			frm.add_custom_button(__("Open ERPNext Repack"), () =>
				frappe.set_route("Form", "Stock Entry", frm.doc.repack_stock_entry_name), __("View"));
		}
		if (frm.doc.status === "Completed") {
			frm.dashboard.set_headline_alert(
				__("Recovery completed. ERP and tag history remain available for audit, and the Card is released."),
				"green"
			);
			return;
		}
		const manager = ["Manufacturing Manager", "System Manager"]
			.some((role) => frappe.user_roles.includes(role));
		frm.dashboard.set_headline_alert(
			frm.doc.blocking_reason || __("Certificate Process is frozen pending controlled recovery."),
			frm.doc.status === "Blocked" ? "red" : "orange"
		);
		if (!manager) return;
		frm.add_custom_button(__("Refresh Assessment"), async () => {
			await frappe.call({
				method: "cfg_kanban.services.certificate_process_recovery.refresh_certificate_process_recovery",
				args: { recovery_name: frm.doc.name }, freeze: true,
				freeze_message: __("Rechecking ERP and physical tag state..."),
			});
			await frm.reload_doc();
		}, __("Recovery"));
		if (frm.doc.status === "Pending ERP Reversal") {
			frm.add_custom_button(__("Cancel ERPNext Repack"), () => {
				frappe.prompt([
					{ fieldname: "warning", fieldtype: "HTML", options:
						`<div class="alert alert-danger">${__("ERPNext cancellation remains authoritative. This action stops if the stock or physical output is no longer safely reversible.")}</div>` },
					{ fieldname: "reversal_notes", label: __("ERP Reversal Evidence / Notes"),
						fieldtype: "Small Text", reqd: 1 },
				], async (values) => {
					await frappe.call({
						method: "cfg_kanban.services.certificate_process_recovery.cancel_certificate_process_repack",
						args: { recovery_name: frm.doc.name,
							reversal_notes: values.reversal_notes },
						freeze: true, freeze_message: __("Cancelling ERPNext Repack..."),
					});
					await frm.reload_doc();
				}, __("Cancel Submitted Repack"), __("Cancel Repack"));
			}, __("ERP Reversal"));
		}
		if (frm.doc.status === "Ready to Finalize") {
			frm.add_custom_button(__("Finalize and Release Card"), () => {
				const dialog = new frappe.ui.Dialog({
					title: __("Finalize Certificate Process Recovery"),
					fields: [
						{ fieldname: "warning", fieldtype: "HTML", options:
							`<div class="alert alert-warning">${__("Verify the ERP Repack state, source quantity, output tag, Batch and certificate state. A Draft Repack will be discarded while its complete snapshot remains in this recovery record.")}</div>` },
						{ fieldname: "reconciliation_evidence", label: __("Final Reconciliation Evidence"),
							fieldtype: "Text", reqd: 1 },
						{ fieldname: "confirmed", label: __("I verified ERP and physical tag reconciliation"),
							fieldtype: "Check", default: 0 },
					],
					primary_action_label: __("Finalize Recovery"),
					primary_action: async (values) => {
						if (!values.confirmed) {
							frappe.msgprint(__("Confirm the final reconciliation."));
							return;
						}
						await frappe.call({
							method: "cfg_kanban.services.certificate_process_recovery.finalize_certificate_process_recovery",
							args: { recovery_name: frm.doc.name,
								reconciliation_evidence: values.reconciliation_evidence },
							freeze: true, freeze_message: __("Finalizing controlled recovery..."),
						});
						dialog.hide();
						await frm.reload_doc();
					},
				});
				dialog.show();
			}, __("Recovery")).addClass("btn-danger");
		}
	},
});
