from collections import deque

import frappe
from frappe import _
from frappe.utils import cint

from cfg_kanban.services.logistics_foundation import resolve_logistics_scan


MAX_GRAPH_NODES = 100
MAX_TIMELINE_EVENTS = 250


@frappe.whitelist()
def get_handling_unit_genealogy(scan_value=None, handling_unit=None, max_depth=8):
    """Return read-only upstream/downstream lineage for one physical stock tag."""
    _require_read_access()
    identity, root_name = _resolve_root(scan_value, handling_unit)
    if not root_name:
        return {
            "identity": identity,
            "activated": False,
            "evidence_level": "Registered identity only",
            "focus": None,
            "upstream": [],
            "downstream": [],
            "relationships": [],
            "timeline": [],
            "manifests": [],
            "container_history": [],
            "truncated": False,
        }

    depth_limit = min(max(cint(max_depth) or 8, 1), 20)
    nodes, edges, levels, truncated = _walk_graph(root_name, depth_limit)
    summaries = _unit_summaries(nodes)
    if root_name not in summaries:
        frappe.throw(_("You do not have permission to view this Handling Unit"), frappe.PermissionError)
    visible_nodes = set(summaries)
    focus = summaries[root_name]
    focus["level"] = 0

    upstream = []
    downstream = []
    for name, summary in summaries.items():
        if name == root_name:
            continue
        row = dict(summary)
        row["level"] = levels.get(name, 0)
        if row["level"] < 0:
            upstream.append(row)
        elif row["level"] > 0:
            downstream.append(row)

    upstream.sort(key=lambda row: (abs(row["level"]), row.get("packed_on") or "", row["visible_code"]))
    downstream.sort(key=lambda row: (row["level"], row.get("packed_on") or "", row["visible_code"]))

    return {
        "identity": identity,
        "activated": True,
        "evidence_level": "Exact Handling Unit",
        "focus": focus,
        "upstream": upstream,
        "downstream": downstream,
        "relationships": _serialise_edges(edges, summaries),
        "timeline": _timeline(visible_nodes, summaries),
        "manifests": _manifest_history(visible_nodes),
        "container_history": _container_history(visible_nodes),
        "truncated": truncated,
    }


def _container_history(visible_nodes):
    from cfg_kanban.services.container_contents import container_history_for_units
    return container_history_for_units(visible_nodes)


def get_genealogy_print_context(handling_unit):
    """Jinja-safe context used by the standard genealogy Print Format."""
    result = get_handling_unit_genealogy(handling_unit=handling_unit, max_depth=12)
    if not result.get("activated"):
        frappe.throw(_("The selected physical identity has not been activated as a Handling Unit"))
    return result


def _require_read_access():
    required = ("CFG Kanban Handling Unit", "CFG Kanban Handling Unit Quantity Ledger")
    if not all(frappe.has_permission(doctype, ptype="read") for doctype in required):
        frappe.throw(
            _("Manager permission is required to view exact Handling Unit genealogy"),
            frappe.PermissionError,
        )


def _resolve_root(scan_value, handling_unit):
    if handling_unit:
        if not frappe.db.exists("CFG Kanban Handling Unit", handling_unit):
            frappe.throw(_("Handling Unit {0} was not found").format(handling_unit))
        doc = frappe.get_doc("CFG Kanban Handling Unit", handling_unit)
        doc.check_permission("read")
        return {
            "identity_type": "Handling Unit",
            "name": doc.name,
            "visible_code": doc.handling_unit_id,
            "matched_by": "document_name",
        }, doc.name

    if not (scan_value or "").strip():
        frappe.throw(_("Scan or enter a physical Stock Tag"))
    identity = resolve_logistics_scan(scan_value)
    if not identity:
        frappe.throw(_("The scanned physical identity was not found"))
    if identity["identity_type"] == "Handling Unit":
        doc = frappe.get_doc("CFG Kanban Handling Unit", identity["name"])
        doc.check_permission("read")
        return identity, doc.name
    if identity["identity_type"] in ("Registered Tag Identity", "Tag Range Candidate"):
        return identity, None
    frappe.throw(
        _("{0} is a {1}, not a physical Stock Tag").format(
            identity.get("visible_code") or scan_value,
            identity.get("identity_type") or _("different scan identity"),
        )
    )


