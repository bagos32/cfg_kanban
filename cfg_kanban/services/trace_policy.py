import frappe


NO_TAG = "No Physical Tag"


def effective_trace_policy(item_code, company):
    """Return the explicit Item/Company policy or the non-blocking ERP-only default."""
    name = frappe.db.get_value(
        "CFG Kanban Material Trace Policy",
        {"item_code": item_code, "company": company, "enabled": 1},
        "name",
    )
    if name:
        policy = frappe.get_cached_doc("CFG Kanban Material Trace Policy", name).as_dict()
        policy["policy_source"] = name
        return policy
    return frappe._dict({
        "name": None,
        "policy_source": "Default ERP-only behavior",
        "company": company,
        "item_code": item_code,
        "trace_level": "ERP Document Only",
        "receiving_tag_policy": NO_TAG,
        "production_input_tag_policy": NO_TAG,
        "production_output_tag_policy": NO_TAG,
        "warehouse_transfer_tag_policy": NO_TAG,
        "stock_withdrawal_tag_policy": NO_TAG,
        "require_batch": 0,
        "allow_partial_tag_quantity": 1,
    })


def stage_requires_tag(item_code, company, stage):
    fieldname = {
        "Purchase Receiving": "receiving_tag_policy",
        "Production Input": "production_input_tag_policy",
        "Production Output": "production_output_tag_policy",
        "Stock Withdrawal": "stock_withdrawal_tag_policy",
    }.get(stage)
    if not fieldname:
        frappe.throw(f"Unsupported material trace stage {stage}")
    return effective_trace_policy(item_code, company).get(fieldname) == "Required Physical Tag"
