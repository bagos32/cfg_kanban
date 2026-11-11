"""Runtime Process Certificate controls for ERPNext Work Order production.

The Work Order, Job Cards, Stock Entry, Batch, and stock ledger remain authoritative in
ERPNext.  This module gates Kanban operation execution from scanned Handling Units, carries
the approved certificate-state snapshot across digital operation handoffs, and binds the
final state to the exact tagged Manufacture output after ERPNext submission.
"""

import hashlib
import json

import frappe
from frappe.utils import add_days, cint, flt, now_datetime

from cfg_kanban.services.idempotency import canonical_key


TOLERANCE = 0.000001


def certificate_context(execution):
    execution = _execution(execution)
    master = frappe.get_doc("CFG Kanban Master", execution.kanban_master)
    requirements = [
        row.as_dict() for row in master.certificate_requirements
        if row.operation == execution.operation
    ]
    outputs = [
        row.as_dict() for row in master.certificate_output_rules
        if row.operation == execution.operation
    ]
    enabled = bool(requirements or outputs)
    gate_status = execution.certificate_gate_status or "Not Required"
    if enabled and gate_status == "Not Required":
        gate_status = "Pending"
    return {
        "enabled": enabled,
        "gate_status": gate_status,
        "input_certificate_sets": frappe.parse_json(
            execution.input_certificate_sets_json or "[]"
        ) or [],
        "result_certificate_set": execution.result_certificate_set,
        "requirements": requirements,
        "output_rules": outputs,
    }


def assert_execution_certificate_gate(execution, stage, stock_entry=None):
    """Enforce one configured operation gate from immutable scanned/source evidence."""
    execution = _execution(execution)
    master = frappe.get_doc("CFG Kanban Master", execution.kanban_master)
    rows = [
        row for row in master.certificate_requirements
        if row.operation == execution.operation and row.gate_stage == stage
    ]
    if not rows:
        return {"required": False, "passed": True, "sets": []}

    evidence = _certificate_evidence(execution, stock_entry=stock_entry)
    groups = {}
    for row in rows:
        passed = _requirement_passes(evidence, row)
        key = (row.requirement_group or "DEFAULT").strip().upper()
        groups.setdefault(key, {"logic": row.group_logic, "checks": []})[
            "checks"
        ].append((row.certificate_type, passed))

    failed = []
    for group, values in groups.items():
        checks = values["checks"]
        passed = (
            all(value for _certificate, value in checks)
            if values["logic"] == "All Required"
            else any(value for _certificate, value in checks)
        )
        if not passed:
            failed.append(
                f"{group}: " + ", ".join(
                    certificate for certificate, value in checks if not value
                )
            )
    if failed:
        execution.db_set({
            "certificate_gate_status": "Failed",
            "certificate_checked_on": now_datetime(),
            "input_certificate_sets_json": frappe.as_json(evidence["set_names"]),
        }, update_modified=True)
        frappe.throw(
            f"{execution.operation} cannot pass the {stage} Certificate gate. "
            + "; ".join(failed)
            + ". Scan the certified source tag in the operation Material Run, or complete "
              "the prerequisite operation that produces the required certificate."
        )

    execution.db_set({
        "certificate_gate_status": "Passed",
        "certificate_checked_on": now_datetime(),
        "input_certificate_sets_json": frappe.as_json(evidence["set_names"]),
    }, update_modified=True)
    return {"required": True, "passed": True, "sets": evidence["set_names"]}


