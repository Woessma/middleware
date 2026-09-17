import uuid

from utils.fhir_utils import (
    cda_ts_to_fhir_datetime,
)

PROFILE = (
    "http://fhir.ch/ig/ch-core/"
    "StructureDefinition/ch-core-encounter"
)

ENCOUNTER_IDENTIFIER_SYSTEM = (
    "urn:oid:1.2.840.114350.1.13.521.3.7.3.698084.8"
)


def build_ch_core_encounter(
    encounter,
    patient_ref,
    organization_ref=None,
):
    resource = {
        "resourceType": "Encounter",
        "id": str(uuid.uuid4()),
        "meta": {
            "profile": [
                PROFILE
            ]
        },
        "status": encounter.status,
        "class": {
            "system": (
                "http://terminology.hl7.org/"
                "CodeSystem/v3-ActCode"
            ),
            "code": encounter.encounter_class,
        },
        "subject": {
            "reference": patient_ref,
        },
    }

    if encounter.encounter_id:

        resource["identifier"] = [
            {
                "system": (
                    ENCOUNTER_IDENTIFIER_SYSTEM
                ),
                "value": encounter.encounter_id,
            }
        ]

    if encounter.start or encounter.end:

        period = {}

        if encounter.start:

            start = cda_ts_to_fhir_datetime(
                encounter.start
            )

            if start:
                period["start"] = start

        if encounter.end:

            end = cda_ts_to_fhir_datetime(
                encounter.end
            )

            if end:
                period["end"] = end

        if period:
            resource["period"] = period

    if organization_ref:

        resource["serviceProvider"] = {
            "reference": organization_ref
        }

    return resource