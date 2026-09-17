# LEGACY
# replaced by parse_patient() + build_ch_core_patient()


from fastapi import FastAPI, UploadFile, File, HTTPException

import requests
import traceback
import xml.etree.ElementTree as ET
import uuid
from datetime import datetime, timezone
import os
import logging
import json
import copy
import hashlib

DEBUG_MODE = os.getenv(
    "DEBUG_MODE",
    "false"
).lower() == "true"

logger = logging.getLogger(__name__)

# Import

from typing import Optional

from fastapi import (
    UploadFile,
    File,
    Form,
    HTTPException,
    Request,
    Query,
    Response,
)


# CDA Constants
from parser.cda.constants import NS

# CDA Parser
from parser.cda.patient_parser import parse_patient
from parser.cda.practitioner_parser import parse_practitioner
from parser.cda.encounter_parser import (
    parse_encounters,
)

from parser.cda.section_parser import (
    extract_sections,
)

from parser.cda.section_parser import (
    extract_code,
)
from parser.hl7v2.oru_r01_parser import parse_oru_r01, to_transaction_bundle


# Builder
from builders.ch_core_patient_builder import (
    build_ch_core_patient
)

from builders.ch_core_practitioner_builder import (
    build_ch_core_practitioner
)

from builders.ch_core_organization_builder import (
    build_ch_core_organization
)

from builders.ch_core_practitioner_role_builder import (
    build_ch_core_practitioner_role
)

from builders.ch_core_encounter_builder import (
    build_ch_core_encounter,
)
from builders.observation_builder import build_observation_from_entry

# Mapper
from mappers.organization_mapper import (
    organization_to_fhir_params
)

# Converter
from converter.section_dispatcher import (
    get_section_mapper
)

from converter.profile_detector import (
    detect_profile
)

# Utils
from utils.fhir_utils import (
    cda_ts_to_fhir_date,
    cda_ts_to_fhir_datetime
)

# Services
from services.patient_service import (
    get_or_create_patient
)

from services.practitioner_service import (
    get_or_create_practitioner
)
from services.organization_service import (
    get_or_create_organization
)

from services.cda_bundle_service import (
    cda_to_fhir_bundle
)

from services.umzh_convert_service import (
    cda_to_etoc_document_bundle,
    cda_to_umzh_bundle,
)
from services.umzh_send_service import (
    send_umzh_bundle,
)
from services.vacd_send_service import (
    send_vacd_bundle,
    _embed_precreated_resource,
)
from services.emediplan_service import (
    emediplan_to_fhir_bundle,
    fhir_medications_to_epic_cda,
    fetch_medication_bundle_from_fhir_server,
)
from services.emediplan_qr_service import extract_emediplan_payload_from_file, resolve_emediplan_payload
from services.echosos_service import import_echosos
from services.terminology_service import (
    call_terminology_operation,
    enrich_bundle_terminology,
    validate_bundle_terminology,
)
from fhir.narrative import ensure_resource_narrative

# helpers
from parser.cda.helpers import (
    text_or_none,
    attr_or_none,
)

from config import FHIR_BASE, TERMINOLOGY_VALIDATION_MODE, VACD_SEND_BASE_URL, VACD_SEND_TIMEOUT


UMZH_SEND_BASE_URL = os.getenv("UMZH_SEND_BASE_URL", "")
UMZH_SEND_TIMEOUT = int(os.getenv("UMZH_SEND_TIMEOUT", "60"))

def _validate_bundle(bundle):
    enrichment_report = enrich_bundle_terminology(bundle)
    logger.info(
        "Terminology enrichment: status=%s enriched=%s checked=%s",
        enrichment_report["status"],
        enrichment_report["enriched"],
        enrichment_report["checked"],
    )
    report = validate_bundle_terminology(bundle)
    logger.info(
        "Terminology validation: status=%s checked=%s",
        report["status"],
        report["checked"],
    )
    if TERMINOLOGY_VALIDATION_MODE == "strict" and report["status"] != "ok":
        raise ValueError("Terminology validation failed")
    return bundle


def _bundle_resource_identity(resource):
    if not isinstance(resource, dict):
        return ("invalid", str(resource))

    identifiers = resource.get("identifier", []) or []
    if isinstance(identifiers, dict):
        identifiers = [identifiers]

    normalized_identifiers = tuple(
        sorted(
            (
                str(identifier.get("system") or ""),
                str(identifier.get("value") or ""),
            )
            for identifier in identifiers
            if identifier.get("system") and identifier.get("value")
        )
    )

    if normalized_identifiers:
        return (
            "identifier",
            resource.get("resourceType"),
            normalized_identifiers,
        )

    payload = copy.deepcopy(resource)
    payload.pop("id", None)
    digest = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return ("payload", resource.get("resourceType"), digest)


