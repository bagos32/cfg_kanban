frappe.ui.form.on("Purchase Receipt", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || frm.doc.is_return) return;
		frm.add_custom_button(__("Tag Received Material"), () => receiving_tag_dialog(frm),
			__("CFG Kanban"));
	},
});

async function receiving_tag_dialog(frm) {
	let plan = await load_trace_plan(frm.doc.name);
	const dialog = new frappe.ui.Dialog({
		title: __("Tag Confirmed Purchase Receipt Material"),
		size: "large",
		fields: [
			{ fieldname: "summary", fieldtype: "HTML" },
			{ fieldname: "item_row", label: __("Receipt Item"), fieldtype: "Select", reqd: 1 },
			{ fieldname: "scan_value", label: __("Preprinted Main Tag"), fieldtype: "Data", reqd: 1,
				description: __("Scan a still-unused main Stock Tag from an active Tag Range Registry.") },
			{ fieldname: "qty", label: __("Quantity in Stock UOM"), fieldtype: "Float", reqd: 1 },
			{ fieldname: "handling_unit_type", label: __("Handling Unit Type"), fieldtype: "Select",
				options: "Pallet\nMesh\nTote\nContainer\nReusable Box\nOther", default: "Container", reqd: 1 },
		],
		primary_action_label: __("Activate Received Tag"),
		primary_action: async (values) => {
			const row_name = String(values.item_row || "").split(" :: ")[0];
			await frappe.call({
				method: "cfg_kanban.api.receiving.activate_purchase_receipt_tag",
				args: {
					purchase_receipt: frm.doc.name,
					item_row: row_name,
					scan_value: values.scan_value,
					qty: values.qty,
					handling_unit_type: values.handling_unit_type,
				},
				freeze: true,
				freeze_message: __("Validating ERP receipt quantity and activating tag..."),
			});
			frappe.show_alert({ message: __("Received-material tag activated"), indicator: "green" });
			plan = await load_trace_plan(frm.doc.name);
			await refresh_receiving_dialog(dialog, plan);
			await dialog.set_value("scan_value", "");
			dialog.get_field("scan_value").$input.trigger("focus");
		},
	});
	dialog.show();
	await refresh_receiving_dialog(dialog, plan);
}

async function load_trace_plan(purchase_receipt) {
	const response = await frappe.call({
		method: "cfg_kanban.api.receiving.get_purchase_receipt_trace_plan",
		args: { purchase_receipt },
	});
	return response.message;
}

async function refresh_receiving_dialog(dialog, plan) {
	const available = (plan.rows || []).filter((row) => row.tagging_available && row.remaining_stock_qty > 0.000001);
	const options = available.map((row) => `${row.row_name} :: ${row.item_code} :: ${row.remaining_stock_qty} ${row.stock_uom}`);
	dialog.set_df_property("item_row", "options", options.join("\n"));
	dialog.fields_dict.summary.$wrapper.html(receiving_summary(plan));
	if (!options.length) {
		await dialog.set_value("item_row", "");
		await dialog.set_value("qty", 0);
		dialog.disable_primary_action();
		return;
	}
	dialog.enable_primary_action();
	const current = options.includes(dialog.get_value("item_row")) ? dialog.get_value("item_row") : options[0];
	await dialog.set_value("item_row", current);
	const selected = available.find((row) => row.row_name === current.split(" :: ")[0]);
	await dialog.set_value("qty", selected ? selected.remaining_stock_qty : 0);
	const $select = dialog.get_field("item_row").$input;
	$select.off("change.cfg_receiving").on("change.cfg_receiving", () => {
		const row_name = String(dialog.get_value("item_row") || "").split(" :: ")[0];
		const row = available.find((candidate) => candidate.row_name === row_name);
		if (row) dialog.set_value("qty", row.remaining_stock_qty);
	});
}

function receiving_summary(plan) {
	const e = frappe.utils.escape_html;
	const rows = (plan.rows || []).map((row) => `<tr>
		<td>${e(row.item_code)}</td><td>${e(row.batch_no || "-")}</td><td>${e(row.warehouse || "-")}</td>
		<td>${e(row.tag_policy)}</td><td>${e(row.tagged_stock_qty)} / ${e(row.confirmed_stock_qty)} ${e(row.stock_uom)}</td>
	</tr>`).join("");
	return `<div class="alert alert-info"><strong>${e(plan.purchase_receipt)}</strong> · ${e(plan.company)} · ${e(plan.supplier)}</div>
		<div class="table-responsive"><table class="table table-bordered table-sm"><thead><tr>
		<th>${__("Item")}</th><th>${__("Batch")}</th><th>${__("Warehouse")}</th><th>${__("Tag Policy")}</th><th>${__("Tagged / Confirmed")}</th>
		</tr></thead><tbody>${rows}</tbody></table></div>
		<p class="text-muted">${__("Rows configured as No Physical Tag remain valid ERPNext warehouse stock and require no Kanban tag.")}</p>`;
}
