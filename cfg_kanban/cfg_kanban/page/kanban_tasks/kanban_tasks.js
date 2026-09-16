frappe.pages["kanban-tasks"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Kanban Service Tasks"), single_column: true });
	const token = localStorage.getItem("cfg_kanban_operator_session");
	const $root = $("<div class='cfg-kanban-tasks mt-4'></div>").appendTo(page.main);
	page.set_primary_action(__("Refresh"), load, "refresh");

	async function load() {
		if (!token) {
			$root.html(`<div class="alert alert-warning">${__("Identify the operator in Kanban Operator before opening Service Tasks.")} <a href="/app/kanban-operator">${__("Open Kanban Operator")}</a></div>`);
			return;
		}
		const response = await frappe.call({ method: "cfg_kanban.api.task.get_open_tasks",
			args: { operator_session_token: token } });
		render(response.message || []);
	}

	function render(tasks) {
		$root.empty();
		if (!tasks.length) return $root.html(`<div class="text-muted text-center p-5">${__("No open service tasks.")}</div>`);
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
			task_name: task.name, capture_on: action, operator_session_token: token } });
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
				const args = { task_name: task.name, operator_session_token: token,
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
