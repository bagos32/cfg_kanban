import frappe
from frappe import _
from frappe.utils import cint, getdate, today


LEVEL_RANKS = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4}


def competency_level_code(value):
    return (value or "").split(" - ", 1)[0].strip().upper()


def competency_level_rank(value):
    code = competency_level_code(value)
    if code not in LEVEL_RANKS:
        frappe.throw(_("Unknown competency level {0}").format(value))
    return LEVEL_RANKS[code]


def effective_competency_status(record, on_date=None):
    record = frappe._dict(record)
    check_date = getdate(on_date or today())
    if cint(record.docstatus) != 1:
        return "Draft"
    if record.status != "Active":
        return record.status or "Inactive"
    if record.effective_from and getdate(record.effective_from) > check_date:
        return "Not Yet Effective"
    if record.valid_until and getdate(record.valid_until) < check_date:
        return "Expired"
    return "Active"


def employee_has_competency(employee, skill, minimum_level="L0", *,
                            require_independent=False, require_supervisor=False,
                            on_date=None):
    required_rank = competency_level_rank(minimum_level)
    for row in _competency_rows(employee, skill=skill):
        if effective_competency_status(row, on_date) != "Active":
            continue
        if competency_level_rank(row.competency_level) < required_rank:
            continue
        if require_independent and not cint(row.can_work_independently):
            continue
        if require_supervisor and not cint(row.can_supervise_trainees):
            continue
        return True
    return False


@frappe.whitelist()
def get_operator_profile_competency_summary(profile_name):
    if not frappe.has_permission("CFG Kanban Operator Profile", "read", profile_name):
        frappe.throw(_("Not permitted to read this Operator Profile"), frappe.PermissionError)
    if not frappe.has_permission("CFG Kanban Employee Competency", "read"):
        frappe.throw(_("Not permitted to read Employee Competency"), frappe.PermissionError)
    employee = frappe.db.get_value("CFG Kanban Operator Profile", profile_name, "employee")
    if not employee:
        return []
    result = []
    for row in _competency_rows(employee):
        row["effective_status"] = effective_competency_status(row)
        row["level_code"] = competency_level_code(row.competency_level)
        result.append(row)
    return result


@frappe.whitelist()
def change_competency_status(competency_name, status, reason):
    if status not in ("Active", "Suspended", "Revoked"):
        frappe.throw(_("Invalid competency status"))
    doc = frappe.get_doc("CFG Kanban Employee Competency", competency_name)
    doc.check_permission("write")
    if cint(doc.docstatus) != 1:
        frappe.throw(_("Only a submitted competency authorization can change status"))
    if doc.status == "Revoked":
        frappe.throw(_("A revoked competency cannot be reactivated; create a new approval"))
    if doc.status == status:
        return {"name": doc.name, "status": doc.status}
    if not (reason or "").strip():
        frappe.throw(_("A status change reason is required"))
    doc.status = status
    doc.status_reason = reason.strip()
    doc.save()
    return {"name": doc.name, "status": doc.status}


def _competency_rows(employee, skill=None):
    filters = {"employee": employee, "docstatus": ["<", 2]}
    if skill:
        filters["skill"] = skill
    return frappe.get_all(
        "CFG Kanban Employee Competency",
        filters=filters,
        fields=[
            "name", "docstatus", "employee", "skill", "skill_name", "competency_level",
            "can_work_independently", "can_supervise_trainees", "effective_from",
            "valid_until", "status", "approved_by", "approved_on",
        ],
        order_by="skill asc, effective_from desc, creation desc",
        limit_page_length=0,
    )
