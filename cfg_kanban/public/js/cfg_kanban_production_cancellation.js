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
			if (["Manufacturing Manager", "System Manager"].some((role) => frappe.user_roles.includes(role))) {
				frm.add_custom_button(__("Verify / Repair Card Release"), () => {
					const dialog = new frappe.ui.Dialog({
						title: __("Reconcile Completed Cancellation"),
						fields: [
							{ fieldname: "warning", fieldtype: "HTML", options:
								`<div class="alert alert-warning">${__("Use this only when the completed cancellation still shows an active Card, Ready/Not Ready process, blocked runtime, or unreleased related operation Card. It does not alter ERPNext documents.")}</div>` },
							{ fieldname: "reconciliation_notes", label: __("Recovery Evidence"),
								fieldtype: "Small Text", reqd: 1,
								description: __("Record the observed stale state and who verified the cancelled Work Order and floor material state.") },
							{ fieldname: "confirmed", label: __("I verified this cancellation is already completed"),
								fieldtype: "Check", default: 0 },
						],
						primary_action_label: __("Verify and Repair Release"),
						primary_action: async (values) => {
							if (!values.confirmed) {
								frappe.msgprint(__("Confirm the completed cancellation before reconciliation."));
								return;
							}
							const response = await frappe.call({
								method: "cfg_kanban.services.production_cancellation.finalize_production_cancellation",
								args: { cancellation_name: frm.doc.name,
									reconciliation_notes: values.reconciliation_notes },
								freeze: true, freeze_message: __("Reconciling completed cancellation release..."),
							});
							dialog.hide();
							await frm.reload_doc();
							const repaired = response.message?.repaired_cycles || [];
							frappe.show_alert({
								message: repaired.length
									? __("Repaired cancelled Cycle(s): {0}", [repaired.join(", ")])
									: __("Cancellation release is already consistent."),
								indicator: repaired.length ? "green" : "blue",
							}, 7);
						},
					});
					dialog.show();
				}, __("Recovery"));
			}
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
		add_erp_reversal_buttons(frm);
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

function add_erp_reversal_buttons(frm) {
	const dependencies = frm.doc.dependencies || [];
	const job_cards = [...new Set(dependencies.filter((row) =>
		row.blocking && row.reference_doctype === "Job Card"
	).map((row) => row.reference_name))];
	if (job_cards.length) {
		frm.add_custom_button(__("Cancel Linked Job Card"), () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Cancel ERP Job Card"),
				fields: [
					{ fieldname: "warning", fieldtype: "HTML", options:
						`<div class="alert alert-warning">${__("Use this only after every related Stock Entry is cancelled or discarded. Resolve every listed Work Order Job Card, including not-started downstream Drafts. A submitted Job Card runs ERPNext cancellation hooks; a Draft is retained and marked Cancelled. Kanban and Process Execution audit links remain.")}</div>` },
					{ fieldname: "job_card", label: __("Job Card"), fieldtype: "Select", reqd: 1,
						options: job_cards.join("\n") },
					{ fieldname: "reversal_notes", label: __("ERP Reversal Evidence"),
						fieldtype: "Small Text", reqd: 1,
						description: __("Record why this Job Card is being cancelled and who verified the reversal.") },
					{ fieldname: "confirmed", label: __("I verified the related Stock Entries are reversed"),
						fieldtype: "Check", default: 0 },
				],
				primary_action_label: __("Cancel Job Card"),
				primary_action: async (values) => {
					if (!values.confirmed) {
						frappe.msgprint(__("Confirm the Stock Entry reversal before continuing."));
						return;
					}
					await frappe.call({
						method: "cfg_kanban.services.production_cancellation.cancel_production_job_card",
						args: { cancellation_name: frm.doc.name, job_card_name: values.job_card,
							reversal_notes: values.reversal_notes },
						freeze: true, freeze_message: __("Cancelling ERP Job Card..."),
					});
					dialog.hide();
					await frm.reload_doc();
				},
			});
			dialog.show();
		}, __("ERP Reversal"));
	}

	const work_order_blocked = dependencies.some((row) =>
		row.blocking && row.reference_doctype === "Work Order"
	);
	const lower_level_blocked = dependencies.some((row) =>
		row.blocking && ["Job Card", "Stock Entry"].includes(row.reference_doctype)
	);
	if (work_order_blocked && !lower_level_blocked) {
		frm.add_custom_button(__("Cancel Work Order"), () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Cancel ERP Work Order"),
				fields: [
					{ fieldname: "warning", fieldtype: "HTML", options:
						`<div class="alert alert-danger">${__("This runs ERPNext Work Order cancellation after all lower-level production records are resolved. Kanban audit links remain preserved.")}</div>` },
					{ fieldname: "reversal_notes", label: __("ERP Reversal Evidence"),
						fieldtype: "Small Text", reqd: 1 },
					{ fieldname: "confirmed", label: __("I verified all Job Cards and Stock Entries are resolved"),
						fieldtype: "Check", default: 0 },
				],
				primary_action_label: __("Cancel Work Order"),
				primary_action: async (values) => {
					if (!values.confirmed) {
						frappe.msgprint(__("Confirm the lower-level ERP reversal before continuing."));
						return;
					}
					await frappe.call({
						method: "cfg_kanban.services.production_cancellation.cancel_production_work_order",
						args: { cancellation_name: frm.doc.name,
							reversal_notes: values.reversal_notes },
						freeze: true, freeze_message: __("Cancelling ERP Work Order..."),
					});
					dialog.hide();
					await frm.reload_doc();
				},
			});
			dialog.show();
		}, __("ERP Reversal"));
	}
}
