frappe.pages["kanban-floor"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Kanban Floor"), single_column: true });
	const state = { profile: null, timer: null, profiles: [] };
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
		$root.empty().attr("data-columns", profile.column_count || 3);
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
			<small>${__("Next")}: ${queue.length}</small></header></section>`).appendTo($grid);
		const $body = $("<div class='cfg-station-body'></div>").appendTo($station);
		if (current.length) current.forEach((row) => $body.append(execution_card(row, true)));
		else $body.append(`<div class="cfg-idle">${__("No active work")}</div>`);
		$body.append(`<div class="cfg-queue-title">${__("Upcoming Queue")}</div>`);
		if (queue.length) queue.forEach((row, index) => $body.append(execution_card(row, false, index + 1)));
		else $body.append(`<div class="text-muted p-3">${__("Queue empty")}</div>`);
	}

	function execution_card(row, active, position) {
		const e = frappe.utils.escape_html;
		return `<div class="cfg-job ${active ? "active" : "queued"} ${row.priority === "Urgent" ? "urgent" : ""}">
			<div class="cfg-job-title">${position ? `<b>${position}</b>` : ""}<span><strong>${e(row.item_code || "-")}</strong>
			<small>${e(row.item_name || "")}</small></span><span class="indicator-pill ${indicator(row.status)}">${e(row.status)}</span></div>
			<div class="cfg-progress"><i style="width:${e(row.progress_percent || 0)}%"></i></div>
			<div class="cfg-job-data"><span>${e(row.operation || "-")}</span><span>${e(row.good_qty || 0)} / ${e(row.target_qty || 0)}</span></div>
			<div class="cfg-job-data"><span>${e(row.work_order || "No Work Order")}</span><span>${e(row.job_card || "No Job Card")}</span></div>
			<div class="cfg-job-foot"><span class="priority-${(row.priority || "normal").toLowerCase()}">${e(row.priority || "Normal")}</span>
			<span>${e(row.readiness || "")}</span></div></div>`;
	}

	function indicator(status) {
		if (["Running", "In Progress"].includes(status)) return "blue";
		if (["Ready", "Completed"].includes(status)) return "green";
		if (["Blocked"].includes(status)) return "red";
		return "orange";
	}

	$(window).on("beforeunload.cfg-kanban-floor", () => state.timer && clearTimeout(state.timer));
	initialise();
};
