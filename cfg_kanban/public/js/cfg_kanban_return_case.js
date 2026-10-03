frappe.ui.form.on("CFG Kanban Return Case", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.return_flow !== "Customer Return for QC") return;
		if (frm.doc.credit_document) {
			frm.add_custom_button(__("Open Credit Return"), () => {
				frappe.set_route("Form", frm.doc.credit_document_doctype || "Sales Invoice", frm.doc.credit_document);
			});
		}
		if (can_prepare_accounting(frm)) {
			frm.add_custom_button(__("Prepare Accounting Decision"), () => open_accounting_dialog(frm), __("Accounting"));
		}
		if (frm.doc.stock_disposition_entry) {
			frm.add_custom_button(__("Open Return Material Receipt"), () => {
				frappe.set_route("Form", "Stock Entry", frm.doc.stock_disposition_entry);
			});
			if (frm.doc.stock_disposition_entry_status === "Draft"
				&& ["Stock Manager", "System Manager"].some((role) => frappe.user_roles.includes(role))) {
				frm.add_custom_button(__("Discard Return Material Receipt Draft"), () => discard_stock_draft(frm), __("Stock"));
			}
		}
		if (can_prepare_stock_disposition(frm)) {
			frm.add_custom_button(__("Prepare Stock Disposition"), () => open_stock_disposition_dialog(frm), __("Stock"));
		}
	},
});

function can_prepare_accounting(frm) {
	const allowed = ["Accounts User", "Accounts Manager", "Sales Manager", "System Manager"];
	return frm.doc.state === "QC Completed - Accounting Pending"
		&& Number(frm.doc.accepted_total_qty || 0) > 0
		&& !(frm.doc.credit_document && frm.doc.credit_document_status !== "Cancelled")
		&& allowed.some((role) => frappe.user_roles.includes(role));
}

function discard_stock_draft(frm) {
	frappe.prompt({
		fieldtype: "Small Text", fieldname: "reason", label: __("Discard Reason"), reqd: 1,
	}, async (values) => {
		await frappe.call({
			method: "cfg_kanban.services.return_disposition.discard_stock_disposition_draft",
			args: { return_case: frm.docname, reason: values.reason },
			freeze: true,
			freeze_message: __("Discarding Draft return Material Receipt..."),
		});
		await frm.reload_doc();
	}, __("Discard Draft Return Material Receipt"), __("Discard Draft"));
}

function can_prepare_stock_disposition(frm) {
	const allowed = ["Stock Manager", "Quality Manager", "System Manager"];
	return Number(frm.doc.accepted_total_qty || 0) > 0
		&& Boolean(frm.doc.qc_completed_on)
		&& frm.doc.disposition_status !== "Completed"
		&& !(frm.doc.stock_disposition_entry && frm.doc.stock_disposition_entry_status !== "Cancelled")
		&& allowed.some((role) => frappe.user_roles.includes(role));
}

