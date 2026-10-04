import frappe
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime

from cfg_kanban.services.container_contents import (
    active_container_contents,
    active_container_membership,
)
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import resolve_logistics_scan
from cfg_kanban.services.operator_auth import require_operator


RECONCILIATION_RESPONSIBILITY = "Logistics Reconciliation"
OPEN_STATES = ("Counting", "Variance", "Ready to Close")
EPSILON = 0.000001
CORRECTION_DOCTYPES = {
    "Stock Reconciliation", "Stock Entry", "Delivery Note", "Purchase Receipt"
}


@frappe.whitelist()
def get_reconciliation_console(operator_session_token):
    profile, _session = require_operator(operator_session_token)
    if not _authorized(profile):
        return {"vehicle_warehouses": [], "open_reconciliations": [],
                "recent_reconciliations": [], "can_reconcile": False}
    warehouses = frappe.get_all(
        "Warehouse",
        filters={"disabled": 0, "is_group": 0, "cfg_is_vehicle_warehouse": 1},
        fields=["name", "company", "cfg_vehicle_reference"],
        order_by="company asc, cfg_vehicle_reference asc, name asc",
        limit_page_length=500,
    )
    fields = [
        "name", "state", "company", "vehicle_warehouse", "vehicle_reference",
        "period_start", "period_end", "expected_line_count", "counted_line_count",
        "variance_line_count", "variance_exception", "modified",
    ]
    return {
        "vehicle_warehouses": warehouses,
        "open_reconciliations": frappe.get_all(
            "CFG Kanban Route Reconciliation",
            filters={"state": ["in", OPEN_STATES]}, fields=fields,
            order_by="period_start desc", limit_page_length=100,
        ),
        "recent_reconciliations": frappe.get_all(
            "CFG Kanban Route Reconciliation",
            filters={"state": ["in", ("Closed", "Cancelled")]}, fields=fields,
            order_by="modified desc", limit_page_length=10,
        ),
        "can_reconcile": True,
    }


@frappe.whitelist()
def start_route_reconciliation(company, vehicle_warehouse, event_token,
                               operator_session_token):
    profile, session = require_operator(operator_session_token, "start")
    _require_authorized(profile)
    if not event_token:
        frappe.throw(_("A stable event token is required"))
    _validate_vehicle_warehouse(company, vehicle_warehouse)
    frappe.db.sql(
        "select name from `tabWarehouse` where name=%s for update", vehicle_warehouse
    )
    key = canonical_key("route-reconciliation-open", vehicle_warehouse, event_token)
    existing = frappe.db.get_value(
        "CFG Kanban Route Reconciliation", {"idempotency_key": key}, "name"
    )
    if existing:
        return get_route_reconciliation(existing, operator_session_token)
    open_name = frappe.db.get_value(
        "CFG Kanban Route Reconciliation",
        {"vehicle_warehouse": vehicle_warehouse, "state": ["in", OPEN_STATES]},
        "name",
    )
    if open_name:
        return get_route_reconciliation(open_name, operator_session_token)

    opened_on = now_datetime()
    vehicle_reference = frappe.db.get_value(
        "Warehouse", vehicle_warehouse, "cfg_vehicle_reference"
    )
    doc = frappe.get_doc({
        "doctype": "CFG Kanban Route Reconciliation",
        "state": "Counting",
        "company": company,
        "vehicle_warehouse": vehicle_warehouse,
        "vehicle_reference": vehicle_reference,
        "period_start": opened_on,
        "opened_by_operator": profile.employee,
        "opened_operator_session": session.name,
        "idempotency_key": key,
    })
    opening = _erp_balances(company, vehicle_warehouse, opened_on)
    _replace_lines(doc, opening, opening)
    doc.insert(ignore_permissions=True)
    record(
        "Route Reconciliation Started", route_reconciliation=doc.name,
        previous_state=None, new_state="Counting", reference_doctype=doc.doctype,
        reference_name=doc.name, device_id=event_token, operator=profile.employee,
        operator_session=session.name, terminal_user=session.terminal_user,
        notes=f"{company} / {vehicle_warehouse} / {vehicle_reference}",
    )
    return _result(doc, profile)


