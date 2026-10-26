# P07-0B2 Acceptance Test — Exact-action Supervisor Pass

## Purpose

This test verifies the first controlled action gate built on the P07-0A immutable role snapshot and
P07-0B1 runtime assignments. It covers only a non-owner closing a runtime-selected production Cycle.
The pass must never log out, replace, or permanently elevate the active operator.

## Preconditions

- P07-0A and P07-0B1 acceptance has passed.
- A production Card has **Enforce Job Owner** enabled and an **Operator-in-Charge** requirement.
- The same Card has a **Supervisor / Mentor** or **Verifier** requirement whose Authority Role has
  **Close on Behalf** enabled.
- The supervisor's Operator Profile has that exact scoped Authority Role and any required Job Code
  and competency.
- If the requirement enables **Require Active Presence**, the supervisor is active in the applicable
  workstation crew and appears under **Job Role Coverage**.
- An owner has accepted the Cycle, and another authorized operator is logged in to the Production
  Operator panel.
- The runtime-selected operation has reached its target and all ordinary ERP/Job Card/WIP close
  prerequisites are satisfied.

## Test 1 — Non-owner sees the controlled close action

1. Open the production Card as the non-owner operator.
2. Find the completed runtime execution lane.
3. Confirm the action says **Supervisor Pass & Close**, not the ordinary green close button.
4. Open it and confirm the dialog shows the assigned operator-in-charge and an approval reason.

Expected: the system clearly explains that the supervisor scan authorizes only this close attempt.

## Test 2 — Negative credential and scope checks

1. Scan an ordinary Employee credential that has no matching Close-on-Behalf Authority Role.
2. Confirm closure does not occur and the active operator remains unchanged.
3. Test a supervisor whose assignment is scoped to another Company, Operation, or Workstation.
4. If Active Presence is required, place the correct supervisor On Break and scan again.
5. If Separate Approver is required, try the requester or Cycle owner credential.

Expected: every invalid scan is rejected before a token is issued; no Cycle state changes.

## Test 3 — Approve and close without switching operator

1. Restore the eligible supervisor to active crew presence where required.
2. Open **Supervisor Pass & Close** and confirm the approval reason.
3. Scan the eligible supervisor's existing Operator QR. Enter their PIN first if their profile
   requires one.
4. Confirm the dialog shows **Supervisor pass approved**, approver name, and expiry.
5. Confirm the page still displays the original active operator.
6. Scan `CFG:CMD:CONFIRM`.

Expected: the Cycle closes normally, the reusable Card releases according to existing rules, and the
operator session was never replaced.

## Test 4 — Audit and one-time use

1. Open **CFG Job Architecture → Supervisor Action Approvals**.
2. Find the new record and confirm:
   - Action Code is `CLOSE_CYCLE_ON_BEHALF`.
   - Status is **Consumed**.
   - Cycle, Process Execution, requester, approver, session, terminal, matched requirement, Authority
     Role, reason, approval time, expiry, and consumption time are recorded.
3. Confirm the raw token is not visible or stored; only the hidden hash exists.
4. Attempt to reuse the captured approval token through an API test, if available.

Expected: reuse is rejected as already Consumed and history remains read-only.

## Test 5 — Expiry and exact-context binding

1. Issue another pass but do not confirm for more than two minutes.
2. Attempt closure and confirm the pass is rejected as expired.
3. Issue a fresh pass for another eligible Cycle or execution and attempt to apply it here through an
   API test.

Expected: expired and cross-context passes cannot mutate either Cycle.

## Test 6 — Backward compatibility

Test each case below:

- the assigned Cycle owner performs the close;
- owner enforcement is disabled;
- no Supervisor/Verifier role has an Authority Role with **Close on Behalf**.

Expected: the existing **Close Kanban Cycle** flow remains available and no supervisor pass is
requested.

## Pass criteria

- Enforcement is opt-in and limited to the exact configured action.
- The approving Employee satisfies the exact snapshot requirement and current presence evidence.
- Credential scanning does not switch the operator session.
- Approval is short-lived, one-time, hash-stored, and context-bound.
- Every issued and consumed pass is auditable.
- Existing owner and unconfigured Card workflows remain unchanged.
