# E5B1 guided dispatch recovery — acceptance checklist

Development prepared 20 November 2026 above `5116653`. Implementation is not native/site acceptance.
Use an isolated test site. Record its deployed Git revision, data IDs, ERP/ledger evidence, operator,
result and any accepted exception. No migration, live posting or device test was run by Codex.

## Offline verification

Verified 20 November 2026 against this pending change set:

- **360 Python tests passed**, including 32 E5B1 checks and the E3/E4/E5A, Dispatch quantities,
  schema, authorization, logistics identity, repack and container-release regressions.
- **196 UI checks passed**: E5B1 26, E5A 21, E4C 20, E4A 18, E4B 35, Dispatch quantities 9,
  repack/release 58, Hopper lookup 3 and logistics metadata/printing 6.
- Changed/new Python, JavaScript and DocType JSON syntax, duplicate function/field checks and
  `git diff --check` passed. No native/site tests were run.

`cfg_kanban.tests.test_dispatch_recovery` exercises actual service, Manifest snapshot, native builder,
before-submit composition, feedback and current-read reservation functions with dependency doubles.
`cfg_kanban/tests/test_dispatch_recovery_ui.cjs` exercises the actual controller/dialog, scanner suffixes,
mandatory ERP inputs, retry identities, safe Cancel, camera and global command dispatch with UI/RPC doubles.
Existing E3/E4/E5A, identity, repack, schema and operator regressions must also pass.

Dependency doubles do not establish native SQL compatibility, locking, transaction rollback,
ERP serial/batch bundles, permissions/migration or actual kiosk operation.

## Native scenarios — all Not run

| Scenario | Evidence / expected result | Status |
| --- | --- | --- |
| Setup/permissions | Only active same-Company Direct Transfer routes from original lorry; explicit choice even for one; reject wrong role/Override/Plan/Reconciliation/route responsibilities | Not run |
| Tagged return | Open Review, scan exact tags/containers, prepare, post to return warehouse; one Stock Entry and correct HU ledger/location | Not run |
| Another lorry | Correct configured destination/vehicle reference; original Plan/allocations/loading Manifest retain original vehicle and links | Not run |
| Loose + Batch | Exact non-serial Item/Batch/stock-UOM quantities; physical quantity confirmation required; correct signed ERP bundle/SLE; no fake tag or double reservation | Not run |
| Mixed sources | Tagged plus loose rows, including different Items/Batches/UOMs, confirmed in either order; only prepared remainder moved | Not run |
| Identity | Certificates, printed expiry, Batch expiry, serials and immutable snapshots survive; changed identity or ambiguous certified loose stock rejects | Not run |
| Source mismatch | Changed tag quantity, membership, warehouse, quality, reservation, delivery total, missing loose balance or other Plan commitment rejects | Not run |
| Containers | Complete current group only; empty/extra/off-plan contents reject; physical group scan required; group location feedback correct | Not run |
| Preparation replay | Concurrent duplicate preparation reserves once; current recipe and competing loose commitments checked | Not run |
| ERP Draft | Auto-submit disabled creates one saved Draft; manual submission revalidates recipe/availability; duplicate/substitute/deleted or detached Draft attempts reject | Not run |
| Posting replay | Lost response/repeated confirm/reopen uses the same Manifest/ERP Command/document; no duplicate movement | Not run |
| Failed posting | Mandatory-input failure, negative stock, failed command, deadlock and response loss allow controlled read-back/retry with atomic rollback | Not run |
| Unused cancellation | Cancel before ERP work releases once, preserves history; second destination possible; old create-token replay cannot resurrect a cancelled recovery | Not run |
| ERP cancellation guard | Pending ERP work cannot be abandoned through Manifest cancel, direct delete or Review Resume; submitted controlled movement cancellation blocked | Not run |
| Final Review | Stock-stays/unrelated movement rejected while recovery active; exact submitted movement plus fresh balanced D3 count settles; source/destination stock and commitments agree | Not run |
| Other lorry activity | Other Plans/unassigned stock not included in recovery; count covers complete lorry; intervening stock changes require a fresh count | Not run |
| Multi-day trip | Ordinary two-to-three-day Plan continues normally; no automatic midnight/daily closure; E5A overnight choices unchanged | Not run |
| Scanner/tablet | Production and Logistics global command; printable labels; paged route/loose choices; full scanner-only Tab/Enter flow; mandatory scalar/table values; camera, Cancel, operator switch and focus on real devices | Not run |
| Regressions | E3 loading, E4 fulfilment/proof/pickup, D3 counts, existing direct/transit/intercompany movement, certificate identity and container tools | Not run |

Specifically exercise raw SLE and Serial and Batch Bundle locking queries on installed
Frappe 15.69.2 / ERPNext 15.65.1 and MariaDB, including backdated/future entries, cancelled entries,
UOM rounding and simultaneous reservations/submissions/counts. Preserve failures and Not run statuses.

## Result record

- Site / deployed revision:
- Plan / original loading Manifest / Review / recovery Manifest:
- Source/destination Warehouses / tags / certificates / Batch:
- Stock Entry / ERP Command / SLE or bundle / HU ledger:
- D3 count / final Review disposition:
- Operator / date / result / exceptions:

This increment covers the entire prepared remainder to one destination. Mixed per-line/multiple
movements, receiving recovery Plans/reassignment, wider known-customer partial/refused fulfilment
and guided damage/write-off decisions are not implemented by this increment. Package L1 and the
other unrecorded acceptance gates remain open.

## Manual untagged quantity entry — 26 November 2026

Correction: the recovery dialog now offers an explicit **Enter Count** choice and a discoverable
quantity control. Raw manual input immediately updates the same controller as scanner entry;
unchanged field properties no longer trigger native refresh, and typing does not restore scanner
focus until an action completes. Native delayed onchange and multi-digit/decimal input are covered.
No expected amount is prefilled as a physical count. Pending requests retain their original value.
The D3 open-movement closure guard remains mandatory.

Offline checks include the actual controller/dialog with RPC/UI doubles and a standalone browser
fixture with real DOM events plus Frappe-like 500 ms change/model refresh. Run
`node cfg_kanban/tests/run_dispatch_recovery_browser.mjs` in Chrome, or prefix with
`CFG_BROWSER=firefox` for Firefox. No native ERPNext site or stock is connected.

Live acceptance for this correction remains **Not run**:

- Reopen an existing Draft recovery with one confirmed tag and one untagged row. Select Enter Count,
  type its exact physical quantity, and confirm with touch; use no stock QR for that ERP row.
- Type a multi-digit decimal for a fractional stock UOM; the caret/focus and quantity must survive
  a pause longer than 500 ms. The primary button must enable at the exact valid quantity.
- Complete the same row by scanner, and verify its quantity is mirrored into the visible field.
- A mismatch cannot prepare stock. An uncertain response locks the original value and identity.
- Prepare and post through existing native controls, submit a saved Draft if required, and wait
  for Received. Recount remaining lorry stock, evaluate/close D3 and finish the matching Review.
- A still-open Manifest must continue blocking Close Balanced Route. Cancel only through the
  authorized unused recovery or complete per-item decision-set action before ERP work begins.

Offline result for this correction: **103 Python regression tests**, **35 recovery UI checks**
and **29 related UI checks** passed. The DOM fixture passed **22 checks in Chrome and 22 in
Firefox**, covering typed quantities before blur, retained focus through the native-style delay,
multi-digit decimals, exact source confirmation, prepare/post feedback, mismatch rejection,
unknown-result retry and safe Cancel. These results do not verify the development site's Manifest,
native ERPNext posting/rollback, actual permissions or physical stock.
