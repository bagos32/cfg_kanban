"""Trip-bound collection executes the existing direct intake/QC factory offline; no site or ledger acceptance."""
import datetime,json,types,unittest
from cfg_kanban.tests import test_direct_customer_returns as direct
from cfg_kanban.tests.test_vehicle_overview import load

class TestDriverCollections(unittest.TestCase):
    def setUp(self):
        self.d=direct.TestDirectCustomerReturns();self.d.setUp();self.d.direct._returns=lambda:self.d.returns;self.d.current_read_required=False
        self.d.add('Warehouse','LORRY',company='A')
        self.profile=self.d.profile;self.session=self.d.session
        self.trip=direct.Doc(name='TRIP',doctype='CFG Kanban Delivery Trip',company='A',state='Planned',driver_route_state='In Progress',driver_route_snapshot_json=json.dumps({'vehicle':'LORRY'}))
        self.stop=direct.Doc(stop_key='STOP',customer='CUST',customer_address='CUST ADDRESS')
        self.ns=load('services/driver_collections.py',dict(frappe=self.d.frappe,json=json,intake=self.d.direct,record=self.d.record,now_datetime=lambda:datetime.datetime(2026,11,21,18)))
        self.values=dict(inspection_location='QC BAY',customer_return_reason='Old damaged goods',lines=[dict(item_code='BAG',claimed_qty=3,condition='Damaged')],reported_source_reference='Previous delivery DN-OLD')
    def preview(self):return self.ns['preview'](self.trip,self.stop,self.values,self.profile,'TOKEN')
    def collect(self,key='EVENT'):return self.ns['collect'](self.trip,self.stop,self.values,self.profile,self.session,'TOKEN',key)
    def case(self):return next(iter(self.d.data[direct.CASE].values()))
    def test_old_collection_creates_one_existing_native_qc_case_without_stock_or_credit(self):
        before=self.preview();self.assertEqual(before['lines'][0]['stock_uom'],'Nos');result=self.collect()
        case=self.case();self.assertEqual(result['return_case'],case.name);self.assertEqual(case.state,'Awaiting QC Receipt')
        self.assertEqual(case.claimed_total_qty,3);self.assertFalse(case.stock_already_owned);self.assertEqual(case.driver_trip,'TRIP')
        self.assertEqual(case.collection_vehicle_warehouse,'LORRY');self.assertEqual(case.reported_source_reference,'Previous delivery DN-OLD')
        self.assertEqual(case.collected_by,self.profile.employee)
        self.assertFalse(self.d.returns._assert_accounting_ready.__globals__['execute_command'].called)
    def test_scope_comes_from_saved_stop_not_untrusted_payload(self):
        self.values.update(company='B',customer='OTHER',customer_address=None)
        self.collect();case=self.case();self.assertEqual((case.selling_company,case.customer,case.customer_address),('A','CUST','CUST ADDRESS'))
    def test_unstarted_or_closed_office_trip_cannot_collect(self):
        for field,value in [('driver_route_state','Not Started'),('state','Closed')]:
            old=self.trip[field];self.trip[field]=value
            with self.assertRaisesRegex(ValueError,'Start the route'):self.collect()
            self.trip[field]=old
        self.assertFalse(self.d.data.get(direct.CASE))
    def test_collection_location_and_company_permissions_remain_native(self):
        self.values['inspection_location']='BAY B'
        with self.assertRaisesRegex(ValueError,'Company'):self.preview()
        self.values['inspection_location']='QC BAY';self.d.data['Company']['A']._denied=True
        with self.assertRaises(PermissionError):self.collect()
    def test_existing_temporary_note_is_collected_without_creating_another_claim(self):
        self.collect();case=self.case();case.driver_trip=None;case.driver_stop_key=None;case.collection_key=None
        case.created_by_operator='SALESPERSON';self.values={'existing_return_case':case.name}
        view=self.preview();self.assertEqual(view['existing_return_case'],case.name)
        self.collect('PICKUP');self.assertEqual(len(self.d.data[direct.CASE]),1)
        self.assertEqual(case.created_by_operator,'SALESPERSON');self.assertEqual(case.collected_by,self.profile.employee)
        result=self.d.returns.get_return_case(case.name,'TOKEN');self.assertEqual(result['name'],case.name)
        with self.assertRaisesRegex(ValueError,'already collected'):self.collect('DUPLICATE')
    def test_existing_case_cannot_cross_customer_company_or_custody(self):
        self.collect();case=self.case();case.driver_trip=None;case.collection_key=None;self.values={'existing_return_case':case.name}
        for field,value in [('customer','OTHER'),('selling_company','B'),('stock_already_owned',1),('state','QC In Progress')]:
            old=case.get(field);case[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.preview()
            case[field]=old
    def test_old_return_still_enters_existing_qc_accounting_pipeline(self):
        self.collect();case=self.case();self.profile.responsibilities.append(direct.Doc(responsibility='Customer Return QC'))
        self.d.returns.start_qc_inspection(case.name,'START','TOKEN')
        rows=[dict(name=r.name,received_qty=3,accepted_qty=3,rejected_qty=0,qc_disposition='Accept for Credit') for r in case.lines]
        self.d.returns.complete_qc_inspection(case.name,rows,'Inspected','QC','TOKEN')
        self.assertEqual(case.state,'QC Completed - Accounting Pending');self.assertEqual(case.accounting_status,'Pending Source Selection')
    def test_reported_original_reference_never_selects_accounting_source(self):
        self.values['reported_source_reference']='SI-12345';self.collect();case=self.case()
        self.assertFalse(case.accounting_sales_invoice);self.assertFalse(case.credit_document)
        self.assertFalse(case.original_delivery_note);self.assertEqual(case.reported_source_reference,'SI-12345')
    def test_existing_note_requires_native_read_even_for_same_customer(self):
        self.collect();case=self.case();case.driver_trip=None;case.collection_key=None;case._denied=True;self.values={'existing_return_case':case.name}
        with self.assertRaises(PermissionError):self.preview()

if __name__=='__main__':unittest.main()
