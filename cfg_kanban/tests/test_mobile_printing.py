"""Actual mobile document functions with offline native/transaction doubles.

These tests do not prove ERPNext posting, MariaDB concurrency or Bluetooth output.
"""
import copy
import datetime
import hashlib
import json
import math
import sys
import types
import unittest
from unittest.mock import Mock, patch

from cfg_kanban.tests.test_vehicle_overview import Row, load, ROOT


class Doc:
    def __init__(self, **values):
        self.__dict__.update(values)
        self.flags = Row()
        self.modified = '2026-11-23 12:00:00'
        self.denied = set()
    def __getattr__(self, key):
        return None
    def get(self, key, default=None):
        return self.__dict__.get(key, default)
    def set(self, key, value):
        setattr(self, key, value)
    def check_permission(self, permission):
        if permission in self.denied:
            raise PermissionError(permission)
    def db_set(self, field, value=None, **kwargs):
        self.__dict__.update(field if isinstance(field, dict) else {field: value})
    def precision(self, field):
        return 3


def canonical(namespace, *args):
    return hashlib.sha256(json.dumps([namespace, *args], sort_keys=True, default=str).encode()).hexdigest()


class TestMobilePrinting(unittest.TestCase):
    def setUp(self):
        self.data = {}; self.inserts = []; self.queries = []; self.renders = []
        self.operator = Doc(employee='DRIVER', can_complete=1)
        self.session = Doc(name='SESSION', terminal_user='driver@example.com')
        self.roles = {'Stock Manager'}
        self.frappe = Row(get_doc=self.get_doc, get_all=self.get_all, get_list=self.get_all,
            get_print=self.render, has_permission=self.has_permission, as_json=json.dumps,
            parse_json=json.loads, throw=self.throw, PermissionError=PermissionError,
            session=Row(user='office@example.com'), get_roles=lambda:list(self.roles), only_for=self.only_for,
            local=Row(), db=Row(get_value=self.get_value, sql=self.sql))
        self.ns = load('services/mobile_printing.py', dict(frappe=self.frappe, math=math, json=json,
            hashlib=hashlib, canonical_key=canonical, cint=lambda x:int(x or 0),
            flt=lambda x, p=None: round(float(x or 0), p) if p is not None else float(x or 0),
            now_datetime=lambda:datetime.datetime(2026, 11, 23, 12), record=Mock(),
            get_datetime=lambda value:datetime.datetime.fromisoformat(str(value))))
        self.trip = self.add('CFG Kanban Delivery Trip', 'TRIP', company='A', driver_route_revision=3,
            dispatch_plans=[], stops=[Doc(stop_key='STOP', customer='C1', stop_purpose='Delivery')])
        self.add('Customer', 'C1'); self.add('Company', 'A')
        self.profile = self.add(self.ns['PROFILE'], 'A', company='A', enabled=1, paper_width_mm=80,
            printable_width=576, dpi=203, invoice_mode='Draft', invoice_operators=[])
        self.add('UOM', 'Nos', must_be_whole_number=1); self.add('UOM', 'Kg', must_be_whole_number=0)
        self.case = self.add(self.ns['CASE'], 'CASE', driver_trip='TRIP', driver_stop_key='STOP', selling_company='A',
            customer='C1', state='Awaiting QC Receipt', return_flow='Customer Return for QC',
            stock_already_owned=0, collected_on='2026-11-23', lines=[Doc(name='RL', item_code='ITEM',
            claimed_qty=5, batch_no='BATCH', expiry_date='2027-01-01', stock_uom='Kg')])
        self.source = self.add('Sales Invoice', 'INV', company='A', customer='C1', docstatus=1)
        self.fmt = self.add('Print Format', 'CUSTOM', doc_type='Sales Invoice', disabled=0, raw_printing=0)
        self.catalog = [dict(doctype='Sales Invoice', name='INV')]
        self.native_catalog = self.ns['_catalog']
        self.ns['_catalog'] = Mock(side_effect=lambda *args:copy.deepcopy(self.catalog))
        views = types.ModuleType('cfg_kanban.services.driver_routes')
        views._access = lambda *a:(self.operator, self.session)
        views._trip = lambda *a:self.trip
        views.trip_vehicle_warehouse=load('services/driver_routes.py',dict(frappe=self.frappe))['trip_vehicle_warehouse']
        actions = types.ModuleType('cfg_kanban.services.driver_route_actions'); actions._core = lambda doc:'SCOPE'
        auth = types.ModuleType('cfg_kanban.services.operator_auth'); auth.require_operator = self.auth
        office = types.ModuleType('cfg_kanban.services.delivery_trips')
        office.EDITORS = ('Stock Manager', 'Sales Manager', 'System Manager', 'CFG Kanban System Maintenance')
        self.auth_calls = []
        mod = types.ModuleType('cfg_kanban.services.mobile_printing'); mod.__dict__.update(self.ns)
        p=patch.dict(sys.modules, {m.__name__:m for m in (views, actions, auth, office, mod)});p.start();self.addCleanup(p.stop)
    def only_for(self, roles):
        if not self.roles.intersection(roles):
            raise PermissionError('Office authority')
    def auth(self, token, action=None):
        self.auth_calls.append((token,action))
        if not self.operator.can_complete and action=='complete':
            raise PermissionError('Complete')
        return self.operator, self.session
    def throw(self, message, exc=ValueError):
        raise exc(message)
    def add(self, doctype, name, **values):
        doc=Doc(doctype=doctype, name=name, **values);self.data.setdefault(doctype,{})[name]=doc;return doc
    def has_permission(self, doctype, ptype=None, doc=None):
        row=self.data.get(doctype,{}).get(doc)
        return not row or (ptype or 'read') not in row.denied
    def get_doc(self, doctype, name=None, **kw):
        if isinstance(doctype,dict):
            doc=Doc(**doctype)
            def insert(**kwargs):
                self.ns['controlled_document'](doc)
                doc.name='NEW'+str(len(self.inserts)+1);self.inserts.append(doc)
                self.data.setdefault(doc.doctype,{})[doc.name]=doc;return doc
            doc.insert=insert;return doc
        self.queries.append((doctype,name,kw));return self.data[doctype][name]
    def get_all(self, doctype, filters=None, fields=None, pluck=None, **kw):
        def match(row):
            for key, target in (filters or {}).items():
                if isinstance(target,list):
                    if target[0]=='in' and row.get(key) not in target[1]:return False
                elif row.get(key)!=target:return False
            return True
        rows=[r for r in self.data.get(doctype,{}).values() if match(r)]
        if kw.get('limit_page_length'): rows=rows[:kw['limit_page_length']]
        if pluck:return [r.get(pluck) for r in rows]
        return [Row({f:r.get(f) for f in fields}) if fields else r for r in rows]
    def sql(self, query, args, **kwargs):
        if 'tabCFG Kanban Mobile Print Job' in query:
            return self.get_all(self.ns['JOB'], filters={'document_type':args[0], 'document_name':args[1],
                'status':['in',['Prepared','Awaiting Confirmation']]}, fields=['name'])
        if 'tabCFG Kanban Return Custody Label' in query:
            return self.get_all(self.ns['LABEL'], filters={'return_case':args[0], 'return_line':args[1]}, fields=['qty'])
        return []
    def get_value(self, doctype, name, field):
        if isinstance(name,dict):
            rows=self.get_all(doctype,filters=name);return rows[0].get(field) if rows else None
        return self.data[doctype][name].get(field)
    def render(self, doctype, name, **kwargs):
        self.renders.append((doctype,name,kwargs))
        return '<html><div class="print-format">'+kwargs['print_format']+'</div></html>'
    def prepare(self, **values):
        args=dict(doctype='Sales Invoice', name='INV', print_format='CUSTOM', copies=1)
        args.update(values)
        result=self.ns['_prepare'](self.trip,'STOP',args,self.operator,self.session,'KEY')
        return self.data[self.ns['JOB']][result['print_job']]
    def label(self, **values):
        args=dict(return_case='CASE',return_line='RL',qty=3);args.update(values)
        return self.ns['_label'](self.trip,self.trip.stops[0],args,self.operator,self.session,'LABELKEY')
    def segment(self, job, outcome='Awaiting Confirmation', **values):
        args=dict(print_job=job.name,page=1,frame_hashes=['a'*64,'b'*64],outcome=outcome);args.update(values)
        return self.ns['_segment'](self.trip,args,self.operator)

    def test_printer_dimensions_are_frozen_for_resuming_the_original_job(self):
        job=self.prepare(printer_settings={'dpi':203,'paper_width_mm':80,'printable_width':512})
        self.profile.printable_width=576
        result=self.ns['get_mobile_print_job']('TRIP',job.name,'TOKEN')
        self.assertEqual(result['printer_settings']['printable_width'],512)
        self.assertNotIn('key',job.printer_settings_json)
    def test_native_format_is_rendered_without_pdf_or_binary_persistence(self):
        job=self.prepare()
        self.assertEqual(job.print_format,'CUSTOM');self.assertEqual(job.status,'Prepared')
        self.assertNotIn('html',job.__dict__);self.assertNotIn('raster',job.__dict__)
        self.assertEqual(self.renders[0][2]['as_pdf'],False)
        self.assertEqual(self.renders[0][2]['doc'],self.source)
    def test_wrong_doctype_disabled_and_raw_formats_reject(self):
        for field,value in [('doc_type','Delivery Note'),('disabled',1),('raw_printing',1)]:
            with self.subTest(field=field):
                before=getattr(self.fmt,field);setattr(self.fmt,field,value)
                with self.assertRaises(ValueError):self.prepare()
                setattr(self.fmt,field,before)
        self.assertFalse(self.inserts)
    def test_tag_print_expiry_keeps_earliest_tag_batch_and_certified_printed_date(self):
        self.add('Batch','BATCH',expiry_date='2027-03-01')
        unit=Doc(name='TAG',batch_no='BATCH',item_code='BAG',stock_uom='Nos',expiry_date='2027-02-01',process_certificate_set='CERT')
        evidence=types.ModuleType('cfg_kanban.services.certificate_output_evidence')
        evidence.certificate_output_evidence=Mock(return_value=[{'printed_expiry':'2027-01-01'}])
        evidence.printed_expiry_dates=lambda data:[r['printed_expiry'] for r in data]
        with patch.dict(sys.modules,{evidence.__name__:evidence}):
            self.assertEqual(self.ns['_stock_print_expiry'](unit),'2027-01-01')
        self.assertFalse(self.inserts)
    def test_empty_profile_format_uses_native_doctype_default(self):
        self.frappe.get_meta=lambda dt:Doc(default_print_format='CUSTOM')
        job=self.prepare(print_format=None)
        self.assertEqual(job.print_format,'CUSTOM')
    def test_ordinary_driver_can_select_native_format_without_reading_its_definition(self):
        self.fmt.denied.add('read')
        job=self.prepare()
        self.assertEqual(job.print_format,'CUSTOM')
        self.assertIn('CUSTOM',self.ns['_formats']('Sales Invoice'))
    def test_read_and_print_permissions_both_apply(self):
        for permission in ('read','print'):
            self.source.denied={permission}
            with self.assertRaises(PermissionError):self.prepare()
        self.assertFalse(self.inserts)
    def test_arbitrary_unlinked_document_is_rejected_before_render(self):
        with self.assertRaises(PermissionError):self.prepare(name='OTHER')
        self.assertFalse(self.renders)
    def test_copy_bounds_and_unfinished_job_block_duplicate_preparation(self):
        for copies in (0,6,-1,1.5,float('nan')):
            with self.assertRaises(ValueError):self.prepare(copies=copies)
        self.prepare()
        with self.assertRaisesRegex(ValueError,'unfinished'):self.prepare()
    def test_blocker_error_identifies_the_exact_original_job(self):
        job=self.prepare();job.operator='OTHER'
        with self.assertRaisesRegex(ValueError,job.name):self.prepare()
    def test_context_exposes_blocker_from_another_operator_trip_and_stop(self):
        job=self.prepare();job.operator='OTHER';job.delivery_trip='OLD';job.stop_key='OLD-STOP'
        self.ns['_formats']=lambda dt:['CUSTOM'];self.ns['default_format']=lambda *a:'CUSTOM'
        self.ns['_custody_lines']=lambda *a:[]
        self.ns['_sessions']=lambda *a:[]
        result=self.ns['get_mobile_print_context']('TRIP','TOKEN','STOP')
        self.assertEqual(len(result['active_jobs']),1)
        row=result['active_jobs'][0]
        self.assertEqual((row.name,row.operator,row.delivery_trip,row.stop_key),(job.name,'OTHER','OLD','OLD-STOP'))
        self.assertFalse(row.can_resume)
        with self.assertRaises(PermissionError):self.ns['get_mobile_print_job']('TRIP',job.name,'TOKEN')
    def test_blocker_discovery_keeps_company_document_pairs_and_native_list_permissions(self):
        original=self.prepare();original.operator='OTHER';original.stop_key='OTHER-STOP'
        for name,dt,source,company in [('UNRELATED','Sales Invoice','OTHER','A'),
                ('PAIR1','Sales Invoice','TAG','A'),('PAIR2',self.ns['HU'],'INV','A'),
                ('OTHERCO','Sales Invoice','INV','B')]:
            self.add(self.ns['JOB'],name,company=company,delivery_trip='OLD',operator='OTHER',
                stop_key='OLD',document_type=dt,document_name=source,status='Prepared')
        entries=self.catalog+[dict(doctype=self.ns['HU'],name='TAG')]
        jobs=self.ns['_unfinished_jobs'](self.trip,'STOP',self.operator,entries)
        self.assertEqual([r.name for r in jobs],[original.name])
        self.frappe.get_list=Mock(return_value=[])
        self.assertEqual(self.ns['_unfinished_jobs'](self.trip,'STOP',self.operator,entries),[])
        self.assertEqual(self.frappe.get_list.call_count,2)
    def test_current_operator_jobs_survive_catalog_changes_but_other_jobs_do_not_leak(self):
        own=self.prepare();self.catalog=[]
        jobs=self.ns['_unfinished_jobs'](self.trip,'STOP',self.operator,[])
        self.assertEqual([r.name for r in jobs],[own.name]);self.assertTrue(jobs[0].can_resume)
        own.operator='OTHER'
        self.assertEqual(self.ns['_unfinished_jobs'](self.trip,'STOP',self.operator,[]),[])
    def test_same_operator_can_resume_another_stop_on_this_trip_using_original_scope(self):
        job=self.prepare();job.stop_key='EARLIER'
        self.trip.stops.append(Doc(stop_key='EARLIER',customer='C1',stop_purpose='Delivery'))
        jobs=self.ns['_unfinished_jobs'](self.trip,'STOP',self.operator,self.catalog)
        self.assertTrue(jobs[0].can_resume)
        result=self.ns['get_mobile_print_job']('TRIP',job.name,'TOKEN')
        self.assertEqual(result['stop_key'],'EARLIER')
        self.ns['_catalog'].assert_called_with(self.trip,'EARLIER',self.operator)
        p=patch.dict(sys.modules,{'cfg_kanban.services.mobile_invoicing':types.ModuleType('cfg_kanban.services.mobile_invoicing')});p.start();self.addCleanup(p.stop)
        request=dict(action='Close Mobile Print',dispatch_plan=None,stop_key='STOP',payload=dict(print_job=job.name,reason='Checked'))
        with self.assertRaisesRegex(ValueError,'another customer stop'):
            self.ns['action'](self.trip,request,self.operator,self.session,'TOKEN','CLOSE')
        self.assertEqual(job.status,'Prepared')
        request['stop_key']='EARLIER';self.ns['action'](self.trip,request,self.operator,self.session,'TOKEN','CLOSE')
        self.assertEqual(job.status,'Abandoned')
    def test_office_can_close_reassigned_closed_trip_job_without_rendering_changed_source(self):
        job=self.prepare();job.operator='PREVIOUS';self.trip.state='Closed'
        self.source.modified='CHANGED';job.segments_json=json.dumps({'pages':{'1':{'status':'Operator Confirmed'},'2':{'status':'Outcome Unknown'}}})
        segments=job.segments_json;renders=len(self.renders)
        result=self.ns['close_mobile_print_job'](job.name,' Checked paper; prepare corrected format ',job.modified)
        self.assertEqual(result,dict(print_job=job.name,job_status='Abandoned'))
        self.assertEqual((job.reason,job.closed_by,job.operator),('Checked paper; prepare corrected format','office@example.com','PREVIOUS'))
        self.assertTrue(job.closed_on);self.assertFalse(job.confirmed_on)
        self.assertEqual(job.segments_json,segments);self.assertEqual(len(self.renders),renders)
        self.assertEqual(self.source.modified,'CHANGED')
        event=self.ns['record'].call_args
        self.assertEqual(event.args,('Mobile Print Job Closed',))
        self.assertEqual(event.kwargs['payload']['closure_source'],'Office')
        self.assertEqual(event.kwargs['payload']['prepared_by'],'PREVIOUS')
        self.assertIn((self.ns['JOB'],job.name,{'for_update':True}),self.queries)
    def test_office_close_requires_native_authority_job_trip_and_company_permissions(self):
        job=self.prepare()
        self.roles={'Stock User'}
        self.assertFalse(self.ns['can_close_mobile_print_job'](job))
        with self.assertRaises(PermissionError):self.ns['close_mobile_print_job'](job.name,'Reviewed',job.modified)
        self.roles={'Stock Manager'}
        for doc,permission in [(job,'read'),(self.trip,'read'),(self.trip,'write'),(self.data['Company']['A'],'read')]:
            doc.denied={permission}
            self.assertFalse(self.ns['can_close_mobile_print_job'](job))
            with self.assertRaises(PermissionError):self.ns['close_mobile_print_job'](job.name,'Reviewed',job.modified)
            doc.denied=set()
        self.assertTrue(self.ns['can_close_mobile_print_job'](job));self.assertEqual(job.status,'Prepared')
        self.ns['record'].assert_not_called()
    def test_office_close_rejects_company_mismatch_blank_reason_and_stale_version(self):
        job=self.prepare();self.trip.company='B'
        with self.assertRaises(PermissionError):self.ns['close_mobile_print_job'](job.name,'Reviewed',job.modified)
        self.trip.company='A'
        for reason,version,message in [(' ',job.modified,'reason'),('Reviewed',None,'changed'),
                ('Reviewed','2026-11-22 12:00:00','changed')]:
            with self.assertRaisesRegex(ValueError,message):self.ns['close_mobile_print_job'](job.name,reason,version)
        self.assertEqual(job.status,'Prepared');self.ns['record'].assert_not_called()
    def test_repeated_office_closure_preserves_first_reason_and_single_audit(self):
        job=self.prepare();self.ns['close_mobile_print_job'](job.name,'First reason',job.modified)
        result=self.ns['close_mobile_print_job'](job.name,'Different reason','2026-11-22 00:00:00')
        self.assertTrue(result['already_closed']);self.assertEqual(job.reason,'First reason')
        self.assertEqual(self.ns['record'].call_count,1)
        new=self.prepare();self.assertNotEqual(new.name,job.name)
    def test_operator_close_is_audited_and_does_not_grant_other_operator_job_ownership(self):
        job=self.prepare();request=dict(action='Close Mobile Print',dispatch_plan=None,stop_key='STOP',payload=dict(print_job=job.name,reason='Checked physical receipt'))
        p=patch.dict(sys.modules,{'cfg_kanban.services.mobile_invoicing':types.ModuleType('cfg_kanban.services.mobile_invoicing')});p.start();self.addCleanup(p.stop)
        job.operator='OTHER'
        with self.assertRaises(PermissionError):self.ns['action'](self.trip,request,self.operator,self.session,'TOKEN','CLOSE')
        job.operator='DRIVER';self.ns['action'](self.trip,request,self.operator,self.session,'TOKEN','CLOSE')
        event=self.ns['record'].call_args.kwargs
        self.assertEqual((event['operator'],event['operator_session']),('DRIVER','SESSION'))
        self.assertEqual(event['payload']['closure_source'],'Driver')
    def test_confirmed_job_cannot_be_abandoned_or_overwritten(self):
        job=self.prepare();job.status='Operator Confirmed';job.confirmed_on='CONFIRMED'
        with self.assertRaisesRegex(ValueError,'ended'):self.ns['close_mobile_print_job'](job.name,'Reviewed',job.modified)
        self.assertEqual((job.status,job.confirmed_on),('Operator Confirmed','CONFIRMED'))
        self.ns['record'].assert_not_called()
    def test_document_or_format_change_blocks_resume_and_handoff(self):
        job=self.prepare();self.source.modified='CHANGED'
        with self.assertRaisesRegex(ValueError,'changed'):
            self.ns['get_mobile_print_job']('TRIP',job.name,'TOKEN')
        with self.assertRaisesRegex(ValueError,'changed'):self.segment(job)
        self.assertEqual(job.status,'Prepared')
    def test_handoff_is_not_confirmation_and_unknown_never_advances(self):
        job=self.prepare();self.segment(job)
        self.assertEqual(job.status,'Awaiting Confirmation');self.assertFalse(job.confirmed_on)
        self.segment(job,'Outcome Unknown')
        with self.assertRaisesRegex(ValueError,'previous'):
            self.segment(job,page=2)
        with self.assertRaisesRegex(ValueError,'reason'):self.segment(job)
        self.segment(job,reason='App did not open; checked no receipt')
        self.assertEqual(json.loads(job.segments_json)['pages']['1']['attempts'],2)
    def test_ordered_confirmation_finishes_once_and_cannot_replay_with_new_identity(self):
        job=self.prepare();self.segment(job)
        self.segment(job,'Operator Confirmed')
        self.assertEqual(job.status,'Awaiting Confirmation')
        self.segment(job,page=2);self.segment(job,'Operator Confirmed',page=2)
        self.assertEqual(job.status,'Operator Confirmed');self.assertTrue(job.confirmed_on)
        with self.assertRaises(ValueError):self.segment(job,'Operator Confirmed',page=2)
    def test_changed_manifest_or_noncollated_copies_reject(self):
        job=self.prepare(copies=2)
        for hashes in [['a'*64,'b'*64],['bad'],[]]:
            with self.assertRaises(ValueError):self.segment(job,frame_hashes=hashes)
        hashes=['a'*64,'b'*64]*2
        self.segment(job,frame_hashes=hashes)
        with self.assertRaises(ValueError):self.segment(job,frame_hashes=['a'*64]*4)
    def test_custody_label_preserves_identity_and_posts_no_stock_or_credit(self):
        result=self.label();label=self.data[self.ns['LABEL']][result['custody_label']]
        self.assertEqual((label.return_line,label.item_code,label.batch_no,label.expiry_date,label.stock_uom,label.qty),('RL','ITEM','BATCH','2027-01-01','Kg',3))
        self.assertEqual(label.custody_notice,'Pending QC — not available stock')
        self.assertEqual({d.doctype for d in self.inserts},{self.ns['LABEL']})
        self.assertTrue(any(dt==self.ns['CASE'] and kw.get('for_update') for dt,_,kw in self.queries))
    def test_split_labels_cannot_exceed_returned_quantity(self):
        self.label(qty=3)
        with self.assertRaises(ValueError):self.label(qty=3)
        self.label(qty=2);self.assertEqual(sum(d.qty for d in self.inserts),5)
    def test_invalid_label_quantities_and_uom_precision_reject(self):
        for qty in (-1,0,float('nan'),float('inf'),1.2345,6):
            with self.subTest(qty=qty),self.assertRaises(ValueError):self.label(qty=qty)
        self.case.lines[0].stock_uom='Nos'
        with self.assertRaisesRegex(ValueError,'whole'):self.label(qty=1.5)
    def test_labels_reject_other_customer_trip_row_or_qc_started(self):
        for field,value in [('driver_trip','OTHER'),('customer','OTHER'),('state','QC In Progress'),('stock_already_owned',1),('collected_on',None)]:
            before=getattr(self.case,field);setattr(self.case,field,value)
            with self.subTest(field=field),self.assertRaises((ValueError,PermissionError)):self.label()
            setattr(self.case,field,before)
        with self.assertRaises(ValueError):self.label(return_line='OTHER')
    def test_completed_custody_job_counts_only_after_all_segments(self):
        result=self.label();label=self.data[self.ns['LABEL']][result['custody_label']]
        label.print_count=0;self.catalog=[dict(doctype=label.doctype,name=label.name)]
        self.add('Print Format','LABELFMT',doc_type=label.doctype,disabled=0,raw_printing=0)
        job=self.prepare(doctype=label.doctype,name=label.name,print_format='LABELFMT')
        self.segment(job);self.segment(job,'Operator Confirmed');self.assertEqual(label.print_count,0)
        self.segment(job,page=2);self.segment(job,'Operator Confirmed',page=2);self.assertEqual(label.print_count,1)
        with self.assertRaises(ValueError):self.segment(job,'Operator Confirmed',page=2)
        self.assertEqual(label.print_count,1)
    def test_controlled_records_reject_direct_edit_and_delete(self):
        with self.assertRaises(ValueError):self.ns['controlled_document'](Doc())
        with self.assertRaises(ValueError):self.ns['no_delete']()
    def test_profile_rejects_impossible_dots_and_unapproved_auto_submission(self):
        self.ns['validate_profile'](self.profile)
        for field,value in [('printable_width',575),('paper_width_mm',40),('dpi',99),('invoice_mode','Automatic Submission')]:
            before=getattr(self.profile,field);setattr(self.profile,field,value)
            with self.subTest(field=field),self.assertRaises(ValueError):self.ns['validate_profile'](self.profile)
            setattr(self.profile,field,before)
    def test_custody_qr_opens_live_case_with_native_permissions(self):
        result=self.label();name=result['custody_label']
        self.frappe.db.table_exists=lambda dt:True
        self.frappe.db.exists=lambda dt,name:name in self.data.get(dt,{})
        resolve=self.ns['custody_case_scan']
        self.assertEqual(resolve('CFG:RETURN-CUSTODY:'+name),'CASE')
        self.case.state='QC Completed - Accounting Pending'
        self.assertEqual(resolve('CFG:RETURN-CUSTODY:'+name),'CASE')
        self.data[self.ns['LABEL']][name].denied.add('read')
        with self.assertRaises(PermissionError):resolve('CFG:RETURN-CUSTODY:'+name)
        self.assertEqual(resolve('RM00001'),'RM00001')
        with self.assertRaises(ValueError):resolve('CFG:RETURN-CUSTODY:NOTFOUND')
    def test_native_catalog_has_explicit_note_invoice_and_return_links_only(self):
        note=self.add('Delivery Note','DN',company='A',customer='C1',docstatus=1,is_return=0,items=[])
        delivery=Doc(name='DELIVERY',delivery_note='DN')
        self.ns['_sessions']=lambda *a:[delivery]
        self.ns['_invoice_names']=lambda note:{'INV'}
        entries=self.native_catalog(self.trip,'STOP',self.operator)
        refs={(r['doctype'],r['name']) for r in entries}
        self.assertIn(('Delivery Note','DN'),refs);self.assertIn(('Sales Invoice','INV'),refs)
        self.assertIn((self.ns['CASE'],'CASE'),refs)
        self.assertNotIn(('Sales Invoice','UNLINKED'),refs)
        self.source.denied.add('print')
        self.assertNotIn(('Sales Invoice','INV'),{(r['doctype'],r['name']) for r in self.native_catalog(self.trip,'STOP',self.operator)})
    def test_linked_invoice_cannot_cross_customer_even_with_native_read_permission(self):
        self.add('Delivery Note','DN',company='A',customer='C1',docstatus=1,is_return=0,items=[])
        self.ns['_sessions']=lambda *a:[Doc(name='DELIVERY',delivery_note='DN')]
        self.ns['_invoice_names']=lambda note:{'INV'}
        self.source.customer='OTHER'
        with self.assertRaisesRegex(ValueError,'customer'):self.native_catalog(self.trip,'STOP',self.operator)
    def test_source_is_checked_again_after_current_read(self):
        self.source.company='B'
        with self.assertRaises(PermissionError):self.prepare()
        self.assertFalse(self.inserts)
    def test_source_change_after_handoff_still_allows_truthful_operator_confirmation(self):
        job=self.prepare();self.segment(job);self.source.modified='CHANGED'
        # Captures a statement about already handed-off paper, not permission for another send.
        self.segment(job,'Operator Confirmed')
        self.assertEqual(json.loads(job.segments_json)['pages']['1']['status'],'Operator Confirmed')
        with self.assertRaisesRegex(ValueError,'changed'):self.segment(job,page=2)
    def test_job_owner_company_and_trip_are_exact(self):
        job=self.prepare()
        for field,value in [('operator','OTHER'),('company','B'),('delivery_trip','OTHER')]:
            before=getattr(job,field);setattr(job,field,value)
            with self.subTest(field=field),self.assertRaises(PermissionError):self.ns['_job'](self.trip,job.name,self.operator)
            setattr(job,field,before)


    def stock_fixture(self):
        self.add('Company','A');self.vehicle=self.add('Warehouse','LORRY',company='A')
        self.trip.vehicle_warehouse=None;self.trip.driver_route_state='In Progress'
        self.trip.driver_route_snapshot_json=json.dumps(dict(vehicle='LORRY',scope_hash='SCOPE'))
        tag=self.add(self.ns['HU'],'TAG',current_qty=2)
        self.stock=Mock(return_value=dict(stock=[dict(item_code='ITEM',erp_qty=6,tag_qty=2,untagged_qty=4,
            tags=[Row(name=tag.name,current_qty=tag.current_qty)])]))
        module=types.ModuleType('cfg_kanban.services.vehicle_overview');module._stock=self.stock
        patcher=patch.dict(sys.modules,{module.__name__:module});patcher.start();self.addCleanup(patcher.stop)
        self.ns['_stock_print_expiry']=lambda tag:'2027-01-01'

    def test_stock_print_uses_frozen_departure_with_blank_header_and_current_stock(self):
        self.stock_fixture();rows=self.ns['trip_stock_rows'](self.trip)
        self.assertEqual(self.stock.call_args[0][0].name,'LORRY')
        self.assertEqual((rows[0]['erp_qty'],rows[0]['tag_qty'],rows[0]['untagged_qty']),(6,2,4))
        self.assertEqual(rows[0]['tags'][0].effective_expiry,'2027-01-01')
        self.assertIsNone(self.trip.vehicle_warehouse)

    def test_stock_print_keeps_native_warehouse_company_and_tag_permissions(self):
        self.stock_fixture();self.vehicle.denied.add('read')
        with self.assertRaises(PermissionError):self.ns['trip_stock_rows'](self.trip)
        self.stock.assert_not_called();self.vehicle.denied.clear();self.vehicle.company='B'
        with self.assertRaises(PermissionError):self.ns['trip_stock_rows'](self.trip)
        self.stock.assert_not_called();self.vehicle.company='A'
        self.data[self.ns['HU']]['TAG'].denied.add('read')
        self.assertEqual(self.ns['trip_stock_rows'](self.trip)[0]['tags'],[])

    def test_stock_print_rejects_changed_departure_scope_or_header_instead_of_guessing(self):
        self.stock_fixture();self.trip.vehicle_warehouse='WRONG'
        with self.assertRaisesRegex(ValueError,'frozen departure'):self.ns['trip_stock_rows'](self.trip)
        self.trip.vehicle_warehouse=None;self.trip.driver_route_snapshot_json=json.dumps(dict(vehicle='LORRY',scope_hash='CHANGED'))
        with self.assertRaisesRegex(ValueError,'Reconcile the Trip departure'):self.ns['trip_stock_rows'](self.trip)
        self.stock.assert_not_called()

    def test_unassigned_unstarted_trip_stock_print_does_not_invent_a_lorry(self):
        self.stock_fixture();self.trip.driver_route_state='Not Started';self.trip.driver_route_snapshot_json=None
        self.assertEqual(self.ns['trip_stock_rows'](self.trip),[]);self.stock.assert_not_called()


