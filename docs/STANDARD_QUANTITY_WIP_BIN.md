# CFG Kanban — Standard Quantity Reusable WIP Bin

**Status:** Full lifecycle, closure guard, supervisor control report, partial-bin exception, and transfer/consumption cancellation reconciliation implemented; server acceptance required
**Date:** 18 October 2026
**ERP stock authority:** ERPNext Work Order, Job Card, and submitted Stock Entry

## 1. Purpose

A Standard Quantity Reusable WIP Bin is a permanent, scannable bin or tray whose physical full
condition proves a predefined quantity at a workstation. It is appropriate only when the bin
itself provides a reliable visual poka-yoke: for example, one moulding tray always holds 10 units.

It is not an unrestricted loose-material bin and is not a replacement for ERPNext stock.

## 2. Locked identity model

The permanent QR identifies the physical bin. It does not permanently identify an Item, Batch, or
quantity. Those belong to one future controlled load episode. A bin may carry different Items only
sequentially: it must be Empty and cleared before another Item or Batch is loaded.

The existing reusable logistics container remains unchanged. It holds complete active Stock Tags
and may support configured mixed content. A Standard Quantity WIP Bin is a separate reusable role,
cannot allow mixed content, and belongs to one WIP Bin Pool.

## 3. Configuration records

### Physical bin

Create **CFG Kanban Handling Unit**:

| Field | Required value |
|---|---|
| Tag Kind | Reusable Container |
| Reusable Container Role | Standard Quantity WIP Bin |
| Inventory Company | Company owning the WIP stock |
| Current Warehouse | Exact ERPNext WIP Warehouse |
| Allow Mixed Item / Batch Content | Disabled |

### WIP Bin Pool

Create one **CFG Kanban WIP Bin Pool** for an exact Company, Operation, and WIP Warehouse. Add one
or more approved physical WIP bins and map every bin to its actual Workstation. A bin cannot belong
to another pool. Multiple workstation rows allow the same Operation to run in parallel while the
scanner runtime verifies the exact Job Card workstation.

The pool records these locked safety choices:

- require the physical bin scan;
- require full-bin consumption by default; and
- keep supervisor partial-bin exception disabled unless the process is separately approved. When
  enabled, only an active Kanban Supervisor QR profile with Override permission can authorize it.

### Kanban Master material row

Use **Production Material Mode = Transfer to WIP by Job Card**. On the correct BOM component row,
select **WIP Presentation = Standard Quantity Reusable WIP Bin**, choose the matching pool, and set
**Qty per Full Bin** in the component Stock UOM.

The standard quantity belongs to the Item/Operation material mapping, not to the permanent bin.
This allows the same cleaned, empty physical bin type to be used for another approved Item later
without rewriting its identity.

### WIP Bin Load episode

**CFG Kanban WIP Bin Load** is system-created and read-only to floor and Desk users. One record
represents one physical fill/use episode. It snapshots the Item, Batch, standard and actual
quantity, Cycle, Work Order, Job Card, Operation, Workstation, source, WIP Warehouse, operator
session, and the native ERPNext Stock Entry rows.

Only one active load may occupy a physical WIP bin. A Draft ERP transfer may reserve the bin, but
cannot make its load Ready. Submitted ERP feedback changes it to Ready. Submitted consumption
changes it to Consumed and releases the permanent bin to Empty. ERP cancellation creates a visible
Reversed/Exception condition and a dedicated reconciliation record rather than deleting history.

Different material rows in the same BOM/Work Order may use different methods. The reusable-bin
runtime applies only to rows explicitly configured as `Standard Quantity Reusable WIP Bin`; all
other rows continue through normal ERP quantity or physical-tag flow.

## 4. Runtime sequence

The controlled sequence is:

```text
source Stock Tag or ERP quantity
        ↓ operator scans source and empty fixed bin
Draft Material Transfer for Manufacture (Job Card scope)
        ↓ ERPNext submission confirms the warehouse movement
bin load = Ready at WIP (exact Item, Batch, quantity, Job Card)
        ↓ operation scans the same bin
full load consumed against the matching Job Card
        ↓ ERPNext submission confirms consumption
bin = Empty and available for cleaning/refill
```

