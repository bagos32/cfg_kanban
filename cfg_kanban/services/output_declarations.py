"""Pre-receipt final-output bundling. Declarations reserve identities, never ERP stock."""
import math
import frappe
from frappe.utils import cint, flt, now_datetime
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.operator_auth import require_operator
from cfg_kanban.services.logistics_foundation import resolve_logistics_scan
from cfg_kanban.services.physical_identity import normalize_physical_code

DT='CFG Kanban Output Declaration'
EPS=0.000001
ACTIVE=('Declared','Bound to Draft')


def installed():return frappe.db.table_exists(DT)


def _supervisor(profile):
    if profile.kanban_role not in ('Supervisor','Development Proxy') or profile.allowed_operations or profile.allowed_workstations:
        frappe.throw('An unrestricted Supervisor must prepare/post station-declared output')


def _station(token, session_token, action=None):
    from cfg_kanban.api.operator import _resolve_card_name
    name=_resolve_card_name(token)
    card=frappe.get_doc('CFG Kanban Card',name) if name else None
    if not card or card.card_type!='Workstation Queue Card' or not card.active or card.blocked or not card.current_station or not card.queue_company:
        frappe.throw('Scan an active Workstation Queue Card with Company and Workstation configured')
    profile,session=require_operator(session_token,action,workstation=card.current_station)
    return card,profile,session


def _order(name, lock=False):
    locked=frappe.db.sql('select * from `tabWork Order` where name=%s for update',name,as_dict=True) if lock else None
    order=frappe.get_doc('Work Order',name)
    if locked:order.update(locked[0])
    cycle=frappe.get_doc('CFG Kanban Cycle',order.cfg_kanban_cycle) if order.get('cfg_kanban_cycle') else None
    if not cycle:frappe.throw('Only a Kanban-owned Work Order can declare station output')
    master=frappe.get_doc('CFG Kanban Master',cycle.kanban_master)
    return order,cycle,master


def _declarations(work_order, current=False):
    return frappe.db.sql('select * from `tabCFG Kanban Output Declaration` where work_order=%s order by declared_on,name'+
        (' for update' if current else ''),work_order,as_dict=True)


def _final_jobs(order,current=False):
    operations=sorted(order.operations,key=lambda row:(cint(row.get('sequence_id') or row.idx),cint(row.idx)))
    if not operations:frappe.throw('Work Order has no final ERP operation')
    final=operations[-1]
    fields=['name','operation','workstation','total_completed_qty','docstatus','status']
    has_id=frappe.get_meta('Job Card').has_field('operation_id')
    if has_id:fields.append('operation_id')
    jobs=frappe.db.sql('select '+','.join(fields)+' from `tabJob Card` where work_order=%s and operation=%s and docstatus<2 order by name'+(' for update' if current else ''),(order.name,final.operation),as_dict=True)
    repeated=sum(1 for row in operations if row.operation==final.operation)>1
    result=[]
    for job in jobs:
        if job.get('operation_id'):
            if job.operation_id!=final.name:continue
        elif repeated:
            frappe.throw('Repeated final operation requires exact Job Card operation-row identity; reconcile this route')
        result.append(job)
    return final.operation,result


def availability(order, master, workstation, current=False):
    operation,jobs=_final_jobs(order,current)
    total=sum(max(0,flt(job.total_completed_qty)) for job in jobs)
    dedicated=master.get('output_packing_workstation')
    local=total if dedicated==workstation else (0 if dedicated else sum(max(0,flt(job.total_completed_qty)) for job in jobs if job.workstation==workstation))
    declarations=_declarations(order.name,current)
    pending=sum(flt(row.qty) for row in declarations if row.status in ACTIVE)
    posted=sum(flt(row.qty) for row in declarations if row.status=='Posted')
    local_taken=sum(flt(row.qty) for row in declarations if row.workstation==workstation and row.status in (*ACTIVE,'Posted'))
    unlocated_posted=max(0,flt(order.produced_qty)-posted)
    available=max(0,min(total-flt(order.produced_qty)-pending,local-local_taken-unlocated_posted,flt(order.qty)-flt(order.produced_qty)-pending))
    return {'operation':operation,'reported_good_qty':total,'station_good_qty':local,'already_received_qty':flt(order.produced_qty),
        'pending_declared_qty':pending,'available_qty':available,'declarations':[dict(row) for row in declarations],
        'job_cards':[dict(job) for job in jobs]}


