import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.operation_summary import (ensure_summary, ready_executions,
                                                    ready_next_sequential_lane, recalculate)
from cfg_kanban.services.state_machine import set_cycle_state, transition_card


def _cycle(doc):
    return getattr(doc, "cfg_kanban_cycle", None)


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
    if not _cycle(doc):
        return
    execution = frappe.db.get_value("CFG Kanban Process Execution", {
        "job_card": doc.name, "kanban_cycle": doc.cfg_kanban_cycle,
    }, "name")
    if execution:
        execution_doc = frappe.get_doc("CFG Kanban Process Execution", execution)
        status = "Completed" if doc.status == "Completed" else "In Progress" if doc.status == "Work In Progress" else None
        if status:
            values = {"status": status}
            # A runtime execution is one card-sized allocation, while the Job Card
            # quantity is cumulative across multiple reusable-card cycles.
            if status == "Completed" and not execution_doc.runtime_allocation:
                values.update({"good_qty": flt(doc.total_completed_qty), "processed_qty": flt(doc.total_completed_qty)})
            frappe.db.set_value("CFG Kanban Process Execution", execution, values)
            if status == "Completed":
                from cfg_kanban.services.progress import complete_execution_handoff
                complete_execution_handoff(execution)
                ready_next_sequential_lane(frappe.get_doc("CFG Kanban Process Execution", execution))
            recalculate(doc.cfg_kanban_cycle, doc.operation)
        record("Job Card Feedback", cycle=doc.cfg_kanban_cycle, execution=execution,
               reference_doctype=doc.doctype, reference_name=doc.name, new_state=status)


def on_job_card_cancel(doc, method=None):
    _block(doc, "Job Card Cancelled")


def on_stock_entry_submit(doc, method=None):
    if not _cycle(doc):
        return
    cycle = frappe.get_doc("CFG Kanban Cycle", doc.cfg_kanban_cycle)
    record("Stock Entry Submitted", cycle=cycle.name, card=cycle.kanban_card,
           reference_doctype=doc.doctype, reference_name=doc.name)
    if doc.stock_entry_type == "Manufacture":
        _update_mto_output(doc, cycle)
        set_cycle_state(cycle, "Waiting FG Receipt", event_type="Manufacture Submitted")


def validate_stock_entry(doc, method=None):
    if not _cycle(doc) or doc.stock_entry_type != "Manufacture":
        return
    cycle = frappe.get_doc("CFG Kanban Cycle", doc.cfg_kanban_cycle)
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
    _block(doc, "Stock Entry Cancelled")


def _block(doc, reason):
    if not _cycle(doc):
        return
    cycle = frappe.get_doc("CFG Kanban Cycle", doc.cfg_kanban_cycle)
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
