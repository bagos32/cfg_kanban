app_name = "cfg_kanban"
app_title = "CFG Kanban"
app_publisher = "CFG"
app_description = "Kanban process-control layer for ERPNext manufacturing"
app_email = "engineering@example.com"
app_license = "MIT"
required_apps = ["erpnext"]

fixtures = [
    {
        "dt": "Custom Field",
        "filters": [["module", "=", "CFG Kanban"]],
    }
]

doc_events = {
    "Work Order": {
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
        "on_submit": "cfg_kanban.integrations.erp_feedback.on_stock_entry_submit",
        "on_cancel": "cfg_kanban.integrations.erp_feedback.on_stock_entry_cancel",
    },
}

after_install = "cfg_kanban.install.after_install"

