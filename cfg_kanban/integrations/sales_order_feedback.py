from cfg_kanban.services.sales_demand import cancel_sales_order_demands, evaluate_sales_order


def on_submit(doc, method=None):
    evaluate_sales_order(doc)


def on_update_after_submit(doc, method=None):
    evaluate_sales_order(doc)


def on_cancel(doc, method=None):
    cancel_sales_order_demands(doc)
