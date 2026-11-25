import frappe
from frappe.model.document import Document


class CFGKanbanDispatchReview(Document):
    def validate(self):
        if self.state not in ('Reviewing','Held','Overnight','Completed','Resumed'):
            frappe.throw('Invalid Dispatch Review state')
        before=None if self.is_new() else self.get_doc_before_save()
        if before:
            for name in ('dispatch_plan','company','vehicle_warehouse','vehicle_reference',
                         'opened_on','opened_by_operator','operator_session','opening_snapshot_json',
                         'opening_snapshot_hash','idempotency_key','mixed_recovery_json'):
                if before.get(name)!=self.get(name):
                    frappe.throw('Dispatch Review opening snapshots are immutable')
            if before.state in ('Completed','Resumed') and before.as_dict()!=self.as_dict():
                frappe.throw('Final Dispatch Reviews are immutable audit records')

    def on_trash(self):
        frappe.throw('Dispatch Reviews are audit records; use controlled resume or settlement')
