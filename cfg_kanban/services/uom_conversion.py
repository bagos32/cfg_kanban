import frappe
from frappe.utils import flt

from cfg_kanban.services.purchase_uom import calculate_purchase_quantities


def get_item_purchase_uom(item_code, purchase_uom=None):
    item = frappe.db.get_value(
        "Item", item_code, ["stock_uom", "purchase_uom"], as_dict=True
    )
    if not item:
        frappe.throw(f"Item {item_code} does not exist")

    stock_uom = item.stock_uom
    purchase_uom = purchase_uom or item.purchase_uom or stock_uom
    if purchase_uom == stock_uom:
        conversion_factor = 1
    else:
        conversion_factor = flt(frappe.db.get_value(
            "UOM Conversion Detail",
            {"parent": item_code, "parenttype": "Item", "uom": purchase_uom},
            "conversion_factor",
        ))
        if conversion_factor <= 0:
            frappe.throw(
                f"Configure UOM {purchase_uom} with a positive conversion factor on Item "
                f"{item_code}. Stock UOM is {stock_uom}."
            )

    return {
        "stock_uom": stock_uom,
        "purchase_uom": purchase_uom,
        "conversion_factor": conversion_factor,
    }


@frappe.whitelist()
def get_purchase_uom_preview(item_code, purchase_uom=None, stock_qty=0,
                             minimum_purchase_qty=0, purchase_multiple=0,
                             supplier_pack_multiple=0):
    uom = get_item_purchase_uom(item_code, purchase_uom)
    return {
        **uom,
        **calculate_purchase_quantities(
            flt(stock_qty),
            uom["conversion_factor"],
            flt(minimum_purchase_qty),
            flt(purchase_multiple),
            flt(supplier_pack_multiple),
        ),
    }
