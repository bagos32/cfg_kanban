import json

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, today

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import (
    post_quantity_event,
    resolve_logistics_scan,
    validate_warehouse_company,
)
from cfg_kanban.services.operator_auth import require_operator
from cfg_kanban.services.physical_identity import normalize_physical_code
from cfg_kanban.services.serial_evidence import assign_serials


TOLERANCE = 0.000001
STOCK_ADOPTION_RESPONSIBILITY = "Stock Adoption"
OPEN_CYCLE_STATES = ("New", "Signalled", "Released")


@frappe.whitelist()
def get_existing_stock_adoption_context(warehouse, item_code, batch_no=None,
                                        operator_session_token=None):
    profile, _session = _authorize(operator_session_token)
    company = frappe.db.get_value("Warehouse", warehouse, "company")
    if not company:
        frappe.throw(_("Warehouse {0} does not have a Company").format(warehouse))
    item = frappe.db.get_value(
        "Item", item_code,
        ["item_name", "stock_uom", "is_stock_item", "has_batch_no", "has_serial_no"],
        as_dict=True,
    )
    if not item:
        frappe.throw(_("Item {0} was not found").format(item_code))
    if not cint(item.is_stock_item):
        frappe.throw(
            _("Existing ERP Stock Adoption is only for stock Items. Use the Kanban "
              "operational-inventory workflow for a non-stock Item.")
        )
    if cint(item.has_batch_no) and not batch_no:
        return {
            "company": company, "warehouse": warehouse, "item_code": item_code,
            "item_name": item.item_name, "stock_uom": item.stock_uom,
            "batch_required": True, "serial_controlled": bool(cint(item.has_serial_no)),
            "erp_qty": 0, "active_tagged_qty": 0, "untagged_qty": 0,
            "eligible_cycles": [],
        }
    _validate_batch(item_code, batch_no, bool(cint(item.has_batch_no)))
    erp_qty = _erp_balance(item_code, warehouse, batch_no)
    tagged_qty = _active_tagged_qty(company, warehouse, item_code, batch_no)
    return {
        "company": company,
        "warehouse": warehouse,
        "item_code": item_code,
        "item_name": item.item_name,
        "stock_uom": item.stock_uom,
        "batch_no": batch_no,
        "batch_required": bool(cint(item.has_batch_no)),
        "serial_controlled": bool(cint(item.has_serial_no)),
        "erp_qty": erp_qty,
        "active_tagged_qty": tagged_qty,
        "untagged_qty": max(erp_qty - tagged_qty, 0),
        "tagged_excess_qty": max(tagged_qty - erp_qty, 0),
        "eligible_cycles": _eligible_cycles(company, warehouse, item_code, profile),
    }


