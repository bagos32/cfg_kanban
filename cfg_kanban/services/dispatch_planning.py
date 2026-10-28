import hashlib
import json

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, today

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import (
    assert_erp_stock,
    post_quantity_event,
    resolve_logistics_scan,
    validate_warehouse_company,
)
from cfg_kanban.services.operator_auth import require_operator


RESERVABLE_STATES = {"Approved", "Picking", "Ready for Vehicle"}
ACTIVE_ALLOCATION_STATES = {"Reserved"}
VEHICLE_LOADING_STATES = {
    "Vehicle Claimed", "Loading", "Ready to Dispatch", "Dispatch Pending",
}
PROFILE_SNAPSHOT_FIELDS = (
    "name", "business_label", "revision", "dispatch_point", "company",
    "source_warehouse", "plan_type", "fulfilment_mode", "customer_site", "territory",
    "logistics_route", "destination_assignment_policy", "destination_warehouse",
    "staging_warehouse", "transit_warehouse", "tag_policy", "stock_rotation_policy",
    "approval_required", "allow_supervisor_override", "auto_submit_stock_transfer",
    "auto_submit_delivery_note", "proof_policy", "dispatch_responsibility",
)


@frappe.whitelist()
def create_dispatch_plan(dispatch_profile, lines, customer_site=None, sales_order=None,
                         logistics_route=None, territory=None, required_date=None,
                         trip_date=None, priority="Normal", event_token=None,
                         operator_session_token=None):
    _require_event_token(event_token)
    operator, session = require_operator(operator_session_token, "start")
    policy = _authorized_profile(dispatch_profile, operator)
    priority = priority or "Normal"
    if priority not in {"Low", "Normal", "High", "Urgent"}:
        frappe.throw("Priority must be Low, Normal, High or Urgent")
    rows = _normalize_lines(lines, sales_order)
    context = _business_context(
        policy, customer_site=customer_site, sales_order=sales_order,
        logistics_route=logistics_route, territory=territory,
        required_date=required_date, trip_date=trip_date,
    )
    key = canonical_key("dispatch-plan-create", policy.name, event_token or "")
    existing = frappe.db.get_value(
        "CFG Kanban Dispatch Plan", {"idempotency_key": key}, "name"
    )
    if existing:
        return get_dispatch_plan(existing, operator_session_token)

    snapshot = {fieldname: policy.get(fieldname) for fieldname in PROFILE_SNAPSHOT_FIELDS}
    snapshot_json = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
    plan = frappe.get_doc({
        "doctype": "CFG Kanban Dispatch Plan",
        "state": "Draft",
        "business_label": policy.business_label,
        "dispatch_profile": policy.name,
        "profile_revision": policy.revision,
        "profile_snapshot_json": snapshot_json,
        "profile_snapshot_hash": hashlib.sha256(snapshot_json.encode()).hexdigest(),
        "dispatch_point": policy.dispatch_point,
        "company": policy.company,
        "source_warehouse": policy.source_warehouse,
        "plan_type": policy.plan_type,
        "fulfilment_mode": policy.fulfilment_mode,
        "tag_policy": policy.tag_policy,
        "stock_rotation_policy": policy.stock_rotation_policy,
        "approval_required": policy.approval_required,
        "allow_supervisor_override": policy.allow_supervisor_override,
        "auto_submit_stock_transfer": policy.auto_submit_stock_transfer,
        "dispatch_responsibility": policy.dispatch_responsibility,
        "destination_assignment_policy": policy.destination_assignment_policy,
        "destination_warehouse": policy.destination_warehouse,
        "staging_warehouse": policy.staging_warehouse,
        "transit_warehouse": policy.transit_warehouse,
        "proof_policy": policy.proof_policy,
        **context,
        "priority": priority or "Normal",
        "lines": rows,
        "created_by_operator": operator.employee,
        "created_operator_session": session.name,
        "created_by_user": session.terminal_user,
        "created_on": now_datetime(),
        "idempotency_key": key,
    })
    try:
        plan.insert(ignore_permissions=True)
    except frappe.DuplicateEntryError:
        existing = frappe.db.get_value(
            "CFG Kanban Dispatch Plan", {"idempotency_key": key}, "name"
        )
        if existing:
            return get_dispatch_plan(existing, operator_session_token)
        raise
    record(
        "Dispatch Plan Created", reference_doctype=plan.doctype, reference_name=plan.name,
        previous_state=None, new_state="Draft", device_id=event_token,
        operator=operator.employee, operator_session=session.name,
        terminal_user=session.terminal_user,
        notes=f"{plan.plan_type}; {plan.business_label}; no stock reserved",
    )
    return get_dispatch_plan(plan.name, operator_session_token)


@frappe.whitelist()
def submit_dispatch_plan(dispatch_plan, event_token=None, operator_session_token=None):
    _require_event_token(event_token)
    operator, session = require_operator(operator_session_token, "start")
    plan = _locked_authorized_plan(dispatch_plan, operator)
    if plan.state != "Draft":
        if plan.state in ("Awaiting Approval", "Approved"):
            return get_dispatch_plan(plan.name, operator_session_token)
        frappe.throw(f"Dispatch Plan {plan.name} cannot be submitted from {plan.state}")
    _assert_plan_lines(plan)
    next_state = "Awaiting Approval" if cint(plan.approval_required) else "Approved"
    values = {
        "state": next_state,
        "submitted_by_operator": operator.employee,
        "submitted_on": now_datetime(),
    }
    if next_state == "Approved":
        values.update({
            "approved_by_operator": operator.employee,
            "approved_operator_session": session.name,
            "approved_on": now_datetime(),
        })
    plan.db_set(values, update_modified=True)
    record(
        "Dispatch Plan Submitted", reference_doctype=plan.doctype,
        reference_name=plan.name, previous_state="Draft", new_state=next_state,
        device_id=event_token, operator=operator.employee,
        operator_session=session.name, terminal_user=session.terminal_user,
    )
    return get_dispatch_plan(plan.name, operator_session_token)


@frappe.whitelist()
def approve_dispatch_plan(dispatch_plan, event_token=None, operator_session_token=None):
    _require_event_token(event_token)
    operator, session = require_operator(operator_session_token)
    plan = _locked_authorized_plan(dispatch_plan, operator)
    if plan.state == "Approved":
        return get_dispatch_plan(plan.name, operator_session_token)
    if plan.state != "Awaiting Approval":
        frappe.throw(f"Dispatch Plan {plan.name} is not awaiting approval")
    if not cint(operator.get("can_override")):
        frappe.throw("Supervisor Override permission is required to approve a Dispatch Plan")
    plan.db_set({
        "state": "Approved", "approved_by_operator": operator.employee,
        "approved_operator_session": session.name, "approved_on": now_datetime(),
    }, update_modified=True)
    record(
        "Dispatch Plan Approved", reference_doctype=plan.doctype,
        reference_name=plan.name, previous_state="Awaiting Approval", new_state="Approved",
        device_id=event_token, operator=operator.employee,
        operator_session=session.name, terminal_user=session.terminal_user,
    )
    return get_dispatch_plan(plan.name, operator_session_token)


