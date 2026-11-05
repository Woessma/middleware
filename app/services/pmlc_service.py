"""Generate a read-only PMLC from one patient's active medication statements."""

import copy
import json
import re
import time
import uuid
from urllib.parse import urljoin, urlsplit

import requests

from config import FHIR_BASE, HUSKY_VALIDATOR_URL
from services.emediplan_service import _rewrite_reference_values
from services.fhir_validation_service import is_valid_operation_outcome


DOCUMENT_PROFILE = (
    "http://fhir.ch/ig/ch-emed-epr/StructureDefinition/"
    "ch-emed-epr-document-medicationcard|3.0.0"
)
MAX_RESOURCES = 1000
MAX_BYTES = 5 * 1024 * 1024
RESOURCE_TYPES = {
    "Patient", "MedicationStatement", "Medication", "PractitionerRole",
    "Practitioner", "Organization", "RelatedPerson", "Device", "Encounter",
}
RESOURCE_PATH = re.compile(
    r"^([A-Za-z]+)/([A-Za-z0-9.-]{1,64})(?:/_history/([A-Za-z0-9.-]{1,64}))?$"
)


class PmlcSourceError(Exception):
    """Source data cannot safely be turned into this patient's medication card."""


class PmlcServiceError(Exception):
    """Internal read/generation/validation failed."""


def _references(node):
    if isinstance(node, dict):
        reference = node.get("reference")
        if isinstance(reference, str):
            yield reference
        for value in node.values():
            yield from _references(value)
    elif isinstance(node, list):
        for value in node:
            yield from _references(value)


def _internal_url(url, base):
    target = urlsplit(urljoin(base + "/", url))
    allowed = urlsplit(base)
    if (
        target.scheme != allowed.scheme or target.netloc != allowed.netloc
        or target.username or target.password or target.fragment
        or not target.path.startswith(allowed.path.rstrip("/") + "/")
        or any(part in (".", "..") for part in target.path.split("/"))
        or "%" in target.path
    ):
        raise PmlcSourceError("FHIR source links must remain inside the internal FHIR base")
    return target.geturl()


