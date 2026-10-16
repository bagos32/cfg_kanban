"""Controlled mapper/writer for one allowlisted DocType Action target.

The browser may supply values only for pinned Operator Input mappings.  Target
selection, fixed/context values, task evidence, destination metadata and posting
policy are all resolved again on the server.  Target writes use the authenticated
terminal User's normal Frappe permissions and controller validations; this module
never uses ``ignore_permissions`` for a destination document.
"""

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime

from cfg_kanban.services.doctype_action_runs import (
    assert_pinned_snapshot_compatible,
    authorize_run_actor,
    get_attempt_for_retry_token,
    get_locked_run,
    public_run,
    record_run_attempt,
    sanitize_error,
    transition_run,
)
from cfg_kanban.services.doctype_action_tasks import release_task_gate
from cfg_kanban.services.idempotency import canonical_key


MAX_TEXT_LENGTH = 20000
SAFE_TASK_FIELDS = {
    "task_name", "task_category", "priority", "requested_on", "due_on",
    "assigned_employee", "responsible_role", "workstation", "asset", "location",
    "started_by", "started_on", "completed_by", "completed_on",
    "completion_notes", "verification_status", "verified_by", "verified_on",
    "verification_notes", "blocked_reason",
}
BLOCKED_RUN_STATES = {"Cancelled", "Skipped by Condition", "Needs Reconciliation"}


def get_operator_form(run_name, operator_session_token):
    run = frappe.get_doc("CFG Kanban DocType Action Run", run_name)
    task, profile, _session = authorize_run_actor(run, operator_session_token)
    snapshot = assert_pinned_snapshot_compatible(run)
    meta = frappe.get_meta(run.target_doctype)
    configuration = snapshot["configuration"]
    payload = _stored_payload(run)
    current_parent = {}
    for mapping in configuration.get("parent") or []:
        current = (payload.get("parent") or {}).get(mapping["fieldname"])
        if current is None:
            if mapping.get("source_type") == "Operator Input":
                current = mapping.get("default_value")
            else:
                current = _resolve_mapping_value(mapping, task, profile, {})
        current_parent[mapping["fieldname"]] = current
    condition_values = _condition_context(task, profile, current_parent)
    parent_fields = []
    for mapping in sorted(configuration.get("parent") or [], key=_display_order):
        if not cint(mapping.get("show_to_operator", 1)):
            continue
        field = meta.get_field(mapping["fieldname"])
        if not field:
            continue
        parent_fields.append(_form_field(
            field,
            mapping,
            current_parent.get(mapping["fieldname"]),
            visible=_condition_matches(
                mapping.get("visible_condition"), condition_values
            ),
        ))

    child_tables = []
    saved_children = payload.get("children") or {}
    columns_by_table = _columns_by_table(configuration)
    for table in sorted(configuration.get("tables") or [], key=_display_order):
        table_field = meta.get_field(table["table_fieldname"])
        if not table_field:
            continue
        child_meta = frappe.get_meta(table_field.options)
        columns = []
        for mapping in columns_by_table.get(table["table_fieldname"], []):
            child_field = child_meta.get_field(mapping["fieldname"])
            if child_field and cint(mapping.get("show_to_operator", 1)):
                default = mapping.get("default_value")
                if mapping.get("source_type") != "Operator Input":
                    default = _resolve_mapping_value(mapping, task, profile, {})
                columns.append(_form_field(child_field, mapping, default))
        child_tables.append({
            "fieldname": table["table_fieldname"],
            "label": table.get("operator_heading") or table_field.label,
            "rows_mode": table.get("rows_mode"),
            "min_rows": cint(table.get("min_rows")),
            "max_rows": cint(table.get("max_rows")),
            "allow_add_delete_rows": bool(cint(table.get("allow_add_delete_rows"))),
            "columns": columns,
            "rows": saved_children.get(table["table_fieldname"]) or [],
        })

    return {
        "run": public_run(run),
        "form_title": configuration.get("form_title") or snapshot.get("profile_name"),
        "form_instructions": configuration.get("form_instructions"),
        "posting_policy": configuration.get("posting_policy"),
        "task": {
            "name": task.name,
            "task_name": task.task_name,
            "company": task.company,
            "location": task.location,
        },
        "operator": profile.employee,
        "parent_fields": parent_fields,
        "child_tables": child_tables,
        # Only values deliberately referenced by a configured condition are
        # returned. This permits truthful client-side visibility without
        # exposing the rest of the Task/context payload.
        "condition_context": _condition_context_for_form(
            configuration, condition_values
        ),
        "last_error_code": run.last_error_code,
        "last_error": run.last_error,
        "target_link": _target_link(run),
    }


