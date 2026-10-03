import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime, today

from cfg_kanban.services.container_contents import (
    active_container_contents,
    active_container_membership,
)
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, insert_once
from cfg_kanban.services.logistics_foundation import (
    assert_erp_stock,
    price_list_rate,
    post_quantity_event,
    resolve_logistics_scan,
    validate_price_list_mode,
)
from cfg_kanban.services.operator_auth import require_operator
from cfg_kanban.integrations.erp_gateway import (
    build_customer_delivery_note,
    execute_command,
    get_required_erp_inputs,
)


CUSTOMER_DELIVERY_RESPONSIBILITY = "Customer Delivery"
DELIVERY_TERMINAL_STATES = {"Invoiced", "Closed", "Rejected", "Cancelled"}
ACTIVE_ALLOCATION_STATES = ("Reserved", "Delivery Pending", "Exception")


@frappe.whitelist()
def start_delivery_session(customer_scan, source_warehouse, event_token,
                           operator_session_token):
    profile, operator_session = require_operator(operator_session_token, "start")
    _require_customer_delivery(profile)
    if not event_token:
        frappe.throw(_("A stable event token is required"))
    site = _resolve_customer_site(customer_scan)
    vehicle = _vehicle_warehouse(source_warehouse, site.selling_company)
    price_list = site.default_price_list or frappe.db.get_single_value(
        "Selling Settings", "selling_price_list"
    )
    if not price_list:
        frappe.throw(
            _("Set Default Selling Price List on the Customer Scan Point or Selling Settings")
        )
    validate_price_list_mode(price_list, "selling", "Delivery Price List")
    key = canonical_key(
        "customer-delivery-session", site.name, source_warehouse, event_token
    )
    existing = frappe.db.get_value(
        "CFG Kanban Delivery Session", {"idempotency_key": key}, "name"
    )
    if existing:
        return get_delivery_session(existing, operator_session_token)

    active = frappe.get_all(
        "CFG Kanban Delivery Session",
        filters={
            "started_by_operator": profile.employee,
            "state": ["not in", list(DELIVERY_TERMINAL_STATES)],
        },
        fields=["name", "site_name", "state"],
        order_by="started_on desc",
        limit_page_length=1,
    )
    if active:
        frappe.throw(
            _("Operator already has active Delivery Session {0} for {1} ({2}). "
              "Complete or cancel it before starting another site.").format(
                active[0].name, active[0].site_name, active[0].state
            )
        )

    delivery = frappe.get_doc({
        "doctype": "CFG Kanban Delivery Session",
        "state": "Customer Identified",
        "customer_scan_point": site.name,
        "site_code": site.site_code,
        "site_name": site.site_name,
        "selling_company": site.selling_company,
        "customer": site.customer,
        "customer_address": site.customer_address,
        "territory": site.territory,
        "route_reference": site.route_reference,
        "source_warehouse": source_warehouse,
        "vehicle_reference": vehicle.vehicle_reference,
        "price_list": price_list,
        "auto_submit_delivery_note": site.auto_submit_delivery_note,
        "proof_policy": site.proof_policy,
        "require_recipient_name": site.require_recipient_name,
        "require_signature": site.require_signature,
        "require_photo": site.require_photo,
        "require_gps": site.require_gps,
        "unattended_reason_required": site.unattended_reason_required,
        "started_by_operator": profile.employee,
        "operator_session": operator_session.name,
        "started_on": now_datetime(),
        "idempotency_key": key,
    }).insert(ignore_permissions=True)
    record(
        "Customer Delivery Session Started",
        delivery_session=delivery.name,
        previous_state=None,
        new_state="Customer Identified",
        reference_doctype=site.doctype,
        reference_name=site.name,
        device_id=key,
        notes=f"{site.site_code} / {source_warehouse} / {vehicle.vehicle_reference}",
        operator=profile.employee,
        operator_session=operator_session.name,
        terminal_user=operator_session.terminal_user,
    )
    return get_delivery_session(delivery.name, operator_session_token)


@frappe.whitelist()
def get_delivery_session(delivery_session, operator_session_token):
    profile, _session = require_operator(operator_session_token)
    _require_customer_delivery(profile)
    delivery = frappe.get_doc("CFG Kanban Delivery Session", delivery_session)
    if not _can_view_delivery(profile, delivery):
        frappe.throw(_("Operator cannot access this Delivery Session"), frappe.PermissionError)
    result = delivery.as_dict()
    result["allocations"] = frappe.get_all(
        "CFG Kanban Delivery Allocation",
        filters={"delivery_session": delivery.name},
        fields=[
            "name", "state", "handling_unit", "visible_code", "container_visible_code",
            "item_code", "batch_no", "stock_uom", "allocated_qty", "delivered_qty",
            "delivery_note", "reserved_on", "released_on", "release_reason",
        ],
        order_by="reserved_on asc",
        limit_page_length=500,
    )
    result["delivery_note_status"] = None
    if delivery.delivery_note and frappe.db.exists("Delivery Note", delivery.delivery_note):
        result["delivery_note_status"] = frappe.db.get_value(
            "Delivery Note", delivery.delivery_note,
            ["docstatus", "status"], as_dict=True,
        )
    return result


