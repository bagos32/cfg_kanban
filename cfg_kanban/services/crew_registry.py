import json

import frappe
from frappe.utils import cint, now_datetime

from cfg_kanban.services.crew_registry_rules import (
    expected_roster_match,
    next_presence_state,
    validate_membership_choice,
)
from cfg_kanban.services.operator_auth import credential_hash, require_operator


@frappe.whitelist()
def open_workstation_crew_session(
    company,
    workstation,
    operator_session_token,
    operation=None,
    crew_template=None,
    notes=None,
):
    actor = _actor(operator_session_token, workstation)
    existing = frappe.db.get_value(
        "CFG Kanban Crew Session",
        {"company": company, "workstation": workstation, "status": "Active"},
        "name",
    )
    if existing:
        frappe.throw(
            f"Workstation {workstation} already has active Crew Session {existing}. "
            "Use the existing persistent crew instead of opening a crew for each job."
        )

    template, roster = _template_snapshot(crew_template, company, workstation, operation)
    current = now_datetime()
    session = frappe.get_doc({
        "doctype": "CFG Kanban Crew Session",
        "company": company,
        "workstation": workstation,
        "operation_context": operation,
        "status": "Active",
        "main_employee": actor["employee"],
        "main_employee_name": actor["employee_name"],
        "main_operator_profile": actor["operator_profile"],
        "crew_template": template.name if template else None,
        "template_revision_snapshot": template.revision if template else None,
        "expected_roster_snapshot": json.dumps(roster),
        "started_on": current,
        "last_activity_on": current,
        "opened_by": frappe.session.user,
        "notes": notes,
    }).insert(ignore_permissions=True)

    _record_event(session, "Open Session", actor, new_state="Active")
    expected = expected_roster_match(roster, actor["employee"])
    membership = _insert_membership(
        session,
        actor["employee"],
        actor["employee_name"],
        actor["operator_profile"],
        "Main Operator",
        "Direct Participation",
        "Session Owner Scan",
        actor,
        expected,
    )
    session.db_set("main_membership", membership.name, update_modified=False)
    return get_crew_session(session.name, operator_session_token)


@frappe.whitelist()
def join_crew_member(
    crew_session,
    member_qr_token,
    operator_session_token,
    crew_role="Supporting Operator",
    work_category="Direct Participation",
    reason=None,
):
    session = _active_session(crew_session)
    actor = _actor(operator_session_token, session.workstation)
    _assert_actor_can_manage(session, actor)
    try:
        validate_membership_choice(crew_role, work_category)
    except ValueError as exc:
        frappe.throw(str(exc))
    identity = _scanned_identity(member_qr_token, session.company)
    duplicate = frappe.db.get_value(
        "CFG Kanban Crew Membership",
        {
            "crew_session": session.name,
            "employee": identity["employee"],
            "status": ["in", ["Active", "On Break"]],
        },
        "name",
    )
    if duplicate:
        frappe.throw(f"Employee {identity['employee']} is already present in membership {duplicate}")
    if crew_role == "Main Operator":
        frappe.throw("Use Change Main Operator after the employee has joined the crew")

    roster = _json_list(session.expected_roster_snapshot)
    expected = expected_roster_match(roster, identity["employee"])
    membership = _insert_membership(
        session,
        identity["employee"],
        identity["employee_name"],
        identity["operator_profile"],
        crew_role,
        work_category,
        "Employee QR Scan",
        actor,
        expected,
        reason,
    )
    return _public_membership(membership)


@frappe.whitelist()
def break_crew_member(crew_session, member_qr_token, operator_session_token, reason=None):
    return _transition_scanned_member(
        crew_session, member_qr_token, operator_session_token, "Break", reason
    )


@frappe.whitelist()
def resume_crew_member(crew_session, member_qr_token, operator_session_token, reason=None):
    return _transition_scanned_member(
        crew_session, member_qr_token, operator_session_token, "Resume", reason
    )


@frappe.whitelist()
def leave_crew_member(crew_session, member_qr_token, operator_session_token, reason=None):
    session = _active_session(crew_session)
    actor = _actor(operator_session_token, session.workstation)
    _assert_actor_can_manage(session, actor)
    identity = _scanned_identity(member_qr_token, session.company)
    membership = _present_membership(session.name, identity["employee"])
    if membership.name == session.main_membership:
        frappe.throw("Change the Main Operator or close the Crew Session before the main employee leaves")
    return _transition_membership(session, membership, "Leave", actor, reason)