def _validate_order(order,cycle,master,card):
    if order.docstatus!=1 or order.status in ('Completed','Closed','Stopped','Cancelled') or cycle.status in ('Completed','Cancelled'):
        frappe.throw('Use an active submitted Work Order with an open Production Cycle')
    if master.control_type!='Production' or not cint(master.get('enable_station_output_declarations')):
        frappe.throw('Enable station output declarations on this Production Master first')
    if order.company!=card.queue_company:frappe.throw('Work Order and station belong to different Companies')
    if master.company!=order.company or master.item_code!=order.production_item:
        frappe.throw('The Master Item/Company changed after Work Order release; reconcile its packing setup')
    if master.stock_uom!=frappe.db.get_value('Item',order.production_item,'stock_uom'):
        frappe.throw('The Master stock UOM differs from the finished Item; reconcile before declaring output')
    from cfg_kanban.services.production_cancellation import assert_cycle_not_under_cancellation
    assert_cycle_not_under_cancellation(cycle.name)
    if frappe.db.sql("select name from `tabStock Entry` where work_order=%s and purpose='Manufacture' and docstatus=0 for update",order.name):
        frappe.throw('A Manufacture Draft already exists. Review/post/discard it before declaring another bundle')


@frappe.whitelist()
def station_output_context(station_scan,operator_session_token=None):
    if not installed():frappe.throw('Run the migration to install station output declarations')
    card,profile,_session=_station(station_scan,operator_session_token)
    # Candidate discovery is bounded by Company, open Work Orders and configured Masters.
    orders=[row.name for row in frappe.db.sql("""select distinct wo.name
        from `tabWork Order` wo
        join `tabCFG Kanban Cycle` cycle on cycle.name=wo.cfg_kanban_cycle
        join `tabCFG Kanban Master` master on master.name=cycle.kanban_master
        where wo.company=%s and wo.docstatus=1 and wo.status not in ('Completed','Closed','Stopped','Cancelled')
          and cycle.status not in ('Completed','Cancelled') and master.control_type='Production'
          and master.enable_station_output_declarations=1
          and (master.output_packing_workstation=%s
            or (ifnull(master.output_packing_workstation,'')='' and exists
                (select 1 from `tabJob Card` job where job.work_order=wo.name and job.workstation=%s and job.docstatus<2))
            or exists (select 1 from `tabCFG Kanban Output Declaration` declaration
                where declaration.work_order=wo.name and declaration.workstation=%s and declaration.status in ('Declared','Bound to Draft')))
        order by wo.name""",(card.queue_company,card.current_station,card.current_station,card.current_station),as_dict=True)]
    choices=[]
    for name in orders:
        order,cycle,master=_order(name)
        if not cint(master.get('enable_station_output_declarations')) or cycle.status in ('Completed','Cancelled') or not order.operations:continue
        info=availability(order,master,card.current_station)
        if profile.allowed_operations and info['operation'] not in {row.operation for row in profile.allowed_operations}:continue
        if info['station_good_qty']<=EPS and not any(row['workstation']==card.current_station and row['status'] in ACTIVE for row in info['declarations']):continue
        choices.append({'work_order':name,'cycle':cycle.name,'item_code':order.production_item,'stock_uom':master.stock_uom,
            'warehouse':master.destination_warehouse or order.fg_warehouse,**info})
    return {'station_card':card.name,'station_scan':card.card_number,'workstation':card.current_station,'company':card.queue_company,'choices':choices}


