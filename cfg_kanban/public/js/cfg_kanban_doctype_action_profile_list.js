frappe.listview_settings["CFG Kanban DocType Action Profile"] = {
	onload(listview) {
		listview.page.add_inner_button(__("Install Gate 1 Pilot"), async () => {
			const confirmed = await new Promise((resolve) => {
				frappe.confirm(
					__(
						"Install or restore the two non-production Gate 1 pilot profiles? "
						+ "Use them only on the development site.",
					),
					() => resolve(true),
					() => resolve(false),
				);
			});
			if (!confirmed) return;
			const response = await frappe.call({
				method: "cfg_kanban.api.doctype_action.install_gate1_pilot",
				type: "POST",
				freeze: true,
				freeze_message: __("Preparing Gate 1 pilot profiles..."),
			});
			frappe.msgprint({
				title: __("Gate 1 Pilot Ready"),
				indicator: "green",
				message: frappe.utils.escape_html(response.message.message),
			});
			listview.refresh();
		});
	},
};
