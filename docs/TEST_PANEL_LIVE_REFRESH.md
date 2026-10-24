# CFG Kanban Acceptance Test — Service and Logistics Live Refresh

## Purpose

Confirm that floor operators receive Supervisor and parallel-operator updates without manually
reloading the browser, while scanner work and open forms remain protected.

## Service Task Panel

1. Open the Service Task Panel on Terminal A and identify an operator.
2. Open the same task from a Supervisor session on Terminal B.
3. On Terminal B, start, report progress, request correction, verify, cancel, or bypass the task as
   permitted by the test profile.
4. Do not press Refresh on Terminal A. Wait up to 15 seconds.
5. Confirm Terminal A shows a blue update alert and the new status, action buttons, progress summary,
   or Supervisor instruction.
6. Filter Terminal A to one task and repeat an update. Confirm the filter and scroll position remain.
7. Open a task form on Terminal A, change the task on Terminal B, and wait 15 seconds. Confirm the
   open form is not interrupted. Close it and wait for the next check; the panel must then refresh.
8. For the race-condition check, start a live check and immediately open or type in a task form.
   Confirm a response that was already in flight is discarded: it must not redraw the task cards,
   move focus, erase input, or show an update alert. After closing the form, the next check must
   still detect and apply the change.

## Logistics Operator Panel

1. Open one Manifest on Terminal A and leave the scanner in lookup mode.
2. On Terminal B, add/remove a permitted line, prepare the Manifest, submit or approve its linked ERP
   document, dispatch it, or receive it.
3. Do not press Refresh on Terminal A. Wait up to 15 seconds.
4. Confirm Terminal A shows a blue update alert and refreshes the Manifest state, document status,
   quantities, action buttons and open/recent lists.
5. Repeat with an open Delivery Session, Return Case, or Route Stock Count and confirm its current
   view updates.
6. Arm dispatch or receipt scanning on Terminal A, then make a safe parallel update on Terminal B.
   Confirm Terminal A retains its transaction scan mode after refreshing.
7. Open a confirmation/data-entry dialog on Terminal A. Confirm live refresh waits until the dialog
   closes and does not erase typed values.
8. While a live check is in flight, scan a tag or press a Manifest action on Terminal A. Confirm the
   foreground scanner/action completes without the background response replacing its Manifest,
   scan mode, input focus, or dialog. The deferred external change must appear on a later check.
9. Begin a frozen ERP creation/submission action just before the polling interval. Confirm live
   refresh does not apply until the frozen action is finished.

## Connection behaviour

1. Temporarily interrupt the network for one check.
2. Confirm the scanner status says the live check was interrupted and will retry.
3. Restore the network and confirm the next successful change refreshes normally without logging the
   operator out or requiring a page reload.

Expected result: unchanged checks remain lightweight; full panel data is fetched only after a
revision change. Operators are informed of external changes without losing scanner context, dialog
input, filters, or scroll position. A refresh abandoned because of a popup or operator interaction
must not advance its revision marker; the update must therefore be retried rather than lost.
