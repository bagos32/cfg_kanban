import json

import frappe
from frappe.utils import add_to_date, flt, get_datetime, now_datetime
from erpnext.manufacturing.doctype.work_order.work_order import get_item_details

from cfg_kanban.services.state_machine import set_cycle_state, transition_card


HANDLERS = {}


def handler(command_type):
    def register(fn):
        HANDLERS[command_type] = fn
        return fn
    return register


def execute_command(command_name):
    command = frappe.get_doc("CFG ERP Command", command_name)
    if command.status == "Completed" and command.target_document:
        return frappe.get_doc(command.target_doctype, command.target_document)
    if command.status == "Running":
        frappe.throw("ERP command is already running")
    fn = HANDLERS.get(command.command_type)
    if not fn:
        frappe.throw(f"No ERP gateway handler for {command.command_type}")
    command.db_set({"status": "Running", "started_on": now_datetime(),
                    "attempt_count": (command.attempt_count or 0) + 1})
    try:
        result = fn(command, json.loads(command.request_payload or "{}"))
        detail = getattr(result, "_cfg_command_result", None) or {
            "doctype": result.doctype, "name": result.name
        }
        command.db_set({"status": "Completed", "completed_on": now_datetime(),
                        "target_document": result.name,
                        "result_payload": frappe.as_json(detail)})
        return result
    except Exception:
        command.db_set({"status": "Failed", "last_error": frappe.get_traceback()})
        raise


@handler("Create Work Order")
def create_work_order(command, payload):
    cycle = frappe.get_doc("CFG Kanban Cycle", command.kanban_cycle)
    existing = frappe.db.get_value("Work Order", {"cfg_kanban_cycle": cycle.name, "docstatus": ["<", 2]}, "name")
    if existing:
        return frappe.get_doc("Work Order", existing)
    work_order = frappe.new_doc("Work Order")
    work_order.production_item = payload["production_item"]
    work_order.company = payload["company"]
    work_order.update(get_item_details(payload["production_item"]))
    work_order.update({
        "bom_no": payload.get("bom_no"), "qty": payload["qty"],
        "source_warehouse": payload.get("source_warehouse"), "wip_warehouse": payload.get("wip_warehouse"),
        "fg_warehouse": payload.get("fg_warehouse"), "cfg_kanban_controlled": 1,
        "cfg_kanban_cycle": cycle.name, "cfg_kanban_signal": command.source_signal,
        "cfg_production_origin": "SALES ORDER" if cycle.get("sales_order") else "KANBAN",
        "cfg_sales_order": cycle.get("sales_order"), "cfg_planned_batch": cycle.batch_no,
    })
    work_order.get_items_and_operations_from_bom()
    if not work_order.required_items:
        frappe.throw(f"BOM {work_order.bom_no} did not provide any required material rows")
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    if master.operation_profiles and not work_order.operations:
        frappe.throw(f"BOM {work_order.bom_no} has no operations. Enable With Operations and "
                     "configure the ERPNext BOM route before creating a Kanban Work Order.")
    work_order.insert(ignore_permissions=True)
    settings = frappe.get_single("CFG Kanban Settings")
    if settings.auto_submit_work_order:
        work_order.submit()
    cycle.db_set("work_order", work_order.name)
    signal = frappe.get_doc("CFG Kanban Signal", command.source_signal)
    signal.db_set({"erp_reference_doctype": "Work Order", "erp_reference_name": work_order.name,
                   "status": "Completed"})
    set_cycle_state(cycle, "Released", event_type="Work Order Created",
                    reference_doctype="Work Order", reference_name=work_order.name)
    if cycle.kanban_card:
        transition_card(cycle.kanban_card, "Production Released", event_type="Production Released", cycle=cycle.name)
    return work_order


