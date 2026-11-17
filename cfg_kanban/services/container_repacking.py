"""Atomic same-warehouse stock repacking across physical tags/reusable containers.

Operational Hopper WIP is separate. This moves existing stock identity/quantity,
never manufactures stock, changes an ERP Batch, or posts an ERP warehouse transfer.
"""
import math

import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.container_contents import (
    _authorize, active_container_contents, active_container_membership,
    assert_container_not_in_open_manifest, assert_container_not_in_open_delivery,
)
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import resolve_logistics_scan, post_quantity_event
from cfg_kanban.services.logistics_stock_identity import (
    assert_merge_compatible, identity_snapshot, inherit_split_certificates,
)
from cfg_kanban.services.physical_identity import normalize_physical_code
from cfg_kanban.services.retagging_auth import authorize_stock_retagging

EPSILON = 0.000001
ROLES = ('Logistics Container', 'Logistics Quantity Bin', 'Production Output Container')
RESTRICTED = ('Internal Transit', 'Intercompany Transit', 'Delivered', 'Quarantined', 'Reserved')


def _auth(token, write=False):
    authorize_stock_retagging(token, 'start' if write else None)
    return _authorize(token, write=write)


def _resolve(scan):
    identity = resolve_logistics_scan(scan)
    if not identity or identity.get('identity_type') != 'Handling Unit':
        frappe.throw('Scan an active Stock Tag or reusable container')
    return frappe.get_doc('CFG Kanban Handling Unit', identity['name'])


def _container(unit):
    if (unit.tag_kind != 'Reusable Container' or unit.reusable_container_role not in ROLES or
            unit.identity_state != 'Active' or unit.quality_state != 'Released' or unit.movement_state in RESTRICTED):
        frappe.throw('Use an Active, Released logistics or production-output container outside an open movement')
    assert_container_not_in_open_manifest(unit.name, 'repacking its contents')
    assert_container_not_in_open_delivery(unit.name, 'repacking its contents')


def _stock(unit):
    if (unit.tag_kind == 'Reusable Container' or unit.identity_state != 'Active' or unit.quality_state != 'Released' or
            unit.movement_state not in ('At Source','Packed','Received','Returned') or not unit.item_code or not unit.stock_uom or
            not unit.inventory_company or not unit.current_warehouse):
        frappe.throw('Repacking requires Active, Released stock with Item, UOM, Company and Warehouse')
    quantities = [flt(unit.get(field)) for field in ('current_qty','reserved_qty','available_qty')]
    if (not all(math.isfinite(qty) and qty>=0 for qty in quantities) or quantities[0] <= EPSILON or
            quantities[1] > EPSILON or abs(quantities[0]-quantities[2]) > EPSILON):
        frappe.throw('Release all stock reservations and reconcile its balance before repacking')
    if frappe.db.get_value('Item',unit.item_code,'has_serial_no') or unit.get('serial_count') or frappe.db.exists('CFG Kanban Handling Unit Serial', {'handling_unit':unit.name,'state':'Active'}):
        frappe.throw('Serial-controlled stock requires its exact-serial workflow')
    from cfg_kanban.services.logistics_quantity_bins import _assert_source_not_in_open_transaction
    _assert_source_not_in_open_transaction(unit.name)
    if frappe.db.table_exists('CFG Kanban Operation Material Draw'):
        from cfg_kanban.services.operation_material_runs import _source_reserved_qty
        if _source_reserved_qty(unit.name) > EPSILON:
            frappe.throw('Release/settle the Material Run reservations before repacking this source')



def _current_transaction_guards(names):
    placeholders=','.join(['%s']*len(names))
    manifest=frappe.db.sql("""select manifest.name from `tabCFG Kanban Manifest Line` line
        join `tabCFG Kanban Movement Manifest` manifest on manifest.name=line.parent
        where (line.handling_unit in ("""+placeholders+") or line.container_handling_unit in ("+placeholders+"""))
          and manifest.state not in ('Received','Billing Pending','Partially Billed','Billed','Closed','Cancelled')
        for update""",tuple(names)+tuple(names))
    delivery=frappe.db.sql("select name from `tabCFG Kanban Delivery Allocation` where (handling_unit in ("+
        placeholders+") or container_handling_unit in ("+placeholders+")) and state in ('Reserved','Delivery Pending','Exception') for update",tuple(names)+tuple(names))
    if manifest or delivery:
        frappe.throw('Release the open Manifest or Delivery allocation before repacking')

