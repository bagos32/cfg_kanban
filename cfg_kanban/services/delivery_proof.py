import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from cfg_kanban.services.customer_delivery import (
    CUSTOMER_DELIVERY_RESPONSIBILITY,
    assert_delivery_access,
)
from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.media import list_reference_media
from cfg_kanban.services.operator_auth import require_operator


POLICY_DISPOSITIONS = {
    "Required": ("Attended",),
    "Optional": ("Attended", "No Proof Recorded"),
    "Unattended Delivery Allowed": ("Attended", "Unattended"),
    "No Proof Required": ("No Proof Recorded",),
}


@frappe.whitelist()
def get_or_create_delivery_proof(delivery_session, operator_session_token):
    profile, operator_session = require_operator(operator_session_token)
    _require_responsibility(profile)
    delivery = assert_delivery_access(delivery_session, profile)
    proof_name = delivery.delivery_proof or frappe.db.get_value(
        "CFG Kanban Delivery Proof", {"delivery_session": delivery.name}, "name"
    )
    if proof_name:
        return get_delivery_proof(proof_name, operator_session_token)
    if delivery.state != "Delivered":
        frappe.throw(_("Submit the ERPNext Delivery Note before recording delivery proof"))
    if delivery.proof_policy == "No Proof Required":
        frappe.throw(_("This Customer Site closes automatically without a proof record"))
    if not delivery.delivery_note or frappe.db.get_value(
        "Delivery Note", delivery.delivery_note, "docstatus"
    ) != 1:
        frappe.throw(_("The linked Delivery Note must be submitted"))

    if not proof_name:
        proof = frappe.get_doc({
            "doctype": "CFG Kanban Delivery Proof",
            "delivery_session": delivery.name,
            "delivery_note": delivery.delivery_note,
            "site_code": delivery.site_code,
            "site_name": delivery.site_name,
            "selling_company": delivery.selling_company,
            "customer": delivery.customer,
            "customer_address": delivery.customer_address,
            "source_warehouse": delivery.source_warehouse,
            "proof_policy": delivery.proof_policy,
            "require_recipient_name": delivery.require_recipient_name,
            "require_signature": delivery.require_signature,
            "require_photo": delivery.require_photo,
            "require_gps": delivery.require_gps,
            "unattended_reason_required": delivery.unattended_reason_required,
            "operator_session": operator_session.name,
        }).insert(ignore_permissions=True)
        proof_name = proof.name
        delivery.db_set("delivery_proof", proof.name, update_modified=True)
    return get_delivery_proof(proof_name, operator_session_token)


@frappe.whitelist()
def get_delivery_proof(proof_name, operator_session_token):
    profile, _session = require_operator(operator_session_token)
    _require_responsibility(profile)
    proof = frappe.get_doc("CFG Kanban Delivery Proof", proof_name)
    delivery = assert_delivery_access(proof.delivery_session, profile)
    result = proof.as_dict()
    result["allowed_dispositions"] = list(
        POLICY_DISPOSITIONS.get(proof.proof_policy, ("Attended",))
    )
    result["media"] = list_reference_media(
        proof.doctype, proof.name, permission_checked=True
    )
    result["delivery_state"] = delivery.state
    return result


