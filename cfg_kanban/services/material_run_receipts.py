"""Reconcile final Manufacture inputs to completed, audited Material Run actuals.

A BOM balance is an estimate, not evidence that stock was physically consumed.
This module never edits submitted stock or relaxes the physical-tag validator.
"""
import math

import frappe
from frappe.utils import flt

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key

TOLERANCE = 0.000001


def _stock_qty(row):
    return flt(row.get("transfer_qty") or flt(row.qty) * flt(row.conversion_factor or 1))


def _receipt_scopes(order, jobs, executions):
    """Only replace BOM groups wholly covered by immutable tracked-rule snapshots."""
    required = {}
    for row in order.required_items:
        key = (row.item_code, row.source_warehouse, row.stock_uom)
        required.setdefault(key, []).append(row)
    ratios = {}
    execution_rules = {}
    for execution in executions:
        if execution.material_run_control not in ("Optional", "Required Before Progress"):
            continue
        rules = frappe.parse_json(execution.material_run_rules_json or "[]") or []
        for rule in rules:
            key = (rule.get("item_code"), rule.get("scan_warehouse"), rule.get("stock_uom"))
            ratio = flt(rule.get("qty_per_output"))
            if key not in required or not math.isfinite(ratio) or ratio <= TOLERANCE:
                continue
            if rule.get("operation") != execution.operation:
                continue
            ratios.setdefault(key, {}).setdefault(execution.operation, set()).add(ratio)
            execution_rules[(execution.name, rule.get("rule_row"))] = (key, execution.operation)
    covered = {}
    for key, rows in required.items():
        by_operation = ratios.get(key, {})
        if not by_operation or any(len(values) != 1 for values in by_operation.values()):
            continue
        if any(row.operation and row.operation not in by_operation for row in rows):
            continue
        expected = sum(flt(row.required_qty) for row in rows)
        tracked = sum(next(iter(values)) for values in by_operation.values()) * flt(order.qty)
        # Includes blank-operation Work Order rows, but only when the tracked ratios
        # prove the complete component estimate. Mixed tracked/untracked use stays native.
        if not math.isfinite(tracked) or not math.isfinite(expected) or abs(tracked - expected) > TOLERANCE:
            continue
        owners = {job.name for job in jobs if job.operation in by_operation and flt(job.for_quantity) > TOLERANCE}
        if owners:
            covered[key] = owners
    return covered, execution_rules


def _validated_draw_posting(draw, entry, order, cache):
    """Validate each existing adoption against its live native posting and trace line."""
    if not draw.material_trace or not draw.material_trace_line:
        if draw.status == "Bound to ERP":
            frappe.throw("A settled Material Draw is missing its ERP trace; reconcile it before Manufacture")
        return False
    def document(doctype, name):
        key = (doctype, name)
        if key not in cache:
            cache[key] = frappe.get_doc(doctype, name)
        return cache[key]
    trace = document("CFG Kanban Material Trace", draw.material_trace)
    native = document("Stock Entry", trace.stock_entry)
    line = next((row for row in trace.lines if row.name == draw.material_trace_line), None)
    if (native.work_order != order.name or native.company != order.company
            or native.purpose not in ("Material Consumption for Manufacture", "Manufacture")
            or not line or line.direction != "Input" or line.handling_unit != draw.source_handling_unit
            or line.item_code != draw.item_code or line.warehouse != draw.source_warehouse
            or line.stock_uom != draw.stock_uom or abs(flt(line.qty) - flt(draw.used_qty)) > TOLERANCE):
        frappe.throw("Material Draw ERP evidence does not match its actual use; reconcile it before Manufacture")
    if draw.status == "Bound to ERP":
        if native.docstatus != 1 or line.status != "Confirmed":
            frappe.throw("Material Draw settlement is not submitted; reconcile its ERP posting before Manufacture")
        return True
    if native.name != entry.name or native.docstatus != 0 or line.status != "Reserved":
        frappe.throw("Submit or discard the earlier Material Run Draft before preparing Manufacture")
    return False