def _compatible(source, destination):
    for field in ('item_code','batch_no','stock_uom','inventory_company','current_warehouse','current_operation','packed_on'):
        if str(source.get(field) or '') != str(destination.get(field) or ''):
            frappe.throw('Destination stock must have the same Item, Batch, UOM, Company, Warehouse, operation and packing date')
    assert_merge_compatible(source, destination)


def _option(unit, container=None):
    code = container.handling_unit_id if unit.get('virtual_content') and container else unit.handling_unit_id
    return {'name':unit.name,'visible_code':code,'item_code':unit.item_code,'batch_no':unit.batch_no,
            'stock_uom':unit.stock_uom,'qty':flt(unit.current_qty),'available_qty':flt(unit.available_qty),
            'company':unit.inventory_company,'warehouse':unit.current_warehouse,'expiry_date':unit.expiry_date,
            'process_certificate_set':unit.get('process_certificate_set'),
            'container':container.name if container else None,
            'source_code':frappe.db.get_value('CFG Kanban Handling Unit',unit.origin_reference_name,'handling_unit_id')
                          if unit.origin_reference_doctype=='CFG Kanban Handling Unit' else None}


@frappe.whitelist()
def repack_source_context(source_scan, operator_session_token=None):
    _auth(operator_session_token)
    scanned = _resolve(source_scan)
    if scanned.tag_kind == 'Reusable Container':
        _container(scanned)
        from cfg_kanban.services.operation_hoppers import assert_no_operation_fill
        assert_no_operation_fill(scanned.name, 'stock repacking; use Recover Hopper for intermediate operation WIP')
        rows = active_container_contents(scanned.name)
        options = [_option(frappe.get_doc('CFG Kanban Handling Unit',row.content_handling_unit), scanned) for row in rows]
    else:
        if scanned.get('virtual_content'):
            frappe.throw('Scan the permanent physical container QR, not its internal stock identity')
        membership = active_container_membership(scanned.name)
        holder = frappe.get_doc('CFG Kanban Handling Unit',membership.container_handling_unit) if membership else None
        options = [_option(scanned,holder)]
    options = [row for row in options if row['qty'] > EPSILON]
    if not options:
        frappe.throw('This container has no received stock to repack; intermediate WIP uses Recover Hopper')
    return {'source_scan':source_scan,'options':options}


@frappe.whitelist()
def repack_destination_context(source_stock, destination_scan, operator_session_token=None):
    _auth(operator_session_token)
    source = frappe.get_doc('CFG Kanban Handling Unit',source_stock)
    destination = _resolve(destination_scan)
    _container(destination)
    from cfg_kanban.services.operation_hoppers import assert_no_operation_fill
    assert_no_operation_fill(destination.name, 'receiving repacked stock')
    if ((destination.inventory_company and destination.inventory_company != source.inventory_company) or
            (destination.current_warehouse and destination.current_warehouse != source.current_warehouse)):
        frappe.throw('Same-warehouse repacking requires the same Company and Warehouse; use a Manifest for warehouse movement')
    options=[]
    for row in active_container_contents(destination.name):
        unit=frappe.get_doc('CFG Kanban Handling Unit',row.content_handling_unit)
        _compatible(source,unit)
        options.append(_option(unit,destination))
    return {'destination':destination.name,'visible_code':destination.handling_unit_id,
            'role':destination.reusable_container_role,'options':options,'new_tag_allowed':not bool(options)}


@frappe.whitelist()
def repack_new_tag_context(new_tag, operator_session_token=None):
    _auth(operator_session_token)
    from cfg_kanban.services.tag_to_tag_transfer import _validate_unused_main_tag
    code = normalize_physical_code(new_tag)
    if not code:
        frappe.throw('Scan an unused preprinted Main Stock Tag')
    _validate_unused_main_tag(code)
    return {'visible_code': code}


