import copy
import json

import requests

from config import FHIR_BASE


class FhirResourceMatchConflictError(ValueError):
    pass


class FhirDuplicateLookupError(RuntimeError):
    pass


def find_existing_resource_by_identifier(resource: dict, fhir_base: str = FHIR_BASE):
    resource_type = resource.get("resourceType")
    if not resource_type:
        raise ValueError("resourceType is required")

    identifiers = resource.get("identifier") or []
    if isinstance(identifiers, dict):
        identifiers = [identifiers]

    matches = {}
    searches = [
        ("identifier", identifier.get("system"), identifier.get("value"))
        for identifier in identifiers
        if isinstance(identifier, dict)
        and identifier.get("system")
        and identifier.get("value")
    ]
    if resource_type == "Medication":
        code = resource.get("code") or {}
        codings = code.get("coding") or [] if isinstance(code, dict) else []
        if isinstance(codings, dict):
            codings = [codings]
        product_code_systems = {
            "https://emediplan.ch/fhir/NamingSystem/pharmacode",
            "urn:epc:id:sgtin",
        }
        searches.extend(
            ("code", coding.get("system"), coding.get("code"))
            for coding in codings
            if isinstance(coding, dict)
            and coding.get("system") in product_code_systems
            and coding.get("system")
            and coding.get("code")
        )

    for parameter, system, value in searches:
        if not system or not value:
            continue

        response = requests.get(
            f"{fhir_base.rstrip('/')}/{resource_type}",
            params={parameter: f"{system}|{value}", "_count": "2"},
            headers={"Accept": "application/fhir+json"},
            timeout=60,
        )
        response.raise_for_status()
        bundle = response.json()
        if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
            raise FhirDuplicateLookupError(
                f"{resource_type} identifier search returned no FHIR Bundle"
            )

        entries = bundle.get("entry") or []
        if not isinstance(entries, list):
            raise FhirDuplicateLookupError(
                f"{resource_type} identifier search returned invalid entries"
            )
        found = [
            entry["resource"]
            for entry in entries
            if isinstance(entry, dict)
            and isinstance(entry.get("resource"), dict)
            and entry["resource"].get("resourceType") == resource_type
        ]
        total = bundle.get("total", len(found))
        if not isinstance(total, int):
            total = len(found)
        if total > 1 or len(found) > 1:
            raise FhirResourceMatchConflictError(
                f"{resource_type} identifier {system}|{value} is not unique"
            )
        if found:
            resource_id = found[0].get("id")
            if not resource_id:
                raise FhirDuplicateLookupError(
                    f"Existing {resource_type} resource has no id"
                )
            matches[resource_id] = found[0]

    if len(matches) > 1:
        raise FhirResourceMatchConflictError(
            f"{resource_type} identifiers match different existing resources"
        )
    return next(iter(matches.values())) if matches else None


def _resource_signature(resource: dict) -> str:
    normalized = copy.deepcopy(resource)
    normalized.pop("id", None)
    normalized.pop("meta", None)

    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _fetch_page(resource_type: str, params: dict, base_url: str):
    response = requests.get(
        f"{base_url.rstrip('/')}/{resource_type}",
        params=params,
        headers={"Accept": "application/fhir+json"},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def find_exact_fhir_duplicates(
    resource_type: str = "MedicationStatement",
    patient_id: str | None = None,
    fhir_base: str = FHIR_BASE,
    count: int = 200,
):
    fhir_base = fhir_base or FHIR_BASE

    if not resource_type:
        raise ValueError("resource_type is required")

    params = {"_count": str(count)}

    if patient_id:
        params["patient"] = patient_id

    resources = []
    next_url = None

    while True:
        if next_url:
            response = requests.get(
                next_url,
                headers={"Accept": "application/fhir+json"},
                timeout=60,
            )
            response.raise_for_status()
            bundle = response.json()
        else:
            bundle = _fetch_page(resource_type, params, fhir_base)

        for entry in bundle.get("entry", []) or []:
            resource = entry.get("resource") or {}

            if resource.get("resourceType") == resource_type:
                resources.append(resource)

        next_url = None
        for link in bundle.get("link", []) or []:
            if link.get("relation") == "next" and link.get("url"):
                next_url = link["url"]
                break

        if not next_url:
            break

    grouped = {}
    for resource in resources:
        signature = _resource_signature(resource)
        grouped.setdefault(signature, []).append(resource)

    duplicates = []
    for signature, items in grouped.items():
        if len(items) < 2:
            continue

        duplicates.append(
            {
                "signature": signature,
                "count": len(items),
                "ids": [item.get("id") for item in items if item.get("id")],
            }
        )

    duplicates.sort(key=lambda item: (-item["count"], item["ids"][0] if item["ids"] else ""))

    return {
        "resourceType": resource_type,
        "patientId": patient_id,
        "count": len(resources),
        "duplicateGroups": duplicates,
    }