def _stabilize_bundle(bundle):
    if not isinstance(bundle, dict) or not bundle.get("resourceType"):
        raise ValueError("FHIR Bundle or FHIR resource expected")

    if bundle.get("resourceType") != "Bundle":
        resource = copy.deepcopy(bundle)
        resource_type = resource["resourceType"]
        resource_id = resource.get("id")
        request = {
            "method": "PUT" if resource_id else "POST",
            "url": f"{resource_type}/{resource_id}" if resource_id else resource_type,
        }
        bundle = {
            "resourceType": "Bundle",
            "type": "transaction",
            "entry": [{"resource": resource, "request": request}],
        }

    entries = bundle.get("entry") or []
    if not isinstance(entries, list):
        raise ValueError("Bundle entry must be a list")

    if bundle.get("type") == "document":
        bundle = copy.deepcopy(bundle)
        bundle["type"] = "transaction"

    seen = set()
    stabilized_entries = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        resource = entry.get("resource") or {}
        request = dict(entry.get("request") or {})
        method = request.get("method")

        if not request.get("method") or not request.get("url"):
            resource_type = resource.get("resourceType")
            resource_id = resource.get("id")
            if not resource_type:
                continue
            request = {
                "method": "PUT" if resource_id else "POST",
                "url": f"{resource_type}/{resource_id}" if resource_id else resource_type,
            }
            method = request["method"]

        identity = _bundle_resource_identity(resource)
        if method == "POST" and identity[0] == "identifier":
            if "ifNoneExist" not in request:
                identifier_values = [
                    (system, value)
                    for system, value in identity[2]
                    if system and value
                ]
                if identifier_values:
                    system, value = identifier_values[0]
                    request["ifNoneExist"] = f"identifier={system}|{value}"

        stabilized_entry = dict(entry)
        ensure_resource_narrative(resource)
        stabilized_entry["request"] = request

        if identity in seen:
            logger.info("SKIP DUPLICATE BUNDLE RESOURCE: %s", identity)
            continue

        seen.add(identity)
        stabilized_entries.append(stabilized_entry)

    stabilized = copy.deepcopy(bundle)
    stabilized["entry"] = stabilized_entries
    return stabilized


app = FastAPI(
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)


@app.post("/fhir/stabilize")
async def fhir_stabilize(request: Request):
    try:
        payload = await request.json()
        stabilized = _stabilize_bundle(payload)
        return stabilized
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Bundle stabilization failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/fhir/convert")
async def fhir_convert(request: Request):
    try:
        payload = await request.json()
        stabilized = _validate_bundle(_stabilize_bundle(payload))
        return stabilized
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.RequestException as exc:
        logger.exception("FHIR convert/send failed")
        raise HTTPException(status_code=502, detail="FHIR server unavailable") from exc
    except Exception as exc:
        logger.exception("FHIR convert failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
@app.get("/")
def root():
    raise HTTPException(status_code=404)
 
 
@app.get("/metadata")
def metadata():
 
    if not DEBUG_MODE:
        raise HTTPException(
            status_code=404,
            detail="Not Found"
        )

    return {
        "status": "debug-enabled"
    }


@app.post("/terminology/{resource_type}/{operation}")
async def terminology_operation(resource_type: str, operation: str, request: Request):
    try:
        parameters = await request.json()
        response = call_terminology_operation(resource_type, operation, parameters)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.RequestException as exc:
        logger.exception("Terminology server request failed")
        raise HTTPException(status_code=502, detail="Terminology server unavailable") from exc

    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type="application/fhir+json",
    )


@app.post("/hl7v2/convert")
async def hl7v2_convert(
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_hl7: Optional[str] = Form(None),
):
    if file is not None:
        message = (await file.read()).decode("utf-8-sig")
    elif raw_hl7:
        message = raw_hl7
    else:
        message = (await request.body()).decode("utf-8-sig")

    if not message.strip():
        raise HTTPException(status_code=400, detail="No HL7v2 message provided")

    try:
        return _validate_bundle(parse_oru_r01(message))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("HL7v2 conversion failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/hl7v2/import")
