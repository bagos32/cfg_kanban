import frappe
from frappe.utils import add_days, cint, flt, now_datetime, today

from cfg_kanban.integrations.erp_gateway import execute_command
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key, insert_once
from cfg_kanban.services.triggers import create_work_order_command
from cfg_kanban.services.demand_math import calculate_mto_plan, calculate_recommendation


OPEN_CYCLE_STATES = ("New", "Signalled", "Released", "In Production", "Packing In Progress",
                     "Production Complete", "Waiting FG Receipt", "Hold", "Blocked")


def evaluate_sales_order(sales_order):
    if not frappe.db.exists("DocType", "CFG Kanban Demand"):
        return []
    sales_order = frappe.get_doc("Sales Order", sales_order) if isinstance(sales_order, str) else sales_order
    results = []
    for item in sales_order.items:
        master = _select_master(item.item_code,
            item.get("warehouse") or sales_order.get("set_warehouse"), sales_order)
        if not master:
            continue
        results.append(_evaluate_item(sales_order, item, master))
    return results


@frappe.whitelist()
def evaluate_order(sales_order):
    frappe.only_for(("Manufacturing Manager", "System Manager"))
    return evaluate_sales_order(sales_order)


def _select_master(item_code, warehouse=None, order=None):
    masters = frappe.get_all("CFG Kanban Master", filters={"item_code": item_code, "active": 1,
        "enable_sales_order_trigger": 1}, fields=["name", "destination_warehouse",
        "demand_scope", "demand_scope_value", "master_priority"])
    exact = [row for row in masters if warehouse and row.destination_warehouse == warehouse]
    candidates = exact if warehouse else masters
    scoped = [row for row in candidates if _scope_matches(row, order)]
    if not scoped:
        return None
    best_specificity = max(_scope_specificity(row) for row in scoped)
    scoped = [row for row in scoped if _scope_specificity(row) == best_specificity]
    best_priority = max(int(row.master_priority or 0) for row in scoped)
    winners = [row for row in scoped if int(row.master_priority or 0) == best_priority]
    if len(winners) == 1:
        return frappe.get_doc("CFG Kanban Master", winners[0].name)
    if winners:
        _raise_configuration_exception(item_code, warehouse, winners)
    return None


def _scope_matches(master, order):
    scope = master.demand_scope or "General"
    value = master.demand_scope_value
    if scope == "General":
        return True
    if not order:
        return False
    if scope == "Customer":
        return value == order.get("customer")
    if scope == "Sales Territory":
        return value == order.get("territory")
    if scope == "Production Line":
        return value == order.get("cfg_production_line")
    return False


def _scope_specificity(master):
    return 0 if (master.demand_scope or "General") == "General" else 1


def _evaluate_item(order, item, master):
    outstanding = max(0, flt(item.qty) - flt(item.delivered_qty))
    if (master.production_policy or "Stock Replenishment") == "Customer Make-to-Order":
        return _evaluate_mto_item(order, item, master, outstanding)
    projected = flt(frappe.db.get_value("Bin", {"item_code": item.item_code,
        "warehouse": master.destination_warehouse}, "projected_qty") or 0)
    open_qty = flt(frappe.db.sql("""
        select coalesce(sum(planned_qty), 0) from `tabCFG Kanban Cycle`
        where item_code=%s and destination_warehouse=%s and status in %s
    """, (master.item_code, master.destination_warehouse, OPEN_CYCLE_STATES))[0][0])
    key = canonical_key("sales-demand", order.name, item.name, master.name)
    open_proposal = flt(frappe.db.sql("""
        select coalesce(sum(recommended_qty), 0) from `tabCFG Kanban Demand`
        where item_code=%s and destination_warehouse=%s
          and status in ('Waiting Approval', 'Partially Allocated')
          and idempotency_key != %s
    """, (master.item_code, master.destination_warehouse, key))[0][0])
    target, threshold_source = _get_target_stock(master)
    minimum = flt(master.sales_minimum_shortage_qty)
    card_qty = flt(master.replenishment_qty)
    maximum = int(master.sales_max_cards_per_order or 0)
    missing_threshold = target is None
    if missing_threshold:
        target, shortage, count, recommended, capped = 0, 0, 0, 0, False
    else:
        shortage, count, recommended, capped = calculate_recommendation(
            target, projected, open_qty + open_proposal, card_qty, minimum, maximum)
    status = "Blocked" if missing_threshold else ("Waiting Approval" if count else "No Action")
    note = "Recommendation capped by maximum cards per Sales Order" if capped else None
    error = (f"No ERPNext warehouse reorder level exists for {master.item_code} / "
             f"{master.destination_warehouse}") if missing_threshold else None
    demand, created = insert_once(frappe.get_doc({
        "doctype": "CFG Kanban Demand", "sales_order": order.name,
        "sales_order_item_row": item.name, "customer": order.customer,
        "kanban_master": master.name, "item_code": item.item_code,
        "destination_warehouse": master.destination_warehouse,
        "threshold_source": threshold_source, "target_stock_qty": target,
        "sales_order_qty": item.qty, "delivered_qty": item.delivered_qty,
        "outstanding_qty": outstanding, "projected_available_qty": projected,
        "open_kanban_qty": open_qty, "open_proposal_qty": open_proposal,
        "net_shortage_qty": shortage, "kanban_qty": card_qty,
        "recommended_card_count": count, "recommended_qty": recommended,
        "status": status, "delivery_date": item.delivery_date,
        "evaluated_on": now_datetime(),
        "notes": note, "error_message": error,
    }), key)
    if not created and demand.status not in ("Released", "Cancelled"):
        demand.db_set({"sales_order_qty": item.qty, "delivered_qty": item.delivered_qty,
            "outstanding_qty": outstanding, "projected_available_qty": projected,
            "destination_warehouse": master.destination_warehouse,
            "threshold_source": threshold_source, "target_stock_qty": target,
            "open_kanban_qty": open_qty, "open_proposal_qty": open_proposal,
            "net_shortage_qty": shortage, "kanban_qty": card_qty,
            "recommended_card_count": count, "recommended_qty": recommended,
            "status": status, "delivery_date": item.delivery_date,
            "evaluated_on": now_datetime(), "notes": note,
            "error_message": error}, update_modified=True)
    if missing_threshold and created:
        _create_exception(demand, error)
    return {"demand": demand.name, "status": demand.status, "created": created}


