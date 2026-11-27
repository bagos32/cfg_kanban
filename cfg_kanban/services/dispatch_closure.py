"""Settle only a Plan's proven deliveries/returns; never count or move lorry stock.

The caller holds the route scope and Plan locks. Do not acquire Session locks here:
delivery feedback takes Session -> Plan. Closed Sessions and submitted documents
are read as evidence; the locked Plan mirrors and frozen-review gates prevent a
new visit or delivery cancellation from crossing settlement.
"""
import json

import frappe
from frappe.utils import flt, get_datetime, now_datetime

from cfg_kanban.services.events import record
from cfg_kanban.services.idempotency import canonical_key

PLAN = 'CFG Kanban Dispatch Plan'
REVIEW = 'CFG Kanban Dispatch Review'
SESSION = 'CFG Kanban Delivery Session'
ALLOCATION = 'CFG Kanban Delivery Allocation'
MANIFEST = 'CFG Kanban Movement Manifest'
SOURCE = 'CFG Kanban Dispatch Allocation'
ADOPTION = 'CFG Kanban Stock Adoption'
TAG_LEDGER = 'CFG Kanban Handling Unit Quantity Ledger'
EPSILON = 0.000001
TERMINAL = {'Completed', 'Skipped', 'Cancelled', 'Closed Incomplete'}


class ClosureEvidenceError(frappe.ValidationError):
    """Quiet during candidate discovery; reported normally at the API boundary."""


def report_blocker(error):
    if isinstance(error, ClosureEvidenceError):
        frappe.throw(str(error))


def _reviews():
    from cfg_kanban.services import dispatch_reconciliation
    return dispatch_reconciliation


def _feedback():
    from cfg_kanban.integrations import logistics_feedback
    return logistics_feedback


def _rows(doctype, filters, fields=None):
    return frappe.get_all(doctype, filters=filters, fields=fields or ['*'],
                          order_by='name asc', limit_page_length=0)


def _fail(plan, message):
    raise ClosureEvidenceError(f'{plan.name}: {message}. Use E5 Review / Reconciliation if this evidence cannot be resolved')


def _proof(plan, delivery, note):
    policy = delivery.proof_policy
    flags = ('require_recipient_name', 'require_signature', 'require_photo', 'require_gps')
    if policy == 'No Proof Required' and not any(delivery.get(key) for key in flags):
        return None
    name = delivery.delivery_proof
    if not name:
        _fail(plan, f'Delivery Session {delivery.name} is missing required proof')
    proof = frappe.get_doc('CFG Kanban Delivery Proof', name)
    if (proof.state != 'Submitted' or proof.delivery_session != delivery.name
            or proof.delivery_note != note.name or proof.selling_company != plan.company
            or proof.customer != delivery.customer or proof.proof_policy != policy):
        _fail(plan, f'Proof {name} is not submitted for Delivery Note {note.name} and its customer')
    allowed = {'Required': ('Attended',), 'Optional': ('Attended', 'No Proof Recorded'),
               'Unattended Delivery Allowed': ('Attended', 'Unattended'),
               'No Proof Required': ('No Proof Recorded',)}
    if proof.disposition not in allowed.get(policy, ()):
        _fail(plan, f'Proof {name} has an invalid disposition for {policy}')
    if proof.disposition == 'Attended':
        for flag, value in (('require_recipient_name', str(proof.recipient_name or '').strip()),
                            ('require_signature', flt(proof.signature_count)),
                            ('require_photo', flt(proof.photo_count))):
            if delivery.get(flag) and not value:
                _fail(plan, f'Proof {name} is missing {flag.replace("require_", "").replace("_", " ")}')
    if proof.disposition == 'Unattended':
        if ((delivery.get('unattended_reason_required') and not str(proof.unattended_reason or '').strip())
                or (delivery.require_photo and not flt(proof.photo_count))):
            _fail(plan, f'Proof {name} is missing unattended delivery evidence')
    if delivery.require_gps and proof.disposition != 'No Proof Recorded':
        if not proof.location_captured or not -90 <= flt(proof.latitude) <= 90 or not -180 <= flt(proof.longitude) <= 180:
            _fail(plan, f'Proof {name} is missing valid GPS evidence')
    return name


