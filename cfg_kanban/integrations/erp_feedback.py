import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.operation_summary import (ensure_summary, ready_executions,
                                                    ready_next_sequential_lane, recalculate,
                                                    refresh_destination)
from cfg_kanban.services.state_machine import set_cycle_state, transition_card


EMPTY_LINK_VALUES = {"", "none", "null", "undefined"}


def _link_value(value):
    """Return a usable Link value without accepting browser/string null markers."""
    if value is None:
        return None
    value = str(value).strip()
    return None if value.lower() in EMPTY_LINK_VALUES else value


def _cycle_for_work_order(work_order):
    work_order = _link_value(work_order)
    if not work_order:
        return None
    cycle = _link_value(
        frappe.db.get_value("Work Order", work_order, "cfg_kanban_cycle")
    )
    if cycle:
        return cycle
    # Recovery path for older records where only Cycle.work_order was populated.
    return _link_value(
        frappe.db.get_value("CFG Kanban Cycle", {"work_order": work_order}, "name")
    )


def _cycle(doc):
    cycle = _link_value(getattr(doc, "cfg_kanban_cycle", None))
    if cycle:
        return cycle
    if getattr(doc, "doctype", None) != "Stock Entry":
        return None

    # ERPNext creates consumption/transfer entries from either a Job Card or its
    # Work Order and does not consistently copy custom fields between versions.
    # Both documents are audited bridges back to the owning Kanban Cycle.
    work_order = _link_value(getattr(doc, "work_order", None))
    job_card = (
        _link_value(getattr(doc, "cfg_kanban_job_card", None))
        or _link_value(getattr(doc, "job_card", None))
    )
    if job_card:
        job_context = frappe.db.get_value(
            "Job Card", job_card, ["cfg_kanban_cycle", "work_order"], as_dict=True
        )
        if job_context:
            cycle = _link_value(job_context.cfg_kanban_cycle)
            if cycle:
                return cycle
            work_order = work_order or _link_value(job_context.work_order)
    if work_order:
        return _cycle_for_work_order(work_order)
    return None


def prepare_stock_entry(doc, method=None):
    """Attach ERPNext-generated production Stock Entries to their Kanban Cycle.

    This runs before Link validation so a Material Consumption Stock Entry made
    from a Job Card cannot persist the literal text ``None`` as a Cycle link.
    Unrelated ERPNext Stock Entries remain untouched.
    """
    for fieldname in ("cfg_kanban_cycle", "cfg_kanban_signal", "cfg_kanban_job_card"):
        if doc.meta.has_field(fieldname) and not _link_value(doc.get(fieldname)):
            doc.set(fieldname, None)

    cycle_name = _cycle(doc)
    if not cycle_name:
        return
    if not frappe.db.exists("CFG Kanban Cycle", cycle_name):
        frappe.throw(f"CFG Kanban Cycle {cycle_name} linked to this Stock Entry was not found")

    cycle = frappe.db.get_value(
        "CFG Kanban Cycle", cycle_name, ["name", "signal", "work_order"], as_dict=True
    )
    if doc.get("work_order") and cycle.work_order and doc.work_order != cycle.work_order:
        frappe.throw(
            f"Stock Entry Work Order {doc.work_order} does not belong to "
            f"CFG Kanban Cycle {cycle.name}"
        )
    doc.cfg_kanban_cycle = cycle.name
    doc.cfg_kanban_controlled = 1
    if doc.meta.has_field("cfg_kanban_signal"):
        doc.cfg_kanban_signal = cycle.signal or None


@frappe.whitelist()
def get_stock_entry_kanban_context(work_order=None, job_card=None):
    """Expose the audited production context to a newly mapped Stock Entry form."""
    work_order = _link_value(work_order)
    job_card = _link_value(job_card)
    if job_card:
        job = frappe.get_doc("Job Card", job_card)
        job.check_permission("read")
        work_order = work_order or _link_value(job.work_order)
    if not work_order:
        return {}

    work_order_doc = frappe.get_doc("Work Order", work_order)
    work_order_doc.check_permission("read")
    cycle_name = _cycle_for_work_order(work_order_doc.name)
    if not cycle_name:
        return {}
    cycle = frappe.db.get_value(
        "CFG Kanban Cycle", cycle_name,
        ["name", "signal", "kanban_card", "status"], as_dict=True,
    )
    if not cycle:
        frappe.throw(f"CFG Kanban Cycle {cycle_name} linked to Work Order {work_order} was not found")
    return {
        "cfg_kanban_controlled": 1,
        "cfg_kanban_cycle": cycle.name,
        "cfg_kanban_signal": cycle.signal,
        "kanban_card": cycle.kanban_card,
        "cycle_status": cycle.status,
    }


def prepare_work_order(doc, method=None):
    """Prevent a submitted Kanban Work Order that can never produce Job Cards."""
    if not _cycle(doc) or doc.operations:
        return
    cycle = frappe.get_doc("CFG Kanban Cycle", doc.cfg_kanban_cycle)
    if cycle.work_order and cycle.work_order != doc.name:
        frappe.throw(f"Kanban Cycle {cycle.name} already uses Work Order {cycle.work_order}. "
                     "One cycle cannot control two Work Orders.")
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    frappe.throw(f"Kanban Work Order has no ERPNext operation rows. Enable With Operations and "
                 f"configure operations on BOM {master.bom}; Kanban operation profiles control "
                 "handoff behavior but do not replace the ERPNext BOM route.")


