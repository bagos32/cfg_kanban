"""Read captured printing metadata from posted certificate provenance.

Printed expiry is distinct from certificate validity. Operational serial boundaries
are source evidence, never invented ERPNext Serial Number membership for child tags.
"""
import frappe


def certificate_output_evidence(handling_unit, certificate_set, item_code, stock_uom):
    if not certificate_set or not frappe.db.table_exists("CFG Process Certificate Run"):
        return []
    proofs = frappe.get_all("CFG Process Certificate", filters={
        "handling_unit": handling_unit, "certificate_set": certificate_set},
        fields=["name", "handling_unit", "certificate_type", "certificate_set", "item_code", "stock_uom",
                "kanban_cycle", "status", "source_reference_doctype", "source_reference_name"],
        order_by="name asc", limit_page_length=0)
    documents, runs_by_posting, posted_entries, result = {}, {}, {}, {}
    for proof in proofs:
        lineage = []
        root = _certificate_origin(proof, item_code, stock_uom, documents, lineage)
        if not root or root.source_reference_doctype != "Stock Entry" or not root.source_reference_name:
            continue
        posting = root.source_reference_name
        if posting not in posted_entries:
            posted_entries[posting] = frappe.db.get_value("Stock Entry", posting,
                ["docstatus", "purpose"], as_dict=True)
        native = posted_entries[posting]
        if not native or native.docstatus != 1 or native.purpose != "Repack":
            continue
        if posting not in runs_by_posting:
            runs_by_posting[posting] = frappe.get_all("CFG Process Certificate Run", filters={
                "repack_stock_entry": posting, "status": "Completed"},
                fields=["name", "kanban_cycle", "item_code", "stock_uom", "output_handling_unit",
                    "result_certificate_set", "printed_expiry", "first_output_serial", "last_output_serial"],
                order_by="name asc", limit_page_length=0)
        for run in runs_by_posting[posting]:
            if (run.item_code != item_code or run.stock_uom != stock_uom
                    or run.output_handling_unit != root.handling_unit
                    or run.kanban_cycle != root.kanban_cycle or run.result_certificate_set != root.certificate_set):
                continue
            if run.name in result:
                known = {row["name"]:row for row in result[run.name]["certificate_provenance"]}
                known.update({row["name"]:row for row in lineage})
                result[run.name]["certificate_provenance"] = [known[name] for name in sorted(known)]
                continue
            progress = frappe.get_all("CFG Certificate Process Progress", filters={
                "certificate_process_run":run.name,"status":"ERP Posted"},
                fields=["name","sequence","printed_expiry","first_output_serial","last_output_serial"],
                order_by="sequence asc, name asc", limit_page_length=0
            ) if frappe.db.table_exists("CFG Certificate Process Progress") else []
            if not any(run.get(field) for field in ("printed_expiry","first_output_serial","last_output_serial")) and not progress:
                continue
            result[run.name] = {
                "certificate_process_run":run.name, "repack_stock_entry":posting,
                "source_handling_unit":root.handling_unit,
                "certificate_provenance":sorted(lineage,key=lambda row:row["name"]),
                "printed_expiry":str(run.printed_expiry)[:10] if run.printed_expiry else None,
                "first_output_serial":run.first_output_serial or None,
                "last_output_serial":run.last_output_serial or None,
                "progress":[{
                    "name":row.name,"sequence":row.sequence,
                    "printed_expiry":str(row.printed_expiry)[:10] if row.printed_expiry else None,
                    "first_output_serial":row.first_output_serial or None,
                    "last_output_serial":row.last_output_serial or None,
                } for row in progress],
            }
    return [result[name] for name in sorted(result)]


def _certificate_origin(proof, item_code, stock_uom, documents, lineage=None):
    seen = set()
    current = proof
    while current:
        if (current.name in seen or len(seen) >= 64 or current.status not in ("Active","Expired","Revoked","Superseded")
                or current.item_code != item_code or current.stock_uom != stock_uom):
            return None
        seen.add(current.name)
        if lineage is not None:
            lineage.append({"name":current.name,"status":current.status})
        if current.source_reference_doctype != "CFG Process Certificate":
            return current
        name = current.source_reference_name
        if not name or not frappe.db.exists("CFG Process Certificate",name):
            return None
        if name not in documents:
            documents[name] = frappe.get_doc("CFG Process Certificate",name)
        parent = documents[name]
        if parent.certificate_type != current.certificate_type:
            return None
        current = parent
    return None


def printed_expiry_dates(evidence):
    return [row["printed_expiry"] for run in evidence for row in [run, *run.get("progress", [])]
            if row.get("printed_expiry")]