@frappe.whitelist()
def get_route_reconciliation(reconciliation_name, operator_session_token):
    profile, _session = require_operator(operator_session_token)
    _require_authorized(profile)
    return _result(frappe.get_doc("CFG Kanban Route Reconciliation", reconciliation_name), profile)


@frappe.whitelist()
def scan_reconciliation_tag(reconciliation_name, scan_value, event_token,
                            operator_session_token):
    profile, session = require_operator(operator_session_token, "start")
    _require_authorized(profile)
    if not event_token:
        frappe.throw(_("A stable scan event token is required"))
    doc = _locked_reconciliation(reconciliation_name)
    _require_counting(doc)
    resolved = resolve_logistics_scan(scan_value)
    if not resolved or resolved.get("identity_type") != "Handling Unit":
        frappe.throw(_("Scan an activated Handling Unit or reusable-container code"))
    scanned_unit = frappe.get_doc("CFG Kanban Handling Unit", resolved["name"])
    units = []
    if scanned_unit.tag_kind == "Reusable Container":
        if (
            scanned_unit.identity_state != "Active"
            or scanned_unit.inventory_company != doc.company
            or scanned_unit.current_warehouse != doc.vehicle_warehouse
        ):
            frappe.throw(_("Reusable Container {0} is not active in this Company/Warehouse").format(
                scanned_unit.handling_unit_id
            ))
        contents = active_container_contents(scanned_unit.name)
        if not contents:
            frappe.throw(_("Reusable Container {0} is empty").format(
                scanned_unit.handling_unit_id
            ))
        for content in contents:
            units.append((
                frappe.get_doc("CFG Kanban Handling Unit", content.content_handling_unit),
                scanned_unit,
            ))
    else:
        units.append((scanned_unit, None))

    current = {row.handling_unit: row.scan_event_key for row in doc.scans}
    requested_keys = {
        unit.name: canonical_key(
            "route-reconciliation-scan", doc.name, unit.name, event_token
        )
        for unit, _container in units
    }
    if all(current.get(unit.name) == requested_keys[unit.name] for unit, _container in units):
        return _result(doc, profile)
    for unit, container in units:
        _validate_counted_unit(unit, doc, expected_container=container)
        if unit.name in current:
            frappe.throw(_("Tag {0} is already counted in {1}").format(
                unit.handling_unit_id, doc.name
            ))
    scanned_on = now_datetime()
    for unit, container in units:
        doc.append("scans", {
            "handling_unit": unit.name,
            "visible_code": unit.handling_unit_id,
            "container_handling_unit": container.name if container else None,
            "container_visible_code": container.handling_unit_id if container else None,
            "item_code": unit.item_code,
            "batch_no": unit.batch_no,
            "qty": unit.current_qty,
            "stock_uom": unit.stock_uom,
            "scanned_on": scanned_on,
            "scanned_by": profile.employee,
            "operator_session": session.name,
            "scan_event_key": requested_keys[unit.name],
        })
    doc.state = "Counting"
    _refresh_lines(doc)
    doc.save(ignore_permissions=True)
    record(
        "Route Reconciliation Tag Counted", route_reconciliation=doc.name,
        handling_unit=scanned_unit.name,
        qty=sum(flt(unit.current_qty) for unit, _container in units),
        reference_doctype=doc.doctype, reference_name=doc.name,
        device_id=event_token, operator=profile.employee,
        operator_session=session.name, terminal_user=session.terminal_user,
        notes=(f"{scanned_unit.handling_unit_id}; "
               f"{len(units)} physical stock tag(s) counted"),
    )
    return _result(doc, profile)