@frappe.whitelist()
def change_main_operator(crew_session, member_qr_token, operator_session_token, reason=None):
    session = _active_session(crew_session)
    actor = _actor(operator_session_token, session.workstation)
    _assert_actor_can_manage(session, actor)
    identity = _scanned_identity(member_qr_token, session.company)
    replacement = _present_membership(session.name, identity["employee"])
    if replacement.status != "Active":
        frappe.throw("The new Main Operator must be actively present, not on break")
    if replacement.name == session.main_membership:
        return get_crew_session(session.name, operator_session_token)

    previous = frappe.get_doc("CFG Kanban Crew Membership", session.main_membership)
    previous_role = previous.crew_role
    replacement_role = replacement.crew_role
    previous.db_set({
        "crew_role": "Supporting Operator",
        "last_event": "Change Main Operator",
        "last_event_on": now_datetime(),
    }, update_modified=False)
    replacement.db_set({
        "crew_role": "Main Operator",
        "work_category": "Direct Participation",
        "last_event": "Change Main Operator",
        "last_event_on": now_datetime(),
    }, update_modified=False)
    session.db_set({
        "main_employee": replacement.employee,
        "main_employee_name": replacement.employee_name,
        "main_operator_profile": replacement.operator_profile,
        "main_membership": replacement.name,
        "last_activity_on": now_datetime(),
    }, update_modified=False)
    _record_event(
        session,
        "Change Main Operator",
        actor,
        membership=replacement,
        subject_employee=replacement.employee,
        previous_state=previous.employee,
        new_state=replacement.employee,
        reason=reason,
        details={
            "previous_membership": previous.name,
            "previous_role": previous_role,
            "replacement_membership": replacement.name,
            "replacement_previous_role": replacement_role,
        },
    )
    return get_crew_session(session.name, operator_session_token)


@frappe.whitelist()
def set_crew_operation_context(crew_session, operation, operator_session_token, reason=None):
    session = _active_session(crew_session)
    actor = _actor(operator_session_token, session.workstation)
    _assert_actor_can_manage(session, actor)
    previous = session.operation_context
    session.db_set({
        "operation_context": operation or None,
        "last_activity_on": now_datetime(),
    }, update_modified=False)
    _record_event(
        session,
        "Context Change",
        actor,
        previous_state=previous,
        new_state=operation,
        reason=reason,
    )
    return get_crew_session(session.name, operator_session_token)


@frappe.whitelist()
def close_workstation_crew_session(crew_session, operator_session_token, reason):
    session = _active_session(crew_session)
    actor = _actor(operator_session_token, session.workstation)
    _assert_actor_can_manage(session, actor)
    if not (reason or "").strip():
        frappe.throw("Close Reason is required")
    current = now_datetime()
    memberships = frappe.get_all(
        "CFG Kanban Crew Membership",
        filters={"crew_session": session.name, "status": ["in", ["Active", "On Break"]]},
        pluck="name",
    )
    for name in memberships:
        membership = frappe.get_doc("CFG Kanban Crew Membership", name)
        membership.db_set({
            "status": "Left",
            "break_started_on": None,
            "left_on": current,
            "left_by_employee": actor["employee"],
            "last_event": "Close Session",
            "last_event_on": current,
        }, update_modified=False)
        _record_event(
            session,
            "Leave",
            actor,
            membership=membership,
            subject_employee=membership.employee,
            previous_state="Active/On Break",
            new_state="Left",
            reason="Crew Session closed: " + reason.strip(),
        )
    session.db_set({
        "status": "Closed",
        "last_activity_on": current,
        "ended_on": current,
        "closed_by": frappe.session.user,
        "close_reason": reason.strip(),
    }, update_modified=False)
    _record_event(session, "Close Session", actor, previous_state="Active", new_state="Closed", reason=reason)
    return {"crew_session": session.name, "status": "Closed", "ended_on": current}


