frappe.pages["material-genealogy"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Material Genealogy Explorer"),
		single_column: true,
	});
	const state = { result: null };
	const $scanner = $(`<div class="frappe-card cfg-genealogy-scanner">
		<div><h3>${__("Scan Any Physical Stock Tag")}</h3>
		<p class="text-muted">${__("Read-only trace from ERP receipt through production, Warehouse movements, intercompany handover, and delivery.")}</p></div>
		<div class="cfg-genealogy-scan-row">
			<input class="form-control genealogy-scan-input" autocomplete="off" spellcheck="false"
				placeholder="${__("Scan or enter preprinted tag, for example STK1000")}">
			<button class="btn btn-primary find-genealogy">${__("Find Trace")}</button>
			<button class="btn btn-default camera-genealogy">${__("Scan with Camera")}</button>
		</div>
		<div class="genealogy-message text-muted"><small>${__("Scanner ready")}</small></div>
	</div>`).appendTo(page.main);
	const $result = $('<div class="cfg-genealogy-result mt-3"></div>').appendTo(page.main);

	$scanner.find(".genealogy-scan-input").on("keydown", (event) => {
		if (event.key === "Enter") { event.preventDefault(); load_scan(); }
	});
	$scanner.find(".find-genealogy").on("click", () => load_scan());
	$scanner.find(".camera-genealogy").on("click", camera_scan);
	page.set_primary_action(__("Scan with Camera"), camera_scan, "scan");
	page.add_inner_button(__("Clear"), clear_result);

	function route_scan_value() {
		const route = frappe.get_route();
		if (route && route[0] === "material-genealogy" && route[1]) return decodeURIComponent(route[1]);
		return null;
	}

	async function load_scan(value) {
		const $input = $scanner.find(".genealogy-scan-input");
		const raw = String(value || $input.val() || "").trim();
		if (!raw) return focus_scanner();
		$input.val(raw);
		try {
			const response = await frappe.call({
				method: "cfg_kanban.services.genealogy.get_handling_unit_genealogy",
				args: { scan_value: raw }, freeze: true,
				freeze_message: __("Building upstream and downstream trace..."),
			});
			state.result = response.message;
			render();
			$scanner.find(".genealogy-message").html(
				`<small class="text-success">${__("Trace loaded: {0}", [escape(raw)])}</small>`);
		} catch (error) {
			state.result = null;
			$result.empty();
			$scanner.find(".genealogy-message").html(
				`<small class="text-danger">${__("Trace could not be loaded. Review the validation message.")}</small>`);
		}
		focus_scanner(false);
	}

	function render() {
		if (!state.result) return $result.empty();
		if (!state.result.activated) return render_unused_identity();
		const data = state.result;
		$result.html(`${data.truncated ? `<div class="alert alert-warning">${__("The lineage exceeded the safe display limit. Narrow the investigation from a related tag or use ERP references for the remaining chain.")}</div>` : ""}
			${focus_card(data.focus, data.evidence_level)}
			<div class="cfg-genealogy-columns">
				${generation_column(__("Upstream Materials"), data.upstream, "upstream")}
				${generation_column(__("Downstream Products"), data.downstream, "downstream")}
			</div>
			${relationship_table(data.relationships)}
			${manifest_table(data.manifests)}
			${timeline_table(data.timeline)}
		`);
		$result.find(".open-unit").on("click", function () { load_scan($(this).data("code")); });
		$result.find(".open-reference").on("click", function () {
			frappe.set_route("Form", $(this).data("doctype"), $(this).data("name"));
		});
		$result.find(".print-genealogy").on("click", print_report);
	}

	function render_unused_identity() {
		const identity = state.result.identity || {};
		$result.html(`<div class="frappe-card cfg-genealogy-unused">
			<h3>${escape(identity.visible_code || identity.name || "-")}</h3>
			<p><strong>${escape(identity.identity_type || __("Registered identity"))}</strong></p>
			<div class="alert alert-warning mb-0">${__("This preprinted identity has not been activated as a Handling Unit. It has no material genealogy yet.")}</div>
		</div>`);
	}

	function focus_card(unit, evidence) {
		return `<div class="frappe-card cfg-genealogy-focus">
			<div class="cfg-genealogy-focus-head"><div><small>${__("FOCUS PHYSICAL TAG")}</small>
				<h2>${escape(unit.visible_code)}</h2><strong>${escape(unit.item_code || __("No item"))}</strong>
				<span>${escape(unit.short_description || "")}</span></div>
				<div><span class="indicator-pill blue">${escape(evidence)}</span>
				<button class="btn btn-primary print-genealogy">${__("Print Trace Report")}</button></div></div>
			<div class="cfg-genealogy-facts">
				${fact(__("Batch"), unit.batch_no || __("No Batch"))}
				${fact(__("Company"), unit.inventory_company || "-")}
				${fact(__("Current Location"), unit.current_warehouse || unit.physical_custodian || __("In Transit / Unassigned"))}
				${fact(__("Current / Available"), `${number(unit.current_qty)} / ${number(unit.available_qty)} ${escape(unit.stock_uom || "")}`)}
				${fact(__("Lifecycle"), `${unit.identity_state} · ${unit.movement_state} · ${unit.quality_state}`)}
				${fact(__("ERP Origin"), unit.origin_reference_name || __("No ERP origin recorded"))}
			</div>
		</div>`;
	}

	function generation_column(title, rows, direction) {
		const cards = (rows || []).map((row) => `<button class="frappe-card cfg-genealogy-unit open-unit ${direction}" data-code="${attr(row.visible_code)}">
			<div><small>${__("Generation {0}", [Math.abs(row.level)])}</small><strong>${escape(row.visible_code)}</strong>
			<span>${escape(row.item_code || __("No item"))}</span></div>
			<div><small>${escape(row.batch_no || __("No Batch"))}</small><strong>${number(row.current_qty)} ${escape(row.stock_uom || "")}</strong>
			<span>${escape(row.inventory_company || "-")} · ${escape(row.current_warehouse || row.movement_state || "-")}</span></div>
		</button>`).join("");
		return `<section class="cfg-genealogy-generation ${direction}"><h3>${title}</h3>
			${cards || `<div class="text-muted cfg-genealogy-empty">${direction === "upstream" ? __("No tagged upstream material recorded") : __("No tagged downstream product recorded")}</div>`}
		</section>`;
	}

	function relationship_table(rows) {
		const body = (rows || []).map((row) => `<tr>
			<td><button class="btn btn-link open-unit" data-code="${attr(row.source_code)}">${escape(row.source_code)}</button></td>
			<td><strong>${escape(row.relation_type)}</strong><small>${escape(row.status || "")}</small></td>
			<td><button class="btn btn-link open-unit" data-code="${attr(row.target_code)}">${escape(row.target_code)}</button></td>
			<td>${row.qty ? `${number(row.qty)} ${escape(row.stock_uom || "")}` : "-"}</td>
			<td>${reference_button(row.reference_doctype, row.reference_name)}</td>
		</tr>`).join("");
		return table_section(__("Confirmed Lineage Relationships"),
			`<th>${__("From")}</th><th>${__("Relationship")}</th><th>${__("To")}</th><th>${__("Quantity")}</th><th>${__("ERP Reference")}</th>`,
			body, __("No transformation or split relationship recorded"));
	}

	function manifest_table(rows) {
		const body = (rows || []).map((row) => `<tr><td>${reference_button("CFG Kanban Movement Manifest", row.name)}</td>
			<td>${escape(row.state)}</td><td>${escape(row.source_company || "-")}<br><small>${escape(row.source_warehouse || "-")}</small></td>
			<td>${escape(row.destination_company || "-")}<br><small>${escape(row.destination_warehouse || "-")}</small></td>
			<td>${reference_button("Delivery Note", row.dispatch_delivery_note)}<br>${reference_button("Purchase Receipt", row.receipt_purchase_receipt)}</td></tr>`).join("");
		return table_section(__("Movement Manifest History"),
			`<th>${__("Manifest")}</th><th>${__("State")}</th><th>${__("From")}</th><th>${__("To")}</th><th>${__("ERP Documents")}</th>`,
			body, __("No Movement Manifest is linked to this lineage"));
	}

	function timeline_table(rows) {
		const body = (rows || []).map((row) => `<tr><td>${escape(date_time(row.posting_datetime))}</td>
			<td><strong>${escape(row.event_type)}</strong><small>${escape(row.reason || "")}</small></td>
			<td>${escape(row.source_code || row.destination_code || "-")}</td>
			<td>${number(row.stock_qty)} ${escape(row.stock_uom || "")}</td>
			<td>${escape(row.source_warehouse || "-")} → ${escape(row.destination_warehouse || "-")}</td>
			<td>${reference_button(row.reference_doctype, row.reference_name)}</td></tr>`).join("");
		return table_section(__("Chronological Quantity and Movement Evidence"),
			`<th>${__("When")}</th><th>${__("Event")}</th><th>${__("Tag")}</th><th>${__("Quantity")}</th><th>${__("Location")}</th><th>${__("Reference")}</th>`,
			body, __("No quantity-ledger event recorded"));
	}

	function table_section(title, headings, body, empty) {
		return `<section class="frappe-card cfg-genealogy-table"><h3>${title}</h3>
			<div class="table-responsive"><table class="table table-bordered table-sm"><thead><tr>${headings}</tr></thead>
			<tbody>${body || `<tr><td colspan="8" class="text-muted">${empty}</td></tr>`}</tbody></table></div></section>`;
	}

	function fact(label, value) { return `<div><small>${label}</small><strong>${escape(value)}</strong></div>`; }
	function reference_button(doctype, name) {
		if (!doctype || !name) return '<span class="text-muted">-</span>';
		return `<button class="btn btn-link open-reference" data-doctype="${attr(doctype)}" data-name="${attr(name)}">${escape(name)}</button>`;
	}
	function print_report() {
		const unit = state.result && state.result.focus;
		if (!unit) return;
		const url = `/printview?doctype=${encodeURIComponent("CFG Kanban Handling Unit")}` +
			`&name=${encodeURIComponent(unit.name)}&format=${encodeURIComponent("CFG Kanban Genealogy Report")}&no_letterhead=1`;
		window.open(url, "_blank");
	}
	function camera_scan() {
		if (!(frappe.ui && frappe.ui.Scanner)) return frappe.msgprint(__("Camera scanning is unavailable. Use the scanner field."));
		new frappe.ui.Scanner({ dialog: true, multiple: false, on_scan(data) {
			load_scan(String(data.decodedText || "").trim());
		} });
	}
	function clear_result() {
		state.result = null; $result.empty();
		$scanner.find(".genealogy-scan-input").val("");
		$scanner.find(".genealogy-message").html(`<small>${__("Scanner ready")}</small>`);
		focus_scanner();
	}
	function focus_scanner(select = true) {
		if (!window.matchMedia("(min-width: 768px) and (hover: hover)").matches) return;
		setTimeout(() => {
			const $input = $scanner.find(".genealogy-scan-input").trigger("focus");
			if (select) $input.select();
		}, 50);
	}
	function date_time(value) {
		if (!value) return "-";
		try { return frappe.datetime.str_to_user(value); } catch (error) { return String(value); }
	}
	function number(value) { return format_number(value || 0); }
	function escape(value) { return frappe.utils.escape_html(String(value == null ? "" : value)); }
	function attr(value) { return escape(value).replace(/`/g, "&#96;"); }

	const initial = route_scan_value();
	if (initial) { $scanner.find(".genealogy-scan-input").val(initial); load_scan(initial); }
	else focus_scanner();
};