@handler("Create Material Request")
def create_material_request(command, payload):
    cycle = frappe.get_doc("CFG Kanban Cycle", command.kanban_cycle)
    existing = frappe.db.get_value("Material Request", {
        "cfg_kanban_cycle": cycle.name, "docstatus": ["<", 2]
    }, "name")
    if existing:
        return frappe.get_doc("Material Request", existing)
    request = frappe.get_doc({
        "doctype": "Material Request", "material_request_type": "Purchase",
        "company": payload["company"], "schedule_date": add_to_date(now_datetime(), days=1).date(),
        "cfg_kanban_controlled": 1, "cfg_kanban_cycle": cycle.name,
        "cfg_kanban_signal": command.source_signal,
        "items": [{"item_code": payload["item_code"], "qty": payload["qty"],
                   "uom": payload.get("stock_uom"),
                   "warehouse": payload.get("warehouse"),
                   "schedule_date": add_to_date(now_datetime(), days=1).date()}],
    }).insert(ignore_permissions=True)
    if payload.get("submit"):
        request.submit()
    cycle.db_set({"material_request": request.name, "supplier": payload.get("supplier"),
                  "purchase_status": "Material Requested",
                  "outstanding_qty": payload["qty"]})
    signal = frappe.get_doc("CFG Kanban Signal", command.source_signal)
    signal.db_set({"erp_reference_doctype": "Material Request",
                   "erp_reference_name": request.name, "status": "Completed"})
    set_cycle_state(cycle, "Material Requested", event_type="Material Request Created",
                    reference_doctype="Material Request", reference_name=request.name)
    return request


@handler("Create Purchase Receipt")
def create_purchase_receipt(command, payload):
    from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

    cycle = frappe.get_doc("CFG Kanban Cycle", command.kanban_cycle)
    receipt = make_purchase_receipt(payload["purchase_order"])
    selected = [row for row in receipt.items
                if row.get("purchase_order_item") == payload["purchase_order_item"]]
    if not selected:
        frappe.throw("ERPNext could not map the selected Purchase Order item row")
    receipt.set("items", selected)
    row = receipt.items[0]
    row.received_qty = payload["delivered_qty"]
    row.qty = payload["accepted_qty"]
    row.rejected_qty = payload.get("rejected_qty") or 0
    row.warehouse = payload.get("warehouse")
    row.rejected_warehouse = payload.get("rejected_warehouse")
    receipt.supplier_delivery_note = payload.get("supplier_delivery_note")
    receipt.cfg_kanban_controlled = 1
    receipt.cfg_kanban_cycle = cycle.name
    receipt.cfg_kanban_signal = command.source_signal
    receipt.insert(ignore_permissions=True)

    item = frappe.db.get_value("Item", cycle.item_code,
                               ["has_batch_no", "has_serial_no", "inspection_required_before_purchase"],
                               as_dict=True)
    controlled = item and (item.has_batch_no or item.has_serial_no or
                           item.inspection_required_before_purchase)
    if payload.get("submit") and not controlled:
        receipt.submit()
    receipt._cfg_command_result = {
        "doctype": receipt.doctype, "name": receipt.name, "docstatus": receipt.docstatus,
        "submitted": receipt.docstatus == 1,
        "requires_erp_completion": bool(payload.get("submit") and controlled),
        "message": ("Draft retained because batch, serial, or Quality Inspection control must "
                    "be completed in ERPNext before submission") if payload.get("submit") and controlled else None,
    }
    cycle.db_set("latest_purchase_receipt", receipt.name)
    return receipt


@handler("Create Intercompany Delivery Note")
def create_intercompany_delivery_note(command, payload):
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", command.movement_manifest)
    existing = frappe.db.get_value(
        "Delivery Note",
        {"cfg_movement_manifest": manifest.name, "docstatus": ["<", 2]},
        "name",
    )
    if existing:
        return frappe.get_doc("Delivery Note", existing)
    delivery_note = build_intercompany_delivery_note(manifest, payload, command=command)
    delivery_note.insert(ignore_permissions=True)
    manifest.db_set("dispatch_delivery_note", delivery_note.name, update_modified=True)
    _link_manifest_erp_rows(manifest.name, delivery_note, "delivery_note_item")
    if payload.get("submit"):
        delivery_note.submit()
        delivery_note.reload()
    delivery_note._cfg_command_result = {
        "doctype": delivery_note.doctype,
        "name": delivery_note.name,
        "docstatus": delivery_note.docstatus,
        "submitted": delivery_note.docstatus == 1,
        "movement_manifest": manifest.name,
    }
    return delivery_note


