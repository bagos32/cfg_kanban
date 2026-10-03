import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import resolve_logistics_scan
from cfg_kanban.services.operator_auth import require_operator


CONTAINER_LOADING_RESPONSIBILITY = "Container Loading"


@frappe.whitelist()
def get_container_contents(container_scan, operator_session_token=None, include_history=1):
    _authorize(operator_session_token, write=False)
    container = _resolve_container(container_scan)
    return _container_result(container, include_history=cint(include_history))


@frappe.whitelist()
def load_content_tag(container_scan, content_scan, event_token,
                     operator_session_token=None):
    actor = _authorize(operator_session_token, write=True)
    if not event_token:
        frappe.throw(_("A stable scan event token is required"))
    container = _resolve_container(container_scan)
    content = _resolve_content(content_scan)
    _lock_units(container.name, content.name)
    container.reload()
    content.reload()
    assert_container_not_in_open_manifest(container.name, "changing its physical contents")
    assert_container_not_in_open_delivery(container.name, "changing its physical contents")
    _validate_load(container, content)

    load_key = canonical_key("container-load", container.name, content.name, event_token)
    existing = frappe.db.get_value(
        "CFG Kanban Container Content", {"load_event_key": load_key}, "name"
    )
    if existing:
        return _container_result(container, include_history=True)
    active = active_container_membership(content.name)
    if active:
        if active.container_handling_unit == container.name:
            return _container_result(container, include_history=True)
        frappe.throw(
            _("Tag {0} is already loaded in container {1}").format(
                content.handling_unit_id, active.container_visible_code
            )
        )

    _validate_container_mix(container, content)
    _adopt_container_location(container, content)
    now = now_datetime()
    episode = frappe.get_doc({
        "doctype": "CFG Kanban Container Content",
        "state": "Loaded",
        "container_handling_unit": container.name,
        "container_visible_code": container.handling_unit_id,
        "content_handling_unit": content.name,
        "content_visible_code": content.handling_unit_id,
        "item_code": content.item_code,
        "batch_no": content.batch_no,
        "qty": content.current_qty,
        "stock_uom": content.stock_uom,
        "company": content.inventory_company,
        "warehouse": content.current_warehouse,
        "loaded_on": now,
        "loaded_by": actor.get("operator"),
        "loaded_operator_session": actor.get("operator_session"),
        "load_event_key": load_key,
    }).insert(ignore_permissions=True)
    container.db_set({"movement_state": "Packed", "last_scan_time": now},
                     update_modified=False)
    content.db_set("last_scan_time", now, update_modified=False)
    record(
        "Stock Tag Loaded into Reusable Container",
        handling_unit=container.name,
        qty=content.current_qty,
        reference_doctype=episode.doctype,
        reference_name=episode.name,
        device_id=event_token,
        notes=(f"{content.handling_unit_id}: {content.item_code} / "
               f"{content.batch_no or 'no batch'} / {content.current_qty} {content.stock_uom}"),
        operator=actor.get("operator"),
        operator_session=actor.get("operator_session"),
        terminal_user=actor.get("terminal_user"),
    )
    container.reload()
    return _container_result(container, include_history=True)


