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
from terminology.echosos import (
    ECHOSOS_ALLERGENS,
    ECHOSOS_ALLERGY_REACTIONS,
    ECHOSOS_MEDICAL_HISTORY,
    SNOMED_SYSTEM,
)

ECHOSOS_HOST = "eid.echosos.com"
ECHOSOS_IDENTIFIER_SYSTEM = "https://fhir.omnilink.ch/fhir/NamingSystem/echosos"
ECHOSOS_ALLERGY_IDENTIFIER_SYSTEM = "https://fhir.omnilink.ch/fhir/NamingSystem/echosos-allergy"
ECHOSOS_CONDITION_IDENTIFIER_SYSTEM = "https://fhir.omnilink.ch/fhir/NamingSystem/echosos-condition"
BLOOD_GROUP_LOINC = "882-1"
BLOOD_GROUPS = ["A-", "A+", "B-", "B+", "AB-", "AB+", "0-", "0+", "Unbekannt"]
ECHOSOS_CODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
ECHOSOS_ALLERGY_OPTIONS = (
    "Keine", "Penizillin", "Andere Antibiotika", "Entzündungshemmer", "Aspirin",
    "Kontrastmittel", "Curare (Anästhesie)", "Erdnüsse", "Nüsse", "Meeresfrüchte",
    "Bienenstich", "Wespenstich", "Andere",
)
ECHOSOS_ALLERGY_REACTION_OPTIONS = (
    "Hautrötung", "Schwellung der Haut", "Atemnot", "Angioödem", "Anaphylaxie",
)
ECHOSOS_MEDICATION_OPTIONS = (
    "Keine", "Antihypertensiva", "Betablocker", "Nitroderivate", "Antiarrhythmika",
    "Antikoagulantien", "Antidepressiva", "Neuroleptika", "Antiepileptika",
    "Antidiabetika vom Insulin-Typ", "Orale Antidiabetika", "Kortikoide",
    "Immunsuppressiva", "Antiphlogistikum", "Opiate", "Andere",
    "Amyloidgerichtete Therapie",
)
ECHOSOS_MEDICAL_HISTORY_OPTIONS = (
    "Keine", "Asthma", "Chronisch obstruktive Lungenerkrankung (COPD)",
    "Koronare Herzkrankheit", "Herzinsuffizienz", "Herzrhythmusstörungen",
    "Periphere arterielle Verschlusskrankheit", "Abdominales Aortenaneurysma",
    "Künstliche Herzklappen", "Störung der Blutgerinnung", "Krampfanfälle",
    "Nierenversagen/Dialyse", "Leberkrankheit", "Ansteckende Krankheit",
    "Herzschrittmacher/Defibrillator", "Andere", "Schwierige Intubation",
    "Organtransplantierter", "Diabetes",
)
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


def _decode_option_codes(params, key, options):
    encoded = _value(params, key)
    selections = []
    for character in encoded:
        try:
            index = ECHOSOS_CODE_ALPHABET.index(character)
            selections.append((index, options[index]))
        except (ValueError, IndexError) as exc:
            raise ValueError(f"Ungültiger EchoSOS-Auswahlcode im Feld {key}") from exc
    return selections


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
    emergency_contacts = []
    for contact_number in range(1, 4):
        contact_name = html.unescape(_value(params, f"n{contact_number}"))
        contact_phone = html.unescape(_value(params, f"p{contact_number}"))
        if contact_name or contact_phone:
            emergency_contacts.append({"name": contact_name, "phone": contact_phone})
    text_parser = _TextParser()
    text_parser.feed(page_html)
    text = text_parser.text()
    full_name = re.search(r"Notfallpass\s+([^\n]+)", text, re.IGNORECASE)
    if full_name and not first and not family:
        parts = full_name.group(1).split()
        first, family = (parts[0], parts[-1]) if len(parts) > 1 else (parts[0], "")
    blood_code = _value(params, "b")
    blood_group = BLOOD_GROUPS[int(blood_code)] if blood_code.isdigit() and int(blood_code) < len(BLOOD_GROUPS) else _label_value(text, "Blutgruppe")
    if blood_group not in BLOOD_GROUPS:
        blood_group = None

    allergy_codes = _decode_option_codes(params, "a", ECHOSOS_ALLERGY_OPTIONS)
    reaction_codes = _decode_option_codes(params, "r", ECHOSOS_ALLERGY_REACTION_OPTIONS)
    allergy_selections = []
    for position, (index, allergen) in enumerate(allergy_codes):
        if index == 0:
            continue
        reaction = reaction_codes[position][1] if position < len(reaction_codes) else None
        allergy_selections.append({"allergen": allergen, "reaction": reaction})

    medication_codes = _decode_option_codes(params, "m", ECHOSOS_MEDICATION_OPTIONS)
    medical_history_codes = _decode_option_codes(
        params, "d", ECHOSOS_MEDICAL_HISTORY_OPTIONS
    )
    organ_donation = {
        "outside_switzerland": {
            "0": "yes",
            "1": "no",
            "2": "no_information",
        }.get(_value(params, "o")),
        "swiss_registry": {
            "0": "registered",
            "1": "no_entry",
        }.get(_value(params, "s")),
    }

    return {
        "source_url": url,
        "given": first,
        "family": family,
        "birth_date": _date_from_echosos_code(_value(params, "g")) or _date_from_text(text),
        "blood_group": blood_group,
        "emergency_contact": emergency_contacts[0] if emergency_contacts else {"name": "", "phone": ""},
        "emergency_contacts": emergency_contacts,
        "allergy_selections": allergy_selections,
        "no_known_allergies": [index for index, _ in allergy_codes] == [0],
        "medication_selections": [label for index, label in medication_codes if index != 0],
        "medical_history_selections": [
            label for index, label in medical_history_codes if index != 0
        ],
        "organ_donation": organ_donation,
        "other_information": html.unescape(_value(params, "i")) or _label_value(text, "Sonstiges"),
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
    contacts_to_add = data.get("emergency_contacts") or [data.get("emergency_contact", {})]
    for contact in contacts_to_add:
        if not (contact.get("name") or contact.get("phone")):
            continue
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
        "performer": [{"reference": f"Patient/{patient_id}"}],
    }]


