# Operation Material Runs — High-frequency Production Traceability

## Purpose

An Operation Material Run is a short, auditable production boundary inside one Job Card or
Process Card execution. It is intended for fast repeated floor work where the operator must later
bind raw-material Batch/serial evidence to a small output interval without slowing every unit.

This feature is optional per Operation Profile. Existing production remains unchanged while
**Material Run Control** is **Disabled**.

## Package status

Package 1 provides the safe run foundation:

- operation-level configuration and immutable runtime snapshots;
- one concurrently open Material Run per execution lane;
- scanner-only start using `CFG:CMD:START_MATERIAL_RUN`;
- numbered `CFG:SELECT:1` to `CFG:SELECT:10` disambiguation;
- configurable output-boundary capture;
- idempotent creation, operator/session audit, live refresh and printable command label;
- automatic linkage and closure when the next operator progress record is posted;
- scanner-safe cancellation before progress.

Package 2 adds opt-in source quantity evidence:

- per-BOM-component **Material Run Tracking = Source Tag Quantity**;
- immutable rule snapshots on newly released Process Executions;
- scanner sequence of Material Quantity then physical source Stock Tag;
- Item, Company, Warehouse, UOM, active/released and available-quantity validation;
- immutable **CFG Kanban Operation Material Draw** audit rows;
- cross-execution operational reservation so a shared bulk tag cannot be over-declared;
- BOM-ratio progress gating and FIFO carry-forward into later Material Runs;
- cancelled-draw audit with reservation release;
- no change to operations and components that retain Disabled/No Run Tracking defaults.

Package 3 adds controlled ERP settlement without a second physical scan:

- **At Job Card End** creates a dedicated Draft `Material Consumption for Manufacture` only for
  the used Material Draw quantities of that Job Card;
- **At Work Order Manufacture Receipt** adopts those quantities into the final native
  `Manufacture` entry instead;
- ordinary Skip-WIP inputs are consumed only by final Manufacture and no longer create a duplicate
  intermediate consumption entry;
- the original source Handling Unit, Warehouse, UOM, Batch and quantity are adopted into Production
  Material Trace through the same validation used by a live scan;
- different scanned input Batches are split into exact native Stock Entry Detail rows;
- ERP submission changes stock/Handling Unit quantity and marks the Draw **Bound to ERP**;
- Draft line cancellation, Draft abandonment and submitted-entry reversal restore controlled Draw
  state; and
- Cycle closure is blocked by any linked Draft production Stock Entry or used, unsettled Draw.

The following packages must still be completed before this is accepted as the full
serial-controlled material-trace flow:

1. exact serial reservation and serial-range evidence with parallel-machine collision protection;
2. live acceptance of controlled post-progress quantity correction and ERP cancellation/reversal;
3. complete floor acceptance of both settlement timings and recovery cases.

## Minimal configuration

In **CFG Kanban Master → Operation Profiles**, use these values only on an operation that needs
the high-frequency flow:

| Field | Recommended pilot value |
|---|---|
| Output Reporting Mode | Incremental |
| Material Run Control | Optional first; Required Before Progress after Package 2 acceptance |
| Output Boundary Requirement | Every Material Run |
| Allow Unused Material Carry-forward | Enabled |
| ERP Settlement Timing | At Job Card End |

For each tracked BOM row, select **Source Tag Quantity**, its physical scan Warehouse, and
**Standard ERP / Tag Flow**. The calculated ratio is BOM component quantity divided by BOM output
quantity. Leave simple components at **No Run Tracking**. Do not enable it for an ERPNext
serial-controlled Item until the exact-serial package is delivered.

Source Tag Quantity currently requires **Production Material Mode = Skip WIP Transfer**. At Job
Card end, BOMs controlled against Job Card use the Job Card material rows. BOMs controlled against
Work Order use the immutable used Material Draws as the exact settlement scope while preserving
the originating Job Card in CFG Kanban's audit field.

