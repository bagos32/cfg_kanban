import frappe
from frappe.model.document import Document


class CFGKanbanCycle(Document):
    def before_insert(self):
        self._snapshot_job_owner_policy()
        self._snapshot_job_role_requirements()

    def validate(self):
        self._validate_job_owner_snapshot()
        self._validate_job_role_snapshot()
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

    def _snapshot_job_role_requirements(self):
        self.set("job_role_requirements_snapshot", [])
        if not self.kanban_card:
            return
        card = frappe.get_doc("CFG Kanban Card", self.kanban_card)
        fields = (
            "assignment_type", "job_code", "authority_role", "required_count",
            "skill", "minimum_competency_level", "require_independent_authorization",
            "allow_supervised_trainee", "require_active_presence", "may_own_cycle",
            "separate_approver_required",
        )
        for source in card.get("job_role_requirements") or []:
            self.append(
                "job_role_requirements_snapshot",
                {fieldname: source.get(fieldname) for fieldname in fields},
            )

    def _validate_job_role_snapshot(self):
        before = None if self.is_new() else self.get_doc_before_save()
        if not before:
            return
        if self._job_role_snapshot_key(before) != self._job_role_snapshot_key(self):
            frappe.throw("Cycle Job Role requirement snapshot is immutable")

    @staticmethod
    def _job_role_snapshot_key(doc):
        fields = (
            "assignment_type", "job_code", "authority_role", "required_count",
            "skill", "minimum_competency_level", "require_independent_authorization",
            "allow_supervised_trainee", "require_active_presence", "may_own_cycle",
            "separate_approver_required",
        )
        return tuple(
            tuple(row.get(fieldname) or 0 for fieldname in fields)
            for row in (doc.get("job_role_requirements_snapshot") or [])
        )
