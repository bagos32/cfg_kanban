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
	const operations = (data.allowed_operations || []).map(e).join(", ") || __("All permitted operations");
	const workstations = (data.allowed_workstations || []).map(e).join(", ") || __("All permitted workstations");
	const card = `<div class="cfg-operator-card" style="max-width:420px;margin:auto;border:2px solid #222;padding:20px;text-align:center">
		<h3>${e(data.employee_name)}</h3><div><b>${e(data.employee)}</b></div>
		<div>${e(data.designation || "")} ${data.department ? "· " + e(data.department) : ""}</div>
		<img src="${data.qr_svg}" style="width:220px;height:220px;margin:16px auto;display:block">
		<div><b>${e(data.kanban_role || "")}</b></div>
		<hr><small><b>${__("Operations")}:</b> ${operations}<br><b>${__("Workstations")}:</b> ${workstations}</small>
	</div>`;
	const dialog = new frappe.ui.Dialog({
		title: __("New Operator QR Card"),
		fields: [{ fieldtype: "HTML", options: `${card}<p class="text-warning mt-3">${__("Print or download now. The credential is stored only as a hash and cannot be displayed again.")}</p>` }],
		primary_action_label: __("Print Card"),
		primary_action: () => {
			const popup = window.open("", "_blank", "width=600,height=760");
			popup.document.write(`<html><head><title>${e(data.employee)} - ${__("Operator Card")}</title></head><body>${card}<script>window.onload=()=>window.print();<\/script></body></html>`);
			popup.document.close();
		},
	});
	dialog.show();
	const $download = $(`<button class="btn btn-default btn-sm mr-2">${__("Download QR")}</button>`);
	$download.on("click", () => {
		const link = document.createElement("a");
		link.href = data.qr_svg;
		link.download = `${data.employee}-kanban-operator.svg`;
		link.click();
	});
	dialog.get_primary_btn().before($download);
}
