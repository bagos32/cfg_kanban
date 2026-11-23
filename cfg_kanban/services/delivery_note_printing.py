"""Native DN acknowledgement images; private bytes still travel directly from S3."""
from urllib.parse import urlencode

import frappe
from frappe.utils import cint
from werkzeug.utils import redirect

from cfg_kanban.services.idempotency import canonical_key

PROOF = 'CFG Kanban Delivery Proof'
SESSION = 'CFG Kanban Delivery Session'
IMAGE_METHOD = 'cfg_kanban.services.delivery_note_printing.signature_image'
IMAGE_TYPES = ('image/png', 'image/jpeg', 'image/webp')
IMAGE_LIMIT = 512 * 1024


def _read(doctype, name):
    doc = frappe.get_doc(doctype, name)
    doc.check_permission('read')
    return doc


def delivery_note_acknowledgement(doc):
    from cfg_kanban.services import media
    if doc.doctype != 'Delivery Note':
        frappe.throw('Acknowledgement printing requires a Delivery Note')
    note = _read('Delivery Note', doc.name)
    note.check_permission('print')
    _read('Company', note.company)
    if note.docstatus != 1 or cint(note.is_return):
        return None
    names = frappe.get_list(PROOF, filters={'delivery_note': note.name,
        'selling_company': note.company, 'customer': note.customer, 'state': 'Submitted'},
        pluck='name', limit_page_length=0)
    if not names:
        return None
    if len(names) != 1:
        frappe.throw('Delivery Note has multiple submitted proofs; reconcile its acknowledgement before printing')
    proof = _read(PROOF, names[0])
    delivery = _read(SESSION, proof.delivery_session)
    if (proof.delivery_note != note.name or proof.selling_company != note.company
            or proof.customer != note.customer or proof.state != 'Submitted'
            or delivery.delivery_note != note.name or delivery.delivery_proof != proof.name
            or delivery.selling_company != note.company or delivery.customer != note.customer
            or delivery.state != 'Closed'):
        frappe.throw('Delivery proof does not match this submitted Delivery Note', frappe.PermissionError)
    images = []
    for row in media.list_reference_media(PROOF, proof.name):
        if row.get('evidence_kind') != 'signature':
            continue
        image = media._get(row.media_id)
        if (image.reference_doctype != PROOF or image.reference_name != proof.name
                or image.media_class != 'delivery-proof-evidence' or image.status != 'available'):
            frappe.throw('Signature does not belong to this available delivery proof', frappe.PermissionError)
        if image.content_type not in IMAGE_TYPES or not 0 < cint(image.size_bytes) <= IMAGE_LIMIT:
            frappe.throw('Delivery signature must be a PNG, JPEG or WebP image up to 512 KB')
        version = canonical_key('dn-signature-image', image.media_id, image.get('version_id'),
            image.get('checksum_value'), image.size_bytes, str(image.get('confirmed_at')),
            str(image.modified))
        images.append(dict(media_id=image.media_id, version=version,
            src='/api/method/' + IMAGE_METHOD + '?' + urlencode(dict(
                delivery_note=note.name, proof_name=proof.name, media_id=image.media_id, version=version))))
    if cint(proof.signature_count) and not images:
        frappe.throw('Submitted delivery signature is unavailable; restore its evidence before printing acknowledgement')
    return dict(proof_name=proof.name, recipient_name=proof.recipient_name,
        captured_on=proof.get('captured_on') or proof.get('submitted_on'),
        disposition=proof.disposition, signatures=images)


@frappe.whitelist(methods=['GET'])
def signature_image(delivery_note, proof_name, media_id, version):
    from cfg_kanban.services import media
    note = _read('Delivery Note', delivery_note)
    context = delivery_note_acknowledgement(note)
    if not context or context['proof_name'] != proof_name or not any(
            row['media_id'] == media_id and row['version'] == version for row in context['signatures']):
        frappe.throw('Signature reference changed or is not available for this Delivery Note', frappe.PermissionError)
    # No image proxy, persistence, public S3 access or caller-supplied redirect destination.
    target = media.create_view_url(media_id, disposition='inline')['url']
    response = redirect(target, code=302)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response
