# CFG Kanban Acceptance Test — Workforce P06 Scanner-First Crew Controls

## Purpose

This test proves that a production operator can control the persistent Workstation crew from the
existing Production Operator Panel by touch or barcode scanner. The helper's existing operator QR
identifies that Employee for crew membership only. It does not log the helper into the terminal,
replace the main authenticated operator, or duplicate ERPNext Job Card quantity.

Complete P01–P05 first. Use the same configured two-person or supervised pilot Operation, active
employees, competencies, Crew Requirement and production Card used in the P04/P05 tests.

## Printable scanner commands

From the Production Operator Panel open **Scanner Help**, then **Print Command Labels**. Confirm the
sheet includes:

- `CFG:CMD:CREW` — open Crew Controls for the current execution;
- `CFG:CMD:CREW_OPEN` — open the Workstation crew;
- `CFG:CMD:CREW_JOIN`, `CREW_JOIN_OVERSIGHT`, `CREW_JOIN_TEMP`;
- `CFG:CMD:CREW_BREAK`, `CREW_RESUME`, `CREW_LEAVE`;
- `CFG:CMD:CREW_MAIN`, `CREW_CONTEXT`, and `CREW_CLOSE`;
- the existing `CFG:CMD:CONFIRM` and `CFG:CMD:CANCEL` labels.

These command labels contain no credentials or production quantity.

## Test 1 — open Crew Controls

1. Sign in to the Production Operator Panel with the pilot Main Operator.
2. Scan the production/process Card containing the pilot execution.
3. Confirm every Job Card Execution Lane shows a **Workstation Crew** strip and **Crew Controls**.
4. Scan `CFG:CMD:CREW`. The panel must select the current In Progress/Blocked/Paused execution,
   otherwise the next Ready execution.
5. Confirm the modal shows exact Operation, Workstation, Job Card, effective policy, current
   findings, member roster and scanner input.

Expected result: a crew-specific hold is shown ahead of ordinary current work. No crew action is
performed merely by opening the modal.

## Test 2 — open the persistent Workstation crew

1. If approved templates exist, select one by touch or scan its numbered `CFG:SELECT:n` label.
   A template is optional and is only the expected-roster snapshot.
2. Select **Open Crew Session**, or scan `CFG:CMD:CREW_OPEN` followed by
   `CFG:CMD:CONFIRM`.
3. Confirm the terminal's authenticated operator becomes **Main Operator / Direct Participation**.
4. Confirm the crew stays attached to Company + Workstation and is not recreated for every Card.

Expected result: one active Crew Session exists and the Main Operator is the first actual
Membership. Expected template members are not present until they scan.

## Test 3 — join direct and oversight employees

1. Scan `CFG:CMD:CREW_JOIN`.
2. Confirm the modal says to scan an employee QR, then scan the helper's normal operator QR.
3. Confirm the helper appears as Supporting Operator / Direct Participation.
4. Scan `CFG:CMD:CREW_JOIN_OVERSIGHT`, then scan the qualified supervisor's normal operator QR.
5. Confirm the supervisor appears as Senior / Overseer / Oversight Only.
6. Confirm the terminal header still names the original logged-in operator.

Expected result: compliant coverage resolves the crew hold automatically. The Card live refresh
updates the crew strip without requiring a rescan. No additional ERPNext Job Card is created.

## Test 4 — break, resume and leave

1. Scan `CFG:CMD:CREW_BREAK`, then scan the helper's QR.
2. Confirm the helper becomes On Break and does not count as active coverage. A configured minimum
   crew must create a Crew Hold.
3. Scan `CFG:CMD:CREW_RESUME`, then the same helper QR. Confirm Active and automatic hold recovery.
4. Scan `CFG:CMD:CREW_LEAVE`, then the helper QR. Confirm Left and the correct compliance result.
5. Try to make the current Main Operator leave. Confirm the server requires a Main Operator change
   or complete Crew Session closure first.

## Test 5 — change Main Operator and operation context

1. Rejoin the helper if necessary.
2. Scan `CFG:CMD:CREW_MAIN`, then scan that active helper's QR.
3. Confirm the old main becomes Supporting Operator and the helper becomes Main Operator.
4. Open another operation lane at the same Workstation and scan `CFG:CMD:CREW_CONTEXT`.
5. Confirm only the persistent crew's current Operation context changes; the Crew Session and
   Membership intervals are retained.

## Test 6 — controlled closure

1. Scan `CFG:CMD:CREW_CLOSE`.
2. Confirm the modal asks for a second `CFG:CMD:CONFIRM`; scan Cancel once and verify nothing closes.
3. Repeat Close and Confirm.
4. Confirm every still-present member receives a Left interval, the Crew Session becomes Closed,
   immutable Leave/Close events exist, and configured live work enters a Crew Hold.

## Evidence and failure checks

- A wrong, inactive or other-company employee QR must be rejected without changing the terminal
  operator or current crew.
- An operator who is not actively in the crew and has no Supervisor/Override authority must see the
  crew but cannot mutate it.
- An On Break operator cannot manage the crew unless they have Supervisor/Override authority.
- Crew Event, Membership, Compliance Check, Compliance Hold and Job Participation records must
  retain Employee, terminal User, Operator Session and timestamps.
- ERPNext Work Order and Job Card good/completed quantities must remain unchanged by crew actions.