def finalize_execution_certificate_result(execution):
    """Freeze the operation's resulting certificate state for downstream handoff."""
    execution = _execution(execution)
    master = frappe.get_doc("CFG Kanban Master", execution.kanban_master)
    rules = [
        row for row in master.certificate_output_rules
        if row.operation == execution.operation
    ]
    evidence = _certificate_evidence(execution)
    if not rules:
        result = _latest_internal_set(execution) or (
            evidence["set_names"][0] if len(evidence["set_names"]) == 1 else None
        )
        if result:
            execution.db_set({
                "result_certificate_set": result,
                "input_certificate_sets_json": frappe.as_json(evidence["set_names"]),
                "certificate_gate_status": "Passed",
                "certificate_checked_on": now_datetime(),
            }, update_modified=True)
        return result

    source_members = _member_union(evidence["set_names"])
    members = {}
    for rule in rules:
        if rule.action == "Revoke":
            members.pop(rule.certificate_type, None)
        elif rule.action == "Issue":
            members[rule.certificate_type] = cint(frappe.db.get_value(
                "CFG Process Certificate Type", rule.certificate_type, "revision"
            ))
        elif rule.action == "Retain":
            if rule.certificate_type not in source_members:
                frappe.throw(
                    f"{execution.operation} cannot retain {rule.certificate_type}; the "
                    "certificate is absent from its certified input or prior operation handoff"
                )
            if (not _prior_issue_rule(master, execution, rule.certificate_type)
                    and not _active_input_certificate(
                        evidence["unit_names"], rule.certificate_type
                    )):
                frappe.throw(
                    f"{execution.operation} cannot retain {rule.certificate_type}; no "
                    "active, unexpired issued certificate proves its input lineage"
                )
            members[rule.certificate_type] = source_members[rule.certificate_type]
    if not members:
        frappe.throw(
            f"Certificate Output Rules for {execution.operation} produce an empty state"
        )
    result = _certificate_set(members, master.name, execution.operation)
    execution.db_set({
        "result_certificate_set": result.name,
        "input_certificate_sets_json": frappe.as_json(evidence["set_names"]),
        "certificate_gate_status": "Passed",
        "certificate_checked_on": now_datetime(),
    }, update_modified=True)
    return result.name


def validate_production_certificate_stock_entry(doc):
    """Apply native Inventory Dimension state before a controlled Stock Entry submits."""
    cycle_name = doc.get("cfg_kanban_cycle")
    if not cycle_name:
        return
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    if master.control_type != "Production" or not (
        master.certificate_requirements or master.certificate_output_rules
    ):
        return
    _apply_input_certificate_dimensions(doc)

    purpose = doc.get("purpose") or doc.get("stock_entry_type")
    if purpose in ("Material Consumption for Manufacture", "Manufacture"):
        _assert_stock_entry_gates(cycle, master, doc, "Before Material Consumption")
    if purpose != "Manufacture":
        return
    _assert_stock_entry_gates(cycle, master, doc, "Before Output Release")
    result_set = _final_production_result_set(cycle, master)
    if not result_set:
        return
    detail_meta = frappe.get_meta("Stock Entry Detail")
    if not detail_meta.has_field("to_process_certificate_set"):
        frappe.throw(
            "Target Process Certificate Set Inventory Dimension is missing. Run the CFG "
            "Kanban migration before submitting certified production output."
        )
    output_rows = [
        row for row in doc.items
        if row.t_warehouse and not row.s_warehouse and row.item_code == cycle.item_code
    ]
    if not output_rows:
        frappe.throw("Certified Manufacture has no finished-output row")
    trace = frappe.db.get_value(
        "CFG Kanban Material Trace", {"stock_entry": doc.name}, "name"
    )
    for row in output_rows:
        staged = flt(frappe.db.get_value(
            "CFG Kanban Material Trace Line",
            {
                "parent": trace or "__missing__",
                "stock_entry_detail": row.name,
                "direction": "Output",
                "status": ["in", ["Pending", "Confirmed"]],
            },
            "sum(qty)",
        ) or 0)
        output_qty = _stock_qty(row)
        if staged + TOLERANCE < output_qty:
            frappe.throw(
                f"Certified output Item {row.item_code} requires physical output tags for "
                f"the complete quantity. Staged {staged} of {output_qty}."
            )
        row.to_process_certificate_set = result_set


