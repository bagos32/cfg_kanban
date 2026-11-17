# Station bundling and tagging before a Manufacture Draft

Prepared 17 November 2026. Requires migration/build of these changes. Offline validation
is not site or kiosk acceptance. Use this for finished Items without ERPNext unit-serial
tracking; Batch tracking and printed packaging serial evidence remain supported through
the existing production trace/certificate flow.

## Simple setup

1. **Production Kanban Master**: enable **Declare Finished Output at Station Before
   Receipt**. Set **Output Packing Workstation** to the workstation where operators
   physically collect and bundle the final output. It may be the final production
   workstation or a dedicated packing bench. Leave blank only when output should stay
   assigned to each final Job Card's own workstation. Keep the finished Item, stock UOM,
   Company and destination warehouse consistent with the released Work Order.
2. **CFG Kanban Material Trace Policy**, finished Item + Company: Enabled; Trace Level
   **Exact Handling Unit**; **Production Output Tags = Required Physical Tag**; enable
   **Allow ERP Quantity Across Multiple Tags**. Set Require Batch consistently with the
   Item's ERP Batch setup. Do not create an extra Process Task or BOM operation just
   to bundle/tag already-produced goods.
3. **CFG Kanban Card**: Card Type **Workstation Queue Card**, correct **Current Station**
   and **Queue Company**, Active. Print its **Workstation Queue Card** label. This is the
   station identity the operator scans; a Warehouse Operations Card tags already-posted
   stock and is a different workflow.
4. Register the unused main tags in an active Tag Family/Tag Range Registry. For a
   permanent bin, create a reusable Handling Unit with role **Production Output
   Container**, correct Company and finished-goods receipt Warehouse. It must be empty,
   Released, outside logistics transactions and free of operation Hopper WIP. One bin
   carries one output bundle at a time. A bundle may use a new main tag, the permanent
   bin QR alone, or a new main tag inside that bin.
5. **Operator Profile**: enable **Partial Complete / Progress**, with the final operation
   and packing workstation in scope. The operator declares reported good output and
   does not need receipt-posting permission. **Supervisor**: unrestricted operation and
   workstation scope, **Complete** and **Partial Complete / Progress** permissions, to
   prepare/adopt and post the Work Order receipt. Set **Manufacture Receipt Posting =
   Create Draft for Tag / Batch Review** for a clear review workflow. Declared output
   forces Draft preparation even if a Master previously selected automatic submission.

## Operator sequence

In **Kanban Operator**, identify the operator, scan the station card, then select
**Bundle / Tag Finished Output** (or scan `CFG:CMD:PACK_FINISHED_OUTPUT`).

1. Select the exact Work Order if several have output here. The screen shows final
   operation good quantity, earlier receipt quantity, pending declarations and the
   quantity still available to bundle. It includes positive good output while the
   final operation is running; rejects, BOM targets and estimates add no availability.
2. Enter/set the quantity physically in this bundle.
3. Scan an unused main tag and/or an empty Production Output Container. A tag plus bin
   creates one physical tagged bundle inside that bin. The same identity cannot be
   reserved on another declaration or ordinary Draft Material Trace.
4. Confirm. Repeat for the next bundle. This creates **CFG Kanban Output Declaration**,
   reserves the identities and marks a pending bin Reserved. It does not report Job Card
   output again, create a Stock Tag balance, change ERP stock or close the Work Order.
   Scanning the reserved tag/bin in Logistics shows its pending Item/quantity/Work Order.

Example: final operation has reported 3 good pieces against a 5-piece Work Order.
Declare tag FG001/bin BOX1 = 2 and FG002/bin BOX2 = 1. Available becomes 0; ERP output
stock remains 0. If another 2 good pieces are reported, available becomes 2. Declare
that bundle when physically packed. The five pieces have been reported once and
bundled once, not produced twice.

Scanner-only sequence: `CFG:CMD:PACK_FINISHED_OUTPUT` → physical station card →
`CFG:SELECT:1`–`CFG:SELECT:10` if needed → `CFG:QTY:GOOD:n` (or `+n`) → main tag and/or bin →
`CFG:CMD:CONFIRM`. `NEXT_MATERIALS` / `PREVIOUS_MATERIALS` page choices.
`OUTPUT_STATION`, `OUTPUT_TAG`, `OUTPUT_BIN` and `OUTPUT_REASON` are `CFG:CMD:*` commands
that explicitly arm the next scan. Physical identities retain their own labels. The
commands are selectable in **Scanner Command Labels** and described in Scanner Help.

A lost response keeps the exact request/token in browser storage across Cancel,
reopen and refresh. The original operator retries Confirm to reconcile it. Confirmed
server rejection permits corrections. HTTPS, local storage and Web Locks support are
required. No operator session secret is stored in the pending request.

## Supervisor receipt and closure

After all Job Cards finish and the normal material/settlement gates pass, open the
production Card and **Prepare Manufacture Receipt**. The screen lists pending bundles
and defaults the accepted finished quantity to their total.

- Prepare the receipt for **all currently pending declared bundles of that Work Order**.
  The accepted quantity, Item, stock UOM and target warehouse must match. Partial-bundle
  adoption and silently selecting only some tags are not supported. Correct a wrong
  bundle through cancellation/redeclaration before preparing the receipt.
- Preparation creates the native Draft and adopts the exact tag/bin/quantity lines.
  Earlier Material Run input scans are adopted through their existing settlement path.
- Review the Draft trace, actual input use, certificates and finished Batch/expiry.
  Existing optional printed-expiry-to-Batch rules remain unchanged: one matching proven
  date is required; mixed expiry evidence is not silently combined into a new Batch.
- Submit as Supervisor, then complete the normal Work Order/Card closure. ERPNext
  submission creates/assigns the authoritative Batch and activates the exact Stock Tags
  and bin memberships. Physical tag + bin mode keeps the preprinted main tag inside the
  bin. The operator's original bundling timestamp becomes the tag/fill Packing Timestamp.
  Declaration states progress **Declared → Bound to Draft → Posted**, with audit events.

A pre-existing Manufacture Draft must be reviewed/posted/discarded before declaring
more bundles for the Work Order. If receipt preparation loses its response, refresh
and inspect that existing Draft; do not create another receipt for the same output.
For legacy receipts whose output has no station attribution, remaining station
availability is conservatively reduced; a dedicated packing workstation can pool the
reported final output into one controlled station.

## Corrections

Use **Cancel a Declaration** (scanner `CFG:CMD:CANCEL_OUTPUT_DECLARATION`), select its exact
numbered record, scan/enter a reason and Confirm. Physically reconcile the bundle/tag
before cancelling its assignment. Its quantity returns to the station's unassigned
reported-good pool; no production is reversed or ERP stock discarded.

An operator may cancel their own unbound declaration. Another operator's declaration
or one bound to a Draft requires an unrestricted Supervisor. Bound cancellation also
cancels its trace line and releases both identity reservations together. Direct trace
line cancellation and Draft abandonment/deletion are blocked while declarations remain
bound; cancel/reconcile declarations first, then review the Draft quantity and recreate
it when needed. Posted output uses existing controlled ERP receipt reversal; declarations
become **Voided** while history, certificate provenance and native tag reversal remain.

Declaring output requires a current submitted open Work Order. Cancelling an unposted
declaration remains available for recovery after Work Order closure, provided the station
and authorized operator are still active. Original declarations and audit history are
never deleted.
