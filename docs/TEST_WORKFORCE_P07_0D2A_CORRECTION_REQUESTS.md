# CFG Kanban Acceptance Test — P07-0D2A Controlled Correction Requests

## Purpose

Prove that an operator can report an incorrect production record, a separately authorized reviewer
can triage it, and neither action rewrites the original Kanban or ERPNext record. This package records
the request and decision only. Applying an approved Kanban adjustment belongs to P07-0D2B.

## Preconditions

1. Deploy, migrate, build, clear cache, and restart after pulling this package.
2. Use an active production Card with a Cycle and at least one Process Execution.
3. The requesting Employee has an active **CFG Kanban Operator Profile** and can open the Production
   Operator panel.
4. The Cycle's immutable Job Role Requirement snapshot contains a **Supervisor / Mentor** or
   **Verifier** row whose Authority Role has **Correct Records** enabled.
5. The reviewer has that exact scoped Authority Role, required Job Code and competency, and active
   Cycle Role Assignment when the snapshot requires active presence.
6. The requester and reviewer are different Employees.

## A. Operator request

1. Open **Kanban Operator**, scan the operator credential, and scan the active production Card.
2. Select **Report Correction** above Job Card Execution Lanes. A fixed scanner may instead scan
   `CFG:CMD:REQUEST_CORRECTION`.
3. Select **Operation Progress**. Confirm that **Affected Record** becomes
   **Current Operation / Execution**.
4. Enter a factual reason, for example `Good quantity was entered against the wrong observation`.
5. Enter the requested correction, for example `Supervisor to verify the source sheet and approve a
   minus-5 adjustment in the next correction package`.
6. Optionally enter an evidence reference. Select **Submit Correction Request**, or scan
   `CFG:CMD:CONFIRM`.

Expected:

- a new `KCR-...` Correction Request is created in **Open** state;
- the affected DocType/document and a JSON snapshot of its original values are stored;
- the requesting Employee, Operator Profile, Operator Session, terminal User, and request time are
  recorded;
- the original Process Execution, Operation Progress, Job Card, Work Order, Stock Entry, ownership,
  and participation records remain unchanged;
- rescanning the Card shows the latest request and status.

## B. Category and scope guards

Create or attempt each request:

| Category | Permitted affected record |
|---|---|
| Cycle Status | Current Cycle |
| Operation Progress | Current Operation / Execution |
| Ownership | Current Ownership |
| Participation | My Participation |
| Material / ERP Record | Work Order or Job Card |
| Other | Any listed current Cycle context |

Expected: a mismatched category/scope is rejected by the server. Ownership or participation is also
rejected when the corresponding current record does not exist.

## C. Supervisor triage

1. Open **CFG Job Architecture → Workforce Supervisor Centre** as Manufacturing Manager, HR Manager,
   or System Manager.
2. Find the request under **Controlled Correction Queue** and select **Review**.
3. Choose **Start Review**, enter review notes, scan the authorized reviewer's Employee QR, and select
   **Authorize Decision**.
4. Refresh and confirm the state is **Under Review**.
5. Review it again, choose **Approve Kanban Adjustment**, enter the verification notes, scan the same
   eligible reviewer, and authorize.

Expected:

- the request becomes **Approved** with resolution type **Kanban Adjustment Required**;
- each decision creates and consumes its own `CFG Kanban Supervisor Action Approval`;
- the approval is bound to the Correction Request, decision, Cycle, Process Execution, requester,
  original Operator Session, actual review terminal User, reviewer, and notes;
- approval does not apply any quantity or status adjustment in P07-0D2A.

## D. Negative authorization tests

Repeat a review using each of the following:

1. the requester's own credential;
2. an Employee without a scoped Authority Role whose **Correct Records** capability is enabled;
3. an Employee missing the required Job Code or competency;
4. an Employee missing required active presence.

Expected: each attempt is rejected and the Correction Request remains in its previous state.

## E. ERP correction-required path

1. Create a **Material / ERP Record** request against the Work Order or Job Card.
2. In the Supervisor Centre choose **Require ERP Correction** and authorize it.
3. Confirm the request becomes **ERP Correction Required**. CFG Kanban must not cancel, amend, or
   resubmit the ERPNext document.
4. Attempt **Resolve** without an ERP correction reference.

Expected: resolution is blocked.

5. Create or identify the correct authoritative ERPNext correction through the normal ERPNext
   workflow.
6. Review again, choose **Resolve**, link its DocType and document, enter resolution notes, scan the
   authorized reviewer, and authorize.

Expected: the request becomes **Resolved**, resolution type becomes **ERP Correction Confirmed**, and
the authoritative reference is retained without modifying that ERP document.

## F. Rejection and terminal-state protection

1. Create another request and authorize **Reject** with an evidence-based reason.
2. Confirm the request becomes **Rejected** and records resolver/time/notes.
3. Attempt to review the rejected request again or edit/delete it from Desk.

Expected: rejected and resolved requests are terminal; direct editing and deletion are blocked.

## Acceptance boundary

Pass P07-0D2A only when request creation, immutable snapshots, manager queue visibility,
decision-bound Correct Records authorization, ERP reference enforcement, terminal-state protection,
and unchanged original records are all demonstrated. Do not expect an approved quantity or status
adjustment until P07-0D2B is deployed.

