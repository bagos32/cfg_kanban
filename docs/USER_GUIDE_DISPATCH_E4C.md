# Direct Warehouse Delivery and Customer Pickup — E4C

A prepared Customer Order Plan can now deliver directly from its selling-company Warehouse.
The operator uses the existing Delivery Session, Delivery Note and private proof tools. No lorry
claim, loading Manifest or intermediate Stock Entry is needed for these two modes.

This is a development guide. Live ERP, database-concurrency and device acceptance remain pending.

## Simple setup

Create a **CFG Kanban Dispatch Profile** with:

| Setting | Direct delivery | Customer pickup |
|---|---|---|
| Plan Type | Customer Order | Customer Order |
| Fulfilment Mode | Direct Warehouse Delivery | Customer Pickup |
| Dispatch Operations Card | Active card at the source Warehouse | Active card at the pickup Warehouse |
| Company / Source Warehouse | Same selling Company as the Customer Site; active leaf Warehouse | Same rule |
| Tag Policy | Tagged, Untagged or Mixed | Tagged, Untagged or Mixed |
| Destination / Staging / Transit Warehouses | Leave empty | Leave empty |
| Auto-submit Stock Transfer | Off | Off |
| Auto-submit Customer Delivery Note | Choose Draft review or automatic submission | Same choice |
| Delivery Proof Policy | Inherit Site or select the required policy | Attended acknowledgement is always required |
| Pickup Acknowledgement | Not used | Recipient Name, Signature, or Recipient Name and Signature |
| Dispatch Responsibility | Assign the responsible operator(s) | Same rule |

A Logistics Route and lorry are not required. Destination Assignment does not create a destination
movement in these modes. Keep an existing optional route consistent with the Profile source if one
is retained. Open Route Stock continues to use Vehicle Delivery and E4B.

Operators need the Plan's Dispatch Responsibility, **Customer Delivery** responsibility, and the
appropriate Start/Complete permissions. Supervisor exceptions retain their existing permissions.
Company comes from the scanned Plan/Site/source context, without changing the global Kanban default.
Stock owned by another Company must complete its intercompany handover first.

Pickup requirements are additive:

- **Recipient Name:** enter the person acknowledging collection.
- **Signature:** capture and save their signature with the private proof tools.
- **Recipient Name and Signature:** provide both.

Customer Site requirements for name, signature, photograph and GPS also apply. For example, a
Signature-only Profile still requires a name when the Site requires one. A No Proof Required,
Optional or Unattended Profile policy never bypasses pickup acknowledgement. Its Session uses
Required / Attended proof and records the selected pickup requirement.

The Profile revision, selected mode, posting policy and effective pickup/proof requirements are
captured when the Plan/Session is created. Changing the Profile does not alter an existing Plan.

## Operator sequence

1. Identify the operator and scan the Dispatch Operations Card.
2. Create a Customer Order Plan for the exact Customer Site, required date and stock-UOM quantities.
   An optional Sales Order supplies its outstanding quantities as in E4A.
3. Submit/approve the Plan and reserve the exact tagged and/or untagged stock.
4. When all lines are reserved, the Plan becomes **Ready for Fulfilment**.
5. Select **Start Warehouse Delivery** or **Start Customer Pickup**, or scan
   `CFG:CMD:START_WAREHOUSE_DELIVERY`. Scan the Plan and its exact Customer Site; choose a numbered
   Plan when several match, review and Confirm. Scanning the Site first also lists eligible Plans.
6. The existing prepared quantities enter a Delivery Session. They remain reserved in the same
   Warehouse. There is no quantity re-entry, substitute stock, lorry claim or stock movement.
7. Use **Confirm Customer Allocation**, then **Create Delivery Note**. Enter any mandatory ERP
   details. Draft policy waits for authorized review; only native submission consumes stock.
8. Direct delivery follows its captured proof policy. For Pickup, use **Acknowledge Pickup** after
   Delivery Note submission. Enter the required name and/or save the signature, plus Site evidence,
   then **Submit Proof and Close**.

Warehouse Plan lifecycle:

```text
Draft → approval/preparation → Ready for Fulfilment
      → Fulfilment In Progress → Fulfilled
```

A submitted Delivery Note can show **Delivered** while proof/acknowledgement is still pending.
The Plan becomes **Fulfilled / Completed** only when the Session closes. Reservation itself does
not reduce ERP stock. Source reservation audit rows become In Fulfilment, then Fulfilled on ERP
posting; their handoff release audit is not a stock disposal. The Delivery Session owns the active
hold. Operational tag reserved quantity therefore retains one hold during the handoff.

