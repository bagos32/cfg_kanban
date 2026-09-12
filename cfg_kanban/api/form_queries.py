import frappe


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def master_operations(doctype, txt, searchfield, start, page_len, filters):
    """Limit operation selectors to the chosen Kanban Master's configured route."""
    master = (filters or {}).get("kanban_master")
    if not master:
        return []
    return frappe.db.sql("""
        select operation, coalesce(workstation, '')
        from `tabCFG Kanban Operation Profile`
        where parent=%s and parenttype='CFG Kanban Master'
          and operation like %s
        order by sequence asc
        limit %s offset %s
    """, (master, f"%{txt}%", page_len, start))


@frappe.whitelist()
def operation_profile_context(kanban_master, operation):
    frappe.get_doc("CFG Kanban Master", kanban_master).check_permission("read")
    row = frappe.db.get_value("CFG Kanban Operation Profile", {
        "parent": kanban_master, "parenttype": "CFG Kanban Master", "operation": operation,
    }, ["workstation", "handoff_mode"], as_dict=True)
    if not row:
        frappe.throw(f"Operation {operation} is not configured in Kanban Master {kanban_master}")
    return row


@frappe.whitelist()
def cycle_operations(kanban_cycle):
    cycle = frappe.get_doc("CFG Kanban Cycle", kanban_cycle)
    cycle.check_permission("read")
    master = cycle.kanban_master
    return frappe.get_all("CFG Kanban Operation Profile", filters={
        "parent": master, "parenttype": "CFG Kanban Master",
    }, fields=["operation", "sequence", "workstation", "handoff_mode", "destination_operation"],
        order_by="sequence asc")
