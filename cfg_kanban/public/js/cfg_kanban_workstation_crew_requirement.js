frappe.ui.form.on("CFG Kanban Workstation Crew Requirement", {
	setup(frm) {
		frm.set_query("crew_requirement_profile", () => ({
			filters: { active: 1, docstatus: 1 },
		}));
	},
});
