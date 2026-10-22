frappe.ui.form.on("CFG Kanban Crew Template", {
	setup(frm) {
		frm.set_query("employee", "members", () => ({ filters: { status: "Active" } }));
	},
});

frappe.ui.form.on("CFG Kanban Crew Template Member", {
	crew_role(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.crew_role === "Main Operator") {
			frappe.model.set_value(cdt, cdn, "work_category", "Direct Participation");
		}
	},
});
