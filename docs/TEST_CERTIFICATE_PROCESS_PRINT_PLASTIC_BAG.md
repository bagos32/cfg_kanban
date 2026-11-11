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
8. Start with ERP Posting Mode **Create Draft for Review**.
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

## D. Partial process test

1. Scan Start Certificate Process.
2. Scan `CFG:QTY:MATERIAL:1000` and then scan the source Stock Tag.
3. Scan Confirm.
4. Expected: Run is **In Progress** and exactly `1000 Nos` is reserved on the source tag.
5. Scan Complete Certificate Process.
6. Scan Good quantity `1000` and Reject quantity `0`.
7. Scan Certificate Output Tag, then scan one unused preprinted main Stock Tag.
8. When Batch control is enabled, optionally scan Certificate Batch and the output Batch. When it
   is disabled, verify Batch input is absent/rejected.
9. Scan expiry and first/last printed serial using their field-arm commands when configured.
10. Scan Confirm.
11. Expected: one Draft ERPNext Repack exists; source tag still shows its old quantity/set, the
    output tag is not yet activated, and no PRINTED certificate has been issued.
12. Review Repack rows: outgoing `1000 PLS_ABC` from the old Set; incoming `1000 PLS_ABC` to the
    result Set. Total stock quantity is conserved.
13. Scan Submit Certificate Repack.
14. Expected after ERP submission:
    - source tag quantity reduced from `3000` to `2000`;
    - output tag activated with `1000` and `SANITISED + PRINTED`;
    - one active PRINTED certificate is linked to the output tag;
    - Cycle is Completed and Card returns to Available;
    - native Stock Ledger shows the submitted Repack and exact Certificate Set dimensions.

## E. Full tag reuse test

Use a source tag whose available/current quantity exactly equals the selected good quantity.
Complete with zero reject and no output tag. Expected: the submitted Repack changes the same tag's
Certificate Set; it does not create a second Handling Unit.

## F. Required negative tests

- Wrong Item, Warehouse, Company, UOM, inactive/Hold tag: start is rejected.
- Missing, expired, or too-old SANITISED certificate: gate is rejected.
- Selected quantity above tagged or ERPNext balance: rejected.
- Partial result without unused output tag: rejected.
- Already active/revoked/child output tag: rejected.
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
| Partial process | Pass / Fail |
| Full tag reuse | Pass / Fail |
| Batch-enabled behavior | Pass / Fail / Not tested |
| Batch-disabled behavior | Pass / Fail / Not tested |
| Scanner-only kiosk run | Pass / Fail |
| Native Stock Ledger evidence | |
| Accepted exceptions/deferred risks | |