@frappe.whitelist()
def unload_content_tag(container_scan, content_scan, reason, event_token,
                       operator_session_token=None):
    actor = _authorize(operator_session_token, write=True)
    if not (reason or "").strip():
        frappe.throw(_("Unload Reason is required"))
    if not event_token:
        frappe.throw(_("A stable unload event token is required"))
    container = _resolve_container(container_scan)
    content = _resolve_content(content_scan, require_active=False)
    _lock_units(container.name, content.name)
    assert_container_not_in_open_manifest(container.name, "changing its physical contents")
    assert_container_not_in_open_delivery(container.name, "changing its physical contents")
    content.reload()
    if flt(content.reserved_qty):
        frappe.throw(
            _("Tag {0} is reserved for an open transaction and cannot be unloaded").format(
                content.handling_unit_id
            )
        )
    unload_key = canonical_key("container-unload", container.name, content.name, event_token)
    existing = frappe.db.get_value(
        "CFG Kanban Container Content", {"unload_event_key": unload_key}, "name"
    )
    if existing:
        return _container_result(container, include_history=True)
    episode_name = frappe.db.get_value(
        "CFG Kanban Container Content",
        {
            "container_handling_unit": container.name,
            "content_handling_unit": content.name,
            "state": "Loaded",
        },
        "name",
    )
    if not episode_name:
        frappe.throw(
            _("Tag {0} is not currently loaded in container {1}").format(
                content.handling_unit_id, container.handling_unit_id
            )
        )
    now = now_datetime()
    frappe.db.set_value(
        "CFG Kanban Container Content",
        episode_name,
        {
            "state": "Unloaded",
            "unloaded_on": now,
            "unloaded_by": actor.get("operator"),
            "unloaded_operator_session": actor.get("operator_session"),
            "unload_event_key": unload_key,
            "unload_reason": reason.strip(),
        },
        update_modified=True,
    )
    if not frappe.db.exists(
        "CFG Kanban Container Content",
        {"container_handling_unit": container.name, "state": "Loaded"},
    ):
        container.db_set({"movement_state": "Empty", "last_scan_time": now},
                         update_modified=False)
    content.db_set("last_scan_time", now, update_modified=False)
    record(
        "Stock Tag Unloaded from Reusable Container",
        handling_unit=container.name,
        qty=content.current_qty,
        reference_doctype="CFG Kanban Container Content",
        reference_name=episode_name,
        device_id=event_token,
        notes=f"{content.handling_unit_id}: {reason.strip()}",
        operator=actor.get("operator"),
        operator_session=actor.get("operator_session"),
        terminal_user=actor.get("terminal_user"),
    )
    container.reload()
    return _container_result(container, include_history=True)


def active_container_membership(content_handling_unit):
    name = frappe.db.get_value(
        "CFG Kanban Container Content",
        {"content_handling_unit": content_handling_unit, "state": "Loaded"},
        "name",
    )
    return frappe.get_doc("CFG Kanban Container Content", name) if name else None


def active_container_contents(container_handling_unit):
    """Return the immutable membership episodes currently loaded in a container."""
    return frappe.get_all(
        "CFG Kanban Container Content",
        filters={"container_handling_unit": container_handling_unit, "state": "Loaded"},
        fields=[
            "name", "container_handling_unit", "container_visible_code",
            "content_handling_unit", "content_visible_code", "item_code", "batch_no",
            "qty", "stock_uom", "company", "warehouse", "loaded_on",
        ],
        order_by="loaded_on asc, name asc",
        limit_page_length=500,
    )


def assert_not_loaded_in_container(content_handling_unit, action):
    active = active_container_membership(content_handling_unit)
    if active:
        frappe.throw(
            _("Tag {0} is physically loaded in reusable container {1}. Unload it before {2}.").format(
                active.content_visible_code, active.container_visible_code, action
            )
        )


def assert_container_empty(container_handling_unit, action):
    active = frappe.db.get_value(
        "CFG Kanban Container Content",
        {"container_handling_unit": container_handling_unit, "state": "Loaded"},
        "content_visible_code",
    )
    if active:
        frappe.throw(
            _("Reusable container still contains tag {0}. Unload all contents before {1}.").format(
                active, action
            )
        )


def assert_container_not_in_open_manifest(container_handling_unit, action):
    manifest = frappe.db.sql(
        """
        select manifest.name
        from `tabCFG Kanban Manifest Line` line
        inner join `tabCFG Kanban Movement Manifest` manifest on manifest.name=line.parent
        where line.container_handling_unit=%s
          and manifest.state not in ('Received','Billing Pending','Partially Billed','Billed',
                                     'Closed','Cancelled')
        limit 1
        """,
        (container_handling_unit,),
    )
    if manifest:
        frappe.throw(
            _("Reusable container is assigned to open Manifest {0}; it cannot be used for {1}").format(
                manifest[0][0], action
            )
        )


