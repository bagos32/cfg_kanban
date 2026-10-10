frappe.query_reports["Kanban Operational Inventory Balance"] = {
	filters: [
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
	]
};
