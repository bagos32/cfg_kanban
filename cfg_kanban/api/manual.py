from pathlib import Path

import frappe
from frappe.utils import md_to_html


@frappe.whitelist()
def get_user_manual():
    """Render the repository manual for authenticated manufacturing users."""
    frappe.only_for(("Manufacturing User", "Manufacturing Manager", "System Manager"))
    manual_path = Path(frappe.get_app_path("cfg_kanban")).parent / "docs" / "USER_MANUAL.md"
    if not manual_path.is_file():
        frappe.throw("CFG Kanban User Manual is not available in this deployment")
    source = manual_path.read_text(encoding="utf-8")
    return {"html": md_to_html(source), "source": "docs/USER_MANUAL.md"}
