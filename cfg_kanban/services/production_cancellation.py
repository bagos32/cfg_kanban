import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, insert_once


CANCELLATION_DOCTYPE = "CFG Kanban Production Cancellation"
ACTIVE_CANCELLATION_STATES = (
    "Frozen",
    "Awaiting ERP Reversal",
    "Awaiting Physical Reconciliation",
    "Ready to Finalize",
)
ACTIVE_WIP_LOAD_STATES = (
    "Reserved",
    "Transfer Draft",
    "Ready",
    "In Use",
    "Consumption Pending ERP",
    "Consumption Draft",
    "Return Draft",
    "Exception",
)


@frappe.whitelist()
def preview_production_cancellation(cycle_name):
    """Return live blockers without changing production state."""
    _require_manager()
    cycle, master = _production_context(cycle_name)
    existing = frappe.db.get_value(CANCELLATION_DOCTYPE, {"kanban_cycle": cycle.name}, "name")
    dependencies, evidence = _assess(cycle)
    return {
        "cycle": cycle.name,
        "work_order": cycle.work_order,
        "existing_cancellation": existing,
        "dependencies": dependencies,
        "blocking_count": sum(1 for row in dependencies if row["blocking"]),
        "activity_evidence_count": len(evidence),
        "activity_evidence": evidence,
        "control_type": master.control_type,
    }


@frappe.whitelist()
def request_production_cancellation(cycle_name, reason_category, reason):
    """Freeze one production Cycle and create immutable cancellation control evidence."""
    _require_manager()
    reason = (reason or "").strip()
    if not reason:
        frappe.throw("A detailed production cancellation reason is required")
    allowed_categories = {
        "Mistaken Release", "Demand Withdrawn", "Material or Quality Issue",
        "Equipment or Capacity Issue", "Duplicate Production", "Other",
    }
    if reason_category not in allowed_categories:
        frappe.throw("Select a valid production cancellation reason category")
    frappe.db.sql("select name from `tabCFG Kanban Cycle` where name=%s for update", cycle_name)
    cycle, master = _production_context(cycle_name)
    existing = frappe.db.get_value(CANCELLATION_DOCTYPE, {"kanban_cycle": cycle.name}, "name")
    if existing:
        cancellation = frappe.get_doc(CANCELLATION_DOCTYPE, existing)
        if cancellation.status == "Completed":
            return _public_result(cancellation, duplicate=True)
        _refresh(cancellation, cycle)
        return _public_result(cancellation, duplicate=True)
    if cycle.status in ("Completed", "Cancelled"):
        frappe.throw(f"Cycle {cycle.name} is already {cycle.status}")

    card = frappe.get_doc("CFG Kanban Card", cycle.kanban_card) if cycle.kanban_card else None
    if card:
        frappe.db.sql("select name from `tabCFG Kanban Card` where name=%s for update", card.name)
        card.reload()
    if card and card.active_cycle != cycle.name:
        frappe.throw(
            f"Card {card.name} is not assigned to Cycle {cycle.name}. Refresh the production "
            "record before requesting cancellation."
        )
    related_cycles = _related_runtime_cycles(cycle)
    controlled_cycle_names = [cycle.name] + [row.name for row in related_cycles]
    executions = frappe.get_all(
        "CFG Kanban Process Execution",
        filters={"kanban_cycle": ["in", controlled_cycle_names]},
        fields=["name", "kanban_cycle", "status", "blocked", "job_card"],
        order_by="sequence asc, lane_sequence asc, creation asc",
    )
    cancellation = frappe.get_doc({
        "doctype": CANCELLATION_DOCTYPE,
        "status": "Frozen",
        "kanban_cycle": cycle.name,
        "kanban_signal": cycle.signal,
        "kanban_card": cycle.kanban_card,
        "kanban_master": cycle.kanban_master,
        "company": cycle.company or master.company,
        "item_code": cycle.item_code,
        "work_order": cycle.work_order,
        "reason_category": reason_category,
        "reason": reason,
        "previous_cycle_status": cycle.status,
        "previous_cycle_blocked": cint(cycle.blocked),
        "previous_card_state": card.current_state if card else None,
        "previous_card_blocked": cint(card.blocked) if card else 0,
        "previous_card_blocked_reason": card.blocked_reason if card else None,
        "execution_status_snapshot": frappe.as_json([
            {"name": row.name, "kanban_cycle": row.kanban_cycle,
             "status": row.status, "blocked": cint(row.blocked)}
            for row in executions
        ]),
        "requested_by": frappe.session.user,
        "requested_on": now_datetime(),
        "frozen_on": now_datetime(),
    }).insert(ignore_permissions=True)

    exception = frappe.get_doc({
        "doctype": "CFG Kanban Exception",
        "exception_type": "Controlled Production Cancellation",
        "severity": "Critical",
        "status": "Open",
        "kanban_cycle": cycle.name,
        "kanban_card": cycle.kanban_card,
        "message": f"Production cancellation {cancellation.name} is reconciling ERP and physical state",
        "reference_doctype": CANCELLATION_DOCTYPE,
        "reference_name": cancellation.name,
        "raised_on": now_datetime(),
    }).insert(ignore_permissions=True)
    cancellation.db_set("exception", exception.name, update_modified=False)
    cycle.db_set({
        "status": "Hold",
        "blocked": 1,
        "exception": exception.name,
        "production_cancellation": cancellation.name,
        "remarks": ((cycle.remarks or "") +
                    f"\nControlled cancellation requested: {reason}").strip(),
    }, update_modified=True)
    if card:
        previous_card_state = card.current_state
        card.db_set({
            "current_state": "Blocked",
            "blocked": 1,
            "blocked_reason": f"Controlled Production Cancellation {cancellation.name}",
        }, update_modified=True)
        event = record(
            "Card Frozen for Production Cancellation",
            card=card.name,
            cycle=cycle.name,
            previous_state=previous_card_state,
            new_state="Blocked",
            reference_doctype=CANCELLATION_DOCTYPE,
            reference_name=cancellation.name,
            notes=reason,
            system_generated=False,
            ignore_permissions=True,
        )
        card.db_set("last_event", event.name, update_modified=False)
    _freeze_executions(
        cycle,
        [row for row in executions if row.kanban_cycle == cycle.name],
        cancellation,
    )
    _freeze_related_runtime_cycles(
        related_cycles,
        executions,
        cancellation,
        exception.name,
    )
    if cycle.signal:
        frappe.db.set_value("CFG Kanban Signal", cycle.signal, {
            "status": "Blocked",
            "error_message": f"Controlled Production Cancellation {cancellation.name} is active",
        }, update_modified=True)
    _pause_open_job_card_timers(cycle, cancellation)
    cycle.reload()
    _refresh(cancellation, cycle)
    record(
        "Controlled Production Cancellation Requested",
        card=cycle.kanban_card,
        cycle=cycle.name,
        previous_state=cancellation.previous_cycle_status,
        new_state="Hold",
        reference_doctype=CANCELLATION_DOCTYPE,
        reference_name=cancellation.name,
        notes=f"{reason_category}: {reason}",
        system_generated=False,
        ignore_permissions=True,
    )
    return _public_result(cancellation)


