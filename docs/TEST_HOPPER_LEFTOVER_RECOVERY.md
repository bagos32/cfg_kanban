# Intermediate Hopper visibility and leftover recovery

Prepared against base revision `eb51873`; changes are uncommitted. This document
records offline evidence, not live-site or production acceptance.

## Scope

- Read recorded operation Hopper fills directly, including closed Work Orders.
- Logistics lookup displays Item, source operation, owning Work Order/status and
  remaining/reserved/available quantities separately from native ERP contents.
- Operational Inventory Balance includes distinct Operation WIP rows and totals;
  native ERP/tag quantities are never increased by the same WIP.
- Supervisor recovery, without an active Card, can move the entire unreserved
  remainder to an empty physical Hopper in the same Company/warehouse, confirm a
  physically empty Hopper, or record discard of its full remainder.
- Preserve original fill identity, source Material Run/Progress, original Hopper,
  original Work Order and used quantities. Transfer records a current physical
  Hopper; clear/discard records cleared quantity. Events and WIP adjustments retain
  the reason and operator. No ERP Stock Entry or Job Card is changed by recovery.
- Open runs/reservations must be returned through Material Run recovery first.
  Native ERP-posted contents require their controlled ERP/container workflow.

## Work Order carry-in

Implemented for the matching two-operation Rinse/Pack Hopper route. The receiving
order must be active/submitted, use the same Company, Item, BOM and Master, use
Skip WIP Transfer, and have an eligible source Job Card with no actual work yet.
The previous owner must be Completed/Closed/Stopped; original raw settlement must
still be submitted and validated. Source gate/sub-operation inheritance is blocked
until explicit evidence mapping exists; downstream Packing certificates stay enforced.

Carry-in preserves original fill/progress provenance, credits the new source Job
Card with a linked zero-duration row, updates the owner and WIP handoff once, and
consumes only additional actual inputs on the new order. It does not move ERP
stock/valuation or redistribute original input costs. A partial carry leaves
remaining source demand open. The final receipt requires physical Hopper Use,
valid native credits and actual Material Run proof for additional source work.
Source cancellation is blocked until downstream dependent orders are cancelled.

## Offline checks

- 319 targeted Python checks: Hopper recovery/inventory and existing Material Run,
  inventory, reservation, closure, quantity/yield, logistics identity, receipt,
  certificate, expiry, and selection regressions.
- 65 existing DocType/schema/scanner contract checks.
- 48 JavaScript checks: 14 Hopper recovery scanner/touch checks, 3 actual Logistics
  API/SQL-to-renderer checks, and 31 existing pre-use/recovery/receipt/override checks.
- Carry-in coverage includes source gates, demand, companies/BOMs, original posting, native credit tampering, zero-duration workstation handling, partial demand and native runtime input availability, receipt inputs, idempotency, and ownership/closure.
- JavaScript syntax checks on both changed floor pages and the report; diff whitespace check.
- Report joins and filters run against SQLite fixtures, not MariaDB. Recovery uses
  in-memory Frappe doubles, not real transaction/concurrency acceptance.

## Live acceptance still required

Record deployed revision, physical counts, Work Orders, fill/run/event IDs and
ERP evidence before accepting each case below. Do not perform destructive tests
against real good material without the responsible supervisor's physical check.

| Case | Expected result | Live result |
| --- | --- | --- |
| Rinse 3 into Hopper, Pack 2 | Lookup/report show Item, WO and 1 remaining; native ERP quantities unchanged | Pending |
| Recorded leftover after WO/cycle closed | Lookup and report still show its recorded Item/quantity | Pending |
| Full physical transfer to empty Hopper | Source empty/reusable; destination shows same fill remainder; provenance unchanged | Pending |
| Continue same active WO from transferred Hopper | Reserve/consume on destination; quantities conserved | Pending |
| Confirm physically empty | Explicit zero count and reason; cleared quantity audited; new load allowed | Pending |
| Full discard | Confirm full remainder and reason; used/output evidence retained | Pending |
| Reserved/open run | Recovery blocked until controlled release/cancel; release alone retains material | Pending |
| Native ERP stock, wrong Company/warehouse, occupied target | WIP recovery rejected without stock changes | Pending |
| Lost response/retry, changed payload/token, double Confirm | One audit/outcome; changed token payload rejected | Pending |
| Carry 3 into a fresh 3-unit WO | Native Rinse credit 3 with zero duration; Pack scans inherited Hopper and new certified bags; receipt has new bags and no repeated raw input | Pending |
| Carry 3 into a fresh 5-unit WO | Rinse remaining demand 2; final receipt consumes only actual new raw 2 plus actual bags 5 | Pending |
| Busy workstation / native time enforcement | Inherited row occupies zero time; real work overlap and all native sequence/quantity rules remain enforced | Pending |
| Reversed source / changed native credit / missing physical use | Carry/pre-use/receipt rejected; read-only context still permits recovery | Pending |
| Carry-in retry and target choices | One native credit; explicit selection; more than ten choices page correctly | Pending |
| Fixed scanner in kiosk/full-screen | Command, physical IDs, numbered choices, quantity zero/positive, reason, Confirm/Cancel and error focus work without mouse | Pending |
| Touch flow | Same identities, quantities, authorizations and recovery outcome as scanner | Pending |

Migrate the updated Hopper Fill fields before using this code on a site. No live
records were inspected, reconstructed, cleared or transferred during development.


Native reference reviewed: ERPNext v15.65.1 Job Card validates completed quantities
from time-log rows, permits equal From/To timestamps, and normally performs
workstation overlap checks even for those rows. The carry validation exemption is
limited to immutable, exactly matching zero-duration carry rows; actual-work rows
still delegate to the native overlap implementation. Source:
https://github.com/frappe/erpnext/blob/v15.65.1/erpnext/manufacturing/doctype/job_card/job_card.py