def post_action(run_name, operator_session_token, retry_token,
                operator_values=None, child_rows=None):
    if not retry_token or len(str(retry_token)) < 12:
        frappe.throw(_("A fresh opaque posting token is required."))
    run = get_locked_run(run_name)
    task, profile, session = authorize_run_actor(run, operator_session_token)
    request_state = run.state

    duplicate = get_attempt_for_retry_token(retry_token)
    if duplicate:
        if duplicate.action_run != run.name:
            frappe.throw(_("This posting token was already used for a different Action Run."))
        return _attempt_result(run, duplicate, deduplicated=True)

    if run.state in BLOCKED_RUN_STATES:
        frappe.throw(_("Action Run cannot post while it is {0}.").format(run.state))
    if run.state == "Posting":
        return _reconciliation_result(
            run, profile, session, retry_token,
            "A previous posting attempt has an uncertain outcome.",
        )

    try:
        existing_target = _linked_target(run)
    except Exception as exc:
        return _failure_result(
            run, profile, session, retry_token, exc,
            previous_state=request_state,
        )
    if run.target_name and not existing_target:
        return _reconciliation_result(
            run, profile, session, retry_token,
            "The target document linked to this Action Run no longer exists.",
        )
    terminal_result = _existing_terminal_result(
        run, existing_target, None, profile, session, retry_token
    )
    if terminal_result:
        return (_release_gate_or_reconcile(run, profile, session, retry_token)
                or terminal_result)

    try:
        snapshot = assert_pinned_snapshot_compatible(run)
    except Exception as exc:
        return _reconciliation_result(
            run, profile, session, retry_token,
            "Pinned Action configuration is no longer compatible: {0}".format(
                sanitize_error(exc)
            ),
        )
    configuration = snapshot["configuration"]
    try:
        terminal_result = _existing_terminal_result(
            run, existing_target, configuration, profile, session, retry_token
        )
        if terminal_result:
            return (_release_gate_or_reconcile(run, profile, session, retry_token)
                    or terminal_result)

        parent_input = _object(operator_values, "Parent operator values")
        child_input = _object(child_rows, "Child-table rows")
        payload, should_post = _build_payload(
            run, task, profile, configuration, parent_input, child_input,
            trigger_condition=configuration.get("trigger_condition"),
        )
        _persist_payload(run, payload, profile.employee)

        if not should_post:
            if run.target_name:
                return _reconciliation_result(
                    run, profile, session, retry_token,
                    "The trigger condition changed after a target document was linked.",
                )
            run, _changed = transition_run(
                run.name, "Skipped by Condition", profile, session,
                _phase_token(retry_token, "skipped"), attempt_type="State Transition",
            )
            attempt, _created = record_run_attempt(
                run, "Post", "Succeeded", profile, session, retry_token,
                previous_state=request_state, result_state=run.state,
            )
            gate_error = _release_gate_or_reconcile(
                run, profile, session, retry_token
            )
            if gate_error:
                return gate_error
            result = public_run(run, attempt=attempt.name)
            result.update({"ok": True, "skipped": True,
                           "message": _("Action condition was not met; no target was created.")})
            return result

        target = existing_target
        if target:
            if run.state not in {"Draft Created", "Failed"}:
                return _reconciliation_result(
                    run, profile, session, retry_token,
                    "A linked draft exists in an incompatible Action Run state.",
                )
            if run.state == "Failed":
                run = _advance_to_posting(run, profile, session, retry_token)
            target = _update_existing_draft(target, payload, configuration)
            _link_target(run, target)
            if run.state == "Posting":
                run, _changed = transition_run(
                    run.name, "Draft Created", profile, session,
                    _phase_token(retry_token, "draft-restored"),
                    values={"target_docstatus": cint(target.docstatus)},
                )
        else:
            _assert_create_permission(run.target_doctype)
            run = _advance_to_posting(run, profile, session, retry_token)
            target = _new_target(run.target_doctype, payload, configuration)
            target.insert()
            _link_target(run, target)
            run, _changed = transition_run(
                run.name, "Draft Created", profile, session,
                _phase_token(retry_token, "draft-created"),
                values={"target_docstatus": cint(target.docstatus)},
            )

        if configuration.get("posting_policy") == "Submit When Authorized":
            if cint(target.docstatus) != 0:
                frappe.throw(_("Only a draft target can be submitted by this Action Run."))
            target.check_permission("submit")
            target.submit()
            _link_target(run, target)
            run, _changed = transition_run(
                run.name, "Submitted", profile, session,
                _phase_token(retry_token, "submitted"),
                values={"target_docstatus": cint(target.docstatus),
                        "posted_at": now_datetime()},
            )

        attempt, _created = record_run_attempt(
            run, "Post", "Succeeded", profile, session, retry_token,
            previous_state=request_state, result_state=run.state,
        )
        gate_error = _release_gate_or_reconcile(run, profile, session, retry_token)
        if gate_error:
            return gate_error
        result = public_run(run, attempt=attempt.name)
        result.update({
            "ok": True,
            "skipped": False,
            "message": (_("Target document submitted") if run.state == "Submitted"
                        else _("Target document saved as Draft")),
            "target_link": _target_link(run),
        })
        return result
    except Exception as exc:
        return _failure_result(
            run, profile, session, retry_token, exc,
            previous_state=request_state,
        )