## Scanner-only pilot

1. Release/allocate production. For certified inputs, prepare the Material Run while the operation
   is **Ready**, then Start Operation after confirmation passes; begin physical work only after that.
   Operations without input certificate requirements may retain their normal start-first sequence.
2. Scan `CFG:CMD:START_MATERIAL_RUN`.
3. If several enabled operations are active, scan the displayed `CFG:SELECT:n` label.
4. If requested, scan the first output serial or other printed output boundary.
5. Scan `CFG:QTY:MATERIAL:n`, then the physical source Stock Tag for each tracked component.
6. Scan `CFG:CMD:CONFIRM`.
7. Verify that the execution lane displays the open Material Run number and boundary and that each
   Draw is recorded without reducing ERPNext or Handling Unit stock.
8. Scan `CFG:CMD:START_MATERIAL_RUN` again. Verify that it reports the existing open run rather
   than creating a second run.
9. Report a positive progress quantity. Verify that the BOM-ratio quantity is used, the progress
   record links to the Material Run, the run becomes **Progress Posted**, and any remainder becomes
   **Carry Forward**.
10. Start another run by mistake, scan `CFG:CMD:CANCEL_MATERIAL_RUN`, then Confirm. Verify that the
   run and staged Draws are Cancelled before progress and no reservation remains active.
11. For an operation where Material Run Control is Disabled, verify that the start command says no
   eligible operation is available and that normal production remains unchanged.
12. If **ERP Settlement Timing = At Job Card End**, complete/submit the Job Card, select/scan
    **Prepare Materials**, choose the Job Card when prompted, and use **Settle Material Runs**.
    Verify the Draft already contains the earlier source scans. Submit it with the normal scanner
    command; do not scan those tags again.
13. If **ERP Settlement Timing = At Work Order Manufacture Receipt**, finish all Job Cards and
    prepare Manufacture. Verify the final Draft already contains the earlier source scans. Scan
    only other required physical inputs and the finished-output tag, then submit.
14. Verify no unused `Material Transfer for Manufacture` or duplicate consumption Draft remains.
    Attempting to close with any linked Draft or unsettled Draw must be rejected with its identifier.

Follow `docs/TEST_OPERATION_MATERIAL_RUN_DRAWS.md` for scanner evidence and
`docs/TEST_OPERATION_MATERIAL_RUN_SETTLEMENT.md` for ERP settlement. A Draw remains only an
operational reservation until its linked native Stock Entry is submitted. Exact serial membership
is not included; do not enable Source Tag Quantity for an ERPNext serial-controlled Item.


## Warehouse-local FEFO and full Work Order override

Material Run source preview and final Start confirmation now reject expired source material.
For Batch-controlled Items, the Batch must exist, belong to the Item and not be disabled. When
both the tag and Batch have expiry dates, the earlier date wins; a later printed/tag date cannot
extend native Batch validity. An expiry equal to today's site date remains valid through today.
Carry-forward sources are checked again when starting a run and selected sources are checked
again before progress consumption, so an overnight run does not bypass expiry protection.

FEFO is evaluated inside the exact Company, Item, source Warehouse, stock UOM and compatible
Process Certificate Set. Held, inactive, unavailable, in-transit, incompatible Batch and active
manifest stock is excluded. Loaded production-container content is eligible only with a valid
single active fill in the same Company/Warehouse. Dates sort earliest first; undated stock is
last. Receipt/packed time and internal identity break ties. A smaller earlier balance is not
silently skipped to satisfy a larger requested quantity: use the smaller balance first.

An exception requires a supervisor with Override permission and unrestricted operation and
workstation scope, because the approval applies to the **entire Work Order**, including every
operation card, lane and later micro-run. It is not scoped to the initiating micro-run or Card.
It never allows expired/disabled/incompatible material or bypasses quantity/identity checks.
The approval is valid only while that exact Work Order is submitted and active. It does not
apply to another Work Order or automatically approve a new order when a reusable Card is reused.