def reconcile_production_output_certificates(doc):
    """Bind submitted Manufacture certificate state to each confirmed output identity."""
    cycle_name = doc.get("cfg_kanban_cycle")
    if not cycle_name or doc.docstatus != 1 or (
        doc.get("purpose") or doc.get("stock_entry_type")
    ) != "Manufacture":
        return
    cycle = frappe.get_doc("CFG Kanban Cycle", cycle_name)
    master = frappe.get_doc("CFG Kanban Master", cycle.kanban_master)
    if master.control_type != "Production" or not master.certificate_output_rules:
        return
    trace = frappe.db.get_value(
        "CFG Kanban Material Trace", {"stock_entry": doc.name}, "name"
    )
    if not trace:
        return
    output_rows = {row.name: row for row in doc.items if row.t_warehouse and not row.s_warehouse}
    lines = frappe.get_all(
        "CFG Kanban Material Trace Line",
        filters={"parent": trace, "direction": "Output", "status": "Confirmed"},
        fields=["name", "stock_entry_detail", "handling_unit", "qty", "batch_no"],
        order_by="idx asc", limit_page_length=0,
    )
    for line in lines:
        row = output_rows.get(line.stock_entry_detail)
        if not row or row.item_code != cycle.item_code or not line.handling_unit:
            continue
        result_set = row.get("to_process_certificate_set")
        if not result_set:
            continue
        frappe.db.set_value(
            "CFG Kanban Handling Unit", line.handling_unit,
            "process_certificate_set", result_set, update_modified=True,
        )
        _issue_finished_output_certificates(
            master, cycle, doc, row, line, result_set
        )


def revoke_cancelled_stock_entry_certificates(doc):
    """Revoke output certificates when their authoritative ERP stock movement is cancelled."""
    cycle_name = doc.get("cfg_kanban_cycle")
    if not cycle_name:
        return
    trace = frappe.db.get_value(
        "CFG Kanban Material Trace", {"stock_entry": doc.name}, "name"
    )
    output_units = []
    if trace:
        output_units = frappe.get_all(
            "CFG Kanban Material Trace Line",
            filters={
                "parent": trace,
                "direction": "Output",
                "handling_unit": ["is", "set"],
            },
            pluck="handling_unit",
            limit_page_length=0,
        )
    run_unit = frappe.db.get_value(
        "CFG Process Certificate Run",
        {"kanban_cycle": cycle_name, "repack_stock_entry": doc.name},
        "output_handling_unit",
    )
    if run_unit:
        output_units.append(run_unit)
    output_units = list(dict.fromkeys(unit for unit in output_units if unit))
    names = []
    if output_units:
        names.extend(frappe.get_all(
            "CFG Process Certificate",
            filters={
                "kanban_cycle": cycle_name,
                "handling_unit": ["in", output_units],
                "status": "Active",
            },
            pluck="name",
            limit_page_length=0,
        ))
    names.extend(frappe.get_all(
        "CFG Process Certificate",
        filters={
            "source_reference_doctype": "Stock Entry",
            "source_reference_name": doc.name,
            "status": "Active",
        },
        pluck="name",
        limit_page_length=0,
    ))
    values = {
        "status": "Revoked",
        "revoked_on": now_datetime(),
        "revoked_by": frappe.session.user,
        "revocation_reason": f"Authoritative Stock Entry {doc.name} was cancelled",
    }
    for name in dict.fromkeys(names):
        frappe.db.set_value(
            "CFG Process Certificate", name, values, update_modified=True
        )


def validate_job_card_certificate_submission(doc):
    """Prevent native/direct Job Card submission from bypassing Kanban certificate gates."""
    cycle_name = doc.get("cfg_kanban_cycle")
    if not cycle_name:
        return
    execution_name = frappe.db.get_value(
        "CFG Kanban Process Execution",
        {"kanban_cycle": cycle_name, "job_card": doc.name},
        "name",
    )
    if not execution_name:
        return
    execution = frappe.get_doc("CFG Kanban Process Execution", execution_name)
    master = frappe.get_doc("CFG Kanban Master", execution.kanban_master)
    if master.control_type != "Production":
        return
    assert_execution_certificate_gate(execution, "Before Operation Start")
    assert_execution_certificate_gate(execution, "Before Progress")
    finalize_execution_certificate_result(execution)


