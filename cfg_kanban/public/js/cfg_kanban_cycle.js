frappe.ui.form.on("CFG Kanban Cycle", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("New Handling Unit"), () => {
			frappe.route_options = { kanban_cycle: frm.doc.name };
			frappe.new_doc("CFG Kanban Handling Unit");
		}, __("Create"));
		if (frm.doc.work_order) {
			frm.add_custom_button(__("Open Work Order"), () =>
				frappe.set_route("Form", "Work Order", frm.doc.work_order), __("View"));
		}
		if (frm.doc.batch_no) {
			frm.add_custom_button(__("Open Batch"), () =>
				frappe.set_route("Form", "Batch", frm.doc.batch_no), __("View"));
		}
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