@frappe.whitelist()
def refresh_production_cancellation(cancellation_name):
    _require_manager()
    cycle_name = frappe.db.get_value(CANCELLATION_DOCTYPE, cancellation_name, "kanban_cycle")
    if not cycle_name:
        frappe.throw("Production Cancellation record was not found")
    frappe.db.sql(
        "select name from `tabCFG Kanban Cycle` where name=%s for update", cycle_name
    )
    frappe.db.sql(
        "select name from `tabCFG Kanban Production Cancellation` where name=%s for update",
        cancellation_name,
    )
    cancellation = frappe.get_doc(CANCELLATION_DOCTYPE, cancellation_name)
    cancellation.check_permission("read")
    if cancellation.status == "Completed":
        return _public_result(cancellation)
    cycle = frappe.get_doc("CFG Kanban Cycle", cancellation.kanban_cycle)
    _refresh(cancellation, cycle)
    return _public_result(cancellation)


@frappe.whitelist()
def finalize_production_cancellation(cancellation_name, reconciliation_notes):
    """Finish only after ERPNext and physical control both prove no live production remains."""
    _require_manager()
    notes = (reconciliation_notes or "").strip()
    if not notes:
        frappe.throw("Final reconciliation evidence is required")
    cycle_name = frappe.db.get_value(CANCELLATION_DOCTYPE, cancellation_name, "kanban_cycle")
    if not cycle_name:
        frappe.throw("Production Cancellation record was not found")
    frappe.db.sql(
        "select name from `tabCFG Kanban Cycle` where name=%s for update", cycle_name
    )
    frappe.db.sql(
        "select name from `tabCFG Kanban Production Cancellation` where name=%s for update",
        cancellation_name,
    )
    cancellation = frappe.get_doc(CANCELLATION_DOCTYPE, cancellation_name)
    if cancellation.status == "Completed":
        return _public_result(cancellation, duplicate=True)
    cycle = frappe.get_doc("CFG Kanban Cycle", cancellation.kanban_cycle)
    card = None
    if cycle.kanban_card:
        frappe.db.sql(
            "select name from `tabCFG Kanban Card` where name=%s for update",
            cycle.kanban_card,
        )
        card = frappe.get_doc("CFG Kanban Card", cycle.kanban_card)
        if card.active_cycle != cycle.name:
            frappe.throw(
                f"Card {card.name} is now assigned to Cycle {card.active_cycle or '-'}; "
                f"it cannot be released by cancellation of Cycle {cycle.name}."
            )
    _refresh(cancellation, cycle)
    cancellation.reload()
    if cancellation.status != "Ready to Finalize" or cint(cancellation.blocking_count):
        frappe.throw(
            "Production cancellation is not ready. Refresh Assessment and resolve every blocking "
            "ERP or physical dependency first."
        )
    if cycle.get("production_cancellation") != cancellation.name:
        frappe.throw("The Kanban Cycle no longer identifies this cancellation control record")
    related_cycles = frappe.get_all(
        "CFG Kanban Cycle",
        filters={
            "production_cancellation": cancellation.name,
            "name": ["!=", cycle.name],
        },
        pluck="name",
        order_by="name asc",
    )
    for related_cycle_name in related_cycles:
        _finalize_related_runtime_cycle(
            related_cycle_name, cancellation, notes
        )

    executions = frappe.get_all(
        "CFG Kanban Process Execution", filters={"kanban_cycle": cycle.name}, pluck="name"
    )
    for execution_name in executions:
        frappe.db.set_value("CFG Kanban Process Execution", execution_name, {
            "status": "Cancelled", "blocked": 0,
        }, update_modified=True)
        if frappe.db.table_exists("CFG Kanban Dispatch Queue"):
            queue_name = frappe.db.get_value(
                "CFG Kanban Dispatch Queue", {"process_execution": execution_name}, "name"
            )
            if queue_name:
                frappe.db.set_value(
                    "CFG Kanban Dispatch Queue", queue_name,
                    {
                        "dispatch_status": "Cancelled",
                        "readiness": "Controlled Production Cancellation completed",
                    },
                    update_modified=True,
                )
        from cfg_kanban.services.job_participation import close_execution_participation
        close_execution_participation(
            execution_name,
            source_event="Controlled Production Cancellation",
            reason=notes,
        )
    for summary_name in frappe.get_all(
            "CFG Kanban Operation Summary", filters={"kanban_cycle": cycle.name}, pluck="name"):
        frappe.db.set_value(
            "CFG Kanban Operation Summary", summary_name, "status", "Cancelled",
            update_modified=False,
        )
    for allocation_name in frappe.get_all(
            "CFG Kanban Runtime Allocation",
            filters={"kanban_cycle": cycle.name, "status": ["!=", "Cancelled"]},
            pluck="name"):
        frappe.db.set_value(
            "CFG Kanban Runtime Allocation", allocation_name,
            {"status": "Cancelled", "completed_on": now_datetime(), "notes": notes},
            update_modified=False,
        )
    for task_name in frappe.get_all(
            "CFG Kanban Process Task",
            filters={
                "kanban_cycle": cycle.name,
                "status": ["not in", ["Completed", "Cancelled", "Expired"]],
            },
            pluck="name"):
        frappe.db.set_value(
            "CFG Kanban Process Task", task_name,
            {"status": "Cancelled", "blocked": 0}, update_modified=False,
        )
    from cfg_kanban.services.job_ownership import close_cycle_ownership
    from cfg_kanban.services.runtime_roles import close_cycle_role_assignments
    close_cycle_ownership(cycle, "Controlled production cancellation completed")
    close_cycle_role_assignments(cycle, "Controlled production cancellation completed")

    previous_cycle_state = cycle.status
    cycle.db_set({
        "status": "Cancelled",
        "blocked": 0,
        "completed_on": now_datetime(),
        "remarks": ((cycle.remarks or "") +
                    f"\nCancellation finalized: {notes}").strip(),
    }, update_modified=True)
    if cycle.signal:
        frappe.db.set_value("CFG Kanban Signal", cycle.signal, {
            "status": "Cancelled",
            "cancelled_on": now_datetime(),
            "cancelled_by": frappe.session.user,
            "cancellation_reason": cancellation.reason,
            "error_message": None,
        }, update_modified=True)
    if card:
        previous_card_state = card.current_state
        card.db_set({
            "current_state": "Available",
            "active_cycle": None,
            "blocked": 0,
            "blocked_reason": None,
        }, update_modified=True)
        event = record(
            "Card Released after Controlled Production Cancellation",
            card=card.name,
            cycle=cycle.name,
            previous_state=previous_card_state,
            new_state="Available",
            reference_doctype=CANCELLATION_DOCTYPE,
            reference_name=cancellation.name,
            notes=notes,
            system_generated=False,
            ignore_permissions=True,
        )
        card.db_set("last_event", event.name, update_modified=False)
    cancellation.db_set({
        "status": "Completed",
        "blocking_count": 0,
        "reconciliation_notes": notes,
        "finalized_by": frappe.session.user,
        "finalized_on": now_datetime(),
        "assessment_summary": "ERP and physical dependencies resolved; Kanban cancellation finalized.",
    }, update_modified=True)
    if cancellation.exception:
        frappe.db.set_value("CFG Kanban Exception", cancellation.exception, {
            "status": "Resolved",
            "resolved_on": now_datetime(),
            "resolved_by": frappe.session.user,
            "resolution": notes,
        }, update_modified=True)
    record(
        "Controlled Production Cancellation Completed",
        card=cycle.kanban_card,
        cycle=cycle.name,
        previous_state=previous_cycle_state,
        new_state="Cancelled",
        reference_doctype=CANCELLATION_DOCTYPE,
        reference_name=cancellation.name,
        notes=notes,
        system_generated=False,
        ignore_permissions=True,
    )
    cancellation.reload()
    return _public_result(cancellation)


