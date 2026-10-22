# CFG Kanban Workforce, Competency & Crew Control

## Status and delivery boundary

This is the approved implementation baseline for packages P01–P07. It extends the existing CFG
Kanban application; it is not a separate app and does not replace ERPNext Employee, Work Order, Job
Card, Operation, or Workstation records.

ERPNext Job Card remains authoritative for production quantities. CFG Kanban records the workforce
authorization, crew presence, participation intervals, scanner interaction, and audit evidence.
Supporting employees must never create duplicate quantity-bearing ERPNext Job Cards or multiply the
reported production output.

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

P01 acceptance proves registry correctness only. Do not expect it to block a Kanban operation until
P04 is implemented and accepted.

## P02 — Crew Requirement Policy

P02 adds approved configuration and a conservative policy resolver. It still does not block operation
start, progress, or completion; the runtime checkpoints remain P04.

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
11. Confirm normal production behavior is unchanged. P04 is still required before crew composition
    or competency can block start, progress, completion, or WIP release.

## Remaining approved packages

### P04 — Authorization Engine

Validate competency, crew size, qualified lead, supervision, concurrency, and expiry before start,
during progress, on crew change, and before completion/WIP release. Loss of required coverage creates
a controlled Crew Compliance Hold.

### P05 — Employee Job Participation Ledger

Automatically project eligible active crew into Employee participation intervals for each Job Card
execution. Production quantity remains counted once by ERPNext; labour and oversight time remain
separate CFG Kanban facts.

### P06 — Operator Interface & QR Integration

Add scanner-first crew actions to the existing Production Operator Panel without replacing the
existing Employee login QR, card commands, terminal User, or operator session security.

### P07 — Supervisor Control, Reports & Audit

Add workforce traceability, competency expiry, compliance history, trainee supervision, labour
utilization, controlled corrections, and exception reporting.
