import math

import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record


SIGNS = {"Produced": 1, "Released": 1, "Consumed": -1, "Returned": 1, "Rejected": -1, "Adjusted": 1}


def append_entry(cycle, transaction_type, qty, *, source_execution=None, destination_execution=None,
                 source_operation=None, destination_operation=None,
                 item_code=None, stock_uom=None, source_progress=None, notes=None):
    if transaction_type not in SIGNS:
        frappe.throw("Unsupported WIP transaction type")
    entry = frappe.get_doc({
        "doctype": "CFG Kanban WIP Ledger", "kanban_cycle": cycle,
        "source_execution": source_execution, "destination_execution": destination_execution,
        "source_operation": source_operation, "destination_operation": destination_operation,
        "item_code": item_code, "transaction_type": transaction_type, "qty": flt(qty),
        "stock_uom": stock_uom, "posting_datetime": now_datetime(),
        "source_progress": source_progress, "notes": notes,
    }).insert(ignore_permissions=True)
    event = record(f"WIP {transaction_type}", cycle=cycle, execution=source_execution,
                   qty=qty, reference_doctype=entry.doctype, reference_name=entry.name)
    entry.db_set("reference_event", event.name, update_modified=False)
    return entry


def available_qty(cycle, source_execution, destination_execution):
    rows = frappe.get_all("CFG Kanban WIP Ledger",
        filters={"kanban_cycle": cycle, "source_execution": source_execution,
                 "destination_execution": destination_execution}, fields=["transaction_type", "qty"])
    return sum(SIGNS[row.transaction_type] * flt(row.qty) for row in rows if row.transaction_type != "Produced")


def available_operation_qty(cycle, source_operation, destination_operation):
    rows = frappe.get_all("CFG Kanban WIP Ledger", filters={
        "kanban_cycle": cycle, "source_operation": source_operation,
        "destination_operation": destination_operation,
    }, fields=["transaction_type", "qty"])
    return sum(SIGNS[row.transaction_type] * flt(row.qty)
               for row in rows if row.transaction_type != "Produced")


def releasable_increment(total_good, already_released, transfer_multiple):
    multiple = flt(transfer_multiple)
    eligible = flt(total_good) if multiple <= 0 else math.floor(flt(total_good) / multiple) * multiple
    return max(0, eligible - flt(already_released))
