import hashlib
import uuid

from domain.patient import (
    Address,
    CodeableConcept,
    HumanName,
    Identifier,
    PatientContact,
    Telecom,
)


CH_CORE_RELATED_PERSON_PROFILE = (
    "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-relatedperson"
)

RELATED_PERSON_IDENTIFIER_SYSTEM = (
    "https://woess.ch/fhir/NamingSystem/cda-import-relatedperson"
)


def _build_codeable_concept(concept: CodeableConcept | None) -> dict | None:
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


def _build_human_name(name: HumanName | None) -> dict | None:
    if name is None:
        return None

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

    return result or None


def _build_address(address: Address | None) -> dict | None:
    if address is None:
        return None

    result = {}

    if address.use:
        result["use"] = address.use

    if address.lines:
        result["line"] = address.lines

    if address.city:
        result["city"] = address.city

    if address.state:
        result["state"] = address.state

    if address.postal_code:
        result["postalCode"] = address.postal_code

    if address.country:
        result["country"] = address.country

    if address.text:
        result["text"] = address.text

    return result or None


def _build_telecom(telecom: Telecom) -> dict:
    result = {
        "system": telecom.system,
        "value": telecom.value,
    }

    if telecom.use:
        result["use"] = telecom.use

    return result


def _build_identifier(identifier: Identifier) -> dict:
    result = {
        "system": identifier.system,
        "value": identifier.value,
    }

    if identifier.use:
        result["use"] = identifier.use

    if identifier.type:
        identifier_type = _build_codeable_concept(identifier.type)
        if identifier_type:
            result["type"] = identifier_type

    return result


def _contact_fingerprint(patient_reference: str, contact: PatientContact) -> str:
    name = contact.name.text if contact.name and contact.name.text else ""

    if not name and contact.name is not None:
        name = " ".join(
            [
                *(contact.name.given or []),
                contact.name.family or "",
            ]
        ).strip()

    relationship = ""

    if contact.relationship:
        relationship = "|".join(
            [
                contact.relationship.system or "",
                contact.relationship.code or "",
                contact.relationship.text or "",
            ]
        )

    telecom_values = "|".join(
        f"{item.system}:{item.value}:{item.use or ''}"
        for item in contact.telecoms
    )

    address = ""

    if contact.address:
        address = "|".join(
            [
                " ".join(contact.address.lines or []),
                contact.address.city or "",
                contact.address.state or "",
                contact.address.postal_code or "",
                contact.address.country or "",
            ]
        )

    raw = "|".join(
        [
            patient_reference,
            name,
            relationship,
            telecom_values,
            address,
        ]
    )

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _stable_related_person_id(identifier_system: str, identifier_value: str) -> str:
    stable_uuid = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"{identifier_system}|{identifier_value}",
    )

    return f"relatedperson-{stable_uuid}"


def build_ch_core_related_persons(
    patient_reference: str,
    contacts: list[PatientContact],
) -> list[dict]:
    resources = []

    for contact in contacts:
        resource = {
            "resourceType": "RelatedPerson",
            "meta": {
                "profile": [
                    CH_CORE_RELATED_PERSON_PROFILE,
                ]
            },
            "patient": {
                "reference": patient_reference,
            },
        }

        identifiers = [
            _build_identifier(identifier)
            for identifier in contact.identifiers
            if identifier.system and identifier.value
        ]

        if not identifiers:
            identifiers.append(
                {
                    "system": RELATED_PERSON_IDENTIFIER_SYSTEM,
                    "value": _contact_fingerprint(patient_reference, contact),
                }
            )

        resource["identifier"] = identifiers
        resource["id"] = _stable_related_person_id(
            identifiers[0]["system"],
            identifiers[0]["value"],
        )

        relationship = _build_codeable_concept(contact.relationship)
        if relationship:
            resource["relationship"] = [relationship]

        name = _build_human_name(contact.name)
        if name:
            resource["name"] = [name]

        if contact.telecoms:
            resource["telecom"] = [
                _build_telecom(item)
                for item in contact.telecoms
            ]

        address = _build_address(contact.address)
        if address:
            resource["address"] = [address]

        resources.append(resource)

    return resources