def canonical_output_code(code):
    identity=resolve_logistics_scan(code)
    if identity and identity.get('visible_code'):return identity['visible_code']
    if identity and identity.get('identity_type')=='Handling Unit':
        return frappe.db.get_value('CFG Kanban Handling Unit',identity['name'],'handling_unit_id')
    return code


def identity_key(code):return canonical_key('pending-output-identity',canonical_output_code(code)) if code else None


def lock_identity(code):
    """Share exact physical identity locks with ordinary staging and tag activation."""
    identity=resolve_logistics_scan(code)
    if identity and identity.get('identity_type')=='Handling Unit':
        frappe.db.sql('select name from `tabCFG Kanban Handling Unit` where name=%s for update',identity['name'])
    else:
        if identity and identity.get('identity_type')=='Tag Range Candidate':
            from cfg_kanban.services.tag_registry import materialize_tag_family_for_code
            materialize_tag_family_for_code(code)
        rows=frappe.db.sql('select name from `tabCFG Kanban Tag Identity` where visible_code=%s for update',code)
        if not rows:frappe.throw('Scan a registered unused main tag or Production Output Container')
    return identity


def reservation(code,stock_entry=None,declaration=None,activation=False):
    if not installed() or not code:return None
    code=canonical_output_code(code)
    identity=lock_identity(code)
    container=identity['name'] if identity and identity.get('identity_type')=='Handling Unit' else None
    native=frappe.db.sql("""select trace.stock_entry from `tabCFG Kanban Material Trace Line` line
        join `tabCFG Kanban Material Trace` trace on trace.name=line.parent
        where trace.status='Draft' and line.direction='Output' and line.status='Pending'
          and (line.pending_tag_code=%s or line.physical_container=%s) for update""",(code,container),as_dict=True)
    if any(row.stock_entry!=stock_entry for row in native):
        frappe.throw('This output identity is already staged on another native Draft')
    rows=frappe.db.sql('select name,status,stock_entry from `tabCFG Kanban Output Declaration` where active_tag_key=%s or active_container_key=%s for update',
        (identity_key(code),identity_key(code)),as_dict=True)
    if not rows:return None
    row=rows[0]
    if row.name==declaration:return row
    if stock_entry and row.status=='Bound to Draft' and row.stock_entry==stock_entry:
        if activation and frappe.db.get_value('Stock Entry',stock_entry,'docstatus')!=1:
            frappe.throw('Pending declared output activates only inside submitted ERP receipt reconciliation')
        return row
    frappe.throw('This tag/bin is reserved by pending output declaration '+row.name)


def _identity(tag_code,container_code,company,warehouse,declaration=None,stock_entry=None):
    from cfg_kanban.services.production_trace import _validate_unused_main_tag,_production_output_container
    for code in sorted(filter(None,[tag_code,container_code])):reservation(code,stock_entry,declaration)
    if tag_code:_validate_unused_main_tag(tag_code)
    container=_production_output_container(container_code,company,warehouse,stock_entry=stock_entry,declaration=declaration) if container_code else None
    if container:
        from cfg_kanban.services.operation_hoppers import assert_no_operation_fill
        assert_no_operation_fill(container.name,'declaring finished output')
    return container


