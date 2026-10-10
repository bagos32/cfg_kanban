frappe.pages["kanban-logistics"].on_page_load = function (wrapper) {
	const TERMINAL_STATES = new Set(["Received", "Billing Pending", "Partially Billed", "Billed", "Closed", "Cancelled"]);
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Kanban Logistics"), single_column: true });
	const session_key = "cfg_kanban_operator_session";
	const last_manifest_key = "cfg_kanban_last_manifest";
	const last_reconciliation_key = "cfg_kanban_last_reconciliation";
	const state = { token: localStorage.getItem(session_key), operator: null, routes: [],
		manifests: [], recent_manifests: [], internal_transfers: [], manifest: null,
		delivery_sessions: [], return_cases: [], vehicle_warehouses: [], open_reconciliations: [],
		recent_reconciliations: [], can_reconcile: false, reconciliation: null,
		lookup: null, scan_mode: "lookup" };
	const $sticky = $("<div class='cfg-logistics-sticky'></div>").appendTo(page.main);
	const $scanner = $(`<div class="frappe-card cfg-logistics-scanner">
		<div class="cfg-logistics-scanner-head"><div><strong>${__("Logistics Scanner")}</strong>
			<small>${__("Scan operator, Manifest ID, or preprinted Stock Tag")}</small></div>
			<span class="indicator-pill orange scanner-state">${__("Operator required")}</span></div>
		<div class="cfg-logistics-scan-row">
			<input class="form-control logistics-scan-input" autocomplete="off" spellcheck="false"
				placeholder="${__("Scan Kanban Card, Stock Tag, or KMF number")}">
			<button class="btn btn-primary camera-scan">${__("Scan with Camera")}</button>
		</div><div class="scanner-message text-muted"><small>${__("Ready")}</small></div>
	</div>`).appendTo($sticky);
	const $identity = $("<div></div>").appendTo($sticky);
	const $lookup = $("<div class='cfg-logistics-lookup mt-3'></div>").appendTo(page.main);
	const $active = $("<div class='cfg-logistics-active mt-3'></div>").appendTo(page.main);
	const $reconciliation = $("<div class='cfg-logistics-reconciliation mt-3'></div>").appendTo(page.main);
	const $actions = $(`<div class="cfg-logistics-toolbar mt-3 mb-3">
		<button class="btn btn-primary new-manifest">${__("New Dispatch Manifest")}</button>
		<button class="btn btn-warning route-reconciliation">${__("Route Stock Count")}</button>
		<button class="btn btn-default refresh-logistics">${__("Refresh")}</button>
		<button class="btn btn-default clear-current">${__("Clear Screen")}</button>
		<button class="btn btn-primary switch-operator cfg-change-operator">${__("Scan / Change Operator")}</button>
		<button class="btn btn-default production-panel">${__("Production Panel")}</button>
		<button class="btn btn-default service-panel">${__("Service Panel")}</button>
	</div>`).appendTo(page.main);
	const $list = $("<div class='cfg-logistics-list'></div>").appendTo(page.main);

	$scanner.find(".logistics-scan-input").on("keydown", (event) => {
		if (event.key === "Enter") { event.preventDefault(); process_scan(); }
	});
	$scanner.find(".camera-scan").on("click", camera_scan);
	$actions.find(".new-manifest").on("click", new_manifest_dialog);
	$actions.find(".route-reconciliation").on("click", reconciliation_dialog);
	$actions.find(".refresh-logistics").on("click", load);
	$actions.find(".clear-current").on("click", clear_manifest_view);
	$actions.find(".switch-operator").on("click", identify_operator);
	$actions.find(".production-panel").on("click", () => frappe.set_route("kanban-operator"));
	$actions.find(".service-panel").on("click", () => frappe.set_route("kanban-tasks"));
	page.set_primary_action(__("Refresh"), load, "refresh");
	page.add_inner_button(__("Identify Operator"), identify_operator);

	async function load() {
		sync_session_from_storage();
		if (!state.token) return show_login();
		const requested_token = state.token;
		try {
			const response = await frappe.call({ method: "cfg_kanban.api.logistics.get_logistics_console",
				args: { operator_session_token: state.token } });
			state.operator = response.message.operator;
			state.routes = response.message.routes || [];
			state.manifests = response.message.manifests || [];
			state.recent_manifests = response.message.recent_manifests || [];
			state.internal_transfers = response.message.internal_transfers || [];
			state.delivery_sessions = response.message.delivery_sessions || [];
			state.return_cases = response.message.return_cases || [];
			state.vehicle_warehouses = response.message.vehicle_warehouses || [];
			state.open_reconciliations = response.message.open_reconciliations || [];
			state.recent_reconciliations = response.message.recent_reconciliations || [];
			state.can_reconcile = Boolean(response.message.can_reconcile);
			state.scan_mode = "lookup";
			render_identity();
			const last_manifest = state.manifest?.name || state.manifest || localStorage.getItem(last_manifest_key);
			if (last_manifest) await open_manifest(last_manifest, { quiet: true, restore: true });
			else render_active();
			const last_reconciliation = localStorage.getItem(last_reconciliation_key);
			if (last_reconciliation) await open_reconciliation(last_reconciliation, { quiet: true });
			else render_reconciliation();
			render_lookup();
			render_list();
			focus_scanner();
		} catch (error) {
			const latest_token = localStorage.getItem(session_key);
			if (latest_token && latest_token !== requested_token) return load();
			clear_session(requested_token);
			show_login(__("Operator session expired. Scan the operator credential again."));
		}
	}

	function sync_session_from_storage() {
		const stored_token = localStorage.getItem(session_key);
		if (stored_token === state.token) return false;
		state.token = stored_token;
		state.operator = null;
		state.routes = [];
		state.manifests = [];
		state.recent_manifests = [];
		state.internal_transfers = [];
		state.delivery_sessions = [];
		state.return_cases = [];
		state.vehicle_warehouses = [];
		state.open_reconciliations = [];
		state.recent_reconciliations = [];
		state.can_reconcile = false;
		state.reconciliation = null;
		state.manifest = null;
		state.lookup = null;
		state.scan_mode = "lookup";
		return true;
	}

	function show_login(message) {
		state.operator = null; state.manifest = null;
		$identity.html(`<div class="alert alert-warning cfg-logistics-identity"><div><small>${__("Active operator")}</small>
			<strong>${__("Not identified")}</strong></div><button class="btn btn-primary login-operator">${__("Scan / Enter Operator")}</button></div>`);
		$identity.find(".login-operator").on("click", identify_operator);
		$active.html(`<div class="frappe-card text-center p-5"><h3>${__("Operator identification required")}</h3>
			<p class="text-muted">${message || __("Identify the operator before preparing or receiving a Manifest.")}</p></div>`);
		$lookup.empty(); $reconciliation.empty(); $list.empty(); update_scanner_state(); focus_scanner();
	}

	function render_identity() {
		const e = frappe.utils.escape_html;
		$identity.html(`<div class="alert alert-info cfg-logistics-identity"><div><small>${__("Active operator")}</small>
			<strong>${e(state.operator.employee_name || state.operator.employee)}</strong>
			<span>${e(state.operator.kanban_role || "")}</span></div>
			<div><button class="btn btn-primary switch cfg-change-operator">${__("Scan / Change Operator")}</button>
			<button class="btn btn-default end">${__("End Session")}</button></div></div>`);
		$identity.find(".switch").on("click", identify_operator);
		$identity.find(".end").on("click", () => frappe.confirm(__("End operator session?"), end_session));
		update_scanner_state();
	}

	function render_active() {
		if (!state.manifest) {
			$active.html(`<div class="frappe-card cfg-logistics-empty"><h3>${__("No Manifest selected")}</h3>
				<p>${__("Scan a Stock Tag for status lookup, create a Manifest, or select one below.")}</p></div>`);
			update_scanner_state();
			return;
		}
		const m = state.manifest; const e = frappe.utils.escape_html;
		const receipt_mode = ["Dispatched", "Awaiting Receipt", "Receipt Document Pending"].includes(m.state) || m.receipt_retry_available;
		const physical_lines = (m.lines || []).filter((row) => row.line_kind !== "ERP Stock without Physical Tag");
		const receipt_scanned = physical_lines.filter((row) => row.receipt_scanned).length;
		const tag_policy = m.transfer_tag_policy && m.transfer_tag_policy !== "Manifest Scan" ?
			`<div class="alert alert-secondary"><strong>${__("Warehouse Transfer Tags")}:</strong> ${e(m.transfer_tag_policy)}</div>` : "";
		const non_stock_notice = m.non_stock_operational_tracking ?
			`<div class="alert alert-info"><strong>${__("Kanban operational inventory")}</strong> · ${__("This ERPNext Item does not maintain stock. Physical tags and the Handling Unit ledger control quantity and location; no Stock Entry will be created.")}</div>` : "";
		let mode_notice = `<div class="alert alert-info"><strong>${__("View-only lookup")}</strong> · ${__("Scanning a Stock Tag will show its status and will not change this Manifest.")}</div>`;
		if (state.scan_mode === "dispatch") mode_notice = `<div class="alert alert-warning"><strong>${__("DISPATCH SCANNING ARMED")}</strong> · ${e(m.name)} · ${__("Scanned tags will be added to this Manifest.")}</div>`;
		if (state.scan_mode === "receipt") mode_notice = `<div class="alert alert-success"><strong>${__("RECEIPT SCANNING ARMED")}</strong> · ${e(m.name)} · ${__("Only tags listed on this Manifest will be accepted.")}</div>`;
		const rendered_container_actions = new Set();
		const lines = (m.lines || []).map((row) => {
			const show_container_remove = row.container_handling_unit &&
				!rendered_container_actions.has(row.container_handling_unit);
			if (show_container_remove) rendered_container_actions.add(row.container_handling_unit);
			return `<div class="cfg-logistics-line">
			<div><strong>${e(row.visible_code || row.line_kind || __("ERP Stock"))}</strong><small>${e(row.item_code)} · ${e(row.batch_no || __("No Batch"))}</small>
				${row.container_visible_code ? `<small>${__("Inside container")}: <strong>${e(row.container_visible_code)}</strong></small>` : ""}</div>
			<div><strong>${format_number(row.dispatch_qty)} ${e(row.stock_uom)}</strong>
				<small>${row.receipt_scanned ? __("Receipt scan confirmed") : e(row.state)}</small></div>
				${m.state === "Draft" && state.scan_mode === "dispatch" && row.handling_unit && (!row.container_handling_unit || show_container_remove) ? `<button class="btn btn-xs btn-danger remove-line" data-unit="${e(row.handling_unit)}" data-line="${e(row.name)}">${row.container_visible_code ? __("Remove Container") : __("Remove")}</button>` : ""}
				${m.state === "Draft" && !row.handling_unit ? `<button class="btn btn-xs btn-danger remove-line" data-line="${e(row.name)}">${__("Remove")}</button>` : ""}
			</div>`;
		}).join("");
		$active.html(`<div class="frappe-card cfg-logistics-manifest">
			<div class="cfg-logistics-manifest-head"><div><small>${__("Viewed Manifest")}</small><h2>${e(m.name)}</h2>
				<strong>${e(m.manifest_type || __("Movement Manifest"))} · ${e(m.logistics_route)}</strong></div><span class="indicator-pill ${state_colour(m.state)}">${e(m.state)}</span></div>
			<div class="cfg-logistics-route"><div><small>${__("FROM")}</small><strong>${e(m.source_company)}</strong><span>${e(m.source_warehouse)}</span></div>
				<div class="cfg-logistics-arrow">→</div><div><small>${__("TO")}</small><strong>${e(m.destination_company)}</strong><span>${e(m.destination_warehouse)}</span></div></div>
			${mode_notice}${tag_policy}${non_stock_notice}
			${receipt_mode ? `<div class="cfg-logistics-receipt-progress"><strong>${__("Receipt scans: {0} of {1}", [receipt_scanned, physical_lines.length])}</strong><span>${m.can_receive ? (physical_lines.length ? __("Arm Receipt Scanning and scan every physical tag.") : __("This movement uses ERP stock without physical tags; confirm the physical receipt.")) : __("Switch to an operator assigned to the route's Receipt Responsibility.")}</span></div>` : ""}
			<div class="cfg-logistics-lines">${lines || `<div class="text-muted p-3">${__("No tags scanned")}</div>`}</div>
			<div class="cfg-logistics-docs"><span>${e(m.dispatch_document_type || __("Dispatch document"))}: <strong>${e(m.dispatch_stock_entry || m.dispatch_delivery_note || __("Not created"))}</strong></span>
				${m.receipt_document_type ? `<span>${e(m.receipt_document_type)}: <strong>${e(m.receipt_stock_entry || m.receipt_purchase_receipt || __("Not created"))}</strong></span>` : ""}</div>
			<div class="cfg-logistics-actions">${manifest_actions(m)}</div>
		</div>`);
		$active.find(".remove-line").on("click", function () {
			remove_line($(this).data("line"), $(this).data("unit"));
		});
		$active.find(".prepare-manifest").on("click", prepare_manifest);
		$active.find(".use-untagged-stock").on("click", use_untagged_stock);
		$active.find(".confirm-dispatch").on("click", confirm_dispatch);
		$active.find(".confirm-receipt").on("click", confirm_receipt);
		$active.find(".cancel-manifest").on("click", cancel_manifest);
		$active.find(".open-dn").on("click", () => frappe.set_route("Form", "Delivery Note", m.dispatch_delivery_note));
		$active.find(".open-pr").on("click", () => frappe.set_route("Form", "Purchase Receipt", m.receipt_purchase_receipt));
		$active.find(".open-dispatch-se").on("click", () => frappe.set_route("Form", "Stock Entry", m.dispatch_stock_entry));
		$active.find(".open-receipt-se").on("click", () => frappe.set_route("Form", "Stock Entry", m.receipt_stock_entry));
		$active.find(".arm-dispatch").on("click", () => set_scan_mode("dispatch"));
		$active.find(".arm-receipt").on("click", () => set_scan_mode("receipt"));
		$active.find(".stop-scanning").on("click", () => set_scan_mode("lookup"));
		$active.find(".clear-manifest").on("click", clear_manifest_view);
		update_scanner_state();
	}

	function manifest_actions(m) {
		const buttons = [];
		const receipt_state = ["Dispatched", "Awaiting Receipt", "Receipt Document Pending"].includes(m.state) || m.receipt_retry_available;
		const all_received = Boolean(m.lines.length && m.lines.every((row) =>
			row.line_kind === "ERP Stock without Physical Tag" || row.receipt_scanned));
		if (m.can_dispatch && m.state === "Draft" && m.can_scan_dispatch_tags !== false) {
			buttons.push(state.scan_mode === "dispatch" ?
				`<button class="btn btn-warning stop-scanning">${__("Stop Dispatch Scanning")}</button>` :
				`<button class="btn btn-primary arm-dispatch">${__("Start Dispatch Scanning")}</button>`);
		}
		if (m.can_dispatch && m.can_use_untagged_stock) {
			buttons.push(`<button class="btn btn-default use-untagged-stock">${__("Use ERP Stock Without Tags")}</button>`);
		}
		if (receipt_state && m.can_receive) {
			buttons.push(state.scan_mode === "receipt" ?
				`<button class="btn btn-warning stop-scanning">${__("Stop Receipt Scanning")}</button>` :
				`<button class="btn btn-primary arm-receipt">${__("Start Receipt Scanning")}</button>`);
		}
		if (m.can_dispatch && m.state === "Draft" && m.lines.length) {
			buttons.push(state.scan_mode === "lookup" ?
				`<button class="btn btn-primary prepare-manifest">${__("Prepare and Reserve")}</button>` :
				`<button class="btn btn-default" disabled>${__("Stop scanning before preparation")}</button>`);
		}
		if (m.can_dispatch && (m.state === "Prepared" || m.dispatch_retry_available)) {
			buttons.push(`<button class="btn btn-success confirm-dispatch">${m.dispatch_retry_available ? __("Retry Dispatch") : __("Confirm Dispatch")}</button>`);
		}
		if (receipt_state && m.can_receive && all_received) {
			buttons.push(state.scan_mode === "lookup" ?
				`<button class="btn btn-success confirm-receipt">${m.receipt_retry_available ? __("Retry Receipt") : __("Confirm Receipt")}</button>` :
				`<button class="btn btn-default" disabled>${__("Stop scanning before receipt confirmation")}</button>`);
		}
		else if (receipt_state && m.can_receive) buttons.push(`<button class="btn btn-default" disabled>${__("Scan all tags to confirm receipt")}</button>`);
		else if (receipt_state) buttons.push(`<button class="btn btn-default" disabled>${__("Receipt responsibility required")}</button>`);
		if (["Draft", "Prepared"].includes(m.state) && state.operator.can_override) {
			buttons.push(state.scan_mode === "lookup" ?
				`<button class="btn btn-danger cancel-manifest">${__("Cancel Manifest")}</button>` :
				`<button class="btn btn-default" disabled>${__("Stop scanning before cancellation")}</button>`);
		}
		if (m.dispatch_delivery_note) buttons.push(`<button class="btn btn-default open-dn">${__("Open Delivery Note")}</button>`);
		if (m.receipt_purchase_receipt) buttons.push(`<button class="btn btn-default open-pr">${__("Open Purchase Receipt")}</button>`);
		if (m.dispatch_stock_entry) buttons.push(`<button class="btn btn-default open-dispatch-se">${__("Open Dispatch Stock Entry")}</button>`);
		if (m.receipt_stock_entry) buttons.push(`<button class="btn btn-default open-receipt-se">${__("Open Receipt Stock Entry")}</button>`);
		buttons.push(`<button class="btn btn-default clear-manifest">${TERMINAL_STATES.has(m.state) ? __("Done — Clear Screen") : __("Clear Viewed Manifest")}</button>`);
		return buttons.join("");
	}

	function render_reconciliation() {
		if (!state.reconciliation) {
			$reconciliation.empty();
			return;
		}
		const r = state.reconciliation; const e = frappe.utils.escape_html;
		const variance = Number(r.variance_line_count || 0);
		const lines = (r.lines || []).map((row) => `<tr class="${Math.abs(Number(row.variance_qty || 0)) > 0.000001 ? "text-danger" : ""}">
			<td><strong>${e(row.item_code)}</strong><small>${e(row.batch_no || __("No Batch"))}</small></td>
			<td>${format_number(row.opening_qty)}</td><td>${format_number(row.movement_qty)}</td>
			<td>${format_number(row.expected_closing_qty)}</td><td>${format_number(row.tagged_count_qty)}</td>
			<td>${format_number(row.loose_count_qty)}</td><td><strong>${format_number(row.counted_qty)}</strong></td>
			<td><strong>${format_number(row.variance_qty)}</strong></td></tr>`).join("");
		const scans = (r.scans || []).map((row) => `<div class="cfg-logistics-line">
			<div><strong>${e(row.visible_code)}</strong><small>${e(row.item_code)} · ${e(row.batch_no || __("No Batch"))}
			${row.container_visible_code ? ` · ${__("Container")}: ${e(row.container_visible_code)}` : ""}</small></div>
			<div><strong>${format_number(row.qty)} ${e(row.stock_uom)}</strong></div>
			${r.can_count ? `<button class="btn btn-xs btn-danger remove-reconciliation-scan" data-unit="${e(row.handling_unit)}">${__("Remove")}</button>` : ""}
		</div>`).join("");
		const counting = state.scan_mode === "reconciliation";
		const actions = [];
		if (r.can_count) actions.push(counting ?
			`<button class="btn btn-warning stop-reconciliation-scan">${__("Stop Count Scanning")}</button>` :
			`<button class="btn btn-primary arm-reconciliation-scan">${__("Start Tag Count Scanning")}</button>`);
		if (r.can_count && !counting) {
			actions.push(`<button class="btn btn-default loose-counts">${__("Enter Loose / Untagged Count")}</button>`);
			actions.push(`<button class="btn btn-primary evaluate-reconciliation">${__("Evaluate against ERPNext")}</button>`);
		}
		if (r.can_close && !counting) actions.push(`<button class="btn btn-success close-reconciliation">${__("Close Balanced Route")}</button>`);
		if (r.can_override && r.can_count && !counting) actions.push(`<button class="btn btn-danger cancel-reconciliation">${__("Cancel Count")}</button>`);
		actions.push(`<button class="btn btn-default clear-reconciliation">${__("Clear Viewed Count")}</button>`);
		$reconciliation.html(`<div class="frappe-card cfg-reconciliation-card">
			<div class="cfg-logistics-manifest-head"><div><small>${__("End-of-route stock reconciliation")}</small>
			<h2>${e(r.name)}</h2><strong>${e(r.vehicle_reference)} · ${e(r.vehicle_warehouse)}</strong></div>
			<span class="indicator-pill ${reconciliation_colour(r.state)}">${e(r.state)}</span></div>
			<div class="cfg-reconciliation-totals"><div><small>${__("ERP Item / Batch lines")}</small><strong>${format_number(r.expected_line_count)}</strong></div>
			<div><small>${__("Physically counted lines")}</small><strong>${format_number(r.counted_line_count)}</strong></div>
			<div><small>${__("Variance lines")}</small><strong class="${variance ? "text-danger" : "text-success"}">${format_number(variance)}</strong></div></div>
			${counting ? `<div class="alert alert-warning"><strong>${__("ROUTE COUNT SCANNING ARMED")}</strong> · ${__("Every Stock Tag scan is added to this physical count.")}</div>` : ""}
			<div class="table-responsive"><table class="table table-bordered"><thead><tr><th>${__("Item / Batch")}</th><th>${__("Opening")}</th><th>${__("ERP movement")}</th><th>${__("Expected")}</th><th>${__("Tags")}</th><th>${__("Loose")}</th><th>${__("Counted")}</th><th>${__("Variance")}</th></tr></thead>
			<tbody>${lines || `<tr><td colspan="8" class="text-muted">${__("No ERP balance or physical count lines yet")}</td></tr>`}</tbody></table></div>
			<h5>${__("Exact scanned tags")}</h5><div class="cfg-logistics-lines">${scans || `<div class="text-muted p-3">${__("No Stock Tags counted yet")}</div>`}</div>
			${r.variance_exception ? `<div class="alert alert-danger"><strong>${__("Variance Exception")}: ${e(r.variance_exception)}</strong><br>${__("Do not alter Kanban history. Recount or post an authorized ERP stock correction, then evaluate again.")}</div>` : ""}
			<div class="cfg-logistics-actions">${actions.join("")}</div>
		</div>`);
		$reconciliation.find(".arm-reconciliation-scan").on("click", () => {
			state.scan_mode = "reconciliation"; render_reconciliation(); update_scanner_state(); focus_scanner();
		});
		$reconciliation.find(".stop-reconciliation-scan").on("click", () => {
			state.scan_mode = "lookup"; render_reconciliation(); update_scanner_state(); focus_scanner();
		});
		$reconciliation.find(".remove-reconciliation-scan").on("click", function () {
			remove_reconciliation_scan($(this).data("unit"));
		});
		$reconciliation.find(".loose-counts").on("click", loose_count_dialog);
		$reconciliation.find(".evaluate-reconciliation").on("click", evaluate_reconciliation);
		$reconciliation.find(".close-reconciliation").on("click", close_reconciliation_dialog);
		$reconciliation.find(".cancel-reconciliation").on("click", cancel_reconciliation);
		$reconciliation.find(".clear-reconciliation").on("click", clear_reconciliation_view);
	}

	function reconciliation_dialog() {
		if (!state.can_reconcile) return frappe.msgprint(__("This operator is not assigned to Logistics Reconciliation."));
		if (!state.vehicle_warehouses.length) return frappe.msgprint(__("No active Vehicle Warehouse is configured."));
		const dialog = new frappe.ui.Dialog({ title: __("Start or Continue Route Stock Count"), fields: [
			{ fieldname: "warehouse", label: __("Company-specific Vehicle Warehouse"), fieldtype: "Select", reqd: 1,
				options: state.vehicle_warehouses.map((row) => row.name).join("\n"),
				description: __("One physical lorry may have a separate Warehouse for each Company. Count only one Company Warehouse at a time.") },
		], primary_action_label: __("Start / Continue Count"), primary_action: async (values) => {
			const warehouse = state.vehicle_warehouses.find((row) => row.name === values.warehouse);
			const response = await frappe.call({ method: "cfg_kanban.services.route_reconciliation.start_route_reconciliation", args: {
				company: warehouse.company, vehicle_warehouse: warehouse.name,
				event_token: unique_token(), operator_session_token: state.token,
			}, freeze: true, freeze_message: __("Opening ERP stock snapshot...") });
			dialog.hide(); state.reconciliation = response.message; state.scan_mode = "lookup";
			localStorage.setItem(last_reconciliation_key, state.reconciliation.name);
			render_reconciliation(); await refresh_list(); focus_scanner();
		} });
		dialog.show();
	}

	async function open_reconciliation(name, options) {
		try {
			const response = await frappe.call({ method: "cfg_kanban.services.route_reconciliation.get_route_reconciliation", args: {
				reconciliation_name: name, operator_session_token: state.token,
			} });
			state.reconciliation = response.message;
			localStorage.setItem(last_reconciliation_key, name);
			render_reconciliation(); focus_scanner(); return true;
		} catch (error) {
			localStorage.removeItem(last_reconciliation_key); state.reconciliation = null; render_reconciliation();
			if (!options?.quiet) scanner_error(__("Route Reconciliation could not be opened for this operator."));
			return false;
		}
	}

	async function reconciliation_scan(raw) {
		if (!state.reconciliation) return scanner_error(__("Open a Route Stock Count first."));
		try {
			const response = await frappe.call({ method: "cfg_kanban.services.route_reconciliation.scan_reconciliation_tag", args: {
				reconciliation_name: state.reconciliation.name, scan_value: raw,
				event_token: unique_token(), operator_session_token: state.token,
			}, freeze: true, freeze_message: __("Counting Stock Tag...") });
			state.reconciliation = response.message; render_reconciliation();
			$scanner.find(".scanner-message").html(`<small class="text-success">${__("Counted: {0}", [frappe.utils.escape_html(raw)])}</small>`);
		} catch (error) { scanner_error(__("Tag was not accepted into the route count.")); }
		focus_scanner();
	}

	async function remove_reconciliation_scan(handling_unit) {
		const response = await frappe.call({ method: "cfg_kanban.services.route_reconciliation.remove_reconciliation_scan", args: {
			reconciliation_name: state.reconciliation.name, handling_unit,
			operator_session_token: state.token,
		} });
		state.reconciliation = response.message; render_reconciliation(); focus_scanner();
	}

	function loose_count_dialog() {
		const rows = (state.reconciliation.lines || []).filter((row) => Number(row.loose_count_qty || 0) !== 0)
			.map((row) => ({ item_code: row.item_code, batch_no: row.batch_no, qty: row.loose_count_qty }));
		const dialog = new frappe.ui.Dialog({ title: __("Loose / Untagged Physical Count"), size: "extra-large", fields: [
			{ fieldname: "counts", label: __("Loose Stock"), fieldtype: "Table", data: rows,
				in_place_edit: true, description: __("Enter only physical quantity not represented by the Stock Tags scanned above."),
				fields: [
					{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item", reqd: 1, in_list_view: 1, columns: 4 },
					{ fieldname: "batch_no", label: __("Batch"), fieldtype: "Link", options: "Batch", in_list_view: 1, columns: 4 },
					{ fieldname: "qty", label: __("Physical Qty"), fieldtype: "Float", reqd: 1, in_list_view: 1, columns: 4 },
				] },
		], primary_action_label: __("Save Loose Count"), primary_action: async (values) => {
			const response = await frappe.call({ method: "cfg_kanban.services.route_reconciliation.save_loose_counts", args: {
				reconciliation_name: state.reconciliation.name,
				counts: JSON.stringify(values.counts || []), operator_session_token: state.token,
			}, freeze: true });
			dialog.hide(); state.reconciliation = response.message; render_reconciliation(); focus_scanner();
		} });
		dialog.show();
	}

	async function evaluate_reconciliation() {
		const response = await frappe.call({ method: "cfg_kanban.services.route_reconciliation.evaluate_route_reconciliation", args: {
			reconciliation_name: state.reconciliation.name, operator_session_token: state.token,
		}, freeze: true, freeze_message: __("Comparing physical count with ERPNext...") });
		state.reconciliation = response.message; state.scan_mode = "lookup";
		render_reconciliation(); await refresh_list(); focus_scanner();
	}

	function close_reconciliation_dialog() {
		const had_variance = Boolean(state.reconciliation.variance_exception);
		const dialog = new frappe.ui.Dialog({ title: __("Close Balanced Route Reconciliation"), fields: [
			{ fieldname: "resolution_notes", label: had_variance ? __("Recount / Resolution Notes") : __("Closing Notes"),
				fieldtype: "Small Text", reqd: had_variance ? 1 : 0 },
			{ fieldname: "correction_reference_doctype", label: __("ERP Correction Document Type"), fieldtype: "Select", options: "\nStock Reconciliation\nStock Entry\nDelivery Note\nPurchase Receipt" },
			{ fieldname: "correction_reference", label: __("ERP Correction Document"), fieldtype: "Dynamic Link", options: "correction_reference_doctype" },
		], primary_action_label: __("Close Reconciliation"), primary_action: async (values) => {
			const response = await frappe.call({ method: "cfg_kanban.services.route_reconciliation.close_route_reconciliation", args: {
				reconciliation_name: state.reconciliation.name, resolution_notes: values.resolution_notes,
				correction_reference_doctype: values.correction_reference_doctype,
				correction_reference: values.correction_reference, operator_session_token: state.token,
			}, freeze: true, freeze_message: __("Closing balanced route count...") });
			dialog.hide(); state.reconciliation = response.message; render_reconciliation(); await refresh_list(); focus_scanner();
			if (state.reconciliation.state === "Variance") frappe.msgprint({ title: __("Route Count Changed"), indicator: "red",
				message: __("ERPNext stock changed after evaluation or the count is still different. Recount or post the authorized ERP correction, then evaluate again.") });
		} });
		dialog.show();
	}

	function cancel_reconciliation() {
		frappe.prompt([{ fieldname: "reason", label: __("Cancellation Reason"), fieldtype: "Small Text", reqd: 1 }], async (values) => {
			const response = await frappe.call({ method: "cfg_kanban.services.route_reconciliation.cancel_route_reconciliation", args: {
				reconciliation_name: state.reconciliation.name, reason: values.reason,
				operator_session_token: state.token,
			}, freeze: true });
			state.reconciliation = response.message; state.scan_mode = "lookup";
			render_reconciliation(); await refresh_list(); focus_scanner();
		}, __("Cancel Route Stock Count"), __("Cancel Count"));
	}

	function clear_reconciliation_view() {
		state.scan_mode = "lookup"; state.reconciliation = null;
		localStorage.removeItem(last_reconciliation_key); render_reconciliation(); update_scanner_state(); focus_scanner();
	}

	function render_list() {
		const e = frappe.utils.escape_html;
		const open_rows = state.manifests.map((m) =>
			`<button class="frappe-card cfg-logistics-list-row" data-name="${e(m.name)}"><div><strong>${e(m.name)}</strong><small>${e(m.manifest_type || __("Movement Manifest"))} · ${e(m.logistics_route)}</small></div>
			<div><span class="indicator-pill ${state_colour(m.state)}">${e(m.state)}</span><small>${format_number(m.total_quantity)} ${__("total quantity")}</small></div></button>`).join("") ||
			`<div class="text-muted p-4">${__("No open Manifests available for this operator")}</div>`;
		const recent_rows = state.recent_manifests.map((m) =>
			`<button class="frappe-card cfg-logistics-list-row recent-manifest-row" data-name="${e(m.name)}"><div><strong>${e(m.name)}</strong><small>${e(m.manifest_type || __("Movement Manifest"))} · ${e(m.logistics_route)} · ${e(display_datetime(m.modified))}</small></div>
			<div><span class="indicator-pill ${state_colour(m.state)}">${e(m.state)}</span><small>${format_number(m.total_quantity)} ${__("total quantity")}</small></div></button>`).join("") ||
			`<div class="text-muted p-3">${__("No recently completed Manifests")}</div>`;
		const transfer_rows = state.internal_transfers.map((row) => {
			const from = (row.source_warehouses || []).join(", ") || "-";
			const to = (row.destination_warehouses || []).join(", ") || "-";
			const trace_colour = row.trace_status === "Confirmed" ? "green" :
				row.trace_status === "Draft" ? "orange" : "grey";
			return `<button class="frappe-card cfg-logistics-list-row internal-transfer-row" data-name="${e(row.name)}">
				<div><strong>${e(row.name)}</strong><small>${e(row.company)} · ${e(from)} → ${e(to)}</small></div>
				<div><span class="indicator-pill ${row.docstatus === 1 ? "green" : "orange"}">${e(row.erp_status)}</span>
				<span class="indicator-pill ${trace_colour}">${e(row.trace_status)}</span>
				<small>${e(row.item_count)} ${__("rows")} · ${format_number(row.total_quantity)} ${__("total quantity")}</small></div>
			</button>`;
		}).join("") || `<div class="text-muted p-4">${__("No Material Transfer Stock Entries are available, or this operator lacks Internal Warehouse Transfer responsibility.")}</div>`;
		const delivery_rows = state.delivery_sessions.map((row) =>
			`<button class="frappe-card cfg-logistics-list-row delivery-session-row" data-name="${e(row.name)}"><div><strong>${e(row.name)}</strong><small>${e(row.site_name)} · ${e(row.customer)}</small></div>
			<div><span class="indicator-pill orange">${e(row.state)}</span><small>${e(row.vehicle_reference)} · ${e(row.source_warehouse)}</small></div></button>`
		).join("") || `<div class="text-muted p-3">${__("No active Customer Delivery Sessions for this operator")}</div>`;
		const return_rows = state.return_cases.map((row) =>
			`<button class="frappe-card cfg-logistics-list-row return-case-row" data-name="${e(row.name)}"><div><strong>${e(row.name)}</strong><small>${e(row.site_name)} · ${e(row.return_flow)}</small></div>
			<div><span class="indicator-pill orange">${e(row.state)}</span><small>${__("Claim quantity recorded")}</small></div></button>`
		).join("") || `<div class="text-muted p-3">${__("No open Customer Return Cases for this operator")}</div>`;
		const reconciliation_rows = state.open_reconciliations.map((row) =>
			`<button class="frappe-card cfg-logistics-list-row reconciliation-row" data-name="${e(row.name)}"><div><strong>${e(row.name)}</strong><small>${e(row.vehicle_reference)} · ${e(row.vehicle_warehouse)}</small></div>
			<div><span class="indicator-pill ${reconciliation_colour(row.state)}">${e(row.state)}</span><small>${__("Variance lines")}: ${format_number(row.variance_line_count)}</small></div></button>`
		).join("") || `<div class="text-muted p-3">${state.can_reconcile ? __("No open Route Stock Counts") : __("Logistics Reconciliation responsibility is not assigned")}</div>`;
		const recent_reconciliation_rows = state.recent_reconciliations.map((row) =>
			`<button class="frappe-card cfg-logistics-list-row reconciliation-row" data-name="${e(row.name)}"><div><strong>${e(row.name)}</strong><small>${e(row.vehicle_reference)} · ${e(display_datetime(row.modified))}</small></div>
			<div><span class="indicator-pill ${reconciliation_colour(row.state)}">${e(row.state)}</span><small>${__("Variance lines")}: ${format_number(row.variance_line_count)}</small></div></button>`
		).join("") || `<div class="text-muted p-3">${__("No recently closed Route Stock Counts")}</div>`;
		$list.html(`<section class="cfg-reconciliation-list mb-4"><h3>${__("End-of-route Reconciliation")}</h3>
			<p class="text-muted">${__("Physically count one Company-specific lorry Warehouse, compare it with ERPNext, and resolve every variance before route closure.")}</p>
			${reconciliation_rows}<details class="cfg-logistics-recent mt-3"><summary><strong>${__("Recently Closed Counts")}</strong></summary><div class="mt-3">${recent_reconciliation_rows}</div></details></section>
			<section class="cfg-customer-delivery-list mb-4"><h3>${__("Customer Delivery Sessions")}</h3>
			<p class="text-muted">${__("Scan a Customer Site code in normal lookup mode to start a controlled delivery context.")}</p>${delivery_rows}</section>
			<section class="cfg-customer-return-list mb-4"><h3>${__("Customer Return Intake")}</h3>
			<p class="text-muted">${__("Returned goods under inspection are physical custody only and are not ERPNext available stock.")}</p>${return_rows}</section>
			<section class="cfg-internal-transfer-list mb-4"><h3>${__("Manual Material Transfer Fallback")}</h3>
			<p class="text-muted">${__("For same-Company movements not started by a Transfer Kanban Card: an authorized ERP user prepares the Draft Material Transfer, then physical tags can be traced here. Card-triggered replenishment appears in Open Movement Manifests above.")}</p>${transfer_rows}</section>
			<section class="cfg-logistics-open-list"><h3>${__("Open Movement Manifests")}</h3>${open_rows}</section>
			<details class="cfg-logistics-recent mt-4"><summary><strong>${__("Recently Completed")}</strong> <span class="text-muted">${__("Latest 10")}</span></summary><div class="mt-3">${recent_rows}</div></details>`);
		$list.find(".cfg-logistics-list-row").on("click", function () { open_manifest($(this).data("name")); });
		$list.find(".internal-transfer-row").off("click").on("click", function () {
			internal_transfer_dialog($(this).data("name"));
		});
		$list.find(".delivery-session-row").off("click").on("click", function () {
			open_delivery_session($(this).data("name"));
		});
		$list.find(".return-case-row").off("click").on("click", function () {
			open_return_case($(this).data("name"));
		});
		$list.find(".reconciliation-row").off("click").on("click", function () {
			open_reconciliation($(this).data("name"));
		});
	}

	async function internal_transfer_dialog(stock_entry) {
		let plan = await load_internal_transfer_plan(stock_entry);
		let dialog;
		const reload = async () => {
			plan = await load_internal_transfer_plan(stock_entry);
			await refresh_internal_transfer_dialog(dialog, plan, reload);
		};
		dialog = new frappe.ui.Dialog({
			title: __("Tagged Warehouse Transfer: {0}", [stock_entry]), size: "extra-large",
			fields: [
				{ fieldname: "summary", fieldtype: "HTML" },
				{ fieldname: "input_section", label: __("Scan Physical Stock Tags"), fieldtype: "Section Break" },
				{ fieldname: "input_row", label: __("ERP Transfer Row"), fieldtype: "Select" },
				{ fieldname: "input_scan", label: __("Handling Unit Tag"), fieldtype: "Data",
					description: __("Scan the active tag in the ERP source Warehouse. The entire physical Handling Unit moves together.") },
				{ fieldname: "camera_scan", label: __("Scan Tag with Camera"), fieldtype: "Button",
					click: () => camera_value((value) => {
						dialog.set_value("input_scan", value);
						dialog.get_field("allocate_input").$input.trigger("click");
					}) },
				{ fieldname: "input_qty", label: __("Stock Quantity (0 = complete tag)"), fieldtype: "Float", default: 0,
					description: __("A general Warehouse transfer cannot split one physical tag across two locations.") },
				{ fieldname: "allocate_input", label: __("Add Tag to Transfer"), fieldtype: "Button",
					click: async () => {
						await frappe.call({ method: "cfg_kanban.services.production_trace.allocate_input_tag", args: {
							stock_entry, item_row: transfer_row_name(dialog.get_value("input_row")),
							scan_value: dialog.get_value("input_scan"), qty: dialog.get_value("input_qty") || 0,
							operator_session_token: state.token,
						}, freeze: true, freeze_message: __("Reserving tag for Warehouse transfer...") });
						frappe.show_alert({ message: __("Tag reserved for this Material Transfer"), indicator: "green" });
						await dialog.set_value("input_scan", "");
						await reload();
					} },
				{ fieldname: "line_section", label: __("Transfer Trace Lines"), fieldtype: "Section Break" },
				{ fieldname: "lines", fieldtype: "HTML" },
			],
		});
		dialog.onhide = async () => { await refresh_list(); focus_scanner(); };
		dialog.show();
		await refresh_internal_transfer_dialog(dialog, plan, reload);
	}

	async function load_internal_transfer_plan(stock_entry) {
		const response = await frappe.call({
			method: "cfg_kanban.services.production_trace.get_stock_entry_trace_plan",
			args: { stock_entry, operator_session_token: state.token },
		});
		return response.message;
	}

	async function refresh_internal_transfer_dialog(dialog, plan, reload) {
		const rows = (plan.rows || []).filter((row) => row.direction === "Input" &&
			row.tagging_available && row.remaining_qty > 0.000001);
		const options = rows.map(transfer_row_option);
		dialog.set_df_property("input_row", "options", options.join("\n"));
		dialog.fields_dict.summary.$wrapper.html(internal_transfer_summary(plan));
		dialog.fields_dict.lines.$wrapper.html(internal_transfer_lines(plan));
		const editable = plan.can_edit && options.length;
		["input_section", "input_row", "input_scan", "camera_scan", "input_qty", "allocate_input"]
			.forEach((name) => dialog.get_field(name).wrapper.toggle(Boolean(editable)));
		if (editable) {
			const selected = options.includes(dialog.get_value("input_row")) ?
				dialog.get_value("input_row") : options[0];
			await dialog.set_value("input_row", selected);
			const field = dialog.get_field("input_scan");
			field.$input.off("keydown.cfg_internal_transfer").on("keydown.cfg_internal_transfer", (event) => {
				if (event.key !== "Enter" && event.key !== "Tab") return;
				event.preventDefault();
				dialog.get_field("allocate_input").$input.trigger("click");
			});
			window.setTimeout(() => field.set_focus(), 80);
		}
		dialog.fields_dict.lines.$wrapper.find("[data-cancel-transfer-line]").off("click").on("click", async (event) => {
			await frappe.call({ method: "cfg_kanban.services.production_trace.cancel_trace_line", args: {
				stock_entry: plan.stock_entry, trace_line: event.currentTarget.dataset.cancelTransferLine,
				operator_session_token: state.token,
			}, freeze: true, freeze_message: __("Releasing transfer reservation...") });
			await reload();
		});
	}

	function transfer_row_option(row) {
		return `${row.row_name} :: ${row.item_code} :: ${row.remaining_qty} ${row.stock_uom} :: ${row.warehouse}`;
	}

	function transfer_row_name(value) {
		return String(value || "").split(" :: ")[0];
	}

	function internal_transfer_summary(plan) {
		const e = frappe.utils.escape_html;
		const rows = (plan.rows || []).map((row) => `<tr><td>${e(row.item_code)}</td>
			<td>${e(row.batch_no || "-")}</td><td>${e(row.warehouse || "-")}</td><td>${e(row.tag_policy)}</td>
			<td>${e(row.traced_qty)} / ${e(row.stock_qty)} ${e(row.stock_uom)}</td></tr>`).join("");
		return `<div class="alert alert-info"><strong>${e(plan.stock_entry)}</strong> · ${e(plan.company)} · ${e(plan.purpose)}
			<a class="btn btn-default btn-xs ml-2" href="/app/stock-entry/${encodeURIComponent(plan.stock_entry)}">${__("Open ERP Stock Entry")}</a><br>
			${__("Material Trace")}: ${e(plan.trace || __("Not created"))} · ${e(plan.trace_status)}</div>
			<div class="table-responsive"><table class="table table-bordered table-sm"><thead><tr>
			<th>${__("Item")}</th><th>${__("Batch")}</th><th>${__("Source Warehouse")}</th><th>${__("Tag Policy")}</th>
			<th>${__("Traced / ERP Qty")}</th></tr></thead><tbody>${rows}</tbody></table></div>
			<p class="text-muted">${__("No Physical Tag rows need no scan. Submit the ERPNext Stock Entry to confirm the same-company Warehouse movement.")}</p>`;
	}

	function internal_transfer_lines(plan) {
		if (!(plan.lines || []).length) return `<p class="text-muted">${__("No tagged Handling Units reserved yet.")}</p>`;
		const e = frappe.utils.escape_html;
		const rows = plan.lines.map((line) => `<tr><td>${e(line.item_code)}</td><td>${e(line.handling_unit || "-")}</td>
			<td>${e(line.qty)} ${e(line.stock_uom)}</td><td>${e(line.status)}</td><td>${line.can_cancel ?
				`<button class="btn btn-xs btn-danger" data-cancel-transfer-line="${e(line.name)}">${__("Remove")}</button>` : ""}</td></tr>`).join("");
		return `<div class="table-responsive"><table class="table table-bordered table-sm"><thead><tr>
			<th>${__("Item")}</th><th>${__("Tag")}</th><th>${__("Quantity")}</th><th>${__("Status")}</th><th></th>
			</tr></thead><tbody>${rows}</tbody></table></div>`;
	}

	function camera_value(callback) {
		if (!(frappe.ui && frappe.ui.Scanner)) return frappe.msgprint(__("Camera scanning is unavailable. Use the scanner field."));
		new frappe.ui.Scanner({ dialog: true, multiple: false, on_scan(data) {
			callback(String(data.decodedText || "").trim());
		} });
	}

	function render_lookup() {
		if (!state.lookup) return $lookup.empty();
		if (state.lookup.withdrawal_card) {
			render_withdrawal_card(state.lookup);
			return;
		}
		if (state.lookup.transfer_card) {
			render_transfer_card(state.lookup);
			return;
		}
		if (state.lookup.supplier_receiving) {
			render_supplier_receiving(state.lookup.supplier_receiving);
			return;
		}
		if (state.lookup.warehouse_operations) {
			render_warehouse_operations(state.lookup.warehouse_operations);
			return;
		}
		if (state.lookup.return_case) {
			render_return_case(state.lookup.return_case);
			return;
		}
		if (state.lookup.delivery_session) {
			render_delivery_session(state.lookup.delivery_session);
			return;
		}
		if (state.lookup.customer_site) {
			render_customer_site(state.lookup.customer_site);
			return;
		}
		if (!state.lookup.handling_unit) {
			const identity = state.lookup.identity || {}; const e = frappe.utils.escape_html;
			const is_range = identity.identity_type === "Tag Range Candidate";
			const range_detail = is_range ?
				`<p class="mb-2"><strong>${__("Range Registry")}:</strong> ${e(identity.range_registry || "-")}</p>` : "";
			const status_message = is_range ?
				__("This preprinted code is valid in an active serial range but has never been activated. Its exact Tag Family will be created only when a Handling Unit is saved for it; it cannot be dispatched or received before then.") :
				__("This code is registered but is not an active stock Handling Unit. It cannot be dispatched or received until it is activated and assigned stock details.");
			$lookup.html(`<div class="frappe-card cfg-logistics-tag-status">
				<div class="cfg-logistics-tag-head"><div><small>${__("Scanned Identity Status")}</small>
					<h3>${e(identity.visible_code || identity.name || "-")}</h3>
					<strong>${e(identity.identity_type || __("Registered identity"))}</strong></div>
					<button class="btn btn-default close-lookup">${__("Close")}</button></div>
				${range_detail}<div class="alert alert-warning mt-3 mb-0">${status_message}</div>
			</div>`);
			$lookup.find(".close-lookup").on("click", () => { state.lookup = null; render_lookup(); focus_scanner(); });
			return;
		}
		const e = frappe.utils.escape_html; const unit = state.lookup.handling_unit;
		const movement = state.lookup.last_movement;
		const container_status = state.lookup.container_status || {};
		const membership = container_status.active_membership;
		const serials = state.lookup.active_serial_numbers || [];
		const manifests = (state.lookup.manifests || []).map((manifest) =>
			`<button class="btn btn-default lookup-manifest" data-name="${e(manifest.name)}"><strong>${e(manifest.name)}</strong> · ${e(manifest.state)}</button>`
		).join("");
		const customer_deliveries = (state.lookup.customer_deliveries || []).map((row) =>
			`<span><button class="btn btn-default lookup-delivery" data-name="${e(row.delivery_session)}"><strong>${e(row.delivery_session)}</strong> · ${e(row.delivery_note)}</button>
			<button class="btn btn-warning lookup-return" data-name="${e(row.delivery_session)}">${__("Record Return")} · ${format_number(row.delivered_qty)}</button></span>`
		).join("");
		const container_action = container_status.mode === "container" && state.lookup.can_manage_container ?
			`<button class="btn btn-primary manage-container">${__("Manage Contents")}</button>` : "";
		const membership_notice = membership ? `<div class="alert alert-warning mt-3">
			<strong>${__("Physically inside reusable container")}: ${e(membership.container_visible_code)}</strong><br>
			<small>${__("Unload this Stock Tag from the container before moving, consuming, replacing, or voiding it independently.")}</small></div>` : "";
		const content_notice = container_status.mode === "container" ? `<div class="alert alert-info mt-3">
			<strong>${__("Current contents")}: ${(container_status.current_contents || []).length} ${__("complete Stock Tags")}</strong><br>
			<small>${__("Container membership is physical grouping only. ERP stock remains recorded against each Stock Tag.")}</small>
			${state.lookup.can_manage_container ? "" : `<br><small>${__("Container Loading responsibility is required to change contents.")}</small>`}</div>` : "";
		const serial_notice = serials.length ? `<div class="alert alert-success mt-3"><strong>${serials.length} ${__("exact ERPNext Serial Numbers")}</strong><br>
			<small>${serials.map((value) => e(value)).join(", ")}</small></div>` : "";
		const retag_actions = state.lookup.can_retag && unit.tag_kind !== "Reusable Container" ? `<div class="alert alert-primary mt-3 cfg-logistics-retagging">
			<strong>${__("Stock Retagging")}</strong><br><small>${__("Same-warehouse physical quantity control. ERPNext stock does not move.")}</small>
			<div class="mt-2"><button class="btn btn-primary split-unused-tag">${__("Split to New Tag")}</button>
			<button class="btn btn-warning transfer-active-tag">${__("Move to Active Tag")}</button></div></div>` : "";
		$lookup.html(`<div class="frappe-card cfg-logistics-tag-status">
			<div class="cfg-logistics-tag-head"><div><small>${__("Scanned Tag Status")}</small><h3>${e(unit.visible_code)}</h3><strong>${e(unit.item_code || __("No item assigned"))}</strong></div>
				<div>${container_action}<button class="btn btn-default explore-genealogy" data-code="${e(unit.visible_code)}">${__("Full Genealogy")}</button>
				<button class="btn btn-default close-lookup">${__("Close")}</button></div></div>
			<div class="cfg-logistics-tag-grid">
				<div><small>${__("Batch")}</small><strong>${e(unit.batch_no || __("No Batch"))}</strong></div>
				<div><small>${__("Company")}</small><strong>${e(unit.inventory_company || "-")}</strong></div>
				<div><small>${__("Location")}</small><strong>${e(unit.current_warehouse || unit.physical_custodian || __("In Transit / Unassigned"))}</strong></div>
				<div><small>${__("Quantity")}</small><strong>${format_number(unit.current_qty)} ${e(unit.stock_uom || "")}</strong></div>
				<div><small>${__("Available / Reserved")}</small><strong>${format_number(unit.available_qty)} / ${format_number(unit.reserved_qty)}</strong></div>
				<div><small>${__("Lifecycle")}</small><strong>${e(unit.identity_state)} · ${e(unit.movement_state)} · ${e(unit.quality_state)}</strong></div>
			</div>
			${membership_notice}${content_notice}${serial_notice}${retag_actions}
			<div class="cfg-logistics-last-movement"><small>${__("Last movement")}</small><strong>${movement ? `${e(movement.event_type)} · ${e(display_datetime(movement.posting_datetime))}` : __("No quantity movement recorded")}</strong></div>
			<div class="cfg-logistics-related"><small>${__("Related Manifests")}</small><div>${manifests || `<span class="text-muted">${__("No Manifest history for this tag")}</span>`}</div></div>
			<div class="cfg-logistics-related"><small>${__("Customer Delivery History")}</small><div>${customer_deliveries || `<span class="text-muted">${__("No delivered customer allocation for this tag")}</span>`}</div></div>
		</div>`);
		$lookup.find(".close-lookup").on("click", () => { state.lookup = null; render_lookup(); focus_scanner(); });
		$lookup.find(".lookup-manifest").on("click", function () { open_manifest($(this).data("name")); });
		$lookup.find(".lookup-delivery").on("click", function () { open_delivery_session($(this).data("name")); });
		$lookup.find(".lookup-return").on("click", function () { open_customer_return({ name: $(this).data("name") }); });
		$lookup.find(".explore-genealogy").on("click", function () {
			frappe.set_route("material-genealogy", $(this).data("code"));
		});
		$lookup.find(".manage-container").on("click", manage_container_dialog);
		$lookup.find(".split-unused-tag").on("click", () => open_stock_retagging_dialog("split"));
		$lookup.find(".transfer-active-tag").on("click", () => open_stock_retagging_dialog("transfer"));
	}

	function render_withdrawal_card(lookup) {
		const e = frappe.utils.escape_html;
		const card = lookup.withdrawal_card;
		const withdrawal = lookup.withdrawal;
		const allocations = (withdrawal?.withdrawal_allocations || []).map((row) =>
			`<div class="cfg-logistics-list-row"><div><strong>${e(row.visible_code || row.line_kind)}</strong>
			<small>${e(row.line_kind)} · ${e(row.state)}</small></div>
			<div><strong>${format_number(row.qty)} ${e(row.stock_uom || "")}</strong>
			${withdrawal.can_edit_selection && row.handling_unit ? `<button class="btn btn-xs btn-danger remove-withdrawal-tag" data-unit="${e(row.handling_unit)}">${__("Remove")}</button>` : ""}</div></div>`
		).join("");
		let actions = "";
		if (!card.active_cycle) {
			actions = card.can_trigger ? `<button class="btn btn-primary trigger-withdrawal-card">${__("Trigger Withdrawal Card")}</button>` : "";
		} else if (!withdrawal) {
			actions = `<div class="alert alert-warning">${__("The Withdrawal Signal is waiting for supervisor approval.")}</div>`;
		} else {
			const non_stock_notice = withdrawal.non_stock_operational_tracking ?
				`<div class="alert alert-info mt-3"><strong>${__("Kanban operational inventory")}</strong> · ${__("This non-stock Item requires physical tags. Confirmation consumes the Handling Unit balance without creating an ERPNext Material Issue.")}</div>` : "";
			actions = `<div class="cfg-logistics-toolbar mt-3">
			${withdrawal.can_edit_selection && withdrawal.withdrawal_tag_policy !== "No Physical Tag" ? `<button class="btn btn-primary add-withdrawal-tag">${__("Add Stock Tag")}</button>` : ""}
			${withdrawal.can_use_untagged_stock ? `<button class="btn btn-default use-untagged-withdrawal">${__("Use ERP Stock without Tags")}</button>` : ""}
			${withdrawal.can_prepare ? `<button class="btn btn-warning prepare-withdrawal">${__("Prepare Withdrawal")}</button>` : ""}
			${withdrawal.can_confirm ? `<button class="btn btn-success confirm-withdrawal">${withdrawal.non_stock_operational_tracking ? __("Confirm Tagged Withdrawal") : __("Create Material Issue")}</button>` : ""}
			${withdrawal.withdrawal_stock_entry ? `<button class="btn btn-default open-withdrawal-entry">${__("Open Stock Entry")}</button>` : ""}
			${withdrawal.can_discard_draft ? `<button class="btn btn-danger discard-withdrawal-draft">${__("Discard Draft and Retry")}</button>` : ""}
			</div>${non_stock_notice}`;
		}
		$lookup.html(`<div class="frappe-card cfg-logistics-tag-status">
			<div class="cfg-logistics-tag-head"><div><small>${__("Stock Withdrawal Kanban")}</small>
			<h3>${e(card.card_number || card.card)}</h3><strong>${e(card.item_code)}</strong></div>
			<button class="btn btn-default close-lookup">${__("Close")}</button></div>
			<div class="cfg-logistics-tag-grid">
			<div><small>${__("Source Warehouse")}</small><strong>${e(card.source_warehouse)}</strong></div>
			<div><small>${__("Card Quantity")}</small><strong>${format_number(card.quantity)} ${e(card.stock_uom || "")}</strong></div>
			<div><small>${__("Cycle")}</small><strong>${e(card.active_cycle || __("Not triggered"))}</strong></div>
			<div><small>${__("Withdrawal Status")}</small><strong>${e(withdrawal?.withdrawal_status || __("Waiting"))}</strong></div>
			<div><small>${__("Tag Policy")}</small><strong>${e(withdrawal?.withdrawal_tag_policy || "-")}</strong></div>
			<div><small>${__("Selected")}</small><strong>${format_number(withdrawal?.selected_qty || 0)} / ${format_number(card.quantity)}</strong></div></div>
			${allocations ? `<div class="mt-3"><strong>${__("Selected Stock")}</strong>${allocations}</div>` : ""}
			${actions}</div>`);
		$lookup.find(".close-lookup").on("click", () => { state.lookup = null; render_lookup(); focus_scanner(); });
		$lookup.find(".trigger-withdrawal-card").on("click", () => trigger_withdrawal_card(card));
		$lookup.find(".add-withdrawal-tag").on("click", () => add_withdrawal_tag_dialog(card, withdrawal));
		$lookup.find(".use-untagged-withdrawal").on("click", () => withdrawal_action("select_untagged_stock", card, withdrawal));
		$lookup.find(".prepare-withdrawal").on("click", () => withdrawal_action("prepare_withdrawal", card, withdrawal));
		$lookup.find(".confirm-withdrawal").on("click", () => confirm_withdrawal(card, withdrawal));
		$lookup.find(".open-withdrawal-entry").on("click", () => frappe.set_route("Form", "Stock Entry", withdrawal.withdrawal_stock_entry));
		$lookup.find(".discard-withdrawal-draft").on("click", () => {
			frappe.prompt([{ fieldname: "reason", label: __("Discard Reason"), fieldtype: "Small Text", reqd: 1 }],
				async (values) => {
					await frappe.call({ method: "cfg_kanban.services.withdrawal.discard_withdrawal_draft",
						args: { cycle_name: withdrawal.name, reason: values.reason,
							operator_session_token: state.token }, freeze: true,
						freeze_message: __("Discarding unused Material Issue draft...") });
					await lookup_tag(card.card_number || card.card);
				}, __("Discard Draft Material Issue"), __("Discard and Retry"));
		});
		$lookup.find(".remove-withdrawal-tag").on("click", function () {
			withdrawal_action("remove_withdrawal_tag", card, withdrawal, { handling_unit: $(this).data("unit") });
		});
	}

	async function trigger_withdrawal_card(card) {
		const response = await frappe.call({
			method: "cfg_kanban.api.logistics.trigger_withdrawal_card",
			args: { card_name: card.card, event_token: unique_token(), operator_session_token: state.token },
			freeze: true, freeze_message: __("Triggering Withdrawal Card..."),
		});
		if (response.message.waiting_approval) frappe.msgprint(__("Withdrawal Signal {0} is waiting for supervisor approval.", [response.message.signal]));
		await lookup_tag(card.card_number || card.card);
	}

	function add_withdrawal_tag_dialog(card, withdrawal) {
		const dialog = new frappe.ui.Dialog({
			title: __("Add Stock Tag to Withdrawal"),
			fields: [
				{ fieldname: "scan_value", label: __("Stock Tag Barcode / QR"), fieldtype: "Data", reqd: 1 },
				{ fieldname: "camera", label: __("Scan with Camera"), fieldtype: "Button", click() {
					camera_value((value) => dialog.set_value("scan_value", value));
				} },
				{ fieldname: "qty", label: __("Quantity from this Tag"), fieldtype: "Float", reqd: 1,
					default: withdrawal.remaining_qty },
			],
			primary_action_label: __("Add Tag"),
			primary_action: async (values) => {
				dialog.hide();
				await withdrawal_action("add_withdrawal_tag", card, withdrawal, {
					scan_value: values.scan_value, qty: values.qty,
				});
			},
		});
		dialog.show();
		dialog.get_field("scan_value").$input.focus();
	}

	async function withdrawal_action(method, card, withdrawal, extra) {
		await frappe.call({
			method: `cfg_kanban.services.withdrawal.${method}`,
			args: { cycle_name: withdrawal.name, event_token: unique_token(),
				operator_session_token: state.token, ...(extra || {}) },
			freeze: true, freeze_message: __("Updating stock withdrawal..."),
		});
		await lookup_tag(card.card_number || card.card);
	}

	async function confirm_withdrawal(card, withdrawal) {
		const response = await frappe.call({
			method: "cfg_kanban.services.withdrawal.get_withdrawal_requirements",
			args: { cycle_name: withdrawal.name, operator_session_token: state.token },
			freeze: true, freeze_message: withdrawal.non_stock_operational_tracking ?
				__("Checking tagged operational withdrawal...") : __("Checking Material Issue requirements..."),
		});
		const requirements = response.message.fields || [];
		if (!requirements.length) return submit_withdrawal(card, withdrawal);
		const dialog = new frappe.ui.Dialog({
			title: __("Required Material Issue Details"),
			fields: required_erp_dialog_fields(requirements),
			primary_action_label: __("Create Material Issue"),
			primary_action: async (values) => {
				dialog.hide();
				await submit_withdrawal(card, withdrawal,
					JSON.stringify(required_erp_values(requirements, values)));
			},
		});
		dialog.show();
	}

	async function submit_withdrawal(card, withdrawal, required_erp_inputs) {
		await frappe.call({
			method: "cfg_kanban.services.withdrawal.confirm_withdrawal",
			args: { cycle_name: withdrawal.name, event_token: unique_token(),
				operator_session_token: state.token, required_erp_inputs },
			freeze: true, freeze_message: withdrawal.non_stock_operational_tracking ?
				__("Consuming tagged operational stock...") : __("Creating ERPNext Material Issue..."),
		});
		await lookup_tag(card.card_number || card.card);
		await refresh_list();
	}

	function render_transfer_card(lookup) {
		const e = frappe.utils.escape_html;
		const card = lookup.transfer_card;
		const manifest = lookup.transfer_manifest;
		$lookup.html(`<div class="frappe-card cfg-logistics-tag-status">
			<div class="cfg-logistics-tag-head"><div><small>${__("Transfer Kanban Card")}</small>
			<h3>${e(card.card_number || card.card)}</h3><strong>${e(card.item_code)}</strong></div>
			<button class="btn btn-default close-lookup">${__("Close")}</button></div>
			<div class="cfg-logistics-route"><div><small>${__("FROM")}</small><strong>${e(card.source_warehouse)}</strong></div>
			<div class="cfg-logistics-arrow">→</div><div><small>${__("TO")}</small><strong>${e(card.destination_warehouse)}</strong></div></div>
			${manifest ? `<div class="alert alert-success mt-3"><strong>${e(manifest.name)} · ${e(manifest.state)}</strong><br>
			<small>${__("This card is already linked to its controlled Movement Manifest.")}</small></div>
			<button class="btn btn-primary open-transfer-manifest" data-name="${e(manifest.name)}">${__("Open Movement Manifest")}</button>` :
			`<div class="alert alert-warning mt-3">${card.active_cycle ? __("The Transfer Cycle is waiting for supervisor approval.") : __("Trigger this card to start its controlled warehouse replenishment.")}</div>
			${card.can_trigger ? `<button class="btn btn-primary trigger-transfer-card" data-name="${e(card.card)}">${__("Trigger Transfer Card")}</button>` : ""}`}
		</div>`);
		$lookup.find(".close-lookup").on("click", () => { state.lookup = null; render_lookup(); focus_scanner(); });
		$lookup.find(".open-transfer-manifest").on("click", function () { open_manifest($(this).data("name")); });
		$lookup.find(".trigger-transfer-card").on("click", function () {
			const card_name = $(this).data("name");
			frappe.confirm(__("Trigger this Transfer Card and create its replenishment Signal?"), async () => {
				const response = await frappe.call({
					method: "cfg_kanban.api.logistics.trigger_transfer_card",
					args: { card_name, event_token: unique_token(), operator_session_token: state.token },
					freeze: true, freeze_message: __("Triggering Transfer Card..."),
				});
				if (response.message.manifest) {
					state.lookup = null; render_lookup(); await open_manifest(response.message.manifest);
					frappe.show_alert({ message: __("Transfer released to Logistics"), indicator: "green" });
				} else {
					frappe.msgprint(__("Transfer Signal {0} is waiting for supervisor approval.", [response.message.signal]));
					await lookup_tag(card.card_number || card.card);
				}
				await refresh_list();
			});
		});
	}

	function render_supplier_receiving(context) {
		const e = frappe.utils.escape_html;
		const direct = context.mode === "purchase_card";
		const can_override = Boolean(state.operator?.permissions?.override);
		const rows = (context.pending_orders || []).map((row) => `<div class="frappe-card cfg-logistics-list-row supplier-receipt-row">
			<div><strong>${e(row.item_code)}</strong><small>${e(row.supplier)} · ${e(row.purchase_order)}</small>
			<small>${__("Purchase Card")}: ${e(row.card_number || "-")} · ${e(row.priority || "Normal")}</small></div>
			<div><strong>${format_number(row.outstanding_qty)} ${e(row.purchase_uom)} ${__("outstanding")}</strong>
			<small>${format_number(row.outstanding_stock_qty)} ${e(row.stock_uom)} · ${e(row.purchase_status)}</small>
			${direct || can_override ? `<button class="btn btn-primary receive-supplier" data-cycle="${e(row.cycle)}">${direct ? __("Receive This Order") : __("Supervisor Select")}</button>` : ""}</div>
		</div>`).join("") || `<div class="alert alert-success">${__("No submitted Purchase Orders are awaiting receipt at this warehouse.")}</div>`;
		$lookup.html(`<div class="frappe-card cfg-logistics-tag-status">
			<div class="cfg-logistics-tag-head"><div><small>${direct ? __("Purchase Kanban Receiving") : __("Warehouse Receiving Point")}</small>
			<h3>${e(context.warehouse)}</h3><strong>${e(context.company || "-")}</strong></div>
			<button class="btn btn-default close-lookup">${__("Close")}</button></div>
			<div class="alert ${direct ? "alert-success" : "alert-info"} mt-3">${direct ?
				__("The original Purchase Kanban card selected its exact submitted order.") :
				__("Pending orders are filtered to this warehouse. Scan the original Purchase Kanban card to select the exact order.")}</div>
			<div class="cfg-supplier-receipts">${rows}</div>
		</div>`);
		$lookup.find(".close-lookup").on("click", () => { state.lookup = null; render_lookup(); focus_scanner(); });
		$lookup.find(".receive-supplier").on("click", function () {
			const row = (context.pending_orders || []).find((value) => value.cycle === $(this).data("cycle"));
			if (row) supplier_receipt_dialog(row, !direct);
		});
	}

	function render_warehouse_operations(context) {
		const e = frappe.utils.escape_html;
		const can_override = Boolean(state.operator?.permissions?.override);
		const receipts = (context.pending_orders || []).map((row) => `<div class="frappe-card cfg-logistics-list-row warehouse-receipt-row">
			<div><strong>${e(row.item_code)}</strong><small>${e(row.supplier)} · ${e(row.purchase_order)}</small>
			<small>${__("Purchase Card")}: ${e(row.card_number || "-")} · ${e(row.purchase_status)}</small></div>
			<div><strong>${format_number(row.outstanding_qty)} ${e(row.purchase_uom)} ${__("outstanding")}</strong>
			${can_override ? `<button class="btn btn-primary warehouse-receive-order" data-cycle="${e(row.cycle)}">${__("Supervisor Select")}</button>` : `<small>${__("Scan the Purchase Kanban card to receive")}</small>`}</div>
		</div>`).join("") || `<div class="alert alert-light">${context.can_receive_supplier ? __("No submitted Purchase Orders are awaiting receipt here.") : __("Supplier Receiving is outside this operator's responsibility.")}</div>`;
		const manifests = (context.manifests || []).map((row) => `<div class="frappe-card cfg-logistics-list-row">
			<div><strong>${e(row.name)}</strong><small>${e(row.manifest_type)} · ${e(row.logistics_route)}</small>
			<small>${e(row.source_warehouse)} → ${e(row.destination_warehouse)}</small></div>
			<div><span class="indicator-pill ${state_colour(row.state)}">${e(row.state)}</span>
			<button class="btn btn-primary warehouse-open-manifest" data-name="${e(row.name)}">${__("Open")}</button></div>
		</div>`).join("") || `<div class="alert alert-light">${__("No authorized open movement Manifests involve this warehouse.")}</div>`;
		const cards = (context.stock_cards || []).map((row) => `<div class="frappe-card cfg-logistics-list-row">
			<div><strong>${e(row.item_code)}</strong><small>${e(row.control_type)} · ${e(row.kanban_name || row.kanban_master)}</small>
			<small>${e(row.source_warehouse || "-")} → ${e(row.destination_warehouse || "-")}</small></div>
			<div><span class="indicator-pill ${state_colour(row.current_state)}">${e(row.current_state)}</span>
			<button class="btn btn-default warehouse-open-card" data-number="${e(row.card_number)}">${__("Open Card")}</button></div>
		</div>`).join("") || `<div class="alert alert-light">${__("No authorized Transfer or Withdrawal cards involve this warehouse.")}</div>`;
		$lookup.html(`<div class="frappe-card cfg-logistics-tag-status">
			<div class="cfg-logistics-tag-head"><div><small>${__("Warehouse Operations Point")}</small>
			<h3>${e(context.location_reference || context.warehouse)}</h3><strong>${e(context.warehouse)} · ${e(context.company || "-")}</strong></div>
			<div>${context.can_adopt_stock ? `<button class="btn btn-primary adopt-existing-stock">${__("Tag Existing ERP Stock")}</button>` : ""}
			<button class="btn btn-default close-lookup">${__("Close")}</button></div></div>
			<div class="alert alert-info mt-3">${__("This permanent card is a read-only warehouse access point. Opening a listed transaction does not modify it until the operator explicitly confirms an action.")}</div>
			<h4>${__("Pending Supplier Receipts")}</h4><div class="cfg-supplier-receipts">${receipts}</div>
			<h4 class="mt-4">${__("Open Warehouse Movements")}</h4><div>${manifests}</div>
			<h4 class="mt-4">${__("Transfer and Withdrawal Cards")}</h4><div>${cards}</div>
		</div>`);
		$lookup.find(".close-lookup").on("click", () => { state.lookup = null; render_lookup(); focus_scanner(); });
		$lookup.find(".adopt-existing-stock").on("click", () => existing_stock_adoption_dialog(context));
		$lookup.find(".warehouse-open-manifest").on("click", function () { open_manifest($(this).data("name")); });
		$lookup.find(".warehouse-open-card").on("click", function () { lookup_tag($(this).data("number")); });
		$lookup.find(".warehouse-receive-order").on("click", function () {
			const row = (context.pending_orders || []).find((value) => value.cycle === $(this).data("cycle"));
			if (row) supplier_receipt_dialog(row, true);
		});
	}

	function existing_stock_adoption_dialog(warehouse_context) {
		const e = frappe.utils.escape_html;
		let adoption_context = null;
		const dialog = new frappe.ui.Dialog({
			title: __("Tag Existing ERP Stock"), size: "large", fields: [
				{ fieldname: "warning", fieldtype: "HTML", options: `<div class="alert alert-warning">
					<strong>${__("Identity only — no ERP stock movement")}</strong><br>
					${__("This action binds an unused physical tag to stock already posted in ERPNext. It never records new production or creates a Stock Entry.")}
				</div>` },
				{ fieldname: "item_code", label: __("Finished Item"), fieldtype: "Link", options: "Item", reqd: 1,
					get_query: () => ({ filters: { is_stock_item: 1, disabled: 0 } }),
					change: () => refresh_existing_stock_context(dialog, warehouse_context, (value) => { adoption_context = value; }) },
				{ fieldname: "batch_no", label: __("Batch"), fieldtype: "Link", options: "Batch",
					get_query: () => ({ filters: { item: dialog.get_value("item_code") || "" } }),
					change: () => refresh_existing_stock_context(dialog, warehouse_context, (value) => { adoption_context = value; }) },
				{ fieldname: "balance", fieldtype: "HTML", options: `<div class="text-muted">${__("Select an Item to check ERP and tagged balances.")}</div>` },
				{ fieldname: "qty", label: __("Quantity in this Container (Stock UOM)"), fieldtype: "Float", reqd: 1,
					description: __("Enter only the physical quantity carried by this tag. It may be lower than the remaining untagged ERP stock.") },
				{ fieldname: "scan_value", label: __("Unused Preprinted Main Tag"), fieldtype: "Data", reqd: 1 },
				{ fieldname: "camera_tag", label: __("Scan Tag with Camera"), fieldtype: "Button",
					click: () => camera_value((value) => dialog.set_value("scan_value", value)) },
				{ fieldname: "handling_unit_type", label: __("Handling Unit Type"), fieldtype: "Select",
					options: "Pallet\nMesh\nTote\nContainer\nReusable Box\nOther", default: "Container", reqd: 1 },
				{ fieldname: "packed_on", label: __("Packing Timestamp"), fieldtype: "Datetime",
					default: frappe.datetime.now_datetime(), reqd: 1 },
				{ fieldname: "expiry_date", label: __("Expiry Date Snapshot"), fieldtype: "Date" },
				{ fieldname: "serial_numbers", label: __("Serial Numbers (one per line)"), fieldtype: "Small Text",
					description: __("Required only for a serial-controlled Item; the count must equal the tag quantity.") },
				{ fieldname: "adoption_reason", label: __("Why was this existing stock not already tagged?"),
					fieldtype: "Small Text", reqd: 1 },
				...(warehouse_context.can_allocate_adopted_stock ? [
					{ fieldname: "kanban_cycle", label: __("Optional Eligible Kanban Cycle"), fieldtype: "Select",
						options: "", description: __("Supervisor-only. Reserves this complete tag but does not report production or close the Cycle.") },
					{ fieldname: "allocation_reason", label: __("Cycle Allocation Reason"), fieldtype: "Small Text",
						depends_on: "kanban_cycle", mandatory_depends_on: "kanban_cycle" },
				] : []),
				{ fieldname: "confirmed", label: __("I physically checked the Item, Batch, tag, quantity and Warehouse"),
					fieldtype: "Check", reqd: 1 },
			],
			primary_action_label: __("Adopt Existing Stock Tag"),
			primary_action: async (values) => {
				adoption_context = await refresh_existing_stock_context(
					dialog, warehouse_context, null, { preserve_quantity: true, show_error: true }
				);
				if (!adoption_context) return;
				if (adoption_context.batch_required && !values.batch_no) {
					return frappe.msgprint(__("Select the exact Batch before confirming this tag."));
				}
				if (!(values.qty > 0)) {
					return frappe.msgprint(__("Enter the positive physical quantity in this container."));
				}
				if (values.qty > adoption_context.untagged_qty) {
					return frappe.msgprint(__("This container quantity exceeds the verified untagged ERP stock of {0} {1}.", [
						format_number(adoption_context.untagged_qty), adoption_context.stock_uom,
					]));
				}
				const cycle = values.kanban_cycle ? String(values.kanban_cycle).split(" :: ")[0] : null;
				const response = await frappe.call({
					method: "cfg_kanban.services.stock_adoption.adopt_existing_stock",
					args: { warehouse: warehouse_context.warehouse, item_code: values.item_code,
						batch_no: values.batch_no, qty: values.qty, scan_value: values.scan_value,
						handling_unit_type: values.handling_unit_type, packed_on: values.packed_on,
						expiry_date: values.expiry_date, serial_numbers: values.serial_numbers,
						adoption_reason: values.adoption_reason, kanban_cycle: cycle,
						allocation_reason: values.allocation_reason, event_token: unique_token(),
						operator_session_token: state.token },
					freeze: true, freeze_message: __("Verifying ERP stock and activating physical tag..."),
				});
				dialog.hide();
				const result = response.message || {};
				frappe.msgprint({ title: __("Existing Stock Tagged"), indicator: "green",
					message: __("Tag {0} now represents {1} {2} of existing ERP stock.{3}", [
						e(result.visible_tag_code), format_number(result.adopted_qty), e(result.stock_uom),
						result.kanban_cycle ? ` ${__("Reserved for Cycle")}: ${e(result.kanban_cycle)}.` : "",
					]) });
				await refresh_list(); focus_scanner();
			},
		});
		dialog.show();
	}

	async function refresh_existing_stock_context(dialog, warehouse_context, callback, options = {}) {
		const item_code = dialog.get_value("item_code");
		if (!item_code) {
			if (callback) callback(null);
			return null;
		}
		if (callback) callback(null);
		dialog.get_field("balance").$wrapper.html(`<div class="text-muted">${__("Checking live ERP and tagged balances...")}</div>`);
		try {
			const response = await frappe.call({
				method: "cfg_kanban.services.stock_adoption.get_existing_stock_adoption_context",
				args: { warehouse: warehouse_context.warehouse, item_code,
					batch_no: dialog.get_value("batch_no"), operator_session_token: state.token },
			});
			const context = response.message || {};
			if (callback) callback(context);
			const e = frappe.utils.escape_html;
			const field = dialog.get_field("balance");
			field.$wrapper.html(context.batch_required && !context.batch_no ?
				`<div class="alert alert-warning">${__("Select the exact Batch before entering a quantity.")}</div>` :
				`<div class="alert ${context.tagged_excess_qty ? "alert-danger" : "alert-info"}">
					${__("ERP Actual Stock")}: <strong>${format_number(context.erp_qty)} ${e(context.stock_uom)}</strong><br>
					${__("Already Active under Tags")}: <strong>${format_number(context.active_tagged_qty)} ${e(context.stock_uom)}</strong><br>
					${__("Available for New Tagging")}: <strong>${format_number(context.untagged_qty)} ${e(context.stock_uom)}</strong>
					${context.tagged_excess_qty ? `<br><strong>${__("Stop: active tags exceed ERP stock by {0}.", [format_number(context.tagged_excess_qty)])}</strong>` : ""}
				</div>`);
			if (dialog.get_field("serial_numbers")) dialog.set_df_property("serial_numbers", "hidden", !context.serial_controlled);
			if (dialog.get_field("kanban_cycle")) {
				const options = [""].concat((context.eligible_cycles || []).map((row) =>
					`${row.name} :: ${row.remaining_qty} ${row.stock_uom} ${__("remaining")} :: ${row.status}`));
				dialog.set_df_property("kanban_cycle", "options", options.join("\n"));
				dialog.refresh_field("kanban_cycle");
			}
			return context;
		} catch (error) {
			if (callback) callback(null);
			const message = server_error_message(error, __("ERP stock balance could not be verified."));
			dialog.get_field("balance").$wrapper.html(`<div class="alert alert-danger">${frappe.utils.escape_html(message)}</div>`);
			if (options.show_error) frappe.msgprint(message);
			return null;
		}
	}

	function supplier_receipt_dialog(row, override) {
		const e = frappe.utils.escape_html;
		const dialog = new frappe.ui.Dialog({
			title: __("Receive Supplier Delivery"), size: "large", fields: [
				{ fieldname: "summary", fieldtype: "HTML", options: `<div class="alert alert-info">
					<strong>${e(row.item_code)}</strong> · ${e(row.purchase_order)} · ${e(row.supplier)}<br>
					${__("Outstanding")}: ${format_number(row.outstanding_qty)} ${e(row.purchase_uom)}
					(${format_number(row.outstanding_stock_qty)} ${e(row.stock_uom)})<br>
					${__("Receiving Warehouse")}: ${e(row.warehouse)}${override ? `<br><strong>${__("Supervisor cardless selection")}</strong>` : ""}
				</div>` },
				{ fieldname: "supplier_delivery_note", label: __("Supplier Delivery Note"), fieldtype: "Data" },
				{ fieldname: "delivered_qty", label: __("Delivered Qty ({0})", [row.purchase_uom]), fieldtype: "Float", reqd: 1, default: row.outstanding_qty },
				{ fieldname: "accepted_qty", label: __("Accepted Qty ({0})", [row.purchase_uom]), fieldtype: "Float", reqd: 1, default: row.outstanding_qty },
				{ fieldname: "rejected_qty", label: __("Rejected Qty ({0})", [row.purchase_uom]), fieldtype: "Float", default: 0 },
				...(override ? [{ fieldname: "override_reason", label: __("Why is the original Purchase Kanban card unavailable?"), fieldtype: "Small Text", reqd: 1 }] : []),
				{ fieldname: "confirmation", label: __("I checked the supplier, item, warehouse and physical quantities"), fieldtype: "Check", reqd: 1 },
			],
			primary_action_label: __("Confirm Supplier Receipt"),
			primary_action: async (values) => {
				const response = await frappe.call({
					method: "cfg_kanban.api.logistics.receive_supplier_purchase",
					args: { cycle_name: row.cycle, delivered_qty: values.delivered_qty,
						accepted_qty: values.accepted_qty, rejected_qty: values.rejected_qty,
						supplier_delivery_note: values.supplier_delivery_note,
						cardless_override: override ? 1 : 0, override_reason: values.override_reason,
						event_token: unique_token(), operator_session_token: state.token },
					freeze: true, freeze_message: __("Creating controlled Purchase Receipt..."),
				});
				dialog.hide();
				const result = response.message || {};
				if (result.docstatus === 1) {
					if ((result.rejected_qty || 0) > 0) {
						frappe.show_alert({ message: __("Purchase Receipt submitted with {0} rejected. Keep it in the configured Rejected Warehouse; supervisor disposition is now open.", [result.rejected_qty]), indicator: "orange" }, 12);
					} else {
						frappe.show_alert({ message: __("Purchase Receipt submitted"), indicator: "green" }, 8);
					}
					open_supplier_tagging(result.purchase_receipt);
				} else {
					frappe.msgprint({ title: __("ERP Completion Required"), indicator: "orange",
						message: __("Draft Purchase Receipt {0} was created. Complete its Batch, Serial, Quality Inspection, or approval requirements before stock and physical tags are released.", [result.purchase_receipt]),
						primary_action: { label: __("Open Purchase Receipt"), action: () => frappe.set_route("Form", "Purchase Receipt", result.purchase_receipt) } });
				}
				state.lookup = null; render_lookup(); focus_scanner();
			},
		});
		dialog.show();
	}

	async function open_supplier_tagging(purchase_receipt) {
		const response = await frappe.call({
			method: "cfg_kanban.api.receiving.get_purchase_receipt_trace_plan",
			args: { purchase_receipt, operator_session_token: state.token },
		});
		const plan = response.message || {}; const rows = (plan.rows || []).filter((row) => row.tagging_ready);
		if (!rows.length) return frappe.msgprint({ title: __("Receipt Completed"), indicator: "green",
			message: __("ERP stock is received. No receipt row is currently ready or required for physical tag activation.") });
		const options = rows.map((row) => `${row.row_name} :: ${row.item_code} :: ${row.remaining_stock_qty} ${row.stock_uom}`);
		const dialog = new frappe.ui.Dialog({ title: __("Activate Received Stock Tag"), fields: [
			{ fieldname: "item_row", label: __("Receipt Item"), fieldtype: "Select", options: options.join("\n"), reqd: 1, default: options[0] },
			{ fieldname: "qty", label: __("Quantity in Stock UOM"), fieldtype: "Float", reqd: 1, default: rows[0].remaining_stock_qty },
			{ fieldname: "scan_value", label: __("Preprinted Main Tag"), fieldtype: "Data", reqd: 1 },
			{ fieldname: "camera_tag", label: __("Scan Tag with Camera"), fieldtype: "Button",
				click: () => camera_value((value) => dialog.set_value("scan_value", value)) },
			{ fieldname: "handling_unit_type", label: __("Handling Unit Type"), fieldtype: "Select", options: "Pallet\nMesh\nTote\nContainer\nReusable Box\nOther", default: "Container", reqd: 1 },
			{ fieldname: "confirmed", label: __("I checked the receipt row, tag and physical quantity"), fieldtype: "Check", reqd: 1 },
		], primary_action_label: __("Activate Tag"), primary_action: async (values) => {
			const item_row = String(values.item_row).split(" :: ")[0];
			await frappe.call({ method: "cfg_kanban.api.receiving.activate_purchase_receipt_tag", args: {
				purchase_receipt, item_row, scan_value: values.scan_value, qty: values.qty,
				handling_unit_type: values.handling_unit_type, operator_session_token: state.token,
			}, freeze: true, freeze_message: __("Activating received-material tag...") });
			dialog.hide(); frappe.show_alert({ message: __("Received-material tag activated"), indicator: "green" }, 8);
			open_supplier_tagging(purchase_receipt);
		} });
		dialog.show();
	}

	async function open_stock_retagging_dialog(mode) {
		if (!state.lookup?.handling_unit || !state.lookup.can_retag) return;
		const unit = state.lookup.handling_unit;
		const is_split = mode === "split";
		const plan_method = is_split ?
			"cfg_kanban.services.tag_to_tag_transfer.get_stock_tag_split_plan" :
			"cfg_kanban.services.tag_to_tag_transfer.get_tag_to_tag_transfer_plan";
		const response = await frappe.call({
			method: plan_method,
			args: { source_handling_unit: unit.name, operator_session_token: state.token },
		});
		const plan = response.message || {};
		const allowed = is_split ? plan.can_split : plan.can_transfer;
		if (!allowed) {
			frappe.msgprint({ title: is_split ? __("Stock Tag Split Not Available") : __("Tag Transfer Not Available"),
				message: plan.blocked_reason, indicator: "orange" });
			return;
		}
		const event_token = unique_token();
		const e = frappe.utils.escape_html;
		const dialog = new frappe.ui.Dialog({
			title: is_split ? __("Split Quantity to New Tag") : __("Move Quantity to Active Tag"),
			fields: [
				{ fieldname: "summary", fieldtype: "HTML", options: `<div class="alert alert-info">
					<strong>${e(plan.source_tag)}</strong> · ${e(plan.item_code)} · ${format_number(plan.available_qty)} ${e(plan.stock_uom)}<br>
					${e(plan.company)} · ${e(plan.warehouse)}<br><small>${is_split ?
						__("Destination must be a new unused main Stock Tag.") :
						__("Destination must be an active tag with matching stock and process context.")}</small></div>` },
				{ fieldname: "qty", label: __("Quantity Moving"), fieldtype: "Float", reqd: 1 },
				{ fieldname: "reason", label: __("Physical Movement Reason"), fieldtype: "Small Text", reqd: 1 },
				{ fieldname: "destination_scan_value", label: is_split ? __("New Unused Destination Tag") : __("Active Destination Tag"),
					fieldtype: "Data", reqd: 1 },
				{ fieldname: "camera_destination", label: __("Scan Destination with Camera"), fieldtype: "Button",
					click: () => camera_value((value) => dialog.set_value("destination_scan_value", value)) },
			],
			primary_action_label: __("Review Retagging"),
			primary_action: (values) => stock_retagging_review(
				dialog, plan, values, event_token, is_split
			),
		});
		dialog.show();
	}

	function stock_retagging_review(source_dialog, plan, values, event_token, is_split) {
		const e = frappe.utils.escape_html;
		let review;
		review = new frappe.ui.Dialog({
			title: __("Confirm Physical Stock Retagging"),
			fields: [
				{ fieldname: "summary", fieldtype: "HTML", options: `<div class="alert alert-warning">
					${__("Action")}: <strong>${is_split ? __("Split to new tag") : __("Move to active tag")}</strong><br>
					${__("Source")}: <strong>${e(plan.source_tag)}</strong><br>
					${__("Destination")}: <strong>${e(values.destination_scan_value)}</strong><br>
					${__("Quantity")}: <strong>${format_number(values.qty)} ${e(plan.stock_uom)}</strong><br>
					${__("Warehouse")}: ${e(plan.warehouse)}<br>${__("Reason")}: ${e(values.reason)}
				</div>` },
				{ fieldname: "confirmed", label: __("I physically checked both tags and the moved quantity"),
					fieldtype: "Check", reqd: 1, change: () => {
						if (review.get_value("confirmed")) review.enable_primary_action();
						else review.disable_primary_action();
					} },
			],
			primary_action_label: __("Confirm Retagging"),
			primary_action: async () => {
				review.disable_primary_action();
				try {
					const method = is_split ?
						"cfg_kanban.services.tag_to_tag_transfer.split_to_unused_tag" :
						"cfg_kanban.services.tag_to_tag_transfer.transfer_between_active_tags";
					const response = await frappe.call({ method, args: {
						source_handling_unit: plan.source_handling_unit,
						destination_scan_value: values.destination_scan_value,
						qty: values.qty,
						reason: values.reason,
						event_token,
						operator_session_token: state.token,
					}, freeze: true, freeze_message: __("Posting balanced retagging ledger...") });
					review.hide(); source_dialog.hide();
					const result = response.message || {};
					frappe.show_alert({ message: __("Source {0}: {1}; destination {2}: {3} {4}", [
						result.source.visible_code, format_number(result.source.current_qty),
						result.destination.visible_code, format_number(result.destination.current_qty),
						result.stock_uom,
					]), indicator: result.idempotent_replay ? "blue" : "green" }, 10);
					await lookup_tag(plan.source_tag);
				} finally {
					review.enable_primary_action();
				}
			},
		});
		review.show();
		review.disable_primary_action();
	}

	function render_customer_site(site) {
		const e = frappe.utils.escape_html;
		const warehouses = site.vehicle_warehouses || [];
		const start_action = site.can_start_delivery && warehouses.length ?
			`<button class="btn btn-primary start-delivery">${__("Start Customer Delivery")}</button>` : "";
		const return_action = site.can_start_return ?
			`<button class="btn btn-warning start-qc-return">${__("Customer Return for QC")}</button>` : "";
		const warning = !site.can_start_delivery ?
			__("The active operator is not assigned to Customer Delivery.") :
			(!warehouses.length ? __("No active Vehicle Warehouse is configured for this selling Company.") : "");
		$lookup.html(`<div class="frappe-card cfg-logistics-tag-status">
			<div class="cfg-logistics-tag-head"><div><small>${__("Customer Site identified")}</small>
				<h3>${e(site.site_name)}</h3><strong>${e(site.site_code)}</strong></div>
				<div>${start_action}${return_action}<button class="btn btn-default close-lookup">${__("Close")}</button></div></div>
			<div class="cfg-logistics-tag-grid">
				<div><small>${__("Selling Company")}</small><strong>${e(site.selling_company)}</strong></div>
				<div><small>${__("Customer")}</small><strong>${e(site.customer)}</strong></div>
				<div><small>${__("Delivery Address")}</small><strong>${e(site.customer_address)}</strong></div>
				<div><small>${__("Route")}</small><strong>${e(site.route_reference || __("Not assigned"))}</strong></div>
				<div><small>${__("Proof Policy")}</small><strong>${e(site.proof_policy)}</strong></div>
				<div><small>${__("Available Vehicle Warehouses")}</small><strong>${warehouses.length}</strong></div>
			</div>
			${warning ? `<div class="alert alert-warning mt-3 mb-0">${e(warning)}</div>` :
				`<div class="alert alert-info mt-3 mb-0">${__("Customer, address, Company, price policy and proof policy will be locked into the new Delivery Session.")}</div>`}
		</div>`);
		$lookup.find(".close-lookup").on("click", () => { state.lookup = null; render_lookup(); focus_scanner(); });
		$lookup.find(".start-delivery").on("click", () => start_delivery_dialog(site));
		$lookup.find(".start-qc-return").on("click", () => open_qc_return_intake(site));
	}

	async function open_qc_return_intake(site) {
		const response = await frappe.call({
			method: "cfg_kanban.services.customer_returns.get_return_intake_context",
			args: { customer_scan: site.site_code, operator_session_token: state.token },
		});
		const context = response.message;
		const dialog = new frappe.ui.Dialog({
			title: __("Temporary Return Note: {0}", [context.site_name]), size: "extra-large",
			fields: [
				{ fieldname: "warning", fieldtype: "HTML", options: `<div class="alert alert-warning"><strong>${__("NOT A TAX CREDIT NOTE OR E-INVOICE")}</strong><br>${__("This note records physical return custody for QC only. It does not add available stock or approve customer credit.")}</div>` },
				{ fieldname: "customer_return_reason", label: __("Customer Return Reason"), fieldtype: "Small Text", reqd: 1 },
				{ fieldname: "customer_acknowledgement_name", label: __("Customer Representative (Optional)"), fieldtype: "Data",
					description: __("Record the name of the customer representative acknowledging physical handover. This is not credit approval.") },
				{ fieldname: "inspection_location", label: __("Inspection Custody Location"), fieldtype: "Data", read_only: 1, default: context.inspection_location },
				{ fieldname: "lines", label: __("Physical Items Received from Customer"), fieldtype: "Table",
					cannot_add_rows: false, cannot_delete_rows: false, in_place_edit: true,
					fields: [
						{ fieldname: "original_visible_code", label: __("Stock Tag / Reference"), fieldtype: "Data", in_list_view: 1, columns: 2 },
						{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item", reqd: 1, in_list_view: 1, columns: 2 },
						{ fieldname: "batch_no", label: __("Batch"), fieldtype: "Link", options: "Batch", in_list_view: 1, columns: 2 },
						{ fieldname: "expiry_date", label: __("Expiry"), fieldtype: "Date", in_list_view: 1, columns: 1 },
						{ fieldname: "claimed_qty", label: __("Physical Qty"), fieldtype: "Float", reqd: 1, in_list_view: 1, columns: 1 },
						{ fieldname: "condition", label: __("Reported Condition"), fieldtype: "Select", options: "Unknown\nGood / Unwanted\nDamaged\nExpired\nPest or Contamination\nCustomer Handling Damage\nWrong Item or Quantity\nOther", default: "Unknown", in_list_view: 1, columns: 2 },
						{ fieldname: "details", label: __("Details"), fieldtype: "Small Text", in_list_view: 1, columns: 2 },
					] },
			],
			primary_action_label: __("Issue Temporary Return Note"),
			primary_action: async (values) => {
				const rows = values.lines || dialog.fields_dict.lines.df.data || [];
				if (!rows.length) return frappe.msgprint(__("Add at least one returned Item."));
				const created = await frappe.call({
					method: "cfg_kanban.services.customer_returns.create_qc_return_case",
					args: { customer_scan: site.site_code, customer_return_reason: values.customer_return_reason,
						customer_acknowledgement_name: values.customer_acknowledgement_name,
						lines: JSON.stringify(rows), event_token: unique_token(), operator_session_token: state.token },
					freeze: true, freeze_message: __("Issuing controlled Temporary Return Note..."),
				});
				dialog.hide(); state.lookup = { return_case: created.message };
				render_lookup(); await refresh_list();
			},
		});
		dialog.show();
	}

	function start_delivery_dialog(site) {
		const options = (site.vehicle_warehouses || []).map((row) =>
			`${row.name} :: ${row.vehicle_reference}`).join("\n");
		if (!options) return frappe.msgprint(__("No Vehicle Warehouse is configured for this Company."));
		const dialog = new frappe.ui.Dialog({
			title: __("Start Delivery: {0}", [site.site_name]),
			fields: [
				{ fieldname: "site", label: __("Customer Site"), fieldtype: "Data", read_only: 1,
					default: `${site.site_code} · ${site.customer} · ${site.customer_address}` },
				{ fieldname: "vehicle_warehouse", label: __("Selling-company Lorry Warehouse"),
					fieldtype: "Select", options, reqd: 1,
					description: __("Choose the logical Warehouse for the physical lorry currently carrying this Company's stock.") },
			],
			primary_action_label: __("Lock Customer and Vehicle"),
			primary_action: async (values) => {
				const source_warehouse = String(values.vehicle_warehouse || "").split(" :: ")[0];
				const response = await frappe.call({
					method: "cfg_kanban.services.customer_delivery.start_delivery_session",
					args: { customer_scan: site.site_code, source_warehouse,
						event_token: unique_token(), operator_session_token: state.token },
					freeze: true, freeze_message: __("Starting Customer Delivery Session..."),
				});
				dialog.hide();
				state.lookup = { delivery_session: response.message };
				render_lookup(); await refresh_list(); focus_scanner();
			},
		});
		dialog.show();
	}

	function render_delivery_session(delivery) {
		const e = frappe.utils.escape_html;
		const allocations = delivery.allocations || [];
		const active_allocations = allocations.filter((row) => ["Reserved", "Delivery Pending"].includes(row.state));
		const active_qty = active_allocations.reduce((total, row) => total + Number(row.allocated_qty || 0), 0);
		const rendered_containers = new Set();
		const allocation_rows = allocations.map((row) => {
			const release_group = row.container_visible_code || row.name;
			const show_release = !rendered_containers.has(release_group);
			rendered_containers.add(release_group);
			return `<div class="cfg-logistics-line">
			<div><strong>${e(row.visible_code)}</strong><small>${e(row.item_code)} · ${e(row.batch_no || __("No Batch"))}
				${row.container_visible_code ? ` · ${__("Container")}: ${e(row.container_visible_code)}` : ""}</small></div>
			<div><strong>${format_number(row.allocated_qty)} ${e(row.stock_uom)}</strong><small>${e(row.state)}</small></div>
			${show_release && ["Reserved", "Delivery Pending"].includes(row.state) && !row.delivery_note ? `<button class="btn btn-xs btn-danger release-allocation" data-name="${e(row.name)}">${row.container_visible_code ? __("Release Container") : __("Release")}</button>` : ""}
		</div>`;
		}).join("");
		let mode_notice = `<div class="alert alert-info mt-3"><strong>${__("Customer stock reservation")}</strong> · ${__("Start allocation scanning, then scan a complete Stock Tag or reusable container in this lorry Warehouse.")}</div>`;
		if (state.scan_mode === "delivery") mode_notice = `<div class="alert alert-warning mt-3"><strong>${__("CUSTOMER ALLOCATION SCANNING ARMED")}</strong> · ${e(delivery.name)} · ${__("Scanned stock will be reserved for this customer.")}</div>`;
		const can_scan = ["Customer Identified", "Allocating Stock"].includes(delivery.state);
		const delivery_note = delivery.delivery_note ? `<div class="alert ${delivery.delivery_note_status?.docstatus === 1 ? "alert-success" : delivery.delivery_note_status?.docstatus === 2 ? "alert-danger" : "alert-warning"} mt-3 mb-0">
			<strong>${__("ERPNext Delivery Note")}: ${e(delivery.delivery_note)}</strong> · ${e(delivery.delivery_note_status?.status || __("Unknown"))}
			<button class="btn btn-xs btn-default ml-2 open-customer-dn">${__("Open Delivery Note")}</button></div>` : "";
		const delivery_action = ["Awaiting Confirmation", "Exception"].includes(delivery.state) ?
			`<button class="btn btn-success prepare-customer-dn">${delivery.delivery_note_status?.docstatus === 2 ? __("Create Amended Delivery Note") : __("Create Delivery Note")}</button>` : "";
		const proof_action = delivery.state === "Delivered" ?
			`<button class="btn btn-success capture-delivery-proof">${__("Capture / Close Delivery")}</button>` : "";
		const return_action = ["Delivered", "Closed", "Invoiced"].includes(delivery.state) ?
			`<button class="btn btn-warning start-customer-return">${__("Correct Wrong Delivery Note")}</button>` : "";
		$lookup.html(`<div class="frappe-card cfg-logistics-tag-status">
			<div class="cfg-logistics-tag-head"><div><small>${__("Active Customer Delivery")}</small>
				<h3>${e(delivery.site_name)}</h3><strong>${e(delivery.name)} · ${e(delivery.state)}</strong></div>
				<div>${delivery.state === "Customer Identified" && !active_allocations.length ? `<button class="btn btn-danger cancel-delivery">${__("Cancel Empty Session")}</button>` : ""}
				<button class="btn btn-default close-lookup">${__("Close")}</button></div></div>
			<div class="cfg-logistics-tag-grid">
				<div><small>${__("Customer")}</small><strong>${e(delivery.customer)}</strong></div>
				<div><small>${__("Delivery Address")}</small><strong>${e(delivery.customer_address)}</strong></div>
				<div><small>${__("Selling Company")}</small><strong>${e(delivery.selling_company)}</strong></div>
				<div><small>${__("Physical Vehicle")}</small><strong>${e(delivery.vehicle_reference)}</strong></div>
				<div><small>${__("Lorry Warehouse")}</small><strong>${e(delivery.source_warehouse)}</strong></div>
				<div><small>${__("Proof Policy")}</small><strong>${e(delivery.proof_policy)}</strong></div>
				<div><small>${__("Delivery Note Policy")}</small><strong>${delivery.auto_submit_delivery_note ? __("Auto-submit") : __("Keep Draft for ERP review")}</strong></div>
			</div>
			${mode_notice}
			<div class="cfg-logistics-receipt-progress"><strong>${__("Reserved for this customer")}: ${format_number(active_qty)}</strong>
				<span>${active_allocations.length} ${__("active Stock Tag allocation(s)")}</span></div>
			<div class="cfg-logistics-lines">${allocation_rows || `<div class="text-muted p-3">${__("No stock allocated yet")}</div>`}</div>
			<div class="cfg-logistics-actions">
				${can_scan ? (state.scan_mode === "delivery" ? `<button class="btn btn-warning stop-delivery-scan">${__("Stop Allocation Scanning")}</button>` : `<button class="btn btn-primary arm-delivery">${__("Start Allocation Scanning")}</button>`) : ""}
				${delivery.state === "Allocating Stock" && active_allocations.length && state.scan_mode !== "delivery" ? `<button class="btn btn-success confirm-allocations">${__("Confirm Customer Allocation")}</button>` : ""}
				${delivery_action}
				${proof_action}
				${return_action}
			</div>
			${delivery.state === "Awaiting Confirmation" ? `<div class="alert alert-success mt-3 mb-0">${__("Allocation confirmed. Stock remains reserved until the ERPNext Delivery Note is submitted.")}</div>` : ""}
			${delivery.state === "ERP Document Pending" ? `<div class="alert alert-warning mt-3 mb-0">${__("The Delivery Note is Draft. An authorized ERPNext user must review and submit it; only submission posts Kanban delivery quantities.")}</div>` : ""}
			${delivery.state === "Delivered" ? `<div class="alert alert-warning mt-3 mb-0">${__("ERPNext confirmed the stock delivery. Record the customer proof required by this site before closing the session.")}</div>` : ""}
			${delivery.state === "Closed" ? `<div class="alert alert-success mt-3 mb-0">${__("Delivery closed")} · ${e(delivery.proof_disposition || __("No Proof Recorded"))}${delivery.delivery_proof ? ` · <button class="btn btn-xs btn-default open-delivery-proof">${__("Open Proof")}</button>` : ""}</div>` : ""}
			${delivery.exception ? `<div class="alert alert-danger mt-3 mb-0"><strong>${__("Supervisor attention required")}</strong> · ${e(delivery.exception)}</div>` : ""}
			${delivery_note}
		</div>`);
		$lookup.find(".close-lookup").on("click", () => { state.scan_mode = "lookup"; state.lookup = null; render_lookup(); update_scanner_state(); focus_scanner(); });
		$lookup.find(".arm-delivery").on("click", () => { state.scan_mode = "delivery"; render_delivery_session(delivery); update_scanner_state(); focus_scanner(); });
		$lookup.find(".stop-delivery-scan").on("click", () => { state.scan_mode = "lookup"; render_delivery_session(delivery); update_scanner_state(); focus_scanner(); });
		$lookup.find(".release-allocation").on("click", function () { release_delivery_allocation($(this).data("name")); });
		$lookup.find(".confirm-allocations").on("click", () => confirm_delivery_allocations(delivery));
		$lookup.find(".prepare-customer-dn").on("click", () => prepare_customer_delivery_note(delivery));
		$lookup.find(".capture-delivery-proof").on("click", () => open_delivery_proof(delivery));
		$lookup.find(".start-customer-return").on("click", () => open_customer_return(delivery));
		$lookup.find(".open-delivery-proof").on("click", () => frappe.set_route("Form", "CFG Kanban Delivery Proof", delivery.delivery_proof));
		$lookup.find(".open-customer-dn").on("click", () => frappe.set_route("Form", "Delivery Note", delivery.delivery_note));
		$lookup.find(".cancel-delivery").on("click", () => frappe.prompt([
			{ fieldname: "reason", label: __("Cancellation Reason"), fieldtype: "Small Text", reqd: 1 },
		], async (values) => {
			const response = await frappe.call({
				method: "cfg_kanban.services.customer_delivery.cancel_delivery_session",
				args: { delivery_session: delivery.name, reason: values.reason,
					event_token: unique_token(), operator_session_token: state.token },
				freeze: true, freeze_message: __("Cancelling Delivery Session..."),
			});
			state.lookup = { delivery_session: response.message };
			render_lookup(); await refresh_list();
		}, __("Cancel Empty Delivery Session"), __("Cancel Session")));
	}

	async function open_customer_return(delivery) {
		const response = await frappe.call({
			method: "cfg_kanban.services.customer_returns.get_delivery_correction_candidate",
			args: { delivery_session: delivery.name, operator_session_token: state.token },
			freeze: true, freeze_message: __("Loading submitted Delivery Note quantities..."),
		});
		const candidate = response.message;
		if (!(candidate.lines || []).length) {
			return frappe.msgprint(__("No remaining quantity is available for Delivery Note correction."));
		}
		const dialog = new frappe.ui.Dialog({
			title: __("Correct Wrong Delivery Note: {0}", [candidate.delivery_note]), size: "extra-large",
			fields: [
				{ fieldname: "delivery_context", label: __("Original ERP-confirmed Delivery"), fieldtype: "HTML",
					options: `<div class="alert alert-info"><strong>${frappe.utils.escape_html(candidate.delivery_note)}</strong> · ${frappe.utils.escape_html(candidate.customer)} · ${frappe.utils.escape_html(candidate.site_code)}<br><small>${__("This reverses physical delivery only; it does not create an accounting Credit Note.")}</small></div>${candidate.accounting_attention_required ? `<div class="alert alert-danger"><strong>${__("Accounting attention required")}</strong><br>${__("Submitted Sales Invoice(s):")} ${candidate.linked_sales_invoices.map((name) => frappe.utils.escape_html(name)).join(", ")}. ${__("The Return Delivery Note will remain Draft.")}</div>` : ""}` },
				{ fieldname: "customer_return_reason", label: __("Correction Reason"), fieldtype: "Small Text", reqd: 1 },
				{ fieldname: "correction_return_warehouse", label: __("Stock Returns To"), fieldtype: "Data", read_only: 1, default: candidate.correction_return_warehouse },
				{ fieldname: "lines", label: __("Delivery Note Lines to Reverse"), fieldtype: "Table",
					cannot_add_rows: true, cannot_delete_rows: true, in_place_edit: true, data: candidate.lines,
					fields: [
						{ fieldname: "original_delivery_allocation", fieldtype: "Data", hidden: 1 },
						{ fieldname: "original_visible_code", label: __("Stock Tag"), fieldtype: "Data", read_only: 1, in_list_view: 1, columns: 2 },
						{ fieldname: "item_code", label: __("Item"), fieldtype: "Data", read_only: 1, in_list_view: 1, columns: 2 },
						{ fieldname: "batch_no", label: __("Batch"), fieldtype: "Data", read_only: 1, in_list_view: 1, columns: 1 },
						{ fieldname: "available_to_correct_qty", label: __("Available"), fieldtype: "Float", read_only: 1, in_list_view: 1, columns: 1 },
						{ fieldname: "claimed_qty", label: __("Reverse Qty"), fieldtype: "Float", in_list_view: 1, columns: 1 },
						{ fieldname: "details", label: __("Details"), fieldtype: "Small Text", in_list_view: 1, columns: 3 },
					] },
				{ fieldname: "correction_warning", fieldtype: "HTML", options: `<div class="alert alert-warning"><strong>${__("Physical delivery correction only")}</strong><br>${__("For damaged, expired, or disputed goods, scan the Customer Site and use Customer Return for QC.")}</div>` },
			],
			primary_action_label: __("Create Return Delivery Note"),
			primary_action: async (values) => {
				const rows = (values.lines || dialog.fields_dict.lines.df.data || []).filter((row) => Number(row.claimed_qty || 0) > 0);
				if (!rows.length) return frappe.msgprint(__("Enter a reverse quantity on at least one line."));
				const created = await frappe.call({
					method: "cfg_kanban.services.customer_returns.create_delivery_correction_case",
					args: { delivery_session: delivery.name,
						customer_return_reason: values.customer_return_reason, lines: JSON.stringify(rows),
						event_token: unique_token(), operator_session_token: state.token },
					freeze: true, freeze_message: __("Creating controlled Return Delivery Note..."),
				});
				dialog.hide(); state.lookup = { return_case: created.message };
				render_lookup(); await refresh_list();
				frappe.show_alert({ message: __("Delivery correction recorded"), indicator: "green" });
			},
		});
		dialog.show();
	}

	async function open_return_case(name) {
		const response = await frappe.call({
			method: "cfg_kanban.services.customer_returns.get_return_case",
			args: { return_case: name, operator_session_token: state.token },
		});
		state.lookup = { return_case: response.message }; render_lookup();
	}

	function render_return_case(return_case) {
		const e = frappe.utils.escape_html;
		const rows = (return_case.lines || []).map((row) => `<div class="cfg-logistics-line">
			<div><strong>${e(row.original_visible_code || "-")}</strong><small>${e(row.item_code)} · ${e(row.batch_no || __("No Batch"))} · ${e(row.condition)}</small></div>
			<div><strong>${format_number(row.claimed_qty)} ${e(row.stock_uom)}</strong><small>${__("Received")}: ${format_number(row.received_qty)} · ${__("Accepted")}: ${format_number(row.accepted_qty)} · ${e(row.qc_disposition || __("Pending"))}</small></div>
		</div>`).join("");
		const qc_actions = `${return_case.can_start_qc ? `<button class="btn btn-primary start-return-qc">${__("Receive and Start QC")}</button>` : ""}${return_case.can_complete_qc ? `<button class="btn btn-success complete-return-qc">${__("Complete QC Result")}</button>` : ""}`;
		const evidence_open = return_case.return_flow === "Customer Return for QC" && ["Awaiting QC Receipt", "QC In Progress"].includes(return_case.state);
		const print_url = `/printview?doctype=CFG%20Kanban%20Return%20Case&name=${encodeURIComponent(return_case.name)}&format=CFG%20Temporary%20Return%20Note&no_letterhead=1`;
		$lookup.html(`<div class="frappe-card cfg-logistics-tag-status">
			<div class="cfg-logistics-tag-head"><div><small>${__("Controlled Return Workflow")}</small><h3>${e(return_case.name)}</h3>
			<strong>${e(return_case.site_name)} · ${e(return_case.state)}</strong></div><button class="btn btn-default close-lookup">${__("Close")}</button></div>
			<div class="cfg-logistics-tag-grid">
				<div><small>${__("Workflow")}</small><strong>${e(return_case.return_flow)}</strong></div>
				<div><small>${__("Original Delivery Note")}</small><strong>${e(return_case.original_delivery_note || __("Not required for QC intake"))}</strong></div>
				<div><small>${__("Customer")}</small><strong>${e(return_case.customer)}</strong></div>
				<div><small>${__("Selling Company")}</small><strong>${e(return_case.selling_company)}</strong></div>
				<div><small>${__("Inspection Location")}</small><strong>${e(return_case.inspection_location || "-")}</strong></div>
				<div><small>${__("Customer Acknowledged By")}</small><strong>${e(return_case.customer_acknowledgement_name || __("Not recorded"))}</strong></div>
				<div><small>${__("Return Delivery Note")}</small><strong>${e(return_case.correction_return_delivery_note || __("Not applicable"))}</strong></div>
			</div>
			${return_case.return_flow === "Customer Return for QC" ? `<div class="alert alert-warning mt-3"><strong>${__("NOT A TAX CREDIT NOTE OR ERP STOCK RECEIPT")}</strong> · ${__("QC must finish before a supervisor/accountant selects any accounting source.")}</div>` : `<div class="alert alert-info mt-3"><strong>${__("Physical Delivery Note correction")}</strong> · ${__("Accounting remains a separate ERPNext responsibility.")}</div>`}
			<div class="cfg-logistics-lines">${rows}</div>
			${return_case.return_flow === "Customer Return for QC" ? `<div class="cfg-return-evidence mt-3">
				<h5>${__("Private Return Evidence")}</h5>
				<div class="cfg-return-media text-muted">${__("Loading evidence...")}</div>
				${evidence_open ? `<div class="cfg-logistics-actions mt-2">
					<label class="btn btn-primary mb-0">${__("Take Timestamped Photo")}<input class="cfg-return-camera" type="file" accept="image/*" capture="environment" hidden></label>
					<label class="btn btn-default mb-0">${__("Upload File / PDF")}<input class="cfg-return-file" type="file" accept="image/jpeg,image/png,image/webp,video/mp4,application/pdf" multiple hidden></label>
				</div><div class="cfg-return-media-status mt-2"></div>` : `<div class="text-muted">${__("Evidence is locked because QC is complete.")}</div>`}
			</div>` : ""}
			<div class="cfg-logistics-actions">${qc_actions}<a class="btn btn-default" href="${print_url}" target="_blank">${__("Print Temporary Return Note")}</a><button class="btn btn-default open-return-record">${__("Open Audit Record")}</button></div>
		</div>`);
		$lookup.find(".close-lookup").on("click", () => { state.lookup = null; render_lookup(); focus_scanner(); });
		$lookup.find(".open-return-record").on("click", () => frappe.set_route("Form", "CFG Kanban Return Case", return_case.name));
		$lookup.find(".start-return-qc").on("click", async () => {
			const response = await frappe.call({ method: "cfg_kanban.services.customer_returns.start_qc_inspection",
				args: { return_case: return_case.name, event_token: unique_token(), operator_session_token: state.token },
				freeze: true, freeze_message: __("Starting QC inspection...") });
			state.lookup = { return_case: response.message }; render_lookup(); await refresh_list();
		});
		$lookup.find(".complete-return-qc").on("click", () => complete_return_qc_dialog(return_case));
		if (return_case.return_flow === "Customer Return for QC") bind_return_case_evidence(return_case, evidence_open);
	}

	function bind_return_case_evidence(return_case, evidence_open) {
		const $evidence = $lookup.find(".cfg-return-evidence");
		let rows = [];
		const render_rows = () => {
			const e = frappe.utils.escape_html;
			$evidence.find(".cfg-return-media").html(rows.length ? rows.map((row) =>
				`<div class="cfg-logistics-line" data-media-id="${e(row.media_id)}"><div><strong>${e(row.evidence_kind || "attachment")}</strong><small>${e(row.original_filename)} · ${e(row.capture_timestamp || row.confirmed_at || "")}</small></div><div><button class="btn btn-xs btn-default cfg-open-return-media">${__("Open")}</button>${evidence_open ? ` <button class="btn btn-xs btn-danger cfg-remove-return-media">${__("Remove")}</button>` : ""}</div></div>`
			).join("") : `<div class="text-muted">${__("No return evidence uploaded yet")}</div>`);
			$evidence.find(".cfg-open-return-media").off("click").on("click", async function () {
				const media_id = $(this).closest("[data-media-id]").data("media-id");
				const view = await frappe.call({ method: "cfg_kanban.api.media.create_return_case_view_url", args: {
					return_case: return_case.name, media_id, operator_session_token: state.token,
				} }); window.open(view.message.url, "_blank", "noopener");
			});
			$evidence.find(".cfg-remove-return-media").off("click").on("click", async function () {
				const media_id = $(this).closest("[data-media-id]").data("media-id");
				await frappe.call({ method: "cfg_kanban.api.media.archive_return_case_media", args: {
					return_case: return_case.name, media_id, operator_session_token: state.token,
				} }); rows = rows.filter((row) => row.media_id !== media_id); render_rows();
			});
		};
		const refresh = async () => {
			const response = await frappe.call({ method: "cfg_kanban.api.media.list_return_case_media", args: {
				return_case: return_case.name, operator_session_token: state.token,
			} }); rows = response.message || []; render_rows();
		};
		const upload = async (files, camera = false) => {
			const $status = $evidence.find(".cfg-return-media-status");
			try {
				let location = null; let captured_at = null; let selected = Array.from(files || []);
				if (camera) {
					location = await delivery_geotag();
					const stamp = await frappe.call({ method: "cfg_kanban.api.media.get_return_case_camera_stamp", args: {
						return_case: return_case.name, operator_session_token: state.token,
					} }); captured_at = stamp.message.captured_at;
					selected = [await stamp_delivery_photo(selected[0], captured_at, return_case.name, location,
						"CFG Kanban customer return evidence")];
				}
				for (const file of selected) {
					$status.html(`<div class="alert alert-info">${__("Uploading {0}", [frappe.utils.escape_html(file.name)])}</div>`);
					const auth = await frappe.call({ method: "cfg_kanban.api.media.create_return_case_upload_url", args: {
						return_case: return_case.name, original_filename: file.name, content_type: file.type,
						size_bytes: file.size, idempotency_key: unique_token(), operator_session_token: state.token,
						evidence_kind: camera ? "photo" : "attachment", capture_source: camera ? "timestamped-camera" : "file-upload",
						capture_timestamp: captured_at, latitude: location && location.latitude,
						longitude: location && location.longitude, location_accuracy: location && location.accuracy,
					} });
					const data = auth.message; if (data.already_available) continue;
					const form = new FormData(); Object.entries(data.fields || {}).forEach(([key, value]) => form.append(key, value)); form.append("file", file);
					const result = await fetch(data.url, { method: data.method, body: form });
					if (!result.ok) throw new Error(__("Private upload failed with HTTP {0}", [result.status]));
					await frappe.call({ method: "cfg_kanban.api.media.confirm_return_case_upload", args: {
						return_case: return_case.name, media_id: data.media_id, confirmation_token: data.confirmation_token,
						operator_session_token: state.token,
					} });
				}
				await refresh(); $status.html(`<div class="alert alert-success">${__("Return evidence uploaded")}</div>`);
			} catch (error) { $status.html(`<div class="alert alert-danger">${frappe.utils.escape_html(error.message || __("Upload failed"))}</div>`); }
		};
		$evidence.find(".cfg-return-camera").on("change", function () { if (this.files.length) upload(this.files, true); this.value = ""; });
		$evidence.find(".cfg-return-file").on("change", function () { if (this.files.length) upload(this.files); this.value = ""; });
		refresh();
	}

	function complete_return_qc_dialog(return_case) {
		const data = (return_case.lines || []).map((row) => ({ name: row.name, item_code: row.item_code,
			claimed_qty: row.claimed_qty, received_qty: row.claimed_qty, accepted_qty: 0,
			rejected_qty: row.claimed_qty, qc_disposition: "Hold for Investigation", qc_reason: "" }));
		const dialog = new frappe.ui.Dialog({
			title: __("QC Result: {0}", [return_case.name]), size: "extra-large",
			fields: [
				{ fieldname: "notice", fieldtype: "HTML", options: `<div class="alert alert-info">${__("Accepted + Rejected must equal the physically received quantity. Accepted quantity becomes accounting-pending, not available stock.")}</div>` },
				{ fieldname: "lines", label: __("Inspection Results"), fieldtype: "Table", cannot_add_rows: true, cannot_delete_rows: true, in_place_edit: true, data,
					fields: [
						{ fieldname: "name", fieldtype: "Data", hidden: 1 },
						{ fieldname: "item_code", label: __("Item"), fieldtype: "Data", read_only: 1, in_list_view: 1, columns: 2 },
						{ fieldname: "claimed_qty", label: __("Intake"), fieldtype: "Float", read_only: 1, in_list_view: 1, columns: 1 },
						{ fieldname: "received_qty", label: __("Received"), fieldtype: "Float", in_list_view: 1, columns: 1 },
						{ fieldname: "accepted_qty", label: __("Accepted"), fieldtype: "Float", in_list_view: 1, columns: 1 },
						{ fieldname: "rejected_qty", label: __("Rejected"), fieldtype: "Float", in_list_view: 1, columns: 1 },
						{ fieldname: "qc_disposition", label: __("Disposition"), fieldtype: "Select", options: "Accept for Credit\nReject Customer Claim\nAccept for Rework\nAccept for Disposal\nHold for Investigation", reqd: 1, in_list_view: 1, columns: 3 },
						{ fieldname: "qc_reason", label: __("Reason"), fieldtype: "Small Text", in_list_view: 1, columns: 3 },
					] },
				{ fieldname: "qc_notes", label: __("Overall QC Notes"), fieldtype: "Small Text" },
			],
			primary_action_label: __("Complete QC and Hand Off to Accounting"),
			primary_action: async (values) => {
				const response = await frappe.call({ method: "cfg_kanban.services.customer_returns.complete_qc_inspection",
					args: { return_case: return_case.name, lines: JSON.stringify(values.lines || dialog.fields_dict.lines.df.data || []),
						qc_notes: values.qc_notes, event_token: unique_token(), operator_session_token: state.token },
					freeze: true, freeze_message: __("Saving controlled QC disposition...") });
				dialog.hide(); state.lookup = { return_case: response.message }; render_lookup(); await refresh_list();
			},
		});
		dialog.show();
	}

	async function open_delivery_proof(delivery) {
		const response = await frappe.call({
			method: "cfg_kanban.services.delivery_proof.get_or_create_delivery_proof",
			args: { delivery_session: delivery.name, operator_session_token: state.token },
			freeze: true, freeze_message: __("Opening delivery proof..."),
		});
		const proof = response.message;
		if (proof.state === "Submitted") {
			frappe.set_route("Form", "CFG Kanban Delivery Proof", proof.name); return;
		}
		const dialog = new frappe.ui.Dialog({
			title: __("Customer Delivery Proof: {0}", [proof.site_name]),
			size: "large",
			fields: [
				{ fieldname: "policy", label: __("Proof Policy"), fieldtype: "Data", read_only: 1,
					default: proof.proof_policy },
				{ fieldname: "disposition", label: __("Delivery Disposition"), fieldtype: "Select",
					options: (proof.allowed_dispositions || []).join("\n"), reqd: 1,
					default: (proof.allowed_dispositions || [])[0] },
				{ fieldname: "recipient_name", label: __("Recipient Name"), fieldtype: "Data" },
				{ fieldname: "unattended_reason", label: __("Unattended Delivery Reason"), fieldtype: "Small Text" },
				{ fieldname: "notes", label: __("Delivery Notes"), fieldtype: "Small Text" },
				{ fieldname: "evidence", label: __("Private Delivery Evidence"), fieldtype: "HTML",
					options: `<div class="cfg-delivery-proof-tools">
					<label class="btn btn-primary cfg-proof-camera">${__("Take Delivery Photo")}<input type="file" accept="image/*" capture="environment" hidden></label>
					<label class="btn btn-default cfg-proof-file">${__("Upload File")}<input type="file" accept="image/*,application/pdf,video/mp4" multiple hidden></label>
					<div class="cfg-proof-status mt-2"></div><div class="cfg-proof-media mt-2"></div></div>` },
				{ fieldname: "signature", label: __("Recipient Signature"), fieldtype: "HTML",
					options: `<div class="cfg-signature-wrap"><canvas class="cfg-signature-pad" width="700" height="220" style="width:100%;height:180px;border:1px solid #aaa;background:#fff;touch-action:none"></canvas>
					<div class="mt-2"><button type="button" class="btn btn-default cfg-clear-signature">${__("Clear")}</button>
					<button type="button" class="btn btn-primary cfg-save-signature">${__("Save Signature")}</button></div></div>` },
			],
			primary_action_label: __("Submit Proof and Close"),
			primary_action: async (values) => {
				let location = null;
				if (proof.require_gps && values.disposition !== "No Proof Recorded") {
					location = await delivery_geotag();
				}
				await frappe.call({
					method: "cfg_kanban.services.delivery_proof.submit_delivery_proof",
					args: { proof_name: proof.name, disposition: values.disposition,
						recipient_name: values.recipient_name, unattended_reason: values.unattended_reason,
						notes: values.notes, latitude: location && location.latitude,
						longitude: location && location.longitude, location_accuracy: location && location.accuracy,
						event_token: unique_token(), operator_session_token: state.token },
					freeze: true, freeze_message: __("Submitting delivery proof..."),
				});
				dialog.hide();
				state.lookup = { delivery_session: await fetch_delivery(delivery.name) };
				render_lookup(); await refresh_list();
				frappe.show_alert({ message: __("Delivery proof submitted and session closed"), indicator: "green" });
			},
		});
		dialog.show();
		bind_delivery_proof_evidence(dialog, proof);
	}

	async function fetch_delivery(name) {
		const response = await frappe.call({
			method: "cfg_kanban.services.customer_delivery.get_delivery_session",
			args: { delivery_session: name, operator_session_token: state.token },
		});
		return response.message;
	}

	function bind_delivery_proof_evidence(dialog, proof) {
		const $evidence = dialog.get_field("evidence").$wrapper;
		let rows = proof.media || [];
		const render_rows = () => {
			const e = frappe.utils.escape_html;
			$evidence.find(".cfg-proof-media").html(rows.length ? rows.map((row) =>
				`<div class="cfg-logistics-line" data-media-id="${e(row.media_id)}"><div><strong>${e(row.evidence_kind || "attachment")}</strong><small>${e(row.original_filename)}</small></div><div><button type="button" class="btn btn-xs btn-default cfg-view-proof">${__("Open")}</button> <button type="button" class="btn btn-xs btn-danger cfg-remove-proof">${__("Remove")}</button></div></div>`
			).join("") : `<div class="text-muted">${__("No proof media uploaded yet")}</div>`);
			$evidence.find(".cfg-view-proof").off("click").on("click", async function () {
				const media_id = $(this).closest("[data-media-id]").data("media-id");
				const view = await frappe.call({ method: "cfg_kanban.api.media.create_delivery_proof_view_url", args: {
					proof_name: proof.name, media_id, operator_session_token: state.token,
				} }); window.open(view.message.url, "_blank", "noopener");
			});
			$evidence.find(".cfg-remove-proof").off("click").on("click", async function () {
				const media_id = $(this).closest("[data-media-id]").data("media-id");
				await frappe.call({ method: "cfg_kanban.api.media.archive_delivery_proof_media", args: {
					proof_name: proof.name, media_id, operator_session_token: state.token,
				} }); rows = rows.filter((row) => row.media_id !== media_id); render_rows();
			});
		};
		const refresh = async () => {
			const response = await frappe.call({ method: "cfg_kanban.api.media.list_delivery_proof_media", args: {
				proof_name: proof.name, operator_session_token: state.token,
			} }); rows = response.message || []; render_rows();
		};
		const upload = async (files, kind, camera = false) => {
			const $status = $evidence.find(".cfg-proof-status");
			try {
				let location = null; let captured_at = null; let selected = Array.from(files || []);
				if (camera) {
					location = await delivery_geotag();
					const stamp = await frappe.call({ method: "cfg_kanban.api.media.get_delivery_proof_camera_stamp", args: {
						proof_name: proof.name, operator_session_token: state.token,
					} }); captured_at = stamp.message.captured_at;
					selected = [await stamp_delivery_photo(selected[0], captured_at, proof.name, location,
						"CFG Kanban customer delivery proof")];
				}
				for (const file of selected) {
					$status.html(`<div class="alert alert-info">${__("Uploading {0}", [frappe.utils.escape_html(file.name)])}</div>`);
					const auth = await frappe.call({ method: "cfg_kanban.api.media.create_delivery_proof_upload_url", args: {
						proof_name: proof.name, original_filename: file.name, content_type: file.type,
						size_bytes: file.size, idempotency_key: unique_token(), operator_session_token: state.token,
						evidence_kind: kind, capture_source: camera ? "timestamped-camera" : (kind === "signature" ? "signature-pad" : "file-upload"),
						capture_timestamp: captured_at, latitude: location && location.latitude,
						longitude: location && location.longitude, location_accuracy: location && location.accuracy,
					} });
					const data = auth.message; if (data.already_available) continue;
					const form = new FormData(); Object.entries(data.fields || {}).forEach(([key, value]) => form.append(key, value)); form.append("file", file);
					const result = await fetch(data.url, { method: data.method, body: form });
					if (!result.ok) throw new Error(__("Private upload failed with HTTP {0}", [result.status]));
					await frappe.call({ method: "cfg_kanban.api.media.confirm_delivery_proof_upload", args: {
						proof_name: proof.name, media_id: data.media_id, confirmation_token: data.confirmation_token,
						operator_session_token: state.token,
					} });
				}
				await refresh(); $status.html(`<div class="alert alert-success">${__("Evidence uploaded")}</div>`);
			} catch (error) { $status.html(`<div class="alert alert-danger">${frappe.utils.escape_html(error.message || __("Upload failed"))}</div>`); }
		};
		$evidence.find(".cfg-proof-camera input").on("change", function () { if (this.files.length) upload(this.files, "photo", true); this.value = ""; });
		$evidence.find(".cfg-proof-file input").on("change", function () { if (this.files.length) upload(this.files, "attachment"); this.value = ""; });
		bind_signature_pad(dialog, (file) => upload([file], "signature"));
		render_rows();
	}

	function bind_signature_pad(dialog, save_signature) {
		const canvas = dialog.get_field("signature").$wrapper.find("canvas")[0];
		const ctx = canvas.getContext("2d"); ctx.strokeStyle = "#111"; ctx.lineWidth = 3; ctx.lineCap = "round";
		let drawing = false; let has_ink = false;
		const point = (event) => { const rect = canvas.getBoundingClientRect(); return { x: (event.clientX - rect.left) * canvas.width / rect.width, y: (event.clientY - rect.top) * canvas.height / rect.height }; };
		canvas.addEventListener("pointerdown", (event) => { drawing = true; const p = point(event); ctx.beginPath(); ctx.moveTo(p.x, p.y); canvas.setPointerCapture(event.pointerId); });
		canvas.addEventListener("pointermove", (event) => { if (!drawing) return; const p = point(event); ctx.lineTo(p.x, p.y); ctx.stroke(); has_ink = true; });
		canvas.addEventListener("pointerup", () => { drawing = false; });
		dialog.get_field("signature").$wrapper.find(".cfg-clear-signature").on("click", () => { ctx.clearRect(0, 0, canvas.width, canvas.height); has_ink = false; });
		dialog.get_field("signature").$wrapper.find(".cfg-save-signature").on("click", () => {
			if (!has_ink) return frappe.msgprint(__("Ask the recipient to sign before saving."));
			canvas.toBlob((blob) => {
			if (blob) save_signature(new File([blob], `recipient-signature-${Date.now()}.png`, { type: "image/png" }));
		}, "image/png");
		});
	}

	function delivery_geotag() {
		if (!navigator.geolocation) return Promise.reject(new Error(__("This device does not provide geolocation.")));
		return new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(
			(position) => resolve({ latitude: position.coords.latitude, longitude: position.coords.longitude, accuracy: position.coords.accuracy }),
			() => reject(new Error(__("Location permission is required for delivery proof."))),
			{ enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
		));
	}

	async function stamp_delivery_photo(file, captured_at, reference_name, location, evidence_label) {
		const bitmap = window.createImageBitmap ? await createImageBitmap(file) : await new Promise((resolve, reject) => {
			const image = new Image(); const url = URL.createObjectURL(file);
			image.onload = () => { URL.revokeObjectURL(url); resolve(image); }; image.onerror = reject; image.src = url;
		});
		const canvas = document.createElement("canvas"); canvas.width = bitmap.width; canvas.height = bitmap.height;
		const ctx = canvas.getContext("2d"); ctx.drawImage(bitmap, 0, 0);
		const font = Math.max(22, Math.round(canvas.width * 0.025)); ctx.fillStyle = "rgba(0,0,0,.72)"; ctx.fillRect(0, canvas.height - font * 3.2, canvas.width, font * 3.2);
		ctx.fillStyle = "#fff"; ctx.font = `bold ${font}px Arial`; ctx.fillText(`${captured_at} · ${reference_name}`, font * .6, canvas.height - font * 1.45);
		ctx.font = `${Math.round(font * .65)}px Arial`; ctx.fillText(`GPS ${location.latitude.toFixed(6)}, ${location.longitude.toFixed(6)} · ±${Math.round(location.accuracy)}m`, font * .6, canvas.height - font * .65);
		ctx.fillText(evidence_label, font * .6, canvas.height - font * .12);
		const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", .9)); if (bitmap.close) bitmap.close();
		if (!blob) throw new Error(__("The delivery photo could not be stamped."));
		return new File([blob], `kanban-evidence-${Date.now()}.jpg`, { type: "image/jpeg" });
	}

	async function delivery_allocation_scan(raw) {
		const delivery = state.lookup && state.lookup.delivery_session;
		if (!delivery) return scanner_error(__("Open a Delivery Session before allocation scanning."));
		try {
			const response = await frappe.call({
				method: "cfg_kanban.services.customer_delivery.get_delivery_allocation_candidate",
				args: { delivery_session: delivery.name, scan_value: raw, operator_session_token: state.token },
				freeze: true, freeze_message: __("Checking customer stock allocation..."),
			});
			const candidate = response.message;
			if (candidate.mode === "container") return confirm_container_allocation(delivery, raw, candidate);
			const row = candidate.contents[0];
			const dialog = new frappe.ui.Dialog({
				title: __("Allocate Stock Tag {0}", [row.visible_code]),
				fields: [
					{ fieldname: "item", label: __("Item / Batch"), fieldtype: "Data", read_only: 1,
						default: `${row.item_code} · ${row.batch_no || __("No Batch")}` },
					{ fieldname: "available", label: __("Available Quantity"), fieldtype: "Data", read_only: 1,
						default: `${format_number(row.available_qty)} ${row.stock_uom}` },
					{ fieldname: "qty", label: __("Customer Allocation Quantity"), fieldtype: "Float", reqd: 1,
						default: row.available_qty, read_only: candidate.full_quantity_only ? 1 : 0,
						description: candidate.full_quantity_only ? __("Serialized Stock Tags must remain complete.") : __("Enter a partial quantity only when the physical balance remains with this tag in the lorry.") },
				],
				primary_action_label: __("Reserve for Customer"),
				primary_action: async (values) => {
					dialog.hide(); await submit_delivery_allocation(delivery, raw, values.qty);
				},
			});
			dialog.show();
		} catch (error) { scanner_error(__("Stock Tag cannot be allocated. Review the validation message.")); }
	}

	function confirm_container_allocation(delivery, raw, candidate) {
		const e = frappe.utils.escape_html;
		const lines = candidate.contents.map((row) => `<li><strong>${e(row.visible_code)}</strong> · ${e(row.item_code)} · ${format_number(row.available_qty)} ${e(row.stock_uom)}</li>`).join("");
		frappe.confirm(
			`<strong>${__("Allocate complete container {0}?", [e(candidate.container_visible_code)])}</strong><ul class="mt-2">${lines}</ul><p>${__("Every contained Stock Tag will be reserved at full quantity. Individual partial allocation is not permitted while physically loaded.")}</p>`,
			() => submit_delivery_allocation(delivery, raw, candidate.total_qty)
		);
	}

	async function submit_delivery_allocation(delivery, raw, qty) {
		const response = await frappe.call({
			method: "cfg_kanban.services.customer_delivery.allocate_delivery_stock",
			args: { delivery_session: delivery.name, scan_value: raw, allocated_qty: qty,
				event_token: unique_token(), operator_session_token: state.token },
			freeze: true, freeze_message: __("Reserving Stock Tag for customer..."),
		});
		state.lookup = { delivery_session: response.message };
		render_lookup(); await refresh_list();
		$scanner.find(".scanner-message").html(`<small class="text-success">${__("Customer stock reserved")}</small>`);
		focus_scanner();
	}

	function release_delivery_allocation(name) {
		frappe.prompt([{ fieldname: "reason", label: __("Release Reason"), fieldtype: "Small Text", reqd: 1 }],
			async (values) => {
				const response = await frappe.call({
					method: "cfg_kanban.services.customer_delivery.release_delivery_allocation",
					args: { allocation: name, reason: values.reason, event_token: unique_token(), operator_session_token: state.token },
					freeze: true, freeze_message: __("Releasing customer reservation..."),
				});
				state.scan_mode = "lookup"; state.lookup = { delivery_session: response.message };
				render_lookup(); await refresh_list(); focus_scanner();
			}, __("Release Customer Stock Allocation"), __("Release Allocation"));
	}

	function confirm_delivery_allocations(delivery) {
		frappe.confirm(__("Confirm these Stock Tags and quantities for this customer? They remain reserved while the ERP Delivery Note is pending."), async () => {
			const response = await frappe.call({
				method: "cfg_kanban.services.customer_delivery.confirm_delivery_allocations",
				args: { delivery_session: delivery.name, event_token: unique_token(), operator_session_token: state.token },
				freeze: true, freeze_message: __("Confirming customer allocation..."),
			});
			state.lookup = { delivery_session: response.message }; render_lookup(); await refresh_list(); focus_scanner();
		});
	}

	async function prepare_customer_delivery_note(delivery) {
		const response = await frappe.call({
			method: "cfg_kanban.services.customer_delivery.get_customer_delivery_requirements",
			args: { delivery_session: delivery.name, operator_session_token: state.token },
			freeze: true, freeze_message: __("Checking Delivery Note requirements..."),
		});
		if (response.message.existing_draft) {
			frappe.set_route("Form", "Delivery Note", response.message.existing_draft);
			return;
		}
		const requirements = response.message.fields || [];
		if (!requirements.length) {
			const action = delivery.auto_submit_delivery_note ?
				__("Create and submit the ERPNext Delivery Note now?") :
				__("Create the ERPNext Delivery Note as Draft for authorized review?");
			return frappe.confirm(action, () => submit_customer_delivery_note(delivery));
		}
		const dialog = new frappe.ui.Dialog({
			title: __("Required Customer Delivery Note Details"),
			fields: required_erp_dialog_fields(requirements),
			primary_action_label: delivery.auto_submit_delivery_note ? __("Create and Submit") : __("Create Draft"),
			primary_action: async (values) => {
				dialog.hide();
				await submit_customer_delivery_note(
					delivery, JSON.stringify(required_erp_values(requirements, values))
				);
			},
		});
		dialog.show();
	}

	function required_erp_dialog_fields(requirements) {
		return requirements.map((row, index) => {
			if (row.scope === "table") return {
				fieldname: `customer_required_erp_${index}`, label: __(row.label),
				fieldtype: "Table", options: row.options, reqd: 1,
				data: row.default || [], in_place_edit: true,
				fields: (row.fields || []).map((column) => ({
					fieldname: column.fieldname, label: __(column.label),
					fieldtype: column.fieldtype, options: column.options,
					default: column.default, reqd: column.reqd ? 1 : 0,
					in_list_view: 1, columns: 2,
				})),
				description: __("Add all mandatory ERP rows. Sales Team allocations must total 100%."),
			};
			return {
				fieldname: `customer_required_erp_${index}`, label: __(row.label),
				fieldtype: row.fieldtype, options: row.options, default: row.default,
				reqd: 1, description: __("Required ERP document value"),
			};
		});
	}

	function required_erp_values(requirements, values) {
		const result = { parent: {}, tables: {} };
		requirements.forEach((row, index) => {
			const value = values[`customer_required_erp_${index}`];
			if (row.scope === "table") { result.tables[row.fieldname] = value || []; return; }
			if (row.scope === "parent") { result.parent[row.fieldname] = value; return; }
			if (!result.tables[row.table_field]) result.tables[row.table_field] = [];
			if (!result.tables[row.table_field][row.row_index]) result.tables[row.table_field][row.row_index] = {};
			result.tables[row.table_field][row.row_index][row.fieldname] = value;
		});
		return result;
	}

	async function submit_customer_delivery_note(delivery, required_erp_inputs) {
		const response = await frappe.call({
			method: "cfg_kanban.services.customer_delivery.create_customer_delivery_document",
			args: { delivery_session: delivery.name, event_token: unique_token(),
				operator_session_token: state.token, required_erp_inputs },
			freeze: true,
			freeze_message: delivery.auto_submit_delivery_note ? __("Creating and submitting Delivery Note...") : __("Creating Draft Delivery Note..."),
		});
		state.lookup = { delivery_session: response.message };
		render_lookup(); await refresh_list(); focus_scanner();
	}

	async function open_delivery_session(name) {
		const response = await frappe.call({
			method: "cfg_kanban.services.customer_delivery.get_delivery_session",
			args: { delivery_session: name, operator_session_token: state.token },
		});
		state.scan_mode = "lookup"; state.lookup = { delivery_session: response.message };
		render_lookup(); focus_scanner();
	}

	function manage_container_dialog() {
		const status = state.lookup && state.lookup.container_status;
		if (!status || status.mode !== "container") return;
		const container = status.container;
		const dialog = new frappe.ui.Dialog({
			title: __("Reusable Container {0}", [container.visible_code]),
			size: "extra-large",
			fields: [
				{ fieldname: "content_scan", label: __("Stock Tag"), fieldtype: "Data",
					description: __("Scan one complete physical Stock Tag, then select Load Tag.") },
				{ fieldname: "scan_camera", fieldtype: "Button", label: __("Scan Stock Tag with Camera") },
				{ fieldname: "content_html", fieldtype: "HTML" },
			],
			primary_action_label: __("Load Tag"),
			primary_action: async (values) => {
				const content_scan = String(values.content_scan || "").trim();
				if (!content_scan) return frappe.msgprint(__("Scan or enter a Stock Tag first."));
				await change_container_content("load_content_tag", {
					container_scan: container.visible_code, content_scan,
					event_token: unique_token(), operator_session_token: state.token,
				}, dialog);
			},
		});
		dialog.fields_dict.scan_camera.$input.on("click", () => camera_value((value) => {
			dialog.set_value("content_scan", value);
		}));
		dialog.fields_dict.content_scan.$input.on("keydown", (event) => {
			if (event.key === "Enter") { event.preventDefault(); dialog.get_primary_btn().trigger("click"); }
		});
		render_container_dialog(dialog, status);
		dialog.show();
	}

	function render_container_dialog(dialog, status) {
		const e = frappe.utils.escape_html;
		const current = (status.current_contents || []).map((row) => `<tr>
			<td><strong>${e(row.content_visible_code)}</strong></td><td>${e(row.item_code || "-")}</td>
			<td>${e(row.batch_no || __("No Batch"))}</td><td>${format_number(row.qty)} ${e(row.stock_uom || "")}</td>
			<td>${e(display_datetime(row.loaded_on))}</td><td><button class="btn btn-xs btn-danger unload-content" data-code="${e(row.content_visible_code)}">${__("Unload")}</button></td></tr>`).join("");
		const history = (status.history || []).slice(0, 20).map((row) => `<tr>
			<td>${e(row.content_visible_code)}</td><td>${e(row.item_code || "-")}</td><td>${format_number(row.qty)} ${e(row.stock_uom || "")}</td>
			<td>${e(display_datetime(row.unloaded_on))}</td><td>${e(row.unload_reason || "-")}</td></tr>`).join("");
		const html = `<div class="cfg-container-summary"><strong>${(status.current_contents || []).length} ${__("Stock Tags currently loaded")}</strong>
			<span>${e(status.container.inventory_company || "-")} · ${e(status.container.current_warehouse || "-")}</span></div>
			<h5>${__("Current Contents")}</h5><div class="table-responsive"><table class="table table-bordered"><thead><tr><th>${__("Tag")}</th><th>${__("Item")}</th><th>${__("Batch")}</th><th>${__("Quantity")}</th><th>${__("Loaded")}</th><th></th></tr></thead>
			<tbody>${current || `<tr><td colspan="6" class="text-muted">${__("Container is empty")}</td></tr>`}</tbody></table></div>
			<h5>${__("Recent Unloads")}</h5><div class="table-responsive"><table class="table table-bordered"><thead><tr><th>${__("Tag")}</th><th>${__("Item")}</th><th>${__("Quantity")}</th><th>${__("Unloaded")}</th><th>${__("Reason")}</th></tr></thead>
			<tbody>${history || `<tr><td colspan="5" class="text-muted">${__("No unload history")}</td></tr>`}</tbody></table></div>`;
		const $html = dialog.fields_dict.content_html.$wrapper.html(html);
		$html.find(".unload-content").on("click", function () {
			const content_scan = $(this).data("code");
			frappe.prompt([{ fieldname: "reason", label: __("Unload Reason"), fieldtype: "Small Text", reqd: 1 }],
				async (values) => change_container_content("unload_content_tag", {
					container_scan: status.container.visible_code, content_scan, reason: values.reason,
					event_token: unique_token(), operator_session_token: state.token,
				}, dialog), __("Unload {0}", [content_scan]), __("Unload Tag"));
		});
	}

	async function change_container_content(method, args, dialog) {
		const response = await frappe.call({ method: `cfg_kanban.services.container_contents.${method}`,
			args, freeze: true, freeze_message: method === "load_content_tag" ? __("Loading Stock Tag...") : __("Unloading Stock Tag...") });
		state.lookup.container_status = { mode: "container", ...response.message };
		render_container_dialog(dialog, state.lookup.container_status);
		dialog.set_value("content_scan", "");
		render_lookup();
	}

	async function process_scan(value) {
		const $input = $scanner.find(".logistics-scan-input");
		const raw = String(value || $input.val() || "").trim(); $input.val("");
		if (!raw) return focus_scanner();
		const operator = operator_token(raw);
		if (!state.token || operator) return login_operator(operator || raw);
		if (/^KMF-/i.test(raw)) return open_manifest(raw);
		if (/^KREC-/i.test(raw)) return open_reconciliation(raw);
		if (state.scan_mode === "delivery") return delivery_allocation_scan(raw);
		if (state.scan_mode === "reconciliation") return reconciliation_scan(raw);
		if (state.scan_mode === "lookup") return lookup_tag(raw);
		if (!state.manifest) return scanner_error(__("No Manifest is armed for transaction scanning."));
		const receipt_mode = state.scan_mode === "receipt";
		const method = receipt_mode ? "scan_receipt_tag" : "scan_dispatch_tag";
		try {
			const response = await frappe.call({ method: `cfg_kanban.api.logistics.${method}`, args: {
				manifest_name: state.manifest.name, scan_value: raw, event_token: unique_token(),
				operator_session_token: state.token,
			}, freeze: true, freeze_message: receipt_mode ? __("Confirming receipt tag...") : __("Adding dispatch tag...") });
			state.manifest = response.message; render_active(); await refresh_list();
			$scanner.find(".scanner-message").html(`<small class="text-success">${__("Tag accepted: {0}", [frappe.utils.escape_html(raw)])}</small>`);
		} catch (error) { scanner_error(__("Tag was not accepted. Read the displayed validation message.")); }
		focus_scanner();
	}

	async function lookup_tag(raw) {
		try {
			const response = await frappe.call({
				method: "cfg_kanban.api.logistics.lookup_logistics_tag",
				args: { scan_value: raw, operator_session_token: state.token },
				freeze: true,
				freeze_message: __("Looking up tag status..."),
			});
			state.lookup = response.message; render_lookup();
			if (state.lookup.transfer_manifest?.name) await open_manifest(state.lookup.transfer_manifest.name, { keep_lookup: true });
			else if (state.lookup.preferred_manifest) await open_manifest(state.lookup.preferred_manifest, { keep_lookup: true });
			else clear_manifest_view({ keep_lookup: true });
			$scanner.find(".scanner-message").html(`<small class="text-success">${__("Status loaded: {0}", [frappe.utils.escape_html(raw)])}</small>`);
		} catch (error) {
			scanner_error(server_error_message(error, __("Tag status could not be loaded.")));
		}
		focus_scanner();
	}

	async function open_manifest(name, options) {
		state.scan_mode = "lookup";
		if (!options?.keep_lookup) { state.lookup = null; render_lookup(); }
		try {
			const response = await frappe.call({ method: "cfg_kanban.api.logistics.get_manifest", args: {
				manifest_name: name, operator_session_token: state.token,
			} });
			state.manifest = response.message;
			if (options?.restore && TERMINAL_STATES.has(state.manifest.state)) {
				localStorage.removeItem(last_manifest_key);
				state.manifest = null;
				render_active(); focus_scanner(); return false;
			}
			localStorage.setItem(last_manifest_key, state.manifest.name);
			render_active(); focus_scanner(); return true;
		} catch (error) {
			localStorage.removeItem(last_manifest_key); state.manifest = null; render_active();
			if (!options?.quiet) scanner_error(__("Manifest could not be opened for this operator."));
			return false;
		}
	}

	function new_manifest_dialog() {
		if (!state.token) return identify_operator();
		const options = state.routes.filter((route) => route.can_dispatch);
		if (!options.length) {
			const assigned = (state.operator.responsibilities || []).join(", ") || __("None");
			return frappe.msgprint({ title: __("No Dispatch Route Assigned"), indicator: "orange",
				message: __("No active Logistics Route authorizes this operator for dispatch. Active Kanban Role: {0}. Responsible Roles: {1}.",
					[state.operator.kanban_role || "-", assigned]) });
		}
		const dialog = new frappe.ui.Dialog({ title: __("New Movement Manifest"), fields: [
			{ fieldname: "route", label: __("Logistics Route"), fieldtype: "Select", reqd: 1,
				options: options.map((route) => route.name).join("\n") },
		], primary_action_label: __("Create Manifest"), primary_action: async (values) => {
			const response = await frappe.call({ method: "cfg_kanban.api.logistics.create_manifest", args: {
				logistics_route: values.route, event_token: unique_token(), operator_session_token: state.token,
			}, freeze: true });
			dialog.hide(); state.manifest = response.message; state.scan_mode = "lookup";
			localStorage.setItem(last_manifest_key, state.manifest.name);
			render_active(); await refresh_list(); focus_scanner();
		} }); dialog.show();
	}

	function set_scan_mode(mode) {
		if (!state.manifest) return scanner_error(__("Select a Manifest before arming transaction scanning."));
		if (mode === "dispatch" && !(state.manifest.can_dispatch && state.manifest.state === "Draft")) {
			return scanner_error(__("This Manifest is not available for dispatch scanning."));
		}
		if (mode === "receipt" && !state.manifest.can_receive) {
			return scanner_error(__("This operator or Manifest is not available for receipt scanning."));
		}
		state.scan_mode = mode; render_active(); focus_scanner();
	}

	function clear_manifest_view(options) {
		state.scan_mode = "lookup"; state.manifest = null;
		localStorage.removeItem(last_manifest_key);
		if (!options?.keep_lookup) { state.lookup = null; render_lookup(); }
		render_active(); focus_scanner();
	}

	async function remove_line(line_name, unit) {
		const response = await frappe.call({ method: "cfg_kanban.api.logistics.remove_dispatch_tag", args: {
			manifest_name: state.manifest.name, line_name, handling_unit: unit,
			operator_session_token: state.token,
		} }); state.manifest = response.message; render_active(); await refresh_list(); focus_scanner();
	}

	function prepare_manifest() {
		if (state.scan_mode !== "lookup") return scanner_error(__("Stop transaction scanning before preparing the Manifest."));
		frappe.confirm(__("Reserve every scanned tag for this Manifest?"), async () => {
			await manifest_action("prepare_manifest", __("Preparing Manifest..."));
		});
	}

	function use_untagged_stock() {
		if (state.scan_mode !== "lookup") return scanner_error(__("Stop transaction scanning before selecting untagged ERP stock."));
		frappe.confirm(__("Use the Transfer Card quantity as ordinary ERP warehouse stock without creating a physical tag?"), async () => {
			await manifest_action("use_untagged_transfer_stock", __("Adding ERP stock line..."));
		});
	}

	async function confirm_dispatch() {
		const internal = state.manifest.manifest_type === "Internal Warehouse Transfer";
		const document_label = state.manifest.non_stock_operational_tracking ?
			__("Kanban Movement") : internal ? __("Stock Entry") : __("Delivery Note");
		const response = await frappe.call({
			method: "cfg_kanban.api.logistics.get_dispatch_requirements",
			args: { manifest_name: state.manifest.name, operator_session_token: state.token },
			freeze: true,
			freeze_message: __("Checking {0} requirements...", [document_label]),
		});
		const requirements = response.message.fields || [];
		if (!requirements.length) {
			return frappe.confirm(internal ?
				(state.manifest.non_stock_operational_tracking ?
					__("Confirm physical tagged movement? This non-stock Item will update only the Kanban Handling Unit ledger and location.") :
					__("Confirm physical movement and create the ERPNext Material Transfer Stock Entry?")) :
				__("Confirm physical dispatch and create the source-company Delivery Note?"), async () => {
				await manifest_action("confirm_dispatch", __("Creating {0}...", [document_label]));
			});
		}
		const fields = requirements.map((row, index) => {
			if (row.scope === "table") {
				return {
					fieldname: `required_erp_${index}`,
					label: __(row.label),
					fieldtype: "Table",
					options: row.options,
					reqd: 1,
					data: row.default || [],
					in_place_edit: true,
					fields: (row.fields || []).map((column) => ({
						fieldname: column.fieldname,
						label: __(column.label),
						fieldtype: column.fieldtype,
						options: column.options,
						default: column.default,
						reqd: column.reqd ? 1 : 0,
						in_list_view: 1,
						columns: 2,
					})),
					description: __("Add one or more rows. Percentage allocations must total 100%."),
				};
			}
			return {
				fieldname: `required_erp_${index}`,
				label: __(row.label),
				fieldtype: row.fieldtype,
				options: row.options,
				default: row.default,
				reqd: 1,
				description: __("Required ERP document value"),
			};
		});
		const dialog = new frappe.ui.Dialog({
			title: __("Required {0} Details", [document_label]),
			fields,
			primary_action_label: __("Confirm Dispatch"),
			primary_action: async (values) => {
				const required_erp_inputs = { parent: {}, tables: {} };
				requirements.forEach((row, index) => {
					const value = values[`required_erp_${index}`];
					if (row.scope === "table") {
						required_erp_inputs.tables[row.fieldname] = value || [];
						return;
					}
					if (row.scope === "parent") {
						required_erp_inputs.parent[row.fieldname] = value;
						return;
					}
					if (!required_erp_inputs.tables[row.table_field]) required_erp_inputs.tables[row.table_field] = [];
					if (!required_erp_inputs.tables[row.table_field][row.row_index]) required_erp_inputs.tables[row.table_field][row.row_index] = {};
					required_erp_inputs.tables[row.table_field][row.row_index][row.fieldname] = value;
				});
				dialog.hide();
				await manifest_action("confirm_dispatch", __("Creating {0}...", [document_label]), {
					required_erp_inputs: JSON.stringify(required_erp_inputs),
				});
			},
		});
		dialog.show();
	}

	function confirm_receipt() {
		if (state.scan_mode !== "lookup") return scanner_error(__("Stop receipt scanning before confirming receipt."));
		const internal = state.manifest.manifest_type === "Internal Warehouse Transfer";
		frappe.confirm(internal ?
			(state.manifest.non_stock_operational_tracking ?
				__("Confirm every tagged non-stock item was received at the destination Warehouse?") :
				__("Confirm receipt at the destination Warehouse and create the transit receipt Stock Entry?")) :
			__("Confirm all scanned tags were received and create the destination Purchase Receipt?"), async () => {
			await manifest_action("confirm_receipt", state.manifest.non_stock_operational_tracking ?
				__("Confirming tagged receipt...") : internal ? __("Creating receipt Stock Entry...") : __("Creating Purchase Receipt..."));
		});
	}

	function cancel_manifest() {
		if (state.scan_mode !== "lookup") return scanner_error(__("Stop transaction scanning before cancelling the Manifest."));
		frappe.prompt([{ fieldname: "reason", label: __("Cancellation Reason"), fieldtype: "Small Text", reqd: 1 }],
			async (values) => { await manifest_action("cancel_manifest", __("Cancelling Manifest..."), { reason: values.reason }); },
			__("Cancel Movement Manifest"), __("Cancel Manifest"));
	}

	async function manifest_action(method, message, extra) {
		const response = await frappe.call({ method: `cfg_kanban.api.logistics.${method}`, args: {
			manifest_name: state.manifest.name, event_token: unique_token(), operator_session_token: state.token,
			...(extra || {}),
		}, freeze: true, freeze_message: message });
		state.manifest = response.message;
		if (TERMINAL_STATES.has(state.manifest.state)) localStorage.removeItem(last_manifest_key);
		else localStorage.setItem(last_manifest_key, state.manifest.name);
		if ((state.scan_mode === "dispatch" && state.manifest.state !== "Draft") ||
			(state.scan_mode === "receipt" && !state.manifest.can_receive)) state.scan_mode = "lookup";
		render_active(); await refresh_list(); focus_scanner();
	}

	async function refresh_list() {
		const response = await frappe.call({ method: "cfg_kanban.api.logistics.get_logistics_console",
			args: { operator_session_token: state.token } });
		state.routes = response.message.routes || []; state.manifests = response.message.manifests || [];
		state.recent_manifests = response.message.recent_manifests || [];
		state.internal_transfers = response.message.internal_transfers || [];
		state.delivery_sessions = response.message.delivery_sessions || [];
		state.return_cases = response.message.return_cases || [];
		state.vehicle_warehouses = response.message.vehicle_warehouses || [];
		state.open_reconciliations = response.message.open_reconciliations || [];
		state.recent_reconciliations = response.message.recent_reconciliations || [];
		state.can_reconcile = Boolean(response.message.can_reconcile);
		render_list();
	}

	function identify_operator() {
		if (frappe.ui && frappe.ui.Scanner) return camera_operator();
		credential_dialog();
	}

	function camera_operator() {
		new frappe.ui.Scanner({ dialog: true, multiple: false, on_scan(data) {
			login_operator(operator_token(String(data.decodedText || "").trim()) || String(data.decodedText || "").trim());
		} });
	}

	function credential_dialog() {
		const dialog = new frappe.ui.Dialog({ title: __("Identify Logistics Operator"), fields: [
			{ fieldname: "token", label: __("Operator Credential"), fieldtype: "Data", reqd: 1 },
			{ fieldname: "pin", label: __("PIN"), fieldtype: "Password" },
			{ fieldname: "station", label: __("Terminal / Station"), fieldtype: "Data",
				default: localStorage.getItem("cfg_kanban_station") || "" },
		], primary_action_label: __("Continue"), primary_action: async (values) => {
			await login_operator(values.token, values.pin, values.station); dialog.hide();
		} }); dialog.show();
	}

	async function login_operator(token, pin, station) {
		try {
			const response = await frappe.call({ method: "cfg_kanban.api.operator.login_operator", args: {
				token, pin, station: station || localStorage.getItem("cfg_kanban_station") || "",
			}, freeze: true, freeze_message: __("Identifying operator...") });
			state.token = response.message.session_token; localStorage.setItem(session_key, state.token);
			if (station) localStorage.setItem("cfg_kanban_station", station);
			state.manifest = null; state.reconciliation = null; state.lookup = null; state.scan_mode = "lookup"; await load();
		} catch (error) { scanner_error(__("Operator identification failed.")); }
	}

	async function end_session() {
		if (state.token) await frappe.call({ method: "cfg_kanban.api.operator.logout_operator",
			args: { operator_session_token: state.token } });
		clear_session(); show_login();
	}

	function clear_session(expected_token) {
		const stored_token = localStorage.getItem(session_key);
		if (!expected_token || stored_token === expected_token) localStorage.removeItem(session_key);
		state.token = null; state.operator = null;
		state.routes = []; state.manifests = []; state.recent_manifests = []; state.internal_transfers = [];
		state.delivery_sessions = []; state.return_cases = [];
		state.vehicle_warehouses = []; state.open_reconciliations = []; state.recent_reconciliations = [];
		state.can_reconcile = false; state.manifest = null; state.reconciliation = null;
		state.lookup = null; state.scan_mode = "lookup";
	}

	function camera_scan() {
		if (!(frappe.ui && frappe.ui.Scanner)) return frappe.msgprint(__("Camera scanning is unavailable. Use the scanner field."));
		new frappe.ui.Scanner({ dialog: true, multiple: false, on_scan(data) {
			process_scan(String(data.decodedText || "").trim());
		} });
	}

	function operator_token(value) {
		try { const url = new URL(value); return new URLSearchParams(url.hash.replace(/^#/, "")).get("operator"); }
		catch (error) { return null; }
	}

	function route_scan_value() {
		const route = frappe.get_route();
		return route && route[0] === "kanban-logistics" && route[1] ? decodeURIComponent(route[1]) : null;
	}

	function update_scanner_state() {
		let label = __("Operator required"); let colour = "orange";
		if (state.token) { label = __("Tag lookup ready"); colour = "blue"; }
		if (state.scan_mode === "dispatch" && state.manifest) { label = `${__("Dispatch")} → ${state.manifest.name}`; colour = "orange"; }
		if (state.scan_mode === "receipt" && state.manifest) { label = `${__("Receipt")} → ${state.manifest.name}`; colour = "green"; }
		if (state.scan_mode === "delivery" && state.lookup?.delivery_session) { label = `${__("Customer Allocation")} → ${state.lookup.delivery_session.name}`; colour = "orange"; }
		if (state.scan_mode === "reconciliation" && state.reconciliation) { label = `${__("Route Count")} → ${state.reconciliation.name}`; colour = "orange"; }
		$scanner.find(".scanner-state").removeClass("orange blue green red").addClass(colour).text(label);
	}

	function scanner_error(message) {
		const safe_message = frappe.utils.escape_html(message || __("Unexpected scanner error"));
		$scanner.find(".scanner-message").html(`<small class="text-danger">${safe_message}</small>`);
		frappe.show_alert({ message, indicator: "red" }, 6); focus_scanner();
	}

	function server_error_message(error, fallback) {
		if (error?.message && !String(error.message).includes("There was an error")) {
			return String(error.message);
		}
		const response = error?.responseJSON || error;
		if (response?._server_messages) {
			try {
				const messages = JSON.parse(response._server_messages)
					.map((value) => {
						const parsed = typeof value === "string" ? JSON.parse(value) : value;
						return parsed?.message || parsed;
					})
					.filter(Boolean);
				if (messages.length) return messages.join(" ");
			} catch (_ignored) { /* Fall through to the stable fallback. */ }
		}
		return fallback;
	}

	function focus_scanner() {
		if (window.matchMedia("(min-width: 768px) and (hover: hover)").matches)
			setTimeout(() => $scanner.find(".logistics-scan-input").trigger("focus").select(), 50);
	}

	function unique_token() {
		return window.crypto && window.crypto.randomUUID ? window.crypto.randomUUID() :
			`${Date.now()}-${Math.random().toString(16).slice(2)}`;
	}

	function state_colour(value) {
		if (["Received", "Closed"].includes(value)) return "green";
		if (["Exception", "Hold"].includes(value)) return "red";
		if (["Awaiting Receipt", "Receipt Document Pending"].includes(value)) return "orange";
		return "blue";
	}

	function reconciliation_colour(value) {
		if (value === "Closed") return "green";
		if (value === "Variance") return "red";
		if (value === "Ready to Close") return "blue";
		if (value === "Cancelled") return "grey";
		return "orange";
	}

	function display_datetime(value) {
		if (!value) return "-";
		try { return frappe.datetime.prettyDate(value); }
		catch (error) { return String(value); }
	}

	const initial_scan = route_scan_value();
	load().then(() => { if (initial_scan && state.token) lookup_tag(initial_scan); });
};
