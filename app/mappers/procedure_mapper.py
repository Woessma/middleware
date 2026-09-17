import logging
import hashlib
import uuid
from mappers.author_helpers import add_author_display

from utils.fhir_utils import (
    cda_ts_to_fhir_datetime
)


logger = logging.getLogger(__name__)


def map_procedure_section(
    section,
    patient_reference,
    context
):

    resources = []
    seen_identifiers = context.setdefault(
        "seen_procedure_identifiers",
        set(),
    )

    entries = section.get("entries", [])

    logger.debug(
        "PROCEDURE MAPPER CALLED: %s entries",
        len(entries),
    )

    for entry in entries:

        value = entry.get("value")
        code = entry.get("code")

        procedure_text = (
            section.get("title")
            or "Historical procedure"
        )

        procedure_code = ""

        if value and value.get("code"):

            procedure_code = value.get("code")

            procedure_text = (
                value.get("displayName")
                or procedure_text
            )

        elif code and (
            code.get("code")
            or code.get("displayName")
        ):

            procedure_code = (
                code.get("code")
                or ""
            )

            procedure_text = (
                code.get("displayName")
                or procedure_text
            )

        effective_time = (
            entry.get("effectiveDateTime")
            or entry.get("effectiveTime")
            or ""
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
                f"{patient_reference}|"
                f"{procedure_code}|"
                f"{procedure_text}|"
                f"{effective_time}"
            )

        identifier_value = hashlib.sha256(
            identifier_source.encode("utf-8")
        ).hexdigest()

        if identifier_value in seen_identifiers:
            logger.debug("SKIP DUPLICATE PROCEDURE IN MAPPER")
            continue

        seen_identifiers.add(identifier_value)

        procedure = {
            "resourceType": "Procedure",
            "id": str(uuid.uuid4()),
            "identifier": [
                {
                    "system": (
                        "https://woess.ch/fhir/"
                        "NamingSystem/cda-import-procedure"
                    ),
                    "value": identifier_value
                }
            ],
            "status": "completed",
            "subject": {
                "reference": patient_reference
            }
        }
        add_author_display(procedure, entry)

        if value and value.get("code"):

            procedure["code"] = {
                "coding": [
                    {
                        "system": (
                            "urn:oid:"
                            + value.get(
                                "codeSystem",
                                ""
                            )
                        ),
                        "code": value.get("code"),
                        "display": value.get(
                            "displayName"
                        )
                    }
                ],
                "text": procedure_text
            }

        elif code and (
            code.get("code")
            or code.get("displayName")
        ):

            procedure["code"] = {
                "coding": [
                    {
                        "system": (
                            "urn:oid:"
                            + code.get(
                                "codeSystem",
                                ""
                            )
                        ),
                        "code": code.get("code"),
                        "display": code.get(
                            "displayName"
                        )
                    }
                ],
                "text": procedure_text
            }

        else:

            procedure["code"] = {
                "text": procedure_text
            }

        if effective_time:

            performed_datetime = (
                cda_ts_to_fhir_datetime(
                    effective_time
                )
            )

            if performed_datetime:

                procedure[
                    "performedDateTime"
                ] = performed_datetime

        resources.append(procedure)

        logger.debug(
            "CREATED PROCEDURE: %s",
            procedure_text,
        )

    logger.debug(
        "CREATED %s PROCEDURES",
        len(resources),
    )

    return resources