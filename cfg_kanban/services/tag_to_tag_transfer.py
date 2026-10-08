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


ALLOWED_ROLES = (
    "Stock User", "Stock Manager", "Manufacturing User", "Manufacturing Manager",
    "System Manager",
)
TOLERANCE = 0.000001
BLOCKED_MOVEMENT_STATES = {
    "Reserved", "Loaded", "Intercompany Transit", "Delivered", "Quarantined", "Empty",
}


@frappe.whitelist()
def get_tag_to_tag_transfer_plan(source_handling_unit):
    frappe.only_for(ALLOWED_ROLES)
    source = frappe.get_doc("CFG Kanban Handling Unit", source_handling_unit)
    problem = _unit_problem(source, _("Source"))
    return {
        "source_handling_unit": source.name,
        "source_tag": source.handling_unit_id,
        "item_code": source.item_code,
        "batch_no": source.batch_no,
        "company": source.inventory_company,
        "warehouse": source.current_warehouse,
        "stock_uom": source.stock_uom,
        "available_qty": flt(source.available_qty),
        "can_transfer": not problem,
        "blocked_reason": problem,
    }


@frappe.whitelist()
def transfer_between_active_tags(
    source_handling_unit, destination_scan_value, qty, reason, event_token
):
    frappe.only_for(ALLOWED_ROLES)
    reason = (reason or "").strip()
    if not reason:
        frappe.throw(_("Tag-to-tag transfer reason is required"))
    if not event_token:
        frappe.throw(_("Event token is required; retry with the same token after a network error"))
    qty = flt(qty)
    if qty <= TOLERANCE:
        frappe.throw(_("Transfer quantity must be positive"))

    identity = resolve_logistics_scan(destination_scan_value)
    if not identity or identity.get("identity_type") != "Handling Unit":
        frappe.throw(
            _("Destination must be an already-active Stock Tag. Use Split / Repack "
              "when assigning a new unused tag.")
        )
    destination_name = identity.get("name")
    if destination_name == source_handling_unit:
        frappe.throw(_("Source and destination tags must be different"))

    transfer_key = canonical_key(
        "tag-to-tag-transfer", source_handling_unit, event_token
    )
    existing_result = _existing_transfer_result(
        transfer_key, source_handling_unit, destination_name, qty
    )
    if existing_result:
        return existing_result

    names = sorted({source_handling_unit, destination_name})
    placeholders = ", ".join(["%s"] * len(names))
    frappe.db.sql(
        f"select name from `tabCFG Kanban Handling Unit` "
        f"where name in ({placeholders}) order by name for update",
        tuple(names),
    )
    source = frappe.get_doc("CFG Kanban Handling Unit", source_handling_unit)
    destination = frappe.get_doc("CFG Kanban Handling Unit", destination_name)
    existing_result = _existing_transfer_result(
        transfer_key, source.name, destination.name, qty
    )
    if existing_result:
        return existing_result
    problem = _transfer_problem(source, destination)
    if problem:
        frappe.throw(problem)
    if qty > flt(source.available_qty) + TOLERANCE:
        frappe.throw(
            _("Quantity {0} exceeds source tag available quantity {1} {2}").format(
                qty, source.available_qty, source.stock_uom
            )
        )

    ledger = post_quantity_event(
        event_type="Merge",
        qty=qty,
        stock_uom=source.stock_uom,
        idempotency_key=transfer_key,
        source_handling_unit=source.name,
        destination_handling_unit=destination.name,
        item_code=source.item_code,
        batch_no=source.batch_no,
        source_company=source.inventory_company,
        destination_company=destination.inventory_company,
        source_warehouse=source.current_warehouse,
        destination_warehouse=destination.current_warehouse,
        reference_doctype="CFG Kanban Handling Unit",
        reference_name=source.name,
        device_id=event_token,
        reason=f"Same-warehouse active-tag quantity transfer: {reason}",
    )
    source.reload()
    destination.reload()
    if flt(source.current_qty) <= TOLERANCE:
        source.db_set(
            {"identity_state": "Empty", "movement_state": "Empty"},
            update_modified=False,
        )
    record(
        "Stock Tag Quantity Transferred",
        card=source.kanban_card,
        cycle=source.kanban_cycle,
        handling_unit=destination.name,
        qty=qty,
        reference_doctype=ledger.doctype,
        reference_name=ledger.name,
        notes=(f"{source.handling_unit_id} -> {destination.handling_unit_id}; "
               f"{qty} {source.stock_uom}; {reason}"),
        system_generated=False,
        ignore_permissions=True,
    )
    return _result(source.name, destination.name, ledger.name)


