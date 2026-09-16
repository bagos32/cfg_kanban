frappe.query_reports["Kanban Maintenance Evidence"] = {
	filters: [
		{ fieldname: "task", label: __("Task"), fieldtype: "Link", options: "CFG Kanban Task" },
		{ fieldname: "from_date", label: __("Completed From"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("Completed To"), fieldtype: "Date" },
		{ fieldname: "evidence_type", label: __("Evidence Type"), fieldtype: "Select", options: "\nChecklist\nDynamic Field" },
		{ fieldname: "verification_status", label: __("Verification Status"), fieldtype: "Select", options: "\nNot Required\nPending\nApproved\nRejected" },
	]
};
