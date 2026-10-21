import uuid
import requests
from urllib.parse import urlsplit

from config import FHIR_BASE
from fhir.identifiers import import_resource_identity
from fhir.narrative import ensure_resource_narrative

from mappers.medication_mapper import (
    get_medication_if_none_exist,
)

from mappers.allergy_mapper import (
    get_allergy_if_none_exist,
)


def _preserve_existing_careteam_participants(resource, resource_id):
    if resource.get("resourceType") != "CareTeam" or resource.get("participant"):
        return

    response = requests.get(
        f"{FHIR_BASE}/CareTeam/{resource_id}",
        headers={"Accept": "application/fhir+json"},
        timeout=60,
    )
    if response.status_code == 200:
        existing = response.json()
        if existing.get("participant"):
            resource["participant"] = existing["participant"]

def _find_existing_resource_id(
    resource_type: str, system: str, value: str, resource: dict,
):

    identifier_tokens = [f"{system}|{value}"]
    current_prefix = "https://fhir.omnilink.ch/fhir/NamingSystem/cda-import-"
    legacy_prefix = "https://woess.ch/fhir/NamingSystem/cda-import-"
    if system.startswith(current_prefix):
        identifier_tokens.append(f"{legacy_prefix}{system[len(current_prefix):]}|{value}")
    elif system.startswith(legacy_prefix):
        identifier_tokens.append(f"{current_prefix}{system[len(legacy_prefix):]}|{value}")

    response = requests.get(
        f"{FHIR_BASE}/{resource_type}",
        params={
            "identifier": ",".join(identifier_tokens)
        },
        headers={
            "Accept": "application/fhir+json"
        },
        timeout=60,
    )

    response.raise_for_status()

    bundle = response.json()
    entries = bundle.get("entry", [])

    if not entries:
        return None

    candidates = [entry.get("resource", {}) for entry in entries]
    if len(candidates) == 1:
        return candidates[0].get("id")

    own_id = resource.get("id")
    for candidate in candidates:
        if own_id and candidate.get("id") == own_id:
            return own_id
    identity = import_resource_identity(resource)
    matches = [
        candidate for candidate in candidates
        if import_resource_identity(candidate) == identity
    ]
    if matches:
        preferred = next(
            (candidate for candidate in matches
             if any(identifier.get("system") == system
                    and identifier.get("value") == value
                    for identifier in candidate.get("identifier", []))),
            matches[0],
        )
        return preferred.get("id")
    raise ValueError(f"Ambiguous {resource_type} import identifier; refusing to overwrite")


def _find_existing_consent_id(resource: dict) -> str | None:
    if resource.get("resourceType") != "Consent":
        return None
    patient_reference = (resource.get("patient") or {}).get("reference")
    if not patient_reference:
        raise ValueError("Consent requires a patient reference for duplicate matching")

    target_identity = import_resource_identity(resource)
    next_url = f"{FHIR_BASE.rstrip('/')}/Consent"
    params = {"patient": patient_reference, "_count": "200"}
    seen_urls = set()
    base = urlsplit(FHIR_BASE)
    while next_url:
        parsed = urlsplit(next_url)
        if (
            parsed.scheme != base.scheme
            or parsed.netloc != base.netloc
            or not parsed.path.startswith(base.path.rstrip("/") + "/")
            or next_url in seen_urls
        ):
            raise ValueError("Invalid Consent search pagination link")
        seen_urls.add(next_url)
        response = requests.get(
            next_url, params=params,
            headers={"Accept": "application/fhir+json"}, timeout=60,
        )
        response.raise_for_status()
        bundle = response.json()
        for entry in bundle.get("entry", []):
            candidate = entry.get("resource", {})
            if (
                candidate.get("resourceType") == "Consent"
                and candidate.get("patient", {}).get("reference") == patient_reference
                and import_resource_identity(candidate) == target_identity
                and candidate.get("id")
            ):
                return candidate["id"]
        next_url = next(
            (link["url"] for link in bundle.get("link", [])
             if link.get("relation") == "next"), None,
        )
        params = None
    return None


