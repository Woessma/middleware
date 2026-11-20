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
from fhir.narrative import ensure_resource_narrative
from services.patient_service import warn_if_external_patient_duplicate
from services.fhir_mdm_service import find_mdm_match
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


class EchoSosPatientMatchConflictError(ValueError):
    pass


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


def to_poc_notfall_logobject(data):
    emergency_contacts = []
    for contact in data.get("emergency_contacts", []):
        name_parts = contact.get("name", "").split(maxsplit=1)
        emergency_contacts.append({
            "firstName": name_parts[0] if name_parts else None,
            "lastName": name_parts[1] if len(name_parts) > 1 else None,
            "phone": contact.get("phone") or None,
            "relationship": None,
            "isHealthcareProxy": None,
            "isHearingImpairedOrRestricted": None,
        })

    organ_donation = data.get("organ_donation") or {}
    organ_donor = (
        True
        if organ_donation.get("outside_switzerland") == "yes"
        or organ_donation.get("swiss_registry") == "registered"
        else False
        if organ_donation.get("outside_switzerland") == "no"
        else None
    )
    medications = data.get("medications")
    if medications:
        medications = [medications]
    else:
        medications = data.get("medication_selections", [])

    return {
        "createdAt": datetime.now(timezone.utc).date().isoformat(),
        "personal": {
            "firstName": data.get("given") or None,
            "lastName": data.get("family") or None,
            "dateOfBirth": data.get("birth_date"),
            "sex": None,
            "memberNumber": None,
        },
        "emergencyContacts": emergency_contacts,
        "medical": {
            "bloodGroup": data.get("blood_group"),
            "preExistingConditions": data.get("medical_history_selections", []),
            "diagnosesFreeText": [],
            "medications": medications,
            "allergies": [
                {
                    "substance": selection["allergen"],
                    "reaction": selection.get("reaction"),
                }
                for selection in data.get("allergy_selections", [])
            ],
            "pregnancy": None,
            "pregnancyDueDate": None,
            "specialNotes": data.get("other_information") or None,
            "specialClinic": None,
        },
        "implants": {
            "pacemaker": None,
            "pacemakerWithDefibrillator": None,
            "cochlearImplant": None,
            "insulinPump": None,
        },
        "provision": {
            "livingWill": None,
            "livingWillLocation": None,
            "organDonor": organ_donor,
            "hasDependents": None,
            "dependentsNotes": None,
            "dependentsCaregiver": None,
        },
    }


def _fhir_concept_text(concept):
    if not isinstance(concept, dict):
        return None
    text = concept.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    codings = concept.get("coding", [])
    for coding in codings if isinstance(codings, list) else []:
        if isinstance(coding, dict):
            display = coding.get("display")
            if isinstance(display, str) and display.strip():
                return display.strip()
    return None


def _fhir_concept_codes(concept):
    if not isinstance(concept, dict):
        return set()
    codings = concept.get("coding", [])
    if not isinstance(codings, list):
        return set()
    return {
        coding["code"]
        for coding in codings
        if isinstance(coding, dict) and isinstance(coding.get("code"), str)
    }


def _append_unique(values, value):
    if not value:
        return
    normalized = value.casefold()
    if not any(
        isinstance(item, str) and item.casefold() == normalized
        for item in values
    ):
        values.append(value)


def _fhir_name_parts(name):
    if not isinstance(name, dict):
        return None, None
    given = name.get("given")
    first_name = (
        " ".join(
            item.strip()
            for item in given
            if isinstance(item, str) and item.strip()
        )
        if isinstance(given, list)
        else ""
    )
    last_name = name.get("family") if isinstance(name.get("family"), str) else ""
    if first_name or last_name:
        return first_name or None, last_name or None
    text = name.get("text")
    parts = text.split(maxsplit=1) if isinstance(text, str) else []
    return parts[0] if parts else None, parts[1] if len(parts) > 1 else None