def assert_cycle_not_under_cancellation(cycle_name):
    if not cycle_name:
        return
    name = frappe.db.get_value("CFG Kanban Cycle", cycle_name, "production_cancellation")
    if name:
        status = frappe.db.get_value(CANCELLATION_DOCTYPE, name, "status")
        if status not in ACTIVE_CANCELLATION_STATES:
            name = None
    if not name:
        name = frappe.db.get_value(
            CANCELLATION_DOCTYPE,
            {"kanban_cycle": cycle_name, "status": ["in", ACTIVE_CANCELLATION_STATES]},
            "name",
        )
    if name:
        frappe.throw(
            f"Production is frozen by Controlled Production Cancellation {name}. "
            "Resolve or finalize that record before further floor execution."
        )


def _production_context(cycle_name):
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    cycle.check_permission("read")
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    if master.control_type != "Production":
        frappe.throw("Controlled Production Cancellation is only for Production Kanban Cycles")
    if not cycle.work_order:
        frappe.throw("This production Cycle has no effective Work Order")
    return cycle, master


def _freeze_executions(cycle, executions, cancellation):
    from cfg_kanban.services.job_participation import close_execution_participation

    for row in executions:
        if row.status in ("Completed", "Cancelled"):
            continue
        frappe.db.set_value("CFG Kanban Process Execution", row.name, {
            "status": "Blocked", "blocked": 1,
        }, update_modified=True)
        queue = frappe.db.get_value(
            "CFG Kanban Dispatch Queue", {"process_execution": row.name}, "name"
        ) if frappe.db.table_exists("CFG Kanban Dispatch Queue") else None
        if queue:
            frappe.db.set_value("CFG Kanban Dispatch Queue", queue, {
                "dispatch_status": "Blocked",
                "readiness": "Controlled Production Cancellation",
                "notes": cancellation.reason,
            }, update_modified=True)
        close_execution_participation(
            row.name,
            source_event="Production Cancellation Freeze",
            reason=cancellation.reason,
        )


