frappe.ui.form.on("CFG Kanban Master", {
	setup(frm) {
		frm.set_query("bom", () => ({ filters: {
			item: frm.doc.item_code || "", is_active: 1, docstatus: 1,
		} }));
		frm.set_query("operation", "operator_field_definitions", () => ({
			query: "cfg_kanban.api.form_queries.master_operations",
			filters: { kanban_master: frm.doc.name || "" },
		}));
		frm.set_query("linked_operation", "process_task_profiles", () => ({
			query: "cfg_kanban.api.form_queries.master_operations",
			filters: { kanban_master: frm.doc.name || "" },
		}));
		frm.set_query("logistics_route", () => ({ filters: {
			route_type: "Internal Warehouse Transfer",
			source_company: frm.doc.company || "",
			destination_company: frm.doc.company || "",
			source_warehouse: frm.doc.source_warehouse || "",
			destination_warehouse: frm.doc.destination_warehouse || "",
			active: 1,
		} }));
		frm.set_query("source_warehouse", "material_flow_rules", () => ({ filters: {
			company: frm.doc.company || "", is_group: 0, disabled: 0,
		} }));
		frm.set_query("wip_bin_pool", "material_flow_rules", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			return { filters: {
				active: 1,
				company: frm.doc.company || "",
				operation: row.operation || "",
				wip_warehouse: frm.doc.wip_warehouse || "",
			} };
		});
		frm.set_query("crew_requirement_profile", "operation_profiles", () => ({
			filters: { active: 1, docstatus: 1 },
		}));
	},
	item_code(frm) {
		if (!frm.doc.item_code) return;
		frappe.db.get_value("Item", frm.doc.item_code, ["stock_uom", "default_bom", "purchase_uom"])
			.then(({ message }) => frm.set_value({
				stock_uom: message.stock_uom,
				bom: frm.doc.bom || message.default_bom,
				purchase_uom: frm.doc.control_type === "Purchase Replenishment" ?
					(message.purchase_uom || message.stock_uom) : frm.doc.purchase_uom,
			})).then(() => refresh_purchase_uom(frm));
	},
	control_type(frm) {
		refresh_purchase_uom(frm);
		frm.trigger("refresh");
	},
	async bom(frm) {
		if (frm.doc.control_type !== "Production") return;
		if (!frm.doc.bom) {
			frm.clear_table("material_flow_rules");
			frm.refresh_field("material_flow_rules");
			return;
		}
		await load_bom_material_flow(frm, {
			confirm_replace: false,
			preserve_sources: true,
			automatic: true,
		});
	},
	production_material_mode(frm) {
		set_production_material_intro(frm);
	},
	purchase_uom: refresh_purchase_uom,
	replenishment_qty: refresh_purchase_uom,
	supplier_pack_size: refresh_purchase_uom,
	minimum_order_qty: refresh_purchase_uom,
	purchase_order_multiple: refresh_purchase_uom,
	production_policy(frm) {
		const mto = frm.doc.production_policy === "Customer Make-to-Order";
		if (mto && frm.doc.demand_scope !== "Customer") frm.set_value("demand_scope", "Customer");
		frm.set_df_property("threshold_source", "read_only", mto);
		if (mto) frm.set_value("threshold_source", "ERPNext Warehouse Reorder Level");
	},
	refresh(frm) {
		frm.trigger("production_policy");
		refresh_purchase_uom(frm);
		if (!frm.is_new() && frm.doc.enable_inventory_threshold_trigger) {
			frm.add_custom_button(__("Evaluate Threshold Now"), async () => {
				const response = await frappe.call({
					method: "cfg_kanban.services.inventory_threshold.evaluate_master_now",
					args: { master_name: frm.doc.name },
					freeze: true,
					freeze_message: __("Evaluating warehouse inventory..."),
				});
				const result = response.message || {};
				await frm.reload_doc();
				const detail = result.signal
					? __("{0}. Signal {1} was selected.", [result.status, result.signal])
					: result.status;
				frappe.msgprint({ title: __("Threshold Evaluation"), message: detail, indicator: result.signal ? "orange" : "blue" });
			}, __("Inventory Control"));
		}
		if (frm.doc.control_type === "Production" && frm.doc.bom) {
			window.setTimeout(() => hide_restricted_material_flow_rows(frm), 0);
			frm.add_custom_button(__("Refresh BOM Material Flow"), () => load_bom_material_flow(frm, {
				confirm_replace: true,
				preserve_sources: true,
			}),
				__("Production Material"));
			set_production_material_intro(frm);
			if (!(frm.doc.material_flow_rules || []).length) {
				load_bom_material_flow(frm, {
					confirm_replace: false,
					preserve_sources: true,
					automatic: true,
				});
			}
		}
		if (frm.doc.production_policy === "Customer Make-to-Order") {
			frm.set_intro(__("MTO mode creates one digital cycle and Batch per Sales Order line. It does not reserve reusable cards or use reorder stock."), "blue");
		} else if (frm.doc.control_type === "Withdrawal") {
			frm.set_intro(__("Withdrawal creates a controlled ERPNext Material Issue for consumables or indirect stock. Use a Transfer Master when stock must remain in inventory at another warehouse."), "orange");
		}
	},
});

function set_production_material_intro(frm) {
	if (frm.doc.control_type !== "Production") return;
	const mode = frm.doc.production_material_mode || "Follow ERPNext BOM / Work Order";
	const messages = {
		"Transfer to WIP by Job Card": __("Each Job Card receives only BOM components whose Item Operation matches that Job Card. Prepare those materials before completing the Job Card."),
		"Transfer to WIP by Work Order": __("All required BOM materials are transferred to WIP together for the Work Order."),
		"Skip WIP Transfer": __("No WIP transfer is created. The final Manufacture entry consumes inputs directly from their configured source Warehouses."),
		"Follow ERPNext BOM / Work Order": __("ERPNext BOM and Work Order settings decide whether transfer is against the Work Order or Job Card. Kanban still applies the per-component source Warehouses."),
	};
	frm.set_intro(messages[mode], "blue");
}