def on_work_order_update(doc, method=None):
    if not _cycle(doc):
        return
    cycle = frappe.get_doc("CFG Kanban Cycle", doc.cfg_kanban_cycle)
    if cycle.work_order and cycle.work_order != doc.name:
        return
    if cycle.status == "Completed":
        return
    _sync_job_cards(doc, cycle)
    if doc.docstatus == 1 and doc.status == "Not Started":
        _mark_released(cycle, doc)
    elif doc.status in ("In Process", "Started"):
        set_cycle_state(cycle, "In Production", event_type="Work Order Started",
                        reference_doctype=doc.doctype, reference_name=doc.name)
        if cycle.kanban_card:
            transition_card(cycle.kanban_card, "In Production", event_type="Production Started", cycle=cycle.name)
    elif doc.status == "Completed":
        set_cycle_state(cycle, "Production Complete", event_type="Work Order Completed",
                        reference_doctype=doc.doctype, reference_name=doc.name)
        reconcile_physical_production_cycle(
            cycle.name, reference_doctype=doc.doctype, reference_name=doc.name
        )


def _mark_released(cycle, work_order):
    if cycle.status in ("New", "Signalled"):
        set_cycle_state(cycle, "Released", event_type="Work Order Submitted",
            reference_doctype=work_order.doctype, reference_name=work_order.name)
    if not cycle.kanban_card:
        return
    card = frappe.get_doc("CFG Kanban Card", cycle.kanban_card)
    next_states = {"Consumed": "Signal Created", "Signal Created": "Replenishment Requested",
                   "Replenishment Requested": "Production Released"}
    while card.current_state in next_states:
        target = next_states[card.current_state]
        transition_card(card, target, event_type="Work Order Submission Reconciliation",
                        cycle=cycle.name)
        card.reload()


@frappe.whitelist()
def reconcile_work_order(work_order_name):
    work_order = frappe.get_doc("Work Order", work_order_name)
    work_order.check_permission("read")
    if not _cycle(work_order):
        frappe.throw("This Work Order is not linked to a CFG Kanban Cycle")
    cycle = frappe.get_doc("CFG Kanban Cycle", work_order.cfg_kanban_cycle)
    if _runtime_card(cycle) and not cycle.runtime_allocation:
        frappe.throw("Process and Station cards must select a Job Card through the Operator runtime "
                     "allocation flow. Do not synchronize the complete Work Order to this Cycle. "
                     "Use Release Legacy Runtime Card on the Cycle if it was previously reconciled.")
    if cycle.work_order and cycle.work_order != work_order.name:
        frappe.throw(f"Cycle {cycle.name} identifies {cycle.work_order} as its effective Work Order. "
                     "Use Resolve Effective Work Order on the Cycle before synchronizing this one.")
    if work_order.docstatus == 1:
        _mark_released(cycle, work_order)
    job_count = frappe.db.count("Job Card", {"work_order": work_order.name,
                                              "docstatus": ["<", 2]})
    if not job_count:
        if not work_order.operations:
            frappe.throw("No Job Cards exist because this submitted Work Order has no operation rows. "
                         "Cancel and amend it after deploying this fix, or create a new Kanban cycle.")
        frappe.throw("ERPNext has not created Job Cards for the Work Order operations. "
                     "Use the Work Order Create Job Card action, then run Sync Kanban again.")
    _sync_job_cards(work_order, cycle)
    return {"work_order": work_order.name, "job_cards": job_count,
            "cycle": cycle.name, "card": cycle.kanban_card}


@frappe.whitelist()
def select_effective_work_order(cycle_name, work_order_name, reason):
    """Resolve legacy cycles that were accidentally linked to more than one Work Order."""
    frappe.only_for(("Manufacturing Manager", "System Manager"))
    if not (reason or "").strip():
        frappe.throw("A reconciliation reason is required")
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    cycle.check_permission("write")
    if _runtime_card(cycle):
        frappe.throw("Process and Station cards select Job Cards through the Operator runtime "
                     "allocation flow. Release the legacy Cycle first instead of resolving its Work Order.")
    selected = frappe.get_doc("Work Order", work_order_name)
    if selected.production_item != cycle.item_code or selected.docstatus != 1:
        frappe.throw("The effective Work Order must be submitted and match the Cycle item")
    job_count = frappe.db.count("Job Card", {"work_order": selected.name, "docstatus": ["<", 2]})
    if not job_count:
        frappe.throw("Select the submitted Work Order that has valid Job Cards")
    previous = cycle.work_order
    if previous and previous != selected.name:
        _detach_inactive_work_order(previous, cycle)
    frappe.db.set_value("Work Order", selected.name, {
        "cfg_kanban_controlled": 1, "cfg_kanban_cycle": cycle.name,
        "cfg_kanban_signal": cycle.signal,
    }, update_modified=False)
    cycle.db_set("work_order", selected.name, update_modified=True)
    if cycle.signal:
        frappe.db.set_value("CFG Kanban Signal", cycle.signal, {
            "erp_reference_doctype": "Work Order", "erp_reference_name": selected.name,
        })
    _sync_job_cards(selected, cycle)
    _mark_released(cycle, selected)
    record("Effective Work Order Selected", card=cycle.kanban_card, cycle=cycle.name,
           reference_doctype="Work Order", reference_name=selected.name,
           notes=f"Replaced {previous or 'no Work Order'}; {reason}", system_generated=False)
    return {"cycle": cycle.name, "work_order": selected.name, "job_cards": job_count}


