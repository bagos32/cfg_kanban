# Simple setup: two hoppers, one Master, one Work Order

Use one Production Master and one Work Order with **Rinse** and **Pack**. Both operations use high-frequency Material Runs. Enable the new optional Hopper Mode only for operations with a physical holding hopper. Ordinary digital handoff keeps **Hopper Mode = None** and needs no holding-place scan.

This is a setup proposal for the new implementation, requiring test-site acceptance. Existing executions keep their old settings. Previously reported output is not automatically loaded into an old empty HOPPER_3; do not report it twice.

## 1. Example and BOM

`Raw bin -> Rinse -> Hopper_1 / Hopper_2 -> Pack + certified bags -> Finished Item`

Example: 1 Kg raw material + 1 bag = 1 finished pack. Work Order = 10 packs. Hopper load = 5 packs' equivalent. Replace these figures with your real BOM and physical hopper capacity.

Create/select the finished Item and active submitted BOM with two operations:

- **Rinse**, sequence 1: assign the raw-material BOM row's Item Operation here.
- **Pack**, sequence 2: assign the plastic-bag BOM row's Item Operation here.

Both operations and hopper WIP use the **finished Item's stock UOM**. For an Item in Nos, Rinse Good Qty = 5 means enough rinsed material for five packs; the raw-material scan still records 5 Kg. The intermediate hopper quantity is not another ERP stock receipt.

## 2. Master settings

| Field | Value |
|---|---|
| Control Type | Production |
| Item / BOM / Company | Your finished Item, BOM and Company |
| Card Representation | Batch |
| Replenishment Qty | 10 Nos in this example |
| Number of Cards | 1 main card; create the two Process cards separately |
| Use ERP BOM Operations | Enabled |
| Production Material Mode | Skip WIP Transfer |
| Manufacture Receipt Posting | Create Draft for Tag / Batch Review |
| Destination Warehouse | Actual finished-goods warehouse |

Under **BOM Component Material Flow**, load the BOM:

| Component | Item Operation | Material Run Tracking | WIP Presentation |
|---|---|---|---|
| Raw material | Rinse | Source Tag Quantity | Standard ERP / Tag Flow |
| Plastic bag | Pack | Source Tag Quantity | Standard ERP / Tag Flow |

For each row, set Source Warehouse and Material Run Scan Warehouse to its actual physical stock location. Tags must already belong to that Company/warehouse. The BOM supplies Material Qty per Output Unit.

## 3. Operation Profiles

| Field | Rinse | Pack |
|---|---|---|
| Sequence / Workstation | 1 / rinse workstation | 2 / packing workstation |
| Execution Mode | Single Workstation | Single Workstation |
| Dependency Operation | Blank | Rinse |
| Start Rule | No Dependency | Minimum Qty Available |
| Minimum Qty | Not applicable | 1 Nos |
| Handoff Mode | Digital Quantity Handoff | Full Batch Handoff; no destination |
| Destination Operation | Pack | Blank |
| Transfer Multiple | 1 Nos | Not applicable |
| Output Reporting Mode | Incremental | Incremental |
| Allow Incremental Output | Enabled | Enabled |
| Material Run Control | Required Before Progress | Required Before Progress |
| Operation Hopper Mode | **Fill Hopper** | **Consume Hopper** |
| Hopper Warehouse | Actual production warehouse | Same production warehouse |
| Output Boundary Requirement | Every Material Run | Every Material Run |
| Allow Unused Material Carry-forward | Enabled | Enabled |
| ERP Settlement Timing | At Work Order Manufacture Receipt | At Work Order Manufacture Receipt |
| Completion Rule | Full Qty | Full Qty |

For fractional output UOMs, select the appropriate Transfer Multiple; every hopper's Good Qty must be a complete multiple. Configure before releasing a new execution.

## 4. Cards and hopper identities

Create three cards linked to the same Master:

| Label | Card Type | Controlled Operation | Kanban Qty |
|---|---|---|---|
| MAIN-PRODUCTION | Physical Batch Card | Blank | 10 Nos |
| RINSE-LOAD | Process Kanban | Rinse | 5 Nos |
| PACK-LOAD | Process Kanban | Pack | 5 Nos |

Reuse both Process cards against the same Work Order's Job Cards. Record progress there once; do not repeat the same progress through the main card.

