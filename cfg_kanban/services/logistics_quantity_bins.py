"""Controlled partial-quantity fills behind permanent logistics-bin QR codes.

The reusable bin is the floor-facing physical identity.  Quantity remains on an
internal Handling Unit so the ordinary ledger, manifest, delivery and genealogy
controls continue to operate without printing a disposable child tag.
"""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from cfg_kanban.services.container_contents import (
    _authorize,
    _container_result,
    _lock_units,
    _resolve_container,
    _resolve_content,
    active_container_contents,
    active_container_membership,
    assert_container_not_in_open_delivery,
    assert_container_not_in_open_manifest,
)
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import post_quantity_event


TOLERANCE = 0.000001
QUANTITY_BIN_ROLE = "Logistics Quantity Bin"


@frappe.whitelist()
def load_quantity_into_bin(
    container_scan, source_scan, qty, reason, event_token,
    operator_session_token=None,
):
    """Move a partial source-tag balance behind one permanent quantity-bin QR."""
    actor = _authorize(operator_session_token, write=True)
    reason = (reason or "").strip()
    if not reason:
        frappe.throw(_("Loading reason is required"))
    if not event_token:
        frappe.throw(_("A stable scan event token is required"))
    qty = flt(qty)
    if qty <= TOLERANCE:
        frappe.throw(_("Quantity loaded into the bin must be positive"))

    container = _resolve_container(container_scan)
    _assert_quantity_bin(container)
    source = _resolve_content(source_scan, require_active=False)
    load_key = canonical_key(
        "logistics-quantity-bin-load", container.name, source.name, event_token
    )
    existing = frappe.db.get_value(
        "CFG Kanban Handling Unit", {"activation_key": load_key}, "name"
    )
    if existing:
        return _container_result(container, include_history=True)
    _lock_units(container.name, source.name)
    container.reload()
    source.reload()
    existing = frappe.db.get_value(
        "CFG Kanban Handling Unit", {"activation_key": load_key}, "name"
    )
    if existing:
        return _container_result(container, include_history=True)
    _assert_quantity_bin(container)
    assert_container_not_in_open_manifest(container.name, "changing its quantity")
    assert_container_not_in_open_delivery(container.name, "changing its quantity")
    _validate_source(container, source, qty)
    _validate_existing_fill(container, source)

    fill = _new_fill(container, source, qty, load_key)
    ledger = post_quantity_event(
        event_type="Load into Container",
        qty=qty,
        stock_uom=source.stock_uom,
        idempotency_key=canonical_key("logistics-quantity-bin-load-ledger", load_key),
        source_handling_unit=source.name,
        destination_handling_unit=fill.name,
        item_code=source.item_code,
        batch_no=source.batch_no,
        source_company=source.inventory_company,
        destination_company=container.inventory_company,
        source_warehouse=source.current_warehouse,
        destination_warehouse=container.current_warehouse,
        reference_doctype="CFG Kanban Handling Unit",
        reference_name=container.name,
        operator=actor.get("operator"),
        operator_session=actor.get("operator_session"),
        device_id=event_token,
        reason=f"Load partial quantity into permanent logistics bin: {reason}",
    )
    _create_membership(container, fill, source, qty, actor, load_key)
    source.reload()
    if flt(source.current_qty) <= TOLERANCE:
        source.db_set(
            {"identity_state": "Empty", "movement_state": "Empty"},
            update_modified=False,
        )
    container.db_set(
        {"movement_state": "Packed", "last_scan_time": now_datetime()},
        update_modified=False,
    )
    record(
        "Quantity Loaded into Logistics Bin",
        card=source.kanban_card,
        cycle=source.kanban_cycle,
        handling_unit=container.name,
        qty=qty,
        reference_doctype=ledger.doctype,
        reference_name=ledger.name,
        device_id=event_token,
        notes=(
            f"{source.handling_unit_id} -> {container.handling_unit_id}; "
            f"{source.item_code} / {source.batch_no or 'no Batch'} / "
            f"{qty} {source.stock_uom}; {reason}"
        ),
        operator=actor.get("operator"),
        operator_session=actor.get("operator_session"),
        terminal_user=actor.get("terminal_user"),
    )
    container.reload()
    return _container_result(container, include_history=True)


