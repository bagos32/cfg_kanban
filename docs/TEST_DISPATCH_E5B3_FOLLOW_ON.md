# E5B3 — Follow-on Trip acceptance

Prepared 25 November 2026 above `3c9cc99`. **Native acceptance: Not run.**
The owner explicitly approved development without a live E5B2 checkpoint on 25 November 2026;
run E5B2 and E5B3 together when the section is complete. This records a deferral, not a pass.

Scope: normal office Trip follow-on editor; exact SO/visit selection; tagged/loose stock already
on the receiving lorry; existing E2 reservations/loaded commitments and DN/proof services; lead
and assistant assignment; same original Return Cases with current custody and pending QC;
permission gates, frozen request receipts, readback/void, scanner/camera and historical lineage.

## Offline evidence

`test_trip_continuation.py` executes real orchestration, stock preview, Trip/Plan validators and
Dispatch builders with explicit Frappe/DB/stock/reservation-service doubles. It does not simulate
native transaction rollback, cross-worker MariaDB concurrency or actual posting. Existing native
service regression suites remain separate evidence. `test_trip_continuation_ui.cjs` exercises the
real editor controller with RPC/storage/locks doubles. `run_trip_continuation_browser.mjs` mounts
the normal-form section in a DOM shim with real browser localStorage/Web Locks and simulated
RPC/camera, checking Enter/Tab, touch, numbered fields, exact source preview, original-payload
reopening, readback, focus, operator changes and late camera callbacks.

E5B3-only checkpoint, 25 November 2026, before the subsequent hardening increment:

- 688 Python tests run: **678 passed, 10 skipped** (native/site prerequisites unavailable).
  This includes **28 E5B3 tests**, existing E5B1/E5B2, native delivery/proof orchestration,
  office/driver/team/route/refusal/return/QC/printing, schema and installation regressions.
- **196 Node test results passed** across 11 UI suites. Some legacy suite processes report
  their detailed scanner checks internally; this count is the formal runner result count.
- The actual mounted form fixture passed **16 checks in Chrome 158 and 16 in Firefox 153**.
  An initial Firefox launcher exited before testing; its diagnostic retry and final run passed.
- Python, JSON and changed JavaScript syntax checks passed. No Git mutation, deployment,
  companion-app modification, native ERP posting or physical custody/printing test was performed.

These checks use explicit dependency doubles/DOM shims and simulated RPC/camera. They cannot
establish MariaDB rollback, concurrency, native permission/migration, physical stock/custody,
real QR/tablet/kiosk behavior or ERPNext document posting.

## Required combined site evidence

Record deployed Git SHA, date, tester, Trip/Plan/SO/allocation/SE/Case/DN/proof IDs, quantities by
UOM and screenshots/logs. Do not copy demo fixture numbers into the acceptance record.

| Case | Expected evidence | Result |
| --- | --- | --- |
| Migrate/build | New readonly lineage/custody fields and unique request/source keys; old records remain valid | Not run |
| Office/terminal permissions | Native Trip Create/Write and source Read/Company scopes plus authorized reconciliation Supervisor; other users rejected before mutation | Not run |
| Same lorry | Original E5B2 stock-stays settlement, fresh balanced D3; exact whole tag and loose quantities confirmed without any new load SE | Not run |
| Replacement lorry | E5B2 transfer submitted before confirmation; selected physical target card, exact received tags/Batch/expiry/certificates/UOM and current ERP balance | Not run |
| Partial SO | Original 10, posted 4: only up to 6 still required/current unassigned; other Trip claims reduce availability; no duplicate delivered quantity | Not run |
| Refusal/cancellation | No auto-selection of completed/refused stops; cancelled stops excluded; company-owned QC holds remain blocked until normal release | Not run |
| Shared optional sales | Selected unfinished visits share one controlled Open Route pool; extra tagged/loose stock optional; unassigned stock follows existing route-sales controls | Not run |
| Driver/assistants | Active lead and valid assistant profiles; receiving team sees only authorized Trip; normal Start Route and DN/POD work | Not run |
| Original sheet | Settled original sheets close/cancel through their existing engine without editing completed stops or approving the child's route | Not run |
| Required new sheet approval | No departure until normal configured route approval; order/customer QR/proof policies remain in force | Not run |
| Carried old returns | Selected complete Cases physically confirmed, same origin/lines/QC/accounting; separate current custody and complete history; no stock receipt/credit | Not run |
| Mixed return disposition | QC-receive some Cases, carry all others; original Trip can end; child cannot end until its current returns are physically received or transferred again | Not run |
| Return-only | No fake stop, DN, Stock Entry or Plan; Start Route with confirmed custody; office completion after QC receipt | Not run |
| Follow-on chain | Second takeover works from latest child; all prior Trips preserve lineage/incoming Case history; source can never create a second child | Not run |
| Return visibility/prints | Driver carried-Case list without original stop; QC original/current Trip filters; original Note/label reprint; native privacy preserved | Not run |
| Mutation/rollback | Altered tag certificate/expiry/quantity, wrong lorry, stale SO/profile/template/return, duplicate whole tag and aggregate loose over-allocation rejected; native failure rolls back child, closure, custody, reservations and events together | Not run |
| Lost Create response | Original nonce/payload persists through reload; Read Back finds one child; retry does not re-reserve or recollect; other actor/different payload rejected | Not run |
| Concurrent Create/void | Two workers/tabs, identical and changed requests, late Create after void: one recorded outcome; no duplicate child/stock/custody; database rollback verified | Not run |
| Scanner-only kiosk/tablet | Full setup/physical identity/quantity/review/Create/readback/void/cancel with scanner and camera; all focus restored without a mouse | Not run |

Package L1 remains its separate recorded acceptance gate; this development does not close it.


## Subsequent recovery hardening

The same pending change set now includes current-read reservation/metadata guards, exact carry-in
Allocation validation, atomic failure rollback, pre-departure child recovery and late browser-reply
privacy. Use [the combined E5 procedure](TEST_DISPATCH_E5_COMBINED.md) for the latest execution
record and one complete physical scenario. The native transaction suite is supplied but unrun.
