# Acceptance Test — Process Certificates in Work Order Production

## Purpose

Prove that a normal Production Kanban with BOM, Work Order, Job Cards, and reusable Process Cards
can gate an Operation from certified material and place the resulting certificate state on exact
tagged finished output. ERPNext remains authoritative for stock, Batch, Job Card, Work Order, and
Manufacture submission.

This is a pre-production test. Record actual document names and the deployed Git revision. Code or
unit-test success is not live-site acceptance. The pre-use/Ready-operation scenarios added below
are **NOT RUN** on a live site; record their actual results after deployment.

## Minimal sample data

| Record | Sample |
|---|---|
| Company | `TEST Manufacturing` |
| Raw Item | `PLS_ABC` |
| Finished Item | `PACKED_ABC` |
| Operation 1 | `Print Plastic Bag` |
| Operation 2 | `Pack Product` |
| Input certificate | approved `SANITISED-R001` |
| Operation 1 output certificate | approved `PRINTED-R001` |
| Operation 2 output certificate | approved `PACKED-R001` |
| Raw source tag | active/released `PLS_ABC`, correct Warehouse/UOM/Batch, Set `SANITISED` |
| Output identities | unused main Stock Tags or empty Production Output Containers |

## A. Configure the Production Master

1. Open the normal Production **CFG Kanban Master**.
2. Keep **Control Type = Production** and select the submitted BOM with both Operations.
3. Ensure the Material Flow Rule for `PLS_ABC` belongs to `Print Plastic Bag`, uses **Source Tag
   Quantity** Material Run tracking, and has the correct scan Warehouse and quantity per output.
4. Add a Certificate Requirement for `Print Plastic Bag`:
   - Required Certificate: `SANITISED-R001`
   - Gate Stage: **Before Progress**
   - Group: `INPUT`
   - Logic: **All Required**
   - minimum revision `1`; unexpired enabled.
5. Add Output Rule `PRINTED-R001`, Action **Issue**, Apply To **Finished Output**, Operation
   `Print Plastic Bag`.
6. Add a requirement on `Pack Product` for `PRINTED-R001` at **Before Operation Start**.
7. Add Output Rule `PACKED-R001`, Action **Issue**, Apply To **Finished Output**, Operation
   `Pack Product`.
8. Save. Expected: Processed Tagged Quantity is rejected for Production output rules.

Each issued Certificate Type must apply to the finished Item (or one of its parent Item Groups),
not only to the raw material Item. A retained raw-material certificate must have active, unexpired
issued evidence on its source tag; a certificate issued by an earlier Operation is carried through
the internal result Set until it is bound to final output.

## B. Release the Work Order and Process Card

1. Activate the main Production Card and approve/release its Signal.
2. Confirm ERPNext creates the expected Work Order and Job Cards.
3. If a reusable Process/Station Card is used, scan it and select the same eligible Job Card.
4. Expected: the execution shows Certificate Gate **Pending**. The Process Card and main Card refer
   to the same ERP Job Card but keep their normal separate Kanban Cycles.

## C. Scanner-only source verification before physical work

1. Leave the operation **Ready**. Attempt Start Operation without input certificate evidence.
   Expected: certificate rejection before the Job Card starts; the source-preparation path remains available.
2. Scan Start Material Run, the exact Material Quantity, then the certified `PLS_ABC` source tag.
   Scan Confirm. Expected: both input gate stages are checked, the Material Run opens, but the
   operation remains Ready and no ERP consumption or Job Card start is recorded.
3. Scan Start Operation, then begin physical work. Report Good/Reject and Confirm afterwards.
   Expected: certificates are checked again; progress retains its result Set and the scans are reused
   by the main Work Order Card/native settlement.
4. Repeat the first-operation raw requirement using **Before Operation Start** instead of
   **Before Progress**. The same scan-first flow must work without a circular start dependency.
5. Negative: missing/expired/revoked/insufficient-revision certificates must reject Material Run
   confirmation before physical use. Check no new run/draw reservations remain after transaction
   rollback, no start event, and the scanner dialog stays available for correction or Cancel.
6. Complete one certified run, then use an uncertified source in the next run. The earlier Used
   draw or a source reserved by another execution lane must not satisfy this run. Allowed positive
   carry-forward is rechecked for current validity; zero or cancelled balances never authorize work.
