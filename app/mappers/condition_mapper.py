import logging
import hashlib
import uuid
from mappers.author_helpers import add_author_display


logger = logging.getLogger(__name__)


def _extract_condition_value(entry):
    nested = entry.get("nestedObservation")
    if nested:
        return nested.get("value")
    return entry.get("value")


def _extract_clinical_status(entry):
    allergy_status = entry.get("allergyStatus") or {}
    status_text = (allergy_status.get("displayName") or "").strip().lower()

    if status_text in {"resolved", "inactive", "remission"}:
        return "resolved"

    if status_text in {"active", "recurrence", "relapse"}:
        return "active"

    if allergy_status.get("code") in {"413322009"}:
        return "resolved"

    return "active"


def map_condition_section(
    section,
    patient_reference,
    context
):

    resources = []

    entries = section.get("entries", [])

    logger.debug(
        "CONDITION MAPPER CALLED: %s entries",
        len(entries),
    )

    for entry in entries:

        value = _extract_condition_value(entry)

        if not value:
            continue

        code = value.get("code")

        display = (
            value.get("displayName")
            or value.get("text")
            or "Condition"
        )

        effective = (
            entry.get("effectiveDateTime")
            or entry.get("nestedObservation", {}).get("effectiveDateTime")
            or ""
        )

        identifier_source = (
            f"{patient_reference}|"
            f"{display}|"
            f"{effective}"
        )

        identifier_value = hashlib.sha256(
            identifier_source.encode("utf-8")
        ).hexdigest()

        condition = {
            "resourceType": "Condition",
            "id": str(uuid.uuid4()),
            "identifier": [
                {
                    "system": (
                        "https://woess.ch/fhir/"
                        "NamingSystem/cda-import-condition"
                    ),
                    "value": identifier_value
                }
            ],
            "subject": {
                "reference": patient_reference
            },
            "clinicalStatus": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                        "code": _extract_clinical_status(entry)
                    }
                ]
            },
            "verificationStatus": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                        "code": "confirmed"
                    }
                ]
            },
            "code": {
                "text": display
            }
        }
        add_author_display(condition, entry)

        if code:

            condition["code"] = {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": code,
                        "display": display
                    }
                ],
                "text": display
            }

        if effective:
            condition["onsetDateTime"] = (
                effective
            )

        resources.append(
            condition
        )

        logger.debug("CREATED CONDITION: %s", display)

    logger.debug(
        "CREATED %s CONDITIONS",
        len(resources),
    )

    return resources