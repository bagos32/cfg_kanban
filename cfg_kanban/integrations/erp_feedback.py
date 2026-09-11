import frappe

from cfg_kanban.services.events import record
from cfg_kanban.services.state_machine import set_cycle_state, transition_card


def _cycle(doc):
    return getattr(doc, "cfg_kanban_cycle", None)


def on_work_order_update(doc, method=None):
    if not _cycle(doc):
        return
    cycle = frappe.get_doc("CFG Kanban Cycle", doc.cfg_kanban_cycle)
    _sync_job_cards(doc, cycle)
    if doc.status in ("In Process", "Started"):
        set_cycle_state(cycle, "In Production", event_type="Work Order Started",
                        reference_doctype=doc.doctype, reference_name=doc.name)
        if cycle.kanban_card:
            transition_card(cycle.kanban_card, "In Production", event_type="Production Started", cycle=cycle.name)
    elif doc.status == "Completed":
        set_cycle_state(cycle, "Production Complete", event_type="Work Order Completed",
                        reference_doctype=doc.doctype, reference_name=doc.name)


def on_work_order_cancel(doc, method=None):
    _block(doc, "Work Order Cancelled")


def on_job_card_update(doc, method=None):
    if not _cycle(doc):
        return
    execution = frappe.db.get_value("CFG Kanban Process Execution", {"job_card": doc.name}, "name")
    if execution:
        status = "Completed" if doc.status == "Completed" else "In Progress" if doc.status in ("Work In Progress", "Open") else None
        if status:
            frappe.db.set_value("CFG Kanban Process Execution", execution, "status", status)
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
        set_cycle_state(cycle, "Waiting FG Receipt", event_type="Manufacture Submitted")


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
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    profiles = {row.operation: row for row in master.operation_profiles}
    cards = frappe.get_all("Job Card", filters={"work_order": work_order.name, "docstatus": ["<", 2]},
                           fields=["name", "operation", "workstation", "status"])
    created = {}
    for job in cards:
        frappe.db.set_value("Job Card", job.name, {
            "cfg_kanban_controlled": 1,
            "cfg_kanban_cycle": cycle.name,
            "cfg_kanban_signal": cycle.signal,
        }, update_modified=False)
        existing = frappe.db.get_value("CFG Kanban Process Execution", {"job_card": job.name}, "name")
        if existing:
            created[job.operation] = existing
            continue
        profile = profiles.get(job.operation)
        if not profile:
            continue
        execution = frappe.get_doc({
            "doctype": "CFG Kanban Process Execution", "kanban_cycle": cycle.name,
            "kanban_master": master.name, "operation": job.operation, "sequence": profile.sequence,
            "job_card": job.name, "workstation": job.workstation, "status": "Ready" if (
                profile.start_rule == "No Dependency" or profile.allow_parallel) else "Not Ready",
            "target_qty": cycle.planned_qty, "allow_parallel": profile.allow_parallel,
            "handoff_mode": profile.handoff_mode, "transfer_multiple": profile.transfer_multiple,
            "operation_profile_revision": master.revision,
        }).insert(ignore_permissions=True)
        created[job.operation] = execution.name
    for operation, execution_name in created.items():
        destination = profiles.get(operation).destination_operation if profiles.get(operation) else None
        if destination and created.get(destination):
            frappe.db.set_value("CFG Kanban Process Execution", execution_name,
                                "destination_execution", created[destination])
