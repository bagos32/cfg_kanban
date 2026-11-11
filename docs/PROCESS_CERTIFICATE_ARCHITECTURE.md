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

Production Masters now contain:

- **Input Certificate Requirements** — certificate, operation, gate stage, minimum revision,
  expiry rule, and All/Any requirement group.
- **Output Certificate Rules** — Issue, Retain, or Revoke a certificate for processed tagged
  quantity or finished output.

These configuration rows validate only approved active certificate types and route operations.

## Direct ERPNext document rule

When a user creates a supported native ERPNext stock transaction directly:

1. Select the correct **Process Certificate Set** on each affected stock row.
2. Never use a set merely because the Item normally passes that process; verify the physical tag or
   controlled evidence.
3. To change state from no certificate to `SANITISED`, or from `SANITISED` to
   `SANITISED + PRINTED`, use a quantity-conserving stock movement such as a controlled Repack.
4. The outgoing row carries the old set; the incoming row carries the new set.
5. Submit the ERP document. Only submitted ERP stock movement changes the native Stock Ledger.

The scanner-first issuance package will automate this Repack and certificate-instance creation.
Until that package is accepted, managers may configure types/sets and use the native dimension for
controlled manual ERP transactions, but production operators must not be instructed to issue
certificates from an unimplemented screen path.

## Split and merge rules

- A child tag inherits a certificate only when the Certificate Type permits inheritance and the
  split remains within the certified quantity.
- A merge is allowed only when the active sets are identical and every member certificate permits
  it; otherwise the merge is blocked.
- A reusable container cannot make uncertified contents certified. Certificate state belongs to
  its exact content episode, not merely to the reusable container identity.
- Revocation does not erase past ledger or genealogy evidence.

## Package boundary

This foundation package provides definitions, immutable sets/instances, Kanban Master configuration,
Handling Unit visibility, native ERPNext Inventory Dimension creation, workspace links, and contract
tests.

The next runtime package must add scanner-first certificate issuance and process gates, controlled
same-Item Repack, numbered choices, confirmation/cancel commands, printable command labels, focus
recovery, genealogy display, any-certificate reporting, and kiosk acceptance tests. The foundation
must not be reported as completed floor-operation acceptance.
