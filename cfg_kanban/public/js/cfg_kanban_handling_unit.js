frappe.ui.form.on("CFG Kanban Handling Unit", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Print Thermal Tag"), () => audited_print(
			frm, "CFG Kanban Handling Unit Tag"), __("Kanban Actions"));
		if (!["Received", "Void", "Replaced"].includes(frm.doc.state)) {
			frm.add_custom_button(__("Replace Tag"), () => replace_tag(frm), __("Kanban Actions"));
		}
	},
});

async function audited_print(frm, format) {
	const reason = frm.doc.print_count ? await ask_reason(__("Reason for reprint")) : null;
	if (frm.doc.print_count && !reason) return;
	await frappe.call({ method: "cfg_kanban.services.printing.record_print",
		args: { doctype: frm.doctype, name: frm.doc.name, print_format: format, reason } });
	await frm.reload_doc();
	const url = `/printview?doctype=${encodeURIComponent(frm.doctype)}&name=${encodeURIComponent(frm.doc.name)}` +
		`&format=${encodeURIComponent(format)}&no_letterhead=1`;
	window.open(url, "_blank");
}

function ask_reason(label) {
	return new Promise((resolve) => frappe.prompt([
		{ fieldname: "reason", label, fieldtype: "Small Text", reqd: 1 },
	], (values) => resolve(values.reason), __("Reprint Control"), __("Continue")));
}

function replace_tag(frm) {
	frappe.prompt([
		{ fieldname: "new_id", label: __("New Handling Unit ID"), fieldtype: "Data", reqd: 1 },
		{ fieldname: "reason", label: __("Replacement Reason"), fieldtype: "Small Text", reqd: 1 },
	], async (values) => {
		const response = await frappe.call({ method: "cfg_kanban.services.printing.replace_handling_unit",
			args: { unit_name: frm.doc.name, new_handling_unit_id: values.new_id, reason: values.reason }, freeze: true });
		frappe.set_route("Form", "CFG Kanban Handling Unit", response.message.new_unit);
	}, __("Replace Handling Unit Tag"), __("Create Replacement"));
}
