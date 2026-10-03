frappe.pages["kanban-logistics"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Kanban Logistics"), single_column: true });
	const session_key = "cfg_kanban_operator_session";
	const last_manifest_key = "cfg_kanban_last_manifest";
	const state = { token: localStorage.getItem(session_key), operator: null, routes: [],
		manifests: [], recent_manifests: [], internal_transfers: [], manifest: null,
		lookup: null, scan_mode: "lookup" };
	const $sticky = $("<div class='cfg-logistics-sticky'></div>").appendTo(page.main);
	const $scanner = $(`<div class="frappe-card cfg-logistics-scanner">
		<div class="cfg-logistics-scanner-head"><div><strong>${__("Logistics Scanner")}</strong>
			<small>${__("Scan operator, Manifest ID, or preprinted Stock Tag")}</small></div>
			<span class="indicator-pill orange scanner-state">${__("Operator required")}</span></div>
		<div class="cfg-logistics-scan-row">
			<input class="form-control logistics-scan-input" autocomplete="off" spellcheck="false"
				placeholder="${__("Scan MFG-STK1000 or KMF number")}">
			<button class="btn btn-primary camera-scan">${__("Scan with Camera")}</button>
		</div><div class="scanner-message text-muted"><small>${__("Ready")}</small></div>
	</div>`).appendTo($sticky);
	const $identity = $("<div></div>").appendTo($sticky);
	const $lookup = $("<div class='cfg-logistics-lookup mt-3'></div>").appendTo(page.main);
	const $active = $("<div class='cfg-logistics-active mt-3'></div>").appendTo(page.main);
	const $actions = $(`<div class="cfg-logistics-toolbar mt-3 mb-3">
		<button class="btn btn-primary new-manifest">${__("New Dispatch Manifest")}</button>
		<button class="btn btn-default refresh-logistics">${__("Refresh")}</button>
		<button class="btn btn-default switch-operator">${__("Switch Operator")}</button>
		<button class="btn btn-default production-panel">${__("Production Panel")}</button>
		<button class="btn btn-default service-panel">${__("Service Panel")}</button>
	</div>`).appendTo(page.main);
	const $list = $("<div class='cfg-logistics-list'></div>").appendTo(page.main);

	$scanner.find(".logistics-scan-input").on("keydown", (event) => {
		if (event.key === "Enter") { event.preventDefault(); process_scan(); }
	});
	$scanner.find(".camera-scan").on("click", camera_scan);
	$actions.find(".new-manifest").on("click", new_manifest_dialog);
	$actions.find(".refresh-logistics").on("click", load);
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
			state.scan_mode = "lookup";
			render_identity();
			const last_manifest = state.manifest?.name || state.manifest || localStorage.getItem(last_manifest_key);
			if (last_manifest) await open_manifest(last_manifest, { quiet: true });
			else render_active();
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
		$lookup.empty(); $list.empty(); update_scanner_state(); focus_scanner();
	}

	function render_identity() {
		const e = frappe.utils.escape_html;
		$identity.html(`<div class="alert alert-info cfg-logistics-identity"><div><small>${__("Active operator")}</small>
			<strong>${e(state.operator.employee_name || state.operator.employee)}</strong>
			<span>${e(state.operator.kanban_role || "")}</span></div>
			<div><button class="btn btn-primary switch">${__("Switch Operator")}</button>
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
		const receipt_mode = ["Dispatched", "Awaiting Receipt", "Receipt Document Pending"].includes(m.state);
		const receipt_scanned = (m.lines || []).filter((row) => row.receipt_scanned).length;
		let mode_notice = `<div class="alert alert-info"><strong>${__("View-only lookup")}</strong> · ${__("Scanning a Stock Tag will show its status and will not change this Manifest.")}</div>`;
		if (state.scan_mode === "dispatch") mode_notice = `<div class="alert alert-warning"><strong>${__("DISPATCH SCANNING ARMED")}</strong> · ${e(m.name)} · ${__("Scanned tags will be added to this Manifest.")}</div>`;
		if (state.scan_mode === "receipt") mode_notice = `<div class="alert alert-success"><strong>${__("RECEIPT SCANNING ARMED")}</strong> · ${e(m.name)} · ${__("Only tags listed on this Manifest will be accepted.")}</div>`;
		const rendered_container_actions = new Set();
		const lines = (m.lines || []).map((row) => {
			const show_container_remove = row.container_handling_unit &&
				!rendered_container_actions.has(row.container_handling_unit);
			if (show_container_remove) rendered_container_actions.add(row.container_handling_unit);
			return `<div class="cfg-logistics-line">
			<div><strong>${e(row.visible_code)}</strong><small>${e(row.item_code)} · ${e(row.batch_no || __("No Batch"))}</small>
				${row.container_visible_code ? `<small>${__("Inside container")}: <strong>${e(row.container_visible_code)}</strong></small>` : ""}</div>
			<div><strong>${format_number(row.dispatch_qty)} ${e(row.stock_uom)}</strong>
				<small>${row.receipt_scanned ? __("Receipt scan confirmed") : e(row.state)}</small></div>
				${m.state === "Draft" && state.scan_mode === "dispatch" && (!row.container_handling_unit || show_container_remove) ? `<button class="btn btn-xs btn-danger remove-line" data-unit="${e(row.handling_unit)}">${row.container_visible_code ? __("Remove Container") : __("Remove")}</button>` : ""}
			</div>`;
		}).join("");
		$active.html(`<div class="frappe-card cfg-logistics-manifest">
			<div class="cfg-logistics-manifest-head"><div><small>${__("Viewed Manifest")}</small><h2>${e(m.name)}</h2>
				<strong>${e(m.logistics_route)}</strong></div><span class="indicator-pill ${state_colour(m.state)}">${e(m.state)}</span></div>
			<div class="cfg-logistics-route"><div><small>${__("FROM")}</small><strong>${e(m.source_company)}</strong><span>${e(m.source_warehouse)}</span></div>
				<div class="cfg-logistics-arrow">→</div><div><small>${__("TO")}</small><strong>${e(m.destination_company)}</strong><span>${e(m.destination_warehouse)}</span></div></div>
			${mode_notice}
			${receipt_mode ? `<div class="cfg-logistics-receipt-progress"><strong>${__("Receipt scans: {0} of {1}", [receipt_scanned, (m.lines || []).length])}</strong><span>${m.can_receive ? __("Arm Receipt Scanning and scan every physical tag.") : __("Switch to an operator assigned to the route's Receipt Responsibility.")}</span></div>` : ""}
			<div class="cfg-logistics-lines">${lines || `<div class="text-muted p-3">${__("No tags scanned")}</div>`}</div>
			<div class="cfg-logistics-docs"><span>${__("Delivery Note")}: <strong>${e(m.dispatch_delivery_note || __("Not created"))}</strong></span>
				<span>${__("Purchase Receipt")}: <strong>${e(m.receipt_purchase_receipt || __("Not created"))}</strong></span></div>
			<div class="cfg-logistics-actions">${manifest_actions(m)}</div>
		</div>`);
		$active.find(".remove-line").on("click", function () { remove_line($(this).data("unit")); });
		$active.find(".prepare-manifest").on("click", prepare_manifest);
		$active.find(".confirm-dispatch").on("click", confirm_dispatch);
		$active.find(".confirm-receipt").on("click", confirm_receipt);
		$active.find(".cancel-manifest").on("click", cancel_manifest);
		$active.find(".open-dn").on("click", () => frappe.set_route("Form", "Delivery Note", m.dispatch_delivery_note));
		$active.find(".open-pr").on("click", () => frappe.set_route("Form", "Purchase Receipt", m.receipt_purchase_receipt));
		$active.find(".arm-dispatch").on("click", () => set_scan_mode("dispatch"));
		$active.find(".arm-receipt").on("click", () => set_scan_mode("receipt"));
		$active.find(".stop-scanning").on("click", () => set_scan_mode("lookup"));
		$active.find(".clear-manifest").on("click", clear_manifest_view);
		update_scanner_state();
	}

	function manifest_actions(m) {
		const buttons = [];
		const receipt_state = ["Dispatched", "Awaiting Receipt", "Receipt Document Pending"].includes(m.state);
		const all_received = Boolean(m.lines.length && m.lines.every((row) => row.receipt_scanned));
		if (m.can_dispatch && m.state === "Draft") {
			buttons.push(state.scan_mode === "dispatch" ?
				`<button class="btn btn-warning stop-scanning">${__("Stop Dispatch Scanning")}</button>` :
				`<button class="btn btn-primary arm-dispatch">${__("Start Dispatch Scanning")}</button>`);
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
				`<button class="btn btn-success confirm-receipt">${__("Confirm Receipt")}</button>` :
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
		buttons.push(`<button class="btn btn-default clear-manifest">${__("Clear Viewed Manifest")}</button>`);
		return buttons.join("");
	}

	function render_list() {
		const e = frappe.utils.escape_html;
		const open_rows = state.manifests.map((m) =>
			`<button class="frappe-card cfg-logistics-list-row" data-name="${e(m.name)}"><div><strong>${e(m.name)}</strong><small>${e(m.logistics_route)}</small></div>
			<div><span class="indicator-pill ${state_colour(m.state)}">${e(m.state)}</span><small>${format_number(m.total_quantity)} ${__("total quantity")}</small></div></button>`).join("") ||
			`<div class="text-muted p-4">${__("No open Manifests available for this operator")}</div>`;
		const recent_rows = state.recent_manifests.map((m) =>
			`<button class="frappe-card cfg-logistics-list-row recent-manifest-row" data-name="${e(m.name)}"><div><strong>${e(m.name)}</strong><small>${e(m.logistics_route)} · ${e(display_datetime(m.modified))}</small></div>
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
		$list.html(`<section class="cfg-internal-transfer-list mb-4"><h3>${__("Same-Company Tagged Warehouse Transfers")}</h3>
			<p class="text-muted">${__("A Stock/Manufacturing user prepares the Draft ERPNext Material Transfer. Scan its physical tags here; ERPNext submission confirms the Warehouse movement.")}</p>${transfer_rows}</section>
			<section class="cfg-logistics-open-list"><h3>${__("Open Movement Manifests")}</h3>${open_rows}</section>
			<details class="cfg-logistics-recent mt-4"><summary><strong>${__("Recently Completed")}</strong> <span class="text-muted">${__("Latest 10")}</span></summary><div class="mt-3">${recent_rows}</div></details>`);
		$list.find(".cfg-logistics-list-row").on("click", function () { open_manifest($(this).data("name")); });
		$list.find(".internal-transfer-row").off("click").on("click", function () {
			internal_transfer_dialog($(this).data("name"));
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
			${membership_notice}${content_notice}${serial_notice}
			<div class="cfg-logistics-last-movement"><small>${__("Last movement")}</small><strong>${movement ? `${e(movement.event_type)} · ${e(display_datetime(movement.posting_datetime))}` : __("No quantity movement recorded")}</strong></div>
			<div class="cfg-logistics-related"><small>${__("Related Manifests")}</small><div>${manifests || `<span class="text-muted">${__("No Manifest history for this tag")}</span>`}</div></div>
		</div>`);
		$lookup.find(".close-lookup").on("click", () => { state.lookup = null; render_lookup(); focus_scanner(); });
		$lookup.find(".lookup-manifest").on("click", function () { open_manifest($(this).data("name")); });
		$lookup.find(".explore-genealogy").on("click", function () {
			frappe.set_route("material-genealogy", $(this).data("code"));
		});
		$lookup.find(".manage-container").on("click", manage_container_dialog);
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
			if (state.lookup.preferred_manifest) await open_manifest(state.lookup.preferred_manifest, { keep_lookup: true });
			else clear_manifest_view({ keep_lookup: true });
			$scanner.find(".scanner-message").html(`<small class="text-success">${__("Status loaded: {0}", [frappe.utils.escape_html(raw)])}</small>`);
		} catch (error) { scanner_error(__("Tag status could not be loaded.")); }
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
		const dialog = new frappe.ui.Dialog({ title: __("New Intercompany Dispatch Manifest"), fields: [
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

	async function remove_line(unit) {
		const response = await frappe.call({ method: "cfg_kanban.api.logistics.remove_dispatch_tag", args: {
			manifest_name: state.manifest.name, handling_unit: unit, operator_session_token: state.token,
		} }); state.manifest = response.message; render_active(); await refresh_list(); focus_scanner();
	}

	function prepare_manifest() {
		if (state.scan_mode !== "lookup") return scanner_error(__("Stop transaction scanning before preparing the Manifest."));
		frappe.confirm(__("Reserve every scanned tag for this Manifest?"), async () => {
			await manifest_action("prepare_manifest", __("Preparing Manifest..."));
		});
	}

	async function confirm_dispatch() {
		const response = await frappe.call({
			method: "cfg_kanban.api.logistics.get_dispatch_requirements",
			args: { manifest_name: state.manifest.name, operator_session_token: state.token },
			freeze: true,
			freeze_message: __("Checking Delivery Note requirements..."),
		});
		const requirements = response.message.fields || [];
		if (!requirements.length) {
			return frappe.confirm(__("Confirm physical dispatch and create the source-company Delivery Note?"), async () => {
				await manifest_action("confirm_dispatch", __("Creating Delivery Note..."));
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
			title: __("Required Delivery Note Details"),
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
				await manifest_action("confirm_dispatch", __("Creating Delivery Note..."), {
					required_erp_inputs: JSON.stringify(required_erp_inputs),
				});
			},
		});
		dialog.show();
	}

	function confirm_receipt() {
		if (state.scan_mode !== "lookup") return scanner_error(__("Stop receipt scanning before confirming receipt."));
		frappe.confirm(__("Confirm all scanned tags were received and create the destination Purchase Receipt?"), async () => {
			await manifest_action("confirm_receipt", __("Creating Purchase Receipt..."));
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
		localStorage.setItem(last_manifest_key, state.manifest.name);
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
			state.manifest = null; state.lookup = null; state.scan_mode = "lookup"; await load();
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
		state.manifest = null; state.lookup = null; state.scan_mode = "lookup";
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
		$scanner.find(".scanner-state").removeClass("orange blue green red").addClass(colour).text(label);
	}

	function scanner_error(message) {
		$scanner.find(".scanner-message").html(`<small class="text-danger">${message}</small>`);
		frappe.show_alert({ message, indicator: "red" }, 6); focus_scanner();
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

	function display_datetime(value) {
		if (!value) return "-";
		try { return frappe.datetime.prettyDate(value); }
		catch (error) { return String(value); }
	}

	const initial_scan = route_scan_value();
	load().then(() => { if (initial_scan && state.token) lookup_tag(initial_scan); });
};