async def hl7v2_import(
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_hl7: Optional[str] = Form(None),
):
    if file is not None:
        message = (await file.read()).decode("utf-8-sig")
    elif raw_hl7:
        message = raw_hl7
    else:
        message = (await request.body()).decode("utf-8-sig")

    if not message.strip():
        raise HTTPException(status_code=400, detail="No HL7v2 message provided")

    try:
        bundle = _validate_bundle(to_transaction_bundle(parse_oru_r01(message)))
        return bundle
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.RequestException as exc:
        logger.exception("HL7v2 FHIR import failed")
        raise HTTPException(status_code=502, detail="FHIR server unavailable") from exc
    except Exception as exc:
        logger.exception("HL7v2 import failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

 
def extract_patient(root):
    patient_role = root.find(".//hl7:recordTarget/hl7:patientRole", NS)
    patient_node = root.find(".//hl7:recordTarget/hl7:patientRole/hl7:patient", NS)
 
    patient_id = str(uuid.uuid4())
 
    patient = {
        "resourceType": "Patient",
        "id": patient_id,
        "name": [
            {
                "family": "Unknown",
                "given": ["Unknown"]
            }
        ]
    }
 
    if patient_role is None or patient_node is None:
        return patient
 
    # Identifier
    identifiers = []
 
    for id_node in patient_role.findall("hl7:id", NS):
        identifier_root = id_node.attrib.get("root")
        identifier_extension = id_node.attrib.get("extension")
 
        if identifier_root or identifier_extension:
            item = {
                "value": identifier_extension or identifier_root
            }
 
            if identifier_root:
                item["system"] = f"urn:oid:{identifier_root}"
 
            identifiers.append(item)
 
    if identifiers:
        patient["identifier"] = identifiers
 
    # Name
    name_node = patient_node.find("hl7:name", NS)
 
    if name_node is not None:
        family_node = name_node.find("hl7:family", NS)
        given_nodes = name_node.findall("hl7:given", NS)
 
        family = text_or_none(family_node)
        givens = []
 
        for g in given_nodes:
            g_text = text_or_none(g)
            if g_text:
                givens.append(g_text)
 
        patient["name"] = [
            {
                "family": family or "Unknown",
                "given": givens or ["Unknown"]
            }
        ]
 
    # Gender
    gender_node = patient_node.find("hl7:administrativeGenderCode", NS)
    gender_code = attr_or_none(gender_node, "code")
 
    if gender_code:
        gender_map = {
            "M": "male",
            "F": "female",
            "U": "unknown",
            "UN": "unknown"
        }
        patient["gender"] = gender_map.get(gender_code, "unknown")
 
    # Birthdate
    birth_node = patient_node.find("hl7:birthTime", NS)
    birth_value = attr_or_none(birth_node, "value")
    birth_date = cda_ts_to_fhir_date(birth_value)
 
    if birth_date:
        patient["birthDate"] = birth_date
 
    # Address
    addr_node = patient_role.find("hl7:addr", NS)
 
    if addr_node is not None:
        street = text_or_none(addr_node.find("hl7:streetAddressLine", NS))
        city = text_or_none(addr_node.find("hl7:city", NS))
        postal_code = text_or_none(addr_node.find("hl7:postalCode", NS))
        country = text_or_none(addr_node.find("hl7:country", NS))
 
        address = {}
 
        if street:
            address["line"] = [street]
 
        if city:
            address["city"] = city
 
        if postal_code:
            address["postalCode"] = postal_code
 
        if country:
            address["country"] = country
 
        if address:
            patient["address"] = [address]
 
    # Telecom
    telecoms = []
 
    for telecom in patient_role.findall("hl7:telecom", NS):
        value = telecom.attrib.get("value")
        use = telecom.attrib.get("use")
 
        if value:
            item = {}
 
            if value.startswith("tel:"):
                item["system"] = "phone"
                item["value"] = value.replace("tel:", "")
            elif value.startswith("mailto:"):
                item["system"] = "email"
                item["value"] = value.replace("mailto:", "")
            else:
                item["system"] = "other"
                item["value"] = value
 
            if use:
                use_map = {
                    "HP": "home",
                    "WP": "work",
                    "MC": "mobile"
                }
                item["use"] = use_map.get(use, "temp")
 
            telecoms.append(item)
 
    if telecoms:
        patient["telecom"] = telecoms
 
    return patient
 
 
def extract_cda_header(root):
    title = root.find("./hl7:title", NS)
    effective_time = root.find("./hl7:effectiveTime", NS)
    code = root.find("./hl7:code", NS)
 
    ids = []
 
    for id_node in root.findall("./hl7:id", NS):
        ids.append(
            {
                "root": id_node.attrib.get("root"),
                "extension": id_node.attrib.get("extension")
            }
        )
 
    template_ids = []
 
    for template in root.findall("./hl7:templateId", NS):
        template_ids.append(
            {
                "root": template.attrib.get("root"),
                "extension": template.attrib.get("extension")
            }
        )
 
    effective_raw = attr_or_none(effective_time, "value")
 
    return {
        "title": text_or_none(title),
        "effectiveTime": effective_raw,
        "effectiveDateTime": cda_ts_to_fhir_datetime(effective_raw),
        "code": extract_code(code),
        "ids": ids,
        "templateIds": template_ids
    }
 
 


 
 


def cda_debug_payload(xml_content):
 
    root = ET.fromstring(xml_content)
 
    profile = detect_profile(root)
 
    patient = extract_patient(root)
    header = extract_cda_header(root)
    sections = extract_sections(root)
 
    return {
        "profile": profile,
        "rootTag": root.tag,
        "document": header,
        "patient": patient,
        "sectionCount": len(sections),
        "sections": sections
    } 

@app.get("/test/patient")
def test_patient():
 
    patient = {
        "resourceType": "Patient",
        "identifier": [
            {
                "system": "urn:oid:1.2.3.4.5",
                "value": "33030032"
            }
        ],
        "name": [
            {
                "family": "Test",
                "given": ["Patient"]
            }
        ]
    }
 
    patient_id = get_or_create_patient(patient)
 
    return {
        "patient_id": patient_id
    }
 

@app.get("/test/organization")
def test_organization():
 
    organization_id = get_or_create_organization(
        identifier_system="urn:oid:1.2.3.4.5",
        identifier_value="12345",
        name="Test Organization"
    )
 
    return {
        "organization_id": organization_id
    }
  
@app.post("/cda/debug")
async def cda_debug(file: UploadFile = File(...)):
 
    if not DEBUG_MODE:
        raise HTTPException(
            status_code=404,
            detail="Not Found"
        )
 
    xml_content = await file.read()
 
    try:
        return cda_debug_payload(xml_content)
 
    except ET.ParseError as ex:
        raise HTTPException(
            status_code=400,
            detail=f"XML Parse Error: {str(ex)}"
        )
 
    except Exception as ex:
        raise HTTPException(
            status_code=500,
            detail=str(ex)
        )
 
 
VACD_SECTION_CODES = {
    "55108-5",
    "11369-6",
    "11450-4",
    "11348-0",
    "48765-2",
    "18727-8",
    "48767-8",
}

VACD_ALWAYS_ALLOWED_RESOURCE_TYPES = {
    "Composition",
    "Patient",
    "Immunization",
    "Practitioner",
    "Organization",
    "PractitionerRole",
}


def _mark_vacd_bundle(bundle):
    if not isinstance(bundle, dict):
        return bundle

    bundle["resourceType"] = bundle.get("resourceType", "Bundle")
    bundle["type"] = "document"

    meta = bundle.setdefault("meta", {})
    profiles = meta.get("profile") or []

    vacd_document_profile = (
        "http://fhir.ch/ig/ch-vacd/StructureDefinition/"
        "ch-vacd-document-immunization-administration"
    )

    if vacd_document_profile not in profiles:
        profiles.append(vacd_document_profile)

    ch_core_document_epr_profile = (
        "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-document-epr"
    )
    if ch_core_document_epr_profile not in profiles:
        profiles.append(ch_core_document_epr_profile)

    meta["profile"] = profiles

    meta.pop("tag", None)

    bundle_identifier = bundle.get("identifier") or {}
    if (
        bundle_identifier.get("system") != "urn:ietf:rfc:3986"
        or not str(bundle_identifier.get("value", "")).startswith("urn:uuid:")
    ):
        bundle["identifier"] = {
            "system": "urn:ietf:rfc:3986",
            "value": f"urn:uuid:{uuid.uuid4()}",
        }

    if "timestamp" not in bundle:
        bundle["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    entries = bundle.get("entry") or []
    compositions = [
        entry.get("resource") or {}
        for entry in entries
        if (entry.get("resource") or {}).get("resourceType") == "Composition"
    ]

    allowed_sections = []
    section_references = set()

    for composition in compositions:
        for section in composition.get("section") or []:
            codes = {
                coding.get("code")
                for coding in (section.get("code") or {}).get("coding") or []
            }

            if not codes.intersection(VACD_SECTION_CODES):
                continue

            allowed_sections.append((composition, section))
            for section_entry in section.get("entry") or []:
                reference = section_entry.get("reference")
                if reference:
                    section_references.add(reference)

    for composition in compositions:
        composition["section"] = [
            section
            for current_composition, section in allowed_sections
            if current_composition is composition
        ]

    filtered_entries = []

    for entry in entries:
        resource = entry.get("resource") or {}
        resource_type = resource.get("resourceType")
        full_url = entry.get("fullUrl")
        resource_reference = (
            f"{resource_type}/{resource.get('id')}"
            if resource_type and resource.get("id")
            else None
        )

        if resource_type in VACD_ALWAYS_ALLOWED_RESOURCE_TYPES:
            filtered_entries.append(entry)
        elif resource_type in {"Basic", "Condition", "AllergyIntolerance", "Observation", "Medication"}:
            if full_url in section_references or resource_reference in section_references:
                filtered_entries.append(entry)

    bundle["entry"] = filtered_entries
    entries = filtered_entries

    resource_full_urls = {}
    for entry in entries:
        resource = entry.get("resource") or {}
        resource_type = resource.get("resourceType")
        resource_id = resource.get("id")
        full_url = entry.get("fullUrl")
        if resource_type and resource_id and full_url:
            resource_full_urls[f"{resource_type}/{resource_id}"] = full_url

    def replace_references(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "reference" and item in resource_full_urls:
                    value[key] = resource_full_urls[item]
                else:
                    replace_references(item)
        elif isinstance(value, list):
            for item in value:
                replace_references(item)

    replace_references(bundle)

    resource_full_urls = {
        f"{(entry.get('resource') or {}).get('resourceType')}/"
        f"{(entry.get('resource') or {}).get('id')}": entry.get("fullUrl")
        for entry in entries
        if (entry.get("resource") or {}).get("resourceType")
        and (entry.get("resource") or {}).get("id")
        and entry.get("fullUrl")
    }

    for composition in compositions:
        author_references = []
        for author in composition.get("author") or []:
            if author.get("reference") in resource_full_urls.values():
                author_references.append(author)
        if author_references:
            composition["author"] = author_references
        else:
            subject_reference = composition.get("subject", {}).get("reference")
            if subject_reference:
                composition["author"] = [{"reference": subject_reference}]
            else:
                composition.pop("author", None)

        custodian = composition.get("custodian") or {}
        if custodian.get("reference") not in resource_full_urls.values():
            composition.pop("custodian", None)

        encounter = composition.get("encounter") or {}
        if encounter.get("reference") not in resource_full_urls.values():
            composition.pop("encounter", None)

    composition_identifier = bundle["identifier"]
    immunization_entries = [
        entry
        for entry in entries
        if (entry.get("resource") or {}).get("resourceType") == "Immunization"
    ]

    composition_profile = (
        "http://fhir.ch/ig/ch-vacd/StructureDefinition/"
        "ch-vacd-composition-immunization-administration"
    )
    immunization_profile = (
        "http://fhir.ch/ig/ch-vacd/StructureDefinition/ch-vacd-immunization"
    )

    reordered_entries = []
    other_entries = []

    for entry in entries:
        resource = entry.get("resource") or {}
        resource_type = resource.get("resourceType")

        if resource_type == "Composition":
            resource_meta = resource.setdefault("meta", {})
            resource_profiles = resource_meta.get("profile") or []
            resource_profiles = [
                profile
                for profile in resource_profiles
                if profile not in {
                    "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-composition",
                    "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-composition-epr",
                }
            ]
            ch_core_composition_profile = (
                "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-composition"
            )
            ch_core_composition_epr_profile = (
                "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-composition-epr"
            )
            resource_profiles.insert(0, ch_core_composition_profile)
            resource_profiles.insert(1, ch_core_composition_epr_profile)
            if composition_profile not in resource_profiles:
                resource_profiles.append(composition_profile)
            resource_meta["profile"] = resource_profiles
            resource["identifier"] = copy.deepcopy(composition_identifier)
            resource["type"] = {
                "coding": [{
                    "system": "http://snomed.info/sct",
                    "code": "41000179103",
                    "display": "Immunization record",
                }]
            }
            resource["category"] = [{
                "coding": [{
                    "system": "urn:oid:2.16.756.5.30.1.127.3.10.10",
                    "code": "urn:che:epr:ch-vacd:immunization-administration:2022",
                    "display": "CH VACD Immunization Administration",
                }]
            }]
            resource["confidentiality"] = "N"
            resource["_confidentiality"] = {
                "extension": [{
                    "url": (
                        "http://fhir.ch/ig/ch-core/StructureDefinition/"
                        "ch-ext-epr-confidentialitycode"
                    ),
                    "valueCodeableConcept": {
                        "coding": [{
                            "system": "http://snomed.info/sct",
                            "code": "17621005",
                            "display": "Normal",
                        }]
                    },
                }]
            }

            for section in resource.get("section") or []:
                for coding in (section.get("code") or {}).get("coding") or []:
                    if coding.get("code") in VACD_SECTION_CODES:
                        coding["system"] = "http://loinc.org"

                if section.get("title") and not section.get("text"):
                    section["text"] = {
                        "status": "generated",
                        "div": f"<div xmlns=\"http://www.w3.org/1999/xhtml\">{section['title']}</div>",
                    }

                section_code = {
                    coding.get("code")
                    for coding in (section.get("code") or {}).get("coding") or []
                }
                if "11369-6" in section_code and not section.get("entry"):
                    section["entry"] = [
                        {"reference": immunization_entry.get("fullUrl")}
                        for immunization_entry in immunization_entries
                        if immunization_entry.get("fullUrl")
                    ]

            reordered_entries.append(entry)
        else:
            if resource_type == "Immunization":
                resource_meta = resource.setdefault("meta", {})
                resource_profiles = resource_meta.get("profile") or []
                if immunization_profile not in resource_profiles:
                    resource_profiles.append(immunization_profile)
                resource_meta["profile"] = resource_profiles

            if resource_type == "Patient":
                resource_meta = resource.setdefault("meta", {})
                resource_profiles = resource_meta.get("profile") or []
                resource_meta["profile"] = [
                    "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-patient-epr"
                    if profile == "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-patient"
                    else profile
                    for profile in resource_profiles
                ]
                for contact in resource.get("contact") or []:
                    contact.pop("telecom", None)
                    contact["extension"] = [
                        extension
                        for extension in contact.get("extension") or []
                        if extension.get("url")
                        != "https://woess.ch/fhir/StructureDefinition/patient-contact-identifier"
                    ]
                    if not contact["extension"]:
                        contact.pop("extension", None)

            other_entries.append(entry)

    bundle["entry"] = reordered_entries + other_entries

    return bundle


@app.post("/cda/convert")

async def cda_convert(
    request: Request,
    bundle_type: str = "transaction",
    file: Optional[UploadFile] = File(None),
    raw_xml: Optional[str] = Form(None)
):

    
    if file is not None:

        xml_content = await file.read()

    elif raw_xml:

        xml_content = raw_xml.encode("utf-8")

    else:

        xml_content = await request.body()

        if not xml_content:
            raise HTTPException(
                status_code=400,
                detail="No CDA content provided"
            )
 
    try:
        normalized_bundle_type = bundle_type.strip().lower()

        if normalized_bundle_type not in {"transaction", "document"}:
            raise HTTPException(
                status_code=400,
                detail="bundle_type must be 'transaction' or 'document'",
            )

        bundle = cda_to_fhir_bundle(
            xml_content,
            bundle_type=normalized_bundle_type,
        )
        return _validate_bundle(bundle)
 
    except ET.ParseError as ex:
        raise HTTPException(
            status_code=400,
            detail=f"XML Parse Error: {str(ex)}"
        )
 
    except Exception as ex:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=str(ex)
        )


@app.post("/cda/vacd/convert")
async def cda_vacd_convert(
    request: Request,
    bundle_type: str = "document",
    file: Optional[UploadFile] = File(None),
    raw_xml: Optional[str] = Form(None),
):
    if file is not None:
        xml_content = await file.read()
    elif raw_xml:
        xml_content = raw_xml.encode("utf-8")
    else:
        xml_content = await request.body()
        if not xml_content:
            raise HTTPException(
                status_code=400,
                detail="No CDA content provided",
            )

    try:
        bundle = cda_to_fhir_bundle(
            xml_content,
            bundle_type="document",
        )
        return _validate_bundle(_mark_vacd_bundle(bundle))

    except ET.ParseError as ex:
        raise HTTPException(
            status_code=400,
            detail=f"XML Parse Error: {str(ex)}",
        )

    except Exception as ex:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=str(ex),
        )


@app.post("/cda/vacd/send")
async def cda_vacd_send(
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_xml: Optional[str] = Form(None),
    destination_base_url: Optional[str] = Query(None),
    outbound_authorization: Optional[str] = Query(None),
):
    if file is not None:
        xml_content = await file.read()
    elif raw_xml:
        xml_content = raw_xml.encode("utf-8")
    else:
        xml_content = await request.body()
        if not xml_content:
            raise HTTPException(
                status_code=400,
                detail="No CDA content provided",
            )

    resolved_destination = destination_base_url or VACD_SEND_BASE_URL

    if not resolved_destination:
        raise HTTPException(
            status_code=400,
            detail="destination_base_url is required (query param or VACD_SEND_BASE_URL env)",
        )

    try:
        bundle = cda_to_fhir_bundle(
            xml_content,
            bundle_type="document",
        )

        # Embed "precreated" Practitioner/Organization resources (only stored on our own
        # FHIR_BASE by cda_bundle_service.py) before VACD-filtering, so Composition.author
        # and .custodian keep resolving to a self-contained bundle for the external target.
        composition = next(
            (
                entry.get("resource") or {}
                for entry in bundle.get("entry", [])
                if (entry.get("resource") or {}).get("resourceType") == "Composition"
            ),
            {},
        )
        for author in composition.get("author") or []:
            _embed_precreated_resource(bundle, author.get("reference"))
        _embed_precreated_resource(bundle, (composition.get("custodian") or {}).get("reference"))

        bundle = _validate_bundle(_mark_vacd_bundle(bundle))

        send_report = send_vacd_bundle(
            bundle=bundle,
            destination_base_url=resolved_destination,
            outbound_authorization=outbound_authorization,
            timeout_seconds=VACD_SEND_TIMEOUT,
        )

        return {
            "convert": {
                "bundle_entry_count": len(bundle.get("entry", [])),
            },
            "send": send_report,
        }

    except ET.ParseError as ex:
        raise HTTPException(
            status_code=400,
            detail=f"XML Parse Error: {str(ex)}",
        )

    except Exception as ex:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=str(ex),
        )


