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
from cfg_kanban.services.tag_registry import materialize_tag_family_for_code


TOLERANCE = 0.000001
BLOCKED_MOVEMENT_STATES = {
    "Reserved", "Loaded", "Intercompany Transit", "Delivered", "Quarantined", "Empty",
}


@frappe.whitelist()
def get_stock_tag_split_plan(source_handling_unit, operator_session_token=None):
    authorize_stock_retagging(operator_session_token)
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
        "can_split": not problem,
        "blocked_reason": problem,
    }


@frappe.whitelist()
def get_child_tag_split_plan(source_handling_unit, operator_session_token=None):
    authorize_stock_retagging(operator_session_token)
    source = frappe.get_doc("CFG Kanban Handling Unit", source_handling_unit)
    problem = _child_split_problem(source)
    children = []
    if source.tag_family:
        children = frappe.get_all(
            "CFG Kanban Tag Identity",
            filters={
                "parent": source.tag_family,
                "tag_role": "Child",
                "state": "Unused",
            },
            fields=["visible_code", "child_index"],
            order_by="child_index asc",
            limit_page_length=100,
        )
    if not problem and not children:
        problem = _("No unused detachable child tag remains in this Tag Family")
    return {
        "source_handling_unit": source.name,
        "source_tag": source.handling_unit_id,
        "tag_family": source.tag_family,
        "item_code": source.item_code,
        "batch_no": source.batch_no,
        "company": source.inventory_company,
        "warehouse": source.current_warehouse,
        "stock_uom": source.stock_uom,
        "available_qty": flt(source.available_qty),
        "unused_child_tags": children,
        "can_split": not problem,
        "blocked_reason": problem,
    }


@frappe.whitelist()
def split_to_unused_tag(
    source_handling_unit, destination_scan_value, qty, reason, event_token,
    operator_session_token=None,
):
    profile, session = authorize_stock_retagging(operator_session_token, "start")
    reason = (reason or "").strip()
    if not reason:
        frappe.throw(_("Stock-tag split reason is required"))
    if not event_token:
        frappe.throw(_("Event token is required; retry with the same token after a network error"))
    qty = flt(qty)
    if qty <= TOLERANCE:
        frappe.throw(_("Split quantity must be positive"))
    destination_code = normalize_physical_code(destination_scan_value)

    split_key = canonical_key("same-warehouse-tag-split", source_handling_unit, event_token)
    existing_name = frappe.db.get_value(
        "CFG Kanban Handling Unit", {"activation_key": split_key}, "name"
    )
    if existing_name:
        return _existing_split_result(
            split_key, source_handling_unit, destination_code, qty, existing_name
        )

    frappe.db.sql(
        "select name from `tabCFG Kanban Handling Unit` where name=%s for update",
        source_handling_unit,
    )
    source = frappe.get_doc("CFG Kanban Handling Unit", source_handling_unit)
    existing_name = frappe.db.get_value(
        "CFG Kanban Handling Unit", {"activation_key": split_key}, "name"
    )
    if existing_name:
        return _existing_split_result(
            split_key, source.name, destination_code, qty, existing_name
        )
    problem = _unit_problem(source, _("Source"))
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
    destination.identity_state = "Active"
    destination.origin_reference_doctype = "CFG Kanban Handling Unit"
    destination.origin_reference_name = source.name
    destination.origin_reference_row = None
    destination.activation_key = split_key
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
        idempotency_key=canonical_key("same-warehouse-tag-split-ledger", split_key),
        source_handling_unit=source.name,
        destination_handling_unit=destination.name,
        item_code=source.item_code,
        batch_no=source.batch_no,
        source_company=source.inventory_company,
        destination_company=source.inventory_company,
        source_warehouse=source.current_warehouse,
        destination_warehouse=source.current_warehouse,
        reference_doctype="CFG Kanban Handling Unit",
        reference_name=source.name,
        operator=profile.employee if profile else None,
        operator_session=session.name if session else None,
        device_id=event_token,
        reason=f"Same-warehouse split to unused Stock Tag: {reason}",
    )
    source.reload()
    destination.reload()
    if flt(source.current_qty) <= TOLERANCE:
        source.db_set(
            {"identity_state": "Empty", "movement_state": "Empty"},
            update_modified=False,
        )
    record(
        "Stock Tag Split Onsite",
        card=source.kanban_card,
        cycle=source.kanban_cycle,
        handling_unit=destination.name,
        qty=qty,
        reference_doctype=ledger.doctype,
        reference_name=ledger.name,
        device_id=event_token,
        notes=(f"{source.handling_unit_id} -> {destination.handling_unit_id}; "
               f"{qty} {source.stock_uom}; {reason}"),
        system_generated=False,
        ignore_permissions=True,
        operator=profile.employee if profile else None,
        operator_session=session.name if session else None,
    )
    return _result(source.name, destination.name, ledger.name)


