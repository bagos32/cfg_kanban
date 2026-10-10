frappe.ui.form.on("CFG Kanban Stock Adoption", {
	refresh(frm) {
		if (frm.is_new()) return;
		const token = localStorage.getItem("cfg_kanban_operator_session");
		if (!token) {
			frm.dashboard.set_headline_alert(__("Scan a supervisor credential in an Operator panel before changing Cycle allocation."), "orange");
			return;
		}
		if (["Adopted", "Allocation Released"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Allocate Complete Tag to Cycle"), () => {
				let dialog;
				dialog = new frappe.ui.Dialog({
					title: __("Allocate Existing Stock to Kanban Cycle"),
					fields: [
						{ fieldname: "warning", fieldtype: "HTML", options: `<div class="alert alert-warning">${__("This reserves the complete physical tag. It does not report production, update a Job Card, or close the Cycle.")}</div>` },
						{ fieldname: "kanban_cycle", label: __("Kanban Cycle"), fieldtype: "Link", options: "CFG Kanban Cycle", reqd: 1,
							get_query: () => ({ filters: { company: frm.doc.company, item_code: frm.doc.item_code,
								status: ["in", ["New", "Signalled", "Released"]] } }) },
						{ fieldname: "allocation_reason", label: __("Allocation Reason"), fieldtype: "Small Text", reqd: 1 },
					],
					primary_action_label: __("Reserve Complete Tag"),
					primary_action: async (values) => {
						await frappe.call({
							method: "cfg_kanban.services.stock_adoption.allocate_adopted_stock",
							args: { adoption_name: frm.doc.name, kanban_cycle: values.kanban_cycle,
								allocation_reason: values.allocation_reason, operator_session_token: token },
							freeze: true, freeze_message: __("Reserving adopted stock..."),
						});
						dialog.hide(); await frm.reload_doc();
					},
				});
				dialog.show();
			}, __("Kanban Actions"));
		}
		if (frm.doc.status === "Allocated to Cycle") {
			frm.add_custom_button(__("Release Cycle Allocation"), () => {
				frappe.prompt([
					{ fieldname: "reason", label: __("Release Reason"), fieldtype: "Small Text", reqd: 1 },
				], async (values) => {
					await frappe.call({
						method: "cfg_kanban.services.stock_adoption.release_adopted_stock_allocation",
						args: { adoption_name: frm.doc.name, reason: values.reason,
							operator_session_token: token },
						freeze: true, freeze_message: __("Releasing stock reservation..."),
					});
					await frm.reload_doc();
				}, __("Release Existing Stock Allocation"), __("Release"));
			}, __("Kanban Actions"));
		}
	},
});
