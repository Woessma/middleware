"""Sends a CH-VACD document Bundle to an openEHR-based CH-VACD FHIR reference server.

Workflow (as required by the target CH-VACD reference server, e.g.
https://vaccination-demo.raly.ch/api/fhir):
1. Search for an existing Patient first to avoid creating duplicates (same idea as the
   find-or-create pattern in services/patient_service.py against our own FHIR server).
   Preferred search is by identifier; if the destination server rejects that search
   parameter (observed on the raly.ch demo, which only supports `name`), a fallback
   search by family name is used, confirmed by exact given name and birthDate.
   Ambiguous or incomplete searches block creation.
2. Embed "precreated" resources referenced by Composition.author/custodian (e.g.
   Practitioner/Organization, which cda_bundle_service.py only creates on our own
   FHIR_BASE and references by id without including them in the document) by
   fetching them from FHIR_BASE. This step (see `_embed_precreated_resource`) must
   run in main.py's /cda/vacd/send endpoint before `_mark_vacd_bundle`, since that
   function otherwise drops the "precreated" references before this module ever
   sees the bundle, so the document sent externally is self-contained.
3. Rewrite every entry so that fullUrl and internal references follow the official
    CH-VACD 1.0.0 example format (see
    https://fhir.ch/ig/ch-vacd/1.0.0/Bundle-1-1-ImmunizationAdministration.json.html):
   fullUrl = "<destination_base_url>/<ResourceType>/<id>" (absolute), and every
   "reference" pointing at another bundle entry is rewritten to the relative
   "<ResourceType>/<id>" form instead of a urn:uuid. The Patient entry's id is the
   one assigned by (or matched on) the destination server, plus an identifier with
   system "urn:che:epr:ch-vacd:ehr-id" is added.
The CH-VACD document must pass internal validation before step 1 and again
after reference rewriting, immediately before POST /Bundle. Validation errors
or an unavailable validator block the next external step.
Destination-scoped locking and a persistent register protect this middleware's
retries. Existing immunizations are omitted, with a new document identity and
regenerated vaccination narrative; conflicting clinical data require review.
"""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
from html import escape
from typing import Callable, Optional
from urllib.parse import quote

import requests

from config import FHIR_BASE, VACD_IMPORT_DB
from services.fhir_validation_service import FhirValidationError, validate_fhir_bundle
from services.patient_service import PatientLookupError, PatientMatchConflictError
from services.vacd_import_guard import VacdImportGuard

VACD_EHR_ID_SYSTEM = "urn:che:epr:ch-vacd:ehr-id"
VACD_DOCUMENT_PROFILE = (
    "http://fhir.ch/ig/ch-vacd/StructureDefinition/"
    "ch-vacd-document-immunization-administration"
)


class VacdValidationRejected(Exception):
    def __init__(self, outcome: dict, phase: str):
        super().__init__("VACD validation failed; external document send blocked")
        self.outcome = outcome
        self.phase = phase


def _require_valid_vacd(bundle: dict, phase: str) -> dict:
    if (
        bundle.get("type") != "document"
        or VACD_DOCUMENT_PROFILE not in bundle.get("meta", {}).get("profile", [])
    ):
        raise VacdValidationRejected({
            "resourceType": "OperationOutcome",
            "issue": [{
                "severity": "error",
                "code": "invalid",
                "diagnostics": "A CH-VACD immunization administration document is required",
            }],
        }, phase)
    status, outcome = validate_fhir_bundle(bundle)
    if status >= 300 or any(
        issue["severity"] in {"error", "fatal"} for issue in outcome["issue"]
    ):
        raise VacdValidationRejected(outcome, phase)
    return outcome


def _base(base_url: str) -> str:
    return base_url.rstrip("/")


def _headers(outbound_authorization: Optional[str]) -> dict:
    headers = {
        "Content-Type": "application/fhir+json",
        "Accept": "application/fhir+json",
    }
    if outbound_authorization:
        headers["Authorization"] = outbound_authorization
    return headers


