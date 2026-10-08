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
			{ fieldname: "row_guidance", fieldtype: "HTML" },
			{ fieldname: "scan_value", label: __("Preprinted Main Tag"), fieldtype: "Data", reqd: 1,
				description: __("Scan a still-unused main Stock Tag from an active Tag Range Registry.") },
			{ fieldname: "qty", label: __("Quantity in Stock UOM"), fieldtype: "Float", reqd: 1 },
			{ fieldname: "serial_numbers", label: __("Exact Serial Numbers"), fieldtype: "Small Text",
				description: __("Serial-controlled Items only. Enter or scan one ERPNext Serial No per line. The field fills automatically when this tag takes every remaining serial.") },
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
					serial_numbers: values.serial_numbers,
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
	const rows = plan.rows || [];
	const options = rows.map((row) => `${row.row_name} :: ${row.item_code} :: ${row.remaining_stock_qty} ${row.stock_uom} :: ${row.tag_policy}`);
	dialog.set_df_property("item_row", "options", options.join("\n"));
	dialog.fields_dict.summary.$wrapper.html(receiving_summary(plan));
	if (!options.length) {
		await dialog.set_value("item_row", "");
		await dialog.set_value("qty", 0);
		await dialog.set_value("serial_numbers", "");
		dialog.fields_dict.row_guidance.$wrapper.html(
			`<div class="alert alert-warning">${__("This submitted Purchase Receipt has no Item rows available for review.")}</div>`);
		dialog.disable_primary_action();
		return;
	}
	const current = options.includes(dialog.get_value("item_row")) ? dialog.get_value("item_row") : options[0];
	await dialog.set_value("item_row", current);
	const selected = rows.find((row) => row.row_name === current.split(" :: ")[0]);
	await apply_receiving_row(dialog, selected);
	const $select = dialog.get_field("item_row").$input;
	$select.off("change.cfg_receiving").on("change.cfg_receiving", () => {
		const row_name = String(dialog.get_value("item_row") || "").split(" :: ")[0];
		const row = rows.find((candidate) => candidate.row_name === row_name);
		if (row) apply_receiving_row(dialog, row);
	});
}

async function apply_receiving_row(dialog, row) {
	const e = frappe.utils.escape_html;
	if (!row) {
		dialog.disable_primary_action();
		return;
	}
	await dialog.set_value("scan_value", "");
	await dialog.set_value("qty", row.remaining_stock_qty || 0);
	await update_receiving_serial_field(dialog, row);
	if (row.tagging_ready) {
		dialog.fields_dict.row_guidance.$wrapper.html(
			`<div class="alert alert-success"><strong>${__("Ready to tag")}</strong> · ${e(row.item_code)} · ${e(row.remaining_stock_qty)} ${e(row.stock_uom)}</div>`);
		dialog.enable_primary_action();
		dialog.get_field("scan_value").$input.prop("disabled", false);
		dialog.get_field("qty").$input.prop("disabled", false);
		return;
	}
	dialog.fields_dict.row_guidance.$wrapper.html(
		`<div class="alert alert-warning"><strong>${e(row.item_code)}</strong><br>${e(row.tagging_status || __("This row is not ready for tag activation."))}<br>
		<small>${__("Policy source")}: ${e(row.policy_source || "-")}</small></div>`);
	dialog.disable_primary_action();
	dialog.get_field("scan_value").$input.prop("disabled", true);
	dialog.get_field("qty").$input.prop("disabled", true);
}

async function update_receiving_serial_field(dialog, row) {
	const visible = Boolean(row && row.tagging_ready && row.serial_controlled);
	dialog.get_field("serial_numbers").wrapper.toggle(visible);
	await dialog.set_value("serial_numbers", visible ? (row.available_serial_numbers || []).join("\n") : "");
}

function receiving_summary(plan) {
	const e = frappe.utils.escape_html;
	const rows = (plan.rows || []).map((row) => `<tr>
		<td>${e(row.item_code)}</td><td>${e(row.batch_no || "-")}</td><td>${e(row.warehouse || "-")}</td>
		<td>${e(row.tag_policy)}</td><td>${e(row.tagged_stock_qty)} / ${e(row.confirmed_stock_qty)} ${e(row.stock_uom)}</td>
		<td><span class="indicator-pill ${row.tagging_ready ? "green" : "orange"}">${e(row.tagging_ready ? __("Ready") : __("Attention"))}</span><br><small>${e(row.tagging_status || "")}</small></td>
	</tr>`).join("");
	return `<div class="alert alert-info"><strong>${e(plan.purchase_receipt)}</strong> · ${e(plan.company)} · ${e(plan.supplier)}</div>
		<div class="table-responsive"><table class="table table-bordered table-sm"><thead><tr>
		<th>${__("Item")}</th><th>${__("Batch")}</th><th>${__("Warehouse")}</th><th>${__("Tag Policy")}</th><th>${__("Tagged / Confirmed")}</th><th>${__("Status")}</th>
		</tr></thead><tbody>${rows}</tbody></table></div>
		<p class="text-muted">${__("Every receipt row is listed. Rows configured as No Physical Tag remain valid ERPNext warehouse stock and intentionally cannot activate a Kanban Stock Tag.")}</p>`;
}