On the active production Card, use **Approve WO FEFO Override**, or print and scan
`CFG:CMD:APPROVE_MATERIAL_FEFO_OVERRIDE`. If several orders are eligible, scan `CFG:SELECT:n`,
then scan the reason text and Confirm. Touch users can enter the same reason in the dialog.
The supervisor records one active approval; subsequent operators use it without repeating the
approval for each micro-run. The Material Run guide shows the active Work Order and reason.
Every draw that bypasses priority stores the approval link and immutable rotation evidence.

To stop the exception, use **Revoke WO FEFO Override** or
`CFG:CMD:REVOKE_MATERIAL_FEFO_OVERRIDE`, select the exact context, scan a revocation reason,
and Confirm. Revocation targets the exact displayed approval so a stale request cannot revoke
a newer replacement approval. Cancel safely exits either dialog. Scanner focus is restored
after errors/cancel, using the shared confirmation scanner. Approval/revocation records and
events remain in the audit history. Revocation affects new draws, not deletion/reversal of
previously authorized physical consumption.

## Material Run quantities in Operational Inventory Balance

Both Summary and Tag Detail show four additional quantities:

- **Material Run Reserved**: unused quantity held in active Material Draws.
- **Consumed Pending ERP**: used quantity not yet bound to a submitted ERP transaction.
- **Operational Remaining**: posted tag balance less consumption awaiting ERP.
- **Operationally Available**: tag availability less outstanding Material Run reservations,
  accounting for the used portion already reserved by a Draft Material Trace.

Example: posted tag quantity 1000, drawn 100, used 60, unused 40 gives operational remaining
940 and operationally available 900. ERP/tag quantity stays 1000 until submission. After the
60 units are adopted into an ERP Draft, the trace reserves those 60; the report subtracts only
the additional 40 and still shows operational availability 900. After submission changes
the tag to 940 and marks the draw Bound to ERP, it contributes no second deduction. Cancelled
draws contribute nothing. Unused balances on settled draws follow the existing release rules.

For raw materials controlled by ERPNext, select **Inventory Control Mode = ERP Stock**, or
clear that filter to include both inventory modes. The existing default **Kanban Operational
Inventory** excludes ERP Stock Items. Refresh the report after floor activity.

Existing Total, Reserved, Available and ERP Actual fields remain posted/ledger values. The new
fields are operational views and do not post stock. Certificate pending-output rows do not add
raw-material reservations again. Company, Warehouse, Item, UOM, quality and certificate filters
apply to the same source-tag scope. Quantity summary cards are suppressed for mixed UOMs.

Migration is required for the approval DocType and immutable draw evidence fields. Local tests
are not site acceptance: verify native transaction rollback, concurrent starts/revocation,
settlement/cancellation and scanner-only kiosk behavior on the isolated test site.


## Actual material quantities and Work Order yield approval

Material Run output checks use the snapshotted BOM component-to-output ratios in stock UOM.
On tracked operations, reporting output needing more than the scanned/declared material is
blocked by default. Good + Reject cannot exceed Processed quantity in the output stock UOM.
Raw material and output UOMs are not compared numerically without the BOM ratio.

An unrestricted supervisor can approve a **full Work Order Yield / Quantity Override** with a
reason. It applies to all that Work Order's operation cards and micro-runs, remains separate
from FEFO approval, and can be revoked. It permits a recorded variable-yield exception but
does not invent stock, bypass source availability, certificate/expiry checks, native ERP or
customer overproduction limits, or expand a Cycle's fixed allocation. ERP quantity limits must
still be resolved through the normal controlled planning process.

