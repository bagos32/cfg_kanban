import frappe
from frappe.utils import flt, now_datetime
from erpnext.stock.utils import get_stock_balance

from cfg_kanban.integrations.erp_gateway import execute_command
from cfg_kanban.services.events import record
from cfg_kanban.services.hidden_items import get_hidden_item_policy
from cfg_kanban.services.idempotency import canonical_key, insert_once
from cfg_kanban.services.operator_auth import require_operator


def apply_master_material_flow(work_order, master):
    """Apply the approved Master material policy before the Work Order is inserted."""
    mode = master.get("production_material_mode") or "Follow ERPNext BOM / Work Order"
    if mode == "Transfer to WIP by Work Order":
        work_order.skip_transfer = 0
        work_order.transfer_material_against = "Work Order"
    elif mode == "Transfer to WIP by Job Card":
        work_order.skip_transfer = 0
        work_order.transfer_material_against = "Job Card"
    elif mode == "Skip WIP Transfer":
        work_order.skip_transfer = 1

    rules = {(row.item_code, row.operation or ""): row for row in master.material_flow_rules}
    for row in work_order.required_items:
        rule = rules.get((row.item_code, row.operation or ""))
        if rule:
            row.source_warehouse = rule.source_warehouse

    hidden_policy = get_hidden_item_policy()
    restricted_items = (hidden_policy["items"]
                        if not hidden_policy["can_view"] else set())
    if work_order.transfer_material_against == "Job Card" and not work_order.skip_transfer:
        missing = [row.item_code for row in work_order.required_items
                   if not row.operation and row.item_code not in restricted_items]
        restricted_missing = any(
            not row.operation and row.item_code in restricted_items
            for row in work_order.required_items
        )
        if missing:
            frappe.throw(
                "Job Card material transfer requires Item Operation on every BOM component: "
                + ", ".join(missing)
            )
        if restricted_missing:
            frappe.throw(
                "A restricted production component has no Item Operation. Contact an "
                "authorized material controller."
            )
    # The default mode preserves ERPNext's own Work Order behaviour for existing Masters.
    # Explicit Kanban modes (or an explicit component map) require deterministic sources.
    if mode == "Follow ERPNext BOM / Work Order" and not rules:
        return
    missing_warehouses = [row.item_code for row in work_order.required_items
                          if not row.source_warehouse
                          and row.item_code not in restricted_items]
    restricted_missing_warehouse = any(
        not row.source_warehouse and row.item_code in restricted_items
        for row in work_order.required_items
    )
    if missing_warehouses:
        frappe.throw(
            "Source Warehouse is missing for required material: "
            + ", ".join(missing_warehouses)
        )
    if restricted_missing_warehouse:
        frappe.throw(
            "A restricted production component has no Source Warehouse. Contact an "
            "authorized material controller."
        )


