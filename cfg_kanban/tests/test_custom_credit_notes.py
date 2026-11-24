"""Optional custom Credit Note path with offline document/ERP substitutes.

No native custom-controller, database, tax, GL or e-Invoice acceptance is implied.
"""
import ast
import datetime
import json
import math
import hashlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
CASE = 'CFG Kanban Return Case'


class Doc(dict):
    def __getattribute__(self, key):
        if not key.startswith('_') and dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        return super().__getattribute__(key)
    def __getattr__(self, key):
        if key.startswith('__'): raise AttributeError(key)
        return self.get(key)
    def __setattr__(self, key, value): self[key] = value
    def set(self, key, value):
        self[key] = [Doc(row) for row in value] if isinstance(value, list) else value
    def as_dict(self):
        def clean(value):
            if isinstance(value, dict): return {k:clean(v) for k,v in dict.items(value) if not callable(v) and k not in ('meta',)}
            if isinstance(value, list): return [clean(v) for v in value]
            return value
        return clean(self)
    def check_permission(self, action): pass
    def db_set(self, key, value=None, **kwargs): self.update(key if isinstance(key, dict) else {key:value})
    def reload(self): return self




def load(path, common):
    module=types.ModuleType('cfg_kanban.'+path[:-3].replace('/','.'))
    module.__dict__.update(common)
    body=[]
    for node in ast.parse((ROOT/path).read_text()).body:
        if isinstance(node,(ast.FunctionDef,ast.Assign,ast.ClassDef)):
            if isinstance(node,ast.FunctionDef):node.decorator_list=[]
            body.append(node)
    exec(compile(ast.Module(body=body,type_ignores=[]),path,'exec'),module.__dict__)
    return module