def _receipt_evidence(order, strict=True):
    if not order.skip_transfer or order.docstatus != 1 or flt(order.qty) <= 0:
        return {}, {}, {}
    jobs = frappe.get_all("Job Card", filters={"work_order":order.name,"docstatus":["<",2]},
        fields=["name","operation","docstatus","status","for_quantity"],limit_page_length=0)
    if not jobs or any(job.docstatus != 1 or job.status != "Completed" for job in jobs):
        return {}, {}, {}
    executions = frappe.get_all("CFG Kanban Process Execution",
        filters={"job_card":["in",[job.name for job in jobs]],"status":["!=","Cancelled"]},
        fields=["name","job_card","operation","material_run_control","material_run_rules_json",
                "material_run_settlement_timing"],limit_page_length=0)
    scopes, rules = _receipt_scopes(order, jobs, executions)
    if not scopes:
        return {}, {}, {}
    owners = {execution.name:execution for execution in executions}
    draws = frappe.get_all("CFG Kanban Operation Material Draw",
        filters={"work_order":order.name,"status":["!=","Cancelled"],"used_qty":[">",TOLERANCE]},
        fields=["name","process_execution","job_card","operation","material_flow_rule_row","status",
            "item_code","source_warehouse","stock_uom","source_handling_unit","used_qty",
            "material_trace","material_trace_line"],limit_page_length=0)
    grouped = {}
    for draw in draws:
        key = (draw.item_code,draw.source_warehouse,draw.stock_uom)
        owner = owners.get(draw.process_execution)
        if key not in scopes:
            continue
        if (not owner or draw.job_card != owner.job_card or draw.operation != owner.operation
                or rules.get((owner.name,draw.material_flow_rule_row)) != (key,owner.operation)):
            if strict:
                frappe.throw("Material Draw does not match its snapshotted material rule; reconcile it before Manufacture")
            return {}, {}, {}
        if not math.isfinite(flt(draw.used_qty)) or flt(draw.used_qty) <= TOLERANCE:
            if strict:
                frappe.throw("Invalid actual Material Run quantity")
            return {}, {}, {}
        grouped.setdefault(key,[]).append(draw)
    scopes = {key:jobs for key,jobs in scopes.items()
              if jobs.issubset({draw.job_card for draw in grouped.get(key,[])})}
    if not scopes:
        return {}, {}, {}
    return owners, grouped, scopes


def material_run_receipt_summary(order):
    """Read-only recorded usage; strict native posting validation follows at preparation."""
    _owners, grouped, scopes = _receipt_evidence(order, strict=False)
    return [{"item_code":key[0],"source_warehouse":key[1],"stock_uom":key[2],
        "used_qty":sum(flt(draw.used_qty) for draw in grouped[key]),
        "settled_qty":sum(flt(draw.used_qty) for draw in grouped[key] if draw.status=="Bound to ERP"),
        "pending_qty":sum(flt(draw.used_qty) for draw in grouped[key] if draw.status!="Bound to ERP")}
        for key in scopes]


