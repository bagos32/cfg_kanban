import frappe
from frappe.utils import cint, cstr, flt, now_datetime
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
    if work_order.transfer_material_against == "Job Card":
        missing = [row.item_code for row in work_order.required_items
                   if not row.operation and row.item_code not in restricted_items]
        restricted_missing = any(
            not row.operation and row.item_code in restricted_items
            for row in work_order.required_items
        )
        if missing:
            frappe.throw(
                "Job Card material control requires Item Operation on every BOM component: "
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
    profile, _session = require_operator(operator_session_token)
    cycle, master, work_order = _production_context(cycle_name)
    mode = _effective_mode(master, work_order)
    hidden_policy = get_hidden_item_policy()
    restricted_items = (hidden_policy["items"]
                        if not hidden_policy["can_view"] else set())
    all_rows = [_work_order_material_row(row, work_order.wip_warehouse, mode)
                for row in work_order.required_items]
    restricted_rows = [row for row in all_rows if row["item_code"] in restricted_items]
    rows = [row for row in all_rows if row["item_code"] not in restricted_items]
    material_rules = {
        (row.item_code, row.operation or ""): row for row in master.material_flow_rules
    }
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
        consumed_by_item = (_job_consumed_quantities(job.name)
                            if mode == "Skip WIP Transfer" else {})
        all_material_rows = [
            _job_material_row(
                row, work_order.wip_warehouse, mode,
                consumed_by_item.get((row.item_code, row.source_warehouse), 0),
            )
            for row in items
        ]
        for material_row in all_material_rows:
            rule = material_rules.get((material_row["item_code"], job.operation or ""))
            material_row["wip_presentation_method"] = (
                (rule.wip_presentation_method if rule else None)
                or "Standard ERP / Tag Flow"
            )
            material_row["standard_bin_qty"] = flt(
                rule.standard_bin_qty if rule else 0
            )
            material_row["wip_bin_pool"] = rule.wip_bin_pool if rule else None
        restricted_job_rows = [row for row in all_material_rows
                               if row["item_code"] in restricted_items]
        material_rows = [row for row in all_material_rows
                         if row["item_code"] not in restricted_items]
        wip_loads = frappe.get_all(
            "CFG Kanban WIP Bin Load",
            {"kanban_cycle": cycle.name, "job_card": job.name,
             "status": ["in", ["Ready", "In Use", "Consumption Draft"]]},
            ["name", "status", "item_code", "actual_qty", "stock_uom", "reusable_bin"],
            order_by="creation asc",
        )
        open_wip_consumption = frappe.db.get_value("Stock Entry", {
            "cfg_kanban_cycle": cycle.name,
            "work_order": work_order.name,
            "job_card": job.name,
            "purpose": "Material Consumption for Manufacture",
            "docstatus": 0,
        }, "name")
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
                     ),
                     "wip_bin_ready_count": sum(
                         1 for row in wip_loads if row.status == "Ready"
                     ),
                     "wip_bin_ready_qty": sum(
                         flt(row.actual_qty) for row in wip_loads if row.status == "Ready"
                     ),
                     "wip_bin_consumption_draft": open_wip_consumption})

    incomplete_jobs = [row["name"] for row in jobs if row["status"] != "Completed"]
    remaining_output = max(0, flt(work_order.qty) - flt(work_order.produced_qty))
    wip_bin_reconciliations = frappe.get_all(
        "CFG Kanban WIP Bin Reconciliation",
        {"kanban_cycle": cycle.name, "work_order": work_order.name, "status": "Open"},
        ["name", "reversal_context", "wip_bin_load", "reusable_bin",
         "source_handling_unit", "item_code", "batch_no", "qty",
         "stock_uom", "job_card", "operation", "workstation",
         "cancelled_stock_entry", "exception", "raised_on"],
        order_by="raised_on asc",
    )
    for reconciliation in wip_bin_reconciliations:
        reconciliation.reversal_context = (
            reconciliation.reversal_context or "Consumption Cancellation"
        )
    from cfg_kanban.services.wip_bin_loads import manufacture_receipt_wip_bin_readiness
    receipt_wip_readiness = manufacture_receipt_wip_bin_readiness(
        work_order.name, cycle.name
    )
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
        "wip_bin_reconciliations": wip_bin_reconciliations,
        "can_reconcile_wip_bins": bool(
            profile.kanban_role in ("Supervisor", "Development Proxy")
            and cint(profile.get("can_override"))
        ),
        "has_pending_materials": any(row["pending_qty"] > 0.000001 for row in all_rows),
        "restricted_materials_present": bool(restricted_rows),
        "restricted_material_attention": any(
            row["shortage_qty"] > 0.000001 for row in restricted_rows
        ),
        "has_shortage": any(row["shortage_qty"] > 0 for row in all_rows),
        "all_job_cards_completed": not incomplete_jobs and bool(jobs),
        "incomplete_job_cards": incomplete_jobs,
        "wip_bin_receipt_ready": receipt_wip_readiness["ready"],
        "wip_bin_receipt_block_reason": receipt_wip_readiness["reason"],
        "active_wip_bin_loads": receipt_wip_readiness["active_loads"],
        "material_transfer_posting_mode": master.get("material_transfer_posting_mode")
            or "Create Draft for Review",
        "material_consumption_posting_mode": "Create Draft for Review",
        "manufacture_posting_mode": master.get("manufacture_posting_mode")
            or "Create Draft for Tag / Batch Review",
    }


