# E4C — Warehouse fulfilment and pickup acceptance

Development baseline: `fc889fa` (E4B). Prepared in the existing worktree on 20 November 2026.
The owner requested further development and specified that Pickup Acknowledgement must offer
recipient name, signature, or both during setup. Customer Site evidence adds to that minimum.
This document records development checks separately from native/live acceptance.

## Offline verification

- **289 Python tests passed**, including 32 E4C behavioral tests and the E4A/E4B/E3, Dispatch order
  quantities, schema, authorization, stock identity, repack and container-release suites.
- **149 UI checks passed:** E4C 20, E4A 18, E4B 35, Dispatch quantities 9, repack/release 58,
  Hopper lookup 3 and logistics metadata/printing 6.
- Python tests execute actual source functions with in-memory document, SQL, ERP and ledger doubles.
  UI checks execute the actual controller/dialog/dispatcher with RPC/UI/camera doubles; the retained
  E4B suite also uses storage/Web Lock doubles.
- Coverage includes one reservation hold during tagged/untagged handoff; exact line/source identity;
  same-token/reopened-session replay; authorization and source rejection; payload certificates/order
  links/UOM; partial-release rejection and explicit reset; native submit/proof callbacks; three
  acknowledgement modes; partial-bin retention/reversal; ordinary-container protection; scalar/table
  scanner inputs, paging, Tab/Enter, camera, cancellation and owner/focus guards.
- Syntax/JSON and whitespace checks passed. These checks do not prove native MariaDB locking,
  transaction rollback, ERP stock posting, Frappe table widgets, media, physical devices or migration.
- Local Python has no Frappe installation. The existing native `test_logistics_foundation` suite
  remains excluded locally and must run in a bench environment.

Focused checks:

```bash
python3 -B -m unittest cfg_kanban.tests.test_warehouse_fulfilment
node cfg_kanban/tests/test_warehouse_fulfilment_ui.cjs
```

## Site prerequisites / recorded evidence

Site, deployed SHA (`git log -1 --oneline`), tester/date, native DB isolation, Company, source
Warehouse, Dispatch Point/Profile/Plan, Customer Site, Sales Order/UOM, Stock Tags/containers,
Batch/printed expiry, original reservation ledgers, Delivery Sessions/Notes/proofs and ERP/HU balances:
**Not recorded**. No live E4C test or deployment was performed by this development run.

Use isolated test data. Prepare separate Direct Delivery and Pickup Profiles. Test Recipient Name,
Signature and Recipient Name and Signature, plus additional Site name/photo/GPS requirements.
Include tagged and untagged stock, a partial quantity bin, an ordinary mixed logistics container,
a Sales Order with a non-unit conversion factor, different-Company operators/stock and two terminals.

| Acceptance check | Required result | Site result |
|---|---|---|
| Migration/defaults | New fields/state options sync; existing vehicle Sessions remain vehicle; only eligible old warehouse readiness corrected; historical snapshots unchanged | Not run |
| Profile setup | Three pickup choices, revision capture, correct card/Company/source; no fake vehicle or mandatory Logistics Route | Not run |
| Queues | Prepared direct/pickup Plans appear at Dispatch Point/Site and can resume; completed warehouse Plan leaves active queue | Not run |
| Readiness/approval | Every line fully reserved; approval and operator responsibilities remain enforced | Not run |
| Company/source rejection | Disabled/group/wrong-Company Warehouse, changed Site address/customer, blocked Card and wrong operator all reject | Not run |
| Reservation handoff | Same HU stock/reserved/available before and after handoff; one delivery hold replaces the dispatch hold; no Stock Entry or Manifest | Not run |
| Untagged availability | Shared availability subtracts other dispatch/customer holds once; no fake identities or ledger; exact mandatory Batch | Not run |
| Tagged identity | Certificate set, printed expiry, Batch and serial eligibility preserved; expired stock blocked | Not run |
| Quantity/order | Exact prepared quantities and source rows; Sales Order remaining stock quantity, conversion/rate/currency enforced before posting | Not run |
| Draft/submission | Draft retains operational holds and stock; native submission alone consumes once and updates Plan delivery totals | Not run |
| Direct proof | Effective Site/Profile policy controls closure; required proof keeps Plan In Progress | Not run |
| Pickup name | Cannot auto-close from No Proof policy; attended name required; valid name closes without optional signature when Site allows | Not run |
| Pickup signature | Saved private signature required; name optional only when Site allows; no unattended/no-proof disposition | Not run |
| Pickup both/additional Site evidence | Both enforced; Site name/photo/GPS requirements cannot be bypassed by Profile choice | Not run |
| Signature/media | Existing private media registry, S3 evidence upload/save/view, ownership and submitted-proof protection work | Not run |
| Partial quantity bin | Deliver reserved portion, keep one loaded membership and exact remaining quantity; valid DN reversal restores the reservation without duplicate membership | Not run |
| Ordinary container | All current tags at full quantities; partial aggregate/unrelated current contents rejected; split/repack path remains available | Not run |
| Reset before ERP | Partial release cannot confirm; release all + reasoned empty cancellation returns Plan Approved with zero hold; reprepare required | Not run |
| Cancellation/amendment | No Plan/source release during fulfilment; native DN reversal restores once; submitted proof requires controlled return | Not run |
| Retry/refresh | Lost response and duplicate tabs resolve one Session/DN/proof; original token replay remains historical after reset; owner isolation retained | Not run |
| Native transactions | Concurrent start/confirm/cancel/source reservation, lock wait/deadlock rollback and failed second-half handoff leave no orphan Session, lost reservation or excess promise | Not run |
| Scanner/tablet | Global commands/catalogue; Plan/Site numbering; scalar/table input paging; Enter/Tab; Confirm/Cancel; focus; camera; signature; actual kiosk/full-screen | Not run |
| E3/E4A/E4B regression | Vehicle claim/loading and prepared/open-route delivery remain correct after migration and shared-dialog changes | Not run |

A failure during reservation conversion relies on the native request transaction rolling back both
release and reserve. The in-memory fixture does not simulate an actual database rollback. Include
an injected failure after source unreserve and another during the second allocation; inspect ERP,
HU/ledger/DA/source rows from a new transaction and record the evidence.

Run the bench-native logistics foundation checks and relevant native ERP tests on the authorized
test site. Record actual outcomes and deployed revision; do not turn offline passes into live
acceptance. E4A/E4B outstanding acceptance, Package L1 and the E5/E6 boundaries remain separate.
