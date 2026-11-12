"""Work Order-wide yield approval and controlled actual-material corrections.

ERPNext remains the stock authority. These checks never post stock or modify tag balances.
"""
import math

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, today

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.operator_auth import require_operator

OVERRIDE_DOCTYPE = "CFG Kanban Work Order Yield Override"
TERMINAL_WORK_ORDER_STATES = ("Completed", "Closed", "Stopped", "Cancelled")
TOLERANCE = 0.000001


def _work_order(execution, lock=False):
    name = frappe.db.get_value("Job Card", execution.job_card, "work_order") if execution.job_card else None
    if not name:
        frappe.throw(_("Material quantity requires an exact linked Job Card and Work Order"))
    if lock:
        locked = frappe.db.sql("select name, company, docstatus, status from `tabWork Order` where name=%s for update",
                               name, as_dict=True)
        if not locked:
            frappe.throw(_("Work Order was not found"))
    order = frappe.get_doc("Work Order", name)
    if lock:
        for field in ("company", "docstatus", "status"):
            setattr(order, field, locked[0][field])
    company = frappe.db.get_value("CFG Kanban Master", execution.kanban_master, "company")
    if order.company != company:
        frappe.throw(_("Material quantity Work Order belongs to another Company"))
    if order.docstatus != 1 or order.status in TERMINAL_WORK_ORDER_STATES:
        frappe.throw(_("Material quantity requires an active submitted Work Order"))
    return order


def lock_work_order_yield(execution):
    return _work_order(execution, lock=True)


def active_work_order_yield_override(execution, current=False):
    """Read the live WO authority; never cache it in a Card or micro-run snapshot."""
    if not frappe.db.table_exists(OVERRIDE_DOCTYPE):
        return None
    order = _work_order(execution)
    # Current locking read: do not reuse a pre-lock repeatable-read snapshot after
    # a concurrent approval or revocation. All mutation paths lock the WO first.
    lock_clause = "for update" if current else ""
    rows = frappe.db.sql(f"""
        select approval.name, approval.work_order, approval.company, approval.reason,
               approval.approved_by_operator, approval.approved_on
        from `tabCFG Kanban Work Order Yield Override` approval
        inner join `tabWork Order` wo on wo.name=approval.work_order
        where approval.work_order=%s and approval.company=%s and approval.status='Active'
          and wo.docstatus=1 and wo.status not in ('Completed','Closed','Stopped','Cancelled')
        {lock_clause}
    """, (order.name, order.company), as_dict=True)
    return rows[0] if rows else None


def _require_order_override_authority(execution, order, token):
    # The approval covers the whole WO, so checking only the initiating lane is insufficient.
    profile, session = require_operator(token, "override", execution=execution)
    scopes = {(row.operation, row.workstation) for row in frappe.get_all(
        "Job Card", filters={"work_order": order.name, "docstatus": ["<", 2]},
        fields=["operation", "workstation"], limit_page_length=0,
    )}
    scopes.update((row.operation, row.workstation) for row in order.operations)
    for operation, workstation in sorted(scopes, key=lambda scope: (scope[0] or "", scope[1] or "")):
        require_operator(token, "override", operation=operation, workstation=workstation)
    # A scoped approval would silently become broader if a lane were added later. Require
    # unrestricted operation/station scope for this explicitly WO-wide authority.
    if profile.allowed_operations or profile.allowed_workstations:
        frappe.throw(_("A Work Order-wide yield approval requires a supervisor with unrestricted operation and workstation scope"))
    return profile, session