def _first_entry_of_type(entries: list, resource_type: str) -> Optional[dict]:
    for entry in entries:
        if (entry.get("resource") or {}).get("resourceType") == resource_type:
            return entry
    return None


def _embed_precreated_resource(bundle: dict, reference: Optional[str], timeout_seconds: int = 30) -> None:
    """Fetches a "ResourceType/id" reference from our own FHIR_BASE and adds it as a
    bundle entry, unless it is already present. Used for resources like Practitioner/
    Organization that cda_bundle_service.py only creates on FHIR_BASE without
    including them in the document bundle itself."""
    if not reference or "/" not in reference:
        return

    resource_type, resource_id = reference.split("/", 1)
    entries = bundle.setdefault("entry", [])

    for entry in entries:
        resource = entry.get("resource") or {}
        if resource.get("resourceType") == resource_type and resource.get("id") == resource_id:
            return  # already embedded

    try:
        response = requests.get(
            f"{FHIR_BASE.rstrip('/')}/{resource_type}/{resource_id}",
            headers={"Accept": "application/fhir+json"},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        resource = response.json()
    except Exception:
        return  # leave the dangling reference to be dropped by the caller

    entries.append({"fullUrl": f"urn:uuid:{uuid.uuid4()}", "resource": resource})


def _rewrite_references(node, old_ref_to_new: dict) -> None:
    if isinstance(node, dict):
        reference = node.get("reference")
        if reference in old_ref_to_new:
            node["reference"] = old_ref_to_new[reference]
        for value in node.values():
            _rewrite_references(value, old_ref_to_new)
    elif isinstance(node, list):
        for item in node:
            _rewrite_references(item, old_ref_to_new)


def _search_patients(
    destination_base_url: str,
    query: str,
    outbound_authorization: Optional[str] = None,
    timeout_seconds: int = 60,
) -> tuple[list, bool]:
    """Runs a Patient search. Returns (candidates, supported).

    `supported` is False when the destination server rejects the search parameter
    (HTTP 400), so the caller can fall back to a different search strategy instead
    of treating it as a hard error.
    """
    url = f"{_base(destination_base_url)}/Patient?{query}"
    response = requests.get(
        url,
        headers=_headers(outbound_authorization),
        timeout=timeout_seconds,
    )
    if response.status_code == 400:
        outcome = response.json()
        issues = outcome.get("issue") or []
        if issues and all(
            issue.get("code") == "not-supported"
            or any(
                phrase in str(issue.get("diagnostics", "")).lower()
                for phrase in ("unknown search parameter", "unsupported search parameter")
            )
            for issue in issues
        ):
            return [], False
    response.raise_for_status()
    bundle = response.json()
    return _search_resources(bundle, "Patient"), True


def _search_resources(bundle: dict, resource_type: str) -> list:
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise PatientLookupError("Destination search returned no FHIR Bundle")
    if bundle.get("type") != "searchset" or not isinstance(bundle.get("entry", []), list):
        raise PatientLookupError("Destination search returned an invalid searchset")
    resources = []
    for entry in bundle.get("entry") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("resource"), dict):
            raise PatientLookupError("Destination search returned an invalid resource entry")
        resource = entry.get("resource") or {}
        if resource.get("resourceType") == "OperationOutcome":
            if any(i.get("severity") in {"error", "fatal", "warning"} for i in resource.get("issue", [])):
                raise PatientLookupError("Destination search reported an incomplete or rejected query")
        elif resource.get("resourceType") == resource_type:
            resources.append(resource)
    links = bundle.get("link") or []
    if not isinstance(links, list) or any(not isinstance(link, dict) for link in links):
        raise PatientLookupError("Destination search returned invalid pagination links")
    if any(link.get("relation") == "next" for link in links):
        raise PatientMatchConflictError("Destination search is paginated; complete review required")
    total = bundle.get("total", len(resources))
    if type(total) is not int or total != len(resources):
        raise PatientLookupError("Destination search is incomplete; send blocked")
    return resources


