import frappe

from cfg_kanban.services.purchase_replenishment import (
    PURCHASE_ROLES, continue_purchase_execution, create_purchase_receipt_command,
    link_purchase_order, receipt_context,
)
from cfg_kanban.services.purchase_disposition import (
    approve_concession, confirm_disposal, reconcile_purchase_cycle, set_disposition, short_close,
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
def retry_purchase_execution(cycle_name):
    _require_purchase_role()
    return continue_purchase_execution(cycle_name)


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


@frappe.whitelist()
def refresh_receipt_disposition(cycle_name):
    _require_purchase_role()
    return reconcile_purchase_cycle(cycle_name).as_dict()


@frappe.whitelist()
def choose_receipt_disposition(disposition_name, disposition, reason):
    return set_disposition(disposition_name, disposition, reason).as_dict()


@frappe.whitelist()
def accept_rejected_by_concession(disposition_name, stock_entry, qty, reason):
    return approve_concession(disposition_name, stock_entry, qty, reason).as_dict()


@frappe.whitelist()
def confirm_rejected_disposal(disposition_name, stock_entry, qty, reason):
    return confirm_disposal(disposition_name, stock_entry, qty, reason).as_dict()


@frappe.whitelist()
def short_close_purchase_cycle(cycle_name, qty, reason):
    return short_close(cycle_name, qty, reason).as_dict()
