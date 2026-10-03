import frappe
from frappe import _
from frappe.utils import flt

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import post_quantity_event, resolve_logistics_scan
from cfg_kanban.services.physical_identity import normalize_physical_code
from cfg_kanban.services.serial_evidence import (
    active_serials_for_unit,
    merge_child_serials,
    transfer_selected_serials,
)
from cfg_kanban.services.tag_registry import materialize_tag_family_for_code


TOLERANCE = 0.000001


@frappe.whitelist()
def get_serial_split_plan(parent_handling_unit):
    parent = frappe.get_doc("CFG Kanban Handling Unit", parent_handling_unit)
    parent.check_permission("write")
    if not frappe.has_permission("CFG Kanban Handling Unit", ptype="create"):
        frappe.throw(_("You do not have permission to activate Handling Units"),
                     frappe.PermissionError)
    serials = active_serials_for_unit(parent.name)
    problem = _serial_split_problem(parent, serials)
    children = frappe.get_all(
        "CFG Kanban Tag Identity",
        filters={"parent": parent.tag_family, "tag_role": "Child", "state": "Unused"},
        fields=["visible_code", "child_index"],
        order_by="child_index asc",
        limit_page_length=1000,
    ) if parent.tag_family else []
    return {
        "parent_handling_unit": parent.name,
        "parent_code": parent.handling_unit_id,
        "item_code": parent.item_code,
        "batch_no": parent.batch_no,
        "company": parent.inventory_company,
        "warehouse": parent.current_warehouse,
        "current_qty": parent.current_qty,
        "stock_uom": parent.stock_uom,
        "serial_numbers": serials,
        "serial_count": len(serials),
        "unused_child_tags": children,
        "can_split": bool(problem is None and children),
        "blocked_reason": problem,
    }


@frappe.whitelist()
def split_serials_to_child(parent_handling_unit, child_scan_value, serial_numbers, reason):
    if not frappe.has_permission("CFG Kanban Handling Unit", ptype="create"):
        frappe.throw(_("You do not have permission to activate Handling Units"),
                     frappe.PermissionError)
    if not (reason or "").strip():
        frappe.throw(_("Split reason is required"))
    child_code = normalize_physical_code(child_scan_value)
    frappe.db.sql(
        "select name from `tabCFG Kanban Handling Unit` where name=%s for update",
        parent_handling_unit,
    )
    parent = frappe.get_doc("CFG Kanban Handling Unit", parent_handling_unit)
    parent.check_permission("write")
    serials = active_serials_for_unit(parent.name)
    problem = _serial_split_problem(parent, serials)
    if problem:
        frappe.throw(problem)

    activation_key = canonical_key("serial-child-split", parent.name, child_code)
    existing = frappe.db.get_value(
        "CFG Kanban Handling Unit", {"activation_key": activation_key}, "name"
    )
    if existing:
        return _split_result(parent.name, existing)

    identity = resolve_logistics_scan(child_code)
    if identity and identity.get("identity_type") == "Tag Range Candidate":
        materialize_tag_family_for_code(child_code, identity.get("range_registry"))
        identity = resolve_logistics_scan(child_code)
    if not identity or identity.get("identity_type") != "Registered Tag Identity":
        frappe.throw(_("Scan an unused detachable child tag from the parent's Tag Family"))
    if identity.get("tag_role") != "Child":
        frappe.throw(_("The scanned tag is not a detachable child identity"))
    if identity.get("tag_family") != parent.tag_family:
        frappe.throw(_("Child tag {0} does not belong to parent family {1}").format(
            child_code, parent.tag_family
        ))
    if identity.get("state") != "Unused" or identity.get("handling_unit"):
        frappe.throw(_("Child tag {0} has already been activated").format(child_code))

    selected = _validate_selected_serials(parent, serials, serial_numbers)
    child = frappe.copy_doc(parent)
    child.name = None
    child.handling_unit_id = child_code
    child.opaque_token = None
    child.tag_kind = "Child Stock Tag"
    child.parent_handling_unit = parent.name
    child.root_handling_unit = parent.root_handling_unit or parent.name
    child.child_index = identity.get("child_index")
    child.qty = len(selected)
    child.original_qty = len(selected)
    child.current_qty = 0
    child.reserved_qty = 0
    child.available_qty = 0
    child.serial_count = 0
    child.activation_key = activation_key
    child.replacement_of = None
    child.replaced_by = None
    child.void_reason = None
    child.print_revision = 1
    child.print_count = 0
    child.last_printed_on = None
    child.last_printed_by = None
    child.last_scan_time = None
    child.flags.controlled_serial_split = True
    child.flags.activation_reason = (
        f"Controlled serial split from {parent.handling_unit_id}: {reason.strip()}"
    )
    child.insert(ignore_permissions=True)

    transferred = transfer_selected_serials(
        parent,
        child,
        selected,
        f"Controlled split to child tag {child.handling_unit_id}: {reason.strip()}",
    )
    parent.reload()
    if flt(parent.current_qty) <= TOLERANCE:
        parent.db_set(
            {"identity_state": "Empty", "movement_state": "Empty"},
            update_modified=False,
        )
    record(
        "Serial Stock Tag Split",
        card=parent.kanban_card,
        cycle=parent.kanban_cycle,
        handling_unit=child.name,
        qty=len(transferred),
        reference_doctype="CFG Kanban Handling Unit",
        reference_name=parent.name,
        notes=(f"{parent.handling_unit_id} -> {child.handling_unit_id}; "
               f"Serials: {', '.join(transferred)}; {reason.strip()}"),
        system_generated=True,
    )
    return _split_result(parent.name, child.name)