def reconcile_manufacture_material_runs(entry):
    """Set Draft inputs to remaining actual use; preserve unrelated/untagged BOM inputs.

    Repeated calls are absolute and idempotent, including after receipt-draw adoption.
    A submitted native document is never changed. Existing trace reservations are a
    lower bound: a correction cannot silently remove an allocated physical quantity.
    """
    if (entry.get("purpose") != "Manufacture" or not entry.get("cfg_kanban_cycle")
            or not entry.get("work_order") or entry.docstatus == 2):
        return []
    if entry.name and frappe.db.get_value("Stock Entry", entry.name, "docstatus") == 1:
        return []
    order = frappe.get_doc("Work Order", entry.work_order)
    cycle_order = frappe.db.get_value("CFG Kanban Cycle", entry.cfg_kanban_cycle, "work_order")
    if cycle_order != order.name or entry.company != order.company:
        frappe.throw("Manufacture receipt does not match the Kanban Work Order and Company")
    if not order.skip_transfer or order.docstatus != 1 or flt(order.qty) <= 0:
        return []
    owners, grouped, scopes = _receipt_evidence(order)
    if not scopes:
        return []
    open_runs = frappe.get_all("CFG Kanban Operation Material Run",
        filters={"process_execution":["in",list(owners)],"status":"Open"},pluck="name",limit_page_length=0)
    if open_runs:
        frappe.throw("Close or cancel the open Material Run before receiving output: " + ", ".join(open_runs))
    posted = frappe.db.sql("""
        select sed.item_code, sed.s_warehouse as warehouse, sed.stock_uom,
               sum(coalesce(nullif(sed.transfer_qty,0),sed.qty*coalesce(nullif(sed.conversion_factor,0),1))) as qty
        from `tabStock Entry Detail` sed join `tabStock Entry` se on se.name=sed.parent
        where se.work_order=%s and se.docstatus=1
          and se.purpose in ('Material Consumption for Manufacture','Manufacture')
          and coalesce(sed.s_warehouse,'')!='' and coalesce(sed.t_warehouse,'')=''
        group by sed.item_code, sed.s_warehouse, sed.stock_uom
    """,order.name,as_dict=True)
    posted_qty = {(row.item_code,row.warehouse,row.stock_uom):flt(row.qty) for row in posted}
    cache, pending, evidence = {}, {}, {}
    for key in scopes:
        settled = 0
        pending[key] = 0
        evidence[key] = [draw.name for draw in grouped[key]]
        for draw in grouped[key]:
            if _validated_draw_posting(draw,entry,order,cache):
                settled += flt(draw.used_qty)
            else:
                timing = owners[draw.process_execution].material_run_settlement_timing
                if timing != "At Work Order Manufacture Receipt":
                    frappe.throw("Settle the Job Card-end Material Runs before receiving output")
                pending[key] += flt(draw.used_qty)
        if abs(settled-posted_qty.get(key,0)) > TOLERANCE:
            frappe.throw("Submitted ERP consumption differs from Material Run actuals; reconcile it before Manufacture")
    trace_name = frappe.db.get_value("CFG Kanban Material Trace",{"stock_entry":entry.name},"name") if entry.name else None
    trace = frappe.get_doc("CFG Kanban Material Trace",trace_name) if trace_name else None
    allocated = {}
    for line in trace.lines if trace else []:
        if line.direction == "Input" and line.status in ("Reserved","Confirmed"):
            allocated[line.stock_entry_detail] = allocated.get(line.stock_entry_detail,0)+flt(line.qty)
    entry._cfg_material_run_receipt_keys = set(pending)
    adjustments = []
    for key,desired in pending.items():
        rows = [row for row in entry.items if row.s_warehouse and not row.t_warehouse
                and (row.item_code,row.s_warehouse,row.stock_uom)==key]
        before = sum(_stock_qty(row) for row in rows)
        if desired > TOLERANCE and not rows:
            frappe.throw("ERPNext did not map the pending Material Run input; rebuild and reconcile the Manufacture Draft")
        if abs(before-desired) <= TOLERANCE:
            continue
        reserved = sum(allocated.get(row.name,0) for row in rows)
        if reserved > desired+TOLERANCE:
            frappe.throw("Existing input tags exceed corrected Material Run actuals; cancel the affected trace allocations first")
        if desired > before:
            rows[0].transfer_qty = _stock_qty(rows[0])+desired-before
            rows[0].qty = rows[0].transfer_qty/flt(rows[0].conversion_factor or 1)
        else:
            reduction = before-desired
            for row in reversed(rows):
                current = _stock_qty(row)
                take = min(reduction,max(0,current-allocated.get(row.name,0)))
                row.transfer_qty = current-take
                row.qty = row.transfer_qty/flt(row.conversion_factor or 1)
                reduction -= take
                if row.transfer_qty <= TOLERANCE and not allocated.get(row.name,0):
                    entry.remove(row)
        adjustments.append({"item_code":key[0],"warehouse":key[1],"stock_uom":key[2],
            "mapped_qty":before,"actual_pending_qty":desired,"material_draws":evidence[key]})
    if adjustments:
        record("Manufacture Material Run Actuals Applied",work_order=order.name,
            cycle=entry.cfg_kanban_cycle,reference_doctype="Work Order",reference_name=order.name,
            payload={"stock_entry":entry.name,"adjustments":adjustments},
            notes="Unused BOM estimates excluded; only recorded unposted Material Run consumption remains",
            idempotency_key=canonical_key("manufacture-material-run-actuals",order.name,entry.name or "new",
                                         entry.get("fg_completed_qty"),adjustments))
    return adjustments
