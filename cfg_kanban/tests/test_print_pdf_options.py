"""Fixed-media PDF contract; native rendering/site acceptance are separate checks."""
import json
import re
import unittest
from pathlib import Path

PRINT_FORMATS = Path(__file__).resolve().parents[1] / 'cfg_kanban' / 'print_format'
FIXED_MEDIA = {
    'cfg_kanban_standard_card': ('148mm', '105mm'),
    'cfg_kanban_handling_unit_tag': ('45mm', '250mm'),
    'cfg_kanban_bin_slot_label_50x30': ('50mm', '30mm'),
    'cfg_kanban_bin_slot_label_100x50': ('100mm', '50mm'),
    'cfg_kanban_bin_slot_card_a6': ('148mm', '105mm'),
}


def format_document(folder):
    return json.loads((PRINT_FORMATS / folder / (folder + '.json')).read_text())


def declared_pdf_options(css):
    # Only bare .print-format rules become Frappe PDF options; @page is browser CSS.
    options = {}
    for block in re.findall(r'(?<![\w.-])\.print-format\s*\{([^{}]*)\}', css):
        for declaration in block.split(';'):
            name, colon, value = declaration.partition(':')
            if colon:
                options[name.strip()] = value.split('!')[0].strip()
    return options


class TestPrintPdfOptions(unittest.TestCase):
    def test_app_formats_never_send_custom_as_a_named_wkhtmltopdf_size(self):
        for path in sorted(PRINT_FORMATS.glob('*/*.json')):
            with self.subTest(format=path.stem):
                options = declared_pdf_options(json.loads(path.read_text()).get('css', ''))
                self.assertNotEqual(options.get('page-size', '').lower(), 'custom',
                    'wkhtmltopdf rejects --page-size Custom; use explicit dimensions')

    def test_fixed_media_have_exact_pdf_dimensions_and_explicit_orientation(self):
        for folder, dimensions in FIXED_MEDIA.items():
            with self.subTest(format=folder):
                options = declared_pdf_options(format_document(folder)['css'])
                self.assertEqual((options.get('page-width'), options.get('page-height')), dimensions)
                self.assertEqual(options.get('orientation'), 'Portrait',
                    'Explicit dimensions must not rotate with site-wide landscape defaults')

    def test_browser_and_pdf_physical_sizes_match(self):
        for folder, dimensions in FIXED_MEDIA.items():
            with self.subTest(format=folder):
                css = format_document(folder)['css']
                sizes = re.findall(r'@page\s*\{\s*size\s*:\s*([^;}]+)', css)
                self.assertEqual(sizes, [' '.join(dimensions)])

    def test_fixed_media_override_each_pdf_margin_explicitly(self):
        for folder in FIXED_MEDIA:
            with self.subTest(format=folder):
                options = declared_pdf_options(format_document(folder)['css'])
                for side in ('top', 'bottom', 'left', 'right'):
                    self.assertEqual(options.get('margin-'+side), '0mm',
                        'Frappe does not expand margin shorthand into PDF options')
                self.assertEqual(options.get('min-height'), '0',
                    'Small media must not inherit the standard document minimum height')

    def test_fixed_media_do_not_depend_on_grid_or_flex_in_old_qt(self):
        for folder in FIXED_MEDIA:
            with self.subTest(format=folder):
                self.assertNotRegex(format_document(folder)['css'],
                    r'display\s*:\s*(?:inline-)?(?:grid|flex)\b')

    def test_fixed_formats_keep_their_existing_content_and_trace_identity(self):
        for folder in FIXED_MEDIA:
            with self.subTest(format=folder):
                doc = format_document(folder)
                self.assertEqual(doc['disabled'], 0)
                self.assertEqual(doc['standard'], 'Yes')
                self.assertEqual(doc['raw_printing'], 0)
                if folder == 'cfg_kanban_standard_card':
                    self.assertEqual(doc['doc_type'], 'CFG Kanban Card')
                    self.assertIn('get_card_print_context(doc.kanban_master)', doc['html'])
                    self.assertIn('get_qr_svg', doc['html'])
                else:
                    self.assertEqual(doc['doc_type'], 'CFG Kanban Handling Unit')
                    self.assertIn('get_code128_svg(doc.handling_unit_id', doc['html'])


if __name__ == '__main__':
    unittest.main()