def _related_runtime_cycles(cycle):
    if not cycle.work_order:
        return []
    rows = frappe.get_all(
        "CFG Kanban Cycle",
        filters={
            "work_order": cycle.work_order,
            "name": ["!=", cycle.name],
            "runtime_allocation": ["is", "set"],
            "status": ["!=", "Cancelled"],
        },
        fields=["name", "kanban_card", "signal", "status", "remarks"],
        order_by="creation asc",
    )
    result = []
    for row in rows:
        if not row.kanban_card:
            continue
        active_cycle = frappe.db.get_value("CFG Kanban Card", row.kanban_card, "active_cycle")
        if active_cycle == row.name:
            result.append(row)
    return result


def _freeze_related_runtime_cycles(cycles, executions, cancellation, exception_name):
    for row in cycles:
        frappe.db.sql(
            "select name from `tabCFG Kanban Cycle` where name=%s for update", row.name
        )
        related = frappe.get_doc("CFG Kanban Cycle", row.name)
        frappe.db.sql(
            "select name from `tabCFG Kanban Card` where name=%s for update",
            related.kanban_card,
        )
        card = frappe.get_doc("CFG Kanban Card", related.kanban_card)
        if card.active_cycle != related.name:
            frappe.throw(
                f"Related operation Card {card.name} no longer owns Cycle {related.name}"
            )
        previous_cycle_state = related.status
        previous_card_state = card.current_state
        related.db_set({
            "status": "Hold",
            "blocked": 1,
            "exception": exception_name,
            "production_cancellation": cancellation.name,
            "remarks": ((related.remarks or "") +
                        f"\nFrozen with production cancellation {cancellation.name}").strip(),
        }, update_modified=True)
        card.db_set({
            "current_state": "Blocked",
            "blocked": 1,
            "blocked_reason": f"Controlled Production Cancellation {cancellation.name}",
        }, update_modified=True)
        _freeze_executions(
            related,
            [execution for execution in executions
             if execution.kanban_cycle == related.name],
            cancellation,
        )
        if related.signal:
            frappe.db.set_value("CFG Kanban Signal", related.signal, {
                "status": "Blocked",
                "error_message": f"Controlled Production Cancellation {cancellation.name} is active",
            }, update_modified=True)
        record(
            "Related Operation Cycle Frozen for Production Cancellation",
            card=card.name,
            cycle=related.name,
            previous_state=previous_cycle_state,
            new_state="Hold",
            reference_doctype=CANCELLATION_DOCTYPE,
            reference_name=cancellation.name,
            notes=f"Card state {previous_card_state} frozen with Work Order {cancellation.work_order}",
            system_generated=False,
            ignore_permissions=True,
        )


