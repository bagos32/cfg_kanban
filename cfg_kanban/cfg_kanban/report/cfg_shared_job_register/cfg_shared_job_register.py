import frappe
from frappe import _
from frappe.utils import cint, flt


TERMINAL_CYCLE_STATUSES = ("Completed", "Cancelled")


def execute(filters=None):
    filters = frappe._dict(filters or {})
    cycles = _permitted_cycles(filters)
    execution_totals = _execution_totals(cycles)
    participation_totals = _participation_totals(cycles)

    data = []
    for cycle in cycles:
        row = frappe._dict(cycle)
        row.update(execution_totals.get(cycle.name, {}))
        row.update(participation_totals.get(cycle.name, {}))
        for fieldname in (
            "execution_count",
            "completed_execution_count",
            "open_execution_count",
            "blocked_execution_count",
            "participation_segment_count",
            "participant_count",
            "active_participant_count",
            "recorded_participation_hours",
        ):
            row.setdefault(fieldname, 0)
        data.append(row)

    message = _(
        "<b>Reuse-first boundary:</b> Kanban Cycle is the shared work instance, "
        "Process Execution is its operation-level execution, and Job Participation records "
        "worker contribution intervals. Recorded participation hours are operational evidence "
        "only; they are not attendance, payable time, payroll eligibility, or earnings."
    )
    return _columns(), data, message, None, _summary(data)


def _permitted_cycles(filters):
    cycle_filters = {}
    for fieldname in ("company", "status", "item_code", "work_order"):
        if filters.get(fieldname):
            cycle_filters[fieldname] = filters.get(fieldname)
    if cint(filters.get("active_only")) and not filters.get("status"):
        cycle_filters["status"] = ["not in", TERMINAL_CYCLE_STATUSES]
    if filters.get("from_date"):
        cycle_filters["creation"] = [">=", filters.from_date]
    if filters.get("to_date"):
        upper_bound = ["<=", f"{filters.to_date} 23:59:59"]
        if "creation" in cycle_filters:
            cycle_filters["creation"] = ["between", [filters.from_date, upper_bound[1]]]
        else:
            cycle_filters["creation"] = upper_bound

    return frappe.get_list(
        "CFG Kanban Cycle",
        filters=cycle_filters,
        fields=[
            "name",
            "company",
            "status",
            "priority",
            "kanban_card",
            "item_code",
            "planned_qty",
            "actual_good_qty",
            "reject_qty",
            "stock_uom",
            "work_order",
            "started_on",
            "completed_on",
            "creation",
            "modified",
        ],
        order_by="modified desc",
        limit_page_length=0,
    )


def _execution_totals(cycles):
    cycle_names = tuple(row.name for row in cycles)
    if not cycle_names:
        return {}
    rows = frappe.db.sql(
        """
        select
            kanban_cycle,
            count(*) as execution_count,
            sum(case when status = 'Completed' then 1 else 0 end)
                as completed_execution_count,
            sum(case when status in ('Ready', 'In Progress', 'Paused', 'Waiting Input')
                     then 1 else 0 end) as open_execution_count,
            sum(case when status = 'Blocked' then 1 else 0 end)
                as blocked_execution_count
        from `tabCFG Kanban Process Execution`
        where kanban_cycle in %(cycle_names)s
        group by kanban_cycle
        """,
        {"cycle_names": cycle_names},
        as_dict=True,
    )
    return {row.kanban_cycle: row for row in rows}


def _participation_totals(cycles):
    cycle_names = tuple(row.name for row in cycles)
    if not cycle_names:
        return {}
    rows = frappe.db.sql(
        """
        select
            kanban_cycle,
            count(*) as participation_segment_count,
            count(distinct employee) as participant_count,
            count(distinct case when status = 'Active' then employee end)
                as active_participant_count,
            sum(
                case
                    when status = 'Active' then
                        greatest(timestampdiff(second, started_on, now()), 0) / 3600
                    else coalesce(duration_seconds, 0) / 3600
                end
            ) as recorded_participation_hours
        from `tabCFG Kanban Job Participation`
        where kanban_cycle in %(cycle_names)s
        group by kanban_cycle
        """,
        {"cycle_names": cycle_names},
        as_dict=True,
    )
    for row in rows:
        row.recorded_participation_hours = flt(row.recorded_participation_hours, 4)
    return {row.kanban_cycle: row for row in rows}


def _columns():
    return [
        {"label": _("Shared Job / Cycle"), "fieldname": "name", "fieldtype": "Link", "options": "CFG Kanban Cycle", "width": 150},
        {"label": _("Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 170},
        {"label": _("Status"), "fieldname": "status", "width": 130},
        {"label": _("Priority"), "fieldname": "priority", "width": 85},
        {"label": _("Card"), "fieldname": "kanban_card", "fieldtype": "Link", "options": "CFG Kanban Card", "width": 125},
        {"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 145},
        {"label": _("Planned Qty"), "fieldname": "planned_qty", "fieldtype": "Float", "width": 105},
        {"label": _("Good Qty"), "fieldname": "actual_good_qty", "fieldtype": "Float", "width": 95},
        {"label": _("Reject Qty"), "fieldname": "reject_qty", "fieldtype": "Float", "width": 95},
        {"label": _("UOM"), "fieldname": "stock_uom", "fieldtype": "Link", "options": "UOM", "width": 80},
        {"label": _("Work Order"), "fieldname": "work_order", "fieldtype": "Link", "options": "Work Order", "width": 135},
        {"label": _("Operations"), "fieldname": "execution_count", "fieldtype": "Int", "width": 85},
        {"label": _("Completed Ops"), "fieldname": "completed_execution_count", "fieldtype": "Int", "width": 105},
        {"label": _("Open Ops"), "fieldname": "open_execution_count", "fieldtype": "Int", "width": 85},
        {"label": _("Blocked Ops"), "fieldname": "blocked_execution_count", "fieldtype": "Int", "width": 95},
        {"label": _("Participants"), "fieldname": "participant_count", "fieldtype": "Int", "width": 95},
        {"label": _("Active Participants"), "fieldname": "active_participant_count", "fieldtype": "Int", "width": 125},
        {"label": _("Participation Segments"), "fieldname": "participation_segment_count", "fieldtype": "Int", "width": 140},
        {"label": _("Recorded Participation Hours"), "fieldname": "recorded_participation_hours", "fieldtype": "Float", "precision": 4, "width": 175},
        {"label": _("Started On"), "fieldname": "started_on", "fieldtype": "Datetime", "width": 150},
        {"label": _("Completed On"), "fieldname": "completed_on", "fieldtype": "Datetime", "width": 150},
        {"label": _("Last Updated"), "fieldname": "modified", "fieldtype": "Datetime", "width": 150},
    ]


def _summary(data):
    return [
        {"value": len(data), "label": _("Jobs Listed"), "datatype": "Int", "indicator": "Blue"},
        {
            "value": sum(row.status not in TERMINAL_CYCLE_STATUSES for row in data),
            "label": _("Open Jobs"),
            "datatype": "Int",
            "indicator": "Orange",
        },
        {
            "value": sum(cint(row.active_participant_count) for row in data),
            "label": _("Active Participants"),
            "datatype": "Int",
            "indicator": "Green",
        },
        {
            "value": sum(cint(row.blocked_execution_count) for row in data),
            "label": _("Blocked Operations"),
            "datatype": "Int",
            "indicator": "Red",
        },
    ]
