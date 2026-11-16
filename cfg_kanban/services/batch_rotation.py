"""Set-aside Batch selection policy; explicit valid scans remain permitted."""
import frappe
from frappe.utils import cint
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key


def _installed():
    return frappe.get_meta('Batch').has_field('cfg_rotation_excluded')


def batch_rotation_exclusion(batch_no, current=False):
    if not batch_no or not _installed():
        return None
    rows = frappe.db.sql('''select name, item, cfg_rotation_excluded, cfg_rotation_reason, modified
        from `tabBatch` where name=%s''' + (' for update' if current else ''),batch_no,as_dict=True)
    if not rows or not cint(rows[0].cfg_rotation_excluded):
        return None
    row=rows[0]
    if not str(row.cfg_rotation_reason or '').strip():
        frappe.throw('The isolated Batch requires an isolation reason')
    return {'batch':row.name,'item_code':row.item,'reason':row.cfg_rotation_reason,'modified':str(row.modified or '')}


def automatic_batch_condition(alias):
    if alias != 'unit':
        frappe.throw('Unsupported automatic Batch selection alias')
    if not _installed():
        return ''
    return "and not exists (select 1 from `tabBatch` isolated_batch where isolated_batch.name=unit.batch_no and ifnull(isolated_batch.cfg_rotation_excluded,0)=1)"


def _changed(doc):
    before=doc.get_doc_before_save() if not doc.is_new() else None
    old_flag=cint(before.get('cfg_rotation_excluded')) if before else 0
    old_reason=(before.get('cfg_rotation_reason') or '') if before else ''
    new_flag=cint(doc.get('cfg_rotation_excluded'))
    reason=str(doc.get('cfg_rotation_reason') or '').strip()
    return before,old_flag,old_reason,new_flag,reason,(old_flag!=new_flag or old_reason!=reason)


def validate_batch_exclusion(doc, method=None):
    before,old_flag,old_reason,new_flag,reason,changed=_changed(doc)
    if not changed:return
    if not set(frappe.get_roles()) & {'Stock Manager','Manufacturing Manager','System Manager'}:
        frappe.throw('A Stock, Manufacturing or System Manager must change Batch selection isolation',frappe.PermissionError)
    if (new_flag or old_flag) and not reason:
        frappe.throw('Enter an isolation or release reason')
    if old_flag and not new_flag and reason==old_reason:
        frappe.throw('Enter a new release reason when returning this Batch to automatic selection')
    doc.cfg_rotation_reason=reason


def audit_batch_exclusion(doc, method=None):
    before,old_flag,old_reason,new_flag,reason,changed=_changed(doc)
    if not changed:return
    record('Batch Selection Isolation Changed',reference_doctype='Batch',reference_name=doc.name,
        material_item=doc.item,material_batch=doc.name,terminal_user=frappe.session.user,notes=reason,
        payload={'isolated_before':old_flag,'isolated_after':new_flag,'previous_reason':old_reason,'reason':reason},
        idempotency_key=canonical_key('batch-selection-isolation',doc.name,str(doc.modified),new_flag,reason))
