import uuid

import frappe
from frappe.model.document import Document
from frappe.utils import cint


class CFGKanbanCard(Document):
    def before_insert(self):
        self.uuid = self.uuid or str(uuid.uuid4())
        self.qr_code = self.qr_code or self.uuid

    def validate(self):
        production_types = ("Physical Unit Card", "Physical Batch Card",
                            "Process Kanban", "Station Kanban")
        service_types = ("Asset Card", "Location Card", "Task Card")
        permanent_access_types = ("Workstation Queue Card",)
        action_types = ("DocType Action Card",)
        behaviour = {
            "Physical Unit Card": "TRAVELLING_CARD",
            "Physical Batch Card": "TRAVELLING_CARD",
            "Process Kanban": "STATION_CARD",
            "Station Kanban": "STATION_CARD",
            "Asset Card": "ASSET_CARD",
            "Location Card": "LOCATION_CARD",
            "Task Card": "TASK_CARD",
            "Workstation Queue Card": "WORKSTATION_QUEUE_CARD",
            "DocType Action Card": "DOCTYPE_ACTION_CARD",
        }
        self.card_behavior = behaviour.get(self.card_type)
        if self.card_type in service_types + permanent_access_types + action_types and self.kanban_master:
            frappe.throw(
                "Permanent identity cards cannot use a Kanban Master. DocType Action cards "
                "also cannot use a Kanban Master. "
                "For Purchase, Transfer, Withdrawal, or production quantity control, use the "
                "corresponding physical or runtime Kanban card."
            )
        if self.card_type in production_types and not self.kanban_master:
            frappe.throw("Kanban Master is required for a production card")
        self._copy_master_context()
        self._validate_crew_requirement()
        self._validate_job_owner_policy(production_types)
        self._validate_job_role_requirements(production_types)
        self._validate_doctype_action_card()
        if self.kanban_master:
            master = frappe.get_cached_doc("CFG Kanban Master", self.kanban_master)
            if (master.control_type in ("Purchase Replenishment", "Transfer", "Withdrawal")
                    and self.card_type not in ("Physical Unit Card", "Physical Batch Card")):
                frappe.throw(
                    f"{master.control_type} Master {master.name} requires a Physical Unit Card "
                    "or Physical Batch Card; it does not use Task Schedule."
                )
        if self.card_type in production_types and self.kanban_qty <= 0:
            frappe.throw("Kanban quantity must be positive")
        if self.card_type in ("Process Kanban", "Station Kanban") and not self.operation:
            frappe.throw("Controlled Operation is required for Process and Station Kanban cards")
        if self.card_type == "Station Kanban" and not self.workstation:
            frappe.throw("Eligible Workstation is required for a Station Kanban card")
        if self.card_type == "Asset Card" and not self.asset:
            frappe.throw("Asset is required for an Asset Card")
        if self.card_type == "Location Card" and not self.location_reference:
            frappe.throw("Location Reference is required for a Location Card")
        if (self.card_type == "Location Card" and
                self.get("location_purpose") in (
                    "Supplier Receiving", "Warehouse Operations", "Dispatch Operations"
                )):
            if not self.current_warehouse:
                frappe.throw("Current Warehouse is required for an operational Location Card")
            warehouse_company = frappe.db.get_value("Warehouse", self.current_warehouse, "company")
            if self.company and warehouse_company != self.company:
                frappe.throw("Location Card company must match its Current Warehouse")
            self.company = warehouse_company
        if self.card_type == "Workstation Queue Card":
            if not self.get("queue_company"):
                frappe.throw("Queue Company is required for a Workstation Queue Card")
            if not self.current_station:
                frappe.throw("Current Station is required for a Workstation Queue Card")
        else:
            self.queue_company = None
        if self.card_type == "Task Card" and not self.task_schedule:
            frappe.throw("Task Schedule is required for a Task Card")
        if self.card_type != "Task Card":
            self.task_schedule = None

    def _validate_job_owner_policy(self, production_types):
        before = None if self.is_new() else self.get_doc_before_save()
        if self.card_type not in production_types:
            self.enforce_job_owner = 0
            self.owner_job_code = None
            return
        if before and before.active_cycle and (
                before.enforce_job_owner != self.enforce_job_owner
                or before.owner_job_code != self.owner_job_code):
            frappe.throw(
                "Job Owner policy cannot change while this Card has an active Cycle. "
                "Complete or cancel the Cycle first."
            )
        if not self.enforce_job_owner:
            self.owner_job_code = None
            return
        control_type = frappe.db.get_value(
            "CFG Kanban Master", self.kanban_master, "control_type"
        ) if self.kanban_master else None
        if control_type != "Production":
            frappe.throw(
                "Job Owner enforcement currently applies to Production Cards. "
                "Leave it disabled for Purchase, Transfer, Withdrawal, and permanent identity Cards."
            )
        if not self.owner_job_code:
            frappe.throw("Required Owner Job Code is mandatory when Job Owner is enforced")
        job_code = frappe.db.get_value(
            "CFG Kanban Job Code", self.owner_job_code,
            ["active", "company"], as_dict=True,
        )
        if not job_code or not job_code.active:
            frappe.throw(f"Job Code {self.owner_job_code} is not active")
        if job_code.company and self.company and job_code.company != self.company:
            frappe.throw(
                f"Job Code {self.owner_job_code} belongs to {job_code.company}, "
                f"not Card company {self.company}"
            )

    def _validate_job_role_requirements(self, production_types):
        rows = self.get("job_role_requirements") or []
        if self.card_type not in production_types:
            if rows:
                frappe.throw(
                    "Multi-role Job Requirements currently apply only to Production Cards"
                )
            return

        before = None if self.is_new() else self.get_doc_before_save()
        if before and before.active_cycle and (
                self._job_role_requirement_key(before.get("job_role_requirements") or [])
                != self._job_role_requirement_key(rows)):
            frappe.throw(
                "Job Role requirements cannot change while this Card has an active Cycle. "
                "Complete or cancel the Cycle first."
            )

        seen = set()
        owner_candidate_count = 0
        for row in rows:
            if not row.job_code and not row.authority_role:
                frappe.throw(
                    f"Row {row.idx}: select a Required Job Code, Required Authority Role, or both"
                )
            if cint(row.required_count) < 1:
                frappe.throw(f"Row {row.idx}: Required Count must be at least 1")
            if bool(row.skill) != bool(row.minimum_competency_level):
                frappe.throw(
                    f"Row {row.idx}: Required Skill and Minimum Competency must be set together"
                )
            if row.require_independent_authorization and row.allow_supervised_trainee:
                frappe.throw(
                    f"Row {row.idx}: an independently authorized role cannot also allow a "
                    "supervised trainee"
                )
            if row.may_own_cycle:
                owner_candidate_count += 1
                if not row.job_code:
                    frappe.throw(
                        f"Row {row.idx}: a role that May Own Cycle requires a Job Code"
                    )
                if self.enforce_job_owner and row.job_code != self.owner_job_code:
                    frappe.throw(
                        f"Row {row.idx}: the Cycle owner role must use Required Owner Job Code "
                        f"{self.owner_job_code}"
                    )
            if row.separate_approver_required and row.assignment_type not in (
                    "Supervisor / Mentor", "Verifier"):
                frappe.throw(
                    f"Row {row.idx}: Separate Approver applies only to Supervisor / Mentor "
                    "or Verifier assignments"
                )
            self._assert_active_job_role_reference(row)
            key = (
                row.assignment_type,
                row.job_code,
                row.authority_role,
                row.skill,
            )
            if key in seen:
                frappe.throw(f"Row {row.idx}: duplicate Card Job Role requirement")
            seen.add(key)
        if owner_candidate_count > 1:
            frappe.throw("Only one Card Job Role requirement may be marked May Own Cycle")

    def _assert_active_job_role_reference(self, row):
        if row.job_code:
            job_code = frappe.db.get_value(
                "CFG Kanban Job Code", row.job_code,
                ["active", "company"], as_dict=True,
            )
            if not job_code or not job_code.active:
                frappe.throw(f"Row {row.idx}: Job Code {row.job_code} is not active")
            if job_code.company and self.company and job_code.company != self.company:
                frappe.throw(
                    f"Row {row.idx}: Job Code {row.job_code} belongs to {job_code.company}, "
                    f"not Card company {self.company}"
                )
        if row.authority_role:
            role = frappe.db.get_value(
                "CFG Kanban Authority Role", row.authority_role,
                ["active", "company"], as_dict=True,
            )
            if not role or not role.active:
                frappe.throw(
                    f"Row {row.idx}: Authority Role {row.authority_role} is not active"
                )
            if role.company and self.company and role.company != self.company:
                frappe.throw(
                    f"Row {row.idx}: Authority Role {row.authority_role} belongs to "
                    f"{role.company}, not Card company {self.company}"
                )

    @staticmethod
    def _job_role_requirement_key(rows):
        fields = (
            "assignment_type", "job_code", "authority_role", "required_count",
            "skill", "minimum_competency_level", "require_independent_authorization",
            "allow_supervised_trainee", "require_active_presence", "may_own_cycle",
            "separate_approver_required",
        )
        return tuple(tuple(row.get(fieldname) or 0 for fieldname in fields) for row in rows)

    def _validate_crew_requirement(self):
        if self.card_type not in ("Process Kanban", "Station Kanban"):
            self.crew_requirement_profile = None
            return
        if not self.crew_requirement_profile:
            return
        from cfg_kanban.services.crew_policy import assert_approved_crew_profile

        assert_approved_crew_profile(self.crew_requirement_profile, self.company)

    def _validate_doctype_action_card(self):
        before = None if self.is_new() else self.get_doc_before_save()
        is_action_card = self.card_type == "DocType Action Card"
        was_action_card = bool(before and before.card_type == "DocType Action Card")

        if before and is_action_card != was_action_card:
            frappe.throw(
                "A saved Card cannot be converted to or from a DocType Action Card. "
                "Create a new card identity instead."
            )
        if before and is_action_card and (
                before.doctype_action_profile != self.doctype_action_profile):
            frappe.throw(
                "DocType Action Profile is immutable after the Card is created. "
                "Use Replace Card Identity when a different physical card is required, or "
                "create a new DocType Action Card for a different profile."
            )
        if not is_action_card:
            self.doctype_action_profile = None
            return

        if self.is_new() and not self.flags.get("doctype_action_replacement"):
            from cfg_kanban.services.doctype_actions import require_configuration_role
            require_configuration_role()
        if not self.doctype_action_profile:
            frappe.throw("DocType Action Profile is required for a DocType Action Card")
        if self.active_cycle:
            frappe.throw(
                "DocType Action Cards cannot have a Kanban Cycle. Cancel or reconcile the "
                "incorrect production linkage before using this card."
            )

        if self.is_new() or self.active:
            from cfg_kanban.services.doctype_actions import (
                assert_direct_card_profile_compatible,
                executable_profile_snapshot,
            )
            profile, _snapshot, _mapping_hash = executable_profile_snapshot(
                self.doctype_action_profile
            )
            assert_direct_card_profile_compatible(_snapshot)
        else:
            profile = frappe.get_doc(
                "CFG Kanban DocType Action Profile", self.doctype_action_profile
            )

        # The card is a reusable non-production identity. Individual Action Runs
        # pin the exact profile revision and own all execution lifecycle state.
        self.company = profile.company
        self.kanban_qty = 0
        self.asset = None
        self.location_reference = None
        self.location_purpose = None
        self.task_schedule = None
        self.queue_company = None
        self.current_station = None
        self.current_warehouse = None

    def _copy_master_context(self):
        if not self.kanban_master:
            if self.is_new():
                self.company = None
            self.item_code = None
            self.stock_uom = None
            self.source_warehouse = None
            self.destination_warehouse = None
            self.operation = None
            self.workstation = None
            self.handoff_mode = None
            self.crew_requirement_profile = None
            return
        master = frappe.get_cached_doc("CFG Kanban Master", self.kanban_master)
        before = None if self.is_new() else self.get_doc_before_save()
        if before and before.company:
            if self.company != before.company:
                frappe.throw("Company Snapshot is immutable after the Card is created")
            self.company = before.company
        else:
            self.company = master.company
        self.item_code = master.item_code
        self.stock_uom = master.stock_uom
        self.source_warehouse = master.source_warehouse
        self.destination_warehouse = master.destination_warehouse
        self.current_warehouse = self.current_warehouse or master.destination_warehouse
        if not self.kanban_qty:
            self.kanban_qty = master.replenishment_qty
        if not self.operation:
            self.workstation = None
            self.handoff_mode = None
            return
        profile = next((row for row in master.operation_profiles if row.operation == self.operation), None)
        if not profile:
            frappe.throw(f"Operation {self.operation} is not configured in Kanban Master {master.name}")
        if self.card_type == "Station Kanban":
            self.workstation = self.workstation or profile.workstation
            self.current_station = self.current_station or self.workstation
        else:
            self.workstation = None
            self.current_station = None
        self.handoff_mode = profile.handoff_mode
