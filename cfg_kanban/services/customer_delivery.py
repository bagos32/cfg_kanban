import frappe
from frappe import _
from frappe.utils import now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import (
    resolve_logistics_scan,
    validate_price_list_mode,
)
from cfg_kanban.services.operator_auth import require_operator


CUSTOMER_DELIVERY_RESPONSIBILITY = "Customer Delivery"
DELIVERY_TERMINAL_STATES = {"Delivered", "Invoiced", "Closed", "Rejected", "Cancelled"}


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
            "delivery_note",
        ],
        order_by="reserved_on asc",
        limit_page_length=500,
    )
    return result


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
    if frappe.db.exists("CFG Kanban Delivery Allocation", {"delivery_session": delivery.name}):
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
