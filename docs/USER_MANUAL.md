# CFG Kanban Code-Verified Operating Guide

**Application:** CFG Kanban for ERPNext/Frappe v15  
**Guide version:** 1.23

**Updated:** 3 October 2026

**Scope:** Current repository code; Frappe/ERPNext v15

**Canonical file:** `docs/USER_MANUAL.md`

## 1. Purpose of this manual

This guide explains how to configure and operate CFG Kanban from an empty installation through
the first production signal. It covers normal reusable-card replenishment, Sales Order stock
proposals, customer make-to-order production, operation reporting, production Process Tasks,
standalone Service Tasks, controlled QC, private media evidence, printing, handling-unit tags, and
audit records.

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
| Asset Card | Finds open standalone Service Tasks for one Asset | Never | Asset; no Master required |
| Location Card | Finds open standalone Service Tasks for one location text | Never | Location Reference; no Master required |
| Task Card | Finds open standalone Service Tasks from one Task Schedule | Never | Task Schedule; no Master required |

A Process/Station card is a reusable runtime allocation tool. It filters Job Cards by the Card Item,
Master Company, Card Operation, submitted Kanban-controlled Work Order, remaining Job Card demand,
and available upstream input. A Station Kanban adds an exact Workstation match. The system recommends
according to **Runtime Selection Priority**, but an authorised operator may choose another eligible
candidate and must give an Override Reason. One card-sized Cycle is then created for the effective
quantity; it does not mirror every Job Card on that Work Order.

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
- **Production Supervisor:** production floor, dispatch sequence, cycles, signals, demand, and
  production exceptions.
- **Service & Maintenance Supervisor:** service tasks, schedules, maintenance register, and
  compliance evidence.
- **System Setup:** Masters, Cards, operator profiles, dashboard profiles, and global settings.
- **Detailed Records & Audit:** production execution, WIP, ERP documents, operator sessions, and
  event history.

The operator interface is available at:

```text
/app/kanban-operator
```

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
| Control Type (`control_type`) | Production | Options: Production, Withdrawal, Transfer |
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
| Task Schedule (`task_schedule`) | Required only for Task Card |
| Active (`active`) | Yes |
| Revision (`revision`) | Start with 1 |

Exact **Card Type** (`card_type`) options are: `Physical Unit Card`, `Physical Batch Card`,
`Process Kanban`, `Station Kanban`, `Asset Card`, `Location Card`, and `Task Card`. The first four
are production cards. The final three are service identity cards and do not trigger production.
**Card Behaviour** (`card_behavior`), current state, QR, UUID, active Cycle, handoff mode, and most
location/status fields are derived or system-maintained.

UUID and QR Code are generated by the server if left empty. Do not copy a QR identity from another
card.

### Step 5 — Print and verify the card

Open the saved Card and use **Print Kanban**:

- **Print Standard Card:** reusable A6 landscape, two pages for front and reverse instructions.
- **Print Operational Card:** reusable A6 landscape, single-sided operational version.

For Standard Card on A4 stock, select four pages per sheet and duplex printing in the printer
dialog. Always test front/back orientation before a production print run.

The first print increments Print Count. Every reprint requires a reason and creates an Event.

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
Receipt**.

> Physical replenishment limitation: Manufacture Stock Entry feedback currently moves the Cycle to
> Waiting FG Receipt, but the final FG receipt confirmation and reusable physical-card return are
> not yet implemented as one automatic closure action.

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

Existing preprinted stock tags are the normal operating method, so production does not depend on a
live tag printer. **Kanban Actions → Print Thermal Tag** is an optional replacement/emergency label.
Its PDF canvas is 45 mm × 250 mm for portrait-feed thermal stock, with the horizontal design
rotated onto that canvas. Both its QR and Code 128 encode the visible `handling_unit_id`.

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
2. Under **Allocate Tagged Material Input**, select a tag-enabled source row, scan an active
   Handling Unit in that row's source Warehouse, and enter the Stock UOM quantity. The quantity is
   reserved against the Draft entry but ERP stock does not move.
3. Under **Stage Preprinted Production Output Tag**, select a tag-enabled finished/repacked target
   row, scan an unused main tag, enter its Stock UOM quantity and Handling Unit Type. The identity
   remains pending; no output stock tag is created while the entry is Draft.
4. Use **Cancel** beside a staged line to release its reservation or discard the pending output tag
   before submission.
5. If the complete ERP draft will be discarded, select **Discard Entire Draft Trace**, enter the
   reason, and only then delete the Draft Stock Entry. This releases all tag reservations and keeps
   the Material Trace as Abandoned audit history without retaining a link that blocks ERP deletion.
6. Submit the Stock Entry through ERPNext. Only then does the trace become Confirmed. Consumption
   reduces input-tag balance; Material Transfer for Manufacture updates the tag's Warehouse; and
   Manufacture/Repack activates output tags from the ERP-confirmed output.

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
3. Under **Production Material Trace**, locate the linked Stock Entry and select **Scan Material
   Tags**.
