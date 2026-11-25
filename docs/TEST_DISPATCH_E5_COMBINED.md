# E5 — Combined recovery and follow-on acceptance

Prepared 25 November 2026 above `3c9cc99`, including the pending E5B3 development and subsequent
recovery hardening. **Native/site/physical acceptance: Not run.** The owner explicitly deferred
live E5B2/E5B3 testing until the complete section could be tested together. That decision remains
in force; offline tests and the native test harness below do not replace the recorded site result.

## Current scope and corrections

- E5A review, overnight continuation/stock-stays, fresh D3 counts and settlement.
- E5B1 whole-remainder and E5B2 mixed per-source recovery through existing native movements.
- E5B3 linked follow-on Trips, confirmed existing lorry stock, driving team and whole-Case return
  custody handover through the existing Delivery Note/proof/QC engines.
- A confirmed unused child can be recovered before departure after its Plans settle. Office may
  cancel it after custody is received, or explicitly review/confirm a further takeover that closes
  it and passes pending return custody onward atomically. No invented route start is required.
- Source/void receipts and stock availability use current locking reads after waits. Dispatch
  reservations lock their Bin before the tag, re-read current Plan lines and commitments, reject
  changed-quantity retries, enforce finite/whole-UOM/precision limits, and require POST.
- Current certificate ancestry, serial assignments, Batch expiry, Repack status and printed
  boundaries contribute to the physical-source version check; movement does not issue certificates.
- Actual carry-in Allocations validate against their recorded receipt without a fabricated
  Manifest. Ordinary edits cannot rewrite their controlled reservation/loading/release audit.
- Follow-on creation has a savepoint after the source lock. A nested failure rolls back the child,
  source closure, custody, allocation/quantity audit and events; missing savepoints after a
  deadlock trigger full request rollback. The action never commits a nested transaction itself.
- Browser owner/session changes discard late replies. Expired sessions clear prior private data;
  a storage failure after a recorded response retains the original request for Read Back.

## Offline evidence

Final local verification, 25 November 2026:

- **778 Python tests run: 764 passed, 14 skipped.** The skips include four supplied opt-in
  native transaction tests and ten existing native/site-dependent checks. The changed numeric and Desk timestamp
  boundary guards were rechecked afterward with the 60 relevant recovery/reservation tests.
- **202 Node test results passed** across 11 UI suites, including 21 follow-on controller tests.
- **18 checks passed in Chrome 158 and 18 in Firefox 153** on the mounted form fixture.
  The initial Chrome attempt exposed a fixture timing assumption; replacing the fixed delay
  with an explicit async-completion wait made the final Chrome run pass. No product failure
  was inferred from that timing-only failure.
- Changed Python/JSON/JavaScript syntax checks and Git whitespace checks passed.
- No server, native transaction, ERP posting, physical stock/custody, printer or companion-app
  tests were executed. No Git commit, push, pull or deployment was performed.

 Actual function tests use
explicit Frappe/record/MVCC/stock-service doubles. Failure-injection rollback uses an in-memory
transaction model. Browser tests use a DOM shim and simulated RPC/camera with real browser
storage/Web Locks. None establishes native MariaDB rollback/concurrency, server permissions,
HTTP method/CSRF behavior, stock posting, physical custody or tablet/kiosk acceptance.

## One complete physical scenario

Use an isolated test company/site with the normal profiles, permissions and test-site restore
plan. Record the actual deployed SHA and document IDs. Use future-dated valid Batch/certificate
identities and stock-UOM quantities. Example quantities below are test instructions, not results.

1. Office: prepare a Trip with C1's SO for tagged A **6 Nos** plus loose B **4 Nos**, C2's SO for
   tagged A **4 Nos**, and optional visits C3/C4 sharing extra B **2 Nos** plus C **2 Nos**.
   Use separate whole A tags of 6 and 4; confirm both tagged and loose loading into Lorry A using
   E3's native Stock Entries and the required approved route. Assign a driver and assistant. Use Flexible Order for this scenario, or obtain the existing
   Supervisor sequence approval before visiting C3 ahead of C2.
2. Driver: Start Route; complete C1's A6/B4 DN and required proof. At C3 sell B1 through the shared
   route pool and complete proof. Leave C2 and C4 unvisited. Collect a complete old-return Case
   of 2 Nos from C1, including its original custody label. These old returns remain non-stock
   custody awaiting QC; they do not increase the lorry's available ERP balance.
3. Confirm the native remaining lorry stock: A4/B1/C2. In Trip Handover begin every relevant Plan
   review. Transfer the whole A4 tag to Lorry B. For the shared pool send loose B1 to Lorry B and
   C2 back to the warehouse, exercising two destinations within one mixed recovery decision.
4. Physically confirm and post each existing recovery movement. Verify exact quantity, Batch,
   certificate/expiry/serial identity and warehouse. Close a **fresh** balanced D3 count after
   all movements and settle every source Plan. C1's DN/proof and C3's sale remain unchanged.
5. Original Trip → Plan Follow-on Trip: select C2's remaining SO A4, optional C4, receiving Lorry
   B and its physical Warehouse Operations Card, relief driver/assistant and dates/reason. Confirm
   the exact A4 tag and loose B1 as shared stock. Select and physically confirm the complete old
   Return Case after checking all its lines/bundles. Review and Confirm once.
6. Verify one Draft child and original source closure. The new normal allocations are confirmed
   on Lorry B without another loading Stock Entry. Original DNs/proof and collection facts remain
   intact; the same Return Case now has Lorry B/child transport custody and still awaits QC.