def _finalize_related_runtime_cycle(cycle_name, cancellation, notes):
    frappe.db.sql(
        "select name from `tabCFG Kanban Cycle` where name=%s for update", cycle_name
    )
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    card = None
    if cycle.kanban_card:
        frappe.db.sql(
            "select name from `tabCFG Kanban Card` where name=%s for update",
            cycle.kanban_card,
        )
        card = frappe.get_doc("CFG Kanban Card", cycle.kanban_card)
        if card.active_cycle != cycle.name:
            frappe.throw(
                f"Related operation Card {card.name} is now assigned to "
                f"{card.active_cycle or '-'}; cancellation cannot release it."
            )
    executions = frappe.get_all(
        "CFG Kanban Process Execution", filters={"kanban_cycle": cycle.name}, pluck="name"
    )
    for execution_name in executions:
        frappe.db.set_value(
            "CFG Kanban Process Execution", execution_name,
            {"status": "Cancelled", "blocked": 0}, update_modified=True,
        )
        if frappe.db.table_exists("CFG Kanban Dispatch Queue"):
            queue_name = frappe.db.get_value(
                "CFG Kanban Dispatch Queue", {"process_execution": execution_name}, "name"
            )
            if queue_name:
                frappe.db.set_value(
                    "CFG Kanban Dispatch Queue", queue_name,
                    {"dispatch_status": "Cancelled",
                     "readiness": "Controlled Production Cancellation completed"},
                    update_modified=True,
                )
        from cfg_kanban.services.job_participation import close_execution_participation
        close_execution_participation(
            execution_name,
            source_event="Related Operation Production Cancellation",
            reason=notes,
        )
    for summary_name in frappe.get_all(
            "CFG Kanban Operation Summary", filters={"kanban_cycle": cycle.name}, pluck="name"):
        frappe.db.set_value(
            "CFG Kanban Operation Summary", summary_name, "status", "Cancelled",
            update_modified=False,
        )
    for allocation_name in frappe.get_all(
            "CFG Kanban Runtime Allocation", filters={"kanban_cycle": cycle.name}, pluck="name"):
        frappe.db.set_value(
            "CFG Kanban Runtime Allocation", allocation_name,
            {"status": "Cancelled", "completed_on": now_datetime(), "notes": notes},
            update_modified=False,
        )
    for task_name in frappe.get_all(
            "CFG Kanban Process Task",
            filters={"kanban_cycle": cycle.name,
                     "status": ["not in", ["Completed", "Cancelled", "Expired"]]},
            pluck="name"):
        frappe.db.set_value(
            "CFG Kanban Process Task", task_name,
            {"status": "Cancelled", "blocked": 0}, update_modified=False,
        )
    from cfg_kanban.services.job_ownership import close_cycle_ownership
    from cfg_kanban.services.runtime_roles import close_cycle_role_assignments
    close_cycle_ownership(cycle, "Related production Cycle cancelled")
    close_cycle_role_assignments(cycle, "Related production Cycle cancelled")
    previous_cycle_state = cycle.status
    cycle.db_set({
        "status": "Cancelled", "blocked": 0, "completed_on": now_datetime(),
        "remarks": ((cycle.remarks or "") +
                    f"\nCancelled with {cancellation.name}: {notes}").strip(),
    }, update_modified=True)
    if cycle.signal:
        frappe.db.set_value("CFG Kanban Signal", cycle.signal, {
            "status": "Cancelled",
            "cancelled_on": now_datetime(),
            "cancelled_by": frappe.session.user,
            "cancellation_reason": cancellation.reason,
            "error_message": None,
        }, update_modified=True)
    if card:
        previous_card_state = card.current_state
        card.db_set({
            "current_state": "Available", "active_cycle": None,
            "blocked": 0, "blocked_reason": None,
        }, update_modified=True)
        event = record(
            "Related Operation Card Released after Production Cancellation",
            card=card.name,
            cycle=cycle.name,
            previous_state=previous_card_state,
            new_state="Available",
            reference_doctype=CANCELLATION_DOCTYPE,
            reference_name=cancellation.name,
            notes=notes,
            system_generated=False,
            ignore_permissions=True,
        )
        card.db_set("last_event", event.name, update_modified=False)
    record(
        "Related Operation Cycle Cancelled with Production",
        card=cycle.kanban_card,
        cycle=cycle.name,
        previous_state=previous_cycle_state,
        new_state="Cancelled",
        reference_doctype=CANCELLATION_DOCTYPE,
        reference_name=cancellation.name,
        notes=notes,
        system_generated=False,
        ignore_permissions=True,
    )