@frappe.whitelist()
def prepare_material_transfer(cycle_name, lines, job_card=None, event_token=None,
                              confirmation=None, operator_session_token=None,
                              defer_submit_for_scanning=0, requesting_cycle=None):
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
    operation_cycle = _validated_operation_requesting_cycle(
        requesting_cycle, cycle, work_order, job_card
    )
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
              "Submit on Operator Confirmation" and not cint(defer_submit_for_scanning))
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
    if operation_cycle:
        record(
            "Operation Card Material Transfer Prepared",
            card=operation_cycle.kanban_card,
            cycle=operation_cycle.name,
            execution=frappe.db.get_value(
                "CFG Kanban Process Execution",
                {"kanban_cycle": operation_cycle.name, "job_card": job_card}, "name",
            ),
            qty=sum(row["qty"] for row in normalized),
            reference_doctype="Stock Entry", reference_name=entry.name,
            operator=profile.employee, operator_session=session.name,
            terminal_user=session.terminal_user,
            notes=f"ERP material owner Cycle {cycle.name}; Job Card {job_card}",
        )
    return {"command": command.name, "stock_entry": entry.name,
            "docstatus": entry.docstatus, "duplicate": not created}


@frappe.whitelist()
def prepare_wip_bin_consumption(cycle_name, job_card, confirmation,
                                operator_session_token=None, event_token=None,
                                requesting_cycle=None):
    """Create a Draft native consumption entry from the Job Card's Ready WIP bins."""
    cycle, master, work_order = _production_context(cycle_name)
    if work_order.docstatus != 1:
        frappe.throw("Submit the effective Work Order before consuming WIP-bin materials")
    if (_effective_mode(master, work_order) != "Transfer to WIP by Job Card"
            or work_order.transfer_material_against != "Job Card"):
        frappe.throw("Ready WIP Bin consumption requires Transfer to WIP by Job Card")
    job = frappe.db.get_value(
        "Job Card", {"name": job_card, "work_order": work_order.name,
                     "docstatus": ["<", 2]},
        ["name", "operation", "workstation"], as_dict=True,
    )
    if not job:
        frappe.throw("Job Card does not belong to the effective Work Order")
    operation_cycle = _validated_operation_requesting_cycle(
        requesting_cycle, cycle, work_order, job_card
    )
    execution = frappe.db.get_value(
        "CFG Kanban Process Execution",
        {"kanban_cycle": cycle.name, "job_card": job.name}, "name",
    )
    profile, session = require_operator(
        operator_session_token, "material_transfer", execution=execution,
        operation=job.operation, workstation=job.workstation,
    )
    confirmation = _validated_confirmation(confirmation)
    _assert_no_open_production_entry(
        cycle.name, work_order.name, "Material Consumption for Manufacture", job.name
    )
    ready = frappe.get_all(
        "CFG Kanban WIP Bin Load",
        {"kanban_cycle": cycle.name, "work_order": work_order.name,
         "job_card": job.name, "status": "Ready"},
        ["name", "item_code", "batch_no", "actual_qty", "stock_uom",
         "wip_warehouse"], order_by="creation asc",
    )
    if not ready:
        frappe.throw(f"Job Card {job.name} has no Ready Standard Quantity WIP Bin")
    grouped = {}
    for load in ready:
        key = (load.item_code, load.wip_warehouse, load.batch_no or "", load.stock_uom)
        grouped[key] = grouped.get(key, 0) + flt(load.actual_qty)
    lines = [{
        "item_code": item_code,
        "source_warehouse": warehouse,
        "batch_no": batch_no or None,
        "stock_uom": stock_uom,
        "qty": qty,
    } for (item_code, warehouse, batch_no, stock_uom), qty in grouped.items()]
    identity = event_token or frappe.as_json(lines)
    key = canonical_key("wip-bin-material-consumption", cycle.name, job.name, identity)
    command, created = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command",
        "command_type": "Create Production Material Consumption",
        "source_signal": cycle.signal,
        "kanban_cycle": cycle.name,
        "process_execution": execution,
        "status": "Pending",
        "target_doctype": "Stock Entry",
        "request_payload": frappe.as_json({
            "work_order": work_order.name,
            "job_card": job.name,
            "lines": lines,
            "wip_bin_consumption": 1,
            "submit": False,
            "operator": profile.employee,
            "confirmation": confirmation,
        }),
        "requested_on": now_datetime(),
        "created_by_system": 1,
        "requested_by_operator": profile.employee,
        "operator_session": session.name,
        "terminal_user": session.terminal_user,
    }), key, ignore_permissions=True)
    entry = execute_command(command.name)
    record(
        "WIP Bin Material Consumption Prepared", card=cycle.kanban_card,
        cycle=cycle.name, execution=execution,
        qty=sum(row["qty"] for row in lines),
        reference_doctype="Stock Entry", reference_name=entry.name,
        operator=profile.employee, operator_session=session.name,
        terminal_user=session.terminal_user,
        notes=(f"Job Card {job.name}; {len(ready)} Ready bin(s); "
               f"Operator confirmation: {confirmation}"),
    )
    if operation_cycle:
        record(
            "Operation Card WIP Bin Consumption Prepared",
            card=operation_cycle.kanban_card, cycle=operation_cycle.name,
            execution=frappe.db.get_value(
                "CFG Kanban Process Execution",
                {"kanban_cycle": operation_cycle.name, "job_card": job.name}, "name",
            ),
            qty=sum(row["qty"] for row in lines),
            reference_doctype="Stock Entry", reference_name=entry.name,
            operator=profile.employee, operator_session=session.name,
            terminal_user=session.terminal_user,
            notes=f"ERP material owner Cycle {cycle.name}; Job Card {job.name}",
        )
    return {"command": command.name, "stock_entry": entry.name,
            "docstatus": entry.docstatus, "duplicate": not created,
            "ready_bin_count": len(ready)}


