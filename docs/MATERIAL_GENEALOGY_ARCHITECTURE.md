# CFG Kanban Material Genealogy Architecture

**Status:** Approved additive V1 architecture; mixed-trace policy, submitted Purchase Receipt tag
activation, Stock Entry-confirmed production input/output tracing, scoped floor-panel access to
those production traces, a same-company tagged Warehouse-transfer assistant, and the read-only
upstream/downstream trace explorer with printable exact-tag reports, and time-bounded reusable-
container content episodes, and ERP-referenced exact Serial Number membership are implemented.

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

### Floor operator access

After scanning a production Kanban Card, the Operator panel lists supported Stock Entries belonging
to the Card's active Cycle Work Order. An authorized operator can open a Draft entry's material
trace, scan input Handling Units, stage preprinted output tags, and cancel individual Draft trace
lines. The floor route cannot submit the Stock Entry and cannot access an unrelated Work Order,
Company, Cycle, or Card. Fixed scanners submit a focused tag field with their Enter suffix; mobile
operators can use the input/output camera buttons. A zero input quantity means allocate the scanned
tag's available quantity up to the remaining ERP input-row quantity.

### Same-company Warehouse transfer

An ERPNext Stock Entry with exact Purpose **Material Transfer** is also trace-enabled. A Stock or
Manufacturing user prepares and saves the Draft entry with Company, source Warehouse, destination
Warehouse, Items, Batches, and quantities. An operator assigned to **Internal Warehouse Transfer**
opens the Logistics panel and scans active Handling Units against that Draft. No Physical Tag rows
remain ordinary ERP stock and need no scan.

A physical tag must move in full because one tag cannot be located in two Warehouses. For a partial
physical movement, activate an appropriate detachable child tag first. Scanning reserves the tagged
quantity; ERPNext submission confirms the stock movement and changes the Handling Unit's current
Warehouse. Cancelling an untouched submitted transfer returns the tag to the source Warehouse.
Operators cannot submit the Stock Entry through this assistant.

### Scan-any-tag genealogy exploration

The Desk **Material Genealogy Explorer** resolves the same preprinted visible code used on the
floor. An activated Handling Unit becomes the focus and the service walks confirmed or reversed
production trace relationships, parent/child and replacement lineage, and immutable ledger
source/destination relationships in both directions. It displays current stock identity, upstream
materials, downstream products, ERP references, Movement Manifest history, and chronological
quantity/location evidence. Selecting a related tag continues the investigation from that tag.

The explorer is strictly read-only and requires Handling Unit read permission. It limits one graph
to 100 Handling Units and 20 generations, reports truncation explicitly, and does not convert
ERP-only or Batch-pool evidence into exact physical-unit evidence. The standard **CFG Kanban
Genealogy Report** prints the same lineage and states **Exact Handling Unit** as its evidence level.

### Reusable-container contents

A permanent **Reusable Container** tag can group several complete Stock Tags without pretending
that unlike Items or UOMs form one scalar stock balance. In the Logistics panel, scan the container
in normal lookup mode and select **Manage Contents**. Scan each complete Stock Tag to load it. To
remove one, select **Unload** and record the reason.

Each load creates an immutable **CFG Kanban Container Content** episode containing the container,
Stock Tag, Item, Batch, quantity, Company, Warehouse, operator, session, and time. Unloading closes
that episode rather than deleting it. When **Allow Mixed Item / Batch Content** is disabled, every
simultaneously loaded tag must have the same Item and Batch. The first loaded tag assigns a blank
container's Company and Warehouse; later tags must match both.

Container loading is physical grouping only: it does not post an ERPNext stock movement or change
the Stock Tag balance. A loaded Stock Tag must be unloaded before it can be consumed, transferred,
dispatched, received, replaced, or voided independently. A nonempty container cannot be replaced,
voided, or moved through the generic lifecycle scan. Container episodes appear separately in the
Genealogy Explorer so reuse over time does not create false upstream/downstream product lineage.

A complete loaded reusable container can move through an intercompany **Movement Manifest**. One
dispatch scan expands the current membership into one Manifest line per contained Stock Tag. The
Delivery Note and Purchase Receipt therefore retain the actual Item, Batch, UOM, quantity, and tag
identity; the container never becomes a synthetic stock row. Preparation verifies that the
membership has not changed, then reservations prevent load/unload changes. One destination scan of
the same container confirms all still-contained Manifest tags. Submitted ERPNext feedback moves
each Stock Tag and updates the permanent container's custody location. Cancellation feedback keeps
the container aligned with the same source/transit recovery state as its contents.

### Exact serial-number membership

For an ERPNext Item with **Has Serial No**, a physical Stock Tag must identify each exact Serial No,
not merely a quantity. Purchase Receipt activation and production-output staging read the Serial
Numbers from the ERP row or its Serial and Batch Bundle. If one tag takes every remaining serial,
the UI fills them automatically; otherwise the user selects/scans exactly the serial count matching
the tag quantity.

**CFG Kanban Handling Unit Serial** stores an immutable, ERP-referenced membership episode. Only
one active Stock Tag may claim a Serial No. Production input validation requires the tag's complete
serial membership to match the ERP Stock Entry row and blocks partial consumption of a multi-serial
tag. Submitted consumption releases the membership; ERP cancellation reactivates it. Warehouse and
intercompany movements retain membership, while controlled tag replacement transfers it to the
replacement identity. Output cancellation releases the serials and voids the produced tag.

Cancelling a Purchase Receipt voids its untouched received tags and releases their serial
memberships in the same transaction. Cancellation is blocked if any affected tag has already
moved, split, entered a reusable container, been reserved, or been consumed.

Serial membership is physical evidence, not serial ownership or stock accounting. ERPNext Serial
No, Serial and Batch Bundle, and submitted stock documents remain authoritative. Generic child-tag
splitting is deliberately blocked for a serial-controlled parent because serials must be explicitly
selected. **Split Exact Serials to Child Tag** moves the selected whole-number serial subset and the
same quantity to one unused detachable child identity without posting ERP stock. The immutable
membership history and quantity ledger record both sides of the split.

An untouched, unreserved child in the same Company and Warehouse may be returned using **Merge
Untouched Child Back to Parent**. The merge restores the exact serials and quantity to the parent,
marks the used child identity Empty, and never makes its printed code reusable. Any later movement,
reservation, container loading, consumption, replacement, or other quantity activity blocks the
merge and requires normal reconciliation.

### Subsequent increments

The next logistics increment extends the same container-preserving principle to vehicle/customer
delivery without weakening Delivery Note and customer-site controls.

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
