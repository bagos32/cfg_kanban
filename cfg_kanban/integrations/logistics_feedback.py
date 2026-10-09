import frappe
from frappe.utils import flt, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key
from cfg_kanban.services.logistics_foundation import post_quantity_event


def on_delivery_note_submit(doc, method=None):
    return_case = doc.get("cfg_return_case")
    if return_case:
        _on_correction_return_submit(doc, return_case)
        return
    delivery_session = doc.get("cfg_delivery_session")
    if delivery_session:
        _on_customer_delivery_submit(doc, delivery_session)
        return
    manifest_name = doc.get("cfg_movement_manifest")
    if not manifest_name:
        return
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    if doc.company != manifest.source_company:
        frappe.throw("Delivery Note Company does not match the Movement Manifest source Company")
    manifest.db_set({"dispatch_delivery_note": doc.name, "state": "Awaiting Receipt"},
                    update_modified=True)
    for line in manifest.lines:
        post_quantity_event(
            event_type="Location Transfer", qty=line.dispatch_qty, stock_uom=line.stock_uom,
            idempotency_key=canonical_key("manifest-dispatch-posted", manifest.name, line.name),
            source_handling_unit=line.handling_unit, item_code=line.item_code,
            batch_no=line.batch_no, source_company=manifest.source_company,
            destination_company=manifest.destination_company,
            source_warehouse=manifest.source_warehouse,
            reference_doctype="Delivery Note", reference_name=doc.name,
            reason="Submitted intercompany dispatch Delivery Note",
        )
        frappe.db.set_value("CFG Kanban Handling Unit", line.handling_unit, {
            "movement_state": "Intercompany Transit",
            "current_warehouse": None,
            "state": "Dispatched",
            "last_scan_time": now_datetime(),
        }, update_modified=False)
        frappe.db.set_value("CFG Kanban Manifest Line", line.name, "state", "In Transit",
                            update_modified=False)
    _update_manifest_containers(
        manifest, inventory_company=manifest.source_company, current_warehouse=None,
        movement_state="Intercompany Transit", state="Dispatched",
    )
    record("Intercompany Dispatch Posted", movement_manifest=manifest.name,
           previous_state="Dispatch Document Pending", new_state="Awaiting Receipt",
           qty=manifest.total_quantity, reference_doctype="Delivery Note",
           reference_name=doc.name)


def on_delivery_note_cancel(doc, method=None):
    return_case = doc.get("cfg_return_case")
    if return_case:
        _on_correction_return_cancel(doc, return_case)
        return
    delivery_session = doc.get("cfg_delivery_session")
    if delivery_session:
        _on_customer_delivery_cancel(doc, delivery_session)
        return
    manifest_name = doc.get("cfg_movement_manifest")
    if not manifest_name:
        return
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    if manifest.receipt_purchase_receipt and frappe.db.get_value(
        "Purchase Receipt", manifest.receipt_purchase_receipt, "docstatus"
    ) == 1:
        frappe.throw(
            "Cannot cancel dispatch Delivery Note after the destination Purchase Receipt is submitted"
        )
    for line in manifest.lines:
        unit = frappe.get_doc("CFG Kanban Handling Unit", line.handling_unit)
        if unit.reserved_qty:
            post_quantity_event(
                event_type="Unreserve", qty=min(line.dispatch_qty, unit.reserved_qty),
                stock_uom=line.stock_uom,
                idempotency_key=canonical_key("manifest-dispatch-cancel-unreserve",
                                              manifest.name, line.name),
                source_handling_unit=line.handling_unit, item_code=line.item_code,
                batch_no=line.batch_no, source_company=manifest.source_company,
                source_warehouse=manifest.source_warehouse,
                reference_doctype="Delivery Note", reference_name=doc.name,
                reason="Intercompany dispatch Delivery Note cancelled",
            )
        frappe.db.set_value("CFG Kanban Handling Unit", line.handling_unit, {
            "inventory_company": manifest.source_company,
            "current_warehouse": manifest.source_warehouse,
            "movement_state": "Packed",
            "state": "Attached",
        }, update_modified=False)
        frappe.db.set_value("CFG Kanban Manifest Line", line.name, "state", "Exception",
                            update_modified=False)
    _update_manifest_containers(
        manifest, inventory_company=manifest.source_company,
        current_warehouse=manifest.source_warehouse, movement_state="Packed", state="Attached",
    )
    _raise_manifest_exception(
        manifest, "Dispatch Delivery Note Cancelled",
        f"Delivery Note {doc.name} was cancelled; source stock was restored and supervisor review is required",
        "Delivery Note", doc.name,
    )