@frappe.whitelist()
def get_crew_session(crew_session, operator_session_token):
    session = frappe.get_doc("CFG Kanban Crew Session", crew_session)
    _actor(operator_session_token, session.workstation)
    members = frappe.get_all(
        "CFG Kanban Crew Membership",
        filters={"crew_session": session.name},
        fields=[
            "name", "employee", "employee_name", "operator_profile", "crew_role",
            "work_category", "status", "joined_on", "break_started_on", "left_on",
            "expected_from_template",
        ],
        order_by="joined_on asc",
    )
    return {
        "name": session.name,
        "company": session.company,
        "workstation": session.workstation,
        "operation_context": session.operation_context,
        "status": session.status,
        "main_employee": session.main_employee,
        "main_employee_name": session.main_employee_name,
        "crew_template": session.crew_template,
        "template_revision_snapshot": session.template_revision_snapshot,
        "expected_roster": _json_list(session.expected_roster_snapshot),
        "started_on": session.started_on,
        "ended_on": session.ended_on,
        "members": members,
    }


def get_active_workstation_crew(company, workstation):
    """Internal P04 boundary: return registered presence without deciding authorization."""
    session_name = frappe.db.get_value(
        "CFG Kanban Crew Session",
        {"company": company, "workstation": workstation, "status": "Active"},
        "name",
    )
    if not session_name:
        return None
    session = frappe.get_doc("CFG Kanban Crew Session", session_name)
    members = frappe.get_all(
        "CFG Kanban Crew Membership",
        filters={"crew_session": session_name, "status": ["in", ["Active", "On Break"]]},
        fields=[
            "name", "employee", "employee_name", "operator_profile", "crew_role",
            "work_category", "status", "joined_on", "break_started_on",
        ],
        order_by="joined_on asc",
    )
    return {"session": session, "members": members}


def _transition_scanned_member(crew_session, member_qr_token, operator_session_token, event_type, reason):
    session = _active_session(crew_session)
    actor = _actor(operator_session_token, session.workstation)
    _assert_actor_can_manage(session, actor)
    identity = _scanned_identity(member_qr_token, session.company)
    membership = _present_membership(session.name, identity["employee"])
    return _transition_membership(session, membership, event_type, actor, reason)


def _transition_membership(session, membership, event_type, actor, reason):
    try:
        new_state = next_presence_state(membership.status, event_type)
    except ValueError as exc:
        frappe.throw(str(exc))
    previous_state = membership.status
    current = now_datetime()
    updates = {"status": new_state, "last_event": event_type, "last_event_on": current}
    if event_type == "Break":
        updates["break_started_on"] = current
    elif event_type == "Resume":
        updates["break_started_on"] = None
    elif event_type == "Leave":
        updates.update({
            "break_started_on": None,
            "left_on": current,
            "left_by_employee": actor["employee"],
        })
    membership.db_set(updates, update_modified=False)
    session.db_set("last_activity_on", current, update_modified=False)
    _record_event(
        session,
        event_type,
        actor,
        membership=membership,
        subject_employee=membership.employee,
        previous_state=previous_state,
        new_state=new_state,
        reason=reason,
    )
    return _public_membership(membership)


def _insert_membership(
    session,
    employee,
    employee_name,
    operator_profile,
    crew_role,
    work_category,
    join_source,
    actor,
    expected=None,
    reason=None,
):
    current = now_datetime()
    membership = frappe.get_doc({
        "doctype": "CFG Kanban Crew Membership",
        "crew_session": session.name,
        "company": session.company,
        "workstation": session.workstation,
        "operation_context": session.operation_context,
        "employee": employee,
        "employee_name": employee_name,
        "operator_profile": operator_profile,
        "crew_role": crew_role,
        "work_category": work_category,
        "status": "Active",
        "join_source": join_source,
        "expected_from_template": 1 if expected else 0,
        "template_member_reference": expected.get("row_name") if expected else None,
        "joined_on": current,
        "joined_by_employee": actor["employee"],
        "last_event": "Join",
        "last_event_on": current,
    }).insert(ignore_permissions=True)
    session.db_set("last_activity_on", current, update_modified=False)
    _record_event(
        session,
        "Join",
        actor,
        membership=membership,
        subject_employee=employee,
        new_state="Active",
        reason=reason,
        details={
            "crew_role": crew_role,
            "work_category": work_category,
            "expected_from_template": bool(expected),
        },
    )
    return membership


def _actor(operator_session_token, workstation):
    profile, operator_session = require_operator(
        operator_session_token, workstation=workstation
    )
    employee_name = frappe.db.get_value("Employee", operator_session.employee, "employee_name")
    return {
        "employee": operator_session.employee,
        "employee_name": employee_name or operator_session.employee,
        "operator_profile": None if operator_session.development_proxy else operator_session.operator_profile,
        "operator_session": operator_session.name,
        "terminal_user": operator_session.terminal_user,
        "can_override": bool(cint(profile.get("can_override"))),
        "kanban_role": profile.get("kanban_role"),
    }