@frappe.whitelist()
def reserve_dispatch_tag(dispatch_plan, dispatch_plan_line, scan_value, qty=0,
                         event_token=None, operator_session_token=None):
    _require_event_token(event_token)
    operator, session = require_operator(operator_session_token, "start")
    plan = _locked_authorized_plan(dispatch_plan, operator)
    _assert_reservable(plan, "Tagged")
    line = _plan_line(plan, dispatch_plan_line)
    identity = resolve_logistics_scan(scan_value)
    if not identity or identity.get("identity_type") != "Handling Unit":
        frappe.throw("Scan an active Stock Tag Handling Unit")
    unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    key = canonical_key(
        "dispatch-plan-tag-reserve", plan.name, line.name, unit.name, event_token or ""
    )
    existing = frappe.db.get_value(
        "CFG Kanban Dispatch Allocation", {"reservation_key": key}, "name"
    )
    if existing:
        return get_dispatch_plan(plan.name, operator_session_token)
    active = frappe.db.get_value(
        "CFG Kanban Dispatch Allocation",
        {"active_handling_unit_key": unit.name, "state": "Reserved"},
        ["dispatch_plan", "dispatch_plan_line"], as_dict=True,
    )
    if active and active.dispatch_plan == plan.name and active.dispatch_plan_line == line.name:
        return get_dispatch_plan(plan.name, operator_session_token)
    _validate_tag_for_plan(unit, plan, line)
    remaining = flt(line.requested_qty) - _active_line_reserved(line.name)
    requested = flt(qty) or min(flt(unit.available_qty), remaining)
    if requested <= 0 or requested > remaining + 0.000001:
        frappe.throw(f"Tagged reservation must be between 0 and remaining quantity {remaining}")
    if requested > flt(unit.available_qty) + 0.000001:
        frappe.throw(
            f"Stock Tag {unit.handling_unit_id} has only {unit.available_qty} "
            f"{unit.stock_uom} available"
        )
    if (cint(frappe.db.get_value("Item", unit.item_code, "has_serial_no"))
            and abs(requested - flt(unit.available_qty)) > 0.000001):
        frappe.throw(
            f"Serialized Stock Tag {unit.handling_unit_id} must be reserved in full; "
            "split it into exact physical identities first"
        )
    assert_erp_stock(unit, plan.source_warehouse, requested)
    _assert_not_in_open_manifest(unit.name)
    before_state = unit.movement_state
    allocation = frappe.get_doc({
        "doctype": "CFG Kanban Dispatch Allocation",
        "state": "Reserved", "allocation_kind": "Tagged Stock",
        "dispatch_plan": plan.name, "dispatch_plan_line": line.name,
        "handling_unit": unit.name, "visible_code": unit.handling_unit_id,
        "item_code": unit.item_code, "batch_no": unit.batch_no,
        "stock_uom": unit.stock_uom, "allocated_qty": requested,
        "source_company": plan.company, "source_warehouse": plan.source_warehouse,
        "reserved_by_operator": operator.employee, "operator_session": session.name,
        "reserved_on": now_datetime(),
        "movement_state_before_reservation": before_state,
        "reservation_key": key, "active_handling_unit_key": unit.name,
    })
    try:
        allocation.insert(ignore_permissions=True)
    except frappe.DuplicateEntryError:
        conflict = frappe.db.get_value(
            "CFG Kanban Dispatch Allocation", {"active_handling_unit_key": unit.name},
            ["name", "dispatch_plan"], as_dict=True,
        )
        if conflict:
            frappe.throw(
                f"Stock Tag {unit.handling_unit_id} is already reserved in Dispatch Plan "
                f"{conflict.dispatch_plan}"
            )
        raise
    ledger = post_quantity_event(
        event_type="Reserve", qty=requested, stock_uom=unit.stock_uom,
        idempotency_key=key, source_handling_unit=unit.name,
        item_code=unit.item_code, batch_no=unit.batch_no,
        source_company=plan.company, source_warehouse=plan.source_warehouse,
        reference_doctype=allocation.doctype, reference_name=allocation.name,
        operator=operator.employee, operator_session=session.name,
        device_id=event_token, reason=f"Reserved for Dispatch Plan {plan.name}",
    )
    allocation.db_set("reservation_ledger", ledger.name, update_modified=False)
    unit.db_set({"movement_state": "Reserved", "last_scan_time": now_datetime()},
                update_modified=False)
    _refresh_plan_totals(plan.name)
    record(
        "Dispatch Tagged Stock Reserved", handling_unit=unit.name, qty=requested,
        reference_doctype=allocation.doctype, reference_name=allocation.name,
        device_id=event_token, operator=operator.employee,
        operator_session=session.name, terminal_user=session.terminal_user,
        notes=f"Dispatch Plan {plan.name}; line {line.name}",
    )
    return get_dispatch_plan(plan.name, operator_session_token)


@frappe.whitelist()
def reserve_dispatch_untagged(dispatch_plan, dispatch_plan_line, qty, batch_no=None,
                              event_token=None, operator_session_token=None):
    _require_event_token(event_token)
    operator, session = require_operator(operator_session_token, "start")
    plan = _locked_authorized_plan(dispatch_plan, operator)
    _assert_reservable(plan, "Untagged")
    line = _plan_line(plan, dispatch_plan_line)
    qty = flt(qty)
    if qty <= 0:
        frappe.throw("Untagged reservation quantity must be positive")
    inventory = frappe.db.get_value(
        "Item", line.item_code, ["is_stock_item", "has_serial_no", "has_batch_no"],
        as_dict=True,
    )
    if not inventory or not cint(inventory.is_stock_item):
        frappe.throw(
            "Untagged reservation requires an ERPNext stock Item; use a physical Stock Tag "
            "for Kanban operational inventory"
        )
    if cint(inventory.has_serial_no):
        frappe.throw(
            f"Serialized Item {line.item_code} requires exact tagged stock reservation"
        )
    batch_no = batch_no or line.batch_no
    if cint(inventory.has_batch_no) and not batch_no:
        frappe.throw(f"Batch is required to reserve untagged stock for {line.item_code}")
    if line.batch_no and batch_no != line.batch_no:
        frappe.throw(f"This line is restricted to Batch {line.batch_no}")
    key = canonical_key(
        "dispatch-plan-untagged-reserve", plan.name, line.name, batch_no or "",
        event_token or "",
    )
    existing = frappe.db.get_value(
        "CFG Kanban Dispatch Allocation", {"reservation_key": key}, "name"
    )
    if existing:
        return get_dispatch_plan(plan.name, operator_session_token)
    _validate_batch(line.item_code, batch_no)
    _lock_erp_bin(line.item_code, plan.source_warehouse)
    remaining = flt(line.requested_qty) - _active_line_reserved(line.name)
    if qty > remaining + 0.000001:
        frappe.throw(f"Untagged reservation exceeds remaining quantity {remaining}")
    available = _untagged_available(
        plan.company, plan.source_warehouse, line.item_code, batch_no
    )
    if qty > available + 0.000001:
        frappe.throw(
            f"Verified untagged ERP stock is {available} {line.stock_uom}; "
            f"requested {qty}"
        )
    allocation = frappe.get_doc({
        "doctype": "CFG Kanban Dispatch Allocation",
        "state": "Reserved", "allocation_kind": "Untagged ERP Stock",
        "dispatch_plan": plan.name, "dispatch_plan_line": line.name,
        "visible_code": "ERP STOCK", "item_code": line.item_code,
        "batch_no": batch_no, "stock_uom": line.stock_uom,
        "allocated_qty": qty, "source_company": plan.company,
        "source_warehouse": plan.source_warehouse,
        "reserved_by_operator": operator.employee, "operator_session": session.name,
        "reserved_on": now_datetime(), "reservation_key": key,
    })
    try:
        allocation.insert(ignore_permissions=True)
    except frappe.DuplicateEntryError:
        existing = frappe.db.get_value(
            "CFG Kanban Dispatch Allocation", {"reservation_key": key}, "name"
        )
        if existing:
            return get_dispatch_plan(plan.name, operator_session_token)
        raise
    _refresh_plan_totals(plan.name)
    record(
        "Dispatch Untagged Stock Reserved", qty=qty,
        reference_doctype=allocation.doctype, reference_name=allocation.name,
        device_id=event_token, operator=operator.employee,
        operator_session=session.name, terminal_user=session.terminal_user,
        notes=(f"Dispatch Plan {plan.name}; {line.item_code}; "
               f"Batch {batch_no or 'No Batch'}; no ERP stock movement"),
    )
    return get_dispatch_plan(plan.name, operator_session_token)


@frappe.whitelist()
def release_dispatch_allocation(allocation_name, reason, event_token=None,
                                operator_session_token=None):
    _require_event_token(event_token)
    operator, session = require_operator(operator_session_token, "start")
    allocation = frappe.get_doc("CFG Kanban Dispatch Allocation", allocation_name)
    plan = _locked_authorized_plan(allocation.dispatch_plan, operator)
    if plan.state not in RESERVABLE_STATES:
        frappe.throw(f"Allocation cannot be released while Plan is {plan.state}")
    _release_allocation(allocation, plan, operator, session, reason, event_token)
    _refresh_plan_totals(plan.name)
    return get_dispatch_plan(plan.name, operator_session_token)