7. Revoke/expire a certificate between preparation and Start, and between Start and Report Progress.
   Recheck must block. Cancel the unconsumed run and reprepare with an eligible source as appropriate.
8. Enable automatic Job Card start. Allocate a card needing a raw certificate. Expected: allocation
   remains Ready with a deferral event, so sources can be prepared; it must not roll back allocation
   or start the Job Card without the required proof. Prior-operation-only gates can still auto-start
   when their prerequisites and the existing material-readiness checks pass.
9. Test multiple Ready/started operations: the scanner must require an explicit numbered choice,
   retain the chosen operation after physical evidence, and restore focus on Confirm/error/Cancel.
   Physical Item/Warehouse/UOM/Batch/Company/FEFO validation still applies at source confirmation.

## D. Downstream operation gate

1. Open/start `Pack Product` only after the prior Job Card progress is available.
2. Expected: its Before Operation Start gate reads the prior operation result Set and passes without
   inventing a physical intermediate stock tag.
3. Complete its normal progress/Job Card procedure.
4. Expected: the final execution Result Certificate Set includes the configured final state.

## E. Manufacture output and ERP authority

1. Prepare the final Manufacture receipt through the Production Operator Panel.
2. Open **Scan Material Tags**.
3. Stage the complete finished quantity across one or more unused output tags or Production Output
   Containers. Partial tag staging is rejected for certified output.
4. Before submission, inspect the Draft Stock Entry output row. Expected: native field **Process
   Certificate Set** contains the final immutable Set.
5. Submit through **Submit Material Entry**.
6. Expected after ERPNext submission:
   - Stock Entry and Stock Ledger are submitted with the final Process Certificate Set dimension;
   - each confirmed output Handling Unit carries the same Set;
   - issued `PRINTED` and `PACKED` certificate instances reference the exact output tag quantity,
     Work Order, Job Card/Operation, Cycle, and submitted Stock Entry;
   - the Work Order/Cycle closure continues through the normal production rules.

## F. Required failure and recovery checks

- Missing source evidence blocks Material Run/Operation Start and is rechecked at progress for both input gate stages.
- Missing prior-operation certificate blocks the downstream Operation start.
- Incomplete output-tag/container staging blocks Manufacture submission.
- A simple Production Master with no certificate rules behaves exactly as before.
- Scanner Cancel returns focus in every Material Run, progress, and Material Trace dialog.
- Direct ERPNext submission still cannot bypass a configured Kanban certificate gate on a
  controlled Stock Entry.
- Parallel final lanes with different Certificate Sets are rejected instead of being silently
  merged into one finished-output state.
- Cancelling the submitted Manufacture entry revokes the certificates issued to its output tags
  while retaining the certificate and event audit records.
- Cancellation/recovery preserves Process Execution, Progress, certificate-set, Stock Entry, and
  event audit; do not delete transactional evidence.

## Acceptance record

| Field | Result |
|---|---|
| Deployed Git revision | |
| Site | |
| Tester/date | |
| Main Production Card | |
| Reusable Process/Station Card | Pass / Fail / Not used |
| Before Progress raw-tag gate | Pass / Fail |
| Prior-operation start gate | Pass / Fail |
| Scanner-only kiosk flow | Pass / Fail |
| Manufacture output tag binding | Pass / Fail |
| Native Stock Ledger dimension evidence | |
| Negative tests | Pass / Fail |
| Recovery/audit | Pass / Fail |
| Accepted exceptions/deferred risks | |


## Local pre-use regression evidence (2026-11-12)

- 284 Python checks passed across pre-use certificate behavior, Material Runs, quantity/yield,
  BOM mapping, runtime selection/closure, cancellation, schema, logistics identity and certificate
  regression suites. The new pre-use module contains 21 checks, including direct API gate rejection.
- 38 JavaScript checks passed: 7 scan-before-start checks, 11 material quantity/approval checks,
  6 FEFO checks and 14 certificate retry checks. Operator-panel syntax and whitespace checks passed.
- All results are offline with dependency doubles/source contracts. Database transaction rollback,
  concurrent revocation/source changes, native ERP posting and real scanner/kiosk focus are NOT RUN.
  No commit, deployment or live-site test was performed while preparing this change.
