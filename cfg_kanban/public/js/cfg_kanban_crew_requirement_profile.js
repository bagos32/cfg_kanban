frappe.ui.form.on("CFG Kanban Crew Requirement Profile", {
	setup(frm) {
		frm.set_query("skill", "skill_requirements", () => ({ filters: { active: 1 } }));
	},
	crew_mode(frm) {
		const mode = frm.doc.crew_mode;
		if (mode === "Single Operator") {
			frm.set_value("minimum_direct_workers", 1);
			frm.set_value("minimum_assistants", 0);
		} else if (mode === "Multiple Operators" && (frm.doc.minimum_direct_workers || 0) < 2) {
			frm.set_value("minimum_direct_workers", 2);
		} else if (mode === "Supervised Operation" &&
			frm.doc.supervision_presence === "Not Required") {
			frm.set_value("supervision_presence", "Always Required");
		} else if (mode === "Qualified Lead + Assistants") {
			if ((frm.doc.minimum_assistants || 0) < 1) frm.set_value("minimum_assistants", 1);
			if ((frm.doc.minimum_direct_workers || 0) < 2) frm.set_value("minimum_direct_workers", 2);
		}
	},
	trainee_policy(frm) {
		if (frm.doc.trainee_policy === "Supervised Only" &&
			frm.doc.supervision_presence === "Not Required") {
			frm.set_value("supervision_presence", "Required When Trainees Present");
		}
	},
});

frappe.ui.form.on("CFG Kanban Crew Skill Requirement", {
	participation_role(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.participation_role === "Qualified Lead") {
			frappe.model.set_value(cdt, cdn, "require_independent_authorization", 1);
		}
		if (row.participation_role === "Active Supervisor") {
			frappe.model.set_value(cdt, cdn, "require_supervisor_authorization", 1);
		}
	},
});
