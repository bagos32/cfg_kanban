frappe.ui.form.on("CFG Kanban Operator Profile", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Issue New QR Credential"), async () => {
			frappe.confirm(__("This will invalidate the operator's previous QR. Continue?"), async () => {
				const response = await frappe.call({
					method: "cfg_kanban.api.operator.issue_operator_credential",
					args: { profile_name: frm.doc.name }, freeze: true,
				});
				show_credential_card(response.message);
			});
		}, __("Credentials"));
	},
});

function show_credential_card(data) {
	const e = frappe.utils.escape_html;
	const photo = data.employee_image
		? `<img class="operator-photo" src="${e(data.employee_image)}" alt="${e(data.employee_name)}">`
		: `<div class="operator-photo photo-placeholder">${e(initials(data.employee_name))}</div>`;
	const card = `<div class="operator-card">
		<div class="card-band"><span>CFG KANBAN</span><span>OPERATOR</span></div>
		<div class="card-body">
			<div class="identity">${photo}<div class="identity-copy">
				<div class="operator-name">${e(data.employee_name)}</div>
				<div class="employee-id">${e(data.employee)}</div>
				<div class="designation">${e(data.designation || "Operator")}</div>
				<div class="department">${e(data.department || "")}</div>
				<div class="role">${e(data.kanban_role || "")}</div>
			</div></div>
			<div class="qr"><img src="${data.qr_svg}"><small>${__("SCAN TO IDENTIFY")}</small></div>
		</div>
		<div class="card-foot"><span>${__("Personal credential — do not share")}</span><span>${e(data.employee)}</span></div>
	</div>`;
	const vertical_photo = data.employee_image
		? `<img class="operator-photo" src="${e(data.employee_image)}" alt="${e(data.employee_name)}">`
		: `<div class="operator-photo photo-placeholder">${e(initials(data.employee_name))}</div>`;
	const vertical_card = `<div class="operator-card-vertical">
		<div class="vertical-band"><span>CFG KANBAN</span><span>OPERATOR</span></div>
		<div class="vertical-body">
			${vertical_photo}
			<div class="vertical-name">${e(data.employee_name)}</div>
			<div class="vertical-employee">${e(data.employee)}</div>
			<div class="vertical-designation">${e(data.designation || "Operator")}${data.department ? `<br>${e(data.department)}` : ""}</div>
			<div class="vertical-role">${e(data.kanban_role || "")}</div>
			<div class="vertical-qr"><img src="${data.qr_svg}"><small>${__("SCAN TO IDENTIFY")}</small></div>
		</div>
		<div class="vertical-foot">${__("Personal credential — do not share")}</div>
	</div>`;
	const preview = `<style>${card_css("preview")}</style><div class="credential-previews">
		<div><div class="preview-label">${__("CR80 Horizontal")}</div><div class="card-preview horizontal-preview">${card}</div></div>
		<div><div class="preview-label">${__("CR80 Vertical")}</div><div class="card-preview vertical-preview">${vertical_card}</div></div>
	</div>`;
	const dialog = new frappe.ui.Dialog({
		title: __("New Operator QR Card"),
		fields: [{ fieldtype: "HTML", options: `${preview}<p class="text-warning mt-3">${__("Print or download now. The credential is stored only as a hash and cannot be displayed again.")}</p>` }],
		primary_action_label: __("Print CR80 Horizontal Card"),
		primary_action: () => print_operator_card(data, card, "horizontal"),
	});
	dialog.show();
	const $vertical = $(`<button class="btn btn-default btn-sm mr-2">${__("Print CR80 Vertical Card")}</button>`);
	$vertical.on("click", () => print_operator_card(data, vertical_card, "vertical"));
	const $large = $(`<button class="btn btn-default btn-sm mr-2">${__("Print Large QR Sheet")}</button>`);
	$large.on("click", () => print_operator_card(data, card, "large"));
	const $download = $(`<button class="btn btn-default btn-sm mr-2">${__("Download QR")}</button>`);
	$download.on("click", () => {
		const link = document.createElement("a");
		link.href = data.qr_svg;
		link.download = `${data.employee}-kanban-operator.svg`;
		link.click();
	});
	dialog.get_primary_btn().before($vertical).before($large).before($download);
}

function print_operator_card(data, card, format) {
	const e = frappe.utils.escape_html;
	const popup = window.open("", "_blank", format === "horizontal" ? "width=700,height=500" : "width=600,height=850");
	if (!popup) {
		frappe.msgprint(__("Allow pop-ups for this site to print the operator card."));
		return;
	}
	popup.document.write(`<html><head><meta charset="utf-8"><title>${e(data.employee)} - ${__("Operator Card")}</title><style>${card_css(format)}</style></head><body><div class="print-sheet">${card}</div><script>window.onload=()=>window.print();<\/script></body></html>`);
	popup.document.close();
}

