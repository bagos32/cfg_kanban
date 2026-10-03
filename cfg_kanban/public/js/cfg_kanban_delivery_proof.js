frappe.ui.form.on("CFG Kanban Delivery Proof", {
	refresh(frm) {
		render_delivery_proof_media(frm);
	},
});

async function render_delivery_proof_media(frm) {
	const field = frm.get_field("media_evidence_html");
	if (!field || frm.is_new()) return;
	const $wrapper = field.$wrapper;
	$wrapper.html(`<div class="text-muted">${__("Loading private delivery evidence...")}</div>`);
	try {
		const response = await frappe.call({
			method: "cfg_kanban.api.media.get_reference_gallery",
			args: { reference_doctype: frm.doctype, reference_name: frm.docname },
		});
		const rows = response.message || [];
		if (!rows.length) {
			$wrapper.html(`<div class="text-muted">${__("No private delivery evidence is attached.")}</div>`);
			return;
		}
		const e = frappe.utils.escape_html;
		$wrapper.html(`<div class="cfg-task-media-gallery">${rows.map((row) => `<article class="frappe-card cfg-task-media-card">
			<div class="cfg-task-media-preview">${row.preview_url && (row.content_type || "").startsWith("image/") ? `<img src="${e(row.preview_url)}" alt="${e(row.original_filename)}" loading="lazy">` : `<div class="cfg-task-media-file-icon">${e(row.evidence_kind || "FILE")}</div>`}</div>
			<div class="cfg-task-media-details"><strong>${e(row.evidence_kind || "attachment")} · ${e(row.original_filename)}</strong>
			<small>${e(row.content_type || "-")} · ${delivery_media_bytes(row.size_bytes)}</small>
			<small>${__("Captured by")}: ${e(row.operator_employee || row.created_by || "-")}</small>
			${row.capture_timestamp ? `<small>${__("Captured")}: ${e(row.capture_timestamp)}</small>` : ""}
			${row.geotag ? `<small>GPS: ${e(row.geotag.latitude)}, ${e(row.geotag.longitude)} · ±${e(row.geotag.accuracy_metres || 0)}m</small>` : ""}</div>
			<button type="button" class="btn btn-default cfg-open-delivery-media" data-media-id="${e(row.media_id)}">${__("Open Original")}</button>
		</article>`).join("")}</div>`);
		$wrapper.find(".cfg-open-delivery-media").on("click", async function () {
			const view = await frappe.call({ method: "cfg_kanban.api.media.create_view_url", args: { media_id: $(this).data("media-id") } });
			window.open(view.message.url, "_blank", "noopener");
		});
	} catch (error) {
		$wrapper.html(`<div class="alert alert-warning">${__("Private delivery evidence could not be loaded. Confirm permission and media configuration.")}</div>`);
	}
}

function delivery_media_bytes(value) {
	const bytes = Number(value || 0);
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
