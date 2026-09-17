import copy
import hashlib
import html
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import requests

from config import FHIR_BASE
from services.terminology_service import validate_coding

ECHOSOS_HOST = "eid.echosos.com"
ECHOSOS_IDENTIFIER_SYSTEM = "https://woess.ch/fhir/NamingSystem/echosos"
BLOOD_GROUP_LOINC = "882-1"
BLOOD_GROUPS = ["A-", "A+", "B-", "B+", "AB-", "AB+", "0-", "0+", "Unbekannt"]
MONTHS = {
    "januar": "01",
    "februar": "02",
    "märz": "03",
    "maerz": "03",
    "april": "04",
    "mai": "05",
    "juni": "06",
    "juli": "07",
    "august": "08",
    "september": "09",
    "oktober": "10",
    "november": "11",
    "dezember": "12",
}


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.ignore_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignore_depth += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.ignore_depth:
            self.ignore_depth -= 1

    def handle_data(self, data):
        if not self.ignore_depth:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)

    def text(self):
        return "\n".join(self.parts)


def _barcode_from_pkpass(raw_bytes):
    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
        payload = json.loads(archive.read("pass.json"))
    barcode = payload.get("barcodes", [payload.get("barcode")])[0]
    if not barcode or not barcode.get("message"):
        raise ValueError("Kein EchoSOS-Barcode in der PKPass-Datei gefunden")
    return barcode["message"]


def extract_echosos_url(raw_bytes, content_type=None):
    if raw_bytes[:2] == b"PK" or content_type == "application/vnd.apple.pkpass":
        value = _barcode_from_pkpass(raw_bytes)
    elif raw_bytes.lstrip().startswith((b"http://", b"https://")):
        value = raw_bytes.decode("utf-8").strip()
    else:
        from PIL import Image
        from pyzbar.pyzbar import decode as decode_qr_codes

        symbols = decode_qr_codes(Image.open(io.BytesIO(raw_bytes)))
        if not symbols:
            raise ValueError("Kein QR-Code in der Datei gefunden")
        value = symbols[0].data.decode("utf-8")

    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname != ECHOSOS_HOST:
        raise ValueError("Der QR-Code enthält keinen gültigen EchoSOS-Link")
    return value


def _value(params, key):
    values = params.get(key, [])
    return values[0].strip() if values else ""


def _date_from_text(text):
    match = re.search(r"(\d{1,2})\.\s*([A-Za-zÄÖÜäöü]+)\s+(\d{4})", text)
    if not match:
        return None
    month = MONTHS.get(match.group(2).lower())
    return f"{match.group(3)}-{month}-{int(match.group(1)):02d}" if month else None


def _date_from_echosos_code(value):
    if not value or len(value) != 4:
        return None
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    try:
        year = 64 * alphabet.index(value[0]) + alphabet.index(value[1])
        month = alphabet.index(value[2])
        day = alphabet.index(value[3])
        if not 1 <= month <= 12 or not 1 <= day <= 31:
            return None
        return f"{year:04d}-{month:02d}-{day:02d}"
    except ValueError:
        return None


def _label_value(text, label):
    match = re.search(rf"{re.escape(label)}\s+([^\n]+)", text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def fetch_echosos_data(url):
    response = requests.get(
        url,
        headers={"Accept": "text/html", "User-Agent": "FHIR-Middleware EchoSOS importer"},
        timeout=15,
    )
    response.raise_for_status()
    return response.text


def parse_echosos_data(url, page_html=""):
    parsed = urlsplit(url)
    params = parse_qs(parsed.fragment, keep_blank_values=True)
    first = html.unescape(_value(params, "f"))
    family = html.unescape(_value(params, "l"))
    contact_name = html.unescape(_value(params, "n1"))
    contact_phone = html.unescape(_value(params, "p1"))
    text_parser = _TextParser()
    text_parser.feed(page_html)
    text = text_parser.text()
    full_name = re.search(r"Notfallpass\s+([^\n]+)", text, re.IGNORECASE)
    if full_name and not first and not family:
        parts = full_name.group(1).split()
        first, family = (parts[0], parts[-1]) if len(parts) > 1 else (parts[0], "")
    blood_code = _value(params, "b")
    blood_group = BLOOD_GROUPS[int(blood_code)] if blood_code.isdigit() and int(blood_code) < len(BLOOD_GROUPS) else _label_value(text, "Blutgruppe")
    return {
        "source_url": url,
        "given": first,
        "family": family,
        "birth_date": _date_from_echosos_code(_value(params, "g")) or _date_from_text(text),
        "blood_group": blood_group if re.fullmatch(r"[A-Z][+-]", blood_group) else None,
        "emergency_contact": {"name": contact_name, "phone": contact_phone},
        "allergies": _label_value(text, "Allergien / Stärkste Reaktion"),
        "medications": _label_value(text, "Medikamente"),
        "medical_history": _label_value(text, "Medizinische Vorgeschichte"),
    }


def _patient_search(data):
    response = requests.get(
        f"{FHIR_BASE}/Patient",
        params={"family": data["family"], "given": data["given"], "birthdate": data["birth_date"]},
        headers={"Accept": "application/fhir+json"},
        timeout=15,
    )
    response.raise_for_status()
    entries = response.json().get("entry", [])
    return entries[0]["resource"] if entries else None


def _patient_resource(data, existing=None):
    patient = copy.deepcopy(existing) if existing else {
        "resourceType": "Patient",
        "meta": {"profile": ["http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-patient"]},
    }
    patient["name"] = [{"use": "official", "family": data["family"], "given": [data["given"]]}]
    patient["birthDate"] = data["birth_date"]
    contact = data["emergency_contact"]
    if contact.get("name") or contact.get("phone"):
        contacts = patient.setdefault("contact", [])
        matching = next(
            (
                item
                for item in contacts
                if item.get("name", {}).get("text") == contact.get("name")
                or any(
                    telecom.get("value") == contact.get("phone")
                    for telecom in item.get("telecom", [])
                )
            ),
            None,
        )
        if matching is None:
            matching = {}
            contacts.append(matching)
        if contact.get("name"):
            matching["name"] = {"text": contact["name"]}
        if contact.get("phone"):
            matching["telecom"] = [{"system": "phone", "value": contact["phone"], "use": "mobile"}]
        relationships = matching.setdefault("relationship", [])
        if not any(
            coding.get("code") == "ECON"
            for relationship in relationships
            for coding in relationship.get("coding", [])
        ):
            relationships.append({
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/v3-RoleCode",
                    "code": "ECON",
                    "display": "Emergency contact",
                }],
                "text": "Notfallkontakt",
            })
    return patient


