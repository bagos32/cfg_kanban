frappe.ui.form.on("CFG Kanban Media", {
	refresh(frm) {
		if (frm.doc.status === "available") {
			frm.add_custom_button(__("Open Private Media"), async () => {
				const response = await frappe.call({
					method: "cfg_kanban.api.media.create_view_url",
					args: { media_id: frm.doc.media_id },
				});
				window.open(response.message.url, "_blank", "noopener");
			}, __("Media"));
		}
		if (["available", "quarantined"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Archive"), async () => {
				await frappe.call({ method: "cfg_kanban.api.media.delete_object",
					args: { media_id: frm.doc.media_id, mode: "archive" }, freeze: true });
				frm.reload_doc();
			}, __("Media"));
		}
	},
});
