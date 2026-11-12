# Material Run FEFO and Operational Inventory acceptance

Implementation is local until explicitly deployed. Offline tests do not certify live ERPNext,
database concurrency, Stock Ledger behavior or scanner-only kiosk acceptance.

## Owner-run offline checks

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest cfg_kanban.tests.test_material_rotation_behavior cfg_kanban.tests.test_material_run_inventory_balance cfg_kanban.tests.test_operation_material_run_contract -v
node cfg_kanban/tests/test_material_rotation_override_ui.cjs
git diff --check
```

## Isolated site scenarios (not yet run)

Record deployed SHA, exact site, installed ERPNext/Frappe versions, tester and date before testing.
Use the identified isolated test environment; do not run these against an assumed disposable site.
The owner performs deployment and migration manually.

1. Configure a Source Tag Quantity material rule and two same-Warehouse raw-material tags with
   earlier/later expiry. Preview and start using the later tag must be blocked. Use the earlier
   tag first. Equal dates use packed/receipt time, then internal identity; undated stock is last.
2. Reject expired tag dates and expired native Batch dates, including conflicting tag/Batch dates.
   Reject disabled/missing/wrong-Item Batch, and missing Batch for a Batch-controlled Item.
   Verify today's expiry is accepted and an overnight carry-forward/progress becomes blocked
   after expiry. An approval must never bypass these checks.
3. Confirm another Company/Warehouse/UOM/certificate state, Hold/inactive tags, in-transit tags,
   active manifests, exhausted Material Draw reservations and invalid container fills do not
   incorrectly block the first eligible source. Verify actual valid production-container scans.
4. Have an authorized unrestricted supervisor scan the approval command, exact numbered context,
   reason and Confirm. Retain the approval document/event. Reject ordinary and scoped operators.
   Verify the same approval works on a later micro-run, another operation/station lane and another
   Card of the SAME Work Order. Verify a DIFFERENT Work Order remains blocked.
5. Revoke the exact approval with a reason. Future bypasses are blocked; past draws remain audited.
   Duplicate approval/revocation requests do not create additional authority. After replacement,
   a stale revocation must not revoke the new approval. Closed/stopped/cancelled/completed orders
   cannot authorize new draws. Race starts against revocation and verify locking behavior.
6. Start with tag 1000; draw 100; post progress using 60. Summary AND Tag Detail must show unused
   reserved 40, pending consumption 60, operational remaining 940 and operational available 900.
   ERP Actual and posted tag total remain 1000. Multiple draws must not multiply tag totals.
7. Adopt used 60 into the configured ERP Draft. The trace reservation must not cause a second
   deduction: operational available remains 900. Discard/cancel the draft and verify the same
   outstanding reservation remains visible. Submit: tag/ERP reduce once and Bound draws no
   longer contribute pending consumption. Cancel ERP through supported recovery and reconcile
   restored draw status, tag/ERP and report. Repeat both configured settlement timings.
8. Cancel an unused run: its reservation disappears without deleting audit. Test filters in both
   report modes and mixed UOMs. Pending certificate output must not duplicate material deductions.
9. Complete all routine and exception paths scanner-only in kiosk/full screen. Include numbered
   Work Order choice, reason, Confirm, Cancel, error and message dismissal; verify focus returns.

## Acceptance record

| Evidence | Result |
|---|---|
| Deployed SHA / site / ERPNext and Frappe versions | Not recorded |
| Tester / date | Not recorded |
| FEFO and expiry rejection | Not run |
| Full Work Order approval scope and revocation | Not run |
| Concurrent workers / approval races / rollback | Not run |
| Operational report and both settlement timings | Not run |
| Native stock / audit document names | Not recorded |
| Scanner-only kiosk acceptance | Not run |
| Accepted exceptions / deferred risks | Not recorded |
