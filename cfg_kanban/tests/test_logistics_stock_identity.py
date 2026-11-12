"""Offline logistics stock-identity behavior; no live ERP/database acceptance."""
import ast
import copy
import datetime
import hashlib
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]

class Row(dict):
    __getattr__=dict.get
    __setattr__=dict.__setitem__

class TestLogisticsStockIdentity(unittest.TestCase):
    def setUp(self):
        frappe=types.ModuleType('frappe')
        frappe._dict=Row
        frappe.throw=Mock(side_effect=lambda message: (_ for _ in ()).throw(ValueError(message)))
        utils=types.ModuleType('frappe.utils')
        utils.flt=lambda value: float(value or 0)
        utils.now_datetime=lambda: datetime.datetime(2026,11,12,12)
        utils.get_datetime=lambda value: value if isinstance(value,datetime.datetime) else datetime.datetime.fromisoformat(str(value))
        idem=types.ModuleType('cfg_kanban.services.idempotency')
        idem.canonical_key=lambda *parts: hashlib.sha256(json.dumps(parts).encode()).hexdigest()
        spec=importlib.util.spec_from_file_location('logistics_identity_subject',ROOT/'services/logistics_stock_identity.py')
        self.service=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'frappe':frappe,'frappe.utils':utils,'cfg_kanban.services.idempotency':idem}):
            spec.loader.exec_module(self.service)
        self.frappe=frappe
        self.unit=Row(name='SOURCE',handling_unit_id='RAW-1',item_code='RAW',stock_uom='Kg',
            batch_no='BATCH',expiry_date='2027-01-31',packed_on='2026-10-01 10:00:00',
            process_certificate_set='SET',short_description='Sanitised raw material',
            work_order='WO-ORIGIN',current_operation='Sanitise',kanban_cycle='CYCLE',kanban_card='CARD',
            inventory_company='TEST',current_warehouse='Raw Store',current_qty=100)
        self.destination=Row(self.unit,name='DEST',handling_unit_id='RAW-2',current_qty=20)
        self.proof=Row(name='CERT-1',certificate_type='TYPE',certificate_set='SET',handling_unit='SOURCE',
            status='Active',valid_from='2026-10-01 10:00:00',valid_until='2027-01-01 10:00:00',
            issued_on='2026-10-01 10:00:00',issued_by_operator='EMP',operator_session='SESSION',
            terminal_user='terminal',certified_qty=100,inventory_company='TEST',warehouse='Raw Store',
            item_code='RAW',stock_uom='Kg',batch_no='BATCH',revision_snapshot=3,
            certificate_code_snapshot='SANITISED',certificate_name_snapshot='Sanitised R3',
            evidence_references='{"media_id":"EVIDENCE-1"}',source_reference_doctype='Stock Entry',
            source_reference_name='REPACK-1',idempotency_key='ORIGINAL')
        self.proofs={'CERT-1':self.proof}
        self.units={'SOURCE':self.unit,'DEST':self.destination}
        self.serials=['SER-2','SER-1']
        self.serial_controlled=False
        self.definition=Row(split_inheritance='Inherit to Child Tags',merge_policy='Identical Active Set Required')
        self.batch_expiry='2027-01-15'
        self.other_docs={}
        frappe.get_all=Mock(side_effect=self.get_all)
        frappe.get_doc=Mock(side_effect=self.get_doc)
        frappe.get_meta=Mock(return_value=Row(has_field=lambda field: True))
        frappe.db=Row(get_value=Mock(side_effect=self.get_value),exists=Mock(side_effect=self.exists),sql=Mock(return_value=[]))
        frappe.copy_doc=Mock(side_effect=self.copy_doc)
        self.line=Row(name='LINE-1',doctype='CFG Kanban Manifest Line',handling_unit='SOURCE',
            item_code='RAW',batch_no='BATCH',stock_uom='Kg',source_company='TEST',source_warehouse='Raw Store',
            dispatch_qty=100)

    def get_all(self,doctype,filters,fields=None,pluck=None,**kwargs):
        if doctype=='CFG Kanban Handling Unit Serial': return list(self.serials)
        def matches(row):
            for key,value in filters.items():
                if isinstance(value,list) and value[0]=='>=':
                    if row.get(key,0)<value[1]:return False
                elif row.get(key)!=value:return False
            return True
        rows=[row for row in self.proofs.values() if matches(row)]
        if pluck:return [row.get(pluck) for row in rows]
        return [Row({field:row.get(field) for field in fields}) for row in rows]

    def get_doc(self,doctype,name=None):
        if isinstance(doctype,dict):
            return Row(doctype,set_missing_values=lambda:None)
        if doctype=='CFG Kanban Handling Unit':return self.units[name]
        if doctype=='CFG Process Certificate':return self.proofs[name]
        if doctype=='CFG Process Certificate Type':return self.definition
        if doctype=='CFG Process Certificate Set':return Row(members=[Row(certificate_type='TYPE',revision_snapshot=3)])
        if doctype=='CFG Kanban Manifest Line':return self.line
        return self.other_docs[(doctype,name)]

    def get_value(self,doctype,name,fields=None,**kwargs):
        if doctype=='Item':return self.serial_controlled
        if doctype=='CFG Kanban Handling Unit':return self.units[name].get(fields)
        if doctype=='CFG Kanban Manifest Line':return 'DN-ROW'
        if doctype=='Delivery Note Item':return 'DN-1' 
        if doctype=='Batch':return self.batch_expiry
        if doctype=='Stock Entry Detail':return 'OUTWARD-ROW'
        raise AssertionError((doctype,name,fields))

    def exists(self,doctype,name):
        if doctype=='CFG Process Certificate':
            if isinstance(name,str):return name in self.proofs
            return any(all(row.get(k)==v for k,v in name.items()) for row in self.proofs.values())
        if doctype=='CFG Kanban Handling Unit':return False
        raise AssertionError((doctype,name))

    def copy_doc(self,proof):
        row=Row(copy.deepcopy(dict(proof)))
        def insert(**kwargs):
            row.name='DERIVED-'+str(len(self.proofs))
            self.proofs[row.name]=row
            return row
        row.insert=insert
        return row

    def capture(self):
        self.service.capture_manifest_line(self.line)
        return self.line

    def test_manifest_captures_certificates_batch_expiry_serials_and_production_origin(self):
        self.capture(); snapshot=json.loads(self.line.stock_identity_snapshot)
        self.assertEqual(self.line.process_certificate_set,'SET')
        self.assertEqual(self.line.expiry_date,'2027-01-15')
        self.assertEqual(snapshot['serial_nos'],['SER-1','SER-2'])
        self.assertEqual(snapshot['work_order'],'WO-ORIGIN')
        self.assertEqual(snapshot['packed_on'],'2026-10-01 10:00:00')
        self.assertEqual(snapshot['certificates'][0]['name'],'CERT-1')

    def test_internal_transfer_keeps_source_and_target_certificate_dimensions(self):
        fields=self.service.erp_identity_fields(self.capture(),'Stock Entry Detail',transfer=True)
        self.assertEqual(fields['process_certificate_set'],'SET')
        self.assertEqual(fields['to_process_certificate_set'],'SET')
        self.assertEqual(fields['serial_no'],'SER-1\nSER-2')
        self.assertEqual(fields['use_serial_batch_fields'],1)

    def test_intercompany_dispatch_and_receipt_keep_exact_certificate_identity(self):
        self.capture()
        for doctype in ('Delivery Note Item','Purchase Receipt Item'):
            fields=self.service.fields_for_manifest_reference({'manifest_line':'LINE-1',
                'handling_unit':'SOURCE','item_code':'RAW'},doctype)
            self.assertEqual(fields['process_certificate_set'],'SET')
            self.assertEqual(fields['serial_no'],'SER-1\nSER-2')

    def test_moving_same_tag_changes_location_without_rewriting_issuance_history(self):
        self.capture(); before=copy.deepcopy(dict(self.proof))
        self.unit.current_warehouse='Destination'; self.unit.inventory_company='OTHER'
        self.service.erp_identity_fields(self.line,'Purchase Receipt Item')
        self.assertEqual(self.proof,before)

    def test_metadata_changes_after_scan_are_rejected(self):
        for field,value in (('process_certificate_set','OTHER'),('expiry_date','2028-01-01'),
                             ('batch_no','OTHER'),('work_order','OTHER')):
            with self.subTest(field=field):
                self.setUp(); self.capture(); self.unit[field]=value
                with self.assertRaisesRegex(ValueError,'identity changed'):
                    self.service.erp_identity_fields(self.line,'Stock Entry Detail',True)

    def test_certificate_revocation_after_selection_requires_review(self):
        self.capture(); self.proof.status='Revoked'
        with self.assertRaisesRegex(ValueError,'identity changed'):
            self.service.erp_identity_fields(self.line,'Stock Entry Detail',True)

    def test_legacy_certified_manifest_is_not_silently_reconstructed(self):
        with self.assertRaisesRegex(ValueError,'no stock identity snapshot'):
            self.service.erp_identity_fields(self.line,'Stock Entry Detail',True)

    def test_missing_dimension_migration_blocks_certified_transfer(self):
        self.capture(); self.frappe.get_meta.return_value=Row(has_field=lambda field:field!='to_process_certificate_set')
        with self.assertRaisesRegex(ValueError,'migration'):
            self.service.erp_identity_fields(self.line,'Stock Entry Detail',True)

    def test_missing_exact_serial_assignments_cannot_trigger_native_auto_selection(self):
        self.serial_controlled=True
        with self.assertRaisesRegex(ValueError,'complete exact serial assignments'):
            self.capture()

    def test_tampered_manifest_certificate_or_expiry_is_rejected(self):
        self.capture(); self.line.expiry_date='2028-01-01'
        with self.assertRaisesRegex(ValueError,'expiry differs'):
            self.service.erp_identity_fields(self.line,'Stock Entry Detail',True)

    def test_submitted_outward_without_certificate_dimension_blocks_receipt(self):
        self.capture()
        self.other_docs[('Stock Entry Detail','OUTWARD-ROW')]=Row(process_certificate_set='SET',to_process_certificate_set=None)
        with self.assertRaisesRegex(ValueError,'outward transfer lost'):
            self.service.assert_outward_identity(self.line,'OUTWARD-ROW')

    def test_split_inherits_immutable_evidence_without_renewing_its_validity(self):
        self.service.inherit_split_certificates(self.unit,self.destination,20,'SPLIT-1')
        derived=self.proofs['DERIVED-1']
        self.assertEqual(derived.handling_unit,'DEST')
        self.assertEqual(derived.source_reference_name,'CERT-1')
        for field in ('valid_from','valid_until','issued_on','revision_snapshot','evidence_references'):
            self.assertEqual(derived[field],self.proof[field])
        self.assertEqual(derived.certified_qty,20)

    def test_split_retry_does_not_duplicate_certificates(self):
        self.service.inherit_split_certificates(self.unit,self.destination,20,'SPLIT-1')
        self.service.inherit_split_certificates(self.unit,self.destination,20,'SPLIT-1')
        self.assertEqual(len(self.proofs),2)

    def test_split_and_merge_policies_cannot_be_bypassed(self):
        self.definition.split_inheritance='Do Not Inherit'
        with self.assertRaisesRegex(ValueError,'prohibits split'):
            self.service.inherit_split_certificates(self.unit,self.destination,20,'SPLIT-1')
        self.definition.merge_policy='Block Merge'
        with self.assertRaisesRegex(ValueError,'blocks this merge'):
            self.service.assert_merge_compatible(self.unit,self.unit)

    def test_replacement_keeps_evidence_without_treating_whole_tag_replacement_as_split(self):
        self.definition.split_inheritance='Do Not Inherit'
        self.service.inherit_split_certificates(self.unit,self.destination,20,'REPLACE-1',replacement=True)
        self.assertEqual(self.proofs['DERIVED-1'].source_reference_name,'CERT-1')

    def test_expired_certificate_is_not_renewed_by_logistics_split(self):
        self.proof.valid_until='2026-01-01 00:00:00'
        self.service.inherit_split_certificates(self.unit,self.destination,20,'SPLIT-1')
        self.assertFalse(self.service.certificate_is_effective('DERIVED-1'))

    def test_revoked_ancestor_invalidates_derived_certificate(self):
        self.service.inherit_split_certificates(self.unit,self.destination,20,'SPLIT-1')
        self.assertTrue(self.service.certificate_is_effective('DERIVED-1'))
        self.proof.status='Revoked'
        self.assertFalse(self.service.certificate_is_effective('DERIVED-1'))
        self.assertFalse(self.service.certificate_is_effective('DERIVED-1',require_unexpired=False))

    def test_untagged_transfer_cannot_hide_certified_erp_balance(self):
        self.line.handling_unit=None
        self.frappe.db.sql.return_value=[('SET',)]
        with self.assertRaisesRegex(ValueError,'Certified ERP stock exists'):
            self.service.erp_identity_fields(self.line,'Stock Entry Detail',True)

    def test_missing_proof_or_insufficient_certified_quantity_cannot_create_evidence(self):
        self.proof.certified_qty=1
        with self.assertRaisesRegex(ValueError,'does not cover'):
            self.service.inherit_split_certificates(self.unit,self.destination,20,'SPLIT-1')
        self.proofs.clear()
        with self.assertRaisesRegex(ValueError,'no intact issued evidence'):
            self.service.inherit_split_certificates(self.unit,self.destination,20,'SPLIT-1')

    def test_different_certificate_sets_or_expiry_cannot_merge(self):
        for field,value in (('process_certificate_set','OTHER'),('expiry_date','2029-01-01')):
            with self.subTest(field=field):
                self.setUp(); self.destination[field]=value
                with self.assertRaisesRegex(ValueError,'different Process Certificate Sets or expiry'):
                    self.service.assert_merge_compatible(self.unit,self.destination)

    def test_same_origin_split_can_return_but_distinct_evidence_cannot_merge(self):
        self.service.inherit_split_certificates(self.unit,self.destination,20,'SPLIT-1')
        self.service.assert_merge_compatible(self.destination,self.unit)
        self.proofs['DERIVED-1'].source_reference_doctype='Stock Entry'
        with self.assertRaisesRegex(ValueError,'different evidence provenance'):
            self.service.assert_merge_compatible(self.destination,self.unit)

    def test_actual_gateway_builder_maps_both_dimensions_for_direct_outward_and_receipt(self):
        self.capture()
        source=(ROOT/'integrations/erp_gateway.py').read_text()
        tree=ast.parse(source)
        function=next(node for node in tree.body if isinstance(node,ast.FunctionDef)
                      and node.name=='build_internal_transfer_stock_entry')
        namespace={'frappe':self.frappe,'apply_required_erp_inputs':Mock()}
        exec(compile(ast.Module(body=[function],type_ignores=[]),str(ROOT/'integrations/erp_gateway.py'),'exec'),namespace)
        self.other_docs[('Stock Entry Detail','OUTWARD-ROW')]=Row(process_certificate_set='SET',to_process_certificate_set='SET')
        manifest=Row(lines=[self.line],source_warehouse='SOURCE',destination_warehouse='DEST',transit_warehouse='TRANSIT')
        with patch.dict(sys.modules,{'cfg_kanban.services.logistics_stock_identity':self.service}):
            for stage in ('Direct','Outward','Receipt'):
                result=namespace['build_internal_transfer_stock_entry'](manifest,{'stage':stage})
                self.assertEqual(result['items'][0]['process_certificate_set'],'SET')
                self.assertEqual(result['items'][0]['to_process_certificate_set'],'SET')

    def _actual_function(self, path, names, namespace):
        tree=ast.parse((ROOT/path).read_text())
        functions=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
        exec(compile(ast.Module(body=functions,type_ignores=[]),str(ROOT/path),'exec'),namespace)
        return namespace

    def test_actual_production_gate_accepts_transferred_proof_and_rejects_revoked_parent(self):
        self.service.inherit_split_certificates(self.unit,self.destination,20,'SPLIT-1')
        namespace=self._actual_function('services/production_certificates.py',['_requirement_passes'],
            {'frappe':self.frappe,'cint':lambda value:int(value or 0),
             '_member_union':lambda names:{'TYPE':3} if names else {}})
        evidence={'internal_set_names':[],'unit_names':['DEST']}
        rule=Row(certificate_type='TYPE',minimum_revision=1,require_unexpired=1)
        with patch.dict(sys.modules,{'cfg_kanban.services.logistics_stock_identity':self.service}):
            self.assertTrue(namespace['_requirement_passes'](evidence,rule))
            self.proof.status='Revoked'
            self.assertFalse(namespace['_requirement_passes'](evidence,rule))
            rule.require_unexpired=0
            self.assertFalse(namespace['_requirement_passes'](evidence,rule))

    def test_actual_certificate_process_gate_accepts_transferred_proof_and_rejects_revoked_parent(self):
        self.service.inherit_split_certificates(self.unit,self.destination,20,'SPLIT-1')
        namespace=self._actual_function('services/certificate_process.py',['_validate_certificate_requirements'],
            {'frappe':self.frappe,'cint':lambda value:int(value or 0)})
        master=Row(certificate_process_operation='Print',certificate_requirements=[Row(
            operation='Print',gate_stage='Before Operation Start',certificate_type='TYPE',
            minimum_revision=1,require_unexpired=1,requirement_group='Input',group_logic='All Required')])
        with patch.dict(sys.modules,{'cfg_kanban.services.logistics_stock_identity':self.service}):
            namespace['_validate_certificate_requirements'](master,self.destination)
            self.proof.status='Revoked'
            with self.assertRaisesRegex(ValueError,'does not satisfy Certificate gate'):
                namespace['_validate_certificate_requirements'](master,self.destination)

    def test_actual_dispatch_receipt_customer_delivery_and_withdrawal_builders_keep_dimensions(self):
        self.capture()
        namespace=self._actual_function('integrations/erp_gateway.py',[
            '_manifest_stock_identity_fields','_tag_stock_identity_fields','build_intercompany_delivery_note',
            '_intercompany_purchase_receipt_items','build_customer_delivery_note','build_withdrawal_stock_entry'],
            {'frappe':self.frappe,'now_datetime':lambda:datetime.datetime(2026,11,12),
             'apply_required_erp_inputs':Mock(),'get_required_erp_inputs':Mock(return_value=[])})
        payload={'company':'TEST','customer':'CUSTOMER','warehouse':'Raw Store','price_list':'Prices',
            'customer_address':'ADDRESS','counterpart_company':'OTHER','counterpart_document':'DN-1',
            'items':[{'manifest_line':'LINE-1','handling_unit':'SOURCE','item_code':'RAW','batch_no':'BATCH',
                      'uom':'Kg','qty':100,'rate':1,'delivery_allocation':'ALLOCATION'}]}
        with patch.dict(sys.modules,{'cfg_kanban.services.logistics_stock_identity':self.service}):
            dispatch=namespace['build_intercompany_delivery_note'](Row(name='MANIFEST'),payload)
            receipt=namespace['_intercompany_purchase_receipt_items'](payload)
            customer=namespace['build_customer_delivery_note'](Row(name='DELIVERY'),payload)
            cycle=Row(company='TEST',source_warehouse='Raw Store',withdrawal_allocations=[Row(
                name='ALLOCATION',handling_unit='SOURCE',item_code='RAW',batch_no='BATCH',stock_uom='Kg',qty=100)])
            withdrawal=namespace['build_withdrawal_stock_entry'](cycle,{})
        for row in (dispatch['items'][0],receipt[0],customer['items'][0],withdrawal['items'][0]):
            self.assertEqual(row['process_certificate_set'],'SET')
            self.assertEqual(row['serial_no'],'SER-1\nSER-2')

    def test_historical_snapshot_can_be_read_after_movement_but_its_fields_cannot_change(self):
        self.capture(); self.proof.status='Revoked'
        self.service.validate_saved_manifest_fields(self.line)
        self.line.process_certificate_set='OTHER'
        with self.assertRaisesRegex(ValueError,'Historical Manifest stock identity fields'):
            self.service.validate_saved_manifest_fields(self.line)

    def test_submit_validation_rejects_stripped_dimensions(self):
        self.capture()
        self.other_docs[('CFG Kanban Movement Manifest','MANIFEST')]=Row(lines=[self.line])
        row=Row(doctype='Stock Entry Detail',cfg_manifest_line='LINE-1',process_certificate_set='SET',
                to_process_certificate_set=None,batch_no='BATCH',serial_no='SER-1\nSER-2')
        doc=Row(doctype='Stock Entry',cfg_movement_manifest='MANIFEST',items=[row])
        # dict.items is a real method, whereas Frappe Document.items is its child table.
        values=dict(doc)
        doc=types.SimpleNamespace(**values,get=lambda key:values.get(key))
        with self.assertRaisesRegex(ValueError,'certificate dimensions'):
            self.service.validate_logistics_document(doc)



