# CFG Kanban Process Certificate Architecture

## Purpose

Process Certificates describe **what controlled value-neutral processes a physical stock quantity
has passed** without creating another ERPNext Item for every intermediate state.

Example:

| Physical state | ERPNext Item | Process Certificate Set |
|---|---|---|
| Purchased blank pouch | `PLS_ABC` | blank |
| Sanitised pouch | `PLS_ABC` | `SANITISED` |
| Sanitised and printed pouch | `PLS_ABC` | `SANITISED + PRINTED` |

ERPNext remains the stock system of record. CFG Kanban controls the physical certificate identity,
process gates, scans, issuance evidence, and genealogy.

## Identity model

Four identities must not be mixed:

1. **Item** — what the material is for valuation, purchasing, BOM, and stock accounting.
2. **Batch** — ERPNext lot/expiry/quality stock identity when true Batch control is required.
3. **Handling Unit / Stock Tag** — the exact physical box, bundle, tote, or quantity.
4. **Process Certificate** — proof that the exact tagged quantity passed a controlled process.

A certificate is never granted globally to an Item. It is issued to an exact Handling Unit episode
and quantity. A partial process therefore requires a controlled physical split or separate output
tag before a different certificate state can exist.

## Native ERPNext Stock Ledger integration

Migration creates one ERPNext **Inventory Dimension**:

- **Dimension Name:** `Process Certificate Set`
- **Reference Document:** `CFG Process Certificate Set`
- **Fieldname:** `process_certificate_set`
- **Apply to All Inventory Documents:** enabled
- **Validate Negative Stock:** enabled

ERPNext creates the corresponding Link fields on supported inventory transaction rows and Stock
Ledger Entry (including separate source/target fields where ERPNext provides them). The native
**Stock Ledger** and **Stock Balance** reports can therefore filter an exact
certificate state such as `SANITISED + PRINTED`. A Work Order, Stock Entry, Purchase Receipt, or
other stock document created directly in ERPNext can carry the same dimension.

ERPNext v15 does not expose Inventory Dimensions consistently on every stock utility. In
particular, do not use Stock Reconciliation as the certificate-state acceptance path unless the
deployed ERPNext revision is separately verified to support it. Use supported Stock Entry/Repack
transactions and confirm the submitted Stock Ledger instead.

The native filter selects an **exact certificate set**. To find every set that contains one
certificate type (for example every stock state containing `SANITISED`), use the future CFG Kanban
certificate inventory report. Exact-set filtering is deliberate because one physical balance must
have one unambiguous stock state.

## Configuration records

### CFG Process Certificate Type

An approved, revision-controlled definition such as `SANITISED-R001` or `PRINTED-R001`. The stable
Certificate Code remains `SANITISED` or `PRINTED`, while the record identity also includes its
revision. It records optional
Item/Item Group applicability, validity, evidence, supervisor verification, split inheritance,
merge policy, and a neutral external-standard revision snapshot.

This record does not depend on TrackQMS. A future connector may synchronize an approved external
standard while CFG Kanban keeps its immutable revision snapshot.

### CFG Process Certificate Set

An immutable combination of approved certificate revisions. Examples:

- `SANITISED`
- `SANITISED + PRINTED`
- `SANITISED + PRINTED + QC_RELEASED`

Membership and the stable set code cannot be edited after insert. Create a new set when the
combination changes. Deactivation requires an audit reason and does not rewrite historical stock.

### CFG Process Certificate

An immutable issued instance tied to one Handling Unit, Item, quantity, Company, Warehouse, Batch,
operation, Work Order/Job Card/Kanban context, operator, validity, evidence references, and
resulting Certificate Set. It is revoked or superseded; it is not deleted or rewritten.

### CFG Kanban Master rules

Production and Certificate Process Masters now contain:

- **Input Certificate Requirements** — certificate, operation, gate stage, minimum revision,
  expiry rule, and All/Any requirement group.
- **Output Certificate Rules** — Issue, Retain, or Revoke a certificate for processed tagged
  quantity or finished output.

These configuration rows validate only approved active certificate types and route operations.
Certificate Process uses one dedicated controlled Operation and does not accept a BOM.

## No-BOM Certificate Process runtime

Use **Control Type = Certificate Process** when a value-neutral floor process changes the
controlled state of the same stock Item, for example printing a sanitised pouch.

1. A physical Card creates the normal auditable Signal and Cycle.
2. Release creates one `CFG Process Certificate Run`; it does not create a Work Order or Job Card.
3. The operator scans a quantity and exact source Stock Tag. The system checks Item, UOM, Company,
   Warehouse, available tagged balance, ERPNext stock, and the configured certificate gate.
4. The selected tagged quantity is reserved operationally.
5. Completion creates a native ERPNext **Repack without BOM**. The outgoing row uses the source
   Certificate Set; the incoming row uses the immutable result Set.