@frappe.whitelist()
def prepare_material_consumption(cycle_name, lines, job_card=None, event_token=None,
                                 confirmation=None, operator_session_token=None,
                                 defer_submit_for_scanning=0, requesting_cycle=None):
    """Create native ERPNext consumption for actual Skip-WIP operation usage.

    Draft creation gives the scanner native ERP rows against which physical tag quantities
    can be reserved. Only ERPNext submission consumes stock and confirms genealogy.
    """
    cycle, master, work_order = _production_context(cycle_name)
    if work_order.docstatus != 1:
        frappe.throw("Submit the effective Work Order before consuming production materials")
    if _effective_mode(master, work_order) != "Skip WIP Transfer":
        frappe.throw(
            "Operation material consumption is available only when the Work Order uses "
            "Skip WIP Transfer"
        )

    execution = None
    operation = None
    workstation = None
    if work_order.transfer_material_against == "Job Card":
        if not job_card:
            frappe.throw("Select the Job Card whose actual material usage is being recorded")
        job = frappe.db.get_value(
            "Job Card", {"name": job_card, "work_order": work_order.name,
                         "docstatus": ["<", 2]},
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
        frappe.throw(
            "This Skip-WIP Work Order records consumption against the Work Order, not a Job Card"
        )

    operation_cycle = _validated_operation_requesting_cycle(
        requesting_cycle, cycle, work_order, job_card
    )
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
    _validate_consumption_scope(
        work_order, normalized, hidden_policy["items"], job_card=job_card
    )
    confirmation = _validated_confirmation(confirmation)
    for row in normalized:
        _assert_warehouse_company(row["source_warehouse"], work_order.company)
    _assert_no_open_production_entry(
        cycle.name, work_order.name, "Material Consumption for Manufacture", job_card
    )

    required_tag_scan = _requires_input_tag_scan(normalized, work_order.company)
    # Consumption remains Draft until the operator has had a chance to scan the exact
    # physical quantity used. This is intentionally independent of WIP-transfer posting.
    submit = False
    identity = event_token or frappe.as_json(normalized)
    key = canonical_key(
        "production-material-consumption", cycle.name,
        job_card or work_order.name, identity,
    )
    command, created = insert_once(frappe.get_doc({
        "doctype": "CFG ERP Command",
        "command_type": "Create Production Material Consumption",
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
    record(
        "Production Material Consumption Prepared", card=cycle.kanban_card,
        cycle=cycle.name, execution=execution,
        qty=sum(row["qty"] for row in normalized),
        reference_doctype="Stock Entry", reference_name=entry.name,
        operator=profile.employee, operator_session=session.name,
        terminal_user=session.terminal_user,
        notes=(f"Skip WIP Transfer; {'Submitted' if entry.docstatus == 1 else 'Draft'}; "
               f"Job Card {job_card or 'Work Order scope'}; "
               f"Operator confirmation: {confirmation}"),
    )
    if operation_cycle:
        record(
            "Operation Card Material Consumption Prepared",
            card=operation_cycle.kanban_card,
            cycle=operation_cycle.name,
            execution=frappe.db.get_value(
                "CFG Kanban Process Execution",
                {"kanban_cycle": operation_cycle.name, "job_card": job_card}, "name",
            ),
            qty=sum(row["qty"] for row in normalized),
            reference_doctype="Stock Entry", reference_name=entry.name,
            operator=profile.employee, operator_session=session.name,
            terminal_user=session.terminal_user,
            notes=f"ERP material owner Cycle {cycle.name}; Job Card {job_card}",
        )
    return {
        "command": command.name,
        "stock_entry": entry.name,
        "docstatus": entry.docstatus,
        "duplicate": not created,
        "tag_scan_required": required_tag_scan,
    }


@frappe.whitelist()
def prepare_manufacture_receipt(cycle_name, output_qty, lines=None,
                                target_warehouse=None, batch_no=None, event_token=None,
                                confirmation=None, operator_session_token=None,
                                defer_submit_for_scanning=0):
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
    from cfg_kanban.services.wip_bin_loads import manufacture_receipt_wip_bin_readiness
    receipt_wip_readiness = manufacture_receipt_wip_bin_readiness(
        work_order.name, cycle.name
    )
    if not receipt_wip_readiness["ready"]:
        frappe.throw(receipt_wip_readiness["reason"])
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
    batch_no = _validated_finished_batch(cycle, work_order, batch_no)
    _assert_no_open_production_entry(
        cycle.name, work_order.name, "Manufacture"
    )
    submit = (master.get("manufacture_posting_mode") == "Submit on Operator Confirmation"
              and not cint(defer_submit_for_scanning))
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
def discard_premature_manufacture_draft(stock_entry, reason,
                                        operator_session_token=None):
    """Discard only a clean, Kanban-created Manufacture draft blocked by WIP bins.

    The Stock Entry never posted stock. Its command and event remain as audit evidence, while
    the operator can complete WIP-bin consumption and create a fresh ERPNext-mapped receipt.
    """
    explanation = (reason or "").strip()
    if not explanation:
        frappe.throw("A discard reason is required")
    frappe.db.sql(
        "select name from `tabStock Entry` where name=%s for update", stock_entry
    )
    entry = frappe.get_doc("Stock Entry", stock_entry)
    if (entry.docstatus != 0 or entry.purpose != "Manufacture"
            or not entry.get("cfg_kanban_controlled")
            or not entry.get("cfg_kanban_cycle")):
        frappe.throw("Only a Kanban-controlled Draft Manufacture entry can be discarded here")
    cycle = frappe.get_doc("CFG Kanban Cycle", entry.cfg_kanban_cycle)
    if cycle.work_order != entry.work_order:
        frappe.throw("Manufacture draft does not match its Kanban Cycle Work Order")
    profile, session = require_operator(operator_session_token, "production_receipt")
    from cfg_kanban.services.wip_bin_loads import manufacture_receipt_wip_bin_readiness
    readiness = manufacture_receipt_wip_bin_readiness(
        entry.work_order, entry.cfg_kanban_cycle
    )
    if readiness["ready"]:
        frappe.throw(
            "This Manufacture draft is no longer blocked by an active WIP Bin; review it "
            "instead of discarding it through premature-draft recovery"
        )
    trace = frappe.db.get_value(
        "CFG Kanban Material Trace", {"stock_entry": entry.name}, ["name", "status"],
        as_dict=True,
    )
    if trace:
        frappe.throw(
            f"Material Trace {trace.name} is already attached. Discard its Draft trace first, "
            "then discard this premature Manufacture draft."
        )
    command_names = frappe.get_all(
        "CFG ERP Command",
        filters={"target_doctype": "Stock Entry", "target_document": entry.name},
        pluck="name",
    )
    for command_name in command_names:
        frappe.db.set_value("CFG ERP Command", command_name, {
            "status": "Cancelled",
            "target_document": None,
            "last_error": f"Premature Draft {entry.name} discarded: {explanation}",
        }, update_modified=False)
    entry_name = entry.name
    audit_reference = command_names[0] if command_names else None
    _detach_discarded_stock_entry_events(
        entry_name, explanation, audit_reference=audit_reference
    )
    frappe.delete_doc("Stock Entry", entry_name, ignore_permissions=True)
    record(
        "Premature Manufacture Draft Discarded", card=cycle.kanban_card,
        cycle=cycle.name,
        reference_doctype="CFG ERP Command" if audit_reference else None,
        reference_name=audit_reference,
        operator=profile.employee, operator_session=session.name,
        terminal_user=session.terminal_user,
        notes=(f"Discarded Draft Stock Entry {entry_name}; blocked by active WIP Bin "
               f"material; {explanation}"),
    )
    return {"discarded_stock_entry": entry_name, "cycle": cycle.name}


def _detach_discarded_stock_entry_events(stock_entry, reason, audit_reference=None):
    """Preserve immutable Events without leaving a Dynamic Link to a deleted ERP draft."""
    events = frappe.get_all(
        "CFG Kanban Event",
        filters={"reference_doctype": "Stock Entry", "reference_name": stock_entry},
        fields=["name", "notes"],
    )
    suffix = f"Discarded Draft Stock Entry reference: {stock_entry}. Reason: {reason}"
    for event in events:
        notes = cstr(event.notes).strip()
        if suffix not in notes:
            notes = f"{notes}\n{suffix}".strip()
        frappe.db.set_value("CFG Kanban Event", event.name, {
            "reference_doctype": "CFG ERP Command" if audit_reference else None,
            "reference_name": audit_reference,
            "notes": notes,
        }, update_modified=False)


def _validated_finished_batch(cycle, work_order, batch_no):
    """Accept an existing/new operator Batch, or leave ERPNext to generate one."""
    requested = cstr(batch_no).strip()
    planned = cstr(cycle.get("batch_no")).strip()
    if planned:
        if requested and requested != planned:
            frappe.throw(
                f"Finished Batch must use the Cycle planned Batch {planned}"
            )
        return planned
    if not requested:
        # A blank value is intentional. ERPNext may create the Batch during submission
        # according to the finished Item's native Batch settings.
        return None

    item = frappe.db.get_value(
        "Item", work_order.production_item, ["has_batch_no"], as_dict=True
    )
    if not item or not cint(item.has_batch_no):
        frappe.throw(
            f"Finished Item {work_order.production_item} is not Batch-controlled; "
            "leave Finished Batch blank"
        )
    existing = (
        frappe.db.get_value("Batch", requested, ["name", "item"], as_dict=True)
        or frappe.db.get_value(
            "Batch", {"batch_id": requested}, ["name", "item"], as_dict=True
        )
    )
    if existing and existing.item != work_order.production_item:
        frappe.throw(
            f"Batch {requested} belongs to a different Item and cannot receive "
            f"{work_order.production_item}"
        )
    return existing.name if existing else requested


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
    action = ("material_transfer" if entry.purpose in (
        "Material Transfer for Manufacture", "Material Consumption for Manufacture"
    ) else "production_receipt")
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


def _validated_operation_requesting_cycle(requesting_cycle, owner_cycle, work_order,
                                           job_card):
    if not requesting_cycle or requesting_cycle == owner_cycle.name:
        return None
    if not job_card:
        frappe.throw("An operation Card can request only its selected Job Card materials")
    cycle = frappe.get_doc("CFG Kanban Cycle", requesting_cycle)
    if (not cycle.runtime_allocation or cycle.work_order != work_order.name
            or cycle.selected_job_card != job_card):
        frappe.throw("Operation Card Cycle does not control this Work Order / Job Card")
    if frappe.db.get_value("Job Card", job_card, "work_order") != work_order.name:
        frappe.throw("Selected Job Card does not belong to the effective Work Order")
    return cycle


def _effective_mode(_master, work_order):
    # The released Work Order is the immutable execution truth. A later Master edit must not
    # reinterpret an active Cycle's already-created material path.
    if work_order.skip_transfer:
        return "Skip WIP Transfer"
    return ("Transfer to WIP by Job Card"
            if work_order.transfer_material_against == "Job Card"
            else "Transfer to WIP by Work Order")


def job_card_material_readiness(job_card_name):
    """Return whether ERP material transfer prerequisites allow this Job Card to start."""
    job = frappe.db.get_value(
        "Job Card", job_card_name, ["name", "work_order"], as_dict=True
    )
    if not job:
        return {"ready": False, "reason": "ERPNext Job Card was not found", "pending_qty": 0}
    work_order = frappe.db.get_value(
        "Work Order", job.work_order,
        ["skip_transfer", "transfer_material_against"], as_dict=True,
    )
    if not work_order:
        return {"ready": False, "reason": "ERPNext Work Order was not found", "pending_qty": 0}
    if work_order.skip_transfer:
        return {"ready": True, "reason": None, "pending_qty": 0}
    if work_order.transfer_material_against == "Job Card":
        pending = flt(frappe.db.sql("""
            select coalesce(sum(greatest(required_qty - coalesce(transferred_qty, 0), 0)), 0)
            from `tabJob Card Item` where parent=%s
        """, job.name)[0][0])
        reason = (f"Prepare and submit the operation materials for Job Card {job.name} "
                  f"before starting it. Pending transfer quantity: {pending}")
        return {"ready": pending <= 0.000001, "reason": reason, "pending_qty": pending}
    pending = flt(frappe.db.sql("""
        select coalesce(sum(greatest(required_qty - coalesce(transferred_qty, 0), 0)), 0)
        from `tabWork Order Item` where parent=%s
    """, job.work_order)[0][0])
    reason = (f"Submit the Work Order material transfer before starting Job Card {job.name}. "
              f"Pending transfer quantity: {pending}")
    return {"ready": pending <= 0.000001, "reason": reason, "pending_qty": pending}


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


def _job_material_row(row, wip_warehouse, mode=None, consumed_qty=0):
    consumed = flt(consumed_qty)
    accounted = consumed if mode == "Skip WIP Transfer" else flt(row.transferred_qty)
    pending = max(0, flt(row.required_qty) - accounted)
    available = _balance(row.item_code, row.source_warehouse)
    return {
        "item_code": row.item_code,
        "source_warehouse": row.source_warehouse,
        "wip_warehouse": wip_warehouse,
        "stock_uom": row.uom,
        "required_qty": flt(row.required_qty),
        "transferred_qty": flt(row.transferred_qty),
        "consumed_qty": consumed,
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
    consumed = (_job_consumed_quantities(job_card)
                if job_card and work_order.skip_transfer else {})
    return any(
        row.item_code in restricted_items
        and flt(row.required_qty) - (
            flt(consumed.get((row.item_code, row.source_warehouse), 0))
            if work_order.skip_transfer else flt(row.transferred_qty)
        ) > 0.000001
        for row in rows
    )


def _job_consumed_quantities(job_card):
    if not job_card:
        return {}
    rows = frappe.db.sql("""
        select sed.item_code, sed.s_warehouse,
               coalesce(sum(coalesce(nullif(sed.transfer_qty, 0),
                                     sed.qty * coalesce(sed.conversion_factor, 1))), 0)
                   as consumed_qty
        from `tabStock Entry Detail` sed
        inner join `tabStock Entry` se on se.name = sed.parent
        where se.docstatus = 1
          and se.purpose = 'Material Consumption for Manufacture'
          and se.job_card = %s
          and sed.s_warehouse is not null
        group by sed.item_code, sed.s_warehouse
    """, job_card, as_dict=True)
    return {
        (row.item_code, row.s_warehouse): flt(row.consumed_qty)
        for row in rows
    }


def _validate_consumption_scope(work_order, normalized, restricted_items, job_card=None):
    source_rows = (frappe.get_doc("Job Card", job_card).items
                   if job_card else work_order.required_items)
    allowed = {(row.item_code, row.source_warehouse) for row in source_rows}
    invalid = [
        f"{row['item_code']} / {row['source_warehouse']}"
        for row in normalized
        if (row["item_code"], row["source_warehouse"]) not in allowed
    ]
    if invalid:
        frappe.throw(
            "Material is outside the selected Job Card / Work Order scope: "
            + ", ".join(invalid)
        )
    if not normalized and not any(
            row.item_code in restricted_items for row in source_rows):
        frappe.throw("At least one positive material quantity is required")


def _requires_input_tag_scan(lines, company):
    if not lines:
        return False
    from cfg_kanban.services.trace_policy import effective_trace_policy

    return any(
        effective_trace_policy(row["item_code"], company).production_input_tag_policy
        == "Required Physical Tag"
        for row in lines
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