def build_intercompany_delivery_note(manifest, payload, command=None, validate_required=True):
    """Build the ERP document in memory for preflight or command execution."""
    delivery_note = frappe.get_doc({
        "doctype": "Delivery Note",
        "company": payload["company"],
        "customer": payload["customer"],
        "posting_date": now_datetime().date(),
        "set_warehouse": payload["warehouse"],
        "selling_price_list": payload["price_list"],
        "cfg_kanban_controlled": 1,
        "cfg_logistics_route": manifest.logistics_route,
        "cfg_movement_manifest": manifest.name,
        "cfg_counterpart_company": payload["counterpart_company"],
        "cfg_requested_operator": command.requested_by_operator if command else None,
        "cfg_scan_event": command.idempotency_key if command else None,
        "items": [{
            "item_code": row["item_code"],
            "qty": row["qty"],
            "uom": row["uom"],
            "warehouse": payload["warehouse"],
            "batch_no": row.get("batch_no"),
            "rate": row["rate"],
            "price_list_rate": row["rate"],
            "cfg_handling_unit": row["handling_unit"],
            "cfg_manifest_line": row["manifest_line"],
        } for row in payload["items"]],
    })
    delivery_note.set_missing_values()
    apply_required_erp_inputs(delivery_note, payload.get("required_erp_inputs"))
    missing = get_required_erp_inputs(delivery_note)
    if validate_required and missing:
        frappe.throw(
            "Required Delivery Note details are missing: "
            + ", ".join(row["label"] for row in missing)
        )
    return delivery_note


@handler("Create Customer Delivery Note")
def create_customer_delivery_note(command, payload):
    delivery = frappe.get_doc("CFG Kanban Delivery Session", command.delivery_session)
    existing = frappe.db.get_value(
        "Delivery Note",
        {"cfg_delivery_session": delivery.name, "docstatus": ["<", 2]},
        "name",
    )
    if existing:
        return frappe.get_doc("Delivery Note", existing)
    delivery_note = build_customer_delivery_note(delivery, payload, command=command)
    delivery_note.insert(ignore_permissions=True)
    delivery.db_set("delivery_note", delivery_note.name, update_modified=True)
    for row in delivery_note.items:
        allocation = row.get("cfg_delivery_allocation")
        if allocation:
            frappe.db.set_value(
                "CFG Kanban Delivery Allocation", allocation,
                {"delivery_note": delivery_note.name, "delivery_note_item": row.name},
                update_modified=False,
            )
    if payload.get("submit"):
        delivery_note.submit()
        delivery_note.reload()
    delivery_note._cfg_command_result = {
        "doctype": delivery_note.doctype,
        "name": delivery_note.name,
        "docstatus": delivery_note.docstatus,
        "submitted": delivery_note.docstatus == 1,
        "delivery_session": delivery.name,
    }
    return delivery_note


def build_customer_delivery_note(delivery, payload, command=None, validate_required=True):
    """Build one locked-price customer Delivery Note row per physical allocation."""
    values = {
        "doctype": "Delivery Note",
        "company": payload["company"],
        "customer": payload["customer"],
        "posting_date": now_datetime().date(),
        "set_warehouse": payload["warehouse"],
        "selling_price_list": payload["price_list"],
        "shipping_address_name": payload["customer_address"],
        "cfg_kanban_controlled": 1,
        "cfg_delivery_session": delivery.name,
        "cfg_requested_operator": command.requested_by_operator if command else None,
        "cfg_scan_event": command.idempotency_key if command else None,
        "items": [{
            "item_code": row["item_code"],
            "qty": row["qty"],
            "uom": row["uom"],
            "warehouse": payload["warehouse"],
            "batch_no": row.get("batch_no"),
            "rate": row["rate"],
            "price_list_rate": row["rate"],
            "cfg_handling_unit": row["handling_unit"],
            "cfg_delivery_allocation": row["delivery_allocation"],
        } for row in payload["items"]],
    }
    if payload.get("amended_from"):
        values["amended_from"] = payload["amended_from"]
    delivery_note = frappe.get_doc(values)
    delivery_note.set_missing_values()
    apply_required_erp_inputs(delivery_note, payload.get("required_erp_inputs"))
    missing = get_required_erp_inputs(delivery_note)
    if validate_required and missing:
        frappe.throw(
            "Required Delivery Note details are missing: "
            + ", ".join(row["label"] for row in missing)
        )
    return delivery_note


