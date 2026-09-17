import frappe
from frappe import _


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = [
        {"label": _("Task"), "fieldname": "task", "fieldtype": "Link", "options": "CFG Kanban Task", "width": 170},
        {"label": _("Task Name"), "fieldname": "task_name", "width": 210},
        {"label": _("Media ID"), "fieldname": "media_id", "fieldtype": "Link", "options": "CFG Kanban Media", "width": 180},
        {"label": _("Evidence Type"), "fieldname": "evidence_type", "width": 120},
        {"label": _("Capture Stage"), "fieldname": "capture_on", "width": 110},
        {"label": _("Evidence"), "fieldname": "label", "width": 240},
        {"label": _("Result / Value"), "fieldname": "value", "width": 170},
        {"label": _("Unit"), "fieldname": "unit", "width": 80},
        {"label": _("Captured By"), "fieldname": "captured_by", "fieldtype": "Link", "options": "Employee", "width": 150},
        {"label": _("Captured On"), "fieldname": "captured_on", "fieldtype": "Datetime", "width": 155},
        {"label": _("Verification"), "fieldname": "verification_status", "width": 120},
    ]
    conditions = ["t.status in ('Awaiting Verification', 'Correction Required', 'Completed')"]
    values = {}
    if filters.task:
        conditions.append("t.name = %(task)s")
        values["task"] = filters.task
    if filters.from_date:
        conditions.append("date(t.completed_on) >= %(from_date)s")
        values["from_date"] = filters.from_date
    if filters.to_date:
        conditions.append("date(t.completed_on) <= %(to_date)s")
        values["to_date"] = filters.to_date
    if filters.verification_status:
        conditions.append("t.verification_status = %(verification_status)s")
        values["verification_status"] = filters.verification_status
    where = " and ".join(conditions)
    parts = []
    if not filters.evidence_type or filters.evidence_type == "Checklist":
        parts.append(f"""select t.name as task, t.task_name, null as media_id, 'Checklist' as evidence_type,
            'Complete' as capture_on, c.item as label, c.result as value, '' as unit,
            c.captured_by, c.captured_on, t.verification_status
            from `tabCFG Kanban Task` t join `tabCFG Kanban Checklist Result` c
              on c.parent=t.name and c.parenttype='CFG Kanban Task'
            where {where}""")
    if not filters.evidence_type or filters.evidence_type == "Dynamic Field":
        parts.append(f"""select t.name as task, t.task_name, null as media_id, 'Dynamic Field' as evidence_type,
            v.capture_on, v.label, v.value, v.unit, v.captured_by, v.captured_on,
            t.verification_status
            from `tabCFG Kanban Task` t join `tabCFG Kanban Execution Value` v
              on v.parent=t.name and v.parenttype='CFG Kanban Task'
            where {where}""")
    if not filters.evidence_type or filters.evidence_type == "Media":
        parts.append(f"""select t.name as task, t.task_name, m.media_id,
            'Media' as evidence_type, 'Complete' as capture_on,
            m.media_class as label, m.original_filename as value,
            m.content_type as unit, m.operator_employee as captured_by,
            m.confirmed_at as captured_on,
            t.verification_status
            from `tabCFG Kanban Task` t join `tabCFG Kanban Media` m
              on m.reference_doctype='CFG Kanban Task' and m.reference_name=t.name
             and m.status='available'
            where {where}""")
    if not parts:
        return columns, []
    data = frappe.db.sql(" union all ".join(parts) + " order by captured_on desc, task desc",
                         values, as_dict=True)
    return columns, data
