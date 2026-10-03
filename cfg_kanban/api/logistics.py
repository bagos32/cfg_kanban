import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.integrations.erp_gateway import (
    build_intercompany_delivery_note,
    execute_command,
    get_required_erp_inputs,
)
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, insert_once
from cfg_kanban.services.logistics_foundation import (
    post_quantity_event,
    resolve_logistics_scan,
    validate_warehouse_company,
)
from cfg_kanban.services.operator_auth import require_operator


TERMINAL_STATES = {"Received", "Billing Pending", "Partially Billed", "Billed", "Closed", "Cancelled"}
MANIFEST_LIST_FIELDS = [
    "name", "logistics_route", "state", "source_company", "source_warehouse",
    "destination_company", "destination_warehouse", "total_quantity",
    "total_received_quantity", "dispatch_delivery_note", "receipt_purchase_receipt",
    "modified",
]
INTERNAL_TRANSFER_RESPONSIBILITY = "Internal Warehouse Transfer"


@frappe.whitelist()
def assign_initial_warehouse(unit_name, warehouse, reason):
    frappe.only_for(("Manufacturing User", "Stock User", "Manufacturing Manager",
                     "Stock Manager", "System Manager"))
    if not (reason or "").strip():
        frappe.throw("Assignment reason is required")
    if not warehouse:
        frappe.throw("Current Warehouse is required")
    frappe.db.sql(
        "select name from `tabCFG Kanban Handling Unit` where name=%s for update",
        unit_name,
    )
    unit = frappe.get_doc("CFG Kanban Handling Unit", unit_name)
    unit.check_permission("write")
    if unit.tag_kind == "Reusable Container":
        frappe.throw("Use controlled container movement for a Reusable Container")
    if unit.current_warehouse:
        if unit.current_warehouse == warehouse:
            return unit.as_dict()
        frappe.throw(
            f"Handling Unit is already assigned to {unit.current_warehouse}. "
            "Use a controlled stock movement instead of changing its current location."
        )
    if unit.identity_state != "Active" or unit.movement_state not in ("At Source", "Packed"):
        frappe.throw("Initial Warehouse can be assigned only to an active source Stock Tag")
    if not unit.inventory_company:
        frappe.throw("Set the Handling Unit Inventory Company before assigning its Warehouse")
    if flt(unit.reserved_qty):
        frappe.throw("A reserved Handling Unit cannot receive an initial Warehouse assignment")
    if flt(unit.current_qty) <= 0 or not unit.stock_uom:
        frappe.throw("The Handling Unit must have a positive ledger balance before assignment")
    validate_warehouse_company(warehouse, unit.inventory_company, "Current Warehouse")
    _assert_erp_stock(unit, warehouse, unit.current_qty)
    post_quantity_event(
        event_type="Location Transfer", qty=unit.current_qty, stock_uom=unit.stock_uom,
        idempotency_key=canonical_key("handling-unit-initial-warehouse", unit.name, warehouse),
        source_handling_unit=unit.name, item_code=unit.item_code, batch_no=unit.batch_no,
        source_company=unit.inventory_company, destination_company=unit.inventory_company,
        destination_warehouse=warehouse, reference_doctype=unit.doctype,
        reference_name=unit.name, reason=reason,
    )
    unit.db_set("current_warehouse", warehouse, update_modified=True)
    record(
        "Handling Unit Initial Warehouse Assigned", handling_unit=unit.name,
        qty=unit.current_qty, reference_doctype=unit.doctype, reference_name=unit.name,
        notes=f"{warehouse}: {reason}",
    )
    unit.current_warehouse = warehouse
    return unit.as_dict()


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
    allowed_routes = {route.name for route in routes}
    manifests = _manifest_summaries(
        allowed_routes,
        {"state": ["not in", list(TERMINAL_STATES)]},
        limit=100,
    )
    recent_manifests = _manifest_summaries(
        allowed_routes,
        {"state": ["in", list(TERMINAL_STATES)]},
        limit=10,
    )
    from cfg_kanban.services.customer_delivery import delivery_session_summaries
    from cfg_kanban.services.customer_returns import return_case_summaries
    return {"operator": _operator_summary(profile, session), "routes": routes,
            "manifests": manifests, "recent_manifests": recent_manifests,
            "internal_transfers": _internal_transfer_summaries(profile),
            "delivery_sessions": delivery_session_summaries(profile),
            "return_cases": return_case_summaries(profile)}


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
    result["dispatch_retry_available"] = _dispatch_retry_available(manifest)
    result["can_dispatch"] = (
        (manifest.state in ("Draft", "Prepared") or result["dispatch_retry_available"]) and
        (_can_view_all(profile) or route.dispatch_responsibility in responsibilities)
    )
    result["can_receive"] = (
        manifest.state in ("Dispatched", "Awaiting Receipt", "Receipt Document Pending") and
        (_can_view_all(profile) or route.receipt_responsibility in responsibilities)
    )
    result["operator"] = _operator_summary(profile, session)
    return result


