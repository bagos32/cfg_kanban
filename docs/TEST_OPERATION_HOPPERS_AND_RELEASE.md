# Operation hopper and unused-reservation acceptance

Status: implementation prepared; live-site acceptance not performed. Record deployed Git SHA,
site, tester, date and actual evidence before marking any live case passed.

## Boundaries

- One Production Master / Work Order, Rinse then Pack, two physical hoppers.
- Ordinary Digital Quantity Handoff with Operation Hopper Mode=None adds no holding-place scan.
- Opt-in Fill Hopper/Consume Hopper tracks intermediate WIP in finished-Item stock UOM.
- Intermediate fills do not create an ERP Manufacture entry or a second raw-material input.
- Existing executions retain their snapshots. Old HOPPER_3 output is not automatically reconstructed; supervised recovery never re-reports production.
- Only component reservations are returned at operation-cycle closure. Physical rinsed WIP is not
  silently returned to raw stock or cleared by ERP cancellation. Exceptional physical-WIP recovery
  requires a separately reviewed reconciliation; no automatic reallocation to another WO is provided.

## Offline checks

`test_operation_hoppers` exercises actual hopper/release functions with in-memory Frappe doubles.
Inventory tests execute report/FEFO SQL against SQLite. Scanner tests execute the actual dialog and
scanner functions with UI doubles. These do not establish MariaDB isolation, transaction rollback,
native ERP stock correctness or scanner-only kiosk acceptance.

Verified offline on 2026-11-16 against the working tree based on `a869514`, including these
uncommitted changes: **230 Python checks passed** across hopper/release, actual material use,
inventory, receipt, runtime closure/selection, pre-use certificates, logistics identity, FEFO,
printed expiry and incremental WIP modules. **25 scanner-dialog checks passed**: 10 Material Run
pre-use, 9 receipt and 6 FEFO override checks. JavaScript syntax, Python syntax, DocType metadata,
changed-line whitespace and new-document links passed. Protected user documents were unchanged.
No live site, MariaDB concurrency, ERP ledger or real kiosk acceptance was performed.

## Required isolated-site cases

1. **Raw reservation release:** draw 3 at a 1:1 BOM ratio; report 2 with a permitted partial operation
   allocation. Before operation closure: Used=2, Reserved=1. Close that operation allocation:
   Drawn=3, Used=2, Remaining=0, Released=1. ERP/tag stock is unchanged; operational availability
   excludes only the used 2. Settle ERP: stock decreases by 2 exactly once. Reopening the card does
   not inherit the previous execution's reservation.
2. **FIFO carry:** within one execution draw 3/report 2, then draw 2/report 3. The older run's cached
   carry-forward becomes zero. Consumption totals 5, not 6; original draw lineage remains intact.
3. **Old completed-cycle repair:** preserve a reviewed backup. Deploy/migrate a fixture with a
   completed cycle holding an entirely unused draw. The patch releases it with one audit event;
   used/settled quantities and ERP stock do not change. Repeat the helper: no duplicate release.
4. **Normal digital path:** Hopper Mode=None. Partial source handoff makes destination eligible
   under its existing start rule; no hopper/source-holding-place scan is added.
5. **Rinse to Hopper_1:** enable the paired modes/new execution. Scan boundary, empty Hopper_1,
   raw quantity/tag, Confirm; Start Operation. Before progress it is Filling and cannot be consumed.
   Report Good=5: Loaded/Available=5 in finished UOM; raw ERP stock is not posted yet.
6. **Packing:** scan boundary, Hopper_1, certified bag quantity/tag, Confirm. Show loaded, reserved
   and available quantities. Start and report 2: Loaded=3, unused run reservation returned; actual
   use record links Pack progress to the Rinse fill/progress. Raw material is not consumed again.
7. **Alternating hoppers:** while Hopper_1 is reserved/part-used, fill empty Hopper_2. Refilling
   Hopper_1 is blocked until empty. Consume the remainder, then reuse its QR for a new fill; history
   remains separate and Packing always selects an explicit hopper.
8. **Rejections:** empty hopper, another WO/operation/Company/warehouse, held/in-transit hopper,
   ERP-stock-filled hopper, insufficient quantity, concurrent second reservation and stale closed
   execution. Each must reject without committed Draw/Run/fill/use side effects. Exercise two tabs
   and two Work Orders against the same hopper using MariaDB transactions.
9. **Before-use certificates:** uncertified, expired or revoked bag evidence blocks the Material Run
   and progress. A failed bag gate must not reserve the hopper. Existing FEFO and process-cycle
   printed-expiry checks remain enforced.
10. **Cancel/retry:** cancel prepared source fill -> hopper reusable; cancel prepared packing run ->
    loaded quantity unchanged, reservation returned. Lost response + identical retry creates one
    run/fill/reservation/use. Changed Hopper with same token rejects. Close Operator Complete with
    an unused next run: its component/hopper reservations release with audit.
11. **Final receipt:** finish 10 Rinse/Pack units across two fills, confirm both empty. Prepare one
    receipt with actual raw/bag traces; submit once. Check native ledgers, tag balances, batch/expiry,
    no hopper input stock row, completed WO and recycled cards. Remaining physical hopper WIP must
    block final closure. Test ERP cancellation/reposting without erasing physical hopper history.
12. **Scanner-only kiosk:** fixed wedge scanner, numbered selection, quantity labels, both Hopper
    QRs, Confirm/Cancel, errors and restored focus, across repeated micro-runs. Repeat by touch.

Package L1 transfer acceptance remains separate and partial; see TEST_PACKAGE_L1_TRANSFER_KANBAN.md.

## Supervisor recovery extension

Offline: test_material_run_recovery exercises unused-only release, preserved usage, source-progress
linkage, retry identity, closed-WO release, unauthorized requests and rejection of prior Packing,
partial physical balance or unreleased output. Live acceptance remains pending.

On an isolated site, verify both Recover Material Run paths with click/touch and fixed scanner:
select the exact run, action, physical Hopper/quantity when required, reason, Confirm/Cancel.
Verify audit records, source-run totals and hopper quantities; no new production progress, native
stock entry or ledger change may be created. Repeat lost-response/same-token and changed-token
payload tests, multi-tab locking, occupied hopper, different Company/warehouse, old closed Cycle,
and a role without Override. Partial/mixed historical contents must reject rather than infer use.

Recovery working-tree verification, 2026-11-16: 242 Python checks and 29 scanner-dialog checks passed offline. Live recovery and MariaDB concurrency remain unverified.