async function open_stock_disposition_dialog(frm) {
	const response = await frappe.call({
		method: "cfg_kanban.services.return_disposition.get_stock_disposition_context",
		args: { return_case: frm.docname },
		freeze: true,
		freeze_message: __("Loading accepted return quantities..."),
	});
	const context = response.message || {};
	const dialog = new frappe.ui.Dialog({
		title: __("Prepare Accepted Return Stock Disposition"),
		size: "extra-large",
		fields: [
			{ fieldtype: "HTML", fieldname: "stock_guidance" },
			{
				fieldtype: "Table", fieldname: "disposition_lines", label: __("Disposition Splits"),
				reqd: 1, cannot_add_rows: false, cannot_delete_rows: false, in_place_edit: true,
				fields: [
					{ fieldtype: "Data", fieldname: "return_line", label: __("Return Row"), hidden: 1 },
					{ fieldtype: "Link", fieldname: "item_code", label: __("Item"), options: "Item", read_only: 1, in_list_view: 1, columns: 2 },
					{ fieldtype: "Link", fieldname: "batch_no", label: __("Batch"), options: "Batch", read_only: 1, in_list_view: 1, columns: 1 },
					{ fieldtype: "Link", fieldname: "stock_uom", label: __("UOM"), options: "UOM", read_only: 1, in_list_view: 1, columns: 1 },
					{ fieldtype: "Float", fieldname: "qty", label: __("Qty"), reqd: 1, in_list_view: 1, columns: 1 },
					{ fieldtype: "Select", fieldname: "disposition", label: __("Disposition"), reqd: 1, in_list_view: 1, columns: 2,
						options: ["Receive to Quarantine", "Receive for Rework", "Return to Available Stock", "Dispose Without Stock Receipt"] },
					{ fieldtype: "Link", fieldname: "target_warehouse", label: __("Target Warehouse"), options: "Warehouse", in_list_view: 1, columns: 2,
						get_query: () => ({ filters: { company: context.selling_company, is_group: 0 } }) },
					{ fieldtype: "Currency", fieldname: "valuation_rate", label: __("Valuation Rate"), in_list_view: 1, columns: 1 },
					{ fieldtype: "Small Text", fieldname: "reason", label: __("Reason"), reqd: 1, in_list_view: 1, columns: 2 },
				],
			},
			{ fieldtype: "Small Text", fieldname: "decision_notes", label: __("Overall Disposition Decision Notes"), reqd: 1 },
		],
		primary_action_label: __("Prepare Controlled Disposition"),
		primary_action: async (values) => {
			dialog.disable_primary_action();
			try {
				const result = await frappe.call({
					method: "cfg_kanban.services.return_disposition.prepare_stock_disposition",
					args: {
						return_case: frm.docname,
						lines: values.disposition_lines,
						decision_notes: values.decision_notes,
						event_token: frappe.utils.get_random(24),
					},
					freeze: true,
					freeze_message: __("Preparing controlled return disposition..."),
				});
				dialog.hide();
				if (result.message && result.message.stock_entry) {
					frappe.show_alert({ message: __("Draft return Material Receipt prepared for Stock Manager review."), indicator: "green" });
					frappe.set_route("Form", "Stock Entry", result.message.stock_entry);
				} else {
					await frm.reload_doc();
				}
			} finally {
				dialog.enable_primary_action();
			}
		},
	});
	dialog.fields_dict.stock_guidance.$wrapper.html(`<div class="alert alert-warning">
		<strong>${__("Stock control")}</strong><br>
		${__("Every QC-accepted quantity must be allocated. Warehouse receipts create a Draft Material Receipt; ERPNext stock changes only after submission. Disposal creates no stock receipt. Accounting credit remains separate.")}
	</div>`);
	const rows = (context.existing_dispositions || []).length
		? context.existing_dispositions.map((row) => ({ ...row }))
		: (context.accepted_lines || []).map((row) => ({
			return_line: row.return_line,
			item_code: row.item_code,
			batch_no: row.batch_no,
			stock_uom: row.stock_uom,
			qty: row.accepted_qty,
			disposition: suggested_disposition(row.qc_disposition),
			target_warehouse: "",
			valuation_rate: 0,
			reason: row.qc_reason || row.qc_disposition || "",
		}));
	dialog.fields_dict.disposition_lines.df.data = rows;
	dialog.fields_dict.disposition_lines.grid.refresh();
	dialog.show();
}

function suggested_disposition(qc_disposition) {
	if (qc_disposition === "Accept for Rework") return "Receive for Rework";
	if (qc_disposition === "Accept for Disposal") return "Dispose Without Stock Receipt";
	return "Receive to Quarantine";
}