def _extract_primary_code(resource: dict) -> tuple[str | None, str | None]:
    coding_candidates = []

    for field_name in ["code", "vaccineCode", "medicationCodeableConcept"]:
        codeable = resource.get(field_name) or {}
        coding = codeable.get("coding") or []

        for item in coding:
            system = item.get("system")
            code = item.get("code")

            if system and code:
                coding_candidates.append((system, code))

    if not coding_candidates:
        return None, None

    return coding_candidates[0]


def _extract_subject_search_params(resource_type: str, resource: dict) -> dict:
    subject_ref = (resource.get("subject") or {}).get("reference")
    patient_ref = (resource.get("patient") or {}).get("reference")

    if resource_type in {"AllergyIntolerance", "Immunization"}:
        patient_id = _extract_reference_id(patient_ref or subject_ref)
        return {"patient": patient_id} if patient_id else {}

    subject_id = _extract_reference_id(subject_ref or patient_ref)
    return {"subject": subject_id} if subject_id else {}


def _extract_date_search_params(resource_type: str, resource: dict) -> dict:
    if resource_type == "Observation":
        date_value = resource.get("effectiveDateTime")
        return {"date": date_value} if date_value else {}

    if resource_type == "Procedure":
        date_value = resource.get("performedDateTime")
        return {"date": date_value} if date_value else {}

    if resource_type == "Condition":
        date_value = resource.get("onsetDateTime")
        return {"onset-date": date_value} if date_value else {}

    if resource_type == "Immunization":
        date_value = resource.get("occurrenceDateTime")
        return {"date": date_value} if date_value else {}

    return {}


def _find_existing_resource_id_by_code(resource: dict) -> str | None:
    resource_type = resource.get("resourceType")

    # Restrict lookup to resource types with robust code-based search params.
    if resource_type not in {
        "Observation",
        "Condition",
        "Procedure",
        "Immunization",
        "AllergyIntolerance",
    }:
        return None

    system, code = _extract_primary_code(resource)

    if not system or not code:
        return None

    params = {
        "code": f"{system}|{code}",
        "_count": "1",
    }

    params.update(_extract_subject_search_params(resource_type, resource))
    params.update(_extract_date_search_params(resource_type, resource))

    response = requests.get(
        f"{FHIR_BASE}/{resource_type}",
        params=params,
        headers={
            "Accept": "application/fhir+json"
        },
        timeout=60,
    )

    response.raise_for_status()

    bundle = response.json()
    entries = bundle.get("entry", [])

    if not entries:
        return None

    return entries[0].get("resource", {}).get("id")


def _extract_reference_id(reference: str | None) -> str | None:
    if not reference:
        return None

    return reference.split("/")[-1]


def _first_attachment_fingerprint(resource: dict) -> dict:
    for content in resource.get("content", []) or []:
        attachment = content.get("attachment") or {}

        if attachment:
            return {
                "contentType": attachment.get("contentType"),
                "size": attachment.get("size"),
                "hash": attachment.get("hash"),
                "title": attachment.get("title"),
            }

    return {}


def _is_same_document_reference(candidate: dict, target: dict) -> bool:
    candidate_attachment = _first_attachment_fingerprint(candidate)
    target_attachment = _first_attachment_fingerprint(target)

    if not candidate_attachment or not target_attachment:
        return False

    candidate_hash = candidate_attachment.get("hash")
    target_hash = target_attachment.get("hash")

    if candidate_hash and target_hash:
        return (
            candidate_hash == target_hash
            and candidate_attachment.get("contentType") == target_attachment.get("contentType")
        )

    return (
        candidate_attachment.get("contentType") == target_attachment.get("contentType")
        and candidate_attachment.get("size") == target_attachment.get("size")
        and candidate_attachment.get("title") == target_attachment.get("title")
    )


