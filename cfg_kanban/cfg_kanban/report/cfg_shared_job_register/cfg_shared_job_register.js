frappe.query_reports["CFG Shared Job Register"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
		},
		{
			fieldname: "status",
			label: __("Cycle Status"),
			fieldtype: "Select",
			options: [
				"",
				"New",
				"Signalled",
				"Released",
				"In Production",
				"Packing In Progress",
				"Production Complete",
				"Waiting FG Receipt",
				"Completed",
				"Hold",
				"Blocked",
				"Cancelled",
			].join("\n"),
		},
		{
			fieldname: "item_code",
			label: __("Item"),
			fieldtype: "Link",
			options: "Item",
		},
		{
			fieldname: "work_order",
			label: __("Work Order"),
			fieldtype: "Link",
			options: "Work Order",
		},
		{
			fieldname: "from_date",
			label: __("Created From"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_date",
			label: __("Created To"),
			fieldtype: "Date",
		},
		{
			fieldname: "active_only",
			label: __("Open Jobs Only"),
			fieldtype: "Check",
			default: 1,
		},
	],
};
