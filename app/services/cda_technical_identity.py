import hashlib
import json


CDA_TECHNICAL_SOURCE_SYSTEM = (
    "https://fhir.omnilink.ch/fhir/NamingSystem/mdm-technical-cda-source"
)


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