def _build_payload(run, task, profile, configuration, operator_values, child_rows,
                   trigger_condition=None):
    meta = frappe.get_meta(run.target_doctype)
    parent_mappings = configuration.get("parent") or []
    allowed_parent = {
        row["fieldname"] for row in parent_mappings
        if row.get("source_type") == "Operator Input"
        and cint(row.get("show_to_operator", 1))
        and not cint(row.get("read_only"))
    }
    _reject_extra_keys(operator_values, allowed_parent, "parent field")

    context = _condition_context(task, profile, operator_values)
    raw_parent = {}
    for mapping in parent_mappings:
        field = meta.get_field(mapping["fieldname"])
        raw_parent[mapping["fieldname"]] = _resolve_and_convert(
            mapping, field, task, profile, operator_values
        )
    condition_values = dict(context)
    condition_values.update(raw_parent)
    should_post = _condition_matches(trigger_condition, condition_values)
    parent = {}
    for mapping in parent_mappings:
        field = meta.get_field(mapping["fieldname"])
        if not _condition_matches(mapping.get("visible_condition"), condition_values):
            continue
        value = raw_parent.get(mapping["fieldname"])
        if should_post:
            _assert_required(mapping, field, value)
        if value not in (None, ""):
            parent[mapping["fieldname"]] = value

    table_configs = {
        row["table_fieldname"]: row for row in configuration.get("tables") or []
    }
    _reject_extra_keys(child_rows, set(table_configs), "child table")
    if not should_post:
        return _json_safe({"parent": parent, "children": {}}), False
    columns_by_table = _columns_by_table(configuration)
    children = {}
    total_rows = 0
    for table_name, table in table_configs.items():
        rows = child_rows.get(table_name) or []
        if not isinstance(rows, list):
            frappe.throw(_("Child table {0} must contain a list of rows.").format(table_name))
        minimum, maximum = cint(table.get("min_rows")), cint(table.get("max_rows"))
        if len(rows) < minimum or len(rows) > maximum:
            frappe.throw(_("Child table {0} requires between {1} and {2} rows.").format(
                table_name, minimum, maximum
            ))
        total_rows += len(rows)
        if total_rows > cint(configuration.get("max_child_rows")):
            frappe.throw(_("The Action Profile child-row safety limit was exceeded."))
        table_field = meta.get_field(table_name)
        child_meta = frappe.get_meta(table_field.options)
        mappings = columns_by_table.get(table_name, [])
        allowed_columns = {
            mapping["fieldname"] for mapping in mappings
            if mapping.get("source_type") == "Operator Input"
            and cint(mapping.get("show_to_operator", 1))
            and not cint(mapping.get("read_only"))
        }
        output_rows = []
        for index, supplied_row in enumerate(rows, start=1):
            supplied_row = _object(supplied_row, f"{table_name} row {index}")
            _reject_extra_keys(supplied_row, allowed_columns,
                               f"{table_name} row {index} field")
            row_context = dict(condition_values)
            row_context.update(supplied_row)
            raw_row = {}
            for mapping in mappings:
                field = child_meta.get_field(mapping["fieldname"])
                raw_row[mapping["fieldname"]] = _resolve_and_convert(
                    mapping, field, task, profile, supplied_row
                )
            row_context.update(raw_row)
            output = {}
            for mapping in mappings:
                field = child_meta.get_field(mapping["fieldname"])
                if not _condition_matches(mapping.get("visible_condition"), row_context):
                    continue
                value = raw_row.get(mapping["fieldname"])
                _assert_required(mapping, field, value)
                if value not in (None, ""):
                    output[mapping["fieldname"]] = value
            if not output:
                frappe.throw(_("Child table {0} row {1} is empty.").format(
                    table_name, index
                ))
            output_rows.append(output)
        children[table_name] = output_rows
    return _json_safe({"parent": parent, "children": children}), True


