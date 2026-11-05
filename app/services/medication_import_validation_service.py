"""Fail-closed profile validation of the final medication import transaction."""

import copy
import logging

import requests
from fastapi import HTTPException

from config import FHIR_BASE
from services.fhir_validation_service import FhirValidationError, validate_fhir_bundle


logger = logging.getLogger(__name__)
MEDICATION_PROFILES = {
    "MedicationStatement": "ch-core-medicationstatement",
    "MedicationRequest": "ch-core-medicationrequest",
    "Medication": "ch-core-medication",
}


class MedicationImportRejected(HTTPException):
    def __init__(self, status_code, outcome):
        super().__init__(status_code=status_code, detail=outcome)
        self.outcome = outcome


def _reject(status, code, diagnostics):
    raise MedicationImportRejected(status, {
        "resourceType": "OperationOutcome",
        "issue": [{"severity": "error", "code": code, "diagnostics": diagnostics}],
    })


def _declared_profiles(value):
    profiles = set()
    if isinstance(value, dict):
        if "meta" in value:
            meta = value["meta"]
            if not isinstance(meta, dict) or not isinstance(meta.get("profile", []), list) \
                    or any(not isinstance(profile, str) or not profile for profile in meta.get("profile", [])):
                _reject(400, "invalid", "Invalid medication import profile declarations")
            profiles.update(meta.get("profile", []))
        for item in value.values():
            profiles.update(_declared_profiles(item))
    elif isinstance(value, list):
        for item in value:
            profiles.update(_declared_profiles(item))
    return profiles


def validate_medication_import(bundle: dict) -> dict:
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle" \
            or not isinstance(bundle.get("entry", []), list):
        _reject(400, "invalid", "Medication import requires a FHIR Bundle")
    for entry in bundle.get("entry", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("resource", {}), dict):
            _reject(400, "invalid", "Invalid medication import entry")
    resources = [
        entry.get("resource", {}) for entry in bundle.get("entry", [])
        if isinstance(entry, dict)
    ]
    if not any(resource.get("resourceType") in MEDICATION_PROFILES for resource in resources):
        return bundle
    if bundle.get("type") != "transaction":
        _reject(400, "invalid", "Medication import requires a transaction Bundle")
    _declared_profiles(bundle)
    final = copy.deepcopy(bundle)
    for entry in final.get("entry", []):
        resource = entry.get("resource", {})
        profile = MEDICATION_PROFILES.get(resource.get("resourceType"))
        if profile:
            profiles = resource.setdefault("meta", {}).setdefault("profile", [])
            canonical = f"http://fhir.ch/ig/ch-core/StructureDefinition/{profile}"
            if canonical not in profiles:
                profiles.append(canonical)
    profiles = _declared_profiles(final)
    try:
        for profile in sorted(profiles):
            canonical, separator, version = profile.partition("|")
            params = {"url": canonical, "_count": 1}
            if separator:
                params["version"] = version
            response = requests.get(
                f"{FHIR_BASE.rstrip('/')}/StructureDefinition",
                params=params, headers={"Accept": "application/fhir+json"},
                timeout=(5, 30), allow_redirects=False,
            )
            if response.status_code != 200:
                _reject(502, "exception", "Medication import blocked: profile registry unavailable")
            definitions = response.json()
            if not isinstance(definitions, dict) or definitions.get("resourceType") != "Bundle" \
                    or not isinstance(definitions.get("entry", []), list) \
                    or any(not isinstance(item, dict) or not isinstance(item.get("resource", {}), dict)
                           for item in definitions.get("entry", [])):
                _reject(502, "exception", "Medication import blocked: invalid profile registry response")
            if not any(
                item.get("resource", {}).get("resourceType") == "StructureDefinition"
                and item.get("resource", {}).get("url") == canonical
                and (not separator or item.get("resource", {}).get("version") == version)
                for item in definitions.get("entry", [])
            ):
                _reject(422, "not-supported", f"Medication import blocked: unknown profile {profile}")
        status, outcome = validate_fhir_bundle(final)
    except (requests.RequestException, FhirValidationError, ValueError) as ex:
        logger.error("Medication import validation unavailable: %s", type(ex).__name__)
        _reject(502, "exception", "Medication import blocked: internal profile validation unavailable")
    if status >= 400 or any(issue["severity"] in ("error", "fatal") for issue in outcome["issue"]):
        logger.warning("Medication import blocked by profile validation")
        raise MedicationImportRejected(422, outcome)
    logger.info("Medication import profile validation passed: warnings=%s",
                sum(issue["severity"] == "warning" for issue in outcome["issue"]))
    return final
