import logging
import hashlib
import uuid

from terminology.loinc import get_loinc_display
from utils.fhir_utils import (
    cda_ts_to_fhir_date,
    cda_ts_to_fhir_datetime
)
from mappers.author_helpers import add_author_display


VITAL_LOINC_CODES = {
    "8302-2",
    "29463-7",
    "8480-6",
    "8462-4",
    "8867-4",
    "9279-1",
    "8310-5",
    "2708-6",
    "39156-5"
}


logger = logging.getLogger(__name__)

def map_vitalsign_section(
    section,
    patient_reference,
    context
):

    resources = []

    entries = section.get("entries", [])

    logger.debug(
        "VITALSIGN MAPPER CALLED: %s entries",
        len(entries),
    )

    for organizer in entries:

        logger.debug("ORGANIZER: %s", organizer.get("id"))
        logger.debug(
            "ORGANIZER COMPONENT COUNT: %s",
            len(organizer.get("components", [])),
        )

        for entry in organizer.get(
            "components",
            []
        ):

            code = entry.get(
                "code",
                {}
            )

            loinc_code = code.get(
                "code"
            )

            logger.debug("VITAL CODE: %s", loinc_code)

            if loinc_code not in VITAL_LOINC_CODES:
                logger.debug("SKIPPED VITAL CODE: %s", loinc_code)
                continue

            effective_time = (
                entry.get("effectiveTime")
                or ""
            )

            value = entry.get("value") or {}

            value_key = ""

            if value.get("value") is not None:

                value_key = str(
                    value.get("value")
                )

            identifier_source = (
                f"{patient_reference}|"
                f"{loinc_code}|"
                f"{value_key}|"
                f"{effective_time}"
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
                "system": "http://loinc.org",
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
                            "NamingSystem/"
                            "cda-import-vitalsign"
                        ),
                        "value": identifier_value
                    }
                ],
                "status": "final",
                "category": [
                    {
                        "coding": [
                            {
                                "system": (
                                    "http://terminology.hl7.org/"
                                    "CodeSystem/"
                                    "observation-category"
                                ),
                                "code": "vital-signs",
                                "display": "Vital Signs"
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
                    "text": display
                }
            }
            add_author_display(observation, entry)

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

            if value.get("value") is not None:

                observation[
                    "valueQuantity"
                ] = {
                    "value": value.get(
                        "value"
                    ),
                    "unit": value.get(
                        "unit"
                    ),
                    "system": (
                        "http://unitsofmeasure.org"
                    ),
                    "code": value.get(
                        "unit"
                    )
                }

            resources.append(
                observation
            )

            logger.debug("CREATED VITAL SIGN %s", loinc_code)

    logger.debug(
        "CREATED %s VITAL SIGNS",
        len(resources),
    )

    return resources