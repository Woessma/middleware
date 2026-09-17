from html import escape

from domain.patient import PatientData

CH_CORE_PROFILE = (
    "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-patient"
)

PATIENT_BIRTH_PLACE_URL = (
    "http://hl7.org/fhir/StructureDefinition/patient-birthPlace"
)

PATIENT_RELIGION_URL = (
    "http://hl7.org/fhir/StructureDefinition/patient-religion"
)

PATIENT_CONTACT_IDENTIFIER_URL = (
    "https://woess.ch/fhir/StructureDefinition/patient-contact-identifier"
)


def _normalized_string(value):

    if value is None:
        return None

    return " ".join(str(value).strip().lower().split())


def _normalized_lines(lines):

    return [
        _normalized_string(line)
        for line in (lines or [])
        if _normalized_string(line)
    ]


def _is_subset_value(candidate, existing):

    if candidate == existing:
        return True

    if isinstance(candidate, str) and isinstance(existing, str):
        candidate_norm = _normalized_string(candidate)
        existing_norm = _normalized_string(existing)

        if not candidate_norm:
            return True

        if not existing_norm:
            return False

        return (
            candidate_norm == existing_norm
            or existing_norm.startswith(candidate_norm)
        )

    if isinstance(candidate, list) and isinstance(existing, list):
        if all(isinstance(item, str) for item in candidate + existing):
            candidate_norm = _normalized_lines(candidate)
            existing_norm = _normalized_lines(existing)

            if not candidate_norm:
                return True

            if len(candidate_norm) != len(existing_norm):
                return False

            return all(
                _is_subset_value(cand, exist)
                for cand, exist in zip(
                    candidate_norm,
                    existing_norm,
                )
            )

        return candidate == existing

    return False


def _resource_dict_subset(candidate: dict, existing: dict) -> bool:

    for key, candidate_value in candidate.items():
        existing_value = existing.get(key)

        if key not in existing:
            return False

        if not _is_subset_value(candidate_value, existing_value):
            return False

    return True


def _dedupe_resource_dicts(items: list[dict]) -> list[dict]:

    deduped = []

    for item in items:
        replaced_existing = False
        skip_item = False

        for index, existing in enumerate(deduped):
            if _resource_dict_subset(item, existing):
                skip_item = True
                break

            if _resource_dict_subset(existing, item):
                deduped[index] = item
                replaced_existing = True
                break

        if skip_item:
            continue

        if not replaced_existing:
            deduped.append(item)

    return deduped


def _field_richness(value):

    if value is None:
        return 0

    if isinstance(value, str):
        return 1 if value.strip() else 0

    if isinstance(value, list):
        return sum(_field_richness(item) for item in value)

    if isinstance(value, dict):
        return sum(_field_richness(item) for item in value.values())

    return 1


def _dedupe_human_name_dicts(items: list[dict]) -> list[dict]:

    deduped_by_key = {}
    ordered_keys = []

    for item in items:
        key = (
            _normalized_string(item.get("family")),
            tuple(_normalized_lines(item.get("given", []))),
        )

        if key == (None, ()):
            key = (
                _normalized_string(item.get("text")),
                (),
            )

        current = deduped_by_key.get(key)

        if current is None:
            deduped_by_key[key] = item
            ordered_keys.append(key)
            continue

        current_score = _field_richness(current)
        item_score = _field_richness(item)

        if item_score > current_score:
            deduped_by_key[key] = item

    return [deduped_by_key[key] for key in ordered_keys]


def build_codeable_concept(concept):

    if concept is None:
        return None

    result = {}
    codings = list(concept.codings)
    coding = {}

    if concept.system:
        coding["system"] = concept.system

    if concept.code:
        coding["code"] = concept.code

    if concept.display:
        coding["display"] = concept.display

    if coding:
        codings.append(coding)

    if codings:
        result["coding"] = codings

    if concept.text:
        result["text"] = concept.text

    return result or None


def build_address(address):

    result = {}

    if address.use:
        result["use"] = address.use

    if address.lines:
        result["line"] = address.lines

    if address.postal_code:
        result["postalCode"] = address.postal_code

    if address.city:
        result["city"] = address.city

    if address.state:
        result["state"] = address.state

    if address.country:
        result["country"] = address.country

    if address.text:
        result["text"] = address.text

    return result


def build_telecom(telecom):

    result = {
        "system": telecom.system,
        "value": telecom.value,
    }

    if telecom.use:
        result["use"] = telecom.use

    return result


def build_human_name(name):

    result = {}

    if name.use:
        result["use"] = name.use

    if name.family:
        result["family"] = name.family

    if name.given:
        result["given"] = name.given

    if name.prefix:
        result["prefix"] = name.prefix

    if name.suffix:
        result["suffix"] = name.suffix

    if name.text:
        result["text"] = name.text

    return result


