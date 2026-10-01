import frappe
from frappe.utils import now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import post_quantity_event


def on_delivery_note_submit(doc, method=None):
    manifest_name = doc.get("cfg_movement_manifest")
    if not manifest_name:
        return
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    if doc.company != manifest.source_company:
        frappe.throw("Delivery Note Company does not match the Movement Manifest source Company")
    manifest.db_set({"dispatch_delivery_note": doc.name, "state": "Awaiting Receipt"},
                    update_modified=True)
    for line in manifest.lines:
        post_quantity_event(
            event_type="Location Transfer", qty=line.dispatch_qty, stock_uom=line.stock_uom,
            idempotency_key=canonical_key("manifest-dispatch-posted", manifest.name, line.name),
            source_handling_unit=line.handling_unit, item_code=line.item_code,
            batch_no=line.batch_no, source_company=manifest.source_company,
            destination_company=manifest.destination_company,
            source_warehouse=manifest.source_warehouse,
            reference_doctype="Delivery Note", reference_name=doc.name,
            reason="Submitted intercompany dispatch Delivery Note",
        )
        frappe.db.set_value("CFG Kanban Handling Unit", line.handling_unit, {
            "movement_state": "Intercompany Transit",
            "current_warehouse": None,
            "state": "Dispatched",
            "last_scan_time": now_datetime(),
        }, update_modified=False)
        frappe.db.set_value("CFG Kanban Manifest Line", line.name, "state", "In Transit",
                            update_modified=False)
    record("Intercompany Dispatch Posted", movement_manifest=manifest.name,
           previous_state="Dispatch Document Pending", new_state="Awaiting Receipt",
           qty=manifest.total_quantity, reference_doctype="Delivery Note",
           reference_name=doc.name)


def on_delivery_note_cancel(doc, method=None):
    manifest_name = doc.get("cfg_movement_manifest")
    if not manifest_name:
        return
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    if manifest.receipt_purchase_receipt and frappe.db.get_value(
        "Purchase Receipt", manifest.receipt_purchase_receipt, "docstatus"
    ) == 1:
        frappe.throw(
            "Cannot cancel dispatch Delivery Note after the destination Purchase Receipt is submitted"
        )
    for line in manifest.lines:
        unit = frappe.get_doc("CFG Kanban Handling Unit", line.handling_unit)
        if unit.reserved_qty:
            post_quantity_event(
                event_type="Unreserve", qty=min(line.dispatch_qty, unit.reserved_qty),
                stock_uom=line.stock_uom,
                idempotency_key=canonical_key("manifest-dispatch-cancel-unreserve",
                                              manifest.name, line.name),
                source_handling_unit=line.handling_unit, item_code=line.item_code,
                batch_no=line.batch_no, source_company=manifest.source_company,
                source_warehouse=manifest.source_warehouse,
                reference_doctype="Delivery Note", reference_name=doc.name,
                reason="Intercompany dispatch Delivery Note cancelled",
            )
        frappe.db.set_value("CFG Kanban Handling Unit", line.handling_unit, {
            "inventory_company": manifest.source_company,
            "current_warehouse": manifest.source_warehouse,
            "movement_state": "Packed",
            "state": "Attached",
        }, update_modified=False)
        frappe.db.set_value("CFG Kanban Manifest Line", line.name, "state", "Exception",
                            update_modified=False)
    _raise_manifest_exception(
        manifest, "Dispatch Delivery Note Cancelled",
        f"Delivery Note {doc.name} was cancelled; source stock was restored and supervisor review is required",
        "Delivery Note", doc.name,
    )


