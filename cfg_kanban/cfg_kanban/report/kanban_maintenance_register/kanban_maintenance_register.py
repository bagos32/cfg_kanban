import frappe
from frappe import _


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = [
        {"label": _("Task"), "fieldname": "name", "fieldtype": "Link", "options": "CFG Kanban Task", "width": 170},
        {"label": _("Task Name"), "fieldname": "task_name", "width": 220},
        {"label": _("Category"), "fieldname": "task_category", "width": 150},
        {"label": _("Asset"), "fieldname": "asset", "fieldtype": "Link", "options": "Asset", "width": 140},
        {"label": _("Location"), "fieldname": "location", "width": 140},
        {"label": _("Status"), "fieldname": "status", "width": 150},
        {"label": _("Verification"), "fieldname": "verification_status", "width": 130},
        {"label": _("Due On"), "fieldname": "due_on", "fieldtype": "Datetime", "width": 155},
        {"label": _("Completed By"), "fieldname": "completed_by", "fieldtype": "Link", "options": "Employee", "width": 150},
        {"label": _("Completed On"), "fieldname": "completed_on", "fieldtype": "Datetime", "width": 155},
        {"label": _("Verified By"), "fieldname": "verified_by", "fieldtype": "Link", "options": "Employee", "width": 150},
        {"label": _("Verified On"), "fieldname": "verified_on", "fieldtype": "Datetime", "width": 155},
        {"label": _("Media Evidence"), "fieldname": "media_count", "fieldtype": "Int", "width": 115},
        {"label": _("Timeliness"), "fieldname": "timeliness", "width": 100},
    ]
    conditions = ["status in ('Awaiting Verification', 'Correction Required', 'Completed')"]
    values = {}
    if filters.from_date:
        conditions.append("date(completed_on) >= %(from_date)s")
        values["from_date"] = filters.from_date
    if filters.to_date:
        conditions.append("date(completed_on) <= %(to_date)s")
        values["to_date"] = filters.to_date
    for key, column in (("company", "company"), ("category", "task_category"),
                        ("status", "status"), ("verification_status", "verification_status"),
                        ("asset", "asset")):
        if filters.get(key):
            conditions.append(f"`{column}` = %({key})s")
            values[key] = filters.get(key)
    data = frappe.db.sql(f"""
        select name, task_name, task_category, asset, location, status,
               verification_status, due_on, completed_by, completed_on,
               verified_by, verified_on,
               (select count(*) from `tabCFG Kanban Media` m
                 where m.reference_doctype='CFG Kanban Task'
                   and m.reference_name=`tabCFG Kanban Task`.name
                   and m.status='available') as media_count,
               case when completed_on <= due_on then 'On Time' else 'Late' end as timeliness
          from `tabCFG Kanban Task`
         where {' and '.join(conditions)}
         order by completed_on desc, name desc
    """, values, as_dict=True)
    return columns, data
