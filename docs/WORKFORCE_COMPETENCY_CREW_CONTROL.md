# CFG Kanban Workforce, Competency & Crew Control

## Status and delivery boundary

This is the approved implementation baseline for packages P01–P07. It extends the existing CFG
Kanban application; it is not a separate app and does not replace ERPNext Employee, Work Order, Job
Card, Operation, or Workstation records.

ERPNext Job Card remains authoritative for production quantities. CFG Kanban records the workforce
authorization, crew presence, participation intervals, scanner interaction, and audit evidence.
Supporting employees must never create duplicate quantity-bearing ERPNext Job Cards or multiply the
reported production output.

The separate **CFG Job Architecture** workspace is the manager and auditor entry point for this
implemented foundation. It groups the existing Operator Profile, Skill, Employee Competency, crew
policy, live Crew Session, membership, compliance, Job Participation, Cycle, Process Execution,
operation result, Event, and Exception records without duplicating their data. Record-level access
continues to use each DocType's existing permissions.

The workspace does not mean that every proposed shared-job architecture record already exists.
EODR, payroll export, general capacity, and cross-app integration remain controlled future packages.
If a future package conflicts with an existing CFG Kanban identity, competency scale, Cycle,
participation record, event contract, exception boundary, or the TrackQMS integration boundary,
implementation must stop for an explicit product decision before changing the data model.

### Reuse-first shared job register

The **Shared Job Register** report in the CFG Job Architecture workspace implements the approved
reuse boundary without creating a second job database:

- **CFG Kanban Cycle** is the shared work instance and stable repeated-execution identity.
- **CFG Kanban Process Execution** is the operation-level execution under that Cycle.
- **CFG Kanban Job Participation** is the employee contribution interval under the Process
  Execution and Cycle.
- ERPNext Work Order and Job Card remain the manufacturing and quantity authority.

The report shows each permitted Cycle once, with operation counts, blocked/open operation counts,
unique participants, active participants, participation segment count, and recorded participation
hours. Active intervals are measured to the current report time. These hours are operational
evidence only: they are not attendance, payable time, payroll eligibility, or earnings. The report
uses permission-aware Cycle selection before calculating aggregates, so it does not create a
broader cross-company visibility path.

### Optional Cycle operator-in-charge

Job ownership is an explicit **Card-level opt-in** and is separate from crew participation:

- Create stable business identifiers in **CFG Kanban Job Code**.
- Add the Job Codes an Employee may own under **CFG Kanban Operator Profile → Job Codes**.
- On a production **CFG Kanban Card**, enable **Enforce Job Owner** and select the required Job Code.
- Disabled Cards continue through the established execution flow and do not require or create a Job
  Owner Assignment. Existing Cards migrate with enforcement disabled.
- Each new Cycle snapshots the Card policy. The first eligible direct operator who starts work accepts
  ownership and becomes the single **Operator-in-Charge** for that Cycle.
- Assistants, trainers, supporting operators, and supervisors remain Job Participation/Crew records;
  they do not become co-owners and may still perform authorized later work without replacing the owner.
- **CFG Kanban Job Owner Assignment** preserves the ownership audit record. ERPNext Work Order and Job
  Card remain the manufacturing and quantity authority.

Do not use Kanban Role, Service Responsibility, allowed Operation/Workstation, or Competency as a
substitute for Job Code. They answer different authorization questions.

Delivery remains sequential:

| Release | Packages | Boundary |
|---|---|---|
| R1 | P01, P02, P03 | Competency foundation, crew requirements, persistent workstation crew |
| R2 | P04, P05, P06 | Server enforcement, job participation, scanner-first floor UI |
| R3 | P07 | Supervisor controls, reports, exception and compliance audit |

Each package must be reviewed, migrated, tested, documented, committed, deployed, and accepted before
the next package changes runtime behavior.

## Gate 0 repository audit — 22 October 2026

- Primary working tree: `g-p-6aa02b4ed18c8191a7352634cb6b3ecd`.
- Primary branch: `codex/build-initial-cfgkanban-appmain`.
- Audited starting revision: `2730be6`.
- Existing WIP-bin operation-scoped consumption and permanent output-container work is present and
  must remain intact.
- One pre-existing untracked manual snapshot, `docs/USER_MANUAL_v1.89.md`, is intentionally excluded
  from this extension.
- Operator identity already uses ERPNext Employee plus a hashed QR credential and a time-limited
  `CFG Kanban Operator Session`; the ERP terminal User remains a separate audit identity.