def _assert_stock_entry_gates(cycle, master, doc, stage):
    operations = {
        row.operation for row in master.certificate_requirements
        if row.gate_stage == stage
    }
    for operation in operations:
        executions = frappe.get_all(
            "CFG Kanban Process Execution",
            filters={
                "kanban_cycle": cycle.name,
                "operation": operation,
                "status": ["!=", "Cancelled"],
            },
            fields=["name", "runtime_allocation"], order_by="sequence asc, creation asc",
            limit_page_length=0,
        )
        candidates = [row for row in executions if not row.runtime_allocation] or executions
        if not candidates:
            frappe.throw(f"No Process Execution exists for Certificate-controlled {operation}")
        for row in candidates:
            assert_execution_certificate_gate(row.name, stage, stock_entry=doc)


def _final_production_result_set(cycle, master):
    executions = frappe.get_all(
        "CFG Kanban Process Execution",
        filters={"kanban_cycle": cycle.name, "status": ["!=", "Cancelled"]},
        fields=[
            "name", "operation", "sequence", "status", "runtime_allocation",
            "result_certificate_set",
        ],
        order_by="sequence asc, creation asc", limit_page_length=0,
    )
    main = [row for row in executions if not row.runtime_allocation] or executions
    controlled_operations = {
        row.operation for row in master.certificate_output_rules
    }
    incomplete = [
        row.operation for row in main
        if row.operation in controlled_operations and row.status != "Completed"
    ]
    if incomplete:
        frappe.throw(
            "Complete the certificate-controlled Job Card operation(s) before preparing "
            "the Manufacture output: " + ", ".join(dict.fromkeys(incomplete))
        )
    for row in main:
        if not row.result_certificate_set:
            row.result_certificate_set = finalize_execution_certificate_result(row.name)
    available = [row for row in main if row.result_certificate_set]
    if not available:
        if master.certificate_output_rules:
            frappe.throw(
                "Complete the certificate-controlled Job Card operation(s) before preparing "
                "the Manufacture output."
            )
        return None
    max_sequence = max(cint(row.sequence) for row in available)
    sets = list(dict.fromkeys(
        row.result_certificate_set for row in available
        if cint(row.sequence) == max_sequence and row.result_certificate_set
    ))
    if len(sets) == 1:
        return sets[0]
    frappe.throw(
        "Parallel final Job Card lanes produced different Process Certificate Sets. "
        "Do not merge them into one Manufacture output row; reconcile the lane results "
        "or stage them as separate certified outputs."
    )


def _apply_input_certificate_dimensions(doc):
    if not frappe.get_meta("Stock Entry Detail").has_field("process_certificate_set"):
        return
    trace = frappe.db.get_value(
        "CFG Kanban Material Trace", {"stock_entry": doc.name}, "name"
    )
    if not trace:
        return
    for row in doc.items:
        if not row.s_warehouse:
            continue
        lines = frappe.get_all(
            "CFG Kanban Material Trace Line",
            filters={
                "parent": trace,
                "stock_entry_detail": row.name,
                "direction": "Input",
                "status": ["in", ["Reserved", "Confirmed"]],
            },
            fields=["handling_unit", "qty"], limit_page_length=0,
        )
        units = list(dict.fromkeys(
            line.handling_unit for line in lines if line.handling_unit
        ))
        if not units:
            continue
        unit_sets = frappe.get_all(
            "CFG Kanban Handling Unit",
            filters={"name": ["in", units]},
            fields=["name", "process_certificate_set"], limit_page_length=0,
        )
        sets = list(dict.fromkeys(
            unit.process_certificate_set for unit in unit_sets
            if unit.process_certificate_set
        ))
        if not sets:
            continue
        if len(sets) != 1 or any(not unit.process_certificate_set for unit in unit_sets):
            frappe.throw(
                f"Stock Entry input row {row.idx} mixes different certified/uncertified "
                "physical quantities. Split the row by Process Certificate Set."
            )
        traced_qty = sum(flt(line.qty) for line in lines)
        row_qty = _stock_qty(row)
        if abs(traced_qty - row_qty) > TOLERANCE:
            frappe.throw(
                f"Certified input row {row.idx} has {traced_qty} physically traced but "
                f"{row_qty} in ERPNext. Split or scan the complete row before submission."
            )
        if row.get("process_certificate_set") and row.process_certificate_set != sets[0]:
            frappe.throw(
                f"Stock Entry input row {row.idx} Process Certificate Set does not match "
                "its scanned source tag."
            )
        row.process_certificate_set = sets[0]


