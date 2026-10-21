import copy
import hashlib
import html
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urlsplit
from uuid import uuid4

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
ECHOSOS_CONSENT_IDENTIFIER_SYSTEM = "https://fhir.omnilink.ch/fhir/NamingSystem/echosos-organ-donation-consent"
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
    result = response.json()
    entries = result.get("entry", [])
    if result.get("total", len(entries)) > 1 or len(entries) > 1:
        raise ValueError("EchoSOS-Patientensuche mit Name und Geburtsdatum ist nicht eindeutig")
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


def _patient_reference(patient_id):
    if patient_id.startswith(("Patient/", "urn:uuid:")):
        return patient_id
    return f"Patient/{patient_id}"


def _blood_observations(data, patient_id, author):
    if not data.get("blood_group"):
        return []
    coding = {"system": "http://loinc.org", "code": BLOOD_GROUP_LOINC}
    validation = validate_coding(coding)
    if validation.get("status") != "validated":
        raise ValueError(f"LOINC {BLOOD_GROUP_LOINC} konnte über den TX-Server nicht validiert werden")
    digest = _patient_selection_identifier(data, BLOOD_GROUP_LOINC, data["blood_group"])
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
        "subject": {"reference": _patient_reference(patient_id)},
        "valueCodeableConcept": {"text": data["blood_group"]},
        "performer": [{"reference": _patient_reference(patient_id)}],
    }]


def _patient_selection_identifier(data, *selection):
    identity = [
        data["given"].strip().casefold(),
        data["family"].strip().casefold(),
        data["birth_date"],
        *selection,
    ]
    return hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _echosos_allergy_resources(data, patient_id):
    patient_reference = _patient_reference(patient_id)
    resources = []
    selections = data.get("allergy_selections", [])

    if data.get("no_known_allergies") and not selections:
        selections = [{"allergen": "Keine", "reaction": None}]

    for selection in selections:
        allergen = selection["allergen"]
        reaction = selection.get("reaction")
        identifier_value = _patient_selection_identifier(data, allergen, reaction or "")

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
    patient_reference = _patient_reference(patient_id)
    resources = []

    for label in data.get("medical_history_selections", []):
        condition = {
            "resourceType": "Condition",
            "identifier": [{
                "system": ECHOSOS_CONDITION_IDENTIFIER_SYSTEM,
                "value": _patient_selection_identifier(data, label),
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


def _echosos_organ_donation_consents(data, patient_id):
    organ_donation = data.get("organ_donation") or {}
    swiss_registry = organ_donation.get("swiss_registry")

    if swiss_registry is not None:
        provision_type = "permit" if swiss_registry == "registered" else None
    else:
        provision_type = {
            "yes": "permit",
            "no": "deny",
        }.get(organ_donation.get("outside_switzerland"))

    if provision_type is None:
        return []

    patient_reference = _patient_reference(patient_id)
    return [{
        "resourceType": "Consent",
        "identifier": [{
            "system": ECHOSOS_CONSENT_IDENTIFIER_SYSTEM,
            "value": _patient_selection_identifier(data, "organ-donation-consent", provision_type),
        }],
        "status": "active",
        "scope": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/consentscope",
                "code": "adr",
                "display": "Advance Care Directive",
            }]
        },
        "category": [{
            "coding": [{
                "system": "http://loinc.org",
                "code": "42348-3",
                "display": "Advance directives",
            }]
        }],
        "patient": {"reference": patient_reference},
        "performer": [{"reference": patient_reference}],
        "provision": {"type": provision_type},
    }]


def _clinical_identity(resource):
    payload = copy.deepcopy(resource)
    for key in ("id", "meta", "identifier", "text"):
        payload.pop(key, None)
    if _is_echosos_blood_observation(resource):
        # These are import timestamps, not distinct blood-group measurements.
        for key in ("effectiveDateTime", "issued"):
            payload.pop(key, None)

    def without_display(value):
        if isinstance(value, dict):
            return {
                key: without_display(item)
                for key, item in value.items()
                if key != "display"
            }
        if isinstance(value, list):
            return [without_display(item) for item in value]
        return value

    return json.dumps(without_display(payload), sort_keys=True, ensure_ascii=False)


def _is_echosos_blood_observation(resource):
    return (
        resource.get("resourceType") == "Observation"
        and any(item.get("system") == ECHOSOS_IDENTIFIER_SYSTEM for item in resource.get("identifier", []))
        and any(
            item.get("system") == "http://loinc.org" and item.get("code") == BLOOD_GROUP_LOINC
            for item in resource.get("code", {}).get("coding", [])
        )
    )


