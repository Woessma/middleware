import os
import xml.etree.ElementTree as ET
import copy
import hashlib
import json
import logging

DEBUG_MODE = os.getenv(
    "DEBUG_MODE",
    "false"
).lower() == "true"

logger = logging.getLogger(__name__)

from parser.cda.constants import NS

from parser.cda.patient_parser import parse_patient
from parser.cda.practitioner_parser import parse_practitioner
from parser.cda.organization_parser import parse_organization
from parser.cda.encounter_parser import (
    parse_encounters,
)

from domain.patient import HumanName, Address

from services.refdata_service import lookup_gln

from builders.ch_core_patient_builder import (
    build_ch_core_patient,
    set_patient_narrative,
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

from builders.ch_core_related_person_builder import (
    build_ch_core_related_persons,
)

from mappers.organization_mapper import (
    organization_to_fhir_params
)

from builders.document_reference_builder import (
    build_document_reference_with_binaries,
)

from builders.ch_core_composition_builder import (
    build_ch_core_composition,
)

from converter.clinical_note_extractor import (
    extract_clinical_notes,
)

from converter.section_dispatcher import (
    get_section_mapper
)

from converter.profile_detector import (
    detect_profile
)

from services.patient_service import (
    get_or_create_patient
)

from services.practitioner_service import (
    get_or_create_practitioner
)

from services.organization_service import (
    get_or_create_organization
)

from fhir.bundle import (
    build_bundle_entry,
)

from parser.cda.section_parser import (
    extract_sections,
)

from builders.observation_builder import build_observation_from_entry
from utils.fhir_utils import cda_ts_to_fhir_datetime


CH_CORE_DOCUMENT_PROFILE = (
    "http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-document"
)


def _dedupe_bundle_entries(bundle_entries):

    deduped_entries = []
    seen_requests = set()

    for entry in bundle_entries:
        request = entry.get("request", {})
        method = request.get("method")
        url = request.get("url")
        resource = entry.get("resource", {})
        resource_type = resource.get("resourceType")

        # POST entries can legitimately share the same URL (e.g. many Encounters),
        # but they should still be treated as duplicates when they represent the
        # same business resource. Use resource type + business identity instead of
        # the request URL so equivalent resources are deduplicated consistently.
        if method == "POST":
            identifiers = resource.get("identifier", []) or []

            if isinstance(identifiers, dict):
                identifiers = [identifiers]

            normalized_identifiers = tuple(
                sorted(
                    (
                        resource_type,
                        identifier.get("system"),
                        identifier.get("value"),
                    )
                    for identifier in identifiers
                    if identifier.get("system") and identifier.get("value")
                )
            )

            if normalized_identifiers:
                request_key = (
                    method,
                    "identifier",
                    normalized_identifiers,
                )
            else:
                resource_for_hash = copy.deepcopy(resource)
                resource_for_hash.pop("id", None)
                payload_hash = hashlib.sha256(
                    json.dumps(
                        resource_for_hash,
                        sort_keys=True,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                request_key = (
                    method,
                    "payload",
                    resource_type,
                    payload_hash,
                )
        else:
            request_key = (
                method,
                url,
            )

        if request_key in seen_requests:
            logger.debug("SKIP DUPLICATE BUNDLE ENTRY: %s", request_key)
            continue

        seen_requests.add(request_key)
        deduped_entries.append(entry)

    return deduped_entries


def _extract_document_datetime(root):
    effective_time = root.find(
        "./hl7:effectiveTime",
        NS,
    )

    if effective_time is None:
        return None

    return cda_ts_to_fhir_datetime(
        effective_time.attrib.get("value")
    )


def _extract_document_identifier(root):
    identifier = root.find(
        "./hl7:id",
        NS,
    )

    if identifier is None:
        return None

    root_oid = identifier.attrib.get("root")
    extension = identifier.attrib.get("extension")
    value = extension or root_oid

    if not value:
        return None

    if root_oid:
        system = f"urn:oid:{root_oid}"
    else:
        system = "https://woess.ch/fhir/NamingSystem/cda-document-id"

    return {
        "system": system,
        "value": value,
    }


def _extract_document_title(root):
    title = root.findtext(
        "./hl7:title",
        default=None,
        namespaces=NS,
    )

    if title:
        normalized = title.strip()

        if normalized:
            return normalized

    return "Clinical Document"


def _extract_document_type_code(root):
    code_node = root.find(
        "./hl7:code",
        NS,
    )

    if code_node is None:
        return None

    return {
        "code": code_node.attrib.get("code"),
        "codeSystem": code_node.attrib.get("codeSystem"),
        "displayName": code_node.attrib.get("displayName"),
    }


def _extract_document_language(root):
    language_code = root.find(
        "./hl7:languageCode",
        NS,
    )

    if language_code is None:
        return None

    return language_code.attrib.get("code")


def _append_clinical_note_entries(
    bundle_entries,
    sections,
    patient_ref,
    encounter_ref,
    document_datetime,
):
    binary_full_url_by_payload = {}
    note_references = []

    clinical_notes = extract_clinical_notes(
        sections,
        patient_reference=patient_ref,
        document_datetime=document_datetime,
        encounter_reference=encounter_ref,
    )

    for note in clinical_notes:
        document_reference, binary_resources = (
            build_document_reference_with_binaries(note)
        )

        binary_entries = []
        binary_url_map = {}

        for binary_resource in binary_resources:
            payload_key = (
                binary_resource.get("contentType"),
                binary_resource.get("data"),
            )

            if payload_key in binary_full_url_by_payload:
                binary_url_map[
                    f"Binary/{binary_resource['id']}"
                ] = binary_full_url_by_payload[payload_key]
                continue

            binary_entry = build_bundle_entry(binary_resource)

            binary_entries.append(binary_entry)

            binary_full_url_by_payload[payload_key] = (
                binary_entry["fullUrl"]
            )

            binary_url_map[
                f"Binary/{binary_resource['id']}"
            ] = binary_entry["fullUrl"]

        for content in document_reference.get("content", []):
            attachment = content.get("attachment", {})
            attachment_url = attachment.get("url")

            if attachment_url in binary_url_map:
                attachment["url"] = binary_url_map[attachment_url]

        bundle_entries.extend(binary_entries)
        document_reference_entry = build_bundle_entry(
            document_reference
        )
        bundle_entries.append(document_reference_entry)

        note_references.append(
            {
                "reference": (
                    "DocumentReference/"
                    f"{document_reference_entry['resource']['id']}"
                ),
                "sectionCode": note.source_section_code,
                "sectionTitle": note.source_section_title,
            }
        )

    return note_references


def cda_to_fhir_bundle(xml_content, bundle_type="transaction"):

    root = ET.fromstring(xml_content)

    if DEBUG_MODE:

        logger.debug("=== BEFORE PRACTITIONER ===")

        practitioner = parse_practitioner(root)

        logger.debug("=== AFTER PRACTITIONER ===")
        logger.debug("=== PRACTITIONER ===")
        logger.debug("%s", practitioner)

        encounters = parse_encounters(root)

        logger.debug("=== ENCOUNTERS: %s ===", len(encounters))

        patient_new = parse_patient(root)

        logger.debug("=== NEW PATIENT PARSER ===")
        logger.debug("%s", patient_new)

    profile = detect_profile(root)

    logger.info("=== CDA PROFILE DETECTED: %s ===", profile)

    profile_code = (
        f"{profile['vendor']}-"
        f"{profile['profile']}"
    )

    #
    # Practitioner
    #
    practitioner_resource = None
    practitioner_id = None

    practitioner_data = parse_practitioner(root)

    if practitioner_data:

        if practitioner_data.gln and not practitioner_data.names:
            # PROC-EXP-11: CDA sources sometimes reference a prescriber/author only by GLN
            # (no embedded name), same gap as eMediplan - enrich via refdata.ch best-effort.
            refdata_entry = lookup_gln(practitioner_data.gln)
            if refdata_entry:
                if refdata_entry.get("given_name") or refdata_entry.get("family_name"):
                    practitioner_data.names.append(
                        HumanName(
                            given=[refdata_entry["given_name"]] if refdata_entry.get("given_name") else [],
                            family=refdata_entry.get("family_name"),
                        )
                    )
                elif refdata_entry.get("name"):
                    # No given/family split available (e.g. SOAP API or organisation name) -
                    # the builder only renders family/given, so use the whole name as family.
                    practitioner_data.names.append(HumanName(family=refdata_entry["name"]))
                if not practitioner_data.addresses and refdata_entry.get("address"):
                    address = refdata_entry["address"]
                    practitioner_data.addresses.append(
                        Address(
                            lines=address.get("line") or [],
                            postal_code=address.get("postalCode"),
                            city=address.get("city"),
                            state=address.get("state"),
                            country=address.get("country"),
                        )
                    )

        practitioner_resource = (
            build_ch_core_practitioner(
                practitioner_data
            )
        )

        practitioner_id = (
            get_or_create_practitioner(
                practitioner_resource
            )
        )

        logger.info("Practitioner ID: %s", practitioner_id)

    #
    # Organization
    #
    organization_resource = None
    organization_id = None

    org_node = root.find(
        ".//hl7:custodian/"
        "hl7:assignedCustodian/"
        "hl7:representedCustodianOrganization",
        NS
    )

    if org_node is not None:

        org = parse_organization(
            org_node
        )

        organization_resource = (
            build_ch_core_organization(
                org
            )
        )

        params = (
            organization_to_fhir_params(
                org
            )
        )

        existing_org = (
            get_or_create_organization(
                **params
            )
        )

        organization_id = (
            existing_org["id"]
        )

        logger.info("Organization ID: %s", organization_id)
        logger.debug("=== ORGANIZATION ===")
        logger.debug("%s", organization_resource)

    #
    # PractitionerRole
    #
    practitioner_role_resource = None

    if (
        practitioner_id and
        organization_id
    ):

        practitioner_role_resource = (
            build_ch_core_practitioner_role(
                practitioner_id,
                organization_id
            )
        )

    #
    # Patient
    #
    patient_data = parse_patient(root)

    patient = build_ch_core_patient(
        patient_data
    )

    existing_patient_id = get_or_create_patient(
        patient
    )

    patient_ref = (
        f"Patient/{existing_patient_id}"
    )

    document_datetime = _extract_document_datetime(root)
    
    #
    # Encounters
    #
    encounters = parse_encounters(root)

    logger.debug("=== ENCOUNTERS: %s ===", len(encounters))

    encounter_ref = None

    #
    # Bundle
    #
    bundle_entries = []

    patient["id"] = existing_patient_id
    set_patient_narrative(patient)
    bundle_entries.append(
        build_bundle_entry(
            patient
        )
    )

    related_person_resources = build_ch_core_related_persons(
        patient_reference=patient_ref,
        contacts=patient_data.contacts,
    )

    for related_person in related_person_resources:
        bundle_entries.append(
            build_bundle_entry(
                related_person
            )
        )

    if practitioner_role_resource:

        bundle_entries.append(
            build_bundle_entry(
                practitioner_role_resource
            )
        )
    
    #
    # Encounters
    #
    for encounter in encounters:
        
        logger.debug("%s", encounter)

        encounter_resource = (
            build_ch_core_encounter(
                encounter=encounter,
                patient_ref=patient_ref,
                organization_ref=(
                    f"Organization/{organization_id}"
                    if organization_id
                    else None
                ),
            )
        )

        bundle_entries.append(
            build_bundle_entry(
                encounter_resource
            )
        )

        if encounter_ref is None:
            encounter_ref = (
                f"Encounter/{encounter_resource['id']}"
            )

    sections = extract_sections(root)

    clinical_note_references = _append_clinical_note_entries(
        bundle_entries,
        sections,
        patient_ref,
        encounter_ref,
        document_datetime,
    )

    mapping_context = {
        "practitioner_id": practitioner_id,
        "organization_id": organization_id,
    }
    section_resource_references = []

    for section in sections:

        section_title = section.get("title")

        section_code_obj = (
            section.get("code") or {}
        )

        section_code = (
            section_code_obj.get("code")
        )

        if section_code == "30954-2":
            logger.debug("=== SECTION 30954-2 DEBUG ===")
            logger.debug(
                "%s",
                json.dumps(
                    section,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False
                )
            )

        mapper = get_section_mapper(
            section_code
        )

        if mapper:

            mapped_resources = mapper(
                section,
                patient_ref,
                mapping_context
            )

            for resource in mapped_resources:
                resource_entry = build_bundle_entry(resource)

                bundle_entries.append(
                    resource_entry
                )

                section_resource_references.append(
                    {
                        "reference": (
                            f"{resource_entry['resource']['resourceType']}/"
                            f"{resource_entry['resource']['id']}"
                        ),
                        "sectionCode": section_code,
                        "sectionTitle": section_title,
                    }
                )

            continue

        #
        # Fallback
        #
        for cda_entry in section.get(
            "entries",
            []
        ):

            observation = (
                build_observation_from_entry(
                    cda_entry,
                    patient_ref,
                    section_title
                )
            )

            if observation:
                observation_entry = build_bundle_entry(observation)

                bundle_entries.append(
                    observation_entry
                )

                section_resource_references.append(
                    {
                        "reference": (
                            f"Observation/"
                            f"{observation_entry['resource']['id']}"
                        ),
                        "sectionCode": section_code,
                        "sectionTitle": section_title,
                    }
                )

    deduped_entries = _dedupe_bundle_entries(bundle_entries)
    available_references = {
        (
            f"{entry['resource']['resourceType']}/"
            f"{entry['resource']['id']}"
        )
        for entry in deduped_entries
        if entry.get("resource", {}).get("resourceType")
        and entry.get("resource", {}).get("id")
    }
    clinical_note_references = [
        reference
        for reference in clinical_note_references
        if reference["reference"] in available_references
    ]
    section_resource_references = [
        reference
        for reference in section_resource_references
        if reference["reference"] in available_references
    ]
    composition_section_references = {
        reference["reference"]
        for reference in (
            section_resource_references
            + clinical_note_references
        )
    }

    for entry in deduped_entries:
        resource = entry.get("resource", {})
        resource_type = resource.get("resourceType")
        resource_id = resource.get("id")
        resource_reference = (
            f"{resource_type}/{resource_id}"
            if resource_type and resource_id
            else None
        )

        if resource_reference in composition_section_references:
            entry["request"] = {
                "method": "PUT",
                "url": resource_reference,
            }

    composition_identifier = _extract_document_identifier(root)
    composition_resource = build_ch_core_composition(
        patient_reference=patient_ref,
        document_type_code=_extract_document_type_code(root),
        title=_extract_document_title(root),
        date=document_datetime,
        section_summaries=sections,
        clinical_note_references=clinical_note_references,
        section_resource_references=section_resource_references,
        composition_identifier=composition_identifier,
        practitioner_reference=(
            f"Practitioner/{practitioner_id}"
            if practitioner_id
            else None
        ),
        organization_reference=(
            f"Organization/{organization_id}"
            if organization_id
            else None
        ),
        encounter_reference=encounter_ref,
        language=_extract_document_language(root),
        use_ch_ips_profile=True,
    )

    deduped_entries.append(
        build_bundle_entry(
            composition_resource
        )
    )

    if bundle_type == "document":
        document_entries = [
            {
                "fullUrl": entry["fullUrl"],
                "resource": entry["resource"],
            }
            for entry in deduped_entries
        ]

        composition_entries = [
            entry
            for entry in document_entries
            if entry.get("resource", {}).get("resourceType") == "Composition"
        ]

        other_entries = [
            entry
            for entry in document_entries
            if entry.get("resource", {}).get("resourceType") != "Composition"
        ]

        bundle = {
            "resourceType": "Bundle",
            "type": "document",
            "meta": {
                "profile": [
                    CH_CORE_DOCUMENT_PROFILE,
                ],
                "tag": [
                    {
                        "system": "http://woess.ch/cda-profile",
                        "code": profile_code,
                    }
                ],
            },
            "entry": composition_entries + other_entries,
        }

        if document_datetime:
            bundle["timestamp"] = document_datetime

        if composition_identifier:
            bundle["identifier"] = composition_identifier

        return bundle

    bundle = {
        "resourceType": "Bundle",
        "type": "transaction",
        "meta": {
            "tag": [
                {
                    "system":
                        "http://woess.ch/cda-profile",
                    "code":
                        profile_code
                }
            ]
        },
        "entry": deduped_entries
    }

    return bundle