def _certificate_evidence(execution, stock_entry=None):
    unit_names = []
    set_names = []
    internal_sets = []
    prior = _prior_execution_sets(execution)
    set_names.extend(prior)
    internal_sets.extend(prior)
    draw_filters = {
        "process_execution": execution.name,
        "status": ["!=", "Cancelled"],
    }
    # A reusable Process/Station Card owns a separate runtime execution but reports
    # against the same ERP Job Card.  Certificate evidence scanned there must therefore
    # be visible to the Work Order-owning execution without duplicating a material scan.
    if execution.job_card:
        draw_filters = {
            "job_card": execution.job_card,
            "operation": execution.operation,
            "status": ["!=", "Cancelled"],
        }
    draws = frappe.get_all(
        "CFG Kanban Operation Material Draw",
        filters=draw_filters,
        pluck="source_handling_unit", limit_page_length=0,
    )
    unit_names.extend(draws)
    if stock_entry:
        trace = frappe.db.get_value(
            "CFG Kanban Material Trace", {"stock_entry": stock_entry.name}, "name"
        )
        if trace:
            unit_names.extend(frappe.get_all(
                "CFG Kanban Material Trace Line",
                filters={
                    "parent": trace,
                    "direction": "Input",
                    "status": ["in", ["Reserved", "Confirmed"]],
                },
                pluck="handling_unit", limit_page_length=0,
            ))
    unit_names = list(dict.fromkeys(name for name in unit_names if name))
    if unit_names:
        set_names.extend(frappe.get_all(
            "CFG Kanban Handling Unit",
            filters={"name": ["in", unit_names], "process_certificate_set": ["is", "set"]},
            pluck="process_certificate_set", limit_page_length=0,
        ))
    return {
        "unit_names": unit_names,
        "set_names": list(dict.fromkeys(name for name in set_names if name)),
        "internal_set_names": list(dict.fromkeys(internal_sets)),
    }


def _prior_execution_sets(execution):
    cycle_name = _certificate_owner_cycle(execution)
    return frappe.get_all(
        "CFG Kanban Process Execution",
        filters={
            "kanban_cycle": cycle_name,
            "sequence": ["<", execution.sequence],
            "status": "Completed",
            "result_certificate_set": ["is", "set"],
        },
        pluck="result_certificate_set", order_by="sequence asc, creation asc",
        limit_page_length=0,
    )


def _latest_internal_set(execution):
    cycle_name = _certificate_owner_cycle(execution)
    rows = frappe.get_all(
        "CFG Kanban Process Execution",
        filters={
            "kanban_cycle": cycle_name,
            "sequence": ["<", execution.sequence],
            "status": "Completed",
            "result_certificate_set": ["is", "set"],
        },
        fields=["result_certificate_set"], order_by="sequence desc, creation desc",
        limit_page_length=1,
    )
    return rows[0].result_certificate_set if rows else None


def _certificate_owner_cycle(execution):
    if not execution.job_card:
        return execution.kanban_cycle
    work_order = frappe.db.get_value("Job Card", execution.job_card, "work_order")
    return (
        frappe.db.get_value("Work Order", work_order, "cfg_kanban_cycle")
        if work_order else None
    ) or execution.kanban_cycle