- Operation and Workstation scope already lives in `CFG Kanban Operator Profile`.
- ERP manufacturing writes remain behind the existing gateway and ERP feedback hooks. No workforce
  package may directly replace Work Order or Job Card quantity logic.
- No Skill, Employee Competency, Crew Session, Crew Requirement, or Job Participation DocType existed
  at the audited revision.
- The local full test discovery has two pre-existing environment failures: the macOS Python 3.9
  runtime cannot parse one Python 3.10 union annotation, and tests importing Frappe cannot run without
  the Bench environment. Contract/schema tests otherwise run locally; server migration and Bench tests
  remain required before acceptance.

## P01 — Skill & Competency Registry

P01 adds configuration and approval records only. It does not yet block operation start or progress;
that enforcement belongs to P04 after P02 and P03 establish the effective policy and actual crew.

### CFG Kanban Skill

Create one reusable skill for each independently controlled capability, for example:

| Field | Example |
|---|---|
| Skill Code | `KETTLE-COOKING` |
| Skill Name | Kettle Cooking |
| Skill Category | Production |
| Certification Reference Required | Yes, when a certificate/assessment must be identified |
| Expiry Date Required | Yes, when authorization must be renewed |
| Default Validity (Days) | Optional planning value |
| External Standard / SOP Reference | Neutral approved-document identifier only |

Skill codes are stable uppercase business identifiers. Inactivating a Skill prevents new approvals
but preserves historical Employee Competency records.

### Competency levels

| Level | Meaning | Maximum authorization available in P01 |
|---|---|---|
| L0 | Untrained / awareness only | No independent work; no supervision |
| L1 | Trainee | Must not be authorized for independent work or supervision |
| L2 | Qualified Operator | May be explicitly authorized for independent work |
| L3 | Senior / Lead | May be explicitly authorized to supervise trainees |
| L4 | Trainer / Supervisor | May be explicitly authorized to supervise trainees |

Level alone is not permission. **Authorized to Work Independently** and **Authorized to Supervise
Trainees** are explicit, skill-specific approvals. The Operator Profile action checkboxes and allowed
Operation/Workstation scope remain separate controls.

### Approve an Employee Competency

1. Ensure the Employee is Active and already has a **CFG Kanban Operator Profile**.
2. Open **CFG Kanban → Employee Competencies → New**.
3. Select Employee and Skill. The Operator Profile and names resolve from authoritative records.
4. Select L0–L4 and the explicit independent/supervision approvals.
5. Enter Effective From and, when required, Valid Until.
6. Enter the required assessment/certification reference. Optional external evidence is stored as a
   neutral ID and immutable revision snapshot; CFG Kanban does not link to TrackQMS DocTypes.
7. Save, review, and Submit. Submission records the approving ERP User and timestamp and activates the
   authorization.

Overlapping submitted Active approvals for the same Employee and Skill are rejected. Draft renewals
may be prepared while the current approval remains active.

### Suspend, reactivate, revoke, or cancel

Use the **Authorization** actions on the submitted Competency. Every status change requires a reason
and records the responsible ERP User and timestamp. A suspended approval may be reactivated. A revoked
approval cannot be reactivated; create and submit a new approval. Before cancelling a submitted
record, enter a Status Change / Revocation Reason. History remains in the document timeline and
version audit.

### Effective validity

Runtime validity is evaluated from all of the following:

- submitted document;
- stored status is Active;
- Effective From is not in the future;
- Valid Until has not passed;
- requested minimum L0–L4 level is met; and
- explicit independent/supervisor flags are met when requested.

An expired record can remain stored as Active because expiry is computed against the requested date.
It is never returned as effectively Active by the competency service.

### P01 acceptance test

1. Create Skill `KETTLE-COOKING`, requiring certification and expiry.
2. Create an L1 trainee competency and confirm independent authorization is rejected.
3. Create and submit an L2 competency with certificate, effective date, expiry, and independent work
   enabled.
4. Open the Employee's Operator Profile and confirm the competency summary shows L2 and Active.
5. Try to submit an overlapping approval for the same Employee/Skill and confirm it is rejected.
6. Suspend the submitted approval with a reason and confirm the Operator Profile summary shows
   Suspended.
7. Reactivate it with a reason, then revoke it. Confirm a revoked record cannot be reactivated.
8. Create a record whose Valid Until is in the past and confirm the summary reports Expired.