@frappe.whitelist()
def split_to_unused_child_tag(
    source_handling_unit, destination_scan_value, qty, reason, event_token,
    operator_session_token=None,
):
    """Move non-serial quantity from a main tag to its preprinted child identity."""
    profile, session = authorize_stock_retagging(operator_session_token, "start")
    reason = (reason or "").strip()
    if not reason:
        frappe.throw(_("Detachable-child split reason is required"))
    if not event_token:
        frappe.throw(_("Event token is required; retry with the same token after a network error"))
    qty = flt(qty)
    if qty <= TOLERANCE:
        frappe.throw(_("Split quantity must be positive"))
    child_code = normalize_physical_code(destination_scan_value)
    split_key = canonical_key(
        "same-warehouse-child-split", source_handling_unit, child_code, event_token
    )
    existing_name = frappe.db.get_value(
        "CFG Kanban Handling Unit", {"activation_key": split_key}, "name"
    )
    if existing_name:
        return _existing_child_split_result(
            split_key, source_handling_unit, child_code, qty, existing_name
        )

    frappe.db.sql(
        "select name from `tabCFG Kanban Handling Unit` where name=%s for update",
        source_handling_unit,
    )
    source = frappe.get_doc("CFG Kanban Handling Unit", source_handling_unit)
    existing_name = frappe.db.get_value(
        "CFG Kanban Handling Unit", {"activation_key": split_key}, "name"
    )
    if existing_name:
        return _existing_child_split_result(
            split_key, source.name, child_code, qty, existing_name
        )
    problem = _child_split_problem(source)
    if problem:
        frappe.throw(problem)
    if qty > flt(source.available_qty) + TOLERANCE:
        frappe.throw(
            _("Quantity {0} exceeds source tag available quantity {1} {2}").format(
                qty, source.available_qty, source.stock_uom
            )
        )
    identity = _validate_unused_child_tag(source, child_code)

    child = frappe.copy_doc(source)
    child.name = None
    child.handling_unit_id = child_code
    child.opaque_token = None
    child.tag_kind = "Child Stock Tag"
    child.parent_handling_unit = source.name
    child.root_handling_unit = source.root_handling_unit or source.name
    child.child_index = identity.get("child_index")
    child.qty = qty
    child.original_qty = qty
    child.current_qty = 0
    child.reserved_qty = 0
    child.available_qty = 0
    child.serial_count = 0
    child.identity_state = "Active"
    child.origin_reference_doctype = "CFG Kanban Handling Unit"
    child.origin_reference_name = source.name
    child.origin_reference_row = None
    child.activation_key = split_key
    child.replacement_of = None
    child.replaced_by = None
    child.void_reason = None
    child.print_revision = 1
    child.print_count = 0
    child.last_printed_on = None
    child.last_printed_by = None
    child.last_scan_time = None
    child.flags.skip_initial_ledger = True
    child.flags.activation_reason = (
        f"Controlled onsite child split from {source.handling_unit_id}: {reason}"
    )
    child.insert(ignore_permissions=True)

    ledger = post_quantity_event(
        event_type="Split",
        qty=qty,
        stock_uom=source.stock_uom,
        idempotency_key=canonical_key("same-warehouse-child-split-ledger", split_key),
        source_handling_unit=source.name,
        destination_handling_unit=child.name,
        item_code=source.item_code,
        batch_no=source.batch_no,
        source_company=source.inventory_company,
        destination_company=source.inventory_company,
        source_warehouse=source.current_warehouse,
        destination_warehouse=source.current_warehouse,
        reference_doctype="CFG Kanban Handling Unit",
        reference_name=source.name,
        operator=profile.employee if profile else None,
        operator_session=session.name if session else None,
        device_id=event_token,
        reason=f"Same-warehouse split to detachable child tag: {reason}",
    )
    source.reload()
    child.reload()
    if flt(source.current_qty) <= TOLERANCE:
        source.db_set(
            {"identity_state": "Empty", "movement_state": "Empty"},
            update_modified=False,
        )
    record(
        "Stock Tag Split to Detachable Child",
        card=source.kanban_card,
        cycle=source.kanban_cycle,
        handling_unit=child.name,
        qty=qty,
        reference_doctype=ledger.doctype,
        reference_name=ledger.name,
        device_id=event_token,
        notes=(f"{source.handling_unit_id} -> {child.handling_unit_id}; "
               f"{qty} {source.stock_uom}; {reason}"),
        system_generated=False,
        ignore_permissions=True,
        operator=profile.employee if profile else None,
        operator_session=session.name if session else None,
    )
    return _result(source.name, child.name, ledger.name)