def on_purchase_receipt_submit(doc, method=None):
    manifest_name = doc.get("cfg_movement_manifest")
    if not manifest_name:
        return
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    if doc.company != manifest.destination_company:
        frappe.throw("Purchase Receipt Company does not match the Manifest destination Company")
    if not manifest.dispatch_delivery_note or frappe.db.get_value(
        "Delivery Note", manifest.dispatch_delivery_note, "docstatus"
    ) != 1:
        frappe.throw("The source Delivery Note must remain submitted before receiving the Manifest")
    for line in manifest.lines:
        unit = frappe.get_doc("CFG Kanban Handling Unit", line.handling_unit)
        if unit.reserved_qty:
            post_quantity_event(
                event_type="Unreserve", qty=min(line.dispatch_qty, unit.reserved_qty),
                stock_uom=line.stock_uom,
                idempotency_key=canonical_key("manifest-receipt-unreserve", manifest.name, line.name),
                source_handling_unit=line.handling_unit, item_code=line.item_code,
                batch_no=line.batch_no, source_company=manifest.source_company,
                destination_company=manifest.destination_company,
                destination_warehouse=manifest.destination_warehouse,
                reference_doctype="Purchase Receipt", reference_name=doc.name,
                reason="Destination Purchase Receipt submitted",
            )
        post_quantity_event(
            event_type="Location Transfer", qty=line.dispatch_qty, stock_uom=line.stock_uom,
            idempotency_key=canonical_key("manifest-receipt-posted", manifest.name, line.name),
            source_handling_unit=line.handling_unit, item_code=line.item_code,
            batch_no=line.batch_no, source_company=manifest.source_company,
            destination_company=manifest.destination_company,
            destination_warehouse=manifest.destination_warehouse,
            reference_doctype="Purchase Receipt", reference_name=doc.name,
            reason="Submitted destination Purchase Receipt",
        )
        frappe.db.set_value("CFG Kanban Handling Unit", line.handling_unit, {
            "inventory_company": manifest.destination_company,
            "current_warehouse": manifest.destination_warehouse,
            "movement_state": "Received",
            "state": "Received",
            "last_scan_time": now_datetime(),
        }, update_modified=False)
        frappe.db.set_value("CFG Kanban Manifest Line", line.name, {
            "state": "Received", "received_qty": line.dispatch_qty,
        }, update_modified=False)
    _update_manifest_containers(
        manifest, inventory_company=manifest.destination_company,
        current_warehouse=manifest.destination_warehouse, movement_state="Received",
        state="Received",
    )
    manifest.db_set({"receipt_purchase_receipt": doc.name, "state": "Received",
                     "total_received_quantity": manifest.total_quantity}, update_modified=True)
    if manifest.dispatch_delivery_note:
        frappe.db.set_value("Delivery Note", manifest.dispatch_delivery_note,
                            "cfg_counterpart_document", doc.name, update_modified=False)
    record("Intercompany Receipt Posted", movement_manifest=manifest.name,
           previous_state="Receipt Document Pending", new_state="Received",
           qty=manifest.total_quantity, reference_doctype="Purchase Receipt",
           reference_name=doc.name)


def on_purchase_receipt_cancel(doc, method=None):
    manifest_name = doc.get("cfg_movement_manifest")
    if not manifest_name:
        return
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", manifest_name)
    for line in manifest.lines:
        unit = frappe.get_doc("CFG Kanban Handling Unit", line.handling_unit)
        if not unit.reserved_qty:
            post_quantity_event(
                event_type="Reserve", qty=line.dispatch_qty, stock_uom=line.stock_uom,
                idempotency_key=canonical_key("manifest-receipt-cancel-reserve",
                                              manifest.name, line.name),
                source_handling_unit=line.handling_unit, item_code=line.item_code,
                batch_no=line.batch_no, source_company=manifest.source_company,
                destination_company=manifest.destination_company,
                reference_doctype="Purchase Receipt", reference_name=doc.name,
                reason="Destination Purchase Receipt cancelled; stock returned to transit control",
            )
        frappe.db.set_value("CFG Kanban Handling Unit", line.handling_unit, {
            "inventory_company": manifest.source_company,
            "current_warehouse": None,
            "movement_state": "Intercompany Transit",
            "state": "Dispatched",
        }, update_modified=False)
        frappe.db.set_value("CFG Kanban Manifest Line", line.name, {
            "state": "Exception", "received_qty": 0,
        }, update_modified=False)
    _update_manifest_containers(
        manifest, inventory_company=manifest.source_company, current_warehouse=None,
        movement_state="Intercompany Transit", state="Dispatched",
    )
    _raise_manifest_exception(
        manifest, "Receipt Purchase Receipt Cancelled",
        f"Purchase Receipt {doc.name} was cancelled; tags returned to transit control",
        "Purchase Receipt", doc.name,
    )


