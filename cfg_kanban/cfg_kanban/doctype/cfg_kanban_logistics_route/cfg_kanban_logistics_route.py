import frappe
from frappe.model.document import Document

from cfg_kanban.services.logistics_foundation import (
    validate_price_list_mode,
    validate_warehouse_company,
)


class CFGKanbanLogisticsRoute(Document):
    def validate(self):
        self.route_type = self.route_type or "Intercompany Handover"
        internal = self.route_type == "Internal Warehouse Transfer"
        if internal and self.source_company != self.destination_company:
            frappe.throw("Internal Warehouse Transfer requires the same source and destination Company")
        if not internal and self.source_company == self.destination_company:
            frappe.throw("Intercompany Handover requires different source and destination Companies")
        validate_warehouse_company(self.source_warehouse, self.source_company, "Source Warehouse")
        if self.transit_warehouse:
            validate_warehouse_company(self.transit_warehouse, self.source_company, "Transit Warehouse")
        validate_warehouse_company(
            self.destination_warehouse, self.destination_company, "Destination Warehouse"
        )
        if self.source_warehouse == self.destination_warehouse:
            frappe.throw("Source Warehouse and Destination Warehouse must be different")
        if internal:
            if self.internal_transfer_mode == "Goods in Transit" and not self.transit_warehouse:
                frappe.throw("Transit Warehouse is required for Goods in Transit")
            if (self.internal_transfer_mode == "Goods in Transit"
                    and frappe.db.get_value("Warehouse", self.transit_warehouse,
                                            "warehouse_type") != "Transit"):
                frappe.throw("Goods in Transit requires a Warehouse whose Warehouse Type is Transit")
            if self.transit_warehouse in (self.source_warehouse, self.destination_warehouse):
                frappe.throw("Transit Warehouse must differ from source and destination Warehouses")
            self.internal_customer = None
            self.internal_supplier = None
            self.selling_price_list = None
            self.buying_price_list = None
            self.billing_frequency = None
            return
        for fieldname, label in (
            ("internal_customer", "Internal Customer"),
            ("internal_supplier", "Internal Supplier"),
            ("selling_price_list", "Selling Price List"),
            ("buying_price_list", "Buying Price List"),
        ):
            if not self.get(fieldname):
                frappe.throw(f"{label} is required for Intercompany Handover")
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