def enrich_poc_notfall_logobject(logobject, patient, bundle):
    result = copy.deepcopy(logobject)
    entries = bundle.get("entry", []) if isinstance(bundle, dict) else []
    resources = [
        entry["resource"]
        for entry in entries
        if isinstance(entry, dict)
        and isinstance(entry.get("resource"), dict)
    ] if isinstance(entries, list) else []
    fhir_patient = next(
        (resource for resource in resources if resource.get("resourceType") == "Patient"),
        patient,
    )

    personal = result["personal"]
    names = fhir_patient.get("name") or []
    name = names[0] if isinstance(names, list) and names else {}
    given_name, family_name = _fhir_name_parts(name)
    for field, value in (
        ("firstName", given_name),
        ("lastName", family_name),
        ("dateOfBirth", fhir_patient.get("birthDate")),
        ("sex", {
            "male": "M",
            "female": "W",
            "other": "D",
        }.get(fhir_patient.get("gender"))),
    ):
        if personal.get(field) is None and value:
            personal[field] = value
    if personal.get("memberNumber") is None:
        for identifier in fhir_patient.get("identifier") or []:
            type_concept = identifier.get("type") or {}
            if "MB" in _fhir_concept_codes(type_concept):
                personal["memberNumber"] = identifier.get("value") or None
                if personal["memberNumber"]:
                    break

    contacts = result["emergencyContacts"]
    for contact in fhir_patient.get("contact") or []:
        relationships = contact.get("relationship", [])
        if not isinstance(relationships, list):
            relationships = [relationships]
        relationship_codes = set()
        relationship_text = None
        for relationship in relationships:
            relationship_codes.update(_fhir_concept_codes(relationship))
            relationship_text = relationship_text or _fhir_concept_text(relationship)
        if "ECON" not in relationship_codes and not any(
            term in (relationship_text or "").casefold()
            for term in ("emergency", "notfall")
        ):
            continue

        first_name, last_name = _fhir_name_parts(contact.get("name"))
        telecoms = contact.get("telecom", [])
        phone = next(
            (
                telecom.get("value")
                for telecom in (telecoms if isinstance(telecoms, list) else [])
                if isinstance(telecom, dict)
                and telecom.get("system") == "phone"
                and telecom.get("value")
            ),
            None,
        )
        matching = next(
            (
                item for item in contacts
                if (phone and item.get("phone") == phone)
                or (
                    first_name
                    and last_name
                    and (item.get("firstName") or "").casefold() == first_name.casefold()
                    and (item.get("lastName") or "").casefold() == last_name.casefold()
                )
            ),
            None,
        )
        if matching is None:
            contacts.append({
                "firstName": first_name,
                "lastName": last_name,
                "phone": phone,
                "relationship": relationship_text,
                "isHealthcareProxy": None,
                "isHearingImpairedOrRestricted": None,
            })
        else:
            for key, value in (
                ("firstName", first_name),
                ("lastName", last_name),
                ("phone", phone),
                ("relationship", relationship_text),
            ):
                if matching.get(key) is None and value:
                    matching[key] = value

    condition_values = result["medical"]["preExistingConditions"]
    diagnosis_values = result["medical"]["diagnosesFreeText"]
    allergies = result["medical"]["allergies"]
    medications = result["medical"]["medications"]
    medication_names = {
        f"Medication/{resource['id']}": _fhir_concept_text(resource.get("code"))
        for resource in resources
        if resource.get("resourceType") == "Medication"
        and resource.get("id")
        and _fhir_concept_text(resource.get("code"))
    }
    organ_donor_values = set()

    for resource in resources:
        resource_type = resource.get("resourceType")
        if resource_type == "Condition":
            code = resource.get("code") or {}
            text = _fhir_concept_text(code)
            if text:
                target = condition_values if code.get("coding") else diagnosis_values
                _append_unique(target, text)
        elif resource_type in {"MedicationStatement", "MedicationRequest"}:
            if resource.get("status") != "active":
                continue
            medication = resource.get("medicationCodeableConcept") or {}
            reference = resource.get("medicationReference") or {}
            text = (
                _fhir_concept_text(medication)
                or reference.get("display")
                or medication_names.get(reference.get("reference"))
            )
            if text:
                dosage = resource.get("dosage") or resource.get("dosageInstruction") or []
                dosage_text = next(
                    (
                        item.get("text")
                        for item in dosage
                        if isinstance(item, dict) and item.get("text")
                    ),
                    None,
                )
                _append_unique(
                    medications,
                    f"{text} {dosage_text}".strip() if dosage_text else text,
                )
        elif resource_type == "AllergyIntolerance":
            code = resource.get("code") or {}
            if "716186003" in _fhir_concept_codes(code):
                continue
            substance = _fhir_concept_text(code)
            if not substance:
                continue
            reactions = []
            for reaction in resource.get("reaction") or []:
                for manifestation in reaction.get("manifestation") or []:
                    _append_unique(reactions, _fhir_concept_text(manifestation))
            reaction_text = "; ".join(reactions) or None
            matching = next(
                (
                    item for item in allergies
                    if item.get("substance", "").casefold() == substance.casefold()
                ),
                None,
            )
            if matching is None:
                allergies.append({"substance": substance, "reaction": reaction_text})
            elif matching.get("reaction") is None and reaction_text:
                matching["reaction"] = reaction_text
        elif resource_type == "Observation":
            codes = _fhir_concept_codes(resource.get("code"))
            if BLOOD_GROUP_LOINC in codes and result["medical"]["bloodGroup"] is None:
                result["medical"]["bloodGroup"] = (
                    _fhir_concept_text(resource.get("valueCodeableConcept"))
                    or resource.get("valueString")
                )
            if "82810-3" in codes and result["medical"]["pregnancy"] is None:
                value = resource.get("valueBoolean")
                value_concept = resource.get("valueCodeableConcept") or {}
                value_codes = _fhir_concept_codes(value_concept)
                value_text = (_fhir_concept_text(value_concept) or "").casefold()
                if isinstance(value, bool):
                    result["medical"]["pregnancy"] = value
                elif (
                    "60001007" in value_codes
                    or "not pregnant" in value_text
                    or "nicht schwanger" in value_text
                ):
                    result["medical"]["pregnancy"] = False
                elif (
                    "77386006" in value_codes
                    or "pregnant" in value_text
                    or "schwanger" in value_text
                ):
                    result["medical"]["pregnancy"] = True
        elif resource_type == "Consent":
            categories = resource.get("category") or []
            category_codes = set().union(*(
                _fhir_concept_codes(category)
                for category in categories
            ))
            category_text = " ".join(
                filter(None, (
                    _fhir_concept_text(category)
                    for category in categories
                ))
            ).casefold()
            if "42348-3" in category_codes or "organ" in category_text:
                consent_type = (resource.get("provision") or {}).get("type")
                if resource.get("status") in {None, "active"}:
                    if consent_type == "permit":
                        organ_donor_values.add(True)
                    elif consent_type == "deny":
                        organ_donor_values.add(False)
        elif resource_type == "Device":
            device_names = resource.get("deviceName") or []
            device_text = " ".join(filter(None, [
                _fhir_concept_text(resource.get("type")),
                *(
                    item.get("name")
                    for item in device_names
                    if isinstance(item, dict)
                ),
            ])).casefold()
            if "pacemaker" in device_text or "herzschrittmacher" in device_text:
                result["implants"]["pacemaker"] = True
            if "defibrillator" in device_text:
                result["implants"]["pacemakerWithDefibrillator"] = True
            if "cochlear" in device_text or "kochlea" in device_text:
                result["implants"]["cochlearImplant"] = True
            if "insulin pump" in device_text or "insulinpumpe" in device_text:
                result["implants"]["insulinPump"] = True
        elif resource_type == "RelatedPerson":
            relationships = resource.get("relationship", [])
            if not isinstance(relationships, list):
                relationships = [relationships]
            relation_text = " ".join(filter(None, (
                _fhir_concept_text(relationship)
                for relationship in relationships
            ))).casefold()
            relation_codes = set().union(*(
                _fhir_concept_codes(relationship)
                for relationship in relationships
            ))
            if (
                relation_codes.intersection({"CHILD", "CHLD"})
                or "child" in relation_text
                or "kind" in relation_text
            ):
                result["provision"]["hasDependents"] = True

    if result["provision"]["organDonor"] is None and len(organ_donor_values) == 1:
        result["provision"]["organDonor"] = organ_donor_values.pop()
    return result