def validate_internal_stock_entry(doc):
    """Protect the immutable movement plan behind a Kanban-controlled Stock Entry."""
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", doc.cfg_movement_manifest)
    if manifest.manifest_type != "Internal Warehouse Transfer":
        frappe.throw("A Movement Manifest Stock Entry requires an Internal Warehouse Transfer route")
    if doc.company != manifest.source_company or manifest.source_company != manifest.destination_company:
        frappe.throw("Internal transfer Stock Entry Company does not match the Manifest")
    stage = doc.get("cfg_transfer_stage")
    allowed_stages = ({"Outward", "Receipt"}
                      if manifest.internal_transfer_mode == "Goods in Transit"
                      else {"Direct"})
    if stage not in allowed_stages:
        frappe.throw(
            "Internal transfer stage must remain " + " or ".join(sorted(allowed_stages))
        )
    if stage == "Receipt" and (
        not manifest.dispatch_stock_entry
        or frappe.db.get_value("Stock Entry", manifest.dispatch_stock_entry, "docstatus") != 1
    ):
        frappe.throw("Receipt requires its submitted outward Stock Entry")
    expected_source = manifest.transit_warehouse if stage == "Receipt" else manifest.source_warehouse
    expected_destination = (
        manifest.destination_warehouse if stage in ("Direct", "Receipt")
        else manifest.transit_warehouse
    )
    manifest_rows = {row.name: row for row in manifest.lines}
    if len(doc.items) != len(manifest_rows):
        frappe.throw("Stock Entry rows must match the controlled Movement Manifest")
    seen = set()
    for item in doc.items:
        line = manifest_rows.get(item.get("cfg_manifest_line"))
        if not line or line.name in seen:
            frappe.throw("Stock Entry contains an item outside the controlled Movement Manifest")
        seen.add(line.name)
        if (item.item_code != line.item_code
                or item.s_warehouse != expected_source
                or item.t_warehouse != expected_destination
                or abs(flt(item.transfer_qty or item.qty) - flt(line.dispatch_qty)) > 0.000001
                or (item.batch_no or None) != (line.batch_no or None)):
            frappe.throw(f"Stock Entry row for {line.item_code} no longer matches the Manifest")
        if stage == "Receipt":
            outward_detail = frappe.db.get_value(
                "Stock Entry Detail",
                {"parent": manifest.dispatch_stock_entry, "cfg_manifest_line": line.name},
                "name",
            )
            if (item.against_stock_entry != manifest.dispatch_stock_entry
                    or item.ste_detail != outward_detail):
                frappe.throw(
                    f"Receipt row for {line.item_code} must remain linked to its outward Stock Entry row"
                )


def on_internal_stock_entry_submit(doc):
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", doc.cfg_movement_manifest)
    stage = doc.cfg_transfer_stage
    validate_internal_stock_entry(doc)
    if stage == "Direct":
        _post_internal_direct(manifest, doc)
    elif stage == "Outward":
        _post_internal_outward(manifest, doc)
    elif stage == "Receipt":
        _post_internal_receipt(manifest, doc)
    else:
        frappe.throw(f"Unsupported internal transfer stage {stage}")


def on_internal_stock_entry_cancel(doc):
    manifest = frappe.get_doc("CFG Kanban Movement Manifest", doc.cfg_movement_manifest)
    frappe.throw(
        f"Stock Entry {doc.name} is controlled by Movement Manifest {manifest.name}. "
        "Use the Kanban controlled recovery workflow instead of cancelling it directly."
    )


def _post_internal_direct(manifest, doc):
    for line in manifest.lines:
        _unreserve_manifest_line(manifest, line, doc, "direct")
        _post_tag_location(manifest, line, doc, manifest.source_warehouse,
                           manifest.destination_warehouse, "internal-direct")
        _finish_internal_line(line, manifest.destination_warehouse)
    _update_manifest_containers(
        manifest, inventory_company=manifest.destination_company,
        current_warehouse=manifest.destination_warehouse, movement_state="Received",
        state="Received",
    )
    manifest.db_set({
        "dispatch_stock_entry": doc.name, "state": "Received",
        "total_received_quantity": manifest.total_quantity,
    }, update_modified=True)
    if manifest.kanban_cycle:
        frappe.db.set_value("CFG Kanban Cycle", manifest.kanban_cycle, {
            "transfer_dispatch_stock_entry": doc.name,
            "transfer_receipt_stock_entry": doc.name,
        }, update_modified=False)
    from cfg_kanban.services.internal_transfer import complete_transfer_cycle
    complete_transfer_cycle(manifest, "Stock Entry", doc.name)
    record("Internal Transfer Posted", movement_manifest=manifest.name,
           previous_state="Dispatch Document Pending", new_state="Received",
           qty=manifest.total_quantity, reference_doctype="Stock Entry", reference_name=doc.name)


def _post_internal_outward(manifest, doc):
    for line in manifest.lines:
        _post_tag_location(manifest, line, doc, manifest.source_warehouse,
                           manifest.transit_warehouse, "internal-outward")
        if line.handling_unit:
            frappe.db.set_value("CFG Kanban Handling Unit", line.handling_unit, {
                "current_warehouse": manifest.transit_warehouse,
                "movement_state": "Internal Transit", "state": "Dispatched",
                "last_scan_time": now_datetime(),
            }, update_modified=False)
        frappe.db.set_value("CFG Kanban Manifest Line", line.name, "state", "In Transit",
                            update_modified=False)
    _update_manifest_containers(
        manifest, current_warehouse=manifest.transit_warehouse,
        movement_state="Internal Transit", state="Dispatched",
    )
    manifest.db_set({"dispatch_stock_entry": doc.name, "state": "Awaiting Receipt"},
                    update_modified=True)
    from cfg_kanban.services.internal_transfer import mark_transfer_in_transit
    mark_transfer_in_transit(manifest, doc)
    record("Internal Transfer Outward Posted", movement_manifest=manifest.name,
           previous_state="Dispatch Document Pending", new_state="Awaiting Receipt",
           qty=manifest.total_quantity, reference_doctype="Stock Entry", reference_name=doc.name)


