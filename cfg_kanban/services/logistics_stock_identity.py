"""Preserve physical stock identity and certificate provenance through logistics.

Movement is not certification: never extend validity or rewrite issuance history.
"""
import json

import frappe
from frappe.utils import flt, get_datetime, now_datetime

from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.certificate_output_evidence import certificate_output_evidence, printed_expiry_dates

COPY_FIELDS = (
    "process_certificate_set", "expiry_date", "packed_on", "short_description",
    "work_order", "current_operation", "kanban_cycle", "kanban_card",
)
IDENTITY_FIELDS = ("item_code", "batch_no", "stock_uom", *COPY_FIELDS)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _serials(unit):
    return sorted(frappe.get_all("CFG Kanban Handling Unit Serial",
        filters={"handling_unit": unit.name, "state": "Active"}, pluck="serial_no", limit_page_length=0))


def identity_snapshot(unit):
    result = {field: unit.get(field) or None for field in IDENTITY_FIELDS}
    result["handling_unit"] = unit.name
    result["serial_nos"] = _serials(unit)
    if frappe.db.get_value("Item", unit.item_code, "has_serial_no") and len(result["serial_nos"]) != flt(unit.current_qty):
        frappe.throw("Serial-controlled stock requires complete exact serial assignments on its tag before logistics movement")
    result["batch_expiry_date"] = str(frappe.db.get_value("Batch", unit.batch_no, "expiry_date") or "") if unit.batch_no else ""
    result["certificates"] = sorted(frappe.get_all("CFG Process Certificate",
        filters={"handling_unit": unit.name, "certificate_set": unit.get("process_certificate_set")},
        fields=["name", "certificate_type", "revision_snapshot", "valid_from", "valid_until",
                "status", "source_reference_doctype", "source_reference_name"],
        limit_page_length=0), key=lambda row: row.name) if unit.get("process_certificate_set") else []
    printing = certificate_output_evidence(unit.name, unit.get("process_certificate_set"), unit.item_code, unit.stock_uom)
    if printing:
        result["certificate_output_evidence"] = printing
    return json.loads(_json(result))


def capture_manifest_line(line):
    if not line.handling_unit:
        return
    unit = frappe.get_doc("CFG Kanban Handling Unit", line.handling_unit)
    snapshot = identity_snapshot(unit)
    if line.get("stock_identity_snapshot"):
        if json.loads(line.stock_identity_snapshot) != snapshot:
            frappe.throw("Stock Tag certificate, expiry, serial or trace identity changed after selection. Reconcile the Manifest; do not transfer with stale evidence.")
        if (line.get("process_certificate_set") or None) != snapshot["process_certificate_set"] or str(line.get("expiry_date") or "") != _expiry(snapshot):
            frappe.throw("Manifest certificate/expiry fields differ from their immutable stock identity snapshot")
    else:
        line.process_certificate_set = snapshot["process_certificate_set"]
        line.expiry_date = _expiry(snapshot) or None
        line.stock_identity_snapshot = _json(snapshot)


def _expiry(snapshot):
    dates = [snapshot.get("expiry_date"), snapshot.get("batch_expiry_date"),
             *printed_expiry_dates(snapshot.get("certificate_output_evidence", []))]
    return min(str(value)[:10] for value in dates if value) if any(dates) else ""



def validate_saved_manifest_fields(line):
    """Freeze historical line fields without requiring live stock to remain unchanged.

    Cancellation/history editing must still work after a revocation or later movement.
    Current source identity is checked separately immediately before ERP posting.
    """
    if not line.get("stock_identity_snapshot"):
        return
    saved = json.loads(line.stock_identity_snapshot)
    expected = {field: saved.get(field) or None for field in ("item_code", "batch_no", "stock_uom", "process_certificate_set")}
    expected["expiry_date"] = _expiry(saved) or None
    if any(str(line.get(field) or "") != str(value or "") for field, value in expected.items()):
        frappe.throw("Historical Manifest stock identity fields must match their immutable snapshot")


def _line_identity(line):
    if not line.get("handling_unit"):
        if line.get("process_certificate_set"):
            frappe.throw("Certified logistics stock requires its exact physical tag; an untagged line cannot infer certificate evidence")
        filters = {"inventory_company": line.get("source_company"),
                   "current_warehouse": line.get("source_warehouse"), "item_code": line.get("item_code"),
                   "identity_state": "Active", "current_qty": [">", 0],
                   "process_certificate_set": ["is", "set"]}
        if line.get("batch_no"):
            filters["batch_no"] = line.batch_no
        if frappe.db.exists("CFG Kanban Handling Unit", filters):
            frappe.throw("Certified stock exists in this source scope. Select its physical tag instead of an ambiguous untagged transfer.")
        if frappe.get_meta("Stock Ledger Entry").has_field("process_certificate_set"):
            batch_condition = "and batch_no=%(batch)s" if line.get("batch_no") else ""
            balances = frappe.db.sql(f"""
                select process_certificate_set
                from `tabStock Ledger Entry`
                where company=%(company)s and warehouse=%(warehouse)s and item_code=%(item)s
                  and is_cancelled=0 and ifnull(process_certificate_set,'')!=''
                  {batch_condition}
                group by process_certificate_set having sum(actual_qty)>0.000001
            """, {"company":line.get("source_company"), "warehouse":line.get("source_warehouse"),
                  "item":line.get("item_code"), "batch":line.get("batch_no")})
            if balances:
                frappe.throw("Certified ERP stock exists in this source scope. Reconcile its exact tag/certificate identity before an untagged transfer.")
        return {"process_certificate_set": None, "serial_nos": []}
    unit = frappe.get_doc("CFG Kanban Handling Unit", line.handling_unit)
    current = identity_snapshot(unit)
    if not line.get("stock_identity_snapshot"):
        if unit.get("process_certificate_set"):
            frappe.throw("This certified Manifest line has no stock identity snapshot. Reconcile or rescan it before posting; do not rewrite submitted ERP history.")
        return current
    saved = json.loads(line.stock_identity_snapshot)
    if saved != current:
        frappe.throw("Source stock identity changed after Manifest preparation. Review certificates, expiry and serials before posting.")
    if (line.get("process_certificate_set") or None) != saved["process_certificate_set"]:
        frappe.throw("Manifest Process Certificate Set differs from its stock identity snapshot")
    if str(line.get("expiry_date") or "") != _expiry(saved):
        frappe.throw("Manifest expiry differs from its stock identity snapshot")
    for field in ("item_code", "batch_no", "stock_uom"):
        if (line.get(field) or None) != (saved.get(field) or None):
            frappe.throw("Manifest Item, Batch or UOM differs from its stock identity snapshot")
    return saved


def erp_identity_fields(line, child_doctype, transfer=False):
    identity = _line_identity(line)
    certificate_set = identity.get("process_certificate_set")
    meta = frappe.get_meta(child_doctype)
    required = ["process_certificate_set"] + (["to_process_certificate_set"] if transfer else [])
    if certificate_set and any(not meta.has_field(field) for field in required):
        frappe.throw("Run the CFG Kanban certificate Inventory Dimension migration before moving certified stock")
    result = {field: certificate_set for field in required if meta.has_field(field)}
    serials = identity.get("serial_nos") or []
    if serials:
        result["serial_no"] = "\n".join(serials)
    if serials or identity.get("batch_no"):
        result["use_serial_batch_fields"] = 1
    return result


def fields_for_tag(unit_name, child_doctype):
    if not unit_name:
        return {}
    unit = frappe.get_doc("CFG Kanban Handling Unit", unit_name)
    line = frappe._dict(handling_unit=unit.name, item_code=unit.item_code,
        batch_no=unit.batch_no, stock_uom=unit.stock_uom,
        process_certificate_set=unit.get("process_certificate_set"), expiry_date=_expiry(identity_snapshot(unit)) or None,
        stock_identity_snapshot=_json(identity_snapshot(unit)))
    return erp_identity_fields(line, child_doctype)


def fields_for_manifest_reference(row, child_doctype):
    line = frappe.get_doc("CFG Kanban Manifest Line", row["manifest_line"])
    if (line.get("handling_unit") or None) != (row.get("handling_unit") or None) or line.item_code != row["item_code"]:
        frappe.throw("ERP logistics row differs from its authoritative Manifest line")
    return erp_identity_fields(line, child_doctype)


