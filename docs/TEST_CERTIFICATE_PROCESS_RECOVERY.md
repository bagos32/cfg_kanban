# Acceptance Test — Controlled Certificate Process Recovery

## Purpose

Verify that a no-BOM Certificate Process with an ERPNext Repack cannot be casually cancelled, and
that a Manufacturing Manager can reverse it without deleting submitted ERP, certificate, tag, Cycle
or Event history.

## Roles and sample records

- Operator: an active Kanban Operator allowed to Start and Complete the controlled operation.
- Recovery manager: Manufacturing Manager or System Manager.
- Master: one active **Certificate Process** Master using **Create Draft for Review**.
- Card: one available physical Card for that Master.
- Source: one Released Handling Unit with sufficient quantity and any required input certificates.

## A. Draft Repack recovery

1. Scan the Card, release its Signal, and start the Certificate Process.
2. Complete the process so that an ERPNext **Draft Repack** is created, but do not submit it.
3. Attempt normal **Cancel Certificate Process**.
4. Confirm it is refused because a Repack transaction exists.
5. Open the linked **CFG Process Certificate Run**.
6. Select **Recovery → Request Controlled Recovery**. Enter an exact reason and confirm.
7. Open the created **CFG Process Certificate Recovery**.
8. Confirm status is **Ready to Finalize**, the Run and Card are frozen, and the original Draft
   Repack snapshot is visible.
9. Select **Recovery → Finalize and Release Card**. Record the Draft name, source-tag quantity,
   location, and verifier in Final Reconciliation Evidence.

Expected:

- Draft Repack is discarded, but its name and JSON snapshot remain in the Recovery record.
- the source reservation is released exactly once;
- Run, Cycle and Signal become Cancelled;
- Card becomes Available with no active Cycle;
- source tag quantity and original certificate state remain unchanged;
- Recovery becomes Completed and Events identify the manager and reason.

## B. Submitted Repack recovery

1. Run a second Certificate Process and submit its Repack so the Run completes.
2. Do not move, reserve, split, consume, or reuse the resulting output tag.
3. Immediately open the completed Run and request Controlled Recovery.
4. In the Recovery record, confirm status **Pending ERP Reversal**.
5. Select **ERP Reversal → Cancel ERPNext Repack** and enter reversal evidence.
6. Confirm ERPNext changes the Repack to Cancelled and issued output certificates become Revoked.
7. Select **Recovery → Finalize and Release Card** and enter the physical verification evidence.

Expected:

- ERPNext cancellation remains in its native cancelled document and Stock Ledger;
- a reused source tag regains its previous Batch, Warehouse and Certificate Set; or a separate
  output tag is merged back into the source and marked Void;
- certificate instances stay in history as Revoked;
- original Run stays in history as Cancelled;
- Cycle and Signal are Cancelled, and Card is Available;
- the immutable Recovery links every step.

## C. Required negative tests

- Move, reserve, consume, split, or reuse the completed output tag before requesting recovery:
  request/finalization must stop and identify later tag activity.
- Start a later Cycle with the same reusable Card: recovery must stop until that later Cycle is
  resolved.
- Leave the submitted Repack active: finalization must refuse release.
- Enter no reason or no final reconciliation evidence: the action must be refused.
- Use Manufacturing User only: controlled recovery actions must be unavailable/refused.
- Retry request, ERP cancellation, refresh, and finalization: no duplicate Recovery, ledger reversal,
  certificate revocation, or Card release may be created.

## Acceptance record

| Field | Result |
|---|---|
| Deployed Git revision | |
| Site | |
| Tester/date | |
| Draft Repack recovery | Pass / Fail |
| Submitted Repack recovery | Pass / Fail |
| Reused-source-tag restoration | Pass / Fail / Not used |
| Separate-output-tag merge and void | Pass / Fail / Not used |
| Later-activity rejection | Pass / Fail |
| Role rejection | Pass / Fail |
| ERPNext / Kanban audit evidence | Pass / Fail |