def _pause_open_job_card_timers(cycle, cancellation):
    if not cycle.work_order:
        return
    jobs = frappe.get_all(
        "Job Card",
        filters={"work_order": cycle.work_order, "docstatus": 0, "status": "Work In Progress"},
        pluck="name",
    )
    for job_card in jobs:
        if not frappe.db.exists("Job Card Time Log", {"parent": job_card, "to_time": ["is", "not set"]}):
            continue
        execution = frappe.db.get_value(
            "CFG Kanban Process Execution",
            {"kanban_cycle": cycle.name, "job_card": job_card},
            "name",
        )
        key = canonical_key("production-cancellation-pause", cancellation.name, job_card)
        command, created = insert_once(frappe.get_doc({
            "doctype": "CFG ERP Command",
            "command_type": "Pause Job Card",
            "source_signal": cycle.signal,
            "kanban_cycle": cycle.name,
            "process_execution": execution,
            "status": "Pending",
            "target_doctype": "Job Card",
            "request_payload": frappe.as_json({
                "job_card": job_card,
                "paused_on": now_datetime(),
                "reason": cancellation.reason,
                "production_cancellation": cancellation.name,
            }),
            "requested_on": now_datetime(),
            "created_by_system": 1,
        }), key, ignore_permissions=True)
        if created or command.status != "Completed":
            from cfg_kanban.integrations.erp_gateway import execute_command
            try:
                execute_command(command.name)
            except Exception:
                # The cancellation freeze is the primary safety action. A timer that ERPNext
                # cannot pause remains a visible blocking dependency and must not roll back the
                # freeze itself.
                frappe.log_error(
                    frappe.get_traceback(),
                    f"Production cancellation could not pause Job Card {job_card}",
                )


def _refresh(cancellation, cycle):
    dependencies, evidence = _assess(cycle)
    erp_blockers = [row for row in dependencies if row["blocking"] and row["category"] == "ERP"]
    physical_blockers = [
        row for row in dependencies if row["blocking"] and row["category"] == "Physical"
    ]
    status = (
        "Awaiting ERP Reversal" if erp_blockers else
        "Awaiting Physical Reconciliation" if physical_blockers else
        "Ready to Finalize"
    )
    cancellation.set("dependencies", [])
    for sequence, row in enumerate(dependencies, 1):
        cancellation.append("dependencies", {"sequence": sequence, **row})
    cancellation.status = status
    cancellation.erp_reversal_required = bool(erp_blockers)
    cancellation.physical_reconciliation_required = bool(physical_blockers)
    cancellation.blocking_count = len(erp_blockers) + len(physical_blockers)
    cancellation.activity_evidence_count = len(evidence)
    cancellation.last_assessed_on = now_datetime()
    cancellation.assessment_summary = _assessment_summary(
        status, erp_blockers, physical_blockers, evidence
    )
    cancellation.flags.controlled_update = True
    cancellation.flags.ignore_permissions = True
    cancellation.save()


