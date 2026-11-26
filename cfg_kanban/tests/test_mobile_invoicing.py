"""Real driver billing orchestration; ERPNext mapper is an explicit offline double."""
import copy
import json
import sys
import types
import unittest
from unittest.mock import Mock, patch

from cfg_kanban.tests.test_mobile_printing import Doc, canonical
from cfg_kanban.tests.test_vehicle_overview import Row, load


class TestMobileInvoicing(unittest.TestCase):
    def setUp(self):
        self.operator=Doc(employee='DRIVER',can_complete=1)
        self.session=Doc(name='SESSION',terminal_user='driver@example.com')
        self.profile=Doc(name='A',invoice_mode='Draft',invoice_operators=[])
        self.note=Doc(doctype='Delivery Note',name='DN',docstatus=1,is_return=0,company='A',customer='CUSTOMER',
            items=[Doc(name='DNROW',item_code='BAG',qty=5)])
        self.invoice=Doc(doctype='Sales Invoice',name=None,docstatus=0,is_return=0,update_stock=0,is_pos=0,company='A',customer='CUSTOMER',
            items=[Doc(name=None,item_code='BAG',qty=3,rate=2,amount=6,dn_detail='DNROW',delivery_note='DN',custom_mandatory=None)])
        self.invoice.insert=Mock(side_effect=self.insert)
        self.invoice.submit=Mock(side_effect=lambda:self.invoice.db_set('docstatus',1))
        self.permissions={'create':True,'submit':True}
        self.frappe=Row(has_permission=lambda dt,ptype:self.permissions[ptype],throw=self.throw,PermissionError=PermissionError,
            parse_json=json.loads,get_doc=Mock(),as_json=json.dumps,local=Row(),db=Row(sql=Mock(return_value=[])))
        self.ns=load('services/mobile_invoicing.py',dict(frappe=self.frappe,cint=lambda x:int(x or 0),flt=lambda x:float(x or 0),
            canonical_key=canonical,insert_once=Mock(),now_datetime=lambda:'NOW'))
        self.mapper=Mock(return_value=self.invoice)
        mapping=types.ModuleType('erpnext.stock.doctype.delivery_note.delivery_note');mapping.make_sales_invoice=self.mapper
        gateway=types.ModuleType('cfg_kanban.integrations.erp_gateway')
        self.missing=[]
        gateway.get_required_erp_inputs=lambda invoice:self.missing
        gateway.apply_required_erp_inputs=Mock(side_effect=self.apply)
        gateway.execute_command=Mock(return_value=self.invoice)
        self.gateway=gateway
        mobile=types.ModuleType('cfg_kanban.services.mobile_printing')
        mobile.delivery_note=Mock(return_value=self.note);mobile.get_profile=lambda company,**kw:self.profile
        mobile.saved_stop=lambda trip,key:Doc(stop_key=key)
        routes=types.ModuleType('cfg_kanban.services.driver_routes');routes._trip=lambda *a:Doc(name='TRIP',company='A')
        auth=types.ModuleType('cfg_kanban.services.operator_auth');auth.require_operator=Mock(return_value=(self.operator,self.session))
        self.auth=auth
        p=patch.dict(sys.modules,{m.__name__:m for m in (mapping,gateway,mobile,routes,auth)});p.start();self.addCleanup(p.stop)
    def throw(self,message,exc=ValueError):raise exc(message)
    def insert(self):self.invoice.name='NATIVE-NAMING-RULE-0001';return self.invoice
    def apply(self,invoice,values):
        for key,value in values.get('parent',{}).items():
            # The real shared helper admits only currently missing mandatory fields.
            if key=='custom_header':invoice.set(key,value)
    def command(self):return Doc(requested_by_operator='DRIVER',operator_session='SESSION',terminal_user='driver@example.com')
    def payload(self,automatic=False):return dict(trip_name='TRIP',stop_key='STOP',delivery_note='DN',profile='A',employee='DRIVER',automatic=automatic,profile_version=str(self.profile.modified))
    def execute(self,automatic=False):
        self.frappe.local.cfg_mobile_invoice_token='TOKEN'
        return self.ns['execute'](self.command(),self.payload(automatic))

    def test_customer_automatic_documents_force_draft_even_under_submission_policy(self):
        self.profile.invoice_mode='Automatic Submission'
        self.profile.invoice_operators=[Doc(employee='DRIVER')]
        self.frappe.local.cfg_mobile_invoice_token='TOKEN'
        payload=dict(self.payload(),draft_only=True)
        result=self.ns['execute'](self.command(),payload)
        self.assertEqual(result.docstatus,0)
        self.invoice.insert.assert_called_once_with()
        self.invoice.submit.assert_not_called()
        self.assertFalse(self.invoice.update_stock)

    def test_customer_draft_does_not_bypass_company_disable_native_create_or_named_operator(self):
        self.frappe.local.cfg_mobile_invoice_token='TOKEN'
        payload=dict(self.payload(),draft_only=True)
        for mode,allowed,native in [('Disabled',[],True),('Draft',[],False),('Automatic Submission',[],True)]:
            self.profile.invoice_mode=mode;self.profile.invoice_operators=allowed;self.permissions['create']=native
            with self.assertRaises((ValueError,PermissionError)):
                self.ns['execute'](self.command(),payload)
        self.mapper.assert_not_called();self.invoice.insert.assert_not_called()

    def test_draft_only_is_frozen_into_the_native_command_payload(self):
        command=Doc(name='COMMAND')
        self.ns['insert_once'].return_value=(command,True)
        self.frappe.get_doc.return_value=command
        self.profile.invoice_mode='Automatic Submission';self.profile.invoice_operators=[Doc(employee='DRIVER')]
        values=dict(delivery_note='DN',profile_version=str(self.profile.modified),invoice_mode=self.profile.invoice_mode)
        self.ns['create'](Doc(name='TRIP'),Doc(stop_key='STOP'),values,self.operator,self.session,self.profile,'KEY',draft_only=True)
        payload=json.loads(self.frappe.get_doc.call_args.args[0]['request_payload'])
        self.assertTrue(payload['draft_only']);self.assertFalse(payload['automatic'])
        self.assertEqual(payload['delivery_note'],'DN')

    def test_default_manual_command_keeps_the_legacy_payload_for_retries(self):
        command=Doc(name='COMMAND')
        self.ns['insert_once'].return_value=(command,True);self.frappe.get_doc.return_value=command
        values=dict(delivery_note='DN',profile_version=str(self.profile.modified),invoice_mode=self.profile.invoice_mode)
        self.ns['create'](Doc(name='TRIP'),Doc(stop_key='STOP'),values,self.operator,self.session,self.profile,'KEY')
        payload=json.loads(self.frappe.get_doc.call_args.args[0]['request_payload'])
        self.assertNotIn('draft_only',payload);self.assertFalse(payload['automatic'])

    def test_native_mapper_owns_remaining_quantity_and_numbering(self):
        invoice=self.ns['build'](self.note)
        self.mapper.assert_called_once_with('DN')
        self.assertEqual(invoice.items[0].qty,3)  # Submitted partial billing is handled natively.
        self.assertFalse(invoice.update_stock);self.assertFalse(invoice.is_pos)
        self.assertFalse(invoice.name);self.assertNotIn('naming_series',invoice.__dict__)
    def test_draft_is_default_and_native_insert_permissions_are_not_ignored(self):
        result=self.execute()
        self.invoice.insert.assert_called_once_with();self.invoice.submit.assert_not_called()
        self.assertEqual(result.name,'NATIVE-NAMING-RULE-0001');self.assertEqual(result.docstatus,0)
        self.assertIn('FOR UPDATE',self.frappe.db.sql.call_args.args[0])
    def test_automatic_submission_requires_named_operator_and_native_permission(self):
        self.profile.invoice_mode='Automatic Submission'
        with self.assertRaises(PermissionError):self.execute(True)
        self.profile.invoice_operators=[Doc(employee='DRIVER')];self.permissions['submit']=False
        with self.assertRaises(PermissionError):self.execute(True)
        self.permissions['submit']=True;self.execute(True)
        self.invoice.submit.assert_called_once();self.assertEqual(self.invoice.docstatus,1)
    def test_disabled_or_native_create_denied_has_no_accounting_effect(self):
        self.profile.invoice_mode='Disabled'
        with self.assertRaises(ValueError):self.execute()
        self.profile.invoice_mode='Draft';self.permissions['create']=False
        with self.assertRaises(PermissionError):self.execute()
        self.invoice.insert.assert_not_called();self.mapper.assert_not_called()
    def test_native_draft_is_reused_without_automatic_submission(self):
        self.profile.invoice_mode='Automatic Submission';self.profile.invoice_operators=[Doc(employee='DRIVER')]
        self.frappe.db.sql.return_value=[Row(parent='OFFICE-DRAFT')]
        existing=Doc(name='OFFICE-DRAFT',company='A',customer='CUSTOMER',update_stock=0)
        self.frappe.get_doc.return_value=existing
        self.assertIs(self.execute(True),existing)
        self.mapper.assert_not_called();self.invoice.insert.assert_not_called();self.invoice.submit.assert_not_called()
    def test_multiple_existing_drafts_require_accounts_reconciliation(self):
        self.frappe.db.sql.return_value=[Row(parent='DRAFT1'),Row(parent='DRAFT2')]
        with self.assertRaisesRegex(ValueError,'Multiple'):self.execute()
        self.invoice.insert.assert_not_called()
    def test_existing_draft_cannot_cross_customer_company_or_post_stock(self):
        self.frappe.db.sql.return_value=[Row(parent='DRAFT')]
        for values in [dict(company='B'),dict(customer='OTHER'),dict(update_stock=1)]:
            base=dict(company='A',customer='CUSTOMER',update_stock=0);base.update(values)
            self.frappe.get_doc.return_value=Doc(name='DRAFT',**base)
            with self.assertRaises(ValueError):self.execute()
    def test_command_requires_live_original_operator_session(self):
        with self.assertRaises(PermissionError):self.ns['execute'](self.command(),self.payload())
        self.frappe.local.cfg_mobile_invoice_token='TOKEN';command=self.command();command.operator_session='OTHER'
        with self.assertRaises(PermissionError):self.ns['execute'](command,self.payload())
        self.mapper.assert_not_called()
    def test_stale_draft_review_cannot_become_an_automatic_submission(self):
        self.profile.invoice_mode='Automatic Submission';self.profile.invoice_operators=[Doc(employee='DRIVER')]
        with self.assertRaisesRegex(ValueError,'policy changed'):
            self.ns['create'](Doc(name='TRIP'),Doc(stop_key='STOP'),
                dict(delivery_note='DN',profile_version='OLD',invoice_mode='Draft'),self.operator,self.session,self.profile,'KEY')
        self.gateway.execute_command.assert_not_called()
        self.invoice.insert.assert_not_called()
    def test_policy_change_does_not_silently_submit_an_original_draft_request(self):
        self.profile.invoice_mode='Automatic Submission';self.profile.invoice_operators=[Doc(employee='DRIVER')]
        with self.assertRaisesRegex(ValueError,'policy changed'):self.execute(False)
        self.invoice.insert.assert_not_called()
    def test_non_submitted_return_or_cross_scope_mapper_rows_reject(self):
        for field,value in [('docstatus',0),('is_return',1)]:
            before=getattr(self.note,field);setattr(self.note,field,value)
            with self.assertRaises(ValueError):self.ns['build'](self.note)
            setattr(self.note,field,before)
        for field,value in [('company','B'),('customer','OTHER')]:
            before=getattr(self.invoice,field);setattr(self.invoice,field,value)
            with self.assertRaises(ValueError):self.ns['build'](self.note)
            setattr(self.invoice,field,before)
        for field,value in [('dn_detail','OTHER'),('delivery_note','OTHER'),('qty',6),('qty',0),('item_code','OTHER')]:
            row=self.invoice.items[0];before=getattr(row,field);setattr(row,field,value)
            with self.assertRaises(ValueError):self.ns['build'](self.note)
            setattr(row,field,before)
    def test_required_custom_item_value_preserves_native_billing_references_and_quantities(self):
        self.missing=[dict(fieldname='items',fields=[dict(fieldname='custom_mandatory',reqd=1),dict(fieldname='qty',reqd=1)])]
        # Preflight has missing fields; creation input must fill only those fields.
        self.ns['build'](self.note,dict(tables={'items':[dict(custom_mandatory='OK',qty=999,dn_detail='OTHER')]}),validate_required=False)
        row=self.invoice.items[0]
        self.assertEqual((row.qty,row.dn_detail,row.delivery_note,row.custom_mandatory),(3,'DNROW','DN','OK'))
        self.assertNotIn('items',self.gateway.apply_required_erp_inputs.call_args.args[1]['tables'])
    def test_missing_accounting_defaults_require_office_setup_instead_of_driver_entry(self):
        self.missing=[dict(fieldname='debit_to',scope='parent',fieldtype='Link',options='Account')]
        with self.assertRaisesRegex(ValueError,'Office must configure'):
            self.ns['build'](self.note,dict(parent={'debit_to':'ARBITRARY'}),validate_required=False)
        self.gateway.apply_required_erp_inputs.assert_not_called()
    def test_mandatory_custom_item_editor_keeps_commercial_columns_read_only(self):
        self.missing=[dict(fieldname='items',scope='table',fields=[
            dict(fieldname='qty',reqd=1),dict(fieldname='rate',fieldtype='Currency',reqd=1),
            dict(fieldname='custom_mandatory',reqd=1)])]
        fields=self.ns['driver_required_inputs'](self.invoice)[0]['fields']
        self.assertTrue(fields[0]['read_only']);self.assertTrue(fields[1]['read_only'])
        self.assertFalse(fields[2].get('read_only'))
    def test_required_item_count_mismatch_rejects_instead_of_replacing_rows(self):
        with self.assertRaises(ValueError):self.ns['build'](self.note,dict(tables={'items':[]}),validate_required=False)
        self.assertEqual(len(self.invoice.items),1)
    def test_required_parent_fields_remain_delegated_to_native_shared_helper(self):
        result=self.ns['build'](self.note,dict(parent={'custom_header':'VALUE','update_stock':1}))
        self.assertEqual(result.custom_header,'VALUE');self.assertEqual(result.update_stock,0)


if __name__=='__main__':unittest.main()