P01 acceptance proves registry correctness only. Runtime blocking is provided by the later P04
authorization engine when an effective Crew Requirement uses these competencies.

## P02 — Crew Requirement Policy

P02 adds approved configuration and a conservative policy resolver. P02 alone does not block an
operation; the P04 engine applies its result at the controlled runtime checkpoints.

### CFG Kanban Crew Requirement Profile

Create a reusable Profile, add every required skill row, then Submit it. The four crew modes are:

| Mode | Configuration rule |
|---|---|
| Single Operator | Exactly one direct worker; separate supervision may still be required |
| Multiple Operators | At least two direct workers |
| Supervised Operation | Active supervisor presence is mandatory |
| Qualified Lead + Assistants | At least one lead plus the configured number of assistants |

**Minimum Direct Workers** counts employees directly participating in the operation. An
oversight-only supervisor is not silently counted as direct labour. **Trainee Policy** may prohibit
trainees, allow them only with active supervision, or permit them. A supervised policy also records
the maximum trainee-to-supervisor ratio.

Each Required Skill row identifies a Direct Worker, Qualified Lead, or Active Supervisor role; the
Skill; minimum L0–L4 level; minimum people; and whether independent-work or trainee-supervision
authorization is required. Lead rows always require independent authorization. Active Supervisor
rows always require the explicit trainee-supervision authorization from P01.

Profiles are submitted manager approvals. Use a new Profile/revision when the approved safety rule
changes. External policy fields are neutral identifiers and immutable revision snapshots; they do
not create a TrackQMS dependency.

### Three policy layers

1. In **CFG Kanban Master → Operation Profiles**, select the normal submitted Crew Requirement.
2. Create a submitted **CFG Kanban Workstation Crew Requirement** for equipment-specific minimums.
   Operation is optional: blank applies the restriction to every operation at that Workstation.
3. A Process or Station Kanban Card may select an additional submitted Profile for a special stricter
   requirement.

The effective policy combines every applicable submitted, active layer. It uses the highest direct
worker/assistant minimum, the most restrictive trainee and supervision rule, the lowest positive
trainee-to-supervisor ratio, and the highest skill level/people/authorization requirement for each
skill-role pair. Therefore a Single Operator Card cannot bypass a two-person Workstation rule.

### P02 acceptance test

1. Submit Profile `PACKING-SINGLE` with Single Operator and one direct-worker Packaging skill.
2. Submit Profile `MIXING-TWO-PERSON` with Multiple Operators, two direct workers, trainees
   prohibited, and the required Mixing skill.
3. Submit Profile `MIXING-SUPERVISED` with Supervised Operation, trainees supervised only, and an
   Active Supervisor skill requiring L3 or L4 supervision authorization.
4. Assign `PACKING-SINGLE` to an Operation Profile.
5. Create and submit a Workstation rule applying `MIXING-TWO-PERSON` to that Workstation.
6. Optionally select `MIXING-SUPERVISED` on its Station Card.
7. Preview the resolver on the server or inspect its returned policy and confirm the result still
   needs at least two direct workers and includes the stricter supervision/skill rules.
8. Confirm normal production behavior is unchanged. P02 stores and resolves policy only; P04 will
   enforce it against the P03 active crew.

## P03 — Workstation Crew Registry

P03 records who is physically present at a Workstation. It does not yet decide whether that crew is
qualified; P04 consumes this registry and applies the P01/P02 authorization rules.

### Crew Templates are expected rosters, not attendance

A submitted **CFG Kanban Crew Template** identifies one Company's normal Workstation team and an
optional default Operation. It supports these roles:

- Main Operator;
- Supporting Operator;
- Senior / Overseer; and
- Temporary Support.

Every member is separately classified as Direct Participation or Oversight Only. The template must
contain exactly one Main Operator and that person must be a direct participant. Employee names and
active Operator Profiles are validated when the template is saved and submitted.

When a Crew Session opens with a template, CFG Kanban copies an immutable JSON snapshot of the
expected roster and revision into the session. It does **not** create attendance for those people.
This prevents yesterday's saved team from being silently treated as present today.

### Persistent Workstation Crew Session

Only one active **CFG Kanban Crew Session** may be opened for the same Company and Workstation. It
remains open across successive Cards, Cycles, Work Orders, and Job Cards until explicitly closed.
Changing the current Operation context does not close or recreate the crew.