@app.post("/cda/import")
async def cda_import_bundle(
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_xml: Optional[str] = Form(None)
):

    
    if file is not None:

        xml_content = await file.read()

    elif raw_xml:

        xml_content = raw_xml.encode("utf-8")

    else:

        xml_content = await request.body()

        if not xml_content:
            raise HTTPException(
                status_code=400,
                detail="No CDA content provided"
            )


    try:

        bundle = cda_to_fhir_bundle(
            xml_content
        )
        _validate_bundle(bundle)

        obs_identifiers = {}

        for entry in bundle.get("entry", []):

            resource = entry.get(
                "resource",
                {}
            )

            if (
                resource.get("resourceType")
                != "Observation"
            ):
                continue

            for identifier in resource.get(
                "identifier",
                []
            ):

                key = (
                    identifier.get("system"),
                    identifier.get("value")
                )

                obs_identifiers[key] = (
                    obs_identifiers.get(
                        key,
                        0
                    ) + 1
                )

        for key, count in obs_identifiers.items():

            if count > 1:
                logger.warning(
                    "DUPLICATE OBSERVATION IDENTIFIER: %s -> %s",
                    key,
                    count,
                )

        return bundle

    except ET.ParseError as ex:

        raise HTTPException(
            status_code=400,
            detail=f"XML Parse Error: {str(ex)}"
        )

    except Exception as ex:

        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=str(ex)
        )