def _post_internal_receipt(manifest, doc):
    if not manifest.dispatch_stock_entry or frappe.db.get_value(
        "Stock Entry", manifest.dispatch_stock_entry, "docstatus"
    ) != 1:
        frappe.throw("The outward transit Stock Entry must remain submitted")
    for line in manifest.lines:
        _unreserve_manifest_line(manifest, line, doc, "receipt")
        _post_tag_location(manifest, line, doc, manifest.transit_warehouse,
                           manifest.destination_warehouse, "internal-receipt")
        _finish_internal_line(line, manifest.destination_warehouse)
    _update_manifest_containers(
        manifest, current_warehouse=manifest.destination_warehouse,
        movement_state="Received", state="Received",
    )
    manifest.db_set({
        "receipt_stock_entry": doc.name, "state": "Received",
        "total_received_quantity": manifest.total_quantity,
    }, update_modified=True)
    if manifest.kanban_cycle:
        frappe.db.set_value("CFG Kanban Cycle", manifest.kanban_cycle,
                            "transfer_receipt_stock_entry", doc.name, update_modified=False)
    from cfg_kanban.services.internal_transfer import complete_transfer_cycle
    complete_transfer_cycle(manifest, "Stock Entry", doc.name)
    record("Internal Transfer Receipt Posted", movement_manifest=manifest.name,
           previous_state="Receipt Document Pending", new_state="Received",
           qty=manifest.total_quantity, reference_doctype="Stock Entry", reference_name=doc.name)


def _unreserve_manifest_line(manifest, line, doc, suffix):
    if not line.handling_unit:
        return
    unit = frappe.get_doc("CFG Kanban Handling Unit", line.handling_unit)
    if not flt(unit.reserved_qty):
        return
    post_quantity_event(
        event_type="Unreserve", qty=min(flt(line.dispatch_qty), flt(unit.reserved_qty)),
        stock_uom=line.stock_uom,
        idempotency_key=canonical_key("manifest-internal-unreserve", suffix,
                                      manifest.name, line.name),
        source_handling_unit=line.handling_unit, item_code=line.item_code,
        batch_no=line.batch_no, source_company=manifest.source_company,
        source_warehouse=unit.current_warehouse,
        reference_doctype="Stock Entry", reference_name=doc.name,
        reason="Submitted internal Material Transfer",
    )


def _post_tag_location(manifest, line, doc, source, destination, suffix):
    if not line.handling_unit:
        return
    post_quantity_event(
        event_type="Location Transfer", qty=line.dispatch_qty, stock_uom=line.stock_uom,
        idempotency_key=canonical_key("manifest-internal-location", suffix,
                                      manifest.name, line.name),
        source_handling_unit=line.handling_unit, item_code=line.item_code,
        batch_no=line.batch_no, source_company=manifest.source_company,
        destination_company=manifest.destination_company, source_warehouse=source,
        destination_warehouse=destination,
        reference_doctype="Stock Entry", reference_name=doc.name,
        reason="Submitted internal Material Transfer",
    )


def _finish_internal_line(line, destination_warehouse):
    if line.handling_unit:
        frappe.db.set_value("CFG Kanban Handling Unit", line.handling_unit, {
            "current_warehouse": destination_warehouse,
            "movement_state": "Received", "state": "Received",
            "last_scan_time": now_datetime(),
        }, update_modified=False)
    frappe.db.set_value("CFG Kanban Manifest Line", line.name, {
        "state": "Received", "received_qty": line.dispatch_qty,
    }, update_modified=False)


def _raise_manifest_exception(manifest, exception_type, message, reference_doctype,
                              reference_name):
    exception = frappe.get_doc({
        "doctype": "CFG Kanban Exception",
        "exception_type": exception_type,
        "severity": "Critical",
        "status": "Open",
        "movement_manifest": manifest.name,
        "message": message,
        "reference_doctype": reference_doctype,
        "reference_name": reference_name,
        "raised_on": now_datetime(),
    }).insert(ignore_permissions=True)
    manifest.db_set({"state": "Exception", "exception": exception.name}, update_modified=True)
    return exception


def _update_manifest_containers(manifest, **values):
    values["last_scan_time"] = now_datetime()
    container_names = {
        line.container_handling_unit for line in manifest.lines if line.container_handling_unit
    }
    for container_name in container_names:
        frappe.db.set_value(
            "CFG Kanban Handling Unit", container_name, values, update_modified=False
        )


