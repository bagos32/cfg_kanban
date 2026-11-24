# ERPNext logistics audit fields: permissions regression and related-risk review

Reviewed 24 November 2026. Code scope is the optional operator Employee and counterpart Company
audit Links on native Delivery Note and Purchase Receipt. This document is not live-site acceptance.

## Reported failure and permanent change

An ordinary ERPNext user creating a Delivery Note received an Employee `empty` rejection in
**Requested by Kanban Operator**, followed by a generic Create permission error. The field is
installed on the native DocType, so opening the document from ERPNext also runs its Link-based
User Permission checks. Under strict User Permissions, a blank Link can fail an applicable
Employee restriction; a populated operator belonging to another Employee can also fail it.

The user then reported an empty Delivery Note list with Company-restricted access. Native
list-query construction filters every non-exempt Company Link, including Kanban's optional
**Counterpart Company**. It combines that filter with the standard owning **Company** filter.
Under strict permissions, a blank counterpart is excluded; an unpermitted intercompany
counterpart is excluded even without strict mode. This structural failure was reproduced with
native query functions and fixture rows; the production metadata/queries were not inspected.

`cfg_kanban/install.py` now declares `ignore_user_permissions = 1` only for
`cfg_requested_operator` and `cfg_counterpart_company` on Delivery Note and Purchase Receipt.
The operator is attribution; the counterpart Company is intercompany audit data. The standard
owning **Company** remains the access boundary. Native Custom Field creation and updates cover
new and existing sites. After that update, effective metadata is checked:
if a Property Setter shadows the setting, the native validated `make_property_setter` API
repairs only this field's Ignore User Permissions property. Correct manual exemptions are
preserved, and subsequent migrations do not repeatedly rewrite them. A missing or mistyped
audit Link stops setup instead of granting a broader exemption.

Both fields remain optional, read-only Links. Genuine operator and counterpart Company values
are unchanged, and the normal ERPNext path needs no artificial audit values. No transactional
documents, User Permission records, roles, system strict-permission setting or permission
hooks are changed. This does not grant access to referenced Employee or Company records.
Do not grant additional Company access or exempt the standard Company field to repair this issue.

Native behavior was checked against these official Frappe v15.94.0 sources:

- [Permission evaluation](https://github.com/frappe/frappe/blob/v15.94.0/frappe/permissions.py):
  `has_user_permission` skips only Link fields marked Ignore User Permissions;
  `get_doc_permissions` still applies native roles, controller rules and User Permissions.
- [Native list-query permissions](https://github.com/frappe/frappe/blob/v15.94.0/frappe/model/db_query.py):
  `DatabaseQuery.build_match_conditions` and `add_user_permissions` retain the main Company
  filter and omit only explicitly exempted audit fields.
- [Custom Field updates](https://github.com/frappe/frappe/blob/v15.94.0/frappe/custom/doctype/custom_field/custom_field.py):
  `create_custom_fields(..., update=True)` updates existing fields and clears affected metadata.
- [Property Setter API](https://github.com/frappe/frappe/blob/v15.94.0/frappe/custom/doctype/property_setter/property_setter.py):
  `make_property_setter` replaces only the matching property and uses native metadata validation.

## Review of other DocTypes and fields

The review covered all app-created Custom Fields, their creation call sites, the generated
Inventory Dimension path, and all 146 app DocType JSON files at the baseline revision
`8013082`. The native ERP Custom Field definitions contain 45 Link placements across 15
parent/child DocTypes. Only two point to Employee: the two operator audit fields fixed here.
The optional custom Credit Note gets Return Case and event references, with no Employee Link.

Other Links can cause a similar rejection **when a User Permission on their target DocType
applies to the document**. Read-only does not prevent permission propagation. Link validation
does not recursively follow a target's own Employee/Company fields: e.g. a Cycle reference
does not by itself propagate its operator's Employee restriction to an ERP document.

| Field / documents reviewed | Remaining risk and decision |
| --- | --- |
| `cfg_counterpart_company` on Delivery Note and Purchase Receipt | Fixed alongside the operator audit Link: counterpart trace data no longer adds a second Company filter to ordinary document/list access. The standard owning Company field and other business Company Links remain permission checked. |
| `cfg_sales_order`, `cfg_planned_batch` on Work Order; `cfg_sales_order` on Batch | Applicable Sales Order or Batch User Permissions can reject a blank or out-of-scope optional reference. Existing MTO/business-reference checks remain unchanged. |
| `cfg_kanban_job_card` on Stock Entry | Applicable Job Card User Permissions can reject blank or out-of-scope references. This field identifies operation-owned material consumption; its access policy is unchanged. |
| Cycle/Signal links on Work Order, Job Card, Stock Entry, Material Request, Purchase Order, Delivery Note and Purchase Receipt | A User Permission explicitly targeting the linked Kanban DocType can restrict these documents, including blank links in strict mode. No automatic exemption is introduced. |
| Route Template on Sales Order; Demand on Batch; Route/Manifest/Session/Return Case links on logistics ERP documents; Return Case on Sales Invoice and optional Credit Note | Same conditional risk if the site restricts those specific Kanban target DocTypes. Preserve their current policies and verify any configured User Permissions. |
| Handling Unit/Delivery Allocation links on Stock Entry Detail, Delivery Note Item and Purchase Receipt Item; Carry In/Operation Progress on Job Card Time Log | Native permissions check child-row Links too. Site restrictions on these Kanban targets can affect their parent documents. No child-row permission is bypassed. |
| Native Process Certificate Set Inventory Dimension generated at migration | Site User Permissions on the Certificate Set DocType can affect generated Link fields. Dimension scope, stock validation and its permission metadata are unchanged. |
| Employee Links inside app-owned DocTypes | 121 Employee Links across 66 parent/child DocTypes; 107 are read-only. These include both audit actors and real assignment/access subjects, so read-only alone is not a safe exemption rule. See examples below. No blanket change was made. |

Examples requiring a distinct policy if the site applies Employee User Permissions to these
Kanban documents:

- **Task / Process Task:** Assigned Employee is an assignment subject; Started By, Completed By
  and Verified By are audit actors. Applying an Employee self-restriction to all these Links can
  prevent a supervisor reading another operator's work or a task whose later audit fields are blank.
- **Delivery Trip / assistants:** Driver and assistant Employee are assignment subjects; route
  starter, stop completer, cancellation actor and assistant assigner are audit actors. Do not
  exempt assignment fields without reviewing the trip/team access rules.
- **Dispatch Plan / Movement Manifest / Delivery Session / Return Case:** their creator,
  approval, reservation, loading, delivery, receipt, cancellation and QC actor Links can cause
  similar document-level rejection where Employee User Permissions apply.
- **Operator Profile / Employee Competency / Job Participation / crew records:** Employee may
  be the subject of authorization or personnel access. These fields are not covered by the
  operator-audit exemption on native ERP documents.

These are policy-sensitive potential risks, not a claim that each workflow currently fails.
The reported normal-ERP Employee failure and structurally reproduced counterpart Company list
failure are fixed at their four field placements. Owning Company, other business Company fields,
Customer, Supplier, Warehouse, Item, Batch, document-specific, role and controller checks remain
in force. Resolve any additional field named by an actual rejection separately;
do not remove Employee User Permissions or disable strict permissions globally.

## Automated checks and their limits

Run from the app checkout:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest cfg_kanban.tests.test_installation cfg_kanban.tests.test_operator_audit_permissions cfg_kanban.tests.test_custom_credit_notes -v
```

- `test_installation`: native API doubles exercise fresh install, existing-field upgrade,
  conflicting Property Setter repair, correct manual customization, repeat migration,
  restricted repair scope, invalid metadata rejection and unrelated-field preservation.
- `test_operator_audit_permissions`: when Frappe is installed, runs actual native role,
  controller, document and Link User Permission evaluation with in-memory metadata and
  mocked permission/configuration lookup. Without Frappe, these cases are explicitly skipped.
  Covers both native document types, blank/populated operators, the original rejection,
  role denial, owning Company and party denial, Item/Batch/Warehouse child-row denial,
  other Company/Employee fields, Employee record access, document-specific denial and counterpart
  audit data with owning Company restrictions.
- The list-query cases in the same module execute actual native permission predicate builders
  and evaluate their SQL using isolated in-memory SQLite fixture tables. They reproduce an empty
  list with the old counterpart/operator metadata and verify normal and Kanban rows in the allowed
  Company, exclusion of other-company rows, party/document-specific filters and native Read denial.
- The existing custom Credit Note tests continue to cover its optional installer path; its
  unrelated accounting behavior is unchanged.

The checks do not install/migrate a real site, query real User Permissions, exercise a real
Frappe/MariaDB list view, create or submit a real ERP document, or verify the production user's access.
Record exact offline totals and any native-source harness result separately from site tests.

### Offline result, 24 November 2026

- Targeted installer, audit-permission, custom Credit Note, DocType schema, stock-identity
  and purchase-replenishment run: **173 cases, 151 passed, 22 skipped**. Twenty-one skipped
  cases require installed Frappe; the other is an existing Frappe-dependent purchase test.
- Separately executed the same 21 document/list permission cases against the actual upstream
  permission functions from Frappe **15.94.0** and **15.69.2** using temporary harnesses:
  **21 passed on each version**. Metadata/configuration lookup was replaced by the explicit
  fixtures used by the checked-in tests; list SQL was evaluated with in-memory SQLite tables.
  This is native-source behavior, not a site or MariaDB test.
- A broader attempt including `test_logistics_foundation` could not import that module
  because Frappe is not installed locally. The unchanged baseline has the identical import
  failure. That module was excluded from the successful targeted run; it is not reported as
  passing or fixed by this change.

## Site acceptance (administrator performs; not run by Codex)

Use an isolated test site first, retaining the site's existing role and User Permission
records. Do not weaken production restrictions to make this test pass.

| Check | Expected result | Recorded result |
| --- | --- | --- |
| Deploy reviewed revision and run native migration | Operator Employee and Counterpart Company Links on both DN and PR are read-only, Ignore User Permissions = 1; standard Company is unchanged | Not run |
| Same migration with prior manual exemption | Effective setting remains enabled; no unrelated customizations change | Not run |
| Strict Employee-restricted user with DN/PR Create rights opens new documents directly in ERPNext | No operator-field Employee-empty rejection; other configured checks still apply | Not run |
| Ordinary saved DN/PR with no operator | Can open with otherwise sufficient rights | Not run |
| Kanban DN/PR requested by another Employee | Actual operator remains unchanged; this audit field does not restrict access | Not run |
| User without native Create/Read/Submit rights | Relevant native action remains denied | Not run |
| Outside allowed owning Company, Customer/Supplier, Warehouse, Item or Batch | Existing document/child checks remain denied where configured | Not run |
| Direct Employee access or another business Employee Link | Existing Employee restriction remains enforced | Not run |
| List view, linked navigation, print and normal ERP insert/submit | Native behavior confirmed with real metadata, User Permissions and controller hooks | Not run |
| Applicable strict Company permission with blank Counterpart Company | Allowed owning-Company rows appear in DN/PR lists and can be opened; other-company rows remain excluded | Not run |
| Counterpart Company outside allowed Company list | An allowed owning-Company DN/PR is visible independently of its counterpart; direct access to the counterpart Company remains restricted | Not run |

**Deployed revision:** pending. **Tester/date/evidence:** pending. No production access or
broader package acceptance is established by offline results.
