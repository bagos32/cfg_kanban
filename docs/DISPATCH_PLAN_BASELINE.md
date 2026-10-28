# CFG Kanban Dispatch Planning Baseline

**Baseline identifier:** `CFG-DISPATCH-E2`
**Decision status:** Locked
**Current status:** E1 and E2 implemented; E3–E5 remain pending
**Implementation status:** Dispatch Profiles, permanent Dispatch Operations cards, the read-only
operator launcher, Dispatch Plans, approval/cancellation, and controlled tagged/untagged reservation
are implemented. E2 does not assign a vehicle, create a Manifest, move stock, or post ERP documents.

## 1. Objective

Keep warehouse operators, drivers, and supervisors inside CFG Kanban while ERPNext remains the
system of record. Operators must not need to understand or open native Stock Entries, Delivery
Notes, or other ERP documents during normal floor work.

The solution must support:

1. known customer and quantity with the lorry assigned later;
2. unknown customers with a total route-stock quantity prepared in advance;
3. direct customer delivery or pickup from a Sales Company warehouse without a lorry;
4. existing ad-hoc customer delivery from stock already held in a lorry warehouse;
5. tagged, untagged, and mixed stock;
6. optional Goods-in-Transit routing when the final destination is genuinely unknown after
   physical dispatch;
7. end-of-route stock reconciliation and controlled recovery.

## 2. Central design decision

Introduce one user-facing **CFG Kanban Dispatch Plan** rather than separate unrelated planning
systems.

The Dispatch Plan authorises and reserves stock. It does not itself move ERP stock. Existing CFG
Kanban Movement Manifests, Handling Units, Customer Delivery Sessions, Delivery Allocations,
Delivery Notes, delivery proof, and Route Reconciliation remain the execution and audit records.

Two initial Plan Types are required:

| Plan Type | Customer required at planning | Purpose |
|---|---:|---|
| Customer Order | Yes | Reserve and prepare a known customer requirement before vehicle assignment |
| Open Route Stock | No | Prepare a general quantity for mobile/route sales to customers identified later |

## 3. Fulfilment modes

| Fulfilment Mode | ERP chronology |
|---|---|
| Vehicle Delivery | Sales Warehouse → Material Transfer → Company-specific Lorry Warehouse → Delivery Note |
| Direct Warehouse Delivery | Sales Warehouse → Delivery Note |
| Customer Pickup | Sales/Pickup Warehouse → Delivery Note plus pickup acknowledgement |
| Existing Ad-hoc Lorry Delivery | Existing Lorry Warehouse stock → Customer Delivery Session → Delivery Note |
| Goods in Transit | Source → Transit Warehouse → destination selected at receipt → final Warehouse |

Goods in Transit is optional and should follow the primary packages. It is justified only when
goods physically depart before the destination Warehouse is known.

Direct delivery must use a Warehouse belonging to the Selling Company. If stock remains owned by a
Manufacturing Company, the intercompany handover must complete into a Sales Company Warehouse
before customer delivery. Two Company-specific Warehouses may represent the same physical factory.

## 4. One-card operator experience

Extend the existing permanent Location Card with a **Dispatch Operations** purpose. One permanent
Dispatch Point Card identifies the operating context:

- Company;
- source Warehouse;
- physical dispatch point;
- available manager-controlled Dispatch Profiles.

The operator selects the business work, not the technical ERP method:

```text
Scan operator
  → Scan Dispatch Point Card
  → View prioritised eligible work
  → Scan/select the work context
  → System resolves the Dispatch Profile
  → Show only necessary data capture
  → Review and activate
```

Automatic resolution rules:

| Scanned context | Action |
|---|---|
| Existing Dispatch Plan | Resume that Plan |
| Sales Order | Use the eligible Customer Order Profile |
| Customer Site | Use eligible Direct Delivery, Pickup, or prepared Customer Plan |
| Route code | Use the eligible Open Route Stock Profile |
| Lorry Warehouse card | Show prepared loads eligible for that vehicle |
| Stock Tag | Show eligible active preparation/load work for the Item |
| No second scan | Show authorised preset work queue |

If exactly one workflow is eligible, open it automatically. When more than one is valid, show a
small business-language choice rather than ERP document names or technical routing modes.

## 5. Dispatch Profiles

Add a manager-controlled **CFG Kanban Dispatch Profile** containing:

- business-facing label, instructions, colour, priority, and active state;
- Company and Dispatch Point/source Warehouse;
- Plan Type and Fulfilment Mode;
- permitted route, territory, Customer Site, or destination scope;
- staging Warehouse and Goods-in-Transit Warehouse where applicable;
- destination assignment policy: Fixed, Select Before Dispatch, or Select at Receipt;
- tag policy: tagged, untagged, or mixed;
- FIFO/FEFO suggestion policy;
- approval and supervisor-override policy;
- ERP auto-submit policies;
- proof policy and responsible operational roles.

The selected Profile is snapshotted into the Dispatch Plan. Later Profile edits must not alter
active or historical Plans.

## 6. Preparation and reservation

Sales or a supervisor creates the business request. The warehouse operator only prepares it.

### Known customer

Capture Customer Site or optional Sales Order, Item/quantity, required date, and priority. Vehicle
assignment is not required during preparation.

### Open route stock

Capture route/territory, trip date, Item/total quantity, and priority. Customer and vehicle are not
required. Example: prepare 100 pieces for route sales, then allocate actual quantities to individual
customers during the trip.

Tagged stock reserves exact Handling Units. Untagged stock reserves Company, Warehouse, Item,
optional Batch, UOM, and quantity. Mixed Plans may use both. Reservation changes Kanban available
quantity but does not post ERP stock movement.

Suggested preparation states:

```text
Draft → Awaiting Approval → Approved → Picking → Ready for Vehicle
```

Cancellation before loading releases every active reservation while preserving audit history.

## 7. Late vehicle assignment

The warehouse operator is not required to know the lorry. A driver scans the Company-specific lorry
Warehouse card and sees **Loads Awaiting Vehicle Assignment**.

The driver claims one prepared Plan. The claim must be atomic so two drivers cannot claim the same
load. After assignment, the operator scans/verifies the physically loaded stock and confirms
loading. The backend creates the controlled ERPNext Material Transfer without exposing the native
Stock Entry UI.

Preferred mode:

```text
Prepared, destination unassigned
  → driver claims with Lorry Card
  → destination Warehouse locked
  → one Material Transfer from source/staging to lorry
```

After ERP submission, destination reassignment is prohibited. Correction requires controlled
cancellation or reverse movement.

## 8. Customer delivery

For a Customer Order Plan, scanning the Customer Site retrieves the prepared delivery. For Open
Route Stock, the driver scans each Customer Site and allocates the actual quantity from current
lorry stock. Each customer receives a separate Delivery Note and proof record.

A genuinely unknown Customer cannot receive a compliant Delivery Note. The operator must scan or
select an existing Customer Site, use an approved walk-in Customer policy, or request authorised
Customer creation. Drivers must not freely type accounting Customer identities or prices.

## 9. Route reconciliation

The system must reconcile:

```text
opening lorry load
  - submitted customer Delivery Notes
  - approved damage/loss
  - returned stock
  = expected closing balance
```

Remaining stock may stay in the lorry overnight, return to a Warehouse, move to another authorised
lorry, or go on Hold for discrepancy investigation.

## 10. Minimal data model

New records:

1. **CFG Kanban Dispatch Profile** — reusable manager-controlled policy.
2. **CFG Kanban Dispatch Plan** — user-facing business authorisation and lifecycle.
3. **CFG Kanban Dispatch Plan Line** — requested Item quantities.
4. **CFG Kanban Dispatch Allocation** — exact tagged or untagged reservations.

Existing records to reuse:

- CFG Kanban Card with Dispatch Operations Location purpose;
- CFG Kanban Movement Manifest and Manifest Line;
- CFG Kanban Handling Unit and quantity ledger;
- Warehouse/lorry cards and Customer Scan Points;
- CFG Kanban Delivery Session and Delivery Allocation;
- ERPNext Stock Entry and Delivery Note through the ERP gateway;
- CFG Kanban Delivery Proof and Route Reconciliation.

No additional physical card is mandatory beyond the Dispatch Point, Stock Tag, Warehouse/Lorry,
and Customer Site cards already in the architecture.

## 11. Guardrails

- ERPNext submission remains the stock system-of-record event.
- Operators remain in CFG Kanban panels during normal work.
- Company, source Warehouse, document type, price, and posting policy come from the Profile.
- Wrong-Company tags, Warehouses, vehicles, and Customers are rejected.
- One quantity cannot be actively reserved by two Plans.
- One prepared load cannot be claimed by two vehicles.
- Every activation and override is idempotent and audited.
- Supervisor override requires authority and a reason.
- Cancellation releases reservations but never deletes history.
- ERP mandatory fields are supplied by presets; the panel requests only genuinely missing
  operational values.

## 12. Approved implementation sequence

### E1 — Profiles and one-card launcher — implemented

- Dispatch Profiles;
- Dispatch Operations Location Card purpose and print behaviour;
- prioritised queue and automatic Profile resolution;
- no stock movement in this package.

### E2 — Plans and preparation — implemented

- Customer Order and Open Route Stock Plans;
- approval/cancellation;
- tagged, untagged, and mixed reservations;
- preparation state through Ready for Vehicle;
- immutable Profile revision snapshot, idempotent creation/reservation and release audit;
- no staging Stock Entry, vehicle assignment, Manifest, or ERP posting in this package.

### E3 — Vehicle claim and loading

- last-minute lorry assignment;
- atomic claim;
- Manifest generation;
- controlled ERP Material Transfer.

### E4 — Customer fulfilment

- prepared known-customer delivery;
- Open Route Stock delivery to multiple customers;
- Direct Warehouse Delivery and Customer Pickup;
- Delivery Note and proof integration.

### E5 — Reconciliation and recovery

- loaded, delivered, remaining, returned, overnight, and variance control;
- reassignment and cancellation guardrails;
- system test package and User Manual update.

### Optional E6 — Destination selected at receipt

- Goods-in-Transit-only dynamic destination;
- second controlled Stock Entry from transit to the selected destination;
- implement only after E1–E5 pass end-to-end testing.

## 13. Resume instructions

When this work is resumed, first audit the current repository against this document and the latest
`docs/MULTI_COMPANY_LOGISTICS_ARCHITECTURE.md`. Do not rebuild Dispatch Profiles, Dispatch Plans,
reservation, existing Manifest, Customer Delivery, proof, tag, or reconciliation features. Begin
E3 only after the E2 acceptance test passes. Keep production execution behaviour separate, add
regression tests, and stop for user-managed commit/deployment before each later package.