The transfer-allocation part of this sequence is implemented in **Production Material Trace**.
The operator selects the WIP material row (or scans its displayed row number), scans the source
Stock Tag when the Item policy uses one, and then scans the Empty reusable WIP bin. For an optional
tag policy, `CFG:CMD:NO_SOURCE` explicitly selects ERP-only source stock. A Draft allocation may be
cancelled without deleting its audit record.

If a source tag holds 25 kg and the full-bin standard is 10 kg, the runtime allocates 10 kg to
one controlled WIP-bin load while the source tag retains 15 kg. The reusable bin will not become a
normal Stock Tag and no detachable printed child label is required. The load episode carries the
immutable source lineage and ERP Stock Entry reference. Draft allocation reserves 10 kg; only
submitted ERPNext transfer feedback removes it from the source tag and marks the bin Ready.

After transfer submission, the exact Job Card shows **Consume Ready WIP Bins**. This creates one
Draft `Material Consumption for Manufacture` from the Ready load snapshots. In Production Material
Trace the operator scans each physical Ready bin. A mistaken Draft scan can be cancelled back to
Ready. Only native ERPNext submission changes the linked load to Consumed and the permanent bin to
Empty. Report Progress still saves the ERPNext Job Card completed quantity while consumption is
pending. ERPNext requires the operation Job Card to complete before it accepts the matching
production consumption, so Job Card submission is allowed when loads are `Ready`, `In Use`, or
`Consumption Draft`. Only a `Transfer Draft` load or Open reconciliation blocks Job Card
submission. Kanban Cycle closure and Manufacture receipt retain the stricter rule and remain
blocked until every load is `Consumed`.

The final Manufacture draft must be created only after this consumption is submitted. The
Operator panel treats any `Ready`, `In Use`, `Consumption Draft`, or unsubmitted `Transfer Draft`
load as a receipt prerequisite and keeps **Prepare Manufacture Receipt** unavailable. This prevents
ERPNext from mapping still-unconsumed WIP material into a premature Manufacture draft and making
it appear that the bin allocation was lost.

For a draft created by an older release before this gate existed, use **Discard Premature Draft**
on that Draft Manufacture row. This controlled action is allowed only while an active WIP-bin load
still blocks the receipt, only when no Material Trace has already been staged, and always requires
a reason. It cancels the originating ERP command reference and records the discard in the Kanban
timeline. It does not delete or reallocate the WIP-bin load. Then use **Consume Ready WIP Bins** on
the Job Card that owns the load, scan the physical Ready bin in Production Material Trace, submit
the Material Consumption entry, and prepare a fresh Manufacture receipt.

## 5. Runtime safeguards

The runtime gate must not be considered complete until it enforces all of these rules:

1. Bin is Empty, active, quality released, in the selected pool, and scanned by the operator.
2. Pool Company, Operation, and WIP Warehouse match the effective Job Card, and the scanned bin's
   workstation row matches that Job Card's actual Workstation.
3. Item and Batch cannot be mixed in one bin load.
4. Planned quantity is a whole number of full bins unless the Pool explicitly permits a supervisor
   partial-bin exception. The exception quantity must be positive, below the standard capacity,
   and within the remaining native ERP row. The supervisor reason, Employee identity, terminal
   User, session, and approval time are immutable audit evidence.
5. Source quantity is reserved while the ERP Stock Entry is Draft; it is not deducted early.
6. Bin becomes Ready only after the native Material Transfer for Manufacture is submitted.
7. Job Card consumption accepts only a Ready load belonging to that Job Card/operation.
8. A partial load is created only during transfer by a Supervisor with Override permission. Later
   Job Card consumption scans and consumes that load's exact approved actual quantity; it cannot
   silently revert to the standard full-bin quantity.
9. Bin becomes Empty only after native ERP consumption is submitted or a controlled reversal is
   completed.
