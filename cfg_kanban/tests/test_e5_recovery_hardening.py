"""Real E5 orchestration/validators over explicit transaction and MVCC doubles.

Savepoint rollback here is an in-memory model, not MariaDB transaction acceptance.
Opt-in native tests and the combined acceptance record are separate evidence.
"""
import copy
import datetime
import json
import unittest
from unittest.mock import Mock
from cfg_kanban.tests.test_trip_continuation import FollowOnFixture,Doc,Row,load,TRIP,PLAN,ALLOC,CASE


class TestE5RecoveryHardening(FollowOnFixture,unittest.TestCase):
    def settled_unused_child(self,returns=False):
        if returns:self.case()
        result=self.create(self.payload(returns=['RETURN'] if returns else [],confirmed_returns=['RETURN'] if returns else []))
        child=self.data[TRIP][result['trip']]
        for link in child.dispatch_plans:self.data[PLAN][link.dispatch_plan].update(state='Reconciled',dispatch_review_state='Settled',prepared_stock_commitment=0)
        child.flags=Doc();return child
    def assert_original(self,count,cases=None):
        self.assertEqual(len(self.data[TRIP]),count)
        self.assertIsNone(self.source.follow_on_trip)
        self.assertFalse(self.data.get(ALLOC));self.assertFalse(self.quantity_events)
        self.assertFalse(any(r['event']=='Follow-on Delivery Trip Created' for r in self.events))
        if cases:
            case=self.data[CASE]['RETURN'];self.assertIsNone(case.custody_trip);self.assertIsNone(case.custody_handover_json)
    def test_unused_child_can_be_cancelled_then_replaced_after_settlement(self):
        child=self.settled_unused_child();self.source=child
        context=self.context();self.assertTrue(context['unused_follow_on']);self.assertEqual(context['blockers'],[])
        child.state='Cancelled';child.closure_reason='Lorry replacement before departure';child.save()
        context=self.context();self.assertEqual(context['blockers'],[])
        row=child.orders[0].name;p=self.payload(orders=[dict(source_row=row,qty=4)],stock=[dict(self.payload()['stock'][0],source_row=row)])
        result=self.create(p,token='REPLACEMENT')
        self.assertEqual(child.state,'Cancelled');self.assertEqual(self.data[TRIP][result['trip']].follow_on_of,child.name)
        self.assertEqual(len(self.data[TRIP]),3)
    def test_settled_unused_child_hands_returns_onward_without_a_fake_start_or_qc_receipt(self):
        child=self.settled_unused_child(returns=True);self.source=child
        row=child.orders[0].name
        payload=self.payload(orders=[dict(source_row=row,qty=4)],stock=[dict(self.payload()['stock'][0],source_row=row)],returns=['RETURN'],confirmed_returns=['RETURN'])
        result=self.create(payload,token='SECOND-RELIEF')
        self.assertEqual(child.state,'Closed');self.assertIsNone(child.driver_route_started_on)
        self.assertEqual(self.data[CASE]['RETURN'].custody_trip,result['trip']);self.assertIsNone(self.data[CASE]['RETURN'].received_on)
        self.assertEqual(len(json.loads(self.data[CASE]['RETURN'].custody_handover_json)),2)

    def test_cancel_unused_child_releases_office_so_claim_but_not_old_return_custody(self):
        child=self.settled_unused_child(returns=True);self.source=child
        child.state='Cancelled';child.closure_reason='Unused load'
        with self.assertRaisesRegex(ValueError,'await QC receipt'):child.save()
        self.data[CASE]['RETURN'].received_on='2026-11-25 12:00:00';child.save()
        elsewhere=self.g.office._assignments(['SO1'],current=True)
        self.assertEqual(elsewhere.get(('SO1','ROW1'),0),0)
        self.assertEqual(self.data[CASE]['RETURN'].custody_trip,child.name)
    def test_forged_or_incomplete_follow_on_origin_does_not_bypass_start_gate(self):
        self.source.follow_on_of='FAKE';self.source.driver_route_started_on=None
        self.source.follow_on_snapshot_json='{"preparing":true}'
        with self.assertRaisesRegex(ValueError,'no completed'):self.context()
    def test_ordinary_new_trip_still_requires_real_departure_before_follow_on(self):
        self.source.driver_route_started_on=None
        self.assertTrue(any('normal office planning' in r for r in self.context()['blockers']))
    def test_source_row_lock_precedes_savepoint_and_first_child_write(self):
        order=[];original=self.b.frappe.get_doc
        def get_doc(dt,name=None,**kw):
            if dt==TRIP and name==self.source.name and kw.get('for_update'):order.append('source lock')
            return original(dt,name,**kw)
        self.b.frappe.get_doc=get_doc
        before=self.b.frappe.db.savepoint
        self.b.frappe.db.savepoint=lambda name:(order.append('savepoint'),before(name))[-1]
        fn=self.ns['_new_trip'];self.ns['_new_trip']=lambda *a:(order.append('child insert'),fn(*a))[-1]
        self.create();self.assertLess(order.index('source lock'),order.index('savepoint'));self.assertLess(order.index('savepoint'),order.index('child insert'))
    def test_late_void_is_seen_as_current_read_after_waiting_for_source_lock(self):
        payload=self.payload();key=self.ns['_void_key'](self.source.name,'EVENT');original=self.b.frappe.db.get_value
        def value(dt,name,fields,**kw):
            if dt=='CFG Kanban Event' and isinstance(name,dict) and name.get('idempotency_key')==key:
                self.assertTrue(kw.get('for_update'))
                return Doc(name='VOID',operator=self.op.employee,user=self.b.frappe.session.user,payload_json=json.dumps({'request_hash':self.ns['canonical_key']('follow-on-request',self.ns['_payload'](payload))}))
            return original(dt,name,fields,**kw)
        self.b.frappe.db.get_value=value
        with self.assertRaisesRegex(self.ns['FollowOnReplayError'],'voided'):self.create(payload)
        self.assertFalse(self.transaction_calls);self.assertFalse(self.reserve_calls)
    def test_void_token_cannot_be_reused_for_another_payload_or_actor(self):
        p=self.payload();self.ns['reconcile_follow_on'](self.source.name,p,'EVENT','TOKEN',void_reason='Correct')
        p['reason']='CHANGED'
        with self.assertRaisesRegex(self.ns['FollowOnReplayError'],'another actor|different details'):self.ns['reconcile_follow_on'](self.source.name,p,'EVENT','TOKEN')
    def test_failure_after_child_insert_rolls_back_even_if_caller_catches_it(self):
        fn=self.ns['_new_trip']
        def fail(*args):fn(*args);raise RuntimeError('Injected after child')
        self.ns['_new_trip']=fail
        with self.assertRaisesRegex(RuntimeError,'after child'):self.create()
        self.assert_original(1);self.assertEqual(self.transaction_calls[-1],('rollback','cfg_follow_on_create'))
    def test_failure_after_return_handover_restores_original_case_and_audit(self):
        self.case();fn=self.custody.transfer
        def fail(*args):fn(*args);raise RuntimeError('Injected after custody')
        self.custody.transfer=fail
        with self.assertRaisesRegex(RuntimeError,'after custody'):self.create(self.payload(returns=['RETURN'],confirmed_returns=['RETURN']))
        self.assert_original(1,cases=True)
    def test_failure_after_parent_closure_restores_source_and_custody(self):
        self.case();self.ns['_close_sheets']=Mock(side_effect=RuntimeError('Injected after closure'))
        with self.assertRaisesRegex(RuntimeError,'after closure'):self.create(self.payload(returns=['RETURN'],confirmed_returns=['RETURN']))
        self.assert_original(1,cases=True);self.assertEqual(self.source.driver_route_state,'In Progress')
    def test_failure_after_reservation_exchange_restores_stock_and_allocation_audit(self):
        fn=self.carry.confirm
        def fail(*args):fn(*args);raise RuntimeError('Injected after exchange')
        self.carry.confirm=fail
        with self.assertRaisesRegex(RuntimeError,'after exchange'):self.create()
        self.assertTrue(self.reserve_calls);self.assert_original(1)
        self.assertEqual(self.data['CFG Kanban Handling Unit']['HU'].current_qty,4)
    def test_last_audit_failure_rolls_back_then_same_request_can_create_once(self):
        fn=self.ns['record'];p=self.payload()
        def fail(event,**kw):
            fn(event,**kw)
            if event=='Follow-on Delivery Trip Created':raise RuntimeError('Injected last write')
        self.ns['record']=fail
        with self.assertRaisesRegex(RuntimeError,'last write'):self.create(p)
        self.assert_original(1);self.ns['record']=fn;result=self.create(p)
        self.assertEqual(self.create(p),result);self.assertEqual(len(self.data[TRIP]),2)
    def test_deadlock_without_savepoint_forces_full_request_rollback(self):
        rollback=self.b.frappe.db.rollback
        def missing_savepoint(save_point=None):
            if save_point:raise RuntimeError('SAVEPOINT no longer exists after deadlock')
            return rollback()
        self.b.frappe.db.rollback=missing_savepoint
        self.ns['_close_sheets']=Mock(side_effect=RuntimeError('Original deadlock'))
        with self.assertRaisesRegex(RuntimeError,'Original deadlock'):self.create()
        self.assert_original(1);self.assertEqual(self.transaction_calls[-1],('rollback',None))

    def test_permission_rejection_has_no_savepoint_or_mutation(self):
        self.data['Company']['A']._denied=1
        with self.assertRaises(PermissionError):self.context()
        self.assertFalse(self.transaction_calls);self.assertFalse(self.reserve_calls)
    def test_saved_follow_on_allocation_is_valid_without_a_fabricated_manifest(self):
        result=self.create();child=self.data[TRIP][result['trip']];row=next(iter(self.data[ALLOC].values()))
        for plan in self.data[PLAN].values():
            for line in plan.get('lines') or []:self.data.setdefault('CFG Kanban Dispatch Plan Line',{})[line.name]=line
        row._before=Doc(dict(row));row.flags=Doc()
        controller=load('cfg_kanban/doctype/cfg_kanban_dispatch_allocation/cfg_kanban_dispatch_allocation.py',dict(frappe=self.b.frappe,flt=lambda n:float(n or 0),get_datetime=lambda value:value if isinstance(value,datetime.datetime) else datetime.datetime.fromisoformat(str(value)),Document=Doc))['CFGKanbanDispatchAllocation']
        controller.validate(row)
        self.assertFalse(row.movement_manifest);self.assertTrue(row.load_confirmed)
        row.loaded_on=row.loaded_on.isoformat()
        controller.validate(row) # Desk JSON text and DB datetime represent the same instant.
        row.loaded_on='2026-11-25 12:00:00'
        with self.assertRaisesRegex(ValueError,'controlled reservation/loading audit'):controller.validate(row)
        row.loaded_on=row._before.loaded_on
        row.allocated_qty=3
        with self.assertRaisesRegex(ValueError,'controlled reservation/loading audit'):controller.validate(row)
    def test_same_receipt_cannot_authorize_new_or_relocated_allocation(self):
        self.create();row=next(iter(self.data[ALLOC].values()));self.carry.validate_allocation(row)
        row.source_warehouse='SOURCE'
        with self.assertRaisesRegex(ValueError,'immutable physical confirmation'):self.carry.validate_allocation(row)

    def test_current_stock_revision_tracks_inherited_printing_and_serial_metadata(self):
        unit=self.data['CFG Kanban Handling Unit']['HU'];unit.process_certificate_set='SET';unit.batch_no='LOT'
        self.b.add('Batch','LOT',item='ITEM1',expiry_date='2027-01-01',modified='A')
        self.b.add('CFG Kanban Handling Unit Serial','SERIAL',handling_unit='HU',serial_no='SER-1',state='Active',modified='A')
        child=self.b.add('CFG Process Certificate','CHILD',handling_unit='HU',certificate_set='SET',source_reference_doctype='CFG Process Certificate',source_reference_name='ROOT',modified='A',status='Active')
        root=self.b.add('CFG Process Certificate','ROOT',source_reference_doctype='Stock Entry',source_reference_name='REPACK',modified='A',status='Active')
        self.b.add('Stock Entry','REPACK',docstatus=1,purpose='Repack',modified='A')
        run=self.b.add('CFG Process Certificate Run','RUN',repack_stock_entry='REPACK',status='Completed',printed_expiry='2027-01-01',modified='A')
        first=self.revisions.revision(unit)
        root.status='Revoked';root.modified='B';run.printed_expiry='2026-11-01'
        current=self.revisions.revision(unit,current=True)
        self.assertNotEqual(first,current)
        self.assertEqual(next(row for row in current['certificates'] if row['name']=='ROOT')['status'],'Revoked')
        self.assertEqual(current['runs'][0]['printed_expiry'],'2026-11-01')
    def test_current_revision_uses_locking_reads_instead_of_the_stale_preview_view(self):
        unit=self.data['CFG Kanban Handling Unit']['HU'];unit.process_certificate_set='SET'
        self.b.add('CFG Process Certificate','CERT',handling_unit='HU',certificate_set='SET',modified='B',status='Revoked')
        original=self.b.frappe.get_all
        self.b.frappe.get_all=lambda dt,**kw:[Doc(name='CERT',modified='A',status='Active')] if dt=='CFG Process Certificate' else original(dt,**kw)
        first=self.revisions.revision(unit)
        current=self.revisions.revision(unit,current=True)
        self.assertEqual(first['certificates'][0]['status'],'Active');self.assertEqual(current['certificates'][0]['status'],'Revoked')
    def test_post_only_reservation_contracts_are_declared_on_both_mutation_endpoints(self):
        import ast
        from cfg_kanban.tests.test_vehicle_overview import ROOT
        tree=ast.parse((ROOT/'services/dispatch_planning.py').read_text())
        for name in ('reserve_dispatch_tag','reserve_dispatch_untagged'):
            fn=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name==name)
            methods=next(kw.value for kw in fn.decorator_list[0].keywords if kw.arg=='methods')
            self.assertEqual(ast.literal_eval(methods),['POST'])
