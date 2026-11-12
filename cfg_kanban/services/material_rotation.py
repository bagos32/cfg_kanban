"""Warehouse-local Material Run FEFO and auditable Work Order-wide exceptions.

ERPNext remains the stock authority. These checks never post stock or modify tag balances.
"""
import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, today

from cfg_kanban.services.events import record
from cfg_kanban.services.certificate_output_evidence import certificate_output_evidence, printed_expiry_dates
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.operator_auth import require_operator
from cfg_kanban.services.manufacture_expiry import assert_process_cycle_printed_expiry

OVERRIDE_DOCTYPE = "CFG Kanban Material Rotation Override"
TERMINAL_WORK_ORDER_STATES = ("Completed", "Closed", "Stopped", "Cancelled")
TOLERANCE = 0.000001


def _work_order(execution, lock=False):
    name = frappe.db.get_value("Job Card", execution.job_card, "work_order") if execution.job_card else None
    if not name:
        frappe.throw(_("Material rotation requires an exact linked Job Card and Work Order"))
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
        frappe.throw(_("Material rotation Work Order belongs to another Company"))
    if order.docstatus != 1 or order.status in TERMINAL_WORK_ORDER_STATES:
        frappe.throw(_("Material rotation requires an active submitted Work Order"))
    return order


def lock_material_rotation(execution):
    return _work_order(execution, lock=True)


def active_work_order_override(execution, current=False):
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
        from `tabCFG Kanban Material Rotation Override` approval
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
        frappe.throw(_("A Work Order-wide FEFO approval requires a supervisor with unrestricted operation and workstation scope"))
    return profile, session


@frappe.whitelist()
def approve_work_order_material_rotation(execution_name, reason, event_token, operator_session_token=None):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    require_operator(operator_session_token, "override", execution=execution)
    order = _work_order(execution, lock=True)
    profile, session = _require_order_override_authority(execution, order, operator_session_token)
    reason = str(reason or "").strip()
    if not reason or not event_token:
        frappe.throw(_("A reason and stable event token are required for Work Order FEFO approval"))
    if not frappe.db.table_exists(OVERRIDE_DOCTYPE):
        frappe.throw(_("Migrate CFG Kanban before approving Work Order FEFO overrides"))
    key = canonical_key("work-order-material-fefo-approval", order.name, event_token)
    previous = frappe.db.get_value(OVERRIDE_DOCTYPE, {"idempotency_key": key},
                                   ["name", "reason", "status"], as_dict=True)
    if previous:
        if previous.reason != reason:
            frappe.throw(_("This approval token was already used with a different reason"))
        return dict(previous)
    existing = active_work_order_override(execution, current=True)
    if existing:
        return {"name": existing.name, "status": "Active", "already_active": True}
    approval = frappe.get_doc({
        "doctype": OVERRIDE_DOCTYPE, "status": "Active", "work_order": order.name,
        "company": order.company, "active_work_order_key": order.name, "reason": reason,
        "approved_by_operator": profile.employee, "operator_session": session.name,
        "terminal_user": session.terminal_user, "approved_on": now_datetime(),
        "idempotency_key": key,
    }).insert(ignore_permissions=True)
    record("Work Order Material FEFO Override Approved", work_order=order.name,
           reference_doctype=OVERRIDE_DOCTYPE, reference_name=approval.name,
           operator=profile.employee, operator_session=session.name,
           terminal_user=session.terminal_user, notes=reason,
           idempotency_key=canonical_key("work-order-material-fefo-approved", approval.name))
    return {"name": approval.name, "status": approval.status, "work_order": order.name}


