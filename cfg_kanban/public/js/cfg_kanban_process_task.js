frappe.ui.form.on("CFG Kanban Process Task", {
	refresh(frm) {
		render_private_media(frm);
		if (!frm.is_new()) {
			frm.add_custom_button(__("Print Process Task QR"), () => print_task_label(frm, "Process Task"));
		}
		if (!frm.is_new() && frm.doc.sample_qr_payload) {
			frm.add_custom_button(__("Print Sample Traveller"), () => print_task_label(frm, "Sample Traveller"));
		}
	},
});

async function print_task_label(frm, label_type) {
				const response = await frappe.call({ method: "cfg_kanban.api.process_task.get_sample_label",
					args: { task_name: frm.doc.name, label_type } });
				const data = response.message;
				const win = window.open("", "_blank");
				win.document.write(`<html><head><title>${frappe.utils.escape_html(data.task.sample_id || data.task.name)}</title>
					<style>@page{size:100mm 70mm;margin:4mm}body{font-family:Arial}.label{border:2px solid;padding:4mm;display:grid;grid-template-columns:1fr 36mm;gap:4mm}img{width:34mm;height:34mm}h1{font-size:16pt;margin:0}.meta{font-size:10pt;line-height:1.5}</style></head><body>
					<div class="label"><div><h1>${frappe.utils.escape_html(data.label_type.toUpperCase())}</h1><div class="meta"><b>${frappe.utils.escape_html(data.task.sample_id || data.task.name)}</b><br>${frappe.utils.escape_html(data.task.task_name || "")}<br>${frappe.utils.escape_html(data.task.item_code || "")}<br>${frappe.utils.escape_html(data.task.batch_no || "No batch")}<br>${frappe.utils.escape_html(data.task.test_method || "")}</div></div><img src="${data.qr_svg}"></div>
					<script>window.onload=()=>window.print();<\/script></body></html>`);
				win.document.close();
}

async function render_private_media(frm) {
	const field = frm.get_field("media_evidence_html");
	if (!field || frm.is_new()) return;
	const $wrapper = field.$wrapper.html(`<div class="text-muted">${__("Loading private media evidence...")}</div>`);
	try {
		const response = await frappe.call({ method: "cfg_kanban.api.media.get_reference_gallery",
			args: { reference_doctype: frm.doctype, reference_name: frm.docname } });
		const rows = response.message || [];
		if (!rows.length) return $wrapper.html(`<div class="text-muted">${__("No private QC evidence is attached.")}</div>`);
		const e = frappe.utils.escape_html;
		$wrapper.html(`<div class="cfg-task-media-gallery">${rows.map((row) => `<article class="frappe-card cfg-task-media-card">
			<div class="cfg-task-media-preview">${row.preview_url ? `<img src="${e(row.preview_url)}" loading="lazy">` : `<div class="cfg-task-media-file-icon">FILE</div>`}</div>
			<div class="cfg-task-media-details"><strong>${e(row.original_filename)}</strong><small>${e(row.content_type || "-")}</small><small>${e(row.confirmed_at || row.created_at || "-")}</small></div>
			<button class="btn btn-default open-qc-media" data-id="${e(row.media_id)}">${__("Open Original")}</button></article>`).join("")}</div>`);
		$wrapper.find(".open-qc-media").on("click", async function () {
			const view = await frappe.call({ method: "cfg_kanban.api.media.create_view_url",
				args: { media_id: $(this).data("id") } });
			window.open(view.message.url, "_blank", "noopener");
		});
	} catch (error) {
		$wrapper.html(`<div class="alert alert-warning">${__("Private QC evidence could not be loaded.")}</div>`);
	}
}
