# CFG Kanban Acceptance Test — Skip-WIP Job Card Material Consumption

**Purpose:** prove that actual material usage can be recorded at the responsible Job Card without a
WIP transfer, including partial use of a larger tagged bundle. ERPNext remains the stock system of
record; Kanban adds scanner control and genealogy.

**Test only on the development site.** Use disposable quantities and do not mix this test with an
existing live Work Order.

## 1. Test data

Use one submitted BOM with two operations and at least these components:

| Component | Item Operation | Test tag policy | Example required quantity |
|---|---|---|---:|
| Ingredient A | Cooking | Required Physical Tag | 10 |
| Ingredient B | Moulding | No Physical Tag | 5 |

Prepare an active Handling Unit for Ingredient A in its configured source Warehouse with quantity
`25`. This intentionally exceeds the operation requirement of `10` so the remaining-tag test is
meaningful.

The BOM must have **With Operations** enabled and each operation-controlled BOM Item must have its
exact **Item Operation**. ERPNext must create Job Cards for Cooking and Moulding.

## 2. Kanban Master

Create or copy a Production Master with:

- **Production Material Mode:** `Skip WIP Transfer`
- ERPNext BOM / Work Order **Transfer Material Against:** `Job Card`
- per-component Source Warehouses loaded under **BOM Component Material Flow**
- **Manufacture Receipt Posting:** `Create Draft for Tag / Batch Review`
- Operation Profiles for Cooking and Moulding

Expected validation: a BOM component without Item Operation is rejected when the resulting Work
Order controls materials by Job Card.

## 3. Release production

1. Activate the production Kanban Card.
2. Approve/release the Signal when the Master uses Approval.
3. Confirm that ERPNext creates and submits one Work Order and creates both Job Cards.
4. Scan the production Card in **Kanban Operator**.

Expected:

- **Material mode** is `Skip WIP Transfer`.
- No Material Transfer for Manufacture exists.
- Cooking shows Ingredient A under **Consume Operation Materials**.
- Moulding shows Ingredient B under **Consume Operation Materials**.
- Job Card start is not blocked by a WIP-transfer prerequisite.

## 4. Create Cooking consumption using only scanner commands

1. Start the Cooking operation when its gate is Ready.
2. Scan `CFG:CMD:PREPARE_MATERIALS`.
3. If more than one Job Card is eligible, scan the numbered Cooking option, for example
   `CFG:SELECT:1`, then `CFG:CMD:CONFIRM`.
4. In **Record Actual Material Use**, scan the row number for Ingredient A.
5. Scan `CFG:QTY:MATERIAL:10`.
6. Scan `CFG:CMD:CONFIRM`.

Expected:

- one Draft **Material Consumption for Manufacture** is created;
- its Work Order and Job Card are the effective Cooking records;
- its source row is Ingredient A, quantity `10`, from the configured source Warehouse;
- ERPNext stock has not changed yet;
- a second preparation for the same Job Card is blocked while this Draft exists.

## 5. Allocate the physical tag and submit

1. Scan `CFG:CMD:SCAN_MATERIALS`.
2. Scan the Ingredient A Handling Unit containing `25`.
3. Leave **Stock Quantity** at `0` or use the scanner-ready field. The Stock Entry row balance is
   `10`, so automatic allocation must reserve only `10`.
4. Confirm the trace summary shows `10 / 10` for Ingredient A.
5. Scan `CFG:CMD:SUBMIT_MATERIALS`.

Expected:

- ERPNext submits the Material Consumption for Manufacture;
- the Material Trace becomes Confirmed;
- the Handling Unit decreases from `25` to `15`, not to zero;
- Ingredient A ERP stock decreases by `10`;
- the Handling Unit stays active and its remaining `15` is available;
- the production Card and Cooking operation Card both show the same submitted entry and audit
  relationship, but the operation Card cannot access another Job Card's material entry.

## 6. No-tag Moulding material

1. Start or open Moulding when its operation gate permits.
2. Scan `CFG:CMD:PREPARE_MATERIALS` and select Moulding if prompted.
3. Confirm Ingredient B actual quantity `5`.
4. Scan `CFG:CMD:CONFIRM` to create the Draft.
5. Scan `CFG:CMD:SCAN_MATERIALS`.

Expected: the trace states that no physical tag is required. Scan
`CFG:CMD:SUBMIT_MATERIALS` to submit the native ERP entry. Ingredient B ERP stock decreases by `5`
without creating a fictitious tag.

## 7. Live balances and repeated partial use

Rescan the production Card.

Expected:

- each Job Card shows its submitted consumed quantity;
- **Required / Pending** is reduced by submitted consumption only;
- Draft quantities are not reported as consumed;
- a later consumption may record additional actual usage if a positive pending quantity remains;
- the same source tag can be scanned again for another permitted consumption, using only its
  currently available balance.

## 8. Manufacture receipt

1. Complete both Job Cards through the normal Kanban progress workflow.
2. Select **Prepare Manufacture Receipt**.
3. Confirm accepted output, destination Warehouse and optional Batch.
4. Review the input table.

Expected: inputs already submitted through Material Consumption for Manufacture are not consumed a
second time. Only ERPNext-mapped remaining input is included. Stage any required output tag, then
submit the Manufacture Stock Entry.

Final expected state:

- Work Order produced quantity increases from the submitted Manufacture entry;
- finished stock appears only after ERPNext submission;
- raw-material stock and tag balances reconcile to the submitted consumption entries;
- genealogy links the exact input Handling Unit quantities to the native production Stock Entries;
- no parallel Kanban-only stock ledger exists.

## 9. Negative tests

Verify each is rejected without stock change:

1. Scan a tag whose Item is outside the selected Job Card material list.
2. Scan a matching Item from the wrong Company, Warehouse, UOM or Batch.
3. Enter a quantity greater than the tag's available quantity.
4. Try to use an operation Card to open another Job Card's consumption entry.
5. Try to submit a Required Physical Tag row before its full Stock Entry quantity is tagged.
6. Cancel a reserved trace line before submission; its quantity must become available again.
7. Cancel a submitted consumption through ERPNext only under authorized recovery procedure; the
   Kanban production-consumption ledger must reverse rather than delete history.

## 10. Result record

Record Work Order, Job Cards, consumption Stock Entries, Material Traces, Handling Unit before/after
quantities, Manufacture Stock Entry, tester, date, and Pass/Fail notes. Attach screenshots only as
test evidence; ERPNext document state and stock ledgers remain the acceptance authority.
