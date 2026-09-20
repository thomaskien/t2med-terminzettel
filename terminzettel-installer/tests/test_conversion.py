from pathlib import Path
import gzip
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from test_runtime import app


def pdf_fixture(content=None):
    content = content or (b"BT /F1 11 Tf 50 780 Td (TERMINE) Tj 0 -20 Td "
               b"(Testperson Alpha) Tj 0 -20 Td (Terminzeitpunkt              Termintyp) Tj "
               b"0 -20 Td (Do. 17.09.2026, 09:00 Kontrolle) Tj ET\n")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               ("<< /Length %d >>\nstream\n" % len(content)).encode() + content + b"endstream"]
    data, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(("%d 0 obj\n" % number).encode() + obj + b"\nendobj\n")
    start = len(data)
    data.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets:
        data.extend(("%010d 00000 n \n" % offset).encode())
    data.extend(("trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % start).encode())
    return bytes(data)


def postscript_fixture():
    return b"%!PS-Adobe-3.0\n/Helvetica findfont 11 scalefont setfont\n50 780 moveto (TERMINE) show\n50 760 moveto (Testperson Alpha) show\n50 740 moveto (Terminzeitpunkt              Termintyp) show\n50 720 moveto (Do. 17.09.2026, 09:00 Kontrolle) show\nshowpage\n"


class ConversionTests(unittest.TestCase):
    def setUp(self):
        original = app.run_checked

        def host_command(args, **kwargs):
            return original([shutil.which(args[0]) or args[0], *args[1:]], **kwargs)

        patcher = patch.object(app, "run_checked", side_effect=host_command)
        patcher.start()
        self.addCleanup(patcher.stop)

    @unittest.skipUnless(shutil.which("pdftotext"), "pdftotext fehlt")
    def test_real_pdf(self):
        text = app.extract_text(pdf_fixture(), {})
        ticket = app.parse_t2med(text)
        self.assertEqual(ticket.patient, "Testperson Alpha")
        self.assertEqual(len(ticket.appointments), 1)

    @unittest.skipUnless(shutil.which("gs") and shutil.which("pdftotext"), "Ghostscript/Poppler fehlen")
    def test_real_postscript(self):
        try:
            subprocess.run(["gs", "--version"], check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("Lokales Ghostscript nicht ausführbar")
        with tempfile.TemporaryDirectory() as directory, patch.object(app, "WORK", Path(directory)):
            ticket = app.parse_t2med(app.extract_text(postscript_fixture(), {}))
            self.assertEqual(len(ticket.appointments), 1)
            self.assertEqual(list(Path(directory).iterdir()), [])

    @unittest.skipUnless(shutil.which("gs") and shutil.which("pdftotext"), "Ghostscript/Poppler fehlen")
    def test_mac_generic_postscript(self):
        try:
            subprocess.run(["gs", "--version"], check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("Lokales Ghostscript nicht ausführbar")
        source = gzip.decompress((Path(__file__).parent / "fixtures/mac-generic-postscript.ps.gz").read_bytes())
        with tempfile.TemporaryDirectory() as directory, patch.object(app, "WORK", Path(directory)):
            ticket = app.parse_t2med(app.extract_text(source, {}))
            self.assertEqual(ticket.patient, "Testperson Alpha")
            self.assertEqual(len(ticket.appointments), 1)
            self.assertEqual(ticket.appointments[0].date, "17.09.2026")


if __name__ == "__main__":
    unittest.main()