@frappe.whitelist()
def lookup_logistics_tag(scan_value, operator_session_token):
    """Read-only tag lookup. This endpoint never changes a Manifest or balance."""
    profile, _session = require_operator(operator_session_token)
    identity = resolve_logistics_scan(scan_value)
    if not identity:
        frappe.throw("The scanned logistics identity was not found")
    result = {"identity": identity, "handling_unit": None, "manifests": []}
    if identity["identity_type"] == "Customer Scan Point":
        from cfg_kanban.services.customer_delivery import customer_delivery_context
        result["customer_site"] = customer_delivery_context(scan_value, profile)
        return result
    if identity["identity_type"] == "Customer Return Case":
        from cfg_kanban.services.customer_returns import get_return_case
        result["return_case"] = get_return_case(identity["name"], operator_session_token)
        return result
    if identity["identity_type"] != "Handling Unit":
        return result

    unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    from cfg_kanban.services.container_contents import container_status_for_unit
    result["handling_unit"] = {
        "name": unit.name,
        "visible_code": unit.handling_unit_id,
        "tag_kind": unit.tag_kind,
        "item_code": unit.item_code,
        "description": unit.short_description,
        "batch_no": unit.batch_no,
        "serial_count": unit.serial_count,
        "stock_uom": unit.stock_uom,
        "current_qty": unit.current_qty,
        "reserved_qty": unit.reserved_qty,
        "available_qty": unit.available_qty,
        "inventory_company": unit.inventory_company,
        "current_warehouse": unit.current_warehouse,
        "physical_custodian": unit.physical_custodian,
        "identity_state": unit.identity_state,
        "movement_state": unit.movement_state,
        "quality_state": unit.quality_state,
        "packed_on": unit.packed_on,
        "expiry_date": unit.expiry_date,
    }
    result["container_status"] = container_status_for_unit(unit)
    result["can_manage_container"] = bool(
        unit.tag_kind == "Reusable Container"
        and profile.can_start
        and (_can_view_all(profile) or "Container Loading" in _responsibilities(profile))
    )
    from cfg_kanban.services.serial_evidence import active_serials_for_unit
    result["active_serial_numbers"] = active_serials_for_unit(unit.name)
    result["customer_deliveries"] = frappe.get_all(
        "CFG Kanban Delivery Allocation",
        filters={"handling_unit": unit.name, "state": "Delivered"},
        fields=["name", "delivery_session", "delivery_note", "delivered_qty"],
        order_by="modified desc", limit_page_length=10,
    )
    last_movement = frappe.db.sql(
        """
        select name, event_type, posting_datetime, reference_doctype, reference_name
        from `tabCFG Kanban Handling Unit Quantity Ledger`
        where source_handling_unit=%s or destination_handling_unit=%s
        order by posting_datetime desc, creation desc
        limit 1
        """,
        (unit.name, unit.name),
        as_dict=True,
    )
    result["last_movement"] = last_movement[0] if last_movement else None

    route_names = _authorized_route_names(profile)
    parent_names = frappe.get_all(
        "CFG Kanban Manifest Line",
        filters={"handling_unit": unit.name},
        pluck="parent",
        group_by="parent",
        limit_page_length=50,
    )
    if route_names and parent_names:
        manifests = frappe.get_all(
            "CFG Kanban Movement Manifest",
            filters={
                "name": ["in", parent_names],
                "logistics_route": ["in", list(route_names)],
            },
            fields=MANIFEST_LIST_FIELDS,
            order_by="modified desc",
            limit_page_length=20,
        )
        manifests.sort(key=lambda row: row.state in TERMINAL_STATES)
        result["manifests"] = manifests
        result["preferred_manifest"] = manifests[0].name if manifests else None
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
    if identity["identity_type"] == "Tag Range Candidate":
        frappe.throw(
            f"Tag {identity['visible_code']} is covered by Range Registry "
            f"{identity['range_registry']} but has not been activated as a Handling Unit"
        )
    if identity["identity_type"] != "Handling Unit":
        frappe.throw(f"{identity['visible_code']} is not a Handling Unit tag")
    unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    if unit.tag_kind == "Reusable Container":
        return _scan_dispatch_container(
            manifest, unit, event_token, profile, session, operator_session_token
        )
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


