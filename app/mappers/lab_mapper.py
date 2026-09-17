import logging
import hashlib
import uuid

from parser.cda.helpers import text_or_none
from terminology.loinc import (
    LOINC,
    get_loinc_display
)
from terminology.oid import oid_to_fhir_system
from utils.fhir_utils import (
    cda_ts_to_fhir_date,
    cda_ts_to_fhir_datetime
)
from mappers.author_helpers import add_author_display
  
 
LAB_SECTION_CODE = "30954-2"


logger = logging.getLogger(__name__)
 
 
def map_lab_section(
    section,
    patient_reference,
    context
):
 
    resources = []
 
    entries = section.get("entries", [])
 
    logger.debug(
        "LAB MAPPER CALLED: %s entries",
        len(entries),
    )
 
    observation_refs = []
 
    for entry in entries:
 
        observation = build_lab_observation(
            entry,
            patient_reference
        )

        if observation:
            add_author_display(observation, entry)
 
        if observation:
 
            resources.append(observation)
 
            observation_refs.append(
                {
                    "reference": f"urn:uuid:{observation['id']}"
                }
            )
 
            logger.debug(
                "CREATED LAB OBSERVATION: %s",
                observation["id"],
            )
 
    if observation_refs:
 
        diagnostic_report = build_diagnostic_report(
            section,
            patient_reference,
            observation_refs
        )
 
        resources.insert(
            0,
            diagnostic_report
        )
 
    elif section.get("narrativeText") or section.get("text"):
 
        diagnostic_report = build_diagnostic_report(
            section,
            patient_reference,
            []
        )
 
        narrative_text = (
            section.get("narrativeText")
            or section.get("text")
            or ""
        )
 
        if narrative_text:
            diagnostic_report["conclusion"] = narrative_text
 
        resources.insert(0, diagnostic_report)
 
        logger.debug(
            "CREATED DIAGNOSTIC REPORT: %s",
            diagnostic_report["id"],
        )
 
    logger.debug(
        "CREATED %s LAB RESOURCES",
        len(resources),
    )
 
    return resources
 
 
def build_lab_observation(
    entry,
    patient_reference
):
 
    code = entry.get("code") or {}
    value = entry.get("value") or {}
 
    loinc_code = code.get("code")
 
    if not loinc_code:
        return None

    if loinc_code not in LOINC:
        return None
    effective_datetime = (
        entry.get("effectiveDateTime")
        or ""
    )

    value_key = ""

    if value.get("value") is not None:

        value_key = str(
            value.get("value")
        )

    elif value.get("code"):

        value_key = value.get("code")

    elif value.get("text"):

        value_key = value.get("text")

    identifier_source = (
        f"{patient_reference}|"
        f"{loinc_code}|"
        f"{value_key}|"
        f"{effective_datetime}"
    )

    identifier_value = hashlib.sha256(
        identifier_source.encode("utf-8")
    ).hexdigest()
 
    display = (
        code.get("displayName")
        or get_loinc_display(loinc_code)
        or loinc_code
    )

    coding = {
        "system": oid_to_fhir_system(
            code.get("codeSystem")
        ),
        "code": loinc_code
    }

    if display:
        coding["display"] = display

    observation = {
        "resourceType": "Observation",
        "id": str(uuid.uuid4()),
        "identifier": [
            {
                "system": (
                    "https://woess.ch/fhir/"
                    "NamingSystem/cda-import-observation"
                ),
                "value": identifier_value
            }
        ],
        "status": map_status(
            entry.get("statusCode")
        ),
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "laboratory",
                        "display": "Laboratory"
                    }
                ]
            }
        ],
        "subject": {
            "reference": patient_reference
        },
        "code": {
            "coding": [
                coding
            ],
            "text": display or loinc_code
        }
    }
 
    effective_time = (
        entry.get("effectiveTime")
    )

    if effective_time:

        fhir_datetime = (
            cda_ts_to_fhir_datetime(
                effective_time
            )
        )

        if fhir_datetime:

            observation[
                "effectiveDateTime"
            ] = fhir_datetime

    elif entry.get("effectiveDateTime"):

        observation[
            "effectiveDateTime"
        ] = entry.get(
            "effectiveDateTime"
        )

    if value:
 
        if value.get("value") is not None:
 
            observation["valueQuantity"] = {
                "value": to_number_or_string(
                    value.get("value")
                ),
                "unit": value.get("unit"),
                "system": "http://unitsofmeasure.org",
                "code": value.get("unit")
            }
 
        elif value.get("code"):
 
            observation["valueCodeableConcept"] = {
                "coding": [
                    {
                        "system": oid_to_fhir_system(
                            value.get("codeSystem")
                        ),
                        "code": value.get("code"),
                        "display": value.get("displayName")
                    }
                ],
                "text": value.get("displayName") or value.get("code")
            }
 
        elif value.get("text"):
 
            observation["valueString"] = value.get("text")
 
        elif value.get("nullFlavor"):
 
            observation["dataAbsentReason"] = {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/data-absent-reason",
                        "code": "unknown",
                        "display": f"CDA nullFlavor: {value.get('nullFlavor')}"
                    }
                ]
            }
 
    return observation
 
 
def build_diagnostic_report(
    section,
    patient_reference,
    observation_refs
):
 
    section_code = section.get("code") or {}
    report_code = (
        section_code.get("code")
        or LAB_SECTION_CODE
    )

    identifier_source = (
        f"{patient_reference}|"
        f"{report_code}|"
        f"{len(observation_refs)}"
    )

    identifier_value = hashlib.sha256(
        identifier_source.encode("utf-8")
    ).hexdigest()   
 
    diagnostic_report = {
        "resourceType": "DiagnosticReport",
        "id": str(uuid.uuid4()),
        "identifier": [
            {
                "system": (
                    "https://woess.ch/fhir/"
                    "NamingSystem/cda-import-diagnosticreport"
                ),
                "value": identifier_value
            }
        ],
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                        "code": "LAB",
                        "display": "Laboratory"
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": oid_to_fhir_system(
                        section_code.get("codeSystem")
                    ),
                    "code": section_code.get("code") or LAB_SECTION_CODE,
                    "display": section_code.get("displayName")
                }
            ],
            "text": section.get("title") or "Laboratory results"
        },
        "subject": {
            "reference": patient_reference
        },
        "result": observation_refs
    }
 
    return diagnostic_report
 
 
def map_status(status_code):
 
    if status_code in ["completed", "complete"]:
        return "final"
 
    if status_code in ["active"]:
        return "preliminary"
 
    if status_code in ["cancelled", "aborted"]:
        return "cancelled"
 
    return "final"
 
 
def to_number_or_string(value):
 
    try:
        return float(value)
    except Exception:
        return value
 