def assert_container_not_in_open_delivery(container_handling_unit, action):
    allocation = frappe.db.get_value(
        "CFG Kanban Delivery Allocation",
        {
            "container_handling_unit": container_handling_unit,
            "state": ["in", ["Reserved", "Delivery Pending", "Exception"]],
        },
        ["delivery_session", "container_visible_code"],
        as_dict=True,
    )
    if allocation:
        frappe.throw(
            _("Reusable container {0} is assigned to Delivery Session {1}; "
              "it cannot be used for {2}").format(
                allocation.container_visible_code,
                allocation.delivery_session,
                action,
            )
        )


def container_history_for_units(handling_units):
    names = list(handling_units or [])
    if not names or not frappe.has_permission("CFG Kanban Container Content", ptype="read"):
        return []
    fields = [
        "name", "state", "container_handling_unit", "container_visible_code",
        "content_handling_unit", "content_visible_code", "item_code", "batch_no",
        "qty", "stock_uom", "company", "warehouse", "loaded_on", "loaded_by",
        "unloaded_on", "unloaded_by", "unload_reason",
    ]
    rows = {}
    for fieldname in ("container_handling_unit", "content_handling_unit"):
        for row in frappe.get_list(
            "CFG Kanban Container Content",
            filters={fieldname: ["in", names]},
            fields=fields,
            order_by="loaded_on desc",
            limit_page_length=250,
        ):
            rows[row.name] = row
    return sorted(rows.values(), key=lambda row: str(row.loaded_on or ""), reverse=True)[:250]


def container_status_for_unit(unit):
    """Return physical-container context for a read-authorized Handling Unit."""
    if unit.tag_kind == "Reusable Container":
        return {"mode": "container", **_container_result(unit, include_history=True)}
    active = active_container_membership(unit.name)
    if not active:
        return {"mode": "stock_tag", "active_membership": None}
    return {
        "mode": "stock_tag",
        "active_membership": {
            "name": active.name,
            "container_handling_unit": active.container_handling_unit,
            "container_visible_code": active.container_visible_code,
            "loaded_on": active.loaded_on,
            "loaded_by": active.loaded_by,
        },
    }


def _authorize(operator_session_token, write):
    if operator_session_token:
        profile, session = require_operator(
            operator_session_token, action="start" if write else None
        )
        responsibilities = {
            row.responsibility for row in profile.responsibilities if row.responsibility
        }
        if not (
            cint(profile.get("view_all_responsibilities"))
            or profile.kanban_role in ("Supervisor", "Development Proxy")
            or CONTAINER_LOADING_RESPONSIBILITY in responsibilities
        ):
            frappe.throw(_("Operator is not assigned to Container Loading"))
        return {
            "operator": profile.employee,
            "operator_session": session.name,
            "terminal_user": session.terminal_user,
        }
    roles = set(frappe.get_roles(frappe.session.user))
    if not roles.intersection({"Stock Manager", "Manufacturing Manager", "System Manager"}):
        frappe.throw(_("Manager permission or an authorized operator session is required"),
                     frappe.PermissionError)
    return {"operator": None, "operator_session": None,
            "terminal_user": frappe.session.user}


def _resolve_container(scan_value):
    identity = resolve_logistics_scan(scan_value)
    if not identity or identity.get("identity_type") != "Handling Unit":
        frappe.throw(_("Scan an activated reusable-container tag"))
    container = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    if container.tag_kind != "Reusable Container":
        frappe.throw(_("Tag {0} is not a Reusable Container").format(container.handling_unit_id))
    if container.identity_state != "Active" or container.quality_state != "Released":
        frappe.throw(
            _("Reusable container {0} is {1} / {2}").format(
                container.handling_unit_id, container.identity_state, container.quality_state
            )
        )
    return container


def _resolve_content(scan_value, require_active=True):
    identity = resolve_logistics_scan(scan_value)
    if not identity or identity.get("identity_type") != "Handling Unit":
        frappe.throw(_("Scan an activated physical Stock Tag"))
    content = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
    if content.tag_kind == "Reusable Container":
        frappe.throw(_("Nested reusable containers are not supported"))
    if require_active and (
        content.identity_state != "Active" or content.quality_state != "Released"
    ):
        frappe.throw(
            _("Stock Tag {0} is {1} / {2}").format(
                content.handling_unit_id, content.identity_state, content.quality_state
            )
        )
    return content


