# Logistics stock identity acceptance

Local implementation and offline checks are not production acceptance. No site test is recorded
by this change. The owner performs commit/push/pull/migrate/build/cache/restart manually.

## Offline checks

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest cfg_kanban.tests.test_logistics_stock_identity -v
git diff --check
```

## Isolated-site scenarios — not run

Record exact site, deployed SHA, Frappe/ERPNext versions, tester/date and actual document names.

1. Start with certified, Batch-controlled raw material with tag expiry, Batch expiry, packing date,
   original Work Order/operation and issued certificate/media evidence. Prepare a new Manifest.
   Verify its immutable snapshot and the Certificate Set/Expiry shown on the scanner panel.
2. Direct warehouse transfer: verify both Stock Entry dimensions, exact Batch/serial values and
   native Stock Ledger balances at source/destination. The same tag retains all trace metadata;
   certificate issuance history is unchanged. Scan the received material into production and
   verify its actual configured certificate gate and native ERP availability.
3. Goods in Transit: repeat for source->transit and transit->destination, checking source AND
   target certificate dimensions on each native row. Repeat Dispatch Plan lorry loading.
4. Intercompany dispatch/receipt: verify exact Delivery Note/Purchase Receipt row mapping,
   certificate dimensions, Batch/serial bundles and native company stock, without changing
   certificate Company/Warehouse at issuance. Repeat native cancellation/recovery paths.
5. Logistics Quantity Bin: load a partial quantity, transfer/receive the bin, then start production
   using that exact fill. Verify inherited certificate evidence, original validity/revision,
   expiry, packing date, origin and exact quantity genealogy. Reject incompatible fill mixing.
6. Main/child split, controlled serial split, receipt repack and replacement: verify each newly
   activated stock identity retains proof. Repeat token retries. Test Do Not Inherit and Block
   Merge policies, insufficient/missing proof, expired certificates and revoked ancestors.
7. Reject different-set, different-expiry and different-provenance merges. A return to the
   original compatible source must conserve quantity and evidence without extending validity.
8. Strip/change dimensions on an ERP draft: submission must be blocked. Change source expiry,
   certificates or serial assignment after preparation: posting must require reconciliation.
9. Missing dimension schema, ambiguous certified untagged stock and certified legacy lines without
   snapshots must fail closed. A legacy submitted outward row missing dimensions must NOT be
   repaired by inventing receipt evidence. Verify ordinary uncertified transfers still work.
10. Complete scanner-only kiosk dispatch/receipt/split/bin paths, safe Cancel and error focus.

| Evidence | Result |
|---|---|
| Exact site / deployed SHA / ERPNext and Frappe versions | Not recorded |
| Tester/date | Not recorded |
| Direct / Goods in Transit / lorry loading | Not run |
| Intercompany / customer delivery / withdrawal | Not run |
| Production certificate gate after receipt | Not run |
| Bin/split/repack/replacement provenance | Not run |
| Rollback / retry / cancellation / concurrency | Not run |
| Scanner-only kiosk and focus | Not run |
| Stock Ledger / certificate / lineage document names | Not recorded |
| Accepted exceptions or deferred risks | Not recorded |
