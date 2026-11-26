import hashlib
import json


CDA_TECHNICAL_SOURCE_SYSTEM = (
    "https://fhir.omnilink.ch/fhir/NamingSystem/mdm-technical-cda-source"
)
CDA_TECHNICAL_EPIC_IDENTIFIER_SYSTEMS = {
    "urn:oid:1.2.840.114350.1.13.521.3.7.3.688884.100"
}


class CdaTechnicalSourceConflict(ValueError):
    pass


def cda_technical_source_identifier(patient: dict, epic_systems: set[str]) -> dict:
    """Derive a stable technical-source marker, without resolving or writing a patient."""
    if not isinstance(epic_systems, set) or not epic_systems or any(
        not isinstance(system, str) or not system or system != system.strip()
        for system in epic_systems
    ):
        raise ValueError("An explicit set of EPIC identifier systems is required")
    if not isinstance(patient, dict) or patient.get("resourceType") != "Patient":
        raise ValueError("A FHIR Patient is required")
    identifiers = patient.get("identifier", [])
    if not isinstance(identifiers, list) or not all(isinstance(item, dict) for item in identifiers):
        raise ValueError("Invalid FHIR Patient identifiers")

    keys = set()
    for identifier in identifiers:
        system = identifier.get("system")
        if system is not None and not isinstance(system, str):
            raise ValueError("Invalid FHIR Patient identifier system")
        if system not in epic_systems:
            continue
        value = identifier.get("value")
        if not isinstance(value, str) or not value or value != value.strip():
            raise CdaTechnicalSourceConflict("EPIC patient identifier is invalid; review required")
        keys.add((system, value))
    if len(keys) != 1:
        raise CdaTechnicalSourceConflict("A unique EPIC patient identifier is required; review required")

    canonical = json.dumps(next(iter(keys)), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return {"system": CDA_TECHNICAL_SOURCE_SYSTEM, "value": digest}


def attach_cda_technical_source_identifier(patient: dict) -> None:
    if not isinstance(patient, dict) or patient.get("resourceType") != "Patient":
        raise ValueError("A FHIR Patient is required")
    identifiers = patient.get("identifier", [])
    if not isinstance(identifiers, list) or not all(isinstance(item, dict) for item in identifiers):
        raise ValueError("Invalid FHIR Patient identifiers")
    if any(
        identifier.get("system") is not None
        and not isinstance(identifier.get("system"), str)
        for identifier in identifiers
    ):
        raise ValueError("Invalid FHIR Patient identifier system")

    markers = [
        identifier
        for identifier in identifiers
        if identifier.get("system") == CDA_TECHNICAL_SOURCE_SYSTEM
    ]
    has_approved_source = any(
        identifier.get("system") in CDA_TECHNICAL_EPIC_IDENTIFIER_SYSTEMS
        for identifier in identifiers
    )
    if not has_approved_source:
        if markers:
            raise CdaTechnicalSourceConflict(
                "A technical CDA source marker without an approved source identifier requires review"
            )
        return

    marker = cda_technical_source_identifier(
        patient, CDA_TECHNICAL_EPIC_IDENTIFIER_SYSTEMS
    )
    if markers:
        if len(markers) != 1 or markers[0] != marker:
            raise CdaTechnicalSourceConflict(
                "The technical CDA source marker does not match the approved source identifier"
            )
        return
    identifiers.append(marker)