def _lock_units(names):
    names=sorted(set(filter(None,names)))
    rows=frappe.db.sql('select * from `tabCFG Kanban Handling Unit` where name in ('+
        ','.join(['%s']*len(names))+') order by name for update',tuple(names),as_dict=True)
    if len(rows)!=len(names):frappe.throw('A source or destination identity no longer exists')
    return {row.name:row for row in rows}


def _memberships(stock_name=None, container_name=None):
    field,value=('content_handling_unit',stock_name) if stock_name else ('container_handling_unit',container_name)
    return frappe.db.sql('select * from `tabCFG Kanban Container Content` where '+field+"=%s and state='Loaded' order by name for update",value,as_dict=True)


def _doc(name, locked):
    unit=frappe.get_doc('CFG Kanban Handling Unit',name)
    unit.update(locked[name])
    return unit


def _close(episode, actor, key, reason):
    frappe.db.set_value('CFG Kanban Container Content',episode.name,{
        'state':'Unloaded','unloaded_on':now_datetime(),'unloaded_by':actor.get('operator'),
        'unloaded_operator_session':actor.get('operator_session'),
        'unload_event_key':canonical_key('container-repack-unload',key,episode.name),'unload_reason':reason})


def _attach(container, stock, actor, key):
    return frappe.get_doc({'doctype':'CFG Kanban Container Content','state':'Loaded',
        'container_handling_unit':container.name,'container_visible_code':container.handling_unit_id,
        'content_handling_unit':stock.name,'content_visible_code':stock.handling_unit_id,
        'item_code':stock.item_code,'batch_no':stock.batch_no,'stock_uom':stock.stock_uom,'qty':flt(stock.current_qty),
        'company':stock.inventory_company,'warehouse':stock.current_warehouse,'loaded_on':now_datetime(),
        'loaded_by':actor.get('operator'),'loaded_operator_session':actor.get('operator_session'),
        'load_event_key':canonical_key('container-repack-load',key,stock.name)}).insert(ignore_permissions=True)


def _new_stock(source, container, qty, new_tag, key):
    if new_tag:
        from cfg_kanban.services.tag_to_tag_transfer import _validate_unused_main_tag
        _validate_unused_main_tag(new_tag)
    elif container.reusable_container_role=='Logistics Container':
        frappe.throw('A partial/internal source needs a new preprinted main tag in a Logistics Container')
    destination=frappe.copy_doc(source)
    destination.name=None
    destination.update({'handling_unit_id':new_tag or ('REPACK-FILL-'+key[:20].upper()),
        'opaque_token':None,'tag_kind':'Main Stock Tag','tag_family':None,'tag_range_registry':None,
        'parent_handling_unit':None,'root_handling_unit':None,'child_index':0,
        'virtual_content':0 if new_tag else 1,'physical_container':None if new_tag else container.name,
        'qty':qty,'original_qty':qty,'current_qty':0,'reserved_qty':0,'available_qty':0,'serial_count':0,
        'identity_state':'Active','movement_state':'Packed','state':'Attached',
        'origin_reference_doctype':'CFG Kanban Handling Unit','origin_reference_name':source.name,'origin_reference_row':None,
        'activation_key':canonical_key('container-repack-stock',key),'replacement_of':None,'replaced_by':None,
        'void_reason':None,'print_revision':1,'print_count':0,'last_printed_on':None,'last_printed_by':None,'last_scan_time':None})
    destination.flags.skip_initial_ledger=True
    destination.flags.activation_reason='Controlled same-warehouse container repack'
    destination.insert(ignore_permissions=True)
    return destination


