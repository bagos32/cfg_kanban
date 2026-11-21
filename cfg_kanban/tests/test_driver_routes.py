"""Driver route visibility over actual functions using offline source-document doubles."""
import datetime
import math
import json
import unittest
from unittest.mock import Mock
from cfg_kanban.tests import test_office_delivery_trip as office
from cfg_kanban.tests.test_vehicle_overview import Row, ROOT, load

SESSION='CFG Kanban Delivery Session'
NOTE='Delivery Note'
DA='CFG Kanban Delivery Allocation'

class TestDriverRoutes(unittest.TestCase):
    def setUp(self):
        self.b=office.TestOfficeDeliveryTrip();self.b.setUp();self.data=self.b.data
        self.operator=office.Doc(employee='EMP',kanban_role='Operator',view_all_responsibilities=0,
            responsibilities=[office.Doc(responsibility='Customer Delivery')])
        self.b.frappe.PermissionError=PermissionError
        self.b.frappe.throw=self.throw
        self.b.frappe.get_all=self.get_all
        self.auth=Mock(side_effect=self.require_operator)
        self.engine=Row(_require_customer_delivery=self.require_delivery,
            _can_view_delivery=lambda profile,delivery:profile.employee==delivery.started_by_operator or bool(profile.view_all_responsibilities and profile.kanban_role=='Supervisor'))
        self.ns=load('services/driver_routes.py',dict(frappe=self.b.frappe,math=math,
            cint=lambda value:int(value or 0),flt=lambda value:float(value or 0),
            now_datetime=lambda:datetime.datetime(2026,11,21,14),require_operator=self.auth,
            public_operator=lambda profile,session:dict(employee=profile.employee,employee_name='Driver',kanban_role=profile.kanban_role)))
        self.ns['_delivery']=lambda:self.engine
        self.b.assign(qty=4);self.b.assign(n=2,qty=2)
        self.p1=self.b.plan('PLAN1');self.p2=self.b.plan('PLAN2',n=2);self.p2.lines[0].requested_qty=2
        self.b.add('Employee','EMP',status='Active',company='A')
        self.b.doc.driver='EMP';self.b.persist(name='KTRIP-2026-00001')
        self.trip=self.data[office.TRIP]['KTRIP-2026-00001'];self.keys=[row.stop_key for row in self.trip.stops]
        for n,plan in enumerate((self.p1,self.p2),1):
            plan.update(state='Loaded',customer='C'+str(n),vehicle_warehouse='LORRY',movement_manifest='MAN'+str(n))
            self.b.add('CFG Kanban Movement Manifest','MAN'+str(n),source_company='A',destination_warehouse='LORRY',dispatch_stock_entry='SE'+str(n))
            self.b.add('Stock Entry','SE'+str(n),company='A',docstatus=1)
            self.b.allocation('ALLOC'+str(n),4 if n==1 else 2,plan=plan.name,n=n,state='Loaded').visible_code='RM'+str(n)
    def throw(self,message,kind=ValueError):raise kind(message)
    def require_operator(self,token,**kwargs):
        if token!='TOKEN':raise ValueError('Operator session is not active')
        return self.operator,office.Doc(name='SESSION')
    def require_delivery(self,profile):
        if not any(row.responsibility=='Customer Delivery' for row in profile.responsibilities):raise PermissionError('Customer Delivery required')
    def get_all(self,doctype,filters=None,pluck=None,**kwargs):
        rows=[row for row in self.data.get(doctype,{}).values() if self.b.matches(row,filters)]
        return [row[pluck] for row in rows] if pluck else rows
    def read(self):return self.ns['get_driver_trip'](self.trip.name,'TOKEN')
    def queue(self,**kwargs):return self.ns['get_driver_trips']('TOKEN',**kwargs)
    def delivery(self,n=1,state='Closed',qty=None,note_status=1,owner='EMP'):
        plan=self.p1 if n==1 else self.p2;qty=(4 if n==1 else 2) if qty is None else qty
        plan.update(delivery_session='DEL'+str(n),fulfilment_status='Completed' if state=='Closed' else 'Delivered' if state in ('Delivered','Invoiced') else 'In Progress')
        session=self.b.add(SESSION,'DEL'+str(n),dispatch_plan=plan.name,selling_company='A',customer_scan_point='SITE'+str(n),customer='C'+str(n),
            state=state,delivery_note='DN'+str(n),started_by_operator=owner)
        self.b.add(NOTE,'DN'+str(n),company='A',customer='C'+str(n),docstatus=note_status,is_return=0)
        if qty:
            self.b.add(DA,'USAGE'+str(n),dispatch_allocation='ALLOC'+str(n),delivery_session=session.name,state='Delivered',delivered_qty=qty)
        return session
    def sheet(self,order=(2,1),state='Approved'):
        sheet=self.b.add('CFG Kanban Route Sheet','SHEET',company='A',vehicle_warehouse='LORRY',state=state,sequence_policy='Planned Order',verification_policy='Require Customer Site QR',
            stops=[office.Doc(dispatch_plan='PLAN'+str(n),customer_scan_point='SITE'+str(n)) for n in order])
        for plan in (self.p1,self.p2):plan.active_route_sheet=sheet.name;plan.route_approval_required=1
        return sheet

    def test_assigned_trip_queue_has_no_date_cutoff_and_reads_native_permissions(self):
        self.trip.trip_date='2026-11-19';self.trip.expected_return_date='2026-11-22'
        result=self.queue();self.assertEqual(result['trips'][0]['name'],self.trip.name)
        self.assertEqual(result['operator']['employee'],'EMP')
        self.assertEqual(result['trips'][0]['planning_state'],'Draft')
        self.auth.assert_called_with('TOKEN',touch_activity=False)
        self.trip._hidden=True;self.assertEqual(self.queue()['trips'],[])
    def test_unassigned_other_driver_and_native_company_denials_do_not_leak(self):
        self.trip.driver='OTHER';self.assertEqual(self.queue()['trips'],[])
        with self.assertRaises(PermissionError):self.read()
        self.trip.driver=None
        with self.assertRaises(PermissionError):self.read()
        self.trip.driver='EMP';self.data['Company']['A']._denied=True
        with self.assertRaises(PermissionError):self.read()
    def test_supervisor_scope_requires_both_role_and_view_all_and_native_read(self):
        self.trip.driver='OTHER';self.operator.view_all_responsibilities=1
        with self.assertRaises(PermissionError):self.read()
        self.operator.kanban_role='Supervisor';self.assertEqual(len(self.queue()['trips']),1)
        self.trip._denied=True
        with self.assertRaises(PermissionError):self.read()
    def test_customer_delivery_responsibility_and_valid_session_are_required(self):
        self.operator.responsibilities=[]
        with self.assertRaises(PermissionError):self.queue()
        with self.assertRaises(ValueError):self.ns['get_driver_trip'](self.trip.name,'BAD')
    def test_terminal_trip_history_is_opt_in_and_never_proposes_next_stop(self):
        self.trip.state='Closed';self.assertEqual(self.queue()['trips'],[])
        self.assertEqual(len(self.queue(include_closed=1)['trips']),1)
        self.assertIsNone(self.read()['next_stop_key'])
    def test_planned_loaded_tagged_and_untagged_quantities_keep_stock_uom(self):
        self.data[office.PLAN]['PLAN2'].state='Picking';self.data['Stock Entry']['SE2'].docstatus=0
        alloc=self.data['CFG Kanban Dispatch Allocation']['ALLOC2'];alloc.allocation_kind='Untagged ERP Stock';alloc.visible_code='INTERNAL'
        result=self.read();self.assertTrue(result['read_only']);self.assertEqual(result['next_stop_key'],self.keys[0])
        item=result['stops'][0]['items'][0];self.assertEqual((item['planned_qty'],item['loaded_qty'],item['remaining_qty']),(4,4,4))
        source=result['stops'][1]['sources'][0];self.assertIsNone(source['tag_code']);self.assertEqual(source['loaded_qty'],0)
        self.assertEqual(result['stops'][1]['items'][0]['stock_uom'],'Nos')
    def test_unprepared_order_balance_never_means_the_full_stop_is_loaded(self):
        self.trip.orders[0].planned_qty=6
        stop=self.read()['stops'][0]
        self.assertEqual(stop['state'],'Partially loaded')
        self.assertEqual(stop['items'][0]['unprepared_qty'],2)

    def test_draft_or_cancelled_stock_entry_never_means_loaded(self):
        for state in (0,2):
            self.data['Stock Entry']['SE1'].docstatus=state
            result=self.read();self.assertEqual(result['stops'][0]['items'][0]['loaded_qty'],0)
            self.assertNotEqual(result['stops'][0]['state'],'Loaded')
    def test_partial_posted_delivery_reduces_assigned_remaining_without_advancing_proof(self):
        self.delivery(state='Delivered',qty=2)
        result=self.read();stop=result['stops'][0];item=stop['items'][0]
        self.assertEqual((item['delivered_qty'],item['remaining_qty']),(2,2))
        self.assertEqual(stop['state'],'Awaiting proof');self.assertEqual(result['current_stop_key'],self.keys[0])
        self.assertEqual(result['next_stop_key'],self.keys[0])
    def test_native_closed_full_delivery_advances_to_next_stop(self):
        self.delivery();result=self.read()
        self.assertEqual(result['stops'][0]['state'],'Completed');self.assertEqual(result['completed_stops'],1)
        self.assertEqual(result['next_stop_key'],self.keys[1])
    def test_draft_cancelled_or_return_note_never_counts_as_delivery(self):
        self.delivery(state='Closed',note_status=0)
        for note_status in (0,2):
            self.data[NOTE]['DN1'].docstatus=note_status
            result=self.read();self.assertEqual(result['stops'][0]['items'][0]['delivered_qty'],0)
            self.assertEqual(result['stops'][0]['state'],'Review required')
        self.data[NOTE]['DN1'].update(docstatus=1,is_return=1)
        self.assertEqual(self.read()['stops'][0]['items'][0]['delivered_qty'],0)
    def test_pending_erp_document_stays_current_and_cannot_skip_to_other_customer(self):
        self.delivery(state='ERP Document Pending',qty=0,note_status=0)
        result=self.read();self.assertEqual(result['stops'][0]['state'],'Delivery Note pending')
        self.assertEqual(result['current_stop_key'],self.keys[0])
    def test_native_session_owner_is_preserved_in_existing_workflow_handoff(self):
        self.delivery(state='Allocating',qty=0,note_status=0,owner='OTHER')
        plan=self.read()['stops'][0]['plans'][0]
        self.assertFalse(plan['session_accessible']);self.assertIsNone(plan['delivery_session'])
    def test_approved_order_overrides_office_sequence_without_mutating_trip(self):
        self.sheet();before=self.trip.as_dict();result=self.read()
        self.assertEqual([s['stop_key'] for s in result['stops']],list(reversed(self.keys)))
        self.assertEqual(result['sequence_source'],'Approved Route Sheet');self.assertEqual(result['next_stop_key'],self.keys[1])
        self.assertEqual(self.trip.as_dict(),before)
    def test_draft_route_sheet_has_no_approved_order_authority(self):
        self.sheet(state='Draft');result=self.read()
        self.assertEqual(result['sequence_source'],'Office plan');self.assertEqual(result['next_stop_key'],self.keys[0])
        self.assertTrue(any('approval' in warning for warning in result['warnings']))
    def test_unmapped_or_repeated_operational_stop_never_silently_selects_another_customer(self):
        sheet=self.sheet();sheet.stops.append(office.Doc(dispatch_plan='OTHER',customer_scan_point='PRIVATE'))
        result=self.read();self.assertEqual(result['sequence_source'],'Office plan')
        self.assertNotIn('PRIVATE',json.dumps(result,default=str));self.assertTrue(result['warnings'])
        sheet.stops=[sheet.stops[0],sheet.stops[0],sheet.stops[1]]
        self.assertEqual(self.read()['sequence_source'],'Office plan')
    def test_visit_only_is_displayed_and_never_invents_delivery_or_completion(self):
        visit=office.Doc(stop_key='VISIT_KEY',delivery_sequence=3,stop_purpose='Visit Only',customer='C1',site_name='Collect information',instructions='Ask for forecast',address_display='Street 1')
        self.trip.stops.insert(0,visit);self.sheet();result=self.read()
        self.assertEqual(result['stops'][0]['state'],'Visit planned');self.assertEqual(result['stops'][0]['items'],[])
        self.assertEqual(result['next_stop_key'],'VISIT_KEY');self.assertEqual(result['sequence_source'],'Office plan')
    def test_multiple_live_sessions_and_lorries_require_review_without_guessing_next(self):
        self.delivery(state='Allocating',qty=0,note_status=0);self.delivery(n=2,state='Allocating',qty=0,note_status=0)
        self.assertIsNone(self.read()['next_stop_key'])
        self.data['Warehouse']['LORRY2']=office.Doc(name='LORRY2',company='A');self.p2.vehicle_warehouse='LORRY2'
        self.data['CFG Kanban Movement Manifest']['MAN2'].destination_warehouse='LORRY2'
        self.assertIsNone(self.read()['next_stop_key'])
    def test_permission_restricted_allocations_fail_instead_of_silently_understating_quantities(self):
        self.data['CFG Kanban Dispatch Allocation']['ALLOC1']._denied=True
        with self.assertRaises(PermissionError):self.read()
    def test_source_company_site_stock_uom_and_quantity_mismatch_reject(self):
        old=self.p1.company;self.p1.company='B'
        with self.assertRaises(ValueError):self.read()
        self.p1.company=old;self.data['CFG Kanban Dispatch Allocation']['ALLOC1'].stock_uom='Kg'
        with self.assertRaises(ValueError):self.read()
    def test_all_sources_and_office_records_remain_unchanged_on_read(self):
        self.delivery(state='Delivered',qty=2);self.sheet()
        before={doctype:{name:doc.as_dict() for name,doc in docs.items()} for doctype,docs in self.data.items()}
        self.b.queries.clear();self.read();self.queue()
        after={doctype:{name:doc.as_dict() for name,doc in docs.items()} for doctype,docs in self.data.items()}
        self.assertEqual(before,after)
        self.assertFalse(self.b.queries,'The read page must not acquire planning/execution row locks')
    def test_manual_use_touches_session_activity_but_background_reads_do_not(self):
        self.ns['get_driver_trip'](self.trip.name,'TOKEN',interactive=1)
        self.auth.assert_called_with('TOKEN',touch_activity=True)
        self.read();self.auth.assert_called_with('TOKEN',touch_activity=False)

    def test_closed_history_paging_and_inactive_template_do_not_hide_saved_trips(self):
        self.trip.state='Closed';self.b.template.active=0
        self.assertEqual(self.queue()['trips'],[])
        self.assertEqual(len(self.queue(include_closed=1)['trips']),1)
        self.assertIsNone(self.read()['next_stop_key'])
        self.trip.state='Planned'
        clone=office.document(self.trip.as_dict());clone.name='KTRIP-2026-00002';self.data[office.TRIP][clone.name]=clone
        self.assertTrue(self.queue(page_length=1)['has_more'])
        self.assertEqual(self.queue(page_length=1,start=1)['trips'][0]['name'],clone.name)

    def test_page_and_launchers_exist_without_adding_stock_mutation_api(self):
        folder=ROOT/'cfg_kanban/page/kanban_driver_route'
        schema=json.loads((folder/'kanban_driver_route.json').read_text());self.assertEqual(schema['name'],'kanban-driver-route')
        office_form=(ROOT/'cfg_kanban/doctype/cfg_kanban_delivery_trip/cfg_kanban_delivery_trip.js').read_text()
        self.assertIn("frappe.set_route('kanban-driver-route', frm.doc.name)",office_form)
        workspace=json.loads((ROOT/'cfg_kanban/workspace/cfg_dispatch_control/cfg_dispatch_control.json').read_text())
        self.assertTrue(any(row.get('link_to')=='kanban-driver-route' for row in workspace['shortcuts']))

if __name__=='__main__':unittest.main()
