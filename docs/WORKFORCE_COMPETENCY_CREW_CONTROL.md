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

## Remaining approved packages

### P02 — Crew Requirement Policy

Define single operator, multiple operator, supervised operation, and qualified-lead-plus-assistants
requirements. Effective requirements combine Operation Profile, Workstation restriction, and Card
selection without allowing a lower layer to weaken a safety rule.

### P03 — Workstation Crew Registry

Keep one persistent crew session across successive jobs. Record main, supporting, senior/overseer,
temporary, direct, and oversight membership intervals with explicit join, break, resume, leave, and
main-operator change events.

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