@frappe.whitelist()
def declare_output(station_scan,work_order,qty,event_token,tag_code=None,container_code=None,notes=None,operator_session_token=None):
    if not installed():frappe.throw('Run the migration to install station output declarations')
    card,profile,session=_station(station_scan,operator_session_token,'report_progress')
    order,cycle,master=_order(work_order,lock=True)
    try:qty=float(qty)
    except (TypeError,ValueError):frappe.throw('Enter a finite positive bundle quantity')
    if not math.isfinite(qty) or qty<=EPS or not event_token:frappe.throw('A finite positive quantity and stable action token are required')
    tag_code=canonical_output_code(normalize_physical_code(tag_code)) if tag_code else None
    container_code=canonical_output_code(normalize_physical_code(container_code)) if container_code else None
    if not tag_code and not container_code:frappe.throw('Scan a preprinted output tag, a permanent bin, or both')
    key=canonical_key('station-output-declaration',event_token)
    fingerprint=canonical_key('station-output-request',card.name,work_order,qty,tag_code,container_code,str(notes or '').strip())
    existing=frappe.db.sql('select * from `tabCFG Kanban Output Declaration` where idempotency_key=%s for update',key,as_dict=True)
    if existing:
        if existing[0].request_fingerprint!=fingerprint:frappe.throw('This retry token was used for different output declaration data')
        return {'name':existing[0].name,'qty':existing[0].qty,'duplicate':True}
    _validate_order(order,cycle,master,card)
    info=availability(order,master,card.current_station,current=True)
    require_operator(operator_session_token,'report_progress',operation=info['operation'],workstation=card.current_station)
    if qty>info['available_qty']+EPS:frappe.throw('Bundle quantity exceeds reported good output still available at this station: '+str(info['available_qty']))
    if frappe.db.get_value('UOM',master.stock_uom,'must_be_whole_number') and abs(qty-round(qty))>EPS:frappe.throw('This stock UOM requires whole quantities')
    if frappe.db.get_value('Item',order.production_item,'has_serial_no'):frappe.throw('ERP serial-controlled output requires exact native serial staging; use the Draft trace workflow')
    from cfg_kanban.services.trace_policy import effective_trace_policy,NO_TAG
    policy=effective_trace_policy(order.production_item,order.company)
    if policy.production_output_tag_policy==NO_TAG or not policy.allow_partial_tag_quantity:
        frappe.throw('Enable production-output tags and Allow ERP Quantity Across Multiple Tags for station bundling')
    warehouse=master.destination_warehouse or order.fg_warehouse
    container=_identity(tag_code,container_code,order.company,warehouse)
    declaration=frappe.get_doc({'doctype':DT,'status':'Declared','work_order':order.name,'kanban_cycle':cycle.name,'kanban_master':master.name,
        'station_card':card.name,'workstation':card.current_station,'company':order.company,'item_code':order.production_item,'stock_uom':master.stock_uom,
        'warehouse':warehouse,'qty':qty,'tag_code':tag_code,'container_code':container_code,'physical_container':container.name if container else None,
        'handling_unit_type':'Container','declared_on':now_datetime(),'operator':profile.employee,'operator_session':session.name,'terminal_user':session.terminal_user,
        'notes':str(notes or '').strip(),'source_snapshot':frappe.as_json(dict({key:info[key] for key in ('operation','reported_good_qty','station_good_qty','available_qty','already_received_qty','job_cards')},master_revision=master.get('revision'))),'previous_container_state':container.movement_state if container else None,
        'idempotency_key':key,'request_fingerprint':fingerprint,'active_tag_key':identity_key(tag_code),'active_container_key':identity_key(container_code)})
    declaration.flags.controlled_output_declaration=True
    declaration.insert(ignore_permissions=True)
    if container:container.db_set('movement_state','Reserved',update_modified=False)
    record('Finished Output Declared',cycle=cycle.name,reference_doctype=DT,reference_name=declaration.name,qty=qty,operator=profile.employee,
        operator_session=session.name,terminal_user=session.terminal_user,payload={'reported_good':info['reported_good_qty'],'station_available_before':info['available_qty'],'tag':tag_code,'bin':container_code})
    return {'name':declaration.name,'qty':qty,'duplicate':False}


def receipt_plan(order, master, qty, profile):
    if not installed():return []
    rows=[row for row in _declarations(order.name,True) if row.status=='Declared']
    enabled=cint(master.get('enable_station_output_declarations')) or bool(rows)
    if not enabled:return []
    _supervisor(profile)
    if not rows or abs(sum(flt(row.qty) for row in rows)-flt(qty))>EPS:
        frappe.throw('Receipt quantity must equal all pending declared bundles: '+str(sum(flt(row.qty) for row in rows)))
    return rows


