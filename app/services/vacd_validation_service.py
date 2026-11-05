"""Additional read-only CH-VACD validation using the internal offline Husky engine."""

import json

import requests

from config import HUSKY_VALIDATOR_URL
from services.fhir_validation_service import is_valid_operation_outcome


MAX_VACD_BYTES = 5 * 1024 * 1024


class VacdValidationError(Exception):
    pass


def validate_vacd_husky(bundle: dict) -> tuple[int, dict]:
    if bundle.get("resourceType") != "Bundle" or bundle.get("type") != "document":
        raise ValueError("A CH-VACD document Bundle is required")
    payload = json.dumps(bundle, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(payload) > MAX_VACD_BYTES:
        raise ValueError("FHIR input exceeds 5 MiB")
    try:
        response = requests.post(
            f"{HUSKY_VALIDATOR_URL.rstrip('/')}/vacd/validate",
            data=payload,
            headers={"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"},
            timeout=(5, 120),
            allow_redirects=False,
        )
    except requests.RequestException as ex:
        raise VacdValidationError("Internal Husky VACD validator unavailable") from ex
    if response.status_code not in (200, 400, 413, 422):
        raise VacdValidationError(f"Internal Husky VACD validator returned HTTP {response.status_code}")
    try:
        outcome = response.json()
    except ValueError as ex:
        raise VacdValidationError("Internal Husky VACD validator returned invalid JSON") from ex
    if not is_valid_operation_outcome(outcome):
        raise VacdValidationError("Internal Husky VACD validator returned an invalid OperationOutcome")
    errors = any(issue["severity"] in ("error", "fatal") for issue in outcome["issue"])
    if response.status_code != 200 and not errors:
        raise VacdValidationError("Internal Husky VACD validator returned an inconsistent error outcome")
    return (422 if errors and response.status_code == 200 else response.status_code), outcome
