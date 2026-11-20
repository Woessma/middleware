import hashlib
import logging
import os
import re
import secrets
import threading
import time

import requests

from config import FHIR_BASE, PMLC_KEYCLOAK_ISSUER
from services.echosos_service import (
    _patient_resource, build_echosos_transaction, extract_echosos_url, import_echosos, parse_echosos_data,
)
from services.fhir_mdm_service import (
    FhirMdmLookupError, FhirMdmMatchConflictError, MDM_RECORD_STATUS_SYSTEM,
    find_linked_golden_id, find_mdm_matches,
)
from services.pmlc_auth_service import authorize_keycloak

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_pending = {}
_ttl = 300


def _golden_patient(patient):
    return any(
        tag.get("system") == MDM_RECORD_STATUS_SYSTEM and tag.get("code") == "GOLDEN_RECORD"
        for tag in patient.get("meta", {}).get("tag", [])
    )


def _candidates(data):
    by_id = {}
    matches = find_mdm_matches(_patient_resource(data))
    for match in matches:
        resource = match["resource"]
        candidate_id = resource["id"]
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,64}", candidate_id):
            raise FhirMdmLookupError("Invalid MDM candidate ID")
        golden_id = candidate_id if _golden_patient(resource) else find_linked_golden_id("Patient", candidate_id)
        if not golden_id or golden_id in by_id:
            continue
        response = requests.get(
            f"{FHIR_BASE.rstrip('/')}/Patient/{golden_id}",
            headers={"Accept": "application/fhir+json"}, timeout=10,
        )
        response.raise_for_status()
        try:
            golden = response.json()
        except ValueError as exc:
            raise FhirMdmLookupError("Invalid Golden Patient response") from exc
        if not isinstance(golden, dict) or golden.get("resourceType") != "Patient" or golden.get("id") != golden_id:
            raise FhirMdmLookupError("Invalid Golden Patient response")
        if _golden_patient(golden) and golden.get("active") is not False:
            names = golden.get("name") or []
            name = next((n for n in names if n.get("use") == "official"), names[0] if names else {})
            by_id[golden_id] = {
                "patientId": golden_id,
                "name": name.get("text") or " ".join([*name.get("given", []), name.get("family", "")]).strip(),
                "birthDate": golden.get("birthDate"),
            }
    return by_id


def authorize_echosos(authorization: str) -> dict:
    return authorize_keycloak(
        authorization,
        issuer=os.getenv("ECHOSOS_KEYCLOAK_ISSUER", PMLC_KEYCLOAK_ISSUER),
        audience=os.getenv("ECHOSOS_KEYCLOAK_AUDIENCE", ""),
        clients=os.getenv("ECHOSOS_KEYCLOAK_ALLOWED_CLIENTS", "app-omnilink-cardtest"),
        required_role=os.getenv("ECHOSOS_KEYCLOAK_REQUIRED_ROLE", ""),
        purpose="EchoSOS",
    )


def _review_binding(source, claims, purpose):
    digest = hashlib.sha256(source.encode()).hexdigest()
    return (purpose, claims["iss"], claims["sub"], claims.get("azp"), digest)


def start_patient_review(data, source, claims, *, purpose):
    candidates = _candidates(data)
    if not candidates or len(candidates) > 10:
        raise FhirMdmMatchConflictError("Keine überschaubare Liste prüfbarer Golden Patients verfügbar.")

    review_id = secrets.token_urlsafe(32)
    now = time.monotonic()
    binding = _review_binding(source, claims, purpose)
    with _lock:
        for key, (expiry, *_) in list(_pending.items()):
            if expiry <= now:
                del _pending[key]
        if len(_pending) >= 512:
            raise FhirMdmMatchConflictError("Zu viele offene Zuordnungen. Bitte später erneut scannen.")
        _pending[review_id] = (now + _ttl, binding, frozenset(candidates))
    return {
        "code": "patient_review_required", "reviewId": review_id,
        "expiresIn": _ttl, "candidates": list(candidates.values()),
    }


def confirm_patient_review(payload, data, source, claims, *, purpose):
    review_id, patient_id = payload.get("reviewId"), payload.get("patientId")
    if not isinstance(review_id, str) or not isinstance(patient_id, str) or payload.get("identityVerified") is not True:
        raise ValueError("Zuordnung und unabhängige Identitätsprüfung müssen bestätigt werden")
    binding = _review_binding(source, claims, purpose)
    with _lock:
        pending = _pending.get(review_id)
        if (not pending or pending[0] <= time.monotonic() or pending[1] != binding
                or patient_id not in pending[2]):
            raise FhirMdmMatchConflictError("Zuordnung ungültig oder abgelaufen. Bitte erneut scannen.")
        del _pending[review_id]

    if patient_id not in _candidates(data):
        raise FhirMdmMatchConflictError("Patientenvorschlag hat sich geändert. Bitte erneut scannen.")
    return patient_id


def review_echosos(payload, authorization):
    if not isinstance(payload, dict) or not isinstance(payload.get("sourceUrl"), str):
        raise ValueError("Ungültige EchoSOS-Prüfanfrage")
    action = payload.get("action")
    if action not in ("review", "confirm"):
        raise ValueError("Unbekannte EchoSOS-Prüfaktion")
    claims = authorize_echosos(authorization)
    author = claims.get("preferred_username") or claims["sub"]
    raw = payload["sourceUrl"].encode()
    if len(raw) > 32768 or not raw.startswith((b"https://", b"http://")):
        raise ValueError("Ungültiger EchoSOS-Link")
    source = extract_echosos_url(raw, "text/plain")

    if action == "review":
        try:
            return 200, import_echosos(raw, "text/plain", author=author)
        except FhirMdmMatchConflictError:
            return 409, start_patient_review(parse_echosos_data(source), source, claims, purpose="import")

    data = parse_echosos_data(source)
    patient_id = confirm_patient_review(payload, data, source, claims, purpose="import")
    bundle = build_echosos_transaction(data, _patient_resource(data), {"id": patient_id}, author)
    if not bundle["entry"]:
        raise ValueError("Der Scan enthält keine importierbaren klinischen Angaben")
    logger.info("EchoSOS manual patient assignment authorized: actor=%s target=Patient/%s", claims["sub"], patient_id)
    return 200, bundle
