# E5B2 — Trip Handover and per-item recovery acceptance

Development prepared 24 November 2026 above `d466852`. Native acceptance **Not run**.
Offline tests are implementation evidence, not proof of live ERP stock posting or tablet behavior.

## Scope

- Full-page Trip Handover from Driver Route, normal office Delivery Trip, Operator and Logistics.
- Per-Plan immutable per-source quantities: several approved same-Company route destinations
  plus selected stock staying on the lorry until old Plan settlement.
- Existing Manifest scan/confirmation, reservation, native ERP inputs/posting/feedback, certificates,
  expiry and D3 count remain authoritative. Legacy E5B1 keeps its original whole-remainder path.
- Old returns remain separate non-stock QC custody. Office closure requires their physical receipt;
  QC/accounting may finish later. Company-owned refusals receive no duplicate receipt/credit.
- Whole-tag/held-source constraints, all-destination conservation, native Company/record permissions,
  retries, whole-unused cancellation, cancellation/evidence-reuse guards and scanner/camera controls.

## Automated evidence

Run the new suites together with existing E5A/E5B1, cancellation/refusal, Driver Route, office Trip,
native quantity/schema and scanner regressions. The actual mixed functions and existing native
document builders/feedback run with explicit DB/Frappe/permission doubles. Local browser fixtures
use demo RPC/camera responses and isolated profiles; no real site or printer is connected.

- `test_dispatch_recovery_mixed.py`: conservation; tagged/loose multi-destination feedback; retained
  stock; permission/company/whole-UOM/stale-source rejections; holds; safe legacy coexistence;
  repeat/reopen/cancel; exact group lookup; cross-Plan evidence reuse and settled cancellation.
- `test_trip_handover.py`: assignment/native record/Company/Item/Batch privacy; standalone supervisor
  scope; separate old-return custody; physical-receipt close gate including hidden Cases.
- `test_trip_handover_ui.cjs`: scanner-driven choices, explicit approval, source identity, quantity
  limits, durable unknown payload, first rejection/replay rules, Web Locks/cross-tab storage protection, lifecycle/actor/privacy and entry points.
- `test_handover_count_ui.cjs`: actual D3 input adapters with the shared scanner controller,
  exact warehouse, loose table, correction fields, stable opening event and actor-change guards.
- `run_trip_handover_browser.mjs`: actual DOM controls, Enter/Tab focus, separate destination lookup,
  frozen instructions, camera lifecycle and unknown-request reopening/retry in real browser storage.

Final local results:

- **441 Python tests passed** across the new suites, E5A/E5B1, cancelled/refused stock,
  office/driver actions, direct/old returns, identity, native schema and installation contracts.
- **143 Node test results passed** across 11 UI suites, including legacy standalone suites
  that report their detailed scanner checks inside the suite process.
- The actual full-page fixture passed **18 checks in Chrome 158 and 18 in Firefox 153**:
  DOM controls, Enter/Tab, scanner focus, camera lifecycle, exact destination selection,
  frozen approval, real localStorage/Web Locks and original-payload retry after reopening.
- Python/JSON/JavaScript syntax checks passed for the changed files. Existing file formatting
  and unrelated user files are preserved. No server/companion/stock operations were performed.

Frappe/DB/ERP feedback use dependency doubles. Browser RPC and camera input are simulated.
These results do not establish actual migration/permissions/CSRF/MariaDB concurrency, ERPNext
posting, warehouse physical counts, QC custody, kiosk or tablet camera acceptance.

## Required site evidence

| Case | Expected result | Result |
| --- | --- | --- |
| Migrate/build current revision | New Review JSON and Manifest identity fields sync; existing records remain valid | Not run |
| Normal office/driver entry | Driver/assistant sees own Trip; deciding Supervisor retains native scope and reconciliation responsibility | Not run |
| Mixed quantities | Whole tag retained; loose stock split between warehouse and another lorry; totals exact by UOM | Not run |
| Several prepared Plans | Each preserves its own allocations; one fresh global D3 count may certify all completed movements if still current | Not run |
| Physical scans and certificates | Every group scans/counts exact sources; certificates, printed expiry, serial identity and container membership persist | Not run |
| Native Draft/submission | Route submission policy and mandatory ERP fields work; source balance changes only on native submission | Not run |
| QC/refusal custody | Held source cannot become next-trip stock or be split; destination retains hold; no duplicate stock receipt/credit; owned-stock release/disposal waits for frozen Review settlement | Not run |
| Old customer returns | Case quantities shown separately; QC physical receipt permits office closure while inspection/accounting continue | Not run |
| Hidden old-return Case | Cannot close transport custody merely because current user cannot see its unreceived Case | Not run |
| Pending/part-failed group | Other groups/history stay frozen; cannot close/resume/replan or certify unfinished ERP work | Not run |
| Whole unused cancellation | All groups cancelled once; reservations/held custody restored; corrected approval retains old audit | Not run |
| Unknown RPC / browser reopening | Original payload/token retained; duplicate retry creates no second Manifest/Stock Entry | Not run |
| Concurrency | Simultaneous supervisors, native submission, stock reservation and cancellation serialize safely on real MariaDB/Redis | Not run |
| Fresh D3 count | Reject variance, older count, foreign lorry, moved/used tag and stock changed after count | Not run |
| Evidence guards | No cross-Plan reuse or cancellation/detachment of settled evidence; native permission denials remain enforced | Not run |
| Floor-only scanner path | Open, choose, quantities, reason, approve, each movement, D3 and final Review using scanner only in kiosk mode | Not run |
| Tablet path | Touch controls, camera denial/cancel/duplicate/late callback and operator changes restore safe focus | Not run |
| Office closure | All linked Plans Reconciled/Cancelled plus old-return physical receipt; original itinerary/loading remains audit history | Not run |

Record site, deployed Git revision, operator/native user, ERP documents, quantity ledger and evidence
for each accepted case. This phase does not close Package L1 or other unrecorded logistics acceptance.
