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
from urllib.parse import urljoin, urlsplit

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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool


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
    build_ch_core_patient,
    ensure_contact_address,
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
    VacdValidationRejected,
    _embed_precreated_resource,
)
from services.emediplan_service import (
    enrich_emediplan_bundle,
    emediplan_to_fhir_bundle,
    fhir_medications_to_epic_cda,
    fetch_medication_bundle_from_fhir_server,
)
from services.patient_service import (
    PatientMatchConflictError,
    PatientLookupError,
    find_matching_patient,
    find_patient_by_id,
)
from services.fhir_duplicate_service import (
    FhirDuplicateLookupError,
    FhirResourceMatchConflictError,
    find_existing_resource_by_identifier,
)
from services.emediplan_qr_service import extract_emediplan_payload_from_file, resolve_emediplan_payload
from services.echosos_service import import_echosos, extract_echosos_url, parse_echosos_data
from services.card_analysis_service import analyze_card
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

from config import (
    EPIC_JWKS_KID,
    EPIC_PUBLIC_KEY_PATH,
    FHIR_BASE,
    FHIR_EXTERNAL_BASE_URL,
    FHIR_EXTERNAL_TIMEOUT,
    TERMINOLOGY_BASE_URL,
    TERMINOLOGY_VALIDATION_MODE,
    VACD_SEND_BASE_URL,
    VACD_SEND_TIMEOUT,
)
from services.jwks_service import JwksConfigurationError, build_jwks
from services.fhir_validation_service import FhirValidationError, validate_fhir_bundle
from services.cda_validation_service import (
    CdaValidationError,
    MAX_CDA_BYTES,
    validate_cda_source,
)
from services.pmlc_service import PmlcServiceError, PmlcSourceError, generate_pmlc
from services.pmlc_auth_service import PmlcAuthError, authorize_pmlc
from services.vacd_validation_service import VacdValidationError, validate_vacd_husky
from services.medication_import_validation_service import MedicationImportRejected, validate_medication_import


UMZH_SEND_BASE_URL = os.getenv("UMZH_SEND_BASE_URL", "")
UMZH_SEND_TIMEOUT = int(os.getenv("UMZH_SEND_TIMEOUT", "60"))
BRIDGELINK_CDA_URL = "https://api.omnilink.ch/v1/cda/convert"
# Ziel fuer /cda/import. Default ist uebergangsweise der bestehende
# BridgeLink-Convert-Kanal (der schreibt bereits nach HAPI). Sobald
# BridgeLink die Route /v1/cda/import bereitstellt, per Env umschalten:
# BRIDGELINK_CDA_IMPORT_URL=https://api.omnilink.ch/v1/cda/import
BRIDGELINK_CDA_IMPORT_URL = os.getenv(
    "BRIDGELINK_CDA_IMPORT_URL",
    BRIDGELINK_CDA_URL,
)
BRIDGELINK_EMEDIPLAN_IMPORT_URL = os.getenv(
    "BRIDGELINK_EMEDIPLAN_IMPORT_URL",
    "https://api.omnilink.ch/v1/emediplan/import",
)
ECHOSOS_IMPORT_URL = "https://api.omnilink.ch/v1/echosos/resolve"

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
        dedupe_identity = (
            ("id", resource.get("resourceType"), resource["id"])
            if resource.get("id")
            else identity
        )
        if method == "POST" and identity[0] == "identifier":
            if "ifNoneExist" not in request:
                identifier_values = [
                    (system, value)
                    for system, value in identity[2]
                    if system and value
                ]
                if identifier_values:
                    _, value = identifier_values[0]
                    request["ifNoneExist"] = f"identifier={value}"

        stabilized_entry = dict(entry)
        ensure_resource_narrative(resource)
        stabilized_entry["request"] = request

        if dedupe_identity in seen:
            logger.info("SKIP DUPLICATE BUNDLE RESOURCE: %s", dedupe_identity)
            continue

        seen.add(dedupe_identity)
        stabilized_entries.append(stabilized_entry)

    stabilized = copy.deepcopy(bundle)
    stabilized["entry"] = stabilized_entries
    return stabilized


def _rewrite_bundle_references(value, reference_map):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "reference" and isinstance(child, str):
                value[key] = reference_map.get(child, child)
            else:
                _rewrite_bundle_references(child, reference_map)
    elif isinstance(value, list):
        for child in value:
            _rewrite_bundle_references(child, reference_map)


