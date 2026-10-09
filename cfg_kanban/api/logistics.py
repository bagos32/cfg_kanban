import frappe
from frappe.utils import cint, flt, now_datetime

from cfg_kanban.integrations.erp_gateway import (
    build_internal_transfer_stock_entry,
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
from cfg_kanban.services.retagging_auth import can_stock_retag


TERMINAL_STATES = {"Received", "Billing Pending", "Partially Billed", "Billed", "Closed", "Cancelled"}
MANIFEST_LIST_FIELDS = [
    "name", "manifest_type", "internal_transfer_mode", "inventory_control_mode",
    "logistics_route", "state",
    "kanban_cycle", "source_signal", "source_company", "source_warehouse",
    "destination_company", "destination_warehouse", "total_quantity",
    "total_received_quantity", "dispatch_delivery_note", "receipt_purchase_receipt",
    "dispatch_stock_entry", "receipt_stock_entry",
    "modified",
]
INTERNAL_TRANSFER_RESPONSIBILITY = "Internal Warehouse Transfer"
SUPPLIER_RECEIVING_RESPONSIBILITY = "Supplier Receiving"
STOCK_WITHDRAWAL_RESPONSIBILITY = "Stock Withdrawal"


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
                "route_type", "internal_transfer_mode",
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
    from cfg_kanban.services.route_reconciliation import get_reconciliation_console
    reconciliation = get_reconciliation_console(operator_session_token)
    return {"operator": _operator_summary(profile, session), "routes": routes,
            "manifests": manifests, "recent_manifests": recent_manifests,
            "internal_transfers": _internal_transfer_summaries(profile),
            "delivery_sessions": delivery_session_summaries(profile),
            "return_cases": return_case_summaries(profile),
            "vehicle_warehouses": reconciliation["vehicle_warehouses"],
            "open_reconciliations": reconciliation["open_reconciliations"],
            "recent_reconciliations": reconciliation["recent_reconciliations"],
            "can_reconcile": reconciliation["can_reconcile"]}


@frappe.whitelist()
def get_supplier_receiving_context(scan_value, operator_session_token):
    """Resolve either a warehouse receiving point or its exact Purchase Kanban card."""
    profile, _session = require_operator(operator_session_token)
    _require_supplier_receiving(profile)
    card_name = (frappe.db.get_value("CFG Kanban Card", {"qr_code": scan_value}, "name")
                 or frappe.db.get_value("CFG Kanban Card", {"card_number": scan_value}, "name"))
    if not card_name:
        frappe.throw("Scan a Supplier Receiving Location Card or Purchase Kanban card")
    card = frappe.get_doc("CFG Kanban Card", card_name)
    if card.card_type == "Location Card":
        if card.get("location_purpose") != "Supplier Receiving" or not card.current_warehouse:
            frappe.throw("This Location Card is not configured as a Supplier Receiving point")
        return {
            "mode": "warehouse", "location_card": card.name,
            "warehouse": card.current_warehouse,
            "company": frappe.db.get_value("Warehouse", card.current_warehouse, "company"),
            "pending_orders": _pending_supplier_receipts(card.current_warehouse),
        }
    if not card.kanban_master:
        frappe.throw("This card is not linked to a Purchase Replenishment Master")
    master = frappe.get_doc("CFG Kanban Master", card.kanban_master)
    if master.control_type != "Purchase Replenishment":
        frappe.throw("Only Purchase Replenishment cards can open supplier receiving")
    if not card.active_cycle:
        frappe.throw("This Purchase Kanban card has no active receiving Cycle")
    rows = _pending_supplier_receipts(master.destination_warehouse, card.active_cycle)
    if not rows:
        frappe.throw("This card has no submitted Purchase Order quantity awaiting receipt")
    return {
        "mode": "purchase_card", "purchase_card": card.name,
        "warehouse": master.destination_warehouse, "company": master.company,
        "pending_orders": rows, "selected_order": rows[0],
    }


@frappe.whitelist()
def receive_supplier_purchase(cycle_name, delivered_qty, accepted_qty, rejected_qty=0,
                              supplier_delivery_note=None, event_token=None,
                              operator_session_token=None, cardless_override=0,
                              override_reason=None):
    profile, session = require_operator(operator_session_token, "start")
    _require_supplier_receiving(profile)
    if cint(cardless_override):
        if not cint(profile.get("can_override")):
            frappe.throw("Supervisor Override permission is required for cardless receiving")
        if not (override_reason or "").strip():
            frappe.throw("Cardless receiving requires an override reason")
    from cfg_kanban.services.purchase_replenishment import create_purchase_receipt_command
    context = _supplier_receipt_row(cycle_name)
    result = create_purchase_receipt_command(
        cycle_name, delivered_qty, accepted_qty, rejected_qty,
        warehouse=context["warehouse"], rejected_warehouse=context.get("rejected_warehouse"),
        supplier_delivery_note=supplier_delivery_note, event_token=event_token,
    )
    result["rejected_qty"] = flt(rejected_qty)
    if result.get("docstatus") == 1 and flt(rejected_qty) > 0:
        result["receipt_dispositions"] = frappe.get_all(
            "CFG Kanban Receipt Disposition",
            filters={"kanban_cycle": cycle_name, "purchase_receipt": result["purchase_receipt"]},
            pluck="name",
        )
    record("Supplier Receipt Confirmed at Logistics Panel", card=context.get("kanban_card"),
           cycle=cycle_name, qty=accepted_qty, reference_doctype="Purchase Receipt",
           reference_name=result["purchase_receipt"], operator=profile.employee,
           operator_session=session.name, terminal_user=session.terminal_user,
           notes=(f"Supplier Delivery Note: {supplier_delivery_note or '-'}; "
                  f"Cardless override: {override_reason or 'No'}"))
    result["receiving_context"] = context
    return result


def _pending_supplier_receipts(warehouse, cycle_name=None):
    filters = {
        "destination_warehouse": warehouse,
        "purchase_status": ["in", ("Ordered", "Partially Received", "Receipt Exception")],
        "blocked": 0,
    }
    if cycle_name:
        filters["name"] = cycle_name
    cycles = frappe.get_all(
        "CFG Kanban Cycle", filters=filters,
        fields=["name", "kanban_card", "kanban_master", "item_code", "priority",
                "purchase_order", "purchase_order_item", "purchase_status"],
        order_by="creation asc", limit_page_length=200,
    )
    rows = []
    for cycle in cycles:
        try:
            row = _supplier_receipt_row(cycle.name)
        except Exception:
            continue
        if row["outstanding_qty"] > 0:
            rows.append(row)
    return rows


def _supplier_receipt_row(cycle_name):
    from cfg_kanban.services.purchase_replenishment import receipt_context
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    context = receipt_context(cycle.name)
    po = frappe.get_doc("Purchase Order", context["purchase_order"])
    if po.docstatus != 1 or po.status in ("Closed", "Cancelled"):
        frappe.throw("Supplier receiving requires a submitted, open Purchase Order")
    card_number = (frappe.db.get_value("CFG Kanban Card", cycle.kanban_card, "card_number")
                   if cycle.kanban_card else None)
    return {
        **context,
        "kanban_card": cycle.kanban_card,
        "card_number": card_number,
        "priority": cycle.priority,
        "purchase_status": cycle.purchase_status,
        "schedule_date": po.schedule_date,
    }


def _require_supplier_receiving(profile):
    if _can_view_all(profile) or SUPPLIER_RECEIVING_RESPONSIBILITY in _responsibilities(profile):
        return
    frappe.throw("Supplier Receiving responsibility is required", frappe.PermissionError)


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
    internal = manifest.manifest_type == "Internal Warehouse Transfer"
    non_stock_operational = _is_non_stock_operational_manifest(manifest)
    result["non_stock_operational_tracking"] = non_stock_operational
    result["dispatch_document_type"] = (
        "Kanban Movement" if non_stock_operational
        else "Stock Entry" if internal else "Delivery Note"
    )
    result["receipt_document_type"] = (
        None if non_stock_operational
        else "Stock Entry" if internal and manifest.internal_transfer_mode == "Goods in Transit"
        else "Purchase Receipt" if not internal else None
    )
    result["dispatch_document_status"] = (None if non_stock_operational else _document_status(
        result["dispatch_document_type"],
        manifest.dispatch_stock_entry if internal else manifest.dispatch_delivery_note,
    ))
    result["receipt_document_status"] = _document_status(
        result["receipt_document_type"],
        manifest.receipt_stock_entry if internal else manifest.receipt_purchase_receipt,
    ) if result["receipt_document_type"] else None
    result["transfer_tag_policy"] = _transfer_tag_policy(manifest)
    result["can_scan_dispatch_tags"] = bool(
        not manifest.kanban_cycle or result["transfer_tag_policy"] != "No Physical Tag"
    )
    result["dispatch_retry_available"] = _dispatch_retry_available(manifest)
    result["receipt_retry_available"] = _receipt_retry_available(manifest)
    result["can_use_untagged_stock"] = _can_use_untagged_stock(manifest)
    result["can_dispatch"] = (
        (manifest.state in ("Draft", "Prepared") or result["dispatch_retry_available"]) and
        (_can_view_all(profile) or route.dispatch_responsibility in responsibilities)
    )
    result["can_receive"] = (
        (not internal or manifest.internal_transfer_mode == "Goods in Transit") and
        (manifest.state in ("Dispatched", "Awaiting Receipt", "Receipt Document Pending")
         or result["receipt_retry_available"]) and
        (_can_view_all(profile) or route.receipt_responsibility in responsibilities)
    )
    result["operator"] = _operator_summary(profile, session)
    return result


@frappe.whitelist()
def use_untagged_transfer_stock(manifest_name, event_token, operator_session_token):
    """Choose ordinary ERP warehouse stock for an optional-tag Transfer Card."""
    profile, session = require_operator(operator_session_token, "start")
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    route = frappe.get_doc("CFG Kanban Logistics Route", manifest.logistics_route)
    _require_route_responsibility(profile, route.dispatch_responsibility, "dispatch")
    if manifest.manifest_type != "Internal Warehouse Transfer" or not manifest.kanban_cycle:
        frappe.throw("Untagged ERP stock selection is available only for a Transfer Kanban Manifest")
    if manifest.state != "Draft" or manifest.lines:
        frappe.throw("Choose tagged or untagged stock before adding any Manifest lines")
    if not _can_use_untagged_stock(manifest):
        frappe.throw("This Item policy requires physical Stock Tags for warehouse transfer")
    cycle = frappe.get_doc("CFG Kanban Cycle", manifest.kanban_cycle)
    key = canonical_key("manifest-untagged-stock", manifest.name, event_token or "")
    if frappe.db.get_value("CFG Kanban Event", {"device_id": key}, "name"):
        return get_manifest(manifest.name, operator_session_token)
    manifest.append("lines", {
        "line_kind": "ERP Stock without Physical Tag", "visible_code": "ERP STOCK",
        "item_code": cycle.item_code, "stock_uom": cycle.stock_uom,
        "available_qty_at_scan": cycle.planned_qty, "dispatch_qty": cycle.planned_qty,
        "received_qty": 0, "source_company": manifest.source_company,
        "source_warehouse": manifest.source_warehouse,
        "destination_company": manifest.destination_company,
        "destination_warehouse": manifest.destination_warehouse, "state": "Prepared",
    })
    manifest.save(ignore_permissions=True)
    record("Untagged ERP Stock Selected", movement_manifest=manifest.name,
           cycle=cycle.name, qty=cycle.planned_qty, device_id=key,
           reference_doctype=manifest.doctype, reference_name=manifest.name,
           operator=profile.employee, operator_session=session.name,
           terminal_user=session.terminal_user)
    return get_manifest(manifest.name, operator_session_token)


@frappe.whitelist()
def lookup_logistics_tag(scan_value, operator_session_token):
    """Read-only tag lookup. This endpoint never changes a Manifest or balance."""
    profile, _session = require_operator(operator_session_token)
    card_name = (frappe.db.get_value("CFG Kanban Card", {"qr_code": scan_value}, "name")
                 or frappe.db.get_value("CFG Kanban Card", {"card_number": scan_value}, "name"))
    if card_name:
        card = frappe.get_doc("CFG Kanban Card", card_name)
        master = (frappe.get_doc("CFG Kanban Master", card.kanban_master)
                  if card.kanban_master else None)
        result = {"identity": {"identity_type": "Kanban Card", "name": card_name}}
        if master and master.control_type == "Transfer":
            route = frappe.get_doc("CFG Kanban Logistics Route", master.logistics_route)
            responsibilities = _responsibilities(profile)
            manifest_name = None
            if card.active_cycle:
                manifest_name = frappe.db.get_value(
                    "CFG Kanban Movement Manifest", {"kanban_cycle": card.active_cycle}, "name"
                )
            result["transfer_manifest"] = (
                get_manifest(manifest_name, operator_session_token) if manifest_name else None
            )
            result["transfer_card"] = {
                "card": card.name, "card_number": card.card_number,
                "item_code": master.item_code, "source_warehouse": master.source_warehouse,
                "destination_warehouse": master.destination_warehouse,
                "active_cycle": card.active_cycle,
                "can_trigger": bool(
                    not card.active_cycle and card.active and not card.blocked
                    and (_can_view_all(profile)
                         or route.dispatch_responsibility in responsibilities)
                ),
            }
            return result
        if master and master.control_type == "Withdrawal":
            responsibilities = _responsibilities(profile)
            allowed = bool(
                _can_view_all(profile)
                or STOCK_WITHDRAWAL_RESPONSIBILITY in responsibilities
            )
            if not allowed:
                frappe.throw("Operator is not assigned to Stock Withdrawal", frappe.PermissionError)
            result["withdrawal_card"] = {
                "card": card.name, "card_number": card.card_number,
                "item_code": master.item_code, "source_warehouse": master.source_warehouse,
                "quantity": card.kanban_qty or master.replenishment_qty,
                "stock_uom": master.stock_uom, "active_cycle": card.active_cycle,
                "can_trigger": bool(
                    not card.active_cycle and card.active and not card.blocked
                    and profile.can_start
                ),
            }
            if card.active_cycle:
                from cfg_kanban.services.withdrawal import get_withdrawal
                result["withdrawal"] = get_withdrawal(
                    card.active_cycle, operator_session_token
                )
            return result
        result["supplier_receiving"] = get_supplier_receiving_context(
            scan_value, operator_session_token
        )
        return result
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
    result["can_retag"] = bool(can_stock_retag(profile) and profile.can_start)
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
def trigger_transfer_card(card_name, event_token, operator_session_token):
    """Start a Transfer Card from the Logistics panel without ERP Desk access."""
    profile, session = require_operator(operator_session_token, "start")
    card = frappe.get_doc("CFG Kanban Card", card_name)
    if not card.kanban_master:
        frappe.throw("Transfer Card is not linked to a Kanban Master")
    master = frappe.get_doc("CFG Kanban Master", card.kanban_master)
    if master.control_type != "Transfer":
        frappe.throw("Only Transfer Kanban cards can be triggered from this logistics action")
    route = frappe.get_doc("CFG Kanban Logistics Route", master.logistics_route)
    _require_route_responsibility(profile, route.dispatch_responsibility, "dispatch")
    from cfg_kanban.services.triggers import consume_card
    result = consume_card(
        card.name, device_id=f"logistics:{session.name}", event_token=event_token,
        trusted_operator=True,
    )
    signal = frappe.get_doc("CFG Kanban Signal", result["signal"])
    manifest_name = frappe.db.get_value(
        "CFG Kanban Movement Manifest", {"kanban_cycle": result["cycle"]}, "name"
    )
    return {
        "card": card.name, "cycle": result["cycle"], "signal": signal.name,
        "signal_status": signal.status, "manifest": manifest_name,
        "waiting_approval": not bool(manifest_name),
    }


@frappe.whitelist()
def trigger_withdrawal_card(card_name, event_token, operator_session_token):
    """Start a controlled consumable withdrawal from the Logistics panel."""
    profile, session = require_operator(operator_session_token, "start")
    responsibilities = _responsibilities(profile)
    if (not _can_view_all(profile)
            and STOCK_WITHDRAWAL_RESPONSIBILITY not in responsibilities):
        frappe.throw("Operator is not assigned to Stock Withdrawal", frappe.PermissionError)
    card = frappe.get_doc("CFG Kanban Card", card_name)
    if not card.kanban_master:
        frappe.throw("Withdrawal Card is not linked to a Kanban Master")
    master = frappe.get_doc("CFG Kanban Master", card.kanban_master)
    if master.control_type != "Withdrawal":
        frappe.throw("Only Withdrawal Kanban cards can use this action")
    from cfg_kanban.services.triggers import consume_card
    result = consume_card(
        card.name, device_id=f"logistics:{session.name}", event_token=event_token,
        trusted_operator=True,
    )
    signal = frappe.get_doc("CFG Kanban Signal", result["signal"])
    return {
        "card": card.name, "cycle": result["cycle"], "signal": signal.name,
        "signal_status": signal.status,
        "released": bool(frappe.db.get_value(
            "CFG Kanban Cycle", result["cycle"], "withdrawal_status"
        )),
        "waiting_approval": signal.status == "Waiting Approval",
    }


@frappe.whitelist()
def scan_dispatch_tag(manifest_name, scan_value, event_token, operator_session_token):
    profile, session = require_operator(operator_session_token, "start")
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    route = frappe.get_doc("CFG Kanban Logistics Route", manifest.logistics_route)
    _require_route_responsibility(profile, route.dispatch_responsibility, "dispatch")
    if manifest.state != "Draft":
        frappe.throw("Dispatch tags can only be added while the Manifest is Draft")
    if manifest.kanban_cycle and _transfer_tag_policy(manifest) == "No Physical Tag":
        frappe.throw(
            "This Transfer Card uses ERP stock without physical tags. Its Card quantity is "
            "already represented by the ERP STOCK Manifest line. To scan Stock Tags, change "
            "Warehouse Transfer Tags on the Item/Company Material Trace Policy to Optional "
            "Physical Tag or Required Physical Tag, then cancel this unused Cycle and trigger "
            "a new one."
        )
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
    if manifest.kanban_cycle:
        cycle = frappe.get_doc("CFG Kanban Cycle", manifest.kanban_cycle)
        selected = sum(flt(row.dispatch_qty) for row in manifest.lines)
        remaining = max(flt(cycle.planned_qty) - selected, 0)
        if flt(unit.available_qty) > remaining + 0.000001:
            frappe.throw(
                f"Tag {unit.handling_unit_id} contains {unit.available_qty} {unit.stock_uom}, "
                f"but Transfer Card {cycle.kanban_card} has only {remaining} "
                f"{cycle.stock_uom} remaining. A physical Stock Tag must move in full because "
                "one tag cannot remain in two Warehouses. Split the exact required quantity "
                "to another active tag first, or use a Transfer Card whose quantity matches "
                "the full tag."
            )
    if not event_token:
        frappe.throw("A stable scan event token is required")
    event_key = canonical_key("manifest-dispatch-scan", manifest.name, unit.name, event_token)
    if frappe.db.get_value("CFG Kanban Event", {"device_id": event_key}, "name"):
        return get_manifest(manifest.name, operator_session_token)
    manifest.append("lines", {
        "line_kind": "Tagged Stock",
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
    _validate_transfer_manifest_quantity(manifest)
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
            "line_kind": "Tagged Stock",
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
    _validate_transfer_manifest_quantity(manifest)
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
def remove_dispatch_tag(manifest_name, operator_session_token, handling_unit=None, line_name=None):
    """Remove one Draft selection, including ordinary ERP stock without a physical tag."""
    profile, session = require_operator(operator_session_token, "start")
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    route = frappe.get_doc("CFG Kanban Logistics Route", manifest.logistics_route)
    _require_route_responsibility(profile, route.dispatch_responsibility, "dispatch")
    if manifest.state != "Draft":
        frappe.throw(
            "Manifest selections can only be removed while the Manifest is Draft. "
            "An override-authorized supervisor must cancel a Prepared Manifest to release it."
        )
    row = next((row for row in manifest.lines if (
        (line_name and row.name == line_name)
        or (handling_unit and row.handling_unit == handling_unit)
    )), None)
    if not row:
        return get_manifest(manifest.name, operator_session_token)
    removed_kind = row.line_kind
    removed_code = row.visible_code or row.handling_unit or "ERP STOCK"
    removed_qty = row.dispatch_qty
    if row.container_handling_unit:
        for grouped_row in list(manifest.lines):
            if grouped_row.container_handling_unit == row.container_handling_unit:
                manifest.remove(grouped_row)
    else:
        manifest.remove(row)
    manifest.save(ignore_permissions=True)
    record("Manifest Dispatch Selection Removed", movement_manifest=manifest.name,
           handling_unit=handling_unit or None, qty=removed_qty,
           reference_doctype=manifest.doctype,
           reference_name=manifest.name, operator=profile.employee,
           operator_session=session.name, terminal_user=session.terminal_user,
           notes=f"{removed_kind}: {removed_code}")
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
    _validate_transfer_manifest_quantity(manifest, require_exact=True)
    _validate_manifest_container_groups(manifest)
    for row in manifest.lines:
        if row.line_kind == "ERP Stock without Physical Tag":
            _assert_untagged_erp_stock(row.item_code, manifest.source_warehouse,
                                       row.dispatch_qty)
            continue
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
            reason="Reserved for controlled Movement Manifest",
        )
    manifest.db_set({"state": "Prepared", "prepared_on": now_datetime()},
                    update_modified=True)
    if manifest.kanban_cycle:
        from cfg_kanban.services.state_machine import set_cycle_state
        cycle = frappe.get_doc("CFG Kanban Cycle", manifest.kanban_cycle)
        cycle.db_set("transfer_status", "Prepared", update_modified=False)
        set_cycle_state(cycle, "Transfer Prepared", event_type="Internal Transfer Prepared",
                        reference_doctype=manifest.doctype, reference_name=manifest.name)
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
    if _is_non_stock_operational_manifest(manifest):
        return {"doctype": None, "fields": [], "non_stock_operational_tracking": True}
    if manifest.manifest_type == "Internal Warehouse Transfer":
        payload = _internal_transfer_payload(manifest, _dispatch_stage(manifest))
        entry = build_internal_transfer_stock_entry(manifest, payload)
        return {"doctype": "Stock Entry", "fields": get_required_erp_inputs(entry)}
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
    if (_is_non_stock_operational_manifest(manifest)
            and manifest.state in ("Awaiting Receipt", "Received")):
        return get_manifest(manifest.name, operator_session_token)
    if (
        manifest.state not in ("Prepared", "Dispatch Document Pending")
        and not _dispatch_retry_available(manifest)
    ):
        frappe.throw(f"Manifest cannot dispatch while it is {manifest.state}")
    internal = manifest.manifest_type == "Internal Warehouse Transfer"
    if _is_non_stock_operational_manifest(manifest):
        return _confirm_non_stock_dispatch(
            manifest, profile, session, event_token, operator_session_token
        )
    key = canonical_key("manifest-dispatch", manifest.name)
    payload = (_internal_transfer_payload(manifest, _dispatch_stage(manifest),
                                          required_erp_inputs)
               if internal else _dispatch_payload(manifest, required_erp_inputs))
    command, _created = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command",
        "command_type": ("Create Internal Transfer Dispatch" if internal
                         else "Create Intercompany Delivery Note"),
        "movement_manifest": manifest.name,
        "status": "Pending",
        "target_doctype": "Stock Entry" if internal else "Delivery Note",
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
    _set_transfer_status(manifest, "Dispatch Document Pending")
    try:
        dispatch_document = execute_command(command.name)
    except Exception:
        _manifest_exception(manifest, "Dispatch ERP Command Failed",
                            f"{'Stock Entry' if internal else 'Delivery Note'} creation or submission failed",
                            command.name)
        raise
    manifest.reload()
    _resolve_manifest_exception(
        manifest, f"{'Stock Entry' if internal else 'Delivery Note'} creation retried successfully"
    )
    if dispatch_document.docstatus == 0:
        field = "dispatch_stock_entry" if internal else "dispatch_delivery_note"
        manifest.db_set({field: dispatch_document.name, "state": "Dispatch Document Pending"},
                        update_modified=True)
    return get_manifest(manifest.name, operator_session_token)


@frappe.whitelist()
def scan_receipt_tag(manifest_name, scan_value, event_token, operator_session_token):
    profile, session = require_operator(operator_session_token, "start")
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    route = frappe.get_doc("CFG Kanban Logistics Route", manifest.logistics_route)
    _require_route_responsibility(profile, route.receipt_responsibility, "receipt")
    if manifest.state not in ("Dispatched", "Awaiting Receipt", "Receipt Document Pending"):
        frappe.throw("Receipt scanning requires confirmed dispatch")
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
    internal = manifest.manifest_type == "Internal Warehouse Transfer"
    expected_warehouse = manifest.transit_warehouse if internal else None
    expected_state = "Internal Transit" if internal else "Intercompany Transit"
    if (
        container.inventory_company != manifest.source_company
        or container.current_warehouse != expected_warehouse
        or container.movement_state != expected_state
    ):
        frappe.throw(
            f"Reusable Container {container.handling_unit_id} is not in the expected "
            "transit state"
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
    if _is_non_stock_operational_manifest(manifest) and manifest.state == "Received":
        return get_manifest(manifest.name, operator_session_token)
    if (manifest.state not in ("Dispatched", "Awaiting Receipt", "Receipt Document Pending")
            and not _receipt_retry_available(manifest)):
        frappe.throw(f"Manifest cannot be received while it is {manifest.state}")
    if not manifest.lines or any(
        row.line_kind != "ERP Stock without Physical Tag" and not row.receipt_scanned
        for row in manifest.lines
    ):
        frappe.throw("Receiving operator must scan every Manifest tag before confirmation")
    internal = manifest.manifest_type == "Internal Warehouse Transfer"
    if _is_non_stock_operational_manifest(manifest):
        return _confirm_non_stock_receipt(
            manifest, profile, session, event_token, operator_session_token
        )
    if internal and manifest.internal_transfer_mode != "Goods in Transit":
        frappe.throw("Direct internal transfers complete when the dispatch Stock Entry is submitted")
    if internal:
        dispatch_status = _document_status("Stock Entry", manifest.dispatch_stock_entry)
        if not dispatch_status or dispatch_status["docstatus"] != 1:
            frappe.throw("Outward Stock Entry must be submitted before transit receipt can be posted")
        key = canonical_key("manifest-receipt", manifest.name)
        payload = _internal_transfer_payload(manifest, "Receipt")
        command, _created = insert_once(frappe.get_doc({
            "doctype": "CFG ERP Command",
            "command_type": "Create Internal Transfer Receipt",
            "movement_manifest": manifest.name,
            "status": "Pending",
            "target_doctype": "Stock Entry",
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
        _set_transfer_status(manifest, "Receipt Document Pending")
        try:
            receipt = execute_command(command.name)
        except Exception:
            _manifest_exception(manifest, "Receipt ERP Command Failed",
                                "Transit receipt Stock Entry creation or submission failed",
                                command.name)
            raise
        manifest.reload()
        _resolve_manifest_exception(manifest, "Transit receipt Stock Entry retried successfully")
        if receipt.docstatus == 0:
            manifest.db_set({"receipt_stock_entry": receipt.name,
                             "state": "Receipt Document Pending"}, update_modified=True)
        return get_manifest(manifest.name, operator_session_token)
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
    if (manifest.dispatch_delivery_note or manifest.receipt_purchase_receipt
            or manifest.dispatch_stock_entry or manifest.receipt_stock_entry):
        frappe.throw("Manifest has an ERP document and requires controlled recovery")
    if not reason:
        frappe.throw("Cancellation reason is required")
    if manifest.source_signal:
        from cfg_kanban.services.signal_cancellation import cancel_and_rollback
        cancel_and_rollback(manifest.source_signal, reason)
        manifest.db_set("cancelled_by", profile.employee, update_modified=False)
        return get_manifest(manifest.name, operator_session_token)
    if manifest.state == "Prepared":
        for row in manifest.lines:
            if row.line_kind == "ERP Stock without Physical Tag":
                continue
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
        assert_not_loaded_in_container(unit.name, "adding it to a Movement Manifest")
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


def _dispatch_stage(manifest):
    return "Outward" if manifest.internal_transfer_mode == "Goods in Transit" else "Direct"


def _internal_transfer_payload(manifest, stage, required_erp_inputs=None):
    payload = {
        "manifest": manifest.name,
        "stage": stage,
        "submit": bool(
            manifest.auto_submit_internal_receipt if stage == "Receipt"
            else manifest.auto_submit_internal_dispatch
        ),
    }
    if required_erp_inputs:
        payload["required_erp_inputs"] = frappe.parse_json(required_erp_inputs)
    return payload


def _validate_transfer_manifest_quantity(manifest, require_exact=False):
    """Keep a card-triggered movement inside its item and card quantity."""
    if not manifest.kanban_cycle:
        return
    cycle = frappe.get_doc("CFG Kanban Cycle", manifest.kanban_cycle)
    wrong_items = [row.item_code for row in manifest.lines if row.item_code != cycle.item_code]
    if wrong_items:
        frappe.throw(
            f"Transfer Card {cycle.kanban_card} controls Item {cycle.item_code}; "
            f"tagged Item {wrong_items[0]} cannot be added"
        )
    total = sum(flt(row.dispatch_qty) for row in manifest.lines)
    if total > flt(cycle.planned_qty) + 0.000001:
        frappe.throw(
            f"Tagged quantity {total} exceeds Transfer Card quantity {cycle.planned_qty}"
        )
    if require_exact and abs(total - flt(cycle.planned_qty)) > 0.000001:
        frappe.throw(
            f"Transfer Card requires exactly {cycle.planned_qty} {cycle.stock_uom}; "
            f"Manifest currently contains {total}"
        )


def _assert_untagged_erp_stock(item_code, warehouse, qty):
    if not frappe.db.get_value("Item", item_code, "is_stock_item"):
        frappe.throw(
            f"{item_code} does not maintain ERPNext stock. Use physical Stock Tags so CFG "
            "Kanban can control its operational quantity and Warehouse location."
        )
    tracking = frappe.db.get_value(
        "Item", item_code, ["has_batch_no", "has_serial_no"], as_dict=True
    )
    if tracking and (tracking.has_batch_no or tracking.has_serial_no):
        frappe.throw(
            f"{item_code} is batch/serial controlled. Use physical Stock Tags that identify the "
            "exact batch/serial stock, or use the Manual Material Transfer Fallback in ERPNext."
        )
    actual_qty = flt(frappe.db.get_value(
        "Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"
    ))
    if actual_qty + 0.000001 < flt(qty):
        frappe.throw(
            f"ERPNext stock for {item_code} in {warehouse} is {actual_qty}; "
            f"{flt(qty)} is required"
        )


def _can_use_untagged_stock(manifest):
    if (manifest.manifest_type != "Internal Warehouse Transfer"
            or not manifest.kanban_cycle or manifest.state != "Draft" or manifest.lines):
        return False
    return (not _is_non_stock_operational_manifest(manifest)
            and _transfer_tag_policy(manifest) != "Required Physical Tag")


def _transfer_tag_policy(manifest):
    """Return the effective Card policy; generic Manifests remain scan-first."""
    if not manifest.kanban_cycle:
        return "Manifest Scan"
    if _is_non_stock_operational_manifest(manifest):
        return "Required Physical Tag"
    cycle = frappe.get_doc("CFG Kanban Cycle", manifest.kanban_cycle)
    from cfg_kanban.services.trace_policy import effective_trace_policy
    policy = effective_trace_policy(cycle.item_code, manifest.source_company)
    return policy.get("warehouse_transfer_tag_policy") or "No Physical Tag"


def _is_non_stock_operational_manifest(manifest):
    if manifest.manifest_type != "Internal Warehouse Transfer" or not manifest.kanban_cycle:
        return False
    if manifest.get("inventory_control_mode"):
        return manifest.inventory_control_mode == "Kanban Operational Inventory"
    # Compatibility for a Manifest released before the inventory-mode snapshot existed.
    item_code = frappe.db.get_value("CFG Kanban Cycle", manifest.kanban_cycle, "item_code")
    return bool(item_code and not frappe.db.get_value("Item", item_code, "is_stock_item"))


def _confirm_non_stock_dispatch(
    manifest, profile, session, event_token, operator_session_token
):
    if any(not row.handling_unit for row in manifest.lines):
        frappe.throw("Non-stock operational transfer requires physical Stock Tags")
    destination = (manifest.transit_warehouse
                   if manifest.internal_transfer_mode == "Goods in Transit"
                   else manifest.destination_warehouse)
    if not destination:
        frappe.throw("Non-stock operational transfer requires a destination Warehouse")
    if manifest.internal_transfer_mode != "Goods in Transit":
        _release_non_stock_manifest_reservations(manifest, profile, session, "direct")
    for row in manifest.lines:
        unit = frappe.get_doc("CFG Kanban Handling Unit", row.handling_unit)
        if unit.current_warehouse != manifest.source_warehouse:
            frappe.throw(f"Tag {unit.handling_unit_id} is no longer in the source Warehouse")
        post_quantity_event(
            event_type="Location Transfer", qty=row.dispatch_qty, stock_uom=row.stock_uom,
            idempotency_key=canonical_key("non-stock-transfer-dispatch", manifest.name, row.name),
            source_handling_unit=row.handling_unit, item_code=row.item_code,
            batch_no=row.batch_no, source_company=manifest.source_company,
            destination_company=manifest.destination_company,
            source_warehouse=manifest.source_warehouse, destination_warehouse=destination,
            reference_doctype=manifest.doctype, reference_name=manifest.name,
            operator=profile.employee, operator_session=session.name,
            reason="Kanban operational movement for ERPNext non-stock Item",
        )
        frappe.db.set_value("CFG Kanban Handling Unit", row.handling_unit, {
            "current_warehouse": destination,
            "movement_state": ("Internal Transit" if manifest.internal_transfer_mode == "Goods in Transit"
                               else "Received"),
            "state": ("Dispatched" if manifest.internal_transfer_mode == "Goods in Transit"
                      else "Received"),
            "last_scan_time": now_datetime(),
        }, update_modified=False)
        frappe.db.set_value("CFG Kanban Manifest Line", row.name, {
            "state": ("In Transit" if manifest.internal_transfer_mode == "Goods in Transit"
                      else "Received"),
            "received_qty": (0 if manifest.internal_transfer_mode == "Goods in Transit"
                             else row.dispatch_qty),
        }, update_modified=False)
    _update_non_stock_containers(manifest, destination,
                                 manifest.internal_transfer_mode == "Goods in Transit")
    if manifest.internal_transfer_mode == "Goods in Transit":
        manifest.db_set({"state": "Awaiting Receipt",
                         "dispatch_key": canonical_key(
                             "non-stock-transfer-dispatch", manifest.name
                         ),
                         "dispatch_confirmed_by": profile.employee,
                         "dispatch_operator_session": session.name,
                         "dispatch_confirmed_on": now_datetime()}, update_modified=True)
        from cfg_kanban.services.state_machine import set_cycle_state, transition_card
        cycle = frappe.get_doc("CFG Kanban Cycle", manifest.kanban_cycle)
        cycle.db_set("transfer_status", "In Transit", update_modified=True)
        set_cycle_state(cycle, "In Transit", event_type="Non-stock Transfer Dispatched",
                        reference_doctype=manifest.doctype, reference_name=manifest.name)
        if cycle.kanban_card:
            card = frappe.get_doc("CFG Kanban Card", cycle.kanban_card)
            if card.current_state == "Replenishment Requested":
                transition_card(card, "In Transit", event_type="Non-stock Transfer Dispatched",
                                cycle=cycle.name)
        new_state = "Awaiting Receipt"
    else:
        manifest.db_set({"state": "Received", "total_received_quantity": manifest.total_quantity,
                         "dispatch_key": canonical_key(
                             "non-stock-transfer-dispatch", manifest.name
                         ),
                         "dispatch_confirmed_by": profile.employee,
                         "dispatch_operator_session": session.name,
                         "dispatch_confirmed_on": now_datetime()}, update_modified=True)
        from cfg_kanban.services.internal_transfer import complete_transfer_cycle
        complete_transfer_cycle(manifest, manifest.doctype, manifest.name)
        new_state = "Received"
    record(
        "Non-stock Operational Transfer Dispatched", movement_manifest=manifest.name,
        previous_state="Prepared", new_state=new_state, qty=manifest.total_quantity,
        device_id=canonical_key("non-stock-transfer-confirm", manifest.name, event_token or ""),
        reference_doctype=manifest.doctype, reference_name=manifest.name,
        operator=profile.employee, operator_session=session.name,
        terminal_user=session.terminal_user,
        notes="Handling Unit ledger only; no ERPNext Stock Entry",
    )
    return get_manifest(manifest.name, operator_session_token)


def _confirm_non_stock_receipt(
    manifest, profile, session, event_token, operator_session_token
):
    if manifest.internal_transfer_mode != "Goods in Transit":
        frappe.throw("Direct non-stock movement completes during dispatch confirmation")
    _release_non_stock_manifest_reservations(manifest, profile, session, "receipt")
    for row in manifest.lines:
        unit = frappe.get_doc("CFG Kanban Handling Unit", row.handling_unit)
        if unit.current_warehouse != manifest.transit_warehouse:
            frappe.throw(f"Tag {unit.handling_unit_id} is no longer in the Transit Warehouse")
        post_quantity_event(
            event_type="Location Transfer", qty=row.dispatch_qty, stock_uom=row.stock_uom,
            idempotency_key=canonical_key("non-stock-transfer-receipt", manifest.name, row.name),
            source_handling_unit=row.handling_unit, item_code=row.item_code,
            batch_no=row.batch_no, source_company=manifest.source_company,
            destination_company=manifest.destination_company,
            source_warehouse=manifest.transit_warehouse,
            destination_warehouse=manifest.destination_warehouse,
            reference_doctype=manifest.doctype, reference_name=manifest.name,
            operator=profile.employee, operator_session=session.name,
            reason="Kanban operational receipt for ERPNext non-stock Item",
        )
        frappe.db.set_value("CFG Kanban Handling Unit", row.handling_unit, {
            "current_warehouse": manifest.destination_warehouse,
            "movement_state": "Received", "state": "Received",
            "last_scan_time": now_datetime(),
        }, update_modified=False)
        frappe.db.set_value("CFG Kanban Manifest Line", row.name, {
            "state": "Received", "received_qty": row.dispatch_qty,
        }, update_modified=False)
    _update_non_stock_containers(manifest, manifest.destination_warehouse, False)
    manifest.db_set({"state": "Received", "total_received_quantity": manifest.total_quantity,
                     "receipt_key": canonical_key(
                         "non-stock-transfer-receipt", manifest.name
                     ),
                     "receipt_confirmed_by": profile.employee,
                     "receipt_operator_session": session.name,
                     "receipt_confirmed_on": now_datetime()}, update_modified=True)
    from cfg_kanban.services.internal_transfer import complete_transfer_cycle
    complete_transfer_cycle(manifest, manifest.doctype, manifest.name)
    record(
        "Non-stock Operational Transfer Received", movement_manifest=manifest.name,
        previous_state="Awaiting Receipt", new_state="Received", qty=manifest.total_quantity,
        device_id=canonical_key("non-stock-transfer-receipt-confirm", manifest.name,
                                event_token or ""),
        reference_doctype=manifest.doctype, reference_name=manifest.name,
        operator=profile.employee, operator_session=session.name,
        terminal_user=session.terminal_user,
        notes="Handling Unit ledger only; no ERPNext Stock Entry",
    )
    return get_manifest(manifest.name, operator_session_token)


def _release_non_stock_manifest_reservations(manifest, profile, session, suffix):
    for row in manifest.lines:
        unit = frappe.get_doc("CFG Kanban Handling Unit", row.handling_unit)
        if not flt(unit.reserved_qty):
            continue
        post_quantity_event(
            event_type="Unreserve", qty=min(flt(row.dispatch_qty), flt(unit.reserved_qty)),
            stock_uom=row.stock_uom,
            idempotency_key=canonical_key("non-stock-transfer-unreserve", suffix,
                                          manifest.name, row.name),
            source_handling_unit=row.handling_unit, item_code=row.item_code,
            batch_no=row.batch_no, source_company=manifest.source_company,
            source_warehouse=unit.current_warehouse,
            reference_doctype=manifest.doctype, reference_name=manifest.name,
            operator=profile.employee, operator_session=session.name,
            reason="Completed Kanban operational movement",
        )


def _update_non_stock_containers(manifest, warehouse, in_transit):
    container_names = {row.container_handling_unit for row in manifest.lines
                       if row.container_handling_unit}
    for container_name in container_names:
        frappe.db.set_value("CFG Kanban Handling Unit", container_name, {
            "current_warehouse": warehouse,
            "movement_state": "Internal Transit" if in_transit else "Received",
            "state": "Dispatched" if in_transit else "Received",
            "last_scan_time": now_datetime(),
        }, update_modified=False)


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
        "can_retag": bool(can_stock_retag(profile) and profile.can_start),
        "session": session.name,
    }


def _document_status(doctype, name):
    if not name or not frappe.db.exists(doctype, name):
        return None
    # Stock Entry does not expose a stored ``status`` column on every supported
    # ERPNext v15 revision. Query only fields that exist, then provide the
    # stable display status expected by the Logistics panel.
    fields = ["name", "docstatus"]
    if frappe.get_meta(doctype).has_field("status"):
        fields.insert(1, "status")
    row = frappe.db.get_value(doctype, name, fields, as_dict=True)
    if row and not row.get("status"):
        row["status"] = {
            0: "Draft",
            1: "Submitted",
            2: "Cancelled",
        }.get(cint(row.docstatus), "Unknown")
    return row


def _dispatch_retry_available(manifest):
    if manifest.state != "Exception":
        return False
    document_type = ("Stock Entry" if manifest.manifest_type == "Internal Warehouse Transfer"
                     else "Delivery Note")
    document_name = (manifest.dispatch_stock_entry
                     if document_type == "Stock Entry" else manifest.dispatch_delivery_note)
    document_status = _document_status(document_type, document_name)
    if document_status and document_status["docstatus"] == 1:
        return False
    command_name = manifest.dispatch_command
    return bool(
        command_name
        and frappe.db.get_value("CFG ERP Command", command_name, "status") == "Failed"
    )


def _receipt_retry_available(manifest):
    if manifest.state != "Exception":
        return False
    document_type = ("Stock Entry" if manifest.manifest_type == "Internal Warehouse Transfer"
                     else "Purchase Receipt")
    document_name = (manifest.receipt_stock_entry
                     if document_type == "Stock Entry" else manifest.receipt_purchase_receipt)
    document_status = _document_status(document_type, document_name)
    if document_status and document_status["docstatus"] == 1:
        return False
    command_name = manifest.receipt_command
    return bool(
        command_name
        and frappe.db.get_value("CFG ERP Command", command_name, "status") == "Failed"
    )


def _set_transfer_status(manifest, status):
    if manifest.manifest_type != "Internal Warehouse Transfer" or not manifest.kanban_cycle:
        return
    frappe.db.set_value(
        "CFG Kanban Cycle", manifest.kanban_cycle, "transfer_status", status,
        update_modified=True,
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
    _set_transfer_status(manifest, "Exception")
    return exception
