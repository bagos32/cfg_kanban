import math


def calculate_recommendation(target_stock, projected_available, open_supply,
                             kanban_qty, minimum_shortage=0, maximum_cards=0):
    """Return the card-rounded supply needed to restore the inventory target.

    ERPNext projected quantity already reflects submitted sales demand.  Therefore
    the Sales Order outstanding quantity must not be added again here.
    """
    shortage = max(0, target_stock - projected_available - open_supply)
    count = math.ceil(shortage / kanban_qty) if shortage >= minimum_shortage and shortage > 0 and kanban_qty > 0 else 0
    capped = bool(maximum_cards and count > maximum_cards)
    if capped:
        count = maximum_cards
    return shortage, count, count * kanban_qty, capped


def calculate_mto_plan(outstanding_qty, master_tolerance_pct, po_allows_extra,
                       po_tolerance_pct, plan_to_maximum=True):
    """Return effective tolerance, base quantity and authorized maximum.

    Extra production is authorized only when the customer PO explicitly permits it.
    The lower of the Master and PO percentages always governs.
    """
    outstanding = max(0, float(outstanding_qty or 0))
    master_pct = max(0, float(master_tolerance_pct or 0))
    po_pct = max(0, float(po_tolerance_pct or 0)) if po_allows_extra else 0
    effective_pct = min(master_pct, po_pct) if po_allows_extra else 0
    maximum = outstanding * (1 + effective_pct / 100)
    planned = maximum if plan_to_maximum else outstanding
    return effective_pct, outstanding, maximum, planned