def _deliveries(plan, sources):
    documents = []
    source_map = {row.name: row for row in sources}
    delivered_by_source = {}
    total = 0
    sessions = _rows(SESSION, {'dispatch_plan': plan.name})
    known = {row.name for row in sessions}
    if plan.get('delivery_session') and plan.delivery_session not in known:
        _fail(plan, f'linked Delivery Session {plan.delivery_session} is missing from this Plan')
    if plan.get('active_route_stop'):
        _fail(plan, f'Route Stop {plan.active_route_stop} is still active')
    for delivery in sessions:
        if delivery.state not in ('Closed', 'Cancelled'):
            _fail(plan, f'Delivery Session {delivery.name} is {delivery.state}; finish posting/proof or controlled recovery')
        _exception(plan, delivery)
        allocations = _rows(ALLOCATION, {'delivery_session': delivery.name})
        if any(row.state not in ('Delivered', 'Released', 'Cancelled') for row in allocations):
            row = next(row for row in allocations if row.state not in ('Delivered', 'Released', 'Cancelled'))
            _fail(plan, f'Allocation {row.name} ({row.item_code}) is still {row.state}')
        delivered = [row for row in allocations if row.state == 'Delivered']
        if delivery.state == 'Cancelled':
            if delivered or delivery.get('delivery_note') and frappe.db.get_value('Delivery Note', delivery.delivery_note, 'docstatus') != 2:
                _fail(plan, f'cancelled Session {delivery.name} still has delivery evidence to resolve')
            continue
        if not delivered or not delivery.delivery_note:
            _fail(plan, f'closed Session {delivery.name} has no posted delivery allocations / Delivery Note')
        note = frappe.get_doc('Delivery Note', delivery.delivery_note)
        note.check_permission('read')
        if (note.docstatus != 1 or note.get('is_return') or note.get('cfg_delivery_session') != delivery.name
                or delivery.selling_company != plan.company or delivery.source_warehouse != plan.vehicle_warehouse):
            _fail(plan, f'Delivery Note {note.name} is not a submitted delivery for Session {delivery.name} and this lorry')
        _feedback()._validate_customer_delivery_header(note, delivery)
        rows = _feedback()._validate_customer_delivery_rows(note, delivery, delivered)
        for allocation in delivered:
            if (allocation.delivery_note != note.name or allocation.delivery_note_item != rows[allocation.name].name
                    or flt(allocation.delivered_qty) <= EPSILON
                    or abs(flt(allocation.delivered_qty) - flt(allocation.allocated_qty)) > EPSILON):
                _fail(plan, f'Allocation {allocation.name} ({allocation.item_code}) has inconsistent posted quantity / DN row')
            if allocation.dispatch_allocation:
                source = source_map.get(allocation.dispatch_allocation)
                if (not source or source.item_code != allocation.item_code or (source.batch_no or '') != (allocation.batch_no or '')
                        or source.stock_uom != allocation.stock_uom or (source.handling_unit or '') != (allocation.handling_unit or '')):
                    _fail(plan, f'Allocation {allocation.name} does not match loaded source {allocation.dispatch_allocation}')
                delivered_by_source[source.name] = delivered_by_source.get(source.name, 0) + flt(allocation.delivered_qty)
            elif allocation.get('route_source_kind') != 'Unassigned Lorry Stock':
                _fail(plan, f'Allocation {allocation.name} has no loaded source or unassigned-lorry provenance')
            total += flt(allocation.delivered_qty)
        proof = _proof(plan, delivery, note)
        documents.append(dict(delivery_session=delivery.name, delivery_note=note.name, delivery_proof=proof,
                              allocations=[row.name for row in delivered]))
    if abs(total - flt(plan.total_delivered_qty)) > EPSILON:
        _fail(plan, 'posted Delivery Note quantities differ from the current Plan delivery total; refresh its feedback')
    # Reject orphaned/cross-Plan allocations, even if their Session was not in this Plan's query.
    for source in sources:
        posted = _rows(ALLOCATION, {'dispatch_allocation': source.name, 'state': 'Delivered'})
        if any(row.delivery_session not in known for row in posted):
            _fail(plan, f'loaded source {source.name} is used by another Delivery Session')
        if abs(sum(flt(row.delivered_qty) for row in posted) - delivered_by_source.get(source.name, 0)) > EPSILON:
            _fail(plan, f'loaded source {source.name} has unmatched Delivery Note evidence')
    return documents


def _pending(plan, sources, review):
    for row in _rows('CFG Kanban Route Stop', {'dispatch_plan': plan.name}):
        if row.state not in TERMINAL:
            _fail(plan, f'Route Stop {row.name} is {row.state}; complete or skip it first')
    for pack in _rows('CFG Kanban Loose Tag', {'dispatch_plan': plan.name}):
        if pack.state not in ('Processed', 'Cancelled'):
            _fail(plan, f'Loose Tag {pack.name} is still {pack.state}; resolve its packed quantities first')
    for row in _rows('CFG Kanban Dispatch Allocation', {'dispatch_plan': plan.name}):
        if row.state not in ('Loaded', 'Released', 'Cancelled'):
            _fail(plan, f'prepared allocation {row.name} ({row.item_code}) remains {row.state}')
        if row.state in ('Released', 'Cancelled') and row.get('active_handling_unit_key'):
            _fail(plan, f'allocation {row.name} still holds an active tag reservation')
    manifests = {row.name for row in _rows(MANIFEST, {'dispatch_plan': plan.name}, ['name'])}
    review_names = [row.name for row in _rows(REVIEW, {'dispatch_plan': plan.name}, ['name'])]
    if review_names:
        manifests.update(row.name for row in _rows(MANIFEST, {'dispatch_recovery_review': ['in', review_names]}, ['name']))
    if sources:
        manifests.update(row.parent for row in _rows('CFG Kanban Manifest Line',
                         {'dispatch_allocation': ['in', [source.name for source in sources]]}, ['parent']))
    for name in sorted(manifests):
        manifest = frappe.get_doc(MANIFEST, name)
        if manifest.state not in ('Received', 'Cancelled'):
            _fail(plan, f'Movement Manifest {name} is {manifest.state}')
        _exception(plan, manifest)
        _commands(plan, 'movement_manifest', name)
    for delivery in _rows(SESSION, {'dispatch_plan': plan.name}, ['name']):
        _commands(plan, 'delivery_session', delivery.name)
    if review and plan.state != 'Reconciled' and review.get('mixed_recovery_json'):
        _fail(plan, f'Review {review.name} has a per-item recovery; finish its existing E5 workflow')
    if review and review.state not in ('Reviewing', 'Completed'):
        _fail(plan, f'Review {review.name} is {review.state}; resolve its hold/overnight decision first')
    if review and plan.state != 'Reconciled' and review.get('variance_exception'):
        _fail(plan, f'Review {review.name} has variance Exception {review.variance_exception}; resolve it through E5')


def _exception(plan, source):
    if source.get('exception'):
        status=frappe.db.get_value('CFG Kanban Exception', source.exception, 'status')
        if status not in ('Resolved', 'Cancelled', 'Closed'):
            _fail(plan, f'{source.name} has unresolved Exception {source.exception}')


def _commands(plan, field, name):
    filters = {field: name}
    if field == 'delivery_session':
        filters['command_type'] = 'Create Customer Delivery Note'
    for command in _rows('CFG ERP Command', filters):
        if command.status not in ('Completed', 'Cancelled'):
            _fail(plan, f'ERP Command {command.name} is {command.status} for {name}')


def _key(row):
    # Native Frappe child Documents support get(), not dictionary subscripting.
    return tuple(row.get(field) or '' for field in ('handling_unit', 'item_code', 'batch_no', 'stock_uom'))


def _quantities(rows, quantity):
    result = {}
    for row in rows:
        qty = flt(row.get(quantity))
        if qty > EPSILON:
            key = _key(row)
            result[key] = result.get(key, 0) + qty
    return result


