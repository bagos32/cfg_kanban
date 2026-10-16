# CFG Kanban — Standard Quantity Reusable WIP Bin

**Status:** Configuration foundation implemented; controlled runtime is the next delivery gate  
**Date:** 16 October 2026  
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
future scanner runtime still verifies the exact Job Card workstation.

The pool records these locked safety choices:

- require the physical bin scan;
- require full-bin consumption by default; and
- keep supervisor partial-bin exception disabled unless the process is separately approved.

### Kanban Master material row

Use **Production Material Mode = Transfer to WIP by Job Card**. On the correct BOM component row,
select **WIP Presentation = Standard Quantity Reusable WIP Bin**, choose the matching pool, and set
**Qty per Full Bin** in the component Stock UOM.

The standard quantity belongs to the Item/Operation material mapping, not to the permanent bin.
This allows the same cleaned, empty physical bin type to be used for another approved Item later
without rewriting its identity.

## 4. Intended runtime sequence

The next delivery gate will implement this controlled sequence:

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

If a source tag holds 25 kg and the full-bin standard is 10 kg, the runtime will allocate 10 kg to
one controlled WIP-bin load while the source tag retains 15 kg. The reusable bin will not become a
normal Stock Tag and no detachable printed child label will be required. The future load episode
will carry the immutable source lineage and ERP Stock Entry reference.

## 5. Required runtime safeguards

The runtime gate must not be considered complete until it enforces all of these rules:

1. Bin is Empty, active, quality released, in the selected pool, and scanned by the operator.
2. Pool Company, Operation, and WIP Warehouse match the effective Job Card, and the scanned bin's
   workstation row matches that Job Card's actual Workstation.
3. Item and Batch cannot be mixed in one bin load.
4. Planned quantity is a whole number of full bins unless an approved alternative bin profile or
   supervisor exception is used.
5. Source quantity is reserved while the ERP Stock Entry is Draft; it is not deducted early.
6. Bin becomes Ready only after the native Material Transfer for Manufacture is submitted.
7. Job Card consumption accepts only a Ready load belonging to that Job Card/operation.
8. Full-bin consumption is the normal path. A partial exception requires supervisor identity,
   reason, actual quantity, and exception audit.
9. Bin becomes Empty only after native ERP consumption is submitted or a controlled reversal is
   completed.
10. Retry/idempotency guards prevent duplicate transfer, load, consumption, or emptying events.

## 6. Current deployment boundary

This first gate creates and validates the physical roles, pools, and Master mapping. It deliberately
does not create Stock Entries, reserve source tags, create load episodes, or expose floor scanner
actions. If a Master is configured to use the WIP-bin method, Work Order creation is blocked with a
clear message and no ERP document or stock mutation occurs. Keep live Masters on **Standard ERP /
Tag Flow** until the runtime gate is deployed and accepted.
