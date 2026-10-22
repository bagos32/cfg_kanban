# CFG Kanban Acceptance Test — P04 Crew Authorization Engine

**Package:** Workforce P04  
**Date:** 22 October 2026  
**Audience:** System tester, manufacturing supervisor, implementation administrator  
**Purpose:** Prove that approved crew and competency rules control production without duplicating
ERPNext Job Card quantities.

## 1. Test boundary

P04 is the server authorization package. It checks the actual P03 Workstation crew against the
effective P02 crew policy and P01 Employee competencies at these checkpoints:

1. Before Runtime Allocation;
2. Before Operation Start;
3. Progress;
4. Crew Change;
5. Before Completion; and
6. Before WIP Release.

P06 will add scanner-first crew-management buttons to the Production Operator Panel. Until P06 is
deployed, use the temporary browser-console calls in section 6 to open and change a Crew Session.
Do not create or edit Crew Session, Membership, Event, Compliance Check, or Exception records
directly from Desk.

## 2. Expected result summary

| Condition | Expected result |
|---|---|
| Operation has no effective Crew Requirement | Existing production behavior continues; no Crew Session is required |
| Policy exists but no active crew | Production action is rejected and a Crew Compliance Hold is recorded |
| Active crew is short, on break, expired, unqualified, or concurrently direct-working elsewhere | The related Process Execution is Blocked |
| Active crew satisfies the policy | The action proceeds and a Pass Compliance Check is recorded |
| Crew is corrected after a hold | The crew-specific hold resolves and the previous execution state is restored |
| ERP Job Card feedback arrives during a crew failure | ERP evidence remains authoritative, but CFG Kanban withholds downstream WIP release |

## 3. Prerequisites

Confirm all of the following before testing:

- the P04 revision is pulled to the server;
- `bench --site site1.local migrate` completed successfully;
- assets were built, cache cleared, and Bench restarted;
- scheduler/workers are healthy;
- three active ERPNext Employees have active **CFG Kanban Operator Profile** records;
- the test BOM, Work Order, Job Cards, Operation, and Workstation are valid;
- one reusable production Card can create or open a Process Execution for the test Operation; and
- the tester can access **CFG Kanban → Execution Records → Crew Compliance Checks** and
  **CFG Kanban Exception**.

Use a non-production test Work Order and quantities. Do not reuse an active live production crew.

## 4. Sample master data

Replace the example Company, Operation, Workstation, and Employees with real test records. Keep the
policy shape unchanged so expected results remain comparable.

### 4.1 Employees

| Test identity | Example | Required setup |
|---|---|---|
| A — Main Operator | `EMP-A` | Active Operator Profile; allowed to start/progress/complete at the test Operation and Workstation |
| B — Trainee Assistant | `EMP-B` | Active Operator Profile; same Operation and Workstation access |
| C — Qualified Supervisor | `EMP-C` | Active Supervisor/Senior Operator Profile; same Workstation access |

Keep each person's printable Operator QR available. The console calls use the same raw QR payload;
they never use or expose the stored credential hash.

### 4.2 Skill records

Create these in **CFG Kanban → Skill Registry**:

| Field | Direct-work skill | Supervisor skill |
|---|---|---|
| Skill Code (`skill_code`) | `P04-DIRECT` | `P04-SUPERVISE` |
| Skill Name (`skill_name`) | P04 Direct Work | P04 Trainee Supervision |
| Skill Category (`skill_category`) | Production | Production |
| Active (`active`) | Yes | Yes |
| Certification Reference Required (`requires_certification`) | No for this test | No for this test |
| Expiry Date Required (`requires_expiry_tracking`) | Yes | Yes |

### 4.3 Employee Competencies

Create, review, and Submit these **CFG Kanban Employee Competency** records:

| Employee | Skill | Competency Level | Work Independently | Supervise Trainees | Effective From | Valid Until |
|---|---|---|---|---|---|---|
| A | `P04-DIRECT` | L2 - Qualified Operator | Yes | No | Today or earlier | Future date |
| B | `P04-DIRECT` | L1 - Trainee | No | No | Today or earlier | Future date |
| C | `P04-SUPERVISE` | L3 - Senior / Lead | Yes | Yes | Today or earlier | Future date |

Enter an **Assessment Reference** on every row. After submission, confirm **Authorization Status**
is Active and the approval identity/time are populated.

### 4.4 Crew Requirement Profile

Create and Submit one **CFG Kanban Crew Requirement Profile**:

| Field | Test value |
|---|---|
| Requirement Code (`requirement_code`) | `P04-SUPERVISED-2` |
| Requirement Name (`requirement_name`) | P04 Two-Person Supervised Crew |
| Company (`company`) | Test manufacturing Company |
| Active (`active`) | Yes |
| Revision (`revision`) | 1 |
| Crew Mode (`crew_mode`) | Supervised Operation |
| Minimum Direct Workers (`minimum_direct_workers`) | 2 |
| Minimum Assistants (`minimum_assistants`) | 1 |
| Trainee Policy (`trainee_policy`) | Supervised Only |
| Active Supervisor Presence (`supervision_presence`) | Required When Trainees Present |
| Maximum Trainees per Supervisor (`max_trainees_per_supervisor`) | 1 |

Add these **Required Skills** child rows:

| Crew Role | Required Skill | Minimum Competency | Minimum People | Independent | Supervision Authorization |
|---|---|---|---:|---|---|
| Direct Worker | `P04-DIRECT` | L2 - Qualified Operator | 1 | Yes | No |
| Active Supervisor | `P04-SUPERVISE` | L3 - Senior / Lead | 1 | No | Yes |

### 4.5 Apply the policy

For the simplest test, open the production **CFG Kanban Master**, find the test Operation in
**Operation Profiles**, and select `P04-SUPERVISED-2` in **Normal Crew Requirement**
(`crew_requirement_profile`). Save.

Do not also add a Workstation or Card override during the first pass. Those layers merge
conservatively and would make fault diagnosis harder. Test policy merging separately after the basic
authorization test passes.

### 4.6 Crew Template

Create and Submit **CFG Kanban Crew Template** `P04-CREW`:

| Employee | Crew Role | Work Category |
|---|---|---|
| A | Main Operator | Direct Participation |
| B | Supporting Operator | Direct Participation |
| C | Senior / Overseer | Oversight Only |

Select the same Company, Workstation, and optional Operation used above. A template is an expected
roster only; B and C do not count until their own QRs are scanned into the active Crew Session.

## 5. Establish the production test execution

1. Submit the ERPNext Work Order and ensure the relevant Job Card exists.
2. Open **Kanban Operator** and log in by scanning Employee A's Operator QR.
3. Scan/activate the normal production Card or its Process/Station Card until the test Process
   Execution is visible.
4. Do not start the Job Card yet.
5. Record the Process Execution name, Cycle, Job Card, Operation, and Workstation on the test sheet.

## 6. Temporary P03 crew controls before P06

Open browser Developer Tools on the logged-in **Kanban Operator** page and select **Console**. The
following calls reuse the authenticated Kanban operator session saved by the panel.

Replace values in angle brackets with exact ERPNext record names.

### 6.1 Open the persistent Workstation Crew Session

```javascript
await frappe.call({
  method: "cfg_kanban.services.crew_registry.open_workstation_crew_session",
  args: {
    company: "<COMPANY>",
    workstation: "<WORKSTATION>",
    operation: "<OPERATION>",
    crew_template: "P04-CREW",
    operator_session_token: localStorage.getItem("cfg_kanban_operator_session"),
    notes: "P04 acceptance test"
  }
}).then(r => console.log(r.message));
```

Copy the returned Crew Session name, for example `KCS-2026-00001`. Opening the session registers only
Employee A as the actual Main Operator.

### 6.2 Join Employee B or C