@app.post("/emediplan/convert")
async def emediplan_convert(
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_payload: Optional[str] = Form(None),
):
    if file is not None:
        payload = await file.read()
        content_type = file.content_type
    elif raw_payload:
        payload = raw_payload.encode("utf-8")
        content_type = None
    else:
        payload = await request.body()
        content_type = request.headers.get("content-type")

    if not payload:
        raise HTTPException(
            status_code=400,
            detail="No eMediplan payload provided",
        )

    try:
        payload = resolve_emediplan_payload(payload, content_type)
        return _validate_bundle(emediplan_to_fhir_bundle(payload))
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except Exception as ex:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(ex))


@app.post("/emediplan/import")
async def emediplan_import(
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_payload: Optional[str] = Form(None),
):
    if file is not None:
        payload = await file.read()
        content_type = file.content_type
    elif raw_payload:
        payload = raw_payload.encode("utf-8")
        content_type = None
    else:
        payload = await request.body()
        content_type = request.headers.get("content-type")

    if not payload:
        raise HTTPException(
            status_code=400,
            detail="No eMediplan payload provided",
        )

    try:
        payload = resolve_emediplan_payload(payload, content_type)
        bundle = _validate_bundle(emediplan_to_fhir_bundle(payload))
        return bundle
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except Exception as ex:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(ex))