@frappe.whitelist()
def cancel_dispatch_plan(dispatch_plan, reason, event_token=None,
                         operator_session_token=None):
    _require_event_token(event_token)
    operator, session = require_operator(operator_session_token)
    plan = _locked_authorized_plan(dispatch_plan, operator)
    reason = (reason or "").strip()
    if not reason:
        frappe.throw("Cancellation reason is required")
    if plan.state == "Cancelled":
        return get_dispatch_plan(plan.name, operator_session_token)
    if plan.state not in {"Draft", "Awaiting Approval", *RESERVABLE_STATES}:
        frappe.throw(f"Dispatch Plan cannot be cancelled from {plan.state}")
    if plan.state in RESERVABLE_STATES and not cint(operator.get("can_override")):
        frappe.throw("Supervisor Override permission is required to cancel an approved Plan")
    if plan.state not in RESERVABLE_STATES and not cint(operator.get("can_start")):
        frappe.throw("Start permission is required to cancel a Draft or pending Dispatch Plan")
    allocations = frappe.get_all(
        "CFG Kanban Dispatch Allocation",
        filters={"dispatch_plan": plan.name, "state": "Reserved"},
        pluck="name", order_by="creation asc", limit_page_length=0,
    )
    for name in allocations:
        _release_allocation(
            frappe.get_doc("CFG Kanban Dispatch Allocation", name), plan,
            operator, session, reason, canonical_key(event_token or "", name),
            final_state="Cancelled",
        )
    previous = plan.state
    plan.db_set({
        "state": "Cancelled", "total_reserved_qty": 0,
        "cancelled_by_operator": operator.employee,
        "cancelled_operator_session": session.name,
        "cancelled_on": now_datetime(), "cancellation_reason": reason,
    }, update_modified=True)
    for line in plan.lines:
        frappe.db.set_value(
            "CFG Kanban Dispatch Plan Line", line.name,
            {"reserved_qty": 0, "line_state": "Cancelled"}, update_modified=False,
        )
    record(
        "Dispatch Plan Cancelled", reference_doctype=plan.doctype,
        reference_name=plan.name, previous_state=previous, new_state="Cancelled",
        device_id=event_token, operator=operator.employee,
        operator_session=session.name, terminal_user=session.terminal_user,
        notes=reason,
    )
    return get_dispatch_plan(plan.name, operator_session_token)


@frappe.whitelist()
def claim_dispatch_vehicle(dispatch_plan, scan_value, event_token=None,
                           operator_session_token=None):
    """Atomically claim one ready E2 Plan with a Company-specific lorry Warehouse card."""
    _require_event_token(event_token)
    operator, session = require_operator(operator_session_token, "start")
    plan = _locked_authorized_plan(dispatch_plan, operator)
    vehicle_warehouse = _vehicle_warehouse_from_scan(scan_value, plan.company)
    if plan.state in VEHICLE_LOADING_STATES | {"Loaded"}:
        if plan.vehicle_warehouse != vehicle_warehouse.name:
            frappe.throw(
                f"Dispatch Plan {plan.name} is already claimed by vehicle "
                f"{plan.vehicle_reference or plan.vehicle_warehouse}"
            )
        return get_dispatch_plan(plan.name, operator_session_token)
    if plan.state != "Ready for Vehicle":
        frappe.throw(f"Dispatch Plan must be Ready for Vehicle; current state is {plan.state}")
    if plan.fulfilment_mode != "Vehicle Delivery":
        frappe.throw(
            f"Vehicle claim is available only for Vehicle Delivery Plans; this Plan uses "
            f"{plan.fulfilment_mode}"
        )
    route = _vehicle_loading_route(plan, vehicle_warehouse.name, operator)
    _assert_e3_allocations_ready(plan)
    claim_key = canonical_key(
        "dispatch-plan-vehicle-claim", plan.name, vehicle_warehouse.name, event_token or ""
    )
    existing = frappe.db.get_value(
        "CFG Kanban Movement Manifest",
        {"dispatch_plan": plan.name, "state": ["!=", "Cancelled"]}, "name",
    )
    if existing:
        frappe.throw(f"Dispatch Plan already owns Movement Manifest {existing}")

    plan.db_set({
        "state": "Vehicle Claimed",
        "vehicle_warehouse": vehicle_warehouse.name,
        "vehicle_reference": vehicle_warehouse.cfg_vehicle_reference,
        "claim_key": claim_key,
        "claimed_by_operator": operator.employee,
        "claimed_operator_session": session.name,
        "claimed_on": now_datetime(),
    }, update_modified=True)
    plan.reload()
    manifest = _create_vehicle_manifest(plan, route, operator, session, claim_key)
    plan.db_set("movement_manifest", manifest.name, update_modified=True)
    record(
        "Dispatch Vehicle Claimed", movement_manifest=manifest.name,
        reference_doctype=plan.doctype, reference_name=plan.name,
        previous_state="Ready for Vehicle", new_state="Vehicle Claimed",
        device_id=event_token, operator=operator.employee,
        operator_session=session.name, terminal_user=session.terminal_user,
        notes=(f"{vehicle_warehouse.cfg_vehicle_reference}; "
               f"{vehicle_warehouse.name}; Manifest {manifest.name}"),
    )
    return get_dispatch_plan(plan.name, operator_session_token)


def confirm_plan_tag_loaded(manifest_name, scan_value, event_token,
                            operator_session_token):
    """Bind a physical Stock Tag scan to its already-reserved E2 allocation."""
    _require_event_token(event_token)
    operator, session = require_operator(operator_session_token, "start")
    manifest, plan = _locked_plan_manifest(manifest_name, operator)
    if manifest.state != "Draft" or plan.state not in {"Vehicle Claimed", "Loading"}:
        frappe.throw("Tagged loading can be confirmed only while the claimed Manifest is Draft")
    identity = resolve_logistics_scan(scan_value)
    if not identity or identity.get("identity_type") != "Handling Unit":
        frappe.throw("Scan the exact reserved Stock Tag")
    allocation = frappe.db.get_value(
        "CFG Kanban Dispatch Allocation",
        {"dispatch_plan": plan.name, "handling_unit": identity["name"], "state": "Reserved"},
        ["name", "manifest_line", "allocated_qty", "item_code", "stock_uom",
         "source_warehouse", "load_confirmed"], as_dict=True,
    )
    if not allocation:
        frappe.throw("This Stock Tag is not reserved for the selected Dispatch Plan")
    if allocation.load_confirmed:
        return _manifest_result(manifest.name, operator_session_token)
    unit = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    if (unit.current_warehouse != plan.source_warehouse or unit.inventory_company != plan.company
            or unit.item_code != allocation.item_code
            or unit.stock_uom != allocation.stock_uom):
        frappe.throw("Reserved Stock Tag no longer matches the Plan source, Item or UOM")
    if abs(flt(unit.current_qty) - flt(allocation.allocated_qty)) > 0.000001:
        frappe.throw(
            "Reserved Stock Tag quantity changed after vehicle claim; split/repack and "
            "reclaim the exact physical load"
        )
    key = canonical_key(
        "dispatch-plan-tag-loaded", plan.name, allocation.name, event_token or ""
    )
    _confirm_allocation_loading(
        allocation.name, allocation.manifest_line, manifest, plan,
        operator, session, key,
    )
    record(
        "Dispatch Tagged Stock Loaded", movement_manifest=manifest.name,
        handling_unit=unit.name, qty=allocation.allocated_qty,
        reference_doctype="CFG Kanban Dispatch Allocation",
        reference_name=allocation.name, device_id=event_token,
        operator=operator.employee, operator_session=session.name,
        terminal_user=session.terminal_user,
        notes=f"Vehicle {plan.vehicle_reference}; Plan {plan.name}",
    )
    return _manifest_result(manifest.name, operator_session_token)


@frappe.whitelist()
def confirm_dispatch_untagged_loaded(manifest_name, manifest_line, event_token=None,
                                     operator_session_token=None):
    """Confirm the physical pick of one reserved untagged ERP-stock allocation."""
    _require_event_token(event_token)
    operator, session = require_operator(operator_session_token, "start")
    manifest, plan = _locked_plan_manifest(manifest_name, operator)
    if manifest.state != "Draft" or plan.state not in {"Vehicle Claimed", "Loading"}:
        frappe.throw("Untagged loading can be confirmed only while the claimed Manifest is Draft")
    line = next((row for row in manifest.lines if row.name == manifest_line), None)
    if not line or line.line_kind != "ERP Stock without Physical Tag":
        frappe.throw("Select an untagged ERP-stock Manifest line")
    allocation = frappe.get_doc("CFG Kanban Dispatch Allocation", line.dispatch_allocation)
    if allocation.dispatch_plan != plan.name or allocation.state != "Reserved":
        frappe.throw("Untagged allocation is no longer actively reserved for this Plan")
    if allocation.load_confirmed:
        return _manifest_result(manifest.name, operator_session_token)
    _assert_untagged_allocation_available(allocation)
    key = canonical_key(
        "dispatch-plan-untagged-loaded", plan.name, allocation.name, event_token or ""
    )
    _confirm_allocation_loading(
        allocation.name, line.name, manifest, plan, operator, session, key
    )
    record(
        "Dispatch Untagged Stock Loaded", movement_manifest=manifest.name,
        qty=allocation.allocated_qty,
        reference_doctype=allocation.doctype, reference_name=allocation.name,
        device_id=event_token, operator=operator.employee,
        operator_session=session.name, terminal_user=session.terminal_user,
        notes=(f"{allocation.item_code}; Batch {allocation.batch_no or 'No Batch'}; "
               f"vehicle {plan.vehicle_reference}"),
    )
    return _manifest_result(manifest.name, operator_session_token)


