"""Driver invoicing delegates quantity, taxes and naming to ERPNext v15."""
import frappe
from frappe.utils import cint, flt, now_datetime

from cfg_kanban.services.idempotency import canonical_key, insert_once

OFFICE_FIELDS = {
    'company', 'customer', 'naming_series', 'currency', 'conversion_rate',
    'selling_price_list', 'price_list_currency', 'plc_conversion_rate', 'debit_to',
    'cost_center', 'taxes', 'taxes_and_charges', 'tax_category', 'tax_id',
    'payment_schedule', 'payment_terms_template', 'payments', 'advances',
    'discount_amount', 'additional_discount_percentage', 'write_off_account',
    'write_off_cost_center', 'company_bank_account', 'bank_account', 'incoterm',
}
ITEM_SOURCE_FIELDS = {
    'item_code', 'item_name', 'description', 'qty', 'rate', 'amount', 'stock_qty',
    'base_rate', 'base_amount', 'uom', 'stock_uom', 'conversion_factor', 'delivery_note',
    'dn_detail', 'sales_order', 'so_detail', 'warehouse', 'batch_no', 'serial_no',
    'serial_and_batch_bundle', 'process_certificate_set', 'income_account', 'expense_account',
    'cost_center', 'discount_percentage', 'discount_amount', 'item_tax_template',
    'item_tax_rate', 'deferred_revenue_account', 'enable_deferred_revenue',
}


def driver_required_inputs(invoice):
    """Mandatory custom inputs cannot become a commercial/accounting editor."""
    from cfg_kanban.integrations.erp_gateway import get_required_erp_inputs
    result = []
    for row in get_required_erp_inputs(invoice):
        if row['fieldname'] in OFFICE_FIELDS or (row.get('scope') != 'table' and
                (row.get('options') == 'Account' or row.get('fieldtype') in ('Currency', 'Percent'))):
            frappe.throw('Office must configure the missing Invoice accounting default: ' + row['fieldname'])
        if row['fieldname'] == 'items':
            columns = []
            for column in row.get('fields') or []:
                protected = (column['fieldname'] in ITEM_SOURCE_FIELDS or column.get('options') == 'Account'
                             or column.get('fieldtype') in ('Currency', 'Percent'))
                if protected and column.get('reqd') and any(item.get(column['fieldname']) in (None, '') for item in invoice.items):
                    frappe.throw('Office must configure the missing Invoice Item default: ' + column['fieldname'])
                columns.append(dict(column, **({'read_only': 1} if protected else {})))
            row = dict(row, fields=columns)
        result.append(row)
    return result


def _permissions(profile, operator):
    if profile.invoice_mode == 'Disabled':
        frappe.throw('Driver invoicing is disabled in the Company Mobile Print Profile')
    if not frappe.has_permission('Sales Invoice', ptype='create'):
        frappe.throw('Sales Invoice Create permission is required', frappe.PermissionError)
    automatic = profile.invoice_mode == 'Automatic Submission'
    if automatic:
        employees = {r.employee for r in profile.get('invoice_operators') or []}
        if operator.employee not in employees or not frappe.has_permission('Sales Invoice', ptype='submit'):
            frappe.throw('This operator is not authorized for automatic invoice submission', frappe.PermissionError)
    return automatic


def _existing(note, current=False):
    # Include native office drafts: the native mapper subtracts submitted invoices only.
    names = {r.parent for r in frappe.db.sql('''
        SELECT DISTINCT i.parent FROM `tabSales Invoice Item` i
        INNER JOIN `tabSales Invoice` p ON p.name=i.parent
        WHERE p.docstatus=0 AND p.is_return=0
          AND (i.delivery_note=%s OR i.dn_detail IN
            (SELECT name FROM `tabDelivery Note Item` WHERE parent=%s))
        ''' + (' FOR UPDATE' if current else ''), (note.name, note.name), as_dict=True)}
    if len(names) > 1:
        frappe.throw('Multiple Invoice drafts already reference this Delivery Note; ask Accounts to reconcile them')
    if not names:
        return None
    doc = frappe.get_doc('Sales Invoice', names.pop(), **({'for_update': True} if current else {}))
    doc.check_permission('read')
    if doc.company != note.company or doc.customer != note.customer or cint(doc.update_stock):
        frappe.throw('Existing Invoice draft does not match this non-stock billing request')
    return doc