def _walk_graph(root_name, max_depth):
    nodes = {root_name}
    levels = {root_name: 0}
    edges = {}
    queue = deque([(root_name, 0)])
    truncated = False

    while queue:
        name, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for edge in _neighbour_edges(name):
            key = (
                edge["source"], edge["target"], edge["relation_type"],
                edge.get("reference_doctype"), edge.get("reference_name"),
            )
            edges[key] = edge
            other = edge["target"] if edge["source"] == name else edge["source"]
            if other in nodes:
                continue
            if len(nodes) >= MAX_GRAPH_NODES:
                truncated = True
                continue
            nodes.add(other)
            direction = 1 if edge["source"] == name else -1
            levels[other] = levels[name] + direction
            queue.append((other, depth + 1))
    return nodes, list(edges.values()), levels, truncated


def _neighbour_edges(handling_unit):
    edges = []
    edges.extend(_production_edges(handling_unit))
    edges.extend(_ledger_edges(handling_unit))
    edges.extend(_family_edges(handling_unit))
    return edges


def _production_edges(handling_unit):
    anchor_lines = frappe.db.sql(
        """
        select line.parent, line.direction
        from `tabCFG Kanban Material Trace Line` line
        inner join `tabCFG Kanban Material Trace` trace on trace.name=line.parent
        where line.handling_unit=%s
          and line.status in ('Confirmed', 'Reversed')
          and trace.status in ('Confirmed', 'Reversed')
        """,
        handling_unit,
        as_dict=True,
    )
    edges = []
    for anchor in anchor_lines:
        trace = frappe.db.get_value(
            "CFG Kanban Material Trace",
            anchor.parent,
            ["name", "status", "purpose", "stock_entry_reference", "work_order", "kanban_cycle"],
            as_dict=True,
        )
        if not trace:
            continue
        siblings = frappe.get_all(
            "CFG Kanban Material Trace Line",
            filters={
                "parent": anchor.parent,
                "handling_unit": ["is", "set"],
                "status": ["in", ["Confirmed", "Reversed"]],
            },
            fields=["handling_unit", "direction", "qty", "stock_uom", "item_code", "batch_no"],
            limit_page_length=500,
        )
        inputs = [row for row in siblings if row.direction == "Input"]
        outputs = [row for row in siblings if row.direction == "Output"]
        for source in inputs:
            for target in outputs:
                if source.handling_unit == target.handling_unit:
                    continue
                edges.append({
                    "source": source.handling_unit,
                    "target": target.handling_unit,
                    "relation_type": "Production Transformation",
                    "status": trace.status,
                    "qty": target.qty,
                    "stock_uom": target.stock_uom,
                    "reference_doctype": "Stock Entry",
                    "reference_name": trace.stock_entry_reference,
                    "material_trace": trace.name,
                    "purpose": trace.purpose,
                    "work_order": trace.work_order,
                    "kanban_cycle": trace.kanban_cycle,
                })
    return edges


def _ledger_edges(handling_unit):
    rows = frappe.db.sql(
        """
        select name, event_type, posting_datetime, source_handling_unit,
               destination_handling_unit, stock_qty, stock_uom,
               reference_doctype, reference_name, reason
        from `tabCFG Kanban Handling Unit Quantity Ledger`
        where (source_handling_unit=%s or destination_handling_unit=%s)
          and source_handling_unit is not null
          and destination_handling_unit is not null
          and source_handling_unit != destination_handling_unit
        order by posting_datetime asc, creation asc
        """,
        (handling_unit, handling_unit),
        as_dict=True,
    )
    return [{
        "source": row.source_handling_unit,
        "target": row.destination_handling_unit,
        "relation_type": row.event_type,
        "status": "Confirmed",
        "qty": row.stock_qty,
        "stock_uom": row.stock_uom,
        "posting_datetime": row.posting_datetime,
        "reference_doctype": row.reference_doctype,
        "reference_name": row.reference_name,
        "ledger": row.name,
        "reason": row.reason,
    } for row in rows]


