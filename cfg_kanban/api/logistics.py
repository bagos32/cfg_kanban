import frappe
from frappe.utils import flt, now_datetime, today

from cfg_kanban.integrations.erp_gateway import execute_command
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, insert_once
from cfg_kanban.services.logistics_foundation import (
    post_quantity_event,
    resolve_logistics_scan,
)
from cfg_kanban.services.operator_auth import require_operator


TERMINAL_STATES = {"Received", "Billing Pending", "Partially Billed", "Billed", "Closed", "Cancelled"}


@frappe.whitelist()
def get_logistics_console(operator_session_token):
    profile, session = require_operator(operator_session_token)
    responsibilities = _responsibilities(profile)
    routes = frappe.get_all(
        "CFG Kanban Logistics Route",
        filters={"active": 1},
        fields=["name", "route_name", "source_company", "source_warehouse",
                "destination_company", "destination_warehouse", "handover_mode",
                "dispatch_responsibility", "receipt_responsibility"],
        order_by="route_name asc",
    )
    if not _can_view_all(profile):
        routes = [route for route in routes if (
            route.dispatch_responsibility in responsibilities or
            route.receipt_responsibility in responsibilities
        )]
    for route in routes:
        route["can_dispatch"] = bool(
            _can_view_all(profile) or route.dispatch_responsibility in responsibilities
        )
        route["can_receive"] = bool(
            _can_view_all(profile) or route.receipt_responsibility in responsibilities
        )
    manifests = frappe.get_all(
        "CFG Kanban Movement Manifest",
        filters={"state": ["not in", list(TERMINAL_STATES)]},
        fields=["name", "logistics_route", "state", "source_company", "source_warehouse",
                "destination_company", "destination_warehouse", "total_quantity",
                "total_received_quantity", "dispatch_delivery_note",
                "receipt_purchase_receipt", "modified"],
        order_by="modified desc", limit_page_length=100,
    )
    allowed_routes = {route.name for route in routes}
    manifests = [row for row in manifests if row.logistics_route in allowed_routes]
    return {"operator": _operator_summary(profile, session), "routes": routes,
            "manifests": manifests}


@frappe.whitelist()
def create_manifest(logistics_route, event_token, operator_session_token):
    profile, session = require_operator(operator_session_token, "start")
    route = frappe.get_doc("CFG Kanban Logistics Route", logistics_route)
    _require_route_responsibility(profile, route.dispatch_responsibility, "dispatch")
    if not route.active:
        frappe.throw("The selected Logistics Route is inactive")
    if not event_token:
        frappe.throw("A stable event token is required to create a Manifest")
    key = canonical_key("movement-manifest", route.name, event_token)
    existing = frappe.db.get_value(
        "CFG Kanban Movement Manifest", {"preparation_key": key}, "name"
    )
    if existing:
        return get_manifest(existing, operator_session_token)
    manifest = frappe.get_doc({
        "doctype": "CFG Kanban Movement Manifest",
        "logistics_route": route.name,
        "state": "Draft",
        "preparation_key": key,
        "created_by_operator": profile.employee,
        "created_operator_session": session.name,
    }).insert(ignore_permissions=True)
    record("Movement Manifest Created", movement_manifest=manifest.name,
           previous_state=None, new_state="Draft", reference_doctype=manifest.doctype,
           reference_name=manifest.name, device_id=key, operator=profile.employee,
           operator_session=session.name, terminal_user=session.terminal_user)
    return get_manifest(manifest.name, operator_session_token)


@frappe.whitelist()
def get_manifest(manifest_name, operator_session_token):
    profile, session = require_operator(operator_session_token)
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    route = frappe.get_doc("CFG Kanban Logistics Route", manifest.logistics_route)
    responsibilities = _responsibilities(profile)
    if not _can_view_all(profile) and not {
        route.dispatch_responsibility, route.receipt_responsibility
    }.intersection(responsibilities):
        frappe.throw("Operator is not assigned to this Logistics Route")
    result = manifest.as_dict()
    result["dispatch_document_status"] = _document_status(
        "Delivery Note", manifest.dispatch_delivery_note
    )
    result["receipt_document_status"] = _document_status(
        "Purchase Receipt", manifest.receipt_purchase_receipt
    )
    result["can_dispatch"] = (
        manifest.state in ("Draft", "Prepared") and
        (_can_view_all(profile) or route.dispatch_responsibility in responsibilities)
    )
    result["can_receive"] = (
        manifest.state in ("Dispatched", "Awaiting Receipt", "Receipt Document Pending") and
        (_can_view_all(profile) or route.receipt_responsibility in responsibilities)
    )
    result["operator"] = _operator_summary(profile, session)
    return result


