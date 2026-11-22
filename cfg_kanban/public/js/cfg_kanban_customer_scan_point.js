function cfg_customer_delivery_pin_tools(frm) {
 const field=frm.fields_dict.delivery_pin_tools;
 if(!field)return;
 const name=frm.doc.name,doc=frm.doc;
 const ready=window.cfg_delivery_maps?Promise.resolve():frappe.require('/assets/cfg_kanban/js/delivery_maps.js');
 ready.then(()=>{
  if(frm.doc===doc&&frm.doc.name===name)window.cfg_delivery_maps.pinTools(frm,frappe);
 }).catch(()=>{if(frm.doc===doc&&frm.doc.name===name)field.$wrapper.text(__('Delivery Pin tools unavailable. Use the map marker and save the Customer Site.'));});
}

frappe.ui.form.on("CFG Kanban Customer Scan Point", {
	setup(frm) {
		frm.set_query("default_price_list", () => ({ filters: { selling: 1 } }));
	},
	refresh(frm) {
		cfg_customer_delivery_pin_tools(frm);
		if (frm.is_new()) return;
		frm.add_custom_button(__("Print Customer Site QR"), () => {
			const format = "CFG Customer Site Card";
			const url = `/printview?doctype=${encodeURIComponent(frm.doctype)}` +
				`&name=${encodeURIComponent(frm.doc.name)}` +
				`&format=${encodeURIComponent(format)}&no_letterhead=1`;
			window.open(url, "_blank");
		});
		frm.add_custom_button(__("Open Logistics Panel"), () => {
			frappe.set_route("kanban-logistics");
		});
	},
	delivery_location(frm) { cfg_customer_delivery_pin_tools(frm); },
	proof_policy(frm) {
		frm.set_value(
			"unattended_reason_required",
			frm.doc.proof_policy === "Unattended Delivery Allowed" ? 1 : 0,
		);
	},
});