def _family_edges(handling_unit):
    unit = frappe.db.get_value(
        "CFG Kanban Handling Unit",
        handling_unit,
        ["name", "parent_handling_unit"],
        as_dict=True,
    )
    edges = []
    if unit and unit.parent_handling_unit:
        edges.append({
            "source": unit.parent_handling_unit,
            "target": unit.name,
            "relation_type": "Detachable Child Tag",
            "status": "Confirmed",
            "reference_doctype": "CFG Kanban Handling Unit",
            "reference_name": unit.name,
        })
    children = frappe.get_all(
        "CFG Kanban Handling Unit",
        filters={"parent_handling_unit": handling_unit},
        fields=["name"],
        limit_page_length=100,
    )
    for child in children:
        edges.append({
            "source": handling_unit,
            "target": child.name,
            "relation_type": "Detachable Child Tag",
            "status": "Confirmed",
            "reference_doctype": "CFG Kanban Handling Unit",
            "reference_name": child.name,
        })
    return edges


def _unit_summaries(names):
    rows = frappe.get_list(
        "CFG Kanban Handling Unit",
        filters={"name": ["in", list(names)]},
        fields=[
            "name", "handling_unit_id", "tag_kind", "handling_unit_type", "item_code",
            "short_description", "batch_no", "stock_uom", "original_qty", "current_qty",
            "reserved_qty", "available_qty", "inventory_company", "current_warehouse",
            "physical_custodian", "identity_state", "movement_state", "quality_state",
            "packed_on", "expiry_date", "work_order", "kanban_cycle", "kanban_card",
            "origin_reference_doctype", "origin_reference_name", "origin_reference_row",
            "parent_handling_unit", "root_handling_unit", "replacement_of", "replaced_by",
        ],
        limit_page_length=MAX_GRAPH_NODES,
    )
    result = {}
    for row in rows:
        data = dict(row)
        data["visible_code"] = data.pop("handling_unit_id")
        result[row.name] = data
    return result


def _serialise_edges(edges, summaries):
    result = []
    for edge in edges:
        if edge["source"] not in summaries or edge["target"] not in summaries:
            continue
        row = dict(edge)
        row["source_code"] = summaries[edge["source"]]["visible_code"]
        row["target_code"] = summaries[edge["target"]]["visible_code"]
        result.append(row)
    result.sort(key=lambda row: (
        row.get("posting_datetime") or "",
        row.get("reference_name") or "",
        row["source_code"],
        row["target_code"],
    ))
    return result


def _timeline(names, summaries):
    names = list(names)
    if not names:
        return []
    placeholders = ", ".join(["%s"] * len(names))
    rows = frappe.db.sql(
        f"""
        select name, event_type, posting_datetime, source_handling_unit,
               destination_handling_unit, stock_qty, stock_uom,
               source_company, source_warehouse, destination_company,
               destination_warehouse, reference_doctype, reference_name,
               operator, reason
        from `tabCFG Kanban Handling Unit Quantity Ledger`
        where source_handling_unit in ({placeholders})
           or destination_handling_unit in ({placeholders})
        order by posting_datetime desc, creation desc
        limit {MAX_TIMELINE_EVENTS}
        """,
        tuple(names + names),
        as_dict=True,
    )
    for row in rows:
        row["source_code"] = summaries.get(row.source_handling_unit, {}).get("visible_code")
        row["destination_code"] = summaries.get(row.destination_handling_unit, {}).get("visible_code")
    return rows


def _manifest_history(names):
    if not frappe.has_permission("CFG Kanban Movement Manifest", ptype="read"):
        return []
    parents = frappe.get_all(
        "CFG Kanban Manifest Line",
        filters={"handling_unit": ["in", list(names)]},
        pluck="parent",
        group_by="parent",
        limit_page_length=100,
    )
    if not parents:
        return []
    return frappe.get_list(
        "CFG Kanban Movement Manifest",
        filters={"name": ["in", parents]},
        fields=[
            "name", "state", "source_company", "source_warehouse",
            "destination_company", "destination_warehouse", "dispatch_delivery_note",
            "receipt_purchase_receipt", "total_quantity", "modified",
        ],
        order_by="modified desc",
        limit_page_length=100,
    )