7. Mark the child Planned and obtain its normal route approval. Start Route, deliver C2 A4 and
   optionally sell B1 to C4 using the existing DN/proof flow. Check source balances and SO links.
8. QC Monitor: find the old Case by Original Trip and Current Custody Trip. Confirm physical QC
   receipt; inspection/accounting can continue afterward. Finish E5/D3 settlement and office
   closure. Confirm that unreceived current custody blocks closure before this receipt.

Run the unused-child branch from a fresh fixture: do not Start Route on the child. Settle its
Plans with the existing stock-stays/count workflow. Check both office cancellation after physical
QC receipt and reviewed takeover of all still-unreceived Cases to another child. SO balances become
available once the cancelled/closed child's commitments settle; original lineage remains intact.

## Required evidence matrix

| Check | Expected result | Recorded result / IDs |
| --- | --- | --- |
| Migration/build and ordinary old records | Readonly fields/indexes sync; regular E2/E3, normal Trip, warehouse delivery and pickup remain valid | Not run |
| Whole/mixed recovery | Exact source conservation, several routes, whole tags, loose quantities, native feedback and fresh D3 count | Not run |
| Same lorry / replacement lorry | Actual stock confirmed once; replacement movement precedes takeover; no duplicate loading or delivery | Not run |
| Multi-day / overnight | Two-to-three-day Trip remains active; overnight Continue retains commitments; stock-stays settlement releases them | Not run |
| Unstarted child cancellation/recovery | Settled confirmed child can be cancelled or handed onward; no fake departure, duplicate stock or orphan SO commitment | Not run |
| Old-return custody / hidden Case | Whole original Cases and QC state retained; hidden unreceived custody still blocks abandonment | Not run |
| Return-only takeover / chain | No fake customer DN/Plan; original and middle Trips preserve custody history across successive handovers | Not run |
| Two tabs / two workers reserve same tag | One active commitment; second request re-reads current stock and cannot take a prepared load | Not run |
| Concurrent loose reservation / changed Plan line | Current reserved/prepared/ERP balances and current line budget prevent over-allocation after a lock wait | Not run |
| Concurrent Create versus Create/void | One recorded child or a void; late Create cannot miss a committed void; changed payload/actor rejected | Not run |
| Metadata changed during wait | Batch expiry, serial/certificate ancestry, Repack cancellation or printed-boundary changes require new review | Not run |
| Partial failure / deadlock | Native rollback restores source, child, Cases, sheets, allocations, quantities and events; original request remains reconcilable | Not run |
| Permissions | Native Company/record and operator role/capability gates reject unauthorized reads/mutations without leaks or audit side effects | Not run |
| Numeric / identity rejection | NaN/infinity/negative/bool, fractional whole UOM, excess precision, wrong Batch/warehouse/company, split tag and duplicate source rejected | Not run |
| HTTP contracts | Reservation mutations accept the standard POST/CSRF flow and reject GET without changing data | Not run |
| Allocation Desk validation | Legitimate carry-in validates without Manifest; quantity/source/state/receipt edits cannot rewrite audit | Not run |
| Browser unknown response / expiry / operator switch | Original payload survives; late replies stay private; Read Back/void safe; recorded stock is never silently retried as a new action | Not run |
| Kiosk/tablet | Whole scanner-only setup/action path, Enter/Tab/camera, numbered choices, safe cancel and focus verified on the actual device | Not run |

For worker races use independent connections on the isolated fixture. Record lock wait/deadlock
logs, both request identities/outcomes and native ledgers. The offline current-read tests do not
establish this result. Restore/recreate the fixture between mutually exclusive scenarios.

## Opt-in native transaction suite — supplied, not executed

Module: `cfg_kanban.tests.test_e5_native_transactions`. Four native tests exercise actual Frappe
success/replay, Allocation validation, rollback after source/custody closure, rollback after stock
exchange/final audit, and void-before-late-Create. It does **not** test two-worker concurrency,
physical warehouse posting, real camera or the complete driver/QC flow above.

Prerequisites:

- A separately authorized isolated clone/test site with a restore point, configured with
  `cfg_e5_isolated_acceptance: 1`. Do not set this flag on production.
- The fully prepared source Trip with settled Plans, an eligible receiving-lorry load and at
  least one collected old-return Case. It must have no existing follow-on child.
- A private JSON fixture outside the repository containing `source_trip`, `company`,
  `terminal_user`, and `payload` copied from the reviewed follow-on setup. The payload is the
  same exact warehouse/card/driver/assistants/dates/orders/visits/stock/returns/reason request.
  The harness refreshes context/source hashes; quantities and identities remain explicit.
- `CFG_E5_FIXTURE` points to that file; `CFG_E5_OPERATOR_SESSION` is an active authorized
  Supervisor session belonging to `terminal_user`; `CFG_E5_NATIVE_ACCEPTANCE=1` opts in. Enter
  the session privately in the terminal environment; do not put it in Git, the fixture, logs or chat.

On that isolated site only, run Bench's normal `run-tests` command with this module. The tests
refuse unmarked sites, block unexpected internal commits, and roll back their outer test
transaction. They are skipped during offline verification. Review custom site hooks separately;
rollback does not reverse external side effects introduced by other apps.

## Acceptance record

- Deployed Git SHA: Not recorded
- Site / Company / restore point: Not recorded
- Tester / date / devices: Not recorded
- E5B2 + E5B3 + hardening outcome: Not run
- Explicit exceptions / deferred cases / owner decision: Not recorded

The separate Package L1 acceptance record remains open; this document does not close it.