@frappe.whitelist()
def revoke_work_order_material_rotation(execution_name, reason, event_token, operator_session_token=None,
                                       approval_name=None):
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    require_operator(operator_session_token, "override", execution=execution)
    order = _work_order(execution, lock=True)
    profile, session = _require_order_override_authority(execution, order, operator_session_token)
    reason = str(reason or "").strip()
    if not reason or not event_token or not approval_name:
        frappe.throw(_("An exact approval, reason and stable event token are required for Work Order FEFO revocation"))
    key = canonical_key("work-order-material-fefo-revocation", order.name, event_token)
    previous = frappe.db.get_value(OVERRIDE_DOCTYPE, {"revocation_key": key},
                                   ["name", "revocation_reason"], as_dict=True)
    if previous:
        if previous.revocation_reason != reason or previous.name != approval_name:
            frappe.throw(_("This revocation token was already used with a different reason"))
        return {"name": previous.name, "status": "Revoked"}
    approval = active_work_order_override(execution, current=True)
    if not approval:
        return {"work_order": order.name, "status": "No Active Override"}
    if approval.name != approval_name:
        frappe.throw(_("The Work Order FEFO approval changed. Reopen and review the current approval before revoking it."))
    frappe.db.set_value(OVERRIDE_DOCTYPE, approval.name, {
        "status": "Revoked", "active_work_order_key": None,
        "revocation_reason": reason, "revoked_by_operator": profile.employee,
        "revoked_operator_session": session.name, "revoked_on": now_datetime(),
        "revocation_key": key,
    })
    record("Work Order Material FEFO Override Revoked", work_order=order.name,
           reference_doctype=OVERRIDE_DOCTYPE, reference_name=approval.name,
           operator=profile.employee, operator_session=session.name,
           terminal_user=session.terminal_user, notes=reason, idempotency_key=key)
    return {"name": approval.name, "status": "Revoked", "work_order": order.name}


def material_expiry(unit):
    """Neither a tag date nor an override may extend native Batch validity."""
    batch = None
    if unit.batch_no:
        batch = frappe.db.get_value("Batch", unit.batch_no,
                                    ["item", "disabled", "expiry_date"], as_dict=True)
        if not batch or batch.item != unit.item_code or cint(batch.disabled):
            frappe.throw(_("Source tag {0} has a missing, disabled or incompatible Batch").format(unit.handling_unit_id))
    elif cint(frappe.db.get_value("Item", unit.item_code, "has_batch_no")):
        frappe.throw(_("Batch-controlled material {0} requires a Batch on its source tag").format(unit.item_code))
    dates = [getdate(value) for value in (getattr(unit, "expiry_date", None),
             batch.expiry_date if batch else None) if value]
    dates.extend(getdate(value) for value in printed_expiry_dates(certificate_output_evidence(
        unit.name, getattr(unit, "process_certificate_set", None), unit.item_code, unit.stock_uom)))
    return min(dates) if dates else None


def assert_material_not_expired(unit):
    expiry = material_expiry(unit)
    if expiry and expiry < getdate(today()):
        frappe.throw(_("Source tag {0} expired on {1}. FEFO override cannot authorize expired material.").format(
            unit.handling_unit_id, expiry))
    return expiry


