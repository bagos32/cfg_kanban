# Package L1 — Transfer Kanban System Test

## 1. Purpose

This procedure verifies same-company warehouse replenishment from a reusable **Transfer** Kanban
Card through the mobile-friendly **Kanban Logistics** panel. It proves that the operator does not
need to open an ERPNext Stock Entry, while ERPNext remains the stock system of record.

This package is deliberately separate from:

- purchase replenishment from a Supplier;
- manufacturing/Work Order replenishment;
- intercompany handover using Delivery Note and Purchase Receipt;
- customer delivery; and
- same-Warehouse repacking, splitting, or retagging.

## 2. Test data

Use a dedicated non-production Item and quantities so that the expected result is unambiguous.

| Record | Sample value | Requirement |
|---|---|---|
| Company | `FZD Manufacturing Test` | One Company for the entire test |
| Item | `KAN-TRANSFER-TEST` | Stock Item, Stock UOM `Nos`, no Serial Number |
| Source Warehouse | `Raw Store - FZDT` | Belongs to the test Company |
| Destination Warehouse | `Production Store - FZDT` | Belongs to the same Company |
| Transit Warehouse | `Internal Transit - FZDT` | Only for Goods in Transit; Warehouse Type must be `Transit` |
| Opening source balance | `100 Nos` | Submitted ERPNext stock balance |
| Card quantity | `20 Nos` | Quantity represented by one Transfer Card |
| Card number | `MOVE-RAW-20` | Unique visible scan value |

Record the source and destination Bin quantities before every test. Do not reuse a Cycle or
Movement Manifest from a previous test.

## 3. Authorization prerequisites

1. Create or reuse the **Internal Warehouse Transfer** Kanban Responsibility.
2. Give the test operator a valid **CFG Kanban Operator Profile** with:
   - permission to start and complete work;
   - Internal Warehouse Transfer responsibility; and
   - the source/destination Workstation or operation restrictions required by the local policy.
3. Give the supervisor approval/override authority when the Master uses Approval automation.
4. Start an operator session in **Kanban Logistics** and verify the operator name is visible.

Expected result: unauthorized operators cannot prepare, dispatch, receive, or cancel this movement.

## 4. Create the Direct Transfer configuration

### 4.1 Logistics Route

Create **CFG Kanban Logistics Route** with these exact fields:

| Field | Value |
|---|---|
| Active | Yes |
| Route Type | Internal Warehouse Transfer |
| Source Company | Test Company |
| Source Warehouse | Raw Store |
| Destination Company | Same Test Company |
| Destination Warehouse | Production Store |
| Internal Transfer Posting Mode | Direct Transfer |
| Dispatch Responsibility | Internal Warehouse Transfer |
| Receipt Responsibility | Internal Warehouse Transfer |
| Submit Internal Dispatch on Operator Confirmation | Enable for automatic test; disable for draft test |

Do not enter an Internal Customer, Internal Supplier, selling Price List, or buying Price List.
Those are intercompany fields and must not be required by this route.

### 4.2 Material Trace Policy

Create or update **CFG Kanban Material Trace Policy** for the test Company and Item:

| Field | First test value |
|---|---|
| Enabled | Yes |
| Warehouse Transfer Tags | No Physical Tag |

### 4.3 Kanban Master and Card

Create **CFG Kanban Master**:

| Field | Value |
|---|---|
| Control Type | Transfer |
| Company | Test Company |
| Item | `KAN-TRANSFER-TEST` |
| Replenishment Qty (Stock UOM) | `20` |
| Source Warehouse | Raw Store |
| Destination Warehouse | Production Store |
| Internal Logistics Route | Direct Transfer route above |
| Automation Level | Approval for the first test |

Create an active **CFG Kanban Card** for this Master with Card Number `MOVE-RAW-20`.

Open the saved Card and verify **Print Card with QR** is visible. Printing must retain the current QR
identity, increment Print Count, and label the output **STOCK TRANSFER**. **Replace Card Identity** is
an exception action for a lost/damaged identity; it is not required for ordinary printing.

Expected result: the Master refuses a route whose Company, Warehouses, or Route Type do not match,
and the Card can be printed without replacing its identity.

## 5. Direct Transfer without physical tags

1. Open **Kanban Logistics**.
2. Scan or type `MOVE-RAW-20` and select **Find**.
3. Verify the result explicitly says **Transfer Card**, shows the Item, `20 Nos`, source Warehouse,
   destination Warehouse, and route.
4. Select **Trigger Transfer**.
5. If Approval is configured, approve the Signal in the Supervisor panel, then return to Logistics
   and scan the Card again.
6. Open the linked Movement Manifest.
7. Verify it has one line labelled **ERP Stock without Physical Tag** for exactly `20 Nos`.
8. Select **Prepare Manifest**.
9. Verify the system checks the ERP source balance and changes the Manifest/Cycle to Prepared.
10. Select **Confirm Dispatch** and satisfy any genuine ERPNext mandatory input displayed by the
    controlled dialog.

Expected automatic-submit result:

