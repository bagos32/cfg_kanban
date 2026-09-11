import html

import frappe
from frappe.utils import now_datetime

from cfg_kanban.services.events import record


@frappe.whitelist()
def record_print(doctype, name, print_format, reason=None):
    if doctype not in ("CFG Kanban Card", "CFG Kanban Handling Unit"):
        frappe.throw("Unsupported Kanban print document")
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("print")
    count = (doc.print_count or 0) + 1
    values = {"print_count": count}
    if doctype == "CFG Kanban Handling Unit":
        values.update({"last_printed_on": now_datetime(), "last_printed_by": frappe.session.user})
    doc.db_set(values, update_modified=True)
    record("Card Printed" if doctype == "CFG Kanban Card" else "Handling Unit Tag Printed",
           card=doc.name if doctype == "CFG Kanban Card" else doc.kanban_card,
           cycle=getattr(doc, "kanban_cycle", None), reference_doctype=doctype,
           reference_name=doc.name, notes=f"Format: {print_format}; Print #{count}; {reason or ''}",
           system_generated=False)
    return {"print_count": count}


@frappe.whitelist()
def replace_card(card_name, new_card_number, reason):
    frappe.only_for(("Manufacturing Manager", "System Manager"))
    old = frappe.get_doc("CFG Kanban Card", card_name)
    if not reason:
        frappe.throw("Replacement reason is required")
    new = frappe.copy_doc(old)
    new.name = None
    new.card_number = new_card_number
    new.uuid = None
    new.qr_code = None
    new.revision = (old.revision or 0) + 1
    new.print_count = 0
    new.replacement_of = old.name
    new.active_cycle = old.active_cycle
    new.last_event = None
    new.current_state = old.current_state
    new.blocked = 0
    new.blocked_reason = None
    new.insert()
    if old.active_cycle:
        frappe.db.set_value("CFG Kanban Cycle", old.active_cycle, "kanban_card", new.name)
    old.db_set({"active": 0, "current_state": "Inactive", "blocked": 1,
                "blocked_reason": f"Replaced by {new.name}: {reason}"})
    record("Card Replaced", card=old.name, previous_state=old.current_state,
           new_state="Inactive", reference_doctype=new.doctype, reference_name=new.name,
           notes=reason, system_generated=False)
    return {"old_card": old.name, "new_card": new.name}


@frappe.whitelist()
def replace_handling_unit(unit_name, new_handling_unit_id, reason):
    frappe.only_for(("Manufacturing Manager", "System Manager"))
    old = frappe.get_doc("CFG Kanban Handling Unit", unit_name)
    if old.state in ("Received", "Void", "Replaced"):
        frappe.throw(f"A {old.state.lower()} tag cannot be replaced")
    if not reason:
        frappe.throw("Replacement reason is required")
    new = frappe.copy_doc(old)
    new.name = None
    new.handling_unit_id = new_handling_unit_id
    new.opaque_token = None
    new.state = "Issued"
    new.print_revision = (old.print_revision or 0) + 1
    new.print_count = 0
    new.last_printed_on = None
    new.last_printed_by = None
    new.last_scan_time = None
    new.replacement_of = old.name
    new.replaced_by = None
    new.void_reason = None
    new.insert()
    old.db_set({"state": "Replaced", "replaced_by": new.name, "void_reason": reason})
    record("Handling Unit Replaced", card=old.kanban_card, cycle=old.kanban_cycle,
           previous_state=old.state, new_state="Replaced", reference_doctype=new.doctype,
           reference_name=new.name, notes=reason, system_generated=False)
    return {"old_unit": old.name, "new_unit": new.name}


def get_card_route(master_name):
    master = frappe.get_doc("CFG Kanban Master", master_name)
    return [{"sequence": row.sequence, "operation": row.operation,
             "workstation": row.workstation, "handoff_mode": row.handoff_mode,
             "destination_operation": row.destination_operation}
            for row in sorted(master.operation_profiles, key=lambda row: row.sequence)]


def get_card_print_context(master_name):
    master = frappe.get_doc("CFG Kanban Master", master_name)
    return {"name": master.name, "item_code": master.item_code,
            "source_warehouse": master.source_warehouse,
            "destination_warehouse": master.destination_warehouse,
            "replenishment_qty": master.replenishment_qty,
            "stock_uom": master.stock_uom, "revision": master.revision,
            "route": get_card_route(master.name)}


def get_qr_svg(value, size=124):
    """Render QR as a data URI using Frappe v15's installed PyQRCode dependency."""
    import base64
    import io
    from pyqrcode import create as qrcreate

    output = io.BytesIO()
    qrcreate(str(value)).svg(output, scale=5, quiet_zone=1)
    return f"data:image/svg+xml;base64,{base64.b64encode(output.getvalue()).decode()}"


# Code 128 patterns indexed by symbol value, 0-106. Values encode bar/space widths.
_CODE128 = (
    "212222","222122","222221","121223","121322","131222","122213","122312","132212","221213",
    "221312","231212","112232","122132","122231","113222","123122","123221","223211","221132",
    "221231","213212","223112","312131","311222","321122","321221","312212","322112","322211",
    "212123","212321","232121","111323","131123","131321","112313","132113","132311","211313",
    "231113","231311","112133","112331","132131","113123","113321","133121","313121","211331",
    "231131","213113","213311","213131","311123","311321","331121","312113","312311","332111",
    "314111","221411","431111","111224","111422","121124","121421","141122","141221","112214",
    "112412","122114","122411","142112","142211","241211","221114","413111","241112","134111",
    "111242","121142","121241","114212","124112","124211","411212","421112","421211","212141",
    "214121","412121","111143","111341","131141","114113","114311","411113","411311","113141",
    "114131","311141","411131","211412","211214","211232","2331112",
)


def get_code128_svg(value, height=38):
    text = str(value)
    if not text or any(ord(char) < 32 or ord(char) > 126 for char in text):
        frappe.throw("Code 128 value must contain printable ASCII characters")
    codes = [104] + [ord(char) - 32 for char in text]
    checksum = (codes[0] + sum(code * index for index, code in enumerate(codes[1:], 1))) % 103
    codes.extend([checksum, 106])
    quiet, module, x = 10, 1, 10
    bars = []
    for code in codes:
        for index, width in enumerate(_CODE128[code]):
            width = int(width) * module
            if index % 2 == 0:
                bars.append(f'<rect x="{x}" y="0" width="{width}" height="{height}"/>')
            x += width
    width = x + quiet
    label = html.escape(text)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height + 13}" '
            f'preserveAspectRatio="none"><g fill="#000">{"".join(bars)}</g>'
            f'<text x="{width / 2}" y="{height + 11}" text-anchor="middle" '
            f'font-family="monospace" font-size="10">{label}</text></svg>')