class TestDriverMobileReceipts(unittest.TestCase):
    def test_qc_custody_scan_retains_native_company_and_case_filters(self):
        from cfg_kanban.tests.test_return_qc_monitor import TestReturnQCMonitor
        base=TestReturnQCMonitor();base.setUp();self.addCleanup(base.doCleanups)
        mobile=types.ModuleType('cfg_kanban.services.mobile_printing')
        mobile.custody_case_scan=Mock(return_value='OLD')
        with patch.dict(sys.modules,{mobile.__name__:mobile}):
            case=base.ns['_case']('CFG:RETURN-CUSTODY:KRC-1',{'A'})
            self.assertEqual(case.name,'OLD')
            mobile.custody_case_scan.return_value='FOREIGN'
            with self.assertRaises(PermissionError):base.ns['_case']('CFG:RETURN-CUSTODY:KRC-2',{'A'})

    def test_invoice_label_and_print_replays_use_existing_driver_receipt(self):
        from cfg_kanban.tests.test_driver_route_actions import TestDriverRouteActions
        base=TestDriverRouteActions();base.setUp();self.addCleanup(base.doCleanups)
        mobile=types.ModuleType('cfg_kanban.services.mobile_printing');mobile.action=Mock(return_value={'invoice':'INV'})
        with patch.dict(sys.modules,{mobile.__name__:mobile}):
            for n,action in enumerate(('Create Sales Invoice','Create Custody Label','Prepare Mobile Print','Record Print Segment','Close Mobile Print')):
                request=base.request(action);request['event_token']='MOBILE'+str(n);request['dispatch_plan']=None
                request['payload']={}
                first=base.perform(request);again=base.perform(request)
                self.assertEqual(first,again)
            self.assertEqual(mobile.action.call_count,5)


if __name__=='__main__':unittest.main()