@frappe.whitelist()
def get_cycle_material_flow(cycle_name, operator_session_token=None):
    require_operator(operator_session_token)
    cycle, master, work_order = _production_context(cycle_name)
    mode = _effective_mode(master, work_order)
    hidden_policy = get_hidden_item_policy()
    restricted_items = (hidden_policy["items"]
                        if not hidden_policy["can_view"] else set())
    all_rows = [_work_order_material_row(row, work_order.wip_warehouse, mode)
                for row in work_order.required_items]
    restricted_rows = [row for row in all_rows if row["item_code"] in restricted_items]
    rows = [row for row in all_rows if row["item_code"] not in restricted_items]
    jobs = []
    for job in frappe.get_all(
        "Job Card",
        filters={"work_order": work_order.name, "docstatus": ["<", 2]},
        fields=["name", "operation", "workstation", "status", "docstatus",
                "for_quantity"],
        order_by="creation asc",
    ):
        items = frappe.get_all(
            "Job Card Item", filters={"parent": job.name},
            fields=["item_code", "source_warehouse", "required_qty", "transferred_qty", "uom"],
            order_by="idx asc",
        )
        all_material_rows = [_job_material_row(row, work_order.wip_warehouse)
                             for row in items]
        restricted_job_rows = [row for row in all_material_rows
                               if row["item_code"] in restricted_items]
        material_rows = [row for row in all_material_rows
                         if row["item_code"] not in restricted_items]
        jobs.append({**job, "materials": material_rows,
                     "pending_material_qty": sum(row["pending_qty"] for row in material_rows),
                     "has_pending_materials": any(
                         row["pending_qty"] > 0.000001 for row in all_material_rows
                     ),
                     "restricted_materials_present": bool(restricted_job_rows),
                     "restricted_material_attention": any(
                         row["shortage_qty"] > 0.000001 for row in restricted_job_rows
                     ),
                     "has_shortage": any(
                         row["shortage_qty"] > 0.000001 for row in all_material_rows
                     )})

    incomplete_jobs = [row["name"] for row in jobs if row["status"] != "Completed"]
    remaining_output = max(0, flt(work_order.qty) - flt(work_order.produced_qty))
    return {
        "cycle": cycle.name,
        "work_order": work_order.name,
        "work_order_status": work_order.status,
        "work_order_docstatus": work_order.docstatus,
        "mode": mode,
        "transfer_material_against": work_order.transfer_material_against,
        "skip_transfer": bool(work_order.skip_transfer),
        "wip_warehouse": work_order.wip_warehouse,
        "output_warehouse": work_order.fg_warehouse,
        "stock_uom": cycle.stock_uom,
        "production_item": work_order.production_item,
        "company": work_order.company,
        "planned_batch": cycle.get("batch_no"),
        "planned_output_qty": flt(cycle.planned_qty),
        "remaining_output_qty": remaining_output,
        "materials": rows,
        "jobs": jobs,
        "has_pending_materials": any(row["pending_qty"] > 0.000001 for row in all_rows),
        "restricted_materials_present": bool(restricted_rows),
        "restricted_material_attention": any(
            row["shortage_qty"] > 0.000001 for row in restricted_rows
        ),
        "has_shortage": any(row["shortage_qty"] > 0 for row in all_rows),
        "all_job_cards_completed": not incomplete_jobs and bool(jobs),
        "incomplete_job_cards": incomplete_jobs,
        "material_transfer_posting_mode": master.get("material_transfer_posting_mode")
            or "Create Draft for Review",
        "manufacture_posting_mode": master.get("manufacture_posting_mode")
            or "Create Draft for Tag / Batch Review",
    }