def _identifiers(resource: dict) -> set:
    identifiers = resource.get("identifier") or []
    if isinstance(identifiers, dict):
        identifiers = [identifiers]
    return {
        (identifier["system"], identifier["value"])
        for identifier in identifiers
        if identifier.get("system") and identifier.get("value")
        and identifier["system"] != VACD_EHR_ID_SYSTEM
    }


def _names(patient: dict) -> set:
    return {
        (name["family"].strip().casefold(), name["given"][0].strip().casefold())
        for name in patient.get("name") or []
        if name.get("family") and name.get("given")
        and name["family"].strip().casefold() != "unknown"
        and name["given"][0].strip().casefold() != "unknown"
    }


def _check_patient_identity(source: dict, candidate: dict) -> None:
    incoming = _identifiers(source)
    existing = _identifiers(candidate)
    for system in {system for system, _ in incoming}:
        incoming_values = {value for authority, value in incoming if authority == system}
        existing_values = {value for authority, value in existing if authority == system}
        if existing_values and not incoming_values.intersection(existing_values):
            raise PatientMatchConflictError("Patient match has conflicting identifiers")
    if source.get("birthDate") and candidate.get("birthDate") and source["birthDate"] != candidate["birthDate"]:
        raise PatientMatchConflictError("Patient identifier match has conflicting birth date")


