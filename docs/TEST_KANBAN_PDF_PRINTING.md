# Fixed-media Kanban PDF download regression

Initial correction prepared 2026-11-18 from `4162554`, committed as `50ebc46`.
The layout follow-up below is based on `50ebc46`. Server reprint/physical scanning remain pending.

## Cause and correction

Frappe 15.69.2 reads PDF options from bare `.print-format` CSS rules. Its `prepare_options`
uses Custom to choose explicit dimensions but does not remove an already supplied
`page-size:Custom`. pdfkit therefore emits `--page-size Custom`, rejected by wkhtmltopdf
before rendering. Browser `@page` alone does not set those PDF options.

Source: [Frappe v15.69.2 PDF pipeline](https://github.com/frappe/frappe/blob/v15.69.2/frappe/utils/pdf.py).
The [wkhtmltopdf 0.12.6 converter](https://github.com/wkhtmltopdf/wkhtmltopdf/blob/0.12.6/src/lib/pdfconverter.cc)
uses explicit page width and height ahead of its named-size setting.

Remove the invalid named-size declaration from the five affected app formats, retaining
explicit width/height and using explicit Portrait orientation. With explicit dimensions,
Portrait leaves width and height in their declared order, including 148 × 105 mm A6.
This overrides an incoming Landscape PDF option without relying on global site settings.
HTML content, browser page sizes, printed identity payloads and print audits are unchanged.
No Frappe patch or global Print Settings mutation is included. Standard formats sync on
normal app migration. User-created/copied formats are outside that sync and must have
the same CSS correction reviewed separately.

| Format | PDF width × height |
| --- | --- |
| CFG Kanban Standard Card | 148 × 105 mm |
| CFG Kanban Handling Unit Tag | 45 × 250 mm |
| CFG Kanban Bin Slot Label 50x30 | 50 × 30 mm |
| CFG Kanban Bin Slot Label 100x50 | 100 × 50 mm |
| CFG Kanban Bin Slot Card A6 | 148 × 105 mm |

## Offline verification

`test_print_pdf_options` validates the five exact media sizes, explicit orientation,
browser/PDF size agreement, existing identity content and the absence of Custom as a
named wkhtmltopdf page size across app formats. Before the correction it failed ten
subcases; after correction all four tests pass.

Separately, unmodified `prepare_options`, `read_options_from_html` and
`get_print_format_styles` functions were extracted from the official Frappe v15.69.2
source and executed with real CSS/HTML parsers and pdfkit command construction. Framework
session, header/footer and private-image I/O were doubled. All five old formats emitted
invalid Custom with each of A4, Letter and Custom site defaults (15 cases). All five
corrected formats preserve exact dimensions and remove the invalid argument across the
same defaults, including an incoming Landscape option (15 cases).

The initial checks constructed options/commands only; wkhtmltopdf was unavailable at that
checkpoint. They did not establish visual layout or scan acceptance. The follow-up below
adds actual local rendering and barcode decoding. No live site was queried.

## Server acceptance pending

After the owner's normal migration/cache clearing, open Print View on a saved Kanban
Card, select CFG Kanban Standard Card, and download PDF. Confirm no server error, correct
front/back content and a 148 × 105 mm PDF page. Test each label format above using a saved
Handling Unit; confirm PDF dimensions and unchanged visible-code QR/Code 128 identities.
Check print preview/browser printing and physical output at 100% scale on matching media.
Scan the resulting identity labels. Verify long Item/Card/Warehouse text is not clipped.
Repeat with the normal Letter Head setting and without it. Check a user-created copy
separately if that is the chosen format. If an error remains, record the exact selected
Print Format and request PDF options rather than changing global paper size blindly.

Record deployed SHA, site, tester, date, selected formats, PDF dimensions/page count and
scan results before marking acceptance passed. Do not infer live success from offline tests.


## Layout follow-up: three-page HOPPER_3 label

The owner supplied HUT-2026-00089.pdf after `50ebc46`: three pages, each approximately
100.19 × 50.09 mm. Page 1 had the heading/identity, page 2 the facts/top of QR, page 3
the remaining QR. The paper size was fixed but the complete label was unusable.

Two remaining template defects were identified: Frappe's option reader does not expand
`margin:0` shorthand into individual PDF margin options, and the old Qt renderer does
not implement the CSS Grid layout used for label columns/rows. The previous 100 × 50 mm
template reproduced the same three-page failure locally.

All five fixed-media formats now specify all four zero PDF margins and clear inherited
document minimum height. Layout uses bounded positioning and compatible tables rather
than Grid/Flex. Barcode/QR data, visible identities, document metadata and print audit
logic remain unchanged. Full Trace Tag has an explicit WebKit rotation on its portrait
feed canvas. Standard Card puts each front/back in an equal inset sheet for duplex alignment.
The Bin Slot 100 × 50 facts use a three-row table rather than an unsupported grid list.

### Render verification

A temporary, unpacked official wkhtmltopdf 0.12.6 with patched Qt rendered real Jinja
templates and the app's actual QR/Code 128 helpers. No installer or site mutation was run.
Representative fixtures use HOPPER_3, Production Output Container, F02 - FZD, and a two-step
Production Card. The harness supplies inherited document styles, 15 mm incoming margins,
and incoming Landscape orientation to check the format overrides.

All four label/tag formats render on one page; Standard Card renders on two A6 pages.
Long bin/warehouse/operation names were also rendered in 100 × 50 and A6 labels. All seven
fixture PDFs were rendered to PNG and visually inspected. QR and Code 128 images decode
to their original identities using zxing-cpp; the 50 × 30 format deliberately has only
Code 128, and the Standard Card retains its existing internal Card QR payload.

`test_print_pdf_options` adds explicit-margin/minimum-height and legacy-renderer layout
contracts. `test_print_pdf_rendering` runs the seven fixture renders when wkhtmltopdf,
pdftoppm and its documented test-only Python dependencies are present, otherwise reports
an explicit skip. Set CFG_TEST_WKHTMLTOPDF to the test binary path when it is not on PATH.
Only the tests require these extra packages; the production app adds no dependency.

This is local rendering evidence on macOS wkhtmltopdf 0.12.6, not server acceptance on the
owner's 0.12.6.1 environment. Re-download all five deployed formats, check page counts,
layout/dimensions and scanner-only physical label readability at 100% scale. Record
actual results and deployed SHA. User-created copies need the same fixes separately.
