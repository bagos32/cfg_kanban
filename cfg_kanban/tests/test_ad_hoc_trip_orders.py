"""Trip-specific unrouted SO planning over actual functions and offline dependencies.

Native Desk/permissions/SQL locking and ERP posting still require test-site acceptance.
"""
import copy
import json
import unittest

from cfg_kanban.tests import test_office_delivery_trip as office
from cfg_kanban.tests import test_trip_dispatch as dispatch
from cfg_kanban.tests import test_consolidated_dispatch as consolidated_fixture


class TestAdHocTripOrders(unittest.TestCase):
    def setUp(self):
        self.t = office.TestOfficeDeliveryTrip(); self.t.setUp()
        self.data = self.t.data; self.doc = self.t.doc; self.ns = self.t.ns
        self.t.add('Customer','C3',customer_name='Ad Hoc Customer',disabled=0)
        self.t.add('Address','A3',address_line1='Ad Hoc Road',links=[office.Doc(link_doctype='Customer',link_name='C3')])
        self.t.add('CFG Kanban Customer Scan Point','SITE3',active=1,selling_company='A',customer='C3',customer_address='A3',site_name='Ad Hoc Shop')
        self.order = self.t.add('Sales Order','SO3',company='A',cfg_delivery_route=None,customer='C3',
            shipping_address_name='A3',docstatus=1,status='To Deliver and Bill',po_no='ADHOC-PO',delivery_date='2026-11-28',
            items=[office.Doc(name='ROW3',item_code='ITEM1',item_name='Item 1',stock_uom='Nos',qty=10,delivered_qty=0,conversion_factor=1)])
        self.stop = office.Doc(stop_key='ADHOC_STOP',stop_purpose='Delivery',customer_scan_point='SITE3',customer='C3',customer_address='A3')
        self.doc.stops.append(self.stop)

    def inbox(self, **kwargs):
        return self.ns['get_route_order_inbox']('ROUTE','A',trip_stops=[row.as_dict() for row in self.doc.stops],**kwargs)

    def assign(self, doc=None, qty=4):
        doc = doc or self.doc
        row = office.Doc(stop_key='ADHOC_STOP',sales_order='SO3',sales_order_item='ROW3',planned_qty=qty)
        doc.orders.append(row); return row

    def test_ad_hoc_customer_not_in_template_and_unrouted_so_visible_in_unsaved_trip(self):
        self.assertNotIn('C3',[row.customer for row in self.t.template.stops])
        row = next(row for row in self.inbox()['rows'] if row['sales_order']=='SO3')
        self.assertEqual((row['customer'],row['customer_po'],row['unassigned_qty'],row['assignable']),('C3','ADHOC-PO',10,1))
        self.assertIsNone(row['standard_route'])
        self.assertNotIn('SO3',[row['sales_order'] for row in self.ns['get_route_order_inbox']('ROUTE')['rows']])

    def test_json_editor_stops_and_saved_trip_fallback_both_include_unrouted_order(self):
        self.t.persist()
        for kwargs in ({'trip_stops':json.dumps([row.as_dict() for row in self.doc.stops])},{'trip_name':'TRIP1'}):
            rows=self.ns['get_route_order_inbox']('ROUTE','A',**kwargs)['rows']
            self.assertIn('SO3',[row['sales_order'] for row in rows])

    def test_saved_trip_uses_new_unsaved_stop_before_next_save(self):
        self.doc.stops.pop(); self.t.persist(); self.doc.stops.append(self.stop)
        rows=self.inbox(trip_name='TRIP1')['rows']
        self.assertIn('SO3',[row['sales_order'] for row in rows])
        self.assertNotIn('SO3',[row['sales_order'] for row in self.ns['get_route_order_inbox']('ROUTE',trip_name='TRIP1')['rows']])

    def test_save_assigns_exact_ad_hoc_so_line_and_preserves_so_route_and_template(self):
        template=copy.deepcopy(self.t.template.as_dict()); order=copy.deepcopy(self.order.as_dict())
        row=self.assign(); self.t.persist()
        self.assertEqual((row.customer,row.customer_po,row.item_code,row.stock_uom,row.planned_qty),('C3','ADHOC-PO','ITEM1','Nos',4))
        self.assertEqual(self.doc.loading_sequence[0].customer,'C3')
        self.assertEqual(template,self.t.template.as_dict()); self.assertEqual(order,self.order.as_dict())
        self.assertTrue(any(dt=='Sales Order' and name=='SO3' and kw.get('for_update') for dt,name,kw in self.t.reads))

    def test_already_routed_to_another_template_stays_excluded_and_rejected_on_save(self):
        self.order.cfg_delivery_route='OTHER'
        self.assertNotIn('SO3',[row['sales_order'] for row in self.inbox()['rows']])
        self.assign()
        with self.assertRaisesRegex(ValueError,'Company and Standard Route'): self.t.validate()

    def test_unrouted_default_order_reader_remains_strict_outside_trip_assignment(self):
        with self.assertRaisesRegex(ValueError,'Standard Route'): self.ns['_order']('SO3','A','ROUTE')

    def test_company_customer_address_and_site_permissions_are_retained(self):
        for field,value in (('company','B'),('customer','C1'),('shipping_address_name','A1')):
            with self.subTest(field=field):
                old=self.order[field]; self.order[field]=value
                self.assertNotIn('SO3',[row['sales_order'] for row in self.inbox()['rows']])
                self.assign()
                with self.assertRaises(ValueError):self.t.validate()
                self.doc.orders.clear(); self.order[field]=old
        site=self.data['CFG Kanban Customer Scan Point']['SITE3'];site.selling_company='B'
        with self.assertRaisesRegex(ValueError,'Company'):self.inbox()
        site.selling_company='A';site._denied=True
        with self.assertRaises(PermissionError):self.inbox()

    def test_no_order_shipping_address_can_match_explicit_customer_site(self):
        self.order.shipping_address_name=None
        self.assertIn('SO3',[row['sales_order'] for row in self.inbox()['rows']])
        self.assign();self.t.validate()

    def test_drafts_are_information_only_and_terminal_orders_are_not_assignable(self):
        self.order.docstatus=0
        row=next(row for row in self.inbox()['rows'] if row['sales_order']=='SO3')
        self.assertEqual(row['assignable'],0);self.assign()
        with self.assertRaisesRegex(ValueError,'submitted'):self.t.validate()
        self.order.docstatus=1
        for status in ('Closed','Completed','Cancelled','On Hold'):
            self.order.status=status
            self.assertNotIn('SO3',[row['sales_order'] for row in self.inbox()['rows']])
            with self.assertRaisesRegex(ValueError,'no longer open'):self.t.validate()

    def test_native_order_visibility_and_read_permissions_are_not_bypassed(self):
        self.order._hidden=True
        self.assertNotIn('SO3',[row['sales_order'] for row in self.inbox()['rows']])
        self.order._hidden=False; self.order._denied=True
        with self.assertRaises(PermissionError):self.inbox()
        self.assign()
        with self.assertRaises(PermissionError):self.t.validate()

    def test_spoofed_customer_is_derived_from_real_site_and_visit_only_has_no_order_assignment(self):
        rows=self.ns['get_route_order_inbox']('ROUTE','A',trip_stops=[dict(customer='C3',customer_scan_point='SITE1')])['rows']
        self.assertEqual({row['customer'] for row in rows},{'C1'})
        for stops in ([],[dict(stop_purpose='Visit Only',customer='C3',customer_scan_point='SITE3')],
                      [dict(stop_purpose='Delivery',customer='C3')]):
            self.assertEqual(self.ns['get_route_order_inbox']('ROUTE','A',trip_stops=stops)['rows'],[])

    def test_cancelled_saved_stop_cannot_be_restored_to_inbox_by_omitting_its_flag(self):
        self.t.persist()
        self.data[office.TRIP]['TRIP1'].stops[-1].cancellation_request='CANCELLED-STOP'
        self.doc.stops[-1].cancellation_request=None
        self.assertNotIn('SO3',[row['sales_order'] for row in self.inbox(trip_name='TRIP1')['rows']])

    def test_ad_hoc_assignment_preserves_remaining_qty_conversion_and_current_trip_budget(self):
        self.order['items'][0].conversion_factor=2
        self.assign(qty=12);self.t.persist()
        row=next(row for row in self.inbox(trip_name='TRIP1')['rows'] if row['sales_order']=='SO3')
        self.assertEqual((row['assigned_here'],row['unassigned_qty']),(12,8))
        other=self.t.trip();other.stops.append(office.Doc(self.stop.as_dict()));self.assign(other,qty=9)
        with self.assertRaisesRegex(ValueError,'balance'):self.t.validate(other)
        other.orders[0].planned_qty=8;self.t.validate(other)

    def test_unrouted_so_cannot_be_overbooked_by_a_trip_using_another_template(self):
        self.assign(qty=7);self.t.persist()
        self.t.add(office.TEMPLATE,'OTHER',company='A',active=1,revision=1,sequence_policy='Flexible Order',stops=[])
        other=self.t.trip();other.route_template='OTHER';other.stops.append(office.Doc(self.stop.as_dict()))
        self.assign(other,qty=4)
        with self.assertRaisesRegex(ValueError,'balance'):self.t.validate(other)
        other.orders[0].planned_qty=3;self.t.validate(other)

    def test_inbox_pagination_and_nonroute_candidates_remain_scoped(self):
        found=[];start=0
        while True:
            page=self.inbox(start=start,page_length=1)
            found.extend(row['sales_order'] for row in page['rows'])
            if not page['has_more']:break
            start+=page['page_length']
        self.assertEqual(found,['SO1','SO2','SO3'])
        self.order.cfg_delivery_route='OTHER'
        self.assertEqual({row['sales_order'] for row in self.inbox()['rows']},{'SO1','SO2'})

    def test_malformed_scope_and_foreign_saved_trip_are_rejected(self):
        for raw in ('{bad','{}','[1]'):
            with self.subTest(raw=raw),self.assertRaisesRegex(ValueError,'list of customer stops'):
                self.ns['get_route_order_inbox']('ROUTE','A',trip_stops=raw)
        self.t.persist();self.data[office.TRIP]['TRIP1'].company='B'
        with self.assertRaisesRegex(ValueError,'Trip does not match'):self.inbox(trip_name='TRIP1')