async function load_bom_material_flow(frm, options = {}) {
	if (!frm.doc.bom || !frm.doc.company) {
		if (!options.automatic) frappe.msgprint(__("Select Company and BOM first."));
		return;
	}
	if (frm.__cfg_loading_material_flow) return;
	if (options.confirm_replace && (frm.doc.material_flow_rules || []).length) {
		const confirmed = await new Promise((resolve) => {
			frappe.confirm(__("Refresh the component list from the selected BOM? Matching Source Warehouse selections will be preserved."),
				() => resolve(true), () => resolve(false));
		});
		if (!confirmed) return;
	}
	const controls_by_component = {};
	if (options.preserve_sources) {
		(frm.doc.material_flow_rules || []).forEach((row) => {
			controls_by_component[material_flow_key(row)] = {
				source_warehouse: row.source_warehouse,
				wip_presentation_method: row.wip_presentation_method || "Standard ERP / Tag Flow",
				wip_bin_pool: row.wip_bin_pool,
				standard_bin_qty: row.standard_bin_qty,
			};
		});
	}
	frm.__cfg_loading_material_flow = true;
	try {
		const selected_bom = frm.doc.bom;
		const response = await frappe.call({
			method: "cfg_kanban.cfg_kanban.doctype.cfg_kanban_master.cfg_kanban_master.get_bom_material_flow_preview",
			args: { bom: selected_bom, company: frm.doc.company,
				default_source_warehouse: frm.doc.source_warehouse },
			freeze: !options.automatic,
			freeze_message: __("Loading BOM components and operations..."),
		});
		// Ignore a late response when the user selected another BOM while this request was running.
		if (frm.doc.bom !== selected_bom) return;
		const rows = response.message.rows || [];
		frm.clear_table("material_flow_rules");
		rows.forEach((value) => {
			const row = frm.add_child("material_flow_rules");
			Object.assign(row, value);
			const preserved = controls_by_component[material_flow_key(value)];
			if (preserved) Object.assign(row, preserved);
		});
		frm.refresh_field("material_flow_rules");
		hide_restricted_material_flow_rows(frm);
		const missing_operation = rows.filter((row) => !row.operation);
		const missing_warehouse = (frm.doc.material_flow_rules || [])
			.filter((row) => !row.source_warehouse);
		const warnings = [];
		if (missing_operation.length) warnings.push(__("{0} component(s) have no Item Operation.", [missing_operation.length]));
		if (missing_warehouse.length) warnings.push(__("{0} component(s) still need a Source Warehouse.", [missing_warehouse.length]));
		if (response.message.restricted_components_present) {
			warnings.push(__("Restricted BOM component(s) are hidden and will remain server-managed."));
		}
		frappe.show_alert({
			message: warnings.length ? warnings.join(" ") : __("BOM material flow synchronized"),
			indicator: warnings.length ? "orange" : "green",
		});
	} finally {
		frm.__cfg_loading_material_flow = false;
	}
}

function hide_restricted_material_flow_rows(frm) {
	if (!frappe.boot || frappe.boot.show_hidden_items) return;
	const hidden_items = frappe.boot.hidden_items || [];
	if (!hidden_items.length || !frm.fields_dict.material_flow_rules) return;
	const hidden = new Set(hidden_items);
	(frm.fields_dict.material_flow_rules.grid.grid_rows || []).forEach((grid_row) => {
		grid_row.wrapper.toggle(!hidden.has(grid_row.doc.item_code));
	});
}

function material_flow_key(row) {
	return `${row.item_code || ""}::${row.operation || ""}`;
}

async function refresh_purchase_uom(frm) {
	if (frm.doc.control_type !== "Purchase Replenishment" || !frm.doc.item_code) return;
	const response = await frappe.call({
		method: "cfg_kanban.services.uom_conversion.get_purchase_uom_preview",
		args: {
			item_code: frm.doc.item_code,
			purchase_uom: frm.doc.purchase_uom,
			stock_qty: frm.doc.replenishment_qty,
			minimum_purchase_qty: frm.doc.minimum_order_qty,
			purchase_multiple: frm.doc.purchase_order_multiple,
			supplier_pack_multiple: frm.doc.supplier_pack_size,
		},
	});
	const values = response.message || {};
	await frm.set_value({
		stock_uom: values.stock_uom,
		purchase_uom: values.purchase_uom,
		purchase_uom_conversion_factor: values.conversion_factor,
		purchase_replenishment_qty: values.purchase_qty,
	});
}

frappe.ui.form.on("CFG Kanban Operation Profile", {
	execution_mode(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, "allow_parallel", row.execution_mode === "Parallel Workstations" ? 1 : 0);
	},
});

frappe.ui.form.on("CFG Kanban Material Flow Rule", {
	wip_presentation_method(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.wip_presentation_method !== "Standard Quantity Reusable WIP Bin") {
			frappe.model.set_value(cdt, cdn, "wip_bin_pool", null);
			frappe.model.set_value(cdt, cdn, "standard_bin_qty", 0);
		}
	},
});

frappe.ui.form.on("CFG Kanban Field Definition", {
	definition_scope(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.definition_scope === "Operation") frappe.model.set_value(cdt, cdn, "process_task_key", null);
		if (row.definition_scope === "Process Task") frappe.model.set_value(cdt, cdn, "operation", null);
	},
});
