import frappe
from frappe.model.document import Document
from frappe.utils import cint


class CFGKanbanWIPBinPool(Document):
    def validate(self):
        self.pool_mode = self.pool_mode or "Standard Quantity"
        if self.pool_mode not in ("Standard Quantity", "Loose Multi-Item"):
            frappe.throw("Select a supported WIP Bin Mode")
        if self.pool_mode == "Loose Multi-Item":
            self.loose_consumption_policy = (
                self.loose_consumption_policy or "Accumulate until Work Order close"
            )
            if self.loose_consumption_policy != "Accumulate until Work Order close":
                frappe.throw(
                    "Loose Multi-Item WIP currently posts accumulated use at Work Order close"
                )
            self.require_full_bin_consumption = 0
            self.allow_supervisor_partial_exception = 0
        else:
            self.loose_consumption_policy = None
        self._validate_warehouse()
        self._validate_bins()

    def _validate_warehouse(self):
        warehouse = frappe.db.get_value(
            "Warehouse",
            self.wip_warehouse,
            ["company", "is_group", "disabled"],
            as_dict=True,
        )
        if not warehouse:
            frappe.throw(f"WIP Warehouse {self.wip_warehouse} was not found")
        if warehouse.company != self.company:
            frappe.throw(
                f"WIP Warehouse belongs to {warehouse.company}, not {self.company}"
            )
        if warehouse.is_group or warehouse.disabled:
            frappe.throw("Select an enabled non-group WIP Warehouse")

    def _validate_bins(self):
        bins = [row.reusable_bin for row in self.bins]
        active_bins = [row.reusable_bin for row in self.bins if cint(row.active)]
        if cint(self.active) and not active_bins:
            frappe.throw("An active WIP Bin Pool requires at least one active physical bin")
        if len(bins) != len(set(bins)):
            frappe.throw("A physical WIP Bin can appear only once in a pool")

        for row in self.bins:
            if cint(row.priority) <= 0:
                frappe.throw(f"WIP Bin row {row.idx}: Fill Priority must be positive")
            if not row.workstation:
                frappe.throw(f"WIP Bin row {row.idx}: Workstation is required")
            unit = frappe.db.get_value(
                "CFG Kanban Handling Unit",
                row.reusable_bin,
                [
                    "handling_unit_id", "tag_kind", "reusable_container_role",
                    "identity_state", "quality_state", "inventory_company",
                    "current_warehouse",
                ],
                as_dict=True,
            )
            if not unit:
                frappe.throw(f"WIP Bin row {row.idx}: Handling Unit was not found")
            expected_role = (
                "Loose Multi-Item WIP Bin"
                if self.pool_mode == "Loose Multi-Item"
                else "Standard Quantity WIP Bin"
            )
            if unit.tag_kind != "Reusable Container" or (
                unit.reusable_container_role != expected_role
            ):
                frappe.throw(
                    f"WIP Bin row {row.idx}: {unit.handling_unit_id} must be a Reusable "
                    f"Container with role {expected_role}"
                )
            if unit.identity_state not in ("Active", "Empty"):
                frappe.throw(
                    f"WIP Bin row {row.idx}: {unit.handling_unit_id} is {unit.identity_state}"
                )
            if unit.quality_state != "Released":
                frappe.throw(
                    f"WIP Bin row {row.idx}: {unit.handling_unit_id} is not quality released"
                )
            if unit.inventory_company != self.company:
                frappe.throw(
                    f"WIP Bin row {row.idx}: {unit.handling_unit_id} belongs to "
                    f"{unit.inventory_company}, not {self.company}"
                )
            if unit.current_warehouse != self.wip_warehouse:
                frappe.throw(
                    f"WIP Bin row {row.idx}: {unit.handling_unit_id} is assigned to "
                    f"{unit.current_warehouse}, not {self.wip_warehouse}"
                )
            duplicate_parent = frappe.db.get_value(
                "CFG Kanban WIP Bin Pool Entry",
                {"reusable_bin": row.reusable_bin, "parent": ["!=", self.name]},
                "parent",
            )
            if duplicate_parent:
                frappe.throw(
                    f"WIP Bin {unit.handling_unit_id} already belongs to pool {duplicate_parent}"
                )