def _resolve_and_convert(mapping, field, task, profile, operator_values):
    if not field:
        frappe.throw(_("Mapped target field {0} no longer exists.").format(
            mapping.get("fieldname")
        ))
    value = _resolve_mapping_value(mapping, task, profile, operator_values)
    return _convert_value(field, value, mapping.get("source_type") == "Operator Input")


def _resolve_mapping_value(mapping, task, profile, operator_values):
    source_type = mapping.get("source_type")
    if source_type == "Operator Input":
        if mapping.get("fieldname") in operator_values:
            return operator_values[mapping["fieldname"]]
        return mapping.get("default_value")
    if source_type == "Fixed Value":
        return mapping.get("fixed_value")
    if source_type == "Server Context":
        return _server_context(task, profile).get(mapping.get("source_key"))
    if source_type == "Service Task Field":
        task_values = _task_values(task)
        source_key = mapping.get("source_key")
        if source_key not in task_values:
            frappe.throw(_(
                "Mapped Service Task field {0} is not available on this task occurrence."
            ).format(source_key))
        return task_values.get(source_key)
    frappe.throw(_("Unsupported mapping source for {0}.").format(mapping.get("fieldname")))


def _convert_value(field, value, operator_supplied):
    if value in (None, ""):
        return None
    try:
        if field.fieldtype == "Int":
            converted = int(str(value))
        elif field.fieldtype in {"Float", "Currency"}:
            precision = cint(field.get("precision")) if field.get("precision") else None
            converted = flt(value, precision)
        elif field.fieldtype == "Check":
            converted = _check_value(value)
        elif field.fieldtype == "Date":
            converted = str(getdate(value))
        elif field.fieldtype == "Datetime":
            converted = str(get_datetime(value))
        else:
            converted = str(value)
    except (TypeError, ValueError):
        frappe.throw(_("{0} is not a valid {1} value.").format(
            field.label or field.fieldname, field.fieldtype
        ))

    if field.fieldtype == "Select" and field.options:
        if converted not in str(field.options).splitlines():
            frappe.throw(_("{0} is not an allowed value for {1}.").format(
                converted, field.label or field.fieldname
            ))
    if field.fieldtype == "Link":
        if not frappe.db.exists(field.options, converted):
            frappe.throw(_("{0} does not exist in {1}.").format(converted, field.options))
        if operator_supplied and not frappe.has_permission(
            field.options, ptype="read", doc=converted, user=frappe.session.user
        ):
            frappe.throw(_("You are not permitted to select {0} {1}.").format(
                field.options, converted
            ), frappe.PermissionError)
    if field.fieldtype == "Data":
        maximum = cint(field.get("length")) or 140
        if len(converted) > maximum:
            frappe.throw(_("{0} exceeds the maximum length of {1}.").format(
                field.label or field.fieldname, maximum
            ))
    if field.fieldtype in {"Small Text", "Text", "Long Text"}:
        if len(converted) > MAX_TEXT_LENGTH:
            frappe.throw(_("{0} exceeds the Action Engine text limit.").format(
                field.label or field.fieldname
            ))
    return converted


def _new_target(target_doctype, payload, configuration):
    target = frappe.get_doc({"doctype": target_doctype})
    _apply_payload(target, payload, configuration)
    return target


