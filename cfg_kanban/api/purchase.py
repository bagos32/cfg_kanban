import frappe

from cfg_kanban.services.purchase_replenishment import (
    PURCHASE_ROLES, create_purchase_receipt_command, link_purchase_order,
    receipt_context,
)


def _require_purchase_role():
    if not set(PURCHASE_ROLES).intersection(frappe.get_roles(frappe.session.user)):
        frappe.throw("A purchasing, stock, manufacturing manager, or system manager role is required",
                     frappe.PermissionError)


@frappe.whitelist()
def get_receipt_context(cycle_name):
    _require_purchase_role()
    return receipt_context(cycle_name)


@frappe.whitelist()
def select_purchase_order(cycle_name, purchase_order_name, reason):
    _require_purchase_role()
    if not reason:
        frappe.throw("Selection reason is required for the audit trail")
    return link_purchase_order(cycle_name, purchase_order_name, reason)


@frappe.whitelist()
def receive_purchase(cycle_name, delivered_qty, accepted_qty, rejected_qty=0,
                     warehouse=None, rejected_warehouse=None,
                     supplier_delivery_note=None, event_token=None):
    _require_purchase_role()
    return create_purchase_receipt_command(
        cycle_name, delivered_qty, accepted_qty, rejected_qty,
        warehouse=warehouse, rejected_warehouse=rejected_warehouse,
        supplier_delivery_note=supplier_delivery_note, event_token=event_token,
    )