@frappe.whitelist()
def get_delivery_allocation_candidate(delivery_session, scan_value,
                                      operator_session_token):
    profile, _session = require_operator(operator_session_token, "start")
    _require_customer_delivery(profile)
    delivery = _delivery_for_operator(delivery_session, profile)
    _assert_allocation_session(delivery)
    identity = resolve_logistics_scan(scan_value)
    if not identity or identity.get("identity_type") != "Handling Unit":
        frappe.throw(_("Scan an activated Stock Tag or reusable container"))
    unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    if unit.tag_kind == "Reusable Container":
        _validate_container(unit, delivery)
        contents = active_container_contents(unit.name)
        if not contents:
            frappe.throw(_("Reusable container {0} is empty").format(unit.handling_unit_id))
        rows = []
        for membership in contents:
            content = frappe.get_doc(
                "CFG Kanban Handling Unit", membership.content_handling_unit
            )
            _validate_allocation_unit(content, delivery, expected_container=unit.name)
            rows.append(_candidate_row(content))
        return {
            "mode": "container",
            "container": unit.name,
            "container_visible_code": unit.handling_unit_id,
            "contents": rows,
            "total_qty": sum(flt(row["available_qty"]) for row in rows),
            "full_quantity_only": True,
        }

    _validate_allocation_unit(unit, delivery)
    return {
        "mode": "stock_tag",
        "container": None,
        "container_visible_code": None,
        "contents": [_candidate_row(unit)],
        "total_qty": flt(unit.available_qty),
        "full_quantity_only": bool(unit.serial_count),
    }


@frappe.whitelist()
def allocate_delivery_stock(delivery_session, scan_value, allocated_qty, event_token,
                            operator_session_token):
    profile, operator_session = require_operator(operator_session_token, "start")
    _require_customer_delivery(profile)
    if not event_token:
        frappe.throw(_("A stable scan event token is required"))
    delivery = _delivery_for_operator(delivery_session, profile)
    _assert_allocation_session(delivery)
    identity = resolve_logistics_scan(scan_value)
    if identity and identity.get("identity_type") == "Handling Unit":
        scanned = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
        unit_names = ([row.content_handling_unit for row in active_container_contents(scanned.name)]
                      if scanned.tag_kind == "Reusable Container" else [scanned.name])
        if unit_names and all(frappe.db.exists(
            "CFG Kanban Delivery Allocation",
            {"reservation_key": canonical_key(
                "customer-delivery-reserve", delivery.name, name, event_token
            )},
        ) for name in unit_names):
            return get_delivery_session(delivery.name, operator_session_token)
    candidate = get_delivery_allocation_candidate(
        delivery.name, scan_value, operator_session_token
    )
    allocations = []
    if candidate["mode"] == "container":
        for row in candidate["contents"]:
            allocations.append(_reserve_unit(
                delivery, frappe.get_doc("CFG Kanban Handling Unit", row["handling_unit"]),
                row["available_qty"], event_token, profile, operator_session,
                candidate["container"], candidate["container_visible_code"],
            ))
    else:
        unit = frappe.get_doc(
            "CFG Kanban Handling Unit", candidate["contents"][0]["handling_unit"]
        )
        qty = flt(allocated_qty)
        if qty <= 0:
            frappe.throw(_("Allocation Quantity must be greater than zero"))
        if flt(unit.serial_count) and abs(qty - flt(unit.available_qty)) > 0.000001:
            frappe.throw(
                _("Serialized tag {0} must be allocated as one complete physical unit").format(
                    unit.handling_unit_id
                )
            )
        if frappe.db.get_value("UOM", unit.stock_uom, "must_be_whole_number") and qty % 1:
            frappe.throw(_("UOM {0} requires a whole-number quantity").format(unit.stock_uom))
        allocations.append(_reserve_unit(
            delivery, unit, qty, event_token, profile, operator_session
        ))

    previous_state = delivery.state
    if delivery.state == "Customer Identified":
        delivery.db_set("state", "Allocating Stock", update_modified=True)
    record(
        "Customer Delivery Stock Allocated",
        delivery_session=delivery.name,
        qty=sum(flt(row.allocated_qty) for row in allocations),
        previous_state=previous_state,
        new_state="Allocating Stock",
        reference_doctype="CFG Kanban Delivery Allocation",
        reference_name=allocations[0].name if allocations else None,
        device_id=event_token,
        notes=(candidate.get("container_visible_code") or
               allocations[0].visible_code if allocations else scan_value),
        operator=profile.employee,
        operator_session=operator_session.name,
        terminal_user=operator_session.terminal_user,
    )
    return get_delivery_session(delivery.name, operator_session_token)


