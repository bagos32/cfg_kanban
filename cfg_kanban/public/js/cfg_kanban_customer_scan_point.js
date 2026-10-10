frappe.ui.form.on("CFG Kanban Customer Scan Point", {
	setup(frm) {
		frm.set_query("default_price_list", () => ({ filters: { selling: 1 } }));
	},
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Print Customer Site QR"), () => {
			const format = "CFG Customer Site Card";
			const url = `/printview?doctype=${encodeURIComponent(frm.doctype)}` +
				`&name=${encodeURIComponent(frm.doc.name)}` +
				`&format=${encodeURIComponent(format)}&no_letterhead=1`;
			window.open(url, "_blank");
		});
		frm.add_custom_button(__("Open Logistics Panel"), () => {
			frappe.set_route("kanban-logistics");
		});
	},
	proof_policy(frm) {
		frm.set_value(
			"unattended_reason_required",
			frm.doc.proof_policy === "Unattended Delivery Allowed" ? 1 : 0,
		);
	},
});