def _detach_inactive_work_order(work_order_name, cycle):
    stock_activity = frappe.db.exists("Stock Entry", {
        "work_order": work_order_name, "docstatus": 1,
    })
    job_activity = frappe.db.exists("Job Card", {
        "work_order": work_order_name, "status": ["in", ("Work In Progress", "Completed")],
    })
    if stock_activity or job_activity:
        frappe.throw(f"Work Order {work_order_name} has production activity and cannot be detached. "
                     "Resolve it as a production exception.")
    job_cards = frappe.get_all("Job Card", filters={"work_order": work_order_name}, pluck="name")
    if job_cards:
        for job_card in job_cards:
            executions = frappe.get_all("CFG Kanban Process Execution",
                                        filters={"job_card": job_card}, pluck="name")
            for execution in executions:
                frappe.db.set_value("CFG Kanban Process Execution", execution,
                                    "status", "Cancelled")
            frappe.db.set_value("Job Card", job_card, {
                "cfg_kanban_controlled": 0, "cfg_kanban_cycle": None,
                "cfg_kanban_signal": None,
            }, update_modified=False)
    frappe.db.set_value("Work Order", work_order_name, {
        "cfg_kanban_controlled": 0, "cfg_kanban_cycle": None,
        "cfg_kanban_signal": None,
    }, update_modified=False)


def on_work_order_cancel(doc, method=None):
    _block(doc, "Work Order Cancelled")


def on_job_card_update(doc, method=None):
    cycle_name = _cycle(doc)
    if not cycle_name:
        return
    _sync_job_card_execution(doc, cycle_name, emit_event=True)


def reconcile_cycle_job_card_progress(cycle_name):
    """Repair a main production Cycle from its authoritative ERP Job Cards."""
    rows = frappe.get_all(
        "CFG Kanban Process Execution",
        filters={"kanban_cycle": cycle_name},
        fields=["job_card", "runtime_allocation"],
    )
    job_cards = {row.job_card for row in rows if row.job_card and not row.runtime_allocation}
    for job_card in job_cards:
        if frappe.db.exists("Job Card", job_card):
            _sync_job_card_execution(frappe.get_doc("Job Card", job_card), cycle_name,
                                     emit_event=False)


def _sync_job_card_execution(doc, cycle_name, emit_event=False):
    execution = frappe.db.get_value("CFG Kanban Process Execution", {
        "job_card": doc.name, "kanban_cycle": cycle_name,
    }, "name")
    if not execution:
        return False
    execution_doc = frappe.get_doc("CFG Kanban Process Execution", execution)
    status = ("Completed" if doc.status == "Completed" else
              "In Progress" if doc.status == "Work In Progress" else None)
    values = {"status": status} if status and status != execution_doc.status else {}
    # The production Cycle is the Work Order/Job Card overview. A separate
    # Process or Station Card owns only its card-sized runtime allocation.
    # Mirror ERPNext's cumulative Job Card result into the non-runtime
    # execution so both cards show one authoritative quantity without
    # posting it to ERPNext a second time.
    if not execution_doc.runtime_allocation:
        erp_good_qty = flt(doc.total_completed_qty)
        erp_processed_qty = erp_good_qty + flt(execution_doc.reject_qty)
        if flt(execution_doc.good_qty) != erp_good_qty:
            values["good_qty"] = erp_good_qty
        if flt(execution_doc.processed_qty) != erp_processed_qty:
            values["processed_qty"] = erp_processed_qty
    became_completed = status == "Completed" and execution_doc.status != "Completed"
    if values:
        frappe.db.set_value("CFG Kanban Process Execution", execution, values)
    released = False
    if not execution_doc.runtime_allocation:
        released = _release_mirrored_job_card_progress(
            execution_doc, flt(doc.total_completed_qty)
        )
    if became_completed:
        from cfg_kanban.services.progress import complete_execution_handoff
        from cfg_kanban.services.process_tasks import evaluate_gate
        complete_execution_handoff(execution)
        evaluate_gate(cycle_name, "After Operation Complete", doc.operation)
        ready_next_sequential_lane(frappe.get_doc("CFG Kanban Process Execution", execution))
    if values or released or became_completed:
        recalculate(cycle_name, doc.operation)
    if emit_event and (values or released or became_completed):
        record("Job Card Feedback", cycle=cycle_name, execution=execution,
               reference_doctype=doc.doctype, reference_name=doc.name, new_state=status)
    return bool(values or released or became_completed)


def _release_mirrored_job_card_progress(execution, total_good):
    """Release incremental main-cycle WIP mirrored from a shared ERP Job Card."""
    if execution.handoff_mode != "Digital Quantity Handoff":
        return False
    from cfg_kanban.services.wip import append_entry, releasable_increment

    release = releasable_increment(total_good, execution.released_qty,
                                   execution.transfer_multiple)
    if not release:
        return False
    append_entry(
        execution.kanban_cycle, "Released", release,
        source_execution=execution.name,
        source_operation=execution.operation,
        destination_operation=execution.destination_operation,
        notes=("ERPNext Job Card progress mirrored from a separate Process or "
               "Station Kanban runtime allocation"),
    )
    execution.db_set("released_qty", flt(execution.released_qty) + release)
    refresh_destination(execution.kanban_cycle, execution.operation,
                        execution.destination_operation)
    return True


def on_job_card_cancel(doc, method=None):
    _block(doc, "Job Card Cancelled")


def on_stock_entry_submit(doc, method=None):
    if doc.get("cfg_withdrawal_cycle"):
        from cfg_kanban.services.withdrawal import complete_withdrawal
        complete_withdrawal(doc)
        return
    if doc.get("cfg_movement_manifest"):
        from cfg_kanban.integrations.logistics_feedback import on_internal_stock_entry_submit
        on_internal_stock_entry_submit(doc)
        return
    from cfg_kanban.services.production_trace import confirm_stock_entry_trace
    confirm_stock_entry_trace(doc)
    from cfg_kanban.services.wip_bin_loads import confirm_wip_bin_stock_entry
    confirm_wip_bin_stock_entry(doc)
    if doc.get("cfg_return_case"):
        from cfg_kanban.integrations.return_stock_feedback import on_submit
        on_submit(doc)
    cycle_name = _cycle(doc)
    if not cycle_name:
        return
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    record("Stock Entry Submitted", cycle=cycle.name, card=cycle.kanban_card,
           reference_doctype=doc.doctype, reference_name=doc.name)
    if cycle.status == "Completed":
        return
    if doc.stock_entry_type == "Manufacture":
        _update_mto_output(doc, cycle)
        set_cycle_state(cycle, "Waiting FG Receipt", event_type="Manufacture Submitted")
        reconcile_physical_production_cycle(
            cycle.name, reference_doctype=doc.doctype, reference_name=doc.name
        )


