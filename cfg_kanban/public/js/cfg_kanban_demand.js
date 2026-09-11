frappe.ui.form.on("CFG Kanban Demand", {
	refresh(frm) {
		if (frm.doc.status !== "Waiting Approval") return;
		frm.add_custom_button(__("Approve and Release"), () => {
			frappe.confirm(__("Reserve {0} available Kanban card(s) and create a Work Order for {1}?",
				[frm.doc.recommended_card_count, frm.doc.recommended_qty]), async () => {
				const response = await frappe.call({ method: "cfg_kanban.services.sales_demand.approve_demand",
					args: { demand_name: frm.doc.name }, freeze: true,
					freeze_message: __("Releasing Kanban sales demand...") });
				if (response.message.blocked) {
					frappe.msgprint({ title: __("Demand Blocked"), message: response.message.message, indicator: "red" });
				} else {
					frappe.show_alert({ message: __("Work Order {0} created", [response.message.work_order]), indicator: "green" });
				}
				frm.reload_doc();
			});
		}).addClass("btn-primary");
	},
});
