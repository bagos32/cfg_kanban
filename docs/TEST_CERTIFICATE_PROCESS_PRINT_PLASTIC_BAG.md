# Acceptance Test — Print Plastic Bag with a Process Certificate

## Purpose

Prove that `PLS_ABC` can remain one ERPNext Item while an exact tagged quantity changes from
`SANITISED` to `SANITISED + PRINTED`, without a BOM, Work Order, or Job Card.

This is a pre-production acceptance test. Record actual document names and results. Do not treat
implementation or unit-test success as live-site acceptance.

## Minimal sample data

| Record | Sample value |
|---|---|
| Company | `TEST Manufacturing` |
| Item | `PLS_ABC` |
| Stock UOM | `Nos` |
| Source/output Warehouse | `Printing Store - TEST` |
| Operation | `Print Plastic Bag` |
| Input tag | one active released tag holding `3000 Nos` |
| Card quantity | `1000 Nos` |
| Certificate Type A | approved `SANITISED-R001` |
| Certificate Type B | approved `PRINTED-R001` |
| Source Set | `SANITISED` |
| Result Set | `SANITISED + PRINTED` |

The source Handling Unit must match the Item, Company, Warehouse, UOM, available quantity, and
source Certificate Set. ERPNext must hold at least the tested quantity in the same Warehouse and
Batch, when Batch control is enabled.

## A. Configure the Master

1. Open **CFG Kanban Master** and create `PLS_ABC Print Certificate`.
2. Select Company and Item `PLS_ABC`.
3. Set **Control Type** to **Certificate Process**.
4. Leave **BOM** empty.
5. Set Replenishment Qty to `1000` and Number of Cards to `1`.
6. Set Source and Destination Warehouse to `Printing Store - TEST`.
7. Select Controlled Operation `Print Plastic Bag`.
8. Start with ERP Posting Mode **Create Draft for Review** and **Progress and ERP
   Consolidation = Consolidated Partial Progress**.
9. Enable Allow Partial Quantity, Reuse Source Tag for Full Quantity, Capture Printed Expiry,
   and Capture First / Last Printed Serial as required.
10. Add an Input Certificate Requirement: Operation `Print Plastic Bag`, Certificate
    `SANITISED-R001`, Gate **Before Operation Start**, minimum revision `1`, unexpired enabled.
11. Add Output rules: **Retain** `SANITISED-R001` and **Issue** `PRINTED-R001`, applied to
    Processed Tagged Quantity.
12. Save. Expected: no BOM validation and no Work Order configuration appears.

## B. Create and print the Card and commands

1. Create one Physical Batch Card linked to the Master.
2. Print the Card QR normally.
3. In Production Operator Panel > Scanner Help > Print Command Labels, select:
   - `CFG:CMD:ACTIVATE`
   - `CFG:CMD:START_CERTIFICATE_PROCESS`
   - `CFG:CMD:COMPLETE_CERTIFICATE_PROCESS`
   - `CFG:CMD:REPORT_CERTIFICATE_PROGRESS`
   - `CFG:CMD:CLOSE_CERTIFICATE_PROCESS`
   - `CFG:CMD:SUBMIT_CERTIFICATE_PROCESS`
   - `CFG:CMD:CANCEL_CERTIFICATE_PROCESS`
   - `CFG:CMD:CERTIFICATE_OUTPUT_TAG`
   - Batch/expiry/serial field-arm commands that the test uses
   - Material/Good/Reject quantity, Confirm, and Cancel.

## C. Release the run

1. Log in to the Production Operator Panel by operator QR.
2. Scan the Card and scan Activate.
3. If Automation is Approval, approve the Signal in Production Supervisor Action Center, then
   refresh or wait for the panel's live update.
4. Expected: one Cycle and one `CFG Process Certificate Run` in **Ready** state; there is no Work Order or Job Card.

## D. Consolidated partial-progress test

1. Scan Start Certificate Process.
2. Scan `CFG:QTY:MATERIAL:1000` and then scan the source Stock Tag.
3. Scan Confirm.
4. Expected: Run is **In Progress** and exactly `1000 Nos` is reserved on the source tag.
5. Scan Report Certificate Progress.
6. Scan Good quantity `400` and Reject quantity `0`.
7. Scan Certificate Output Tag, then scan either one unused preprinted main Stock Tag or an active
   compatible output tag already holding the exact result Certificate Set.
8. When Batch control is enabled, optionally scan Certificate Batch and the output Batch. When it
   is disabled, verify Batch input is absent/rejected.
9. Scan expiry and first/last printed serial using their field-arm commands when configured.
10. Scan Confirm. Expected: no Repack yet. Operational Inventory Balance shows `400 Nos` and the
    output tag as **Pending ERP Consolidation**, but Total/Available/ERP Actual stock is unchanged.
11. Repeat Report Certificate Progress with `600 Nos`, the same output tag, and compatible
    Batch/expiry values. Expected pending total: `1000 Nos`; still no ERPNext Repack.
12. Scan Close Consolidated Certificate Process and Confirm.
13. Expected: exactly one Draft ERPNext Repack exists; source tag still shows its old quantity/set,
    the output tag is not yet activated/increased, and no PRINTED certificate has been issued.
