import frappe
from frappe.model.document import Document

from cfg_kanban.services.logistics_foundation import (
    validate_price_list_mode,
    validate_warehouse_company,
)


class CFGKanbanLogisticsRoute(Document):
    def validate(self):
        if self.source_company == self.destination_company:
            frappe.throw("Source Company and Destination Company must be different")
        validate_warehouse_company(self.source_warehouse, self.source_company, "Source Warehouse")
        validate_warehouse_company(self.transit_warehouse, self.source_company, "Transit Warehouse")
        validate_warehouse_company(
            self.destination_warehouse, self.destination_company, "Destination Warehouse"
        )
        validate_price_list_mode(self.selling_price_list, "selling", "Selling Price List")
        validate_price_list_mode(self.buying_price_list, "buying", "Buying Price List")
        self._validate_internal_party("Customer", self.internal_customer, self.destination_company)
        self._validate_internal_party("Supplier", self.internal_supplier, self.source_company)

    @staticmethod
    def _validate_internal_party(doctype, party, expected_company):
        if not party:
            return
        meta = frappe.get_meta(doctype)
        if not meta.has_field("represents_company"):
            return
        represented_company = frappe.db.get_value(doctype, party, "represents_company")
        if represented_company and represented_company != expected_company:
            frappe.throw(
                f"{doctype} {party} represents {represented_company}, not {expected_company}"
            )
