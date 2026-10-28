frappe.pages["kanban-operator"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Kanban Operator"),
		single_column: true,
	});

	const session_key = "cfg_kanban_operator_session";
	const command_print_key = "cfg_kanban_command_print_selection_v1";
	const live_poll_ms = 12000;
	const manual_scroll_guard_ms = 8000;
	const state = { context: null, operator: null, access: null,
		session_token: localStorage.getItem(session_key), awaiting_operator_scan: false,
		active_progress_dialog: null, active_material_trace_dialog: null,
		active_command_dialog: null, active_crew_dialog: null,
		pending_process_task: null, scanner_message: __("Scanner ready"),
		modal_scan_buffer: "", modal_scan_at: 0, live_revision: null,
		live_request: false, live_timer: null, live_checked_at: null,
		last_operator_interaction_at: 0, auto_scrolling: false, current_live_focus: null };
	const scan = page.add_field({
		label: __("Fixed scanner input — scan any card"),
		fieldtype: "Data",
		fieldname: "scan_token",
		change: () => process_scan(scan.get_value()),
	});
	page.set_primary_action(__("Find Card"), () => process_scan(scan.get_value()), "search");
	page.add_inner_button(__("Open Service Task Panel"), () => frappe.set_route("kanban-tasks"));
	page.add_inner_button(__("Open Logistics Panel"), () => frappe.set_route("kanban-logistics"));
	page.add_inner_button(__("Clear / Next Card (F3)"), clear_for_next_card);
	page.add_inner_button(__("Refresh Operator Session"), refresh_console);
	const $sticky_header = $("<div class='cfg-operator-sticky-shell'></div>").appendTo(page.main);
	const $scanner_status = $(`<div class="cfg-scanner-status" aria-live="polite"></div>`)
		.appendTo($sticky_header);
	const $operator_identity = $("<div class='cfg-production-identity'></div>").appendTo($sticky_header);
	const $current_action = $("<div class='cfg-live-current-action'></div>")
		.appendTo($sticky_header).hide();
	const $root = $("<div class='cfg-kanban-operator cfg-active-work-region mt-3'></div>").appendTo(page.main);
	const $panel_switcher = $(`<div class="cfg-panel-switcher mt-3 mb-3">
		<div><strong>${__("Production Operator Panel")}</strong><small>${__("Use this panel for production cards, operations, and process tasks.")}</small></div>
		<div><button class="btn btn-primary btn-lg open-service-panel">${__("Open Service Task Panel")}</button>
		<button class="btn btn-info btn-lg open-logistics-panel">${__("Open Logistics Panel")}</button></div>
	</div>`).appendTo(page.main);
	$panel_switcher.find(".open-service-panel").on("click", () => frappe.set_route("kanban-tasks"));
	$panel_switcher.find(".open-logistics-panel").on("click", () => frappe.set_route("kanban-logistics"));

	const $card_camera = $(`<div class="cfg-kanban-card-camera mt-3 mb-3">
		<button class="btn btn-primary btn-lg btn-block">
			${__("Scan Kanban Card with Camera")}
		</button>
		<small class="text-muted d-block text-center mt-2">
			${__("Or paste/type the card number in the field above and select Find Card.")}
		</small>
	</div>`).appendTo(page.main).hide();
	$card_camera.find("button").on("click", scan_kanban_qr);
	page.add_inner_button(__("Switch Operator (F2)"), prepare_operator_switch);
	page.add_inner_button(__("End Operator Session (F8)"), confirm_end_operator_session);
	page.add_inner_button(__("Scan Operator QR"), scan_operator_qr);
	page.add_inner_button(__("Camera Scan (F4)"), scan_kanban_qr);
	page.add_inner_button(__("Scanner Help (F1)"), show_scanner_help);
	install_scanner_shortcuts();
	install_live_updates();

	async function load_console() {
		const response = await frappe.call({ method: "cfg_kanban.api.operator.get_console_access" });
		state.access = response.message;
		if (await consume_deep_link()) return;
		await restore_operator();
	}

	async function refresh_console() {
		await load_console();
		frappe.show_alert({ message: state.operator ? __("Operator session refreshed") : __("No active operator session"),
			indicator: state.operator ? "green" : "orange" });
		focus_scanner();
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
		sync_session_from_storage();
		if (!state.session_token) return render();
		const requested_token = state.session_token;
		try {
			const response = await frappe.call({
				method: "cfg_kanban.api.operator.operator_session_status",
				args: { operator_session_token: state.session_token },
			});
			state.operator = response.message;
			render();
		} catch (error) {
			const latest_token = localStorage.getItem(session_key);
			if (latest_token && latest_token !== requested_token) return restore_operator();
			clear_operator(requested_token);
			show_operator_login(false);
		}
	}

	function sync_session_from_storage() {
		const stored_token = localStorage.getItem(session_key);
		if (stored_token === state.session_token) return false;
		state.session_token = stored_token;
		state.operator = null;
		state.context = null;
		state.live_revision = null;
		state.current_live_focus = null;
		state.awaiting_operator_scan = false;
		$operator_identity.empty();
		$current_action.hide().empty();
		return true;
	}

	function clear_operator(expected_token) {
		const stored_token = localStorage.getItem(session_key);
		if (!expected_token || stored_token === expected_token) localStorage.removeItem(session_key);
		state.session_token = null;
		state.operator = null;
		state.context = null;
		state.live_revision = null;
		state.current_live_focus = null;
		state.awaiting_operator_scan = false;
		$operator_identity.empty();
		$current_action.hide().empty();
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
		state.live_revision = null;
		state.current_live_focus = null;
		state.awaiting_operator_scan = false;
		$current_action.hide().empty();
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
		state.last_operator_interaction_at = Date.now();
		scan.set_value("");
		const trace_dialog = state.active_material_trace_dialog?.dialog;
		if (trace_dialog?.$wrapper?.is(":visible")) {
			return run_material_trace_scan(trace_dialog, value);
		}
		const crew_dialog = state.active_crew_dialog?.dialog;
		if (crew_dialog?.$wrapper?.is(":visible")) {
			return handle_crew_dialog_scan(crew_dialog, value);
		}
		if (await dispatch_scanner_command(value)) return;
		if (!state.operator || state.awaiting_operator_scan) {
			state.awaiting_operator_scan = false;
			return login_scanned_operator(operator_token_from_scan(value));
		}
		if (/^CFG:(PROCESS_TASK|SAMPLE):/i.test(value)) return load_process_task_scan(value);
		return load_card(value);
	}

	async function load_process_task_scan(value) {
		const response = await frappe.call({ method: "cfg_kanban.api.process_task.resolve_scan", args: {
			scan_value: value, operator_session_token: state.session_token,
		} });
		state.pending_process_task = response.message.task.name;
		await load_card(response.message.card_qr);
		const task = (state.context.process_tasks || []).find((row) => row.name === state.pending_process_task);
		state.pending_process_task = null;
		if (!task) return frappe.msgprint(__("The scanned Process Task is not available in this cycle."));
		const action = task.status === "Ready" ? "Start" : task.status === "Awaiting Verification" ? "Verify" : "Complete";
		return process_task_dialog(task, action);
	}

	async function dispatch_scanner_command(raw_value) {
		const value = raw_value.toUpperCase();
		const command = value.startsWith("CFG:CMD:") ? value.slice(8) : "";
		if (!command && !value.startsWith("CFG:QTY:")) return false;

		if (value.startsWith("CFG:QTY:")) {
			const active_dialog = state.active_command_dialog;
			if (value.startsWith("CFG:QTY:MATERIAL:") && active_dialog?.$wrapper?.is(":visible")) {
				await handle_confirmation_scanner_value(active_dialog, value);
				return true;
			}
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
			ACTIVATE: () => consume_card(true),
			CONSUME: () => consume_card(true),
			TRIGGER: () => consume_card(true),
			ACCEPT_OWNER: accept_context_job_ownership,
			TRANSFER_OWNER: transfer_context_job_ownership,
			REQUEST_CORRECTION: open_context_correction_request,
			START: () => run_context_execution_action("start"),
			REPORT_PROGRESS: () => run_context_execution_action("report_progress"),
			GO_TO_CURRENT_WORK: go_to_current_work,
			CLOSE_CYCLE: close_context_runtime_cycle,
			PREPARE_MATERIALS: open_scanner_material_preparation,
			RECORD_LOOSE_WIP_USE: open_scanner_loose_wip_usage,
			PREPARE_LOOSE_WIP_CONSUMPTION: open_scanner_loose_wip_consumption,
			PREPARE_RECEIPT: open_scanner_manufacture_receipt,
			SCAN_MATERIALS: open_scanner_material_trace,
			SUBMIT_MATERIALS: submit_scanner_material_entry,
			CREW: () => open_context_crew_control(),
			CREW_OPEN: () => open_context_crew_control("CFG:CMD:CREW_OPEN"),
			CREW_JOIN: () => open_context_crew_control("CFG:CMD:CREW_JOIN"),
			CREW_JOIN_OVERSIGHT: () => open_context_crew_control("CFG:CMD:CREW_JOIN_OVERSIGHT"),
			CREW_JOIN_TEMP: () => open_context_crew_control("CFG:CMD:CREW_JOIN_TEMP"),
			CREW_BREAK: () => open_context_crew_control("CFG:CMD:CREW_BREAK"),
			CREW_RESUME: () => open_context_crew_control("CFG:CMD:CREW_RESUME"),
			CREW_LEAVE: () => open_context_crew_control("CFG:CMD:CREW_LEAVE"),
			CREW_MAIN: () => open_context_crew_control("CFG:CMD:CREW_MAIN"),
			CREW_CONTEXT: () => open_context_crew_control("CFG:CMD:CREW_CONTEXT"),
			CREW_CLOSE: () => open_context_crew_control("CFG:CMD:CREW_CLOSE"),
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

	async function accept_context_job_ownership() {
		const ownership = state.context?.job_ownership;
		if (!ownership?.enabled) {
			return scanner_command_message(__("The scanned Card does not require a Cycle owner."));
		}
		if (ownership.owner) {
			return scanner_command_message(__("This Cycle already has an operator-in-charge."));
		}
		if (!ownership.eligible_to_accept) {
			return scanner_command_message(__("This operator does not carry the required Job Code."));
		}
		const execution = (state.context.executions || []).find((row) =>
			["In Progress", "Ready", "Paused", "Waiting Input"].includes(row.status));
		if (!execution) {
			return scanner_command_message(__("No execution lane is available for ownership acceptance."));
		}
		await frappe.call({
			method: "cfg_kanban.api.operator.accept_job_ownership",
			args: { execution_name: execution.name, operator_session_token: state.session_token },
			freeze: true,
			freeze_message: __("Accepting Cycle ownership..."),
		});
		frappe.show_alert({ message: __("Cycle ownership accepted"), indicator: "green" });
		await load_card(state.context.card.qr_code);
	}

	function go_to_current_work() {
		if (!state.context || !state.current_live_focus) {
			set_scanner_message(__("Scan a Kanban card before navigating to current work"), "orange");
			return focus_scanner();
		}
		scroll_to_live_action(true);
		set_scanner_message(__("Current work displayed"), "green");
	}

	function open_context_correction_request() {
		const execution = crew_execution_context();
		if (!execution) {
			return scanner_command_message(__("Scan an active production Card before reporting a correction."));
		}
		return correction_request_dialog(execution.name);
	}

	function close_context_runtime_cycle() {
		if (!state.context || !state.context.card) {
			return scanner_command_message(__("Scan a Process or Station Kanban card first."));
		}
		if (!state.operator?.permissions?.complete) {
			return scanner_command_message(__("This operator is not authorized to close a Kanban Cycle."));
		}
		const executions = (state.context.executions || []).filter((row) => row.runtime_allocation);
		const eligible = executions.filter((row) =>
			(row.processed_qty || 0) >= (row.target_qty || 0) && row.can_close_runtime_cycle);
		if (eligible.length === 1) return close_runtime_cycle(eligible[0]);
		if (eligible.length > 1) {
			return scanner_command_message(__("More than one runtime Cycle is eligible. Open the correct Process or Station Card before closing."));
		}
		const blocked = executions.find((row) =>
			(row.processed_qty || 0) >= (row.target_qty || 0) && !row.can_close_runtime_cycle);
		return scanner_command_message(blocked?.close_block_reason ||
			__("No runtime Kanban Cycle is currently eligible for closure."));
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
		if ($(event.target).is("input, textarea, select") &&
			$(event.target).closest(".modal:visible").length) return false;
		const now = Date.now();
		if (now - state.modal_scan_at > 150) state.modal_scan_buffer = "";
		state.modal_scan_at = now;
		if (event.key === "Enter" || event.key === "Tab") {
			if (!state.modal_scan_buffer) return false;
			event.preventDefault();
			const value = state.modal_scan_buffer;
			state.modal_scan_buffer = "";
			const active_dialog = state.active_command_dialog;
			const $top_modal = $(".modal:visible").last();
			if (active_dialog && active_dialog.$wrapper &&
				active_dialog.$wrapper.is(":visible") && $top_modal.is(active_dialog.$wrapper)) {
				handle_confirmation_scanner_value(active_dialog, value);
				return true;
			}
			const trace_dialog = state.active_material_trace_dialog?.dialog;
			if (trace_dialog?.$wrapper && trace_dialog.$wrapper.is(":visible") &&
				$top_modal.is(trace_dialog.$wrapper)) {
				run_material_trace_scan(trace_dialog, value);
				return true;
			}
			if (value.toUpperCase() === "CFG:CMD:CONFIRM") {
				confirm_visible_dialog();
				return true;
			}
			if (["CFG:CMD:CANCEL", "CFG:CMD:DISMISS"].includes(value.toUpperCase())) {
				dismiss_visible_message();
				return true;
			}
			dismiss_visible_message();
			window.setTimeout(() => process_scan(value), 100);
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
		if ($modal.length) {
			$modal.one("hidden.bs.modal.cfg_scanner_restore", () => restore_scanner_focus());
			$modal.modal("hide");
		}
		restore_scanner_focus();
	}

	function restore_scanner_focus(attempt = 0) {
		window.setTimeout(() => {
			const $top_modal = $(".modal:visible").last();
			if ($top_modal.length) {
				const command_dialog = state.active_command_dialog;
				if (command_dialog?.$wrapper && $top_modal.is(command_dialog.$wrapper)) {
					return command_dialog.get_field("scanner_command")?.set_focus();
				}
				const progress_dialog = state.active_progress_dialog?.dialog;
				if (progress_dialog?.$wrapper && $top_modal.is(progress_dialog.$wrapper)) {
					return focus_progress_scanner();
				}
				const trace_dialog = state.active_material_trace_dialog?.dialog;
				if (trace_dialog?.$wrapper && $top_modal.is(trace_dialog.$wrapper)) {
					const trace_field = trace_dialog.get_field("trace_scan");
					if (trace_field) return trace_field.set_focus();
				}
				if (attempt < 8) return restore_scanner_focus(attempt + 1);
				return;
			}
			focus_scanner();
		}, attempt ? 80 : 30);
	}

	function confirm_visible_dialog() {
		const $modal = $(".modal:visible").last();
		const $primary = $modal.find(".modal-footer .btn-primary:visible").last();
		if (!$primary.length || $primary.prop("disabled")) {
			frappe.show_alert({ message: __("This message has no confirm action"), indicator: "orange" });
			return;
		}
		$primary.trigger("click");
	}

	function focus_scanner() {
		if ($(".modal:visible").length || document.hidden) return;
		window.setTimeout(() => {
			scan.set_value("");
			const input = scan.$input && scan.$input.get(0);
			if (input) {
				// Keep the fixed scanner armed without pulling the operator away from
				// the active operation, task, or material-control section.
				input.focus({ preventScroll: true });
				return;
			}
			const scroll_container = live_scroll_container();
			const previous_scroll = scroll_container ? scroll_container.scrollTop : 0;
			scan.set_focus();
			if (scroll_container) scroll_container.scrollTop = previous_scroll;
		}, 80);
	}

	function install_live_updates() {
		if (state.live_timer) window.clearInterval(state.live_timer);
		state.live_timer = window.setInterval(check_live_updates, live_poll_ms);
		$(document).off("visibilitychange.cfg_kanban_live").on("visibilitychange.cfg_kanban_live", () => {
			if (!document.hidden) window.setTimeout(check_live_updates, 500);
		});
		$(wrapper).off("wheel.cfg_kanban_live touchstart.cfg_kanban_live pointerdown.cfg_kanban_live")
			.on("wheel.cfg_kanban_live touchstart.cfg_kanban_live pointerdown.cfg_kanban_live", () => {
				if (!state.auto_scrolling) state.last_operator_interaction_at = Date.now();
			});
	}

	async function check_live_updates(force) {
		if (state.live_request || document.hidden || !$(wrapper).is(":visible") ||
			!state.operator || !state.context || !state.context.card ||
			(!force && $(".modal:visible").length)) return;
		state.live_request = true;
		set_live_connection(__("Checking"), "orange");
		try {
			const response = await frappe.call({
				method: "cfg_kanban.api.operator.get_card_live_revision",
				args: { token: state.context.card.qr_code || state.context.card.card_number,
					operator_session_token: state.session_token },
				error: () => {},
			});
			const live = response.message || {};
			state.live_checked_at = live.checked_at;
			if (!state.live_revision) {
				// The first revision may arrive after a supervisor changed the Card while
				// this tab was hidden or a dialog blocked polling. Re-sync the context
				// before accepting that revision as the baseline, otherwise the already
				// changed state is silently treated as current while the screen stays stale.
				await refresh_live_card(live.revision, { initial_sync: true });
				return;
			}
			if (live.revision === state.live_revision) {
				set_live_connection(__("Live"), "green");
				return;
			}
			await refresh_live_card(live.revision);
		} catch (error) {
			set_live_connection(__("Connection interrupted — retrying"), "red");
		} finally {
			state.live_request = false;
		}
	}

	async function refresh_live_card(revision, options = {}) {
		const old_context = state.context;
		const card_token = old_context.card.qr_code || old_context.card.card_number;
		const response = await frappe.call({
			method: "cfg_kanban.api.operator.get_card_context",
			args: { token: card_token, operator_session_token: state.session_token },
			error: () => {},
		});
		if (!state.context || state.context.card.name !== old_context.card.name) return;
		const old_focus = current_live_action(old_context)?.key;
		const scroll_container = live_scroll_container();
		const previous_scroll = scroll_container ? scroll_container.scrollTop : 0;
		const recent_manual_interaction =
			Date.now() - state.last_operator_interaction_at < manual_scroll_guard_ms;
		const refreshed_context = response.message;
		const context_changed = JSON.stringify(old_context) !== JSON.stringify(refreshed_context);
		state.context = refreshed_context;
		state.live_revision = revision;
		const message = describe_live_change(old_context, state.context);
		render();
		const announce_change = !options.initial_sync || context_changed;
		set_live_connection(announce_change ? __("Live — updated") : __("Live"), "green");
		if (announce_change) {
			$root.addClass("cfg-live-update-flash");
			window.setTimeout(() => $root.removeClass("cfg-live-update-flash"), 2200);
			frappe.show_alert({ message, indicator: "blue" }, 7);
		}
		const new_focus = current_live_action(state.context)?.key;
		window.requestAnimationFrame(() => {
			if (recent_manual_interaction && scroll_container) {
				scroll_container.scrollTop = previous_scroll;
			} else if (announce_change && new_focus && (new_focus !== old_focus || message)) {
				scroll_to_live_action(false);
			}
		});
		focus_scanner();
	}

	function set_live_connection(label, colour) {
		const $status = $current_action.find(".cfg-live-connection");
		if (!$status.length) return;
		$status.attr("class", `indicator-pill ${colour || "green"} cfg-live-connection`)
			.text(label);
	}

	function current_live_action(context) {
		if (!context || !context.card) return null;
		const permissions = state.operator?.permissions || {};
		const flow = context.production_material_flow;
		const entries = context.production_stock_entries || [];
		const executions = context.executions || [];
		const process_tasks = context.process_tasks || [];
		const crew_hold = executions.find((row) => row.crew?.compliance_status === "Hold");
		if (crew_hold) return { key: `execution:${crew_hold.name}`, title: __("Crew authorization hold"),
			detail: __("Open Crew Controls for {0} and restore the required active crew", [crew_hold.operation]),
			status: __("Blocked"), colour: "red" };
		if ((flow?.wip_bin_reconciliations || []).length) {
			return { key: "wip-bin-reconciliation", title: __("WIP Bin reconciliation"),
				detail: __("A supervisor must resolve the physical and ERP stock difference"),
				status: __("Blocked"), colour: "red" };
		}
		const blocking_task = process_tasks.find((row) => row.blocking &&
			["Blocked", "Awaiting Verification", "In Progress", "Ready"].includes(row.status));
		if (blocking_task) return { key: `task:${blocking_task.name}`, title: blocking_task.task_name,
			detail: process_task_next_instruction(blocking_task), status: blocking_task.status,
			colour: indicator(blocking_task.status) };
		if (!context.cycle && context.card.current_state === "Available" && permissions.consume) {
			return { key: "active-card", title: __("Activate production card"),
				detail: __("Consume or trigger this Card to create the next production Cycle"),
				status: __("Ready"), colour: "green" };
		}
		if (flow?.has_shortage || flow?.restricted_material_attention) {
			return { key: "production-material", title: __("Production material control"),
				detail: flow.has_shortage ? __("Material shortage requires attention") :
					__("A restricted component needs an authorized material controller"),
				status: __("Action Required"), colour: "orange" };
		}

		const active_execution = executions.find((row) => ["In Progress", "Paused"].includes(row.status));
		const ready_execution = executions.find((row) => row.status === "Ready");
		const next_execution = active_execution || ready_execution;
		const next_job = next_execution
			? (flow?.jobs || []).find((row) => row.name === next_execution.job_card)
			: null;
		const entry_for_job = (purpose) => entries.find((row) => row.docstatus === 0 &&
			(!purpose || row.purpose === purpose) &&
			(!next_execution || !row_effective_job_card(row) ||
				row_effective_job_card(row) === next_execution.job_card));
		const pending_transfer = entry_for_job("Material Transfer for Manufacture");
		if (pending_transfer) return material_entry_live_action(pending_transfer);

		if (next_execution?.status === "Ready") {
			if (next_job?.has_pending_materials && permissions.material_transfer) {
				return { key: `material-job:${next_job.name}`, title: __("Issue operation materials"),
					detail: __("Prepare and confirm materials for {0} before starting", [next_job.operation]),
					status: __("Next Step"), colour: "orange" };
			}
			if (permissions.start) return execution_live_action(next_execution, "start");
		}

		if (active_execution) {
			if (!active_execution.job_card_target_reached && permissions.report_progress) {
				return execution_live_action(active_execution, "report_progress");
			}
			if (next_job?.wip_bin_ready_count && !next_job.wip_bin_consumption_draft &&
				permissions.material_transfer) {
				return { key: `material-job:${next_job.name}`, title: __("Consume Ready WIP Bins"),
					detail: __("Prepare the verified WIP-bin consumption for {0}", [next_job.operation]),
					status: __("Next Step"), colour: "orange" };
			}
			const consumption = entry_for_job("Material Consumption for Manufacture");
			if (consumption && next_job?.wip_bin_ready_count) {
				return { key: `stock-entry:${consumption.name}`,
					title: __("Scan Ready WIP Bins"),
					detail: __("{0} bin(s) still need physical-use confirmation for {1}",
						[next_job.wip_bin_ready_count, next_job.operation]),
					status: __("Scan Required"), colour: "orange" };
			}
			if (consumption && consumption.erp_route_ready !== false) {
				return material_entry_live_action(consumption);
			}
			if (active_execution.job_card_needs_submit && permissions.complete) {
				return execution_live_action(active_execution, "complete");
			}
			if (active_execution.runtime_allocation && active_execution.can_close_runtime_cycle &&
				permissions.complete) {
				return execution_live_action(active_execution, "close");
			}
			if (permissions.report_progress) return execution_live_action(active_execution, "report_progress");
		}

		const pending_material_entry = entries.find((row) => row.docstatus === 0 && [
			"Material Transfer for Manufacture", "Material Consumption for Manufacture",
		].includes(row.purpose) && (row.purpose !== "Material Consumption for Manufacture" ||
			row.erp_route_ready !== false));
		if (pending_material_entry) return material_entry_live_action(pending_material_entry);
		if (flow?.has_pending_materials && permissions.material_transfer) {
			return { key: "production-material", title: __("Prepare production materials"),
				detail: __("Issue or consume the next required material quantity"),
				status: __("Next Step"), colour: "orange" };
		}
		const active_task = process_tasks.find((row) => row.status === "In Progress");
		if (active_task) return { key: `task:${active_task.name}`, title: active_task.task_name,
			detail: process_task_next_instruction(active_task), status: active_task.status,
			colour: "blue" };
		const ready_task = process_tasks.find((row) => row.status === "Ready");
		if (ready_task) return { key: `task:${ready_task.name}`, title: ready_task.task_name,
			detail: process_task_next_instruction(ready_task), status: ready_task.status,
			colour: "green" };
		if (flow?.all_job_cards_completed && flow?.remaining_output_qty > 0.000001 &&
			flow?.wip_bin_receipt_ready !== false && permissions.production_receipt) {
			return { key: "production-material", title: __("Receive manufactured product"),
				detail: __("Prepare and confirm the finished-goods Manufacture receipt"),
				status: __("Next Step"), colour: "green" };
		}
		if (flow?.all_job_cards_completed && !flow?.erp_consumption_submission_ready) {
			return { key: "production-material", title: __("ERP operation update pending"),
				detail: flow.erp_consumption_submission_reason,
				status: __("ERP Update Required"), colour: "orange" };
		}
		if (flow?.wip_bin_receipt_ready === false) {
			return { key: "production-material", title: __("Complete WIP-bin consumption"),
				detail: flow.wip_bin_receipt_block_reason,
				status: __("Action Required"), colour: "orange" };
		}
		if (context.work_order_attention?.severity === "warning") {
			return { key: "work-order-attention", title: __("Supervisor ERP attention"),
				detail: context.work_order_attention.message, status: __("Attention"), colour: "orange" };
		}
		return { key: "active-card", title: context.card.card_number,
			detail: context.cycle ? `${__("Cycle")}: ${context.cycle.status}` : __("Waiting for activation"),
			status: context.card.current_state, colour: indicator(context.card.current_state) };
	}

	function row_effective_job_card(row) {
		return row.cfg_kanban_job_card || row.job_card;
	}

	function material_entry_live_action(row) {
		const needs_scan = !["Draft", "Confirmed"].includes(row.trace_status);
		return { key: `stock-entry:${row.name}`,
			title: needs_scan ? __("Scan or verify material") : __("Submit material movement"),
			detail: `${row.purpose} · ${row.name}`,
			status: needs_scan ? __("Scan Required") : __("Ready to Submit"),
			colour: needs_scan ? "orange" : "green" };
	}

	function process_task_next_instruction(task) {
		if (task.status === "Ready") return __("Start this required process task");
		if (task.status === "In Progress") return __("Complete this process task");
		if (task.status === "Awaiting Verification") return __("Supervisor verification is required");
		return __("Resolve this blocking process task");
	}

	function execution_live_action(row, action) {
		const instructions = {
			start: __("Start this operation"),
			report_progress: __("Report the current good and reject quantities"),
			complete: __("Complete the ERPNext Job Card"),
			close: __("Close the completed Kanban Cycle"),
		};
		return { key: `execution:${row.name}`, title: `${row.sequence}.${row.lane_sequence || 1} ${row.operation}`,
			detail: `${instructions[action] || row.workstation || __("Continue operation")} · ${row.good_qty || 0} / ${row.target_qty || row.allocated_qty || 0}`,
			status: __("Next Step"), colour: action === "start" ? "green" : "blue" };
	}

	function render_live_current_action() {
		const action = current_live_action(state.context);
		if (!state.operator || !action) {
			$current_action.hide().empty();
			return;
		}
		state.current_live_focus = action.key;
		const e = frappe.utils.escape_html;
		$current_action.html(`<div class="cfg-live-action-copy">
			<span class="indicator-pill ${action.colour} cfg-live-connection">${state.live_checked_at ? __("Live") : __("Connecting")}</span>
			<div><small>${__("Current action")}</small><strong>${e(action.title)}</strong>
				<span>${e(action.detail || "")}</span></div>
			<span class="indicator-pill ${action.colour}">${e(action.status)}</span></div>
			<div class="cfg-live-action-buttons"><button class="btn btn-primary btn-sm cfg-go-current-work">${__("Go to current work")}</button>
			<button class="btn btn-default btn-sm cfg-refresh-live">${__("Refresh")}</button></div>`).show();
		$current_action.find(".cfg-go-current-work").on("click", () => scroll_to_live_action(true));
		$current_action.find(".cfg-refresh-live").on("click", () => check_live_updates(true));
	}

	function scroll_to_live_action(force) {
		if (!state.current_live_focus || (!force &&
			Date.now() - state.last_operator_interaction_at < manual_scroll_guard_ms)) return;
		const target = $root.find("[data-live-focus]").filter((index, element) =>
			$(element).attr("data-live-focus") === state.current_live_focus).get(0);
		if (!target) return;
		state.auto_scrolling = true;
		target.scrollIntoView({ behavior: "smooth", block: "center" });
		window.setTimeout(() => { state.auto_scrolling = false; focus_scanner(); }, 900);
	}

	function live_scroll_container() {
		return $root.closest(".layout-main-section-wrapper").get(0) || document.scrollingElement;
	}

	function describe_live_change(before, after) {
		if (!before.cycle && after.cycle) return __("Supervisor approval received — production has been released");
		const old_executions = Object.fromEntries((before.executions || []).map((row) => [row.name, row]));
		const changed_execution = (after.executions || []).find((row) =>
			!old_executions[row.name] || old_executions[row.name].status !== row.status);
		if (changed_execution) return __("{0} is now {1}", [changed_execution.operation, changed_execution.status]);
		const old_tasks = Object.fromEntries((before.process_tasks || []).map((row) => [row.name, row]));
		const changed_task = (after.process_tasks || []).find((row) =>
			!old_tasks[row.name] || old_tasks[row.name].status !== row.status);
		if (changed_task) return __("{0} is now {1}", [changed_task.task_name, changed_task.status]);
		if (before.effective_work_order?.status !== after.effective_work_order?.status) {
			return __("Work Order status changed to {0}", [after.effective_work_order?.status || __("Not assigned")]);
		}
		if (before.cycle?.status !== after.cycle?.status) {
			return __("Kanban Cycle status changed to {0}", [after.cycle?.status || __("Completed")]);
		}
		return __("The open Kanban card was updated");
	}

	function set_scanner_message(message, color) {
		state.scanner_message = message;
		const indicator_color = color || "green";
		const operator_camera = (!state.operator || state.awaiting_operator_scan)
			? `<button type="button" class="btn btn-primary btn-sm cfg-operator-camera-header">${__("Scan Operator with Camera")}</button>`
			: "";
		$scanner_status.html(`<div class="cfg-scanner-ready ${indicator_color}">
			<span class="indicator-pill ${indicator_color}">${frappe.utils.escape_html(message)}</span>
			<small>${__("No field selection or deletion is required. Scanner suffix should be Enter.")}</small>
			${operator_camera}
		</div>`);
		$scanner_status.find(".cfg-operator-camera-header").on("click", scan_operator_qr);
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
			<p><strong>${__("Card and operation commands")}</strong>: <code>CFG:CMD:ACTIVATE</code>, <code>CFG:CMD:ACCEPT_OWNER</code>, <code>CFG:CMD:TRANSFER_OWNER</code>, <code>CFG:CMD:START</code>, <code>CFG:CMD:REPORT_PROGRESS</code>, <code>CFG:CMD:GO_TO_CURRENT_WORK</code>, <code>CFG:CMD:CLOSE_CYCLE</code>.</p>
			<p><strong>${__("Production material commands")}</strong>: <code>CFG:CMD:PREPARE_MATERIALS</code>, <code>CFG:CMD:RECORD_LOOSE_WIP_USE</code>, <code>CFG:CMD:PREPARE_LOOSE_WIP_CONSUMPTION</code>, <code>CFG:SELECT:1</code>, <code>CFG:QTY:MATERIAL:10</code>, <code>CFG:CMD:SCAN_MATERIALS</code>, <code>CFG:CMD:NO_SOURCE</code>, <code>CFG:CMD:FULL_BIN</code>, <code>CFG:CMD:SUBMIT_MATERIALS</code>, <code>CFG:CMD:PREPARE_RECEIPT</code>.</p>
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

	async function configure_scanner_command_sheet() {
		let catalog = [];
		let catalog_quantity_signature = "";
		let selected = new Set();
		let custom_labels = {};
		try {
			const saved = JSON.parse(localStorage.getItem(command_print_key) || "{}");
			selected = new Set(Array.isArray(saved.selected) ? saved.selected : []);
			custom_labels = saved.custom_labels && typeof saved.custom_labels === "object" ?
				saved.custom_labels : {};
		} catch (error) {
			localStorage.removeItem(command_print_key);
		}

		const dialog = new frappe.ui.Dialog({
			title: __("Configure Command Labels"),
			size: "extra-large",
			fields: [
				{ fieldname: "quantity_steps", label: __("Routine Good / Material Quantity Values"),
					fieldtype: "Data", reqd: 1, default: "1, 5, 10, 50, 100",
					description: __("Creates Good +quantity plus absolute and additive Material Quantity commands. Change this list, then leave the field to refresh the catalogue.") },
				{ fieldname: "command_selector", fieldtype: "HTML" },
			],
			primary_action_label: __("Print Selected"),
			primary_action: () => generate_sheet(false),
		});

		function quantity_steps() {
			return String(dialog.get_value("quantity_steps") || "")
				.split(",").map((value) => value.trim()).filter(Boolean);
		}

		function capture_editor() {
			const $body = dialog.get_field("command_selector").$wrapper;
			selected = new Set();
			custom_labels = {};
			$body.find(".cfg-command-print-row").each(function () {
				const index = Number($(this).data("index"));
				const row = catalog[index];
				if (!row) return;
				if ($(this).find(".cfg-command-select").prop("checked")) selected.add(row.payload);
				const custom = String($(this).find(".cfg-command-custom-label").val() || "").trim();
				if (custom) custom_labels[row.payload] = custom;
			});
		}

		function render_catalog() {
			const e = frappe.utils.escape_html;
			const grouped = {};
			catalog.forEach((row, index) => {
				(grouped[row.category] ||= []).push({ row, index });
			});
			const groups = Object.entries(grouped).map(([category, rows]) => `
				<section class="cfg-command-print-group mb-4">
					<h4>${e(category)}</h4>
					${rows.map(({ row, index }) => `<div class="cfg-command-print-row" data-index="${index}" style="display:grid;grid-template-columns:28px minmax(210px,1fr) minmax(220px,1fr);gap:10px;align-items:center;padding:8px;border-bottom:1px solid var(--border-color);">
						<input class="cfg-command-select" type="checkbox" ${selected.has(row.payload) ? "checked" : ""} aria-label="${e(__("Select {0}", [row.label]))}">
						<div><strong>${e(row.label)}</strong><small class="d-block text-muted"><code>${e(row.payload)}</code>${row.key ? ` · ${e(row.key)}` : ""}</small></div>
						<input class="form-control cfg-command-custom-label" maxlength="100" value="${e(custom_labels[row.payload] || "")}" placeholder="${e(__("Optional custom / translated label"))}">
					</div>`).join("")}
				</section>`).join("");
			const $wrapper = dialog.get_field("command_selector").$wrapper;
			$wrapper.html(`<div class="cfg-command-print-tools mb-3">
				<button class="btn btn-sm btn-default cfg-command-select-all">${__("Select All")}</button>
				<button class="btn btn-sm btn-default cfg-command-clear-all">${__("Clear All")}</button>
				<span class="text-muted ml-2">${__("Custom text changes only the printed title. The original command name and QR payload remain visible.")}</span>
			</div>${groups || `<div class="text-muted">${__("No printable commands are available.")}</div>`}`);
			$wrapper.find(".cfg-command-select-all").on("click", () => {
				$wrapper.find(".cfg-command-select").prop("checked", true);
			});
			$wrapper.find(".cfg-command-clear-all").on("click", () => {
				$wrapper.find(".cfg-command-select").prop("checked", false);
			});
		}

		async function load_catalog(preserve_editor = false) {
			if (preserve_editor) capture_editor();
			const $wrapper = dialog.get_field("command_selector").$wrapper;
			$wrapper.html(`<div class="text-muted p-3">${__("Loading registered scanner commands...")}</div>`);
			const response = await frappe.call({
				method: "cfg_kanban.api.operator.get_scanner_command_catalog",
				args: { quantity_steps: quantity_steps() },
			});
			catalog = response.message || [];
			catalog_quantity_signature = quantity_steps().join(",");
			const available = new Set(catalog.map((row) => row.payload));
			selected = new Set([...selected].filter((payload) => available.has(payload)));
			custom_labels = Object.fromEntries(
				Object.entries(custom_labels).filter(([payload]) => available.has(payload))
			);
			render_catalog();
		}

		function save_editor() {
			localStorage.setItem(command_print_key, JSON.stringify({
				selected: [...selected], custom_labels,
			}));
		}

		async function generate_sheet(print_all) {
			capture_editor();
			if (catalog_quantity_signature !== quantity_steps().join(",")) {
				await load_catalog();
			}
			if (!print_all && !selected.size) {
				return frappe.msgprint(__("Select at least one command label to print."));
			}
			save_editor();
			print_scanner_command_sheet(
				quantity_steps(), [...selected], custom_labels, print_all
			);
		}

		dialog.show();
		const $print_all = $(`<button class="btn btn-default mr-2">${__("Print All")}</button>`);
		$print_all.on("click", () => generate_sheet(true));
		dialog.get_primary_btn().before($print_all);
		dialog.get_field("quantity_steps").$input.on("change", () => load_catalog(true));
		await load_catalog();
	}

	async function print_scanner_command_sheet(quantity_steps, selected_payloads, custom_labels, print_all) {
		const popup = window.open("", "_blank", "width=1000,height=800");
		if (!popup) {
			frappe.msgprint(__("Allow pop-ups for this site to print scanner command labels."));
			return;
		}
		popup.document.write(`<p style="font-family:Arial;padding:20px">${__("Preparing command labels...")}</p>`);
		try {
			const response = await frappe.call({ method: "cfg_kanban.api.operator.get_scanner_command_sheet",
				args: { quantity_steps, selected_payloads, custom_labels, print_all: print_all ? 1 : 0 } });
			const labels = (response.message || []).map((row) => `<div class="command-label">
				<div class="command-title">${frappe.utils.escape_html(row.custom_label || row.label)}</div>
				${row.custom_label ? `<div class="command-standard">${__("Standard")}: ${frappe.utils.escape_html(row.label)}</div>` : ""}
				${row.key ? `<div class="command-key">${frappe.utils.escape_html(row.key)}</div>` : ""}
				<img src="${row.qr_svg}" alt="${frappe.utils.escape_html(row.label)}">
				<div class="command-payload">${frappe.utils.escape_html(row.payload)}</div>
			</div>`).join("");
			popup.document.open();
			popup.document.write(`<html><head><meta charset="utf-8"><title>${__("Kanban Scanner Command Labels")}</title>
				<style>@page{size:A4 portrait;margin:8mm}*{box-sizing:border-box}body{font-family:Arial,sans-serif;margin:0;color:#111}.heading{text-align:center;margin-bottom:3mm}.heading h2{margin:0}.sheet{display:grid;grid-template-columns:repeat(2,1fr);gap:3mm}.command-label{height:45mm;border:1.2mm solid #111;border-radius:2mm;padding:2.5mm;display:grid;grid-template-columns:1fr 27mm;grid-template-rows:auto auto 1fr auto;gap:1mm;break-inside:avoid}.command-title{font-size:4.5mm;font-weight:800}.command-standard{grid-column:1;font-size:2.8mm;font-weight:600;color:#444}.command-key{grid-column:1;font-size:7mm;font-weight:900;align-self:center}.command-label img{grid-column:2;grid-row:1/5;width:26mm;height:26mm;align-self:center}.command-payload{grid-column:1;font-family:monospace;font-size:2.6mm;font-weight:700;align-self:end;word-break:break-all}.note{text-align:center;font-size:2.8mm;margin-top:3mm}@media print{.no-print{display:none}}</style>
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
			state.live_revision = null;
			state.live_checked_at = null;
			set_scanner_message(__("Card loaded. Scan another card at any time."), "green");
			render();
			window.setTimeout(check_live_updates, 500);
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
			$current_action.hide().empty();
			$operator_identity.html(`<div class="cfg-production-identity-empty">
				<strong>${__("No active operator")}</strong><small>${__("Scan an operator credential to begin.")}</small></div>
				<button class="btn btn-default btn-sm refresh-shared-session">${__("Refresh Session")}</button>`);
			$operator_identity.find(".refresh-shared-session").on("click", refresh_console);
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
		$operator_identity.html(`<div class="cfg-production-operator-details"><small>${__("Active operator")}</small>
			<strong class="cfg-production-operator-name">${e(state.operator.employee_name)}</strong>
			<span class="cfg-production-operator-meta">${e(state.operator.employee)} · ${e(state.operator.kanban_role || "")}</span>
			${state.operator.development_proxy ? `<span class="indicator-pill orange ml-2">${__("Administrator Proxy")}</span>` : ""}</div>
			<div class="cfg-production-station"><small>${__("Station")}</small><strong>${e(state.operator.station || "-")}</strong></div>
			<button class="btn btn-default btn-sm refresh-shared-session" title="${__("Refresh operator session")}" aria-label="${__("Refresh operator session")}">${__("Refresh")}</button>`);
		$operator_identity.find(".refresh-shared-session").on("click", refresh_console);
		if (state.access && state.access.can_use_development_proxy) {
			$("<button class='btn btn-warning btn-sm mb-3'>" + __("Change Development Proxy Employee") + "</button>")
				.appendTo($root).on("click", show_development_proxy_login);
		}
		if (!state.context) {
			$current_action.hide().empty();
			$root.append(`<div class="cfg-work-section-heading"><div><h3>${__("Active Work")}</h3>
				<small>${__("The scanned production card and its current execution appear here.")}</small></div>
				<span class="indicator-pill grey">0 ${__("Active")}</span></div>
				<div class="frappe-card empty-state text-muted text-center p-5">
				${__("No production card is selected. Scan a Kanban card to load the current work.")}</div>`);
			focus_scanner();
			return;
		}
		const { card, master, cycle, effective_work_order, work_order_attention, selected_job_card,
			executions, operation_summaries, production_progress, production_stock_entries, production_material_flow,
			process_tasks, service_tasks,
			service_identity_card, workstation_queue_card, workstation_queue,
			work_orders, route_warnings, production_reconciliation } = state.context;
		if (workstation_queue_card) {
			render_workstation_queue(card, workstation_queue || {});
			render_live_current_action();
			return;
		}
		const cycle_label = cycle ? `${document_link("cfg-kanban-cycle", cycle.name)}${status_line(cycle.status)}` : __("No active cycle");
		const work_order_label = effective_work_order
			? `${document_link("work-order", effective_work_order.name)}${status_line(effective_work_order.status, effective_work_order.docstatus)}`
			: document_link("work-order", null);
		const purchase_equivalent = master.control_type === "Purchase Replenishment" && master.purchase_uom
			? `<div class="text-muted"><small>${__("Planned supplier order")}: ${e(master.purchase_replenishment_qty || 0)} ${e(master.purchase_uom)} · ${__("1 {0} = {1} {2}", [master.purchase_uom, master.purchase_uom_conversion_factor || 1, master.stock_uom || ""])}</small></div>`
			: "";
		const overall_progress = production_progress ? `<div class="cfg-production-route-progress mt-3">
			<div class="d-flex justify-content-between"><strong>${__("Overall route progress")}</strong>
				<strong>${e(Number(production_progress.route_percent || 0).toFixed(1))}%</strong></div>
			<div class="progress mt-1 mb-1"><div class="progress-bar" role="progressbar"
				style="width:${Math.max(0, Math.min(100, Number(production_progress.route_percent || 0)))}%"></div></div>
			<small>${__("Cumulative operations")}: ${e(production_progress.route_good_qty || 0)} / ${e(production_progress.route_target_qty || 0)} ·
				${__("Completed operations")}: ${e(production_progress.completed_operations || 0)} / ${e(production_progress.operation_count || 0)} ·
				${e(production_progress.final_operation || "-")}: ${e(production_progress.final_good_qty || 0)} / ${e(production_progress.final_target_qty || 0)}</small>
		</div>` : "";
		$root.append(`<div class="cfg-work-section-heading"><div><h3>${__("Active Work")}</h3>
			<small>${__("Current scanned production card, ERP status, tasks and execution lanes.")}</small></div>
			<span class="indicator-pill blue">1 ${__("Selected")}</span></div>
			<div class="frappe-card p-4 mb-4 cfg-active-production-card" data-live-focus="active-card">
			<div class="d-flex justify-content-between align-items-start flex-wrap">
				<div><div class="d-flex align-items-center flex-wrap"><h3 class="mr-3 mb-1">${e(card.card_number)}</h3>
					<span class="indicator-pill blue mb-1">${e(card.card_type || __("Unspecified Card Type"))}</span></div>
					<div><strong>${e(card.item_code || master.item_code || card.asset || card.location_reference || card.task_schedule || "")}</strong>${card.kanban_qty ? ` · ${e(card.kanban_qty)} ${e(card.stock_uom || master.stock_uom || "")}` : ""}</div>${purchase_equivalent}
					<div class="text-muted">${e(master.control_type || card.card_behavior || "")} ${master.card_representation ? "· " + e(master.card_representation) : ""}${card.operation ? " · " + e(card.operation) : ""}</div></div>
				<div class="text-right"><small>${__("Card Status")}</small><br><span class="indicator-pill ${indicator(card.current_state)}">${e(card.current_state)}</span></div>
			</div><hr>
			<div class="row">
				<div class="col-sm-2"><small>${__("Master")}</small><div>${e(master.kanban_name || __("Service identity"))}</div></div>
				<div class="col-sm-2"><small>${__("Quantity")}</small><div>${e(card.kanban_qty)} ${e(card.stock_uom || master.stock_uom || "")}</div></div>
				<div class="col-sm-2"><small>${__("Automation")}</small><div>${e(master.automation_level)}</div></div>
				<div class="col-sm-3"><small>${__("Cycle")}</small><div>${cycle_label}</div></div>
				<div class="col-sm-3"><small>${__("Effective Work Order")}</small><div>${work_order_label}</div></div>
			</div>${overall_progress}<div class="cfg-card-actions mt-4"></div>
		</div>`);
		(route_warnings || []).forEach((warning) => $root.append(
			`<div class="alert alert-warning">${e(warning)}</div>`));
		if (production_reconciliation?.completed) {
			const related_closed = production_reconciliation.related_operation_cycles?.closed?.length || 0;
			$root.append(`<div class="alert alert-success"><strong>${__("Production cycle completed")}</strong><br>
				${__("ERPNext completion was verified and this reusable Card is Available for its next production cycle.")}
				${related_closed ? `<br>${__("Related operation Cards automatically closed and released")}: <strong>${e(related_closed)}</strong>` : ""}</div>`);
		} else if (production_reconciliation?.reason &&
			cycle && (["Production Complete", "Waiting FG Receipt"].includes(cycle.status) ||
				effective_work_order?.status === "Completed")) {
			$root.append(`<div class="alert alert-warning"><strong>${__("Production card is waiting to recycle")}</strong><br>
				${e(production_reconciliation.reason)}</div>`);
		}
		if (work_order_attention) {
			const attention_class = work_order_attention.severity === "info" ? "alert-info" : "alert-warning";
			const button_class = work_order_attention.severity === "info" ? "btn-info" : "btn-warning";
			$root.append(`<div class="alert ${attention_class} d-flex justify-content-between align-items-center flex-wrap" data-live-focus="work-order-attention">
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
			render_live_current_action();
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
		render_production_material_flow(production_material_flow);
		render_production_stock_entries(production_stock_entries || [], effective_work_order,
			production_material_flow);
		render_process_tasks(process_tasks || []);
		render_job_role_coverage(state.context?.job_role_compliance);
		render_summaries(operation_summaries || []);
		render_executions(executions || []);
		render_live_current_action();
	}

	function render_service_tasks(tasks) {
		const e = frappe.utils.escape_html;
		const $section = $(`<div><h4>${__("Open Service Tasks for this Card")}</h4></div>`).appendTo($root);
		if (!tasks.length) return $section.append(`<div class="text-muted p-3">${__("No open tasks match this identity.")}</div>`);
		tasks.forEach((task) => $section.append(`<div class="frappe-card p-3 mb-2"><strong>${e(task.task_name)}</strong>
			<span class="indicator-pill ${indicator(task.status)} ml-2">${e(task.status)}</span><br>
			<small>${__("Priority")}: ${e(task.priority)} · ${__("Due")}: ${e(task.due_on || "-")}</small></div>`));
	}

	function render_workstation_queue(card, queue) {
		const e = frappe.utils.escape_html;
		const active = queue.active || [];
		const paused = queue.paused || [];
		const waiting = queue.queue || [];
		$root.append(`<div class="cfg-work-section-heading"><div><h3>${__("Workstation Queue")}</h3>
			<small>${__("Permanent station view. Scan another production card at any time.")}</small></div>
			<span class="indicator-pill blue">${e(queue.total || 0)} ${__("Open")}</span></div>
			<div class="frappe-card p-4 mb-4 cfg-active-production-card" data-live-focus="active-card">
				<div class="d-flex justify-content-between align-items-start flex-wrap"><div>
					<div class="d-flex align-items-center flex-wrap"><h3 class="mr-3 mb-1">${e(queue.workstation || card.current_station)}</h3>
					<span class="indicator-pill blue mb-1">${__("Workstation Queue Card")}</span></div>
					<strong>${e(queue.company || card.queue_company || "-")}</strong><br>
					<small class="text-muted">${e(card.card_number)} · ${__("Read-only queue access; production remains controlled by its own card and Cycle.")}</small>
				</div><button class="btn btn-default refresh-station-queue">${__("Refresh Queue")}</button></div>
			</div>`);
		$root.find(".refresh-station-queue").on("click", () => load_card(card.qr_code));
		render_workstation_queue_group(__("Active Work"), active, "blue", true);
		render_workstation_queue_group(__("Paused Work"), paused, "orange", true);
		render_workstation_queue_group(__("Ready and Upcoming Queue"), waiting, "green", false);
	}

	function render_workstation_queue_group(title, rows, colour, active) {
		const e = frappe.utils.escape_html;
		const $section = $(`<div class="cfg-station-queue-group mb-4"><div class="cfg-work-section-heading">
			<div><h4>${e(title)}</h4></div><span class="indicator-pill ${colour}">${rows.length}</span></div></div>`).appendTo($root);
		if (!rows.length) {
			$section.append(`<div class="frappe-card p-3 text-muted">${active ? __("No work in this state.") : __("The station queue is empty.")}</div>`);
			return;
		}
		rows.forEach((row, index) => {
			const can_open = Boolean(row.card_qr_code || row.card_number);
			const position = active ? "" : `<strong class="cfg-queue-position">#${index + 1}</strong>`;
			const $row = $(`<div class="frappe-card p-3 mb-2 cfg-station-queue-row">
				<div class="row align-items-center"><div class="col-md-1">${position}</div>
				<div class="col-md-3"><strong>${e(row.item_code || "-")}</strong><br><small>${e(row.operation || "-")}</small></div>
				<div class="col-md-2"><span class="indicator-pill ${indicator(row.dispatch_status)}">${e(row.dispatch_status)}</span><br><small>${e(row.readiness || "")}</small></div>
				<div class="col-md-2"><small>${__("Good / Target")}</small><div>${e(row.good_qty || 0)} / ${e(row.target_qty || 0)}</div><small>${__("Reject")}: ${e(row.reject_qty || 0)}</small></div>
				<div class="col-md-3"><small>${__("Work Order")}</small><div>${document_link("work-order", row.work_order)}</div><small>${__("Job Card")}: ${document_link("job-card", row.job_card)}</small></div>
				<div class="col-md-1 text-right">${can_open ? `<button class="btn btn-primary btn-sm open-queued-work" data-token="${e(row.card_qr_code || row.card_number)}">${__("Open")}</button>` : `<small class="text-muted">${__("No card")}</small>`}</div>
				</div><div class="mt-2"><small>${__("Priority")}: ${e(row.priority || "Normal")} · ${__("Cycle")}: ${e(row.kanban_cycle || "-")} · ${__("Queue source")}: ${e(row.sequence_source || "-")}</small></div>
			</div>`).appendTo($section);
			$row.find(".open-queued-work").on("click", function () { load_card($(this).data("token")); });
		});
	}

	function render_production_material_flow(flow) {
		if (!flow) return;
		const e = frappe.utils.escape_html;
		const shortage_count = (flow.materials || []).filter((row) => row.shortage_qty > 0.000001).length;
		const restricted_attention = Boolean(flow.restricted_material_attention);
		const $section = $(`<div class="cfg-production-material-section" data-live-focus="production-material"><div class="d-flex justify-content-between align-items-center flex-wrap">
			<h4>${__("Production Material Control")}</h4>
			<span class="indicator-pill ${shortage_count || restricted_attention ? "red" : "green"}">${shortage_count ? __("{0} Visible Shortage(s)", [shortage_count]) : restricted_attention ? __("Restricted Material Attention") : __("Stock Checked")}</span>
		</div><div class="frappe-card p-3 mb-3">
			<div class="row"><div class="col-md-4"><small>${__("Material mode")}</small><br><strong>${e(flow.mode)}</strong></div>
			<div class="col-md-3"><small>${__("WIP Warehouse")}</small><br>${e(flow.wip_warehouse || __("Skipped"))}</div>
			<div class="col-md-3"><small>${__("Output Warehouse")}</small><br>${e(flow.output_warehouse || "-")}</div>
			<div class="col-md-2 text-right cfg-production-material-actions"></div></div>
			<div class="table-responsive mt-3">${production_material_table(flow.materials || [])}</div>
		</div></div>`).appendTo($root);
		if (flow.operation_card_scope) {
			$section.prepend(`<div class="alert alert-info"><strong>${__("Operation material control")}</strong><br>
				${__("This operation Card controls material movement or consumption only for Job Card {0}. The main production Cycle remains the ERP material owner.", [document_link("job-card", flow.selected_job_card)])}</div>`);
		}
		if (flow.restricted_materials_present) {
			$section.append(`<div class="alert ${restricted_attention ? "alert-warning" : "alert-info"}">${restricted_attention
				? __("A restricted production component needs attention. Contact an authorized material controller; its identity is intentionally hidden.")
				: __("Restricted BOM component(s) are included automatically by ERPNext and are intentionally hidden from this operator view.")}</div>`);
		}
		render_wip_bin_reconciliations($section, flow);
		const $actions = $section.find(".cfg-production-material-actions");
		if (flow.work_order_docstatus !== 1) {
			$section.append(`<div class="alert alert-warning">${__("Submit the effective ERPNext Work Order before preparing material transfers or Manufacture receipt.")}</div>`);
			return;
		}
		if (state.operator.permissions.material_transfer &&
			flow.mode === "Transfer to WIP by Work Order" &&
			flow.has_pending_materials) {
			add_action($actions, __("Prepare WIP Transfer"), "btn-primary", () =>
				production_material_dialog(flow, null, flow.materials));
		}
		if (state.operator.permissions.material_transfer && flow.mode === "Transfer to WIP by Job Card") {
			(flow.jobs || []).forEach((job) => {
				if (!job.has_pending_materials && !job.wip_bin_ready_count && !job.has_loose_wip &&
					!job.wip_bin_pending_erp_count && !job.wip_bin_consumption_draft) return;
				const $job = $(`<div class="frappe-card p-3 mb-2" data-live-focus="material-job:${e(job.name)}"><div class="row align-items-center">
					<div class="col-md-4"><strong>${e(job.operation)}</strong><br><small>${document_link("job-card", job.name)} · ${e(job.workstation || "-")}</small></div>
					<div class="col-md-5">${production_material_table(job.materials || [])}</div>
					<div class="col-md-3 text-right cfg-job-material-action"></div></div></div>`).appendTo($section);
				const $job_actions = $job.find(".cfg-job-material-action");
				if (job.has_pending_materials) {
					add_action($job_actions, __("Prepare Operation Materials"),
						job.has_shortage ? "btn-warning" : "btn-primary", () =>
						production_material_dialog(flow, job, job.materials));
				}
				if (job.wip_bin_ready_count && !job.wip_bin_consumption_draft) {
					add_action($job_actions, __("Record WIP Bin Use"), "btn-success", () =>
						record_wip_bin_consumption_dialog(flow, job));
					$job.append(`<div class="mt-2 alert alert-success py-2"><small>${__("{0} Ready bin(s), {1} total quantity await Job Card consumption", [job.wip_bin_ready_count, job.wip_bin_ready_qty])}</small></div>`);
				}
				if (job.has_loose_wip && (job.loose_wip_active_bins || []).length &&
					!flow.loose_wip_consumption_draft) {
					add_action($job_actions, __("Record Loose WIP Use"), "btn-success", () =>
						record_loose_wip_usage_dialog(flow, job));
					const usage_rows = (job.loose_wip_usage_rows || []).filter((row) => row.status === "Recorded");
					const usage_html = usage_rows.map((usage) =>
						`<div class="d-flex justify-content-between align-items-center mt-1"><span>${e(usage.visible_bin_code || usage.reusable_bin)} · ${e(usage.item_code)}${usage.batch_no ? ` · ${e(usage.batch_no)}` : ""} · ${e(usage.qty)} ${e(usage.stock_uom)}</span>
						<button type="button" class="btn btn-xs btn-danger cancel-loose-wip-use" data-usage="${e(usage.name)}">${__("Undo")}</button></div>`).join("");
					$job.append(`<div class="mt-2 alert alert-info py-2"><small><strong>${__("Loose WIP accumulation")}</strong><br>
						${__("Loaded: {0}. Recorded use awaiting final Work Order consumption: {1}.", [job.loose_wip_loaded_qty || 0, job.loose_wip_recorded_qty || 0])}</small>${usage_html}</div>`);
					$job.find(".cancel-loose-wip-use").on("click", function () {
						frappe.prompt([{ fieldname: "reason", label: __("Reason"), fieldtype: "Small Text", reqd: 1 }], async (values) => {
							await frappe.call({ method: "cfg_kanban.services.production_material_flow.cancel_recorded_loose_wip_usage", args: {
								usage_name: $(this).data("usage"), reason: values.reason,
								operator_session_token: state.session_token,
							}, freeze: true, freeze_message: __("Reversing unposted Loose WIP use...") });
							await load_card(state.context.card.qr_code || state.context.card.card_number);
						}, __("Reverse Loose WIP Use"), __("Reverse"));
					});
				}
				if (job.wip_bin_pending_erp_count && !job.wip_bin_consumption_draft) {
					if (job.erp_consumption_submission_ready) {
						add_action($job_actions, __("Prepare ERP Consumption"), "btn-primary", () =>
							prepare_wip_bin_consumption_dialog(flow, job));
					}
					const pending_rows = (job.wip_bin_pending_erp_loads || []).map((load) =>
						`<div class="d-flex justify-content-between align-items-center mt-1"><span>${e(load.reusable_bin)} · ${e(load.item_code)} · ${e(load.consumed_qty)} ${e(load.stock_uom)}</span>
						<button type="button" class="btn btn-xs btn-danger cancel-pending-wip-use" data-load="${e(load.name)}">${__("Undo Use")}</button></div>`).join("");
					$job.append(`<div class="mt-2 alert alert-warning py-2"><small><strong>${__("Physical use recorded · ERP posting pending")}</strong><br>
						${job.erp_consumption_submission_ready ? __("The owning Job Card is complete. Prepare this operation's native ERP consumption entry.") : e(job.erp_consumption_submission_reason || __("Complete this operation's Job Card first."))}</small>${pending_rows}</div>`);
					$job.find(".cancel-pending-wip-use").on("click", async function () {
						await frappe.call({ method: "cfg_kanban.services.production_material_flow.cancel_recorded_wip_bin_consumption", args: {
							load_name: $(this).data("load"), operator_session_token: state.session_token,
						}, freeze: true, freeze_message: __("Restoring WIP Bin to Ready...") });
						await load_card(state.context.card.qr_code || state.context.card.card_number);
					});
				}
				if (job.wip_bin_consumption_draft) {
					const message = job.erp_consumption_submission_ready
						? __("WIP-bin consumption Draft {0} is fully scanned and ready for ERP submission.", [document_link("stock-entry", job.wip_bin_consumption_draft)])
						: __("WIP-bin consumption Draft {0} belongs only to this operation. Complete its Job Card before ERP submission: {1}", [document_link("stock-entry", job.wip_bin_consumption_draft), e(job.erp_consumption_submission_reason || __("Owning operation is incomplete"))]);
					$job.append(`<div class="mt-2 alert alert-warning py-2"><small>${message}</small></div>`);
				}
				if (job.restricted_materials_present) {
					$job.append(`<div class="mt-2 text-muted"><small>${__("Restricted operation material is included server-side and is not displayed.")}</small></div>`);
				}
			});
		}
		if (state.operator.permissions.material_transfer && flow.mode === "Skip WIP Transfer") {
			if (flow.transfer_material_against === "Job Card") {
				(flow.jobs || []).forEach((job) => {
					if (!job.has_pending_materials) return;
					const $job = $(`<div class="frappe-card p-3 mb-2" data-live-focus="material-job:${e(job.name)}"><div class="row align-items-center">
						<div class="col-md-4"><strong>${e(job.operation)}</strong><br><small>${document_link("job-card", job.name)} · ${e(job.workstation || "-")}</small></div>
						<div class="col-md-5">${production_material_table(job.materials || [])}</div>
						<div class="col-md-3 text-right cfg-job-material-action"></div></div></div>`).appendTo($section);
					add_action($job.find(".cfg-job-material-action"), __("Consume Operation Materials"),
						job.has_shortage ? "btn-warning" : "btn-primary", () =>
						production_consumption_dialog(flow, job, job.materials));
					if (job.restricted_materials_present) {
						$job.append(`<div class="mt-2 text-muted"><small>${__("Restricted operation material is included server-side and is not displayed.")}</small></div>`);
					}
				});
			} else if (flow.has_pending_materials) {
				add_action($actions, __("Consume Work Order Materials"), "btn-primary", () =>
					production_consumption_dialog(flow, null, flow.materials));
			}
			$section.append(`<div class="alert alert-info">${__("Skip-WIP consumption uses a native ERPNext Material Consumption for Manufacture entry. A partial tag scan consumes only the confirmed quantity; the balance stays available on the same tag. ERPNext stock changes only when the entry is submitted.")}</div>`);
		}
		if (state.operator.permissions.production_receipt &&
			flow.all_job_cards_completed && flow.remaining_output_qty > 0.000001 &&
			flow.wip_bin_receipt_ready !== false) {
			add_action($actions, __("Prepare Manufacture Receipt"), "btn-success", () =>
				manufacture_receipt_dialog(flow));
		} else if (flow.all_job_cards_completed && !flow.erp_consumption_submission_ready) {
			$section.append(`<div class="alert alert-warning" data-live-focus="production-material">
				<strong>${__("ERP Work Order operation update required")}</strong><br>
				${e(flow.erp_consumption_submission_reason || "")}</div>`);
		} else if (flow.wip_bin_receipt_ready === false) {
			$section.append(`<div class="alert alert-warning" data-live-focus="production-material">
				<strong>${__("Manufacture receipt is waiting for WIP-bin consumption")}</strong><br>
				${e(flow.wip_bin_receipt_block_reason || "")}</div>`);
		} else if (flow.incomplete_job_cards && flow.incomplete_job_cards.length) {
			$section.append(`<div class="alert alert-info">${__("Manufacture receipt becomes available after these Job Cards are completed")}: ${flow.incomplete_job_cards.map((name) => document_link("job-card", name)).join(", ")}</div>`);
		}
		if (state.operator.permissions.material_transfer && flow.all_job_cards_completed &&
			flow.loose_wip_recorded_count && !flow.loose_wip_consumption_draft) {
			add_action($actions, __("Prepare Consolidated Loose WIP Consumption"), "btn-primary", () =>
				prepare_consolidated_loose_wip_consumption_dialog(flow));
		}
		if (flow.loose_wip_consumption_draft) {
			$section.append(`<div class="alert alert-warning"><strong>${__("Consolidated Loose WIP consumption Draft")}</strong><br>
				${document_link("stock-entry", flow.loose_wip_consumption_draft)} · ${__("Review and submit this ERP entry, then submit any generated unused-material returns before Manufacture receipt.")}</div>`);
		}
	}

	function render_wip_bin_reconciliations($section, flow) {
		const rows = flow.wip_bin_reconciliations || [];
		if (!rows.length) return;
		const e = frappe.utils.escape_html;
		const $block = $(`<div class="alert alert-danger mb-3" data-live-focus="wip-bin-reconciliation">
			<div class="d-flex justify-content-between align-items-start flex-wrap"><div>
				<strong>${__("WIP Bin supervisor reconciliation required")}</strong><br>
				<small>${__("A submitted WIP transfer or consumption was cancelled. The affected bin is blocked until its exact physical material state agrees with ERPNext.")}</small>
			</div><span class="indicator-pill red">${rows.length} ${__("Open")}</span></div>
		</div>`).appendTo($section);
		rows.forEach((row) => {
			const $row = $(`<div class="frappe-card p-3 mt-2">
				<div class="row align-items-center"><div class="col-md-4">
					<strong>${e(row.reusable_bin)}</strong><br><small>${e(row.reversal_context)} · ${e(row.item_code)}${row.batch_no ? ` · ${__("Batch")} ${e(row.batch_no)}` : ""}</small>
				</div><div class="col-md-3">${e(row.qty)} ${e(row.stock_uom)}<br><small>${document_link("job-card", row.job_card)}</small></div>
				<div class="col-md-3"><small>${__("Cancelled Stock Entry")}</small><br>${document_link("stock-entry", row.cancelled_stock_entry)}</div>
				<div class="col-md-2 text-right cfg-wip-reconciliation-action"></div></div>
			</div>`).appendTo($block);
			if (flow.can_reconcile_wip_bins) {
				add_action($row.find(".cfg-wip-reconciliation-action"), __("Reconcile"), "btn-danger", () =>
					wip_bin_reconciliation_dialog(row));
			} else {
				$row.find(".cfg-wip-reconciliation-action").html(
					`<small class="text-danger">${__("Scan a Supervisor QR with Override permission")}</small>`
				);
			}
		});
	}

	function wip_bin_reconciliation_dialog(row) {
		const e = frappe.utils.escape_html;
		const transfer_cancellation = row.reversal_context === "Transfer Cancellation";
		const decision_options = transfer_cancellation
			? "\nMaterial Returned to Source\nMaterial Remains in WIP after ERP Correction"
			: "\nMaterial Restored to Bin\nBin Empty after ERP Correction";
		let dialog;
		dialog = new frappe.ui.Dialog({
			title: __("Reconcile WIP Bin: {0}", [row.reusable_bin]),
			fields: [
				{ fieldname: "summary", fieldtype: "HTML", options:
					`<div class="alert alert-danger"><strong>${e(row.item_code)} · ${e(row.qty)} ${e(row.stock_uom)}</strong><br>
					${e(row.reversal_context)}: ${document_link("stock-entry", row.cancelled_stock_entry)}<br>
					${transfer_cancellation
						? __("ERPNext returned this quantity to the source Warehouse. Inspect the WIP bin and original source before choosing an outcome.")
						: __("ERPNext returned this quantity to WIP. Inspect the physical bin before choosing an outcome.")}</div>` },
				{ fieldname: "decision", label: __("Verified Physical Outcome"), fieldtype: "Select",
					options: decision_options, reqd: 1,
					description: transfer_cancellation
						? __("Returned releases the source safety hold. Remains in WIP requires an exact new submitted transfer before a Ready load is recovered.")
						: __("Restored creates a new Ready load. Empty requires an exact submitted ERPNext correction that removed this quantity from WIP.") },
				{ fieldname: "reusable_bin_scan", label: __("Scan Affected WIP Bin"),
					fieldtype: "Data", reqd: 1, description: __("Scan the permanent physical identity printed on this exact bin.") },
				{ fieldname: "source_handling_unit_scan", label: __("Scan Original Source Stock Tag"),
					fieldtype: "Data",
					depends_on: "eval:doc.decision=='Material Returned to Source'",
					mandatory_depends_on: transfer_cancellation && row.source_handling_unit
						? "eval:doc.decision=='Material Returned to Source'" : "",
					description: row.source_handling_unit
						? __("After physically returning the material, scan the original source tag {0}.", [row.source_handling_unit])
						: __("This transfer used ERP-only source stock; no source tag scan is required.") },
				{ fieldname: "correction_stock_entry", label: __("Submitted ERPNext Correction"),
					fieldtype: "Link", options: "Stock Entry",
					depends_on: "eval:doc.decision=='Bin Empty after ERP Correction' || doc.decision=='Material Remains in WIP after ERP Correction'",
					mandatory_depends_on: "eval:doc.decision=='Bin Empty after ERP Correction' || doc.decision=='Material Remains in WIP after ERP Correction'",
					description: transfer_cancellation
						? __("Must move one exact row from the original source Warehouse to WIP after this hold was raised.")
						: __("Must remove the exact Item, Batch, UOM and quantity from the WIP Warehouse after this hold was raised.") },
				{ fieldname: "reason", label: __("Supervisor Verification / Reason"),
					fieldtype: "Small Text", reqd: 1 },
				{ fieldname: "reconciliation_scan", label: __("Scanner Command"), fieldtype: "Data",
					description: __("Scan Select 1 or Select 2, the affected bin, any required source tag, then Confirm / Submit.") },
			],
			primary_action_label: __("Resolve Controlled Hold"),
			primary_action: async (values) => {
				if (["Bin Empty after ERP Correction", "Material Remains in WIP after ERP Correction"].includes(values.decision) && !values.correction_stock_entry) {
					frappe.throw(__("Select the exact submitted ERPNext correction required by this outcome."));
				}
				if (values.decision === "Material Returned to Source" && row.source_handling_unit && !values.source_handling_unit_scan) {
					frappe.throw(__("Scan the original source Stock Tag after physically returning the material."));
				}
				await frappe.call({
					method: "cfg_kanban.services.wip_bin_loads.resolve_wip_bin_reconciliation",
					args: {
						reconciliation_name: row.name, decision: values.decision,
						reusable_bin_scan: values.reusable_bin_scan, reason: values.reason,
						source_handling_unit_scan: values.source_handling_unit_scan,
						correction_stock_entry: values.correction_stock_entry,
						operator_session_token: state.session_token,
						kanban_card: state.context.card.name,
						event_token: frappe.utils.get_random(24),
					},
					freeze: true, freeze_message: __("Reconciling physical WIP Bin and ERPNext evidence..."),
				});
				dialog.hide();
				frappe.show_alert({ message: __("WIP Bin reconciliation resolved and audited."), indicator: "green" });
				await load_card(state.context.card.qr_code || state.context.card.card_number);
			},
		});
		const scanner = dialog.get_field("reconciliation_scan").$input;
		scanner.attr({ autocomplete: "off", inputmode: "none" });
		scanner.on("keydown.cfg_wip_reconcile", async (event) => {
			if (event.key !== "Enter" && event.key !== "Tab") return;
			event.preventDefault();
			const value = String(scanner.val() || "").trim();
			await dialog.set_value("reconciliation_scan", "");
			const command = value.toUpperCase();
			if (command === "CFG:SELECT:1") await dialog.set_value("decision", transfer_cancellation ? "Material Returned to Source" : "Material Restored to Bin");
			else if (command === "CFG:SELECT:2") await dialog.set_value("decision", transfer_cancellation ? "Material Remains in WIP after ERP Correction" : "Bin Empty after ERP Correction");
			else if (["CFG:CMD:CANCEL", "CFG:CMD:DISMISS"].includes(command)) return dialog.hide();
			else if (["CFG:CMD:CONFIRM", "CFG:CMD:SUBMIT_MATERIALS"].includes(command)) return dialog.get_primary_btn().trigger("click");
			else if (value && !dialog.get_value("reusable_bin_scan")) await dialog.set_value("reusable_bin_scan", value);
			else if (value && dialog.get_value("decision") === "Material Returned to Source" && row.source_handling_unit) await dialog.set_value("source_handling_unit_scan", value);
			else if (value && ["Bin Empty after ERP Correction", "Material Remains in WIP after ERP Correction"].includes(dialog.get_value("decision"))) await dialog.set_value("correction_stock_entry", value);
			else if (value) await dialog.set_value("reusable_bin_scan", value);
			window.setTimeout(() => scanner.trigger("focus"), 80);
		});
		dialog.show();
		window.setTimeout(() => scanner.trigger("focus"), 120);
	}

	function production_material_table(rows) {
		const e = frappe.utils.escape_html;
		if (!rows.length) return `<small class="text-muted">${__("No operation-specific materials")}</small>`;
		return `<table class="table table-bordered table-sm mb-0"><thead><tr><th>${__("Item")}</th><th>${__("Operation")}</th>
			<th>${__("Source")}</th><th>${__("Required / Pending")}</th><th>${__("Available")}</th></tr></thead><tbody>${rows.map((row) =>
			`<tr class="${row.shortage_qty > 0.000001 ? "text-danger" : ""}"><td>${e(row.item_code)}</td><td>${e(row.operation || "-")}</td>
			<td>${e(row.source_warehouse || "-")}</td><td>${e(row.required_qty)} / ${e(row.pending_qty)} ${e(row.stock_uom || "")}</td>
			<td>${e(row.available_qty)}${row.wip_available_qty !== undefined ? `<br><small>${__("WIP")}: ${e(row.wip_available_qty)}</small>` : ""}${row.shortage_qty > 0.000001 ? `<br><strong>${__("Short")}: ${e(row.shortage_qty)}</strong>` : ""}</td></tr>`).join("")}</tbody></table>`;
	}

	function prepare_wip_bin_consumption_dialog(flow, job, scanner_mode = false) {
		let dialog;
		dialog = new frappe.ui.Dialog({
			title: __("Consume Ready WIP Bins: {0}", [job.operation || job.name]),
			fields: [
				{ fieldname: "summary", fieldtype: "HTML", options:
					`<div class="alert alert-info"><strong>${frappe.utils.escape_html(job.name)}</strong><br>${__("{0} recorded WIP-bin use(s), {1} total consumed quantity. This posting belongs only to the completed {2} operation; downstream operations are not checked.", [job.wip_bin_pending_erp_count, job.wip_bin_pending_erp_qty, job.operation || job.name])}</div>` },
				{ fieldname: "confirmation", label: __("Operator Confirmation / Notes"),
					fieldtype: "Small Text", reqd: 1,
					default: __("Operator confirmed the Ready WIP bins for this Job Card") },
				{ fieldname: "scanner_command", label: __("Scanner Command"), fieldtype: "Data",
					description: __("Scan Confirm / Submit or Cancel. After creation, scan the physical Ready bins in Material Trace.") },
			],
			primary_action_label: __("Create ERP Consumption Draft"),
			primary_action: async (values) => {
				const response = await frappe.call({
					method: "cfg_kanban.services.production_material_flow.prepare_wip_bin_consumption",
					args: {
						cycle_name: flow.cycle, job_card: job.name,
						confirmation: values.confirmation,
						requesting_cycle: flow.requesting_cycle || null,
						event_token: frappe.utils.get_random(24),
						operator_session_token: state.session_token,
					},
					freeze: true, freeze_message: __("Preparing WIP-bin consumption Draft..."),
				});
				dialog.hide();
				await operator_material_trace_dialog(response.message.stock_entry);
			},
		});
		dialog.show();
		bind_confirmation_scanner(dialog, true);
		return dialog;
	}

	function record_wip_bin_consumption_dialog(flow, job) {
		let dialog;
		const update_summary = (remaining) => dialog.get_field("summary").$wrapper.html(
			`<div class="alert alert-info"><strong>${frappe.utils.escape_html(job.name)}</strong><br>
			${__("Scan each Ready WIP Bin now. This records physical operation use without creating an ERP Stock Entry. Remaining Ready bins: {0}.", [remaining])}</div>`);
		const record_scan = async (raw_value) => {
			const scan_value = String(raw_value || "").trim();
			if (!scan_value) return;
			const response = await frappe.call({
				method: "cfg_kanban.services.production_material_flow.record_wip_bin_consumption",
				args: {
					cycle_name: flow.cycle, job_card: job.name,
					reusable_bin_scan: scan_value,
					actual_qty: dialog.get_value("actual_qty") || 0,
					consumption_reason: dialog.get_value("consumption_reason"),
					confirmation: dialog.get_value("confirmation"),
					requesting_cycle: flow.requesting_cycle || null,
					event_token: frappe.utils.get_random(24),
					operator_session_token: state.session_token,
				},
				freeze: true, freeze_message: __("Recording physical WIP Bin use..."),
			});
			const result = response.message || {};
			frappe.show_alert({ message: __("{0}: consumed {1}; unused return {2} {3}. ERP posting is deferred.",
				[result.reusable_bin, result.consumed_qty, result.return_qty, result.stock_uom]), indicator: "green" });
			await dialog.set_value("actual_qty", 0);
			await dialog.set_value("consumption_reason", "");
			update_summary(result.ready_remaining || 0);
			if (!result.ready_remaining) {
				dialog.hide();
				await load_card(state.context.card.qr_code || state.context.card.card_number);
			}
		};
		dialog = new frappe.ui.Dialog({
			title: __("Record WIP Bin Use: {0}", [job.operation || job.name]),
			fields: [
				{ fieldname: "summary", fieldtype: "HTML" },
				{ fieldname: "actual_qty", label: __("Actual Quantity Consumed (0 = full bin)"), fieldtype: "Float", default: 0,
					description: __("Optional: scan a Material Quantity command before the bin.") },
				{ fieldname: "consumption_reason", label: __("Adjustment Reason"), fieldtype: "Small Text",
					description: __("Required when actual use is lower than the prepared quantity.") },
				{ fieldname: "camera_scan", label: __("Camera Scan Ready WIP Bin"), fieldtype: "Button",
					click: () => open_camera_scanner(record_scan) },
				{ fieldname: "confirmation", label: __("Operator Confirmation / Notes"), fieldtype: "Small Text", reqd: 1,
					default: __("Operator physically verified the WIP Bin and actual use") },
				{ fieldname: "scanner_command", label: __("Scanner Input"), fieldtype: "Data",
					description: __("Scan the Ready WIP Bin directly. Cancel closes this window without reversing already recorded bins.") },
			],
			primary_action_label: __("Close"),
			primary_action: () => dialog.hide(),
		});
		dialog.cfg_raw_scanner_handler = record_scan;
		dialog.cfg_quantity_handler = async (qty, additive = false) => {
			const next_qty = additive ? Number(dialog.get_value("actual_qty") || 0) + qty : qty;
			await dialog.set_value("actual_qty", next_qty);
			frappe.show_alert({ message: next_qty
				? __("Actual consumption armed: {0}. Scan the Ready WIP Bin.", [next_qty])
				: __("Full-bin consumption armed. Scan the Ready WIP Bin."), indicator: "blue" });
		};
		dialog.show();
		update_summary(job.wip_bin_ready_count || 0);
		bind_confirmation_scanner(dialog, true);
		return dialog;
	}

	function record_loose_wip_usage_dialog(flow, job) {
		let dialog;
		let balance = null;
		const option_for = (row, index) => `${index + 1}. ${row.item_code}${row.batch_no ? ` · ${row.batch_no}` : ""} · ${row.available_qty} ${row.stock_uom}`;
		const refresh_summary = () => {
			const e = frappe.utils.escape_html;
			const items = (balance?.items || []).map((row, index) =>
				`<div><strong>${index + 1}. ${e(row.item_code)}</strong>${row.batch_no ? ` · ${e(row.batch_no)}` : ""} · ${e(row.available_qty)} ${e(row.stock_uom)} ${__("available")}</div>`).join("");
			dialog.get_field("summary").$wrapper.html(balance
				? `<div class="alert alert-info"><strong>${e(balance.handling_unit_id)}</strong> · ${e(job.name)}<br>${items || __("No available material remains in this bin.")}</div>`
				: `<div class="alert alert-info">${__("Scan the permanent Loose WIP Bin first. If it contains multiple Items or Batches, scan Select 1, Select 2, and so on. Then scan a Material Quantity and Confirm.")}</div>`);
		};
		const load_bin = async (scan_value) => {
			const response = await frappe.call({
				method: "cfg_kanban.services.production_material_flow.get_loose_wip_bin_balance",
				args: { cycle_name: flow.cycle, job_card: job.name,
					reusable_bin_scan: scan_value,
					requesting_cycle: flow.requesting_cycle || null,
					operator_session_token: state.session_token },
				freeze: true, freeze_message: __("Loading Loose WIP Bin contents..."),
			});
			balance = response.message || {};
			await dialog.set_value("reusable_bin_scan", balance.handling_unit_id || scan_value);
			const options = (balance.items || []).map(option_for);
			dialog.set_df_property("material_choice", "options", options.join("\n"));
			await dialog.set_value("material_choice", options.length === 1 ? options[0] : "");
			refresh_summary();
		};
		const submit_usage = async () => {
			if (!balance) frappe.throw(__("Scan the Loose WIP Bin first."));
			const option = dialog.get_value("material_choice");
			const index = Math.max(parseInt(String(option || "").split(".")[0], 10) - 1, 0);
			const material = (balance.items || [])[index];
			if (!material) frappe.throw(__("Select the material being used."));
			const qty = Number(dialog.get_value("qty") || 0);
			if (!(qty > 0) || qty > Number(material.available_qty) + 0.000001) {
				frappe.throw(__("Enter a quantity above zero and no more than {0} {1}.", [material.available_qty, material.stock_uom]));
			}
			await frappe.call({
				method: "cfg_kanban.services.production_material_flow.record_loose_wip_usage",
				args: { cycle_name: flow.cycle, job_card: job.name,
					reusable_bin_scan: balance.handling_unit_id, qty,
					item_code: material.item_code, batch_no: material.batch_no,
					confirmation: dialog.get_value("confirmation"),
					requesting_cycle: flow.requesting_cycle || null,
					event_token: frappe.utils.get_random(24),
					operator_session_token: state.session_token },
				freeze: true, freeze_message: __("Recording cumulative Loose WIP use..."),
			});
			frappe.show_alert({ message: __("Loose WIP use recorded for final Work Order consumption."), indicator: "green" });
			await dialog.set_value("qty", 0);
			await load_bin(balance.handling_unit_id);
			if (!(balance.items || []).length) {
				dialog.hide();
				await load_card(state.context.card.qr_code || state.context.card.card_number);
			}
		};
		dialog = new frappe.ui.Dialog({
			title: __("Record Loose WIP Use: {0}", [job.operation || job.name]),
			fields: [
				{ fieldname: "summary", fieldtype: "HTML" },
				{ fieldname: "reusable_bin_scan", label: __("Loose WIP Bin"), fieldtype: "Data" },
				{ fieldname: "camera_scan", label: __("Camera Scan Loose WIP Bin"), fieldtype: "Button",
					click: () => open_camera_scanner(load_bin) },
				{ fieldname: "material_choice", label: __("Material in Bin"), fieldtype: "Select", reqd: 1 },
				{ fieldname: "qty", label: __("Actual Quantity Used"), fieldtype: "Float", reqd: 1 },
				{ fieldname: "confirmation", label: __("Operator Confirmation / Notes"), fieldtype: "Small Text", reqd: 1,
					default: __("Operator verified the Item, bin, and actual quantity used") },
				{ fieldname: "scanner_command", label: __("Scanner Input"), fieldtype: "Data",
					description: __("Scan the bin, Select number, Material Quantity, and Confirm / Submit. Cancel closes this window.") },
			],
			primary_action_label: __("Record Use"),
			primary_action: submit_usage,
		});
		dialog.cfg_raw_scanner_handler = async (raw_value) => {
			const value = String(raw_value || "").trim();
			const command = value.toUpperCase();
			const select = command.match(/^(?:CFG:SELECT:)?(\d+)$/);
			const quantity = command.match(/^CFG:QTY:MATERIAL:([+]?(?:\d+\.?\d*|\.\d+))$/);
			if (["CFG:CMD:CONFIRM", "CFG:CMD:SUBMIT_MATERIALS"].includes(command)) return submit_usage();
			if (select && balance) {
				const index = Number(select[1]) - 1;
				const row = (balance.items || [])[index];
				if (!row) frappe.throw(__("That Loose WIP material number is not available."));
				return dialog.set_value("material_choice", option_for(row, index));
			}
			if (quantity) {
				const instruction = quantity[1];
				const next_qty = instruction.startsWith("+")
					? Number(dialog.get_value("qty") || 0) + Number(instruction)
					: Number(instruction);
				return dialog.set_value("qty", next_qty);
			}
			return load_bin(value);
		};
		dialog.cfg_quantity_handler = (qty, additive = false) => dialog.set_value(
			"qty", additive ? Number(dialog.get_value("qty") || 0) + qty : qty
		);
		dialog.show();
		refresh_summary();
		bind_confirmation_scanner(dialog, true);
		return dialog;
	}

	function prepare_consolidated_loose_wip_consumption_dialog(flow) {
		const dialog = new frappe.ui.Dialog({
			title: __("Prepare Consolidated Loose WIP Consumption"),
			fields: [
				{ fieldtype: "HTML", options: `<div class="alert alert-warning"><strong>${__("Final Work Order posting")}</strong><br>${__("All unposted Loose WIP use from every operation-card cycle will be consolidated into one native ERPNext consumption Draft. Every unused transferred balance will receive a separate controlled WIP-to-source return Draft.")}</div>` },
				{ fieldname: "confirmation", label: __("Operator Confirmation / Notes"), fieldtype: "Small Text", reqd: 1,
					default: __("All operation usage was reviewed before final Work Order consumption") },
				{ fieldname: "scanner_command", label: __("Scanner Command"), fieldtype: "Data" },
			],
			primary_action_label: __("Create Consolidated ERP Draft"),
			primary_action: async (values) => {
				const response = await frappe.call({
					method: "cfg_kanban.services.production_material_flow.prepare_consolidated_loose_wip_consumption",
					args: { cycle_name: flow.cycle, confirmation: values.confirmation,
						event_token: frappe.utils.get_random(24),
						operator_session_token: state.session_token },
					freeze: true, freeze_message: __("Preparing consolidated Loose WIP consumption..."),
				});
				dialog.hide();
				await operator_material_trace_dialog(response.message.stock_entry);
			},
		});
		dialog.show();
		bind_confirmation_scanner(dialog, true);
		return dialog;
	}

	function material_confirmation_fields() {
		return [
			{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item", read_only: 1, in_list_view: 1, columns: 3 },
			{ fieldname: "operation", label: __("Operation"), fieldtype: "Link", options: "Operation", read_only: 1, in_list_view: 1, columns: 2 },
			{ fieldname: "source_warehouse", label: __("Source Warehouse"), fieldtype: "Link", options: "Warehouse", reqd: 1, in_list_view: 1, columns: 3 },
			{ fieldname: "available_qty", label: __("Available"), fieldtype: "Float", read_only: 1, in_list_view: 1, columns: 2 },
			{ fieldname: "stock_uom", label: __("Stock UOM"), fieldtype: "Link", options: "UOM", read_only: 1, hidden: 1 },
			{ fieldname: "qty", label: __("Actual Qty"), fieldtype: "Float", reqd: 1, in_list_view: 1, columns: 2 },
		];
	}

	function production_material_dialog(flow, job, rows, scanner_mode = false) {
		const data = rows.filter((row) => row.pending_qty > 0.000001).map((row) => ({
			item_code: row.item_code, operation: job ? job.operation : row.operation,
			source_warehouse: row.source_warehouse, available_qty: row.available_qty,
			qty: row.pending_qty, stock_uom: row.stock_uom,
		}));
		const dialog = new frappe.ui.Dialog({
			title: job ? __("Confirm Materials for {0}", [job.operation]) : __("Confirm Work Order Material Transfer"),
			size: "extra-large",
			fields: [
				{ fieldtype: "HTML", options: `<div class="alert alert-info">${__("Verify the physical Source Warehouse and actual quantity. ERPNext stock remains authoritative. Posting policy")}: <strong>${frappe.utils.escape_html(flow.material_transfer_posting_mode)}</strong><br>
					<strong>${__("Scanner step")}</strong>: ${__("Scan Confirm / Submit to create the Draft transfer. Do not scan raw-material tags in this confirmation window; scan them in Production Material Trace after the Draft is created.")}</div>` },
				{ fieldname: "material_scanner_guide", fieldtype: "HTML" },
				{ fieldname: "materials", fieldtype: "Table", label: __("Confirmed Materials"),
					cannot_add_rows: true, cannot_delete_rows: true, in_place_edit: true,
					fields: material_confirmation_fields(), data },
				{ fieldname: "confirmation", label: __("Operator Confirmation / Notes"), fieldtype: "Small Text", reqd: 1,
					default: __("Operator confirmed material preparation from the Kanban panel") },
				{ fieldname: "scanner_command", label: __("Scanner Command"), fieldtype: "Data",
					description: __("Scan Confirm / Submit or Cancel. The scanner remains active without touching the screen.") },
			],
			primary_action_label: flow.material_transfer_posting_mode === "Submit on Operator Confirmation" ? __("Confirm and Submit Transfer") : __("Create Draft Transfer"),
			primary_action: async (values) => {
				const lines = (values.materials || []).map((row) => ({ item_code: row.item_code,
					source_warehouse: row.source_warehouse, qty: row.qty }));
				await frappe.call({ method: "cfg_kanban.services.production_material_flow.prepare_material_transfer", args: {
					cycle_name: flow.cycle, job_card: job && job.name, lines,
					requesting_cycle: flow.requesting_cycle,
					confirmation: values.confirmation,
					defer_submit_for_scanning: (scanner_mode || dialog.cfg_scanner_confirmed) ? 1 : 0,
					event_token: frappe.utils.get_random(24), operator_session_token: state.session_token,
				}, freeze: true, freeze_message: __("Preparing ERPNext material transfer...") });
				dialog.hide();
				await load_card(state.context.card.qr_code);
			},
		});
		dialog.onhide = restore_scanner_focus;
		dialog.show();
		configure_material_confirmation_scanner(dialog);
		bind_confirmation_scanner(dialog, true);
	}

	function production_consumption_dialog(flow, job, rows, scanner_mode = false) {
		const data = rows.filter((row) => row.pending_qty > 0.000001).map((row) => ({
			item_code: row.item_code, operation: job ? job.operation : row.operation,
			source_warehouse: row.source_warehouse, available_qty: row.available_qty,
			qty: row.pending_qty, stock_uom: row.stock_uom,
		}));
		const posting_mode = flow.material_consumption_posting_mode || "Create Draft for Review";
		const dialog = new frappe.ui.Dialog({
			title: job ? __("Record Actual Material Use for {0}", [job.operation]) :
				__("Record Work Order Material Use"),
			size: "extra-large",
			fields: [
				{ fieldtype: "HTML", options: `<div class="alert alert-info">${__("Enter the quantity physically used now. It may be less than the quantity held by a scanned tag. ERPNext remains the stock authority and records consumption only after submission.")}<br>
					<strong>${__("Posting policy")}</strong>: ${frappe.utils.escape_html(posting_mode)}<br>
					<strong>${__("Scanner step")}</strong>: ${__("Create the Draft, scan actual material tags in Production Material Trace, then scan Submit Materials.")}</div>` },
				{ fieldname: "material_scanner_guide", fieldtype: "HTML" },
				{ fieldname: "materials", fieldtype: "Table", label: __("Actual Materials Used"),
					cannot_add_rows: true, cannot_delete_rows: true, in_place_edit: true,
					fields: material_confirmation_fields(), data },
				{ fieldname: "confirmation", label: __("Operator Confirmation / Notes"), fieldtype: "Small Text", reqd: 1,
					default: __("Operator confirmed actual Skip-WIP material usage") },
				{ fieldname: "scanner_command", label: __("Scanner Command"), fieldtype: "Data",
					description: __("Scan Confirm / Submit or Cancel. The scanner remains active without touching the screen.") },
			],
			primary_action_label: posting_mode === "Submit on Operator Confirmation" ?
				__("Confirm Material Consumption") : __("Create Draft Consumption"),
			primary_action: async (values) => {
				const lines = (values.materials || []).map((row) => ({ item_code: row.item_code,
					source_warehouse: row.source_warehouse, qty: row.qty }));
				await frappe.call({ method: "cfg_kanban.services.production_material_flow.prepare_material_consumption", args: {
					cycle_name: flow.cycle, job_card: job && job.name, lines,
					requesting_cycle: flow.requesting_cycle,
					confirmation: values.confirmation,
					defer_submit_for_scanning: (scanner_mode || dialog.cfg_scanner_confirmed) ? 1 : 0,
					event_token: frappe.utils.get_random(24), operator_session_token: state.session_token,
				}, freeze: true, freeze_message: __("Preparing ERPNext material consumption...") });
				dialog.hide();
				await load_card(state.context.card.qr_code);
			},
		});
		dialog.onhide = restore_scanner_focus;
		dialog.show();
		configure_material_confirmation_scanner(dialog);
		bind_confirmation_scanner(dialog, true);
	}

	function configure_material_confirmation_scanner(dialog) {
		dialog.cfg_material_rows = dialog.get_value("materials") || [];
		dialog.cfg_material_row_index = 0;
		refresh_material_scanner_guide(dialog);
	}

	function refresh_material_scanner_guide(dialog) {
		const field = dialog.get_field("material_scanner_guide");
		if (!field) return;
		const e = frappe.utils.escape_html;
		const rows = dialog.cfg_material_rows || [];
		field.$wrapper.html(`<div class="alert alert-success py-2"><strong>${__("Scanner-only quantity entry")}</strong><br>
			${rows.map((row, index) => `${index + 1}. ${e(row.item_code)} · ${e(row.qty || 0)} ${e(row.stock_uom || "")}${index === dialog.cfg_material_row_index ? ` · <strong>${__("Selected")}</strong>` : ""}`).join("<br>")}<br>
			<small>${__("Scan Select Option, then scan Material Quantity. Example: CFG:SELECT:2 then CFG:QTY:MATERIAL:5. Scan Confirm / Submit when finished.")}</small></div>`);
	}

	function manufacture_receipt_dialog(flow, scanner_mode = false) {
		const direct = flow.mode === "Skip WIP Transfer";
		const data = (flow.materials || []).map((row) => ({
			item_code: row.item_code, operation: row.operation,
			source_warehouse: direct ? row.source_warehouse : flow.wip_warehouse,
			available_qty: direct ? row.available_qty : row.wip_available_qty,
			qty: Math.max(0, row.manufacture_pending_qty ??
				((row.required_qty || 0) - (row.consumed_qty || 0))),
		})).filter((row) => row.qty > 0.000001);
		const dialog = new frappe.ui.Dialog({
			title: __("Confirm Manufacture Receipt"), size: "extra-large",
			fields: [
				{ fieldtype: "HTML", options: `<div class="alert alert-warning">${__("Verify actual input consumption and accepted finished quantity before creating the ERPNext Manufacture entry. Posting policy")}: <strong>${frappe.utils.escape_html(flow.manufacture_posting_mode)}</strong></div>` },
				{ fieldname: "output_qty", label: __("Accepted Finished Quantity"), fieldtype: "Float", reqd: 1, default: flow.remaining_output_qty },
				{ fieldname: "target_warehouse", label: __("Finished Goods Warehouse"), fieldtype: "Link", options: "Warehouse", reqd: 1, default: flow.output_warehouse },
				{ fieldname: "batch_no", label: __("Finished Batch (Optional)"), fieldtype: "Data", default: flow.planned_batch,
					read_only: Boolean(flow.planned_batch),
					description: flow.planned_batch ?
						__("This Cycle already has a controlled planned Batch.") :
						__("Enter a Batch number to use/create that exact Batch, or leave blank so ERPNext generates it during submission from the Item Batch settings.") },
				{ fieldname: "materials", fieldtype: "Table", label: __("Actual Input Consumption"),
					cannot_add_rows: true, cannot_delete_rows: true, in_place_edit: true,
					fields: material_confirmation_fields(), data },
				{ fieldname: "confirmation", label: __("Operator Confirmation / Notes"), fieldtype: "Small Text", reqd: 1,
					default: __("Operator confirmed manufacture receipt from the Kanban panel") },
				{ fieldname: "scanner_command", label: __("Scanner Command"), fieldtype: "Data",
					description: __("Scan Confirm / Submit or Cancel. The scanner remains active without touching the screen.") },
			],
			primary_action_label: flow.manufacture_posting_mode === "Submit on Operator Confirmation" ? __("Confirm and Submit Manufacture") : __("Create Draft Manufacture"),
			primary_action: async (values) => {
				const lines = (values.materials || []).map((row) => ({ item_code: row.item_code,
					source_warehouse: row.source_warehouse, qty: row.qty }));
				await frappe.call({ method: "cfg_kanban.services.production_material_flow.prepare_manufacture_receipt", args: {
					cycle_name: flow.cycle, output_qty: values.output_qty, target_warehouse: values.target_warehouse,
					batch_no: values.batch_no, lines, confirmation: values.confirmation,
					defer_submit_for_scanning: (scanner_mode || dialog.cfg_scanner_confirmed) ? 1 : 0,
					event_token: frappe.utils.get_random(24),
					operator_session_token: state.session_token,
				}, freeze: true, freeze_message: __("Preparing ERPNext Manufacture receipt...") });
				dialog.hide();
				await load_card(state.context.card.qr_code);
			},
		});
		dialog.onhide = restore_scanner_focus;
		dialog.show();
		bind_confirmation_scanner(dialog, true);
	}

	function bind_confirmation_scanner(dialog, focus_now = true, selection_values = [], selection_field = null) {
		const field = dialog.get_field("scanner_command");
		if (!field || !field.$input) return;
		dialog.cfg_scanner_selection_values = selection_values;
		dialog.cfg_scanner_selection_field = selection_field;
		state.active_command_dialog = dialog;
		const previous_onhide = dialog.onhide;
		dialog.onhide = () => {
			if (state.active_command_dialog === dialog) state.active_command_dialog = null;
			if (typeof previous_onhide === "function") previous_onhide();
			else restore_scanner_focus();
		};
		field.$input.attr({ autocomplete: "off", inputmode: "none" });
		field.$input.off("keydown.cfg_confirmation_scan").on("keydown.cfg_confirmation_scan", (event) => {
			if (event.key !== "Enter" && event.key !== "Tab") return;
			event.preventDefault();
			const command = String(field.$input.val() || "").trim();
			handle_confirmation_scanner_value(dialog, command);
		});
		if (focus_now) window.setTimeout(() => field.set_focus(), 100);
	}

	async function handle_confirmation_scanner_value(dialog, raw_command) {
		const field = dialog.get_field("scanner_command");
		const raw_value = String(raw_command || "").trim();
		const command = raw_value.toUpperCase();
		await dialog.set_value("scanner_command", "");
		const selection_values = dialog.cfg_scanner_selection_values || [];
		const selection_field = dialog.cfg_scanner_selection_field;
		const selection = command.match(/^CFG:SELECT:(\d+)$/) || command.match(/^(\d+)$/);
		if (selection && dialog.cfg_material_rows) {
			const index = Number(selection[1]) - 1;
			if (index >= 0 && index < dialog.cfg_material_rows.length) {
				dialog.cfg_material_row_index = index;
				refresh_material_scanner_guide(dialog);
				frappe.show_alert({ message: __("Material row {0} selected. Scan its Material Quantity.", [index + 1]), indicator: "blue" });
				return window.setTimeout(() => field.set_focus(), 80);
			}
			frappe.show_alert({ message: __("That material row number is not available."), indicator: "orange" });
			return window.setTimeout(() => field.set_focus(), 80);
		}
		const material_qty = command.match(/^CFG:QTY:MATERIAL:([+]?\d+(?:\.\d+)?)$/);
		if (command === "CFG:CMD:FULL_BIN" && typeof dialog.cfg_quantity_handler === "function") {
			await dialog.cfg_quantity_handler(0);
			return window.setTimeout(() => field.set_focus(), 80);
		}
		if (material_qty && typeof dialog.cfg_quantity_handler === "function") {
			const instruction = material_qty[1];
			await dialog.cfg_quantity_handler(Number(instruction), instruction.startsWith("+"));
			return window.setTimeout(() => field.set_focus(), 80);
		}
		if (material_qty && dialog.cfg_material_rows) {
			const row = dialog.cfg_material_rows[dialog.cfg_material_row_index || 0];
			if (!row) return window.setTimeout(() => field.set_focus(), 80);
			const instruction = material_qty[1];
			const current = Number(row.qty || 0);
			row.qty = instruction.startsWith("+") ? current + Number(instruction) : Number(instruction);
			dialog.get_field("materials").grid.refresh();
			refresh_material_scanner_guide(dialog);
			frappe.show_alert({ message: __("{0} material quantity: {1}", [row.item_code, row.qty]), indicator: "green" });
			return window.setTimeout(() => field.set_focus(), 80);
		}
		if (selection && selection_field) {
			const index = Number(selection[1]) - 1;
			if (index >= 0 && index < selection_values.length) {
				await dialog.set_value(selection_field, selection_values[index]);
				if (selection_field === "selected_job_card" && dialog.get_field("override_reason") && index > 0) {
					await dialog.set_value("override_reason",
						__("Operator selected eligible option {0} using the scanner", [index + 1]));
				}
				frappe.show_alert({ message: __("Option {0} selected. Scan Confirm / Submit to continue.", [index + 1]), indicator: "blue" });
				return window.setTimeout(() => field.set_focus(), 80);
			}
			frappe.show_alert({ message: __("That numbered option is not available."), indicator: "orange" });
			return window.setTimeout(() => field.set_focus(), 80);
		}
		if (command === "CFG:CMD:CONFIRM") {
			dialog.cfg_scanner_confirmed = true;
			return dialog.get_primary_btn().trigger("click");
		}
		if (["CFG:CMD:CANCEL", "CFG:CMD:DISMISS"].includes(command)) return dialog.hide();
		if (raw_value && typeof dialog.cfg_raw_scanner_handler === "function") {
			await dialog.cfg_raw_scanner_handler(raw_value);
			if (dialog.$wrapper.is(":visible")) window.setTimeout(() => field.set_focus(), 80);
			return;
		}
		frappe.show_alert({ message: __("Scan Confirm / Submit or Cancel"), indicator: "orange" });
		window.setTimeout(() => field.set_focus(), 80);
	}

	function scanner_selection_dialog(title, choices, primary_label, on_confirm) {
		const e = frappe.utils.escape_html;
		const options = choices.map((choice) => ({ label: choice.label, value: choice.value }));
		const numbered = `<div class="alert alert-info"><strong>${__("Scan a numbered Select label")}</strong><br>${
			options.map((choice, index) => `${index + 1}. ${e(choice.label)}`).join("<br>")
		}</div>`;
		let dialog;
		dialog = new frappe.ui.Dialog({
			title,
			fields: [
				{ fieldname: "numbered_options", fieldtype: "HTML", options: numbered },
				{ fieldname: "selected_value", label: __("Selected Option"), fieldtype: "Select",
					options, default: options[0]?.value, reqd: 1 },
				{ fieldname: "scanner_command", label: __("Scanner Command"), fieldtype: "Data",
					description: __("Scan Select Option 1-10, then scan Confirm / Submit. Plain numbers work only while this dialog is open.") },
			],
			primary_action_label: primary_label,
			primary_action: async (values) => {
				const choice = choices.find((row) => row.value === values.selected_value);
				if (!choice) return;
				dialog.hide();
				await on_confirm(choice);
			},
		});
		dialog.show();
		bind_confirmation_scanner(dialog, true, options.map((row) => row.value), "selected_value");
		return dialog;
	}

	function open_scanner_loose_wip_usage() {
		const flow = state.context && state.context.production_material_flow;
		if (!flow || !state.operator.permissions.material_transfer) {
			return scanner_command_message(__("No authorized Loose WIP use is available on this card."));
		}
		if (flow.work_order_docstatus !== 1) {
			return scanner_command_message(__("Submit the Work Order before recording Loose WIP use."));
		}
		if (flow.loose_wip_consumption_draft) {
			return scanner_command_message(__("The consolidated Loose WIP consumption Draft is already open."));
		}
		const eligible = (flow.jobs || []).filter((job) =>
			job.has_loose_wip && (job.loose_wip_active_bins || []).length);
		if (!eligible.length) {
			return scanner_command_message(__("No active Loose WIP Bin is available for this production card."));
		}
		if (eligible.length > 1) return scanner_selection_dialog(
			__("Select Job Card for Loose WIP Use"),
			eligible.map((job) => ({ value: job.name,
				label: `${job.operation || __("Operation")} · ${job.name}`, job })),
			__("Record Selected Loose WIP Use"),
			(choice) => record_loose_wip_usage_dialog(flow, choice.job),
		);
		return record_loose_wip_usage_dialog(flow, eligible[0]);
	}

	function open_scanner_loose_wip_consumption() {
		const flow = state.context && state.context.production_material_flow;
		if (!flow || !state.operator.permissions.material_transfer) {
			return scanner_command_message(__("No authorized consolidated Loose WIP consumption is available on this card."));
		}
		if (flow.loose_wip_consumption_draft) {
			return scanner_command_message(__("The consolidated Loose WIP consumption Draft is already open."));
		}
		if (!flow.all_job_cards_completed) {
			return scanner_command_message(__("Complete all Job Cards before preparing consolidated Loose WIP consumption."));
		}
		if (!flow.loose_wip_recorded_count) {
			return scanner_command_message(__("No recorded Loose WIP use is waiting for ERP consumption."));
		}
		return prepare_consolidated_loose_wip_consumption_dialog(flow);
	}

	function open_scanner_material_preparation() {
		const flow = state.context && state.context.production_material_flow;
		if (!flow || !state.operator.permissions.material_transfer) {
			return scanner_command_message(__("No authorized material transfer or consumption is available on this card."));
		}
		if (flow.work_order_docstatus !== 1) {
			return scanner_command_message(__("Submit the Work Order before preparing materials."));
		}
		if (flow.mode === "Skip WIP Transfer") {
			if (flow.transfer_material_against !== "Job Card") {
				if (!flow.has_pending_materials) return scanner_command_message(__("No Work Order material remains to consume."));
				return production_consumption_dialog(flow, null, flow.materials || [], true);
			}
			const pending_consumption = (flow.jobs || []).filter((job) => job.has_pending_materials);
			if (pending_consumption.length > 1) return scanner_selection_dialog(
				__("Select Job Card for Material Consumption"),
				pending_consumption.map((job) => ({ value: job.name,
					label: `${job.operation || __("Operation")} · ${job.name}`, job })),
				__("Record Selected Material Use"),
				(choice) => production_consumption_dialog(
					flow, choice.job, choice.job.materials || [], true
				),
			);
			if (!pending_consumption.length) return scanner_command_message(__("No Job Card material remains to consume."));
			return production_consumption_dialog(
				flow, pending_consumption[0], pending_consumption[0].materials || [], true
			);
		}
		if (flow.mode === "Transfer to WIP by Work Order") {
			if (!flow.has_pending_materials) return scanner_command_message(__("No Work Order material remains to transfer."));
			return production_material_dialog(flow, null, flow.materials || [], true);
		}
		const ready_bins = (flow.jobs || []).filter((job) =>
			job.wip_bin_ready_count && !job.wip_bin_consumption_draft);
		if (ready_bins.length > 1) return scanner_selection_dialog(
			__("Select Job Card for Ready WIP Bin Consumption"),
			ready_bins.map((job) => ({ value: job.name,
				label: `${job.operation || __("Operation")} · ${job.name} · ${job.wip_bin_ready_count} ${__("Ready bin(s)")}`, job })),
			__("Record Selected WIP Bin Use"),
			(choice) => record_wip_bin_consumption_dialog(flow, choice.job),
		);
		if (ready_bins.length === 1) {
			return record_wip_bin_consumption_dialog(flow, ready_bins[0]);
		}
		const recorded_bins = (flow.jobs || []).filter((job) =>
			job.wip_bin_pending_erp_count && !job.wip_bin_consumption_draft &&
			job.erp_consumption_submission_ready);
		if (recorded_bins.length > 1) return scanner_selection_dialog(
			__("Select Job Card for ERP WIP Consumption"),
			recorded_bins.map((job) => ({ value: job.name,
				label: `${job.operation || __("Operation")} · ${job.name} · ${job.wip_bin_pending_erp_count} ${__("recorded bin(s)")}`, job })),
			__("Prepare ERP Consumption"),
			(choice) => prepare_wip_bin_consumption_dialog(flow, choice.job, true),
		);
		if (recorded_bins.length === 1) {
			return prepare_wip_bin_consumption_dialog(flow, recorded_bins[0], true);
		}
		const pending = (flow.jobs || []).filter((job) => job.has_pending_materials);
		const active_jobs = new Set((state.context.executions || [])
			.filter((row) => ["In Progress", "Ready"].includes(row.status)).map((row) => row.job_card));
		const preferred = pending.filter((job) => active_jobs.has(job.name));
		const eligible = preferred.length ? preferred : pending;
		if (eligible.length > 1) return scanner_selection_dialog(
			__("Select Job Card for Material Transfer"),
			eligible.map((job) => ({ value: job.name,
				label: `${job.operation || __("Operation")} · ${job.name}`, job })),
			__("Prepare Selected Materials"),
			(choice) => production_material_dialog(flow, choice.job, choice.job.materials || [], true),
		);
		if (!eligible.length) return scanner_command_message(__("No Job Card material remains to transfer."));
		return production_material_dialog(flow, eligible[0], eligible[0].materials || [], true);
	}

	function open_scanner_manufacture_receipt() {
		const flow = state.context && state.context.production_material_flow;
		if (!flow || !state.operator.permissions.production_receipt ||
			!flow.all_job_cards_completed || !(flow.remaining_output_qty > 0.000001)) {
			return scanner_command_message(__("Manufacture receipt is not ready for scanner confirmation."));
		}
		if (flow.wip_bin_receipt_ready === false) {
			return scanner_command_message(flow.wip_bin_receipt_block_reason ||
				__("Consume and submit the Ready WIP Bin material first."));
		}
		return manufacture_receipt_dialog(flow, true);
	}

	function open_scanner_material_trace() {
		const candidates = (state.context && state.context.production_stock_entries || [])
			.filter((row) => row.can_stage_trace);
		if (candidates.length > 1) return scanner_selection_dialog(
			__("Select Draft Material Entry"),
			candidates.map((row) => ({ value: row.name,
				label: `${row.name} · ${row.purpose || row.stock_entry_type || "-"}` })),
			__("Scan Tags for Selected Entry"),
			(choice) => operator_material_trace_dialog(choice.value),
		);
		if (!candidates.length) return scanner_command_message(__("No Draft production material entry is ready for tag scanning."));
		return operator_material_trace_dialog(candidates[0].name);
	}

	async function submit_scanner_material_entry(selected_stock_entry = null) {
		const active_entry = state.active_material_trace_dialog &&
			state.active_material_trace_dialog.stock_entry;
		const candidates = (state.context && state.context.production_stock_entries || [])
			.filter((row) => row.can_submit &&
				(selected_stock_entry ? row.name === selected_stock_entry : (active_entry ? row.name === active_entry : true)));
		if (candidates.length > 1) return scanner_selection_dialog(
			__("Select Material Entry to Submit"),
			candidates.map((row) => ({ value: row.name,
				label: `${row.name} · ${row.purpose || row.stock_entry_type || "-"}` })),
			__("Submit Selected ERP Entry"),
			(choice) => submit_scanner_material_entry(choice.value),
		);
		if (!candidates.length) return scanner_command_message(__("No Draft production entry is ready to submit."));
		const stock_entry = candidates[0].name;
		if (state.active_material_trace_dialog?.dialog) {
			close_operator_material_trace_dialog(state.active_material_trace_dialog.dialog);
		}
		await frappe.call({ method: "cfg_kanban.services.production_material_flow.submit_production_stock_entry", args: {
			stock_entry, event_token: frappe.utils.get_random(24),
			operator_session_token: state.session_token,
		}, freeze: true, freeze_message: __("Submitting ERPNext stock entry...") });
		frappe.show_alert({ message: __("Production material entry submitted"), indicator: "green" });
		await load_card(state.context.card.qr_code || state.context.card.card_number);
	}

	function scanner_command_message(message) {
		frappe.msgprint({ title: __("Scanner Command Not Applied"), message, indicator: "orange" });
		return false;
	}

	function render_production_stock_entries(entries, work_order, flow) {
		if (!work_order) return;
		const e = frappe.utils.escape_html;
		const $section = $(`<div class="cfg-material-trace-section"><h4>${__("Production Material Trace")}</h4></div>`)
			.appendTo($root);
		if (!entries.length) {
			$section.append(`<div class="frappe-card p-3 mb-3 text-muted">
				${__("No Manufacture, Repack, Material Transfer for Manufacture, or Material Consumption Stock Entry is linked to this Work Order yet. ERP-only materials require no tag action.")}
			</div>`);
			return;
		}
		entries.forEach((row) => {
			const trace_color = row.trace_status === "Confirmed" ? "green" :
				row.trace_status === "Draft" ? "orange" : "grey";
			const $row = $(`<div class="frappe-card p-3 mb-2" data-live-focus="stock-entry:${e(row.name)}"><div class="row align-items-center">
				<div class="col-md-4"><strong>${document_link("stock-entry", row.name)}</strong><br>
					<small>${e(row.purpose || row.stock_entry_type || "-")}</small></div>
				<div class="col-md-2"><span class="indicator-pill ${row.docstatus === 1 ? "green" : "orange"}">${e(row.erp_status)}</span></div>
				<div class="col-md-3"><small>${__("Material Trace")}</small><br>
					<span class="indicator-pill ${trace_color}">${e(row.trace_status)}</span>
					${row.trace ? `<small class="ml-1">${e(row.trace)}</small>` : ""}</div>
				<div class="col-md-3 text-right cfg-material-trace-actions"></div>
			</div></div>`).appendTo($section);
			const $actions = $row.find(".cfg-material-trace-actions");
			if (row.is_wip_bin_return) {
				$row.find(".col-md-4").append(`<br><small class="text-warning">${__("Unused WIP-bin material return to source warehouse")}</small>`);
			}
			const label = row.is_wip_bin_return ? __("View Return Entry") :
				row.can_stage_trace ? __("Scan Material Tags") :
				row.trace_status === "Confirmed" ? __("View Confirmed Trace") : __("View ERP-Only Entry");
			const css = row.can_stage_trace ? "btn-primary" : "btn-default";
			if (!row.is_wip_bin_return) {
				add_action($actions, label, css, () => operator_material_trace_dialog(row.name));
			}
			const can_submit = row.submit_permission === "material_transfer" ?
				state.operator.permissions.material_transfer : state.operator.permissions.production_receipt;
			const route_deferred_consumption = row.purpose === "Material Consumption for Manufacture" &&
				row.docstatus === 0 && row.erp_route_ready === false;
			if (route_deferred_consumption) {
				const owning_job = (flow?.jobs || []).find((job) => job.name === row_effective_job_card(row));
				const ready_bins = owning_job?.wip_bin_ready_count || 0;
				const pending_label = ready_bins
					? __("Scan {0} Ready WIP Bin(s) before closing this operation", [ready_bins])
					: (row.submit_block_reason || __("Operation use recorded · ERP posting waits for all Work Order operations"));
				$row.find(".col-md-4").append(`<br><small class="text-warning">${e(pending_label)}</small>`);
				$actions.append(`<span class="indicator-pill orange">${ready_bins ? __("Scan Bins") : __("ERP Posting Pending")}</span>`);
			}
			if (row.can_submit && can_submit && !route_deferred_consumption) {
				add_action($actions, row.is_wip_bin_return
					? __("Confirm Unused Material Return") : __("Submit ERP Entry"), "btn-success", () => {
					frappe.confirm(__("Submit {0}? ERPNext stock will change only if all validations pass.", [row.name]), async () => {
						await frappe.call({ method: "cfg_kanban.services.production_material_flow.submit_production_stock_entry", args: {
							stock_entry: row.name, event_token: frappe.utils.get_random(24),
							operator_session_token: state.session_token,
						}, freeze: true, freeze_message: __("Submitting ERPNext stock entry...") });
						await load_card(state.context.card.qr_code);
					});
				});
			}
			if (row.can_submit && row.purpose === "Manufacture" &&
				flow?.wip_bin_receipt_ready === false &&
				state.operator.permissions.production_receipt) {
				add_action($actions, __("Discard Premature Draft"), "btn-danger", () => {
					frappe.prompt([
						{ fieldname: "reason", label: __("Reason"), fieldtype: "Small Text",
							reqd: 1, default: __("Created before WIP-bin consumption was completed") },
					], async (values) => {
						await frappe.call({
							method: "cfg_kanban.services.production_material_flow.discard_premature_manufacture_draft",
							args: { stock_entry: row.name, reason: values.reason,
								operator_session_token: state.session_token },
							freeze: true,
							freeze_message: __("Discarding premature Manufacture draft..."),
						});
						frappe.show_alert({ message: __("Premature Manufacture draft discarded"),
							indicator: "orange" });
						await load_card(state.context.card.qr_code || state.context.card.card_number);
					}, __("Discard Premature Manufacture Draft"), __("Discard Draft"));
				});
			}
		});
	}

	async function operator_material_trace_dialog(stock_entry) {
		let plan = await load_operator_trace_plan(stock_entry);
		let dialog;
		const reload = async () => {
			plan = await load_operator_trace_plan(stock_entry);
			await refresh_operator_trace_dialog(dialog, plan, reload);
		};
		dialog = new frappe.ui.Dialog({
			title: __("Production Material Trace: {0}", [stock_entry]), size: "extra-large",
			fields: [
				{ fieldname: "summary", fieldtype: "HTML" },
				{ fieldname: "trace_scanner_status", fieldtype: "HTML" },
				{ fieldname: "trace_scan", label: __("Scanner Ready — Scan Material Tag or Command"), fieldtype: "Data",
					description: __("This field remains armed. A physical tag is matched to its ERP row automatically. Scan Submit Materials when staging is complete, or Cancel to close.") },
				{ fieldname: "wip_bin_section", label: __("Load Standard Quantity Reusable WIP Bin"), fieldtype: "Section Break" },
				{ fieldname: "wip_bin_row", label: __("WIP Bin ERP Material Row"), fieldtype: "Select",
					description: __("Use the numbered scanner command to select a different row when more than one material uses fixed WIP bins.") },
				{ fieldname: "wip_source_scan", label: __("Source Stock Tag (when used)"), fieldtype: "Data",
					description: __("Scan the source Stock Tag first. For an Optional Physical Tag row, scan No Source to use ERP-only stock.") },
				{ fieldname: "wip_bin_scan", label: __("Empty Reusable WIP Bin"), fieldtype: "Data",
					description: __("Scan an Empty bin approved in the configured WIP Bin Pool.") },
				{ fieldname: "allocate_wip_bin", label: __("Allocate Full WIP Bin"), fieldtype: "Button",
					click: async () => allocate_operator_wip_bin(dialog, stock_entry, reload, false) },
				{ fieldname: "wip_partial_notice", fieldtype: "HTML" },
				{ fieldname: "wip_partial_qty", label: __("Partial-bin Quantity"), fieldtype: "Float",
					description: __("During loading this is the quantity prepared. During consumption this is the actual quantity used.") },
				{ fieldname: "wip_partial_reason", label: __("Quantity Adjustment Reason"), fieldtype: "Small Text",
					description: __("Required whenever the quantity is lower than the prepared or full-bin quantity.") },
				{ fieldname: "allocate_partial_wip_bin", label: __("Approve and Allocate Partial WIP Bin"), fieldtype: "Button",
					click: async () => allocate_operator_wip_bin(dialog, stock_entry, reload, true) },
				{ fieldname: "input_section", label: __("Scan Tagged Material Input"), fieldtype: "Section Break" },
				{ fieldname: "input_row", label: __("Matched ERP Input Row"), fieldtype: "Select", read_only: 1,
					description: __("The scanned tag automatically selects the matching Item, Warehouse, UOM, Batch, and remaining ERP row.") },
				{ fieldname: "input_scan", label: __("Handling Unit Tag"), fieldtype: "Data",
					description: __("Scan the physical input tag. With quantity 0, the system allocates the available tag quantity up to the ERP row balance.") },
				{ fieldname: "input_camera", label: __("Camera Scan Input Tag"), fieldtype: "Button",
					click: () => open_camera_scanner((value) => {
						dialog.set_value("input_scan", value);
						dialog.get_field("allocate_input").$input.trigger("click");
					}) },
				{ fieldname: "input_qty", label: __("Stock Quantity (0 = automatic)"), fieldtype: "Float", default: 0 },
				{ fieldname: "allocate_input", label: __("Allocate Input Tag"), fieldtype: "Button",
					click: async () => {
						await frappe.call({ method: "cfg_kanban.services.production_trace.allocate_input_tag", args: {
							stock_entry, item_row: null,
							scan_value: dialog.get_value("input_scan"), qty: dialog.get_value("input_qty") || 0,
							operator_session_token: state.session_token, kanban_card: state.context.card.name,
						}, freeze: true, freeze_message: __("Reserving tagged production input...") });
						frappe.show_alert({ message: __("Input tag reserved"), indicator: "green" });
						await dialog.set_value("input_scan", "");
						await reload();
					} },
				{ fieldname: "output_section", label: __("Stage Production Output Identity"), fieldtype: "Section Break" },
				{ fieldname: "output_row", label: __("ERP Output Row"), fieldtype: "Select" },
				{ fieldname: "output_scan", label: __("Unused Main Tag or Empty Production Output Container"), fieldtype: "Data",
					description: __("Scan either an unused preprinted Main Stock Tag or an empty permanent Production Output Container. The identity remains pending until ERPNext submits this Stock Entry.") },
				{ fieldname: "output_camera", label: __("Camera Scan Output Tag"), fieldtype: "Button",
					click: () => open_camera_scanner((value) => dialog.set_value("output_scan", value)) },
				{ fieldname: "output_qty", label: __("Stock Quantity"), fieldtype: "Float",
					description: __("Quantity carried by this tag. Repeat Stage Output Tag until the ERP output quantity is covered, then submit the Manufacture entry once.") },
				{ fieldname: "output_serial_numbers", label: __("Exact Output Serial Numbers"), fieldtype: "Small Text",
					description: __("Serial-controlled output only. One ERPNext Serial No per line. Do not enter a Batch here; ERPNext assigns the submitted output Batch to every staged tag.") },
				{ fieldname: "handling_unit_type", label: __("Handling Unit Type"), fieldtype: "Select",
					options: "Pallet\nMesh\nTote\nContainer\nReusable Box\nOther", default: "Container" },
				{ fieldname: "stage_output", label: __("Stage Output Tag"), fieldtype: "Button",
					click: async () => stage_operator_output_tag(dialog, stock_entry, reload) },
				{ fieldname: "line_section", label: __("Current Trace Lines"), fieldtype: "Section Break" },
				{ fieldname: "lines", fieldtype: "HTML" },
			],
		});
		state.active_material_trace_dialog = { dialog, stock_entry };
		dialog.onhide = () => {
			if (dialog.cfg_trace_scan_input && dialog.cfg_trace_scan_handler) {
				dialog.cfg_trace_scan_input.removeEventListener(
					"keydown", dialog.cfg_trace_scan_handler, true
				);
			}
			if (dialog.cfg_trace_scan_input && dialog.cfg_trace_input_handler) {
				dialog.cfg_trace_scan_input.removeEventListener(
					"input", dialog.cfg_trace_input_handler, true
				);
			}
			window.clearTimeout(dialog.cfg_trace_scan_timer);
			dialog.$wrapper.off(".cfg_material_trace_persist");
			if (state.active_material_trace_dialog?.dialog === dialog) state.active_material_trace_dialog = null;
			restore_scanner_focus();
		};
		dialog.show();
		configure_operator_material_trace_dialog(dialog);
		await refresh_operator_trace_dialog(dialog, plan, reload);
	}

	function configure_operator_material_trace_dialog(dialog) {
		dialog.cfg_operator_close_requested = false;
		const modal = dialog.$wrapper.data("bs.modal");
		if (modal && modal._config) {
			modal._config.backdrop = "static";
			modal._config.keyboard = false;
		}
		dialog.$wrapper
			.off("click.cfg_material_trace_persist")
			.on("click.cfg_material_trace_persist",
				".modal-header .close, .modal-header .btn-modal-close, .modal-header [data-dismiss='modal']", () => {
					dialog.cfg_operator_close_requested = true;
				})
			.on("click.cfg_material_trace_persist", "[data-cancel-wip-bin-load]", (event) => {
				cancel_operator_wip_bin_load(dialog, event);
			})
			.on("click.cfg_material_trace_persist", "[data-cancel-operator-trace-line]", (event) => {
				cancel_operator_trace_line(dialog, event);
			})
			.off("hide.bs.modal.cfg_material_trace_persist")
			.on("hide.bs.modal.cfg_material_trace_persist", (event) => {
				if (!dialog.cfg_material_scan_lock || dialog.cfg_operator_close_requested) return;
				event.preventDefault();
				refocus_operator_material_trace(dialog);
			});
	}

	function close_operator_material_trace_dialog(dialog) {
		dialog.cfg_operator_close_requested = true;
		dialog.cfg_pending_material_scans = [];
		window.clearTimeout(dialog.cfg_trace_scan_timer);
		dialog.$wrapper.one("hidden.bs.modal.cfg_material_trace_restore", () => {
			restore_scanner_focus();
		});
		dialog.hide();
		// Bootstrap finishes its modal transition after Dialog.onhide. Keep a fallback
		// for themes that do not emit hidden.bs.modal reliably in full-screen mode.
		window.setTimeout(() => restore_scanner_focus(), 400);
	}

	function refocus_operator_material_trace(dialog, delay = 80) {
		window.setTimeout(() => {
			if (dialog.cfg_operator_close_requested || !dialog.$wrapper.is(":visible")) return;
			bind_material_trace_scanner(dialog);
			dialog.get_field("trace_scan")?.set_focus();
		}, delay);
	}

	async function load_operator_trace_plan(stock_entry) {
		const response = await frappe.call({
			method: "cfg_kanban.services.production_trace.get_stock_entry_trace_plan",
			args: { stock_entry, operator_session_token: state.session_token,
				kanban_card: state.context.card.name },
		});
		return response.message;
	}

	async function refresh_operator_trace_dialog(dialog, plan, reload) {
		dialog.cfg_trace_plan = plan;
		dialog.cfg_trace_reload = reload;
		const inputs = (plan.rows || []).filter((row) => row.direction === "Input" &&
			row.tagging_available && row.remaining_qty > 0.000001);
		const wip_inputs = (plan.rows || []).filter((row) => row.direction === "Input" &&
			row.wip_bin_required && row.wip_bin_remaining_qty > 0.000001);
		const outputs = (plan.rows || []).filter((row) => row.direction === "Output" &&
			row.tagging_available && row.remaining_qty > 0.000001);
		const input_options = inputs.map(operator_trace_row_option);
		const output_options = outputs.map(operator_trace_row_option);
		dialog.set_df_property("input_row", "options", input_options.join("\n"));
		const wip_options = wip_inputs.map((row, index) => operator_wip_row_option(row, index));
		dialog.set_df_property("wip_bin_row", "options", wip_options.join("\n"));
		dialog.set_df_property("output_row", "options", output_options.join("\n"));
		dialog.fields_dict.summary.$wrapper.html(operator_trace_summary(plan));
		dialog.fields_dict.lines.$wrapper.html(operator_trace_lines(plan));
		const input_visible = plan.can_edit && input_options.length;
		const output_visible = plan.can_edit && output_options.length;
		const wip_visible = plan.can_edit && wip_options.length;
		// The Stock Entry purpose is the authority for scanner behaviour. A stale row
		// selection must never turn a consumption scan back into the two-scan load flow.
		const wip_consumption = wip_visible &&
			plan.purpose === "Material Consumption for Manufacture";
		const selected_wip = operator_wip_row(wip_inputs, dialog.get_value("wip_bin_row")) || wip_inputs[0];
		const loose_wip = Boolean(selected_wip?.wip_bin_mode === "Loose Multi-Item");
		const scanner_instruction = wip_visible
			? operator_wip_scanner_instruction(dialog, wip_inputs)
			: input_visible
			? __("Scanner ready for an INPUT handling-unit tag. The Item, Warehouse, UOM, Batch, and ERP row are selected automatically.")
			: output_visible
				? __("All required input tags are staged. Scanner ready for an unused OUTPUT tag.")
				: plan.can_submit
					? __("Tag staging is complete. Scan Submit Materials to post the ERPNext entry.")
					: __("No physical tag scan is required for the remaining ERP rows.");
		dialog.fields_dict.trace_scanner_status.$wrapper.html(
			`<div class="alert alert-success py-2"><strong>${__("Scanner Ready")}</strong><br>${scanner_instruction}</div>`
		);
		["input_section", "input_row", "input_scan", "input_camera", "input_qty", "allocate_input"]
			.forEach((name) => toggle_dialog_field(dialog, name, input_visible));
		["wip_bin_section", "wip_bin_scan", "allocate_wip_bin"]
			.forEach((name) => toggle_dialog_field(dialog, name, wip_visible));
		toggle_dialog_field(dialog, "wip_bin_row", wip_visible && !wip_consumption);
		toggle_dialog_field(dialog, "wip_source_scan", wip_visible && !wip_consumption);
		dialog.set_df_property("wip_bin_section", "label", wip_consumption
			? __("Consume Ready Standard Quantity WIP Bin")
			: loose_wip ? __("Load Loose Multi-Item WIP Bin")
				: __("Load Standard Quantity Reusable WIP Bin"));
		dialog.set_df_property("wip_bin_scan", "label", wip_consumption
			? __("Ready Reusable WIP Bin") : loose_wip
				? __("Authorized Loose WIP Bin") : __("Empty Reusable WIP Bin"));
		dialog.set_df_property("allocate_wip_bin", "label", wip_consumption
			? __("Bind Ready Bin to Consumption") : loose_wip
				? __("Load Remaining Quantity") : __("Allocate Full WIP Bin"));
		["output_section", "output_row", "output_scan", "output_camera", "output_qty",
			"output_serial_numbers", "handling_unit_type", "stage_output"]
			.forEach((name) => toggle_dialog_field(dialog, name, output_visible));
		if (input_visible) {
			const selected = input_options.includes(dialog.get_value("input_row")) ?
				dialog.get_value("input_row") : input_options[0];
			await dialog.set_value("input_row", selected);
			bind_operator_trace_enter(dialog, "input_scan", "allocate_input");
		}
		if (wip_visible) {
			const selected = wip_options.includes(dialog.get_value("wip_bin_row")) ?
				dialog.get_value("wip_bin_row") : wip_options[0];
			await dialog.set_value("wip_bin_row", selected);
			const $wip_select = dialog.get_field("wip_bin_row").$input;
			$wip_select.off("change.cfg_wip_row").on("change.cfg_wip_row", async () => {
				if (dialog.cfg_setting_wip_row) return;
				dialog.cfg_wip_row_explicit = true;
				dialog.cfg_wip_erp_only = false;
				dialog.cfg_held_wip_scan = null;
				dialog.cfg_pending_wip_bin_scan = null;
				await dialog.set_value("wip_source_scan", "");
				await dialog.set_value("wip_bin_scan", "");
				await dialog.set_value("wip_partial_reason", "");
				const selected_row = operator_wip_row(wip_inputs, dialog.get_value("wip_bin_row"));
				if (dialog.cfg_pending_wip_qty && selected_row) {
					await arm_operator_wip_quantity(
						dialog, selected_row, dialog.cfg_pending_wip_qty, wip_consumption
					);
				} else {
					dialog.cfg_wip_partial_qty = 0;
					await dialog.set_value("wip_partial_qty", 0);
				}
				await refresh_wip_partial_controls(dialog, wip_inputs);
				window.setTimeout(() => dialog.get_field("trace_scan").set_focus(), 80);
			});
			bind_operator_trace_enter(dialog, "wip_bin_scan", "allocate_wip_bin");
		}
		await refresh_wip_partial_controls(dialog, wip_inputs, wip_consumption);
		if (output_visible) {
			const selected = output_options.includes(dialog.get_value("output_row")) ?
				dialog.get_value("output_row") : output_options[0];
			await dialog.set_value("output_row", selected);
			const selected_row = operator_trace_row(outputs, selected);
			if (!dialog.get_value("output_qty") && selected_row) {
				await dialog.set_value("output_qty", selected_row.remaining_qty);
			}
			await update_operator_output_serial_field(dialog, selected_row);
			const $output_select = dialog.get_field("output_row").$input;
			$output_select.off("change.cfg_serials").on("change.cfg_serials", () => {
				update_operator_output_serial_field(
					dialog, operator_trace_row(outputs, dialog.get_value("output_row"))
				);
			});
			bind_operator_trace_enter(dialog, "output_scan", "stage_output");
		}
		bind_material_trace_scanner(dialog);
		refocus_operator_material_trace(dialog);
	}

	async function cancel_operator_trace_line(dialog, event) {
		event.preventDefault();
		event.stopImmediatePropagation();
		event.stopPropagation();
		const $button = $(event.target).closest("[data-cancel-operator-trace-line]");
		if ($button.prop("disabled")) return;
		$button.prop("disabled", true);
		try {
			await frappe.call({ method: "cfg_kanban.services.production_trace.cancel_trace_line", args: {
				stock_entry: dialog.cfg_trace_plan.stock_entry,
				trace_line: $button.attr("data-cancel-operator-trace-line"),
				operator_session_token: state.session_token, kanban_card: state.context.card.name,
			}, freeze: true, freeze_message: __("Releasing staged trace line...") });
			frappe.show_alert({ message: __("Staged material released"), indicator: "green" });
			if (typeof dialog.cfg_trace_reload === "function") {
				await dialog.cfg_trace_reload();
			}
		} finally {
			$button.prop("disabled", false);
			refocus_operator_material_trace(dialog);
		}
	}

	async function cancel_operator_wip_bin_load(dialog, event) {
		event.preventDefault();
		event.stopImmediatePropagation();
		event.stopPropagation();
		const $button = $(event.target).closest("[data-cancel-wip-bin-load]");
		if ($button.prop("disabled")) return;
		$button.prop("disabled", true);
		const load_name = $button.attr("data-cancel-wip-bin-load");
		const status = $button.attr("data-wip-bin-status");
		const method = status === "Consumption Draft"
			? "cfg_kanban.services.wip_bin_loads.cancel_consumption_bin"
			: "cfg_kanban.services.wip_bin_loads.cancel_transfer_bin";
		try {
			await frappe.call({ method, args: {
				load_name,
				operator_session_token: state.session_token, kanban_card: state.context.card.name,
			}, freeze: true, freeze_message: __("Releasing Draft WIP Bin allocation...") });
			frappe.show_alert({ message: status === "Consumption Draft"
				? __("WIP Bin removed from Draft consumption and restored to Ready.")
				: __("Draft WIP Bin allocation cancelled and source reservation released."),
			indicator: "green" });
			if (typeof dialog.cfg_trace_reload === "function") {
				await dialog.cfg_trace_reload();
			}
		} finally {
			$button.prop("disabled", false);
			refocus_operator_material_trace(dialog);
		}
	}

	async function refresh_wip_partial_controls(dialog, rows, force_consumption = false) {
		const row = operator_wip_row(rows, dialog.get_value("wip_bin_row")) || rows[0];
		const consumption = Boolean(row && (force_consumption || row.wip_bin_action === "Consume"));
		const transfer = Boolean(row && !consumption && row.wip_bin_action === "Load");
		const loose = Boolean(transfer && row?.wip_bin_mode === "Loose Multi-Item");
		const configured = transfer && Boolean(row.allow_supervisor_partial_exception);
		const consumption_needs_supervisor = consumption && Boolean(row.require_full_bin_consumption);
		const authorized = loose || (consumption
			? (!consumption_needs_supervisor || (row.allow_supervisor_partial_exception &&
				Boolean(dialog.cfg_trace_plan?.can_approve_partial_wip_bin)))
			: configured && Boolean(dialog.cfg_trace_plan?.can_approve_partial_wip_bin));
		["wip_partial_qty", "wip_partial_reason", "allocate_partial_wip_bin"]
			.forEach((name) => toggle_dialog_field(dialog, name, authorized));
		const notice = dialog.get_field("wip_partial_notice");
		toggle_dialog_field(dialog, "wip_partial_notice", Boolean(row));
		dialog.set_df_property("wip_partial_qty", "label", consumption
			? __("Actual Quantity Consumed") : loose
				? __("Loose WIP Load Quantity") : __("Approved Partial-bin Quantity"));
		dialog.set_df_property("wip_partial_reason", "label", consumption
			? __("Consumption Adjustment Reason") : loose
				? __("Load Note (optional)") : __("Supervisor Exception Reason"));
		dialog.set_df_property("allocate_partial_wip_bin", "label", consumption
			? __("Report Actual Use and Bind Bin") : loose
				? __("Load Quantity into Loose WIP Bin") : __("Approve and Allocate Partial WIP Bin"));
		if (!row) return;
		let message;
		let indicator = "info";
		if (loose) {
			message = __("Enter or scan the actual quantity being moved into this authorized Loose WIP Bin. The bin may already hold other authorized Items for this same Job Card; no child tag is printed or split.");
		} else if (consumption && consumption_needs_supervisor && !authorized) {
			message = row.allow_supervisor_partial_exception
				? __("This Pool requires full-bin consumption. Switch to a Supervisor QR with Override permission to report a lower actual quantity.")
				: __("This Pool requires full-bin consumption and does not permit partial-consumption exceptions.");
			indicator = "warning";
		} else if (consumption) {
			message = __("Enter or scan the actual quantity used, add a reason, then scan the Ready WIP Bin. The balance will become a separate WIP-to-source return Draft after ERP consumption is submitted.");
		} else if (configured && !authorized) {
			message = __("Partial bins require an active Supervisor QR session with Override permission. Full-bin scanning remains available.");
		} else if (authorized) {
			message = __("Supervisor partial-bin control is available. Each scanned bin supplies its own Item-specific full capacity. Use a Material Quantity command and reason only when that physical bin is deliberately under-filled.");
		} else {
			message = __("This Pool accepts full-bin allocation only. The scanned bin's Item-specific capacity determines the allocated quantity.");
		}
		notice.$wrapper.html(`<div class="alert alert-${indicator} py-2">${frappe.utils.escape_html(message)}</div>`);
	}

	async function update_operator_output_serial_field(dialog, row) {
		const visible = Boolean(row && row.serial_controlled);
		toggle_dialog_field(dialog, "output_serial_numbers", visible);
		await dialog.set_value("output_serial_numbers",
			visible ? (row.available_serial_numbers || []).join("\n") : "");
	}

	function toggle_dialog_field(dialog, fieldname, visible) {
		const field = dialog.get_field(fieldname);
		const wrapper = field?.$wrapper || field?.wrapper;
		if (!wrapper) return;
		$(wrapper).toggle(Boolean(visible));
	}

	function bind_operator_trace_enter(dialog, scan_field, action_field) {
		dialog.get_field(scan_field).$input.off("keydown.cfg_material_trace").on("keydown.cfg_material_trace", async (event) => {
			if (event.key !== "Enter" && event.key !== "Tab") return;
			event.preventDefault();
			event.stopImmediatePropagation();
			const direct_scan_value = String(event.currentTarget.value || "").trim();
			await dialog.set_value(scan_field, direct_scan_value);
			const value = direct_scan_value.toUpperCase();
			if (value === "CFG:CMD:SUBMIT_MATERIALS") return submit_scanner_material_entry();
			if (["CFG:CMD:CANCEL", "CFG:CMD:DISMISS"].includes(value)) {
				return close_operator_material_trace_dialog(dialog);
			}
			const selected_action = scan_field === "wip_bin_scan" &&
				Number(dialog.get_value("wip_partial_qty") || dialog.cfg_wip_partial_qty || 0)
				? "allocate_partial_wip_bin" : action_field;
			dialog.get_field(selected_action).$input.trigger("click");
		});
	}

	function bind_material_trace_scanner(dialog) {
		const field = dialog.get_field("trace_scan");
		field.$input.attr({ autocomplete: "off", inputmode: "none" });
		field.$input.off("keydown.cfg_material_trace_scanner");
		if (dialog.cfg_trace_scan_input && dialog.cfg_trace_scan_handler) {
			dialog.cfg_trace_scan_input.removeEventListener(
				"keydown", dialog.cfg_trace_scan_handler, true
			);
		}
		if (dialog.cfg_trace_scan_input && dialog.cfg_trace_input_handler) {
			dialog.cfg_trace_scan_input.removeEventListener(
				"input", dialog.cfg_trace_input_handler, true
			);
		}
		window.clearTimeout(dialog.cfg_trace_scan_timer);
		const input = field.$input.get(0);
		const submit = () => {
			window.clearTimeout(dialog.cfg_trace_scan_timer);
			const value = String(input.value || "").trim();
			if (!value) return;
			input.value = "";
			run_material_trace_scan(dialog, value);
		};
		const handler = (event) => {
			if (event.key !== "Enter" && event.key !== "Tab") return;
			event.preventDefault();
			event.stopImmediatePropagation();
			submit();
		};
		const input_handler = () => {
			window.clearTimeout(dialog.cfg_trace_scan_timer);
			if (!String(input.value || "").trim()) return;
			dialog.cfg_trace_scan_timer = window.setTimeout(submit, 180);
		};
		input.addEventListener("keydown", handler, true);
		input.addEventListener("input", input_handler, true);
		dialog.cfg_trace_scan_input = input;
		dialog.cfg_trace_scan_handler = handler;
		dialog.cfg_trace_input_handler = input_handler;
	}

	async function run_material_trace_scan(dialog, raw_value) {
		const value = String(raw_value || "").trim();
		if (dialog.cfg_material_scan_lock) {
			if (value && value !== dialog.cfg_active_material_scan) {
				dialog.cfg_pending_material_scans = dialog.cfg_pending_material_scans || [];
				if (dialog.cfg_pending_material_scans.length >= 20) {
					frappe.show_alert({
						message: __("Material scanner queue is full. Wait for the current scan result, then rescan {0}.", [value]),
						indicator: "red",
					}, 10);
					return;
				}
				dialog.cfg_pending_material_scans.push(value);
				frappe.show_alert({
					message: __("Scan queued ({0} waiting). It will run after the current material scan.",
						[dialog.cfg_pending_material_scans.length]),
					indicator: "blue",
				}, 4);
			}
			return;
		}
		dialog.cfg_active_material_scan = value;
		dialog.cfg_material_scan_lock = true;
		try {
			await handle_material_trace_scan(dialog, value);
		} catch (error) {
			const message = error?.message || error?.exc ||
				__("The material scan could not be processed. Review the visible message and rescan.");
			frappe.show_alert({
				message: __("Material scan {0} was not accepted: {1}", [value, message]),
				indicator: "red",
			}, 10);
		} finally {
			window.setTimeout(() => {
				dialog.cfg_material_scan_lock = false;
				dialog.cfg_active_material_scan = null;
				const queue = dialog.cfg_pending_material_scans || [];
				const pending = queue.shift();
				dialog.cfg_pending_material_scans = queue;
				if (pending && !dialog.cfg_operator_close_requested) {
					run_material_trace_scan(dialog, pending);
				} else {
					refocus_operator_material_trace(dialog, 0);
				}
			}, 80);
		}
	}

	async function handle_material_trace_scan(dialog, raw_value) {
		const value = String(raw_value || "").trim();
		const command = value.toUpperCase();
		await dialog.set_value("trace_scan", "");
		if (!value) return dialog.get_field("trace_scan").set_focus();
		if (command === "CFG:CMD:SUBMIT_MATERIALS" || command === "CFG:CMD:CONFIRM") {
			return submit_scanner_material_entry();
		}
		if (["CFG:CMD:CANCEL", "CFG:CMD:DISMISS"].includes(command)) {
			return close_operator_material_trace_dialog(dialog);
		}
		const output_qty_command = command.match(/^CFG:QTY:GOOD:\+?(\d+(?:\.\d+)?)$/);
		if (output_qty_command) {
			const outputs = (dialog.cfg_trace_plan?.rows || []).filter((row) =>
				row.direction === "Output" && row.tagging_available && row.remaining_qty > 0.000001);
			const selected = operator_trace_row(outputs, dialog.get_value("output_row")) || outputs[0];
			if (!selected) frappe.throw(__("No remaining production output is available for this quantity command."));
			const qty = Number(output_qty_command[1]);
			if (!(qty > 0) || qty > Number(selected.remaining_qty) + 0.000001) {
				frappe.throw(__("Output-tag quantity must be above zero and no more than the remaining {0} {1}.",
					[selected.remaining_qty, selected.stock_uom]));
			}
			await dialog.set_value("output_row", operator_trace_row_option(selected));
			await dialog.set_value("output_qty", qty);
			frappe.show_alert({
				message: __("Output quantity {0} {1} armed. Scan the unused output tag or empty permanent output container next.",
					[qty, selected.stock_uom]), indicator: "green",
			});
			return window.setTimeout(() => dialog.get_field("trace_scan").set_focus(), 80);
		}
		const pending_wip = (dialog.cfg_trace_plan?.rows || []).filter((row) =>
			row.direction === "Input" && row.wip_bin_required && row.wip_bin_remaining_qty > 0.000001);
		if (pending_wip.length) {
			const consumption_entry = dialog.cfg_trace_plan?.purpose ===
				"Material Consumption for Manufacture";
			const partial_qty = command.match(/^CFG:QTY:MATERIAL:([+]?(?:\d+\.?\d*|\.\d+))$/);
			if (partial_qty) {
				const instruction = partial_qty[1];
				const qty = instruction.startsWith("+")
					? Number(dialog.cfg_pending_wip_qty || dialog.get_value("wip_partial_qty") || 0) + Number(instruction)
					: Number(instruction);
				dialog.cfg_pending_wip_qty = qty;
				const selected = operator_wip_row(pending_wip, dialog.get_value("wip_bin_row"));
				if (pending_wip.length === 1 || dialog.cfg_wip_row_explicit) {
					await arm_operator_wip_quantity(
						dialog, selected || pending_wip[0], qty, consumption_entry
					);
				} else {
					frappe.show_alert({
						message: __("Material quantity {0} armed. Scan the source tag or WIP Bin; its physical identity will select the correct material row.", [qty]),
						indicator: "blue",
					});
				}
				return window.setTimeout(() => dialog.get_field("trace_scan").set_focus(), 80);
			}
			const row = operator_wip_row(pending_wip, dialog.get_value("wip_bin_row")) || pending_wip[0];
			if (command === "CFG:CMD:FULL_BIN" &&
				["Load", "Consume"].includes(row?.wip_bin_action)) {
				dialog.cfg_pending_wip_qty = null;
				dialog.cfg_wip_partial_qty = 0;
				await dialog.set_value("wip_partial_qty", 0);
				await dialog.set_value("wip_partial_reason", "");
				frappe.show_alert({ message: row.wip_bin_action === "Consume"
					? __("Full prepared quantity consumption restored.")
					: __("Full-bin allocation restored."), indicator: "blue" });
				return window.setTimeout(() => dialog.get_field("trace_scan").set_focus(), 80);
			}
			if (/^(CFG:SELECT:)?\d+$/.test(command)) {
				const index = parseInt(command.replace("CFG:SELECT:", ""), 10) - 1;
				if (pending_wip[index]) {
					const selected_row = pending_wip[index];
					const held = dialog.cfg_held_wip_scan;
					if (held && !(held.classification?.candidate_rows || []).includes(selected_row.row_name)) {
						frappe.throw(__("The held tag cannot be used for material row {0}.", [index + 1]));
					}
					dialog.cfg_wip_row_explicit = true;
					dialog.cfg_wip_erp_only = false;
					await dialog.set_value("wip_source_scan", "");
					await dialog.set_value("wip_bin_scan", "");
					dialog.cfg_setting_wip_row = true;
					await dialog.set_value("wip_bin_row", operator_wip_row_option(selected_row, index));
					dialog.cfg_setting_wip_row = false;
					if (dialog.cfg_pending_wip_qty) {
						await arm_operator_wip_quantity(
							dialog, selected_row, dialog.cfg_pending_wip_qty, consumption_entry
						);
					}
					if (held) {
						dialog.cfg_held_wip_scan = null;
						return route_classified_wip_scan(
							dialog, held.value, held.classification, pending_wip, selected_row
						);
					}
				}
				else frappe.show_alert({ message: __("That WIP material row number is not available."), indicator: "orange" });
				return window.setTimeout(() => dialog.get_field("trace_scan").set_focus(), 80);
			}
			if (command === "CFG:CMD:NO_SOURCE") {
				if (pending_wip.length > 1 && !dialog.cfg_wip_row_explicit) {
					frappe.throw(__("Scan a numbered Select command before No Source when more than one WIP material row is pending."));
				}
				if (row?.tag_required) frappe.throw(__("This Item requires a source Stock Tag."));
				dialog.cfg_wip_erp_only = true;
				await dialog.set_value("wip_source_scan", "");
				if (dialog.cfg_pending_wip_bin_scan) {
					const held_bin = dialog.cfg_pending_wip_bin_scan;
					dialog.cfg_pending_wip_bin_scan = null;
					return route_classified_wip_scan(
						dialog, held_bin.value, held_bin.classification, pending_wip, row
					);
				}
				frappe.show_alert({ message: __("ERP-only source selected; scan the reusable WIP Bin."), indicator: "blue" });
				return window.setTimeout(() => dialog.get_field("trace_scan").set_focus(), 80);
			}
			const response = await frappe.call({
				method: "cfg_kanban.services.production_trace.classify_wip_trace_scan",
				args: { stock_entry: dialog.cfg_trace_plan.stock_entry, scan_value: value,
					operator_session_token: state.session_token,
					kanban_card: state.context.card.name },
			});
			const classification = response.message || {};
			const candidates = classification.candidate_rows || [];
			if (!candidates.length) {
				frappe.throw(__(classification.message || "The scanned tag does not match a pending WIP material row."));
			}
			let matched_row = candidates.length === 1
				? pending_wip.find((candidate) => candidate.row_name === candidates[0]) : null;
			if (!matched_row && (dialog.cfg_wip_row_explicit || dialog.get_value("wip_source_scan"))) {
				const current = operator_wip_row(pending_wip, dialog.get_value("wip_bin_row"));
				if (current && candidates.includes(current.row_name)) matched_row = current;
			}
			if (!matched_row) {
				dialog.cfg_held_wip_scan = { value, classification };
				const numbers = candidates.map((row_name) =>
					pending_wip.findIndex((candidate) => candidate.row_name === row_name) + 1
				).filter((number) => number > 0);
				frappe.show_alert({
					message: __("Tag {0} matches material rows {1}. Scan CFG:SELECT:n to choose; this tag is held and will continue automatically.",
						[classification.handling_unit_id || value, numbers.join(", ")]),
					indicator: "orange",
				}, 8);
				return window.setTimeout(() => dialog.get_field("trace_scan").set_focus(), 80);
			}
			return route_classified_wip_scan(
				dialog, value, classification, pending_wip, matched_row
			);
		}
		const pending_inputs = (dialog.cfg_trace_plan?.rows || []).filter((row) =>
			row.direction === "Input" && row.tagging_available && row.remaining_qty > 0.000001);
		const pending_outputs = (dialog.cfg_trace_plan?.rows || []).filter((row) =>
			row.direction === "Output" && row.tagging_available && row.remaining_qty > 0.000001);
		let scan_direction = pending_inputs.length ? "Input" : "Output";
		if (pending_inputs.length && pending_outputs.length) {
			const response = await frappe.call({
				method: "cfg_kanban.services.production_trace.classify_trace_scan",
				args: { stock_entry: dialog.cfg_trace_plan.stock_entry, scan_value: value,
					operator_session_token: state.session_token,
					kanban_card: state.context.card.name },
			});
			scan_direction = response.message?.direction;
		}
		if (scan_direction === "Input" && pending_inputs.length) {
			await dialog.set_value("input_scan", value);
			return dialog.get_field("allocate_input").$input.trigger("click");
		}
		if (scan_direction === "Output" && pending_outputs.length) {
			await dialog.set_value("output_scan", value);
			return stage_operator_output_tag(
				dialog, dialog.cfg_trace_plan.stock_entry, dialog.cfg_trace_reload,
				pending_outputs
			);
		}
		frappe.show_alert({ message: __("No physical tag is required at the current material stage."), indicator: "orange" });
		window.setTimeout(() => dialog.get_field("trace_scan").set_focus(), 80);
	}

	async function arm_operator_wip_quantity(dialog, row, qty, force_consumption = false) {
		if (!row || !["Load", "Consume"].includes(row.wip_bin_action)) {
			frappe.throw(__("Select a pending WIP material row before scanning its quantity."));
		}
		const consuming = force_consumption || row.wip_bin_action === "Consume";
		const loose = !consuming && row.wip_bin_mode === "Loose Multi-Item";
		if (!(qty > 0) || qty > Number(row.wip_bin_remaining_qty) + 0.000001) {
			frappe.throw(__("Material quantity must be above zero and no more than the remaining {0} {1}.",
				[row.wip_bin_remaining_qty, row.stock_uom]));
		}
		if (!consuming && !loose && !row.allow_supervisor_partial_exception) {
			frappe.throw(__("This Standard Quantity WIP Bin Pool does not allow partial-bin exceptions. Scan the bin without a Material Quantity command."));
		}
		if (!loose && (!consuming || row.require_full_bin_consumption) &&
			!dialog.cfg_trace_plan?.can_approve_partial_wip_bin) {
			frappe.throw(__("Switch to a Supervisor QR with Override permission before setting a partial-bin quantity."));
		}
		dialog.cfg_pending_wip_qty = qty;
		dialog.cfg_wip_partial_qty = qty;
		await dialog.set_value("wip_partial_qty", qty);
		if (Math.abs(qty - Number(row.wip_bin_remaining_qty)) < 0.000001 &&
			!dialog.get_value("wip_partial_reason")) {
			await dialog.set_value("wip_partial_reason",
				__("Final ERP material row remainder does not fill the standard WIP bin"));
		}
		frappe.show_alert({ message: consuming
			? __("Actual consumption {0} {1} armed for {2}. Scan its Ready WIP Bin.",
				[qty, row.stock_uom, row.item_code])
			: loose
				? __("Loose WIP load {0} {1} armed for {2}. Scan its source tag when required, then the Loose WIP Bin.",
					[qty, row.stock_uom, row.item_code])
				: __("Partial Standard WIP quantity {0} {1} armed for {2}. Confirm the exception reason, then scan the required tag(s).",
					[qty, row.stock_uom, row.item_code]), indicator: loose ? "blue" : "orange" });
	}

	async function select_operator_wip_row(dialog, rows, row) {
		const index = rows.findIndex((candidate) => candidate.row_name === row.row_name);
		if (index < 0) frappe.throw(__("The matched WIP material row is no longer pending."));
		const option = operator_wip_row_option(row, index);
		if (dialog.get_value("wip_bin_row") !== option) {
			dialog.cfg_setting_wip_row = true;
			try {
				await dialog.set_value("wip_bin_row", option);
			} finally {
				dialog.cfg_setting_wip_row = false;
			}
		}
		if (dialog.cfg_pending_wip_qty) {
			await arm_operator_wip_quantity(
				dialog, row, dialog.cfg_pending_wip_qty,
				dialog.cfg_trace_plan?.purpose === "Material Consumption for Manufacture"
			);
		}
		await refresh_wip_partial_controls(
			dialog, rows,
			dialog.cfg_trace_plan?.purpose === "Material Consumption for Manufacture"
		);
	}

	async function route_classified_wip_scan(dialog, value, classification, rows, row) {
		await select_operator_wip_row(dialog, rows, row);
		// A unique physical identity match is as authoritative as a numbered Select scan.
		// This also lets an Optional-tag row accept No Source after its bin selected the row.
		dialog.cfg_wip_row_explicit = true;
		if (classification.scan_kind === "Source Stock Tag") {
			if (dialog.cfg_trace_plan?.purpose === "Material Consumption for Manufacture" ||
				row.wip_bin_action === "Consume") {
				frappe.throw(__("Consumption requires the Ready WIP Bin tag, not its original source Stock Tag."));
			}
			if (row.tag_policy === "No Physical Tag") {
				frappe.throw(__("Item {0} uses ERP-only source stock; scan No Source, then the WIP Bin.", [row.item_code]));
			}
			dialog.cfg_wip_erp_only = false;
			await dialog.set_value("wip_source_scan", value);
			const held_bin = dialog.cfg_pending_wip_bin_scan;
			if (held_bin && (held_bin.classification?.candidate_rows || []).includes(row.row_name)) {
				dialog.cfg_pending_wip_bin_scan = null;
				return route_classified_wip_scan(
					dialog, held_bin.value, held_bin.classification, rows, row
				);
			}
			frappe.show_alert({
				message: __("Source tag {0} matched {1}. Now scan its {2} WIP Bin.",
					[classification.handling_unit_id || value, row.item_code,
						row.wip_bin_mode === "Loose Multi-Item" ? "Loose" : "Standard Quantity"]),
				indicator: "blue",
			});
			return window.setTimeout(() => dialog.get_field("trace_scan").set_focus(), 80);
		}
		if (classification.scan_kind !== "WIP Bin") {
			frappe.throw(__(classification.message || "The scanned reusable container is not a WIP Bin."));
		}
		const consuming = dialog.cfg_trace_plan?.purpose ===
			"Material Consumption for Manufacture" || row.wip_bin_action === "Consume";
		if (!consuming && row.wip_bin_mode === "Loose Multi-Item" &&
			!Number(dialog.get_value("wip_partial_qty") || dialog.cfg_wip_partial_qty || 0)) {
			frappe.throw(__("Scan Material Quantity before loading a Loose Multi-Item WIP Bin."));
		}
		if (!consuming && row.tag_policy === "No Physical Tag") {
			dialog.cfg_wip_erp_only = true;
		}
		if (!consuming && !dialog.cfg_wip_erp_only && !dialog.get_value("wip_source_scan")) {
			dialog.cfg_pending_wip_bin_scan = { value, classification };
			frappe.show_alert({
				message: row.tag_required
					? __("{0} WIP Bin recognized for {1}. Scan the required source Stock Tag next; the bin scan is held.",
						[classification.bin_mode, row.item_code])
					: __("{0} WIP Bin recognized for {1}. Scan its source Stock Tag, or scan No Source for ERP-only stock; the bin scan is held.",
						[classification.bin_mode, row.item_code]),
				indicator: "blue",
			});
			return window.setTimeout(() => dialog.get_field("trace_scan").set_focus(), 80);
		}
		await dialog.set_value("wip_bin_scan", value);
		return allocate_operator_wip_bin(
			dialog, dialog.cfg_trace_plan.stock_entry, dialog.cfg_trace_reload,
			Boolean(Number(dialog.get_value("wip_partial_qty") || dialog.cfg_wip_partial_qty || 0))
		);
	}

	function operator_trace_row_option(row) {
		return `${row.row_name} :: ${row.item_code} :: ${row.remaining_qty} ${row.stock_uom}`;
	}

	function operator_wip_row_option(row, index) {
		const prefix = index === undefined ? "" : `${index + 1}. `;
		return `${prefix}${row.row_name} :: ${row.item_code} :: ${row.wip_bin_remaining_qty} ${row.stock_uom} remaining`;
	}

	function operator_wip_row(rows, value) {
		const normalized = String(value || "").replace(/^\d+\.\s*/, "");
		const name = operator_trace_row_name(normalized);
		return rows.find((row) => row.row_name === name);
	}

	function operator_wip_scanner_instruction(dialog, rows) {
		const row = operator_wip_row(rows, dialog.get_value("wip_bin_row")) || rows[0];
		if (!row) return __("Select a WIP material row.");
		if (dialog.cfg_trace_plan?.purpose === "Material Consumption for Manufacture" ||
			row.wip_bin_action === "Consume") {
			return __("Scan the READY reusable WIP Bin. Its Item, Warehouse, UOM, Batch, and exact ERP consumption row are resolved automatically. ERPNext stock changes only after submission.");
		}
		if (row.tag_policy === "No Physical Tag" || dialog.cfg_wip_erp_only) {
			return row.wip_bin_mode === "Loose Multi-Item"
				? __(`WIP row: ${row.item_code}. Scan an authorized LOOSE WIP Bin. It may already contain other allowed material for this Job Card.`)
				: __(`WIP row: ${row.item_code}. Scan an EMPTY reusable WIP Bin. ERPNext stock remains authoritative.`);
		}
		if (row.wip_bin_mode === "Loose Multi-Item") {
			return dialog.get_value("wip_source_scan")
				? __(`Source captured for ${row.item_code}. Now scan an authorized LOOSE WIP Bin for this Job Card.`)
				: __(`WIP row: ${row.item_code}. Scan its source Stock Tag, then scan an authorized LOOSE WIP Bin. Scan No Source only when this row allows optional tags.`);
		}
		return dialog.get_value("wip_source_scan")
			? __(`Source captured for ${row.item_code}. Now scan an EMPTY reusable WIP Bin.`)
			: __(`WIP row: ${row.item_code}. Scan its source Stock Tag, then scan the EMPTY reusable WIP Bin. Scan No Source only when this row allows optional tags.`);
	}

	async function allocate_operator_wip_bin(dialog, stock_entry, reload, partial = false) {
		const rows = (dialog.cfg_trace_plan?.rows || []).filter((row) =>
			row.direction === "Input" && row.wip_bin_required && row.wip_bin_remaining_qty > 0.000001);
		const row = operator_wip_row(rows, dialog.get_value("wip_bin_row")) || rows[0];
		if (!row) {
			frappe.throw(__("No pending WIP material row is available. Refresh the card before scanning again."));
		}
		const consuming = dialog.cfg_trace_plan?.purpose ===
			"Material Consumption for Manufacture" || row.wip_bin_action === "Consume";
		const method = consuming
			? "cfg_kanban.services.wip_bin_loads.allocate_consumption_bin"
			: "cfg_kanban.services.wip_bin_loads.allocate_transfer_bin";
		const args = {
			stock_entry, item_row: consuming ? null : row.row_name,
			reusable_bin_scan: dialog.get_value("wip_bin_scan"),
			operator_session_token: state.session_token, kanban_card: state.context.card.name,
			event_token: frappe.utils.get_random(24),
		};
		if (!consuming) {
			args.source_scan = dialog.cfg_wip_erp_only ? null : dialog.get_value("wip_source_scan");
		}
		if (partial) {
			args.actual_qty = Number(dialog.get_value("wip_partial_qty") || dialog.cfg_wip_partial_qty || 0);
			args.exception_reason = String(dialog.get_value("wip_partial_reason") || "").trim();
			const loose = !consuming && row.wip_bin_mode === "Loose Multi-Item";
			if (!args.actual_qty || (!loose && !args.exception_reason)) {
				frappe.throw(consuming
					? __("Enter the actual consumed quantity and adjustment reason.")
					: __("Enter the approved partial-bin quantity and supervisor exception reason."));
			}
		}
		const response = await frappe.call({ method, args, freeze: true,
			freeze_message: consuming ? __("Binding Ready WIP Bin to ERP consumption...")
				: __("Reserving source material and WIP Bin...") });
		const result = response.message || {};
		frappe.show_alert({ message: consuming
			? __("Ready WIP Bin linked to {0}: prepared {1}, consume {2}, return {3} {4}. ERP stock changes only after submission.",
				[result.item_code || row.item_code, result.prepared_qty || result.actual_qty || 0,
					result.consumed_qty || result.actual_qty || 0, result.return_qty || 0,
					result.stock_uom || row.stock_uom])
			: partial
				? __("Supervisor partial-bin exception recorded; ERP stock moves only after Stock Entry submission.")
				: __("WIP Bin allocated {0} / {1} {2}; ERP stock moves only after Stock Entry submission.",
					[result.actual_qty || 0, result.standard_qty || 0,
						result.stock_uom || row.stock_uom]), indicator: "green" });
		dialog.cfg_wip_erp_only = false;
		dialog.cfg_wip_row_explicit = false;
		dialog.cfg_pending_wip_qty = null;
		dialog.cfg_held_wip_scan = null;
		dialog.cfg_pending_wip_bin_scan = null;
		dialog.cfg_wip_partial_qty = 0;
		await dialog.set_value("wip_source_scan", "");
		await dialog.set_value("wip_bin_scan", "");
		await dialog.set_value("wip_partial_qty", 0);
		await dialog.set_value("wip_partial_reason", "");
		await reload();
	}

	function operator_trace_row_name(value) {
		return String(value || "").replace(/^\d+\.\s*/, "").split(" :: ")[0].trim();
	}

	function operator_trace_row(rows, value) {
		const name = operator_trace_row_name(value);
		return rows.find((row) => row.row_name === name);
	}

	async function stage_operator_output_tag(dialog, stock_entry, reload, candidates = null) {
		const outputs = candidates || (dialog.cfg_trace_plan?.rows || []).filter((row) =>
			row.direction === "Output" && row.tagging_available && row.remaining_qty > 0.000001);
		const row = operator_trace_row(outputs, dialog.get_value("output_row")) || outputs[0];
		if (!row) frappe.throw(__("No remaining ERP output row is available for this tag."));
		const option = operator_trace_row_option(row);
		if (dialog.get_value("output_row") !== option) await dialog.set_value("output_row", option);
		await frappe.call({ method: "cfg_kanban.services.production_trace.stage_output_tag", args: {
			stock_entry, item_row: row.row_name,
			scan_value: dialog.get_value("output_scan"), qty: dialog.get_value("output_qty"),
			handling_unit_type: dialog.get_value("handling_unit_type"),
			serial_numbers: dialog.get_value("output_serial_numbers"),
			operator_session_token: state.session_token, kanban_card: state.context.card.name,
		}, freeze: true, freeze_message: __("Staging production output tag...") });
		frappe.show_alert({ message: __("Output identity staged pending ERP submission"), indicator: "green" });
		await dialog.set_value("output_scan", "");
		await reload();
	}

	function operator_trace_summary(plan) {
		const e = frappe.utils.escape_html;
		const rows = (plan.rows || []).map((row) => `<tr><td>${e(row.direction)}</td>
			<td>${e(row.item_code)}</td><td>${e(row.batch_no || "-")}</td><td>${e(row.warehouse || "-")}</td>
			<td>${e(row.wip_bin_required ? __(`WIP Bin · ${row.tag_policy}`) : row.tag_policy)}</td>
			<td>${e(row.wip_bin_required ? row.wip_bin_allocated_qty : row.traced_qty)} / ${e(row.stock_qty)} ${e(row.stock_uom)}</td></tr>`).join("");
		return `<div class="alert alert-info"><strong>${e(plan.stock_entry)}</strong> · ${e(plan.purpose)} · ${e(plan.company)}<br>
			${__("Material Trace")}: ${e(plan.trace || __("Not created"))} · ${e(plan.trace_status)}</div>
			<div class="table-responsive"><table class="table table-bordered table-sm"><thead><tr>
			<th>${__("Stage")}</th><th>${__("Item")}</th><th>${__("Batch")}</th><th>${__("Warehouse")}</th>
			<th>${__("Tag Policy")}</th><th>${__("Traced / ERP Qty")}</th></tr></thead><tbody>${rows}</tbody></table></div>
			<p class="text-muted">${__("No Physical Tag rows continue through normal ERPNext stock without operator scanning. ERPNext submission confirms every staged movement.")}</p>`;
	}

	function operator_trace_lines(plan) {
		const wip_loads = (plan.rows || []).flatMap((row) => (row.wip_bin_loads || []).map((load) => ({ ...load, item_code: row.item_code })));
		if (!(plan.lines || []).length && !wip_loads.length) return `<p class="text-muted">${__("No production tags or WIP Bins staged.")}</p>`;
		const e = frappe.utils.escape_html;
		const trace_rows = (plan.lines || []).map((line) => `<tr><td>${e(line.direction)}</td><td>${e(line.item_code)}</td>
			<td>${e(line.physical_container || line.handling_unit || line.pending_tag_code || "-")}</td><td>${e(line.qty)} ${e(line.stock_uom)}${line.serial_count ? `<br><small>${e(line.serial_count)} ${__("serials")}</small>` : ""}</td>
			<td>${e(line.status)}</td><td>${line.can_cancel ? `<button type="button" class="btn btn-xs btn-danger" data-cancel-operator-trace-line="${e(line.name)}">${__("Release Loaded Material")}</button>` : ""}</td></tr>`).join("");
		const consumption_plan = plan.purpose === "Material Consumption for Manufacture";
		const wip_rows = wip_loads.map((load) => {
			const quantity = consumption_plan
				? `<strong>${__("Prepared")}: ${e(load.actual_qty)} ${e(load.stock_uom)}</strong><br>
					<span class="text-success">${__("Actual Used")}: ${e(load.consumed_qty || 0)} ${e(load.stock_uom)}</span><br>
					<span class="text-warning">${__("Unused Return")}: ${e(load.return_qty || 0)} ${e(load.stock_uom)}</span>`
				: `${e(load.actual_qty)} ${e(load.stock_uom)}`;
			const consumption_reason = consumption_plan && load.consumption_reason
				? `<br><small>${__("Reason")}: ${e(load.consumption_reason)}</small>` : "";
			return `<tr><td>${consumption_plan ? __("WIP Bin Consumption") : __("WIP Bin")}${load.partial_exception ? `<br><span class="indicator-pill orange">${__("Supervisor Partial Exception")}</span>` : ""}</td><td>${e(load.item_code)}</td>
			<td>${e(load.reusable_bin)}${load.partial_exception ? `<br><small>${e(load.exception_reason || "")}</small><br><small>${e(load.approved_by_operator || load.approved_by || "")}</small>` : ""}${consumption_reason}</td><td>${quantity}</td><td>${e(load.status)}</td>
			<td>${["Transfer Draft", "Consumption Draft"].includes(load.status) ? `<button type="button" class="btn btn-xs btn-danger" data-cancel-wip-bin-load="${e(load.name)}" data-wip-bin-status="${e(load.status)}">${__("Cancel Loaded Material")}</button>` : ""}</td></tr>`;
		}).join("");
		return `<div class="table-responsive"><table class="table table-bordered table-sm"><thead><tr>
			<th>${__("Direction")}</th><th>${__("Item")}</th><th>${__("Tag")}</th><th>${__("Quantity")}</th>
			<th>${__("Status")}</th><th></th></tr></thead><tbody>${trace_rows}${wip_rows}</tbody></table></div>`;
	}

	function render_process_tasks(tasks) {
		if (!tasks.length) return;
		const e = frappe.utils.escape_html;
		const $section = $(`<div><h4>${__("Production Process Tasks")}</h4></div>`).appendTo($root);
		tasks.forEach((task) => {
			const reuse = task.reused_from_task
				? `<div class="text-success"><small>${__("Valid completion reused from")}: ${e(task.reused_from_task)}</small></div>` : "";
			const qc = task.qc_controlled ? `<div><small>${__("QC")}: <strong>${e(task.qc_result || "Pending")}</strong>${task.sample_id ? ` · ${__("Sample")}: ${e(task.sample_id)}` : ""}</small></div>` : "";
			const $row = $(`<div class="frappe-card p-3 mb-2" data-live-focus="task:${e(task.name)}"><div class="row align-items-center">
				<div class="col-md-4"><strong>${e(task.sequence)}. ${e(task.task_name)}</strong><br>
					<small>${e(task.task_type || "")} · ${e(task.trigger_point || "")}</small>
					${task.linked_operation ? `<div class="text-muted">${__("Operation")}: ${e(task.linked_operation)}</div>` : ""}${qc}${reuse}</div>
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
			if (task.status === "Blocked" && task.qc_controlled && state.operator.permissions.task_verify) {
				add_action($buttons, __("Authorise Retest"), "btn-warning", () => authorize_qc_retest(task));
			}
		});
	}

	function authorize_qc_retest(task) {
		frappe.prompt([{ fieldname: "reason", label: __("Retest Reason / Corrective Action"), fieldtype: "Small Text", reqd: 1 }],
			async (values) => {
				await frappe.call({ method: "cfg_kanban.api.process_task.authorize_retest", args: {
					task_name: task.name, reason: values.reason, operator_session_token: state.session_token,
				}, freeze: true });
				await load_card(state.context.card.qr_code);
			}, __("Authorise Controlled QC Retest"), __("Authorise"));
	}

	async function process_task_dialog(task, action) {
		const response = await frappe.call({ method: "cfg_kanban.api.process_task.get_task_form", args: {
			task_name: task.name, capture_on: action, operator_session_token: state.session_token,
		} });
		const details = response.message.task;
		const context = response.message.production_context || {};
		const definitions = response.message.fields || [];
		const initial_media = response.message.media || [];
		const checklist = (details.checklist || "").split("\n").map((item) => item.trim()).filter(Boolean);
		const fields = [
			{ fieldtype: "HTML", options: `<div class="alert alert-info"><strong>${frappe.utils.escape_html(details.task_name)}</strong><br>
				${__("Item")}: <b>${frappe.utils.escape_html(context.item_code || "-")}</b> · ${__("Batch")}: <b>${frappe.utils.escape_html(context.batch_no || "-")}</b><br>
				${__("Cycle")}: ${frappe.utils.escape_html(context.cycle || "-")} · ${__("Work Order")}: ${frappe.utils.escape_html(context.work_order || "-")} · ${__("Operation")}: ${frappe.utils.escape_html(context.operation || "-")}</div>` },
			...(details.qc_controlled && action === "Complete" ? [
				{ fieldname: "sample_id", label: __("Sample ID"), fieldtype: "Data", reqd: 1, default: details.sample_id || details.name },
				{ fieldname: "qc_result", label: __("QC Result"), fieldtype: "Select", reqd: 1,
					options: details.allow_conditional_release ? "Pass\nFail\nConditional Release" : "Pass\nFail" },
				{ fieldname: "qc_reference", fieldtype: "HTML", options: `<p><b>${__("Test Method")}</b>: ${frappe.utils.escape_html(details.test_method || "-")}<br><b>${__("Specification")}</b>: ${frappe.utils.escape_html(details.specification_reference || "-")}</p>` },
				{ fieldname: "qc_disposition_notes", label: __("QC Disposition / Hold Notes"), fieldtype: "Small Text" },
			] : []),
			...checklist.map((item, index) => ({ fieldname: `check_${index}`, label: item, fieldtype: "Check",
				reqd: action === "Complete" })),
			...definitions.map(dialog_field),
			{ fieldtype: "Section Break", label: __("Private QC / Process Evidence") },
			{ fieldname: "process_media", fieldtype: "HTML", options: process_media_html(initial_media, action !== "Verify", details.status === "In Progress") },
			{ fieldname: "notes", label: __("Notes"), fieldtype: "Small Text" },
		];
		const method = { Start: "start", Complete: "complete", Verify: "verify" }[action];
		const dialog = new frappe.ui.Dialog({ title: __(`${action} Process Task`), fields,
			primary_action_label: __(action), primary_action: async (values) => {
				const dynamic_values = visible_dynamic_definitions(definitions, values).map((definition) => ({ field_key: definition.field_key,
					label: definition.label, field_type: definition.field_type,
					value: values[`dynamic_${definition.field_key}`], unit: definition.unit }));
				const checklist_results = checklist.map((item, index) => ({ item, completed: values[`check_${index}`] ? 1 : 0 }));
				const args = {
					task_name: task.name, operator_session_token: state.session_token,
					values: dynamic_values, notes: values.notes,
				};
				if (details.qc_controlled && action === "Complete") Object.assign(args, {
					sample_id: values.sample_id, qc_result: values.qc_result,
					qc_disposition_notes: values.qc_disposition_notes,
				});
				if (action === "Complete") args.checklist_results = checklist_results;
				await frappe.call({ method: `cfg_kanban.api.process_task.${method}`, args, freeze: true });
				dialog.hide();
				await load_card(state.context.card.qr_code);
			} });
		dialog.show();
		configure_dynamic_visibility(dialog, definitions);
		bind_process_media(dialog, task, action, initial_media);
	}

	function process_media_html(rows, can_upload, can_camera) {
		return `<div class="cfg-task-media-evidence">${can_upload ? `<div class="cfg-media-actions">
			${can_camera ? `<label class="btn btn-primary cfg-process-camera-picker">${__("Take Timestamped Photo")}
				<input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" hidden></label>` : ""}
			<label class="btn btn-default cfg-process-file-picker">${__("Upload Photo / PDF / File")}
				<input type="file" accept="image/jpeg,image/png,image/webp,video/mp4,application/pdf" multiple hidden></label></div>
			<small class="text-muted">${can_camera ? __("Camera photos receive server time and device geolocation. Uploaded files remain unchanged.") : __("Start the task to enable timestamped camera capture. Existing files can still be uploaded.")}</small>` : ""}
			<div class="cfg-process-media-status mt-2"></div><div class="cfg-process-media-list mt-2">${process_media_rows(rows)}</div></div>`;
	}

	function process_media_rows(rows) {
		const e = frappe.utils.escape_html;
		if (!rows.length) return `<div class="text-muted">${__("No private evidence attached yet.")}</div>`;
		return rows.map((row) => `<div class="cfg-process-media-row" data-id="${e(row.media_id)}">
			<strong>${e(row.original_filename)}</strong><span><span class="indicator-pill green">${e(row.status)}</span>
			<button type="button" class="btn btn-default btn-sm cfg-open-process-media">${__("Open")}</button>
			<button type="button" class="btn btn-danger btn-sm cfg-remove-process-media">${__("Remove")}</button></span></div>`).join("");
	}

	function bind_process_media(dialog, task, action, initial_rows) {
		const $field = dialog.get_field("process_media").$wrapper;
		let rows = initial_rows || [];
		const refresh = () => {
			$field.find(".cfg-process-media-list").html(process_media_rows(rows));
			$field.find(".cfg-open-process-media").off("click").on("click", async function () {
				const response = await frappe.call({ method: "cfg_kanban.api.media.create_process_task_view_url", args: {
					task_name: task.name, media_id: $(this).closest(".cfg-process-media-row").data("id"), operator_session_token: state.session_token,
				} });
				window.open(response.message.url, "_blank", "noopener");
			});
			$field.find(".cfg-remove-process-media").off("click").on("click", function () {
				const media_id = $(this).closest(".cfg-process-media-row").data("id");
				frappe.confirm(__("Remove this accidental attachment? The audit record will be retained."), async () => {
					await frappe.call({ method: "cfg_kanban.api.media.archive_process_task_media", args: {
						task_name: task.name, media_id, operator_session_token: state.session_token,
					}, freeze: true });
					rows = rows.filter((row) => row.media_id !== media_id);
					refresh();
				});
			});
		};
		refresh();
		if (action === "Verify") return;
		const handle_upload = async (input, camera_capture) => {
			let files = Array.from(input.files || []);
			const $status = $field.find(".cfg-process-media-status");
			try {
				let capture_timestamp = null;
				let geotag = null;
				if (camera_capture) {
					geotag = await process_execution_geotag();
					const stamp = await frappe.call({ method: "cfg_kanban.api.media.get_process_task_camera_stamp", args: {
						task_name: task.name, operator_session_token: state.session_token,
					} });
					capture_timestamp = stamp.message.captured_at;
					files = [await stamp_process_photo(files[0], capture_timestamp, task.name, geotag)];
				}
				for (const file of files) {
					$status.html(`<div class="alert alert-info">${__("Uploading {0}", [frappe.utils.escape_html(file.name)])}</div>`);
					const auth = await frappe.call({ method: "cfg_kanban.api.media.create_process_task_upload_url", args: {
						task_name: task.name, original_filename: file.name, content_type: file.type,
						size_bytes: file.size, idempotency_key: frappe.utils.get_random(32),
						operator_session_token: state.session_token,
						capture_source: camera_capture ? "timestamped-camera" : "file-upload",
						capture_timestamp,
						latitude: geotag && geotag.latitude, longitude: geotag && geotag.longitude,
						location_accuracy: geotag && geotag.accuracy,
					} });
					if (!auth.message.already_available) {
						const upload = auth.message;
						const form = new FormData();
						Object.entries(upload.fields || {}).forEach(([key, value]) => form.append(key, value));
						form.append("file", file);
						const result = await fetch(upload.url, { method: upload.method, body: form });
						if (!result.ok) throw new Error(__("Private media upload failed with HTTP {0}", [result.status]));
						await frappe.call({ method: "cfg_kanban.api.media.confirm_process_task_upload", args: {
							task_name: task.name, media_id: upload.media_id, confirmation_token: upload.confirmation_token,
							operator_session_token: state.session_token,
						} });
					}
				}
				const response = await frappe.call({ method: "cfg_kanban.api.media.list_process_task_media", args: {
					task_name: task.name, operator_session_token: state.session_token,
				} });
				rows = response.message || [];
				refresh();
				$status.html(`<div class="alert alert-success">${__("Evidence uploaded and verified")}</div>`);
			} catch (error) {
				$status.html(`<div class="alert alert-danger">${frappe.utils.escape_html(error.message || __("Media upload failed"))}</div>`);
			} finally { input.value = ""; }
		};
		$field.find(".cfg-process-camera-picker input").on("change", function () { handle_upload(this, true); });
		$field.find(".cfg-process-file-picker input").on("change", function () { handle_upload(this, false); });
	}

	function process_execution_geotag() {
		if (!navigator.geolocation) return Promise.reject(new Error(__("This device does not provide geolocation.")));
		return new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(
			(position) => resolve({ latitude: position.coords.latitude, longitude: position.coords.longitude,
				accuracy: position.coords.accuracy }),
			() => reject(new Error(__("Location permission is required for timestamped task photos. Use Upload File for existing evidence."))),
			{ enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
		));
	}

	async function stamp_process_photo(file, captured_at, task_name, geotag) {
		const bitmap = await load_process_bitmap(file);
		const canvas = document.createElement("canvas");
		canvas.width = bitmap.width; canvas.height = bitmap.height;
		const context = canvas.getContext("2d");
		context.drawImage(bitmap, 0, 0);
		const font_size = Math.max(24, Math.round(canvas.width * 0.027));
		const padding = Math.round(font_size * 0.7);
		context.fillStyle = "rgba(0,0,0,0.72)";
		context.fillRect(0, canvas.height - font_size * 3.4, canvas.width, font_size * 3.4);
		context.fillStyle = "#fff"; context.font = `bold ${font_size}px Arial`;
		context.fillText(`${captured_at} · ${task_name}`, padding, canvas.height - font_size * 1.55);
		context.font = `${Math.round(font_size * 0.65)}px Arial`;
		context.fillText(`GPS ${geotag.latitude.toFixed(6)}, ${geotag.longitude.toFixed(6)} · ±${Math.round(geotag.accuracy)}m`, padding, canvas.height - font_size * 0.75);
		context.fillText("CFG Kanban execution capture · server time + device geolocation", padding, canvas.height - font_size * 0.18);
		const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));
		if (bitmap.close) bitmap.close();
		if (!blob) throw new Error(__("The camera photo could not be timestamped."));
		const base = String(file.name || "photo").replace(/\.[^.]+$/, "");
		return new File([blob], `${base}-timestamped.jpg`, { type: "image/jpeg", lastModified: Date.now() });
	}

	async function load_process_bitmap(file) {
		if (window.createImageBitmap) return createImageBitmap(file);
		return new Promise((resolve, reject) => {
			const image = new Image();
			const url = URL.createObjectURL(file);
			image.onload = () => { URL.revokeObjectURL(url); resolve(image); };
			image.onerror = () => { URL.revokeObjectURL(url); reject(new Error(__("The selected image could not be read."))); };
			image.src = url;
		});
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

	async function consume_card(scanner_mode = false) {
		if (!state.context || !state.context.card) {
			return scanner_command_message(__("Scan a Kanban card first."));
		}
		const card = state.context.card;
		if (state.context.cycle || card.current_state !== "Available" ||
			!state.operator.permissions.consume) {
			return scanner_command_message(__("The selected Card is not available for activation by this operator."));
		}
		if (["Process Kanban", "Station Kanban"].includes(card.card_type)) {
			return propose_runtime_selection(card, scanner_mode);
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

	async function propose_runtime_selection(card, scanner_mode = false) {
		const response = await frappe.call({
			method: "cfg_kanban.api.operator.preview_runtime_selection",
			args: { card_name: card.name, operator_session_token: state.session_token }, freeze: true,
			freeze_message: __("Finding eligible production work..."),
		});
		let proposal = response.message;
		const candidate_options = proposal.candidates.map((candidate) => ({
			label: candidate.label, value: candidate.job_card,
		}));
		const numbered_candidates = `<div class="alert alert-info"><strong>${__("Scanner choices")}</strong><br>${
			candidate_options.map((candidate, index) => `${index + 1}. ${frappe.utils.escape_html(candidate.label)}`).join("<br>")
		}</div>`;
		let dialog;
		const proposal_html = (value) => `<div class="mb-3">
			<b>${__("Item")}</b>: ${frappe.utils.escape_html(value.item_code || card.item_code)}<br>
			<b>${__("Recommendation Basis")}</b>: ${frappe.utils.escape_html(value.selection_basis || "-")}
			${value.selection_basis === "Supervisor Dispatch Queue" ? ` · ${__("Queue")} #${value.selection_rank}` : ""}<br>
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
				{ fieldname: "numbered_candidates", fieldtype: "HTML", options: numbered_candidates },
				{ fieldname: "selected_job_card", label: __("Eligible Work Order / Job Card"), fieldtype: "Select",
					options: candidate_options, default: proposal.recommended_job_card, reqd: 1,
					description: __("An audited supervisor dispatch sequence for this workstation is selected first. Otherwise the Operation Profile runtime rule applies. Only item-, operation-, company-, status-, input-, and workstation-eligible choices are listed."),
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
					default: __("Operator confirmed runtime allocation from the Kanban panel"),
					description: proposal.short_cycle ? __("Confirm that the reduced quantity and reason are understood.") : __("Confirm the proposed Work Order, Job Card, and quantity.") },
				{ fieldname: "scanner_command", label: __("Scanner Command"), fieldtype: "Data",
					description: __("Scan Confirm / Submit or Cancel after reviewing the proposed allocation.") },
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
		bind_confirmation_scanner(dialog, true,
			candidate_options.map((row) => row.value), "selected_job_card");
	}

	function render_job_role_coverage(role_coverage) {
		if (!role_coverage?.configured) return;
		const e = frappe.utils.escape_html;
		const colour = role_coverage.status === "Compliant" ? "green" :
			role_coverage.status === "Attention" ? "red" : "orange";
		const rows = (role_coverage.requirements || []).map((row) => {
			const people = (row.assignments || [])
				.map((assignment) => assignment.employee_name || assignment.employee)
				.join(", ") || __("Awaiting eligible active assignment");
			return `<div class="col-md-6 mb-2"><strong>${e(row.assignment_type)}</strong>
				<span class="indicator-pill ${row.missing_count ? "orange" : "green"}">${e(row.assigned_count)} / ${e(row.required_count)}</span>
				<br><small>${e(people)}</small></div>`;
		}).join("");
		$(`<div class="frappe-card p-3 mb-3" data-live-focus="job-role-coverage">
			<div class="d-flex justify-content-between align-items-center mb-2">
				<strong>${__("Job Role Coverage")}</strong>
				<span class="indicator-pill ${colour}">${e(role_coverage.status)}</span>
			</div>
			<div class="text-muted mb-2">${e(role_coverage.summary || "")}</div>
			<div class="row">${rows}</div>
			<small class="text-muted">${__("Advisory visibility only in P07-0B1; missing coverage does not block production actions.")}</small>
		</div>`).appendTo($root);
	}

	function render_executions(executions) {
		if (!executions.length) return;
		const e = frappe.utils.escape_html;
		const $section = $(`<div><div class="d-flex justify-content-between align-items-center mb-2">
			<h4 class="mb-0">${__("Job Card Execution Lanes")}</h4><div class="cfg-correction-actions"></div></div></div>`).appendTo($root);
		add_action($section.find(".cfg-correction-actions"), __("Report Correction"), "btn-warning",
			() => correction_request_dialog(crew_execution_context().name));
		const correction_requests = state.context?.correction_requests || [];
		if (correction_requests.length) {
			const latest = correction_requests[0];
			const colour = latest.status === "Resolved" ? "green" : latest.status === "Rejected" ? "grey" :
				latest.status === "ERP Correction Required" ? "red" : "orange";
			$section.append(`<div class="alert alert-${colour === "green" ? "success" : colour === "red" ? "danger" : "warning"} py-2 mb-3">
				<strong>${__("Latest Correction Request")}: ${e(latest.name)}</strong> ·
				<span class="indicator-pill ${colour}">${e(latest.status)}</span><br>
				<small>${e(latest.correction_category)} · ${e(latest.reason)}</small></div>`);
		}
		const ownership = state.context?.job_ownership;
		if (ownership?.enabled) {
			const colour = ownership.owner ? "green" : ownership.eligible_to_accept ? "orange" : "red";
			const owner_text = ownership.owner
				? `${ownership.owner_name || ownership.owner} · ${ownership.required_job_code}`
				: ownership.eligible_to_accept
					? `${__("You are eligible to accept ownership")} · ${ownership.required_job_code}`
					: `${__("Eligible operator required")} · ${ownership.required_job_code}`;
			const $ownership_banner = $(`<div class="alert alert-${colour === "green" ? "success" : colour === "orange" ? "warning" : "danger"} py-2 mb-3">
				<strong>${__("Cycle Operator-in-Charge")}</strong><br>${e(owner_text)}
				${ownership.owner ? `<br><small>${__("Other authorized operators may still participate as assistants, trainers, or supervisors without replacing the owner.")}</small>` : ""}
			</div>`).appendTo($section);
			if (!ownership.owner && ownership.eligible_to_accept && state.operator.permissions.start) {
				add_action($ownership_banner, __("Accept Ownership"), "btn-primary mt-2", async () => {
					await frappe.call({
						method: "cfg_kanban.api.operator.accept_job_ownership",
						args: { execution_name: executions[0].name,
							operator_session_token: state.session_token },
						freeze: true,
						freeze_message: __("Accepting Cycle ownership..."),
					});
					frappe.show_alert({ message: __("Cycle ownership accepted"), indicator: "green" });
					await load_card(state.context.card.qr_code);
				});
			}
			if (ownership.owner && ownership.transfer?.available && ownership.transfer_execution) {
				add_action($ownership_banner, __("Transfer Owner"), "btn-warning mt-2", () =>
					open_job_ownership_transfer(ownership.transfer_execution));
			} else if (ownership.owner && ownership.transfer && !ownership.transfer.available) {
				$ownership_banner.append(`<br><small class="text-muted">${e(ownership.transfer.reason || __("Controlled ownership transfer is not configured for this Cycle snapshot."))}</small>`);
			}
		}
		executions.forEach((row) => {
			const crew = row.crew || {};
			const crew_colour = crew.compliance_status === "Compliant" ? "green" :
				crew.compliance_status === "Hold" ? "red" : crew.session ? "blue" : "grey";
			const crew_text = crew.session
				? `${crew.main_employee_name || crew.main_employee || __("Crew active")} · ${__("Active")}: ${crew.active_count || 0} · ${__("Break")}: ${crew.break_count || 0}`
				: __("No active workstation crew");
			const $row = $(`<div class="frappe-card p-3 mb-2" data-live-focus="execution:${e(row.name)}">
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
			$(`<div class="cfg-execution-crew-strip ${crew_colour}">
				<div><strong>${__("Workstation Crew")}</strong><span>${e(crew_text)}</span></div>
				<div><span class="indicator-pill ${crew_colour}">${e(crew.compliance_status || __("Not Checked"))}</span>
				<button class="btn btn-sm btn-default cfg-open-crew">${__("Crew Controls")}</button></div>
			</div>`).appendTo($row).find(".cfg-open-crew").on("click", () => open_crew_control(row));
			const $buttons = $row.find(".cfg-execution-actions");
			if (row.status === "Ready" && state.operator.permissions.start) {
				if (ownership?.enabled && !ownership.owner && !ownership.eligible_to_accept) {
					$(`<button class="btn btn-sm btn-warning ml-1" disabled>${__("Job Code Required")}</button>`).appendTo($buttons);
				} else {
					const start_label = ownership?.enabled && !ownership.owner
						? __("Accept Ownership and Start") : __("Start");
					add_action($buttons, start_label, "btn-primary", () => job_action(row, "start"));
				}
			}
			if (["Ready", "In Progress", "Paused"].includes(row.status) && state.operator.permissions.report_progress) add_action($buttons, __("Report Progress"), "btn-default", () => progress_dialog(row));
			if (row.status === "In Progress" && !row.runtime_allocation && state.operator.permissions.complete) add_action($buttons, __("Complete"), "btn-default", () => job_action(row, "complete"));
			if (row.runtime_allocation && row.job_card_needs_submit && state.operator.permissions.complete) {
				add_action($buttons, __("Complete Job Card"), "btn-primary", () => job_action(row, "complete"));
			}
			if (row.runtime_allocation && (row.processed_qty || 0) >= (row.target_qty || 0) && row.can_close_runtime_cycle && state.operator.permissions.complete) {
				const close_label = row.close_requires_supervisor_approval
					? __("Supervisor Pass & Close") : __("Close Kanban Cycle");
				const close_class = row.close_requires_supervisor_approval ? "btn-warning" : "btn-success";
				add_action($buttons, close_label, close_class, () => close_runtime_cycle(row));
				if (row.wip_bin_erp_posting_pending) {
					$row.append(`<div class="mt-2 alert alert-warning py-2"><small>${__("Operation use is recorded for this Job Card. Its ERP consumption {0} remains pending, but it does not prevent the next operation from starting after this Job Card reaches its progress target.", [(row.wip_bin_pending_entries || []).join(", ")])}</small></div>`);
				}
			}
			if (row.runtime_allocation && (row.processed_qty || 0) >= (row.target_qty || 0) && !row.can_close_runtime_cycle) {
				const $blocked = $("<button class='btn btn-sm btn-warning ml-1'>" + __("ERP Update Required") + "</button>").appendTo($buttons);
				$blocked.on("click", () => frappe.msgprint({ title: __("Cannot Close Kanban Cycle"),
					message: e(row.close_block_reason || __("ERP Work Order and Job Card are not ready.")), indicator: "orange" }));
			}
		});
	}

	function crew_execution_context() {
		const executions = state.context?.executions || [];
		if (!executions.length) return null;
		const focus = String(state.current_live_focus?.key || "");
		if (focus.startsWith("execution:")) {
			const name = focus.slice(10);
			const focused = executions.find((row) => row.name === name);
			if (focused) return focused;
		}
		return executions.find((row) => ["In Progress", "Blocked", "Paused"].includes(row.status)) ||
			executions.find((row) => row.status === "Ready") || executions[0];
	}

	function open_context_crew_control(initial_command) {
		const row = crew_execution_context();
		if (!row) return scanner_command_message(__("Scan a production or operation Card with an execution lane first."));
		return open_crew_control(row, initial_command);
	}

	async function open_crew_control(row, initial_command) {
		const response = await frappe.call({
			method: "cfg_kanban.api.operator.get_execution_crew_panel",
			args: { execution_name: row.name, operator_session_token: state.session_token },
		});
		const panel = response.message;
		const templates = panel.templates || [];
		const template_options = [{ label: __("No template"), value: "" }].concat(
			templates.map((template) => ({
				label: `${template.template_name || template.template_code} · R${template.revision || 1}`,
				value: template.name,
			}))
		);
		let dialog;
		dialog = new frappe.ui.Dialog({
			title: __("Workstation Crew: {0}", [panel.execution.workstation]),
			fields: [
				{ fieldname: "crew_status", fieldtype: "HTML" },
				{ fieldname: "crew_template", label: __("Expected Crew Template"), fieldtype: "Select",
					options: template_options, default: template_options.length === 2 ? template_options[1].value : "",
					description: __("Optional expected roster snapshot. Every person must still scan to join.") },
				{ fieldname: "reason", label: __("Reason / Crew Note"), fieldtype: "Small Text",
					default: __("Crew action from Production Operator Panel") },
				{ fieldname: "crew_actions", fieldtype: "HTML" },
				{ fieldname: "scanner_command", label: __("Crew Scanner Input"), fieldtype: "Data",
					description: __("Scan a Crew command, then scan the employee's normal operator QR when requested.") },
			],
			primary_action_label: __("Refresh Crew"),
			primary_action: async () => {
				const active = state.active_crew_dialog;
				if (active?.pending_close) return close_crew_from_dialog(dialog);
				if (!active?.panel?.crew) return open_crew_from_dialog(dialog);
				await refresh_crew_dialog(dialog);
			},
		});
		state.active_crew_dialog = { dialog, row, panel, pending_action: null,
			pending_open: false, pending_close: false };
		dialog.onhide = async () => {
			if (state.active_crew_dialog?.dialog === dialog) state.active_crew_dialog = null;
			if (state.context?.card?.qr_code) await load_card(state.context.card.qr_code);
			else focus_scanner();
		};
		dialog.show();
		render_crew_dialog(dialog);
		dialog.cfg_raw_scanner_handler = (value) => handle_crew_dialog_scan(dialog, value);
		bind_confirmation_scanner(
			dialog, true, template_options.map((option) => option.value), "crew_template"
		);
		if (initial_command) await handle_crew_dialog_scan(dialog, initial_command);
	}

	function render_crew_dialog(dialog) {
		const active = state.active_crew_dialog;
		if (!active || active.dialog !== dialog) return;
		const panel = active.panel;
		const crew = panel.crew;
		const members = crew?.members || [];
		const e = frappe.utils.escape_html;
		const findings = (panel.findings || []).map((row) => `<li>${e(row.message || row.code)}</li>`).join("");
		const member_rows = members.length ? members.map((row) => `<tr>
			<td>${e(row.employee_name || row.employee)}</td><td>${e(row.crew_role)}</td>
			<td>${e(row.work_category)}</td><td><span class="indicator-pill ${row.status === "Active" ? "green" : "orange"}">${e(row.status)}</span></td>
		</tr>`).join("") : `<tr><td colspan="4" class="text-muted">${__("No scanned crew members")}</td></tr>`;
		const policy = panel.configured
			? `${e(panel.policy.crew_mode || __("Configured"))} · ${__("Minimum direct")}: ${e(panel.policy.minimum_direct_workers || 0)}`
			: __("No crew requirement configured; attendance can still be recorded.");
		const status_html = `<div class="cfg-crew-dialog-status ${panel.allowed ? "is-compliant" : "is-hold"}">
			<div><strong>${e(panel.execution.operation)}</strong><span>${e(panel.execution.workstation)} · ${e(panel.execution.job_card || "-")}</span></div>
			<div><span class="indicator-pill ${panel.allowed ? "green" : "red"}">${panel.allowed ? __("Compliant") : __("Crew Hold")}</span></div>
			<p>${policy}</p>${findings ? `<ul>${findings}</ul>` : ""}
			<table class="table table-bordered table-sm"><thead><tr><th>${__("Employee")}</th><th>${__("Role")}</th><th>${__("Work")}</th><th>${__("Presence")}</th></tr></thead><tbody>${member_rows}</tbody></table>
		</div>`;
		dialog.get_field("crew_status").df.options = status_html;
		dialog.get_field("crew_status").refresh();

		const instruction = active.pending_action
			? __("Now scan the employee operator QR for: {0}", [crew_action_label(active.pending_action)])
			: active.pending_open
				? __("Scan Confirm / Submit to open this Workstation Crew, or scan Cancel.")
			: active.pending_close
				? __("Scan Confirm / Submit to close the whole Crew Session, or scan Cancel.")
				: __("Choose an action below or scan a Crew command label.");
		const disabled = crew && !panel.can_manage ? " disabled" : "";
		const actions = crew ? `<div class="cfg-crew-scan-instruction">${instruction}</div>
			<div class="cfg-crew-actions">
				<button class="btn btn-primary" data-crew-action="join_direct"${disabled}>${__("Join Direct")}</button>
				<button class="btn btn-info" data-crew-action="join_oversight"${disabled}>${__("Join Oversight")}</button>
				<button class="btn btn-default" data-crew-action="join_temp"${disabled}>${__("Join Temporary")}</button>
				<button class="btn btn-warning" data-crew-action="break"${disabled}>${__("Start Break")}</button>
				<button class="btn btn-success" data-crew-action="resume"${disabled}>${__("Resume")}</button>
				<button class="btn btn-default" data-crew-action="leave"${disabled}>${__("Leave")}</button>
				<button class="btn btn-default" data-crew-action="main"${disabled}>${__("Make Main")}</button>
				<button class="btn btn-default" data-crew-action="context"${disabled}>${__("Use This Operation")}</button>
				<button class="btn btn-danger" data-crew-action="close"${disabled}>${__("Close Crew")}</button>
			</div>` : `<div class="cfg-crew-scan-instruction">${instruction}</div>
			<button class="btn btn-primary btn-lg btn-block" data-crew-action="open">${__("Open Crew Session")}</button>`;
		dialog.get_field("crew_actions").df.options = actions;
		dialog.get_field("crew_actions").refresh();
		dialog.get_field("crew_actions").$wrapper.find("[data-crew-action]").on("click", function () {
			select_crew_action(dialog, $(this).data("crew-action"));
		});
		dialog.get_primary_btn().text(
			active.pending_close ? __("Confirm Close Crew") : active.pending_open ? __("Confirm Open Crew") :
				crew ? __("Refresh Crew") : __("Open Crew Session")
		);
		window.setTimeout(() => dialog.get_field("scanner_command").set_focus(), 80);
	}

	function crew_action_label(action) {
		return ({ join_direct: __("Join Direct"), join_oversight: __("Join Oversight"),
			join_temp: __("Join Temporary"), break: __("Start Break"), resume: __("Resume"),
			leave: __("Leave"), main: __("Change Main Operator") })[action] || action;
	}

	async function select_crew_action(dialog, action) {
		const active = state.active_crew_dialog;
		if (!active || active.dialog !== dialog) return;
		active.pending_action = null;
		active.pending_open = false;
		active.pending_close = false;
		if (action === "open") return open_crew_from_dialog(dialog);
		if (action === "context") return set_crew_context_from_dialog(dialog);
		if (action === "close") {
			active.pending_close = true;
			render_crew_dialog(dialog);
			return;
		}
		active.pending_action = action;
		render_crew_dialog(dialog);
	}

	async function handle_crew_dialog_scan(dialog, raw_value) {
		const active = state.active_crew_dialog;
		if (!active || active.dialog !== dialog) return;
		const value = String(raw_value || "").trim();
		const command = value.toUpperCase();
		await dialog.set_value("scanner_command", "");
		const command_actions = {
			"CFG:CMD:CREW_JOIN": "join_direct", "CFG:CMD:CREW_JOIN_OVERSIGHT": "join_oversight",
			"CFG:CMD:CREW_JOIN_TEMP": "join_temp", "CFG:CMD:CREW_BREAK": "break",
			"CFG:CMD:CREW_RESUME": "resume", "CFG:CMD:CREW_LEAVE": "leave",
			"CFG:CMD:CREW_MAIN": "main", "CFG:CMD:CREW_CONTEXT": "context",
			"CFG:CMD:CREW_CLOSE": "close",
		};
		if (command === "CFG:CMD:CREW") return render_crew_dialog(dialog);
		if (command === "CFG:CMD:CREW_OPEN") {
			active.pending_action = null;
			active.pending_open = true;
			active.pending_close = false;
			return render_crew_dialog(dialog);
		}
		if (command_actions[command]) return select_crew_action(dialog, command_actions[command]);
		if (["CFG:CMD:CANCEL", "CFG:CMD:DISMISS"].includes(command)) return dialog.hide();
		if (command === "CFG:CMD:CONFIRM") {
			if (active.pending_close) return close_crew_from_dialog(dialog);
			if (active.pending_open) return open_crew_from_dialog(dialog);
			if (!active.panel.crew) return open_crew_from_dialog(dialog);
			return refresh_crew_dialog(dialog);
		}
		if (!active.pending_action) {
			frappe.show_alert({ message: __("Scan a Crew action command before scanning an employee QR."), indicator: "orange" });
			return render_crew_dialog(dialog);
		}
		return run_scanned_crew_member_action(dialog, operator_token_from_scan(value));
	}

	async function open_crew_from_dialog(dialog) {
		const active = state.active_crew_dialog;
		const values = dialog.get_values(true) || {};
		await frappe.call({ method: "cfg_kanban.api.operator.open_execution_crew_session", args: {
			execution_name: active.row.name, crew_template: values.crew_template || null,
			notes: values.reason, operator_session_token: state.session_token,
		}, freeze: true, freeze_message: __("Opening workstation crew...") });
		await refresh_crew_dialog(dialog);
	}

	async function set_crew_context_from_dialog(dialog) {
		const active = state.active_crew_dialog;
		await frappe.call({ method: "cfg_kanban.services.crew_registry.set_crew_operation_context", args: {
			crew_session: active.panel.crew.name, operation: active.panel.execution.operation,
			reason: dialog.get_value("reason"), operator_session_token: state.session_token,
		}, freeze: true });
		await refresh_crew_dialog(dialog);
	}

	async function close_crew_from_dialog(dialog) {
		const active = state.active_crew_dialog;
		await frappe.call({ method: "cfg_kanban.services.crew_registry.close_workstation_crew_session", args: {
			crew_session: active.panel.crew.name,
			reason: dialog.get_value("reason") || __("Closed from Production Operator Panel"),
			operator_session_token: state.session_token,
		}, freeze: true, freeze_message: __("Closing workstation crew...") });
		active.pending_close = false;
		await refresh_crew_dialog(dialog);
	}

	async function run_scanned_crew_member_action(dialog, member_token) {
		const active = state.active_crew_dialog;
		const action = active.pending_action;
		const args = { crew_session: active.panel.crew.name, member_qr_token: member_token,
			operator_session_token: state.session_token, reason: dialog.get_value("reason") };
		let method;
		if (["join_direct", "join_oversight", "join_temp"].includes(action)) {
			method = "cfg_kanban.services.crew_registry.join_crew_member";
			args.crew_role = action === "join_temp" ? "Temporary Support" :
				action === "join_oversight" ? "Senior / Overseer" : "Supporting Operator";
			args.work_category = action === "join_oversight" ? "Oversight Only" : "Direct Participation";
		} else {
			method = ({ break: "break_crew_member", resume: "resume_crew_member",
				leave: "leave_crew_member", main: "change_main_operator" })[action];
			method = `cfg_kanban.services.crew_registry.${method}`;
		}
		await frappe.call({ method, args, freeze: true, freeze_message: __("Updating workstation crew...") });
		active.pending_action = null;
		frappe.show_alert({ message: __("Crew updated"), indicator: "green" });
		await refresh_crew_dialog(dialog);
	}

	async function refresh_crew_dialog(dialog) {
		const active = state.active_crew_dialog;
		if (!active || active.dialog !== dialog) return;
		const response = await frappe.call({ method: "cfg_kanban.api.operator.get_execution_crew_panel", args: {
			execution_name: active.row.name, operator_session_token: state.session_token,
		} });
		active.panel = response.message;
		active.pending_action = null;
		active.pending_open = false;
		active.pending_close = false;
		render_crew_dialog(dialog);
	}

	function close_runtime_cycle(row) {
		const e = frappe.utils.escape_html;
		const approval = row.close_approval || {};
		const requires_supervisor = Boolean(row.close_requires_supervisor_approval);
		let supervisor_approval_token = null;
		const approval_reason = __("Supervisor reviewed and authorized Cycle closure on behalf of the assigned operator-in-charge.");
		const supervisor_fields = requires_supervisor ? [
			{ fieldname: "supervisor_pass_help", fieldtype: "HTML", options:
				`<div class="alert alert-warning"><strong>${__("Exact-action supervisor pass required")}</strong><br>
				${__("Assigned operator-in-charge")}: ${e(approval.cycle_owner_name || approval.cycle_owner || "-")}<br>
				${__("Scan an eligible supervisor or verifier credential below. This approves only this Cycle-close attempt and does not switch the active operator.")}</div>` },
			{ fieldname: "supervisor_reason", label: __("Supervisor Approval Reason"),
				fieldtype: "Small Text", reqd: 1, default: approval_reason },
			{ fieldname: "supervisor_pin", label: __("Supervisor PIN, if required"),
				fieldtype: "Password" },
			{ fieldname: "supervisor_pass_status", fieldtype: "HTML", options:
				`<div class="text-muted">${__("Awaiting eligible supervisor credential scan")}</div>` },
		] : [];
		const dialog = new frappe.ui.Dialog({
			title: __("Close Kanban Cycle"),
			fields: [
				{ fieldname: "closure_summary", fieldtype: "HTML", options:
					`<div class="alert alert-warning"><strong>${__("Final closure confirmation")}</strong><br>
					${__("Operation")}: ${e(row.operation || "-")}<br>
					${__("Job Card")}: ${e(row.job_card || "-")}<br>
					${__("Processed")}: ${e(row.processed_qty || 0)} / ${e(row.target_qty || 0)}<br>
					${__("ERP and process gates will be checked again before closure.")}</div>` },
				{ fieldname: "notes", label: __("Completion Notes"), fieldtype: "Small Text" },
				...supervisor_fields,
				{ fieldname: "scanner_command", label: __("Scanner Command"), fieldtype: "Data",
					description: requires_supervisor
						? __("First scan the supervisor credential. After approval, scan Confirm / Submit to close, or scan Cancel.")
						: __("Scan Confirm / Submit to close and release the Card, or scan Cancel.") },
			],
			primary_action_label: requires_supervisor
				? __("Use Supervisor Pass and Close") : __("Close Cycle and Release Card"),
			primary_action: async (values) => {
				if (requires_supervisor && !supervisor_approval_token) {
					frappe.show_alert({ message: __("Scan an eligible supervisor credential first"), indicator: "orange" });
					return window.setTimeout(() => dialog.get_field("scanner_command").set_focus(), 80);
				}
				const response = await frappe.call({ method: "cfg_kanban.api.operator.complete_runtime_cycle", args: {
					execution_name: row.name, notes: values.notes,
					operator_session_token: state.session_token,
					supervisor_approval_token,
				}, freeze: true, freeze_message: __("Closing Kanban Cycle...") });
				dialog.hide();
				const result = response.message;
				frappe.show_alert({ message: result.wip_bin_erp_posting_pending
					? __("Operation closed; ERP WIP-bin consumption remains pending in {0}", [(result.wip_bin_pending_entries || []).join(", ")])
					: result.job_card_target_reached
					? __("Cycle completed and ERPNext Job Card submitted")
					: __("Cycle completed; reusable card is available for the remaining Job Card demand"), indicator: "green" });
				await load_card(state.context.card.qr_code);
			},
		});
		dialog.show();
		if (requires_supervisor) {
			dialog.cfg_raw_scanner_handler = async (credential) => {
				const reason = String(dialog.get_value("supervisor_reason") || "").trim();
				if (!reason) {
					frappe.show_alert({ message: __("Enter the supervisor approval reason before scanning"), indicator: "orange" });
					return;
				}
				const response = await frappe.call({
					method: "cfg_kanban.api.operator.approve_supervisor_action",
					args: {
						action_code: "CLOSE_CYCLE_ON_BEHALF",
						execution_name: row.name,
						supervisor_qr_token: operator_token_from_scan(credential),
						supervisor_pin: dialog.get_value("supervisor_pin"),
						reason,
						operator_session_token: state.session_token,
					},
					freeze: true,
					freeze_message: __("Validating exact-action supervisor pass..."),
				});
				supervisor_approval_token = response.message.approval_token;
				const status = dialog.get_field("supervisor_pass_status");
				status.$wrapper.html(`<div class="alert alert-success py-2 mb-2">
					<strong>${__("Supervisor pass approved")}</strong><br>
					${e(response.message.approved_by_name || response.message.approved_by_employee)} ·
					${__("valid for this close attempt until")} ${e(response.message.expires_on)}</div>`);
				frappe.show_alert({ message: __("Supervisor pass accepted. Scan Confirm / Submit to close."), indicator: "green" });
			};
		}
		bind_confirmation_scanner(dialog, true);
	}

	function transfer_context_job_ownership() {
		const ownership = state.context?.job_ownership;
		if (!ownership?.owner || !ownership.transfer?.available || !ownership.transfer_execution) {
			frappe.show_alert({
				message: ownership?.transfer?.reason || __("Ownership transfer is not available for this Card"),
				indicator: "orange",
			});
			return focus_scanner();
		}
		open_job_ownership_transfer(ownership.transfer_execution);
	}

	function open_job_ownership_transfer(execution_name) {
		const e = frappe.utils.escape_html;
		const ownership = state.context?.job_ownership || {};
		let replacement_token = null;
		let supervisor_approval_token = null;
		let scan_stage = "replacement";
		const dialog = new frappe.ui.Dialog({
			title: __("Transfer Cycle Ownership"),
			fields: [
				{ fieldname: "transfer_warning", fieldtype: "HTML", options:
					`<div class="alert alert-warning"><strong>${__("Controlled ownership transfer")}</strong><br>
					${__("Current operator-in-charge")}: ${e(ownership.owner_name || ownership.owner || "-")}<br>
					${__("The existing assignment will be ended, not overwritten. ERPNext documents and production quantities are unchanged.")}</div>` },
				{ fieldname: "reason", label: __("Transfer Reason"), fieldtype: "Small Text", reqd: 1 },
				{ fieldname: "replacement_pin", label: __("Replacement Operator PIN, if required"), fieldtype: "Password" },
				{ fieldname: "supervisor_pin", label: __("Supervisor PIN, if required"), fieldtype: "Password" },
				{ fieldname: "transfer_scan_status", fieldtype: "HTML", options:
					`<div class="alert alert-info py-2 mb-2"><strong>${__("Step 1 of 2")}</strong><br>${__("Scan the replacement operator credential.")}</div>` },
				{ fieldname: "scanner_command", label: __("Scanner Command"), fieldtype: "Data",
					description: __("Scan replacement operator, then approving supervisor, then Confirm / Submit. Scan Cancel to leave without changing ownership.") },
			],
			primary_action_label: __("Transfer Ownership"),
			primary_action: async (values) => {
				if (!replacement_token) {
					frappe.show_alert({ message: __("Scan the replacement operator credential first"), indicator: "orange" });
					return;
				}
				if (!supervisor_approval_token) {
					frappe.show_alert({ message: __("Scan an eligible approving supervisor credential"), indicator: "orange" });
					return;
				}
				const response = await frappe.call({
					method: "cfg_kanban.api.operator.transfer_job_ownership",
					args: {
						execution_name,
						replacement_qr_token: replacement_token,
						replacement_pin: values.replacement_pin,
						reason: String(values.reason || "").trim(),
						supervisor_approval_token,
						operator_session_token: state.session_token,
					},
					freeze: true,
					freeze_message: __("Transferring Cycle ownership..."),
				});
				dialog.hide();
				frappe.show_alert({
					message: __("Ownership transferred to {0}", [response.message.new_owner_name || response.message.new_owner]),
					indicator: "green",
				});
				await load_card(state.context.card.qr_code);
			},
		});
		dialog.show();
		dialog.cfg_raw_scanner_handler = async (credential) => {
			const reason = String(dialog.get_value("reason") || "").trim();
			if (!reason) {
				frappe.show_alert({ message: __("Enter the transfer reason before scanning"), indicator: "orange" });
				return;
			}
			if (scan_stage === "replacement") {
				replacement_token = operator_token_from_scan(credential);
				try {
					const response = await frappe.call({
						method: "cfg_kanban.api.operator.preview_job_ownership_transfer",
						args: {
							execution_name,
							replacement_qr_token: replacement_token,
							replacement_pin: dialog.get_value("replacement_pin"),
							operator_session_token: state.session_token,
						},
					});
					scan_stage = "supervisor";
					dialog.get_field("transfer_scan_status").$wrapper.html(
						`<div class="alert alert-info py-2 mb-2"><strong>${__("Replacement")}: ${e(response.message.employee_name || response.message.employee)}</strong><br>${__("Step 2 of 2: scan the eligible approving supervisor credential.")}</div>`
					);
					frappe.show_alert({ message: __("Replacement operator accepted. Scan supervisor approval."), indicator: "blue" });
				} catch (error) {
					replacement_token = null;
					throw error;
				}
				return;
			}
			const response = await frappe.call({
				method: "cfg_kanban.api.operator.approve_supervisor_action",
				args: {
					action_code: "TRANSFER_CYCLE_OWNERSHIP",
					execution_name,
					supervisor_qr_token: operator_token_from_scan(credential),
					supervisor_pin: dialog.get_value("supervisor_pin"),
					subject_qr_token: replacement_token,
					subject_pin: dialog.get_value("replacement_pin"),
					reason,
					operator_session_token: state.session_token,
				},
				freeze: true,
				freeze_message: __("Validating ownership-transfer supervisor pass..."),
			});
			supervisor_approval_token = response.message.approval_token;
			scan_stage = "approved";
			dialog.get_field("transfer_scan_status").$wrapper.html(
				`<div class="alert alert-success py-2 mb-2"><strong>${__("Transfer approved")}</strong><br>${__("Replacement")}: ${e(response.message.subject_name || response.message.subject_employee)}<br>${__("Approved by")}: ${e(response.message.approved_by_name || response.message.approved_by_employee)}<br>${__("Scan Confirm / Submit to transfer ownership.")}</div>`
			);
			frappe.show_alert({ message: __("Supervisor pass accepted. Scan Confirm / Submit."), indicator: "green" });
		};
		bind_confirmation_scanner(dialog, true);
	}

	function correction_request_dialog(execution_name) {
		const scopes = {
			"Cycle Status": ["Current Cycle"],
			"Operation Progress": ["Current Operation / Execution"],
			"Ownership": ["Current Ownership"],
			"Participation": ["My Participation"],
			"Material / ERP Record": ["Work Order", "Job Card"],
			"Other": ["Current Cycle", "Current Operation / Execution", "Work Order", "Job Card", "Current Ownership", "My Participation"],
		};
		let dialog;
		dialog = new frappe.ui.Dialog({
			title: __("Report a Correction for Supervisor Review"),
			fields: [
				{ fieldname: "boundary", fieldtype: "HTML", options:
					`<div class="alert alert-info"><strong>${__("Audit-safe request only")}</strong><br>${__("This request does not rewrite progress, ownership, participation, Job Cards, Work Orders, or Stock Entries. A supervisor must review it separately.")}</div>` },
				{ fieldname: "correction_category", label: __("Correction Category"), fieldtype: "Select",
					options: Object.keys(scopes), default: "Operation Progress", reqd: 1,
					onchange: async () => {
						if (!dialog) return;
						const choices = scopes[dialog.get_value("correction_category")] || [];
						dialog.set_df_property("affected_scope", "options", choices);
						await dialog.set_value("affected_scope", choices[0] || "");
					} },
				{ fieldname: "affected_scope", label: __("Affected Record"), fieldtype: "Select",
					options: scopes["Operation Progress"], default: "Current Operation / Execution", reqd: 1 },
				{ fieldname: "reason", label: __("What is incorrect?"), fieldtype: "Small Text", reqd: 1 },
				{ fieldname: "requested_change", label: __("What should be reviewed or corrected?"), fieldtype: "Text", reqd: 1 },
				{ fieldname: "evidence_notes", label: __("Evidence / Reference Notes"), fieldtype: "Small Text",
					description: __("Optional factual reference only. Existing source records remain unchanged.") },
				{ fieldname: "scanner_command", label: __("Scanner Command"), fieldtype: "Data",
					description: __("Scan Confirm / Submit to create the request, or Cancel to leave without a request.") },
			],
			primary_action_label: __("Submit Correction Request"),
			primary_action: async (values) => {
				const response = await frappe.call({
					method: "cfg_kanban.api.operator.submit_correction_request",
					args: {
						execution_name,
						correction_category: values.correction_category,
						affected_scope: values.affected_scope,
						reason: values.reason,
						requested_change: values.requested_change,
						evidence_notes: values.evidence_notes,
						event_token: frappe.utils.get_random(24),
						operator_session_token: state.session_token,
					},
					freeze: true,
					freeze_message: __("Recording correction request..."),
				});
				dialog.hide();
				frappe.show_alert({ message: __("Correction Request {0} recorded", [response.message.name]), indicator: "green" });
				await load_card(state.context.card.qr_code || state.context.card.card_number);
			},
		});
		dialog.show();
		bind_confirmation_scanner(dialog, true);
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
				const dynamic_values = visible_dynamic_definitions(definitions, values).map((definition) => ({
					field_key: definition.field_key, label: definition.label,
					field_type: definition.field_type, value: values[`dynamic_${definition.field_key}`], unit: definition.unit,
				}));
				const submitted = await frappe.call({ method: "cfg_kanban.api.operator.submit_progress", args: {
					execution_name: row.name, good_qty: values.good_qty, reject_qty: values.reject_qty,
					notes: values.notes, values: dynamic_values, event_token: frappe.utils.get_random(16),
					operator_session_token: state.session_token,
				}, freeze: true });
				dialog.hide();
				const deferred = submitted.message?.erp_result?.auto_submit_deferred;
				frappe.show_alert({ message: deferred
					? __("Progress recorded. Job Card auto-submit is waiting for the WIP-bin prerequisite.")
					: __("Progress recorded"), indicator: deferred ? "blue" : "green" }, 7);
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
		configure_dynamic_visibility(dialog, definitions);
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

	function configure_dynamic_visibility(dialog, definitions) {
		if (!definitions.length) return;
		const refresh = () => {
			const values = {};
			definitions.forEach((definition) => {
				values[`dynamic_${definition.field_key}`] = dialog.get_value(`dynamic_${definition.field_key}`);
			});
			const visible = new Set(visible_dynamic_definitions(definitions, values).map((row) => row.field_key));
			definitions.forEach((definition) => {
				const fieldname = `dynamic_${definition.field_key}`;
				const field = dialog.get_field(fieldname);
				const is_visible = visible.has(definition.field_key);
				const hidden = !is_visible;
				const required = is_visible && Boolean(Number(definition.mandatory));
				if (Boolean(field.df.hidden) !== hidden) dialog.set_df_property(fieldname, "hidden", hidden);
				if (Boolean(field.df.reqd) !== required) dialog.set_df_property(fieldname, "reqd", required);
			});
		};
		dialog.$wrapper.off(".cfg_visible").on(
			"change.cfg_visible",
			"[data-fieldname^='dynamic_'] :input",
			refresh,
		);
		refresh();
	}

	function visible_dynamic_definitions(definitions, dialog_values) {
		const rows = Object.fromEntries(definitions.map((row) => [row.field_key, row]));
		const values = Object.fromEntries(definitions.map((row) => [row.field_key,
			dialog_values[`dynamic_${row.field_key}`] ?? row.default_value]));
		const memo = {};
		const visible = (key, trail = []) => {
			if (Object.prototype.hasOwnProperty.call(memo, key)) return memo[key];
			if (trail.includes(key)) return false;
			const parsed = parse_visible_condition(rows[key].visible_condition);
			if (!parsed) return (memo[key] = true);
			let actual = values[parsed.field_key];
			if (rows[parsed.field_key] && !visible(parsed.field_key, [...trail, key])) actual = null;
			return (memo[key] = evaluate_visible_condition(parsed, actual));
		};
		return definitions.filter((row) => visible(row.field_key));
	}

	function parse_visible_condition(condition) {
		let expression = String(condition || "").trim();
		if (!expression) return null;
		expression = expression.replace(/^eval:\s*/i, "");
		const match = expression.match(/^(?:doc\.)?([A-Za-z][A-Za-z0-9_]*)(?:\s*(==|!=|=)\s*(.+))?$/);
		if (!match) return { invalid: true };
		let field_key = match[1];
		if (field_key.startsWith("dynamic_")) field_key = field_key.slice(8);
		return { field_key, operator: match[2] === "=" ? "==" : match[2], expected: parse_condition_value(match[3]) };
	}

	function parse_condition_value(value) {
		if (value === undefined) return undefined;
		const text = String(value).trim(); const lower = text.toLowerCase();
		if (["true", "yes", "on"].includes(lower)) return true;
		if (["false", "no", "off"].includes(lower)) return false;
		if (["none", "null"].includes(lower)) return null;
		if (/^-?(?:\d+\.?\d*|\.\d+)$/.test(text)) return Number(text);
		if ((text.startsWith("\"") && text.endsWith("\"")) || (text.startsWith("'") && text.endsWith("'"))) return text.slice(1, -1);
		return text;
	}

	function evaluate_visible_condition(parsed, actual) {
		if (!parsed || parsed.invalid) return false;
		if (!parsed.operator) return condition_truthy(actual);
		let equal;
		if (typeof parsed.expected === "boolean") equal = condition_truthy(actual) === parsed.expected;
		else if (typeof parsed.expected === "number") equal = Number(actual) === parsed.expected;
		else if (parsed.expected === null) equal = actual === null || actual === undefined || actual === "";
		else equal = String(actual ?? "") === String(parsed.expected);
		return parsed.operator === "==" ? equal : !equal;
	}

	function condition_truthy(value) {
		if (value === null || value === undefined || value === false || value === 0) return false;
		return !["", "0", "false", "no", "off", "none", "null"].includes(String(value).trim().toLowerCase());
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
