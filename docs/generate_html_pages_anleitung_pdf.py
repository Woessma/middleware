"""Erzeugt eine bebilderte PDF-Anleitung fuer die HTML-Testseiten des Repos.

Bildquelle: docs/screenshots/*.png (per Playwright-Screenshot erzeugt).
Es wird kein externes PDF-Package benutzt, sondern ein minimaler PDF-Writer
nach dem Vorbild von generate_management_pdf.py / generate_infrastructure_pdf.py.
"""
from pathlib import Path
import struct
import textwrap
import zlib

BASE = Path('/opt/fhir-middleware/Woess_Fhir/fhir-middleware/docs')
SCREENSHOTS = BASE / 'screenshots'
LOGO_PATH = BASE / 'Designer.png'

PAGE_W = 595
PAGE_H = 842
MARGIN = 50
CONTENT_W = PAGE_W - 2 * MARGIN
LOGO_W = 70
LOGO_H = 47
LOGO_PX_W = 280  # downsampled logo resolution embedded in the PDF (keeps file size small)
LOGO_PX_H = 187


def pdf_escape(text: str) -> str:
    return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def downsample_rgb(raw: bytes, src_w: int, src_h: int, dst_w: int, dst_h: int) -> bytes:
    """Nearest-neighbor downsample of a raw RGB buffer to keep the embedded logo small."""
    out = bytearray(dst_w * dst_h * 3)
    for y in range(dst_h):
        src_y = min(src_h - 1, y * src_h // dst_h)
        src_row = src_y * src_w * 3
        dst_row = y * dst_w * 3
        for x in range(dst_w):
            src_x = min(src_w - 1, x * src_w // dst_w)
            src_off = src_row + src_x * 3
            dst_off = dst_row + x * 3
            out[dst_off:dst_off + 3] = raw[src_off:src_off + 3]
    return bytes(out)


def decode_png_rgb8_raw(path: Path):
    """Decode a non-interlaced 8-bit RGB PNG into (width, height, raw_rgb_bytes)."""
    data = path.read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise RuntimeError(f'Not a PNG file: {path}')

    pos = 8
    width = height = bit_depth = color_type = interlace = None
    idat = bytearray()

    while pos < len(data):
        chunk_len = struct.unpack('>I', data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]
        chunk_data = data[pos + 8:pos + 8 + chunk_len]
        pos += 12 + chunk_len

        if chunk_type == b'IHDR':
            width, height, bit_depth, color_type, _comp, _filt, interlace = struct.unpack('>IIBBBBB', chunk_data)
        elif chunk_type == b'IDAT':
            idat.extend(chunk_data)
        elif chunk_type == b'IEND':
            break

    if bit_depth != 8 or color_type != 2 or interlace != 0:
        raise RuntimeError(f'Unsupported PNG format in {path}: need RGB, 8-bit, non-interlaced')

    scan = zlib.decompress(bytes(idat))
    bpp = 3
    stride = width * bpp
    out = bytearray(height * stride)

    def paeth(a, b, c):
        p = a + b - c
        pa = abs(p - a)
        pb = abs(p - b)
        pc = abs(p - c)
        if pa <= pb and pa <= pc:
            return a
        if pb <= pc:
            return b
        return c

    src = 0
    for y in range(height):
        filt = scan[src]
        src += 1
        row = scan[src:src + stride]
        src += stride
        dst = y * stride
        prev = (y - 1) * stride

        for x in range(stride):
            left = out[dst + x - bpp] if x >= bpp else 0
            up = out[prev + x] if y > 0 else 0
            up_left = out[prev + x - bpp] if (y > 0 and x >= bpp) else 0
            rv = row[x]

            if filt == 0:
                v = rv
            elif filt == 1:
                v = (rv + left) & 0xFF
            elif filt == 2:
                v = (rv + up) & 0xFF
            elif filt == 3:
                v = (rv + ((left + up) // 2)) & 0xFF
            elif filt == 4:
                v = (rv + paeth(left, up, up_left)) & 0xFF
            else:
                raise RuntimeError('Unknown PNG filter type')

            out[dst + x] = v

    return width, height, bytes(out)


def add_text_block(cmds, x, y, lines, font='F1', size=11, leading=14):
    cmds.append('BT')
    cmds.append(f'/{font} {size} Tf')
    cmds.append(f'{x} {y} Td')
    first = True
    for line in lines:
        line = line.encode('latin-1', 'replace').decode('latin-1')
        if first:
            cmds.append(f'({pdf_escape(line)}) Tj')
            first = False
        else:
            cmds.append(f'0 -{leading} Td ({pdf_escape(line)}) Tj')
    cmds.append('ET')


def wrap(text, width=98):
    return textwrap.wrap(text, width=width) or ['']


class PdfBuilder:
    def __init__(self):
        self.objects = {}
        self.next_id = 1
        self.page_ids = []
        self.font_reg_id = self._reserve()
        self.font_bold_id = self._reserve()
        self.font_mono_id = self._reserve()
        self.objects[self.font_reg_id] = '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'
        self.objects[self.font_bold_id] = '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>'
        self.objects[self.font_mono_id] = '<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>'
        self.pages_id = self._reserve()
        self.catalog_id = self._reserve()

        logo_w, logo_h, logo_raw = decode_png_rgb8_raw(LOGO_PATH)
        logo_raw = downsample_rgb(logo_raw, logo_w, logo_h, LOGO_PX_W, LOGO_PX_H)
        self.logo_image_id = self.add_image(LOGO_PX_W, LOGO_PX_H, logo_raw)

    def _reserve(self):
        obj_id = self.next_id
        self.next_id += 1
        return obj_id

    def draw_header_logo(self, commands, image_ids):
        """Places the logo top-right on a page and registers it as the last XObject."""
        image_ids.append(self.logo_image_id)
        logo_index = len(image_ids) - 1
        logo_x = PAGE_W - MARGIN - LOGO_W
        logo_y = PAGE_H - 35 - LOGO_H
        commands.append('q')
        commands.append(f'{LOGO_W} 0 0 {LOGO_H} {logo_x} {logo_y} cm')
        commands.append(f'/Im{logo_index} Do')
        commands.append('Q')

    def add_image(self, width, height, raw_rgb):
        stream = zlib.compress(raw_rgb, level=9)
        image_id = self._reserve()
        header = (
            f'<< /Type /XObject /Subtype /Image /Width {width} /Height {height} '
            f'/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length {len(stream)} >>\n'
        ).encode('latin-1')
        self.objects[image_id] = header + b'stream\n' + stream + b'\nendstream'
        return image_id

    def add_page(self, commands, image_ids):
        stream = '\n'.join(commands).encode('latin-1')
        content_id = self._reserve()
        self.objects[content_id] = f'<< /Length {len(stream)} >>\nstream\n'.encode('latin-1') + stream + b'\nendstream'

        xobjects = ' '.join(f'/Im{i} {img_id} 0 R' for i, img_id in enumerate(image_ids))
        resources = (
            f'/Resources << /Font << /F1 {self.font_reg_id} 0 R /F2 {self.font_bold_id} 0 R '
            f'/F3 {self.font_mono_id} 0 R >> /XObject << {xobjects} >> >>'
        )
        page_id = self._reserve()
        self.objects[page_id] = (
            f'<< /Type /Page /Parent {self.pages_id} 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] '
            f'{resources} /Contents {content_id} 0 R >>'
        )
        self.page_ids.append(page_id)

    def write(self, out_path: Path):
        self.objects[self.catalog_id] = f'<< /Type /Catalog /Pages {self.pages_id} 0 R >>'
        kids = ' '.join(f'{pid} 0 R' for pid in self.page_ids)
        self.objects[self.pages_id] = f'<< /Type /Pages /Kids [{kids}] /Count {len(self.page_ids)} >>'

        pdf = bytearray(b'%PDF-1.4\n')
        offsets = {0: 0}
        for obj_id in sorted(self.objects.keys()):
            offsets[obj_id] = len(pdf)
            pdf += f'{obj_id} 0 obj\n'.encode('latin-1')
            body = self.objects[obj_id]
            pdf += (body if isinstance(body, bytes) else body.encode('latin-1'))
            pdf += b'\nendobj\n'

        xref_pos = len(pdf)
        max_id = max(self.objects.keys())
        pdf += f'xref\n0 {max_id + 1}\n'.encode('latin-1')
        pdf += b'0000000000 65535 f \n'
        for obj_id in range(1, max_id + 1):
            off = offsets.get(obj_id, 0)
            pdf += f'{off:010d} 00000 n \n'.encode('latin-1')

        pdf += (
            f'trailer\n<< /Size {max_id + 1} /Root {self.catalog_id} 0 R >>\n'
            f'startxref\n{xref_pos}\n%%EOF\n'
        ).encode('latin-1')

        out_path.write_bytes(pdf)


def layout_section(builder: PdfBuilder, title, subtitle, description_lines, screenshot_name):
    img_path = SCREENSHOTS / screenshot_name
    width, height, raw = decode_png_rgb8_raw(img_path)
    scale = CONTENT_W / width
    stride = width * 3

    # First page: title + description + as much of the image as fits.
    cmds = []
    add_text_block(cmds, MARGIN, 792, [title], font='F2', size=16, leading=18)
    if subtitle:
        add_text_block(cmds, MARGIN, 772, [subtitle], font='F3', size=10, leading=12)
    desc_y = 750 if subtitle else 764
    add_text_block(cmds, MARGIN, desc_y, description_lines, font='F1', size=10, leading=13)
    desc_bottom = desc_y - len(description_lines) * 13

    image_top_y = desc_bottom - 14
    first_avail_h = image_top_y - MARGIN
    cont_avail_h = PAGE_H - 2 * MARGIN

    y_cursor = 0  # source pixel row cursor
    remaining_px = height
    avail_pt = first_avail_h
    page_cmds = cmds
    page_top_y = image_top_y
    part = 1

    while remaining_px > 0:
        max_px_for_page = int(avail_pt / scale)
        crop_px = min(remaining_px, max_px_for_page) if max_px_for_page > 0 else remaining_px
        if crop_px <= 0:
            crop_px = remaining_px  # safety net, avoid infinite loop

        row_bytes = crop_px * stride
        crop_raw = raw[y_cursor * stride: y_cursor * stride + row_bytes]
        img_id = builder.add_image(width, crop_px, crop_raw)

        crop_h_pt = crop_px * scale
        img_y = page_top_y - crop_h_pt
        page_cmds.append('q')
        page_cmds.append(f'{CONTENT_W} 0 0 {crop_h_pt} {MARGIN} {img_y} cm')
        page_cmds.append('/Im0 Do')
        page_cmds.append('Q')

        image_ids = [img_id]
        builder.draw_header_logo(page_cmds, image_ids)
        builder.add_page(page_cmds, image_ids)

        y_cursor += crop_px
        remaining_px -= crop_px
        part += 1

        if remaining_px > 0:
            page_cmds = []
            add_text_block(page_cmds, MARGIN, 792, [f'{title} (Fortsetzung {part - 1})'], font='F2', size=13, leading=16)
            page_top_y = 792 - 24
            avail_pt = cont_avail_h - 24
        else:
            break


PAGES = [
    dict(
        out_name='anleitung-fhir-query-client.pdf',
        title='FHIR Server Query Client',
        subtitle='https://fhir.woess.ch/fhir-query-client.html',
        description_lines=(
            wrap('Fuehrt lesende Abfragen direkt gegen den FHIR-Server aus und visualisiert Bundles: '
                 'Patient-Stammdaten, Kontakte, Adressen und Notfallkontakte, gefolgt von einer fachlichen '
                 'Zusammenfassung und aufklappbaren Detailtabellen (Vitalwerte, Labor, Medikation, Probleme, '
                 'Allergien, Immunisierungen).')
            + ['']
            + wrap('Standard-Query: Patient/{patientId}/$everything?_count=500. Ueber "Use Case" lassen sich '
                   'auch einzelne Ressourcentypen wie Observation oder Condition abfragen. Authentifizierung '
                   'per Basic Auth oder Bearer Token; Zugangsdaten koennen optional lokal im Browser gespeichert werden.')
            + ['']
            + ['Aufrufen unter: https://fhir.woess.ch/fhir-query-client.html']
            + wrap('Lokale Entwicklung (im Verzeichnis fhir-middleware): python3 -m http.server 8080, '
                   'danach http://localhost:8080/fhir-query-client.html.')
        ),
        screenshot_name='fhir-query-client.png',
    ),
    dict(
        out_name='anleitung-test-client.pdf',
        title='BridgeLink API Werkbank',
        subtitle='https://fhir.woess.ch/test-client.html',
        description_lines=(
            wrap('Browser-Werkbank fuer alle fachlichen Middleware-Use-Cases: FHIR Bundle, CDA (inkl. CH-Profile), '
                 'UMZH, HL7v2 ORU^R01, eMediplan, EPIC-CDA, Terminologie ($expand/$lookup/$validate-code/...) '
                 'und Smoke Tests.')
            + ['']
            + wrap('Nach Auswahl eines Use Cases zeigt die Seite Methode und Pfad des Aufrufs sowie ein passendes '
                   'Beispiel-Payload. Text-/JSON-Dateien lassen sich direkt laden, eMediplan-Use-Cases akzeptieren '
                   'zusaetzlich PDF/Bild mit QR-Code als Multipart-Upload.')
            + ['']
            + wrap('"Als Eingabe verwenden" uebernimmt die letzte Antwort in den Editor (z. B. CDA konvertieren, '
                   'Ergebnis stabilisieren, dann an FHIR senden). "Verbindung pruefen" testet Middleware und FHIR-Server.')
            + ['']
            + ['Aufrufen unter: https://fhir.woess.ch/test-client.html']
            + wrap('Lokale Entwicklung (im Verzeichnis fhir-middleware): python3 -m http.server 8080, '
                   'danach http://localhost:8080/test-client.html.')
        ),
        screenshot_name='test-client.png',
    ),
    dict(
        out_name='anleitung-matrix-smoke-test.pdf',
        title='Matrix Smoke Test',
        subtitle='https://fhir.woess.ch/matrix-test/',
        description_lines=(
            wrap('Schnelltest fuer die Matrix/Synapse-Infrastruktur direkt im Browser: prueft Client Versions, '
                 'die Well-Known-Discovery (Server/Client) und den Federation-Server-Key-Endpunkt ("Run All Checks").')
            + ['']
            + wrap('Matrix Login Test prueft Benutzeranmeldung gegen /_matrix/client/v3/login. Die Zugangsdaten '
                   'werden nur fuer den jeweiligen Request verwendet und nicht gespeichert.')
            + ['']
            + wrap('Matrix Communication Test simuliert einen vollstaendigen 2-Nutzer-Ablauf: Raum erstellen, '
                   'beide Nutzer beitreten lassen, Nachrichten senden/lesen und den Chatverlauf gerendert '
                   'anzeigen ("Run 2-User E2E").')
            + ['']
            + wrap('eMediplan Bot Test (Kurzform) sendet ein PDF/Bild mit eMediplan-QR-Code in den Bot-Raum von '
                   'Nutzer A und zeigt die Bot-Antwort; der Bot muss vorher in den Raum eingeladen worden sein. '
                   'Fuer den vollstaendigen Ablauf inkl. Identitaetspflege siehe die eigene Anleitung zum eMediplan Bot Test.')
            + ['']
            + ['Aufrufen unter: https://fhir.woess.ch/matrix-test/']
        ),
        screenshot_name='matrix-smoke-test.png',
    ),
    dict(
        out_name='anleitung-bot-test.pdf',
        title='eMediplan Bot Test',
        subtitle='https://fhir.woess.ch/matrix-test/bot-test.html',
        description_lines=(
            wrap('Dedizierte Seite fuer den eMediplan-Import-Bot mit gefuehrtem Ablauf in vier Schritten.')
            + ['']
            + wrap('1. Login: Anmeldung mit Matrix-Benutzername/Passwort; Zugangsdaten koennen optional lokal '
                   'gespeichert werden.')
            + wrap('1b. Profil bearbeiten: Matrix-Displayname laden/speichern (Matrix kennt offiziell nur '
                   'Displayname und Avatar).')
            + wrap('1c. Meine Patienten-Identitaet: Vorname, Nachname und Geburtsdatum hinterlegen. Der Bot '
                   'importiert ein eMediplan-Dokument nur, wenn dessen Patient zu dieser Identitaet passt; '
                   'nur der eigene Zugriffstoken kann den eigenen Eintrag aendern.')
            + wrap('2. Raum: Bot-User-ID und gemeinsamen Bot-Raum auswaehlen bzw. neu laden; der Bot tritt '
                   'eingeladenen Raeumen automatisch dauerhaft bei.')
            + wrap('3. Datei senden: eMediplan-PDF/Bild oder CDA-XML auswaehlen und an den Bot senden. Die Seite '
                   'wartet kurz und liest anschliessend die neuesten Raumnachrichten fuer die Bot-Antwort.')
            + wrap('4. Bisherige Unterhaltung: Verlauf manuell laden oder per Auto-Refresh (3-20s) aktuell halten.')
            + ['']
            + ['Aufrufen unter: https://fhir.woess.ch/matrix-test/bot-test.html']
        ),
        screenshot_name='bot-test.png',
    ),
    dict(
        out_name='anleitung-epic-spital-emediplan-cda-de.pdf',
        title='EPIC-Spital: eMediplan (CHMED16A) -> EPIC CDA',
        subtitle='https://fhir.woess.ch/epic-spital-emediplan-cda.html',
        description_lines=(
            wrap('Dedizierte, vereinfachte Testseite fuer den Benutzer "EPIC-Spital" mit genau '
                 'einem Use Case: eMediplan im CHMED16A-Format (Text, PDF oder Bild mit QR-Code) '
                 'wird ueber die Middleware zu FHIR und anschliessend zu einem EPIC-Medikations-CDA '
                 'konvertiert.')
            + ['']
            + wrap('Zugangsdaten (Auth Typ, Username, Passwort/Token) koennen ueber "Zugangsdaten '
                   'speichern" lokal im Browser hinterlegt werden. CHMED16A-Text kann direkt in das '
                   'Eingabefeld eingefuegt werden, alternativ kann rechts eine PDF- oder Bilddatei mit '
                   'eMediplan-QR-Code ausgewaehlt werden.')
            + ['']
            + wrap('"Use Case ausfuehren" sendet den Request an POST /emediplan/epic-cda. Das '
                   'resultierende EPIC-CDA-XML wird direkt angezeigt und kann ueber "CDA herunterladen" '
                   'als Datei gespeichert werden.')
            + ['']
            + ['Aufrufen unter: https://fhir.woess.ch/epic-spital-emediplan-cda.html']
        ),
        screenshot_name='epic-spital-emediplan-cda.png',
    ),
    dict(
        out_name='anleitung-epic-spital-emediplan-cda-en.pdf',
        title='EPIC-Spital: eMediplan (CHMED16A) -> EPIC CDA',
        subtitle='https://fhir.woess.ch/epic-spital-emediplan-cda.html',
        description_lines=(
            wrap('Dedicated, simplified test page for the "EPIC-Spital" user with exactly one use '
                 'case: an eMediplan payload in CHMED16A format (text, PDF, or image with QR code) is '
                 'converted via the middleware to FHIR and then to an EPIC medication CDA document.')
            + ['']
            + wrap('Credentials (Auth Type, Username, Password/Token) can be stored locally in the '
                   'browser via "Zugangsdaten speichern" (Save credentials). CHMED16A text can be '
                   'pasted directly into the input field, or a PDF/image file containing an eMediplan '
                   'QR code can be selected on the right.')
            + ['']
            + wrap('"Use Case ausfuehren" (Run use case) sends the request to POST /emediplan/epic-cda. '
                   'The resulting EPIC CDA XML is displayed directly and can be saved as a file via '
                   '"CDA herunterladen" (Download CDA).')
            + ['']
            + ['Open at: https://fhir.woess.ch/epic-spital-emediplan-cda.html']
        ),
        screenshot_name='epic-spital-emediplan-cda.png',
    ),
]


def build_pdfs():
    created = []
    for page in PAGES:
        builder = PdfBuilder()
        layout_section(
            builder,
            title=page['title'],
            subtitle=page['subtitle'],
            description_lines=page['description_lines'],
            screenshot_name=page['screenshot_name'],
        )
        out_path = BASE / page['out_name']
        builder.write(out_path)
        created.append(out_path)
    return created


if __name__ == '__main__':
    for out_path in build_pdfs():
        print(f'created: {out_path} ({out_path.stat().st_size} bytes)')
