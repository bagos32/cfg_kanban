"""Batch, stock-tag and physical-bin selection isolation; explicit valid scans remain permitted."""
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


TAG_FLAG = 'rotation_excluded'
TAG_REASON = 'rotation_isolation_reason'


def _tag_installed():
    return frappe.get_meta('CFG Kanban Handling Unit').has_field(TAG_FLAG)


def tag_rotation_exclusions(names, current=False):
    """Current tag rule OR its actively loaded bin rule. Never follow an old bin pointer."""
    names=sorted(set(filter(None,names)))
    if not names or not _tag_installed():
        return {}
    placeholders=','.join(['%s']*len(names));lock=' for update' if current else ''
    rows=frappe.db.sql('select name, handling_unit_id, item_code, tag_kind, rotation_excluded, rotation_isolation_reason, modified '
        'from `tabCFG Kanban Handling Unit` where name in ('+placeholders+') order by name'+lock,tuple(names),as_dict=True)
    memberships=frappe.db.sql("select content_handling_unit, container_handling_unit from `tabCFG Kanban Container Content` "
        "where content_handling_unit in ("+placeholders+") and state='Loaded' order by name"+lock,tuple(names),as_dict=True)
    containers=sorted({row.container_handling_unit for row in memberships})
    bin_rows=frappe.db.sql('select name, handling_unit_id, rotation_excluded, rotation_isolation_reason, modified '
        'from `tabCFG Kanban Handling Unit` where name in ('+','.join(['%s']*len(containers))+') order by name'+lock,
        tuple(containers),as_dict=True) if containers else []
    def evidence(row,kind):
        if not cint(row.rotation_excluded):return None
        if not str(row.rotation_isolation_reason or '').strip():
            frappe.throw('The isolated tag/bin requires an isolation reason')
        return {'scope':kind,'handling_unit':row.name,'visible_code':row.handling_unit_id,
                'reason':row.rotation_isolation_reason,'modified':str(row.modified or '')}
    bins={row.name:evidence(row,'Bin') for row in bin_rows}
    result={}
    for row in rows:
        rules=[];own=evidence(row,'Bin' if row.tag_kind=='Reusable Container' else 'Tag')
        if own:rules.append(own)
        rules.extend(bins[member.container_handling_unit] for member in memberships
                     if member.content_handling_unit==row.name and bins.get(member.container_handling_unit))
        if rules:result[row.name]={'tag':row.name,'rules':rules}
    return result


def automatic_tag_condition(alias):
    if alias!='unit':frappe.throw('Unsupported automatic tag selection alias')
    if not _tag_installed():return ''
    return """and ifnull(unit.rotation_excluded,0)=0
        and not exists (
            select 1 from `tabCFG Kanban Container Content` isolated_membership
            join `tabCFG Kanban Handling Unit` isolated_bin on isolated_bin.name=isolated_membership.container_handling_unit
            where isolated_membership.content_handling_unit=unit.name and isolated_membership.state='Loaded'
              and ifnull(isolated_bin.rotation_excluded,0)=1)
    """


def validate_handling_unit_isolation(doc):
    """Fields are read-only; existing rules change only through the audited action.

    Stock identity splits/replacements copy the source's local rule, never a bin's
    effective rule. The bin's own rule applies through membership, including new fills.
    """
    if not _tag_installed():return
    if not doc.is_new():
        before=doc.get_doc_before_save()
        if before and (cint(before.get(TAG_FLAG))!=cint(doc.get(TAG_FLAG)) or
                       str(before.get(TAG_REASON) or '')!=str(doc.get(TAG_REASON) or '')):
            frappe.throw('Use FEFO / FIFO Isolation to change a tag/bin rule with an audit reason')
        return
    source_name=doc.get('replacement_of') or doc.get('parent_handling_unit') or (
        doc.get('origin_reference_name') if doc.get('origin_reference_doctype')=='CFG Kanban Handling Unit' else None)
    if source_name:
        sources=frappe.db.sql('select tag_kind, rotation_excluded, rotation_isolation_reason from `tabCFG Kanban Handling Unit` '
            'where name=%s for update',source_name,as_dict=True)
        if sources and ((sources[0].tag_kind=='Reusable Container')==(doc.tag_kind=='Reusable Container')):
            doc.rotation_excluded=cint(sources[0].rotation_excluded)
            doc.rotation_isolation_reason=sources[0].rotation_isolation_reason
            return
    if cint(doc.get(TAG_FLAG)) or doc.get(TAG_REASON):
        frappe.throw('Activate the identity first, then use FEFO / FIFO Isolation')
    doc.rotation_excluded=0
    doc.rotation_isolation_reason=None