def _exact(plan, expected, actual, document):
    for key in sorted(set(expected) | set(actual)):
        if abs(expected.get(key, 0) - actual.get(key, 0)) > EPSILON:
            tag, item, batch, uom = key
            _fail(plan, f'{document}: {item} / {batch or "No Batch"} / {tag or "untagged"}: expected {expected.get(key, 0):g} {uom}, recorded {actual.get(key, 0):g}')


def _ledger(plan, entry):
    """Check existing ERP posting, by voucher detail; Batch/tag stay on the SE rows."""
    actual = {}; submitted = []
    for row in _rows('Stock Ledger Entry', {'voucher_type': 'Stock Entry', 'voucher_no': entry.name}):
        if row.get('is_cancelled'):
            _fail(plan, f'Stock Entry {entry.name} has cancelled stock ledger evidence')
        if not plan.get('loaded_on') or not row.creation or get_datetime(row.creation) < get_datetime(plan.loaded_on):
            _fail(plan, f'Stock Entry {entry.name} predates this Plan load; it cannot prove its return')
        submitted.append(get_datetime(row.creation))
        key = (row.voucher_detail_no, row.warehouse, row.item_code, row.stock_uom)
        actual[key] = actual.get(key, 0) + flt(row.actual_qty)
    expected = {}
    for row in entry.items:
        for warehouse, sign in ((row.s_warehouse, -1), (row.t_warehouse, 1)):
            key = (row.name, warehouse, row.item_code, row.stock_uom)
            expected[key] = expected.get(key, 0) + sign * flt(row.transfer_qty)
    if set(actual) != set(expected) or any(abs(actual[key] - expected[key]) > EPSILON for key in expected):
        _fail(plan, f'Stock Entry {entry.name} has missing or mismatched submitted stock ledger quantities')
    return min(submitted)


def _identity_evidence(plan, manifest, line, item):
    snapshot = json.loads(line.stock_identity_snapshot) if line.get('stock_identity_snapshot') else None
    certificate = line.get('process_certificate_set') or None
    if not snapshot and item.get('serial_no'):
        _fail(plan, f'Manifest {manifest.name} line {line.name} lacks its historical serial snapshot')
    if certificate and not snapshot:
        _fail(plan, f'Manifest {manifest.name} line {line.name} lacks its historical certificate snapshot')
    if snapshot:
        for field in ('handling_unit', 'item_code', 'batch_no', 'stock_uom', 'process_certificate_set'):
            if (snapshot.get(field) or None) != (line.get(field) or None):
                _fail(plan, f'Manifest {manifest.name} line {line.name} {field} differs from its frozen stock identity')
        expected_serials = sorted(snapshot.get('serial_nos') or [])
        actual_serials = sorted(str(item.get('serial_no') or '').splitlines())
        if actual_serials != expected_serials:
            _fail(plan, f'Manifest {manifest.name} line {line.name} serials differ from the submitted transfer')
    for field in ('process_certificate_set', 'to_process_certificate_set'):
        if (item.get(field) or None) != certificate:
            _fail(plan, f'Manifest {manifest.name} line {line.name} certificate dimension differs from the submitted transfer')


def _loose_sources(plan, group):
    return [row for row in _rows(SOURCE, {'dispatch_plan': plan.name, 'state': 'Loaded',
            'movement_manifest': plan.movement_manifest})
            if not row.handling_unit and _key(row)[1:] == group]


def _loose_at(plan, sources, at):
    """Original loose load less exact deliveries actually posted before adoption."""
    by_name = {row.name: row for row in sources}
    quantity = sum(flt(row.allocated_qty) for row in sources)
    notes = set()
    for allocation in _rows(ALLOCATION, {'dispatch_allocation': ['in', sorted(by_name)], 'state': 'Delivered'}):
        source = by_name[allocation.dispatch_allocation]
        if not allocation.get('delivery_note') or not allocation.get('delivery_note_item'):
            _fail(plan, f'Allocation {allocation.name} lacks its historical Delivery Note reference')
        note = frappe.get_doc('Delivery Note', allocation.delivery_note)
        note.check_permission('read')
        item = next((row for row in note.items if row.name == allocation.delivery_note_item), None)
        if (note.docstatus != 1 or note.get('is_return') or note.company != plan.company or not item
                or note.get('cfg_delivery_session') != allocation.delivery_session
                or item.get('cfg_delivery_allocation') != allocation.name
                or _key(allocation) != _key(source)
                or _key(dict(handling_unit=item.get('cfg_handling_unit'), item_code=item.item_code,
                             batch_no=item.get('batch_no'), stock_uom=item.stock_uom)) != _key(source)
                or item.warehouse != plan.vehicle_warehouse
                or flt(allocation.delivered_qty) <= EPSILON
                or abs(flt(item.stock_qty) - flt(allocation.delivered_qty)) > EPSILON):
            _fail(plan, f'Allocation {allocation.name} lacks exact historical loose-delivery evidence')
        ledger = [row for row in _rows('Stock Ledger Entry', {'voucher_type': 'Delivery Note', 'voucher_no': note.name})
                  if row.voucher_detail_no == item.name and not row.get('is_cancelled')]
        if (not ledger or any(not row.creation or row.warehouse != plan.vehicle_warehouse
                or row.item_code != source.item_code or row.stock_uom != source.stock_uom
                or flt(row.actual_qty) >= 0 or get_datetime(row.creation) < get_datetime(plan.loaded_on) for row in ledger)
                or abs(sum(flt(row.actual_qty) for row in ledger) + flt(allocation.delivered_qty)) > EPSILON):
            _fail(plan, f'Delivery Note {note.name} lacks exact posted stock-ledger dates / quantity before tagging')
        if max(get_datetime(row.creation) for row in ledger) <= at:
            quantity -= flt(allocation.delivered_qty)
            notes.add((note.name, item.name))
    if quantity < -EPSILON:
        _fail(plan, 'historical loose deliveries exceed the original load')
    return quantity, notes


