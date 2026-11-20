# Direct Customer Return — customer selection without a Site QR

## Implementation and acceptance boundary

This extends the existing D2A Customer Return for QC intake. It reuses its Return
Case, evidence, QC, D2B accounting and physical disposition. Site-based intake
and exact Delivery Note Correction retain their Site requirements. Direct intake
creates no Site, Delivery Session, ERP stock document or accounting document.

Offline behavioural coverage: `cfg_kanban/tests/test_direct_customer_returns.py`
and `cfg_kanban/tests/test_direct_customer_return_ui.cjs`. Dependency doubles do
not prove MariaDB transaction/locking, native permissions, migrations, printing,
S3 media, ERP stock/accounting or kiosk/camera behaviour on a deployed site.

**Development-site acceptance: Not run.** Record the deployed revision and results
below; do not substitute offline results for site evidence.

## Setup

- Enable Customer Return Workflows in CFG Kanban Settings.
- Intake operator: Customer Return responsibility + Start permission, or existing
  unrestricted Supervisor authority; QC inspector: Customer Return QC authority.
- Terminal ERP user: read permissions/user restrictions for the selected Company,
  Customer, native Location, Items, optional Address and Batch.
- Existing native Location for physical QC custody. Optional custom company/disabled
  fields are respected. No Customer Scan Point is needed.
- Supported HTTPS/localhost browser with Web Locks; printed command labels from
  Kanban Operator → Scanner Command Labels. Use the existing D2A/D2B setup for QC,
  accounting, evidence and disposition roles.

## Acceptance checklist

| Scenario | Expected result | Site evidence |
| --- | --- | --- |
| Customer without any Site QR | Direct Customer Return allows explicit Company/Customer selection and required custody | Not run |
| Company differs from Kanban default | Note and Case retain selected Company/Customer; no default substitution | Not run |
| Optional address and multi-Item rows | Linked address accepted; wrong-Customer address rejected; Batch/expiry/tag/condition/details retained | Not run |
| Review stock UOM quantities | Review occurs before issuing; wrong Batch, fractions of whole UOM, zero/negative/non-finite qty rejected | Not run |
| Disabled/restricted masters | Disabled Customer/Item, group Company, unauthorized read and mismatched company-specific custody rejected | Not run |
| Intake permissions | Missing Customer Return/Start or disabled workflow blocks new notes; no stock/accounting is posted | Not run |
| Printed Temporary Return Note | Customer, Company, Direct Customer method, custody, items and Case QR shown; custody warning retained | Not run |
| Existing Site QC intake | Still works and preserves Site snapshots/inspection custody | Not run |
| Existing wrong-DN correction | Still needs original delivered Session, Site and exact submitted DN; no direct-intake bypass | Not run |
| QC and evidence | Direct Case receives evidence, starts QC and completes accepted/rejected quantities without a Site | Not run |
| Accounting and disposition | Existing source invoice Company/Customer gates, no-credit and stock/disposal decisions work; ERP retains stock/accounting ownership | Not run |
| Duplicate/lost response | Retry original payload creates one Case/event; reopen/refresh restores pending values/token | Not run |
| Read vs abandon pending request | Not Recorded stays locked; reasoned void prevents late creation; recorded note opens instead | Not run |
| Multiple tabs/changed operator | No second intake slips past pending request; original actor required; unknown retry remains locked on error | Not run |
| Scanner-only kiosk | Open, numbered header/table inputs, add/move rows, Qty, review/edit/Confirm/Cancel, reason and pending reconciliation complete without mouse/keyboard | Not run |
| Tablet and focus | Camera button and command accept one scan; Tab/Enter work; cancel/error/success restore focus and late camera callbacks are ignored | Not run |

## Scanner commands

`CFG:CMD:DIRECT_CUSTOMER_RETURN`, `RETURN_ITEMS`, `RETURN_ADD_ITEM`,
`RETURN_NEXT_ITEM`, `RETURN_PREVIOUS_ITEM`, `RETURN_INPUTS`, `RETURN_REASON`,
`RETURN_EDIT`, `RETURN_CAMERA`, `RETURN_RECONCILE`, `RETURN_VOID_REASON`,
`RETURN_VOID_PENDING` (all names prefixed `CFG:CMD:`), standard Confirm/Cancel,
numbered choices, Next/Previous Material Choices and `CFG:QTY:MATERIAL:n`.

## Offline validation — 20 November 2026

- 23 direct-return backend/controller checks passed, including the existing Site
  intake, legacy missing-method compatibility, QC, no-credit decision and disposal.
- 65 existing DocType/schema checks passed.
- 27 direct-return controller/dialog/scanner checks passed, including unknown
  requests, cross-tab serialization, immediate scanner cancel and camera handling.
- 191 existing UI regression checks passed for prepared fulfilment, Open Route,
  warehouse/pickup, Dispatch Review/recovery, repack and stock isolation.

These tests execute application functions/controllers using dependency doubles.
They do not verify migration, native database locking/rollback, live permissions,
PDF output or scanner/tablet use on the deployed ERPNext/Frappe site.

## Recorded result

- Deployed Git revision:
- Test date / operator / terminal user:
- Return Cases, printed notes and relevant ERP records:
- Exceptions / deferred risks:
- Acceptance decision:
