"""Actual closure, route action, loading and native row validators with offline records.

These doubles verify control flow and rollback boundaries, not MariaDB isolation,
Frappe permissions, stock posting or live-site acceptance.
"""
import copy
import datetime
import json
import sys
import types
import unittest
from unittest.mock import Mock, patch

from cfg_kanban.tests import test_route_sheets as sheet_fixture
from cfg_kanban.tests.test_route_sheets import Doc
from cfg_kanban.tests.test_vehicle_overview import load, Row

PLAN = 'CFG Kanban Dispatch Plan'
REVIEW = 'CFG Kanban Dispatch Review'
SESSION = 'CFG Kanban Delivery Session'
DA = 'CFG Kanban Delivery Allocation'
SOURCE = 'CFG Kanban Dispatch Allocation'
MF = 'CFG Kanban Movement Manifest'
HU = 'CFG Kanban Handling Unit'
LEDGER = 'CFG Kanban Handling Unit Quantity Ledger'


class Document(Doc):
    def __deepcopy__(self, memo):
        result=Document();memo[id(self)]=result
        for key,value in dict.items(self): result[key]=copy.deepcopy(value,memo)
        return result

    def as_dict(self):
        def clean(value):
            if isinstance(value, NativeDocument): return clean(value.as_dict())
            if isinstance(value, dict): return {key: clean(item) for key, item in dict.items(value) if not key.startswith('_')}
            if isinstance(value, list): return [clean(row) for row in value]
            return value
        return clean(self)

    def __getattribute__(self, name):
        if not name.startswith('__') and dict.__contains__(self, name):
            return dict.__getitem__(self, name)
        return super().__getattribute__(name)


class NativeDocument:
    """Frappe-shaped child: attributes/get(), deliberately no __getitem__."""
    def __init__(self, **values):
        self.__dict__.update(values)

    def get(self, field, default=None):
        return self.__dict__.get(field, default)

    def __getattr__(self, field):
        if field.startswith('__'): raise AttributeError(field)
        return None

    def as_dict(self):
        return {field: value for field, value in self.__dict__.items() if not field.startswith('_')}

    def update(self, values):
        self.__dict__.update(values)