def _member_union(set_names):
    members = {}
    for set_name in set_names:
        certificate_set = frappe.get_doc("CFG Process Certificate Set", set_name)
        for row in certificate_set.members:
            members[row.certificate_type] = max(
                members.get(row.certificate_type, 0), cint(row.revision_snapshot)
            )
    return members


def _requirement_passes(evidence, row):
    certificate_type = row.certificate_type
    minimum_revision = cint(row.minimum_revision or 1)
    trusted = _member_union(evidence["internal_set_names"])
    if trusted.get(certificate_type, 0) >= minimum_revision:
        return True
    now = now_datetime()
    for unit_name in evidence["unit_names"]:
        set_name = frappe.db.get_value(
            "CFG Kanban Handling Unit", unit_name, "process_certificate_set"
        )
        if not set_name:
            continue
        members = _member_union([set_name])
        if members.get(certificate_type, 0) < minimum_revision:
            continue
        if not cint(row.require_unexpired):
            return True
        certificates = frappe.get_all(
            "CFG Process Certificate",
            filters={
                "handling_unit": unit_name,
                "certificate_type": certificate_type,
                "status": "Active",
                "revision_snapshot": [">=", minimum_revision],
            },
            fields=["valid_until"], limit_page_length=0,
        )
        if any(
            not certificate.valid_until or certificate.valid_until >= now
            for certificate in certificates
        ):
            return True
    return False


