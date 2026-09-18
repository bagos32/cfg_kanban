frappe.ui.form.on("CFG Kanban Task Schedule", {
	refresh(frm) {
		(frm.doc.task_field_definitions || []).forEach((row) => {
			if (row.definition_scope !== "Standalone Task") {
				frappe.model.set_value(row.doctype, row.name, "definition_scope", "Standalone Task");
			}
		});
		if (!frm.is_new() && frm.doc.service_point_enabled) {
			frm.add_custom_button(__("Print Service Point QR"), async () => {
				const response = await frappe.call({ method: "cfg_kanban.api.task.get_service_point_label",
					args: { schedule_name: frm.doc.name } });
				const data = response.message;
				const win = window.open("", "_blank");
				win.document.write(`<html><head><title>${frappe.utils.escape_html(data.schedule.schedule_name)}</title>
					<style>@page{size:100mm 100mm;margin:5mm}body{font-family:Arial;text-align:center}.label{border:3px solid #111;padding:6mm}svg{width:52mm;height:52mm}h1{font-size:20pt;margin:0 0 3mm}.where{font-size:14pt;font-weight:700}.code{font-size:9pt;word-break:break-all}</style></head><body>
					<div class="label"><h1>${__("SERVICE POINT")}</h1><div class="where">${frappe.utils.escape_html(data.schedule.location || data.schedule.task_name)}</div>
					<img src="${data.qr_svg}"><h2>${frappe.utils.escape_html(data.schedule.task_name)}</h2><div class="code">${frappe.utils.escape_html(data.payload)}</div></div>
					<script>window.onload=()=>window.print();<\/script></body></html>`);
				win.document.close();
			});
		}
	},
});

frappe.ui.form.on("CFG Kanban Field Definition", {
	task_field_definitions_add(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "definition_scope", "Standalone Task");
	},
});