def _reconcile_emediplan_patients(bundle):
    patient_entries = [
        entry
        for entry in bundle.get("entry", [])
        if (entry.get("resource") or {}).get("resourceType") == "Patient"
    ]
    entries_to_remove = set()

    for entry in patient_entries:
        patient = entry["resource"]
        existing = find_matching_patient(patient)
        if not existing:
            continue

        existing_id = existing.get("id")
        if not existing_id:
            raise PatientLookupError("Gefundener FHIR Patient enthält keine ID.")
        target_reference = f"Patient/{existing_id}"
        reference_map = {}
        if patient.get("id"):
            reference_map[f"Patient/{patient['id']}"] = target_reference
        if entry.get("fullUrl"):
            reference_map[entry["fullUrl"]] = target_reference

        _rewrite_bundle_references(bundle, reference_map)
        entries_to_remove.add(id(entry))
        logger.info("eMediplan Patient wiederverwendet: %s", existing_id)

    if entries_to_remove:
        bundle["entry"] = [
            entry for entry in bundle.get("entry", [])
            if id(entry) not in entries_to_remove
        ]

    included_patient_refs = {
        f"Patient/{(entry.get('resource') or {}).get('id')}"
        for entry in bundle.get("entry", [])
        if (entry.get("resource") or {}).get("resourceType") == "Patient"
        and (entry.get("resource") or {}).get("id")
    }
    patient_refs = set()

    def collect_patient_references(value):
        if isinstance(value, dict):
            reference = value.get("reference")
            if isinstance(reference, str) and reference.startswith("Patient/"):
                patient_refs.add(reference.split("/_history/", 1)[0])
            for child in value.values():
                collect_patient_references(child)
        elif isinstance(value, list):
            for child in value:
                collect_patient_references(child)

    collect_patient_references(bundle)
    for patient_reference in patient_refs - included_patient_refs:
        patient_id = patient_reference.split("/", 1)[1]
        if not find_patient_by_id(patient_id):
            raise ValueError(
                f"Referenzierter FHIR Patient {patient_id} wurde nicht gefunden."
            )

    return bundle


def _reconcile_existing_emediplan_resources(bundle):
    reference_map = {}
    for entry in bundle.get("entry", []):
        resource = entry.get("resource") or {}
        resource_type = resource.get("resourceType")
        if resource_type not in {"Medication", "MedicationStatement", "Practitioner"}:
            continue

        existing = find_existing_resource_by_identifier(resource)
        if not existing:
            continue

        existing_id = existing["id"]
        previous_id = resource.get("id")
        target_reference = f"{resource_type}/{existing_id}"
        if previous_id:
            reference_map[f"{resource_type}/{previous_id}"] = target_reference
        if entry.get("fullUrl"):
            reference_map[entry["fullUrl"]] = target_reference

        resource["id"] = existing_id
        entry["request"] = {"method": "PUT", "url": target_reference}
        logger.info(
            "eMediplan %s wiederverwendet: %s",
            resource_type,
            existing_id,
        )

    _rewrite_bundle_references(bundle, reference_map)
    return bundle


def _prepare_emediplan_import_bundle(bundle):
    bundle = _stabilize_bundle(bundle)
    bundle["type"] = "transaction"
    bundle = enrich_emediplan_bundle(bundle)
    bundle = _reconcile_emediplan_patients(bundle)
    bundle = _reconcile_existing_emediplan_resources(bundle)
    return validate_medication_import(_validate_bundle(_stabilize_bundle(bundle)))


app = FastAPI(

    docs_url=None,
    redoc_url=None,
    openapi_url=None
)


@app.exception_handler(MedicationImportRejected)
async def medication_import_rejected(request: Request, error: MedicationImportRejected):
    return JSONResponse(status_code=error.status_code, content=error.outcome,
                        media_type="application/fhir+json", headers={"Cache-Control": "no-store"})


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "OmniLink Python Middleware"
    }


@app.get("/.well-known/jwks.json")
def get_epic_jwks(response: Response):
    if not EPIC_PUBLIC_KEY_PATH:
        raise HTTPException(
            status_code=503,
            detail="JWKS is not configured",
        )

    try:
        jwks = build_jwks(EPIC_PUBLIC_KEY_PATH, EPIC_JWKS_KID)
    except JwksConfigurationError as exc:
        logger.error("Unable to provide Epic JWKS: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="JWKS public key is unavailable or invalid",
        ) from exc

    response.headers["Cache-Control"] = "public, max-age=300"
    return jwks


cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:8080,http://127.0.0.1:8080",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _check_service(url):
    started_at = datetime.now(timezone.utc)
    try:
        response = requests.get(url, timeout=3)
        return {
            "status": "online" if response.ok else "degraded",
            "http_status": response.status_code,
            "latency_ms": round((datetime.now(timezone.utc) - started_at).total_seconds() * 1000),
        }
    except requests.RequestException as exc:
        return {
            "status": "offline",
            "error": str(exc),
            "latency_ms": round((datetime.now(timezone.utc) - started_at).total_seconds() * 1000),
        }


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard():
    dashboard_path = os.path.join(os.path.dirname(__file__), "admin_dashboard.html")
    with open(dashboard_path, encoding="utf-8") as dashboard_file:
        return dashboard_file.read()


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _app_file(filename):
    candidates = [
        os.path.join(PROJECT_ROOT, filename),
        os.path.join(os.path.dirname(__file__), filename),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(os.path.dirname(__file__), filename)


ADMIN_DOCUMENTS = {
    "endpoints": {
        "title": "API-Endpunkte",
        "filename": "ENDPOINTS.md",
    },
    "architecture": {
        "title": "Technische Architektur",
        "filename": "architecture.md",
    },
}


def _documentation_file(filename):
    app_docs_path = os.path.join(os.path.dirname(__file__), "docs", filename)
    if os.path.isfile(app_docs_path):
        return app_docs_path

    return os.path.join(os.path.dirname(__file__), "..", "docs", filename)


@app.get("/test-client.html", response_class=FileResponse)
def test_client():
    return FileResponse(_app_file("test-client.html"), media_type="text/html")


@app.get("/echosos-fhir-test.html", response_class=FileResponse)
def echosos_fhir_test():
    return FileResponse(_app_file("echosos-fhir-test.html"), media_type="text/html")


@app.get("/qr-reader.html", response_class=FileResponse, include_in_schema=False)
@app.get("/erezept-reader.html", response_class=FileResponse, include_in_schema=False)
@app.get("/erezept-emediplan-reader.html", response_class=FileResponse)
def erezept_emediplan_reader():
    return FileResponse(_app_file("erezept-emediplan-reader.html"), media_type="text/html")


@app.get("/fhir-query-client.html", response_class=FileResponse)
def fhir_query_client():
    return FileResponse(_app_file("fhir-query-client.html"), media_type="text/html")


@app.get("/fhir-patient-duplicate-test.html", response_class=FileResponse)
def fhir_patient_duplicate_test():
    return FileResponse(_app_file("fhir-patient-duplicate-test.html"), media_type="text/html")


@app.get("/epic-spital-emediplan-cda.html", response_class=FileResponse)
def epic_spital_emediplan_cda():
    return FileResponse(_app_file("epic-spital-emediplan-cda.html"), media_type="text/html")


@app.get("/card-analysis-test.html", response_class=FileResponse)
def card_analysis_test():
    return FileResponse(_app_file("card-analysis-test.html"), media_type="text/html")


@app.get("/keycloak-auth.js", response_class=FileResponse)
def keycloak_auth():
    return FileResponse(_app_file("keycloak-auth.js"), media_type="application/javascript")


@app.get("/admin/api/overview")
def admin_overview():
    return {
        "service": "python-middleware",
        "debug_mode": DEBUG_MODE,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "fhir": _check_service(f"{FHIR_BASE.rstrip('/')}/metadata"),
            "terminology": _check_service(TERMINOLOGY_BASE_URL),
            "vacd_send": _check_service(f"{VACD_SEND_BASE_URL.rstrip('/')}/metadata"),
        },
        "configuration": {
            "fhir_base": FHIR_BASE,
            "terminology_base": TERMINOLOGY_BASE_URL,
            "vacd_send_base": VACD_SEND_BASE_URL,
            "terminology_validation": TERMINOLOGY_VALIDATION_MODE,
            "vacd_send_configured": bool(VACD_SEND_BASE_URL),
            "refdata_configured": bool(os.getenv("REFDATA_API_KEY")),
        },
    }


@app.get("/admin/api/docs")
def admin_documents():
    return [
        {
            "id": document_id,
            "title": document["title"],
            "filename": document["filename"],
        }
        for document_id, document in ADMIN_DOCUMENTS.items()
    ]


@app.get("/admin/api/docs/{document_id}")
def admin_document(document_id: str):
    document = ADMIN_DOCUMENTS.get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")

    document_path = _documentation_file(document["filename"])
    try:
        with open(document_path, encoding="utf-8") as document_file:
            content = document_file.read()
    except OSError as exc:
        logger.exception("Admin documentation unavailable: %s", document["filename"])
        raise HTTPException(status_code=404, detail="Dokument nicht verfügbar") from exc

    return {
        "id": document_id,
        "title": document["title"],
        "filename": document["filename"],
        "content": content,
    }