def reconcile_physical_production_cycle(
    cycle_name, reference_doctype=None, reference_name=None
):
    """Close a travelling production-card cycle only after ERPNext proves completion."""
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    if not cycle.kanban_card:
        return {"completed": False, "reason": "Cycle has no physical Kanban Card"}
    card = frappe.get_doc("CFG Kanban Card", cycle.kanban_card)
    if card.card_type not in ("Physical Unit Card", "Physical Batch Card"):
        return {"completed": False, "reason": "Runtime cards use runtime allocation closure"}
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    if master.control_type != "Production":
        return {"completed": False, "reason": "Cycle is not Production control"}
    if card.active_cycle != cycle.name:
        return {"completed": False, "reason": "Card does not identify this as its active Cycle"}
    if cycle.status in ("Cancelled", "Blocked", "Hold") or card.blocked:
        return {"completed": False, "reason": "Cycle or Card requires supervisor attention"}

    if cycle.status == "Completed":
        related = _complete_related_operation_cycles(cycle)
        if related["blockers"]:
            return {
                "completed": False,
                "reason": _related_operation_block_reason(related["blockers"]),
                "related_operation_cycles": related,
            }
        result = _release_completed_physical_card(
            cycle, card, reference_doctype, reference_name
        )
        result["related_operation_cycles"] = related
        return result
    if not cycle.work_order:
        return {"completed": False, "reason": "Cycle has no effective Work Order"}
    work_order = frappe.db.get_value(
        "Work Order", cycle.work_order, ["name", "docstatus", "status"], as_dict=True
    )
    if not work_order or work_order.docstatus != 1 or work_order.status != "Completed":
        return {"completed": False, "reason": "ERPNext Work Order is not Completed"}

    incomplete_jobs = frappe.get_all(
        "Job Card",
        filters={"work_order": cycle.work_order, "docstatus": ["<", 2],
                 "status": ["!=", "Completed"]},
        pluck="name",
    )
    if incomplete_jobs:
        return {
            "completed": False,
            "reason": "ERPNext Job Card(s) are not Completed: " + ", ".join(incomplete_jobs),
        }

    received_qty = _submitted_finished_goods_qty(
        cycle.name, cycle.work_order, cycle.item_code
    )
    required_qty = flt(cycle.effective_cycle_qty or cycle.planned_qty)
    if received_qty + 0.000001 < required_qty:
        return {
            "completed": False,
            "reason": (f"Submitted Manufacture receipt is {received_qty} {cycle.stock_uom}; "
                       f"Cycle requires {required_qty} {cycle.stock_uom}"),
            "received_qty": received_qty,
            "required_qty": required_qty,
        }

    from cfg_kanban.services.process_tasks import evaluate_gate
    gate = evaluate_gate(cycle.name, "Before Cycle Close")
    if not gate["open"]:
        blockers = ", ".join(
            f"{row['task_name']} ({row['status']})" for row in gate["blockers"]
        )
        return {
            "completed": False,
            "reason": f"Before Cycle Close is blocked by: {blockers}",
        }
    if card.current_state not in ("Production Released", "In Production", "Produced", "Available"):
        return {
            "completed": False,
            "reason": f"Card state {card.current_state} requires controlled reconciliation",
        }

    related = _complete_related_operation_cycles(cycle)
    if related["blockers"]:
        return {
            "completed": False,
            "reason": _related_operation_block_reason(related["blockers"]),
            "related_operation_cycles": related,
        }

    cycle.db_set({
        "actual_good_qty": received_qty,
        "completed_on": now_datetime(),
    }, update_modified=True)
    set_cycle_state(
        cycle, "Completed", event_type="Physical Production Cycle Completed",
        reference_doctype=reference_doctype or "Work Order",
        reference_name=reference_name or cycle.work_order,
    )
    result = _release_completed_physical_card(
        cycle, card, reference_doctype or "Work Order",
        reference_name or cycle.work_order,
    )
    result["related_operation_cycles"] = related
    return result


