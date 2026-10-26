import json

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, get_datetime, getdate, now_datetime, today


WORKFORCE_MANAGER_ROLES = {
    "Manufacturing Manager",
    "HR Manager",
    "System Manager",
}
TERMINAL_CYCLE_STATUSES = ("Completed", "Cancelled")


def _require_workforce_manager():
    roles = set(frappe.get_roles())
    if not roles.intersection(WORKFORCE_MANAGER_ROLES):
        frappe.throw(
            _("A workforce supervisor or manager role is required"),
            frappe.PermissionError,
        )
    return roles


@frappe.whitelist()
def get_workforce_action_centre(company=None, workstation=None, expiry_days=30, limit=200):
    """Return permission-aware, read-only workforce supervision queues."""
    _require_workforce_manager()
    limit = min(max(cint(limit) or 200, 1), 500)
    expiry_days = min(max(cint(expiry_days) or 30, 1), 365)
    company = _validated_company(company)

    cycles = _open_cycles(company, limit)
    cycle_names = [row.name for row in cycles]
    role_attention = [
        row for row in cycles
        if row.job_role_compliance_status in ("Pending", "Attention")
    ]
    holds = _compliance_holds(cycle_names, workstation, limit)
    crews = _active_crews(company, workstation, limit)
    competencies = _competency_attention(company, expiry_days, limit)
    participation = _participation_summary(company, workstation, limit)
    approvals = _recent_supervisor_approvals(company, workstation, limit)
    corrections = _correction_requests(company, workstation, limit)

    return {
        "filters": {
            "company": company,
            "workstation": workstation,
            "expiry_days": expiry_days,
        },
        "counts": {
            "active_cycles": len(cycles),
            "role_attention": len(role_attention),
            "compliance_holds": len(holds),
            "active_crews": len(crews),
            "active_people": sum(row["active_count"] for row in crews),
            "on_break": sum(row["break_count"] for row in crews),
            "competency_attention": len(competencies),
            "expired_competencies": sum(row["expiry_state"] == "Expired" for row in competencies),
            "active_participants": participation["active_count"],
            "today_recorded_hours": participation["today_recorded_hours"],
            "recent_supervisor_passes": len(approvals),
            "open_corrections": len(corrections),
        },
        "role_attention": role_attention,
        "compliance_holds": holds,
        "active_crews": crews,
        "competency_attention": competencies,
        "participation": participation,
        "supervisor_approvals": approvals,
        "correction_requests": corrections,
        "generated_on": now_datetime(),
    }


def _validated_company(company):
    company = (company or "").strip() or None
    if not company:
        return None
    doc = frappe.get_doc("Company", company)
    doc.check_permission("read")
    return doc.name


def _open_cycles(company, limit):
    if not (
        frappe.has_permission("CFG Kanban Cycle", "read")
        and frappe.has_permission("CFG Kanban Master", "read")
    ):
        return []
    master_filters = {"control_type": "Production"}
    if company:
        master_filters["company"] = company
    production_masters = frappe.get_list(
        "CFG Kanban Master",
        filters=master_filters,
        pluck="name",
        limit_page_length=0,
    )
    if not production_masters:
        return []
    filters = {
        "status": ["not in", TERMINAL_CYCLE_STATUSES],
        "kanban_master": ["in", production_masters],
    }
    if company:
        filters["company"] = company
    return frappe.get_list(
        "CFG Kanban Cycle",
        filters=filters,
        fields=[
            "name", "company", "kanban_card", "item_code", "status", "priority",
            "blocked", "work_order", "started_on", "modified", "enforce_job_owner",
            "job_owner", "job_owner_name", "job_owner_assigned_on",
            "job_role_compliance_status", "job_role_compliance_summary",
            "job_role_last_evaluated_on",
        ],
        order_by="priority desc, modified desc",
        limit_page_length=limit,
    )