def get_required_erp_inputs(doc):
    """Describe editable mandatory values still missing from an ERP document."""
    requirements = []
    for field in doc.meta.fields:
        if field.fieldtype == "Table":
            rows = doc.get(field.fieldname) or []
            missing_children = []
            for row_index, row in enumerate(rows):
                missing_children.extend(
                    _missing_child_requirements(field, row=row, row_index=row_index)
                )
            invalid_sales_team = (
                field.fieldname == "sales_team"
                and rows
                and abs(sum(flt(row.get("allocated_percentage")) for row in rows) - 100)
                > 0.000001
            )
            if (field.reqd and not rows) or missing_children or invalid_sales_team:
                requirements.append(_required_table_descriptor(field, rows))
            continue
        if not field.reqd:
            continue
        if _is_missing_required_value(doc.get(field.fieldname)):
            requirements.append(_required_field_descriptor(field, scope="parent"))
    return [row for row in requirements if row]


def apply_required_erp_inputs(doc, values):
    values = frappe.parse_json(values) if isinstance(values, str) else (values or {})
    allowed = get_required_erp_inputs(doc)
    parent_values = values.get("parent") or {}
    table_values = values.get("tables") or {}

    for requirement in allowed:
        if requirement["scope"] == "parent":
            value = parent_values.get(requirement["fieldname"])
            if not _is_missing_required_value(value):
                doc.set(requirement["fieldname"], value)

    for requirement in allowed:
        if requirement["scope"] != "table":
            continue
        supplied_rows = table_values.get(requirement["fieldname"])
        if supplied_rows:
            if requirement["fieldname"] == "sales_team":
                allocated = sum(flt(row.get("allocated_percentage")) for row in supplied_rows)
                if abs(allocated - 100) > 0.000001:
                    frappe.throw("Sales Team allocated percentage must total 100%")
            allowed_columns = {column["fieldname"] for column in requirement["fields"]}
            clean_rows = [
                {fieldname: row.get(fieldname) for fieldname in allowed_columns}
                for row in supplied_rows
            ]
            doc.set(requirement["fieldname"], clean_rows)

def _missing_child_requirements(table_field, row, row_index):
    child_meta = frappe.get_meta(table_field.options)
    requirements = []
    for field in child_meta.fields:
        if not field.reqd:
            continue
        value = row.get(field.fieldname) if row else None
        if _is_missing_required_value(value):
            requirements.append(_required_field_descriptor(
                field,
                scope="child",
                table_field=table_field.fieldname,
                table_label=table_field.label,
                row_index=row_index,
            ))
    return [requirement for requirement in requirements if requirement]


def _required_table_descriptor(table_field, rows):
    child_meta = frappe.get_meta(table_field.options)
    fields = []
    for field in child_meta.fields:
        include = bool(field.reqd or field.in_list_view)
        if table_field.fieldname == "sales_team" and field.fieldname in (
            "sales_person", "allocated_percentage"
        ):
            include = True
        if not include or field.read_only:
            continue
        descriptor = _required_field_descriptor(field, scope="table_column")
        if not descriptor:
            continue
        descriptor["reqd"] = bool(
            field.reqd
            or (
                table_field.fieldname == "sales_team"
                and field.fieldname in ("sales_person", "allocated_percentage")
            )
        )
        if table_field.fieldname == "sales_team" and field.fieldname == "allocated_percentage":
            descriptor["default"] = 100
        fields.append(descriptor)
    if not fields:
        frappe.throw(
            f"Mandatory ERP table {table_field.label} has no editable columns. "
            "Configure a default in ERPNext."
        )
    return {
        "scope": "table",
        "fieldname": table_field.fieldname,
        "label": table_field.label,
        "fieldtype": "Table",
        "options": table_field.options,
        "fields": fields,
        "default": [
            {column["fieldname"]: row.get(column["fieldname"]) for column in fields}
            for row in rows
        ],
    }