def _complete_related_operation_cycles(owner_cycle):
    """Close Process/Station card allocations proved complete by the owning production Cycle.

    The function preflights every active related allocation before changing any one of them. This
    prevents the main physical Card from recycling while an operation Card still has incomplete
    Kanban quantity, ERP Job Card, WIP-bin, or Process Task evidence.
    """
    if not owner_cycle.work_order:
        return {"closed": [], "already_released": [], "blockers": []}
    names = [row[0] for row in frappe.db.sql("""
        select name
        from `tabCFG Kanban Cycle`
        where work_order=%s
          and name != %s
          and ifnull(runtime_allocation, '') != ''
          and status != 'Cancelled'
        order by creation asc
        for update
    """, (owner_cycle.work_order, owner_cycle.name))]
    candidates = []
    blockers = []
    already_released = []
    for name in names:
        cycle = frappe.get_doc("CFG Kanban Cycle", name)
        card = frappe.get_doc("CFG Kanban Card", cycle.kanban_card)
        if card.card_type not in ("Process Kanban", "Station Kanban"):
            continue
        if cycle.status == "Completed" and card.active_cycle != cycle.name:
            already_released.append(cycle.name)
            continue
        blocker, context = _related_operation_close_context(owner_cycle, cycle, card)
        if blocker:
            blockers.append(blocker)
        else:
            candidates.append(context)
    if blockers:
        return {"closed": [], "already_released": already_released, "blockers": blockers}

    closed = []
    for context in candidates:
        cycle = context["cycle"]
        card = context["card"]
        execution = context["execution"]
        allocation = context["allocation"]
        completed_on = now_datetime()
        if execution.status != "Completed":
            execution.db_set({"status": "Completed", "completed_on": completed_on},
                             update_modified=True)
        if allocation.status != "Completed":
            notes = (allocation.notes or "").strip()
            closure_note = f"Auto-closed with main production Cycle {owner_cycle.name}"
            allocation.db_set({
                "status": "Completed", "completed_on": completed_on,
                "good_qty": execution.good_qty, "reject_qty": execution.reject_qty,
                "notes": f"{notes}\n{closure_note}".strip(),
            }, update_modified=True)
        cycle.db_set({
            "completed_on": completed_on, "actual_good_qty": execution.good_qty,
            "reject_qty": execution.reject_qty,
        }, update_modified=True)
        set_cycle_state(
            cycle, "Completed", event_type="Related Operation Cycle Auto-Completed",
            reference_doctype="CFG Kanban Cycle", reference_name=owner_cycle.name,
        )
        recalculate(cycle.name, execution.operation)
        if card.current_state == "Production Released":
            transition_card(
                card, "In Production", event_type="Related Operation Reconciled",
                cycle=cycle.name,
            )
            card.reload()
        if card.current_state == "In Production":
            transition_card(
                card, "Produced", event_type="Related Operation Completed",
                cycle=cycle.name,
            )
            card.reload()
        if card.current_state == "Produced":
            transition_card(
                card, "Available", event_type="Related Operation Card Recycled",
                cycle=cycle.name,
            )
            card.reload()
        if card.active_cycle == cycle.name:
            card.db_set("active_cycle", None, update_modified=False)
        record(
            "Related Operation Card Auto-Released", card=card.name, cycle=cycle.name,
            execution=execution.name, qty=execution.good_qty,
            reference_doctype="CFG Kanban Cycle", reference_name=owner_cycle.name,
            notes=(f"ERPNext Work Order {owner_cycle.work_order} and Job Card "
                   f"{execution.job_card} are complete; main production closure released this "
                   "related operation Card."),
        )
        closed.append({
            "cycle": cycle.name, "card": card.name, "operation": execution.operation,
            "job_card": execution.job_card,
        })
    return {"closed": closed, "already_released": already_released, "blockers": []}


def _related_operation_close_context(owner_cycle, cycle, card):
    label = f"{card.card_number or card.name} / {cycle.name}"
    if card.blocked:
        return f"{label}: Card is Blocked", None
    if card.active_cycle != cycle.name:
        return f"{label}: Card active Cycle does not match this operation Cycle", None
    if card.current_state not in ("Production Released", "In Production", "Produced", "Available"):
        return f"{label}: Card state is {card.current_state}", None
    allocation = frappe.get_doc("CFG Kanban Runtime Allocation", cycle.runtime_allocation)
    if (allocation.kanban_cycle != cycle.name or allocation.kanban_card != card.name or
            allocation.work_order != owner_cycle.work_order):
        return f"{label}: runtime allocation ownership does not match the main Work Order", None
    if allocation.status == "Cancelled":
        return f"{label}: runtime allocation is Cancelled", None
    executions = frappe.get_all(
        "CFG Kanban Process Execution",
        filters={"kanban_cycle": cycle.name, "runtime_allocation": allocation.name},
        pluck="name",
    )
    if len(executions) != 1:
        return f"{label}: expected one runtime execution, found {len(executions)}", None
    execution = frappe.get_doc("CFG Kanban Process Execution", executions[0])
    if flt(execution.processed_qty) + 0.000001 < flt(execution.target_qty):
        return (f"{label}: operation {execution.operation} reported "
                f"{flt(execution.processed_qty)} of {flt(execution.target_qty)}"), None
    job = frappe.db.get_value(
        "Job Card", execution.job_card,
        ["name", "work_order", "status", "docstatus"], as_dict=True,
    )
    if (not job or job.work_order != owner_cycle.work_order or job.docstatus != 1 or
            job.status != "Completed"):
        status = job.status if job else "Missing"
        return f"{label}: ERPNext Job Card {execution.job_card} is {status}", None
    from cfg_kanban.services.wip_bin_loads import job_card_wip_bin_close_readiness
    wip_readiness = job_card_wip_bin_close_readiness(job.name)
    if not wip_readiness["ready"]:
        return f"{label}: {wip_readiness['reason']}", None
    from cfg_kanban.services.process_tasks import evaluate_gate
    gate = evaluate_gate(cycle.name, "Before Cycle Close")
    if not gate["open"]:
        task_blockers = ", ".join(
            f"{row['task_name']} ({row['status']})" for row in gate["blockers"]
        )
        return f"{label}: Before Cycle Close is blocked by {task_blockers}", None
    return None, {
        "cycle": cycle, "card": card, "allocation": allocation,
        "execution": execution,
    }


def _related_operation_block_reason(blockers):
    return ("Related operation Card cycle(s) are not ready to close automatically: "
            + "; ".join(blockers))


def _release_completed_physical_card(
    cycle, card, reference_doctype=None, reference_name=None
):
    if card.current_state == "Production Released":
        transition_card(
            card, "In Production", event_type="Physical Production Reconciled",
            cycle=cycle.name,
        )
        card.reload()
    if card.current_state == "In Production":
        transition_card(
            card, "Produced", event_type="Finished Goods Received",
            cycle=cycle.name,
        )
        card.reload()
    if card.current_state == "Produced":
        transition_card(
            card, "Available", event_type="Physical Production Card Recycled",
            cycle=cycle.name,
        )
        card.reload()
    if card.current_state != "Available":
        return {
            "completed": False,
            "reason": f"Card state {card.current_state} requires controlled reconciliation",
        }
    if card.active_cycle == cycle.name:
        card.db_set("active_cycle", None, update_modified=False)
    record(
        "Physical Production Card Released",
        card=card.name,
        cycle=cycle.name,
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        notes="ERPNext Work Order, Job Cards, and submitted finished-goods receipt are complete",
    )
    return {
        "completed": True,
        "cycle": cycle.name,
        "card": card.name,
        "card_state": "Available",
        "received_qty": flt(cycle.actual_good_qty),
    }