@frappe.whitelist()
def confirm_delivery_allocations(delivery_session, event_token,
                                 operator_session_token):
    profile, operator_session = require_operator(operator_session_token, "complete")
    _require_customer_delivery(profile)
    if not event_token:
        frappe.throw(_("A stable confirmation event token is required"))
    delivery = _delivery_for_operator(delivery_session, profile)
    if delivery.state == "Awaiting Confirmation":
        return get_delivery_session(delivery.name, operator_session_token)
    if delivery.state != "Allocating Stock":
        frappe.throw(_("Only an Allocating Stock session can be confirmed"))
    allocation_rows = frappe.get_all(
        "CFG Kanban Delivery Allocation",
        filters={"delivery_session": delivery.name, "state": "Reserved"},
        fields=["name", "handling_unit", "container_handling_unit"],
        limit_page_length=500,
    )
    names = [row.name for row in allocation_rows]
    if not names:
        frappe.throw(_("Allocate at least one Stock Tag before confirmation"))
    _validate_confirmed_container_groups(allocation_rows)
    for name in names:
        frappe.db.set_value(
            "CFG Kanban Delivery Allocation", name,
            "state", "Delivery Pending", update_modified=False,
        )
    now = now_datetime()
    delivery.db_set({"state": "Awaiting Confirmation", "confirmed_on": now},
                    update_modified=True)
    record(
        "Customer Delivery Allocations Confirmed",
        delivery_session=delivery.name,
        previous_state="Allocating Stock",
        new_state="Awaiting Confirmation",
        reference_doctype=delivery.doctype,
        reference_name=delivery.name,
        device_id=canonical_key("customer-delivery-confirm", delivery.name, event_token),
        notes=f"{len(names)} Stock Tag allocation(s) awaiting ERP Delivery Note",
        operator=profile.employee,
        operator_session=operator_session.name,
        terminal_user=operator_session.terminal_user,
    )
    return get_delivery_session(delivery.name, operator_session_token)


@frappe.whitelist()
def get_customer_delivery_requirements(delivery_session, operator_session_token):
    profile, _session = require_operator(operator_session_token, "complete")
    _require_customer_delivery(profile)
    delivery = _delivery_for_operator(delivery_session, profile)
    if delivery.state not in ("Awaiting Confirmation", "ERP Document Pending", "Exception"):
        frappe.throw(_("Confirm customer allocations before creating the Delivery Note"))
    if delivery.delivery_note and frappe.db.get_value(
        "Delivery Note", delivery.delivery_note, "docstatus"
    ) == 0:
        return {"doctype": "Delivery Note", "fields": [], "existing_draft": delivery.delivery_note}
    payload = _customer_delivery_payload(delivery)
    delivery_note = build_customer_delivery_note(
        delivery, payload, validate_required=False
    )
    return {"doctype": "Delivery Note", "fields": get_required_erp_inputs(delivery_note)}


@frappe.whitelist()
def create_customer_delivery_document(delivery_session, event_token,
                                      operator_session_token,
                                      required_erp_inputs=None):
    profile, operator_session = require_operator(operator_session_token, "complete")
    _require_customer_delivery(profile)
    if not event_token:
        frappe.throw(_("A stable Delivery Note request token is required"))
    delivery = _delivery_for_operator(delivery_session, profile)
    if delivery.delivery_note and frappe.db.exists("Delivery Note", delivery.delivery_note):
        status = frappe.db.get_value("Delivery Note", delivery.delivery_note, "docstatus")
        if status in (0, 1):
            return get_delivery_session(delivery.name, operator_session_token)
    if delivery.state not in ("Awaiting Confirmation", "ERP Document Pending", "Exception"):
        frappe.throw(_("Delivery Session cannot create a Delivery Note while it is {0}").format(
            delivery.state
        ))
    previous_state = delivery.state
    payload = _customer_delivery_payload(delivery, required_erp_inputs)
    revision = int(delivery.delivery_revision or 0)
    key = canonical_key("customer-delivery-note", delivery.name, revision)
    command, created = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command",
        "command_type": "Create Customer Delivery Note",
        "delivery_session": delivery.name,
        "status": "Pending",
        "target_doctype": "Delivery Note",
        "request_payload": frappe.as_json(payload),
        "requested_by_operator": profile.employee,
        "operator_session": operator_session.name,
        "terminal_user": operator_session.terminal_user,
        "requested_on": now_datetime(),
        "created_by_system": 1,
    }), key, ignore_permissions=True)
    if not created:
        if command.status == "Completed" and command.target_document:
            if frappe.db.exists("Delivery Note", command.target_document):
                delivery.db_set("delivery_note", command.target_document,
                                update_modified=False)
                return get_delivery_session(delivery.name, operator_session_token)
        if command.status != "Failed":
            frappe.throw(_("Customer Delivery ERP Command is {0}; it cannot be retried").format(
                command.status
            ))
        command.db_set({
            "status": "Pending",
            "request_payload": frappe.as_json(payload),
            "last_error": None,
            "requested_by_operator": profile.employee,
            "operator_session": operator_session.name,
            "terminal_user": operator_session.terminal_user,
            "requested_on": now_datetime(),
        }, update_modified=True)
    delivery.db_set({
        "delivery_key": key,
        "delivery_command": command.name,
        "delivery_confirmed_by": profile.employee,
        "delivery_operator_session": operator_session.name,
        "delivery_confirmed_on": now_datetime(),
        "state": "ERP Document Pending",
    }, update_modified=True)
    try:
        delivery_note = execute_command(command.name)
    except Exception:
        _delivery_exception(
            delivery, "Customer Delivery Note Command Failed",
            "Customer Delivery Note creation or submission failed", command.name,
        )
        raise
    delivery.reload()
    _resolve_delivery_exception(delivery, "Customer Delivery Note command succeeded")
    if delivery_note.docstatus == 0:
        delivery.db_set({"delivery_note": delivery_note.name,
                         "state": "ERP Document Pending"}, update_modified=True)
    record(
        "Customer Delivery Note Requested",
        delivery_session=delivery.name,
        previous_state=previous_state,
        new_state=delivery.state,
        qty=sum(flt(row["qty"]) for row in payload["items"]),
        reference_doctype="Delivery Note",
        reference_name=delivery_note.name,
        device_id=key,
        notes=("Auto-submit enabled" if delivery.auto_submit_delivery_note
               else "Draft retained for ERPNext review and manual submission"),
        operator=profile.employee,
        operator_session=operator_session.name,
        terminal_user=operator_session.terminal_user,
    )
    return get_delivery_session(delivery.name, operator_session_token)


