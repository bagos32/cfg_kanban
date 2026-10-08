import frappe
from frappe import _

from cfg_kanban.services.operator_auth import require_operator


STOCK_RETAGGING_RESPONSIBILITY = "Stock Retagging"
ERP_ROLES = (
    "Stock User", "Stock Manager", "Manufacturing User", "Manufacturing Manager",
    "System Manager",
)


def can_stock_retag(profile):
    responsibilities = {
        row.responsibility for row in profile.responsibilities if row.responsibility
    }
    can_view_all = bool(
        profile.get("view_all_responsibilities")
        and profile.kanban_role in ("Supervisor", "Development Proxy")
    )
    return bool(can_view_all or STOCK_RETAGGING_RESPONSIBILITY in responsibilities)


def authorize_stock_retagging(operator_session_token=None, action=None):
    if not operator_session_token:
        frappe.only_for(ERP_ROLES)
        return None, None
    profile, session = require_operator(operator_session_token, action)
    if not can_stock_retag(profile):
        frappe.throw(
            _("Operator is not assigned to the Stock Retagging responsibility")
        )
    return profile, session