def adopt(entry_name,declarations,token,card):
    if not declarations:return 0
    from cfg_kanban.services.production_trace import stage_output_tag,_get_trace
    profile,session=require_operator(token,'production_receipt')
    _supervisor(profile)
    entry=frappe.get_doc('Stock Entry',entry_name)
    outputs=[row for row in entry.items if row.item_code==declarations[0].item_code and row.t_warehouse and not row.s_warehouse]
    if len(outputs)!=1:frappe.throw('Station declarations require one unambiguous finished output row')
    output=outputs[0]
    if abs(flt(output.transfer_qty or output.qty)-sum(flt(row.qty) for row in declarations))>EPS:frappe.throw('Draft output differs from declared bundle total')
    for row in declarations:
        if row.warehouse!=output.t_warehouse or row.stock_uom!=output.stock_uom:frappe.throw('Declared warehouse/UOM differs from the Manufacture output')
        frappe.db.set_value(DT,row.name,{'status':'Bound to Draft','stock_entry':entry.name})
        stage_output_tag(entry.name,output.name,row.tag_code or row.container_code,row.qty,operator_session_token=token,kanban_card=card)
        trace=_get_trace(entry.name)
        line=next(line for line in trace.lines if line.status=='Pending' and line.pending_tag_code==(row.tag_code or row.container_code))
        if row.tag_code and row.physical_container:
            _identity(None,row.container_code,row.company,row.warehouse,stock_entry=entry.name)
            line.physical_container=row.physical_container;trace.save(ignore_permissions=True)
        frappe.db.set_value(DT,row.name,'material_trace_line',line.name)
        record('Output Declaration Bound to Draft',cycle=row.kanban_cycle,reference_doctype=DT,reference_name=row.name,qty=row.qty,
            operator=profile.employee,operator_session=session.name,terminal_user=session.terminal_user,
            payload={'stock_entry':entry.name,'trace_line':line.name},idempotency_key=canonical_key('output-declaration-bound',row.name,entry.name))
    return len(declarations)


def authorize_posting(entry,profile,session):
    if installed() and entry.purpose=='Manufacture' and frappe.db.exists(DT,{'stock_entry':entry.name,'status':'Bound to Draft'}):
        _supervisor(profile)
        frappe.local.station_output_posting_actor={'entry':entry.name,'operator':profile.employee,'operator_session':session.name}


def validate_receipt(doc,method=None):
    if not installed() or doc.get('purpose')!='Manufacture' or not doc.get('work_order'):return
    if not frappe.db.get_value('Work Order',doc.work_order,'cfg_kanban_cycle'):return
    order,cycle,master=_order(doc.work_order,lock=True)
    rows=[row for row in _declarations(doc.work_order,True) if row.status in ACTIVE]
    if not rows:return
    if frappe.db.sql('select name from `tabJob Card` where work_order=%s and docstatus<2 and status!=%s for update',(doc.work_order,'Completed')):
        frappe.throw('Complete all Job Cards before posting station-declared output')
    _operation,jobs=_final_jobs(order,current=True)
    if sum(flt(row.qty) for row in rows)+flt(order.produced_qty)>sum(flt(job.total_completed_qty) for job in jobs)+EPS:
        frappe.throw('Pending declarations exceed the current final-operation good output; reconcile before posting')
    actor=getattr(frappe.local,'station_output_posting_actor',{}) or {}
    if actor.get('entry')!=doc.name and not set(frappe.get_roles())&{'Stock Manager','Manufacturing Manager','System Manager'}:
        frappe.throw('A Supervisor must review and submit station-declared output')
    selected=[row for row in rows if row.stock_entry==doc.name and row.status=='Bound to Draft']
    if not selected:frappe.throw('Adopt pending station declarations into this Manufacture Draft before posting')
    from cfg_kanban.services.production_trace import _get_trace
    trace=_get_trace(doc.name);lines={line.name:line for line in trace.lines} if trace else {}
    output_qty=sum(flt(row.transfer_qty or row.qty) for row in doc.items if row.t_warehouse and not row.s_warehouse and row.item_code==selected[0].item_code)
    if abs(output_qty-sum(flt(row.qty) for row in selected))>EPS:frappe.throw('Receipt quantity must equal its declared bundle total')
    for row in selected:
        line=lines.get(row.material_trace_line)
        if not line or line.status!='Pending' or line.direction!='Output' or abs(flt(line.qty)-flt(row.qty))>EPS or line.pending_tag_code!=(row.tag_code or row.container_code) or (line.physical_container or None)!=(row.physical_container or None):
            frappe.throw('A declared output trace line changed or was cancelled; reconcile declarations before posting')


