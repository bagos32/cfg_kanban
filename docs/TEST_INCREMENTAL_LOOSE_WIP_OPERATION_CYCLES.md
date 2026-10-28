# Acceptance Test — Incremental Loose WIP and Partial Operation Cycles

Use this test on a development site after migration, asset build, cache clear, and restart.

## Test data

- Production quantity: `100`
- Operation Card quantity: `40`
- One Job Card operation: `Cooking`
- Loose WIP component: `TPJ`, required quantity `3 Bag`
- Permanent Loose WIP Bin: an authorized bin in the Cooking Pool
- Operation Profile Completion Rule: `Operator Complete`
- Material Flow Rule for TPJ:
  - WIP Presentation: `Loose Multi-Item WIP Bin`
  - Loose WIP Release Policy: `Incremental by Operation Cycle`

Keep at least one other BOM row on **Standard ERP / Tag Flow**. This proves the incremental option
does not weaken unrelated material gates.

## A. Configuration safety

1. Open the Production Kanban Master and refresh BOM Material Flow.
2. Configure TPJ as described above.
3. Leave the other component on Standard ERP / Tag Flow.
4. Save.

Expected: only TPJ uses incremental readiness. The other component must still be fully prepared by
its normal ERP/tag workflow.

## B. Partial material readiness

1. Release the main Production Card and submit the Work Order.
2. Prepare and submit only `1 Bag` TPJ into the authorized Loose WIP Bin.
3. Satisfy the normal readiness gate for the non-Loose component.
4. Scan the Cooking operation card and select the Job Card.
5. Start the operation.

Expected: the operation starts with the positive `1 Bag` Loose WIP balance even though the Job Card
requires `3 Bag`. If the Loose WIP balance is zero, start must be rejected with an instruction to
load material. If the normal component is incomplete, start must still be rejected.

## C. First partial operation cycle

1. Report actual Job Card progress: Good `35` (or another positive partial quantity).
2. Scan `CFG:CMD:RECORD_LOOSE_WIP_USE`.
3. Scan the Loose WIP Bin, enter/scan actual TPJ use, and Confirm.
4. Scan `CFG:CMD:CLOSE_CYCLE` and Confirm.

Expected:

- the reusable operation card becomes Available;
- the Work Order, Job Card, and main production Cycle remain open;
- the Runtime Allocation records Completion Rule `Operator Complete`;
- the allocation records its processed/good/reject quantities and unfulfilled quantity;
- the remaining Job Card demand returns to the operation-card queue; and
- the handoff follows the configured handoff mode, not the partial-close rule.

Negative test: try to close without recording Loose WIP use. Expected: closure is blocked and names
the incremental Item awaiting usage evidence.

## D. Repeated cycles and additional loading

1. Scan the same operation card again.
2. Select the same Job Card from the queue.
3. If the bin does not contain enough remaining TPJ, prepare and submit another partial load into
   the same permanent Loose WIP Bin.
4. Report the second cycle progress and record its actual Loose WIP use.
5. Close the second operation-card cycle.
6. Repeat until the Job Card target is reached.

Expected: every cycle has its own requesting Cycle reference in **CFG Kanban Loose WIP Usage**. The
bin may contain multiple load episodes, but all remain inside the same Work Order/Job Card boundary.

## E. Job Card-scoped ERP posting

1. Complete and submit the Cooking Job Card.
2. Scan `CFG:CMD:PREPARE_LOOSE_WIP_CONSUMPTION`.
3. If several completed Job Cards qualify, scan the numbered Cooking choice and Confirm.
4. Review the Draft `Material Consumption for Manufacture`.
5. Submit it with `CFG:CMD:SUBMIT_MATERIALS`.
6. Submit any controlled WIP-to-source return Draft created for unused TPJ.

Expected:

- the consumption Draft contains only recorded Loose WIP use for the selected Job Card;
- downstream Job Cards are not required to be complete;
- the Stock Entry keeps the owning Job Card in `cfg_kanban_job_card` audit context;
- only the selected Job Card's unused loads are returned; and
- submitted ERPNext entries remain the stock authority.

## F. Default behavior regression

1. Change a separate Loose WIP component or test Master to **Full Job Card Quantity Before Start**.
2. Prepare less than the required quantity.
3. Try to start its Job Card.
4. Test an Operation Profile with Completion Rule `Full Qty` and report less than its allocation.

Expected: both original full-quantity gates remain enforced.

