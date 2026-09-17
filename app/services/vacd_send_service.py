"""Sends a CH-VACD document Bundle to an openEHR-based CH-VACD FHIR reference server.

Workflow (as required by the target CH-VACD reference server, e.g.
https://vaccination-demo.raly.ch/api/fhir):
1. Search for an existing Patient first to avoid creating duplicates (same idea as the
   find-or-create pattern in services/patient_service.py against our own FHIR server).
   Preferred search is by identifier; if the destination server rejects that search
   parameter (observed on the raly.ch demo, which only supports `name`), a fallback
   search by family name is used, confirmed by an exact birthDate match. Only if no
   match is found is a new Patient created.
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
4. POST the resulting document Bundle to the destination server.
"""
from __future__ import annotations

import uuid
from typing import Optional
from urllib.parse import quote

import requests

from config import FHIR_BASE

VACD_EHR_ID_SYSTEM = "urn:che:epr:ch-vacd:ehr-id"


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
        return [], False
    response.raise_for_status()
    bundle = response.json()
    return [entry["resource"] for entry in bundle.get("entry", []) if entry.get("resource")], True


def create_or_find_vacd_patient(
    patient_resource: dict,
    destination_base_url: str,
    outbound_authorization: Optional[str] = None,
    timeout_seconds: int = 60,
) -> tuple[dict, bool]:
    """Finds a matching Patient on the destination server, or creates one.

    Returns (patient_json, matched_existing).
    """
    for identifier in patient_resource.get("identifier") or []:
        system = identifier.get("system")
        value = identifier.get("value")
        if not system or not value:
            continue
        candidates, supported = _search_patients(
            destination_base_url,
            f"identifier={quote(system)}|{quote(value)}",
            outbound_authorization=outbound_authorization,
            timeout_seconds=timeout_seconds,
        )
        if not supported:
            break  # server does not support identifier search - fall back to name search below
        if candidates:
            return candidates[0], True

    family = next(
        (name["family"] for name in patient_resource.get("name") or [] if name.get("family")),
        None,
    )
    if family:
        birth_date = patient_resource.get("birthDate")
        candidates, supported = _search_patients(
            destination_base_url,
            f"name={quote(family)}",
            outbound_authorization=outbound_authorization,
            timeout_seconds=timeout_seconds,
        )
        if supported:
            for candidate in candidates:
                if not birth_date or candidate.get("birthDate") == birth_date:
                    return candidate, True

    payload = {key: value for key, value in patient_resource.items() if key != "id"}
    payload.setdefault("active", True)
    url = f"{_base(destination_base_url)}/Patient"
    response = requests.post(
        url,
        json=payload,
        headers=_headers(outbound_authorization),
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    return response.json(), False


def send_vacd_bundle(
    bundle: dict,
    destination_base_url: str,
    outbound_authorization: Optional[str] = None,
    timeout_seconds: int = 60,
) -> dict:
    if not destination_base_url:
        raise ValueError("destination_base_url is required")

    entries = bundle.get("entry", [])
    patient_entry = _first_entry_of_type(entries, "Patient")

    if patient_entry is None:
        raise ValueError("Bundle does not contain a Patient resource")

    patient_resource = patient_entry.get("resource") or {}

    try:
        patient_response, matched_existing = create_or_find_vacd_patient(
            patient_resource,
            destination_base_url=destination_base_url,
            outbound_authorization=outbound_authorization,
            timeout_seconds=timeout_seconds,
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

    patient_resource["id"] = assigned_id
    identifiers = patient_resource.setdefault("identifier", [])
    if not any(ident.get("system") == VACD_EHR_ID_SYSTEM for ident in identifiers):
        identifiers.append({"system": VACD_EHR_ID_SYSTEM, "value": assigned_id})

    composition_entry = _first_entry_of_type(entries, "Composition")
    composition = (composition_entry or {}).get("resource") or {}

    # Rewrite every entry to the CH-VACD example's fullUrl/reference scheme: absolute
    # fullUrl per resource, and relative "ResourceType/id" references between entries
    # (plain urn:uuid matching triggered a NullPointerException on the raly.ch demo).
    old_ref_to_new = {}
    known_references = set()
    for entry in entries:
        resource = entry.get("resource") or {}
        resource_type = resource.get("resourceType")
        resource_id = resource.get("id")
        old_full_url = entry.get("fullUrl")
        if resource_type and resource_id and old_full_url:
            known_references.add(f"{resource_type}/{resource_id}")
            old_ref_to_new[old_full_url] = f"{resource_type}/{resource_id}"
            entry["fullUrl"] = f"{_base(destination_base_url)}/{resource_type}/{resource_id}"

    # Drop any author/custodian reference that could not be embedded (e.g. the
    # precreated Practitioner/Organization no longer exists on FHIR_BASE), to avoid
    # sending the destination server a reference it can never resolve.
    if composition:
        composition["author"] = [
            author for author in composition.get("author") or []
            if author.get("reference") in known_references
        ]
        if not composition["author"]:
            composition.pop("author", None)
        custodian = composition.get("custodian") or {}
        if custodian.get("reference") not in known_references:
            composition.pop("custodian", None)

    _rewrite_references(bundle, old_ref_to_new)

    bundle_url = f"{_base(destination_base_url)}/Bundle"
    try:
        bundle_response = requests.post(
            bundle_url,
            json=bundle,
            headers=_headers(outbound_authorization),
            timeout=timeout_seconds,
        )
        try:
            bundle_payload = bundle_response.json()
        except Exception:
            bundle_payload = bundle_response.text

        bundle_result = {
            "url": bundle_url,
            "http_status": bundle_response.status_code,
            "ok": bundle_response.status_code < 300,
            "response": bundle_payload,
        }
    except Exception as ex:
        bundle_result = {
            "url": bundle_url,
            "http_status": None,
            "ok": False,
            "error": str(ex),
        }

    return {
        "status": "sent" if bundle_result.get("ok") else "partial-error",
        "destination_base_url": _base(destination_base_url),
        "patient": {
            "url": f"{_base(destination_base_url)}/Patient",
            "assigned_id": assigned_id,
            "matched_existing": matched_existing,
            "identifier_system": VACD_EHR_ID_SYSTEM,
            "ok": True,
        },
        "bundle": bundle_result,
    }
