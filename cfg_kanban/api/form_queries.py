import frappe

from cfg_kanban.services.logistics_foundation import resolve_logistics_scan


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


@frappe.whitelist()
def preprinted_tag_context(scan_value):
    """Resolve a typed/scanned preprinted code while creating a Handling Unit."""
    if not frappe.has_permission("CFG Kanban Handling Unit", ptype="create"):
        frappe.throw("You do not have permission to activate Handling Units",
                     frappe.PermissionError)
    result = resolve_logistics_scan(scan_value)
    if not result:
        return {"found": False, "visible_code": str(scan_value or "").strip()}
    if result["identity_type"] == "Registered Tag Identity":
        allowed = {
            "identity_type", "name", "visible_code", "matched_by", "tag_family",
            "tag_role", "child_index", "state", "handling_unit", "issued_company",
        }
    else:
        # The activation form only needs enough information to reject a duplicate
        # Handling Unit or the wrong physical-code type. Do not expose customer or
        # warehouse context through this convenience endpoint.
        allowed = {"identity_type", "name", "visible_code", "matched_by"}
    return {"found": True, **{key: value for key, value in result.items() if key in allowed}}
