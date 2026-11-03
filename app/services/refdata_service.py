import copy
import hashlib
import logging
import os
import re
import sqlite3
import tempfile
import threading
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from config import REFDATA_API_KEY, REFDATA_BASE_URL, REFDATA_TIMEOUT

logger = logging.getLogger(__name__)

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
_PARTNER_TYPES = ("NAT", "JUR")
_REFDATA_XML_FILES = {
    "NAT": Path(__file__).resolve().parents[1] / "terminology" / "data" / "Refdata.Partners.Nat.xml",
    "JUR": Path(__file__).resolve().parents[1] / "terminology" / "data" / "Refdata.Partners.Jur.xml",
}
_INDEX_BUILD_LOCK = threading.Lock()


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def _xml_item_data(item, partner_type):
    fields = {}
    role = None

    for child in item:
        child_name = _local_name(child.tag)
        if child_name == "ROLE":
            role = child
        else:
            fields[child_name] = (child.text or "").strip() or None

    if fields.get("PTYPE") and fields["PTYPE"] != partner_type:
        return None

    given_name = fields.get("DESCR2") if partner_type == "NAT" else None
    family_name = fields.get("DESCR1") if partner_type == "NAT" else None
    name = (
        " ".join(part for part in (given_name, family_name) if part)
        if partner_type == "NAT"
        else fields.get("DESCR1")
    )

    address = None
    if role is not None:
        role_fields = {
            _local_name(child.tag): (child.text or "").strip() or None
            for child in role
        }
        street = " ".join(
            part
            for part in (role_fields.get("STREET"), role_fields.get("STRNO"))
            if part
        )
        address = {
            "line": [street] if street else [],
            "postalCode": role_fields.get("ZIP"),
            "city": role_fields.get("CITY"),
            "state": role_fields.get("CTN"),
            "country": role_fields.get("CNTRY"),
        }

    return {
        "gln": fields.get("GLN"),
        "partner_type": partner_type,
        "status": fields.get("STATUS"),
        "name": name,
        "name2": fields.get("DESCR2") if partner_type == "JUR" else None,
        "given_name": given_name,
        "family_name": family_name,
        "address": address,
        "updated_at": item.attrib.get("DT", ""),
    }


def _xml_index_path(partner_type, xml_path):
    stat = xml_path.stat()
    fingerprint = hashlib.sha256(
        f"{xml_path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8")
    ).hexdigest()[:20]
    return Path(tempfile.gettempdir()) / f"python-middleware-refdata-{partner_type}-{fingerprint}.sqlite3"