@frappe.whitelist()
def return_quantity_to_source(
    container_scan, content_handling_unit, qty, reason, event_token,
    operator_session_token=None,
):
    """Return an unreserved bin fill to the exact physical source tag."""
    actor = _authorize(operator_session_token, write=True)
    reason = (reason or "").strip()
    if not reason:
        frappe.throw(_("Return reason is required"))
    if not event_token:
        frappe.throw(_("A stable scan event token is required"))
    qty = flt(qty)
    if qty <= TOLERANCE:
        frappe.throw(_("Return quantity must be positive"))

    container = _resolve_container(container_scan)
    _assert_quantity_bin(container)
    membership_row = frappe.db.get_value(
        "CFG Kanban Container Content",
        {
            "container_handling_unit": container.name,
            "content_handling_unit": content_handling_unit,
        },
        ["name", "state"],
        as_dict=True,
    )
    if not membership_row:
        frappe.throw(_("The selected fill is not currently loaded in this quantity bin"))
    membership = membership_row.name
    fill = frappe.get_doc("CFG Kanban Handling Unit", content_handling_unit)
    source_name = fill.origin_reference_name
    if (
        not fill.get("virtual_content")
        or fill.physical_container != container.name
        or fill.origin_reference_doctype != "CFG Kanban Handling Unit"
        or not source_name
        or not frappe.db.exists("CFG Kanban Handling Unit", source_name)
    ):
        frappe.throw(_("This bin fill has no recoverable physical source tag"))

    _lock_units(container.name, fill.name, source_name)
    container.reload()
    fill.reload()
    source = frappe.get_doc("CFG Kanban Handling Unit", source_name)
    assert_container_not_in_open_manifest(container.name, "returning its quantity")
    assert_container_not_in_open_delivery(container.name, "returning its quantity")
    return_key = canonical_key(
        "logistics-quantity-bin-return", membership, source.name, event_token
    )
    if frappe.db.get_value(
        "CFG Kanban Handling Unit Quantity Ledger",
        {"idempotency_key": return_key},
        "name",
    ):
        return _container_result(container, include_history=True)
    if membership_row.state != "Loaded":
        frappe.throw(_("The selected quantity-bin fill has already been returned"))
    _validate_return(container, fill, source, qty)

    ledger = post_quantity_event(
        event_type="Unload from Container",
        qty=qty,
        stock_uom=fill.stock_uom,
        idempotency_key=return_key,
        source_handling_unit=fill.name,
        destination_handling_unit=source.name,
        item_code=fill.item_code,
        batch_no=fill.batch_no,
        source_company=container.inventory_company,
        destination_company=source.inventory_company,
        source_warehouse=container.current_warehouse,
        destination_warehouse=source.current_warehouse,
        reference_doctype="CFG Kanban Container Content",
        reference_name=membership,
        operator=actor.get("operator"),
        operator_session=actor.get("operator_session"),
        device_id=event_token,
        reason=f"Return unused logistics-bin quantity to source tag: {reason}",
    )
    fill.reload()
    source.reload()
    if source.identity_state == "Empty":
        source.db_set(
            {"identity_state": "Active", "movement_state": "Received"},
            update_modified=False,
        )
    if flt(fill.current_qty) <= TOLERANCE:
        fill.db_set(
            {"identity_state": "Empty", "movement_state": "Empty"},
            update_modified=False,
        )
        _close_membership(membership, actor, event_token, reason)
    if not active_container_contents(container.name):
        container.db_set(
            {"movement_state": "Empty", "last_scan_time": now_datetime()},
            update_modified=False,
        )
    record(
        "Quantity Returned from Logistics Bin",
        handling_unit=container.name,
        qty=qty,
        reference_doctype=ledger.doctype,
        reference_name=ledger.name,
        device_id=event_token,
        notes=(
            f"{container.handling_unit_id} -> {source.handling_unit_id}; "
            f"{qty} {fill.stock_uom}; {reason}"
        ),
        operator=actor.get("operator"),
        operator_session=actor.get("operator_session"),
        terminal_user=actor.get("terminal_user"),
    )
    container.reload()
    return _container_result(container, include_history=True)