@frappe.whitelist()
def scan_dispatch_tag(manifest_name, scan_value, event_token, operator_session_token):
    profile, session = require_operator(operator_session_token, "start")
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    route = frappe.get_doc("CFG Kanban Logistics Route", manifest.logistics_route)
    _require_route_responsibility(profile, route.dispatch_responsibility, "dispatch")
    if manifest.state != "Draft":
        frappe.throw("Dispatch tags can only be added while the Manifest is Draft")
    identity = resolve_logistics_scan(scan_value)
    if not identity:
        frappe.throw("Preprinted Stock Tag was not found")
    if identity["identity_type"] == "Registered Tag Identity":
        frappe.throw(
            f"Tag {identity['visible_code']} is registered but not activated as a Handling Unit"
        )
    if identity["identity_type"] != "Handling Unit":
        frappe.throw(f"{identity['visible_code']} is not a Handling Unit tag")
    unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    _validate_dispatch_unit(unit, manifest)
    if any(row.handling_unit == unit.name for row in manifest.lines):
        return get_manifest(manifest.name, operator_session_token)
    _assert_not_in_other_open_manifest(unit.name, manifest.name)
    _assert_erp_stock(unit, manifest.source_warehouse, unit.available_qty)
    if not event_token:
        frappe.throw("A stable scan event token is required")
    event_key = canonical_key("manifest-dispatch-scan", manifest.name, unit.name, event_token)
    if frappe.db.get_value("CFG Kanban Event", {"device_id": event_key}, "name"):
        return get_manifest(manifest.name, operator_session_token)
    manifest.append("lines", {
        "handling_unit": unit.name,
        "visible_code": unit.handling_unit_id,
        "tag_kind": unit.tag_kind,
        "item_code": unit.item_code,
        "batch_no": unit.batch_no,
        "stock_uom": unit.stock_uom,
        "available_qty_at_scan": unit.available_qty,
        "dispatch_qty": unit.available_qty,
        "received_qty": 0,
        "source_company": manifest.source_company,
        "source_warehouse": manifest.source_warehouse,
        "destination_company": manifest.destination_company,
        "destination_warehouse": manifest.destination_warehouse,
        "state": "Prepared",
        "scan_event_key": event_key,
        "scanned_by": profile.employee,
        "scanned_on": now_datetime(),
    })
    manifest.save(ignore_permissions=True)
    record("Manifest Dispatch Tag Scanned", movement_manifest=manifest.name,
           handling_unit=unit.name, qty=unit.available_qty,
           reference_doctype=unit.doctype, reference_name=unit.name,
           device_id=event_key, operator=profile.employee,
           operator_session=session.name, terminal_user=session.terminal_user)
    return get_manifest(manifest.name, operator_session_token)


@frappe.whitelist()
def remove_dispatch_tag(manifest_name, handling_unit, operator_session_token):
    profile, session = require_operator(operator_session_token, "start")
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    route = frappe.get_doc("CFG Kanban Logistics Route", manifest.logistics_route)
    _require_route_responsibility(profile, route.dispatch_responsibility, "dispatch")
    if manifest.state != "Draft":
        frappe.throw("Tags can only be removed while the Manifest is Draft")
    row = next((row for row in manifest.lines if row.handling_unit == handling_unit), None)
    if not row:
        return get_manifest(manifest.name, operator_session_token)
    manifest.remove(row)
    manifest.save(ignore_permissions=True)
    record("Manifest Dispatch Tag Removed", movement_manifest=manifest.name,
           handling_unit=handling_unit, reference_doctype=manifest.doctype,
           reference_name=manifest.name, operator=profile.employee,
           operator_session=session.name, terminal_user=session.terminal_user)
    return get_manifest(manifest.name, operator_session_token)


