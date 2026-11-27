"""Restore the native representation of an unused optional unique movement Link.

Only blank references become NULL. No named evidence, closing state, audit
timestamps, Plan, ERP document or stock quantity is changed. The unique index
continues to prevent the same actual Stock Entry from settling two Reviews.
"""
import frappe


def execute():
    doctype = 'CFG Kanban Dispatch Review'
    if not frappe.db.table_exists(doctype):
        return {'normalized_empty_references': 0}
    rows = frappe.db.sql("""
        select name from `tabCFG Kanban Dispatch Review`
        where movement_stock_entry is not null and trim(movement_stock_entry)=''
    """)
    if rows:
        frappe.db.sql("""
            update `tabCFG Kanban Dispatch Review`
            set movement_stock_entry=NULL
            where movement_stock_entry is not null and trim(movement_stock_entry)=''
        """)
        for row in rows:
            frappe.clear_document_cache(doctype, row[0])
    return {'normalized_empty_references': len(rows)}
