import uuid

import frappe
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from cfg_kanban.services.logistics_foundation import (
    post_quantity_event,
    validate_physical_code_namespace,
)
from cfg_kanban.services.physical_identity import normalize_physical_code
from cfg_kanban.services.tag_registry import materialize_tag_family_for_code


class CFGKanbanHandlingUnit(Document):
    def before_insert(self):
        self.tag_kind = self.tag_kind or "Main Stock Tag"
        try:
            self.handling_unit_id = normalize_physical_code(self.handling_unit_id)
        except ValueError as exc:
            frappe.throw(str(exc))
        self._materialize_range_family()
        if self.tag_kind != "Reusable Container" and not self.tag_family:
            frappe.throw(
                "A Stock Tag must be registered in an exact Tag Family or covered by an "
                "active Tag Range Registry"
            )
        validate_physical_code_namespace(
            self.handling_unit_id, "Handling Unit", tag_family=self.tag_family
        )
        self._bind_tag_identity()
        self.opaque_token = self.opaque_token or str(uuid.uuid4())
        if not self.handling_unit_id:
            self.handling_unit_id = self.name
        self._copy_parent_context()
        self._copy_cycle_context()
        self.identity_state = self.identity_state or "Active"
        self.movement_state = self.movement_state or "At Source"
        self.quality_state = self.quality_state or "Released"
        self.packed_on = self.packed_on or now_datetime()
        self.original_qty = flt(self.original_qty or self.qty)
        self.current_qty = 0
        self.reserved_qty = 0
        self.available_qty = 0

    def after_insert(self):
        if getattr(self.flags, "tag_identity_row", None):
            frappe.db.set_value(
                "CFG Kanban Tag Identity",
                self.flags.tag_identity_row,
                {"state": "Activated", "handling_unit": self.name},
                update_modified=False,
            )
        if self.tag_kind == "Reusable Container" or getattr(
            self.flags, "skip_initial_ledger", False
        ):
            return
        event_type = "Split" if self.tag_kind == "Child Stock Tag" else "Pack / Activate"
        post_quantity_event(
            event_type=event_type,
            qty=self.qty,
            stock_uom=self.stock_uom,
            idempotency_key=f"handling-unit-activation:{self.name}",
            source_handling_unit=self.parent_handling_unit,
            destination_handling_unit=self.name,
            item_code=self.item_code,
            batch_no=self.batch_no,
            source_company=self.inventory_company if self.parent_handling_unit else None,
            destination_company=self.inventory_company,
            source_warehouse=self.current_warehouse if self.parent_handling_unit else None,
            destination_warehouse=self.current_warehouse,
            reference_doctype=self.origin_reference_doctype or self.doctype,
            reference_name=self.origin_reference_name or self.name,
            reason=(getattr(self.flags, "activation_reason", None)
                    or ("Initial tag activation" if event_type == "Pack / Activate"
                        else "Child tag split")),
        )

    def validate(self):
        self._copy_parent_context()
        self._copy_cycle_context()
        # Frappe assigns autonames after before_insert and before validate. Set the
        # self-referencing root here so a new main tag never persists a blank root.
        if self.tag_kind == "Main Stock Tag" and not self.root_handling_unit:
            self.root_handling_unit = self.name
        self._validate_immutable_identity()
        self._validate_reusable_policy_change()
        if self.tag_kind != "Reusable Container" and (not self.item_code or not self.stock_uom):
            frappe.throw("Item and Stock UOM are required for a Stock Tag")
        if self.tag_kind != "Reusable Container" and (
            not self.inventory_company or not self.current_warehouse
        ):
            frappe.throw(
                "Inventory Company and Current Warehouse are required for a Stock Tag. "
                "Current Warehouse is the present ERPNext source location, not its future destination."
            )
        if self.tag_kind != "Reusable Container" and flt(self.qty) <= 0:
            frappe.throw("Handling-unit quantity must be positive")
        if self.tag_kind == "Reusable Container" and flt(self.qty):
            frappe.throw(
                "Reusable containers have no combined Item quantity; load complete Stock Tags "
                "through the Logistics panel"
            )
        if (flt(self.sequence_no) <= 0 or flt(self.total_units) <= 0
                or flt(self.sequence_no) > flt(self.total_units)):
            frappe.throw("Handling-unit sequence must be between 1 and the total number of units")
        if self.kanban_card and self.opaque_token == frappe.db.get_value(
            "CFG Kanban Card", self.kanban_card, "uuid"
        ):
            frappe.throw("Handling-unit token must be different from the reusable card token")
        if self.tag_kind == "Child Stock Tag":
            if not self.tag_family or not self.parent_handling_unit or flt(self.child_index) <= 0:
                frappe.throw("Child Stock Tags require a Tag Family, parent tag, and child index")
            self._validate_child_parent()
            if frappe.db.exists(
                "CFG Kanban Handling Unit Serial",
                {"handling_unit": self.parent_handling_unit, "state": "Active"},
            ) and not getattr(self.flags, "controlled_serial_split", False):
                frappe.throw(
                    "Serial-controlled parent tags require a controlled serial split; "
                    "use Split Exact Serials to Child Tag on the parent Handling Unit"
                )
        elif self.parent_handling_unit:
            frappe.throw("Only a Child Stock Tag may have a Parent Handling Unit")
        if self.tag_kind == "Reusable Container" and (
            self.tag_family or self.root_handling_unit or flt(self.child_index)
        ):
            frappe.throw("A Reusable Container cannot belong to a detachable Tag Family")
        self.current_qty = flt(self.current_qty)
        self.reserved_qty = flt(self.reserved_qty)
        if self.current_qty < 0 or self.reserved_qty < 0:
            frappe.throw("Current and reserved quantities cannot be negative")
        if self.reserved_qty > self.current_qty:
            frappe.throw("Reserved quantity cannot exceed current quantity")
        self.available_qty = self.current_qty - self.reserved_qty
        if self.current_warehouse:
            warehouse_company = frappe.db.get_value("Warehouse", self.current_warehouse, "company")
            if self.inventory_company and warehouse_company != self.inventory_company:
                frappe.throw(
                    f"Current Warehouse {self.current_warehouse} belongs to {warehouse_company}, "
                    f"not {self.inventory_company}"
                )
            self.inventory_company = self.inventory_company or warehouse_company

    def _validate_immutable_identity(self):
        if self.is_new():
            return
        has_ledger = frappe.db.exists(
            "CFG Kanban Handling Unit Quantity Ledger", {"source_handling_unit": self.name}
        ) or frappe.db.exists(
            "CFG Kanban Handling Unit Quantity Ledger", {"destination_handling_unit": self.name}
        )
        if not has_ledger:
            return
        before = self.get_doc_before_save()
        if not before:
            return
        immutable = (
            "handling_unit_id", "opaque_token", "tag_kind", "tag_range_registry", "tag_family",
            "parent_handling_unit", "root_handling_unit", "child_index", "item_code",
            "batch_no", "stock_uom", "packed_on", "expiry_date", "original_qty", "qty",
            "inventory_company", "current_warehouse", "origin_reference_doctype",
            "origin_reference_name", "origin_reference_row", "activation_key",
        )
        for fieldname in immutable:
            if before.get(fieldname) != self.get(fieldname):
                frappe.throw(f"{self.meta.get_label(fieldname)} is immutable after ledger activation")

    def _validate_reusable_policy_change(self):
        if self.is_new() or self.tag_kind != "Reusable Container":
            return
        before = self.get_doc_before_save()
        if not before or before.allow_mixed_content == self.allow_mixed_content:
            return
        if frappe.db.exists(
            "CFG Kanban Container Content",
            {"container_handling_unit": self.name, "state": "Loaded"},
        ):
            frappe.throw("Allow Mixed Item / Batch Content cannot change while the container is loaded")

    def _bind_tag_identity(self):
        if not self.tag_family or not self.handling_unit_id:
            return
        identity = frappe.db.get_value(
            "CFG Kanban Tag Identity",
            {"parent": self.tag_family, "visible_code": self.handling_unit_id},
            ["name", "tag_role", "child_index", "opaque_token", "state", "handling_unit"],
            as_dict=True,
        )
        if not identity:
            frappe.throw(
                f"Handling Unit ID {self.handling_unit_id} is not registered in Tag Family {self.tag_family}"
            )
        if identity.state != "Unused" or identity.handling_unit:
            frappe.throw(f"Tag identity {self.handling_unit_id} has already been activated")
        self.tag_kind = "Main Stock Tag" if identity.tag_role == "Main" else "Child Stock Tag"
        self.child_index = identity.child_index
        self.opaque_token = identity.opaque_token
        self.inventory_company = self.inventory_company or frappe.db.get_value(
            "CFG Kanban Tag Family", self.tag_family, "issued_company"
        )
        self.tag_range_registry = self.tag_range_registry or frappe.db.get_value(
            "CFG Kanban Tag Family", self.tag_family, "range_registry"
        )
        self.flags.tag_identity_row = identity.name

    def _materialize_range_family(self):
        if self.tag_kind == "Reusable Container":
            return
        if self.tag_family and frappe.db.exists("CFG Kanban Tag Family", self.tag_family):
            self.tag_range_registry = self.tag_range_registry or frappe.db.get_value(
                "CFG Kanban Tag Family", self.tag_family, "range_registry"
            )
            return
        family = materialize_tag_family_for_code(
            self.handling_unit_id, expected_registry=self.tag_range_registry or None
        )
        if not family:
            return
        if self.tag_family and self.tag_family != family.name:
            frappe.throw(
                f"Printed code {self.handling_unit_id} belongs to Tag Family {family.name}, "
                f"not {self.tag_family}"
            )
        self.tag_family = family.name
        self.tag_range_registry = family.range_registry

    def _copy_parent_context(self):
        if not self.parent_handling_unit:
            return
        parent = frappe.get_cached_doc("CFG Kanban Handling Unit", self.parent_handling_unit)
        self.tag_family = self.tag_family or parent.tag_family
        self.root_handling_unit = self.root_handling_unit or parent.root_handling_unit or parent.name
        self.item_code = self.item_code or parent.item_code
        self.short_description = self.short_description or parent.short_description
        self.stock_uom = self.stock_uom or parent.stock_uom
        self.batch_no = self.batch_no or parent.batch_no
        self.work_order = self.work_order or parent.work_order
        self.kanban_cycle = self.kanban_cycle or parent.kanban_cycle
        self.kanban_card = self.kanban_card or parent.kanban_card
        self.inventory_company = self.inventory_company or parent.inventory_company
        self.current_warehouse = self.current_warehouse or parent.current_warehouse
        self.packed_on = self.packed_on or parent.packed_on
        self.expiry_date = self.expiry_date or parent.expiry_date

    def _validate_child_parent(self):
        parent = frappe.get_cached_doc("CFG Kanban Handling Unit", self.parent_handling_unit)
        if parent.identity_state != "Active":
            frappe.throw("A Child Stock Tag can only split an active parent tag")
        if parent.tag_kind != "Main Stock Tag":
            frappe.throw("A detachable Child Stock Tag must split from its main Stock Tag")
        if parent.tag_family != self.tag_family:
            frappe.throw("Child Stock Tag and parent must belong to the same Tag Family")
        for fieldname in ("item_code", "batch_no", "stock_uom", "inventory_company"):
            if self.get(fieldname) != parent.get(fieldname):
                frappe.throw(
                    f"Child {self.meta.get_label(fieldname)} must match its parent tag"
                )

    def _copy_cycle_context(self):
        if not self.kanban_cycle:
            return
        cycle = frappe.get_doc("CFG Kanban Cycle", self.kanban_cycle)
        self.kanban_card = self.kanban_card or cycle.kanban_card
        self.item_code = self.item_code or cycle.item_code
        self.stock_uom = self.stock_uom or cycle.stock_uom
        self.batch_no = self.batch_no or cycle.batch_no
        self.work_order = self.work_order or cycle.work_order
        self.inventory_company = self.inventory_company or cycle.company
        if not self.short_description and self.item_code:
            self.short_description = frappe.db.get_value("Item", self.item_code, "item_name")
        if self.current_operation:
            master = cycle.kanban_master
            profile = frappe.db.get_value("CFG Kanban Operation Profile", {
                "parent": master, "parenttype": "CFG Kanban Master",
                "operation": self.current_operation,
            }, ["workstation", "destination_operation"], as_dict=True)
            if not profile:
                frappe.throw(f"Operation {self.current_operation} is not configured in cycle Master {master}")
            self.source_location = self.source_location or profile.workstation
            destination = None
            if profile.destination_operation:
                destination = frappe.db.get_value("CFG Kanban Operation Profile", {
                    "parent": master, "parenttype": "CFG Kanban Master",
                    "operation": profile.destination_operation,
                }, "workstation")
            self.destination_location = self.destination_location or destination or cycle.destination_warehouse