@frappe.whitelist()
def get_dispatch_plan(dispatch_plan, operator_session_token):
    operator, _session = require_operator(operator_session_token)
    plan = frappe.get_doc("CFG Kanban Dispatch Plan", dispatch_plan)
    _assert_plan_authorized(plan, operator)
    result = plan.as_dict()
    result["allocations"] = frappe.get_all(
        "CFG Kanban Dispatch Allocation",
        filters={"dispatch_plan": plan.name},
        fields=[
            "name", "state", "allocation_kind", "dispatch_plan_line", "handling_unit",
            "visible_code", "item_code", "batch_no", "stock_uom", "allocated_qty",
            "source_warehouse", "reserved_by_operator", "reserved_on", "released_on",
            "release_reason", "movement_manifest", "manifest_line", "load_confirmed",
            "loaded_by_operator", "loaded_on",
        ],
        order_by="creation asc", limit_page_length=0,
    )
    result["can_submit"] = bool(plan.state == "Draft" and operator.can_start)
    result["can_approve"] = bool(
        plan.state == "Awaiting Approval" and cint(operator.get("can_override"))
    )
    result["can_reserve"] = bool(plan.state in RESERVABLE_STATES and operator.can_start)
    result["can_claim_vehicle"] = bool(
        plan.state == "Ready for Vehicle" and plan.fulfilment_mode == "Vehicle Delivery"
        and operator.can_start
    )
    result["can_release_vehicle_claim"] = bool(
        plan.state in {"Vehicle Claimed", "Loading", "Ready to Dispatch"}
        and cint(operator.get("can_override")) and bool(plan.movement_manifest)
    )
    result["can_cancel"] = bool(
        (plan.state in ("Draft", "Awaiting Approval") and operator.can_start) or
        (plan.state in RESERVABLE_STATES and cint(operator.get("can_override")))
    )
    result["suggested_tags_by_line"] = {
        row.name: _suggested_tags(plan, row) for row in plan.lines
    } if plan.state in RESERVABLE_STATES and plan.tag_policy in ("Tagged", "Mixed") else {}
    result["policy_only_reservation"] = int(plan.state in RESERVABLE_STATES)
    result["vehicle_claim_active"] = int(plan.state in VEHICLE_LOADING_STATES)
    return result


def dispatch_point_plans(card, operator):
    """Read-only summaries for the E1/E2 permanent Dispatch Operations launcher."""
    responsibilities = _responsibilities(operator)
    view_all = _view_all(operator)
    rows = frappe.get_all(
        "CFG Kanban Dispatch Plan",
        filters={
            "dispatch_point": card.name,
            "company": card.company,
            "source_warehouse": card.current_warehouse,
            "state": ["in", [
                "Draft", "Awaiting Approval", "Approved", "Picking", "Ready for Vehicle",
                "Vehicle Claimed", "Loading", "Ready to Dispatch", "Dispatch Pending",
            ]],
        },
        fields=[
            "name", "state", "business_label", "dispatch_profile", "plan_type",
            "fulfilment_mode", "customer_site", "customer", "territory",
            "logistics_route", "required_date", "trip_date", "priority",
            "total_requested_qty", "total_reserved_qty", "dispatch_responsibility",
            "vehicle_warehouse", "vehicle_reference", "movement_manifest",
            "modified",
        ],
        order_by="required_date asc, creation asc",
        limit_page_length=200,
    )
    rows = [
        row for row in rows
        if view_all or row.dispatch_responsibility in responsibilities
    ]
    by_plan = {}
    if rows:
        for line in frappe.get_all(
                "CFG Kanban Dispatch Plan Line",
                filters={"parent": ["in", [row.name for row in rows]]},
                fields=["parent", "stock_uom", "requested_qty", "reserved_qty"],
                limit_page_length=0):
            values = by_plan.setdefault(line.parent, {}).setdefault(
                line.stock_uom, {"requested": 0, "reserved": 0}
            )
            values["requested"] += flt(line.requested_qty)
            values["reserved"] += flt(line.reserved_qty)
    for row in rows:
        row["quantity_summary"] = ", ".join(
            f"{values['reserved']:g}/{values['requested']:g} {uom}"
            for uom, values in sorted(by_plan.get(row.name, {}).items())
        )
    priority_order = {"Urgent": 0, "High": 1, "Normal": 2, "Low": 3}
    rows.sort(key=lambda row: (
        priority_order.get(row.priority, 2), str(row.required_date or row.trip_date or ""),
        str(row.modified or ""),
    ))
    return rows


def claimable_vehicle_plans(vehicle_warehouse, operator):
    """Return Ready Plans eligible for one scanned Company-specific lorry Warehouse."""
    vehicle = _vehicle_warehouse(vehicle_warehouse)
    responsibilities = _responsibilities(operator)
    view_all = _view_all(operator)
    rows = frappe.get_all(
        "CFG Kanban Dispatch Plan",
        filters={
            "company": vehicle.company,
            "state": "Ready for Vehicle",
            "fulfilment_mode": "Vehicle Delivery",
        },
        fields=[
            "name", "business_label", "plan_type", "customer", "customer_site",
            "territory", "logistics_route", "required_date", "trip_date", "priority",
            "total_requested_qty", "total_reserved_qty", "dispatch_responsibility",
            "destination_assignment_policy", "destination_warehouse",
        ],
        order_by="required_date asc, creation asc",
        limit_page_length=200,
    )
    eligible = []
    for row in rows:
        if not (view_all or row.dispatch_responsibility in responsibilities):
            continue
        if row.destination_assignment_policy == "Fixed" and row.destination_warehouse != vehicle.name:
            continue
        eligible.append(row)
    priority_order = {"Urgent": 0, "High": 1, "Normal": 2, "Low": 3}
    eligible.sort(key=lambda row: (
        priority_order.get(row.priority, 2),
        str(row.required_date or row.trip_date or ""), str(row.name),
    ))
    return eligible


def mark_plan_manifest_prepared(manifest_name):
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    if not manifest.dispatch_plan:
        return
    plan = frappe.get_doc("CFG Kanban Dispatch Plan", manifest.dispatch_plan)
    if plan.state not in {"Vehicle Claimed", "Loading", "Ready to Dispatch"}:
        frappe.throw(f"Dispatch Plan cannot confirm loading while it is {plan.state}")
    if any(not row.loading_confirmed for row in manifest.lines):
        frappe.throw("Confirm every reserved tagged and untagged line before preparing dispatch")
    plan.db_set({
        "state": "Ready to Dispatch", "loading_confirmed_on": now_datetime(),
    }, update_modified=True)
    for line in plan.lines:
        frappe.db.set_value(
            "CFG Kanban Dispatch Plan Line", line.name,
            "line_state", "Loading Confirmed", update_modified=False,
        )


def mark_plan_dispatch_pending(manifest_name):
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    if not manifest.dispatch_plan:
        return
    plan = frappe.get_doc("CFG Kanban Dispatch Plan", manifest.dispatch_plan)
    if plan.state not in {"Ready to Dispatch", "Dispatch Pending", "Exception"}:
        frappe.throw(f"Dispatch Plan cannot post its Material Transfer while it is {plan.state}")
    plan.db_set({
        "state": "Dispatch Pending", "dispatch_started_on": now_datetime(),
    }, update_modified=True)


def mark_plan_loaded(manifest_name, stock_entry_name):
    """Close the E3 claim only after ERPNext submits the controlled Material Transfer."""
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    if not manifest.dispatch_plan:
        return
    plan = frappe.get_doc("CFG Kanban Dispatch Plan", manifest.dispatch_plan)
    loaded_total = 0
    by_line = {}
    allocations = frappe.get_all(
        "CFG Kanban Dispatch Allocation",
        filters={"dispatch_plan": plan.name, "movement_manifest": manifest.name},
        fields=[
            "name", "dispatch_plan_line", "allocated_qty", "state",
            "load_confirmed",
        ],
        limit_page_length=0,
    )
    if not allocations:
        frappe.throw("Dispatch Plan has no loading allocations for this Manifest")
    for allocation in allocations:
        if allocation.state not in ("Reserved", "Loaded"):
            frappe.throw(
                f"Dispatch allocation {allocation.name} is {allocation.state}; loading cannot close"
            )
        if not allocation.load_confirmed:
            frappe.throw(
                f"Dispatch allocation {allocation.name} was not physically confirmed as loaded"
            )
        loaded_total += flt(allocation.allocated_qty)
        by_line[allocation.dispatch_plan_line] = (
            by_line.get(allocation.dispatch_plan_line, 0) + flt(allocation.allocated_qty)
        )
        frappe.db.set_value(
            "CFG Kanban Dispatch Allocation", allocation.name,
            {"state": "Loaded", "active_handling_unit_key": None},
            update_modified=False,
        )
    for line in plan.lines:
        qty = by_line.get(line.name, 0)
        frappe.db.set_value(
            "CFG Kanban Dispatch Plan Line", line.name,
            {"reserved_qty": 0, "loaded_qty": qty, "line_state": "Loaded"},
            update_modified=False,
        )
    plan.db_set({
        "state": "Loaded", "total_reserved_qty": 0,
        "total_loaded_qty": loaded_total, "loaded_on": now_datetime(),
    }, update_modified=True)
    record(
        "Dispatch Plan Loaded", movement_manifest=manifest.name,
        reference_doctype="Stock Entry", reference_name=stock_entry_name,
        previous_state="Dispatch Pending", new_state="Loaded", qty=loaded_total,
        notes=f"Vehicle {plan.vehicle_reference}; Warehouse {plan.vehicle_warehouse}",
    )


