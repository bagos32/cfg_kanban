# Driver field workflow — verification and native acceptance

Prepared 27 November 2026 above `f328dcd`. **Offline checks only; native-site/device acceptance is
Not run.** No live Trip, Plan, Manifest or Return Case was read or changed. This includes reported
`KRTN-2026-00010`.

## Changes under test

1. Customer Scan Point **Require Product Check Before Delivery**, default off, frozen on new
   Delivery Sessions; scan exact accepted tag/box/bin contents or explicitly count untagged stock.
   Enforce the saved allocation fingerprint before confirmation, DN creation and native Draft
   submission. Existing site, Company, stock/expiry, driver/team, responsibility, document and proof
   controls remain. Scans create only verification evidence/events.
2. Exact Manifest rows use persisted loading/receipt/registration flags for their green state.
3. Driver Route/Logistics switch, remembered Trip per ERP user/operator in this browser tab, and
   scanner navigation commands.
4. Material Genealogy **Back to Logistics** and scanner command.
5. Custody-label selector/quantity survive synchronous native Select change during construction;
   picker matches the old-return/collected/QC-waiting rules enforced on creation.
6. Handover colours distinguish actual settled Plan state from completed delivery/review.
7. Office Trip tools grouped, scoped wrapping and viewport-clamped native dropdowns.
8. Production Operator Tools grouped with scanner/camera/session actions preserved. Styling is
   removed when the native Form wrapper is reused by an ordinary ERPNext document.

