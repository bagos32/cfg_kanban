"""Optional printed-expiry handoff to finished ERP Batches and per-card source cohorts."""
import frappe
from frappe.utils import cint, getdate, today

from cfg_kanban.services.certificate_output_evidence import certificate_output_evidence, printed_expiry_dates


def manufacture_printed_expiry_sources(work_order, company, strict=True):
    sources = {}
    # Only positive actual usage, not unused draws or BOM estimates, can set finished expiry.
    for draw in frappe.get_all("CFG Kanban Operation Material Draw", filters={
        "work_order":work_order,"used_qty":[">",0],
        "status":["in",["Used","Partially Used","Carry Forward"]]},
        fields=["name","source_handling_unit","item_code","stock_uom"],limit_page_length=0):
        unit = frappe.get_doc("CFG Kanban Handling Unit",draw.source_handling_unit)
        if unit.inventory_company != company or unit.item_code != draw.item_code or unit.stock_uom != draw.stock_uom:
            if strict:
                frappe.throw("Consumed source identity changed; reconcile it before copying printed expiry")
            return {"dates":[],"sources":[]}
        key = (unit.name,unit.process_certificate_set,unit.item_code,unit.stock_uom)
        sources[key] = None
    # Settled sources use the native input's certificate dimension snapshot, even after
    # the old tag is consumed. Do not substitute an unrelated current certificate set.
    if frappe.get_meta("Stock Entry Detail").has_field("process_certificate_set"):
        for row in frappe.db.sql("""
            select distinct line.handling_unit, sed.process_certificate_set as certificate_set,
                            line.item_code, line.stock_uom
            from `tabCFG Kanban Material Trace Line` line
            join `tabCFG Kanban Material Trace` trace on trace.name=line.parent
            join `tabStock Entry` se on se.name=trace.stock_entry
            join `tabStock Entry Detail` sed on sed.name=line.stock_entry_detail and sed.parent=se.name
            where se.work_order=%s and se.company=%s and se.docstatus=1
              and se.purpose in ('Material Consumption for Manufacture','Manufacture')
              and trace.status='Confirmed' and line.status='Confirmed' and line.direction='Input'
              and line.qty>0 and coalesce(line.handling_unit,'')!=''
              and sed.item_code=line.item_code and sed.stock_uom=line.stock_uom
        """,(work_order,company),as_dict=True):
            sources[(row.handling_unit,row.certificate_set,row.item_code,row.stock_uom)] = None
    result, dates = [], set()
    for unit, certificate_set, item, uom in sorted(sources,key=lambda key:tuple(str(value or '') for value in key)):
        printing = certificate_output_evidence(unit,certificate_set,item,uom)
        values = printed_expiry_dates(printing)
        if values:
            dates.update(str(getdate(value)) for value in values)
            result.append({"handling_unit":unit,"certificate_set":certificate_set,"printing":printing})
    return {"dates":sorted(dates),"sources":result}


def selected_manufacture_printed_expiry(work_order, company):
    evidence = manufacture_printed_expiry_sources(work_order,company)
    if not evidence["dates"]:
        frappe.throw("No posted printing expiry is proven by the consumed materials")
    if any(proof["status"]!="Active" for source in evidence["sources"]
           for printing in source["printing"] for proof in printing.get("certificate_provenance",[])):
        frappe.throw("Consumed printing certificate provenance is revoked, expired or superseded; reconcile it before copying expiry")
    if len(evidence["dates"]) != 1:
        frappe.throw("Consumed materials have different printed expiries. Separate the production batches; automatic Batch expiry requires one matching printed date")
    expiry = evidence["dates"][0]
    if getdate(expiry) < getdate(today()):
        frappe.throw("The consumed packaging's printed expiry has passed; reconcile this production batch")
    return expiry, evidence["sources"]