6. Until that Repack is submitted, the source tag and issued certificate records do not change.
7. Submitted ERP feedback releases the reservation, moves partial quantity to its new output tag
   or updates a full reused tag, issues immutable certificate instances, completes the Cycle, and
   releases the reusable Card.

Partial processing can never change only part of one physical tag. It requires a separate unused
main output tag. Full processing may reuse the source tag when the Master permits it and no reject
quantity remains on that source identity.

Batch behavior is not duplicated in Kanban configuration. The Run snapshots ERPNext Item
`has_batch_no` at release. A Batch-controlled source tag must carry its exact Batch. Leaving Output
Batch blank preserves that source Batch; scanning/entering another valid Batch moves the processed
quantity to that Batch. When the Item is not Batch controlled, Batch inputs are rejected. Printed
expiry and first/last printed serial are process evidence; native FEFO exists only when ERPNext
Batch control and its expiry are used.

## Work Order / Job Card Production runtime

Use **Control Type = Production** when the process also changes the ERPNext Item through a BOM,
Work Order, Job Cards, and a final Manufacture Stock Entry. Certificate rules remain attached to
the exact Operation, including when that Operation is executed from a reusable Process or Station
Card.

1. **Before Operation Start** requirements are evaluated from a prior completed operation's
   immutable result Set. This is suitable for sequential operation-to-operation gates.
2. **Before Progress** requirements are evaluated from the source Handling Units scanned in the
   operation Material Run, plus the prior operation result. Use this stage when the first operation
   must prove certified raw material because Material Runs begin after the Job Card starts.
3. A reusable Process/Station Card has its own Kanban Cycle, but its scanned Material Draws are
   joined through the authoritative ERP Job Card. The Work Order-owning execution therefore sees
   the same evidence without a second scan.
4. Each progress/Job Card completion freezes its result Certificate Set on the Process Execution.
   That digital handoff carries the controlled state between operations before finished stock
   physically exists.
5. **Before Material Consumption** and **Before Output Release** requirements are rechecked while
   the controlled ERPNext Stock Entry submits.
6. Production Certificate Output Rules must apply to **Finished Output**. The complete Manufacture
   output must be staged to physical Stock Tags or Production Output Containers.
7. Before submission, the final result Set is written to the native `Process Certificate Set`
   Inventory Dimension on each finished-output row. ERPNext submission remains the stock truth.
8. After submission confirms the output identities, CFG Kanban binds the Set and immutable issued
   certificates to each exact output Handling Unit quantity.

Parallel final Job Card lanes may share one output only when they resolve to the same exact
Certificate Set. Different lane results are never silently unioned; reconcile them or stage them
as separate certified outputs. Cancelling the authoritative Manufacture/Repack voids or reverses
the related physical output through the existing recovery path and marks its issued certificates
Revoked without deleting their audit history.

This does not add a second operator workflow. Existing scanner-only Material Run quantity/tag
scans supply certificate evidence, and existing output-tag staging supplies the finished identity.
Simple Production Masters with no Certificate rules behave exactly as before.

## Direct ERPNext document rule

When a user creates a supported native ERPNext stock transaction directly:

1. Select the correct **Process Certificate Set** on each affected stock row.
2. Never use a set merely because the Item normally passes that process; verify the physical tag or
   controlled evidence.
3. To change state from no certificate to `SANITISED`, or from `SANITISED` to
   `SANITISED + PRINTED`, use a quantity-conserving stock movement such as a controlled Repack.
4. The outgoing row carries the old set; the incoming row carries the new set.
5. Submit the ERP document. Only submitted ERP stock movement changes the native Stock Ledger.

The Production Operator Panel automates the no-BOM path with printable Certificate Process command
labels. Work Order production reuses the existing scanner-only Material Run, progress, output-tag,
confirmation, and cancellation commands. Direct ERPNext transactions remain available for
authorized recovery and manual work, but must use the same exact-set and submitted-stock rules.

## Split and merge rules

- A child tag inherits a certificate only when the Certificate Type permits inheritance and the
  split remains within the certified quantity.
- A merge is allowed only when the active sets are identical and every member certificate permits
  it; otherwise the merge is blocked.
- A reusable container cannot make uncertified contents certified. Certificate state belongs to
  its exact content episode, not merely to the reusable container identity.
- Revocation does not erase past ledger or genealogy evidence.

## Acceptance boundary

The repository now contains scanner-first runtime for both the no-BOM Certificate Process and
Work Order / Job Card Production. This implementation status is not live-site acceptance. Complete
the dedicated kiosk tests, native Stock Ledger evidence, negative gates, cancellation/recovery, and
deployed-revision record before declaring either route production-ready. Genealogy display,
any-certificate reporting, split/merge enforcement, and controlled revocation remain separate
acceptance increments unless their test documents explicitly record a pass.
Repository implementation must not be reported as completed floor-operation acceptance.
