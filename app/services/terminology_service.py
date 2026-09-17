import requests

from config import TERMINOLOGY_BASE_URL, TERMINOLOGY_TIMEOUT
from terminology.cvx import SYSTEM as CVX_SYSTEM, snomed_code_for_cvx


VALIDATABLE_SYSTEMS = {
    "http://loinc.org",
    "http://snomed.info/sct",
    "http://fhir.ch/ig/ch-vacd/CodeSystem/ch-vacd-swissmedic-cs",
}

FHIR_JSON_HEADERS = {
    "Accept": "application/fhir+json",
    "Content-Type": "application/fhir+json",
}

SUPPORTED_OPERATIONS = {
    "$expand",
    "$validate-code",
    "$lookup",
    "$translate",
    "$subsumes",
    "$closure",
}


def validate_coding(
    coding: dict,
    base_url: str = TERMINOLOGY_BASE_URL,
    timeout: int = TERMINOLOGY_TIMEOUT,
) -> dict:
    system = coding.get("system")
    code = coding.get("code")

    if not system or not code:
        return {"status": "skipped", "reason": "coding has no system or code"}

    if system == CVX_SYSTEM:
        snomed_code = snomed_code_for_cvx(code)
        if not snomed_code:
            return {
                "status": "skipped",
                "reason": "CVX has no internal SNOMED mapping",
            }

        mapped_coding = {
            "system": "http://snomed.info/sct",
            "code": snomed_code,
        }
        if coding.get("display"):
            mapped_coding["display"] = coding["display"]

        result = validate_coding(
            mapped_coding,
            base_url=base_url,
            timeout=timeout,
        )
        result["mapped_from"] = coding
        result["mapped_coding"] = mapped_coding
        return result

    if system not in VALIDATABLE_SYSTEMS:
        return {"status": "skipped", "reason": "system is not supported by tx.fhir.ch"}

    response = call_terminology_operation(
        "CodeSystem",
        "$lookup",
        {
            "resourceType": "Parameters",
            "parameter": [{"name": "coding", "valueCoding": coding}],
        },
        base_url=base_url,
        timeout=timeout,
    )
    return {"status": "validated", "result": response.json()}


def _lookup_display(
    coding: dict,
    base_url: str = TERMINOLOGY_BASE_URL,
    timeout: int = TERMINOLOGY_TIMEOUT,
) -> dict:
    system = coding.get("system")
    code = coding.get("code")

    if not system or not code:
        return {"status": "skipped", "reason": "coding has no system or code"}

    if system not in VALIDATABLE_SYSTEMS:
        return {"status": "skipped", "reason": "system is not supported by tx.fhir.ch"}

    response = call_terminology_operation(
        "CodeSystem",
        "$lookup",
        {
            "resourceType": "Parameters",
            "parameter": [{"name": "coding", "valueCoding": coding}],
        },
        base_url=base_url,
        timeout=timeout,
    )

    parameters = response.json().get("parameter", [])

    for parameter in parameters:
        if parameter.get("name") == "display" and parameter.get("valueString"):
            return {
                "status": "enriched",
                "display": parameter["valueString"],
            }

    for parameter in parameters:
        if parameter.get("name") == "name" and parameter.get("valueString"):
            return {
                "status": "enriched",
                "display": parameter["valueString"],
            }

    return {"status": "skipped", "reason": "lookup returned no display"}


def enrich_bundle_terminology(
    bundle: dict,
    base_url: str = TERMINOLOGY_BASE_URL,
    timeout: int = TERMINOLOGY_TIMEOUT,
) -> dict:
    results = []
    display_cache = {}
    enriched = 0

    def visit(value, path):
        nonlocal enriched

        if isinstance(value, dict):
            if "system" in value and "code" in value:
                system = value.get("system")
                code = value.get("code")
                coding_key = (system, code)

                if not value.get("display"):
                    if coding_key in display_cache:
                        display = display_cache[coding_key]

                        if display:
                            value["display"] = display
                            enriched += 1
                            results.append({
                                "path": path,
                                "coding": value,
                                "status": "enriched_from_cache",
                                "display": display,
                            })
                    else:
                        try:
                            result = _lookup_display(value, base_url=base_url, timeout=timeout)
                        except requests.RequestException as exc:
                            result = {"status": "unavailable", "reason": str(exc)}

                        display = result.get("display")
                        display_cache[coding_key] = display

                        if display:
                            value["display"] = display
                            enriched += 1

                        results.append({"path": path, "coding": value, **result})

            for key, child in value.items():
                visit(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(bundle, "Bundle")
    return {
        "status": "ok" if all(item["status"] in {"enriched", "enriched_from_cache", "skipped"} for item in results) else "issues",
        "enriched": enriched,
        "checked": len(results),
        "results": results,
    }


def validate_bundle_terminology(
    bundle: dict,
    base_url: str = TERMINOLOGY_BASE_URL,
    timeout: int = TERMINOLOGY_TIMEOUT,
) -> dict:
    results = []
    seen = set()

    def visit(value, path):
        if isinstance(value, dict):
            if "system" in value and "code" in value:
                coding_key = (value.get("system"), value.get("code"))
                if coding_key not in seen:
                    seen.add(coding_key)
                    try:
                        result = validate_coding(value, base_url=base_url, timeout=timeout)
                    except requests.RequestException as exc:
                        result = {"status": "unavailable", "reason": str(exc)}
                    results.append({"path": path, "coding": value, **result})
            for key, child in value.items():
                visit(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(bundle, "Bundle")
    return {
        "status": "ok" if all(item["status"] in {"validated", "skipped"} for item in results) else "issues",
        "checked": len(results),
        "results": results,
    }


def call_terminology_operation(
    resource_type: str,
    operation: str,
    parameters: dict,
    base_url: str = TERMINOLOGY_BASE_URL,
    timeout: int = TERMINOLOGY_TIMEOUT,
) -> requests.Response:
    if resource_type not in {"ValueSet", "CodeSystem", "ConceptMap"}:
        raise ValueError("Unsupported terminology resource type")
    if operation not in SUPPORTED_OPERATIONS:
        raise ValueError("Unsupported terminology operation")

    response = requests.post(
        f"{base_url.rstrip('/')}/{resource_type}/{operation}",
        json=parameters,
        headers=FHIR_JSON_HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()
    return response