@frappe.whitelist()
def prepare_manifest(manifest_name, event_token, operator_session_token):
    profile, session = require_operator(operator_session_token, "complete")
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    route = frappe.get_doc("CFG Kanban Logistics Route", manifest.logistics_route)
    _require_route_responsibility(profile, route.dispatch_responsibility, "dispatch")
    if manifest.state == "Prepared":
        return get_manifest(manifest.name, operator_session_token)
    if manifest.state != "Draft" or not manifest.lines:
        frappe.throw("A Draft Manifest with at least one scanned tag is required")
    for row in manifest.lines:
        unit = frappe.get_doc("CFG Kanban Handling Unit", row.handling_unit)
        _validate_dispatch_unit(unit, manifest)
        if abs(flt(row.dispatch_qty) - flt(unit.available_qty)) > 0.000001:
            frappe.throw(
                f"Tag {unit.handling_unit_id} quantity changed. Rescan it before preparation."
            )
        _assert_erp_stock(unit, manifest.source_warehouse, row.dispatch_qty)
        post_quantity_event(
            event_type="Reserve", qty=row.dispatch_qty, stock_uom=row.stock_uom,
            idempotency_key=canonical_key("manifest-reserve", manifest.name, row.name),
            source_handling_unit=row.handling_unit, item_code=row.item_code,
            batch_no=row.batch_no, source_company=manifest.source_company,
            source_warehouse=manifest.source_warehouse,
            reference_doctype=manifest.doctype, reference_name=manifest.name,
            operator=profile.employee, operator_session=session.name,
            reason="Reserved for intercompany Movement Manifest",
        )
    manifest.db_set({"state": "Prepared", "prepared_on": now_datetime()},
                    update_modified=True)
    record("Movement Manifest Prepared", movement_manifest=manifest.name,
           previous_state="Draft", new_state="Prepared", qty=manifest.total_quantity,
           reference_doctype=manifest.doctype, reference_name=manifest.name,
           device_id=canonical_key("manifest-prepare", manifest.name, event_token or ""),
           operator=profile.employee, operator_session=session.name,
           terminal_user=session.terminal_user)
    return get_manifest(manifest.name, operator_session_token)


@frappe.whitelist()
def confirm_dispatch(manifest_name, event_token, operator_session_token):
    profile, session = require_operator(operator_session_token, "complete")
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    route = frappe.get_doc("CFG Kanban Logistics Route", manifest.logistics_route)
    _require_route_responsibility(profile, route.dispatch_responsibility, "dispatch")
    if manifest.state not in ("Prepared", "Dispatch Document Pending"):
        frappe.throw(f"Manifest cannot dispatch while it is {manifest.state}")
    key = canonical_key("manifest-dispatch", manifest.name)
    payload = _dispatch_payload(manifest)
    command, _created = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command",
        "command_type": "Create Intercompany Delivery Note",
        "movement_manifest": manifest.name,
        "status": "Pending",
        "target_doctype": "Delivery Note",
        "request_payload": frappe.as_json(payload),
        "requested_by_operator": profile.employee,
        "operator_session": session.name,
        "terminal_user": session.terminal_user,
        "requested_on": now_datetime(),
        "created_by_system": 1,
    }), key, ignore_permissions=True)
    manifest.db_set({"dispatch_key": key, "dispatch_command": command.name,
                     "dispatch_confirmed_by": profile.employee,
                     "dispatch_operator_session": session.name,
                     "dispatch_confirmed_on": now_datetime(),
                     "state": "Dispatch Document Pending"}, update_modified=True)
    try:
        delivery_note = execute_command(command.name)
    except Exception:
        _manifest_exception(manifest, "Dispatch ERP Command Failed",
                            "Delivery Note creation or submission failed", command.name)
        raise
    manifest.reload()
    if delivery_note.docstatus == 0:
        manifest.db_set({"dispatch_delivery_note": delivery_note.name,
                         "state": "Dispatch Document Pending"}, update_modified=True)
    return get_manifest(manifest.name, operator_session_token)


