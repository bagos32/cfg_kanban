import frappe


def execute():
    """Preserve former flexible behavior without rewriting historical Profile snapshots."""
    for doctype in ("CFG Kanban Dispatch Profile", "CFG Kanban Dispatch Plan"):
        frappe.db.sql(f"""
            update `tab{doctype}` set stop_sequence_policy='Flexible Order'
            where ifnull(stop_sequence_policy, '')=''
        """)