@frappe.whitelist()
def approve_work_order_yield(execution_name, reason, event_token, operator_session_token=None):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    require_operator(operator_session_token, "override", execution=execution)
    order = _work_order(execution, lock=True)
    profile, session = _require_order_override_authority(execution, order, operator_session_token)
    reason = str(reason or "").strip()
    if not reason or not event_token:
        frappe.throw(_("A reason and stable event token are required for Work Order yield approval"))
    if not frappe.db.table_exists(OVERRIDE_DOCTYPE):
        frappe.throw(_("Migrate CFG Kanban before approving Work Order yield/quantity overrides"))
    key = canonical_key("work-order-yield-approval", order.name, event_token)
    previous = frappe.db.get_value(OVERRIDE_DOCTYPE, {"idempotency_key": key},
                                   ["name", "reason", "status"], as_dict=True)
    if previous:
        if previous.reason != reason:
            frappe.throw(_("This approval token was already used with a different reason"))
        return dict(previous)
    existing = active_work_order_yield_override(execution, current=True)
    if existing:
        return {"name": existing.name, "status": "Active", "already_active": True}
    approval = frappe.get_doc({
        "doctype": OVERRIDE_DOCTYPE, "status": "Active", "work_order": order.name,
        "company": order.company, "active_work_order_key": order.name, "reason": reason,
        "approved_by_operator": profile.employee, "operator_session": session.name,
        "terminal_user": session.terminal_user, "approved_on": now_datetime(),
        "idempotency_key": key,
    }).insert(ignore_permissions=True)
    record("Work Order Yield Override Approved", work_order=order.name,
           reference_doctype=OVERRIDE_DOCTYPE, reference_name=approval.name,
           operator=profile.employee, operator_session=session.name,
           terminal_user=session.terminal_user, notes=reason,
           idempotency_key=canonical_key("work-order-yield-approved", approval.name))
    return {"name": approval.name, "status": approval.status, "work_order": order.name}


@frappe.whitelist()
def revoke_work_order_yield(execution_name, reason, event_token, operator_session_token=None,
                                       approval_name=None):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    require_operator(operator_session_token, "override", execution=execution)
    order = _work_order(execution, lock=True)
    profile, session = _require_order_override_authority(execution, order, operator_session_token)
    reason = str(reason or "").strip()
    if not reason or not event_token or not approval_name:
        frappe.throw(_("An exact approval, reason and stable event token are required for Work Order yield revocation"))
    key = canonical_key("work-order-yield-revocation", order.name, event_token)
    previous = frappe.db.get_value(OVERRIDE_DOCTYPE, {"revocation_key": key},
                                   ["name", "revocation_reason"], as_dict=True)
    if previous:
        if previous.revocation_reason != reason or previous.name != approval_name:
            frappe.throw(_("This revocation token was already used with a different reason"))
        return {"name": previous.name, "status": "Revoked"}
    approval = active_work_order_yield_override(execution, current=True)
    if not approval:
        return {"work_order": order.name, "status": "No Active Override"}
    if approval.name != approval_name:
        frappe.throw(_("The Work Order yield approval changed. Reopen and review the current approval before revoking it."))
    frappe.db.set_value(OVERRIDE_DOCTYPE, approval.name, {
        "status": "Revoked", "active_work_order_key": None,
        "revocation_reason": reason, "revoked_by_operator": profile.employee,
        "revoked_operator_session": session.name, "revoked_on": now_datetime(),
        "revocation_key": key,
    })
    record("Work Order Yield Override Revoked", work_order=order.name,
           reference_doctype=OVERRIDE_DOCTYPE, reference_name=approval.name,
           operator=profile.employee, operator_session=session.name,
           terminal_user=session.terminal_user, notes=reason, idempotency_key=key)
    return {"name": approval.name, "status": "Revoked", "work_order": order.name}



def _correction_actor(execution_name, token):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    require_operator(token, "override", execution=execution)
    order = _work_order(execution, lock=True)
    profile, session = _require_order_override_authority(execution, order, token)
    return execution, order, profile, session


def _retry(key, fingerprint):
    row = frappe.db.get_value("CFG Kanban Event", {"device_id": key}, ["payload_json"], as_dict=True)
    if row:
        if frappe.parse_json(row.payload_json).get("request") != fingerprint:
            frappe.throw("Correction token was reused with different actual quantities or reason")
        return True
    return False


