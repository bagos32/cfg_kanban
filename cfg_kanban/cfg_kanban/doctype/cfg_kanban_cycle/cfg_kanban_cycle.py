import frappe
from frappe.model.document import Document


class CFGKanbanCycle(Document):
    def before_insert(self):
        self._snapshot_job_owner_policy()

    def validate(self):
        self._validate_job_owner_snapshot()
        if not self.kanban_master:
            return
        before = None if self.is_new() else self.get_doc_before_save()
        if before and before.company:
            if self.company != before.company:
                frappe.throw("Company Snapshot is immutable after the Cycle is created")
            self.company = before.company
            return
        master_company = frappe.db.get_value("CFG Kanban Master", self.kanban_master, "company")
        if self.company and self.company != master_company:
            frappe.throw(
                f"Cycle Company {self.company} does not match Kanban Master Company {master_company}"
            )
        self.company = master_company

    def _snapshot_job_owner_policy(self):
        self.enforce_job_owner = 0
        self.owner_job_code = None
        if not self.kanban_card:
            return
        policy = frappe.db.get_value(
            "CFG Kanban Card", self.kanban_card,
            ["enforce_job_owner", "owner_job_code"], as_dict=True,
        )
        if not policy:
            return
        self.enforce_job_owner = policy.enforce_job_owner or 0
        self.owner_job_code = policy.owner_job_code if policy.enforce_job_owner else None

    def _validate_job_owner_snapshot(self):
        before = None if self.is_new() else self.get_doc_before_save()
        if before and (
                before.enforce_job_owner != self.enforce_job_owner
                or before.owner_job_code != self.owner_job_code):
            frappe.throw("Cycle Job Owner policy snapshot is immutable")
        if self.enforce_job_owner and not self.owner_job_code:
            frappe.throw("An owner-enforced Cycle requires a Job Code snapshot")