def _on_correction_return_submit(doc, return_case):
    case = frappe.get_doc("CFG Kanban Return Case", return_case)
    previous_state = case.state
    if case.return_flow != "Delivery Note Correction" or doc.return_against != case.original_delivery_note:
        frappe.throw("Return Delivery Note does not match its controlled correction case")
    by_source_row = {row.original_delivery_note_item: row for row in case.lines}
    seen = set()
    for item in doc.items:
        line = by_source_row.get(item.dn_detail)
        if not line or item.dn_detail in seen:
            frappe.throw("Return Delivery Note contains a row outside the correction case")
        seen.add(item.dn_detail)
        expected = flt(line.claimed_qty)
        if abs(abs(flt(item.stock_qty or item.qty)) - expected) > 0.000001:
            frappe.throw(f"Return quantity for {line.item_code} must remain {expected}")
        post_quantity_event(
            event_type="Customer Return", qty=expected, stock_uom=line.stock_uom,
            idempotency_key=canonical_key("delivery-correction-posted", case.name, line.name),
            destination_handling_unit=line.original_handling_unit,
            item_code=line.item_code, batch_no=line.batch_no,
            destination_company=case.selling_company,
            destination_warehouse=case.correction_return_warehouse,
            reference_doctype="Delivery Note", reference_name=doc.name,
            operator=case.created_by_operator, operator_session=case.created_operator_session,
            reason="Submitted wrong-Delivery-Note stock correction",
        )
        frappe.db.set_value("CFG Kanban Handling Unit", line.original_handling_unit, {
            "identity_state": "Active", "movement_state": "Returned",
            "current_warehouse": case.correction_return_warehouse,
            "state": "Attached", "last_scan_time": now_datetime(),
        }, update_modified=False)
    if seen != set(by_source_row):
        frappe.throw("Return Delivery Note must retain every controlled correction row")
    case.db_set({
        "state": "Delivery Correction Posted", "correction_return_delivery_note": doc.name,
        "correction_document_status": "Submitted",
    }, update_modified=True)
    record(
        "Delivery Note Correction Posted", return_case=case.name,
        delivery_session=case.original_delivery_session,
        previous_state=previous_state, new_state="Delivery Correction Posted",
        qty=case.claimed_total_qty, reference_doctype="Delivery Note", reference_name=doc.name,
    )


def _on_correction_return_cancel(doc, return_case):
    case = frappe.get_doc("CFG Kanban Return Case", return_case)
    for line in case.lines:
        unit = frappe.get_doc("CFG Kanban Handling Unit", line.original_handling_unit)
        if unit.current_warehouse != case.correction_return_warehouse:
            frappe.throw(
                f"Cannot cancel correction after Stock Tag {unit.handling_unit_id} moved from "
                f"{case.correction_return_warehouse}"
            )
        if flt(unit.available_qty) + 0.000001 < flt(line.claimed_qty):
            frappe.throw(
                f"Cannot cancel correction after returned quantity from {unit.handling_unit_id} was used"
            )
        post_quantity_event(
            event_type="Reconcile Decrease", qty=line.claimed_qty, stock_uom=line.stock_uom,
            idempotency_key=canonical_key("delivery-correction-cancelled", case.name, line.name),
            source_handling_unit=line.original_handling_unit,
            item_code=line.item_code, batch_no=line.batch_no,
            source_company=case.selling_company,
            source_warehouse=case.correction_return_warehouse,
            reference_doctype="Delivery Note", reference_name=doc.name,
            reason="Cancelled wrong-Delivery-Note stock correction",
        )
        unit.reload()
        empty = flt(unit.current_qty) <= 0.000001
        unit.db_set({
            "identity_state": "Empty" if empty else "Active",
            "movement_state": "Empty" if empty else "Returned",
            "current_warehouse": None if empty else case.correction_return_warehouse,
            "state": "Dispatched" if empty else "Attached",
            "last_scan_time": now_datetime(),
        }, update_modified=False)
    case.db_set({"state": "Exception", "correction_document_status": "Cancelled"},
                update_modified=True)
    record(
        "Delivery Note Correction Cancelled", return_case=case.name,
        delivery_session=case.original_delivery_session,
        previous_state="Delivery Correction Posted", new_state="Exception",
        qty=case.claimed_total_qty, reference_doctype="Delivery Note", reference_name=doc.name,
    )


