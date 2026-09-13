import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.cycle_allocation import calculate_cycle_allocation
from cfg_kanban.services.events import record
from cfg_kanban.services.operation_summary import ensure_summary, recalculate
from cfg_kanban.services.state_machine import transition_card


TERMINAL_ALLOCATION_STATUSES = ("Completed", "Cancelled")


def preview(card_name):
    card = frappe.get_doc("CFG Kanban Card", card_name)
    _validate_runtime_card(card)
    master = frappe.get_doc("CFG Kanban Master", card.kanban_master)
    profile = _profile(master, card.operation)
    candidates = _eligible_candidates(card, master, profile)
    if not candidates:
        frappe.throw("No eligible open Job Card has remaining demand and available input")
    candidate = candidates[0]
    plan = calculate_cycle_allocation(card.kanban_qty, candidate.remaining_qty,
                                      candidate.available_input_qty)
    if plan.effective_qty <= 0:
        frappe.throw("The selected Job Card currently has no allocatable quantity")
    return {
        "card": card.name, "card_number": card.card_number, "card_type": card.card_type,
        "nominal_qty": plan.nominal_qty, "work_order": candidate.work_order,
        "work_order_status": candidate.work_order_status, "job_card": candidate.name,
        "job_card_status": candidate.status, "operation": candidate.operation,
        "workstation": candidate.workstation, "remaining_job_card_qty": plan.remaining_demand_qty,
        "available_input_qty": plan.available_input_qty, "effective_cycle_qty": plan.effective_qty,
        "short_cycle": bool(plan.short_reason), "short_cycle_reason": plan.short_reason,
    }


def allocate(card_name, job_card_name, confirmation):
    if not (confirmation or "").strip():
        frappe.throw("Operator confirmation is required")
    card = frappe.get_doc("CFG Kanban Card", card_name)
    _validate_runtime_card(card)
    # Serialize allocation decisions for this Job Card and recalculate from live ERP quantities.
    frappe.db.sql("select name from `tabJob Card` where name=%s for update", job_card_name)
    proposal = preview(card.name)
    if proposal["job_card"] != job_card_name:
        frappe.throw(f"Job Card availability changed. Review the new proposal {proposal['job_card']}.")
    master = frappe.get_doc("CFG Kanban Master", card.kanban_master)
    profile = _profile(master, card.operation)
    transition_card(card, "Consumed", event_type="Runtime Card Scanned",
                    notes=f"Selected {proposal['job_card']} from {proposal['work_order']}")
    cycle = frappe.get_doc({
        "doctype": "CFG Kanban Cycle", "kanban_master": master.name,
        "kanban_card": card.name, "item_code": master.item_code,
        "planned_qty": proposal["effective_cycle_qty"],
        "nominal_card_qty": proposal["nominal_qty"],
        "effective_cycle_qty": proposal["effective_cycle_qty"],
        "available_input_qty": proposal["available_input_qty"],
        "short_cycle": proposal["short_cycle"],
        "short_cycle_reason": proposal["short_cycle_reason"],
        "stock_uom": master.stock_uom, "status": "Released",
        "priority": master.default_priority, "work_order": proposal["work_order"],
        "selected_job_card": proposal["job_card"],
        "source_warehouse": master.source_warehouse,
        "destination_warehouse": master.destination_warehouse,
    }).insert(ignore_permissions=True)
    allocation = frappe.get_doc({
        "doctype": "CFG Kanban Runtime Allocation", "kanban_cycle": cycle.name,
        "kanban_card": card.name, "work_order": proposal["work_order"],
        "job_card": proposal["job_card"], "operation": proposal["operation"],
        "workstation": proposal["workstation"], "nominal_card_qty": proposal["nominal_qty"],
        "remaining_job_card_qty": proposal["remaining_job_card_qty"],
        "available_input_qty": proposal["available_input_qty"],
        "effective_qty": proposal["effective_cycle_qty"], "short_cycle": proposal["short_cycle"],
        "short_cycle_reason": proposal["short_cycle_reason"],
        "operator_confirmation": confirmation, "status": "Allocated",
        "allocated_on": now_datetime(),
    }).insert(ignore_permissions=True)
    cycle.db_set("runtime_allocation", allocation.name, update_modified=False)
    card.db_set("active_cycle", cycle.name, update_modified=False)
    summary = ensure_summary(cycle, master, profile)
    execution = frappe.get_doc({
        "doctype": "CFG Kanban Process Execution", "kanban_cycle": cycle.name,
        "kanban_master": master.name, "runtime_allocation": allocation.name,
        "operation_summary": summary.name, "operation": profile.operation,
        "sequence": profile.sequence, "lane_sequence": 1,
        "job_card": proposal["job_card"], "workstation": proposal["workstation"],
        "status": "In Progress" if proposal["job_card_status"] == "Work In Progress" else "Ready",
        "execution_mode": "Single Workstation",
        "allocated_qty": proposal["effective_cycle_qty"],
        "target_qty": proposal["effective_cycle_qty"],
        "input_available_qty": proposal["available_input_qty"],
        "handoff_mode": profile.handoff_mode, "transfer_multiple": profile.transfer_multiple,
        "destination_operation": profile.destination_operation,
        "operation_profile_revision": master.revision,
    }).insert(ignore_permissions=True)
    recalculate(cycle.name, profile.operation)
    transition_card(card, "Production Released", event_type="Runtime Allocation Confirmed",
                    cycle=cycle.name, notes=confirmation)
    record("Job Card Temporarily Allocated", card=card.name, cycle=cycle.name,
           execution=execution.name, qty=proposal["effective_cycle_qty"],
           reference_doctype="Job Card", reference_name=proposal["job_card"],
           notes=proposal["short_cycle_reason"] or "Full nominal card quantity")
    return {**proposal, "cycle": cycle.name, "allocation": allocation.name,
            "execution": execution.name}