class TestLogisticsIdentityWiring(unittest.TestCase):
    def test_manifest_and_gateways_snapshot_and_preserve_controlled_identity(self):
        schema=json.loads((ROOT/'cfg_kanban/doctype/cfg_kanban_manifest_line/cfg_kanban_manifest_line.json').read_text())
        fields={field['fieldname']:field for field in schema['fields']}
        for name in ('process_certificate_set','expiry_date','stock_identity_snapshot'):
            self.assertEqual(fields[name]['read_only'],1)
        gateway=(ROOT/'integrations/erp_gateway.py').read_text()
        self.assertIn('**erp_identity_fields(row, "Stock Entry Detail", transfer=True)',gateway)
        self.assertIn('_manifest_stock_identity_fields(row, "Delivery Note Item")',gateway)
        self.assertIn('_manifest_stock_identity_fields(row, "Purchase Receipt Item")',gateway)
        self.assertIn('_tag_stock_identity_fields(row.get("handling_unit"), "Delivery Note Item")',gateway)
        hooks=(ROOT/'hooks.py').read_text()
        self.assertEqual(hooks.count('cfg_kanban.services.logistics_stock_identity.validate_logistics_document'),3)

    def test_every_existing_logistics_split_or_replacement_keeps_issued_provenance(self):
        for path in ('services/tag_to_tag_transfer.py','services/receipt_repack.py',
                     'services/logistics_quantity_bins.py','services/printing.py',
                     'cfg_kanban/doctype/cfg_kanban_handling_unit/cfg_kanban_handling_unit.py'):
            with self.subTest(path=path):
                source=(ROOT/path).read_text()
                self.assertIn('inherit_split_certificates',source)
        bins=(ROOT/'services/logistics_quantity_bins.py').read_text()
        self.assertIn('"process_certificate_set": source.get("process_certificate_set")',bins)
        self.assertIn('"packed_on": source.packed_on',bins)
        self.assertIn('assert_merge_compatible(fill, source)',bins)


if __name__=='__main__': unittest.main()