class TestCustomCreditNotes(unittest.TestCase):
    def setUp(self):
        self.data={};self.events=[];self.permissions={};self.installed=True
        self.meta={};self.docs_created=[]
        self.schema('Sales Invoice', ['naming_series','is_return','return_against','company','customer','currency',
            'conversion_rate','selling_price_list','price_list_currency','plc_conversion_rate','debit_to','remarks','update_stock',
            'cfg_return_case','cfg_scan_event','return_against_credit_note'], {'items':'Sales Invoice Item','taxes':'Sales Taxes and Charges'})
        self.schema('Credit Note', ['naming_series','is_return','return_against','company','customer','currency',
            'conversion_rate','selling_price_list','price_list_currency','plc_conversion_rate','debit_to','remarks','update_stock',
            'cfg_return_case','cfg_scan_event'], {'items':'Credit Note Item','taxes':'Sales Taxes and Charges'})
        item=['item_code','qty','uom','stock_uom','conversion_factor','stock_qty','rate','income_account','sales_invoice_item']
        self.schema('Sales Invoice Item',item);self.schema('Credit Note Item',item)
        self.schema('Sales Taxes and Charges',['charge_type','tax_amount','account_head'])
        self.meta['Sales Invoice'].get_field('return_against_credit_note').update(fieldtype='Link',options='Credit Note')
        self.case=self.add(CASE,'CASE',return_flow='Customer Return for QC',state='QC Completed - Accounting Pending',
            accounting_status='Pending Source Selection',selling_company='B',customer='CUST',accounting_revision=0,
            accepted_total_qty=2,disposition_status='Not Started',
            lines=[Doc(item_code='ITEM',stock_uom='Kg',accepted_qty=2)])
        row=Doc(name='ORIGINAL-ITEM',item_code='ITEM',qty=5,stock_qty=10,uom='Bag',stock_uom='Kg',conversion_factor=2,
                rate=50,income_account='Sales - B',sales_invoice_item='ORIGINAL-ITEM')
        self.source=self.add('Sales Invoice','ORIGINAL',docstatus=1,is_return=0,company='B',customer='CUST',
            currency='MYR',conversion_rate=1,naming_series='INV-',items=[row],taxes=[])
        self.frappe=Doc(get_doc=self.get_doc,new_doc=self.new_doc,get_meta=lambda dt:self.meta[dt],get_all=self.get_all,
            has_permission=lambda dt,ptype='read',**kwargs:self.permissions.get((dt,ptype),True),
            only_for=Mock(),throw=self.throw,PermissionError=PermissionError,parse_json=json.loads,as_json=json.dumps,
            session=Doc(user='accountant'),db=Doc(sql=Mock(return_value=[]),get_value=self.get_value,
                exists=self.exists))
        common=dict(frappe=self.frappe,json=json,flt=lambda v:float(v or 0),isfinite=math.isfinite,_=lambda s:s,
            now_datetime=lambda:datetime.datetime(2026,11,20,12),record=lambda name,**kw:self.events.append((name,kw)),
            canonical_key=lambda *parts:'|'.join(map(str,parts)),insert_once=self.insert_once,
            get_default_naming_series=lambda dt:'CN-' if dt=='Credit Note' else 'INV-')
        self.gateway=load('integrations/erp_gateway.py',common)
        self.gateway.HANDLERS['Create Customer Credit Return']=self.gateway.create_customer_credit_return
        self.adapter=load('services/custom_credit_notes.py',common)
        self.feedback=load('integrations/return_accounting_feedback.py',common)
        self.returns=load('services/customer_returns.py',dict(common,execute_command=self.gateway.execute_command))
        mapper=types.ModuleType('erpnext.controllers.sales_and_purchase_return')
        mapper.make_return_doc=Mock(side_effect=self.map_return);self.mapper=mapper.make_return_doc
        modules={m.__name__:m for m in (self.adapter,self.feedback,self.gateway)}
        modules[mapper.__name__]=mapper
        self.patcher=patch.dict(sys.modules,modules);self.patcher.start();self.addCleanup(self.patcher.stop)
        self.payload=dict(source_sales_invoice='ORIGINAL',source_basis='Exact Sales Invoice',accepted_items={'ITEM':2},
                          decision_notes='QC accepted',accounting_revision=0,credit_document_doctype='Credit Note')
        self.command=Doc(return_case='CASE',idempotency_key='CMD',terminal_user='accountant')

    @staticmethod
    def throw(message, error=ValueError): raise error(message)
    def schema(self, dt, fields, tables=None):
        rows=[Doc(fieldname=f,fieldtype='Data',options=None) for f in fields]
        rows += [Doc(fieldname=f,fieldtype='Table',options=child) for f,child in (tables or {}).items()]
        meta=Doc(fields=rows,is_submittable=1,has_field=lambda field:any(r.fieldname==field for r in rows),
                 get_field=lambda field:next((r for r in rows if r.fieldname==field),None))
        self.meta[dt]=meta;return meta
    def add(self, dt, name, **values):
        doc=Doc(doctype=dt,name=name,**values)
        if dt in self.meta:doc.meta=self.meta[dt]
        doc.insert=lambda **kwargs:self.insert(doc)
        self.data.setdefault(dt,{})[name]=doc;return doc
    def new_doc(self, dt):
        doc=Doc(doctype=dt,meta=self.meta.get(dt),docstatus=0,naming_series='CN-' if dt=='Credit Note' else 'INV-')
        doc.insert=lambda **kwargs:self.insert(doc);return doc
    def insert(self, doc):
        if not doc.name:doc.name=('CN-' if doc.doctype=='Credit Note' else doc.doctype+'-')+str(len(self.data.get(doc.doctype,{}))+1)
        self.data.setdefault(doc.doctype,{})[doc.name]=doc;self.docs_created.append(doc.doctype);return doc
    def insert_once(self, doc, key, **kwargs):
        found=next((r for r in self.data.get(doc.doctype,{}).values() if r.get('idempotency_key')==key),None)
        if found:return found,False
        doc.idempotency_key=key;return self.insert(doc),True
    def get_doc(self, dt, name=None, **kwargs):
        if isinstance(dt,dict):
            d=Doc(dt);d.insert=lambda **kw:self.insert(d);return d
        return self.data[dt][name]
    def matches(self, row, filters):
        for key,value in (filters or {}).items():
            if isinstance(value,list):
                op,target=value
                if op=='in' and row.get(key) not in target:return False
                if op=='not in' and row.get(key) in target:return False
                if op=='<' and not row.get(key)<target:return False
            elif row.get(key)!=value:return False
        return True
    def get_all(self, dt, filters=None, **kwargs):
        return [row for row in self.data.get(dt,{}).values() if self.matches(row,filters)]
    def get_value(self, dt, name, field, **kwargs):
        row=self.data.get(dt,{}).get(name) if isinstance(name,str) else next(iter(self.get_all(dt,name)),None)
        return row.get(field) if row else None
    def exists(self, dt, name):
        if dt=='DocType':return self.installed if name=='Credit Note' else True
        return bool(self.get_value(dt,name,'name'))
    def map_return(self, dt, name):
        doc=self.new_doc('Sales Invoice');doc.update(self.source.as_dict());doc.name=None;doc.docstatus=0
        doc.meta=self.meta['Sales Invoice'];doc.is_return=1;doc.return_against=name
        doc.items=[Doc(self.source.items[0],qty=-5,stock_qty=-10)]
        return doc
    def create(self, custom=True):
        self.payload['credit_document_doctype']='Credit Note' if custom else 'Sales Invoice'
        return self.gateway.create_customer_credit_return(self.command,self.payload)
    def decision(self, custom=1, basis='Exact Sales Invoice'):
        return self.returns.prepare_accounting_decision('CASE',basis,'QC accepted',
            'ORIGINAL' if basis!='No Credit' else None,use_custom_credit_note=custom)
    def make_invoice(self, note, name='RETURN1'):
        invoice=self.new_doc('Sales Invoice');invoice.update(doctype='Sales Invoice',name=name,docstatus=0,
            return_against_credit_note=note.name,return_against='ORIGINAL',company='B',customer='CUST',is_return=1,
            update_stock=0,items=[Doc(row.as_dict()) for row in note.items])
        self.adapter.bind_invoice(invoice);self.insert(invoice);return invoice

    def test_gateway_custom_creates_cn_draft_using_qc_stock_qty_and_custom_child(self):
        note=self.create();self.assertEqual(note.doctype,'Credit Note');self.assertEqual(note.naming_series,'CN-')
        self.assertTrue(note.name.startswith('CN-'));self.assertEqual((note.items[0].qty,note.items[0].stock_qty),(-1,-2))
        self.assertEqual(note.items[0].sales_invoice_item,'ORIGINAL-ITEM')
        self.assertEqual(self.case.credit_document_doctype,'Credit Note');self.assertEqual(note.docstatus,0)
        self.assertEqual(self.docs_created,['Credit Note']);self.assertFalse(self.case.accounting_sales_invoice)
        self.assertEqual(note._cfg_command_result['doctype'],'Credit Note')
    def test_default_path_still_creates_only_sales_invoice_return(self):
        doc=self.create(False);self.assertEqual(doc.doctype,'Sales Invoice');self.assertEqual(self.docs_created,['Sales Invoice'])
        self.assertEqual(self.case.credit_document_doctype,'Sales Invoice');self.assertEqual(self.case.accounting_sales_invoice,doc.name)
    def test_no_optional_app_rejects_custom_without_creating_invoice_but_default_works(self):
        self.installed=False
        with self.assertRaisesRegex(ValueError,'not installed'):self.create()
        self.assertFalse(self.docs_created);self.create(False)
    def test_optional_schema_and_permissions_are_checked(self):
        self.meta['Credit Note'].fields[:] = [r for r in self.meta['Credit Note'].fields if r.fieldname!='cfg_return_case']
        with self.assertRaisesRegex(ValueError,'traceability'):self.create()
        self.setUp();self.permissions[('Credit Note','create')]=False
        with self.assertRaises(PermissionError):self.create()
        self.assertFalse(self.docs_created)
    def test_custom_adapter_does_not_copy_source_identity_or_series(self):
        template=self.map_return('Sales Invoice','ORIGINAL');template.name='STALE';template.docstatus=1
        template.naming_series='INV-';template.amended_from='OLD-INVOICE'
        target=self.adapter.build_draft(template)
        self.assertIsNone(target.name);self.assertEqual(target.naming_series,'CN-');self.assertEqual(target.docstatus,0)
        self.assertFalse(target.amended_from)
    def test_api_captures_checkbox_and_returns_dynamic_doctype_and_reuses_original(self):
        result=self.decision();again=self.decision()
        self.assertEqual(result['credit_document_doctype'],'Credit Note');self.assertEqual(again['credit_document'],result['credit_document'])
        self.assertEqual(self.docs_created.count('Credit Note'),1)
        command=next(iter(self.data['CFG ERP Command'].values()))
        self.assertEqual(command.target_doctype,'Credit Note');self.assertEqual(json.loads(command.request_payload)['credit_document_doctype'],'Credit Note')
    def test_api_default_checkbox_is_sales_invoice(self):
        self.decision(0);self.assertEqual(self.case.credit_document_doctype,'Sales Invoice')
    def test_active_custom_cannot_be_replaced_by_unchecked_or_no_credit(self):
        self.create()
        with self.assertRaisesRegex(ValueError,'another DocType'):self.decision(0)
        with self.assertRaisesRegex(ValueError,'existing credit'):self.decision(0,'No Credit')
        self.assertEqual(self.docs_created,['Credit Note'])
    def test_no_credit_rejects_custom_option_and_requires_no_sales_invoice(self):
        with self.assertRaisesRegex(ValueError,'No Credit'):self.decision(1,'No Credit')
        self.assertFalse(self.docs_created)
    def test_failed_command_does_not_silently_change_target(self):
        self.insert_once(Doc(doctype='CFG ERP Command',status='Failed',request_payload=json.dumps({'credit_document_doctype':'Sales Invoice'})),
                         'customer-credit-return|CASE|0')
        with self.assertRaisesRegex(ValueError,'another credit DocType'):self.decision()
        self.assertFalse('Credit Note' in self.docs_created)
    def test_custom_submit_tracks_native_draft_without_completing_accounting(self):
        note=self.create();self.adapter.before_submit(note);note.docstatus=1;invoice=self.make_invoice(note)
        self.adapter.on_submit(note)
        self.assertEqual(invoice.cfg_return_case,'CASE');self.assertEqual(invoice.return_against_credit_note,note.name)
        self.assertEqual(self.case.credit_document,note.name);self.assertEqual(self.case.credit_document_doctype,'Credit Note')
        self.assertEqual(self.case.credit_document_status,'Submitted');self.assertEqual(self.case.accounting_status,'Credit Pending')
        self.assertEqual(self.case.accounting_sales_invoice,invoice.name);self.assertEqual(self.case.accounting_sales_invoice_status,'Draft')
    def test_native_posting_completes_case_and_retains_custom_note_reference(self):
        note=self.create();note.docstatus=1;invoice=self.make_invoice(note);self.adapter.on_submit(note)
        invoice.docstatus=1;self.feedback.on_submit(invoice)
        self.assertEqual(self.case.accounting_status,'Completed');self.assertEqual(self.case.state,'Accounting Completed')
        self.assertEqual(self.case.credit_document,note.name);self.assertEqual(self.case.accounting_sales_invoice_status,'Submitted')
        self.case.disposition_status='Completed';self.case.accounting_status='Credit Pending';self.feedback.on_submit(invoice)
        self.assertEqual(self.case.state,'Closed')
    def test_quantity_uom_company_and_source_tampering_reject_before_custom_submit(self):
        for field,value in [('company','WRONG'),('return_against','WRONG')]:
            note=self.create();old=note.get(field);note[field]=value
            with self.assertRaises(ValueError):self.adapter.before_submit(note)
            note[field]=old
        note.items[0].stock_qty=-3
        with self.assertRaisesRegex(ValueError,'conversion'):self.adapter.before_submit(note)
        note.items[0].stock_qty=-2;note.items[0].stock_uom='Nos'
        with self.assertRaisesRegex(ValueError,'UOM'):self.adapter.before_submit(note)
    def test_custom_cancel_blocks_active_native_draft_and_submitted_invoice(self):
        note=self.create();note.docstatus=1;invoice=self.make_invoice(note);self.adapter.on_submit(note)
        for status in (0,1):
            invoice.docstatus=status
            with self.assertRaisesRegex(ValueError,'linked submitted'):self.adapter.before_cancel(note)
    def test_native_cancel_keeps_custom_active_until_custom_is_cancelled(self):
        note=self.create();note.docstatus=1;invoice=self.make_invoice(note);self.adapter.on_submit(note)
        invoice.docstatus=1;self.feedback.on_submit(invoice);invoice.docstatus=2;self.feedback.on_cancel(invoice)
        self.assertEqual(self.case.credit_document_doctype,'Credit Note');self.assertEqual(self.case.credit_document,note.name)
        self.assertEqual(self.case.accounting_status,'Credit Pending');self.assertEqual(self.case.accounting_revision,0)
        self.adapter.before_cancel(note);note.docstatus=2;self.adapter.on_cancel(note)
        self.assertEqual(self.case.credit_document_status,'Cancelled');self.assertEqual(self.case.accounting_revision,1)
        self.assertEqual(self.case.accounting_status,'Source Selected')
    def test_deleted_generated_draft_clears_case_link_and_retains_snapshot_audit(self):
        note=self.create();note.docstatus=1;invoice=self.make_invoice(note);self.adapter.on_submit(note)
        self.adapter.invoice_draft_deleted(invoice);self.data['Sales Invoice'].pop(invoice.name)
        self.assertFalse(self.case.accounting_sales_invoice);self.adapter.before_cancel(note)
        self.assertTrue(any(event[0]=='Custom Credit Invoice Draft Discarded' for event in self.events))
    def test_wrong_native_credit_note_link_and_unsubmitted_note_are_rejected(self):
        note=self.create()
        with self.assertRaisesRegex(ValueError,'Submit the approved'):self.make_invoice(note)
        note.docstatus=1;invoice=self.make_invoice(note);invoice.return_against_credit_note='WRONG'
        with self.assertRaisesRegex(ValueError,'exact approved'):self.feedback.on_submit(invoice)
    def test_uncontrolled_credit_notes_do_not_change_kanban_accounting(self):
        note=Doc(doctype='Credit Note',name='UNCONTROLLED')
        for fn in ('before_submit','on_submit','before_cancel','on_cancel'):
            getattr(self.adapter,fn)(note)
        self.assertFalse(self.events)

    def test_second_native_return_cannot_reuse_one_custom_credit_note(self):
        note=self.create();note.docstatus=1;invoice=self.make_invoice(note);self.adapter.on_submit(note)
        with self.assertRaisesRegex(ValueError,'active|another|amendment'):
            self.make_invoice(note,'SECOND')
    def test_duplicate_source_item_uom_uses_standard_return_until_custom_mapper_supports_exact_rows(self):
        self.source.items.append(Doc(self.source.items[0],name='OTHER-SOURCE-ROW',rate=99))
        with self.assertRaisesRegex(ValueError,'repeated Item/UOM'):
            self.create()
        self.assertFalse(self.docs_created)

    def test_approved_custom_availability_hides_unmigrated_or_absent_optional_app(self):
        self.assertTrue(self.adapter.available())
        self.installed=False;self.assertFalse(self.adapter.available())
    def test_controlled_native_amendment_can_replace_cancelled_accounting_invoice(self):
        note=self.create();note.docstatus=1;invoice=self.make_invoice(note);self.adapter.on_submit(note)
        invoice.docstatus=1;self.feedback.on_submit(invoice);invoice.docstatus=2;self.feedback.on_cancel(invoice)
        amended=self.new_doc('Sales Invoice');amended.update(invoice.as_dict())
        amended.meta=self.meta['Sales Invoice'];amended.name='RETURN2';amended.docstatus=0;amended.amended_from=invoice.name
        amended.set('items',[Doc(row) for row in amended.items])
        self.adapter.bind_invoice(amended);self.insert(amended);amended.docstatus=1;self.feedback.on_submit(amended)
        self.assertEqual(self.case.accounting_sales_invoice,'RETURN2');self.assertEqual(self.case.credit_document,note.name)

    def test_default_native_submit_and_cancel_keep_existing_case_lifecycle(self):
        invoice=self.create(False);invoice.docstatus=1;self.feedback.on_submit(invoice)
        self.assertEqual(self.case.accounting_status,'Completed');self.assertEqual(self.case.credit_document_doctype,'Sales Invoice')
        self.assertEqual(self.case.accounting_sales_invoice,invoice.name)
        invoice.docstatus=2;self.feedback.on_cancel(invoice)
        self.assertEqual(self.case.accounting_status,'Source Selected');self.assertEqual(self.case.accounting_revision,1)
    def test_custom_submit_rechecks_exact_source_row_and_conversion(self):
        note=self.create();note.items[0].sales_invoice_item='UNRELATED'
        with self.assertRaisesRegex(ValueError,'source row'):self.adapter.before_submit(note)
    def test_install_registers_credit_note_trace_fields_only_if_optional_doctype_exists(self):
        captured=[]
        fields_module=types.ModuleType('frappe.custom.doctype.custom_field.custom_field')
        fields_module.create_custom_fields=lambda fields,**kwargs:captured.append(fields)
        install=load('install.py',dict(frappe=self.frappe))
        install._ensure_responsibilities=Mock();install._ensure_process_certificate_inventory_dimension=Mock()
        install._ensure_logistics_audit_user_permissions=Mock()
        original=self.frappe.db.exists
        for installed in (False,True):
            self.frappe.db.exists=lambda dt,name: installed if dt=='DocType' and name=='Credit Note' else True
            with patch.dict(sys.modules,{fields_module.__name__:fields_module}):install.after_install()
            self.assertEqual('Credit Note' in captured[-1],installed)
            if installed:self.assertEqual({f['fieldname'] for f in captured[-1]['Credit Note']},{'cfg_return_case','cfg_scan_event'})
        self.frappe.db.exists=original

    def test_accounting_context_uses_configured_initial_choice(self):
        self.frappe.db.get_single_value=Mock(return_value=1)
        self.frappe.db.get_value=Mock(return_value='Kg')
        context=self.returns.get_accounting_context('CASE')
        self.assertEqual(context['default_use_custom_credit_note'],1)
        self.frappe.db.get_single_value.assert_called_with('CFG Kanban Settings','default_custom_credit_note')
        self.frappe.db.get_single_value.return_value='0'
        self.assertEqual(self.returns.get_accounting_context('CASE')['default_use_custom_credit_note'],0)

    def test_accounting_context_does_not_default_to_unavailable_or_unauthorized_custom_note(self):
        self.frappe.db.get_single_value=Mock(return_value=1)
        self.frappe.db.get_value=Mock(return_value='Kg')
        self.installed=False
        self.assertEqual(self.returns.get_accounting_context('CASE')['default_use_custom_credit_note'],0)
        self.installed=True;self.permissions[('Credit Note','create')]=False
        self.assertEqual(self.returns.get_accounting_context('CASE')['default_use_custom_credit_note'],0)