def confirm_receipt(doc):
    if not installed() or doc.get('purpose')!='Manufacture':return
    from cfg_kanban.services.production_trace import _get_trace
    trace=_get_trace(doc.name);lines={line.name:line for line in trace.lines} if trace else {}
    for row in frappe.get_all(DT,filters={'stock_entry':doc.name,'status':'Bound to Draft'},fields=['name','material_trace_line','qty','kanban_cycle'],limit_page_length=0):
        line=lines.get(row.material_trace_line)
        if not line or line.status!='Confirmed' or not line.handling_unit:frappe.throw('Declared output was not activated by native submission')
        frappe.db.set_value(DT,row.name,{'status':'Posted','handling_unit':line.handling_unit,'active_tag_key':None,'active_container_key':None})
        actor=getattr(frappe.local,'station_output_posting_actor',{}) or {}
        record('Declared Output Posted',cycle=row.kanban_cycle,reference_doctype=DT,reference_name=row.name,qty=row.qty,
            operator=actor.get('operator'),operator_session=actor.get('operator_session'),terminal_user=frappe.session.user,
            payload={'stock_entry':doc.name,'handling_unit':line.handling_unit},idempotency_key=canonical_key('declared-output-posted',row.name,doc.name))


def reverse_receipt(doc):
    if not installed():return
    for row in frappe.get_all(DT,filters={'stock_entry':doc.name,'status':'Posted'},fields=['name','qty','kanban_cycle'],limit_page_length=0):
        frappe.db.set_value(DT,row.name,{'status':'Voided','active_tag_key':None,'active_container_key':None})
        record('Declared Output Voided',cycle=row.kanban_cycle,reference_doctype=DT,reference_name=row.name,qty=row.qty,
            terminal_user=frappe.session.user,payload={'cancelled_stock_entry':doc.name},idempotency_key=canonical_key('declared-output-voided',row.name,doc.name))


def protect_draft_delete(doc,method=None):
    if installed() and frappe.db.exists(DT,{'stock_entry':doc.name,'status':'Bound to Draft'}):
        frappe.throw('Cancel the bound output declarations with a Supervisor reason before discarding/deleting this Draft')


