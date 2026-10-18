frappe.query_reports["Kanban WIP Bin Control"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company" },
		{ fieldname: "wip_bin_pool", label: __("WIP Bin Pool"), fieldtype: "Link",
			options: "CFG Kanban WIP Bin Pool",
			get_query: () => {
				const company = frappe.query_report.get_filter_value("company");
				const operation = frappe.query_report.get_filter_value("operation");
				const filters = {};
				if (company) filters.company = company;
				if (operation) filters.operation = operation;
				return { filters };
			} },
		{ fieldname: "operation", label: __("Operation"), fieldtype: "Link", options: "Operation" },
		{ fieldname: "workstation", label: __("Workstation"), fieldtype: "Link", options: "Workstation" },
		{ fieldname: "wip_warehouse", label: __("WIP Warehouse"), fieldtype: "Link",
			options: "Warehouse",
			get_query: () => {
				const company = frappe.query_report.get_filter_value("company");
				return company ? { filters: { company } } : {};
			} },
		{ fieldname: "wip_bin_state", label: __("WIP Bin State"), fieldtype: "Select",
			options: "\nEmpty\nReserved\nFilling\nReady\nIn Use\nException" },
		{ fieldname: "load_status", label: __("Active Load Status"), fieldtype: "Select",
			options: "\nTransfer Draft\nReady\nIn Use\nConsumption Draft\nReversed" },
		{ fieldname: "item_code", label: __("Loaded Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "attention_only", label: __("Attention Only"), fieldtype: "Check", default: 0 },
		{ fieldname: "include_unavailable", label: __("Include Disabled / Held Bins"),
			fieldtype: "Check", default: 0 },
	]
};