def _scan_dispatch_container(manifest, container, event_token, profile, session,
                             operator_session_token):
    from cfg_kanban.services.container_contents import active_container_contents

    _validate_dispatch_container(container, manifest)
    if not event_token:
        frappe.throw("A stable scan event token is required")
    contents = active_container_contents(container.name)
    if not contents:
        frappe.throw(f"Reusable Container {container.handling_unit_id} is empty")
    existing_container_lines = [
        row for row in manifest.lines if row.container_handling_unit == container.name
    ]
    if existing_container_lines:
        return get_manifest(manifest.name, operator_session_token)

    units = []
    for content in contents:
        unit = frappe.get_doc("CFG Kanban Handling Unit", content.content_handling_unit)
        _validate_dispatch_unit(unit, manifest, expected_container=container.name)
        if any(row.handling_unit == unit.name for row in manifest.lines):
            frappe.throw(
                f"Contained tag {unit.handling_unit_id} is already listed separately on this Manifest"
            )
        _assert_not_in_other_open_manifest(unit.name, manifest.name)
        _assert_erp_stock(unit, manifest.source_warehouse, unit.available_qty)
        units.append(unit)

    scan_key = canonical_key(
        "manifest-container-dispatch-scan", manifest.name, container.name, event_token
    )
    if frappe.db.get_value("CFG Kanban Event", {"device_id": scan_key}, "name"):
        return get_manifest(manifest.name, operator_session_token)
    scanned_on = now_datetime()
    for unit in units:
        manifest.append("lines", {
            "handling_unit": unit.name,
            "visible_code": unit.handling_unit_id,
            "tag_kind": unit.tag_kind,
            "container_handling_unit": container.name,
            "container_visible_code": container.handling_unit_id,
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
            "scan_event_key": canonical_key(scan_key, unit.name),
            "scanned_by": profile.employee,
            "scanned_on": scanned_on,
        })
    manifest.save(ignore_permissions=True)
    record(
        "Manifest Container Scanned",
        movement_manifest=manifest.name,
        handling_unit=container.name,
        qty=sum(flt(unit.available_qty) for unit in units),
        reference_doctype=container.doctype,
        reference_name=container.name,
        device_id=scan_key,
        notes=f"Expanded {container.handling_unit_id} into {len(units)} contained Stock Tags",
        operator=profile.employee,
        operator_session=session.name,
        terminal_user=session.terminal_user,
    )
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
    if row.container_handling_unit:
        for grouped_row in list(manifest.lines):
            if grouped_row.container_handling_unit == row.container_handling_unit:
                manifest.remove(grouped_row)
    else:
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
    _validate_manifest_container_groups(manifest)
    for row in manifest.lines:
        unit = frappe.get_doc("CFG Kanban Handling Unit", row.handling_unit)
        _validate_dispatch_unit(
            unit, manifest, expected_container=row.container_handling_unit or None
        )
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
def get_dispatch_requirements(manifest_name, operator_session_token):
    profile, _session = require_operator(operator_session_token, "complete")
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    route = frappe.get_doc("CFG Kanban Logistics Route", manifest.logistics_route)
    _require_route_responsibility(profile, route.dispatch_responsibility, "dispatch")
    if manifest.state != "Prepared" and not _dispatch_retry_available(manifest):
        frappe.throw(f"Manifest cannot dispatch while it is {manifest.state}")
    payload = _dispatch_payload(manifest)
    delivery_note = build_intercompany_delivery_note(
        manifest, payload, validate_required=False
    )
    return {"doctype": "Delivery Note", "fields": get_required_erp_inputs(delivery_note)}


