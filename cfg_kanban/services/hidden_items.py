"""Optional compatibility with the legacy Hidden Item Settings customization.

This module deliberately uses DocType metadata and database rows only. CFG Kanban must remain
installable when bagos_changes (and therefore Hidden Item Settings) is absent.
"""

import frappe


SETTINGS_DOCTYPE = "Hidden Item Settings"
ITEM_CHILD_DOCTYPE = "Secret Items"
USER_CHILD_DOCTYPE = "Secret Item User"


def get_hidden_item_policy(user=None):
    user = user or frappe.session.user
    if not _integration_available():
        return {
            "enabled": False,
            "can_view": True,
            "items": set(),
        }
    items = set(frappe.get_all(
        ITEM_CHILD_DOCTYPE,
        filters={"parent": SETTINGS_DOCTYPE, "parenttype": SETTINGS_DOCTYPE},
        pluck="item",
    ))
    allowed_users = set(frappe.get_all(
        USER_CHILD_DOCTYPE,
        filters={"parent": SETTINGS_DOCTYPE, "parenttype": SETTINGS_DOCTYPE},
        pluck="user",
    ))
    return {
        "enabled": True,
        "can_view": user == "Administrator" or user in allowed_users,
        "items": items,
    }


def hidden_item_codes(user=None):
    policy = get_hidden_item_policy(user)
    return set() if policy["can_view"] else policy["items"]


def _integration_available():
    return all(frappe.db.exists("DocType", doctype) for doctype in (
        SETTINGS_DOCTYPE, ITEM_CHILD_DOCTYPE, USER_CHILD_DOCTYPE,
    ))