def mark_plan_dispatch_exception(manifest_name, reason):
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    if not manifest.dispatch_plan:
        return
    plan = frappe.get_doc("CFG Kanban Dispatch Plan", manifest.dispatch_plan)
    previous = plan.state
    plan.db_set("state", "Exception", update_modified=True)
    record(
        "Dispatch Plan Exception", movement_manifest=manifest.name,
        reference_doctype=plan.doctype, reference_name=plan.name,
        previous_state=previous, new_state="Exception", notes=reason,
    )


def release_vehicle_claim(manifest, operator, session, reason, event_token=None):
    """Cancel an unposted E3 Manifest while preserving the approved E2 reservations."""
    plan = _locked_authorized_plan(manifest.dispatch_plan, operator)
    if plan.movement_manifest != manifest.name:
        frappe.throw("Dispatch Plan no longer identifies this Movement Manifest")
    if plan.state not in {"Vehicle Claimed", "Loading", "Ready to Dispatch"}:
        frappe.throw(f"Vehicle claim cannot be released while Plan is {plan.state}")
    if any((manifest.dispatch_stock_entry, manifest.dispatch_delivery_note,
            manifest.receipt_stock_entry, manifest.receipt_purchase_receipt)):
        frappe.throw("Vehicle claim has an ERP document and requires controlled recovery")
    for allocation in frappe.get_all(
            "CFG Kanban Dispatch Allocation",
            filters={"dispatch_plan": plan.name, "movement_manifest": manifest.name},
            pluck="name", limit_page_length=0):
        frappe.db.set_value(
            "CFG Kanban Dispatch Allocation", allocation,
            {"movement_manifest": None, "manifest_line": None, "load_confirmed": 0,
             "loaded_by_operator": None, "loaded_operator_session": None,
             "loaded_on": None, "load_key": None}, update_modified=False,
        )
    previous = plan.state
    plan.db_set({
        "state": "Ready for Vehicle", "vehicle_warehouse": None,
        "vehicle_reference": None, "movement_manifest": None, "claim_key": None,
        "claimed_by_operator": None, "claimed_operator_session": None,
        "claimed_on": None, "loading_confirmed_on": None,
        "dispatch_started_on": None, "total_loaded_qty": 0, "loaded_on": None,
    }, update_modified=True)
    for line in plan.lines:
        frappe.db.set_value(
            "CFG Kanban Dispatch Plan Line", line.name,
            "line_state", "Reserved", update_modified=False,
        )
    manifest.db_set({
        "state": "Cancelled", "cancelled_by": operator.employee,
        "cancelled_on": now_datetime(), "cancellation_reason": reason,
    }, update_modified=True)
    frappe.db.set_value(
        "CFG Kanban Manifest Line", {"parent": manifest.name},
        "state", "Cancelled", update_modified=False,
    )
    record(
        "Dispatch Vehicle Claim Released", movement_manifest=manifest.name,
        reference_doctype=plan.doctype, reference_name=plan.name,
        previous_state=previous, new_state="Ready for Vehicle",
        device_id=event_token, operator=operator.employee,
        operator_session=session.name, terminal_user=session.terminal_user,
        notes=reason,
    )


def validate_plan_manifest_for_prepare(manifest, operator):
    """Validate E3 physical loading without creating a second reservation."""
    plan = frappe.get_doc("CFG Kanban Dispatch Plan", manifest.dispatch_plan)
    _assert_plan_authorized(plan, operator)
    if plan.movement_manifest != manifest.name:
        frappe.throw("Dispatch Plan does not identify this Movement Manifest")
    if plan.state not in {"Vehicle Claimed", "Loading", "Ready to Dispatch"}:
        frappe.throw(f"Dispatch Plan cannot prepare loading while it is {plan.state}")
    if not manifest.lines:
        frappe.throw("Vehicle-loading Manifest has no reserved stock lines")
    for row in manifest.lines:
        allocation = frappe.get_doc(
            "CFG Kanban Dispatch Allocation", row.dispatch_allocation
        )
        if (allocation.dispatch_plan != plan.name
                or allocation.movement_manifest != manifest.name
                or allocation.manifest_line != row.name
                or allocation.state != "Reserved"):
            frappe.throw(f"Manifest line {row.name} is not backed by an active Plan reservation")
        if not row.loading_confirmed or not allocation.load_confirmed:
            frappe.throw(
                f"Confirm physical loading for {row.visible_code or row.item_code} first"
            )
        if abs(flt(row.dispatch_qty) - flt(allocation.allocated_qty)) > 0.000001:
            frappe.throw(f"Manifest line {row.name} quantity no longer matches its reservation")
        if row.line_kind == "Tagged Stock":
            unit = frappe.get_doc("CFG Kanban Handling Unit", row.handling_unit)
            if (unit.current_warehouse != plan.source_warehouse
                    or unit.inventory_company != plan.company
                    or abs(flt(unit.current_qty) - flt(row.dispatch_qty)) > 0.000001
                    or flt(unit.reserved_qty) + 0.000001 < flt(row.dispatch_qty)):
                frappe.throw(
                    f"Reserved Stock Tag {row.visible_code} changed after loading confirmation"
                )
            assert_erp_stock(unit, plan.source_warehouse, row.dispatch_qty)
        else:
            _assert_untagged_allocation_available(allocation)
    return plan


def _vehicle_warehouse_from_scan(scan_value, company):
    value = str(scan_value or "").strip()
    if not value:
        frappe.throw("Scan the Company-specific lorry Warehouse card")
    card_name = None
    for fieldname in ("qr_code", "uuid", "card_number", "name"):
        card_name = frappe.db.get_value("CFG Kanban Card", {fieldname: value}, "name")
        if card_name:
            break
    if not card_name:
        frappe.throw("Lorry Warehouse card was not found")
    card = frappe.db.get_value(
        "CFG Kanban Card", card_name,
        ["active", "blocked", "card_type", "location_purpose", "company",
         "current_warehouse"], as_dict=True,
    )
    if (not card or not card.active or card.blocked or card.card_type != "Location Card"
            or card.location_purpose != "Warehouse Operations" or not card.current_warehouse):
        frappe.throw(
            "Vehicle claim requires an active Warehouse Operations Location Card"
        )
    if card.company and card.company != company:
        frappe.throw(f"Lorry Warehouse card belongs to {card.company}, not {company}")
    return _vehicle_warehouse(card.current_warehouse, company)


def _vehicle_warehouse(warehouse, company=None):
    row = frappe.db.get_value(
        "Warehouse", warehouse,
        ["name", "company", "disabled", "is_group", "cfg_is_vehicle_warehouse",
         "cfg_vehicle_reference"], as_dict=True,
    )
    if (not row or row.disabled or row.is_group or not row.cfg_is_vehicle_warehouse
            or not row.cfg_vehicle_reference):
        frappe.throw("Scanned location is not an active Company-specific lorry Warehouse")
    if company and row.company != company:
        frappe.throw(f"Lorry Warehouse belongs to {row.company}, not {company}")
    return row


def _vehicle_loading_route(plan, vehicle_warehouse, operator=None):
    if not plan.logistics_route:
        frappe.throw(
            "Vehicle Delivery Dispatch Profile requires an Internal Warehouse Transfer route"
        )
    route = frappe.get_doc("CFG Kanban Logistics Route", plan.logistics_route)
    if (not route.active or route.route_type != "Internal Warehouse Transfer"
            or route.internal_transfer_mode != "Direct Transfer"):
        frappe.throw(
            "E3 vehicle loading requires an active Direct Internal Warehouse Transfer route"
        )
    if (route.source_company != plan.company or route.destination_company != plan.company
            or route.source_warehouse != plan.source_warehouse):
        frappe.throw("Vehicle-loading route does not match the Dispatch Plan source Company/Warehouse")
    if operator and not (_view_all(operator)
                         or route.dispatch_responsibility in _responsibilities(operator)):
        frappe.throw("Operator is not assigned to the vehicle-loading route responsibility",
                     frappe.PermissionError)
    if (plan.destination_assignment_policy == "Fixed"
            and plan.destination_warehouse != vehicle_warehouse):
        frappe.throw(
            f"Dispatch Plan is fixed to {plan.destination_warehouse}; scan that lorry Warehouse"
        )
    if plan.destination_assignment_policy == "Select at Receipt":
        frappe.throw("Select at Receipt belongs to the optional Goods-in-Transit package")
    return route


