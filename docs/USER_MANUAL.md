# CFG Kanban Code-Verified Operating Guide

**Application:** CFG Kanban for ERPNext/Frappe v15  
**Guide version:** 2.03

**Updated:** 26 October 2026

**Scope:** Current repository code; Frappe/ERPNext v15

**Canonical file:** `docs/USER_MANUAL.md`

## 1. Purpose of this manual

This guide explains how to configure and operate CFG Kanban from an empty installation through
the first production signal. It covers normal reusable-card replenishment, Sales Order stock
proposals, customer make-to-order production, operation reporting, production Process Tasks,
standalone Service Tasks, controlled QC, private media evidence, printing, handling-unit tags, and
audit records.

It also documents the protected configuration and runtime foundations for the Special DocType
Action extension. That extension is being delivered in serial gates: Gate 1A validates target
metadata and previews a mapped form, Gate 1B adds immutable Action Run and attempt audit records,
Gate 1C adds the controlled server mapper/writer, Gate 1D binds that engine to exact Service Task
events with a truthful closure gate, and Gate 1E supplies the phone/tablet operator form for mapped
parent fields and repeatable first-level child rows. Gate 1F pins authorized private-media registry
references and adds Employee-authorized supervisor recovery without replacing an existing target.
Gate 1G adds an explicit development-only draft/submission pilot so the complete parent/child,
permission, idempotency, evidence, and closure behavior can be accepted before a real target is
allowlisted.

Gate 2A adds the exact reusable **DocType Action Card** configuration and physical identity. It is
deliberately non-production: it has no Kanban Master or quantity and cannot create a Signal, Cycle,
Work Order, Job Card, stock movement, or logistics transaction. Gate 2B adds its scanner resolver
to **Kanban Service Tasks**. A scan only identifies the Card and shows authorized in-progress Runs;
the operator must deliberately choose **Resume** or **Start New Action**. A scan alone never creates
a target document or a new Action Run. Gate 2C adds private photo/file evidence owned by each
immutable direct Action Run, with timestamped/geotagged camera capture and an evidence freeze when
controlled document posting begins.

This file is designed to be usable by a person or by another LLM without access to the development
chat history. When this guide and an earlier chat answer disagree, use this guide for the code
revision in which it is shipped. When this guide and the running ERPNext site disagree, first verify
that the site has pulled this revision, migrated, built assets, and cleared cache; then treat the
running DocType metadata and server code as authoritative.

### How field names are written

Every configuration field is written as **Screen Label** (`internal_fieldname`) where ambiguity is
possible. The Screen Label is what a user normally sees in ERPNext. The internal fieldname is what
an administrator, report author, API client, or LLM should use when inspecting metadata or code.
Do not invent a similarly worded field when the exact label below is absent.

Records described as **system-created** must not be manually created merely to move a workflow
forward. Use the operator page, approval button, ERPNext document action, reconciliation action, or
controlled recovery action identified in this guide.

CFG Kanban is the process-control layer. ERPNext remains the official system of record for Items,
BOMs, Operations, Work Orders, Job Cards, Batches, Stock Entries, stock balances, deliveries, and
accounting.

> **Development-stage warning:** Use the app on a development server first and validate every pilot
> route, task gate, permission, ERP command, and recovery path before production rollout. Delivery
> Note batch enforcement and automatic batch selection in Manufacture Stock Entry are not yet
> implemented.

## 2. Choose the correct production flow first

Do not begin by creating a card. First decide which of these two policies applies.

| Question | Stock Replenishment | Customer Make-to-Order |
|---|---|---|
| Why production starts | Stock falls below a warehouse target or a reusable card is consumed | A particular customer submits an order |
| Quantity | Fixed quantity represented by one or more cards | Sales Order outstanding quantity, optionally including PO-authorized tolerance |
| Existing finished stock | May be considered | Prohibited by policy |
| Reusable card | Required for physical-card flow | Not reserved or consumed |
| Batch | Normal ERPNext batch practice | One dedicated Batch per Sales Order line |
| Order consolidation | May be possible operationally | Prohibited |

Use **Stock Replenishment** for products made repeatedly for inventory. Use **Customer
Make-to-Order** where every order must have its own batch and common expiry date, and unused stock
must not be supplied to that customer.

### Choose the card behaviour separately

Production policy and Card Type answer different questions. Production policy decides *why and how
much* to produce. Card Type decides *what a scan does*.

| Exact Card Type | What scanning it does | Creates a new Work Order? | Required setup |
|---|---|---|---|
| Physical Unit Card | Consumes a reusable replenishment card and creates a Signal/Cycle | Yes, after Automatic or Approval release | Production Master, BOM, warehouses |
| Physical Batch Card | Same trigger model for a batch-sized quantity | Yes, after Automatic or Approval release | Production Master, BOM, warehouses |
| Process Kanban | Selects an eligible open Job Card for the same Item and controlled Operation | No; allocates against an existing submitted Work Order/Job Card | Controlled Operation on Card and matching Operation Profile |
| Station Kanban | Same runtime allocation, restricted to one eligible Workstation | No | Controlled Operation and Eligible Workstation |
| Workstation Queue Card | Shows all operator-authorized active, paused, ready, waiting, and blocked work for one Company and Workstation | Never | Queue Company and Current Station; no Master |
| Asset Card | Finds open standalone Service Tasks for one Asset | Never | Asset; no Master required |
| Location Card | Opens service work, supplier receiving, or a warehouse operations view according to Location Purpose | Never | Location Reference and, for logistics purposes, Current Warehouse; no Master |
| Task Card | Finds open standalone Service Tasks from one Task Schedule | Never | Task Schedule; no Master required |
| DocType Action Card | Reusable identity for a controlled allowlisted DocType Action Profile | Never | Enabled and Valid DocType Action Profile; no Master or quantity |

A Purchase Replenishment, Transfer, or Withdrawal Master uses a **Physical Unit Card** or
**Physical Batch Card**. It never requires a Task Schedule. A **Task Card** is a separate service
identity whose QR is resolved in the **Service Task Panel**; it does not trigger stock movement and
must not be linked to a Kanban Master.

A Process/Station card is a reusable runtime allocation tool. It filters Job Cards by the Card Item,
Master Company, Card Operation, submitted Kanban-controlled Work Order, remaining Job Card demand,
and available upstream input. A Station Kanban adds an exact Workstation match. The system recommends
according to **Runtime Selection Priority**, but an authorised operator may choose another eligible
candidate and must give an Override Reason. One card-sized Cycle is then created for the effective
quantity; it does not mirror every Job Card on that Work Order.

A **Workstation Queue Card** is different: it is a permanent access identity, carries no item or
quantity, and never allocates work by itself. Scan it in the Production Operator Panel to see the
operator-authorized queue for its exact Company and Workstation. Select **Open** on a queue row to
load that row's own production Card and continue through the existing controlled actions.

## 3. Roles and responsibilities

### System Manager

- Installs and migrates the app.
- Maintains CFG Kanban Settings.
- Can configure Masters and perform supervisor approvals.
- Investigates technical failures and ERP Commands.

### Manufacturing Manager

- Creates and maintains Kanban Masters and Cards.
- Approves Signals and Sales Demand proposals.
- Replaces cards and handling-unit tags.
- Reviews and resolves operational Exceptions.

### Manufacturing User

- Uses the Kanban Operator page.
- Reads Signals, Cycles, progress, and exceptions allowed by role permissions.
- Starts or completes linked Job Cards and reports operation progress where authorized in ERPNext.

### Service and Maintenance Supervisor

- Configures Task Schedules, recurrence, Holiday Lists, permanent Service Point QR identities, and
  required evidence.
- Reviews maintenance records and private media evidence.
- Verifies, rejects, cancels, or bypasses task occurrences through controlled actions.

### Kanban Operator Profile roles

The Employee-based profile controls floor actions independently of the shared ERPNext terminal
login. **Operator** performs assigned work, **Senior Operator** may request unplanned Service Tasks,
and **Supervisor** may verify work, authorise QC retests, or apply task dispositions when the
corresponding permission is enabled.

**Kanban Responsibility** is separate from both the authority level above and ERPNext User roles.
Create operational responsibilities such as Housekeeping, Maintenance, Quality, Production,
Warehouse, or Safety in **CFG Kanban Responsibility**. Add one or more to the Operator Profile's
**Responsible Roles** (`responsibilities`) table. Task Schedule **Responsible Kanban Role**
(`responsible_role`) then controls which scanner-only Employees can see an unassigned occurrence.
An occurrence assigned directly to the Employee remains visible. Blank-responsibility tasks remain
generally available within workstation scope. A Supervisor can be scoped to several responsibilities
or enable **View All Service Tasks** (`view_all_responsibilities`). When it is unticked, the
Supervisor sees their own assigned tasks, eligible unassigned tasks, Awaiting Verification work
that they are authorized to verify, and matching active work started by an Operator or Senior
Operator. The latter is marked **Supervisor assist**: the Supervisor can see its live status, review
progress, add progress, and complete it on behalf of the assigned operator. Every added measurement,
note, attachment, completion, and event records the Supervisor's Employee identity; the original
Assigned Employee is preserved. This assistance does not permit the Supervisor to start or take over
an unstarted task, cancel/bypass the occurrence, or operate another Supervisor's assigned task. When
**View All Service Tasks** is enabled, the Supervisor can also fully control work assigned to other
Employees and work across all Kanban Responsibilities. For backward compatibility, an Operator
Profile with an empty Responsible Roles table remains unrestricted for unassigned tasks until
responsibilities are deliberately assigned. It does not grant assistance or control over another
Employee's role-specific assigned work; the Supervisor must hold that explicit Responsibility.

ERPNext permissions still apply. A Kanban role does not automatically grant permission to Items,
BOMs, Work Orders, Job Cards, Stock Entries, Warehouses, or Batches.

### Workforce competency foundation (P01)

**CFG Kanban Skill** defines reusable, skill-specific capability identities and whether certification
or expiry evidence is required. **CFG Kanban Employee Competency** is a submitted manager approval
linking one Employee and their Operator Profile to one Skill at level L0–L4. Level alone does not
grant permission: independent-work and trainee-supervision authorization are explicit controls.

Submitted competency validity is evaluated from approval status, Effective From, Valid Until,
minimum level, and the explicit authorization flags. An expired authorization is ineffective even if
its stored approval status remains Active. Suspending, reactivating, revoking, or cancelling requires
a reason and records the responsible ERP User and timestamp. Revoked records cannot be reactivated.

Open an Operator Profile to see the read-only competency summary or use **Workforce → Employee
Competencies**. This P01 registry does not yet block production actions; crew requirements and
runtime enforcement are delivered sequentially in P02–P04. See
`docs/WORKFORCE_COMPETENCY_CREW_CONTROL.md` for the package boundary and acceptance test.

### Crew requirement policy foundation (P02)

Create and submit **CFG Kanban Crew Requirement Profile** records for approved staffing and
skill-specific safety rules. Available **Crew Mode** (`crew_mode`) values are Single Operator,
Multiple Operators, Supervised Operation, and Qualified Lead + Assistants. Configure **Minimum
Direct Workers** (`minimum_direct_workers`), optional **Minimum Assistants**
(`minimum_assistants`), **Trainee Policy** (`trainee_policy`), **Active Supervisor Presence**
(`supervision_presence`), **Maximum Trainees per Supervisor**
(`max_trainees_per_supervisor`), and the **Required Skills** (`skill_requirements`) table.

Apply the approved Profile at one or more levels: **Normal Crew Requirement**
(`crew_requirement_profile`) inside the Kanban Master's Operation Profile, submitted **CFG Kanban
Workstation Crew Requirement** records for equipment restrictions, and optional **Additional Crew
Requirement** (`crew_requirement_profile`) on Process or Station Cards. The resolver combines every
applicable rule conservatively; a Card cannot lower an Operation or Workstation safety minimum.

P02 is configuration and policy resolution only. It deliberately does not block an operator yet.
P03 supplies the persistent actual Workstation crew and P04 compares that crew with this effective
policy at every controlled runtime checkpoint.

### Persistent workstation crew registry (P03)

Create and submit **CFG Kanban Crew Template** only when a Workstation commonly uses the same named
team. Select Company, Workstation, optional Operation, and the expected Employees with their normal
roles: Main Operator, Supporting Operator, Senior / Overseer, or Temporary Support. Classify each as
Direct Participation or Oversight Only. A template must have exactly one direct Main Operator.

A template is not attendance. Opening a **CFG Kanban Crew Session** stores an immutable snapshot of
the expected roster but initially registers only the authenticated operator who opened it. Every
helper must still scan their own existing Employee/Operator Profile QR to join. The helper scan only
identifies that Employee; it does not log the helper in as the terminal operator and does not grant
the helper or main operator any additional action permission.

One active Crew Session persists for a Company and Workstation across successive production jobs.
Do not close and recreate it for every Card. Live membership is stored in **CFG Kanban Crew
Membership** with explicit Active, On Break, and Left intervals. **CFG Kanban Crew Event** preserves
Open Session, Join, Break, Resume, Leave, Change Main Operator, operation-context change, and Close
Session evidence with the acting Employee, terminal User, and Operator Session.

P03 exposes the authoritative actual crew to the P04 server authorization engine. Scanner buttons
and command labels for crew changes are delivered in P06; until then, the registry endpoints and
audit records form the controlled server backbone.

### Crew authorization and compliance holds (P04)

When an approved effective Crew Requirement exists, CFG Kanban checks the active Workstation crew
before runtime allocation, operation start, progress, completion, and WIP release, and after every
crew change. Only Active Memberships count; an Employee on break does not. The check covers minimum
direct workers and assistants, required skills and competency levels, explicit independent or
supervisor authorization, qualified lead, trainee policy and ratio, competency expiry, and one-
Workstation-at-a-time direct participation.

A failed check creates a persistent **Crew Compliance Hold** on the Process Execution and rejects the
requested floor action. Open **Execution Records → Crew Compliance Checks** to see the immutable
effective-policy snapshot, actual-crew snapshot, findings, checkpoint, acting Employee, terminal
User, and production references. Correct the actual crew or competency record; the next crew change
or controlled action rechecks coverage, resolves the crew-specific hold, and restores the prior
execution state when compliant.

An Operation with no effective submitted Crew Requirement remains backward-compatible and does not
require a Crew Session. ERPNext remains the Work Order/Job Card quantity system of record. If ERP
feedback arrives while the crew is non-compliant, CFG Kanban records the hold and withholds the
downstream WIP release; it does not alter or duplicate ERP quantity evidence.

Use `docs/TEST_WORKFORCE_P04_AUTHORIZATION.md` for the complete sample data, temporary pre-P06 crew
control calls, expected results, evidence checklist, and cleanup procedure.

### Employee Job Participation Ledger (P05)

When a Process Execution is In Progress, **CFG Kanban Job Participation** records a separate timed
interval for every eligible active person at that Workstation. Direct Participation becomes
**Production Labour**; Oversight Only becomes **Oversight**. A crew join or resume opens an interval.
A break, departure, role/category change, compliance hold, execution completion, or cancellation
closes it and stores the duration. Restoring compliant coverage opens new intervals for the active
crew instead of rewriting the earlier evidence.

For backward-compatible Operations with no effective Crew Requirement and no active Crew Session,
the authenticated operator who starts or reports the execution is recorded as an explicitly marked
Authenticated Operator Fallback. If a Crew Session exists, actual active Memberships are used.

Open **Execution Records → Employee Job Participation** and filter by Process Execution, Job Card,
Employee, Work Category, or Status. Participation rows contain no production quantity: ERPNext
still owns the Work Order and Job Card result, and adding three crew members never triples good
quantity. Direct labour duration and oversight duration remain separate facts. Use
`docs/TEST_WORKFORCE_P05_PARTICIPATION.md` for the full sample test.

### Scanner-first Workstation Crew control (P06)

Every Job Card Execution Lane in the Production Operator Panel shows a **Workstation Crew** strip.
It identifies the persistent Crew Session's Main Operator, active/break counts, and current crew
compliance. Select **Crew Controls**, or scan the printable `CFG:CMD:CREW` command, to manage the
crew for the panel's current execution.

To work without a mouse, scan a Crew action command first and then scan the affected Employee's
normal operator QR. Supported actions are Open Crew, Join Direct, Join Oversight, Join Temporary,
Start Break, Resume, Leave, Change Main Operator, Use Current Operation and Close Crew. Close Crew
requires a separate Confirm scan. Cancel closes the modal without converting the next scan into a
Card scan.

The Employee scan inside Crew Controls is identity evidence only. The terminal remains signed in as
the current operator, every crew mutation carries that authenticated Operator Session and ERP
terminal User, and helpers receive no terminal permissions. A submitted Crew Template may be chosen
as an expected-roster snapshot, but its people are not present until each one scans to join.

Crew changes are included in the production Card's live revision. An authorized change from another
terminal refreshes the lane and resolves or creates its crew hold without a Card rescan. Operations
with no approved effective Crew Requirement remain backward-compatible, while attendance may still
be recorded. Use `docs/TEST_WORKFORCE_P06_OPERATOR_UI.md` for the complete test.

## 4. ERPNext prerequisites

Complete these records before configuring CFG Kanban:

1. **Company** — the production company.
2. **Warehouses** — source/raw-material, WIP, and finished-goods destination warehouses.
3. **Item** — a stock Item with the correct Stock UOM.
4. **BOM** — active and default where appropriate, with the required materials and Operations.
5. **Operations and Workstations** — in the same sequence used by the BOM.
6. **Manufacturing permissions** — users must be able to access the ERPNext records their work
   requires.

For a batched MTO product, also configure the Item as follows:

- **Has Batch No:** enabled.
- **Shelf Life in Days:** set to the customer/product requirement.
- **Default BOM:** set and valid.

For stock-based Sales Order proposals, add a warehouse row under **Item → Reorder** and set the
**Warehouse Reorder Level** for the same warehouse used as the Master's Destination Warehouse.

## 5. Open the CFG Kanban workspace

From ERPNext Desk, open **CFG Kanban** in the sidebar. The workspace is organized into:

- **Daily Operator Work:** separate Production Operator and Service Task panels.
- **Production Supervisor:** visual Signal approval centre, production floor, dispatch sequence,
  cycles, demand, and production exceptions.
- **Service & Maintenance Supervisor:** service tasks, schedules, maintenance register, and
  compliance evidence.
- **System Setup:** Masters, Cards, operator profiles, dashboard profiles, and global settings.
- **Detailed Records & Audit:** production execution, WIP, ERP documents, operator sessions, and
  event history.

The separate **CFG Job Architecture** workspace appears under **CFG Kanban** after migration. Use it
for the implemented workforce and shared-execution foundation: operator identity, skills,
competency approvals, crew policy, live crew membership, authorization checks, Employee Job
Participation, Cycles, Process Executions, operation results, Events, and Exceptions. It is a
separate manager/auditor navigation surface inside the same app; it does not duplicate data or
introduce a second permission model.

The workspace deliberately does not show EODR, payroll export, a general capacity ledger, or
TrackQMS integration as completed features. Those remain controlled future packages. Their data
model must not be added merely to fill the workspace, and any conflict with the existing CFG Kanban
records requires an explicit product decision before implementation continues.

The operator interface is available at:

```text
/app/kanban-operator
```

The manager-facing visual approval queue is available at:

```text
/app/kanban-supervisor
```

Open the workspace **Production Signals** shortcut to enter the **Kanban Supervisor Action
Centre**. Its Signal cards show company, priority, Item, Card demand in Stock UOM, supplier-order
quantity in Purchase UOM where applicable, supplier/BOM, warehouses, Cycle status, waiting time,
and any retry error. Manufacturing Manager, Purchase Manager, or System Manager may approve an
eligible card after confirmation. Approval creates the controlled Work Order or Material Request;
it does not replace the ERPNext document. **Cancel** uses the existing audited safe rollback and
requires a reason. Blocked Signals remain visible but cannot be approved until their blocking issue
is resolved.

The same page summarizes Service Tasks and production Process/QC Tasks awaiting verification and
open Exceptions. Verification still takes place through the corresponding Service or Production
operator panel because it requires an Employee-based Kanban supervisor session and independent
verifier identity. The Action Centre refreshes every 30 seconds; the conventional Signal list
remains available through **Open Signal List** for audit and advanced filtering.

Standalone housekeeping, maintenance, inspection, safety, and emergency work is available at:

```text
/app/kanban-tasks
```

The operator can identify themselves directly in either console by QR credential or credential/PIN.
Both consoles reuse the same Employee-based operator session; the shared ERP terminal login is not
changed. The Production, Service Task, and Logistics panels also share that browser-stored operator
session across parallel tabs. If an operator logs in or switches identity on one tab, select
**Refresh Session** on Production or **Refresh** on Service/Logistics to deliberately adopt that
latest identity. Refreshing operational data never signs the ERPNext terminal user out. A stale tab
cannot delete a newer session created in another tab.

### Live production-card updates and current-work navigation

After a production Card is scanned, the Production Operator Panel checks a lightweight change
revision approximately every 12 seconds. Supervisor approval, Cycle release, Job Card/operation
status, Process Task, ERP command, Work Order, and production Stock Entry changes therefore appear
without rescanning the Card. The complete Card context is downloaded only when that revision changes.

The compact sticky **Current action** strip shows **Connecting**, **Live**, **Checking**, or a retry
warning, followed by the next operator-actionable floor step. The guide follows process gates,
material shortage, the first incomplete operation's material issue or consumption, Draft ERP
material scanning/submission, Start, Report Progress, Job Card completion, WIP-bin consumption,
finished-goods receipt, and Cycle closure. A general Work Order warning is only a fallback when no
operator floor action is available. **Go to current work** scrolls directly to the exact operation,
task, Job Card material row, or Stock Entry action instead of sending a normal operator to the Work
Order link. When an external update changes actionable work, the panel flashes, shows a short update
alert, and normally scrolls to the new current action.
It preserves the operator's position instead when they recently touched or manually scrolled the
screen. Automatic checking also pauses while a dialog is open and resumes when the page is visible.
The first check always re-synchronizes the displayed Card context before accepting its revision
baseline. Therefore an approval completed while the operator tab was hidden or blocked by a dialog
cannot be silently absorbed as the baseline while leaving the old waiting-for-approval screen.
Use **Refresh** on the Current action strip for an immediate check; scanning remains available at all
times. Scanner focus is restored invisibly after live navigation without moving the page back to the
scanner field, so the operator remains at the selected current-work block.

On short or tablet-sized Production terminals, the sticky header uses a single compact
operator-and-station row. The Employee name remains prominent, the Station stays visible beside it,
and repeated scanner guidance and Current-action detail text are collapsed. Scanner state, the next
action title, **Go to current work**, and Refresh remain available without occupying most of the
working area. Before an operator is identified, **Scan Operator with Camera** is displayed directly
in this scanner header; it does not depend on finding the Desk page-menu action.

When a separate Process or Station Kanban Card reports against a Job Card belonging to an open
Production Card, ERPNext remains the quantity authority. The Production Card mirrors the cumulative
Job Card quantity into its own execution lane and Operation Result without writing the quantity back
to ERPNext again. Digital handoff quantities are released incrementally into the Production Cycle,
so dependent operations can become ready. **Overall route progress** shows cumulative progress across
all configured operations, completed-operation count, and the final operation's output separately.

### Operation work, production Process Tasks, and maintenance Tasks

These are different records and must not be used interchangeably.

| Work type | Use it for | Configured from | Operator interface | Official result |
|---|---|---|---|---|
| **Production Operation / Job Card** | Work that transforms material or reports manufactured quantity, such as cooking, filling, packing, or cartoning | ERPNext BOM Operation plus the Kanban Master's Operation Profile | **Production Operator Panel** | ERPNext Job Card, operation quantity, Work Order status, and Kanban progress/WIP records |
| **Production Process Task** | A non-quantity prerequisite or control that belongs to a production Cycle, such as pre-operation sanitation, line clearance, quality release, or post-cleaning | Process Task Profile inside the relevant **CFG Kanban Master** | Production Operator Panel for the active Cycle | CFG Kanban Process Task linked to the Cycle; it can block a configured production gate |
| **Standalone Service/Maintenance Task** | Independent housekeeping, preventive maintenance, inspection, safety, environmental, vehicle, or emergency work | **CFG Kanban Task Schedule**; no Kanban Master is required | **Service Task Panel** | CFG Kanban Task, structured checklist/measurement evidence, verification stamp, and maintenance reports |

Use this decision rule:

1. If the work produces or confirms production quantity, use an **ERPNext Operation/Job Card**.
2. If it does not produce quantity but must control a particular production Cycle, use a
   **production Process Task**.
3. If it exists independently of production, use a **standalone Service/Maintenance Task**.

Do not create an ERPNext Job Card for cleaning or inspection merely to obtain a task record. Do not
use a standalone maintenance Task to release production; a production Process Task must be linked to
the Kanban Master and Cycle for that control.

## 6. Initial system settings

Open **CFG Kanban Settings**. This is a Single DocType. Its explicit DocType permission is
**CFG Kanban System Maintenance**; the role is created by the app installation/migration hook.

Recommended pilot configuration:

| Screen label (`fieldname`) | Recommended starting value | Meaning |
|---|---|---|
| Enabled (`enabled`) | Yes | Global configuration flag; it is not a complete kill switch in every API |
| Default Company (`default_company`) | Production company | Default business context |
| Default WIP Warehouse (`default_wip_warehouse`) | Pilot WIP warehouse | Intermediate production location |
| Default FG Warehouse (`default_fg_warehouse`) | Pilot FG warehouse | Completed-product location |
| Default Automation Level (`default_automation_level`) | Approval | Options: Automatic, Approval, Signal Only |
| Allow Manual WO for Kanban Item (`allow_manual_wo_for_kanban_item`) | No initially | Policy flag against bypassing Kanban |
| Require Manual Override Reason (`require_manual_override_reason`) | Yes | Preserves exception reasons |
| Auto-submit Work Order (`auto_submit_work_order`) | No initially | When enabled, the created Work Order is submitted by the ERP gateway |
| Auto-start Job Card (`auto_start_job_card`) | No initially | When enabled, starts the selected Job Card when runtime production begins |
| Auto-submit Job Card at Target (`auto_submit_job_card`) | No initially | Submits only after verified completed quantity reaches the full Job Card target |
| Enable WIP Ledger (`enable_wip_ledger`) | Yes | Enables quantity handoff records |
| Enable Dynamic Forms (`enable_dynamic_forms`) | Yes | Enables Master/Schedule-defined fields |
| Operator Session Inactivity (Minutes) (`operator_session_timeout_minutes`) | 15 | Ends inactive operator sessions |
| Enable Administrator Operator Bypass (Development Only) (`enable_administrator_operator_bypass`) | No | Literal Administrator only; never enable for production |
| Command Retry Limit (`command_retry_limit`) | 3 | Retry policy value; full retry orchestration is not complete |
| Exception Email Role (`exception_email_role`) | Manufacturing Manager | Intended audience; full email automation is not complete |

Private media fields are also maintained here: **Enable Private Media Storage**
(`enable_private_media`), **Environment** (`media_environment`), **AWS Region**
(`media_s3_region`), **Private S3 Bucket** (`media_s3_bucket`), upload limits, allowed MIME types,
retention class, optional KMS ARN, and upload/view authorization lifetimes. AWS credentials are
intentionally absent; the server must use its workload/instance role.

Save the Settings before creating the pilot Master.

### Special DocType Action foundations (Gates 1A through 1F)

This is a system-maintenance function, not a production operator function. Only **System Manager**
or **CFG Kanban System Maintenance** can maintain its configuration records.

1. Create **CFG Kanban DocType Action Policy** for a deliberately approved operational target.
   Select **Approved Target DocType** (`target_doctype`), enable **Allow Create / Save Draft**
   (`allow_create`), and enable **Allow Submit When Authorized** (`allow_submit`) only if the real
   target is submittable and that future action has been reviewed.
2. Core ERP manufacturing, stock, accounting, payroll, User/permission, and system-configuration
   records are hard-denied even if an administrator attempts to add a policy. Existing dedicated
   Kanban integrations remain the only path for those records.
3. Create **CFG Kanban DocType Action Profile** and choose its allowlisted **Target DocType**
   (`target_doctype`). Configure **Parent Field Mappings** (`parent_field_mappings`), flat **Child
   Table Configurations** (`child_table_configs`), and flat **Child Column Mappings**
   (`child_column_mappings`). Nested child-table configuration is not supported.
4. Choose mapping fields from the target's live effective metadata. Supported first-pass value
   types are Data/text, Int, Float, Currency, Check, Select, Date, Datetime, and validated Link.
   Hidden, read-only, system identity/status, Dynamic Link, Attach, Code, HTML, Button, and nested
   Table fields are not accepted as writable values.
5. Select **DocType Action → Validate Configuration**. Validation checks the current allowlist,
   target submission capability, mandatory parent/child fields, Link/fixed values, row limits,
   safe JSON conditions, and a target-metadata fingerprint. Only then may **Enabled** (`enabled`)
   be selected. A material profile edit increments **Configuration Revision**
   (`configuration_revision`), disables the profile, and requires revalidation.
6. Select **DocType Action → Preview Operator Form** to inspect the parent fields and first-level
   child-row layout. The preview never creates a destination record.

#### Non-posting Action Run foundation (Gate 1B)

Gate 1B adds two **system-created** records:

- **CFG Kanban DocType Action Run** is the durable identity for one source occurrence, Action
  Profile and `primary` action slot. It pins **Profile Revision** (`profile_revision`), **Mapping
  Snapshot** (`mapping_snapshot`) and **Mapping Snapshot Hash** (`mapping_hash`), and separately
  records the acting **Initial Operator Employee** (`operator_employee`) and shared **Terminal
  User** (`terminal_user`).
- **CFG Kanban DocType Action Attempt** is immutable history for create, resume, state transition,
  retry, cancel and reconciliation attempts. Raw retry tokens are never stored; only a one-way
  hash is retained.

The source **CFG Kanban Task** has a read-only **DocType Action Run**
(`doctype_action_run`) link. **CFG Kanban Event** also links relevant events to the Action Run.
Both record lists are available in **CFG Kanban Workspace → Execution Records**.

Action Runs cannot be created or edited manually. A Supervisor with `can_override` authority may
open an existing run and use **Recovery → Cancel Run with Reason** only before any destination is
linked, or **Recovery → Mark Needs Reconciliation**. These actions require a current scanned
Supervisor session from the Service Task Panel and preserve an immutable attempt/event trail.
Submitted, externally linked, uncertain or already terminal results are never silently deleted or
cancelled.

#### Controlled target mapper/writer (Gate 1C)

Gate 1C adds the protected server operation that turns one authorized Action Run into at most one
destination record. It is intentionally not a generic ERP transaction endpoint:

- the destination DocType and mapped fields come only from the immutable validated snapshot on the
  Action Run; the browser cannot choose a target or add unmapped fields;
- `Operator Input`, `Service Task Field`, `Server Context`, and `Fixed Value` sources are resolved
  again on the server and converted using current target metadata;
- parent fields and one level of child-table rows enforce mapped columns, safe visibility/trigger
  conditions, mandatory values, Select/Link validity, text limits, and configured row limits;
- **Save Draft** and **Submit When Authorized** are separate policies. Creation, write and submit
  use the authenticated terminal User's normal Frappe permissions and the target controller's
  normal validation. The engine never bypasses destination permissions;
- the validated input snapshot and its hash are retained on **CFG Kanban DocType Action Run** as
  **Form Payload** (`form_payload`) and **Form Payload Hash** (`form_payload_hash`), together with
  **Last Input By** (`last_input_by`) and **Last Input On** (`last_input_on`);
- retries use an opaque one-use token, reuse the same linked draft, and never create a second target
  for the same Run. A missing, externally submitted/cancelled, or uncertain target is moved to
  **Needs Reconciliation** rather than silently recreated;
- a false configured trigger is recorded as **Skipped by Condition** without creating a target.

