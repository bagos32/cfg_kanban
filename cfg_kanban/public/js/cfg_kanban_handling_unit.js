frappe.ui.form.on("CFG Kanban Handling Unit", {
	setup(frm) {
		frm._cfg_cycle_operations = [];
		frm.set_query("tag_family", () => ({ filters: { active: 1 } }));
		frm.set_query("parent_handling_unit", () => ({ filters: {
			tag_kind: "Main Stock Tag",
			identity_state: "Active",
			tag_family: frm.doc.tag_family || "",
		} }));
		frm.set_query("current_warehouse", () => ({ filters: {
			company: frm.doc.inventory_company || "", is_group: 0,
		} }));
		frm.set_query("current_operation", () => ({ filters: {
			name: ["in", frm._cfg_cycle_operations.length ? frm._cfg_cycle_operations : ["__none__"]],
		} }));
	},
	async kanban_cycle(frm) {
		if (!frm.doc.kanban_cycle) return;
		const [{ message: cycle }, { message: operations }] = await Promise.all([
			frappe.db.get_value("CFG Kanban Cycle", frm.doc.kanban_cycle,
				["kanban_card", "company", "item_code", "stock_uom", "batch_no", "work_order",
					"destination_warehouse"]),
			frappe.call({ method: "cfg_kanban.api.form_queries.cycle_operations",
				args: { kanban_cycle: frm.doc.kanban_cycle } }),
		]);
		frm._cfg_cycle_operations = (operations || []).map((row) => row.operation);
		await frm.set_value({
			kanban_card: cycle.kanban_card, item_code: cycle.item_code, stock_uom: cycle.stock_uom,
			batch_no: cycle.batch_no, work_order: cycle.work_order,
			inventory_company: cycle.company,
			current_warehouse: frm.doc.current_warehouse || cycle.destination_warehouse,
			current_operation: frm.doc.current_operation || frm._cfg_cycle_operations[0] || null,
		});
	},
	async handling_unit_id(frm) {
		if (!frm.is_new() || frm._cfg_resolving_tag || !frm.doc.handling_unit_id) return;
		frm._cfg_resolving_tag = true;
		try {
			await frm.set_value({
				tag_family: null,
				tag_range_registry: null,
				parent_handling_unit: null,
				root_handling_unit: null,
				child_index: 0,
			});
			const response = await frappe.call({
				method: "cfg_kanban.api.form_queries.preprinted_tag_context",
				args: { scan_value: frm.doc.handling_unit_id },
			});
			const identity = response.message || {};
			if (!identity.found) {
				frappe.show_alert({ message: __("Code is not covered by an exact Tag Family or active Tag Range Registry. Unregistered codes remain available only for reusable containers."), indicator: "orange" }, 8);
				return;
			}
			if (identity.identity_type === "Handling Unit") {
				frappe.msgprint({
					title: __("Tag Already Active"),
					message: __("{0} is already assigned to Handling Unit {1}.",
						[identity.visible_code, identity.name]),
					indicator: "red",
				});
				return;
			}
			const is_registered = identity.identity_type === "Registered Tag Identity";
			const is_range_candidate = identity.identity_type === "Tag Range Candidate";
			if (!is_registered && !is_range_candidate) {
				frappe.msgprint({ title: __("Wrong Scan Type"),
					message: __("{0} is registered as {1}, not a Stock Tag.",
						[identity.visible_code, identity.identity_type]), indicator: "red" });
				return;
			}
			if (is_registered && identity.state !== "Unused") {
				frappe.msgprint({ title: __("Tag Not Available"),
					message: __("Preprinted tag {0} is {1}.", [identity.visible_code, identity.state]),
					indicator: "red" });
				return;
			}
			await frm.set_value({
				handling_unit_id: identity.visible_code,
				tag_family: is_registered ? identity.tag_family : null,
				tag_range_registry: identity.range_registry || null,
				tag_kind: identity.tag_role === "Main" ? "Main Stock Tag" : "Child Stock Tag",
				child_index: identity.child_index || 0,
				inventory_company: frm.doc.inventory_company || identity.issued_company,
			});
			if (is_range_candidate) {
				frappe.show_alert({
					message: __("Tag is covered by Range Registry {0}. Its exact Tag Family will be created when this Handling Unit is saved.", [identity.range_registry]),
					indicator: "blue",
				}, 10);
			} else {
				frappe.show_alert({ message: __("Registered preprinted tag recognized"), indicator: "green" });
			}
			if (identity.tag_role === "Child") {
				frappe.show_alert({ message: __("Select the active main Parent Handling Unit before saving this child split."), indicator: "blue" }, 8);
			}
		} finally {
			frm._cfg_resolving_tag = false;
		}
	},
	refresh(frm) {
		if (frm.doc.kanban_cycle) frm.trigger("kanban_cycle");
		if (frm.is_new()) return;
		if (frm.doc.tag_kind !== "Reusable Container" && !frm.doc.current_warehouse) {
			frm.add_custom_button(__("Assign Initial Warehouse"), () => {
				assign_initial_warehouse(frm);
			}, __("Kanban Actions"));
		}
		frm.add_custom_button(__("Print Thermal Tag"), () => audited_print(
			frm, "CFG Kanban Handling Unit Tag"), __("Kanban Actions"));
		frm.add_custom_button(__("Explore Material Genealogy"), () => {
			frappe.set_route("material-genealogy", frm.doc.handling_unit_id);
		}, __("Kanban Actions"));
		if (frm.doc.tag_kind === "Reusable Container") {
			frm.add_custom_button(__("Manage Container Contents"), () => {
				frappe.set_route("kanban-logistics", frm.doc.handling_unit_id);
			}, __("Kanban Actions"));
			frm.add_custom_button(__("Container Content History"), () => {
				frappe.set_route("List", "CFG Kanban Container Content", {
					container_handling_unit: frm.doc.name,
				});
			}, __("Kanban Actions"));
		}
		frm.add_custom_button(__("Print Genealogy Report"), () => {
			const url = `/printview?doctype=${encodeURIComponent(frm.doctype)}&name=${encodeURIComponent(frm.doc.name)}` +
				`&format=${encodeURIComponent("CFG Kanban Genealogy Report")}&no_letterhead=1`;
			window.open(url, "_blank");
		}, __("Kanban Actions"));
		if (frm.doc.serial_count) {
			frm.add_custom_button(__("Exact Serial Membership"), () => {
				frappe.set_route("List", "CFG Kanban Handling Unit Serial", {
					handling_unit: frm.doc.name,
				});
			}, __("Kanban Actions"));
			if (frm.doc.tag_kind === "Main Stock Tag" && frm.doc.identity_state === "Active") {
				frm.add_custom_button(__("Split Exact Serials to Child Tag"), () => {
					serial_child_split(frm);
				}, __("Kanban Actions"));
			}
			if (frm.doc.tag_kind === "Child Stock Tag" && frm.doc.identity_state === "Active" &&
				frm.doc.parent_handling_unit) {
				frm.add_custom_button(__("Merge Untouched Child Back to Parent"), () => {
					merge_serial_child(frm);
				}, __("Kanban Actions"));
			}
		}
		if (!["Received", "Void", "Replaced"].includes(frm.doc.state)) {
			frm.add_custom_button(__("Replace Tag"), () => replace_tag(frm), __("Kanban Actions"));
		}
	},
});

