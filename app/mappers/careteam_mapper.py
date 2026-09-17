import logging
import hashlib
import uuid
from mappers.author_helpers import add_author_display

from utils.fhir_utils import (
    cda_ts_to_fhir_date,
    cda_ts_to_fhir_datetime
)


logger = logging.getLogger(__name__)


def map_careteam_section(
    section,
    patient_reference,
    context
):

    resources = []

    entries = section.get("entries", [])

    logger.debug(
        "CARETEAM MAPPER CALLED: %s entries",
        len(entries),
    )

    for entry in entries:

        status = "active"

        if entry.get("statusCode") == "completed":
            status = "inactive"

        name = (
            section.get("title")
            or "Care Team"
        )

        identifier_source = (
            f"{patient_reference}|"
            f"{name}|"
            f"{status}"
        )

        identifier_value = hashlib.sha256(
            identifier_source.encode("utf-8")
        ).hexdigest()

        careteam = {
            "resourceType": "CareTeam",
            "id": str(uuid.uuid4()),
            "identifier": [
                {
                    "system": (
                        "https://woess.ch/fhir/"
                        "NamingSystem/cda-import-careteam"
                    ),
                    "value": identifier_value
                }
            ],
            "status": status,
            "subject": {
                "reference": patient_reference
            },
            "name": name
        }
        add_author_display(careteam, entry)

        participants = entry.get("participants", [])
        practitioner_id = context.get("practitioner_id") if context else None
        careteam_participants = []
        for participant in participants:
            function = participant.get("function") or {}
            role_code = function.get("code")
            role_display = function.get("display")
            if role_code != "PCP":
                continue
            role = {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/participationfunction",
                    "code": role_code,
                    "display": role_display or "Primary Care Provider",
                }]
            }
            participant_entry = {"role": [role]}
            if practitioner_id:
                participant_entry["member"] = {"reference": f"Practitioner/{practitioner_id}"}
            elif participant.get("identifier"):
                participant_entry["member"] = {"identifier": participant["identifier"]}
            careteam_participants.append(participant_entry)
        if careteam_participants:
            careteam["participant"] = careteam_participants

        resources.append(careteam)

        logger.debug("CREATED CARETEAM")

    logger.debug(
        "CREATED %s CARETEAMS",
        len(resources),
    )

    return resources