For **HOPPER_1** and **HOPPER_2**, configure:

- Tag Kind = **Reusable Container**.
- Handling Unit Type = **Hopper**.
- Reusable Container Role = **Production Output Container**.
- Identity State = Active; Quality State = Released.
- Inventory Company = Work Order Company; Current Warehouse = configured Hopper Warehouse.

Print the hopper QR identities. A hopper must have no other active operation fill or ERP-manufactured fill before Rinse selects it. This implementation adds a separate intermediate operation-fill record; it does not create ERP stock inside the hopper.

For the raw-material reusable bin, scan its current contents' standalone **Stock Tag** into Rinse, outside a formal logistics-container membership. Its ordinary permanent bin QR is not a Material Run source. Packing scans the hopper through the new Consume Hopper step, then the bag Stock Tag through the existing component step.

## 5. Bag certificates and expiry

In **Input Certificate Requirements**, select the actual approved expiry-print/serial-print certificate types for Pack:

- Gate Stage = Before Operation Start.
- Same Requirement Group, Group Logic = All Required if both are mandatory.
- Minimum Revision = approved revision; Require Unexpired = enabled.

The bag tags must carry submitted certificates and printed-expiry evidence. One certificate covering both checks needs only one requirement. Printed serial evidence does not require ERPNext serial-number control; Source Tag Quantity rejects ERPNext serial-controlled Items.

Prepare/confirm material before physical packing. Existing certificate gates and warehouse-local FEFO still apply. Printed expiry must match within a Process Card cycle; close the cycle normally before changing to another date. For one final ERP Batch with optional **Use Printed Expiry**, use one matching consumed printed date across the receipt. Different dates require separate batches and reviewed receipt allocation; a Process Card cycle does not automatically split ERP batches.

## 6. Operator sequence

1. Activate MAIN-PRODUCTION and release the Work Order with its two Job Cards.
2. Scan RINSE-LOAD and select that Work Order's Rinse Job Card. Start Material Run: scan the first output boundary, **empty HOPPER_1**, raw-material quantity and Stock Tag, then Confirm. Start Operation before physical work. Rinse/load the hopper and report Good Qty = 5 Nos. The hopper now shows Loaded = 5, Available = 5. Close Operation Cycle when its allocation is complete.
3. Scan PACK-LOAD and select the same Work Order's Pack Job Card. Start Material Run: scan the boundary, **loaded HOPPER_1**, bag quantity and certified bag tag, then Confirm. The dialog shows the hopper's loaded/available quantity. Start physical packing. Reporting two packs consumes two hopper units; Loaded becomes 3. Start another Material Run and scan the hopper again before the next report. Bag component carry-forward stays within this execution.
4. While Packing uses Hopper_1, reuse RINSE-LOAD to fill empty **HOPPER_2**. Separate workstation/operator sessions can work concurrently. Rinse cannot refill Hopper_1 while it still contains WIP.
5. After Hopper_1 is empty, switch Packing's next run to Hopper_2. Rinse can now refill Hopper_1. Continue alternating.
6. Complete/submit the Job Cards at their targets. Ensure both hopper fills are consumed. From the main card, Prepare Manufacture Receipt, review adopted actual raw-material/bag quantities and finished tags/batch, then submit once. ERP stock posts at receipt submission with this settlement setting.

Scanner commands: **CFG:CMD:START_MATERIAL_RUN**, **CFG:QTY:MATERIAL:5**, **CFG:CMD:START**, **CFG:CMD:REPORT_PROGRESS**, **CFG:CMD:CLOSE_CYCLE**, **CFG:CMD:CONFIRM**, **CFG:CMD:CANCEL**. Use **CFG:SELECT:n** for numbered operation choices. **PPHU Hopper Change remains trace-only**; it does not load hopper quantity.

Closing a Material Run retains unused component carry-forward inside its execution. Closing the Operation Card cycle releases unused components and records Unused Qty Released. Used quantities remain Consumed Pending ERP. Physical rinsed WIP remains in its hopper until consumed; final closure checks for it separately.

Run the [hopper/release acceptance checks](TEST_OPERATION_HOPPERS_AND_RELEASE.md) on an isolated site. Offline tests do not verify the live ledger or scanner. Package L1 transfer acceptance is also still partial: [L1 checks](TEST_PACKAGE_L1_TRANSFER_KANBAN.md).