@app.post("/emediplan/import-bundle")
async def emediplan_import_bundle(
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_json: Optional[str] = Form(None),
):
    if file is not None:
        raw_content = await file.read()
        json_payload = raw_content.decode("utf-8")
    elif raw_json:
        json_payload = raw_json
    else:
        json_payload = (await request.body()).decode("utf-8")

    if not json_payload.strip():
        raise HTTPException(
            status_code=400,
            detail="No FHIR bundle payload provided",
        )

    try:
        bundle = json.loads(json_payload)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Payload must be valid FHIR Bundle JSON",
        )

    try:
        _validate_bundle(bundle)
        return bundle
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except Exception as ex:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(ex))


@app.post("/emediplan/qr/convert")
async def emediplan_qr_convert(
    request: Request,
    file: Optional[UploadFile] = File(None),
):
    if file is not None:
        raw_bytes = await file.read()
        content_type = file.content_type
    else:
        raw_bytes = await request.body()
        content_type = request.headers.get("content-type")

    if not raw_bytes:
        raise HTTPException(
            status_code=400,
            detail="No file provided (PDF or QR code image)",
        )

    try:
        payload = extract_emediplan_payload_from_file(raw_bytes, content_type)
        return _validate_bundle(emediplan_to_fhir_bundle(payload))
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except Exception as ex:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(ex))


