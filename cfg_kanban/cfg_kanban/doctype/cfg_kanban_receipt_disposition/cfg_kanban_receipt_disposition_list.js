frappe.listview_settings["CFG Kanban Receipt Disposition"] = {
	add_fields: ["status", "disposition", "open_rejected_qty"],
	get_indicator(doc) {
		if (doc.status === "Resolved") return [__("Resolved"), "green", "status,=,Resolved"];
		if (doc.status === "Cancelled") return [__("Cancelled"), "gray", "status,=,Cancelled"];
		if (doc.status === "Open") return [__("Decision Required"), "red", "status,=,Open"];
		return [__(doc.status || "Pending"), "orange", `status,=,${doc.status}`];
	},
};