def _rotation_candidates(unit):
    # Same Company/Item/warehouse/UOM/certificate state, with outstanding micro-run
    # draws deducted in exactly the same way as the allocator and inventory report.
    return frappe.db.sql("""
        select hu.name, hu.handling_unit_id, hu.batch_no, hu.expiry_date,
               batch.expiry_date as batch_expiry, batch.item as batch_item,
               batch.disabled as batch_disabled,
               coalesce(hu.packed_on, hu.creation) as received_on,
               greatest(hu.available_qty-coalesce(draws.reserved, 0), 0) as effective_available,
               coalesce(pc.handling_unit_id, hu.handling_unit_id) as scan_code
        from `tabCFG Kanban Handling Unit` hu
        left join `tabBatch` batch on batch.name=hu.batch_no
        left join `tabCFG Kanban Handling Unit` pc on pc.name=hu.physical_container
        left join (
            select source_handling_unit,
                   sum(case when ifnull(material_trace, '')='' then drawn_qty
                            else remaining_qty end) as reserved
            from `tabCFG Kanban Operation Material Draw`
            where status in ('Open','Partially Used','Carry Forward','Used')
            group by source_handling_unit
        ) draws on draws.source_handling_unit=hu.name
        where hu.inventory_company=%(company)s and hu.item_code=%(item)s
          and hu.current_warehouse=%(warehouse)s and hu.stock_uom=%(uom)s
          and coalesce(hu.process_certificate_set,'')=%(certificate_set)s
          and hu.identity_state='Active' and hu.quality_state='Released'
          and hu.tag_kind!='Reusable Container' and hu.current_qty>0
          and hu.available_qty-coalesce(draws.reserved,0)>0.000001
          and hu.movement_state not in ('Internal Transit','Intercompany Transit','Delivered','Quarantined','Empty')
          and (
              (coalesce(hu.virtual_content,0)=0 and not exists (
                  select 1 from `tabCFG Kanban Container Content` cc
                  where cc.content_handling_unit=hu.name and cc.state='Loaded'))
              or (coalesce(hu.virtual_content,0)=1
                  and pc.identity_state='Active' and pc.quality_state='Released'
                  and pc.reusable_container_role='Production Output Container'
                  and pc.inventory_company=hu.inventory_company
                  and pc.current_warehouse=hu.current_warehouse
                  and exists (select 1 from `tabCFG Kanban Container Content` cc
                      where cc.container_handling_unit=pc.name
                        and cc.content_handling_unit=hu.name and cc.state='Loaded')
                  and (select count(*) from `tabCFG Kanban Container Content` cc
                       where cc.container_handling_unit=pc.name and cc.state='Loaded')=1)
          )
          and not exists (
              select 1 from `tabCFG Kanban Manifest Line` ml
              join `tabCFG Kanban Movement Manifest` m on m.name=ml.parent
              where ml.handling_unit in (hu.name, pc.name)
                and m.state not in ('Received','Billing Pending','Partially Billed','Billed','Closed','Cancelled')
          )
        order by hu.name
    """, {"company": unit.inventory_company, "item": unit.item_code,
          "warehouse": unit.current_warehouse, "uom": unit.stock_uom,
          "certificate_set": getattr(unit, "process_certificate_set", None) or ""}, as_dict=True)


def validate_material_rotation(execution, unit, current=False):
    expiry = assert_material_not_expired(unit)
    cohort = assert_process_cycle_printed_expiry(execution, unit, current=current)
    batch_controlled = cint(frappe.db.get_value("Item", unit.item_code, "has_batch_no"))
    eligible = []
    for row in _rotation_candidates(unit):
        if row.batch_no:
            if row.batch_item != unit.item_code or cint(row.batch_disabled):
                continue
        elif batch_controlled:
            continue
        dates = [getdate(value) for value in (row.expiry_date, row.batch_expiry) if value]
        dates.extend(getdate(value) for value in printed_expiry_dates(certificate_output_evidence(
            row.name, getattr(unit, "process_certificate_set", None), unit.item_code, unit.stock_uom)))
        candidate_expiry = min(dates) if dates else None
        if candidate_expiry and candidate_expiry < getdate(today()):
            continue
        eligible.append((candidate_expiry or getdate("9999-12-31"),
                         str(row.received_on or ""), row.name, row))
    eligible.sort(key=lambda candidate: candidate[:3])
    if not any(candidate[3].name == unit.name for candidate in eligible):
        frappe.throw(_("Source tag {0} is no longer eligible for warehouse-local material rotation").format(unit.handling_unit_id))
    first = eligible[0][3]
    approval = active_work_order_override(execution, current=True)
    bypassed = first.name != unit.name
    if bypassed and not approval:
        frappe.throw(_("FEFO requires source tag {0} first ({1} available). Use its balance first, or obtain a Work Order-wide supervisor override.").format(
            first.scan_code, first.effective_available))
    return {
        "expiry_date": str(expiry) if expiry else None,
        **cohort,
        "priority_source": first.name, "priority_scan_code": first.scan_code,
        "priority_available_qty": flt(first.effective_available),
        "rotation_override": approval.name if bypassed else None,
        "override_work_order": approval.work_order if bypassed else None,
        "override_reason": approval.reason if bypassed else None,
    }
