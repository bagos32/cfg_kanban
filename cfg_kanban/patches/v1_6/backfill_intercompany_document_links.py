import frappe


def execute():
    """Restore ERPNext-native links on existing Kanban intercompany receipts."""
    if not (
        frappe.db.table_exists("CFG Kanban Movement Manifest")
        and frappe.db.table_exists("Purchase Receipt")
        and frappe.db.table_exists("Delivery Note")
    ):
        return

    manifests = frappe.get_all(
        "CFG Kanban Movement Manifest",
        filters={
            "manifest_type": "Intercompany Handover",
            "dispatch_delivery_note": ["is", "set"],
            "receipt_purchase_receipt": ["is", "set"],
        },
        fields=[
            "name", "source_company", "destination_company",
            "dispatch_delivery_note", "receipt_purchase_receipt",
        ],
    )
    for manifest in manifests:
        if not _documents_are_live(manifest):
            continue
        _backfill_parent_links(manifest)
        _backfill_item_links(manifest)


def _documents_are_live(manifest):
    return (
        frappe.db.get_value("Delivery Note", manifest.dispatch_delivery_note, "docstatus") != 2
        and frappe.db.get_value(
            "Purchase Receipt", manifest.receipt_purchase_receipt, "docstatus"
        ) != 2
    )


def _backfill_parent_links(manifest):
    frappe.db.set_value(
        "Delivery Note", manifest.dispatch_delivery_note,
        "cfg_counterpart_document", manifest.receipt_purchase_receipt,
        update_modified=False,
    )
    frappe.db.set_value(
        "Purchase Receipt", manifest.receipt_purchase_receipt,
        {
            "inter_company_reference": manifest.dispatch_delivery_note,
            "cfg_counterpart_document": manifest.dispatch_delivery_note,
        },
        update_modified=False,
    )


def _backfill_item_links(manifest):
    lines = frappe.get_all(
        "CFG Kanban Manifest Line",
        filters={"parent": manifest.name, "parenttype": "CFG Kanban Movement Manifest"},
        fields=["delivery_note_item", "purchase_receipt_item"],
    )
    for line in lines:
        if not line.delivery_note_item or not line.purchase_receipt_item:
            continue
        if frappe.db.get_value(
            "Delivery Note Item", line.delivery_note_item, "parent"
        ) != manifest.dispatch_delivery_note:
            continue
        if frappe.db.get_value(
            "Purchase Receipt Item", line.purchase_receipt_item, "parent"
        ) != manifest.receipt_purchase_receipt:
            continue
        frappe.db.set_value(
            "Purchase Receipt Item", line.purchase_receipt_item,
            "delivery_note_item", line.delivery_note_item,
            update_modified=False,
        )