def _loose_custody(plan, group, at, notes):
    """Do not replace a Plan's loose stock with unrelated later receipts of the same SKU."""
    load = frappe.get_doc(MANIFEST, plan.movement_manifest)
    load_entries = {load.get('dispatch_stock_entry'), load.get('receipt_stock_entry')} - {None, ''}
    evidence = []
    for row in _rows('Stock Ledger Entry', {'warehouse': plan.vehicle_warehouse, 'item_code': group[0]}):
        if row.get('is_cancelled'):
            continue
        if not row.creation:
            _fail(plan, f'Stock ledger {row.name} has no custody timestamp')
        if not get_datetime(plan.loaded_on) <= get_datetime(row.creation) <= at:
            continue
        if row.voucher_type not in ('Stock Entry', 'Delivery Note'):
            _fail(plan, f'{row.voucher_type} {row.voucher_no} changes loose {group[0]} before tagging; Plan ownership is ambiguous')
        document = frappe.get_doc(row.voucher_type, row.voucher_no)
        document.check_permission('read')
        item = next((line for line in document.items if line.name == row.voucher_detail_no), None)
        if not item or document.docstatus != 1 or document.company != plan.company or item.item_code != group[0]:
            _fail(plan, f'{row.voucher_type} {row.voucher_no} has incomplete historical custody evidence')
        if (item.get('batch_no') or '', item.stock_uom) != group[1:]:
            # A missing legacy Batch with a serial/batch bundle cannot prove a different Batch.
            if item.get('serial_and_batch_bundle') and not item.get('batch_no'):
                _fail(plan, f'{row.voucher_type} {row.voucher_no} needs Batch custody verification through E5')
            continue
        if item.get('cfg_handling_unit'):
            continue
        own_load = row.voucher_type == 'Stock Entry' and row.voucher_no in load_entries and flt(row.actual_qty) > 0
        own_delivery = row.voucher_type == 'Delivery Note' and (row.voucher_no, item.name) in notes
        if not own_load and not own_delivery:
            _fail(plan, f'{row.voucher_type} {row.voucher_no} changes loose {group[0]} before tagging; Plan ownership is ambiguous')
        evidence.append(row.name)
    return evidence


def _adopted_return(plan, tag, group, qty, departed_on, received_on):
    unit = frappe.get_doc('CFG Kanban Handling Unit', tag)
    unit.check_permission('read')
    if unit.get('origin_reference_doctype') != ADOPTION or not unit.get('origin_reference_name'):
        _fail(plan, f'tag {tag} differs from its loaded source and has no Tag Existing ERP Stock provenance')
    adoption = frappe.get_doc(ADOPTION, unit.origin_reference_name)
    adoption.check_permission('read')
    if (adoption.handling_unit != tag or adoption.company != plan.company
            or adoption.warehouse != plan.vehicle_warehouse or _key(adoption)[1:] != group
            or adoption.status not in ('Adopted', 'Allocated to Cycle', 'Allocation Released')
            or not adoption.get('adopted_on') or not plan.get('loaded_on')
            or not get_datetime(plan.loaded_on) <= get_datetime(adoption.adopted_on) <= departed_on):
        _fail(plan, f'Stock Adoption {adoption.name} does not prove this tag was assigned to loose stock on this Plan lorry after loading and before return')
    quantity = flt(adoption.adopted_qty)
    if quantity <= EPSILON or abs(quantity - qty) > EPSILON:
        _fail(plan, f'Stock Adoption {adoption.name}: return must cover its whole unchanged tag ({quantity:g} {group[2]})')
    erp, tagged, loose = (flt(adoption.get(field)) for field in ('erp_qty_at_adoption', 'tagged_qty_before', 'untagged_qty_before'))
    if (tagged < -EPSILON or loose < quantity - EPSILON or abs(erp - tagged - loose) > EPSILON
            or abs(flt(adoption.remaining_untagged_qty) - (loose - quantity)) > EPSILON):
        _fail(plan, f'Stock Adoption {adoption.name} has inconsistent immutable untagged-stock quantities')
    # Later production allocation/use may change status and current tag balances.
    # Only the immutable quantity history up to receipt establishes this return.
    events = {row.name: row for field in ('source_handling_unit', 'destination_handling_unit')
              for row in _rows(TAG_LEDGER, {field: tag})}
    activations = [row for row in events.values() if row.event_type == 'Pack / Activate'
                   and row.reference_doctype == ADOPTION and row.reference_name == adoption.name
                   and row.destination_handling_unit == tag and not row.source_handling_unit
                   and _key(row)[1:] == group and abs(flt(row.stock_qty) - qty) <= EPSILON
                   and abs(flt(row.destination_qty_delta) - qty) <= EPSILON
                   and abs(flt(row.source_qty_delta)) <= EPSILON
                   and row.destination_company == plan.company and row.destination_warehouse == plan.vehicle_warehouse
                   and row.get('creation') and get_datetime(adoption.adopted_on) <= get_datetime(row.creation) <= departed_on]
    if len(activations) != 1:
        _fail(plan, f'Stock Adoption {adoption.name} is missing its exact original tag activation ledger')
    for event in events.values():
        if event.name == activations[0].name:
            continue
        changes_qty = ((event.source_handling_unit == tag and abs(flt(event.source_qty_delta)) > EPSILON)
                       or (event.destination_handling_unit == tag and abs(flt(event.destination_qty_delta)) > EPSILON))
        if changes_qty and (not event.get('creation') or get_datetime(event.creation) <= received_on):
            _fail(plan, f'tag {tag} changed quantity through ledger {event.name} before this return; use its exact source history through E5')
    return dict(handling_unit=tag, stock_adoption=adoption.name, activation_ledger=activations[0].name,
                adopted_on=str(adoption.adopted_on), qty=quantity, group=group,
                untagged_qty_before=loose)


