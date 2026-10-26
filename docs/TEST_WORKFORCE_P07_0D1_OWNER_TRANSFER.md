# CFG Kanban Acceptance Test — P07-0D1 Controlled Ownership Transfer

## Purpose

Prove that an active production Cycle can move Operator-in-Charge accountability to an eligible
replacement while retaining the old assignment, requiring a separate exact-action supervisor pass,
and leaving every ERPNext manufacturing document unchanged.

## Test identities

Prepare three active Employees with CFG Kanban Operator Profiles:

- **Current Owner** — carries the Card's Required Owner Job Code.
- **Replacement Operator** — carries the same required Job Code and satisfies every immutable
  Operator-in-Charge Authority Role and competency requirement. If crew policy is configured, join
  this Employee to the execution Workstation crew as Active Direct Participation before the test.
- **Approving Supervisor** — is different from both people and has the exact scoped Authority Role,
  Job Code, competency, and presence required by the Cycle snapshot.

On the relevant reusable production Card:

1. Enable **Enforce Job Owner** and select its Required Owner Job Code.
2. Add a **Supervisor / Mentor** or **Verifier** role requirement.
3. Select an Authority Role with **Transfer Ownership** enabled.
4. Configure Job Code, competency, active presence, and separation settings as required by the real
   operation. Save this policy before creating the test Cycle because the Cycle snapshot is immutable.

## Positive scanner/touch test

1. Trigger, approve, and open the production Card normally.
2. Let Current Owner accept ownership and start work.
3. Confirm the Card banner names Current Owner and that one **Cycle Owner Assignment** is Active.
4. If configured crew policy applies, scan Replacement Operator into the Workstation crew as a direct
   worker. Keep the approving supervisor present in the role required by the Cycle snapshot.
5. In the production Card select **Transfer Owner**, or scan `CFG:CMD:TRANSFER_OWNER`.
6. Enter a specific reason, for example `Shift handover after cooking preparation`.
7. Scan Replacement Operator's normal Operator credential. Enter their PIN if configured.
8. Expected: the dialog names the replacement and requests the approving supervisor credential.
9. Scan Approving Supervisor's normal Operator credential. Enter their PIN if configured.
10. Expected: the dialog names both replacement and approver and asks for Confirm / Submit.
11. Scan `CFG:CMD:CONFIRM` or select **Transfer Ownership**.

Expected result:

- the active terminal remains logged in as the original requesting operator;
- the Card banner now names Replacement Operator as Operator-in-Charge;
- the original Owner Assignment is **Ended**, retains its original assigned time, and contains the
  transfer reason;
- a new **Active** Owner Assignment links to the previous assignment and the consumed Supervisor
  Action Approval;
- the Cycle points to the new owner and new active assignment;
- the Cycle timeline contains **Cycle Ownership Transferred** with old owner, new owner, reason, and
  approval reference;
- the Supervisor Action Approval is **Consumed**, action is `TRANSFER_CYCLE_OWNERSHIP`, and its Target
  Employee is Replacement Operator;
- the Workforce Supervisor Centre audit row shows that target;
- Work Order, Job Cards, Stock Entries, production quantities, and earlier Job Participation records
  remain unchanged.

## Negative tests

Run each with a fresh dialog:

1. Scan a replacement without the Required Owner Job Code. Expected: rejected before supervisor scan.
2. Scan a replacement missing an Operator-in-Charge scoped Authority Role or competency. Expected:
   rejected before supervisor scan.
3. With configured crew policy, scan a replacement who is not Active Direct Participation. Expected:
   rejected.
4. Scan the Current Owner as replacement. Expected: already-owner rejection.
5. Scan the requesting operator as approver. Expected: self-approval rejection.
6. Scan the replacement as approver. Expected: replacement self-approval rejection.
7. Scan an Employee without the exact scoped Transfer Ownership role. Expected: rejected.
8. Change the reason after approval and submit. Expected: wrong transfer-reason rejection.
9. Wait more than two minutes after approval and submit. Expected: expired approval rejection.
10. Reuse a consumed approval token. Expected: already-consumed rejection.
11. Attempt transfer after Cycle completion/cancellation. Expected: unavailable and no history change.
12. Scan Cancel at any stage. Expected: dialog closes and ownership remains unchanged.

## Audit sign-off

Record the Card, Cycle, Process Execution, previous/new Owner Assignments, Supervisor Action Approval,
current/new Employee, reason, and test result. Do not delete test history; cancellation and correction
must remain auditable.