@frappe.whitelist()
def adopt_existing_stock(warehouse, item_code, qty, scan_value, adoption_reason,
                         handling_unit_type="Container", batch_no=None, packed_on=None,
                         expiry_date=None, serial_numbers=None, kanban_cycle=None,
                         allocation_reason=None, event_token=None,
                         operator_session_token=None):
    profile, session = _authorize(operator_session_token)
    qty = flt(qty)
    if qty <= 0:
        frappe.throw(_("Adoption quantity must be positive"))
    if not (adoption_reason or "").strip():
        frappe.throw(_("Existing stock adoption requires a reason"))
    if not event_token:
        frappe.throw(_("A stable event token is required"))
    try:
        visible_code = normalize_physical_code(scan_value)
    except ValueError as exc:
        frappe.throw(str(exc))

    key = canonical_key("existing-erp-stock-adoption", warehouse, item_code, visible_code,
                        event_token)
    existing = frappe.db.get_value(
        "CFG Kanban Stock Adoption", {"adoption_key": key}, "name"
    )
    if existing:
        return _result(existing)

    company = frappe.db.get_value("Warehouse", warehouse, "company")
    validate_warehouse_company(warehouse, company)
    _lock_stock_scope(item_code, warehouse)
    item = frappe.db.get_value(
        "Item", item_code,
        ["item_name", "stock_uom", "is_stock_item", "has_batch_no", "has_serial_no"],
        as_dict=True,
    )
    if not item or not cint(item.is_stock_item):
        frappe.throw(_("Existing ERP Stock Adoption requires an ERPNext stock Item"))
    _validate_batch(item_code, batch_no, bool(cint(item.has_batch_no)))
    identity = resolve_logistics_scan(visible_code)
    if identity and identity.get("identity_type") == "Handling Unit":
        frappe.throw(_("Preprinted tag {0} is already active").format(visible_code))
    if not identity or identity.get("identity_type") not in (
        "Registered Tag Identity", "Tag Range Candidate"
    ):
        frappe.throw(
            _("Preprinted tag {0} is not covered by an active Tag Family or Tag Range")
            .format(visible_code)
        )
    if identity.get("tag_role") != "Main":
        frappe.throw(_("Adopt existing stock with an unused main tag, not a child tag"))
    if identity.get("state") not in ("Unused", "Unmaterialized"):
        frappe.throw(_("Preprinted tag {0} is {1}").format(
            visible_code, identity.get("state")
        ))
    if (identity.get("identity_type") == "Registered Tag Identity"
            and identity.get("tag_family")
            and not frappe.db.get_value(
                "CFG Kanban Tag Family", identity.get("tag_family"), "active"
            )):
        frappe.throw(_("Tag Family {0} is inactive").format(identity.get("tag_family")))

    erp_qty = _erp_balance(item_code, warehouse, batch_no)
    tagged_qty = _active_tagged_qty(company, warehouse, item_code, batch_no, lock=True)
    untagged_qty = max(erp_qty - tagged_qty, 0)
    if qty > untagged_qty + TOLERANCE:
        frappe.throw(
            _("Only {0} {1} remains untagged. ERP stock is {2}; active tagged stock is {3}.")
            .format(untagged_qty, item.stock_uom, erp_qty, tagged_qty)
        )

    serials = _parse_serials(serial_numbers)
    _validate_serials(item_code, warehouse, batch_no, qty, serials,
                      bool(cint(item.has_serial_no)))
    packed_on = packed_on or now_datetime()
    expiry_date = expiry_date or (
        frappe.db.get_value("Batch", batch_no, "expiry_date") if batch_no else None
    )
    adoption = frappe.get_doc({
        "doctype": "CFG Kanban Stock Adoption",
        "status": "Pending",
        "company": company,
        "warehouse": warehouse,
        "item_code": item_code,
        "stock_uom": item.stock_uom,
        "batch_no": batch_no,
        "adopted_qty": qty,
        "visible_tag_code": visible_code,
        "handling_unit_type": handling_unit_type or "Container",
        "packed_on": packed_on,
        "expiry_date": expiry_date,
        "erp_qty_at_adoption": erp_qty,
        "tagged_qty_before": tagged_qty,
        "untagged_qty_before": untagged_qty,
        "remaining_untagged_qty": untagged_qty - qty,
        "adoption_reason": adoption_reason.strip(),
        "adopted_by_operator": profile.employee,
        "operator_session": session.name,
        "adopted_on": now_datetime(),
        "adoption_key": key,
    }).insert(ignore_permissions=True)

    unit = frappe.get_doc({
        "doctype": "CFG Kanban Handling Unit",
        "handling_unit_id": visible_code,
        "handling_unit_type": handling_unit_type or "Container",
        "tag_kind": "Main Stock Tag",
        "item_code": item_code,
        "short_description": item.item_name,
        "qty": qty,
        "stock_uom": item.stock_uom,
        "batch_no": batch_no,
        "packed_on": packed_on,
        "expiry_date": expiry_date,
        "inventory_company": company,
        "current_warehouse": warehouse,
        "source_location": warehouse,
        "destination_location": warehouse,
        "state": "Received",
        "movement_state": "Received",
        "origin_reference_doctype": adoption.doctype,
        "origin_reference_name": adoption.name,
        "activation_key": canonical_key("stock-adoption-tag", adoption.name, visible_code),
    })
    unit.flags.activation_reason = "Existing ERP stock adopted into physical Kanban identity"
    unit.insert(ignore_permissions=True)
    if serials:
        assign_serials(unit, serials, adoption.doctype, adoption.name)
    adoption.db_set({"handling_unit": unit.name, "status": "Adopted"}, update_modified=True)
    record(
        "Existing ERP Stock Tag Adopted", handling_unit=unit.name, qty=qty,
        reference_doctype=adoption.doctype, reference_name=adoption.name,
        operator=profile.employee, operator_session=session.name,
        terminal_user=session.terminal_user,
        notes=(f"{item_code} / {batch_no or 'no Batch'} / {warehouse}; "
               f"ERP {erp_qty}; tagged before {tagged_qty}; reason: {adoption_reason}"),
    )
    if kanban_cycle:
        _allocate(adoption.name, kanban_cycle, allocation_reason, profile, session)
    return _result(adoption.name)


