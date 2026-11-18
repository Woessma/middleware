"""Builds a CH-VACD-ready source bundle from Epic Immunization exports.

Epic's `Immunization.Search` returns a searchset bundle without the Patient
resource. This service accepts either a combined payload
``{"patient": <Epic Patient.Read JSON>, "immunizations": <searchset>}`` or a
searchset bundle that additionally contains the Patient as an entry, and
synthesizes the Composition required for the CH-VACD immunization
administration document. Downstream the regular `/fhir/vacd/convert`
pipeline (Epic normalization, VACD marking, stabilization, validation)
applies unchanged.
"""

import copy
import html
import uuid
from datetime import datetime, timezone

from terminology.cvx import (
    SYSTEM as CVX_SYSTEM,
    cvx_concept_for_code,
    snomed_code_for_cvx,
)

# Epic ships site/route codings from its internal code systems; they are
# meaningless outside Epic and only the text survives the conversion.
_EPIC_INTERNAL_SYSTEM_PREFIX = "urn:oid:1.2.840.114350."

_SNOMED_SYSTEM = "http://snomed.info/sct"


def _document_entry(resource):
    return {"fullUrl": f"urn:uuid:{uuid.uuid4()}", "resource": resource}


def is_epic_immunization_payload(payload):
    """True for the combined payload or a FHIR searchset bundle."""
    if not isinstance(payload, dict):
        return False
    if "immunizations" in payload:
        return True
    return (
        payload.get("resourceType") == "Bundle"
        and payload.get("type") == "searchset"
    )


def _contained_resources(value):
    if isinstance(value, dict) and value.get("resourceType") == "Bundle":
        return [
            entry.get("resource")
            for entry in value.get("entry") or []
            if isinstance(entry, dict) and isinstance(entry.get("resource"), dict)
        ]
    if isinstance(value, list):
        return [resource for resource in value if isinstance(resource, dict)]
    if isinstance(value, dict) and value.get("resourceType"):
        return [value]
    return []


def _strip_epic_internal_codings(codeable_concept):
    if not isinstance(codeable_concept, dict):
        return
    codings = [
        coding
        for coding in codeable_concept.get("coding") or []
        if not str(coding.get("system", "")).startswith(_EPIC_INTERNAL_SYSTEM_PREFIX)
    ]
    if codings:
        codeable_concept["coding"] = codings
    else:
        codeable_concept.pop("coding", None)


def _normalize_immunization(resource, patient_reference):
    immunization = copy.deepcopy(resource)
    immunization.setdefault("id", str(uuid.uuid4()))
    immunization["patient"] = {"reference": patient_reference}

    vaccine_code = immunization.get("vaccineCode") or {}
    codings = vaccine_code.get("coding") or []
    snomed_codes = {
        coding.get("code")
        for coding in codings
        if coding.get("system") == _SNOMED_SYSTEM
    }
    snomed_twins = []

    for coding in codings:
        if coding.get("system") != CVX_SYSTEM:
            continue
        concept = cvx_concept_for_code(coding.get("code", ""))
        if concept and not coding.get("display"):
            coding["display"] = concept["display"]
        snomed_code = snomed_code_for_cvx(coding.get("code", ""))
        if snomed_code and snomed_code not in snomed_codes:
            snomed_twins.append(
                {
                    "system": _SNOMED_SYSTEM,
                    "code": snomed_code,
                    "display": vaccine_code.get("text") or coding.get("display"),
                }
            )
            snomed_codes.add(snomed_code)

    if snomed_twins:
        vaccine_code["coding"] = codings + snomed_twins

    for field in ("site", "route"):
        _strip_epic_internal_codings(immunization.get(field))

    return immunization


