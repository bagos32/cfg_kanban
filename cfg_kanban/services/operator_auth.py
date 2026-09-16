import hashlib
import hmac
import secrets

import frappe
from frappe.utils import add_to_date, cint, get_datetime, now_datetime


ACTION_FLAGS = {
    "consume": "can_start",
    "start": "can_start",
    "complete": "can_complete",
    "report_progress": "can_partial_complete",
    "report_reject": "can_report_reject",
    "physical_handoff": "can_complete",
    "override": "can_override",
    "reopen": "can_reopen",
    "task_start": "can_start",
    "task_complete": "can_complete",
    "task_verify": "can_verify_tasks",
}


def credential_hash(value):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def new_credential():
    return secrets.token_urlsafe(32)


def open_session(qr_token, pin=None, station=None):
    _require_terminal_user()
    profile_name = frappe.db.get_value(
        "CFG Kanban Operator Profile", {"qr_token_hash": credential_hash(qr_token)}, "name"
    )
    if not profile_name:
        frappe.throw("Unknown operator credential")
    profile = frappe.get_doc("CFG Kanban Operator Profile", profile_name)
    if not profile.active:
        frappe.throw("This Kanban operator profile is inactive")
    employee_status = frappe.db.get_value("Employee", profile.employee, "status")
    if employee_status and employee_status != "Active":
        frappe.throw("This employee is not active")
    if profile.pin_required:
        saved_pin = profile.get_password("pin", raise_exception=False)
        if not saved_pin or not hmac.compare_digest(str(pin or ""), str(saved_pin)):
            frappe.throw("Invalid operator PIN")

    terminal_user = frappe.session.user
    _close_active_sessions(terminal_user, station, "Operator Switched")
    raw_token = new_credential()
    current = now_datetime()
    timeout = _timeout_minutes()
    session = frappe.get_doc({
        "doctype": "CFG Kanban Operator Session",
        "operator_profile": profile.name,
        "employee": profile.employee,
        "terminal_user": terminal_user,
        "station": station,
        "session_token_hash": credential_hash(raw_token),
        "started_on": current,
        "last_activity_on": current,
        "expires_on": add_to_date(current, minutes=timeout),
        "active": 1,
    }).insert(ignore_permissions=True)
    return {"session_token": raw_token, "operator": public_operator(profile, session)}


def open_development_proxy_session(employee, station=None):
    if frappe.session.user != "Administrator":
        frappe.throw("Only Administrator can use the development operator bypass")
    if not cint(frappe.db.get_single_value(
            "CFG Kanban Settings", "enable_administrator_operator_bypass")):
        frappe.throw("Administrator operator bypass is disabled in CFG Kanban Settings")
    employee_details = frappe.db.get_value(
        "Employee", employee, ["name", "employee_name", "status"], as_dict=True
    )
    if not employee_details:
        frappe.throw("Employee was not found")
    if employee_details.status and employee_details.status != "Active":
        frappe.throw("This employee is not active")

    terminal_user = frappe.session.user
    _close_active_sessions(terminal_user, station, "Development Proxy Switched")
    raw_token = new_credential()
    current = now_datetime()
    session = frappe.get_doc({
        "doctype": "CFG Kanban Operator Session",
        "employee": employee_details.name,
        "terminal_user": terminal_user,
        "station": station,
        "session_token_hash": credential_hash(raw_token),
        "started_on": current,
        "last_activity_on": current,
        "expires_on": add_to_date(current, minutes=_timeout_minutes()),
        "active": 1,
        "development_proxy": 1,
        "proxy_authorized_by": terminal_user,
    }).insert(ignore_permissions=True)
    profile = _development_proxy_profile(employee_details.name)
    return {"session_token": raw_token, "operator": public_operator(profile, session)}


