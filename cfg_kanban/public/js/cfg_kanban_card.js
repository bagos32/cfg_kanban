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
			["item_code", "stock_uom", "replenishment_qty", "source_warehouse", "destination_warehouse"])
			.then(({ message }) => frm.set_value({
				item_code: message.item_code,
				stock_uom: message.stock_uom,
				kanban_qty: frm.doc.kanban_qty || message.replenishment_qty,
				source_warehouse: message.source_warehouse,
				destination_warehouse: message.destination_warehouse,
				current_warehouse: frm.doc.current_warehouse || message.destination_warehouse,
			}));
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
		const required = ["Process Kanban", "Station Kanban"].includes(frm.doc.card_type);
		frm.set_df_property("operation", "reqd", required);
		if (frm.doc.card_type !== "Station Kanban" && frm.doc.workstation) {
			frm.set_value("workstation", null);
		}
	},
	refresh(frm) {
		frm.trigger("card_type");
		if (frm.is_new()) return;
		frm.add_custom_button(__("Open Operator Console"), () => {
			frappe.set_route("kanban-operator");
		});
		frm.add_custom_button(__("Print Standard Card"), () => cfg_card_print(frm,
			"CFG Kanban Standard Card"), __("Print Kanban"));
		frm.add_custom_button(__("Print Operational Card"), () => cfg_card_print(frm,
			"CFG Kanban Operational Card"), __("Print Kanban"));
		if (frm.doc.active) {
			frm.add_custom_button(__("Replace Card"), () => cfg_replace_card(frm), __("Print Kanban"));
		}
		if (frm.doc.current_state === "Available" && !frm.doc.active_cycle && frm.doc.active &&
			!["Process Kanban", "Station Kanban"].includes(frm.doc.card_type)) {
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
