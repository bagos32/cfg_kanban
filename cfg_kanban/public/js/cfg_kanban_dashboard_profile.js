frappe.ui.form.on("CFG Kanban Dashboard Profile", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.active) return;
		frm.add_custom_button(__("Open Saved Screen"), () => {
			window.open(`/app/kanban-floor?profile=${encodeURIComponent(frm.doc.name)}`, "_blank");
		}).addClass("btn-primary");
	},
});
