import frappe


def execute():
    frappe.db.sql("""update `tabCFG Kanban Dispatch Profile` set pickup_acknowledgement='Recipient Name'
        where ifnull(pickup_acknowledgement,'')=''""")
    frappe.db.sql("""update `tabCFG Kanban Delivery Session` set fulfilment_mode='Vehicle Delivery'
        where ifnull(fulfilment_mode,'')=''""")
    # Former E2 warehouse Plans waited for a vehicle that their mode cannot claim.
    # Preserve their snapshot JSON and reservations; only correct the readiness label.
    frappe.db.sql("""update `tabCFG Kanban Dispatch Plan` set state='Ready for Fulfilment'
        where state='Ready for Vehicle' and plan_type='Customer Order'
          and fulfilment_mode in ('Direct Warehouse Delivery','Customer Pickup')
          and ifnull(movement_manifest,'')='' and ifnull(delivery_session,'')=''
          and ifnull(vehicle_warehouse,'')=''""")
