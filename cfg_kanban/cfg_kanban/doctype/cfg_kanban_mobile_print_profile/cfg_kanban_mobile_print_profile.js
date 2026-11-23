frappe.ui.form.on('CFG Kanban Mobile Print Profile', {
  setup(frm) {
    const formats = {
      delivery_note_format: 'Delivery Note', sales_invoice_format: 'Sales Invoice',
      credit_note_format: 'Credit Note', return_note_format: 'CFG Kanban Return Case',
      trip_stock_format: 'CFG Kanban Delivery Trip', stock_tag_format: 'CFG Kanban Handling Unit',
      custody_label_format: 'CFG Kanban Return Custody Label',
    };
    for (const [field, doctype] of Object.entries(formats)) {
      frm.set_query(field, () => ({filters: {doc_type: doctype, disabled: 0, raw_printing: 0}}));
    }
    frm.set_query('employee', 'invoice_operators', () => ({filters: {status: 'Active'}}));
  },
});