def validate_logistics_document(doc, method=None):
    if not doc.get("cfg_movement_manifest"):
        if doc.get("cfg_delivery_session") or (doc.doctype == "Stock Entry" and doc.get("cfg_kanban_controlled") and
                (doc.get("purpose") == "Material Transfer" or doc.get("cfg_withdrawal_cycle"))):
            for row in doc.items:
                if not row.get("cfg_handling_unit"):
                    continue
                unit = frappe.get_doc("CFG Kanban Handling Unit", row.cfg_handling_unit)
                expected = fields_for_tag(unit.name, row.doctype)
                if doc.doctype == "Stock Entry" and row.get("t_warehouse"):
                    expected["to_process_certificate_set"] = unit.get("process_certificate_set")
                if any((row.get(field) or None) != (value or None) for field, value in expected.items()
                       if field in ("process_certificate_set", "to_process_certificate_set")):
                    frappe.throw("Controlled logistics certificate dimensions differ from the selected physical stock")
                if (row.get("batch_no") or None) != (unit.batch_no or None):
                    frappe.throw("Controlled logistics Batch differs from the selected physical stock")
                if expected.get("serial_no") and sorted(str(row.get("serial_no") or "").splitlines()) != expected["serial_no"].splitlines():
                    frappe.throw("Controlled logistics serials differ from the selected physical stock")
        return
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", doc.cfg_movement_manifest)
    expected_lines = {line.name: line for line in manifest.lines}
    seen = set()
    for row in doc.items:
        line = expected_lines.get(row.get("cfg_manifest_line"))
        if not line or line.name in seen:
            frappe.throw("ERP logistics document has a duplicate or unrelated Manifest line")
        seen.add(line.name)
        expected = erp_identity_fields(line, row.doctype, transfer=doc.doctype == "Stock Entry")
        if doc.doctype == "Stock Entry" and doc.get("cfg_transfer_stage") == "Receipt":
            outgoing = frappe.db.get_value("Stock Entry Detail",
                {"parent": manifest.dispatch_stock_entry, "cfg_manifest_line": line.name}, "name")
            assert_outward_identity(line, outgoing)
        if doc.doctype == "Purchase Receipt":
            if not line.get("delivery_note_item"):
                frappe.throw("Intercompany receipt has no exact submitted dispatch row")
            outgoing = frappe.get_doc("Delivery Note Item", line.delivery_note_item)
            if (outgoing.get("process_certificate_set") or None) != (expected.get("process_certificate_set") or None):
                frappe.throw("Submitted dispatch lost its certificate dimension. Reconcile it before receiving; do not invent receipt evidence.")
        for field in ("process_certificate_set", "to_process_certificate_set"):
            if field in expected and (row.get(field) or None) != (expected[field] or None):
                frappe.throw("ERP logistics certificate dimensions must match both the source tag and Manifest")
        if (row.get("batch_no") or None) != (line.batch_no or None):
            frappe.throw("ERP logistics Batch differs from the Manifest")
        if expected.get("serial_no") and sorted(str(row.get("serial_no") or "").splitlines()) != expected["serial_no"].splitlines():
            frappe.throw("ERP logistics serials differ from the exact source tag")
    if seen != set(expected_lines):
        frappe.throw("ERP logistics document must retain every Manifest stock identity")


def validate_manifest_identity(line):
    return _line_identity(line)


def assert_outward_identity(line, detail_name):
    if not detail_name:
        frappe.throw("Outward Stock Entry row is missing; reconcile the Manifest before receipt")
    row = frappe.get_doc("Stock Entry Detail", detail_name)
    expected = erp_identity_fields(line, "Stock Entry Detail", transfer=True)
    for field in ("process_certificate_set", "to_process_certificate_set"):
        if field in expected and (row.get(field) or None) != (expected[field] or None):
            frappe.throw("Submitted outward transfer lost certificate dimensions. Use controlled reconciliation before receipt.")


def prepare_controlled_transfer(doc, method=None):
    if doc.doctype != "Stock Entry" or doc.get("purpose") != "Material Transfer" or not doc.get("cfg_kanban_controlled") or doc.get("cfg_movement_manifest"):
        return
    for row in doc.items:
        if row.get("cfg_handling_unit"):
            unit = frappe.get_doc("CFG Kanban Handling Unit", row.cfg_handling_unit)
            line = frappe._dict(handling_unit=unit.name, item_code=unit.item_code,
                batch_no=unit.batch_no, stock_uom=unit.stock_uom,
                process_certificate_set=unit.get("process_certificate_set"),
                expiry_date=_expiry(identity_snapshot(unit)) or None,
                stock_identity_snapshot=_json(identity_snapshot(unit)))
            row.update(erp_identity_fields(line, row.doctype, transfer=True))


