function configure_job_card_item_operations(frm) {
	const job_card_transfer = frm.doc.transfer_material_against === "Job Card";
	const items_grid = frm.get_field("items") && frm.get_field("items").grid;
	if (items_grid) {
		items_grid.update_docfield_property("operation", "reqd", job_card_transfer ? 1 : 0);
	}
	frm.set_df_property("items", "description", job_card_transfer
		? __("Item Operation is mandatory on every raw-material row because materials are controlled by Job Card.")
		: "");
	frm.refresh_field("items");
}

function validate_job_card_item_operations(frm) {
	if (frm.doc.transfer_material_against !== "Job Card") return;
	if (!frm.doc.with_operations) {
		frappe.throw(__("Enable With Operations before selecting Job Card material transfer."));
	}
	const missing = (frm.doc.items || []).filter((row) => !row.operation);
	if (!missing.length) return;
	const details = missing.map((row) => {
		return __("Row #{0}: {1}", [row.idx, row.item_code || __("Unspecified Item")]);
	}).join("<br>");
	frappe.throw(__("Transfer Material Against is Job Card. Set Item Operation on every raw-material row:<br>{0}", [details]));
}

frappe.ui.form.on("BOM", {
	refresh(frm) {
		configure_job_card_item_operations(frm);
	},
	transfer_material_against(frm) {
		configure_job_card_item_operations(frm);
	},
	with_operations(frm) {
		configure_job_card_item_operations(frm);
	},
	validate(frm) {
		validate_job_card_item_operations(frm);
	},
});