Report Progress has an optional Actual Material Used table. Each component uses its own stock
UOM. Zero/blank keeps normal BOM-based consumption; a positive amount records explicit use.
With several components, scan CFG:SELECT:n before CFG:QTY:MATERIAL:n, then scan Good/Reject
and Confirm. Lists have ten choices per page; CFG:CMD:NEXT_MATERIALS and
CFG:CMD:PREVIOUS_MATERIALS change pages in Progress and Correct Material Use.
Unused withdrawn material remains carry-forward; withdrawal is not automatically
consumption. Without an approved variable-yield exception, declared actual use must support
the reported output. With approval, a smaller available scanned quantity may support the
recorded yield exception, and the actual used amount and approval are retained in the audit.
No-tracking components cannot supply measured yield evidence; configure Source Tag Quantity
rules before expecting an automatic material-limited output check.

Settle Material Runs preserves used Draw quantities. If recorded usage is 5 bags and ERP mapped
only 3, the Draft input row is sized to the recorded 5 rather than clipping the trace to 3.
Over-BOM native posting requires the Work Order quantity approval, and ERP validates actual
stock and its own manufacturing limits. Generic Material Trace no longer silently uses only a
draft estimate when a larger tag is scanned: scan an explicit Material Quantity first. The
trace scanner accepts CFG:QTY:MATERIAL:n for ordinary input tags as well as WIP bins.

Supervisor correction before ERP posting is available through **Correct Material Use**:
select the operation, then the exact recorded draw/trace, scan Material Quantity and a reason,
then Confirm. Draw usage can be corrected only within its original scanned quantity; extra
physical material must be recorded first. A draw already adopted into an ERP Draft must have
that Draft discarded/cancelled first, then be corrected and settled again. For an ordinary
Draft trace, correction retains the original cancelled allocation, resizes the native input row
and reserves the corrected quantity on the same source tag. All corrections retain before/after
quantities, reason, actor and a stable retry identity. Submitted ERP entries require controlled
ERP cancellation/recovery; this function does not directly edit posted stock or history.

Scanner command labels (selectable in Print Command Labels):

- CFG:CMD:APPROVE_WO_YIELD — choose context, scan reason, Confirm.
- CFG:CMD:REVOKE_WO_YIELD — revoke the exact displayed approval with a reason.
- CFG:CMD:CORRECT_MATERIAL_USE — choose operation and allocation using CFG:SELECT:n, scan
  CFG:QTY:MATERIAL:n, scan reason and Confirm. Cancel exits safely; error/cancel restores focus.

Migration is required for the new Work Order approval DocType. No historical Job Card output,
Material Draw, trace or ERP posting is silently rewritten. Offline test success is not live
acceptance; verify stock posting, native ERP quantity tolerances, rollback, concurrent correction,
permissions and scanner-only kiosk behavior on the isolated test site.


## Certificates before physical use

The same Start Material Run scanner action works while an operation is **Ready**, **In Progress**
or **Paused**. A Ready operation stays Ready after preparation; the operator must still Start
Operation before physical work or reporting progress from that run. Other blocked/not-ready or
terminal states cannot prepare a run.

Both **Before Operation Start** and **Before Progress** input-certificate requirements are checked
at Material Run confirmation, before the run is authorized. Both are also checked at Operation
Start and again before progress. Certificate groups, minimum revisions, unexpired/active evidence
and prior-operation result rules are preserved. Only that execution's current open source draws
and permitted remaining carry-forward can prove the pre-use raw-material gate. Used, cancelled,
empty or unrelated-lane draws do not authorize new work. Final ERP settlement still uses the
shared Job Card consumption history; source material does not need to be scanned a second time.

If automatic Job Card start needs an unscanned source certificate, allocation remains Ready and
records an automatic-start deferral. Scan the sources and Confirm, then Start Operation. An
uncertified source is rejected at run confirmation, not first discovered after physical work.
No ERP stock is posted by preparation. Verify real transaction rollback, revocation/expiry between
preparation and start/progress, and scanner-only focus on the test site before acceptance.