class TestDocumentClosure(unittest.TestCase):
    def setUp(self):
        self.r = sheet_fixture.TestRouteSheets(); self.r.setUp()
        self.data = self.r.data; self.frappe = self.r.frappe
        def get_all(dt, filters=None, fields=None, **kw):
            fields = None if fields == ['*'] else fields
            if dt == 'CFG Kanban Manifest Line':
                rows=[Document(line.as_dict(),parent=manifest.name) for manifest in self.data.get(MF,{}).values() for line in manifest.get('lines') or []]
                return [Document({field:row.get(field) for field in fields}) if fields else row for row in rows if self.r.matches(row,filters or {})]
            return self.r.get_all(dt, filters, fields, **kw)
        self.frappe.get_all = get_all
        self.frappe.ValidationError = ValueError
        self.r.operator.can_complete = 1
        self.data['Warehouse']['LORRY'].cfg_is_vehicle_warehouse = 1
        self.r.operator.responsibilities.append(Row(responsibility='Logistics Reconciliation'))
        self.frappe.db.savepoint = self.savepoint
        self.frappe.db.rollback = self.rollback
        self.snapshots = {}; self.prohibited = []
        old = self.frappe.get_doc
        def get_doc(dt, name=None, **kw):
            if isinstance(dt, dict) and dt['doctype'] in (MF, 'Stock Entry', 'Delivery Note', 'Stock Ledger Entry', LEDGER):
                self.prohibited.append(dt['doctype'])
                raise AssertionError('Closure attempted a stock document / movement insert')
            return old(dt, name, **kw)
        self.frappe.get_doc = get_doc
        common = dict(self.r.common, flt=lambda value: float(value or 0),
                      get_datetime=lambda value: value if isinstance(value, datetime.datetime) else datetime.datetime.fromisoformat(str(value)))
        self.closure = types.ModuleType('closure'); self.closure.__dict__.update(common)
        load('services/dispatch_closure.py', self.closure.__dict__)
        self.reviews = types.ModuleType('reviews'); self.reviews.__dict__.update(common)
        load('services/dispatch_reconciliation.py', self.reviews.__dict__)
        self.fulfilment = types.ModuleType('fulfilment'); self.fulfilment.__dict__.update(common)
        load('services/dispatch_fulfilment.py', self.fulfilment.__dict__)
        self.feedback = types.ModuleType('feedback'); self.feedback.__dict__.update(common)
        load('integrations/logistics_feedback.py', self.feedback.__dict__)
        self.reviews._fulfilment = lambda: self.fulfilment
        self.reviews._planning = lambda: self.r.planning
        self.reviews._counts = lambda: Row(_require_authorized=self.require_reconciliation)
        self.closure._reviews = lambda: self.reviews
        self.closure._feedback = lambda: self.feedback
        self.r.ns['_closure'] = lambda: self.closure
        identity = types.ModuleType('cfg_kanban.services.logistics_stock_identity')
        identity.validate_logistics_document = Mock()
        self.identity = identity
        patcher = patch.dict(sys.modules, {identity.__name__: identity}); patcher.start(); self.addCleanup(patcher.stop)
        self.r.add('Warehouse', 'SOURCE', company='B', disabled=0, is_group=0, cfg_is_vehicle_warehouse=0)
        self.make_load(self.r.p1, 'A', 'TAG-A', 3)
        self.make_load(self.r.p2, 'B', None, 2)

    def require_reconciliation(self, operator):
        if 'Logistics Reconciliation' not in [row.responsibility for row in operator.responsibilities]:
            raise PermissionError('Logistics Reconciliation required')

    def add(self, dt, name, **values):
        doc = Document(doctype=dt, name=name, **values); doc._data = self.data
        self.data.setdefault(dt, {})[name] = doc
        return doc

    def savepoint(self, name):
        self.snapshots[name] = (copy.deepcopy(self.data), copy.deepcopy(self.r.events))

    def rollback(self, save_point):
        data, events = self.snapshots[save_point]
        self.data.clear(); self.data.update(data); self.r.events[:] = events
        for table in self.data.values():
            for doc in table.values():
                doc._data = self.data

    def snapshot_stock(self):
        return {dt: {name: doc.as_dict() for name, doc in self.data.get(dt, {}).items()}
                for dt in (MF, 'Stock Entry', 'Delivery Note', 'Stock Ledger Entry', LEDGER, HU)}

    def make_load(self, plan, item, tag, qty):
        plan.update(lines=[Doc(name=plan.name+'-LINE', item_code=item, loaded_qty=qty, stock_uom='Nos')],
                    source_warehouse='SOURCE', movement_manifest='LOAD-'+plan.name, loaded_on=datetime.datetime(2026, 11, 19, 10),
                    total_loaded_qty=qty, total_delivered_qty=0, fulfilment_status='Not Started',
                    dispatch_review_state=None, active_dispatch_review=None)
        self.add(SOURCE, 'SRC-'+plan.name, dispatch_plan=plan.name, dispatch_plan_line=plan.name+'-LINE',
                 movement_manifest=plan.movement_manifest, state='Loaded', load_confirmed=1,
                 allocated_qty=qty, allocation_kind='Tagged Stock' if tag else 'Untagged ERP Stock',
                 item_code=item, stock_uom='Nos', batch_no=None, handling_unit=tag)
        self.add(MF, plan.movement_manifest, dispatch_plan=plan.name, state='Received', source_company='B',
                 destination_company='B', source_warehouse='SOURCE', destination_warehouse='LORRY',
                 dispatch_stock_entry='LOAD-STE-'+plan.name)
        self.add('Stock Entry', 'LOAD-STE-'+plan.name, docstatus=1, company='B')
        if tag:
            self.add(HU, tag, handling_unit_id=tag, current_qty=qty, reserved_qty=0,
                     current_warehouse='LORRY', inventory_company='B', item_code=item, batch_no=None, stock_uom='Nos')

    def deliver(self, name):
        plan = self.data[PLAN][name]; source = self.data[SOURCE]['SRC-'+name]
        session = self.add(SESSION, 'SESSION-'+name, dispatch_plan=name, state='Closed',
            selling_company='B', source_warehouse='LORRY', customer=plan.customer or 'C2',
            customer_address=plan.customer_address or 'A2', price_list='SELL', proof_policy='No Proof Required',
            delivery_note='DN-'+name)
        item = Document(name='DN-LINE-'+name, cfg_delivery_allocation='DA-'+name, item_code=source.item_code,
            batch_no=source.batch_no, warehouse='LORRY', stock_uom='Nos', uom='Nos', stock_qty=source.allocated_qty,
            cfg_handling_unit=source.handling_unit)
        self.add('Delivery Note', 'DN-'+name, docstatus=1, company='B', customer=session.customer,
                 shipping_address_name=session.customer_address, selling_price_list='SELL',
                 cfg_delivery_session=session.name, items=[item])
        self.add(DA, 'DA-'+name, delivery_session=session.name, state='Delivered', delivery_note='DN-'+name,
                 delivery_note_item=item.name, item_code=source.item_code, batch_no=source.batch_no,
                 stock_uom='Nos', allocated_qty=source.allocated_qty, delivered_qty=source.allocated_qty,
                 handling_unit=source.handling_unit, source_warehouse='LORRY', dispatch_allocation=source.name)
        plan.update(delivery_session=session.name, delivery_note=session.delivery_note, fulfilment_status='Completed',
                    total_delivered_qty=source.allocated_qty, active_route_stop=None)
        for stop in self.data.get('CFG Kanban Route Stop', {}).values():
            if stop.dispatch_plan == name:
                stop.update(state='Completed', delivery_session=session.name, delivery_note=session.delivery_note)
        if source.handling_unit:
            self.data[HU][source.handling_unit].update(current_qty=0, current_warehouse=None)
        return session

    def route(self):
        self.r.save()
        self.deliver('P1'); self.deliver('P2')
        return self.r.sheet()

    def close_route(self, event='CLOSE', **kw):
        sheet = self.r.sheet()
        return self.r.save('Close', expected_revision=sheet.revision, route_sheet=sheet.name,
                           event_token=event, reason='Deliveries finished', **kw)

    def review(self, plan):
        rows = self.reviews._balances(plan)
        review = self.add(REVIEW, 'REVIEW-'+plan.name, dispatch_plan=plan.name, company='B',
            vehicle_warehouse='LORRY', state='Reviewing', opened_on=datetime.datetime(2026, 11, 20, 11),
            opening_snapshot_json=json.dumps(rows), opening_snapshot_hash=self.reviews._hash(rows))
        plan.update(active_dispatch_review=review.name, dispatch_review_state='Reviewing')
        return review

    def returned(self, name='P2', tag=None):
        plan = self.data[PLAN][name]; source = self.data[SOURCE]['SRC-'+name]
        if tag is not None:
            source.handling_unit = tag; source.allocation_kind = 'Tagged Stock'
            self.add(HU, tag, handling_unit_id=tag, current_qty=source.allocated_qty, reserved_qty=0,
                     current_warehouse='SOURCE', inventory_company='B', item_code=source.item_code, stock_uom='Nos')
        line = Document(name='RET-LINE', dispatch_allocation=source.name, handling_unit=source.handling_unit,
                        item_code=source.item_code, stock_uom='Nos', dispatch_qty=source.allocated_qty,
                        received_qty=source.allocated_qty, state='Received')
        manifest = self.add(MF, 'RETURN', state='Received', manifest_type='Internal Warehouse Transfer',
            internal_transfer_mode='Direct Transfer', source_company='B', destination_company='B',
            source_warehouse='LORRY', destination_warehouse='SOURCE', dispatch_stock_entry='RETURN-STE',
            dispatch_confirmed_on=datetime.datetime(2026, 11, 19, 18), lines=[line])
        item = Document(name='RET-ITEM', cfg_manifest_line=line.name, cfg_handling_unit=source.handling_unit,
            item_code=source.item_code, stock_uom='Nos', uom='Nos', transfer_qty=source.allocated_qty,
            s_warehouse='LORRY', t_warehouse='SOURCE')
        entry = self.add('Stock Entry', 'RETURN-STE', docstatus=1, company='B', purpose='Material Transfer',
                         cfg_movement_manifest=manifest.name, cfg_transfer_stage='Direct', items=[item])
        for wh, sign in (('LORRY', -1), ('SOURCE', 1)):
            self.add('Stock Ledger Entry', 'SLE-'+wh, voucher_type='Stock Entry', voucher_no=entry.name,
                     voucher_detail_no=item.name, warehouse=wh, item_code=item.item_code, stock_uom='Nos',
                     actual_qty=sign*source.allocated_qty, creation=manifest.dispatch_confirmed_on)
        if source.handling_unit:
            self.add(LEDGER, 'LOCATION', event_type='Location Transfer', source_handling_unit=source.handling_unit,
                reference_doctype='Stock Entry', reference_name=entry.name, item_code=source.item_code,
                stock_uom='Nos', stock_qty=source.allocated_qty, source_company='B', source_warehouse='LORRY',
                destination_company='B', destination_warehouse='SOURCE')
        return manifest, entry

    def close_plan(self, event='CLOSE-PLAN', manifest='RETURN'):
        return self.closure.close_dispatch_plan('P2', 'All remaining goods returned', event, 'TOKEN', manifest)

    def test_full_route_with_unrelated_stock_and_reused_empty_tag_needs_no_count_or_stock_write(self):
        self.route()
        self.data[HU]['TAG-A'].update(item_code='UNRELATED', current_qty=42, current_warehouse='LORRY')
        self.add(PLAN, 'UNRELATED', company='B', vehicle_warehouse='LORRY', state='Loaded', route_stock_commitment=1)
        before = self.snapshot_stock(); unrelated = self.data[PLAN]['UNRELATED'].as_dict()
        result = self.close_route()
        self.assertEqual(result['sheet']['state'], 'Completed')
        self.assertIsNone(self.r.sheet().active_scope_key)
        for name in ('P1', 'P2'):
            plan = self.data[PLAN][name]
            self.assertEqual((plan.state, plan.dispatch_review_state), ('Reconciled', 'Settled'))
            review = self.data[REVIEW][plan.active_dispatch_review]
            self.assertEqual(review.settlement_basis, 'Posted Documents'); self.assertFalse(review.route_reconciliation)
            evidence = json.loads(review.closure_evidence_json)
            self.assertEqual(evidence['deliveries'][0]['delivery_note'], 'DN-'+name)
            self.assertEqual(evidence['actor'], 'EMP'); self.assertTrue(evidence['closed_on'])
        self.assertEqual(before, self.snapshot_stock()); self.assertEqual(unrelated, self.data[PLAN]['UNRELATED'].as_dict())
        self.assertFalse(self.data.get('CFG Kanban Route Reconciliation')); self.assertFalse(self.prohibited)

    def test_public_close_plan_reports_exact_blocker_as_standard_validation_after_rollback(self):
        self.returned();self.data[MF]['RETURN'].lines[0].dispatch_qty=1
        self.reviews._closure_services=lambda:self.closure
        before=self.snapshot_stock()
        with self.assertRaisesRegex(ValueError,'expected 2 Nos, recorded 1') as raised:
            self.reviews.close_dispatch_plan('P2','Checked','EVENT','TOKEN','RETURN')
        self.assertIs(type(raised.exception),ValueError)
        self.assertEqual(self.snapshot_stock(),before);self.assertFalse(self.data.get(REVIEW))

    def test_optional_invoice_and_print_follow_up_do_not_block_completed_delivery_closure(self):
        self.route()
        self.add('CFG ERP Command','INVOICE-PENDING',delivery_session='SESSION-P2',command_type='Create Driver Sales Invoice',status='Pending')
        before=self.snapshot_stock()
        self.assertEqual(self.close_route()['sheet']['state'],'Completed')
        self.assertEqual(before,self.snapshot_stock())

    def test_same_or_new_token_duplicate_route_close_does_not_duplicate_reviews_or_events(self):
        self.route(); sheet = self.r.sheet(); args = self.r.rows
        self.close_route(); reviews = len(self.data[REVIEW]); events = len(self.r.events)
        result = self.r.ns['save_route_sheet']('V:LORRY', args, 1, 'CLOSE', 'TOKEN', 'Close',
                                               reason='Deliveries finished', route_sheet=sheet.name)
        self.assertEqual(result['sheet']['state'], 'Completed')
        self.close_route('NEW-TOKEN')
        with self.assertRaisesRegex(ValueError,'reason'):
            self.r.save('Close',route_sheet=sheet.name,expected_revision=sheet.revision,event_token='NO-REASON')
        self.assertEqual((len(self.data[REVIEW]), len(self.r.events)), (reviews, events))

    def test_missing_or_unsubmitted_proof_blocks_all_linked_plans_without_writes(self):
        for state in (None, 'Draft'):
            with self.subTest(state=state):
                self.setUp(); self.route()
                delivery = self.data[SESSION]['SESSION-P2']; delivery.proof_policy = 'Required'
                if state:
                    delivery.delivery_proof = 'PROOF'
                    self.add('CFG Kanban Delivery Proof', 'PROOF', state=state)
                stock = self.snapshot_stock(); before = len(self.r.events)
                with self.assertRaisesRegex(ValueError, 'proof|Proof'):
                    self.close_route()
                self.assertEqual(self.data[PLAN]['P1'].state, 'Loaded'); self.assertFalse(self.data.get(REVIEW))
                self.assertEqual(len(self.r.events), before); self.assertEqual(self.snapshot_stock(), stock)

    def test_submitted_proof_with_missing_required_signature_still_blocks(self):
        self.route(); delivery = self.data[SESSION]['SESSION-P1']
        delivery.update(proof_policy='Required', require_signature=1, delivery_proof='PROOF')
        self.add('CFG Kanban Delivery Proof', 'PROOF', state='Submitted', delivery_session=delivery.name,
                 delivery_note=delivery.delivery_note, selling_company='B', customer=delivery.customer,
                 proof_policy='Required', disposition='Attended', signature_count=0)
        with self.assertRaisesRegex(ValueError, 'signature'):
            self.close_route()

    def test_submitted_matching_proof_allows_closure(self):
        self.route(); delivery = self.data[SESSION]['SESSION-P1']
        delivery.update(proof_policy='Required', require_signature=1, delivery_proof='PROOF')
        self.add('CFG Kanban Delivery Proof', 'PROOF', state='Submitted', delivery_session=delivery.name,
                 delivery_note=delivery.delivery_note, selling_company='B', customer=delivery.customer,
                 proof_policy='Required', disposition='Attended', signature_count=1)
        self.assertEqual(self.close_route()['sheet']['state'], 'Completed')

    def test_draft_cancelled_or_changed_delivery_note_cannot_back_closure(self):
        for mutation in ({'docstatus': 0}, {'docstatus': 2}, {'customer': 'OTHER'}, {'is_return': 1}):
            with self.subTest(mutation=mutation):
                self.setUp(); self.route(); self.data['Delivery Note']['DN-P1'].update(mutation)
                with self.assertRaises(ValueError): self.close_route()
                self.assertFalse(self.data.get(REVIEW)); self.assertEqual(self.data[PLAN]['P2'].state, 'Loaded')

    def test_wrong_dn_row_stock_uom_batch_quantity_and_tag_are_rejected(self):
        for mutation in ({'stock_uom': 'Kg'}, {'batch_no': 'OTHER'}, {'stock_qty': 4}, {'cfg_handling_unit': 'OTHER'}):
            with self.subTest(mutation=mutation):
                self.setUp(); self.route(); self.data['Delivery Note']['DN-P1'].items[0].update(mutation)
                with self.assertRaises(ValueError): self.close_route()
                self.assertFalse(self.data.get(REVIEW))

    def test_pending_session_command_manifest_and_prepared_allocation_are_exact_blockers(self):
        for kind in ('session', 'command', 'manifest', 'allocation'):
            with self.subTest(kind=kind):
                self.setUp(); self.route()
                if kind == 'session': self.add(SESSION, 'UNFINISHED', dispatch_plan='P2', state='Awaiting Confirmation')
                if kind == 'command': self.add('CFG ERP Command', 'UNFINISHED', delivery_session='SESSION-P2', command_type='Create Customer Delivery Note', status='Running')
                if kind == 'manifest': self.add(MF, 'UNFINISHED', dispatch_plan='P2', state='Draft')
                if kind == 'allocation': self.add(SOURCE, 'UNFINISHED', dispatch_plan='P2', state='Reserved', item_code='B')
                with self.assertRaisesRegex(ValueError, 'UNFINISHED'): self.close_route()
                self.assertFalse(self.data.get(REVIEW))

    def test_failure_after_first_settlement_and_response_error_both_rollback_everything(self):
        for fail_response in (False, True):
            with self.subTest(response=fail_response):
                self.setUp(); self.route(); before = self.snapshot_stock(); event_count = len(self.r.events)
                actual = self.closure.settle
                def settle(value, *args):
                    if value['plan'].name == 'P2': raise ValueError('Injected second Plan audit failure')
                    return actual(value, *args)
                if fail_response:
                    real = self.r.ns['sheet_context']
                    self.r.ns['sheet_context'] = lambda sheet, op: (_ for _ in ()).throw(ValueError('Injected response failure')) if sheet.state == 'Completed' else real(sheet, op)
                else: self.closure.settle = settle
                with self.assertRaisesRegex(ValueError, 'Injected'): self.close_route()
                self.assertEqual(self.data[PLAN]['P1'].state, 'Loaded'); self.assertEqual(self.data[PLAN]['P2'].state, 'Loaded')
                self.assertEqual(self.r.sheet().state, 'Approved'); self.assertFalse(self.data.get(REVIEW))
                self.assertEqual(len(self.r.events), event_count); self.assertEqual(self.snapshot_stock(), before)

    def test_exact_pre_review_untagged_return_settles_without_recreating_movement(self):
        manifest, entry = self.returned(); plan = self.data[PLAN]['P2']; review = self.review(plan)
        self.assertLess(manifest.dispatch_confirmed_on, review.opened_on)
        stock = self.snapshot_stock(); result = self.close_plan()
        self.assertEqual((result['plan']['state'], result['plan']['fulfilment_status']), ('Reconciled', 'Closed Incomplete'))
        self.assertEqual(result['review']['action'], 'Returned to Warehouse')
        self.assertEqual(result['plan']['total_delivered_qty'], 0)
        self.assertTrue(json.loads(result['review']['closure_evidence_json'])['returned']['posted_before_review'])
        self.assertEqual(self.snapshot_stock(), stock); self.assertFalse(self.prohibited)

    def test_tagged_return_without_review_link_is_identified_by_exact_source_and_ledgers(self):
        manifest, entry = self.returned(tag='TAG-B'); manifest.lines[0].dispatch_allocation = None
        self.review(self.data[PLAN]['P2']); stock = self.snapshot_stock()
        context = self.closure.get_close_plan_context('P2', 'TOKEN')
        self.assertEqual(context['return_manifest'], 'RETURN')
        self.assertEqual(self.close_plan(manifest=None)['review']['movement_stock_entry'], entry.name)
        self.assertEqual(stock, self.snapshot_stock())

    def test_returned_tag_later_used_at_warehouse_does_not_require_another_lorry_count(self):
        self.returned(tag='TAG-B');self.data[HU]['TAG-B'].update(current_qty=0,item_code='LATER-STOCK',inventory_company='A')
        before=self.snapshot_stock()
        result=self.close_plan()
        self.assertEqual(result['review']['action'],'Returned to Warehouse')
        audit=json.loads(result['review']['closing_snapshot_json'])[0]
        self.assertEqual(audit['item_code'],'B');self.assertFalse(any(key.startswith('current_') for key in audit))
        self.assertEqual(before,self.snapshot_stock())

    def test_already_settled_manual_mixed_review_is_retained_during_route_close(self):
        self.route()
        for plan in (self.data[PLAN]['P1'],self.data[PLAN]['P2']):
            review=self.review(plan);review.update(state='Completed',mixed_recovery_json='{"active":true}',variance_exception='OLD-RESOLVED')
            plan.update(state='Reconciled',dispatch_review_state='Settled')
        before={name:doc.as_dict() for name,doc in self.data[REVIEW].items()}
        self.close_route()
        self.assertEqual(before,{name:doc.as_dict() for name,doc in self.data[REVIEW].items()})

    def test_historical_return_uses_frozen_certificate_identity_and_keeps_posting_checks(self):
        manifest,entry=self.returned(tag='TAG-B');line=manifest.lines[0]
        line.process_certificate_set='CERT-SET'
        line.stock_identity_snapshot=json.dumps(dict(handling_unit='TAG-B',item_code='B',batch_no=None,stock_uom='Nos',process_certificate_set='CERT-SET',serial_nos=[]))
        entry.items[0].update(process_certificate_set='CERT-SET',to_process_certificate_set='WRONG')
        self.identity.validate_logistics_document.side_effect=ValueError('Current stock has different certificates')
        with self.assertRaisesRegex(ValueError,'certificate dimension'):self.close_plan()
        self.data['Stock Entry']['RETURN-STE'].items[0].to_process_certificate_set='CERT-SET'
        self.assertEqual(self.close_plan()['plan']['state'],'Reconciled')
        self.identity.validate_logistics_document.assert_not_called()
        with self.assertRaisesRegex(ValueError,'Current stock'):
            self.feedback.validate_internal_stock_entry(self.data['Stock Entry']['RETURN-STE'])
        self.identity.validate_logistics_document.assert_called_once()

    def test_return_after_tag_loaded_again_cannot_settle_its_previous_load(self):
        self.returned(tag='TAG-B')
        self.add(PLAN,'LATER-PLAN',loaded_on=datetime.datetime(2026,11,19,17))
        self.add(SOURCE,'LATER-SOURCE',dispatch_plan='LATER-PLAN',handling_unit='TAG-B',state='Loaded')
        with self.assertRaisesRegex(ValueError,'loaded again'):self.close_plan()
        self.data[PLAN]['LATER-PLAN'].loaded_on=datetime.datetime(2026,11,20,10)
        self.assertEqual(self.close_plan()['plan']['state'],'Reconciled')

    def test_untagged_return_without_plan_provenance_remains_in_manual_workflow(self):
        manifest, _entry = self.returned(); manifest.lines[0].dispatch_allocation = None
        context = self.closure.get_close_plan_context('P2', 'TOKEN')
        self.assertFalse(context['can_close']); self.assertTrue(any('provenance' in text for text in context['blockers']))
        with self.assertRaisesRegex(ValueError, 'provenance'): self.close_plan()

    def test_ambiguous_completed_returns_require_explicit_choice(self):
        manifest,entry=self.returned()
        other_line=Document(manifest.lines[0].as_dict(),name='OTHER-LINE')
        self.add(MF,'OTHER-RETURN',**{key:value for key,value in manifest.as_dict().items() if key not in ('name','doctype','lines','dispatch_stock_entry')},
                 lines=[other_line],dispatch_stock_entry='OTHER-STE')
        other_item=Document(entry.items[0].as_dict(),name='OTHER-ITEM',cfg_manifest_line=other_line.name)
        self.add('Stock Entry','OTHER-STE',**{key:value for key,value in entry.as_dict().items() if key not in ('name','doctype','items','cfg_movement_manifest')},
                 items=[other_item],cfg_movement_manifest='OTHER-RETURN')
        for wh,sign in (('LORRY',-1),('SOURCE',1)):
            self.add('Stock Ledger Entry','OTHER-'+wh,voucher_type='Stock Entry',voucher_no='OTHER-STE',voucher_detail_no='OTHER-ITEM',
                     warehouse=wh,item_code='B',stock_uom='Nos',actual_qty=sign*2,creation=manifest.dispatch_confirmed_on)
        context=self.closure.get_close_plan_context('P2','TOKEN')
        self.assertEqual(len(context['candidates']),2);self.assertFalse(context['can_close']);self.assertIsNone(context['return_manifest'])
        with self.assertRaisesRegex(ValueError,'several completed return'):self.close_plan(manifest=None)
        self.assertEqual(self.close_plan(manifest='OTHER-RETURN')['review']['movement_stock_entry'],'OTHER-STE')

    def test_exact_batch_and_stock_uom_are_accepted_and_recorded(self):
        plan=self.data[PLAN]['P2'];source=self.data[SOURCE]['SRC-P2']
        plan.lines[0].update(batch_no='LOT-1',stock_uom='Kg');source.update(batch_no='LOT-1',stock_uom='Kg')
        manifest,entry=self.returned();manifest.lines[0].update(batch_no='LOT-1',stock_uom='Kg');entry.items[0].update(batch_no='LOT-1',stock_uom='Kg',uom='Kg')
        for sle in self.data['Stock Ledger Entry'].values():sle.stock_uom='Kg'
        result=self.close_plan();row=json.loads(result['review']['closing_snapshot_json'])[0]
        self.assertEqual((row['item_code'],row['batch_no'],row['stock_uom'],row['remaining_qty']),('B','LOT-1','Kg',2))

    def test_completed_two_leg_return_requires_both_exact_submitted_postings(self):
        manifest,entry=self.returned(tag='TAG-B')
        manifest.update(internal_transfer_mode='Goods in Transit',transit_warehouse='TRANSIT',receipt_stock_entry='RECEIPT-STE')
        entry.cfg_transfer_stage='Outward';entry.items[0].t_warehouse='TRANSIT'
        self.data['Stock Ledger Entry']['SLE-SOURCE'].warehouse='TRANSIT'
        self.add('Stock Entry Detail',entry.items[0].name,parent=entry.name,cfg_manifest_line=manifest.lines[0].name)
        receipt_item=Document(entry.items[0].as_dict(),name='RECEIPT-ITEM',s_warehouse='TRANSIT',t_warehouse='SOURCE',
                              against_stock_entry=entry.name,ste_detail=entry.items[0].name)
        receipt=self.add('Stock Entry','RECEIPT-STE',docstatus=1,company='B',purpose='Material Transfer',
                         cfg_movement_manifest=manifest.name,cfg_transfer_stage='Receipt',items=[receipt_item])
        for wh,sign in (('TRANSIT',-1),('SOURCE',1)):
            self.add('Stock Ledger Entry','RECEIPT-'+wh,voucher_type='Stock Entry',voucher_no=receipt.name,
                     voucher_detail_no=receipt_item.name,warehouse=wh,item_code='B',stock_uom='Nos',
                     actual_qty=sign*2,creation=manifest.dispatch_confirmed_on)
        self.data[LEDGER]['LOCATION'].destination_warehouse='TRANSIT'
        self.add(LEDGER,'RECEIPT-LOCATION',event_type='Location Transfer',source_handling_unit='TAG-B',
            reference_doctype='Stock Entry',reference_name=receipt.name,item_code='B',stock_uom='Nos',stock_qty=2,
            source_company='B',source_warehouse='TRANSIT',destination_company='B',destination_warehouse='SOURCE')
        receipt.docstatus=0
        with self.assertRaisesRegex(ValueError,'RECEIPT-STE'):self.close_plan()
        receipt=self.data['Stock Entry'][receipt.name];receipt.docstatus=1
        before=self.snapshot_stock();result=self.close_plan()
        evidence=json.loads(result['review']['closure_evidence_json'])['returned']
        self.assertEqual(evidence['stock_entries'],['RETURN-STE','RECEIPT-STE'])
        self.assertEqual(evidence['tag_ledgers'],['LOCATION','RECEIPT-LOCATION'])
        self.assertEqual(before,self.snapshot_stock())

    def test_wrong_return_item_batch_uom_tag_quantity_company_lorry_and_destination_are_rejected(self):
        mutations = [('line', {'item_code': 'WRONG'}), ('line', {'batch_no': 'WRONG'}), ('line', {'stock_uom': 'Kg'}),
                     ('line', {'handling_unit': 'WRONG'}), ('line', {'dispatch_qty': 1}), ('manifest', {'source_company': 'A'}),
                     ('manifest', {'source_warehouse': 'OTHER'}), ('warehouse', {'cfg_is_vehicle_warehouse': 1}),
                     ('warehouse', {'company': 'A'}), ('entry', {'docstatus': 0})]
        for target, values in mutations:
            with self.subTest(target=target, values=values):
                self.setUp(); manifest, entry = self.returned()
                {'line': manifest.lines[0], 'manifest': manifest, 'warehouse': self.data['Warehouse']['SOURCE'], 'entry': entry}[target].update(values)
                stock = self.snapshot_stock()
                with self.assertRaises(ValueError): self.close_plan()
                self.assertEqual(self.data[PLAN]['P2'].state, 'Loaded'); self.assertFalse(self.data.get(REVIEW))
                self.assertEqual(stock, self.snapshot_stock())

    def test_missing_return_stock_ledger_and_extra_se_row_are_rejected(self):
        for extra in (False, True):
            self.setUp(); _manifest, entry = self.returned()
            if extra: entry.items.append(Document(entry.items[0], name='EXTRA'))
            else: self.data['Stock Ledger Entry'].clear()
            with self.assertRaisesRegex(ValueError, 'ledger|Manifest'): self.close_plan()

    def test_return_predating_the_load_and_reused_evidence_are_rejected(self):
        self.returned(); self.data[PLAN]['P2'].loaded_on = datetime.datetime(2026, 11, 20, 10)
        with self.assertRaisesRegex(ValueError, 'predates'): self.close_plan()
        self.data[PLAN]['P2'].loaded_on = datetime.datetime(2026, 11, 19, 10)
        self.add(REVIEW, 'OTHER-REVIEW', state='Completed', movement_stock_entry='RETURN-STE')
        with self.assertRaisesRegex(ValueError, 'already settled Review OTHER-REVIEW'): self.close_plan()

    def test_duplicate_plan_closure_with_same_or_new_token_keeps_one_audit_and_return(self):
        self.returned(); self.close_plan(); events = len(self.r.events); stock = self.snapshot_stock()
        self.close_plan(); self.close_plan('SECOND')
        self.assertEqual((len(self.data[REVIEW]), len(self.r.events)), (1, events)); self.assertEqual(stock, self.snapshot_stock())
        with self.assertRaisesRegex(ValueError, 'different details'): self.close_plan(manifest='CHANGED')

    def test_selected_return_and_actual_partial_delivery_outcome_are_retained(self):
        plan = self.data[PLAN]['P2']; self.deliver('P2')
        self.data[SOURCE]['SRC-P2'].allocated_qty = 5; plan.lines[0].loaded_qty = 5
        self.returned(); self.data[MF]['RETURN'].lines[0].update(dispatch_qty=3, received_qty=3)
        self.data['Stock Entry']['RETURN-STE'].items[0].transfer_qty = 3
        for event in self.data['Stock Ledger Entry'].values(): event.actual_qty = 3 if event.warehouse == 'SOURCE' else -3
        result = self.close_plan()
        self.assertEqual(result['plan']['total_delivered_qty'], 2)
        self.assertEqual(result['plan']['fulfilment_status'], 'Closed Incomplete')
        self.assertEqual(json.loads(result['review']['closure_evidence_json'])['deliveries'][0]['delivery_note'], 'DN-P2')

    def test_route_permissions_and_standalone_permissions_remain_required(self):
        self.route(); self.r.operator.kanban_role = 'Operator'
        with self.assertRaisesRegex(ValueError, 'Supervisor'): self.close_route()
        self.r.operator.kanban_role = 'Supervisor'; self.r.allowed = False
        with self.assertRaises(PermissionError): self.close_route()
        self.r.allowed = True; self.r.operator.responsibilities = []
        with self.assertRaisesRegex(PermissionError, 'Reconciliation'): self.close_plan()
        self.assertFalse(self.prohibited)

    def test_standalone_cannot_bypass_linked_sheet_or_required_reason(self):
        self.route()
        with self.assertRaisesRegex(ValueError, 'Close Route'): self.close_plan()
        self.data[PLAN]['P2'].active_route_sheet = None
        with self.assertRaisesRegex(ValueError, 'reason'):
            self.closure.close_dispatch_plan('P2', '', 'EVENT', 'TOKEN')