def _submitted_finished_goods_qty(cycle_name, work_order, item_code):
    return flt(frappe.db.sql("""
        select coalesce(sum(sed.qty), 0)
        from `tabStock Entry Detail` sed
        inner join `tabStock Entry` se on se.name=sed.parent
        where se.docstatus=1
          and (se.cfg_kanban_cycle=%s or se.work_order=%s)
          and se.stock_entry_type='Manufacture'
          and sed.item_code=%s
          and ifnull(sed.t_warehouse, '') != ''
    """, (cycle_name, work_order, item_code))[0][0])


def validate_stock_entry(doc, method=None):
    if doc.get("cfg_withdrawal_cycle"):
        from cfg_kanban.services.withdrawal import validate_withdrawal_stock_entry
        validate_withdrawal_stock_entry(doc)
        return
    if doc.get("cfg_movement_manifest"):
        from cfg_kanban.integrations.logistics_feedback import validate_internal_stock_entry
        validate_internal_stock_entry(doc)
        return
    from cfg_kanban.services.production_trace import validate_stock_entry_trace
    validate_stock_entry_trace(doc)
    from cfg_kanban.services.wip_bin_loads import validate_wip_bin_stock_entry
    validate_wip_bin_stock_entry(doc)
    if doc.get("cfg_return_case"):
        from cfg_kanban.integrations.return_stock_feedback import validate
        validate(doc)
    cycle_name = _cycle(doc)
    if not cycle_name or doc.stock_entry_type != "Manufacture":
        return
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    from cfg_kanban.services.process_tasks import assert_gate_open
    assert_gate_open(cycle.name, "Before FG Release")
    if cycle.get("production_policy") != "Customer Make-to-Order":
        return
    demand = frappe.get_doc("CFG Kanban Demand", cycle.sales_demand)
    finished_rows = _mto_finished_rows(doc, cycle)
    if not finished_rows:
        frappe.throw("MTO Manufacture entry must contain the ordered finished item")
    wrong_batches = [row.batch_no or "(blank)" for row in finished_rows
                     if row.batch_no != cycle.batch_no]
    if wrong_batches:
        frappe.throw(f"All MTO finished output must use planned Batch {cycle.batch_no}")
    prior_qty = _submitted_mto_qty(cycle.name, cycle.item_code)
    resulting_qty = prior_qty + sum(flt(row.qty) for row in finished_rows)
    if resulting_qty > flt(demand.maximum_authorized_qty) + 0.000001:
        frappe.throw(f"MTO output {resulting_qty} exceeds customer-authorized maximum "
                     f"{demand.maximum_authorized_qty}")


def _update_mto_output(doc, cycle):
    if cycle.get("production_policy") != "Customer Make-to-Order":
        return
    demand = frappe.get_doc("CFG Kanban Demand", cycle.sales_demand)
    actual = _submitted_mto_qty(cycle.name, cycle.item_code)
    excess = max(0, actual - flt(demand.outstanding_qty))
    acceptance = "PO Authorized" if excess else "Not Applicable"
    demand.db_set({"actual_accepted_qty": actual, "excess_qty": excess,
                   "excess_acceptance_status": acceptance}, update_modified=True)
    cycle.db_set("actual_good_qty", actual)
    if excess:
        record("MTO Excess Accepted by Customer PO", cycle=cycle.name, qty=excess,
               reference_doctype="Sales Order", reference_name=demand.sales_order,
               notes=demand.po_tolerance_reference)


def _mto_finished_rows(doc, cycle):
    return [row for row in doc.items if row.item_code == cycle.item_code and row.t_warehouse]


def _submitted_mto_qty(cycle_name, item_code):
    return flt(frappe.db.sql("""
        select coalesce(sum(sed.qty), 0)
        from `tabStock Entry Detail` sed
        inner join `tabStock Entry` se on se.name=sed.parent
        where se.docstatus=1 and se.cfg_kanban_cycle=%s
          and se.stock_entry_type='Manufacture' and sed.item_code=%s
          and ifnull(sed.t_warehouse, '') != ''
    """, (cycle_name, item_code))[0][0])


def on_stock_entry_cancel(doc, method=None):
    if doc.get("cfg_withdrawal_cycle"):
        from cfg_kanban.services.withdrawal import block_withdrawal_cancel
        block_withdrawal_cancel(doc)
        return
    if doc.get("cfg_movement_manifest"):
        from cfg_kanban.integrations.logistics_feedback import on_internal_stock_entry_cancel
        on_internal_stock_entry_cancel(doc)
    from cfg_kanban.services.production_trace import reverse_stock_entry_trace
    reverse_stock_entry_trace(doc)
    from cfg_kanban.services.wip_bin_loads import reverse_wip_bin_stock_entry
    reverse_wip_bin_stock_entry(doc)
    if doc.get("cfg_return_case"):
        from cfg_kanban.integrations.return_stock_feedback import on_cancel
        on_cancel(doc)
    _block(doc, "Stock Entry Cancelled")


def _block(doc, reason):
    cycle_name = _cycle(doc)
    if not cycle_name:
        return
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    cycle.db_set({"status": "Blocked", "blocked": 1})
    if cycle.kanban_card:
        card = frappe.get_doc("CFG Kanban Card", cycle.kanban_card)
        card.db_set({"blocked": 1, "blocked_reason": reason})
    record("Exception Raised", cycle=cycle.name, card=cycle.kanban_card, notes=reason,
           reference_doctype=doc.doctype, reference_name=doc.name)


