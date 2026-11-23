"""Proof/Company/media scope with offline records; no native PDF or S3 acceptance."""
import hashlib
import json
import sys
import types
import unittest
from urllib.parse import urlencode, urlparse, parse_qs
from unittest.mock import Mock, patch

from cfg_kanban.tests.test_mobile_printing import Doc, canonical
from cfg_kanban.tests.test_vehicle_overview import Row, load


class TestDeliveryNoteAcknowledgement(unittest.TestCase):
    def setUp(self):
        self.data = {}
        self.note = self.add('Delivery Note', 'DN', company='A', customer='C', docstatus=1, is_return=0)
        self.company = self.add('Company', 'A')
        self.proof = self.add('CFG Kanban Delivery Proof', 'PROOF', delivery_note='DN',
            selling_company='A', customer='C', state='Submitted', delivery_session='SESSION',
            recipient_name='Recipient <name>', captured_on='2026-11-23 12:00:00',
            disposition='Attended', signature_count=1)
        self.delivery = self.add('CFG Kanban Delivery Session', 'SESSION', delivery_note='DN',
            delivery_proof='PROOF', selling_company='A', customer='C', state='Closed')
        self.image = self.add('CFG Kanban Media', 'MEDIA', media_id='IMAGE',
            reference_doctype='CFG Kanban Delivery Proof', reference_name='PROOF',
            media_class='delivery-proof-evidence', status='available', content_type='image/png',
            size_bytes=100, version_id='VERSION', checksum_value='HASH', confirmed_at='CONFIRMED')
        self.rows = [Row(media_id='IMAGE', evidence_kind='signature')]
        self.media = types.ModuleType('cfg_kanban.services.media')
        self.media._get = lambda name:self.image
        self.media.list_reference_media = Mock(side_effect=lambda *a:self.rows)
        self.media.create_view_url = Mock(return_value={'url':'https://private-s3.example/signed'})
        p=patch.dict(sys.modules,{self.media.__name__:self.media});p.start();self.addCleanup(p.stop)
        self.frappe = Row(get_doc=lambda dt,name:self.data[(dt,name)], get_list=self.get_list,
            throw=lambda msg,exc=ValueError:(_ for _ in ()).throw(exc(msg)), PermissionError=PermissionError)
        self.ns = load('services/delivery_note_printing.py',dict(frappe=self.frappe,
            cint=lambda x:int(x or 0),urlencode=urlencode,canonical_key=canonical,
            redirect=lambda url,code:Row(location=url,status_code=code,headers={})))
    def add(self, dt, name, **values):
        doc=Doc(doctype=dt,name=name,**values);self.data[(dt,name)]=doc;return doc
    def get_list(self, dt, filters, pluck=None, **kwargs):
        rows=[v for (kind,name),v in self.data.items() if kind==dt and all(v.get(k)==value for k,value in filters.items())]
        return [v.get(pluck) for v in rows] if pluck else rows
    def context(self):
        return self.ns['delivery_note_acknowledgement'](self.note)
    def image_args(self):
        result=parse_qs(urlparse(self.context()['signatures'][0]['src']).query)
        return {key:value[0] for key,value in result.items()}
    def test_native_context_contains_only_stable_authorized_reference_not_signed_s3_url(self):
        context=self.context();self.assertEqual(context['recipient_name'],'Recipient <name>')
        self.assertEqual(context['proof_name'],'PROOF')
        self.assertEqual(len(context['signatures']),1)
        self.assertIn('/api/method/cfg_kanban.services.delivery_note_printing.signature_image?',context['signatures'][0]['src'])
        self.assertNotIn('private-s3',json.dumps(context));self.media.create_view_url.assert_not_called()
    def test_image_redirect_reauthorizes_and_disables_redirect_caching(self):
        args=self.image_args();response=self.ns['signature_image'](**args)
        self.assertEqual(response.status_code,302);self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertEqual(response.headers['Referrer-Policy'],'no-referrer')
        self.media.create_view_url.assert_called_once_with('IMAGE',disposition='inline')
    def test_native_note_read_print_company_proof_and_session_permissions_apply(self):
        for doc,permission in [(self.note,'read'),(self.note,'print'),(self.company,'read'),
                (self.proof,'read'),(self.delivery,'read')]:
            doc.denied={permission}
            with self.assertRaises(PermissionError):self.context()
            doc.denied=set()
        self.media.create_view_url.assert_not_called()
    def test_draft_return_and_missing_submitted_proof_do_not_invent_acknowledgement(self):
        self.note.docstatus=0;self.assertIsNone(self.context())
        self.note.docstatus=1;self.note.is_return=1;self.assertIsNone(self.context())
        self.note.is_return=0;self.proof.state='Draft';self.assertIsNone(self.context())
    def test_native_list_visibility_is_respected(self):
        self.frappe.get_list=Mock(return_value=[]);self.assertIsNone(self.context())
        self.media.list_reference_media.assert_not_called()
    def test_multiple_submitted_proofs_need_reconciliation(self):
        self.add('CFG Kanban Delivery Proof','OTHER',**{k:v for k,v in self.proof.__dict__.items() if k not in ('name','doctype')})
        with self.assertRaisesRegex(ValueError,'multiple'):self.context()
    def test_wrong_session_identity_and_company_cannot_supply_signature(self):
        for field,value in [('delivery_note','OTHER'),('delivery_proof','OTHER'),
                ('selling_company','B'),('customer','OTHER'),('state','Cancelled')]:
            original=self.delivery.get(field);setattr(self.delivery,field,value)
            with self.assertRaises(PermissionError):self.context()
            setattr(self.delivery,field,original)
    def test_foreign_archived_or_wrong_class_media_is_rejected(self):
        for field,value in [('reference_doctype','Other'),('reference_name','OTHER'),
                ('media_class','customer-return-evidence'),('status','archived')]:
            original=self.image.get(field);setattr(self.image,field,value)
            with self.assertRaises(PermissionError):self.context()
            setattr(self.image,field,original)
    def test_non_image_and_oversize_signature_cannot_be_embedded(self):
        for field,value in [('content_type','image/svg+xml'),('content_type','text/html'),
                ('size_bytes',0),('size_bytes',512*1024+1)]:
            original=self.image.get(field);setattr(self.image,field,value)
            with self.assertRaisesRegex(ValueError,'512 KB'):self.context()
            setattr(self.image,field,original)
    def test_recorded_but_unavailable_signature_fails_visibly(self):
        self.rows=[]
        with self.assertRaisesRegex(ValueError,'unavailable'):self.context()
        self.proof.signature_count=0;self.assertEqual(self.context()['signatures'],[])
    def test_old_media_version_wrong_proof_or_wrong_media_cannot_download(self):
        original=self.image_args()
        for field in ('version','proof_name','media_id'):
            args={**original,field:'OTHER'}
            with self.assertRaises(PermissionError):self.ns['signature_image'](**args)
        self.image.version_id='NEW'
        with self.assertRaises(PermissionError):self.ns['signature_image'](**original)
        self.assertNotEqual(self.image_args()['version'],original['version'])
        self.media.create_view_url.assert_not_called()
    def test_authority_is_rechecked_when_image_is_requested(self):
        args=self.image_args();self.note.denied={'print'}
        with self.assertRaises(PermissionError):self.ns['signature_image'](**args)
        self.media.create_view_url.assert_not_called()


if __name__ == '__main__':unittest.main()