@frappe.whitelist()
def merge_serial_child_to_parent(child_handling_unit, reason):
    if not (reason or "").strip():
        frappe.throw(_("Merge reason is required"))
    child = frappe.get_doc("CFG Kanban Handling Unit", child_handling_unit)
    if not child.parent_handling_unit:
        frappe.throw(_("The selected tag has no parent Handling Unit"))
    names = sorted({child.name, child.parent_handling_unit})
    placeholders = ", ".join(["%s"] * len(names))
    frappe.db.sql(
        f"select name from `tabCFG Kanban Handling Unit` "
        f"where name in ({placeholders}) order by name for update",
        tuple(names),
    )
    child.reload()
    parent = frappe.get_doc("CFG Kanban Handling Unit", child.parent_handling_unit)
    child.check_permission("write")
    parent.check_permission("write")
    merge_key = canonical_key("serial-child-merge", parent.name, child.name)
    if frappe.db.exists(
        "CFG Kanban Handling Unit Quantity Ledger", {"idempotency_key": merge_key}
    ):
        return _split_result(parent.name, child.name)
    problem = _serial_merge_problem(parent, child)
    if problem:
        frappe.throw(problem)

    child_qty = flt(child.current_qty)
    ledger = post_quantity_event(
        event_type="Merge",
        qty=child_qty,
        stock_uom=child.stock_uom,
        idempotency_key=merge_key,
        source_handling_unit=child.name,
        destination_handling_unit=parent.name,
        item_code=child.item_code,
        batch_no=child.batch_no,
        source_company=child.inventory_company,
        destination_company=parent.inventory_company,
        source_warehouse=child.current_warehouse,
        destination_warehouse=parent.current_warehouse,
        reference_doctype="CFG Kanban Handling Unit",
        reference_name=child.name,
        reason=f"Controlled child-tag merge: {reason.strip()}",
    )
    transferred = merge_child_serials(
        child,
        parent,
        f"Controlled merge back to parent tag {parent.handling_unit_id}: {reason.strip()}",
    )
    frappe.db.set_value(
        "CFG Kanban Handling Unit",
        parent.name,
        {
            "identity_state": "Active",
            "movement_state": (child.movement_state
                               if child.movement_state != "Empty" else "Received"),
        },
        update_modified=False,
    )
    frappe.db.set_value(
        "CFG Kanban Handling Unit",
        child.name,
        {"identity_state": "Empty", "movement_state": "Empty"},
        update_modified=False,
    )
    record(
        "Serial Child Tag Merged",
        card=parent.kanban_card,
        cycle=parent.kanban_cycle,
        handling_unit=child.name,
        qty=child_qty,
        reference_doctype=ledger.doctype,
        reference_name=ledger.name,
        notes=(f"{child.handling_unit_id} -> {parent.handling_unit_id}; "
               f"Serials: {', '.join(transferred)}; {reason.strip()}"),
        system_generated=True,
    )
    return _split_result(parent.name, child.name)