def _sync_job_cards(work_order, cycle):
    """Mirror ERPNext's Job Cards as parallel-capable Kanban executions."""
    if _runtime_card(cycle):
        # Runtime selector creates only the confirmed Job Card execution. Never mirror the whole WO.
        return
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    profiles = {row.operation: row for row in master.operation_profiles}
    summaries = {row.operation: ensure_summary(cycle, master, row)
                 for row in master.operation_profiles}
    first_sequence = min((row.sequence for row in master.operation_profiles), default=0)
    cards = frappe.get_all("Job Card", filters={"work_order": work_order.name, "docstatus": ["<", 2]},
                           fields=["name", "operation", "workstation", "status",
                                   "for_quantity", "total_completed_qty", "creation"],
                           order_by="operation asc, creation asc")
    created = {}
    lane_counts = {}
    for job in cards:
        frappe.db.set_value("Job Card", job.name, {
            "cfg_kanban_controlled": 1,
            "cfg_kanban_cycle": cycle.name,
            "cfg_kanban_signal": cycle.signal,
        }, update_modified=False)
        profile = profiles.get(job.operation)
        if not profile:
            _record_unmatched_job_card(job, cycle)
            continue
        lane_counts[job.operation] = lane_counts.get(job.operation, 0) + 1
        lane_sequence = lane_counts[job.operation]
        summary = summaries[profile.operation]
        mode = _profile_execution_mode(profile)
        existing = frappe.db.get_value("CFG Kanban Process Execution", {
            "job_card": job.name, "kanban_cycle": cycle.name,
        }, "name")
        if existing:
            current = frappe.db.get_value("CFG Kanban Process Execution", existing, "status")
            repaired = _execution_status(job.status, profile, first_sequence, current,
                                         lane_sequence=lane_sequence)
            if repaired != current:
                frappe.db.set_value("CFG Kanban Process Execution", existing, "status", repaired)
            frappe.db.set_value("CFG Kanban Process Execution", existing, {
                "operation_summary": summary.name, "lane_sequence": lane_sequence,
                "execution_mode": mode, "allocated_qty": job.for_quantity,
                "target_qty": job.for_quantity, "destination_operation": profile.destination_operation,
            })
            created[job.operation] = existing
            continue
        execution = frappe.get_doc({
            "doctype": "CFG Kanban Process Execution", "kanban_cycle": cycle.name,
            "kanban_master": master.name, "operation": job.operation, "sequence": profile.sequence,
            "operation_summary": summary.name, "lane_sequence": lane_sequence,
            "job_card": job.name, "workstation": job.workstation,
            "status": _execution_status(job.status, profile, first_sequence, lane_sequence=lane_sequence),
            "execution_mode": mode, "allocated_qty": job.for_quantity,
            "target_qty": job.for_quantity, "allow_parallel": mode == "Parallel Workstations",
            "handoff_mode": profile.handoff_mode, "transfer_multiple": profile.transfer_multiple,
            "destination_operation": profile.destination_operation,
            "operation_profile_revision": master.revision,
        }).insert(ignore_permissions=True)
        created[job.operation] = execution.name
    for operation, count in lane_counts.items():
        profile = profiles[operation]
        mode = _profile_execution_mode(profile)
        summary = recalculate(cycle.name, operation)
        if summary:
            _validate_operation_allocation(cycle, summary, mode, count)
        if summary and profile.sequence == first_sequence:
            ready_executions(summary, mode)
    for operation, execution_name in created.items():
        destination = profiles.get(operation).destination_operation if profiles.get(operation) else None
        if destination and created.get(destination):
            frappe.db.set_value("CFG Kanban Process Execution", execution_name,
                                "destination_execution", created[destination])


def _execution_status(job_status, profile, first_sequence, current=None, lane_sequence=1):
    if job_status == "Completed":
        return "Completed"
    if job_status == "Work In Progress":
        return "In Progress"
    if current not in (None, "Not Ready", "Ready"):
        return current
    mode = _profile_execution_mode(profile)
    operation_ready = profile.sequence == first_sequence or profile.start_rule == "No Dependency"
    ready = operation_ready and (mode != "Sequential Split" or lane_sequence == 1)
    return "Ready" if ready else "Not Ready"


def _profile_execution_mode(profile):
    if profile.allow_parallel and profile.execution_mode in (None, "", "Single Workstation"):
        return "Parallel Workstations"
    return profile.execution_mode or "Single Workstation"


def _record_parallel_configuration_exception(cycle, operation, count, detail=None):
    message = detail or (f"Operation {operation} has {count} Job Cards but its Kanban Execution Mode is "
                         "Single Workstation")
    if frappe.db.exists("CFG Kanban Exception", {"kanban_cycle": cycle.name,
            "message": message, "status": "Open"}):
        return
    frappe.get_doc({"doctype": "CFG Kanban Exception", "exception_type": "Configuration",
        "severity": "Error", "status": "Open", "kanban_cycle": cycle.name,
        "message": message, "reference_doctype": "Work Order",
        "reference_name": cycle.work_order, "raised_on": frappe.utils.now_datetime()
    }).insert(ignore_permissions=True)


