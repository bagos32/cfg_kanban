"""Optional real wkhtmltopdf layout/scan regression; no ERP or database calls.

Install test-only jinja2, pyqrcode, pdfkit, pypdf, Pillow, zxing-cpp. Set
CFG_TEST_WKHTMLTOPDF to a patched-Qt binary when it is not on PATH.
"""
import ast
import html
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

APP_ROOT = Path(__file__).resolve().parents[1]
FORMAT_ROOT = APP_ROOT / 'cfg_kanban' / 'print_format'
WKHTMLTOPDF = os.environ.get('CFG_TEST_WKHTMLTOPDF') or shutil.which('wkhtmltopdf')
PDFTOPPM = shutil.which('pdftoppm')
DEPENDENCIES = all(importlib.util.find_spec(name) for name in
                   ('jinja2', 'pyqrcode', 'pdfkit', 'pypdf', 'PIL', 'zxingcpp'))
MEDIA = {
    'cfg_kanban_bin_slot_label_100x50': (100, 50, 1, True),
    'cfg_kanban_bin_slot_label_50x30': (50, 30, 1, False),
    'cfg_kanban_bin_slot_card_a6': (148, 105, 1, True),
    'cfg_kanban_handling_unit_tag': (45, 250, 1, True),
    'cfg_kanban_standard_card': (148, 105, 2, True),
}
# Relevant inherited print defaults; app CSS must override these without cropping.
BASE_CSS = '''*{box-sizing:border-box}body{font-size:10pt}
.print-format{padding:.75in;max-width:8.3in;min-height:11.69in;margin:auto;line-height:1.6}
.print-format table{width:100%;margin-bottom:20px}.print-format td{padding:5px}
.print-format dl{margin:0 0 20px}.print-format dt{font-weight:bold}.print-format dd{margin-left:0}
.print-format-gutter{padding:30px 0}'''


def print_helpers():
    tree = ast.parse((APP_ROOT / 'services' / 'printing.py').read_text())
    namespace = {'html': html, 'frappe': SimpleNamespace(throw=lambda message:
        (_ for _ in ()).throw(ValueError(message)))}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_CODE128' for t in node.targets):
            namespace['_CODE128'] = ast.literal_eval(node.value)
        if isinstance(node, ast.FunctionDef) and node.name in ('get_qr_svg', 'get_code128_svg'):
            exec(compile(ast.Module(body=[node], type_ignores=[]), 'printing.py', 'exec'), namespace)
    return namespace


def render_format(folder, directory, long_text=False):
    from jinja2 import Environment, select_autoescape
    import pdfkit
    from cfg_kanban.tests.test_print_pdf_options import declared_pdf_options
    document = json.loads((FORMAT_ROOT / folder / (folder + '.json')).read_text())
    helpers = print_helpers()
    doc = dict(handling_unit_id='HOPPER_3', reusable_container_role='Production Output Container',
        tag_kind='Reusable Container', identity_state='Active', wip_bin_state='', state='Issued',
        container_reference='HOPPER 3', current_warehouse='F02 - FZD', current_operation='Packing',
        handling_unit_type='Hopper', movement_state='Loaded', total_units=0,
        inventory_company='FZD', kanban_cycle='CYCLE-001', work_order='WO-001',
        print_revision=1, print_count=1, last_printed_on='2026-11-18', last_printed_by='Operator',
        item_code='WR1,5KG', kanban_master='MASTER', card_number='PACK-LOAD', kanban_qty=5,
        card_type='Process Kanban', revision=1, uuid='CFG-CARD-TEST-001', qr_code='CFG-CARD-TEST-001')
    if long_text:
        doc.update(container_reference='PACKING LINE 02 / HOLDING TANK HOPPER THREE',
            current_warehouse='FINISHED PRODUCTION HOLDING AREA - FZD',
            current_operation='Packing and Final Product Labelling')
    context = SimpleNamespace(control_type='Production', stock_uom='Nos', revision=1,
        source_warehouse='F02 - FZD', destination_warehouse='Finished - FZD',
        route=[SimpleNamespace(sequence=1, operation='Rinse', workstation='RINSE', handoff_mode='Digital Quantity Handoff'),
               SimpleNamespace(sequence=2, operation='Pack', workstation='PACK', handoff_mode='Full Batch Handoff')])
    env = Environment(autoescape=select_autoescape(default=True))
    template = env.from_string(document['html'])
    content = template.render(doc=doc, get_qr_svg=helpers['get_qr_svg'],
        get_code128_svg=helpers['get_code128_svg'], get_card_print_context=lambda name: context)
    source = ('<!doctype html><html><head><meta charset="utf-8"><style>'+BASE_CSS+
        document['css']+'</style></head><body><div class="print-format-gutter"><div class="print-format">'+
        content+'</div></div></body></html>')
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    output = directory / (folder + ('-long' if long_text else '') + '.pdf')
    output.with_suffix('.html').write_text(source)
    options = {'page-size':'A4', 'orientation':'Landscape',
        'margin-top':'15mm', 'margin-bottom':'15mm', 'margin-left':'15mm', 'margin-right':'15mm',
        'disable-javascript':'', 'disable-local-file-access':'', 'disable-smart-shrinking':'', 'quiet':'', 'encoding':'UTF-8'}
    for name, value in declared_pdf_options(document['css']).items():
        if name in ('orientation','page-size','page-width','page-height',
                    'margin-top','margin-bottom','margin-left','margin-right'):
            options[name] = value
    pdfkit.from_string(source, str(output), options=options,
        configuration=pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF))
    return output, doc


