# Document-backed Route / Plan closure and shared E5 count

27 November 2026. Local implementation over base `8359891`; no deployment or live acceptance.
The named customer reproduction records were not accessed or changed. All verification uses demo
records, in-memory transaction doubles or localhost UI/RPC fixtures. Native Frappe/MariaDB stock
and concurrency behavior is still unverified.

## Implemented contract

- Close Route reuses Start + Supervisor Override, route scope/member authorization and native
  source-document reads. It preflights all members before writes, wraps settlement/Sheet/audit/
  response in a savepoint, and uses the existing route action receipt for identical-token replay.
  Completed-route retries do not create another settlement/audit. Cancel Route is unchanged.
- Deliveries require Closed Sessions, exact submitted non-return Delivery Notes and allocations,
  matching Company/customer/address/lorry, SKU/Batch/stock UOM/quantity/tag/SO row, and submitted
  required proof with its required captured evidence. Unfinished visits, delivery/transfer commands,
  reservations, packs, Manifests and exceptions block closure with a specific diagnostic.
- Only Plan sources are balanced. Another Plan's lorry stock is untouched and need not be counted.
  Optional non-stock invoice/print follow-up is not converted into a delivery-stock blocker.
- Standalone Open Route Stock Close Plan supports an existing exact Received return Manifest.
  Submitted direct or both Goods-in-Transit transfers, their exact voucher-detail SLE quantities
  and tag location ledgers must match. A pre-review return after the load is valid. Foreign/reused
  settlement evidence, a later reuse of the same tag before the claimed return, mismatches and
  ambiguous ownership are rejected. Ambiguous valid candidates require an explicit selection.
- Untagged historical stock needs Dispatch Allocation provenance. Selecting an arbitrary matching
  SKU total cannot prove Plan ownership. Missing evidence retains E5 rather than manufacturing it.
- Historical return identity uses frozen Manifest/ERP facts. Normal stock posting still runs its
  live certificate/tag checks before the extracted native structural transfer validator. Settlement
  does not reapply today's mutable identity or remaining quantity to a valid past return.
- Existing Dispatch Reviews/Events retain actor/time, original delivery outcome, quantities and
  supporting DN/proof/transfer/ledger references. Returned quantities are Returned to Warehouse;
  partial/undelivered outcomes remain Closed Incomplete. No closure creates a movement or stock post.
- Trip Handover accepts Trip, Route Sheet or standalone Plan. Its Next Guided Step opens an
  unfinished delivery, missing Review, pending movement, one lorry count or the next Finish Review.
  One current balanced count on the same Company/lorry can back every Review opened before it.
  All movements finish first; a later movement or later-opened Review requires a new count. Native
  E5 count and disposition validation is unchanged. Unrelated Plans are not silently frozen.

## Offline verification

Checkout verification: **633 Python tests passed**, including **28 closure tests**; **258 JavaScript checks passed** across 11 suites. A final reason/retry guard also passed the 76 focused closure/route tests. These are offline results only.

- Python: the closure suite plus route sheets, reconciliation, handover, cancellation, E3 loading,
  prepared/open-route fulfilment, recovery, stop cancellation, consolidated/office Trips, sequence,
  mixed recovery, E5 hardening, reservation hardening, stock identity, Loose Tags, follow-on Trips,
  installation and DocType schema regressions. Uses actual application functions with dependency
  doubles. The savepoint model is not evidence of native SQL rollback/isolation.
- JavaScript: route sheet, review, handover, recovery, fulfilment, route delivery, Plan cancellation,
  Loose Tags, Trip continuation, driver route and dispatch quantity suites. Actual controllers/
  adapters with explicit RPC/DOM doubles; scanner commands/catalogue/global routing included.
- Isolated Chrome and Firefox closure fixture: 10 checks each, including single Close Route,
  exact Sheet/revision, unknown-response replay, no posting/count RPC, paged return selection,
  count-free Close Plan and restored Scanner Ready focus.
- Isolated Chrome Trip Handover fixture: 21 checks, including the visible guide, shared-count
  handoff, native recovery navigation, Tab/Enter/camera, safe Cancel and unknown-request recovery.
- Python parsing, JSON field-order/metadata regression and JavaScript syntax checks. Existing
  trailing whitespace in unchanged manual lines is preserved; Git diff checks only changed lines.

Browser runners: `run_dispatch_closure_browser.mjs` (optional `firefox` argument) and
`run_trip_handover_browser.mjs`, under `cfg_kanban/tests`. They use localhost demo RPC and isolated
browser profiles; no ERPNext credentials, site or physical stock/printer are connected.

## Migration

Owner-run normal CFG migration adds these optional readonly Dispatch Review fields:

- `settlement_basis`: Lorry Count / Posted Documents; new manual Reviews default to Lorry Count.
- `closure_evidence_json`: immutable document-backed settlement details in completed Review audit.

Build CFG assets and clear cache/restart through the normal owner deployment sequence. No data
migration closes records, rewrites old Reviews, re-reserves stock or posts ERP documents. Existing
manual reviews with an empty historical basis retain their original count evidence. No new
external dependencies, ERPNext/Frappe upgrade or new stock DocType is required.

## Isolated live-site acceptance — all Not run

Record actual Bench versions and the deployed Git revision. Use disposable test fixtures only.
Do not use or alter the customer's reported Route Sheet / Plans for acceptance.