def _compliance_holds(cycle_names, workstation, limit):
    if not cycle_names or not frappe.has_permission("CFG Kanban Process Execution", "read"):
        return []
    filters = {
        "kanban_cycle": ["in", cycle_names],
        "crew_compliance_status": "Hold",
    }
    if workstation:
        filters["workstation"] = workstation
    rows = frappe.get_list(
        "CFG Kanban Process Execution",
        filters=filters,
        fields=[
            "name", "kanban_cycle", "operation", "workstation", "job_card", "status",
            "crew_compliance_status", "last_crew_compliance_check", "crew_compliance_hold",
            "crew_compliance_checked_on",
        ],
        order_by="crew_compliance_checked_on asc",
        limit_page_length=limit,
    )
    check_names = [row.last_crew_compliance_check for row in rows if row.last_crew_compliance_check]
    checks = {}
    if check_names and frappe.has_permission("CFG Kanban Crew Compliance Check", "read"):
        checks = {row.name: row for row in frappe.get_list(
            "CFG Kanban Crew Compliance Check",
            filters={"name": ["in", check_names]},
            fields=[
                "name", "checkpoint", "findings", "checked_on", "crew_session",
                "active_direct_workers", "active_assistants", "active_supervisors",
            ],
            limit_page_length=limit,
        )}
    output = []
    for row in rows:
        check = checks.get(row.last_crew_compliance_check) or frappe._dict()
        findings = _json_value(check.get("findings"), [])
        output.append({
            **row,
            "checkpoint": check.get("checkpoint"),
            "checked_on": check.get("checked_on") or row.crew_compliance_checked_on,
            "crew_session": check.get("crew_session"),
            "active_direct_workers": check.get("active_direct_workers") or 0,
            "active_assistants": check.get("active_assistants") or 0,
            "active_supervisors": check.get("active_supervisors") or 0,
            "findings": findings,
            "finding_summary": _finding_summary(findings),
            "supervision_attention": _contains_supervision_finding(findings),
        })
    return output


def _active_crews(company, workstation, limit):
    if not frappe.has_permission("CFG Kanban Crew Session", "read"):
        return []
    filters = {"status": "Active"}
    if company:
        filters["company"] = company
    if workstation:
        filters["workstation"] = workstation
    sessions = frappe.get_list(
        "CFG Kanban Crew Session",
        filters=filters,
        fields=[
            "name", "company", "workstation", "operation_context", "main_employee",
            "main_employee_name", "started_on", "last_activity_on", "crew_template",
        ],
        order_by="last_activity_on desc",
        limit_page_length=limit,
    )
    session_names = [row.name for row in sessions]
    members = []
    if session_names and frappe.has_permission("CFG Kanban Crew Membership", "read"):
        members = frappe.get_list(
            "CFG Kanban Crew Membership",
            filters={
                "crew_session": ["in", session_names],
                "status": ["in", ["Active", "On Break"]],
            },
            fields=[
                "name", "crew_session", "employee", "employee_name", "crew_role",
                "work_category", "status", "joined_on", "break_started_on",
            ],
            order_by="joined_on asc",
            limit_page_length=limit * 5,
        )
    by_session = {}
    for member in members:
        by_session.setdefault(member.crew_session, []).append(member)
    output = []
    for session in sessions:
        session_members = by_session.get(session.name, [])
        output.append({
            **session,
            "members": session_members,
            "active_count": sum(row.status == "Active" for row in session_members),
            "break_count": sum(row.status == "On Break" for row in session_members),
            "direct_count": sum(
                row.status == "Active" and row.work_category == "Direct Participation"
                for row in session_members
            ),
            "oversight_count": sum(
                row.status == "Active" and row.work_category == "Oversight Only"
                for row in session_members
            ),
        })
    return output


def _competency_attention(company, expiry_days, limit):
    if not (
        frappe.has_permission("CFG Kanban Employee Competency", "read")
        and frappe.has_permission("Employee", "read")
    ):
        return []
    employee_filters = {"status": "Active"}
    if company:
        employee_filters["company"] = company
    employees = frappe.get_list(
        "Employee",
        filters=employee_filters,
        fields=["name", "employee_name", "company", "department", "designation"],
        limit_page_length=limit * 5,
    )
    employee_map = {row.name: row for row in employees}
    if not employee_map:
        return []
    warning_date = add_days(today(), expiry_days)
    rows = frappe.get_list(
        "CFG Kanban Employee Competency",
        filters={
            "employee": ["in", list(employee_map)],
            "status": "Active",
            "valid_until": ["<=", warning_date],
        },
        fields=[
            "name", "employee", "employee_name", "skill", "skill_name",
            "competency_level", "valid_until", "can_work_independently",
            "can_supervise_trainees", "certification_reference",
        ],
        order_by="valid_until asc",
        limit_page_length=limit,
    )
    current_date = getdate(today())
    output = []
    for row in rows:
        employee = employee_map.get(row.employee) or frappe._dict()
        days_remaining = date_diff(getdate(row.valid_until), current_date)
        output.append({
            **row,
            "company": employee.get("company"),
            "department": employee.get("department"),
            "designation": employee.get("designation"),
            "days_remaining": days_remaining,
            "expiry_state": "Expired" if days_remaining < 0 else "Expiring",
        })
    return output


