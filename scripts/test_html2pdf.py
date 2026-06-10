import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("html2pdf.py")
spec = importlib.util.spec_from_file_location("html2pdf", SCRIPT)
html2pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(html2pdf)


class Html2PdfTests(unittest.TestCase):
    def test_build_page_url_percent_encodes_local_file_names(self):
        url = html2pdf.build_page_url(8765, Path("个人 简历.html"))

        self.assertEqual(
            url,
            "http://127.0.0.1:8765/%E4%B8%AA%E4%BA%BA%20%E7%AE%80%E5%8E%86.html",
        )


    def test_cli_defaults_to_vector_pdf_output(self):
        args = html2pdf.parse_args(["resume.html"])

        self.assertEqual(args.mode, "vector")
        self.assertEqual(args.width, 1400)


if __name__ == "__main__":
    unittest.main()
