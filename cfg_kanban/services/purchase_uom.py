from decimal import Decimal, InvalidOperation, ROUND_CEILING


def _decimal(value):
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def calculate_purchase_quantities(stock_qty, conversion_factor=1, minimum_purchase_qty=0,
                                  purchase_multiple=0, supplier_pack_multiple=0):
    """Return one purchase-UOM quantity and its Stock-UOM equivalent.

    ``conversion_factor`` follows ERPNext: Stock Qty = Purchase Qty × Conversion Factor.
    Minimum, order multiple, and supplier pack multiple are expressed in Purchase UOM.
    """
    stock_qty = _decimal(stock_qty)
    conversion_factor = _decimal(conversion_factor)
    if conversion_factor <= 0:
        raise ValueError("UOM conversion factor must be greater than zero")

    purchase_qty = max(stock_qty / conversion_factor, _decimal(minimum_purchase_qty))
    multiple = _decimal(purchase_multiple) or _decimal(supplier_pack_multiple)
    if multiple > 0:
        purchase_qty = (purchase_qty / multiple).to_integral_value(
            rounding=ROUND_CEILING
        ) * multiple

    return {
        "purchase_qty": float(purchase_qty),
        "stock_qty": float(purchase_qty * conversion_factor),
        "conversion_factor": float(conversion_factor),
    }
