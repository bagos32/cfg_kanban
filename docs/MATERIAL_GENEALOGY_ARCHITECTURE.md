# CFG Kanban Material Genealogy Architecture

**Status:** Approved additive V1 architecture; mixed-trace policy, submitted Purchase Receipt tag
activation, and Stock Entry-confirmed production input/output tracing are implemented. A floor-panel
scan workflow, broader Warehouse movement assistant, and the trace explorer remain subsequent
increments.

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

## 4. Stock Entry-confirmed production genealogy

Saved Draft Stock Entries with Purpose **Manufacture**, **Repack**, **Material Transfer for
Manufacture**, or **Material Consumption for Manufacture** expose **CFG Kanban → Production
Material Trace**.

The workflow is:

1. ERP-only rows remain visible and require no scan.
2. For tag-enabled source rows, scan one or more active Handling Units and reserve the exact stock
   quantity against the Draft Stock Entry.
3. For tag-enabled finished/repacked target rows, scan unused preprinted main tags and stage their
   quantities. No Handling Unit or output balance is created while the ERP document is Draft.
   If the ERP draft will not be used, **Discard Entire Draft Trace** releases all reservations,
   cancels pending output identities, and retains an Abandoned trace record before the draft is
   deleted.
4. An explicit Required policy blocks submission until its ERP row quantity is completely covered.
   Optional policies allow partial tagged quantity; No Physical Tag never gates submission.
5. ERPNext submission confirms the trace. Direct-consumption inputs are deducted, material-transfer
   tags move to the ERP target Warehouse, and output tags are activated in the ERP target Warehouse.
6. Cancelling a submitted Stock Entry reverses untouched trace balances. Cancellation is refused if
   a produced tag has subsequently moved, split, reduced, or been reserved.

Material Transfer for Manufacture and later consumption remain separate ERP confirmations. The same
raw-material tag is scanned again from its WIP Warehouse when the Manufacture or Material
Consumption entry consumes it. This keeps both WIP-transfer-enabled and skip-transfer workflows
auditable without inventing stock movement outside ERPNext.

ERPNext v15 direct Batch fields and single-Batch Serial and Batch Bundles are supported. A row that
contains multiple Batches must be split by Batch before assigning a physical Handling Unit because
one tag cannot represent multiple lots.

### Subsequent increments

The next increments add:

1. scanner-first production-panel access to the Stock Entry trace workflow;
2. a guided general same-company tagged Warehouse-transfer assistant;
3. scan-any-tag upstream/downstream genealogy exploration and printable trace reports;
4. container-content genealogy for mixed reusable containers;
5. richer serial-number evidence where one physical unit requires individual serial association.

Job Cards provide operator/operation context, but raw-material stock consumption remains linked to
the Work Order and submitted Stock Entry details.

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
