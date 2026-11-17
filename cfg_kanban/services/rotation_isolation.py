"""Audited supervisor isolation of one tag/fill or a persistent physical bin rule."""
import frappe
from frappe.utils import cint, flt

from cfg_kanban.services.batch_rotation import (
    _tag_installed, batch_rotation_exclusion, tag_rotation_exclusions,
)
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import resolve_logistics_scan
from cfg_kanban.services.operator_auth import require_operator
from cfg_kanban.services.physical_identity import normalize_physical_code

HU='CFG Kanban Handling Unit'
BIN_ROLES=('Logistics Container','Logistics Quantity Bin','Production Output Container')


def _authorize(token, write=False):
    if token:
        profile,session=require_operator(token,'override' if write else None)
        if profile.kanban_role not in ('Supervisor','Development Proxy') or profile.allowed_operations or profile.allowed_workstations:
            frappe.throw('An unrestricted Kanban Supervisor is required for stock selection isolation')
        return {'operator':profile.employee,'operator_session':session.name,'terminal_user':session.terminal_user}
    frappe.only_for(('Stock Manager','Manufacturing Manager','System Manager'))
    return {'operator':None,'operator_session':None,'terminal_user':frappe.session.user}


def _resolve(scan):
    identity=resolve_logistics_scan(scan)
    if not identity or identity.get('identity_type')!='Handling Unit':
        frappe.throw('Scan an activated Stock Tag or a reusable stock container')
    return frappe.get_doc(HU,identity['name'])


def _members(container,current=False):
    return frappe.db.sql("select content_handling_unit, loaded_on from `tabCFG Kanban Container Content` "
        "where container_handling_unit=%s and state='Loaded' order by name"+
        (' for update' if current else ''),container,as_dict=True)


def _validate_subject(unit):
    if unit.identity_state not in ('Active','Empty'):
        frappe.throw('Only an Active or Empty tag/bin can change selection isolation')
    if unit.tag_kind=='Reusable Container' and unit.reusable_container_role not in BIN_ROLES:
        frappe.throw('This bin uses separate operation WIP controls, not automatic stock-tag FEFO/FIFO selection')


def _context(unit, *, locked=None, current=False):
    _validate_subject(unit)
    members=_members(unit.name,current) if unit.tag_kind=='Reusable Container' else []
    names=[unit.name]+[row.content_handling_unit for row in members]
    loaded_on={row.content_handling_unit:str(row.loaded_on or '') for row in members}
    if locked is not None and any(name not in locked for name in names):
        frappe.throw('Bin contents changed; reread the source before confirming')
    rules=tag_rotation_exclusions(names,current=current)
    targets=[]
    for name in names:
        target=frappe.get_doc(HU,name)
        if locked is not None:target.update(locked[name])
        batch=batch_rotation_exclusion(target.batch_no,current=current) if target.get('batch_no') else None
        is_bin=target.tag_kind=='Reusable Container'
        source_code=None
        if target.get('origin_reference_doctype')==HU and target.get('origin_reference_name'):
            if not frappe.db.get_value(HU,target.origin_reference_name,'virtual_content'):
                source_code=frappe.db.get_value(HU,target.origin_reference_name,'handling_unit_id')
        targets.append({'name':target.name,'visible_code':unit.handling_unit_id if target.get('virtual_content') else target.handling_unit_id,
            'scope':'Bin (current and future loads)' if is_bin else 'Stock Tag / Fill',
            'item_code':target.item_code,'batch_no':target.batch_no,'stock_uom':target.stock_uom,
            'qty':flt(target.current_qty),'expiry_date':str(target.get('expiry_date') or ''),
            'loaded_on':loaded_on.get(name),'source_code':source_code,'excluded':cint(target.get('rotation_excluded')),
            'reason':target.get('rotation_isolation_reason') or '',
            'effective_isolation':rules.get(target.name),'batch_isolation':batch})
    fingerprint=canonical_key('stock-isolation-context',unit.name,targets)
    return {'source_scan':unit.handling_unit_id,'subject':unit.name,'targets':targets,'signature':fingerprint}


@frappe.whitelist()
def get_rotation_isolation_context(scan_value,operator_session_token=None):
    _authorize(operator_session_token)
    if not _tag_installed():frappe.throw('Run the site migration to install tag/bin selection isolation')
    return _context(_resolve(scan_value))


@frappe.whitelist()
def set_rotation_isolation(scan_value,target_name,excluded,reason,context_signature,event_token,
                           operator_session_token=None):
    actor=_authorize(operator_session_token,write=True)
    if not _tag_installed():frappe.throw('Run the site migration to install tag/bin selection isolation')
    if str(excluded) not in ('0','1'):frappe.throw('Choose Isolate or Release')
    excluded=cint(excluded);reason=str(reason or '').strip()
    if not reason or not event_token or not context_signature:
        frappe.throw('A reason, current source context and stable event token are required')
    scan_value=normalize_physical_code(scan_value)
    key=canonical_key('stock-selection-isolation',event_token)
    request=canonical_key('stock-selection-isolation-request',scan_value,target_name,excluded,reason,context_signature)
    unit=_resolve(scan_value)
    members=_members(unit.name) if unit.tag_kind=='Reusable Container' else []
    names=sorted({unit.name,*[row.content_handling_unit for row in members]})
    locked_rows=frappe.db.sql('select * from `tabCFG Kanban Handling Unit` where name in ('+
        ','.join(['%s']*len(names))+') order by name for update',tuple(names),as_dict=True)
    if len(locked_rows)!=len(names):frappe.throw('Source stock changed; reread the source')
    locked={row.name:row for row in locked_rows};unit.update(locked[unit.name])
    existing=frappe.db.sql('select payload_json from `tabCFG Kanban Event` where idempotency_key=%s for update',key)
    if existing:
        payload=frappe.parse_json(existing[0][0])
        if payload.get('request')!=request:frappe.throw('This retry token was used for different isolation data')
        return dict(payload['result'],duplicate=True)
    context=_context(unit,locked=locked,current=True)
    if context['signature']!=context_signature:
        frappe.throw('Isolation, quantity or bin contents changed; reread the source before confirming')
    target=next((row for row in context['targets'] if row['name']==target_name),None)
    if not target:frappe.throw('Select a tag/bin displayed for this scanned source')
    if target['excluded'] and not excluded and reason==target['reason']:
        frappe.throw('Enter a new release reason when returning this tag/bin to automatic selection')
    changed=target['excluded']!=excluded or target['reason']!=reason
    if changed:
        frappe.db.set_value(HU,target_name,{'rotation_excluded':excluded,'rotation_isolation_reason':reason})
    result={'name':target_name,'source_scan':context['source_scan'],'visible_code':target['visible_code'],
            'scope':target['scope'],'excluded':excluded,'changed':changed,
            'note':'Other Batch, tag or bin rules remain in force. Reread the source to see current effective isolation.'}
    audit=record('Stock Rotation Isolation Changed',handling_unit=target_name,
        reference_doctype=HU,reference_name=target_name,operator=actor['operator'],
        operator_session=actor['operator_session'],terminal_user=actor['terminal_user'],notes=reason,
        payload={'request':request,'target_before':target,'excluded_after':excluded,'reason_after':reason,'result':result},
        idempotency_key=key)
    if not audit or frappe.parse_json(audit.payload_json).get('request')!=request:
        frappe.throw('This retry token was used concurrently for different isolation data')
    return result
