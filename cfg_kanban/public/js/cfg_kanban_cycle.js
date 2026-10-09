frappe.ui.form.on("CFG Kanban Cycle", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("New Handling Unit"), () => {
			frappe.route_options = { kanban_cycle: frm.doc.name };
			frappe.new_doc("CFG Kanban Handling Unit");
		}, __("Create"));
		if (frm.doc.work_order) {
			frm.add_custom_button(__("Open Work Order"), () =>
				frappe.set_route("Form", "Work Order", frm.doc.work_order), __("View"));
		}
		if (frm.doc.material_request) {
			frm.add_custom_button(__("Open Material Request"), () =>
				frappe.set_route("Form", "Material Request", frm.doc.material_request), __("View"));
			if (["Purchase Order Draft", "Purchase Attention Required"].includes(frm.doc.purchase_status) &&
				["Manufacturing Manager", "Purchase Manager", "System Manager"].some((role) => frappe.user_roles.includes(role))) {
				frm.add_custom_button(__("Retry Purchase Automation"), async () => {
					const response = await frappe.call({ method: "cfg_kanban.api.purchase.retry_purchase_execution",
						args: { cycle_name: frm.doc.name }, freeze: true,
						freeze_message: __("Retrying controlled Purchase Order automation...") });
					const result = response.message || {};
					frappe.show_alert({ message: __("Purchase result: {0}", [result.status || result.purchase_order]),
						indicator: result.status === "Purchase Attention Required" ? "orange" : "green" }, 8);
					frm.reload_doc();
				}, __("Purchase Replenishment"));
			}
		}
		if (frm.doc.purchase_order) {
			frm.add_custom_button(__("Open Purchase Order"), () =>
				frappe.set_route("Form", "Purchase Order", frm.doc.purchase_order), __("View"));
			if (!["Completed", "Cancelled", "Blocked"].includes(frm.doc.status) && (frm.doc.outstanding_qty || 0) > 0) {
				frm.add_custom_button(__("Receive Purchased Item"), async () => {
				const response = await frappe.call({ method: "cfg_kanban.api.purchase.get_receipt_context",
					args: { cycle_name: frm.doc.name } });
				const context = response.message;
				frappe.prompt([
					{ fieldname: "uom_summary", fieldtype: "HTML", options:
						`<div class="alert alert-info"><strong>${__("Purchase UOM")}: ${frappe.utils.escape_html(context.purchase_uom)}</strong><br>
						${__("1 {0} = {1} {2}", [context.purchase_uom, context.conversion_factor, context.stock_uom])}<br>
						${__("Outstanding: {0} {1} = {2} {3}", [context.outstanding_qty, context.purchase_uom,
							context.outstanding_stock_qty, context.stock_uom])}</div>` },
					{ fieldname: "delivered_qty", label: __("Delivered Qty ({0})", [context.purchase_uom]), fieldtype: "Float", reqd: 1, default: context.outstanding_qty },
					{ fieldname: "accepted_qty", label: __("Accepted Qty ({0})", [context.purchase_uom]), fieldtype: "Float", reqd: 1, default: context.outstanding_qty },
					{ fieldname: "rejected_qty", label: __("Rejected Qty ({0})", [context.purchase_uom]), fieldtype: "Float", default: 0 },
					{ fieldname: "warehouse", label: __("Accepted Warehouse"), fieldtype: "Link", options: "Warehouse", reqd: 1, default: context.warehouse },
					{ fieldname: "rejected_warehouse", label: __("Rejected Warehouse"), fieldtype: "Link", options: "Warehouse", default: context.rejected_warehouse },
					{ fieldname: "supplier_delivery_note", label: __("Supplier Delivery Note"), fieldtype: "Data" },
				], async (values) => {
					const result = await frappe.call({ method: "cfg_kanban.api.purchase.receive_purchase",
						args: { cycle_name: frm.doc.name, ...values, event_token: frappe.utils.get_random(16) },
						freeze: true, freeze_message: __("Creating Purchase Receipt...") });
					frappe.set_route("Form", "Purchase Receipt", result.message.purchase_receipt);
				}, __("Receive against {0}", [context.purchase_order]), __("Create Purchase Receipt"));
				}, __("Purchase Replenishment"));
			}
			frm.add_custom_button(__("Refresh Receipt Result"), async () => {
				await frappe.call({ method: "cfg_kanban.api.purchase.refresh_receipt_disposition",
					args: { cycle_name: frm.doc.name }, freeze: true,
					freeze_message: __("Reconciling submitted Purchase Receipts and returns...") });
				frm.reload_doc();
			}, __("Purchase Replenishment"));
			if (frm.doc.receipt_disposition_status === "Open") {
				frm.add_custom_button(__("Open Receipt Dispositions"), () => {
					frappe.route_options = { kanban_cycle: frm.doc.name };
					frappe.set_route("List", "CFG Kanban Receipt Disposition");
				}, __("Purchase Replenishment"));
			}
			if ((frm.doc.outstanding_purchase_qty || 0) > 0 &&
				["Manufacturing Manager", "Purchase Manager", "Stock Manager", "System Manager"]
					.some((role) => frappe.user_roles.includes(role))) {
				frm.add_custom_button(__("Short-close Usable Shortage"), () => {
					frappe.prompt([
						{ fieldname: "warning", fieldtype: "HTML", options: `<div class="alert alert-warning">${__("This releases the purchase Kanban card without receiving the remaining usable quantity. It does not remove rejected stock from its warehouse or create a supplier credit.")}</div>` },
						{ fieldname: "qty", label: __("Short-close Qty ({0})", [frm.doc.purchase_uom]), fieldtype: "Float", reqd: 1, default: frm.doc.outstanding_purchase_qty },
						{ fieldname: "reason", label: __("Supervisor Reason"), fieldtype: "Small Text", reqd: 1 },
					], async (values) => {
						await frappe.call({ method: "cfg_kanban.api.purchase.short_close_purchase_cycle",
							args: { cycle_name: frm.doc.name, qty: values.qty, reason: values.reason },
							freeze: true, freeze_message: __("Applying controlled short close...") });
						frm.reload_doc();
					}, __("Short-close Purchase Replenishment"), __("Confirm Short Close"));
				}, __("Purchase Replenishment"));
			}
		}
		if (frm.doc.purchase_status && !frm.doc.purchase_order &&
			["Manufacturing Manager", "Purchase Manager", "System Manager"].some((role) => frappe.user_roles.includes(role))) {
			frm.add_custom_button(__("Select Purchase Order"), () => {
				frappe.prompt([
					{ fieldname: "purchase_order", label: __("Submitted Purchase Order"), fieldtype: "Link", options: "Purchase Order", reqd: 1,
						get_query: () => ({ filters: { supplier: frm.doc.supplier, docstatus: 1 } }) },
					{ fieldname: "reason", label: __("Selection Reason"), fieldtype: "Small Text", reqd: 1 },
				], async (values) => {
					await frappe.call({ method: "cfg_kanban.api.purchase.select_purchase_order",
						args: { cycle_name: frm.doc.name, purchase_order_name: values.purchase_order, reason: values.reason },
						freeze: true, freeze_message: __("Validating Purchase Order...") });
					frm.reload_doc();
				}, __("Select Effective Purchase Order"), __("Link Purchase Order"));
			}, __("Purchase Replenishment"));
		}
		if (["Manufacturing Manager", "System Manager"].some((role) => frappe.user_roles.includes(role))) {
			if (frm.doc.kanban_card && !frm.doc.runtime_allocation &&
				!["Completed", "Cancelled"].includes(frm.doc.status)) {
				frm.add_custom_button(__("Release Legacy Runtime Card"), () => {
					frappe.prompt([
						{ fieldname: "reason", label: __("Recovery Reason"), fieldtype: "Small Text", reqd: 1,
							description: __("Allowed only when no production, progress, stock, or WIP activity exists.") },
					], async (values) => {
						const response = await frappe.call({
							method: "cfg_kanban.integrations.erp_feedback.release_legacy_runtime_card",
							args: { cycle_name: frm.doc.name, reason: values.reason },
							freeze: true, freeze_message: __("Checking activity and releasing reusable Card..."),
						});
						frappe.msgprint(__("Cycle {0} was cancelled and Card {1} is Available. Work Order {2} was preserved.",
							[response.message.cycle, response.message.card, response.message.work_order || "-"]));
						frm.reload_doc();
					}, __("Release Incorrect Legacy Mapping"), __("Release Card"));
				}, __("Kanban Recovery"));
			}
			frm.add_custom_button(__("Resolve Effective Work Order"), () => {
				frappe.prompt([
					{ fieldname: "work_order", label: __("Effective Work Order"), fieldtype: "Link", options: "Work Order", reqd: 1,
						get_query: () => ({ filters: { production_item: frm.doc.item_code, docstatus: 1 } }) },
					{ fieldname: "reason", label: __("Reconciliation Reason"), fieldtype: "Small Text", reqd: 1 },
				], async (values) => {
					const response = await frappe.call({
						method: "cfg_kanban.integrations.erp_feedback.select_effective_work_order",
						args: { cycle_name: frm.doc.name, work_order_name: values.work_order, reason: values.reason },
						freeze: true, freeze_message: __("Resolving effective Work Order..."),
					});
					frappe.show_alert({ message: __("Effective Work Order {0} selected with {1} Job Card(s)",
						[response.message.work_order, response.message.job_cards]), indicator: "green" });
					frm.reload_doc();
				}, __("Resolve Work Order Ambiguity"), __("Confirm"));
			}, __("Kanban Recovery"));
		}
		if (frm.doc.batch_no) {
			frm.add_custom_button(__("Open Batch"), () =>
				frappe.set_route("Form", "Batch", frm.doc.batch_no), __("View"));
		}
		frm.add_custom_button(__("Show Event Timeline"), async () => {
			const response = await frappe.call({ method: "cfg_kanban.api.operator.get_cycle_timeline",
				args: { cycle_name: frm.doc.name } });
			const escape = frappe.utils.escape_html;
			const html = response.message.events.map((event) => `<div class="mb-3">
				<strong>${escape(event.event_type)}</strong> <span class="text-muted">${escape(event.event_datetime)}</span>
				<div>${escape(event.previous_state || "")} ${event.new_state ? "→ " + escape(event.new_state) : ""}</div>
			</div>`).join("");
			const dialog = new frappe.ui.Dialog({ title: __("Kanban Event Timeline"), size: "large" });
			dialog.$body.html(html || __("No events recorded yet."));
			dialog.show();
		});
	},
});