async function serial_child_split(frm) {
	const response = await frappe.call({
		method: "cfg_kanban.services.handling_unit_split.get_serial_split_plan",
		args: { parent_handling_unit: frm.doc.name },
	});
	const plan = response.message || {};
	if (plan.blocked_reason) {
		frappe.msgprint({
			title: __("Serial Split Not Available"),
			message: plan.blocked_reason,
			indicator: "orange",
		});
		return;
	}
	const child_codes = (plan.unused_child_tags || []).map((row) => row.visible_code);
	if (!child_codes.length) {
		frappe.msgprint(__("No unused detachable child tag remains in this Tag Family."));
		return;
	}
	const e = frappe.utils.escape_html;
	const dialog = new frappe.ui.Dialog({
		title: __("Split Exact Serials to Child Tag"),
		size: "large",
		fields: [
			{ fieldname: "summary", fieldtype: "HTML",
				options: `<div class="alert alert-info"><strong>${e(plan.parent_code)}</strong> · ${e(plan.item_code)} · ${e(plan.current_qty)} ${e(plan.stock_uom)}<br>
					<small>${__("This changes physical tag membership only. ERPNext Item, Batch, Warehouse, and stock quantity do not change.")}</small></div>` },
			{ fieldname: "child_scan_value", label: __("Unused Detachable Child Tag"),
				fieldtype: "Data", reqd: 1,
				description: __("Scan one of the unused child tags: {0}", [child_codes.join(", ")]) },
			{ fieldname: "serial_numbers", label: __("Serial Numbers Moving to Child"),
				fieldtype: "Small Text", reqd: 1,
				description: __("Scan or enter one exact ERPNext Serial No per line. Available on parent: {0}", [(plan.serial_numbers || []).join(", ")]) },
			{ fieldname: "reason", label: __("Split Reason"), fieldtype: "Small Text", reqd: 1 },
		],
		primary_action_label: __("Create Controlled Child Tag"),
		primary_action: async (values) => {
			const result = await frappe.call({
				method: "cfg_kanban.services.handling_unit_split.split_serials_to_child",
				args: {
					parent_handling_unit: frm.doc.name,
					child_scan_value: values.child_scan_value,
					serial_numbers: values.serial_numbers,
					reason: values.reason,
				},
				freeze: true,
				freeze_message: __("Splitting quantity and exact serial membership..."),
			});
			dialog.hide();
			frappe.show_alert({
				message: __("Child tag {0} activated with {1} serials", [
					result.message.child.visible_code,
					(result.message.child.serial_numbers || []).length,
				]),
				indicator: "green",
			}, 8);
			frappe.set_route("Form", "CFG Kanban Handling Unit", result.message.child.name);
		},
	});
	dialog.show();
	dialog.get_field("child_scan_value").$input.trigger("focus");
}

