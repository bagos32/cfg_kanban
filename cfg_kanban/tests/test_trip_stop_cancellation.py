"""Actual Trip/stock/receipt behavior offline; native transaction and ERP acceptance are separate."""
import datetime,json,sqlite3,sys,types,unittest
from unittest.mock import patch
from cfg_kanban.tests import test_trip_sequence as seq
from cfg_kanban.tests import test_driver_route_actions as driver
from cfg_kanban.tests import test_office_delivery_trip as office
from cfg_kanban.tests.test_vehicle_overview import Row,load
from cfg_kanban.tests.test_container_repacking import functions
STOCK='CFG Kanban Cancelled Stop Stock';REQUEST='CFG Kanban Route Change Request'

def module(name,path,**values):
    result=types.ModuleType('cfg_kanban.services.'+name);result.__dict__.update(values);load(path,result.__dict__);return result

class TestStopCancellation(unittest.TestCase):
    def setUp(self):
        self.b=seq.TestTripSequence();self.b.setUp();self.addCleanup(self.b.doCleanups)
        self.a=self.b.a;self.data=self.a.data;self.trip=self.a.trip;self.op=self.a.operator;self.f=self.a.b.frappe
        self.f._dict=Row;self.f.flags=Row();self.f.ValidationError=ValueError;self.ledgers={};self.stock_erp=20;self.now=datetime.datetime(2026,11,22,14)
        self.op.responsibilities.append(office.Doc(responsibility='Dispatch'))
        old=self.f.get_doc
        def persist(doc,**kw):
            for n,row in enumerate(doc.get('cancelled_stock') or [],1):
                row.update(doctype=STOCK,parent=doc.name,parenttype=REQUEST,parentfield='cancelled_stock',name=doc.name+'-STOCK-'+str(n));self.data.setdefault(STOCK,{})[row.name]=row
            return doc
        def get_doc(dt,name=None,**kw):
            doc=old(dt,**kw) if isinstance(dt,dict) else old(dt,name,**kw)
            if doc.doctype==REQUEST:object.__setattr__(doc,'save',lambda **args:persist(doc,**args))
            return doc
        self.f.get_doc=get_doc;self.f.db.get_values=self.values;self.f.db.get_value=self.value;self.f.db.set_value=self.set_value
        self.f.get_all=lambda dt,filters=None,pluck=None,fields=None,**kw:[r[pluck] if pluck else r for r in self.data.get(dt,{}).values() if self.matches(r,filters or {})]
        self.f.db.exists=lambda dt,v:any(self.matches(r,v) for r in self.data.get(dt,{}).values()) if isinstance(v,dict) else v in self.data.get(dt,{})
        self.f.as_json=lambda value:json.dumps(value,default=str)
        common=dict(frappe=self.f,json=json,cint=lambda v:int(v or 0),flt=lambda v:float(v or 0),now_datetime=lambda:self.now,canonical_key=driver.canonical,record=lambda *a,**k:None,post_quantity_event=self.ledger)
        self.plan=load('services/dispatch_planning.py',dict(common));self.plan['_lock_erp_bin']=lambda *a:None;self.plan['_untagged_available']=lambda *a,**k:self.stock_erp
        self.prepared=load('services/dispatch_fulfilment.py',dict(common))
        self.review=module('dispatch_reconciliation','services/dispatch_reconciliation.py',**common);self.review._planning=lambda:Row(**self.plan);self.review._fulfilment=lambda:Row(**self.prepared)
        self.stock=module('cancelled_stop_stock','services/cancelled_stop_stock.py',**common)
        self.cancel=module('trip_stop_cancellation','services/trip_stop_cancellation.py',**common)
        self.cancel._actions=lambda:Row(**self.a.ns);self.cancel._sequence=lambda:self.b.seq;self.cancel._planning=lambda:Row(**self.plan);self.cancel._prepared=lambda:Row(**self.prepared);self.cancel._custody=lambda:self.stock
        self.sheets=types.ModuleType('cfg_kanban.services.route_sheets');self.sheets._status=lambda row:dict(state=row.state or 'Planned');self.sheets.lock_plan_route_scope=lambda *a:None
        outcomes=types.ModuleType('cfg_kanban.services.driver_delivery_outcomes')
        def resalable(row):
            if row.handling_unit:
                unit=self.data['CFG Kanban Handling Unit'][row.handling_unit]
                if unit.quality_state!='Released':raise ValueError('Quality hold')
                if unit.expiry_date and unit.expiry_date<'2026-11-22':raise ValueError('Expired')
        outcomes._assert_resalable=resalable
        p=patch.dict(sys.modules,{m.__name__:m for m in (self.stock,self.cancel,self.review,self.sheets,outcomes)});p.start();self.addCleanup(p.stop)
        for n,qty in ((1,4),(2,2)):
            self.data['CFG Kanban Dispatch Allocation']['ALLOC'+str(n)].update(handling_unit='HU'+str(n),visible_code='RM'+str(n),load_confirmed=1,movement_manifest='MAN'+str(n))
            plan=self.data[office.PLAN]['PLAN'+str(n)];plan.update(prepared_stock_commitment=1,dispatch_responsibility='Dispatch',customer_address='A'+str(n));plan.lines[0].loaded_qty=qty
            self.a.b.add('CFG Kanban Handling Unit','HU'+str(n),handling_unit_id='RM'+str(n),item_code='ITEM'+str(n),batch_no='BATCH',stock_uom='Nos',inventory_company='A',current_warehouse='LORRY',current_qty=qty,reserved_qty=0,available_qty=qty,identity_state='Active',quality_state='Released',expiry_date='2027-01-01',process_certificate_set='CERT'+str(n))
        self.b.start(True);self.saved=self.trip.driver_route_snapshot_json;self.business=self.a.ns['_core'](self.trip)
    def matches(self,row,filters):
        for key,value in filters.items():
            if isinstance(value,list):
                op,want=value
                if op=='in' and row.get(key) not in want:return False
                if op=='not in' and row.get(key) in want:return False
                if op=='!=' and row.get(key)==want:return False
            elif row.get(key)!=value:return False
        return True
    def values(self,dt,filters,fields,**kw):return [office.Doc({key:r.get(key) for key in fields}) for r in self.data.get(dt,{}).values() if self.matches(r,filters)]
    def value(self,dt,name,field,**kw):
        if dt=='Bin':return self.stock_erp
        rows=self.data.get(dt,{})
        doc=next((r for r in rows.values() if self.matches(r,name)),None) if isinstance(name,dict) else rows.get(name)
        return (office.Doc({k:doc.get(k) for k in field}) if isinstance(field,list) else doc.get(field)) if doc else None
    def set_value(self,dt,name,key,value=None,**kw):
        targets=[r for r in self.data.get(dt,{}).values() if self.matches(r,name)] if isinstance(name,dict) else ([self.data[dt][name]] if name in self.data.get(dt,{}) else [r for plan in self.data.get(office.PLAN,{}).values() for r in plan.lines if r.name==name])
        for row in targets:row.update(key if isinstance(key,dict) else {key:value})
    def ledger(self,**values):
        key=values['idempotency_key']
        if key in self.ledgers:return self.ledgers[key]
        unit=self.data['CFG Kanban Handling Unit'][values['source_handling_unit']];delta=values['qty']*(1 if values['event_type']=='Reserve' else -1)
        if unit.reserved_qty+delta<-0.000001 or unit.reserved_qty+delta>unit.current_qty+0.000001:raise ValueError('Reservation balance invalid')
        unit.reserved_qty+=delta;unit.available_qty=unit.current_qty-unit.reserved_qty;row=office.Doc(name='LEDGER'+str(len(self.ledgers)+1),**values);self.ledgers[key]=row;return row
    def supervisor(self):self.b.supervisor();self.op.can_complete=1
    def context(self,n=0):return self.a.ns['driver_action_context'](self.trip.name,'TOKEN',stop_key=self.b.keys[n],operation='Cancel Customer Stop')
    def request_args(self,action,c,**payload):
        self.b.n+=1;return dict(trip_name=self.trip.name,action=action,event_token='CANCEL'+str(self.b.n),operator_session_token='TOKEN',expected_revision=c['revision'],scope_hash=c['scope_hash'],stop_key=c.get('stop_key'),payload=payload)
    def direct(self,n=0,disposition='Keep Reserved for Return'):
        c=self.context(n);self.last=self.request_args('Cancel Customer Stop',c,reason='Customer closed',goods_hash=c['setup']['goods_hash'],stock_disposition=disposition);return self.a.perform(self.last)
    def request(self,n=0):
        c=self.context(n);self.last=self.request_args('Request Stop Cancellation',c,reason='Customer asks to cancel visit');self.a.perform(self.last);return self.data[REQUEST][self.trip.route_change_request]
    def approve(self,row,decision='Approve',disposition='Keep Reserved for Return'):
        c=self.a.ns['driver_action_context'](self.trip.name,'TOKEN',operation='Review Route Change',outcome_name=row.name)
        self.last=self.request_args('Decide Route Change',c,request_name=row.name,decision=decision,reason='Reviewed cancellation',goods_hash=c['setup'].get('goods_hash'),stock_disposition=disposition);return self.a.perform(self.last)
    def test_driver_only_requests_and_supervisor_rejection_changes_no_stock(self):
        row=self.request();self.assertEqual(row.state,'Pending');self.assertFalse(self.trip.stops[0].cancellation_request);self.assertFalse(self.ledgers)
        with self.assertRaisesRegex(ValueError,'awaits Supervisor'):self.a.ns['_target'](self.trip,dict(stop_key=self.b.keys[0]),json.loads(self.saved))
        self.supervisor();self.approve(row,'Reject');self.assertEqual(row.state,'Rejected');self.assertFalse(self.trip.stops[0].cancellation_request);self.assertFalse(self.ledgers)
    def test_draft_request_is_visible_and_requester_can_withdraw_before_departure(self):
        self.trip.update(state='Draft',driver_route_state='Not Started',driver_route_snapshot_json=None)
        row=self.request();view=self.a.v.read()
        self.assertEqual(view['route_sequence']['request']['request_type'],'Cancel Customer Stop');self.assertTrue(view['route_sequence']['request']['can_cancel'])
        c=self.a.ns['driver_action_context'](self.trip.name,'TOKEN',operation='Cancel Route Change')
        self.a.perform(self.request_args('Cancel Route Change',c,request_name=row.name,reason='Customer can receive after all'))
        self.assertEqual(row.state,'Cancelled');self.assertFalse(self.trip.stops[0].cancellation_request);self.assertFalse(self.ledgers)

    def test_enforced_route_keeps_supervisor_approval_and_cannot_supersede_cancellation(self):
        self.trip.sequence_policy='Planned Order'
        self.trip.driver_route_snapshot_json=json.dumps(self.a.ns['_execution'](self.trip,self.op,self.a.v.read()),default=str)
        row=self.request()
        c=self.b.context()
        with self.assertRaisesRegex(ValueError,'customer cancellation'):
            self.b.execute('Request Route Change',dict(order=list(reversed(self.b.keys)),reason='New order'),c)
        self.assertEqual(row.state,'Pending');self.supervisor();self.approve(row)
        saved=json.loads(self.trip.driver_route_snapshot_json);self.a.ns['_target'](self.trip,dict(stop_key=self.b.keys[1]),saved)
        with self.assertRaisesRegex(ValueError,'next stop'):self.a.ns['_target'](self.trip,dict(stop_key=self.b.keys[2]),saved)

    def test_remaining_customer_still_checks_a_shared_route_sheet_revision(self):
        sheet=self.a.v.sheet(order=(1,2));sheet.revision=1
        for n,row in enumerate(sheet.stops):row.row_key='ROW'+str(n)
        self.trip.driver_route_snapshot_json=json.dumps(self.a.ns['_execution'](self.trip,self.op,self.a.v.read()),default=str)
        self.supervisor();self.direct(disposition='Release for Same-trip Sale')
        original=json.loads(self.trip.driver_route_snapshot_json)
        self.assertEqual(driver.canonical('s',self.a.ns['_execution'](self.trip,self.op,self.a.v.read())),driver.canonical('s',original))
        sheet.revision+=1
        with self.assertRaisesRegex(ValueError,'execution route changed'):self.a.begin_stop(2)

    def test_loaded_hold_keeps_original_loading_order_and_certificate_identity(self):
        self.supervisor();result=self.direct();row=self.data[REQUEST][self.trip.route_change_request];unit=self.data['CFG Kanban Handling Unit']['HU1']
        self.assertTrue(result['result']['stop_cancelled']);self.assertEqual((unit.current_qty,unit.reserved_qty,unit.available_qty),(4,4,0));self.assertEqual((unit.process_certificate_set,unit.expiry_date),('CERT1','2027-01-01'))
        self.assertEqual(row.state,'Approved');self.assertEqual(self.trip.driver_route_snapshot_json,self.saved);self.assertEqual(self.a.ns['_core'](self.trip),self.business);self.assertEqual(self.data['Stock Entry']['SE1'].docstatus,1)
        self.assertFalse(self.data.get(driver.views.NOTE));self.assertEqual(self.data['Sales Order']['SO1'].docstatus,1);self.assertEqual(self.data[office.PLAN]['PLAN1'].prepared_stock_commitment,1)
    def test_other_customers_remain_deliverable_and_frozen_source_stays_identical(self):
        self.supervisor();self.direct(disposition='Release for Same-trip Sale');view=self.a.v.read()
        self.assertEqual(view['next_stop_key'],self.b.keys[1]);self.assertNotIn(self.b.keys[0],[r['stop_key'] for r in view['stops']]);self.assertEqual(len(view['cancelled_stops']),1);self.assertEqual(view['total_stops'],2)
        self.assertEqual(driver.canonical('s',self.a.ns['_execution'](self.trip,self.op,view)),driver.canonical('s',json.loads(self.saved)))
        self.a.act(n=2,customer_scan='QR2');self.a.act(n=2);self.a.act(n=2,required_erp_inputs={'parent':{},'tables':{}});self.a.act(n=2);self.a.proof_submit(n=2);self.assertTrue(self.trip.stops[1].driver_completed_on)
    def test_release_leaves_physical_stock_in_lorry_and_e5_subtracts_exact_release(self):
        self.supervisor();self.direct(disposition='Release for Same-trip Sale');unit=self.data['CFG Kanban Handling Unit']['HU1'];plan=self.data[office.PLAN]['PLAN1']
        self.assertEqual((unit.current_warehouse,unit.current_qty,unit.reserved_qty),('LORRY',4,0));self.assertFalse(self.ledgers);self.assertEqual(plan.prepared_stock_commitment,0)
        row=self.review._balances(plan)[0];self.assertEqual((row['cancelled_released_qty'],row['remaining_qty']),(4,0))
    def test_replay_is_exact_and_does_not_repeat_reservations(self):
        self.supervisor();first=self.direct();request=dict(self.last);self.assertEqual(self.a.perform(request),first);self.assertEqual(len(self.ledgers),1)
        changed=dict(request,payload=dict(request['payload'],stock_disposition='Release for Same-trip Sale'))
        with self.assertRaisesRegex(ValueError,'different original'):self.a.perform(changed)
    def test_driver_cannot_force_direct_cancellation(self):
        with self.assertRaises(PermissionError):self.direct()
        self.assertFalse(self.trip.stops[0].cancellation_request);self.assertFalse(self.ledgers)
    def test_untagged_hold_uses_plan_commitment_without_inventing_a_tag(self):
        self.data['CFG Kanban Dispatch Allocation']['ALLOC1'].update(allocation_kind='Untagged ERP Stock',handling_unit=None,visible_code=None)
        self.trip.driver_route_snapshot_json=json.dumps(self.a.ns['_execution'](self.trip,self.op,self.a.v.read()),default=str)
        self.supervisor();self.direct();row=self.data[REQUEST][self.trip.route_change_request].cancelled_stock[0]
        self.assertIsNone(row.handling_unit);self.assertEqual(row.qty,4);self.assertFalse(self.ledgers);self.assertEqual(self.data[office.PLAN]['PLAN1'].prepared_stock_commitment,1)
    def test_stale_preview_rejects_before_direct_decision_creation(self):
        self.supervisor();c=self.context();self.data['CFG Kanban Handling Unit']['HU1'].expiry_date='2027-02-01'
        with self.assertRaisesRegex(ValueError,'changed'):self.a.perform(self.request_args('Cancel Customer Stop',c,reason='Closed',goods_hash=c['setup']['goods_hash']))
        self.assertFalse(self.trip.route_change_request);self.assertFalse(self.ledgers)
    def test_delivery_and_proof_history_requires_existing_recovery(self):
        self.a.b.add(driver.views.SESSION,'DELIVERING',dispatch_plan='PLAN1',state='Delivered');self.supervisor()
        with self.assertRaisesRegex(ValueError,'delivery history'):self.context()
        self.assertFalse(self.ledgers)
    def test_other_active_customer_blocks_approval_without_losing_pending_request(self):
        row=self.request();self.trip.driver_active_stop_key=self.b.keys[1];self.supervisor()
        with self.assertRaisesRegex(ValueError,'active customer'):self.approve(row)
        self.assertEqual(row.state,'Pending');self.assertFalse(self.ledgers)
    def test_quality_hold_expiry_and_moved_stock_cannot_be_silently_released(self):
        self.supervisor();unit=self.data['CFG Kanban Handling Unit']['HU1'];unit.quality_state='Hold'
        with self.assertRaisesRegex(ValueError,'Quality'):self.direct(disposition='Release for Same-trip Sale')
        unit.quality_state='Released';unit.current_warehouse='OTHER'
        with self.assertRaisesRegex(ValueError,'moved'):self.context()
    def test_native_company_and_warehouse_denials_do_not_mutate_stock(self):
        self.supervisor();self.data['Company']['A']._denied=True
        with self.assertRaises(PermissionError):self.context()
        self.data['Company']['A']._denied=False;self.data['Warehouse']['LORRY']._denied=True
        with self.assertRaises(PermissionError):self.context()
        self.assertFalse(self.ledgers)
    def test_last_cancel_ends_route_without_inventing_delivery_or_e5_settlement(self):
        self.trip.stops[1].driver_completed_on=self.now;self.trip.stops[2].driver_completed_on=self.now;self.supervisor();self.direct()
        self.assertEqual(self.trip.driver_route_state,'Completed');self.assertIsNone(self.trip.driver_active_vehicle_key);self.assertFalse(self.trip.stops[0].driver_completed_on);self.assertEqual(self.data[office.PLAN]['PLAN1'].state,'Loaded')
    def test_reserved_return_requires_recovery_or_same_plan_overnight(self):
        self.supervisor();self.direct();plan=self.data[office.PLAN]['PLAN1']
        with self.assertRaisesRegex(ValueError,'reserved for return'):self.stock.assert_review_action(plan,'Close Trip - Stock Stays')
        self.stock.assert_review_action(plan,'Continue Same Plan Overnight');self.stock.assert_review_action(plan,'Returned to Warehouse')
    def test_unused_recovery_cancel_restores_hold_once_received_goods_become_available_at_destination(self):
        self.supervisor();self.direct();row=self.data[REQUEST][self.trip.route_change_request].cancelled_stock[0];unit=self.data['CFG Kanban Handling Unit']['HU1']
        manifest=office.Doc(name='RECOVER',source_company='A',source_warehouse='LORRY',destination_warehouse='SOURCE',lines=[office.Doc(dispatch_allocation='ALLOC1',dispatch_qty=4)])
        self.stock.recovery_adopt(manifest);self.assertEqual(unit.reserved_qty,0);self.stock.recovery_restore(manifest);self.stock.recovery_restore(manifest);self.assertEqual(unit.reserved_qty,4)
        manifest.name='RECOVER2';self.stock.recovery_adopt(manifest);unit.current_warehouse='SOURCE';self.stock.recovery_restore(manifest,True);self.stock.recovery_restore(manifest,True);self.assertEqual(row.stock_state,'Recovered');self.assertEqual(unit.reserved_qty,0)
    def test_supervisor_unloads_only_held_tag_from_mixed_container_without_releasing_its_hold(self):
        self.supervisor();self.direct();unit=self.data['CFG Kanban Handling Unit']['HU1'];unit.reload=lambda:unit
        container=self.a.b.add('CFG Kanban Handling Unit','BIN',handling_unit_id='BIN',reusable_container_role='Logistics Container');container.reload=lambda:container
        first=self.a.b.add('CFG Kanban Container Content','MEM1',container_handling_unit='BIN',content_handling_unit='HU1',state='Loaded')
        other=self.a.b.add('CFG Kanban Container Content','MEM2',container_handling_unit='BIN',content_handling_unit='HU2',state='Loaded')
        ns=dict(frappe=self.f,flt=lambda v:float(v or 0),_=lambda v:v,now_datetime=lambda:self.now,
            canonical_key=driver.canonical,_authorize=lambda *a,**k:dict(operator=self.op.employee,operator_session='OS',terminal_user='terminal'),
            _resolve_container=lambda scan:container,_resolve_content=lambda scan,**kw:unit,_lock_units=lambda *a:None,
            assert_container_not_in_open_manifest=lambda *a:None,assert_container_not_in_open_delivery=lambda *a:None,
            _container_result=lambda *a,**kw:dict(qty=unit.current_qty,reserved=unit.reserved_qty),record=lambda *a,**kw:None)
        functions('services/container_contents.py',{'unload_content_tag'},ns)
        ns.update(_authorize=lambda *a,**k:dict(operator=self.op.employee,operator_session='OS',terminal_user='terminal'),_container_result=lambda *a,**kw:dict(qty=unit.current_qty,reserved=unit.reserved_qty))
        auth=types.SimpleNamespace(require_operator=lambda *a,**kw:(self.op,office.Doc(name="OS")))
        sequence=types.SimpleNamespace(_supervisor=self.b.seq._supervisor)
        args=('BIN','RM1','Remove tagged goods for return','UNLOAD','TOKEN')
        with patch.dict(sys.modules,{'cfg_kanban.services.operator_auth':auth,'cfg_kanban.services.trip_sequence':sequence}):
            self.op.can_override=0
            with self.assertRaises(PermissionError):ns['unload_content_tag'](*args)
            self.op.can_override=1
            result=ns['unload_content_tag'](*args);again=ns['unload_content_tag'](*args)
        self.assertEqual(result,again);self.assertEqual(first.state,'Unloaded');self.assertEqual(other.state,'Loaded')
        self.assertEqual((unit.current_qty,unit.reserved_qty,unit.available_qty),(4,4,0));self.assertEqual(unit.current_warehouse,'LORRY')
        self.assertEqual(unit.process_certificate_set,'CERT1');self.assertEqual(len(self.ledgers),1)

    def test_held_tag_unload_rejects_partial_unowned_or_recovery_reserved_stock(self):
        self.supervisor();self.direct();unit=self.data['CFG Kanban Handling Unit']['HU1']
        auth=types.SimpleNamespace(require_operator=lambda *a,**kw:(self.op,office.Doc(name="OS")))
        sequence=types.SimpleNamespace(_supervisor=self.b.seq._supervisor)
        row=self.data[REQUEST][self.trip.route_change_request].cancelled_stock[0]
        with patch.dict(sys.modules,{'cfg_kanban.services.operator_auth':auth,'cfg_kanban.services.trip_sequence':sequence}):
            for changes in ({'stock_state':'Recovery Reserved'},{'qty':3},{'parent':'OTHER'}):
                original=dict(row);row.update(changes)
                with self.assertRaises((ValueError,KeyError)):self.stock.assert_held_tag_unload(unit,'TOKEN')
                row.clear();row.update(original)
            with self.assertRaisesRegex(ValueError,'Supervisor'):self.stock.assert_held_tag_unload(unit,None)
        self.assertEqual(unit.reserved_qty,4)

    def test_loose_protection_uses_the_exact_batch_not_other_batch_stock(self):
        self.supervisor();self.direct();self.stock_erp=30
        counts=types.SimpleNamespace(_erp_balances=lambda *a,**kw:{('ITEM1','BATCH'):4,('ITEM1','OTHER'):26})
        movement=office.Doc(lines=[office.Doc(item_code='ITEM1',batch_no='BATCH',dispatch_qty=1)])
        with patch.dict(sys.modules,{'cfg_kanban.services.dispatch_planning':Row(**self.plan),'cfg_kanban.services.route_reconciliation':counts}):
            with self.assertRaisesRegex(ValueError,'reserved for return'):self.stock.assert_loose_movement('ITEM1','LORRY',1,movement)
            movement.lines[0].batch_no='OTHER';self.stock.assert_loose_movement('ITEM1','LORRY',1,movement)

    def test_ordinary_form_cannot_forge_clear_or_rewrite_cancellation(self):
        self.supervisor();self.direct();before=office.document(self.trip.as_dict());doc=office.document(before.as_dict());doc.stops[0].cancellation_request=None
        self.a.b.ns['_protect_driver_execution'](doc,before);self.assertTrue(doc.stops[0].cancellation_request);doc.orders[0].planned_qty+=1
        with self.assertRaisesRegex(ValueError,'cancelled stop retains'):self.a.b.ns['_protect_driver_execution'](doc,before)

    def test_driver_request_can_be_approved_after_other_information_visit_progress(self):
        row=self.request();key=self.b.keys[2]
        c=self.a.ns['driver_action_context'](self.trip.name,'TOKEN',stop_key=key)
        self.a.perform(self.request_args('Complete Stop',c,notes='Information collected'))
        self.supervisor();self.approve(row);self.assertEqual(row.state,'Approved');self.assertTrue(self.trip.stops[0].cancellation_request)
    def test_cancel_before_departure_releases_unused_reservation_and_other_customer_can_start(self):
        self.trip.update(driver_route_state='Not Started',driver_route_snapshot_json=None,driver_route_revision=0,driver_active_vehicle_key=None,driver_active_stop_key=None)
        plan=self.data[office.PLAN]['PLAN1'];plan.update(state='Ready for Vehicle',movement_manifest=None,vehicle_warehouse=None)
        source=self.data['CFG Kanban Dispatch Allocation']['ALLOC1'];source.update(state='Reserved',movement_manifest=None,load_confirmed=0,source_company='A',source_warehouse='SOURCE')
        unit=self.data['CFG Kanban Handling Unit']['HU1'];unit.update(current_warehouse='SOURCE',reserved_qty=4,available_qty=0)
        self.supervisor();self.direct();self.assertEqual(plan.state,'Cancelled');self.assertEqual(source.state,'Cancelled');self.assertEqual(unit.reserved_qty,0)
        self.assertFalse(self.data.get(STOCK));self.a.start();self.assertEqual(self.trip.driver_route_state,'In Progress');self.assertEqual(self.a.v.read()['next_stop_key'],self.b.keys[1])
    def test_pending_or_draft_loading_erp_work_is_not_automatically_cancelled(self):
        self.trip.update(driver_route_state='Not Started',driver_route_snapshot_json=None)
        plan=self.data[office.PLAN]['PLAN1'];plan.state='Loading'
        manifest=self.data['CFG Kanban Movement Manifest']['MAN1'];manifest.update(state='Prepared',dispatch_stock_entry=None,dispatch_command='PENDING')
        self.supervisor()
        with self.assertRaisesRegex(ValueError,'ERP work'):self.context()
        self.assertFalse(self.ledgers);self.assertEqual(plan.state,'Loading')
    def test_optional_visit_cancellation_keeps_shared_pool_and_other_repeated_visit(self):
        self.trip.update(driver_route_state='Not Started',driver_route_snapshot_json=None,open_route_plan='POOL')
        pool=self.a.b.add(office.PLAN,'POOL',office_delivery_trip=self.trip.name,company='A',plan_type='Open Route Stock',dispatch_responsibility='Dispatch',state='Loaded',vehicle_warehouse='LORRY',lines=[],route_stock_commitment=1)
        target=self.trip.stops[2]
        visit=self.a.b.add('CFG Kanban Route Stop','VISIT',dispatch_plan='POOL',office_delivery_trip=self.trip.name,office_stop_key=target.stop_key,customer_scan_point=target.customer_scan_point,customer=target.customer,customer_address=target.customer_address,state='Planned')
        other=self.a.b.add('CFG Kanban Route Stop','OTHER',dispatch_plan='POOL',office_delivery_trip=self.trip.name,office_stop_key='DIFFERENT',customer_scan_point=target.customer_scan_point,state='Planned')
        sales=module('trip_sales','services/trip_sales.py',frappe=self.f,json=json);sales._office=lambda:Row(_read=self.cancel._read)
        with patch.dict(sys.modules,{sales.__name__:sales}):
            self.supervisor();self.direct(2)
        self.assertEqual(visit.state,'Skipped');self.assertEqual(other.state,'Planned');self.assertEqual(pool.route_stock_commitment,1);self.assertFalse(self.data.get(STOCK))
    def test_untagged_generic_transfer_cannot_evict_held_stock(self):
        self.supervisor();self.direct();stock=self.data[REQUEST][self.trip.route_change_request].cancelled_stock[0]
        planning=types.ModuleType('cfg_kanban.services.dispatch_planning');planning._lock_erp_bin=lambda *a:None
        self.stock_erp=6;stock.batch_no=None
        with patch.dict(sys.modules,{planning.__name__:planning}):
            self.stock.assert_loose_movement('ITEM1','LORRY',2)
            with self.assertRaisesRegex(ValueError,'reserved for return'):self.stock.assert_loose_movement('ITEM1','LORRY',3)
        self.assertEqual(stock.stock_state,'Held for Return')
    def test_native_stock_entry_hook_rechecks_a_draft_prepared_before_the_hold(self):
        self.supervisor();self.direct();stock=self.data[REQUEST][self.trip.route_change_request].cancelled_stock[0]
        stock.batch_no=None;self.stock_erp=6
        manifest=self.a.b.add('CFG Kanban Movement Manifest','OLD-DRAFT',source_warehouse='LORRY',lines=[office.Doc(item_code='ITEM1',batch_no=None,line_kind='ERP Stock without Physical Tag',dispatch_qty=3)])
        document=office.Doc(doctype='Stock Entry',cfg_movement_manifest=manifest.name,cfg_transfer_stage='Direct')
        ns=load('services/logistics_stock_identity.py',dict(frappe=self.f))
        with patch.dict(sys.modules,{'cfg_kanban.services.dispatch_planning':Row(**self.plan)}):
            with self.assertRaisesRegex(ValueError,'reserved for return'):ns['validate_logistics_document'](document,'before_submit')
        self.assertEqual(stock.stock_state,'Held for Return')

    def test_changed_loading_identity_after_departure_is_rejected(self):
        source=self.data['CFG Kanban Dispatch Allocation']['ALLOC1'];source.batch_no='CHANGED';self.data['CFG Kanban Handling Unit']['HU1'].batch_no='CHANGED';self.supervisor()
        with self.assertRaisesRegex(ValueError,'frozen departure'):self.context()


