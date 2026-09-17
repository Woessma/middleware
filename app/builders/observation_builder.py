import logging
import uuid
import hashlib

from fhir.fhir_helpers import make_fhir_coding


logger = logging.getLogger(__name__)

def build_observation_from_entry(
    entry,
    patient_ref,
    section_title
):

    code_coding = make_fhir_coding(
        entry.get("code")
    )

    value = entry.get("value")

    if not code_coding and not value:
        return None

    observation_id = str(
        uuid.uuid4()
    )

    effective = (
        entry.get("effectiveDateTime")
        or ""
    )

    code_value = ""

    if code_coding:

        code_value = (
            code_coding.get("code")
            or ""
        )

    value_key = ""

    if value:

        if value.get("value") is not None:

            value_key = str(
                value.get("value")
            )

        elif value.get("code"):

            value_key = (
                value.get("code")
            )

        elif value.get("text"):

            value_key = (
                value.get("text")
            )

    entry_id = entry.get("id") or {}

    id_root = entry_id.get("root")
    id_extension = entry_id.get("extension")

    if id_root and id_extension:

        identifier_source = (
            f"{id_root}|{id_extension}"
        )

    else:

        identifier_source = (
            f"{patient_ref}|"
            f"{code_value}|"
            f"{value_key}|"
            f"{effective}"
        )

    identifier_value = hashlib.sha256(
        identifier_source.encode("utf-8")
    ).hexdigest()
    
    logger.debug("OBS ID SOURCE: %s", identifier_source)

    observation = {
        "resourceType": "Observation",
        "id": observation_id,
        "identifier": [
            {
                "system": (
                    "https://woess.ch/fhir/"
                    "NamingSystem/"
                    "cda-import-observation"
                ),
                "value": identifier_value
            }
        ],
        "status": "final",
        "subject": {
            "reference": patient_ref
        }
    }

    if entry.get("authorDisplay"):
        observation["performer"] = [{
            "display": entry["authorDisplay"]
        }]

    if code_coding:

        observation["code"] = {
            "coding": [
                code_coding
            ],
            "text": (
                code_coding.get("display")
                or code_coding.get("code")
            )
        }

    else:

        observation["code"] = {
            "text": (
                section_title
                or "CDA entry"
            )
        }

    if effective:

        observation[
            "effectiveDateTime"
        ] = effective

    if value:

        if value.get("value") is not None:

            try:

                observation[
                    "valueQuantity"
                ] = {
                    "value": float(
                        value.get("value")
                    ),
                    "unit": value.get(
                        "unit"
                    ),
                    "system":
                        "http://unitsofmeasure.org",
                    "code": value.get(
                        "unit"
                    )
                }

            except Exception:

                observation[
                    "valueString"
                ] = str(
                    value.get("value")
                )

        elif value.get("code"):

            value_coding = (
                make_fhir_coding(
                    {
                        "code":
                            value.get(
                                "code"
                            ),
                        "codeSystem":
                            value.get(
                                "codeSystem"
                            ),
                        "displayName":
                            value.get(
                                "displayName"
                            )
                    }
                )
            )

            if value_coding:

                observation[
                    "valueCodeableConcept"
                ] = {
                    "coding": [
                        value_coding
                    ],
                    "text": (
                        value_coding.get(
                            "display"
                        )
                        or value_coding.get(
                            "code"
                        )
                    )
                }

        elif value.get("text"):

            observation[
                "valueString"
            ] = value.get("text")

        elif value.get("nullFlavor"):

            observation[
                "dataAbsentReason"
            ] = {
                "coding": [
                    {
                        "system": (
                            "http://terminology.hl7.org/"
                            "CodeSystem/"
                            "data-absent-reason"
                        ),
                        "code": "unknown",
                        "display": (
                            f"CDA nullFlavor: "
                            f"{value.get('nullFlavor')}"
                        )
                    }
                ]
            }

    return observation