4. For an input row, scan the Handling Unit with a fixed scanner or **Camera Scan Input Tag**. Leave
   **Stock Quantity (0 = automatic)** at zero to allocate the available tag quantity up to the ERP
   row balance, or enter a smaller explicit quantity for a permitted direct-consumption allocation.
   Material Transfer for Manufacture still requires the complete physical Handling Unit.
5. For an output row, scan an unused preprinted main tag, confirm quantity and Handling Unit Type,
   and select **Stage Output Tag**. Output quantity cannot be inferred when several physical
   containers may divide one ERP row.
6. The Stock/Manufacturing user reviews and submits the ERPNext Stock Entry. The operator panel does
   not submit it. Reload or rescan the Card to see **Confirmed**.

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
physical membership episode. A Stock Tag cannot be consumed, transferred, dispatched, received,
replaced, or voided independently while loaded, and a nonempty container cannot be replaced or
voided. Managers can review **Container Content History** or **Reusable Container Episodes** in the
Material Genealogy Explorer.

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

- `CFG:CMD:START` starts the operation when exactly one execution lane is Ready.
- `CFG:CMD:REPORT_PROGRESS` opens progress entry when exactly one execution lane is eligible.
- If multiple lanes are eligible, the command is refused and the operator must select the correct
  lane on screen. This prevents a general command label from updating the wrong Job Card.

Inside **Report Progress**, quantity labels can replace keypad entry. Examples:

- `CFG:QTY:GOOD:+1` adds one good unit.
- `CFG:QTY:GOOD:10` sets good quantity to 10.
- `CFG:QTY:REJECT:+1` adds one rejected unit, subject to operator permission.
- `CFG:CMD:CONFIRM` submits the progress form.
- `CFG:CMD:CANCEL` closes the progress form without submitting.

When printing the command sheet, enter the routine Good Quantity increments required by that
workstation, separated by commas—for example `1, 10, 50, 100`. The sheet is generated on demand, so
different operations may keep different laminated quantity sheets without changing the Kanban Card
or Master. A scanned absolute command such as `CFG:QTY:GOOD:100` sets the field to 100, while
`CFG:QTY:GOOD:+100` adds 100 to its current value.

If an error message is open, the operator may immediately scan the next card. The panel closes the
message and processes that scan. `CFG:CMD:DISMISS` closes the message without loading another card.
When a Yes/No confirmation is open, `CFG:CMD:CONFIRM` selects its primary Yes/Confirm action;
`CFG:CMD:CANCEL` or `CFG:CMD:DISMISS` closes it without approval. The same Confirm label continues
to submit the Report Progress dialog when that form is active.

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
not yet have one final automatic FG-receipt/card-return action, so do not force these states manually.

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
- Controlled whole-container vehicle/customer movement while preserving each contained tag.
  Purchase Receipt activation, reusable-container content episodes, exact serial membership and
  controlled child split/merge, Stock Entry-confirmed production tracing, scoped scanner-first floor access, same-company tagged
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
occurrences, Progress, WIP Ledger, Events, Sequence Changes, Operator Sessions, and Media registry
records. Material Trace records and Handling Unit Quantity Ledger rows are also system-created and
immutable. Supervisors
interact with those generated records only through their defined approval,
verification, disposition, reconciliation, recovery, or exception actions.

## 23. Buyer-owned purchase replenishment

Use **Control Type** (`control_type`) = **Purchase Replenishment** when the item is bought from a
normal third-party supplier. This V1 flow does not represent buyer-directed contract manufacturing;
that richer vendor execution model remains V2.

On **CFG Kanban Master**, configure exact fields **Default Supplier** (`default_supplier`),
**Destination Warehouse** (`destination_warehouse`), optional **Supplier Pack Size**
(`supplier_pack_size`), **Minimum Order Qty** (`minimum_order_qty`), **Purchase Order Multiple**
(`purchase_order_multiple`), **Submit Material Request on Approval**
(`auto_submit_material_request`), **Receipt Posting Mode** (`receipt_posting_mode`), **Allow Partial
Receipt** (`allow_partial_receipt`), **Kanban Over-receipt Tolerance %**
(`over_receipt_tolerance_pct`), and optional **Rejected Warehouse** (`rejected_warehouse`).

The operational sequence is:

1. Consume the reusable Card. The app creates a **Purchase Replenishment** Signal and Cycle.
2. For Approval mode, open the Signal and select **Approve and Create Material Request**. Automatic
   mode performs the same command immediately. Signal Only does not create an ERP document.
3. ERPNext Material Request is the first purchasing record. Purchasing creates and submits the
   Purchase Order from it using the normal ERPNext buying workflow.
4. A Purchase Order made from the linked Material Request is associated automatically when the
   link is unambiguous. Otherwise open the Cycle and use **Purchase Replenishment → Select Purchase
   Order**. The submitted PO must match Company, Supplier, and Item, and the reason is audited.
