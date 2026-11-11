(function () {
	"use strict";

	const CANONICAL_WORKSPACE = {
		label: "CFG Kanban",
		route: "cfg-kanban",
	};
	const WORKSPACE_LABELS = new Set([
		"CFG Kanban",
		"CFG Dispatch Control",
		"CFG Job Architecture",
	]);
	const WORKSPACE_ROUTES = new Set([
		"/app/cfg-kanban",
		"/app/cfg-dispatch-control",
		"/app/cfg-job-architecture",
	]);
	const CFG_PAGE_ROUTES = new Set([
		"cfg-kanban-user-manual",
		"kanban-floor",
		"kanban-logistics",
		"kanban-operator",
		"kanban-supervisor",
		"kanban-tasks",
		"kanban-workforce-supervisor",
		"material-genealogy",
	]);
	const CFG_REPORTS = new Set([
		"cfg-shared-job-register",
		"kanban-maintenance-evidence",
		"kanban-maintenance-register",
		"kanban-operational-inventory-balance",
		"kanban-wip-bin-control",
	]);
	const DOCUMENT_ROUTE_TYPES = new Set(["form", "list", "tree"]);

	let breadcrumb_observer;
	let scheduled = false;

	function normalize(value) {
		return String(value || "")
			.trim()
			.toLowerCase()
			.replace(/[_-]+/g, " ")
			.replace(/\s+/g, " ");
	}

	function route_belongs_to_cfg_kanban(route) {
		if (!Array.isArray(route) || !route.length) {
			return false;
		}

		const route_type = normalize(route[0]);
		const target = normalize(route[1]);

		if (DOCUMENT_ROUTE_TYPES.has(route_type)) {
			return (
				target.startsWith("cfg kanban ") ||
				target.startsWith("cfg process certificate") ||
				target === "cfg erp command" ||
				target.startsWith("kanban maintenance ")
			);
		}

		if (route_type === "query report" || route_type === "report") {
			return CFG_REPORTS.has(target.replace(/\s+/g, "-"));
		}

		return CFG_PAGE_ROUTES.has(route_type.replace(/\s+/g, "-"));
	}

	function translated_label() {
		return typeof __ === "function"
			? __(CANONICAL_WORKSPACE.label)
			: CANONICAL_WORKSPACE.label;
	}

	function create_workspace_crumb(nav) {
		const item = document.createElement("li");
		const link = document.createElement("a");
		const label = translated_label();

		link.href = `/app/${CANONICAL_WORKSPACE.route}`;
		link.textContent = label;
		link.title = label;
		item.appendChild(link);
		nav.insertBefore(item, nav.firstElementChild);
	}

	function apply_canonical_breadcrumb() {
		scheduled = false;
		if (typeof frappe === "undefined" || typeof frappe.get_route !== "function") {
			return;
		}

		const route = frappe.get_route();
		if (!route_belongs_to_cfg_kanban(route)) {
			return;
		}

		const nav = document.querySelector(".navbar-breadcrumbs");
		if (!nav) {
			return;
		}

		const first_item = nav.querySelector(":scope > li:first-child");
		const first_link = first_item && first_item.querySelector("a");
		if (!first_link) {
			create_workspace_crumb(nav);
			return;
		}

		const current_label = first_link.textContent.trim();
		const current_href = first_link.getAttribute("href") || "";
		if (!WORKSPACE_LABELS.has(current_label) && !WORKSPACE_ROUTES.has(current_href)) {
			create_workspace_crumb(nav);
			return;
		}

		const label = translated_label();
		const href = `/app/${CANONICAL_WORKSPACE.route}`;
		if (first_link.getAttribute("href") !== href) {
			first_link.setAttribute("href", href);
		}
		if (current_label !== label) {
			first_link.textContent = label;
		}
		if (first_link.getAttribute("title") !== label) {
			first_link.setAttribute("title", label);
		}
	}

	function schedule_breadcrumb_update() {
		if (scheduled) {
			return;
		}
		scheduled = true;
		window.requestAnimationFrame(apply_canonical_breadcrumb);
	}

	function observe_breadcrumbs() {
		const nav = document.querySelector(".navbar-breadcrumbs");
		if (!nav || breadcrumb_observer) {
			return;
		}

		breadcrumb_observer = new MutationObserver(schedule_breadcrumb_update);
		breadcrumb_observer.observe(nav, {
			childList: true,
			subtree: true,
			characterData: true,
			attributes: true,
			attributeFilter: ["href"],
		});
	}

	function initialize_navigation() {
		observe_breadcrumbs();
		schedule_breadcrumb_update();

		if (frappe.router && typeof frappe.router.on === "function") {
			frappe.router.on("change", () => {
				observe_breadcrumbs();
				schedule_breadcrumb_update();
			});
		}
	}

	if (typeof frappe !== "undefined" && typeof frappe.ready === "function") {
		frappe.ready(initialize_navigation);
	} else {
		document.addEventListener("DOMContentLoaded", initialize_navigation, { once: true });
	}
})();