| Check | Required evidence | Result |
| --- | --- | --- |
| Full route, tagged + untagged | Native submitted DNs and required proof; route and all Plans close together while unrelated stock remains unchanged | Not run |
| Historical return | Exact direct and two-leg pre-review returns, source lineage and SLE/tag ledger; one existing movement referenced, none created | Not run |
| Return rejection | Wrong item/Batch/UOM/quantity/tag/Company/lorry/destination, reused Stock Entry, missing serial/certificate snapshot or ambiguous loose provenance names its blocker | Not run |
| Partial delivery | Delivered DN total remains unchanged; remainder closes Returned to Warehouse / Closed Incomplete | Not run |
| Proof / unfinished posting | Missing signature/photo/GPS, Draft/cancelled DN, pending Session/command/Manifest/pack/exception cannot close | Not run |
| Atomic failure | Inject a failure on member two and during final Sheet/audit/response; actual database retains neither settlement nor closure | Not run |
| Concurrency / retry | Two tabs/operators, lost replies, proof/cancellation/return posting races and cross-Plan reuse; no deadlock, duplicate audit, release or movement | Not run |
| Permissions | Native terminal role and Company/warehouse/document user permissions; unauthorized role/responsibility/Start/Complete/Override cannot bypass closure | Not run |
| Evidence cancellation | Existing hooks prevent cancelling a submitted transfer already used as settlement evidence | Not run |
| Shared count | Open all group Reviews first, post all movements, close one D3 count, settle each using it; later movement/review invalidates reuse | Not run |
| Guide / kiosk | Trip and legacy Sheet groups, blocking delivery navigation, exact numbered choices, camera, Tab/Enter, unknown retry, safe Cancel/focus without mouse | Not run |
| No stock effects | Compare Manifest, SE, DN and SLE identifiers/counts plus stock/tag quantities before and after every success/failure/retry | Not run |

## Changed files

The final file inventory and verification totals are appended below. Owner handover/manual-version
files and outputs are excluded; no Git commit, push, pull, deployment or live mutation is performed.

- `cfg_kanban/api/operator.py`
- `cfg_kanban/cfg_kanban/doctype/cfg_kanban_dispatch_review/cfg_kanban_dispatch_review.json`
- `cfg_kanban/cfg_kanban/page/kanban_logistics/kanban_logistics.js`
- `cfg_kanban/cfg_kanban/page/kanban_operator/kanban_operator.js`
- `cfg_kanban/integrations/logistics_feedback.py`
- `cfg_kanban/public/js/dispatch_review.js`
- `cfg_kanban/public/js/route_sheet.js`
- `cfg_kanban/public/js/trip_handover.js`
- `cfg_kanban/services/dispatch_closure.py`
- `cfg_kanban/services/dispatch_planning.py`
- `cfg_kanban/services/dispatch_reconciliation.py`
- `cfg_kanban/services/route_sheets.py`
- `cfg_kanban/services/trip_handover.py`
- `cfg_kanban/tests/fixtures/dispatch_closure_browser.html`
- `cfg_kanban/tests/fixtures/trip_handover_browser.html`
- `cfg_kanban/tests/run_dispatch_closure_browser.mjs`
- `cfg_kanban/tests/test_dispatch_closure.py`
- `cfg_kanban/tests/test_dispatch_reconciliation.py`
- `cfg_kanban/tests/test_dispatch_recovery.py`
- `cfg_kanban/tests/test_dispatch_review_ui.cjs`
- `cfg_kanban/tests/test_route_sheet_ui.cjs`
- `cfg_kanban/tests/test_route_sheets.py`
- `cfg_kanban/tests/test_trip_handover.py`
- `cfg_kanban/tests/test_trip_handover_ui.cjs`
- `docs/DISPATCH_PLAN_BASELINE.md`
- `docs/TEST_DISPATCH_DOCUMENT_CLOSURE.md`
- `docs/TEST_LORRY_ROUTES_AND_FLOOR.md`
- `docs/USER_GUIDE_DISPATCH_E5A.md`
- `docs/USER_GUIDE_LORRY_ROUTES_AND_FLOOR.md`
- `docs/USER_MANUAL.md`


Python command modules (run with `python3 -B -m unittest` and `PYTHONDONTWRITEBYTECODE=1`):

```
cfg_kanban.tests.test_dispatch_closure
cfg_kanban.tests.test_route_sheets
cfg_kanban.tests.test_dispatch_reconciliation
cfg_kanban.tests.test_trip_handover
cfg_kanban.tests.test_dispatch_plan_cancellation
cfg_kanban.tests.test_dispatch_e3_behavior
cfg_kanban.tests.test_dispatch_fulfilment
cfg_kanban.tests.test_route_delivery
cfg_kanban.tests.test_dispatch_recovery
cfg_kanban.tests.test_trip_stop_cancellation
cfg_kanban.tests.test_consolidated_dispatch
cfg_kanban.tests.test_office_delivery_trip
cfg_kanban.tests.test_trip_sequence
cfg_kanban.tests.test_dispatch_recovery_mixed
cfg_kanban.tests.test_e5_recovery_hardening
cfg_kanban.tests.test_dispatch_reservation_hardening
cfg_kanban.tests.test_logistics_stock_identity
cfg_kanban.tests.test_loose_tags
cfg_kanban.tests.test_stop_cancellation_recovery
cfg_kanban.tests.test_trip_continuation
cfg_kanban.tests.test_installation
cfg_kanban.tests.test_doctype_schema
```
