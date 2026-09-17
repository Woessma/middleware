import logging
import hashlib
import uuid
from mappers.author_helpers import add_author_display

from utils.fhir_utils import (
    cda_ts_to_fhir_date,
    cda_ts_to_fhir_datetime
)


logger = logging.getLogger(__name__)


def map_goal_section(
    section,
    patient_reference,
    context
):

    resources = []

    entries = section.get("entries", [])

    logger.debug(
        "GOAL MAPPER CALLED: %s entries",
        len(entries),
    )

    for entry in entries:

        value = entry.get("value")

        description = (
            value.get("displayName")
            or value.get("code")
            or "Goal"
        ) if value else "Goal"

        effective_time = (
            entry.get("effectiveTime")
            or ""
        )

        identifier_source = (
            f"{patient_reference}|"
            f"{description}|"
            f"{effective_time}"
        )

        identifier_value = hashlib.sha256(
            identifier_source.encode("utf-8")
        ).hexdigest()

        goal = {
            "resourceType": "Goal",
            "id": str(uuid.uuid4()),
            "identifier": [
                {
                    "system": (
                        "https://woess.ch/fhir/"
                        "NamingSystem/cda-import-goal"
                    ),
                    "value": identifier_value
                }
            ],
            "lifecycleStatus": "active",
            "subject": {
                "reference": patient_reference
            },
            "description": {
                "text": description
            }
        }
        add_author_display(goal, entry)

        if effective_time:

            fhir_date = cda_ts_to_fhir_date(
                effective_time
            )

            if fhir_date:

                goal["startDate"] = (
                    fhir_date
                )

        resources.append(goal)

        logger.debug("CREATED GOAL: %s", description)

    logger.debug(
        "CREATED %s GOALS",
        len(resources),
    )

    return resources