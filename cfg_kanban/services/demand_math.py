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
