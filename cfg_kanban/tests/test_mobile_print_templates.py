"""Render shipped Jinja bodies with explicit document doubles, without ERPNext posting."""
import json
import types
import unittest
from pathlib import Path

try:
    from jinja2.sandbox import SandboxedEnvironment
except ImportError:
    SandboxedEnvironment = None

from cfg_kanban.tests.test_mobile_printing import Doc

ROOT = Path(__file__).resolve().parents[1] / 'cfg_kanban' / 'print_format'


@unittest.skipUnless(SandboxedEnvironment, 'Jinja2 is supplied by the native Frappe runtime')
class TestMobilePrintTemplates(unittest.TestCase):
    def setUp(self):
        self.qr_values = []
        self.environment = SandboxedEnvironment(autoescape=False)
        self.environment.globals.update(
            _=lambda value:value,
            get_qr_svg=lambda value,*args:self.qr(value),
            stock_tag_print_context=lambda unit:Doc(expiry_date='2027-01-01',serial_nos=['SERIAL-1'],certificate_output_evidence=[Doc(first_output_serial='PK-001',last_output_serial='PK-010',printed_expiry='2027-01-01',progress=[])]),
            trip_stock_rows=lambda trip:[Doc(item_code='ITEM',item_name='Plastic bag',batch_no='LOT',
                expiry_date='2027-03-01',stock_uom='Nos',erp_qty=5,tag_qty=3,untagged_qty=2,
                identity_variance=False,tags=[Doc(handling_unit_id='RM1',current_qty=3,stock_uom='Nos',
                quality_state='Released',movement_state='Received',effective_expiry='2027-01-01')])],
            trip_vehicle_warehouse=lambda trip:trip.vehicle_warehouse,
            frappe=types.SimpleNamespace(utils=types.SimpleNamespace(now_datetime=lambda:'2026-11-23 12:00:00')),
        )
    def qr(self, value):
        self.qr_values.append(value)
        return 'data:image/svg+xml;base64,TEST'
    def document(self, **values):
        doc=Doc(**values)
        doc.get_formatted=lambda field,*args:str(doc.get(field) if doc.get(field) is not None else '')
        return doc
    def render(self, slug, doc):
        path=ROOT/slug/(slug+'.json')
        definition=json.loads(path.read_text())
        return self.environment.from_string(definition['html']).render(doc=doc,letter_head='<b>LETTERHEAD</b>')
    def invoice(self, **values):
        item=self.document(item_code='BAG',item_name='Plastic Bag',qty=5,stock_uom='Nos',uom='Nos',
                           rate='RM 2.00',amount='RM 10.00',batch_no='LOT',serial_no='SERIAL1\nSERIAL2')
        tax=self.document(description='SST',rate=6,included_in_print_rate=0,tax_amount='RM 0.60')
        doc=self.document(doctype='Sales Invoice',name='INV1',company='A',customer='CUSTOMER',customer_name='Shop',
            owner='driver@example.com',posting_date='2026-11-23',posting_time='12:00',items=[item],taxes=[tax],
            total='RM 10.00',net_total='RM 10.00',grand_total='RM 10.60',rounded_total='RM 10.60',
            terms='<p>PAYMENT TERMS</p>',docstatus=1,is_return=0)
        doc.flags.show_inclusive_tax_in_print=0
        doc.__dict__.update(values)
        return doc
    def test_invoice_preserves_native_formatted_totals_tax_qr_serials_and_rich_terms(self):
        doc=self.invoice(custom_einvoice_qr='/private/files/qr.png?x=1&y=2')
        html=self.render('cfg_sales_invoice_80mm',doc)
        for value in ('LETTERHEAD','INV1','BAG','RM 10.00','RM 0.60','RM 10.60','SERIAL1, SERIAL2',
                      'PAYMENT TERMS','/private/files/qr.png?x=1&amp;y=2'):
            self.assertIn(value,html)
        self.assertNotIn('DRAFT — NOT POSTED',html)
    def test_draft_and_credit_heading_use_native_document_state(self):
        html=self.render('cfg_sales_invoice_80mm',self.invoice(docstatus=0,is_return=1,return_against='SOURCE'))
        self.assertIn('DRAFT — NOT POSTED',html);self.assertIn('Credit Note',html);self.assertIn('SOURCE',html)
    def test_native_delivery_without_amounts_does_not_leak_financial_columns(self):
        html=self.render('cfg_delivery_note_80mm',self.invoice(doctype='Delivery Note',print_without_amount=1))
        self.assertIn('BAG',html);self.assertNotIn('RM 10.60',html);self.assertNotIn('RM 2.00',html)
    def test_return_note_is_custody_only_and_escapes_operator_text(self):
        line=self.document(item_code='BAG',batch_no=None,expiry_date=None,condition='Unknown',claimed_qty=2,stock_uom='Nos')
        doc=self.document(name='CASE',selling_company='A',customer='CUSTOMER',state='Awaiting QC Receipt',
            claimed_on='2026-11-23',customer_return_reason='<script>BAD</script>',lines=[line])
        html=self.render('cfg_return_note_80mm',doc)
        self.assertIn('Pending QC — not available stock',html)
        self.assertIn('&lt;script&gt;BAD&lt;/script&gt;',html);self.assertNotIn('<script>',html)
        self.assertEqual(self.qr_values,['CASE'])
    def test_custody_qr_is_distinct_from_available_stock_identity(self):
        doc=self.document(name='KRC-1',return_case='CASE',delivery_trip='TRIP',item_code='BAG',qty=2,stock_uom='Nos',
                          batch_no='LOT',expiry_date='2027-01-01',created_on='2026-11-23')
        html=self.render('cfg_return_custody_80mm',doc)
        self.assertIn('NOT A STOCK TAG OR CREDIT NOTE',html)
        self.assertIn('2027-01-01',html);self.assertEqual(self.qr_values,['CFG:RETURN-CUSTODY:KRC-1'])
    def test_stock_tag_includes_effective_printed_expiry_certificate_and_erp_serials(self):
        doc=self.document(handling_unit_id='RM1',item_code='BAG',batch_no='LOT',expiry_date=None,current_qty=2,
            stock_uom='Nos',quality_state='Hold',movement_state='Received',identity_state='Active',process_certificate_set='CERT')
        html=self.render('cfg_stock_tag_80mm',doc)
        for text in ('2027-01-01','CERT','SERIAL-1','Hold','Active','PK-001','PK-010','Source range, not an individual-unit assignment.'):
            self.assertIn(text,html)
        self.assertEqual(self.qr_values,['RM1'])
    def test_trip_list_keeps_erp_tag_and_untagged_views_distinct(self):
        doc=self.document(name='TRIP',company='A',vehicle_warehouse='LORRY')
        doc.flags.cfg_mobile_print_on='FROZEN PREPARATION TIME'
        html=self.render('cfg_trip_stock_80mm',doc)
        for value in ('FROZEN PREPARATION TIME','ERP: 5','Tagged: 3','Untagged: 2','RM1','2027-01-01','Batch expiry: 2027-03-01'):
            self.assertIn(value,html)

    def test_legacy_trip_stock_heading_uses_the_same_departure_lorry_as_rows(self):
        self.environment.globals['trip_vehicle_warehouse']=lambda doc:'RECORDED-LORRY'
        doc=self.document(name='TRIP',company='A',vehicle_warehouse=None)
        html=self.render('cfg_trip_stock_80mm',doc)
        self.assertIn('RECORDED-LORRY',html);self.assertNotIn('Lorry not assigned',html)


if __name__=='__main__':unittest.main()
