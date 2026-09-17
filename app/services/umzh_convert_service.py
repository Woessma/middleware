import hashlib
import uuid
from datetime import datetime, timezone

from builders.diagnostic_report_builder import build_diagnostic_report
from builders.servicerequest_builder import build_umzh_servicerequest
from builders.task_builder import build_umzh_task
from config import FHIR_BASE
from domain.diagnostic_report import DiagnosticReportData
from domain.service_request import ServiceRequestData
from domain.task import TaskData
from services.cda_bundle_service import cda_to_fhir_bundle

UMZH_QUESTIONNAIRE_URL = (
    "http://fulfiller.example.org/ch-umzh-connect/QuestionnaireSmokingStatus"
)

SANDBOX_PLACER_FHIR_BASE = "http://localhost:8080/fhir"
SANDBOX_REGISTRY_BASE = "http://localhost:8084/fhir"
SANDBOX_PLACER_ORG_REF = f"{SANDBOX_REGISTRY_BASE}/Organization/HospitalP"
SANDBOX_FULFILLER_ORG_REF = f"{SANDBOX_REGISTRY_BASE}/Organization/HospitalF"

TASK_BUSINESS_STATUS_NEEDS_INFO = (
    "The fulfiller needs more information in order to proceed with the fulfillment of the request"
)

CH_ETOC_SERVICEREQUEST_PROFILE = (
    "http://fhir.ch/ig/ch-etoc/StructureDefinition/ch-etoc-servicerequest"
)

CH_ETOC_DOCUMENT_PROFILE = (
    "http://fhir.ch/ig/ch-etoc/StructureDefinition/ch-etoc-document"
)

CH_ETOC_COMPOSITION_PROFILE = (
    "http://fhir.ch/ig/ch-etoc/StructureDefinition/ch-etoc-composition"
)

CH_ETOC_LAB_OBSERVATION_PROFILE = (
    "http://fhir.ch/ig/ch-etoc/StructureDefinition/ch-etoc-lab-observation"
)

CH_ETOC_PATHOLOGY_OBSERVATION_PROFILE = (
    "http://fhir.ch/ig/ch-etoc/StructureDefinition/ch-etoc-pathology-observation"
)

CH_ETOC_RADIOLOGY_OBSERVATION_PROFILE = (
    "http://fhir.ch/ig/ch-etoc/StructureDefinition/ch-etoc-radiology-observation"
)

CH_ETOC_CARDIOLOGY_OBSERVATION_PROFILE = (
    "http://fhir.ch/ig/ch-etoc/StructureDefinition/ch-etoc-cardiology-observation"
)


def _first_resource_of_type(bundle_entries: list[dict], resource_type: str) -> dict | None:
    for entry in bundle_entries:
        resource = entry.get("resource", {})

        if resource.get("resourceType") == resource_type:
            return resource

    return None


def _all_resources_of_type(bundle_entries: list[dict], resource_type: str) -> list[dict]:
    resources = []

    for entry in bundle_entries:
        resource = entry.get("resource", {})

        if resource.get("resourceType") == resource_type:
            resources.append(resource)

    return resources


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _stable_suffix(*parts: str) -> str:
    raw = "|".join(parts)

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:12]


def _fhir_base(base_url: str | None = None) -> str:
    resolved = base_url or FHIR_BASE
    return resolved.rstrip("/")


def _absolute_ref(reference: str, base_url: str | None = None) -> str:
    if reference.startswith("http://") or reference.startswith("https://"):
        return reference

    return f"{_fhir_base(base_url)}/{reference.lstrip('/')}"


def _resource_absolute_url(resource_type: str, resource_id: str, base_url: str | None = None) -> str:
    return _absolute_ref(f"{resource_type}/{resource_id}", base_url=base_url)


def _resolve_target_config(target: str | None) -> dict:
    target_name = (target or "default").strip().lower()

    if target_name == "sandbox-placer":
        return {
            "target": target_name,
            "resource_base": SANDBOX_PLACER_FHIR_BASE,
            "task_requester": SANDBOX_PLACER_ORG_REF,
            "task_owner": SANDBOX_FULFILLER_ORG_REF,
        }

    if target_name == "default":
        return {
            "target": target_name,
            "resource_base": FHIR_BASE,
            "task_requester": None,
            "task_owner": None,
        }

    raise ValueError("target must be one of: default, sandbox-placer")