@frappe.whitelist()
def material_correction_context(execution_name, operator_session_token=None):
    execution, order, _profile, _session = _correction_actor(execution_name, operator_session_token)
    draws = frappe.get_all("CFG Kanban Operation Material Draw", filters={
        "work_order": order.name, "job_card": execution.job_card,
        "status": ["in", ["Used", "Carry Forward", "Partially Used"]]},
        fields=["name", "item_code", "drawn_qty", "used_qty", "remaining_qty", "stock_uom", "material_trace"],
        limit_page_length=0)
    entries = frappe.get_all("Stock Entry", filters={"work_order": order.name, "docstatus": 0,
        "purpose": ["in", ["Material Consumption for Manufacture", "Manufacture"]]},
        fields=["name", "cfg_kanban_job_card"], limit_page_length=0)
    names = [entry.name for entry in entries if not entry.cfg_kanban_job_card or entry.cfg_kanban_job_card == execution.job_card]
    traces = frappe.get_all("CFG Kanban Material Trace", filters={"stock_entry": ["in", names]},
                            fields=["name", "stock_entry"], limit_page_length=0) if names else []
    parents = {trace.name: trace.stock_entry for trace in traces}
    lines = frappe.get_all("CFG Kanban Material Trace Line", filters={"parent": ["in", list(parents)],
        "direction": "Input", "status": "Reserved"},
        fields=["name", "parent", "item_code", "qty", "stock_uom"], limit_page_length=0) if parents else []
    from cfg_kanban.services.hidden_items import get_hidden_item_policy
    policy = get_hidden_item_policy()
    hidden = policy["items"] if not policy["can_view"] else set()
    return {"work_order": order.name, "choices": [
        {"value": "DRAW:" + draw.name, "label": f"{draw.item_code}: used {draw.used_qty}; drawn {draw.drawn_qty} {draw.stock_uom}",
         "qty": draw.used_qty} for draw in draws if not draw.material_trace and draw.item_code not in hidden] + [
        {"value": "TRACE:" + line.name, "label": f"{line.item_code}: traced {line.qty} {line.stock_uom} on {parents[line.parent]}",
         "qty": line.qty, "stock_entry": parents[line.parent]} for line in lines if line.item_code not in hidden]}


@frappe.whitelist()
def correct_material_use(execution_name, target, actual_qty, reason, event_token,
                         operator_session_token=None, kanban_card=None):
    from frappe.utils import flt
    execution, order, profile, session = _correction_actor(execution_name, operator_session_token)
    reason = str(reason or "").strip()
    qty = flt(actual_qty)
    if not reason or not event_token or not math.isfinite(qty) or qty < 0:
        frappe.throw("A non-negative actual quantity, reason and stable event token are required")
    fingerprint = canonical_key("material-use-correction-request", execution.name, target, qty, reason)
    key = canonical_key("material-use-correction", order.name, event_token)
    if _retry(key, fingerprint):
        return {"duplicate": True}
    kind, name = target.split(":", 1)
    if kind == "DRAW":
        frappe.db.sql("select name from `tabCFG Kanban Operation Material Draw` where name=%s for update", name)
        draw = frappe.get_doc("CFG Kanban Operation Material Draw", name)
        if draw.work_order != order.name or draw.job_card != execution.job_card:
            frappe.throw("Material Draw is outside this Job Card / Work Order")
        if draw.material_trace or draw.status not in ("Used", "Carry Forward", "Partially Used"):
            frappe.throw("Cancel or discard the linked ERP Draft before correcting its original Material Draw; submitted entries require controlled ERP recovery")
        if qty > draw.drawn_qty:
            frappe.throw("Actual use cannot exceed the physically scanned draw; record the additional source material first")
        _assert_material_visible(draw.item_code)
        before = draw.used_qty
        draw.db_set({"used_qty": qty, "remaining_qty": flt(draw.drawn_qty) - qty,
                     "status": "Used" if abs(qty - flt(draw.drawn_qty)) < 0.000001 else "Carry Forward"})
        from cfg_kanban.services.operation_material_runs import _refresh_run_totals
        _refresh_run_totals(frappe.get_doc("CFG Kanban Operation Material Run", draw.material_run))
        reference_type, reference_name = draw.doctype, draw.name
    elif kind == "TRACE":
        if qty <= 0:
            frappe.throw("Use controlled trace-line cancellation for zero actual use")
        original = frappe.get_doc("CFG Kanban Material Trace Line", name)
        trace = frappe.get_doc("CFG Kanban Material Trace", original.parent)
        from cfg_kanban.services.production_trace import (
            _lock_stock_entry, cancel_trace_line, allocate_input_tag,
        )
        _lock_stock_entry(trace.stock_entry)
        entry = frappe.get_doc("Stock Entry", trace.stock_entry)
        if entry.docstatus != 0 or entry.work_order != order.name or entry.purpose not in ("Material Consumption for Manufacture", "Manufacture"):
            frappe.throw("Only an unsubmitted production consumption Draft of this Work Order can be corrected; posted stock needs controlled ERP recovery")
        if entry.get("cfg_kanban_job_card") and entry.cfg_kanban_job_card != execution.job_card:
            frappe.throw("This Draft belongs to another Job Card")
        original = frappe.get_doc("CFG Kanban Material Trace Line", name)
        if original.direction != "Input" or original.status != "Reserved":
            frappe.throw("The selected Material Trace allocation is no longer editable")
        if frappe.db.exists("CFG Kanban Operation Material Draw", {"material_trace_line": name}):
            frappe.throw("This trace was adopted from Material Runs. Discard the Draft and correct the original draw, then settle it again")
        _assert_material_visible(original.item_code)
        before = flt(original.qty)
        unit = frappe.get_doc("CFG Kanban Handling Unit", original.handling_unit)
        scan_code = frappe.db.get_value("CFG Kanban Handling Unit", original.get("physical_container"), "handling_unit_id") if original.get("physical_container") else unit.handling_unit_id
        cancel_trace_line(entry.name, name, operator_session_token, kanban_card)
        entry.reload()
        row = next((row for row in entry.items if row.name == original.stock_entry_detail), None)
        if not row or not row.s_warehouse or row.t_warehouse:
            frappe.throw("Only a consumption input row can be adjusted")
        conversion = flt(row.conversion_factor or 1)
        total = flt(row.transfer_qty or flt(row.qty) * conversion) - before + qty
        if total <= 0 or conversion <= 0:
            frappe.throw("Invalid corrected stock quantity or UOM conversion")
        row.qty, row.transfer_qty = total / conversion, total
        entry.save(ignore_permissions=True)
        allocate_input_tag(entry.name, row.name, scan_code, qty, operator_session_token, kanban_card)
        reference_type, reference_name = "Stock Entry", entry.name
    else:
        frappe.throw("Select an exact Material Draw or Material Trace allocation")
    record("Actual Material Use Corrected", work_order=order.name, job_card=execution.job_card,
           execution=execution.name, qty=qty - flt(before), operator=profile.employee,
           operator_session=session.name, terminal_user=session.terminal_user,
           reference_doctype=reference_type, reference_name=reference_name, device_id=key,
           idempotency_key=key, notes=reason,
           payload={"request": fingerprint, "target": target, "before": before, "after": qty, "reason": reason})
    return {"duplicate": False, "before": before, "actual_qty": qty}


