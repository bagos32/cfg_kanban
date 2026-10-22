frappe.query_reports["Kanban Operational Inventory Balance"] = {
	filters: [
		{ fieldname: "display_mode", label: __("Display Mode"), fieldtype: "Select",
			options: "Summary\nTag Detail", default: "Summary" },
		{ fieldname: "company", label: __("Inventory Company"), fieldtype: "Link", options: "Company" },
		{ fieldname: "warehouse", label: __("Current Warehouse"), fieldtype: "Link", options: "Warehouse",
			get_query: () => {
				const company = frappe.query_report.get_filter_value("company");
				return company ? { filters: { company } } : {};
			} },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "stock_uom", label: __("Stock UOM"), fieldtype: "Link", options: "UOM" },
		{ fieldname: "inventory_control_mode", label: __("Inventory Control Mode"), fieldtype: "Select",
			options: "\nKanban Operational Inventory\nERP Stock", default: "Kanban Operational Inventory" },
		{ fieldname: "quality_state", label: __("Quality State"), fieldtype: "Select",
			options: "\nReleased\nHold\nQuarantined\nRejected" },
		{ fieldname: "include_zero_balance", label: __("Include Empty / Zero Balance"), fieldtype: "Check", default: 0 },
	],
	onload(report) {
		report.page.add_inner_button(__("Summary View"), () => {
			report.set_filter_value("display_mode", "Summary");
			report.refresh();
		});
		report.page.wrapper
			.off("click.cfg_inventory_tag_detail")
			.on("click.cfg_inventory_tag_detail", "[data-cfg-inventory-tag-detail]", (event) => {
				event.preventDefault();
				const payload = JSON.parse(decodeURIComponent(
					$(event.currentTarget).attr("data-cfg-inventory-tag-detail")
				));
				Object.entries(payload).forEach(([fieldname, value]) => {
					report.set_filter_value(fieldname, value || "");
				});
				report.set_filter_value("display_mode", "Tag Detail");
				report.refresh();
			});
	},
	formatter(value, row, column, data, default_formatter) {
		const rendered = default_formatter(value, row, column, data);
		if (column.fieldname !== "tag_count" || !data || !Number(value)) return rendered;
		const payload = encodeURIComponent(JSON.stringify({
			company: data.company,
			warehouse: data.warehouse,
			item_code: data.item_code,
			stock_uom: data.stock_uom,
		}));
		return `<a href="#" data-cfg-inventory-tag-detail="${payload}" title="${__("List the exact active physical tags in this balance")}">${rendered} · ${__("View Tags")}</a>`;
	},
};
