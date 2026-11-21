"""Actual office generation/controller/quantity behavior with offline documents; native DB acceptance remains separate."""
import copy,datetime,hashlib,json,sys,types,unittest
from unittest.mock import Mock,patch
from cfg_kanban.tests import test_office_delivery_trip as base
from cfg_kanban.tests.test_vehicle_overview import load,ROOT

PLAN='CFG Kanban Dispatch Plan';STOP='CFG Kanban Route Stop'

class TestTripDispatch(unittest.TestCase):
    def setUp(self):
        self.b=base.TestOfficeDeliveryTrip();self.b.setUp();self.data=self.b.data
        self.b.assign(qty=4);self.b.doc.stops[1].stop_purpose='Visit Only';self.b.persist()
        self.events=Mock();self.ledger=Mock(side_effect=AssertionError('Generation must not move stock'))
        common=dict(frappe=self.b.frappe,json=json,hashlib=hashlib,cint=lambda n:int(n or 0),flt=lambda n:float(n or 0),
            now_datetime=lambda:datetime.datetime(2026,11,21,12),get_datetime=lambda v:datetime.datetime.fromisoformat(str(v)),
            canonical_key=lambda *v:hashlib.sha256(json.dumps(v,sort_keys=True,default=str).encode()).hexdigest(),record=self.events,
            post_quantity_event=self.ledger,Document=base.Doc,require_operator=Mock(side_effect=AssertionError('Office must not fabricate an operator session')))
        self.planning=types.ModuleType('cfg_kanban.services.dispatch_planning');self.planning.__dict__.update(load('services/dispatch_planning.py',dict(common)))
        self.planning._validate_batch=Mock();self.planning._vehicle_warehouse=lambda name,company: self.data['Warehouse'][name]
        self.office=types.ModuleType('cfg_kanban.services.delivery_trips');self.office.__dict__.update(self.b.ns)
        self.mod=types.ModuleType('cfg_kanban.services.trip_dispatch');self.mod.__dict__.update(load('services/trip_dispatch.py',dict(common)))
        self.routes=types.ModuleType('cfg_kanban.services.route_delivery');self.routes.__dict__.update(load('services/route_delivery.py',dict(common)))
        self.routes._assert_site_scope=Mock()
        self.mod._office=lambda:self.office;self.mod._planning=lambda:self.planning;self.mod._routes=lambda:self.routes
        self.plan_controller=load('cfg_kanban/doctype/cfg_kanban_dispatch_plan/cfg_kanban_dispatch_plan.py',dict(common))['CFGKanbanDispatchPlan']
        self.created=[];outer=self
        class NewDoc(base.Doc):
            def insert(doc,**kwargs):
                doc.flags=doc.get('flags') or base.Doc();doc.meta=base.Doc(get_label=lambda f:f)
                for i,r in enumerate(doc.get('lines') or [],1):r.idx=i
                if doc.doctype==PLAN:outer.plan_controller.validate(doc)
                doc.name=doc.name or 'GEN'+str(len(outer.created)+1);outer.data.setdefault(doc.doctype,{})[doc.name]=doc;outer.created.append(doc)
                for i,r in enumerate(doc.get('lines') or [],1):r.name=doc.name+'-L'+str(i);r.parent=doc.name
                return doc
        self.NewDoc=NewDoc
        original=self.b.get_doc
        def get_doc(dt,name=None,**kwargs):
            if isinstance(dt,dict):
                values=base.document(dt);values['flags']=base.Doc();return NewDoc(values)
            return original(dt,name,**kwargs)
        self.b.frappe.get_doc=get_doc;self.b.frappe.get_all=self.b.get_list
        self.b.frappe.db.get_values=lambda dt,filters,fields,**kw:self.b.get_list(dt,filters,fields)
        self.b.frappe.db.set_value=lambda dt,name,k,v=None,**kw:self.data[dt][name].db_set(k,v)
        self.b.frappe.db.get_value=self.value
        self.planning._business_context.__globals__['frappe']=self.b.frappe
        p=patch.dict(sys.modules,{self.mod.__name__:self.mod,self.planning.__name__:self.planning,self.routes.__name__:self.routes,self.office.__name__:self.office});p.start();self.addCleanup(p.stop)
        self.customer=self.profile('CUSTOMER','Customer Order');self.open=self.profile('OPEN','Open Route Stock');self.open.territory='NORTH'
        self.data['CFG Kanban Customer Scan Point']['SITE2'].territory='NORTH'
        outer=self
        class TripDoc(base.Doc):
            def as_dict(doc):return {k:v for k,v in super().as_dict().items() if k!='flags'}
            def save(doc,**kwargs):
                before=base.document(outer.data[base.TRIP][doc.name].as_dict());doc._before=before
                controller.validate(doc)
                outer.data[base.TRIP][doc.name]=base.document(doc.as_dict());doc._before=base.document(doc.as_dict())
                return doc
        controller=load('cfg_kanban/doctype/cfg_kanban_delivery_trip/cfg_kanban_delivery_trip.py',dict(common,validate_trip=self.office.validate_trip))['CFGKanbanDeliveryTrip']
        self.trip=TripDoc(self.b.doc);self.b.doc=self.trip;self.trip.flags=base.Doc()
        self.trip.update(auto_generate_dispatch=1,dispatch_profile='CUSTOMER',open_route_profile='OPEN',route_stock=[],vehicle_warehouse='LORRY',state='Planned')
    def profile(self,name,kind):
        self.b.add('CFG Kanban Card',name+'-CARD',active=1,blocked=0,card_type='Location Card',location_purpose='Dispatch Operations',company='A',current_warehouse='SOURCE')
        return self.b.add('CFG Kanban Dispatch Profile',name,active=1,company='A',revision=1,plan_type=kind,fulfilment_mode='Vehicle Delivery',
            dispatch_point=name+'-CARD',source_warehouse='SOURCE',business_label=kind,approval_required=0,tag_policy='Optional',stock_rotation_policy='FEFO',
            dispatch_responsibility='Dispatch',destination_assignment_policy='Select Before Dispatch',proof_policy='Required',customer_verification='Allow Assigned Stop Selection')
    def value(self,dt,name,fields,**kwargs):
        if isinstance(name,dict):row=next((r for r in self.data.get(dt,{}).values() if self.b.matches(r,name)),None)
        else:row=self.data.get(dt,{}).get(name)
        if not row:return None
        if isinstance(fields,list):return base.Doc({f:row.get(f) for f in fields})
        return row.get(fields)
    def generate(self,explicit=False):return self.mod.generate(self.trip,explicit)
    def plans(self):return list(self.data.get(PLAN,{}).values())
    def test_mark_planned_creates_exact_customer_request_and_one_existing_stock_pool(self):
        self.generate();self.assertEqual(len(self.plans()),2);self.assertEqual(len(self.trip.dispatch_plans),1)
        known=self.data[PLAN][self.trip.dispatch_plans[0].dispatch_plan];pool=self.data[PLAN][self.trip.open_route_plan]
        self.assertEqual((known.sales_order,known.lines[0].sales_order_item,known.lines[0].requested_qty),('SO1','ROW1',4))
        self.assertEqual(known.state,'Approved');self.assertEqual(pool.state,'Ready for Fulfilment');self.assertTrue(pool.existing_lorry_stock_only)
        self.assertFalse(pool.lines);self.assertFalse(pool.movement_manifest);self.assertEqual(pool.vehicle_warehouse,'LORRY')
        self.assertEqual(len(self.data[STOP]),1);self.assertEqual(next(iter(self.data[STOP].values())).office_stop_key,self.trip.stops[1].stop_key)
        self.assertEqual(known.created_by_user,'planner@example.com');self.assertFalse(known.created_by_operator);self.ledger.assert_not_called()
    def test_repeated_save_or_generation_reuses_requests_and_visits(self):
        self.generate();names=[p.name for p in self.plans()];self.generate();self.generate(explicit=True)
        self.assertEqual([p.name for p in self.plans()],names);self.assertEqual(len(self.data[STOP]),1)
    def test_profile_approval_is_preserved_for_both_requests(self):
        self.customer.approval_required=self.open.approval_required=1;self.generate()
        self.assertEqual({p.state for p in self.plans()},{'Awaiting Approval'});self.assertFalse(self.data[PLAN][self.trip.open_route_plan].vehicle_warehouse)
    def test_extra_goods_form_one_shared_real_loading_request_and_lifo_rows(self):
        self.trip.route_stock=[base.Doc(item_code='ITEM2',qty=6,stock_uom='Nos')]
        self.mod.validate_setup(self.trip);self.generate();pool=self.data[PLAN][self.trip.open_route_plan]
        self.assertEqual(pool.state,'Approved');self.assertFalse(pool.existing_lorry_stock_only);self.assertEqual(pool.lines[0].requested_qty,6)
        self.assertEqual(sum(r.qty for r in self.trip.loading_sequence if r.dispatch_plan==pool.name),6)
        self.assertFalse(self.data.get('Stock Entry'));self.assertFalse(self.data.get('CFG Kanban Handling Unit Quantity Ledger'))
    def test_extra_whole_uom_invalid_batch_and_duplicates_reject_before_generation(self):
        for qty in (0,-1,float('nan'),float('inf'),1.5):
            self.trip.route_stock=[base.Doc(item_code='ITEM2',qty=qty)]
            with self.assertRaises(ValueError):self.mod.validate_setup(self.trip)
        self.trip.route_stock=[base.Doc(item_code='ITEM2',qty=1),base.Doc(item_code='ITEM2',qty=2)]
        with self.assertRaisesRegex(ValueError,'duplicate'):self.mod.validate_setup(self.trip)
        self.assertFalse(self.plans())
    def test_missing_inactive_other_company_and_wrong_kind_profiles_reject(self):
        for field,value in [('active',0),('company','B'),('plan_type','Open Route Stock')]:
            old=self.customer[field];self.customer[field]=value
            with self.assertRaises(ValueError):self.generate()
            self.customer[field]=old
        self.customer._denied=True
        with self.assertRaises(PermissionError):self.generate()
        self.assertFalse(self.plans())
    def test_disabled_dispatch_card_and_wrong_source_warehouse_reject(self):
        card=self.data['CFG Kanban Card']['CUSTOMER-CARD'];card.blocked=1
        with self.assertRaisesRegex(ValueError,'Card'):self.generate()
        card.blocked=0;self.trip.source_warehouse='OTHER'
        with self.assertRaisesRegex(ValueError,'Warehouse'):self.generate()
    def test_informational_visit_without_site_does_not_invent_customer_qr_or_pool(self):
        self.trip.stops[1].customer_scan_point=None;self.generate()
        self.assertEqual(len(self.plans()),1);self.assertFalse(self.trip.open_route_plan)
    def test_legacy_manual_mode_does_not_generate_and_started_trip_is_not_rewritten(self):
        self.trip.auto_generate_dispatch=0;self.generate();self.assertFalse(self.plans())
        self.trip.auto_generate_dispatch=1;self.trip.driver_route_state='In Progress';self.mod.generate(self.trip);self.assertFalse(self.plans())
        with self.assertRaisesRegex(ValueError,'before driver'):self.generate(explicit=True)
    def test_duplicate_item_so_rows_keep_exact_identity_within_one_customer_request(self):
        source=self.data['Sales Order']['SO1'];source['items'].append(base.Doc(name='ROW1-B',item_code='ITEM1',item_name='Second price',stock_uom='Nos',qty=5,delivered_qty=0,conversion_factor=1))
        self.trip.orders.append(base.Doc(sales_order='SO1',sales_order_item='ROW1-B',stop_key=self.trip.stops[0].stop_key,planned_qty=2,item_code='ITEM1',item_name='Second price',stock_uom='Nos',is_stock_item=1))
        self.generate();known=self.data[PLAN][self.trip.dispatch_plans[0].dispatch_plan]
        self.assertEqual(len(self.trip.dispatch_plans),1);self.assertEqual([(r.sales_order_item,r.requested_qty) for r in known.lines],[('ROW1',4),('ROW1-B',2)])
    def test_mark_planned_save_generates_without_a_separate_factory_call(self):
        self.trip.save()
        self.assertEqual(len(self.trip.dispatch_plans),1);self.assertTrue(self.trip.open_route_plan)
        self.assertEqual(len(self.plans()),2)
    def test_unused_request_quantity_change_replaces_once_with_cancelled_history(self):
        self.trip.save();old=self.data[PLAN][self.trip.dispatch_plans[0].dispatch_plan]
        self.trip.orders[0].planned_qty=3;self.trip.save()
        current=self.data[PLAN][self.trip.dispatch_plans[0].dispatch_plan]
        self.assertNotEqual(old.name,current.name);self.assertEqual(old.state,'Cancelled')
        self.assertEqual(current.lines[0].requested_qty,3)
        names=[p.name for p in self.plans()];self.trip.save();self.assertEqual([p.name for p in self.plans()],names)
    def test_reserved_request_blocks_trip_quantity_rewrite(self):
        self.trip.save();plan=self.data[PLAN][self.trip.dispatch_plans[0].dispatch_plan]
        self.b.add('CFG Kanban Dispatch Allocation','RES',dispatch_plan=plan.name,state='Reserved')
        self.trip.orders[0].planned_qty=3
        with self.assertRaisesRegex(ValueError,'started'):self.trip.save()
        self.assertEqual(plan.state,'Approved');self.assertEqual(plan.lines[0].requested_qty,4)

    def test_foreign_or_manual_link_never_creates_duplicate_requests(self):
        self.b.plan(state='Approved')
        with self.assertRaisesRegex(ValueError,'manual'):self.generate()
        self.assertEqual(len(self.plans()),1)



    def test_generated_allocation_matches_exact_duplicate_sales_order_row(self):
        from cfg_kanban.tests.test_dispatch_fulfilment import Record
        self.generate();plan=self.data[PLAN][self.trip.dispatch_plans[0].dispatch_plan]
        source=self.data['Sales Order']['SO1'];order=Record(source)
        order.items.append(base.Doc(name='ROW1-B',item_code='ITEM1',stock_uom='Nos',qty=5,delivered_qty=0,conversion_factor=1))
        self.data['Sales Order']['SO1']=order
        plan.lines[0].sales_order_item='ROW1-B'
        bridge=load('services/dispatch_fulfilment.py',dict(frappe=self.b.frappe,flt=lambda v:float(v or 0)))
        allocation=base.Doc(name='ALLOC',dispatch_plan_line=plan.lines[0].name,item_code='ITEM1',stock_uom='Nos',allocated_qty=2)
        _,mapping=bridge['_order_assignments'](plan,[allocation]);self.assertEqual(mapping,{'ALLOC':'ROW1-B'})
        order.items[1].qty=1
        with self.assertRaisesRegex(ValueError,'undelivered'):bridge['_order_assignments'](plan,[allocation])


    def test_unused_quantity_can_return_to_a_previous_value_without_resurrecting_history(self):
        self.trip.save();first=self.data[PLAN][self.trip.dispatch_plans[0].dispatch_plan]
        self.trip.orders[0].planned_qty=3;self.trip.save()
        self.trip.orders[0].planned_qty=4;self.trip.save()
        current=self.data[PLAN][self.trip.dispatch_plans[0].dispatch_plan]
        self.assertNotEqual(current.name,first.name);self.assertEqual(first.state,'Cancelled')
        names=[p.name for p in self.plans()];self.trip.save();self.assertEqual([p.name for p in self.plans()],names)


    def test_generated_request_cannot_be_edited_on_plan_or_linked_to_another_trip(self):
        self.trip.save();plan=self.data[PLAN][self.trip.dispatch_plans[0].dispatch_plan]
        plan._before=base.document(plan.as_dict());plan.lines[0].requested_qty=3
        with self.assertRaisesRegex(ValueError,'office Delivery Trip'):self.plan_controller.validate(plan)
        plan.lines[0].requested_qty=4;plan.office_delivery_trip='FOREIGN'
        with self.assertRaisesRegex(ValueError,'exact office Trip'):self.office._plans(self.trip,current=True)

if __name__=='__main__':unittest.main()
