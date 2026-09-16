import frappe


def execute():
    frappe.db.sql("""
        update `tabCFG Kanban Task`
           set verification_status = case
               when ifnull(verification_required, 0) = 0 then 'Not Required'
               when status = 'Completed' and verified_on is not null then 'Approved'
               when status = 'Awaiting Verification' then 'Pending'
               else 'Pending'
           end
         where ifnull(verification_status, '') = ''
    """)