@frappe.whitelist()
def allocate_adopted_stock(adoption_name, kanban_cycle, allocation_reason,
                           operator_session_token=None):
    profile, session = _authorize(operator_session_token, supervisor=True)
    _allocate(adoption_name, kanban_cycle, allocation_reason, profile, session)
    return _result(adoption_name)


@frappe.whitelist()
def release_adopted_stock_allocation(adoption_name, reason,
                                     operator_session_token=None):
    profile, session = _authorize(operator_session_token, supervisor=True)
    if not (reason or "").strip():
        frappe.throw(_("Allocation release reason is required"))
    frappe.db.sql(
        "select name from `tabCFG Kanban Stock Adoption` where name=%s for update",
        adoption_name,
    )
    adoption = frappe.get_doc("CFG Kanban Stock Adoption", adoption_name)
    if adoption.status != "Allocated to Cycle" or not adoption.kanban_cycle:
        frappe.throw(_("This Stock Adoption has no active Kanban Cycle allocation"))
    cycle_name = adoption.kanban_cycle
    revision = cint(adoption.allocation_revision or 1)
    post_quantity_event(
        event_type="Unreserve", qty=adoption.cycle_allocated_qty,
        stock_uom=adoption.stock_uom,
        idempotency_key=canonical_key("stock-adoption-allocation-release", adoption.name,
                                      revision),
        source_handling_unit=adoption.handling_unit,
        item_code=adoption.item_code, batch_no=adoption.batch_no,
        source_company=adoption.company, source_warehouse=adoption.warehouse,
        reference_doctype=adoption.doctype, reference_name=adoption.name,
        operator=profile.employee, operator_session=session.name,
        reason=reason.strip(),
    )
    adoption.db_set({
        "status": "Allocation Released", "kanban_cycle": None,
        "cycle_allocated_qty": 0,
        "allocated_by_operator": None, "allocated_on": None,
    }, update_modified=True)
    _refresh_cycle_allocation(cycle_name)
    record(
        "Existing Stock Cycle Allocation Released", cycle=cycle_name,
        handling_unit=adoption.handling_unit, qty=adoption.adopted_qty,
        reference_doctype=adoption.doctype, reference_name=adoption.name,
        operator=profile.employee, operator_session=session.name,
        terminal_user=session.terminal_user, notes=reason.strip(),
    )
    return _result(adoption.name)


