# CFG Kanban Acceptance Test — Skip-WIP Single-Settlement Flow

**Purpose:** prove that Skip-WIP uses ERPNext's native final Manufacture transaction for ordinary
input consumption, without a duplicate intermediate consumption entry. Job Card-end Material Run
settlement is tested separately in `docs/TEST_OPERATION_MATERIAL_RUN_SETTLEMENT.md`.

Test only on the development site with disposable quantities.

## 1. Test data

Use one submitted BOM with two operations:

| Component | Item Operation | Test tag policy | Required quantity |
|---|---|---|---:|
| Ingredient A | Cooking | Required Physical Tag | 10 |
| Ingredient B | Moulding | No Physical Tag | 5 |

Prepare an active Ingredient A Handling Unit in its configured source Warehouse with quantity
`25`. The BOM must use Operations and each operation-controlled BOM Item must have its exact Item
Operation.

## 2. Kanban Master

Create or copy a Production Master with:

- **Production Material Mode** = `Skip WIP Transfer`;
- ERPNext BOM / Work Order **Transfer Material Against** = `Job Card`;
- per-component source Warehouses in **BOM Component Material Flow**;
- both components set to **No Run Tracking** for this baseline;
- **Manufacture Receipt Posting** = `Create Draft for Tag / Batch Review`; and
- Cooking and Moulding Operation Profiles.

Expected validation: an operation-controlled BOM component without Item Operation is rejected.

## 3. Release and execute

1. Activate and release the production Kanban Card.
2. Confirm ERPNext creates one submitted Work Order and both Job Cards.
3. Scan the production Card in **Kanban Operator**.

Expected:

- Material mode is `Skip WIP Transfer`;
- no Material Transfer for Manufacture exists;
- no general **Consume Operation Materials** or **Consume Work Order Materials** action appears;
- **Settle Material Runs** appears only for used Material Runs explicitly configured
  **At Job Card End**; and
- Job Card start is not blocked by a WIP-transfer prerequisite.

4. Execute and complete Cooking and Moulding through their normal operation-card progress flow.
5. Do not prepare a separate consumption entry for these ordinary components.

Expected: no Material Transfer or Material Consumption for Manufacture exists, and raw-material
ERP/Handling Unit quantities remain unchanged until final Manufacture.

## 4. Prepare final Manufacture

1. From the main production Card choose **Prepare Manufacture Receipt**.
2. Confirm the accepted finished quantity, destination Warehouse and native input quantities.
3. Open Production Material Trace for the Draft Manufacture entry.
4. Scan the Ingredient A Handling Unit containing `25`. The input row balance is `10`, so automatic
   allocation must reserve only `10`.
5. Ingredient B must show that no physical input tag is required.
6. Stage the finished-output tag/container.
7. Scan `CFG:CMD:SUBMIT_MATERIALS`.

Expected:

- ERPNext submits one Manufacture entry containing the raw inputs and finished output;
- the Material Trace becomes Confirmed;
- the Ingredient A Handling Unit decreases from `25` to `15` exactly once;
- Ingredient A ERP stock decreases by `10` exactly once;
- Ingredient B ERP stock decreases by `5` without a fictitious tag;
- Work Order produced quantity and finished stock increase only after submission; and
- no unused Draft production Stock Entry remains.

## 5. Closure and recovery gates

1. Repeat the test but stop after creating the Draft Manufacture entry.
2. Attempt to close/release the production Cycle.

Expected: closure rejects and names the open Draft Stock Entry.

3. Cancel a reserved trace line before submission. Its Handling Unit quantity must become
   available again.
4. Abandon the Draft trace through the controlled action, then have an authorized supervisor
   delete the now-unposted Draft Stock Entry before creating a fresh receipt.
5. Submit and close normally.

Expected: audit history remains, no raw material is consumed twice, and no orphan Draft remains.

## 6. Negative tests

Verify each is rejected without stock change:

1. Scan a tag whose Item is outside the Manufacture input list.
2. Scan a matching Item from the wrong Company, Warehouse, UOM or Batch.
3. Enter a quantity greater than the tag's available quantity or ERP row remainder.
4. Submit a Required Physical Tag row before its complete Stock Entry quantity is traced.
5. Attempt Cycle closure while a linked Draft exists.

## 7. Result record

Record deployed revision, Master, Cycle, Work Order, Job Cards, Manufacture Stock Entry, Material
Trace, Handling Unit before/after quantities, tester, date and Pass/Fail notes. ERPNext document and
stock-ledger state remain the acceptance authority.
