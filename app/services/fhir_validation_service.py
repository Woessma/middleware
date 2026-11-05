"""Read-only validation against the configured internal FHIR server."""

import requests

from config import FHIR_BASE


class FhirValidationError(Exception):
    pass


def is_valid_operation_outcome(outcome) -> bool:
    issues = outcome.get("issue") if isinstance(outcome, dict) else None
    return (
        isinstance(outcome, dict)
        and outcome.get("resourceType") == "OperationOutcome"
        and isinstance(issues, list)
        and bool(issues)
        and all(
            isinstance(issue, dict)
            and issue.get("severity") in ("fatal", "error", "warning", "information")
            and isinstance(issue.get("code"), str)
            and bool(issue["code"])
            for issue in issues
        )
    )


def validate_fhir_bundle(bundle: dict) -> tuple[int, dict]:
    if bundle.get("resourceType") != "Bundle":
        raise ValueError("A FHIR Bundle is required")
    try:
        response = requests.post(
            f"{FHIR_BASE.rstrip('/')}/Bundle/$validate",
            json=bundle,
            headers={
                "Content-Type": "application/fhir+json",
                "Accept": "application/fhir+json",
            },
            timeout=120,
            allow_redirects=False,
        )
    except requests.RequestException as ex:
        raise FhirValidationError("Internal FHIR validator unavailable") from ex

    if not (200 <= response.status_code < 300 or response.status_code in {400, 422}):
        raise FhirValidationError(
            f"Internal FHIR validator returned HTTP {response.status_code}"
        )
    try:
        outcome = response.json()
    except ValueError as ex:
        raise FhirValidationError("Internal FHIR validator returned invalid JSON") from ex
    if not is_valid_operation_outcome(outcome):
        raise FhirValidationError("Internal FHIR validator returned an invalid OperationOutcome")
    if response.status_code in {400, 422} and not any(
        issue["severity"] in {"error", "fatal"} for issue in outcome["issue"]
    ):
        raise FhirValidationError("Internal FHIR validator returned an inconsistent error outcome")
    return response.status_code, outcome
