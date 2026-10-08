import frappe
from frappe import _
from frappe.utils import flt

from cfg_kanban.services.container_contents import active_container_membership
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import (
    post_quantity_event,
    resolve_logistics_scan,
)
from cfg_kanban.services.physical_identity import normalize_physical_code
from cfg_kanban.services.retagging_auth import authorize_stock_retagging


TOLERANCE = 0.000001


@frappe.whitelist()
def get_receipt_repack_plan(source_handling_unit, operator_session_token=None):
    authorize_stock_retagging(operator_session_token)
    source = frappe.get_doc("CFG Kanban Handling Unit", source_handling_unit)
    receipt, row = _receipt_origin(source)
    problem = _repack_problem(source, receipt, row)
    return {
        "source_handling_unit": source.name,
        "source_tag": source.handling_unit_id,
        "item_code": source.item_code,
        "batch_no": source.batch_no,
        "company": source.inventory_company,
        "warehouse": source.current_warehouse,
        "stock_uom": source.stock_uom,
        "available_qty": flt(source.available_qty),
        "purchase_receipt": receipt.name,
        "purchase_receipt_row": row.name,
        "can_repack": not problem,
        "blocked_reason": problem,
    }


@frappe.whitelist()
def repack_receipt_quantity(
    source_handling_unit, destination_scan_value, qty, reason,
    operator_session_token=None,
):
    profile, session = authorize_stock_retagging(operator_session_token, "start")
    reason = (reason or "").strip()
    if not reason:
        frappe.throw(_("Split / repack reason is required"))
    qty = flt(qty)
    if qty <= TOLERANCE:
        frappe.throw(_("Split / repack quantity must be positive"))
    destination_code = normalize_physical_code(destination_scan_value)

    frappe.db.sql(
        "select name from `tabCFG Kanban Handling Unit` where name=%s for update",
        source_handling_unit,
    )
    source = frappe.get_doc("CFG Kanban Handling Unit", source_handling_unit)
    receipt, row = _receipt_origin(source)
    problem = _repack_problem(source, receipt, row)
    if problem:
        frappe.throw(problem)
    if destination_code == source.handling_unit_id:
        frappe.throw(_("Destination tag must be different from the source tag"))
    if qty > flt(source.available_qty) + TOLERANCE:
        frappe.throw(
            _("Quantity {0} exceeds source tag available quantity {1} {2}").format(
                qty, source.available_qty, source.stock_uom
            )
        )

    activation_key = canonical_key(
        "receipt-time-repack", source.name, destination_code
    )
    existing = frappe.db.get_value(
        "CFG Kanban Handling Unit", {"activation_key": activation_key}, "name"
    )
    if existing:
        destination = frappe.get_doc("CFG Kanban Handling Unit", existing)
        if destination.identity_state in ("Void", "Replaced"):
            disposition = "voided" if destination.identity_state == "Void" else "replaced"
            detail = destination.void_reason or destination.replaced_by or _("No reason recorded")
            frappe.throw(
                _("Destination tag {0} was already {1} and cannot be reused. "
                  "Recorded detail: {2}. Scan a new unused main tag.").format(
                    destination_code, disposition, detail
                )
            )
        if abs(flt(destination.original_qty) - qty) > TOLERANCE:
            frappe.throw(
                _("Destination tag {0} was already created with {1} {2}; "
                  "the retry quantity cannot change").format(
                    destination_code, destination.original_qty, destination.stock_uom
                )
            )
        return _result(source.name, destination.name, receipt.name, idempotent_replay=True)

    _validate_unused_main_tag(destination_code)
    destination = frappe.copy_doc(source)
    destination.name = None
    destination.handling_unit_id = destination_code
    destination.opaque_token = None
    destination.tag_kind = "Main Stock Tag"
    destination.tag_family = None
    destination.tag_range_registry = None
    destination.parent_handling_unit = None
    destination.root_handling_unit = None
    destination.child_index = 0
    destination.qty = qty
    destination.original_qty = qty
    destination.current_qty = 0
    destination.reserved_qty = 0
    destination.available_qty = 0
    destination.serial_count = 0
    destination.state = "Received"
    destination.identity_state = "Active"
    destination.movement_state = "Received"
    destination.origin_reference_doctype = "CFG Kanban Handling Unit"
    destination.origin_reference_name = source.name
    destination.origin_reference_row = None
    destination.activation_key = activation_key
    destination.replacement_of = None
    destination.replaced_by = None
    destination.void_reason = None
    destination.print_revision = 1
    destination.print_count = 0
    destination.last_printed_on = None
    destination.last_printed_by = None
    destination.last_scan_time = None
    destination.flags.skip_initial_ledger = True
    destination.insert(ignore_permissions=True)

    ledger = post_quantity_event(
        event_type="Split",
        qty=qty,
        stock_uom=source.stock_uom,
        idempotency_key=canonical_key(
            "receipt-time-repack-ledger", source.name, destination.name
        ),
        source_handling_unit=source.name,
        destination_handling_unit=destination.name,
        item_code=source.item_code,
        batch_no=source.batch_no,
        source_company=source.inventory_company,
        destination_company=source.inventory_company,
        source_warehouse=source.current_warehouse,
        destination_warehouse=source.current_warehouse,
        reference_doctype="Purchase Receipt",
        reference_name=receipt.name,
        operator=profile.employee if profile else None,
        operator_session=session.name if session else None,
        reason=f"Receipt-time physical split / repack: {reason}",
    )
    source.reload()
    destination.reload()
    if flt(source.current_qty) <= TOLERANCE:
        source.db_set(
            {"identity_state": "Empty", "movement_state": "Empty"},
            update_modified=False,
        )
    record(
        "Purchase Receipt Stock Tag Split",
        handling_unit=destination.name,
        qty=qty,
        reference_doctype=ledger.doctype,
        reference_name=ledger.name,
        notes=(f"{source.handling_unit_id} -> {destination.handling_unit_id}; "
               f"{qty} {source.stock_uom}; {reason}"),
        system_generated=False,
        ignore_permissions=True,
        operator=profile.employee if profile else None,
        operator_session=session.name if session else None,
    )
    return _result(source.name, destination.name, receipt.name)