def _patient_search(data, check_external_duplicates=True):
    search_params = {
        "family": data["family"],
        "given": data["given"],
        "birthdate": data["birth_date"],
    }
    response = requests.get(
        f"{FHIR_BASE}/Patient",
        params=search_params,
        headers={"Accept": "application/fhir+json"},
        timeout=15,
    )
    response.raise_for_status()
    result = response.json()
    if check_external_duplicates:
        warn_if_external_patient_duplicate(search_params, "family-given-birthdate")
    entries = result.get("entry", [])
    if result.get("total", len(entries)) > 1 or len(entries) > 1:
        raise EchoSosPatientMatchConflictError(
            "EchoSOS-Patientensuche mit Name und Geburtsdatum ist nicht eindeutig"
        )
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
                    "code": "unconfirmed",
                }]
            },
            "type": "allergy",
            "patient": {"reference": patient_reference},
            "recorder": {"reference": patient_reference},
            "asserter": {"reference": patient_reference},
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
    if resource.get("resourceType") == "AllergyIntolerance":
        for key in ("verificationStatus", "asserter", "recorder"):
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
        if resource_type == "AllergyIntolerance":
            # A patient reimport must not replace an existing clinical assessment.
            for key in ("verificationStatus", "asserter", "recorder"):
                if key in existing:
                    resource[key] = copy.deepcopy(existing[key])
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
    ensure_resource_narrative(resource)
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
    warn_if_external_patient_duplicate(
        {
            "family": data["family"],
            "given": data["given"],
            "birthdate": data["birth_date"],
        },
        "family-given-birthdate",
    )
    patient = _patient_resource(data)
    ensure_resource_narrative(patient)
    existing = find_mdm_match(patient)
    return build_echosos_transaction(data, patient, existing, author)


def build_echosos_transaction(data, patient, existing, author):
    if existing:
        patient_id = existing["id"]
        patient_reference = f"Patient/{patient_id}"
        patient_entry = None
    else:
        patient_reference = f"urn:uuid:{uuid4()}"
        patient_entry = {
            "fullUrl": patient_reference,
            "resource": patient,
            "request": {"method": "POST", "url": "Patient"},
        }

    resources = _blood_observations(data, patient_reference, author)
    resources.extend(_echosos_allergy_resources(data, patient_reference))
    resources.extend(_echosos_condition_resources(data, patient_reference))
    resources.extend(_echosos_organ_donation_consents(data, patient_reference))

    entries = [_transaction_entry(item) for item in resources]
    if patient_entry:
        entries.insert(0, patient_entry)
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": entries,
    }
