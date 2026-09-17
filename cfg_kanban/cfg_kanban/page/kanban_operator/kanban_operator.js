frappe.pages["kanban-operator"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Kanban Operator"),
		single_column: true,
	});

	const session_key = "cfg_kanban_operator_session";
	const state = { context: null, operator: null, access: null,
		session_token: localStorage.getItem(session_key), awaiting_operator_scan: false,
		active_progress_dialog: null, scanner_message: __("Scanner ready"),
		modal_scan_buffer: "", modal_scan_at: 0 };
	const scan = page.add_field({
		label: __("Fixed scanner input — scan any card"),
		fieldtype: "Data",
		fieldname: "scan_token",
		change: () => process_scan(scan.get_value()),
	});
	page.set_primary_action(__("Find Card"), () => process_scan(scan.get_value()), "search");
	page.add_inner_button(__("Clear / Next Card (F3)"), clear_for_next_card);
	const $scanner_status = $(`<div class="cfg-scanner-status mt-3 mb-3" aria-live="polite"></div>`)
		.appendTo(page.main);

	const $card_camera = $(`<div class="cfg-kanban-card-camera mt-3 mb-3">
		<button class="btn btn-primary btn-lg btn-block">
			${__("Scan Kanban Card with Camera")}
		</button>
		<small class="text-muted d-block text-center mt-2">
			${__("Or paste/type the card number in the field above and select Find Card.")}
		</small>
	</div>`).appendTo(page.main).hide();
	$card_camera.find("button").on("click", scan_kanban_qr);
	const $root = $("<div class='cfg-kanban-operator mt-4'></div>").appendTo(page.main);
	page.add_inner_button(__("Switch Operator (F2)"), prepare_operator_switch);
	page.add_inner_button(__("End Operator Session (F8)"), confirm_end_operator_session);
	page.add_inner_button(__("Scan Operator QR"), scan_operator_qr);
	page.add_inner_button(__("Camera Scan (F4)"), scan_kanban_qr);
	page.add_inner_button(__("Scanner Help (F1)"), show_scanner_help);
	install_scanner_shortcuts();

	async function load_console() {
		const response = await frappe.call({ method: "cfg_kanban.api.operator.get_console_access" });
		state.access = response.message;
		if (await consume_deep_link()) return;
		await restore_operator();
	}

	async function consume_deep_link() {
		const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
		const token = params.get("operator");
		if (!token) return false;
		window.history.replaceState({}, document.title, window.location.pathname + window.location.search);
		try {
			const response = await frappe.call({ method: "cfg_kanban.api.operator.login_operator", args: {
				token, station: localStorage.getItem("cfg_kanban_station") || "",
			}, freeze: true, freeze_message: __("Identifying operator...") });
			activate_operator(response.message);
			render();
		} catch (error) {
			show_operator_login(false, token);
		}
		return true;
	}

	async function restore_operator() {
		if (!state.session_token) return render();
		try {
			const response = await frappe.call({
				method: "cfg_kanban.api.operator.operator_session_status",
				args: { operator_session_token: state.session_token },
			});
			state.operator = response.message;
			render();
		} catch (error) {
			clear_operator();
			show_operator_login(false);
		}
	}

	function clear_operator() {
		localStorage.removeItem(session_key);
		state.session_token = null;
		state.operator = null;
		state.context = null;
		state.awaiting_operator_scan = false;
	}

	function activate_operator(message) {
		clear_operator();
		state.session_token = message.session_token;
		state.operator = message.operator;
		localStorage.setItem(session_key, state.session_token);
	}

	async function end_operator_session() {
		if (state.session_token) {
			await frappe.call({ method: "cfg_kanban.api.operator.logout_operator",
				args: { operator_session_token: state.session_token }, freeze: true });
		}
		clear_operator();
		render();
		frappe.show_alert({ message: __("Operator session ended; ERP terminal remains signed in"), indicator: "green" });
		focus_scanner();
	}

	function confirm_end_operator_session() {
		frappe.confirm(
			__("End the active operator session on this terminal?"),
			end_operator_session,
			focus_scanner
		);
	}

	function prepare_operator_switch() {
		state.awaiting_operator_scan = true;
		set_scanner_message(__("Scan the NEXT OPERATOR credential now"), "orange");
		focus_scanner();
	}

	function clear_for_next_card() {
		scan.set_value("");
		state.context = null;
		state.awaiting_operator_scan = false;
		set_scanner_message(__("Ready for next Kanban card"), "green");
		render();
		focus_scanner();
	}

	function show_operator_login(switching, scanned_token) {
		const dialog = new frappe.ui.Dialog({
			title: switching ? __("Switch Operator") : __("Operator Login"),
			fields: [
				{ fieldname: "token", label: __("Scan Operator QR"), fieldtype: "Data", reqd: 1,
					default: scanned_token || "", read_only: Boolean(scanned_token) },
				{ fieldname: "pin", label: __("PIN (if required)"), fieldtype: "Password" },
				{ fieldname: "station", label: __("Terminal / Station"), fieldtype: "Data",
					default: localStorage.getItem("cfg_kanban_station") || "" },
			],
			primary_action_label: __("Continue"),
			primary_action: async (values) => {
				const response = await frappe.call({ method: "cfg_kanban.api.operator.login_operator",
					args: values, freeze: true, freeze_message: __("Identifying operator...") });
				activate_operator(response.message);
				localStorage.setItem("cfg_kanban_station", values.station || "");
				dialog.hide();
				render();
				scan.set_focus();
			},
		});
		dialog.show();
		dialog.get_field("token").set_focus();
	}

	function show_development_proxy_login() {
		if (!(state.access && state.access.can_use_development_proxy)) return;
		const dialog = new frappe.ui.Dialog({
			title: __("Development Proxy Operator"),
			fields: [
				{ fieldname: "warning", fieldtype: "HTML", options:
					`<div class="alert alert-warning">${__("Development bypass: actions will be attributed to the selected Employee and Administrator. Do not enable this in production.")}</div>` },
				{ fieldname: "employee", label: __("Operate as Employee"), fieldtype: "Link",
					options: "Employee", reqd: 1, get_query: () => ({ filters: { status: "Active" } }) },
				{ fieldname: "station", label: __("Terminal / Station"), fieldtype: "Data",
					default: localStorage.getItem("cfg_kanban_station") || "" },
			],
			primary_action_label: __("Start Development Proxy Session"),
			primary_action: async (values) => {
				const response = await frappe.call({
					method: "cfg_kanban.api.operator.login_development_proxy",
					args: values,
					freeze: true,
					freeze_message: __("Starting development proxy session..."),
				});
				activate_operator(response.message);
				localStorage.setItem("cfg_kanban_station", values.station || "");
				dialog.hide();
				render();
			},
		});
		dialog.show();
	}

	function operator_token_from_scan(decoded_text) {
		const value = String(decoded_text || "").trim();
		if (!value) return "";
		try {
			const url = new URL(value, window.location.origin);
			return new URLSearchParams(url.hash.replace(/^#/, "")).get("operator") || value;
		} catch (error) {
			return value;
		}
	}

	async function login_scanned_operator(token) {
		try {
			const station = localStorage.getItem("cfg_kanban_station") || "";
			const response = await frappe.call({
				method: "cfg_kanban.api.operator.login_operator",
				args: { token, station },
				freeze: true,
				freeze_message: __("Identifying operator..."),
			});
			activate_operator(response.message);
			render();
			scan.set_focus();
		} catch (error) {
			show_operator_login(Boolean(state.operator), token);
		}
	}

	function open_camera_scanner(on_scan) {
		if (!window.isSecureContext && !["localhost", "127.0.0.1"].includes(window.location.hostname)) {
			frappe.msgprint(__("Camera scanning requires HTTPS. Open the secure ERP site and try again."));
			return false;
		}
		if (!(frappe.ui && frappe.ui.Scanner)) {
			frappe.msgprint(__("Camera scanning is unavailable in this browser. Enter the code manually."));
			return false;
		}
		new frappe.ui.Scanner({
			dialog: true,
			multiple: false,
			on_scan(data) {
				const value = String((data && data.decodedText) || "").trim();
				if (value) on_scan(value);
			},
		});
		return true;
	}

	function scan_operator_qr() {
		open_camera_scanner((value) => {
			const token = operator_token_from_scan(value);
			if (token) login_scanned_operator(token);
		});
	}

	function scan_kanban_qr() {
		if (!state.operator) return scan_operator_qr();
		open_camera_scanner((token) => process_scan(token));
	}

	async function process_scan(raw_value) {
		const value = String(raw_value || "").trim();
		if (!value) return;
		scan.set_value("");
		if (await dispatch_scanner_command(value)) return;
		if (!state.operator || state.awaiting_operator_scan) {
			state.awaiting_operator_scan = false;
			return login_scanned_operator(operator_token_from_scan(value));
		}
		return load_card(value);
	}

	async function dispatch_scanner_command(raw_value) {
		const value = raw_value.toUpperCase();
		const command = value.startsWith("CFG:CMD:") ? value.slice(8) : "";
		if (!command && !value.startsWith("CFG:QTY:")) return false;

		if (value.startsWith("CFG:QTY:")) {
			apply_scanned_quantity(value);
			return true;
		}

		const commands = {
			HELP: show_scanner_help,
			CLEAR: clear_for_next_card,
			NEXT_CARD: clear_for_next_card,
			SWITCH_OPERATOR: prepare_operator_switch,
			END_SESSION: confirm_end_operator_session,
			CAMERA: scan_kanban_qr,
			CAMERA_CARD: scan_kanban_qr,
			START: () => run_context_execution_action("start"),
			REPORT_PROGRESS: () => run_context_execution_action("report_progress"),
			CONFIRM: submit_active_progress,
			CANCEL: cancel_active_dialog,
			DISMISS: dismiss_visible_message,
		};
		if (!commands[command]) {
			set_scanner_message(__("Unknown scanner command: {0}", [command]), "red");
			focus_scanner();
			return true;
		}
		commands[command]();
		return true;
	}

	function run_context_execution_action(action) {
		if (!state.context || !state.context.card) {
			frappe.show_alert({ message: __("Scan a Kanban card first"), indicator: "orange" });
			return focus_scanner();
		}
		const executions = state.context.executions || [];
		const eligible = executions.filter((row) => {
			if (action === "start") {
				return row.status === "Ready" && state.operator.permissions.start;
			}
			return ["Ready", "In Progress", "Paused"].includes(row.status) &&
				state.operator.permissions.report_progress;
		});
		if (eligible.length !== 1) {
			const message = eligible.length
				? __("More than one execution lane is eligible. Select the correct lane on screen.")
				: __("No execution lane is currently eligible for this command.");
			frappe.msgprint({ title: __("Scanner Command Not Applied"), message, indicator: "orange" });
			return;
		}
		if (action === "start") return job_action(eligible[0], "start");
		return progress_dialog(eligible[0]);
	}

	function install_scanner_shortcuts() {
		$(document).off("keydown.cfg_kanban_operator");
		$(document).on("keydown.cfg_kanban_operator", (event) => {
			if (!$(wrapper).is(":visible")) return;
			if (capture_scan_behind_message(event)) return;
			const handlers = {
				F1: show_scanner_help,
				F2: prepare_operator_switch,
				F3: clear_for_next_card,
				F4: scan_kanban_qr,
				F8: confirm_end_operator_session,
			};
			if (!handlers[event.key]) return;
			event.preventDefault();
			handlers[event.key]();
		});
		const $input = scan.$input;
		$input.attr({ autocomplete: "off", inputmode: "none" });
		$input.off("keydown.cfg_scanner").on("keydown.cfg_scanner", (event) => {
			if (event.key !== "Enter" && event.key !== "Tab") return;
			event.preventDefault();
			process_scan($input.val());
		});
		$(wrapper).off("click.cfg_scanner_focus").on("click.cfg_scanner_focus", (event) => {
			if (!$(event.target).is("input, textarea, select, button, a, .modal *")) focus_scanner();
		});
	}

	function capture_scan_behind_message(event) {
		if (!$('.modal:visible').length || state.active_progress_dialog) return false;
		if ($(event.target).is("input, textarea, select")) return false;
		const now = Date.now();
		if (now - state.modal_scan_at > 150) state.modal_scan_buffer = "";
		state.modal_scan_at = now;
		if (event.key === "Enter" || event.key === "Tab") {
			if (!state.modal_scan_buffer) return false;
			event.preventDefault();
			const value = state.modal_scan_buffer;
			state.modal_scan_buffer = "";
			dismiss_visible_message();
			if (value.toUpperCase() !== "CFG:CMD:DISMISS") window.setTimeout(() => process_scan(value), 100);
			return true;
		}
		if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
			state.modal_scan_buffer += event.key;
			event.preventDefault();
			return true;
		}
		return false;
	}

	function dismiss_visible_message() {
		const $modal = $(".modal:visible").last();
		if ($modal.length) $modal.modal("hide");
		window.setTimeout(focus_scanner, 100);
	}

	function focus_scanner() {
		if ($(".modal:visible").length || document.hidden) return;
		window.setTimeout(() => {
			scan.set_value("");
			scan.set_focus();
		}, 80);
	}

	function set_scanner_message(message, color) {
		state.scanner_message = message;
		const indicator_color = color || "green";
		$scanner_status.html(`<div class="cfg-scanner-ready ${indicator_color}">
			<span class="indicator-pill ${indicator_color}">${frappe.utils.escape_html(message)}</span>
			<small>${__("No field selection or deletion is required. Scanner suffix should be Enter.")}</small>
		</div>`);
	}

	function show_scanner_help() {
		const dialog = new frappe.ui.Dialog({
			title: __("Hands-free Scanner Controls"),
			size: "large",
			primary_action_label: __("Close"),
			primary_action: () => dialog.hide(),
		});
		dialog.$body.html(`<div class="cfg-scanner-help">
			<p>${__("Keep this page open in full-screen or kiosk mode. Scan cards directly; the previous number is cleared automatically.")}</p>
			<table class="table table-bordered"><thead><tr><th>${__("Function key")}</th><th>${__("Barcode / QR payload")}</th><th>${__("Action")}</th></tr></thead><tbody>
			<tr><td>F1</td><td><code>CFG:CMD:HELP</code></td><td>${__("Show this guide")}</td></tr>
			<tr><td>F2</td><td><code>CFG:CMD:SWITCH_OPERATOR</code></td><td>${__("Next scan identifies the new operator")}</td></tr>
			<tr><td>F3</td><td><code>CFG:CMD:NEXT_CARD</code></td><td>${__("Clear the display and accept the next card")}</td></tr>
			<tr><td>F4</td><td><code>CFG:CMD:CAMERA_CARD</code></td><td>${__("Open camera scanner")}</td></tr>
			<tr><td>F8</td><td><code>CFG:CMD:END_SESSION</code></td><td>${__("End operator session after confirmation")}</td></tr>
			</tbody></table>
			<p><strong>${__("Operation commands")}</strong>: <code>CFG:CMD:START</code>, <code>CFG:CMD:REPORT_PROGRESS</code>.</p>
			<p><strong>${__("Progress dialog commands")}</strong>: <code>CFG:QTY:GOOD:+1</code>, <code>CFG:QTY:REJECT:+1</code>, <code>CFG:CMD:CONFIRM</code>, <code>CFG:CMD:CANCEL</code>.</p>
			<p><strong>${__("Message control")}</strong>: scan the next card to close an error and continue, or scan <code>CFG:CMD:DISMISS</code> to close it.</p>
			<div class="alert alert-warning">${__("A web page cannot receive scanner keys while the browser address bar is selected. Use full-screen/kiosk mode and configure the scanner to append Enter.")}</div>
		</div>`);
		dialog.onhide = focus_scanner;
		dialog.show();
		const $print = $(`<button class="btn btn-default mr-2">${__("Print Command Labels")}</button>`);
		$print.on("click", configure_scanner_command_sheet);
		dialog.get_primary_btn().before($print);
	}

	function configure_scanner_command_sheet() {
		frappe.prompt([
			{ fieldname: "quantity_steps", label: __("Routine Good Quantity Increments"),
				fieldtype: "Data", reqd: 1, default: "1, 5, 10, 100",
				description: __("Comma-separated positive quantities. Example: 1, 10, 50, 100") },
		], (values) => {
			const steps = String(values.quantity_steps || "").split(",").map((value) => value.trim()).filter(Boolean);
			print_scanner_command_sheet(steps);
		}, __("Configure Command Labels"), __("Generate Printable Sheet"));
	}

	async function print_scanner_command_sheet(quantity_steps) {
		const popup = window.open("", "_blank", "width=1000,height=800");
		if (!popup) {
			frappe.msgprint(__("Allow pop-ups for this site to print scanner command labels."));
			return;
		}
		popup.document.write(`<p style="font-family:Arial;padding:20px">${__("Preparing command labels...")}</p>`);
		try {
			const response = await frappe.call({ method: "cfg_kanban.api.operator.get_scanner_command_sheet",
				args: { quantity_steps } });
			const labels = (response.message || []).map((row) => `<div class="command-label">
				<div class="command-title">${frappe.utils.escape_html(row.label)}</div>
				${row.key ? `<div class="command-key">${frappe.utils.escape_html(row.key)}</div>` : ""}
				<img src="${row.qr_svg}" alt="${frappe.utils.escape_html(row.label)}">
				<div class="command-payload">${frappe.utils.escape_html(row.payload)}</div>
			</div>`).join("");
			popup.document.open();
			popup.document.write(`<html><head><meta charset="utf-8"><title>${__("Kanban Scanner Command Labels")}</title>
				<style>@page{size:A4 portrait;margin:8mm}*{box-sizing:border-box}body{font-family:Arial,sans-serif;margin:0;color:#111}.heading{text-align:center;margin-bottom:3mm}.heading h2{margin:0}.sheet{display:grid;grid-template-columns:repeat(2,1fr);gap:3mm}.command-label{height:42mm;border:1.2mm solid #111;border-radius:2mm;padding:2.5mm;display:grid;grid-template-columns:1fr 27mm;grid-template-rows:auto 1fr auto;gap:1mm;break-inside:avoid}.command-title{font-size:4.5mm;font-weight:800}.command-key{grid-column:1;font-size:7mm;font-weight:900;align-self:center}.command-label img{grid-column:2;grid-row:1/4;width:26mm;height:26mm;align-self:center}.command-payload{grid-column:1;font-family:monospace;font-size:2.6mm;font-weight:700;align-self:end;word-break:break-all}.note{text-align:center;font-size:2.8mm;margin-top:3mm}@media print{.no-print{display:none}}</style>
				</head><body><div class="heading"><h2>CFG KANBAN — SCANNER CONTROLS</h2></div><div class="sheet">${labels}</div>
				<div class="note">${__("Configure the fixed scanner to append Enter. Use full-screen or kiosk mode.")}</div>
				<script>window.onload=()=>window.print();<\/script></body></html>`);
			popup.document.close();
		} catch (error) {
			popup.close();
			throw error;
		}
	}

	function apply_scanned_quantity(value) {
		const active = state.active_progress_dialog;
		if (!active || !active.dialog || !active.dialog.$wrapper.is(":visible")) {
			set_scanner_message(__("Quantity command ignored: open Report Progress first"), "orange");
			focus_scanner();
			return;
		}
		const match = /^CFG:QTY:(GOOD|REJECT):([+-]?\d+(?:\.\d+)?)$/i.exec(value);
		if (!match) {
			frappe.show_alert({ message: __("Invalid quantity scan"), indicator: "red" });
			return focus_progress_scanner();
		}
		const fieldname = match[1].toUpperCase() === "GOOD" ? "good_qty" : "reject_qty";
		const field = active.dialog.get_field(fieldname);
		if (!field || field.df.read_only) {
			frappe.show_alert({ message: __("You are not authorized to change this quantity"), indicator: "red" });
			return focus_progress_scanner();
		}
		const instruction = match[2];
		const current = Number(active.dialog.get_value(fieldname) || 0);
		const next = instruction.startsWith("+") || instruction.startsWith("-")
			? current + Number(instruction)
			: Number(instruction);
		active.dialog.set_value(fieldname, Math.max(0, next));
		frappe.show_alert({ message: __("{0} quantity: {1}", [match[1], Math.max(0, next)]), indicator: "green" });
		focus_progress_scanner();
	}

	function submit_active_progress() {
		const active = state.active_progress_dialog;
		if (!active || !active.dialog || !active.dialog.$wrapper.is(":visible")) {
			set_scanner_message(__("Nothing is ready to submit"), "orange");
			return focus_scanner();
		}
		active.dialog.get_primary_btn().trigger("click");
	}

	function cancel_active_dialog() {
		const active = state.active_progress_dialog;
		if (active && active.dialog && active.dialog.$wrapper.is(":visible")) active.dialog.hide();
		else focus_scanner();
	}

	function focus_progress_scanner() {
		const active = state.active_progress_dialog;
		if (!active || !active.dialog) return;
		window.setTimeout(() => {
			active.dialog.set_value("scanner_command", "");
			active.dialog.get_field("scanner_command").set_focus();
		}, 50);
	}

	async function load_card(token) {
		if (!token) return;
		if (!state.operator) return show_operator_login(false);
		try {
			const response = await frappe.call({
				method: "cfg_kanban.api.operator.get_card_context",
				args: { token, operator_session_token: state.session_token },
				freeze: true,
				freeze_message: __("Loading Kanban card..."),
			});
			state.context = response.message;
			set_scanner_message(__("Card loaded. Scan another card at any time."), "green");
			render();
		} finally {
			focus_scanner();
		}
	}

	function render() {
		$root.empty();
		set_scanner_message(state.awaiting_operator_scan
			? __("Scan the NEXT OPERATOR credential now")
			: (state.operator ? __("Scanner ready for Kanban card") : __("Scanner ready for operator credential")),
			state.awaiting_operator_scan ? "orange" : "green");
		$card_camera.toggle(Boolean(state.operator));
		if (!state.operator) {
			const setup = state.access && state.access.can_manage_operators
				? `<p><a class="btn btn-default" href="/app/cfg-kanban-operator-profile">${__("Manage Operator Profiles")}</a></p>` : "";
			const development_proxy = state.access && state.access.can_use_development_proxy
				? `<p><button class="btn btn-warning cfg-development-proxy">${__("Use Development Employee Proxy")}</button></p>` : "";
			$root.html(`<div class="frappe-card text-center p-5"><h4>${__("Operator identification required")}</h4>
				<p class="text-muted">${__("Scan your personal operator QR. The terminal remains signed in to ERPNext.")}</p>
				<button class="btn btn-primary cfg-operator-camera">${__("Scan Operator QR with Camera")}</button>
				<button class="btn btn-default cfg-operator-login">${__("Enter Credential / PIN")}</button>
				${development_proxy}${setup}<small class="text-muted">${__("ERP terminal user")}: ${frappe.utils.escape_html((state.access && state.access.terminal_user) || "")}</small></div>`);
			$root.find(".cfg-operator-camera").on("click", scan_operator_qr);
			$root.find(".cfg-operator-login").on("click", () => show_operator_login(false));
			$root.find(".cfg-development-proxy").on("click", show_development_proxy_login);
			focus_scanner();
			return;
		}
		const e = frappe.utils.escape_html;
		$root.append(`<div class="alert alert-info d-flex justify-content-between align-items-center">
			<div><strong>${__("Active operator")}: ${e(state.operator.employee_name)}</strong>
			<span class="ml-2">${e(state.operator.employee)} · ${e(state.operator.kanban_role || "")}</span>
			${state.operator.development_proxy ? `<span class="indicator-pill orange ml-2">${__("Administrator Proxy")}</span>` : ""}</div>
			<div>${e(state.operator.station || "")}</div></div>`);
		if (state.access && state.access.can_use_development_proxy) {
			$("<button class='btn btn-warning btn-sm mb-3'>" + __("Change Development Proxy Employee") + "</button>")
				.appendTo($root).on("click", show_development_proxy_login);
		}
		if (!state.context) {
			$root.append(`<div class="empty-state text-muted text-center p-5">
				${__("Scan a Kanban QR code or enter its card number to begin.")}</div>`);
			focus_scanner();
			return;
		}
		const { card, master, cycle, effective_work_order, work_order_attention, selected_job_card, executions, operation_summaries, process_tasks, service_tasks, service_identity_card, work_orders, route_warnings } = state.context;
		const cycle_label = cycle ? `${document_link("cfg-kanban-cycle", cycle.name)}${status_line(cycle.status)}` : __("No active cycle");
		const work_order_label = effective_work_order
			? `${document_link("work-order", effective_work_order.name)}${status_line(effective_work_order.status, effective_work_order.docstatus)}`
			: document_link("work-order", null);
		$root.append(`<div class="frappe-card p-4 mb-4">
			<div class="d-flex justify-content-between align-items-start flex-wrap">
				<div><div class="d-flex align-items-center flex-wrap"><h3 class="mr-3 mb-1">${e(card.card_number)}</h3>
					<span class="indicator-pill blue mb-1">${e(card.card_type || __("Unspecified Card Type"))}</span></div>
					<div><strong>${e(card.item_code || master.item_code || card.asset || card.location_reference || card.task_schedule || "")}</strong>${card.kanban_qty ? ` · ${e(card.kanban_qty)} ${e(card.stock_uom || master.stock_uom || "")}` : ""}</div>
					<div class="text-muted">${e(master.control_type || card.card_behavior || "")} ${master.card_representation ? "· " + e(master.card_representation) : ""}${card.operation ? " · " + e(card.operation) : ""}</div></div>
				<div class="text-right"><small>${__("Card Status")}</small><br><span class="indicator-pill ${indicator(card.current_state)}">${e(card.current_state)}</span></div>
			</div><hr>
			<div class="row">
				<div class="col-sm-2"><small>${__("Master")}</small><div>${e(master.kanban_name || __("Service identity"))}</div></div>
				<div class="col-sm-2"><small>${__("Quantity")}</small><div>${e(card.kanban_qty)}</div></div>
				<div class="col-sm-2"><small>${__("Automation")}</small><div>${e(master.automation_level)}</div></div>
				<div class="col-sm-3"><small>${__("Cycle")}</small><div>${cycle_label}</div></div>
				<div class="col-sm-3"><small>${__("Effective Work Order")}</small><div>${work_order_label}</div></div>
			</div><div class="cfg-card-actions mt-4"></div>
		</div>`);
		(route_warnings || []).forEach((warning) => $root.append(
			`<div class="alert alert-warning">${e(warning)}</div>`));
		if (work_order_attention) {
			const attention_class = work_order_attention.severity === "info" ? "alert-info" : "alert-warning";
			const button_class = work_order_attention.severity === "info" ? "btn-info" : "btn-warning";
			$root.append(`<div class="alert ${attention_class} d-flex justify-content-between align-items-center flex-wrap">
				<div><strong>${__("ERP Work Order attention required")}</strong><br>${e(work_order_attention.message)}</div>
				<a class="btn ${button_class} btn-sm mt-2" href="/app/work-order/${encodeURIComponent(work_order_attention.work_order)}">${__("Open Work Order")}</a>
			</div>`);
		}
		if ((work_orders || []).length > 1) {
			$root.append(`<div class="frappe-card p-3 mb-3"><strong>${__("Work Orders claiming this Cycle")}</strong><div>${work_orders.map((row) =>
				`${document_link("work-order", row.name)} · ${e(row.status)}`).join("<br>")}</div></div>`);
		}
		const $actions = $root.find(".cfg-card-actions");
		if (service_identity_card) {
			$actions.append(`<a class="btn btn-primary mr-2" href="/app/kanban-tasks">${__("Open Service Tasks")}</a>`);
			if (card.card_type === "Task Card" && state.operator.permissions.task_start) {
				add_action($actions, __("Request Task"), "btn-warning", async () => {
					await frappe.call({ method: "cfg_kanban.api.task.request_task", args: {
						schedule_name: card.task_schedule, request_source: `Task Card ${card.card_number}`,
						event_token: frappe.utils.get_random(16), operator_session_token: state.session_token,
					}, freeze: true });
					await load_card(card.qr_code);
				});
			}
			render_service_tasks(service_tasks || []);
			return;
		}
		if (!cycle && card.current_state === "Available" && state.operator.permissions.consume) {
			$("<button class='btn btn-primary mr-2'>" + __("Consume / Trigger") + "</button>")
				.appendTo($actions).on("click", consume_card);
		}
		if (cycle) {
			if (cycle.runtime_allocation) {
				$root.append(`<div class="alert ${cycle.short_cycle ? "alert-warning" : "alert-info"}">
					<strong>${__("Runtime allocation")}: ${e(cycle.effective_cycle_qty || cycle.planned_qty)} / ${e(cycle.nominal_card_qty || card.kanban_qty)} ${e(card.stock_uom || "")}</strong><br>
					${__("Selected Job Card")}: ${document_link("job-card", cycle.selected_job_card)}
					${selected_job_card ? status_line(selected_job_card.status, selected_job_card.docstatus) : ""}
					${selected_job_card ? `<small>${__("ERP completed")}: ${e(selected_job_card.total_completed_qty || 0)} / ${e(selected_job_card.for_quantity || 0)}</small>` : ""}
					${cycle.short_cycle_reason ? `<br>${__("Short-cycle reason")}: ${e(cycle.short_cycle_reason)}` : ""}</div>`);
			}
			$("<button class='btn btn-default mr-2'>" + __("View Timeline") + "</button>")
				.appendTo($actions).on("click", () => show_timeline(cycle.name));
		}
		render_process_tasks(process_tasks || []);
		render_summaries(operation_summaries || []);
		render_executions(executions || []);
	}

	function render_service_tasks(tasks) {
		const e = frappe.utils.escape_html;
		const $section = $(`<div><h4>${__("Open Service Tasks for this Card")}</h4></div>`).appendTo($root);
		if (!tasks.length) return $section.append(`<div class="text-muted p-3">${__("No open tasks match this identity.")}</div>`);
		tasks.forEach((task) => $section.append(`<div class="frappe-card p-3 mb-2"><strong>${e(task.task_name)}</strong>
			<span class="indicator-pill ${indicator(task.status)} ml-2">${e(task.status)}</span><br>
			<small>${__("Priority")}: ${e(task.priority)} · ${__("Due")}: ${e(task.due_on || "-")}</small></div>`));
	}

	function render_process_tasks(tasks) {
		if (!tasks.length) return;
		const e = frappe.utils.escape_html;
		const $section = $(`<div><h4>${__("Production Process Tasks")}</h4></div>`).appendTo($root);
		tasks.forEach((task) => {
			const reuse = task.reused_from_task
				? `<div class="text-success"><small>${__("Valid completion reused from")}: ${e(task.reused_from_task)}</small></div>` : "";
			const $row = $(`<div class="frappe-card p-3 mb-2"><div class="row align-items-center">
				<div class="col-md-4"><strong>${e(task.sequence)}. ${e(task.task_name)}</strong><br>
					<small>${e(task.task_type || "")} · ${e(task.trigger_point || "")}</small>
					${task.linked_operation ? `<div class="text-muted">${__("Operation")}: ${e(task.linked_operation)}</div>` : ""}${reuse}</div>
				<div class="col-md-2"><span class="indicator-pill ${indicator(task.status)}">${e(task.status)}</span></div>
				<div class="col-md-3">${task.workstation ? `${__("Workstation")}: ${e(task.workstation)}` : ""}
					${task.valid_until ? `<br><small>${__("Valid until")}: ${e(task.valid_until)}</small>` : ""}</div>
				<div class="col-md-3 text-right cfg-task-actions"></div>
			</div></div>`).appendTo($section);
			const $buttons = $row.find(".cfg-task-actions");
			if (task.status === "Ready" && state.operator.permissions.task_start) {
				add_action($buttons, __("Start Task"), "btn-primary", () => process_task_dialog(task, "Start"));
			}
			if (["Ready", "In Progress"].includes(task.status) && state.operator.permissions.task_complete) {
				add_action($buttons, __("Complete Task"), "btn-success", () => process_task_dialog(task, "Complete"));
			}
			if (task.status === "Awaiting Verification" && state.operator.permissions.task_verify) {
				add_action($buttons, __("Verify Task"), "btn-warning", () => process_task_dialog(task, "Verify"));
			}
		});
	}

	async function process_task_dialog(task, action) {
		const response = await frappe.call({ method: "cfg_kanban.api.process_task.get_task_form", args: {
			task_name: task.name, capture_on: action, operator_session_token: state.session_token,
		} });
		const details = response.message.task;
		const definitions = response.message.fields || [];
		const checklist = (details.checklist || "").split("\n").map((item) => item.trim()).filter(Boolean);
		const fields = [
			{ fieldtype: "HTML", options: `<p><strong>${frappe.utils.escape_html(details.task_name)}</strong><br>${frappe.utils.escape_html(details.trigger_point || "")}</p>` },
			...checklist.map((item, index) => ({ fieldname: `check_${index}`, label: item, fieldtype: "Check",
				reqd: action === "Complete" })),
			...definitions.map(dialog_field),
			{ fieldname: "notes", label: __("Notes"), fieldtype: "Small Text" },
		];
		const method = { Start: "start", Complete: "complete", Verify: "verify" }[action];
		const dialog = new frappe.ui.Dialog({ title: __(`${action} Process Task`), fields,
			primary_action_label: __(action), primary_action: async (values) => {
				const dynamic_values = definitions.map((definition) => ({ field_key: definition.field_key,
					label: definition.label, field_type: definition.field_type,
					value: values[`dynamic_${definition.field_key}`], unit: definition.unit }));
				const checklist_results = checklist.map((item, index) => ({ item, completed: values[`check_${index}`] ? 1 : 0 }));
				const args = {
					task_name: task.name, operator_session_token: state.session_token,
					values: dynamic_values, notes: values.notes,
				};
				if (action === "Complete") args.checklist_results = checklist_results;
				await frappe.call({ method: `cfg_kanban.api.process_task.${method}`, args, freeze: true });
				dialog.hide();
				await load_card(state.context.card.qr_code);
			} });
		dialog.show();
	}

	function render_summaries(summaries) {
		if (!summaries.length) return;
		const e = frappe.utils.escape_html;
		const $section = $(`<div><h4>${__("Operation Results")}</h4></div>`).appendTo($root);
		summaries.forEach((row) => $section.append(`<div class="frappe-card p-3 mb-2">
			<div class="row"><div class="col-md-3"><strong>${e(row.sequence)}. ${e(row.operation)}</strong><br><small>${e(row.execution_mode)}</small></div>
			<div class="col-md-2"><span class="indicator-pill ${indicator(row.status)}">${e(row.status)}</span></div>
			<div class="col-md-2">${__("Lanes")}: ${e(row.completed_execution_count || 0)} / ${e(row.execution_count || 0)}<br>${__("Allocated")}: ${e(row.allocated_qty || 0)}</div>
			<div class="col-md-3">${__("Combined Good")}: ${e(row.good_qty || 0)} / ${e(row.target_qty || 0)}<br>${__("Reject")}: ${e(row.reject_qty || 0)}</div>
			<div class="col-md-2">${__("Released")}: ${e(row.released_qty || 0)}<br>${__("Input")}: ${e(row.input_available_qty || 0)}</div></div>
		</div>`));
	}

	async function consume_card() {
		const card = state.context.card;
		if (["Process Kanban", "Station Kanban"].includes(card.card_type)) {
			return propose_runtime_selection(card);
		}
		await frappe.call({
			method: "cfg_kanban.api.scan.scan",
			args: { token: card.qr_code, action: "consume", event_token: frappe.utils.get_random(16),
				operator_session_token: state.session_token },
			freeze: true,
			freeze_message: __("Creating Kanban signal..."),
		});
		frappe.show_alert({ message: __("Kanban signal created"), indicator: "green" });
		await load_card(card.qr_code);
	}

	async function propose_runtime_selection(card) {
		const response = await frappe.call({
			method: "cfg_kanban.api.operator.preview_runtime_selection",
			args: { card_name: card.name, operator_session_token: state.session_token }, freeze: true,
			freeze_message: __("Finding eligible production work..."),
		});
		let proposal = response.message;
		const candidate_options = proposal.candidates.map((candidate) => ({
			label: candidate.label, value: candidate.job_card,
		}));
		let dialog;
		const proposal_html = (value) => `<div class="mb-3">
			<b>${__("Item")}</b>: ${frappe.utils.escape_html(value.item_code || card.item_code)}<br>
			<b>${__("Work Order")}</b>: ${document_link("work-order", value.work_order)} · ${frappe.utils.escape_html(value.work_order_status)}<br>
			<b>${__("Job Card")}</b>: ${document_link("job-card", value.job_card)} · ${frappe.utils.escape_html(value.job_card_status)}
			${value.is_recommended ? `<span class="indicator-pill green ml-2">${__("Recommended")}</span>` : `<span class="indicator-pill orange ml-2">${__("Override")}</span>`}<br>
			<b>${__("Operation / Workstation")}</b>: ${frappe.utils.escape_html(value.operation)} / ${frappe.utils.escape_html(value.workstation || "-")}<hr>
			<b>${__("Nominal Card Qty")}</b>: ${value.nominal_qty}<br>
			<b>${__("Remaining Job Card Demand")}</b>: ${value.remaining_job_card_qty}<br>
			<b>${__("Available Input")}</b>: ${value.available_input_qty}<br>
			<h4>${__("Effective Cycle Qty")}: ${value.effective_cycle_qty}</h4>
			${value.short_cycle_reason ? `<div class="text-warning"><b>${__("Short cycle")}</b>: ${frappe.utils.escape_html(value.short_cycle_reason)}</div>` : ""}</div>`;
		dialog = new frappe.ui.Dialog({
			title: __("Confirm Runtime Allocation"),
			fields: [
				{ fieldname: "selected_job_card", label: __("Eligible Work Order / Job Card"), fieldtype: "Select",
					options: candidate_options, default: proposal.recommended_job_card, reqd: 1,
					description: __("The system recommendation is selected first. Only item-, operation-, company-, status-, input-, and workstation-eligible choices are listed."),
					onchange: async () => {
						if (!dialog) return;
						const selected = dialog.get_value("selected_job_card");
						if (!selected) return;
						const changed = await frappe.call({ method: "cfg_kanban.api.operator.preview_runtime_selection",
							args: { card_name: card.name, job_card: selected,
								operator_session_token: state.session_token } });
						proposal = changed.message;
						dialog.fields_dict.proposal_html.$wrapper.html(proposal_html(proposal));
						dialog.set_df_property("override_reason", "reqd", !proposal.is_recommended);
						dialog.set_df_property("override_reason", "hidden", proposal.is_recommended);
					},
				},
				{ fieldname: "proposal_html", fieldtype: "HTML", options: proposal_html(proposal) },
				{ fieldname: "override_reason", label: __("Override Reason"), fieldtype: "Small Text", hidden: 1,
					description: __("Required when the operator chooses a different eligible option from the system recommendation.") },
				{ fieldname: "confirmation", label: __("Operator Confirmation / Notes"), fieldtype: "Small Text", reqd: 1,
					description: proposal.short_cycle ? __("Confirm that the reduced quantity and reason are understood.") : __("Confirm the proposed Work Order, Job Card, and quantity.") },
			],
			primary_action_label: __("Confirm and Allocate"),
			primary_action: async (values) => {
				await frappe.call({ method: "cfg_kanban.api.operator.confirm_runtime_selection", args: {
					card_name: card.name, job_card: values.selected_job_card,
					confirmation: values.confirmation, override_reason: values.override_reason,
					operator_session_token: state.session_token,
				}, freeze: true, freeze_message: __("Allocating production work...") });
				dialog.hide();
				await load_card(card.qr_code);
			},
		});
		dialog.show();
	}

	function render_executions(executions) {
		if (!executions.length) return;
		const e = frappe.utils.escape_html;
		const $section = $("<div><h4>" + __("Job Card Execution Lanes") + "</h4></div>").appendTo($root);
		executions.forEach((row) => {
			const $row = $(`<div class="frappe-card p-3 mb-2">
				<div class="row align-items-center">
				<div class="col-md-3"><strong>${e(row.sequence)}.${e(row.lane_sequence || 1)} ${e(row.operation)}</strong><div class="text-muted">${e(row.workstation || "")}</div>
					<small>${__("Job Card")}: ${document_link("job-card", row.job_card)}</small>
					${status_line(row.job_card_status, row.job_card_docstatus)}
					<small>${__("ERP completed")}: ${e(row.job_card_completed_qty || 0)} / ${e(row.job_card_target_qty || 0)}</small>
					${(row.good_qty || 0) > (row.job_card_completed_qty || 0) ? `<div class="text-warning"><small>${__("Kanban progress is awaiting ERP Job Card entry")}</small></div>` : ""}</div>
				<div class="col-md-2"><span class="indicator-pill ${indicator(row.status)}">${e(row.status)}</span></div>
				<div class="col-md-3">${__("Allocated")}: ${e(row.allocated_qty || row.target_qty || 0)}<br>${__("Good")}: ${e(row.good_qty || 0)}<br>${__("Released")}: ${e(row.released_qty || 0)}</div>
				<div class="col-md-4 text-right cfg-execution-actions"></div>
				</div></div>`).appendTo($section);
			const $buttons = $row.find(".cfg-execution-actions");
			if (row.status === "Ready" && state.operator.permissions.start) add_action($buttons, __("Start"), "btn-primary", () => job_action(row, "start"));
			if (["Ready", "In Progress", "Paused"].includes(row.status) && state.operator.permissions.report_progress) add_action($buttons, __("Report Progress"), "btn-default", () => progress_dialog(row));
			if (row.status === "In Progress" && !row.runtime_allocation && state.operator.permissions.complete) add_action($buttons, __("Complete"), "btn-default", () => job_action(row, "complete"));
			if (row.runtime_allocation && row.job_card_needs_submit && state.operator.permissions.complete) {
				add_action($buttons, __("Complete Job Card"), "btn-primary", () => job_action(row, "complete"));
			}
			if (row.runtime_allocation && (row.processed_qty || 0) >= (row.target_qty || 0) && row.can_close_runtime_cycle && state.operator.permissions.complete) {
				add_action($buttons, __("Close Kanban Cycle"), "btn-success", () => close_runtime_cycle(row));
			}
			if (row.runtime_allocation && (row.processed_qty || 0) >= (row.target_qty || 0) && !row.can_close_runtime_cycle) {
				const $blocked = $("<button class='btn btn-sm btn-warning ml-1'>" + __("ERP Update Required") + "</button>").appendTo($buttons);
				$blocked.on("click", () => frappe.msgprint({ title: __("Cannot Close Kanban Cycle"),
					message: e(row.close_block_reason || __("ERP Work Order and Job Card are not ready.")), indicator: "orange" }));
			}
		});
	}

	async function close_runtime_cycle(row) {
		const values = await new Promise((resolve) => frappe.prompt([
			{ fieldname: "notes", label: __("Completion Notes"), fieldtype: "Small Text" },
		], resolve, __("Close Kanban Cycle"), __("Close Cycle and Release Card")));
		const response = await frappe.call({ method: "cfg_kanban.api.operator.complete_runtime_cycle", args: {
			execution_name: row.name, notes: values.notes,
			operator_session_token: state.session_token,
		}, freeze: true });
		const result = response.message;
		frappe.show_alert({ message: result.job_card_target_reached
			? __("Cycle completed and ERPNext Job Card submitted")
			: __("Cycle completed; reusable card is available for the remaining Job Card demand"), indicator: "green" });
		await load_card(state.context.card.qr_code);
	}

	function document_link(route, name) {
		if (!name) return `<span class="text-muted">${__("Not assigned")}</span>`;
		return `<a href="/app/${route}/${encodeURIComponent(name)}">${frappe.utils.escape_html(name)}</a>`;
	}

	function status_line(status, docstatus) {
		if (!status) return "";
		const e = frappe.utils.escape_html;
		const draft_note = docstatus === 0 ? ` · ${__("Draft")}` : "";
		return `<div class="mt-1"><span class="indicator-pill ${indicator(status)}">${e(status)}${draft_note}</span></div>`;
	}

	function add_action($parent, label, cls, fn) {
		$("<button class='btn btn-sm " + cls + " ml-1'>" + label + "</button>").appendTo($parent).on("click", fn);
	}

	async function job_action(row, action) {
		await frappe.call({ method: "cfg_kanban.api.operator.run_job_card_action",
			args: { execution_name: row.name, action, event_token: frappe.utils.get_random(16),
				operator_session_token: state.session_token }, freeze: true });
		frappe.show_alert({ message: __("Job Card updated"), indicator: "green" });
		await load_card(state.context.card.qr_code);
	}

	async function progress_dialog(row) {
		const response = await frappe.call({ method: "cfg_kanban.api.operator.get_execution_form",
			args: { execution_name: row.name, capture_on: "Progress",
				operator_session_token: state.session_token } });
		const definitions = response.message.fields || [];
		const fields = [
			{ fieldname: "scanner_command", label: __("Scanner Command"), fieldtype: "Data",
				description: __("Scan quantity command cards here; no keypad is required.") },
			{ fieldtype: "HTML", options: `<div class="alert alert-info py-2">
				<strong>${__("Hands-free examples")}</strong>: <code>CFG:QTY:GOOD:+1</code> ·
				<code>CFG:QTY:REJECT:+1</code> · <code>CFG:CMD:CONFIRM</code> · <code>CFG:CMD:CANCEL</code>
			</div>` },
			{ fieldname: "good_qty", label: __("Good Qty"), fieldtype: "Float", reqd: 1 },
			{ fieldname: "reject_qty", label: __("Reject Qty"), fieldtype: "Float", default: 0,
				read_only: !state.operator.permissions.report_reject },
			{ fieldname: "notes", label: __("Notes"), fieldtype: "Small Text" },
			{ fieldtype: "Section Break", label: __("Operation Checks") },
			...definitions.map(dialog_field),
		];
		const dialog = new frappe.ui.Dialog({
			title: __("Report Progress: {0}", [row.operation]), fields,
			primary_action_label: __("Submit Progress"),
			primary_action: async (values) => {
				const dynamic_values = definitions.map((definition) => ({
					field_key: definition.field_key, label: definition.label,
					field_type: definition.field_type, value: values[`dynamic_${definition.field_key}`], unit: definition.unit,
				}));
				await frappe.call({ method: "cfg_kanban.api.operator.submit_progress", args: {
					execution_name: row.name, good_qty: values.good_qty, reject_qty: values.reject_qty,
					notes: values.notes, values: dynamic_values, event_token: frappe.utils.get_random(16),
					operator_session_token: state.session_token,
				}, freeze: true });
				dialog.hide();
				frappe.show_alert({ message: __("Progress recorded"), indicator: "green" });
				await load_card(state.context.card.qr_code);
			},
		});
		state.active_progress_dialog = { dialog, row };
		dialog.onhide = () => {
			if (state.active_progress_dialog && state.active_progress_dialog.dialog === dialog) {
				state.active_progress_dialog = null;
			}
			focus_scanner();
		};
		dialog.show();
		const command_field = dialog.get_field("scanner_command");
		command_field.$input.attr({ autocomplete: "off", inputmode: "none" });
		command_field.$input.on("keydown.cfg_progress_scanner", (event) => {
			if (event.key !== "Enter" && event.key !== "Tab") return;
			event.preventDefault();
			process_scan(command_field.$input.val());
		});
		focus_progress_scanner();
	}

	function dialog_field(definition) {
		const types = { Data: "Data", Int: "Int", Float: "Float", Check: "Check", Select: "Select",
			Date: "Date", Datetime: "Datetime", Text: "Small Text" };
		return { fieldname: `dynamic_${definition.field_key}`, label: definition.label,
			fieldtype: types[definition.field_type] || "Data", reqd: definition.mandatory,
			options: definition.options, default: definition.default_value, read_only: definition.read_only,
			description: definition.unit ? `${__("Unit")}: ${definition.unit}` : "" };
	}

	async function show_timeline(cycle_name) {
		const response = await frappe.call({ method: "cfg_kanban.api.operator.get_cycle_timeline",
			args: { cycle_name, operator_session_token: state.session_token } });
		const e = frappe.utils.escape_html;
		const rows = response.message.events.map((event) => `<div class="mb-3">
			<strong>${e(event.event_type)}</strong> <span class="text-muted">${e(event.event_datetime)}</span>
			<div>${e(event.previous_state || "")} ${event.new_state ? "→ " + e(event.new_state) : ""}${event.qty ? " · " + e(event.qty) : ""}</div>
			${event.reference_name ? `<small>${e(event.reference_doctype)}: ${e(event.reference_name)}</small>` : ""}</div>`).join("");
		const dialog = new frappe.ui.Dialog({ title: __("Cycle Timeline: {0}", [cycle_name]), size: "large" });
		dialog.$body.html(rows || `<div class="text-muted">${__("No events recorded yet.")}</div>`);
		dialog.show();
	}

	function indicator(status) {
		if (["Available", "Ready", "Completed", "Produced"].includes(status)) return "green";
		if (["Blocked", "Failed", "Cancelled"].includes(status)) return "red";
		if (["In Progress", "In Production", "Production Released"].includes(status)) return "blue";
		return "orange";
	}

	load_console();
};
