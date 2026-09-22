import io

import pymupdf
from PIL import Image

from services.emediplan_service import EMEDIPLAN_PREFIX

PDF_RENDER_DPI = 300


def _looks_like_pdf(raw_bytes):
    return raw_bytes[:5] == b"%PDF-"


def _images_from_pdf(raw_bytes):
    images = []
    zoom = PDF_RENDER_DPI / 72

    with pymupdf.open(stream=raw_bytes, filetype="pdf") as document:
        matrix = pymupdf.Matrix(zoom, zoom)

        for page in document:
            pixmap = page.get_pixmap(matrix=matrix)
            mode = "RGB" if pixmap.n < 4 else "RGBA"
            images.append(Image.frombytes(mode, [pixmap.width, pixmap.height], pixmap.samples))

    return images


def _looks_like_emediplan_payload(text):
    return text.startswith(EMEDIPLAN_PREFIX) or text.startswith("{")


def extract_emediplan_payload_from_file(raw_bytes, content_type=None):
    if not raw_bytes:
        raise ValueError("No file content provided")

    try:
        from pyzbar.pyzbar import decode as decode_qr_codes
    except ImportError as ex:
        raise ValueError("QR-Decoding ist auf diesem System nicht verfügbar: zbar-Bibliothek fehlt") from ex

    is_pdf = _looks_like_pdf(raw_bytes) or content_type == "application/pdf"

    try:
        images = _images_from_pdf(raw_bytes) if is_pdf else [Image.open(io.BytesIO(raw_bytes))]
    except Exception as ex:
        raise ValueError(f"Could not read file as {'PDF' if is_pdf else 'image'}: {ex}")

    for image in images:
        for symbol in decode_qr_codes(image):
            text = symbol.data.decode("utf-8", errors="ignore").strip()

            if _looks_like_emediplan_payload(text):
                return text.encode("utf-8")

    raise ValueError(
        "Kein eMediplan erkannt: keine eMediplan-QR-Codierung in der Datei gefunden "
        "(No eMediplan QR code found in the provided file)"
    )


def resolve_emediplan_payload(raw_bytes, content_type=None):
    """Accepts a raw CHMED16A/JSON payload as-is, or falls back to reading
    an embedded QR code when the bytes are a PDF/image instead of text."""
    if not raw_bytes:
        raise ValueError("No eMediplan payload provided")

    try:
        text = raw_bytes.decode("utf-8").strip()
    except UnicodeDecodeError:
        text = ""

    if _looks_like_emediplan_payload(text):
        return raw_bytes

    return extract_emediplan_payload_from_file(raw_bytes, content_type)
