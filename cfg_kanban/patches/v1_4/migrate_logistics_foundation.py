import frappe
from frappe.utils import flt

from cfg_kanban.services.logistics_foundation import (
    post_quantity_event,
    rebuild_handling_unit_balance,
)


MOVEMENT_STATE = {
    "Issued": "At Source",
    "Attached": "Packed",
    "Dispatched": "Loaded",
    "Received": "Received",
    "Void": "Empty",
    "Replaced": "Empty",
}


def execute():
    _set_company_snapshots()
    _migrate_handling_units()


def _set_company_snapshots():
    if frappe.db.table_exists("CFG Kanban Card"):
        frappe.db.sql(
            """
            update `tabCFG Kanban Card` card
            inner join `tabCFG Kanban Master` master on master.name = card.kanban_master
            set card.company = master.company
            where ifnull(card.company, '') = ''
            """
        )
    if frappe.db.table_exists("CFG Kanban Cycle"):
        frappe.db.sql(
            """
            update `tabCFG Kanban Cycle` cycle
            inner join `tabCFG Kanban Master` master on master.name = cycle.kanban_master
            set cycle.company = master.company
            where ifnull(cycle.company, '') = ''
            """
        )


def _migrate_handling_units():
    if not frappe.db.table_exists("CFG Kanban Handling Unit"):
        return
    rows = frappe.get_all(
        "CFG Kanban Handling Unit",
        fields=[
            "name", "state", "qty", "stock_uom", "item_code", "batch_no", "kanban_cycle",
            "creation", "current_qty", "inventory_company", "current_warehouse",
        ],
        limit_page_length=0,
    )
    for row in rows:
        cycle = _cycle_context(row.kanban_cycle)
        company = row.inventory_company or cycle.get("company")
        warehouse = row.current_warehouse or _warehouse_for_state(row.state, cycle)
        if warehouse and frappe.db.get_value("Warehouse", warehouse, "company") != company:
            warehouse = None
        identity_state = "Void" if row.state == "Void" else (
            "Replaced" if row.state == "Replaced" else "Active"
        )
        target_qty = 0 if row.state in {"Void", "Replaced"} else flt(row.qty)
        opening_key = f"migration-v1.4-opening:{row.name}"
        opening_exists = frappe.db.exists(
            "CFG Kanban Handling Unit Quantity Ledger", {"idempotency_key": opening_key}
        )
        values = {
            "tag_kind": "Main Stock Tag",
            "root_handling_unit": row.name,
            "identity_state": identity_state,
            "movement_state": MOVEMENT_STATE.get(row.state, "At Source"),
            "quality_state": "Released",
            "inventory_company": company,
            "current_warehouse": warehouse,
            "packed_on": row.creation,
            "expiry_date": (
                frappe.db.get_value("Batch", row.batch_no, "expiry_date")
                if row.batch_no else None
            ),
            "original_qty": flt(row.qty),
        }
        if not opening_exists:
            values.update({"current_qty": 0, "reserved_qty": 0, "available_qty": 0})
        frappe.db.set_value("CFG Kanban Handling Unit", row.name, values, update_modified=False)
        if opening_exists:
            rebuild_handling_unit_balance(row.name, apply=True)
            continue
        if target_qty <= 0 or not row.stock_uom:
            continue
        post_quantity_event(
            event_type="Opening Balance",
            qty=target_qty,
            stock_uom=row.stock_uom,
            idempotency_key=opening_key,
            destination_handling_unit=row.name,
            item_code=row.item_code,
            batch_no=row.batch_no,
            destination_company=company,
            destination_warehouse=warehouse,
            reference_doctype="CFG Kanban Handling Unit",
            reference_name=row.name,
            reason="Package A migration opening balance",
            posting_datetime=row.creation,
        )


def _cycle_context(cycle_name):
    if not cycle_name:
        return frappe._dict()
    return frappe.db.get_value(
        "CFG Kanban Cycle",
        cycle_name,
        ["company", "source_warehouse", "destination_warehouse"],
        as_dict=True,
    ) or frappe._dict()


def _warehouse_for_state(state, cycle):
    if state == "Received":
        return cycle.get("destination_warehouse")
    return cycle.get("source_warehouse") or cycle.get("destination_warehouse")