@unittest.skipUnless(WKHTMLTOPDF and PDFTOPPM and DEPENDENCIES,
    'requires wkhtmltopdf, pdftoppm and test-only PDF/template/barcode dependencies')
class TestPrintPdfRendering(unittest.TestCase):
    def assert_rendered(self, folder, directory, long_text=False):
        from pypdf import PdfReader
        from PIL import Image
        import zxingcpp
        pdf, doc = render_format(folder, directory, long_text)
        width, height, count, has_qr = MEDIA[folder]
        reader = PdfReader(pdf)
        self.assertEqual(len(reader.pages), count, str(pdf))
        for page in reader.pages:
            self.assertAlmostEqual(float(page.mediabox.width)*25.4/72, width, delta=.6)
            self.assertAlmostEqual(float(page.mediabox.height)*25.4/72, height, delta=.6)
        identity = doc['uuid'] if folder == 'cfg_kanban_standard_card' else doc['handling_unit_id']
        text = ''.join(page.extract_text() or '' for page in reader.pages)
        self.assertIn(identity, text.replace('\t', '').replace('\n', ''))
        prefix = str(pdf.with_suffix(''))
        subprocess.run([PDFTOPPM, '-r', '240', '-png', str(pdf), prefix], check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        codes = []
        for png in sorted(pdf.parent.glob(pdf.stem+'-*.png')):
            with Image.open(png) as picture:
                codes.extend(zxingcpp.read_barcodes(picture))
        if has_qr:
            self.assertTrue(any(code.text == identity and code.format == zxingcpp.BarcodeFormat.QRCode
                for code in codes), 'Complete QR must decode to the original identity: '+str(pdf))
        if folder != 'cfg_kanban_standard_card':
            self.assertTrue(any(code.text == identity and code.format == zxingcpp.BarcodeFormat.Code128
                for code in codes), 'Complete Code 128 must decode to the original identity: '+str(pdf))
        if folder == 'cfg_kanban_standard_card':
            self.assertIn('HANDLING AND EXCEPTION INSTRUCTIONS', ' '.join(reader.pages[1].extract_text().split()))
        return pdf

    def test_all_fixed_media_render_complete_scannable_labels(self):
        with tempfile.TemporaryDirectory(prefix='cfg-print-') as directory:
            for folder in MEDIA:
                with self.subTest(format=folder):
                    self.assert_rendered(folder, directory)

    def test_long_location_names_do_not_split_labels_or_damage_codes(self):
        with tempfile.TemporaryDirectory(prefix='cfg-print-long-') as directory:
            for folder in ('cfg_kanban_bin_slot_label_100x50', 'cfg_kanban_bin_slot_card_a6'):
                with self.subTest(format=folder):
                    self.assert_rendered(folder, directory, long_text=True)


if __name__ == '__main__':
    unittest.main()
