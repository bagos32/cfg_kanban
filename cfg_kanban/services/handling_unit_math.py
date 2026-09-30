from decimal import Decimal


ZERO = Decimal("0")


def as_decimal(value):
    return Decimal(str(value or 0))


def validate_balance(current_qty, reserved_qty):
    current = as_decimal(current_qty)
    reserved = as_decimal(reserved_qty)
    if current < ZERO:
        raise ValueError("Handling-unit current quantity cannot be negative")
    if reserved < ZERO:
        raise ValueError("Handling-unit reserved quantity cannot be negative")
    if reserved > current:
        raise ValueError("Handling-unit reserved quantity cannot exceed current quantity")
    return current, reserved, current - reserved


def apply_balance_delta(current_qty, reserved_qty, *, qty_delta=0, reserved_delta=0):
    return validate_balance(
        as_decimal(current_qty) + as_decimal(qty_delta),
        as_decimal(reserved_qty) + as_decimal(reserved_delta),
    )


def event_deltas(event_type, stock_qty, *, release_reserved=False):
    qty = as_decimal(stock_qty)
    if qty <= ZERO:
        raise ValueError("Ledger quantity must be positive")

    deltas = {
        "source_qty_delta": ZERO,
        "destination_qty_delta": ZERO,
        "source_reserved_delta": ZERO,
        "destination_reserved_delta": ZERO,
    }
    if event_type in {"Opening Balance", "Pack / Activate", "Refill", "Reconcile Increase",
                      "Customer Return"}:
        deltas["destination_qty_delta"] = qty
    elif event_type in {"Split", "Replace", "Load into Container", "Unload from Container"}:
        deltas["source_qty_delta"] = -qty
        deltas["destination_qty_delta"] = qty
    elif event_type == "Reserve":
        deltas["source_reserved_delta"] = qty
    elif event_type == "Unreserve":
        deltas["source_reserved_delta"] = -qty
    elif event_type == "Deliver":
        deltas["source_qty_delta"] = -qty
        if release_reserved:
            deltas["source_reserved_delta"] = -qty
    elif event_type in {"Damage", "Reconcile Decrease", "Empty"}:
        deltas["source_qty_delta"] = -qty
    elif event_type not in {"Location Transfer", "Return to Warehouse", "Quarantine", "Release"}:
        raise ValueError(f"Unsupported handling-unit ledger event: {event_type}")
    return deltas