@frappe.whitelist()
def prepare_material_transfer(cycle_name, lines, job_card=None, event_token=None,
                              confirmation=None, operator_session_token=None):
    cycle, master, work_order = _production_context(cycle_name)
    if work_order.docstatus != 1:
        frappe.throw("Submit the effective Work Order before preparing production materials")
    mode = _effective_mode(master, work_order)
    if mode == "Skip WIP Transfer":
        frappe.throw("This Work Order uses Skip WIP Transfer; inputs are consumed by Manufacture")
    execution = None
    operation = None
    workstation = None
    if mode == "Transfer to WIP by Job Card":
        if not job_card:
            frappe.throw("Select the Job Card whose operation materials are being prepared")
        job = frappe.db.get_value(
            "Job Card", {"name": job_card, "work_order": work_order.name},
            ["name", "operation", "workstation"], as_dict=True,
        )
        if not job:
            frappe.throw("Job Card does not belong to the effective Work Order")
        operation, workstation = job.operation, job.workstation
        execution = frappe.db.get_value(
            "CFG Kanban Process Execution",
            {"kanban_cycle": cycle.name, "job_card": job.name}, "name",
        )
    elif job_card:
        frappe.throw("This Master transfers materials against the Work Order, not a Job Card")
    profile, session = require_operator(
        operator_session_token, "material_transfer", execution=execution,
        operation=operation, workstation=workstation,
    )
    hidden_policy = get_hidden_item_policy()
    server_manage_restricted = bool(
        hidden_policy["items"] and not hidden_policy["can_view"]
    )
    normalized = _validated_confirmation_lines(
        lines, allow_empty=server_manage_restricted
    )
    if server_manage_restricted and any(
            row["item_code"] in hidden_policy["items"] for row in normalized):
        frappe.throw("Restricted production components are managed server-side")
    confirmation = _validated_confirmation(confirmation)
    if not normalized and not _has_pending_restricted_material(
            work_order, hidden_policy["items"], job_card=job_card):
        frappe.throw("At least one positive material quantity is required")
    for row in normalized:
        _assert_warehouse_company(row["source_warehouse"], work_order.company)
    _assert_no_open_production_entry(
        cycle.name, work_order.name, "Material Transfer for Manufacture", job_card
    )
    submit = (master.get("material_transfer_posting_mode") ==
              "Submit on Operator Confirmation")
    identity = event_token or frappe.as_json(normalized)
    key = canonical_key("production-material-transfer", cycle.name,
                        job_card or work_order.name, identity)
    command, created = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command",
        "command_type": "Create Production Material Transfer",
        "source_signal": cycle.signal,
        "kanban_cycle": cycle.name,
        "process_execution": execution,
        "status": "Pending",
        "target_doctype": "Stock Entry",
        "request_payload": frappe.as_json({
            "work_order": work_order.name,
            "job_card": job_card,
            "lines": normalized,
            "submit": submit,
            "operator": profile.employee,
            "confirmation": confirmation,
            "server_manage_restricted_items": server_manage_restricted,
        }),
        "requested_on": now_datetime(),
        "created_by_system": 1,
        "requested_by_operator": profile.employee,
        "operator_session": session.name,
        "terminal_user": session.terminal_user,
    }), key, ignore_permissions=True)
    entry = execute_command(command.name)
    record("Production Material Transfer Prepared", card=cycle.kanban_card,
           cycle=cycle.name, execution=execution, qty=sum(row["qty"] for row in normalized),
           reference_doctype="Stock Entry", reference_name=entry.name,
           operator=profile.employee, operator_session=session.name,
           terminal_user=session.terminal_user,
           notes=(f"{mode}; {'Submitted' if entry.docstatus == 1 else 'Draft'}; "
                  f"Operator confirmation: {confirmation}"))
    return {"command": command.name, "stock_entry": entry.name,
            "docstatus": entry.docstatus, "duplicate": not created}


@frappe.whitelist()
def prepare_manufacture_receipt(cycle_name, output_qty, lines=None,
                                target_warehouse=None, batch_no=None, event_token=None,
                                confirmation=None, operator_session_token=None):
    cycle, master, work_order = _production_context(cycle_name)
    if work_order.docstatus != 1:
        frappe.throw("Submit the effective Work Order before preparing Manufacture receipt")
    profile, session = require_operator(operator_session_token, "production_receipt")
    qty = flt(output_qty)
    remaining = max(0, flt(work_order.qty) - flt(work_order.produced_qty))
    if qty <= 0 or qty > remaining + 0.000001:
        frappe.throw(f"Manufacture quantity must be greater than zero and not exceed {remaining}")
    incomplete = frappe.get_all(
        "Job Card", filters={"work_order": work_order.name, "docstatus": ["<", 2],
                             "status": ["!=", "Completed"]}, pluck="name",
    )
    if incomplete:
        frappe.throw("Complete the ERPNext Job Card(s) before receiving output: "
                     + ", ".join(incomplete))
    hidden_policy = get_hidden_item_policy()
    server_manage_restricted = bool(
        hidden_policy["items"] and not hidden_policy["can_view"]
    )
    normalized = _validated_confirmation_lines(lines or [], allow_empty=True)
    if server_manage_restricted and any(
            row["item_code"] in hidden_policy["items"] for row in normalized):
        frappe.throw("Restricted production components are managed server-side")
    confirmation = _validated_confirmation(confirmation)
    for row in normalized:
        _assert_warehouse_company(row["source_warehouse"], work_order.company)
    target = target_warehouse or master.destination_warehouse or work_order.fg_warehouse
    _assert_warehouse_company(target, work_order.company)
    _assert_no_open_production_entry(
        cycle.name, work_order.name, "Manufacture"
    )
    submit = master.get("manufacture_posting_mode") == "Submit on Operator Confirmation"
    identity = event_token or f"{qty}:{target}:{batch_no or ''}:{frappe.as_json(normalized)}"
    key = canonical_key("production-manufacture-receipt", cycle.name, identity)
    command, created = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command",
        "command_type": "Create Production Manufacture Receipt",
        "source_signal": cycle.signal,
        "kanban_cycle": cycle.name,
        "status": "Pending",
        "target_doctype": "Stock Entry",
        "request_payload": frappe.as_json({
            "work_order": work_order.name,
            "output_qty": qty,
            "target_warehouse": target,
            "batch_no": batch_no,
            "lines": normalized,
            "submit": submit,
            "operator": profile.employee,
            "confirmation": confirmation,
            "server_manage_restricted_items": server_manage_restricted,
        }),
        "requested_on": now_datetime(),
        "created_by_system": 1,
        "requested_by_operator": profile.employee,
        "operator_session": session.name,
        "terminal_user": session.terminal_user,
    }), key, ignore_permissions=True)
    entry = execute_command(command.name)
    record("Production Manufacture Receipt Prepared", card=cycle.kanban_card,
           cycle=cycle.name, qty=qty, reference_doctype="Stock Entry",
           reference_name=entry.name, operator=profile.employee,
           operator_session=session.name, terminal_user=session.terminal_user,
           notes=(f"Target {target}; {'Submitted' if entry.docstatus == 1 else 'Draft'}; "
                  f"Operator confirmation: {confirmation}"))
    return {"command": command.name, "stock_entry": entry.name,
            "docstatus": entry.docstatus, "duplicate": not created}


