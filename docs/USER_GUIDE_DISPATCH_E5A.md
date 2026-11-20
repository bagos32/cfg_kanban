# Dispatch trip review, overnight choices and settlement — E5A

E5A connects a loaded Dispatch Plan to the existing lorry stock count (D3) and submitted recovery
movements. It records how the trip ended, releases or retains its prepared-stock commitments, and
preserves the original loading/delivery/vehicle history. It creates no stock movement or write-off.

This is the first E5 development increment. Guided recovery-transfer creation, mixed per-line
leftover dispositions, follow-on recovery Plans and the wider partial/refused known-customer
workflow remain E5B. Live site acceptance is still pending.

## Normal two-to-three-day trip

Use **one Dispatch Plan for the complete trip**:

1. Prepare and load the lorry normally. **Trip Date** is the planned departure date.
2. If recording an opening count, start the existing **Route Stock Count** after loading and before
   departure. The same count may span several days; it tracks submitted ERP movements.
3. Visit customers on days one, two and three using separate Delivery Sessions/Notes/proof. Keep the
   same Plan, vehicle Warehouse and remaining prepared quantities throughout. Complete each customer
   Session before the next visit. Re-identify the operator when authentication expires; the Plan is
   independent of the login session.
4. At the actual end of the trip, start the Dispatch Review, finish the physical closing count and
   reconcile the Plan as below.

There is **no forced daily Plan closure or daily reconciliation**. Passing midnight does not expire
or reset a Plan. Ordinary stock/certificate expiry, permissions and availability still apply on
each delivery. Do not begin an end-of-trip review every evening unless you intend a formal pause:
starting a review freezes new fulfilment until it is completed or resumed.

An explicit overnight pause is also supported, including two consecutive overnight pauses during
a longer trip. Its closing choice retains the same Plan's commitments and requires explicit Resume
before further customer fulfilment. Each formal pause uses its own closed balanced stock count.

## Responsibilities and access

The operator needs both the Plan's **Dispatch Responsibility** and **Logistics Reconciliation**.
Start/Complete permissions govern the actions. A Supervisor/Development Proxy with **Override**
permission must decide any remaining prepared stock, place a Hold, or abandon an ordinary review.
A fully delivered trip can be reconciled by an authorized Complete operator. An authorized Complete
operator may resume a formally carried overnight Plan; a Held review cannot bypass counted recovery.

Company, original lorry and stock scope come from the Plan. E4C direct warehouse/pickup Plans retain
their own closure workflow and are not Vehicle Delivery trip reviews.

## End-of-trip sequence

1. Finish or cancel every unfinished Customer Delivery Session, including its required proof.
2. Open the loaded Plan and select **Review / Reconcile Trip**, or use `CFG:CMD:REVIEW_DISPATCH` and
   scan the Plan. Confirm the prepared-stock summary to begin the review.
3. The new **CFG Kanban Dispatch Review** (`KDR-...`) freezes new fulfilment and preserves the opening
   loaded/delivered/remaining quantities. No stock quantity changes.
4. If returning/transferring leftovers, complete the existing authorized stock movement **after
   beginning the review and before closing the physical count**. Record its submitted Stock Entry.
5. Use the existing Route Stock Count panel to scan tags/containers and enter actual loose stock.
   Evaluate and close the balanced count. A variance must be resolved through D3; an unexplained
   difference cannot be settled here. The count must close after the review began.
6. Reopen **Finish Dispatch Review**, scan the Plan/Review, choose one numbered closing action, scan
   its closed `KREC-...` count, supply movement evidence when required, enter a reason and Confirm.
   If stock changed after the review screen was loaded, refresh and review the quantities again.

The route count covers **all** stock in that company-specific lorry, including other Plans and
unassigned stock. The Dispatch Review settles **only this Plan**. The screen separates prepared
loaded/delivered/remaining quantities, additional unassigned customer deliveries, and the lorry ERP
balance. The ERP balance includes other Plans and unassigned stock; this Plan's outstanding budget is shown
separately and is not a promise of freely allocatable stock or its current physical location.
Do not add Kg and Nos together; review quantities in their stock UOM. If several Plans share the same
lorry trip, begin all their reviews before closing the common lorry count, then settle each Plan
against that count with its own decision. Movement evidence remains exclusive to one review;
automatic trip-wide/bulk recovery remains E5B.

## Closing choices

| Choice | Result |
|---|---|
| No Remaining Prepared Stock | Requires every prepared allocation to be delivered. Finalizes the Plan after the balanced count |
| Close Trip - Stock Stays | Finalizes this Plan and releases its remaining commitments. Actual stock stays in the lorry, including overnight for a future trip |
| Continue Same Plan Overnight | Retains the Plan and its commitments. Records an Overnight review; explicit Resume is required before continuing |
| Returned to Warehouse | Requires exact submitted recovery-transfer evidence and the completed controlled manifest/tag location for tagged stock |
| Transferred to Another Lorry | Same evidence rules, with an active same-Company vehicle Warehouse destination. Original vehicle history remains unchanged |

