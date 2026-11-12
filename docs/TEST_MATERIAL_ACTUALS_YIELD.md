# Material actuals and Work Order yield acceptance

Offline behavior is supplemental; all live scenarios below are NOT RUN.

Local validation on 2026-11-12: 258 Python tests passed across actual material/yield,
BOM mapping, Material Run/Trace, cancellation, schema, runtime, logistics identity and
certificate regression suites. All 31 JavaScript checks passed (11 quantity/approval/
correction scanner checks, 6 FEFO approval checks and 14 certificate retry checks).
Operator-panel JavaScript syntax and Git whitespace checks passed. These tests use
local doubles and source contracts; no Frappe database, ERP posting, real browser/scanner
or live-site behavior was verified.

1. Configure a tracked 1 Kg raw/output-unit and 1 bag/output-unit BOM in the actual stock UOM.
   Scan 3 Kg and attempt output 5: reject without approval. Lower output remains supported.
2. Approve a Work Order-wide yield exception. Record approved 3-input/5-output, then operate
   another card/lane of that SAME Work Order. Check the approval and actual-use audit. A different
   Work Order remains unapproved. FEFO approval must not imply yield approval. Revoke and retry.
3. Scan/use 5 bags for 5 items. Settle: native Draft and adopted trace must both contain 5,
   including when ERP initially maps 3, when transfer_qty is blank and when UOM conversion differs.
4. Withdraw 5, use 3: remaining 2 is carried forward. Supervisor corrects recorded used 3 to 5
   before adoption, with reason. Trace then reflects 5. Reject used > withdrawn and hidden items.
5. Ordinary Draft trace allocated 3 from a source holding 5: supervisor corrects to 5, retains
   original cancelled allocation, native Draft input and replacement allocation both show 5.
   Failures restore original reservations transactionally. Reject another WO, posted ERP,
   invalid/revoked operator, insufficient stock, expired/incompatible source and wrong material.
6. Reuse correction token: same request is idempotent; changed payload is rejected. Race it
   against native submit, another correction and approval revocation. Check actual locks/rollback.
7. Test ordinary scanner Material Quantity, numbered materials in Progress and numbered
   operation/allocation correction, including NEXT_MATERIALS / PREVIOUS_MATERIALS
   paging beyond ten choices. Complete success/error/Cancel scanner-only in kiosk mode.
8. Test native customer MTO and fixed Cycle limits: yield approval never bypasses them.

Record exact site, deployed SHA, Frappe/ERPNext versions, tester/date, Stock Entry/Trace/Draw/
Progress/approval/Event names and accepted exceptions. No deployment or site test was performed
when preparing this document.
