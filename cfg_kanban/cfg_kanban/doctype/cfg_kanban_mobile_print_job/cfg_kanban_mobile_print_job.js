frappe.ui.form.on('CFG Kanban Mobile Print Job', {
 refresh(frm) {
  if (frm.is_new() || !frm.doc.__onload?.can_close_mobile_print_job
      || !['Prepared', 'Awaiting Confirmation'].includes(frm.doc.status)) return;
  let segments;
  try {
   segments = Object.entries(JSON.parse(frm.doc.segments_json || '{}').pages || {})
    .map(([page, row]) => `${__('Segment')} ${page}: ${row?.status || __('Unknown')}`).join(' · ');
  } catch (_) { segments = __('Segment metadata cannot be read; reconcile the physical output before closing.'); }
  frm.set_intro(__('Check the physical receipt before closing this job. Closure retains confirmations and does not confirm printing, cancel the source document or change stock.')
   + (segments ? '<br>' + frappe.utils.escape_html(segments) : ''));
  frm.add_custom_button(__('Close Unfinished Job'), () => {
   if (frm.is_dirty()) return frappe.msgprint(__('Reload this print job before closing it.'));
   frappe.prompt([{fieldname: 'reason', fieldtype: 'Small Text', reqd: 1,
    label: __('Reason for closing the unfinished print job')}], async values => {
    await frappe.call({method: 'cfg_kanban.services.mobile_printing.close_mobile_print_job',
     args: {print_job: frm.doc.name, reason: values.reason, expected_modified: frm.doc.modified},
     freeze: true, freeze_message: __('Closing unfinished print job…')});
    await frm.reload_doc();
   }, __('Close Unfinished Job'), __('Close Job'));
  });
 }
});
