import frappe
from frappe.model.document import Document

from cfg_kanban.services.physical_identity import (
    format_tag_family_code,
    validate_tag_range_definition,
)


CONTROL_FIELDS = (
    "prefix", "start_number", "end_number", "number_width", "child_separator",
    "child_count", "issued_company",
)


class CFGKanbanTagRangeRegistry(Document):
    def validate(self):
        try:
            controls = validate_tag_range_definition(
                self.prefix, self.start_number, self.end_number, self.number_width,
                self.child_separator, self.child_count,
            )
        except ValueError as exc:
            frappe.throw(str(exc))
        for fieldname, value in controls.items():
            self.set(fieldname, value)
        self._set_calculated_fields()
        self._protect_used_definition()
        self._validate_registry_overlap()
        self.materialized_count = frappe.db.count(
            "CFG Kanban Tag Family", {"range_registry": self.name}
        ) if not self.is_new() else 0

    def on_trash(self):
        if frappe.db.exists("CFG Kanban Tag Family", {"range_registry": self.name}):
            frappe.throw(
                "A Tag Range Registry with materialized Tag Families cannot be deleted. "
                "Deactivate it instead."
            )

    def _set_calculated_fields(self):
        self.first_main_code = format_tag_family_code(
            self.prefix, self.start_number, self.number_width
        )
        self.last_main_code = format_tag_family_code(
            self.prefix, self.end_number, self.number_width
        )
        self.total_main_tags = self.end_number - self.start_number + 1
        self.potential_identity_count = self.total_main_tags * (self.child_count + 1)

    def _protect_used_definition(self):
        if self.is_new() or not frappe.db.exists(
            "CFG Kanban Tag Family", {"range_registry": self.name}
        ):
            return
        before = self.get_doc_before_save()
        if not before:
            return
        for fieldname in CONTROL_FIELDS:
            before_value = before.get(fieldname)
            current_value = self.get(fieldname)
            if fieldname == "child_separator":
                before_value = before_value or "-"
                current_value = current_value or "-"
            if before_value != current_value:
                frappe.throw(
                    f"{self.meta.get_label(fieldname)} cannot change after the first Tag "
                    "Family is materialized. Deactivate this registry and create a new range."
                )

    def _validate_registry_overlap(self):
        registries = frappe.get_all(
            "CFG Kanban Tag Range Registry",
            filters={"name": ["!=", self.name or ""]},
            fields=["name", "prefix", "start_number", "end_number", "number_width"],
            limit_page_length=0,
        )
        for other in registries:
            if self.prefix == other.prefix:
                if int(self.number_width) != int(other.number_width):
                    continue
                overlaps = not (
                    int(self.end_number) < int(other.start_number)
                    or int(self.start_number) > int(other.end_number)
                )
                if overlaps:
                    frappe.throw(
                        f"This number range overlaps Tag Range Registry {other.name}"
                    )
                continue
            if self.prefix.startswith(other.prefix) or other.prefix.startswith(self.prefix):
                frappe.throw(
                    f"Printed Prefix overlaps the namespace of Tag Range Registry {other.name}. "
                    "Use non-nested issuer prefixes to keep scans unambiguous."
                )
