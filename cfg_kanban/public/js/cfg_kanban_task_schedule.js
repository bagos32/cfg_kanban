frappe.ui.form.on("CFG Kanban Task Schedule", {
	refresh(frm) {
		(frm.doc.task_field_definitions || []).forEach((row) => {
			if (row.definition_scope !== "Standalone Task") {
				frappe.model.set_value(row.doctype, row.name, "definition_scope", "Standalone Task");
			}
		});
	},
});

frappe.ui.form.on("CFG Kanban Field Definition", {
	task_field_definitions_add(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "definition_scope", "Standalone Task");
	},
});