def create_or_find_vacd_patient(
    patient_resource: dict,
    destination_base_url: str,
    outbound_authorization: Optional[str] = None,
    timeout_seconds: int = 60,
    before_create: Optional[Callable[[], None]] = None,
) -> tuple[dict, bool]:
    """Finds a matching Patient on the destination server, or creates one.

    Returns (patient_json, matched_existing).
    """
    matches = {}
    identifier_supported = True
    for system, value in sorted(_identifiers(patient_resource)):
        candidates, supported = _search_patients(
            destination_base_url,
            f"identifier={quote(system, safe='')}|{quote(value, safe='')}",
            outbound_authorization=outbound_authorization,
            timeout_seconds=timeout_seconds,
        )
        if not supported:
            identifier_supported = False
            break  # server does not support identifier search - fall back to name search below
        if len(candidates) > 1:
            raise PatientMatchConflictError("Patient identifier is not unique")
        for candidate in candidates:
            if (system, value) not in _identifiers(candidate):
                raise PatientLookupError("Destination ignored Patient identifier search")
            if not candidate.get("id"):
                raise PatientLookupError("Destination Patient has no id")
            _check_patient_identity(patient_resource, candidate)
            matches[candidate["id"]] = candidate
    if len(matches) > 1:
        raise PatientMatchConflictError("Patient identifiers refer to different patients")
    if matches:
        return next(iter(matches.values())), True

    names = _names(patient_resource)
    birth_date = patient_resource.get("birthDate")
    if not (names and birth_date) and not (
        identifier_supported and _identifiers(patient_resource)
    ):
        raise PatientMatchConflictError("Patient cannot be safely matched without identifiers or full name and birth date")
    for family in sorted({name[0] for name in names}) if birth_date else []:
        candidates, supported = _search_patients(
            destination_base_url,
            f"name={quote(family, safe='')}",
            outbound_authorization=outbound_authorization,
            timeout_seconds=timeout_seconds,
        )
        if not supported:
            raise PatientLookupError("Destination does not support Patient name search")
        for candidate in candidates:
            if candidate.get("birthDate") == birth_date and names.intersection(_names(candidate)):
                if not candidate.get("id"):
                    raise PatientLookupError("Destination Patient has no id")
                _check_patient_identity(patient_resource, candidate)
                matches[candidate["id"]] = candidate
    if len(matches) > 1:
        raise PatientMatchConflictError("Patient name and birth date are not unique")
    if matches:
        return next(iter(matches.values())), True

    payload = {key: value for key, value in patient_resource.items() if key != "id"}
    payload.setdefault("active", True)
    url = f"{_base(destination_base_url)}/Patient"
    if before_create:
        before_create()
    response = requests.post(
        url,
        json=payload,
        headers=_headers(outbound_authorization),
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    if response.status_code not in {200, 201}:
        raise PatientLookupError("Destination did not confirm synchronous Patient creation")
    patient = response.json()
    if not isinstance(patient, dict) or patient.get("resourceType") != "Patient" or not patient.get("id"):
        raise PatientLookupError("Destination create returned no Patient with id")
    return patient, response.status_code == 200


def _vaccine_codes(resource):
    return {
        (coding["system"], coding["code"])
        for coding in (resource.get("vaccineCode") or {}).get("coding") or []
        if coding.get("system") and coding.get("code")
    }


def _same_immunization(incoming, existing):
    same_identifier = bool(_identifiers(incoming) & _identifiers(existing))
    same_code = bool(_vaccine_codes(incoming) & _vaccine_codes(existing))
    same_date = (
        incoming.get("occurrenceDateTime")
        and incoming.get("occurrenceDateTime") == existing.get("occurrenceDateTime")
    )
    if not same_identifier and not (same_code and same_date):
        return False
    if not same_identifier and (
        not incoming.get("lotNumber")
        or incoming.get("lotNumber") != existing.get("lotNumber")
    ):
        raise PatientMatchConflictError("Possible immunization duplicate needs review (vaccine/date match)")
    for field in (
        "occurrenceDateTime", "occurrenceString", "lotNumber", "status",
        "statusReason", "expirationDate", "doseQuantity", "route", "site",
        "protocolApplied", "primarySource", "reportOrigin", "manufacturer",
        "performer", "reasonCode", "reasonReference", "reaction", "isSubpotent",
        "subpotentReason", "extension", "note",
    ):
        if incoming.get(field) != existing.get(field):
            raise PatientMatchConflictError("Matching immunization has different clinical data")
    if _vaccine_codes(incoming) != _vaccine_codes(existing) or (
        not _vaccine_codes(incoming)
        and incoming.get("vaccineCode") != existing.get("vaccineCode")
    ):
        raise PatientMatchConflictError("Matching immunization has different vaccine codes")
    return True


def _retain_new_immunizations(bundle, existing):
    retained = []
    removed_references = set()
    removed_count = 0
    for entry in bundle.get("entry", []):
        resource = entry.get("resource") or {}
        if resource.get("resourceType") != "Immunization":
            continue
        matches = [_same_immunization(resource, candidate) for candidate in existing + retained]
        if any(matches):
            removed_count += 1
            removed_references.update(
                ref for ref in (entry.get("fullUrl"), f"Immunization/{resource.get('id')}") if ref
            )
        else:
            retained.append(resource)
    if not removed_count:
        return len(retained), 0
    bundle["entry"] = [
        entry for entry in bundle["entry"]
        if (entry.get("resource") or {}).get("resourceType") != "Immunization"
        or any(entry["resource"] is resource for resource in retained)
    ]
    summaries = [
        escape(
            f"{(resource.get('vaccineCode') or {}).get('text') or ', '.join(code for _, code in sorted(_vaccine_codes(resource)))}"
            f" | {resource.get('occurrenceDateTime') or resource.get('occurrenceString') or ''}"
            f" | {resource.get('lotNumber') or ''}"
        )
        for resource in retained
    ]
    narrative = '<div xmlns="http://www.w3.org/1999/xhtml"><ul>' + "".join(
        f"<li>{summary}</li>" for summary in summaries
    ) + "</ul></div>"

    def rebuild_sections(sections):
        for section in sections:
            original = section.get("entry") or []
            section["entry"] = [ref for ref in original if ref.get("reference") not in removed_references]
            is_vaccination_section = any(
                coding.get("code") == "11369-6"
                for coding in (section.get("code") or {}).get("coding") or []
            )
            if len(section["entry"]) != len(original) or is_vaccination_section:
                section["text"] = {"status": "generated", "div": narrative}
                if not section["entry"]:
                    section.pop("entry")
                    section["emptyReason"] = {"coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/list-empty-reason",
                        "code": "unavailable",
                    }]}
            elif not original:
                section.pop("entry", None)
            rebuild_sections(section.get("section") or [])

    new_identifier = {"system": "urn:ietf:rfc:3986", "value": f"urn:uuid:{uuid.uuid4()}"}
    bundle["identifier"] = new_identifier
    for entry in bundle["entry"]:
        resource = entry["resource"]
        if resource.get("resourceType") == "Composition":
            source_identifier = resource.get("identifier")
            if source_identifier:
                resource.setdefault("relatesTo", []).append({
                    "code": "transforms", "targetIdentifier": source_identifier,
                })
            resource["identifier"] = copy.deepcopy(new_identifier)
            rebuild_sections(resource.get("section") or [])
            if "text" in resource:
                resource["text"] = {"status": "generated", "div": narrative}
    return len(retained), removed_count