def _update_existing_draft(target, payload, configuration):
    if cint(target.docstatus) != 0:
        return target
    target.check_permission("write")
    _apply_payload(target, payload, configuration)
    target.save()
    return target


def _apply_payload(target, payload, configuration):
    # Clear every pinned mapped field/table first so a condition that becomes false
    # cannot leave stale values on a retry of the same draft.
    for mapping in configuration.get("parent") or []:
        target.set(mapping["fieldname"], None)
    for table in configuration.get("tables") or []:
        target.set(table["table_fieldname"], [])
    for fieldname, value in (payload.get("parent") or {}).items():
        target.set(fieldname, value)
    for table_name, rows in (payload.get("children") or {}).items():
        for row in rows:
            target.append(table_name, row)


def _advance_to_posting(run, profile, session, retry_token):
    if run.state in {"Form In Progress", "Failed"}:
        recovery_values = (
            {"last_error_code": None, "last_error": None}
            if run.state == "Failed" else None
        )
        run, _changed = transition_run(
            run.name, "Ready to Post", profile, session,
            _phase_token(retry_token, "ready"),
            values=recovery_values,
        )
    if run.state == "Ready to Post":
        run, _changed = transition_run(
            run.name, "Posting", profile, session,
            _phase_token(retry_token, "posting"),
        )
    return run


def _linked_target(run):
    if not run.target_name:
        return None
    if not frappe.db.exists(run.target_doctype, run.target_name):
        return None
    target = frappe.get_doc(run.target_doctype, run.target_name)
    target.check_permission("read")
    return target


def _existing_terminal_result(run, target, configuration, profile, session, retry_token):
    if run.state == "Submitted":
        if not target or cint(target.docstatus) != 1:
            return _reconciliation_result(
                run, profile, session, retry_token,
                "Action Run says Submitted but the target document does not.",
            )
        attempt, _created = record_run_attempt(
            run, "Post", "Succeeded", profile, session, retry_token,
            previous_state=run.state, result_state=run.state,
        )
        result = public_run(run, deduplicated=True, attempt=attempt.name)
        result.update({"ok": True, "target_link": _target_link(run),
                       "message": _("Target document was already submitted.")})
        return result
    if target and cint(target.docstatus) == 2:
        return _reconciliation_result(
            run, profile, session, retry_token,
            "The linked target document is cancelled.",
        )
    if target and cint(target.docstatus) == 1:
        return _reconciliation_result(
            run, profile, session, retry_token,
            "The linked target was submitted outside this Action Run.",
        )
    if (configuration and target and run.state == "Draft Created"
            and configuration.get("posting_policy") == "Save Draft"):
        attempt, _created = record_run_attempt(
            run, "Post", "Succeeded", profile, session, retry_token,
            previous_state=run.state, result_state=run.state,
        )
        result = public_run(run, deduplicated=True, attempt=attempt.name)
        result.update({"ok": True, "target_link": _target_link(run),
                       "message": _("Target document was already saved as Draft.")})
        return result
    return None


def _failure_result(run, profile, session, retry_token, exc, previous_state=None):
    message = sanitize_error(exc)
    code = exc.__class__.__name__
    try:
        current = get_locked_run(run.name)
        if current.state not in {"Cancelled", "Skipped by Condition", "Needs Reconciliation",
                                 "Submitted"}:
            current, _changed = transition_run(
                current.name, "Failed", profile, session,
                _phase_token(retry_token, "failed"), attempt_type="State Transition",
                error_code=code, error_message=message,
            )
        attempt, _created = record_run_attempt(
            current, "Post", "Failed", profile, session, retry_token,
            previous_state=previous_state or run.state, result_state=current.state,
            error_code=code, error_message=message,
        )
        result = public_run(current, attempt=attempt.name)
    except Exception:
        # Do not hide the original controlled error with a secondary audit failure.
        result = public_run(run)
    result.update({"ok": False, "error_code": code, "message": message})
    return result


