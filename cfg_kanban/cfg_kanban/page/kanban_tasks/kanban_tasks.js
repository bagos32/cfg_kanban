frappe.pages["kanban-tasks"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Kanban Service Tasks"), single_column: true });
	const session_key = "cfg_kanban_operator_session";
	const state = { token: localStorage.getItem(session_key), operator: null };
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
			render(response.message || []);
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
	}

	function show_login_required(message) {
		$identity.empty();
		$root.html(`<div class="frappe-card text-center p-5 cfg-service-login"><h3>${__("Operator identification required")}</h3>
			<p class="text-muted">${message || __("Scan the operator QR or enter the credential before viewing tasks.")}</p>
			<div class="cfg-service-login-actions"><button class="btn btn-primary scan-operator">${__("Scan Operator QR with Camera")}</button>
			<button class="btn btn-default enter-credential">${__("Enter Credential / PIN")}</button></div></div>`);
		$root.find(".scan-operator").on("click", scan_operator_qr);
		$root.find(".enter-credential").on("click", credential_dialog);
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
		localStorage.removeItem(session_key); state.token = null; state.operator = null;
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
		const fields = [
			{ fieldtype: "Section Break", label: __("Task Information") },
			{ fieldtype: "HTML", options: task_identity(details) },
			{ fieldtype: "Section Break", label: __("Work Instructions") },
			{ fieldtype: "HTML", options: `<div class="frappe-card p-3">${safe_rich_text(details.instructions || __("No work instructions were provided."))}</div>` },
			...(action === "Verify" ? verification_evidence(details, existing_checklist, existing_values) : []),
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