@frappe.whitelist()
def remove_reconciliation_scan(reconciliation_name, handling_unit,
                               operator_session_token):
    profile, session = require_operator(operator_session_token, "start")
    _require_authorized(profile)
    doc = _locked_reconciliation(reconciliation_name)
    _require_counting(doc)
    matched = next((row for row in doc.scans if row.handling_unit == handling_unit), None)
    if not matched:
        frappe.throw(_("The selected tag is not part of this physical count"))
    remove_names = {matched.handling_unit}
    if matched.container_handling_unit:
        remove_names = {
            row.handling_unit for row in doc.scans
            if row.container_handling_unit == matched.container_handling_unit
        }
    doc.set("scans", [row for row in doc.scans if row.handling_unit not in remove_names])
    doc.state = "Counting"
    _refresh_lines(doc)
    doc.save(ignore_permissions=True)
    record(
        "Route Reconciliation Count Removed", route_reconciliation=doc.name,
        handling_unit=handling_unit, reference_doctype=doc.doctype,
        reference_name=doc.name, operator=profile.employee,
        operator_session=session.name, terminal_user=session.terminal_user,
        notes=f"Removed {len(remove_names)} counted tag(s) before closure",
    )
    return _result(doc, profile)


@frappe.whitelist()
def save_loose_counts(reconciliation_name, counts, operator_session_token):
    profile, session = require_operator(operator_session_token, "start")
    _require_authorized(profile)
    doc = _locked_reconciliation(reconciliation_name)
    _require_counting(doc)
    rows = frappe.parse_json(counts) if isinstance(counts, str) else counts
    rows = rows or []
    loose = {}
    for index, row in enumerate(rows, 1):
        item_code = (row.get("item_code") or "").strip()
        batch_no = (row.get("batch_no") or "").strip()
        qty = flt(row.get("qty"))
        if not item_code or not frappe.db.exists("Item", item_code):
            frappe.throw(_("Loose-count row {0}: select a valid Item").format(index))
        if qty < 0:
            frappe.throw(_("Loose-count row {0}: quantity cannot be negative").format(index))
        if batch_no:
            batch_item = frappe.db.get_value("Batch", batch_no, "item")
            if batch_item != item_code:
                frappe.throw(_("Batch {0} does not belong to Item {1}").format(
                    batch_no, item_code
                ))
        stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
        if frappe.db.get_value("UOM", stock_uom, "must_be_whole_number") and qty != int(qty):
            frappe.throw(_("{0} must be counted in whole {1}").format(item_code, stock_uom))
        key = (item_code, batch_no)
        loose[key] = loose.get(key, 0) + qty
    _refresh_lines(doc, loose_override=loose)
    doc.state = "Counting"
    doc.save(ignore_permissions=True)
    record(
        "Route Reconciliation Loose Count Saved", route_reconciliation=doc.name,
        reference_doctype=doc.doctype, reference_name=doc.name,
        operator=profile.employee, operator_session=session.name,
        terminal_user=session.terminal_user,
        notes=f"{len(loose)} Item/Batch loose-count row(s)",
    )
    return _result(doc, profile)


@frappe.whitelist()
def evaluate_route_reconciliation(reconciliation_name, operator_session_token):
    profile, session = require_operator(operator_session_token, "complete")
    _require_authorized(profile)
    doc = _locked_reconciliation(reconciliation_name)
    if doc.state == "Closed":
        return _result(doc, profile)
    _require_counting(doc)
    _validate_scan_snapshot(doc)
    previous_state = doc.state
    _refresh_lines(doc, evaluated_on=now_datetime())
    if any(abs(flt(row.variance_qty)) > EPSILON for row in doc.lines):
        doc.state = "Variance"
        _ensure_variance_exception(doc)
    else:
        doc.state = "Ready to Close"
    doc.save(ignore_permissions=True)
    record(
        "Route Reconciliation Evaluated", route_reconciliation=doc.name,
        previous_state=previous_state, new_state=doc.state,
        qty=0, reference_doctype=doc.doctype,
        reference_name=doc.name, operator=profile.employee,
        operator_session=session.name, terminal_user=session.terminal_user,
        notes=("Physical count matches ERPNext" if doc.state == "Ready to Close"
               else f"{doc.variance_line_count} Item/Batch variance line(s) require supervisor resolution"),
    )
    return _result(doc, profile)