def _questionnaire_resource(questionnaire_id: str) -> dict:
    return {
        "resourceType": "Questionnaire",
        "id": questionnaire_id,
        "url": UMZH_QUESTIONNAIRE_URL,
        "version": "1.0.0-ballot",
        "status": "active",
        "title": "Smoking Status Inquiry",
        "subjectType": [
            "Patient",
        ],
        "item": [
            {
                "linkId": "smoking-status",
                "text": "What is the patient's smoking status?",
                "type": "choice",
                "required": True,
                "answerOption": [
                    {
                        "valueCoding": {
                            "system": "http://snomed.info/sct",
                            "code": "266919005",
                            "display": "Never smoked tobacco",
                        }
                    },
                    {
                        "valueCoding": {
                            "system": "http://snomed.info/sct",
                            "code": "8517006",
                            "display": "Ex-smoker",
                        }
                    },
                    {
                        "valueCoding": {
                            "system": "http://snomed.info/sct",
                            "code": "77176002",
                            "display": "Smoker",
                        }
                    },
                ],
            },
            {
                "linkId": "pack-years",
                "text": "What is the patient's pack years?",
                "type": "decimal",
                "required": False,
            },
        ],
    }


def _questionnaire_response_resource(
    questionnaire_response_id: str,
    patient_ref: str,
    authored_on: str,
) -> dict:
    return {
        "resourceType": "QuestionnaireResponse",
        "id": questionnaire_response_id,
        "status": "completed",
        "questionnaire": UMZH_QUESTIONNAIRE_URL,
        "subject": {
            "reference": patient_ref,
        },
        "authored": authored_on,
        "item": [
            {
                "linkId": "smoking-status",
                "answer": [
                    {
                        "valueCoding": {
                            "system": "http://snomed.info/sct",
                            "code": "8517006",
                            "display": "Ex-smoker",
                        }
                    }
                ],
            },
            {
                "linkId": "pack-years",
                "answer": [
                    {
                        "valueDecimal": 50,
                    }
                ],
            },
        ],
    }


def _diagnostic_report_presented_form(
    source_entries: list[dict],
    resource_base: str,
) -> dict | None:
    document_reference = _first_resource_of_type(
        source_entries,
        "DocumentReference",
    )

    if document_reference is None:
        return None

    attachments = (
        (document_reference.get("content") or [{}])[0].get("attachment")
        or {}
    )

    if not attachments:
        return None

    presented_form = {}

    for key in (
        "contentType",
        "language",
        "title",
        "creation",
        "data",
        "size",
        "hash",
    ):
        value = attachments.get(key)
        if value is not None:
            presented_form[key] = value

    if attachments.get("url"):
        presented_form["url"] = _absolute_ref(
            attachments["url"],
            base_url=resource_base,
        )

    return presented_form or None


def _append_profile(resource: dict, profile_url: str) -> None:
    meta = resource.setdefault("meta", {})
    profiles = list(meta.get("profile") or [])

    if profile_url not in profiles:
        profiles.append(profile_url)

    meta["profile"] = profiles


def _replace_or_append_section(composition: dict, section_entry: dict) -> None:
    section_code = (
        ((section_entry.get("code") or {}).get("coding") or [{}])[0].get("code")
    )

    sections = list(composition.get("section") or [])

    for index, existing in enumerate(sections):
        existing_code = (
            (((existing.get("code") or {}).get("coding") or [{}])[0].get("code"))
        )

        if existing_code and existing_code == section_code:
            sections[index] = section_entry
            composition["section"] = sections
            return

    sections.append(section_entry)
    composition["section"] = sections


def _entry_reference(entry: dict) -> str:
    resource = entry.get("resource") or {}
    full_url = entry.get("fullUrl")

    if full_url:
        return full_url

    return f"{resource['resourceType']}/{resource['id']}"


