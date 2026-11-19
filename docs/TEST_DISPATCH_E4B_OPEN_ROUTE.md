# E4B — Open Route customers, sequence policies and stock allocation

## Scope and decisions

Development baseline: `790b15a` (E4A). The owner requested further development and explicitly asked
for both configurable visit-order options during setup. E4B implements Flexible Order and Planned
Order, loaded Open Route Stock multi-customer visits, planned/actual Stop audit, separate customer
Delivery Notes/proof, tagged/untagged origins, unassigned lorry stock and partial posted-stock quantity
containers. It reuses the existing customer-delivery engine and ERP gateway.

The change does not accept E4C direct/pickup, E5 route settlement/reassignment/overnight recovery,
optional E6, invoicing, route optimization, or the outstanding L1 acceptance gate.

Setup and floor instructions: [E4B operator guide](USER_GUIDE_DISPATCH_E4B.md).

## Offline results — 19 November 2026

- **257 Python tests passed**, including 34 E4B tests plus E3/E4A, Dispatch order quantities,
  DocType contracts, operator authorization, stock identity, repack and container release.
- **129 UI checks passed**: E4B 35, E4A 18, Dispatch quantities 9, repack/release 58,
  Hopper lookup 3 and logistics metadata/printing 6.
- Tests execute actual route/delivery functions and the actual dialog/controller/dispatcher with
  in-memory SQL/document/ledger/storage/lock/camera doubles. They do not run native ERPNext.
- Official Frappe 15.69.2 document/current-read interfaces were inspected; the implementation uses
  `get_doc(..., for_update=True)` and supported locking value reads for route state, budget and replay.
- Official ERPNext 15.65.1 Batch quantity signature was inspected. An unsupported
  `ignore_reserved_stock` keyword was removed from the shared tagged/untagged checks and tested
  against a signature-compatible double.
- The existing `test_logistics_foundation` module remains excluded locally because this Python
  environment has no Frappe installation; run it in the bench environment.
- No live E4B site, schema migration, native database-concurrency, ERP posting, S3 proof,
  tablet/camera or kiosk acceptance was run. No deployed E4B revision has been recorded.

Focused commands:

```bash
python3 -B -m unittest cfg_kanban.tests.test_route_delivery
node cfg_kanban/tests/test_route_delivery_ui.cjs
```

Primary compatibility sources:
[Frappe document locking](https://github.com/frappe/frappe/blob/v15.69.2/frappe/model/document.py),
[Frappe database value reads](https://github.com/frappe/frappe/blob/v15.69.2/frappe/database/database.py),
[ERPNext Batch quantity API](https://github.com/frappe/erpnext/blob/v15.65.1/erpnext/stock/doctype/batch/batch.py).

## Live prerequisites and evidence

Record site, deployed SHA (`git log -1 --oneline`), tester/date, Company, lorry Warehouse, Dispatch
Profile/Plan/Manifest/submitted Stock Entry, Customer Sites, stock identities, Items/Batches/UOMs,
Delivery Sessions/Stops/Notes/proof IDs and before/after ERP/HU balances. These are **Not recorded**.

Prepare separate Plans for Flexible Order and Planned Order. Include tagged stock, untagged stock,
an additional unassigned lorry quantity, a single-fill quantity container and a mixed logistics
container. Use separate test drivers and a Supervisor. Configure both Customer route-reference and
Territory constraints where used. Do not reuse production data for destructive acceptance cases.

| Check | Required outcome | Site result |
|---|---|---|
| Migration/defaults | Route Stop schema/indexes sync; old Profile/Plan policy defaults to Flexible without rewriting snapshot JSON | Not run |
| Policy snapshot | Profile changes increment revision; existing Plan retains its original sequence/scope/posting/proof policy | Not run |
| Flexible visits | Visit planned customer 2 before 1; planned positions remain and actual sequence records 1 then 2 | Not run |
| Planned Order | Out-of-order/unplanned visit rejected; planned Site and exact Stop required | Not run |
| Supervisor decision | Required role/permission/reason; approval respects captured override flag; old approval token cannot rewrite a newer approval | Not run |
| Skip/retry | Supervisor skip retains record; empty cancellation retains actual history and creates a planned retry position | Not run |
| Scope rejection | Wrong Company, lorry, route reference, Territory, role, owner or Site snapshot cannot proceed | Not run |
| Concurrent start | Two native transactions cannot create parallel active Stops or duplicate actual sequence for one Plan | Not run |
| Multi-customer sale | Each Site gets a separate locked Session, submitted DN and proof, with exact source stock quantities | Not run |
| Prepared stock budget | Sales/reservations across Stops never exceed each loaded source, including concurrent requests | Not run |
| Unassigned stock | Explicitly selected, independently available, not stolen from another prepared customer/route | Not run |
| Untagged/Batch stock | Stock-UOM precision, mandatory exact Batch and expiry; no fake tag/ledger; native Batch signature works | Not run |
| Cross-Plan/native concurrency | Repeat under the site’s actual transaction isolation, including concurrent stock posting and reservation; no over-promise or negative balance | Not run |
| Partial quantity container | Deliver 2 of 5, retain one loaded fill of 3; next Site can consume remaining quantity | Not run |
| Mixed logistics container | Full current tagged contents only; separate products/batches/origins retained; no partial aggregate pick | Not run |
| Partial reversal | Cancel eligible DN, restore quantity/reservation without duplicating membership; reused contents/required proof remain protected | Not run |
| Draft/submitted ERP | Draft does not deliver stock; only native submission consumes; failures roll back operational changes | Not run |
| Proof | Required evidence keeps Stop active; valid proof closes it and permits next Site; no-proof policy closes on submission | Not run |
| Uncertain retry | Lost response, refresh, camera duplicates and tabs retain one original intent and one stock allocation set | Not run |
| Replay conflict | Changed payload cannot replace a recorded action; read-back returns the existing result | Not run |
| No-record cancellation | Reason required, native scope locks serialize it; late original request cannot post; recorded result is never undone | Not run |
| Scanner/tablet | Enter/Tab, numbered paging, touch source/qty, camera, success/error/cancel focus and full proof flow tested on actual devices | Not run |
| E4A/E3 regression | Known-customer whole-load fulfilment and late lorry loading keep their prior behavior | Not run |

Actual DB tests must cover lock waits/deadlock rollback, read consistency and native ERP/Batch
posting. An in-memory lock/request test does not prove MariaDB concurrency or recovery. Record
failures and deployed SHA rather than promoting offline results to live acceptance.

## Acceptance boundary

Completing Customer Stops does not close the route, settle discrepancies, release remaining route
commitments or complete the Dispatch Plan. E5 must integrate loaded/delivered/returned/overnight
stock with D3, controlled reassignment/cancellation and remaining-stock disposition. Until then,
keep that operational boundary visible. Acceptance of E4B requires the live evidence above.