def _assess(cycle):
    dependencies = []
    evidence = []
    if cycle.get("production_cancellation"):
        related_runtime_cycles = frappe.get_all(
            "CFG Kanban Cycle",
            filters={
                "production_cancellation": cycle.production_cancellation,
                "name": ["!=", cycle.name],
            },
            fields=["name", "status", "kanban_card", "selected_job_card"],
            order_by="creation asc",
        )
        for related in related_runtime_cycles:
            dependencies.append(_dependency(
                "Kanban Scope", "CFG Kanban Cycle", related.name, related.status,
                "This related Process/Station Card Cycle is frozen and will close with the "
                "main production cancellation.",
                details=(f"Card {related.kanban_card or '-'} · "
                         f"Job Card {related.selected_job_card or '-'}"),
                blocking=0,
                resolved=1,
            ))
            evidence.append(
                f"Related runtime Cycle {related.name}: Card {related.kanban_card or '-'}"
            )
    work_order = frappe.get_doc("Work Order", cycle.work_order) if (
        cycle.work_order and frappe.db.exists("Work Order", cycle.work_order)
    ) else None
    if work_order and work_order.docstatus != 2:
        dependencies.append(_dependency(
            "ERP", "Work Order", work_order.name,
            _doc_state(work_order),
            "Cancel the Work Order in ERPNext after its Stock Entries and Job Cards are reversed.",
        ))

    jobs = frappe.get_all(
        "Job Card",
        filters={"work_order": cycle.work_order},
        fields=["name", "status", "docstatus", "total_completed_qty"],
        order_by="creation asc",
    ) if cycle.work_order else []
    for job in jobs:
        open_timers = frappe.db.count(
            "Job Card Time Log", {"parent": job.name, "to_time": ["is", "not set"]}
        )
        if open_timers:
            dependencies.append(_dependency(
                "ERP", "Job Card", job.name, f"{job.status}; active timer",
                "Pause the active Job Card timer before ERP cancellation.",
                details=f"{open_timers} open time log(s)",
            ))
        if job.docstatus != 2 and (job.status not in ("Open", "Cancelled") or
                                   flt(job.total_completed_qty) > 0):
            dependencies.append(_dependency(
                "ERP", "Job Card", job.name, _row_state(job),
                "Cancel this Job Card through ERPNext as part of Work Order reversal.",
                quantity=job.total_completed_qty,
            ))
        if flt(job.total_completed_qty) > 0:
            evidence.append(f"Job Card {job.name}: {job.total_completed_qty} completed")

    stock_entries = _production_stock_entries(cycle)
    purpose_rank = {
        "Manufacture": 10,
        "Material Consumption for Manufacture": 20,
        "Material Transfer for Manufacture": 30,
    }
    stock_entries.sort(key=lambda row: (
        purpose_rank.get(row.purpose or row.stock_entry_type, 25), row.creation or ""
    ))
    for entry in stock_entries:
        if entry.docstatus == 2:
            continue
        action = (
            "Cancel this submitted Stock Entry in ERPNext; its cancellation hooks will reverse "
            "Kanban trace and create any required physical reconciliation."
            if entry.docstatus == 1 else
            "Discard this Draft Stock Entry after verifying that it was never physically posted."
        )
        dependencies.append(_dependency(
            "ERP", "Stock Entry", entry.name,
            f"{entry.purpose or entry.stock_entry_type or 'Stock Entry'} · {_row_state(entry)}",
            action,
            quantity=entry.fg_completed_qty,
        ))
        evidence.append(
            f"Stock Entry {entry.name}: {entry.purpose or entry.stock_entry_type} "
            f"({_doc_state(entry)})"
        )

    active_loads = frappe.get_all(
        "CFG Kanban WIP Bin Load",
        filters={"work_order": cycle.work_order, "status": ["in", list(ACTIVE_WIP_LOAD_STATES)]},
        fields=["name", "status", "reusable_bin", "item_code", "actual_qty", "stock_uom"],
        order_by="creation asc",
    ) if cycle.work_order and frappe.db.table_exists("CFG Kanban WIP Bin Load") else []
    for load in active_loads:
        dependencies.append(_dependency(
            "Physical", "CFG Kanban WIP Bin Load", load.name, load.status,
            "Reconcile this exact WIP Bin after the related ERP Stock Entry is cancelled.",
            quantity=load.actual_qty,
            details=f"{load.reusable_bin} · {load.item_code} · {load.stock_uom}",
        ))

    reconciliations = frappe.get_all(
        "CFG Kanban WIP Bin Reconciliation",
        filters={"work_order": cycle.work_order, "status": "Open"},
        fields=["name", "status", "reusable_bin", "item_code", "qty", "stock_uom"],
        order_by="creation asc",
    ) if cycle.work_order and frappe.db.table_exists("CFG Kanban WIP Bin Reconciliation") else []
    for reconciliation in reconciliations:
        dependencies.append(_dependency(
            "Physical", "CFG Kanban WIP Bin Reconciliation", reconciliation.name,
            reconciliation.status,
            "Resolve this exact-bin reconciliation with physical verification and Supervisor authority.",
            quantity=reconciliation.qty,
            details=(f"{reconciliation.reusable_bin} · {reconciliation.item_code} · "
                     f"{reconciliation.stock_uom}"),
        ))

    cycle_names = frappe.get_all(
        "CFG Kanban Cycle", filters={"work_order": cycle.work_order}, pluck="name"
    ) if cycle.work_order else [cycle.name]
    units = frappe.get_all(
        "CFG Kanban Handling Unit",
        filters={"kanban_cycle": ["in", cycle_names or [cycle.name]]},
        fields=["name", "handling_unit_id", "identity_state", "movement_state",
                "item_code", "current_qty", "reserved_qty", "stock_uom"],
        order_by="creation asc",
    ) if frappe.db.table_exists("CFG Kanban Handling Unit") else []
    for unit in units:
        live_qty = max(flt(unit.current_qty), 0) + max(flt(unit.reserved_qty), 0)
        if live_qty <= 0.000001 or unit.identity_state in ("Empty", "Void", "Replaced", "Unused"):
            continue
        dependencies.append(_dependency(
            "Physical", "CFG Kanban Handling Unit", unit.name,
            f"{unit.identity_state} · {unit.movement_state}",
            "Reverse or reconcile this production output identity before releasing the Card.",
            quantity=live_qty,
            details=f"{unit.handling_unit_id or unit.name} · {unit.item_code} · {unit.stock_uom}",
        ))

    progress_count = frappe.db.count(
        "CFG Kanban Operation Progress", {"kanban_cycle": cycle.name}
    )
    if progress_count:
        evidence.append(f"{progress_count} immutable Kanban Operation Progress record(s)")
    wip_count = frappe.db.count("CFG Kanban WIP Ledger", {"kanban_cycle": cycle.name})
    if wip_count:
        evidence.append(f"{wip_count} immutable Kanban WIP Ledger record(s)")
    return dependencies, evidence