def _return_sources(plan, rows, manifest, departed_on, received_on):
    """Bridge physical return tags to original logical allocations without rewriting either."""
    by_source = {row['dispatch_allocation']: row for row in rows if row['remaining_qty'] > EPSILON}
    physical = _quantities(manifest.lines, 'dispatch_qty')
    changes = {}
    for (tag, *parts), qty in physical.items():
        group = tuple(parts)
        if tag and not any(_key(row) == (tag, *group) for row in by_source.values()):
            if not any(not row['handling_unit'] and _key(row)[1:] == group for row in by_source.values()):
                _fail(plan, f'Manifest {manifest.name} tag {tag} has no matching original loose Plan source')
            changes[tag] = _adopted_return(plan, tag, group, qty, departed_on, received_on)
    prior = {}
    for change in sorted(changes.values(), key=lambda row: (get_datetime(row['adopted_on']), row['stock_adoption'])):
        group = change['group']; at = get_datetime(change['adopted_on'])
        sources = _loose_sources(plan, group)
        quantity, notes = _loose_at(plan, sources, at)
        if any(row.get('refused_released_qty') or row.get('cancelled_released_qty') for row in rows if not row['handling_unit'] and _key(row)[1:] == group):
            _fail(plan, f'Stock Adoption {change["stock_adoption"]} follows released loose commitments; verify their ownership through E5')
        # Stock Adoption has no Plan FK. Reject a competing loose obligation even
        # if the current lorry is empty or that other Plan settled after adoption.
        others = {row.dispatch_plan for row in _rows(SOURCE, {'state': 'Loaded', 'item_code': group[0], 'stock_uom': group[2]})
                  if not row.handling_unit and _key(row)[1:] == group and row.dispatch_plan != plan.name}
        for name in sorted(others):
            other = frappe.get_doc(PLAN, name)
            if other.company != plan.company or other.vehicle_warehouse != plan.vehicle_warehouse:
                continue
            if other.get('loaded_on') and get_datetime(other.loaded_on) > at:
                continue
            other.check_permission('read')
            if (other.state == 'Reconciled' and other.get('dispatch_review_state') == 'Settled'
                    and other.get('active_dispatch_review')):
                review = frappe.get_doc(REVIEW, other.active_dispatch_review)
                if review.state == 'Completed' and review.get('closed_on') and get_datetime(review.closed_on) <= at:
                    continue
            if not other.get('loaded_on') or _loose_at(other, _loose_sources(other, group), at)[0] > EPSILON:
                _fail(plan, f'Stock Adoption {change["stock_adoption"]} has ambiguous loose ownership with Plan {name}')
        available = quantity - prior.get(group, 0)
        if abs(available - change['untagged_qty_before']) > EPSILON:
            _fail(plan, f'Stock Adoption {change["stock_adoption"]}: Plan loose balance was {available:g} {group[2]}, untagged snapshot was {change["untagged_qty_before"]:g}; ownership is ambiguous')
        change['custody_stock_ledgers'] = _loose_custody(plan, group, at, notes)
        change['prior_adopted_qty'] = prior.get(group, 0)
        prior[group] = prior.get(group, 0) + change['qty']
    logical = {}; assigned = {}; mappings = []
    # Honour explicit allocation links before distributing fungible loose rows.
    for line in sorted(manifest.lines, key=lambda row: (not bool(row.get('dispatch_allocation')), row.name)):
        key = _key(line)
        logical_key = ('', *key[1:]) if key[0] in changes else key
        logical[logical_key] = logical.get(logical_key, 0) + flt(line.dispatch_qty)
        candidates = [row for row in by_source.values() if _key(row) == logical_key
                      and (not line.get('dispatch_allocation') or row['dispatch_allocation'] == line.dispatch_allocation)]
        if line.get('dispatch_allocation') and not candidates:
            _fail(plan, f'Manifest {manifest.name} line {line.name} belongs to another source allocation')
        if not line.handling_unit and not line.get('dispatch_allocation'):
            _fail(plan, f'Manifest {manifest.name} untagged {line.item_code} has no Plan allocation provenance')
        if key[0] and key[0] not in changes and len(candidates) != 1:
            _fail(plan, f'Manifest {manifest.name} tag {key[0]} has ambiguous Plan ownership')
        remaining = flt(line.dispatch_qty)
        for source in sorted(candidates, key=lambda row: row['dispatch_allocation']):
            name = source['dispatch_allocation']
            qty = min(remaining, max(source['remaining_qty'] - assigned.get(name, 0), 0))
            if qty > EPSILON:
                assigned[name] = assigned.get(name, 0) + qty; remaining -= qty
                mappings.append(dict(manifest_line=line.name, handling_unit=line.handling_unit,
                                     dispatch_allocation=name, qty=qty, stock_uom=line.stock_uom))
        if remaining > EPSILON:
            _fail(plan, f'Manifest {manifest.name} line {line.name} exceeds its exact remaining Plan source')
    _exact(plan, _quantities(rows, 'remaining_qty'), logical, manifest.name)
    if any(abs(assigned.get(name, 0) - row['remaining_qty']) > EPSILON for name, row in by_source.items()):
        _fail(plan, f'Manifest {manifest.name} does not cover every exact remaining Plan source')
    return dict(identity_changes=list(changes.values()), allocation_sources=mappings)