@frappe.whitelist()
def get_tag_to_tag_transfer_plan(source_handling_unit, operator_session_token=None):
    authorize_stock_retagging(operator_session_token)
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
    source_handling_unit, destination_scan_value, qty, reason, event_token,
    operator_session_token=None,
):
    profile, session = authorize_stock_retagging(operator_session_token, "start")
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
        operator=profile.employee if profile else None,
        operator_session=session.name if session else None,
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
        operator=profile.employee if profile else None,
        operator_session=session.name if session else None,
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


def _existing_split_result(split_key, source_name, destination_code, qty, existing_name):
    destination = frappe.get_doc("CFG Kanban Handling Unit", existing_name)
    if (
        destination.origin_reference_name != source_name
        or destination.handling_unit_id != destination_code
        or abs(flt(destination.original_qty) - qty) > TOLERANCE
    ):
        frappe.throw(
            _("This split retry token was already used with a different tag or quantity. "
              "Refresh and start a new split.")
        )
    if destination.identity_state in ("Void", "Replaced"):
        frappe.throw(
            _("The destination created by this split was later {0}; start a new split "
              "with a new unused tag.").format(destination.identity_state.lower())
        )
    ledger = frappe.db.get_value(
        "CFG Kanban Handling Unit Quantity Ledger",
        {"idempotency_key": canonical_key("same-warehouse-tag-split-ledger", split_key)},
        "name",
    )
    return _result(source_name, destination.name, ledger, idempotent_replay=True)


def _existing_child_split_result(
    split_key, source_name, child_code, qty, existing_name
):
    child = frappe.get_doc("CFG Kanban Handling Unit", existing_name)
    if (
        child.parent_handling_unit != source_name
        or child.handling_unit_id != child_code
        or child.tag_kind != "Child Stock Tag"
        or abs(flt(child.original_qty) - qty) > TOLERANCE
    ):
        frappe.throw(
            _("This child-split retry token was already used with a different tag or "
              "quantity. Refresh and start a new split.")
        )
    if child.identity_state in ("Void", "Replaced"):
        frappe.throw(
            _("The child created by this split was later {0}; start a new split with "
              "another unused child tag.").format(child.identity_state.lower())
        )
    ledger = frappe.db.get_value(
        "CFG Kanban Handling Unit Quantity Ledger",
        {"idempotency_key": canonical_key(
            "same-warehouse-child-split-ledger", split_key
        )},
        "name",
    )
    return _result(source_name, child.name, ledger, idempotent_replay=True)


def _validate_unused_main_tag(visible_code):
    identity = resolve_logistics_scan(visible_code)
    if identity and identity.get("identity_type") == "Handling Unit":
        frappe.throw(
            _("Destination tag {0} is already active. Use Transfer Quantity to Active Tag.").format(
                visible_code
            )
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
        frappe.throw(_("Stock-tag split requires an unused main Stock Tag"))
    if identity.get("state") not in ("Unused", "Unmaterialized"):
        frappe.throw(
            _("Destination tag {0} is {1}").format(visible_code, identity.get("state"))
        )


def _validate_unused_child_tag(source, visible_code):
    identity = resolve_logistics_scan(visible_code)
    if identity and identity.get("identity_type") == "Tag Range Candidate":
        materialize_tag_family_for_code(
            visible_code, identity.get("range_registry")
        )
        identity = resolve_logistics_scan(visible_code)
    if identity and identity.get("identity_type") == "Handling Unit":
        frappe.throw(_("Child tag {0} is already active").format(visible_code))
    if not identity or identity.get("identity_type") != "Registered Tag Identity":
        frappe.throw(
            _("Scan an unused detachable child tag from Tag Family {0}").format(
                source.tag_family
            )
        )
    if identity.get("tag_role") != "Child":
        frappe.throw(_("Destination {0} is not a detachable child tag").format(
            visible_code
        ))
    if identity.get("tag_family") != source.tag_family:
        frappe.throw(
            _("Child tag {0} belongs to Tag Family {1}, not source family {2}").format(
                visible_code, identity.get("tag_family"), source.tag_family
            )
        )
    if identity.get("state") != "Unused" or identity.get("handling_unit"):
        frappe.throw(
            _("Child tag {0} is {1}").format(visible_code, identity.get("state"))
        )
    return identity


def _child_split_problem(source):
    problem = _unit_problem(source, _("Source"))
    if problem:
        return problem
    if source.tag_kind != "Main Stock Tag":
        return _("Only an active main Stock Tag can split to its detachable child")
    if not source.tag_family:
        return _("Source main Stock Tag has no Tag Family")
    if not frappe.db.get_value("CFG Kanban Tag Family", source.tag_family, "active"):
        return _("Source Tag Family {0} is inactive").format(source.tag_family)
    return None


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