class TestCancelledPreparation(unittest.TestCase):
    def setUp(self):
        from cfg_kanban.tests import test_trip_dispatch
        self.n=test_trip_dispatch.TestTripDispatch();self.n.setUp();self.addCleanup(self.n.doCleanups)
        self.n.generate()
    def persist_runtime(self):
        self.n.data[office.TRIP][self.n.trip.name]=office.document(self.n.trip.as_dict())
    def test_refresh_never_recreates_the_cancelled_customer_request(self):
        trip=self.n.trip;link=trip.dispatch_plans[0];original=link.dispatch_plan
        trip.stops[0].cancellation_request='DECISION';plan=self.n.data[office.PLAN][original]
        plan.db_set(dict(state='Cancelled',stop_cancellation='DECISION'))
        self.persist_runtime();self.n.generate(explicit=True)
        self.assertEqual([r.dispatch_plan for r in trip.dispatch_plans],[original]);self.assertEqual(len(self.n.plans()),2)
        self.assertEqual(plan.state,'Cancelled');self.assertFalse(self.n.office._source_rows(trip,self.n.office._plans(trip,current=True)))
        self.n.ledger.assert_not_called()
    def test_last_optional_visit_cancel_keeps_shared_pool_and_skipped_history(self):
        trip=self.n.trip;pool=trip.open_route_plan;trip.stops[1].cancellation_request='DECISION'
        visit=next(iter(self.n.data['CFG Kanban Route Stop'].values()));visit.db_set('state','Skipped')
        self.persist_runtime();self.n.generate(explicit=True)
        self.assertEqual(trip.open_route_plan,pool);self.assertEqual(len(self.n.plans()),2);self.assertEqual(visit.state,'Skipped')
        self.assertEqual(self.n.data[office.PLAN][pool].state,'Ready for Fulfilment');self.n.ledger.assert_not_called()


