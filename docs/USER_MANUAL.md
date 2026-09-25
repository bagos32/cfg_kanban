# CFG Kanban Code-Verified Operating Guide

**Application:** CFG Kanban for ERPNext/Frappe v15  
**Guide version:** 1.0

**Updated:** 23 September 2026

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
changed.

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
Workstations are returned. A non-Supervisor sees unassigned tasks plus tasks assigned to that same
Employee; a Supervisor may see all otherwise eligible tasks. Starting an unassigned task assigns it
to the starting Employee. A task already assigned to someone else cannot be started or completed by
another normal operator.

The Service Tasks page is optimized for phones and tablets rather than a fixed barcode terminal.
Large touch controls for **Refresh**, **Scan / Switch Operator**, and **Create Task** remain at the
top of the page. Each task is displayed as a separate touch card with prominent **Start**, **Report
Progress**, **Complete**, **Correct and Resubmit**, or **Verify** actions according to its status. Urgent and
high-priority work has a colored card edge. On a phone, task forms use the full screen with a sticky
action footer so the final action remains accessible after scrolling through instructions and
checklists. The operator can explicitly switch identity or end the shared session from the active
operator banner.

Work instructions, completion checklist, measurements, and notes are presented as separate sections.
Dynamic fields use their exact **Capture On** stage: Start appears in the Start dialog, Progress in
**Report Progress**, Complete in the completion dialog, and Verify in the independent verification
dialog. A task must be started before Progress can be reported. Every Progress submission is kept as
a separate timestamped measurement row. Completion is blocked until every mandatory Progress field
has at least one valid recorded value. Mandatory Check fields must be checked; zero remains valid for
mandatory numeric fields. A mandatory read-only definition must have a Default Value or the Schedule
cannot be saved.

When **Require Supervisor Verification** is enabled, completion moves the Task to **Awaiting
Verification**. A different authorized employee must approve it. Rejection requires remarks and
moves it to **Correction Required** for correction and resubmission.

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

Create **CFG Kanban Handling Unit → New** after a Cycle exists. Enter:

- Handling Unit Type and unique visible ID.
- Kanban Cycle.
- Quantity and UOM.
- Carton/container count where applicable.
- Immediate Source and Immediate Destination.
- Sequence No. and Total Units, for example `1 of 3`.

Item, Batch, Work Order, reusable Card, and description are copied from the Cycle when available.
The Opaque Token is generated automatically; users should not type or reuse it.

Use **Kanban Actions → Print Thermal Tag**. The PDF canvas is 45 mm × 250 mm for portrait-feed
thermal stock, with the horizontal tag design rotated onto that canvas.

Handling-unit scan lifecycle:

```text
Issued → Attached → Dispatched → Received
   └──────────────→ Void
```

Received, Void, and Replaced are terminal states. A repeated terminal scan returns the existing
state without triggering production.

Reprints require a reason. Replacement creates a new tag identity and revision, marks the old tag
Replaced, and preserves the relationship between both records.

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
- Do not photocopy, duplicate, or manually edit QR/opaque identities.
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
(Hours)** (`default_due_hours`), **Default Priority** (`priority`), responsibility/location fields,
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
Progress**, **Override**, **Reopen**, plus **Allowed Workstations** and **Allowed Operations** child
tables. A profile role alone does not grant an action: the corresponding permission checkbox and
scope must also allow it. The terminal ERPNext user separately needs the `Kanban Terminal` role (or
manager/system-manager access).

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
Profiles, and Handling Units. The app normally creates Demands, Signals, Cycles, ERP Commands,
Process Executions, Operation Summaries, Runtime Allocations, Process Tasks, service Task
occurrences, Progress, WIP Ledger, Events, Sequence Changes, Operator Sessions, and Media registry
records. Supervisors interact with those generated records only through their defined approval,
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

## 25. Guidance rules for another LLM

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

## 26. Revision history

| Version | Date | Change |
|---|---|---|
| 1.1 | 25 September 2026 | Added buyer-owned Purchase Replenishment through Material Request, Purchase Order selection, guarded Purchase Receipt creation, partial receipt, ERP feedback, and Card recycling |
| 1.0 | 23 September 2026 | Re-audited repository code; added exact labels/internal fieldnames, card-behaviour split, runtime allocation/closure, Job Card sync, dashboard/dispatch, recovery table, and independent-LLM rules |
| 0.6 | 18 September 2026 | Added permanent Service Point QR, overlap/holiday policies, Supervisor cancellation/bypass, Process/Sample QR, controlled QC hold/retest, private multi-file evidence, timestamp/GPS camera capture, and recoverable removal |
| 0.5 | 18 September 2026 | Added private S3 media settings, task evidence gallery, mobile Service Task scanning, and scheduler guidance |
| 0.4 | 17 September 2026 | Added scanner-first focus recovery, command labels/function keys, and scan-driven progress quantities |
| 0.3 | 15 September 2026 | Added mobile camera scanning and the Administrator-only development Employee proxy |
| 0.2 | 15 September 2026 | Added Employee-based shared-terminal operator authentication, authorization, and audit attribution |
| 0.1 | 11 September 2026 | Initial manual covering the current stock, Sales Order, MTO, printing, scanning, execution, WIP, and audit functions |