def _find_existing_document_reference_id(resource: dict) -> str | None:
    if resource.get("resourceType") != "DocumentReference":
        return None

    subject_reference = (resource.get("subject") or {}).get("reference")
    patient_id = _extract_reference_id(subject_reference)
    date = resource.get("date")

    coding = ((resource.get("type") or {}).get("coding") or [])
    coding = coding[0] if coding else {}

    params = {}

    if patient_id:
        params["patient"] = patient_id

    if date:
        params["date"] = date

    code = coding.get("code")
    system = coding.get("system")

    if code and system:
        params["type"] = f"{system}|{code}"
    elif code:
        params["type"] = code

    if not params:
        return None

    response = requests.get(
        f"{FHIR_BASE}/DocumentReference",
        params=params,
        headers={
            "Accept": "application/fhir+json"
        },
        timeout=60,
    )

    response.raise_for_status()

    bundle = response.json()
    entries = bundle.get("entry", [])

    for entry in entries:
        candidate = entry.get("resource", {})

        candidate_id = candidate.get("id")

        if not candidate_id:
            continue

        candidate_subject = (candidate.get("subject") or {}).get("reference")
        candidate_patient_id = _extract_reference_id(candidate_subject)

        if patient_id and candidate_patient_id and candidate_patient_id != patient_id:
            continue

        if _is_same_document_reference(candidate, resource):
            return candidate_id

    return None


def build_bundle_entry(resource: dict) -> dict:

    full_url_id = str(uuid.uuid4())

    if "id" not in resource:
        resource["id"] = str(uuid.uuid4())

    request = {
        "method": "POST",
        "url": resource["resourceType"],
    }

    # Binary resources are generated with stable IDs; upsert by ID avoids
    # creating a new Binary on every import of the same payload.
    if resource.get("resourceType") == "Binary" and resource.get("id"):
        request["method"] = "PUT"
        request["url"] = f"Binary/{resource['id']}"

        return {
            "fullUrl": (
                f"urn:uuid:{full_url_id}"
            ),
            "resource": resource,
            "request": request,
        }

    identifiers = resource.get(
        "identifier",
        [],
    )

    if isinstance(identifiers, dict):
        identifiers = [identifiers]

    if identifiers:

        identifier = identifiers[0]

        system = identifier.get(
            "system"
        )

        value = identifier.get(
            "value"
        )

        if system and value:
            existing_resource_id = _find_existing_resource_id(
                resource["resourceType"],
                system,
                value,
                resource,
            )

            if not existing_resource_id:
                existing_resource_id = _find_existing_consent_id(resource)

            if not existing_resource_id:
                existing_resource_id = _find_existing_document_reference_id(
                    resource
                )

            if existing_resource_id:
                _preserve_existing_careteam_participants(
                    resource,
                    existing_resource_id,
                )
                resource["id"] = existing_resource_id
                request["method"] = "PUT"
                request["url"] = (
                    f"{resource['resourceType']}/{existing_resource_id}"
                )
            else:
                # No server match yet: upsert by our own (deterministic) id so
                # re-imports of the same source data update instead of duplicating.
                request["method"] = "PUT"
                request["url"] = f"{resource['resourceType']}/{resource['id']}"
    else:
        existing_resource_id_by_code = _find_existing_resource_id_by_code(
            resource
        )

        if existing_resource_id_by_code:
            resource["id"] = existing_resource_id_by_code
            request["method"] = "PUT"
            request["url"] = (
                f"{resource['resourceType']}/{existing_resource_id_by_code}"
            )
        else:
            # Same rationale as above: resources without identifiers (e.g. Patient
            # built from eMediplan payloads) still carry a stable builder-assigned id.
            request["method"] = "PUT"
            request["url"] = f"{resource['resourceType']}/{resource['id']}"

    ensure_resource_narrative(resource)

    return {
        "fullUrl": (
            f"urn:uuid:{full_url_id}"
        ),
        "resource": resource,
        "request": request,
    }