### Unused BOM balance at Manufacture receipt

For fully tracked components with completed/submitted Job Cards and complete Material Draw
history, **Prepare Manufacture Receipt** uses recorded actual consumption. The confirmation
shows total used, already posted and still to post; those inputs are managed from the Material
Runs. Ordinary/untracked components remain in the editable actual-input table.

Example: BOM requirement 5 Kg, actual use 3 Kg, and Job Card-end ERP consumption already
submitted for 3 Kg. The remaining 2 Kg is unused, stays on its source tag and is excluded from
the Manufacture inputs. Do not scan or consume it merely to satisfy the BOM estimate. If the
3 Kg instead settles at Manufacture receipt, the receipt input and adopted trace are both 3 Kg.

Corrections belong in **Correct Material Use** before settlement, or controlled ERP recovery
for submitted entries. Incomplete tracking, mismatched/cancelled ERP evidence and unrelated
inputs retain normal validation. Required tags and certificates for actual consumption still
apply. No source-tag balance or submitted stock is rewritten by receipt preparation.

For an existing unsubmitted Manufacture Draft with this old residual, save the Draft and reopen
**Scan Material Tags** to refresh its inputs. The existing **Submit Materials** scanner action
also reconciles eligible actuals before native submission. Reconciliation retains existing valid
trace allocations and rejects a reduction below an allocation until it is cancelled properly.


### Printed expiry, Process Card cycles and optional finished Batch date

Certificate Process **Printed Expiry** and printed serial boundaries are separate from issued
certificate validity. Logistics resolves these captured values from the completed Run, submitted
Repack and exact certificate provenance, including inherited child tags. Dispatch/receipt snapshots
retain that evidence. The Manifest shows **Printed expiry** and **Printed serial boundaries
(source evidence)**. A boundary is not an invented list of ERPNext Serial Numbers for a split tag.
A certified No-Batch Item can therefore show its captured expiry without enabling Batch tracking.

Material Run FEFO includes captured printed expiry. Its effective stock expiry remains the earliest
of tag, native Batch and captured printed dates; certificate Valid Until is not substituted.
Within one **Process Card cycle**, printing dates must match across its Material Runs. A different
date is rejected before material use with suggestions for matching eligible tags in the same
warehouse, or guidance to report completed work and close the current cycle/batch through the
normal controls. A new Process Card cycle starts a new expiry group. A Work Order FEFO override does not permit
mixing printed dates in one Process Card cycle. FEFO/expired-stock rules and
native quantity/closure checks continue to apply; this warning does not automatically close ERP
Work Orders or create/split output Batches.

At **Prepare Manufacture Receipt**, **Use consumed material's printed expiry for Finished Batch**
is optional and defaults off. The finished Item must be Batch-controlled in ERPNext. Select/scan
a Finished Batch ID: a new Batch receives the single proven printed date; an existing Batch must
already have the same date. Existing Batch dates are never overwritten. Standard mode retains
normal Batch/shelf-life handling. Multiple consumed printed dates are rejected for automatic copy;
separate production batches and their source/output allocations first. Unused draws and BOM-only
quantities cannot provide finished expiry. The selection/evidence stays in the ERP Command audit
and is checked again when an opted-in Draft is submitted.

Scanner commands, available in Print Command Labels:

- CFG:CMD:RECEIPT_USE_PRINTED_EXPIRY — opt in while the receipt dialog is open.
- CFG:CMD:RECEIPT_STANDARD_EXPIRY — retain ordinary expiry handling.
- CFG:CMD:RECEIPT_BATCH — scan this label, then the Finished Batch ID.
- Confirm submits the existing receipt action; Cancel exits safely.

For a Draft Manifest selected before this metadata fix, remove and rescan the affected line to
capture the date. Frozen prepared/submitted Manifest snapshots and historical ERP postings are
not silently rewritten. No re-certification is needed when intact posted evidence already exists.