@frappe.whitelist()
def close_route_reconciliation(reconciliation_name, resolution_notes=None,
                               correction_reference_doctype=None,
                               correction_reference=None,
                               operator_session_token=None):
    profile, session = require_operator(operator_session_token, "complete")
    _require_authorized(profile)
    doc = _locked_reconciliation(reconciliation_name)
    if doc.state == "Closed":
        return _result(doc, profile)
    _require_counting(doc)
    _validate_scan_snapshot(doc)
    _refresh_lines(doc, evaluated_on=now_datetime())
    if any(abs(flt(row.variance_qty)) > EPSILON for row in doc.lines):
        doc.state = "Variance"
        _ensure_variance_exception(doc)
        doc.save(ignore_permissions=True)
        return _result(doc, profile)
    if doc.variance_exception and not (resolution_notes or "").strip():
        frappe.throw(_("Recount / Resolution Notes are required after a variance"))
    if bool(correction_reference_doctype) != bool(correction_reference):
        frappe.throw(_("Correction Reference Type and Correction Reference must be supplied together"))
    if correction_reference_doctype and correction_reference_doctype not in CORRECTION_DOCTYPES:
        frappe.throw(_("Select an approved ERP stock correction or movement document type"))
    if correction_reference and not frappe.db.exists(
        correction_reference_doctype, correction_reference
    ):
        frappe.throw(_("Correction reference {0} {1} was not found").format(
            correction_reference_doctype, correction_reference
        ))
    _assert_no_open_vehicle_work(doc)
    closed_on = now_datetime()
    doc.state = "Closed"
    doc.closed_by_operator = profile.employee
    doc.closed_operator_session = session.name
    doc.closed_on = closed_on
    doc.resolution_notes = (resolution_notes or "").strip()
    doc.correction_reference_doctype = correction_reference_doctype
    doc.correction_reference = correction_reference
    if doc.variance_exception:
        doc.resolved_by = frappe.session.user
        doc.resolved_on = closed_on
        frappe.db.set_value(
            "CFG Kanban Exception", doc.variance_exception,
            {"status": "Resolved", "resolved_on": closed_on,
             "resolved_by": frappe.session.user,
             "resolution": doc.resolution_notes}, update_modified=True,
        )
    doc.save(ignore_permissions=True)
    for row in doc.scans:
        frappe.db.set_value(
            "CFG Kanban Handling Unit", row.handling_unit,
            "last_reconciled_on", closed_on, update_modified=False,
        )
    record(
        "Route Reconciliation Closed", route_reconciliation=doc.name,
        previous_state="Ready to Close", new_state="Closed",
        reference_doctype=doc.doctype, reference_name=doc.name,
        operator=profile.employee, operator_session=session.name,
        terminal_user=session.terminal_user,
        notes=doc.resolution_notes or "Balanced count closed",
    )
    return _result(doc, profile)