def _upsert_patient(patient):
    patient_id = patient.get("id")
    method = requests.put if patient_id else requests.post
    url = f"{FHIR_BASE}/Patient/{patient_id}" if patient_id else f"{FHIR_BASE}/Patient"
    response = method(url, json=patient, headers={"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"}, timeout=15)
    response.raise_for_status()
    return response.json()


def _blood_observations(data, patient_id, author):
    if not data.get("blood_group"):
        return []
    coding = {"system": "http://loinc.org", "code": BLOOD_GROUP_LOINC}
    validation = validate_coding(coding)
    if validation.get("status") != "validated":
        raise ValueError(f"LOINC {BLOOD_GROUP_LOINC} konnte über den TX-Server nicht validiert werden")
    digest = hashlib.sha256(f"{data['source_url']}|{BLOOD_GROUP_LOINC}".encode()).hexdigest()
    recorded_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return [{
        "resourceType": "Observation",
        "identifier": [{"system": ECHOSOS_IDENTIFIER_SYSTEM, "value": digest}],
        "status": "final",
        "effectiveDateTime": recorded_at,
        "issued": recorded_at,
        "category": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                "code": "laboratory",
                "display": "Laboratory"
            }],
            "text": "Laboratory"
        }],
        "code": {"coding": [coding], "text": "ABO and Rh group [Type] in Blood"},
        "subject": {"reference": f"Patient/{patient_id}"},
        "valueCodeableConcept": {"text": data["blood_group"]},
        "performer": [{"display": author}],
    }]


def _upsert_observation(observation):
    identifier = observation["identifier"][0]
    response = requests.get(
        f"{FHIR_BASE}/Observation",
        params={"identifier": f"{identifier['system']}|{identifier['value']}"},
        headers={"Accept": "application/fhir+json"},
        timeout=15,
    )
    response.raise_for_status()
    entries = response.json().get("entry", [])
    if entries:
        observation["id"] = entries[0]["resource"]["id"]
        url = f"{FHIR_BASE}/Observation/{observation['id']}"
        method = requests.put
    else:
        url = f"{FHIR_BASE}/Observation"
        method = requests.post
    result = method(url, json=observation, headers={"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"}, timeout=15)
    result.raise_for_status()
    return result.json()


def import_echosos(raw_bytes, content_type=None, author="unknown"):
    url = extract_echosos_url(raw_bytes, content_type)
    data = parse_echosos_data(url)
    if not data["given"] or not data["family"] or not data["birth_date"]:
        raise ValueError("EchoSOS-Daten enthalten keinen vollständigen Namen und kein Geburtsdatum")
    existing = _patient_search(data)
    patient = _upsert_patient(_patient_resource(data, existing))
    observations = [_upsert_observation(item) for item in _blood_observations(data, patient["id"], author)]
    everything = requests.get(
        f"{FHIR_BASE}/Patient/{patient['id']}/$everything",
        params={"_count": 500},
        headers={"Accept": "application/fhir+json"},
        timeout=15,
    )
    everything.raise_for_status()
    return {
        "source": data,
        "patient": patient,
        "patient_id": patient["id"],
        "created": existing is None,
        "observations": observations,
        "everything": everything.json(),
    }
