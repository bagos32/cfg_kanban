frappe.ui.form.on("CFG Kanban Demand", {
	refresh(frm) {
		if (frm.doc.status !== "Waiting Approval") return;
		frm.add_custom_button(__("Approve and Release"), () => {
			const is_mto = frm.doc.production_policy === "Customer Make-to-Order";
			const question = is_mto
				? __("Create one MTO cycle, dedicated Batch, and Work Order for {0}? No reusable card will be consumed.", [frm.doc.recommended_qty])
				: __("Reserve {0} available Kanban card(s) and create a Work Order for {1}?", [frm.doc.recommended_card_count, frm.doc.recommended_qty]);
			frappe.confirm(question, async () => {
				const response = await frappe.call({ method: "cfg_kanban.services.sales_demand.approve_demand",
					args: { demand_name: frm.doc.name }, freeze: true,
					freeze_message: __("Releasing Kanban sales demand...") });
				if (response.message.blocked) {
					frappe.msgprint({ title: __("Demand Blocked"), message: response.message.message, indicator: "red" });
				} else {
					const message = response.message.batch
						? __("Work Order {0} and Batch {1} created", [response.message.work_order, response.message.batch])
						: __("Work Order {0} created", [response.message.work_order]);
					frappe.show_alert({ message, indicator: "green" });
				}
				frm.reload_doc();
			});
		}).addClass("btn-primary");
	},
});
