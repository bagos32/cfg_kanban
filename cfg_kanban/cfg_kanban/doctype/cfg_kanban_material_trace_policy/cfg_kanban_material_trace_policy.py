import frappe
from frappe.model.document import Document


class CFGKanbanMaterialTracePolicy(Document):
    def validate(self):
        duplicate = frappe.db.get_value(
            "CFG Kanban Material Trace Policy",
            {"company": self.company, "item_code": self.item_code, "name": ["!=", self.name]},
            "name",
        )
        if duplicate:
            frappe.throw(
                f"Material Trace Policy {duplicate} already controls Item {self.item_code} "
                f"for Company {self.company}"
            )
        policies = (
            self.receiving_tag_policy,
            self.production_input_tag_policy,
            self.production_output_tag_policy,
        )
        if self.trace_level == "Exact Handling Unit" and not any(
            value in ("Optional Physical Tag", "Required Physical Tag") for value in policies
        ):
            frappe.throw(
                "Exact Handling Unit trace requires an Optional or Required Physical Tag "
                "at one or more stages"
            )
