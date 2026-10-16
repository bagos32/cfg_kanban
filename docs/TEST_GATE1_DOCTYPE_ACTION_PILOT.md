# Gate 1 DocType Action Service Task Pilot

**Application:** CFG Kanban

**Scope:** development site only

**Purpose:** prove the complete Service Task → mapped parent/child form → controlled target flow
before any real operational DocType is approved.

## 1. Safety boundary

This test uses two app-owned records that have no stock, accounting, manufacturing, payroll, or
quality-system effect:

| Pilot profile | Destination | Expected end state |
|---|---|---|
| `CFG Gate 1 Pilot - Draft` | `CFG Action Pilot Draft` | Action Run `Draft Created`; target `docstatus = 0` |
| `CFG Gate 1 Pilot - Submit` | `CFG Action Pilot Submission` | Action Run `Submitted`; target `docstatus = 1` |

The records are in the isolated **CFG Kanban Pilot** module. They are the only exact app-owned
targets exempted from the engine's CFG Kanban module deny rule, and each still needs an enabled
**CFG Kanban DocType Action Policy**. The setup never runs automatically during migrate.

Use a development site. Do not bind these profiles to a real recurring schedule.

## 2. Prerequisites

- The updated app is pulled, migrated, built, cache-cleared, and restarted.
- The shared terminal User has the ERPNext role **Kanban Terminal**.
- A test Employee has an active **CFG Kanban Operator Profile** with **Start** and **Complete**.
- A Senior Operator or Supervisor profile can create a manual Service Task.
- Use a responsibility and Workstation allowed by the test operator.

## 3. Install the explicit pilot configuration

1. Log in as **Administrator**, **System Manager**, or a user with
   **CFG Kanban System Maintenance**.
2. Open **CFG Kanban DocType Action Profile** list.
3. Select **Install Gate 1 Pilot** and confirm the development-only warning.
4. Confirm these enabled, Valid profiles appear:
   - `CFG Gate 1 Pilot - Draft`
   - `CFG Gate 1 Pilot - Submit`
5. Open **CFG Kanban DocType Action Policy** and confirm the two targets are enabled. Only the
   submission target may have **Allow Submit When Authorized** enabled.

The button is idempotent: running it again restores the two named pilot configurations rather than
creating duplicate profiles.

## 4. Pilot A — non-submittable draft with parent and child rows

### Configure the schedule

Create one **CFG Kanban Task Schedule** with:

| Field | Sample value |
|---|---|
| Schedule Name | `PILOT-A-DRAFT` |
| Active | enabled |
| Company | test company |
| Task Name | `Inspect Pilot Area A` |
| Category | `Inspection` |
| Trigger Type | `Manual Request` |
| Responsible Kanban Role | responsibility held by the test operator |
| Workstation / Location | allowed test station / `Pilot Area A` |
| Require Supervisor Verification | disabled |
| DocType Action Profile | `CFG Gate 1 Pilot - Draft` |
| DocType Action Trigger | `On Task Complete` |
| DocType Action Required | enabled |

### Execute from the Service Task panel

1. Scan/login the test operator in **Kanban Service Tasks**.
2. A Senior Operator or Supervisor selects **Create Task**, chooses `PILOT-A-DRAFT`, and enters
   request source `Gate 1 draft pilot`.
3. Start the task.
4. Complete the task. The mapped document dialog must open; the task must show
   **Pending Document Posting**, not Completed.
5. Confirm **Service Task** and **Performed By** are populated and read-only.
6. Enter:
   - Summary: `Pilot draft inspection`
   - Outcome: `Pass`
   - Notes: `Draft path validation`
7. Add two **Pilot Observations**:
   - `Guard condition` / `OK` / Accepted
   - `Area condition` / `Clean` / Accepted
8. Select **Save Document**.

### Expected result

- The Task reaches **Completed** only after the document is saved.
- One **CFG Kanban DocType Action Run** exists and ends at **Draft Created**.
- Its linked target is one **CFG Action Pilot Draft**, `docstatus = 0`.
- Parent values and both observation rows match the submitted form.
- The target contains the same Service Task name and Employee.
- Reopening or retrying the completed action does not create a second target.
- The Run attempt history contains create/state/post events and no raw retry token.

Record the Task, Run, and target names in the test report.

## 5. Pilot B — submittable target

Create a second manual schedule with the same safe values, except:

| Field | Value |
|---|---|
| Schedule Name | `PILOT-B-SUBMIT` |
| Task Name | `Inspect Pilot Area B` |
| Location | `Pilot Area B` |
| DocType Action Profile | `CFG Gate 1 Pilot - Submit` |
| DocType Action Trigger | `On Task Complete` |
| DocType Action Required | enabled |

Repeat the operator flow and enter at least one observation. The final button must say
**Submit Document**, not Save Document.

### Expected result

- The Task remains **Pending Document Posting** until submission succeeds.
- The Action Run ends at **Submitted**.
- The linked **CFG Action Pilot Submission** has `docstatus = 1`.
- The target has exactly one Service Task identity, one Employee identity, and the entered child
  rows.
- Retrying the same browser request or reopening the action returns the existing result; it creates
  exactly one target for that Run.

## 6. Required negative and recovery checks

Perform these checks on fresh pilot Task occurrences:

1. **Missing parent value:** leave Summary empty. Posting is rejected inside the dialog; no second
   target is created. Correct the value and retry.
2. **Missing child row:** remove all observations. Posting is rejected; the Task stays Pending
   Document Posting.
3. **Terminal permission:** temporarily remove **Kanban Terminal** from the shared terminal User.
   Creation must be denied by normal target permission. Restore the role before continuing.
4. **Network/retry safety:** submit once, then repeat the action using the retained dialog. The Run
   must still link to exactly one target.
5. **Supervisor recovery:** place a test Run into an allowed recovery situation using the product's
   controlled failure path. In the Service Task panel, scan an authorized Supervisor and verify
   **Return to Form** is offered only without a linked target; **Recheck Linked Target** is offered
   only with one. Every recovery requires notes.
6. **Private evidence:** attach a photo/file to the Task before posting. The Run records the stable
   media registry reference. Opening it requests a temporary view URL; neither the Run nor target
   stores a presigned URL.

## 7. Acceptance record

Gate 1 may be marked live-site accepted only when both pilots pass and the tester records:

- app commit;
- site and test date;
- terminal User and Employee;
- schedule, Task, Action Run, and target names;
- final Task/Run/target states;
- child-row count;
- duplicate count (must be one target per Run);
- negative/recovery check results;
- screenshots or private-media evidence references where required.

After acceptance, disable or remove the pilot profiles from all Task Schedules. Keep the Action
Runs and target records as test audit evidence; do not delete transactional history to hide a failed
test.