def _assert_e3_allocations_ready(plan):
    allocations = frappe.get_all(
        "CFG Kanban Dispatch Allocation",
        filters={"dispatch_plan": plan.name, "state": "Reserved"},
        fields=[
            "name", "allocation_kind", "handling_unit", "allocated_qty", "item_code",
            "batch_no", "stock_uom", "source_company", "source_warehouse",
        ],
        order_by="creation asc", limit_page_length=0,
    )
    if not allocations:
        frappe.throw("Dispatch Plan has no active stock reservations")
    if abs(sum(flt(row.allocated_qty) for row in allocations)
           - flt(plan.total_requested_qty)) > 0.000001:
        frappe.throw("Dispatch Plan must be fully reserved before vehicle claim")
    for allocation in allocations:
        if not cint(frappe.db.get_value("Item", allocation.item_code, "is_stock_item")):
            frappe.throw(
                f"Item {allocation.item_code} does not maintain ERPNext stock and cannot use "
                "the E3 Material Transfer workflow"
            )
        if allocation.source_company != plan.company or allocation.source_warehouse != plan.source_warehouse:
            frappe.throw(f"Allocation {allocation.name} no longer matches the Plan source")
        if allocation.allocation_kind == "Tagged Stock":
            unit = frappe.get_doc("CFG Kanban Handling Unit", allocation.handling_unit)
            if abs(flt(allocation.allocated_qty) - flt(unit.current_qty)) > 0.000001:
                frappe.throw(
                    f"Stock Tag {unit.handling_unit_id} is only partly reserved. A physical tag "
                    "cannot remain in two Warehouses; split/repack the exact Plan quantity first."
                )
            if flt(unit.reserved_qty) + 0.000001 < flt(allocation.allocated_qty):
                frappe.throw(f"Stock Tag {unit.handling_unit_id} reservation is no longer complete")
            assert_erp_stock(unit, plan.source_warehouse, allocation.allocated_qty)
        else:
            _assert_untagged_allocation_available(allocation)


def _create_vehicle_manifest(plan, route, operator, session, claim_key):
    preparation_key = canonical_key(
        "dispatch-plan-manifest", plan.name, claim_key
    )
    manifest = frappe.get_doc({
        "doctype": "CFG Kanban Movement Manifest",
        "dispatch_plan": plan.name,
        "logistics_route": route.name,
        "state": "Draft",
        "preparation_key": preparation_key,
        "created_by_operator": operator.employee,
        "created_operator_session": session.name,
    })
    allocations = frappe.get_all(
        "CFG Kanban Dispatch Allocation",
        filters={"dispatch_plan": plan.name, "state": "Reserved"},
        fields=[
            "name", "allocation_kind", "handling_unit", "visible_code", "item_code",
            "batch_no", "stock_uom", "allocated_qty", "source_company",
            "source_warehouse",
        ],
        order_by="creation asc", limit_page_length=0,
    )
    for allocation in allocations:
        manifest.append("lines", {
            "line_kind": (
                "Tagged Stock" if allocation.allocation_kind == "Tagged Stock"
                else "ERP Stock without Physical Tag"
            ),
            "dispatch_allocation": allocation.name,
            "handling_unit": allocation.handling_unit,
            "visible_code": allocation.visible_code,
            "tag_kind": (frappe.db.get_value(
                "CFG Kanban Handling Unit", allocation.handling_unit, "tag_kind"
            ) if allocation.handling_unit else None),
            "item_code": allocation.item_code,
            "batch_no": allocation.batch_no,
            "stock_uom": allocation.stock_uom,
            "available_qty_at_scan": allocation.allocated_qty,
            "dispatch_qty": allocation.allocated_qty,
            "received_qty": 0,
            "loading_confirmed": 0,
            "source_company": plan.company,
            "source_warehouse": plan.source_warehouse,
            "destination_company": plan.company,
            "destination_warehouse": plan.vehicle_warehouse,
            "state": "Prepared",
        })
    try:
        manifest.insert(ignore_permissions=True)
    except frappe.DuplicateEntryError:
        existing = frappe.db.get_value(
            "CFG Kanban Movement Manifest",
            {"preparation_key": preparation_key}, "name",
        )
        if existing:
            return frappe.get_doc("CFG Kanban Movement Manifest", existing)
        raise
    for line in manifest.lines:
        frappe.db.set_value(
            "CFG Kanban Dispatch Allocation", line.dispatch_allocation,
            {"movement_manifest": manifest.name, "manifest_line": line.name},
            update_modified=False,
        )
    return manifest


def _locked_plan_manifest(manifest_name, operator):
    frappe.db.sql(
        "select name from `tabCFG Kanban Movement Manifest` where name=%s for update",
        manifest_name,
    )
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    if not manifest.dispatch_plan:
        frappe.throw("Movement Manifest is not linked to a Dispatch Plan")
    plan = _locked_authorized_plan(manifest.dispatch_plan, operator)
    if plan.movement_manifest != manifest.name:
        frappe.throw("Dispatch Plan no longer identifies this Movement Manifest")
    return manifest, plan


def _confirm_allocation_loading(allocation_name, manifest_line, manifest, plan,
                                operator, session, key):
    frappe.db.set_value(
        "CFG Kanban Dispatch Allocation", allocation_name,
        {"load_confirmed": 1, "loaded_by_operator": operator.employee,
         "loaded_operator_session": session.name, "loaded_on": now_datetime(),
         "load_key": key}, update_modified=True,
    )
    frappe.db.set_value(
        "CFG Kanban Manifest Line", manifest_line,
        {"loading_confirmed": 1, "loading_confirmed_by": operator.employee,
         "loading_confirmed_on": now_datetime()}, update_modified=False,
    )
    remaining = frappe.db.count(
        "CFG Kanban Dispatch Allocation",
        {"dispatch_plan": plan.name, "state": "Reserved", "load_confirmed": 0},
    )
    plan.db_set("state", "Loading", update_modified=True)
    for line in plan.lines:
        line_allocations = frappe.get_all(
            "CFG Kanban Dispatch Allocation",
            filters={"dispatch_plan_line": line.name, "state": "Reserved"},
            fields=["load_confirmed"], limit_page_length=0,
        )
        state = (
            "Loading Confirmed" if line_allocations and all(row.load_confirmed for row in line_allocations)
            else "Loading"
        )
        frappe.db.set_value(
            "CFG Kanban Dispatch Plan Line", line.name, "line_state", state,
            update_modified=False,
        )
    if not remaining:
        record(
            "Dispatch Physical Loading Complete", movement_manifest=manifest.name,
            reference_doctype=plan.doctype, reference_name=plan.name,
            previous_state="Loading", new_state="Loading",
            operator=operator.employee, operator_session=session.name,
            terminal_user=session.terminal_user,
            notes="Every reserved line physically confirmed; awaiting Manifest preparation",
        )


def _assert_untagged_allocation_available(allocation):
    if allocation.batch_no:
        from erpnext.stock.doctype.batch.batch import get_batch_qty
        erp_balance = flt(get_batch_qty(
            batch_no=allocation.batch_no, warehouse=allocation.source_warehouse,
            item_code=allocation.item_code, posting_date=today(),
            for_stock_levels=True, ignore_reserved_stock=True,
        ))
        batch_condition = "and batch_no=%(batch)s"
    else:
        from erpnext.stock.utils import get_stock_balance
        erp_balance = flt(get_stock_balance(
            allocation.item_code, allocation.source_warehouse, posting_date=today()
        ))
        batch_condition = "and (batch_no is null or batch_no='')"
    params = {
        "company": allocation.source_company,
        "warehouse": allocation.source_warehouse,
        "item": allocation.item_code,
        "batch": allocation.batch_no,
    }
    tagged = flt(frappe.db.sql(
        f"""
        select coalesce(sum(current_qty), 0)
        from `tabCFG Kanban Handling Unit`
        where inventory_company=%(company)s and current_warehouse=%(warehouse)s
          and item_code=%(item)s and identity_state='Active' and current_qty>0
          {batch_condition}
        """, params,
    )[0][0])
    untagged_reserved = flt(frappe.db.sql(
        f"""
        select coalesce(sum(allocated_qty), 0)
        from `tabCFG Kanban Dispatch Allocation`
        where allocation_kind='Untagged ERP Stock' and state='Reserved'
          and source_company=%(company)s and source_warehouse=%(warehouse)s
          and item_code=%(item)s {batch_condition}
        """, params,
    )[0][0])
    if erp_balance + 0.000001 < tagged + untagged_reserved:
        frappe.throw(
            f"ERPNext stock for {allocation.item_code} is now {erp_balance}; active tagged "
            f"stock plus untagged Dispatch reservations require {tagged + untagged_reserved}"
        )