def _allocate(adoption_name, cycle_name, reason, profile, session):
    if not cint(profile.get("can_override")):
        frappe.throw(_("Supervisor Override permission is required to allocate existing stock"))
    if not (reason or "").strip():
        frappe.throw(_("Cycle allocation reason is required"))
    frappe.db.sql(
        "select name from `tabCFG Kanban Stock Adoption` where name=%s for update",
        adoption_name,
    )
    frappe.db.sql(
        "select name from `tabCFG Kanban Cycle` where name=%s for update", cycle_name
    )
    adoption = frappe.get_doc("CFG Kanban Stock Adoption", adoption_name)
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    if adoption.status == "Allocated to Cycle" and adoption.kanban_cycle == cycle.name:
        return
    if adoption.status not in ("Adopted", "Allocation Released"):
        frappe.throw(_("Only an unallocated adopted Stock Tag can be assigned to a Cycle"))
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    if master.control_type != "Production":
        frappe.throw(_("Existing finished stock can be allocated only to a Production Cycle"))
    if master.get("production_policy") == "Customer Make-to-Order":
        frappe.throw(_("Customer Make-to-Order policy prohibits existing-stock allocation"))
    if cycle.work_order:
        frappe.throw(
            _("Cycle {0} already has Work Order {1}. Reconcile that ERP document before "
              "using existing stock.").format(cycle.name, cycle.work_order)
        )
    if cycle.status not in OPEN_CYCLE_STATES:
        frappe.throw(_("Cycle {0} is {1} and cannot accept existing stock").format(
            cycle.name, cycle.status
        ))
    expected_warehouse = cycle.destination_warehouse or master.destination_warehouse
    for label, actual, expected in (
        (_("Company"), adoption.company, cycle.company),
        (_("Item"), adoption.item_code, cycle.item_code),
        (_("Stock UOM"), adoption.stock_uom, cycle.stock_uom),
        (_("Warehouse"), adoption.warehouse, expected_warehouse),
    ):
        if (actual or "") != (expected or ""):
            frappe.throw(_("{0} mismatch: adopted stock is {1}; Cycle requires {2}").format(
                label, actual or "(blank)", expected or "(blank)"
            ))
    if cycle.batch_no and (adoption.batch_no or "") != cycle.batch_no:
        frappe.throw(_("Adopted stock Batch does not match the Cycle Batch"))
    allocated = _cycle_allocated_qty(cycle.name)
    target = flt(cycle.effective_cycle_qty or cycle.planned_qty)
    if allocated + flt(adoption.adopted_qty) > target + TOLERANCE:
        frappe.throw(
            _("This allocation would exceed the Cycle target. Split the physical stock to a "
              "smaller tag before allocating it.")
        )
    revision = cint(adoption.allocation_revision) + 1
    post_quantity_event(
        event_type="Reserve", qty=adoption.adopted_qty, stock_uom=adoption.stock_uom,
        idempotency_key=canonical_key("stock-adoption-cycle-allocation", adoption.name,
                                      cycle.name, revision),
        source_handling_unit=adoption.handling_unit,
        item_code=adoption.item_code, batch_no=adoption.batch_no,
        source_company=adoption.company, source_warehouse=adoption.warehouse,
        reference_doctype=adoption.doctype, reference_name=adoption.name,
        operator=profile.employee, operator_session=session.name,
        reason=reason.strip(),
    )
    adoption.db_set({
        "status": "Allocated to Cycle", "kanban_cycle": cycle.name,
        "cycle_allocated_qty": adoption.adopted_qty,
        "allocation_revision": revision,
        "allocation_reason": reason.strip(),
        "allocated_by_operator": profile.employee, "allocated_on": now_datetime(),
    }, update_modified=True)
    _refresh_cycle_allocation(cycle.name)
    record(
        "Existing ERP Stock Allocated to Cycle", cycle=cycle.name,
        handling_unit=adoption.handling_unit, qty=adoption.adopted_qty,
        reference_doctype=adoption.doctype, reference_name=adoption.name,
        operator=profile.employee, operator_session=session.name,
        terminal_user=session.terminal_user, notes=reason.strip(),
    )


def _authorize(token, supervisor=False):
    profile, session = require_operator(token, "override" if supervisor else None)
    responsibilities = {
        row.responsibility for row in profile.responsibilities if row.responsibility
    }
    view_all = bool(
        profile.get("view_all_responsibilities")
        and profile.kanban_role in ("Supervisor", "Development Proxy")
    )
    if not (view_all or STOCK_ADOPTION_RESPONSIBILITY in responsibilities):
        frappe.throw(_("Operator is not assigned to the Stock Adoption responsibility"),
                     frappe.PermissionError)
    return profile, session


def _eligible_cycles(company, warehouse, item_code, profile):
    if not cint(profile.get("can_override")):
        return []
    rows = frappe.get_all(
        "CFG Kanban Cycle",
        filters={
            "company": company, "item_code": item_code,
            "status": ["in", OPEN_CYCLE_STATES], "work_order": ["is", "not set"],
        },
        fields=["name", "kanban_master", "kanban_card", "status", "planned_qty",
                "effective_cycle_qty", "stock_uom", "batch_no", "destination_warehouse"],
        order_by="creation asc", limit_page_length=100,
    )
    result = []
    for row in rows:
        master = frappe.db.get_value(
            "CFG Kanban Master", row.kanban_master,
            ["control_type", "production_policy", "destination_warehouse"], as_dict=True,
        )
        if not master or master.control_type != "Production":
            continue
        if master.production_policy == "Customer Make-to-Order":
            continue
        destination = row.destination_warehouse or master.destination_warehouse
        if destination != warehouse:
            continue
        allocated = _cycle_allocated_qty(row.name)
        target = flt(row.effective_cycle_qty or row.planned_qty)
        row["allocated_qty"] = allocated
        row["remaining_qty"] = max(target - allocated, 0)
        if row.remaining_qty > TOLERANCE:
            result.append(row)
    return result


