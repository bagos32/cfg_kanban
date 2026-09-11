frappe.ui.form.on("CFG Kanban Cycle", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Show Event Timeline"), async () => {
			const response = await frappe.call({ method: "cfg_kanban.api.operator.get_cycle_timeline",
				args: { cycle_name: frm.doc.name } });
			const escape = frappe.utils.escape_html;
			const html = response.message.events.map((event) => `<div class="mb-3">
				<strong>${escape(event.event_type)}</strong> <span class="text-muted">${escape(event.event_datetime)}</span>
				<div>${escape(event.previous_state || "")} ${event.new_state ? "→ " + escape(event.new_state) : ""}</div>
			</div>`).join("");
			const dialog = new frappe.ui.Dialog({ title: __("Kanban Event Timeline"), size: "large" });
			dialog.$body.html(html || __("No events recorded yet."));
			dialog.show();
		});
	},
});
