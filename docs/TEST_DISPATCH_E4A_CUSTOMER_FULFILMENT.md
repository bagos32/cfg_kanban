# E4A — Prepared known-customer fulfilment acceptance

## Scope and evidence

Runtime baseline before development: `d01b40d`. On 19 November 2026 the owner reported that E3
worked on site, including loading goods into a lorry selected at the last minute, and requested
continued development. The owner explicitly requires both tagged and untagged quantities in E4A.
The site identity, deployed E3 SHA and full A–F acceptance evidence remain unrecorded; the owner’s
positive-path result does not independently verify concurrency or all negative cases.

E4A reuses Customer Delivery Sessions/Allocations, the ERP gateway, native Delivery Notes, shared
certificate identity, proof and controlled returns. It adds no separate delivery engine. E4B, E4C,
E5 and E6 are not accepted by this increment.

Read [the setup/operator guide](USER_GUIDE_DISPATCH_E4A.md) before running these checks.

## Offline regression

```bash
python3 -B -m unittest cfg_kanban.tests.test_dispatch_e3_behavior cfg_kanban.tests.test_dispatch_fulfilment cfg_kanban.tests.test_dispatch_order_quantities cfg_kanban.tests.test_doctype_schema
node cfg_kanban/tests/test_dispatch_fulfilment_ui.cjs
node cfg_kanban/tests/test_dispatch_order_quantities_ui.cjs
```

The E4A tests exercise actual bridge, reservation, payload-builder, feedback and proof functions
against in-memory document/SQL/ledger doubles. UI tests execute the actual controller/dialog and
scanner dispatcher. Native ERPNext 15.65.1 source was inspected for Sales Order UOM/conversion
validation; native ERP execution is still a site check.

They do not establish MariaDB locking, transaction rollback, native ERP stock/batch/serial
submission, migrations on existing data, S3 evidence, browser layout or real camera/scanner/kiosk
behavior. A simulated Stock Entry/Delivery Note is not a real ERP posting.

## Recorded development result — 19 November 2026

- **223 Python tests passed** across E3, E4A, Dispatch order quantities, DocType contracts,
  operator authorization, stock identity, container repack and container release.
- E4A contributes **32 actual-function behavioral/contract tests**; E3 contributes 18.
- **94 UI checks passed**: E4A 18, Dispatch quantities 9, container repack/release 58,
  Hopper lookup 3 and logistics metadata/printing 6.
- Changed JavaScript sources passed syntax checks; `git diff --check` passed.
- The existing `test_logistics_foundation` module was also attempted but **could not import**
  because the local Python environment has no `frappe` installation. It is not included in the
  passed count and still needs the Frappe/bench environment.
- No live E4A site, database-concurrency, native ERP, migration, camera or kiosk acceptance was run.
- Tests ran on the existing worktree at `d01b40d` plus these uncommitted E4A/checkpoint changes.

## Required live records

- Site / tester / date: **Not recorded**
- Deployed E4A commit (`git log -1 --oneline`): **Not recorded**
- Company / dispatch point / Profile / route: **Not recorded**
- Customer Site / Customer / address / proof policy: **Not recorded**
- Loaded Plan / Manifest / submitted loading Stock Entry / lorry Warehouse: **Not recorded**
- Exact tagged and untagged Items, Batch, stock UOM and quantities: **Not recorded**

Use separate Plans where appropriate. Keep an ERP stock/physical-tag before-and-after record.

| Test | Expected outcome | Site result |
|---|---|---|
| Migration | Existing tagged allocations retain identities, quantities and audit; allocation kind backfilled | Not run |
| Known-customer lookup | Exact Site shows authorized loaded Plans and lorry; several Plans require explicit selection | Not run |
| Mixed load start | One Session; exact loaded tags and loose quantities staged; no stock posting or phantom tag | Not run |
| Responsibility/owner controls | Both required responsibilities; another operator cannot adopt an existing Session | Not run |
| Rejection controls | Wrong Site/Company/address, incomplete loading, Draft Stock Entry, moved/missing stock rejected | Not run |
| Historical compatibility | Old Loaded Plans are not retroactively committed; explicit E4A entry revalidates stock | Not run |
| Commitment isolation | Prepared tags reject ad-hoc delivery; waiting/active loose commitments reduce free ERP stock | Not run |
| Reservation concurrency | Two native transactions cannot double-reserve the same tagged or untagged lorry quantity | Not run |
| Retry/reload | Lost response, repeated confirm and refresh/reopen reuse one Session and allocation set | Not run |
| Batch/expiry | Mandatory Batch, batch identity, printed/tag expiry, serial restrictions and whole-number UOM respected | Not run |
| Container | Current complete membership only; no unrelated container contents delivered | Not run |
| Sales Order | Exact order item references, native sales UOM/conversion and rate/currency/project; stock quantity conserved | Not run |
| Remaining order balance | Another delivery or changed/closed order blocks excessive or stale fulfilment | Not run |
| Draft DN | Existing ERP fields captured; Plan shows Delivery Note Pending; no tag consumption or completion | Not run |
| Submit DN | Native ERP posts exact quantities; tags consumed once; loose stock has no tag ledger; Plan Delivered | Not run |
| Proof | Required evidence keeps Delivered until valid proof; then Plan Completed; No Proof policy closes on submission | Not run |
| Reset before ERP | Release all, cancel empty Session, reservations clear and same loaded Plan can restart | Not run |
| DN cancellation/amendment | Guarded native reversal; tagged ledger restored once; loose reservation restored; submitted proof blocks cancellation | Not run |
| Wrong-DN return | Controlled return for tagged/untagged rows conserves native stock, without phantom tag entries | Not run |
| Floor UI | Tablet camera, Tab/Enter suffixes, numbered choice paging, success/error/cancel focus, and full existing proof workflow | Not run |

## Acceptance boundary

E4A is accepted only after recording the deployed revision, document IDs, balances, proof and
negative/concurrent/retry evidence above. Whole-load known-customer fulfilment does not prove
partial/refused-delivery recovery, Open Route stops, pickup/direct delivery, route reconciliation
or go-live readiness. Package L1 and the wider logistics identity acceptance debt remain unchanged.