def _release_gate_or_reconcile(run, profile, session, retry_token):
    savepoint = "cfg_action_gate_" + canonical_key(
        run.name, retry_token
    )[:16]
    frappe.db.savepoint(savepoint)
    try:
        release_task_gate(run, profile, session)
        return None
    except Exception as exc:
        frappe.db.rollback(save_point=savepoint)
        return _reconciliation_result(
            run,
            profile,
            session,
            _phase_token(retry_token, "task-gate-release"),
            "The target was written but its Service Task document gate could not be released: "
            + sanitize_error(exc),
        )


def _reconciliation_result(run, profile, session, retry_token, reason):
    previous = run.state
    if run.state != "Needs Reconciliation":
        run, _changed = transition_run(
            run.name, "Needs Reconciliation", profile, session,
            _phase_token(retry_token, "reconciliation"),
            error_code="ReconciliationRequired", error_message=reason,
        )
    attempt, _created = record_run_attempt(
        run, "Post", "Failed", profile, session, retry_token,
        previous_state=previous, result_state=run.state,
        error_code="ReconciliationRequired", error_message=reason,
    )
    result = public_run(run, attempt=attempt.name)
    result.update({"ok": False, "error_code": "ReconciliationRequired",
                   "message": reason})
    return result


def _attempt_result(run, attempt, deduplicated):
    result = public_run(run, deduplicated=deduplicated, attempt=attempt.name)
    result.update({
        "ok": attempt.outcome == "Succeeded",
        "message": attempt.error_message or _("This posting request was already processed."),
        "error_code": attempt.error_code,
        "target_link": _target_link(run),
    })
    return result


def _link_target(run, target):
    if run.target_name and run.target_name != target.name:
        frappe.throw(_("Action Run is already linked to a different target document."))
    values = {"target_name": target.name, "target_docstatus": cint(target.docstatus)}
    frappe.db.set_value(run.doctype, run.name, values, update_modified=False)
    run.update(values)


def _persist_payload(run, payload, employee):
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    values = {
        "form_payload": serialized,
        "form_payload_hash": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "last_input_by": employee,
        "last_input_on": now_datetime(),
    }
    frappe.db.set_value(run.doctype, run.name, values, update_modified=False)
    run.update(values)


def _stored_payload(run):
    if not run.form_payload:
        return {"parent": {}, "children": {}}
    try:
        payload = json.loads(run.form_payload)
    except (TypeError, ValueError):
        frappe.throw(_("Stored Action Run form data is unreadable; reconciliation is required."))
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    if hashlib.sha256(serialized.encode("utf-8")).hexdigest() != run.form_payload_hash:
        frappe.throw(_("Stored Action Run form data failed its integrity check."))
    return payload


def _task_values(task):
    values = {fieldname: task.get(fieldname) for fieldname in SAFE_TASK_FIELDS}
    if task.get("task_schedule"):
        schedule = frappe.get_doc("CFG Kanban Task Schedule", task.task_schedule)
        for definition in schedule.get("task_field_definitions") or []:
            if definition.definition_scope == "Standalone Task":
                values.setdefault(definition.field_key, definition.default_value)
    for row in task.get("execution_values") or []:
        values[row.field_key] = row.value
    return values


def _server_context(task, profile):
    return {
        "employee": profile.employee,
        "task_name": task.name,
        "company": task.company,
        "location": task.location,
        "asset": task.asset,
        "workstation": task.workstation,
        "server_timestamp": now_datetime(),
    }


def _condition_context(task, profile, supplied):
    values = _task_values(task)
    values.update(_server_context(task, profile))
    values.update(supplied or {})
    return values


def _condition_matches(condition, values):
    if not condition:
        return True
    if isinstance(condition, str):
        try:
            condition = json.loads(condition)
        except (TypeError, ValueError):
            frappe.throw(_("Pinned Action condition is not valid JSON."))
    if "all" in condition:
        return all(_condition_matches(row, values) for row in condition["all"])
    if "any" in condition:
        return any(_condition_matches(row, values) for row in condition["any"])
    actual = values.get(condition.get("field"))
    expected = condition.get("value")
    operator = condition.get("operator")
    if operator == "equals":
        return _equal(actual, expected)
    if operator == "not_equals":
        return not _equal(actual, expected)
    if operator in {"in", "not_in"}:
        candidates = expected if isinstance(expected, list) else [expected]
        matched = any(_equal(actual, candidate) for candidate in candidates)
        return matched if operator == "in" else not matched
    if operator in {"greater_than", "less_than"}:
        try:
            left, right = float(actual), float(expected)
        except (TypeError, ValueError):
            return False
        return left > right if operator == "greater_than" else left < right
    frappe.throw(_("Pinned Action condition contains an unsupported comparison."))


