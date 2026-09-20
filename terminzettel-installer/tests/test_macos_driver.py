from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_conversion import pdf_fixture

PPD = Path(__file__).resolve().parents[2] / "macos/Terminzettel-PDF.ppd"


@unittest.skipUnless(sys.platform == "darwin", "Requires the macOS print filters")
class MacDriverTests(unittest.TestCase):
    def test_pdf_is_sent_without_postscript_or_pdf_reencoding(self):
        # Both PDF MIME types must reach the IPP backend without a converter.
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "synthetic.pdf"
            source.write_bytes(pdf_fixture())
            for mime in ("application/pdf", "application/vnd.cups-pdf"):
                with self.subTest(mime=mime):
                    result = subprocess.run([
                        "/usr/sbin/cupsfilter", "--list-filters", "-e", "-p", str(PPD),
                        "-i", mime, "-m", "printer/Terminzettel", str(source),
                    ], capture_output=True, check=True, timeout=30)
                    self.assertEqual(result.stdout.strip(), b"")


if __name__ == "__main__":
    unittest.main()