def _bridge_link_authorization(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer ") or not authorization[7:].strip():
        raise HTTPException(
            status_code=401,
            detail="A Keycloak ****** is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return authorization


async def _bridge_link_post(
    request: Request,
    target_url: str,
    *,
    body: Optional[bytes] = None,
    content_type: Optional[str] = None,
    use_case: str = "CDA",
) -> Response:
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer ") or not authorization[7:].strip():
        raise HTTPException(
            status_code=401,
            detail="A Keycloak Bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    headers = {"Authorization": _bridge_link_authorization(request)}
    for header_name in ("accept", "content-type"):
        header_value = request.headers.get(header_name)
        if header_value:
            headers[header_name.title()] = header_value
    if content_type:
        headers["Content-Type"] = content_type

    if body is None:
        body = await request.body()
    try:
        upstream = await run_in_threadpool(
            requests.post,
            target_url,
            data=body,
            headers=headers,
            timeout=300,
        )
    except requests.RequestException as exc:
        logger.warning("BridgeLink %s request failed: %s", use_case, exc)
        raise HTTPException(
            status_code=502,
            detail=f"BridgeLink {use_case} endpoint unavailable",
        ) from exc

    response_headers = {
        header_name: upstream.headers[header_name]
        for header_name in ("Content-Type", "WWW-Authenticate", "Retry-After", "Location")
        if header_name in upstream.headers
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )


async def _patient_duplicate_search_params(request: Request):
    try:
        params = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Ungültiger Such-Request") from exc
    if not isinstance(params, dict):
        raise HTTPException(status_code=400, detail="Suchparameter müssen ein JSON-Objekt sein")

    allowed_params = {"identifier", "family", "given", "birthdate", "_count"}
    if any(name not in allowed_params for name in params):
        raise HTTPException(status_code=400, detail="Nicht unterstützter Patientensuchparameter")
    if any(not isinstance(value, (str, int)) for value in params.values()):
        raise HTTPException(status_code=400, detail="Patientensuchparameter müssen Textwerte sein")

    params = {name: str(value) for name, value in params.items()}
    has_identifier = bool(params.get("identifier"))
    has_demographics = all(params.get(name) for name in ("family", "given", "birthdate"))
    if has_identifier == has_demographics:
        raise HTTPException(
            status_code=400,
            detail="Genau eine Suche per Identifier oder Name/Geburtsdatum angeben",
        )

    count_text = params.get("_count", "20")
    try:
        count = int(count_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="_count muss eine Zahl sein") from exc
    if count < 1 or count > 100:
        raise HTTPException(status_code=400, detail="_count muss zwischen 1 und 100 liegen")
    params["_count"] = str(count)
    return params


async def _patient_duplicate_search(
    request: Request,
    base_url: str,
    headers: dict,
    timeout: float = FHIR_EXTERNAL_TIMEOUT,
):
    params = await _patient_duplicate_search_params(request)
    try:
        upstream = await run_in_threadpool(
            requests.get,
            f"{base_url.rstrip('/')}/Patient",
            params=params,
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.warning("FHIR-Patientensuche im Dubletten-Test fehlgeschlagen: %s", exc)
        raise HTTPException(status_code=502, detail="FHIR-Server nicht erreichbar") from exc

    response_headers = {
        name: upstream.headers[name]
        for name in ("Content-Type", "Retry-After")
        if name in upstream.headers
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )


async def _patient_duplicate_everything(request: Request, base_url: str, headers: dict):
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Ungültiger Request") from exc
    patient_id = body.get("patientId") if isinstance(body, dict) else None
    if not isinstance(patient_id, str) or not 1 <= len(patient_id) <= 64 or not all(
        character in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-"
        for character in patient_id
    ):
        raise HTTPException(status_code=400, detail="Ungültige Patient-ID")

    base_url = base_url.rstrip("/")
    patient_path = f"Patient/{patient_id}/$everything"
    try:
        upstream = await run_in_threadpool(
            requests.get,
            f"{base_url}/{patient_path}",
            params={"_count": "500"},
            headers=headers,
            timeout=30,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        logger.warning("FHIR-$everything-Abfrage fehlgeschlagen: %s", exc)
        raise HTTPException(status_code=502, detail="FHIR-Abfrage nicht verfügbar") from exc

    if upstream.status_code != 200:
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("Content-Type"),
        )

    try:
        def read_page(content):
            result = json.loads(content)
            if not isinstance(result, dict) or result.get("resourceType") != "Bundle":
                raise ValueError("$everything did not return a Bundle")
            for field in ("entry", "link"):
                items = result.get(field, [])
                if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
                    raise ValueError(f"Invalid $everything {field}")
            return result

        bundle = read_page(upstream.content)
        entries = list(bundle.get("entry", []))
        page = bundle
        base_parts = urlsplit(base_url)
        visited = set()
        while True:
            next_links = [
                link["url"] for link in page.get("link", [])
                if link.get("relation") == "next"
            ]
            if not next_links:
                break
            if len(next_links) != 1:
                raise ValueError("Ambiguous $everything next page")
            next_url = urljoin(base_url + "/", next_links[0])
            parts = urlsplit(next_url)
            allowed_paths = {
                base_parts.path, base_parts.path + "/",
                base_parts.path + "/" + patient_path,
            }
            if (
                (parts.scheme, parts.netloc) != (base_parts.scheme, base_parts.netloc)
                or parts.path not in allowed_paths
                or parts.fragment
                or next_url in visited
            ):
                raise ValueError("Invalid or repeated $everything next page")
            visited.add(next_url)
            next_response = await run_in_threadpool(
                requests.get,
                next_url,
                headers=headers,
                timeout=30,
                allow_redirects=False,
            )
            if next_response.status_code != 200:
                raise ValueError(
                    f"$everything next page returned HTTP {next_response.status_code}"
                )
            page = read_page(next_response.content)
            entries.extend(page.get("entry", []))

        if visited:
            bundle["entry"] = entries
            bundle["link"] = [
                link for link in bundle.get("link", [])
                if link.get("relation") == "self"
            ]
            return Response(
                content=json.dumps(bundle),
                media_type="application/fhir+json",
            )
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning("FHIR-$everything-Antwort oder Pagination ungültig: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="FHIR-Gesamtabfrage unvollständig oder ungültig.",
        ) from exc

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("Content-Type"),
    )


@app.post("/fhir/patient-duplicate-test/local-search")
async def local_patient_duplicate_search(request: Request):
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer ") or not authorization[7:].strip():
        raise HTTPException(
            status_code=401,
            detail="Bitte zuerst mit Keycloak anmelden.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await _patient_duplicate_search(
        request,
        FHIR_BASE,
        {"Accept": "application/fhir+json, application/json", "Authorization": authorization},
        timeout=30,
    )


@app.post("/fhir/patient-duplicate-test/external-search")
async def external_patient_duplicate_search(request: Request):
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer ") or not authorization[7:].strip():
        raise HTTPException(
            status_code=401,
            detail="Bitte zuerst mit Keycloak anmelden.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not FHIR_EXTERNAL_BASE_URL:
        raise HTTPException(status_code=503, detail="Externer FHIR-Server nicht konfiguriert")

    external_authorization = request.headers.get("x-fhir-external-authorization", "")
    headers = {"Accept": "application/fhir+json, application/json"}
    if external_authorization:
        if not (
            external_authorization.lower().startswith("basic ")
            or external_authorization.lower().startswith("bearer ")
        ):
            raise HTTPException(status_code=400, detail="Ungültiger externer Authentifizierungstyp")
        headers["Authorization"] = external_authorization

    return await _patient_duplicate_search(request, FHIR_EXTERNAL_BASE_URL, headers)


@app.post("/fhir/patient-duplicate-test/local-everything")
async def local_patient_duplicate_everything(request: Request):
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer ") or not authorization[7:].strip():
        raise HTTPException(
            status_code=401,
            detail="Bitte zuerst mit Keycloak anmelden.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await _patient_duplicate_everything(
        request,
        FHIR_BASE,
        {"Accept": "application/fhir+json, application/json", "Authorization": authorization},
    )


@app.post("/fhir/patient-duplicate-test/external-everything")
async def external_patient_duplicate_everything(request: Request):
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer ") or not authorization[7:].strip():
        raise HTTPException(
            status_code=401,
            detail="Bitte zuerst mit Keycloak anmelden.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not FHIR_EXTERNAL_BASE_URL:
        raise HTTPException(status_code=503, detail="Externer FHIR-Server nicht konfiguriert")

    headers = {"Accept": "application/fhir+json, application/json"}
    external_authorization = request.headers.get("x-fhir-external-authorization", "")
    if external_authorization:
        if not (
            external_authorization.lower().startswith("basic ")
            or external_authorization.lower().startswith("bearer ")
        ):
            raise HTTPException(status_code=400, detail="Ungültiger externer Authentifizierungstyp")
        headers["Authorization"] = external_authorization
    return await _patient_duplicate_everything(request, FHIR_EXTERNAL_BASE_URL, headers)


@app.post("/_proxy/bridge/cda")
async def bridge_link_cda_proxy(request: Request):
    return await _bridge_link_post(request, BRIDGELINK_CDA_URL)


@app.post("/echosos/preview")
async def echosos_preview(request: Request):
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer ") or not authorization[7:].strip():
        raise HTTPException(status_code=401, detail="Bitte zuerst mit Keycloak anmelden.")
    raw_bytes = await request.body()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Keine QR-Daten vorhanden.")
    try:
        url = await run_in_threadpool(
            extract_echosos_url, raw_bytes, request.headers.get("content-type"),
        )
        return parse_echosos_data(url)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/echosos/import")
async def echosos_import_proxy(request: Request):
    headers = {"Authorization": _bridge_link_authorization(request)}
    for header_name in ("accept", "content-type"):
        header_value = request.headers.get(header_name)
        if header_value:
            headers[header_name.title()] = header_value

    body = await request.body()
    try:
        upstream = await run_in_threadpool(
            requests.post,
            ECHOSOS_IMPORT_URL,
            data=body,
            headers=headers,
            timeout=300,
        )
    except requests.RequestException as exc:
        logger.warning("BridgeLink EchoSOS import failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="BridgeLink EchoSOS endpoint unavailable",
        ) from exc

    response_headers = {
        header_name: upstream.headers[header_name]
        for header_name in ("Content-Type", "WWW-Authenticate", "Retry-After", "Location")
        if header_name in upstream.headers
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )


@app.get("/echosos/fhir/{patient_path:path}")
async def echosos_fhir_proxy(patient_path: str, request: Request):
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer ") or not authorization[7:].strip():
        raise HTTPException(
            status_code=401,
            detail="A Keycloak ****** is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    segments = patient_path.split("/")
    valid_resource_path = segments == ["Patient"]
    if len(segments) in (2, 3) and segments[0] == "Patient":
        patient_id = segments[1]
        valid_patient_id = bool(patient_id) and all(
            character in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-"
            for character in patient_id
        )
        valid_resource_path = valid_patient_id and (
            len(segments) == 2 or segments[2] == "$everything"
        )
    if not valid_resource_path:
        raise HTTPException(status_code=404, detail="FHIR-Abfrage nicht verfügbar")

    headers = {
        "Accept": request.headers.get(
            "accept",
            "application/fhir+json, application/json",
        ),
        "Authorization": authorization,
    }
    try:
        upstream = await run_in_threadpool(
            requests.get,
            f"{FHIR_BASE.rstrip('/')}/{patient_path}",
            params=list(request.query_params.multi_items()),
            headers=headers,
            timeout=30,
        )
        if patient_path.endswith("/$everything") and upstream.status_code == 200:
            try:
                def read_page(content):
                    result = json.loads(content)
                    if not isinstance(result, dict) or result.get("resourceType") != "Bundle":
                        raise ValueError("$everything did not return a Bundle")
                    for field in ("entry", "link"):
                        items = result.get(field, [])
                        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
                            raise ValueError(f"Invalid $everything {field}")
                    return result

                bundle = read_page(upstream.content)
                entries = list(bundle.get("entry", []))
                page = bundle
                visited = set()
                base_url = FHIR_BASE.rstrip("/")
                base_parts = urlsplit(base_url)
                while True:
                    next_links = [
                        link["url"] for link in page.get("link", [])
                        if link.get("relation") == "next"
                    ]
                    if not next_links:
                        break
                    if len(next_links) != 1:
                        raise ValueError("Ambiguous $everything next page")
                    next_url = urljoin(base_url + "/", next_links[0])
                    parts = urlsplit(next_url)
                    allowed_paths = {
                        base_parts.path, base_parts.path + "/",
                        base_parts.path + "/" + patient_path,
                    }
                    if (
                        (parts.scheme, parts.netloc) != (base_parts.scheme, base_parts.netloc)
                        or parts.path not in allowed_paths
                        or parts.fragment
                        or next_url in visited
                    ):
                        raise ValueError("Invalid or repeated $everything next page")
                    visited.add(next_url)
                    next_response = await run_in_threadpool(
                        requests.get, next_url, headers=headers, timeout=30,
                        allow_redirects=False,
                    )
                    if next_response.status_code != 200:
                        raise ValueError(
                            f"$everything next page returned HTTP {next_response.status_code}"
                        )
                    page = read_page(next_response.content)
                    entries.extend(page.get("entry", []))
                if visited:
                    bundle["entry"] = entries
                    bundle["link"] = [
                        link for link in bundle.get("link", [])
                        if link.get("relation") == "self"
                    ]
                    return Response(
                        content=json.dumps(bundle),
                        media_type="application/fhir+json",
                    )
            except (ValueError, KeyError, TypeError) as exc:
                logger.warning("EchoSOS $everything response or pagination is invalid: %s", exc)
                raise HTTPException(
                    status_code=502,
                    detail="FHIR-Gesamtabfrage unvollständig oder ungültig; keine vollständigen Patientendaten geladen.",
                ) from exc
    except requests.RequestException as exc:
        logger.warning("EchoSOS FHIR query failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="FHIR-Abfrage nicht verfügbar",
        ) from exc

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("Content-Type"),
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
        return await run_in_threadpool(validate_medication_import, stabilized)
    except MedicationImportRejected:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.RequestException as exc:
        logger.exception("FHIR convert/send failed")
        raise HTTPException(status_code=502, detail="FHIR server unavailable") from exc
    except Exception as exc:
        logger.exception("FHIR convert failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
@app.get("/", response_class=HTMLResponse)
def root():
    return admin_dashboard()
 
 
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

    for entry in entries:
        entry.pop("request", None)
        entry.pop("response", None)

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
                    "http://fhir.ch/ig/ch-ips/StructureDefinition/ch-ips-composition",
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
                verification_url = (
                    "http://fhir.ch/ig/ch-vacd/StructureDefinition/"
                    "ch-vacd-ext-verification-status"
                )
                extensions = resource.setdefault("extension", [])
                if not any(item.get("url") == verification_url for item in extensions):
                    extensions.append({
                        "url": verification_url,
                        "valueCoding": {
                            "system": "http://snomed.info/sct",
                            "code": "76104008",
                            "display": "Not confirmed by (contextual qualifier) (qualifier value)",
                        },
                    })

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
                    ensure_contact_address(contact)
                    contact.pop("telecom", None)
                    contact["extension"] = [
                        extension
                        for extension in contact.get("extension") or []
                        if extension.get("url")
                        != "https://fhir.omnilink.ch/fhir/StructureDefinition/patient-contact-identifier"
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
        _warn_duplicate_observation_identifiers(bundle)
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


def _validation_outcome_response(status_code, code, diagnostics):
    return JSONResponse(
        status_code=status_code,
        media_type="application/fhir+json",
        content={
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "code": code, "diagnostics": diagnostics}],
        },
    )


async def _validate_converted_bundle(bundle):
    try:
        status_code, outcome = await run_in_threadpool(validate_fhir_bundle, bundle)
    except ValueError as ex:
        return _validation_outcome_response(400, "invalid", str(ex))
    except FhirValidationError as ex:
        logger.error("FHIR validation failed: %s", ex)
        return _validation_outcome_response(502, "exception", str(ex))
    return JSONResponse(
        status_code=status_code, content=outcome, media_type="application/fhir+json"
    )


@app.post("/fhir/validate")
async def fhir_validate(bundle: dict):
    return await _validate_converted_bundle(bundle)


@app.post("/fhir/medications/pmlc/from-server")
async def pmlc_from_server(
    request: Request,
    patient_id: str = Query(..., pattern=r"^[A-Za-z0-9.-]{1,64}$"),
    language: str = Query("de-CH", pattern=r"^(de-CH|fr-CH|it-CH)$"),
    confidentiality: str = Query("restricted", pattern=r"^(normal|restricted|secret)$"),
):
    try:
        await run_in_threadpool(authorize_pmlc, request.headers.get("authorization", ""))
        result = await run_in_threadpool(generate_pmlc, patient_id, language, confidentiality)
    except PmlcAuthError as ex:
        logger.warning("PMLC authorization rejected: %s", ex)
        response = _validation_outcome_response(ex.status_code, "forbidden", str(ex))
        response.headers["Cache-Control"] = "no-store"
        if ex.status_code == 401:
            response.headers["WWW-Authenticate"] = "Bearer"
        return response
    except PmlcSourceError as ex:
        logger.warning("PMLC source rejected: %s", ex)
        return _validation_outcome_response(422, "invalid", str(ex))
    except PmlcServiceError as ex:
        logger.error("PMLC service failed: %s", ex)
        return _validation_outcome_response(502, "exception", str(ex))
    return JSONResponse(
        status_code=422 if result["status"] == "invalid" else 200,
        content=result, headers={"Cache-Control": "no-store"},
    )


@app.post("/cda/validate")
async def cda_validate(
    request: Request,
    bundle_type: str = Query("transaction", pattern="^(transaction|document)$"),
    file: Optional[UploadFile] = File(None),
    raw_xml: Optional[str] = Form(None),
):
    bundle = await cda_convert(request, bundle_type=bundle_type, file=file, raw_xml=raw_xml)
    return await _validate_converted_bundle(bundle)


@app.post("/cda/source/validate")
async def cda_source_validate(
    request: Request,
    level: str = Query("full", pattern="^(xsd|full)$"),
    file: Optional[UploadFile] = File(None),
    raw_xml: Optional[str] = Form(None),
):
    if file is not None:
        xml_content = await file.read(MAX_CDA_BYTES + 1)
    elif raw_xml is not None:
        xml_content = raw_xml.encode("utf-8")
    else:
        chunks = bytearray()
        async for chunk in request.stream():
            chunks.extend(chunk)
            if len(chunks) > MAX_CDA_BYTES:
                break
        xml_content = bytes(chunks)
    if len(xml_content) > MAX_CDA_BYTES:
        logger.warning("CDA source validation rejected oversized input")
        return _validation_outcome_response(413, "too-costly", "CDA exceeds 5 MiB")
    try:
        status_code, outcome = await run_in_threadpool(validate_cda_source, xml_content, level)
    except ValueError as ex:
        logger.warning("CDA source validation rejected input: %s", ex)
        return _validation_outcome_response(400, "invalid", str(ex))
    except CdaValidationError as ex:
        logger.error("CDA source validation failed: %s", ex)
        return _validation_outcome_response(502, "exception", str(ex))
    return JSONResponse(
        status_code=status_code, content=outcome, media_type="application/fhir+json"
    )


@app.post("/cda/vacd/validate")
async def cda_vacd_validate(
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_xml: Optional[str] = Form(None),
):
    bundle = await cda_vacd_convert(
        request, bundle_type="document", file=file, raw_xml=raw_xml
    )
    return await _validate_converted_bundle(bundle)


async def _validate_vacd_with_husky(bundle: dict):
    try:
        status_code, outcome = await run_in_threadpool(validate_vacd_husky, bundle)
    except ValueError as ex:
        logger.warning("Husky VACD validation rejected input: %s", ex)
        response = _validation_outcome_response(400, "invalid", str(ex))
        response.headers["Cache-Control"] = "no-store"
        return response
    except VacdValidationError as ex:
        logger.error("Husky VACD validation failed: %s", ex)
        response = _validation_outcome_response(502, "exception", str(ex))
        response.headers["Cache-Control"] = "no-store"
        return response
    return JSONResponse(
        status_code=status_code, content=outcome, media_type="application/fhir+json",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/fhir/vacd/husky/validate")
async def fhir_vacd_husky_validate(bundle: dict):
    return await _validate_vacd_with_husky(bundle)


@app.post("/cda/vacd/husky/validate")
async def cda_vacd_husky_validate(
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_xml: Optional[str] = Form(None),
):
    bundle = await cda_vacd_convert(
        request, bundle_type="document", file=file, raw_xml=raw_xml
    )
    return await _validate_vacd_with_husky(bundle)


@app.post("/cda/vacd/import")
@app.post("/cda/vacd/prepare")
async def cda_vacd_prepare(
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_xml: Optional[str] = Form(None),
):
    logger.warning("Disabled VACD HAPI import requested")
    return _validation_outcome_response(
        410,
        "not-supported",
        "VACD HAPI import is disabled. Use /cda/vacd/validate without storage.",
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

        send_report = await run_in_threadpool(
            send_vacd_bundle,
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

    except VacdValidationRejected as ex:
        logger.warning("VACD external send blocked by validation: phase=%s", ex.phase)
        outcome = copy.deepcopy(ex.outcome)
        if ex.phase == "before-bundle":
            outcome["issue"].append({
                "severity": "information",
                "code": "informational",
                "diagnostics": (
                    "Document not sent; destination patient step already completed. "
                    "A patient may have been created."
                ),
            })
        return JSONResponse(
            status_code=422,
            media_type="application/fhir+json",
            content=outcome,
            headers={"X-VACD-Validation-Phase": ex.phase},
        )
    except FhirValidationError as ex:
        logger.error("VACD external send blocked: %s", ex)
        return _validation_outcome_response(502, "exception", str(ex))
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


def _warn_duplicate_observation_identifiers(bundle):
    obs_identifiers = {}

    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})

        if resource.get("resourceType") != "Observation":
            continue

        for identifier in resource.get("identifier", []):
            key = (
                identifier.get("system"),
                identifier.get("value"),
            )
            obs_identifiers[key] = obs_identifiers.get(key, 0) + 1

    for key, count in obs_identifiers.items():
        if count > 1:
            logger.warning(
                "DUPLICATE OBSERVATION IDENTIFIER: %s -> %s",
                key,
                count,
            )


@app.post("/cda/import")
async def cda_import_proxy(request: Request):
    """Importiert CDA ueber BridgeLink; BridgeLink schreibt das Bundle nach HAPI FHIR."""
    return await _bridge_link_post(request, BRIDGELINK_CDA_IMPORT_URL)


@app.post("/cda/prepare")
async def cda_prepare(
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_xml: Optional[str] = Form(None),
):
    _bridge_link_authorization(request)
    bundle = await cda_convert(request, bundle_type="transaction", file=file, raw_xml=raw_xml)
    return await run_in_threadpool(validate_medication_import, bundle)


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


@app.post("/emediplan/prepare")
async def emediplan_prepare(
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_payload: Optional[str] = Form(None),
):
    _bridge_link_authorization(request)
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
        raise HTTPException(status_code=400, detail="No eMediplan payload provided")

    try:
        payload = resolve_emediplan_payload(payload, content_type)
        text = payload.decode("utf-8").strip()
        source = json.loads(text) if text.startswith("{") else None
        if isinstance(source, dict) and "resourceType" in source:
            bundle = source
        else:
            bundle = emediplan_to_fhir_bundle(payload)
        return _prepare_emediplan_import_bundle(bundle)
    except HTTPException:
        raise
    except (PatientMatchConflictError, FhirResourceMatchConflictError) as ex:
        raise HTTPException(status_code=409, detail=str(ex)) from ex
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    except (requests.RequestException, PatientLookupError, FhirDuplicateLookupError) as ex:
        logger.exception("FHIR preflight failed during eMediplan preparation")
        raise HTTPException(status_code=502, detail="FHIR preflight lookup unavailable") from ex
    except Exception as ex:
        logger.exception("eMediplan preparation failed")
        raise HTTPException(status_code=500, detail=str(ex)) from ex


@app.post("/emediplan/import")
async def emediplan_import(
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_payload: Optional[str] = Form(None),
):
    _bridge_link_authorization(request)
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
        bundle = _prepare_emediplan_import_bundle(emediplan_to_fhir_bundle(payload))
        bundle_body = json.dumps(bundle).encode("utf-8")
        return await _bridge_link_post(
            request,
            BRIDGELINK_EMEDIPLAN_IMPORT_URL,
            body=bundle_body,
            content_type="application/fhir+json",
            use_case="eMediplan import",
        )
    except HTTPException:
        raise
    except PatientMatchConflictError as ex:
        raise HTTPException(status_code=409, detail=str(ex)) from ex
    except FhirResourceMatchConflictError as ex:
        raise HTTPException(status_code=409, detail=str(ex)) from ex
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except (requests.RequestException, PatientLookupError, FhirDuplicateLookupError) as ex:
        logger.exception("FHIR preflight failed during eMediplan import")
        raise HTTPException(status_code=502, detail="FHIR preflight lookup unavailable") from ex
    except Exception as ex:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(ex))


@app.post("/emediplan/import-bundle")
async def emediplan_import_bundle(
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_json: Optional[str] = Form(None),
):
    _bridge_link_authorization(request)
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
        bundle = _prepare_emediplan_import_bundle(bundle)
        bundle_body = json.dumps(bundle).encode("utf-8")
        return await _bridge_link_post(
            request,
            BRIDGELINK_EMEDIPLAN_IMPORT_URL,
            body=bundle_body,
            content_type="application/fhir+json",
            use_case="eMediplan bundle import",
        )
    except HTTPException:
        raise
    except PatientMatchConflictError as ex:
        raise HTTPException(status_code=409, detail=str(ex)) from ex
    except FhirResourceMatchConflictError as ex:
        raise HTTPException(status_code=409, detail=str(ex)) from ex
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except (requests.RequestException, PatientLookupError, FhirDuplicateLookupError) as ex:
        logger.exception("FHIR preflight failed during eMediplan bundle import")
        raise HTTPException(status_code=502, detail="FHIR preflight lookup unavailable") from ex
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
    _bridge_link_authorization(request)
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
        bundle = _prepare_emediplan_import_bundle(emediplan_to_fhir_bundle(payload))
        bundle_body = json.dumps(bundle).encode("utf-8")
        return await _bridge_link_post(
            request,
            BRIDGELINK_EMEDIPLAN_IMPORT_URL,
            body=bundle_body,
            content_type="application/fhir+json",
            use_case="eMediplan QR import",
        )
    except HTTPException:
        raise
    except PatientMatchConflictError as ex:
        raise HTTPException(status_code=409, detail=str(ex)) from ex
    except FhirResourceMatchConflictError as ex:
        raise HTTPException(status_code=409, detail=str(ex)) from ex
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except (requests.RequestException, PatientLookupError, FhirDuplicateLookupError) as ex:
        logger.exception("FHIR preflight failed during eMediplan QR import")
        raise HTTPException(status_code=502, detail="FHIR preflight lookup unavailable") from ex
    except Exception as ex:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(ex))


@app.post("/echosos/qr")
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


@app.post("/card/analyze")
async def card_analyze(
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
        raise HTTPException(status_code=400, detail="No file or payload provided")

    try:
        return analyze_card(raw_bytes, content_type=content_type)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except Exception as ex:
        traceback.print_exc()
        raise HTTPException(status_code=502, detail=f"Card analysis failed: {ex}")


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