def certificate_root(certificate, require_unexpired=True):
    """Follow retained/split provenance so revoking an ancestor invalidates descendants."""
    current = certificate if not isinstance(certificate, str) else frappe.get_doc("CFG Process Certificate", certificate)
    seen = set()
    now = get_datetime(now_datetime())
    while current:
        if current.name in seen or len(seen) >= 64 or current.status != "Active":
            return None
        seen.add(current.name)
        if current.get("valid_from") and get_datetime(current.valid_from) > now:
            return None
        if require_unexpired and current.get("valid_until") and get_datetime(current.valid_until) < now:
            return None
        if current.get("source_reference_doctype") != "CFG Process Certificate":
            return current
        parent = current.get("source_reference_name")
        if not parent or not frappe.db.exists("CFG Process Certificate", parent):
            return None
        ancestor = frappe.get_doc("CFG Process Certificate", parent)
        if ancestor.certificate_type != current.certificate_type:
            return None
        current = ancestor
    return None


def certificate_is_effective(name, require_unexpired=True):
    return bool(certificate_root(name, require_unexpired=require_unexpired))


def _certificate_sources(source):
    if not source.get("process_certificate_set"):
        return []
    certificate_set = frappe.get_doc("CFG Process Certificate Set", source.process_certificate_set)
    result = []
    for member in certificate_set.members:
        rows = frappe.get_all("CFG Process Certificate",
            filters={"handling_unit": source.name, "certificate_type": member.certificate_type,
             "certificate_set": source.process_certificate_set, "status": "Active"},
            pluck="name", order_by="issued_on asc, name asc", limit_page_length=0)
        proofs = []
        for name in rows:
            candidate = frappe.get_doc("CFG Process Certificate", name)
            if certificate_root(candidate, require_unexpired=False):
                proofs.append(candidate)
        if not proofs:
            frappe.throw("Certified quantity has no intact issued evidence; reconcile it before splitting or repacking")
        result.extend(proofs)
    return result


def _available_certificate_qty(proof, lock=True):
    # Issued evidence is immutable. Child allocations consume its coverage even if
    # later revoked: revocation alone cannot authorize allocating the quantity again.
    if lock:
        frappe.db.sql("select name from `tabCFG Process Certificate` where name=%s for update", proof.name)
    suffix = "for update" if lock else ""
    allocated = frappe.db.sql(f"""
        select certified_qty from `tabCFG Process Certificate`
        where source_reference_doctype='CFG Process Certificate' and source_reference_name=%s
        {suffix}
    """, proof.name)
    return max(0, flt(proof.certified_qty) - sum(flt(row[0]) for row in allocated))


def certificate_quantity_coverage(unit, certificate_type, minimum_revision=1, require_unexpired=True):
    names = frappe.get_all("CFG Process Certificate", filters={
        "handling_unit": unit.name, "certificate_set": unit.process_certificate_set,
        "certificate_type": certificate_type, "status": "Active",
        "revision_snapshot": [">=", minimum_revision]}, pluck="name", limit_page_length=0)
    total = 0
    for name in names:
        proof = frappe.get_doc("CFG Process Certificate", name)
        if certificate_is_effective(name, require_unexpired=require_unexpired):
            total += _available_certificate_qty(proof, lock=False)
    return total



def certificate_requirement_covered(unit, certificate_type, minimum_revision=1, require_unexpired=True):
    if flt(unit.current_qty) > 0.000001:
        return certificate_quantity_coverage(unit, certificate_type, minimum_revision,
            require_unexpired=require_unexpired) + 0.000001 >= flt(unit.current_qty)
    # A completed material trace refers to consumed stock. Do not require its
    # old tag to retain a live balance, but still reject revoked/invalid lineage.
    names = frappe.get_all("CFG Process Certificate", filters={
        "handling_unit": unit.name, "certificate_set": unit.process_certificate_set,
        "certificate_type": certificate_type, "status": "Active",
        "revision_snapshot": [">=", minimum_revision]}, pluck="name", limit_page_length=0)
    return any(certificate_is_effective(name, require_unexpired=require_unexpired) for name in names)


