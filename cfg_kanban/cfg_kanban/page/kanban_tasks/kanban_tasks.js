frappe.pages["kanban-tasks"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Kanban Service Tasks"), single_column: true });
	const session_key = "cfg_kanban_operator_session";
	const state = { token: localStorage.getItem(session_key), operator: null, tasks: [] };
	const $sticky_header = $("<div class='cfg-service-sticky-shell'></div>").appendTo(page.main);
	const $scanner = $(`<div class="frappe-card cfg-service-scanner mb-3">
		<div class="cfg-service-scanner-heading"><div><strong>${__("Service Task Scanner")}</strong>
			<small class="text-muted">${__("USB scanners can scan directly into this field and append Enter.")}</small></div>
			<span class="indicator-pill orange scanner-mode">${__("Operator scan required")}</span></div>
		<div class="cfg-service-scanner-controls">
			<input type="text" class="form-control service-scan-input" autocomplete="off" autocapitalize="off"
				spellcheck="false" placeholder="${__("Scan or type Task / Card No.")}">
			<button class="btn btn-primary camera-service-task">${__("Scan Task QR with Camera")}</button>
			<button class="btn btn-default find-service-task">${__("Find Task / Card")}</button>
			<button class="btn btn-default clear-service-filter">${__("Show All")}</button>
		</div><div class="text-muted scanner-message"><small>${__("Before login, a scan identifies the operator. After login, a scan finds the Service Task card.")}</small></div>
	</div>`).appendTo($sticky_header);
	const $identity = $("<div class='mb-3'></div>").appendTo($sticky_header);
	const $active_root = $("<div class='cfg-service-active-work'></div>").appendTo(page.main);
	const $mobile_actions = $(`<div class="cfg-service-mobile-actions mb-3">
		<button class="btn btn-info open-production-panel">${__("Production Panel")}</button>
		<button class="btn btn-info open-logistics-panel">${__("Logistics Panel")}</button>
		<button class="btn btn-default refresh-tasks"><span class="octicon octicon-sync"></span> ${__("Refresh")}</button>
		<button class="btn btn-primary identify-operator">${__("Scan / Switch Operator")}</button>
		<button class="btn btn-success create-service-task">${__("Create Task")}</button>
	</div>`).appendTo(page.main);
	const $root = $("<div class='cfg-kanban-tasks cfg-service-ready-work'></div>").appendTo(page.main);
	page.set_primary_action(__("Refresh"), load, "refresh");
	page.add_inner_button(__("Open Production Operator Panel"), () => frappe.set_route("kanban-operator"));
	page.add_inner_button(__("Open Logistics Panel"), () => frappe.set_route("kanban-logistics"));
	page.add_inner_button(__("Identify Operator"), identify_operator);
	page.add_inner_button(__("Create Task"), create_task);
	$mobile_actions.find(".open-production-panel").on("click", () => frappe.set_route("kanban-operator"));
	$mobile_actions.find(".open-logistics-panel").on("click", () => frappe.set_route("kanban-logistics"));
	$mobile_actions.find(".refresh-tasks").on("click", load);
	$mobile_actions.find(".identify-operator").on("click", identify_operator);
	$mobile_actions.find(".create-service-task").on("click", create_task);
	$scanner.find(".find-service-task").on("click", process_scanner_value);
	$scanner.find(".camera-service-task").on("click", scan_service_code);
	$scanner.find(".clear-service-filter").on("click", clear_task_filter);
	$scanner.find(".service-scan-input").on("keydown", (event) => {
		if (event.key === "Enter") { event.preventDefault(); process_scanner_value(); }
	});

	async function load() {
		sync_session_from_storage();
		if (!state.token) return show_login_required();
		const requested_token = state.token;
		$active_root.html(`<div class="text-muted p-4">${__("Loading active work...")}</div>`);
		$root.html(`<div class="text-muted p-4">${__("Loading ready tasks...")}</div>`);
		try {
			const session = await frappe.call({ method: "cfg_kanban.api.operator.operator_session_status",
				args: { operator_session_token: state.token } });
			state.operator = session.message;
			render_identity();
			const response = await frappe.call({ method: "cfg_kanban.api.task.get_open_tasks",
				args: { operator_session_token: state.token } });
			state.tasks = response.message || [];
			render(state.tasks);
			update_scanner_mode();
			focus_scanner();
		} catch (error) {
			const latest_token = localStorage.getItem(session_key);
			if (latest_token && latest_token !== requested_token) return load();
			clear_session(requested_token);
			show_login_required(__("The operator session expired. Identify the operator again on this page."));
		}
	}

	function sync_session_from_storage() {
		const stored_token = localStorage.getItem(session_key);
		if (stored_token === state.token) return false;
		state.token = stored_token;
		state.operator = null;
		state.tasks = [];
		return true;
	}

	function render_identity() {
		const e = frappe.utils.escape_html;
		$identity.html(`<div class="alert alert-info cfg-service-identity">
			<div class="cfg-active-operator-details"><small>${__("Active operator")}</small><strong class="cfg-active-operator-name">${e(state.operator.employee_name || state.operator.employee)}</strong>
			<span>${e(state.operator.kanban_role || "")}</span></div>
			<div class="cfg-service-session-actions">
				<button class="btn btn-primary switch-operator">${__("Switch Operator")}</button>
				<button class="btn btn-default end-session">${__("End Session")}</button>
			</div></div>`);
		$identity.find(".switch-operator").on("click", identify_operator);
		$identity.find(".end-session").on("click", confirm_end_session);
		update_scanner_mode();
	}

	function show_login_required(message) {
		state.tasks = [];
		update_scanner_mode();
		$identity.html(`<div class="alert alert-warning cfg-service-identity"><div>
			<small>${__("Active operator")}</small><br><strong>${__("Not identified")}</strong></div></div>`);
		$active_root.empty();
		$root.html(`<div class="frappe-card text-center p-5 cfg-service-login"><h3>${__("Operator identification required")}</h3>
			<p class="text-muted">${message || __("Scan the operator QR or enter the credential before viewing tasks.")}</p>
			<div class="cfg-service-login-actions"><button class="btn btn-primary scan-operator">${__("Scan Operator QR with Camera")}</button>
			<button class="btn btn-default enter-credential">${__("Enter Credential / PIN")}</button></div></div>`);
		$root.find(".scan-operator").on("click", scan_operator_qr);
		$root.find(".enter-credential").on("click", credential_dialog);
		focus_scanner();
	}

	async function process_scanner_value() {
		const $input = $scanner.find(".service-scan-input");
		const raw = String($input.val() || "").trim();
		if (!raw) { focus_scanner(); return; }
		$input.val("");
		const operator = operator_token_from_url(raw);
		if (!state.token || operator) {
			try { await login_operator(operator || raw); }
			catch (error) { scanner_error(__("Operator identification failed. Check the credential and retry.")); }
			return;
		}
		if (/^CFG:SERVICE:SCHEDULE:/i.test(raw)) {
			try {
				const resolved = await frappe.call({ method: "cfg_kanban.api.task.resolve_service_scan", args: {
					scan_value: raw, operator_session_token: state.token,
				} });
				if (!resolved.message.task) {
					scanner_error(__(resolved.message.message));
					return;
				}
				await load();
				find_service_task(resolved.message.task.name);
				return;
			} catch (error) {
				scanner_error(__("Service Point QR could not be resolved."));
				return;
			}
		}
		const task_value = service_task_token(raw);
		const known_task = state.tasks.some((task) => [task.name, task.task_name, task.task_schedule]
			.filter(Boolean).some((candidate) => String(candidate).toLowerCase() === task_value.toLowerCase()));
		if (/^KTASK-/i.test(task_value) || known_task || task_value !== raw) {
			find_service_task(task_value);
			return;
		}
		try { await login_operator(raw); }
		catch (error) { scanner_error(__("The scan is not an open Service Task or a valid operator credential.")); }
	}

	function find_service_task(value) {
		const query = String(value || "").trim().toLowerCase();
		const exact = state.tasks.filter((task) => [task.name, task.task_name, task.task_schedule]
			.filter(Boolean).some((candidate) => String(candidate).toLowerCase() === query));
		const matches = exact.length ? exact : state.tasks.filter((task) => [task.name, task.task_name]
			.filter(Boolean).some((candidate) => String(candidate).toLowerCase().includes(query)));
		if (matches.length !== 1) {
			scanner_error(matches.length ? __("More than one Service Task matches. Scan the exact Task ID.") :
				__("No open Service Task matches {0}.", [frappe.utils.escape_html(value)]));
			return;
		}
		render(matches);
		$scanner.find(".scanner-message").html(`<small class="text-success">${__("Task found: {0}", [frappe.utils.escape_html(matches[0].name)])}</small>`);
		setTimeout(() => document.querySelector(".cfg-service-active-work .cfg-service-task-card, .cfg-service-ready-work .cfg-service-task-card")?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
		focus_scanner();
	}

	function clear_task_filter() {
		if (state.token) render(state.tasks);
		$scanner.find(".service-scan-input").val("");
		$scanner.find(".scanner-message").html(`<small>${__("Ready for the next operator or Service Task scan.")}</small>`);
		focus_scanner();
	}

	function scan_service_code() {
		if (!(frappe.ui && frappe.ui.Scanner)) {
			scanner_error(__("Camera scanning is unavailable in this browser. Use the scan field instead."));
			return;
		}
		new frappe.ui.Scanner({ dialog: true, multiple: false, on_scan(data) {
			const value = String((data && data.decodedText) || "").trim();
			$scanner.find(".service-scan-input").val(value);
			process_scanner_value();
		} });
	}

	function service_task_token(value) {
		try {
			const url = new URL(value);
			const hash = new URLSearchParams(url.hash.replace(/^#/, ""));
			const parameter = hash.get("service_task") || hash.get("task") ||
				url.searchParams.get("service_task") || url.searchParams.get("task");
			if (parameter) return parameter;
			const match = url.pathname.match(/\/cfg-kanban-task\/([^/?#]+)/i);
			return match ? decodeURIComponent(match[1]) : value;
		} catch (error) { return value; }
	}

	function operator_token_from_url(value) {
		try {
			const url = new URL(value);
			return new URLSearchParams(url.hash.replace(/^#/, "")).get("operator") ||
				url.searchParams.get("operator");
		} catch (error) { return null; }
	}

	function update_scanner_mode() {
		$scanner.find(".scanner-mode").removeClass("orange green")
			.addClass(state.token ? "green" : "orange")
			.text(state.token ? __("Task scanner ready") : __("Operator scan required"));
	}

	function scanner_error(message) {
		$scanner.find(".scanner-message").html(`<small class="text-danger">${message}</small>`);
		frappe.show_alert({ message, indicator: "red" }, 5);
		focus_scanner();
	}

	function focus_scanner() {
		if (window.matchMedia("(min-width: 768px) and (hover: hover)").matches) {
			setTimeout(() => $scanner.find(".service-scan-input").trigger("focus").select(), 50);
		}
	}

	function identify_operator() {
		if (frappe.ui && frappe.ui.Scanner) scan_operator_qr(); else credential_dialog();
	}

	function scan_operator_qr() {
		if (!(frappe.ui && frappe.ui.Scanner)) return credential_dialog();
		if (!window.isSecureContext && !["localhost", "127.0.0.1"].includes(window.location.hostname)) {
			frappe.msgprint(__("Camera scanning requires HTTPS. Enter the credential instead."));
			return;
		}
		new frappe.ui.Scanner({ dialog: true, multiple: false, on_scan(data) {
			const value = String((data && data.decodedText) || "").trim();
			login_operator(operator_token(value));
		} });
	}

	function credential_dialog() {
		const dialog = new frappe.ui.Dialog({ title: __("Identify Kanban Operator"), fields: [
			{ fieldname: "token", label: __("Operator Credential"), fieldtype: "Data", reqd: 1 },
			{ fieldname: "pin", label: __("PIN"), fieldtype: "Password" },
			{ fieldname: "station", label: __("Terminal / Station"), fieldtype: "Data",
				default: localStorage.getItem("cfg_kanban_station") || "" },
		], primary_action_label: __("Continue"), primary_action: async (values) => {
			await login_operator(values.token, values.pin, values.station); dialog.hide();
		} });
		dialog.$wrapper.addClass("cfg-service-task-dialog");
		dialog.show();
	}

	async function login_operator(token, pin, station) {
		const response = await frappe.call({ method: "cfg_kanban.api.operator.login_operator", args: {
			token, pin, station: station || localStorage.getItem("cfg_kanban_station") || "",
		}, freeze: true, freeze_message: __("Identifying operator...") });
		state.token = response.message.session_token;
		state.operator = response.message.operator;
		localStorage.setItem(session_key, state.token);
		if (station) localStorage.setItem("cfg_kanban_station", station);
		await load();
	}

	function operator_token(value) {
		try { const url = new URL(value); return new URLSearchParams(url.hash.replace(/^#/, "")).get("operator") || value; }
		catch (error) { return value; }
	}

	function clear_session(expected_token) {
		const stored_token = localStorage.getItem(session_key);
		if (!expected_token || stored_token === expected_token) localStorage.removeItem(session_key);
		state.token = null; state.operator = null; state.tasks = [];
		update_scanner_mode();
	}

	function confirm_end_session() {
		frappe.confirm(__("End this operator session?"), end_session);
	}

	async function end_session() {
		if (state.token) {
			await frappe.call({ method: "cfg_kanban.api.operator.logout_operator",
				args: { operator_session_token: state.token }, freeze: true });
		}
		clear_session();
		show_login_required(__("Operator session ended. Scan the next operator credential."));
	}

	async function create_task() {
		if (!state.token) return show_login_required();
		try {
			const response = await frappe.call({ method: "cfg_kanban.api.task.get_request_schedules",
				args: { operator_session_token: state.token } });
			const schedules = response.message || [];
			if (!schedules.length) return frappe.msgprint(__("No active Task Schedule is available. Configure one first."));
			const dialog = new frappe.ui.Dialog({ title: __("Create Service Task"), fields: [
				{ fieldname: "schedule", label: __("Task Schedule"), fieldtype: "Select", reqd: 1,
					options: schedules.map((row) => ({ value: row.name, label: `${row.task_name} · ${row.schedule_name}` })) },
				{ fieldname: "priority", label: __("Priority"), fieldtype: "Select",
					options: "Low\nNormal\nHigh\nUrgent", default: "Normal" },
				{ fieldname: "request_source", label: __("Request Reason / Source"), fieldtype: "Small Text", reqd: 1 },
			], primary_action_label: __("Create Task"), primary_action: async (values) => {
				await frappe.call({ method: "cfg_kanban.api.task.supervisor_request_task", args: {
					schedule_name: values.schedule, request_source: values.request_source,
					priority: values.priority, event_token: frappe.utils.get_random(16),
					operator_session_token: state.token,
				}, freeze: true });
				dialog.hide(); await load();
			} });
			dialog.$wrapper.addClass("cfg-service-task-dialog");
			dialog.show();
		} catch (error) {
			frappe.msgprint({ title: __("Cannot Create Task"),
				message: __("Use a Senior Operator or Supervisor profile and confirm that an active Task Schedule exists."), indicator: "orange" });
		}
	}

	function render(tasks) {
		$active_root.empty();
		$root.empty();
		const employee = state.operator && state.operator.employee;
		const active_statuses = ["In Progress", "Overdue", "Correction Required", "Pending Document Posting"];
		const active = tasks.filter((task) => task.assigned_employee === employee && task.started_on &&
			active_statuses.includes(task.status)).sort((a, b) => String(b.modified || b.started_on || "")
				.localeCompare(String(a.modified || a.started_on || "")));
		const supervisor = tasks.filter((task) => state.operator && ["Supervisor", "Development Proxy"].includes(state.operator.kanban_role) &&
			task.assigned_employee && task.assigned_employee !== employee && !active.includes(task));
		const ready = tasks.filter((task) => !active.includes(task) && !supervisor.includes(task));
		render_task_section($active_root, active, __("Active Work"),
			__("Tasks currently started by this operator."), "green", true);
		render_task_section($root, ready, __("Ready / Open Tasks"),
			__("Start a task to move it immediately into Active Work."), "blue", false);
		if (supervisor.length) render_task_section($root, supervisor, __("Supervisor Attention"),
			__("Monitor active operator work, verify submitted tasks, or control other assigned work when View All Service Tasks is enabled."), "orange", false);
		if (!tasks.length) {
			$root.append(`<div class="frappe-card text-center p-5"><h4>${__("No open service tasks")}</h4>
				<p class="text-muted">${__("A Senior Operator or Supervisor can select Create Task. Scheduled tasks appear automatically when due.")}</p></div>`);
			return;
		}
	}

	function render_task_section($container, tasks, title, help, color, active_section) {
		const block_class = active_section ? "active-work" : color === "orange" ? "supervisor-work" : "ready-work";
		const chip_label = active_section ? __("ACTIVE WORK") : color === "orange" ? __("SUPERVISOR VIEW") : __("OPEN TASK");
		const $section = $(`<section class="cfg-service-work-block ${block_class}"></section>`).appendTo($container);
		$section.append(`<div class="cfg-service-list-heading"><div><h3>${title}</h3>
			<small class="text-muted">${help}</small></div>
			<span class="indicator-pill ${color}">${tasks.length} ${active_section ? __("Active") : __("Open")}</span></div>`);
		if (!tasks.length) {
			$section.append(`<div class="frappe-card cfg-service-empty-section text-muted">
				${active_section ? __("No task is currently active for this operator.") : __("No tasks are ready in this section.")}</div>`);
			return;
		}
		tasks.forEach((task) => {
			const e = frappe.utils.escape_html;
			const $row = $(`<div class="frappe-card cfg-service-task-card ${priority_class(task.priority)} ${active_section ? "is-active" : ""}">
				<div class="cfg-service-task-head"><div><h4><span class="cfg-task-state-chip">${chip_label}</span>${e(task.task_name)}</h4><small>${e(task.task_category)} · ${e(task.trigger_type)}</small></div>
				<div class="text-right"><span class="indicator-pill ${indicator(task.status)}">${e(task.status)}</span>
				${task.can_assist && !task.can_operate ? `<span class="indicator-pill blue ml-1">${__("Supervisor assist")}</span>` : ""}
				${task.monitor_only ? `<span class="indicator-pill gray ml-1">${__("Monitor only")}</span>` : ""}<div class="cfg-priority">${e(task.priority)}</div></div></div>
				<div class="cfg-service-task-meta">
					${task.responsible_role ? `<div><small>${__("Responsible Role")}</small><strong>${e(task.responsible_role)}</strong></div>` : ""}
					${task.assigned_employee ? `<div><small>${__("Assigned Employee")}</small><strong>${e(task.assigned_employee)}</strong></div>` : ""}
					${task.workstation ? `<div><small>${__("Workstation")}</small><strong>${e(task.workstation)}</strong></div>` : ""}
					${task.asset ? `<div><small>${__("Asset")}</small><strong>${e(task.asset)}</strong></div>` : ""}
					${task.started_on ? `<div><small>${__("Started")}</small><strong>${e(task.started_on)}</strong></div>` : ""}
					<div><small>${__("Due")}</small><strong>${e(task.due_on || "-")}</strong></div>
				</div>
				${task.progress_count ? `<div class="cfg-service-progress-summary">
					<div><strong>${__("Progress reports")}: ${e(task.progress_count)}</strong>
						<small>${e(task.last_progress_by || "-")} · ${e(task.last_progress_on || "-")}</small></div>
					<span>${e(task.last_progress_summary || __("Progress recorded"))}</span></div>` : ""}
				${task.status === "Correction Required" ? `<div class="alert alert-warning cfg-correction-request">
					<strong>${__("Supervisor correction requested")}</strong><br>${e(task.verification_notes || __("No correction remarks were supplied."))}
					<small>${e(task.verified_by || "-")} · ${e(task.verified_on || "-")}</small></div>` : ""}
				${task.status === "Pending Document Posting" ? `<div class="alert alert-warning cfg-correction-request">
					<strong>${__("Required document is pending")}</strong><br>
					${__("This task will not be shown as completed until its controlled DocType Action reaches the configured Draft or Submitted result.")}
					${task.doctype_action_run ? `<small>${__("Action Run")}: ${e(task.doctype_action_run)} · ${e(task.doctype_action_state || __("Form pending"))}</small>` : ""}</div>` : ""}
				<div class="actions cfg-service-task-actions"></div></div>`).appendTo($section);
			const $actions = $row.find(".actions");
			const can_execute = task.can_operate || task.can_assist;
			if (task.progress_count) button($actions, __("View Progress"), "btn-default", () => progress_history_dialog(task));
			if (task.doctype_action_run && can_open_action(task, can_execute)) button(
				$actions,
				task.status === "Pending Document Posting" ? __("Complete Required Document") : __("Open Document Form"),
				task.status === "Pending Document Posting" ? "btn-warning" : "btn-default",
				() => open_action_form(task.doctype_action_run, task),
			);
			if (task.can_operate && ["Planned", "Due", "Assigned", "Overdue"].includes(task.status)) button($actions, __("Start"), "btn-primary", () => task_dialog(task, "Start"));
			if (can_execute && task.started_on && ["In Progress", "Overdue", "Correction Required"].includes(task.status)) button($actions, __("Report Progress"), "btn-info", () => task_dialog(task, "Progress"));
			const start_action_ready = task.doctype_action_trigger !== "On Task Start" || task.doctype_action_run;
			if (can_execute && start_action_ready && ["Due", "Assigned", "In Progress", "Overdue", "Correction Required"].includes(task.status)) button($actions, task.status === "Correction Required" ? __("Correct and Resubmit") : __("Complete"), "btn-success", () => task_dialog(task, "Complete"));
			if (task.can_operate && task.status === "Awaiting Verification") button($actions, __("Verify"), "btn-warning", () => task_dialog(task, "Verify"));
			if (task.can_operate && state.operator && state.operator.permissions.task_verify && !["Completed", "Cancelled", "Bypassed"].includes(task.status)) {
				button($actions, __("Cancel / Bypass"), "btn-default", () => disposition_dialog(task));
			}
		});
	}

	async function progress_history_dialog(task) {
		const response = await frappe.call({ method: "cfg_kanban.api.task.get_task_progress", args: {
			task_name: task.name, operator_session_token: state.token,
		} });
		const data = response.message || {}; const e = frappe.utils.escape_html;
		const values = data.values || []; const events = data.events || [];
		const value_rows = values.map((row) => `<tr><td>${e(row.captured_on || "-")}</td>
			<td>${e(row.captured_by || "-")}</td><td>${e(row.label || row.field_key)}</td>
			<td><strong>${e(row.value)}</strong> ${e(row.unit || "")}</td></tr>`).join("");
		const event_rows = events.filter((row) => row.notes).map((row) => `<li><strong>${e(row.event_datetime || "-")}</strong>
			· ${e(row.operator || "-")} — ${e(row.notes)}</li>`).join("");
		const dialog = new frappe.ui.Dialog({ title: __("Task Progress History"), size: "large", fields: [
			{ fieldtype: "HTML", options: `<div class="cfg-progress-history">
				<div class="alert alert-info"><strong>${e(task.task_name)}</strong><br>
					${__("Reports")}: ${e(data.progress_count || 0)} · ${__("Latest")}: ${e(data.last_progress_on || "-")} · ${e(data.last_progress_by || "-")}<br>
					${e(data.last_progress_summary || __("No progress summary"))}</div>
				<h5>${__("Recorded measurements")}</h5>
				${value_rows ? `<div class="table-responsive"><table class="table table-bordered"><thead><tr><th>${__("Time")}</th><th>${__("Operator")}</th><th>${__("Field")}</th><th>${__("Value")}</th></tr></thead><tbody>${value_rows}</tbody></table></div>` : `<p class="text-muted">${__("No dynamic Progress measurements were configured.")}</p>`}
				${event_rows ? `<h5>${__("Progress notes")}</h5><ul>${event_rows}</ul>` : ""}</div>` },
		] });
		dialog.show();
	}

	function disposition_dialog(task) {
		frappe.prompt([
			{ fieldname: "disposition", label: __("Disposition"), fieldtype: "Select", options: "Cancelled\nBypassed", reqd: 1,
				description: __("Cancel when the occurrence should not exist, such as a holiday. Bypass only for an approved operational exception.") },
			{ fieldname: "reason", label: __("Supervisor Reason"), fieldtype: "Small Text", reqd: 1 },
		], async (values) => {
			await frappe.call({ method: "cfg_kanban.api.task.supervisor_disposition", args: {
				task_name: task.name, disposition: values.disposition, reason: values.reason,
				operator_session_token: state.token,
			}, freeze: true });
			await load();
		}, __("Cancel or Bypass Task Occurrence"), __("Apply Disposition"));
	}

	async function task_dialog(task, action) {
		const response = await frappe.call({ method: "cfg_kanban.api.task.get_task_form", args: {
			task_name: task.name, capture_on: action, operator_session_token: state.token } });
		const details = response.message.task;
		const definitions = response.message.fields || [];
		const checklist = (details.checklist || "").split("\n").map((row) => row.trim()).filter(Boolean);
		const existing_checklist = details.checklist_evidence || [];
		const existing_values = details.execution_values || [];
		const existing_media = response.message.media || [];
		const fields = [
			{ fieldtype: "Section Break", label: __("Task Information") },
			{ fieldtype: "HTML", options: task_identity(details) },
			...(details.status === "Correction Required" ? [
				{ fieldtype: "Section Break", label: __("Supervisor Correction Request") },
				{ fieldtype: "HTML", options: `<div class="alert alert-warning"><strong>${__("Correct the evidence below and resubmit.")}</strong><p>${frappe.utils.escape_html(details.verification_notes || __("No correction remarks were supplied."))}</p><small>${frappe.utils.escape_html(details.verified_by || "-")} · ${frappe.utils.escape_html(details.verified_on || "-")}</small></div>` },
			] : []),
			{ fieldtype: "Section Break", label: __("Work Instructions") },
			{ fieldtype: "HTML", options: `<div class="frappe-card p-3">${safe_rich_text(details.instructions || __("No work instructions were provided."))}</div>` },
			...(action === "Verify" ? verification_evidence(details, existing_checklist, existing_values) : []),
			{ fieldtype: "Section Break", label: __("Photo, Video and Document Evidence") },
			{ fieldname: "media_evidence", fieldtype: "HTML",
				options: media_evidence_html(existing_media, action !== "Verify", details.status === "In Progress") },
			...(action === "Complete" && checklist.length ? [{ fieldtype: "Section Break", label: __("Completion Checklist") }] : []),
			...checklist.map((item, index) => ({ fieldname: `check_${index}`, label: item, fieldtype: "Check",
				reqd: action === "Complete", hidden: action !== "Complete",
				default: existing_checklist.some((row) => row.item === item && row.result === "Pass") ? 1 : 0 })),
			...(definitions.length ? [{ fieldtype: "Section Break", label: action === "Verify" ? __("Verification Measurements") : action === "Start" ? __("Start Checks") : __("Measurements and Evidence") }] : []),
			...definitions.map((definition) => dialog_field(definition, existing_values, action)),
			{ fieldtype: "Section Break", label: action === "Verify" ? __("Verification Decision") : __("Notes") },
			{ fieldname: "notes", label: __("Notes"), fieldtype: "Small Text",
				default: action === "Complete" && details.status === "Correction Required" ? details.completion_notes : "" },
		];
		const method = { Start: "start", Progress: "progress", Complete: "complete", Verify: "verify" }[action];
		const dialog = new frappe.ui.Dialog({ title: __(`${action} Service Task`), fields,
			primary_action_label: __(action), primary_action: async (values) => {
				const args = { task_name: task.name, operator_session_token: state.token,
					values: visible_dynamic_definitions(definitions, values).map((definition) => ({ field_key: definition.field_key,
						value: values[`dynamic_${definition.field_key}`] })), notes: values.notes };
				if (action === "Complete") args.checklist_results = checklist.map((item, index) => ({ item, completed: values[`check_${index}`] ? 1 : 0 }));
				const result = await frappe.call({ method: `cfg_kanban.api.task.${method}`, args, freeze: true });
				const updated_task = result.message || {};
				dialog.hide();
				if (updated_task.doctype_action_run && should_open_action_after_event(updated_task, action)) {
					await open_action_form(updated_task.doctype_action_run, updated_task);
					return;
				}
				await load();
				if (action === "Start") scroll_to_active_work();
			} });
		if (action === "Verify") {
			dialog.set_secondary_action_label(__("Reject for Correction"));
			dialog.set_secondary_action(async () => {
				const values = dialog.get_values();
				if (!values || !(values.notes || "").trim()) {
					frappe.msgprint(__("Verification remarks are required when rejecting a task.")); return;
				}
				await frappe.call({ method: "cfg_kanban.api.task.reject", args: {
					task_name: task.name, operator_session_token: state.token, notes: values.notes,
				}, freeze: true });
				dialog.hide(); await load();
			});
		}
		dialog.$wrapper.addClass("cfg-service-task-dialog");
		dialog.show();
		configure_dynamic_visibility(dialog, definitions);
		bind_media_evidence(dialog, task, action, existing_media);
	}

	function can_open_action(task, can_execute) {
		const permissions = (state.operator && state.operator.permissions) || {};
		if (task.can_recover_action) return true;
		if (task.can_resume_action) return true;
		if (task.doctype_action_trigger === "After Supervisor Verification") {
			return Boolean(task.can_operate && permissions.task_verify);
		}
		if (task.doctype_action_trigger === "On Task Start") {
			return Boolean(can_execute && permissions.task_start);
		}
		return Boolean(can_execute && permissions.task_complete);
	}

	function should_open_action_after_event(task, action) {
		if (task.status === "Pending Document Posting") return true;
		return (action === "Start" && task.doctype_action_trigger === "On Task Start") ||
			(action === "Complete" && task.doctype_action_trigger === "On Task Complete") ||
			(action === "Verify" && task.doctype_action_trigger === "After Supervisor Verification");
	}

	async function open_action_form(run_name, task) {
		const response = await frappe.call({
			method: "cfg_kanban.api.doctype_action_run.get_operator_form",
			args: { run_name, operator_session_token: state.token },
			freeze: true,
			freeze_message: __("Loading required document form..."),
		});
		const form = response.message || {};
		const run = form.run || {};
		const blocked_states = ["Posting", "Submitted", "Skipped by Condition", "Needs Reconciliation", "Cancelled"];
		const can_post = !blocked_states.includes(run.state) &&
			!(run.state === "Draft Created" && form.posting_policy === "Save Draft");
		const parent_fields = form.parent_fields || [];
		const parent_names = new Map();
		const fields = [
			{ fieldname: "action_summary", fieldtype: "HTML", options: action_summary_html(form, task) },
		];
		if (parent_fields.length) fields.push({ fieldtype: "Section Break", label: __("Document Details") });
		parent_fields.forEach((field, index) => {
			const dialog_name = `action_parent_${index}`;
			parent_names.set(field.fieldname, dialog_name);
			fields.push(action_parent_dialog_field(field, dialog_name));
		});
		(form.child_tables || []).forEach((table, index) => {
			fields.push({ fieldtype: "Section Break", label: table.label });
			fields.push({ fieldname: `action_child_${index}`, fieldtype: "HTML",
				options: action_child_shell_html(table) });
		});
		if ((form.evidence || []).length) {
			fields.push({ fieldtype: "Section Break", label: __("Linked Private Evidence") });
			fields.push({ fieldname: "action_evidence", fieldtype: "HTML",
				options: action_evidence_html(form.evidence) });
		}
		fields.push({ fieldname: "action_result", fieldtype: "HTML",
			options: action_result_html(form) });

		const options = { title: form.form_title || __("Required Document"), size: "extra-large", fields };
		let dialog;
		if (can_post) {
			options.primary_action_label = form.posting_policy === "Submit When Authorized" ?
				__("Submit Document") : __("Save Document");
			options.primary_action = async () => post_action_form(dialog, form, parent_fields, parent_names);
		}
		dialog = new frappe.ui.Dialog(options);
		dialog.__cfg_action_child_managers = [];
		dialog.__cfg_action_retry_token = null;
		dialog.$wrapper.addClass("cfg-service-task-dialog cfg-action-operator-dialog");
		dialog.show();
		(form.child_tables || []).forEach((table, index) => {
			dialog.__cfg_action_child_managers.push(mount_action_child_table(
				dialog, table, index, form, () => action_parent_values(dialog, parent_fields, parent_names)
			));
		});
		configure_action_visibility(dialog, form, parent_fields, parent_names);
		bind_action_target_link(dialog, form.target_link);
		bind_action_evidence(dialog, form, task);
		bind_action_recovery(dialog, form, task);
	}

	function action_summary_html(form, task) {
		const e = frappe.utils.escape_html;
		const run = form.run || {};
		const instructions = e(form.form_instructions || __("Complete the mapped document details below."));
		return `<div class="cfg-action-summary">
			<div><small>${__("Service Task")}</small><strong>${e((form.task && form.task.task_name) || task.task_name || "-")}</strong></div>
			<div><small>${__("Action Run")}</small><strong>${e(run.name || "-")}</strong></div>
			<div><small>${__("Destination")}</small><strong>${e(run.target_doctype || "-")}</strong></div>
			<div><small>${__("Posting")}</small><strong>${e(form.posting_policy || "-")}</strong></div>
		</div><div class="alert alert-info cfg-action-instructions">${instructions}</div>`;
	}

	function action_result_html(form) {
		const e = frappe.utils.escape_html;
		const run = form.run || {};
		let indicator = "blue";
		let message = __("Review the form, then use the button below to create the controlled document.");
		if (["Draft Created", "Submitted", "Skipped by Condition"].includes(run.state)) {
			indicator = "green";
			message = run.state === "Skipped by Condition" ?
				__("The configured condition was not met, so no destination document was required.") :
				__("The controlled destination result has already been recorded.");
		} else if (["Needs Reconciliation", "Cancelled"].includes(run.state)) {
			indicator = "red";
			message = run.state === "Needs Reconciliation" ?
				__("Supervisor reconciliation is required before this Action Run can continue.") :
				__("This Action Run was cancelled and cannot be posted.");
		} else if (run.state === "Posting") {
			indicator = "orange";
			message = __("A previous posting attempt has an uncertain result. Refresh or ask a supervisor to reconcile it; do not create another document.");
		} else if (run.state === "Failed") {
			indicator = "orange";
			message = form.last_error || __("The previous controlled attempt failed. Correct the highlighted data and retry.");
		}
		const target = form.target_link ? `<div class="cfg-action-target mt-2">
			<strong>${e(form.target_link.doctype)}: ${e(form.target_link.name)}</strong>
			<button type="button" class="btn btn-default btn-sm cfg-open-action-target">${__("Open ERP Document")}</button></div>` : "";
		const recovery = form.recovery || {};
		const recovery_buttons = (recovery.recovery_options || []).map((option) =>
			`<button type="button" class="btn btn-warning btn-sm cfg-recover-action" data-resolution="${e(option)}">${e(option)}</button>`
		).join("");
		const attempt_rows = (recovery.attempts || []).slice(0, 8).map((attempt) => `<tr>
			<td>${e(attempt.occurred_at || "-")}</td><td>${e(attempt.attempt_type || "-")}</td>
			<td>${e(attempt.outcome || "-")}</td><td>${e(attempt.result_state || "-")}</td>
			<td>${e(attempt.error_message || "")}</td></tr>`).join("");
		const history = attempt_rows ? `<details class="cfg-action-attempts mt-3"><summary>${__("Action attempt history")}</summary>
			<div class="table-responsive"><table class="table table-bordered table-sm"><thead><tr>
			<th>${__("Time")}</th><th>${__("Attempt")}</th><th>${__("Outcome")}</th><th>${__("State")}</th><th>${__("Message")}</th>
			</tr></thead><tbody>${attempt_rows}</tbody></table></div></details>` : "";
		return `<div class="alert alert-${indicator === "green" ? "success" : indicator === "red" ? "danger" : indicator === "orange" ? "warning" : "info"} cfg-action-result">
			<strong>${__("Action status")}: ${e(run.state || "-")}</strong><br>${e(message)}${target}
			${recovery_buttons ? `<div class="cfg-action-recovery-buttons mt-3">${recovery_buttons}</div>` : ""}${history}</div>`;
	}

	function action_evidence_html(rows) {
		const e = frappe.utils.escape_html;
		return `<div class="cfg-action-evidence-grid">${rows.map((row) => `<article class="cfg-action-evidence-item">
			<div><strong>${e(row.original_filename || row.media_id)}</strong>
			<small>${e(row.content_type || "")} · ${e(row.capture_timestamp || row.confirmed_at || "")}</small>
			<small>${e(row.operator_employee || "")}</small></div>
			<button type="button" class="btn btn-default btn-sm cfg-open-action-evidence" data-media-id="${e(row.media_id)}">${__("Open Evidence")}</button>
		</article>`).join("")}</div>
		<small class="text-muted">${__("These are stable CFG Kanban Media references. Temporary view links are generated only when Open Evidence is selected.")}</small>`;
	}

	function bind_action_evidence(dialog, form, task) {
		if (!dialog.fields_dict.action_evidence) return;
		dialog.get_field("action_evidence").$wrapper.on("click", ".cfg-open-action-evidence", async function () {
			const response = await frappe.call({ method: "cfg_kanban.api.media.create_task_view_url", args: {
				task_name: (form.task && form.task.name) || task.name,
				media_id: $(this).data("media-id"), operator_session_token: state.token,
			} });
			if (response.message && response.message.url) window.open(response.message.url, "_blank", "noopener");
		});
	}

	function bind_action_recovery(dialog, form, task) {
		dialog.get_field("action_result").$wrapper.on("click", ".cfg-recover-action", function () {
			const resolution = $(this).data("resolution");
			frappe.prompt([
				{ fieldname: "reason", label: __("Supervisor Recovery Notes"), fieldtype: "Small Text", reqd: 1 },
			], async (values) => {
				const response = await frappe.call({
					method: "cfg_kanban.api.doctype_action_run.recover", type: "POST",
					args: {
						run_name: form.run.name, resolution, reason: values.reason,
						operator_session_token: state.token, retry_token: frappe.utils.get_random(32),
					}, freeze: true, freeze_message: __("Reconciling the existing document action..."),
				});
				dialog.hide();
				frappe.show_alert({ message: response.message.message || __("Action recovery recorded"),
					indicator: response.message.ok ? "green" : "orange" }, 7);
				await load();
				if (response.message.state === "Form In Progress" || response.message.state === "Draft Created") {
					await open_action_form(form.run.name, task);
				}
			}, __("Recover Existing Action Run"), __("Apply Recovery"));
		});
	}

	function action_parent_dialog_field(field, dialog_name) {
		return {
			fieldname: dialog_name,
			label: field.label,
			fieldtype: action_control_type(field.fieldtype),
			options: field.options,
			default: field.default,
			read_only: field.read_only ? 1 : 0,
			reqd: field.visible !== false && field.required && !field.read_only ? 1 : 0,
			hidden: field.visible === false ? 1 : 0,
			description: field.read_only ? __("Filled from approved task or server context.") : "",
		};
	}

	function action_control_type(fieldtype) {
		if (["Small Text", "Text", "Long Text"].includes(fieldtype)) return "Small Text";
		return fieldtype;
	}

	function action_child_shell_html(table) {
		const e = frappe.utils.escape_html;
		return `<div class="cfg-action-child-table" data-table="${e(table.fieldname)}">
			<div class="cfg-action-child-help"><span>${__("Required rows")}: ${Number(table.min_rows || 0)}–${Number(table.max_rows || 0)}</span>
				<span>${e(table.rows_mode || "")}</span></div>
			<div class="cfg-action-child-rows"></div>
			<div class="cfg-action-child-footer"></div>
		</div>`;
	}

	function configure_action_visibility(dialog, form, fields, names) {
		const refresh = () => {
			const values = { ...(form.condition_context || {}), ...action_parent_values(dialog, fields, names) };
			fields.forEach((field) => {
				const name = names.get(field.fieldname);
				const visible = action_condition_matches(field.visible_condition, values);
				dialog.set_df_property(name, "hidden", !visible);
				dialog.set_df_property(name, "reqd", visible && field.required && !field.read_only);
			});
			(dialog.__cfg_action_child_managers || []).forEach((manager) => manager.refresh_visibility(values));
		};
		dialog.$wrapper.off(".cfg_action_visibility").on(
			"change.cfg_action_visibility input.cfg_action_visibility",
			"[data-fieldname^='action_parent_'] :input",
			refresh,
		);
		refresh();
	}

	function action_parent_values(dialog, fields, names, operator_only = false) {
		const values = {};
		fields.forEach((field) => {
			if (operator_only && field.read_only) return;
			values[field.fieldname] = dialog.get_value(names.get(field.fieldname));
		});
		return values;
	}

	function mount_action_child_table(dialog, table, index, form, parent_values) {
		const $wrapper = dialog.get_field(`action_child_${index}`).$wrapper.find(".cfg-action-child-table");
		const minimum = Number(table.min_rows || 0);
		const maximum = Number(table.max_rows || 0);
		let rows = (table.rows || []).map((row) => ({ ...row }));
		while (rows.length < minimum) rows.push({});
		let views = [];

		const render = () => {
			const $rows = $wrapper.find(".cfg-action-child-rows").empty();
			views = rows.map((row, row_index) => {
				const $card = $(`<div class="cfg-action-child-row"><div class="cfg-action-child-row-head">
					<strong>${__("Row {0}", [row_index + 1])}</strong>
					<button type="button" class="btn btn-danger btn-sm cfg-remove-action-row">${__("Remove")}</button>
				</div><div class="cfg-action-child-controls"></div></div>`).appendTo($rows);
				const controls = {};
				(table.columns || []).forEach((column, column_index) => {
					const $host = $("<div class='cfg-action-child-control'></div>").appendTo($card.find(".cfg-action-child-controls"));
					const control = frappe.ui.form.make_control({ parent: $host, render_input: true, df: {
						fieldname: `action_child_${index}_${row_index}_${column_index}`,
						label: column.label,
						fieldtype: action_control_type(column.fieldtype),
						options: column.options,
						read_only: column.read_only ? 1 : 0,
						reqd: column.required && !column.read_only ? 1 : 0,
					} });
					control.set_value(Object.prototype.hasOwnProperty.call(row, column.fieldname) ? row[column.fieldname] : column.default);
					controls[column.fieldname] = { column, control, $host, visible: true };
					$host.on("change input", ":input", () => {
						row[column.fieldname] = control.get_value();
						refresh_visibility();
					});
				});
				$card.find(".cfg-remove-action-row").toggle(Boolean(table.allow_add_delete_rows && rows.length > minimum))
					.on("click", () => { rows.splice(row_index, 1); render(); });
				return { row, controls };
			});
			const can_add = Boolean(table.allow_add_delete_rows && rows.length < maximum);
			$wrapper.find(".cfg-action-child-footer").html(can_add ?
				`<button type="button" class="btn btn-default btn-block cfg-add-action-row">${__("Add Row")}</button>` : "");
			$wrapper.find(".cfg-add-action-row").on("click", () => { rows.push({}); render(); });
			refresh_visibility();
		};

		const refresh_visibility = (parent_context) => {
			views.forEach((view) => {
				const row_values = {};
				Object.entries(view.controls).forEach(([fieldname, entry]) => {
					row_values[fieldname] = entry.control.get_value();
				});
				const context = { ...(form.condition_context || {}), ...(parent_context || parent_values()), ...row_values };
				Object.values(view.controls).forEach((entry) => {
					entry.visible = action_condition_matches(entry.column.visible_condition, context);
					entry.$host.toggle(entry.visible);
					entry.control.df.reqd = Boolean(entry.visible && entry.column.required && !entry.column.read_only);
					if (entry.control.refresh_label) entry.control.refresh_label();
				});
			});
		};

		const collect = () => {
			if (rows.length < minimum || rows.length > maximum) {
				throw new Error(__("{0} requires between {1} and {2} rows.", [table.label, minimum, maximum]));
			}
			return views.map((view, row_index) => {
				const output = {};
				Object.entries(view.controls).forEach(([fieldname, entry]) => {
					if (!entry.visible || entry.column.read_only) return;
					const value = entry.control.get_value();
					if (entry.column.required && (value === null || value === undefined || value === "")) {
						throw new Error(__("{0} is required in {1}, row {2}.", [entry.column.label, table.label, row_index + 1]));
					}
					output[fieldname] = value;
				});
				return output;
			});
		};

		render();
		return { collect, refresh_visibility };
	}

	async function post_action_form(dialog, form, parent_fields, parent_names) {
		try {
			const operator_values = {};
			const context = { ...(form.condition_context || {}), ...action_parent_values(dialog, parent_fields, parent_names) };
			parent_fields.forEach((field) => {
				if (field.read_only || !action_condition_matches(field.visible_condition, context)) return;
				operator_values[field.fieldname] = dialog.get_value(parent_names.get(field.fieldname));
			});
			const child_rows = {};
			(form.child_tables || []).forEach((table, index) => {
				child_rows[table.fieldname] = dialog.__cfg_action_child_managers[index].collect();
			});
			dialog.__cfg_action_retry_token = dialog.__cfg_action_retry_token || frappe.utils.get_random(32);
			const response = await frappe.call({
				method: "cfg_kanban.api.doctype_action_run.post",
				type: "POST",
				args: {
					run_name: form.run.name,
					operator_session_token: state.token,
					retry_token: dialog.__cfg_action_retry_token,
					operator_values,
					child_rows,
				},
				freeze: true,
				freeze_message: form.posting_policy === "Submit When Authorized" ? __("Submitting controlled document...") : __("Saving controlled document..."),
			});
			const result = response.message || {};
			if (!result.ok) {
				dialog.__cfg_action_retry_token = null;
				update_action_result(dialog, result.message || __("The document could not be posted."), "red", result.state);
				if (result.state === "Needs Reconciliation") dialog.get_primary_btn().prop("disabled", true).hide();
				return;
			}
			dialog.__cfg_action_retry_token = null;
			dialog.hide();
			frappe.show_alert({ message: result.message || __("Controlled document recorded"), indicator: "green" }, 7);
			await load();
		} catch (error) {
			if (error && error.message) {
				update_action_result(dialog, error.message, "red", __("Check required values"));
				return;
			}
			throw error;
		}
	}

	function update_action_result(dialog, message, color, state_label) {
		const e = frappe.utils.escape_html;
		const css = color === "red" ? "danger" : color === "green" ? "success" : "warning";
		dialog.get_field("action_result").$wrapper.html(`<div class="alert alert-${css} cfg-action-result">
			<strong>${e(state_label || __("Document action"))}</strong><br>${e(message)}</div>`);
	}

	function bind_action_target_link(dialog, target) {
		if (!target) return;
		dialog.get_field("action_result").$wrapper.find(".cfg-open-action-target").on("click", () => {
			frappe.set_route("Form", target.doctype, target.name);
			dialog.hide();
		});
	}

	function action_condition_matches(condition, values) {
		if (!condition) return true;
		if (typeof condition === "string") {
			try { condition = JSON.parse(condition); }
			catch (error) { return false; }
		}
		if (condition.all) return condition.all.every((row) => action_condition_matches(row, values));
		if (condition.any) return condition.any.some((row) => action_condition_matches(row, values));
		const actual = values[condition.field];
		const expected = condition.value;
		const equal = action_values_equal(actual, expected);
		if (condition.operator === "equals") return equal;
		if (condition.operator === "not_equals") return !equal;
		const candidates = Array.isArray(expected) ? expected : [expected];
		if (condition.operator === "in") return candidates.some((value) => action_values_equal(actual, value));
		if (condition.operator === "not_in") return !candidates.some((value) => action_values_equal(actual, value));
		if (condition.operator === "greater_than") return Number(actual) > Number(expected);
		if (condition.operator === "less_than") return Number(actual) < Number(expected);
		return false;
	}

	function action_values_equal(actual, expected) {
		if (typeof expected === "boolean") return condition_truthy(actual) === expected;
		if (typeof expected === "number") return Number(actual) === expected;
		if (expected === null) return actual === null || actual === undefined || actual === "";
		return String(actual ?? "") === String(expected);
	}

	function media_evidence_html(rows, can_upload, can_camera) {
		return `<div class="cfg-task-media-evidence">
			${can_upload ? `<div class="cfg-media-actions">
				${can_camera ? `<label class="btn btn-primary btn-lg cfg-camera-picker">${__("Take Timestamped Photo")}
					<input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" hidden></label>` : ""}
				<label class="btn btn-default btn-lg cfg-file-picker">${__("Upload Photo / PDF / File")}
					<input type="file" accept="image/jpeg,image/png,image/webp,video/mp4,application/pdf" multiple hidden></label>
			</div><div class="text-muted mt-2"><small>${can_camera ? __("Camera photos receive visible server time and GPS. Uploaded files remain unchanged.") : __("Start the task to enable timestamped camera capture. Existing files can still be uploaded.")}</small></div>` : ""}
			<div class="cfg-media-upload-status mt-2"></div>
			<div class="cfg-media-list mt-3">${media_rows_html(rows)}</div>
		</div>`;
	}

	function media_rows_html(rows) {
		const e = frappe.utils.escape_html;
		if (!rows.length) return `<div class="text-muted">${__("No media evidence attached yet.")}</div>`;
		return rows.map((row) => `<div class="cfg-media-row" data-media-id="${e(row.media_id)}">
			<span><strong>${e(row.original_filename)}</strong><small>${e(row.content_type)} · ${format_bytes(row.size_bytes)}</small></span>
			<span><span class="indicator-pill green">${e(row.status)}</span>
			<button type="button" class="btn btn-default btn-sm cfg-open-media">${__("Open")}</button>
			<button type="button" class="btn btn-danger btn-sm cfg-remove-media">${__("Remove")}</button></span>
		</div>`).join("");
	}

	function bind_media_evidence(dialog, task, action, initial_rows) {
		const $field = dialog.get_field("media_evidence").$wrapper;
		let rows = initial_rows || [];
		const refresh_rows = () => {
			$field.find(".cfg-media-list").html(media_rows_html(rows));
			$field.find(".cfg-open-media").off("click").on("click", async function () {
				const response = await frappe.call({ method: "cfg_kanban.api.media.create_task_view_url", args: {
					task_name: task.name, media_id: $(this).closest(".cfg-media-row").data("media-id"),
					operator_session_token: state.token,
				} });
				window.open(response.message.url, "_blank", "noopener");
			});
			$field.find(".cfg-remove-media").off("click").on("click", function () {
				const media_id = $(this).closest(".cfg-media-row").data("media-id");
				frappe.confirm(__("Remove this accidental attachment? The audit record will be retained."), async () => {
					await frappe.call({ method: "cfg_kanban.api.media.archive_task_media", args: {
						task_name: task.name, media_id, operator_session_token: state.token,
					}, freeze: true });
					rows = rows.filter((row) => row.media_id !== media_id);
					refresh_rows();
				});
			});
		};
		refresh_rows();
		if (action === "Verify") return;
		const handle_upload = async (input, camera_capture) => {
			let files = Array.from(input.files || []);
			if (!files.length) return;
			const $status = $field.find(".cfg-media-upload-status");
			const $pickers = $field.find(".cfg-camera-picker,.cfg-file-picker").addClass("disabled");
			try {
				let capture_timestamp = null;
				let geotag = null;
				if (camera_capture) {
					geotag = await get_execution_geotag();
					const stamp = await frappe.call({ method: "cfg_kanban.api.media.get_task_camera_stamp", args: {
						task_name: task.name, operator_session_token: state.token,
					} });
					capture_timestamp = stamp.message.captured_at;
					files = [await stamp_execution_photo(files[0], capture_timestamp, task.name, geotag)];
				}
				for (let index = 0; index < files.length; index += 1) {
					const file = files[index];
					$status.html(`<div class="alert alert-info">${__("Uploading {0} of {1}: {2}", [index + 1, files.length, frappe.utils.escape_html(file.name)])}</div>`);
					const authorization = await frappe.call({ method: "cfg_kanban.api.media.create_task_upload_url", args: {
						task_name: task.name, original_filename: file.name, content_type: file.type,
						size_bytes: file.size, idempotency_key: frappe.utils.get_random(32),
						operator_session_token: state.token,
						capture_source: camera_capture ? "timestamped-camera" : "file-upload",
						capture_timestamp,
						latitude: geotag && geotag.latitude,
						longitude: geotag && geotag.longitude,
						location_accuracy: geotag && geotag.accuracy,
					} });
					if (authorization.message.already_available) continue;
					const upload = authorization.message;
					const form = new FormData();
					Object.entries(upload.fields || {}).forEach(([key, value]) => form.append(key, value));
					form.append("file", file);
					const result = await fetch(upload.url, { method: upload.method, body: form });
					if (!result.ok) throw new Error(__("Private media upload failed with HTTP {0}", [result.status]));
					await frappe.call({ method: "cfg_kanban.api.media.confirm_task_upload", args: {
						task_name: task.name, media_id: upload.media_id,
						confirmation_token: upload.confirmation_token,
						operator_session_token: state.token,
					} });
				}
				const response = await frappe.call({ method: "cfg_kanban.api.media.list_task_media", args: {
					task_name: task.name, operator_session_token: state.token,
				} });
				rows = response.message || [];
				refresh_rows();
				$status.html(`<div class="alert alert-success">${__("Media evidence uploaded and verified")}</div>`);
			} catch (error) {
				const detail = frappe.utils.escape_html(error.message || __("Unknown upload error"));
				$status.html(`<div class="alert alert-danger"><strong>${__("Media upload was not completed.")}</strong><br>${detail}</div>`);
				console.error("CFG Kanban media upload failed", error);
			} finally {
				$pickers.removeClass("disabled");
				input.value = "";
			}
		};
		$field.find(".cfg-camera-picker input").on("change", function () { handle_upload(this, true); });
		$field.find(".cfg-file-picker input").on("change", function () { handle_upload(this, false); });
	}

	function get_execution_geotag() {
		if (!navigator.geolocation) return Promise.reject(new Error(__("This device does not provide geolocation.")));
		return new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(
			(position) => resolve({ latitude: position.coords.latitude, longitude: position.coords.longitude,
				accuracy: position.coords.accuracy }),
			() => reject(new Error(__("Location permission is required for timestamped task photos. Use Upload File for existing evidence."))),
			{ enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
		));
	}

	async function stamp_execution_photo(file, captured_at, task_name, geotag) {
		const bitmap = await load_media_bitmap(file);
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

	async function load_media_bitmap(file) {
		if (window.createImageBitmap) return createImageBitmap(file);
		return new Promise((resolve, reject) => {
			const image = new Image();
			const url = URL.createObjectURL(file);
			image.onload = () => { URL.revokeObjectURL(url); resolve(image); };
			image.onerror = () => { URL.revokeObjectURL(url); reject(new Error(__("The selected image could not be read."))); };
			image.src = url;
		});
	}

	function format_bytes(value) {
		const bytes = Number(value || 0);
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	function task_identity(details) {
		const e = frappe.utils.escape_html;
		const rows = [
			[__("Task"), `${e(details.name)} · ${e(details.task_name)}`],
			[__("Category"), e(details.task_category || "-")],
			[__("Location / Workstation"), e(details.location || details.workstation || "-")],
			[__("Asset"), e(details.asset || "-")],
		];
		return `<div class="row">${rows.map(([label, value]) => `<div class="col-sm-6 mb-2"><small class="text-muted">${label}</small><br><strong>${value}</strong></div>`).join("")}</div>`;
	}

	function verification_evidence(details, checklist, values) {
		const e = frappe.utils.escape_html;
		const checklist_html = checklist.length ? checklist.map((row) =>
			`<li><strong>${e(row.result || "-")}</strong> — ${e(row.item || "")}${row.remarks ? `<br><small>${e(row.remarks)}</small>` : ""}</li>`).join("") : `<li>${__("No checklist evidence")}</li>`;
		const values_html = values.length ? values.map((row) =>
			`<li>${e(row.label || row.field_key)}: <strong>${e(row.value || "-")} ${e(row.unit || "")}</strong> <small>(${e(row.capture_on || "-")})</small></li>`).join("") : `<li>${__("No measurement evidence")}</li>`;
		return [
			{ fieldtype: "Section Break", label: __("Submitted Completion Evidence") },
			{ fieldtype: "HTML", options: `<div class="frappe-card p-3"><strong>${__("Checklist Results")}</strong><ul class="mt-2">${checklist_html}</ul><strong>${__("Measurements")}</strong><ul class="mt-2">${values_html}</ul><strong>${__("Completion Notes")}</strong><p>${e(details.completion_notes || "-")}</p><small>${__("Completed by")}: ${e(details.completed_by || "-")} · ${e(details.completed_on || "-")}</small></div>` },
		];
	}

	function safe_rich_text(html) {
		const template = document.createElement("template");
		template.innerHTML = String(html || "");
		template.content.querySelectorAll("script, style, iframe, object, embed").forEach((node) => node.remove());
		template.content.querySelectorAll("*").forEach((node) => {
			[...node.attributes].forEach((attribute) => {
				if (attribute.name.toLowerCase().startsWith("on") || /javascript:/i.test(attribute.value)) node.removeAttribute(attribute.name);
			});
		});
		return template.innerHTML;
	}

	function dialog_field(definition, existing_values, action) {
		const types = { Data: "Data", Int: "Int", Float: "Float", Check: "Check", Select: "Select", Date: "Date", Datetime: "Datetime", Text: "Small Text" };
		const previous = [...(existing_values || [])].reverse().find((row) =>
			row.field_key === definition.field_key && row.capture_on === action);
		return { fieldname: `dynamic_${definition.field_key}`, label: definition.label,
			fieldtype: types[definition.field_type] || "Data", reqd: Boolean(Number(definition.mandatory)),
			options: definition.options, default: previous ? previous.value : definition.default_value,
			read_only: definition.read_only };
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

	function button($parent, label, style, action) {
		$("<button class='btn " + style + "'>" + label + "</button>").appendTo($parent).on("click", action);
	}
	function scroll_to_active_work() {
		setTimeout(() => $active_root[0]?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
	}

	function priority_class(priority) {
		if (priority === "Urgent") return "priority-urgent";
		if (priority === "High") return "priority-high";
		return "";
	}
	function indicator(status) {
		if (status === "Completed") return "green";
		if (["Blocked", "Cancelled", "Escalated"].includes(status)) return "red";
		if (status === "In Progress") return "blue";
		return "orange";
	}
	load();
};