def _manifest_result(manifest_name, operator_session_token):
    from cfg_kanban.api.logistics import get_manifest
    return get_manifest(manifest_name, operator_session_token)


def _normalize_lines(lines, sales_order=None):
    values = frappe.parse_json(lines) if isinstance(lines, str) else (lines or [])
    if not isinstance(values, list) or not values:
        frappe.throw("Enter at least one Dispatch Plan Item")
    sales_order_items = {}
    if sales_order:
        sales_order_items = _sales_order_item_map(sales_order)
    rows = []
    seen = set()
    for idx, value in enumerate(values, start=1):
        item_code = (value.get("item_code") or "").strip()
        batch_no = (value.get("batch_no") or "").strip() or None
        qty = flt(value.get("requested_qty") or value.get("qty"))
        if not item_code or qty <= 0:
            frappe.throw(f"Row {idx}: Item and positive Requested Qty are required")
        item = frappe.db.get_value(
            "Item", item_code, ["item_name", "stock_uom", "disabled"], as_dict=True
        )
        if not item or item.disabled:
            frappe.throw(f"Row {idx}: Item {item_code} is missing or disabled")
        _validate_batch(item_code, batch_no)
        key = (item_code, batch_no or "")
        if key in seen:
            frappe.throw(f"Row {idx}: duplicate Item/Batch; combine it into one line")
        seen.add(key)
        order_item = sales_order_items.get(item_code)
        if sales_order and not order_item:
            frappe.throw(f"Row {idx}: Item {item_code} is not in Sales Order {sales_order}")
        if order_item and qty > flt(order_item["remaining_qty"]) + 0.000001:
            frappe.throw(
                f"Row {idx}: requested {qty} exceeds Sales Order remaining quantity "
                f"{order_item['remaining_qty']} for {item_code}"
            )
        rows.append({
            "item_code": item_code, "item_name": item.item_name,
            "batch_no": batch_no, "stock_uom": item.stock_uom,
            "requested_qty": qty, "reserved_qty": 0, "line_state": "Open",
            "sales_order_item": (order_item or {}).get("names", [None])[0],
        })
    return rows


def _business_context(policy, **values):
    customer_site = values.get("customer_site") or policy.customer_site
    route = values.get("logistics_route") or policy.logistics_route
    territory = values.get("territory") or policy.territory
    if policy.customer_site and customer_site != policy.customer_site:
        frappe.throw(f"This Dispatch Profile is restricted to Customer Site {policy.customer_site}")
    if policy.logistics_route and route != policy.logistics_route:
        frappe.throw(f"This Dispatch Profile is restricted to Route {policy.logistics_route}")
    if policy.territory and territory != policy.territory:
        frappe.throw(f"This Dispatch Profile is restricted to Territory {policy.territory}")
    result = {
        "customer_site": customer_site,
        "territory": territory,
        "logistics_route": route,
        "sales_order": values.get("sales_order"),
        "required_date": values.get("required_date"),
        "trip_date": values.get("trip_date"),
    }
    if policy.plan_type == "Customer Order":
        if not customer_site:
            frappe.throw("Customer Order Profile requires a Customer Site")
        if not values.get("required_date"):
            frappe.throw("Customer Order Dispatch Plan requires a Required Date")
        site = frappe.db.get_value(
            "CFG Kanban Customer Scan Point", customer_site,
            ["active", "selling_company", "customer", "customer_address", "territory"],
            as_dict=True,
        )
        if not site or not site.active or site.selling_company != policy.company:
            frappe.throw("Customer Site must be active and belong to the Profile Company")
        result.update({
            "customer": site.customer, "customer_address": site.customer_address,
            "territory": site.territory or territory,
        })
        if values.get("sales_order"):
            order = frappe.db.get_value(
                "Sales Order", values["sales_order"],
                ["docstatus", "company", "customer"], as_dict=True,
            )
            if (not order or order.docstatus != 1 or order.company != policy.company
                    or order.customer != site.customer):
                frappe.throw(
                    "Sales Order must be submitted for the same Company and Customer Site"
                )
    else:
        if not (route or territory):
            frappe.throw("Open Route Stock requires a Logistics Route or Territory")
        if not values.get("trip_date"):
            frappe.throw("Open Route Stock requires a Trip Date")
    if route:
        route_row = frappe.db.get_value(
            "CFG Kanban Logistics Route", route,
            ["active", "source_company", "source_warehouse"], as_dict=True,
        )
        if (not route_row or not route_row.active or route_row.source_company != policy.company
                or route_row.source_warehouse != policy.source_warehouse):
            frappe.throw("Logistics Route does not match the Dispatch Profile source")
    return result


def _sales_order_item_map(sales_order):
    order = frappe.get_doc("Sales Order", sales_order)
    mapping = {}
    for row in order.items:
        value = mapping.setdefault(row.item_code, {"names": [], "remaining_qty": 0})
        value["names"].append(row.name)
        value["remaining_qty"] += max(flt(row.qty) - flt(row.delivered_qty), 0)
    return mapping


def _authorized_profile(name, operator):
    policy = frappe.get_doc("CFG Kanban Dispatch Profile", name)
    if not policy.active:
        frappe.throw("Dispatch Profile is inactive")
    if not (_view_all(operator) or policy.dispatch_responsibility in _responsibilities(operator)):
        frappe.throw("Operator is not assigned to this Dispatch Profile responsibility",
                     frappe.PermissionError)
    card = frappe.db.get_value(
        "CFG Kanban Card", policy.dispatch_point,
        ["active", "blocked", "card_type", "location_purpose", "company",
         "current_warehouse"], as_dict=True,
    )
    if (not card or not card.active or card.blocked or card.card_type != "Location Card"
            or card.location_purpose != "Dispatch Operations"):
        frappe.throw("Dispatch Operations Card is inactive, blocked or no longer valid")
    if card.company != policy.company or card.current_warehouse != policy.source_warehouse:
        frappe.throw("Dispatch Profile no longer matches its Dispatch Operations Card")
    return policy


def _locked_authorized_plan(name, operator):
    frappe.db.sql(
        "select name from `tabCFG Kanban Dispatch Plan` where name=%s for update", name
    )
    plan = frappe.get_doc("CFG Kanban Dispatch Plan", name)
    _assert_plan_authorized(plan, operator)
    return plan


def _assert_plan_authorized(plan, operator):
    if not (_view_all(operator) or plan.dispatch_responsibility in _responsibilities(operator)):
        frappe.throw("Operator is not assigned to this Dispatch Plan responsibility",
                     frappe.PermissionError)


def _responsibilities(operator):
    return {row.responsibility for row in operator.responsibilities if row.responsibility}


def _view_all(operator):
    return bool(
        operator.get("view_all_responsibilities") and
        operator.kanban_role in ("Supervisor", "Development Proxy")
    )


def _assert_plan_lines(plan):
    if not plan.lines or any(flt(row.requested_qty) <= 0 for row in plan.lines):
        frappe.throw("Dispatch Plan requires positive Item quantities")


def _assert_reservable(plan, kind):
    if plan.state not in RESERVABLE_STATES:
        frappe.throw(f"Dispatch Plan must be Approved before reserving stock; state is {plan.state}")
    card = frappe.db.get_value(
        "CFG Kanban Card", plan.dispatch_point, ["active", "blocked"], as_dict=True
    )
    if not card or not card.active or card.blocked:
        frappe.throw("Dispatch Operations Card is inactive or blocked; stock cannot be reserved")
    allowed = {
        "Tagged": {"Tagged", "Mixed"},
        "Untagged": {"Untagged", "Mixed"},
    }[kind]
    if plan.tag_policy not in allowed:
        frappe.throw(f"Dispatch Profile policy {plan.tag_policy} does not permit {kind} stock")


def _plan_line(plan, line_name):
    line = next((row for row in plan.lines if row.name == line_name), None)
    if not line:
        frappe.throw("Selected Dispatch Plan line does not belong to this Plan")
    return line