def _upsert_resource_entry(document_entries: list[dict], resource: dict, resource_base: str) -> dict:
    target_type = resource.get("resourceType")
    target_id = resource.get("id")

    for entry in document_entries:
        existing = entry.get("resource") or {}

        if existing.get("resourceType") == target_type and existing.get("id") == target_id:
            entry["resource"] = resource
            return entry

    entry = {
        "fullUrl": _resource_absolute_url(
            target_type,
            target_id,
            base_url=resource_base,
        ),
        "resource": resource,
    }
    document_entries.append(entry)
    return entry


def _observation_keywords(observation: dict) -> str:
    coding_text = []

    for coding in (observation.get("code") or {}).get("coding", []) or []:
        coding_text.append(str(coding.get("code") or ""))
        coding_text.append(str(coding.get("display") or ""))

    coding_text.append(str((observation.get("code") or {}).get("text") or ""))

    return " ".join(coding_text).lower()


def _observation_has_category(observation: dict, category_code: str) -> bool:
    for category in observation.get("category", []) or []:
        for coding in category.get("coding", []) or []:
            if coding.get("code") == category_code:
                return True

    return False


def _etoc_observation_profile(observation: dict) -> str | None:
    text = _observation_keywords(observation)

    if _observation_has_category(observation, "laboratory"):
        return CH_ETOC_LAB_OBSERVATION_PROFILE

    if any(token in text for token in ("pathology", "histology", "biopsy")):
        return CH_ETOC_PATHOLOGY_OBSERVATION_PROFILE

    if any(token in text for token in ("radiology", "imaging", "x-ray", "xray", "ct", "mri", "ultrasound")):
        return CH_ETOC_RADIOLOGY_OBSERVATION_PROFILE

    if any(token in text for token in ("cardiology", "ecg", "ekg", "cardiac")):
        return CH_ETOC_CARDIOLOGY_OBSERVATION_PROFILE

    # Current CDA feeds often lack explicit section markers on Observation.
    # Use lab profile as safe baseline in CH eTOC document mode.
    return CH_ETOC_LAB_OBSERVATION_PROFILE


def _apply_etoc_observation_profiles(document_entries: list[dict]) -> None:
    for entry in document_entries:
        resource = entry.get("resource") or {}

        if resource.get("resourceType") != "Observation":
            continue

        profile = _etoc_observation_profile(resource)

        if profile:
            _append_profile(resource, profile)


