# Customer Return QC — monitoring and follow-up

Development prepared 23 November 2026 above `2f988ba`. Native-site acceptance remains **Not run**.
The page uses the existing Return Case, QC inspection, return accounting, stock disposition and
owned-refusal services. Reading or opening a case creates no receipt, credit, QC result or task.

## Open the dedicated page

Use **CFG Dispatch Control → Customer Return QC**, **Kanban Logistics → Customer Return QC**, or
**Customer Return QC** on a saved Return Case. The normal full-page route is
`/app/kanban-return-qc`; `/app/kanban-return-qc/KRTN-…` opens one exact case. The page is separate
from trip driving and office planning; no planning popup is required.

Sign in with the existing operator QR/PIN. The current shared operator session can be reused.
Set **Customer Return QC** in the operator's Responsibilities, with **Can Start** for receipt/start
and **Can Complete** for inspection completion. An unrestricted Supervisor/Development Proxy may
use the existing View All Responsibilities rule. An ordinary empty Responsibility list is denied.

The ERP terminal user needs **Kanban Terminal** (or another existing terminal-authorized role),
Return Case and Company Read permission. **Quality User** or **Quality Manager**, with suitable
Company/User Permissions, supplies the usual QC document access. Kanban Terminal alone does not
grant Return Case/Company reads. Other linked documents require their own native Read permission;
accounting/stock preparation and submission retain their existing role gates. Company scope comes
from the terminal user's native permissions, not an operator-selected Company override.

Deploy through the owner's usual manual migrate/build/cache procedure to sync the Page, Workspace
shortcut and assets. This phase adds no transactional DocType, database backfill, scheduled worker
or independent return engine. Existing cases need no conversion. The short Logistics recent-return list also uses
native record permissions; it remains a convenience list beside this full monitor.

## Worklist and history

The default **Needs Follow-up / Oldest intake first** includes all accessible nonterminal cases,
not just the 30 most recently modified returns. It includes awaiting receipt, inspection in progress,
accounting pending, physical-stock pending, rejected claims and exceptions. **Accounting Completed**
remains in follow-up until its separate physical track finishes.

Use **All Returns** for the complete accessible history, or **Closed / Cancelled** for closed,
cancelled and posted delivery-correction cases. These are paged views, not automatic closure or
record deletion. Native state is retained exactly. A rejected claim or investigation remains
visible for QC/Supervisor review until the existing controlled workflow resolves its case.

Filter by Company, Customer, Inspection Location, Driver Trip, exact Case State, Workflow, inclusive
intake date range, and Case/Customer/Reported Source text. Select **Apply Filters**; **Clear Filters**
returns to the default queue. Choose Recently Updated when investigating new feedback. Summary
counts use the same native permissions and filters as the list, across all pages. Next/Previous
can reach older records; there is no silent thirty-case cutoff.

Each row shows case/customer/Company, return kind, QC state, age since intake, accounting/credit
feedback, physical disposition/receipt status and the functional team responsible for the next
step. Age is descriptive; it is not an invented overdue/SLA threshold. Last Refreshed is shown.
An unacknowledged QC receipt stays **QC receipt unconfirmed** even if a driver has collected the
goods. A recorded collection lorry is a historical collection reference, not live GPS/custody proof.

## Inspect a case and follow up

Select a row, or scan its Temporary Return Note/case number. Case UUID aliases and normal case
links resolve through the same Company/record permissions. A selected historical case can remain
outside the currently displayed worklist/page. **Clear Selected Case** returns to the list.

The detail shows exact Items, printed tag references, Batch, expiry, stock UOM, claimed/received/
accepted/rejected quantities, QC disposition/reasons, inspection operator/times, QC notes and source
references. Totals are grouped by UOM; kilograms and pieces are never added into one quantity.