def _receipt_origin(unit):
    current = unit
    seen = set()
    for _depth in range(20):
        if current.name in seen:
            frappe.throw(_("Handling Unit origin chain contains a cycle"))
        seen.add(current.name)
        if current.origin_reference_doctype == "Purchase Receipt":
            receipt = frappe.get_doc("Purchase Receipt", current.origin_reference_name)
            row = next(
                (candidate for candidate in receipt.items
                 if candidate.name == current.origin_reference_row),
                None,
            )
            if not row:
                frappe.throw(_("The originating Purchase Receipt Item row no longer exists"))
            return receipt, row
        if current.origin_reference_doctype != "CFG Kanban Handling Unit":
            break
        current = frappe.get_doc(
            "CFG Kanban Handling Unit", current.origin_reference_name
        )
    frappe.throw(
        _("Stock Tag {0} is not descended from a Purchase Receipt activation").format(
            unit.handling_unit_id
        )
    )


def _repack_problem(source, receipt, row):
    if receipt.docstatus != 1:
        return _("The originating Purchase Receipt must remain submitted")
    if source.tag_kind == "Reusable Container":
        return _("Reusable containers do not carry one Item quantity to split")
    if source.identity_state != "Active" or flt(source.current_qty) <= TOLERANCE:
        return _("Source Stock Tag must be Active with a positive quantity")
    if source.quality_state != "Released":
        return _("Source Stock Tag must be quality released")
    if flt(source.reserved_qty) > TOLERANCE:
        return _("Release all source-tag reservations before repacking")
    if source.serial_count or frappe.db.exists(
        "CFG Kanban Handling Unit Serial",
        {"handling_unit": source.name, "state": "Active"},
    ):
        return _("Use Split Exact Serials to Child Tag for serial-controlled material")
    if active_container_membership(source.name):
        return _("Unload the source Stock Tag from its reusable container before repacking")
    manifest = frappe.db.sql(
        """
        select manifest.name
        from `tabCFG Kanban Manifest Line` line
        inner join `tabCFG Kanban Movement Manifest` manifest on manifest.name=line.parent
        where line.handling_unit=%s
          and manifest.state not in ('Received','Billing Pending','Partially Billed','Billed',
                                     'Closed','Cancelled')
        limit 1
        """,
        (source.name,),
    )
    if manifest:
        return _("Remove the source tag from open Manifest {0} before repacking").format(
            manifest[0][0]
        )
    delivery = frappe.db.get_value(
        "CFG Kanban Delivery Allocation",
        {"handling_unit": source.name,
         "state": ["in", ["Reserved", "Delivery Pending", "Exception"]]},
        "delivery_session",
    )
    if delivery:
        return _("Release the source tag from Delivery Session {0} before repacking").format(
            delivery
        )
    accepted_warehouse = row.warehouse or receipt.set_warehouse
    if (source.inventory_company != receipt.company
            or source.current_warehouse != accepted_warehouse):
        return _(
            "Receipt-time repack is limited to the original receiving Company and Warehouse"
        )
    if source.item_code != row.item_code or source.stock_uom != row.stock_uom:
        return _("Source tag no longer matches its originating Purchase Receipt Item")
    if source.movement_state != "Received":
        return _("Receipt-time repack is only available before downstream movement")
    return None


def _validate_unused_main_tag(visible_code):
    identity = resolve_logistics_scan(visible_code)
    if identity and identity.get("identity_type") == "Handling Unit":
        frappe.throw(
            _("Destination tag {0} is already an active Handling Unit").format(visible_code)
        )
    if not identity or identity.get("identity_type") not in (
        "Registered Tag Identity", "Tag Range Candidate"
    ):
        frappe.throw(
            _("Destination tag {0} is not covered by an active Tag Family or Tag Range").format(
                visible_code
            )
        )
    if identity.get("tag_role") != "Main":
        frappe.throw(_("Receipt-time repack requires an unused main Stock Tag"))
    if identity.get("state") not in ("Unused", "Unmaterialized"):
        frappe.throw(
            _("Destination tag {0} is {1}").format(visible_code, identity.get("state"))
        )


def _result(source_name, destination_name, purchase_receipt, idempotent_replay=False):
    source = frappe.get_doc("CFG Kanban Handling Unit", source_name)
    destination = frappe.get_doc("CFG Kanban Handling Unit", destination_name)
    return {
        "purchase_receipt": purchase_receipt,
        "source": {
            "name": source.name,
            "visible_code": source.handling_unit_id,
            "current_qty": flt(source.current_qty),
        },
        "destination": {
            "name": destination.name,
            "visible_code": destination.handling_unit_id,
            "current_qty": flt(destination.current_qty),
        },
        "stock_uom": source.stock_uom,
        "idempotent_replay": idempotent_replay,
    }
