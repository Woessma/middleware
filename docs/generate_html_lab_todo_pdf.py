"""Create the HTML lab implementation checklist as a small dependency-free PDF."""

from pathlib import Path
import textwrap


PAGE_W = 595
PAGE_H = 842
MARGIN = 50
OUTPUT = Path(__file__).with_name("anleitung-html-lab-todo.pdf")


def escape(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def wrap(text, width=86):
    return textwrap.wrap(text, width=width) or [""]


class Pdf:
    def __init__(self):
        self.objects = {}
        self.next_id = 1
        self.pages = []
        self.font = self.reserve()
        self.bold = self.reserve()
        self.objects[self.font] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
        self.objects[self.bold] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"
        self.pages_id = self.reserve()
        self.catalog_id = self.reserve()

    def reserve(self):
        object_id = self.next_id
        self.next_id += 1
        return object_id

    def add_page(self, commands):
        stream = "\n".join(commands).encode("latin-1", "replace")
        content_id = self.reserve()
        self.objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1")
            + stream
            + b"\nendstream"
        )
        page_id = self.reserve()
        self.objects[page_id] = (
            f"<< /Type /Page /Parent {self.pages_id} 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
            f"/Resources << /Font << /F1 {self.font} 0 R /F2 {self.bold} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        )
        self.pages.append(page_id)

    def write(self, path):
        kids = " ".join(f"{page_id} 0 R" for page_id in self.pages)
        self.objects[self.pages_id] = (
            f"<< /Type /Pages /Kids [{kids}] /Count {len(self.pages)} >>"
        )
        self.objects[self.catalog_id] = f"<< /Type /Catalog /Pages {self.pages_id} 0 R >>"

        data = bytearray(b"%PDF-1.4\n")
        offsets = {}
        for object_id in sorted(self.objects):
            offsets[object_id] = len(data)
            data += f"{object_id} 0 obj\n".encode("latin-1")
            body = self.objects[object_id]
            data += body if isinstance(body, bytes) else body.encode("latin-1")
            data += b"\nendobj\n"

        xref = len(data)
        data += f"xref\n0 {self.next_id}\n0000000000 65535 f \n".encode("latin-1")
        for object_id in range(1, self.next_id):
            data += f"{offsets[object_id]:010d} 00000 n \n".encode("latin-1")
        data += (
            f"trailer\n<< /Size {self.next_id} /Root {self.catalog_id} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("latin-1")
        path.write_bytes(data)


def text(commands, x, y, value, size=10, bold=False):
    font = "F2" if bold else "F1"
    commands += [
        "BT",
        f"/{font} {size} Tf",
        f"{x} {y} Td",
        f"({escape(value)}) Tj",
        "ET",
    ]


def build_page(pdf, title, intro, sections):
    commands = ["0.12 0.20 0.28 rg", "0.12 0.20 0.28 RG"]
    text(commands, MARGIN, 790, title, size=19, bold=True)
    text(commands, MARGIN, 766, intro, size=10)
    y = 730

    for heading, items in sections:
        text(commands, MARGIN, y, heading, size=13, bold=True)
        y -= 23
        for item in items:
            lines = wrap(item)
            for index, line in enumerate(lines):
                prefix = "[ ] " if index == 0 else "    "
                text(commands, MARGIN, y, prefix + line, size=10)
                y -= 14
            y -= 5
        y -= 8

    pdf.add_page(commands)


def main():
    pdf = Pdf()
    build_page(
        pdf,
        "HTML Lab - To-do",
        "Showcases fuer Read, Convert und Import ueber Cloudflare, Caddy und BridgeLink.",
        [
            (
                "1. Zielarchitektur",
                [
                    "Cloudflare und cloudflared auf den Caddy-Einstiegspunkt zeigen.",
                    "Caddy liefert /lab/* statisch aus und routet /fhir/* sowie /middleware/* zu BridgeLink.",
                    "HAPI FHIR und Middleware bleiben intern und werden nicht direkt aus dem Browser angesprochen.",
                    "BridgeLink prueft JWT, Berechtigungen und leitet den Use Case weiter.",
                ],
            ),
            (
                "2. Caddy und Deployment",
                [
                    "HTML-Dateien unter /srv/lab bereitstellen und /lab/test-client.html pruefen.",
                    "Nur die benoetigten Pfade /lab, /fhir und /middleware oeffnen.",
                    "Direkte Internetfreigaben fuer HAPI, BridgeLink-Admin und Middleware entfernen.",
                    "Request-Groesse fuer CDA, PDF und QR-Dateien begrenzen und Zugriffe protokollieren.",
                ],
            ),
        ],
    )
    build_page(
        pdf,
        "HTML Lab - Showcases",
        "Jeder Showcase verwendet oeffentliche BridgeLink-Routen und synthetische Testdaten.",
        [
            (
                "3. Read-Showcase",
                [
                    "FHIR-Patientensuche ueber die BridgeLink-FHIR-Route aufrufen.",
                    "Patient, Bundle und Ressourcen-Timeline lesbar darstellen.",
                    "Read-only JWT-Scope verwenden und keine Schreibaktion anbieten.",
                ],
            ),
            (
                "4. Convert-Showcases",
                [
                    "CDA, HL7v2, eMediplan, VACD, eTOC und UMZH als Testdaten anbieten.",
                    "Konvertierungsantwort als formatiertes FHIR-Bundle darstellen.",
                    "Request, Response, Status und Laufzeit im Request Inspector anzeigen.",
                ],
            ),
            (
                "5. Import-Showcases",
                [
                    "Import zuerst konvertieren und eine Vorschau des Transaction-Bundles zeigen.",
                    "Nach expliziter Bestaetigung ueber BridgeLink schreiben lassen.",
                    "HAPI-Transaction-Response mit angelegten und aktualisierten Ressourcen anzeigen.",
                    "Kein direkter Browser-Write nach HAPI FHIR.",
                ],
            ),
        ],
    )
    build_page(
        pdf,
        "HTML Lab - Sicherheit und Abnahme",
        "Das Lab ist eine kontrollierte Demo-Oberflaeche, kein Ersatz fuer die API-Autorisierung.",
        [
            (
                "6. Browser-Sicherheit",
                [
                    "OAuth2/OIDC mit Authorization Code und PKCE verwenden.",
                    "Tokens nicht in HTML, Quellcode oder localStorage speichern.",
                    "Lab mit Cloudflare Access oder einer getrennten Demo-Identitaet schuetzen.",
                    "Nur synthetische Patienten- und Dokumentdaten verwenden.",
                ],
            ),
            (
                "7. Qualitaet und Abnahme",
                [
                    "CDA Convert liefert ein valides Bundle ohne HAPI-Write.",
                    "CDA Import wird durch BridgeLink in HAPI geschrieben.",
                    "FHIR Read liefert Daten nur ueber BridgeLink.",
                    "Fehler 400, 401, 403, 413 und 5xx werden im Lab verstaendlich angezeigt.",
                    "Alle Showcases funktionieren unter https://fhir.omnilink.ch/lab/.",
                ],
            ),
            (
                "8. Offen",
                [
                    "Konkrete BridgeLink-Kanalnamen und JWT-Scopes festlegen.",
                    "Matrix ausserhalb dieses Labs halten.",
                    "Caddy-Konfiguration in der VM versioniert ablegen und testen.",
                ],
            ),
        ],
    )
    pdf.write(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()