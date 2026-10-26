# P07-0B1 Acceptance Test — Runtime Cycle Role Coverage

## Purpose

This test verifies that immutable Card role requirements are matched to the actual Cycle owner and
active workstation crew. P07-0B1 is an advisory and audit package: missing coverage is visible but
does not block Start, progress, material, completion, or ERPNext posting.

## Preconditions

- P07-0A configuration and snapshot acceptance has passed.
- One production Card has at least these Required Job Roles:
  - Operator-in-Charge: required count 1 and a Job Code.
  - Direct Worker: required count 1.
  - Supervisor / Mentor: required count 1 and a scoped Authority Role.
- Eligible Operator Profiles contain the required Job Code, Authority Role, and competency records.
- The Card has produced a live Cycle and Process Executions.

## Test 1 — Missing coverage remains advisory

1. Open the production Card before accepting ownership or opening the workstation crew.
2. Find **Job Role Coverage** above Job Card Execution Lanes.
3. Confirm its status is **Pending** and each missing row says **Awaiting eligible active assignment**.
4. Confirm the panel explicitly says it is advisory in P07-0B1.
5. Confirm ordinary production actions are still available according to the existing V1 rules.

Expected: the Cycle shows the matched count and missing count, but no new role-coverage error blocks
work.

## Test 2 — Operator-in-Charge matching

1. Use an eligible operator to select **Accept Ownership and Start**.
2. Allow the normal live refresh or rescan the Card.
3. Confirm the Operator-in-Charge row shows 1/1 and the Employee name.
4. Open **CFG Job Architecture → Cycle Role Assignments**.
5. Confirm an Active record exists with source **Cycle Ownership**, the immutable requirement row,
   Employee, Operator Profile, Job Code, and matching-evidence JSON.

Expected: accepting ownership creates role evidence without replacing the separate Owner Assignment
history.

## Test 3 — Crew role matching

1. Open the relevant Workstation Crew Session.
2. Join a Direct Participation member as Main or Supporting Operator.
3. Join the supervisor as **Senior / Overseer** or **Oversight Only**.
4. Return to the production Card and allow live refresh.
5. Confirm Direct Worker and Supervisor / Mentor coverage displays the correct people.
6. Confirm Active Crew assignment records link to the Crew Session and Crew Membership.

Expected: Job Code, exact scoped Authority Role, competency, presence, work category, and crew role
are all evaluated independently. The legacy Kanban Role dropdown cannot satisfy an explicitly named
Authority Role.

## Test 4 — Scope and separation negative cases

1. Give a person the correct Authority Role but scope it to another Company, Operation, or
   Workstation.
2. Confirm the relevant requirement remains Pending.
3. Configure a Verifier requirement with **Separate Approver Required**.
4. Make the Cycle owner otherwise eligible and confirm the owner does not fill that Verifier row.
5. Join another eligible active crew member and confirm that person fills it.

Expected: runtime matching never broadens a scoped assignment and never lets the owner satisfy a
separate-approver requirement.

## Test 5 — Assignment interval closure

1. Put a matched crew member On Break or remove them from the active crew.
2. Confirm the role coverage returns to Pending.
3. Confirm the former Cycle Role Assignment is **Ended**, with Ended On and an end reason.
4. Resume or rejoin the person and confirm a new Active assignment interval is created.
5. Complete or cancel the Cycle and confirm all remaining Active Cycle Role Assignments are Ended.

Expected: history is preserved; records are ended rather than deleted or rewritten.

## Pass criteria

- Runtime role coverage uses the immutable Cycle snapshot.
- The current owner and active crew are matched without changing organizational titles.
- Explicit Job Code, Authority Role, competency, scope, presence, and separation rules work.
- Assignment history is auditable and terminal Cycles close active intervals.
- Missing coverage never blocks production in P07-0B1.

Do not enable P07-0B2 exact-action supervisor-pass enforcement until these checks pass.