The authenticated terminal operator opens the session and becomes its first Main Operator. A helper
then scans their existing Employee/Operator Profile QR to join. That scan resolves identity only: it
does not replace the authenticated terminal operator, create a second Operator Session, or transfer
the helper's permissions to anyone else.

### Membership intervals and immutable events

**CFG Kanban Crew Membership** holds each actual presence interval with Employee, role, work
category, Active/On Break/Left state, join time, break start, and leave time. The controlled service
supports join, break, resume, leave, main-operator change, operation-context change, and session
closure. The current Main Operator cannot leave until another actively present person becomes Main
Operator or the entire Crew Session is closed.

Every transition also inserts a read-only **CFG Kanban Crew Event** with the subject Employee, acting
Employee, terminal ERP User, Operator Session, timestamp, previous/new state, reason, and structured
details. Closing a session closes every still-present membership and preserves individual Leave
events before the final Close Session event.

### P03 acceptance test

1. Submit a Crew Template for one Company and Workstation with Employee A as Main Operator,
   Employee B as Supporting Operator, and Employee C as oversight-only Senior / Overseer.
2. Open a Crew Session using Employee A's authenticated Operator Session and the template.
3. Confirm only Employee A has an actual Membership. B and C appear only in Expected Roster Snapshot.
4. Scan Employee B's QR to join. Confirm B gets an Active direct Membership without becoming the
   authenticated terminal operator.
5. Break and resume Employee B. Confirm the Membership state changes and separate Break/Resume
   Crew Events remain in the audit list.
6. Scan Employee C to join as Senior / Overseer with Oversight Only.
7. Change Main Operator from A to B. Confirm A becomes Supporting Operator, B becomes Main Operator,
   and one Change Main Operator event records both membership references.
8. Change the Operation context and confirm the same Crew Session remains active.
9. Make C leave, then close the Crew Session with a reason. Confirm all remaining Memberships are
   Left and the session is Closed.
10. Confirm opening another crew for the same Workstation was rejected while the first was active,
    but succeeds after closure.
11. Confirm operations without an effective Crew Requirement remain backward-compatible. Operations
    with an effective requirement are now enforced by P04 below.

## P04 — Authorization Engine

Validate competency, crew size, qualified lead, supervision, concurrency, and expiry before start,
during progress, on crew change, and before completion/WIP release. Loss of required coverage creates
a controlled Crew Compliance Hold.

P04 is implemented as a server-side authorization boundary. It resolves the same conservative P02
effective policy and compares it with only P03 Memberships whose presence is **Active**; an Employee
on break never counts. A requirement is checked at Before Runtime Allocation, Before Operation
Start, Progress, Crew Change, Before Completion, and Before WIP Release. ERPNext Job Card quantities
remain authoritative and no supporting crew member creates an extra Job Card or quantity posting.

The engine verifies minimum direct workers, assistants, skill/level/explicit authorization,
qualified lead and active supervisor requirements, trainee rules and ratios, effective dates and
expiry, and concurrent direct participation in more than one active Workstation Crew Session.
Operations with no effective approved Crew Requirement are allowed without a Crew Session for
backward compatibility.

Every configured decision creates a read-only **CFG Kanban Crew Compliance Check** containing the
exact policy snapshot, actual crew snapshot, findings, checkpoint, acting Employee, Operator Session,
terminal User, and production references. A failed decision creates or updates a **Crew Compliance
Hold**, blocks the Process Execution, and prevents the requested action. The hold is committed before
the rejection is returned so the safety evidence is not erased by request rollback.

Crew joins, breaks, resumes, leaves, main-operator changes, context changes, and session closure
immediately re-evaluate live executions at that Workstation. A compliant crew automatically resolves
the crew-specific hold and restores the execution's previous state. ERP feedback remains accepted as
the manufacturing system of record; when feedback arrives while crew coverage is invalid, CFG
Kanban withholds its downstream WIP release and records the hold instead of falsifying ERP status.

### P04 acceptance test

1. Leave one Operation without any Crew Requirement and confirm its normal start/progress behavior
   remains unchanged.
2. Apply a submitted requirement needing two direct workers, one assistant, one L2 direct-worker
   skill and one L3 active supervisor authorized to supervise trainees.
3. Try to start without an active Crew Session. Confirm the action is rejected, the Process
   Execution shows Crew Compliance Hold, and one Compliance Check preserves the failed evidence.
4. Open the Crew Session with only the Main Operator. Confirm the hold remains because staffing and
   skill requirements are incomplete.
