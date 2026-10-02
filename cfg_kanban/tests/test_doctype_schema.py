import json
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1] / "cfg_kanban" / "doctype"
APP_ROOT = Path(__file__).resolve().parents[1]


class TestDocTypeSchema(TestCase):
    def _schemas(self):
        for path in ROOT.glob("*/*.json"):
            yield path, json.loads(path.read_text())

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
        self.assertEqual(shortcuts["Maintenance Register"],
                         "Kanban Maintenance Register")
        self.assertEqual(shortcuts["Private Media Evidence"], "CFG Kanban Media")
        self.assertEqual(shortcuts["Operator Profiles"], "CFG Kanban Operator Profile")
        self.assertEqual(links["Logistics Routes"], "CFG Kanban Logistics Route")
        self.assertEqual(links["Customer Scan Points"], "CFG Kanban Customer Scan Point")
        self.assertEqual(links["Stock Tag Families"], "CFG Kanban Tag Family")
        self.assertEqual(links["Stock Tag Range Registries"],
                         "CFG Kanban Tag Range Registry")
        self.assertEqual(shortcuts["Stock Tag Range Registries"],
                         "CFG Kanban Tag Range Registry")
        self.assertEqual(shortcuts["Handling Unit Quantity Ledger"],
                         "CFG Kanban Handling Unit Quantity Ledger")
        self.assertEqual(links["Movement Manifests"],
                         "CFG Kanban Movement Manifest")
        self.assertEqual(links["Material Trace Policies"],
                         "CFG Kanban Material Trace Policy")
        self.assertEqual(shortcuts["Material Trace Policies"],
                         "CFG Kanban Material Trace Policy")

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
                         "receipt_posting_mode", "allow_partial_receipt",
                         "over_receipt_tolerance_pct", "rejected_warehouse"}.issubset(master))
        cycle = {row["fieldname"] for row in schemas["CFG Kanban Cycle"]["fields"]}
        self.assertTrue({"supplier", "material_request", "purchase_order",
                         "purchase_order_item", "latest_purchase_receipt", "ordered_qty",
                         "received_qty", "outstanding_qty", "purchase_status"}.issubset(cycle))
        commands = next(row for row in schemas["CFG ERP Command"]["fields"]
                        if row["fieldname"] == "command_type")["options"].splitlines()
        self.assertIn("Create Material Request", commands)
        self.assertIn("Create Purchase Receipt", commands)

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
                          "production_output_tag_policy"):
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
        self.assertIn("Tag Received Material", form)
        self.assertIn("No Physical Tag remain valid ERPNext warehouse stock", form)

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
        self.assertIn('frappe.set_route("kanban-logistics")', operator_panel)
        self.assertIn('frappe.set_route("kanban-logistics")', task_panel)
        for panel in (logistics_panel, operator_panel, task_panel):
            self.assertIn("sync_session_from_storage", panel)
            self.assertIn("stored_token ===", panel)
        self.assertIn("Refresh Operator Session", operator_panel)

    def test_card_and_cycle_capture_company_snapshot(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        for doctype in ("CFG Kanban Card", "CFG Kanban Cycle"):
            company = next(row for row in schemas[doctype]["fields"]
                           if row["fieldname"] == "company")
            self.assertEqual(company["options"], "Company")
            self.assertEqual(company.get("read_only"), 1)

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
        self.assertTrue({"card_behavior", "asset", "location_reference", "task_schedule"}
                        .issubset(card))
        self.assertFalse(card["kanban_master"].get("reqd", 0))

    def test_events_and_exceptions_link_both_task_domains(self):
        schemas = {schema["name"]: schema for _, schema in self._schemas()}
        for doctype in ("CFG Kanban Event", "CFG Kanban Exception"):
            fields = {row["fieldname"]: row for row in schemas[doctype]["fields"]}
            self.assertEqual(fields["process_task"]["options"], "CFG Kanban Process Task")
            self.assertEqual(fields["standalone_task"]["options"], "CFG Kanban Task")