@frappe.whitelist()
def confirm_dispatch(
    manifest_name, event_token, operator_session_token, required_erp_inputs=None
):
    profile, session = require_operator(operator_session_token, "complete")
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    route = frappe.get_doc("CFG Kanban Logistics Route", manifest.logistics_route)
    _require_route_responsibility(profile, route.dispatch_responsibility, "dispatch")
    if (
        manifest.state not in ("Prepared", "Dispatch Document Pending")
        and not _dispatch_retry_available(manifest)
    ):
        frappe.throw(f"Manifest cannot dispatch while it is {manifest.state}")
    key = canonical_key("manifest-dispatch", manifest.name)
    payload = _dispatch_payload(manifest, required_erp_inputs)
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
    if not _created:
        if command.status == "Completed":
            return get_manifest(manifest.name, operator_session_token)
        if command.status != "Failed":
            frappe.throw(f"Dispatch ERP Command is {command.status}; it cannot be retried")
        command.db_set({
            "status": "Pending",
            "request_payload": frappe.as_json(payload),
            "last_error": None,
            "requested_by_operator": profile.employee,
            "operator_session": session.name,
            "terminal_user": session.terminal_user,
            "requested_on": now_datetime(),
        }, update_modified=True)
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
    _resolve_manifest_exception(manifest, "Delivery Note creation retried successfully")
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
    scanned_unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    if scanned_unit.tag_kind == "Reusable Container":
        return _scan_receipt_container(
            manifest, scanned_unit, event_token, profile, session, operator_session_token
        )
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


def _scan_receipt_container(manifest, container, event_token, profile, session,
                            operator_session_token):
    if not event_token:
        frappe.throw("A stable receipt scan event token is required")
    if container.identity_state != "Active" or container.quality_state != "Released":
        frappe.throw(
            f"Reusable Container {container.handling_unit_id} is "
            f"{container.identity_state} / {container.quality_state}"
        )
    if (
        container.inventory_company != manifest.source_company
        or container.current_warehouse
        or container.movement_state != "Intercompany Transit"
    ):
        frappe.throw(
            f"Reusable Container {container.handling_unit_id} is not in the expected "
            "intercompany transit state"
        )
    rows = [row for row in manifest.lines if row.container_handling_unit == container.name]
    if not rows:
        frappe.throw("This reusable container is not listed on the selected Manifest")
    from cfg_kanban.services.container_contents import active_container_membership

    for row in rows:
        membership = active_container_membership(row.handling_unit)
        if not membership or membership.container_handling_unit != container.name:
            frappe.throw(
                f"Container contents changed: tag {row.visible_code} is no longer inside "
                f"{container.handling_unit_id}"
            )
    if all(row.receipt_scanned for row in rows):
        return get_manifest(manifest.name, operator_session_token)
    scanned_on = now_datetime()
    for row in rows:
        row.receipt_scanned = 1
        row.received_qty = row.dispatch_qty
        row.receipt_scanned_by = profile.employee
        row.receipt_scanned_on = scanned_on
        row.state = "Receipt Pending"
    manifest.save(ignore_permissions=True)
    record(
        "Manifest Container Receipt Scanned",
        movement_manifest=manifest.name,
        handling_unit=container.name,
        qty=sum(flt(row.dispatch_qty) for row in rows),
        reference_doctype=manifest.doctype,
        reference_name=manifest.name,
        device_id=canonical_key(
            "manifest-container-receipt-scan", manifest.name, container.name, event_token
        ),
        notes=f"Confirmed {len(rows)} contained Stock Tags with one container scan",
        operator=profile.employee,
        operator_session=session.name,
        terminal_user=session.terminal_user,
    )
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