10. Retry/idempotency guards prevent duplicate transfer, load, consumption, or emptying events.
11. Cancelling a submitted transfer or consumption creates a Critical Exception and blocks the
    physical bin. Only a scanned Supervisor with Override permission may resolve it. For a
    cancelled consumption, the Supervisor either:
    verifies that ERPNext's returned quantity is physically restored to the same bin, creating a
    new linked Ready load; or verifies the bin is Empty only after linking a submitted ERPNext
    correction that removes the exact Item/Batch/UOM/quantity from WIP.
12. A cancelled submitted transfer never claims the physical bin is Empty automatically. Any
    restored source-tag quantity is reserved against reuse while the outcome is unknown. The
    Supervisor either verifies the material returned to the original source (and rescans that
    source tag when one was used), or links an exact later submitted transfer from Source to WIP
    before recovering a new Ready load for material that physically remained in the bin.
13. A reusable operation Card cannot close and return to Available while its Job Card has an
    active WIP-bin load or Open WIP-bin reconciliation. This guard is enforced by the server for
    both the panel button and `CFG:CMD:CLOSE_CYCLE`; hiding or bypassing the button cannot release
    the Card. The operator must submit/cancel the Draft material movement, consume every Ready
    bin, or complete the Supervisor reconciliation first.

## 6. Supervisor WIP Bin Control

Open **CFG Kanban > Production Supervisor > WIP Bin Control** to see the current physical and
runtime state of every Standard Quantity WIP Bin. The report starts from permanent Handling Units,
so it includes available Empty bins as well as bins with an active load.

The report shows Company, Pool, Operation, Workstation, WIP Warehouse, physical bin state, active
load status, Item, Batch, quantity, Job Card, Work Order, Cycle, age, and any Open reconciliation.
Use **Attention Only** to isolate configuration gaps, state/load mismatches, Draft movements,
duplicate active loads, changed Pool/Workstation context, Ready bins awaiting consumption, and
Exceptions. **Include Disabled / Held Bins** is intended for
supervisor investigation and also exposes disabled assignments or unavailable identities.

This report is read-only. It does not move stock, change a bin state, submit ERPNext documents, or
resolve an Exception. ERPNext Stock Entries and the controlled WIP-bin lifecycle remain the
authorities; the linked load/reconciliation records must be opened to complete the appropriate
action.

## 7. Current deployment boundary

The package now includes physical roles, pools, Master mapping, immutable load episodes, Draft
transfer allocation, Ready-bin Job Card consumption, native ERP feedback, Draft cancellation, and
completion guards. It also includes immutable `CFG Kanban WIP Bin Reconciliation` records,
Critical Exception visibility, exact-bin rescanning, source-tag safety holds, and controlled
Ready/Empty recovery after a submitted transfer or consumption cancellation. The source tag may be partially reserved for one exact
full-bin quantity; rows
configured without physical tags remain ERP-only. Work Order creation is no longer blanket-stopped.
Runtime operation-card closure also checks the Job Card's complete physical-bin scope before it
releases the reusable Card, including Open cancellation reconciliations.

Do not enable the method on a live Master until the development-server procedure in
`docs/TEST_STANDARD_QUANTITY_WIP_BIN_TRANSFER_GATE.md` passes. Keep partial exceptions disabled
unless the physical verification method and supervisor responsibility are approved. Serial-
controlled components remain on Standard ERP / Tag Flow because a fixed quantity alone is not
sufficient evidence of exact serial membership.

## 8. Deferred V2 enhancements

The V1 lifecycle is intentionally complete without automatic ageing escalation or analytics. When
V2 development starts, review `docs/V2_DEFERRED_ENHANCEMENTS.md` before fixing its scope. The WIP
items that must not be skipped are state-age/andon thresholds, meaningful supervisor escalation,
bin utilization/turnover/waiting/capacity analysis, and optional controlled cleaning/inspection
readiness. These enhancements must remain evidence and control layers; they cannot replace
ERPNext stock authority or silently change a physical-bin state.
