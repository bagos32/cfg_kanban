# CFG Kanban Acceptance Test — P05 Employee Job Participation Ledger

## 1. Purpose

Verify that CFG Kanban records who actually participates in each running Job Card execution without
duplicating ERPNext production quantity. Test direct labour, oversight, breaks, crew changes,
compliance holds, restoration, and final closure.

## 2. Required setup

Complete the P01–P04 setup in `docs/TEST_WORKFORCE_P04_AUTHORIZATION.md` first. Use:

- Company: your production Company
- Workstation: `P05 Mixing Station`
- Operation: `P05 Mixing`
- Main operator: one independently qualified Employee
- Supporting operator: one qualified or supervised Employee
- Overseer: one Employee classified as Senior / Overseer and Oversight Only
- Crew Requirement: minimum two direct workers and active supervision
- One open ERPNext Work Order and Job Card controlled by a Production Kanban Cycle

Record the starting ERPNext Job Card `Total Completed Qty`. Participation testing must not change it
unless the tester deliberately reports production progress.

## 3. Start the crew and execution

1. Log into the Production Operator Panel as the main operator.
2. Open the persistent Crew Session for the test Workstation.
3. Scan the supporting operator into the crew as Supporting Operator / Direct Participation.
4. Scan the overseer into the crew as Senior / Overseer / Oversight Only.
5. Activate the production or operation Card and start its Job Card.
6. Open **CFG Kanban → Execution Records → Employee Job Participation**.
7. Filter **Process Execution** to the active execution.

Expected result:

- three Active rows exist;
- main and supporting operators show Production Labour;
- the overseer shows Oversight;
- every row links to the same Process Execution and Job Card;
- each row links to its Crew Session and Crew Membership;
- no row contains or posts a production quantity.

## 4. Break and resume one direct worker

1. Put the supporting operator on break.
2. Refresh Employee Job Participation.
3. Resume the same operator and refresh again.

Expected result:

- the first supporting-operator segment is Closed at the break time;
- Duration Seconds and Duration Hours are calculated;
- resume creates a new Active segment instead of reopening the closed row;
- other eligible active members remain represented unless the break caused a compliance hold.

## 5. Verify the compliance-hold boundary

1. Put the overseer on break so the effective rule loses required supervision.
2. Open the Process Execution and confirm Crew Compliance is Hold and Status is Blocked.
3. Refresh Employee Job Participation.
4. Resume the overseer.

Expected result:

- all active participation segments close when the operation is blocked;
- no labour time continues accumulating while production is held;
- restoring compliant coverage returns the execution to its prior state;
- new Active segments open for the eligible active crew;
- the new segments link to the latest Crew Compliance Check.

## 6. Change the main operator

1. While the execution is In Progress, use Change Main Operator to select the active supporting
   operator.
2. Refresh Employee Job Participation.

Expected result:

- the affected old-role segments close;
- new segments open with the new Main Operator and Supporting Operator role snapshots;
- earlier rows retain the role that applied during their original interval.

## 7. Complete the operation

1. Report the required production progress normally.
2. Complete the Job Card or runtime-selected Kanban Cycle through the normal controlled action.
3. Refresh Employee Job Participation.

Expected result:

- no Active participation row remains for the completed execution;
- every row has a start time; every Closed row has an end time and non-negative duration;
- direct Production Labour and Oversight remain separately filterable;
- ERPNext Job Card good quantity equals the actual reported quantity only once, regardless of crew
  size.

## 8. Backward-compatible no-policy test

1. Use a separate Operation with no effective Crew Requirement and no active Crew Session.
2. Start it with one authenticated operator.
3. Open Employee Job Participation for that execution.

Expected result:

- one Active row exists for the authenticated operator;
- Participation Source is Authenticated Operator Fallback;
- Work Category is Direct Participation and Participation Kind is Production Labour;
- the Operation remains usable without configuring the P02–P04 crew stack.

## 9. Failure conditions

Fail P05 acceptance if any of the following occurs:

- the crew count multiplies Job Card or Work Order production quantity;
- Oversight is included as direct Production Labour;
- a break, leave, hold, completion, or cancellation leaves a stale Active interval;
- resume or compliance restoration rewrites a closed historical interval;
- a role/category change alters old evidence instead of creating a new segment;
- a configured non-compliant crew receives active participation time;
- a no-policy legacy Operation is blocked solely because no Crew Session exists.

## 10. Evidence to retain

- one Process Execution and Job Card reference;
- screenshots/list export of direct and oversight rows;
- one closed break segment and one resumed segment;
- one Crew Compliance Hold and restored segment set;
- final confirmation that no Active row remains;
- before/after ERPNext Job Card quantity proving the result was counted only once.