def _validate_dispatch_unit(unit, manifest, expected_container=None):
    from cfg_kanban.services.container_contents import (
        active_container_membership,
        assert_not_loaded_in_container,
    )

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
        frappe.throw("Dispatch the contained Stock Tags, not the reusable-container identity")
    if expected_container:
        membership = active_container_membership(unit.name)
        if not membership or membership.container_handling_unit != expected_container:
            frappe.throw(
                f"Tag {unit.handling_unit_id} is no longer inside the scanned reusable container"
            )
    else:
        assert_not_loaded_in_container(unit.name, "adding it to an intercompany Manifest")
    if flt(unit.available_qty) <= 0:
        frappe.throw(f"Tag {unit.handling_unit_id} has no available quantity")
    if flt(unit.reserved_qty):
        frappe.throw(f"Tag {unit.handling_unit_id} already has reserved quantity")


def _validate_dispatch_container(container, manifest):
    from cfg_kanban.services.container_contents import assert_container_not_in_open_delivery

    assert_container_not_in_open_delivery(container.name, "dispatching it on a Movement Manifest")
    if container.identity_state != "Active" or container.quality_state != "Released":
        frappe.throw(
            f"Reusable Container {container.handling_unit_id} is "
            f"{container.identity_state} / {container.quality_state}"
        )
    if container.inventory_company != manifest.source_company:
        frappe.throw(
            f"Reusable Container belongs to {container.inventory_company}, "
            f"not route source {manifest.source_company}"
        )
    if container.current_warehouse != manifest.source_warehouse:
        frappe.throw(
            f"Reusable Container is in {container.current_warehouse}, "
            f"not route source Warehouse {manifest.source_warehouse}"
        )


def _validate_manifest_container_groups(manifest):
    from cfg_kanban.services.container_contents import active_container_contents

    container_names = {
        row.container_handling_unit for row in manifest.lines if row.container_handling_unit
    }
    for container_name in container_names:
        container = frappe.get_doc("CFG Kanban Handling Unit", container_name)
        _validate_dispatch_container(container, manifest)
        expected = {
            row.content_handling_unit for row in active_container_contents(container_name)
        }
        listed = {
            row.handling_unit
            for row in manifest.lines
            if row.container_handling_unit == container_name
        }
        if expected != listed:
            frappe.throw(
                f"Reusable Container {container.handling_unit_id} contents changed after its "
                "dispatch scan. Remove and rescan the container."
            )


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
    from cfg_kanban.services.logistics_foundation import assert_erp_stock

    return assert_erp_stock(unit, warehouse, qty)


def _dispatch_payload(manifest, required_erp_inputs=None):
    payload = {
        "manifest": manifest.name,
        "company": manifest.source_company,
        "warehouse": manifest.source_warehouse,
        "customer": manifest.internal_customer,
        "price_list": manifest.selling_price_list,
        "counterpart_company": manifest.destination_company,
        "submit": bool(manifest.auto_submit_dispatch_dn),
        "items": [_priced_line(manifest, row, "selling") for row in manifest.lines],
    }
    if required_erp_inputs:
        payload["required_erp_inputs"] = frappe.parse_json(required_erp_inputs)
    return payload


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
    from cfg_kanban.services.logistics_foundation import price_list_rate

    return price_list_rate(price_list, item_code, uom, batch_no, mode, party)