def _on_customer_delivery_submit(doc, delivery_session):
    delivery = frappe.get_doc("CFG Kanban Delivery Session", delivery_session)
    _validate_customer_delivery_header(doc, delivery)
    allocations = frappe.get_all(
        "CFG Kanban Delivery Allocation",
        filters={"delivery_session": delivery.name, "state": "Delivery Pending"},
        fields=[
            "name", "handling_unit", "visible_code", "container_handling_unit",
            "container_visible_code", "item_code", "batch_no", "stock_uom",
            "allocated_qty", "source_warehouse", "movement_state_before_reservation",
        ],
        order_by="reserved_on asc, name asc",
        limit_page_length=500,
    )
    if not allocations:
        # A repeated submit hook is harmless only when this exact document was
        # already posted through the Kanban ledger.
        already_posted = frappe.db.exists(
            "CFG Kanban Delivery Allocation",
            {"delivery_session": delivery.name, "delivery_note": doc.name, "state": "Delivered"},
        )
        if already_posted:
            return
        frappe.throw("Customer Delivery Session has no delivery-pending allocations")
    item_rows = _validate_customer_delivery_rows(doc, delivery, allocations)
    now = now_datetime()
    container_names = set()
    for allocation in allocations:
        item_row = item_rows[allocation.name]
        post_quantity_event(
            event_type="Deliver",
            qty=allocation.allocated_qty,
            stock_uom=allocation.stock_uom,
            idempotency_key=canonical_key(
                "customer-delivery-posted", delivery.name, allocation.name, doc.name
            ),
            source_handling_unit=allocation.handling_unit,
            item_code=allocation.item_code,
            batch_no=allocation.batch_no,
            source_company=delivery.selling_company,
            source_warehouse=delivery.source_warehouse,
            reference_doctype="Delivery Note",
            reference_name=doc.name,
            operator=delivery.delivery_confirmed_by,
            operator_session=delivery.delivery_operator_session,
            reason="Submitted customer Delivery Note",
            release_reserved=True,
        )
        unit = frappe.get_doc("CFG Kanban Handling Unit", allocation.handling_unit)
        empty = flt(unit.current_qty) <= 0.000001
        unit.db_set({
            "identity_state": "Empty" if empty else "Active",
            "movement_state": "Empty" if empty else (
                allocation.movement_state_before_reservation or "At Source"
            ),
            "current_warehouse": None if empty else delivery.source_warehouse,
            "state": "Dispatched" if empty else "Attached",
            "last_scan_time": now,
        }, update_modified=False)
        frappe.db.set_value(
            "CFG Kanban Delivery Allocation",
            allocation.name,
            {
                "state": "Delivered",
                "delivered_qty": allocation.allocated_qty,
                "delivery_note": doc.name,
                "delivery_note_item": item_row.name,
                "active_handling_unit_key": None,
            },
            update_modified=False,
        )
        if allocation.container_handling_unit:
            container_names.add(allocation.container_handling_unit)

    for container_name in container_names:
        _unload_customer_container(delivery, container_name, doc.name, now)
    if delivery.exception:
        _resolve_delivery_exception(
            delivery.exception, f"Delivery Note {doc.name} submitted successfully"
        )
    no_proof = delivery.proof_policy == "No Proof Required"
    delivery.db_set({
        "delivery_note": doc.name,
        "state": "Closed" if no_proof else "Delivered",
        "completed_on": now if no_proof else None,
        "proof_disposition": "No Proof Recorded" if no_proof else None,
        "proof_submitted_on": now if no_proof else None,
        "exception": None,
    }, update_modified=True)
    record(
        "Customer Delivery Posted",
        delivery_session=delivery.name,
        previous_state="ERP Document Pending",
        new_state="Closed" if no_proof else "Delivered",
        qty=sum(flt(row.allocated_qty) for row in allocations),
        reference_doctype="Delivery Note",
        reference_name=doc.name,
        notes=f"{len(allocations)} physical allocation(s) confirmed by ERPNext",
        operator=delivery.delivery_confirmed_by,
        operator_session=delivery.delivery_operator_session,
    )


