def calculate_receipt_result(ordered, delivered, accepted, rejected_open,
                             concession=0, short_closed=0,
                             pending_disposition=False):
    values = [float(value or 0) for value in (
        ordered, delivered, accepted, rejected_open, concession, short_closed
    )]
    ordered, delivered, accepted, rejected_open, concession, short_closed = values
    usable = max(accepted, 0) + max(concession, 0)
    outstanding = max(ordered - usable - max(short_closed, 0), 0)
    unresolved = rejected_open > 0.000001 or bool(pending_disposition)
    complete = (outstanding <= 0.000001 and
                (not unresolved or short_closed > 0.000001))
    if complete:
        status = "Completed"
        purchase_status = "Received"
    elif unresolved:
        status = purchase_status = "Receipt Exception"
    elif usable > 0:
        status = purchase_status = "Partially Received"
    else:
        status = purchase_status = "Ordered"
    return {
        "delivered": max(delivered, 0),
        "usable": usable,
        "outstanding": outstanding,
        "unresolved": unresolved,
        "complete": complete,
        "status": status,
        "purchase_status": purchase_status,
    }