def build(note, values=None, validate_required=True):
    from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice
    from cfg_kanban.integrations.erp_gateway import apply_required_erp_inputs
    if note.docstatus != 1 or cint(note.is_return):
        frappe.throw('Only a submitted customer Delivery Note can create an Invoice')
    invoice = make_sales_invoice(note.name)
    invoice.update_stock = 0
    invoice.is_pos = 0  # This action does not collect or fabricate a payment.
    if (invoice.company != note.company or invoice.customer != note.customer or cint(invoice.is_return)
            or not invoice.get('items')):
        frappe.throw('ERPNext did not map a valid customer Invoice')
    source_rows = {r.name: r for r in note.items}
    for row in invoice.items:
        source = source_rows.get(row.dn_detail)
        if (not source or row.delivery_note != note.name or row.item_code != source.item_code
                or flt(row.qty) <= 0 or flt(row.qty) > flt(source.qty) + 0.000001):
            frappe.throw('ERPNext Invoice rows do not match the exact Delivery Note')
    # The shared required-table editor replaces rows. Preserve native item identities
    # while filling missing mandatory/custom values on those exact mapped rows.
    supplied = frappe.parse_json(values) if isinstance(values, str) else (values or {})
    tables = dict(supplied.get('tables') or {})
    item_values = tables.pop('items', None)
    if item_values is not None:
        if not isinstance(item_values, list) or len(item_values) != len(invoice.items):
            frappe.throw('Required Invoice Item values must match the mapped row count')
        descriptor = next((r for r in driver_required_inputs(invoice) if r['fieldname'] == 'items'), None)
        editable = {r['fieldname'] for r in (descriptor or {}).get('fields', []) if r.get('reqd') and not r.get('read_only')}
        for row, additions in zip(invoice.items, item_values):
            for key in editable:
                if row.get(key) in (None, '') and additions.get(key) not in (None, ''):
                    row.set(key, additions[key])
    driver_required_inputs(invoice)  # Reject missing office defaults before accepting parent input.
    apply_required_erp_inputs(invoice, dict(parent=supplied.get('parent') or {}, tables=tables))
    # Required-field entry cannot turn this billing action into a second stock issue.
    if cint(invoice.update_stock) or cint(invoice.is_return) or cint(invoice.is_pos):
        frappe.throw('Driver invoicing must remain a non-stock customer Invoice')
    if validate_required and driver_required_inputs(invoice):
        frappe.throw('Complete the required ERPNext Invoice fields before creation')
    return invoice


def requirements(trip, stop, note_name, operator, profile):
    from cfg_kanban.services.mobile_printing import delivery_note
    _permissions(profile, operator)
    note = delivery_note(trip, stop, note_name, operator)
    existing = _existing(note)
    return dict(doctype='Sales Invoice', existing_draft=existing.name if existing else None,
                fields=[] if existing else driver_required_inputs(build(note, validate_required=False)),
                invoice_mode=profile.invoice_mode, profile_version=str(profile.modified), delivery_note=note.name)


def create(trip, stop, values, operator, session, profile, action_key, *, draft_only=False):
    from cfg_kanban.services.mobile_printing import delivery_note
    from cfg_kanban.integrations.erp_gateway import execute_command
    if values.get('profile_version') != str(profile.modified) or values.get('invoice_mode') != profile.invoice_mode:
        frappe.throw('Office Invoice policy changed after review; refresh and review the current policy')
    automatic = _permissions(profile, operator) and not draft_only
    note = delivery_note(trip, stop, values.get('delivery_note'), operator, current=True)
    existing = _existing(note, current=True)
    if existing:
        # Reusing an office draft must never submit it through the automatic policy.
        return dict(invoice=existing.name, docstatus=existing.docstatus, existing_draft=True)
    payload = dict(trip_name=trip.name, stop_key=stop.stop_key, delivery_note=note.name,
                   required_erp_inputs=values.get('required_erp_inputs') or {},
                   automatic=automatic, profile=profile.name, profile_version=str(profile.modified), employee=operator.employee)
    if draft_only:
        payload['draft_only'] = True  # Keep pre-existing manual command payloads replay-compatible.
    command, created = insert_once(frappe.get_doc(dict(
        doctype='CFG ERP Command', command_type='Create Driver Sales Invoice', status='Pending',
        target_doctype='Sales Invoice', request_payload=frappe.as_json(payload),
        requested_by_operator=operator.employee, operator_session=session.name,
        terminal_user=session.terminal_user, requested_on=now_datetime(), created_by_system=1)),
        canonical_key('driver-sales-invoice', action_key), ignore_permissions=True)
    if not created and command.request_payload != frappe.as_json(payload):
        frappe.throw('Original Invoice command has different details')
    invoice = execute_command(command.name)
    return dict(invoice=invoice.name, docstatus=invoice.docstatus, erp_command=command.name)


def execute(command, payload):
    """Called synchronously by the ERP gateway, in the authenticated operator transaction."""
    from cfg_kanban.services import driver_routes
    from cfg_kanban.services.mobile_printing import get_profile, delivery_note, saved_stop
    operator, session = require_operator_from_command(command)
    trip = driver_routes._trip(payload['trip_name'], operator)
    stop = saved_stop(trip, payload['stop_key'])
    profile = get_profile(trip.company, current=True)
    automatic = _permissions(profile, operator) and not bool(payload.get('draft_only'))
    if (profile.name != payload['profile'] or str(profile.modified) != payload.get('profile_version') or automatic != bool(payload['automatic'])
            or operator.employee != payload['employee']):
        frappe.throw('Invoice policy changed; review a new driver request')
    note = delivery_note(trip, stop, payload['delivery_note'], operator, current=True)
    existing = _existing(note, current=True)
    if existing:
        return existing
    invoice = build(note, payload.get('required_erp_inputs'))
    invoice.insert()  # Native permissions, naming rules and all server validations apply.
    invoice.check_permission('read')
    if automatic:
        invoice.check_permission('submit')
        invoice.submit()
    return invoice


def require_operator_from_command(command):
    """The gateway is not an alternate public authorization boundary."""
    from cfg_kanban.services.operator_auth import require_operator
    token = getattr(frappe.local, 'cfg_mobile_invoice_token', None)
    if not token:
        frappe.throw('Driver Invoice commands require an active authenticated driver action', frappe.PermissionError)
    operator, session = require_operator(token, 'complete')
    if (operator.employee != command.requested_by_operator or session.name != command.operator_session
            or session.terminal_user != command.terminal_user):
        frappe.throw('Invoice command does not belong to this operator session', frappe.PermissionError)
    return operator, session