def _serial_split_problem(parent, serials):
    if parent.tag_kind != "Main Stock Tag":
        return _("Only a main Stock Tag can be split into its detachable child tags")
    if parent.identity_state != "Active":
        return _("Parent Stock Tag must be Active")
    if not parent.tag_family:
        return _("Parent Stock Tag has no Tag Family")
    if not frappe.db.get_value("CFG Kanban Tag Family", parent.tag_family, "active"):
        return _("Parent Tag Family {0} is inactive").format(parent.tag_family)
    if flt(parent.reserved_qty) > TOLERANCE:
        return _("Release all reservations before splitting this Stock Tag")
    if not parent.current_warehouse or not parent.inventory_company:
        return _("Parent Stock Tag requires a current Company and Warehouse")
    if not serials:
        return _("Parent Stock Tag has no active exact Serial Number membership")
    if len(serials) != int(round(flt(parent.current_qty))):
        return _("Parent Stock Tag quantity and active Serial Number count do not match")
    if active_container_membership_name(parent.name):
        return _("Unload the parent Stock Tag from its reusable container before splitting")
    return None


def _serial_merge_problem(parent, child):
    if child.tag_kind != "Child Stock Tag" or child.parent_handling_unit != parent.name:
        return _("Only a detachable child tag can be merged into its recorded parent")
    if child.identity_state != "Active" or parent.identity_state not in ("Active", "Empty"):
        return _("Both child and parent identities must remain available for a controlled merge")
    if flt(child.reserved_qty) > TOLERANCE or flt(parent.reserved_qty) > TOLERANCE:
        return _("Release all parent and child reservations before merging")
    if active_container_membership_name(child.name) or active_container_membership_name(parent.name):
        return _("Unload both tags from reusable containers before merging")
    if frappe.db.exists(
        "CFG Kanban Container Content", {"content_handling_unit": child.name}
    ):
        return _("Child tag has container-loading history and can no longer be merged")
    matching_fields = ("tag_family", "item_code", "batch_no", "stock_uom",
                       "inventory_company", "current_warehouse", "physical_custodian",
                       "current_operation", "quality_state")
    if any(child.get(fieldname) != parent.get(fieldname) for fieldname in matching_fields):
        return _("Parent and child Item, Batch, Company, UOM, and Warehouse must still match")
    if flt(parent.current_qty) + flt(child.current_qty) > flt(parent.original_qty) + TOLERANCE:
        return _("Merged quantity would exceed the parent's original activated quantity")
    serials = active_serials_for_unit(child.name)
    if not serials or len(serials) != int(round(flt(child.current_qty))):
        return _("Child tag quantity and active Serial Number count do not match")
    downstream = frappe.db.sql(
        """
        select name
        from `tabCFG Kanban Handling Unit Quantity Ledger`
        where (source_handling_unit=%s or destination_handling_unit=%s)
          and idempotency_key != %s
        limit 1
        """,
        (child.name, child.name, f"handling-unit-activation:{child.name}"),
    )
    if downstream:
        return _("Child tag has later quantity activity and can no longer be merged")
    return None


def _validate_selected_serials(parent, active_serials, serial_numbers):
    from cfg_kanban.services.serial_evidence import serials_from_json

    selected = serials_from_json(serial_numbers)
    if not selected:
        frappe.throw(_("Scan or enter at least one Serial Number for the child tag"))
    invalid = [value for value in selected if value not in active_serials]
    if invalid:
        frappe.throw(_("Serial Numbers do not belong to parent tag {0}: {1}").format(
            parent.handling_unit_id, ", ".join(invalid)
        ))
    return selected


def active_container_membership_name(handling_unit):
    return frappe.db.get_value(
        "CFG Kanban Container Content",
        {"content_handling_unit": handling_unit, "state": "Loaded"},
        "name",
    )


def _split_result(parent_name, child_name):
    parent = frappe.get_doc("CFG Kanban Handling Unit", parent_name)
    child = frappe.get_doc("CFG Kanban Handling Unit", child_name)
    return {
        "parent": {
            "name": parent.name,
            "visible_code": parent.handling_unit_id,
            "current_qty": parent.current_qty,
            "serial_numbers": active_serials_for_unit(parent.name),
        },
        "child": {
            "name": child.name,
            "visible_code": child.handling_unit_id,
            "current_qty": child.current_qty,
            "serial_numbers": active_serials_for_unit(child.name),
        },
    }
