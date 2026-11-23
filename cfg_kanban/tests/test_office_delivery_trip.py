"""Office planning contracts over actual functions with offline document/DB doubles.

Native migration, Desk behaviour and MariaDB concurrency require site acceptance.
"""
import copy
import datetime as dt
import json
import math
import re
import uuid
import unittest
from unittest.mock import Mock
from cfg_kanban.tests.test_route_sheets import Doc
from cfg_kanban.tests.test_vehicle_overview import Row, ROOT, load

TRIP = 'CFG Kanban Delivery Trip'
TEMPLATE = 'CFG Kanban Route Template'
PLAN = 'CFG Kanban Dispatch Plan'


def document(value):
    if isinstance(value, dict):return Doc({key:document(item) for key,item in value.items()})
    if isinstance(value, list):return [document(item) for item in value]
    return copy.deepcopy(value)

class TestOfficeDeliveryTrip(unittest.TestCase):
    def setUp(self):
        self.data = {}; self.queries = []; self.reads = []; self.fulfilled = []; self.roles = ['Stock Manager']
        self.frappe = Row(get_doc=self.get_doc, get_list=self.get_list, throw=self.throw,
            as_json=json.dumps, only_for=self.only_for, session=Row(user='planner@example.com'),
            db=Row(sql=self.sql, table_exists=lambda name:True, exists=self.exists, get_value=self.get_value))
        self.ns = load('services/delivery_trips.py', dict(frappe=self.frappe, json=json, math=math, re=re, uuid=uuid,
            cint=lambda value:int(value or 0), flt=lambda value:float(value or 0),
            getdate=lambda value:dt.date.fromisoformat(str(value)[:10]),
            get_datetime=lambda value:dt.datetime.fromisoformat(str(value)), now_datetime=lambda:dt.datetime(2026,11,21,10)))
        self.add('Company','A'); self.add('Company','B')
        self.add('UOM','Nos',must_be_whole_number=1); self.add('UOM','Kg',must_be_whole_number=0)
        for n in (1,2):
            self.add('Customer','C'+str(n),customer_name='Customer '+str(n),disabled=0)
            self.add('Address','A'+str(n),address_line1='Street '+str(n),links=[Doc(link_doctype='Customer',link_name='C'+str(n))])
            self.add('CFG Kanban Customer Scan Point','SITE'+str(n),active=1,selling_company='A',customer='C'+str(n),customer_address='A'+str(n),site_name='Shop '+str(n))
            self.add('Item','ITEM'+str(n),item_name='Item '+str(n),stock_uom='Nos',is_stock_item=1,disabled=0)
            self.add('Sales Order','SO'+str(n),company='A',cfg_delivery_route='ROUTE',customer='C'+str(n),
                shipping_address_name='A'+str(n),docstatus=1,status='To Deliver and Bill',po_no='PO'+str(n),delivery_date='2026-11-22',
                items=[Doc(name='ROW'+str(n),item_code='ITEM'+str(n),item_name='Item '+str(n),stock_uom='Nos',qty=10,delivered_qty=0,conversion_factor=1)])
        self.template = self.add(TEMPLATE,'ROUTE',company='A',active=1,revision=1,region='North',direction='Coastal',sequence_policy='Planned Order',
            stops=[Doc(name='TS1',customer_scan_point='SITE1',customer='C1',customer_address='A1'),Doc(name='TS2',customer_scan_point='SITE2',customer='C2',customer_address='A2')])
        self.add('Warehouse','LORRY',company='A',cfg_is_vehicle_warehouse=1,cfg_vehicle_reference='TRUCK',disabled=0,is_group=0)
        self.add('Warehouse','SOURCE',company='A',disabled=0,is_group=0)
        self.doc = self.trip()

    def throw(self, message, *args):raise ValueError(message)
    def only_for(self, roles):
        if not set(roles).intersection(self.roles):raise PermissionError('Planner role required')
    def add(self, doctype, name, **kw):
        doc = Doc(doctype=doctype,name=name,**kw); self.data.setdefault(doctype,{})[name]=doc;return doc
    def get_doc(self, doctype, name, **kw):
        self.reads.append((doctype,name,kw));return self.data[doctype][name]
    def matches(self, doc, filters):
        for key, value in (filters or {}).items():
            if isinstance(value,list):
                if value[0]=='in' and doc.get(key) not in value[1]:return False
                if value[0]=='not in' and doc.get(key) in value[1]:return False
            elif doc.get(key)!=value:return False
        return True
    def get_list(self,doctype,filters=None,fields=None,pluck=None,**kw):
        rows=[doc for doc in self.data.get(doctype,{}).values() if self.matches(doc,filters) and not doc.get('_hidden')]
        if pluck:
            start=kw.get('limit_start',0);rows=rows[start:start+kw.get('limit_page_length',50)]
            return [row[pluck] for row in rows]
        if fields:return [Doc({field:row.get(field) for field in fields}) for row in rows]
        return rows
    def exists(self,doctype,filters):return any(self.matches(row,filters) for row in self.data.get(doctype,{}).values())
    def get_value(self,doctype,name,field):return self.data.get(doctype,{}).get(name,{}).get(field)
    def sql(self, query, values=None, **kw):
        self.queries.append((query,values));trips=self.data.get(TRIP,{}).values()
        if 'SELECT modified' in query:
            doc=self.data.get(TRIP,{}).get(values[0]);return [Row(modified=doc.modified)] if doc else []
        if 'SELECT assignment.sales_order' in query:
            return [Doc(sales_order=row.sales_order,sales_order_item=row.sales_order_item,planned_qty=row.planned_qty,parent=trip.name)
                    for trip in trips if trip.state in ('Draft','Planned') and trip.name!=values[-1]
                    for row in trip.orders if row.sales_order in values[1:-1]]
        if 'FROM `tabCFG Kanban Delivery Trip Plan` source' in query:
            return [Row(parent=trip.name) for trip in trips if trip.name!=values[-1]
                    for row in trip.dispatch_plans if row.dispatch_plan==values[0]]
        if 'INNER JOIN `tabDelivery Note`' in query:return [r for r in self.fulfilled if r.sales_order in values[1:]]
        return []
    def trip(self):
        snap=self.ns['get_route_template']('ROUTE','A')
        doc=Doc(doctype=TRIP,name=None,state='Draft',company='A',route_template='ROUTE',trip_date='2026-11-22',
            expected_return_date='2026-11-24',driver=None,vehicle_warehouse=None,source_warehouse=None,
            trip_title=None,closure_reason=None,closed_by=None,closed_on=None,planning_revision=0,
            orders=[],dispatch_plans=[],loading_sequence=[],**{k:v for k,v in snap.items() if k not in ('company','route_template','stops')})
        doc.set('stops',snap['stops']);return doc
    def assign(self,doc=None,n=1,qty=4):
        doc=doc or self.doc
        doc.orders.append(Doc(sales_order='SO'+str(n),sales_order_item='ROW'+str(n),stop_key=doc.stops[n-1].stop_key,planned_qty=qty))
        return doc.orders[-1]
    def validate(self,doc=None):self.ns['validate_trip'](doc or self.doc)
    def persist(self,doc=None,name='TRIP1'):
        doc=doc or self.doc;self.validate(doc);doc.name=name;doc.modified='2026-11-21 10:00:00'
        self.data.setdefault(TRIP,{})[name]=document(doc.as_dict())
        doc._before=document(doc.as_dict());return doc
    def plan(self,name='PLAN1',n=1,state='Picking'):
        plan=self.add(PLAN,name,company='A',plan_type='Customer Order',fulfilment_mode='Vehicle Delivery',
            state=state,customer_site='SITE'+str(n),sales_order='SO'+str(n),source_warehouse='SOURCE',vehicle_warehouse=None,
            lines=[Doc(name=name+'-LINE',item_code='ITEM'+str(n),stock_uom='Nos',requested_qty=4)])
        self.doc.dispatch_plans.append(Doc(dispatch_plan=name,stop_sequence=n));return plan
    def allocation(self,name,qty,kind='Tagged Stock',state='Reserved',plan='PLAN1',n=1):
        return self.add('CFG Kanban Dispatch Allocation',name,dispatch_plan=plan,dispatch_plan_line=plan+'-LINE',
            allocation_kind=kind,handling_unit='HU1' if kind=='Tagged Stock' else None,visible_code='RM1' if kind=='Tagged Stock' else None,
            item_code='ITEM'+str(n),batch_no='BATCH',stock_uom='Nos',allocated_qty=qty,state=state,load_confirmed=0)

    def test_template_returns_distinct_stable_stop_ids_and_revision_snapshot(self):
        snap=self.ns['get_route_template']('ROUTE','A')
        self.assertEqual(snap['template_revision'],1);self.assertEqual(snap['region'],'North')
        self.assertNotEqual(snap['stops'][0]['stop_key'],snap['stops'][1]['stop_key'])
        self.assertEqual(json.loads(snap['template_snapshot_json'])['name'],'ROUTE')

    def test_route_template_publishes_gps_defaults_and_allowed_interval(self):
        self.template.gps_auto_start=1;self.template.gps_publish_interval_seconds='120'
        snap=self.ns['get_route_template']('ROUTE','A')
        self.assertEqual(snap['gps_auto_start'],1);self.assertEqual(snap['gps_publish_interval_seconds'],120)

    def test_trip_gps_interval_is_validated_and_driver_display_is_server_derived(self):
        self.add('Employee','EMP',status='Active',employee_name='Ali');self.doc.driver='EMP';self.doc.driver_display='Forged'
        self.doc.gps_publish_interval_seconds='60';self.validate()
        self.assertEqual(self.doc.gps_publish_interval_seconds,'60');self.assertEqual(self.doc.driver_display,'Ali (EMP)')
        self.doc.gps_publish_interval_seconds='61'
        with self.assertRaisesRegex(ValueError,'GPS interval'):self.validate()

    def test_live_gps_change_preserves_departure_even_after_so_was_fully_delivered(self):
        self.assign(qty=10);self.doc.state='Planned';self.persist()
        self.doc.driver_route_state='In Progress';self.doc.driver_route_snapshot_json='FROZEN'
        self.doc.gps_publish_interval_seconds='15';self.data['Sales Order']['SO1']['items'][0].delivered_qty=10
        before=document(self.doc.as_dict());self.doc._before=before;self.doc.gps_publish_interval_seconds='120'
        business=self.ns['_business'](self.doc);self.validate()
        self.assertEqual(self.doc.driver_route_snapshot_json,'FROZEN');self.assertEqual(self.ns['_business'](self.doc),business)
        self.assertEqual(self.doc.gps_publish_interval_seconds,'120')
        self.doc.orders[0].planned_qty=1;self.doc.gps_publish_interval_seconds='300'
        with self.assertRaisesRegex(ValueError,'retain their itinerary'):self.validate()
    def test_inbox_company_permissions_drafts_and_customer_po(self):
        self.data['Sales Order']['SO2'].docstatus=0
        rows=self.ns['get_route_order_inbox']('ROUTE','A')['rows']
        self.assertEqual([r['assignable'] for r in rows],[1,0]);self.assertEqual(rows[0]['customer_po'],'PO1')
        self.data['Sales Order']['SO1']._hidden=True
        self.assertEqual(len(self.ns['get_route_order_inbox']('ROUTE')['rows']),1)
        with self.assertRaisesRegex(ValueError,'Company'):self.ns['get_route_order_inbox']('ROUTE','B')
        self.template._denied=True
        with self.assertRaises(PermissionError):self.ns['get_route_order_inbox']('ROUTE')
    def test_inbox_pages_orders_without_silently_truncating(self):
        data=self.ns['get_route_order_inbox']('ROUTE',page_length=1)
        self.assertTrue(data['has_more']);self.assertEqual(len(data['rows']),1)
        self.assertEqual(self.ns['get_route_order_inbox']('ROUTE',start=1,page_length=1)['rows'][0]['sales_order'],'SO2')
    def test_save_uses_source_stock_uom_conversion(self):
        self.data['Sales Order']['SO1']['items'][0].conversion_factor=2
        self.assign(qty=12);self.validate()
        row=self.doc.orders[0];self.assertEqual((row.item_code,row.stock_uom,row.customer_po),('ITEM1','Nos','PO1'))
        self.assertEqual(self.doc.loading_sequence[0].qty,12)
        self.assertTrue(any(kw.get('for_update') for doctype,name,kw in self.reads if doctype=='Sales Order'))
    def test_invalid_source_quantities_and_conversion_fail_without_mutation(self):
        source=self.data['Sales Order']['SO1']['items'][0]
        self.assign()
        for field,value in [('conversion_factor',0),('qty',float('inf')),('delivered_qty',-2)]:
            old=source[field];source[field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'finite and valid'):self.validate()
            source[field]=old

    def test_duplicate_planning_rejects_overbooking_and_excludes_current_trip(self):
        self.assign(qty=7);self.persist()
        other=self.trip();self.assign(other,qty=4)
        with self.assertRaisesRegex(ValueError,'balance'):self.validate(other)
        other.orders[0].planned_qty=3;self.validate(other)
        self.validate();self.assertEqual(self.doc.orders[0].planned_qty,7)
        inbox=self.ns['get_route_order_inbox']('ROUTE',trip_name='TRIP1')['rows'][0]
        self.assertEqual((inbox['assigned_here'],inbox['unassigned_qty']),(7,3))
    def test_submitted_deliveries_reduce_outstanding_planning_holds(self):
        self.assign(qty=7);self.persist()
        self.data['Sales Order']['SO1']['items'][0].delivered_qty=3
        self.fulfilled=[Row(trip='TRIP1',sales_order='SO1',sales_order_item='ROW1',stock_qty=3,delivery_note_item='DNI1')]*2
        other=self.trip();self.assign(other,qty=3);self.validate(other)
        row=self.ns['get_route_order_inbox']('ROUTE')['rows'][0]
        self.assertEqual((row['assigned_elsewhere'],row['unassigned_qty']),(4,3))
        self.assertTrue(any('note.docstatus=1' in q and 'note.is_return' in q for q,v in self.queries))
    def test_exact_so_item_draft_wrong_route_and_company_rejected(self):
        self.assign();source=self.data['Sales Order']['SO1']
        for field,value in [('docstatus',0),('company','B'),('cfg_delivery_route','OTHER')]:
            old=source[field];source[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.validate()
            source[field]=old
        self.doc.orders[0].sales_order_item='ROW2'
        with self.assertRaisesRegex(ValueError,'belong'):self.validate()
    def test_quantity_precision_whole_and_nonfinite_rejected(self):
        self.assign()
        for qty in (0,-1,float('inf'),float('nan'),1.5):
            self.doc.orders[0].planned_qty=qty
            with self.subTest(qty=qty),self.assertRaises(ValueError):self.validate()
        self.doc.orders[0].planned_qty=1.0000004
        self.data['Sales Order']['SO1']['items'][0].stock_uom='Kg'
        with self.assertRaisesRegex(ValueError,'six decimal'):self.validate()
    def test_customer_address_and_disabled_source_validation(self):
        self.assign();self.doc.stops[0].customer_scan_point='SITE2'
        with self.assertRaisesRegex(ValueError,'Customer'):self.validate()
        self.doc.stops[0].customer_scan_point='SITE1';self.data['Address']['A1'].links=[]
        with self.assertRaisesRegex(ValueError,'Address'):self.validate()
        self.data['Address']['A1'].links=[Doc(link_doctype='Customer',link_name='C1')]
        self.data['Item']['ITEM1'].disabled=1
        with self.assertRaisesRegex(ValueError,'disabled'):self.validate()
    def test_visit_only_no_source_scan_or_load_and_delivery_requires_site(self):
        self.doc.stops[0].update(stop_purpose='Visit Only',customer_scan_point=None)
        self.validate();self.assertEqual(self.doc.loading_sequence,[])
        self.assign()
        with self.assertRaisesRegex(ValueError,'Delivery stop'):self.validate()
        self.doc.orders=[];self.doc.stops[0].stop_purpose='Delivery'
        with self.assertRaisesRegex(ValueError,'Site'):self.validate()
    def test_duplicate_stop_keys_and_inactive_sites_rejected(self):
        self.doc.stops[1].stop_key=self.doc.stops[0].stop_key
        with self.assertRaisesRegex(ValueError,'stable identity'):self.validate()
        self.doc.stops[1].stop_key='UNIQUEKEY';self.data['CFG Kanban Customer Scan Point']['SITE1'].active=0
        with self.assertRaisesRegex(ValueError,'active'):self.validate()
    def test_lifo_reverses_delivery_order_preserves_keys_and_excludes_visits(self):
        self.assign(n=1);self.assign(n=2,qty=2);self.validate()
        self.assertEqual([row.customer for row in self.doc.loading_sequence],['C2','C1'])
        original=self.doc.orders[0].stop_key;self.doc.stops.reverse();self.validate()
        self.assertEqual([row.customer for row in self.doc.loading_sequence],['C1','C2'])
        self.assertEqual(self.doc.orders[0].stop_key,original);self.assertEqual(self.doc.orders[0].stop_sequence,2)
    def test_loading_distinguishes_tagged_untagged_and_not_prepared(self):
        self.assign(qty=6);self.plan();self.allocation('TAG',2,state='Loaded');self.allocation('LOOSE',1,kind='Untagged ERP Stock')
        self.allocation('RELEASED',50,state='Released');self.validate()
        rows=self.doc.loading_sequence;self.assertEqual(sum(row.qty for row in rows),6)
        self.assertEqual({row.source_state for row in rows},{'Loaded','Reserved','Not Prepared'})
        self.assertEqual(sum(row.loaded_qty for row in rows),2)
        self.assertEqual(next(row for row in rows if row.tag_code).tag_code,'RM1')
        self.assertTrue(all(row.customer_po=='PO1' for row in rows))
    def test_nonstock_order_does_not_create_physical_loading_instruction(self):
        self.data['Item']['ITEM1'].is_stock_item=0;self.assign();self.validate()
        self.assertEqual(self.doc.loading_sequence,[])
    def test_plan_budget_company_site_vehicle_and_single_active_trip(self):
        self.assign(qty=3);plan=self.plan()
        with self.assertRaisesRegex(ValueError,'exceed'):self.validate()
        self.doc.orders[0].planned_qty=4
        for field,value in [('company','B'),('customer_site','SITE2'),('fulfilment_mode','Customer Pickup')]:
            old=plan[field];plan[field]=value
            with self.assertRaises(ValueError):self.validate()
            plan[field]=old
        self.doc.vehicle_warehouse='LORRY';plan.vehicle_warehouse='OTHER'
        with self.assertRaisesRegex(ValueError,'lorry'):self.validate()
        plan.vehicle_warehouse='LORRY';self.persist()
        other=self.trip();self.assign(other);other.dispatch_plans=[Doc(dispatch_plan='PLAN1',stop_sequence=1)]
        with self.assertRaisesRegex(ValueError,'another Delivery Trip'):self.validate(other)
    def test_completed_plan_cannot_be_recycled_into_an_unrelated_trip(self):
        self.assign();self.plan(state='Reconciled')
        with self.assertRaisesRegex(ValueError,'newly assigned'):self.validate()

    def test_linked_allocation_cannot_exceed_requested_plan(self):
        self.assign(qty=8);self.plan();self.allocation('TOO-MUCH',5)
        with self.assertRaisesRegex(ValueError,'allocation quantities'):self.validate()
    def test_lorry_driver_company_and_date_requirements(self):
        self.doc.expected_return_date='2026-11-21'
        with self.assertRaisesRegex(ValueError,'Date'):self.validate()
        self.doc.expected_return_date='2026-11-24';self.doc.driver='EMP';self.add('Employee','EMP',status='Left',company='B')
        with self.assertRaisesRegex(ValueError,'active'):self.validate()
        self.doc.driver=None;self.doc.vehicle_warehouse='SOURCE'
        with self.assertRaisesRegex(ValueError,'lorry'):self.validate()
    def test_snapshots_are_pinned_and_reload_requires_no_assignments(self):
        self.assign();self.persist();snapshot=self.doc.template_snapshot_json
        self.template.revision=2;self.template.region='East';self.validate()
        self.assertEqual(self.doc.template_snapshot_json,snapshot)
        self.doc.template_revision=2
        with self.assertRaisesRegex(ValueError,'without orders'):self.validate()
        self.doc.template_revision=1;self.doc.template_snapshot_json='{}'
        with self.assertRaisesRegex(ValueError,'immutable'):self.validate()
    def test_stale_initial_template_revision_is_rejected(self):
        self.template.revision=2
        with self.assertRaisesRegex(ValueError,'changed'):self.validate()
    def test_plan_execution_freezes_core_but_refreshes_loading(self):
        self.assign();plan=self.plan();self.persist();plan.state='Loaded';self.allocation('TAG',4,state='Loaded')
        self.validate();self.assertEqual(self.doc.loading_sequence[0].loaded_qty,4)
        self.doc.stops.reverse()
        with self.assertRaisesRegex(ValueError,'execution'):self.validate()
    def test_loaded_draft_can_receive_status_only_office_signoff_before_departure(self):
        self.assign();plan=self.plan();self.persist();plan.state='Loaded';self.allocation('TAG',4,state='Loaded')
        original=self.ns['_business'](self.doc);revision=self.doc.planning_revision
        self.doc.state='Planned';self.validate()
        self.assertEqual(self.doc.state,'Planned');self.assertEqual(self.doc.planning_revision,revision+1)
        self.assertEqual(self.ns['_business'](self.doc),original)
        self.doc._before=document(self.doc.as_dict());self.doc.state='Draft'
        with self.assertRaisesRegex(ValueError,'execution'):self.validate()

    def test_loaded_draft_signoff_never_allows_source_or_itinerary_changes(self):
        self.assign();plan=self.plan();self.persist();plan.state='Loaded';self.doc.state='Planned'
        self.doc.orders[0].planned_qty=3
        with self.assertRaisesRegex(ValueError,'execution'):self.validate()

    def test_reservations_must_be_released_before_unlinking_plan(self):
        self.assign();self.plan();self.allocation('TAG',1);self.persist();self.doc.dispatch_plans=[]
        with self.assertRaisesRegex(ValueError,'reservations'):self.validate()
    def test_cancel_close_require_reason_settlement_and_retain_history(self):
        self.assign();plan=self.plan();self.persist();self.doc.state='Cancelled'
        with self.assertRaisesRegex(ValueError,'reason'):self.validate()
        self.doc.closure_reason='Changed trip'
        with self.assertRaisesRegex(ValueError,'Settle'):self.validate()
        plan.state='Cancelled';self.validate();self.assertEqual(self.doc.closed_by,'planner@example.com')
        self.assertEqual(len(self.doc.orders),1)
        self.data[TRIP]['TRIP1']=document(self.doc.as_dict());self.doc._before=document(self.doc.as_dict())
        self.doc.state='Draft'
        with self.assertRaisesRegex(ValueError,'history'):self.validate()
        other=self.trip();self.assign(other,qty=10);self.validate(other)
    def test_terminal_history_and_derived_fields_cannot_be_rewritten(self):
        self.assign();self.persist();self.doc.state='Closed';self.doc.closure_reason='No dispatch';self.validate()
        self.doc._before=document(self.doc.as_dict());self.doc.orders[0].item_code='FORGED';self.doc.closure_reason='Changed'
        self.validate();self.assertEqual(self.doc.orders[0].item_code,'ITEM1');self.assertEqual(self.doc.closure_reason,'No dispatch')
    def test_stale_save_and_unauthorized_mutation_rejected(self):
        self.persist();self.data[TRIP]['TRIP1'].modified='2026-11-21 10:01:00'
        with self.assertRaisesRegex(ValueError,'another planner'):self.validate()
        self.roles=['Stock User']
        with self.assertRaises(PermissionError):self.validate()
    def test_so_route_customer_company_and_active_assignment_guards(self):
        self.assign();self.persist()
        order=self.data['Sales Order']['SO1'];order._before=document(order.as_dict());order.cfg_delivery_route=None
        with self.assertRaisesRegex(ValueError,'Release'):self.ns['validate_sales_order_route'](order)
        self.data[TRIP]['TRIP1'].state='Cancelled';self.ns['validate_sales_order_route'](order)
        order._before=None;order.cfg_delivery_route='ROUTE';order.customer='OTHER'
        with self.assertRaisesRegex(ValueError,'Customer'):self.ns['validate_sales_order_route'](order)
    def test_native_so_feedback_continues_when_route_unchanged_even_if_inactive(self):
        order=self.data['Sales Order']['SO1'];order._before=document(order.as_dict());self.template.active=0
        order['items'][0].delivered_qty=2;self.ns['validate_sales_order_route'](order)
    def test_office_grids_fit_quantity_and_identity_columns(self):
        for folder in ('cfg_kanban_delivery_trip_stop','cfg_kanban_delivery_trip_order',
                       'cfg_kanban_delivery_trip_plan','cfg_kanban_delivery_trip_load','cfg_kanban_route_template_stop'):
            schema=json.loads((ROOT/'cfg_kanban/doctype'/folder/(folder+'.json')).read_text())
            displayed=[f for f in schema['fields'] if f.get('in_list_view')]
            self.assertLessEqual(sum(f.get('columns',2) for f in displayed),10,folder)
            if folder in ('cfg_kanban_delivery_trip_order','cfg_kanban_delivery_trip_load'):
                self.assertTrue(any(f['fieldname'] in ('qty','planned_qty') for f in displayed))

    def test_read_only_preview_does_not_save_or_touch_stock(self):
        self.assign();self.plan();self.persist();before=self.doc.as_dict()
        result=self.ns['get_loading_sequence']('TRIP1')
        self.assertEqual(result['rows'][0]['source_state'],'Not Prepared');self.assertEqual(self.doc.as_dict(),before)
        self.assertFalse(any('Stock Entry' in q or 'UPDATE ' in q.upper() or 'INSERT ' in q.upper() for q,v in self.queries))
    def test_normal_schema_workspace_and_native_source_hooks(self):
        folder=ROOT/'cfg_kanban/doctype'
        for suffix in ('','_stop','_order','_plan','_load'):
            path=folder/('cfg_kanban_delivery_trip'+suffix)/('cfg_kanban_delivery_trip'+suffix+'.json');schema=json.loads(path.read_text())
            self.assertEqual(schema['name'], 'CFG Kanban Delivery Trip'+(' '+suffix[1:].title() if suffix else ''))
            self.assertIn(schema['name'].replace(' ',''),path.with_suffix('.py').read_text())
        schema=json.loads((folder/'cfg_kanban_delivery_trip/cfg_kanban_delivery_trip.json').read_text())
        self.assertFalse(schema.get('quick_entry'));self.assertFalse(any(r.get('delete') for r in schema['permissions']))
        fields={r['fieldname']:r for r in schema['fields']};self.assertTrue(fields['loading_sequence']['read_only'])
        hooks=(ROOT/'hooks.py').read_text();self.assertIn('sales_order_feedback.on_submit',hooks);self.assertIn('delivery_trips.validate_sales_order_route',hooks)
        workspace=json.loads((ROOT/'cfg_kanban/workspace/cfg_dispatch_control/cfg_dispatch_control.json').read_text())
        self.assertIn(TRIP,{r.get('link_to') for r in workspace['shortcuts']})
        custom=load('install.py',{})['_custom_fields']()['Sales Order'];route=next(f for f in custom if f['fieldname']=='cfg_delivery_route')
        self.assertEqual(route['options'],TEMPLATE);self.assertEqual(route['allow_on_submit'],1)

if __name__=='__main__':unittest.main()