@frappe.whitelist()
def release_delivery_allocation(allocation, reason, event_token,
                                operator_session_token):
    profile, operator_session = require_operator(operator_session_token, "complete")
    _require_customer_delivery(profile)
    if not (reason or "").strip():
        frappe.throw(_("Release Reason is required"))
    if not event_token:
        frappe.throw(_("A stable release event token is required"))
    row = frappe.get_doc("CFG Kanban Delivery Allocation", allocation)
    delivery = _delivery_for_operator(row.delivery_session, profile)
    if row.state == "Released":
        return get_delivery_session(delivery.name, operator_session_token)
    if row.state not in ("Reserved", "Delivery Pending") or row.delivery_note:
        frappe.throw(_("Only an undelivered active allocation can be released"))
    rows = [row]
    if row.container_handling_unit:
        rows = [frappe.get_doc("CFG Kanban Delivery Allocation", name) for name in
                frappe.get_all(
                    "CFG Kanban Delivery Allocation",
                    filters={
                        "delivery_session": delivery.name,
                        "container_handling_unit": row.container_handling_unit,
                        "state": ["in", ["Reserved", "Delivery Pending"]],
                    },
                    pluck="name", limit_page_length=500,
                )]
    for release_row in rows:
        if release_row.delivery_note:
            frappe.throw(_("Container allocation is already linked to a Delivery Note"))
        _release_allocation_row(
            release_row, delivery, reason.strip(), event_token,
            profile, operator_session,
        )

    # Changing a confirmed reservation invalidates the confirmation snapshot.
    for name in frappe.get_all(
        "CFG Kanban Delivery Allocation",
        filters={"delivery_session": delivery.name, "state": "Delivery Pending"},
        pluck="name", limit_page_length=500,
    ):
        frappe.db.set_value(
            "CFG Kanban Delivery Allocation", name,
            "state", "Reserved", update_modified=False,
        )
    active = frappe.db.exists(
        "CFG Kanban Delivery Allocation",
        {"delivery_session": delivery.name, "state": "Reserved"},
    )
    new_state = "Allocating Stock" if active else "Customer Identified"
    delivery.db_set({"state": new_state, "confirmed_on": None}, update_modified=True)
    record(
        "Customer Delivery Allocation Released",
        delivery_session=delivery.name, handling_unit=row.handling_unit,
        qty=sum(flt(release_row.allocated_qty) for release_row in rows),
        previous_state=row.state, new_state="Released",
        reference_doctype=row.doctype, reference_name=row.name,
        device_id=canonical_key("customer-delivery-release", row.name, event_token),
        notes=((f"Container {row.container_visible_code}: " if row.container_visible_code else "")
               + reason.strip()), operator=profile.employee,
        operator_session=operator_session.name,
        terminal_user=operator_session.terminal_user,
    )
    return get_delivery_session(delivery.name, operator_session_token)


def _release_allocation_row(row, delivery, reason, event_token,
                            profile, operator_session):
    release_key = canonical_key("customer-delivery-release", row.name, event_token)
    unit = frappe.get_doc("CFG Kanban Handling Unit", row.handling_unit)
    ledger = post_quantity_event(
        event_type="Unreserve", qty=row.allocated_qty, stock_uom=row.stock_uom,
        idempotency_key=release_key, source_handling_unit=unit.name,
        item_code=row.item_code, batch_no=row.batch_no,
        source_company=delivery.selling_company,
        source_warehouse=delivery.source_warehouse,
        reference_doctype=row.doctype, reference_name=row.name,
        operator=profile.employee, operator_session=operator_session.name,
        device_id=event_token, reason=reason,
    )
    now = now_datetime()
    frappe.db.set_value(row.doctype, row.name, {
        "state": "Released", "active_handling_unit_key": None,
        "released_on": now, "release_reason": reason,
        "release_ledger": ledger.name, "release_key": release_key,
    }, update_modified=True)
    unit.reload()
    if not flt(unit.reserved_qty):
        unit.db_set({
            "movement_state": row.movement_state_before_reservation or "At Source",
            "last_scan_time": now,
        }, update_modified=False)


