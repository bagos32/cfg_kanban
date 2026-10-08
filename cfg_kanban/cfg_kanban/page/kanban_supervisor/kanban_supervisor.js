frappe.pages["kanban-supervisor"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Kanban Supervisor Action Centre"),
		single_column: true,
	});
	const state = { data: null, timer: null, type: "All", priority: "All", search: "" };
	const type_field = page.add_field({
		label: __("Signal Type"), fieldtype: "Select", fieldname: "signal_type",
		options: ["All", "Production Replenishment", "Purchase Replenishment", "Transfer Replenishment"],
		default: "All", change: () => { state.type = type_field.get_value() || "All"; render(); },
	});
	const priority_field = page.add_field({
		label: __("Priority"), fieldtype: "Select", fieldname: "priority",
		options: ["All", "Urgent", "High", "Normal", "Low"], default: "All",
		change: () => { state.priority = priority_field.get_value() || "All"; render(); },
	});
	const search_field = page.add_field({
		label: __("Find"), fieldtype: "Data", fieldname: "search",
		placeholder: __("Item, card, cycle, supplier or warehouse"),
		change: () => { state.search = (search_field.get_value() || "").trim().toLowerCase(); render(); },
	});
	page.set_primary_action(__("Refresh"), () => load(true), "refresh");
	page.add_inner_button(__("Open Signal List"), () => frappe.set_route("List", "CFG Kanban Signal"));
	page.add_inner_button(__("Production Floor"), () => frappe.set_route("kanban-floor"));
	const $root = $("<div class='cfg-supervisor-centre mt-4'></div>").appendTo(page.main);

	async function load(freeze = false) {
		try {
			const response = await frappe.call({
				method: "cfg_kanban.api.supervisor.get_action_centre",
				args: { limit: 200 }, freeze,
				freeze_message: __("Loading supervisor actions..."),
			});
			state.data = response.message || {};
			render();
		} finally {
			schedule();
		}
	}

	function schedule() {
		if (state.timer) clearTimeout(state.timer);
		state.timer = setTimeout(() => load(false), 30000);
	}

	function render() {
		if (!state.data) return;
		const counts = state.data.counts || {};
		$root.empty().append(`<div class="cfg-supervisor-kpis">
			${kpi(__("Signal approvals"), counts.signals || 0, "orange")}
			${kpi(__("Service verification"), counts.service_verifications || 0, "blue")}
			${kpi(__("Process verification"), counts.process_verifications || 0, "purple")}
			${kpi(__("Open exceptions"), counts.exceptions || 0, "red")}
		</div>`);
		render_signals();
		render_attention();
	}

	function render_signals() {
		const signals = (state.data.signals || []).filter(matches_signal);
		const $section = section(__("Signal Approval Queue"),
			__("Review the operational context before creating an ERPNext Work Order or Material Request."),
			signals.length, "orange").appendTo($root);
		const $grid = $("<div class='cfg-action-grid'></div>").appendTo($section);
		if (!signals.length) return empty($grid, __("No signals match the current filters."));
		signals.forEach((row) => $grid.append(signal_card(row)));
	}

	function signal_card(row) {
		const e = frappe.utils.escape_html;
		const purchase = row.signal_type === "Purchase Replenishment";
		const purchase_detail = purchase && row.purchase_uom
			? `<div><small>${__("Planned supplier order")}</small><strong>${number(row.purchase_replenishment_qty)} ${e(row.purchase_uom)}</strong>
			<small>1 ${e(row.purchase_uom)} = ${number(row.purchase_uom_conversion_factor || 1)} ${e(row.stock_uom || "")}</small>
			<small>${e(row.purchase_execution_mode || "Material Request Only")}</small></div>` : "";
		const error = row.error_message ? `<div class="alert alert-danger cfg-inline-alert">${e(row.error_message)}</div>` : "";
		const blocked = row.cycle_blocked ? `<span class="indicator-pill red">${__("Cycle blocked")}</span>` : "";
		const can_act = state.data.permissions?.can_approve_signals;
		const can_approve_row = can_act && ["Waiting Approval", "Validated", "Failed"].includes(row.status);
		const action_label = row.status === "Failed" ? __("Retry {0}", [row.approval_action]) : __("Approve · {0}", [row.approval_action]);
		const $card = $(`<article class="cfg-action-card signal-${purchase ? "purchase" : "production"}" data-name="${e(row.name)}">
			<header><div><span class="indicator-pill ${priority_indicator(row.priority)}">${e(row.priority || "Normal")}</span>
			<span class="indicator-pill ${status_indicator(row.status)}">${e(row.status)}</span>${blocked}</div>
			<small>${e(relative_time(row.requested_on))}</small></header>
			<h3>${e(row.item_code)} <small>${e(row.item_name || "")}</small></h3>
			<div class="cfg-signal-type">${e(row.signal_type)} · ${e(row.company || "")}</div>
			<div class="cfg-action-facts">
				<div><small>${__("Card demand")}</small><strong>${number(row.requested_qty)} ${e(row.stock_uom || "")}</strong><small>${e(row.kanban_card || __("Digital signal"))}</small></div>
				${purchase_detail}
				<div><small>${purchase ? __("Supplier") : __("BOM")}</small><strong>${e((purchase ? row.supplier : row.bom) || "-")}</strong><small>${e(row.master_name || "")}</small></div>
				<div><small>${__("Destination")}</small><strong>${e(row.destination_warehouse || "-")}</strong><small>${e(row.source_warehouse || "")}</small></div>
			</div>
			<div class="cfg-action-links">${doc_link("CFG Kanban Signal", row.name)} · ${doc_link("CFG Kanban Cycle", row.kanban_cycle)}
			${row.erp_reference_name ? ` · ${doc_link(row.erp_reference_doctype, row.erp_reference_name)}` : ""}</div>
			${error}<footer><button class="btn btn-sm btn-default cfg-review">${__("Review Details")}</button>
			${can_act ? `<button class="btn btn-sm btn-danger cfg-cancel">${__("Cancel")}</button>
			${can_approve_row ? `<button class="btn btn-sm btn-primary cfg-approve">${e(action_label)}</button>` : `<span class="text-danger">${__("Resolve the block before approval")}</span>`}` : `<span class="text-muted">${__("Read-only role")}</span>`}</footer>
		</article>`);
		$card.find(".cfg-review").on("click", () => frappe.set_route("Form", "CFG Kanban Signal", row.name));
		$card.find(".cfg-approve").on("click", () => approve_signal(row));
		$card.find(".cfg-cancel").on("click", () => cancel_signal(row));
		return $card;
	}

	function render_attention() {
		const service = state.data.service_verifications || [];
		const process = state.data.process_verifications || [];
		const exceptions = state.data.exceptions || [];
		const $area = $("<div class='cfg-attention-columns'></div>").appendTo($root);
		render_simple_queue($area, __("Service Verification"), service, "blue", (row) => ({
			title: row.task_name, subtitle: [row.task_category, row.location || row.asset || row.workstation].filter(Boolean).join(" · "),
			meta: `${row.completed_by || "-"} · ${relative_time(row.completed_on)}`,
			doctype: "CFG Kanban Task", route: "kanban-tasks", route_label: __("Open Service Panel"),
		}));
		render_simple_queue($area, __("Process / QC Verification"), process, "purple", (row) => ({
			title: row.task_name, subtitle: [row.item_code, row.batch_no, row.linked_operation].filter(Boolean).join(" · "),
			meta: `${row.kanban_cycle || "-"} · ${relative_time(row.completed_on)}`,
			doctype: "CFG Kanban Process Task", route: "kanban-operator", route_label: __("Open Production Panel"),
		}));
		render_simple_queue($area, __("Exceptions"), exceptions, "red", (row) => ({
			title: `${row.severity} · ${row.exception_type}`, subtitle: row.message,
			meta: `${row.status} · ${relative_time(row.raised_on)}`,
			doctype: "CFG Kanban Exception",
		}));
	}

	function render_simple_queue($area, title, rows, color, mapper) {
		const e = frappe.utils.escape_html;
		const $section = $(`<section class="cfg-attention-queue ${color}"><header><h3>${e(title)}</h3>
			<span class="indicator-pill ${color}">${rows.length}</span></header><div class="cfg-attention-list"></div></section>`).appendTo($area);
		const $list = $section.find(".cfg-attention-list");
		if (!rows.length) return empty($list, __("Nothing waiting."));
		rows.slice(0, 20).forEach((row) => {
			const view = mapper(row);
			const $item = $(`<div class="cfg-attention-item"><strong>${e(view.title || row.name)}</strong>
				<small>${e(view.subtitle || "")}</small><span>${e(view.meta || "")}</span>
				<div><button class="btn btn-xs btn-default cfg-record">${__("Review")}</button>
				${view.route ? `<button class="btn btn-xs btn-primary cfg-panel">${e(view.route_label)}</button>` : ""}</div></div>`).appendTo($list);
			$item.find(".cfg-record").on("click", () => frappe.set_route("Form", view.doctype, row.name));
			$item.find(".cfg-panel").on("click", () => frappe.set_route(view.route));
		});
	}

	async function approve_signal(row) {
		frappe.confirm(__("Approve {0} for {1} and {2}?", [row.name, row.item_code, row.approval_action]), async () => {
			await frappe.call({ method: "cfg_kanban.api.operator.approve_signal", args: { signal_name: row.name },
				freeze: true, freeze_message: __("Processing approved signal...") });
			frappe.show_alert({ message: __("Signal approved"), indicator: "green" });
			await load(false);
		});
	}

	function cancel_signal(row) {
		const dialog = new frappe.ui.Dialog({
			title: __("Cancel and Roll Back {0}", [row.name]),
			fields: [{ fieldname: "reason", label: __("Supervisor reason"), fieldtype: "Small Text", reqd: 1 }],
			primary_action_label: __("Cancel Signal"),
			primary_action: async (values) => {
				await frappe.call({ method: "cfg_kanban.api.operator.cancel_signal",
					args: { signal_name: row.name, reason: values.reason }, freeze: true,
					freeze_message: __("Checking safe rollback...") });
				dialog.hide();
				frappe.show_alert({ message: __("Signal cancelled"), indicator: "green" });
				await load(false);
			},
		});
		dialog.show();
	}

	function matches_signal(row) {
		if (state.type !== "All" && row.signal_type !== state.type) return false;
		if (state.priority !== "All" && row.priority !== state.priority) return false;
		if (!state.search) return true;
		return [row.name, row.item_code, row.item_name, row.kanban_card, row.kanban_cycle,
			row.supplier, row.source_warehouse, row.destination_warehouse, row.company]
			.some((value) => String(value || "").toLowerCase().includes(state.search));
	}

	function section(title, subtitle, count, color) {
		return $(`<section class="cfg-action-section"><div class="cfg-section-head"><div><h2>${frappe.utils.escape_html(title)}</h2>
			<small>${frappe.utils.escape_html(subtitle)}</small></div><span class="indicator-pill ${color}">${count}</span></div></section>`);
	}
	function empty($target, message) { $target.html(`<div class="cfg-empty">${frappe.utils.escape_html(message)}</div>`); }
	function kpi(label, value, color) { return `<div class="cfg-supervisor-kpi ${color}"><span>${label}</span><strong>${value}</strong></div>`; }
	function number(value) { return format_number(value || 0, null, 2); }
	function relative_time(value) {
		if (!value) return __("Time unavailable");
		try { return frappe.datetime.prettyDate(value); }
		catch (error) { return String(value); }
	}
	function priority_indicator(value) { return value === "Urgent" ? "red" : value === "High" ? "orange" : value === "Low" ? "grey" : "blue"; }
	function status_indicator(value) { return value === "Failed" || value === "Blocked" ? "red" : value === "Validated" ? "blue" : "orange"; }
	function doc_link(doctype, name) {
		if (!doctype || !name) return "-";
		const route = String(doctype).trim().toLowerCase().replace(/\s+/g, "-");
		return `<a href="/app/${route}/${encodeURIComponent(name)}">${frappe.utils.escape_html(name)}</a>`;
	}

	$(window).on("beforeunload.cfg-kanban-supervisor", () => state.timer && clearTimeout(state.timer));
	load(true);
};
