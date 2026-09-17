import logging
import uuid
import json
import hashlib
from fhir.fhir_helpers import oid_to_fhir_system
from terminology.emediplan_medication_map import resolve_medication_identity
from utils.fhir_utils import (
    cda_ts_to_fhir_datetime
)
from mappers.author_helpers import add_author_display

MEDICATION_IDENTIFIER_SYSTEM = (
    "https://woess.ch/fhir/NamingSystem/cda-import-medicationstatement"
)

CH_CORE_MEDICATION_STATEMENT_PROFILE = (
    "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-medicationstatement"
)

PHARMACODE_SYSTEM = "https://emediplan.ch/fhir/NamingSystem/pharmacode"
GTIN_SYSTEM = "urn:epc:id:sgtin"
DISPENSING_CATEGORY_EXTENSION = (
    "https://emediplan.ch/fhir/StructureDefinition/dispensing-category"
)


logger = logging.getLogger(__name__)


def _clean(value):
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()
        return value if value else None

    return value


def _normalize_status(status):
    status = _clean(status)

    if not status:
        return "active"

    mapping = {
        "active": "active",
        "completed": "completed",
        "complete": "completed",
        "aborted": "stopped",
        "cancelled": "stopped",
        "canceled": "stopped",
        "suspended": "on-hold",
        "held": "on-hold",
        "nullified": "entered-in-error"
    }

    return mapping.get(
        status.lower(),
        "active"
    )


def _build_medication_codeable(concept_code):
    if not concept_code:
        return {
            "text": "Unbekannte Medikation"
        }

    code = _clean(concept_code.get("code"))
    display = _clean(
        concept_code.get("displayName")
        or concept_code.get("originalText")
    )
    code_system = _clean(concept_code.get("codeSystem"))
    null_flavor = _clean(concept_code.get("nullFlavor"))
    translations = concept_code.get("translations") or []

    result = {}

    if display:
        result["text"] = display

    coding_list = []

    if code and not null_flavor:
        coding = {
            "code": code
        }

        system = oid_to_fhir_system(code_system)

        if not system and code_system:
            system = code_system

        if system:
            coding["system"] = system

        if display:
            coding["display"] = display

        coding_list.append(coding)

        if system == PHARMACODE_SYSTEM:
            resolved = resolve_medication_identity(3, code)
        elif system == GTIN_SYSTEM:
            resolved = resolve_medication_identity(2, code)
        else:
            resolved = None

        if resolved and resolved.get("gtin"):
            resolved_coding = {
                "system": GTIN_SYSTEM,
                "code": resolved["gtin"],
                "display": resolved.get("display") or display or resolved["gtin"],
            }
            coding_list.insert(0, resolved_coding)

            if resolved.get("product_number"):
                coding_list.append(
                    {
                        "system": "https://fhir.ch/ig/ch-emed/CodeSystem/swissmedic",
                        "code": resolved["product_number"],
                        "display": resolved.get("display") or resolved["product_number"],
                    }
                )

    # PROC-MAP-01: Rehydrate secondary codings from CDA translations when primary code is missing/UNK.
    for translation in translations:
        translation_code = _clean(translation.get("code"))

        if not translation_code:
            continue

        translation_coding = {
            "code": translation_code,
        }

        translation_system = oid_to_fhir_system(
            _clean(translation.get("codeSystem"))
        )

        if translation_system:
            translation_coding["system"] = translation_system

        translation_display = _clean(translation.get("displayName"))
        if translation_display:
            translation_coding["display"] = translation_display

        coding_list.append(translation_coding)

    if coding_list:
        unique = []
        seen = set()

        for coding in coding_list:
            key = (coding.get("system"), coding.get("code"))

            if key in seen:
                continue

            seen.add(key)
            unique.append(coding)

        result["coding"] = unique

    if not result:
        result["text"] = "Unbekannte Medikation"

    return result


def _build_dosage(entry):
    dosage = {}

    dosage_text = _clean(entry.get("dosageText") or entry.get("directionsText"))

    if dosage_text:
        dosage["text"] = dosage_text

    dose_quantity = entry.get("doseQuantity")

    # PROC-MAP-02: Keep quantitative dose as structured FHIR doseAndRate for CDA round-trips.
    if dose_quantity:
        dosage["doseAndRate"] = [
            {
                "doseQuantity": dose_quantity
            }
        ]

    route_code = entry.get("routeCode")

    if route_code and route_code.get("code"):
        route_coding = {
            "code": route_code.get("code")
        }

        route_system = oid_to_fhir_system(
            route_code.get("codeSystem")
        )

        if route_system:
            route_coding["system"] = route_system

        if route_code.get("displayName"):
            route_coding["display"] = route_code.get("displayName")

        dosage["route"] = {
            "coding": [
                route_coding
            ],
            "text": route_code.get("displayName")
        }

    return dosage if dosage else None