@frappe.whitelist()
def cancel_delivery_session(delivery_session, reason, event_token,
                            operator_session_token):
    profile, operator_session = require_operator(operator_session_token, "complete")
    _require_customer_delivery(profile)
    if not (reason or "").strip():
        frappe.throw(_("Cancellation Reason is required"))
    if not event_token:
        frappe.throw(_("A stable event token is required"))
    delivery = frappe.get_doc("CFG Kanban Delivery Session", delivery_session)
    if not _can_view_delivery(profile, delivery):
        frappe.throw(_("Operator cannot cancel this Delivery Session"), frappe.PermissionError)
    cancel_key = canonical_key(
        "customer-delivery-cancel", delivery.name, event_token
    )
    if frappe.db.exists(
        "CFG Kanban Event",
        {
            "event_type": "Customer Delivery Session Cancelled",
            "delivery_session": delivery.name,
            "device_id": cancel_key,
        },
    ):
        return get_delivery_session(delivery.name, operator_session_token)
    if delivery.state != "Customer Identified":
        frappe.throw(_("Only an empty Customer Identified session can be cancelled"))
    if frappe.db.exists(
        "CFG Kanban Delivery Allocation",
        {"delivery_session": delivery.name, "state": ["in", list(ACTIVE_ALLOCATION_STATES)]},
    ):
        frappe.throw(_("Release all stock allocations before cancelling the Delivery Session"))
    delivery.db_set({
        "state": "Cancelled",
        "cancelled_by_operator": profile.employee,
        "cancelled_on": now_datetime(),
        "cancellation_reason": reason.strip(),
    }, update_modified=True)
    record(
        "Customer Delivery Session Cancelled",
        delivery_session=delivery.name,
        previous_state="Customer Identified",
        new_state="Cancelled",
        reference_doctype=delivery.doctype,
        reference_name=delivery.name,
        device_id=cancel_key,
        notes=reason.strip(),
        operator=profile.employee,
        operator_session=operator_session.name,
        terminal_user=operator_session.terminal_user,
    )
    return get_delivery_session(delivery.name, operator_session_token)


def _delivery_for_operator(delivery_session, profile):
    delivery = frappe.get_doc("CFG Kanban Delivery Session", delivery_session)
    if not _can_view_delivery(profile, delivery):
        frappe.throw(_("Operator cannot access this Delivery Session"), frappe.PermissionError)
    return delivery


def _assert_allocation_session(delivery):
    if delivery.state not in ("Customer Identified", "Allocating Stock"):
        frappe.throw(
            _("Delivery Session {0} is {1}; stock scanning is not available").format(
                delivery.name, delivery.state
            )
        )
    if delivery.delivery_note:
        frappe.throw(_("Delivery Session already has ERP Delivery Note {0}").format(
            delivery.delivery_note
        ))


def _customer_delivery_payload(delivery, required_erp_inputs=None):
    if frappe.db.get_value("Customer", delivery.customer, "disabled"):
        frappe.throw(_("Customer {0} is disabled").format(delivery.customer))
    allocations = frappe.get_all(
        "CFG Kanban Delivery Allocation",
        filters={"delivery_session": delivery.name, "state": "Delivery Pending"},
        fields=[
            "name", "handling_unit", "visible_code", "container_handling_unit",
            "container_visible_code", "item_code", "batch_no", "stock_uom",
            "allocated_qty", "source_warehouse",
        ],
        order_by="reserved_on asc, name asc",
        limit_page_length=500,
    )
    if not allocations:
        frappe.throw(_("Delivery Session has no confirmed stock allocations"))
    _validate_confirmed_container_groups(allocations)
    items = []
    for row in allocations:
        unit = frappe.get_doc("CFG Kanban Handling Unit", row.handling_unit)
        if unit.inventory_company != delivery.selling_company:
            frappe.throw(_("Stock Tag {0} no longer belongs to the Selling Company").format(
                row.visible_code
            ))
        if unit.current_warehouse != delivery.source_warehouse:
            frappe.throw(_("Stock Tag {0} is no longer in lorry Warehouse {1}").format(
                row.visible_code, delivery.source_warehouse
            ))
        if unit.quality_state != "Released" or unit.identity_state != "Active":
            frappe.throw(_("Stock Tag {0} is no longer Active and Released").format(
                row.visible_code
            ))
        if flt(unit.reserved_qty) + 0.000001 < flt(row.allocated_qty):
            frappe.throw(_("Stock Tag {0} reservation is below the confirmed quantity").format(
                row.visible_code
            ))
        if row.batch_no:
            expiry_date = frappe.db.get_value("Batch", row.batch_no, "expiry_date")
            if expiry_date and getdate(expiry_date) < getdate(today()):
                frappe.throw(_("Batch {0} for Stock Tag {1} is expired").format(
                    row.batch_no, row.visible_code
                ))
        assert_erp_stock(unit, delivery.source_warehouse, row.allocated_qty)
        items.append({
            "delivery_allocation": row.name,
            "handling_unit": row.handling_unit,
            "item_code": row.item_code,
            "batch_no": row.batch_no,
            "uom": row.stock_uom,
            "qty": row.allocated_qty,
            "rate": price_list_rate(
                delivery.price_list, row.item_code, row.stock_uom,
                row.batch_no, "selling", delivery.customer,
            ),
        })
    payload = {
        "delivery_session": delivery.name,
        "company": delivery.selling_company,
        "warehouse": delivery.source_warehouse,
        "customer": delivery.customer,
        "customer_address": delivery.customer_address,
        "price_list": delivery.price_list,
        "submit": bool(delivery.auto_submit_delivery_note),
        "items": items,
    }
    if delivery.delivery_note and frappe.db.get_value(
        "Delivery Note", delivery.delivery_note, "docstatus"
    ) == 2:
        payload["amended_from"] = delivery.delivery_note
    if required_erp_inputs:
        payload["required_erp_inputs"] = frappe.parse_json(required_erp_inputs)
    return payload