The terminal User still needs deliberately reviewed Create permission on the approved destination,
plus Write/Submit permission when the selected policy requires those actions. Granting access to an
Action Profile does not grant access to its destination DocType.

#### Service Task event binding and closure gate (Gate 1D)

Gate 1D adds an optional binding to **CFG Kanban Task Schedule**:

- **DocType Action Profile** (`doctype_action_profile`) selects one enabled, Valid Action Profile;
- **DocType Action Trigger** (`doctype_action_trigger`) is exactly **On Task Start**, **On Task
  Complete**, or **After Supervisor Verification**;
- **DocType Action Required** (`doctype_action_required`) decides whether the destination result
  must succeed before the task may advance to its intended completion/verification status.

Each generated **CFG Kanban Task** snapshots those three values. Editing the schedule later does
not rewrite open occurrences. At the configured event, the server creates or resumes the one
primary Action Run and every resulting Task event retains its **DocType Action Run** link.

Safety checks reject these premature combinations:

- **On Task Start** may use only an Action Profile with **Save Draft** posting policy;
- a profile whose **Verification Policy** is **Require Service Task Verification** must be paired
  with **Require Supervisor Verification** and **After Supervisor Verification**;
- a schedule requiring supervisor verification cannot use **Submit When Authorized** at **On Task
  Complete**. Submission must wait for the verification event.

For a required action, the Task becomes **Pending Document Posting** instead of falsely showing
Completed or Awaiting Verification. **Save Draft** is satisfied only by `Draft Created` (or a later
submitted result); **Submit When Authorized** is satisfied only by `Submitted`; a deterministic
false condition is satisfied by the audited `Skipped by Condition` result. The controlled writer
then releases the Task to its stored next status. Failed, unresolved or reconciliation-required
runs leave the Task pending. Supervisor Cancel/Bypass also routes an unposted linked Run through
its controlled cancellation rules rather than deleting its audit.

#### Service Task mapped document form (Gate 1E)

At the exact configured Start, Complete, or Verify event, the **Kanban Service Tasks** panel now
opens the mapped document form automatically. It shows the Service Task, Action Run, fixed
destination DocType and posting policy; an operator cannot choose a different destination.

- mapped parent fields use the administrator's **Operator Label** and approved type/options;
- operator-entered parent fields and repeatable observation fields use the same direct control
  renderer. This keeps Data, Select, and Notes controls genuinely editable on Frappe v15 while
  preserving server-context and explicitly read-only fields as display-only values;
- read-only values resolved from the Service Task, Employee, server context, or fixed configuration
  are visible but cannot be changed;
- structured JSON **Visible Condition** rules react to parent and row values without executing
  arbitrary JavaScript;
- each configured first-level child table appears as mobile-friendly numbered row cards. **Add Row**
  and **Remove** follow the configured row policy and minimum/maximum limits;
- **Save Document** means the profile policy is **Save Draft**. **Submit Document** appears only
  for **Submit When Authorized**. The authenticated terminal User must still have the normal target
  Create/Write/Submit permission and every destination controller validation still runs;
- the form reuses one opaque retry token after an uncertain browser/network result, so pressing the
  action again cannot create a second target. A controlled validation failure displays in the same
  dialog and permits a corrected retry;
- a successful Draft, Submitted, or conditionally skipped result releases a required Task gate.
  Failed or unresolved results remain **Pending Document Posting** and show **Complete Required
  Document** on the Task card;
- an Action Run in **Needs Reconciliation**, **Posting**, **Cancelled**, or an already successful
  state is displayed truthfully without offering another create/submit action. A linked target is
  identified and may be opened only if the terminal User has normal Desk access.

If **After Supervisor Verification** creates the Action Run, the verifying Employee can finish that
exact form even after the Task changes status. This resume right is limited to the immutable Run and
the Employee's allowed Workstation; it does not grant visibility to unrelated Tasks or Actions.

#### Private evidence and supervised recovery (Gate 1F)

When a Service Task Action is posted, the system snapshots every currently **Available** private
media object belonging to that exact Task occurrence. **CFG Kanban DocType Action Run** records
**Evidence Reference Count** (`evidence_reference_count`), **Evidence Snapshot On**
(`evidence_snapshot_on`), and **Stable CFG Kanban Media References** (`evidence_references`). These
are stable registry IDs and safe metadata only. The binary remains in private S3 under **CFG Kanban
Media**; no expiring view URL is copied into the Action Run or destination document.

The mapped operator form shows **Linked Private Evidence** before posting. Select **Open Evidence**
to request a short-lived authorized view URL. Evidence must already be confirmed `available`, use
the `maintenance-evidence` class, and belong to the same **CFG Kanban Task**. Pending, archived,
unrelated, or direct client-supplied media IDs are not linked.

The **Kanban Supervisor Action Centre** now includes **Document recovery** and a **Document Action
Recovery** queue for Runs in `Posting`, `Failed`, or `Needs Reconciliation`. The queue is an
attention view; recovery itself requires the Supervisor to open **Kanban Service Tasks** and use a
current scanned Supervisor profile with Override authority.

Inside the existing mapped document form, expand **Action attempt history** to review the sanitized
attempt timeline. A Supervisor may use only these controlled recoveries:

- **Return to Form** is available only when no target document exists. It keeps the same Action Run
  identity and returns it to `Form In Progress`; it never creates a replacement Run.
- **Recheck Linked Target** is available only when the exact target link already exists. It reads
  that document's real ERPNext `docstatus`. A submitted target reconciles to `Submitted`; a draft
  reconciles to `Draft Created`. For **Submit When Authorized**, that same draft may then be reopened
  and submitted—never recreated.

A missing or cancelled linked target remains under reconciliation. Every recovery requires notes,
an opaque retry token, the Employee identity and terminal User, and creates an immutable Attempt
and Event. If the target is valid but the Task gate cannot be released, the Run returns to **Needs
Reconciliation** rather than falsely completing the Task.

Gate 1F completed the Service Task parent/child data entry, stable private-media references, and
Employee-authorized supervisor recovery foundation. Gate 1G below supplies the controlled live
pilot targets needed to accept those paths before direct Action Cards are introduced.

#### Gate 1 live pilot fixtures (Gate 1G)

Gate 1G supplies two harmless app-owned destination records in the isolated **CFG Kanban Pilot**
module:

- **CFG Action Pilot Draft** is not submittable and proves the `Draft Created` path;
- **CFG Action Pilot Submission** is submittable and proves the `Submitted` path;
- both use **CFG Action Pilot Observation** to prove repeatable child-row mapping.

Nothing is automatically allowlisted during install or migrate. A System Manager or
**CFG Kanban System Maintenance** user opens the **CFG Kanban DocType Action Profile** list and
selects **Install Gate 1 Pilot**. This explicitly creates/restores the two named policies and Valid
profiles **CFG Gate 1 Pilot - Draft** and **CFG Gate 1 Pilot - Submit**. The normal shared terminal
User must hold the **Kanban Terminal** ERPNext role; the engine still performs the target's normal
Create/Write/Submit checks.

The complete independent acceptance procedure, sample values, expected states, negative cases,
evidence check, and recovery check are in
[`docs/TEST_GATE1_DOCTYPE_ACTION_PILOT.md`](TEST_GATE1_DOCTYPE_ACTION_PILOT.md). A code deployment
does not itself complete Gate 1: both live-site pilots must pass, and one Run must produce exactly
one linked target containing the expected parent values and child rows.

#### Reusable DocType Action Card operation (Gate 2B)

Use a direct Card only for an independent occurrence that does not require a generated Service Task.
Its Action Profile must use **No Additional Verification** and must not contain a **Service Task
Field** mapping. Use **Operator Input**, **Server Context**, or **Fixed Value** mappings instead.
New direct profiles may use the protected Server Context keys `source_name` or `card_number`.

1. Identify the Employee in **CFG Kanban → Kanban Service Tasks**.
2. Scan the saved Card's QR or enter its exact **Card Number** in the scanner field.
3. Review the fixed Card, Action Profile, destination DocType and posting policy.
4. If the occurrence already exists, select **Resume** beside its Action Run. Do not use Start New.
5. Select **Start New Action** only for a genuinely new business occurrence. This explicit action
   creates a fresh opaque Run identity and opens the same controlled mapped form used by Service
   Tasks.
6. Complete the form and save/submit. The target still uses the authenticated terminal User's
   normal ERPNext permissions and controller validation.

Closing the form before posting leaves the Run in progress. Scan the same Card again and select
**Resume**; the same Run and any persisted form result are reused. Repeated transport retries reuse
the same opaque request token and cannot create a second Run or destination document. A completed
**Save Draft** occurrence appears as `Draft Created`; a completed submit occurrence appears as
`Submitted`. A Supervisor with Override authority can see recent completed history and open linked
targets, while a normal operator sees only their own in-progress Runs. Another operator cannot open
an Employee's Run merely by knowing its name.

The reusable Card itself remains `Available` throughout. It never gains a Cycle or production
quantity. Direct-card evidence is deliberately not inherited from the reusable physical Card,
because that would mix files between separate occurrences. Instead, the form for each direct Run
shows **Action Run Private Evidence**:

- **Take Timestamped Photo** captures a new image, applies visible server time plus device GPS, and
  uploads it directly to private S3;
- **Upload Photo / PDF / File** accepts multiple existing files without altering their contents;
- **Remove** archives an accidental file while retaining its registry audit record, but only before
  document posting starts;
- **Open Evidence** requests a short-lived authorized view URL; no signed URL is stored;
- posting waits until every initiated upload is confirmed, then snapshots only `Available`
  `doctype-action-evidence` registry IDs and locks the Run evidence set permanently.

Closing the form before posting does not move these files to the reusable Card. Resume the same Run
to see them again. Starting a new occurrence creates a new empty Run evidence area. Manufacturing
Manager, CFG Kanban System Maintenance, and System Manager users with read access may open the
**CFG Kanban DocType Action Run** record to review its direct-media thumbnail gallery. Service Task
actions remain different: their evidence belongs to the exact generated Task occurrence and is
pinned from that Task when its Action posts.

The independent live test is in
[`docs/TEST_GATE2_DOCTYPE_ACTION_CARD.md`](TEST_GATE2_DOCTYPE_ACTION_CARD.md).

**Current Gate 2C boundary:** Gate 2B direct Card form operation and Gate 2C per-Run private media
have passed live-site acceptance. The repeatable procedure remains in
[`docs/TEST_GATE2C_DOCTYPE_ACTION_MEDIA.md`](TEST_GATE2C_DOCTYPE_ACTION_MEDIA.md). A direct
**DocType Action Card** can be configured, validated, replaced, printed, scanned and used to Resume
or Start separate Action Runs without entering any production lifecycle.

The runtime trigger uses the **Master's Automation Level** (`automation_level`). `Automatic`
creates/executes the Work Order command immediately only when the Before Cycle Start gate is open.
`Approval` creates a Waiting Approval Signal. In the current code, `Signal Only` also remains
Waiting Approval and can still be released through the same manager approval action; it is not a
hard technical prohibition against Work Order creation. Treat the distinction as policy until a
separate Signal-Only release restriction is implemented.

## 7. Guided setup: create the first stock-replenishment Kanban

Use one test product and one simple route. Do not start with multiple products.

### Step 1 — Create the Kanban Master

Open **CFG Kanban Master → New** and complete:

| Screen label (`fieldname`) | Example | Guidance |
|---|---|---|
| Kanban Name (`kanban_name`) | Chili Sauce 500 ml – FG Loop | Clear loop name, not only Item code |
| Active (`active`) | Yes | Only active Masters should be used |
| Company (`company`) | Your company | Must match BOM and warehouses |
| Item (`item_code`) | Finished Item | Item controlled by the loop |
| BOM (`bom`) | Active BOM | Required for production Work Orders |
| Control Type (`control_type`) | Production | Production creates Work Orders; Purchase Replenishment creates buying demand; Transfer creates a same-Company Movement Manifest; Withdrawal creates a controlled Material Issue without a Work Order |
| Card Representation (`card_representation`) | Batch | Options: Unit, Batch, Container |
| Replenishment Qty (`replenishment_qty`) | 400 | Nominal quantity represented by a card |
| Stock UOM (`stock_uom`) | Nos | Item/BOM stock unit |
| Number of Cards (`number_of_cards`) | 2 | Planned physical identities |
| Source Warehouse (`source_warehouse`) | Raw-material/source | Work Order source |
| WIP Warehouse (`wip_warehouse`) | Production WIP | ERP manufacturing WIP location |
| Destination Warehouse (`destination_warehouse`) | Finished Goods | Finished output/stock target warehouse |
| Automation Level (`automation_level`) | Approval | Automatic, Approval, or Signal Only |
| Default Priority (`default_priority`) | Normal | Low, Normal, High, or Urgent |
| Allow Partial Output (`allow_partial_output`) | As required | Loop policy |
| Use ERP BOM Operations (`use_erp_bom_operations`) | Yes | ERPNext route remains authoritative |
| Revision (`revision`) | 1 | Increase when controlled design changes |

The Replenishment Qty is the card quantity. It is not the warehouse minimum stock level.

### Step 2 — Add operation profiles

Add one row for every controlled operation, in sequence. For example:

```text
10 Cooking
20 Bottling
30 Cartoning
```

Important profile fields:

| Screen label (`fieldname`) | Purpose |
|---|---|
| Operation (`operation`) | ERPNext Operation used by BOM/Job Card |
| Sequence (`sequence`) | Unique route order |
| Workstation (`workstation`) | Preferred workstation |
| Reference Operation Time (Minutes) (`time_in_mins`) | Standard reference duration |
| Mandatory (`mandatory`) | Whether operation is required |
| Execution Mode (`execution_mode`) | Single Workstation, Parallel Workstations, or Sequential Split |
| Runtime Selection Priority (`runtime_selection_rule`) | Oldest WO First, Smallest Remaining First, or Largest Remaining First |
| Interruption Policy (`interruption_policy`) | Controls supervisor pause/give-way behaviour |
| Setup Family (`setup_family`) / Cleaning Class (`cleaning_class`) | Required for compatible-item interruption checks |
| Dependency Operation (`dependency_operation`) | Upstream operation controlling readiness |
| Start Rule (`start_rule`) | Previous complete, quantity/percentage/full-batch threshold, or no dependency |
| Minimum Qty (`minimum_qty`) / Minimum Percentage (`minimum_percentage`) | Applicable start threshold |
| Output Reporting Mode (`output_reporting_mode`) | Completion Only or Incremental |
| Handoff Mode (`handoff_mode`) | Physical Card, Digital Quantity, Full Batch, or Automatic |
| Transfer Multiple (`transfer_multiple`) | Smallest digital release increment |
| Require Destination Scan (`require_destination_scan`) | Requires destination confirmation where used |
| Destination Operation (`destination_operation`) | Downstream Operation |
| Completion Rule (`completion_rule`) | Full Qty, Operator Complete, or Threshold |

`Allow Parallel` (`allow_parallel`) still exists as a hidden legacy compatibility field. Configure
new Masters with **Execution Mode** rather than looking for a visible Allow Parallel checkbox.

Handoff modes:

- **Full Batch Handoff:** downstream waits for the complete upstream batch.
- **Digital Quantity Handoff:** reported good quantity is released in Transfer Multiple increments.
- **Physical Card Handoff:** a card scan creates the handoff ledger entry.
- **Automatic Handoff:** reserved for controlled automatic behavior; validate on the pilot before use.

Example pilot:

| From | To | Recommended handoff |
|---|---|---|
| Cooking | Bottling | Full Batch Handoff |
| Bottling | Cartoning | Digital Quantity Handoff; transfer multiple = carton size |
| Cartoning | FG | Full Batch Handoff |

### Step 3 — Add dynamic operator fields

Use **Operator Field Definitions** for process information not represented by standard ERPNext Job
Card fields. Example Cooking fields:

```text
Field Key: cooking_temperature
Label: Cooking Temperature
Field Type: Float
Mandatory: Yes
Unit: °C
Minimum Value: 85
Maximum Value: 95
Capture On: Progress
```

Rules:

- Field Key should be stable, lowercase, and use underscores.
- Select options must be one option per line.
- Select **Applies To = Operation** for Job Card execution fields or **Process Task** for a
  production prerequisite/post-task field, then select the corresponding operation or Task Key.

### Step 4 — Add production Process Task Profiles when required

Use Process Task Profiles for work that belongs to a production Cycle but does not produce quantity,
such as machine preparation, sanitation, line clearance, quality verification, and post-cleaning.
Choose the gate it blocks, the responsible workstation/asset, checklist, verification requirement,
and optional validity duration. Do not add a fake ERPNext Operation or Job Card for this work.

For a reusable sanitation or preparation result, enable **Reuse While Valid** and enter its validity
hours. The system reuses only a still-valid completion matching the configured Master and applicable
asset/workstation. A supervisor can invalidate valid completions when an operational event makes the
earlier result unsafe to reuse.

For cycle-specific quality checks, enable **Controlled QC Task** and configure:

- **Enable Sample Traveller QR** when the physical sample needs its own scannable identity.
- **Test Method** and **Specification Reference**. These are required for controlled QC.
- Dynamic Process Task fields for actual measurements and acceptance limits.
- **Allow Conditional Release** only where an approved procedure permits supervisor disposition.
- Independent supervisor verification when the task is a release gate.

Controlled QC results cannot be reused across production cycles. The outcome behaves as follows:

| Result | System action |
|---|---|
| Pass | Completes the task, or waits for verification when configured |
| Fail | Blocks the Process Task, places the Cycle on Hold, and creates a critical Exception |
| Conditional Release | Available only when configured and always waits for independent verification |

After a failure, a Supervisor can select **Authorise Retest** and must record the corrective action
or reason. The previous sample, readings, checklist, disposition, exception, and authorisation are
retained in the QC attempt history before the task returns to Ready. The production hold is cleared
only after the controlled QC path is satisfied and no failed QC task remains.

Every generated Process Task has a printable **Process Task QR**. A QC task may additionally print
a **Sample Traveller QR**. Open the saved **CFG Kanban Process Task** and use **Print Process Task
QR** or **Print Sample Traveller**. Scanning either identity in the Production Operator Panel loads
the owning card and exact task. Always confirm the prominently displayed Item, Batch, Cycle, Work
Order, and Operation before entering results.

### Optional — Configure standalone Service/Maintenance work

Create a **CFG Kanban Task Schedule** for independent housekeeping, maintenance, inspection, vehicle,
safety, environmental, or emergency work. Add checklist and dynamic fields using
**Applies To = Standalone Task**. Time Interval and Calendar Schedule records are generated by the
hourly scheduler. Meter, condition, emergency, and manual triggers create tasks through the controlled
request action/API.

For automatic recurrence, confirm the ERPNext scheduler is enabled for the site. A schedule cannot
generate tasks while the site scheduler is disabled or paused.

#### Optional permanent Service Point QR

The Service Point QR is optional. Use it for a stable physical location or asset—such as a toilet,
machine, inspection point, or utility room—where scanning should locate the current occurrence.
Tasks still generate and remain usable from the Service Task Panel when no QR is enabled.

To configure and print one:

1. Open the saved **CFG Kanban Task Schedule**.
2. Enable **Permanent Service Point QR**.
3. Set at least one Location, Asset, or Workstation.
4. Save and reload the schedule.
5. Select **Print Service Point QR**.
6. Fix the printed QR at the controlled location.

The permanent QR identifies the Schedule/location, not one individual occurrence. Scanning it in
the Service Task Panel resolves the oldest current open occurrence. If none exists and the schedule
is due, the server creates the due occurrence idempotently. If it is not yet due, the panel reports
the next due time and does not create an early task.

Use **Recurring Task Overlap Policy** deliberately:

- **Prevent While Open** keeps one actionable occurrence until completed or disposed. This is the
  normal choice for routine cleaning and maintenance.
- **Allow Parallel Occurrences** preserves every scheduled occurrence independently.

For holidays, select **Skip Listed Holidays** and an ERPNext Holiday List. The scheduler advances
the recurrence and records a skip event without creating the holiday occurrence. If an occurrence
was already generated, an authorised Supervisor may select **Cancel / Bypass**:

- **Cancelled** means the occurrence should not be performed, for example because the site closed
  for a public holiday.
- **Bypassed** means an approved operational exception satisfied the control another way.

Both require a reason and preserve the record. Do not delete generated task history.

Operators use **Kanban Service Tasks** to start, complete, and—when separately authorized—verify the
work. These tasks never create or update an ERPNext Work Order, Job Card, or Stock Entry.

The Service Task Panel does not show every task indiscriminately. It excludes Completed, Cancelled,
and Bypassed occurrences. If the Operator Profile has Allowed Workstations, only tasks at those
Workstations are returned; a task with no Workstation remains eligible because it is not
workstation-specific. Responsibility, assignment, and Workstation access are applied before the
panel's 200-task display limit, so other teams' tasks cannot displace an operator's eligible work.
Every operator sees their own assigned tasks plus eligible unassigned tasks. A Supervisor also sees
matching active tasks started by an Operator or Senior Operator as **Supervisor assist**, even when
**View All Service Tasks** is unticked. Matching means the task passes both the Supervisor's
Responsible Roles and Allowed Workstations. If the Supervisor Profile has **Can Complete**, this
scoped access exposes **Report Progress** and **Complete** so a Supervisor who joins the work or
closes it after operator negligence can record the real outcome. The Assigned Employee remains the
operator, while progress and completion attribution identify the Supervisor. Another Supervisor's
assigned task remains hidden.
**View All Service Tasks** grants controlled operation of other Employees' tasks, while Awaiting
Verification remains available to a Supervisor authorized to verify it. Starting an unassigned task
assigns it to the starting Employee. Ordinary assigned work cannot be started, progressed,
completed, cancelled, or bypassed by another operator without the controlled Supervisor setting.

The Service Tasks page is optimized for phones and tablets rather than a fixed barcode terminal.
Both operator pages contain a prominent panel switch: **Open Service Task Panel** on the Production
Operator page and **Production Panel** / **Open Production Operator Panel** on the Service page.
They share the active operator-session token stored on that terminal, so an identified operator can
move between panels without scanning the credential again while the session remains valid.
The scanner and active-operator identity form a sticky header and remain visible while the operator
scrolls. Immediately below it, **Active Work** contains tasks already started and assigned to that
Employee. Starting a task reloads the panel, moves the task from **Ready / Open Tasks** into Active
Work, and scrolls to that section. Active tasks are ordered with the most recently updated first.
A Supervisor sees active operator work available for Supervisor assistance, authorized verification work, and—when
**View All Service Tasks** is enabled—other controllable assigned work separately under
**Supervisor Attention**. They are not mixed into the Supervisor's own active work.
The three behavioral sections use consistent visual meaning: a green-tinted block for Active Work,
a blue-tinted block for Ready / Open Tasks, and an amber-tinted block for Supervisor Attention.
Each individual task card repeats that contrast with a matching border, surface tint, and an
**ACTIVE WORK**, **OPEN TASK**, or **SUPERVISOR VIEW** chip. This remains identifiable after the
section heading scrolls away. Colors indicate operational state and do not replace written status.

On the Service Task Panel, **Scan Task QR with Camera** is the primary task-selection action and is
shown beside the Task/Card number field. **Find Task / Card** and **Show All** form a slimmer second
row. The number field remains available as a desktop or scanner-keyboard fallback; operators are
not expected to type Task IDs routinely. The active-operator **Switch** and **End Session** controls
are compact and side by side. **Production Panel**, **Refresh**, and **Scan / Switch Operator** share
one compact navigation row, while **Create Task** remains a separate prominent action.
On phone-sized screens the sticky scanner/operator header is deliberately compressed to roughly one
quarter of the usable viewport. Repeated scanner guidance is reduced to a single status line, while
**Scan Task QR with Camera**, the active Employee name, and **Switch Operator** remain prominent.
Find, Show All, and End Session remain available as smaller secondary controls.

The Service Task Panel performs a lightweight live revision check every 15 seconds while it is
visible. It does not reload the page or repeatedly rebuild the task list when nothing changed. If a
Supervisor approves, rejects, requests correction, or another operator updates an occurrence, the
panel refreshes the affected task view in place, preserves the current task filter and scroll
position, and shows a blue live-update alert. Checks pause while an operator dialog is open and
resume when the tab becomes visible again, so checklist or measurement entry is never interrupted.
The panel rechecks those protections after every background response. If a popup opens, the
operator scans/types, a frozen transaction starts, or the active credential changes while a check
is already in flight, that response is discarded without rendering or advancing the revision
marker; the next safe check retries it. Live refresh never moves focus back to the main scanner.
Background checks do not extend the operator inactivity timeout; an expired session still requires
the operator credential.

Large touch controls for **Refresh**, **Scan / Switch Operator**, **Create Task**, and panel switching
appear after Active Work and before the ready queue. Each task is displayed as a separate touch card
with prominent **Start**, **Report Progress**, **Complete**, **Correct and Resubmit**, or **Verify**
actions according to its status. Urgent and high-priority work has a colored card edge. On a phone,
task forms use the full screen with a sticky action footer so the final action remains accessible
after scrolling through instructions and checklists. The operator can explicitly switch identity or
end the shared session from the active operator banner.

Work instructions, completion checklist, measurements, and notes are presented as separate sections.
Dynamic fields use their exact **Capture On** stage: Start appears in the Start dialog, Progress in
**Report Progress**, Complete in the completion dialog, and Verify in the independent verification
dialog. A task must be started before Progress can be reported. Every Progress submission is kept as
a separate timestamped measurement row. The task card shows **Progress Reports**, the latest
operator/time and latest summary. **View Progress** opens all timestamped Progress measurements and
notes, including while the task is still In Progress, so a Supervisor can monitor work before
completion. Completion is blocked until every mandatory Progress field has at least one valid
recorded value. Mandatory Check fields must be checked; zero remains valid for mandatory numeric
fields. A mandatory read-only definition must have a Default Value or the Schedule cannot be saved.

When **Require Supervisor Verification** is enabled, completion moves the Task to **Awaiting
Verification**. A different authorized employee must approve it. Rejection requires remarks and
moves it to **Correction Required** for correction and resubmission.
The assigned operator then sees the Supervisor's remarks on the task card and in the correction
dialog and uses **Correct and Resubmit**. The previous checklist, completion answers, and notes are
prefilled so only the rejected evidence needs editing. Numeric and Check answers are stored as stable
text values in the evidence child table, which preserves Frappe version history across the second
completion submission. The rejected verification remarks remain in the audit Event history; the
corrected submission returns to **Awaiting Verification** for a fresh independent decision.

Completed evidence is available from **Kanban Maintenance Register** and **Kanban Maintenance
Evidence**. The register provides one row per service record; the evidence report provides one row
per checklist result or dynamic value so variable forms remain exportable. Use **CFG Verified
Maintenance Record** when printing a Task for certification evidence and its completion/verification
stamp.

### Private photo, video, and document evidence

When private media storage is configured, Service and Process Task dialogs separate live capture
from ordinary upload:

- **Take Timestamped Photo** is available only after the task is **In Progress**. It opens the
  device camera, requires location permission, and renders server time, Task ID, GPS latitude and
  longitude, and reported accuracy visibly onto the photograph. The same proof is retained as
  structured media metadata.
- **Upload Photo / PDF / File** accepts multiple allowed JPEG, PNG, WebP, MP4, or PDF files. These
  existing files are uploaded unchanged and are not represented as live execution captures.

The binary uploads directly to the configured private S3 bucket. The task dialog shows the media
only after the server verifies the object and marks its metadata available. Multiple evidence files
may be attached to the same task.

Supervisors see the same evidence during verification. **Maintenance Register** includes the number
of available media records, and **Maintenance Evidence** includes Media rows linked to **CFG Kanban
Media**. Opening a media record requests a new short-lived private view URL; URLs are never stored.
Archiving removes evidence from normal task/report views without physically deleting retained S3
objects.

Use **Remove** for an accidentally attached photo or file. Removal is recoverable: it archives the
media registry record and hides it from active views but retains the private object and audit trail.
During verification, supervisors can see thumbnails, open the original file through a short-lived
URL, and review the recorded capture time and GPS coordinates.

Media storage is configured in **CFG Kanban Settings → Private Media Storage** by Administrator or
a user assigned **CFG Kanban System Maintenance**. AWS access keys are never entered in ERPNext;
the server uses its approved IAM workload role. If media is disabled or
incomplete, checklist and measurement evidence continue to work, but media upload reports a
configuration error. See
`docs/SHARED_MEDIA_STORAGE.md` for the required non-secret configuration names and ownership rules.

> A timestamp/GPS watermark documents the server confirmation time and device-reported location.
> It supports operational evidence but does not replace an approved calibration, chain-of-custody,
> or certification procedure where one is legally required.

Dynamic fields are displayed according to their configured capture stage:

- **Start:** pre-work condition or initial reading.
- **Complete:** work result, final reading, and completion evidence.
- **Verify:** an independent verifier's measurement or confirmation.

- Numeric minimum and maximum values are validated by the server.
- Mandatory fields must be supplied in the operator progress dialog.
- `Map to Job Card` and `Job Card Field` describe intended mapping, but generic automatic mapping to
  arbitrary Job Card fields is not yet complete.

Save the Master. Duplicate operation sequence numbers are rejected.

### Step 4 — Create the physical cards

Open **CFG Kanban Card → New**. Create the number of cards defined by the Master.

Complete:

| Screen label (`fieldname`) | Guidance |
|---|---|
| Kanban Master (`kanban_master`) | Required for production card types |
| Card Number (`card_number`) | Unique visible identifier, for example `CDL-001` |
| Card Type (`card_type`) | Use one exact option described below |
| Item (`item_code`) | Filled from Master for production cards |
| Kanban Qty (`kanban_qty`) | Normally Master Replenishment Qty |
| Controlled Operation (`operation`) | Required for Process Kanban and Station Kanban |
| Eligible Workstation (`workstation`) | Required only for Station Kanban |
| Asset (`asset`) | Required only for Asset Card |
| Location Reference (`location_reference`) | Required only for Location Card |
| Task Schedule (`task_schedule`) | Required only for a standalone service Task Card; leave it out of Purchase, Transfer, and Withdrawal cards |
| DocType Action Profile (`doctype_action_profile`) | Required only for DocType Action Card; the profile must be enabled, Valid, and backed by an approved target policy |
| Queue Company (`queue_company`) | Required only for Workstation Queue Card |
| Current Station (`current_station`) | Required only for Workstation Queue Card |
| Location Purpose (`location_purpose`) | General Service Point, Supplier Receiving, or Warehouse Operations |
| Current Warehouse (`current_warehouse`) | Required for Supplier Receiving and Warehouse Operations Location Cards |
| Active (`active`) | Yes |
| Revision (`revision`) | Start with 1 |

Exact **Card Type** (`card_type`) options are: `Physical Unit Card`, `Physical Batch Card`,
`Process Kanban`, `Station Kanban`, `Workstation Queue Card`, `Asset Card`, `Location Card`, and
`Task Card`, and `DocType Action Card`. The first four card types are Master-backed operational cards; their Master Control
Type decides whether the Card controls Production, Purchase Replenishment, Transfer, or Withdrawal.
Workstation Queue, Asset, Location, Task, and DocType Action cards are permanent identities without a
Kanban Master. A DocType Action Card also carries zero Kanban quantity and stays `Available`; each
separate Action Run owns its own immutable lifecycle.
**Card Behaviour** (`card_behavior`), current state, QR, UUID, active Cycle, handoff mode, and most
location/status fields are derived or system-maintained.

UUID and QR Code are generated by the server if left empty. Do not copy a QR identity from another
card.

### Step 5 — Print and verify the card

Open any saved Card linked to a Kanban Master. Use the visible **Print Card with QR** action for the
single-sided operational format, or use **Print Kanban** for either format:

- **Print Standard Card:** reusable A6 landscape, two pages for front and reverse instructions.
- **Print Operational Card:** reusable A6 landscape, single-sided operational version.