def _assert_actor_can_manage(session, actor):
    present = frappe.db.exists(
        "CFG Kanban Crew Membership",
        {
            "crew_session": session.name,
            "employee": actor["employee"],
            "status": "Active",
        },
    )
    if not present and not actor["can_override"] and actor["kanban_role"] != "Supervisor":
        frappe.throw("Only an active crew member or authorized supervisor can change this crew")


def _scanned_identity(qr_token, company):
    profile_name = frappe.db.get_value(
        "CFG Kanban Operator Profile",
        {"qr_token_hash": credential_hash(qr_token), "active": 1},
        "name",
    )
    if not profile_name:
        frappe.throw("Unknown or inactive employee credential")
    profile = frappe.get_doc("CFG Kanban Operator Profile", profile_name)
    employee = frappe.db.get_value(
        "Employee", profile.employee, ["employee_name", "status", "company"], as_dict=True
    )
    if not employee or employee.status != "Active":
        frappe.throw("The scanned employee is not active")
    if company and employee.company and employee.company != company:
        frappe.throw(f"The scanned employee does not belong to Company {company}")
    return {
        "employee": profile.employee,
        "employee_name": employee.employee_name or profile.employee,
        "operator_profile": profile.name,
    }


def _active_session(name):
    session = frappe.get_doc("CFG Kanban Crew Session", name)
    if session.status != "Active":
        frappe.throw(f"Crew Session {name} is closed")
    return session


def _present_membership(crew_session, employee):
    name = frappe.db.get_value(
        "CFG Kanban Crew Membership",
        {
            "crew_session": crew_session,
            "employee": employee,
            "status": ["in", ["Active", "On Break"]],
        },
        "name",
    )
    if not name:
        frappe.throw(f"Employee {employee} is not present in Crew Session {crew_session}")
    return frappe.get_doc("CFG Kanban Crew Membership", name)


def _template_snapshot(template_name, company, workstation, operation):
    if not template_name:
        return None, []
    template = frappe.get_doc("CFG Kanban Crew Template", template_name)
    if template.docstatus != 1 or not cint(template.active):
        frappe.throw(f"Crew Template {template.name} is not approved and active")
    if template.company != company:
        frappe.throw(f"Crew Template {template.name} belongs to another Company")
    if template.workstation != workstation:
        frappe.throw(f"Crew Template {template.name} belongs to another Workstation")
    if template.operation and operation and template.operation != operation:
        frappe.throw(f"Crew Template {template.name} belongs to another Operation")
    roster = [{
        "row_name": row.name,
        "employee": row.employee,
        "employee_name": row.employee_name,
        "operator_profile": row.operator_profile,
        "crew_role": row.crew_role,
        "work_category": row.work_category,
    } for row in template.members]
    return template, roster


def _record_event(
    session,
    event_type,
    actor,
    membership=None,
    subject_employee=None,
    previous_state=None,
    new_state=None,
    reason=None,
    details=None,
):
    employee = subject_employee or (membership.employee if membership else None)
    employee_name = (
        frappe.db.get_value("Employee", employee, "employee_name") if employee else None
    )
    return frappe.get_doc({
        "doctype": "CFG Kanban Crew Event",
        "crew_session": session.name,
        "crew_membership": membership.name if membership else None,
        "company": session.company,
        "workstation": session.workstation,
        "operation_context": session.operation_context,
        "event_type": event_type,
        "occurred_on": now_datetime(),
        "subject_employee": employee,
        "subject_employee_name": employee_name,
        "previous_state": previous_state,
        "new_state": new_state,
        "actor_employee": actor["employee"],
        "actor_operator_profile": actor["operator_profile"],
        "operator_session": actor["operator_session"],
        "terminal_user": actor["terminal_user"],
        "reason": reason,
        "event_details": json.dumps(details or {}),
    }).insert(ignore_permissions=True)


def _json_list(value):
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _public_membership(membership):
    return {
        "name": membership.name,
        "employee": membership.employee,
        "employee_name": membership.employee_name,
        "crew_role": membership.crew_role,
        "work_category": membership.work_category,
        "status": membership.status,
        "joined_on": membership.joined_on,
        "break_started_on": membership.break_started_on,
        "left_on": membership.left_on,
        "expected_from_template": bool(cint(membership.expected_from_template)),
    }
