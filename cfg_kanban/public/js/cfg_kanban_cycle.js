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
		if (["Manufacturing Manager", "System Manager"].some((role) => frappe.user_roles.includes(role))) {
			frm.add_custom_button(__("Resolve Effective Work Order"), () => {
				frappe.prompt([
					{ fieldname: "work_order", label: __("Effective Work Order"), fieldtype: "Link", options: "Work Order", reqd: 1,
						get_query: () => ({ filters: { production_item: frm.doc.item_code, docstatus: 1 } }) },
					{ fieldname: "reason", label: __("Reconciliation Reason"), fieldtype: "Small Text", reqd: 1 },
				], async (values) => {
					const response = await frappe.call({
						method: "cfg_kanban.integrations.erp_feedback.select_effective_work_order",
						args: { cycle_name: frm.doc.name, work_order_name: values.work_order, reason: values.reason },
						freeze: true, freeze_message: __("Resolving effective Work Order..."),
					});
					frappe.show_alert({ message: __("Effective Work Order {0} selected with {1} Job Card(s)",
						[response.message.work_order, response.message.job_cards]), indicator: "green" });
					frm.reload_doc();
				}, __("Resolve Work Order Ambiguity"), __("Confirm"));
			}, __("Kanban Recovery"));
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
