import frappe
from frappe.utils import flt

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
