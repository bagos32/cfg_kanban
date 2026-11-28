# Service Schedule overlap acceptance

Implementation: **Skipped While Open**, added 28 November 2026. Live acceptance: **Not run**.

Use a test site and test Task Schedule only. Do not dispose of production tasks for this check.
Migrate after updating the app so the new Select option is available. Existing schedules retain
their configured policy; **Prevent While Open** remains the default. Configure the new policy on
the normal **CFG Kanban Task Schedule** form, with its existing maintenance/manager permissions.

## Expected behavior

An hourly task generated at 09:00 and finally closed at 11:20 skips the 10:00 and 11:00 slots.
Next Due On becomes 12:00. No skipped-slot Task or Action Run is created. The interval is not reset
to 12:20. Closure includes final verification/document-gate completion, cancellation and bypass;
awaiting verification/document posting/correction remains open work. Already-created tasks remain
in history. A new task becomes eligible at 12:00; actual generation uses the existing hourly
scheduler or a due Service Point scan.

## Offline coverage

`test_service_schedule_overlap.py` executes the actual generation/recurrence functions and Task
`before_save` hook using document, database and clock adapters. It covers multiple missed slots,
completion between scheduler runs, terminal resaves, cancellation/bypass, pending gates, stale
requests, repeated scans, fractional/hour/day/week/month/calendar recurrence, month ends, large
backlogs, busy Task deferral, holidays, manual requests and the existing two policies. Schema regression confirms all
three options and the unchanged default. These checks do not execute a real Frappe transaction,
worker, physical scanner or database lock.

## Live procedure

1. Record the deployed Git revision, site, test Schedule and generated Task IDs. Confirm site
   scheduler status. Choose Time Interval / Hours / 1, a future Next Due On, and Skipped While Open.
2. Let the first occurrence generate and start it. Keep it open past two due slots. Check that
   scheduled generation creates no additional Task and advances Next Due On beyond the current time.
3. Inspect **CFG Kanban Event → Scheduled Task Skipped While Open**. Confirm its Schedule, blocking
   Task, skipped count, first/last due times and next due time. Last Generated On must not change
   because of a skip. Repeat scheduler/Service Point requests: no duplicate Task or skip audit.
4. With another test occurrence, complete after a due slot but before the next scheduler sweep.
   Confirm the Task closes and the close transaction drops the missed slot. Immediately scan its
   permanent QR: show the next due time, without generating the skipped occurrence. After the next
   genuine due time, scan again: exactly one new Task appears.
5. Repeat with Require Supervisor Verification and a required DocType Action. Pending verification,
   correction and document posting continue to block another occurrence. Only final closure advances
   missed slots. Existing approval/posting requirements must still apply. No Action Run is created for
   a skipped slot. Repeat Supervisor Cancel and Bypass with reasons; keep disposition audits.
6. Repeat a simultaneous scheduler/Service Point generation request near closure. Confirm exactly
   one eligible Task, no duplicated skip audit, and no deadlock/error left unresolved. Verify rollback
   in a controlled test transaction: failure during closure must retain both the original Task state
   and original Next Due On. This is a database acceptance check, not proven by offline adapters.
   Generation uses Frappe v15's nonblocking `skip_locked` lookup; a busy closing Task defers generation
   without consuming a slot. An explicit manual request in that state asks for a safe retry.
7. Compare Prevent While Open: overdue Next Due On is retained and the deferred task remains eligible
   after closure. Compare Allow Parallel Occurrences: each scheduled occurrence remains independent.
8. Test Calendar Schedule, a listed holiday and an explicit manual request while a task is open.
   Holiday skip keeps its separate audit; the manual request resolves the open task. Existing Company,
   workstation, responsibility and Start/Complete/Verify permissions remain in force.

Record expected/actual results, Schedule/Task/Event IDs, timestamps, and any accepted exceptions.