def _assert_quantity_bin(container):
    if container.reusable_container_role != QUANTITY_BIN_ROLE:
        frappe.throw(_("Scan a reusable container configured as Logistics Quantity Bin"))


def _validate_source(container, source, qty):
    if source.get("virtual_content"):
        frappe.throw(_("A quantity bin must be loaded from a physical Stock Tag"))
    if active_container_membership(source.name):
        frappe.throw(_("Unload the source Stock Tag from its current container first"))
    if source.inventory_company != container.inventory_company:
        frappe.throw(_("Quantity bin and source Stock Tag belong to different Companies"))
    if source.current_warehouse != container.current_warehouse:
        frappe.throw(_("Quantity bin and source Stock Tag are not in the same Warehouse"))
    if source.identity_state != "Active" or source.quality_state != "Released":
        frappe.throw(
            _("Source Stock Tag {0} is {1} / {2}").format(
                source.handling_unit_id, source.identity_state, source.quality_state
            )
        )
    if source.movement_state not in ("At Source", "Packed", "Received", "Returned"):
        frappe.throw(
            _("Source Stock Tag is in movement state {0}").format(source.movement_state)
        )
    if flt(source.reserved_qty):
        frappe.throw(_("Release the source Stock Tag reservation before loading this bin"))
    _assert_source_not_in_open_transaction(source.name)
    if qty > flt(source.available_qty) + TOLERANCE:
        frappe.throw(
            _("Quantity {0} exceeds source available quantity {1} {2}").format(
                qty, source.available_qty, source.stock_uom
            )
        )
    if source.serial_count or frappe.db.exists(
        "CFG Kanban Handling Unit Serial",
        {"handling_unit": source.name, "state": "Active"},
    ):
        frappe.throw(_("Serial-controlled stock requires an exact-serial transfer workflow"))
    if frappe.db.get_value("UOM", source.stock_uom, "must_be_whole_number") and qty % 1:
        frappe.throw(_("UOM {0} requires a whole-number quantity").format(source.stock_uom))


def _validate_existing_fill(container, source):
    for membership in active_container_contents(container.name):
        fill = frappe.get_doc(
            "CFG Kanban Handling Unit", membership.content_handling_unit
        )
        if not fill.get("virtual_content") or fill.physical_container != container.name:
            frappe.throw(
                _("This quantity bin contains an incompatible physical Stock Tag. Empty it first.")
            )
        if (
            fill.item_code != source.item_code
            or (fill.batch_no or "") != (source.batch_no or "")
            or fill.stock_uom != source.stock_uom
        ):
            frappe.throw(
                _("A Logistics Quantity Bin can hold only one Item, Batch and UOM at a time")
            )


def _new_fill(container, source, qty, load_key):
    fill = frappe.get_doc({
        "doctype": "CFG Kanban Handling Unit",
        "handling_unit_id": f"QBIN-FILL-{load_key[:20].upper()}",
        "handling_unit_type": container.handling_unit_type or "Container",
        "tag_kind": "Main Stock Tag",
        "virtual_content": 1,
        "physical_container": container.name,
        "kanban_cycle": source.kanban_cycle,
        "kanban_card": source.kanban_card,
        "item_code": source.item_code,
        "short_description": source.short_description,
        "qty": qty,
        "stock_uom": source.stock_uom,
        "batch_no": source.batch_no,
        "expiry_date": source.expiry_date,
        "work_order": source.work_order,
        "current_operation": source.current_operation,
        "inventory_company": container.inventory_company,
        "current_warehouse": container.current_warehouse,
        "physical_custodian": container.physical_custodian,
        "source_location": source.handling_unit_id,
        "destination_location": container.handling_unit_id,
        "state": "Attached",
        "movement_state": "Packed",
        "origin_reference_doctype": "CFG Kanban Handling Unit",
        "origin_reference_name": source.name,
        "activation_key": load_key,
    })
    fill.flags.skip_initial_ledger = True
    fill.flags.activation_reason = "Internal fill behind permanent Logistics Quantity Bin"
    fill.insert(ignore_permissions=True)
    return fill