Native button grouping uses the documented third `group` argument to
[`frm.add_custom_button`](https://docs.frappe.io/framework/user/en/api/form), which delegates to the
Page toolbar. Offline DOM checks use lightweight native-UI doubles, not a running Frappe Desk.

## Reproducible offline checks

Use the repository's Python unittest / Node test workflow from the checkout. Frappe is not
installed in the offline environment; service bodies run against explicit DB/document/ERP doubles.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest cfg_kanban.tests.test_delivery_product_scans cfg_kanban.tests.test_dispatch_fulfilment cfg_kanban.tests.test_route_delivery cfg_kanban.tests.test_warehouse_fulfilment cfg_kanban.tests.test_driver_route_actions cfg_kanban.tests.test_trip_sales cfg_kanban.tests.test_loose_tags cfg_kanban.tests.test_trip_handover cfg_kanban.tests.test_mobile_printing cfg_kanban.tests.test_doctype_schema
node --test cfg_kanban/tests/test_field_ui.cjs cfg_kanban/tests/test_delivery_product_checks.cjs cfg_kanban/tests/test_office_delivery_trip_ui.cjs cfg_kanban/tests/test_trip_handover_ui.cjs cfg_kanban/tests/test_driver_route_ui.cjs cfg_kanban/tests/test_driver_route_actions_ui.cjs cfg_kanban/tests/test_mobile_print_bridge.cjs cfg_kanban/tests/test_dispatch_fulfilment_ui.cjs cfg_kanban/tests/test_route_delivery_ui.cjs cfg_kanban/tests/test_warehouse_fulfilment_ui.cjs
node cfg_kanban/tests/run_driver_field_browser.mjs
CFG_BROWSER=firefox node cfg_kanban/tests/run_driver_field_browser.mjs
node cfg_kanban/tests/run_mobile_print_browser.mjs
CFG_BROWSER=firefox node cfg_kanban/tests/run_mobile_print_browser.mjs
node cfg_kanban/tests/run_trip_handover_browser.mjs
```

`CFG_FIELD_WIDTH=320`, `768` or `1280` selects the isolated Chrome viewport for the field fixture.
The fixtures have no real stock, ERPNext site, printer, hardware camera or physical scanner.

Service coverage includes wrong-customer identity, expired/moved/unreleased sources, exact
untagged quantity and Item, immutable source/quantity evidence, explicit Session permissions,
manual Draft DN gate, original retry/payload-conflict checks, replacement allocations, exact
container membership and two-SKU Loose Tag partial refusal. A previously scanned pack verifies
only its accepted quantities (3 of A, 1 of B); refused stock stays on its existing outcome.
Assertions compare quantity-ledger calls, HU balances and native-document inventories before and
after checking. Controller tests reject forged new/edited evidence. Default-off older Sessions
retain their original behavior.

Browser coverage includes the actual driver action component/checklist, manual numeric input,
wrong-tag and wrong-quantity rejection, one green line at a time, lost acknowledgement and exact
retry, focus restoration, camera callback, navigation memory, toolbar wrapping/clamping and
ordinary-form scope cleanup. The printing fixture forces Select change during construction,
asserts selector and quantity visibility, and exercises existing uncertain-action readback.

Final recorded results are appended after the completed regression run below.

## Migration / native acceptance

Owner performs the normal CFG-only `bench --site site1.local migrate`, asset build and cache
clear after review/commit/pull. No dependency, Frappe or ERPNext version change is required. The
new standard fields are two default-off site/Session Checks plus read-only allocation Check/JSON
text evidence. There is no data rewrite, automatic stock movement, delivery or closure.

On a test site, record deployed revision, device/browser, operator and supporting documents:

| Native scenario | Required evidence | Result |
| --- | --- | --- |
| Existing disabled site | Normal prepared/Open Route/direct/pickup flow remains available. | Not run |
| Enabled customer, new Session | Exact policy snapshot; pending tag and untagged rows; no prefilled untagged count. | Not run |
| Physical tag / wrong stop | Only allocated identity becomes green; foreign tag rejected with no posting or completion. | Not run |
| Untagged stock | Touch quantity and scanner SELECT/QTY/CONFIRM both save exact Item/Batch/stock UOM count. | Not run |
| Container / quantity bin | Current exact contents accepted; mixed other-customer contents require individual tags. | Not run |
| Multi-SKU Loose Tag with refusal | One box scan; accepted 3 A/1 B checked; refused 1 B retains existing outcome/stock. | Not run |
| DN / proof | Missing check blocks ordinary API and manual Draft submit; submitted DN, quantities, Company/UOM/expiry and proof still validated. | Not run |
| Retry / concurrency | Lost reply, two tabs and assistant actions retain one evidence result; source replacement needs a new check. Real MariaDB rollback/locks remain native acceptance. | Not run |
| Manifest loading / receipt | Exact accepted row green after server reply and reload; wrong scan has no effect; receiving requires its own scan. | Not run |
| Custody-label form | Exact collected old-return Item and quantity visible on real Frappe; partial labels and reprint work; no stock/credit. | Not run |
| Field navigation | Touch slider and printable DRIVER_ROUTE/LOGISTICS_PANEL commands; same operator and Trip; Genealogy return; pending-action recovery retained. | Not run |
| Handover | Green only for Reconciled; Completed delivery/review remains amber when settlement is pending; Exception red. | Not run |
| Toolbar / kiosk | Real native Trip Tools and Operator Tools, all actions reachable at tablet widths and rotation; no overflow; ordinary forms unaffected. Scanner-only full-screen completion/error/cancel and physical camera focus verified. | Not run |

Do not equate fixture results with native stock posting or live-site verification.

## Recorded offline results — 27 November 2026

- Python command above: **349 tests passed**. Includes the real Open Route selection → required
  product check → existing DN/feedback path, and default-off regressions.
- Node command above: **196 reported test entries passed**. This includes three legacy script
  entries, whose internal runners report 22 E4A, 38 E4B and 20 E4C UI checks respectively.
- Field fixture: **26 checks passed** in Chrome at 320, 768 and 1280 CSS pixels, and Firefox at
  1366 pixels. The final shared camera helper was checked again at tablet width.
- Printing fixture: **102 checks passed in Chrome and 102 in Firefox**, including native-Select
  callback timing, visible custody controls and original uncertain-action identity.
- Trip Handover fixture: **22 checks passed in Chrome and 22 in Firefox** with the actual colour
  helper loaded.
- Changed Python sources parsed; changed JavaScript passed Node syntax checks; changed schemas
  parsed as JSON. Checkout application and whitespace/hash checks are recorded during final review.

These are offline results. They do not close any native-site/device acceptance row above.

## Follow-up: native headers, menu stacking, Plan choices and custody auto print

Prepared above `66d4623`, 27 November 2026. The owner's screenshots showed a body-mounted large
switch, a Tools menu behind the sticky identity fields, and uncoloured numbered Handover Plans.
The earlier fixture checked viewport edges but did not model the native header's stacking context.

The expanded field fixture uses Frappe v15.69.2's real class hierarchy (`page-head`, `title-area`,
`custom-actions`, `inner-group-button`), header z-index 6 and CFG scanner z-index 30. Sources:
[Page template](https://github.com/frappe/frappe/blob/v15.69.2/frappe/public/js/frappe/ui/page.html),
[Page API source](https://github.com/frappe/frappe/blob/v15.69.2/frappe/public/js/frappe/ui/page.js),
[Page styles](https://github.com/frappe/frappe/blob/v15.69.2/frappe/public/scss/desk/page.scss).
It verifies title/switch row geometry, compact size, phone/tablet width, actual `elementFromPoint`
menu hit-testing over the scanner, a dispatched pointer click and native modal priority. It remains
a DOM/Bootstrap-event double, not a complete native Desk. The Handover fixture colours four actual
Plan choice buttons without the global app stylesheet, while exercising existing scanner/recovery
selection and focus.

Custody auto-print coverage includes the off-by-default site setting, Company/customer scope,
separate label creation and native print preparation, exact new label identity/format/one copy,
paired first handoff, absent user gesture, explicit browser rejection, unpaired fallback and lost
preparation readback without paper resend. No test uses a live Return Case, device or printer.

Additional native acceptance (all **Not run**):

- Actual Logistics and Driver Route title rows at desktop/tablet/phone widths and browser zoom.
- Operator Tools and Trip Tools items clickable above all native sticky fields; rotation, native
  toolbar collapse, dialogs and other ERPNext forms still work.
- This exact Trip Handover page shows its legend, coloured summaries and numbered Plan buttons,
  including Loaded/pending and Cancelled audit rows, after refresh/deep link.
- New Scan Point field defaults off after migration. On/Off creation policy at the exact site;
  configured native custody format, paired Android companion, phone browser app-launch permission,
  one physical copy, printer failure, paper confirmation, interrupted preparation and explicit reprint.

Final regression counts for this follow-up are recorded below after validation. Old acceptance
results above remain evidence for that revision, not live acceptance of this update.

Follow-up offline results, 27 November 2026:

- **201 Python tests passed**: mobile printing, stop document policies, schema, Trip Handover and
  driver actions. New tests cover the default-off custody option and reject another Company/customer
  policy before label creation; creation itself still inserts only its custody record.
- **199 Node test entries passed**, including the existing E4A/E4B/E4C script checks; printing
  contracts passed again after updating Scanner Help.
- **38 field browser checks passed** in Chrome at 320, 768 and 1280 CSS pixels and Firefox at
  1366 pixels. The fixture now includes actual header geometry and menu hit-testing over a sticky
  scanner, rather than only menu edge coordinates.
- **27 Handover browser checks passed in each of Chrome and Firefox**, including the exact
  numbered Plan choices and colours from the page's own stylesheet.
- **133 printing browser checks passed in each of Chrome and Firefox**, covering custody policy
  off, one-copy auto preparation and paired first handoff, unpaired fallback, absent transient
  gesture, explicit browser rejection and retained original preparation after a lost response.
- Changed Python/JavaScript/JSON sources passed syntax/parsing checks. An offline desktop screenshot
  was inspected to confirm the compact switches appear beside the titles.

No site, physical scanner/camera, Label Bridge app or printer was used. These results do not mark
any of the native acceptance cases as passed.