def _validate_confirmed_container_groups(allocations):
    grouped = {}
    for row in allocations:
        if row.container_handling_unit:
            grouped.setdefault(row.container_handling_unit, set()).add(row.handling_unit)
    for container_name, allocated_units in grouped.items():
        current_units = {
            row.content_handling_unit for row in active_container_contents(container_name)
        }
        if current_units != allocated_units:
            container_code = frappe.db.get_value(
                "CFG Kanban Handling Unit", container_name, "handling_unit_id"
            )
            frappe.throw(
                _("Reusable container {0} allocation no longer matches its complete physical contents. "
                  "Release the container allocation and scan it again.").format(container_code)
            )


def _delivery_exception(delivery, exception_type, message, reference_name):
    exception = frappe.get_doc({
        "doctype": "CFG Kanban Exception",
        "exception_type": exception_type,
        "severity": "Critical",
        "status": "Open",
        "delivery_session": delivery.name,
        "message": message,
        "reference_doctype": "CFG ERP Command",
        "reference_name": reference_name,
        "raised_on": now_datetime(),
    }).insert(ignore_permissions=True)
    delivery.db_set({"state": "Exception", "exception": exception.name},
                    update_modified=True)
    return exception


def _resolve_delivery_exception(delivery, resolution):
    if not delivery.exception or not frappe.db.exists(
        "CFG Kanban Exception", delivery.exception
    ):
        return
    frappe.db.set_value(
        "CFG Kanban Exception", delivery.exception,
        {"status": "Resolved", "resolved_on": now_datetime(),
         "resolved_by": frappe.session.user, "resolution": resolution},
        update_modified=True,
    )
    delivery.db_set("exception", None, update_modified=False)


def _candidate_row(unit):
    return {
        "handling_unit": unit.name,
        "visible_code": unit.handling_unit_id,
        "item_code": unit.item_code,
        "batch_no": unit.batch_no,
        "stock_uom": unit.stock_uom,
        "current_qty": flt(unit.current_qty),
        "available_qty": flt(unit.available_qty),
        "serial_count": int(unit.serial_count or 0),
    }


def _validate_container(container, delivery):
    if container.identity_state != "Active" or container.quality_state != "Released":
        frappe.throw(
            _("Reusable container {0} is {1} / {2}").format(
                container.handling_unit_id, container.identity_state, container.quality_state
            )
        )
    if container.movement_state not in ("At Source", "Packed", "Received", "Returned"):
        frappe.throw(
            _("Reusable container {0} is in movement state {1}").format(
                container.handling_unit_id, container.movement_state
            )
        )
    if container.inventory_company != delivery.selling_company:
        frappe.throw(
            _("Reusable container belongs to {0}, not selling Company {1}").format(
                container.inventory_company, delivery.selling_company
            )
        )
    if container.current_warehouse != delivery.source_warehouse:
        frappe.throw(
            _("Reusable container is in {0}, not selected lorry Warehouse {1}").format(
                container.current_warehouse, delivery.source_warehouse
            )
        )