Both overnight choices are made **while closing**, as requested. Closing with remaining prepared
stock records **Closed Incomplete**, keeping the distinction from full customer fulfilment. Native
Sales Order quantities are not rewritten. Fully delivered Plans record Completed. A final Plan
state of **Reconciled** stops new visits and releases its old commitments.

One E5A decision covers all remaining prepared allocations. A return/transfer uses one exact
Stock Entry and one destination; its matched tag/Item/Batch/stock-UOM quantities must equal this
Plan's remainder. A movement cannot settle two Reviews. Mixed destinations or some stock returned
while some stays require the later guided E5B workflow.

## Movement evidence and recovery limits

- Draft Stock Entries, wrong Company/source/destination, incomplete quantities and changed tags are
  rejected. The movement must post after review opening and before the chosen count closes; a
  future-dated posting or a movement made after that count requires a fresh count.
- Tagged movement requires its completed controlled Movement Manifest and updated tag ledger/location.
  Certificates, expiry and serial identities continue through the existing movement engine.
- Use existing authorized transfer workflows to create movements. Where the current floor workflow
  cannot represent loose Batch stock, a Supervisor uses the approved native ERP transfer with exact
  Item/Batch fields. E5A validates its evidence; it does not invent a Stock Tag or add a transfer engine.
- A settled recovery Stock Entry cannot be cancelled behind a closed trip. Use an audited follow-on
  movement. Old customer Delivery Notes cannot be reopened while their Plan is reviewed, held,
  overnight or settled; use controlled returns/recovery instead.
- This increment does not automatically create a new Dispatch Plan at the receiving lorry, change the
  original vehicle, write off damage, release a variance without evidence, or change ERP stock by
  editing a review. Those broader recovery actions remain E5B.

## Hold and resume

**Hold for Investigation** requires a Supervisor reason and creates a Critical Exception. Commitments
and stock remain controlled. A held review must be completed against a balanced closed count and
valid disposition; Resume cannot remove the Hold.

**Resume Plan** requires a reason. For an ordinary review, Supervisor authority is required and stock
must still match its original lorry context. For a formal overnight carry, it restores fulfilment
under the same Plan after rechecking the remaining stock. It retains the closed count and old review
snapshot. Resuming does not restore stock that was already moved away. Closed/reconciled trips
cannot be resumed through this action.

## Scanner and tablet controls

Print from **Kanban Operator → Scanner Command Labels**. All commands below use `CFG:CMD:`.

| Command | Purpose |
|---|---|
| REVIEW_DISPATCH | Open the Plan review and begin/resume selection |
| FINISH_DISPATCH_REVIEW | Choose the trip-closing action |
| HOLD_DISPATCH_REVIEW | Supervisor investigation Hold |
| RESUME_DISPATCH_REVIEW | Explicitly resume an eligible review/overnight Plan |
| DISPATCH_REVIEW_COUNT | Arm the closed route-count input |
| DISPATCH_REVIEW_MOVEMENT | Arm the submitted recovery Stock Entry input |
| DISPATCH_REVIEW_REASON | Arm the decision/hold/resume reason |
| DISPATCH_REVIEW_CAMERA | Camera scanner |
| DISPATCH_REVIEW_REFRESH | Re-read server status and quantities |
| CONFIRM / CANCEL | Submit the reviewed action / close the dialog |

Scan the `DPL-...` or `KDR-...` identity, choose `CFG:SELECT:1` through `CFG:SELECT:5`, then the
`KREC-...` identity. For a movement, scan its arm command followed by the exact Stock Entry ID.
Arm Reason and scan its text, then Confirm. Touch fields/buttons use the same controller. Enter/Tab
suffixes, camera cancellation, ordinary blank Tab/Shift-Tab and focus restoration are supported.
The existing D3 count controls remain separate; complete kiosk/device acceptance still needs testing.

A lost response keeps the original token/details locked while that dialog remains open. Retry Confirm
for that same action. After closing/refreshing, re-read the Plan/Review's recorded state before any
correction; opening/resuming does not create parallel reviews and terminal closing decisions cannot
be applied twice. A changed-payload replay is rejected. Never delete the audit record to clear doubt.

## Deployment and acceptance

Migrate the additive Review DocType/Plan fields and build assets before using them. No old trip is
settled automatically. Existing E4C work is retained in this change set at the owner's request.
The current Git base remains `fc889fa`; E4C and E5A are pending manual commit/deployment.

See [the E5A acceptance checklist](TEST_DISPATCH_E5A_RECONCILIATION.md). Offline tests do not verify
native ERP posting, MariaDB concurrency, migration, stock evidence, physical scanning or camera use.
