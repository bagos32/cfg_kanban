const CFG_TRACE_PURPOSES = [
	"Manufacture",
	"Material Transfer for Manufacture",
	"Material Consumption for Manufacture",
	"Repack",
];

frappe.ui.form.on("Stock Entry", {
	refresh(frm) {
		const purpose = frm.doc.purpose || frm.doc.stock_entry_type;
		if (frm.is_new() || !CFG_TRACE_PURPOSES.includes(purpose) || frm.doc.docstatus > 1) return;
		frm.add_custom_button(__("Production Material Trace"), () => production_trace_dialog(frm),
			__("CFG Kanban"));
	},
});

async function production_trace_dialog(frm) {
	let plan = await load_production_trace_plan(frm.doc.name);
	let dialog;
	dialog = new frappe.ui.Dialog({
		title: __("Production Material Trace"),
		size: "extra-large",
		fields: [
			{ fieldname: "summary", fieldtype: "HTML" },
			{ fieldname: "input_section", label: __("Allocate Tagged Material Input"), fieldtype: "Section Break" },
			{ fieldname: "input_row", label: __("Input Row"), fieldtype: "Select" },
			{ fieldname: "input_scan", label: __("Handling Unit Tag"), fieldtype: "Data",
				description: __("Scan an active tag currently located in the Stock Entry source Warehouse.") },
			{ fieldname: "input_qty", label: __("Stock Quantity"), fieldtype: "Float" },
			{ fieldname: "allocate_input", label: __("Allocate Input Tag"), fieldtype: "Button",
				click: async () => {
					const row_name = row_name_from_option(dialog.get_value("input_row"));
					await frappe.call({
						method: "cfg_kanban.services.production_trace.allocate_input_tag",
						args: { stock_entry: frm.doc.name, item_row: row_name,
							scan_value: dialog.get_value("input_scan"), qty: dialog.get_value("input_qty") },
						freeze: true,
						freeze_message: __("Reserving tagged input for this Stock Entry..."),
					});
					frappe.show_alert({ message: __("Input tag reserved"), indicator: "green" });
					plan = await load_production_trace_plan(frm.doc.name);
					await refresh_production_trace_dialog(dialog, plan);
					await dialog.set_value("input_scan", "");
					dialog.get_field("input_scan").$input.trigger("focus");
				} },
			{ fieldname: "output_section", label: __("Stage Preprinted Production Output Tag"), fieldtype: "Section Break" },
			{ fieldname: "output_row", label: __("Output Row"), fieldtype: "Select" },
			{ fieldname: "output_scan", label: __("Unused Preprinted Main Tag"), fieldtype: "Data",
				description: __("The tag remains pending until ERPNext submits the Stock Entry.") },
			{ fieldname: "output_qty", label: __("Stock Quantity"), fieldtype: "Float" },
			{ fieldname: "handling_unit_type", label: __("Handling Unit Type"), fieldtype: "Select",
				options: "Pallet\nMesh\nTote\nContainer\nReusable Box\nOther", default: "Container" },
			{ fieldname: "stage_output", label: __("Stage Output Tag"), fieldtype: "Button",
				click: async () => {
					const row_name = row_name_from_option(dialog.get_value("output_row"));
					await frappe.call({
						method: "cfg_kanban.services.production_trace.stage_output_tag",
						args: { stock_entry: frm.doc.name, item_row: row_name,
							scan_value: dialog.get_value("output_scan"), qty: dialog.get_value("output_qty"),
							handling_unit_type: dialog.get_value("handling_unit_type") },
						freeze: true,
						freeze_message: __("Validating and staging the production output tag..."),
					});
					frappe.show_alert({ message: __("Output tag staged"), indicator: "green" });
					plan = await load_production_trace_plan(frm.doc.name);
					await refresh_production_trace_dialog(dialog, plan);
					await dialog.set_value("output_scan", "");
					dialog.get_field("output_scan").$input.trigger("focus");
				} },
			{ fieldname: "line_section", label: __("Staged Trace Lines"), fieldtype: "Section Break" },
			{ fieldname: "lines", fieldtype: "HTML" },
			{ fieldname: "abandon_trace", label: __("Discard Entire Draft Trace"), fieldtype: "Button",
				click: () => {
					frappe.prompt([
						{ fieldname: "reason", label: __("Reason"), fieldtype: "Small Text", reqd: 1 },
					], async (values) => {
						await frappe.call({
							method: "cfg_kanban.services.production_trace.abandon_draft_trace",
							args: { stock_entry: frm.doc.name, reason: values.reason },
							freeze: true,
							freeze_message: __("Releasing all Draft trace reservations..."),
						});
						frappe.show_alert({ message: __("Draft Material Trace abandoned"), indicator: "orange" });
						dialog.hide();
					}, __("Discard Draft Material Trace"), __("Confirm"));
				} },
		],
	});
	dialog.show();
	await refresh_production_trace_dialog(dialog, plan);
}

async function load_production_trace_plan(stock_entry) {
	const response = await frappe.call({
		method: "cfg_kanban.services.production_trace.get_stock_entry_trace_plan",
		args: { stock_entry },
	});
	return response.message;
}