def _validate_allocation_unit(unit, delivery, expected_container=None):
    if unit.tag_kind == "Reusable Container":
        frappe.throw(_("A reusable container must be expanded into its current Stock Tags"))
    if unit.identity_state != "Active" or unit.quality_state != "Released":
        frappe.throw(
            _("Stock Tag {0} is {1} / {2}").format(
                unit.handling_unit_id, unit.identity_state, unit.quality_state
            )
        )
    if unit.movement_state not in ("At Source", "Packed", "Received", "Returned"):
        frappe.throw(
            _("Stock Tag {0} is in movement state {1} and cannot be allocated").format(
                unit.handling_unit_id, unit.movement_state
            )
        )
    if unit.inventory_company != delivery.selling_company:
        frappe.throw(
            _("Stock Tag belongs to {0}, not selling Company {1}").format(
                unit.inventory_company, delivery.selling_company
            )
        )
    if unit.current_warehouse != delivery.source_warehouse:
        frappe.throw(
            _("Stock Tag is in {0}, not selected lorry Warehouse {1}").format(
                unit.current_warehouse, delivery.source_warehouse
            )
        )
    membership = active_container_membership(unit.name)
    if membership and membership.container_handling_unit != expected_container:
        frappe.throw(
            _("Stock Tag {0} is physically inside reusable container {1}; scan the container").format(
                unit.handling_unit_id, membership.container_visible_code
            )
        )
    if expected_container and (
        not membership or membership.container_handling_unit != expected_container
    ):
        frappe.throw(_("Reusable container contents changed; scan it again"))
    if flt(unit.current_qty) <= 0 or flt(unit.available_qty) <= 0:
        frappe.throw(_("Stock Tag {0} has no available quantity").format(unit.handling_unit_id))
    if flt(unit.reserved_qty):
        frappe.throw(_("Stock Tag {0} is already reserved").format(unit.handling_unit_id))
    existing = frappe.db.get_value(
        "CFG Kanban Delivery Allocation",
        {"handling_unit": unit.name, "state": ["in", list(ACTIVE_ALLOCATION_STATES)]},
        ["name", "delivery_session"], as_dict=True,
    )
    if existing:
        frappe.throw(
            _("Stock Tag {0} is already allocated in Delivery Session {1}").format(
                unit.handling_unit_id, existing.delivery_session
            )
        )
    _assert_not_in_open_manifest(unit.name)
    assert_erp_stock(unit, delivery.source_warehouse, unit.available_qty)


def _assert_not_in_open_manifest(handling_unit):
    rows = frappe.db.sql(
        """
        select manifest.name
        from `tabCFG Kanban Manifest Line` line
        inner join `tabCFG Kanban Movement Manifest` manifest on manifest.name=line.parent
        where line.handling_unit=%s
          and manifest.state not in ('Received','Billing Pending','Partially Billed','Billed',
                                     'Closed','Cancelled')
        limit 1
        """,
        handling_unit,
    )
    if rows:
        frappe.throw(_("Stock Tag is already assigned to open Manifest {0}").format(rows[0][0]))


def _reserve_unit(delivery, unit, qty, event_token, profile, operator_session,
                  container=None, container_visible_code=None):
    qty = flt(qty)
    unit.reload()
    _validate_allocation_unit(unit, delivery, expected_container=container)
    if qty <= 0 or qty > flt(unit.available_qty) + 0.000001:
        frappe.throw(
            _("Requested quantity {0} exceeds available quantity {1} for {2}").format(
                qty, unit.available_qty, unit.handling_unit_id
            )
        )
    reservation_key = canonical_key(
        "customer-delivery-reserve", delivery.name, unit.name, event_token
    )
    existing = frappe.db.get_value(
        "CFG Kanban Delivery Allocation", {"reservation_key": reservation_key}, "name"
    )
    if existing:
        return frappe.get_doc("CFG Kanban Delivery Allocation", existing)
    before_state = unit.movement_state
    now = now_datetime()
    try:
        allocation = frappe.get_doc({
            "doctype": "CFG Kanban Delivery Allocation",
            "state": "Reserved",
            "delivery_session": delivery.name,
            "handling_unit": unit.name,
            "visible_code": unit.handling_unit_id,
            "container_handling_unit": container,
            "container_visible_code": container_visible_code,
            "item_code": unit.item_code,
            "batch_no": unit.batch_no,
            "stock_uom": unit.stock_uom,
            "allocated_qty": qty,
            "source_warehouse": delivery.source_warehouse,
            "reserved_by_operator": profile.employee,
            "operator_session": operator_session.name,
            "reserved_on": now,
            "movement_state_before_reservation": before_state,
            "reservation_key": reservation_key,
            "active_handling_unit_key": unit.name,
        }).insert(ignore_permissions=True)
    except frappe.DuplicateEntryError:
        conflict = frappe.db.get_value(
            "CFG Kanban Delivery Allocation",
            {"active_handling_unit_key": unit.name},
            ["name", "delivery_session"], as_dict=True,
        )
        if conflict:
            frappe.throw(
                _("Stock Tag {0} was concurrently reserved in Delivery Session {1}").format(
                    unit.handling_unit_id, conflict.delivery_session
                )
            )
        raise
    ledger = post_quantity_event(
        event_type="Reserve", qty=qty, stock_uom=unit.stock_uom,
        idempotency_key=reservation_key, source_handling_unit=unit.name,
        item_code=unit.item_code, batch_no=unit.batch_no,
        source_company=delivery.selling_company,
        source_warehouse=delivery.source_warehouse,
        reference_doctype=allocation.doctype, reference_name=allocation.name,
        operator=profile.employee, operator_session=operator_session.name,
        device_id=event_token,
        reason=f"Reserved for customer Delivery Session {delivery.name}",
    )
    frappe.db.set_value(allocation.doctype, allocation.name,
                        "reservation_ledger", ledger.name, update_modified=False)
    unit.db_set({"movement_state": "Reserved", "last_scan_time": now},
                update_modified=False)
    allocation.reservation_ledger = ledger.name
    return allocation