def _existing_resource_id(resource):
    resource_type = resource["resourceType"]
    identifiers = resource.get("identifier", [])
    if isinstance(identifiers, dict):
        identifiers = [identifiers]
    identifier = next(
        (item for item in identifiers if item.get("system") and item.get("value")),
        None,
    )
    if identifier is None:
        return None
    response = requests.get(
        f"{FHIR_BASE}/{resource_type}",
        params={"identifier": f"{identifier['system']}|{identifier['value']}"},
        headers={"Accept": "application/fhir+json"},
        timeout=15,
    )
    response.raise_for_status()
    entries = response.json().get("entry", [])
    if len(entries) > 1:
        raise ValueError(f"EchoSOS-Identifier fuer {resource_type} ist nicht eindeutig")
    legacy_system = {
        "AllergyIntolerance": ECHOSOS_ALLERGY_IDENTIFIER_SYSTEM,
        "Condition": ECHOSOS_CONDITION_IDENTIFIER_SYSTEM,
        "Consent": ECHOSOS_CONSENT_IDENTIFIER_SYSTEM,
    }.get(resource_type)
    if _is_echosos_blood_observation(resource):
        legacy_system = ECHOSOS_IDENTIFIER_SYSTEM
    patient_field = "subject" if resource_type in ("Condition", "Observation") else "patient"
    patient_reference = resource.get(patient_field, {}).get("reference", "")
    if (
        not entries
        and legacy_system is not None
        and patient_reference.startswith("Patient/")
    ):
        # Match older URL-based identifiers without merging other clinical sources.
        response = requests.get(
            f"{FHIR_BASE}/{resource_type}",
            params={"patient": patient_reference, "_count": "100"},
            headers={"Accept": "application/fhir+json"},
            timeout=15,
        )
        response.raise_for_status()
        bundle = response.json()
        if any(link.get("relation") == "next" for link in bundle.get("link", [])):
            raise ValueError(f"EchoSOS-{resource_type}-Abgleich unvollständig: mehr als eine Ergebnisseite")
        identity = _clinical_identity(resource)
        candidates = [
            entry
            for entry in bundle.get("entry", [])
            if any(
                item.get("system") == legacy_system
                for item in entry.get("resource", {}).get("identifier", [])
            )
            and _clinical_identity(entry.get("resource", {})) == identity
        ]
        entries = sorted(candidates, key=lambda entry: entry["resource"]["id"])[:1]
    if entries:
        existing = entries[0].get("resource", {})
        for item in existing.get("identifier", []):
            if item not in identifiers:
                identifiers.append(item)
        resource["identifier"] = identifiers
        if _is_echosos_blood_observation(resource) and _clinical_identity(existing) == _clinical_identity(resource):
            for key in ("effectiveDateTime", "issued"):
                if key in existing:
                    resource[key] = existing[key]
                else:
                    resource.pop(key, None)
    return entries[0].get("resource", {}).get("id") if entries else None


def _transaction_entry(resource):
    resource_type = resource["resourceType"]
    existing_id = _existing_resource_id(resource)
    identifiers = resource.get("identifier", [])
    if isinstance(identifiers, dict):
        identifiers = [identifiers]
    identifier = next(
        (item for item in identifiers if item.get("system") and item.get("value")),
        None,
    )

    if existing_id:
        resource["id"] = existing_id
        return {
            "fullUrl": f"{FHIR_BASE.rstrip('/')}/{resource_type}/{existing_id}",
            "resource": resource,
            "request": {"method": "PUT", "url": f"{resource_type}/{existing_id}"},
        }

    request = {"method": "POST", "url": resource_type}
    if identifier:
        conditional = quote(
            f"{identifier['system']}|{identifier['value']}",
            safe="",
        )
        request["ifNoneExist"] = f"identifier={conditional}"
    return {
        "fullUrl": f"urn:uuid:{uuid4()}",
        "resource": resource,
        "request": request,
    }


def import_echosos(raw_bytes, content_type=None, author="unknown"):
    url = extract_echosos_url(raw_bytes, content_type)
    data = parse_echosos_data(url)
    if not data["given"] or not data["family"] or not data["birth_date"]:
        raise ValueError("EchoSOS-Daten enthalten keinen vollständigen Namen und kein Geburtsdatum")
    existing = _patient_search(data)
    patient = _patient_resource(data, existing)
    if existing:
        patient_id = existing["id"]
        patient_reference = f"Patient/{patient_id}"
        patient_entry = {
            "fullUrl": f"{FHIR_BASE.rstrip('/')}/Patient/{patient_id}",
            "resource": patient,
            "request": {"method": "PUT", "url": f"Patient/{patient_id}"},
        }
    else:
        patient_reference = f"urn:uuid:{uuid4()}"
        patient_entry = {
            "fullUrl": patient_reference,
            "resource": patient,
            "request": {
                "method": "POST",
                "url": "Patient",
                "ifNoneExist": (
                    f"family={quote(data['family'], safe='')}&"
                    f"given={quote(data['given'], safe='')}&"
                    f"birthdate={quote(data['birth_date'], safe='')}"
                ),
            },
        }

    resources = _blood_observations(data, patient_reference, author)
    resources.extend(_echosos_allergy_resources(data, patient_reference))
    resources.extend(_echosos_condition_resources(data, patient_reference))
    resources.extend(_echosos_organ_donation_consents(data, patient_reference))

    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [patient_entry] + [_transaction_entry(item) for item in resources],
    }