def _internal_transfer_summaries(profile):
    responsibilities = _responsibilities(profile)
    if not _can_view_all(profile) and INTERNAL_TRANSFER_RESPONSIBILITY not in responsibilities:
        return []
    fields = ["name", "company", "purpose", "docstatus", "posting_date", "posting_time",
              "modified"]
    drafts = frappe.get_all(
        "Stock Entry", filters={"purpose": "Material Transfer", "docstatus": 0},
        fields=fields, order_by="modified desc", limit_page_length=50,
    )
    submitted = frappe.get_all(
        "Stock Entry", filters={"purpose": "Material Transfer", "docstatus": 1},
        fields=fields, order_by="modified desc", limit_page_length=10,
    )
    rows = drafts + submitted
    if not rows:
        return []
    names = [row.name for row in rows]
    details = frappe.get_all(
        "Stock Entry Detail", filters={"parent": ["in", names]},
        fields=["parent", "item_code", "s_warehouse", "t_warehouse", "transfer_qty",
                "stock_uom"],
        order_by="parent asc, idx asc", limit_page_length=0,
    )
    details_by_parent = {}
    for detail in details:
        details_by_parent.setdefault(detail.parent, []).append(detail)
    traces = frappe.get_all(
        "CFG Kanban Material Trace", filters={"stock_entry": ["in", names]},
        fields=["name", "stock_entry", "status"], limit_page_length=0,
    )
    trace_by_entry = {trace.stock_entry: trace for trace in traces}
    for row in rows:
        item_rows = details_by_parent.get(row.name, [])
        sources = list(dict.fromkeys(
            detail.s_warehouse for detail in item_rows if detail.s_warehouse
        ))
        destinations = list(dict.fromkeys(
            detail.t_warehouse for detail in item_rows if detail.t_warehouse
        ))
        trace = trace_by_entry.get(row.name)
        row["source_warehouses"] = sources
        row["destination_warehouses"] = destinations
        row["item_count"] = len(item_rows)
        row["total_quantity"] = sum(flt(detail.transfer_qty) for detail in item_rows)
        row["erp_status"] = "Draft" if row.docstatus == 0 else "Submitted"
        row["trace"] = trace.name if trace else None
        row["trace_status"] = trace.status if trace else "Not Started"
        row["can_scan"] = row.docstatus == 0
    return rows


def _require_route_responsibility(profile, responsibility, action):
    if _can_view_all(profile):
        return
    if responsibility not in _responsibilities(profile):
        frappe.throw(f"Operator is not assigned to {responsibility} for logistics {action}")


def _responsibilities(profile):
    return {row.responsibility for row in profile.responsibilities if row.responsibility}


def _authorized_route_names(profile):
    routes = frappe.get_all(
        "CFG Kanban Logistics Route",
        fields=["name", "dispatch_responsibility", "receipt_responsibility"],
        limit_page_length=0,
    )
    if _can_view_all(profile):
        return {row.name for row in routes}
    responsibilities = _responsibilities(profile)
    return {
        row.name for row in routes
        if row.dispatch_responsibility in responsibilities
        or row.receipt_responsibility in responsibilities
    }


def _manifest_summaries(route_names, filters, limit):
    if not route_names:
        return []
    filters = dict(filters)
    filters["logistics_route"] = ["in", list(route_names)]
    return frappe.get_all(
        "CFG Kanban Movement Manifest",
        filters=filters,
        fields=MANIFEST_LIST_FIELDS,
        order_by="modified desc",
        limit_page_length=limit,
    )


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


def _dispatch_retry_available(manifest):
    if manifest.state != "Exception" or manifest.dispatch_delivery_note:
        return False
    command_name = manifest.dispatch_command
    return bool(
        command_name
        and frappe.db.get_value("CFG ERP Command", command_name, "status") == "Failed"
    )


def _resolve_manifest_exception(manifest, resolution):
    if not manifest.exception or not frappe.db.exists("CFG Kanban Exception", manifest.exception):
        return
    frappe.db.set_value(
        "CFG Kanban Exception",
        manifest.exception,
        {
            "status": "Resolved",
            "resolved_on": now_datetime(),
            "resolved_by": frappe.session.user,
            "resolution": resolution,
        },
        update_modified=True,
    )


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