def _certificate_set(members, master_name, operation):
    canonical = sorted([[name, cint(revision)] for name, revision in members.items()])
    signature = hashlib.sha256(
        json.dumps(canonical, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    existing = frappe.db.get_value(
        "CFG Process Certificate Set", {"signature_hash": signature}, "name"
    )
    if existing:
        return frappe.get_doc("CFG Process Certificate Set", existing)
    return frappe.get_doc({
        "doctype": "CFG Process Certificate Set",
        "active": 1,
        "members": [{"certificate_type": name} for name in sorted(members)],
        "notes": f"Generated by Production Master {master_name} / {operation}",
    }).insert(ignore_permissions=True)


def _issue_finished_output_certificates(master, cycle, doc, row, line, result_set):
    result_members = _member_union([result_set])
    effective_rules = {}
    for rule in master.certificate_output_rules:
        if (rule.issue_scope != "Finished Output"
                or rule.certificate_type not in result_members
                or rule.action not in ("Issue", "Retain")):
            continue
        current = effective_rules.get(rule.certificate_type)
        if not current or rule.action == "Issue":
            effective_rules[rule.certificate_type] = rule
    source_units = _production_source_units(doc)
    for rule in effective_rules.values():
        key = canonical_key(
            f"production-certificate-{rule.action.lower()}", doc.name, line.name,
            rule.operation, rule.certificate_type,
        )
        if frappe.db.exists("CFG Process Certificate", {"idempotency_key": key}):
            continue
        certificate_type = frappe.get_doc(
            "CFG Process Certificate Type", rule.certificate_type
        )
        source_certificate = (
            _active_input_certificate(source_units, rule.certificate_type)
            if rule.action == "Retain" else None
        )
        if rule.action == "Retain" and not source_certificate:
            frappe.throw(
                f"Cannot bind retained certificate {rule.certificate_type} to output "
                f"tag {line.handling_unit}; source certificate evidence is missing"
            )
        validity_days = cint(rule.validity_days_override or certificate_type.validity_days)
        issued_on = now_datetime()
        valid_from = source_certificate.valid_from if source_certificate else issued_on
        valid_until = (
            source_certificate.valid_until if source_certificate
            else add_days(issued_on, validity_days) if validity_days else None
        )
        execution = frappe.db.get_value(
            "CFG Kanban Process Execution",
            {
                "kanban_cycle": cycle.name,
                "operation": rule.operation,
                "status": "Completed",
            },
            ["name", "job_card", "workstation", "operator"], as_dict=True,
        )
        progress = None
        if execution:
            progress = frappe.db.get_value(
                "CFG Kanban Operation Progress",
                {"process_execution": execution.name, "cancelled": 0},
                ["operator", "operator_session", "terminal_user"],
                order_by="posting_datetime desc", as_dict=True,
            )
        frappe.get_doc({
            "doctype": "CFG Process Certificate",
            "status": "Active",
            "certificate_type": rule.certificate_type,
            "certificate_set": result_set,
            "handling_unit": line.handling_unit,
            "item_code": row.item_code,
            "certified_qty": line.qty,
            "stock_uom": row.stock_uom,
            "inventory_company": doc.company,
            "warehouse": row.t_warehouse,
            "batch_no": line.batch_no,
            "kanban_cycle": cycle.name,
            "kanban_master": master.name,
            "kanban_card": cycle.kanban_card,
            "process_execution": execution.name if execution else None,
            "work_order": doc.work_order,
            "job_card": execution.job_card if execution else None,
            "operation": rule.operation,
            "workstation": execution.workstation if execution else None,
            "issued_on": issued_on,
            "issued_by_operator": (progress.operator if progress else None)
                or (execution.operator if execution else None),
            "operator_session": progress.operator_session if progress else None,
            "terminal_user": (progress.terminal_user if progress else None)
                or frappe.session.user,
            "valid_from": valid_from,
            "valid_until": valid_until,
            "source_reference_doctype": (
                "CFG Process Certificate" if source_certificate else "Stock Entry"
            ),
            "source_reference_name": (
                source_certificate.name if source_certificate else doc.name
            ),
            "evidence_references": (
                source_certificate.evidence_references if source_certificate else None
            ),
            "idempotency_key": key,
        }).insert(ignore_permissions=True)


def _prior_issue_rule(master, execution, certificate_type):
    operation_sequences = {
        row.operation: cint(row.sequence) for row in master.operation_profiles
    }
    return any(
        row.certificate_type == certificate_type
        and row.action == "Issue"
        and operation_sequences.get(row.operation, 0) < cint(execution.sequence)
        for row in master.certificate_output_rules
    )


def _active_input_certificate(unit_names, certificate_type):
    if not unit_names:
        return None
    rows = frappe.get_all(
        "CFG Process Certificate",
        filters={
            "handling_unit": ["in", unit_names],
            "certificate_type": certificate_type,
            "status": "Active",
        },
        fields=["name", "valid_from", "valid_until", "evidence_references"],
        order_by="issued_on desc", limit_page_length=0,
    )
    now = now_datetime()
    return next(
        (row for row in rows if not row.valid_until or row.valid_until >= now), None
    )


def _production_source_units(doc):
    units = frappe.get_all(
        "CFG Kanban Operation Material Draw",
        filters={"work_order": doc.work_order, "status": ["!=", "Cancelled"]},
        pluck="source_handling_unit", limit_page_length=0,
    )
    trace = frappe.db.get_value(
        "CFG Kanban Material Trace", {"stock_entry": doc.name}, "name"
    )
    if trace:
        units.extend(frappe.get_all(
            "CFG Kanban Material Trace Line",
            filters={
                "parent": trace,
                "direction": "Input",
                "status": "Confirmed",
            },
            pluck="handling_unit", limit_page_length=0,
        ))
    return list(dict.fromkeys(unit for unit in units if unit))


def _execution(value):
    return value if getattr(value, "doctype", None) else frappe.get_doc(
        "CFG Kanban Process Execution", value
    )


def _stock_qty(row):
    """Return one Stock Entry Detail quantity in ERPNext's authoritative Stock UOM."""
    transfer_qty = flt(row.get("transfer_qty"))
    if transfer_qty:
        return transfer_qty
    return flt(row.get("qty")) * flt(row.get("conversion_factor") or 1)
