# CFG Kanban Material Genealogy Architecture

**Status:** Approved additive V1 architecture; mixed-trace policy and submitted Purchase Receipt
tag activation are implemented. Production allocation, transformation genealogy, output binding,
same-company transfer, and the trace explorer remain subsequent increments.

## 1. System boundary

ERPNext remains the stock system of record. A Kanban scan may prepare, reserve, or explain a
physical movement, but only a submitted ERPNext document confirms receipt, consumption,
manufacture, or Warehouse movement.

Four identities remain separate:

- Kanban Card: reusable demand or process-control identity.
- ERPNext document: authoritative stock/accounting transaction.
- Handling Unit Tag: physical material/container identity.
- Material genealogy: input-to-output relationship confirmed by ERP transactions.

## 2. Mixed tagged and untagged stock

Physical tags are not universally required. **CFG Kanban Material Trace Policy** is optional and
scoped by Item and Company. When no enabled policy exists, all three stages default to **No Physical
Tag** and normal ERPNext Warehouse, Batch, Work Order, Job Card, Stock Entry, and virtual Kanban WIP
behavior continues unchanged.

Each policy independently controls:

- Purchase Receiving Tags;
- Production Input Tags;
- Production Output Tags.

Each stage supports **No Physical Tag**, **Optional Physical Tag**, or **Required Physical Tag**.
Trace Level supports **ERP Document Only**, **Batch Pool**, or **Exact Handling Unit**. An exact
Handling Unit policy must enable optional or required physical tags at one or more stages.

This permits, for example:

- rubber bands: ERP Stock Only at every stage;
- bulk sugar: Batch Pool, optional receiving tags, no per-operation input tag;
- regulated flavour: exact receiving and production-input tags;
- finished cartons: exact production-output tags but no tagged raw materials.

## 3. Receiving-tag vertical slice

A submitted Purchase Receipt exposes **CFG Kanban > Tag Received Material**. The dialog shows every
receipt row, including ERP-only rows, and permits activation only for rows whose explicit policy is
Optional or Required Physical Tag.

Normal flow:

1. Submit the Purchase Receipt in ERPNext.
2. Open **Tag Received Material**.
3. Select a tag-enabled receipt row.
4. Scan an unused preprinted main tag covered by an active Tag Family or Tag Range Registry.
5. Enter the physical-container quantity in Stock UOM and select its Handling Unit Type.
6. Activate additional tags until the confirmed row quantity is covered.

The server derives Item, Stock UOM, Batch, Company, Warehouse, Supplier, and expiry snapshot from
the submitted receipt. It rejects over-allocation, unregistered tags, child tags without an active
parent, wrong/used tags, missing mandatory Batch, returns, draft receipts, and duplicate activation.
One receipt row may be divided across several tags only when **Allow Receipt Quantity Across
Multiple Tags** is enabled.

Every activated Handling Unit retains immutable generic ERP origin fields and its activation ledger
references the submitted Purchase Receipt. Retrying the same receipt-row/tag combination returns
the existing Handling Unit rather than duplicating quantity.

**Required Physical Tag** currently exposes the untagged confirmed balance but does not block the
native Purchase Receipt submission. A future pre-submission/pending-tag increment will enforce that
requirement without making tag scanning mandatory for ERP-only Items.

## 4. Planned production genealogy

The next increments add:

1. raw-material Handling Unit allocation to Work Order and Stock Entry rows;
2. support for WIP-transfer-enabled and direct-consumption Work Orders;
3. a many-input/many-output Material Trace Transaction;
4. pending preprinted output-tag binding confirmed by submitted Manufacture/Repack Stock Entries;
5. stocked semi-finished tags while keeping non-stock WIP in the existing Cycle/WIP Ledger;
6. same-company tagged Warehouse transfers;
7. scan-any-tag upstream/downstream trace exploration.

Job Cards may provide the operator/operation context, but raw-material stock consumption remains
linked to the Work Order and submitted Stock Entry details.

## 5. Tag lifetime

- Main and Child Stock Tags are one-time material identities and are not reused for a new lot after
  becoming Empty.
- Reusable Container tags are permanent container/location identities and receive controlled refill
  episodes.
- Kanban Cards are reusable demand/process identities and never substitute for stock tags.

## 6. Required invariants

1. No physical scan independently changes ERP stock.
2. Activated tag quantity cannot exceed confirmed ERP receipt/output quantity.
3. One physical tag cannot represent stock in two Companies or Warehouses simultaneously.
4. Duplicate scans and retries are idempotent.
5. Transformation input must reconcile to outputs, remaining quantity, scrap, and approved loss.
6. ERP cancellation creates reversal, blocked, or reconciliation states; it never deletes lineage.
7. Trace reports state whether evidence is exact Handling Unit, Batch Pool, or ERP Document Only.

