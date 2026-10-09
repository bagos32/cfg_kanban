import json
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1] / "cfg_kanban" / "doctype"
APP_ROOT = Path(__file__).resolve().parents[1]


class TestDocTypeSchema(TestCase):
    def _schemas(self):
        for path in ROOT.glob("*/*.json"):
            yield path, json.loads(path.read_text())

    def test_search_fields_fit_frappe_schema_limit(self):
        for path, schema in self._schemas():
            with self.subTest(doctype=schema.get("name"), path=path):
                self.assertLessEqual(len(schema.get("search_fields") or ""), 140)

    def test_patch_file_declares_both_frappe_migration_phases(self):
        patches = (APP_ROOT / "patches.txt").read_text()
        self.assertIn("[pre_model_sync]", patches)
        self.assertIn("[post_model_sync]", patches)

    def test_workspace_exposes_operator_setup_and_console(self):
        workspace_path = (APP_ROOT / "cfg_kanban" / "workspace" / "cfg_kanban" /
                          "cfg_kanban.json")
        workspace = json.loads(workspace_path.read_text())
        links = {row.get("label"): row.get("link_to") for row in workspace["links"]}
        shortcuts = {row.get("label"): row.get("link_to") for row in workspace["shortcuts"]}
        self.assertEqual(links["Operator Profiles"], "CFG Kanban Operator Profile")
        self.assertEqual(links["Operator Sessions"], "CFG Kanban Operator Session")
        self.assertEqual(shortcuts["Production Operator Panel"], "kanban-operator")
        self.assertEqual(shortcuts["Service Task Panel"], "kanban-tasks")
        self.assertEqual(shortcuts["Logistics Operator Panel"], "kanban-logistics")
        self.assertEqual(shortcuts["Material Genealogy Explorer"],
                         "material-genealogy")
        self.assertEqual(shortcuts["Production Signals"], "kanban-supervisor")
        self.assertEqual(shortcuts["Maintenance Register"],
                         "Kanban Maintenance Register")
        self.assertEqual(shortcuts["Private Media Evidence"], "CFG Kanban Media")
        self.assertEqual(shortcuts["Operator Profiles"], "CFG Kanban Operator Profile")
        self.assertEqual(links["Logistics Routes"], "CFG Kanban Logistics Route")
        self.assertEqual(links["Customer Scan Points"], "CFG Kanban Customer Scan Point")
        self.assertEqual(links["Customer Delivery Sessions"],
                         "CFG Kanban Delivery Session")
        self.assertEqual(links["Customer Delivery Allocations"],
                         "CFG Kanban Delivery Allocation")
        self.assertEqual(shortcuts["Customer Delivery Sessions"],
                         "CFG Kanban Delivery Session")
        self.assertEqual(shortcuts["Customer Delivery Allocations"],
                         "CFG Kanban Delivery Allocation")
        self.assertEqual(links["Customer Delivery Proofs"],
                         "CFG Kanban Delivery Proof")
        self.assertEqual(shortcuts["Customer Delivery Proofs"],
                         "CFG Kanban Delivery Proof")
        self.assertEqual(links["Customer Return Cases"],
                         "CFG Kanban Return Case")
        self.assertEqual(shortcuts["Customer Return Cases"],
                         "CFG Kanban Return Case")
        self.assertEqual(links["Stock Tag Families"], "CFG Kanban Tag Family")
        self.assertEqual(links["Stock Tag Range Registries"],
                         "CFG Kanban Tag Range Registry")
        self.assertEqual(shortcuts["Stock Tag Range Registries"],
                         "CFG Kanban Tag Range Registry")
        self.assertEqual(shortcuts["Handling Unit Quantity Ledger"],
                         "CFG Kanban Handling Unit Quantity Ledger")
        self.assertEqual(shortcuts["Container Content History"],
                         "CFG Kanban Container Content")
        self.assertEqual(links["Container Content History"],
                         "CFG Kanban Container Content")
        self.assertEqual(shortcuts["Handling Unit Serial History"],
                         "CFG Kanban Handling Unit Serial")
        self.assertEqual(links["Handling Unit Serial History"],
                         "CFG Kanban Handling Unit Serial")
        self.assertEqual(links["Movement Manifests"],
                         "CFG Kanban Movement Manifest")
        self.assertEqual(links["Route Reconciliations"],
                         "CFG Kanban Route Reconciliation")
        self.assertEqual(shortcuts["Route Reconciliations"],
                         "CFG Kanban Route Reconciliation")
        self.assertEqual(links["Material Trace Policies"],
                         "CFG Kanban Material Trace Policy")
        self.assertEqual(shortcuts["Material Trace Policies"],
                         "CFG Kanban Material Trace Policy")
        self.assertEqual(links["Supplier Receipt Dispositions"],
                         "CFG Kanban Receipt Disposition")
        self.assertEqual(links["Material Genealogy"],
                         "CFG Kanban Material Trace")
        self.assertEqual(links["Material Genealogy Explorer"],
                         "material-genealogy")

    def test_supervisor_action_centre_exposes_visual_approval_queue(self):
        page_root = APP_ROOT / "cfg_kanban" / "page" / "kanban_supervisor"
        page = json.loads((page_root / "kanban_supervisor.json").read_text())
        roles = {row["role"] for row in page["roles"]}
        self.assertTrue({"Manufacturing Manager", "Purchase Manager", "System Manager"}
                        .issubset(roles))
        javascript = (page_root / "kanban_supervisor.js").read_text()
        self.assertIn("cfg_kanban.api.supervisor.get_action_centre", javascript)
        self.assertIn("cfg_kanban.api.operator.approve_signal", javascript)
        self.assertIn("cfg_kanban.api.operator.cancel_signal", javascript)
        api = (APP_ROOT / "api" / "supervisor.py").read_text()
        self.assertIn("def get_action_centre", api)
        self.assertIn('"Waiting Approval"', api)
        self.assertIn('"Awaiting Verification"', api)

    def test_master_backed_cards_expose_qr_print_actions(self):
        card_js = (APP_ROOT / "public" / "js" / "cfg_kanban_card.js").read_text()
        self.assertIn("const master_backed = Boolean(frm.doc.kanban_master)", card_js)
        self.assertIn('__("Print Card with QR")', card_js)
        self.assertIn('__("Replace Card Identity")', card_js)

        standard = json.loads((
            APP_ROOT / "cfg_kanban" / "print_format" /
            "cfg_kanban_standard_card" / "cfg_kanban_standard_card.json"
        ).read_text())
        operational = json.loads((
            APP_ROOT / "cfg_kanban" / "print_format" /
            "cfg_kanban_operational_card" / "cfg_kanban_operational_card.json"
        ).read_text())
        for print_format in (standard, operational):
            self.assertIn("STOCK TRANSFER", print_format["html"])
            self.assertIn("STOCK WITHDRAWAL", print_format["html"])

    def test_material_genealogy_explorer_is_read_only_and_printable(self):
        page = json.loads((
            APP_ROOT / "cfg_kanban" / "page" / "material_genealogy" /
            "material_genealogy.json"
        ).read_text())
        self.assertEqual(page["name"], "material-genealogy")
        self.assertEqual({"Manufacturing Manager", "Stock Manager", "System Manager"},
                         {row["role"] for row in page["roles"]})

        print_format = json.loads((
            APP_ROOT / "cfg_kanban" / "print_format" /
            "cfg_kanban_genealogy_report" / "cfg_kanban_genealogy_report.json"
        ).read_text())
        self.assertEqual(print_format["doc_type"], "CFG Kanban Handling Unit")
        self.assertEqual(print_format["name"], "CFG Kanban Genealogy Report")
        self.assertIn("get_genealogy_print_context", print_format["html"])
        self.assertIn("Exact Handling Unit", print_format["html"])

        service = (APP_ROOT / "services" / "genealogy.py").read_text()
        self.assertIn("def get_handling_unit_genealogy", service)
        self.assertIn('"evidence_level": "Exact Handling Unit"', service)
        self.assertIn("MAX_GRAPH_NODES = 100", service)
        self.assertNotIn("post_quantity_event", service)

        page_source = (
            APP_ROOT / "cfg_kanban" / "page" / "material_genealogy" /
            "material_genealogy.js"
        ).read_text()
        self.assertIn("Scan Any Physical Stock Tag", page_source)
        self.assertIn("Print Trace Report", page_source)
        self.assertIn("Reusable Container Episodes", page_source)

    def test_reusable_container_contents_are_immutable_physical_memberships(self):
        schema = json.loads((
            ROOT / "cfg_kanban_container_content" /
            "cfg_kanban_container_content.json"
        ).read_text())
        fields = {row["fieldname"]: row for row in schema["fields"]}
        self.assertTrue({
            "container_handling_unit", "content_handling_unit", "item_code",
            "batch_no", "qty", "stock_uom", "company", "warehouse",
            "loaded_on", "loaded_by", "load_event_key", "unloaded_on",
            "unloaded_by", "unload_event_key", "unload_reason",
        }.issubset(fields))
        self.assertEqual(fields["load_event_key"].get("unique"), 1)
        self.assertEqual(fields["unload_event_key"].get("unique"), 1)
        for permission in schema["permissions"]:
            self.assertFalse(permission.get("create", 0))
            self.assertFalse(permission.get("write", 0))
            self.assertFalse(permission.get("delete", 0))

        service = (APP_ROOT / "services" / "container_contents.py").read_text()
        self.assertIn("def load_content_tag", service)
        self.assertIn("def unload_content_tag", service)
        self.assertIn("def assert_not_loaded_in_container", service)
        self.assertIn("def active_container_contents", service)
        self.assertIn("def assert_container_not_in_open_manifest", service)
        self.assertNotIn("post_quantity_event", service)

        scan_api = (APP_ROOT / "api" / "scan.py").read_text()
        logistics_api = (APP_ROOT / "api" / "logistics.py").read_text()
        production_trace = (APP_ROOT / "services" / "production_trace.py").read_text()
        printing = (APP_ROOT / "services" / "printing.py").read_text()
        for source in (scan_api, logistics_api, production_trace, printing):
            self.assertTrue(
                "assert_not_loaded_in_container" in source or
                "assert_container_empty" in source
            )

        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        manifest_line = {
            row["fieldname"] for row in schemas["CFG Kanban Manifest Line"]["fields"]
        }
        self.assertTrue({"container_handling_unit", "container_visible_code"}.issubset(
            manifest_line
        ))
        self.assertIn("def _scan_dispatch_container", logistics_api)
        self.assertIn("def _scan_receipt_container", logistics_api)
        self.assertIn("def _validate_manifest_container_groups", logistics_api)
        feedback = (APP_ROOT / "integrations" / "logistics_feedback.py").read_text()
        self.assertIn("def _update_manifest_containers", feedback)

    def test_route_reconciliation_is_count_only_and_erp_authoritative(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        reconciliation = schemas["CFG Kanban Route Reconciliation"]
        fields = {row["fieldname"]: row for row in reconciliation["fields"]}
        self.assertTrue({
            "state", "company", "vehicle_warehouse", "vehicle_reference",
            "period_start", "period_end", "lines", "scans",
            "expected_line_count", "counted_line_count", "variance_line_count",
            "variance_exception", "resolution_notes",
            "correction_reference_doctype", "correction_reference",
            "idempotency_key",
        }.issubset(fields))
        self.assertEqual(fields["idempotency_key"].get("unique"), 1)
        self.assertEqual(fields["lines"]["options"],
                         "CFG Kanban Route Reconciliation Line")
        self.assertEqual(fields["scans"]["options"],
                         "CFG Kanban Route Reconciliation Scan")

        line_fields = {row["fieldname"] for row in
                       schemas["CFG Kanban Route Reconciliation Line"]["fields"]}
        self.assertTrue({
            "opening_qty", "movement_qty", "expected_closing_qty",
            "tagged_count_qty", "loose_count_qty", "counted_qty", "variance_qty",
        }.issubset(line_fields))
        scan_fields = {row["fieldname"] for row in
                       schemas["CFG Kanban Route Reconciliation Scan"]["fields"]}
        self.assertTrue({
            "handling_unit", "visible_code", "container_handling_unit",
            "container_visible_code", "item_code", "batch_no", "qty",
            "scanned_on", "scanned_by", "scan_event_key",
        }.issubset(scan_fields))

        service = (APP_ROOT / "services" / "route_reconciliation.py").read_text()
        for method in (
            "start_route_reconciliation", "scan_reconciliation_tag",
            "save_loose_counts", "evaluate_route_reconciliation",
            "close_route_reconciliation", "cancel_route_reconciliation",
        ):
            self.assertIn(f"def {method}", service)
        self.assertIn("`tabStock Ledger Entry`", service)
        self.assertIn("`tabSerial and Batch Entry`", service)
        self.assertIn("active_container_contents", service)
        self.assertIn('"Route Stock Variance"', service)
        self.assertNotIn("post_quantity_event", service)
        self.assertNotIn('"doctype": "Stock Entry"', service)
        self.assertNotIn('frappe.new_doc("Stock Entry")', service)

        event_fields = {row["fieldname"] for row in
                        schemas["CFG Kanban Event"]["fields"]}
        exception_fields = {row["fieldname"] for row in
                            schemas["CFG Kanban Exception"]["fields"]}
        self.assertIn("route_reconciliation", event_fields)
        self.assertIn("route_reconciliation", exception_fields)

        print_format = json.loads((
            APP_ROOT / "cfg_kanban" / "print_format" /
            "cfg_route_reconciliation_report" /
            "cfg_route_reconciliation_report.json"
        ).read_text())
        self.assertEqual(print_format["doc_type"],
                         "CFG Kanban Route Reconciliation")
        self.assertIn("ERPNext expected balance", print_format["html"])

    def test_exact_serial_membership_is_erp_referenced_and_auditable(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        serial_schema = schemas["CFG Kanban Handling Unit Serial"]
        fields = {row["fieldname"]: row for row in serial_schema["fields"]}
        self.assertTrue({
            "state", "handling_unit", "handling_unit_code", "serial_no",
            "active_serial_key", "item_code", "batch_no", "assigned_on",
            "assignment_reference_doctype", "assignment_reference_name",
            "assignment_reference_row", "assignment_key", "released_on",
            "release_reason", "release_reference_doctype", "release_reference_name",
        }.issubset(fields))
        self.assertEqual(fields["serial_no"]["options"], "Serial No")
        self.assertEqual(fields["active_serial_key"].get("unique"), 1)
        self.assertEqual(fields["assignment_key"].get("unique"), 1)
        for permission in serial_schema["permissions"]:
            self.assertFalse(permission.get("create", 0))
            self.assertFalse(permission.get("write", 0))
            self.assertFalse(permission.get("delete", 0))

        handling = {row["fieldname"] for row in
                    schemas["CFG Kanban Handling Unit"]["fields"]}
        trace_line = {row["fieldname"] for row in
                      schemas["CFG Kanban Material Trace Line"]["fields"]}
        self.assertIn("serial_count", handling)
        self.assertTrue({"serial_count", "serial_numbers_json"}.issubset(trace_line))

        service = (APP_ROOT / "services" / "serial_evidence.py").read_text()
        self.assertIn("def erp_row_serials", service)
        self.assertIn('"Serial and Batch Entry"', service)
        self.assertIn("def assign_serials", service)
        self.assertIn("def release_unit_serials", service)
        self.assertNotIn("post_quantity_event", service)

        receiving = (APP_ROOT / "api" / "receiving.py").read_text()
        feedback = (APP_ROOT / "integrations" / "purchase_feedback.py").read_text()
        self.assertIn("def void_cancelled_purchase_receipt_tags", receiving)
        self.assertIn("_assert_receipt_tag_untouched", receiving)
        self.assertIn("void_cancelled_purchase_receipt_tags(doc)", feedback)

        split_service = (APP_ROOT / "services" / "handling_unit_split.py").read_text()
        self.assertIn("def split_serials_to_child", split_service)
        self.assertIn("def merge_serial_child_to_parent", split_service)
        self.assertIn('event_type="Merge"', split_service)
        self.assertIn("transfer_selected_serials", split_service)
        self.assertIn("merge_child_serials", split_service)
        ledger_fields = {row["fieldname"]: row for row in
                         schemas["CFG Kanban Handling Unit Quantity Ledger"]["fields"]}
        self.assertIn("Merge", ledger_fields["event_type"]["options"].splitlines())

    def test_every_field_is_present_once_in_field_order(self):
        for path, schema in self._schemas():
            fields = [row["fieldname"] for row in schema.get("fields", [])]
            order = schema.get("field_order", [])
            self.assertEqual(len(fields), len(set(fields)), path)
            self.assertEqual(set(fields), set(order), path)
            self.assertEqual(len(order), len(set(order)), path)

    def test_child_table_targets_exist_and_are_child_doctypes(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        for path, schema in self._schemas():
            for field in schema.get("fields", []):
                if field.get("fieldtype") != "Table":
                    continue
                target = schemas.get(field.get("options"))
                self.assertIsNotNone(target, f"{path}: {field['fieldname']}")
                self.assertEqual(target.get("istable"), 1, f"{path}: {field['fieldname']}")

    def test_card_exposes_operation_and_print_audit_context(self):
        path = ROOT / "cfg_kanban_card" / "cfg_kanban_card.json"
        schema = json.loads(path.read_text())
        fields = {row["fieldname"] for row in schema["fields"]}
        required = {"operation", "workstation", "handoff_mode", "stock_uom",
                    "source_warehouse", "destination_warehouse",
                    "last_printed_on", "last_printed_by"}
        self.assertTrue(required.issubset(fields))

        by_name = {row["fieldname"]: row for row in schema["fields"]}
        for fieldname in ("card_type", "item_code", "current_state"):
            self.assertEqual(by_name[fieldname].get("in_list_view"), 1)
            self.assertEqual(by_name[fieldname].get("in_standard_filter"), 1)

    def test_parallel_execution_fields_are_present(self):
        execution_path = ROOT / "cfg_kanban_process_execution" / "cfg_kanban_process_execution.json"
        execution_fields = {row["fieldname"] for row in json.loads(execution_path.read_text())["fields"]}
        self.assertTrue({"operation_summary", "lane_sequence", "execution_mode",
                         "allocated_qty", "destination_operation", "job_card"}
                        .issubset(execution_fields))

        summary_path = ROOT / "cfg_kanban_operation_summary" / "cfg_kanban_operation_summary.json"
        summary = json.loads(summary_path.read_text())
        summary_fields = {row["fieldname"] for row in summary["fields"]}
        self.assertEqual(summary["name"], "CFG Kanban Operation Summary")
        self.assertTrue({"summary_key", "kanban_cycle", "operation", "execution_mode",
                         "target_qty", "allocated_qty", "good_qty", "released_qty",
                         "execution_count", "completed_execution_count"}
                        .issubset(summary_fields))

    def test_runtime_allocation_traceability_fields_are_present(self):
        cycle_path = ROOT / "cfg_kanban_cycle" / "cfg_kanban_cycle.json"
        cycle_fields = {row["fieldname"] for row in json.loads(cycle_path.read_text())["fields"]}
        self.assertTrue({"nominal_card_qty", "effective_cycle_qty", "available_input_qty",
                         "short_cycle_reason", "selected_job_card", "runtime_allocation"}
                        .issubset(cycle_fields))
        allocation_path = ROOT / "cfg_kanban_runtime_allocation" / "cfg_kanban_runtime_allocation.json"
        allocation_fields = {row["fieldname"] for row in json.loads(allocation_path.read_text())["fields"]}
        self.assertTrue({"kanban_cycle", "kanban_card", "work_order", "job_card",
                         "nominal_card_qty", "remaining_job_card_qty", "available_input_qty",
                         "effective_qty", "short_cycle_reason", "selection_method",
                         "recommended_job_card", "override_reason", "operator_confirmation"}
                        .issubset(allocation_fields))

    def test_job_card_automation_settings_are_explicit(self):
        settings_path = ROOT / "cfg_kanban_settings" / "cfg_kanban_settings.json"
        settings = json.loads(settings_path.read_text())
        fields = {row["fieldname"] for row in settings["fields"]}
        self.assertTrue({"auto_start_job_card", "auto_submit_job_card"}.issubset(fields))

    def test_signal_list_and_cancellation_fields_are_present(self):
        path = ROOT / "cfg_kanban_signal" / "cfg_kanban_signal.json"
        schema = json.loads(path.read_text())
        by_name = {row["fieldname"]: row for row in schema["fields"]}
        for fieldname in ("status", "item_code", "requested_qty", "requested_on"):
            self.assertEqual(by_name[fieldname].get("in_list_view"), 1)
        for fieldname in ("status", "item_code", "requested_on", "signal_type", "priority"):
            self.assertEqual(by_name[fieldname].get("in_standard_filter"), 1)
        self.assertTrue({"cancellation_reason", "cancelled_on", "cancelled_by"}.issubset(by_name))

    def test_purchase_replenishment_schema_is_explicit(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        master = {row["fieldname"]: row for row in schemas["CFG Kanban Master"]["fields"]}
        self.assertIn("Purchase Replenishment", master["control_type"]["options"].splitlines())
        self.assertTrue({"default_supplier", "supplier_pack_size", "minimum_order_qty",
                         "purchase_order_multiple", "auto_submit_material_request",
                         "purchase_execution_mode", "master_auto_submit_po_value_limit",
                         "receipt_posting_mode", "allow_partial_receipt",
                         "over_receipt_tolerance_pct", "rejected_warehouse", "purchase_uom",
                         "purchase_uom_conversion_factor", "purchase_replenishment_qty"}
                        .issubset(master))
        self.assertEqual(master["stock_uom"].get("read_only"), 1)
        cycle = {row["fieldname"] for row in schemas["CFG Kanban Cycle"]["fields"]}
        self.assertTrue({"supplier", "material_request", "purchase_order",
                         "purchase_order_item", "latest_purchase_receipt", "ordered_qty",
                         "received_qty", "outstanding_qty", "purchase_status", "purchase_uom",
                         "purchase_uom_conversion_factor", "requested_purchase_qty",
                         "requested_stock_qty", "ordered_purchase_qty", "ordered_stock_qty",
                         "received_purchase_qty", "received_stock_qty",
                         "outstanding_purchase_qty", "outstanding_stock_qty",
                         "delivered_purchase_qty", "accepted_purchase_qty",
                         "rejected_purchase_qty", "rejected_open_purchase_qty",
                         "concession_purchase_qty", "usable_fulfilment_purchase_qty",
                         "purchase_short_closed_qty", "receipt_disposition_status"}.issubset(cycle))
        disposition = {row["fieldname"] for row in
                       schemas["CFG Kanban Receipt Disposition"]["fields"]}
        self.assertTrue({"kanban_cycle", "purchase_receipt", "purchase_receipt_item",
                         "rejected_warehouse", "delivered_qty", "accepted_qty",
                         "rejected_qty", "returned_rejected_qty", "open_rejected_qty",
                         "disposition", "status", "resolution_doctype",
                         "resolution_document", "approved_concession_qty",
                         "disposed_qty", "decision_reason"}.issubset(disposition))
        commands = next(row for row in schemas["CFG ERP Command"]["fields"]
                        if row["fieldname"] == "command_type")["options"].splitlines()
        self.assertIn("Create Material Request", commands)
        self.assertIn("Create Purchase Order", commands)
        self.assertIn("Create Purchase Receipt", commands)

        settings = {row["fieldname"]: row for row in
                    schemas["CFG Kanban Settings"]["fields"]}
        self.assertTrue({"maximum_purchase_automation", "maximum_auto_submit_po_value"}
                        .issubset(settings))

    def test_logistics_foundation_schema_is_additive(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        self.assertTrue({
            "CFG Kanban Logistics Route",
            "CFG Kanban Customer Scan Point",
            "CFG Kanban Tag Family",
            "CFG Kanban Tag Range Registry",
            "CFG Kanban Tag Identity",
            "CFG Kanban Handling Unit Quantity Ledger",
        }.issubset(schemas))

        route = {row["fieldname"]: row for row in
                 schemas["CFG Kanban Logistics Route"]["fields"]}
        self.assertTrue({"source_company", "source_warehouse", "destination_company",
                         "destination_warehouse", "internal_customer", "internal_supplier",
                         "selling_price_list", "buying_price_list", "handover_mode",
                         "auto_submit_dispatch_dn", "auto_submit_receipt_pr",
                         "billing_frequency"}.issubset(route))

        site = {row["fieldname"]: row for row in
                schemas["CFG Kanban Customer Scan Point"]["fields"]}
        self.assertTrue({"site_code", "opaque_token", "selling_company", "customer",
                         "customer_address", "proof_policy", "require_signature",
                         "require_photo", "require_gps"}.issubset(site))

        family = {row["fieldname"]: row for row in
                  schemas["CFG Kanban Tag Family"]["fields"]}
        self.assertEqual(family["identities"]["options"], "CFG Kanban Tag Identity")
        self.assertEqual(family["family_code"]["label"], "Preprinted Main Tag Code")
        self.assertEqual(family["issued_company"].get("reqd"), 1)
        self.assertEqual(family["range_registry"]["options"],
                         "CFG Kanban Tag Range Registry")
        self.assertEqual(family["range_registry"].get("read_only"), 1)
        self.assertIn("child_separator", family)
        registry = {row["fieldname"]: row for row in
                    schemas["CFG Kanban Tag Range Registry"]["fields"]}
        self.assertTrue({"registry_code", "active", "issued_company", "prefix",
                         "start_number", "end_number", "number_width",
                         "child_separator", "child_count", "first_main_code",
                         "last_main_code", "total_main_tags",
                         "potential_identity_count", "materialized_count",
                         "last_materialized_tag", "last_materialized_on"}
                        .issubset(registry))
        self.assertEqual(schemas["CFG Kanban Tag Identity"].get("istable"), 1)
        identity = {row["fieldname"]: row for row in
                    schemas["CFG Kanban Tag Identity"]["fields"]}
        self.assertEqual(identity["opaque_token"]["label"], "Internal UUID Alias")
        self.assertEqual(identity["opaque_token"].get("hidden"), 1)

    def test_handling_unit_has_ledger_backed_logistics_identity(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        handling = {row["fieldname"]: row for row in
                    schemas["CFG Kanban Handling Unit"]["fields"]}
        self.assertTrue({"tag_kind", "tag_family", "parent_handling_unit",
                         "tag_range_registry",
                         "root_handling_unit", "child_index", "inventory_company",
                         "current_warehouse", "physical_custodian", "packed_on",
                         "expiry_date", "original_qty", "current_qty", "reserved_qty",
                         "available_qty", "identity_state", "movement_state",
                         "quality_state"}.issubset(handling))
        self.assertFalse(handling["kanban_cycle"].get("reqd", 0))
        self.assertEqual(
            handling["handling_unit_id"]["label"],
            "Preprinted Tag / Handling Unit ID",
        )
        self.assertEqual(handling["opaque_token"]["label"], "Internal UUID Alias")
        self.assertIn("tag_kind!='Reusable Container'",
                      handling["inventory_company"]["mandatory_depends_on"])
        self.assertIn("tag_kind!='Reusable Container'",
                      handling["current_warehouse"]["mandatory_depends_on"])
        self.assertEqual(handling["current_warehouse"]["read_only_depends_on"],
                         "eval:!doc.__islocal")
        self.assertTrue({"origin_reference_doctype", "origin_reference_name",
                         "origin_reference_row", "activation_key"}.issubset(handling))
        self.assertEqual(handling["origin_reference_name"]["fieldtype"], "Dynamic Link")
        self.assertEqual(handling["origin_reference_name"]["options"],
                         "origin_reference_doctype")
        self.assertTrue(handling["activation_key"]["unique"])

        ledger = {row["fieldname"]: row for row in
                  schemas["CFG Kanban Handling Unit Quantity Ledger"]["fields"]}
        self.assertTrue({"idempotency_key", "source_handling_unit",
                         "destination_handling_unit", "source_qty_delta",
                         "destination_qty_delta", "source_reserved_delta",
                         "destination_reserved_delta", "source_company",
                         "destination_company", "source_warehouse",
                         "destination_warehouse"}.issubset(ledger))
        for permission in schemas["CFG Kanban Handling Unit Quantity Ledger"]["permissions"]:
            self.assertFalse(permission.get("create", 0))
            self.assertFalse(permission.get("write", 0))
            self.assertFalse(permission.get("delete", 0))

    def test_material_trace_policy_keeps_physical_tags_optional(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        policy = {row["fieldname"]: row for row in
                  schemas["CFG Kanban Material Trace Policy"]["fields"]}
        self.assertEqual(
            policy["trace_level"]["options"].splitlines(),
            ["ERP Document Only", "Batch Pool", "Exact Handling Unit"],
        )
        for fieldname in ("receiving_tag_policy", "production_input_tag_policy",
                          "production_output_tag_policy", "warehouse_transfer_tag_policy"):
            self.assertEqual(
                policy[fieldname]["options"].splitlines(),
                ["No Physical Tag", "Optional Physical Tag", "Required Physical Tag"],
            )
            self.assertEqual(policy[fieldname]["default"], "No Physical Tag")

        trace_service = (APP_ROOT / "services" / "trace_policy.py").read_text()
        self.assertIn('"policy_source": "Default ERP-only behavior"', trace_service)
        self.assertIn('"trace_level": "ERP Document Only"', trace_service)
        self.assertIn('"receiving_tag_policy": NO_TAG', trace_service)

    def test_purchase_receipt_tag_activation_is_erp_confirmed_and_bounded(self):
        hooks = (APP_ROOT / "hooks.py").read_text()
        api = (APP_ROOT / "api" / "receiving.py").read_text()
        form = (APP_ROOT / "public" / "js" / "purchase_receipt.js").read_text()
        self.assertIn('"Purchase Receipt": "public/js/purchase_receipt.js"', hooks)
        self.assertIn("receipt.docstatus != 1", api)
        self.assertIn("qty > remaining + 0.000001", api)
        self.assertIn('"origin_reference_doctype": "Purchase Receipt"', api)
        self.assertIn("activation_key = canonical_key", api)
        self.assertIn("Tag Family {tag_family} is inactive", api)
        self.assertIn(
            'identity.get("identity_type") == "Registered Tag Identity"', api
        )
        self.assertIn("Tag Received Material", form)
        self.assertIn("No Physical Tag remain valid ERPNext warehouse stock", form)
        self.assertIn('"tagging_ready": not blocking_reason', api)
        self.assertIn('"tagging_status": "Ready to tag"', api)
        self.assertIn("Every receipt row is listed", form)
        self.assertIn('fieldname: "row_guidance"', form)
        self.assertIn("Review Tag Activation", form)
        self.assertIn("Confirm and Activate Tag", form)
        self.assertIn("def void_purchase_receipt_tag", api)
        self.assertIn("_assert_receipt_tag_untouched(unit, expected_warehouse)", api)
        self.assertIn('"Revoked"', api)
        self.assertIn("Void Wrong Receipt Tag", form)
        self.assertIn("ignore_permissions=True", api)
        self.assertIn("def _existing_activation_result", api)
        self.assertIn("was {disposition} and cannot be reused", api)
        self.assertIn("Recorded reason: {reason}", api)
        self.assertIn("Rescanning it cannot change the quantity", api)
        self.assertIn('result["idempotent_replay"] = True', api)
        self.assertIn("no quantity changed", form)
        repack = (APP_ROOT / "services" / "receipt_repack.py").read_text()
        handling_form = (APP_ROOT / "public" / "js" /
                         "cfg_kanban_handling_unit.js").read_text()
        self.assertIn("def get_receipt_repack_plan", repack)
        self.assertIn("def repack_receipt_quantity", repack)
        self.assertIn('event_type="Split"', repack)
        self.assertIn('destination.flags.skip_initial_ledger = True', repack)
        self.assertIn("Receipt-Time Split / Repack", form)
        self.assertIn("Receipt-Time Split / Repack", handling_form)
        self.assertIn("I checked both physical tags and the quantity", form)
        transfer = (APP_ROOT / "services" / "tag_to_tag_transfer.py").read_text()
        self.assertIn("def get_tag_to_tag_transfer_plan", transfer)
        self.assertIn("def transfer_between_active_tags", transfer)
        self.assertIn('event_type="Merge"', transfer)
        self.assertIn("Same-warehouse active-tag quantity transfer", transfer)
        self.assertIn("Transfer Quantity to Active Tag", form)
        self.assertIn("Transfer Quantity to Active Tag", handling_form)
        self.assertIn("I checked both active tags and the physical quantity", form)
        install = (APP_ROOT / "install.py").read_text()
        self.assertIn('"Stock Retagging"', install)
        auth = (APP_ROOT / "services" / "retagging_auth.py").read_text()
        self.assertIn("STOCK_RETAGGING_RESPONSIBILITY", auth)
        self.assertIn("def authorize_stock_retagging", auth)
        self.assertIn("def split_to_unused_tag", transfer)
        logistics_api = (APP_ROOT / "api" / "logistics.py").read_text()
        logistics_panel = (APP_ROOT / "cfg_kanban" / "page" / "kanban_logistics" /
                           "kanban_logistics.js").read_text()
        self.assertIn('result["can_retag"]', logistics_api)
        self.assertIn("Split to New Tag", logistics_panel)
        self.assertIn("Move to Active Tag", logistics_panel)
        self.assertIn("operator_session_token: state.token", logistics_panel)
        self.assertNotIn(
            ".filter((row) => row.tagging_available && row.remaining_stock_qty",
            form,
        )

    def test_production_material_trace_is_stock_entry_confirmed(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        self.assertIn("CFG Kanban Material Trace", schemas)
        self.assertIn("CFG Kanban Material Trace Line", schemas)
        trace = {row["fieldname"]: row for row in
                 schemas["CFG Kanban Material Trace"]["fields"]}
        self.assertEqual(trace["lines"]["options"], "CFG Kanban Material Trace Line")
        self.assertTrue({"status", "company", "purpose", "stock_entry_reference",
                         "stock_entry", "work_order",
                         "kanban_cycle", "confirmed_on", "confirmed_by", "reversed_on",
                         "reversed_by", "abandoned_on", "abandoned_by",
                         "abandon_reason"}.issubset(trace))
        self.assertTrue(trace["stock_entry"]["unique"])
        self.assertEqual(schemas["CFG Kanban Material Trace Line"].get("istable"), 1)

        line = {row["fieldname"]: row for row in
                schemas["CFG Kanban Material Trace Line"]["fields"]}
        self.assertTrue({"direction", "status", "stock_entry_detail", "item_code",
                         "batch_no", "warehouse", "qty", "stock_uom", "trace_policy",
                         "handling_unit", "pending_tag_code", "reservation_ledger",
                         "confirmation_ledger", "reversal_ledger"}.issubset(line))

        hooks = (APP_ROOT / "hooks.py").read_text()
        feedback = (APP_ROOT / "integrations" / "erp_feedback.py").read_text()
        service = (APP_ROOT / "services" / "production_trace.py").read_text()
        form = (APP_ROOT / "public" / "js" / "stock_entry.js").read_text()
        self.assertIn('"Stock Entry": "public/js/stock_entry.js"', hooks)
        self.assertIn("validate_stock_entry_trace(doc)", feedback)
        self.assertIn("confirm_stock_entry_trace(doc)", feedback)
        self.assertIn("reverse_stock_entry_trace(doc)", feedback)
        self.assertIn('event_type="Production Consume"', service)
        self.assertIn('event_type="Production Output Reversal"', service)
        self.assertIn("Serial and Batch Entry", service)
        self.assertIn("A physical tag cannot be split across two Warehouses", service)
        self.assertIn("def abandon_draft_trace(", service)
        self.assertIn("Discard Entire Draft Trace", form)
        self.assertIn("No Physical Tag rows remain normal ERPNext stock", form)

        operator_api = (APP_ROOT / "api" / "operator.py").read_text()
        operator_panel = (APP_ROOT / "cfg_kanban" / "page" / "kanban_operator" /
                          "kanban_operator.js").read_text()
        self.assertIn("def _production_stock_entries(", operator_api)
        self.assertIn('"production_stock_entries": production_stock_entries', operator_api)
        self.assertIn("def _authorize_trace_access(", service)
        self.assertIn("operator_session_token", service)
        self.assertIn("Scan Material Tags", operator_panel)
        self.assertIn("Camera Scan Input Tag", operator_panel)
        self.assertIn("Camera Scan Output Tag", operator_panel)
        self.assertIn("operator_session_token: state.session_token", operator_panel)

    def test_same_company_tagged_warehouse_transfer_is_guided_by_erp_stock_entry(self):
        service = (APP_ROOT / "services" / "production_trace.py").read_text()
        stock_entry_form = (APP_ROOT / "public" / "js" / "stock_entry.js").read_text()
        logistics_api = (APP_ROOT / "api" / "logistics.py").read_text()
        logistics_panel = (APP_ROOT / "cfg_kanban" / "page" / "kanban_logistics" /
                           "kanban_logistics.js").read_text()
        install = (APP_ROOT / "install.py").read_text()
        self.assertIn('"Material Transfer",', service)
        self.assertIn('return _purpose(doc) in ("Material Transfer",', service)
        self.assertIn('"Material Transfer",', stock_entry_form)
        self.assertIn("INTERNAL_TRANSFER_RESPONSIBILITY", logistics_api)
        self.assertIn("def _internal_transfer_summaries(", logistics_api)
        self.assertIn('"internal_transfers": _internal_transfer_summaries(profile)', logistics_api)
        self.assertIn("Manual Material Transfer Fallback", logistics_panel)
        self.assertIn("Tagged Warehouse Transfer", logistics_panel)
        self.assertIn("Internal Warehouse Transfer", install)

    def test_handling_unit_replacement_print_encodes_visible_code(self):
        path = (APP_ROOT / "cfg_kanban" / "print_format" /
                "cfg_kanban_handling_unit_tag" / "cfg_kanban_handling_unit_tag.json")
        print_format = json.loads(path.read_text())
        html = print_format["html"]
        self.assertIn("get_qr_svg(doc.handling_unit_id", html)
        self.assertIn("get_code128_svg(doc.handling_unit_id", html)
        self.assertNotIn("get_qr_svg(doc.opaque_token", html)

    def test_handling_unit_scan_api_uses_central_physical_resolver(self):
        scan_source = (APP_ROOT / "api" / "scan.py").read_text()
        self.assertIn("resolve_logistics_scan(token)", scan_source)
        self.assertNotIn(
            '"CFG Kanban Handling Unit", {"opaque_token": token}', scan_source
        )

    def test_legacy_blank_handling_unit_has_controlled_warehouse_recovery(self):
        api = (APP_ROOT / "api" / "logistics.py").read_text()
        form = (APP_ROOT / "public" / "js" /
                "cfg_kanban_handling_unit.js").read_text()
        self.assertIn("def assign_initial_warehouse(", api)
        self.assertIn("validate_warehouse_company(warehouse, unit.inventory_company", api)
        self.assertIn("_assert_erp_stock(unit, warehouse, unit.current_qty)", api)
        self.assertIn('event_type="Location Transfer"', api)
        self.assertIn("Assign Initial Warehouse", form)

    def test_tag_range_lookup_is_lazy_and_materialization_is_controlled(self):
        resolver = (APP_ROOT / "services" / "logistics_foundation.py").read_text()
        registry = (APP_ROOT / "services" / "tag_registry.py").read_text()
        handling = (ROOT / "cfg_kanban_handling_unit" /
                    "cfg_kanban_handling_unit.py").read_text()
        form = (APP_ROOT / "public" / "js" /
                "cfg_kanban_handling_unit.js").read_text()
        self.assertIn("resolve_tag_range_candidate(code)", resolver)
        self.assertIn('"identity_type": "Tag Range Candidate"', registry)
        self.assertIn("for update", registry.lower())
        self.assertIn("materialize_tag_family_for_code", handling)
        self.assertIn('identity.identity_type === "Tag Range Candidate"', form)
        receiving = (APP_ROOT / "api" / "receiving.py").read_text()
        production = (APP_ROOT / "services" / "production_trace.py").read_text()
        for source in (receiving, production):
            self.assertIn(
                'identity.get("identity_type") == "Registered Tag Identity"', source
            )

    def test_intercompany_manifest_schema_and_commands_are_present(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        self.assertTrue({"CFG Kanban Movement Manifest",
                         "CFG Kanban Manifest Line"}.issubset(schemas))
        manifest = {row["fieldname"]: row for row in
                    schemas["CFG Kanban Movement Manifest"]["fields"]}
        self.assertEqual(manifest["lines"]["options"], "CFG Kanban Manifest Line")
        self.assertTrue({"logistics_route", "state", "source_company",
                         "source_warehouse", "destination_company",
                         "destination_warehouse", "internal_customer",
                         "internal_supplier", "dispatch_delivery_note",
                         "receipt_purchase_receipt", "preparation_key",
                         "dispatch_key", "receipt_key"}.issubset(manifest))
        self.assertEqual(schemas["CFG Kanban Manifest Line"].get("istable"), 1)

        commands = next(row for row in schemas["CFG ERP Command"]["fields"]
                        if row["fieldname"] == "command_type")["options"].splitlines()
        self.assertIn("Create Intercompany Delivery Note", commands)
        self.assertIn("Create Intercompany Purchase Receipt", commands)
        command_fields = {row["fieldname"]: row for row in
                          schemas["CFG ERP Command"]["fields"]}
        self.assertEqual(command_fields["command_type"].get("reqd"), 1)
        self.assertFalse(command_fields["kanban_cycle"].get("reqd", 0))

    def test_internal_transfer_kanban_uses_controlled_stock_entries(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        route = {row["fieldname"]: row for row in
                 schemas["CFG Kanban Logistics Route"]["fields"]}
        self.assertIn("Internal Warehouse Transfer", route["route_type"]["options"])
        self.assertEqual(
            route["internal_transfer_mode"]["options"].splitlines(),
            ["Direct Transfer", "Goods in Transit"],
        )
        master = {row["fieldname"]: row for row in schemas["CFG Kanban Master"]["fields"]}
        self.assertEqual(master["logistics_route"]["options"], "CFG Kanban Logistics Route")
        manifest = {row["fieldname"]: row for row in
                    schemas["CFG Kanban Movement Manifest"]["fields"]}
        self.assertTrue({
            "manifest_type", "kanban_cycle", "source_signal", "internal_transfer_mode",
            "dispatch_stock_entry", "receipt_stock_entry", "auto_submit_internal_dispatch",
            "auto_submit_internal_receipt",
        }.issubset(manifest))
        line = {row["fieldname"]: row for row in
                schemas["CFG Kanban Manifest Line"]["fields"]}
        self.assertEqual(
            line["line_kind"]["options"].splitlines(),
            ["Tagged Stock", "ERP Stock without Physical Tag"],
        )
        commands = next(row for row in schemas["CFG ERP Command"]["fields"]
                        if row["fieldname"] == "command_type")["options"].splitlines()
        self.assertIn("Create Internal Transfer Dispatch", commands)
        self.assertIn("Create Internal Transfer Receipt", commands)

        gateway = (APP_ROOT / "integrations" / "erp_gateway.py").read_text()
        feedback = (APP_ROOT / "integrations" / "logistics_feedback.py").read_text()
        logistics = (APP_ROOT / "api" / "logistics.py").read_text()
        triggers = (APP_ROOT / "services" / "triggers.py").read_text()
        self.assertIn('stock_entry_type": "Material Transfer"', gateway)
        self.assertIn('"add_to_transit": 1 if stage == "Outward" else 0', gateway)
        self.assertIn('"outgoing_stock_entry"', gateway)
        self.assertIn("def validate_internal_stock_entry", feedback)
        self.assertIn("def on_internal_stock_entry_submit", feedback)
        self.assertIn('{"Outward", "Receipt"}', feedback)
        self.assertIn("def create_transfer_manifest", (APP_ROOT / "services" /
                                                        "internal_transfer.py").read_text())
        self.assertIn('master.control_type == "Transfer"', triggers)
        self.assertIn("ERP Stock without Physical Tag", logistics)
        self.assertIn("def trigger_transfer_card", logistics)
        self.assertIn("def _receipt_retry_available", logistics)
        self.assertIn("def _transfer_tag_policy", logistics)
        self.assertIn("A physical Stock Tag must move in full", logistics)
        self.assertIn("can_scan_dispatch_tags", logistics)
        self.assertIn('frappe.get_meta(doctype).has_field("status")', logistics)
        self.assertIn('1: "Submitted"', logistics)

        panel = (APP_ROOT / "cfg_kanban" / "page" / "kanban_logistics" /
                 "kanban_logistics.js").read_text()
        self.assertIn("Warehouse Transfer Tags", panel)
        self.assertIn("m.can_scan_dispatch_tags !== false", panel)

    def test_customer_delivery_session_foundation_is_company_scoped(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        self.assertTrue({"CFG Kanban Delivery Session", "CFG Kanban Delivery Allocation",
                         "CFG Kanban Delivery Proof"}.issubset(schemas))

        session = {row["fieldname"]: row for row in
                   schemas["CFG Kanban Delivery Session"]["fields"]}
        self.assertTrue({
            "state", "customer_scan_point", "site_code", "site_name",
            "selling_company", "customer", "customer_address", "source_warehouse",
            "vehicle_reference", "price_list", "auto_submit_delivery_note",
            "proof_policy", "operator_session", "started_by_operator", "idempotency_key",
            "delivery_note", "delivery_command", "delivery_key", "delivery_revision",
            "delivery_confirmed_by", "delivery_operator_session", "exception",
            "delivery_proof", "proof_disposition", "proof_submitted_on",
        }.issubset(session))
        self.assertEqual(session["idempotency_key"].get("unique"), 1)

        allocation = {row["fieldname"]: row for row in
                      schemas["CFG Kanban Delivery Allocation"]["fields"]}
        self.assertTrue({
            "delivery_session", "handling_unit", "visible_code", "item_code",
            "batch_no", "stock_uom", "allocated_qty", "delivered_qty",
            "source_warehouse", "reservation_key", "active_handling_unit_key",
            "movement_state_before_reservation", "reservation_ledger",
            "release_ledger", "release_key",
        }.issubset(allocation))
        self.assertEqual(allocation["reservation_key"].get("unique"), 1)
        self.assertEqual(allocation["active_handling_unit_key"].get("unique"), 1)
        self.assertEqual(allocation["release_key"].get("unique"), 1)

        proof = {row["fieldname"]: row for row in
                 schemas["CFG Kanban Delivery Proof"]["fields"]}
        self.assertTrue({
            "delivery_session", "delivery_note", "proof_policy", "disposition",
            "recipient_name", "unattended_reason", "latitude", "longitude",
            "photo_count", "signature_count", "attachment_count", "submitted_on",
            "submitted_by_operator", "idempotency_key", "media_evidence_html",
        }.issubset(proof))
        self.assertEqual(proof["delivery_session"].get("unique"), 1)
        self.assertEqual(proof["idempotency_key"].get("unique"), 1)

        command = {row["fieldname"]: row for row in
                   schemas["CFG ERP Command"]["fields"]}
        self.assertEqual(command["delivery_session"]["options"],
                         "CFG Kanban Delivery Session")
        command_types = command["command_type"]["options"].splitlines()
        self.assertIn("Create Customer Delivery Note", command_types)
        self.assertNotIn("Create Customer Sales Invoice", command_types)

        for doctype in ("CFG Kanban Event", "CFG Kanban Exception"):
            fields = {row["fieldname"]: row for row in schemas[doctype]["fields"]}
            self.assertEqual(fields["delivery_session"]["options"],
                             "CFG Kanban Delivery Session")

        install = (APP_ROOT / "install.py").read_text()
        service = (APP_ROOT / "services" / "customer_delivery.py").read_text()
        panel = (APP_ROOT / "cfg_kanban" / "page" / "kanban_logistics" /
                 "kanban_logistics.js").read_text()
        self.assertIn('"cfg_is_vehicle_warehouse"', install)
        self.assertIn('"cfg_vehicle_reference"', install)
        self.assertIn('"Customer Delivery"', install)
        self.assertIn("def start_delivery_session", service)
        self.assertIn("def cancel_delivery_session", service)
        self.assertIn("def allocate_delivery_stock", service)
        self.assertIn("def confirm_delivery_allocations", service)
        self.assertIn("def release_delivery_allocation", service)
        self.assertIn("def get_customer_delivery_requirements", service)
        self.assertIn("def create_customer_delivery_document", service)
        self.assertIn('event_type="Reserve"', service)
        self.assertIn('event_type="Unreserve"', service)
        self.assertIn("state.lookup.customer_site", panel)
        self.assertIn("Lock Customer and Vehicle", panel)
        self.assertIn("Start Allocation Scanning", panel)
        self.assertIn("Confirm Customer Allocation", panel)
        self.assertIn("Create Delivery Note", panel)
        self.assertIn("Required Customer Delivery Note Details", panel)
        self.assertIn("Capture / Close Delivery", panel)
        self.assertIn("Submit Proof and Close", panel)

        proof_service = (APP_ROOT / "services" / "delivery_proof.py").read_text()
        self.assertIn("def get_or_create_delivery_proof", proof_service)
        self.assertIn("def submit_delivery_proof", proof_service)
        self.assertIn('"Unattended Delivery Allowed"', proof_service)

        container_service = (APP_ROOT / "services" / "container_contents.py").read_text()
        genealogy = (APP_ROOT / "services" / "genealogy.py").read_text()
        genealogy_panel = (APP_ROOT / "cfg_kanban" / "page" / "material_genealogy" /
                           "material_genealogy.js").read_text()
        self.assertIn("def assert_container_not_in_open_delivery", container_service)
        self.assertIn('"delivery_allocations": _delivery_allocation_history', genealogy)
        self.assertIn("Customer Delivery Allocation History", genealogy_panel)

        gateway = (APP_ROOT / "integrations" / "erp_gateway.py").read_text()
        feedback = (APP_ROOT / "integrations" / "logistics_feedback.py").read_text()
        self.assertIn('@handler("Create Customer Delivery Note")', gateway)
        self.assertIn("def build_customer_delivery_note", gateway)
        self.assertIn("_on_customer_delivery_submit", feedback)
        self.assertIn("_on_customer_delivery_cancel", feedback)
        self.assertIn('event_type="Deliver"', feedback)
        self.assertIn('event_type="Customer Return"', feedback)

    def test_intercompany_erp_feedback_and_trace_fields_are_registered(self):
        hooks = (APP_ROOT / "hooks.py").read_text()
        install = (APP_ROOT / "install.py").read_text()
        gateway = (APP_ROOT / "integrations" / "erp_gateway.py").read_text()
        logistics = (APP_ROOT / "api" / "logistics.py").read_text()
        page_root = APP_ROOT / "cfg_kanban" / "page"
        logistics_panel = (page_root / "kanban_logistics" / "kanban_logistics.js").read_text()
        operator_panel = (page_root / "kanban_operator" / "kanban_operator.js").read_text()
        task_panel = (page_root / "kanban_tasks" / "kanban_tasks.js").read_text()
        self.assertIn('"Delivery Note": {', hooks)
        self.assertIn("on_delivery_note_submit", hooks)
        self.assertIn('"cfg_movement_manifest"', install)
        self.assertIn('@handler("Create Intercompany Delivery Note")', gateway)
        self.assertIn('@handler("Create Intercompany Purchase Receipt")', gateway)
        self.assertIn("build_intercompany_delivery_note", gateway)
        self.assertIn("get_required_erp_inputs", gateway)
        self.assertIn("apply_required_erp_inputs", gateway)
        self.assertIn("Sales Team allocated percentage must total 100%", gateway)
        self.assertIn("resolve_logistics_scan(scan_value)", logistics)
        self.assertIn("Receiving operator must scan every Manifest tag", logistics)
        self.assertIn("def get_dispatch_requirements", logistics)
        self.assertIn("def lookup_logistics_tag", logistics)
        self.assertIn('"recent_manifests"', logistics)
        self.assertIn("_dispatch_retry_available", logistics)
        self.assertIn('route["can_dispatch"]', logistics)
        self.assertIn('("Supervisor", "Development Proxy")', logistics)
        self.assertIn('scan_mode: "lookup"', logistics_panel)
        self.assertIn("Start Dispatch Scanning", logistics_panel)
        self.assertIn("Recently Completed", logistics_panel)
        self.assertIn("Done — Clear Screen", logistics_panel)
        self.assertIn("Scan / Change Operator", logistics_panel)
        self.assertIn("options?.restore && TERMINAL_STATES.has", logistics_panel)
        self.assertIn("def remove_dispatch_tag", logistics)
        self.assertIn("Manifest Dispatch Selection Removed", logistics)
        self.assertIn("line_name=None", logistics)
        self.assertIn('frappe.set_route("kanban-logistics")', operator_panel)
        self.assertIn('frappe.set_route("kanban-logistics")', task_panel)
        for panel in (logistics_panel, operator_panel, task_panel):
            self.assertIn("sync_session_from_storage", panel)
            self.assertIn("stored_token ===", panel)
        self.assertIn("Refresh Operator Session", operator_panel)

        card_controller = (APP_ROOT / "cfg_kanban" / "doctype" / "cfg_kanban_card" /
                           "cfg_kanban_card.py").read_text()
        card_form = (APP_ROOT / "public" / "js" / "cfg_kanban_card.js").read_text()
        self.assertIn("Service identity cards cannot use a Kanban Master", card_controller)
        self.assertIn('("Purchase Replenishment", "Transfer", "Withdrawal")', card_controller)
        self.assertIn("Task Schedule is not required", card_form)

    def test_card_and_cycle_capture_company_snapshot(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        for doctype in ("CFG Kanban Card", "CFG Kanban Cycle"):
            company = next(row for row in schemas[doctype]["fields"]
                           if row["fieldname"] == "company")
            self.assertEqual(company["options"], "Company")
            self.assertEqual(company.get("read_only"), 1)

    def test_non_stock_operational_inventory_uses_tag_ledger_without_erp_stock_entry(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        manifest_fields = {
            row["fieldname"]: row
            for row in schemas["CFG Kanban Movement Manifest"]["fields"]
        }
        logistics = (APP_ROOT / "api" / "logistics.py").read_text()
        foundation = (APP_ROOT / "services" / "logistics_foundation.py").read_text()
        transfer = (APP_ROOT / "services" / "internal_transfer.py").read_text()
        withdrawal = (APP_ROOT / "services" / "withdrawal.py").read_text()
        master = (APP_ROOT / "cfg_kanban" / "doctype" / "cfg_kanban_master" /
                  "cfg_kanban_master.py").read_text()
        panel = (APP_ROOT / "cfg_kanban" / "page" / "kanban_logistics" /
                 "kanban_logistics.js").read_text()
        self.assertIn("def _is_non_stock_operational_manifest", logistics)
        self.assertIn("def _confirm_non_stock_dispatch", logistics)
        self.assertIn("def _confirm_non_stock_receipt", logistics)
        self.assertIn('return "Required Physical Tag"', logistics)
        self.assertEqual(
            manifest_fields["inventory_control_mode"]["options"],
            "ERP Stock\nKanban Operational Inventory",
        )
        self.assertIn('"inventory_control_mode"', transfer)
        self.assertIn("ERPNext deliberately has no Bin/Stock Ledger balance", foundation)
        self.assertIn("maintains_stock and", transfer)
        self.assertIn("def _complete_non_stock_withdrawal", withdrawal)
        self.assertIn("NON_STOCK_TAG_POLICY", withdrawal)
        self.assertNotIn("Withdrawal control requires a stock Item", master)
        self.assertIn("Kanban operational inventory", panel)
        self.assertIn("Confirm Tagged Withdrawal", panel)

    def test_dashboard_profile_supports_saved_multi_workstation_screens(self):
        profile_path = ROOT / "cfg_kanban_dashboard_profile" / "cfg_kanban_dashboard_profile.json"
        profile = json.loads(profile_path.read_text())
        fields = {row["fieldname"]: row for row in profile["fields"]}
        self.assertEqual(fields["workstations"]["options"], "CFG Kanban Dashboard Workstation")
        self.assertTrue({"view_type", "access_mode", "queue_depth", "refresh_interval_seconds",
                         "column_count", "company", "warehouse", "customer", "item_group"}
                        .issubset(fields))

    def test_dispatch_queue_and_sequence_audit_are_persistent(self):
        queue_path = ROOT / "cfg_kanban_dispatch_queue" / "cfg_kanban_dispatch_queue.json"
        queue = json.loads(queue_path.read_text())
        queue_fields = {row["fieldname"]: row for row in queue["fields"]}
        self.assertEqual(queue_fields["process_execution"].get("unique"), 1)
        self.assertTrue({"item_code", "target_qty", "workstation", "dispatch_status", "queue_position", "system_priority",
                         "supervisor_priority", "expedite", "sequence_source",
                         "last_sequence_change"}.issubset(queue_fields))

        audit_path = ROOT / "cfg_kanban_sequence_change" / "cfg_kanban_sequence_change.json"
        audit = json.loads(audit_path.read_text())
        audit_fields = {row["fieldname"] for row in audit["fields"]}
        self.assertTrue({"queue_entry", "process_execution", "workstation", "action",
                         "old_position", "new_position", "reason", "changed_by", "changed_on"}
                        .issubset(audit_fields))

    def test_controlled_interruption_fields_and_erp_commands_are_present(self):
        profile_path = ROOT / "cfg_kanban_operation_profile" / "cfg_kanban_operation_profile.json"
        profile_fields = {row["fieldname"] for row in json.loads(profile_path.read_text())["fields"]}
        self.assertTrue({"interruption_policy", "setup_family", "cleaning_class"}
                        .issubset(profile_fields))

        queue_path = ROOT / "cfg_kanban_dispatch_queue" / "cfg_kanban_dispatch_queue.json"
        queue_fields = {row["fieldname"] for row in json.loads(queue_path.read_text())["fields"]}
        self.assertTrue({"paused_for_queue_entry", "pause_reason", "wip_disposition",
                         "machine_condition", "expected_resume_on", "erp_timer_was_active",
                         "paused_by", "paused_on"}
                        .issubset(queue_fields))

        command_path = ROOT / "cfg_erp_command" / "cfg_erp_command.json"
        command = json.loads(command_path.read_text())
        options = next(row for row in command["fields"]
                       if row["fieldname"] == "command_type")["options"].splitlines()
        self.assertIn("Pause Job Card", options)
        self.assertIn("Resume Job Card", options)

    def test_operator_identity_and_audit_fields_use_employee(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        profile = schemas["CFG Kanban Operator Profile"]
        fields = {row["fieldname"]: row for row in profile["fields"]}
        self.assertEqual(fields["employee"]["options"], "Employee")
        self.assertTrue(fields["employee"]["unique"])
        self.assertEqual(fields["employee_name"]["fetch_from"],
                         "employee.employee_name")
        self.assertTrue(fields["employee_name"]["in_list_view"])
        self.assertTrue({"qr_token_hash", "pin_required", "pin", "kanban_role",
                         "can_start", "can_complete", "can_report_reject",
                         "can_partial_complete", "can_override", "can_reopen",
                         "responsibilities", "view_all_responsibilities",
                         "allowed_workstations", "allowed_operations"}.issubset(fields))
        self.assertEqual(fields["responsibilities"]["options"],
                         "CFG Kanban Operator Responsibility")
        self.assertEqual(fields["view_all_responsibilities"]["label"],
                         "View All Service Tasks")

        workstation = {row["fieldname"]: row for row in
                       schemas["CFG Kanban Allowed Workstation"]["fields"]}
        operation = {row["fieldname"]: row for row in
                     schemas["CFG Kanban Allowed Operation"]["fields"]}
        self.assertTrue(workstation["workstation"]["in_list_view"])
        self.assertTrue(operation["operation"]["in_list_view"])

    def test_service_responsibility_is_independent_from_erp_roles(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        schedule = {row["fieldname"]: row for row in
                    schemas["CFG Kanban Task Schedule"]["fields"]}
        task = {row["fieldname"]: row for row in schemas["CFG Kanban Task"]["fields"]}
        child = {row["fieldname"]: row for row in
                 schemas["CFG Kanban Operator Responsibility"]["fields"]}
        self.assertEqual(schedule["responsible_role"]["options"],
                         "CFG Kanban Responsibility")
        self.assertEqual(task["responsible_role"]["options"],
                         "CFG Kanban Responsibility")
        self.assertEqual(child["responsibility"]["options"],
                         "CFG Kanban Responsibility")

        progress = {row["fieldname"]: row for row in
                    schemas["CFG Kanban Operation Progress"]["fields"]}
        self.assertEqual(progress["operator"]["options"], "Employee")
        self.assertEqual(progress["terminal_user"]["options"], "User")
        self.assertEqual(progress["operator_session"]["options"],
                         "CFG Kanban Operator Session")

        event = {row["fieldname"]: row for row in schemas["CFG Kanban Event"]["fields"]}
        self.assertEqual(event["operator"]["options"], "Employee")
        self.assertEqual(event["user"]["options"], "User")

    def test_operator_session_is_separate_from_erp_login(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        fields = {row["fieldname"]: row for row in
                  schemas["CFG Kanban Operator Session"]["fields"]}
        self.assertEqual(fields["employee"]["options"], "Employee")
        self.assertEqual(fields["terminal_user"]["options"], "User")
        self.assertTrue(fields["session_token_hash"]["hidden"])
        self.assertTrue({"last_activity_on", "expires_on", "ended_on", "active",
                         "end_reason"}.issubset(fields))

    def test_process_task_profiles_are_part_of_master_configuration(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        master = {row["fieldname"]: row for row in schemas["CFG Kanban Master"]["fields"]}
        self.assertEqual(master["process_task_profiles"]["options"],
                         "CFG Kanban Process Task Profile")
        profile = {row["fieldname"]: row for row in
                   schemas["CFG Kanban Process Task Profile"]["fields"]}
        self.assertTrue({"task_key", "task_name", "task_type", "linked_operation",
                         "trigger_point", "mandatory", "blocking", "workstation", "asset",
                         "require_supervisor_verification", "validity_duration_hours",
                         "reuse_while_valid", "completion_rule"}.issubset(profile))
        self.assertTrue({"qc_controlled", "enable_sample_traveller", "test_method",
                         "specification_reference", "allow_conditional_release"}
                        .issubset(profile))

    def test_process_task_runtime_is_auditable_and_filterable(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        task = {row["fieldname"]: row for row in
                schemas["CFG Kanban Process Task"]["fields"]}
        self.assertTrue({"kanban_cycle", "kanban_master", "task_key", "status",
                         "linked_process_execution", "assigned_employee", "started_by",
                         "completed_by", "execution_values", "verification_required",
                         "verified_by", "valid_until", "reused_from_task", "exception"}
                        .issubset(task))
        self.assertTrue({"item_code", "batch_no", "work_order", "process_qr_payload", "sample_id",
                         "sample_qr_payload", "qc_controlled", "qc_result",
                         "qc_disposition_notes", "qc_attempt", "qc_attempt_history",
                         "media_evidence_html"}.issubset(task))
        for fieldname in ("kanban_cycle", "task_name", "trigger_point", "status"):
            self.assertEqual(task[fieldname].get("in_list_view"), 1)
        event = {row["fieldname"]: row for row in schemas["CFG Kanban Event"]["fields"]}
        self.assertEqual(event["process_task"]["options"], "CFG Kanban Process Task")

    def test_dynamic_fields_support_operation_and_process_task_scopes(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        fields = {row["fieldname"]: row for row in
                  schemas["CFG Kanban Field Definition"]["fields"]}
        self.assertIn("Process Task", fields["definition_scope"]["options"].splitlines())
        self.assertIn("Verify", fields["capture_on"]["options"].splitlines())
        self.assertIn("process_task_key", fields)
        operator = {row["fieldname"] for row in
                    schemas["CFG Kanban Operator Profile"]["fields"]}
        self.assertIn("can_verify_tasks", operator)

    def test_standalone_task_domain_is_separate_from_production(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        schedule = {row["fieldname"]: row for row in
                    schemas["CFG Kanban Task Schedule"]["fields"]}
        self.assertTrue({"trigger_type", "interval_value", "next_due_on", "workstation",
                         "asset", "location", "task_field_definitions",
                         "require_supervisor_verification"}.issubset(schedule))
        self.assertTrue({"service_point_enabled", "service_point_code", "overlap_policy",
                         "holiday_policy", "holiday_list"}.issubset(schedule))
        self.assertEqual(schedule["task_field_definitions"]["options"],
                         "CFG Kanban Field Definition")
        task = {row["fieldname"]: row for row in schemas["CFG Kanban Task"]["fields"]}
        self.assertTrue({"task_schedule", "trigger_type", "generation_key", "status",
                         "requested_on", "due_on", "assigned_employee", "checklist_results",
                         "checklist_evidence", "execution_values", "verified_by",
                         "verification_status", "verification_notes", "exception"}.issubset(task))
        self.assertTrue({"supervisor_disposition", "disposition_by", "disposition_on",
                         "disposition_reason"}.issubset(task))
        self.assertTrue({"progress_count", "last_progress_by", "last_progress_on",
                         "last_progress_summary"}.issubset(task))
        self.assertEqual(task["checklist_evidence"]["options"],
                         "CFG Kanban Checklist Result")
        self.assertIn("Correction Required", task["status"]["options"].splitlines())
        self.assertTrue(task["work_order"].get("hidden"))
        self.assertTrue(task["job_card"].get("hidden"))

        evidence = {row["fieldname"]: row for row in
                    schemas["CFG Kanban Checklist Result"]["fields"]}
        self.assertTrue({"item_key", "item", "result", "captured_by", "captured_on"}
                        .issubset(evidence))

        execution_value = {row["fieldname"]: row for row in
                           schemas["CFG Kanban Execution Value"]["fields"]}
        self.assertTrue({"capture_on", "captured_by", "captured_on"}
                        .issubset(execution_value))

    def test_card_identity_supports_asset_location_and_task_behaviours(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        card = {row["fieldname"]: row for row in schemas["CFG Kanban Card"]["fields"]}
        options = card["card_type"]["options"].splitlines()
        self.assertTrue({"Asset Card", "Location Card", "Task Card"}.issubset(options))
        self.assertTrue({"card_behavior", "asset", "location_reference", "location_purpose",
                         "task_schedule"}
                        .issubset(card))
        self.assertFalse(card["kanban_master"].get("reqd", 0))

    def test_events_and_exceptions_link_both_task_domains(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        for doctype in ("CFG Kanban Event", "CFG Kanban Exception"):
            fields = {row["fieldname"]: row for row in schemas[doctype]["fields"]}
            self.assertEqual(fields["process_task"]["options"], "CFG Kanban Process Task")
            self.assertEqual(fields["standalone_task"]["options"], "CFG Kanban Task")

    def test_customer_return_workflows_separate_qc_custody_from_dn_correction(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        parent = {row["fieldname"]: row for row in
                  schemas["CFG Kanban Return Case"]["fields"]}
        self.assertTrue({
            "customer_scan_point", "original_delivery_session", "original_delivery_note",
            "delivery_proof", "selling_company", "customer", "site_code", "return_flow",
            "scan_token", "inspection_location", "correction_return_warehouse", "lines",
            "claimed_total_qty", "qc_operator", "qc_completed_on", "accounting_status",
            "accounting_source_basis", "correction_return_delivery_note", "idempotency_key",
            "customer_acknowledgement_name", "customer_acknowledged_on",
            "accounting_decided_by", "accounting_decided_on", "accounting_decision_notes",
            "credit_document_status", "accounting_revision",
            "disposition_status", "disposition_lines", "stock_disposition_entry",
            "stock_disposition_entry_status", "disposition_decided_by",
            "disposition_decided_on", "disposition_notes", "disposition_revision",
        }.issubset(parent))
        self.assertEqual(parent["lines"]["options"], "CFG Kanban Return Line")
        self.assertEqual(parent["disposition_lines"]["options"],
                         "CFG Kanban Return Disposition Line")
        self.assertTrue(parent["idempotency_key"].get("unique"))
        child = {row["fieldname"]: row for row in
                 schemas["CFG Kanban Return Line"]["fields"]}
        self.assertTrue({
            "original_delivery_allocation", "original_delivery_note_item", "original_handling_unit",
            "original_visible_code", "item_code", "batch_no", "expiry_date", "stock_uom",
            "delivered_qty", "claimed_qty", "received_qty", "accepted_qty",
            "rejected_qty", "condition", "qc_disposition", "qc_reason",
        }.issubset(child))
        event = {row["fieldname"]: row for row in schemas["CFG Kanban Event"]["fields"]}
        self.assertEqual(event["return_case"]["options"], "CFG Kanban Return Case")

        service = (APP_ROOT / "services" / "customer_returns.py").read_text()
        self.assertIn('"Customer Return for QC"', service)
        self.assertIn('"Delivery Note Correction"', service)
        self.assertIn("inspection custody", service.lower())
        self.assertNotIn("temporary_credit_note", service)
        self.assertIn("complete_qc_inspection", service)
        self.assertNotIn("bagos_changes", service)

        media_service = (APP_ROOT / "services" / "media.py").read_text()
        self.assertIn('"customer-return-evidence": {"CFG Kanban Return Case"}',
                      media_service)
        media_api = (APP_ROOT / "api" / "media.py").read_text()
        self.assertIn("create_return_case_upload_url", media_api)
        self.assertIn("archive_return_case_media", media_api)

        gateway = (APP_ROOT / "integrations" / "erp_gateway.py").read_text()
        self.assertIn('@handler("Create Correction Return Delivery Note")', gateway)
        self.assertIn('@handler("Create Customer Credit Return")', gateway)
        self.assertIn("make_return_doc", gateway)

        accounting = (APP_ROOT / "integrations" / "return_accounting_feedback.py").read_text()
        self.assertIn("Customer Credit Return Submitted", accounting)
        self.assertIn("must not update stock", accounting)
        hooks = (APP_ROOT / "hooks.py").read_text()
        self.assertIn('"CFG Kanban Return Case": "public/js/cfg_kanban_return_case.js"', hooks)
        self.assertIn('"Sales Invoice": {', hooks)
        self.assertIn("return_accounting_feedback.on_submit", hooks)
        self.assertIn("return_accounting_feedback.on_cancel", hooks)
        install = (APP_ROOT / "install.py").read_text()
        self.assertIn('"cfg_return_case"', install)
        self.assertIn('"cfg_return_disposition_line"', install)

        disposition = (APP_ROOT / "services" / "return_disposition.py").read_text()
        self.assertIn("Dispose Without Stock Receipt", disposition)
        self.assertIn("Create Customer Return Material Receipt", disposition)
        stock_feedback = (APP_ROOT / "integrations" / "return_stock_feedback.py").read_text()
        self.assertIn("Customer Return Stock Disposition Posted", stock_feedback)
        self.assertIn("Material Receipt quantity cannot differ", stock_feedback)
        self.assertIn('@handler("Create Customer Return Material Receipt")', gateway)

        disposition_child = {row["fieldname"]: row for row in
                             schemas["CFG Kanban Return Disposition Line"]["fields"]}
        self.assertTrue({
            "return_line", "item_code", "batch_no", "stock_uom", "qty", "disposition",
            "target_warehouse", "valuation_rate", "reason", "status", "stock_entry_detail",
        }.issubset(disposition_child))

    def test_l2_withdrawal_uses_controlled_material_issue(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        master = {row["fieldname"]: row for row in
                  schemas["CFG Kanban Master"]["fields"]}
        cycle = {row["fieldname"]: row for row in
                 schemas["CFG Kanban Cycle"]["fields"]}
        allocation = {row["fieldname"]: row for row in
                      schemas["CFG Kanban Withdrawal Allocation"]["fields"]}
        self.assertTrue({"withdrawal_reason", "auto_submit_withdrawal_stock_entry"}
                        .issubset(master))
        self.assertTrue({"withdrawal_status", "withdrawal_stock_entry",
                         "withdrawal_command", "withdrawal_tag_policy",
                         "withdrawal_allocations"}.issubset(cycle))
        self.assertEqual(cycle["withdrawal_allocations"]["options"],
                         "CFG Kanban Withdrawal Allocation")
        self.assertTrue({"line_kind", "handling_unit", "qty", "state",
                         "reserved_ledger", "consumed_ledger"}.issubset(allocation))

        gateway = (APP_ROOT / "integrations" / "erp_gateway.py").read_text()
        feedback = (APP_ROOT / "integrations" / "erp_feedback.py").read_text()
        trigger = (APP_ROOT / "services" / "triggers.py").read_text()
        service = (APP_ROOT / "services" / "withdrawal.py").read_text()
        logistics = (APP_ROOT / "api" / "logistics.py").read_text()
        panel = (APP_ROOT / "cfg_kanban" / "page" / "kanban_logistics" /
                 "kanban_logistics.js").read_text()
        install = (APP_ROOT / "install.py").read_text()
        self.assertIn('@handler("Create Kanban Stock Withdrawal")', gateway)
        self.assertIn('"stock_entry_type": "Material Issue"', gateway)
        self.assertIn("validate_withdrawal_stock_entry", feedback)
        self.assertIn('"Withdrawal": "Stock Withdrawal"', trigger)
        self.assertIn("get_default_naming_series", gateway)
        self.assertIn('doc.naming_series = get_default_naming_series(doc.doctype)', gateway)
        self.assertIn('["name", "docstatus"]', service)
        self.assertNotIn('["name", "status", "docstatus"]', service)
        self.assertIn("def prepare_withdrawal", service)
        self.assertIn("def complete_withdrawal", service)
        self.assertIn("def discard_withdrawal_draft", service)
        self.assertIn("def trigger_withdrawal_card", logistics)
        self.assertIn("render_withdrawal_card", panel)
        self.assertIn('"cfg_withdrawal_cycle"', install)
        self.assertIn('"cfg_withdrawal_allocation"', install)
