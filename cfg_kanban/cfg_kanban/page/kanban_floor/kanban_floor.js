frappe.pages["kanban-floor"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Kanban Floor"), single_column: true });
	const state = { profile: null, timer: null, profiles: [], data: null, dragged: null };
	const profile_field = page.add_field({
		label: __("Display Profile"), fieldtype: "Select", fieldname: "profile",
		change: () => select_profile(profile_field.get_value()),
	});
	page.set_primary_action(__("Refresh"), () => load_dashboard(), "refresh");
	page.add_inner_button(__("Full Screen"), () => document.documentElement.requestFullscreen?.());
	const $root = $("<div class='cfg-floor mt-4'></div>").appendTo(page.main);

	async function initialise() {
		const response = await frappe.call({ method: "cfg_kanban.api.dashboard.get_profiles" });
		state.profiles = response.message || [];
		profile_field.df.options = state.profiles.map((row) => ({ label: row.profile_name, value: row.name }));
		profile_field.refresh();
		const requested = frappe.utils.get_url_arg("profile");
		const selected = state.profiles.find((row) => row.name === requested || row.profile_name === requested) || state.profiles[0];
		if (selected) {
			profile_field.set_value(selected.name);
			await select_profile(selected.name);
		} else {
			$root.html(`<div class="empty-state text-center p-5"><h4>${__("No active Dashboard Profile")}</h4>
				<p>${__("Create a CFG Kanban Dashboard Profile and select one or more workstations.")}</p></div>`);
		}
	}

	async function select_profile(name) {
		if (!name) return;
		state.profile = name;
		history.replaceState(null, "", `${location.pathname}?profile=${encodeURIComponent(name)}`);
		await load_dashboard();
	}

	async function load_dashboard() {
		if (!state.profile) return;
		const response = await frappe.call({
			method: "cfg_kanban.api.dashboard.get_dashboard", args: { profile_name: state.profile },
			freeze: !state.timer, freeze_message: __("Loading production floor..."),
		});
		render(response.message);
		schedule(response.message.profile.refresh_interval_seconds || 30);
	}

	function schedule(seconds) {
		if (state.timer) clearTimeout(state.timer);
		state.timer = setTimeout(load_dashboard, Math.max(10, seconds) * 1000);
	}

	function render(data) {
		const e = frappe.utils.escape_html;
		const profile = data.profile;
		state.data = data;
		$root.empty().attr("data-columns", profile.column_count || 3);
		$root.toggleClass("cfg-supervisor", Boolean(profile.can_control_dispatch));
		$root.append(`<div class="cfg-floor-head mb-3"><div><h2>${e(profile.profile_name)}</h2>
			<div class="text-muted">${e(profile.view_type)} · ${e(profile.access_mode)}${profile.description ? " · " + e(profile.description) : ""}</div></div>
			<div class="text-muted">${__("Live refresh")}: ${e(profile.refresh_interval_seconds)}s</div></div>`);
		if (profile.show_statistics) render_statistics(data.statistics);
		const $grid = $("<div class='cfg-station-grid'></div>").appendTo($root);
		(data.stations || []).forEach((station) => render_station($grid, station));
		if (!(data.stations || []).length) {
			$grid.html(`<div class="alert alert-warning">${__("No workstation is configured for this profile.")}</div>`);
		}
		$root.append(`<small class="text-muted">${e(data.sequence_source || "")}</small>`);
	}

	function render_statistics(values) {
		const cards = [
			[__("Running"), values.running, "blue"], [__("Ready"), values.ready, "green"],
			[__("Waiting"), values.waiting, "orange"], [__("Blocked"), values.blocked, "red"],
			[__("Urgent"), values.urgent, "purple"], [__("Good / Target"), `${values.good_qty} / ${values.target_qty}`, "gray"],
		];
		$root.append(`<div class="cfg-kpis mb-4">${cards.map((row) => `<div class="cfg-kpi ${row[2]}">
			<span>${row[0]}</span><strong>${row[1]}</strong></div>`).join("")}</div>`);
	}

	function render_station($grid, station) {
		const e = frappe.utils.escape_html;
		const current = station.current || [];
		const queue = station.queue || [];
		const $station = $(`<section class="cfg-station frappe-card"><header><div><h3>${e(station.workstation)}</h3>
			<span class="indicator-pill ${indicator(station.state)}">${e(station.state)}</span></div>
			<small>${__("Queued")}: ${station.total_queued || queue.length}</small></header></section>`).appendTo($grid);
		const $body = $("<div class='cfg-station-body'></div>").appendTo($station);
		if (current.length) current.forEach((row) => $body.append(execution_card(row, true)));
		else $body.append(`<div class="cfg-idle">${__("No active work")}</div>`);
		$body.append(`<div class="cfg-queue-title">${__("Upcoming Queue")}</div>`);
		if (queue.length) queue.forEach((row, index) => $body.append(execution_card(row, false, index + 1)));
		else $body.append(`<div class="text-muted p-3">${__("Queue empty")}</div>`);
	}

	function execution_card(row, active, position) {
		const e = frappe.utils.escape_html;
		const supervisor = Boolean(state.data?.profile?.can_control_dispatch);
		const controllable = supervisor && ["Not Ready", "Ready", "Waiting Input", "Blocked"].includes(row.status) && row.dispatch_queue;
		const controls = controllable ? `<div class="cfg-dispatch-controls">
			<button class="btn btn-xs btn-default cfg-move-up" title="${__("Move earlier")}">↑</button>
			<button class="btn btn-xs btn-default cfg-move-down" title="${__("Move later")}">↓</button>
			<button class="btn btn-xs ${row.expedite ? "btn-warning" : "btn-default"} cfg-expedite">${row.expedite ? __("Remove urgent") : __("Urgent")}</button>
		</div>` : "";
		return `<div class="cfg-job ${active ? "active" : "queued"} ${row.expedite || row.effective_priority === "Urgent" ? "urgent" : ""}"
			${controllable ? `draggable="true" data-queue-entry="${e(row.dispatch_queue)}" data-workstation="${e(row.workstation)}" data-expedite="${row.expedite ? 1 : 0}"` : ""}>
			<div class="cfg-job-title">${position ? `<b>${position}</b>` : ""}<span><strong>${e(row.item_code || "-")}</strong>
			<small>${e(row.item_name || "")}</small></span><span class="indicator-pill ${indicator(row.status)}">${e(row.status)}</span></div>
			<div class="cfg-progress"><i style="width:${e(row.progress_percent || 0)}%"></i></div>
			<div class="cfg-job-data"><span>${e(row.operation || "-")}</span><span>${e(row.good_qty || 0)} / ${e(row.target_qty || 0)}</span></div>
			<div class="cfg-job-data"><span>${e(row.work_order || "No Work Order")}</span><span>${e(row.job_card || "No Job Card")}</span></div>
			<div class="cfg-job-foot"><span class="priority-${(row.effective_priority || row.priority || "normal").toLowerCase()}">${e(row.effective_priority || row.priority || "Normal")}</span>
			<span>${e(row.sequence_source || "")}</span><span>${e(row.readiness || "")}</span></div>${controls}</div>`;
	}

	function request_reason(title, action) {
		if (state.timer) clearTimeout(state.timer);
		const dialog = frappe.prompt([{ fieldname: "reason", fieldtype: "Small Text", label: __("Supervisor Reason"), reqd: 1 }],
			(values) => action(values.reason), title, __("Confirm"));
		dialog.$wrapper.one("hidden.bs.modal", () => {
			if (!state.timer) schedule(state.data?.profile?.refresh_interval_seconds || 30);
		});
	}

	async function save_order($station, reason) {
		const workstation = $station.find(".cfg-job.queued[data-workstation]").first().attr("data-workstation");
		const ordered = $station.find(".cfg-job.queued[data-queue-entry]").map((_, node) => $(node).attr("data-queue-entry")).get();
		await frappe.call({ method: "cfg_kanban.services.dispatch.reorder_queue", args: {
			profile_name: state.profile, workstation, ordered_queue_entries: ordered, reason,
		}, freeze: true, freeze_message: __("Saving dispatch sequence...") });
		frappe.show_alert({ message: __("Dispatch sequence updated"), indicator: "green" });
		await load_dashboard();
	}

	$root.on("dragstart", ".cfg-job.queued[data-queue-entry]", function (event) {
		state.dragged = this;
		event.originalEvent.dataTransfer.effectAllowed = "move";
		event.originalEvent.dataTransfer.setData("text/plain", $(this).attr("data-queue-entry"));
		$(this).addClass("dragging");
	}).on("dragover", ".cfg-job.queued[data-queue-entry]", function (event) {
		if (!state.dragged || this === state.dragged || $(this).attr("data-workstation") !== $(state.dragged).attr("data-workstation")) return;
		event.preventDefault();
		const rect = this.getBoundingClientRect();
		$(this)[event.originalEvent.clientY < rect.top + rect.height / 2 ? "before" : "after"](state.dragged);
	}).on("drop", ".cfg-job.queued[data-queue-entry]", function (event) {
		event.preventDefault();
		const $station = $(this).closest(".cfg-station");
		request_reason(__("Confirm Dispatch Reorder"), (reason) => save_order($station, reason));
	}).on("dragend", ".cfg-job.queued[data-queue-entry]", function () {
		$(this).removeClass("dragging"); state.dragged = null;
	}).on("click", ".cfg-move-up,.cfg-move-down", function () {
		const $job = $(this).closest(".cfg-job");
		const $other = $(this).hasClass("cfg-move-up") ? $job.prevAll(".cfg-job.queued").first() : $job.nextAll(".cfg-job.queued").first();
		if (!$other.length) return;
		$(this).hasClass("cfg-move-up") ? $other.before($job) : $other.after($job);
		const $station = $job.closest(".cfg-station");
		request_reason(__("Confirm Dispatch Reorder"), (reason) => save_order($station, reason));
	}).on("click", ".cfg-expedite", function () {
		const $job = $(this).closest(".cfg-job");
		const enable = $job.attr("data-expedite") !== "1";
		request_reason(enable ? __("Mark as Urgent") : __("Remove Urgent Override"), async (reason) => {
			await frappe.call({ method: "cfg_kanban.services.dispatch.set_expedite", args: {
				profile_name: state.profile, queue_entry: $job.attr("data-queue-entry"), expedite: enable ? 1 : 0, reason,
			}, freeze: true, freeze_message: __("Updating dispatch priority...") });
			await load_dashboard();
		});
	});

	function indicator(status) {
		if (["Running", "In Progress"].includes(status)) return "blue";
		if (["Ready", "Completed"].includes(status)) return "green";
		if (["Blocked"].includes(status)) return "red";
		return "orange";
	}

	$(window).on("beforeunload.cfg-kanban-floor", () => state.timer && clearTimeout(state.timer));
	initialise();
};