@frappe.whitelist()
def cancel_route_reconciliation(reconciliation_name, reason,
                                operator_session_token):
    profile, session = require_operator(operator_session_token, "override")
    _require_authorized(profile)
    if not profile.get("can_override"):
        frappe.throw(_("Supervisor override permission is required"))
    if not (reason or "").strip():
        frappe.throw(_("Cancellation Reason is required"))
    doc = _locked_reconciliation(reconciliation_name)
    if doc.state == "Cancelled":
        return _result(doc, profile)
    if doc.state not in OPEN_STATES:
        frappe.throw(_("Only an open Route Reconciliation can be cancelled"))
    previous = doc.state
    doc.state = "Cancelled"
    doc.cancellation_reason = reason.strip()
    doc.closed_by_operator = profile.employee
    doc.closed_operator_session = session.name
    doc.closed_on = now_datetime()
    doc.save(ignore_permissions=True)
    if doc.variance_exception:
        frappe.db.set_value(
            "CFG Kanban Exception", doc.variance_exception,
            {"status": "Cancelled", "resolved_on": doc.closed_on,
             "resolved_by": frappe.session.user,
             "resolution": f"Reconciliation cancelled: {reason.strip()}"},
            update_modified=True,
        )
    record(
        "Route Reconciliation Cancelled", route_reconciliation=doc.name,
        previous_state=previous, new_state="Cancelled",
        reference_doctype=doc.doctype, reference_name=doc.name,
        operator=profile.employee, operator_session=session.name,
        terminal_user=session.terminal_user, notes=reason.strip(),
    )
    return _result(doc, profile)


def _authorized(profile):
    responsibilities = {
        row.responsibility for row in profile.responsibilities if row.responsibility
    }
    return (
        RECONCILIATION_RESPONSIBILITY in responsibilities
        or bool(profile.get("view_all_responsibilities") and
                profile.kanban_role in ("Supervisor", "Development Proxy"))
    )


def _require_authorized(profile):
    if not _authorized(profile):
        frappe.throw(_("Operator is not assigned to Logistics Reconciliation"))


def _validate_vehicle_warehouse(company, warehouse):
    row = frappe.db.get_value(
        "Warehouse", warehouse,
        ["company", "disabled", "is_group", "cfg_is_vehicle_warehouse",
         "cfg_vehicle_reference"], as_dict=True,
    )
    if not row or row.company != company:
        frappe.throw(_("Select a Vehicle Warehouse belonging to the selected Company"))
    if row.disabled or row.is_group or not row.cfg_is_vehicle_warehouse:
        frappe.throw(_("Select an active non-group Warehouse marked as Vehicle Warehouse"))
    if not row.cfg_vehicle_reference:
        frappe.throw(_("The Vehicle Warehouse needs a Physical Vehicle Reference"))


def _locked_reconciliation(name):
    frappe.db.sql(
        "select name from `tabCFG Kanban Route Reconciliation` where name=%s for update",
        name,
    )
    return frappe.get_doc("CFG Kanban Route Reconciliation", name)


def _require_counting(doc):
    if doc.state not in OPEN_STATES:
        frappe.throw(_("Route Reconciliation {0} is {1}").format(doc.name, doc.state))


def _validate_counted_unit(unit, doc, expected_container=None):
    if unit.tag_kind == "Reusable Container":
        frappe.throw(_("Count the Stock Tags inside the reusable container"))
    if unit.inventory_company != doc.company or unit.current_warehouse != doc.vehicle_warehouse:
        frappe.throw(_("Tag {0} belongs to {1} / {2}, not this count").format(
            unit.handling_unit_id, unit.inventory_company, unit.current_warehouse
        ))
    if unit.identity_state != "Active" or flt(unit.current_qty) <= 0:
        frappe.throw(_("Tag {0} is {1} with no countable quantity").format(
            unit.handling_unit_id, unit.identity_state
        ))
    membership = active_container_membership(unit.name)
    if expected_container:
        if not membership or membership.container_handling_unit != expected_container.name:
            frappe.throw(_("Container contents changed during the count; scan it again"))
    elif membership:
        frappe.throw(_("Tag {0} is inside reusable container {1}; scan the container instead").format(
            unit.handling_unit_id, membership.container_visible_code
        ))


