frappe.ui.form.on("CFG Kanban Card", {
	setup(frm) {
		frm.set_query("operation", () => ({
			query: "cfg_kanban.api.form_queries.master_operations",
			filters: { kanban_master: frm.doc.kanban_master || "" },
		}));
	},
	kanban_master(frm) {
		frm.set_value("operation", null);
		if (!frm.doc.kanban_master) return;
		frappe.db.get_value("CFG Kanban Master", frm.doc.kanban_master,
			["item_code", "stock_uom", "replenishment_qty", "source_warehouse", "destination_warehouse", "control_type"])
			.then(async ({ message }) => {
				const stock_control = ["Purchase Replenishment", "Transfer", "Withdrawal"].includes(message.control_type);
				if (stock_control && !["Physical Unit Card", "Physical Batch Card"].includes(frm.doc.card_type)) {
					await frm.set_value("card_type", "Physical Batch Card");
					frappe.show_alert({
						message: __("{0} uses a physical stock-control card; Task Schedule is not required.", [message.control_type]),
						indicator: "blue",
					});
				}
				return frm.set_value({
				item_code: message.item_code,
				stock_uom: message.stock_uom,
				kanban_qty: frm.doc.kanban_qty || message.replenishment_qty,
				source_warehouse: message.source_warehouse,
				destination_warehouse: message.destination_warehouse,
				current_warehouse: frm.doc.current_warehouse || message.destination_warehouse,
				});
			});
	},
	operation(frm) {
		if (!frm.doc.kanban_master || !frm.doc.operation) {
			frm.set_value({ workstation: null, handoff_mode: null });
			return;
		}
		frappe.call({ method: "cfg_kanban.api.form_queries.operation_profile_context", args: {
			kanban_master: frm.doc.kanban_master, operation: frm.doc.operation,
		} }).then(({ message }) => {
			const values = message || {};
			if (frm.doc.card_type !== "Station Kanban") values.workstation = null;
			frm.set_value(values);
		});
	},
	card_type(frm) {
		const production = ["Physical Unit Card", "Physical Batch Card", "Process Kanban", "Station Kanban"].includes(frm.doc.card_type);
		const required = ["Process Kanban", "Station Kanban"].includes(frm.doc.card_type);
		frm.set_df_property("kanban_master", "reqd", production);
		frm.set_df_property("kanban_qty", "reqd", production);
		frm.set_df_property("operation", "reqd", required);
		if (frm.doc.card_type !== "Station Kanban" && frm.doc.workstation) {
			frm.set_value("workstation", null);
		}
		if (frm.doc.card_type !== "Task Card" && frm.doc.task_schedule) {
			frm.set_value("task_schedule", null);
		}
		if (!production && frm.doc.kanban_master) {
			frappe.show_alert({
				message: __("Service identity cards do not use a Kanban Master. Select a physical card for stock control."),
				indicator: "orange",
			});
		}
	},
	refresh(frm) {
		frm.trigger("card_type");
		if (frm.is_new()) return;
		frm.add_custom_button(__("Open Operator Console"), () => {
			frappe.set_route("kanban-operator");
		});
		const master_backed = Boolean(frm.doc.kanban_master);
		if (master_backed) {
			frm.add_custom_button(__("Print Card with QR"), () => cfg_card_print(frm,
				"CFG Kanban Operational Card"));
			frm.add_custom_button(__("Print Standard Card"), () => cfg_card_print(frm,
				"CFG Kanban Standard Card"), __("Print Kanban"));
			frm.add_custom_button(__("Print Operational Card"), () => cfg_card_print(frm,
				"CFG Kanban Operational Card"), __("Print Kanban"));
		}
		if (frm.doc.card_type === "Location Card" && frm.doc.location_purpose === "Supplier Receiving") {
			frm.add_custom_button(__("Print Supplier Receiving Location Card"), () => cfg_card_print(frm,
				"CFG Supplier Receiving Location Card"), __("Print Kanban"));
			frm.add_custom_button(__("Open Logistics Panel"), () => frappe.set_route("kanban-logistics"));
		}
		if (frm.doc.active) {
			frm.add_custom_button(__("Replace Card Identity"), () => cfg_replace_card(frm),
				__("Card Identity"));
		}
		if (frm.doc.current_state === "Available" && !frm.doc.active_cycle && frm.doc.active &&
			["Physical Unit Card", "Physical Batch Card"].includes(frm.doc.card_type)) {
			frm.add_custom_button(__("Consume / Trigger"), async () => {
				await frappe.call({ method: "cfg_kanban.api.scan.scan", args: {
					token: frm.doc.qr_code, action: "consume", event_token: frappe.utils.get_random(16),
					operator_session_token: localStorage.getItem("cfg_kanban_operator_session"),
				}, freeze: true });
				frappe.show_alert({ message: __("Kanban signal created"), indicator: "green" });
				frm.reload_doc();
			}, __("Kanban Actions"));
		}
	},
});

async function cfg_card_print(frm, format) {
	let reason = null;
	if (frm.doc.print_count) {
		reason = await new Promise((resolve) => frappe.prompt([
			{ fieldname: "reason", label: __("Reason for reprint"), fieldtype: "Small Text", reqd: 1 },
		], (values) => resolve(values.reason), __("Reprint Control"), __("Continue")));
	}
	await frappe.call({ method: "cfg_kanban.services.printing.record_print", args: {
		doctype: frm.doctype, name: frm.doc.name, print_format: format, reason,
	} });
	await frm.reload_doc();
	window.open(`/printview?doctype=${encodeURIComponent(frm.doctype)}&name=${encodeURIComponent(frm.doc.name)}` +
		`&format=${encodeURIComponent(format)}&no_letterhead=1`, "_blank");
}

function cfg_replace_card(frm) {
	frappe.prompt([
		{ fieldname: "new_card_number", label: __("New Card Number"), fieldtype: "Data", reqd: 1 },
		{ fieldname: "reason", label: __("Replacement Reason"), fieldtype: "Small Text", reqd: 1 },
	], async (values) => {
		const response = await frappe.call({ method: "cfg_kanban.services.printing.replace_card", args: {
			card_name: frm.doc.name, new_card_number: values.new_card_number, reason: values.reason,
		}, freeze: true });
		frappe.set_route("Form", "CFG Kanban Card", response.message.new_card);
	}, __("Replace Reusable Kanban Card"), __("Create Replacement"));
}
