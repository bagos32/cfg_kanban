frappe.ui.form.on("CFG Kanban Card", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Open Operator Console"), () => {
			frappe.set_route("kanban-operator");
		});
		frm.add_custom_button(__("Print Standard Card"), () => cfg_card_print(frm,
			"CFG Kanban Standard Card"), __("Print Kanban"));
		frm.add_custom_button(__("Print Operational Card"), () => cfg_card_print(frm,
			"CFG Kanban Operational Card"), __("Print Kanban"));
		if (frm.doc.active) {
			frm.add_custom_button(__("Replace Card"), () => cfg_replace_card(frm), __("Print Kanban"));
		}
		if (frm.doc.current_state === "Available" && !frm.doc.active_cycle && frm.doc.active) {
			frm.add_custom_button(__("Consume / Trigger"), async () => {
				await frappe.call({ method: "cfg_kanban.api.scan.scan", args: {
					token: frm.doc.qr_code, action: "consume", event_token: frappe.utils.get_random(16),
				}, freeze: true });
				frappe.show_alert({ message: __("Kanban signal created"), indicator: "green" });
				frm.reload_doc();
			}, __("Kanban Actions"));
		}
	},
});

async function cfg_card_print(frm, format) {
	let reason = null;
	if (frm.doc.print_count) {
		reason = await new Promise((resolve) => frappe.prompt([
			{ fieldname: "reason", label: __("Reason for reprint"), fieldtype: "Small Text", reqd: 1 },
		], (values) => resolve(values.reason), __("Reprint Control"), __("Continue")));
	}
	await frappe.call({ method: "cfg_kanban.services.printing.record_print", args: {
		doctype: frm.doctype, name: frm.doc.name, print_format: format, reason,
	} });
	await frm.reload_doc();
	window.open(`/printview?doctype=${encodeURIComponent(frm.doctype)}&name=${encodeURIComponent(frm.doc.name)}` +
		`&format=${encodeURIComponent(format)}&no_letterhead=1`, "_blank");
}

function cfg_replace_card(frm) {
	frappe.prompt([
		{ fieldname: "new_card_number", label: __("New Card Number"), fieldtype: "Data", reqd: 1 },
		{ fieldname: "reason", label: __("Replacement Reason"), fieldtype: "Small Text", reqd: 1 },
	], async (values) => {
		const response = await frappe.call({ method: "cfg_kanban.services.printing.replace_card", args: {
			card_name: frm.doc.name, new_card_number: values.new_card_number, reason: values.reason,
		}, freeze: true });
		frappe.set_route("Form", "CFG Kanban Card", response.message.new_card);
	}, __("Replace Reusable Kanban Card"), __("Create Replacement"));
}