async function refresh_production_trace_dialog(dialog, plan) {
	const inputs = (plan.rows || []).filter((row) => row.direction === "Input" &&
		row.tagging_available && row.remaining_qty > 0.000001);
	const outputs = (plan.rows || []).filter((row) => row.direction === "Output" &&
		row.tagging_available && row.remaining_qty > 0.000001);
	const input_options = inputs.map(trace_row_option);
	const output_options = outputs.map(trace_row_option);
	dialog.set_df_property("input_row", "options", input_options.join("\n"));
	dialog.set_df_property("output_row", "options", output_options.join("\n"));
	dialog.fields_dict.summary.$wrapper.html(production_trace_summary(plan));
	dialog.fields_dict.lines.$wrapper.html(production_trace_lines(plan));
	dialog.get_field("abandon_trace").wrapper.toggle(Boolean(plan.can_abandon));
	dialog.get_field("abandon_trace").$input.addClass("btn-danger");

	const input_visible = plan.can_edit && input_options.length;
	const output_visible = plan.can_edit && output_options.length;
	for (const fieldname of ["input_section", "input_row", "input_scan", "input_qty", "allocate_input"]) {
		dialog.get_field(fieldname).wrapper.toggle(Boolean(input_visible));
	}
	for (const fieldname of ["output_section", "output_row", "output_scan", "output_qty",
		"handling_unit_type", "stage_output"]) {
		dialog.get_field(fieldname).wrapper.toggle(Boolean(output_visible));
	}
	if (input_visible) {
		const selected = input_options.includes(dialog.get_value("input_row")) ?
			dialog.get_value("input_row") : input_options[0];
		await dialog.set_value("input_row", selected);
		await dialog.set_value("input_qty", row_for_option(inputs, selected).remaining_qty);
		bind_quantity_change(dialog, "input_row", "input_qty", inputs);
	}
	if (output_visible) {
		const selected = output_options.includes(dialog.get_value("output_row")) ?
			dialog.get_value("output_row") : output_options[0];
		await dialog.set_value("output_row", selected);
		await dialog.set_value("output_qty", row_for_option(outputs, selected).remaining_qty);
		bind_quantity_change(dialog, "output_row", "output_qty", outputs);
	}
	dialog.fields_dict.lines.$wrapper.find("[data-cancel-trace-line]").off("click").on("click", async (event) => {
		const trace_line = event.currentTarget.dataset.cancelTraceLine;
		await frappe.call({
			method: "cfg_kanban.services.production_trace.cancel_trace_line",
			args: { stock_entry: plan.stock_entry, trace_line },
			freeze: true,
			freeze_message: __("Releasing the staged material trace..."),
		});
		plan = await load_production_trace_plan(plan.stock_entry);
		await refresh_production_trace_dialog(dialog, plan);
	});
}

function bind_quantity_change(dialog, select_field, qty_field, rows) {
	const $select = dialog.get_field(select_field).$input;
	$select.off("change.cfg_trace").on("change.cfg_trace", () => {
		const row = row_for_option(rows, dialog.get_value(select_field));
		if (row) dialog.set_value(qty_field, row.remaining_qty);
	});
}

function trace_row_option(row) {
	return `${row.row_name} :: ${row.item_code} :: ${row.remaining_qty} ${row.stock_uom}`;
}

function row_name_from_option(value) {
	return String(value || "").split(" :: ")[0];
}

function row_for_option(rows, value) {
	const row_name = row_name_from_option(value);
	return rows.find((row) => row.row_name === row_name);
}

function production_trace_summary(plan) {
	const e = frappe.utils.escape_html;
	const rows = (plan.rows || []).map((row) => `<tr>
		<td>${e(row.direction)}</td><td>${e(row.item_code)}</td><td>${e(row.batch_no || "-")}</td>
		<td>${e(row.warehouse || "-")}</td><td>${e(row.tag_policy)}</td>
		<td>${e(row.traced_qty)} / ${e(row.stock_qty)} ${e(row.stock_uom)}</td>
	</tr>`).join("");
	return `<div class="alert alert-info"><strong>${e(plan.stock_entry)}</strong> · ${e(plan.purpose)} ·
		${e(plan.company)}<br>${__("Material Trace")}: ${e(plan.trace || __("Not created"))} · ${e(plan.trace_status)}</div>
		<div class="table-responsive"><table class="table table-bordered table-sm"><thead><tr>
		<th>${__("Stage")}</th><th>${__("Item")}</th><th>${__("Batch")}</th><th>${__("Warehouse")}</th>
		<th>${__("Tag Policy")}</th><th>${__("Traced / ERP Qty")}</th></tr></thead><tbody>${rows}</tbody></table></div>
		<p class="text-muted">${__("No Physical Tag rows remain normal ERPNext stock. Only explicit Required policies gate Stock Entry submission.")}</p>`;
}

function production_trace_lines(plan) {
	if (!(plan.lines || []).length) return `<p class="text-muted">${__("No production tags staged.")}</p>`;
	const e = frappe.utils.escape_html;
	const rows = plan.lines.map((line) => `<tr>
		<td>${e(line.direction)}</td><td>${e(line.item_code)}</td>
		<td>${e(line.handling_unit || line.pending_tag_code || "-")}</td>
		<td>${e(line.qty)} ${e(line.stock_uom)}</td><td>${e(line.status)}</td>
		<td>${line.can_cancel ? `<button class="btn btn-xs btn-danger" data-cancel-trace-line="${e(line.name)}">${__("Cancel")}</button>` : ""}</td>
	</tr>`).join("");
	return `<div class="table-responsive"><table class="table table-bordered table-sm"><thead><tr>
		<th>${__("Direction")}</th><th>${__("Item")}</th><th>${__("Handling Unit / Pending Tag")}</th>
		<th>${__("Quantity")}</th><th>${__("Status")}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
