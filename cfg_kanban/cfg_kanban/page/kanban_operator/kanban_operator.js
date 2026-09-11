frappe.pages["kanban-operator"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Kanban Operator"),
		single_column: true,
	});

	const state = { context: null };
	const scan = page.add_field({
		label: __("Scan or enter card number"),
		fieldtype: "Data",
		fieldname: "scan_token",
		change: () => load_card(scan.get_value()),
	});
	page.set_primary_action(__("Find Card"), () => load_card(scan.get_value()), "search");
	page.add_inner_button(__("Clear"), () => {
		scan.set_value("");
		state.context = null;
		render();
	});

	const $root = $("<div class='cfg-kanban-operator mt-4'></div>").appendTo(page.main);

	async function load_card(token) {
		if (!token) return;
		const response = await frappe.call({
			method: "cfg_kanban.api.operator.get_card_context",
			args: { token },
			freeze: true,
			freeze_message: __("Loading Kanban card..."),
		});
		state.context = response.message;
		render();
	}

	function render() {
		$root.empty();
		if (!state.context) {
			$root.html(`<div class="empty-state text-muted text-center p-5">
				${__("Scan a Kanban QR code or enter its card number to begin.")}</div>`);
			return;
		}
		const { card, master, cycle, executions } = state.context;
		const e = frappe.utils.escape_html;
		const cycle_label = cycle ? `<a href="/app/cfg-kanban-cycle/${e(cycle.name)}">${e(cycle.name)}</a>` : __("No active cycle");
		$root.append(`<div class="frappe-card p-4 mb-4">
			<div class="d-flex justify-content-between align-items-start flex-wrap">
				<div><h3>${e(card.card_number)}</h3><div class="text-muted">${e(master.item_code || "")}</div></div>
				<span class="indicator-pill ${indicator(card.current_state)}">${e(card.current_state)}</span>
			</div><hr>
			<div class="row">
				<div class="col-sm-3"><small>${__("Master")}</small><div>${e(master.kanban_name)}</div></div>
				<div class="col-sm-3"><small>${__("Quantity")}</small><div>${e(card.kanban_qty)}</div></div>
				<div class="col-sm-3"><small>${__("Automation")}</small><div>${e(master.automation_level)}</div></div>
				<div class="col-sm-3"><small>${__("Cycle")}</small><div>${cycle_label}</div></div>
			</div><div class="cfg-card-actions mt-4"></div>
		</div>`);
		const $actions = $root.find(".cfg-card-actions");
		if (!cycle && card.current_state === "Available") {
			$("<button class='btn btn-primary mr-2'>" + __("Consume / Trigger") + "</button>")
				.appendTo($actions).on("click", consume_card);
		}
		if (cycle) {
			$("<button class='btn btn-default mr-2'>" + __("View Timeline") + "</button>")
				.appendTo($actions).on("click", () => show_timeline(cycle.name));
		}
		render_executions(executions || []);
	}

	async function consume_card() {
		const card = state.context.card;
		await frappe.call({
			method: "cfg_kanban.api.scan.scan",
			args: { token: card.qr_code, action: "consume", event_token: frappe.utils.get_random(16) },
			freeze: true,
			freeze_message: __("Creating Kanban signal..."),
		});
		frappe.show_alert({ message: __("Kanban signal created"), indicator: "green" });
		await load_card(card.qr_code);
	}

	function render_executions(executions) {
		if (!executions.length) return;
		const e = frappe.utils.escape_html;
		const $section = $("<div><h4>" + __("Process Executions") + "</h4></div>").appendTo($root);
		executions.forEach((row) => {
			const $row = $(`<div class="frappe-card p-3 mb-2">
				<div class="row align-items-center">
				<div class="col-md-3"><strong>${e(row.sequence)}. ${e(row.operation)}</strong><div class="text-muted">${e(row.workstation || "")}</div></div>
				<div class="col-md-2"><span class="indicator-pill ${indicator(row.status)}">${e(row.status)}</span></div>
				<div class="col-md-3">${__("Good")}: ${e(row.good_qty || 0)} / ${e(row.target_qty || 0)}<br>${__("Released")}: ${e(row.released_qty || 0)}</div>
				<div class="col-md-4 text-right cfg-execution-actions"></div>
				</div></div>`).appendTo($section);
			const $buttons = $row.find(".cfg-execution-actions");
			if (row.status === "Ready") add_action($buttons, __("Start"), "btn-primary", () => job_action(row, "start"));
			if (["Ready", "In Progress", "Paused"].includes(row.status)) add_action($buttons, __("Report Progress"), "btn-default", () => progress_dialog(row));
			if (row.status === "In Progress") add_action($buttons, __("Complete"), "btn-default", () => job_action(row, "complete"));
		});
	}

	function add_action($parent, label, cls, fn) {
		$("<button class='btn btn-sm " + cls + " ml-1'>" + label + "</button>").appendTo($parent).on("click", fn);
	}

	async function job_action(row, action) {
		await frappe.call({ method: "cfg_kanban.api.operator.run_job_card_action",
			args: { execution_name: row.name, action, event_token: frappe.utils.get_random(16) }, freeze: true });
		frappe.show_alert({ message: __("Job Card updated"), indicator: "green" });
		await load_card(state.context.card.qr_code);
	}

	async function progress_dialog(row) {
		const response = await frappe.call({ method: "cfg_kanban.api.operator.get_execution_form",
			args: { execution_name: row.name, capture_on: "Progress" } });
		const definitions = response.message.fields || [];
		const fields = [
			{ fieldname: "good_qty", label: __("Good Qty"), fieldtype: "Float", reqd: 1 },
			{ fieldname: "reject_qty", label: __("Reject Qty"), fieldtype: "Float", default: 0 },
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
				}, freeze: true });
				dialog.hide();
				frappe.show_alert({ message: __("Progress recorded"), indicator: "green" });
				await load_card(state.context.card.qr_code);
			},
		});
		dialog.show();
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
		const response = await frappe.call({ method: "cfg_kanban.api.operator.get_cycle_timeline", args: { cycle_name } });
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

	render();
};
