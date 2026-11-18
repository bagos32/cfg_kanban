# Fixed-media Kanban PDF download regression

Prepared 2026-11-18 from base commit `4162554`. Live PDF rendering and printing are pending.

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

These checks construct options/commands only. wkhtmltopdf is unavailable locally: no PDF
was rendered, visually inspected or physically scanned, and no live site was queried.

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
