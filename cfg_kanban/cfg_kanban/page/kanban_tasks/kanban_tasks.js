frappe.pages["kanban-tasks"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Kanban Service Tasks"), single_column: true });
	const session_key = "cfg_kanban_operator_session";
	const state = { token: localStorage.getItem(session_key), operator: null };
	const $identity = $("<div class='mb-3'></div>").appendTo(page.main);
	const $root = $("<div class='cfg-kanban-tasks'></div>").appendTo(page.main);
	page.set_primary_action(__("Refresh"), load, "refresh");
	page.add_inner_button(__("Identify Operator"), identify_operator);
	page.add_inner_button(__("Create Task"), create_task);

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
		$identity.html(`<div class="alert alert-info"><strong>${__("Active operator")}: ${e(state.operator.employee_name || state.operator.employee)}</strong>
			<span class="ml-2">${e(state.operator.kanban_role || "")}</span></div>`);
	}

	function show_login_required(message) {
		$identity.empty();
		$root.html(`<div class="frappe-card text-center p-5"><h4>${__("Operator identification required")}</h4>
			<p class="text-muted">${message || __("Scan the operator QR or enter the credential before viewing tasks.")}</p>
			<button class="btn btn-primary scan-operator">${__("Scan Operator QR")}</button>
			<button class="btn btn-default enter-credential">${__("Enter Credential / PIN")}</button></div>`);
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
		tasks.forEach((task) => {
			const e = frappe.utils.escape_html;
			const $row = $(`<div class="frappe-card p-3 mb-2"><div class="row align-items-center">
				<div class="col-md-4"><strong>${e(task.task_name)}</strong><br><small>${e(task.task_category)} · ${e(task.trigger_type)}</small></div>
				<div class="col-md-2"><span class="indicator-pill ${indicator(task.status)}">${e(task.status)}</span><br><small>${e(task.priority)}</small></div>
				<div class="col-md-3">${task.workstation ? `${__("Workstation")}: ${e(task.workstation)}<br>` : ""}${task.asset ? `${__("Asset")}: ${e(task.asset)}<br>` : ""}<small>${__("Due")}: ${e(task.due_on || "-")}</small></div>
				<div class="col-md-3 text-right actions"></div></div></div>`).appendTo($root);
			const $actions = $row.find(".actions");
			if (["Planned", "Due", "Assigned", "Overdue"].includes(task.status)) button($actions, __("Start"), "btn-primary", () => task_dialog(task, "Start"));
			if (["Due", "Assigned", "In Progress", "Overdue"].includes(task.status)) button($actions, __("Complete"), "btn-success", () => task_dialog(task, "Complete"));
			if (task.status === "Awaiting Verification") button($actions, __("Verify"), "btn-warning", () => task_dialog(task, "Verify"));
		});
	}

	async function task_dialog(task, action) {
		const response = await frappe.call({ method: "cfg_kanban.api.task.get_task_form", args: {
			task_name: task.name, capture_on: action, operator_session_token: state.token } });
		const details = response.message.task;
		const definitions = response.message.fields || [];
		const checklist = (details.checklist || "").split("\n").map((row) => row.trim()).filter(Boolean);
		const fields = [
			{ fieldtype: "HTML", options: frappe.utils.escape_html(details.instructions || "") },
			...checklist.map((item, index) => ({ fieldname: `check_${index}`, label: item, fieldtype: "Check", reqd: action === "Complete" })),
			...definitions.map(dialog_field),
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
		dialog.show();
	}

	function dialog_field(definition) {
		const types = { Data: "Data", Int: "Int", Float: "Float", Check: "Check", Select: "Select", Date: "Date", Datetime: "Datetime", Text: "Small Text" };
		return { fieldname: `dynamic_${definition.field_key}`, label: definition.label,
			fieldtype: types[definition.field_type] || "Data", reqd: definition.mandatory,
			options: definition.options, default: definition.default_value, read_only: definition.read_only };
	}

	function button($parent, label, style, action) {
		$("<button class='btn btn-sm " + style + " ml-1'>" + label + "</button>").appendTo($parent).on("click", action);
	}
	function indicator(status) {
		if (status === "Completed") return "green";
		if (["Blocked", "Cancelled", "Escalated"].includes(status)) return "red";
		if (status === "In Progress") return "blue";
		return "orange";
	}
	load();
};