@app.post("/emediplan/qr/import")
async def emediplan_qr_import(
    request: Request,
    file: Optional[UploadFile] = File(None),
):
    if file is not None:
        raw_bytes = await file.read()
        content_type = file.content_type
    else:
        raw_bytes = await request.body()
        content_type = request.headers.get("content-type")

    if not raw_bytes:
        raise HTTPException(
            status_code=400,
            detail="No file provided (PDF or QR code image)",
        )

    try:
        payload = extract_emediplan_payload_from_file(raw_bytes, content_type)
        bundle = _validate_bundle(emediplan_to_fhir_bundle(payload))
        return bundle
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except Exception as ex:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(ex))


@app.post("/echosos/qr/import")
async def echosos_qr_import(
    request: Request,
    file: Optional[UploadFile] = File(None),
):
    if file is not None:
        raw_bytes = await file.read()
        content_type = file.content_type
    else:
        raw_bytes = await request.body()
        content_type = request.headers.get("content-type")

    if not raw_bytes:
        raise HTTPException(
            status_code=400,
            detail="No file provided (PKPass, PDF or QR code image)",
        )

    try:
        author = request.headers.get("x-authenticated-user", "unknown").strip() or "unknown"
        return import_echosos(raw_bytes, content_type, author=author)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except Exception as ex:
        traceback.print_exc()
        raise HTTPException(status_code=502, detail=f"EchoSOS/FHIR request failed: {ex}")


@app.post("/fhir/medications/epic-cda")
async def fhir_medications_epic_cda(
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_json: Optional[str] = Form(None),
):
    if file is not None:
        raw_content = await file.read()
        json_payload = raw_content.decode("utf-8")
    elif raw_json:
        json_payload = raw_json
    else:
        json_payload = (await request.body()).decode("utf-8")

    if not json_payload.strip():
        raise HTTPException(
            status_code=400,
            detail="No FHIR bundle payload provided",
        )

    try:
        bundle = json.loads(json_payload)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Payload must be valid FHIR Bundle JSON",
        )

    try:
        cda_xml = fhir_medications_to_epic_cda(bundle)
        return Response(content=cda_xml, media_type="application/xml")
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except Exception as ex:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(ex))