def _build_xml_index(xml_path, index_path, partner_type):
    temporary_path = index_path.with_name(
        f"{index_path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    )
    connection = sqlite3.connect(temporary_path)
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute(
            """
            CREATE TABLE partners (
                gln TEXT PRIMARY KEY,
                updated_at TEXT NOT NULL,
                status TEXT,
                name TEXT,
                name2 TEXT,
                given_name TEXT,
                family_name TEXT,
                street TEXT,
                postal_code TEXT,
                city TEXT,
                state TEXT,
                country TEXT
            )
            """
        )
        upsert = """
            INSERT INTO partners
                (gln, updated_at, status, name, name2, given_name, family_name,
                 street, postal_code, city, state, country)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(gln) DO UPDATE SET
                updated_at = excluded.updated_at,
                status = excluded.status,
                name = excluded.name,
                name2 = excluded.name2,
                given_name = excluded.given_name,
                family_name = excluded.family_name,
                street = excluded.street,
                postal_code = excluded.postal_code,
                city = excluded.city,
                state = excluded.state,
                country = excluded.country
            WHERE excluded.updated_at >= partners.updated_at
        """
        batch = []
        root = None
        for event, element in ET.iterparse(xml_path, events=("start", "end")):
            if event == "start" and root is None:
                root = element
            elif event == "end" and _local_name(element.tag) == "ITEM":
                record = _xml_item_data(element, partner_type)
                if record and record["gln"]:
                    address = record["address"] or {}
                    batch.append(
                        (
                            record["gln"],
                            record["updated_at"],
                            record["status"],
                            record["name"],
                            record["name2"],
                            record["given_name"],
                            record["family_name"],
                            (address.get("line") or [None])[0],
                            address.get("postalCode"),
                            address.get("city"),
                            address.get("state"),
                            address.get("country"),
                        )
                    )
                element.clear()
                if root is not None:
                    root.clear()
                if len(batch) >= 1000:
                    connection.executemany(upsert, batch)
                    batch.clear()

        if batch:
            connection.executemany(upsert, batch)
        connection.commit()
    except Exception:
        connection.close()
        temporary_path.unlink(missing_ok=True)
        raise
    else:
        connection.close()
        os.replace(temporary_path, index_path)


def _lookup_gln_xml(gln, partner_type=None):
    partner_types = (partner_type,) if partner_type else _PARTNER_TYPES
    for current_type in partner_types:
        xml_path = _REFDATA_XML_FILES.get(current_type)
        if not xml_path or not xml_path.is_file():
            continue

        index_path = _xml_index_path(current_type, xml_path)
        with _INDEX_BUILD_LOCK:
            if not index_path.is_file():
                _build_xml_index(xml_path, index_path, current_type)

        connection = sqlite3.connect(index_path)
        try:
            row = connection.execute(
                """
                SELECT status, name, name2, given_name, family_name,
                       street, postal_code, city, state, country
                FROM partners WHERE gln = ?
                """,
                (gln,),
            ).fetchone()
        finally:
            connection.close()

        if row is None:
            continue

        status, name, name2, given_name, family_name, street, postal, city, state, country = row
        return {
            "gln": gln,
            "partner_type": current_type,
            "status": status,
            "name": name,
            "name2": name2,
            "given_name": given_name,
            "family_name": family_name,
            "address": {
                "line": [street] if street else [],
                "postalCode": postal,
                "city": city,
                "state": state,
                "country": country,
            },
        }
    return None


def _identifier_gln(resource):
    for identifier in resource.get("identifier") or []:
        if identifier.get("system") == "urn:oid:2.51.1.3":
            return identifier.get("value")
    return None


def _merge_address(resource, entry):
    refdata_address = {
        key: value
        for key, value in (entry.get("address") or {}).items()
        if value
    }
    if not refdata_address:
        return

    addresses = resource.get("address")
    if not addresses:
        resource["address"] = [refdata_address]
        return

    if isinstance(addresses, list) and addresses and isinstance(addresses[0], dict):
        for key, value in refdata_address.items():
            if not addresses[0].get(key):
                addresses[0][key] = value


def enrich_practitioner_resource(practitioner):
    """Fill missing Practitioner name/address fields from the NAT GLN registry."""
    enriched = copy.deepcopy(practitioner)
    gln = _identifier_gln(enriched)
    if not gln:
        return enriched

    entry = lookup_gln(gln, partner_type="NAT")
    if not entry:
        return enriched

    names = enriched.get("name")
    if not names:
        name = {}
        if entry.get("family_name"):
            name["family"] = entry["family_name"]
        if entry.get("given_name"):
            name["given"] = [entry["given_name"]]
        if not name and entry.get("name"):
            name["text"] = entry["name"]
        if name:
            enriched["name"] = [name]
    elif isinstance(names, list) and names and isinstance(names[0], dict):
        if not names[0].get("family") and entry.get("family_name"):
            names[0]["family"] = entry["family_name"]
        if not names[0].get("given") and entry.get("given_name"):
            names[0]["given"] = [entry["given_name"]]

    _merge_address(enriched, entry)
    return enriched


def enrich_organization_resource(organization):
    """Fill missing Organization name/address fields from the JUR GLN registry."""
    enriched = copy.deepcopy(organization)
    gln = _identifier_gln(enriched)
    if not gln:
        return enriched

    entry = lookup_gln(gln, partner_type="JUR")
    if not entry:
        return enriched

    if not enriched.get("name") and entry.get("name"):
        enriched["name"] = entry["name"]
    if entry.get("name2"):
        aliases = enriched.get("alias")
        if not isinstance(aliases, list):
            aliases = []
            enriched["alias"] = aliases
        if entry["name2"] not in aliases:
            aliases.append(entry["name2"])

    _merge_address(enriched, entry)
    return enriched


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
    partner_type = item.findtext("po:PTYPE", default=None, namespaces=_NS)
    descr1 = item.findtext("po:DESCR1", default=None, namespaces=_NS)
    descr2 = item.findtext("po:DESCR2", default=None, namespaces=_NS)
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

    is_natural_person = partner_type == "NAT"
    given_name = descr2 if is_natural_person else None
    family_name = descr1 if is_natural_person else None
    name = (
        " ".join(part for part in (given_name, family_name) if part)
        if is_natural_person
        else descr1
    )

    return {
        "gln": item.findtext("po:GLN", default=None, namespaces=_NS),
        "partner_type": partner_type,
        "status": item.findtext("po:STATUS", default=None, namespaces=_NS),
        "name": name,
        "name2": descr2 if not is_natural_person else None,
        "given_name": given_name,
        "family_name": family_name,
        "address": address,
    }


def lookup_gln(
    gln,
    base_url=REFDATA_BASE_URL,
    api_key=REFDATA_API_KEY,
    timeout=REFDATA_TIMEOUT,
    partner_type=None,
):
    """Looks up a single GLN via the refdata.ch Partner API, falling back to the public
    refdatabase viewer (production data) when the official (Stage-only) subscription doesn't
    find it. Local XML files are checked first. Set partner_type to NAT or JUR when the
    resource type is known. Returns None when not configured, not found, or on request/parsing
    errors (best-effort enrichment - callers should not fail an import because of this)."""
    try:
        local_entry = _lookup_gln_xml(gln, partner_type=partner_type)
        if local_entry:
            return local_entry
    except (OSError, sqlite3.Error, ET.ParseError):
        logger.exception("Lokale Refdata-XML-Datei konnte nicht ausgewertet werden")

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
            if item.findtext("po:GLN", default=None, namespaces=_NS) != gln:
                continue
            item_type = item.findtext("po:PTYPE", default=None, namespaces=_NS)
            if partner_type and item_type != partner_type:
                continue
            return _parse_item(item)
    except Exception:
        logger.exception("Refdata Partner API lookup failed")

    if partner_type:
        return None
    return _lookup_gln_public_viewer(gln, timeout=timeout)