def _assert_no_open_vehicle_work(doc):
    delivery = frappe.db.get_value(
        "CFG Kanban Delivery Session",
        {"selling_company": doc.company, "source_warehouse": doc.vehicle_warehouse,
         "state": ["not in", ("Closed", "Cancelled")]},
        "name",
    )
    if delivery:
        frappe.throw(_("Complete or cancel open Customer Delivery Session {0} before route closure").format(
            delivery
        ))
    manifests = frappe.db.sql(
        """
        select name
        from `tabCFG Kanban Movement Manifest`
        where (source_warehouse=%s or destination_warehouse=%s)
          and state not in ('Received','Billing Pending','Partially Billed','Billed',
                            'Closed','Cancelled')
        limit 1
        """,
        (doc.vehicle_warehouse, doc.vehicle_warehouse),
    )
    if manifests:
        frappe.throw(_("Complete, receive, resolve, or cancel open Movement Manifest {0} before route closure").format(
            manifests[0][0]
        ))


def _validate_scan_snapshot(doc):
    for row in doc.scans:
        unit = frappe.get_doc("CFG Kanban Handling Unit", row.handling_unit)
        if (
            unit.identity_state != "Active"
            or unit.inventory_company != doc.company
            or unit.current_warehouse != doc.vehicle_warehouse
            or abs(flt(unit.current_qty) - flt(row.qty)) > EPSILON
        ):
            frappe.throw(_("Counted tag {0} changed after scanning. Remove it and count the current physical state again.").format(
                row.visible_code
            ))
        membership = active_container_membership(unit.name)
        if row.container_handling_unit:
            if not membership or membership.container_handling_unit != row.container_handling_unit:
                frappe.throw(_("Container membership for tag {0} changed after scanning. Remove and rescan the container.").format(
                    row.visible_code
                ))
        elif membership:
            frappe.throw(_("Counted tag {0} was loaded into container {1} after scanning. Remove and rescan the container.").format(
                row.visible_code, membership.container_visible_code
            ))


def _refresh_lines(doc, loose_override=None, evaluated_on=None):
    opening = {
        (row.item_code, row.batch_no or ""): flt(row.opening_qty)
        for row in doc.lines
    }
    if loose_override is None:
        loose = {
            (row.item_code, row.batch_no or ""): flt(row.loose_count_qty)
            for row in doc.lines if flt(row.loose_count_qty)
        }
    else:
        loose = loose_override
    closing_on = evaluated_on or now_datetime()
    expected = _erp_balances(doc.company, doc.vehicle_warehouse, closing_on)
    _replace_lines(doc, opening, expected, loose)
    if evaluated_on:
        doc.period_end = evaluated_on


def _replace_lines(doc, opening, expected, loose=None):
    loose = loose or {}
    tagged = {}
    for scan in doc.scans:
        key = (scan.item_code, scan.batch_no or "")
        tagged[key] = tagged.get(key, 0) + flt(scan.qty)
    keys = sorted(set(opening) | set(expected) | set(loose) | set(tagged))
    doc.set("lines", [])
    for item_code, batch_no in keys:
        opening_qty = flt(opening.get((item_code, batch_no)))
        expected_qty = flt(expected.get((item_code, batch_no)))
        tagged_qty = flt(tagged.get((item_code, batch_no)))
        loose_qty = flt(loose.get((item_code, batch_no)))
        counted_qty = tagged_qty + loose_qty
        doc.append("lines", {
            "item_code": item_code,
            "batch_no": batch_no or None,
            "stock_uom": frappe.db.get_value("Item", item_code, "stock_uom"),
            "opening_qty": opening_qty,
            "movement_qty": expected_qty - opening_qty,
            "expected_closing_qty": expected_qty,
            "tagged_count_qty": tagged_qty,
            "loose_count_qty": loose_qty,
            "counted_qty": counted_qty,
            "variance_qty": counted_qty - expected_qty,
        })