@app.post("/emediplan/epic-cda")
async def emediplan_to_epic_cda(
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_payload: Optional[str] = Form(None),
):
    if file is not None:
        payload = await file.read()
        content_type = file.content_type
    elif raw_payload:
        payload = raw_payload.encode("utf-8")
        content_type = None
    else:
        payload = await request.body()
        content_type = request.headers.get("content-type")

    if not payload:
        raise HTTPException(
            status_code=400,
            detail="No eMediplan payload provided",
        )

    try:
        payload = resolve_emediplan_payload(payload, content_type)
        bundle = emediplan_to_fhir_bundle(payload)
        cda_xml = fhir_medications_to_epic_cda(bundle)
        return Response(content=cda_xml, media_type="application/xml")
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except Exception as ex:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(ex))


@app.get("/fhir/medications/epic-cda/from-server")
async def fhir_medications_epic_cda_from_server(
    patient_id: Optional[str] = Query(None),
    count: int = Query(100, ge=1, le=1000),
):
    try:
        bundle = fetch_medication_bundle_from_fhir_server(
            FHIR_BASE,
            patient_id=patient_id,
            count=count,
        )
        cda_xml = fhir_medications_to_epic_cda(bundle)
        return Response(content=cda_xml, media_type="application/xml")
    except requests.HTTPError as ex:
        raise HTTPException(
            status_code=502,
            detail=f"FHIR server request failed: {str(ex)}",
        )
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except Exception as ex:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(ex))


@app.post("/cda/umzh/convert")
async def cda_umzh_convert(
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_xml: Optional[str] = Form(None),
    workflow_stage: str = Query("initial", pattern="^(initial|updated|completed)$"),
    target: str = Query("default", pattern="^(default|sandbox-placer)$")
):

    if file is not None:

        xml_content = await file.read()

    elif raw_xml:

        xml_content = raw_xml.encode("utf-8")

    else:

        xml_content = await request.body()

        if not xml_content:
            raise HTTPException(
                status_code=400,
                detail="No CDA content provided"
            )

    try:
        return _validate_bundle(cda_to_umzh_bundle(
            xml_content,
            workflow_stage=workflow_stage,
            target=target,
        ))

    except ET.ParseError as ex:
        raise HTTPException(
            status_code=400,
            detail=f"XML Parse Error: {str(ex)}"
        )

    except Exception as ex:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=str(ex)
        )


@app.post("/cda/umzh/send")
async def cda_umzh_send(
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_xml: Optional[str] = Form(None),
    workflow_stage: str = Query("initial", pattern="^(initial|updated|completed)$"),
    target: str = Query("default", pattern="^(default|sandbox-placer)$"),
    destination_base_url: Optional[str] = Query(None),
    outbound_authorization: Optional[str] = Query(None),
):

    if file is not None:

        xml_content = await file.read()

    elif raw_xml:

        xml_content = raw_xml.encode("utf-8")

    else:

        xml_content = await request.body()

        if not xml_content:
            raise HTTPException(
                status_code=400,
                detail="No CDA content provided"
            )

    resolved_destination = destination_base_url or UMZH_SEND_BASE_URL

    if not resolved_destination:
        raise HTTPException(
            status_code=400,
            detail="destination_base_url is required (query param or UMZH_SEND_BASE_URL env)",
        )

    try:
        bundle = cda_to_umzh_bundle(
            xml_content,
            workflow_stage=workflow_stage,
            target=target,
        )
        _validate_bundle(bundle)

        send_report = send_umzh_bundle(
            bundle=bundle,
            destination_base_url=resolved_destination,
            timeout_seconds=UMZH_SEND_TIMEOUT,
            outbound_authorization=outbound_authorization,
        )

        return {
            "convert": {
                "workflow_stage": workflow_stage,
                "target": target,
                "bundle_entry_count": len(bundle.get("entry", [])),
            },
            "send": send_report,
        }

    except ET.ParseError as ex:
        raise HTTPException(
            status_code=400,
            detail=f"XML Parse Error: {str(ex)}"
        )

    except Exception as ex:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=str(ex)
        )


@app.post("/cda/etoc/convert")
async def cda_etoc_convert(
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_xml: Optional[str] = Form(None),
    workflow_stage: str = Query("initial", pattern="^(initial|updated|completed)$"),
    target: str = Query("default", pattern="^(default|sandbox-placer)$"),
):

    if file is not None:

        xml_content = await file.read()

    elif raw_xml:

        xml_content = raw_xml.encode("utf-8")

    else:

        xml_content = await request.body()

        if not xml_content:
            raise HTTPException(
                status_code=400,
                detail="No CDA content provided"
            )

    try:
        return _validate_bundle(cda_to_etoc_document_bundle(
            xml_content,
            workflow_stage=workflow_stage,
            target=target,
        ))

    except ET.ParseError as ex:
        raise HTTPException(
            status_code=400,
            detail=f"XML Parse Error: {str(ex)}"
        )

    except Exception as ex:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=str(ex)
        )

