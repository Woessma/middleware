import logging
import hashlib
import uuid

from fhir.fhir_helpers import oid_to_fhir_system
from terminology.cvx import CVX_VACCINES
from terminology.vacd import VACD_VACCINES, SWISSMEDIC_AUTHORIZED_VACCINES
from utils.fhir_utils import (
    cda_ts_to_fhir_date,
)


logger = logging.getLogger(__name__)


CH_CORE_IMMUNIZATION_PROFILE = (
    "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-immunization"
)


def _build_vaccine_code_codings(vaccine_code, vaccine_display, code_system=None):
    coding = []

    if vaccine_code:
        primary_coding = {"code": vaccine_code}
        if code_system:
            system = oid_to_fhir_system(code_system)
            if system:
                primary_coding["system"] = system
        if vaccine_display:
            primary_coding["display"] = vaccine_display
        coding.append(primary_coding)

    normalized_name = (
        "_".join((vaccine_display or "").strip().upper().replace("-", "_").split())
    )
    vaccine_key = None
    for key in [normalized_name, (vaccine_code or "").strip()]:
        if not key:
            continue
        if key in CVX_VACCINES:
            vaccine_key = key
            break
        if key in VACD_VACCINES:
            vaccine_key = key
            break

    if vaccine_key:
        cvx_value = CVX_VACCINES.get(vaccine_key, {}).get("cvx")
        snomed_value = CVX_VACCINES.get(vaccine_key, {}).get("snomed") or VACD_VACCINES.get(vaccine_key, {}).get("snomed")
        swissmedic_value = VACD_VACCINES.get(vaccine_key, {}).get("swissmedic")

        if cvx_value:
            coding.insert(0, {
                "system": "http://hl7.org/fhir/sid/cvx",
                "code": cvx_value,
                "display": vaccine_display or vaccine_key.replace("_", " ").title(),
            })

        if snomed_value:
            coding.insert(1 if cvx_value else 0, {
                "system": "http://snomed.info/sct",
                "code": snomed_value,
                "display": vaccine_display or vaccine_key.replace("_", " ").title(),
            })

        if swissmedic_value:
            coding.append({
                "system": SWISSMEDIC_AUTHORIZED_VACCINES,
                "code": swissmedic_value,
                "display": vaccine_display or vaccine_key.replace("_", " ").title(),
            })

    if not coding and vaccine_display:
        coding.append({
            "display": vaccine_display,
        })

    unique_coding = []
    seen_codings = set()

    for item in coding:
        coding_key = (
            item.get("system"),
            item.get("code"),
            item.get("display"),
        )
        if coding_key in seen_codings:
            continue
        seen_codings.add(coding_key)
        unique_coding.append(item)

    return unique_coding


def map_immunization_section(
    section,
    patient_reference,
    context
):

    resources = []

    entries = section.get("entries", [])

    logger.debug(
        "IMMUNIZATION MAPPER CALLED: %s entries",
        len(entries),
    )

    for entry in entries:

        value = entry.get("value") or {}

        consumable = entry.get("consumable") or {}
        consumable_code = consumable.get("code") or {}

        vaccine_code = (
            value.get("code")
            or consumable_code.get("code")
        )

        code_system = (
            value.get("codeSystem")
            or consumable_code.get("codeSystem")
        )

        vaccine_display = (
            value.get("displayName")
            or consumable_code.get("displayName")
            or consumable_code.get("originalText")
            or entry.get("displayName")
            or entry.get("name")
            or "Unknown Vaccine"
        )

        occurrence_date = None

        if entry.get("effectiveTime"):
            occurrence_date = cda_ts_to_fhir_date(
                entry.get("effectiveTime")
            )

        lot_number = entry.get("lotNumber")
        manufacturer = entry.get("manufacturer")

        #
        # CDA Identifier (bevorzugt)
        #
        cda_id = entry.get("id") or {}

        cda_root = cda_id.get("root")
        cda_extension = cda_id.get("extension")

        if cda_root and cda_extension:

            identifier_system = (
                f"urn:oid:{cda_root}"
            )

            identifier_value = (
                cda_extension
            )

        else:

            #
            # Fallback falls keine CDA-ID vorhanden
            #
            identifier_source = (
                f"{patient_reference}|"
                f"{vaccine_code or vaccine_display}|"
                f"{occurrence_date or ''}"
            )

            identifier_value = hashlib.sha256(
                identifier_source.encode(
                    "utf-8"
                )
            ).hexdigest()

            identifier_system = (
                "https://woess.ch/fhir/"
                "NamingSystem/"
                "cda-import-immunization"
            )

        immunization = {
            "resourceType": "Immunization",
            "meta": {
                "profile": [
                    CH_CORE_IMMUNIZATION_PROFILE,
                ]
            },
            "id": str(uuid.uuid4()),
            "identifier": [
                {
                    "system": identifier_system,
                    "value": identifier_value
                }
            ],
            "status": "completed",
            "patient": {
                "reference": patient_reference
            }
        }

        if entry.get("authorDisplay"):
            immunization["performer"] = [{
                "actor": {
                    "display": entry["authorDisplay"]
                }
            }]

        if occurrence_date:

            immunization[
                "occurrenceDateTime"
            ] = occurrence_date

        #
        # Vaccine Code
        #
        vaccine_codings = _build_vaccine_code_codings(
            vaccine_code,
            vaccine_display,
            code_system,
        )

        if vaccine_codings:
            immunization[
                "vaccineCode"
            ] = {
                "coding": vaccine_codings,
                "text": vaccine_display,
            }
        else:
            immunization[
                "vaccineCode"
            ] = {
                "text": vaccine_display,
            }

        #
        # Lot Number
        #
        if lot_number:

            immunization[
                "lotNumber"
            ] = lot_number

        #
        # Manufacturer
        #
        if manufacturer:

            immunization[
                "manufacturer"
            ] = {
                "display": manufacturer
            }

        resources.append(
            immunization
        )

        logger.debug(
            "CREATED IMMUNIZATION: %s (%s)",
            vaccine_display,
            identifier_value,
        )

    logger.debug(
        "CREATED %s IMMUNIZATIONS",
        len(resources),
    )

    return resources