def require_operator(session_token, action=None, execution=None, operation=None, workstation=None):
    _require_terminal_user()
    if not session_token:
        frappe.throw("Scan your operator QR before using Kanban")
    session_name = frappe.db.get_value(
        "CFG Kanban Operator Session",
        {"session_token_hash": credential_hash(session_token), "active": 1}, "name",
    )
    if not session_name:
        frappe.throw("Operator session is not active; scan your operator QR again")
    session = frappe.get_doc("CFG Kanban Operator Session", session_name)
    if session.terminal_user != frappe.session.user:
        frappe.throw("Operator session belongs to a different terminal login")
    current = now_datetime()
    if session.expires_on and get_datetime(session.expires_on) <= current:
        _close_session(session, "Inactive Timeout")
        frappe.throw("Operator session expired due to inactivity; scan your QR again")
    if session.development_proxy:
        if (frappe.session.user != "Administrator" or
                not cint(frappe.db.get_single_value(
                    "CFG Kanban Settings", "enable_administrator_operator_bypass"))):
            _close_session(session, "Development Bypass Disabled")
            frappe.throw("Administrator operator bypass is no longer available")
        profile = _development_proxy_profile(session.employee)
    else:
        profile = frappe.get_doc("CFG Kanban Operator Profile", session.operator_profile)
        if not profile.active:
            _close_session(session, "Profile Deactivated")
            frappe.throw("This Kanban operator profile is inactive")
    if execution:
        execution = execution if getattr(execution, "doctype", None) else frappe.get_doc(
            "CFG Kanban Process Execution", execution
        )
        operation = operation or execution.operation
        workstation = workstation or execution.workstation
    if action:
        flag = ACTION_FLAGS.get(action)
        if not flag or not cint(profile.get(flag)):
            frappe.throw(f"Operator is not authorized to {action.replace('_', ' ')}")
    allowed_operations = {row.operation for row in profile.allowed_operations if row.operation}
    if allowed_operations and operation and operation not in allowed_operations:
        frappe.throw(f"Operator is not authorized for operation {operation}")
    allowed_workstations = {row.workstation for row in profile.allowed_workstations if row.workstation}
    if allowed_workstations and workstation and workstation not in allowed_workstations:
        frappe.throw(f"Operator is not authorized for workstation {workstation}")
    session.db_set({"last_activity_on": current,
                    "expires_on": add_to_date(current, minutes=_timeout_minutes())},
                   update_modified=False)
    return profile, session


def get_session(session_token):
    profile, session = require_operator(session_token)
    return public_operator(profile, session)


def close_session(session_token, reason="Operator Logout"):
    _require_terminal_user()
    session_name = frappe.db.get_value(
        "CFG Kanban Operator Session", {"session_token_hash": credential_hash(session_token)}, "name"
    )
    if not session_name:
        return {"employee": None, "closed": True}
    session = frappe.get_doc("CFG Kanban Operator Session", session_name)
    if session.terminal_user != frappe.session.user:
        frappe.throw("Operator session belongs to a different terminal login")
    if session.active:
        _close_session(session, reason)
    return {"employee": session.employee, "closed": True}


def public_operator(profile, session):
    employee_name = frappe.db.get_value("Employee", profile.employee, "employee_name")
    return {
        "employee": profile.employee,
        "employee_name": employee_name or profile.employee,
        "operator_profile": profile.name,
        "kanban_role": profile.kanban_role,
        "station": session.station,
        "started_on": session.started_on,
        "expires_on": session.expires_on,
        "development_proxy": bool(cint(session.development_proxy)),
        "permissions": {action: bool(cint(profile.get(flag))) for action, flag in ACTION_FLAGS.items()},
    }


def _development_proxy_profile(employee):
    values = {"name": "Administrator Development Proxy", "employee": employee,
              "active": 1, "kanban_role": "Development Proxy",
              "allowed_operations": [], "allowed_workstations": []}
    for flag in set(ACTION_FLAGS.values()):
        values[flag] = 1
    return frappe._dict(values)


def _timeout_minutes():
    value = frappe.db.get_single_value("CFG Kanban Settings", "operator_session_timeout_minutes")
    return max(1, cint(value or 15))


def _require_terminal_user():
    if not getattr(frappe, "session", None) or frappe.session.user in (None, "", "Guest"):
        frappe.throw("An authenticated Kanban terminal user is required")
    allowed = {"Kanban Terminal", "Manufacturing Manager", "System Manager"}
    if not allowed.intersection(frappe.get_roles(frappe.session.user)):
        frappe.throw("ERP user is not authorized as a Kanban terminal")


def _close_active_sessions(terminal_user, station, reason):
    filters = {"terminal_user": terminal_user, "active": 1}
    if station:
        filters["station"] = station
    for name in frappe.get_all("CFG Kanban Operator Session", filters=filters, pluck="name"):
        _close_session(frappe.get_doc("CFG Kanban Operator Session", name), reason)


def _close_session(session, reason):
    session.db_set({"active": 0, "ended_on": now_datetime(), "end_reason": reason},
                   update_modified=False)
