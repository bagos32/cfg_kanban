# E5A — Dispatch review and settlement acceptance

Development date: 20 November 2026. Git base: `fc889fa` (E4B), with the pending E4C changes preserved.
The owner explicitly authorized E5 above pending E4C. Overnight closing must offer both release of
old commitments and continuation of the same Plan. Normal long-distance trips span two to three
days under one Plan, without forced daily closure.

E5A implements review/freeze, Plan-specific stock summaries, D3 count linkage, overnight choices,
variance Holds, guarded Resume, and exact submitted return/transfer evidence. It does not claim the
whole E5 roadmap. Guided whole-remainder transfer creation is now covered by
[the E5B1 checklist](TEST_DISPATCH_E5B1_RECOVERY.md). Mixed per-line dispositions, follow-on recovery
Plans, wider partial/refused customer fulfilment and broad native operational hardening remain later E5B scope.

## Recorded offline checks

- **328 Python tests passed**, including 39 E5 tests plus E4C/E4B/E4A/E3, Dispatch quantities,
  schema, operator authorization, logistics identity, repack and container release.
- **167 UI checks passed:** E5 18, E4C 20, E4A 18, E4B 35, Dispatch quantities 9,
  repack/release 58, Hopper lookup 3 and logistics metadata/printing 6.
- Changed/new Python, JavaScript and JSON syntax and `git diff --check` passed.
- E5 tests execute actual service/controller/dialog/dispatcher source with document, SQL, ERP,
  ledger, camera and UI doubles. They do not execute a MariaDB transaction or native ERP posting.
- Three-day tests serve customers on different dates under the same Plan and close on day three;
  two consecutive formal overnight pauses retain the same commitments. They do not simulate native
  authentication expiry; live tests must re-identify/renew credentials normally.
- D3 has an optional current-read branch that reads raw legacy/bundle SLE rows with locks and sums
  them without losing duplicate Item/Batch rows. Grouped legacy reads remain supported. ERPNext
  15.65.1's bundle implementation was inspected for signed outward quantities:
  [official source](https://github.com/frappe/erpnext/blob/v15.65.1/erpnext/stock/doctype/serial_and_batch_bundle/serial_and_batch_bundle.py).
  This is source compatibility evidence, not native database or stock-balance acceptance.
- Local Frappe is unavailable. Bench-native logistics foundation checks remain not run locally.
- No E5 live site, migration, native concurrency, stock movement, kiosk/tablet/camera or deployed SHA
  acceptance evidence has been recorded.

Focused checks:

```bash
python3 -B -m unittest cfg_kanban.tests.test_dispatch_reconciliation
node cfg_kanban/tests/test_dispatch_review_ui.cjs
```

## Live evidence to collect

Record site, deployed SHA (`git log -1 --oneline`), tester/date, native DB/isolation configuration,
Companies and lorry Warehouses, Profiles/Plans, all three trip dates, route Stops/Sessions/Delivery
Notes/proof, HU/Batch/certificate identities, D3 counts, Review IDs, movement Manifests/Stock Entries,
SLE posting/creation times, Exceptions and before/after ERP/HU/reservation balances. **Not recorded**.

| Scenario | Required result | Live result |
|---|---|---|
| Additive migration | Review DocType/unique guards sync; old Plans remain unaffected and unreviewed | Not run |
| Permissions | Both Plan responsibility and Logistics Reconciliation; Start/Complete; leftovers/Hold/abandon require Supervisor Override | Not run |
| Freeze | No new delivery/Stop changes while Reviewing/Held/Overnight/Settled; existing history remains readable | Not run |
| Multi-day trip | One Plan/lorry across days 1–3, customer proof each visit; no forced daily closure or quantity reset; renew operator authentication normally | Not run |
| Whole-trip D3 count | Opening count may begin at departure, closing count after final review; submitted movements across all days included | Not run |
| Complete delivery | Zero prepared remainder plus closed current balanced count finalizes Plan; stock untouched by settlement | Not run |
| Close with stock staying | Exact stock remains in lorry, old commitments released, Plan Reconciled / Closed Incomplete | Not run |
| Continue same Plan | Commitments retained, Overnight snapshot stored, explicit Resume required; repeat for two nights | Not run |
| Stock summaries | Prepared and additional unassigned customer deliveries separate; all lorry stock visible; other-Plan stock never presented as freely allocatable | Not run |
| Active work | Pending allocation/Draft/proof/Exception delivery or open Manifest blocks closure | Not run |
| Count scope/currentness | Wrong Company/lorry, old/unclosed/variance count, changed HU/membership or changed ERP balance rejects | Not run |
| Hold | Critical Exception, no stock release or write-off; only counted disposition resolves Hold; Resume cannot bypass it | Not run |
| Returned tags | Exact submitted Stock Entry, completed Manifest, certificates/expiry and updated HU destination; original loading history retained | Not run |
| Transferred lorry | Active same-Company destination lorry; original vehicle snapshot immutable; no automatic receiving Plan claimed | Not run |
| Loose stock evidence | Exact non-serialized Item/Batch/stock-UOM amounts; missing loose balance rejects; no invented tag/ledger | Not run |
| Evidence chronology | SLE creation after review opening, before count closure; posting time no later than closure; future/stale movement rejected | Not run |
| Evidence reuse/cancellation | One movement cannot settle two Reviews, including concurrent requests; settled Stock Entry cancellation blocked | Not run |
| Planned visits | Unvisited Stops retained as skipped with closing reason for final trip closure; continued overnight preserves future stops | Not run |
| Retry/replay | Repeated start/finish/resume and lost responses return recorded state; changed payload rejected; old tokens cannot recreate a resumed/closed action | Not run |
| Native race/rollback | Concurrent posting/count/start/cancel/settlement, SLE/Bin locks, deadlocks, unique collisions and rollback leave no partial closure or released commitment | Not run |
| Scanner/camera | Global and printable commands, physical IDs, numbered choice, count/movement/reason, Tab/Enter, safe Cancel, focus and wrong-operator guards on real devices | Not run |
| Regressions | Existing D3 grouped/bundle counts, vehicle loading, E4 deliveries/pickup, transfer identity/repack and recovery protections remain valid | Not run |

Explicitly test the native raw SLE/bundle locking queries against the installed MariaDB and ERPNext
versions, including backdated posting, cancelled entries, serialized/batch stock, precision and large
multi-day trips. Dependency doubles do not establish native locking, atomicity or performance.

Return/transfer evidence in E5A covers all remaining prepared stock in one movement to one destination.
Where the current floor workflow cannot represent loose Batch transfers, use only the approved
Supervisor native ERP fallback. Guided whole-remainder recovery now has its own [E5B1 checklist](TEST_DISPATCH_E5B1_RECOVERY.md);
mixed dispositions remain later scope. Do not mark either accepted from an E5A pass. Package L1 and the other unrecorded acceptance gates remain open.

## Change boundary

The pre-E5 local E4C diff, files and protected-document hashes were captured before editing under
`/tmp/cfg-dispatch-e5/baseline`. The handover and `USER_MANUAL_V2.23.md` match that saved content.
Existing E4C service, migration, guide and tests remain in the pending change set.

E5 adds Dispatch Review schema/controller, `services/dispatch_reconciliation.py`,
`public/js/dispatch_review.js`, the two E5 test modules and this guide/checklist. It extends Plan
schema/guards, route/known-customer execution gates, reversal protection, D3 current reads, the
Stock Entry cancellation hook, operator commands/Logistics UI and relevant requirements/manual/tests.
Shared files contain both authorized increments; no commit, pull, push or deployment was performed.
