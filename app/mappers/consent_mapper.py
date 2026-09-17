import logging
import uuid
from mappers.author_helpers import add_author_display


logger = logging.getLogger(__name__)


def _extract_consent_text(entry):
    if not entry:
        return None

    if entry.get("value"):
        value = entry.get("value")
        if value.get("displayName"):
            return value.get("displayName")
        if value.get("text"):
            return value.get("text")

    code = entry.get("code") or {}
    if code.get("displayName"):
        return code.get("displayName")

    for component in entry.get("components", []) or []:
        component_value = component.get("value") or {}
        if component_value.get("displayName"):
            return component_value.get("displayName")
        if component_value.get("text"):
            return component_value.get("text")

    return None


def map_consent_section(
    section,
    patient_reference,
    context
):

    resources = []

    entries = section.get("entries", [])

    logger.debug(
        "CONSENT MAPPER CALLED: %s entries",
        len(entries),
    )

    for entry in entries:

        consent_text = _extract_consent_text(entry)

        if not consent_text:
            continue

        consent = {
            "resourceType": "Consent",
            "id": str(uuid.uuid4()),
            "status": "active",
            "scope": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/consentscope",
                        "code": "adr"
                    }
                ]
            },
            "patient": {
                "reference": patient_reference
            }
        }
        add_author_display(consent, entry)

        consent["category"] = [
            {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "42348-3",
                        "display": "Advance directives"
                    }
                ]
            }
        ]

        consent["policyText"] = {
            "text": consent_text
        }

        resources.append(consent)

        logger.debug("CREATED CONSENT: %s", consent_text)

    logger.debug(
        "CREATED %s CONSENTS",
        len(resources),
    )

    return resources