def _refresh_cycle_allocation(cycle_name):
    allocated = _cycle_allocated_qty(cycle_name)
    target = flt(frappe.db.get_value(
        "CFG Kanban Cycle", cycle_name, "effective_cycle_qty"
    ) or frappe.db.get_value("CFG Kanban Cycle", cycle_name, "planned_qty"))
    status = "Fully Allocated" if allocated >= target - TOLERANCE else (
        "Partially Allocated" if allocated > TOLERANCE else None
    )
    frappe.db.set_value(
        "CFG Kanban Cycle", cycle_name,
        {"existing_stock_allocated_qty": allocated,
         "existing_stock_allocation_status": status},
        update_modified=True,
    )


def _cycle_allocated_qty(cycle_name):
    return flt(frappe.db.sql(
        """
        select coalesce(sum(cycle_allocated_qty), 0)
        from `tabCFG Kanban Stock Adoption`
        where kanban_cycle=%s and status='Allocated to Cycle'
        """,
        cycle_name,
    )[0][0])


def _lock_stock_scope(item_code, warehouse):
    frappe.db.sql(
        "select name from `tabBin` where item_code=%s and warehouse=%s for update",
        (item_code, warehouse),
    )


def _active_tagged_qty(company, warehouse, item_code, batch_no=None, lock=False):
    suffix = " for update" if lock else ""
    rows = frappe.db.sql(
        f"""
        select name, current_qty
        from `tabCFG Kanban Handling Unit`
        where inventory_company=%s and current_warehouse=%s and item_code=%s
          and ifnull(batch_no, '')=%s and tag_kind!='Reusable Container'
          and identity_state='Active'
        order by name{suffix}
        """,
        (company, warehouse, item_code, batch_no or ""), as_dict=True,
    )
    return sum(flt(row.current_qty) for row in rows)


def _erp_balance(item_code, warehouse, batch_no=None):
    if batch_no:
        from erpnext.stock.doctype.batch.batch import get_batch_qty
        return flt(get_batch_qty(
            batch_no=batch_no, warehouse=warehouse, item_code=item_code,
            posting_date=today(), for_stock_levels=True, ignore_reserved_stock=True,
        ))
    return flt(frappe.db.get_value(
        "Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"
    ))


def _validate_batch(item_code, batch_no, required):
    if required and not batch_no:
        frappe.throw(_("Batch is required for this Item"))
    if batch_no and frappe.db.get_value("Batch", batch_no, "item") != item_code:
        frappe.throw(_("Batch {0} does not belong to Item {1}").format(batch_no, item_code))


def _validate_serials(item_code, warehouse, batch_no, qty, serials, required):
    if not required:
        if serials:
            frappe.throw(_("Serial Numbers were supplied for a non-serial Item"))
        return
    count = int(round(qty))
    if count <= 0 or abs(qty - count) > TOLERANCE or len(serials) != count:
        frappe.throw(_("Select exactly {0} Serial Numbers for this Stock Tag").format(count))
    for serial_no in serials:
        serial = frappe.db.get_value(
            "Serial No", serial_no, ["item_code", "batch_no", "warehouse"], as_dict=True
        )
        if not serial or serial.item_code != item_code:
            frappe.throw(_("Serial No {0} does not belong to Item {1}").format(
                serial_no, item_code
            ))
        if serial.warehouse != warehouse:
            frappe.throw(_("Serial No {0} is in {1}, not {2}").format(
                serial_no, serial.warehouse or "(no warehouse)", warehouse
            ))
        if batch_no and serial.batch_no and serial.batch_no != batch_no:
            frappe.throw(_("Serial No {0} belongs to Batch {1}").format(
                serial_no, serial.batch_no
            ))
        if frappe.db.exists("CFG Kanban Handling Unit Serial", {
            "active_serial_key": serial_no,
        }):
            frappe.throw(_("Serial No {0} is already assigned to an active Stock Tag").format(
                serial_no
            ))


def _parse_serials(value):
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        raw = value
    else:
        try:
            raw = json.loads(value) if str(value).strip().startswith("[") else str(value).splitlines()
        except (TypeError, ValueError):
            raw = str(value).splitlines()
    return list(dict.fromkeys(str(row).strip() for row in raw if str(row).strip()))


def _result(adoption_name):
    doc = frappe.get_doc("CFG Kanban Stock Adoption", adoption_name)
    result = doc.as_dict()
    if doc.handling_unit:
        result["handling_unit_details"] = frappe.get_doc(
            "CFG Kanban Handling Unit", doc.handling_unit
        ).as_dict()
    return result
