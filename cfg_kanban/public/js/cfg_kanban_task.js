frappe.ui.form.on("CFG Kanban Task", {
	refresh(frm) {
		render_private_media(frm);
	},
});

async function render_private_media(frm) {
	const field = frm.get_field("media_evidence_html");
	if (!field) return;
	const $wrapper = field.$wrapper;
	if (frm.is_new()) {
		$wrapper.html(`<div class="text-muted">${__("Save the task before attaching media evidence.")}</div>`);
		return;
	}
	$wrapper.html(`<div class="text-muted">${__("Loading private media evidence...")}</div>`);
	try {
		const response = await frappe.call({
			method: "cfg_kanban.api.media.get_reference_gallery",
			args: { reference_doctype: frm.doctype, reference_name: frm.docname },
		});
		const rows = response.message || [];
		$wrapper.html(media_gallery_html(rows));
		$wrapper.find(".cfg-open-task-media").on("click", async function () {
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
		$wrapper.html(`<div class="alert alert-warning">${__("Private media evidence could not be loaded. Confirm your permission and media configuration.")}</div>`);
	}
}

function media_gallery_html(rows) {
	if (!rows.length) {
		return `<div class="text-muted cfg-task-media-empty">${__("No private media evidence is attached to this task.")}</div>`;
	}
	const escape = frappe.utils.escape_html;
	return `<div class="cfg-task-media-gallery">${rows.map((row) => {
		const image = (row.content_type || "").startsWith("image/") && row.preview_url;
		const preview = image
			? `<img src="${escape(row.preview_url)}" alt="${escape(row.original_filename)}" loading="lazy">`
			: `<div class="cfg-task-media-file-icon">${escape(file_type_label(row.content_type))}</div>`;
		return `<article class="frappe-card cfg-task-media-card">
			<div class="cfg-task-media-preview">${preview}</div>
			<div class="cfg-task-media-details"><strong title="${escape(row.original_filename)}">${escape(row.original_filename)}</strong>
				<small>${escape(row.content_type || "-")} · ${format_media_bytes(row.size_bytes)}</small>
				<small>${__("Captured by")}: ${escape(row.operator_employee || row.created_by || "-")}</small>
				<small>${escape(row.confirmed_at || row.created_at || "-")}</small>
				<small>${__("Media ID")}: ${escape(row.media_id)}</small></div>
			<button type="button" class="btn btn-default cfg-open-task-media" data-media-id="${escape(row.media_id)}">${__("Open Original")}</button>
		</article>`;
	}).join("")}</div>`;
}

function file_type_label(content_type) {
	if (content_type === "application/pdf") return "PDF";
	if ((content_type || "").startsWith("video/")) return __("VIDEO");
	return __("FILE");
}

function format_media_bytes(value) {
	const bytes = Number(value || 0);
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
