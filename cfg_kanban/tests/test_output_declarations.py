"""Offline station declarations and receipt adoption. Not MariaDB/ERP/kiosk acceptance."""
import copy,json,math,sys,types,unittest
from unittest.mock import Mock,patch
from cfg_kanban.tests.test_container_repacking import RepackHarness,Row,functions,HU,EVENT

DT='CFG Kanban Output Declaration'
class TestOutputDeclarations(RepackHarness):
    def setUp(self):
        super().setUp();self.data[DT]={};self.events=[];self.trace=Row(name='TRACE',lines=[],save=Mock())
        self.order=Row(doctype='Work Order',name='WO',company='TEST',cfg_kanban_cycle='CYCLE',production_item='PRODUCT',docstatus=1,status='In Process',qty=10,produced_qty=0,fg_warehouse='STORE',operations=[Row(name='OP1',operation='Rinse',idx=1),Row(name='OP2',operation='Pack',idx=2)])
        self.card=Row(doctype='CFG Kanban Card',name='STATION',card_number='STATION1',qr_code='QR-STATION',card_type='Workstation Queue Card',active=1,blocked=0,current_station='WS',queue_company='TEST')
        self.master=Row(doctype='CFG Kanban Master',name='MASTER',company='TEST',item_code='PRODUCT',control_type='Production',enable_station_output_declarations=1,output_packing_workstation=None,stock_uom='Kg',destination_warehouse='STORE')
        self.cycle=Row(doctype='CFG Kanban Cycle',name='CYCLE',kanban_master='MASTER',status='Released',kanban_card='CARD')
        for row in (self.order,self.card,self.master,self.cycle):self.data.setdefault(row.doctype,{})[row.name]=row
        self.jobs=[Row(name='JC',operation='Pack',operation_id='OP2',workstation='WS',total_completed_qty=5,docstatus=0,status='Work In Progress')]
        self.open_draft=False;self.serial_item=False
        self.frappe.as_json=lambda value:json.dumps(value,default=str);self.frappe.local=Row();self.frappe.session=Row(user='terminal');self.frappe.get_roles=lambda:['Stock User'];self.frappe.get_meta=lambda dt:Row(has_field=lambda field:True)
        self.frappe.db.table_exists=lambda dt:True
        self.frappe.db.exists=lambda dt,filters:any(all(row.get(k)==v for k,v in filters.items()) for row in self.data.get(dt,{}).values()) if isinstance(filters,dict) else filters in self.data.get(dt,{})
        self.profile=Row(employee='EMP',kanban_role='Operator',allowed_operations=[],allowed_workstations=[])
        self.session=Row(name='SESSION',terminal_user='terminal')
        self.auth=Mock(return_value=(self.profile,self.session))
        ns=dict(self.service);ns.update(require_operator=self.auth,record=self.record,cint=lambda value:int(value or 0))
        self.output=functions('services/output_declarations.py',None,ns)
        self.stage=Mock(side_effect=self.stage_line)
        api=types.SimpleNamespace(_resolve_card_name=lambda scan:'STATION' if scan in ('STATION1','QR-STATION') else None)
        trace=types.SimpleNamespace(_validate_unused_main_tag=self.unused,_production_output_container=self.output_bin,stage_output_tag=self.stage,_get_trace=lambda entry:self.trace,cancel_trace_line=self.cancel_line)
        modules={'cfg_kanban.api.operator':api,'cfg_kanban.services.tag_registry':types.SimpleNamespace(materialize_tag_family_for_code=Mock()),
            'cfg_kanban.services.trace_policy':types.SimpleNamespace(NO_TAG='No Physical Tag',effective_trace_policy=lambda *args:Row(production_output_tag_policy='Required Physical Tag',allow_partial_tag_quantity=1)),
            'cfg_kanban.services.production_trace':trace,'cfg_kanban.services.production_cancellation':types.SimpleNamespace(assert_cycle_not_under_cancellation=Mock())}
        self.patcher=patch.dict(sys.modules,modules);self.patcher.start();self.addCleanup(self.patcher.stop)
        self.container('B','Production Output Container')

    def doc(self,doctype,name=None):
        if isinstance(doctype,dict):values=copy.deepcopy(doctype)
        else:values=copy.deepcopy(self.data[doctype][name])
        owner=self
        class Doc(Row):
            def __getattribute__(self,name):
                if name=="items" and "items" in self:return dict.__getitem__(self,name)
                return super().__getattribute__(name)
            def __init__(self,values):super().__init__(values);object.__setattr__(self,'flags',Row())
            def insert(self,**kw):
                self.name=self.get('name') or f'{self.doctype}-{len(owner.data[self.doctype])+1}'
                if self.doctype==DT:
                    for field in ('active_tag_key','active_container_key','idempotency_key'):
                        if self.get(field) and any(row.get(field)==self.get(field) for row in owner.data[DT].values()):raise ValueError('duplicate claim')
                owner.data[self.doctype][self.name]=Row(copy.deepcopy(dict(self)));return self
            def reload(self):self.update(copy.deepcopy(owner.data[self.doctype][self.name]));return self
            def db_set(self,field,value=None,**kw):
                values=field if isinstance(field,dict) else {field:value};self.update(values);owner.data[self.doctype][self.name].update(values)
        return Doc(values)
    def record(self,event_type,**kw):
        self.events.append((event_type,kw));key=kw.get('idempotency_key',str(len(self.events)))
        return self.doc(dict(doctype=EVENT,idempotency_key=key,payload_json=json.dumps(kw.get('payload',{}),default=str))).insert()
    def set_value(self,doctype,name,field,value=None,**kw):
        self.data[doctype][name].update(field if isinstance(field,dict) else {field:value})
    def get_all(self,doctype,filters=None,fields=None,pluck=None,**kw):
        if doctype=='Work Order':return ['WO']
        rows=list(self.data.get(doctype,{}).values())
        def matches(row):
            for field,value in (filters or {}).items():
                if row.get(field)!=value:return False
            return True
        rows=[Row(copy.deepcopy(row)) for row in rows if matches(row)]
        return [row.get(pluck) for row in rows] if pluck else rows
    def get_value(self,doctype,key,field=None,**kw):
        if doctype=='Item':return self.serial_item if field=='has_serial_no' else ('Kg' if field=='stock_uom' else None)
        if doctype=='UOM':return 0
        return super().get_value(doctype,key,field,**kw)
    def sql(self,query,args=None,as_dict=False):
        if 'select distinct wo.name' in query:return [Row(name='WO')]
        if 'from `tabWork Order`' in query:return [Row(copy.deepcopy(self.data['Work Order'][args]))]
        if 'from `tabJob Card`' in query:
            if 'status!=' in query:return [row for row in self.jobs if row.status!='Completed']
            return [Row(copy.deepcopy(row)) for row in self.jobs]
        if 'from `tabStock Entry`' in query:return [('DRAFT',)] if self.open_draft else []
        if 'from `tabCFG Kanban Material Trace Line`' in query:
            return [Row(stock_entry='SE') for row in self.trace.lines if row.status=='Pending' and (row.pending_tag_code==args[0] or (row.physical_container and row.physical_container==args[1]))]
        if 'from `tabCFG Kanban Tag Identity`' in query:return [(args,)]
        if 'from `tabCFG Kanban Output Declaration`' in query:
            rows=list(self.data[DT].values())
            if 'where work_order=' in query:rows=[row for row in rows if row.work_order==args]
            elif 'where idempotency_key=' in query:rows=[row for row in rows if row.idempotency_key==args]
            elif 'active_tag_key=' in query:
                keys=args if isinstance(args,tuple) else (args,)
                rows=[row for row in rows if row.get('active_tag_key') in keys or row.get('active_container_key') in keys]
            return [Row(copy.deepcopy(row)) for row in rows]
        return super().sql(query,args,as_dict)
    def output_bin(self,scan,company,warehouse,stock_entry=None,declaration=None):
        unit=self.doc(HU,scan)
        if unit.reusable_container_role!='Production Output Container' or unit.current_warehouse!=warehouse:raise ValueError('invalid bin')
        reserved=self.output.reservation(scan,stock_entry,declaration)
        if unit.movement_state=='Reserved' and not reserved:raise ValueError('reserved')
        if self.contents(scan):raise ValueError('occupied')
        return unit
    def stage_line(self,entry,row,code,qty,**kw):self.trace.lines.append(Row(name='LINE'+str(len(self.trace.lines)+1),pending_tag_code=code,qty=qty,status='Pending',direction='Output',physical_container=None))
    def cancel_line(self,entry,line,**kw):next(row for row in self.trace.lines if row.name==line).status='Cancelled'
    def declare(self,**kw):
        args=dict(station_scan='STATION1',work_order='WO',qty=2,event_token='TOKEN',tag_code='NEW1',operator_session_token='OS');args.update(kw);return self.output.declare_output(**args)
    def info(self):return self.output.availability(self.doc('Work Order','WO'),self.master,'WS',True)

    def test_declare_uses_reported_good_while_running_without_creating_stock_or_draft(self):
        total=self.total();result=self.declare();row=self.data[DT][result['name']]
        self.assertEqual(row.status,'Declared');self.assertEqual(self.total(),total);self.assertFalse(self.open_draft)
        self.assertEqual(self.info()['available_qty'],3);self.assertEqual(self.jobs[0].status,'Work In Progress')
    def test_reject_bom_target_quantity_and_nonfinite_or_negative_quantity(self):
        for qty in (6,'nan','inf',0,-1):
            with self.subTest(qty=qty):
                with self.assertRaises(ValueError):self.declare(qty=qty)
        self.assertFalse(self.data[DT])
    def test_replay_and_changed_payload_after_state_mutation(self):
        first=self.declare();self.data[DT][first['name']].status='Posted'
        self.assertTrue(self.declare()['duplicate']);self.assertEqual(len(self.data[DT]),1)
        with self.assertRaisesRegex(ValueError,'different output declaration'):self.declare(qty=1)
    def test_same_identity_cannot_be_declared_twice(self):
        self.declare()
        with self.assertRaisesRegex(ValueError,'reserved'):self.declare(event_token='SECOND')
    def test_bin_only_and_tag_plus_bin_reserve_permanent_bin(self):
        result=self.declare(container_code='B');row=self.data[DT][result['name']]
        self.assertEqual(row.tag_code,'NEW1');self.assertEqual(row.physical_container,'B');self.assertEqual(self.data[HU]['B'].movement_state,'Reserved')
        with self.assertRaisesRegex(ValueError,'reserved'):self.output.reservation('B')
    def test_station_scope_and_dedicated_packing_station(self):
        self.jobs[0].workstation='OTHER'
        with self.assertRaisesRegex(ValueError,'available'):self.declare()
        self.master.output_packing_workstation='WS';self.declare();self.assertEqual(self.info()['available_qty'],3)
    def test_other_stations_cannot_double_count_and_posted_receipts_deduct_capacity(self):
        self.jobs.append(Row(self.jobs[0],name='JC2',workstation='OTHER',total_completed_qty=3))
        self.data['Work Order']['WO'].produced_qty=2
        self.assertEqual(self.info()['available_qty'],3)
        self.declare(qty=3);self.assertEqual(self.info()['available_qty'],0)
    def test_repeated_operation_requires_exact_final_row(self):
        self.order.operations[0].operation='Pack';self.jobs[0].operation_id=None
        with self.assertRaisesRegex(ValueError,'exact Job Card operation-row'):self.declare()
    def test_no_recursive_declaration_snapshots(self):
        self.declare();second=self.declare(tag_code='NEW2',event_token='TWO')
        snapshot=json.loads(self.data[DT][second['name']].source_snapshot);self.assertNotIn('declarations',snapshot)
    def test_disable_feature_open_draft_closed_order_or_erp_serial_item_rejected(self):
        self.master.enable_station_output_declarations=0
        with self.assertRaisesRegex(ValueError,'Enable station'):self.declare()
        self.master.enable_station_output_declarations=1;self.open_draft=True
        with self.assertRaisesRegex(ValueError,'Draft already exists'):self.declare()
        self.open_draft=False;self.serial_item=True
        with self.assertRaisesRegex(ValueError,'serial-controlled'):self.declare()
    def test_supervisor_receipt_plan_requires_exact_declared_quantity(self):
        self.declare()
        with self.assertRaisesRegex(ValueError,'Supervisor'):self.output.receipt_plan(self.order,self.master,2,self.profile)
        self.profile.kanban_role='Supervisor'
        with self.assertRaisesRegex(ValueError,'equal all pending'):self.output.receipt_plan(self.order,self.master,5,self.profile)
        self.assertEqual(len(self.output.receipt_plan(self.order,self.master,2,self.profile)),1)
    def make_entry(self):
        self.data['Stock Entry']={'SE':Row(doctype='Stock Entry',name='SE',purpose='Manufacture',company='TEST',work_order='WO',cfg_kanban_cycle='CYCLE',items=[Row(name='FG',item_code='PRODUCT',t_warehouse='STORE',s_warehouse=None,qty=2,transfer_qty=2,stock_uom='Kg')])}
        return self.doc('Stock Entry','SE')
    def test_adoption_keeps_exact_tag_and_bin_without_posting_stock(self):
        result=self.declare(container_code='B');entry=self.make_entry();self.profile.kanban_role='Supervisor';rows=self.output.receipt_plan(self.order,self.master,2,Row(kanban_role='Supervisor',allowed_operations=[],allowed_workstations=[]))
        count=self.output.adopt(entry.name,rows,'OS','CARD');self.assertEqual(count,1)
        declaration=self.data[DT][result['name']];self.assertEqual(declaration.status,'Bound to Draft');self.assertEqual(declaration.stock_entry,'SE')
        self.assertEqual(self.trace.lines[0].pending_tag_code,'NEW1');self.assertEqual(self.trace.lines[0].physical_container,'B')
        self.assertEqual(self.total(),10)
    def bind(self):
        result=self.declare();entry=self.make_entry();self.profile.kanban_role='Supervisor';self.output.adopt(entry.name,list(self.data[DT].values()),'OS','CARD');return result,entry
    def test_submit_requires_finished_jobs_authorized_supervisor_and_unchanged_trace(self):
        _result,entry=self.bind()
        with self.assertRaisesRegex(ValueError,'Complete all Job Cards'):self.output.validate_receipt(entry)
        self.jobs[0].status='Completed'
        with self.assertRaisesRegex(ValueError,'Supervisor must'):self.output.validate_receipt(entry)
        self.output.authorize_posting(entry,self.profile,self.session);self.output.validate_receipt(entry)
        self.trace.lines[0].qty=3
        with self.assertRaisesRegex(ValueError,'trace line changed'):self.output.validate_receipt(entry)
    def test_posted_feedback_and_reversal_keep_history(self):
        result,entry=self.bind();self.trace.lines[0].status='Confirmed';self.trace.lines[0].handling_unit='POSTED-TAG'
        self.output.confirm_receipt(entry);row=self.data[DT][result['name']];self.assertEqual(row.status,'Posted');self.assertIsNone(row.active_tag_key)
        self.output.reverse_receipt(entry);self.assertEqual(row.status,'Voided')
    def test_cancel_restores_bin_and_capacity_without_deleting_history(self):
        result=self.declare(container_code='B');self.output.cancel_declaration(result['name'],'Emptied bundle','CANCEL','OS')
        self.assertEqual(self.data[DT][result['name']].status,'Cancelled');self.assertEqual(self.data[HU]['B'].movement_state,'Empty');self.assertEqual(self.info()['available_qty'],5)
    def test_bound_draft_cannot_be_deleted_or_discarded(self):
        _result,entry=self.bind()
        with self.assertRaisesRegex(ValueError,'Cancel the bound'):self.output.protect_draft_delete(entry)

    def test_native_pending_trace_blocks_pre_draft_identity_claim(self):
        self.trace.lines.append(Row(name='OLD',status='Pending',pending_tag_code='NEW1',physical_container=None))
        with self.assertRaisesRegex(ValueError,'another native Draft'):self.declare()
        self.assertFalse(self.data[DT])

    def test_reserved_tag_cannot_activate_on_unsubmitted_receipt(self):
        _result,entry=self.bind()
        with self.assertRaisesRegex(ValueError,'submitted ERP receipt'):
            self.output.reservation('NEW1',stock_entry='SE',activation=True)
        self.data['Stock Entry']['SE'].docstatus=1
        self.assertTrue(self.output.reservation('NEW1',stock_entry='SE',activation=True))

    def test_cancel_replay_keeps_original_reason_and_request_identity(self):
        result=self.declare()
        self.output.cancel_declaration(result['name'],'Wrong bundle','CANCEL','OS')
        self.assertTrue(self.output.cancel_declaration(result['name'],'Wrong bundle','CANCEL','OS')['duplicate'])
        with self.assertRaisesRegex(ValueError,'original cancellation data'):
            self.output.cancel_declaration(result['name'],'Different','CANCEL','OS')

    def test_actual_receipt_preparer_adopts_bundles_and_forces_draft_even_on_auto_submit_master(self):
        self.declare();self.profile.kanban_role='Supervisor';self.master.manufacture_posting_mode='Submit on Operator Confirmation'
        entry=self.make_entry();entry.docstatus=0
        modules={
            'cfg_kanban.services.output_declarations':types.SimpleNamespace(receipt_plan=self.output.receipt_plan,adopt=self.output.adopt,installed=lambda:True),
            'cfg_kanban.services.operation_material_runs':types.SimpleNamespace(material_run_settlement_context=lambda wo:{'At Job Card End':[],'At Work Order Manufacture Receipt':[]},adopt_material_run_draws=lambda *args:{'adopted':0}),
            'cfg_kanban.services.wip_bin_loads':types.SimpleNamespace(manufacture_receipt_wip_bin_readiness=lambda *args:{'ready':True})}
        insert=Mock(return_value=(Row(name='COMMAND'),True))
        ns=functions('services/production_material_flow.py',{'prepare_manufacture_receipt'},dict(
            frappe=self.frappe,flt=lambda value:float(value or 0),cint=lambda value:int(value or 0),
            _production_context=lambda cycle:(self.doc('CFG Kanban Cycle','CYCLE'),self.master,self.doc('Work Order','WO')),
            require_operator=self.auth,get_hidden_item_policy=lambda:{'items':set(),'can_view':True},
            _validated_confirmation_lines=lambda *args,**kw:[],_validated_confirmation=lambda value:value,
            _assert_warehouse_company=Mock(),_validated_finished_batch=lambda *args:None,_assert_no_open_production_entry=Mock(),
            canonical_key=self.service.canonical_key,insert_once=insert,execute_command=lambda command:entry,
            now_datetime=self.service.now_datetime,record=self.record))
        with patch.dict(sys.modules,modules):
            result=ns.prepare_manufacture_receipt('CYCLE',2,confirmation='Supervisor reviewed',operator_session_token='OS')
        self.assertEqual(result['output_declarations_adopted'],1)
        payload=json.loads(insert.call_args.args[0].request_payload)
        self.assertFalse(payload['submit']);self.assertEqual(self.trace.lines[0].pending_tag_code,'NEW1')
        self.assertEqual(self.data[DT][next(iter(self.data[DT]))].status,'Bound to Draft')

    def test_actual_native_factory_keeps_physical_tag_and_loads_its_declared_bin(self):
        declared=self.declare(container_code='B')
        saved=self.data[DT][declared['name']];saved.update(status='Bound to Draft',stock_entry='SE',material_trace_line='LINE')
        entry=self.make_entry();entry.docstatus=1
        line=Row(name='LINE',physical_container='B',pending_tag_code='NEW1',batch_no=None,qty=2,handling_unit_type='Container')
        entry.items[0].item_name='Product'
        load=Mock()
        ns=functions('services/production_trace.py',{'_activate_output_unit'},dict(
            frappe=self.frappe,canonical_key=self.service.canonical_key,_validate_unused_main_tag=self.unused,record=self.record))
        with patch.dict(sys.modules,{'cfg_kanban.services.container_contents':types.SimpleNamespace(load_production_output_content=load)}):
            unit=ns._activate_output_unit(entry,entry.items[0],line)
        self.assertEqual(unit.handling_unit_id,'NEW1');self.assertFalse(unit.get('virtual_content'))
        self.assertEqual(load.call_args.args[0],'B');self.assertTrue(load.call_args.kwargs['allow_physical_stock'])
        self.assertEqual(unit.origin_reference_name,'SE');self.assertEqual(unit.packed_on,saved.declared_on)

    def test_station_context_discovers_reported_output_and_honors_operation_scope(self):
        context=self.output.station_output_context('STATION1','OS')
        self.assertEqual(context['choices'][0]['available_qty'],5)
        self.profile.allowed_operations=[Row(operation='Rinse')]
        self.assertFalse(self.output.station_output_context('STATION1','OS')['choices'])

    def test_aliases_of_one_registered_tag_share_one_identity_claim(self):
        original=self.output.declare_output.__globals__['resolve_logistics_scan']
        self.output.declare_output.__globals__['resolve_logistics_scan']=lambda code: {'identity_type':'Registered Tag Identity','visible_code':'NEW1','name':'NEW1'} if code in ('new1','NEW1') else original(code)
        first=self.declare(tag_code='new1')
        self.assertEqual(self.data[DT][first['name']].tag_code,'NEW1')
        with self.assertRaisesRegex(ValueError,'reserved'):self.declare(event_token='SECOND',tag_code='NEW1')
