import frappe


def execute():
    """Legacy customer allocations all carried a physical Stock Tag."""
    frappe.db.sql("""
        update `tabCFG Kanban Delivery Allocation`
        set allocation_kind='Tagged Stock'
        where ifnull(allocation_kind, '')=''
    """)
