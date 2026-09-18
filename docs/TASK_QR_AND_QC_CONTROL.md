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

Controlled QC results are always cycle-specific and cannot use the reusable-task validity option.
The Process Task profile requires both a Test Method and a neutral Specification Reference.
