import frappe
from frappe.model.document import Document
from frappe.utils import cint


class CFGKanbanDispatchProfile(Document):
    """Manager policy resolved at a permanent Dispatch Point and snapshotted into E2 Plans."""

    def validate(self):
        self.route_sequence_scope = self.get('route_sequence_scope') or 'Per Dispatch Plan'
        self.customer_verification = self.get('customer_verification') or 'Require Customer Site QR'
        if self.route_sequence_scope not in ('Per Dispatch Plan','Combined Lorry Trip'):
            frappe.throw('Select a valid Route Sequence Scope')
        if self.customer_verification not in ('Require Customer Site QR','Allow Assigned Stop Selection'):
            frappe.throw('Select a valid Customer Verification policy')
        if self.route_sequence_scope=='Combined Lorry Trip':
            self.route_approval_required=1
        if self.get('route_template'):
            from cfg_kanban.services.route_sheets import template_snapshot
            template_snapshot(self.route_template,self.company)
        if self.fulfilment_mode!='Vehicle Delivery' and (self.route_sequence_scope=='Combined Lorry Trip' or self.get('route_template')):
            frappe.throw('Lorry route templates and combined scope apply to Vehicle Delivery')
        self.stop_sequence_policy = self.get("stop_sequence_policy") or "Flexible Order"
        if self.get("stop_sequence_policy") not in (None, "", "Flexible Order", "Planned Order"):
            frappe.throw("Customer Stop Sequence must be Flexible Order or Planned Order")
        self._validate_priority_and_revision()
        self._validate_dispatch_point()
        self._validate_company_warehouses()
        self._validate_scope()
        self._validate_route()
        self._validate_responsibility()
        self.pickup_acknowledgement = self.get("pickup_acknowledgement") or "Recipient Name"
        if self.pickup_acknowledgement not in ("Recipient Name", "Signature", "Recipient Name and Signature"):
            frappe.throw("Select a valid Pickup Acknowledgement requirement")
        if self.fulfilment_mode in ("Direct Warehouse Delivery", "Customer Pickup"):
            if self.plan_type != "Customer Order":
                frappe.throw("Direct Warehouse Delivery and Customer Pickup require Customer Order Plans")
            from cfg_kanban.services.warehouse_fulfilment import source_warehouse
            source_warehouse(self.source_warehouse, self.company)
            if self.staging_warehouse or self.destination_warehouse:
                frappe.throw("Warehouse fulfilment uses its source directly; clear staging and destination Warehouses")

    def _validate_priority_and_revision(self):
        if cint(self.priority) < 1:
            frappe.throw("Launcher Priority must be at least 1")
        self.revision = cint(self.revision) or 1
        before = None if self.is_new() else self.get_doc_before_save()
        if before and any(before.get(fieldname) != self.get(fieldname) for fieldname in (
                "business_label", "instructions", "dispatch_point", "company",
                "source_warehouse", "plan_type", "fulfilment_mode", "customer_site",
                "territory", "logistics_route", "destination_assignment_policy",
                "destination_warehouse", "staging_warehouse", "transit_warehouse",
                "tag_policy", "stock_rotation_policy", "approval_required",
                "allow_supervisor_override", "auto_submit_stock_transfer",
                "auto_submit_delivery_note", "proof_policy", "dispatch_responsibility",
                "stop_sequence_policy", "delivery_route_reference", "pickup_acknowledgement", "route_sequence_scope", "route_template", "route_approval_required", "customer_verification")):
            self.revision = cint(before.revision) + 1

    def _validate_dispatch_point(self):
        card = frappe.get_doc("CFG Kanban Card", self.dispatch_point)
        if card.card_type != "Location Card" or card.location_purpose != "Dispatch Operations":
            frappe.throw(
                "Dispatch Operations Card must be a Location Card whose Location Purpose is "
                "Dispatch Operations"
            )
        if not card.active or card.blocked:
            frappe.throw("Dispatch Operations Card must be active and unblocked")
        if not card.current_warehouse:
            frappe.throw("Dispatch Operations Card requires a Current Warehouse")
        if self.source_warehouse != card.current_warehouse:
            frappe.throw(
                f"Source Warehouse must match Dispatch Operations Card warehouse "
                f"{card.current_warehouse}"
            )

    def _validate_company_warehouses(self):
        for fieldname, label in (
                ("source_warehouse", "Source Warehouse"),
                ("destination_warehouse", "Fixed Destination Warehouse"),
                ("staging_warehouse", "Staging Warehouse"),
                ("transit_warehouse", "Goods-in-Transit Warehouse")):
            warehouse = self.get(fieldname)
            if not warehouse:
                continue
            warehouse_company = frappe.db.get_value("Warehouse", warehouse, "company")
            if warehouse_company != self.company:
                frappe.throw(f"{label} {warehouse} does not belong to Company {self.company}")
        if (self.destination_assignment_policy == "Fixed"
                and self.fulfilment_mode in ("Vehicle Delivery", "Goods in Transit")
                and not self.destination_warehouse):
            frappe.throw("Fixed vehicle/transit dispatch requires a Fixed Destination Warehouse")
        if self.fulfilment_mode == "Goods in Transit":
            if not self.transit_warehouse:
                frappe.throw("Goods in Transit fulfilment requires a Goods-in-Transit Warehouse")
            if frappe.db.get_value("Warehouse", self.transit_warehouse, "warehouse_type") != "Transit":
                frappe.throw("Goods-in-Transit Warehouse must use ERPNext Warehouse Type Transit")
        elif self.transit_warehouse:
            frappe.throw("Goods-in-Transit Warehouse is valid only for Goods in Transit fulfilment")
        if (self.destination_assignment_policy == "Select at Receipt"
                and self.fulfilment_mode != "Goods in Transit"):
            frappe.throw("Select at Receipt is valid only for Goods in Transit fulfilment")
        if (self.auto_submit_stock_transfer
                and self.fulfilment_mode not in ("Vehicle Delivery", "Goods in Transit")):
            frappe.throw(
                "Auto-submit Stock Transfer is valid only for Vehicle Delivery or Goods in Transit"
            )

    def _validate_scope(self):
        if not self.customer_site:
            return
        site = frappe.db.get_value(
            "CFG Kanban Customer Scan Point", self.customer_site,
            ["active", "selling_company"], as_dict=True,
        )
        if not site or not site.active:
            frappe.throw("Customer Site Scope must be active")
        if site.selling_company != self.company:
            frappe.throw(
                f"Customer Site Scope belongs to {site.selling_company}, not {self.company}"
            )

    def _validate_route(self):
        if not self.logistics_route:
            return
        route = frappe.db.get_value(
            "CFG Kanban Logistics Route", self.logistics_route,
            ["active", "source_company", "source_warehouse"], as_dict=True,
        )
        if not route or not route.active:
            frappe.throw("Logistics Route must be active")
        if route.source_company != self.company or route.source_warehouse != self.source_warehouse:
            frappe.throw(
                "Logistics Route source Company and Warehouse must match the Dispatch Profile"
            )

    def _validate_responsibility(self):
        active = frappe.db.get_value(
            "CFG Kanban Responsibility", self.dispatch_responsibility, "active"
        )
        if not active:
            frappe.throw("Dispatch Responsibility must be active")