def _evaluate_mto_item(order, item, master, outstanding):
    key = canonical_key("sales-demand", order.name, item.name, master.name)
    effective_pct, base_qty, maximum_qty, planned_qty = calculate_mto_plan(
        outstanding, master.mto_extra_tolerance_pct,
        cint(order.get("cfg_po_allows_extra_qty")), order.get("cfg_po_extra_tolerance_pct"),
        cint(master.mto_plan_to_maximum))
    status = "Waiting Approval" if outstanding > 0 else "No Action"
    values = {
        "demand_type": "Customer Make-to-Order", "production_policy": "Customer Make-to-Order",
        "sales_order": order.name, "sales_order_item_row": item.name, "customer": order.customer,
        "kanban_master": master.name, "item_code": item.item_code,
        "destination_warehouse": master.destination_warehouse,
        "threshold_source": "Customer PO / MTO", "target_stock_qty": 0,
        "sales_order_qty": item.qty, "delivered_qty": item.delivered_qty,
        "outstanding_qty": base_qty, "master_tolerance_pct": master.mto_extra_tolerance_pct,
        "po_allows_extra_qty": cint(order.get("cfg_po_allows_extra_qty")),
        "po_tolerance_pct": flt(order.get("cfg_po_extra_tolerance_pct")),
        "effective_tolerance_pct": effective_pct, "maximum_authorized_qty": maximum_qty,
        "net_shortage_qty": base_qty, "kanban_qty": 0, "recommended_card_count": 0,
        "recommended_qty": planned_qty, "excess_acceptance_status": "Not Applicable",
        "po_tolerance_reference": order.get("cfg_po_tolerance_reference"),
        "status": status, "delivery_date": item.delivery_date, "evaluated_on": now_datetime(),
        "notes": "Dedicated MTO cycle; existing stock and order consolidation are prohibited.",
    }
    demand, created = insert_once(frappe.get_doc({"doctype": "CFG Kanban Demand", **values}), key)
    if not created and demand.status not in ("Released", "Cancelled"):
        demand.db_set(values, update_modified=True)
    return {"demand": demand.name, "status": demand.status, "created": created}


def _get_target_stock(master):
    source = master.threshold_source or "ERPNext Warehouse Reorder Level"
    if source == "Kanban Override":
        return flt(master.minimum_stock_override), source
    level = frappe.db.get_value("Item Reorder", {
        "parent": master.item_code, "warehouse": master.destination_warehouse,
    }, "warehouse_reorder_level")
    return (flt(level), source) if level is not None else (None, source)