def _on_customer_delivery_cancel(doc, delivery_session):
    delivery = frappe.get_doc("CFG Kanban Delivery Session", delivery_session)
    previous_delivery_state = delivery.state
    if delivery.delivery_proof and frappe.db.get_value(
        "CFG Kanban Delivery Proof", delivery.delivery_proof, "state"
    ) == "Submitted":
        frappe.throw(
            "Delivery Note cannot be cancelled after customer delivery proof was submitted. "
            "Use the controlled customer return workflow."
        )
    allocations = frappe.get_all(
        "CFG Kanban Delivery Allocation",
        filters={
            "delivery_session": delivery.name,
            "delivery_note": doc.name,
            "state": "Delivered",
        },
        fields=[
            "name", "handling_unit", "visible_code", "container_handling_unit",
            "container_visible_code", "item_code", "batch_no", "stock_uom",
            "allocated_qty", "source_warehouse", "movement_state_before_reservation",
        ],
        order_by="reserved_on asc, name asc",
        limit_page_length=500,
    )
    if not allocations:
        # ERPNext can invoke hooks again during recovery; do not duplicate the
        # quantity reversal or reservation.
        already_reversed = frappe.db.exists(
            "CFG Kanban Delivery Allocation",
            {
                "delivery_session": delivery.name,
                "delivery_note": doc.name,
                "state": "Delivery Pending",
            },
        )
        if already_reversed:
            return
        frappe.throw("Submitted customer Delivery Note has no delivered Kanban allocations")
    _assert_customer_delivery_reversal_is_safe(delivery, allocations, doc.name)
    now = now_datetime()
    container_names = set()
    for allocation in allocations:
        post_quantity_event(
            event_type="Customer Return",
            qty=allocation.allocated_qty,
            stock_uom=allocation.stock_uom,
            idempotency_key=canonical_key(
                "customer-delivery-cancel-return", delivery.name, allocation.name, doc.name
            ),
            destination_handling_unit=allocation.handling_unit,
            item_code=allocation.item_code,
            batch_no=allocation.batch_no,
            destination_company=delivery.selling_company,
            destination_warehouse=delivery.source_warehouse,
            reference_doctype="Delivery Note",
            reference_name=doc.name,
            operator=delivery.delivery_confirmed_by,
            operator_session=delivery.delivery_operator_session,
            reason="Cancelled customer Delivery Note; quantity restored to lorry control",
        )
        post_quantity_event(
            event_type="Reserve",
            qty=allocation.allocated_qty,
            stock_uom=allocation.stock_uom,
            idempotency_key=canonical_key(
                "customer-delivery-cancel-reserve", delivery.name, allocation.name, doc.name
            ),
            source_handling_unit=allocation.handling_unit,
            item_code=allocation.item_code,
            batch_no=allocation.batch_no,
            source_company=delivery.selling_company,
            source_warehouse=delivery.source_warehouse,
            reference_doctype="Delivery Note",
            reference_name=doc.name,
            operator=delivery.delivery_confirmed_by,
            operator_session=delivery.delivery_operator_session,
            reason="Cancelled customer Delivery Note; restored allocation awaiting amendment",
        )
        frappe.db.set_value(
            "CFG Kanban Handling Unit",
            allocation.handling_unit,
            {
                "identity_state": "Active",
                "movement_state": "Reserved",
                "current_warehouse": delivery.source_warehouse,
                "state": "Attached",
                "last_scan_time": now,
            },
            update_modified=False,
        )
        frappe.db.set_value(
            "CFG Kanban Delivery Allocation",
            allocation.name,
            {
                "state": "Delivery Pending",
                "delivered_qty": 0,
                "active_handling_unit_key": allocation.handling_unit,
            },
            update_modified=False,
        )
        if allocation.container_handling_unit:
            container_names.add(allocation.container_handling_unit)

    for container_name in container_names:
        _restore_customer_container(delivery, container_name, doc.name, allocations, now)
    exception = frappe.get_doc({
        "doctype": "CFG Kanban Exception",
        "exception_type": "Customer Delivery Note Cancelled",
        "severity": "Critical",
        "status": "Open",
        "delivery_session": delivery.name,
        "message": (
            f"Delivery Note {doc.name} was cancelled. ERP stock and Kanban reservations "
            "were restored; confirm the physical return before creating the amendment."
        ),
        "reference_doctype": "Delivery Note",
        "reference_name": doc.name,
        "raised_on": now,
    }).insert(ignore_permissions=True)
    delivery.db_set({
        "state": "Awaiting Confirmation",
        "completed_on": None,
        "proof_disposition": None,
        "proof_submitted_on": None,
        "delivery_revision": int(delivery.delivery_revision or 0) + 1,
        "exception": exception.name,
    }, update_modified=True)
    record(
        "Customer Delivery Note Cancelled",
        delivery_session=delivery.name,
        previous_state=previous_delivery_state,
        new_state="Awaiting Confirmation",
        qty=sum(flt(row.allocated_qty) for row in allocations),
        reference_doctype="Delivery Note",
        reference_name=doc.name,
        notes="Reservation restored; physical reversal must be verified before amendment",
        operator=delivery.delivery_confirmed_by,
        operator_session=delivery.delivery_operator_session,
    )


def _validate_customer_delivery_header(doc, delivery):
    if doc.company != delivery.selling_company:
        frappe.throw("Delivery Note Company does not match the Customer Delivery Session")
    if doc.customer != delivery.customer:
        frappe.throw("Delivery Note Customer does not match the scanned Customer Site")
    if doc.get("shipping_address_name") != delivery.customer_address:
        frappe.throw("Delivery Note Address does not match the scanned Customer Site")
    if doc.get("selling_price_list") != delivery.price_list:
        frappe.throw("Delivery Note Price List does not match the Customer Delivery Session")


def _assert_customer_delivery_reversal_is_safe(delivery, allocations, delivery_note):
    """Do not let an old DN cancellation corrupt later physical reservations."""
    for allocation in allocations:
        unit = frappe.get_doc("CFG Kanban Handling Unit", allocation.handling_unit)
        if flt(unit.reserved_qty):
            frappe.throw(
                f"Cannot cancel Delivery Note {delivery_note}: Stock Tag {allocation.visible_code} "
                "has a later active reservation. Release or complete that transaction first."
            )
        later_allocation = frappe.db.get_value(
            "CFG Kanban Delivery Allocation",
            {
                "active_handling_unit_key": allocation.handling_unit,
                "name": ["!=", allocation.name],
            },
            "delivery_session",
        )
        if later_allocation:
            frappe.throw(
                f"Cannot cancel Delivery Note {delivery_note}: Stock Tag {allocation.visible_code} "
                f"is reserved by Delivery Session {later_allocation}."
            )
    for container_name in {row.container_handling_unit for row in allocations
                           if row.container_handling_unit}:
        active_content = frappe.db.get_value(
            "CFG Kanban Container Content",
            {"container_handling_unit": container_name, "state": "Loaded"},
            "content_visible_code",
        )
        if active_content:
            container_code = frappe.db.get_value(
                "CFG Kanban Handling Unit", container_name, "handling_unit_id"
            )
            frappe.throw(
                f"Cannot cancel Delivery Note {delivery_note}: reusable container "
                f"{container_code} was reused and now contains {active_content}."
            )