def _production_stock_entries(cycle):
    if not cycle.work_order:
        return []
    return frappe.db.sql(
        """
        select distinct name, purpose, stock_entry_type, docstatus, fg_completed_qty, creation
        from `tabStock Entry`
        where name is not null
          and (cfg_kanban_cycle=%s or (work_order=%s and cfg_kanban_controlled=1))
        order by creation asc
        """,
        (cycle.name, cycle.work_order),
        as_dict=True,
    )


def _dependency(category, doctype, name, state, action, quantity=0, details=None,
                blocking=1, resolved=0):
    return {
        "category": category,
        "reference_doctype": doctype,
        "reference_name": name,
        "current_state": state,
        "quantity": flt(quantity),
        "blocking": cint(blocking),
        "resolved": cint(resolved),
        "required_action": action,
        "details": details,
    }


def _doc_state(doc):
    return {0: "Draft", 1: "Submitted", 2: "Cancelled"}.get(cint(doc.docstatus), "Unknown")


def _row_state(row):
    return f"{row.status or '-'} · " + {0: "Draft", 1: "Submitted", 2: "Cancelled"}.get(
        cint(row.docstatus), "Unknown"
    )


def _assessment_summary(status, erp_blockers, physical_blockers, evidence):
    if status == "Ready to Finalize":
        prefix = "No live ERP or physical production dependency remains."
    elif erp_blockers:
        prefix = f"Resolve {len(erp_blockers)} ERP dependency/dependencies in the listed order."
    else:
        prefix = f"Resolve {len(physical_blockers)} physical dependency/dependencies."
    preserved = (
        f" {len(evidence)} activity evidence line(s) remain preserved for audit."
        if evidence else ""
    )
    return prefix + preserved


def _public_result(cancellation, duplicate=False):
    cancellation.reload()
    return {
        "name": cancellation.name,
        "status": cancellation.status,
        "cycle": cancellation.kanban_cycle,
        "work_order": cancellation.work_order,
        "blocking_count": cint(cancellation.blocking_count),
        "erp_reversal_required": bool(cint(cancellation.erp_reversal_required)),
        "physical_reconciliation_required": bool(
            cint(cancellation.physical_reconciliation_required)
        ),
        "assessment_summary": cancellation.assessment_summary,
        "duplicate": duplicate,
    }


def _require_manager():
    if not set(frappe.get_roles()).intersection({"Manufacturing Manager", "System Manager"}):
        frappe.throw(
            _("Manufacturing Manager or System Manager role is required"),
            frappe.PermissionError,
        )
