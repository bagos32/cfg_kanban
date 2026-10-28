# Acceptance Test — Controlled Production Cancellation

**Package:** V1 recovery closure  
**Purpose:** Prove that an in-flight production Cycle can be stopped without deleting history,
silently releasing stock identity, or bypassing ERPNext cancellation rules.

## 1. Preconditions

- Use a test Production Kanban Master, physical reusable Card, BOM, Work Order and Job Cards.
- Tester A has **Manufacturing User** and a valid Operator Profile.
- Tester B has **Manufacturing Manager** or **System Manager**.
- Keep the Production Operator Panel and Production Supervisor Action Center open in separate
  browser sessions if possible.
- Record the test Card, Signal, Cycle, Work Order, Job Cards, and every Stock Entry created.

Never test this flow against live customer stock. ERPNext remains the stock and manufacturing
system of record.

## 2. Case A — request freezes an active Cycle

1. Trigger and approve a normal physical Production Card so its Cycle has a submitted Work Order.
2. Start one Job Card or report a small progress quantity. Leave the Cycle incomplete.
3. As Tester B, open the **CFG Kanban Cycle**.
4. Select **Kanban Recovery → Request Controlled Cancellation**.
5. Select **Mistaken Release** and enter `V1 cancellation acceptance test`.
6. Submit the request.

Expected result:

- one **CFG Kanban Production Cancellation** opens;
- Cycle is **Hold**, blocked, and links that cancellation record;
- Card is **Blocked**, retains this Cycle as **Active Cycle**, and is not Available;
- nonterminal Process Executions are Blocked;
- every active Process/Station Card Cycle allocated to the same Work Order is also Hold/Blocked and
  remains assigned to its own Card;
- Signal is Blocked;
- a Critical **Controlled Production Cancellation** Exception exists;
- an active Job Card timer is paused through an audited **Pause Job Card** ERP Command where a
  timer was open;
- Supervisor Action Center shows the request and its blocker count.

## 3. Case B — floor writes are refused during reconciliation

While the cancellation remains active, attempt each action that is applicable:

1. report Good or Reject progress;
2. start or complete a Process Task;
3. allocate or stage a production input/output tag on a linked Stock Entry;
4. complete the operation or Cycle.

Expected result: each mutation is refused with a message naming the active Controlled Production
Cancellation. Read-only Cycle, timeline, Work Order, Job Card, and trace inspection remains
available.

## 4. Case C — ERP dependencies are truthful and ordered

Open the cancellation record and inspect **ERP and Physical Dependencies**.

Expected ERP rows, where present:

- submitted or Draft **Manufacture** Stock Entry;
- submitted or Draft **Material Consumption for Manufacture** Stock Entry;
- submitted or Draft **Material Transfer for Manufacture** Stock Entry;
- active/completed Job Card or active timer;
- Work Order until it is Cancelled.

Reverse through ERPNext in this order:

1. cancel submitted Manufacture Stock Entry;
2. cancel submitted material-consumption Stock Entry;
3. cancel submitted material-transfer Stock Entry;
4. discard unused Draft Stock Entries after confirming nothing was physically posted;
5. in the Controlled Production Cancellation record, select **ERP Reversal → Cancel Linked Job
   Card** for each active or submitted Job Card, enter reversal evidence, and confirm its Stock
   Entries are already reversed. Submitted Job Cards run the ERPNext cancellation hooks; Draft Job
   Cards and their child rows are retained as Cancelled audit records rather than deleted;
6. after no Job Card or Stock Entry blocker remains, select **ERP Reversal → Cancel Work Order**.

The two controlled ERP actions retain the Cycle-to-ERP links as audit evidence while running the
normal ERPNext document cancellation hooks. They bypass only the circular Kanban link check that
would otherwise report `Cannot delete or cancel because ... is linked with CFG Kanban Cycle`.

After each Stock Entry action, select **Refresh Assessment**. The controlled Job Card and Work
Order actions refresh automatically. Expected result: cancelled ERP documents disappear from the
blocker list, while their documents, Kanban links, and Events remain available for audit.

## 5. Case D — physical WIP and output reconciliation

If the Cycle used tagged material, WIP Bins, or produced an output Handling Unit:

1. confirm active **CFG Kanban WIP Bin Load** records appear as physical blockers;
2. complete any cancellation-generated **CFG Kanban WIP Bin Reconciliation** by exact physical
   verification and the existing Supervisor-authorized WIP recovery;
3. reverse/reconcile any output Handling Unit until no live produced/reserved quantity remains;
4. select **Refresh Assessment**.

Expected result: the cancellation cannot become **Ready to Finalize** while any active WIP load,
open WIP reconciliation, or live production-linked Handling Unit quantity remains.

## 6. Case E — finalization and reuse

1. Continue until status is **Ready to Finalize** and **Open Blocking Dependencies** is `0`.
2. Select **Finalize and Release Card**.
3. Enter, for example:
   `WO and Stock Entries cancelled; WIP bin physically counted empty by Tester B; no output stock remains.`
4. Tick the verification checkbox and finalize.

Expected result:

- cancellation is **Completed** with Finalized By/On and evidence retained;
- Cycle and Signal are **Cancelled**;
- execution, runtime allocation, open Process Task and operation summary projections are Cancelled;
- Critical Exception is Resolved;
- Card becomes **Available**, unblocked, with no Active Cycle;
- related Process/Station Cards for the same Work Order also become Available and their runtime
  Cycles/allocations are Cancelled;
- original Operation Progress, WIP Ledger, ERP documents, cancellation dependencies, and Events are
  still available for audit;
- scanning the Card can create a fresh Cycle normally.

## 7. Negative and idempotency tests

1. A Manufacturing User without manager role cannot request, refresh, or finalize cancellation.
2. Finalization with one blocker is refused and Card remains Blocked.
3. Finalization without evidence is refused.
4. Requesting cancellation again opens/returns the existing record; no duplicate is created.
5. If the Card Active Cycle does not match, request/finalization is refused; another Cycle's Card is
   never released.
6. Directly editing or deleting the cancellation record is refused.
7. The older **Safe Cancel (No Activity)** remains suitable only for an activity-free Signal; it must not
   be used to bypass this flow.

## 8. Evidence to return to development

Provide:

- cancellation name and final status;
- Signal, Cycle, Card, Work Order, Job Card and Stock Entry names;
- screenshots of the initial blocker list, physical reconciliation result, and Completed record;
- any ERPNext cancellation rejection exactly as displayed;
- confirmation that the Card was unavailable during reconciliation and reusable only after final
  closure.