def _validate_customer_delivery_rows(doc, delivery, allocations):
    rows = {}
    for row in doc.items:
        allocation_name = row.get("cfg_delivery_allocation")
        if not allocation_name:
            frappe.throw("Every controlled Delivery Note row must reference a Kanban allocation")
        if allocation_name in rows:
            frappe.throw(f"Kanban allocation {allocation_name} appears more than once")
        rows[allocation_name] = row
    expected = {row.name for row in allocations}
    if set(rows) != expected:
        frappe.throw("Delivery Note rows do not exactly match the confirmed Kanban allocations")
    for allocation in allocations:
        row = rows[allocation.name]
        if row.item_code != allocation.item_code:
            frappe.throw(f"Delivery Note item differs for Stock Tag {allocation.visible_code}")
        if (row.batch_no or None) != (allocation.batch_no or None):
            frappe.throw(f"Delivery Note batch differs for Stock Tag {allocation.visible_code}")
        if row.warehouse != delivery.source_warehouse:
            frappe.throw(f"Delivery Note warehouse differs for Stock Tag {allocation.visible_code}")
        if row.uom != allocation.stock_uom or row.stock_uom != allocation.stock_uom:
            frappe.throw(f"Delivery Note UOM differs for Stock Tag {allocation.visible_code}")
        if abs(flt(row.stock_qty) - flt(allocation.allocated_qty)) > 0.000001:
            frappe.throw(f"Delivery Note quantity differs for Stock Tag {allocation.visible_code}")
        if row.get("cfg_handling_unit") != allocation.handling_unit:
            frappe.throw(f"Delivery Note physical identity differs for Stock Tag {allocation.visible_code}")
    return rows


def _unload_customer_container(delivery, container_name, delivery_note, now):
    memberships = frappe.get_all(
        "CFG Kanban Container Content",
        filters={"container_handling_unit": container_name, "state": "Loaded"},
        pluck="name",
        limit_page_length=500,
    )
    for membership in memberships:
        frappe.db.set_value(
            "CFG Kanban Container Content",
            membership,
            {
                "state": "Unloaded",
                "unloaded_on": now,
                "unloaded_by": delivery.delivery_confirmed_by,
                "unloaded_operator_session": delivery.delivery_operator_session,
                "unload_event_key": canonical_key(
                    "customer-delivery-container-unload", membership, delivery_note
                ),
                "unload_reason": f"Customer Delivery Note {delivery_note} submitted",
            },
            update_modified=False,
        )
    frappe.db.set_value(
        "CFG Kanban Handling Unit",
        container_name,
        {"movement_state": "Empty", "last_scan_time": now},
        update_modified=False,
    )


def _restore_customer_container(delivery, container_name, delivery_note, allocations, now):
    container = frappe.get_doc("CFG Kanban Handling Unit", container_name)
    for allocation in allocations:
        if allocation.container_handling_unit != container_name:
            continue
        load_key = canonical_key(
            "customer-delivery-container-restore", delivery.name, allocation.name, delivery_note
        )
        if frappe.db.exists("CFG Kanban Container Content", {"load_event_key": load_key}):
            continue
        frappe.get_doc({
            "doctype": "CFG Kanban Container Content",
            "state": "Loaded",
            "container_handling_unit": container_name,
            "container_visible_code": container.handling_unit_id,
            "content_handling_unit": allocation.handling_unit,
            "content_visible_code": allocation.visible_code,
            "item_code": allocation.item_code,
            "batch_no": allocation.batch_no,
            "qty": allocation.allocated_qty,
            "stock_uom": allocation.stock_uom,
            "company": delivery.selling_company,
            "warehouse": delivery.source_warehouse,
            "loaded_on": now,
            "loaded_by": delivery.delivery_confirmed_by,
            "loaded_operator_session": delivery.delivery_operator_session,
            "load_event_key": load_key,
        }).insert(ignore_permissions=True)
    container.db_set({"movement_state": "Packed", "last_scan_time": now},
                     update_modified=False)


def _resolve_delivery_exception(exception_name, resolution):
    if not exception_name or not frappe.db.exists("CFG Kanban Exception", exception_name):
        return
    frappe.db.set_value(
        "CFG Kanban Exception",
        exception_name,
        {
            "status": "Resolved",
            "resolved_on": now_datetime(),
            "resolved_by": frappe.session.user,
            "resolution": resolution,
        },
        update_modified=True,
    )