class TestAdHocDispatchGeneration(unittest.TestCase):
    def test_unrouted_ad_hoc_customer_generates_exact_dispatch_in_separate_and_consolidated_modes(self):
        for consolidated in (False,True):
            with self.subTest(consolidated=consolidated):
                t=dispatch.TestTripDispatch();t.setUp();self.addCleanup(t.doCleanups)
                order=t.data['Sales Order']['SO2'];order.cfg_delivery_route=None
                t.data[office.TEMPLATE]['ROUTE'].stops=t.data[office.TEMPLATE]['ROUTE'].stops[:1]
                stop=t.trip.stops[1];stop.stop_purpose='Delivery'
                t.b.assign(t.trip,n=2,qty=3)
                t.trip.consolidated_customer_orders=int(consolidated)
                if consolidated:
                    original=t.b.get_list
                    t.b.frappe.get_all=lambda dt,**kw:original(dt,**{key:value for key,value in kw.items() if key!='limit_page_length' or value})
                    consolidated_fixture.install(self,t.b.frappe,t.mod.canonical_key)
                t.trip.state='Draft';t.trip.save();t.trip.state='Planned'
                t.generate()
                plans=[row for row in t.plans() if row.plan_type=='Customer Order']
                self.assertEqual(len(plans),1 if consolidated else 2)
                plan=next(row for row in plans if consolidated or row.sales_order=='SO2')
                line=next(row for row in plan.lines if row.sales_order_item=='ROW2')
                self.assertEqual((line.item_code,line.requested_qty),('ITEM2',3))
                self.assertIsNone(order.cfg_delivery_route);t.ledger.assert_not_called()


if __name__=='__main__':unittest.main()