def build_identifier(identifier):

    result = {
        "system": identifier.system,
        "value": identifier.value,
    }

    if identifier.use:
        result["use"] = identifier.use

    if identifier.type:
        result["type"] = build_codeable_concept(
            identifier.type
        )

    return result


def _format_patient_name(resource):

    names = resource.get("name") or []

    if not names:
        return "Unbekannter Patient"

    name = names[0]

    if name.get("text"):
        return name["text"]

    given = " ".join(name.get("given") or [])
    family = name.get("family") or ""

    return " ".join(
        part for part in [given, family] if part
    ) or "Unbekannter Patient"


def _format_patient_address(resource):

    addresses = resource.get("address") or []

    if not addresses:
        return ""

    address = addresses[0]

    return " ".join(
        part
        for part in [
            " ".join(address.get("line") or []),
            address.get("postalCode"),
            address.get("city"),
            address.get("country"),
        ]
        if part
    )


def set_patient_narrative(resource):

    patient_name = _format_patient_name(resource)
    gender = resource.get("gender") or "unknown"
    birth_date = resource.get("birthDate") or "unknown"
    address = _format_patient_address(resource)

    resource["text"] = {
        "status": "generated",
        "div": (
            "<div xmlns=\"http://www.w3.org/1999/xhtml\">"
            f"<p><b>Generated Narrative: Patient {escape(resource.get('id') or '')}</b></p>"
            f"<p>{escape(patient_name)} {escape(gender)}, DoB: {escape(birth_date)}</p>"
            + (
                f"<p>Contact Detail {escape(address)}</p>"
                if address
                else ""
            )
            + "</div>"
        ),
    }

def build_ch_core_patient(patient: PatientData) -> dict:

    resource = {
        "resourceType": "Patient",
        "meta": {
            "profile": [
                CH_CORE_PROFILE
            ]
        }
    }

    if patient.identifiers:
        resource["identifier"] = [
            build_identifier(identifier)
            for identifier in patient.identifiers
        ]

    if patient.names:
        resource["name"] = _dedupe_human_name_dicts([
            build_human_name(name)
            for name in patient.names
        ])

    if patient.gender:
        resource["gender"] = patient.gender

    if patient.birth_date:
        resource["birthDate"] = patient.birth_date

    if patient.addresses:

        resource["address"] = _dedupe_resource_dicts([
            build_address(address)
            for address in patient.addresses
        ])

    if patient.telecoms:

        resource["telecom"] = _dedupe_resource_dicts([
            build_telecom(telecom)
            for telecom in patient.telecoms
        ])

    if patient.marital_status:
        resource["maritalStatus"] = build_codeable_concept(
            patient.marital_status
        )

    if patient.communications:
        resource["communication"] = []

        for communication in patient.communications:
            communication_entry = {
                "language": build_codeable_concept(
                    communication.language
                )
            }

            if communication.preferred is not None:
                communication_entry["preferred"] = (
                    communication.preferred
                )

            resource["communication"].append(
                communication_entry
            )

    if patient.contacts:
        resource["contact"] = []

        for contact in patient.contacts:
            contact_entry = {}

            if contact.relationship:
                contact_entry["relationship"] = [
                    build_codeable_concept(
                        contact.relationship
                    )
                ]

            if contact.name:
                contact_entry["name"] = build_human_name(
                    contact.name
                )

            if contact.address:
                contact_entry["address"] = build_address(
                    contact.address
                )

            if contact.telecoms:
                contact_entry["telecom"] = [
                    build_telecom(telecom)
                    for telecom in contact.telecoms
                ]

            if contact.identifiers:
                contact_entry["extension"] = [
                    {
                        "url": PATIENT_CONTACT_IDENTIFIER_URL,
                        "valueIdentifier": build_identifier(
                            identifier
                        ),
                    }
                    for identifier in contact.identifiers
                ]

            resource["contact"].append(contact_entry)

    if patient.active is not None:
        resource["active"] = patient.active

    if patient.deceased is not None:
        resource["deceasedBoolean"] = patient.deceased

    extensions = []

    if patient.place_of_birth:
        extensions.append(
            {
                "url": PATIENT_BIRTH_PLACE_URL,
                "valueAddress": build_address(
                    patient.place_of_birth
                )
            }
        )

    if patient.religion:
        extensions.append(
            {
                "url": PATIENT_RELIGION_URL,
                "valueCodeableConcept": build_codeable_concept(
                    patient.religion
                )
            }
        )

    if extensions:
        resource["extension"] = extensions

    set_patient_narrative(resource)

    return resource