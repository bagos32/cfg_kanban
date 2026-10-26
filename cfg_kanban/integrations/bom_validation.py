"""Early BOM guardrails for deterministic Job Card material ownership."""

import frappe
from frappe import _
from frappe.utils import cint, cstr


def validate_job_card_item_operations(doc, method=None):
    """Require every raw-material row to belong to one BOM operation.

    ERPNext copies ``BOM Item.operation`` into Work Order and Job Card material rows. Without that
    mapping, a Work Order configured to transfer material against Job Cards cannot determine which
    Job Card owns the component. CFG Kanban already rejects that ambiguity later; this hook prevents
    the invalid BOM from being saved or submitted in the first place.
    """
    if cstr(doc.get("transfer_material_against")).strip() != "Job Card":
        return

    if not cint(doc.get("with_operations")):
        frappe.throw(
            _("Enable With Operations before selecting Job Card material transfer."),
            title=_("BOM Operations Required"),
        )

    route_operations = {
        cstr(row.get("operation")).strip()
        for row in (doc.get("operations") or [])
        if cstr(row.get("operation")).strip()
    }
    missing_rows = []
    outside_route_rows = []
    for position, row in enumerate(doc.get("items") or [], start=1):
        row_number = cint(row.get("idx")) or position
        item_code = cstr(row.get("item_code")).strip() or _("Unspecified Item")
        operation = cstr(row.get("operation")).strip()
        if not operation:
            missing_rows.append(_("Row #{0}: {1}").format(row_number, item_code))
        elif operation not in route_operations:
            outside_route_rows.append(
                _("Row #{0}: {1} → {2}").format(row_number, item_code, operation)
            )

    if missing_rows:
        frappe.throw(
            _(
                "Transfer Material Against is Job Card. Set Item Operation on every "
                "raw-material row:<br>{0}"
            ).format("<br>".join(missing_rows)),
            title=_("Item Operation Required"),
        )

    if outside_route_rows:
        frappe.throw(
            _(
                "Each Item Operation must also exist in this BOM's Operations table:<br>{0}"
            ).format("<br>".join(outside_route_rows)),
            title=_("Invalid Item Operation"),
        )
