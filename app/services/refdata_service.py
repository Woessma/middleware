import re
import xml.etree.ElementTree as ET

import requests

from config import REFDATA_API_KEY, REFDATA_BASE_URL, REFDATA_TIMEOUT

_SOAP_ENVELOPE = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <DownloadPartnerInput xmlns="http://refdatabase.refdata.ch/">
      <TYPE>GLN</TYPE>
      <PTYPE>ALL</PTYPE>
      <TERM>{gln}</TERM>
    </DownloadPartnerInput>
  </soap:Body>
</soap:Envelope>"""

_NS = {"po": "http://refdatabase.refdata.ch/V2/Partner_out"}

# Public, unauthenticated search used by refdata.ch's own web viewer
# (https://www.refdata.ch/de/partner/abfrage/partner-refdatabase-gln). This is an undocumented
# internal endpoint of that page (no official API contract), used only as a fallback when our
# Partner API subscription (Stage only) doesn't find a GLN that exists in production.
_PUBLIC_VIEWER_URL = "https://refdatabase.refdata.ch/Viewer/SearchPartnerByGln"
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(html_fragment):
    return _TAG_RE.sub("", html_fragment).strip()


def _extract_table_cells(html, table_id, cell_tag):
    match = re.search(rf'<table[^>]*id="{table_id}"[^>]*>.*?</table>', html, re.S)
    if not match:
        return []

    rows = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", match.group(0), re.S):
        cells = [
            _strip_tags(cell)
            for cell in re.findall(rf"<{cell_tag}[^>]*>(.*?)</{cell_tag}>", row_html, re.S)
        ]
        if any(cells):
            rows.append(cells)
    return rows


def _lookup_gln_public_viewer(gln, timeout=15):
    """Best-effort fallback via refdata.ch's public refdatabase viewer (production data,
    no subscription key required). Returns None on any error or if not found."""
    try:
        response = requests.post(
            _PUBLIC_VIEWER_URL,
            params={"Lang": "de"},
            data={
                "SearchGln": gln,
                "Sort": "",
                "NewSort": "",
                "IsAscending": "False",
                "Reset": "False",
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=timeout,
        )
        response.raise_for_status()

        html = response.text
        header_rows = re.search(r'<table[^>]*id="GVResult"[^>]*>.*?</table>', html, re.S)
        if not header_rows:
            return None
        headers = [
            _strip_tags(cell)
            for cell in re.findall(r"<th[^>]*>(.*?)</th>", header_rows.group(0), re.S)
        ]

        rows = _extract_table_cells(html, "GVResultb", "td")
        if not headers or not rows:
            return None

        header_index = {name: i for i, name in enumerate(headers)}

        def col(row, name):
            idx = header_index.get(name)
            return row[idx] if idx is not None and idx < len(row) else None

        for row in rows:
            if col(row, "GLN") != gln:
                continue

            first_name = col(row, "Vorname")
            last_name = col(row, "Nachname")
            name = " ".join(part for part in [first_name, last_name] if part) or None

            return {
                "gln": gln,
                "status": col(row, "Status"),
                "name": name,
                "name2": None,
                "given_name": first_name,
                "family_name": last_name,
                "address": {
                    "line": [],
                    "postalCode": None,
                    "city": col(row, "PLZ Ort"),
                    "state": col(row, "Ktn"),
                    "country": col(row, "Land"),
                },
            }

        return None
    except Exception:
        return None


def _parse_item(item):
    role = item.find("po:ROLE", _NS)

    address = None
    if role is not None:
        line = " ".join(
            part
            for part in [
                (role.findtext("po:STREET", default="", namespaces=_NS) or "").strip(),
                (role.findtext("po:STRNO", default="", namespaces=_NS) or "").strip(),
            ]
            if part
        )
        address = {
            "line": [line] if line else [],
            "postalCode": role.findtext("po:ZIP", default=None, namespaces=_NS),
            "city": role.findtext("po:CITY", default=None, namespaces=_NS),
            "state": role.findtext("po:CTN", default=None, namespaces=_NS),
            "country": role.findtext("po:CNTRY", default=None, namespaces=_NS),
        }

    return {
        "gln": item.findtext("po:GLN", default=None, namespaces=_NS),
        "status": item.findtext("po:STATUS", default=None, namespaces=_NS),
        "name": item.findtext("po:DESCR1", default=None, namespaces=_NS),
        "name2": item.findtext("po:DESCR2", default=None, namespaces=_NS),
        # DESCR1/2 are opaque descriptor strings (person or organisation, format not
        # guaranteed splittable) - no reliable given/family split from the SOAP API.
        "given_name": None,
        "family_name": None,
        "address": address,
    }


def lookup_gln(gln, base_url=REFDATA_BASE_URL, api_key=REFDATA_API_KEY, timeout=REFDATA_TIMEOUT):
    """Looks up a single GLN via the refdata.ch Partner API, falling back to the public
    refdatabase viewer (production data) when the official (Stage-only) subscription doesn't
    find it. Returns None when not configured, not found anywhere, or on any request/parsing
    error (best-effort enrichment - callers should not fail an import because of this)."""
    if not api_key:
        return None

    try:
        response = requests.post(
            base_url,
            params={"subscription-key": api_key},
            data=_SOAP_ENVELOPE.format(gln=gln).encode("utf-8"),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": "http://refdatabase.refdata.ch/Download",
            },
            timeout=timeout,
        )
        response.raise_for_status()

        root = ET.fromstring(response.content)

        for item in root.iter("{http://refdatabase.refdata.ch/V2/Partner_out}ITEM"):
            # the stage/test environment does not reliably filter server-side,
            # so match the requested GLN ourselves against each returned item.
            if item.findtext("po:GLN", default=None, namespaces=_NS) == gln:
                return _parse_item(item)
    except Exception:
        pass

    return _lookup_gln_public_viewer(gln, timeout=timeout)