def _create_membership(container, fill, source, qty, actor, load_key):
    membership_key = canonical_key("logistics-quantity-bin-membership", load_key)
    existing = frappe.db.get_value(
        "CFG Kanban Container Content", {"load_event_key": membership_key}, "name"
    )
    if existing:
        return frappe.get_doc("CFG Kanban Container Content", existing)
    return frappe.get_doc({
        "doctype": "CFG Kanban Container Content",
        "state": "Loaded",
        "container_handling_unit": container.name,
        "container_visible_code": container.handling_unit_id,
        "content_handling_unit": fill.name,
        "content_visible_code": container.handling_unit_id,
        "item_code": fill.item_code,
        "batch_no": fill.batch_no,
        "qty": qty,
        "stock_uom": fill.stock_uom,
        "company": fill.inventory_company,
        "warehouse": fill.current_warehouse,
        "loaded_on": now_datetime(),
        "loaded_by": actor.get("operator"),
        "loaded_operator_session": actor.get("operator_session"),
        "load_event_key": membership_key,
    }).insert(ignore_permissions=True)


def _validate_return(container, fill, source, qty):
    if fill.physical_container != container.name or not fill.get("virtual_content"):
        frappe.throw(_("The selected content is not an internal fill for this bin"))
    if flt(fill.reserved_qty):
        frappe.throw(_("Release this bin from its open transaction before returning quantity"))
    if qty > flt(fill.available_qty) + TOLERANCE:
        frappe.throw(
            _("Return quantity {0} exceeds bin-fill availability {1} {2}").format(
                qty, fill.available_qty, fill.stock_uom
            )
        )
    for fieldname, label in (
        ("item_code", _("Item")),
        ("batch_no", _("Batch")),
        ("stock_uom", _("Stock UOM")),
        ("inventory_company", _("Company")),
        ("current_warehouse", _("Warehouse")),
    ):
        if (fill.get(fieldname) or "") != (source.get(fieldname) or ""):
            frappe.throw(
                _("The original source tag no longer has the same {0}").format(label)
            )
    if source.tag_kind == "Reusable Container" or source.get("virtual_content"):
        frappe.throw(_("The original source must remain a physical Stock Tag"))
    if source.identity_state not in ("Active", "Empty"):
        frappe.throw(_("The original source tag is not available for return"))
    if flt(source.reserved_qty) or active_container_membership(source.name):
        frappe.throw(_("The original source tag is reserved or loaded in another container"))
    _assert_source_not_in_open_transaction(source.name)


def _assert_source_not_in_open_transaction(source_name):
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
        (source_name,),
    )
    if manifest:
        frappe.throw(
            _("Remove the source Stock Tag from open Manifest {0} first").format(
                manifest[0][0]
            )
        )
    delivery = frappe.db.get_value(
        "CFG Kanban Delivery Allocation",
        {
            "handling_unit": source_name,
            "state": ["in", ["Reserved", "Delivery Pending", "Exception"]],
        },
        "delivery_session",
    )
    if delivery:
        frappe.throw(
            _("Release the source Stock Tag from Delivery Session {0} first").format(
                delivery
            )
        )


def _close_membership(membership, actor, event_token, reason):
    frappe.db.set_value(
        "CFG Kanban Container Content",
        membership,
        {
            "state": "Unloaded",
            "unloaded_on": now_datetime(),
            "unloaded_by": actor.get("operator"),
            "unloaded_operator_session": actor.get("operator_session"),
            "unload_event_key": canonical_key(
                "logistics-quantity-bin-membership-return", membership, event_token
            ),
            "unload_reason": reason,
        },
        update_modified=True,
    )