@frappe.whitelist()
def scan_receipt_tag(manifest_name, scan_value, event_token, operator_session_token):
    profile, session = require_operator(operator_session_token, "start")
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    route = frappe.get_doc("CFG Kanban Logistics Route", manifest.logistics_route)
    _require_route_responsibility(profile, route.receipt_responsibility, "receipt")
    if manifest.state not in ("Dispatched", "Awaiting Receipt", "Receipt Document Pending"):
        frappe.throw("Receipt scanning requires a submitted dispatch Delivery Note")
    identity = resolve_logistics_scan(scan_value)
    if not identity or identity["identity_type"] != "Handling Unit":
        frappe.throw("The scanned code is not an active Handling Unit")
    row = next((row for row in manifest.lines if row.handling_unit == identity["name"]), None)
    if not row:
        frappe.throw("This Handling Unit is not listed on the selected Manifest")
    if row.receipt_scanned:
        return get_manifest(manifest.name, operator_session_token)
    if not event_token:
        frappe.throw("A stable receipt scan event token is required")
    row.receipt_scanned = 1
    row.received_qty = row.dispatch_qty
    row.receipt_scanned_by = profile.employee
    row.receipt_scanned_on = now_datetime()
    row.state = "Receipt Pending"
    manifest.save(ignore_permissions=True)
    record("Manifest Receipt Tag Scanned", movement_manifest=manifest.name,
           handling_unit=row.handling_unit, qty=row.dispatch_qty,
           reference_doctype=manifest.doctype, reference_name=manifest.name,
           device_id=canonical_key("manifest-receipt-scan", manifest.name,
                                   row.handling_unit, event_token),
           operator=profile.employee, operator_session=session.name,
           terminal_user=session.terminal_user)
    return get_manifest(manifest.name, operator_session_token)


@frappe.whitelist()
def confirm_receipt(manifest_name, event_token, operator_session_token):
    profile, session = require_operator(operator_session_token, "complete")
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    route = frappe.get_doc("CFG Kanban Logistics Route", manifest.logistics_route)
    _require_route_responsibility(profile, route.receipt_responsibility, "receipt")
    if manifest.state not in ("Dispatched", "Awaiting Receipt", "Receipt Document Pending"):
        frappe.throw(f"Manifest cannot be received while it is {manifest.state}")
    if not manifest.lines or any(not row.receipt_scanned for row in manifest.lines):
        frappe.throw("Receiving operator must scan every Manifest tag before confirmation")
    delivery_status = _document_status("Delivery Note", manifest.dispatch_delivery_note)
    if not delivery_status or delivery_status["docstatus"] != 1:
        frappe.throw("Dispatch Delivery Note must be submitted before receipt can be posted")
    key = canonical_key("manifest-receipt", manifest.name)
    payload = _receipt_payload(manifest)
    command, _created = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command",
        "command_type": "Create Intercompany Purchase Receipt",
        "movement_manifest": manifest.name,
        "status": "Pending",
        "target_doctype": "Purchase Receipt",
        "request_payload": frappe.as_json(payload),
        "requested_by_operator": profile.employee,
        "operator_session": session.name,
        "terminal_user": session.terminal_user,
        "requested_on": now_datetime(),
        "created_by_system": 1,
    }), key, ignore_permissions=True)
    manifest.db_set({"receipt_key": key, "receipt_command": command.name,
                     "receipt_confirmed_by": profile.employee,
                     "receipt_operator_session": session.name,
                     "receipt_confirmed_on": now_datetime(),
                     "state": "Receipt Document Pending"}, update_modified=True)
    try:
        receipt = execute_command(command.name)
    except Exception:
        _manifest_exception(manifest, "Receipt ERP Command Failed",
                            "Purchase Receipt creation or submission failed", command.name)
        raise
    manifest.reload()
    if receipt.docstatus == 0:
        manifest.db_set({"receipt_purchase_receipt": receipt.name,
                         "state": "Receipt Document Pending"}, update_modified=True)
    return get_manifest(manifest.name, operator_session_token)