def on_purchase_receipt_submit(doc, method=None):
    manifest_name = doc.get("cfg_movement_manifest")
    if not manifest_name:
        return
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    if doc.company != manifest.destination_company:
        frappe.throw("Purchase Receipt Company does not match the Manifest destination Company")
    if not manifest.dispatch_delivery_note or frappe.db.get_value(
        "Delivery Note", manifest.dispatch_delivery_note, "docstatus"
    ) != 1:
        frappe.throw("The source Delivery Note must remain submitted before receiving the Manifest")
    for line in manifest.lines:
        unit = frappe.get_doc("CFG Kanban Handling Unit", line.handling_unit)
        if unit.reserved_qty:
            post_quantity_event(
                event_type="Unreserve", qty=min(line.dispatch_qty, unit.reserved_qty),
                stock_uom=line.stock_uom,
                idempotency_key=canonical_key("manifest-receipt-unreserve", manifest.name, line.name),
                source_handling_unit=line.handling_unit, item_code=line.item_code,
                batch_no=line.batch_no, source_company=manifest.source_company,
                destination_company=manifest.destination_company,
                destination_warehouse=manifest.destination_warehouse,
                reference_doctype="Purchase Receipt", reference_name=doc.name,
                reason="Destination Purchase Receipt submitted",
            )
        post_quantity_event(
            event_type="Location Transfer", qty=line.dispatch_qty, stock_uom=line.stock_uom,
            idempotency_key=canonical_key("manifest-receipt-posted", manifest.name, line.name),
            source_handling_unit=line.handling_unit, item_code=line.item_code,
            batch_no=line.batch_no, source_company=manifest.source_company,
            destination_company=manifest.destination_company,
            destination_warehouse=manifest.destination_warehouse,
            reference_doctype="Purchase Receipt", reference_name=doc.name,
            reason="Submitted destination Purchase Receipt",
        )
        frappe.db.set_value("CFG Kanban Handling Unit", line.handling_unit, {
            "inventory_company": manifest.destination_company,
            "current_warehouse": manifest.destination_warehouse,
            "movement_state": "Received",
            "state": "Received",
            "last_scan_time": now_datetime(),
        }, update_modified=False)
        frappe.db.set_value("CFG Kanban Manifest Line", line.name, {
            "state": "Received", "received_qty": line.dispatch_qty,
        }, update_modified=False)
    manifest.db_set({"receipt_purchase_receipt": doc.name, "state": "Received",
                     "total_received_quantity": manifest.total_quantity}, update_modified=True)
    if manifest.dispatch_delivery_note:
        frappe.db.set_value("Delivery Note", manifest.dispatch_delivery_note,
                            "cfg_counterpart_document", doc.name, update_modified=False)
    record("Intercompany Receipt Posted", movement_manifest=manifest.name,
           previous_state="Receipt Document Pending", new_state="Received",
           qty=manifest.total_quantity, reference_doctype="Purchase Receipt",
           reference_name=doc.name)


def on_purchase_receipt_cancel(doc, method=None):
    manifest_name = doc.get("cfg_movement_manifest")
    if not manifest_name:
        return
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    for line in manifest.lines:
        unit = frappe.get_doc("CFG Kanban Handling Unit", line.handling_unit)
        if not unit.reserved_qty:
            post_quantity_event(
                event_type="Reserve", qty=line.dispatch_qty, stock_uom=line.stock_uom,
                idempotency_key=canonical_key("manifest-receipt-cancel-reserve",
                                              manifest.name, line.name),
                source_handling_unit=line.handling_unit, item_code=line.item_code,
                batch_no=line.batch_no, source_company=manifest.source_company,
                destination_company=manifest.destination_company,
                reference_doctype="Purchase Receipt", reference_name=doc.name,
                reason="Destination Purchase Receipt cancelled; stock returned to transit control",
            )
        frappe.db.set_value("CFG Kanban Handling Unit", line.handling_unit, {
            "inventory_company": manifest.source_company,
            "current_warehouse": None,
            "movement_state": "Intercompany Transit",
            "state": "Dispatched",
        }, update_modified=False)
        frappe.db.set_value("CFG Kanban Manifest Line", line.name, {
            "state": "Exception", "received_qty": 0,
        }, update_modified=False)
    _raise_manifest_exception(
        manifest, "Receipt Purchase Receipt Cancelled",
        f"Purchase Receipt {doc.name} was cancelled; tags returned to transit control",
        "Purchase Receipt", doc.name,
    )


def _raise_manifest_exception(manifest, exception_type, message, reference_doctype,
                              reference_name):
    exception = frappe.get_doc({
        "doctype": "CFG Kanban Exception",
        "exception_type": exception_type,
        "severity": "Critical",
        "status": "Open",
        "movement_manifest": manifest.name,
        "message": message,
        "reference_doctype": reference_doctype,
        "reference_name": reference_name,
        "raised_on": now_datetime(),
    }).insert(ignore_permissions=True)
    manifest.db_set({"state": "Exception", "exception": exception.name}, update_modified=True)
    return exception
