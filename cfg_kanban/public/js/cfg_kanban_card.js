frappe.ui.form.on("CFG Kanban Card", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Open Operator Console"), () => {
			frappe.set_route("kanban-operator");
		});
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