def _build_notes(entry):
    notes = []

    text_candidates = []

    for key in ("directionsText", "dosageText", "text", "sectionAuthorTime"):
        value = _clean(entry.get(key))
        if value:
            text_candidates.append(value)

    for key in ("patientInstructions", "comments", "prnReasons", "authorTimes"):
        value = entry.get(key)

        if not value:
            continue

        if isinstance(value, list):
            text_candidates.extend(
                [
                    _clean(item)
                    for item in value
                    if _clean(item)
                ]
            )
        else:
            cleaned = _clean(value)
            if cleaned:
                text_candidates.append(cleaned)

    entry_relationships = entry.get("entryRelationships") or []

    for relationship in entry_relationships:
        if not isinstance(relationship, dict):
            continue

        # Only "text"/"value" carry clinician-authored free text; "statusCode" is
        # administrative metadata (e.g. always "completed") and not a real note.
        for key in ("text", "value"):
            value = relationship.get(key)
            if isinstance(value, dict):
                value = value.get("text") or value.get("displayName") or value.get("code")
            cleaned = _clean(value)
            if cleaned:
                text_candidates.append(cleaned)

    seen = set()

    for text in text_candidates:
        if text in seen:
            continue

        seen.add(text)
        notes.append({"text": text})

    return notes if notes else None


def _extract_cda_identifier(entry):
    """
    Versucht aus dem geparsten CDA-Eintrag eine stabile ID zu extrahieren.

    Unterstützt mehrere mögliche Parser-Strukturen:
    - entry["id"]
    - entry["ids"]
    - entry["templateId"]
    - entry["templateIds"]

    Wenn keine CDA-ID vorhanden ist, wird später ein Fingerprint gebildet.
    """

    possible_keys = [
        "id",
        "ids",
        "templateId",
        "templateIds"
    ]

    for key in possible_keys:
        value = entry.get(key)

        if not value:
            continue

        if isinstance(value, str):
            cleaned = _clean(value)
            if cleaned:
                return cleaned

        if isinstance(value, dict):
            root = _clean(value.get("root"))
            extension = _clean(value.get("extension"))

            if root and extension:
                return f"{root}|{extension}"

            if root:
                return root

            if extension:
                return extension

        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    cleaned = _clean(item)
                    if cleaned:
                        return cleaned

                if isinstance(item, dict):
                    root = _clean(item.get("root"))
                    extension = _clean(item.get("extension"))

                    if root and extension:
                        return f"{root}|{extension}"

                    if root:
                        return root

                    if extension:
                        return extension

    return None


def _build_medication_fingerprint(
    entry,
    patient_reference,
    medication_code,
    fhir_datetime
):
    """
    Baut einen stabilen fachlichen Fingerprint.

    Priorität:
    1. CDA-ID, falls vorhanden
    2. Sonst Patient + Code + Display/Text + Datum + Dosis + Route

    Ziel:
    Gleicher CDA-Import soll dieselbe MedicationStatement-Identifier-Value erzeugen.
    """

    cda_identifier = _extract_cda_identifier(entry)

    if cda_identifier:
        raw_value = f"cda-id|{patient_reference}|{cda_identifier}"
    else:
        code = ""
        code_system = ""
        display = ""

        if medication_code:
            code = _clean(medication_code.get("code")) or ""
            code_system = _clean(medication_code.get("codeSystem")) or ""
            display = _clean(
                medication_code.get("displayName")
                or medication_code.get("originalText")
            ) or ""

        dosage_text = _clean(entry.get("dosageText")) or ""

        route_code = entry.get("routeCode") or {}
        route = ""

        if isinstance(route_code, dict):
            route = _clean(route_code.get("code")) or ""

        raw_value = "|".join(
            [
                "fingerprint",
                patient_reference or "",
                code_system,
                code,
                display,
                fhir_datetime or "",
                dosage_text,
                route
            ]
        )

    digest = hashlib.sha256(
        raw_value.encode("utf-8")
    ).hexdigest()

    return digest


def _build_stable_resource_id(identifier_value):
    """
    Erzeugt eine stabile, FHIR-kompatible Resource.id.

    FHIR id darf nur bestimmte Zeichen enthalten.
    UUID5 ist stabil, wenn identifier_value gleich bleibt.
    """

    stable_uuid = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"{MEDICATION_IDENTIFIER_SYSTEM}|{identifier_value}"
    )

    return f"medstmt-{stable_uuid}"


def _build_medication_core_key(entry, medication_code, patient_reference):
    code = ""
    code_system = ""
    display = ""

    if medication_code:
        code = _clean(medication_code.get("code")) or ""
        code_system = _clean(medication_code.get("codeSystem")) or ""
        display = _clean(
            medication_code.get("displayName")
            or medication_code.get("originalText")
        ) or ""

    dosage_text = _clean(entry.get("dosageText")) or ""

    route_code = entry.get("routeCode") or {}
    route = ""

    if isinstance(route_code, dict):
        route = _clean(route_code.get("code")) or ""

    status = _normalize_status(entry.get("statusCode"))

    return (
        patient_reference or "",
        code_system,
        code,
        display,
        dosage_text,
        route,
        status,
    )