def _returned(plan, rows, manifest_name, review=None):
    manifest = frappe.get_doc(MANIFEST, manifest_name)
    manifest.check_permission('read')
    if (manifest.state != 'Received' or manifest.manifest_type != 'Internal Warehouse Transfer'
            or manifest.source_company != plan.company or manifest.destination_company != plan.company
            or manifest.source_warehouse != plan.vehicle_warehouse):
        _fail(plan, f'Movement Manifest {manifest.name} is not a completed same-Company return from {plan.vehicle_warehouse}')
    _exception(plan, manifest)
    _commands(plan, 'movement_manifest', manifest.name)
    destination = frappe.get_doc('Warehouse', manifest.destination_warehouse)
    destination.check_permission('read')
    if (destination.company != plan.company or destination.disabled or destination.is_group
            or destination.get('cfg_is_vehicle_warehouse') or destination.name == plan.vehicle_warehouse):
        _fail(plan, f'Movement Manifest {manifest.name} destination {destination.name} is not an active non-lorry Warehouse in this Company')
    if manifest.get('dispatch_plan') and manifest.dispatch_plan != plan.name:
        _fail(plan, f'Movement Manifest {manifest.name} belongs to Plan {manifest.dispatch_plan}')
    linked = manifest.get('dispatch_recovery_review')
    if linked and (not review or linked != review.name):
        _fail(plan, f'Movement Manifest {manifest.name} belongs to another Review {linked}')
    if review and review.get('recovery_manifest') and review.recovery_manifest != manifest.name:
        _fail(plan, f'Review {review.name} already has recovery Manifest {review.recovery_manifest}')
    expected = _quantities(rows, 'remaining_qty')
    physical = _quantities(manifest.lines, 'dispatch_qty')
    if all(key in expected for key in physical):
        _exact(plan, expected, physical, manifest.name)
    for line in manifest.lines:
        if (line.state != 'Received' or flt(line.dispatch_qty) <= EPSILON
                or abs(flt(line.received_qty) - flt(line.dispatch_qty)) > EPSILON):
            _fail(plan, f'Manifest {manifest.name} line {line.name} ({line.item_code}) is not fully received')
    entries = [manifest.dispatch_stock_entry]
    if manifest.internal_transfer_mode == 'Goods in Transit':
        entries.append(manifest.receipt_stock_entry)
    evidence = []; submitted = []
    for name in entries:
        if not name:
            _fail(plan, f'Manifest {manifest.name} is missing a submitted Stock Entry')
        entry = frappe.get_doc('Stock Entry', name)
        entry.check_permission('read')
        if (entry.docstatus != 1 or entry.company != plan.company
                or (entry.get('purpose') or entry.get('stock_entry_type')) != 'Material Transfer'
                or entry.get('cfg_movement_manifest') != manifest.name):
            _fail(plan, f'Stock Entry {name} is not a submitted same-Company transfer for Manifest {manifest.name}')
        used = frappe.db.get_value(REVIEW, {'movement_stock_entry': name, 'state': 'Completed'}, 'name')
        if used and (not review or used != review.name):
            _fail(plan, f'Stock Entry {name} already settled Review {used}')
        # Reuse native immutable row/route/transit validation. Posting-time live
        # identity checks are intentionally not rerun on later warehouse stock.
        _feedback().validate_internal_transfer_evidence(entry)
        actual = {}
        manifest_rows = {line.name: line for line in manifest.lines}
        for item in entry.items:
            line = manifest_rows[item.cfg_manifest_line]
            if (item.get('cfg_handling_unit') or '') != (line.handling_unit or '') or item.stock_uom != line.stock_uom:
                _fail(plan, f'Stock Entry {name} row {item.name} tag / stock UOM differs from Manifest line {line.name}')
            _identity_evidence(plan, manifest, line, item)
            key = (item.get('cfg_handling_unit') or '', item.item_code, item.batch_no or '', item.stock_uom)
            actual[key] = actual.get(key, 0) + flt(item.transfer_qty)
        _exact(plan, physical, actual, name)
        submitted.append(_ledger(plan, entry))
        evidence.append(name)
    provenance = _return_sources(plan, rows, manifest, min(submitted), max(submitted))
    # The posted location ledger proves historical custody. Later legitimate use
    # of the returned stock must not be mistaken for an unreturned Plan remainder.
    tag_ledgers=[]
    for key, qty in physical.items():
        tag, item, batch, uom = key
        if not tag:
            continue
        for owner in _rows(SOURCE, {'handling_unit': tag, 'state': 'Loaded'}, ['dispatch_plan']):
            if owner.dispatch_plan == plan.name:
                continue
            later = frappe.get_doc(PLAN, owner.dispatch_plan)
            if later.get('loaded_on') and get_datetime(plan.loaded_on) <= get_datetime(later.loaded_on) <= max(submitted):
                _fail(plan, f'Manifest {manifest.name} tag {tag} was loaded again before this transfer; select its exact earlier return')
        for index, entry_name in enumerate(entries):
            source = plan.vehicle_warehouse if index == 0 else manifest.transit_warehouse
            target = manifest.transit_warehouse if len(entries) == 2 and index == 0 else destination.name
            transfers = _rows(TAG_LEDGER, {
                'event_type': 'Location Transfer', 'source_handling_unit': tag,
                'reference_doctype': 'Stock Entry', 'reference_name': entry_name})
            matches=[event for event in transfers if event.item_code == item
                     and (event.batch_no or '') == batch and event.stock_uom == uom
                     and abs(flt(event.stock_qty) - qty) <= EPSILON
                     and event.source_company == plan.company and event.source_warehouse == source
                     and event.destination_warehouse == target and event.destination_company == plan.company]
            if len(matches) != 1:
                _fail(plan, f'Manifest {manifest.name} tag {tag} is missing its exact posted location-transfer ledger for {entry_name}')
            tag_ledgers.append(matches[0].name)
    # A pre-review return is valid; its real document dates are retained, never rewritten.
    return dict(manifest=manifest.name, stock_entries=evidence, tag_ledgers=tag_ledgers, **provenance, destination_warehouse=destination.name,
                posted_before_review=bool(manifest.get('dispatch_confirmed_on')
                    and get_datetime(manifest.dispatch_confirmed_on) < get_datetime(review.opened_on if review else now_datetime())))