@frappe.whitelist()
def approve_demand(demand_name):
    frappe.only_for(("Manufacturing Manager", "System Manager"))
    demand = frappe.get_doc("CFG Kanban Demand", demand_name)
    if demand.status == "Released":
        return {"demand": demand.name, "signal": demand.signal, "cycle": demand.cycle,
                "duplicate": True}
    is_mto = demand.production_policy == "Customer Make-to-Order"
    if demand.status != "Waiting Approval" or demand.recommended_qty <= 0:
        frappe.throw(f"Demand cannot be approved while it is {demand.status}")
    cards = [] if is_mto else _reserve_cards(demand)
    if cards is None:
        return {"demand": demand.name, "blocked": True, "message": demand.error_message,
                "required_cards": demand.recommended_card_count}
    master = frappe.get_doc("CFG Kanban Master", demand.kanban_master)
    batch = _ensure_mto_batch(demand) if is_mto else None
    cycle = frappe.get_doc({"doctype": "CFG Kanban Cycle", "kanban_master": master.name,
        "item_code": master.item_code, "planned_qty": demand.recommended_qty,
        "stock_uom": master.stock_uom, "status": "Signalled", "priority": master.default_priority,
        "source_warehouse": master.source_warehouse,
        "destination_warehouse": master.destination_warehouse,
        "production_policy": demand.production_policy,
        "sales_order": demand.sales_order, "sales_order_item_row": demand.sales_order_item_row,
        "batch_no": batch.name if batch else None,
        "sales_demand": demand.name}).insert(ignore_permissions=True)
    signal_key = canonical_key("sales-demand-signal", demand.name)
    signal, _ = insert_once(frappe.get_doc({"doctype": "CFG Kanban Signal",
        "signal_type": "Production Replenishment", "kanban_master": master.name,
        "kanban_cycle": cycle.name, "sales_demand": demand.name, "item_code": master.item_code,
        "requested_qty": demand.recommended_qty, "stock_uom": master.stock_uom,
        "status": "Validated", "priority": master.default_priority,
        "automation_level": "Approval", "requested_on": now_datetime(),
        "validated_on": now_datetime()}), signal_key)
    cycle.db_set("signal", signal.name)
    demand.signal, demand.cycle = signal.name, cycle.name
    demand.planned_batch = batch.name if batch else None
    demand.allocated_card_count = len(cards)
    demand.status, demand.approved_on, demand.approved_by = "Released", now_datetime(), frappe.session.user
    demand.save(ignore_permissions=True)
    command = create_work_order_command(signal.name)
    result = execute_command(command.name)
    record("Sales Demand Released", cycle=cycle.name, qty=demand.recommended_qty,
           reference_doctype=demand.doctype, reference_name=demand.name,
           notes=f"Sales Order {demand.sales_order}", system_generated=False)
    return {"demand": demand.name, "signal": signal.name, "cycle": cycle.name,
            "work_order": result.name, "batch": batch.name if batch else None,
            "duplicate": False}


def _reserve_cards(demand):
    cards = frappe.get_all("CFG Kanban Card", filters={"kanban_master": demand.kanban_master,
        "active": 1, "current_state": "Available", "active_cycle": ["is", "not set"],
        "reserved_for_demand": ["is", "not set"]}, fields=["name", "kanban_qty"],
        order_by="creation asc", limit_page_length=demand.recommended_card_count)
    if len(cards) < demand.recommended_card_count:
        demand.db_set({"status": "Blocked", "error_message":
            f"Required {demand.recommended_card_count} cards; only {len(cards)} are available"})
        _create_exception(demand, "Insufficient available Kanban cards for confirmed sales demand")
        return None
    for card in cards:
        frappe.db.set_value("CFG Kanban Card", card.name, "reserved_for_demand", demand.name)
        demand.append("allocations", {"kanban_card": card.name,
            "allocated_qty": card.kanban_qty or demand.kanban_qty, "status": "Reserved"})
    return cards


def _ensure_mto_batch(demand):
    item = frappe.get_cached_doc("Item", demand.item_code)
    if not item.has_batch_no:
        frappe.throw(f"Item {demand.item_code} must have Has Batch No enabled for MTO production")
    existing = frappe.db.get_value("Batch", {"cfg_sales_demand": demand.name}, "name")
    if existing:
        return frappe.get_doc("Batch", existing)
    batch_id = f"MTO-{demand.sales_order}-{demand.sales_order_item_row[-8:]}".replace("/", "-")
    values = {"doctype": "Batch", "batch_id": batch_id, "item": demand.item_code,
        "manufacturing_date": today(), "cfg_sales_demand": demand.name,
        "cfg_sales_order": demand.sales_order}
    if cint(item.shelf_life_in_days):
        values["expiry_date"] = add_days(today(), cint(item.shelf_life_in_days))
    return frappe.get_doc(values).insert(ignore_permissions=True)


def cancel_sales_order_demands(sales_order):
    name = sales_order.name if hasattr(sales_order, "name") else sales_order
    demands = frappe.get_all("CFG Kanban Demand", filters={"sales_order": name,
        "status": ["not in", ("Cancelled", "No Action")]}, pluck="name")
    for demand_name in demands:
        demand = frappe.get_doc("CFG Kanban Demand", demand_name)
        if demand.status == "Waiting Approval":
            demand.db_set("status", "Cancelled")
            continue
        demand.db_set({"status": "Blocked", "error_message":
            "Sales Order was cancelled after Kanban release; supervisor review required"})
        _create_exception(demand, "Sales Order cancelled after Kanban production was released")


def _create_exception(demand, message):
    return frappe.get_doc({"doctype": "CFG Kanban Exception", "exception_type": "Sales Demand",
        "severity": "Error", "status": "Open", "kanban_cycle": demand.cycle,
        "message": message, "reference_doctype": demand.doctype,
        "reference_name": demand.name, "raised_on": now_datetime()}).insert(ignore_permissions=True)


def _raise_configuration_exception(item_code, warehouse, candidates):
    frappe.get_doc({"doctype": "CFG Kanban Exception", "exception_type": "Configuration",
        "severity": "Error", "status": "Open", "message":
        f"Multiple sales-trigger Kanban Masters match {item_code} / {warehouse or 'no warehouse'}",
        "reference_doctype": "Item", "reference_name": item_code,
        "raised_on": now_datetime()}).insert(ignore_permissions=True)
