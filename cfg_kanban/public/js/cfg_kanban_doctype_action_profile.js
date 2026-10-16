frappe.ui.form.on("CFG Kanban DocType Action Profile", {
	setup(frm) {
		frm.set_query("target_doctype", () => ({
			query: "cfg_kanban.api.doctype_action.allowed_target_doctype_query",
		}));
	},

	refresh(frm) {
		if (frm.doc.target_doctype) {
			load_target_metadata(frm);
		}
		if (frm.is_new()) return;

		frm.add_custom_button(__("Validate Configuration"), async () => {
			if (frm.is_dirty()) await frm.save();
			const response = await frappe.call({
				method: "cfg_kanban.api.doctype_action.validate_configuration",
				args: { profile_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Validating live target metadata..."),
			});
			frappe.show_alert({
				message: __("Configuration is valid for {0}", [response.message.target_doctype]),
				indicator: "green",
			});
			await frm.reload_doc();
		}, __("DocType Action"));

		frm.add_custom_button(__("Preview Operator Form"), async () => {
			if (frm.is_dirty()) await frm.save();
			const response = await frappe.call({
				method: "cfg_kanban.api.doctype_action.preview_operator_form",
				args: { profile_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Building safe preview..."),
			});
			show_preview(response.message);
		}, __("DocType Action"));
	},

	target_doctype(frm) {
		clear_field_options(frm);
		if (frm.doc.target_doctype) load_target_metadata(frm);
	},
});

async function load_target_metadata(frm) {
	const response = await frappe.call({
		method: "cfg_kanban.api.doctype_action.get_target_metadata",
		args: { target_doctype: frm.doc.target_doctype },
	});
	const metadata = response.message || {};
	frm.__doctype_action_metadata = metadata;
	const parent_options = (metadata.parent_fields || []).map(option_label);
	const table_options = (metadata.child_tables || []).map(option_label);
	const child_options = [];
	const child_values = new Set();
	(metadata.child_tables || []).forEach((table) => {
		(table.columns || []).forEach((column) => {
			if (!child_values.has(column.fieldname)) {
				child_values.add(column.fieldname);
				child_options.push(option_label(column));
			}
		});
	});
	update_grid_options(frm, "parent_field_mappings", "target_fieldname", parent_options);
	update_grid_options(frm, "child_table_configs", "table_fieldname", table_options);
	update_grid_options(frm, "child_column_mappings", "table_fieldname", table_options);
	update_grid_options(frm, "child_column_mappings", "child_fieldname", child_options);
}

function option_label(field) {
	return {
		label: `${field.label}${field.fieldtype ? ` (${field.fieldtype})` : ""} — ${field.fieldname}`,
		value: field.fieldname,
	};
}

function update_grid_options(frm, table_field, child_field, options) {
	const grid = frm.fields_dict[table_field] && frm.fields_dict[table_field].grid;
	if (!grid) return;
	grid.update_docfield_property(child_field, "options", [
		{ label: "", value: "" },
		...options,
	]);
	grid.refresh();
}

function clear_field_options(frm) {
	update_grid_options(frm, "parent_field_mappings", "target_fieldname", []);
	update_grid_options(frm, "child_table_configs", "table_fieldname", []);
	update_grid_options(frm, "child_column_mappings", "table_fieldname", []);
	update_grid_options(frm, "child_column_mappings", "child_fieldname", []);
}

function show_preview(data) {
	const escape = frappe.utils.escape_html;
	const parent_fields = (data.parent_fields || []).filter((field) => field.show_to_operator);
	const parent_html = parent_fields.length
		? parent_fields.map((field) => preview_field(field, escape)).join("")
		: `<div class="text-muted">${__("No operator-visible parent fields configured.")}</div>`;
	const tables_html = (data.child_tables || []).map((table) => {
		const columns = (table.columns || []).map((field) => preview_field(field, escape)).join("");
		return `<div class="cfg-action-preview-table">
			<h5>${escape(table.label)} <span class="text-muted">(${escape(table.fieldname)})</span></h5>
			<div class="small text-muted">${__("Rows")}: ${table.min_rows}–${table.max_rows} · ${escape(table.rows_mode)}</div>
			<div class="row">${columns || `<div class="col-sm-12 text-muted">${__("No columns mapped.")}</div>`}</div>
		</div>`;
	}).join("");
	const dialog = new frappe.ui.Dialog({
		title: __("Operator Form Preview: {0}", [data.form_title || data.profile_name]),
		size: "extra-large",
		fields: [{ fieldtype: "HTML", fieldname: "preview" }],
	});
	dialog.fields_dict.preview.$wrapper.html(`
		<div class="cfg-action-preview">
			<div class="alert alert-info">
				<b>${escape(data.target_doctype)}</b> · ${escape(data.posting_policy)}<br>
				${escape(data.form_instructions || "")}
			</div>
			<div class="row">${parent_html}</div>
			${tables_html}
			<div class="text-muted small">${__("Preview only — no destination document is created.")}</div>
		</div>`);
	dialog.show();
}

function preview_field(field, escape) {
	const required = field.required ? " *" : "";
	const source = field.source_type ? ` · ${escape(field.source_type)}` : "";
	return `<div class="col-sm-6" style="margin-bottom:12px">
		<label>${escape(field.label)}${required}</label>
		<div class="form-control disabled" style="height:auto;min-height:34px">
			<span class="text-muted">${escape(field.fieldtype)}${source}</span>
		</div>
	</div>`;
}