def inspect_plan(plan, return_manifest=None, discover=False):
    """Preflight without writes. Route callers preflight *all* members before settling any."""
    if plan.fulfilment_mode != 'Vehicle Delivery' or plan.state not in ('Loaded', 'Reconciled', 'Ready for Fulfilment'):
        _fail(plan, f'Plan is {plan.state}; complete its loading/preparation first')
    if plan.state == 'Ready for Fulfilment' and not plan.get('existing_lorry_stock_only'):
        _fail(plan, 'Plan has no confirmed lorry load')
    for doctype, name in (('Company', plan.company), ('Warehouse', plan.vehicle_warehouse)):
        source = frappe.get_doc(doctype, name)
        source.check_permission('read')
        if doctype == 'Warehouse' and (source.company != plan.company or not source.get('cfg_is_vehicle_warehouse')
                                     or source.disabled or source.is_group):
            _fail(plan, f'{name} is not an active lorry Warehouse in this Company')
    review = frappe.get_doc(REVIEW, plan.active_dispatch_review) if plan.get('active_dispatch_review') else None
    if review and (review.dispatch_plan != plan.name or review.company != plan.company or review.vehicle_warehouse != plan.vehicle_warehouse):
        _fail(plan, f'Review {review.name} does not match this Plan / Company / lorry')
    sources = _reviews()._fulfilment()._loaded_allocations(plan)
    if not plan.get('existing_lorry_stock_only'):
        _reviews()._fulfilment().validate_prepared_loading(plan)
    documents = _deliveries(plan, sources)
    _pending(plan, sources, review)
    if plan.state == 'Reconciled':
        if plan.dispatch_review_state != 'Settled' or not review or review.state != 'Completed':
            _fail(plan, 'Plan settlement has no completed Review audit')
        return dict(plan=plan, review=review, settled=True, documents=documents, balances=[], return_evidence=None)
    if review and review.state == 'Completed':
        _fail(plan, f'Review {review.name} is completed but Plan settlement is inconsistent')
    balances = _reviews()._balances(plan)
    for row in balances:
        # Audit this Plan's historical quantities, never the tag's later stock.
        for field in list(row):
            if field.startswith('current_') or field == 'reserved_qty':row.pop(field)
    remaining = any(row['remaining_qty'] > EPSILON for row in balances)
    action = 'Returned to Warehouse' if remaining else 'No Remaining Prepared Stock'
    if plan.get('stop_cancellation') or plan.get('consolidated_customer_orders'):
        from cfg_kanban.services.cancelled_stop_stock import assert_review_action
        assert_review_action(plan, action)
    result = dict(plan=plan, review=review, settled=False, documents=documents, balances=balances,
                  return_evidence=None, candidates=[], blockers=[])
    if not remaining:
        if return_manifest:
            _fail(plan, 'no prepared stock remains; do not assign return evidence to this closure')
        return result
    if return_manifest:
        result['return_evidence'] = _returned(plan, balances, return_manifest, review)
        return result
    names = {line.parent for line in _rows('CFG Kanban Manifest Line',
        {'dispatch_allocation': ['in', [row['dispatch_allocation'] for row in balances if row['remaining_qty'] > EPSILON]]}, ['parent'])}
    tags = [row['handling_unit'] for row in balances if row['remaining_qty'] > EPSILON and row['handling_unit']]
    loose_groups = {_key(row)[1:] for row in balances if row['remaining_qty'] > EPSILON and not row['handling_unit']}
    if loose_groups:
        if not plan.get('loaded_on'):
            _fail(plan, 'the original loose load has no confirmed loading timestamp')
        # Historical loose loading rows deliberately remain untagged. Discover the
        # later physical identity through immutable adoption records instead.
        tags.extend(row.handling_unit for row in _rows(ADOPTION, {'company': plan.company, 'warehouse': plan.vehicle_warehouse,
                    'item_code': ['in', sorted({group[0] for group in loose_groups})]})
                    if row.handling_unit and _key(row)[1:] in loose_groups and row.get('adopted_on')
                    and get_datetime(row.adopted_on) >= get_datetime(plan.loaded_on))
    if tags:
        names.update(line.parent for line in _rows('CFG Kanban Manifest Line', {'handling_unit': ['in', tags]}, ['parent']))
    if review and review.get('recovery_manifest'):
        names.add(review.recovery_manifest)
    candidates = _rows(MANIFEST, {'name': ['in', sorted(names)], 'state': 'Received',
        'manifest_type': 'Internal Warehouse Transfer', 'source_company': plan.company,
        'source_warehouse': plan.vehicle_warehouse}, ['name']) if names else []
    for candidate in candidates:
        # Candidate failures are informational, not permission to bypass any check.
        messages = getattr(getattr(frappe, 'local', None), 'message_log', None)
        message_count = len(messages) if isinstance(messages, list) else 0
        try:
            evidence = _returned(plan, balances, candidate.name, review)
        except (frappe.ValidationError, frappe.PermissionError) as error:
            messages = getattr(getattr(frappe, 'local', None), 'message_log', None)
            if isinstance(messages, list):del messages[message_count:]
            result['blockers'].append(str(error))
        else:
            result['candidates'].append(evidence)
    if not result['candidates'] and not result['blockers']:
        outstanding = ', '.join(f'{row["item_code"]} / {row["batch_no"] or "No Batch"} / {row.get("visible_code") or row["handling_unit"] or "untagged"}: {row["remaining_qty"]:g} {row["stock_uom"]}' for row in balances if row['remaining_qty'] > EPSILON)
        result['blockers'].append('No completed return is linked to these exact remaining sources: '+outstanding+'. Select the existing Manifest for validation; untagged stock requires its Dispatch Allocation provenance.')
    if len(result['candidates']) == 1:
        result['return_evidence'] = result['candidates'][0]
    elif not discover:
        if len(result['candidates']) > 1:
            _fail(plan, 'several completed return Manifests match; select the exact return using Close Plan')
        detail = result['blockers'][0] if result['blockers'] else ', '.join(
            f'{row["item_code"]} / {row["batch_no"] or "No Batch"} / {row.get("visible_code") or row["handling_unit"] or "untagged"}: {row["remaining_qty"]:g} {row["stock_uom"]}'
            for row in balances if row['remaining_qty'] > EPSILON)
        _fail(plan, 'no exact completed return evidence: ' + detail)
    return result


def validate_group(preflights):
    claimed={}
    for value in preflights:
        for entry in (value['return_evidence'] or {}).get('stock_entries', []):
            if entry in claimed:
                _fail(value['plan'], f'Stock Entry {entry} also claims Plan {claimed[entry]} in this route')
            claimed[entry]=value['plan'].name


