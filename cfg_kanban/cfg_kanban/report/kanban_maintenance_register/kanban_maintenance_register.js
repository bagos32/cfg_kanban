frappe.query_reports["Kanban Maintenance Register"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -1) },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company" },
		{ fieldname: "category", label: __("Category"), fieldtype: "Data" },
		{ fieldname: "status", label: __("Task Status"), fieldtype: "Select", options: "\nAwaiting Verification\nCorrection Required\nCompleted" },
		{ fieldname: "verification_status", label: __("Verification Status"), fieldtype: "Select", options: "\nNot Required\nPending\nApproved\nRejected" },
		{ fieldname: "asset", label: __("Asset"), fieldtype: "Link", options: "Asset" },
	]
};