def _assert_material_visible(item_code):
    from cfg_kanban.services.hidden_items import get_hidden_item_policy
    policy = get_hidden_item_policy()
    if not policy["can_view"] and item_code in policy["items"]:
        frappe.throw("Restricted materials are managed server-side")


def progress_material_choices(execution):
    from cfg_kanban.services.operation_material_runs import material_run_rules
    from cfg_kanban.services.hidden_items import get_hidden_item_policy
    policy = get_hidden_item_policy()
    hidden = policy["items"] if not policy["can_view"] else set()
    return [{"rule_row": rule.rule_row, "item_code": rule.item_code,
             "stock_uom": rule.stock_uom, "qty": None} for rule in material_run_rules(execution) if rule.item_code not in hidden]


def validate_material_variance(doc, method=None):
    """Record actual use in Draft; require WO approval before excess native posting."""
    from frappe.utils import flt
    if not doc.get("cfg_kanban_controlled") or not doc.get("work_order") or doc.get("purpose") not in ("Material Consumption for Manufacture", "Manufacture"):
        return
    order = frappe.get_doc("Work Order", doc.work_order)
    actual = {}
    for row in doc.items:
        if row.s_warehouse and not row.t_warehouse:
            actual[row.item_code] = actual.get(row.item_code, 0) + flt(row.transfer_qty or flt(row.qty) * flt(row.conversion_factor or 1))
    expected = {}
    for row in order.required_items:
        expected[row.item_code] = expected.get(row.item_code, 0) + flt(row.required_qty)
    if any(qty > expected.get(item, 0) + 0.000001 for item, qty in actual.items()):
        if not frappe.db.table_exists(OVERRIDE_DOCTYPE):
            frappe.throw("Migrate CFG Kanban before approving quantity variances")
        approval = frappe.db.sql("""
            select approval.name from `tabCFG Kanban Work Order Yield Override` approval
            join `tabWork Order` wo on wo.name=approval.work_order
            where approval.work_order=%s and approval.company=%s and approval.status='Active'
              and wo.docstatus=1 and wo.status not in ('Completed','Closed','Stopped','Cancelled')
            for update
        """, (order.name, doc.company))
        if not approval:
            frappe.throw("Actual material use exceeds the Work Order BOM estimate. Preserve the actual quantity and obtain a Work Order-wide yield/quantity approval before posting")
