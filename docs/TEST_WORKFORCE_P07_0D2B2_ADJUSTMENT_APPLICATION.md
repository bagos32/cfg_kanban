# CFG Kanban Acceptance Test — P07-0D2B2 Adjustment Application

## Purpose and authority boundary

This test proves that a current Prepared proposal can add an immutable signed correction to CFG
Kanban production evidence. It must not edit earlier progress rows or change ERPNext Job Cards, Work
Orders, Stock Entries, batches, stock, attendance, payroll, ownership, or participation.

## Prerequisites

1. Deploy and migrate the current CFG Kanban code.
2. Complete `TEST_WORKFORCE_P07_0D2B1_ADJUSTMENT_PROPOSALS.md` and retain one Prepared proposal.
3. Use an unfinished Cycle and Process Execution.
4. Keep the original requester, proposal preparer, and application reviewer as three different
   Employees.
5. The application reviewer must match an immutable Supervisor/Verifier requirement whose scoped
   Authority Role enables **Correct Records**.
6. Record the Process Execution Good, Reject, Processed, Target, and Released quantities.
7. Record any linked ERPNext Job Card totals and relevant ERPNext stock balances before testing.

## A. Apply a reject-only correction on a Job Card execution

1. Open **CFG Job Architecture → Workforce Supervisor Centre**.
2. Find the approved request carrying the Prepared proposal.
3. Confirm the proposal has Good delta `0` and a safe Reject delta such as `+1`.
4. Select **Apply Adjustment**.
5. Read the boundary notice and verify it explicitly says ERPNext and payroll remain unchanged.
6. Enter final factual **Application Notes**.
7. Scan a different eligible reviewer credential and enter its PIN when configured.
8. Select **Authorize and Apply**, then confirm.

Expected result:

- one consumed `APPLY_KANBAN_ADJUSTMENT` exact-action approval links the exact Proposal;
- the Proposal becomes **Applied**;
- one new immutable Operation Progress row has Source **Correction**, Good `0`, Reject `+1`, and
  Processed `+1`;
- Process Execution Reject and Processed increase by one while Good and Released remain unchanged;
- Operation Summary reflects the corrected totals;
- the Correction Request becomes **Resolved** with resolution **Kanban Adjustment Applied**;
- the Proposal links its application Approval, correction Progress row, and application Event;
- the linked Job Card, Work Order, stock, and payroll-related participation records are unchanged.

## B. Verify separation of duty

Prepare separate test proposals and attempt application using:

1. the original requester's credential; and
2. the proposal preparer's credential.

Expected result: both attempts are rejected before any quantity changes. No Correction progress row
is created and the Proposal remains Prepared.

## C. Verify stale-proposal protection

1. Prepare a new eligible proposal.
2. Before applying it, report legitimate new progress against the same Process Execution.
3. Attempt **Apply Adjustment**.

Expected result: application is blocked because the execution changed after preparation. The old
proposal remains Prepared and no signed correction is inserted. Cancel it with a reason, prepare a
new revision from current values, and apply only that new revision.

## D. Verify ERPNext Good-quantity authority

1. Use an execution linked to an ERPNext Job Card.
2. Confirm P07-0D2B1 refuses any proposal with non-zero Good delta.
3. Confirm P07-0D2B2 therefore cannot apply a Kanban-only Good correction.
4. Route the Correction Request through **Require ERP Correction** only after cancelling any
   Prepared proposal.

Expected result: the authoritative Job Card quantity can be corrected only through the proper
ERPNext workflow and linked back to the Correction Request. CFG Kanban does not invent an ERP result.

## E. Kanban-only Good reclassification without a Job Card

1. Use an unfinished Process Execution that has no linked Job Card and no unsafe released quantity.
2. Prepare Good `-2`, Reject `+2` so Processed delta is zero.
3. Apply with a separate eligible reviewer.

Expected result: a signed Correction row is added; Good decreases by two, Reject increases by two,
Processed remains unchanged, and no ERPNext document is created or edited.

## F. Idempotency and terminal-state checks

1. Repeat the same browser submission or network request using the same event token.
2. Attempt a different application after the Proposal is already Applied.
3. Attempt application after the Cycle or Process Execution becomes Completed or Cancelled.

Expected result:

- the same event token returns the already-applied result without a second progress row;
- an Applied proposal cannot be applied again with a different event token;
- terminal or changed contexts are blocked without mutation.

## Pass criteria

P07-0D2B2 passes only when the signed correction is append-only, current-value guarded,
second-person authorized, idempotent, fully linked across Proposal/Request/Progress/Approval/Event,
and visible in Kanban totals while every ERPNext, stock, payroll, ownership, and participation value
remains unchanged.
