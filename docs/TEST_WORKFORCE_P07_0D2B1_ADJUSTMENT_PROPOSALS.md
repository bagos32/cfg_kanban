# CFG Kanban Acceptance Test — P07-0D2B1 Adjustment Proposal Foundation

## Purpose and safety boundary

This package converts an approved Operation Progress correction request into a current-value,
immutable adjustment proposal. It does **not** apply that proposal. No Process Execution quantity,
Operation Progress row, Cycle, handoff, Job Card, Work Order, Stock Entry, or ERPNext document is
changed by this test.

## Prerequisites

1. Deploy and migrate the current CFG Kanban code.
2. Use an unfinished production Cycle with an unfinished Process Execution.
3. Configure a separate Supervisor/Mentor or Verifier authority that has **Correct Records**.
4. Complete `TEST_WORKFORCE_P07_0D2A_CORRECTION_REQUESTS.md` through **Approve Kanban
   Adjustment** for an **Operation Progress → Current Operation / Execution** request.
5. Keep the approved Correction Request name for audit comparison.

## A. Prepare a reject-only proposal

1. Open **CFG Job Architecture → Workforce Supervisor Centre**.
2. Find the approved request in **Controlled Correction Queue**.
3. Select **Prepare Adjustment**.
4. Enter `0` for **Good Quantity Delta** and a small valid value such as `+1` for **Reject Quantity
   Delta**.
5. Enter preparation notes explaining the verified count/evidence.
6. Select **Preview Adjustment**.

Expected result:

- the dialog shows Current, Delta, and Proposed Good/Reject/Processed quantities;
- the proposed Processed quantity does not exceed the execution target;
- the preview states that it is eligible but has no production effect;
- when a Job Card is linked, a warning explains that reject evidence does not edit ERPNext.

7. Confirm **Prepare Audited Proposal**.

Expected result:

- one `CFG Kanban Adjustment Proposal` is created as **Prepared**, revision 1;
- its source exact-action approval is verified as Consumed and bound to the same Correction Request,
  decision, and approving Employee;
- the supervisor queue displays its proposal number;
- the Process Execution quantities and all ERPNext documents remain unchanged;
- Event History contains **Kanban Adjustment Proposal Prepared**.

## B. Good-quantity ERP ownership guard

1. Use another approved Operation Progress request whose execution has an ERPNext Job Card.
2. Enter a non-zero **Good Quantity Delta** and preview.

Expected result: preview is **Blocked** and identifies the authoritative Job Card. No proposal is
created; correct the ERPNext record through its controlled ERP workflow instead.

## C. Reclassification without ERP-owned good quantity

Use an unfinished Process Execution with no Job Card. Enter Good `-2` and Reject `+2`.

Expected result: Processed Delta is zero and the proposal may be prepared if the resulting Good and
Reject quantities are non-negative and Good is not below already released quantity.

## D. Boundary failures

Verify that preview is blocked when any of these conditions applies:

- both deltas are zero;
- proposed Good, Reject, or Processed quantity is negative;
- proposed Processed quantity exceeds target;
- proposed Good quantity is below already released downstream quantity;
- the Cycle or Process Execution is Completed/Cancelled;
- the request is not Approved for Kanban adjustment;
- the request category/target is not Operation Progress / Process Execution.

## E. Cancel and replace a mistaken proposal

1. On a Prepared proposal, select **Cancel Proposal**.
2. Enter a mandatory cancellation reason.

Expected result:

- proposal becomes **Cancelled** and retains all original preview values;
- Event History records **Kanban Adjustment Proposal Cancelled**;
- production and ERPNext records remain unchanged;
- the queue permits a new revision to be prepared from the same approved Correction Request.

While a proposal remains Prepared, attempting to reroute its request to **Require ERP Correction**
must be blocked. Cancel the proposal first so there can never be two conflicting active paths.

## Pass criteria

Pass P07-0D2B1 only when previews use current values, unsafe conditions are blocked, prepared and
cancelled proposals are immutable/auditable, revisions remain linked, and every operational and
ERPNext value stays unchanged. Actual application is intentionally deferred to P07-0D2B2.
