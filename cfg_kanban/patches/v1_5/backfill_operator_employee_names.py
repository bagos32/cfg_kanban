import frappe


def execute():
    doctype = "CFG Kanban Operator Profile"
    if not frappe.db.table_exists(doctype) or not frappe.db.has_column(doctype, "employee_name"):
        return

    frappe.db.sql(
        """
        update `tabCFG Kanban Operator Profile` profile
        left join `tabEmployee` employee on employee.name = profile.employee
        set profile.employee_name = employee.employee_name
        where ifnull(profile.employee_name, '') != ifnull(employee.employee_name, '')
        """
    )