def cda_to_umzh_bundle(
    xml_content: bytes,
    workflow_stage: str = "initial",
    target: str = "default",
) -> dict:
    stage = (workflow_stage or "initial").strip().lower()

    if stage not in {
        "initial",
        "updated",
        "completed",
    }:
        raise ValueError("workflow_stage must be one of: initial, updated, completed")

    target_config = _resolve_target_config(target)
    resource_base = target_config["resource_base"]

    source_bundle = cda_to_fhir_bundle(
        xml_content,
        bundle_type="transaction",
    )

    source_entries = source_bundle.get("entry", [])

    patient = _first_resource_of_type(source_entries, "Patient")

    if patient is None:
        raise ValueError("Unable to build UMZH bundle: no Patient found")

    patient_ref_relative = f"Patient/{patient['id']}"
    patient_ref = _absolute_ref(patient_ref_relative, base_url=resource_base)

    practitioner_role = _first_resource_of_type(
        source_entries,
        "PractitionerRole",
    )

    organization = _first_resource_of_type(
        source_entries,
        "Organization",
    )

    condition = _first_resource_of_type(
        source_entries,
        "Condition",
    )

    composition = _first_resource_of_type(
        source_entries,
        "Composition",
    )

    supporting_resources = []

    for resource_type in (
        "MedicationStatement",
        "AllergyIntolerance",
        "DocumentReference",
        "Immunization",
        "Observation",
    ):
        supporting_resources.extend(
            _all_resources_of_type(source_entries, resource_type)
        )

    supporting_info_references = [
        _resource_absolute_url(
            resource["resourceType"],
            resource["id"],
            base_url=resource_base,
        )
        for resource in supporting_resources[:10]
    ]

    authored_on = _utc_today()
    suffix = _stable_suffix(
        patient_ref,
        condition.get("id", "") if condition else "",
        composition.get("id", "") if composition else "",
    )

    service_request_id = f"umzh-sr-{suffix}"
    service_request_requester_ref = None
    reason_references = []

    if practitioner_role is not None:
        service_request_requester_ref = _resource_absolute_url(
            "PractitionerRole",
            practitioner_role["id"],
            base_url=resource_base,
        )

    if condition is not None:
        reason_references.append(
            _resource_absolute_url(
                "Condition",
                condition["id"],
                base_url=resource_base,
            )
        )

    service_request_data = ServiceRequestData(
        identifier_value=f"REF-{authored_on.replace('-', '')}-{suffix}",
        status="active",
        intent="order",
        subject_reference=patient_ref,
        requester_reference=service_request_requester_ref,
        authored_on=authored_on,
        category_codings=[
            {
                "system": "http://snomed.info/sct",
                "code": "183545006",
                "display": "Referral to orthopedic service (procedure)",
            }
        ],
        reason_references=reason_references,
        supporting_info_references=supporting_info_references,
        note_text="Generated from CDA via UMZH convert.",
        additional_profile_urls=[
            CH_ETOC_SERVICEREQUEST_PROFILE,
        ],
    )

    service_request = build_umzh_servicerequest(
        service_request_data,
        resource_id=service_request_id,
    )

    service_request_ref = _resource_absolute_url(
        "ServiceRequest",
        service_request_id,
        base_url=resource_base,
    )

    task_uuid = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"umzh-task|{service_request_id}",
        )
    )

    task_requester_ref = None

    if organization is not None:
        task_requester_ref = _resource_absolute_url(
            "Organization",
            organization["id"],
            base_url=resource_base,
        )

    elif practitioner_role is not None:
        task_requester_ref = _resource_absolute_url(
            "PractitionerRole",
            practitioner_role["id"],
            base_url=resource_base,
        )

    if target_config["task_requester"] is not None:
        task_requester_ref = target_config["task_requester"]

    owner_org_ref = None

    if practitioner_role is not None:
        practitioner_role_org = (practitioner_role.get("organization") or {}).get("reference")
        if practitioner_role_org:
            owner_org_ref = _absolute_ref(practitioner_role_org, base_url=resource_base)

    if target_config["task_owner"] is not None:
        owner_org_ref = target_config["task_owner"]

    task_focus_ref = service_request_ref

    task_input_references = []
    task_output_references = []
    task_status = "requested"
    task_last_modified = None
    task_business_status = None

    questionnaire = None
    questionnaire_response = None

    if stage == "updated":
        task_status = "in-progress"
        task_business_status = TASK_BUSINESS_STATUS_NEEDS_INFO
        task_last_modified = authored_on

        questionnaire = _questionnaire_resource(
            questionnaire_id=f"umzh-questionnaire-{suffix}"
        )

        task_output_references = [
            _resource_absolute_url(
                "Questionnaire",
                questionnaire["id"],
                base_url=resource_base,
            )
        ]

    if stage == "completed":
        task_status = "completed"
        task_last_modified = authored_on

        questionnaire = _questionnaire_resource(
            questionnaire_id=f"umzh-questionnaire-{suffix}"
        )

        questionnaire_response = _questionnaire_response_resource(
            questionnaire_response_id=f"umzh-questionnaireresponse-{suffix}",
            patient_ref=patient_ref,
            authored_on=authored_on,
        )

        task_input_references = [
            _resource_absolute_url(
                "QuestionnaireResponse",
                questionnaire_response["id"],
                base_url=resource_base,
            )
        ]

        task_output_references = [
            _resource_absolute_url(
                "Questionnaire",
                questionnaire["id"],
                base_url=resource_base,
            ),
            _resource_absolute_url(
                "QuestionnaireResponse",
                questionnaire_response["id"],
                base_url=resource_base,
            ),
        ]

    task_data = TaskData(
        identifier_value=f"urn:uuid:{task_uuid}",
        based_on_reference=task_focus_ref,
        focus_reference=task_focus_ref,
        for_reference=patient_ref,
        status=task_status,
        intent="order",
        priority="routine",
        authored_on=authored_on,
        last_modified=task_last_modified,
        requester_reference=task_requester_ref,
        owner_reference=owner_org_ref,
        business_status_text=task_business_status,
        input_references=task_input_references,
        output_references=task_output_references,
    )

    task = build_umzh_task(
        task_data,
        resource_id=f"umzh-task-{suffix}",
    )

    observation_resources = _all_resources_of_type(
        source_entries,
        "Observation",
    )

    diagnostic_result_references = [
        _resource_absolute_url(
            "Observation",
            observation["id"],
            base_url=resource_base,
        )
        for observation in observation_resources[:10]
    ]

    diagnostic_performer_references = []
    if owner_org_ref:
        diagnostic_performer_references.append(owner_org_ref)
    elif task_requester_ref:
        diagnostic_performer_references.append(task_requester_ref)

    diagnostic_presented_form = _diagnostic_report_presented_form(
        source_entries,
        resource_base=resource_base,
    )

    diagnostic_report_data = DiagnosticReportData(
        status="final",
        code_codings=[
            {
                "system": "http://loinc.org",
                "code": "11502-2",
                "display": "Laboratory report",
            }
        ],
        subject_reference=patient_ref,
        based_on_references=[service_request_ref],
        performer_references=diagnostic_performer_references,
        result_references=diagnostic_result_references,
        effective_datetime=authored_on,
        issued=f"{authored_on}T00:00:00Z",
        conclusion="Generated from CDA via UMZH convert.",
        presented_forms=[diagnostic_presented_form] if diagnostic_presented_form else [],
    )

    diagnostic_report = build_diagnostic_report(
        diagnostic_report_data,
        resource_id=f"umzh-dr-{suffix}",
    )

    entries = [
        {
            "fullUrl": _resource_absolute_url(
                "ServiceRequest",
                service_request["id"],
                base_url=resource_base,
            ),
            "resource": service_request,
        },
        {
            "fullUrl": _resource_absolute_url(
                "Task",
                task["id"],
                base_url=resource_base,
            ),
            "resource": task,
        },
        {
            "fullUrl": _resource_absolute_url(
                "DiagnosticReport",
                diagnostic_report["id"],
                base_url=resource_base,
            ),
            "resource": diagnostic_report,
        },
    ]

    if questionnaire is not None:
        entries.append(
            {
                "fullUrl": _resource_absolute_url(
                    "Questionnaire",
                    questionnaire["id"],
                    base_url=resource_base,
                ),
                "resource": questionnaire,
            }
        )

    if questionnaire_response is not None:
        entries.append(
            {
                "fullUrl": _resource_absolute_url(
                    "QuestionnaireResponse",
                    questionnaire_response["id"],
                    base_url=resource_base,
                ),
                "resource": questionnaire_response,
            }
        )

    return {
        "resourceType": "Bundle",
        "type": "collection",
        "meta": {
            "tag": [
                {
                    "system": "http://woess.ch/convert-profile",
                    "code": "umzh-connect",
                },
                {
                    "system": "http://woess.ch/convert-workflow-stage",
                    "code": stage,
                },
                {
                    "system": "http://woess.ch/convert-target",
                    "code": target_config["target"],
                }
            ]
        },
        "entry": entries,
    }


