frappe.ui.form.on("CFG Kanban Tag Range Registry", {
	refresh(frm) {
		frm.set_intro(__(
			"This registry recognizes a printed serial range without creating thousands of records. The exact Tag Family and its detachable children are created only when a covered tag is first activated as a Handling Unit."
		), "blue");
		if (!frm.is_new()) {
			frm.add_custom_button(__("View Materialized Tag Families"), () => {
				frappe.route_options = { range_registry: frm.doc.name };
				frappe.set_route("List", "CFG Kanban Tag Family");
			});
		}
		update_preview(frm);
	},
	prefix: update_preview,
	start_number: update_preview,
	end_number: update_preview,
	number_width: update_preview,
	child_count: update_preview,
});

function update_preview(frm) {
	const prefix = String(frm.doc.prefix || "");
	const start = Number(frm.doc.start_number);
	const end = Number(frm.doc.end_number);
	const width = Number(frm.doc.number_width);
	const children = Number(frm.doc.child_count || 0);
	if (!prefix || !Number.isInteger(start) || !Number.isInteger(end) ||
		!Number.isInteger(width) || width < 1 || end < start) return;
	const format = (number) => `${prefix}${String(number).padStart(width, "0")}`;
	frm.set_value("first_main_code", format(start));
	frm.set_value("last_main_code", format(end));
	frm.set_value("total_main_tags", end - start + 1);
	frm.set_value("potential_identity_count", (end - start + 1) * (children + 1));
}
