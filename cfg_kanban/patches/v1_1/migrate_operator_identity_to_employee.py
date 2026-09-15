import frappe


def execute():
    """Map legacy User-valued operator columns to Employee and preserve the terminal User."""
    for table in ("CFG Kanban Operation Progress", "CFG Kanban Process Execution"):
        if not frappe.db.table_exists(table) or not frappe.db.has_column(table, "operator"):
            continue
        if table == "CFG Kanban Operation Progress" and frappe.db.has_column(table, "terminal_user"):
            frappe.db.sql("""
                update `tabCFG Kanban Operation Progress`
                set terminal_user=operator
                where ifnull(terminal_user, '')='' and ifnull(operator, '')!=''
            """)
        frappe.db.sql(f"""
            update `tab{table}` target
            left join `tabEmployee` employee on employee.user_id=target.operator
            set target.operator=employee.name
            where ifnull(target.operator, '')!=''
        """)