Run the call once per Employee. Scan or paste that Employee's raw Operator QR payload when prompted.

```javascript
await frappe.call({
  method: "cfg_kanban.services.crew_registry.join_crew_member",
  args: {
    crew_session: "<CREW-SESSION>",
    member_qr_token: prompt("Scan helper Employee QR"),
    crew_role: "Supporting Operator",
    work_category: "Direct Participation",
    reason: "P04 acceptance test join",
    operator_session_token: localStorage.getItem("cfg_kanban_operator_session")
  }
}).then(r => console.log(r.message));
```

For Employee C, change `crew_role` to `Senior / Overseer` and `work_category` to `Oversight Only`.

### 6.3 Break, resume, or leave a member

Use the appropriate method name below and scan that member's QR when prompted:

```javascript
await frappe.call({
  method: "cfg_kanban.services.crew_registry.break_crew_member",
  args: {
    crew_session: "<CREW-SESSION>",
    member_qr_token: prompt("Scan Employee QR"),
    reason: "P04 acceptance test break",
    operator_session_token: localStorage.getItem("cfg_kanban_operator_session")
  }
}).then(r => console.log(r.message));
```

Replace `break_crew_member` with `resume_crew_member` to resume or `leave_crew_member` to leave.

### 6.4 Close the Crew Session after testing

```javascript
await frappe.call({
  method: "cfg_kanban.services.crew_registry.close_workstation_crew_session",
  args: {
    crew_session: "<CREW-SESSION>",
    reason: "P04 acceptance test completed",
    operator_session_token: localStorage.getItem("cfg_kanban_operator_session")
  }
}).then(r => console.log(r.message));
```

## 7. Required acceptance scenarios

### Test A — Backward compatibility without a policy

1. Use a different test Operation that has no Normal Crew Requirement, no effective Workstation
   Crew Requirement, and no Additional Crew Requirement on its Process/Station Card.
2. Start and report a small progress quantity through the normal Operator Panel.

Expected:

- no Crew Session is demanded;
- the existing production action works normally; and
- P04 does not create a Compliance Check for an unconfigured Operation.

### Test B — Policy exists but no active crew

1. Return to the P04-controlled execution.
2. Ensure no Crew Session is active at the Workstation.
3. Select **Start Job Card**.

Expected:

- the action is rejected with **Crew authorization required**;
- the message states that no active Crew Session exists and lists missing coverage;
- Process Execution becomes Blocked with **Crew Compliance = Hold**;
- **Crew Compliance Hold** links to an Open Critical `CFG Kanban Exception`; and
- **Last Crew Compliance Check** links to a Hold result at **Before Operation Start**.

### Test C — Incomplete actual crew remains held

1. Use section 6.1 to open the Crew Session as Employee A.
2. Refresh the Process Execution.

Expected:

- the hold remains;
- the newest Crew Change check shows one active direct worker;
- B and C in the template snapshot do not count as present; and
- findings identify the missing direct worker, assistant, and supervisor coverage.

### Test D — Compliant crew automatically releases the hold

1. Join B as Supporting Operator / Direct Participation.
2. Confirm the hold remains because the active authorized supervisor is still missing.
3. Join C as Senior / Overseer / Oversight Only.
4. Refresh the Process Execution and Operator Panel.

Expected:

- the latest Crew Change check is Pass;
- Crew Compliance becomes Compliant;
- the Crew Compliance Hold Exception becomes Resolved;
- the execution returns to its previous Ready state; and
- the general Blocked flag clears only when the crew hold owned that block.

### Test E — Start and progress checkpoints pass

1. Start the Job Card normally.
2. Report a small valid incremental progress quantity.
3. Open **Crew Compliance Checks** filtered by Process Execution.

Expected:

- a Pass row exists for **Before Operation Start**;
- a Pass row exists for **Progress**;
- Employee A, the Operator Session, and terminal User are recorded; and
- ERPNext Job Card progress is updated once only. B and C do not create extra Job Cards or output.