For Standard Card on A4 stock, select four pages per sheet and duplex printing in the printer
dialog. Always test front/back orientation before a production print run.

The first print increments Print Count. Every reprint requires a reason and creates an Event.

For permanent access cards use their specific saved-card print action:

- **Workstation Queue Card:** Print Kanban → Print Workstation Queue Card.
- **General Service Point Location Card:** Print Kanban → Print General Service Location Card.
- **Supplier Receiving Location Card:** Print Kanban → Print Supplier Receiving Location Card.
- **Warehouse Operations Location Card:** Print Kanban → Print Warehouse Operations Card.
- **DocType Action Card:** Print Kanban → Print DocType Action Card (CR80 horizontal).

Only **System Manager** or **CFG Kanban System Maintenance** may issue a new DocType Action Card.
Its linked profile cannot be changed after creation. Disable the card if the physical identity must
stop working; use **Replace Card Identity** for a controlled replacement with audit history. A
direct Card profile cannot require Service Task verification or use Service Task Field mappings;
the Card is rejected during save when either Task-only dependency is present.

### Step 6 — Trigger the first replenishment

Use either method:

1. Open **Kanban Operator**, scan the QR code or enter the Card Number, then select **Consume /
   Trigger**; or
2. Open the Card and use **Kanban Actions → Consume / Trigger**.

Expected result:

```text
Card: Available → Consumed → Signal Created
Cycle: New → Signalled
Signal: Waiting Approval
```

Repeated submission with the same request identity does not create another chain. A card with an
Active Cycle returns the existing Cycle and Signal.

### Step 7 — Approve and create the Work Order

Open the Signal and select **Approve and Create Work Order**. This action requires Manufacturing
Manager or System Manager.

Expected result:

```text
Card: Signal Created → Replenishment Requested → Production Released
Signal: Validated → Executing → Completed
ERP Command: Pending → Running → Completed
Cycle: Signalled → Released
ERPNext: one Work Order created
```

If Auto-submit Work Order is disabled, review and submit the Work Order in ERPNext. ERPNext then
creates the Job Cards according to its BOM and manufacturing rules.

## 8. Production operation workflow

When ERPNext creates Job Cards, CFG Kanban mirrors matching BOM Operations into **CFG Kanban
Process Execution** records. Operations missing from the Master profile are not mirrored.

### Configure material movement and consumption

ERPNext still owns every material transfer, consumption, and finished-goods receipt. CFG Kanban
adds a controlled floor workflow around ERPNext's native Work Order and Job Card mappings.

On a Production **CFG Kanban Master**, configure these exact fields:

| Screen label (`fieldname`) | Meaning |
|---|---|
| Production Material Mode (`production_material_mode`) | Selects native Work Order transfer, operation-specific Job Card transfer, direct consumption without WIP, or legacy ERPNext-following behavior |
| Material Transfer Posting (`material_transfer_posting_mode`) | Keeps each Material Transfer for Manufacture in Draft for review, or submits it after operator confirmation |
| Manufacture Receipt Posting (`manufacture_posting_mode`) | Keeps the Manufacture entry in Draft for Batch/tag review, or submits it after operator confirmation |
| BOM Component Material Flow (`material_flow_rules`) | Read-only BOM Item/Operation snapshot plus the controlled source Warehouse for every component |

Selecting a submitted BOM automatically synchronizes **BOM Component Material Flow**. New, removed,
or operation-reassigned components follow the selected BOM immediately; matching Source Warehouse
selections are preserved. Set the actual source Warehouse on every row. Use **Production Material →
Refresh BOM Material Flow** for an explicit refresh when reviewing an older Master.

For `Transfer to WIP by Job Card`, ERPNext's BOM **With Operations** must be enabled and every BOM
Item row must have **Item Operation**. Expand each BOM Item row to see that field. It means “this
component is first required by this operation”; the Operation table alone does not assign materials
to Job Cards. CFG Kanban deliberately refuses to guess this relationship.

#### Optional restricted/secret BOM components

When the site provides **Hidden Item Settings**, CFG Kanban follows its existing User allow-list
without importing or depending on the customization app. Administrator and Users listed in that
setting see the complete BOM material mapping. Other users see only permitted components; the
Master editor and Operator Panel show a neutral restricted-material notice instead of the Item
identity, warehouse, quantity, or stock balance.

Restricted components are not removed from ERPNext. Work Orders, Job Cards and native Stock Entry
mappers still include them server-side. During a Kanban material transfer or Manufacture receipt,
ERPNext retains their mapped quantities and Warehouses while the operator confirms only visible
components. If a restricted component lacks an Item Operation, Source Warehouse, or sufficient
stock, the operator receives a generic attention message and an authorized material controller must
correct it. An unauthorized user cannot change a restricted component mapping or switch a Master
between BOMs containing restricted components.

If **Hidden Item Settings** is not installed, all components behave normally and no additional setup
is required.

The four modes behave as follows:

| Production Material Mode | Floor behavior |
|---|---|
| Follow ERPNext BOM / Work Order | Preserves the Work Order's native transfer policy. Existing Masters remain compatible; loaded component source rules are still applied. |
| Transfer to WIP by Work Order | **Prepare WIP Transfer** appears once for all required materials. Submit that ERP entry before starting a Job Card. |
| Transfer to WIP by Job Card | **Prepare Operation Materials** appears per Job Card and contains only BOM components assigned to its Item Operation. Submit that operation's transfer before starting it. |
| Skip WIP Transfer | No WIP transfer is made. When the Work Order is configured against Job Cards, **Consume Operation Materials** creates a native Draft `Material Consumption for Manufacture` for the selected operation. ERPNext posts that entry against the Work Order; CFG Kanban preserves the exact operation owner in **Kanban Material Job Card**. Work Order scope uses **Consume Work Order Materials**. The final Manufacture entry consumes only the remaining inputs and receives output. |

#### Standard-quantity reusable WIP bins — configuration and audit foundation

Some workstations use a physically dimensioned bin or tray whose full condition is an immediate
visual quantity check. CFG Kanban keeps this separate from an unrestricted loose or mixed bin.
Create each permanent physical identity as **CFG Kanban Handling Unit** with:

- **Tag Kind** (`tag_kind`) = `Reusable Container`;
- **Reusable Container Role** (`reusable_container_role`) = `Standard Quantity WIP Bin`;
- the exact owning **Inventory Company** (`inventory_company`); and
- the actual ERPNext **Current Warehouse** (`current_warehouse`) used as WIP.

When physical bins in the same pool have different capacities, add the applicable Item under
**Full-bin Capacities by Item** (`wip_bin_capacities`) on each Handling Unit. Enter the exact
**Full-bin Qty** (`full_bin_qty`); Stock UOM is copied from the Item. For example, configure Bin A
as RW-MATERIAL = 1 Unit and Bin B as RW-MATERIAL = 2 Units. Capacity is configuration, not live
stock, and cannot be changed while that bin has an active load or an Open reconciliation.

Then create **CFG Kanban WIP Bin Pool** for one Company, Operation, and WIP Warehouse, and add the
approved physical bins with each bin's Workstation. This supports one Operation running at two or
more parallel workstations without allowing a scanned bin to drift between them. One physical bin
can belong to only one pool. A standard WIP bin cannot allow mixed Item/Batch content, and a
logistics container with loaded Stock Tags cannot be converted into a WIP bin.

On the Kanban Master's **BOM Component Material Flow**, the optional fields are:

| Screen label (`fieldname`) | Meaning |
|---|---|
| WIP Presentation (`wip_presentation_method`) | Keeps the existing ERP/tag workflow or selects the visually controlled reusable-bin model |
| WIP Bin Pool (`wip_bin_pool`) | Approved physical bins for the component's exact BOM Item Operation |
| Fallback Qty per Full Bin (`standard_bin_qty`) | Optional backward-compatible capacity used only when the scanned bin has no active Item-specific capacity; leave it at zero only when every active bin in the Pool has an Item-specific capacity. This is not the total BOM/ERP row requirement |

The bin selection is valid only with `Transfer to WIP by Job Card`, and its Company, Operation, and
WIP Warehouse must match the Master. Different BOM component rows may use different presentation
methods in the same Work Order. For example, Flour can use a standard-quantity WIP bin while Water
and Oil remain on `Standard ERP / Tag Flow`. Only the explicitly selected Item/Operation component
uses the bin model.

At runtime, the ERP transfer row remains the total requirement. If that row requires 3 Units and
the operator scans Bin A (capacity 1) followed by Bin B (capacity 2), CFG Kanban allocates 1 then 2
and completes the row at 3. A full bin using its configured capacity is not a partial-bin exception.
The Master fallback applies only to legacy or unconfigured bins. A deliberate under-fill still
requires the existing Supervisor partial-bin authorization and reason.

This release also installs the system-created **CFG Kanban WIP Bin Load** audit record. Each record
is one immutable load episode and snapshots the physical bin, Item, Batch, standard/actual quantity,
Cycle, Work Order, Job Card, Operation, Workstation, source/WIP Warehouses, operator session, and
native transfer/consumption Stock Entries. A Draft transfer may reserve the bin, but the load can
become `Ready` only from submitted ERPNext `Material Transfer for Manufacture` feedback. Likewise,
it can become `Consumed` and the physical bin can become `Empty` only from submitted ERPNext
production-consumption feedback. Cancelling a linked ERP entry produces a visible reversal or
Exception state; it does not erase the episode.

The Draft transfer scanner is now available inside **Production Material Trace**. For each fixed-bin
row, select the numbered ERP material row, scan the source Stock Tag when required, and then scan
the Empty reusable WIP bin. If the Item permits an optional physical input tag, scanning
`CFG:CMD:NO_SOURCE` explicitly uses ERP-only source stock. The system reserves exactly **Qty per Full
Bin** from a larger source tag; for example, loading a 10 kg bin from a 25 kg tag leaves 15 kg on
that source tag after ERPNext submits the transfer. A Draft allocation can be cancelled and releases
its source reservation. Only submitted ERPNext transfer feedback deducts the reserved source-tag
quantity and marks the load/bin `Ready`; cancellation restores it through an auditable reversal.
The Material Trace dialog remains open after the source-tag scan so the same operator can scan the
destination WIP bin. Scanner Enter/Tab cannot dismiss the dialog, and clicking outside it has no
effect. Close it deliberately with its close control or `CFG:CMD:CANCEL`. This command only exits
the current Material Trace window; after the window finishes closing, focus is restored to the main
Operator **Scanner Ready** field. It does not reverse material already loaded into the Draft.
Use **Release Loaded Material** on an ordinary Draft material line to release that staged tag. Use
**Cancel Loaded Material** on a `Transfer Draft` or `Consumption Draft` WIP-bin row to reverse that
specific allocation while keeping Material Trace open. A transfer cancellation releases its source
reservation and returns the reusable bin to `Empty`; a consumption cancellation removes the bin
from the Draft consumption and restores it to `Ready`. These row actions remain bound after the
table refreshes and display a success message before the refreshed state is shown.
The Scanner Ready field captures Enter/Tab before the surrounding modal can handle it. If the next
different tag or command arrives while the source scan is still completing, it is retained and
processed immediately afterward instead of being silently discarded.
If a scanner does not transmit its configured Enter/Tab suffix, the completed code is automatically
accepted after a short scanner-input pause. This fallback applies equally to commands, source Stock
Tags, and reusable WIP-bin codes; the visible code must not remain idle in the Scanner Ready field.

After the submitted transfer makes one or more loads `Ready`, the exact Job Card shows **Record WIP
Bin Use**. Scan each Ready bin once; do not scan its original source tag. CFG Kanban records the
physical use as `Consumption Pending ERP` without creating a Stock Entry, allowing that operation
and its card to close while later Work Order operations continue. **Undo Use** restores a mistaken
unposted record to Ready. As soon as that same owning Job Card is submitted and complete, use
**Prepare ERP Consumption**. CFG Kanban creates the native operation-owned Draft, automatically
binds the already-recorded bins, and exposes **Submit ERP Entry**. It checks only the owning
operation; a later operation neither enables nor blocks it. Only submitted ERPNext feedback changes
stock and makes the bin Empty (or starts its controlled unused-material return).

When the actual quantity used is lower than the prepared quantity, use the same visible quantity
control used for partial loading, or scan `CFG:QTY:MATERIAL:<quantity>` before scanning the Ready
bin. In this consumption context the field is labelled **Actual Quantity Consumed**; it never
rewrites **Actual Load Qty**. Enter a **Consumption Adjustment Reason**. If the Pool has **Require
Full-bin Consumption** disabled, this is a normal operator-reported actual. If it is enabled, a
lower quantity is accepted only when **Allow Supervisor Partial-bin Exception** is also enabled and
the active QR belongs to a Kanban Supervisor with Override permission. `CFG:CMD:FULL_BIN` clears the
reported adjustment and restores consumption of the full prepared quantity.

When **Submit ERP Entry** is scanned or selected, CFG Kanban reduces the native Draft `Material
Consumption for Manufacture` rows to the sum of the reported actual quantities before ERPNext
submits them. For every affected bin the immutable audit therefore retains three separate values:
prepared, consumed, and unused return. If unused quantity exists, submission creates a second Draft
native `Material Transfer` from the WIP Warehouse back to that load's original source Warehouse.
The bin becomes `Return Draft` / `In Use`, not Empty. Select or scan **Submit Materials** again to
submit the visible **Confirm Unused Material Return** entry. Only that submitted ERP return makes
the bin `Consumed` / `Empty`; when the original load came from a Stock Tag, its returned quantity is
restored to that source tag from ERP feedback. This preserves the physical and accounting sequence:
prepared to WIP, actual use consumed, unused balance returned.

After that unused-material return is submitted, the accepted return quantity is also treated as a
resolved actual-use variance when CFG Kanban prepares or submits the final native `Manufacture`
entry. ERPNext may otherwise map the returned balance again as an outstanding input because it was
not consumed. CFG Kanban removes only the quantity supported by the same Cycle's `Consumed` WIP Bin
Load and submitted return Stock Entry. The returned material is therefore not requested for a
second production-input scan and is not consumed twice. Any other outstanding input row retains its
normal ERPNext stock and physical-tag requirements. An existing Draft Manufacture entry is repaired
by this same check when it is submitted after the upgrade.

While the consumption is still Draft, **Current Trace Lines** deliberately displays all three
quantities instead of calling the complete prepared bin quantity consumed: **Prepared**, **Actual
Used**, and **Unused Return**. Treat **Actual Used** as the amount that will be posted when the
consumption entry submits; **Prepared** remains the immutable physical load audit value.

An incorrect Draft scan can be cancelled and the bin returns to `Ready`.
The fixed scanner may use either the persistent **Scanner Ready** field or the visible **Ready
Reusable WIP Bin** field. The direct field reads the browser's completed scan before allocation, and
any scan that falls back to the underlying Production scanner while Material Trace is open is
redirected into the same Material Trace workflow instead of being treated as a Kanban Card.

If the component normally requires a production-input Stock Tag, that policy is enforced when the
source material is allocated into the WIP bin. At consumption, the matching Ready WIP-bin scan is
the physical input evidence; the system does not require a duplicate ordinary input-tag allocation
for the same Stock Entry row. Every prepared bin represented by the Draft must be scanned. The
consumption row itself is then finalized to actual use, rather than falsely forcing the consumed
quantity to equal the quantity originally prepared.

ERPNext v15 permits its native Stock Entry **Job Card** field on `Material Transfer for
Manufacture`, but not on `Material Consumption for Manufacture`. Consumption therefore remains a
native Work Order transaction. CFG Kanban writes the operation owner to the read-only **Kanban
Material Job Card** (`cfg_kanban_job_card`) field and uses it for operation-card visibility,
duplicate-draft protection, WIP-bin matching, and consumed-quantity calculation. This is an audit
bridge, not a replacement for ERPNext stock authority.

Report the operation's completed quantity before preparing the consumption. ERPNext requires the
operation Job Card to complete before it accepts the matching production consumption. Therefore,
when **Auto-submit Job Card at Target** is enabled, reaching the target submits the Job Card while
its WIP-bin loads are `Ready`, `In Use`, or `Consumption Draft`. Only a `Transfer Draft` load or an
Open WIP-bin reconciliation defers Job Card submission.

For a sequential Work Order, ERPNext also validates a native `Material Consumption for
Manufacture` submission against every operation supporting the reported finished-good quantity.
The first operation therefore follows a two-stage close without waiting at the workstation:

1. Complete the Job Card and create its operation-owned consumption Draft.
2. Scan every Ready WIP bin. Each load becomes `Consumption Draft`; this is the immutable physical
   use record for that Job Card.
3. Close the operation Kanban Card/Cycle. The panel shows **ERP Posting Pending**, but the first
   operator is released for the next job.
4. The physical bin remains `In Use` and cannot be loaded again while ERP stock is unposted.
5. After every Work Order Job Card is Completed, submit each visible operation-owned consumption
   Draft. A successful ERP submission changes the load to `Consumed` (or `Return Draft` for unused
   balance) and releases the bin only after the required return is also submitted.

CFG Kanban checks both levels before enabling that submission: every Job Card header must be
`Completed`, and every native Work Order Operation row must show at least the quantity required by
the consumption Stock Entry. A Completed Job Card whose Work Order Operation quantity has not yet
updated is not treated as ERP-ready. The panel shows **ERP Work Order operation update required**
with the exact row, operation, completed/required quantity, and related Job Card instead of sending
an entry that ERPNext will reject.

This separation never represents the Draft as posted ERP stock. The final Manufacture receipt
remains unavailable until every related load is fully resolved, so operation closure cannot bypass
stock, costing, trace, or unused-material return controls.

Do not prepare the final Manufacture receipt while any WIP-bin load remains `Transfer Draft`,
`Ready`, `In Use`, `Consumption Draft`, or `Return Draft`. The Operator panel displays the blocking bin and keeps
**Prepare Manufacture Receipt** unavailable until the native Material Consumption entry is
submitted. If an older deployment already created a premature Draft Manufacture entry, select
**Discard Premature Draft**, record the reason, consume and submit the Ready bin through its exact
Job Card, and then create a new Manufacture receipt. The recovery discards only the unsubmitted ERP
draft; it preserves the WIP-bin load and the audit trail. If a Material Trace is already attached,
an authorized supervisor must discard that Draft trace first. Events previously linked to the
unposted Stock Entry keep its exact document number in audit notes and are relinked to the retained
ERP Command before the Draft Stock Entry is deleted.

Normal operation still uses full bins. A partial load is available only when **Allow Supervisor
Partial-bin Exception** is enabled on the exact Pool and the active operator QR belongs to a
Kanban **Supervisor** with **Override** permission. In Production Material Trace, scan a material
quantity command such as `CFG:QTY:MATERIAL:5`, confirm the mandatory exception reason, then scan
the source tag (when required) and Empty WIP bin. The quantity must be positive, below **Qty per
Full Bin**, and no more than the remaining ERP row quantity. The Load permanently records its
standard and actual quantities, reason, approving Employee, terminal ERP User, operator session,
and approval time. Downstream Job Card consumption uses that exact approved actual quantity.
`CFG:CMD:FULL_BIN` clears partial mode. Keep this Pool option disabled unless the physical
verification and supervisor exception procedure are approved.

Full consumption needs one successful ERPNext consumption submission to change the load to
`Consumed` and return its physical bin to `Empty`. Partial consumption first changes it to
`Return Draft`; the separate successful unused-material return submission completes the load and
empties the bin. The Job Card is blocked only by `Transfer Draft` or Open reconciliation;
`Ready`, `In Use`, and `Consumption Draft` loads permit Job Card completion. An operation Kanban
Card may close after every Ready bin is scanned and only valid `Consumption Pending ERP` or
`Consumption Draft` loads remain.
The Draft, its physical bin, and ERP stock remain visibly pending until that operation's own Job
Card is complete and the entry is submitted. The next operation is released by the completed
progress sequence, not by this material-posting status. Manufacture receipt remains blocked while
the Work Order has any unconsumed load. Cancelling a submitted transfer or consumption puts
the bin in `Exception`, creates a Critical Kanban Exception, and creates an Open **CFG Kanban WIP
Bin Reconciliation** rather than silently claiming that the physical bin is empty. The red recovery
block appears on the main Production Card and only on the matching Operation Card. A scanned
Kanban Supervisor with **Override** permission must rescan the affected bin and choose one factual
outcome. For a cancelled consumption:

- **Material Restored to Bin** — physically verify the exact Item, Batch and full reversed
  quantity. The original Load remains `Reversed`; a separately linked recovered Load becomes
  `Ready` and the bin returns to `Ready` for normal rescanning.
- **Bin Empty after ERP Correction** — first post a separate native ERPNext Stock Entry that
  removes the exact Item, Batch, Stock UOM and quantity from the WIP Warehouse. Link that submitted
  correction; only then can the bin return to `Empty`.

For a cancelled submitted transfer, ERPNext has returned stock to the source Warehouse but cannot
prove where the material physically sits. The bin stays `Exception`. When the transfer originally
used a physical source Stock Tag, CFG Kanban immediately reserves the restored tagged quantity so
another transaction cannot use it while the location is uncertain. The Supervisor chooses:

- **Material Returned to Source** — physically return the exact quantity, rescan the affected WIP
  bin, and rescan the original source Stock Tag when one was used. The source safety reservation is
  released and the reusable bin becomes `Empty`.
- **Material Remains in WIP after ERP Correction** — post a new submitted native `Material
  Transfer for Manufacture` containing one exact row for the same Work Order/Job Card, Item, Batch,
  UOM, quantity, source Warehouse and WIP Warehouse. Link that correction. CFG Kanban consumes the
  source-tag safety reservation when applicable, creates a separately linked recovered `Ready`
  load, and returns the reusable bin to `Ready`.

Both paths record the Supervisor Employee, terminal User, operator session, time, reason, evidence,
cancelled Stock Entry, and Event history. A normal Operator cannot release the hold, a cancelled
entry cannot be its own correction, and the original history is never deleted. The generic
`Stock Entry Cancelled` Cycle/Card hold is restored to its pre-cancellation state only after every
affected physical bin has been reconciled; an older unrelated hold is preserved. Work Order creation
is no longer blanket-blocked for a correctly configured WIP-bin Master.

The reusable operation Card also remains locked to its current Cycle while the selected Job Card
has any `Transfer Draft`, `Ready`, `In Use`, `Consumption Draft`, or `Return Draft` WIP Bin Load, or any Open WIP
Bin Reconciliation. The panel disables closure with the exact bin/state reason, and the server
applies the same rule to **Close Kanban Cycle** and `CFG:CMD:CLOSE_CYCLE`. Submit or cancel the Draft
movement, consume the Ready bin, or finish the controlled Supervisor reconciliation before the
operation Card can return to `Available`. This is intentionally Job Card scoped because the
physical bin load cannot be divided safely between reusable runtime Cards.

Supervisors can monitor the complete pool without opening each load from **CFG Kanban >
Production Supervisor > WIP Bin Control**. The read-only report includes permanent Empty bins,
active Draft/Ready/In-Use loads, production references, state age, configuration gaps, physical
state versus load-status mismatches, duplicate active loads, changed Pool/Workstation context, and
Open cancellation reconciliations. Use **Attention Only**
for exceptions and pending actions. Use **Include Disabled / Held Bins** only when investigating
inactive assignments or unavailable bin identities. The report never posts ERP stock or changes a
bin; follow the linked native Stock Entry, WIP Bin Load, or reconciliation workflow to correct the
condition.

Use `docs/TEST_STANDARD_QUANTITY_WIP_BIN_TRANSFER_GATE.md` for the complete transfer-and-consumption
acceptance test before enabling the method on a live production Master.

For **Transfer to WIP by Job Card**, both the main Production Card and the activated reusable
Process/Station operation Card can prepare the transfer. The operation Card is deliberately limited
to its runtime-selected Job Card: it cannot view or transfer another operation's materials and it
cannot create the final Manufacture receipt. The ERP Stock Entry remains linked to the main
production Cycle because that Cycle owns the Work Order; the operation Card Cycle is recorded as
the requesting execution for audit. If automatic Job Card start is enabled, start is deferred while
that Job Card still has pending material transfer. The operator prepares/scans/submits the material
entry first, then scans `CFG:CMD:START`.

After scanning the production Card, **Production Material Control** shows live ERP stock,
required/transferred/consumed/pending quantities, shortages, WIP Warehouse, and output Warehouse.
The operator verifies source Warehouses and actual quantities and must enter **Operator
Confirmation / Notes**. When a posting policy creates a Draft, **Submit ERP Entry** performs the
controlled submission; the app blocks a second draft for the same Cycle/purpose/Job Card.

The app blocks Job Card Start while the relevant submitted ERP material transfer is still pending.
After every Job Card is completed, **Prepare Manufacture Receipt** becomes available. The operator
confirms accepted output, output Warehouse, optional finished Batch, and actual input consumption.
For a batch-controlled finished Item, the operator may enter a Batch number to use or create that
exact Batch. If the field is left blank, CFG Kanban does not invent a number: ERPNext generates the
Batch during Stock Entry submission when the Item's native automatic Batch creation settings permit
it. A Cycle with a pre-approved planned Batch (for example, controlled make-to-order production)
keeps that Batch locked and cannot switch to a different one at receipt.
The resulting ERPNext Manufacture Stock Entry is the accounting event. Tagged and untagged
materials may coexist; physical-tag genealogy remains an additional trace layer and never replaces
ERP stock.

For **Skip WIP Transfer**, Job Card start is not blocked by a WIP prerequisite. At the point where
the operation physically uses material, the operator scans `CFG:CMD:PREPARE_MATERIALS`, chooses the
Job Card when necessary, and confirms actual quantities. CFG Kanban always creates a Draft native
**Material Consumption for Manufacture** first. This permits physical tags to be scanned before
stock changes. Scan `CFG:CMD:SCAN_MATERIALS`, then the input tags, then
`CFG:CMD:SUBMIT_MATERIALS`. Submission is the authoritative ERPNext consumption event. An input tag
may hold more than the actual usage: the trace reserves and consumes only the Stock Entry row
quantity, leaving the remaining quantity available on the same Handling Unit.

The main Production Card may perform the same consumption for all eligible Job Cards. A runtime
operation Card sees and controls only its selected Job Card. Submitted Job Card-specific
consumption is totalled back into the live **Required / Pending** display. A second draft for the
same Work Order, purpose, and Job Card is blocked until the existing draft is submitted or
cancelled.

For the complete two-operation WIP-transfer example, use
`docs/TEST_RW_NOODLE_TWO_OPERATION_BATCH.md`. For operation-time direct consumption without WIP,
use `docs/TEST_SKIP_WIP_JOB_CARD_CONSUMPTION.md`.

### Start work

In **Kanban Operator**, scan the reusable card and locate the Process Execution. When its status is
Ready, select **Start**. The app sends the action through an auditable ERP Command to the linked
ERPNext Job Card.

### Report progress

Select **Report Progress** and enter:

- Good Qty — accepted output in this progress entry.
- Reject Qty — rejected output in this progress entry.
- Notes — optional operator explanation.
- Dynamic operation checks — fields defined on the Master.

Progress entries are incremental. If the execution already contains 100 good units and the next
entry is 50, the execution total becomes 150. Do not enter the cumulative total unless it is truly
new output.

Progress records are immutable. Corrections require a future explicit adjustment workflow; do not
delete or edit production history directly.

For Digital Quantity Handoff, the app releases only completed Transfer Multiples. Example:

```text
Transfer multiple: 12
Total good output: 29
Eligible release: 24
Previously released: 12
New WIP release: 12
```

### Complete work

When a linked Job Card is In Progress and its ERPNext completed quantity has reached its target,
select **Complete**. ERPNext Job Card feedback updates the Process Execution. ERPNext Work Order
feedback moves the Cycle into In Production and later Production Complete.

Every positive Kanban Good Qty creates an auditable **Update Job Card** ERP Command containing the
Job Card, Work Order, Cycle, Process Execution, optional Runtime Allocation, Operation Progress,
incremental quantity, operator Employee, terminal User, timestamps, notes, and retry token. The
gateway creates or closes an ERPNext Job Card Time Log and links it back through **Kanban Progress**
(`cfg_kanban_progress`). A retry of the same progress reference does not add the quantity twice.

If **Auto-submit Job Card at Target** is enabled, the gateway submits the draft Job Card only when
ERPNext `total_completed_qty` reaches `for_quantity`. Otherwise the Job Card remains draft until an
authorised Complete action or a valid manual ERPNext submission.

Submitting a linked Manufacture Stock Entry records an Event and moves the Cycle to **Waiting FG
Receipt**. A Physical Unit or Physical Batch production Card is then recycled automatically only
after ERPNext proves all of the following: the effective Work Order is submitted and Completed, all
of its active Job Cards are Completed, submitted Manufacture output linked to the Cycle has reached
the effective Cycle quantity, and the **Before Cycle Close** Process Task gate is open. The Cycle is
marked Completed and the Card moves through In Production → Produced → Available with Active Cycle
cleared. If ERP events arrived in a different order, scanning the physical Card again performs the
same idempotent reconciliation; it never manufactures or completes ERP documents by itself.

### Close a Process/Station runtime allocation

Runtime-selected Process/Station cards have a separate implemented closure. **Close Kanban Cycle**
is allowed only after all of these are true:

- the full allocation target has been reported in Kanban;
- the Before Cycle Close Process Task gate is open;
- the ERPNext Job Card is Work In Progress or Completed;
- the ERPNext Work Order is started, or it uses Skip Transfer and the Job Card is already active;
- ERPNext Job Card completed quantity is at least this allocation's Kanban Good Qty.

Closure marks the execution/allocation/Cycle Completed and returns the reusable Card through
Production Released → In Production → Produced → Available. It clears Active Cycle. If several
card cycles feed one larger Job Card, the Job Card remains open until cumulative completed quantity
reaches its own full target.

The operator no longer needs to revisit every related Process/Station Card after the main physical
production Card becomes ready to close. Main Cycle reconciliation first finds every runtime Cycle
for the same effective Work Order and pre-checks them as one set. Any operation Card whose full
Kanban allocation is reported, submitted Job Card is Completed, WIP-bin state is safe, and Before
Cycle Close task gate is open is completed and recycled together with the main Card. The automatic
closure retains separate Cycle, allocation, execution, Card-transition and Event audit records.
If even one related operation Cycle is genuinely incomplete or inconsistent, none of the remaining
operation Cards are auto-closed and the main Card stays open with the exact blocking Card/Cycle and
reason. The individual **Close Kanban Cycle** action remains available when an operation Card must
be released before the overall Work Order and finished-goods receipt are complete.

## 9. Stock-based Sales Order proposals

This mode uses a submitted Sales Order as an evaluation event but still replenishes a warehouse
stock target.

### Master configuration

Configure:

- Enable Sales Order Trigger: Yes.
- Production Policy: Stock Replenishment.
- Threshold Source: ERPNext Warehouse Reorder Level, recommended; or Kanban Override.
- Demand Scope: General, Customer, Sales Territory, or Production Line.
- Demand Scope Value: exact value for a non-General scope.
- Master Priority: higher number wins where valid scopes overlap.
- Minimum Shortage to Propose: optional noise threshold.
- Maximum Cards per Sales Order: safety cap.

The app selects by Sales Order warehouse, then most-specific scope, then highest priority. It
rejects duplicate active Masters with the same Item, destination warehouse, scope, and scope value.
A remaining tie creates a configuration Exception instead of producing duplicate Work Orders.

### Calculation

```text
Shortage = inventory target
           − ERPNext projected quantity
           − open Kanban cycle supply
           − other waiting proposal supply

Cards required = shortage rounded up by Master replenishment quantity
```

Sales Order outstanding quantity is displayed for audit but is not added again because submitted
Sales Order demand is already represented in ERPNext projected quantity.

### Approve the proposal

Submit the Sales Order. Evaluation runs automatically. A manager can also use **Create → Evaluate
Kanban Demand** on the submitted Sales Order.