def _required_field_descriptor(field, scope, table_field=None, table_label=None, row_index=None):
    # Read-only mandatory values such as child-row Status are maintained by
    # ERPNext during validation and are not operator-supplied dispatch data.
    if field.read_only:
        return None
    supported = {
        "Data", "Link", "Select", "Date", "Datetime", "Int", "Float",
        "Currency", "Percent", "Check", "Time", "Duration", "Small Text", "Text",
    }
    if field.fieldtype not in supported:
        frappe.throw(
            f"Mandatory ERP field {table_label + ' / ' if table_label else ''}{field.label} "
            "cannot be collected from the logistics panel. Configure a default in ERPNext."
        )
    default = field.default
    if table_field == "sales_team" and field.fieldname == "allocated_percentage":
        default = 100
    return {
        "scope": scope,
        "fieldname": field.fieldname,
        "label": f"{table_label} / {field.label}" if table_label else field.label,
        "fieldtype": field.fieldtype,
        "options": field.options,
        "default": default,
        "table_field": table_field,
        "row_index": row_index,
    }


def _is_missing_required_value(value):
    return value is None or value == "" or value == []


@handler("Create Intercompany Purchase Receipt")
def create_intercompany_purchase_receipt(command, payload):
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", command.movement_manifest)
    existing = frappe.db.get_value(
        "Purchase Receipt",
        {"cfg_movement_manifest": manifest.name, "docstatus": ["<", 2]},
        "name",
    )
    if existing:
        return frappe.get_doc("Purchase Receipt", existing)
    receipt = frappe.get_doc({
        "doctype": "Purchase Receipt",
        "company": payload["company"],
        "supplier": payload["supplier"],
        "posting_date": now_datetime().date(),
        "set_warehouse": payload["warehouse"],
        "buying_price_list": payload["price_list"],
        "cfg_kanban_controlled": 1,
        "cfg_logistics_route": manifest.logistics_route,
        "cfg_movement_manifest": manifest.name,
        "cfg_counterpart_company": payload["counterpart_company"],
        "cfg_counterpart_document": payload.get("counterpart_document"),
        "cfg_requested_operator": command.requested_by_operator,
        "cfg_scan_event": command.idempotency_key,
        "items": [{
            "item_code": row["item_code"],
            "qty": row["qty"],
            "received_qty": row["qty"],
            "uom": row["uom"],
            "warehouse": payload["warehouse"],
            "batch_no": row.get("batch_no"),
            "rate": row["rate"],
            "price_list_rate": row["rate"],
            "cfg_handling_unit": row["handling_unit"],
            "cfg_manifest_line": row["manifest_line"],
        } for row in payload["items"]],
    })
    receipt.set_missing_values()
    receipt.insert(ignore_permissions=True)
    manifest.db_set("receipt_purchase_receipt", receipt.name, update_modified=True)
    _link_manifest_erp_rows(manifest.name, receipt, "purchase_receipt_item")
    if payload.get("submit"):
        receipt.submit()
        receipt.reload()
    receipt._cfg_command_result = {
        "doctype": receipt.doctype,
        "name": receipt.name,
        "docstatus": receipt.docstatus,
        "submitted": receipt.docstatus == 1,
        "movement_manifest": manifest.name,
    }
    return receipt


def _link_manifest_erp_rows(manifest_name, erp_document, target_field):
    for row in erp_document.items:
        manifest_line = row.get("cfg_manifest_line")
        if manifest_line:
            frappe.db.set_value(
                "CFG Kanban Manifest Line", manifest_line, target_field, row.name,
                update_modified=False,
            )