def _existing_transfer_result(transfer_key, source_name, destination_name, qty):
    existing = frappe.db.get_value(
        "CFG Kanban Handling Unit Quantity Ledger",
        {"idempotency_key": transfer_key},
        ["name", "source_handling_unit", "destination_handling_unit", "stock_qty"],
        as_dict=True,
    )
    if not existing:
        return None
    if (
        existing.source_handling_unit != source_name
        or existing.destination_handling_unit != destination_name
        or abs(flt(existing.stock_qty) - qty) > TOLERANCE
    ):
        frappe.throw(
            _("This transfer retry token was already used with different tags or quantity. "
              "Refresh and start a new transfer.")
        )
    return _result(
        source_name, destination_name, existing.name, idempotent_replay=True
    )


def _transfer_problem(source, destination):
    for unit, label in ((source, _("Source")), (destination, _("Destination"))):
        problem = _unit_problem(unit, label)
        if problem:
            return problem
    matching_fields = (
        ("item_code", _("Item")),
        ("batch_no", _("Batch")),
        ("stock_uom", _("Stock UOM")),
        ("inventory_company", _("Company")),
        ("current_warehouse", _("Warehouse")),
        ("quality_state", _("Quality State")),
        ("current_operation", _("Current Operation")),
        ("movement_state", _("Movement State")),
    )
    for fieldname, label in matching_fields:
        if source.get(fieldname) != destination.get(fieldname):
            return _("Source and destination tags must have the same {0}").format(label)
    return None


def _unit_problem(unit, label):
    if unit.tag_kind == "Reusable Container":
        return _("{0} must be a Stock Tag, not a reusable container").format(label)
    if unit.identity_state != "Active":
        return _("{0} Stock Tag must be Active").format(label)
    if flt(unit.current_qty) <= TOLERANCE:
        return _("{0} Stock Tag must contain a positive quantity").format(label)
    if unit.quality_state != "Released":
        return _("{0} Stock Tag must be quality released").format(label)
    if unit.movement_state in BLOCKED_MOVEMENT_STATES:
        return _("{0} Stock Tag is in blocked movement state {1}").format(
            label, unit.movement_state
        )
    if flt(unit.reserved_qty) > TOLERANCE:
        return _("Release all {0} tag reservations before transferring quantity").format(
            label.lower()
        )
    if unit.serial_count or frappe.db.exists(
        "CFG Kanban Handling Unit Serial",
        {"handling_unit": unit.name, "state": "Active"},
    ):
        return _("Serial-controlled tags require an exact-serial transfer workflow")
    if active_container_membership(unit.name):
        return _("Unload the {0} Stock Tag from its reusable container first").format(
            label.lower()
        )
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
        (unit.name,),
    )
    if manifest:
        return _("Remove the {0} tag from open Manifest {1} first").format(
            label.lower(), manifest[0][0]
        )
    delivery = frappe.db.get_value(
        "CFG Kanban Delivery Allocation",
        {
            "handling_unit": unit.name,
            "state": ["in", ["Reserved", "Delivery Pending", "Exception"]],
        },
        "delivery_session",
    )
    if delivery:
        return _("Release the {0} tag from Delivery Session {1} first").format(
            label.lower(), delivery
        )
    return None


def _result(source_name, destination_name, ledger_name, idempotent_replay=False):
    source = frappe.get_doc("CFG Kanban Handling Unit", source_name)
    destination = frappe.get_doc("CFG Kanban Handling Unit", destination_name)
    return {
        "ledger": ledger_name,
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