Open **Sales Demand Proposals**, review a Waiting Approval record, and select **Approve and
Release**. The app reserves the required Available cards, creates one Signal and Cycle, and creates
the Work Order through the ERP gateway.

If insufficient cards are available, the Demand becomes Blocked and an Exception is created.

## 10. Customer Make-to-Order workflow

Use this for a customer whose product is made only against an order, with a dedicated batch and
common expiry date.

### Master configuration

Create a Customer-scoped Master:

```text
Enable Sales Order Trigger: Yes
Demand Scope: Customer
Demand Scope Value: exact ERPNext Customer ID
Production Policy: Customer Make-to-Order
MTO Extra Production Tolerance %: maximum allowed by internal policy
Plan Work Order to Maximum Permitted Qty: Yes or No
MTO Batch Policy: One Batch per Sales Order Line
Existing Stock Usage: Prohibited
Order Consolidation: Prohibited
```

The same Master is reused for different order quantities. Do not create a new Master for every
quantity.

### Sales Order customer-PO controls

In the Sales Order's **CFG Kanban Demand** section, record:

- Customer PO Allows Extra Quantity.
- Customer PO Extra Tolerance %.
- PO Tolerance Reference — PO clause, amendment, or written authorization.

Effective tolerance is the lower percentage:

```text
Master permits 5%
Customer PO permits 3%
Effective tolerance = 3%
```

Without explicit PO authorization, effective tolerance is zero.

For an outstanding quantity of 1,000 and effective tolerance of 3%:

```text
Base order quantity:       1,000
Maximum authorized output: 1,030
```

If **Plan Work Order to Maximum Permitted Qty** is enabled, the proposal recommends 1,030. If it is
disabled, the proposal recommends 1,000 while still allowing accepted output up to 1,030.

### Approval and batch creation

Submit the Sales Order, open its CFG Kanban Demand, and select **Approve and Release**.

Expected result:

- No reusable card is reserved.
- One Cycle is created for that Sales Order line.
- One ERPNext Batch is created and linked to the Demand, Cycle, and Sales Order.
- Batch expiry is calculated from Item Shelf Life in Days.
- One Work Order is created for the recommended quantity.
- Work Order Production Origin is Sales Order.

Every Sales Order line has its own idempotency identity, so separate lines or orders are not
consolidated into one MTO Cycle.

### Manufacture Stock Entry control

When submitting an MTO Manufacture Stock Entry:

- The finished Item row must use the Cycle's planned Batch.
- Blank or different finished Batch is rejected.
- Cumulative accepted production cannot exceed Maximum Authorized Qty.
- Output above the base outstanding quantity but within the authorized maximum is recorded as
  PO-authorized excess.

The planned Batch is currently not filled automatically into the Stock Entry. Select it manually
and verify it before submission.

The app does not silently increase a submitted Sales Order. Delivery or invoicing of additional
quantity remains governed by ERPNext amendment and over-delivery controls.

## 11. Handling-unit tags

A Handling Unit identifies one physical pallet, mesh, tote, or container. It is different from a
reusable Kanban Card and cannot trigger replenishment.

For a one-off preprinted Stock Tag, register its exact visible number under **CFG Kanban Tag
Family**. For a large preprinted serial series, create one **CFG Kanban Tag Range Registry** instead;
do not import thousands of unused Tag Families. Then create **CFG Kanban Handling Unit → New**
after a Cycle exists and enter:

- **Preprinted Tag / Handling Unit ID** (`handling_unit_id`) by scanning the barcode/QR or typing
  the exact visible value.
- Handling Unit Type.
- Kanban Cycle.
- Quantity and UOM.
- **Inventory Company** (`inventory_company`) and **Current Warehouse** (`current_warehouse`).
  Current Warehouse is the ERPNext warehouse that physically holds the stock now; it is not the
  future Manifest destination.
- Carton/container count where applicable.
- Immediate Source and Immediate Destination.
- Sequence No. and Total Units, for example `1 of 3`.

When the scanned value belongs to an exact family, the form fills **Tag Family**, **Tag Kind**,
**Child Index**, and issuing Company. When it belongs to an active Range Registry, the form fills
**Tag Range Registry**, **Tag Kind**, **Child Index**, and issuing Company. Saving then atomically
creates only that exact Tag Family and its configured detachable child identities. Merely looking
up or scanning an unused range number does not create database records. Item, Batch, Work Order,
reusable Card, and description are copied from the Cycle when available. **Internal UUID Alias**
(`opaque_token`) is generated
automatically for compatibility and audit; users do not type it and it does not need to be printed.

### Print a Handling Unit, reusable bin, or bin-slot identity

Open the saved **CFG Kanban Handling Unit** and use **Print Labels**. Four audited choices are
available:

| Print choice | Physical size | Intended use |
|---|---:|---|
| Full Trace Tag | 45 × 250 mm | Existing detailed stock/handling-unit trace tag |
| Bin Slot Small | 50 × 30 mm | Compact thermal barcode label for a nearby fixed bin or narrow slot |
| Bin Slot Standard | 100 × 50 mm | Barcode and QR label with Warehouse, Operation, and bin/slot reference |
| Bin Slot Large | A6 landscape, 148 × 105 mm | Distance-readable workstation, rack, or large-bin card |

Every format encodes the permanent **Preprinted Tag / Handling Unit ID** (`handling_unit_id`), not
the internal opaque alias. The first print updates the Handling Unit print audit. Any later print,
including a different size, requires a reprint reason so physical duplicates remain traceable.

For a permanent workstation bin, fill **Container Reference** (`container_reference`) with the
human-readable rack/slot name before printing. The Standard and A6 formats also show the current
Warehouse, current Operation, reusable-container role, and current bin/identity state. These labels
identify the physical bin only; mutable Item and quantity contents must still be read from the live
Handling Unit/container record.

In the browser or printer driver, select media matching the named physical size and use **100% / no
scaling**. Do not use “Fit to page”, because it changes barcode dimensions and can reduce scan
reliability.

Existing preprinted stock tags are the normal operating method, so production does not depend on a
live tag printer. **Print Labels → Full Trace Tag (45 × 250 mm)** remains the optional
replacement/emergency trace label. Its PDF canvas is 45 mm × 250 mm for portrait-feed thermal
stock, with the horizontal design rotated onto that canvas. Both its QR and Code 128 encode the
visible `handling_unit_id`.

Handling-unit scan lifecycle:

```text
Issued → Attached → Dispatched → Received
   └──────────────→ Void
```

Received, Void, and Replaced are terminal states. A repeated terminal scan returns the existing
state without triggering production.

Reprints require a reason. Replacement creates a new tag identity and revision, marks the old tag
Replaced, and preserves the relationship between both records.

### Mixed tagged and ERP-only materials

Physical tags are optional per Item and Company. Open **CFG Kanban Material Trace Policy** only for
an Item that needs more physical traceability than its ordinary ERPNext stock record. If no enabled
policy exists, the Item defaults to **ERP Document Only** with **No Physical Tag** at receiving,
production input, and production output. Its Warehouse quantity, Batch where applicable, Work
Order, Job Card, Stock Entry, and virtual Kanban WIP continue to operate normally.

For a submitted ERPNext Purchase Receipt, **CFG Kanban → Tag Received Material** displays every
receipt row. Rows with **No Physical Tag** remain valid received stock and need no further action.
Rows configured as Optional or Required can activate one or more unused preprinted main Stock Tags.
The dialog derives Item, Company, accepted Warehouse, Stock UOM, Batch, Supplier, and expiry context
from the submitted Purchase Receipt and prevents the total activated tag quantity from exceeding
the confirmed receipt-row quantity.

The **Receipt Item** dropdown deliberately includes both tag-enabled and ERP-only rows. Select a row
to see its readiness message. If it says **ERP-only receiving**, create or open **CFG Kanban Material
Trace Policy** for the exact Purchase Receipt **Company** and **Item**, enable it, set **Trace Level**
to **Exact Handling Unit**, and set **Purchase Receiving Tags** to **Optional Physical Tag** (pilot or
selective use) or **Required Physical Tag** (the whole confirmed quantity is expected to be tagged).
Save the policy and reopen **Tag Received Material**. A tag-enabled row also needs an accepted
Warehouse and, when the policy requires it, completed ERPNext Batch information. Rows already fully
tagged remain visible with an explanatory status but cannot activate another tag.

Scanning a preprinted tag in this dialog only opens a separate review step. Confirm the receipt
row, Stock-UOM quantity, handling-unit type, and visible tag number, tick **I checked the tag,
receipt item, and quantity**, and then select **Confirm and Activate Tag**. The scanner's Enter
suffix cannot bypass this acknowledgement. Stock Manager, Manufacturing Manager, or System Manager
can use **Void Wrong Tag** while the newly activated tag is still untouched. A correction reason is
mandatory; the quantity returns to the row's untagged balance and the physical barcode is revoked,
not erased or made reusable. Remove and quarantine that label, then activate a new unused tag. Once
the tag has moved, split, been reserved, loaded, or consumed, this shortcut is blocked and the
controlled downstream reconciliation process is required.

Rescanning an already active receipt tag never adds or subtracts quantity. An exact repeat is
reported as an idempotent retry with **no quantity changed**; a different quantity is rejected.
Correct an untouched wrong total by voiding that tag and activating a new unused tag with the right
quantity. Do not use repeated activation as a basket-transfer method. Moving material between two
physical baskets in the same receiving Warehouse requires the controlled receipt-time split/repack
workflow so the decrease and increase occur as one balanced, audited event without an ERPNext stock
transfer.

For ordinary non-serial material, start that controlled transaction from either location:

- **Purchase Receipt → CFG Kanban → Tag Received Material → Active Tags → Split / Repack**; or
- the source **CFG Kanban Handling Unit → Kanban Actions → Receipt-Time Split / Repack**.

Enter the quantity moving, record the reason, and scan a different unused preprinted **main** Stock
Tag for the new basket. Scanning opens a review window; tick **I checked both physical tags and the
quantity** before confirming. The service posts one balanced Handling Unit **Split** ledger event:
the source decreases and the new destination tag increases by the same Stock-UOM quantity. Item,
Batch, Company, Warehouse and receipt lineage are retained, while ERPNext stock remains unchanged.
The source must still be at the original receiving Warehouse, quality released, unreserved, and not
loaded into another container. A full-quantity repack is allowed and leaves the old source tag Empty.
For serial-controlled Items, use **Split Exact Serials to Child Tag** instead.

When both physical baskets already have active Stock Tags, use **Move to Active Tag** beside the
source tag in the Purchase Receipt dialog, or open the source **CFG Kanban Handling Unit** and select
**Kanban Actions → Transfer Quantity to Active Tag**. Enter the quantity and reason, then scan the
existing active destination tag. Review and tick the physical-check acknowledgement before
confirming. The system records one balanced **Merge** ledger event: the source decreases and the
destination increases, but ERPNext Warehouse stock does not change. A full transfer leaves the
source tag Empty.

This active-tag transfer is intentionally strict. Both tags must have the same Item, Batch, Stock
UOM, Company, Warehouse, quality state, current operation, and movement state. Both must be quality
released, unreserved, outside open manifests and delivery allocations, and unloaded from reusable
containers. Serial-controlled tags require an exact-serial workflow. The destination's original
activation quantity remains immutable audit history; its live `Current Qty` reflects the combined
physical balance. Use **Split / Repack** instead when the destination tag is new and unused.

### Onsite retagging from the Logistics panel

For warehouse staff and drivers working from a phone or tablet, assign **Stock Retagging** under
**CFG Kanban Operator Profile → Responsibilities** and ensure the profile can start work. ERPNext
roles alone do not expose these floor actions. A Supervisor with **View All Responsibilities** can
also use them. Do not assign this responsibility to every operator: it authorizes physical tagged
quantity redistribution.

In **Kanban Logistics**, identify the operator and scan the source Stock Tag in normal lookup mode.
The tag status card shows a **Stock Retagging** block only for an authorized operator:

- **Split to New Main Tag** moves a stated quantity to a different unused main Stock Tag. Use this
  when one basket/bin is physically divided and the second basket uses an independent printed tag.
- **Split to Detachable Child** is shown for a main Stock Tag. It moves a stated quantity to one
  unused preprinted child from the same Tag Family, for example `STK1000` to `STK1000-1`. Scan the
  main tag first, select this action, enter the quantity, and then scan the detachable child. The
  child becomes an active Stock Tag with the same Item, Batch, Company, Warehouse, UOM, quality,
  cycle, and operation context. The main tag remains its genealogy parent.
- **Move to Active Tag** moves a stated quantity into another already-active matching Stock Tag.
  Use this when consolidating or moving loose quantity between two tagged bins.

Enter the physical quantity and reason, scan the destination with the camera or scanner field, then
confirm the separate physical-check acknowledgement. Both operations write one balanced immutable
Handling Unit ledger event and record the employee/operator session. They do not create an ERPNext
Stock Entry because Company and ERP warehouse do not change. If the physical bins are configured as
different ERPNext Warehouses, use the tagged Material Transfer workflow instead.

The Logistics panel rejects retagging when the source is reserved, loaded in a reusable container,
on an open Manifest or customer allocation, quarantined, serial-controlled, or otherwise in an
incompatible process state. A detachable child must be unused and belong to the scanned main tag's
Tag Family; another family's child and an already activated child are rejected. Serial-controlled
stock continues to use **Split Exact Serials to Child Tag** on the Handling Unit form so the exact
ERPNext Serial Numbers are preserved. Active-to-active transfer additionally requires matching
Item, Batch, UOM, Company, Warehouse, quality state, operation, and movement state.

In this first receiving slice, **Required Physical Tag** makes the missing tagged balance visible
but does not block native Purchase Receipt submission. Do not interpret it as an accounting hold.
A later controlled pending-tag workflow will add enforcement without affecting ERP-only Items.

### Production input, transfer, consumption, and output tags

The Stock Entry form exposes **CFG Kanban → Production Material Trace** after a supported Stock Entry
is saved. Supported exact Purpose values are `Manufacture`, `Repack`, `Material Transfer`,
`Material Transfer for Manufacture`, and `Material Consumption for Manufacture`.

For a Draft Stock Entry:

1. Open **Production Material Trace**. The summary lists every applicable source and target row,
   including rows configured as No Physical Tag.
2. Under **Allocate Tagged Material Input**, scan an active Handling Unit. In the floor Operator
   panel the scan automatically selects the remaining ERP input row whose Item, Company, source
   Warehouse, Stock UOM and Batch match the physical tag. Desk users may still select a row
   explicitly. The quantity is reserved against the Draft entry but ERP stock does not move.
3. Under **Stage Production Output Identity**, select a tag-enabled finished/repacked target
   row, scan either an unused main tag or an empty permanent **Production Output Container**, then
   enter its Stock UOM quantity and Handling Unit Type. The identity
   remains pending; no output stock tag is created while the entry is Draft. When the output is
   divided between several containers, enable **Allow ERP Quantity Across Multiple Tags** in the
   Item/Company Material Trace Policy, then repeat this step with a different unused main tag and
   the quantity physically placed in each container. The combined staged quantity cannot exceed
   the ERP output row quantity.
4. Use **Cancel** beside a staged line to release its reservation or discard the pending output tag
   before submission.
5. If the complete ERP draft will be discarded, select **Discard Entire Draft Trace**, enter the
   reason, and only then delete the Draft Stock Entry. This releases all tag reservations and keeps
   the Material Trace as Abandoned audit history without retaining a link that blocks ERP deletion.
6. Submit the Stock Entry through ERPNext or use **Submit ERP Entry** in the scanned Card's
   Production Material Trace section when the operator has the required action permission. Only
   then does the trace become Confirmed. For a Batch-controlled finished Item, the tags may be
   staged while the Draft output Batch is blank. ERPNext creates or assigns the Batch during the
   single Manufacture submission, and CFG Kanban copies that exact submitted Batch to every staged
   output identity before activating it. On ERPNext v15, CFG Kanban resolves the authoritative Batch
   from the saved Stock Entry Detail, its Serial and Batch Bundle, or the exact submitted Stock
   Ledger Entry row; it never guesses from the latest Batch. **Exact Output Serial Numbers** is only
   for ERP Serial Nos;
   never enter a Batch number in that field. Consumption
   reduces input-tag balance; Material Transfer for Manufacture updates the tag's Warehouse; and
   Manufacture/Repack activates output tags from the ERP-confirmed output. For a permanent output
   container, CFG Kanban creates a separate internal content identity for that exact Item, Batch,
   quantity, Work Order, and Stock Entry, and loads it behind the container's permanent QR.

#### Permanent Production Output Container

Use this when the same physical container or tray is reused from one production run to the next and
must also carry the semi-finished Item into the next production process:

1. Create **CFG Kanban Handling Unit** with **Tag Kind = Reusable Container** and **Reusable
   Container Role = Production Output Container**. Enter its permanent scan code, physical
   reference, Inventory Company, and current output Warehouse. Do not assign an Item or opening
   quantity to the container itself.
2. Print one of the Handling Unit / bin-slot formats and attach that permanent QR or barcode to the
   container. The printed identity is reused; it is not replaced for each Batch.
3. In the Draft Manufacture entry, scan a quantity command such as `CFG:QTY:GOOD:+50`, then scan the
   empty permanent container. Repeat with another empty production container when the ERP output is
   divided across several containers. Submit the Manufacture entry once.
4. ERPNext remains the stock and Batch authority. On submission, CFG Kanban creates a hidden,
   immutable fill identity for each scanned container and copies the submitted Item, Batch,
   quantity, Work Order, Warehouse, and Stock Entry origin into that fill. Container Content History
   records when that fill entered and left the permanent container.
5. At the next production process, scan the same permanent container as the material input. CFG
   Kanban resolves its one current fill and reserves/consumes that exact Item and Batch. A full
   consumption closes the fill episode and makes the permanent container empty and reusable. A
   partial consumption leaves the balance in the same container.

The system rejects a Production Output Container that is already filled, belongs to a different
Company or Warehouse, is on an open Manifest/delivery, is on Hold, or contains inconsistent content.
A normal Logistics Container and a Standard Quantity WIP Bin cannot substitute for this role. Never
reuse a Main Stock Tag for a new Batch: only the permanent container QR is reused; every fill remains
a separate auditable identity. Cancelling an untouched Manufacture entry voids its fill and empties
the container. Cancelling downstream consumption restores the fill only when the permanent container
has not been reused for later output.

For WIP-transfer-enabled manufacturing, scan the input tag on the Material Transfer for Manufacture
entry, then scan the same tag again from its WIP source Warehouse on the later Manufacture or
Material Consumption entry. For skip-transfer production, allocate the tag directly on the
Manufacture/Material Consumption entry.

An explicit **Required Physical Tag** production policy blocks Stock Entry submission until the
corresponding ERP row quantity is fully covered. Optional policies permit partial tagged quantities.
No Physical Tag rows never require allocation and continue as normal ERP stock. One trace may have
many input and output tags, so several raw-material containers can produce several semi-finished or
finished containers.

ERPNext v15 direct Batch values and single-Batch Serial and Batch Bundles are resolved. If one ERP
row contains multiple Batches, split it into a row/bundle per Batch before physical tagging. One
Handling Unit cannot represent several lots.

When a submitted Stock Entry is cancelled, the app reverses untouched tagged input/output balances
and marks produced tags Void. Cancellation is blocked if a produced tag has already moved, split,
reduced, or been reserved; resolve downstream activity first rather than deleting trace history.

The same Draft trace is available from the floor Operator panel without giving the operator general
Stock Entry access:

1. Create and save the correct supported Stock Entry against the effective Work Order. Do not
   submit it yet.
2. On `/app/kanban-operator`, identify the operator and scan the production Kanban Card.
   Scanner-initiated material preparation always creates a Draft Stock Entry first—even when the
   Master normally auto-submits—so physical tags can be captured before ERP stock changes.
3. Scan the printed `CFG:CMD:SCAN_MATERIALS` command. If several Draft entries are eligible, scan
   `CFG:SELECT:1` through `CFG:SELECT:10` for the numbered entry, then scan
   `CFG:CMD:CONFIRM`. The matching trace dialog opens without mouse or touch input.
4. For an input row, scan the Handling Unit with a fixed scanner or **Camera Scan Input Tag**. The
   tag selects the matching ERP input row automatically. Leave
   **Stock Quantity (0 = automatic)** at zero to allocate the available tag quantity up to the ERP
   row balance, or enter a smaller explicit quantity for a permitted direct-consumption allocation.
   Material Transfer for Manufacture still requires the complete physical Handling Unit.
5. For an output row, scan an unused preprinted main tag or an empty permanent Production Output
   Container, confirm quantity and Handling Unit Type,
   and select **Stage Output Tag**. Output quantity cannot be inferred when several physical
   containers may divide one ERP row. For scanner-only staging, first scan a routine Good command
   such as `CFG:QTY:GOOD:+50`; inside Production Material Trace this sets the quantity for one
   output identity rather than reporting Job Card progress. Then scan the unused output tag or
   empty permanent output container to stage it.
   The same armed quantity remains available for the next container, while the remaining ERP row
   balance continues to prevent over-staging.
6. Scan `CFG:CMD:SUBMIT_MATERIALS` to submit the single eligible entry. When several entries are
   eligible, scan its numbered Select label and then Confirm. Submission remains governed by the
   operator's Material Transfer or Production Receipt permission and ERPNext validations.

The server accepts this route only when the Stock Entry Company and Work Order match the scanned
Card's active Cycle. Operator authorization, allowed Operation, allowed Workstation, and session
expiry are enforced on every write. A submitted trace is view-only in the floor panel.

### Same-company tagged Warehouse transfer

Use this workflow to move tagged stock between two Warehouses belonging to the same Company without
using an intercompany Movement Manifest:

1. Create and save an ERPNext Stock Entry with Purpose exactly **Material Transfer**. Select the
   Company and complete each row's source Warehouse, destination Warehouse, Item, Batch where
   applicable, Stock UOM, and quantity. Leave it Draft.
2. Assign the operator the Kanban Responsibility **Internal Warehouse Transfer** in **CFG Kanban
   Operator Profile → Responsible Roles**. A Supervisor with **View All Service Tasks** can also
   access this assistant.
3. Open `/app/kanban-logistics`, identify the operator, and find the Draft under **Same-Company
   Tagged Warehouse Transfers**.
4. Select the entry and choose the matching ERP transfer row. Scan the active Handling Unit with the
   fixed scanner or **Scan Tag with Camera**. Quantity zero means the complete physical tag.
5. Repeat for all tagged rows. Rows whose policy is **No Physical Tag** require no Kanban scan.
6. A Stock/Manufacturing user reviews and submits the ERPNext Stock Entry. Submission changes the
   authoritative ERP stock location and confirms the Material Trace; the Handling Unit then shows
   the destination Warehouse.

One tag cannot be split across two Warehouses. If only part of the physical container moves,
activate a detachable child tag for that physical portion before allocation. The logistics operator
cannot submit the Stock Entry. Removing a Draft trace line releases its reservation. Cancelling a
submitted untouched transfer reverses the tag location; later movement or reservations block unsafe
reversal.

### Scan-any-tag Material Genealogy Explorer

Open **CFG Kanban → Material Genealogy Explorer** or `/app/material-genealogy`. This is a read-only
supervisor, stock, and manufacturing investigation page; it never reserves, moves, consumes, or
creates ERP stock.

1. Scan or enter any activated **Preprinted Tag / Handling Unit ID**. A mobile device can select
   **Scan with Camera**. An unused registered/range-covered tag is recognized but correctly reports
   that no material genealogy exists before activation.
2. The blue focus block shows the exact current Item, Batch, Company, Warehouse/custodian,
   quantity, availability, lifecycle, and immutable ERP origin.
3. **Upstream Materials** follows confirmed production inputs, tag splits/replacements, and other
   source-to-destination physical-identity relationships. **Downstream Products** follows the same
   evidence forward. Selecting a related tag makes it the new focus.
4. **Confirmed Lineage Relationships** states the transformation/split type and its Stock Entry or
   other reference. Reversed traces remain visible as reversed audit history rather than being
   silently removed.
5. **Movement Manifest History** shows intercompany handovers and links to their Delivery Note and
   Purchase Receipt. **Chronological Quantity and Movement Evidence** shows the immutable ledger
   events for every displayed lineage tag.
6. Select **Print Trace Report** for an A4 `CFG Kanban Genealogy Report`. The report explicitly
   identifies its evidence as **Exact Handling Unit** and repeats the ERP references.

The same explorer is available from an activated **CFG Kanban Handling Unit → Kanban Actions →
Explore Material Genealogy** and from **Full Genealogy** after a read-only Logistics-panel tag
lookup. The explorer follows a maximum of 20 generations and 100 Handling Units per request. If the
safe display limit is reached, it warns the user to continue from a related tag rather than hiding
the limitation. Untagged stock remains traceable through native ERPNext Item, Batch, Stock Entry,
Work Order, Purchase Receipt, and Delivery Note records; it cannot appear as exact Handling Unit
evidence.

### Reusable containers with one or many Stock Tags

Use **Tag Kind** (`tag_kind`) = **Reusable Container** for a permanent tote, basket, cage, or box
identity. It is not an Item balance. Each Item or Batch inside remains represented by its own Main
or Child Stock Tag and remains backed by ERPNext stock.

1. Create and save the reusable-container Handling Unit. Enable **Allow Mixed Item / Batch Content**
   (`allow_mixed_content`) only when the physical container may hold different Items or Batches.
2. Give the operator **Container Loading** responsibility, or use a Supervisor/manager account.
3. Open **CFG Kanban → Logistics Operator Panel** and identify the operator.
4. Keep the scanner in normal **Tag lookup ready** mode and scan the reusable-container code.
5. Select **Manage Contents**. Scan a complete active Stock Tag and select **Load Tag**. A fixed
   scanner may submit with Enter; a phone or tablet can select **Scan Stock Tag with Camera**.
6. Repeat for every complete Stock Tag physically placed in the container.
7. Before physically removing a Stock Tag, select **Unload**, enter the reason, and then remove it.

The first content tag assigns a blank container's **Inventory Company** and **Current Warehouse**.
Every later content tag must match them. When mixed content is disabled, it must also match the Item
and Batch already inside. Loading/unloading does not create Stock Entry quantity: it records a
physical membership episode. The scanned container card and the Handling Unit form dashboard show
the **computed live quantity, Item, and Batch of the loaded Stock Tags**, grouped when necessary.
If several Batches are loaded, every distinct Batch is shown rather than assigning one misleading
Batch to the reusable-container identity. The
container's own **Current Qty** remains zero by design; copying the same quantity onto both the
container and its Stock Tags would double-count operational stock. A Stock Tag cannot be consumed,
transferred, dispatched, received,
replaced, or voided independently while loaded, and a nonempty container cannot be replaced or
voided. Managers can review **Container Content History** or **Reusable Container Episodes** in the
Material Genealogy Explorer.

#### Dispatch and receive a complete reusable container

When every Stock Tag currently inside the reusable container must travel together:

1. Create or open the correct Draft **Movement Manifest** in the Logistics Operator Panel.
2. Select **Start Dispatch Scanning** and scan the reusable-container code once.
3. The app expands the container into one Manifest line per contained Stock Tag. The container is
   physical grouping evidence only; ERPNext Delivery Note and Purchase Receipt rows continue to
   use each Stock Tag's Item, Batch, UOM, and quantity.
4. Review the expanded lines. Each line displays **Inside container** and the permanent container
   code. **Remove Container** removes the complete group from a Draft Manifest.
5. Select **Prepare and Reserve**, then confirm the dispatch. The container contents are locked
   against load/unload changes while the Manifest remains open.
6. At destination, open the same Manifest, select **Start Receipt Scanning**, and scan the
   reusable-container code once. This confirms every listed tag still physically inside it.
7. Confirm receipt. Only the submitted ERPNext Purchase Receipt changes destination stock and
   updates the container and every contained Stock Tag to the destination Company/Warehouse.

Preparation is rejected if a tag was added to or removed from the container after its dispatch
scan. Scanning an individual loaded Stock Tag for dispatch remains blocked: either dispatch the
complete container or unload the tag with an audited reason before handling it independently.

### Exact Serial Numbers inside a Stock Tag

When ERPNext Item **Has Serial No** is enabled, CFG Kanban requires exact serial membership for
tag activation through the supported receipt and production workflows:

1. Complete the ERPNext row's **Serial No** or **Serial and Batch Bundle** first.
2. In **Tag Received Material** or **Production Material Trace**, choose the ERP row and tag
   quantity.
3. The **Exact Serial Numbers** field fills automatically when this tag takes all remaining serials.
   For several tags, keep exactly the serials physically placed under the scanned tag, one per line.
4. The number of serials must equal the whole-number tag quantity, and every serial must belong to
   the selected ERP row, Item, and Batch.
5. ERP submission activates production-output membership. A received tag is associated immediately
   because its Purchase Receipt is already submitted.

The Handling Unit shows **Active Serial Count** (`serial_count`). Managers can use **Exact Serial
Membership**, **Handling Unit Serial History**, or the Genealogy Explorer. Production consumption
must use the complete serial-controlled tag; partial consumption is blocked. Warehouse transfers,
container membership, and intercompany movement preserve the serial association. Replacement
transfers it to the new tag. Consumption or voiding releases it, while ERP cancellation restores
the prior input association. Cancelling a Purchase Receipt automatically voids its untouched
received tags and releases their serial memberships. The cancellation is blocked when a tag has
already moved, split, been loaded, reserved, or consumed; reconcile that downstream activity
first. Generic detachable-child creation remains blocked for a serial-controlled parent. Use the
controlled workflow below.

#### Split exact serials to a detachable child tag

1. Open the active main **CFG Kanban Handling Unit**.
2. Select **Kanban Actions → Split Exact Serials to Child Tag**.
3. Scan one unused, preprinted detachable child code from the same Tag Family.
4. Scan or enter the exact ERPNext Serial Numbers physically moving to that child, one per line.
5. Enter the operational reason and select **Create Controlled Child Tag**.

The child quantity is derived from the number of selected serials; operators do not type a separate
quantity. The app moves the same quantity in the Handling Unit ledger and moves only those exact
serial memberships. ERPNext stock, Warehouse, Item, Batch, and Serial No ownership do not change.
The parent must be Active, unreserved, unloaded from reusable containers, and its quantity must
match its active serial count.

If the split was a mistake and the child has not had any later activity, open the child Handling
Unit and select **Kanban Actions → Merge Untouched Child Back to Parent**. Both tags must remain
unreserved, unloaded, and in the same Company and Warehouse. The serials and quantity return to the
parent, while the used child identity becomes **Empty** and is not reusable. Later movement,
reservation, container loading, consumption, or other quantity activity blocks this shortcut.

### Permanent Customer Site QR cards

Create one **CFG Kanban Customer Scan Point** for every customer delivery address that drivers must
identify independently. In **Permanent Customer Site Identity**, enter a globally unique **Printed
Customer Site Code** such as `CUSTSITE-CUST001-MAIN`; this exact readable value is the QR and Code
128 payload. Complete the Selling Company, Customer, Delivery Address, selling Price List, Delivery
Note policy, and proof policy, then save.

On the saved form, select **Print Customer Site QR**. The A6 landscape card prints the site name,
Customer, exact delivery address, Selling Company, route, proof policy, QR, readable site code, and
Code 128 barcode. Fix the card permanently at the correct receiving location. Do not print or use
the hidden **Internal UUID Alias** as the operational code.

To test it, open the **Logistics Operator Panel** in normal lookup mode and scan the printed card.
The panel must identify the exact Customer Site and display its Selling Company, Customer, address,
route, proof policy, and eligible Company-specific vehicle Warehouses before it offers **Start
Customer Delivery**. Never allocate stock if the displayed Customer or address differs from the
physical site.

## 12. Scanner-first floor operation

The Kanban Operator page supports both a fixed USB/Bluetooth keyboard-wedge scanner and the device
camera. For a fixed floor terminal:

1. Configure the barcode scanner to append **Enter** after every scan.
2. Open `/app/kanban-operator` in browser full-screen or kiosk mode. This prevents accidental focus
   on the browser address bar, which a web page cannot control.
3. Scan the operator credential directly. The page automatically keeps its scanner input ready.
4. Scan a Kanban card. The previous scanned value is cleared automatically, so the next card can be
   scanned without touching the screen.
5. Watch the green/orange **Scanner ready** banner before scanning.

The scanner-status and active-operator identity stay pinned at the top while the page scrolls. The
scanned production card is presented as **Active Work**, including its Cycle, effective Work Order,
process tasks, operation results, and Job Card execution lanes. General camera and panel-navigation
controls follow the Active Work area so the current production context remains visually dominant.

The same actions can be performed with function keys or printed command QR/Code 128 labels:

| Key | Command payload | Result |
|---|---|---|
| F1 | `CFG:CMD:HELP` | Show the scanner guide |
| F2 | `CFG:CMD:SWITCH_OPERATOR` | Arm the next scan as an operator credential |
| F3 | `CFG:CMD:NEXT_CARD` | Clear the current card and wait for the next one |
| F4 | `CFG:CMD:CAMERA_CARD` | Open the camera scanner |
| F8 | `CFG:CMD:END_SESSION` | Ask for confirmation, then end the operator session |

Operational command labels have no function-key equivalent:

- `CFG:CMD:ACTIVATE` consumes/triggers the open Available Card. A Process or Station Card opens its
  controlled Work Order/Job Card allocation before activation.
- `CFG:CMD:START` starts the operation when exactly one execution lane is Ready.
- `CFG:CMD:REPORT_PROGRESS` opens progress entry when exactly one execution lane is eligible.
- `CFG:CMD:GO_TO_CURRENT_WORK` follows the same workflow-aware priority as the on-screen button and
  scrolls the open Card to the next actionable task, exact material/Stock Entry row, Start, Report
  Progress, completion, receipt, or closure stage while keeping the fixed scanner armed. A Work
  Order warning is not selected while an operator floor action is available.
- `CFG:CMD:CLOSE_CYCLE` opens the guarded final confirmation for exactly one eligible runtime
  Process/Station Cycle. It never closes immediately: scan `CFG:CMD:CONFIRM` to proceed or
  `CFG:CMD:CANCEL` to return. The server rechecks operator permission, full allocated quantity,
  Process Task gate, Work Order state, Job Card state, and ERP-completed quantity before closure.
- `CFG:CMD:PREPARE_MATERIALS` prepares the WIP or operation material transfer.
- `CFG:CMD:PREPARE_RECEIPT` prepares final manufacture receipt/direct consumption when ready.
- `CFG:CMD:SCAN_MATERIALS` opens the eligible Draft Stock Entry for raw-material tag scans.
- `CFG:CMD:SUBMIT_MATERIALS` submits the selected Draft production material entry.
- Where a scanner action has several safe candidates, the panel displays a numbered list. Scan
  `CFG:SELECT:1` through `CFG:SELECT:10` (or a plain number label while that selection dialog is
  open), then scan `CFG:CMD:CONFIRM`. A number scanned outside that dialog is never treated as a
  selection command.

Inside **Report Progress**, quantity labels can replace keypad entry. Examples:

- `CFG:QTY:GOOD:+1` adds one good unit.
- `CFG:QTY:GOOD:10` sets good quantity to 10.
- `CFG:QTY:REJECT:+1` adds one rejected unit, subject to operator permission.
- `CFG:CMD:CONFIRM` submits the progress form.
- `CFG:CMD:CANCEL` closes the progress form without submitting.

When printing the command sheet, enter the routine Good/Material Quantity values required by that
workstation, separated by commas—for example `1, 10, 50, 100`. The sheet is generated on demand, so
different operations may keep different laminated quantity sheets without changing the Kanban Card
or Master. A scanned absolute command such as `CFG:QTY:GOOD:100` sets the field to 100, while
`CFG:QTY:GOOD:+100` adds 100 to its current value. The same values also print absolute
`CFG:QTY:MATERIAL:<value>` labels for material confirmation rows.

If an error message is open, the operator may immediately scan the next card. The panel closes the
message and processes that scan. `CFG:CMD:DISMISS` closes the message without loading another card.
When a Yes/No confirmation is open, `CFG:CMD:CONFIRM` selects its primary Yes/Confirm action;
`CFG:CMD:CANCEL` or `CFG:CMD:DISMISS` closes it without approval. The same Confirm label continues
to submit the Report Progress dialog when that form is active. After the popup closing animation,
the panel repeatedly checks and restores the correct scanner focus. If another operational dialog
is still underneath the error, its scanner field is restored; otherwise the main card scanner is
restored. The operator does not need to touch the page before the next scan.

Production material confirmation dialogs always arm their own **Scanner Command** field, including
when the dialog was opened from an on-screen operation-card button. Scan `CFG:CMD:CONFIRM` to create
the transfer/consumption Draft or `CFG:CMD:CANCEL` to close it. Raw-material tags are intentionally not accepted
in that first confirmation dialog. After the Draft appears, scan `CFG:CMD:SCAN_MATERIALS`, then scan
the physical input tags, and finally scan `CFG:CMD:SUBMIT_MATERIALS`. A scanner-confirmed preparation
is held as Draft until this final submit command even if the Master normally auto-submits.

For hands-free material quantities, each confirmation row is numbered. Scan `CFG:SELECT:1` through
`CFG:SELECT:10` to select the Item row, then scan an absolute material quantity such as
`CFG:QTY:MATERIAL:5`. A `+` form such as `CFG:QTY:MATERIAL:+1` adds to the currently selected row.
The printable scanner command sheet includes Material Quantity labels using the same configurable
quantity values as the routine Good Quantity labels.

Open **Scanner Help → Print Command Labels** to build a paper-saving command sheet. The catalogue
groups every registered hard-coded command and quantity label and provides one checkbox per label.
**Print Selected** generates only the checked labels, while **Print All** generates the complete
current catalogue for the configured quantity values. The browser terminal remembers its most
recent selection. An optional custom or translated title may be entered beside any command. That
custom title prints prominently, while the original standard command name and exact QR payload
remain on the label for support and audit. Custom text never changes the action executed by the QR.

The **Production Material Trace** window has a dedicated **Scanner Ready — Scan Material Tag or
Command** field. Operators do not select an ERP row manually: each physical input tag is matched to
the correct Item, Warehouse, UOM, Batch, and remaining Stock Entry row and allocated immediately.
When all tagged inputs are complete, the same field advances to unused output-tag staging where an
output row exists. Scans captured before browser focus reaches this field are routed back into this
window instead of being interpreted as a new Kanban card. Rows marked **No Physical Tag** require no
scan and remain controlled by the ERPNext Stock Entry.

The scanner determines the active stage from the Stock Entry's pending input/output rows, not from
the visual position of fields in the popup. If a scanned Handling Unit belongs to an Item outside
the remaining input list, the system identifies that Item and rejects it without allocating or
staging the tag. If the Item is expected but its Warehouse, UOM, Batch, or remaining quantity does
not match, the message identifies those conditions separately.

The camera scanner remains available over HTTPS. Offline queue and device enrollment are not yet
implemented.

The Production Operator scanner also recognises `CFG:PROCESS_TASK:<task>` and
`CFG:SAMPLE:<task>` identities. It loads the owning production card and opens the exact Process
Task action appropriate to its status. The Service Task scanner recognises permanent
`CFG:SERVICE:SCHEDULE:<schedule>` identities and resolves them to the current occurrence.

The server scan APIs support stable event tokens for retry/idempotency. Custom scanner clients
must retain the same event token when retrying the same physical scan.

## 13. Production dashboard and dispatch sequence

The **Kanban Floor** page reads a saved **CFG Kanban Dashboard Profile**. A profile does not create
production; it controls which live executions are displayed and whether the screen is read-only,
operator-oriented, or supervisor-controlled.

Key exact fields are **Profile Name** (`profile_name`), **View Type** (`view_type`), **Access Mode**
(`access_mode`), optional Company/Production Line/Warehouse/Customer/Item Group filters,
**Selected Workstations** (`workstations`), **Queue Depth per Workstation** (`queue_depth`),
**Refresh Interval (seconds)** (`refresh_interval_seconds`), **Screen Columns** (`column_count`),
and the statistics/completed/alerts switches.

For supervisor sequence control, use **View Type = Supervisor Sequence Control** and **Access Mode =
Supervisor**. A Manufacturing Manager/System Manager can then:

- reorder work that is still queued and not started;
- mark queued work as expedited;
- pause the currently In Progress Job Card and give way to a Ready execution on the same Workstation;
- resume a paused execution when no competing execution is active.

Every change requires a reason and creates immutable Sequence Change/Event audit. Interruption is
also governed by the operation's **Interruption Policy**. `Compatible Items Only` additionally
requires matching Setup Family and Cleaning Class. The dashboard never rewrites Work Order planned
dates or ERPNext manufacturing history merely to change visual order.

## 14. Understanding system records

| Record | What it means | Normally edited by users? |
|---|---|---|
| CFG Kanban Master | Controlled definition of one replenishment or MTO loop | Managers only |
| CFG Kanban Card | Reusable physical/digital trigger identity | Managers create; operators scan |
| CFG Kanban Demand | Sales Order evaluation and approval record | Managers approve |
| CFG Kanban Signal | Validated request to initiate replenishment | Managers approve |
| CFG Kanban Cycle | One production/replenishment instance | Mostly system-controlled |
| CFG ERP Command | Audited instruction sent to ERPNext | Read-only investigation |
| Process Execution | Kanban view of one Job Card operation | Operated through console |
| Operation Progress | Immutable incremental operator report | Created, not edited |
| WIP Ledger | Quantity releases and handoffs | System-created |
| Event | Audit timeline entry | System-created |
| Exception | Something needing review | Managers acknowledge/resolve |
| Handling Unit | Identity of a pallet/container within a Cycle | Created and scanned operationally |

Additional records:

| Record | What it means | Creation/maintenance rule |
|---|---|---|
| CFG Kanban Operation Summary | Aggregate of one operation across one or more Job Card lanes | System-created/recalculated |
| CFG Kanban Runtime Allocation | One Process/Station card allocation against one existing Job Card | Operator confirmation creates it |
| CFG Kanban Process Task | Production-cycle prerequisite/control/QC task | Generated from Master when Cycle is created |
| CFG Kanban Task Schedule | Reusable definition for independent service work | Supervisor setup |
| CFG Kanban Task | One service occurrence | Scheduler, service-point resolution, or authorised request |
| CFG Kanban Media | Private S3 object registry and audit metadata | Upload workflow; not a normal attachment |
| CFG Kanban Dispatch Queue | Current workstation sequence entry | System-maintained from executions |
| CFG Kanban Sequence Change | Immutable supervisor sequencing audit | System-created |
| CFG Kanban Operator Session | Employee identity on a shared terminal | QR/PIN login creates it |

## 15. State references

Reusable Card states:

```text
Available
→ Consumed
→ Signal Created
→ Replenishment Requested
→ Production Released
→ In Production
→ Produced
→ In Transit
→ Available
```

Blocked can be entered from operational states. Inactive is used for retired/replaced cards.
Runtime Process/Station closure drives Produced → Available. The physical replenishment flow does
the same automatically after ERPNext Work Order, Job Card, finished-goods receipt, and Process Task
evidence are complete. Scanning an older stuck physical Card retries this reconciliation. Do not
force these states manually.

Cycle states:

```text
New → Signalled → Released → In Production
→ Production Complete → Waiting FG Receipt → Completed
```

Hold, Blocked, and Cancelled represent exceptions or stopped work. Runtime Cycle completion is
implemented; final physical replenishment completion remains under development.

## 16. Troubleshooting

### “Card cannot move from … to …”

The requested action skipped a controlled state. Open the Card, Cycle, Signal, and Event Timeline
to identify the last successful step. Do not manually overwrite the state. For approval flow, the
expected pre-Work-Order sequence is Signal Created → Replenishment Requested → Production Released.

### No Sales Demand was created

Check:

- Sales Order is submitted.
- Sales Order Item warehouse matches the Master Destination Warehouse.
- Master is Active and Enable Sales Order Trigger is enabled.
- Item matches exactly.
- Customer/Territory/Production Line scope value matches the Sales Order.
- There is no equally ranked matching Master.
- For stock policy, a shortage actually exists.

### Demand is Blocked because no reorder level exists

For Stock Replenishment, add the matching warehouse under Item → Reorder, or intentionally select
Kanban Override and enter a positive Minimum Stock Override on the Master.

### Demand is Blocked because cards are unavailable

Review Cards for the Master. A card must be Active, Available, have no Active Cycle, and not be
reserved for another Demand. Do not create additional cards merely to clear an unexplained block;
first reconcile the physical cards and active production.

### MTO approval says the Item must have Batch enabled

Open the Item, enable Has Batch No, set Shelf Life in Days, and confirm the BOM. Re-evaluate and
approve only after the product's batch policy is correct.

### MTO Manufacture Stock Entry rejects the Batch

Open the related CFG Kanban Demand or Cycle and use its Planned Batch on the finished Item row. Raw
materials may use their own appropriate batches; the restriction described here is for the MTO
finished output Item.

### MTO output exceeds authorized maximum

Do not bypass the validation. Obtain a revised customer PO authorization and update/amend the
commercial document through the approved ERPNext process. The current released Demand does not
automatically recalculate after approval, so supervisor/technical review is required.

### Work Order was not created

Open the related CFG ERP Command:

- Pending — not yet executed.
- Running — execution began but did not complete.
- Failed — review Last Error and correct the ERPNext prerequisite.
- Completed — open Target Document.

Common causes include missing/default BOM, company mismatch, warehouse configuration, ERPNext
permissions, or invalid Work Order data.

### Job Cards do not appear in Kanban Operator

Confirm the Work Order has generated ERPNext Job Cards and that each Job Card Operation exactly
matches an Operation Profile on the Master. Refresh or update the Work Order so ERP feedback can
synchronize them.

### Print format fails or shows A4

Confirm the current app version is deployed, migration and build completed, cache was cleared, and
the correct CFG Kanban print format was selected with no letterhead. Browser preview may display
surrounding whitespace; verify the downloaded PDF page dimensions and printer scaling.

### Print Service Point QR button is missing

Open and save the Task Schedule, enable **Permanent Service Point QR**, and configure a Location,
Asset, or Workstation. Reload the form. Printing requires Manufacturing Manager or System Manager
access. The QR is optional; disabling it does not stop scheduled task generation.

### Scheduled Service Task did not appear

Confirm the schedule is Active, Next Due On is reached, and the site scheduler is enabled and not
paused. Review **Recurring Task Overlap Policy**: **Prevent While Open** intentionally suppresses a
new occurrence while an older occurrence remains actionable. Also check whether **Skip Listed
Holidays** matched the occurrence date.

### Timestamp or GPS does not appear on a photo

The watermark is applied only through **Take Timestamped Photo**, and that action appears only when
the task is **In Progress**. A phone may offer its camera from the ordinary **Upload Photo / PDF /
File** picker, but that path intentionally preserves the selected file unchanged. Allow location
permission for the ERP site, take a new photo through the timestamped button, wait for upload
verification, and then open the original. Camera and geolocation require HTTPS.

### Location permission was denied

Enable location permission for the ERP site in the browser/device settings and retry. Timestamped
execution capture fails closed without a geotag. Use ordinary file upload only when the evidence is
an existing file and must not be presented as a live execution capture.

### QC failure placed the Cycle on Hold

Open the linked Process Task and Kanban Exception. Do not manually overwrite the Cycle status. An
authorised Supervisor records the corrective action and selects **Authorise Retest**. Enter the new
sample and measurements through the same controlled task. The hold clears only after the required
QC outcome and verification are satisfied.

## 17. Audit and control rules

- Do not manually create ERPNext Work Orders to bypass a blocked Kanban Signal.
- Do not duplicate or manually alter registered physical codes. A QR and Code 128 on the same tag
  may encode the same visible value; that is one identity, not two tags.
- Use Replace Card or Replace Tag so the former identity becomes unusable.
- Supply a stable event token when a scanner retries the same action.
- Review Events for who, when, state transition, quantity, device, and linked document.
- Review ERP Commands for every controlled ERPNext write.
- Treat WIP Ledger and Operation Progress as audit records, not editable worksheets.
- Resolve Exceptions with an explanation instead of deleting them.

## 18. Deployment and update procedure

Before every development-server deployment, take a site backup. Then update the server:

```bash
cd ~/frappe-bench/apps/cfg_kanban
git pull upstream main

cd ~/frappe-bench
bench --site site1.local migrate
bench build --app cfg_kanban
bench --site site1.local clear-cache
bench restart
```

After deployment, confirm:

```bash
bench --site site1.local list-apps
```

Then perform one controlled test before using the new behavior with production data.

## 19. First-pilot acceptance checklist

- [ ] Development site backup completed.
- [ ] App migration and build completed without errors.
- [ ] Settings configured in Approval mode.
- [ ] Test Item, BOM, Operations, and Warehouses verified.
- [ ] One Master created with unique operation sequences.
- [ ] Dynamic progress fields tested.
- [ ] Physical card identity printed and scanned.
- [ ] One Signal approved.
- [ ] Exactly one Cycle and Work Order created.
- [ ] ERPNext Job Cards mirrored as Process Executions.
- [ ] Progress and WIP releases verified.
- [ ] Reprint audit verified.
- [ ] Handling-unit tag printed and lifecycle tested.
- [ ] One optional permanent Service Point QR printed and resolved, if used.
- [ ] Holiday skip and Supervisor Cancel/Bypass disposition tested.
- [ ] Process Task QR and Sample Traveller QR tested, if used.
- [ ] QC Pass, Fail/Hold, and authorised retest path tested.
- [ ] Timestamped GPS photo, multiple-file upload, original view, and recoverable Remove tested.
- [ ] Stock Sales Order calculation verified, if used.
- [ ] MTO PO tolerance, dedicated Batch, and maximum-output validation verified, if used.
- [ ] Events, ERP Commands, and Exceptions reviewed.
- [ ] Known incomplete cycle-closure behavior understood by pilot users.

## 20. Shared-terminal operator access

The Kanban Operator page uses two separate identities:

- The shared terminal stays signed in to ERPNext with a restricted user that has the **Kanban Terminal** role.
- Each operator scans a personal Kanban QR. The operator is an ERPNext **Employee** and does not need an ERPNext User account.

An administrator creates one **CFG Kanban Operator Profile** for each Employee, selects the
operator permissions and optional workstation/operation restrictions, and uses **Credentials →
Issue New QR Credential**. The credential is shown once for QR-label generation; only its hash is
stored. Issuing another credential immediately invalidates the previous QR.

The credential dialog provides these outputs:

- **Print CR80 Horizontal Card (85.60 × 53.98 mm):** the landscape operator card with Employee
  photo, employee number, designation, department, Kanban role, and QR credential.
- **Print CR80 Vertical Card (53.98 × 85.60 mm):** the portrait version of the same secure operator
  credential for vertical badge holders.
- **Print Large QR Sheet:** a larger A4 presentation of the same card for enrollment or testing.
- **Download QR:** saves the QR image without the identity-card layout.

Maintain the operator photograph in the linked ERPNext **Employee → Image** field before issuing the
credential. If no Employee image exists, the card prints an initials placeholder. In the browser
print dialog use **Actual Size / 100%**, disable headers and footers, and select the correct CR80 card
media or card-printer driver. Because the raw credential is never stored, print or download it while
the issuance dialog is open; issuing it again creates a new QR and invalidates the old card.

The active operator is always displayed at the top of the Operator page. **Switch Operator (F2)**
arms the page for the next operator credential; a successful login replaces the previous active
session on that terminal/station. Sessions also expire after the
inactivity period configured in **CFG Kanban Settings** (15 minutes by default).

Kanban progress, events, and ERP commands retain both identities: the Employee who performed the
work and the ERPNext User used by the terminal. Job Card start/complete actions write the Employee
into ERPNext's standard Job Card time logs.

For repeated development testing, a System Manager may enable **Enable Administrator Operator
Bypass (Development Only)** in **CFG Kanban Settings**. This option is disabled by default and is
available only while signed in as the literal **Administrator** account. The Operator page then
allows Administrator to select any active Employee and start a development proxy session without
scanning an operator QR. The selected Employee and Administrator are both retained in the audit
trail, and the proxy is clearly marked in the Operator page. Disable this setting before production
use; disabling it also invalidates an active proxy session at its next server-authorized action.

## 21. Current limitations and planned manual updates

The following are not complete in the current build:

- Final FG receipt confirmation, Cycle closure, and reusable physical-card return for the normal
  replenishment flow. Runtime Process/Station allocation closure is implemented.
- Automatic planned Batch selection on Manufacture Stock Entry.
- Delivery Note enforcement of the Sales Order's dedicated MTO Batch.
- Controlled assistant for Sales Order quantity amendment/accepted excess.
- Underproduction and incomplete-batch supervisor disposition.
- PWA installation, offline scan queue, and device management.
- Full Start/Complete dynamic-field capture and arbitrary Job Card field mapping.
- Automated email alerts and complete command retry orchestration.
- Supplier Kanban and Sales Order fulfillment allocation beyond the implemented demand controls.
- Customer/vehicle delivery beyond the implemented intercompany Movement Manifest container flow.
  Purchase Receipt activation, reusable-container content episodes, complete-container intercompany
  dispatch/receipt, exact serial membership and controlled child split/merge, Stock Entry-confirmed
  production tracing, scoped scanner-first floor access, same-company tagged
  Warehouse transfers, and scan-any-tag upstream/downstream genealogy exploration are implemented.

This file is the maintained manual source. Update its version, date, affected sections, and revision
history whenever a user-visible workflow changes.

## 22. Exact configuration-field reference

This section exists specifically to prevent a user or an LLM from substituting a plausible but
nonexistent field name. Child-table rows are opened from their parent form; they are not separate
business documents to create from the workspace.

### CFG Kanban Master child tables

**Operation Profiles** (`operation_profiles`) uses the fields listed in Step 2. Its most important
exact Select values are:

- **Execution Mode**: `Single Workstation`, `Parallel Workstations`, `Sequential Split`.
- **Runtime Selection Priority**: `Oldest Work Order First`, `Smallest Remaining First`,
  `Largest Remaining First`.
- **Start Rule**: `Previous Operation Complete`, `Minimum Qty Available`,
  `Minimum Percentage Available`, `Full Batch Available`, `No Dependency`.
- **Output Reporting Mode**: `Completion Only`, `Incremental`.
- **Handoff Mode**: `Physical Card Handoff`, `Digital Quantity Handoff`, `Full Batch Handoff`,
  `Automatic Handoff`.

**BOM Component Material Flow** (`material_flow_rules`) is loaded from the selected ERPNext BOM.
Its exact row fields are **BOM Component** (`item_code`, read-only), **Item Operation**
(`operation`, read-only), **Source Warehouse** (`source_warehouse`), **BOM Qty** (`bom_qty`,
read-only), and **Stock UOM** (`stock_uom`, read-only). Edit the Item/Operation relationship in the
BOM, not in this snapshot. The Master refuses missing component rows after this table is loaded.

**Process Task Profiles** (`process_task_profiles`) exact setup fields are **Task Key**
(`task_key`), **Task Name** (`task_name`), **Sequence** (`sequence`), **Category**
(`task_category`), **Task Type** (`task_type`), **Linked Operation** (`linked_operation`),
**Trigger Point** (`trigger_point`), **Mandatory** (`mandatory`), **Blocking** (`blocking`),
**Responsible Role** (`responsible_role`), **Workstation** (`workstation`), **Asset** (`asset`),
**Checklist** (`checklist`), **Controlled QC Task** (`qc_controlled`), **Enable Sample Traveller QR**
(`enable_sample_traveller`), **Test Method** (`test_method`), **Specification Reference**
(`specification_reference`), **Allow Conditional Release** (`allow_conditional_release`),
**Require Supervisor Verification** (`require_supervisor_verification`), **Validity Duration
(Hours)** (`validity_duration_hours`), **Reuse While Valid** (`reuse_while_valid`), and **Completion Rule**
(`completion_rule`).

Exact Trigger Point values are `Before Cycle Start`, `Before Operation Start`,
`After Operation Complete`, `Before WIP Release`, `Before FG Release`, and `Before Cycle Close`.
An operation-specific trigger requires Linked Operation. Controlled QC requires Test Method and
Specification Reference, cannot be reused, and is the only valid basis for a Sample Traveller or
Conditional Release.

**Operator Field Definitions** (`operator_field_definitions`) exact fields are **Applies To**
(`definition_scope`: Operation, Process Task, Standalone Task), **Operation** (`operation`),
**Process Task Key** (`process_task_key`), **Field Key** (`field_key`), **Label** (`label`),
**Field Type** (`field_type`: Data, Int, Float, Check, Select, Date, Datetime, Text), **Mandatory**
(`mandatory`), **Capture On** (`capture_on`: Start, Progress, Complete, Verify), **Options**
(`options`), **Default Value** (`default_value`), **Precision** (`precision`), **Minimum Value**
(`min_value`), **Maximum Value** (`max_value`), **Unit** (`unit`), **Read Only** (`read_only`),
**Map to Job Card** (`map_to_job_card`), **Job Card Field** (`job_card_field`), **Display Order**
(`display_order`), **Visible Condition** (`visible_condition`), and **Validation Message**
(`validation_message`). Generic arbitrary Job Card field mapping is not implemented; the two mapping
fields are metadata for a controlled future mapping.

**Visible Condition** is a safe dependency expression referring to another **Field Key** in the
same task/operation scope and the same Capture On stage. Supported forms are:

| Condition | Result |
|---|---|
| `damage_found` | Visible when `damage_found` is checked/truthy |
| `damage_found == 1` | Visible when the Check field is checked |
| `damage_found == Yes` | Same Check-field test in human-readable form |
| `result == Fail` | Visible when a Select/Data field exactly equals `Fail` |
| `result != Pass` | Visible when the value is not `Pass` |
| `eval:doc.damage_found == 1` | Accepted compatibility form; behaves like `damage_found == 1` |

Do not enter arbitrary JavaScript. When a condition evaluates false, the field is hidden, its
Mandatory flag is disabled for that action, and it is excluded from submitted evidence. The form
reacts immediately when the controlling value changes. Unknown Field Keys, cross-stage references,
self-references, dependency cycles, and unsupported expressions are rejected when the Schedule or
Master is saved.

### Sales-demand fields added to CFG Kanban Master

These are Custom Fields installed by the app and therefore do not appear in the base Master JSON:

| Screen label | Internal fieldname | Exact choices / use |
|---|---|---|
| Enable Sales Order Trigger | `enable_sales_order_trigger` | Enables evaluation on submitted Sales Orders |
| Sales Trigger Mode | `sales_trigger_mode` | Proposal Only; Approval Required |
| Threshold Source | `threshold_source` | ERPNext Warehouse Reorder Level; Kanban Override |
| Minimum Stock Override | `minimum_stock_override` | Required only for Kanban Override |
| Demand Scope | `demand_scope` | General; Customer; Sales Territory; Production Line |
| Demand Scope Value | `demand_scope_value` | Exact matching value for a non-General scope |
| Master Priority | `master_priority` | Higher number wins after scope specificity |
| Production Policy | `production_policy` | Stock Replenishment; Customer Make-to-Order |
| MTO Extra Production Tolerance % | `mto_extra_tolerance_pct` | Master maximum |
| Plan Work Order to Maximum Permitted Qty | `mto_plan_to_maximum` | MTO planning switch |
| MTO Batch Policy | `mto_batch_policy` | One Batch per Sales Order Line |
| Existing Stock Usage | `mto_existing_stock_usage` | Prohibited |
| Order Consolidation | `mto_order_consolidation` | Prohibited |
| Minimum Shortage to Propose | `sales_minimum_shortage_qty` | Ignore smaller stock shortages |
| Maximum Cards per Sales Order | `sales_max_cards_per_order` | Recommendation safety cap |

### CFG Kanban Task Schedule

Use this record only for standalone service/maintenance work. Exact main fields are **Schedule Name**
(`schedule_name`), **Active** (`active`), **Company** (`company`), **Task Name** (`task_name`),
**Category** (`task_category`), **Trigger Type** (`trigger_type`), **Permanent Service Point QR**
(`service_point_enabled`), read-only **Service Point Code** (`service_point_code`), **Recurring Task
Overlap Policy** (`overlap_policy`), **Holiday Generation Policy** (`holiday_policy`), **Holiday
List** (`holiday_list`), interval/calendar values, **Next Due On** (`next_due_on`), **Complete Within
(Hours)** (`default_due_hours`), **Default Priority** (`priority`), **Responsible Kanban Role**
(`responsible_role`, linked to CFG Kanban Responsibility), responsibility/location fields,
**Checklist** (`checklist`), **Dynamic Form Fields** (`task_field_definitions`), **Require Supervisor
Verification** (`require_supervisor_verification`), and **Instructions** (`instructions`).

Exact Trigger Type choices are `Time Interval`, `Calendar Schedule`, `Meter / Usage`,
`Manual Request`, `Condition`, and `Emergency Event`. Only Time Interval and Calendar Schedule are
generated by the hourly scheduler. A Time Interval needs positive Interval Value and Next Due On; a
Calendar Schedule needs positive Calendar Repeat (Days) and Next Due On. The other trigger types
require a controlled manual/API event in the current implementation.

### CFG Kanban Operator Profile

Create one profile per Employee. Exact fields are **Employee** (`employee`), **Active** (`active`),
**Kanban Role** (`kanban_role`: Operator, Senior Operator, Supervisor), optional PIN controls,
permissions **Start**, **Complete**, **Verify Process Tasks**, **Report Reject**, **Partial Complete /
Progress**, **Override**, **Reopen**, **Responsible Roles** (`responsibilities`), **View All Service
Tasks** (`view_all_responsibilities`), plus **Allowed Workstations** and **Allowed Operations** child
tables. A profile role alone does not grant an action: the corresponding permission checkbox and
scope must also allow it. The terminal ERPNext user separately needs the `Kanban Terminal` role (or
manager/system-manager access).

### CFG Kanban Skill and Employee Competency

Create Skills before competency approvals. Exact Skill fields include **Skill Code** (`skill_code`),
**Skill Name** (`skill_name`), **Skill Category** (`skill_category`), **Active** (`active`),
**Certification Reference Required** (`requires_certification`), **Expiry Date Required**
(`requires_expiry_tracking`), **Default Validity (Days)** (`default_validity_days`), and neutral
**External Standard / SOP Reference** (`external_standard_reference`).

Create one submitted **CFG Kanban Employee Competency** per non-overlapping Employee/Skill approval.
Exact controls include **Employee** (`employee`), read-only **Operator Profile** (`operator_profile`),
**Skill** (`skill`), **Competency Level** (`competency_level`: L0–L4), **Authorized to Work
Independently** (`can_work_independently`), **Authorized to Supervise Trainees**
(`can_supervise_trainees`), **Effective From** (`effective_from`), **Valid Until** (`valid_until`),
assessment/certification references, and neutral external evidence/revision snapshots. Submit only
after manager review. Use the form's **Authorization** actions for controlled suspension,
reactivation, or revocation.

### CFG Kanban Crew Requirement Profile and Workstation Crew Requirement

Submit the reusable Profile before selecting it elsewhere. Exact Profile controls are **Requirement
Code** (`requirement_code`), **Requirement Name** (`requirement_name`), optional **Company**
(`company`), **Active** (`active`), **Revision** (`revision`), **Crew Mode** (`crew_mode`), **Minimum
Direct Workers** (`minimum_direct_workers`), **Minimum Assistants** (`minimum_assistants`),
**Trainee Policy** (`trainee_policy`), **Active Supervisor Presence** (`supervision_presence`), and
**Maximum Trainees per Supervisor** (`max_trainees_per_supervisor`).