def _administration_narrative(immunizations):
    items = []
    for immunization in immunizations:
        vaccine_code = immunization.get("vaccineCode") or {}
        label = vaccine_code.get("text") or next(
            (
                coding.get("display")
                for coding in vaccine_code.get("coding") or []
                if coding.get("display")
            ),
            "Immunization",
        )
        occurrence = immunization.get("occurrenceDateTime") or ""
        suffix = f" ({html.escape(occurrence)})" if occurrence else ""
        items.append(f"<li>{html.escape(label)}{suffix}</li>")

    return (
        '<div xmlns="http://www.w3.org/1999/xhtml"><ul>'
        + "".join(items)
        + "</ul></div>"
    )


def build_vacd_source_bundle(payload):
    """Builds the pre-normalization document source bundle; raises ValueError
    for payloads that cannot be converted."""
    if isinstance(payload, dict) and "immunizations" in payload:
        immunization_resources = _contained_resources(payload.get("immunizations"))
        patient = next(
            (
                resource
                for resource in _contained_resources(payload.get("patient"))
                if resource.get("resourceType") == "Patient"
            ),
            None,
        )
        organization = next(
            (
                resource
                for resource in _contained_resources(payload.get("organization"))
                if resource.get("resourceType") == "Organization"
            ),
            None,
        )
    else:
        resources = _contained_resources(payload)
        immunization_resources = resources
        patient = next(
            (
                resource
                for resource in resources
                if resource.get("resourceType") == "Patient"
            ),
            None,
        )
        organization = next(
            (
                resource
                for resource in resources
                if resource.get("resourceType") == "Organization"
            ),
            None,
        )

    immunization_resources = [
        resource
        for resource in immunization_resources
        if resource.get("resourceType") == "Immunization"
    ]

    if patient is None:
        raise ValueError(
            "Epic-Immunization-Eingabe ohne Patient: das Patient.Read-JSON unter "
            '"patient" mitgeben oder als zusaetzlichen Bundle-Eintrag ergaenzen'
        )
    if not immunization_resources:
        raise ValueError("Die Eingabe enthaelt keine Immunization-Ressourcen")

    patient = copy.deepcopy(patient)
    patient.setdefault("id", str(uuid.uuid4()))
    patient_reference = f"Patient/{patient['id']}"

    # The CH-VACD document profile requires a custodian Organization entry;
    # synthesize one from the Epic location when none is supplied.
    if organization is None:
        location_display = next(
            (
                (resource.get("location") or {}).get("display")
                for resource in immunization_resources
                if (resource.get("location") or {}).get("display")
            ),
            None,
        )
        organization = {
            "resourceType": "Organization",
            "name": location_display or "Unknown organization",
        }
    organization = copy.deepcopy(organization)
    organization.setdefault("id", str(uuid.uuid4()))

    immunizations = [
        _normalize_immunization(resource, patient_reference)
        for resource in immunization_resources
    ]

    composition = {
        "resourceType": "Composition",
        "id": str(uuid.uuid4()),
        "language": "en",
        "identifier": {
            "system": "urn:ietf:rfc:3986",
            "value": f"urn:uuid:{uuid.uuid4()}",
        },
        "status": "final",
        "type": {
            "coding": [
                {
                    "system": _SNOMED_SYSTEM,
                    "code": "41000179103",
                    "display": "Immunization record",
                }
            ]
        },
        "subject": {"reference": patient_reference},
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "author": [{"reference": patient_reference}],
        "title": "Immunization Administration",
        "confidentiality": "N",
        "custodian": {"reference": f"Organization/{organization['id']}"},
        "section": [
            {
                "title": "Administration",
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "11369-6",
                            "display": "Hx of Immunization",
                        }
                    ]
                },
                "text": {
                    "status": "generated",
                    "div": _administration_narrative(immunizations),
                },
                "entry": [
                    {"reference": f"Immunization/{immunization['id']}"}
                    for immunization in immunizations
                ],
            }
        ],
    }

    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            _document_entry(composition),
            _document_entry(patient),
            _document_entry(organization),
            *(_document_entry(immunization) for immunization in immunizations),
        ],
    }