@frappe.whitelist()
def submit_delivery_proof(proof_name, disposition, event_token,
                          operator_session_token, recipient_name=None,
                          unattended_reason=None, latitude=None, longitude=None,
                          location_accuracy=None, notes=None):
    profile, operator_session = require_operator(operator_session_token, "complete")
    _require_responsibility(profile)
    if not event_token:
        frappe.throw(_("A stable event token is required"))
    proof = frappe.get_doc("CFG Kanban Delivery Proof", proof_name)
    delivery = assert_delivery_access(proof.delivery_session, profile)
    if proof.state == "Submitted":
        return get_delivery_proof(proof.name, operator_session_token)
    if delivery.state != "Delivered":
        frappe.throw(_("Delivery Session must be Delivered before proof is submitted"))
    allowed = POLICY_DISPOSITIONS.get(proof.proof_policy, ("Attended",))
    if disposition not in allowed:
        frappe.throw(_("{0} is not allowed by proof policy {1}").format(
            disposition, proof.proof_policy
        ))

    media_rows = list_reference_media(proof.doctype, proof.name, permission_checked=True)
    counts = {"photo": 0, "signature": 0, "attachment": 0}
    for row in media_rows:
        kind = row.get("evidence_kind") or "attachment"
        if kind in counts:
            counts[kind] += 1

    if disposition == "Attended":
        if proof.require_recipient_name and not (recipient_name or "").strip():
            frappe.throw(_("Recipient name is required"))
        if proof.require_signature and not counts["signature"]:
            frappe.throw(_("Recipient signature is required"))
        if proof.require_photo and not counts["photo"]:
            frappe.throw(_("Delivery photograph is required"))
    elif disposition == "Unattended":
        if proof.unattended_reason_required and not (unattended_reason or "").strip():
            frappe.throw(_("Unattended delivery reason is required"))
        if proof.require_photo and not counts["photo"]:
            frappe.throw(_("Unattended delivery photograph is required"))

    lat, lng = _validate_location(latitude, longitude, proof.require_gps and
                                  disposition != "No Proof Recorded")
    submitted_on = now_datetime()
    key = canonical_key("customer-delivery-proof", proof.name, event_token)
    existing = frappe.db.get_value(
        "CFG Kanban Delivery Proof", {"idempotency_key": key}, "name"
    )
    if existing and existing != proof.name:
        frappe.throw(_("This proof submission token was already used"))
    proof.db_set({
        "state": "Submitted",
        "disposition": disposition,
        "recipient_name": (recipient_name or "").strip() or None,
        "unattended_reason": (unattended_reason or "").strip() or None,
        "latitude": lat,
        "longitude": lng,
        "location_accuracy": flt(location_accuracy) if location_accuracy not in (None, "") else None,
        "captured_on": submitted_on,
        "notes": notes,
        "photo_count": counts["photo"],
        "signature_count": counts["signature"],
        "attachment_count": counts["attachment"],
        "submitted_by_operator": profile.employee,
        "operator_session": operator_session.name,
        "submitted_on": submitted_on,
        "idempotency_key": key,
    }, update_modified=True)
    delivery.db_set({
        "state": "Closed",
        "delivery_proof": proof.name,
        "proof_disposition": disposition,
        "proof_submitted_on": submitted_on,
        "completed_on": submitted_on,
    }, update_modified=True)
    record(
        "Customer Delivery Proof Submitted",
        delivery_session=delivery.name,
        previous_state="Delivered",
        new_state="Closed",
        reference_doctype=proof.doctype,
        reference_name=proof.name,
        notes=f"{disposition}; photos={counts['photo']}; signatures={counts['signature']}",
        operator=profile.employee,
        operator_session=operator_session.name,
        terminal_user=operator_session.terminal_user,
    )
    return get_delivery_proof(proof.name, operator_session_token)


def _validate_location(latitude, longitude, required):
    if latitude in (None, "") or longitude in (None, ""):
        if required:
            frappe.throw(_("GPS location is required by this proof policy"))
        return None, None
    lat, lng = flt(latitude), flt(longitude)
    if not -90 <= lat <= 90 or not -180 <= lng <= 180:
        frappe.throw(_("Invalid proof geolocation"))
    return lat, lng


def _require_responsibility(profile):
    responsibilities = {row.responsibility for row in profile.responsibilities
                        if row.responsibility}
    can_view_all = (
        profile.kanban_role in ("Supervisor", "Development Proxy")
        and profile.get("view_all_responsibilities")
    )
    if CUSTOMER_DELIVERY_RESPONSIBILITY not in responsibilities and not can_view_all:
        frappe.throw(_("Operator is not assigned to Customer Delivery"), frappe.PermissionError)