@frappe.whitelist()
def reload_draft_work_order_bom(work_order_name):
    """Repair a draft Kanban Work Order created before BOM population was added."""
    work_order = frappe.get_doc("Work Order", work_order_name)
    work_order.check_permission("write")
    if not work_order.cfg_kanban_cycle:
        frappe.throw("This Work Order is not linked to a CFG Kanban Cycle")
    if work_order.docstatus != 0:
        frappe.throw("BOM details can only be reloaded into a Draft Work Order")
    work_order.get_items_and_operations_from_bom()
    if not work_order.operations:
        frappe.throw(f"BOM {work_order.bom_no} has no operations. Enable With Operations and add the route first.")
    work_order.save()
    return {"work_order": work_order.name, "operations": len(work_order.operations),
            "required_items": len(work_order.required_items)}


@handler("Start Job Card")
def start_job_card(command, payload):
    job_card = frappe.get_doc("Job Card", payload["job_card"])
    if command.get("operator_session") and not payload.get("employee"):
        frappe.throw("An Employee is required for a Kanban operator Job Card action")
    if job_card.docstatus != 0:
        frappe.throw(f"Job Card {job_card.name} is not an editable Draft")
    if not any(not row.to_time for row in job_card.time_logs):
        started = now_datetime()
        job_card.append("time_logs", {
            "from_time": started, "employee": payload.get("employee")
        })
        job_card.save(ignore_permissions=True)
    job_card.reload()
    if job_card.status != "Work In Progress":
        frappe.throw(f"ERPNext did not start Job Card {job_card.name}; current status is {job_card.status}")
    job_card._cfg_command_result = _job_card_result(job_card, action="started")
    return job_card


@handler("Pause Job Card")
def pause_job_card(command, payload):
    """Close only the active time log; ERPNext retains cumulative Job Card output."""
    job_card = frappe.get_doc("Job Card", payload["job_card"])
    if job_card.docstatus != 0:
        frappe.throw(f"Job Card {job_card.name} is not an editable Draft")
    if job_card.status != "Work In Progress":
        frappe.throw(f"Job Card {job_card.name} must be Work In Progress before it can be paused")
    open_row = next((row for row in reversed(job_card.time_logs) if not row.to_time), None)
    closed_time_log = None
    if open_row:
        open_row.to_time = get_datetime(payload.get("paused_on") or now_datetime())
        closed_time_log = open_row.name
        job_card.save(ignore_permissions=True)
    job_card.reload()
    job_card._cfg_command_result = _job_card_result(
        job_card, action="paused", closed_time_log=closed_time_log,
        kanban_pause=True,
    )
    return job_card


@handler("Resume Job Card")
def resume_job_card(command, payload):
    """Open a fresh time log on the same Job Card after a Kanban-controlled pause."""
    job_card = frappe.get_doc("Job Card", payload["job_card"])
    if job_card.docstatus != 0:
        frappe.throw(f"Job Card {job_card.name} is not an editable Draft")
    if job_card.status not in ("Open", "Work In Progress"):
        frappe.throw(f"Job Card {job_card.name} cannot resume while its status is {job_card.status}")
    if not any(not row.to_time for row in job_card.time_logs):
        job_card.append("time_logs", {
            "from_time": get_datetime(payload.get("resumed_on") or now_datetime()),
            "employee": payload.get("employee"),
        })
        job_card.save(ignore_permissions=True)
    job_card.reload()
    if job_card.status != "Work In Progress":
        frappe.throw(f"ERPNext did not resume Job Card {job_card.name}; current status is {job_card.status}")
    job_card._cfg_command_result = _job_card_result(job_card, action="resumed", kanban_pause=True)
    return job_card


