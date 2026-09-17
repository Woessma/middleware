import hashlib
import uuid
from mappers.author_helpers import add_author_display


def _map_status(status_code):
    if not status_code:
        return "finished"

    normalized = str(status_code).strip().lower()

    mapping = {
        "completed": "finished",
        "active": "in-progress",
        "normal": "finished",
        "finished": "finished",
        "in-progress": "in-progress",
        "planned": "planned",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "entered-in-error": "entered-in-error",
        "onleave": "onleave",
        "finished": "finished",
    }

    return mapping.get(normalized, "finished")


def map_encounter_section(section, patient_reference, context):
    resources = []
    entries = section.get("entries", [])

    for entry in entries:
        if entry.get("type") != "encounter":
            continue

        encounter_id = entry.get("id", {}).get("extension") or entry.get("id", {}).get("root") or ""
        status = _map_status(entry.get("statusCode"))
        effective_time = entry.get("effectiveDateTime") or ""

        identifier_source = f"{patient_reference}|{encounter_id}|{effective_time}"
        identifier_value = hashlib.sha256(identifier_source.encode("utf-8")).hexdigest()

        resource = {
            "resourceType": "Encounter",
            "id": str(uuid.uuid4()),
            "identifier": [
                {
                    "system": "https://woess.ch/fhir/NamingSystem/cda-import-encounter",
                    "value": identifier_value,
                }
            ],
            "status": status,
            "subject": {"reference": patient_reference},
            "class": {
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                "code": entry.get("code", {}).get("code") or "AMB",
            },
        }
        add_author_display(resource, entry)

        if effective_time:
            resource["period"] = {"start": effective_time}

        resources.append(resource)

    return resources