function card_css(format) {
	const page = format === "horizontal" ? "@page{size:85.60mm 53.98mm;margin:0}"
		: format === "vertical" ? "@page{size:53.98mm 85.60mm;margin:0}"
		: "@page{size:A4 portrait;margin:15mm}";
	const sheet = format === "horizontal" ? ".print-sheet{width:85.60mm;height:53.98mm}"
		: format === "vertical" ? ".print-sheet{width:53.98mm;height:85.60mm}"
		: ".print-sheet{width:85.60mm;height:53.98mm;margin:20mm auto}";
	return `${page}*{box-sizing:border-box}html,body{margin:0;padding:0;font-family:Arial,sans-serif;color:#101828;-webkit-print-color-adjust:exact;print-color-adjust:exact}${sheet}.credential-previews{display:flex;align-items:flex-start;justify-content:center;gap:18px;flex-wrap:wrap}.preview-label{text-align:center;font-size:12px;font-weight:700;margin-bottom:4px}.card-preview{margin:4px auto;box-shadow:0 1px 8px rgba(0,0,0,.25)}.horizontal-preview{width:85.60mm;height:53.98mm}.vertical-preview{width:53.98mm;height:85.60mm}.operator-card{width:85.60mm;height:53.98mm;border:.45mm solid #101828;background:#fff;overflow:hidden;display:grid;grid-template-rows:9mm 1fr 6mm}.card-band{background:#101828;color:#fff;padding:0 4mm;display:flex;align-items:center;justify-content:space-between;font-size:3.5mm;font-weight:800;letter-spacing:.35mm}.card-band span:last-child{font-size:2.6mm;letter-spacing:.6mm}.card-body{display:grid;grid-template-columns:1fr 27mm;gap:2mm;padding:3mm 3mm 2mm}.identity{display:grid;grid-template-columns:19mm 1fr;gap:2.5mm;min-width:0}.operator-photo{width:19mm;height:24mm;object-fit:cover;border:.35mm solid #344054;border-radius:1.2mm;background:#eef2f6}.photo-placeholder{display:flex;align-items:center;justify-content:center;font-size:7mm;font-weight:800;color:#475467}.identity-copy{min-width:0}.operator-name{font-size:4.2mm;line-height:1.05;font-weight:800;max-height:9mm;overflow:hidden}.employee-id{font-size:2.8mm;font-weight:700;margin-top:1mm}.designation,.department{font-size:2.45mm;line-height:1.25;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.role{display:inline-block;margin-top:1.5mm;background:#e8f3ff;color:#075985;border:.25mm solid #7dd3fc;border-radius:2mm;padding:.6mm 1.8mm;font-size:2.4mm;font-weight:800}.qr{text-align:center;font-size:2mm;font-weight:800}.qr img{display:block;width:23mm;height:23mm;margin:0 auto .5mm}.card-foot{border-top:.25mm solid #98a2b3;padding:0 3mm;display:flex;align-items:center;justify-content:space-between;font-size:2.1mm;font-weight:700}.card-foot span:first-child{color:#b42318}.operator-card-vertical{width:53.98mm;height:85.60mm;border:.45mm solid #101828;background:#fff;overflow:hidden;display:grid;grid-template-rows:9mm 1fr 6mm;text-align:center}.vertical-band{background:#101828;color:#fff;padding:0 3mm;display:flex;align-items:center;justify-content:space-between;font-size:3.1mm;font-weight:800;letter-spacing:.25mm}.vertical-band span:last-child{font-size:2.2mm;letter-spacing:.45mm}.vertical-body{display:flex;flex-direction:column;align-items:center;padding:2.5mm 3mm 1.5mm;min-height:0}.operator-card-vertical .operator-photo{width:17mm;height:21mm;flex:0 0 auto}.operator-card-vertical .photo-placeholder{font-size:6mm}.vertical-name{font-size:3.9mm;line-height:1.05;font-weight:800;margin-top:1.5mm;max-height:8.2mm;overflow:hidden}.vertical-employee{font-size:2.7mm;font-weight:700;margin-top:.7mm}.vertical-designation{font-size:2.25mm;line-height:1.15;color:#475467;min-height:5mm;margin-top:.4mm}.vertical-role{background:#e8f3ff;color:#075985;border:.25mm solid #7dd3fc;border-radius:2mm;padding:.5mm 1.6mm;font-size:2.2mm;font-weight:800;margin-top:.7mm}.vertical-qr{font-size:1.8mm;font-weight:800;margin-top:1mm}.vertical-qr img{display:block;width:20mm;height:20mm;margin:0 auto .4mm}.vertical-foot{border-top:.25mm solid #98a2b3;color:#b42318;display:flex;align-items:center;justify-content:center;font-size:1.9mm;font-weight:700}@media print{.card-preview{box-shadow:none}}`;
}

function initials(name) {
	return String(name || "?").trim().split(/\s+/).slice(0, 2).map((part) => part[0] || "").join("").toUpperCase();
}