def inherit_split_certificates(source, destination, qty, event_key, replacement=False):
    """Allocate bulk coverage across issued records, preserving each original proof."""
    if (source.get("process_certificate_set") or None) != (destination.get("process_certificate_set") or None):
        frappe.throw("A logistics split cannot change the Process Certificate Set")
    qty = flt(qty)
    if qty <= 0:
        frappe.throw("Split certificate quantity must be positive")
    grouped = {}
    for proof in _certificate_sources(source):
        grouped.setdefault(proof.certificate_type, []).append(proof)
    plan = []
    for certificate_type, proofs in grouped.items():
        # Respect records created by the previous single-proof implementation.
        legacy = frappe.db.get_value("CFG Process Certificate", {"idempotency_key": canonical_key(
            "logistics-certificate-inheritance", event_key, destination.name, certificate_type)}, "name")
        keys = [(proof, canonical_key("logistics-certificate-inheritance", event_key,
                                     destination.name, certificate_type, proof.name)) for proof in proofs]
        existing = [name for _proof, key in keys if (name := frappe.db.get_value(
            "CFG Process Certificate", {"idempotency_key": key}, "name"))]
        if legacy:
            existing.append(legacy)
        if existing:
            rows = [frappe.get_doc("CFG Process Certificate", name) for name in set(existing)]
            if (abs(sum(flt(row.certified_qty) for row in rows) - qty) > 0.000001
                    or any(row.handling_unit != destination.name for row in rows)):
                frappe.throw("Split retry differs from its recorded certificate allocation")
            continue
        definition = frappe.get_doc("CFG Process Certificate Type", certificate_type)
        if not replacement and definition.split_inheritance != "Inherit to Child Tags":
            frappe.throw("Certificate policy prohibits split inheritance; keep this certified quantity on its original tag")
        remaining = qty
        for proof, key in keys:
            take = min(remaining, _available_certificate_qty(proof))
            if take > 0.000001:
                plan.append((proof, take, key))
                remaining -= take
            if remaining <= 0.000001:
                break
        if remaining > 0.000001:
            frappe.throw(f"Source certificate does not cover the split quantity for {certificate_type}: "
                         f"requested {qty}; unallocated evidence {qty - remaining} {source.stock_uom}")
    # Validate every required type before creating any inherited certificate.
    for proof, take, key in plan:
        inherited = frappe.copy_doc(proof)
        inherited.name = None
        inherited.handling_unit = destination.name
        inherited.certified_qty = take
        inherited.inventory_company = destination.inventory_company
        inherited.warehouse = destination.current_warehouse
        inherited.batch_no = destination.batch_no
        inherited.source_reference_doctype = "CFG Process Certificate"
        inherited.source_reference_name = proof.name
        inherited.idempotency_key = key
        inherited.insert(ignore_permissions=True)
        for field in ("valid_from", "valid_until", "issued_on", "revision_snapshot",
                      "certificate_code_snapshot", "certificate_name_snapshot", "evidence_references"):
            if str(inherited.get(field) or "") != str(proof.get(field) or ""):
                frappe.throw("Inherited certificate identity changed; logistics cannot renew or revise its evidence")


def assert_merge_compatible(source, destination):
    for field in ("process_certificate_set", "expiry_date"):
        if str(source.get(field) or "") != str(destination.get(field) or ""):
            frappe.throw("Do not merge stock with different Process Certificate Sets or expiry dates")
    def signature(unit):
        result = set()
        for proof in _certificate_sources(unit):
            definition = frappe.get_doc("CFG Process Certificate Type", proof.certificate_type)
            if definition.merge_policy == "Block Merge":
                frappe.throw("Certificate policy blocks this merge; retain separate stock identities")
            root = certificate_root(proof, require_unexpired=False)
            result.add((proof.certificate_type, root.name, str(proof.valid_from or ""), str(proof.valid_until or "")))
        return sorted(result)
    if not set(signature(source)).issubset(signature(destination)):
        frappe.throw("Certified tags have different evidence provenance; retain separate tags or fills instead of merging their certificates")

