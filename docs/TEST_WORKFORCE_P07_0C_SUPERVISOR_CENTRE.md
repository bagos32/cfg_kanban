# P07-0C Acceptance Test — Workforce Supervisor Centre

## Purpose

This test verifies the read-only manager view that combines existing workforce, competency, crew,
participation, compliance, Cycle-role, and supervisor-pass evidence. The centre must not create a
second workforce ledger, change production state, or reinterpret participation as attendance or
payroll.

## Preconditions

- P01–P06 and P07-0A through P07-0B2 have been migrated.
- The testing user has Manufacturing Manager, HR Manager, or System Manager.
- Test data includes at least one open production Cycle, an active Crew Session, Employee
  Competencies, and Job Participation evidence.
- For full queue testing, prepare one missing role assignment, one Crew Compliance Hold, one
  competency expiring within 30 days, and one consumed supervisor pass.

## Test 1 — Permission and navigation

1. Open **CFG Job Architecture → Live Workforce → Workforce Supervisor Centre**.
2. Confirm the route is `/app/kanban-workforce-supervisor`.
3. Confirm an ordinary Desk user without Manufacturing Manager, HR Manager, or System Manager cannot
   open the Page or call its data endpoint.

Expected: the manager centre is separate from the Production Supervisor Action Centre and exposes
only records permitted to the logged-in user.

## Test 2 — Company and workstation filtering

1. Select the manufacturing Company.
2. Select one Workstation.
3. Confirm crews, compliance holds, active participation, and supervisor-pass history narrow to that
   Workstation.
4. Clear Workstation and confirm all permitted Workstations return.
5. Switch Company and confirm records from the first Company are not shown.

Expected: filtering never broadens multi-company visibility.

## Test 3 — Immediate attention queues

Confirm these three queues:

1. **Missing Role Coverage** shows an open Cycle whose role status is Pending or Attention, including
   owner, Cycle state, Company, and the stored coverage summary.
2. **Crew Compliance Holds** shows the Operation, Workstation, Cycle, checkpoint, finding summary,
   current direct/assistant/supervisor counts, and links to the Process Execution and Exception.
3. **Competency Expiry** shows Employee, Skill, level, expiry date/state, Company, Department, and
   certificate reference where present.

Expected: Review buttons open existing authoritative records; the centre creates or edits nothing.

## Test 4 — Live crew visibility

1. Open a Crew Session and scan two Active members.
2. Put one member On Break.
3. Refresh the centre.
4. Confirm Active, Direct, Oversight, and Break totals agree with Crew Membership records.
5. Confirm expected template members who never scanned do not appear as present.

Expected: actual membership, not an expected roster, drives the live crew panel.

## Test 5 — Participation boundary

1. Start production with direct and oversight participants.
2. Confirm the active intervals appear with Employee, role, Operation, Workstation, Cycle, and live
   elapsed duration.
3. Confirm Production Labour and Oversight totals are separate.
4. Confirm the page states that recorded hours are not attendance, payroll eligibility, or payable
   hours.

Expected: no new quantity, attendance, or payroll record is created.

## Test 6 — Supervisor-pass audit

1. Complete the P07-0B2 supervisor-pass test.
2. Refresh the centre.
3. Confirm the pass appears with approver, requester, action, Cycle, Operation, Authority Role,
   effective status, and time.
4. Open **Audit** and compare it with the read-only Supervisor Action Approval record.

Expected: Approved, Consumed, Expired, and Cancelled states are visible without exposing the raw
approval token.

## Test 7 — Refresh behavior

1. Leave the page visible and change a Crew Membership or compliance result from another session.
2. Wait up to 30 seconds and confirm the page refreshes.
3. Put the browser tab in the background for more than 30 seconds.
4. Confirm the hidden tab does not repeatedly request centre data.
5. Return to the tab and confirm one fresh load occurs.

## Pass criteria

- All figures come from existing CFG Kanban records.
- The page is read-only and permission-aware.
- Company and Workstation filters behave correctly.
- Attention queues link to the authoritative record.
- Crew and participation evidence is operational only.
- Hidden tabs do not generate continuous refresh traffic.
