"""Release unused operational reservations at a proven Cycle boundary; never post stock."""
import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key

TOLERANCE = 0.000001


def release_closed_execution(execution_name, reason, *, operator=None,
                             operator_session=None, terminal_user=None):
    """Keep used evidence pending ERP; return only unused quantity to source availability."""
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    cycle = frappe.get_doc("CFG Kanban Cycle", execution.kanban_cycle)
    if cycle.status != "Completed":
        frappe.throw("Unused material release requires a completed operation or production Cycle")
    draws = frappe.db.sql("""
        select name, material_run, source_handling_unit, work_order, job_card,
               operation, workstation, drawn_qty, used_qty, remaining_qty,
               released_qty, status
        from `tabCFG Kanban Operation Material Draw`
        where process_execution=%s and remaining_qty > 0.000001
          and status in ('Open','Partially Used','Carry Forward','Used','Bound to ERP')
        order by name for update
    """, execution.name, as_dict=True)
    touched_runs = set()
    total = 0
    for draw in draws:
        unused = flt(draw.remaining_qty)
        released = flt(draw.released_qty) + unused
        if abs(flt(draw.drawn_qty) - flt(draw.used_qty) - released) > TOLERANCE:
            frappe.throw(f"Material Draw {draw.name} quantities require reconciliation before release")
        status = ("Bound to ERP" if draw.status == "Bound to ERP" else
                  "Used" if flt(draw.used_qty) > TOLERANCE else "Released")
        frappe.db.set_value("CFG Kanban Operation Material Draw", draw.name, {
            "remaining_qty": 0, "released_qty": released, "status": status,
        }, update_modified=True)
        record("Unused Operation Material Released", cycle=cycle.name,
               execution=execution.name, handling_unit=draw.source_handling_unit,
               reference_doctype="CFG Kanban Operation Material Draw", reference_name=draw.name,
               qty=unused, previous_state=draw.status, new_state=status,
               work_order=draw.work_order, job_card=draw.job_card,
               operation=draw.operation, workstation=draw.workstation,
               operator=operator, operator_session=operator_session,
               terminal_user=terminal_user, notes=reason,
               payload={"drawn_qty": flt(draw.drawn_qty), "used_qty": flt(draw.used_qty),
                        "remaining_before": unused, "remaining_after": 0,
                        "released_qty": released},
               idempotency_key=canonical_key("unused-material-release", draw.name, released))
        touched_runs.add(draw.material_run)
        total += unused
    # Operator Complete can end a partial allocation with a prepared, unused next run.
    runs = frappe.get_all("CFG Kanban Operation Material Run", filters={
        "process_execution": execution.name, "status": "Open"},
        fields=["name", "progress"], limit_page_length=0)
    for run in runs:
        if run.progress:
            frappe.throw(f"Open Material Run {run.name} already has progress; reconcile it before closure")
        from cfg_kanban.services.operation_hoppers import cancel_run_hopper
        cancel_run_hopper(run.name, reason)
        frappe.db.set_value("CFG Kanban Operation Material Run", run.name, {
            "status": "Cancelled", "active_execution_key": None,
            "closed_on": now_datetime(), "cancelled_on": now_datetime(),
            "cancellation_reason": reason,
        }, update_modified=True)
        record("Unused Material Run Closed", cycle=cycle.name, execution=execution.name,
               reference_doctype="CFG Kanban Operation Material Run", reference_name=run.name,
               previous_state="Open", new_state="Cancelled", notes=reason,
               operator=operator, operator_session=operator_session, terminal_user=terminal_user,
               idempotency_key=canonical_key("closed-cycle-unused-run", run.name))
        touched_runs.add(run.name)
    if execution.open_material_run:
        frappe.db.set_value("CFG Kanban Process Execution", execution.name,
                            "open_material_run", None, update_modified=False)
    from cfg_kanban.services.operation_material_runs import _refresh_run_totals
    for name in sorted(touched_runs):
        _refresh_run_totals(frappe.get_doc("CFG Kanban Operation Material Run", name))
    return {"released_qty": total, "draw_count": len(draws)}


def release_closed_work_order(work_order, reason):
    """Final safeguard, scoped to completed Cycles belonging to this exact Work Order."""
    executions = frappe.db.sql("""
        select execution.name from `tabCFG Kanban Process Execution` execution
        inner join `tabCFG Kanban Cycle` cycle on cycle.name=execution.kanban_cycle
        where cycle.work_order=%s and cycle.status='Completed'
        order by execution.name
    """, work_order)
    return [release_closed_execution(row[0], reason) for row in executions]