def _destination_rejected(payload):
    if not isinstance(payload, dict):
        return False
    if payload.get("resourceType") == "OperationOutcome":
        return any(issue.get("severity") in {"error", "fatal"} for issue in payload.get("issue") or [])
    for entry in payload.get("entry") or []:
        response = entry.get("response") or {}
        if str(response.get("status", "")).startswith(("4", "5")):
            return True
        if _destination_rejected(response.get("outcome")) or _destination_rejected(entry.get("resource")):
            return True
    return False


def send_vacd_bundle(
    bundle: dict,
    destination_base_url: str,
    outbound_authorization: Optional[str] = None,
    timeout_seconds: int = 60,
    source_document_hash: Optional[str] = None,
) -> dict:
    if not destination_base_url:
        raise ValueError("destination_base_url is required")
    preflight_outcome = _require_valid_vacd(bundle, "before-patient")
    content_hash = source_document_hash or hashlib.sha256(
        json.dumps(bundle, sort_keys=True).encode()
    ).hexdigest()
    composition = _first_entry_of_type(bundle.get("entry", []), "Composition")
    identifier = (composition or {}).get("resource", {}).get("identifier") or {}
    document_key = (
        json.dumps([identifier["system"], identifier["value"]])
        if identifier.get("system") and identifier.get("value") else content_hash
    )
    with VacdImportGuard(VACD_IMPORT_DB, _base(destination_base_url), document_key, content_hash) as guard:
        if guard.completed:
            return {"status": "skipped", "reason": "document-already-processed"}
        return _send_vacd_bundle(
            copy.deepcopy(bundle), destination_base_url, outbound_authorization,
            timeout_seconds, preflight_outcome, guard,
        )