def _echosos_identifier(data, resource_type, selection_key):
    source = f"{data['source_url']}|{resource_type}|{selection_key}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _echosos_allergy_resources(data, patient_id):
    patient_reference = f"Patient/{patient_id}"
    resources = []
    selections = data.get("allergy_selections", [])

    if data.get("no_known_allergies") and not selections:
        selections = [{"allergen": "Keine", "reaction": None}]

    for position, selection in enumerate(selections):
        allergen = selection["allergen"]
        reaction = selection.get("reaction")
        identifier_value = _echosos_identifier(
            data,
            "allergy",
            f"{position}|{allergen}|{reaction or ''}",
        )

        allergy = {
            "resourceType": "AllergyIntolerance",
            "meta": {
                "profile": [
                    "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-allergyintolerance"
                ]
            },
            "identifier": [{
                "system": ECHOSOS_ALLERGY_IDENTIFIER_SYSTEM,
                "value": identifier_value,
            }],
            "clinicalStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                    "code": "active",
                }]
            },
            "verificationStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                    "code": "confirmed",
                }]
            },
            "type": "allergy",
            "patient": {"reference": patient_reference},
            "recorder": {"reference": patient_reference},
        }

        if allergen == "Keine":
            allergy["code"] = {
                "coding": [{
                    "system": SNOMED_SYSTEM,
                    "code": "716186003",
                    "display": "No known allergy",
                }],
                "text": "Keine bekannten Allergien",
            }
        else:
            allergy_mapping = next(
                (
                    options[allergen]
                    for options in ECHOSOS_ALLERGENS.values()
                    if allergen in options
                ),
                None,
            )
            if allergy_mapping:
                allergy["code"] = {
                    "coding": [allergy_mapping],
                    "text": allergen,
                }
            else:
                allergy["code"] = {"text": allergen}

            category = next(
                (
                    group
                    for group, options in ECHOSOS_ALLERGENS.items()
                    if allergen in options
                ),
                None,
            )
            category_code = {
                "Medikamente": "medication",
                "Lebensmittel": "food",
                "Insektengift": "environment",
            }.get(category)
            if category_code:
                allergy["category"] = [category_code]

            if reaction in ECHOSOS_ALLERGY_REACTIONS:
                manifestation = ECHOSOS_ALLERGY_REACTIONS[reaction]
                allergy["reaction"] = [{
                    "manifestation": [{
                        "coding": [manifestation],
                        "text": reaction,
                    }]
                }]

        resources.append(allergy)

    return resources


def _echosos_condition_resources(data, patient_id):
    patient_reference = f"Patient/{patient_id}"
    resources = []

    for position, label in enumerate(data.get("medical_history_selections", [])):
        condition = {
            "resourceType": "Condition",
            "identifier": [{
                "system": ECHOSOS_CONDITION_IDENTIFIER_SYSTEM,
                "value": _echosos_identifier(data, "condition", f"{position}|{label}"),
            }],
            "category": [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                    "code": "problem-list-item",
                    "display": "Problem List Item",
                }]
            }],
            "subject": {"reference": patient_reference},
            "asserter": {"reference": patient_reference},
            "verificationStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    "code": "confirmed",
                }]
            },
            "code": {"text": label},
        }

        mapping = ECHOSOS_MEDICAL_HISTORY.get(label)
        if mapping and not mapping.get("requires_disambiguation"):
            condition["code"] = {
                "coding": [mapping],
                "text": label,
            }

        resources.append(condition)

    return resources


def _upsert_resource(resource):
    resource_type = resource["resourceType"]
    identifier = resource["identifier"][0]
    response = requests.get(
        f"{FHIR_BASE}/{resource_type}",
        params={"identifier": identifier["value"]},
        headers={"Accept": "application/fhir+json"},
        timeout=15,
    )
    response.raise_for_status()
    entries = response.json().get("entry", [])
    if entries:
        resource["id"] = entries[0]["resource"]["id"]
        url = f"{FHIR_BASE}/{resource_type}/{resource['id']}"
        method = requests.put
    else:
        url = f"{FHIR_BASE}/{resource_type}"
        method = requests.post
    result = method(url, json=resource, headers={"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"}, timeout=15)
    result.raise_for_status()
    return result.json()


def _upsert_observation(observation):
    return _upsert_resource(observation)


def import_echosos(raw_bytes, content_type=None, author="unknown"):
    url = extract_echosos_url(raw_bytes, content_type)
    data = parse_echosos_data(url)
    if not data["given"] or not data["family"] or not data["birth_date"]:
        raise ValueError("EchoSOS-Daten enthalten keinen vollständigen Namen und kein Geburtsdatum")
    existing = _patient_search(data)
    patient = _upsert_patient(_patient_resource(data, existing))
    observations = [_upsert_observation(item) for item in _blood_observations(data, patient["id"], author)]
    allergies = [
        _upsert_resource(item)
        for item in _echosos_allergy_resources(data, patient["id"])
    ]
    conditions = [
        _upsert_resource(item)
        for item in _echosos_condition_resources(data, patient["id"])
    ]
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
        "allergies": allergies,
        "conditions": conditions,
        "everything": everything.json(),
    }
