import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from cfg_kanban.services.container_contents import (
    active_container_contents,
    active_container_membership,
)
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import (
    assert_erp_stock,
    post_quantity_event,
    resolve_logistics_scan,
    validate_price_list_mode,
)
from cfg_kanban.services.operator_auth import require_operator


CUSTOMER_DELIVERY_RESPONSIBILITY = "Customer Delivery"
DELIVERY_TERMINAL_STATES = {"Delivered", "Invoiced", "Closed", "Rejected", "Cancelled"}
ACTIVE_ALLOCATION_STATES = ("Reserved", "Delivery Pending", "Delivered", "Exception")


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
    names = frappe.get_all(
        "CFG Kanban Delivery Allocation",
        filters={"delivery_session": delivery.name, "state": "Reserved"},
        pluck="name", limit_page_length=500,
    )
    if not names:
        frappe.throw(_("Allocate at least one Stock Tag before confirmation"))
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
    release_key = canonical_key("customer-delivery-release", row.name, event_token)
    if row.state == "Released":
        return get_delivery_session(delivery.name, operator_session_token)
    if row.state not in ("Reserved", "Delivery Pending") or row.delivery_note:
        frappe.throw(_("Only an undelivered active allocation can be released"))
    unit = frappe.get_doc("CFG Kanban Handling Unit", row.handling_unit)
    ledger = post_quantity_event(
        event_type="Unreserve", qty=row.allocated_qty, stock_uom=row.stock_uom,
        idempotency_key=release_key, source_handling_unit=unit.name,
        item_code=row.item_code, batch_no=row.batch_no,
        source_company=delivery.selling_company,
        source_warehouse=delivery.source_warehouse,
        reference_doctype=row.doctype, reference_name=row.name,
        operator=profile.employee, operator_session=operator_session.name,
        device_id=event_token, reason=reason.strip(),
    )
    now = now_datetime()
    frappe.db.set_value(row.doctype, row.name, {
        "state": "Released", "active_handling_unit_key": None,
        "released_on": now, "release_reason": reason.strip(),
        "release_ledger": ledger.name, "release_key": release_key,
    }, update_modified=True)
    unit.reload()
    if not flt(unit.reserved_qty):
        unit.db_set({
            "movement_state": row.movement_state_before_reservation or "At Source",
            "last_scan_time": now,
        }, update_modified=False)

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
        delivery_session=delivery.name, handling_unit=unit.name,
        qty=row.allocated_qty, previous_state=row.state, new_state="Released",
        reference_doctype=row.doctype, reference_name=row.name,
        device_id=release_key, notes=reason.strip(), operator=profile.employee,
        operator_session=operator_session.name,
        terminal_user=operator_session.terminal_user,
    )
    return get_delivery_session(delivery.name, operator_session_token)


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


def _can_view_all(profile):
    return bool(
        profile.kanban_role in ("Supervisor", "Development Proxy")
        and profile.get("view_all_responsibilities")
    )
