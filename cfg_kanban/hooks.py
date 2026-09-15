app_name = "cfg_kanban"
app_title = "CFG Kanban"
app_publisher = "CFG"
app_description = "Kanban process-control layer for ERPNext manufacturing"
app_email = "engineering@example.com"
app_license = "MIT"
required_apps = ["erpnext"]

doctype_js = {
    "CFG Kanban Master": "public/js/cfg_kanban_master.js",
    "CFG Kanban Dashboard Profile": "public/js/cfg_kanban_dashboard_profile.js",
    "Work Order": "public/js/work_order.js",
    "Sales Order": "public/js/sales_order.js",
    "CFG Kanban Card": "public/js/cfg_kanban_card.js",
    "CFG Kanban Signal": "public/js/cfg_kanban_signal.js",
    "CFG Kanban Process Execution": "public/js/cfg_kanban_process_execution.js",
    "CFG Kanban Cycle": "public/js/cfg_kanban_cycle.js",
    "CFG Kanban Handling Unit": "public/js/cfg_kanban_handling_unit.js",
    "CFG Kanban Demand": "public/js/cfg_kanban_demand.js",
}

jinja = {
    "methods": [
        "cfg_kanban.services.printing.get_card_route",
        "cfg_kanban.services.printing.get_card_print_context",
        "cfg_kanban.services.printing.get_qr_svg",
        "cfg_kanban.services.printing.get_code128_svg",
    ]
}

fixtures = [
    {
        "dt": "Custom Field",
        "filters": [["module", "=", "CFG Kanban"]],
    }
]

doc_events = {
    "CFG Kanban Process Execution": {
        "on_update": "cfg_kanban.services.dispatch.on_execution_update",
    },
    "Sales Order": {
        "on_submit": "cfg_kanban.integrations.sales_order_feedback.on_submit",
        "on_update_after_submit": "cfg_kanban.integrations.sales_order_feedback.on_update_after_submit",
        "on_cancel": "cfg_kanban.integrations.sales_order_feedback.on_cancel",
    },
    "Work Order": {
        "before_submit": "cfg_kanban.integrations.erp_feedback.prepare_work_order",
        "on_update": "cfg_kanban.integrations.erp_feedback.on_work_order_update",
        "on_submit": "cfg_kanban.integrations.erp_feedback.on_work_order_update",
        "on_cancel": "cfg_kanban.integrations.erp_feedback.on_work_order_cancel",
    },
    "Job Card": {
        "on_update": "cfg_kanban.integrations.erp_feedback.on_job_card_update",
        "on_submit": "cfg_kanban.integrations.erp_feedback.on_job_card_update",
        "on_cancel": "cfg_kanban.integrations.erp_feedback.on_job_card_cancel",
    },
    "Stock Entry": {
        "before_submit": "cfg_kanban.integrations.erp_feedback.validate_stock_entry",
        "on_submit": "cfg_kanban.integrations.erp_feedback.on_stock_entry_submit",
        "on_cancel": "cfg_kanban.integrations.erp_feedback.on_stock_entry_cancel",
    },
}

after_install = "cfg_kanban.install.after_install"
after_migrate = "cfg_kanban.install.after_migrate"