def _get_json(url, deadline, **kwargs):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise PmlcServiceError("FHIR source read exceeded its time limit")
    try:
        response = requests.get(
            url, headers={"Accept": "application/fhir+json"},
            timeout=(5, min(30, remaining)), allow_redirects=False, **kwargs,
        )
    except requests.RequestException as ex:
        raise PmlcServiceError("Internal FHIR source unavailable") from ex
    if response.status_code == 404:
        raise PmlcSourceError("A required FHIR source resource was not found")
    if response.status_code != 200:
        raise PmlcServiceError(f"Internal FHIR source returned HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError as ex:
        raise PmlcServiceError("Internal FHIR source returned invalid JSON") from ex
    if not isinstance(body, dict):
        raise PmlcServiceError("Internal FHIR source returned an invalid resource")
    return body


def fetch_active_statement_source(patient_id: str) -> tuple[dict, str, int]:
    if not isinstance(patient_id, str) or not re.fullmatch(r"[A-Za-z0-9.-]{1,64}", patient_id):
        raise PmlcSourceError("A valid, explicit Patient ID is required")
    base = FHIR_BASE.rstrip("/")
    deadline = time.monotonic() + 60
    resources = {}
    aliases = {}
    statements = []

    def register(resource, full_url=None, reference=None):
        if not isinstance(resource, dict):
            raise PmlcServiceError("FHIR source contains a non-resource entry")
        kind, identifier = resource.get("resourceType"), resource.get("id")
        if kind not in RESOURCE_TYPES or not isinstance(identifier, str) \
                or not re.fullmatch(r"[A-Za-z0-9.-]{1,64}", identifier):
            raise PmlcSourceError("Unsupported or unidentified FHIR source resource")
        key = f"{kind}/{identifier}"
        if key in resources and resources[key] != resource:
            raise PmlcSourceError("FHIR source changed during pagination or reference resolution")
        resources[key] = copy.deepcopy(resource)
        aliases[key] = key
        aliases[f"{base}/{key}"] = key
        for alias in (full_url, reference):
            if alias:
                if alias in aliases and aliases[alias] != key:
                    raise PmlcSourceError("Ambiguous FHIR source fullUrl")
                aliases[alias] = key
        if len(resources) > MAX_RESOURCES:
            raise PmlcSourceError("Medication source exceeds 1000 resources; no partial plan was generated")
        return key

    patient_key = f"Patient/{patient_id}"
    patient = _get_json(f"{base}/{patient_key}", deadline)
    if patient.get("resourceType") != "Patient" or patient.get("id") != patient_id:
        raise PmlcSourceError("FHIR patient response does not match the selected patient")
    register(patient)
    url = f"{base}/MedicationStatement"
    params = {
        "subject": patient_key, "status": "active", "_count": 100,
        "_include": "MedicationStatement:medication",
    }
    visited = set()
    for _ in range(50):
        if url in visited:
            raise PmlcSourceError("FHIR pagination loop; no partial plan was generated")
        visited.add(url)
        page = _get_json(url, deadline, params=params)
        params = None
        if page.get("resourceType") != "Bundle" or page.get("type") != "searchset" \
                or not isinstance(page.get("entry", []), list):
            raise PmlcServiceError("FHIR medication search returned an invalid search Bundle")
        for entry in page.get("entry", []):
            if not isinstance(entry, dict):
                raise PmlcServiceError("Invalid FHIR search entry")
            resource = entry.get("resource")
            if isinstance(resource, dict) and resource.get("resourceType") == "OperationOutcome":
                raise PmlcServiceError("FHIR medication search returned an OperationOutcome")
            key = register(resource, entry.get("fullUrl"))
            if resource.get("resourceType") == "MedicationStatement":
                if resource.get("status") != "active" or resource.get("subject", {}).get("reference") \
                        not in (patient_key, f"{base}/{patient_key}"):
                    raise PmlcSourceError("FHIR search returned a non-active or other-patient statement")
                if key not in statements:
                    statements.append(key)
        links = page.get("link", [])
        if not isinstance(links, list) or any(not isinstance(link, dict) for link in links):
            raise PmlcServiceError("Invalid FHIR pagination links")
        following = [link.get("url") for link in links if link.get("relation") == "next"]
        if not following:
            break
        if len(following) != 1 or not isinstance(following[0], str) or not following[0]:
            raise PmlcServiceError("Invalid FHIR next-page link")
        url = _internal_url(following[0], base)
    else:
        raise PmlcSourceError("FHIR pagination exceeded 50 pages; no partial plan was generated")
    if not statements:
        raise PmlcSourceError("No active MedicationStatements found for the selected patient")

    selected = set()
    pending = [patient_key, *statements]
    while pending:
        key = pending.pop()
        if key in selected:
            continue
        selected.add(key)
        resource = resources[key]
        for reference in _references(resource):
            if reference.startswith("#"):
                if not any(item.get("id") == reference[1:] for item in resource.get("contained", [])
                           if isinstance(item, dict)):
                    raise PmlcSourceError("Unresolved contained reference in medication source")
                continue
            linked_key = aliases.get(reference)
            if linked_key is None:
                target = _internal_url(reference, base)
                path = target[len(base) + 1:]
                match = RESOURCE_PATH.fullmatch(path)
                if not match or match[1] not in RESOURCE_TYPES or match[1] == "MedicationStatement":
                    raise PmlcSourceError("Unsupported source reference; no incomplete plan was generated")
                linked = _get_json(target, deadline)
                if linked.get("resourceType") != match[1] or linked.get("id") != match[2]:
                    raise PmlcSourceError("FHIR reference response does not match its requested resource")
                linked_key = register(linked, reference=reference)
            if linked_key.startswith("Patient/") and linked_key != patient_key:
                raise PmlcSourceError("A source reference points to a different patient")
            if linked_key.startswith("MedicationStatement/") and linked_key not in statements:
                raise PmlcSourceError("A source reference introduces a non-selected medication statement")
            pending.append(linked_key)
    full_urls = {key: f"urn:uuid:{uuid.uuid4()}" for key in sorted(selected)}
    reference_map = {alias: full_urls[key] for alias, key in aliases.items() if key in selected}
    entries = []
    for key in sorted(selected):
        resource = resources[key]
        _rewrite_reference_values(resource, reference_map)
        entries.append({"fullUrl": full_urls[key], "resource": resource})
    return {"resourceType": "Bundle", "type": "collection", "entry": entries}, full_urls[patient_key], len(statements)


def generate_pmlc(patient_id: str, language="de-CH", confidentiality="restricted") -> dict:
    if language not in ("de-CH", "fr-CH", "it-CH") or confidentiality not in ("normal", "restricted", "secret"):
        raise PmlcSourceError("Unsupported language or confidentiality")
    source, patient_reference, count = fetch_active_statement_source(patient_id)
    requested_level = {"normal": 0, "restricted": 1, "secret": 2}[confidentiality]
    for entry in source["entry"]:
        for security in entry["resource"].get("meta", {}).get("security", []):
            system, code = security.get("system"), security.get("code")
            source_level = None
            if system in ("http://terminology.hl7.org/CodeSystem/v3-Confidentiality",
                          "http://hl7.org/fhir/v3/Confidentiality"):
                source_level = {"N": 0, "R": 1, "V": 2}.get(code)
            elif system == "http://snomed.info/sct":
                source_level = {"17621005": 0, "263856008": 1, "4554003": 2}.get(code)
            if source_level is not None and source_level > requested_level:
                raise PmlcSourceError("Requested document confidentiality would downgrade source confidentiality")
    payload = {
        "source": source, "patientReference": patient_reference,
        "language": language, "confidentiality": confidentiality,
    }
    if len(json.dumps(payload).encode("utf-8")) > MAX_BYTES:
        raise PmlcSourceError("Medication source exceeds 5 MiB; no partial plan was generated")
    try:
        response = requests.post(
            f"{HUSKY_VALIDATOR_URL.rstrip('/')}/emed/pmlc", json=payload,
            headers={"Accept": "application/json"}, timeout=(5, 120), allow_redirects=False,
        )
    except requests.RequestException as ex:
        raise PmlcServiceError("Internal Husky PMLC service unavailable") from ex
    if response.status_code == 400:
        raise PmlcSourceError("Internal Husky service rejected the medication source")
    if response.status_code != 200:
        raise PmlcServiceError(f"Internal Husky PMLC service returned HTTP {response.status_code}")
    try:
        result = response.json()
    except ValueError as ex:
        raise PmlcServiceError("Internal Husky PMLC service returned invalid JSON") from ex
    if not isinstance(result, dict) or result.get("status") not in ("validated", "invalid") \
            or not is_valid_operation_outcome(result.get("validation")):
        raise PmlcServiceError("Internal Husky PMLC service returned an invalid validation report")
    bundle = result.get("bundle")
    entries = bundle.get("entry") if isinstance(bundle, dict) else None
    meta = bundle.get("meta") if isinstance(bundle, dict) else None
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle" \
            or bundle.get("type") != "document" or not isinstance(entries, list) or not entries \
            or not isinstance(entries[0], dict) or not isinstance(entries[0].get("resource"), dict) \
            or entries[0]["resource"].get("resourceType") != "Composition" \
            or not isinstance(meta, dict) or not isinstance(meta.get("profile"), list) \
            or DOCUMENT_PROFILE not in meta["profile"]:
        raise PmlcServiceError("Internal Husky PMLC service returned an invalid document")
    has_errors = any(issue["severity"] in ("fatal", "error") for issue in result["validation"]["issue"])
    if has_errors != (result["status"] == "invalid"):
        raise PmlcServiceError("Internal Husky PMLC service returned an inconsistent validation status")
    result["source"] = {"patientId": patient_id, "activeMedicationStatements": count,
                        "medicationRequestsIncluded": False, "stored": False}
    return result
