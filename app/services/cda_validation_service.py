"""Read-only CDA input validation against the internal Husky service."""

import requests

from config import HUSKY_VALIDATOR_URL
from services.fhir_validation_service import is_valid_operation_outcome


MAX_CDA_BYTES = 5 * 1024 * 1024


class CdaValidationError(Exception):
    pass


def validate_cda_source(xml_content: bytes, level: str = "full") -> tuple[int, dict]:
    if not xml_content:
        raise ValueError("CDA content required")
    if len(xml_content) > MAX_CDA_BYTES:
        raise ValueError("CDA exceeds 5 MiB")
    if level not in ("xsd", "full"):
        raise ValueError("Validation level must be xsd or full")
    try:
        response = requests.post(
            f"{HUSKY_VALIDATOR_URL.rstrip('/')}/validate",
            data=xml_content,
            headers={
                "Content-Type": "application/xml",
                "Accept": "application/fhir+json",
                "X-Validation-Level": level,
            },
            timeout=(5, 60),
            allow_redirects=False,
        )
    except requests.RequestException as ex:
        raise CdaValidationError("Internal Husky validator unavailable") from ex
    if response.status_code not in (200, 400, 413):
        raise CdaValidationError(f"Internal Husky validator returned HTTP {response.status_code}")
    try:
        outcome = response.json()
    except ValueError as ex:
        raise CdaValidationError("Internal Husky validator returned invalid JSON") from ex
    if not is_valid_operation_outcome(outcome):
        raise CdaValidationError("Internal Husky validator returned an invalid OperationOutcome")
    if response.status_code != 200 and not any(
        issue["severity"] in ("error", "fatal") for issue in outcome["issue"]
    ):
        raise CdaValidationError("Internal Husky validator returned an inconsistent error outcome")
    return response.status_code, outcome
