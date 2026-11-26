"""Customer document automation over real mobile print functions, offline DB/ERP doubles.

Does not prove MariaDB transaction isolation, ERPNext mapper validation or paper output.
"""
import copy
import json
import sys
import types
import unittest
from unittest.mock import Mock, patch

from cfg_kanban.tests import test_mobile_printing as printing_tests
from cfg_kanban.tests.test_mobile_printing import Doc, canonical
from cfg_kanban.tests.test_vehicle_overview import load, Row, ROOT


class TestStopDocuments(unittest.TestCase):
    def setUp(self):
        self.p = printing_tests.TestMobilePrinting(); self.p.setUp(); self.addCleanup(self.p.doCleanups)
        self.frappe = self.p.frappe; self.frappe.ValidationError=ValueError; self.frappe.get_meta=lambda dt:Row(default_print_format='Standard'); self.trip = self.p.trip; self.stop = self.trip.stops[0]
        self.stop.customer_scan_point = 'SITE'; self.stop.driver_completed_on = '2026-11-26'
        self.site = self.p.add('CFG Kanban Customer Scan Point', 'SITE', selling_company='A', customer='C1')
        self.note = self.p.add('Delivery Note', 'DN', company='A', customer='C1', docstatus=1, is_return=0)
        self.p.catalog.extend([dict(doctype='Delivery Note', name='DN'),dict(doctype=self.p.ns['CASE'],name='CASE')])
        self.p.ns['_render'] = Mock(return_value=('<div>signed</div>', 'FORMAT-V1', 'HASH'))
        self.p.ns['_sessions'] = Mock(return_value=[Doc(delivery_note='DN')])
        self.printing = sys.modules['cfg_kanban.services.mobile_printing']
        self.printing.__dict__.update(self.p.ns)
        self.printing._invoice_names = Mock(return_value={'AUTO-INV'})
        self.module = types.ModuleType('cfg_kanban.services.stop_documents')
        self.ns = load('services/stop_documents.py', self.module.__dict__)
        self.ns.update(frappe=self.frappe,cint=lambda v:int(v or 0),now_datetime=lambda:'NOW',
                       canonical_key=canonical,insert_once=self.insert_once,record=Mock())
        self.TASK = self.ns['TASK']
        original = self.p.get_doc
        def get_doc(doctype, name=None, **kwargs):
            if isinstance(doctype,dict) and doctype['doctype']==self.TASK:
                task=Doc(**doctype)
                def insert(**kw):
                    self.ns['controlled'](task);task.name='TASK'+str(len(self.tasks())+1)
                    self.p.data.setdefault(self.TASK,{})[task.name]=task
                    return task
                task.insert=insert;return task
            return original(doctype,name,**kwargs)
        self.frappe.get_doc=get_doc
        self.invoicing = types.ModuleType('cfg_kanban.services.mobile_invoicing')
        self.invoicing.create=Mock(side_effect=self.invoice)
        scoped=patch.dict(sys.modules,{self.module.__name__:self.module,self.invoicing.__name__:self.invoicing})
        scoped.start();self.addCleanup(scoped.stop)
    def tasks(self):return list(self.p.data.get(self.TASK,{}).values())
    def insert_once(self, doc, key, **kwargs):
        for row in self.tasks():
            if row.idempotency_key==key:return row,False
        doc.idempotency_key=key;return doc.insert(**kwargs),True
    def invoice(self,*args,**kwargs):
        self.assertTrue(kwargs['draft_only'])
        self.assertEqual(self.frappe.local.cfg_mobile_invoice_token,'TOKEN')
        self.p.add('Sales Invoice','AUTO-INV',company='A',customer='C1',docstatus=0,is_return=0,update_stock=0)
        self.p.catalog.append(dict(doctype='Sales Invoice',name='AUTO-INV'))
        return dict(invoice='AUTO-INV',docstatus=0)
    def schedule(self,**options):
        for key,value in options.items():setattr(self.site,key,value)
        return self.ns['schedule_delivery'](self.trip,self.stop,self.p.operator)
    def execute_task(self,task,stop='STOP'):
        return self.ns['run'](self.trip,stop,task.name,self.p.operator,self.p.session,'TOKEN')
    def job_for(self,task):
        result=self.execute_task(task)
        return self.p.data[self.p.ns['JOB']][result['print_job']]
    def test_all_options_default_off_and_no_sources_or_posting_are_touched(self):
        self.assertEqual(self.schedule(),[])
        self.assertEqual(self.ns['schedule_return'](self.trip,self.stop,'CASE',self.p.operator),[])
        self.p.ns['_sessions'].assert_not_called();self.invoicing.create.assert_not_called()
        self.assertFalse(self.tasks());self.assertFalse(self.p.inserts)
    def test_independent_site_choices_snapshot_exact_source_and_two_separate_copies(self):
        self.schedule(auto_print_delivery_note=1,auto_create_draft_invoice=1,auto_print_draft_invoice=1)
        self.assertEqual({r.task_type for r in self.tasks()},{'Print Delivery Note','Create Draft Invoice','Print Draft Invoice'})
        for row in self.tasks():
            self.assertEqual((row.delivery_trip,row.stop_key,row.customer,row.source_name),('TRIP','STOP','C1','DN'))
            self.assertEqual(row.copies,0 if row.task_type=='Create Draft Invoice' else 2)
        count=len(self.tasks());self.schedule();self.assertEqual(len(self.tasks()),count)
        self.p.ns['_sessions'].return_value.append(Doc(delivery_note='DN'))
        self.schedule();self.assertEqual(len(self.tasks()),count)
    def test_only_submitted_notes_schedule_and_full_refusal_never_invents_an_invoice(self):
        self.note.docstatus=0
        self.assertEqual(self.schedule(auto_create_draft_invoice=1),[])
        self.p.ns['_sessions'].return_value=[Doc(delivery_note=None)]
        self.assertEqual(self.schedule(),[]);self.invoicing.create.assert_not_called()
    def test_new_settings_do_not_backfill_a_read_or_change_an_existing_task(self):
        self.schedule(auto_print_delivery_note=1);task=self.tasks()[0]
        self.site.auto_print_delivery_note=0;before=copy.copy(task.__dict__)
        self.ns['context'](self.trip,'STOP',self.p.operator)
        self.assertEqual(task.__dict__,before);self.execute_task(task)
        self.assertEqual(len(self.p.inserts),1)
    def test_print_retry_reuses_same_job_and_every_copy_waits_for_a_confirmed_handoff(self):
        self.schedule(auto_print_delivery_note=1);task=self.tasks()[0]
        first=self.execute_task(task);job=self.p.data[self.p.ns['JOB']][first['print_job']]
        self.assertEqual(job.copies,2)
        self.assertEqual(self.execute_task(task)['print_job'],job.name);self.assertEqual(len(self.p.inserts),1)
        manifest=['a'*64,'a'*64]
        self.p.segment(job,frame_hashes=manifest)
        self.p.segment(job,'Operator Confirmed',frame_hashes=manifest)
        state=json.loads(job.segments_json)
        self.assertNotIn('2',state['pages']);self.assertEqual(job.status,'Awaiting Confirmation')
        self.assertEqual(self.execute_task(task)['print_job'],job.name)
        self.p.segment(job,frame_hashes=manifest,page=2)
        self.p.segment(job,'Operator Confirmed',frame_hashes=manifest,page=2)
        self.assertEqual(self.ns['context'](self.trip,'STOP',self.p.operator)[0]['status'],'Operator Confirmed')
        self.assertEqual(len(self.p.inserts),1)
    def test_uncertain_output_is_not_silently_reprinted(self):
        self.schedule(auto_print_delivery_note=1);job=self.job_for(self.tasks()[0])
        hashes=['a'*64,'a'*64]
        self.p.segment(job,frame_hashes=hashes);self.p.segment(job,'Outcome Unknown',frame_hashes=hashes)
        self.execute_task(self.tasks()[0])
        with self.assertRaisesRegex(ValueError,'uncertain'):
            self.p.segment(job,frame_hashes=hashes)
        self.assertEqual(json.loads(job.segments_json)['pages']['1']['attempts'],1)
    def test_automatic_invoice_is_once_and_draft_and_later_office_submission_does_not_rebill(self):
        self.schedule(auto_create_draft_invoice=1,auto_print_draft_invoice=1)
        create=next(r for r in self.tasks() if r.task_type=='Create Draft Invoice')
        print_task=next(r for r in self.tasks() if r.task_type=='Print Draft Invoice')
        with self.assertRaisesRegex(ValueError,'before printing'):self.execute_task(print_task)
        self.execute_task(create);self.execute_task(create);self.invoicing.create.assert_called_once()
        job=self.job_for(print_task)
        self.assertEqual((job.document_type,job.document_name,job.copies),('Sales Invoice','AUTO-INV',2))
        self.p.data['Sales Invoice']['AUTO-INV'].docstatus=1
        self.assertEqual(self.execute_task(create)['docstatus'],1);self.invoicing.create.assert_called_once()
        self.assertIsNone(self.frappe.local.cfg_mobile_invoice_token)
    def test_print_invoice_only_requires_existing_exact_draft_and_never_creates_one(self):
        self.schedule(auto_print_draft_invoice=1)
        self.printing._invoice_names.return_value=set()
        with self.assertRaisesRegex(ValueError,'exactly one'):self.execute_task(self.tasks()[0])
        self.invoicing.create.assert_not_called();self.assertEqual(self.tasks()[0].status,'Pending')
    def test_return_note_uses_custody_case_and_does_not_create_stock_credit_or_invoice(self):
        self.site.auto_print_return_note=1;self.stop.driver_completed_on=None
        self.ns['schedule_return'](self.trip,self.stop,'CASE',self.p.operator)
        task=self.tasks()[0];job=self.job_for(task)
        self.assertEqual((job.document_type,job.document_name,job.copies),(self.p.ns['CASE'],'CASE',2))
        self.invoicing.create.assert_not_called();self.assertEqual(len(self.p.inserts),1)
    def test_wrong_stop_company_customer_and_unfinished_delivery_fail_before_preparation(self):
        self.schedule(auto_print_delivery_note=1);task=self.tasks()[0]
        with self.assertRaises(PermissionError):self.execute_task(task,stop='OTHER')
        for field,value in [('company','B'),('customer','C2')]:
            old=getattr(task,field);setattr(task,field,value)
            with self.assertRaises(PermissionError):self.execute_task(task)
            setattr(task,field,old)
        self.stop.driver_completed_on=None
        with self.assertRaisesRegex(ValueError,'Complete this'):self.execute_task(task)
        self.assertFalse(self.p.inserts)
    def test_native_print_permission_and_office_profile_fail_without_losing_task(self):
        self.schedule(auto_print_delivery_note=1);task=self.tasks()[0]
        self.note.denied={'print'}
        with self.assertRaises(PermissionError):self.execute_task(task)
        self.assertEqual(task.status,'Pending');self.assertFalse(self.p.inserts)
        self.note.denied=set();self.p.profile.enabled=0
        with self.assertRaisesRegex(ValueError,'Office setup'):self.execute_task(task)
        self.assertEqual(task.status,'Pending')
    def test_existing_manual_print_is_visible_blocker_not_replaced(self):
        self.schedule(auto_print_delivery_note=1);task=self.tasks()[0]
        job=self.p.prepare(doctype='Delivery Note',name='DN',print_format='Standard',copies=1)
        with self.assertRaisesRegex(ValueError,'unfinished print job: '+job.name):self.execute_task(task)
        self.assertEqual(len(self.p.inserts),1);self.assertIsNone(task.print_job)
    def test_completion_feedback_is_independent_of_print_job_read_permission(self):
        self.schedule(auto_print_delivery_note=1);task=self.tasks()[0];job=self.job_for(task)
        job.denied={'read'}
        self.assertEqual(self.ns['pending_names'](self.trip,'STOP'),[task.name])
        with self.assertRaises(PermissionError):self.ns['context'](self.trip,'STOP',self.p.operator)

    def test_recorded_invoice_changed_or_cancelled_by_office_is_not_replaced(self):
        self.schedule(auto_create_draft_invoice=1);task=self.tasks()[0];self.execute_task(task)
        invoice=self.p.data['Sales Invoice']['AUTO-INV'];invoice.docstatus=2
        with self.assertRaisesRegex(ValueError,'cancelled'):self.execute_task(task)
        self.invoicing.create.assert_called_once()

    def test_other_driver_cannot_resume_and_closed_job_never_spawns_new_copies(self):
        self.schedule(auto_print_delivery_note=1);task=self.tasks()[0]
        job=self.job_for(task)
        job.operator='OTHER'
        self.assertFalse(self.ns['context'](self.trip,'STOP',self.p.operator)[0]['can_resume'])
        with self.assertRaises(PermissionError):self.execute_task(task)
        job.operator=self.p.operator.employee;job.status='Abandoned'
        with self.assertRaisesRegex(ValueError,'closed'):self.execute_task(task)
        self.assertEqual(len(self.p.inserts),1)
    def test_tasks_cannot_be_created_or_changed_through_uncontrolled_form_or_deleted(self):
        with self.assertRaises(ValueError):self.ns['controlled'](Doc())
        with self.assertRaises(ValueError):self.ns['no_delete']()
    def test_native_finish_schedules_after_posting_and_does_not_wait_for_paper(self):
        for field in self.ns['OPTIONS']:setattr(self.site,field,1)
        self.stop.driver_completed_on=None
        actions=load('services/driver_route_actions.py',dict(frappe=self.frappe,now_datetime=lambda:'NOW'))
        actions.update(_is_ready=lambda *a:False,_documents=lambda:self.module)
        self.assertFalse(actions['_finish'](self.trip,self.stop,self.p.operator,'TOKEN'))
        self.assertFalse(self.tasks());self.assertIsNone(self.stop.driver_completed_on)
        actions['_is_ready']=lambda *a:True
        self.assertTrue(actions['_finish'](self.trip,self.stop,self.p.operator,'TOKEN'))
        self.assertEqual(len(self.tasks()),4)
        self.assertTrue(all(row.status=='Pending' for row in self.tasks()))
        self.assertEqual(self.trip.driver_route_state,'Completed')  # Printing never gates travel.
        self.assertTrue(actions['_finish'](self.trip,self.stop,self.p.operator,'TOKEN'))
        self.assertEqual(len(self.tasks()),4);self.invoicing.create.assert_not_called()
        self.assertFalse(self.p.inserts)

    def test_collecting_old_return_schedules_its_note_without_waiting_for_stop_completion(self):
        self.site.auto_print_return_note=1;self.stop.driver_completed_on=None
        collection=types.ModuleType('cfg_kanban.services.driver_collections')
        collection.collect=Mock(return_value=dict(return_case='CASE'))
        actions=load('services/driver_route_actions.py',dict(frappe=self.frappe,cint=lambda v:int(v or 0),require_operator=Mock()))
        actions.update(_core=lambda d:'SCOPE',_documents=lambda:self.module,
            _record=lambda doc,operator,session,key,request,result:result)
        request=dict(action='Collect Old Return',scope_hash='SCOPE',expected_revision=3,
            dispatch_plan=None,stop_key='STOP',payload={})
        with patch.dict(sys.modules,{collection.__name__:collection}):
            result=actions['_special_action'](self.trip,request,self.p.operator,self.p.session,'TOKEN','KEY')
        self.assertEqual(result['return_case'],'CASE');self.assertEqual(len(result['automatic_documents']),1)
        self.assertEqual(self.tasks()[0].task_type,'Print Return Note');self.assertFalse(self.p.inserts)

    def test_schema_default_off_no_hidden_mandatory_and_same_native_read_roles(self):
        base=ROOT/'cfg_kanban/doctype'
        task=json.loads((base/'cfg_kanban_stop_document_task/cfg_kanban_stop_document_task.json').read_text())
        site=json.loads((base/'cfg_kanban_customer_scan_point/cfg_kanban_customer_scan_point.json').read_text())
        fields={f['fieldname']:f for f in site['fields']}
        self.assertTrue(all(fields[name]['default']=='0' for name in self.ns['OPTIONS']))
        self.assertFalse(any(f.get('hidden') and f.get('reqd') and not f.get('default') for f in task['fields']))
        self.assertFalse(any(p.get('write') or p.get('create') for p in task['permissions']))


if __name__=='__main__':unittest.main()
