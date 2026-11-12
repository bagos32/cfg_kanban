"""Offline printed certificate metadata/FEFO checks, not live stock acceptance."""
from datetime import date
import json
import unittest
from unittest.mock import Mock
from cfg_kanban.tests.test_material_actuals_yield import ROOT, Row, functions, frappe_double


class TestCertificatePrintIdentity(unittest.TestCase):
    def setUp(self):
        self.frappe=frappe_double();self.frappe.db.table_exists=lambda *args:True
        self.unit=Row(name='RM00005',item_code='BAG',stock_uom='Nos',process_certificate_set='SET',batch_no=None,
            expiry_date=None,current_qty=10)
        self.proof=Row(name='CERT',handling_unit='RM00005',certificate_type='PRINT',certificate_set='SET',item_code='BAG',stock_uom='Nos',
            kanban_cycle='CYCLE',status='Active',source_reference_doctype='Stock Entry',source_reference_name='REPACK')
        self.proofs=[self.proof]
        self.run=Row(name='RUN',kanban_cycle='CYCLE',item_code='BAG',stock_uom='Nos',output_handling_unit='RM00005',
            result_certificate_set='SET',printed_expiry='2027-06-01',first_output_serial='S001',last_output_serial='S010',
            repack_stock_entry='REPACK',status='Completed')
        self.runs=[self.run];self.native=Row(docstatus=1,purpose='Repack');self.progress=[];self.serials=[]
        self.frappe.get_all.side_effect=self.get_all
        self.frappe.get_doc.side_effect=lambda doctype,name:self.unit if doctype=='CFG Kanban Handling Unit' else self.proof
        self.frappe.db.get_value.side_effect=self.get_value
        self.frappe.db.exists.side_effect=lambda doctype,name:any(proof.name==name for proof in self.proofs)
        self.ns=functions('services/certificate_output_evidence.py',[
            'certificate_output_evidence','_certificate_origin','printed_expiry_dates'],{'frappe':self.frappe,'json':json})
        functions('services/logistics_stock_identity.py',['_expiry','identity_snapshot','capture_manifest_line'],self.ns)
        self.ns.update({'IDENTITY_FIELDS':('item_code','stock_uom','batch_no','expiry_date','process_certificate_set'),
            '_serials':lambda unit:[], '_json':lambda value:json.dumps(value,default=str)})
        functions('services/material_rotation.py',['material_expiry','assert_material_not_expired','validate_material_rotation'],self.ns)
        self.ns.update({'cint':lambda x:int(x or 0),'flt':lambda x:float(x or 0),
            'getdate':lambda value:value if isinstance(value,date) else date.fromisoformat(str(value)[:10]),
            'today':lambda:'2026-11-12','_':lambda value:value,'TOLERANCE':0.000001,
            'assert_process_cycle_printed_expiry':lambda *args,**kwargs:{}})

    def get_all(self,doctype,*,filters,fields=None,pluck=None,**kwargs):
        if doctype=='CFG Process Certificate':rows=self.proofs
        elif doctype=='CFG Process Certificate Run':rows=self.runs
        elif doctype=='CFG Certificate Process Progress':rows=self.progress
        else:raise AssertionError(doctype)
        selected=[row for row in rows if all(row.get(key)==value for key,value in filters.items())]
        return [row.get(pluck) for row in selected] if pluck else [Row({field:row.get(field) for field in fields}) for row in selected]

    def get_value(self,doctype,name,fields=None,**kwargs):
        if doctype=='Stock Entry':return self.native
        if doctype=='Item':return False
        if doctype=='Batch':return Row(item='BAG',disabled=0,expiry_date='2027-02-01')
        raise AssertionError((doctype,name,fields))

    def evidence(self,unit=None):
        unit=unit or self.unit
        return self.ns['certificate_output_evidence'](unit.name,unit.process_certificate_set,unit.item_code,unit.stock_uom)

    def test_manifest_captures_printed_expiry_without_inventing_serial_assignments(self):
        line=Row(handling_unit='RM00005')
        self.ns['capture_manifest_line'](line)
        snapshot=json.loads(line.stock_identity_snapshot)
        self.assertEqual(line.expiry_date,'2027-06-01')
        self.assertEqual(snapshot['serial_nos'],[])
        self.assertEqual(snapshot['certificate_output_evidence'][0]['first_output_serial'],'S001')
        self.assertEqual(line.process_certificate_set,'SET')

    def test_frozen_manifest_requires_rescan_after_printing_evidence_changes(self):
        line=Row(handling_unit='RM00005')
        self.ns['capture_manifest_line'](line)
        self.run.printed_expiry='2027-07-01'
        with self.assertRaisesRegex(ValueError,'changed after selection'):
            self.ns['capture_manifest_line'](line)

    def test_posted_no_batch_tag_exposes_captured_printed_expiry_and_serial_boundaries(self):
        result=self.evidence()
        self.assertEqual(result[0]['printed_expiry'],'2027-06-01')
        self.assertEqual(result[0]['first_output_serial'],'S001')
        self.assertEqual(result[0]['last_output_serial'],'S010')
        self.assertEqual(self.unit.expiry_date,None)

    def test_draft_cancelled_or_incomplete_postings_never_supply_expiry(self):
        for state in (0,2):
            self.native.docstatus=state;self.assertEqual(self.evidence(),[])
        self.native.docstatus=1;self.run.status='Awaiting ERP Submission'
        self.assertEqual(self.evidence(),[])

    def test_matching_certificate_set_alone_does_not_prove_printing(self):
        for field,value in (('output_handling_unit','OTHER'),('item_code','OTHER'),('kanban_cycle','OTHER'),('result_certificate_set','OTHER')):
            with self.subTest(field=field):
                old=self.run[field];self.run[field]=value;self.assertEqual(self.evidence(),[]);self.run[field]=old

    def test_split_child_follows_exact_parent_certificate_provenance(self):
        child=Row(self.proof,name='CHILD-CERT',handling_unit='CHILD',source_reference_doctype='CFG Process Certificate',source_reference_name='CERT')
        self.proofs.append(child)
        child_unit=Row(self.unit,name='CHILD',current_qty=5)
        self.assertEqual(self.evidence(child_unit)[0]['source_handling_unit'],'RM00005')
        self.assertEqual(self.evidence(child_unit)[0]['first_output_serial'],'S001')
        self.assertEqual(self.serials,[])  # An inherited boundary never invents exact child serials.

    def test_revocation_preserves_physical_print_date_and_cycles_are_rejected(self):
        child=Row(self.proof,name='CHILD-CERT',handling_unit='CHILD',source_reference_doctype='CFG Process Certificate',source_reference_name='CERT')
        self.proofs.append(child);self.proof.status='Revoked'
        self.assertEqual(self.evidence(Row(self.unit,name='CHILD'))[0]['printed_expiry'],'2027-06-01')
        self.assertIn({'name':'CERT','status':'Revoked'},self.evidence(Row(self.unit,name='CHILD'))[0]['certificate_provenance'])
        self.proof.status='Active';self.proof.source_reference_doctype='CFG Process Certificate';self.proof.source_reference_name='CERT'
        self.assertEqual(self.evidence(),[])

    def test_multiple_certificate_types_on_one_run_are_not_duplicated(self):
        self.proofs.append(Row(self.proof,name='SERIAL-CERT',certificate_type='SERIAL'))
        self.assertEqual(len(self.evidence()),1)

    def test_partial_progress_serial_episodes_remain_distinct(self):
        self.progress=[Row(name='P1',sequence=1,certificate_process_run='RUN',status='ERP Posted',printed_expiry='2027-06-01',first_output_serial='S001',last_output_serial='S005'),
                       Row(name='P2',sequence=2,certificate_process_run='RUN',status='ERP Posted',printed_expiry='2027-06-01',first_output_serial='S020',last_output_serial='S025')]
        episodes=self.evidence()[0]['progress']
        self.assertEqual([(row['first_output_serial'],row['last_output_serial']) for row in episodes],[('S001','S005'),('S020','S025')])

    def test_effective_expiry_uses_printed_date_without_replacing_earlier_stock_or_batch_date(self):
        printing=self.evidence()
        self.assertEqual(self.ns['_expiry']({'certificate_output_evidence':printing}),'2027-06-01')
        self.assertEqual(self.ns['_expiry']({'certificate_output_evidence':printing,'expiry_date':'2027-01-01'}),'2027-01-01')
        self.assertEqual(self.ns['_expiry']({'certificate_output_evidence':printing,'batch_expiry_date':'2027-02-01'}),'2027-02-01')

    def test_certificate_validity_is_not_substituted_for_printed_expiry(self):
        self.run.printed_expiry=None
        self.proof.valid_until='2027-01-01'
        self.assertEqual(self.ns['_expiry']({'certificate_output_evidence':self.evidence()}),'')

    def test_material_run_expiry_check_uses_captured_printed_date(self):
        self.assertEqual(self.ns['material_expiry'](self.unit),date(2027,6,1))
        self.run.printed_expiry='2026-11-11'
        with self.assertRaisesRegex(ValueError,'expired on'):self.ns['assert_material_not_expired'](self.unit)

    def test_fefo_compares_captured_printed_expiry_of_each_candidate(self):
        early_proof=Row(self.proof,name='EARLY-CERT',handling_unit='EARLY',kanban_cycle='EARLY-CYCLE',source_reference_name='EARLY-REPACK')
        self.proofs.append(early_proof)
        self.runs.append(Row(self.run,name='EARLY-RUN',kanban_cycle='EARLY-CYCLE',output_handling_unit='EARLY',repack_stock_entry='EARLY-REPACK',printed_expiry='2027-01-01'))
        candidates=[Row(name=name,batch_no=None,expiry_date=None,batch_expiry=None,received_on='2026-01-01',scan_code=name,effective_available=10) for name in ('RM00005','EARLY')]
        self.ns['_rotation_candidates']=lambda unit:candidates
        self.ns['active_work_order_override']=lambda *args,**kwargs:None
        with self.assertRaisesRegex(ValueError,'FEFO requires source tag EARLY first'):
            self.ns['validate_material_rotation'](Row(),self.unit)


if __name__=='__main__':unittest.main()
