import hashlib
import uuid
from mappers.author_helpers import add_author_display

from terminology.oid import oid_to_fhir_system


SOCIAL_HISTORY_CATEGORY_SYSTEM = (
    "http://terminology.hl7.org/CodeSystem/observation-category"
)


def _coding_from_cda(value):
    if not value or not value.get("code"):
        return None

    coding = {"code": value["code"]}
    system = oid_to_fhir_system(value.get("codeSystem"))
    if system:
        coding["system"] = system
    elif value.get("codeSystem"):
        coding["system"] = f"urn:oid:{value['codeSystem']}"

    if value.get("displayName"):
        coding["display"] = value["displayName"]

    return coding


def map_social_history_section(section, patient_reference, context):
    resources = []
    entries = section.get("entries", [])

    for entry in entries:
        value = entry.get("value")
        code = entry.get("code") or {}

        if not value:
            continue

        display = (
            value.get("displayName")
            or value.get("text")
            or code.get("displayName")
            or "Social history"
        )
        code_value = value.get("code") or value.get("text") or ""
        question_coding = _coding_from_cda(code)
        value_coding = _coding_from_cda(value)

        identifier_source = f"{patient_reference}|{display}|{code_value}"
        identifier_value = hashlib.sha256(identifier_source.encode("utf-8")).hexdigest()

        resource = {
            "resourceType": "Observation",
            "id": str(uuid.uuid4()),
            "identifier": [
                {
                    "system": "https://woess.ch/fhir/NamingSystem/cda-import-social-history",
                    "value": identifier_value,
                }
            ],
            "status": "final",
            "category": [{
                "coding": [{
                    "system": SOCIAL_HISTORY_CATEGORY_SYSTEM,
                    "code": "social-history",
                    "display": "Social History",
                }],
            }],
            "subject": {"reference": patient_reference},
            "code": {
                "coding": [question_coding] if question_coding else [],
                "text": code.get("displayName") or display,
            },
        }
        add_author_display(resource, entry)

        if value_coding:
            resource["valueCodeableConcept"] = {
                "coding": [value_coding],
                "text": display,
            }
        elif value.get("text") or value.get("displayName"):
            resource["valueString"] = (
                value.get("text")
                or value.get("displayName")
            )

        resources.append(resource)

    return resources