**Open QC Inspection** opens the exact case in the existing Logistics inspection/evidence view.
It rechecks the same QC operator, native case/Company access and current identity before opening.
It does not automatically receive goods or start/complete QC. Use existing **Receive and Start QC**,
then **Complete QC Result**, with the normal quantity/disposition/evidence controls. Both server
mutation endpoints now recheck Case and Company Read permission before changing data. Existing
private S3 photo/document evidence stays in that workflow; this monitor stores no media copies.

**Open Return Case** opens the normal DocType page. Permitted linked documents are separate buttons.
Their live native Draft/Submitted/Cancelled status is displayed on the button; list status fields
are the Case's recorded feedback. No unauthorized document link is exposed by this monitor.

| Pending track | Who follows up | Existing action |
| --- | --- | --- |
| Awaiting QC receipt | QC | Physically receive and start QC |
| QC In Progress | QC | Verify received/accepted/rejected quantities and complete inspection |
| Investigation/rejected claim | QC / Supervisor | Review QC reasons, physical custody and controlled case recovery; the monitor does not manufacture closure |
| Accounting source/credit pending | Accounts | Return Case → Accounting decision, then native Sales Invoice Return/custom Credit Note review and submission as configured |
| Accepted physical stock pending | Stock / Quality Manager | Return Case → Stock disposition, then authorized native receipt/disposal and feedback |
| Cancelled or failed document/exception | Supervisor plus owning team | Use the existing controlled replacement/recovery and inspect the native document |
| Company-owned refusal | Supervisor / Stock | Existing refusal release, controlled recovery or submitted Material Issue disposal confirmation |
| Delivery Note Correction | Stock / Accounts | Inspect the linked Return Delivery Note and any accounting attention; this is not QC-return intake |

Accounting and physical disposition can be pending simultaneously. Completing one never makes
the monitor hide the other. Closed/cancelled native cases remain accessible in history; the page
cannot manually mark an unresolved case complete.

## Company-owned refusal safeguards

Quality/damage refusal cases keep **Company-owned refusal** and explicit no-credit/no-duplicate-
receipt guidance. They stay company stock. QC approval alone does not release their stock hold.
After inspection, authorized staff use the existing Driver Trip/refusal outcome or controlled
recovery/disposal. Where permitted, the monitor shows the exact refusal lines' current held-stock
state and warehouse. A different case's lines are never combined with them.

Old customer goods continue through D2A QC, D2B accounting and D2C physical disposition. They are
not received into available ERP stock simply because a Temporary Return Note or QC result exists.

## Tablet, scanner and refresh

The page offers **Scan with Camera**, fixed-scanner Enter/Tab input and touch buttons. Start with
operator identity. Scanning a normal KRTN return QR before login retains its case selection and
asks for the QC credential; it is not sent as an operator credential.

- **CFG:CMD:VIEW_RETURN_QC_MONITOR** opens the page from Logistics (or clears its selection there).
- **CFG:SELECT:1–10** selects an exact visible numbered case.
- **CFG:CMD:NEXT_MATERIALS / PREVIOUS_MATERIALS** pages cases.
- **CFG:CMD:QC_INSPECT_RETURN** opens the selected case's existing inspection workflow.
- **CFG:CMD:RETURN_CASE_RECORD** opens its normal Return Case form.
- **CFG:CMD:REFRESH**, **CFG:CMD:CANCEL** and **CFG:CMD:HELP** refresh, clear selection or show help.

These monitor labels are selectable in **Kanban Operator → Scanner Command Labels → Customer Return
QC**. They are context-specific viewing/navigation controls, not approval/stock-posting commands.
A blank or modified Tab keeps normal form navigation. Camera acceptance is limited to one result;
late results are discarded on hide/operator replacement. Safe close/errors return scanner focus.

Visible pages refresh every 15 seconds. Background reads do not renew operator inactivity. Native
permission rejection removes cached rows/details; a network failure marks retained data stale and
blocks workflow navigation until Refresh succeeds. Changing operator clears old case/filter data.
The page stops polling and drops cached detail when leaving it. Actual mobile/browser and ERP
acceptance must be recorded with [the test checklist](TEST_CUSTOMER_RETURN_QC_MONITOR.md).
