# Service Point, Process Task, and QC Control

## Permanent service points

A Task Schedule may enable a permanent Service Point QR. The printed payload identifies the
schedule and location (`CFG:SERVICE:SCHEDULE:<schedule>`), not one generated occurrence. The
Service Task panel resolves that identity to the oldest current open occurrence. When no open
occurrence exists and the schedule is due, the server generates the due occurrence idempotently.
When it is not yet due, the panel reports the next due time and does not create an early task.

The overlap policy is explicit:

- **Prevent While Open** keeps one actionable occurrence until it is completed or disposed.
- **Allow Parallel Occurrences** preserves every scheduled occurrence independently.

Automatic schedules can use an ERPNext Holiday List. With **Skip Listed Holidays**, cron advances
the recurrence and records a skip event without generating an occurrence. A Supervisor can also
cancel an unwanted occurrence or bypass it for an approved exception. Both actions require a
reason and retain the audit record; neither deletes task history.

## Service queue responsibility and explicit scans

The default **Ready / Open Tasks** queue includes unassigned tasks whose **Responsible Kanban
Role** matches **Operator Profile → Responsible Roles**. An empty responsibility list is no
longer unrestricted: shared unassigned tasks and direct Employee assignments remain visible.
Job Codes do not grant Service Task responsibility. Scoped Supervisor assistance and **View All
Service Tasks** retain their existing authority. Operator Profile changes invalidate the live
revision so the list refreshes even when no Task has changed.

An explicit scan can reveal other open tasks as status references:

- **General Service Point Location Card:** Card Type = Location Card; Location Purpose = General
  Service Point; Location Reference matches the tasks' Location.
- **Task Card:** exact Task Schedule.
- **Asset Card:** exact Asset.
- **Task QR/ID:** one exact occurrence.

Cards must be active and unblocked. Their Company scopes the results when set; Workstation
restrictions remain in effect. Outside-role or other-Employee references appear separately under
**Scanned Tasks — View Only**, with no execution, private evidence or document-form controls.
Matching actionable tasks take priority before the 200-row display limit. Server action and
private-evidence APIs continue to apply responsibility, assignment and authority checks.

For a Location Card, use **Print Kanban → Print General Service Location Card**. Identify the
operator in **Kanban Service Tasks**, then scan by camera or keyboard wedge. The view retains its
scope through Refresh and live updates; **Show All** returns to the responsibility queue. A Card
scanned before login asks for operator identification and a rescan; it never becomes an Employee
credential. Empty Card contexts show an empty-work message. Logistics-purpose Location Cards
remain outside this service view.

Identity Cards only open existing tasks. A Task Schedule's permanent Service Point QR may also
create a due occurrence, but only with the matching responsibility and Start authority. An
existing outside-role occurrence resolves only to its Task ID for reference; it does not expose
its execution/evidence payload or create an Action Run.

## Service Task lifecycle

Every normal Service Task must be started before progress or completion can be reported.
Unstarted Planned, Due, Assigned and Overdue tasks show **Start**, with no **Report Progress**
or **Complete** action. `started_on` decides whether an Overdue task has already started.
After Start, In Progress and started Overdue tasks expose Progress and Complete and hide Start.
A started task in Correction Required retains **Correct and Resubmit**. Existing required
DocType Action and independent verification gates still apply, including Supervisor completion
on behalf of an operator.

Direct completion requests without a start timestamp are rejected with
`Start the Service Task before completing it`, before recording evidence, resolving an Action
Run or recording a completion event. The Service Panel also guards stale completion dialogs
and returns keyboard-scanner focus after this rejection or after its message is dismissed.
Starting a task refreshes the panel and moves the assigned task into **Active Work**.
Supervisors may still **Cancel / Bypass** an unstarted invalid or holiday occurrence with a reason.

## Cycle-bound process and sample identities

Each Process Task belongs to one Kanban Cycle. Controlled QC profiles can enable a Sample
Traveller QR (`CFG:SAMPLE:<process-task>`). Scanning it in the Production Operator panel loads the
owning card and exact Process Task. The form prominently displays item, batch, cycle, Work Order,
and operation so results cannot silently attach to a different production context.

## Controlled QC outcome

A controlled QC task requires a Sample ID and one of these outcomes:

- **Pass** completes the task under its normal verification rule.
- **Fail** blocks the Process Task, puts the Kanban Cycle on Hold, and opens a critical Kanban
  Exception. The gate remains closed.
- **Conditional Release** is only available when enabled on the profile and always requires
  independent supervisor verification.

A Supervisor may authorise a retest with a mandatory corrective-action reason. This preserves the
failed attempt's structured values, checklist, disposition, exception, and authorisation as a JSON
evidence snapshot while returning the task to a controlled Ready state. Passing and
verification clear the QC hold only when no failed controlled QC task remains.

Dynamic fields remain the structured measurement record. Private image, video, or PDF evidence is
stored through the shared S3 media registry as `process-task-evidence`; the Process Task form shows
thumbnails and short-lived links to originals.

The operator panels deliberately separate live camera capture from ordinary file upload. A camera
photo is available only while the task is In Progress and is rendered with the server timestamp,
task identity, device latitude/longitude, and reported GPS accuracy. The same capture proof is kept
as structured namespaced media metadata. Location permission is mandatory for this evidence mode.
Existing photos, PDFs, videos, and other allowed files can be uploaded separately without modifying
their contents. An operator may remove an accidental attachment; removal archives the registry
record and hides it from the active task while retaining the audit history and private object.

Controlled QC results are always cycle-specific and cannot use the reusable-task validity option.
The Process Task profile requires both a Test Method and a neutral Specification Reference.