@frappe.whitelist()
def cancel_manifest(manifest_name, reason, operator_session_token, event_token=None):
    profile, session = require_operator(operator_session_token, "override")
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    if manifest.state not in ("Draft", "Prepared"):
        frappe.throw("Only a Draft or Prepared Manifest without ERP documents can be cancelled")
    if manifest.dispatch_delivery_note or manifest.receipt_purchase_receipt:
        frappe.throw("Manifest has an ERP document and requires controlled recovery")
    if not reason:
        frappe.throw("Cancellation reason is required")
    if manifest.state == "Prepared":
        for row in manifest.lines:
            post_quantity_event(
                event_type="Unreserve", qty=row.dispatch_qty, stock_uom=row.stock_uom,
                idempotency_key=canonical_key("manifest-cancel-unreserve", manifest.name, row.name),
                source_handling_unit=row.handling_unit, item_code=row.item_code,
                batch_no=row.batch_no, source_company=manifest.source_company,
                source_warehouse=manifest.source_warehouse,
                reference_doctype=manifest.doctype, reference_name=manifest.name,
                operator=profile.employee, operator_session=session.name, reason=reason,
            )
    previous = manifest.state
    manifest.db_set({"state": "Cancelled", "cancelled_by": profile.employee,
                     "cancelled_on": now_datetime(), "cancellation_reason": reason},
                    update_modified=True)
    frappe.db.set_value("CFG Kanban Manifest Line", {"parent": manifest.name},
                        "state", "Cancelled", update_modified=False)
    record("Movement Manifest Cancelled", movement_manifest=manifest.name,
           previous_state=previous, new_state="Cancelled",
           reference_doctype=manifest.doctype, reference_name=manifest.name,
           notes=reason, operator=profile.employee, operator_session=session.name,
           terminal_user=session.terminal_user)
    return get_manifest(manifest.name, operator_session_token)


def _validate_dispatch_unit(unit, manifest):
    if unit.identity_state != "Active":
        frappe.throw(f"Tag {unit.handling_unit_id} is {unit.identity_state}, not Active")
    if unit.quality_state != "Released":
        frappe.throw(f"Tag {unit.handling_unit_id} quality state is {unit.quality_state}")
    if unit.inventory_company != manifest.source_company:
        frappe.throw(
            f"Tag {unit.handling_unit_id} belongs to inventory Company {unit.inventory_company}, "
            f"not route source {manifest.source_company}"
        )
    if unit.current_warehouse != manifest.source_warehouse:
        frappe.throw(
            f"Tag {unit.handling_unit_id} is in {unit.current_warehouse}, "
            f"not route source Warehouse {manifest.source_warehouse}"
        )
    if unit.tag_kind == "Reusable Container" or not unit.item_code:
        frappe.throw("Reusable/mixed container handover is reserved for Package C")
    if flt(unit.available_qty) <= 0:
        frappe.throw(f"Tag {unit.handling_unit_id} has no available quantity")
    if flt(unit.reserved_qty):
        frappe.throw(f"Tag {unit.handling_unit_id} already has reserved quantity")


def _assert_not_in_other_open_manifest(handling_unit, current_manifest):
    rows = frappe.db.sql(
        """
        select line.parent
        from `tabCFG Kanban Manifest Line` line
        inner join `tabCFG Kanban Movement Manifest` manifest on manifest.name=line.parent
        where line.handling_unit=%s and line.parent<>%s
          and manifest.state not in ('Received','Billing Pending','Partially Billed','Billed',
                                     'Closed','Cancelled')
        limit 1
        """,
        (handling_unit, current_manifest),
    )
    if rows:
        frappe.throw(f"Handling Unit is already assigned to open Manifest {rows[0][0]}")


def _assert_erp_stock(unit, warehouse, qty):
    from erpnext.stock.utils import get_stock_balance

    balance = get_stock_balance(
        unit.item_code, warehouse, posting_date=today(), batch_no=unit.batch_no
    )
    if flt(balance) + 0.000001 < flt(qty):
        frappe.throw(
            f"ERPNext stock for {unit.item_code} / {unit.batch_no or 'no batch'} in "
            f"{warehouse} is {balance}, below tag quantity {qty}"
        )


def _dispatch_payload(manifest):
    return {
        "manifest": manifest.name,
        "company": manifest.source_company,
        "warehouse": manifest.source_warehouse,
        "customer": manifest.internal_customer,
        "price_list": manifest.selling_price_list,
        "counterpart_company": manifest.destination_company,
        "submit": bool(manifest.auto_submit_dispatch_dn),
        "items": [_priced_line(manifest, row, "selling") for row in manifest.lines],
    }