def _erp_balances(company, warehouse, at_datetime):
    moment = get_datetime(at_datetime)
    sle_meta = frappe.get_meta("Stock Ledger Entry")
    cancel_clause = " and ifnull(sle.is_cancelled, 0)=0" \
        if sle_meta.has_field("is_cancelled") else ""
    batch_expression = "ifnull(sle.batch_no, '')" \
        if sle_meta.has_field("batch_no") else "''"
    bundle_clause = " and ifnull(sle.serial_and_batch_bundle, '')=''" \
        if sle_meta.has_field("serial_and_batch_bundle") else ""
    params = (company, warehouse, moment.date(), moment.date(), moment.time(), EPSILON)
    rows = frappe.db.sql(
        f"""
        select sle.item_code, {batch_expression} as batch_no,
               sum(sle.actual_qty) as qty
        from `tabStock Ledger Entry` sle
        where sle.company=%s and sle.warehouse=%s
          and (sle.posting_date < %s or
               (sle.posting_date=%s and sle.posting_time <= %s))
          {cancel_clause}
          {bundle_clause}
        group by sle.item_code, {batch_expression}
        having abs(sum(sle.actual_qty)) > %s
        """,
        params,
        as_dict=True,
    )
    balances = {(row.item_code, row.batch_no or ""): flt(row.qty) for row in rows}

    # ERPNext v15 may keep batch quantities in Serial and Batch Bundle children
    # rather than the legacy Stock Ledger Entry.batch_no column. Read both forms,
    # excluding bundled rows from the direct query above so quantities cannot double count.
    if (
        sle_meta.has_field("serial_and_batch_bundle")
        and frappe.db.table_exists("Serial and Batch Entry")
    ):
        bundle_rows = frappe.db.sql(
            f"""
            select sle.item_code, ifnull(entry.batch_no, '') as batch_no,
                   sum(entry.qty) as qty
            from `tabStock Ledger Entry` sle
            inner join `tabSerial and Batch Bundle` bundle
                    on bundle.name=sle.serial_and_batch_bundle
            inner join `tabSerial and Batch Entry` entry
                    on entry.parent=bundle.name
            where sle.company=%s and sle.warehouse=%s
              and (sle.posting_date < %s or
                   (sle.posting_date=%s and sle.posting_time <= %s))
              {cancel_clause}
            group by sle.item_code, ifnull(entry.batch_no, '')
            having abs(sum(entry.qty)) > %s
            """,
            params,
            as_dict=True,
        )
        for row in bundle_rows:
            key = (row.item_code, row.batch_no or "")
            balances[key] = balances.get(key, 0) + flt(row.qty)
    return {key: qty for key, qty in balances.items() if abs(qty) > EPSILON}


def _ensure_variance_exception(doc):
    lines = [
        f"{row.item_code}/{row.batch_no or 'No Batch'}: {flt(row.variance_qty)} {row.stock_uom}"
        for row in doc.lines if abs(flt(row.variance_qty)) > EPSILON
    ]
    message = (
        f"Vehicle Warehouse {doc.vehicle_warehouse} physical count differs from ERPNext. "
        + "; ".join(lines[:20])
    )
    if doc.variance_exception and frappe.db.exists(
        "CFG Kanban Exception", doc.variance_exception
    ):
        frappe.db.set_value(
            "CFG Kanban Exception", doc.variance_exception,
            {"status": "Open", "message": message}, update_modified=True,
        )
        return
    exception = frappe.get_doc({
        "doctype": "CFG Kanban Exception",
        "exception_type": "Route Stock Variance",
        "severity": "Critical",
        "status": "Open",
        "route_reconciliation": doc.name,
        "message": message,
        "reference_doctype": doc.doctype,
        "reference_name": doc.name,
        "raised_on": now_datetime(),
    }).insert(ignore_permissions=True)
    doc.variance_exception = exception.name


def _result(doc, profile):
    doc.reload()
    result = doc.as_dict()
    result["can_override"] = bool(profile.get("can_override"))
    result["can_count"] = doc.state in OPEN_STATES
    result["can_close"] = doc.state == "Ready to Close"
    return result
