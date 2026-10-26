frappe.pages["kanban-workforce-supervisor"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Kanban Workforce Supervisor Centre"),
		single_column: true,
	});
	const state = { data: null, timer: null, loading: false, search: "" };
	const company = page.add_field({
		label: __("Company"), fieldtype: "Link", options: "Company", fieldname: "company",
		default: frappe.defaults.get_user_default("Company") || "",
		change: () => load(true),
	});
	const workstation = page.add_field({
		label: __("Workstation"), fieldtype: "Link", options: "Workstation", fieldname: "workstation",
		change: () => load(true),
	});
	const expiry = page.add_field({
		label: __("Expiry Window"), fieldtype: "Select", fieldname: "expiry_days",
		options: [{ label: __("7 days"), value: "7" }, { label: __("30 days"), value: "30" },
			{ label: __("60 days"), value: "60" }, { label: __("90 days"), value: "90" }],
		default: "30", change: () => load(true),
	});
	const search = page.add_field({
		label: __("Find"), fieldtype: "Data", fieldname: "search",
		placeholder: __("Employee, Cycle, operation, workstation or skill"),
		change: () => { state.search = String(search.get_value() || "").trim().toLowerCase(); render(); },
	});
	page.set_primary_action(__("Refresh"), () => load(true), "refresh");
	page.add_inner_button(__("Shared Job Register"), () => frappe.set_route("query-report", "CFG Shared Job Register"));
	page.add_inner_button(__("Production Action Centre"), () => frappe.set_route("kanban-supervisor"));
	const $root = $("<div class='cfg-workforce-centre mt-4'></div>").appendTo(page.main);

	async function load(freeze = false) {
		if (state.loading) return;
		if (!freeze && document.hidden) return schedule();
		state.loading = true;
		try {
			const response = await frappe.call({
				method: "cfg_kanban.api.workforce_supervisor.get_workforce_action_centre",
				args: {
					company: company.get_value() || null,
					workstation: workstation.get_value() || null,
					expiry_days: expiry.get_value() || 30,
					limit: 200,
				},
				freeze,
				freeze_message: __("Loading workforce supervision..."),
			});
			state.data = response.message || {};
			render();
		} finally {
			state.loading = false;
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
		$root.empty().append(`<div class="cfg-workforce-kpis">
			${kpi(__("Active Cycles"), counts.active_cycles, "blue")}
			${kpi(__("Role Attention"), counts.role_attention, counts.role_attention ? "orange" : "green")}
			${kpi(__("Compliance Holds"), counts.compliance_holds, counts.compliance_holds ? "red" : "green")}
			${kpi(__("Active Crews"), counts.active_crews, "purple")}
			${kpi(__("People / Break"), `${counts.active_people || 0} / ${counts.on_break || 0}`, "blue")}
			${kpi(__("Competency Attention"), counts.competency_attention, counts.expired_competencies ? "red" : "orange")}
			${kpi(__("Correction Requests"), counts.open_corrections, counts.open_corrections ? "red" : "green")}
			${kpi(__("Prepared Adjustments"), counts.prepared_adjustments, counts.prepared_adjustments ? "orange" : "green")}
			${kpi(__("Recorded Hours Today"), number(counts.today_recorded_hours), "green")}
		</div>
		<div class="alert alert-info cfg-workforce-boundary">
			<strong>${__("Operational supervision view")}</strong> ·
			${__("Participation time is execution evidence only—not attendance, payroll eligibility, or payable hours. ERPNext remains the manufacturing quantity authority.")}
		</div>`);
		render_corrections();
		render_attention();
		render_crews();
		render_participation();
		render_approvals();
	}

	function render_corrections() {
		const rows = filtered(state.data.correction_requests);
		const $section = section(__("Controlled Correction Queue"),
			__("Review requests without rewriting original Kanban or ERPNext history."), rows.length).appendTo($root);
		const $list = $("<div class='cfg-workforce-list cfg-correction-list'></div>").appendTo($section);
		if (!rows.length) return empty($list, __("No correction request requires attention."));
		rows.slice(0, 100).forEach((row) => {
			const colour = row.status === "ERP Correction Required" ? "red" :
				row.status === "Approved" ? "green" : row.status === "Under Review" ? "blue" : "orange";
			const proposal = row.adjustment_proposal
				? `<small>${__("Prepared proposal")}: ${e(row.adjustment_proposal)} · ${__("Revision")} ${e(row.adjustment_revision)}</small>` : "";
			const prepare = row.status === "Approved" && row.correction_category === "Operation Progress" &&
				row.affected_doctype === "CFG Kanban Process Execution" && !row.adjustment_proposal;
			const $item = $(`<div class="cfg-workforce-row"><div><strong>${e(row.name)} · ${e(row.correction_category)}</strong>
				<small>${e(row.requested_by_name || row.requested_by_employee)} · ${relative_time(row.requested_on)}</small></div>
				<div><span>${e(row.reason)}</span><small>${e(row.affected_doctype)} · ${e(row.affected_document)}</small>${proposal}</div>
				<div><span class="indicator-pill ${colour}">${e(row.status)}</span>
				${prepare ? `<button class="btn btn-xs btn-warning ml-2 cfg-prepare-adjustment">${__("Prepare Adjustment")}</button>` : ""}
				${row.adjustment_proposal ? `<button class="btn btn-xs btn-default ml-2 cfg-view-adjustment">${__("View Proposal")}</button><button class="btn btn-xs btn-success ml-1 cfg-apply-adjustment">${__("Apply Adjustment")}</button><button class="btn btn-xs btn-danger ml-1 cfg-cancel-adjustment">${__("Cancel Proposal")}</button>` : ""}
				<button class="btn btn-xs btn-primary ml-2 cfg-review">${__("Review")}</button>
				<button class="btn btn-xs btn-default ml-1 cfg-audit">${__("Audit")}</button></div></div>`).appendTo($list);
			$item.find(".cfg-review").on("click", () => review_correction(row));
			$item.find(".cfg-audit").on("click", () => frappe.set_route("Form", "CFG Kanban Correction Request", row.name));
			$item.find(".cfg-prepare-adjustment").on("click", () => prepare_adjustment(row));
			$item.find(".cfg-view-adjustment").on("click", () => frappe.set_route("Form", "CFG Kanban Adjustment Proposal", row.adjustment_proposal));
			$item.find(".cfg-apply-adjustment").on("click", () => apply_adjustment(row));
			$item.find(".cfg-cancel-adjustment").on("click", () => cancel_adjustment(row));
		});
	}

	function adjustment_preview_html(preview) {
		const indicator = preview.eligible ? "green" : "red";
		const issues = preview.eligible ? __("Eligible for proposal preparation. No quantity will be changed.") :
			(preview.blocks || []).map((value) => e(value)).join("<br>");
		const warnings = (preview.warnings || []).length
			? `<div class="mt-2 text-warning">${preview.warnings.map((value) => e(value)).join("<br>")}</div>` : "";
		return `<div class="alert alert-${preview.eligible ? "success" : "danger"}">
			<span class="indicator-pill ${indicator}">${preview.eligible ? __("Eligible") : __("Blocked")}</span><br>
			<strong>${__("Good")}</strong>: ${number(preview.current_good_qty)} ${signed_number(preview.good_qty_delta)} → ${number(preview.proposed_good_qty)}<br>
			<strong>${__("Reject")}</strong>: ${number(preview.current_reject_qty)} ${signed_number(preview.reject_qty_delta)} → ${number(preview.proposed_reject_qty)}<br>
			<strong>${__("Processed")}</strong>: ${number(preview.current_processed_qty)} ${signed_number(preview.processed_qty_delta)} → ${number(preview.proposed_processed_qty)} / ${number(preview.target_qty)} ${e(preview.stock_uom || "")}<hr>
			${issues}${warnings}</div>`;
	}

	function signed_number(value) {
		const amount = Number(value || 0);
		return amount >= 0 ? `+ ${number(amount)}` : `− ${number(Math.abs(amount))}`;
	}

	function prepare_adjustment(row) {
		let dialog;
		dialog = new frappe.ui.Dialog({
			title: __("Prepare Kanban Adjustment — {0}", [row.name]),
			fields: [
				{ fieldname: "boundary", fieldtype: "HTML", options:
					`<div class="alert alert-info"><strong>${__("Preview only")}</strong><br>${__("This package prepares an immutable proposal. It does not change progress, handoff, Cycle, Job Card, Work Order, stock, or history.")}</div>` },
				{ fieldname: "good_qty_delta", label: __("Good Quantity Delta"), fieldtype: "Float", default: 0,
					description: __("Use a positive or negative change. Linked ERPNext Job Card good quantity is blocked from Kanban-only correction.") },
				{ fieldname: "reject_qty_delta", label: __("Reject Quantity Delta"), fieldtype: "Float", default: 0,
					description: __("Use both deltas to reclassify quantity, for example Good -5 and Reject +5.") },
				{ fieldname: "preparation_notes", label: __("Preparation Notes"), fieldtype: "Small Text", reqd: 1,
					description: __("Explain the verified arithmetic and evidence used for this proposal.") },
				{ fieldname: "preview", fieldtype: "HTML" },
			],
			primary_action_label: __("Preview Adjustment"),
			primary_action: async (values) => {
				const response = await frappe.call({
					method: "cfg_kanban.services.adjustment_proposals.preview_operation_quantity_adjustment",
					args: { request_name: row.name, good_qty_delta: values.good_qty_delta,
						reject_qty_delta: values.reject_qty_delta },
					freeze: true, freeze_message: __("Checking current adjustment readiness..."),
				});
				const preview = response.message;
				dialog.get_field("preview").$wrapper.html(adjustment_preview_html(preview));
				if (!preview.eligible) return;
				frappe.confirm(
					__("Prepare this immutable proposal for separate controlled application? No quantity changes at this stage."),
					async () => {
						await frappe.call({
							method: "cfg_kanban.services.adjustment_proposals.prepare_operation_quantity_adjustment",
							args: { request_name: row.name, good_qty_delta: values.good_qty_delta,
								reject_qty_delta: values.reject_qty_delta, preparation_notes: values.preparation_notes,
								event_token: frappe.utils.get_random(20) },
							freeze: true, freeze_message: __("Preparing audited adjustment proposal..."),
						});
						dialog.hide();
						frappe.show_alert({ message: __("Adjustment proposal prepared; no production quantity changed"), indicator: "green" });
						await load(false);
					}
				);
			},
		});
		dialog.show();
	}

	function apply_adjustment(row) {
		let dialog;
		dialog = new frappe.ui.Dialog({
			title: __("Apply Kanban Adjustment — {0}", [row.adjustment_proposal]),
			fields: [
				{ fieldname: "boundary", fieldtype: "HTML", options:
					`<div class="alert alert-warning"><strong>${__("Kanban operational correction only")}</strong><br>
					${__("This changes Process Execution totals and adds an immutable Correction progress row. It does not change ERPNext Job Cards, Work Orders, stock, batches, payroll, or historical progress rows.")}<hr>
					<strong>${__("Good")}</strong>: ${number(row.adjustment_current_good)} ${signed_number(row.adjustment_good_delta)} → ${number(row.adjustment_proposed_good)}<br>
					<strong>${__("Reject")}</strong>: ${number(row.adjustment_current_reject)} ${signed_number(row.adjustment_reject_delta)} → ${number(row.adjustment_proposed_reject)}<br>
					<strong>${__("Processed")}</strong>: ${number(row.adjustment_current_processed)} ${signed_number(Number(row.adjustment_good_delta || 0) + Number(row.adjustment_reject_delta || 0))} → ${number(row.adjustment_proposed_processed)} ${e(row.adjustment_stock_uom || "")}</div>` },
				{ fieldname: "application_notes", label: __("Application Notes"), fieldtype: "Small Text", reqd: 1,
					description: __("Record the final evidence checked immediately before applying this proposal.") },
				{ fieldname: "authority_section", label: __("Separate Exact-action Authority"), fieldtype: "Section Break" },
				{ fieldname: "approver_qr_token", label: __("Applying Reviewer Employee QR"), fieldtype: "Password", reqd: 1,
					description: __("Scan a different eligible Correct Records reviewer. The requester and proposal preparer cannot authorize application.") },
				{ fieldname: "approver_pin", label: __("Reviewer PIN (when configured)"), fieldtype: "Password" },
			],
			primary_action_label: __("Authorize and Apply"),
			primary_action: async (values) => {
				frappe.confirm(
					__("Apply this signed correction to Kanban production execution totals? ERPNext and payroll will remain unchanged."),
					async () => {
						await frappe.call({
							method: "cfg_kanban.services.adjustment_proposals.apply_operation_quantity_adjustment",
							args: { proposal_name: row.adjustment_proposal, ...values,
								event_token: frappe.utils.get_random(20) },
							freeze: true,
							freeze_message: __("Rechecking and applying Kanban adjustment..."),
						});
						dialog.hide();
						frappe.show_alert({ message: __("Kanban adjustment applied; ERPNext and payroll unchanged"), indicator: "green" });
						await load(false);
					}
				);
			},
		});
		dialog.show();
		window.setTimeout(() => dialog.get_field("approver_qr_token")?.set_focus(), 100);
	}

	function cancel_adjustment(row) {
		frappe.prompt([
			{ fieldname: "cancellation_reason", label: __("Cancellation Reason"), fieldtype: "Small Text", reqd: 1 },
		], async (values) => {
			await frappe.call({
				method: "cfg_kanban.services.adjustment_proposals.cancel_adjustment_proposal",
				args: { proposal_name: row.adjustment_proposal, cancellation_reason: values.cancellation_reason },
				freeze: true, freeze_message: __("Cancelling proposal..."),
			});
			frappe.show_alert({ message: __("Proposal cancelled; production records were unchanged"), indicator: "orange" });
			await load(false);
		}, __("Cancel Adjustment Proposal"), __("Cancel Proposal"));
	}

	function correction_decisions(status) {
		if (status === "Open") return ["Start Review", "Approve Kanban Adjustment", "Reject", "Require ERP Correction"];
		if (status === "Under Review") return ["Approve Kanban Adjustment", "Reject", "Require ERP Correction"];
		if (status === "Approved") return ["Require ERP Correction"];
		if (status === "ERP Correction Required") return ["Resolve"];
		return [];
	}

	function review_correction(row) {
		const decisions = correction_decisions(row.status);
		if (!decisions.length) return frappe.msgprint(__("This Correction Request is already terminal."));
		let dialog;
		dialog = new frappe.ui.Dialog({
			title: __("Review Correction Request {0}", [row.name]),
			fields: [
				{ fieldname: "summary", fieldtype: "HTML", options:
					`<div class="alert alert-warning"><strong>${e(row.correction_category)} · ${e(row.status)}</strong><br>
					${e(row.reason)}<hr><strong>${__("Requested correction")}</strong><br>${e(row.requested_change)}<br>
					<small>${e(row.affected_doctype)} · ${e(row.affected_document)}</small></div>` },
				{ fieldname: "decision", label: __("Decision"), fieldtype: "Select",
					options: decisions, default: decisions[0], reqd: 1 },
				{ fieldname: "review_notes", label: __("Review / Resolution Notes"),
					fieldtype: "Small Text", reqd: 1,
					description: __("State what was verified and why this decision is authorized.") },
				{ fieldname: "erp_correction_section", label: __("Authoritative ERPNext Correction Reference"),
					fieldtype: "Section Break", collapsible: 1 },
				{ fieldname: "erp_correction_doctype", label: __("ERP Correction DocType"),
					fieldtype: "Link", options: "DocType",
					description: __("Only Stock Entry, Work Order, or Job Card is accepted.") },
				{ fieldname: "erp_correction_document", label: __("ERP Correction Document"),
					fieldtype: "Dynamic Link", options: "erp_correction_doctype" },
				{ fieldname: "authority_section", label: __("Exact-action Authority"), fieldtype: "Section Break" },
				{ fieldname: "reviewer_qr_token", label: __("Reviewer Employee QR"), fieldtype: "Password",
					reqd: 1, description: __("Scan an eligible employee with Correct Records authority. This does not switch the active floor operator.") },
				{ fieldname: "reviewer_pin", label: __("Reviewer PIN (when configured)"), fieldtype: "Password" },
			],
			primary_action_label: __("Authorize Decision"),
			primary_action: async (values) => {
				await frappe.call({
					method: "cfg_kanban.services.correction_requests.review_correction_request",
					args: { request_name: row.name, ...values },
					freeze: true,
					freeze_message: __("Authorizing correction decision..."),
				});
				dialog.hide();
				frappe.show_alert({ message: __("Correction Request updated"), indicator: "green" });
				await load(false);
			},
		});
		dialog.show();
		window.setTimeout(() => dialog.get_field("reviewer_qr_token")?.set_focus(), 100);
	}

	function render_attention() {
		const $grid = $("<div class='cfg-workforce-attention'></div>").appendTo($root);
		render_queue($grid, __("Missing Role Coverage"), filtered(state.data.role_attention), "orange", (row) => ({
			title: `${row.name} · ${row.item_code || "-"}`,
			subtitle: row.job_role_compliance_summary || __("Configured workforce role is not covered"),
			meta: [row.job_owner_name || row.job_owner || __("Owner not assigned"), row.status, row.company].filter(Boolean).join(" · "),
			doctype: "CFG Kanban Cycle", name: row.name,
		}));
		render_queue($grid, __("Crew Compliance Holds"), filtered(state.data.compliance_holds), "red", (row) => ({
			title: `${row.operation || "-"} · ${row.workstation || "-"}`,
			subtitle: row.finding_summary || __("Crew policy is not satisfied"),
			meta: `${row.kanban_cycle} · ${row.checkpoint || row.status}${row.supervision_attention ? ` · ${__("Supervision attention")}` : ""}`,
			doctype: "CFG Kanban Process Execution", name: row.name,
			secondary_doctype: row.crew_compliance_hold ? "CFG Kanban Exception" : null,
			secondary_name: row.crew_compliance_hold,
		}));
		render_queue($grid, __("Competency Expiry"), filtered(state.data.competency_attention), "purple", (row) => ({
			title: `${row.employee_name || row.employee} · ${row.skill_name || row.skill}`,
			subtitle: `${row.competency_level} · ${row.expiry_state === "Expired" ? __("Expired") : __("Expires in {0} days", [row.days_remaining])}`,
			meta: [row.company, row.department, row.certification_reference].filter(Boolean).join(" · "),
			doctype: "CFG Kanban Employee Competency", name: row.name,
		}));
	}

	function render_crews() {
		const crews = filtered(state.data.active_crews);
		const $section = section(__("Live Workstation Crews"),
			__("Actual active and on-break membership; expected rosters are not treated as presence."), crews.length).appendTo($root);
		const $grid = $("<div class='cfg-workforce-crew-grid'></div>").appendTo($section);
		if (!crews.length) return empty($grid, __("No active crew matches the filters."));
		crews.forEach((crew) => {
			const people = (crew.members || []).map((member) => `<li class="${member.status === "On Break" ? "on-break" : ""}">
				<strong>${e(member.employee_name || member.employee)}</strong>
				<span>${e(member.crew_role)} · ${e(member.work_category)} · ${e(member.status)}</span></li>`).join("");
			const $card = $(`<article class="cfg-workforce-crew-card"><header><div><h3>${e(crew.workstation)}</h3>
				<small>${e(crew.operation_context || __("No operation context"))} · ${e(crew.company)}</small></div>
				<span class="indicator-pill green">${crew.active_count || 0} ${__("Active")}</span></header>
				<div class="cfg-crew-counts"><span>${__("Direct")}: <b>${crew.direct_count || 0}</b></span>
				<span>${__("Oversight")}: <b>${crew.oversight_count || 0}</b></span>
				<span>${__("Break")}: <b>${crew.break_count || 0}</b></span></div>
				<ul>${people || `<li>${__("No scanned members")}</li>`}</ul>
				<footer><button class="btn btn-xs btn-default">${__("Review Crew Session")}</button></footer></article>`).appendTo($grid);
			$card.find("button").on("click", () => frappe.set_route("Form", "CFG Kanban Crew Session", crew.name));
		});
	}

	function render_participation() {
		const participation = state.data.participation || {};
		const rows = filtered(participation.active);
		const $section = section(__("Active Job Participation"),
			__("Live contribution intervals; no production quantity and no payroll interpretation."), rows.length).appendTo($root);
		$section.append(`<div class="cfg-participation-summary">
			<span>${__("Production labour today")}: <b>${number(participation.production_hours)} h</b></span>
			<span>${__("Oversight today")}: <b>${number(participation.oversight_hours)} h</b></span>
			<span>${__("Active intervals")}: <b>${participation.active_count || 0}</b></span>
		</div>`);
		const $list = $("<div class='cfg-workforce-list'></div>").appendTo($section);
		if (!rows.length) return empty($list, __("No active participation intervals match the filters."));
		rows.slice(0, 50).forEach((row) => {
			const $item = $(`<div class="cfg-workforce-row"><div><strong>${e(row.employee_name || row.employee)}</strong>
				<small>${e(row.participation_kind)} · ${e(row.crew_role || row.participation_source)}</small></div>
				<div><span>${e(row.operation || "-")} · ${e(row.workstation || "-")}</span>
				<small>${e(row.kanban_cycle)} · ${number(row.effective_hours)} h</small></div>
				<button class="btn btn-xs btn-default">${__("Review")}</button></div>`).appendTo($list);
			$item.find("button").on("click", () => frappe.set_route("Form", "CFG Kanban Job Participation", row.name));
		});
	}

	function render_approvals() {
		const rows = filtered(state.data.supervisor_approvals);
		const $section = section(__("Recent Exact-action Supervisor Passes"),
			__("Read-only issue and consumption history. A pass never changes the active operator."), rows.length).appendTo($root);
		const $list = $("<div class='cfg-workforce-list'></div>").appendTo($section);
		if (!rows.length) return empty($list, __("No supervisor passes match the filters."));
		rows.slice(0, 50).forEach((row) => {
			const colour = row.effective_status === "Consumed" ? "green" : row.effective_status === "Approved" ? "blue" : "orange";
			const subject = row.subject_name || row.subject_employee;
			const correction = row.correction_request ? ` · ${__("Correction")}: ${e(row.correction_request)} · ${e(row.correction_decision || "-")}` : "";
			const adjustment = row.adjustment_proposal ? ` · ${__("Proposal")}: ${e(row.adjustment_proposal)}` : "";
			const $item = $(`<div class="cfg-workforce-row"><div><strong>${e(row.approved_by_name || row.approved_by_employee)}</strong>
				<small>${e(row.action_code)} · ${e(row.matched_authority_role || "-")}</small></div>
				<div><span>${e(row.kanban_cycle)} · ${e(row.operation || "-")}</span>
				<small>${e(row.requested_by_employee)}${subject ? ` · ${__("Target")}: ${e(subject)}` : ""}${correction}${adjustment} · ${relative_time(row.approved_on)}</small></div>
				<div><span class="indicator-pill ${colour}">${e(row.effective_status)}</span>
				<button class="btn btn-xs btn-default ml-2">${__("Audit")}</button></div></div>`).appendTo($list);
			$item.find("button").on("click", () => frappe.set_route("Form", "CFG Kanban Supervisor Action Approval", row.name));
		});
	}

	function render_queue($area, title, rows, colour, mapper) {
		const $queue = $(`<section class="cfg-workforce-queue ${colour}"><header><h3>${e(title)}</h3>
			<span class="indicator-pill ${colour}">${rows.length}</span></header><div></div></section>`).appendTo($area);
		const $list = $queue.children("div");
		if (!rows.length) return empty($list, __("Nothing requires attention."));
		rows.slice(0, 30).forEach((row) => {
			const view = mapper(row);
			const $item = $(`<div class="cfg-workforce-attention-row"><strong>${e(view.title)}</strong>
				<small>${e(view.subtitle)}</small><span>${e(view.meta)}</span><div>
				<button class="btn btn-xs btn-default cfg-primary">${__("Review")}</button>
				${view.secondary_name ? `<button class="btn btn-xs btn-warning cfg-secondary">${__("Open Exception")}</button>` : ""}</div></div>`).appendTo($list);
			$item.find(".cfg-primary").on("click", () => frappe.set_route("Form", view.doctype, view.name));
			$item.find(".cfg-secondary").on("click", () => frappe.set_route("Form", view.secondary_doctype, view.secondary_name));
		});
	}

	function filtered(rows) {
		rows = rows || [];
		if (!state.search) return rows;
		return rows.filter((row) => JSON.stringify(row).toLowerCase().includes(state.search));
	}
	function section(title, subtitle, count) {
		return $(`<section class="cfg-workforce-section"><div class="cfg-workforce-section-head"><div><h2>${e(title)}</h2>
			<small>${e(subtitle)}</small></div><span class="indicator-pill blue">${count}</span></div></section>`);
	}
	function kpi(label, value, colour) { return `<div class="cfg-workforce-kpi ${colour}"><span>${e(label)}</span><strong>${value || 0}</strong></div>`; }
	function empty($target, message) { $target.html(`<div class="cfg-workforce-empty">${e(message)}</div>`); }
	function e(value) { return frappe.utils.escape_html(String(value ?? "")); }
	function number(value) { return format_number(value || 0, null, 2); }
	function relative_time(value) {
		if (!value) return __("Time unavailable");
		try { return frappe.datetime.prettyDate(value); } catch (error) { return String(value); }
	}

	$(document).off("visibilitychange.cfg-workforce").on("visibilitychange.cfg-workforce", () => {
		if (!document.hidden) load(false);
	});
	$(window).on("beforeunload.cfg-workforce", () => state.timer && clearTimeout(state.timer));
	load(true);
};