def _participation_summary(company, workstation, limit):
    empty = {
        "active_count": 0,
        "today_recorded_hours": 0,
        "production_hours": 0,
        "oversight_hours": 0,
        "active": [],
        "today": [],
        "payroll_authoritative": False,
    }
    if not frappe.has_permission("CFG Kanban Job Participation", "read"):
        return empty
    filters = {}
    if company:
        filters["company"] = company
    if workstation:
        filters["workstation"] = workstation
    rows = frappe.get_list(
        "CFG Kanban Job Participation",
        filters=filters,
        or_filters={"status": "Active", "ended_on": [">=", today()]},
        fields=[
            "name", "process_execution", "kanban_cycle", "company", "job_card",
            "operation", "workstation", "employee", "employee_name", "crew_role",
            "work_category", "participation_kind", "status", "started_on", "ended_on",
            "duration_hours", "participation_source",
        ],
        order_by="started_on desc",
        limit_page_length=limit * 5,
    )
    current = now_datetime()
    day_start = get_datetime(f"{today()} 00:00:00")
    today_rows = []
    for row in rows:
        started_on = get_datetime(row.started_on)
        ended_on = (
            current if row.status == "Active"
            else get_datetime(row.ended_on) if row.ended_on else None
        )
        if row.status == "Active":
            hours = max((current - started_on).total_seconds() / 3600, 0)
        else:
            hours = flt(row.duration_hours)
        row["effective_hours"] = hours
        if ended_on and ended_on >= day_start:
            today_start = max(started_on, day_start)
            row["today_hours"] = max((ended_on - today_start).total_seconds() / 3600, 0)
            today_rows.append(row)
    production_hours = sum(
        row.today_hours for row in today_rows
        if row.participation_kind == "Production Labour"
    )
    oversight_hours = sum(
        row.today_hours for row in today_rows
        if row.participation_kind == "Oversight"
    )
    return {
        "active_count": sum(row.status == "Active" for row in rows),
        "today_recorded_hours": production_hours + oversight_hours,
        "production_hours": production_hours,
        "oversight_hours": oversight_hours,
        "active": [row for row in rows if row.status == "Active"][:limit],
        "today": today_rows[:limit],
        "payroll_authoritative": False,
    }


def _recent_supervisor_approvals(company, workstation, limit):
    if not frappe.has_permission(
        "CFG Kanban Supervisor Action Approval", "read"
    ):
        return []
    filters = {}
    if company:
        filters["company"] = company
    if workstation:
        filters["workstation"] = workstation
    rows = frappe.get_list(
        "CFG Kanban Supervisor Action Approval",
        filters=filters,
        fields=[
            "name", "action_code", "status", "company", "kanban_cycle",
            "process_execution", "operation", "workstation", "requested_by_employee",
            "approved_by_employee", "approved_by_name", "matched_authority_role",
            "subject_employee", "subject_name", "subject_operator_profile",
            "correction_request", "correction_decision", "action_terminal_user",
            "requested_on", "approved_on", "expires_on", "consumed_on", "reason",
        ],
        order_by="approved_on desc",
        limit_page_length=min(limit, 50),
    )
    current = now_datetime()
    for row in rows:
        row["effective_status"] = (
            "Expired"
            if row.status == "Approved" and row.expires_on
            and get_datetime(row.expires_on) <= current
            else row.status
        )
    return rows


def _correction_requests(company, workstation, limit):
    if not frappe.has_permission("CFG Kanban Correction Request", "read"):
        return []
    filters = {
        "status": ["in", ["Open", "Under Review", "Approved", "ERP Correction Required"]],
    }
    if company:
        filters["company"] = company
    if workstation:
        filters["workstation"] = workstation
    return frappe.get_list(
        "CFG Kanban Correction Request",
        filters=filters,
        fields=[
            "name", "status", "correction_category", "affected_scope", "company",
            "kanban_card", "kanban_cycle", "process_execution", "operation",
            "workstation", "affected_doctype", "affected_document", "reason",
            "requested_change", "evidence_notes", "requested_by_employee",
            "requested_by_name", "requested_on", "reviewed_by_name", "reviewed_on",
            "review_decision", "resolution_type", "erp_correction_doctype",
            "erp_correction_document",
        ],
        order_by="requested_on asc",
        limit_page_length=limit,
    )


def _json_value(value, default):
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _finding_summary(findings):
    if not findings:
        return _("Crew policy is not satisfied")
    if isinstance(findings, dict):
        values = findings.values()
    else:
        values = findings
    parts = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("message") or value.get("reason") or json.dumps(value)
        elif isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        if value:
            parts.append(str(value))
    return "; ".join(parts[:3]) or _("Crew policy is not satisfied")


def _contains_supervision_finding(findings):
    text = json.dumps(findings, default=str).lower()
    return any(word in text for word in ("trainee", "supervisor", "supervision", "mentor"))