def customer_delivery_context(scan_value, profile):
    identity = resolve_logistics_scan(scan_value)
    if not identity or identity.get("identity_type") != "Customer Scan Point":
        return None
    site = _resolve_customer_site(scan_value)
    warehouses = _vehicle_warehouses(site.selling_company)
    return {
        "name": site.name,
        "site_code": site.site_code,
        "site_name": site.site_name,
        "selling_company": site.selling_company,
        "customer": site.customer,
        "customer_address": site.customer_address,
        "territory": site.territory,
        "route_reference": site.route_reference,
        "default_price_list": site.default_price_list,
        "auto_submit_delivery_note": bool(site.auto_submit_delivery_note),
        "proof_policy": site.proof_policy,
        "require_recipient_name": bool(site.require_recipient_name),
        "require_signature": bool(site.require_signature),
        "require_photo": bool(site.require_photo),
        "require_gps": bool(site.require_gps),
        "can_start_delivery": bool(_customer_delivery_allowed(profile)),
        "vehicle_warehouses": warehouses,
    }


def delivery_session_summaries(profile, limit=20):
    if not _customer_delivery_allowed(profile):
        return []
    filters = {"state": ["not in", list(DELIVERY_TERMINAL_STATES)]}
    if not _can_view_all(profile):
        filters["started_by_operator"] = profile.employee
    return frappe.get_all(
        "CFG Kanban Delivery Session",
        filters=filters,
        fields=[
            "name", "state", "site_code", "site_name", "selling_company", "customer",
            "source_warehouse", "vehicle_reference", "started_by_operator", "started_on",
            "delivery_note",
        ],
        order_by="modified desc",
        limit_page_length=limit,
    )


def _resolve_customer_site(scan_value):
    identity = resolve_logistics_scan(scan_value)
    if not identity or identity.get("identity_type") != "Customer Scan Point":
        frappe.throw(_("Scan an active Customer Site code"))
    site = frappe.get_doc("CFG Kanban Customer Scan Point", identity["name"])
    if not site.active:
        frappe.throw(_("Customer Site {0} is inactive").format(site.site_code))
    if frappe.db.get_value("Customer", site.customer, "disabled"):
        frappe.throw(_("Customer {0} is disabled").format(site.customer))
    return site


def _vehicle_warehouse(warehouse, company):
    matches = [row for row in _vehicle_warehouses(company) if row.name == warehouse]
    if not matches:
        frappe.throw(
            _("Warehouse {0} is not an active Vehicle Warehouse for {1}").format(
                warehouse, company
            )
        )
    return matches[0]


def _vehicle_warehouses(company):
    meta = frappe.get_meta("Warehouse")
    if not (
        meta.has_field("cfg_is_vehicle_warehouse")
        and meta.has_field("cfg_vehicle_reference")
    ):
        frappe.throw(_("Run CFG Kanban migration before using Customer Delivery"))
    rows = frappe.get_all(
        "Warehouse",
        filters={
            "company": company,
            "disabled": 0,
            "is_group": 0,
            "cfg_is_vehicle_warehouse": 1,
        },
        fields=["name", "warehouse_name", "company", "cfg_vehicle_reference"],
        order_by="cfg_vehicle_reference asc, warehouse_name asc",
        limit_page_length=200,
    )
    return [frappe._dict({
        "name": row.name,
        "warehouse_name": row.warehouse_name,
        "company": row.company,
        "vehicle_reference": row.cfg_vehicle_reference,
    }) for row in rows if row.cfg_vehicle_reference]


def _customer_delivery_allowed(profile):
    return bool(
        _can_view_all(profile)
        or CUSTOMER_DELIVERY_RESPONSIBILITY in {
            row.responsibility for row in profile.responsibilities if row.responsibility
        }
    )


def _require_customer_delivery(profile):
    if not _customer_delivery_allowed(profile):
        frappe.throw(_("Operator is not assigned to Customer Delivery"), frappe.PermissionError)


def _can_view_delivery(profile, delivery):
    return bool(_can_view_all(profile) or delivery.started_by_operator == profile.employee)


def assert_delivery_access(delivery_session, profile):
    """Return an authorised delivery session for related operator workflows."""
    delivery = frappe.get_doc("CFG Kanban Delivery Session", delivery_session)
    if not _can_view_delivery(profile, delivery):
        frappe.throw(_("Operator cannot access this Delivery Session"), frappe.PermissionError)
    return delivery


def _can_view_all(profile):
    return bool(
        profile.kanban_role in ("Supervisor", "Development Proxy")
        and profile.get("view_all_responsibilities")
    )