def _send_vacd_bundle(
    bundle, destination_base_url, outbound_authorization, timeout_seconds,
    preflight_outcome, guard,
):
    if not destination_base_url:
        raise ValueError("destination_base_url is required")

    entries = bundle.get("entry", [])
    patient_entry = _first_entry_of_type(entries, "Patient")

    if patient_entry is None:
        raise ValueError("Bundle does not contain a Patient resource")

    old_patient_id = patient_entry["resource"].get("id")
    patient_resource = patient_entry.get("resource") or {}

    try:
        patient_response, matched_existing = create_or_find_vacd_patient(
            patient_resource,
            destination_base_url=destination_base_url,
            outbound_authorization=outbound_authorization,
            timeout_seconds=timeout_seconds,
            before_create=lambda: guard.record("pending-patient"),
        )
    except requests.HTTPError as ex:
        return {
            "status": "error",
            "destination_base_url": _base(destination_base_url),
            "patient": {
                "url": f"{_base(destination_base_url)}/Patient",
                "http_status": ex.response.status_code if ex.response is not None else None,
                "ok": False,
                "error": str(ex),
            },
        }

    assigned_id = patient_response.get("id")
    if not assigned_id:
        raise ValueError("Destination server did not return a Patient id")
    guard.clear()

    patient_resource["id"] = assigned_id
    identifiers = patient_resource.setdefault("identifier", [])
    if not any(ident.get("system") == VACD_EHR_ID_SYSTEM for ident in identifiers):
        identifiers.append({"system": VACD_EHR_ID_SYSTEM, "value": assigned_id})

    old_ref_to_new = {}
    if old_patient_id:
        old_ref_to_new[f"Patient/{old_patient_id}"] = f"Patient/{assigned_id}"
    for entry in entries:
        resource = entry.get("resource") or {}
        resource_type = resource.get("resourceType")
        resource_id = resource.get("id")
        old_full_url = entry.get("fullUrl")
        if resource_type and resource_id and old_full_url:
            relative = f"{resource_type}/{resource_id}"
            old_ref_to_new[old_full_url] = relative
            entry["fullUrl"] = f"{_base(destination_base_url)}/{relative}"
            old_ref_to_new[entry["fullUrl"]] = relative
    _rewrite_references(bundle, old_ref_to_new)

    existing = []
    if matched_existing:
        response = requests.get(
            f"{_base(destination_base_url)}/Immunization",
            params={"patient": f"Patient/{assigned_id}"},
            headers=_headers(outbound_authorization), timeout=timeout_seconds,
        )
        response.raise_for_status()
        existing = _search_resources(response.json(), "Immunization")
        if any(
            (resource.get("patient") or {}).get("reference") not in {
                f"Patient/{assigned_id}", f"{_base(destination_base_url)}/Patient/{assigned_id}",
            }
            for resource in existing
        ):
            raise PatientLookupError("Destination ignored Immunization patient filter")
        _rewrite_references(existing, old_ref_to_new)
    new_count, duplicate_count = _retain_new_immunizations(bundle, existing)
    if not new_count:
        guard.record("completed")
        return {
            "status": "skipped", "reason": "no-new-immunizations",
            "patient": {"assigned_id": assigned_id, "matched_existing": matched_existing, "ok": True},
            "immunizations": {"new": 0, "skipped": duplicate_count},
            "validation": {"before_patient": preflight_outcome},
        }
    try:
        final_outcome = _require_valid_vacd(bundle, "before-bundle")
    except FhirValidationError as ex:
        raise FhirValidationError(
            "Final VACD validation unavailable; document not sent; "
            "destination patient step already completed"
        ) from ex

    bundle_url = f"{_base(destination_base_url)}/Bundle"
    guard.record("pending-bundle")
    try:
        bundle_response = requests.post(
            bundle_url,
            json=bundle,
            headers=_headers(outbound_authorization),
            timeout=timeout_seconds,
        )
        try:
            bundle_payload = bundle_response.json()
        except ValueError:
            bundle_payload = bundle_response.text

        bundle_result = {
            "url": bundle_url,
            "http_status": bundle_response.status_code,
            "ok": (
                bundle_response.status_code in {200, 201}
                and isinstance(bundle_payload, dict)
                and bool(bundle_payload.get("resourceType"))
                and not _destination_rejected(bundle_payload)
            ),
            "response": bundle_payload,
        }
        if not bundle_result["ok"]:
            bundle_result["error"] = "Destination did not confirm successful document storage; inspect response"
    except requests.RequestException as ex:
        bundle_result = {
            "url": bundle_url,
            "http_status": None,
            "ok": False,
            "error": str(ex),
        }

    if bundle_result.get("ok"):
        guard.record("completed")
    return {
        "status": "sent" if bundle_result.get("ok") else "partial-error",
        "destination_base_url": _base(destination_base_url),
        "immunizations": {"new": new_count, "skipped": duplicate_count},
        "validation": {
            "before_patient": preflight_outcome,
            "before_bundle": final_outcome,
        },
        "patient": {
            "url": f"{_base(destination_base_url)}/Patient",
            "assigned_id": assigned_id,
            "matched_existing": matched_existing,
            "identifier_system": VACD_EHR_ID_SYSTEM,
            "ok": True,
        },
        "bundle": bundle_result,
    }