## Stock and containers

- Tagged and untagged stock may share one Plan. Untagged stock uses real ERP Item/Batch quantities,
  without creating a fake tag, certificate identity or quantity ledger.
- Batch/expiry, printed certificate expiry, Company, Warehouse, UOM and available-stock checks apply.
  Actual tagged certificate/serial identities remain on the native delivery rows.
- Each Plan line must be fully and exactly prepared. A whole Plan can fulfil part of a Sales Order,
  but every prepared allocation must fit its current eligible Sales Order row. Native order UOM,
  conversion, price and currency checks are reused.- A stand-alone non-serialized Stock Tag or single-fill posted-stock quantity bin may deliver its
  reserved portion. The remainder stays at the source; a quantity bin retains its loaded membership.
- An ordinary Logistics Container requires every current tag in full. Split/repack before preparing
  a partial aggregate delivery. Intermediate operation Hopper WIP is not ERP-posted delivery stock.

## Scanner, tablet and ERP details

Print these from **Kanban Operator → Scanner Command Labels**. Commands use the `CFG:CMD:` prefix.

| Command | Purpose |
|---|---|
| START_WAREHOUSE_DELIVERY | Open prepared Plan/Site selection for warehouse delivery or pickup |
| START_PREPARED_DELIVERY | Same prepared selector; loaded vehicle Plans also remain eligible |
| PREPARED_DELIVERY_CAMERA / PREPARED_DELIVERY_SOURCE | Camera or another Plan/Site selection |
| CONFIRM_CUSTOMER_ALLOCATION | Review and confirm the currently displayed Delivery Session |
| CREATE_CUSTOMER_DELIVERY_NOTE | Review posting policy and enter mandatory ERP inputs |
| CAPTURE_DELIVERY_PROOF / ACKNOWLEDGE_PICKUP | Open proof/pickup controls for the current Session |
| DELIVERY_RECIPIENT | Arm the name input, then scan its text |
| DELIVERY_CAMERA | Camera scanner for an input value |
| DELIVERY_ADD_ROW | Add an input row to the selected mandatory ERP table |
| DELIVERY_NEXT_ROW / DELIVERY_PREVIOUS_ROW | Enter/navigate existing table input rows |
| DELIVERY_INPUTS | Return from table columns to the main input list |
| NEXT_MATERIALS / PREVIOUS_MATERIALS | Page numbered Plans or input fields |
| CONFIRM / CANCEL | Submit the reviewed action or close safely |

`CFG:SELECT:1` through `CFG:SELECT:10` choose the displayed Plan or input field. For ERP table
inputs, select the table, Add Row, select its numbered columns and scan values; add further rows as
needed, then Confirm. Existing defaults are retained. Table totals, required fields and ERP
validation still apply. Enter/Tab scanner suffixes, normal blank Tab/Shift-Tab, touch and camera
share the same dialog controls. Photo and signature evidence use the existing tablet tools/private
media registry. Actual kiosk scanning, table-control behavior, camera and signature acceptance must
be tested on the installed site.

## Correction and retry

- An uncertain submission retains its original token/details while that dialog remains open.
  Confirm retries those details. Do not edit the displayed stock quantities to bypass uncertainty.
- Reopening prepared fulfilment resolves the Plan's existing authorized Session. Reopening proof
  resolves its existing proof record; submitted evidence is not recreated. After a refresh, inspect
  the recorded Session/Delivery Note/proof before attempting a correction.
- Before any ERP document exists, release all Delivery allocations with a reason, then cancel the
  empty Session. The Plan returns to **Approved**, with no stock hold, and must be prepared again.
  Releasing only some allocations blocks confirmation; it does not permit substitute delivery.
- Plan cancellation and source-allocation release are blocked while fulfilment owns the hold.
- Once ERP posting exists, use the controlled ERP cancellation/amendment or customer-return flow.
  A submitted proof blocks unsafe Delivery Note cancellation. Eligible partial-bin reversal retains
  one existing membership; a reused container with unrelated contents is protected.

## Migration and remaining scope

Migrate and build assets before use. The patch supplies compatibility defaults without rewriting
historical Profile snapshots or stock history. Former fully prepared warehouse Plans stuck in Ready
for Vehicle become Ready for Fulfilment only when they have no lorry, Manifest or Session.

E5 route settlement, remaining/returned/overnight stock, reassignment and post-loading recovery remain
a separate package. Invoicing, route optimization and optional E6 transit routing are also separate.
Live evidence belongs in [the E4C acceptance checklist](TEST_DISPATCH_E4C_WAREHOUSE_FULFILMENT.md).