def _validate_tag_for_plan(unit, plan, line):
    if unit.identity_state != "Active" or flt(unit.current_qty) <= 0:
        frappe.throw(f"Stock Tag {unit.handling_unit_id} is not active stock")
    if unit.quality_state != "Released":
        frappe.throw(f"Stock Tag {unit.handling_unit_id} quality state is {unit.quality_state}")
    if unit.inventory_company != plan.company:
        frappe.throw(f"Stock Tag belongs to {unit.inventory_company}, not {plan.company}")
    if unit.current_warehouse != plan.source_warehouse:
        frappe.throw(
            f"Stock Tag is in {unit.current_warehouse}, not {plan.source_warehouse}"
        )
    if unit.item_code != line.item_code or unit.stock_uom != line.stock_uom:
        frappe.throw(
            f"Stock Tag Item/UOM {unit.item_code} / {unit.stock_uom} does not match "
            f"Plan line {line.item_code} / {line.stock_uom}"
        )
    if line.batch_no and unit.batch_no != line.batch_no:
        frappe.throw(f"Stock Tag Batch {unit.batch_no or '-'} does not match {line.batch_no}")
    if flt(unit.reserved_qty) > 0:
        frappe.throw(f"Stock Tag {unit.handling_unit_id} is already reserved")
    conflict = frappe.db.get_value(
        "CFG Kanban Dispatch Allocation",
        {"active_handling_unit_key": unit.name, "state": "Reserved"},
        ["name", "dispatch_plan"], as_dict=True,
    )
    if conflict:
        frappe.throw(f"Stock Tag is already reserved in Dispatch Plan {conflict.dispatch_plan}")


def _assert_not_in_open_manifest(handling_unit):
    row = frappe.db.sql(
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
    if row:
        frappe.throw(f"Stock Tag is already assigned to open Manifest {row[0][0]}")


def _active_line_reserved(line_name):
    result = frappe.db.sql(
        """
        select coalesce(sum(allocated_qty), 0)
        from `tabCFG Kanban Dispatch Allocation`
        where dispatch_plan_line=%s and state='Reserved'
        """,
        line_name,
    )
    return flt(result[0][0] if result else 0)


def _refresh_plan_totals(plan_name):
    plan = frappe.get_doc("CFG Kanban Dispatch Plan", plan_name)
    total = 0
    complete = True
    for line in plan.lines:
        reserved = _active_line_reserved(line.name)
        total += reserved
        if reserved <= 0.000001:
            state = "Open"
        elif reserved + 0.000001 < flt(line.requested_qty):
            state = "Partially Reserved"
        else:
            state = "Reserved"
        if reserved + 0.000001 < flt(line.requested_qty):
            complete = False
        frappe.db.set_value(
            "CFG Kanban Dispatch Plan Line", line.name,
            {"reserved_qty": reserved, "line_state": state}, update_modified=False,
        )
    values = {"total_reserved_qty": total}
    if plan.state in RESERVABLE_STATES:
        new_state = "Ready for Vehicle" if complete else ("Picking" if total else "Approved")
        values["state"] = new_state
        if new_state == "Ready for Vehicle" and not plan.ready_on:
            values["ready_on"] = now_datetime()
        elif new_state != "Ready for Vehicle":
            values["ready_on"] = None
    plan.db_set(values, update_modified=True)


def _release_allocation(allocation, plan, operator, session, reason, event_token,
                        final_state="Released"):
    reason = (reason or "").strip()
    if not reason:
        frappe.throw("Release reason is required")
    if allocation.state != "Reserved":
        return
    release_key = canonical_key(
        "dispatch-plan-allocation-release", allocation.name, event_token or ""
    )
    ledger_name = None
    if allocation.handling_unit:
        ledger = post_quantity_event(
            event_type="Unreserve", qty=allocation.allocated_qty,
            stock_uom=allocation.stock_uom, idempotency_key=release_key,
            source_handling_unit=allocation.handling_unit,
            item_code=allocation.item_code, batch_no=allocation.batch_no,
            source_company=allocation.source_company,
            source_warehouse=allocation.source_warehouse,
            reference_doctype=allocation.doctype, reference_name=allocation.name,
            operator=operator.employee, operator_session=session.name,
            device_id=event_token, reason=reason,
        )
        ledger_name = ledger.name
        remaining = flt(frappe.db.get_value(
            "CFG Kanban Handling Unit", allocation.handling_unit, "reserved_qty"
        ))
        if remaining <= 0.000001:
            frappe.db.set_value(
                "CFG Kanban Handling Unit", allocation.handling_unit,
                "movement_state", allocation.movement_state_before_reservation or "At Source",
                update_modified=False,
            )
    allocation.db_set({
        "state": final_state, "active_handling_unit_key": None,
        "released_by_operator": operator.employee,
        "released_operator_session": session.name, "released_on": now_datetime(),
        "release_reason": reason, "release_ledger": ledger_name,
        "release_key": release_key,
    }, update_modified=True)
    record(
        "Dispatch Stock Reservation Released", handling_unit=allocation.handling_unit,
        qty=allocation.allocated_qty, reference_doctype=allocation.doctype,
        reference_name=allocation.name, device_id=event_token,
        operator=operator.employee, operator_session=session.name,
        terminal_user=session.terminal_user,
        notes=f"Dispatch Plan {plan.name}; {reason}",
    )


def _validate_batch(item_code, batch_no):
    if batch_no and frappe.db.get_value("Batch", batch_no, "item") != item_code:
        frappe.throw(f"Batch {batch_no} does not belong to Item {item_code}")


def _suggested_tags(plan, line):
    order_by = "unit.handling_unit_id asc"
    if plan.stock_rotation_policy == "FIFO":
        order_by = "coalesce(unit.packed_on, unit.creation) asc, unit.handling_unit_id asc"
    elif plan.stock_rotation_policy == "FEFO":
        order_by = (
            "case when unit.expiry_date is null then 1 else 0 end asc, unit.expiry_date asc, "
            "coalesce(unit.packed_on, unit.creation) asc, unit.handling_unit_id asc"
        )
    batch_condition = "and unit.batch_no=%(batch)s" if line.batch_no else ""
    return frappe.db.sql(
        f"""
        select unit.name, unit.handling_unit_id, unit.batch_no, unit.current_qty,
               unit.available_qty, unit.stock_uom, unit.packed_on, unit.expiry_date
        from `tabCFG Kanban Handling Unit` unit
        where unit.identity_state='Active' and unit.quality_state='Released'
          and unit.inventory_company=%(company)s and unit.current_warehouse=%(warehouse)s
          and unit.item_code=%(item)s and unit.stock_uom=%(uom)s
          and unit.current_qty>0 and unit.reserved_qty<=0
          {batch_condition}
          and not exists (
              select 1 from `tabCFG Kanban Manifest Line` line
              inner join `tabCFG Kanban Movement Manifest` manifest on manifest.name=line.parent
              where line.handling_unit=unit.name
                and manifest.state not in ('Received','Billing Pending','Partially Billed','Billed',
                                           'Closed','Cancelled')
          )
        order by {order_by}
        limit 5
        """,
        {"company": plan.company, "warehouse": plan.source_warehouse,
         "item": line.item_code, "uom": line.stock_uom, "batch": line.batch_no},
        as_dict=True,
    )


def _lock_erp_bin(item_code, warehouse):
    frappe.db.sql(
        "select name from `tabBin` where item_code=%s and warehouse=%s for update",
        (item_code, warehouse),
    )


def _untagged_available(company, warehouse, item_code, batch_no):
    validate_warehouse_company(warehouse, company, "Dispatch source Warehouse")
    if batch_no:
        from erpnext.stock.doctype.batch.batch import get_batch_qty

        erp_balance = flt(get_batch_qty(
            batch_no=batch_no, warehouse=warehouse, item_code=item_code,
            posting_date=today(), for_stock_levels=True, ignore_reserved_stock=True,
        ))
    else:
        from erpnext.stock.utils import get_stock_balance

        erp_balance = flt(get_stock_balance(item_code, warehouse, posting_date=today()))
    conditions = "and batch_no=%(batch)s" if batch_no else "and (batch_no is null or batch_no='')"
    tagged = frappe.db.sql(
        f"""
        select coalesce(sum(current_qty), 0)
        from `tabCFG Kanban Handling Unit`
        where inventory_company=%(company)s and current_warehouse=%(warehouse)s
          and item_code=%(item)s and identity_state='Active' and current_qty>0
          {conditions}
        """,
        {"company": company, "warehouse": warehouse, "item": item_code, "batch": batch_no},
    )[0][0]
    untagged_reserved = frappe.db.sql(
        f"""
        select coalesce(sum(allocated_qty), 0)
        from `tabCFG Kanban Dispatch Allocation`
        where allocation_kind='Untagged ERP Stock' and state='Reserved'
          and source_company=%(company)s and source_warehouse=%(warehouse)s
          and item_code=%(item)s {conditions}
        """,
        {"company": company, "warehouse": warehouse, "item": item_code, "batch": batch_no},
    )[0][0]
    return max(erp_balance - flt(tagged) - flt(untagged_reserved), 0)


def _require_event_token(event_token):
    if not str(event_token or "").strip():
        frappe.throw("Event Token is required for an auditable Dispatch Plan action")