def _validate_runtime_card(card):
    if card.card_type not in ("Process Kanban", "Station Kanban"):
        frappe.throw("Runtime Job Card selection is only for Process and Station Kanban cards")
    if not card.active or card.blocked:
        frappe.throw("Kanban card is inactive or blocked")
    if card.active_cycle:
        frappe.throw(f"Kanban Card already has active Cycle {card.active_cycle}")


def _profile(master, operation):
    profile = next((row for row in master.operation_profiles if row.operation == operation), None)
    if not profile:
        frappe.throw(f"Operation {operation} is not configured in Kanban Master {master.name}")
    return profile


def _eligible_candidates(card, master, profile):
    rows = frappe.db.sql("""
        select jc.name, jc.work_order, jc.operation, jc.workstation, jc.status,
               jc.for_quantity, jc.total_completed_qty, jc.creation,
               wo.status as work_order_status
        from `tabJob Card` jc
        inner join `tabWork Order` wo on wo.name=jc.work_order
        where jc.docstatus < 2 and wo.docstatus=1 and wo.cfg_kanban_controlled=1
          and wo.production_item=%s and wo.company=%s and jc.operation=%s
          and wo.status not in ('Completed', 'Cancelled', 'Stopped')
          and jc.status not in ('Completed', 'Cancelled')
        order by wo.creation asc, jc.creation asc
    """, (master.item_code, master.company, card.operation), as_dict=True)
    candidates = []
    for row in rows:
        if card.card_type == "Station Kanban" and card.workstation and row.workstation != card.workstation:
            continue
        active = flt(frappe.db.sql("""
            select coalesce(sum(effective_qty), 0)
            from `tabCFG Kanban Runtime Allocation`
            where job_card=%s and status not in ('Completed', 'Cancelled')
        """, row.name)[0][0])
        app_completed = flt(frappe.db.sql("""
            select coalesce(sum(good_qty), 0)
            from `tabCFG Kanban Runtime Allocation`
            where job_card=%s and status='Completed'
        """, row.name)[0][0])
        accounted_completed = max(flt(row.total_completed_qty), app_completed)
        row.remaining_qty = max(0, flt(row.for_quantity) - accounted_completed - active)
        row.available_input_qty = _available_input(row, master, profile, active,
                                                   accounted_completed)
        if row.remaining_qty > 0 and row.available_input_qty > 0:
            candidates.append(row)
    rule = profile.runtime_selection_rule or "Oldest Work Order First"
    if rule == "Smallest Remaining First":
        candidates.sort(key=lambda row: (row.remaining_qty, row.creation, row.name))
    elif rule == "Largest Remaining First":
        candidates.sort(key=lambda row: (-row.remaining_qty, row.creation, row.name))
    return candidates


def _available_input(job, master, profile, active_allocation, accounted_completed):
    if not profile.dependency_operation or profile.start_rule == "No Dependency":
        return job.remaining_qty
    upstream = flt(frappe.db.sql("""
        select coalesce(sum(total_completed_qty), 0) from `tabJob Card`
        where work_order=%s and operation=%s and docstatus < 2
    """, (job.work_order, profile.dependency_operation))[0][0])
    app_upstream = flt(frappe.db.sql("""
        select coalesce(sum(good_qty), 0)
        from `tabCFG Kanban Runtime Allocation`
        where work_order=%s and operation=%s and status='Completed'
    """, (job.work_order, profile.dependency_operation))[0][0])
    upstream = max(upstream, app_upstream)
    consumed = flt(accounted_completed) + flt(active_allocation)
    return max(0, min(job.remaining_qty, upstream - consumed))
