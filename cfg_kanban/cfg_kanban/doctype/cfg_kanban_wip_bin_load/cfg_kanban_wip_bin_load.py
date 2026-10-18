import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt


ACTIVE_STATUSES = (
    "Reserved", "Transfer Draft", "Ready", "In Use", "Consumption Draft",
)
IDENTITY_FIELDS = (
    "reusable_bin", "wip_bin_pool", "company", "item_code", "batch_no",
    "standard_qty", "actual_qty", "stock_uom", "partial_exception",
    "exception_reason", "approved_by", "approved_by_operator", "exception_approved_on",
    "kanban_master", "kanban_cycle", "work_order",
    "job_card", "process_execution", "operation", "workstation",
    "source_handling_unit", "source_warehouse", "wip_warehouse",
    "transfer_stock_entry", "transfer_stock_entry_detail", "idempotency_key",
)
TOLERANCE = 0.000001


class CFGKanbanWIPBinLoad(Document):
    def validate(self):
        self._validate_quantity()
        self._validate_context()
        self._validate_active_bin_exclusivity()
        self._validate_immutable_identity()

    def on_trash(self):
        frappe.throw("WIP Bin Load records are immutable; use controlled reversal or cancellation")

    def _validate_quantity(self):
        if flt(self.standard_qty) <= 0 or flt(self.actual_qty) <= 0:
            frappe.throw("Standard and actual WIP Bin quantities must be positive")
        if flt(self.actual_qty) > flt(self.standard_qty) + TOLERANCE:
            frappe.throw("A fixed-capacity WIP Bin cannot be loaded above its Standard Full-bin Qty")
        if abs(flt(self.actual_qty) - flt(self.standard_qty)) <= TOLERANCE:
            self.partial_exception = 0
            self.exception_reason = None
            self.approved_by = None
            self.approved_by_operator = None
            self.exception_approved_on = None
            return
        if not cint(self.partial_exception):
            frappe.throw("Actual WIP Bin quantity must equal its Standard Full-bin Qty")
        if (not self.exception_reason or not self.approved_by
                or not self.approved_by_operator or not self.exception_approved_on):
            frappe.throw(
                "A partial-bin exception requires a reason, approving supervisor, "
                "terminal user, and approval time"
            )
        if not frappe.db.get_value(
            "CFG Kanban WIP Bin Pool", self.wip_bin_pool,
            "allow_supervisor_partial_exception",
        ):
            frappe.throw("This WIP Bin Pool does not allow partial-bin exceptions")

    def _validate_context(self):
        unit = frappe.db.get_value(
            "CFG Kanban Handling Unit", self.reusable_bin,
            ["tag_kind", "reusable_container_role", "inventory_company",
             "current_warehouse", "identity_state", "quality_state", "wip_bin_state"],
            as_dict=True,
        )
        if not unit or unit.tag_kind != "Reusable Container" or (
            unit.reusable_container_role != "Standard Quantity WIP Bin"
        ):
            frappe.throw("Select a Reusable Container with role Standard Quantity WIP Bin")
        if unit.identity_state != "Active" or unit.quality_state != "Released":
            frappe.throw("The reusable WIP Bin must be active and quality released")
        if unit.inventory_company != self.company or unit.current_warehouse != self.wip_warehouse:
            frappe.throw("WIP Bin Company and Warehouse do not match the load snapshot")
        if self.is_new() and unit.wip_bin_state != "Empty":
            frappe.throw(f"Reusable WIP Bin is {unit.wip_bin_state or 'not Empty'}")

        pool = frappe.db.get_value(
            "CFG Kanban WIP Bin Pool", self.wip_bin_pool,
            ["active", "company", "operation", "wip_warehouse"], as_dict=True,
        )
        if not pool or not pool.active:
            frappe.throw("Select an active WIP Bin Pool")
        if (pool.company != self.company or pool.operation != self.operation
                or pool.wip_warehouse != self.wip_warehouse):
            frappe.throw("WIP Bin Pool does not match Company, Operation, or WIP Warehouse")
        if not frappe.db.exists("CFG Kanban WIP Bin Pool Entry", {
            "parent": self.wip_bin_pool,
            "parenttype": "CFG Kanban WIP Bin Pool",
            "reusable_bin": self.reusable_bin,
            "workstation": self.workstation,
            "active": 1,
        }):
            frappe.throw("WIP Bin is not approved for this Pool and Workstation")

        cycle = frappe.db.get_value(
            "CFG Kanban Cycle", self.kanban_cycle,
            ["kanban_master", "work_order"], as_dict=True,
        )
        job = frappe.db.get_value(
            "Job Card", self.job_card,
            ["work_order", "operation", "workstation", "docstatus"], as_dict=True,
        )
        if not cycle or cycle.kanban_master != self.kanban_master:
            frappe.throw("WIP Bin Load does not match its Kanban Cycle and Master")
        if cycle.work_order and cycle.work_order != self.work_order:
            frappe.throw("WIP Bin Load Work Order does not match the Kanban Cycle")
        if (not job or job.docstatus == 2 or job.work_order != self.work_order
                or job.operation != self.operation or job.workstation != self.workstation):
            frappe.throw("WIP Bin Load does not match the active Job Card operation/workstation")
        rule = frappe.db.get_value("CFG Kanban Material Flow Rule", {
            "parent": self.kanban_master,
            "parenttype": "CFG Kanban Master",
            "item_code": self.item_code,
            "operation": self.operation,
            "wip_presentation_method": "Standard Quantity Reusable WIP Bin",
            "wip_bin_pool": self.wip_bin_pool,
        }, ["standard_bin_qty", "stock_uom"], as_dict=True)
        if not rule:
            frappe.throw("Item is not configured for this WIP Bin Pool on the Kanban Master")
        if (abs(flt(rule.standard_bin_qty) - flt(self.standard_qty)) > TOLERANCE
                or rule.stock_uom != self.stock_uom):
            frappe.throw("WIP Bin standard quantity/UOM does not match the Kanban Master")

    def _validate_active_bin_exclusivity(self):
        if self.status not in ACTIVE_STATUSES:
            return
        duplicate = frappe.db.get_value("CFG Kanban WIP Bin Load", {
            "reusable_bin": self.reusable_bin,
            "status": ["in", ACTIVE_STATUSES],
            "name": ["!=", self.name],
        }, "name")
        if duplicate:
            frappe.throw(f"WIP Bin already has active Load {duplicate}")

    def _validate_immutable_identity(self):
        if self.is_new():
            return
        previous = self.get_doc_before_save()
        if not previous:
            return
        changed = [field for field in IDENTITY_FIELDS if previous.get(field) != self.get(field)]
        if changed:
            frappe.throw("WIP Bin Load identity cannot change after creation: " + ", ".join(changed))