async function open_accounting_dialog(frm) {
	const response = await frappe.call({
		method: "cfg_kanban.services.customer_returns.get_accounting_context",
		args: { return_case: frm.docname },
		freeze: true,
		freeze_message: __("Loading accounting context..."),
	});
	const context = response.message || {};
	const dialog = new frappe.ui.Dialog({
		title: __("Prepare Post-QC Accounting Decision"),
		fields: [
			{ fieldtype: "HTML", fieldname: "guidance" },
			{
				fieldtype: "Select", fieldname: "source_basis", label: __("Accounting Source Basis"),
				options: ["Exact Sales Invoice", "Substitute Historical Sales Invoice", "No Credit"], reqd: 1,
			},
			{
				fieldtype: "Link", fieldname: "source_sales_invoice", label: __("Source Sales Invoice"),
				options: "Sales Invoice",
				get_query: () => ({ filters: { company: context.selling_company, customer: context.customer, docstatus: 1, is_return: 0 } }),
			},
			{ fieldtype: "Small Text", fieldname: "decision_notes", label: __("Accounting Decision Notes"), reqd: 1 },
			{ fieldtype: "HTML", fieldname: "candidate_invoices" },
		],
		primary_action_label: __("Apply Decision"),
		primary_action: async (values) => {
			if (values.source_basis !== "No Credit" && !values.source_sales_invoice) {
				frappe.msgprint(__("Select the submitted Sales Invoice used as the credit source."));
				return;
			}
			dialog.disable_primary_action();
			try {
				const result = await frappe.call({
					method: "cfg_kanban.services.customer_returns.prepare_accounting_decision",
					args: {
						return_case: frm.docname,
						source_basis: values.source_basis,
						source_sales_invoice: values.source_basis === "No Credit" ? null : values.source_sales_invoice,
						decision_notes: values.decision_notes,
						event_token: frappe.utils.get_random(24),
					},
					freeze: true,
					freeze_message: __("Applying controlled accounting decision..."),
				});
				dialog.hide();
				if (result.message && result.message.credit_document) {
					frappe.show_alert({ message: __("Draft Sales Invoice Return prepared for accountant review."), indicator: "green" });
					frappe.set_route("Form", "Sales Invoice", result.message.credit_document);
				} else {
					await frm.reload_doc();
				}
			} finally {
				dialog.enable_primary_action();
			}
		},
	});
	dialog.fields_dict.guidance.$wrapper.html(render_guidance(context));
	dialog.fields_dict.candidate_invoices.$wrapper.html(render_candidates(context.candidate_invoices || []));
	dialog.fields_dict.source_basis.df.onchange = () => {
		const no_credit = dialog.get_value("source_basis") === "No Credit";
		dialog.set_df_property("source_sales_invoice", "reqd", !no_credit);
		dialog.set_df_property("source_sales_invoice", "hidden", no_credit);
		if (no_credit) dialog.set_value("source_sales_invoice", "");
	};
	dialog.show();
}

function render_guidance(context) {
	const escape = frappe.utils.escape_html;
	const rows = (context.accepted_items || []).map((row) =>
		`<tr><td>${escape(row.item_code)}</td><td>${escape(row.accepted_qty)}</td><td>${escape(row.stock_uom || "")}</td></tr>`
	).join("");
	return `<div class="alert alert-warning">
		<strong>${__("Accounting control")}</strong><br>
		${__("This creates a non-stock Draft Sales Invoice Return only. Review taxes and e-Invoice requirements in ERPNext before submission.")}
	</div><table class="table table-bordered"><thead><tr><th>${__("Item")}</th><th>${__("QC Accepted")}</th><th>${__("UOM")}</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function render_candidates(invoices) {
	const escape = frappe.utils.escape_html;
	if (!invoices.length) return `<p class="text-muted">${__("No submitted Sales Invoices were found for this Company and Customer.")}</p>`;
	const rows = invoices.slice(0, 15).map((row) => `<tr>
		<td>${escape(row.name)}</td><td>${escape(row.posting_date || "")}</td>
		<td>${escape(row.currency || "")} ${escape(row.grand_total || 0)}</td>
		<td><span class="indicator-pill ${row.covers_qc_items ? "green" : "orange"}">${row.covers_qc_items ? __("Quantity covered") : __("Insufficient")}</span></td>
	</tr>`).join("");
	return `<h5>${__("Recent submitted invoices for this customer")}</h5>
		<table class="table table-bordered"><thead><tr><th>${__("Invoice")}</th><th>${__("Date")}</th><th>${__("Total")}</th><th>${__("QC items")}</th></tr></thead><tbody>${rows}</tbody></table>`;
}