Each **Required Skills** row records **Crew Role** (`participation_role`: Direct Worker, Qualified
Lead, or Active Supervisor), **Required Skill** (`skill`), **Minimum Competency**
(`minimum_level`), **Minimum People** (`minimum_people`), and the explicit P01 authorization flags.

A submitted **CFG Kanban Workstation Crew Requirement** contains **Company** (`company`),
**Workstation** (`workstation`), optional **Operation** (`operation`), approved **Crew Requirement**
(`crew_requirement_profile`), activity/effective dates, and approval audit. A blank Operation applies
the rule to every operation performed at that Workstation.

### CFG Kanban Material Trace Policy

Create at most one record per **Company** (`company`) and **Item** (`item_code`). Exact controls are
**Enabled** (`enabled`), **Trace Level** (`trace_level`: ERP Document Only, Batch Pool, Exact Handling
Unit), **Purchase Receiving Tags** (`receiving_tag_policy`), **Production Input Tags**
(`production_input_tag_policy`), **Production Output Tags** (`production_output_tag_policy`),
**Require Batch on Tagged Quantity** (`require_batch`), and **Allow Receipt Quantity Across Multiple
Tags** (`allow_partial_tag_quantity`). Each stage policy has exactly three choices: `No Physical
Tag`, `Optional Physical Tag`, and `Required Physical Tag`.

Do not create policies merely to confirm that tags are unnecessary. A missing or disabled policy is
the intentional non-blocking default: ERP Document Only and No Physical Tag at all stages. Exact
Handling Unit trace requires at least one stage to be Optional or Required.

### ERPNext Custom Fields owned by the app

- Work Order, Job Card, Stock Entry, Material Request, Purchase Order, and Purchase Receipt:
  **Kanban Controlled** (`cfg_kanban_controlled`), **Kanban
  Cycle** (`cfg_kanban_cycle`), and **Kanban Signal** (`cfg_kanban_signal`).
- Work Order also has **Production Origin** (`cfg_production_origin`), **MTO Sales Order**
  (`cfg_sales_order`), and **MTO Planned Batch** (`cfg_planned_batch`).
- Job Card Time Log has **Kanban Progress** (`cfg_kanban_progress`) for idempotent quantity sync.
- Sales Order has **Kanban Production Line** (`cfg_production_line`), **Customer PO Allows Extra
  Quantity** (`cfg_po_allows_extra_qty`), **Customer PO Extra Tolerance %**
  (`cfg_po_extra_tolerance_pct`), and **PO Tolerance Reference** (`cfg_po_tolerance_reference`).
- Batch has **Sales Demand** (`cfg_sales_demand`) and **Sales Order** (`cfg_sales_order`).

### User-entered versus system-maintained

Users normally create Settings, Masters, Cards, Operator Profiles, Task Schedules, Dashboard
Profiles, Handling Units, Logistics Routes, Customer Scan Points, and Tag Families. The app normally
creates Demands, Signals, Cycles, ERP Commands,
Process Executions, Operation Summaries, Runtime Allocations, Process Tasks, service Task
occurrences, Progress, WIP Ledger, Events, Sequence Changes, Operator Sessions, Route
Reconciliations, and Media registry
records. Material Trace records and Handling Unit Quantity Ledger rows are also system-created and
immutable. Supervisors
interact with those generated records only through their defined approval,
verification, disposition, reconciliation, recovery, or exception actions.

## 23. Buyer-owned purchase replenishment

## Automatic inventory threshold replenishment

Automatic threshold replenishment is optional. It creates a **digital Cycle and Signal** when the
destination Warehouse balance falls below a configured minimum. It does not consume, reserve, or
change the state of a reusable physical Kanban Card.

Configure these exact fields on **CFG Kanban Master**:

| Form label | Fieldname | Purpose |
|---|---|---|
| Enable Automatic Threshold Trigger | `enable_inventory_threshold_trigger` | Includes the active Master in hourly evaluation |
| Inventory Balance Source | `inventory_balance_source` | System-set from the Item type |
| Inventory Threshold Source | `inventory_threshold_source` | Use Master override quantities or the Item Reorder row for the destination Warehouse |
| Reorder Point (Stock UOM) | `inventory_reorder_point_qty` | Trigger when observed balance is strictly below this value |
| Replenish Up To (Stock UOM) | `inventory_target_qty` | Quantity the generated demand attempts to reach |
| Maximum Replenishment Quantities per Trigger | `inventory_max_cards_per_run` | Caps one generated Signal |
| Automation Level | `automation_level` | Automatic, Approval, or Signal Only behaviour inherited by the generated Signal |

For an ERPNext stock Item, the balance source is **ERPNext Projected Quantity** from the Item and
destination Warehouse `Bin`. The threshold can come from the Master override or from the exact
ERPNext **Item Reorder** row for that Warehouse. With the ERPNext source, the reorder point is the
Warehouse Reorder Level and the target is that level plus Warehouse Reorder Qty; when Reorder Qty is
zero, one Master Replenishment Qty is used. ERPNext remains the inventory system of record. Do not
enable ERPNext automatic reorder execution and CFG Kanban automatic threshold triggering for the
same Item/Warehouse pair, because both controllers could create purchasing demand.

For a non-stock Item, the balance source is **Kanban Operational Inventory**. It is the sum of
released, active and available CFG Kanban Handling Unit quantities for the same Company, Item, and
destination Warehouse. This balance never creates an ERPNext Stock Ledger quantity. Non-stock
threshold control is supported for **Purchase Replenishment** and **Transfer**, but not Production.

Only one active threshold controller is allowed for a Company, Item, and destination Warehouse.
While its Signal is Open, Validated, Waiting Approval, Executing, Blocked, or Failed, another
threshold Signal is not created. This prevents hourly duplicate demand. Cancellation or completion
allows a later evaluation to create a new episode when the balance is still below the threshold.

The requested quantity is calculated as whole Kanban replenishment quantities:

```text
required quantity = Replenish Up To - observed balance
number of replenishments = round required quantity upward / Replenishment Qty
requested quantity = number of replenishments × Replenishment Qty
```

The configured maximum limits the number created in one Signal. Purchase minimum order quantities,
pack multiples, and supplier UOM conversion are still applied later by the existing Purchase
Replenishment workflow.

The scheduler evaluates enabled Masters hourly. For setup and testing, save the Master and select
**Inventory Control → Evaluate Threshold Now**. The Master records the last check time, observed
balance, and result. Threshold-created Signals appear in the **Production Supervisor Action Center**
with the observed balance, reorder point, target, and balance source. Approval and cancellation use
the normal Signal controls.

Use **Control Type** (`control_type`) = **Purchase Replenishment** when the item is bought from a
normal third-party supplier. This V1 flow does not represent buyer-directed contract manufacturing;
that richer vendor execution model remains V2.

The Card's **Replenishment Qty (Stock UOM)** (`replenishment_qty`) is always canonical ERP stock
quantity. **Item Stock UOM** (`stock_uom`) is fetched from the Item and cannot be replaced with the
supplier unit. Configure the Item's UOM conversion table and optional **Default Purchase Unit of
Measure**, then select **Purchase UOM** (`purchase_uom`) on the Master. The app snapshots **Stock
Qty per Purchase UOM** (`purchase_uom_conversion_factor`) and displays **Calculated Replenishment
Qty (Purchase UOM)** (`purchase_replenishment_qty`). ERPNext's rule is preserved: Stock Qty equals
Purchase Qty multiplied by Conversion Factor.

For example, a 500 Kg Card with Purchase UOM Bag and conversion 25 creates a request for 20 Bags /
500 Kg. Card, stock, BOM, WIP, tag and genealogy quantities remain Kg. Purchase quantities, partial
receipts and tolerance entry use Bags. The Cycle records both units explicitly.

On **CFG Kanban Master**, also configure **Default Supplier** (`default_supplier`), **Destination
Warehouse** (`destination_warehouse`), optional **Supplier Pack Multiple (Purchase UOM)**
(`supplier_pack_size`), **Minimum Order Qty (Purchase UOM)** (`minimum_order_qty`), **Purchase Order
Multiple (Purchase UOM)** (`purchase_order_multiple`), **Submit Material Request on Approval**
(`auto_submit_material_request`), **Purchase Execution Mode** (`purchase_execution_mode`), optional
**Master Auto-submit PO Value Limit** (`master_auto_submit_po_value_limit`), **Receipt Posting Mode**
(`receipt_posting_mode`), **Allow Partial
Receipt** (`allow_partial_receipt`), **Kanban Over-receipt Tolerance %**
(`over_receipt_tolerance_pct`), and optional **Rejected Warehouse** (`rejected_warehouse`).

The operational sequence is:

1. Consume the reusable Card. The app creates a **Purchase Replenishment** Signal and Cycle.
2. For Approval mode, open the Signal and select **Approve Purchase Replenishment**. Automatic
   mode performs the same command immediately. Signal Only does not create an ERP document.
3. ERPNext Material Request is always the first purchasing record. **Material Request Only** stops
   here for manual buying; **Create Draft Purchase Order** maps the submitted MR and sets the Master
   supplier; **Create and Submit Purchase Order** also submits the PO when ERP prerequisites and the
   configured monetary ceiling permit it. **CFG Kanban Settings → Maximum Purchase Automation** is
   the global safety ceiling. A positive **Maximum Auto-submit PO Value** and the optional Master
   limit cause higher-value POs to remain Draft for review; zero means no monetary ceiling after
   Submitted PO automation is explicitly enabled.
4. A Purchase Order made from the linked Material Request is associated automatically when the
   link is unambiguous. Otherwise open the Cycle and use **Purchase Replenishment → Select Purchase
   Order**. The submitted PO must match Company, Supplier, and Item, and the reason is audited.
5. At receipt, open the Cycle and choose **Purchase Replenishment → Receive Purchased Item**. The
   dialog states the Purchase UOM, Stock UOM, conversion and both outstanding quantities. Enter
   Delivered Qty, Accepted Qty, and Rejected Qty in the displayed Purchase UOM, plus warehouses and
   Supplier Delivery Note. Delivered must equal Accepted plus Rejected and may not exceed
   outstanding PO purchase quantity plus the configured tolerance.
6. **Create Draft Purchase Receipt** leaves ERPNext submission to an authorised stock user.
   **Submit After Receiver Confirmation** submits simple items immediately. Batch-controlled,
   serial-controlled, or incoming-inspection items deliberately remain Draft until their standard
   ERPNext batch/serial/Quality Inspection information is completed. **Require Supervisor Approval**
   also creates a Draft.
7. Only a submitted Purchase Receipt updates ERPNext stock. Kanban separates physical delivery
   from usable replenishment: **Physically Received Qty** includes accepted and rejected material,
   while **Usable Fulfilment Qty** includes accepted material plus a later approved concession.
   Partial usable fulfilment leaves the Cycle and Card active as **Partially Received**. A receipt
   with rejected material becomes **Receipt Exception** and the Card does not recycle merely because
   ERPNext marks the PO physically received. Purchase Invoice and payment remain the later ERPNext
   accounts workflow.

### Rejected supplier material and usable completion

A non-zero **Rejected Qty** posts that stock into the Master's **Rejected Warehouse** through the
same submitted ERPNext Purchase Receipt. It does not mean the material was returned to the supplier
and it does not create a supplier credit. The app creates one **CFG Kanban Receipt Disposition** per
rejected Purchase Receipt row. Open it from the Cycle with **Purchase Replenishment → Open Receipt
Dispositions** and record one controlled decision:

- **Supplier Replacement**: create and submit ERPNext's Purchase Return from the rejected warehouse.
  The returned quantity reopens native PO receipt capacity; receive the replacement against the same
  controlled Cycle. The Cycle completes only when cumulative accepted replacement reaches the usable
  order quantity.
- **Supplier Credit / Return**: use the native Purchase Return for physical stock and let Accounts
  create the applicable Debit Note/Purchase Invoice Return. Do not update stock twice in the Debit
  Note when the Purchase Return already removed it.
- **Accept by Concession**: first submit a native Material Transfer Stock Entry from the exact
  Rejected Warehouse to the Cycle's Destination Warehouse. Then choose **Confirm Concession
  Transfer** on the disposition. The app validates Item, source, destination and quantity before
  adding the concession to usable fulfilment.
- **Scrap / Dispose**: move or dispose of the rejected stock through the applicable submitted native
  ERP document. Disposal does not satisfy the replenishment shortage.
- **Short Close**: a Purchase/Stock/Manufacturing/System Manager may use **Short-close Usable
  Shortage** on the Cycle with a mandatory reason. This releases only the replenishment shortage;
  it never moves rejected stock and never creates a supplier credit. Any open physical disposition
  remains visible until its native stock action is resolved.

Use **Refresh Receipt Result** after correcting or posting native ERP return/transfer documents.
The Cycle displays the exact labels **Accepted Qty (Purchase UOM)**, **Rejected Qty Awaiting Physical
Disposition**, **Approved Concession Qty**, **Usable Fulfilment Qty**, **Supervisor Short-closed
Qty**, and **Receipt Disposition Status**. Only usable fulfilment plus authorised short-close can
complete the purchase Cycle and recycle its reusable Card.

### Tablet receiving at the warehouse

Create a **CFG Kanban Card** with **Card Type** (`card_type`) = **Location Card**, **Location
Purpose** (`location_purpose`) = **Supplier Receiving**, and set **Current Warehouse**
(`current_warehouse`) to the exact ERPNext receiving Warehouse. Use **Print Kanban → Print Supplier
Receiving Location Card**. Assign **Supplier Receiving** under the warehouse employee's **CFG Kanban
Operator Profile → Responsibilities**.

At the Logistics Panel, identify the operator and either scan the original Purchase Kanban Card to
open its exact submitted PO item, or scan the permanent receiving Location Card to see all submitted
PO quantities outstanding for that Warehouse. After a warehouse scan, scan the original Purchase
Kanban Card to select the exact order. Only an operator with Override permission receives the
**Supervisor Select** fallback. Enter supplier Delivery Note and delivered, accepted and rejected
quantities in Purchase UOM. A submitted simple-item receipt immediately offers onsite preprinted-tag
activation. Controlled Batch, Serial, Quality Inspection, Draft or approval receipts must first be
completed and submitted in ERPNext; Kanban does not claim stock or release physical tags early.

Material Request, Purchase Order, and Purchase Receipt receive app-owned read-only trace fields
**Kanban Controlled**, **Kanban Cycle**, and **Kanban Signal**. Supplier/company/item mismatch,
fully received PO rows, and over-receipt create a visible **CFG Kanban Exception** and block the
purchase Cycle. A purchase Signal with an effective PO or submitted Receipt will not be silently
rolled back; resolve the ERP purchasing record and reconcile instead.

### Permanent warehouse operations card

For a broader warehouse view, create another **Location Card**, set **Location Purpose** to
**Warehouse Operations**, and select the exact **Current Warehouse**. Save it and use **Print
Kanban → Print Warehouse Operations Card**. Scan it only in the Logistics Operator Panel.

It displays data already authorized by the logged-in Operator Profile:

- submitted supplier orders awaiting receipt at this warehouse, when the operator has Supplier
  Receiving responsibility;
- open Movement Manifests whose source or destination is this warehouse and whose route is within
  the operator's responsibilities; and
- active Transfer and Withdrawal cards involving this warehouse.

The warehouse card is a read-only access point. Scanning it never receives stock, creates a
Manifest, or consumes a Card. The operator must open the exact listed transaction and explicitly
confirm its controlled action. For normal receiving, scan the original Purchase Kanban Card after
reviewing the warehouse queue; only an authorized supervisor receives cardless selection.

## 24. Reconciliation and recovery decision table

| Situation | Correct action | Do not do |
|---|---|---|
| Accidental non-Sales Signal; no production activity | Open Signal → Cancel and Roll Back; enter reason | Delete Signal/Cycle/Card |
| Sales Order Demand must stop before release | Cancel Sales Order or controlled Demand workflow | Use Signal rollback directly |
| More than one Work Order claims one Cycle | On Cycle select the effective submitted Work Order and reason; inactive WO must have no activity | Edit Cycle link directly |
| Submitted WO has operations/Job Cards but Kanban missed them | Use Work Order **Sync to Kanban** / reconcile action | Create Process Executions manually |
| Draft legacy WO was created without BOM rows | Use **Reload Draft Work Order BOM** after correcting BOM | Submit an operation-less WO |
| Submitted WO has no operation rows | Correct BOM/WO; ERPNext cannot generate valid Job Cards | Fabricate unrelated Job Cards |
| Legacy Process/Station Cycle predates runtime allocation and has no activity | Use **Release Legacy Runtime Card** with reason | Force Card state to Available |
| Any progress, WIP, submitted Stock Entry, Job Card time log, or production quantity exists | Raise/resolve a production Exception; automatic rollback is deliberately refused | Delete audit/ERP records |
| Service occurrence falls on closure/holiday after generation | Supervisor Cancel or Bypass with reason | Delete occurrence |
| QC Result is Fail | Correct cause, Supervisor Authorise Retest, enter a new controlled result | Manually clear Cycle Hold |

Signal rollback cancels/deletes only activity-free ERP documents, marks Cycle and Signal Cancelled,
returns the Card to Available, clears Active Cycle, and records Events. A submitted Work Order can be
cancelled only while ERPNext permits it and the code has found no production/material activity.

## 25. Multi-company logistics and customer allocation (Packages A-B, C1-C2B, and D1-D3)

Package A installs the configuration and physical-identity foundation. Package B adds the controlled
intercompany Movement Manifest, source-company Delivery Note, destination-company Purchase Receipt,
ERP feedback, and scan-first Logistics Operator Panel. Package C1 now adds Customer Site scanning,
Company-specific vehicle Warehouse validation, and an immutable Delivery Session. Package C2A adds
physical Stock Tag/customer allocation and reservation. Package C2B creates the controlled customer
Delivery Note and waits for ERPNext submission before changing tag stock. Package D1 captures and
validates customer proof before closing the session. Package D2A records a controlled post-delivery
return claim and inspection custody without adding available stock. D2B-D2C control accounting and
physical stock disposition after QC. D3 reconciles each Company-specific lorry Warehouse at route
end without changing ERP stock. Billing Batch grouping remains a later increment. The locked design is in
`docs/MULTI_COMPANY_LOGISTICS_ARCHITECTURE.md`.

### CFG Kanban Logistics Route

Create one directional route for each permitted movement. Select **Route Type** (`route_type`) as
**Intercompany Handover** or **Internal Warehouse Transfer**. Exact fields include **Route Name**
(`route_name`), **Active** (`active`), **Source Company** (`source_company`), **Source Warehouse**
(`source_warehouse`), optional **Transit Warehouse** (`transit_warehouse`), **Destination Company**
(`destination_company`), **Destination Warehouse** (`destination_warehouse`), **Internal Customer**
(`internal_customer`), **Selling Price List** (`selling_price_list`), **Internal Supplier**
(`internal_supplier`), **Buying Price List** (`buying_price_list`), **Handover Mode**
(`handover_mode`), **Auto-submit Dispatch Delivery Note** (`auto_submit_dispatch_dn`), **Auto-submit
Receipt Purchase Receipt** (`auto_submit_receipt_pr`), **Billing Frequency**
(`billing_frequency`), and the three Responsibility links. Internal routes instead expose
**Internal Transfer Posting Mode** (`internal_transfer_mode`: Direct Transfer or Goods in Transit),
**Auto-submit Internal Dispatch Stock Entry** (`auto_submit_internal_dispatch`), and
**Auto-submit Internal Receipt Stock Entry** (`auto_submit_internal_receipt`).

Intercompany routes require different Companies, the internal Customer/Supplier and both Price
Lists. Internal Warehouse Transfer routes require the same Company and never require those parties
or Price Lists. All route types reject Warehouses belonging to the wrong Company. For internal
**Goods in Transit**, the Transit Warehouse is mandatory and must differ from both endpoints.

### CFG Kanban Customer Scan Point

Create one record per physical delivery address. Exact identity fields are **Printed Customer Site Code**
(`site_code`), **Site / Branch Name** (`site_name`), **Active** (`active`), **Selling Company**
(`selling_company`), **Customer** (`customer`), **Delivery Address** (`customer_address`), optional
**Territory** (`territory`), **Route Reference** (`route_reference`), and **Default Selling Price
List** (`default_price_list`).

Set **Auto-submit Customer Delivery Note** (`auto_submit_delivery_note`) separately for each site.
When unticked, the floor action creates a Draft Delivery Note for ERP review. When ticked, the same
action submits only after all native ERPNext mandatory values pass validation. Operators cannot edit
Item rates; rates come from the locked Selling Price List and applicable Item Price.

Proof settings are **Proof Policy** (`proof_policy`: Required, Optional, Unattended Delivery
Allowed, No Proof Required), **Require Recipient Name**, **Require Signature**, **Require
Photograph**, **Require GPS**, and **Require Unattended-delivery Reason**. The printed `site_code` is
the primary scan value. **Internal UUID Alias** is generated automatically as a system fallback.

Return settings are **Enable Customer Return for QC** (`enable_customer_return_qc`), **Enable Wrong
Delivery Note Correction** (`enable_delivery_note_correction`), **Default Inspection Custody
Location** (`return_inspection_location`), **Delivery Correction Return Warehouse**
(`correction_return_warehouse`), and **Auto-submit Correction Return Delivery Note**
(`auto_submit_correction_return_dn`). The inspection Location is physical non-stock custody. Only
the separate wrong-DN correction workflow can post stock through an ERPNext Return Delivery Note.

### Customer Delivery Session, stock allocation, and customer Delivery Note

1. Open the ERPNext **Warehouse** representing the stock physically carried by the lorry. Set
   **Vehicle Warehouse** (`cfg_is_vehicle_warehouse`) and enter **Physical Vehicle Reference**
   (`cfg_vehicle_reference`), for example `LORRY-01`. The Warehouse must be active, non-group, and
   belong to the Customer Scan Point's **Selling Company**. When one physical lorry carries stock
   for two Companies, create a separate Warehouse for each Company and give both the same physical
   vehicle reference.
2. On the driver's **CFG Kanban Operator Profile**, add the Kanban Responsibility **Customer
   Delivery**. Migration creates this responsibility if it does not already exist.
3. Open **Logistics Operator Panel**, identify the operator, and scan the Customer Site's printed
   `site_code` in normal lookup mode.
4. Confirm the displayed Customer, exact Delivery Address, Selling Company, route, and proof policy.
   Select the correct Company-specific lorry Warehouse and choose **Lock Customer and Vehicle**.
5. The panel creates **CFG Kanban Delivery Session** and displays the locked Customer/site/Company,
   physical vehicle, lorry Warehouse, price list, and proof-policy snapshot. The operator cannot
   start a second active site session until the first is completed or cancelled.
6. An empty session in **Customer Identified** state may be cancelled with a mandatory reason. The
   session and its Event history are preserved; they are never deleted.
7. Select **Start Allocation Scanning**. Scan either one activated Stock Tag or one reusable
   container. The Stock Tag must be Active/Released, belong to the locked Selling Company, be in
   the selected lorry Warehouse, have matching ERPNext stock, and not be reserved by another open
   transaction.
8. For an ordinary non-serialized Stock Tag, accept the full available quantity or enter a partial
   quantity. A serialized tag is always allocated as one complete physical unit. The unallocated
   balance remains against the same physical tag in the same lorry Warehouse.
9. Scanning a reusable container expands every currently loaded Stock Tag and reserves every one at
   full quantity. A contained tag cannot be allocated separately; scan the container. Contents
   cannot be changed while any container allocation is active.
10. Stop scanning and select **Confirm Customer Allocation**. The session becomes **Awaiting
    Confirmation**. To correct it before ERP posting, select **Release**, enter a mandatory reason,
    adjust the allocation, and confirm again. Release creates an Unreserve ledger event and never
    deletes the historical allocation.
11. Select **Create Delivery Note**. If ERPNext requires extra parent fields or a child table such as
    **Sales Team**, the panel displays those exact mandatory inputs. Complete all rows; Sales Team
    percentages must total 100%.
12. With site auto-submit off, the session becomes **ERP Document Pending** and the panel links the
    Draft Delivery Note. Current Qty and Reserved Qty do not change yet. An authorized ERPNext user
    reviews and submits the Draft.
13. With site auto-submit on, the command submits immediately after validation. In both modes, only
    the submitted ERPNext Delivery Note changes the session to **Delivered**, changes each allocation
    to **Delivered**, reduces the Handling Unit Current Qty, and releases its reservation. A partly
    delivered ordinary tag remains Active in the same lorry Warehouse with its balance. A zero-balance
    tag becomes Empty. Complete reusable-container contents are unloaded and the container becomes
    Empty for reuse.
14. If the site's Proof Policy is **No Proof Required**, submitted Delivery Note feedback closes the
    session automatically as **No Proof Recorded**. For every other policy the session remains
    **Delivered** and is still active until the proof step is completed.
15. Select **Capture / Close Delivery**. The panel displays only dispositions allowed by the immutable
    site-policy snapshot. **Required** permits Attended only; **Optional** permits Attended or No Proof
    Recorded; **Unattended Delivery Allowed** permits Attended or Unattended.
16. For an attended delivery, enter the recipient and capture signature/photo/GPS according to the
    configured flags. **Take Delivery Photo** uses server time plus device geolocation, visibly stamps
    both onto the image, and uploads the original evidence through the private S3 registry. The
    signature pad is saved as separate PNG evidence. **Upload File** accepts supporting images, PDF,
    or video but does not substitute for a required timestamped photograph or signature.
17. For an unattended delivery, enter the reason when configured and supply required photo/GPS.
    Recipient name and signature are waived for that disposition. Select **Submit Proof and Close**.
    Server validation, not the browser, enforces every requirement. A successful submission creates
    **CFG Kanban Delivery Proof**, links it to the session, and changes the session to **Closed**.
18. Supervisors open **Customer Delivery Proofs** from the CFG Kanban workspace to see the immutable
    policy snapshot, recipient/disposition, submitter, capture time/GPS, thumbnails, and temporary
    **Open Original** links. Presigned URLs are generated on demand and are never stored. When GPS is
    optional and was not captured, **GPS Location Captured** is off; stored zero coordinate fields are
    only database-safe placeholders and must not be interpreted as a real `0,0` delivery location.
19. If ERPNext rejects creation or submission, the session becomes **Exception** without consuming
    tagged quantity. Correct the ERP prerequisite and retry **Create Delivery Note**.
20. Cancel a submitted controlled Delivery Note only after the goods are physically returned to the
    lorry. The cancellation restores the tag quantity and reservation, reopens the session as
    **Awaiting Confirmation**, raises a visible Exception, and increments the Delivery revision. The
    next **Create Amended Delivery Note** is linked to the cancelled document. Cancellation is blocked
    if a partly remaining tag or reusable container has already entered a later transaction. Once a
    Delivery Proof has been submitted, cancellation is blocked; use the later controlled customer
    return workflow so accepted-delivery evidence is never silently reversed.

### Customer Return and wrong Delivery Note correction (Package D2A)

There are only two floor choices. They must not be mixed.

**Customer Return for QC:** Enable Customer Return Workflows globally, enable the site workflow, set
the inspection Location, assign drivers **Customer Return**, and assign inspectors **Customer Return
QC**. The driver scans the Customer Site, selects **Customer Return for QC**, records Item, optional
Batch/expiry/tag, physical quantity, condition, details, reason and optional customer representative,
then issues the printable **CFG Temporary Return Note**. The open Return Case accepts multiple
timestamped/geotagged camera photographs and supporting files/PDFs through the private S3 registry;
files can be removed and replaced until QC completion, after which the evidence is read-only. No
previous Delivery Note or Sales Invoice is required. The note explicitly
says it is not a tax Credit Note, e-Invoice, or stock receipt. Its QR contains the Return Case number.

QC scans that QR, selects **Receive and Start QC**, then **Complete QC Result**. Received quantity
cannot exceed intake; Accepted plus Rejected must equal Received; every row needs a disposition.
Accepted quantity changes the case to **QC Completed - Accounting Pending**, but remains unavailable
ERP stock. Only afterward does a supervisor/accountant choose the exact Sales Invoice, approved
historical substitute, or No Credit and use the controlled ERPNext/e-Invoice workflow. Driver and QC
screens never choose or create accounting credit documents.

### Accountant decision after Customer Return QC (Package D2B)

After QC produces accepted quantity, an authorized **Accounts User**, **Accounts Manager**, **Sales
Manager**, or **System Manager** opens the **CFG Kanban Return Case** in Desk. The positive credit
path additionally requires Sales Invoice Create permission; No Credit does not. Select **Accounting
→ Prepare Accounting Decision**. This action is intentionally not available in the floor
Logistics/QC panel.

The dialog shows the immutable QC-accepted Item quantities and recent submitted, non-return Sales
Invoices filtered to the Return Case **Selling Company** (`selling_company`) and **Customer**
(`customer`). Choose one of these exact values in **Accounting Source Basis**
(`accounting_source_basis`):

- `Exact Sales Invoice` when accounting identifies the intended source invoice;
- `Substitute Historical Sales Invoice` when an older return cannot be traced and accounting
  approves another invoice for the same Company, Customer and sufficient remaining Item quantity;
- `No Credit` when the claim is rejected financially.

**Accounting Decision Notes** (`accounting_decision_notes`) are mandatory. Exact/substitute choices
also require **Source Sales Invoice** in the dialog. The server rejects a Draft, cancelled, return,
wrong-Company, wrong-Customer, missing-Item, or insufficient-uncredited-quantity source.

A credit decision creates one idempotent non-stock Draft ERPNext Sales Invoice Return. Its **Is
Return** is enabled, **Return Against** is the approved source, **Update Stock** is disabled, and its
negative quantities exactly equal the QC-accepted quantities. The Return Case records **Accounting
Decision By**, **Accounting Decision On**, **Accounting Decision Notes**, **Final Credit Document**
and **Credit Document Status**. Preparing the Draft creates no GL Entry, e-Invoice submission, or
Stock Ledger Entry. The accountant must open that Draft, complete all native/custom tax, account,
cost-centre and e-Invoice requirements, then submit it in ERPNext.

On valid ERPNext submission, the Return Case becomes `Accounting Completed` / `Completed`. The
submission hook blocks Company, Customer, source, Update Stock, Item or quantity divergence. If the
submitted return is cancelled, the case reopens to `QC Completed - Accounting Pending`, records the
cancellation and increments its internal accounting revision so one controlled replacement Draft
can be prepared. `No Credit` creates no Sales Invoice Return and changes the case to `Accounting
Completed` / `No Credit Approved`; an active credit Draft must be cancelled before No Credit can be
chosen.

Package D2B is an accounting handoff only. Accepted goods still remain in inspection custody; a
separate controlled stock-disposition function posts quarantine, rework, disposal or accepted-stock
movement in ERPNext as described below. CFG Kanban Core does not depend on the external `bagos_changes` custom **Credit
Note** DocType. The driver-facing **CFG Temporary Return Note** remains the non-tax custody record,
and the final credit is a standard ERPNext Sales Invoice Return.

### Accepted return physical-stock disposition (Package D2C)

After QC completion, a **Stock Manager**, **Quality Manager**, or **System Manager** opens the **CFG
Kanban Return Case** and selects **Stock → Prepare Stock Disposition**. A Warehouse receipt also
requires Stock Entry Create permission. Accounting may still be pending: the accounting and physical
tracks are independent, and the case closes only after both are complete.

Every **QC Accepted Qty** must be conserved across one or more rows in **Accepted Quantity
Dispositions** (`disposition_lines`). Multiple rows may reference the same intake row to split its
quantity. Select one exact **Physical Disposition** (`disposition`) per split:

- `Receive to Quarantine` — receive into a non-group quarantine Warehouse;
- `Receive for Rework` — receive into a non-group rework Warehouse;
- `Return to Available Stock` — receive into an approved available-stock Warehouse;
- `Dispose Without Stock Receipt` — record controlled physical disposal without adding ERP stock.

