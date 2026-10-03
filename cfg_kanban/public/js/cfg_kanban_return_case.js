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
	},
});

function can_prepare_accounting(frm) {
	const allowed = ["Accounts User", "Accounts Manager", "Sales Manager", "System Manager"];
	return frm.doc.state === "QC Completed - Accounting Pending"
		&& Number(frm.doc.accepted_total_qty || 0) > 0
		&& !(frm.doc.credit_document && frm.doc.credit_document_status !== "Cancelled")
		&& allowed.some((role) => frappe.user_roles.includes(role));
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