def _receipt_payload(manifest):
    return {
        "manifest": manifest.name,
        "company": manifest.destination_company,
        "warehouse": manifest.destination_warehouse,
        "supplier": manifest.internal_supplier,
        "price_list": manifest.buying_price_list,
        "counterpart_company": manifest.source_company,
        "counterpart_document": manifest.dispatch_delivery_note,
        "submit": bool(manifest.auto_submit_receipt_pr),
        "items": [_priced_line(manifest, row, "buying") for row in manifest.lines],
    }


def _priced_line(manifest, row, mode):
    price_list = manifest.selling_price_list if mode == "selling" else manifest.buying_price_list
    party = manifest.internal_customer if mode == "selling" else manifest.internal_supplier
    return {
        "manifest_line": row.name,
        "handling_unit": row.handling_unit,
        "item_code": row.item_code,
        "batch_no": row.batch_no,
        "uom": row.stock_uom,
        "qty": row.dispatch_qty,
        "rate": _price_list_rate(price_list, row.item_code, row.stock_uom, row.batch_no,
                                 mode, party),
    }


def _price_list_rate(price_list, item_code, uom, batch_no, mode, party):
    party_field = "customer" if mode == "selling" else "supplier"
    fields = ["name", "price_list_rate", "uom", "batch_no", "valid_from", "valid_upto"]
    if frappe.get_meta("Item Price").has_field(party_field):
        fields.append(party_field)
    candidates = frappe.get_all(
        "Item Price",
        filters={"price_list": price_list, "item_code": item_code},
        fields=fields,
        order_by="valid_from desc, creation desc", limit_page_length=100,
    )
    current = today()
    valid = [row for row in candidates if (
        (not row.uom or row.uom == uom) and
        (not row.batch_no or row.batch_no == batch_no) and
        (party_field not in row or not row.get(party_field) or row.get(party_field) == party) and
        (not row.valid_from or str(row.valid_from) <= current) and
        (not row.valid_upto or str(row.valid_upto) >= current) and
        flt(row.price_list_rate) > 0
    )]
    valid.sort(key=lambda row: (bool(row.get(party_field)), bool(row.batch_no), bool(row.uom)),
               reverse=True)
    if not valid:
        frappe.throw(
            f"No valid {price_list} Item Price for {item_code}, UOM {uom}, "
            f"Batch {batch_no or '-'}"
        )
    return flt(valid[0].price_list_rate)


def _require_route_responsibility(profile, responsibility, action):
    if _can_view_all(profile):
        return
    if responsibility not in _responsibilities(profile):
        frappe.throw(f"Operator is not assigned to {responsibility} for logistics {action}")


def _responsibilities(profile):
    return {row.responsibility for row in profile.responsibilities if row.responsibility}


def _can_view_all(profile):
    return bool(
        profile.get("view_all_responsibilities") and
        profile.kanban_role in ("Supervisor", "Development Proxy")
    )


def _operator_summary(profile, session):
    return {
        "employee": profile.employee,
        "employee_name": frappe.db.get_value("Employee", profile.employee, "employee_name") or profile.employee,
        "kanban_role": profile.kanban_role,
        "responsibilities": sorted(_responsibilities(profile)),
        "view_all_responsibilities": bool(_can_view_all(profile)),
        "can_override": bool(profile.can_override),
        "session": session.name,
    }


def _document_status(doctype, name):
    if not name or not frappe.db.exists(doctype, name):
        return None
    row = frappe.db.get_value(doctype, name, ["name", "status", "docstatus"], as_dict=True)
    return row


def _manifest_exception(manifest, exception_type, message, reference_name):
    exception = frappe.get_doc({
        "doctype": "CFG Kanban Exception",
        "exception_type": exception_type,
        "severity": "Critical",
        "status": "Open",
        "movement_manifest": manifest.name,
        "message": message,
        "reference_doctype": "CFG ERP Command",
        "reference_name": reference_name,
        "raised_on": now_datetime(),
    }).insert(ignore_permissions=True)
    manifest.db_set({"state": "Exception", "exception": exception.name}, update_modified=True)
    return exception
