# P07-0A Acceptance Test — Scoped Multi-role Authority Foundation

## Purpose

This test confirms that CFG Kanban can describe a real job without incorrectly treating an
Employee's title as their runtime authority. P07-0A is configuration and immutable Cycle snapshot
only. It must not change current operator authorization or block existing Cards.

## Sample scenario

- **Junior Supervisor:** performs and leads a production job while under supervision.
- **Production Manager:** remains actively responsible for supervision and later protected approval.
- The Junior Supervisor is not renamed as an Operator in ERPNext Employee.
- The Manager does not become the Cycle owner merely because they supervise the job.

## Prerequisites

1. Deploy the revision and run `bench --site site1.local migrate`.
2. Have one Production Kanban Master and an inactive/test Production Card with no active Cycle.
3. Have two active Employees and Operator Profiles: one Junior Supervisor and one Production
   Manager.
4. Keep their current legacy Kanban Role and permission checkboxes unchanged during this test.

## A. Configure reusable identities

1. Open **CFG Job Architecture → Job Codes**.
2. Create active Job Code `LINE-SUPERVISION` with title **Line Supervision**.
3. Open **CFG Job Architecture → Authority Roles**.
4. Create `SUPERVISED-LINE-LEAD` and enable **Perform Work** and **Lead Crew**.
5. Create `QUALIFIED-SUPERVISOR` and enable **Supervise Trainees**, **Verify Work**, **Approve
   Progress**, and **Close on Behalf**.

Expected:

- A role with no capability cannot be saved.
- Both valid roles appear in the Authority Roles list.
- These roles do not create ERPNext User roles or permissions.

## B. Assign several scoped roles to Employees

1. Open the Junior Supervisor's **CFG Kanban Operator Profile**.
2. Add Job Code `LINE-SUPERVISION`.
3. Under **Scoped Authority Assignments**, add `SUPERVISED-LINE-LEAD` and limit it to the test
   Company and, if desired, the test Operation and Workstation.
4. Open the Manager's Operator Profile.
5. Add `QUALIFIED-SUPERVISOR` with the same Company/Operation/Workstation scope.
6. Save both profiles.

Expected:

- Several non-duplicate Authority Assignment rows can coexist on one profile.
- An Authority Role restricted to another Company is rejected.
- Effective Until earlier than Effective From is rejected.
- An exact duplicate scoped assignment is rejected.
- Existing QR login and legacy permissions continue to work.

## C. Declare the Card's job-role requirements

1. Open the inactive test Production Card.
2. Under **Multi-role Job Requirements**, add:

| Assignment Type | Job Code | Authority Role | Count | Policy |
|---|---|---|---:|---|
| Operator-in-Charge | `LINE-SUPERVISION` | `SUPERVISED-LINE-LEAD` | 1 | Allow Supervised Trainee; May Own Cycle |
| Supervisor / Mentor | — | `QUALIFIED-SUPERVISOR` | 1 | Active Presence; Separate Approver Required |

3. If testing competency detail, select a Skill and its Minimum Competency together. Never enter
   only one of the pair.
4. Save the Card.

Expected:

- A requirement without Job Code and without Authority Role is rejected.
- Required Count below 1 is rejected.
- **Require Independent Authorization** and **Allow Supervised Trainee** cannot both be selected.
- Only one row can be marked **May Own Cycle**.
- Non-production permanent identity Cards cannot store these production job requirements.

## D. Confirm immutable Cycle snapshot

1. Trigger and approve the Production Card normally so a new Cycle is created.
2. Open the new **CFG Kanban Cycle**.
3. Expand **Cycle Job Role Requirement Snapshot**.

Expected:

- Both Card requirement rows are present with the exact Job Code, Authority Role, count,
  competency, supervision, presence, ownership, and separation policy.
- The snapshot table is read-only.
- Attempting to change the Card requirements while this Cycle is active is rejected.
- Completing or cancelling the Cycle permits future Card policy changes, but never rewrites this
  historical Cycle's snapshot.

## E. Backward-compatibility gate

1. Scan and operate one existing Card that has no Required Job Roles.
2. Confirm Start, Progress, Complete, Service, Logistics, and supervisor actions behave as before.
3. Log in both sample Employees and confirm their current legacy Kanban Role/permissions still
   determine runtime access.

Expected:

- P07-0A does not add a runtime block.
- No supervisor credential prompt is shown yet.
- The new requirements are not treated as enforced until P07-0B is deployed and accepted.

## Pass criteria

P07-0A passes when configuration, validation, Card edit protection, Cycle snapshot immutability, and
legacy runtime compatibility all match this document. Do not begin P07-0B enforcement if any
existing Card, scanner session, Service panel, or Logistics panel is unexpectedly blocked.