14. Review Repack rows: outgoing `1000 PLS_ABC` from the old Set; incoming `1000 PLS_ABC` to the
    result Set. Total stock quantity is conserved.
15. Scan Submit Certificate Repack.
16. Expected after ERP submission:
    - source tag quantity reduced from `3000` to `2000`;
    - output tag activated with `1000` and `SANITISED + PRINTED`;
    - one active PRINTED certificate is linked to the output tag;
    - Cycle is Completed and Card returns to Available;
    - native Stock Ledger shows the submitted Repack and exact Certificate Set dimensions.
    - both progress rows show **ERP Posted**, and Operational Inventory Balance no longer shows a
      separate pending quantity for this Run.

### D2. Early partial Card closure

1. Start a new cycle with selected quantity `1000 Nos` and ensure **Allow Partial Quantity** is on.
2. Report one partial good quantity of `400 Nos` against one controlled output tag.
3. Close the consolidated Certificate Process.
4. Expected: one Repack for `400 Nos`, not `1000`; the remaining `600 Nos` stays on the source tag
   after ERP submission and can be processed in a later Card cycle.
5. Repeat with Allow Partial Quantity off. Expected: early closure is rejected.

## E. Full tag reuse test

Use a source tag whose available/current quantity exactly equals the selected good quantity.
Complete with zero reject and no output tag. Expected: the submitted Repack changes the same tag's
Certificate Set; it does not create a second Handling Unit.

## F. Required negative tests

- Wrong Item, Warehouse, Company, UOM, inactive/Hold tag: start is rejected.
- Missing, expired, or too-old SANITISED certificate: gate is rejected.
- Selected quantity above tagged or ERPNext balance: rejected.
- Partial result without unused output tag: rejected.
- Active output tag with a different Item, UOM, Company, Warehouse, Batch, Certificate Set, Hold
  state, or reservation: rejected.
- Revoked/child output tag: rejected.
- Batch-controlled Item with source tag lacking Batch: rejected.
- Non-Batch Item with Batch input: rejected.
- Cancel before ERP Draft: reservation released and Card reusable.
- Cancel after Repack Draft exists: routine cancel blocked; controlled supervisor recovery required.

## Acceptance record

| Field | Result |
|---|---|
| Deployed Git revision | |
| Site | |
| Tester/date | |
| Consolidated partial progress | Pass / Fail |
| Pending inventory visibility without double count | Pass / Fail |
| Early partial Card closure policy | Pass / Fail |
| Compatible existing-tag accumulation | Pass / Fail |
| Full tag reuse | Pass / Fail |
| Batch-enabled behavior | Pass / Fail / Not tested |
| Batch-disabled behavior | Pass / Fail / Not tested |
| Scanner-only kiosk run | Pass / Fail |
| Native Stock Ledger evidence | |
| Accepted exceptions/deferred risks | |


## Printed metadata and finished Batch expiry acceptance — live scenarios NOT RUN

1. Certify a non-Batch Item onto a new tag, capturing printed expiry and serial boundaries; submit
   its Repack. Scan it into dispatch. Check Certificate Set, effective/printed expiry, source serial
   boundaries and exact Run/Repack references in the frozen snapshot. Repeat direct/GIT transfers,
   intercompany receipt, split child and reusable-container paths; no metadata may be invented.
2. Capture gapped partial-progress serial episodes: show each recorded range separately. Exact ERP
   Serial Number membership remains separate. Reject stale evidence and do not rewrite old snapshots.
3. FEFO compares captured printed dates of eligible No-Batch tags; expired printed stock is blocked.
   An earlier native/tag date wins. In one Process Card cycle, switch to another printed date:
   reject before use, suggest matching eligible tags or controlled close/new-cycle guidance. Confirm
   that a new cycle resets the group and parallel confirmations cannot mix dates in one cycle.
4. Finish production using one printed date. Opt in at Manufacture Receipt, scan a new finished
   Batch ID and Confirm. Verify native Batch expiry, Stock Entry output Batch, output tag/FEFO,
   ERP Command evidence and scanner-only touch/error/Cancel behavior. Existing same-date Batch
   is allowed; different/blank-date existing Batch and unbatched finished Item are rejected.
5. Opt out: retain ordinary native Batch/shelf-life behavior. Multiple consumed printed dates,
   changed/revoked posting evidence, unused draws, missing sources and an expired date must not
   authorize automatic expiry copying. Check native direct Draft submission rechecks the selection.

Record deployed SHA, actual source/child tags, Run/progress/certificate/Repack/Manifest/Stock Entry/
finished Batch IDs, before/after expiry and stock balances, tester and accepted exceptions. Offline
checks do not establish database concurrency, real scanner focus or live ERP stock acceptance.


Offline validation, 2026-11-12: 346 Python checks passed, including 13 printing-provenance/
logistics/FEFO checks and 21 manufacture-expiry/cohort checks. All 53 JavaScript checks passed,
including 6 dispatch printing-metadata checks and 9 receipt scanner checks. Changed Python
syntax, Operator/Logistics JavaScript syntax and whitespace checks passed. Dependency doubles
and source contracts were used. Live stock, native Batch valuation/posting, scanner hardware,
transaction rollback, performance and concurrent confirmation/revocation are NOT RUN. No
commit, push, migration, deployment or live-site mutation was performed for this work.