### Test F — Break immediately creates a hold

1. Put Employee B on break using section 6.3.
2. Refresh the Operator Panel.
3. Try to report another progress quantity.

Expected:

- the Crew Change check fails because On Break does not count;
- the Process Execution becomes Blocked;
- the progress action is rejected and does not change Job Card quantity; and
- the hold findings show insufficient direct workers/assistants.

Resume B. Expected: the next Crew Change check passes and the hold resolves automatically.

### Test G — Suspended or expired competency does not count

1. With the execution otherwise compliant, open A's submitted Employee Competency.
2. Use its controlled Authorization action to Suspend it with reason `P04 expiry/suspension test`.
3. Try to report progress.

Expected:

- A no longer satisfies the L2 Direct Worker requirement;
- progress is rejected and a Crew Compliance Hold is recorded; and
- the Compliance Check policy/crew snapshots remain readable for audit.

Reactivate A's competency with a reason. Trigger any crew change or retry progress. Expected: the
hold resolves and the action proceeds. An equivalent test may use a competency whose **Valid Until**
is in the past.

### Test H — Concurrent direct participation is blocked

1. On a second test Workstation, log in an authorized operator and open another active Crew Session.
2. Join A or B there as **Direct Participation** while they remain Active in the first session.
3. Retry progress on the first execution.

Expected:

- the check fails with `CONCURRENT_DIRECT_WORK` evidence;
- both crew registrations remain auditable; and
- production does not proceed until the Employee leaves or stops direct participation in one active
  Workstation Crew Session.

### Test I — Completion and WIP release checkpoints

1. Restore the compliant A+B+C crew.
2. Complete the required quantity and select the normal Job Card completion action.
3. Perform the configured Digital, Full Batch, Automatic, or Physical WIP handoff.

Expected:

- completion has a Pass **Before Completion** check;
- downstream release has a separate Pass **Before WIP Release** check;
- released WIP equals the normal CFG/ERP quantity logic; and
- no supporting crew member multiplies the quantity.

Repeat the handoff after breaking B before release. Expected: ERPNext completion evidence remains
authoritative, but CFG Kanban does not release downstream WIP and records the Crew Compliance Hold.

## 8. Policy-layer merge test

After Tests A–I pass:

1. Create and Submit a **CFG Kanban Workstation Crew Requirement** for the same Company/Workstation,
   using a stricter submitted Crew Requirement Profile.
2. Optionally select another submitted **Additional Crew Requirement** on the Process or Station
   Card.
3. Preview or trigger authorization.

Expected: the effective policy takes the highest staffing/skill requirement, most restrictive
trainee/supervision rule, and lowest positive trainee ratio. A Card cannot weaken an Operation or
Workstation safety rule.

## 9. Evidence to retain

For each failed and passed scenario, record:

- Git revision and test date;
- Company, Workstation, Operation, Master, Card, Cycle, Execution, Work Order, and Job Card;
- Crew Session and Membership names;
- Compliance Check name and result;
- Exception name/status when held;
- Job Card quantity before and after the attempted action; and
- screenshot of the operator message and Process Execution Crew Authorization section.

## 10. Cleanup

1. Complete or cancel only the dedicated test Cycle using normal controlled workflows.
2. Reactivate any competency suspended solely for testing.
3. Make helper members leave and close the test Crew Session with a reason.
4. Do not delete Compliance Checks, Crew Events, Memberships, or Exceptions; they are audit records.
5. Keep or inactivate the test policy/master records according to the site's test-data policy.

## 11. Pass criteria

P04 passes only when:

- all configured checkpoints enforce the same effective approved policy;
- no-policy operations remain backward-compatible;
- failed checks persist a clear auditable hold;
- compliant crew correction resolves only the crew-owned block;
- breaks, expiry, suspension, supervision, ratio, and concurrency behave as documented;
- WIP is not released under a crew hold; and
- ERPNext Job Card quantities remain single and authoritative.