def _validate_load(container, content):
    if flt(content.current_qty) <= 0 or not content.item_code or not content.stock_uom:
        frappe.throw(_("The Stock Tag has no active physical quantity to load"))
    if not content.inventory_company or not content.current_warehouse:
        frappe.throw(_("The Stock Tag requires an ERP Company and Warehouse before loading"))
    if flt(content.reserved_qty) or flt(content.available_qty) != flt(content.current_qty):
        frappe.throw(_("A reserved or partly unavailable Stock Tag cannot be loaded into a container"))
    if content.movement_state not in ("At Source", "Packed", "Received", "Returned"):
        frappe.throw(
            _("Stock Tag {0} is in movement state {1} and cannot be containerized").format(
                content.handling_unit_id, content.movement_state
            )
        )
    if container.inventory_company and container.inventory_company != content.inventory_company:
        frappe.throw(_("Container and Stock Tag belong to different inventory Companies"))
    if container.current_warehouse and container.current_warehouse != content.current_warehouse:
        frappe.throw(_("Container and Stock Tag are not in the same ERP Warehouse"))


def _validate_container_mix(container, content):
    if cint(container.allow_mixed_content):
        return
    existing = frappe.get_all(
        "CFG Kanban Container Content",
        filters={"container_handling_unit": container.name, "state": "Loaded"},
        fields=["item_code", "batch_no"],
        limit_page_length=1,
    )
    if existing and (
        existing[0].item_code != content.item_code
        or (existing[0].batch_no or "") != (content.batch_no or "")
    ):
        frappe.throw(
            _("This container does not allow mixed Item/Batch contents. Empty it first or enable Allow Mixed Item / Batch Content before its first load.")
        )


def _adopt_container_location(container, content):
    values = {}
    if not container.inventory_company:
        values["inventory_company"] = content.inventory_company
    if not container.current_warehouse:
        values["current_warehouse"] = content.current_warehouse
    if values:
        frappe.db.set_value("CFG Kanban Handling Unit", container.name, values,
                            update_modified=False)
        for fieldname, value in values.items():
            container.set(fieldname, value)


def _container_result(container, include_history):
    current = frappe.get_all(
        "CFG Kanban Container Content",
        filters={"container_handling_unit": container.name, "state": "Loaded"},
        fields=[
            "name", "state", "content_handling_unit", "content_visible_code",
            "item_code", "batch_no", "qty", "stock_uom", "company", "warehouse",
            "loaded_on", "loaded_by",
        ],
        order_by="loaded_on asc",
        limit_page_length=500,
    )
    history = []
    if include_history:
        history = frappe.get_all(
            "CFG Kanban Container Content",
            filters={"container_handling_unit": container.name, "state": "Unloaded"},
            fields=[
                "name", "state", "content_handling_unit", "content_visible_code",
                "item_code", "batch_no", "qty", "stock_uom", "company", "warehouse",
                "loaded_on", "loaded_by", "unloaded_on", "unloaded_by", "unload_reason",
            ],
            order_by="unloaded_on desc",
            limit_page_length=50,
        )
    return {
        "container": {
            "name": container.name,
            "visible_code": container.handling_unit_id,
            "container_reference": container.container_reference,
            "handling_unit_type": container.handling_unit_type,
            "allow_mixed_content": bool(cint(container.allow_mixed_content)),
            "inventory_company": container.inventory_company,
            "current_warehouse": container.current_warehouse,
            "physical_custodian": container.physical_custodian,
            "identity_state": container.identity_state,
            "movement_state": container.movement_state,
            "quality_state": container.quality_state,
        },
        "current_contents": current,
        "history": history,
    }


def _lock_units(*names):
    ordered = sorted(set(names))
    placeholders = ", ".join(["%s"] * len(ordered))
    rows = frappe.db.sql(
        f"select name from `tabCFG Kanban Handling Unit` where name in ({placeholders}) order by name for update",
        tuple(ordered),
    )
    if len(rows) != len(ordered):
        frappe.throw(_("One or more Handling Units no longer exist"))