def validate_manufacture_printed_expiry(doc):
    """Recheck an opted-in Draft at native submission without altering existing Batches."""
    if doc.get("purpose") != "Manufacture" or not doc.get("cfg_kanban_cycle"):
        return
    commands = frappe.get_all("CFG ERP Command", filters={
        "command_type":"Create Production Manufacture Receipt", "target_doctype":"Stock Entry",
        "target_document":doc.name},fields=["request_payload"],limit_page_length=0)
    for command in commands:
        payload = frappe.parse_json(command.request_payload or "{}")
        if not cint(payload.get("use_printed_expiry")):
            continue
        expiry, evidence = selected_manufacture_printed_expiry(doc.work_order,doc.company)
        if expiry != payload.get("printed_expiry") or evidence != payload.get("printed_expiry_evidence"):
            frappe.throw("Consumed printed-expiry evidence changed after receipt preparation. Reconcile this Draft")
        order = frappe.get_doc("Work Order",doc.work_order)
        outputs = [row for row in doc.items if row.t_warehouse and not row.s_warehouse and row.item_code==order.production_item]
        if not outputs:
            frappe.throw("Manufacture has no finished output for its selected printed expiry")
        for row in outputs:
            actual = frappe.db.get_value("Batch",row.batch_no,"expiry_date") if row.batch_no else None
            if not actual or getdate(actual) != getdate(expiry):
                frappe.throw("Finished Batch expiry must match the selected printed expiry")


def assert_process_cycle_printed_expiry(execution, unit, current=False):
    """Pin printing dates inside one Process Card cycle, never across future card uses."""
    printing = certificate_output_evidence(unit.name,unit.process_certificate_set,unit.item_code,unit.stock_uom)
    source_dates = set(printed_expiry_dates(printing))
    # A current locking read also covers other lanes confirming a source after a preview.
    # Material Run confirmation already holds the Work Order lock before taking this read.
    lock = "for update" if current else ""
    draws = frappe.db.sql(f"""
        select source_handling_unit, item_code, stock_uom, material_rotation_evidence
        from `tabCFG Kanban Operation Material Draw`
        where kanban_cycle=%s and status!='Cancelled' and drawn_qty>0
        {lock}
    """,execution.kanban_cycle,as_dict=True)
    dates, printed_items, cache = set(), set(), {}
    for draw in draws:
        saved = frappe.parse_json(draw.material_rotation_evidence or "{}")
        values = [saved["printed_expiry_date"]] if saved.get("printed_expiry_date") else []
        if not values:
            if draw.source_handling_unit not in cache:
                old = frappe.get_doc("CFG Kanban Handling Unit",draw.source_handling_unit)
                cache[old.name] = printed_expiry_dates(certificate_output_evidence(
                    old.name,old.process_certificate_set,old.item_code,old.stock_uom))
            values = cache[draw.source_handling_unit]
        if values:
            dates.update(values);printed_items.add(draw.item_code)
    if not source_dates and unit.item_code not in printed_items:
        return {"printed_expiry_date":None,"printed_expiry_cycle":execution.kanban_cycle}
    if len(source_dates)!=1 or len(dates)>1:
        frappe.throw("This Process Card cycle requires one matching printed expiry. Reconcile mixed sources or close the current cycle/batch before starting another")
    selected = next(iter(source_dates))
    if dates and selected not in dates:
        expected = next(iter(dates))
        from cfg_kanban.services.material_rotation import _rotation_candidates
        suggestions = []
        for candidate in _rotation_candidates(unit):
            if candidate.batch_no and (candidate.batch_item!=unit.item_code or cint(candidate.batch_disabled)):
                continue
            values = set(printed_expiry_dates(certificate_output_evidence(
                candidate.name,unit.process_certificate_set,unit.item_code,unit.stock_uom)))
            stock_dates = [getdate(value) for value in (candidate.expiry_date,candidate.batch_expiry,*values) if value]
            if values=={expected} and (not stock_dates or min(stock_dates)>=getdate(today())):
                suggestions.append(candidate.scan_code)
        choices = ", ".join(sorted(set(suggestions))[:3]) or "none available in this warehouse"
        frappe.throw(f"This Process Card cycle uses printed expiry {expected}; the scanned tag has {selected}. "
            f"Matching source suggestions: {choices}. FEFO still applies. Use a matching source, or report completed work "
            "and close the current cycle/batch through the normal checks, then start a new cycle for the other expiry")
    return {"printed_expiry_date":selected,"printed_expiry_cycle":execution.kanban_cycle}
