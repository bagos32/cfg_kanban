frappe.ui.form.on("CFG Kanban Receipt Disposition", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (frm.doc.purchase_receipt) {
			frm.add_custom_button(__("Open Original Purchase Receipt"), () =>
				frappe.set_route("Form", "Purchase Receipt", frm.doc.purchase_receipt), __("View"));
		}
		if (frm.doc.kanban_cycle) {
			frm.add_custom_button(__("Open Kanban Cycle"), () =>
				frappe.set_route("Form", "CFG Kanban Cycle", frm.doc.kanban_cycle), __("View"));
		}
		if (["Resolved", "Cancelled"].includes(frm.doc.status) || !can_manage()) return;
		frm.add_custom_button(__("Select Disposition"), () => {
			frappe.prompt([
				{ fieldname: "disposition", label: __("Disposition"), fieldtype: "Select", reqd: 1,
					options: "Supplier Replacement\nSupplier Credit / Return\nAccept by Concession\nScrap / Dispose",
					default: frm.doc.disposition === "Awaiting Decision" ? "Supplier Replacement" : frm.doc.disposition },
				{ fieldname: "reason", label: __("Decision Reason"), fieldtype: "Small Text", reqd: 1 },
			], async (values) => {
				await frappe.call({ method: "cfg_kanban.api.purchase.choose_receipt_disposition",
					args: { disposition_name: frm.doc.name, ...values }, freeze: true });
				frm.reload_doc();
			}, __("Control Rejected Material"), __("Record Decision"));
		}, __("Disposition"));
		if (frm.doc.disposition === "Accept by Concession" && (frm.doc.open_rejected_qty || 0) > 0) {
			frm.add_custom_button(__("Confirm Concession Transfer"), () => {
				frappe.prompt([
					{ fieldname: "stock_entry", label: __("Submitted Stock Entry"), fieldtype: "Link", options: "Stock Entry", reqd: 1,
						get_query: () => ({ filters: { docstatus: 1 } }) },
					{ fieldname: "qty", label: __("Approved Qty ({0})", [frm.doc.purchase_uom]), fieldtype: "Float", reqd: 1, default: frm.doc.open_rejected_qty },
					{ fieldname: "reason", label: __("QC / Supervisor Approval Reason"), fieldtype: "Small Text", reqd: 1 },
				], async (values) => {
					await frappe.call({ method: "cfg_kanban.api.purchase.accept_rejected_by_concession",
						args: { disposition_name: frm.doc.name, ...values }, freeze: true,
						freeze_message: __("Validating native Stock Entry...") });
					frm.reload_doc();
				}, __("Accept Rejected Material by Concession"), __("Confirm"));
			}, __("Disposition"));
		}
		if (frm.doc.disposition === "Scrap / Dispose" && (frm.doc.open_rejected_qty || 0) > 0) {
			frm.add_custom_button(__("Confirm Disposal Stock Entry"), () => {
				frappe.prompt([
					{ fieldname: "stock_entry", label: __("Submitted Stock Entry"), fieldtype: "Link", options: "Stock Entry", reqd: 1,
						get_query: () => ({ filters: { docstatus: 1 } }) },
					{ fieldname: "qty", label: __("Disposed Qty ({0})", [frm.doc.purchase_uom]), fieldtype: "Float", reqd: 1, default: frm.doc.open_rejected_qty },
					{ fieldname: "reason", label: __("Disposal Approval / Evidence"), fieldtype: "Small Text", reqd: 1 },
				], async (values) => {
					await frappe.call({ method: "cfg_kanban.api.purchase.confirm_rejected_disposal",
						args: { disposition_name: frm.doc.name, ...values }, freeze: true,
						freeze_message: __("Validating native disposal Stock Entry...") });
					frm.reload_doc();
				}, __("Confirm Rejected Material Disposal"), __("Confirm"));
			}, __("Disposition"));
		}
	},
});

function can_manage() {
	return ["Purchase Manager", "Stock Manager", "Manufacturing Manager", "System Manager"]
		.some((role) => frappe.user_roles.includes(role));
}
