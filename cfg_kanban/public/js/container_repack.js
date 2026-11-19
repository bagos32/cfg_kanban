/* Received-stock repacking. The controller is shared by scanner and touch. */
(function (root) {
	"use strict";
	const pendingKey = "cfg_kanban_container_repack_pending_v1";
	const lockKey = "cfg_kanban_container_repack_submit_v1";
	function createController(env) {
		const method = env.release ? "release_container_stock" : "move_container_stock";
		const s = { release: !!env.release, source: null, sourceScan: "", destination: null, destinationScan: "", target: null,
			qty: 0, newTag: "", reason: "", choices: [], page: 0, choosing: "", arm: "", pending: null, busy: false, completed: false, closed: false, message: "" };
		function changed() { env.render(s); }
		function fail(message) { throw new Error(message); }
		function readPending() {
			const text = env.storage.getItem(pendingKey);
			if (!text) return null;
			let row;
			try { row = JSON.parse(text); } catch (_) { fail("Pending repack data is unreadable. Reconcile this terminal before another move."); }
			if (!row?.args?.event_token || !row.owner) fail("Pending repack data is incomplete. Reconcile this terminal before another move.");
			const pendingMethod = row.method || "move_container_stock";
			if (!["move_container_stock", "release_container_stock"].includes(pendingMethod)) fail("Pending stock action is unreadable; reconcile this terminal.");
			if (pendingMethod !== method) fail(pendingMethod === "release_container_stock" ? "Open Release Stock Tag to reconcile the original pending release." : "Open Move / Repack to reconcile the original pending move.");
			return row;
		}
		function editable() { if (s.completed || s.closed) fail("This move dialog is closed. Open a new move."); if (s.pending || s.busy) fail("Retry the original move to reconcile its outcome before changing the data."); }
		function setChoices(kind, rows) {
			s.choosing = kind; s.choices = rows; s.page = 0;
			if (rows.length === 1) choose(1);
		}
		function choose(number) {
			editable();
			const row = s.choices[s.page * 10 + number - 1];
			if (!row || number < 1 || number > 10) fail("Choose a displayed option from 1 to 10.");
			if (s.choosing === "source") { s.source = row; s.destination = null; s.target = null; s.destinationScan = ""; s.newTag = ""; }
			else if (s.choosing === "destination") s.target = row;
			else fail("There is no numbered choice open.");
			s.choosing = ""; s.choices = []; s.page = 0; changed();
		}
		async function source(value) {
			editable();
			const data = await env.rpc(s.release ? "release_source_context" : "repack_source_context", { source_scan: value });
			s.sourceScan = value; s.source = null; s.destination = null; s.target = null; s.newTag = ""; s.destinationScan = "";
			setChoices("source", data.options); changed();
		}
		async function destination(value) {
			editable(); if (s.release) fail("Release Stock Tag does not need another destination container."); if (!s.source) fail("Scan and select the source stock first.");
			const data = await env.rpc("repack_destination_context", { source_stock: s.source.name, destination_scan: value });
			s.destination = data; s.destinationScan = value; s.target = null; s.newTag = "";
			if (data.options.length) setChoices("destination", data.options);
			else { s.choosing = ""; s.choices = []; }
			changed();
		}
		function quantity(value, additive = false) {
			editable(); const qty = Number(value);
			if (!Number.isFinite(qty) || qty <= 0) fail("Use a finite positive quantity.");
			s.qty = additive ? s.qty + qty : qty; changed();
		}
		async function tag(value) {
			editable(); if (s.release && !s.source) fail("Select the source stock first."); if (!s.release && (!s.destination || !s.destination.new_tag_allowed)) fail("A new tag is only for an empty destination. Use its existing tag when loaded.");
			if (value) await env.rpc("repack_new_tag_context", { new_tag: value });
			s.newTag = value; changed();
		}
		function reason(value) { editable(); s.reason = String(value || "").trim(); changed(); }
		function request() {
			if (!s.source || (!s.release && !s.destination) || s.choosing) fail(s.release ? "Scan and select the source stock to release." : "Scan and select the source and destination stock.");
			if (!Number.isFinite(s.qty) || s.qty <= 0 || s.qty > Number(s.source.available_qty) + 0.000001) fail("Quantity must be positive and within available source stock.");
			if (!s.release && s.destination.options.length && !s.target) fail("Select the existing destination tag.");
			if (!s.reason) fail("Enter or scan a reason.");
			if (s.release) {
				if (!s.source.container) fail("Select stock currently inside a reusable container.");
				if (!s.newTag && (s.source.requires_new_tag || Math.abs(s.qty - Number(s.source.qty)) > 0.000001)) fail("An internal fill or partial release requires an unused preprinted Main Stock Tag.");
				return {source_scan:s.sourceScan,source_stock:s.source.name,qty:s.qty,new_tag:s.newTag || null,reason:s.reason,event_token:env.nonce()};
			}
			return { source_scan: s.sourceScan, source_stock: s.source.name, destination_scan: s.destinationScan,
				destination_stock: s.target?.name || null, qty: s.qty, new_tag: s.newTag || null, reason: s.reason, event_token: env.nonce() };
		}
		async function confirm() {
			if (s.busy || s.completed || s.closed) return;
			if (!env.locks?.request) fail("This action requires HTTPS and a browser supporting Web Locks.");
			s.busy = true; changed();
			try {
				return await env.locks.request(lockKey, async () => {
					if (s.closed || s.completed) return;
					const stored = readPending();
					if (stored && (!s.pending || stored.args.event_token !== s.pending.args.event_token)) {
						s.pending = stored; changed(); fail("Another move is awaiting reconciliation. Reopen Move / Repack to retry that original move.");
					}
					if (stored && stored.owner !== env.owner()) fail("The original operator must reconcile the pending move on this terminal.");
					if (!stored && s.pending) fail("This pending move was reconciled in another tab. Close and reopen before a new move.");
					const row = stored || { owner: env.owner(), method, args: request() };
					if (!row.owner) fail("Identify the operator before moving stock.");
					env.storage.setItem(pendingKey, JSON.stringify(row)); s.pending = row; changed();
					let result;
					try { result = await env.rpc(row.method || "move_container_stock", row.args); }
					catch (error) {
						// A structured Frappe exception confirms request rollback; transport loss does not.
						if (error?.exc_type || error?.responseJSON?.exc_type) {
							env.storage.removeItem(pendingKey); s.pending = null;
						}
						throw error;
					}
					env.storage.removeItem(pendingKey); s.pending = null;
					s.completed = true; s.message = s.release ? "Stock Tag released outside its container. Use a Dispatch Manifest for warehouse movement." : "Move recorded. Scan the destination again for its current balance."; changed();
					await env.success(result); return result;
				});
			} finally { s.busy = false; changed(); }
		}
		async function scan(raw) {
			const value = String(raw || "").trim(); if (!value) return;
			const upper = value.toUpperCase();
			if (upper === "CFG:CMD:CANCEL") { if (!s.busy) { s.closed = true; env.close(); } return; }
			if (upper === "CFG:CMD:CONFIRM") return confirm();
			if (upper === "CFG:CMD:REPACK_CAMERA" && env.camera) return env.camera();
			editable();
			const arms = { "CFG:CMD:REPACK_SOURCE": "source", "CFG:CMD:REPACK_DESTINATION": "destination",
				"CFG:CMD:REPACK_NEW_TAG": "tag", "CFG:CMD:REPACK_REASON": "reason" };
			if (arms[upper]) { s.arm = arms[upper]; changed(); return; }
			if (upper === "CFG:CMD:NEXT_MATERIALS" || upper === "CFG:CMD:PREVIOUS_MATERIALS") {
				const delta = upper === "CFG:CMD:NEXT_MATERIALS" ? 1 : -1;
				s.page = Math.max(0, Math.min(Math.ceil(s.choices.length / 10) - 1, s.page + delta)); changed(); return;
			}
			const selected = /^CFG:SELECT:(10|[1-9])$/.exec(upper); if (selected) return choose(Number(selected[1]));
			const qty = /^CFG:QTY:MATERIAL:(\+?)(\d+(?:\.\d+)?)$/.exec(upper); if (qty) return quantity(qty[2], !!qty[1]);
			if (upper.startsWith("CFG:")) fail("Use a Move / Repack command or a physical Stock Tag/container label.");
			const needsTag = s.release && !s.newTag && (s.source?.requires_new_tag || (s.qty > 0 && Math.abs(s.qty - Number(s.source?.qty)) > 0.000001));
			const mode = s.arm || (!s.source ? "source" : s.release ? (needsTag ? "tag" : "reason") : !s.destination ? "destination" : "reason");
			if (s.choosing && !s.arm) fail("Select the numbered stock option before the next scan.");
			s.arm = "";
			if (mode === "source") return source(value);
			if (mode === "destination") return destination(value);
			if (mode === "tag") return tag(value);
			return reason(value);
		}
		function restore() { s.pending = readPending(); changed(); return s.pending; }
		return { state: s, source, destination, quantity, tag, reason, choose, confirm, scan, restore };
	}

	async function open(options) {
		const f = options.frappe, e = f.utils.escape_html;
		let controller, dialog, cameraSession = null, queue = Promise.resolve();
		const enqueue = (action) => {
			queue = queue.then(action).catch((error) => {
				// Show the server error inline so a message modal cannot steal the scanner.
				const messageDialog = f.msg_dialog;
				if (messageDialog && messageDialog !== dialog && messageDialog.$wrapper?.is(":visible")) {
					messageDialog.$wrapper.one("hidden.bs.modal.cfg_repack_focus", focus);
					messageDialog.hide();
				}
				controller.state.message = options.errorMessage(error, error.message || "Move was not acknowledged. Retry the original move.");
				render(controller.state);
			}).finally(focus);
			return queue;
		};
		function focus() {
			if (cameraSession?.scanner?.dialog?.$wrapper.is(":visible")) return;
			if (dialog?.$wrapper.is(":visible")) dialog.fields_dict.scan.$input.trigger("focus");
		}
		function open_camera(method = "scan") {
			if (!dialog.$wrapper.is(":visible") || controller.state.closed) return;
			if (cameraSession) return cameraSession.scanner;
			if (!f.ui.Scanner) throw new Error("Camera scanning is unavailable. Use the Scanner field or Read buttons.");
			const session = { scanner: null, used: false };
			cameraSession = session;
			try {
				session.scanner = new f.ui.Scanner({ dialog: true, multiple: false, on_scan(data) {
					if (session.used || cameraSession !== session || controller.state.closed || !dialog.$wrapper.is(":visible")) return;
					const value = String(data?.decodedText || "").trim();
					if (!value) return;
					session.used = true;
					return enqueue(() => {
						const field = {source:"source_scan",destination:"destination_scan",tag:"new_tag"}[method];
						return Promise.resolve(controller[method](value)).then(() => {
							if (field && !controller.state.closed) dialog.set_value(field, value);
						});
					});
				} });
				session.scanner.dialog.$wrapper.one("hidden.bs.modal.cfg_repack_camera", () => {
					session.used = true;
					if (cameraSession === session) cameraSession = null;
					focus();
				});
				return session.scanner;
			} catch (error) {
				session.used = true;cameraSession = null;
				throw error;
			}
		}
		function render(s) {
			if (!dialog) return;
			const desc = (row) => `${e(row.visible_code)} · ${e(row.item_code)} · ${e(row.batch_no || "No Batch")} · ${e(row.qty)} ${e(row.stock_uom)} · Expiry ${e(row.expiry_date || "-")}${row.source_code ? ` · Source ${e(row.source_code)}` : ""}`;
			const pending = s.pending ? `<div class="alert alert-warning">Unacknowledged ${s.release ? "release" : "move"}: ${e(s.pending.args.source_scan)} → ${e((s.pending.method === "release_container_stock" ? (s.pending.args.new_tag || "existing physical tag") : s.pending.args.destination_scan))} · ${e(s.pending.args.qty)}. Retry Confirm with the original operator. Cancel keeps this request for reconciliation.</div>` : "";
			const choices = s.choices.slice(s.page * 10, s.page * 10 + 10).map((row, i) => `<button type="button" class="btn btn-default repack-choice" data-number="${i + 1}">${i + 1}. ${desc(row)}</button>`).join("<br>");
			const target = s.release ? `${s.newTag ? e(s.newTag) : s.source?.requires_new_tag || (s.qty > 0 && Math.abs(s.qty-Number(s.source?.qty)) > 0.000001) ? "Scan an unused Main Stock Tag" : "Keep the existing physical Stock Tag for a full release"}<br><strong>Standalone stock in the same Warehouse; no destination bin required.</strong>` : s.target ? `${desc(s.target)}<br><strong>Combined total: ${e(Number(s.target.qty) + Number(s.qty))} ${e(s.target.stock_uom)}</strong>` : s.destination ? `${e(s.destination.visible_code)} · Empty · ${s.newTag ? e(s.newTag) : "Keep whole physical source tag, or use permanent container QR for a new internal fill"}` : "Scan destination container";
			dialog.fields_dict.summary.$wrapper.html(`${pending}<p><strong>Source:</strong> ${s.source ? desc(s.source) : "Scan source Stock Tag or container"}</p><p><strong>Move:</strong> ${e(s.qty)} ${e(s.source?.stock_uom || "")}</p><p><strong>${s.release ? "Release to" : "Destination"}:</strong> ${target}</p>${choices}<p>Reason: ${e(s.reason || "Required")}${s.arm ? ` · Next scan: ${e(s.arm)}` : ""}</p><p class="text-danger">${e(s.message)}</p>`);
			dialog.fields_dict.summary.$wrapper.find(".repack-choice").on("click", function () { enqueue(() => controller.choose(Number(this.dataset.number))); });
			for (const name of ["source_scan", "destination_scan", "qty", "new_tag", "reason", "read_source", "read_destination", "set_quantity", "read_tag", "set_reason", "camera_source", "camera_destination", "camera_tag"]) dialog.set_df_property(name, "read_only", !!(s.pending || s.busy));
			dialog.set_df_property("new_tag", "hidden", !s.release && !s.destination?.new_tag_allowed);
			dialog.set_df_property("read_tag", "hidden", !s.release && !s.destination?.new_tag_allowed);
			dialog.set_df_property("camera_tag", "hidden", !s.release && !s.destination?.new_tag_allowed);
			for (const name of ["destination_scan", "read_destination", "camera_destination"]) dialog.set_df_property(name,"hidden",s.release);
			dialog.get_primary_btn().prop("disabled", s.busy);
		}
		dialog = new f.ui.Dialog({ title: options.release ? "Release Stock Tag from Container" : "Move / Repack received stock", size: "large", fields: [
			{ fieldname: "summary", fieldtype: "HTML" },
			{ fieldname: "scan", label: "Scanner", fieldtype: "Data", description: options.release ? "Source container/tag → Material Qty → unused Main tag if required → Reason → Confirm. No destination bin. Tab, Enter and camera scans work; REPACK_NEW_TAG arms an optional replacement tag." : "Keep scanning in Scanner; Tab or Enter ends each code. Source → Material Qty → Destination → Reason → Confirm. Numbered choices 1–10; Next/Previous Material Choices pages. Repack New Tag arms an optional preprinted tag for an empty destination." },
			{ fieldname: "camera_scan", label: "Scan with Camera", fieldtype: "Button" },
			{ fieldname: "source_scan", label: "Source Stock Tag / Container", fieldtype: "Data" },
			{ fieldname: "read_source", label: "Read Source", fieldtype: "Button" },
			{ fieldname: "camera_source", label: "Scan Source with Camera", fieldtype: "Button" },
			{ fieldname: "qty", label: options.release ? "Quantity to Release" : "Quantity to Move", fieldtype: "Float" },
			{ fieldname: "set_quantity", label: "Set Quantity", fieldtype: "Button" },
			{ fieldname: "destination_scan", label: "Destination Reusable Container", fieldtype: "Data", description: "Scan the existing permanent bin/container identity. An unused Stock Tag goes in Optional New Preprinted Main Tag after selecting an empty bin." },
			{ fieldname: "read_destination", label: "Read Destination", fieldtype: "Button" },
			{ fieldname: "camera_destination", label: "Scan Destination with Camera", fieldtype: "Button" },
			{ fieldname: "new_tag", label: options.release ? "New Main Stock Tag (if needed)" : "Optional New Preprinted Main Tag", fieldtype: "Data", hidden: 1 },
			{ fieldname: "read_tag", label: "Use New Tag / Clear if Blank", fieldtype: "Button", hidden: 1 },
			{ fieldname: "camera_tag", label: "Scan New Tag with Camera", fieldtype: "Button", hidden: 1 },
			{ fieldname: "reason", label: "Reason", fieldtype: "Small Text" },
			{ fieldname: "set_reason", label: "Set Reason", fieldtype: "Button" },
			{ fieldname: "help", fieldtype: "HTML", options: options.release ? "<small>Release ERP-posted stock into a standalone physical Stock Tag. Full physical tags can keep their label; internal fills and part quantities require an unused Main tag. No destination container or ERP warehouse movement. Review quantity/reason and Confirm. Intermediate Hopper WIP uses Recover Hopper. Camera, Tab/Enter and CFG:CMD:CANCEL are supported.</small>" : "<small>Same Company and Warehouse only. Item, Batch, UOM, certificate evidence and expiry must match before combining. Existing destination tag is reused. Tag Range registration alone does not assign stock or activate a reusable bin. Camera buttons read directly into the named source, destination or new-tag role; Scan with Camera follows the scanner sequence. Intermediate Hopper WIP uses Recover Hopper. Cancel is also available through CFG:CMD:CANCEL.</small>" }
		], primary_action_label: options.release ? "Release / Retry Original Release" : "Confirm / Retry Original Move", primary_action: () => enqueue(() => controller.confirm()),
		secondary_action_label: "Cancel", secondary_action: () => enqueue(() => controller.scan("CFG:CMD:CANCEL")) });
		controller = createController({ storage: localStorage, locks: navigator.locks, owner: options.owner,
			nonce: options.nonce, release:!!options.release, render, camera: () => open_camera(), rpc: (method, args) => f.call({ method: `cfg_kanban.services.container_repacking.${method}`, args: { ...args, operator_session_token: options.token() }, freeze: true, error: () => {} }).then((response) => response.message),
			close: () => dialog.hide(), success: async (result) => { dialog.hide(); await options.success(result); } });
		for (const [button, method, field] of [["read_source", "source", "source_scan"], ["read_destination", "destination", "destination_scan"], ["set_quantity", "quantity", "qty"], ["read_tag", "tag", "new_tag"], ["set_reason", "reason", "reason"]]) {
			// Frappe creates inputs lazily for hidden controls. The native callback
			// survives revealing the optional new-tag button without rebinding it.
			dialog.fields_dict[button].df.click = () => enqueue(() => controller[method](dialog.get_value(field)));
		}
		for (const [button, method] of [["camera_scan", "scan"], ["camera_source", "source"], ["camera_destination", "destination"], ["camera_tag", "tag"]]) {
			dialog.fields_dict[button].df.click = () => enqueue(() => open_camera(method));
		}
		dialog.fields_dict.scan.$input.on("keydown", (event) => {
			if (!["Enter", "Tab"].includes(event.key) || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey || event.isComposing) return;
			const value = String(dialog.get_value("scan") || "").trim();
			// Empty Tab remains ordinary form navigation. Empty Enter must not
			// activate the dialog's primary action after a scanner's extra suffix.
			if (!value) {
				if (event.key === "Enter") { event.preventDefault(); event.stopPropagation(); }
				return;
			}
			event.preventDefault(); event.stopPropagation();
			dialog.set_value("scan", "");
			return enqueue(() => controller.scan(value));
		});
		dialog.$wrapper.on("hidden.bs.modal", () => {
			controller.state.closed = true;
			if (cameraSession) {
				const session = cameraSession;cameraSession = null;session.used = true;
				session.scanner?.hide_dialog();
			}
			options.onClose();
		});
		dialog.show();
		// Read pending state before allowing a fresh source; a corrupt slot fails closed.
		try { controller.restore(); } catch (error) { dialog.hide(); throw error; }
		const handle = { focus, scan: (value) => enqueue(() => controller.scan(value)), controller, dialog };
		if (!controller.state.pending && options.sourceScan) await enqueue(() => controller.source(options.sourceScan));
		focus(); return handle;
	}
	const api = { createController, open, pendingKey };
	if (typeof module !== "undefined" && module.exports) module.exports = api;
	else root.cfg_container_repack = api;
})(typeof window === "undefined" ? globalThis : window);