Receipt choices require **Target Warehouse** (`target_warehouse`) in the Return Case **Selling
Company**, an approved **Valuation Rate** (`valuation_rate`), and **Disposition Reason** (`reason`). A
zero rate is allowed only when the ERPNext Item explicitly permits zero valuation. Disposal requires
a reason and must not have a Warehouse. **Overall Disposition Decision Notes** are also mandatory.
The server rejects missing/excess quantities, another case's row, wrong-Company/group Warehouses,
invalid rates, or any split total that differs from the accepted quantity.

When any split requires receipt, CFG Kanban creates one Draft `Material Receipt` Stock Entry. It
contains only receipt splits; disposal splits are excluded. **Customer Return Case**
(`cfg_return_case`) and the immutable disposition-row identities tie every Stock Entry Detail back to
the decision. The Stock Manager completes any ERPNext v15 Serial/Batch Bundle requirements and
submits the entry. Before submission, ERPNext stock does not change. The submit guard prevents
changes to Company, Stock Entry Type, Item, controlled quantity, Warehouse or approved valuation
rate. Submitted ERP feedback marks receipt rows `Posted`, disposal rows `Disposed`, and **Stock
Disposition Status** (`disposition_status`) `Completed`.

If every split is `Dispose Without Stock Receipt`, the decision completes without a Stock Entry or
Stock Ledger Entry. A linked Draft Material Receipt can be removed only through **Stock → Discard
Return Material Receipt Draft** with an audit reason; then a corrected decision may be prepared. A
submitted Material Receipt cancellation uses ERPNext's normal cancellation control, reverses its
stock effect, increments **Disposition Revision**, and reopens the physical track for one controlled
replacement.

The combined Return State is intentional:

- stock complete while accounting is pending: `QC Completed - Accounting Pending`;
- accounting complete while stock is pending: `Accounting Completed`;
- accounting and stock complete: `Closed`.

### End-of-route vehicle stock reconciliation (Package D3)

Use D3 at route opening and route closing for each Company-specific lorry Warehouse. The physical
lorry may be shared, but every Company Warehouse has its own ERP stock balance and therefore its own
`CFG Kanban Route Reconciliation`.

1. On the operator's **CFG Kanban Operator Profile**, add **Logistics Reconciliation** and permit
   Start and Complete. Give Supervisor Override only to supervisors who may cancel a count.
2. In **Logistics Operator Panel**, identify the operator and select **Route Stock Count**. Select
   the exact **Company-specific Vehicle Warehouse** (`vehicle_warehouse`). The app records **Opening
   Snapshot On** (`period_start`) and each Item/Batch **Opening ERP Qty** (`opening_qty`) from
   submitted ERPNext Stock Ledger Entries. Only one open count is allowed per Warehouse.
3. At route end select **Start Tag Count Scanning**. Scan every activated Stock Tag physically in
   that Warehouse. A reusable-container scan expands its currently loaded Stock Tags; do not scan
   those child tags again. A contained tag must be counted through its container. Duplicate, empty,
   unactivated, wrong-Company, and wrong-Warehouse tags are rejected. If a counted tag's quantity,
   Warehouse, identity state, or container membership changes, evaluation requires it to be removed
   and rescanned.
4. Stop scanning and select **Enter Loose / Untagged Count**. Enter only physical quantity not
   represented by a scanned tag, grouped by exact Item and optional Batch. This is how ordinary
   ERP-only stock participates without forcing physical tagging.
5. Select **Evaluate against ERPNext**. The server refreshes submitted ERP stock at **Final Count
   Evaluated On** (`period_end`). For every Item/Batch it records:

   ```text
   Opening ERP Qty + Net ERP Movement = Expected Closing Qty
   Scanned Tag Qty + Loose / Untagged Qty = Physical Counted Qty
   Physical Counted Qty - Expected Closing Qty = Variance Qty
   ```

6. A zero variance changes state to `Ready to Close`. Select **Close Balanced Route**. The immutable
   record stores closing operator/time, and every exact scanned tag receives **Last Reconciled On**.
   Closure is blocked while that Company/Warehouse still has an unfinished Customer Delivery
   Session or physically open Movement Manifest.
7. Any variance changes state to `Variance` and creates a Critical `CFG Kanban Exception` with type
   `Route Stock Variance`. The app does not make a Stock Entry or alter Handling Unit quantity.
   Recount the physical stock, or let an authorized stock user post the correct ERPNext adjustment.
   Evaluate again. After balance is restored, closing requires **Recount / Resolution Notes**
   (`resolution_notes`) and may link **ERP Correction Document Type**
   (`correction_reference_doctype`) plus **ERP Correction Document** (`correction_reference`). The
   linked Exception becomes Resolved.
8. Use **CFG Kanban → Route Reconciliations** for audit and print **CFG Route Reconciliation
   Report**. It shows opening, ERP movement, expected, tagged, loose, counted and variance quantities
   plus the exact tag list and resolution evidence.

Counting is observational. ERPNext submitted stock documents remain authoritative. Never create a
fake Kanban ledger movement or delete delivery history merely to force a zero variance.

**Correct Wrong Delivery Note:** Retrieve the completed Delivery Session and select **Correct Wrong
Delivery Note**. The exact submitted Delivery Note is mandatory and reversal quantities cannot exceed
its remaining delivered rows. CFG Kanban creates only a Return Delivery Note against that DN. The
site controls Draft versus auto-submit and the selling-company return Warehouse. If a submitted Sales
Invoice already references the DN, the panel raises Accounting Attention and forcibly retains the
Return DN as Draft; accounting must be corrected separately before ERPNext permits final posting.

### CFG Kanban Tag Range Registry

Use this DocType for a controlled block of preprinted tags that already exists physically. One
registry can cover thousands of labels without creating thousands of database rows.

Example configuration:

| Screen field | Example | Meaning |
|---|---:|---|
| **Range Registry Code** (`registry_code`) | `FZD-STK-1000-1999` | Human-readable registry name |
| **Issuing Company / Number Namespace** (`issued_company`) | Manufacturing Company | Permanent issuer of the printed number series |
| **Printed Prefix** (`prefix`) | `FZD-STK` | Exact, case-sensitive characters before the number |
| **Starting Number** (`start_number`) | 1000 | First permitted main tag |
| **Ending Number** (`end_number`) | 1999 | Last permitted main tag |
| **Number Width** (`number_width`) | 4 | Required fixed number width, including leading zeroes |
| **Child Separator** (`child_separator`) | `-` | Separator before a detachable child number |
| **Detachable Child Count** (`child_count`) | 5 | Permits `FZD-STK1000-1` through `FZD-STK1000-5` |

After Save, verify **First Main Tag**, **Last Main Tag**, **Total Main Tags**, and **Potential Main +
Child Identities**. The app rejects overlapping or nested registry namespaces that could make one scan
ambiguous. One registry is limited to 100,000 main tags and twenty children per family.

An unused code inside an active range resolves as **Tag Range Candidate**. Lookup is read-only: it
does not create a Tag Family, Handling Unit, stock, or ledger entry. The first controlled Handling
Unit Save locks the registry row, creates that one exact **CFG Kanban Tag Family** plus its child
identities, and activates only the scanned identity. This makes repeated scans and simultaneous
activation idempotent while preserving the existing exact-family lifecycle.

After the first family is materialized, the prefix, range, width, separator, child count, and issuing
Company are immutable. Deactivate the old registry and create a new one for a changed print series.
Do not delete a used registry. **Materialized Tag Families**, **Last Materialized Tag Family**, and
**Last Materialized On** provide the audit summary; the form button opens the exact created records.

The issuing Company is the permanent identity namespace. It does not change during intercompany
handover. The Handling Unit's **Inventory Company** and **Current Warehouse** change only after
submitted ERPNext Delivery Note/Purchase Receipt feedback confirms the movement.

### CFG Kanban Tag Family

Enter **Preprinted Main Tag Code** (`family_code`), **Detachable Child Count** (`child_count`, zero
to twenty), and **Issuing Company / Number Namespace** (`issued_company`). The app registers the
visible main identity and numbered child identities and also creates hidden internal UUID aliases.
Example: `MFG-STK1000`, `MFG-STK1000-1` through `MFG-STK1000-5`. Both a printed barcode and QR may
carry the same visible code. The UUID does not need to exist on the physical tag.

Visible codes are unique across the whole ERP site. Use a controlled issuer/company prefix for
each number series, as logistics companies do with waybill numbers. The issuing Company remains
fixed while **Inventory Company** may change through later intercompany handover. Use an exact Tag
Family for a one-off or exceptional code. For a large serial block use **CFG Kanban Tag Range
Registry**; do not import every unused family. Child identities are generated automatically from
`child_count` in either workflow.

The printed number is an identity, not a password. Scanning it never bypasses the active operator
session, authorization, route/company validation, lifecycle rules, idempotency, or ERPNext stock
confirmation.

When a Handling Unit uses a registered family code, the matching identity is activated and cannot
be reused. A child Stock Tag requires a parent Handling Unit and transfers its starting quantity
from that parent through the immutable ledger.

### Extended CFG Kanban Handling Unit

**Tag Kind** (`tag_kind`) is Main Stock Tag, Child Stock Tag, or Reusable Container. Relevant new
fields include **Tag Family**, **Parent Handling Unit**, **Root Handling Unit**, **Child Index**,
**Inventory Company**, **Current Warehouse**, **Physical Custodian / Vehicle**, **Packing
Timestamp**, **Expiry Date Snapshot**, **Identity State**, **Movement State**, **Quality State**, and
the read-only original/current/reserved/available quantity caches.

A Stock Tag cannot be activated without Inventory Company and Current Warehouse. After activation,
these fields are not ordinary editable planning fields: ERPNext stock feedback and controlled
logistics movements own their changes. For a legacy Stock Tag that was saved with a blank warehouse,
use **Kanban Actions → Assign Initial Warehouse**. The recovery requires a reason, validates that the
Warehouse belongs to the Inventory Company, confirms sufficient ERPNext Item/Batch stock, and writes
an auditable location ledger event. It cannot be used to relocate an already assigned or reserved
tag.

The future destination is deliberately not fixed on the Handling Unit. Select a directional
**Logistics Route** when creating the Manifest; its source and destination Company/Warehouse values
are snapshotted onto that Manifest. The destination may remain undecided before the Manifest is
created, but it must be selected before dispatch is confirmed because ERPNext Delivery Note and
Purchase Receipt construction requires an unambiguous destination. Do not wait until Manifest close
to decide it.

A Reusable Container may exist without a production Cycle, Item, or opening quantity. It must be
loaded through controlled ledger events. Existing production Handling Units retain their internal
UUID aliases and old scan state; migration adds the new identity/state fields and an opening ledger
balance without deleting history. Scan resolution accepts the visible code first and old UUID
aliases second, so previously printed labels continue to work.

### CFG Kanban Handling Unit Quantity Ledger

Ledger rows are system-created, read-only, non-deletable, and idempotent. Do not create or edit them
from Desk. Current, reserved, and available quantities can be rebuilt from their signed source and
destination deltas. Package B uses these rows to reserve Manifest quantities and audit the
intercompany location/ownership transition.

### Kanban Operational Inventory Balance report

Open **CFG Kanban → Operational Inventory Balance** when a combined quantity is required rather
than one row per physical tag. The report groups active Handling Units by Inventory Company,
Current Warehouse, Item and Stock UOM and displays:

- **Total Quantity** — combined current quantity across all included tags;
- **Reserved Quantity** — quantity committed to open controlled transactions;
- **Available Quantity** — total quantity currently free for another transaction;
- **Released Available** and **Hold / Restricted** quantities; and
- the number of physical tags included in the balance.

For an ERP stock Item the report also displays **ERP Actual Qty**, **All Active Tagged**,
**Untagged ERP Qty**, and **Tagged Excess**. These columns are the stock-adoption control:
`Untagged ERP Qty = max(ERP Actual Qty - all active tagged quantity, 0)`. A positive Tagged Excess
is an exception that must be investigated; it is not another source of stock.

The default **Inventory Control Mode** filter is **Kanban Operational Inventory**, meaning Items
whose ERPNext **Maintain Stock** setting is disabled. Select **ERP Stock** or clear the filter to
review tagged stock Items. When all displayed rows use one UOM, the report header also shows the
combined Total, Reserved and Available quantities. It deliberately does not combine unlike UOMs.

The default **Display Mode** is **Summary**. Select **Tag Detail**, or click **View Tags** beside an
**Active Tags** count, to list the exact active physical identities behind that balance. Drill-down
retains the current Inventory Control and Quality filters and narrows Company, Warehouse, Item and
UOM to the selected summary row. Each detail row begins with the human-readable **Container / Tag
Label** and the **Physical Scan Code**. For a manufactured fill inside a permanent Production
Output Container, the label comes from that container's **Permanent Container / Compartment
Reference** (falling back to its description or scan code), while **Physical Container** links to
the permanent container record. **Audit Identity Code** deliberately retains the immutable internal
fill identity such as `VCONT-...`; it is audit evidence and is not the operator-facing container
name. The remaining columns include Batch, current/reserved/available quantities, Quality,
Movement State, Custodian/Vehicle, immediate source/destination, last reconciliation and last scan
time. Use **Summary View** to return. Empty, Void and Replaced identities are not counted as Active
Tags. Give permanent output containers clear references such as `Container 1` and `Container 2` so
the report remains readable without weakening the unique audit identity.

### Tag finished goods that already exist in ERPNext

Use this procedure only when finished stock is already posted in ERPNext but has no physical CFG
Stock Tag. It creates identity and audit evidence; it never creates stock or records new production.

Prerequisites:

1. Register an active main-tag family or an active **CFG Kanban Tag Range Registry**.
2. Create and print a permanent **Warehouse Operations** Location Card for the exact Warehouse.
3. Assign **Stock Adoption** responsibility to the operator. A supervisor who may allocate the
   adopted tag to a Cycle also needs **Supervisor Override** permission.
4. ERPNext must show positive actual stock in that Company/Warehouse. Batch- and serial-controlled
   Items require their exact Batch and Serial Numbers.

Operator procedure:

1. Open **CFG Kanban → Logistics Operator Panel** and identify the operator.
2. Scan the Warehouse Operations Card. Select **Tag Existing ERP Stock**.
3. Select the finished Item and, when required, its exact Batch. Read the displayed **ERP Actual
   Stock**, **Already Active under Tags**, and **Available for New Tagging** values.
4. Scan one unused preprinted main tag, enter the physical quantity, Handling Unit Type, packing
   timestamp, expiry snapshot when applicable, and the reason why this stock was not already tagged.
   Enter only the quantity physically contained under that one tag. It may be lower than
   **Available for New Tagging**. Repeat the procedure with another unused tag for every remaining
   pallet, basket or container. For a serial-controlled Item, enter exactly one Serial Number per
   unit.
5. Confirm the physical Item, Batch, Warehouse, tag and quantity. The app locks the ERP Bin and
   matching Handling Units, recalculates the untagged balance, creates **CFG Kanban Stock Adoption**,
   activates the Handling Unit and posts one immutable quantity-ledger event.

The same retry event cannot create a duplicate adoption. A tag cannot be adopted if it is already
active, outside an active registered range, or would make active tagged quantity exceed ERP stock.

An authorized supervisor may select an eligible Cycle while adopting, or later allocate the adopted
record through the controlled API. Allocation is limited to a Production Master using **Stock
Replenishment**, the same Company, Item, Stock UOM and destination Warehouse, an open Cycle without
a Work Order, and the remaining Cycle target. The entire tag is reserved; split it first when only
part is required. Make-to-Order Cycles reject existing-stock allocation. Allocation updates the
Cycle's **Existing Stock Allocated Qty** and status but deliberately does not update Actual Good Qty,
Job Cards or ERP production. Release the allocation with a mandatory reason before using the tag for
another purpose.

Desk audit is available at **CFG Kanban → Existing Stock Adoptions**. The Handling Unit retains
**Origin ERP DocType = CFG Kanban Stock Adoption**, and the Event History and quantity ledger retain
the operator, session, balance snapshot and reason.

### Intercompany Movement Manifest — exact operating procedure

The dedicated page is **CFG Kanban → Logistics Operator Panel** (`/app/kanban-logistics`). It accepts
a fixed keyboard-wedge scanner in **Logistics Scanner**, or **Scan with Camera** on a phone/tablet.
The preprinted value such as `MFG-STK1000` is scanned directly; no printed UUID is required.
The Production Operator and Service Task panels both provide a visible **Logistics Panel** link and
reuse the same active operator session.

The scanner is read-only by default. In **Tag lookup ready** mode, scanning a Stock Tag displays its
Item, Batch, live quantity cache, Company, Warehouse/custodian, lifecycle, last movement, and related
Manifest history. It opens the most relevant authorized Manifest in view-only mode but does not add,
reserve, dispatch, or receive anything. A transaction can occur only after the operator explicitly
selects **Start Dispatch Scanning** or **Start Receipt Scanning** for the displayed Manifest. Opening
another Manifest, switching operator, refreshing, or selecting **Stop ... Scanning** returns to safe
lookup mode.

The Logistics Operator Panel uses the same lightweight 15-second live revision check. An unchanged
check returns only an opaque revision marker; it does not reload Manifest lists or the page. When a
Manifest, linked ERP document, Delivery Session, Return Case, internal transfer, or route count
changes, the panel refreshes the relevant list and currently open work in place. A persistent
scanner message and blue alert tell the operator that a Supervisor or parallel operator changed the
work. Transaction scan mode is preserved, and polling pauses while a confirmation or data-entry
dialog is open. Background checks do not extend the operator inactivity timeout. If another update
makes the currently armed dispatch/receipt mode invalid, the panel safely returns to lookup mode.
The safety check is repeated after every background request, not only when polling begins. A popup,
tag scan, button/keyboard interaction, frozen ERP action, or operator-session change that occurs
mid-request prevents that response from changing the visible Manifest or scanner state. Its revision
is deliberately left pending for the next safe polling interval, and live refresh never claims the
scanner focus.

Selecting an entry under **Open Movement Manifests** or **Recently Completed** loads the Manifest
into the active-work card and automatically scrolls that card below the sticky scanner header. The
card receives a short blue highlight and the scanner status confirms **Manifest loaded**. This jump
occurs only for the operator's deliberate list selection; background live refresh continues to
preserve the operator's current scroll position.

Prerequisites:

1. Create and activate the directional **CFG Kanban Logistics Route** with both Companies,
   Warehouses, intercompany Customer/Supplier, selling/buying Price Lists, and dispatch/receipt
   Responsibilities.
2. Give the operators a valid **CFG Kanban Operator Profile**, the applicable Responsibility, and
   Start/Complete permissions. Cancellation also requires Override permission.
3. The Stock Tag must already be an active **CFG Kanban Handling Unit** with Item, Stock UOM,
   released quality state, source Inventory Company, source Current Warehouse, and positive
   Available Qty. ERPNext must hold at least the same Item/Batch stock in that Warehouse.
4. A valid positive ERPNext **Item Price** must exist for both route Price Lists and the applicable
   Item/UOM/Batch.

Dispatch steps:

1. Identify the operator in **Logistics Operator Panel**.
2. Select **New Dispatch Manifest**, then select **Logistics Route**.
3. Select **Start Dispatch Scanning**. Confirm that the scanner indicator names the intended Manifest.
4. Scan every full Stock Tag. Package B deliberately rejects partial use of one tag; split it to an
   activated child identity first.
5. Select **Stop Dispatch Scanning**, then **Prepare and Reserve**. The quantity ledger reserves every
   scanned tag.
6. Select **Confirm Dispatch**. The app preflights the Delivery Note. Editable mandatory ERP fields
   appear in **Required Delivery Note Details**; mandatory child tables such as **Sales Team** use a
   multi-row grid and Sales Team percentages must total 100%. The app then creates one source-company
   Delivery Note through **CFG ERP
   Command**. If **Auto-submit Dispatch Delivery Note** is enabled, it is submitted immediately;
   otherwise an authorized ERPNext user must review and submit the draft.
7. Only submitted Delivery Note feedback changes the Manifest to **Awaiting Receipt** and the tags
   to **Intercompany Transit**. A draft Delivery Note does not claim the stock moved.

Receipt steps:

1. The receiving operator opens/scans the Movement Manifest number, such as `KMF-2026-00001`.
2. Select **Start Receipt Scanning**. If the current operator lacks the route's Receipt Responsibility,
   switch operator. The panel always shows **Receipt scans: X of Y**.
3. Rescan every physical tag listed on the Manifest. Unlisted tags and missing tags are rejected.
4. Select **Stop Receipt Scanning**, then **Confirm Receipt** after all rows are confirmed. This is
   blocked until the source Delivery Note is submitted.
5. The app creates the destination-company Purchase Receipt. When its own auto-submit setting is
   disabled, review and submit the draft in ERPNext.
6. Only submitted Purchase Receipt feedback changes the Manifest to **Received**, transfers the
   tag's **Inventory Company** and **Current Warehouse**, and makes destination stock operationally
   available. The generated Purchase Receipt also retains ERPNext's native **Inter Company
   Reference** and line-level **Delivery Note Item** references, so the standard Connections tabs
   on both documents show the complete Delivery Note ↔ Purchase Receipt relationship.

The terminal remembers the last open Manifest in that browser so a refresh after manual ERP
submission can reopen pending work. A terminal-state Manifest is not restored as the active screen
after a later page reload. Select **Done — Clear Screen** on a completed Manifest, or the toolbar
**Clear Screen**, to return immediately to the neutral scanner. **Recently Completed** is collapsed
by default and contains only the latest 10 authorized terminal-state Manifests; clearing the screen
does not delete this audit history. Older history remains accessible by scanning a Stock Tag,
scanning/entering the Manifest number, or using the normal Desk list.

The full operator identity block stays in the normal page flow instead of permanently occupying the
sticky header. When it scrolls fully out of view, the scanner's compact sticky status footer retains
the active operator name (and the role where screen width permits); scrolling back up restores the
full block and hides the compact name. **Change Operator** and **End Session** have equal-width, equal-height
touch targets in the full identity block. **Change Operator** makes the next credential scan replace
the active identity; it does not end or alter the current Manifest. The separate Logistics toolbar
also retains its prominent operator-change action.

An unused **Draft** or **Prepared** Manifest can be cancelled by an override-authorized operator
with a reason; prepared physical-tag reservations are released. For a Card-triggered Transfer, this
controlled cancellation also cancels its Signal and Cycle and returns the Card to **Available**.
While a Manifest is still Draft, both a scanned Stock Tag line and an **ERP Stock without Physical
Tag** line have a **Remove** correction action. Removal changes only the draft selection; it does not
move ERP stock. After an ERP document exists, use controlled ERP cancellation/recovery. Movement
Manifests are audit records and cannot be deleted. Package B does not itself load a lorry or perform
later intercompany billing. Customer Delivery Notes are created separately from a confirmed Package
C2 Delivery Session as described above.

### Transfer Kanban — same-Company Warehouse replenishment

Use this workflow when one Company replenishes stock from one Warehouse to another. It is separate
from intercompany handover and separate from customer delivery.

Configuration:

1. Create **CFG Kanban Logistics Route** with **Route Type** (`route_type`) = **Internal Warehouse
   Transfer**. Set the same source and destination Company, the exact source/destination Warehouses,
   dispatch/receipt Responsibilities, and choose **Direct Transfer** or **Goods in Transit**.
2. For Goods in Transit, set a same-Company Warehouse whose ERPNext **Warehouse Type** is
   **Transit**. Direct Transfer does not need one.
3. Create **CFG Kanban Master** with **Control Type** (`control_type`) = **Transfer**, the Item,
   card quantity, source/destination Warehouses, and **Internal Logistics Route**
   (`logistics_route`). The form requires the route Company/Warehouses to match exactly.
4. Configure **Warehouse Transfer Tags** (`warehouse_transfer_tag_policy`) on the Item/Company
   material-trace policy. **No Physical Tag** creates one ERP-stock Manifest line. **Optional
   Physical Tag** lets the operator either scan tags or select **Use ERP Stock Without Tags** before
   preparation. **Required Physical Tag** permits only active Stock Tag scans.
5. Create the Cards normally and assign logistics operators the route Responsibilities.

ERPNext stock mode changes the posting boundary:

- When **Maintain Stock** is enabled on the Item, ERPNext Bin/Stock Ledger and submitted Material
  Transfer Stock Entries remain authoritative. Tags mirror the confirmed physical movement.
- When **Maintain Stock** is disabled, CFG Kanban treats the Item as **Kanban operational
  inventory**. Physical Stock Tags are mandatory, untagged selection is unavailable, and the
  Handling Unit quantity ledger and Current Warehouse provide the operational trace. Confirmation
  does not create a fictional ERPNext Stock Entry. Both Direct Transfer and Goods in Transit are
  supported, including destination receipt scans for the latter. The Manifest stores this inventory
  control mode as an immutable release-time snapshot, so a later Item setting change cannot switch
  an active or historical movement between ERP and Kanban inventory logic.
- A Manifest created directly from the Logistics Operator Panel has no Item at creation time. Its
  first accepted tag locks the Manifest to either **ERP Stock** or **Kanban Operational Inventory**.
  The panel rejects mixing those inventory authorities in one Manifest. Direct-created non-stock
  movement is supported only on an **Internal Warehouse Transfer** route; intercompany movement
  continues to require ERPNext stock documents.

Operation:

1. In **Logistics Operator Panel**, scan the Transfer Card and select **Trigger Transfer Card**.
   Automatic Masters create the Manifest immediately; Approval Masters wait in the Supervisor
   Signal panel for **Release Internal Transfer**. The operator does not need ERPNext Desk access.
2. In **Logistics Operator Panel**, scan the same Card or open its Movement Manifest from the open
   list. The Card scan is read-only and shows the exact linked Manifest.
3. If physical tags are used, choose **Start Dispatch Scanning** and scan only the correct Item tags.
   The prepared total must equal the Card/Cycle quantity. With No Physical Tag, the planned ERP-stock row
   is already present and ERPNext Warehouse availability is checked during preparation.
4. Stop scanning and select **Prepare and Reserve**. Tagged lines are reserved in the Kanban ledger;
   untagged lines remain ERPNext stock and are not given a fictional tag.
5. Select **Confirm Dispatch**. For a stock Item, CFG Kanban creates a native ERPNext **Material
   Transfer Stock Entry**. If auto-submit is off, an authorized ERP user reviews and submits the
   draft. For a non-stock Item, the panel clearly says **Kanban operational inventory** and updates
   only the tagged Handling Unit location after operator confirmation.
6. **Direct Transfer:** submitted Stock Entry feedback moves each tag to the destination, marks the
   Manifest Received, completes the Cycle, and recycles the Card.
7. **Goods in Transit:** the submitted outward Stock Entry moves tagged units to the Transit
   Warehouse and changes the Manifest/Card to in transit. At destination, rescan every physical tag
   (untagged ERP stock needs confirmation but no fictional scan), then **Confirm Receipt**. The linked
   receipt Stock Entry uses ERPNext's outgoing Stock Entry reference. Only its submission completes
   the Manifest/Cycle and recycles the Card.

Safety rules:

- Internal routes never ask for Internal Customer, Internal Supplier, Price List, Delivery Note, or
  Purchase Receipt.
- The panel displays the effective **Warehouse Transfer Tags** policy. **No Physical Tag** already
  represents the complete Card quantity with an `ERP STOCK` line and therefore disables physical
  tag scanning. To scan existing Stock Tags, configure the exact Item/Company policy as **Optional
  Physical Tag** or **Required Physical Tag**, cancel the unused Cycle, and trigger a new Card Cycle
  so its immutable Manifest snapshot follows the corrected policy.
- A card-linked Manifest accepts only its Cycle Item and cannot exceed its planned quantity.
- Every scanned Stock Tag moves in full. If its available quantity is greater than the Card's
  remaining quantity, first split the exact required quantity to another active tag or use a Card
  quantity matching that complete tag. One physical tag cannot remain in two Warehouses.
- Untagged Card transfer is limited to non-batch, non-serial Items because the Card alone cannot
  identify the exact ERP batch/serial stock. Use Required Physical Tags for exact identity, or the
  manual ERPNext Material Transfer fallback when native batch/serial selection is required.
- A submitted controlled Stock Entry cannot be cancelled directly; use controlled recovery so the
  ERP stock ledger and physical-tag ledger cannot diverge.
- A Draft/Prepared Transfer Manifest and its Signal may be cancelled with a reason before any ERP
  document exists; tagged reservations are released and audit history is preserved.
- The older **Same-Company Tagged Warehouse Transfer** Stock Entry assistant remains a manual
  fallback for movements that did not originate from a Transfer Kanban Card.

### Withdrawal Kanban — consumables and indirect stock use

Use this workflow when stock leaves inventory for operational use without becoming another
Warehouse balance and without belonging to a BOM/Work Order—for example rubber bands, cleaning
chemicals, labels, gloves, or workshop consumables. Do not use Withdrawal for Warehouse-to-Warehouse
movement; use Transfer Kanban for that.

Configuration:

1. Create or enable the **Stock Withdrawal** Kanban Responsibility and add it to the applicable
   **CFG Kanban Operator Profile**. The profile must also allow Start and Complete.
2. Create **CFG Kanban Material Trace Policy** for the Item/Company if its physical-tag behavior must
   differ from the safe default. **Stock Withdrawal Tags** (`stock_withdrawal_tag_policy`) supports
   **No Physical Tag**, **Optional Physical Tag**, or **Required Physical Tag**. No policy defaults to
   No Physical Tag.
3. Create **CFG Kanban Master** with **Control Type** (`control_type`) = **Withdrawal**. Set the exact
   Company, Item, Card quantity in Stock UOM, source Warehouse, **Standard Withdrawal Reason**
   (`withdrawal_reason`), and Automation Level. Destination Warehouse, Logistics Route, BOM and WIP
   Warehouse are not part of this transaction.
4. Leave **Submit Material Issue on Operator Confirmation**
   (`auto_submit_withdrawal_stock_entry`) off during rollout. When enabled, the operator's final
   confirmation submits the native Stock Entry immediately.
5. Create/print the Card normally. A reusable physical Withdrawal Card represents the standard
   quantity. For a stock Item it returns to Available only after ERPNext confirms the Material
   Issue. For a non-stock Item it returns after the tagged Kanban withdrawal is confirmed.

For an Item with **Maintain Stock** disabled, physical Stock Tags are compulsory regardless of the
material-trace policy. No ERPNext Bin balance exists to support an untagged selection. The Handling
Unit ledger is operational traceability only; it does not create inventory valuation or accounting
stock. The Withdrawal Cycle stores this choice in its release-time Tag Policy snapshot, so later
changes to **Maintain Stock** apply only to newly released Cycles.

Operation:

1. Identify the operator in **Logistics Operator Panel**, then scan the Withdrawal Card.
2. Select **Trigger Withdrawal Card**. Automatic Masters release immediately; Approval Masters show
   a Waiting Approval Signal in **Kanban Supervisor**, where an authorized manager selects
   **Release Stock Withdrawal**. Scan the Card again after approval.
3. For **No Physical Tag**, the Cycle automatically selects the Card quantity from ordinary ERP
   stock. For **Optional Physical Tag**, select either **Add Stock Tag** one or more times or **Use ERP
   Stock without Tags**. For **Required Physical Tag**, scan active, released Stock Tags from the
   exact Item, Company, and source Warehouse. The selected total must equal the Card quantity.
4. Select **Prepare Withdrawal**. For a stock Item the app also checks ERPNext stock. Tagged rows are
   reserved in the handling-unit ledger so another movement cannot consume the same physical
   quantity.
5. For a stock Item, select **Create Material Issue**; the app creates one idempotent ERPNext Stock
   Entry. For a non-stock Item, select **Confirm Tagged Withdrawal**; it consumes only the Handling
   Unit balance and creates no Stock Entry. The stock-item path uses ERPNext's configured default
   **Stock Entry naming series** automatically; floor operators are not asked to choose document
   numbering. Administrators maintain that default in ERPNext Document Naming Settings.