function merge_serial_child(frm) {
	frappe.prompt([
		{ fieldname: "reason", label: __("Merge Reason"), fieldtype: "Small Text", reqd: 1,
			description: __("Only an untouched, unreserved child in the same Company and Warehouse can be merged.") },
	], async (values) => {
		const response = await frappe.call({
			method: "cfg_kanban.services.handling_unit_split.merge_serial_child_to_parent",
			args: { child_handling_unit: frm.doc.name, reason: values.reason },
			freeze: true,
			freeze_message: __("Returning quantity and exact serials to the parent tag..."),
		});
		frappe.show_alert({
			message: __("Serials returned to parent tag {0}", [response.message.parent.visible_code]),
			indicator: "green",
		}, 8);
		frappe.set_route("Form", "CFG Kanban Handling Unit", response.message.parent.name);
	}, __("Merge Child Tag Back to Parent"), __("Confirm Controlled Merge"));
}

function assign_initial_warehouse(frm) {
	frappe.prompt([
		{ fieldname: "warehouse", label: __("Current Warehouse"), fieldtype: "Link",
			options: "Warehouse", reqd: 1,
			get_query: () => ({ filters: { company: frm.doc.inventory_company || "", is_group: 0 } }) },
		{ fieldname: "reason", label: __("Assignment Reason"), fieldtype: "Small Text", reqd: 1 },
	], async (values) => {
		await frappe.call({
			method: "cfg_kanban.api.logistics.assign_initial_warehouse",
			args: { unit_name: frm.doc.name, warehouse: values.warehouse, reason: values.reason },
			freeze: true,
			freeze_message: __("Validating ERPNext stock and assigning the initial warehouse..."),
		});
		await frm.reload_doc();
	}, __("Assign Initial Warehouse"), __("Assign"));
}

async function audited_print(frm, format) {
	const reason = frm.doc.print_count ? await ask_reason(__("Reason for reprint")) : null;
	if (frm.doc.print_count && !reason) return;
	await frappe.call({ method: "cfg_kanban.services.printing.record_print",
		args: { doctype: frm.doctype, name: frm.doc.name, print_format: format, reason } });
	await frm.reload_doc();
	const url = `/printview?doctype=${encodeURIComponent(frm.doctype)}&name=${encodeURIComponent(frm.doc.name)}` +
		`&format=${encodeURIComponent(format)}&no_letterhead=1`;
	window.open(url, "_blank");
}

function ask_reason(label) {
	return new Promise((resolve) => frappe.prompt([
		{ fieldname: "reason", label, fieldtype: "Small Text", reqd: 1 },
	], (values) => resolve(values.reason), __("Reprint Control"), __("Continue")));
}

function replace_tag(frm) {
	frappe.prompt([
		{ fieldname: "new_id", label: __("New Handling Unit ID"), fieldtype: "Data", reqd: 1 },
		{ fieldname: "reason", label: __("Replacement Reason"), fieldtype: "Small Text", reqd: 1 },
	], async (values) => {
		const response = await frappe.call({ method: "cfg_kanban.services.printing.replace_handling_unit",
			args: { unit_name: frm.doc.name, new_handling_unit_id: values.new_id, reason: values.reason }, freeze: true });
		frappe.set_route("Form", "CFG Kanban Handling Unit", response.message.new_unit);
	}, __("Replace Handling Unit Tag"), __("Create Replacement"));
}
