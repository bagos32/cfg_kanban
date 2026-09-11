frappe.pages["cfg-kanban-user-manual"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("CFG Kanban User Manual"),
		single_column: true,
	});

	page.add_inner_button(__("Print Manual"), () => window.print(), "Actions");
	page.add_inner_button(__("Back to CFG Kanban"), () => frappe.set_route("Workspaces", "CFG Kanban"));

	const $root = $("<div class='cfg-kanban-manual frappe-card'></div>").appendTo(page.main);
	$root.html(`<div class="text-muted text-center p-5">${__("Loading user manual...")}</div>`);

	frappe.call({
		method: "cfg_kanban.api.manual.get_user_manual",
	}).then((response) => {
		$root.html(response.message.html);
		build_toc($root);
	}).catch(() => {
		$root.html(`<div class="alert alert-danger m-4">${__("The user manual could not be loaded. Ask the administrator to verify the app deployment.")}</div>`);
	});
};

function build_toc($manual) {
	const $headings = $manual.find("h2");
	if (!$headings.length) return;
	const $toc = $("<div class='cfg-manual-toc'><strong>" + __("Contents") + "</strong><ol></ol></div>");
	$headings.each((index, heading) => {
		const id = `manual-section-${index + 1}`;
		heading.id = id;
		$("<li></li>").append($("<a></a>").attr("href", `#${id}`).text($(heading).text())).appendTo($toc.find("ol"));
	});
	$manual.find("h1").first().after($toc);
}