5. Join a qualified assistant and qualified supervisor. Confirm the hold resolves automatically and
   the execution returns to its prior Ready/In Progress state.
6. Start and report progress. Confirm Pass checks exist for Before Operation Start and Progress.
7. Put the assistant on break. Confirm the execution immediately enters Hold; resume the assistant
   and confirm automatic resolution.
8. Make a direct participant Active in a second Workstation Crew Session. Confirm concurrent direct
   work is rejected.
9. Suspend or expire a required competency and recheck progress. Confirm the authorization no longer
   counts and a new failed Check explains the missing skill coverage.
10. Complete the Job Card and perform its configured handoff. Confirm completion and WIP release are
    separately checked and no downstream WIP is released while a crew hold is active.

### P05 — Employee Job Participation Ledger (implemented)

**CFG Kanban Job Participation** projects each eligible active crew member into a separate interval
for a running Process Execution. A direct participant is recorded as **Production Labour** and a
Senior / Overseer classified as Oversight Only is recorded as **Oversight**. These categories are
never combined into one labour figure.

An interval opens only while the execution is In Progress and the effective crew policy is
compliant. Join, resume, role/category change and compliance restoration open new segments. Break,
leave, crew closure, a crew hold, execution completion or cancellation closes the current segment
and calculates its duration. Historical segments are not rewritten when the workstation crew later
changes.

For an Operation with no effective crew policy and no Crew Session, the authenticated operator who
starts or reports the execution is recorded as an explicit **Authenticated Operator Fallback**.
This preserves existing single-operator operation without inventing a crew roster. Once an active
Crew Session exists, its active Memberships are the participation source.

The ledger contains no produced, good, reject, transfer or WIP quantity. ERPNext continues counting
Job Card output exactly once. The ledger answers only who participated, in which role/category, and
for how long. Use **Execution Records → Employee Job Participation** and filter by Process
Execution, Job Card, Employee, Work Category, or Status.

Use `docs/TEST_WORKFORCE_P05_PARTICIPATION.md` for the complete acceptance procedure.

### P06 — Operator Interface & QR Integration (implemented)

Every Job Card Execution Lane now shows its persistent Workstation crew, main Employee, active and
break counts, compliance state, and a **Crew Controls** action. The same control opens from the
printable `CFG:CMD:CREW` scanner label and follows the panel's current execution priority.

The scanner-first modal supports opening the Crew Session, joining direct/oversight/temporary
members, break, resume, leave, main-operator change, Operation-context change and controlled Crew
Session closure. A crew action command selects the transition; the next scan uses the Employee's
existing operator credential only as crew identity. It never opens a terminal Operator Session or
changes the authenticated operator. Closing the whole crew requires a separate Confirm scan.

Crew Events participate in the Card's lightweight live revision, so a change made from another
authorized terminal refreshes the crew strip and crew-specific holds without rescanning the Card.
Use `docs/TEST_WORKFORCE_P06_OPERATOR_UI.md` for the complete scanner and touch acceptance test.

## P07-0A — Scoped multi-role authority foundation (implemented)

The original Operator / Senior Operator / Supervisor selection remains a compatibility default, not
an Employee job title. **CFG Kanban Authority Role** now defines explicit reusable capability bundles,
and Operator Profiles may hold multiple assignments scoped by Company, Operation, Workstation,
Kanban Responsibility, and effective dates. ERPNext permissions remain independently required.

Production Cards may define multiple workforce requirement rows for Operator-in-Charge, Direct
Worker, Assistant, Supervisor / Mentor, and Verifier assignments. Requirements may combine Job Code,
Authority Role, head count, Skill/minimum competency, independent-versus-supervised policy, active
presence, ownership eligibility, and separate-approver control. Every new Cycle receives an immutable
snapshot. P07-0A deliberately does not enforce or auto-assign these rows yet; the current runtime
continues through the legacy authority fallback until P07-0B is accepted.

Use `docs/TEST_WORKFORCE_P07_0A_MULTI_ROLE_AUTHORITY.md` for migration and live acceptance.

## Remaining approved package

### P07 — Supervisor Control, Reports & Audit

Add workforce traceability, competency expiry, compliance history, trainee supervision, labour
utilization, controlled corrections, and exception reporting. P07-0B must first add runtime role
assignments and exact-action supervisor credential approval using the P07-0A snapshots; it must not
reinterpret the Employee's designation or silently grant permanent Supervisor authority.