def settle(preflight, operator, session, reason, key, request_hash, route_sheet=None):
    plan, review = preflight['plan'], preflight['review']
    if preflight['settled']:
        return dict(dispatch_plan=plan.name, dispatch_review=review.name, outcome='Already Settled')
    rows, returned = preflight['balances'], preflight['return_evidence']
    if any(row['remaining_qty'] > EPSILON for row in rows) and not returned:
        _fail(plan, 'select exact return evidence before confirming')
    action = 'Returned to Warehouse' if returned else 'No Remaining Prepared Stock'
    evidence = dict(basis='Posted Documents', dispatch_plan=plan.name, route_sheet=route_sheet,
                    delivery_outcome=plan.fulfilment_status, total_delivered_qty=plan.total_delivered_qty,
                    deliveries=preflight['documents'], returned=returned, actor=operator.employee,
                    closed_on=str(now_datetime()), action=action)
    if not review:
        review = frappe.get_doc(dict(doctype=REVIEW, state='Reviewing', dispatch_plan=plan.name,
            company=plan.company, vehicle_warehouse=plan.vehicle_warehouse, vehicle_reference=plan.vehicle_reference,
            opened_on=now_datetime(), opened_by_operator=operator.employee, operator_session=session.name,
            opening_snapshot_json=_reviews()._json(rows), opening_snapshot_hash=_reviews()._hash(rows),
            idempotency_key=canonical_key('document-closure-review', plan.name, key))).insert(ignore_permissions=True)
    review.db_set(dict(state='Completed', settlement_basis='Posted Documents',
        closure_evidence_json=frappe.as_json(evidence), action=action, reason=reason,
        movement_stock_entry=returned['stock_entries'][0] if returned else None,
        destination_warehouse=returned['destination_warehouse'] if returned else None,
        closed_on=now_datetime(), closed_by_operator=operator.employee, active_plan_key=None,
        closing_snapshot_json=_reviews()._json(rows), closing_snapshot_hash=_reviews()._hash(rows),
        finish_key=canonical_key('document-closure-finish', plan.name, key), finish_payload_hash=request_hash),
        update_modified=True)
    # A returned/skipped/partially refused load must never be relabelled as fully delivered.
    incomplete = bool(returned or any(row.get('refused_released_qty') or row.get('cancelled_released_qty') for row in rows))
    skipped = any(row.state in ('Skipped', 'Closed Incomplete') for row in _rows('CFG Kanban Route Stop', {'dispatch_plan': plan.name}))
    plan.db_set(dict(state='Reconciled', dispatch_review_state='Settled', active_dispatch_review=review.name,
        route_stock_commitment=0, prepared_stock_commitment=0,
        fulfilment_status='Closed Incomplete' if incomplete or skipped else 'Completed',
        fulfilment_completed_on=now_datetime()), update_modified=True)
    record('Dispatch Plan Reconciled', reference_doctype=REVIEW, reference_name=review.name,
           operator=operator.employee, operator_session=session.name, terminal_user=session.terminal_user,
           idempotency_key=canonical_key('document-closure-audit', plan.name, key),
           notes=f'{plan.name}; {action}; posted documents; {reason}', payload=evidence)
    return dict(dispatch_plan=plan.name, dispatch_review=review.name, outcome=action, evidence=evidence)


def _response(plan, result=None):
    return dict(plan=plan.as_dict(), closure=result, review=frappe.get_doc(REVIEW, plan.active_dispatch_review).as_dict()
                if plan.get('active_dispatch_review') else None)


def get_close_plan_context(scan_value, operator_session_token):
    operator, _session = _reviews()._authorized(operator_session_token)
    plan = _reviews()._plan(str(scan_value or '').strip(), operator)
    plan.check_permission('read')
    if plan.plan_type != 'Open Route Stock':
        _fail(plan, 'Close Plan is for standalone Open Route Stock; use Close Route for customer itineraries')
    if plan.get('active_route_sheet'):
        _fail(plan, f'use Close Route on linked Sheet {plan.active_route_sheet}')
    result = inspect_plan(plan, discover=True)
    return dict(_response(plan), balances=result['balances'], candidates=result.get('candidates', []),
                blockers=result.get('blockers', []), return_manifest=(result['return_evidence'] or {}).get('manifest'),
                can_close=bool(result['settled'] or not any(row['remaining_qty'] > EPSILON for row in result['balances']) or result['return_evidence']))


def close_dispatch_plan(dispatch_plan, reason, event_token, operator_session_token, return_manifest=None):
    operator, session = _reviews()._authorized(operator_session_token, 'complete')
    _reviews()._planning()._require_event_token(event_token)
    _reviews()._supervisor(operator)
    reason = str(reason or '').strip()
    if not reason:
        frappe.throw('A Plan closure reason is required')
    key = canonical_key('close-dispatch-plan', dispatch_plan, operator.employee, event_token)
    fingerprint = canonical_key('close-dispatch-plan-request', dispatch_plan, reason, return_manifest or '')
    # This savepoint includes the response and audit: caught errors also leave no partial closure.
    frappe.db.savepoint('cfg_close_dispatch_plan')
    try:
        plan = _reviews()._plan(dispatch_plan, operator, current=True)
        plan.check_permission('read')
        old = frappe.db.get_value('CFG Kanban Event', {'idempotency_key': key}, 'payload_json', for_update=True)
        if old:
            payload = json.loads(old)
            if payload.get('request_hash') != fingerprint:
                frappe.throw('This closure token belongs to different details')
            return _response(plan, payload['closure'])
        if plan.plan_type != 'Open Route Stock' or plan.get('active_route_sheet'):
            _fail(plan, 'use Close Route for a linked Route Sheet; standalone Close Plan requires Open Route Stock')
        if plan.state == 'Reconciled' and plan.dispatch_review_state == 'Settled':
            return _response(plan, dict(dispatch_plan=plan.name, outcome='Already Settled'))
        preflight = inspect_plan(plan, return_manifest)
        result = settle(preflight, operator, session, reason, key, fingerprint)
        record('Dispatch Plan Closed from Documents', reference_doctype=PLAN, reference_name=plan.name,
               operator=operator.employee, operator_session=session.name, terminal_user=session.terminal_user,
               idempotency_key=key, notes=reason, payload=dict(request_hash=fingerprint, closure=result))
        return _response(plan, result)
    except Exception:
        frappe.db.rollback(save_point='cfg_close_dispatch_plan')
        raise