- a submitted ERPNext **Material Transfer** Stock Entry exists;
- source Bin decreases by `20 Nos` and destination Bin increases by `20 Nos`;
- Manifest is Received;
- Cycle and Signal are Completed;
- Card returns to Available and has no Active Cycle; and
- no Handling Unit quantity event is fabricated because this test uses untagged ERP stock.

Expected draft-mode result when auto-submit is disabled:

- the Stock Entry is Draft;
- Manifest and Cycle say **Dispatch Document Pending**;
- Card does not recycle and no stock balance changes;
- after an authorized ERP user submits that same Stock Entry, the feedback hook completes the
  Manifest/Cycle/Card exactly once.

## 6. Direct Transfer with physical tags

1. Set **Warehouse Transfer Tags** to `Required Physical Tag`.
2. Ensure an active Stock Tag for the same Company, Item, source Warehouse and quantity is available.
3. Trigger a fresh Transfer Card Cycle.
4. Scan tag(s) into the linked Manifest until the combined quantity is exactly `20 Nos`.
5. Prepare and dispatch.

Expected result:

- an over-quantity, wrong Item, wrong Company, or wrong source-Warehouse tag is rejected;
- preparation is blocked until tagged quantity equals the Card quantity;
- the submitted ERP Stock Entry remains authoritative;
- tag quantity is not consumed; its location moves from source to destination; and
- the quantity ledger and genealogy show the Manifest and submitted Stock Entry.

Repeat with **Optional Physical Tag**. Verify the operator can either scan valid tags or deliberately
select **Use ERP Stock Without Tags**. The choice must be visible on the Manifest line.

## 7. Goods in Transit test

1. Create a second Internal Warehouse Transfer route using the same endpoints.
2. Set **Internal Transfer Posting Mode** to `Goods in Transit`.
3. Select the Transit Warehouse and enable both internal auto-submit options.
4. Point the Master to this route and trigger a fresh Cycle.
5. Prepare and confirm dispatch.

Expected outbound result:

- a submitted outgoing ERPNext Stock Entry exists;
- stock moves from source to the Transit Warehouse;
- Manifest is Awaiting Receipt;
- Cycle/Card show In Transit; and
- tagged stock, when used, has Internal Transit movement state.

6. At destination, open the same Manifest. Scan every listed physical tag, when present, and select
   **Confirm Receipt**. Untagged ERP Stock lines require no fake tag scan.

Expected receipt result:

- the incoming Stock Entry is linked to the submitted outgoing Stock Entry using ERPNext's native
  Goods-in-Transit relationship;
- stock moves from Transit Warehouse to destination;
- Manifest, Cycle, Signal, and Card complete only after the submitted receipt Stock Entry; and
- duplicate confirmation does not create a second Stock Entry.

## 8. Required negative tests

| Test | Expected rejection/result |
|---|---|
| Transfer Master without Internal Logistics Route | Save/release is blocked |
| Internal route uses two different Companies | Route validation blocks it |
| Direct route has a Transit Warehouse | Irrelevant transit data is not used |
| GIT route Warehouse Type is not Transit | Route validation blocks it |
| Insufficient ERP source stock | Manifest preparation is blocked |
| Manifest Item differs from Cycle Item | Preparation is blocked |
| Manifest total differs from Card quantity | Preparation is blocked |
| Physical tags required but none scanned | Preparation is blocked |
| Untagged mode used for batch/serial-controlled Item | Preparation is blocked; use exact physical tags or the manual ERP fallback |
| Operator lacks route responsibility | Action is blocked |
| Re-scan/retry with same event | No duplicate Cycle, Manifest, line, or ERP document |
| Cancel Draft/Prepared Manifest before ERP document | Manifest/Signal/Cycle roll back; Card becomes usable |
| Cancel after submitted Stock Entry | Destructive cancel is blocked; controlled ERP recovery is required |
| Scan Transfer Card while another Cycle is active | Existing Cycle/Manifest is shown; a duplicate is not created |

## 9. Regression tests

After Package L1 passes, perform these short checks:

1. An **Intercompany Handover** route still requires different Companies and uses Delivery Note /
   Purchase Receipt, not Stock Entry.
2. A Customer Delivery Session still uses the Company-specific vehicle Warehouse and Delivery Note.
3. A Purchase Replenishment Card still creates its purchase Signal/Material Request path.
4. A Production Card still creates or binds its Work Order/Job Cards.
5. A Withdrawal Master is explicitly rejected until its separate controlled withdrawal workflow is
   implemented; it must never create a Work Order accidentally.

## 10. Tester evidence

For each test retain:

- screenshots of Card, Signal, Cycle, and Manifest states;
- ERP Stock Entry number(s) and docstatus;
- before/after ERP Bin quantities;
- scanned tag codes and genealogy/ledger evidence when tags are used;
- Exception number and exact message for negative tests; and
- confirmation that a repeated scan/confirmation created no duplicate document.

The package passes only when the Kanban state agrees with submitted ERPNext stock documents. A
green Kanban state without a submitted native stock document is a failure.
