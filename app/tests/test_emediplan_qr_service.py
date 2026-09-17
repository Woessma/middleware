import io
import unittest

import pymupdf
import qrcode
from PIL import Image

from services.emediplan_qr_service import extract_emediplan_payload_from_file


SAMPLE_PAYLOAD = "CHMED16A1H4sIAAAAAAAEAKtWyk0tLtHNSUxPzC22UkjOzytJTS7RUcpJAsoUAwAr69MtHAAAAA=="


def _qr_png_bytes(data):
    image = qrcode.make(data)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _pdf_bytes_with_qr(data):
    qr_image = qrcode.make(data).convert("RGB")
    buffer = io.BytesIO()
    qr_image.save(buffer, format="PNG")

    document = pymupdf.open()
    page = document.new_page()
    page.insert_image(page.rect, stream=buffer.getvalue())
    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


class EmediplanQrServiceTests(unittest.TestCase):
    def test_extracts_payload_from_qr_png(self):
        png_bytes = _qr_png_bytes(SAMPLE_PAYLOAD)

        result = extract_emediplan_payload_from_file(png_bytes, "image/png")

        self.assertEqual(result, SAMPLE_PAYLOAD.encode("utf-8"))

    def test_extracts_payload_from_pdf_page(self):
        pdf_bytes = _pdf_bytes_with_qr(SAMPLE_PAYLOAD)

        result = extract_emediplan_payload_from_file(pdf_bytes, "application/pdf")

        self.assertEqual(result, SAMPLE_PAYLOAD.encode("utf-8"))

    def test_raises_when_no_qr_code_present(self):
        blank_image = Image.new("RGB", (200, 200), color="white")
        buffer = io.BytesIO()
        blank_image.save(buffer, format="PNG")

        with self.assertRaises(ValueError):
            extract_emediplan_payload_from_file(buffer.getvalue(), "image/png")

    def test_raises_on_empty_content(self):
        with self.assertRaises(ValueError):
            extract_emediplan_payload_from_file(b"", "image/png")


if __name__ == "__main__":
    unittest.main()