@frappe.whitelist()
def submit_production_stock_entry(stock_entry, event_token=None,
                                  operator_session_token=None):
    entry = frappe.get_doc("Stock Entry", stock_entry)
    cycle_name = entry.get("cfg_kanban_cycle")
    if not cycle_name:
        frappe.throw("Stock Entry is not controlled by a CFG Kanban production Cycle")
    cycle, _master, work_order = _production_context(cycle_name)
    if entry.work_order != work_order.name or entry.docstatus != 0:
        frappe.throw("Only a Draft Stock Entry for the effective Work Order can be submitted")
    action = ("material_transfer" if entry.purpose == "Material Transfer for Manufacture"
              else "production_receipt")
    profile, session = require_operator(operator_session_token, action)
    key = canonical_key("submit-production-stock-entry", entry.name,
                        event_token or entry.modified)
    command, created = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command",
        "command_type": "Submit Production Stock Entry",
        "source_signal": cycle.signal,
        "kanban_cycle": cycle.name,
        "status": "Pending",
        "target_doctype": "Stock Entry",
        "target_document": entry.name,
        "request_payload": frappe.as_json({"stock_entry": entry.name}),
        "requested_on": now_datetime(),
        "created_by_system": 1,
        "requested_by_operator": profile.employee,
        "operator_session": session.name,
        "terminal_user": session.terminal_user,
    }), key, ignore_permissions=True)
    result = execute_command(command.name)
    record("Production Stock Entry Submitted", card=cycle.kanban_card,
           cycle=cycle.name, reference_doctype="Stock Entry", reference_name=result.name,
           operator=profile.employee, operator_session=session.name,
           terminal_user=session.terminal_user, notes=entry.purpose)
    return {"command": command.name, "stock_entry": result.name,
            "docstatus": result.docstatus, "duplicate": not created}


def _production_context(cycle_name):
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    if master.control_type != "Production" or not cycle.work_order:
        frappe.throw("Cycle does not have an effective Production Work Order")
    work_order = frappe.get_doc("Work Order", cycle.work_order)
    if work_order.get("cfg_kanban_cycle") != cycle.name:
        frappe.throw("Effective Work Order is not linked back to this Kanban Cycle")
    return cycle, master, work_order


def _effective_mode(_master, work_order):
    # The released Work Order is the immutable execution truth. A later Master edit must not
    # reinterpret an active Cycle's already-created material path.
    if work_order.skip_transfer:
        return "Skip WIP Transfer"
    return ("Transfer to WIP by Job Card"
            if work_order.transfer_material_against == "Job Card"
            else "Transfer to WIP by Work Order")


