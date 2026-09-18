frappe.pages["kanban-tasks"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Kanban Service Tasks"), single_column: true });
	const session_key = "cfg_kanban_operator_session";
	const state = { token: localStorage.getItem(session_key), operator: null, tasks: [] };
	const $scanner = $(`<div class="frappe-card cfg-service-scanner mb-3">
		<div class="cfg-service-scanner-heading"><div><strong>${__("Service Task Scanner")}</strong>
			<small class="text-muted">${__("USB scanners can scan directly into this field and append Enter.")}</small></div>
			<span class="indicator-pill orange scanner-mode">${__("Operator scan required")}</span></div>
		<div class="cfg-service-scanner-controls">
			<input type="text" class="form-control service-scan-input" autocomplete="off" autocapitalize="off"
				spellcheck="false" placeholder="${__("Scan operator or task/card code")}">
			<button class="btn btn-primary find-service-task">${__("Find Task / Card")}</button>
			<button class="btn btn-default camera-service-task">${__("Camera Scan")}</button>
			<button class="btn btn-default clear-service-filter">${__("Show All")}</button>
		</div><div class="text-muted scanner-message"><small>${__("Before login, a scan identifies the operator. After login, a scan finds the Service Task card.")}</small></div>
	</div>`).appendTo(page.main);
	const $mobile_actions = $(`<div class="cfg-service-mobile-actions mb-3">
		<button class="btn btn-default refresh-tasks"><span class="octicon octicon-sync"></span> ${__("Refresh")}</button>
		<button class="btn btn-primary identify-operator">${__("Scan / Switch Operator")}</button>
		<button class="btn btn-success create-service-task">${__("Create Task")}</button>
	</div>`).appendTo(page.main);
	const $identity = $("<div class='mb-3'></div>").appendTo(page.main);
	const $root = $("<div class='cfg-kanban-tasks'></div>").appendTo(page.main);
	page.set_primary_action(__("Refresh"), load, "refresh");
	page.add_inner_button(__("Identify Operator"), identify_operator);
	page.add_inner_button(__("Create Task"), create_task);
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
		if (!state.token) return show_login_required();
		$root.html(`<div class="text-muted p-4">${__("Loading service tasks...")}</div>`);
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
			clear_session();
			show_login_required(__("The operator session expired. Identify the operator again on this page."));
		}
	}

	function render_identity() {
		const e = frappe.utils.escape_html;
		$identity.html(`<div class="alert alert-info cfg-service-identity">
			<div><small>${__("Active operator")}</small><br><strong>${e(state.operator.employee_name || state.operator.employee)}</strong>
			<span class="ml-2">${e(state.operator.kanban_role || "")}</span></div>
			<div class="cfg-service-session-actions">
				<button class="btn btn-default switch-operator">${__("Switch")}</button>
				<button class="btn btn-default end-session">${__("End Session")}</button>
			</div></div>`);
		$identity.find(".switch-operator").on("click", identify_operator);
		$identity.find(".end-session").on("click", confirm_end_session);
		update_scanner_mode();
	}

	function show_login_required(message) {
		state.tasks = [];
		update_scanner_mode();
		$identity.empty();
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
		setTimeout(() => document.querySelector(".cfg-service-task-card")?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
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

	function clear_session() {
		localStorage.removeItem(session_key); state.token = null; state.operator = null; state.tasks = [];
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
		$root.empty();
		if (!tasks.length) {
			$root.html(`<div class="frappe-card text-center p-5"><h4>${__("No open service tasks")}</h4>
				<p class="text-muted">${__("A Senior Operator or Supervisor can select Create Task. Scheduled tasks appear automatically when due.")}</p></div>`);
			return;
		}
		$root.append(`<div class="cfg-service-list-heading"><div><h3>${__("Open Service Tasks")}</h3>
			<small class="text-muted">${__("Tap the required action on the task card.")}</small></div>
			<span class="indicator-pill blue">${tasks.length} ${__("Open")}</span></div>`);
		tasks.forEach((task) => {
			const e = frappe.utils.escape_html;
			const $row = $(`<div class="frappe-card cfg-service-task-card ${priority_class(task.priority)}">
				<div class="cfg-service-task-head"><div><h4>${e(task.task_name)}</h4><small>${e(task.task_category)} · ${e(task.trigger_type)}</small></div>
				<div class="text-right"><span class="indicator-pill ${indicator(task.status)}">${e(task.status)}</span><div class="cfg-priority">${e(task.priority)}</div></div></div>
				<div class="cfg-service-task-meta">
					${task.workstation ? `<div><small>${__("Workstation")}</small><strong>${e(task.workstation)}</strong></div>` : ""}
					${task.asset ? `<div><small>${__("Asset")}</small><strong>${e(task.asset)}</strong></div>` : ""}
					<div><small>${__("Due")}</small><strong>${e(task.due_on || "-")}</strong></div>
				</div><div class="actions cfg-service-task-actions"></div></div>`).appendTo($root);
			const $actions = $row.find(".actions");
			if (["Planned", "Due", "Assigned", "Overdue"].includes(task.status)) button($actions, __("Start"), "btn-primary", () => task_dialog(task, "Start"));
			if (["Due", "Assigned", "In Progress", "Overdue", "Correction Required"].includes(task.status)) button($actions, task.status === "Correction Required" ? __("Correct and Resubmit") : __("Complete"), "btn-success", () => task_dialog(task, "Complete"));
			if (task.status === "Awaiting Verification") button($actions, __("Verify"), "btn-warning", () => task_dialog(task, "Verify"));
		});
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
			{ fieldtype: "Section Break", label: __("Work Instructions") },
			{ fieldtype: "HTML", options: `<div class="frappe-card p-3">${safe_rich_text(details.instructions || __("No work instructions were provided."))}</div>` },
			...(action === "Verify" ? verification_evidence(details, existing_checklist, existing_values) : []),
			{ fieldtype: "Section Break", label: __("Photo, Video and Document Evidence") },
			{ fieldname: "media_evidence", fieldtype: "HTML",
				options: media_evidence_html(existing_media, action !== "Verify") },
			...(action === "Complete" && checklist.length ? [{ fieldtype: "Section Break", label: __("Completion Checklist") }] : []),
			...checklist.map((item, index) => ({ fieldname: `check_${index}`, label: item, fieldtype: "Check",
				reqd: action === "Complete", hidden: action !== "Complete" })),
			...(definitions.length ? [{ fieldtype: "Section Break", label: action === "Verify" ? __("Verification Measurements") : action === "Start" ? __("Start Checks") : __("Measurements and Evidence") }] : []),
			...definitions.map(dialog_field),
			{ fieldtype: "Section Break", label: action === "Verify" ? __("Verification Decision") : __("Notes") },
			{ fieldname: "notes", label: __("Notes"), fieldtype: "Small Text" },
		];
		const method = { Start: "start", Complete: "complete", Verify: "verify" }[action];
		const dialog = new frappe.ui.Dialog({ title: __(`${action} Service Task`), fields,
			primary_action_label: __(action), primary_action: async (values) => {
				const args = { task_name: task.name, operator_session_token: state.token,
					values: definitions.map((definition) => ({ field_key: definition.field_key,
						value: values[`dynamic_${definition.field_key}`] })), notes: values.notes };
				if (action === "Complete") args.checklist_results = checklist.map((item, index) => ({ item, completed: values[`check_${index}`] ? 1 : 0 }));
				await frappe.call({ method: `cfg_kanban.api.task.${method}`, args, freeze: true });
				dialog.hide(); await load();
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
		bind_media_evidence(dialog, task, action, existing_media);
	}

	function media_evidence_html(rows, can_upload) {
		return `<div class="cfg-task-media-evidence">
			${can_upload ? `<label class="btn btn-primary btn-lg cfg-media-picker">
				${__("Take Photo / Add Evidence")}<input type="file" accept="image/jpeg,image/png,image/webp,video/mp4,application/pdf" capture="environment" multiple hidden>
			</label><div class="text-muted mt-2"><small>${__("Files upload directly to the configured private company media store.")}</small></div>` : ""}
			<div class="cfg-media-upload-status mt-2"></div>
			<div class="cfg-media-list mt-3">${media_rows_html(rows)}</div>
		</div>`;
	}

	function media_rows_html(rows) {
		const e = frappe.utils.escape_html;
		if (!rows.length) return `<div class="text-muted">${__("No media evidence attached yet.")}</div>`;
		return rows.map((row) => `<button type="button" class="btn btn-default cfg-media-row" data-media-id="${e(row.media_id)}">
			<span><strong>${e(row.original_filename)}</strong><small>${e(row.content_type)} · ${format_bytes(row.size_bytes)}</small></span>
			<span class="indicator-pill green">${e(row.status)}</span>
		</button>`).join("");
	}

	function bind_media_evidence(dialog, task, action, initial_rows) {
		const $field = dialog.get_field("media_evidence").$wrapper;
		let rows = initial_rows || [];
		const refresh_rows = () => {
			$field.find(".cfg-media-list").html(media_rows_html(rows));
			$field.find(".cfg-media-row").off("click").on("click", async function () {
				const response = await frappe.call({ method: "cfg_kanban.api.media.create_task_view_url", args: {
					task_name: task.name, media_id: $(this).data("media-id"),
					operator_session_token: state.token,
				} });
				window.open(response.message.url, "_blank", "noopener");
			});
		};
		refresh_rows();
		if (action === "Verify") return;
		$field.find("input[type=file]").on("change", async function () {
			const files = Array.from(this.files || []);
			if (!files.length) return;
			const $status = $field.find(".cfg-media-upload-status");
			const $picker = $field.find(".cfg-media-picker").addClass("disabled");
			try {
				for (let index = 0; index < files.length; index += 1) {
					const file = files[index];
					$status.html(`<div class="alert alert-info">${__("Uploading {0} of {1}: {2}", [index + 1, files.length, frappe.utils.escape_html(file.name)])}</div>`);
					const authorization = await frappe.call({ method: "cfg_kanban.api.media.create_task_upload_url", args: {
						task_name: task.name, original_filename: file.name, content_type: file.type,
						size_bytes: file.size, idempotency_key: frappe.utils.get_random(32),
						operator_session_token: state.token,
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
				$picker.removeClass("disabled");
				this.value = "";
			}
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

	function dialog_field(definition) {
		const types = { Data: "Data", Int: "Int", Float: "Float", Check: "Check", Select: "Select", Date: "Date", Datetime: "Datetime", Text: "Small Text" };
		return { fieldname: `dynamic_${definition.field_key}`, label: definition.label,
			fieldtype: types[definition.field_type] || "Data", reqd: definition.mandatory,
			options: definition.options, default: definition.default_value, read_only: definition.read_only };
	}

	function button($parent, label, style, action) {
		$("<button class='btn " + style + "'>" + label + "</button>").appendTo($parent).on("click", action);
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