@frappe.whitelist()
def cancel_declaration(declaration_name,reason,event_token,operator_session_token=None):
    row=frappe.get_doc(DT,declaration_name)
    card_scan=frappe.db.get_value('CFG Kanban Card',row.station_card,'card_number')
    card,profile,session=_station(card_scan,operator_session_token,'report_progress')
    snapshot=frappe.parse_json(row.source_snapshot or '{}')
    require_operator(operator_session_token,'report_progress',operation=snapshot.get('operation'),workstation=row.workstation)
    if profile.employee!=row.operator:_supervisor(profile)
    _order(row.work_order,lock=True);row.reload()
    reason=str(reason or '').strip()
    if not reason or not event_token:frappe.throw('A cancellation reason and stable token are required')
    cancel_key=canonical_key('cancel-output-declaration',row.name,event_token)
    cancel_request=canonical_key('cancel-output-request',row.name,reason)
    if row.status=='Cancelled':
        if row.get('cancel_action_key')!=cancel_key or row.get('cancel_request_fingerprint')!=cancel_request:
            frappe.throw('This declaration was already cancelled; retry only its original cancellation data')
        return {'name':row.name,'duplicate':True}
    if row.status=='Bound to Draft':
        _supervisor(profile)
        from cfg_kanban.services.production_trace import cancel_trace_line
        frappe.local.cancelling_output_declaration=row.name
        try:
            cancel_trace_line(row.stock_entry,row.material_trace_line,operator_session_token=operator_session_token,kanban_card=frappe.db.get_value('CFG Kanban Cycle',row.kanban_cycle,'kanban_card'))
        finally:
            frappe.local.cancelling_output_declaration=None
    elif row.status!='Declared':frappe.throw('Posted output must use controlled ERP receipt cancellation')
    for code in sorted(filter(None,[row.tag_code,row.container_code])):reservation(code,row.stock_entry,row.name)
    frappe.db.set_value(DT,row.name,{'status':'Cancelled','active_tag_key':None,'active_container_key':None,'cancelled_on':now_datetime(),'cancelled_by':profile.employee,'cancel_action_key':cancel_key,'cancel_request_fingerprint':cancel_request})
    if row.physical_container:
        if frappe.db.get_value('CFG Kanban Handling Unit',row.physical_container,'movement_state')!='Reserved':
            frappe.throw('The reserved bin state changed; reconcile it before cancelling this declaration')
        frappe.db.set_value('CFG Kanban Handling Unit',row.physical_container,'movement_state',row.previous_container_state or 'Empty')
    record('Output Declaration Cancelled',cycle=row.kanban_cycle,reference_doctype=DT,reference_name=row.name,notes=reason,operator=profile.employee,operator_session=session.name,
        terminal_user=session.terminal_user,idempotency_key=cancel_key)
    return {'name':row.name,'duplicate':False}


@frappe.whitelist()
def classify_output_identity(station_scan,work_order,scan_value,operator_session_token=None):
    card,_profile,_session=_station(station_scan,operator_session_token,'report_progress')
    order,cycle,master=_order(work_order)
    _validate_order(order,cycle,master,card)
    info=availability(order,master,card.current_station)
    require_operator(operator_session_token,'report_progress',operation=info['operation'],workstation=card.current_station)
    if info['station_good_qty']<=EPS:frappe.throw('No reported final-operation good output belongs to this station')
    code=canonical_output_code(normalize_physical_code(scan_value));identity=resolve_logistics_scan(code)
    if identity and identity.get('identity_type')=='Handling Unit':
        from cfg_kanban.services.production_trace import _production_output_container
        unit=frappe.get_doc('CFG Kanban Handling Unit',identity['name'])
        if unit.tag_kind!='Reusable Container':frappe.throw('Use an unused preprinted main tag for new finished output')
        _production_output_container(unit.handling_unit_id,order.company,master.destination_warehouse or order.fg_warehouse)
        return {'kind':'bin','code':unit.handling_unit_id}
    from cfg_kanban.services.production_trace import _validate_unused_main_tag
    _validate_unused_main_tag(code)
    if frappe.db.sql('select name from `tabCFG Kanban Output Declaration` where active_tag_key=%s',identity_key(code)):
        frappe.throw('This output tag is already reserved by a declaration')
    return {'kind':'tag','code':code}


def protect_trace_line_cancel(stock_entry,trace_line):
    if not installed():return
    rows=frappe.db.sql("select name from `tabCFG Kanban Output Declaration` where stock_entry=%s and material_trace_line=%s and status='Bound to Draft' for update",(stock_entry,trace_line))
    if rows and rows[0][0]!=getattr(frappe.local,'cancelling_output_declaration',None):
        frappe.throw('Cancel this output declaration from the station action, with a Supervisor reason; its trace and identity reservations must be released together')


def pending_identity(scan):
    if not installed():return None
    rows=frappe.db.sql("select name,work_order,item_code,stock_uom,qty,workstation,status,tag_code,container_code from `tabCFG Kanban Output Declaration` where active_tag_key=%s or active_container_key=%s",(identity_key(scan),identity_key(scan)),as_dict=True)
    return dict(rows[0]) if rows else None