@handler("Update Job Card")
def update_job_card(command, payload):
    required = ("job_card", "operation_progress", "incremental_good_qty")
    missing = [field for field in required if payload.get(field) in (None, "")]
    if missing:
        frappe.throw("Job Card progress payload is missing: " + ", ".join(missing))
    job_card = frappe.get_doc("Job Card", payload["job_card"])
    if job_card.docstatus != 0:
        frappe.throw(f"Job Card {job_card.name} is not an editable Draft")

    progress_ref = payload["operation_progress"]
    # The app-owned child-row link makes a retry independently detectable even when
    # the original CFG command is manually re-created by a supervisor.
    existing = next((row for row in job_card.time_logs
                     if row.get("cfg_kanban_progress") == progress_ref), None)
    before_qty = flt(job_card.total_completed_qty)
    delta = flt(payload["incremental_good_qty"])
    if not existing:
        end_time = get_datetime(payload.get("to_time") or now_datetime())
        start_time = get_datetime(payload.get("from_time") or add_to_date(end_time, minutes=-1))
        closed_rows = [row for row in job_card.time_logs if row.to_time]
        if closed_rows:
            start_time = max(start_time, max(get_datetime(row.to_time) for row in closed_rows))
        if start_time >= end_time:
            start_time = add_to_date(end_time, minutes=-1)
        open_row = next((row for row in reversed(job_card.time_logs) if not row.to_time), None)
        if open_row:
            open_row.to_time = end_time
            open_row.completed_qty = delta
            open_row.employee = open_row.employee or payload.get("employee")
            open_row.cfg_kanban_progress = progress_ref
        else:
            job_card.append("time_logs", {
                "from_time": start_time, "to_time": end_time,
                "completed_qty": delta, "employee": payload.get("employee"),
                "cfg_kanban_progress": progress_ref,
            })
        job_card.save(ignore_permissions=True)
    job_card.reload()
    after_qty = flt(job_card.total_completed_qty)
    expected_qty = before_qty if existing else before_qty + delta
    if after_qty + 0.000001 < expected_qty:
        frappe.throw(f"ERPNext Job Card {job_card.name} quantity verification failed: "
                     f"expected at least {expected_qty}, found {after_qty}")
    auto_submitted = False
    settings = frappe.get_single("CFG Kanban Settings")
    if (settings.get("auto_submit_job_card") and job_card.docstatus == 0 and
            after_qty + 0.000001 >= flt(job_card.for_quantity)):
        job_card.submit()
        job_card.reload()
        auto_submitted = True
        if job_card.status != "Completed":
            frappe.throw(f"ERPNext submitted Job Card {job_card.name}, but its status is {job_card.status}")
    job_card._cfg_command_result = _job_card_result(
        job_card, action="progress_updated", before_qty=before_qty,
        applied_qty=0 if existing else delta, operation_progress=progress_ref,
        duplicate=bool(existing), reject_qty=flt(payload.get("reject_qty")),
        auto_submitted=auto_submitted,
    )
    return job_card


@handler("Complete Job Card")
def complete_job_card(command, payload):
    job_card = frappe.get_doc("Job Card", payload["job_card"])
    if job_card.docstatus == 0:
        if flt(job_card.total_completed_qty) + 0.000001 < flt(job_card.for_quantity):
            frappe.throw(f"Job Card {job_card.name} cannot be completed: ERP completed quantity "
                         f"is {job_card.total_completed_qty} of {job_card.for_quantity}")
        job_card.submit()
    job_card.reload()
    if job_card.status != "Completed":
        frappe.throw(f"ERPNext did not complete Job Card {job_card.name}; current status is {job_card.status}")
    job_card._cfg_command_result = _job_card_result(job_card, action="completed")
    return job_card


def _job_card_result(job_card, action, **details):
    return {
        "doctype": job_card.doctype, "name": job_card.name, "action": action,
        "status": job_card.status, "docstatus": job_card.docstatus,
        "for_quantity": flt(job_card.for_quantity),
        "total_completed_qty": flt(job_card.total_completed_qty),
        "time_log_rows": len(job_card.time_logs), **details,
    }


@handler("Cancel Signal and Rollback")
def cancel_signal_and_rollback(command, payload):
    from cfg_kanban.services.signal_cancellation import cancel_and_rollback

    return cancel_and_rollback(payload["signal"], payload.get("reason"))


@handler("Create Stock Entry")
def create_stock_entry(command, payload):
    doc = frappe.get_doc({"doctype": "Stock Entry", **payload, "cfg_kanban_controlled": 1,
                          "cfg_kanban_cycle": command.kanban_cycle,
                          "cfg_kanban_signal": command.source_signal}).insert(ignore_permissions=True)
    return doc
