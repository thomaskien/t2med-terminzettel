import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_runtime import app, TEXT
from test_conversion import pdf_fixture


def image_pdf_fixture(source=None):
    """Synthetic text converted to a bitmap, matching the T2med Mac print path."""
    from PIL import Image
    image = subprocess.run(['pdftoppm', '-singlefile', '-scale-to', '2500', '-gray', '-png', '-'],
                           input=source or pdf_fixture(), capture_output=True, check=True).stdout
    output = io.BytesIO()
    with Image.open(io.BytesIO(image)) as page:
        page.convert('RGB').save(output, format='PDF', resolution=300)
    return output.getvalue()


class OcrTests(unittest.TestCase):
    def test_text_pdf_does_not_invoke_ocr(self):
        with patch.object(app, 'run_checked', return_value=TEXT.encode()) as run:
            self.assertEqual(app.extract_text(b'%PDF-test', {}), TEXT)
        self.assertEqual(run.call_count, 1)

    def test_disabled_ocr_has_clear_error(self):
        with patch.object(app, 'run_checked', return_value=b'\f') as run:
            with self.assertRaisesRegex(app.TicketError, 'Texterkennung ist deaktiviert'):
                app.extract_text(b'%PDF-test', {'input': {'ocr_if_needed': False}})
        self.assertEqual(run.call_count, 1)

    def test_multipage_image_pdf_is_not_truncated(self):
        with patch.object(app, 'run_checked', side_effect=[b'\f\f', b'Pages: 2\n']) as run:
            with self.assertRaisesRegex(app.TicketError, 'genau eine PDF-Seite'):
                app.extract_text(b'%PDF-test', {})
        self.assertEqual(run.call_count, 2)

    def test_ocr_pipes_data_and_keeps_ram_temp_directory(self):
        with patch.object(app, 'run_checked', side_effect=[b'\f', b'Pages: 1\n', b'png', b'ocr-pdf', TEXT.encode()]) as run:
            self.assertEqual(app.extract_pdf_text('/run/terminzettel/work/input.pdf', {}, temp_dir='/run/terminzettel/work'), TEXT)
        for call in run.call_args_list:
            self.assertEqual(call.kwargs['temp_dir'], '/run/terminzettel/work')
        self.assertEqual(run.call_args_list[3].kwargs['input_bytes'], b'png')
        self.assertEqual(run.call_args_list[4].kwargs['input_bytes'], b'ocr-pdf')

    def test_ocr_wrong_weekday_is_rejected(self):
        with patch.object(app, 'run_checked', side_effect=[b'', b'Pages: 1\n', b'png', b'pdf', TEXT.replace('Do.', 'Fr.').encode()]):
            with self.assertRaisesRegex(app.TicketError, 'Wochentag und Datum'):
                app.extract_text(b'%PDF-test', {})

    def test_ocr_without_text_is_rejected(self):
        with patch.object(app, 'run_checked', side_effect=[b'', b'Pages: 1\n', b'png', b'pdf', b'\f']):
            with self.assertRaisesRegex(app.TicketError, 'keinen lesbaren Text'):
                app.extract_text(b'%PDF-test', {})

    def test_missing_ocr_dependency_has_fixed_error(self):
        with patch.object(app, 'run_checked', side_effect=[b'', b'Pages: 1\n', b'png', app.TicketError('Dateiumwandlung fehlgeschlagen.')]):
            with self.assertRaisesRegex(app.TicketError, 'Tesseract und das deutsche Sprachpaket'):
                app.extract_text(b'%PDF-test', {})


class RealOcrTests(unittest.TestCase):
    def setUp(self):
        if not all(shutil.which(tool) for tool in ['pdftotext', 'pdftoppm', 'pdfinfo', 'tesseract']):
            self.skipTest('OCR tools fehlen')
        languages = subprocess.run(['tesseract', '--list-langs'], capture_output=True, check=True).stdout.decode().splitlines()
        if 'deu' not in languages:
            self.skipTest('Deutsches OCR-Sprachpaket fehlt')
        original = app.run_checked
        def host_command(args, **kwargs):
            return original([shutil.which(args[0]) or args[0], *args[1:]], **kwargs)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        for item in [patch.object(app, 'WORK', Path(self.directory.name)),
                     patch.object(app, 'run_checked', side_effect=host_command)]:
            item.start()
            self.addCleanup(item.stop)

    def check_image(self, pdf, expected):
        source = image_pdf_fixture(pdf)
        self.assertFalse(subprocess.run(['pdftotext', '-', '-'], input=source, capture_output=True, check=True).stdout.strip())
        actual = app.parse_t2med(app.extract_text(source, {}))
        self.assertEqual(actual, expected)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_real_image_pdf_matches_text_pdf(self):
        self.check_image(pdf_fixture(), app.parse_t2med(TEXT))

    def test_five_appointments_multiline_type_and_centered_footer(self):
        lines = [(50, 780, 'TERMINE'), (50, 750, 'Testperson Alpha'),
                 (50, 720, 'Terminzeitpunkt'), (250, 720, 'Termintyp'),
                 (50, 690, 'Mo. 21.09.2026, 09:00'), (250, 690, 'Kontrolle'),
                 (250, 675, 'mit Beratung'),
                 (50, 640, 'Di. 22.09.2026, 10:15'), (250, 640, 'Labor'),
                 (50, 600, 'Mi. 23.09.2026, 11:30'), (250, 600, 'Impfung'),
                 (50, 560, 'Do. 24.09.2026, 12:45'), (250, 560, 'Kontrolle'),
                 (50, 520, 'Fr. 25.09.2026, 13:00'), (250, 520, 'Beratung'),
                 (290, 420, 'Praxis Beispiel'), (300, 405, 'Musterstadt')]
        content = b''.join(f'BT /F1 11 Tf {x} {y} Td ({text}) Tj ET\n'.encode() for x, y, text in lines)
        pdf = pdf_fixture(content)
        expected = app.parse_t2med(app.extract_text(pdf, {}))
        self.assertEqual(len(expected.appointments), 5)
        self.assertEqual(expected.appointments[0].kind, 'Kontrolle mit Beratung')
        self.assertEqual(expected.appointments[-1].kind, 'Beratung')
        self.check_image(pdf, expected)


if __name__ == '__main__':
    unittest.main()