def get_medication_if_none_exist(resource):
    """
    Liefert den ifNoneExist-String für eine FHIR Conditional Create Anfrage.

    Verwendung im Bundle:
        request = {
            "method": "POST",
            "url": "MedicationStatement",
            "ifNoneExist": get_medication_if_none_exist(resource)
        }
    """

    identifiers = resource.get("identifier", [])

    for identifier in identifiers:
        system = identifier.get("system")
        value = identifier.get("value")

        if system and value:
            return f"identifier={system}|{value}"

    return None


def map_medication_section(
    section,
    patient_reference,
    context
):
    resources_by_variant = {}

    entries = section.get("entries", [])

    logger.debug(
        "MEDICATION MAPPER CALLED: %s entries",
        len(entries),
    )

    for idx, entry in enumerate(entries, start=1):

        logger.debug("MEDICATION ENTRY %s", idx)

        logger.debug("ENTRY KEYS: %s", list(entry.keys()))

        logger.debug(
            "%s",
            json.dumps(
                entry,
                indent=2,
                ensure_ascii=False
            ),
        )

        effective_time = entry.get("effectiveTime")

        fhir_datetime = None

        if effective_time:
            fhir_datetime = cda_ts_to_fhir_datetime(
                effective_time
            )

        consumable = entry.get("consumable")

        medication_code = None

        if consumable:
            medication_code = consumable.get("code")

        identifier_value = _build_medication_fingerprint(
            entry=entry,
            patient_reference=patient_reference,
            medication_code=medication_code,
            fhir_datetime=fhir_datetime
        )

        core_key = _build_medication_core_key(
            entry=entry,
            medication_code=medication_code,
            patient_reference=patient_reference,
        )

        variant_key = (
            core_key,
            fhir_datetime or "",
        )

        if variant_key in resources_by_variant:
            logger.debug(
                "SKIP EXACT DUPLICATE MEDICATION VARIANT: %s",
                variant_key,
            )
            continue

        if not fhir_datetime:
            has_dated_variant = any(
                existing_core == core_key and existing_date
                for (existing_core, existing_date) in resources_by_variant.keys()
            )

            if has_dated_variant:
                logger.debug(
                    "SKIP MEDICATION WITHOUT DATE; DATED VARIANT EXISTS: %s",
                    core_key,
                )
                continue

        medication = {
            "resourceType": "MedicationStatement",
            "meta": {
                "profile": [
                    CH_CORE_MEDICATION_STATEMENT_PROFILE,
                ]
            },
            "id": _build_stable_resource_id(identifier_value),
            "identifier": [
                {
                    "system": MEDICATION_IDENTIFIER_SYSTEM,
                    "value": identifier_value
                }
            ],
            "status": _normalize_status(entry.get("statusCode")),
            "subject": {
                "reference": patient_reference
            },
            "medicationCodeableConcept": _build_medication_codeable(
                medication_code
            )
        }
        add_author_display(medication, entry)

        source_system = oid_to_fhir_system(
            _clean(medication_code.get("codeSystem"))
        ) if medication_code else None
        if not source_system and medication_code:
            source_system = _clean(medication_code.get("codeSystem"))

        if source_system == PHARMACODE_SYSTEM:
            resolved_identity = resolve_medication_identity(3, medication_code.get("code"))
            dispensing_category = resolved_identity.get("dispensing_category")
            if dispensing_category:
                medication["extension"] = [
                    {
                        "url": DISPENSING_CATEGORY_EXTENSION,
                        "valueCode": dispensing_category,
                    }
                ]

        if fhir_datetime:
            medication["effectiveDateTime"] = fhir_datetime

        dosage = _build_dosage(entry)

        if dosage:
            medication["dosage"] = [
                dosage
            ]

        notes = _build_notes(entry)

        if notes:
            medication["note"] = notes

        if fhir_datetime:
            undated_variant_key = (
                core_key,
                "",
            )

            if undated_variant_key in resources_by_variant:
                logger.debug(
                    "REPLACE MEDICATION WITHOUT DATE WITH DATED VARIANT: %s",
                    core_key,
                )
                resources_by_variant.pop(undated_variant_key)

        resources_by_variant[variant_key] = medication

        logger.debug(
            "%s",
            json.dumps(
                medication,
                indent=2,
                ensure_ascii=False
            ),
        )

        logger.debug("CREATED MEDICATION WITH STABLE IDENTIFIER")

    logger.debug(
        "CREATED %s UNIQUE MEDICATIONS",
        len(resources_by_variant),
    )

    return list(resources_by_variant.values())