def cda_to_etoc_document_bundle(
    xml_content: bytes,
    workflow_stage: str = "initial",
    target: str = "default",
) -> dict:
    target_config = _resolve_target_config(target)
    resource_base = target_config["resource_base"]
    authored_on = _utc_today()

    document_bundle = cda_to_fhir_bundle(
        xml_content,
        bundle_type="document",
    )

    workflow_bundle = cda_to_umzh_bundle(
        xml_content,
        workflow_stage=workflow_stage,
        target=target,
    )

    document_entries = list(document_bundle.get("entry") or [])
    workflow_entries = list(workflow_bundle.get("entry") or [])

    composition_entry = next(
        (
            entry for entry in document_entries
            if (entry.get("resource") or {}).get("resourceType") == "Composition"
        ),
        None,
    )

    if composition_entry is None:
        raise ValueError("Unable to build CH eTOC document bundle: no Composition found")

    composition = composition_entry["resource"]
    _append_profile(composition, CH_ETOC_COMPOSITION_PROFILE)
    composition.setdefault("status", "final")
    composition.setdefault("title", "Zuweisungsschreiben")
    composition.setdefault(
        "type",
        {
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "371535009",
                    "display": "Transfer of care record",
                }
            ]
        },
    )
    composition.setdefault(
        "category",
        [
            {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": "721927009",
                        "display": "Referral note",
                    }
                ]
            }
        ],
    )

    service_request = _first_resource_of_type(
        workflow_entries,
        "ServiceRequest",
    )
    if service_request is None:
        raise ValueError("Unable to build CH eTOC document bundle: no ServiceRequest found")

    questionnaire = _first_resource_of_type(
        workflow_entries,
        "Questionnaire",
    )
    questionnaire_response = _first_resource_of_type(
        workflow_entries,
        "QuestionnaireResponse",
    )

    patient = _first_resource_of_type(document_entries, "Patient")
    patient_ref = None
    if patient is not None:
        patient_ref = _resource_absolute_url(
            "Patient",
            patient["id"],
            base_url=resource_base,
        )

    if questionnaire is None:
        questionnaire = _questionnaire_resource(
            questionnaire_id=f"etoc-questionnaire-{service_request['id']}",
        )

    if questionnaire_response is None and patient_ref is not None:
        questionnaire_response = _questionnaire_response_resource(
            questionnaire_response_id=f"etoc-questionnaireresponse-{service_request['id']}",
            patient_ref=patient_ref,
            authored_on=authored_on,
        )

    service_request_entry = _upsert_resource_entry(
        document_entries,
        service_request,
        resource_base=resource_base,
    )

    questionnaire_entry = None
    if questionnaire is not None:
        questionnaire_entry = _upsert_resource_entry(
            document_entries,
            questionnaire,
            resource_base=resource_base,
        )

    questionnaire_response_entry = None
    if questionnaire_response is not None:
        questionnaire_response_entry = _upsert_resource_entry(
            document_entries,
            questionnaire_response,
            resource_base=resource_base,
        )

    document_reference_entries = [
        entry for entry in document_entries
        if (entry.get("resource") or {}).get("resourceType") == "DocumentReference"
    ]

    order_referral_references = []

    if questionnaire_entry is not None:
        order_referral_references.append(
            {
                "reference": _entry_reference(questionnaire_entry),
            }
        )

    if questionnaire_response_entry is not None:
        order_referral_references.append(
            {
                "reference": _entry_reference(questionnaire_response_entry),
            }
        )

    order_referral_references.append(
        {
            "reference": _entry_reference(service_request_entry),
        }
    )

    for document_reference_entry in document_reference_entries:
        order_referral_references.append(
            {
                "reference": _entry_reference(document_reference_entry),
            }
        )

    order_referral_section = {
        "title": "Order-Referral",
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "93037-0",
                    "display": "Referral note",
                }
            ]
        },
        "entry": order_referral_references,
    }

    purpose_section = {
        "title": "Purpose",
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "42349-1",
                    "display": "Reason for referral (narrative)",
                }
            ]
        },
        "entry": [
            {
                "reference": _entry_reference(service_request_entry),
            }
        ],
    }

    _replace_or_append_section(composition, order_referral_section)
    _replace_or_append_section(composition, purpose_section)

    _apply_etoc_observation_profiles(document_entries)

    ordered_entries = [composition_entry] + [
        entry
        for entry in document_entries
        if entry is not composition_entry
    ]

    bundle_profiles = list((document_bundle.get("meta") or {}).get("profile") or [])

    if CH_ETOC_DOCUMENT_PROFILE not in bundle_profiles:
        bundle_profiles.append(CH_ETOC_DOCUMENT_PROFILE)

    return {
        "resourceType": "Bundle",
        "type": "document",
        "identifier": {
            "system": "urn:ietf:rfc:3986",
            "value": f"urn:uuid:{uuid.uuid4()}",
        },
        "timestamp": f"{authored_on}T00:00:00Z",
        "meta": {
            "profile": bundle_profiles,
            "tag": [
                {
                    "system": "http://woess.ch/convert-profile",
                    "code": "ch-etoc-document",
                },
                {
                    "system": "http://woess.ch/convert-workflow-stage",
                    "code": workflow_stage,
                },
                {
                    "system": "http://woess.ch/convert-target",
                    "code": target_config["target"],
                },
            ],
        },
        "entry": ordered_entries,
    }