frappe.ui.form.on("CFG Kanban DocType Action Run", {
	refresh(frm) {
		if (frm.is_new()) return;
		render_action_run_media(frm);
		if (!["Posting", "Submitted", "Skipped by Condition", "Needs Reconciliation", "Cancelled"].includes(frm.doc.state)
			&& !frm.doc.target_name) {
			frm.add_custom_button(__("Cancel Run with Reason"), () =>
				run_supervisor_action(frm, "cancel", __("Cancel DocType Action Run"),
					__("Cancellation Reason"), __("Cancel Run")), __("Recovery"));
		}
		if (!["Cancelled", "Skipped by Condition", "Needs Reconciliation"].includes(frm.doc.state)) {
			frm.add_custom_button(__("Mark Needs Reconciliation"), () =>
				run_supervisor_action(frm, "require_reconciliation",
					__("Require Supervised Reconciliation"), __("Reconciliation Reason"),
					__("Mark for Reconciliation")), __("Recovery"));
		}
	},
});

async function render_action_run_media(frm) {
	const field = frm.get_field("media_evidence_html");
	if (!field) return;
	const $wrapper = field.$wrapper;
	if (frm.doc.source_doctype !== "CFG Kanban Card") {
		$wrapper.html(`<div class="text-muted">${__("This Action Run uses private evidence from its exact source Service Task occurrence. Open the linked Task to view the gallery.")}</div>`);
		return;
	}
	$wrapper.html(`<div class="text-muted">${__("Loading direct Action Run evidence...")}</div>`);
	try {
		const response = await frappe.call({
			method: "cfg_kanban.api.media.get_reference_gallery",
			args: { reference_doctype: frm.doctype, reference_name: frm.docname },
		});
		const rows = response.message || [];
		$wrapper.html(action_run_media_gallery_html(rows));
		$wrapper.find(".cfg-open-action-run-media").on("click", async function () {
			const $button = $(this).prop("disabled", true);
			try {
				const view = await frappe.call({
					method: "cfg_kanban.api.media.create_view_url",
					args: { media_id: $button.data("media-id") },
				});
				window.open(view.message.url, "_blank", "noopener");
			} finally {
				$button.prop("disabled", false);
			}
		});
	} catch (error) {
		$wrapper.html(`<div class="alert alert-warning">${__("Private Action Run evidence could not be loaded. Confirm your permission and media configuration.")}</div>`);
	}
}

function action_run_media_gallery_html(rows) {
	if (!rows.length) {
		return `<div class="text-muted">${__("No private media evidence belongs to this Action Run.")}</div>`;
	}
	const e = frappe.utils.escape_html;
	return `<div class="cfg-task-media-gallery">${rows.map((row) => {
		const preview = row.preview_url && (row.content_type || "").startsWith("image/")
			? `<img src="${e(row.preview_url)}" alt="${e(row.original_filename)}" loading="lazy">`
			: `<div class="cfg-task-media-file-icon">${e(row.evidence_kind || "FILE")}</div>`;
		return `<article class="frappe-card cfg-task-media-card">
			<div class="cfg-task-media-preview">${preview}</div>
			<div class="cfg-task-media-details"><strong>${e(row.original_filename || row.media_id)}</strong>
				<small>${e(row.content_type || "-")} · ${action_run_media_bytes(row.size_bytes)}</small>
				<small>${__("Captured by")}: ${e(row.operator_employee || row.created_by || "-")}</small>
				<small>${e(row.capture_timestamp || row.confirmed_at || row.created_at || "-")}</small>
				${row.geotag ? `<small><strong>GPS</strong>: ${e(row.geotag.latitude)}, ${e(row.geotag.longitude)} · ±${e(row.geotag.accuracy_metres || 0)}m</small>` : ""}
				<small>${__("Media ID")}: ${e(row.media_id)}</small></div>
			<button type="button" class="btn btn-default cfg-open-action-run-media" data-media-id="${e(row.media_id)}">${__("Open Original")}</button>
		</article>`;
	}).join("")}</div>`;
}

function action_run_media_bytes(value) {
	const bytes = Number(value || 0);
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function run_supervisor_action(frm, method, title, reason_label, primary_label) {
	const operator_session_token = localStorage.getItem("cfg_kanban_operator_session");
	if (!operator_session_token) {
		frappe.msgprint(__("Identify an authorized Supervisor in the Service Task Panel before using Action Run recovery."));
		return;
	}
	frappe.prompt([
		{ fieldname: "reason", label: reason_label, fieldtype: "Small Text", reqd: 1 },
	], async (values) => {
		await frappe.call({
			method: `cfg_kanban.api.doctype_action_run.${method}`,
			args: {
				run_name: frm.doc.name,
				reason: values.reason,
				operator_session_token,
				retry_token: frappe.utils.get_random(24),
			},
			freeze: true,
			freeze_message: __("Applying controlled Action Run recovery..."),
		});
		await frm.reload_doc();
	}, title, primary_label);
}
