frappe.pages["kanban-logistics"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Kanban Logistics"), single_column: true });
	const session_key = "cfg_kanban_operator_session";
	const state = { token: localStorage.getItem(session_key), operator: null, routes: [],
		manifests: [], manifest: null };
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
		if (!state.token) return show_login();
		try {
			const response = await frappe.call({ method: "cfg_kanban.api.logistics.get_logistics_console",
				args: { operator_session_token: state.token } });
			state.operator = response.message.operator;
			state.routes = response.message.routes || [];
			state.manifests = response.message.manifests || [];
			render_identity();
			if (state.manifest) await open_manifest(state.manifest.name || state.manifest);
			else render_active();
			render_list();
			focus_scanner();
		} catch (error) {
			clear_session();
			show_login(__("Operator session expired. Scan the operator credential again."));
		}
	}

	function show_login(message) {
		state.operator = null; state.manifest = null;
		$identity.html(`<div class="alert alert-warning cfg-logistics-identity"><div><small>${__("Active operator")}</small>
			<strong>${__("Not identified")}</strong></div><button class="btn btn-primary login-operator">${__("Scan / Enter Operator")}</button></div>`);
		$identity.find(".login-operator").on("click", identify_operator);
		$active.html(`<div class="frappe-card text-center p-5"><h3>${__("Operator identification required")}</h3>
			<p class="text-muted">${message || __("Identify the operator before preparing or receiving a Manifest.")}</p></div>`);
		$list.empty(); update_scanner_state(); focus_scanner();
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
			$active.html(`<div class="frappe-card cfg-logistics-empty"><h3>${__("No active Manifest selected")}</h3>
				<p>${__("Create a dispatch Manifest or select an open Manifest below.")}</p></div>`);
			return;
		}
		const m = state.manifest; const e = frappe.utils.escape_html;
		const receipt_mode = ["Dispatched", "Awaiting Receipt", "Receipt Document Pending"].includes(m.state);
		const lines = (m.lines || []).map((row) => `<div class="cfg-logistics-line">
			<div><strong>${e(row.visible_code)}</strong><small>${e(row.item_code)} · ${e(row.batch_no || __("No Batch"))}</small></div>
			<div><strong>${format_number(row.dispatch_qty)} ${e(row.stock_uom)}</strong>
				<small>${row.receipt_scanned ? __("Receipt scan confirmed") : e(row.state)}</small></div>
			${m.state === "Draft" ? `<button class="btn btn-xs btn-danger remove-line" data-unit="${e(row.handling_unit)}">${__("Remove")}</button>` : ""}
		</div>`).join("");
		$active.html(`<div class="frappe-card cfg-logistics-manifest">
			<div class="cfg-logistics-manifest-head"><div><small>${__("Active Manifest")}</small><h2>${e(m.name)}</h2>
				<strong>${e(m.logistics_route)}</strong></div><span class="indicator-pill ${state_colour(m.state)}">${e(m.state)}</span></div>
			<div class="cfg-logistics-route"><div><small>${__("FROM")}</small><strong>${e(m.source_company)}</strong><span>${e(m.source_warehouse)}</span></div>
				<div class="cfg-logistics-arrow">→</div><div><small>${__("TO")}</small><strong>${e(m.destination_company)}</strong><span>${e(m.destination_warehouse)}</span></div></div>
			<div class="alert ${receipt_mode ? "alert-success" : "alert-info"}">${receipt_mode ?
				__("Receipt mode: scan every tag listed on this Manifest.") :
				__("Dispatch mode: scan activated preprinted Stock Tags from the source Warehouse.")}</div>
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
		update_scanner_state();
	}

	function manifest_actions(m) {
		const buttons = [];
		if (m.can_dispatch && m.state === "Draft" && m.lines.length) buttons.push(`<button class="btn btn-primary prepare-manifest">${__("Prepare and Reserve")}</button>`);
		if (m.can_dispatch && (m.state === "Prepared" || m.dispatch_retry_available)) {
			buttons.push(`<button class="btn btn-success confirm-dispatch">${m.dispatch_retry_available ? __("Retry Dispatch") : __("Confirm Dispatch")}</button>`);
		}
		if (["Dispatched", "Awaiting Receipt", "Receipt Document Pending"].includes(m.state) &&
			m.can_receive && m.lines.length && m.lines.every((row) => row.receipt_scanned)) buttons.push(`<button class="btn btn-success confirm-receipt">${__("Confirm Receipt")}</button>`);
		if (["Draft", "Prepared"].includes(m.state) && state.operator.can_override) buttons.push(`<button class="btn btn-danger cancel-manifest">${__("Cancel Manifest")}</button>`);
		if (m.dispatch_delivery_note) buttons.push(`<button class="btn btn-default open-dn">${__("Open Delivery Note")}</button>`);
		if (m.receipt_purchase_receipt) buttons.push(`<button class="btn btn-default open-pr">${__("Open Purchase Receipt")}</button>`);
		return buttons.join("");
	}

	function render_list() {
		const e = frappe.utils.escape_html;
		$list.html(`<h3>${__("Open Movement Manifests")}</h3>${state.manifests.map((m) =>
			`<button class="frappe-card cfg-logistics-list-row" data-name="${e(m.name)}"><div><strong>${e(m.name)}</strong><small>${e(m.logistics_route)}</small></div>
			<div><span class="indicator-pill ${state_colour(m.state)}">${e(m.state)}</span><small>${format_number(m.total_quantity)} ${__("total quantity")}</small></div></button>`).join("") ||
			`<div class="text-muted p-4">${__("No open Manifests available for this operator")}</div>`}`);
		$list.find(".cfg-logistics-list-row").on("click", function () { open_manifest($(this).data("name")); });
	}

	async function process_scan(value) {
		const $input = $scanner.find(".logistics-scan-input");
		const raw = String(value || $input.val() || "").trim(); $input.val("");
		if (!raw) return focus_scanner();
		const operator = operator_token(raw);
		if (!state.token || operator) return login_operator(operator || raw);
		if (/^KMF-/i.test(raw)) return open_manifest(raw);
		if (!state.manifest) return scanner_error(__("Select or create a Movement Manifest before scanning a Stock Tag."));
		const receipt_mode = ["Dispatched", "Awaiting Receipt", "Receipt Document Pending"].includes(state.manifest.state);
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

	async function open_manifest(name) {
		try {
			const response = await frappe.call({ method: "cfg_kanban.api.logistics.get_manifest", args: {
				manifest_name: name, operator_session_token: state.token,
			} });
			state.manifest = response.message; render_active(); focus_scanner();
		} catch (error) { scanner_error(__("Manifest could not be opened for this operator.")); }
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
			dialog.hide(); state.manifest = response.message; render_active(); await refresh_list(); focus_scanner();
		} }); dialog.show();
	}

	async function remove_line(unit) {
		const response = await frappe.call({ method: "cfg_kanban.api.logistics.remove_dispatch_tag", args: {
			manifest_name: state.manifest.name, handling_unit: unit, operator_session_token: state.token,
		} }); state.manifest = response.message; render_active(); await refresh_list(); focus_scanner();
	}

	function prepare_manifest() {
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
		const fields = requirements.map((row, index) => ({
			fieldname: `required_erp_${index}`,
			label: __(row.label),
			fieldtype: row.fieldtype,
			options: row.options,
			default: row.default,
			reqd: 1,
			description: row.scope === "child" ? __("Required ERP table value") : __("Required ERP document value"),
		}));
		const dialog = new frappe.ui.Dialog({
			title: __("Required Delivery Note Details"),
			fields,
			primary_action_label: __("Confirm Dispatch"),
			primary_action: async (values) => {
				const required_erp_inputs = { parent: {}, tables: {} };
				requirements.forEach((row, index) => {
					const value = values[`required_erp_${index}`];
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
		frappe.confirm(__("Confirm all scanned tags were received and create the destination Purchase Receipt?"), async () => {
			await manifest_action("confirm_receipt", __("Creating Purchase Receipt..."));
		});
	}

	function cancel_manifest() {
		frappe.prompt([{ fieldname: "reason", label: __("Cancellation Reason"), fieldtype: "Small Text", reqd: 1 }],
			async (values) => { await manifest_action("cancel_manifest", __("Cancelling Manifest..."), { reason: values.reason }); },
			__("Cancel Movement Manifest"), __("Cancel Manifest"));
	}

	async function manifest_action(method, message, extra) {
		const response = await frappe.call({ method: `cfg_kanban.api.logistics.${method}`, args: {
			manifest_name: state.manifest.name, event_token: unique_token(), operator_session_token: state.token,
			...(extra || {}),
		}, freeze: true, freeze_message: message });
		state.manifest = response.message; render_active(); await refresh_list(); focus_scanner();
	}

	async function refresh_list() {
		const response = await frappe.call({ method: "cfg_kanban.api.logistics.get_logistics_console",
			args: { operator_session_token: state.token } });
		state.routes = response.message.routes || []; state.manifests = response.message.manifests || [];
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
			state.manifest = null; await load();
		} catch (error) { scanner_error(__("Operator identification failed.")); }
	}

	async function end_session() {
		if (state.token) await frappe.call({ method: "cfg_kanban.api.operator.logout_operator",
			args: { operator_session_token: state.token } });
		clear_session(); show_login();
	}

	function clear_session() {
		localStorage.removeItem(session_key); state.token = null; state.operator = null;
		state.routes = []; state.manifests = []; state.manifest = null;
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

	function update_scanner_state() {
		let label = __("Operator required"); let colour = "orange";
		if (state.token && !state.manifest) { label = __("Select Manifest"); colour = "blue"; }
		if (state.manifest) {
			const receipt = ["Dispatched", "Awaiting Receipt", "Receipt Document Pending"].includes(state.manifest.state);
			label = receipt ? __("Receipt scan ready") : __("Dispatch scan ready"); colour = "green";
		}
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

	load();
};
