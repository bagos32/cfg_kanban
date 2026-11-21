"""Actual native prepared delivery, quantity math, refusal custody and existing QC with offline DB doubles."""
import copy, datetime, json, math, sys, types, unittest
from unittest.mock import Mock, patch
from cfg_kanban.tests import test_dispatch_fulfilment as native
from cfg_kanban.tests.test_vehicle_overview import load

OUT='CFG Kanban Delivery Outcome';LINE='CFG Kanban Delivery Outcome Line';CASE='CFG Kanban Return Case'

class NewDoc(native.Record):
    def insert(self,**kwargs):
        table=self._store.setdefault(self.doctype,{})
        self.name=f'{self.doctype}-{len(table)+1}';table[self.name]=self
        child=LINE if self.doctype==OUT else 'CFG Kanban Return Line'
        for n,row in enumerate(self.get('lines') or [],1):
            row.name=f'{self.name}-R{n}';row.parent=self.name;row.parenttype=self.doctype;row.doctype=child
            self._store.setdefault(child,{})[row.name]=row
        return self

class TestDriverDeliveryOutcomes(unittest.TestCase):
    def setUp(self):
        self.b=native.TestDispatchFulfilment();self.b.setUp();self.addCleanup(self.b.doCleanups)
        self.data=self.b.data;self.plan=self.b.plan;self.operator=self.b.operator;self.session=self.b.e3.session
        self.operator.update(can_start=1,can_complete=1,can_override=0)
        self.operator.responsibilities.append(native.Row(responsibility='Customer Return'))
        p=patch.object(native.Doc,'check_permission',lambda doc,p:(_ for _ in ()).throw(PermissionError('Read denied')) if doc.get('_denied') else None,create=True);p.start();self.addCleanup(p.stop)
        original_doc=self.b.get_doc
        def doc(doctype,name=None,**kwargs):
            if isinstance(doctype,dict) and doctype.get('doctype') in (OUT,CASE):
                values=dict(doctype);values['flags']=native.Row();values['lines']=[native.Record(r) for r in values.get('lines') or []]
                return NewDoc(values,_store=self.data)
            return original_doc(doctype,name,**kwargs)
        self.b.frappe.get_doc=doc
        self.b.frappe.get_cached_value=lambda *args:0
        self.b.frappe.ValidationError=ValueError
        original_value=self.b.get_value
        def value(doctype,name,fields,**kwargs):
            if doctype=='UOM':return self.whole
            if doctype=='Item' and fields=='stock_uom':return 'Nos'
            if doctype=='Item' and fields=='name':return name
            return original_value(doctype,name,fields,**kwargs)
        self.b.frappe.db.get_value=value
        self.whole=0
        common=dict(frappe=self.b.frappe,json=json,math=math,flt=lambda v:float(v or 0),
            now_datetime=lambda:datetime.datetime(2026,11,21,16),canonical_key=self.b.bridge.canonical_key,
            record=self.b.e3.events,post_quantity_event=self.b.post_quantity,require_operator=Mock(return_value=(self.operator,self.session)),_=lambda x:x)
        self.out=types.ModuleType('cfg_kanban.services.driver_delivery_outcomes');self.out.__dict__.update(load('services/driver_delivery_outcomes.py',dict(common)))
        self.ret=types.ModuleType('cfg_kanban.services.customer_returns');self.ret.__dict__.update(load('services/customer_returns.py',dict(common)))
        self.out._returns=lambda:self.ret;self.out._prepared=lambda:self.b.bridge
        self.b.bridge._driver_outcomes=lambda:self.out
        contents=types.ModuleType('cfg_kanban.services.container_contents');contents.active_container_membership=lambda name:None
        p=patch.dict(sys.modules,{self.out.__name__:self.out,self.ret.__name__:self.ret,contents.__name__:contents});p.start();self.addCleanup(p.stop)
        self.trip=native.Record(name='TRIP',doctype='CFG Kanban Delivery Trip')
        self.stop=native.Record(stop_key='STOP')
        self.b.site.update(enable_customer_return_qc=1,return_inspection_location='QC BAY')
        self.b.add('CFG Kanban Operator Session',self.session.name,terminal_user=self.session.terminal_user)
        self.b.add('Location','QC BAY');self.b.add('Warehouse','QC WH',company='B');self.b.add('Company','B')
        self.b.frappe.get_all=self.all
        self.b.add('Item','ITEM',stock_uom='Nos',disabled=0)
    def all(self,doctype,filters=None,pluck=None,**kwargs):
        rows=[row for row in self.data.get(doctype,{}).values() if self.matches(row,filters)]
        return [r.get(pluck) for r in rows] if pluck else rows
    def matches(self,row,filters):
        for key,value in (filters or {}).items():
            v=row.get(key)
            if isinstance(value,list):
                if value[0]=='in' and v not in value[1]:return False
                if value[0]=='is' and value[1]=='not set' and v:return False
            elif v!=value:return False
        return True
    def rows(self,accepted=3,condition='Good / Unwanted'):
        return [dict(dispatch_allocation=r.name,accepted_qty=accepted if r.handling_unit else max(float(r.allocated_qty)-2,0),
            refusal_reason='Customer needs fewer' if condition=='Good / Unwanted' else 'Damaged on arrival',condition=condition)
            for r in self.data[native.ALLOC].values() if r.dispatch_plan==self.plan.name]
    def declare(self,accepted=3,condition='Good / Unwanted'):
        return self.out.declare(self.trip,self.stop,self.plan,self.rows(accepted,condition),self.operator,self.session,'DECISION')
    def start(self,accepted=3,condition='Good / Unwanted'):
        out=self.declare(accepted,condition);self.b.start();return out
    def post(self):
        self.b.engine.confirm_delivery_allocations(self.b.delivery().name,'CONFIRM','TOKEN')
        payload=self.b.engine._customer_delivery_payload(self.b.delivery())
        note=self.b.gateway['build_customer_delivery_note'](self.b.delivery(),payload);note.name='DN';note.docstatus=1
        self.b.feedback._on_customer_delivery_submit(note,self.b.delivery().name);return note
    def qc(self,case,disposition='Release Own Stock'):
        self.operator.responsibilities.append(native.Row(responsibility='Customer Return QC'))
        self.ret.start_qc_inspection(case.name,'QCSTART','TOKEN')
        rows=[dict(name=r.name,received_qty=r.claimed_qty,accepted_qty=r.claimed_qty,rejected_qty=0,qc_disposition=disposition,qc_reason='Inspected') for r in case.lines]
        self.ret.complete_qc_inspection(case.name,rows,'Checked','QCDONE','TOKEN')
    def supervisor(self):self.operator.update(kanban_role='Supervisor',can_override=1)

    def disposal_service(self):
        self.b.frappe.only_for=Mock();self.b.frappe.session=native.Row(user='stock@example.com')
        return load('services/return_disposition.py',dict(frappe=self.b.frappe,flt=lambda v:float(v or 0),
            now_datetime=lambda:datetime.datetime(2026,11,21,17),record=Mock(),canonical_key=self.b.bridge.canonical_key))
    def issue(self,qty=2,company='B',purpose='Material Issue'):
        return self.b.add('Stock Entry','ISSUE',docstatus=1,company=company,purpose=purpose,
            items=[native.Record(item_code='ITEM',stock_uom='Nos',s_warehouse='LORRY1',qty=qty,transfer_qty=qty)])
    def test_owned_qc_disposal_mirrors_exact_native_issue_once_without_new_erp_command(self):
        out=self.start(3,'Damaged');self.post();case=next(iter(self.data[CASE].values()));self.qc(case,'Accept for Disposal')
        issue=self.issue();service=self.disposal_service();confirm=service['confirm_owned_stock_disposal']
        result=confirm(case.name,issue.name,'Physically disposed after QC')
        self.assertFalse(result['already_recorded']);self.assertEqual(case.state,'Closed');self.assertEqual(case.owned_stock_issue,issue.name)
        self.assertEqual((self.b.unit.current_qty,self.b.unit.reserved_qty),(0,0));self.assertEqual(out.lines[0].stock_state,'Disposed')
        self.assertTrue(confirm(case.name,issue.name,'Read outcome')['already_recorded'])
        self.assertEqual(self.b.unit.current_qty,0);self.assertEqual(len(self.data['Stock Entry']),2)
    def test_owned_disposal_rejects_wrong_erp_scope_or_quantity_and_requires_qc_disposal(self):
        self.start(3,'Damaged');self.post();case=next(iter(self.data[CASE].values()));self.qc(case)
        issue=self.issue();confirm=self.disposal_service()['confirm_owned_stock_disposal']
        with self.assertRaisesRegex(ValueError,'approve disposal'):confirm(case.name,issue.name,'Disposed')
        case.lines[0].qc_disposition='Accept for Disposal'
        for field,value in [('company','OTHER'),('purpose','Material Receipt'),('docstatus',0)]:
            old=issue[field];issue[field]=value
            with self.assertRaises(ValueError):confirm(case.name,issue.name,'Disposed')
            issue[field]=old
        issue.items[0].transfer_qty=3
        with self.assertRaisesRegex(ValueError,'exactly'):confirm(case.name,issue.name,'Disposed')
        self.assertEqual(self.b.unit.current_qty,2);self.assertEqual(self.b.unit.reserved_qty,2);self.assertFalse(case.owned_stock_issue)
    def test_expired_refused_stock_cannot_be_resold_even_with_supervisor_or_automatic_policy(self):
        out=self.start();self.post();self.b.delivery().state='Closed';self.supervisor()
        self.b.bridge.assert_delivery_tag_expiry=Mock(side_effect=ValueError('Expired tag'))
        with self.assertRaisesRegex(ValueError,'Expired'):self.out.release(out,[out.lines[0].name],'Release',self.operator,self.session)
        out.sound_refusal_policy='Allow Resale After Delivery';self.out.auto_release(self.b.delivery())
        self.assertEqual(out.lines[0].stock_state,'Held');self.assertEqual(self.b.unit.available_qty,0)
    def test_released_refusal_is_subtracted_once_from_original_dispatch_remainder(self):
        out=self.start();self.post();self.b.delivery().state='Closed';self.supervisor()
        self.out.release(out,[out.lines[0].name],'Sound stock',self.operator,self.session)
        ns=load('services/dispatch_reconciliation.py',dict(frappe=self.b.frappe,flt=lambda v:float(v or 0),EPSILON=0.000001))
        ns['_fulfilment']=lambda:self.b.bridge
        row=ns['_balances'](self.plan,current=True)[0]
        self.assertEqual((row['loaded_qty'],row['delivered_qty'],row['refused_released_qty'],row['remaining_qty']),(5,3,2,0))
    def test_current_read_holds_and_own_loose_recovery_keep_other_claims_unavailable(self):
        self.b.loose(6);out=self.start();self.post()
        self.b.frappe.db.get_values=lambda doctype,filters=None,*a,**kw:self.all(doctype,filters)
        self.assertEqual(self.out.held_untagged('B','LORRY1','ITEM',None,current=True),2)
        self.assertEqual(self.out.held_untagged('OTHER','LORRY1','ITEM',None,current=True),0)
        ns=load('services/dispatch_recovery.py',dict(frappe=self.b.frappe,EPSILON=0.000001))
        planning=native.Row(_lock_erp_bin=Mock(),_untagged_available=Mock(return_value=2))
        ns['_review_service']=lambda:native.Row(_planning=lambda:planning)
        recipe=[dict(handling_unit=None,item_code='ITEM',batch_no=None,stock_uom='Nos',dispatch_qty=2)]
        ns['_validate_loose'](self.plan,recipe)
        self.assertEqual(planning._untagged_available.call_args.kwargs['exclude_refusal_outcome'],out.name)
        recipe[0]['dispatch_qty']=3
        with self.assertRaisesRegex(ValueError,'missing or committed'):ns['_validate_loose'](self.plan,recipe)

    def test_loose_recovery_excludes_own_hold_before_flooring_native_available_stock(self):
        self.b.loose(6);out=self.start();self.post();self.b.delivery().state='Closed'
        self.plan.fulfilment_status='Completed'
        old_exists=self.b.frappe.db.exists
        self.b.frappe.db.exists=lambda dt,name: True if (dt,name)==('DocType',OUT) else old_exists(dt,name)
        # Two tagged units plus two loose units remain. A stock loss leaves only one loose unit.
        self.b.erp_balance=3
        self.assertEqual(self.b.planning._untagged_available('B','LORRY1','ITEM',None,exclude_prepared_plan=self.plan.name,exclude_refusal_outcome=out.name),1)
        self.b.erp_balance=4
        self.assertEqual(self.b.planning._untagged_available('B','LORRY1','ITEM',None,exclude_prepared_plan=self.plan.name,exclude_refusal_outcome=out.name),2)
        self.assertEqual(self.b.planning._untagged_available('B','LORRY1','ITEM',None,exclude_prepared_plan=self.plan.name),0)
        self.assertEqual(self.b.planning._untagged_available('B','LORRY1','ITEM',None,exclude_prepared_plan=self.plan.name,exclude_refusal_outcome='OTHER'),0)

    def test_partial_tag_posts_only_accepted_and_holds_balance_in_same_lorry(self):
        outcome=self.start();self.assertEqual(self.b.unit.reserved_qty,5);self.assertEqual(self.b.unit.current_qty,5)
        note=self.post();self.assertEqual(note.items[0].stock_qty,3)
        self.assertEqual((self.b.unit.current_qty,self.b.unit.reserved_qty,self.b.unit.available_qty),(2,2,0))
        self.assertEqual(self.b.unit.current_warehouse,'LORRY1');self.assertEqual(outcome.lines[0].refused_qty,2)
    def test_mixed_untagged_and_tagged_acceptance_keeps_exact_sources(self):
        self.b.loose(6);outcome=self.start();note=self.post()
        self.assertEqual(sorted(r.stock_qty for r in note.items),[3,4]);self.assertEqual([r.refused_qty for r in outcome.lines],[2,2])
        self.assertEqual(self.out.held_untagged('B','LORRY1','ITEM',None),2)
        self.assertEqual(self.out.declared_source_qty('LOOSE'),2)
    def test_all_refused_closes_without_delivery_note_or_consumption(self):
        outcome=self.start(0);delivery=self.b.delivery()
        self.assertEqual(delivery.state,'Closed');self.assertFalse(delivery.delivery_note)
        self.assertEqual(self.plan.fulfilment_status,'Completed');self.assertTrue(self.out.full_refusal(delivery))
        self.assertEqual(self.b.unit.current_qty,5);self.assertEqual(self.b.unit.reserved_qty,5)
        self.assertFalse(self.data.get(native.DA));self.assertEqual(outcome.lines[0].accepted_qty,0)
    def test_quality_refusal_creates_one_owned_stock_qc_case(self):
        outcome=self.start(3,'Damaged');cases=list(self.data[CASE].values());self.assertEqual(len(cases),1)
        case=cases[0];self.assertEqual(case.state,'Awaiting QC Receipt');self.assertEqual(case.claimed_total_qty,2)
        self.assertTrue(case.stock_already_owned);self.assertEqual(case.accounting_status,'Not Required')
        self.assertEqual(case.driver_trip,'TRIP');self.assertEqual(case.lines[0].driver_outcome_line,outcome.lines[0].name)
        self.assertEqual(self.b.unit.current_qty,5)
    def test_quality_refusal_requires_return_authorization_and_setup(self):
        self.operator.responsibilities=[r for r in self.operator.responsibilities if r.responsibility!='Customer Return']
        with self.assertRaises(ValueError):self.declare(3,'Damaged')
        self.operator.responsibilities.append(native.Row(responsibility='Customer Return'));self.b.site.return_inspection_location=None
        with self.assertRaisesRegex(ValueError,'Configure'):self.declare(3,'Damaged')
        self.assertFalse(self.data.get(OUT))
    def test_qc_does_not_receive_owned_stock_again_or_prepare_customer_credit(self):
        self.start(3,'Damaged');case=next(iter(self.data[CASE].values()));self.qc(case)
        self.assertEqual(case.state,'QC Completed - Stock Pending');self.assertEqual(case.accounting_status,'Not Required')
        with self.assertRaisesRegex(ValueError,'no customer credit'):self.ret._assert_accounting_ready(case)
        ns=load('services/return_disposition.py',dict(frappe=self.b.frappe,flt=lambda v:float(v or 0)))
        with self.assertRaisesRegex(ValueError,'already company stock'):ns['_assert_disposition_ready'](case)
        self.assertEqual(self.b.unit.current_qty,5)
    def test_invalid_or_changed_prepared_rows_fail_before_custody(self):
        for rows in [[dict(dispatch_allocation='OTHER',accepted_qty=3)],[],self.rows(6),self.rows(-1),self.rows(float('nan')),self.rows(float('inf'))]:
            with self.subTest(rows=rows),self.assertRaises(ValueError):self.out.quantities(self.plan,rows)
        rows=self.rows();rows[0]['refusal_reason']=''
        with self.assertRaisesRegex(ValueError,'reason'):self.out.quantities(self.plan,rows)
        rows=self.rows();rows.append(rows[0])
        with self.assertRaisesRegex(ValueError,'exactly once'):self.out.quantities(self.plan,rows)
    def test_whole_stock_uom_and_serialized_tag_boundaries_are_preserved(self):
        self.whole=1
        with self.assertRaisesRegex(ValueError,'whole-number'):self.out.quantities(self.plan,self.rows(2.5))
        self.whole=0;self.b.unit.serial_count=5
        with self.assertRaisesRegex(ValueError,'whole serialized'):self.out.quantities(self.plan,self.rows(3))
        self.assertEqual(self.out.quantities(self.plan,self.rows(0))[0]['refused_qty'],5)
    def test_native_release_cannot_break_the_recorded_accepted_source_decision(self):
        self.start();allocation=next(iter(self.data[native.DA].values()))
        with self.assertRaisesRegex(ValueError,'sources are frozen'):
            self.b.engine.release_delivery_allocation(allocation.name,'Changed order','RELEASE','TOKEN')
        self.assertEqual(allocation.state,'Reserved');self.assertEqual(self.b.unit.reserved_qty,5)

    def test_delivery_cannot_substitute_or_increase_accepted_allocation(self):
        self.start();alloc=next(iter(self.data[native.DA].values()));alloc.allocated_qty=4
        with self.assertRaises(ValueError):self.b.engine.confirm_delivery_allocations(self.b.delivery().name,'CONF','TOKEN')
    def test_no_refusal_retains_native_full_load_and_no_outcome(self):
        self.assertIsNone(self.declare(5));self.b.start();self.assertFalse(self.plan.driver_delivery_outcome)
        self.assertEqual(self.b.delivery().allocations if hasattr(self.b.delivery(),'allocations') else None,None)
    def test_recorded_decision_is_immutable_and_native_start_reuses_session(self):
        self.start();name=self.b.delivery().name;self.b.start('SAMEPHYSICAL')
        self.assertEqual(self.b.delivery().name,name);self.assertEqual(len(self.data[OUT]),1)
        with self.assertRaisesRegex(ValueError,'already'):self.declare(4)
    def test_supervisor_release_waits_for_delivery_proof_and_reason(self):
        outcome=self.start();self.post();self.supervisor()
        with self.assertRaisesRegex(ValueError,'proof'):self.out.release(outcome,[outcome.lines[0].name],'Sound stock',self.operator,self.session)
        self.b.delivery().state='Closed'
        with self.assertRaisesRegex(ValueError,'reason'):self.out.release(outcome,[outcome.lines[0].name],'',self.operator,self.session)
        self.out.release(outcome,[outcome.lines[0].name],'Customer reduced order',self.operator,self.session)
        self.assertEqual(self.b.unit.reserved_qty,0);self.assertEqual(self.b.unit.available_qty,2)
        self.assertEqual(outcome.lines[0].stock_state,'Available for Resale')
    def test_release_uses_current_held_row_after_recovery_changed_a_stale_outcome_snapshot(self):
        outcome=self.start();self.post();self.b.delivery().state='Closed';self.supervisor()
        live=outcome.lines[0];outcome.lines=[native.Record(dict(live))]
        live.stock_state='Recovery Reserved'
        with self.assertRaisesRegex(ValueError,'Only stock still held'):
            self.out.release(outcome,[live.name],'Release',self.operator,self.session)
        self.assertEqual(live.stock_state,'Recovery Reserved');self.assertEqual(self.b.unit.reserved_qty,2)

    def test_quality_hold_cannot_be_released_without_qc_resale_result(self):
        outcome=self.start(3,'Damaged');self.post();self.b.delivery().state='Closed';self.supervisor()
        with self.assertRaisesRegex(ValueError,'QC must approve'):self.out.release(outcome,[outcome.lines[0].name],'Resale',self.operator,self.session)
        case=next(iter(self.data[CASE].values()));self.qc(case)
        self.out.release(outcome,[outcome.lines[0].name],'QC approved',self.operator,self.session)
        self.assertEqual(self.b.unit.available_qty,2)
    def test_release_uses_fresh_locked_child_values_after_a_stale_parent_read(self):
        outcome=self.start();self.post();self.b.delivery().state='Closed';self.supervisor()
        original=outcome.lines[0];stale=native.Record(original);outcome.lines=[stale]
        original.stock_state='Recovery Reserved'
        with self.assertRaisesRegex(ValueError,'Only stock still held'):
            self.out.release(outcome,[original.name],'Release',self.operator,self.session)
        self.assertEqual(self.b.unit.reserved_qty,2)

    def test_profile_auto_release_applies_only_after_native_closed_feedback(self):
        self.plan.profile_snapshot_json=json.dumps({'auto_submit_delivery_note':1,'sound_refusal_policy':'Allow Resale After Delivery'})
        outcome=self.start();self.post();self.assertEqual(outcome.lines[0].stock_state,'Held')
        self.b.delivery().state='Closed';self.b.bridge.sync_plan_delivery(self.b.delivery())
        self.assertEqual(outcome.lines[0].stock_state,'Available for Resale');self.assertEqual(self.b.unit.available_qty,2)
    def test_recovery_adopts_then_restores_hold_after_cancel_or_transfer(self):
        outcome=self.start();self.post();line=outcome.lines[0]
        manifest=native.Record(name='RECOVERY',source_warehouse='LORRY1',destination_warehouse='QC WH',lines=[native.Record(dispatch_allocation=line.dispatch_allocation)])
        self.out.recovery_adopt(manifest);self.assertEqual(self.b.unit.reserved_qty,0);self.assertEqual(line.stock_state,'Recovery Reserved')
        self.out.recovery_restore(manifest);self.assertEqual(self.b.unit.reserved_qty,2);self.assertEqual(line.stock_state,'Held')
        self.out.recovery_adopt(manifest);self.b.unit.current_warehouse='QC WH';self.out.recovery_restore(manifest,received=True)
        self.assertEqual(line.current_warehouse,'QC WH');self.assertEqual(line.stock_state,'Transferred Hold');self.assertEqual(self.b.unit.reserved_qty,2)
        self.out.recovery_restore(manifest,received=True);self.assertEqual(self.b.unit.reserved_qty,2)
    def test_released_refusal_no_longer_consumes_original_plan_recovery_budget(self):
        outcome=self.start();self.post();self.b.delivery().state='Closed';self.supervisor()
        self.out.release(outcome,[outcome.lines[0].name],'Resale',self.operator,self.session)
        self.assertEqual(self.out.released_source_qty('ALLOC'),2)

if __name__=='__main__':unittest.main()