def _work_order_material_row(row, wip_warehouse, mode):
    consumed = flt(row.consumed_qty)
    accounted = consumed if mode == "Skip WIP Transfer" else flt(row.transferred_qty)
    pending = max(0, flt(row.required_qty) - accounted)
    source = row.source_warehouse
    available = _balance(row.item_code, source)
    wip_available = _balance(row.item_code, wip_warehouse)
    manufacture_pending = max(0, flt(row.required_qty) - consumed)
    if mode == "Skip WIP Transfer" or pending > 0.000001:
        shortage = max(0, pending - available)
    else:
        shortage = max(0, manufacture_pending - wip_available)
    return {
        "item_code": row.item_code,
        "item_name": row.item_name,
        "operation": row.operation,
        "source_warehouse": source,
        "wip_warehouse": wip_warehouse,
        "stock_uom": row.stock_uom,
        "required_qty": flt(row.required_qty),
        "transferred_qty": flt(row.transferred_qty),
        "consumed_qty": consumed,
        "pending_qty": pending,
        "available_qty": available,
        "wip_available_qty": wip_available,
        "manufacture_pending_qty": manufacture_pending,
        "shortage_qty": shortage,
    }


def _job_material_row(row, wip_warehouse):
    pending = max(0, flt(row.required_qty) - flt(row.transferred_qty))
    available = _balance(row.item_code, row.source_warehouse)
    return {
        "item_code": row.item_code,
        "source_warehouse": row.source_warehouse,
        "wip_warehouse": wip_warehouse,
        "stock_uom": row.uom,
        "required_qty": flt(row.required_qty),
        "transferred_qty": flt(row.transferred_qty),
        "pending_qty": pending,
        "available_qty": available,
        "shortage_qty": max(0, pending - available),
    }


def _balance(item_code, warehouse):
    return flt(get_stock_balance(item_code, warehouse)) if warehouse else 0


def _has_pending_restricted_material(work_order, restricted_items, job_card=None):
    if not restricted_items:
        return False
    rows = (frappe.get_doc("Job Card", job_card).items
            if job_card else work_order.required_items)
    return any(
        row.item_code in restricted_items
        and flt(row.required_qty) - flt(row.transferred_qty) > 0.000001
        for row in rows
    )


def _validated_confirmation_lines(lines, allow_empty=False):
    values = frappe.parse_json(lines) if isinstance(lines, str) else (lines or [])
    result = []
    for row in values:
        qty = flt(row.get("qty"))
        if qty < 0:
            frappe.throw("Confirmed material quantity cannot be negative")
        if not qty:
            continue
        if not row.get("item_code") or not row.get("source_warehouse"):
            frappe.throw("Every confirmed material row needs Item and Source Warehouse")
        result.append({
            "item_code": row.get("item_code"),
            "source_warehouse": row.get("source_warehouse"),
            "qty": qty,
        })
    if not result and not allow_empty:
        frappe.throw("At least one positive material quantity is required")
    return result


def _validated_confirmation(value):
    confirmation = (value or "").strip()
    if not confirmation:
        frappe.throw("Operator Confirmation / Notes is required")
    return confirmation[:500]


def _assert_no_open_production_entry(cycle_name, work_order, purpose, job_card=None):
    filters = {
        "cfg_kanban_cycle": cycle_name,
        "work_order": work_order,
        "purpose": purpose,
        "docstatus": 0,
    }
    if job_card:
        filters["job_card"] = job_card
    existing = frappe.db.get_value("Stock Entry", filters, "name")
    if existing:
        scope = f" for Job Card {job_card}" if job_card else ""
        frappe.throw(
            f"Draft {purpose} {existing} already exists{scope}. Review, submit, or cancel "
            "that draft before preparing another entry."
        )


def _assert_warehouse_company(warehouse, company):
    details = frappe.db.get_value("Warehouse", warehouse,
                                  ["company", "is_group", "disabled"], as_dict=True)
    if not details or details.company != company or details.is_group or details.disabled:
        frappe.throw(f"Warehouse {warehouse} is not an enabled stock Warehouse for {company}")