def _validate_operation_allocation(cycle, summary, mode, count):
    messages = []
    if mode == "Single Workstation" and count > 1:
        messages.append(f"Single Workstation mode has {count} Job Cards")
    if flt(summary.allocated_qty) > flt(cycle.planned_qty) + 0.000001:
        messages.append(f"allocated Job Card quantity {summary.allocated_qty} exceeds Cycle quantity {cycle.planned_qty}")
    if not messages:
        return
    summary.db_set("status", "Blocked")
    execution_names = frappe.get_all("CFG Kanban Process Execution", filters={
        "operation_summary": summary.name, "status": ["in", ("Not Ready", "Ready")],
    }, pluck="name")
    for execution_name in execution_names:
        frappe.db.set_value("CFG Kanban Process Execution", execution_name, "status", "Blocked")
    _record_parallel_configuration_exception(cycle, summary.operation, count,
        f"Operation {summary.operation} blocked: {'; '.join(messages)}")


def _record_unmatched_job_card(job, cycle):
    key = f"Job Card operation {job.operation} is not configured in Kanban Master {cycle.kanban_master}"
    if frappe.db.exists("CFG Kanban Exception", {"kanban_cycle": cycle.name,
            "reference_doctype": "Job Card", "reference_name": job.name, "status": "Open"}):
        return
    frappe.get_doc({"doctype": "CFG Kanban Exception", "exception_type": "Configuration",
        "severity": "Error", "status": "Open", "kanban_cycle": cycle.name,
        "message": key, "reference_doctype": "Job Card", "reference_name": job.name,
        "raised_on": frappe.utils.now_datetime()}).insert(ignore_permissions=True)


def _runtime_card(cycle):
    if not cycle.kanban_card:
        return False
    card_type = frappe.db.get_value("CFG Kanban Card", cycle.kanban_card, "card_type")
    return card_type in ("Process Kanban", "Station Kanban")


@frappe.whitelist()
def release_legacy_runtime_card(cycle_name, reason):
    """Cancel an activity-free legacy mapping and return its reusable card to Available."""
    frappe.only_for(("Manufacturing Manager", "System Manager"))
    if not (reason or "").strip():
        frappe.throw("A recovery reason is required")
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    cycle.check_permission("write")
    if not _runtime_card(cycle):
        frappe.throw("This recovery action is only for Process and Station Kanban cards")
    if cycle.runtime_allocation:
        frappe.throw("This Cycle already uses the runtime-allocation model")
    card = frappe.get_doc("CFG Kanban Card", cycle.kanban_card)
    if card.active_cycle != cycle.name:
        frappe.throw(f"Card {card.name} does not identify this as its active Cycle")

    executions = frappe.get_all("CFG Kanban Process Execution",
        filters={"kanban_cycle": cycle.name},
        fields=["name", "job_card", "status", "processed_qty", "good_qty",
                "reject_qty", "released_qty"])
    active_job_cards = []
    for row in executions:
        job_status = frappe.db.get_value("Job Card", row.job_card, "status") if row.job_card else None
        if job_status in ("Work In Progress", "Completed"):
            active_job_cards.append(f"{row.job_card} ({job_status})")
        if (row.status in ("In Progress", "Completed") or flt(row.processed_qty) or
                flt(row.good_qty) or flt(row.reject_qty) or flt(row.released_qty)):
            frappe.throw(f"Execution {row.name} contains production activity. Raise a production "
                         "exception instead of releasing this Card automatically.")
    if active_job_cards:
        frappe.throw("ERPNext production activity exists on: " + ", ".join(active_job_cards))
    if frappe.db.exists("CFG Kanban Operation Progress", {"kanban_cycle": cycle.name}):
        frappe.throw("Operation Progress exists for this Cycle; automatic recovery is not allowed")
    if frappe.db.exists("Stock Entry", {"cfg_kanban_cycle": cycle.name, "docstatus": 1}):
        frappe.throw("Submitted Stock Entry exists for this Cycle; automatic recovery is not allowed")
    if frappe.db.exists("CFG Kanban WIP Ledger", {"kanban_cycle": cycle.name}):
        frappe.throw("WIP movement exists for this Cycle; automatic recovery is not allowed")

    for row in executions:
        frappe.db.set_value("CFG Kanban Process Execution", row.name,
                            {"status": "Cancelled", "blocked": 0})
    summaries = frappe.get_all("CFG Kanban Operation Summary",
                               filters={"kanban_cycle": cycle.name}, pluck="name")
    for summary in summaries:
        frappe.db.set_value("CFG Kanban Operation Summary", summary, "status", "Cancelled")

    if cycle.work_order:
        frappe.db.set_value("Work Order", cycle.work_order, {
            "cfg_kanban_cycle": None, "cfg_kanban_signal": None,
        }, update_modified=False)
        jobs = frappe.get_all("Job Card", filters={"work_order": cycle.work_order}, pluck="name")
        for job in jobs:
            if frappe.db.get_value("Job Card", job, "cfg_kanban_cycle") == cycle.name:
                frappe.db.set_value("Job Card", job, {
                    "cfg_kanban_cycle": None, "cfg_kanban_signal": None,
                }, update_modified=False)

    previous_cycle_state = cycle.status
    previous_card_state = card.current_state
    cycle.db_set({"status": "Cancelled", "completed_on": now_datetime(),
                  "blocked": 0, "remarks": ((cycle.remarks or "") +
                  f"\nLegacy runtime reconciliation released: {reason}").strip()})
    card.db_set({"current_state": "Available", "active_cycle": None,
                 "blocked": 0, "blocked_reason": None}, update_modified=True)
    record("Legacy Runtime Cycle Cancelled", card=card.name, cycle=cycle.name,
           previous_state=previous_cycle_state, new_state="Cancelled", notes=reason,
           system_generated=False)
    event = record("Reusable Card Released by Recovery", card=card.name, cycle=cycle.name,
                   previous_state=previous_card_state, new_state="Available", notes=reason,
                   system_generated=False)
    card.db_set("last_event", event.name, update_modified=False)
    return {"cycle": cycle.name, "card": card.name, "work_order": cycle.work_order,
            "cancelled_executions": len(executions), "card_state": "Available"}