class TestCancelledAssignmentSQL(unittest.TestCase):
    def test_real_assignment_sql_frees_only_cancelled_claims(self):
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        db.executescript('''CREATE TABLE `tabCFG Kanban Delivery Trip` (name TEXT,state TEXT);
        CREATE TABLE `tabCFG Kanban Delivery Trip Order` (name TEXT,parent TEXT,parenttype TEXT,parentfield TEXT,stop_key TEXT,sales_order TEXT,sales_order_item TEXT,planned_qty REAL);
        CREATE TABLE `tabCFG Kanban Delivery Trip Stop` (parent TEXT,parenttype TEXT,parentfield TEXT,stop_key TEXT,cancellation_request TEXT);
        INSERT INTO `tabCFG Kanban Delivery Trip` VALUES ('T1','Planned'),('T2','Planned');
        INSERT INTO `tabCFG Kanban Delivery Trip Order` VALUES ('A1','T1','CFG Kanban Delivery Trip','orders','S1','SO','ROW',4),('A2','T2','CFG Kanban Delivery Trip','orders','S2','SO','ROW',2);
        INSERT INTO `tabCFG Kanban Delivery Trip Stop` VALUES ('T1','CFG Kanban Delivery Trip','stops','S1','APPROVED'),('T2','CFG Kanban Delivery Trip','stops','S2',NULL);''')
        def sql(query,params,**kw):
            cursor=db.execute(query.replace('%s','?'),params);names=[r[0] for r in cursor.description];return [Row(zip(names,r)) for r in cursor.fetchall()]
        ns=load('services/delivery_trips.py',dict(frappe=Row(db=Row(sql=sql,table_exists=lambda *_:True)),flt=lambda v:float(v or 0)));ns['_delivered_assignments']=lambda *a,**k:{}
        self.assertEqual(ns['_assignments'](['SO']),{('SO','ROW'):2});db.execute("UPDATE `tabCFG Kanban Delivery Trip Stop` SET cancellation_request=NULL WHERE parent='T1'");self.assertEqual(ns['_assignments'](['SO']),{('SO','ROW'):6})

if __name__=='__main__':unittest.main()