@frappe.whitelist()
def move_container_stock(source_scan, source_stock, destination_scan, qty, reason, event_token,
                         destination_stock=None, new_tag=None, operator_session_token=None):
    actor=_auth(operator_session_token,write=True)
    try:qty=float(qty)
    except (TypeError,ValueError):frappe.throw('Enter a finite positive quantity')
    reason=str(reason or '').strip()
    if not reason or not event_token or not math.isfinite(qty) or qty<=EPSILON:
        frappe.throw('A positive quantity, reason and stable event token are required')
    source_scan=normalize_physical_code(source_scan);destination_scan=normalize_physical_code(destination_scan)
    new_tag=normalize_physical_code(new_tag) if new_tag else None
    key=canonical_key('container-stock-repack',event_token)
    request=canonical_key('container-stock-repack-request',source_scan,source_stock,destination_scan,
                          destination_stock or '',new_tag or '',qty,reason)
    scanned=_resolve(source_scan);target=_resolve(destination_scan)
    original_member=active_container_membership(source_stock)
    source_container_name=original_member.container_handling_unit if original_member else None
    initial_destination=active_container_contents(target.name) if target.tag_kind=='Reusable Container' else []
    names=[scanned.name,target.name,source_stock,source_container_name,destination_stock,
           *[row.content_handling_unit for row in initial_destination]]
    locked=_lock_units(names)
    replay=frappe.db.sql('select payload_json from `tabCFG Kanban Event` where idempotency_key=%s for update',key)
    if replay:
        payload=frappe.parse_json(replay[0][0])
        if payload['request']!=request:frappe.throw('This retry token was used for different repacking data')
        return dict(payload['result'],duplicate=True)
    source=_doc(source_stock,locked);target=_doc(target.name,locked);scanned=_doc(scanned.name,locked)
    members=_memberships(stock_name=source.name)
    if len(members)>1:frappe.throw('Source has conflicting container memberships; reconcile it first')
    member=members[0] if members else None
    current_holder=member.container_handling_unit if member else None
    if current_holder!=source_container_name or (scanned.tag_kind=='Reusable Container' and current_holder!=scanned.name) or (scanned.tag_kind!='Reusable Container' and scanned.name!=source.name):
        frappe.throw('Source contents changed; reload and select the exact stock identity')
    holder=_doc(current_holder,locked) if current_holder else None
    _stock(source);_container(target)
    if holder:
        _container(holder)
        if holder.inventory_company!=source.inventory_company or holder.current_warehouse!=source.current_warehouse:
            frappe.throw('Source container location does not match its stock')
    if source.get('virtual_content') and scanned.tag_kind!='Reusable Container':
        frappe.throw('Scan the permanent physical container QR, not its internal stock identity')
    if source.get('virtual_content') and (not holder or source.physical_container!=holder.name):
        frappe.throw('Internal stock is not attached to its recorded source container')
    if frappe.db.get_value('UOM',source.stock_uom,'must_be_whole_number') and abs(qty-round(qty))>EPSILON:
        frappe.throw('This stock UOM requires a whole-number quantity')
    if qty>flt(source.available_qty)+EPSILON:frappe.throw('Quantity exceeds available source stock')
    containers=sorted({row.name for row in (target,holder) if row})
    if frappe.db.table_exists('CFG Kanban Operation Hopper Fill'):
        wip=frappe.db.sql('select name from `tabCFG Kanban Operation Hopper Fill` where active_hopper_key in ('+
            ','.join(['%s']*len(containers))+') for update',tuple(containers))
        if wip:frappe.throw('Intermediate operation Hopper WIP uses Recover Hopper, not stock repacking')
    if ((target.inventory_company and target.inventory_company!=source.inventory_company) or
            (target.current_warehouse and target.current_warehouse!=source.current_warehouse)):
        frappe.throw('Repacking requires the same Company and Warehouse; use a Manifest for warehouse movement')
    _current_transaction_guards(sorted(locked))
    dest_members=_memberships(container_name=target.name)
    if {row.content_handling_unit for row in dest_members}!={row.content_handling_unit for row in initial_destination}:
        frappe.throw('Destination contents changed; reload before confirming')
    if any(row.content_handling_unit not in locked for row in dest_members):
        frappe.throw('Destination stock changed; reload before confirming')
    destination=None
    if target.reusable_container_role=='Production Output Container' and len(dest_members)>1:
        frappe.throw('Reconcile this production container to one fill before adding stock')
    if dest_members:
        if new_tag:frappe.throw('Destination already has stock: combine into its existing compatible tag, not a new tag')
        if not destination_stock:frappe.throw('Select the exact existing destination tag')
        for row in dest_members:
            stock=_doc(row.content_handling_unit,locked)
            _stock(stock);_compatible(source,stock)
            if stock.name==destination_stock:destination=stock
        if not destination:frappe.throw('Selected destination tag is not loaded in this container')
        if destination.name==source.name:frappe.throw('Source and destination already identify the same stock; no movement is needed')
    elif destination_stock:
        frappe.throw('Destination tag is no longer loaded; reload before confirming')
    if not target.inventory_company or not target.current_warehouse:
        target.db_set({'inventory_company':source.inventory_company,'current_warehouse':source.current_warehouse},update_modified=False)
    before=identity_snapshot(source)
    destination_before=identity_snapshot(destination) if destination else None
    whole=abs(qty-flt(source.current_qty))<=EPSILON
    keep_tag=not destination and not new_tag and not source.get('virtual_content') and whole
    if keep_tag:
        if holder and holder.name==target.name:frappe.throw('The Stock Tag is already in this container')
        if member:_close(member,actor,key,reason)
        destination=source
        _attach(target,destination,actor,key)
        ledger=None
    else:
        destination=destination or _new_stock(source,target,qty,new_tag,key)
        ledger=post_quantity_event(event_type='Merge' if dest_members else 'Split',qty=qty,stock_uom=source.stock_uom,
            idempotency_key=canonical_key('container-repack-ledger',key),source_handling_unit=source.name,
            destination_handling_unit=destination.name,item_code=source.item_code,batch_no=source.batch_no,
            source_company=source.inventory_company,destination_company=source.inventory_company,
            source_warehouse=source.current_warehouse,destination_warehouse=source.current_warehouse,
            reference_doctype='CFG Kanban Handling Unit',reference_name=target.name,
            operator=actor.get('operator'),operator_session=actor.get('operator_session'),
            device_id=event_token,reason='Container stock repack: '+reason)
        source.reload();destination.reload()
        inherit_split_certificates(source,destination,qty,key,replacement=whole and not dest_members)
        if whole:
            source.db_set({'identity_state':'Empty','movement_state':'Empty'},update_modified=False)
            if member:_close(member,actor,key,reason)
        if not dest_members:_attach(target,destination,actor,key)
    for container in (holder,target):
        if container:
            active=_memberships(container_name=container.name)
            container.db_set({'movement_state':'Packed' if active else 'Empty','last_scan_time':now_datetime()},update_modified=False)
    result={'source_stock':source.name,'destination_stock':destination.name,'destination_container':target.name,
            'destination_code':target.handling_unit_id,'destination_tag':destination.handling_unit_id if not destination.get('virtual_content') else target.handling_unit_id,
            'moved_qty':qty,'destination_qty':flt(destination.current_qty),'source_qty':flt(source.current_qty) if destination.name!=source.name else 0,
            'item_code':source.item_code,'batch_no':source.batch_no,'stock_uom':source.stock_uom,'ledger':ledger.name if ledger else None,
            'existing_tag_used':bool(dest_members),'whole_tag_moved':keep_tag}
    audit=record('Container Stock Repacked',handling_unit=target.name,qty=qty,
           reference_doctype='CFG Kanban Handling Unit',reference_name=destination.name,
           operator=actor.get('operator'),operator_session=actor.get('operator_session'),terminal_user=actor.get('terminal_user'),
           notes=reason,payload={'request':request,'source_before':before,'destination_before':destination_before,
                                'destination_after':identity_snapshot(destination),'result':result},idempotency_key=key)
    if not audit or frappe.parse_json(audit.payload_json).get('request')!=request:
        frappe.throw('This retry token was used concurrently for different repacking data')
    return result


def protect_receipt_cancellation(doc, method=None):
    """Do not leave a received tag voided while it is still packed elsewhere."""
    if doc.doctype not in ('Stock Entry','Purchase Receipt'):return
    # Serialize with repacking before inspecting membership. Snapshot reads could
    # otherwise miss a tag loaded while native cancellation waited for its row.
    units=frappe.db.sql("""select name, virtual_content, physical_container
        from `tabCFG Kanban Handling Unit`
        where origin_reference_doctype=%s and origin_reference_name=%s
        order by name for update""",(doc.doctype,doc.name),as_dict=True)
    for unit in units:
        memberships=_memberships(stock_name=unit.name)
        if any(not unit.get('virtual_content') or row.container_handling_unit!=unit.physical_container
               for row in memberships):
            frappe.throw('Unload/reconcile received stock from its reusable container before cancelling this receipt')