6. With auto-submit off, an authorized ERPNext stock user reviews and submits the Draft Stock Entry.
   Draft creation does not reduce ERP stock and does not recycle the Card.
7. On submission, ERPNext reduces stock, tagged quantity is consumed and its reservation released,
   the Withdrawal Cycle/Signal complete, and the reusable Card becomes Available.

Safety and recovery:

- Untagged floor withdrawal is blocked for batch- or serial-controlled Items because the Card cannot
  identify the exact native batch/serial selection. Use Stock Tags for exact batch identity or use an
  authorized native ERPNext Material Issue when exact serial/bundle selection is required.
- A scanned Stock Tag must be active, released, outside a reusable container, and match Item,
  Company, Warehouse, and available quantity. Partial use follows **Allow Partial Tag Quantity**.
- Repeated scans and retries reuse the existing selection/ERP Command; they do not create a second
  Material Issue.
- Before any ERP document exists, the Supervisor can cancel the Signal with a reason. Prepared tag
  reservations are released and the Card returns to Available. An override-authorized operator may
  use **Discard Draft and Retry** for the linked unused Draft Material Issue, with a mandatory reason;
  its prepared reservation is retained for a safe retry. A submitted Stock Entry requires controlled
  recovery; do not delete history or manually edit Kanban status fields.

## 26. Guidance rules for another LLM

When using this file as context, an assistant must:

1. Name the exact Screen Label and internal fieldname from this guide; never invent a synonym.
2. First classify the request as physical replenishment, runtime Process/Station allocation,
   production Process Task/QC, standalone Service Task, Sales stock demand, or MTO demand.
3. Keep ERPNext as system of record for Work Orders, Job Cards, Stock Entries, Batches, and stock.
4. Never advise direct edits to system-created status fields or deletion of transactional history.
5. Ask for the Card Type, current Card/Cycle/Signal state, effective Work Order, Job Card state and
   docstatus, and relevant ERP Command before diagnosing a production flow.
6. For service recurrence, check scheduler state, Next Due On, overlap policy, and holiday policy.
7. For media, distinguish timestamped/geotagged live camera capture from unchanged file upload;
   never request AWS secret keys in ERPNext.
8. Treat Process Task and standalone Task as separate domains. Only Process Tasks gate production.
9. State an implementation limitation explicitly instead of proposing a field or button that the
   code does not contain.
10. Confirm the deployed Git revision/migration when the UI does not match this guide.

11. Treat customer Sales Invoice posting, loose-container delivery, and billing grouping as later
    increments. Packages C1-C2B identify the Customer
    Site, lock the Company-specific lorry Warehouse, reserve full/partial Stock Tag quantities, and
    confirm delivery only from submitted ERPNext Delivery Note feedback. Package B intercompany
    posting remains operational only through the Movement Manifest and submitted Delivery Note /
    Purchase Receipt feedback described above. D2A already covers Temporary Return Note custody,
    QC result handoff, and wrong-Delivery-Note physical correction; it never lets a floor operator
    select or post a Sales Invoice Return/Credit Note. D2B lets only an authorized Desk accounting
    user prepare the standard non-stock Draft Sales Invoice Return or record No Credit; ERPNext still
    owns tax/e-Invoice review and submission. D2C separately conserves accepted quantities across
    quarantine, rework, available-stock or disposal decisions; only submitted ERPNext Material
    Receipts change stock.

## 27. Revision history

| Version | Date | Change |
|---|---|---|
| 2.03 | 26 October 2026 | Added the separate CFG Job Architecture workspace inside the CFG Kanban app, grouping the existing identity, competency, crew-policy, live workforce, authorization, participation, Cycle, Process Execution, operation result, Event, and Exception records while clearly excluding unimplemented EODR, payroll, general-capacity, and cross-app schema |
| 2.02 | 24 October 2026 | Added lightweight 15-second live revision checks for Service and Logistics panels with in-place status refresh, persistent operator alerts, filter/scroll preservation and selected Manifest/ERP feedback monitoring; hardened the checks against dialogs or scanner/actions starting while a request is in flight by revalidating popup, input, frozen-action and operator-session state before every render; added deliberate Manifest-list selection scrolling with visible loaded-card feedback; also documented selective/full scanner-command printing with safe custom or translated display labels |
| 2.01 | 22 October 2026 | Added Workforce P06 scanner-first Workstation Crew controls to each Production execution lane: touch and printable QR commands for persistent crew open/join/break/resume/leave/main/context/close actions, existing Employee QR identity without terminal-login replacement, live crew/compliance status refresh, and controlled two-scan crew closure |
| 2.00 | 22 October 2026 | Added Workforce P05 Employee Job Participation Ledger: separate immutable participation segments for direct labour and oversight, crew join/break/resume/leave/role-change projection, compliance-hold stop/restart, completion/cancellation closure, explicit no-policy operator fallback, and no duplication of ERPNext Job Card production quantity |
| 1.99 | 22 October 2026 | Added Workforce P04 server authorization: effective competency/crew/lead/supervision/trainee/concurrency/expiry checks at allocation, start, progress, crew change, completion and WIP release; immutable Compliance Check snapshots; persistent Crew Compliance Holds with automatic resolution; unconfigured operations remain backward-compatible and ERPNext stays quantity-authoritative |
| 1.98 | 22 October 2026 | Added Workforce P03 persistent Workstation crew registry: approved expected-roster templates, one active Crew Session per Company/Workstation, scanned actual Membership intervals, break/resume/leave/main-operator/context controls, immutable Crew Events, and separate helper identity from terminal authentication |
| 1.97 | 22 October 2026 | Added Workforce P02: submitted reusable Crew Requirement Profiles, four crew modes, skill/level/role requirements, trainee and active-supervision controls, Operation/Profile assignment, Workstation safety restrictions, optional stricter Process/Station Card selection, and a conservative effective-policy resolver that never weakens a higher safety rule; runtime blocking remains P04 |
| 1.96 | 22 October 2026 | Added Workforce P01: manager-controlled Skill registry, submitted Employee competency approvals with L0–L4, explicit independent/supervision authorization, certification/expiry and overlap validation, controlled status audit, Operator Profile summary, workspace access, acceptance guide, and a neutral no-TrackQMS dependency boundary |
| 1.95 | 22 October 2026 | Separated operator-facing container identity from immutable production-fill audit identity in Operational Inventory Tag Detail: permanent output containers now show their human-readable reference and physical scan code while retaining the internal `VCONT-...` code and Handling Unit link for audit |
| 1.92 | 22 October 2026 | Corrected the Production Operator Panel's first live synchronization so supervisor approval or release performed while the operator tab is hidden, inactive, or blocked by a dialog reloads the Card instead of being silently accepted as a stale revision baseline |
| 1.91 | 22 October 2026 | Corrected ERPNext v15 generated-Batch binding for staged production outputs: submitted Stock Entry Detail, Serial and Batch Bundle, and exact Stock Ledger Entry evidence are resolved before output tags/containers are activated, without guessing from Batch recency |
| 1.90 | 22 October 2026 | Reconciled partial WIP-bin actual use with the final Manufacture receipt: a submitted unused-material return now resolves that exact input variance, removes only its supported balance from ERPNext's later Manufacture mapping, prevents a duplicate production-tag demand/double consumption, and repairs an existing Draft during controlled submission |
| 1.89 | 22 October 2026 | Added permanent Production Output Containers: one reusable QR can receive a new immutable manufactured fill on each ERP submission, then the same container scan resolves that exact Item/Batch as input to the next production process; full consumption empties the container for reuse, with guarded reversal and Container Content audit |
| 1.88 | 22 October 2026 | Reused printed Good quantity commands inside Production Material Trace as hands-free per-container output quantities: scan `CFG:QTY:GOOD:+50`, then scan an unused output tag to stage 50 units; added 50 to the default printable quantity set |
| 1.87 | 22 October 2026 | Allowed one or several production-output tags to be staged before ERPNext generates the finished Batch; on the single Manufacture submission, the authoritative ERP Batch is bound to every staged tag before activation, with clearer multi-container and Serial Number guidance |
| 1.86 | 22 October 2026 | Corrected Manufacture output scanning when optional input and output rows coexist: an active Handling Unit now routes to input allocation, an unused preprinted main tag routes to output staging, and the sole remaining ERP output row resolves safely even when the browser selection is stale; clarified that the Serial Number field is not a Batch field |
| 1.85 | 22 October 2026 | Exposed each Draft or submitted WIP-bin unused-material return on its related Operation Card using the existing Job Card linkage and submit action, while retaining the complete view on the main Production Card |
| 1.84 | 22 October 2026 | Added the missing handling-unit quantity-ledger event for submitted WIP-bin unused-material returns, restoring only the confirmed unused quantity to the original source tag |
| 1.83 | 22 October 2026 | Corrected WIP-bin Current Trace Lines to distinguish Prepared, Actual Used, and Unused Return quantities and to keep a linked Return Draft visible instead of displaying the original full prepared load as consumed |
| 1.82 | 22 October 2026 | Added context-sensitive actual WIP-bin consumption: the existing quantity command/control now records actual use separately from prepared quantity, applies Pool-based routine/supervisor rules, reduces the native consumption Draft before submission, automatically creates a WIP-to-source Draft for unused balance, keeps the bin In Use until that ERP return submits, and restores returned source-tag quantity from ERP feedback |
| 1.81 | 22 October 2026 | Added the missing General Service Point Location Card print action and dedicated A6 permanent-location QR format |
| 1.80 | 22 October 2026 | Added Item-specific physical capacity per reusable WIP-bin Handling Unit, allowing heterogeneous bins in one pool (for example 1 + 2 against an ERP requirement of 3); scanner allocation now uses the scanned bin capacity, permits a zero Master fallback when every active Pool bin is configured, and reserves partial-bin exceptions only for actual under-filling |
| 1.79 | 22 October 2026 | Added scalable Operational Inventory drill-down: Active Tags now count only active identities, the count opens exact Company/Warehouse/Item/UOM tag rows, and Tag Detail shows quantities, batch, quality, movement, custodian/location, reconciliation and scan evidence with a Summary View return action |
| 1.78 | 20 October 2026 | Corrected WIP-bin consumption to a true single-scan flow: the Draft Stock Entry purpose now controls the UI, source-tag/row-selection controls are excluded, and the scanned Ready bin securely resolves its exact Item, Warehouse, UOM, Batch, Cycle, Job Card and ERP consumption row before Draft binding |
| 1.77 | 20 October 2026 | Restored reliable Ready WIP-bin recognition in the full Production Material Trace dialog: direct-field Enter/Tab now synchronizes the completed browser scan before allocation, and scans reaching the underlying Production scanner are redirected to the open trace workflow |
| 1.76 | 20 October 2026 | Reverted the progressive Production Material Trace presentation from 1.74 after floor acceptance found scanner-command and field-visibility regressions; restored the previously proven persistent scanner dialog and full material controls while retaining later production-cycle closure work |
| 1.75 | 20 October 2026 | Added all-or-nothing main-production closure of related Process/Station runtime Cycles: eligible operation Cards are completed and recycled automatically, while incomplete quantity, Job Card, WIP-bin, task-gate or ownership conditions keep the main Card open with an exact blocker |
| 1.73 | 20 October 2026 | Added a persistent **Scan Operator with Camera** action directly in the Production scanner header before login and while switching operator, while retaining fixed-scanner and credential/PIN alternatives |
| 1.72 | 20 October 2026 | Compressed the Production Operator sticky header for 8-inch tablets: operator and Station now share one row, repeated scanner/current-action guidance collapses on short screens, and the essential scanner state, current action and navigation controls remain visible |
| 1.71 | 20 October 2026 | Separated scanner Cancel from material reversal: closing Production Material Trace now restores the main Scanner Ready field after the modal transition, while persistent Release/Cancel Loaded Material row actions reverse the selected Draft allocation without closing the dialog |
| 1.70 | 20 October 2026 | Added suffix-independent Scanner Ready processing and focus-time handler rebinding so a scanned reusable WIP-bin code is recognized and allocated instead of remaining as inactive text after the source-tag step |
| 1.69 | 20 October 2026 | Made the persistent Material Trace Scanner Ready field capture scanner suffixes directly and queue the next different WIP-bin tag or command instead of dropping it while the source scan finishes |
| 1.68 | 20 October 2026 | Kept Production Material Trace open across source-tag and WIP-bin scans, isolated scanner Enter/Tab from modal dismissal, and repaired both ordinary staged-material and Draft WIP-bin cancellation controls |
| 1.67 | 19 October 2026 | Corrected the ERPNext manufacturing order for WIP bins: Job Card completion now permits Ready/In-Use/Consumption-Draft loads so ERPNext can accept their material consumption, while Transfer Draft/Open reconciliation still block Job Card submission and Cycle/Manufacture closure remain blocked until every load is Consumed |
| 1.66 | 19 October 2026 | Removed the Standard Quantity WIP Bin progress/consumption deadlock: target progress now persists while Job Card auto-submit is deferred by active bins, submitted consumption retries deferred auto-submit, and Draft WIP-bin cancellation uses a refresh-safe non-submit button with visible confirmation |
| 1.65 | 18 October 2026 | Corrected Material Genealogy route refresh so opening Full Genealogy for a newly searched Stock Tag reloads that tag instead of retaining the prior cached result; stale slower lookups can no longer overwrite the latest selection |
| 1.64 | 18 October 2026 | Added the mandatory V2 planning reminder and exit checklist so TPS analysis plus WIP-bin ageing/andon escalation, supervisor notifications, utilization/capacity statistics, and optional controlled cleaning/inspection readiness cannot be silently omitted from future V2 scope |
| 1.63 | 18 October 2026 | Added the read-only Supervisor WIP Bin Control report with physical-bin and active-load state, production context, state age, configuration and state-mismatch warnings, Open reconciliation visibility, attention filtering, workspace access, and an acceptance test that preserves ERPNext as stock authority |
| 1.62 | 18 October 2026 | Added the server-enforced operation-card WIP-bin closure gate: both panel and scanner closure remain blocked while the selected Job Card has an active transfer/Ready/In-Use/consumption load or Open reconciliation, with exact physical bin/state guidance before Card reuse |
| 1.61 | 18 October 2026 | Extended controlled WIP Bin reconciliation to submitted transfer cancellation: the bin remains Exception, restored source-tag quantity is safety-reserved, Supervisor exact-bin/source verification releases material returned to source, and material left in WIP requires an exact later submitted transfer before a separately linked Ready load is recovered |
| 1.60 | 18 October 2026 | Added controlled WIP Bin cancellation reconciliation: submitted consumption cancellation now creates a Critical Exception and immutable reconciliation, blocks the bin, requires exact-bin rescan plus Supervisor Override, restores verified material through a separately linked Ready load, or permits Empty only against an exact later submitted ERPNext correction |
| 1.59 | 18 October 2026 | Added the controlled Standard Quantity WIP Bin partial exception: Pool opt-in, Supervisor QR plus Override authorization, scanner quantity support, mandatory reason, immutable Employee/User/session/time evidence, exact partial source reservation and downstream consumption, and corrected the Job Card active-bin completion guard |
| 1.58 | 18 October 2026 | Completed the Standard Quantity WIP Bin operation-consumption gate: Ready-load visibility by Job Card, scanner-created Draft consumption, exact Ready-bin/Item/Warehouse/UOM/Batch binding, cancellable Draft scans, submitted ERP feedback to Consumed/Empty, and Job Card/Manufacture completion blocks while physical bins remain unconsumed; removed the temporary Work Order safety stop |
| 1.57 | 17 October 2026 | Added audited Handling Unit print choices for the existing 45 × 250 mm trace tag plus 50 × 30 mm, 100 × 50 mm, and A6 permanent reusable-bin/bin-slot barcode cards; all formats encode the visible physical identity and keep mutable contents out of the fixed label |
| 1.56 | 16 October 2026 | Added scanner-first Draft transfer allocation for Standard Quantity WIP Bins: numbered row selection, optional/required/ERP-only source handling, partial reservation from a larger source Stock Tag, Empty pool-bin validation, cancellable Draft loads, source quantity confirmation only after submitted ERP transfer, reversal restoration, and complete-row submission gates; Work Order release remains safely blocked until operation consumption is delivered |
| 1.55 | 16 October 2026 | Added the immutable Standard WIP Bin Load audit backbone: per-load Item/Batch/quantity and production-context snapshots, one-active-load bin exclusivity, native ERP transfer/consumption row validation, submitted Stock Entry Ready/Consumed confirmation, cancellation reversal/Exception handling, and workspace investigation access; floor scanner allocation remains deliberately gated |
| 1.54 | 16 October 2026 | Added the safe configuration foundation for Standard Quantity Reusable WIP Bins: a distinct Handling Unit role, strict non-mixed fixed-bin identity, one-operation/workstation WIP Bin Pools, Item-specific full-bin quantity mapping on BOM material rows, compatibility validation, workspace access, and an explicit runtime safety stop until controlled fill/consume posting is delivered |
| 1.53 | 16 October 2026 | Added printable scanner commands for **Go to Current Work** and guarded runtime **Close Kanban Cycle**; closure now uses a scanner-ready confirmation and reuses all ERP, quantity, authorization, and Process Task gates |
| 1.52 | 16 October 2026 | Marked Gate 2C live-site accepted and added native Skip-WIP Job Card/Work Order material consumption: controlled Draft `Material Consumption for Manufacture`, operation-card scoping, partial tagged-bundle usage, remaining tag balance, live per-Job-Card consumed/pending quantities, explicit ERP submission, scanner row selection and printable material-quantity commands |
| 1.51 | 16 October 2026 | Marked Gate 2B live-site accepted and added Gate 2C isolated private media per direct Action Run: multiple photo/file upload, visible server-time/GPS camera stamping, recoverable pre-post archive, pending-upload guard, available-only immutable snapshot, post-snapshot lock, operator view, and supervisor Action Run gallery without attaching evidence to the reusable Card |
| 1.50 | 16 October 2026 | Replaced the DocType Action parent-field Dialog layout path with the same direct Frappe control renderer used by working child observations, restoring editable Summary, Outcome and Notes controls while retaining read-only context fields, reactive visibility, typed collection and server allowlisting |
| 1.49 | 16 October 2026 | Corrected DocType Action parent controls so Operator Input fields consistently remain editable when Frappe serializes Check values as strings or integers; server-context and explicitly read-only fields remain protected |
| 1.48 | 16 October 2026 | Added Gate 2B direct DocType Action Card scanning in Kanban Service Tasks, explicit Resume versus Start New intent, per-occurrence opaque Run identity, retry deduplication, operator ownership and Supervisor history scope, reusable-card form context, Task-only profile rejection, and production isolation; direct Action Run media capture remains a later package |
| 1.47 | 16 October 2026 | Added Gate 2A exact non-production DocType Action Card configuration, enabled/Valid profile validation, immutable profile identity, zero production quantity, explicit production/logistics isolation, controlled replacement support, and a dedicated CR80 QR print format; direct Resume/Start New scan resolution remains the next serial package |
| 1.46 | 16 October 2026 | Added Gate 1G explicit development-only draft and submittable pilot targets with repeatable observation rows, an administrator-triggered idempotent pilot policy/profile installer, exact-name-only engine isolation, normal Kanban Terminal target permissions, automated contract tests, and a standalone live acceptance guide |
| 1.45 | 16 October 2026 | Added Gate 1F stable private-media references and supervised recovery: available same-Task evidence is pinned by registry ID without copying S3 binaries or signed URLs; the mapped form opens evidence through authorized temporary links; the Supervisor Action Centre lists document recovery attention; and a scanned Supervisor can return an unposted Run to its existing form or reconcile the exact linked target docstatus with immutable attempt/event audit |
| 1.44 | 16 October 2026 | Added Gate 1E phone/tablet mapped document form in the Service Task panel: automatic exact-event opening, visible/read-only parent mappings, safe reactive conditions, repeatable first-level child row cards, Draft-versus-Submit controls, same-dialog failure/retry, pending-task resume button, terminal-state/target feedback, and exact-Run resume access for the initiating verifier |
| 1.43 | 16 October 2026 | Added Gate 1D Service Task binding: optional validated Action Profile plus exact Start/Complete/Verification trigger and required-closure setting on Task Schedule; immutable occurrence snapshot; automatic one-Run resolution; explicit Pending Document Posting status; posting-policy-aware release; premature-submit validation; linked Task events; and controlled Run cancellation on Task disposition. Phone/tablet mapped form remains Gate 1E |
| 1.42 | 16 October 2026 | Added Gate 1C controlled server mapper/writer: immutable-snapshot target selection, allowlisted typed parent/child values, Service Task/fixed/server sources, safe conditions, terminal-User create/write/submit enforcement, distinct Draft/Submitted results, persisted form-payload integrity hash, retry reuse of one linked target, and reconciliation for uncertain or externally changed targets; Service Task event/UI binding remains pending |
| 1.41 | 16 October 2026 | Added Gate 1B immutable, idempotent `CFG Kanban DocType Action Run` identity; pinned profile revision/mapping snapshot; immutable Action Attempts; separate Employee/terminal attribution; Service Task and Event links; database lock/uniqueness guards; sanitized errors; and controlled Supervisor cancellation/reconciliation while retaining the non-posting boundary |
| 1.40 | 16 October 2026 | Added the locked Special DocType Card source specification and Gate 1A protected target policies, metadata-driven parent/child action profiles, revision/fingerprint invalidation, server validation, and non-posting operator-form preview; explicitly documented that Action Runs, Service Task triggers, writes, and direct cards remain pending |
| 1.39 | 14 October 2026 | Added optional, dependency-free compatibility with Hidden Item Settings: user allow-list visibility, filtered Kanban BOM previews and Operator material responses, protected restricted Master mappings, neutral attention messages, and server-managed inclusion in native ERPNext production Stock Entries |
| 1.38 | 14 October 2026 | Added per-BOM-component source Warehouses, ERPNext Item Operation validation, Work Order-wide and Job Card-specific WIP transfer modes, Skip-WIP direct consumption, live stock/shortage display, operator-confirmed Draft/automatic posting, duplicate-draft protection, controlled Stock Entry submission, and the revised RW Noodle acceptance flow |
| 1.37 | 10 October 2026 | Added Warehouse-card adoption of already-posted ERP finished stock, locked ERP-versus-tag balance validation, preprinted tag activation, exact Batch/Serial checks, supervisor reservation to eligible stock-replenishment Cycles, allocation release, Cycle allocation indicators, audit records, and ERP/tag/untagged report columns |
| 1.36 | 9 October 2026 | Exposed QR printing on every master-backed Card, separated Card identity replacement from printing, recorded Card print time/user, and labelled Transfer and Withdrawal print formats correctly |
| 1.35 | 9 October 2026 | Added controlled Withdrawal Kanban for non-BOM consumables, independent Stock Withdrawal responsibility, optional tagged/untagged selection, tag reservation, native ERPNext Material Issue posting, submission feedback, Card recycling, cancellation safeguards, Logistics-panel operation, and an independent L2 system test |
| 1.34 | 9 October 2026 | Added Transfer Kanban release into Logistics Movement Manifests, explicit internal versus intercompany route modes, direct and Goods-in-Transit Material Transfer Stock Entries, optional no-tag ERP-stock lines, ERP-submission feedback, Card/Cycle completion, cancellation safeguards, and scan-card Manifest lookup |
| 1.33 | 9 October 2026 | Separated physical supplier delivery from usable purchase fulfilment, added rejected-warehouse disposition records, replacement/return reconciliation, validated concession transfers, controlled short close, Receipt Exception lifecycle and Card-release protection |
| 1.32 | 4 October 2026 | Added independent accepted-return physical disposition with quantity-conserving splits, Company/Warehouse/rate validation, controlled Draft Material Receipt, no-stock disposal, draft discard, ERP submit/cancel feedback, and combined accounting-plus-stock closure |
| 1.31 | 4 October 2026 | Added accountant-only post-QC source/no-credit decisions, same-Company/Customer and remaining-quantity validation, idempotent non-stock Draft Sales Invoice Return preparation, ERPNext-owned tax/e-Invoice submission, submit/cancel feedback and controlled replacement revision |
| 1.30 | 4 October 2026 | Replaced the draft return concept with two practical floor workflows: Customer Return for QC from a Customer Site without prior DN/invoice, optional customer acknowledgement, private timestamped/geotagged evidence, printable/scannable Temporary Return Note, QC receipt/disposition and accounting-pending handoff; plus exact submitted-DN correction through a controlled Return Delivery Note with invoiced-DN safety hold |
| 1.29 | 4 October 2026 | Initial return-intake draft (superseded by 1.30 before deployment) |
| 1.28 | 3 October 2026 | Added policy-controlled customer proof of delivery, attended/unattended/no-proof dispositions, private photo/signature/file evidence, server-time and GPS capture, supervisor thumbnail review, server-enforced closure, and safe post-proof cancellation blocking |
| 1.27 | 3 October 2026 | Added controlled customer Delivery Note creation from confirmed Stock Tag allocations, site-specific Draft/auto-submit policy, locked Item Price validation, mandatory ERP parent/child inputs, submission-only tag consumption, reusable-container completion, cancellation restoration, amendment revision, and Exception/idempotency audit |
| 1.26 | 3 October 2026 | Added customer Stock Tag allocation, partial/full quantity reservation, complete reusable-container expansion, audited release/reconfirmation, ERP stock validation, container safeguards, and Delivery Allocation genealogy history without prematurely moving ERP stock |
| 1.25 | 3 October 2026 | Added Customer Site scan resolution, Company-specific Vehicle Warehouse setup, immutable operator-scoped Delivery Sessions, idempotent start/cancel audit, workspace records, and the explicit no-stock-movement C1 boundary |
| 1.24 | 3 October 2026 | Added one-scan complete reusable-container dispatch and receipt through intercompany Movement Manifests while retaining every contained Stock Tag as the ERP-accounted Item/Batch/quantity identity |
| 1.23 | 3 October 2026 | Added controlled exact-serial splitting from main Stock Tags to preprinted detachable child tags, quantity-preserving ledger evidence, and safe untouched-child merge back to the parent |
| 1.22 | 3 October 2026 | Added ERPNext-referenced exact Serial Number membership for received and produced Stock Tags, whole-tag production validation, consumption/reversal/replacement lifecycle handling, serial history, and genealogy/logistics visibility |
| 1.21 | 3 October 2026 | Added reusable-container content loading/unloading in the Logistics panel, immutable membership episodes, mixed-content policy, movement safeguards, workspace history, and genealogy visibility |
| 1.20 | 3 October 2026 | Added the read-only scan-any-tag Material Genealogy Explorer, upstream/downstream Handling Unit lineage, ERP movement/Manifest evidence, related-tag navigation, Handling Unit and Logistics-panel entry points, and printable A4 exact-trace report |
| 1.19 | 3 October 2026 | Added the Logistics-panel same-company tagged Warehouse-transfer assistant backed by Draft/Submitted ERPNext Material Transfer Stock Entries, Internal Warehouse Transfer responsibility, full-tag movement enforcement, and ERP-confirmed Warehouse updates |
| 1.18 | 3 October 2026 | Added scoped Operator-panel production material tracing for Stock Entries tied to the scanned Card's active Cycle Work Order, including fixed-scanner Enter handling, mobile camera scan buttons, automatic input-tag quantity, and submitted trace visibility |
| 1.17 | 2 October 2026 | Added Stock Entry-confirmed production trace transactions, tagged input reservation/transfer/consumption, staged preprinted output activation, cancellation reversal guards, ERP-only coexistence, and ERPNext v15 Batch Bundle resolution |
| 1.16 | 2 October 2026 | Added optional Item/Company mixed material-trace policies, ERP-only fallback, submitted Purchase Receipt tag activation, immutable ERP-origin references, and explicit first-slice limitations |
| 1.15 | 2 October 2026 | Extended scoped Supervisor access to report progress and complete active Operator/Senior Operator Service Tasks with full acting-Employee audit attribution, without granting Start, Cancel/Bypass, or cross-Supervisor control |
| 1.14 | 2 October 2026 | Added scoped Supervisor monitoring of matching active Operator/Senior Operator Service Tasks, including live progress visibility, while preserving action isolation unless View All Service Tasks is enabled |
| 1.13 | 2 October 2026 | Corrected Service Task eligibility ordering so responsibility/employee/Workstation access is applied before the 200-row display limit, and blank-Workstation tasks remain visible to eligible profiles |
| 1.12 | 2 October 2026 | Corrected Dynamic Form interaction refresh so Check and Select controls remain clickable while dependent visibility still updates after each completed value change |
| 1.11 | 2 October 2026 | Implemented reactive Dynamic Form Visible Conditions in Service, Process Task, and production-operation dialogs; added safe syntax validation and server-side exclusion of hidden mandatory fields/evidence |
| 1.10 | 2 October 2026 | Required source Company/Warehouse on new Stock Tags, added controlled initial-Warehouse recovery for legacy blank tags, documented Manifest destination timing, and improved Operator Profile names and workstation/operation grids |
| 1.9 | 2 October 2026 | Corrected Service Task isolation: an unticked Supervisor no longer sees or operates another Employee's ordinary assigned work; direct APIs, media, schedule requests, service-point scans, and verification access now apply the same server-side responsibility rules |
| 1.8 | 2 October 2026 | Added serial Tag Range Registries, read-only candidate resolution, atomic lazy Tag Family/child materialization, range-aware Handling Unit activation and replacement, workspace access, and issuer-versus-inventory ownership guidance |
| 1.7 | 2 October 2026 | Made Production, Service, and Logistics refresh actions safely adopt the latest shared operator credential across parallel tabs without allowing a stale tab to erase a newer login |
| 1.6 | 1 October 2026 | Added safe default logistics Tag lookup, explicitly armed dispatch/receipt scan modes, mobile-first receipt progress, last-Manifest recovery, latest-10 completed history, mandatory ERP child-table capture, and cross-panel Logistics links |
| 1.5 | 1 October 2026 | Fixed Service Task correction/resubmission for numeric and Check answers; added persistent progress count/latest audit fields and live supervisor progress history |
| 1.4 | 1 October 2026 | Added Package B Movement Manifest dispatch/receipt, Logistics Operator Panel, guarded Delivery Note/Purchase Receipt commands, ERP feedback, cancellation, and exact operating prerequisites |
| 1.3 | 1 October 2026 | Corrected Package A scanning for preprinted logistics tags: visible code is primary, UUID is internal fallback, issuer/company number namespaces are explicit, form activation resolves scans, and replacement print QR/Code 128 use the visible code |
| 1.2 | 30 September 2026 | Added Package A multi-company Logistics Routes, Customer Scan Points, registered Stock Tag families, extended Handling Units, Company snapshots, immutable quantity ledger, migration, and explicit Packages B-C limitations |
| 1.1 | 25 September 2026 | Added buyer-owned Purchase Replenishment through Material Request, Purchase Order selection, guarded Purchase Receipt creation, partial receipt, ERP feedback, and Card recycling |
| 1.0 | 23 September 2026 | Re-audited repository code; added exact labels/internal fieldnames, card-behaviour split, runtime allocation/closure, Job Card sync, dashboard/dispatch, recovery table, and independent-LLM rules |
| 0.6 | 18 September 2026 | Added permanent Service Point QR, overlap/holiday policies, Supervisor cancellation/bypass, Process/Sample QR, controlled QC hold/retest, private multi-file evidence, timestamp/GPS camera capture, and recoverable removal |
| 0.5 | 18 September 2026 | Added private S3 media settings, task evidence gallery, mobile Service Task scanning, and scheduler guidance |
| 0.4 | 17 September 2026 | Added scanner-first focus recovery, command labels/function keys, and scan-driven progress quantities |
| 0.3 | 15 September 2026 | Added mobile camera scanning and the Administrator-only development Employee proxy |
| 0.2 | 15 September 2026 | Added Employee-based shared-terminal operator authentication, authorization, and audit attribution |
| 0.1 | 11 September 2026 | Initial manual covering the current stock, Sales Order, MTO, printing, scanning, execution, WIP, and audit functions |
