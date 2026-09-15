frappe.pages["kanban-operator"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Kanban Operator"),
		single_column: true,
	});

	const session_key = "cfg_kanban_operator_session";
	const state = { context: null, operator: null, session_token: localStorage.getItem(session_key) };
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
	page.add_inner_button(__("Switch Operator"), () => show_operator_login(true));

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
	}

	function show_operator_login(switching) {
		const dialog = new frappe.ui.Dialog({
			title: switching ? __("Switch Operator") : __("Operator Login"),
			fields: [
				{ fieldname: "token", label: __("Scan Operator QR"), fieldtype: "Data", reqd: 1 },
				{ fieldname: "pin", label: __("PIN (if required)"), fieldtype: "Password" },
				{ fieldname: "station", label: __("Terminal / Station"), fieldtype: "Data",
					default: localStorage.getItem("cfg_kanban_station") || "" },
			],
			primary_action_label: __("Continue"),
			primary_action: async (values) => {
				const response = await frappe.call({ method: "cfg_kanban.api.operator.login_operator",
					args: values, freeze: true, freeze_message: __("Identifying operator...") });
				clear_operator();
				state.session_token = response.message.session_token;
				state.operator = response.message.operator;
				localStorage.setItem(session_key, state.session_token);
				localStorage.setItem("cfg_kanban_station", values.station || "");
				dialog.hide();
				render();
				scan.set_focus();
			},
		});
		dialog.show();
		dialog.get_field("token").set_focus();
	}

	async function load_card(token) {
		if (!token) return;
		if (!state.operator) return show_operator_login(false);
		const response = await frappe.call({
			method: "cfg_kanban.api.operator.get_card_context",
			args: { token, operator_session_token: state.session_token },
			freeze: true,
			freeze_message: __("Loading Kanban card..."),
		});
		state.context = response.message;
		render();
	}

	function render() {
		$root.empty();
		if (!state.operator) {
			$root.html(`<div class="frappe-card text-center p-5"><h4>${__("Operator identification required")}</h4>
				<p class="text-muted">${__("Scan your personal operator QR. The terminal remains signed in to ERPNext.")}</p>
				<button class="btn btn-primary cfg-operator-login">${__("Scan Operator QR")}</button></div>`);
			$root.find(".cfg-operator-login").on("click", () => show_operator_login(false));
			return;
		}
		const e = frappe.utils.escape_html;
		$root.append(`<div class="alert alert-info d-flex justify-content-between align-items-center">
			<div><strong>${__("Active operator")}: ${e(state.operator.employee_name)}</strong>
			<span class="ml-2">${e(state.operator.employee)} · ${e(state.operator.kanban_role || "")}</span></div>
			<div>${e(state.operator.station || "")}</div></div>`);
		if (!state.context) {
			$root.append(`<div class="empty-state text-muted text-center p-5">
				${__("Scan a Kanban QR code or enter its card number to begin.")}</div>`);
			return;
		}
		const { card, master, cycle, effective_work_order, work_order_attention, selected_job_card, executions, operation_summaries, work_orders, route_warnings } = state.context;
		const cycle_label = cycle ? `${document_link("cfg-kanban-cycle", cycle.name)}${status_line(cycle.status)}` : __("No active cycle");
		const work_order_label = effective_work_order
			? `${document_link("work-order", effective_work_order.name)}${status_line(effective_work_order.status, effective_work_order.docstatus)}`
			: document_link("work-order", null);
		$root.append(`<div class="frappe-card p-4 mb-4">
			<div class="d-flex justify-content-between align-items-start flex-wrap">
				<div><div class="d-flex align-items-center flex-wrap"><h3 class="mr-3 mb-1">${e(card.card_number)}</h3>
					<span class="indicator-pill blue mb-1">${e(card.card_type || __("Unspecified Card Type"))}</span></div>
					<div><strong>${e(card.item_code || master.item_code || "")}</strong> · ${e(card.kanban_qty || 0)} ${e(card.stock_uom || master.stock_uom || "")}</div>
					<div class="text-muted">${e(master.control_type || "")} ${master.card_representation ? "· " + e(master.card_representation) : ""}${card.operation ? " · " + e(card.operation) : ""}</div></div>
				<div class="text-right"><small>${__("Card Status")}</small><br><span class="indicator-pill ${indicator(card.current_state)}">${e(card.current_state)}</span></div>
			</div><hr>
			<div class="row">
				<div class="col-sm-2"><small>${__("Master")}</small><div>${e(master.kanban_name)}</div></div>
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
		render_summaries(operation_summaries || []);
		render_executions(executions || []);
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

	restore_operator();
};