def _equal(actual, expected):
    if isinstance(expected, bool):
        try:
            return bool(_check_value(actual)) == expected
        except ValueError:
            return False
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return float(actual) == float(expected)
        except (TypeError, ValueError):
            return False
    if expected is None:
        return actual in (None, "")
    return str(actual if actual is not None else "") == str(expected)


def _check_value(value):
    if isinstance(value, bool):
        return 1 if value else 0
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return 1
    if lowered in {"0", "false", "no", "off"}:
        return 0
    raise ValueError("invalid check value")


def _assert_required(mapping, field, value):
    target_requires = cint(field.reqd) and not field.default and not field.fetch_from
    if (cint(mapping.get("required_in_kanban")) or target_requires) and value in (None, ""):
        frappe.throw(_("{0} is required.").format(
            mapping.get("operator_label") or field.label or field.fieldname
        ))


def _assert_create_permission(target_doctype):
    if not frappe.has_permission(
        target_doctype, ptype="create", user=frappe.session.user
    ):
        frappe.throw(_(
            "Terminal User {0} is not permitted to create {1}. Grant only the reviewed target "
            "permission; the Action Engine will not bypass it."
        ).format(frappe.session.user, target_doctype), frappe.PermissionError)


def _form_field(field, mapping, current, visible=True):
    return {
        "fieldname": field.fieldname,
        "label": mapping.get("operator_label") or field.label or field.fieldname,
        "fieldtype": field.fieldtype,
        "options": field.options,
        "source_type": mapping.get("source_type"),
        "required": bool(cint(mapping.get("required_in_kanban")) or cint(field.reqd)),
        "read_only": bool(cint(mapping.get("read_only"))
                          or mapping.get("source_type") != "Operator Input"),
        "visible_condition": mapping.get("visible_condition"),
        "visible": bool(visible),
        "default": current if current is not None else mapping.get("default_value"),
    }


def _condition_context_for_form(configuration, values):
    referenced = set()
    for mapping in (configuration.get("parent") or []):
        referenced.update(_condition_fieldnames(mapping.get("visible_condition")))
    for mapping in (configuration.get("columns") or []):
        referenced.update(_condition_fieldnames(mapping.get("visible_condition")))
    referenced.update(_condition_fieldnames(configuration.get("trigger_condition")))
    return _json_safe({key: values.get(key) for key in referenced if key in values})


def _condition_fieldnames(condition):
    if not condition:
        return set()
    if isinstance(condition, str):
        try:
            condition = json.loads(condition)
        except (TypeError, ValueError):
            return set()
    if not isinstance(condition, dict):
        return set()
    for group in ("all", "any"):
        if group in condition:
            fields = set()
            for child in condition.get(group) or []:
                fields.update(_condition_fieldnames(child))
            return fields
    return {condition.get("field")} if condition.get("field") else set()


def _columns_by_table(configuration):
    grouped = {}
    for mapping in sorted(configuration.get("columns") or [], key=_display_order):
        grouped.setdefault(mapping.get("table_fieldname"), []).append(mapping)
    return grouped


def _display_order(row):
    return (cint(row.get("display_order")), row.get("fieldname") or row.get("table_fieldname"))


def _reject_extra_keys(values, allowed, label):
    extra = set(values) - set(allowed)
    if extra:
        frappe.throw(_("Unmapped or protected {0}: {1}").format(
            label, ", ".join(sorted(extra))
        ), frappe.PermissionError)


def _object(value, label):
    if isinstance(value, str):
        value = frappe.parse_json(value)
    value = value or {}
    if not isinstance(value, dict):
        frappe.throw(_("{0} must be a JSON object.").format(label))
    return value


def _json_safe(value):
    return json.loads(json.dumps(value, default=str))


def _phase_token(retry_token, phase):
    return canonical_key("doctype-action-writer-v1", retry_token, phase)


def _target_link(run):
    if not run.target_name:
        return None
    return {"doctype": run.target_doctype, "name": run.target_name,
            "docstatus": cint(run.target_docstatus)}
