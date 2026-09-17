import uuid
from mappers.author_helpers import add_author_display
import hashlib
import logging
import json

from terminology.allergy import (
    CLINICAL_STATUS_SYSTEM,
    VERIFICATION_STATUS_SYSTEM,
    CRITICALITY_HIGH_CDA_CODE,
    CRITICALITY_LOW_CDA_CODE,
    CRITICALITY_HIGH_FHIR_CODE,
    CRITICALITY_LOW_FHIR_CODE,
    ACTIVE_STATUS_CDA_CODE,
    ACTIVE_STATUS_FHIR_CODE,
    VERIFIED_STATUS_FHIR_CODE,
    DEFAULT_ALLERGY_TEXT,
    REACTION_TYPE_CODE,
    REACTION_TYPE_TEXT,
    REACTION_MANIFESTATION_SYSTEM,
)
from fhir.fhir_helpers import oid_to_fhir_system

logger = logging.getLogger(__name__)

ALLERGY_IDENTIFIER_SYSTEM = (
    "https://woess.ch/fhir/NamingSystem/cda-import-allergy"
)

CH_CORE_ALLERGY_INTOLERANCE_PROFILE = (
    "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-allergyintolerance"
)


def _as_list(value):
    if value is None:
        return []
 
    if isinstance(value, list):
        return value
 
    return [value]
 

def _build_allergy_identifier(entry, patient_reference):
 
    allergen_name = ""
 
    allergen = entry.get("allergen")
 
    if allergen:
 
        allergen_name = (
            allergen.get("name")
            or ""
        )
 
        allergen_code = allergen.get("code") or {}
 
        allergen_name = (
            allergen_code.get("displayName")
            or allergen_name
        )
 
    reaction_text = ""
 
    reactions = entry.get("reactions", [])
 
    if reactions:
 
        value = reactions[0].get("value") or {}
 
        reaction_text = (
            value.get("displayName")
            or value.get("text")
            or ""
        )
 
    onset = (
        entry.get("effectiveDateTime")
        or ""
    )
 
    raw = "|".join(
        [
            patient_reference,
            allergen_name,
            reaction_text,
            onset
        ]
    )
 
    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()
 
 
def _build_allergy_resource_id(identifier_value):
 
    stable_uuid = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"{ALLERGY_IDENTIFIER_SYSTEM}|{identifier_value}"
    )
 
    return f"allergy-{stable_uuid}"
 
 
def get_allergy_if_none_exist(resource):
 
    identifiers = resource.get("identifier", [])
 
    for identifier in identifiers:
 
        system = identifier.get("system")
        value = identifier.get("value")
 
        if system and value:
 
            return (
                f"identifier={system}|{value}"
            )
 
    return None
 
 
def extract_allergies(section):
    entries = section.get("entries")
 
    if entries is None:
        entries = section.get("entry")
 
    allergies = _as_list(entries)
 
    logger.info(
        "extract_allergies(): found %d entries",
        len(allergies)
    )
 
    return allergies
 
 
def _codeable_from_cda(value, fallback_text=None):
    if not value:
        if fallback_text:
            return {
                "text": fallback_text
            }
 
        return None
 
    code = value.get("code")
    display = (
        value.get("displayName")
        or value.get("text")
        or fallback_text
    )
 
    code_system = value.get("codeSystem")
    system = oid_to_fhir_system(code_system)
 
    result = {}
 
    if display:
        result["text"] = display
 
    if code:
        coding = {
            "code": code
        }
 
        if system:
            coding["system"] = system
 
        if display:
            coding["display"] = display
 
        result["coding"] = [
            coding
        ]
 
    if not result and fallback_text:
        result["text"] = fallback_text
 
    return result if result else None
 
 
def _get_allergen_codeable(entry):
    allergen = entry.get("allergen")
 
    if allergen:
        allergen_code = allergen.get("code")
        allergen_name = allergen.get("name")
 
        codeable = _codeable_from_cda(
            allergen_code,
            allergen_name
        )
 
        if codeable:
            return codeable
 
    nested = entry.get("nestedObservation")
 
    if nested:
        nested_value = nested.get("value")
        nested_text = nested.get("text")

        if nested_value:
            return _codeable_from_cda(
                nested_value,
                nested_text or DEFAULT_ALLERGY_TEXT
            )

        if nested_text:
            return {
                "text": nested_text
            }

        nested_code = nested.get("code")
        if nested_code:
            return _codeable_from_cda(
                nested_code,
                DEFAULT_ALLERGY_TEXT
            )

    entry_value = entry.get("value")
    if entry_value:
        return _codeable_from_cda(
            entry_value,
            DEFAULT_ALLERGY_TEXT
        )

    return {
        "text": DEFAULT_ALLERGY_TEXT
    }


def _map_clinical_status(entry):
    status = entry.get("allergyStatus")

    if status:
        status_code = status.get("code")
        status_display = status.get("displayName")

        if status_code == ACTIVE_STATUS_CDA_CODE:
            return ACTIVE_STATUS_FHIR_CODE

        if status_display and status_display.lower() == ACTIVE_STATUS_FHIR_CODE:
            return ACTIVE_STATUS_FHIR_CODE

    if entry.get("statusCode") == ACTIVE_STATUS_FHIR_CODE:
        return ACTIVE_STATUS_FHIR_CODE

    return ACTIVE_STATUS_FHIR_CODE