5. At receipt, open the Cycle and choose **Purchase Replenishment → Receive Purchased Item**. Enter
   Delivered Qty, Accepted Qty, Rejected Qty, warehouses, and Supplier Delivery Note. Delivered
   must equal Accepted plus Rejected and may not exceed outstanding PO quantity plus the configured
   tolerance.
6. **Create Draft Purchase Receipt** leaves ERPNext submission to an authorised stock user.
   **Submit After Receiver Confirmation** submits simple items immediately. Batch-controlled,
   serial-controlled, or incoming-inspection items deliberately remain Draft until their standard
   ERPNext batch/serial/Quality Inspection information is completed. **Require Supervisor Approval**
   also creates a Draft.
7. Only a submitted Purchase Receipt updates ERPNext stock. Partial receipt leaves the Cycle and
   Card active as **Partially Received**. Full receipt completes the Cycle and recycles the Card to
   **Available**. Purchase Invoice and payment remain the later ERPNext accounts workflow.

Material Request, Purchase Order, and Purchase Receipt receive app-owned read-only trace fields
**Kanban Controlled**, **Kanban Cycle**, and **Kanban Signal**. Supplier/company/item mismatch,
fully received PO rows, and over-receipt create a visible **CFG Kanban Exception** and block the
purchase Cycle. A purchase Signal with an effective PO or submitted Receipt will not be silently
rolled back; resolve the ERP purchasing record and reconcile instead.

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

## 25. Multi-company logistics and intercompany handover (Packages A-B)

Package A installs the configuration and physical-identity foundation. The Package B vertical slice
adds the controlled intercompany Movement Manifest, source-company Delivery Note, destination-company
Purchase Receipt, ERP feedback, and scan-first Logistics Operator Panel. Customer-site delivery,
vehicle loading, loose reusable containers, proof of delivery, Sales Invoice creation, and Billing
Batch grouping remain later packages. The locked design is in
`docs/MULTI_COMPANY_LOGISTICS_ARCHITECTURE.md`.

### CFG Kanban Logistics Route

Create one directional route for each permitted company pair. Exact fields include **Route Name**
(`route_name`), **Active** (`active`), **Source Company** (`source_company`), **Source Warehouse**
(`source_warehouse`), optional **Transit Warehouse** (`transit_warehouse`), **Destination Company**
(`destination_company`), **Destination Warehouse** (`destination_warehouse`), **Internal Customer**
(`internal_customer`), **Selling Price List** (`selling_price_list`), **Internal Supplier**
(`internal_supplier`), **Buying Price List** (`buying_price_list`), **Handover Mode**
(`handover_mode`), **Auto-submit Dispatch Delivery Note** (`auto_submit_dispatch_dn`), **Auto-submit
Receipt Purchase Receipt** (`auto_submit_receipt_pr`), **Billing Frequency**
(`billing_frequency`), and the three Responsibility links.

The form rejects same-Company routes, Warehouses belonging to the wrong Company, and Price Lists
that are not enabled for the required selling/buying direction. The two auto-submit settings are
independent: one controls the source Delivery Note and the other controls the destination Purchase
Receipt.

### CFG Kanban Customer Scan Point

Create one record per physical delivery address. Exact identity fields are **Printed Customer Site Code**
(`site_code`), **Site / Branch Name** (`site_name`), **Active** (`active`), **Selling Company**
(`selling_company`), **Customer** (`customer`), **Delivery Address** (`customer_address`), optional
**Territory** (`territory`), **Route Reference** (`route_reference`), and **Default Selling Price
List** (`default_price_list`).

Proof settings are **Proof Policy** (`proof_policy`: Required, Optional, Unattended Delivery
Allowed, No Proof Required), **Require Recipient Name**, **Require Signature**, **Require
Photograph**, **Require GPS**, and **Require Unattended-delivery Reason**. The printed `site_code` is
the primary scan value. **Internal UUID Alias** is generated automatically as a system fallback.
Customer-site delivery scanning is Package C.

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
   available.

The terminal remembers the last viewed Manifest in that browser so a refresh after manual ERP
submission reopens it. **Recently Completed** is collapsed by default and contains only the latest
10 authorized terminal-state Manifests; older history remains accessible by scanning a Stock Tag,
scanning/entering the Manifest number, or using the normal Desk list.

An unused **Draft** or **Prepared** Manifest can be cancelled by an override-authorized operator
with a reason; prepared reservations are released. After an ERP document exists, use controlled
ERP cancellation/recovery. Movement Manifests are audit records and cannot be deleted. Package B
does not yet load a lorry, create a customer Delivery Note, or perform later intercompany billing.

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

11. Treat Customer-site delivery, vehicle loading, loose reusable-container movement, and billing
    grouping as future packages. Package B intercompany posting is operational only through the
    Movement Manifest and submitted Delivery Note/Purchase Receipt feedback described above.

## 27. Revision history

| Version | Date | Change |
|---|---|---|
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
