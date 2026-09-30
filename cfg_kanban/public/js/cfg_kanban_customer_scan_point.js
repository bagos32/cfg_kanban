frappe.ui.form.on("CFG Kanban Customer Scan Point", {
	setup(frm) {
		frm.set_query("default_price_list", () => ({ filters: { selling: 1 } }));
	},
	proof_policy(frm) {
		frm.set_value(
			"unattended_reason_required",
			frm.doc.proof_policy === "Unattended Delivery Allowed" ? 1 : 0,
		);
	},
});
