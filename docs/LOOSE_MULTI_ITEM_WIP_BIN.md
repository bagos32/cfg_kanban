# CFG Kanban — Loose Multi-Item WIP Bin

**Status:** V1 controlled accumulation and final ERP posting implemented; live acceptance required  
**Date:** 27 October 2026  
**ERP stock authority:** submitted ERPNext Stock Entries

## Purpose

A Loose Multi-Item WIP Bin is a permanent, reusable QR container used when a workstation must
prepare or accumulate variable quantities without printing or physically splitting a source Stock
Tag. Unlike a Standard Quantity WIP Bin, it has no configured full-bin capacity and may contain
several explicitly authorized Items or Batches. It is still confined to one Company, WIP Warehouse,
Operation, Workstation, Work Order, and Job Card while active.

This mode supports repeated operation-card cycles for the same Job Card. Each cycle may scan the
same bin and record an immutable quantity contribution. CFG Kanban accumulates those contributions
and creates one native ERPNext `Material Consumption for Manufacture` at final Work Order close.

## Configuration

1. Create a **CFG Kanban Handling Unit** with:
   - **Tag Kind** = `Reusable Container`;
   - **Reusable Container Role** = `Loose Multi-Item WIP Bin`;
   - the exact **Inventory Company** and WIP **Current Warehouse**; and
   - every permitted component under **Allowed Loose WIP Items**.
2. Create a **CFG Kanban WIP Bin Pool** with:
   - **WIP Bin Mode** = `Loose Multi-Item`;
   - **Loose WIP Consumption Posting** = `Accumulate until Work Order close`;
   - one Company, Operation, WIP Warehouse, and the actual Workstation for each physical bin.
3. On the Kanban Master's BOM component row, select:
   - **WIP Presentation** = `Loose Multi-Item WIP Bin`; and
   - the matching Loose WIP Pool.
4. Keep the Master on **Transfer to WIP by Job Card**. The BOM component must have the exact Item
   Operation that owns the Job Card.

Different component rows may use different methods in one Work Order. A controlled fixed tray may
use Standard Quantity WIP, a variable component may use Loose WIP, and another component may stay
on normal ERP/tag flow.

## Mixed-mode scanner routing

Production Material Trace classifies every physical identity before placing it in a field. A
Standard Quantity WIP Bin, Loose Multi-Item WIP Bin, and ordinary source Stock Tag can therefore be
used in the same production transfer without relying on whichever ERP row happens to be selected
on screen. The match uses the physical role plus Pool, Workstation, Item authorization/capacity,
Company, Warehouse, UOM, Batch, production Cycle, and Job Card as applicable.

Use these hands-free sequences:

- Scan `CFG:CMD:RECORD_LOOSE_WIP_USE` to open the eligible Job Card's Loose WIP usage workflow.
  When several Job Cards are eligible, select the numbered operation and scan Confirm.
- Scan `CFG:CMD:PREPARE_LOOSE_WIP_CONSUMPTION` after all Job Cards are complete to open the final
  consolidated ERP consumption confirmation.
- Loose WIP with ERP-only source: `Material Quantity → Loose WIP Bin`;
- Loose WIP with a physical source: `Material Quantity → Source Stock Tag → Loose WIP Bin`;
- full Standard WIP: `Source Stock Tag when required → Standard WIP Bin` (the physical bin
  capacity supplies the quantity);
- approved partial Standard WIP: `Material Quantity → Source Stock Tag when required → Standard
  WIP Bin`; and
- optional-tag rows: scan the source tag, or scan `CFG:CMD:NO_SOURCE` before the WIP Bin.

If the WIP Bin is scanned before an optional or required source tag, the dialog holds the recognized
bin rather than misclassifying it as a source. The next source scan—or `No Source` where allowed—
continues automatically. If one physical identity validly matches several remaining rows, the scan
is held and the operator scans `CFG:SELECT:n`; CFG Kanban never guesses between ambiguous rows.

## Runtime model

```text
source Stock Tag or ERP stock
        ↓ scan source when required, then scan authorized Loose WIP Bin
Draft Material Transfer for Manufacture
        ↓ submitted ERPNext transfer confirms WIP stock
one or more immutable WIP Bin Load episodes = Ready / Accumulating
        ↓ each operation-card cycle scans bin and records actual quantity used
immutable Loose WIP Usage rows accumulate against the Job Card
        ↓ all Work Order Job Cards complete
one consolidated Material Consumption for Manufacture Draft
        ↓ ERPNext submission confirms actual consumption
unused quantity receives controlled WIP-to-source return Draft(s)
        ↓ all returns submit
bin = Empty and reusable
```

Loading does not create a child Stock Tag. The source tag quantity is reserved while the transfer
is Draft and reduced only after ERPNext submits the transfer. Every physical load remains a separate
`CFG Kanban WIP Bin Load`, even when several loads share the same permanent bin.

Usage does not directly change ERP stock. Every scan creates `CFG Kanban Loose WIP Usage`, capturing
the owner Cycle, requesting operation-card Cycle, Work Order, Job Card, Operation, Workstation,
Item, Batch, quantity, operator, session, bin, and load. An unposted mistake can be reversed with
**Undo** and a reason.

At final close, **Prepare Consolidated Loose WIP Consumption** groups all recorded contributions by
Item, Batch, UOM, and WIP Warehouse. The operator reviews and submits the one native ERP entry.
CFG Kanban then prepares a separate return Draft for every unused load balance. Manufacture receipt
remains blocked until the consumption and every required unused-material return are submitted.

## Safety boundaries

- The bin Item allow-list is mandatory. Scanning an unauthorized Item is rejected.
- Serial-controlled Items are not supported in Loose WIP; use normal tag/ERP flow.
- A Loose WIP bin cannot simultaneously cross Work Orders, Job Cards, Operations, Workstations,
  Companies, Pools, or WIP Warehouses.
- A scanned reusable bin is routed by its stored role. It cannot silently populate the source Stock
  Tag field, and an ordinary Stock Tag cannot silently populate the WIP Bin field.
- Multiple active load episodes are valid only inside the same production boundary.
- The Job Card may complete after physical use is recorded, but final Manufacture receipt cannot
  bypass consolidated ERP consumption or unused returns.
- The permanent bin QR carries no Item quantity. Live quantity comes from load and usage records;
  ERPNext submitted documents remain authoritative.
- Allowed Items, bin role, Company, Warehouse, and Pool assignment cannot be changed while active
  material or reconciliation exists.

Use `docs/TEST_LOOSE_MULTI_ITEM_WIP_BIN.md` before enabling this mode on live production.