def _map_criticality(entry):
    criticality = entry.get("criticality")

    if not criticality:
        return None

    code = criticality.get("code")
    display = criticality.get("displayName") or criticality.get("text")

    if code == CRITICALITY_HIGH_CDA_CODE:
        return CRITICALITY_HIGH_FHIR_CODE

    if code == CRITICALITY_LOW_CDA_CODE:
        return CRITICALITY_LOW_FHIR_CODE

    if code in {"723509005", "399166001"}:
        return CRITICALITY_HIGH_FHIR_CODE

    if display:
        text = display.lower()

        if "high" in text or "hoch" in text or "lebensbedrohlich" in text or "life" in text:
            return CRITICALITY_HIGH_FHIR_CODE

        if "low" in text or "niedrig" in text:
            return CRITICALITY_LOW_FHIR_CODE

    return None


def _map_severity(entry):
    severity = entry.get("severity")

    if not severity:
        return None

    code = severity.get("code")
    display = severity.get("displayName") or severity.get("text")

    if code == "24484000":
        return "severe"

    if code == "255604002":
        return "moderate"

    if display:
        text = display.lower()
        if "severe" in text or "schwer" in text:
            return "severe"
        if "moderate" in text or "mittel" in text:
            return "moderate"
        if "mild" in text or "leicht" in text:
            return "mild"

    return None


def _get_allergy_type_note(entry):
    nested = entry.get("nestedObservation")

    if not nested:
        return None

    value = nested.get("value")

    if not value:
        return None

    return (
        value.get("displayName")
        or value.get("text")
        or nested.get("text")
    )


def _build_reactions(entry):
    reactions = []

    for reaction in _as_list(entry.get("reactions")):
        manifestation = {}

        if reaction is None:
            continue

        reaction_value = reaction.get("value") or {}
        reaction_code = reaction.get("code") or {}
        reaction_text = reaction.get("text")

        code = (
            reaction_value.get("code")
            or reaction_code.get("code")
        )
        display = (
            reaction_value.get("displayName")
            or reaction_value.get("text")
            or reaction_text
            or reaction_code.get("displayName")
            or reaction_code.get("text")
            or REACTION_TYPE_TEXT
        )

        if display:
            manifestation["text"] = display

        if code:
            coding = {
                "code": code,
                "system": REACTION_MANIFESTATION_SYSTEM,
            }

            if display:
                coding["display"] = display

            manifestation["coding"] = [coding]

        if not manifestation:
            manifestation["text"] = REACTION_TYPE_TEXT

        reaction_item = {
            "manifestation": [manifestation]
        }

        onset = reaction.get("effectiveDateTime")

        if onset:
            reaction_item["onset"] = onset

        reactions.append(reaction_item)

    return reactions
 
 
def map_allergy_section(
    section,
    patient_reference,
    context
):
    resources = []
 
    entries = section.get("entries", [])
 
    logger.debug(
        "ALLERGY MAPPER CALLED: %s entries",
        len(entries),
    )
 
    for entry in entries:
 
        logger.debug("ALLERGY ENTRY DEBUG")
 
        logger.debug(
            "%s",
            json.dumps(
                entry,
                indent=2,
                ensure_ascii=False
            ),
        )
 
        allergy_codeable = _get_allergen_codeable(entry)
        identifier_value = _build_allergy_identifier(
            entry,
            patient_reference
        )
 
 
        if not allergy_codeable:
            logger.debug("SKIP ALLERGY: no allergen/code/display")
            continue
 
        allergy = {
            "resourceType": "AllergyIntolerance",
            "meta": {
                "profile": [
                    CH_CORE_ALLERGY_INTOLERANCE_PROFILE,
                ]
            },
            "id": _build_allergy_resource_id(
                identifier_value
            ),
            "identifier": [
                {
                    "system": ALLERGY_IDENTIFIER_SYSTEM,
                    "value": identifier_value
                }
            ],
        
            "clinicalStatus": {
                "coding": [
                    {
                        "system": CLINICAL_STATUS_SYSTEM,
                        "code": _map_clinical_status(entry)
                    }
                ]
            },
            "verificationStatus": {
                "coding": [
                    {
                        "system": VERIFICATION_STATUS_SYSTEM,
                        "code": VERIFIED_STATUS_FHIR_CODE
                    }
                ]
            },
            "patient": {
                "reference": patient_reference
            },
            "code": allergy_codeable
        }
        add_author_display(allergy, entry)
 
        recorded_date = entry.get("effectiveDateTime")
 
        if recorded_date:
            allergy["recordedDate"] = recorded_date
 
        criticality = _map_criticality(entry)
 
        if criticality:
            allergy["criticality"] = criticality

        severity = _map_severity(entry)

        if severity:
            allergy["severity"] = severity
 
        allergy_type_note = _get_allergy_type_note(entry)
 
        if allergy_type_note:
            allergy["note"] = [
                {
                    "text": allergy_type_note
                }
            ]
 
        reactions = _build_reactions(entry)
        logger.debug(
            "%s",
            json.dumps(
                reactions,
                indent=2,
                ensure_ascii=False
            ),
        )
        if reactions:
            allergy["reaction"] = reactions
 
        resources.append(allergy)
 
        logger.debug(
            "CREATED ALLERGY: %s",
            allergy_codeable.get("text"),
        )
 
    logger.debug(
        "CREATED %s ALLERGY RESOURCES",
        len(resources),
    )
 
    return resources
 